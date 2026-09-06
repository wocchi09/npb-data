"""
不足データの後追い補完（バックフィル）
======================================
すでに保存済みの試合JSONに対して、後から追加した項目だけを埋める。
打席の全巡回はやり直さないので、1試合あたり1〜2リクエストで済む。

埋められるもの:
  - stadium … 球場名
  - boxscore … 出場成績（打順・スタメン判定・守備位置つき）
  - atbats … 牽制/ボークで打席が中断され、本当の結果・残りの投球が
    取れていなかった打席の復元（打者番号の連番だけでは追えなかった
    続きのページを、ページ内リンクから見つけて追いかける）

使い方:
    python scraper/backfill.py --season 2026
    python scraper/backfill.py --date 2026-07-19
    python scraper/backfill.py --season 2026 --what stadium
    python scraper/backfill.py --season 2026 --what atbats

すでに項目が入っている試合・中断が見つからない試合は自動でスキップするので、
何度実行しても余計なアクセスは発生しない（冪等）。
"""

import argparse
import glob
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parser import parse_stats_page, parse_stadium, extract_atbat_indexes
from main import fetch_atbat, looks_interrupted_atbat

BASE = "https://baseball.yahoo.co.jp"
JST = timezone(timedelta(hours=9))
SLEEP_SEC = 1.5
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}


def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    time.sleep(SLEEP_SEC)
    return r.text


def find_game_files(season, base="data", date=None):
    """試合JSONを集める（集計ファイル・データセットは除く）"""
    if date:
        y, m, d = date.split("-")
        pat = f"{base}/{y}/{m}/{d}/*.json"
    else:
        pat = f"{base}/{season}/**/*.json"
    out = []
    for p in glob.glob(pat, recursive=True):
        norm = p.replace("\\", "/")
        name = os.path.basename(norm)
        if name.startswith("_") or name == "index.json":
            continue
        if any(x in norm for x in (
                "/players/", "/teams/", "/dataset/", "/masters/", "/awards/", "/matchups/", "/pitch_heatmaps/")):
            continue
        out.append(norm)
    return sorted(out)


def needs_boxscore(g) -> bool:
    """出場成績が無い、または打順が入っていないなら補完対象"""
    box = g.get("boxscore")
    if not box:
        return True
    bat = (box.get("batting") or {})
    rows = (bat.get("away") or []) + (bat.get("home") or [])
    if not rows:
        return True
    # 打順が1つも入っていない＝古い形式
    return not any(r.get("order") for r in rows)


def find_interrupted_half_innings(g) -> list[list[dict]]:
    """
    牽制/ボークなど打席の結論ではない状態でアウト3未満のまま止まり、
    次のイニング(表/裏)に切り替わっている半イニングを打席の並び順で返す。
    試合最後の半イニング（サヨナラ・コールドで3アウトに届かない場合がある）
    は対象外にする。
    """
    atbats = g.get("atbats") or []
    if not atbats:
        return []
    groups: list[list[dict]] = []
    for ab in atbats:
        key = (ab.get("inning"), ab.get("top_bottom"))
        if groups and (groups[-1][0].get("inning"), groups[-1][0].get("top_bottom")) == key:
            groups[-1].append(ab)
        else:
            groups.append([ab])
    return [
        group for group in groups[:-1]
        if group and looks_interrupted_atbat(group[-1])
    ]


def needs_atbats(g) -> bool:
    """中断されたまま止まっている半イニングがあれば補完対象"""
    return bool(find_interrupted_half_innings(g))


def repair_atbats(g) -> list[str]:
    """
    中断が疑われる半イニングごとに、最後に記録した打席のページを取り直して
    埋め込みリンクからindexを拾い、続きの打席を追いかけて g["atbats"] に
    挿入する。戻り値は復元できた半イニングの説明（ログ表示用）。
    """
    game_id = g.get("game_id")
    touched = []
    for group in find_interrupted_half_innings(g):
        last = group[-1]
        inning, top_bottom = last.get("inning"), last.get("top_bottom")
        tb = 1 if top_bottom == "表" else 2
        prefix = f"{inning:02d}{tb}"
        fetched_indexes = {ab["index"] for ab in g["atbats"] if ab.get("index")}
        known_indexes = set()

        # 中断箇所のページを取り直し、そこに埋まっているリンクから拾い直す
        refetched = fetch_atbat(game_id, last["index"])
        if refetched is None:
            continue
        page, _ = refetched
        known_indexes.update(extract_atbat_indexes(page))

        recovered = []
        current_last = last
        for _ in range(8):  # 無限ループ防止の安全弁
            if not looks_interrupted_atbat(current_last):
                break
            pending = sorted(
                i for i in known_indexes
                if i.startswith(prefix) and i not in fetched_indexes
            )
            if not pending:
                break
            progressed = None
            for idx in pending:
                fetched_indexes.add(idx)
                fetched = fetch_atbat(game_id, idx)
                if fetched is None:
                    continue
                page, ab = fetched
                known_indexes.update(extract_atbat_indexes(page))
                if ab["valid"]:
                    ab["batting_team"] = g["away"] if tb == 1 else g["home"]
                    ab["fielding_team"] = g["home"] if tb == 1 else g["away"]
                    recovered.append(ab)
                    progressed = ab
            if progressed is None:
                break
            current_last = progressed

        if recovered:
            g["atbats"].extend(recovered)
            g["atbats"].sort(key=lambda a: a["index"])
            touched.append(f"{inning}回{top_bottom}: {len(recovered)}打席分を復元")
    return touched


def update_summary(day_dir):
    """その日の _summary.json に球場を反映する"""
    sp = os.path.join(day_dir, "_summary.json")
    if not os.path.exists(sp):
        return
    try:
        with open(sp, encoding="utf-8") as f:
            summary = json.load(f)
    except Exception:
        return

    changed = False
    for entry in summary.get("games", []):
        gid = entry.get("game_id")
        gp = os.path.join(day_dir, f"{gid}.json")
        if not os.path.exists(gp):
            continue
        try:
            with open(gp, encoding="utf-8") as f:
                g = json.load(f)
        except Exception:
            continue
        if g.get("stadium") and entry.get("stadium") != g.get("stadium"):
            entry["stadium"] = g["stadium"]
            changed = True

    if changed:
        with open(sp, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)


def backfill_game(path, what) -> dict:
    """1試合ぶんを補完する。戻り値は処理結果の要約"""
    with open(path, encoding="utf-8") as f:
        g = json.load(f)

    gid = g.get("game_id")
    if not gid:
        return {"status": "skip", "reason": "game_idなし"}

    want_stadium = ("stadium" in what) and not g.get("stadium")
    want_box = ("boxscore" in what) and needs_boxscore(g)
    want_atbats = ("atbats" in what) and needs_atbats(g)
    if not want_stadium and not want_box and not want_atbats:
        return {"status": "skip", "reason": "補完不要"}

    got = []

    if want_atbats:
        try:
            touched = repair_atbats(g)
        except Exception as e:
            print(f"    [WARN] 打席の復元に失敗: {e}")
            touched = []
        if touched:
            g["atbat_count"] = len(g["atbats"])
            g["pitch_count"] = sum(len(ab.get("pitches") or []) for ab in g["atbats"])
            got.append("atbats")
            for line in touched:
                print(f"    復元: {line}")

    # まず /stats を1回取得（出場成績と、あれば球場もここで取れる）
    stats_html = None
    if want_box or want_stadium:
        try:
            stats_html = fetch(f"{BASE}/npb/game/{gid}/stats")
        except Exception as e:
            return {"status": "error", "reason": f"stats取得失敗: {e}"}

    if want_box and stats_html:
        try:
            box = parse_stats_page(stats_html)
            nb = len(box["batting"]["away"]) + len(box["batting"]["home"])
            if nb:
                g["boxscore"] = box
                got.append("boxscore")
        except Exception as e:
            print(f"    [WARN] 出場成績の解析に失敗: {e}")

    if want_stadium:
        st = None
        if stats_html:
            st = parse_stadium(stats_html)
        if not st:
            # /stats に無ければ一球速報ページを1回だけ見る
            try:
                st = parse_stadium(fetch(f"{BASE}/npb/game/{gid}/score"))
            except Exception as e:
                print(f"    [WARN] 球場の取得に失敗: {e}")
        if st:
            g["stadium"] = st
            got.append("stadium")

    if not got:
        return {"status": "nochange", "reason": "取得できず"}

    g["backfilled_at"] = datetime.now(JST).isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(g, f, ensure_ascii=False, indent=2)
    return {"status": "updated", "got": got}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default=None)
    ap.add_argument("--date", default=None, help="この日だけ補完する")
    ap.add_argument("--base", default="data")
    ap.add_argument("--what", default="stadium,boxscore",
                    help="補完する項目（カンマ区切り。stadium,boxscore,atbats）")
    ap.add_argument("--limit", type=int, default=0,
                    help="処理する試合数の上限（0なら無制限）")
    args = ap.parse_args()

    season = args.season or (args.date.split("-")[0] if args.date else None)
    if not season:
        print("[ERROR] --season または --date を指定してください")
        return 1

    what = [x.strip() for x in args.what.split(",") if x.strip()]
    files = find_game_files(season, args.base, args.date)
    print(f"[INFO] 対象 {len(files)}試合 / 補完項目: {', '.join(what)}")

    updated = skipped = errors = 0
    touched_dirs = set()

    for i, path in enumerate(files, 1):
        if args.limit and updated >= args.limit:
            print(f"[INFO] 上限{args.limit}件に達したので終了します")
            break
        res = backfill_game(path, what)
        if res["status"] == "updated":
            updated += 1
            touched_dirs.add(os.path.dirname(path))
            print(f"  [{i}/{len(files)}] {os.path.basename(path)} … {'+'.join(res['got'])}")
        elif res["status"] == "skip":
            skipped += 1
        else:
            errors += 1
            print(f"  [{i}/{len(files)}] {os.path.basename(path)} … {res.get('reason')}")

    # 日別サマリにも球場を反映
    for d in touched_dirs:
        update_summary(d)

    print(f"[INFO] 完了: 更新{updated} / スキップ{skipped} / 失敗{errors}")
    if updated:
        print("[INFO] このあと rebuild_stats.py と build_dataset.py を実行すると"
              "集計とデータセットにも反映されます")
    return 0


if __name__ == "__main__":
    sys.exit(main())
