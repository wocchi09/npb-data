"""
NPB公式サイトからの選手名鑑取得
=================================
https://npb.jp/bis/teams/rst_{code}.html から12球団の選手を取得する。

★対象は支配下選手のみ。育成選手は取得しない★

ページ構造（実物で確認済み）:
  <h3>■支配下選手</h3>
  <table class="rosterlisttbl">   ← これを読む
      No. / 監督   / 生年月日 / ...      ← 小見出し行
      90  / 小久保 裕紀 / 1971.10.08 / ...
      No. / 投手   / 生年月日 / 身長 / 体重 / 投 / 打 / 備考   ← 小見出し行
      11  / 津森 宥紀 / 1998.01.21 / 176 / 86 / 右 / 右 /
      No. / 捕手   / ...
      ...
  <h3>■育成選手</h3>
  <table class="rosterlisttbl">   ← 読まない

注意:
  - ページのHTTPヘッダに文字コードの指定が無く、requests が誤判定するため
    明示的に UTF-8 として読む。
  - 監督・コーチの行は選手ではないので除外する。
  - 選手ページへのリンク（/bis/players/xxxxxxxx.html）から公式選手IDを取る。

使い方:
    python scraper/roster.py                 # 12球団まとめて
    python scraper/roster.py --team f         # 日本ハムだけ
    python scraper/roster.py --out data/masters/npb_roster.json
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

JST = timezone(timedelta(hours=9))

BASE = "https://npb.jp/bis/teams/rst_{code}.html"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}
SLEEP_SEC = 2.0   # 取得元への配慮（12球団で約24秒）

# 球団コード → 内部のチーム名（lib/normalize.py の表記に合わせる）
TEAM_CODES = [
    ("h",  "ソフトバンク"),
    ("f",  "日本ハム"),
    ("b",  "オリックス"),
    ("e",  "楽天"),
    ("l",  "西武"),
    ("m",  "ロッテ"),
    ("t",  "阪神"),
    ("db", "DeNA"),
    ("g",  "巨人"),
    ("d",  "中日"),
    ("c",  "広島"),
    ("s",  "ヤクルト"),
]

# 表内の小見出しに現れる区分。選手として扱うのはこの4つだけ
POSITION_GROUPS = {
    "投手": "投",
    "捕手": "捕",
    "内野手": "内",
    "外野手": "外",
}
# 選手ではない区分（読み飛ばす）
NON_PLAYER = ("監督", "コーチ", "スタッフ")


def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    # ヘッダに charset が無いため requests が Latin-1 と誤判定する。UTF-8で読む
    r.encoding = "utf-8"
    time.sleep(SLEEP_SEC)
    return r.text


def _is_header_row(cells: list[str]) -> str | None:
    """
    小見出し行なら、その区分名（投手/捕手/監督など）を返す。
    小見出し行は1列目が「No.」になっている。
    """
    if not cells or cells[0].strip() not in ("No.", "No", "№"):
        return None
    return cells[1].strip() if len(cells) > 1 else ""


def _clean(s: str) -> str:
    return " ".join((s or "").replace("\u3000", " ").split())


def parse_roster(html: str, team: str) -> list[dict]:
    """
    1球団ぶんのページから支配下選手を取り出す。
    育成選手のテーブルは読まない。
    """
    soup = BeautifulSoup(html, "html.parser")

    # 「支配下選手」の見出しを探し、その後ろで最初に現れる名簿テーブルを使う
    target_table = None
    for h in soup.find_all(["h2", "h3", "h4"]):
        text = h.get_text(strip=True)
        if "支配下" in text:
            target_table = h.find_next("table", class_="rosterlisttbl")
            break

    if target_table is None:
        # 見出しが見つからない場合は最初の名簿テーブルを使う
        # （育成テーブルは常に後ろにあるため、先頭＝支配下）
        tables = soup.select("table.rosterlisttbl")
        target_table = tables[0] if tables else None

    if target_table is None:
        return []

    players = []
    group = None       # 現在読んでいる区分（投手・捕手 など）

    for tr in target_table.find_all("tr"):
        tds = tr.find_all(["td", "th"])
        cells = [td.get_text(strip=True) for td in tds]
        if not any(cells):
            continue

        # 小見出し行なら区分を切り替える
        head = _is_header_row(cells)
        if head is not None:
            group = head
            continue

        if group is None:
            continue
        if any(x in group for x in NON_PLAYER):
            continue                      # 監督・コーチは選手ではない
        pos = POSITION_GROUPS.get(group)
        if not pos:
            continue                      # 想定外の区分は入れない

        number = _clean(cells[0]) if len(cells) > 0 else ""
        name = _clean(cells[1]) if len(cells) > 1 else ""
        if not name:
            continue

        # 公式選手IDは選手ページへのリンクから取る
        npb_id = None
        a = tr.find("a", href=re.compile(r"/bis/players/(\d+)\.html"))
        if a:
            m = re.search(r"/bis/players/(\d+)\.html", a["href"])
            npb_id = m.group(1) if m else None

        def cell(i):
            return _clean(cells[i]) if len(cells) > i else ""

        players.append({
            "npb_id": npb_id,
            "name": name,
            "team": team,
            "number": number,
            "position_group": pos,        # 投 / 捕 / 内 / 外
            "is_pitcher": pos == "投",
            "birthdate": cell(2) or None,
            "height": cell(3) or None,
            "weight": cell(4) or None,
            "throws": cell(5) or None,    # 右 / 左
            "bats": cell(6) or None,      # 右 / 左 / 両
            "note": cell(7) or None,
        })

    return players


def collect(codes=None, out_path="data/masters/npb_roster.json"):
    codes = codes or [c for c, _ in TEAM_CODES]
    name_of = dict(TEAM_CODES)

    all_players = []
    per_team = {}
    for code in codes:
        team = name_of.get(code, code)
        url = BASE.format(code=code)
        try:
            html = fetch(url)
        except Exception as e:
            print(f"[WARN] {team} の取得に失敗: {e}")
            continue
        try:
            rows = parse_roster(html, team)
        except Exception as e:
            print(f"[WARN] {team} の解析に失敗: {e}")
            continue

        # 育成が混ざっていないかの保険：支配下の背番号は3桁にならない
        suspicious = [p for p in rows if re.fullmatch(r"\d{3,}", p["number"] or "")]
        if suspicious:
            print(f"[WARN] {team}: 3桁の背番号が {len(suspicious)}件混ざっています"
                  f"（育成の可能性・除外します）")
            rows = [p for p in rows if p not in suspicious]

        per_team[team] = len(rows)
        all_players.extend(rows)
        print(f"[INFO] {team}: 支配下 {len(rows)}人")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": datetime.now(JST).isoformat(),
            "source": "https://npb.jp/bis/teams/",
            "scope": "支配下選手のみ（育成選手は含まない）",
            "count": len(all_players),
            "per_team": per_team,
            "players": all_players,
        }, f, ensure_ascii=False, indent=2)

    print(f"[INFO] 合計 {len(all_players)}人を {out_path} に保存しました")
    return len(all_players)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", default=None, help="球団コード（省略時は12球団）")
    ap.add_argument("--out", default="data/masters/npb_roster.json")
    args = ap.parse_args()

    codes = [args.team] if args.team else None
    collect(codes, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
