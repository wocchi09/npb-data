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

    return {
        "index": index,
        "inning": int(index[0:2]) if len(index) >= 2 else None,
        "top_bottom": "表" if len(index) >= 3 and index[2] == "1" else "裏",
        "result_summary": result_summary,
        "result_detail": result_detail,
        "pitch_count": len(pitches),
        "pitches": pitches,
    }


def extract_atbat_indexes(html: str) -> list[str]:
    """試合ページ内に載っている全打席のindex一覧を取得（重複除去・昇順）"""
    idxs = sorted(set(re.findall(r"score\?index=(\d+)", html)))
    return idxs
