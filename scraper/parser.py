"""
スポナビ 一球速報パーサー
==========================
1打席ぶんのHTML（.../score?index=RRTBBPP）から
球種・球速・結果・コース座標を抜き出す。

Seleniumは不要。requests + BeautifulSoup だけで動く。
"""

import re
from bs4 import BeautifulSoup

# チーム名の正規化（順位表の判定に使う）
try:
    from lib.normalize import normalize_team, team_info
except ImportError:  # 単体実行時のフォールバック
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from lib.normalize import normalize_team, team_info


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


# チーム名 → 1文字略称
TEAM_MINI = {
    "日本ハム": "日", "楽天": "楽", "西武": "西", "ロッテ": "ロ",
    "オリックス": "オ", "ソフトバンク": "ソ", "巨人": "巨",
    "ヤクルト": "ヤ", "DeNA": "De", "中日": "中", "阪神": "神", "広島": "広",
}


def parse_score_list(html: str) -> list[dict]:
    """
    試合ページ内の「その日の日程・結果」一覧から、
    全試合のスコア・勝敗投手・セーブを取得する。

    1ページで6試合ぶん取れるので、日別サマリの作成に使える。
    """
    soup = BeautifulSoup(html, "html.parser")
    games = []
    for it in soup.select("li.bb-scoreList__item"):
        hn = it.select_one(".bb-scoreList__home .bb-scoreList__teamName")
        an = it.select_one(".bb-scoreList__away .bb-scoreList__teamName")
        hs = it.select_one(".bb-scoreList__homeScore")
        as_ = it.select_one(".bb-scoreList__awayScore")
        st = it.select_one(".bb-scoreList__state")

        home = hn.get_text(strip=True) if hn else None
        away = an.get_text(strip=True) if an else None
        if not home or not away:
            continue

        def pitchers(sel):
            out = {}
            for x in it.select(sel + " .bb-scoreList__player"):
                t = x.get_text(strip=True)
                m = re.match(r"[（(]([^）)]+)[）)](.+)", t)
                if not m:
                    continue
                mark, name = m.group(1), m.group(2).strip()
                if "勝" in mark:
                    out["win"] = name
                elif "敗" in mark:
                    out["lose"] = name
                elif "Ｓ" in mark or "S" in mark:
                    out["save"] = name
            return out

        hp = pitchers(".bb-scoreList__homePlayer")
        ap = pitchers(".bb-scoreList__awayPlayer")

        gid = None
        if st and st.get("href"):
            gm = re.search(r"/npb/game/(\d+)/", st["href"])
            gid = gm.group(1) if gm else None

        merged = {}
        merged.update(hp)
        merged.update(ap)

        games.append({
            "game_id": gid,
            "home": home,
            "away": away,
            "home_mini": TEAM_MINI.get(home, home),
            "away_mini": TEAM_MINI.get(away, away),
            "home_score": int(hs.get_text(strip=True)) if hs and hs.get_text(strip=True).isdigit() else None,
            "away_score": int(as_.get_text(strip=True)) if as_ and as_.get_text(strip=True).isdigit() else None,
            "state": st.get_text(strip=True) if st else None,
            "win_pitcher": merged.get("win"),
            "lose_pitcher": merged.get("lose"),
            "save_pitcher": merged.get("save"),
        })
    return games


def parse_homeruns(html: str) -> list[dict]:
    """
    試合ページの「本塁打」欄から、打者名・号数・詳細を取得する。
    例: 「柳田 4号(7回表ソロ) 正木 1号(7回表ソロ)」→ 3本に分解

    ※ th の直後の tbody 内だけを見る（広く探すとベンチ入り選手まで拾うため）
    """
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for th in soup.select("th.bb-splitsTable__head--homeRun"):
        tbody = th.find_parent("tbody")
        if not tbody:
            continue
        for td in tbody.select("td.bb-splitsTable__data"):
            text = " ".join(td.get_text(" ", strip=True).split())
            # 「名前 N号(詳細)」の繰り返しを個別に切り出す
            for m in re.finditer(r"([^\s\d]+(?:\s[^\s\d]+)?)\s*(\d+)\s*号\s*[（(]([^）)]*)[）)]", text):
                out.append({
                    "batter": m.group(1).strip(),
                    "number": int(m.group(2)),
                    "detail": m.group(3),
                })
    return out


def parse_battery(html: str) -> dict:
    """両チームのバッテリー（投手 - 捕手）を取得する。

    スポナビの試合ページではホーム、ビジターの順に同じ見出しが
    2回現れる。従来は最初の1件で return していたため、ホーム側しか
    保存されていなかった。既存データとの互換用に ``text`` も残す。
    """
    soup = BeautifulSoup(html, "html.parser")
    texts = []
    for th in soup.select("th.bb-splitsTable__head--battery"):
        table = th.find_parent("tbody") or th.find_parent("table")
        if not table:
            continue
        td = table.select_one("td.bb-splitsTable__data")
        if td:
            text = " ".join(td.get_text(" ", strip=True).split())
            if text:
                texts.append(text)
    if not texts:
        return {}

    out = {"text": texts[0], "home": texts[0]}
    if len(texts) > 1:
        out["away"] = texts[1]
    return out


def _to_int(s, default=0):
    """文字列を整数に変換（空文字や'-'は既定値）"""
    if s is None:
        return default
    s = str(s).strip().replace(",", "")
    if not s or s in ("-", "―", "‐"):
        return default
    m = re.match(r"-?\d+", s)
    return int(m.group(0)) if m else default


def _to_float(s, default=None):
    """打率・防御率など小数の変換（'-'やnullは既定値）"""
    if s is None:
        return default
    s = str(s).strip()
    if not s or s in ("-", "―", "‐", "----", "-.---"):
        return default
    try:
        return float(s)
    except ValueError:
        return default


def innings_to_outs(ip: str) -> int:
    """
    投球回の表記をアウト数に変換する。
    「5」→15アウト、「3.1」→10アウト（3回1/3）、「1.2」→5アウト（1回2/3）
    """
    if ip is None:
        return 0
    s = str(ip).strip()
    if not s or s in ("-", "―"):
        return 0
    if "." in s:
        whole, frac = s.split(".", 1)
        return _to_int(whole) * 3 + _to_int(frac)
    return _to_int(s) * 3


def outs_to_innings(outs: int) -> str:
    """アウト数を投球回表記に戻す（10 → '3.1'）"""
    return f"{outs // 3}.{outs % 3}" if outs % 3 else str(outs // 3)


def parse_stats_page(html: str) -> dict:
    """
    出場成績ページ（/npb/game/{id}/stats）から
    打撃成績・投手成績・スコアボードを取得する。

    公式の集計値なので、打席結果からの推定より正確。
    テーブル構造（実データで確認済み）:
      打撃: 位置・選手名・打率・打数・得点・安打・打点・三振・四球・死球・
            犠打・盗塁・失策・本塁打
      投手: 勝敗・選手名・防御率・投球回・投球数・打者・被安打・被本塁打・
            奪三振・与四球・与死球・ボーク・失点・自責点
    """
    soup = BeautifulSoup(html, "html.parser")

    result = {
        "scoreboard": None,
        "batting": {"home": [], "away": []},
        "pitching": {"home": [], "away": []},
    }

    # --- スコアボード（イニング別得点・計・安・失） ---
    sb = soup.select_one("table.bb-gameScoreTable")
    if sb:
        rows = []
        for tr in sb.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) > 3 and cells[0]:
                rows.append(cells)
        if len(rows) >= 2:
            def parse_sb_row(c):
                # 末尾3つが 計・安・失
                return {
                    "team": c[0],
                    "innings": [None if x in ("", "-", "X", "x") else _to_int(x)
                                for x in c[1:-3]],
                    "runs": _to_int(c[-3]),
                    "hits": _to_int(c[-2]),
                    "errors": _to_int(c[-1]),
                }
            # 上段=away（先攻）、下段=home（後攻）
            result["scoreboard"] = {
                "away": parse_sb_row(rows[0]),
                "home": parse_sb_row(rows[1]),
            }

    # --- 打撃成績（bb-statsTable が2つ：先攻・後攻の順） ---
    # 位置が「(遊)」のように括弧付き＝スタメン、「走指」「左」など括弧なし＝交代選手。
    # 交代選手は直前のスタメンの打順を引き継ぐ（表の並びがそのまま打順）。
    bat_tables = soup.select("table.bb-statsTable")
    bat_sides = ["away", "home"]
    for i, t in enumerate(bat_tables[:2]):
        side = bat_sides[i] if i < len(bat_sides) else f"t{i}"
        players = []
        order = 0
        for tr in t.find_all("tr"):
            trcls = " ".join(tr.get("class", []))
            if "--total" in trcls:      # チーム合計の行は選手ではない
                continue
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) < 14:
                continue
            name = cells[1]
            if not name:
                continue

            pos_raw = cells[0].strip()
            is_starter = pos_raw.startswith("(") or pos_raw.startswith("（")
            pos = pos_raw.strip("()（）")
            if is_starter:
                order += 1

            # 交代の種類（先頭文字で判別）
            sub_type = None
            if not is_starter:
                if pos.startswith("打"):
                    sub_type = "代打"
                elif pos.startswith("走"):
                    sub_type = "代走"
                else:
                    sub_type = "守備"

            link = tr.find("a", href=re.compile(r"/npb/player/\d+"))
            pid = None
            if link:
                m = re.search(r"/npb/player/(\d+)", link["href"])
                pid = m.group(1) if m else None
            players.append({
                "order": order if order else None,
                "position": pos,
                "position_raw": pos_raw,
                "is_starter": is_starter,
                "sub_type": sub_type,
                "name": name,
                "player_id": pid,
                "season_avg": _to_float(cells[2]),
                "ab": _to_int(cells[3]),
                "runs": _to_int(cells[4]),
                "hits": _to_int(cells[5]),
                "rbi": _to_int(cells[6]),
                "so": _to_int(cells[7]),
                "bb": _to_int(cells[8]),
                "hbp": _to_int(cells[9]),
                "sac": _to_int(cells[10]),
                "sb": _to_int(cells[11]),
                "errors": _to_int(cells[12]),
                "hr": _to_int(cells[13]),
            })
        result["batting"][side] = players

    # --- 投手成績（bb-scoreTable が2つ） ---
    pit_tables = soup.select("table.bb-scoreTable")
    for i, t in enumerate(pit_tables[:2]):
        side = bat_sides[i] if i < len(bat_sides) else f"t{i}"
        pitchers = []
        for tr in t.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(cells) < 14:
                continue
            name = cells[1]
            if not name:
                continue
            link = tr.find("a", href=re.compile(r"/npb/player/\d+"))
            pid = None
            if link:
                m = re.search(r"/npb/player/(\d+)", link["href"])
                pid = m.group(1) if m else None
            ip = cells[3]
            pitchers.append({
                "decision": cells[0],          # 勝・敗・S など
                "name": name,
                "player_id": pid,
                "season_era": _to_float(cells[2]),
                "innings": ip,
                "outs": innings_to_outs(ip),
                "pitches": _to_int(cells[4]),
                "batters_faced": _to_int(cells[5]),
                "hits_allowed": _to_int(cells[6]),
                "hr_allowed": _to_int(cells[7]),
                "so": _to_int(cells[8]),
                "bb": _to_int(cells[9]),
                "hbp": _to_int(cells[10]),
                "balk": _to_int(cells[11]),
                "runs_allowed": _to_int(cells[12]),
                "earned_runs": _to_int(cells[13]),
            })
        result["pitching"][side] = pitchers

    return result


def _parse_bso(html: str) -> dict | None:
    """
    公式のB/S/Oカウントを取得する。
    <div class="sbo"> 内の ● の数がそのままカウント。
    <p class="b"><em>B</em><b>●●●</b></p> → ボール3
    """
    import re as _re
    m = _re.search(
        r'class="sbo".*?class="b">.*?<b>([^<]*)</b>.*?class="s">.*?<b>([^<]*)</b>.*?class="o">.*?<b>([^<]*)</b>',
        html, _re.S,
    )
    if not m:
        return None
    return {
        "ball": m.group(1).count("●"),
        "strike": m.group(2).count("●"),
        "out": m.group(3).count("●"),
    }


# スポナビの1文字チーム略称
TEAM_ABBR = {
    "巨": "巨人", "神": "阪神", "中": "中日", "広": "広島",
    "ヤ": "ヤクルト", "デ": "DeNA", "ソ": "ソフトバンク", "日": "日本ハム",
    "ロ": "ロッテ", "楽": "楽天", "西": "西武", "オ": "オリックス",
}


def _parse_score_line(html: str) -> list[dict]:
    """
    ページ内のミニスコア（公式の得点）を取得する。
    <td class="nm act">ソ</td><td>3</td> のような行が2つ並ぶ。
    act が付いている方が攻撃中のチーム。
    """
    import re as _re
    rows = _re.findall(
        r'<td class="nm( act)?">([^<]+)</td>\s*<td>(\d+)</td>', html
    )
    out = []
    for act, abbr, score in rows:
        abbr = abbr.strip()
        out.append({
            "abbr": abbr,
            "team": TEAM_ABBR.get(abbr, abbr),
            "score": int(score),
            "batting": bool(act),
        })
    return out


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

    # カウント：公式のsbo表示を優先、無ければ投球結果から推定
    official = _parse_bso(html)
    count = official if official else _count_bso(pitches)
    if official is None:
        count["out"] = None  # 推定ではアウト数は分からない

    return {
        "index": index,
        "inning": int(index[0:2]) if len(index) >= 2 else None,
        "top_bottom": "表" if is_top else "裏",
        "order": int(index[3:5]) if len(index) >= 5 else None,
        "valid": valid,
        "batter": players["batter"],
        "pitcher": players["pitcher"],
        "runners": _parse_runners(html),
        "count": count,
        "score_at": _parse_score_line(html),
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


def _parse_rank_table(table) -> list[dict]:
    """
    bb-rankTable 1つを行の配列に変換する。
    列の並びはページによって微妙に違う（交流戦には残試合が無い等）ため、
    見出しテキストから列位置を割り出して読む。
    """
    # 見出し行から列マップを作る
    head_cells = [th.get_text(strip=True) for th in table.find_all("th")]
    col = {name: i for i, name in enumerate(head_cells)}

    def pick(cells, name, cast=None, default=None):
        i = col.get(name)
        if i is None or i >= len(cells):
            return default
        v = cells[i].strip()
        if not v or v in ("-", "―", "‐"):
            # 勝差の「-」は首位を意味するので、その意味を残す
            return "-" if name == "勝差" else default
        if cast is int:
            m = re.match(r"-?\d+", v)
            return int(m.group(0)) if m else default
        if cast is float:
            try:
                return float(v)
            except ValueError:
                return default
        return v

    rows = []
    for tr in table.find_all("tr"):
        cells = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(cells) < 5:
            continue
        team = pick(cells, "チーム名")
        if not team:
            continue
        wins = pick(cells, "勝利", int, 0) or 0
        losses = pick(cells, "敗戦", int, 0) or 0
        rows.append({
            "rank": pick(cells, "順位", int),
            "team": normalize_team(team),
            "games": pick(cells, "試合", int, 0),
            "wins": wins,
            "losses": losses,
            "ties": pick(cells, "引分", int, 0),
            "pct": pick(cells, "勝率", float),
            "gb": pick(cells, "勝差"),            # 「-」や「5.5」の文字列のまま持つ
            "games_left": pick(cells, "残試合", int),
            "runs": pick(cells, "得点", int),
            "runs_allowed": pick(cells, "失点", int),
            "hr": pick(cells, "本塁打", int),
            "sb": pick(cells, "盗塁", int),
            "avg": pick(cells, "打率", float),
            "era": pick(cells, "防御率", float),
            "errors": pick(cells, "失策", int),
            "diff": wins - losses,               # 貯金（マイナスなら借金）
        })
    return rows


def parse_standings(html: str) -> dict:
    """
    順位表ページ（/npb/standings/）から
    セ・リーグ／パ・リーグ／交流戦／月間成績の順位表を取得する。

    ページ上には bb-rankTable が複数並ぶ。どれがどれかは
    「並び順」ではなく中身から判定する:
      - 6球団かつ全てセ    → セ・リーグ
      - 6球団かつ全てパ    → パ・リーグ
      - 12球団で残試合あり → 交流戦
      - 12球団で残試合なし → 月間成績
    """
    soup = BeautifulSoup(html, "html.parser")
    out = {"central": [], "pacific": [], "interleague": [], "monthly": []}

    for t in soup.select("table.bb-rankTable"):
        rows = _parse_rank_table(t)
        if not rows:
            continue

        leagues = {team_info(r["team"]).get("league") for r in rows}
        leagues.discard(None)

        if len(rows) <= 7 and leagues == {"セ"}:
            if not out["central"]:
                out["central"] = rows
        elif len(rows) <= 7 and leagues == {"パ"}:
            if not out["pacific"]:
                out["pacific"] = rows
        elif len(rows) >= 10:
            has_left = any(r.get("games_left") is not None for r in rows)
            if has_left and not out["interleague"]:
                out["interleague"] = rows
            elif not out["monthly"]:
                out["monthly"] = rows

    return out


def parse_stadium(html: str) -> str | None:
    """
    ページ内の <ul class="stadium"> から球場名を取得する。
    一球速報ページ・statsページの両方に同じ構造で存在する。
    引用符の種類や属性の並びが変わっても拾えるようにしている。
    """
    m = re.search(
        r'<ul[^>]*class=["\']?[^"\'>]*\bstadium\b[^"\'>]*["\']?[^>]*>\s*'
        r'<li>\s*球場名[：:]\s*</li>\s*<li>([^<]+)</li>',
        html,
    )
    if m:
        return m.group(1).strip()
    # 予備：球場名ラベルの直後のリスト項目を拾う
    m2 = re.search(r'球場名[：:]\s*</li>\s*<li>([^<]+)</li>', html)
    return m2.group(1).strip() if m2 else None


# 公式戦以外の試合を示す語。ページのタイトルや見出しに現れる。
GAME_TYPE_KEYWORDS = [
    ("オールスター", "オールスター"),
    ("オールスターゲーム", "オールスター"),
    ("クライマックスシリーズ", "CS"),
    ("クライマックス", "CS"),
    ("日本シリーズ", "日本シリーズ"),
    ("交流戦", "交流戦"),          # 交流戦は公式戦なので、記録はするが除外しない
]


def detect_game_type(html: str, teams: dict | None = None) -> str:
    """
    試合の種別を判定する。
      公式戦 / 交流戦 / オールスター / CS / 日本シリーズ

    判定の根拠は2つ:
      1. チーム名が12球団に含まれない → オールスター（全セ・全パなど）
      2. タイトルや見出しに種別の語がある

    どちらにも当てはまらなければ「公式戦」とする（既定を公式戦にして、
    判定できないものを勝手に除外しないため）。
    """
    # --- 1) チーム名で判定（オールスターは12球団名にならない）---
    if teams:
        for key in ("home", "away"):
            name = teams.get(key)
            # 12球団に無いチーム名（全セ・全パなど）はオールスター
            if name and team_info(name).get("league") is None:
                return "オールスター"

    # --- 2) タイトル・見出しの語で判定 ---
    head = ""
    m = re.search(r"<title>(.*?)</title>", html, re.S)
    if m:
        head += m.group(1)
    for hm in re.finditer(r"<h[12][^>]*>(.*?)</h[12]>", html, re.S):
        head += " " + hm.group(1)
    head = re.sub(r"<[^>]+>", "", head)

    for word, label in GAME_TYPE_KEYWORDS:
        if word in head:
            return label

    return "公式戦"


def parse_teams(html: str) -> dict:
    """
    <title>から対戦カードを取得する。
    例: 「…東北楽天…vs.福岡ソフトバンク… 一球速報 …」

    ★重要★ 日本のプロ野球表記は「主催チーム vs 相手チーム」。
    つまりタイトルの1番目＝ホーム（後攻）、2番目＝ビジター（先攻）。
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

    home_full = vm.group(1).strip()  # 1番目＝ホーム
    away_full = vm.group(2).strip()  # 2番目＝ビジター（先攻）
    return {
        "away": TEAM_SHORT.get(away_full, away_full),
        "home": TEAM_SHORT.get(home_full, home_full),
        "away_full": away_full,
        "home_full": home_full,
        "date_text": date_text,
    }
