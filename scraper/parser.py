"""
スポナビ 一球速報パーサー
==========================
1打席ぶんのHTML（.../score?index=RRTBBPP）から
球種・球速・結果・コース座標を抜き出す。

Seleniumは不要。requests + BeautifulSoup だけで動く。
"""

import re
from bs4 import BeautifulSoup


# ゾーン変換用の定数（配球図エリアの実測ピクセル）
# ballCircle の top/left は 0〜約63px の範囲に分布する。
# これを 5x5 グリッド（中央3x3がストライクゾーン）に近似変換する。
_CHART_SIZE = 63.0  # 配球図エリアの一辺(px)の目安


def _to_zone(top_px: float | None, left_px: float | None) -> dict:
    """
    コースのピクセル座標を、人が読める位置情報に変換する。
    - grid: 5x5マスのどこか（0-4）。中央寄り3x3がおおよそストライクゾーン
    - label: 高さ(高め/真ん中/低め) × 横(内/中/外) の言葉  ※投手視点の左右
    座標が無い場合は None を返す。
    """
    if top_px is None or left_px is None:
        return {"grid_row": None, "grid_col": None, "label": None}

    # 0〜4 の5分割に量子化
    row = min(4, max(0, int(top_px / (_CHART_SIZE / 5))))   # 0=上(高め)
    col = min(4, max(0, int(left_px / (_CHART_SIZE / 5))))  # 0=左

    height = ["高め", "高め", "真ん中", "低め", "低め"][row]
    side = ["外", "外", "真ん中", "内", "内"][col]
    label = f"{height}・{side}"
    return {"grid_row": row, "grid_col": col, "label": label}


def _parse_players(soup):
    """打者・投手の名前・選手ID・背番号・投打を取得"""
    import re as _re
    players = {"batter": None, "pitcher": None}
    html = str(soup)
    for key, label in [("batter", "打者"), ("pitcher", "投手")]:
        i = html.find(f"<em>{label}</em>")
        if i < 0:
            continue
        block = html[i:i + 900]
        pid = _re.search(r"/npb/player/(\d+)/", block)
        name = _re.search(r'alt="([^"]+)"', block)
        no = _re.search(r'class="playerNo">#?(\d+)</span>', block)
        hand = _re.search(r'class="dominantHand">([^<]+)<', block)
        players[key] = {
            "name": name.group(1).strip() if name else None,
            "player_id": pid.group(1) if pid else None,
            "number": no.group(1) if no else None,
            "hand": hand.group(1).strip() if hand else None,
        }
    return players


def _parse_runners(html: str) -> dict:
    """
    ランナー状況を取得する。
    <div id="base" class="b000"> の3桁が [一塁, 二塁, 三塁] に対応。
    b000=無走者 / b100=一塁 / b110=一二塁 / b111=満塁 …
    """
    import re as _re
    m = _re.search(r'id="base" class="b(\d)(\d)(\d)"', html)
    if not m:
        return {"first": False, "second": False, "third": False, "code": None, "label": None}
    first = m.group(1) == "1"
    second = m.group(2) == "1"
    third = m.group(3) == "1"

    on = []
    if first:
        on.append("一塁")
    if second:
        on.append("二塁")
    if third:
        on.append("三塁")
    label = "・".join(on) if on else "走者なし"
    if first and second and third:
        label = "満塁"

    return {
        "first": first, "second": second, "third": third,
        "code": f"b{m.group(1)}{m.group(2)}{m.group(3)}",
        "label": label,
    }


# ボール種別クラス → 意味
# 実データ（40打席）の検証結果に基づく対応
_BALL_KIND = {
    "ball1": "strike",   # ファウル・見逃し・空振り（ストライク系）
    "ball2": "ball",     # ボール
    "ball3": "out",      # 打って凡退（ゴロ・フライ）
    "ball4": "hit",      # 打って安打・本塁打
    "ball5": "bunt",     # 犠打など
}


def _parse_ball_kinds(html: str) -> list[str]:
    """各投球のボール種別クラス（ball1〜ball5）を出現順に返す"""
    import re as _re
    return _re.findall(r"bb-icon__ballCircle--(\w+)", html)


def _count_bso(pitches: list[dict]) -> dict:
    """
    投球結果テキストから、打席終了時点のボール・ストライクカウントを数える。
    ストライクは2つまで（3つ目は三振で打席終了）というルールを反映。
    """
    b = s = 0
    for p in pitches:
        r = p.get("result") or ""
        if not r:
            continue
        if "ボール" in r or "四球" in r:
            b = min(4, b + 1)
        elif "ファウル" in r:
            s = min(2, s + 1)  # ファウルは2ストライクまで
        elif "見逃し" in r or "空振り" in r or "ストライク" in r:
            s = min(3, s + 1)
    return {"ball": min(b, 3), "strike": min(s, 2)}


# 打球方向（結果テキストの先頭文字から判定するのが最も確実）
_DIRECTION = {
    "投": "ピッチャー", "捕": "キャッチャー", "一": "ファースト",
    "二": "セカンド", "三": "サード", "遊": "ショート",
    "左": "レフト", "中": "センター", "右": "ライト",
}
# 描画用のおおよその座標（0-100の相対位置。中央下がホーム）
_DIR_POS = {
    "投": (50, 58), "捕": (50, 88), "一": (68, 62), "二": (60, 46),
    "三": (32, 62), "遊": (40, 46), "左": (22, 24), "中": (50, 14),
    "右": (78, 24),
}


def _parse_hit_direction(result_summary: str | None, html: str) -> dict:
    """
    打球方向を判定する。
    結果テキストの先頭（遊ゴロ→遊、中安打→中）が最も確実なので、それを主に使う。
    dakyuコードは参考情報として一緒に保存する。
    """
    import re as _re
    dm = _re.search(r'id="dakyu" class="(\w+)"', html)
    dakyu = dm.group(1) if dm else None

    if not result_summary:
        return {"dir": None, "dir_name": None, "x": None, "y": None, "dakyu": dakyu}

    head = result_summary[0]
    if head not in _DIRECTION:
        # 「空振り三振」「四球」など打球が無いケース
        return {"dir": None, "dir_name": None, "x": None, "y": None, "dakyu": dakyu}

    x, y = _DIR_POS[head]
    return {
        "dir": head,
        "dir_name": _DIRECTION[head],
        "x": x, "y": y,
        "dakyu": dakyu,
    }


def parse_atbat(html: str, index: str) -> dict:
    """1打席ぶんのHTMLをパースして辞書で返す"""
    soup = BeautifulSoup(html, "html.parser")

    # --- 打席結果サマリ ---
    result_summary = None
    result_detail = None
    rdiv = soup.find("div", id="result")
    if rdiv:
        span = rdiv.find("span")
        em = rdiv.find("em")
        result_summary = span.get_text(strip=True) if span else None
        result_detail = em.get_text(strip=True) if em else None

    # --- 投球明細（球種・球速・結果） ---
    pitches = []
    for tr in soup.find_all("tr"):
        bt = tr.find("td", class_="bb-splitsTable__data--ballType")
        if not bt:
            continue
        sp = tr.find("td", class_="bb-splitsTable__data--speed")
        rs = tr.find("td", class_="bb-splitsTable__data--result")
        num_td = tr.find("td", class_="bb-splitsTable__data")
        num = num_td.get_text(strip=True) if num_td else ""
        speed_txt = sp.get_text(strip=True) if sp else ""
        speed = int(re.sub(r"\D", "", speed_txt)) if re.search(r"\d", speed_txt) else None
        pitches.append({
            "no": int(num) if num.isdigit() else None,
            "type": bt.get_text(strip=True),
            "speed_kmh": speed,
            "result": rs.get_text(strip=True) if rs else None,
        })

    # --- コース座標（ballCircle） ---
    # 同じ番号が複数箇所に出るため、no をキーに最初の1つを採用
    courses = {}
    for span in soup.find_all("span", class_="bb-icon__ballCircle"):
        style = span.get("style", "")
        top = re.search(r"top:\s*([\d.]+)px", style)
        left = re.search(r"left:\s*([\d.]+)px", style)
        numspan = span.find("span", class_="bb-icon__number")
        no = numspan.get_text(strip=True) if numspan else ""
        if not no.isdigit():
            continue
        no = int(no)
        if no in courses:
            continue
        top_px = float(top.group(1)) if top else None
        left_px = float(left.group(1)) if left else None
        courses[no] = {"top_px": top_px, "left_px": left_px, **_to_zone(top_px, left_px)}

    # --- 投球明細にコースを結合 ---
    for p in pitches:
        c = courses.get(p["no"])
        if c:
            p["course"] = c

    # --- 各投球にボール種別（ストライク/ボール/打球）を紐付け ---
    kinds = _parse_ball_kinds(html)
    for i, p in enumerate(pitches):
        if i < len(kinds):
            p["kind"] = _BALL_KIND.get(kinds[i], kinds[i])

    players = _parse_players(soup)
    is_top = len(index) >= 3 and index[2] == "1"

    # 打席が存在するかの判定
    valid = bool(players["batter"] and players["batter"].get("name"))
    if result_summary and "試合前" in result_summary:
        valid = False

    return {
        "index": index,
        "inning": int(index[0:2]) if len(index) >= 2 else None,
        "top_bottom": "表" if is_top else "裏",
        "order": int(index[3:5]) if len(index) >= 5 else None,
        "valid": valid,
        "batter": players["batter"],
        "pitcher": players["pitcher"],
        "runners": _parse_runners(html),
        "count": _count_bso(pitches),
        "hit_direction": _parse_hit_direction(result_summary, html),
        "result_summary": result_summary,
        "result_detail": result_detail,
        "pitch_count": len(pitches),
        "pitches": pitches,
    }


def extract_atbat_indexes(html: str) -> list[str]:
    """試合ページ内に載っている全打席のindex一覧を取得（重複除去・昇順）"""
    idxs = sorted(set(re.findall(r"score\?index=(\d+)", html)))
    return idxs


# 正式名称 → 短縮名の対応表
TEAM_SHORT = {
    "福岡ソフトバンクホークス": "ソフトバンク",
    "東北楽天ゴールデンイーグルス": "楽天",
    "北海道日本ハムファイターズ": "日本ハム",
    "千葉ロッテマリーンズ": "ロッテ",
    "埼玉西武ライオンズ": "西武",
    "オリックス・バファローズ": "オリックス",
    "読売ジャイアンツ": "巨人",
    "阪神タイガース": "阪神",
    "中日ドラゴンズ": "中日",
    "広島東洋カープ": "広島",
    "東京ヤクルトスワローズ": "ヤクルト",
    "横浜DeNAベイスターズ": "DeNA",
}


def parse_teams(html: str) -> dict:
    """
    <title>から対戦カードを取得する。
    例: 「…東北楽天…vs.福岡ソフトバンク… 一球速報 …」
        → {away:楽天, home:ソフトバンク, ...}
    先攻(away)＝vsの前、後攻(home)＝vsの後。
    """
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    if not m:
        return {"away": None, "home": None, "away_full": None, "home_full": None, "date_text": None}
    title = m.group(1)

    # 日付テキスト（例: 2026年5月15日）
    dm = re.search(r"(\d{4}年\d{1,2}月\d{1,2}日)", title)
    date_text = dm.group(1) if dm else None

    vm = re.search(r"(\S+?)vs\.?(\S+?)\s*一球速報", title)
    if not vm:
        return {"away": None, "home": None, "away_full": None, "home_full": None, "date_text": date_text}

    away_full = vm.group(1).strip()
    home_full = vm.group(2).strip()
    return {
        "away": TEAM_SHORT.get(away_full, away_full),
        "home": TEAM_SHORT.get(home_full, home_full),
        "away_full": away_full,
        "home_full": home_full,
        "date_text": date_text,
    }
