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
import re
import time
from datetime import datetime, timedelta, timezone

import requests

from parser import (
    parse_atbat, extract_atbat_indexes, parse_teams,
    parse_score_list, parse_homeruns, parse_battery,
    parse_stats_page, parse_stadium, parse_standings,
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
    p.add_argument("--from-date", dest="from_date", default=None,
                   help="期間指定の開始日 YYYY-MM-DD（--to-dateと併用）")
    p.add_argument("--to-date", dest="to_date", default=None,
                   help="期間指定の終了日 YYYY-MM-DD（--from-dateと併用）")
    return p.parse_args()


# 安全弁：1回の実行でまとめて収集できる日数の上限。
# サーバーへの一括アクセスを避けるため、複数日でも1日ずつ順番に、
# 通常の1.5秒間隔を保ったまま処理する（負荷は増やさず時間だけ使う）。
MAX_RANGE_DAYS = 7


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
    stadium = parse_stadium(html)
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
        # 試合ページのタイトルにある開催日。保存フォルダとのズレ検証に使う
        "game_date": jp_date_to_iso(teams.get("date_text")),
        "stadium": stadium,
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
             "stadium": r.get("stadium"),
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
    """
    収集済みファイルの一覧を更新する。

    ★重要★ 再収集時は clean_day_folder が古いファイルを消すため、
    単に追記するだけだと消えたファイルのパスが残り、
    試合数が実際より多く見えてしまう。
    そのため、書き出す前に「実際に存在するファイル」だけに絞り込む。
    """
    index_path = os.path.join("data", "index.json")
    files = []
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8") as f:
            files = json.load(f).get("files", [])
    for p in paths:
        rel = p.replace(os.sep, "/")
        if rel not in files:
            files.append(rel)

    # 実在しないパスを取り除く
    before = len(files)
    files = [f for f in files if os.path.exists(f)]
    removed = before - len(files)
    if removed:
        print(f"[INFO] index.json から実在しないファイル {removed}件を除去しました")

    files = sorted(set(files))
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump({"updated_at": datetime.now(JST).isoformat(), "files": files},
                  f, ensure_ascii=False, indent=2)


def jp_date_to_iso(text: str | None) -> str | None:
    """「2026年7月19日」→「2026-07-19」。取れない場合は None"""
    if not text:
        return None
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", str(text))
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def record_no_game_day(date: datetime, base="data") -> str | None:
    """
    その日に試合が無かったことを記録する。
    「試合がなかった日」と「まだ収集していない日」を
    カレンダー上で区別できるようにするため。
    """
    season = date.strftime("%Y")
    ds = date.strftime("%Y-%m-%d")
    path = os.path.join(base, season, "no_games.json")
    dates = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                dates = json.load(f).get("dates", [])
        except Exception:
            dates = []
    if ds not in dates:
        dates.append(ds)
    dates = sorted(set(dates))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"updated_at": datetime.now(JST).isoformat(), "dates": dates},
                  f, ensure_ascii=False, indent=2)
    print(f"[INFO] {ds} は試合なしとして記録しました")
    return path


def save_standings(date: datetime) -> str | None:
    """
    順位表（セ・リーグ／パ・リーグ／交流戦／月間）を取得して保存する。
    1ページで全部取れるので、1回の実行につきアクセスは1回だけ。
    """
    season = date.strftime("%Y")
    try:
        html = fetch(f"{BASE}/npb/standings/")
    except Exception as e:
        print(f"[WARN] 順位表の取得に失敗: {e}")
        return None

    try:
        st = parse_standings(html)
    except Exception as e:
        print(f"[WARN] 順位表の解析に失敗: {e}")
        return None

    counts = {k: len(v) for k, v in st.items()}
    if not any(counts.values()):
        print("[WARN] 順位表を取得できませんでした（構造が変わった可能性）")
        return None

    path = os.path.join("data", season, "standings.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "season": season,
            "updated_at": datetime.now(JST).isoformat(),
            **st,
        }, f, ensure_ascii=False, indent=2)

    print(f"[INFO] 順位表を保存: セ{counts['central']}/パ{counts['pacific']}"
          f"/交流戦{counts['interleague']}/月間{counts['monthly']}")
    return path


def collect_day(date: datetime, only_game: str | None = None) -> dict:
    """
    1日分の収集を行う（従来のmain()の中身をそのまま関数化）。
    複数日ループからも単発実行からも、この関数を呼ぶ。
    """
    print(f"[INFO] 収集日: {date.strftime('%Y-%m-%d')}")

    game_ids = [only_game] if only_game else find_game_ids(date)
    if not game_ids:
        print("[INFO] 対象試合なし。終了します。")
        if not only_game:
            p = record_no_game_day(date)
            if p:
                update_index([p])
        return {"date": date.strftime("%Y-%m-%d"), "games": 0, "pitches": 0, "skipped": 0}

    # 古いファイルが残らないよう、収集前にその日のフォルダを初期化
    if not only_game:
        clean_day_folder(date)

    saved_paths = []
    results = []
    skipped = 0
    for gid in game_ids:
        result = collect_game(gid, expected_date=None if only_game else date)
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
        return {"date": date.strftime("%Y-%m-%d"), "games": 0, "pitches": 0, "skipped": skipped}

    saved_paths.append(save_summary(date, results))
    update_index(saved_paths)

    total = sum(r.get("pitch_count", 0) for r in results)
    print(f"[INFO] 完了: {len(results)}試合 / 計{total}球を保存（スキップ{skipped}件）")
    return {"date": date.strftime("%Y-%m-%d"), "games": len(results),
            "pitches": total, "skipped": skipped}


def daterange(d1: datetime, d2: datetime):
    """d1〜d2（両端含む）を1日ずつ生成する"""
    n = (d2.date() - d1.date()).days
    for i in range(n + 1):
        yield d1 + timedelta(days=i)


def main():
    args = parse_args()

    # ---- 期間指定モード ----
    if args.from_date or args.to_date:
        if not (args.from_date and args.to_date):
            raise SystemExit("[ERROR] --from-date と --to-date は両方指定してください")
        if args.game:
            raise SystemExit("[ERROR] 期間指定と --game は同時に使えません")

        d1 = resolve_date(args.from_date)
        d2 = resolve_date(args.to_date)
        if d2 < d1:
            raise SystemExit("[ERROR] --to-date は --from-date より後にしてください")

        days = list(daterange(d1, d2))
        # 安全弁：一度に大量アクセスしないよう日数を制限
        if len(days) > MAX_RANGE_DAYS:
            raise SystemExit(
                f"[ERROR] 指定期間が{len(days)}日あります。"
                f"1回の実行は最大{MAX_RANGE_DAYS}日までにしてください"
                f"（サーバー負荷を抑えるための安全弁です。日付を分けて複数回実行してください）"
            )

        print(f"[INFO] 期間収集: {args.from_date} 〜 {args.to_date}（{len(days)}日）")
        summary = []
        for d in days:
            summary.append(collect_day(d))
            # 日をまたぐ間も間隔を空ける（サーバーへの配慮は単日実行と同じ）
            if d != days[-1]:
                time.sleep(SLEEP_SEC)

        print(f"\n[INFO] 期間収集完了（{len(days)}日）")
        for s in summary:
            print(f"  {s['date']}: {s['games']}試合 / {s['pitches']}球（スキップ{s['skipped']}）")
        # 順位表は日付によらず最新版なので、期間収集でも1回だけ取得する
        sp = save_standings(days[-1])
        if sp:
            update_index([sp])
        return

    # ---- 単日モード（従来どおり） ----
    date = resolve_date(args.date)
    collect_day(date, only_game=args.game)
    sp = save_standings(date)
    if sp:
        update_index([sp])


if __name__ == "__main__":
    main()
