"""
NPBデータ収集 - 本実装版
=========================
指定日（省略時は今日）の全試合について、一球速報を全打席巡回して収集する。

使い方:
    python scraper/main.py                     # 今日（JST）
    python scraper/main.py --date 2026-07-10   # 日付指定
    python scraper/main.py --game 2021038864   # 特定試合だけ

保存先:
    data/YYYY/MM/DD/<試合ID>.json   … 試合ごとの詳細（一球速報つき）
    data/YYYY/MM/DD/_summary.json   … その日の試合一覧
    data/index.json                 … 収集済みファイル一覧（アプリ用）
"""

import argparse
import json
import os
import time
from datetime import datetime, timedelta, timezone

import requests

from parser import parse_atbat, extract_atbat_indexes, parse_teams

JST = timezone(timedelta(hours=9))
BASE = "https://baseball.yahoo.co.jp"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}
# 行儀のいいアクセス（サーバー負荷をかけない）
SLEEP_SEC = 1.5


def fetch(url: str) -> str:
    """1ページ取得（間隔を空ける）"""
    time.sleep(SLEEP_SEC)
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def parse_args():
    p = argparse.ArgumentParser(description="NPB一球速報コレクター")
    p.add_argument("--date", default=None, help="収集日 YYYY-MM-DD（省略時は今日）")
    p.add_argument("--game", default=None, help="特定の試合IDだけ収集")
    return p.parse_args()


def resolve_date(s):
    if s:
        try:
            return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=JST)
        except ValueError:
            raise SystemExit(f"[ERROR] 日付形式エラー: {s}（例: 2026-07-10）")
    return datetime.now(JST)


def find_game_ids(date: datetime) -> list[str]:
    """
    指定日の試合IDを日程ページから取得する。
    スポナビの日程URL: /npb/schedule/?date=YYYY-MM-DD
    """
    import re
    url = f"{BASE}/npb/schedule/?date={date.strftime('%Y-%m-%d')}"
    try:
        html = fetch(url)
    except Exception as e:
        print(f"[WARN] 日程ページ取得失敗: {e}")
        return []
    ids = sorted(set(re.findall(r"/npb/game/(\d+)/", html)))
    print(f"[INFO] {date.strftime('%Y-%m-%d')} の試合: {len(ids)}件")
    return ids


def collect_game(game_id: str) -> dict:
    """1試合ぶんを全打席巡回して収集"""
    # 起点ページ（score）から全打席indexを取得
    start_url = f"{BASE}/npb/game/{game_id}/score"
    try:
        html = fetch(start_url)
    except Exception as e:
        print(f"[WARN] 試合{game_id}取得失敗: {e}")
        return {"game_id": game_id, "error": str(e), "atbats": []}

    teams = parse_teams(html)
    indexes = extract_atbat_indexes(html)
    card = f"{teams['away'] or '?'} vs {teams['home'] or '?'}"
    print(f"[INFO] 試合{game_id}: {card} / {len(indexes)}打席を巡回")

    atbats = []
    for i, idx in enumerate(indexes, 1):
        url = f"{BASE}/npb/game/{game_id}/score?index={idx}"
        try:
            page = fetch(url)
            ab = parse_atbat(page, idx)
            atbats.append(ab)
            print(f"  [{i}/{len(indexes)}] index={idx} {ab['pitch_count']}球 {ab['result_summary'] or ''}")
        except Exception as e:
            print(f"  [{i}/{len(indexes)}] index={idx} 失敗: {e}")

    total_pitches = sum(a["pitch_count"] for a in atbats)
    return {
        "game_id": game_id,
        "collected_at": datetime.now(JST).isoformat(),
        "away": teams["away"],
        "home": teams["home"],
        "away_full": teams["away_full"],
        "home_full": teams["home_full"],
        "card": card,
        "atbat_count": len(atbats),
        "pitch_count": total_pitches,
        "atbats": atbats,
    }


def save_game(data: dict, date: datetime) -> str:
    d = os.path.join("data", date.strftime("%Y"), date.strftime("%m"), date.strftime("%d"))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"{data['game_id']}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def save_summary(date: datetime, results: list[dict]) -> str:
    d = os.path.join("data", date.strftime("%Y"), date.strftime("%m"), date.strftime("%d"))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "_summary.json")
    summary = {
        "date": date.strftime("%Y-%m-%d"),
        "collected_at": datetime.now(JST).isoformat(),
        "game_count": len(results),
        "games": [
            {"game_id": r["game_id"],
             "away": r.get("away"), "home": r.get("home"),
             "card": r.get("card"),
             "atbat_count": r.get("atbat_count", 0),
             "pitch_count": r.get("pitch_count", 0)}
            for r in results
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return path


def update_index(paths: list[str]):
    index_path = os.path.join("data", "index.json")
    files = []
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as f:
            files = json.load(f).get("files", [])
    for p in paths:
        rel = p.replace(os.sep, "/")
        if rel not in files:
            files.append(rel)
    files.sort()
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump({"updated_at": datetime.now(JST).isoformat(), "files": files},
                  f, ensure_ascii=False, indent=2)


def main():
    args = parse_args()
    date = resolve_date(args.date)
    print(f"[INFO] 収集日: {date.strftime('%Y-%m-%d')}")

    game_ids = [args.game] if args.game else find_game_ids(date)
    if not game_ids:
        print("[INFO] 対象試合なし。終了します。")
        return

    saved_paths = []
    results = []
    for gid in game_ids:
        result = collect_game(gid)
        results.append(result)
        saved_paths.append(save_game(result, date))

    saved_paths.append(save_summary(date, results))
    update_index(saved_paths)

    total = sum(r.get("pitch_count", 0) for r in results)
    print(f"[INFO] 完了: {len(results)}試合 / 計{total}球を保存")


if __name__ == "__main__":
    main()
