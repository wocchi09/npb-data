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

from parser import (
    parse_atbat, extract_atbat_indexes, parse_teams,
    parse_score_list, parse_homeruns, parse_battery,
    parse_stats_page,
)

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
# 巡回の上限（延長戦・打者一巡以上に備えた安全弁）
MAX_INNING = 12
MAX_BATTERS_PER_INNING = 15


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
    日程ページには他日付・他カテゴリのリンクも含まれるため、
    「その日のNPB公式戦」に絞り込む。
    """
    import re
    date_str = date.strftime("%Y-%m-%d")
    url = f"{BASE}/npb/schedule/?date={date_str}"
    try:
        html = fetch(url)
    except Exception as e:
        print(f"[WARN] 日程ページ取得失敗: {e}")
        return []

    # その日のセクションだけを切り出す（日付アンカー以降）
    # 取れない場合は全体から拾う
    ids = re.findall(r"/npb/game/(\d{10})/", html)

    # 重複除去（出現順を保つ）
    seen = []
    for i in ids:
        if i not in seen:
            seen.append(i)

    print(f"[INFO] {date_str} の試合候補: {len(seen)}件")
    return seen


def clean_day_folder(date: datetime):
    """
    収集前に、その日のフォルダを空にする。
    余分な試合IDで作られた古いファイルが残り続けるのを防ぐ。
    """
    import shutil
    d = os.path.join("data", date.strftime("%Y"), date.strftime("%m"), date.strftime("%d"))
    if os.path.isdir(d):
        shutil.rmtree(d)
        print(f"[INFO] 既存フォルダを初期化: {d}")


def collect_game(game_id: str, expected_date: datetime | None = None) -> dict:
    """
    1試合ぶんを全打席巡回して収集する。

    indexの構造: RRTBBPP
      RR = 回(01-12) / T = 表1・裏2 / BB = 打者番号(01-) / PP = 球(00)

    ページ内リンクは各イニングの1打席目しか無いため、
    打者番号を 01, 02, 03... と自分で進めて全打席を辿る。
    打者名が取れない or「試合前」が出たらそのイニングは終了。

    expected_date を渡すと、ページのタイトル日付と照合し、
    別日の試合なら skip=True を返す（余分な試合IDの除外用）。
    """
    start_url = f"{BASE}/npb/game/{game_id}/score"
    try:
        html = fetch(start_url)
    except Exception as e:
        print(f"[WARN] 試合{game_id}取得失敗: {e}")
        return {"game_id": game_id, "error": str(e), "skip": True, "atbats": []}

    teams = parse_teams(html)
    # 日本式の表記（主催＝ホームを先に書く）
    card = f"{teams['home'] or '?'} vs {teams['away'] or '?'}"

    # 日付照合（タイトルの「2026年7月12日」と収集対象日を突き合わせる）
    if expected_date is not None and teams.get("date_text"):
        want = f"{expected_date.year}年{expected_date.month}月{expected_date.day}日"
        if teams["date_text"] != want:
            print(f"[SKIP] 試合{game_id}: {teams['date_text']} は対象外（{want}を収集中）")
            return {"game_id": game_id, "skip": True, "card": card, "atbats": []}

    print(f"[INFO] 試合{game_id}: {card} 巡回開始")

    atbats = []
    empty_innings = 0

    for inning in range(1, MAX_INNING + 1):
        inning_had_atbat = False

        for tb in (1, 2):  # 1=表, 2=裏
            for order in range(1, MAX_BATTERS_PER_INNING + 1):
                idx = f"{inning:02d}{tb}{order:02d}00"
                url = f"{BASE}/npb/game/{game_id}/score?index={idx}"
                try:
                    page = fetch(url)
                except Exception as e:
                    print(f"  [{idx}] 取得失敗: {e}")
                    break

                ab = parse_atbat(page, idx)
                if not ab["valid"]:
                    # この打席は存在しない → このイニング(表/裏)は終了
                    break

                # 攻撃側チームを補完（表=away、裏=home）
                ab["batting_team"] = teams["away"] if tb == 1 else teams["home"]
                ab["fielding_team"] = teams["home"] if tb == 1 else teams["away"]
                atbats.append(ab)
                inning_had_atbat = True

        if inning_had_atbat:
            empty_innings = 0
            print(f"  {inning}回まで: 累計{len(atbats)}打席")
        else:
            empty_innings += 1
            # 2イニング連続で打席が無ければ試合終了とみなす
            if empty_innings >= 2:
                break

    # 試合結果まとめ（スコア・勝敗投手・セーブ・本塁打・バッテリー）
    # 起点ページに載っている「その日の日程・結果」から自分の試合を探す
    result_info = {}
    try:
        all_games = parse_score_list(html)
        for gg in all_games:
            if gg["game_id"] == game_id or (
                gg["home"] == teams["home"] and gg["away"] == teams["away"]
            ):
                result_info = gg
                break
        result_info["homeruns"] = parse_homeruns(html)
        result_info["battery"] = parse_battery(html)
    except Exception as e:
        print(f"[WARN] 試合結果の取得に失敗: {e}")

    # 出場成績ページから公式の打撃・投手成績を取得（フェーズ2）
    boxscore = None
    try:
        stats_html = fetch(f"{BASE}/npb/game/{game_id}/stats")
        boxscore = parse_stats_page(stats_html)
        nb = len(boxscore["batting"]["away"]) + len(boxscore["batting"]["home"])
        np_ = len(boxscore["pitching"]["away"]) + len(boxscore["pitching"]["home"])
        print(f"[INFO] 出場成績: 打者{nb}人 / 投手{np_}人")
    except Exception as e:
        print(f"[WARN] 出場成績の取得に失敗: {e}")

    total_pitches = sum(a["pitch_count"] for a in atbats)
    print(f"[INFO] 試合{game_id}: {len(atbats)}打席 / {total_pitches}球")

    # 公式スコア（最後の打席ページに表示されている得点＝ほぼ最終スコア）
    final_score = None
    for ab in reversed(atbats):
        if ab.get("score_at"):
            final_score = ab["score_at"]
            break

    return {
        "game_id": game_id,
        "collected_at": datetime.now(JST).isoformat(),
        "away": teams["away"],
        "home": teams["home"],
        "away_full": teams["away_full"],
        "home_full": teams["home_full"],
        "card": card,
        "final_score": final_score,
        "result": result_info,
        "boxscore": boxscore,
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
             "result": r.get("result", {}),
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

    # 古いファイルが残らないよう、収集前にその日のフォルダを初期化
    if not args.game:
        clean_day_folder(date)

    saved_paths = []
    results = []
    skipped = 0
    for gid in game_ids:
        result = collect_game(gid, expected_date=None if args.game else date)
        if result.get("skip"):
            skipped += 1
            continue
        if not result.get("atbats"):
            print(f"[SKIP] 試合{gid}: 打席データなし")
            skipped += 1
            continue
        results.append(result)
        saved_paths.append(save_game(result, date))

    if not results:
        print(f"[INFO] 保存対象なし（スキップ{skipped}件）")
        return

    saved_paths.append(save_summary(date, results))
    update_index(saved_paths)

    total = sum(r.get("pitch_count", 0) for r in results)
    print(f"[INFO] 完了: {len(results)}試合 / 計{total}球を保存（スキップ{skipped}件）")


if __name__ == "__main__":
    main()
