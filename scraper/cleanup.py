"""
不要な試合ファイルの掃除
=========================
過去のバグで保存された「中身のない試合ファイル」を検出して削除する。

対象:
  - 打席が0件のファイル（試合として成立していない）
  - 同じ試合IDが別の日にも保存されている重複（新しい方を残す）

既定では検出するだけで削除しない。実際に消すには --apply を付ける。

使い方:
    python scraper/cleanup.py --season 2026            # 確認だけ
    python scraper/cleanup.py --season 2026 --apply    # 実際に削除
"""

import argparse
import glob
import json
import os
import re
import sys


def find_game_files(season, base="data"):
    out = []
    for p in glob.glob(f"{base}/{season}/**/*.json", recursive=True):
        norm = p.replace("\\", "/")
        name = os.path.basename(norm)
        if name.startswith("_") or name == "index.json":
            continue
        if any(x in norm for x in (
                "/players/", "/teams/", "/dataset/", "/masters/", "/awards/")):
            continue
        out.append(norm)
    return sorted(out)


def day_of(path):
    m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", path)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def scan(season, base="data"):
    empties, dups = [], []
    by_gid = {}
    for path in find_game_files(season, base):
        try:
            with open(path, encoding="utf-8") as f:
                g = json.load(f)
        except Exception as e:
            print(f"[WARN] 読み込み失敗 {path}: {e}")
            continue
        n = g.get("atbat_count") or len(g.get("atbats") or [])
        if n <= 0:
            empties.append(path)
            continue
        gid = g.get("game_id")
        if gid:
            by_gid.setdefault(gid, []).append((day_of(path), path))

    # 重複はどちらが正しい日付かを試合IDから判断する。
    # スポナビの試合IDは YYYYMMDD で始まらないため、
    # 「試合ページのタイトル日付」を保存している場合はそれを使い、
    # 分からない場合は古い方（先に収集された方）を正とする。
    for gid, items in by_gid.items():
        if len(items) <= 1:
            continue
        items.sort()                          # 日付の古い順
        keep = items[0]                       # 既定は最初に収集された日
        # 試合データに開催日が入っていればそれを優先する
        for d, p in items:
            try:
                with open(p, encoding="utf-8") as f:
                    g = json.load(f)
            except Exception:
                continue
            gd = (g.get("game_date") or "").strip()
            if gd and gd == d:
                keep = (d, p)
                break
        for d, p in items:
            if (d, p) != keep:
                dups.append((gid, d, p))
    return empties, dups


def rebuild_summaries(base="data"):
    """_summary.json を実ファイルから作り直す"""
    fixed = 0
    for sdir in sorted({os.path.dirname(p) for p in glob.glob(f"{base}/*/*/*/*.json")}):
        games = []
        for p in sorted(glob.glob(f"{sdir}/*.json")):
            name = os.path.basename(p)
            if name.startswith("_"):
                continue
            try:
                with open(p, encoding="utf-8") as f:
                    g = json.load(f)
            except Exception:
                continue
            if (g.get("atbat_count") or 0) <= 0:
                continue
            games.append({
                "game_id": g.get("game_id"), "card": g.get("card"),
                "home": g.get("home"), "away": g.get("away"),
                "stadium": g.get("stadium"),
                "result": g.get("result", {}),
                "atbat_count": g.get("atbat_count", 0),
                "pitch_count": g.get("pitch_count", 0),
            })
        spath = os.path.join(sdir, "_summary.json")
        if games:
            d = os.path.basename(os.path.dirname(os.path.dirname(sdir)))
            m = re.search(r"/(\d{4})/(\d{2})/(\d{2})$", sdir.replace("\\", "/"))
            date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""
            with open(spath, "w", encoding="utf-8") as f:
                json.dump({"date": date, "game_count": len(games), "games": games},
                          f, ensure_ascii=False, indent=2)
            fixed += 1
        elif os.path.exists(spath):
            os.remove(spath)
    return fixed


def rebuild_index(base="data"):
    """index.json を実ファイルから作り直す"""
    files = []
    for p in glob.glob(f"{base}/**/*.json", recursive=True):
        norm = p.replace("\\", "/")
        if norm.endswith("/index.json"):
            continue
        files.append(norm)
    files = sorted(set(files))
    with open(os.path.join(base, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"files": files}, f, ensure_ascii=False, indent=2)
    return len(files)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2026")
    ap.add_argument("--base", default="data")
    ap.add_argument("--apply", action="store_true", help="実際に削除する")
    args = ap.parse_args()

    empties, dups = scan(args.season, args.base)
    print(f"[INFO] 打席0件のファイル: {len(empties)}件")
    for p in empties[:10]:
        print(f"    {p}")
    if len(empties) > 10:
        print(f"    …ほか{len(empties)-10}件")

    print(f"[INFO] 別日への重複保存: {len(dups)}件")
    for gid, d, p in dups[:10]:
        print(f"    {gid} ({d}) {p}")
    if len(dups) > 10:
        print(f"    …ほか{len(dups)-10}件")

    if not args.apply:
        print("\n[INFO] 確認のみです。実際に削除するには --apply を付けてください。")
        return 0

    removed = 0
    for p in empties:
        os.remove(p); removed += 1
    for gid, d, p in dups:
        if os.path.exists(p):
            os.remove(p); removed += 1
    print(f"\n[INFO] {removed}件を削除しました")

    n = rebuild_summaries(args.base)
    print(f"[INFO] _summary.json を {n}日ぶん作り直しました")
    n2 = rebuild_index(args.base)
    print(f"[INFO] index.json を作り直しました（{n2}ファイル）")
    print("[INFO] このあと rebuild_stats.py を実行すると集計に反映されます")
    return 0


if __name__ == "__main__":
    sys.exit(main())
