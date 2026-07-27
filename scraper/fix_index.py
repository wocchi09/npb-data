"""
index.json の作り直し
======================
data/index.json は「保存済みファイルの一覧」で、実ファイルから常に作り直せる。

複数の収集が同時に走ると index.json の中身が競合してpushに失敗するため、
競合したときはこのスクリプトで作り直して解決する。
（どちらか一方を選ぶのではなく、実際にあるファイルから正しい一覧を作る）

使い方:
    python scraper/fix_index.py
"""

import glob
import json
import os
import sys
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


def rebuild_index(base="data") -> int:
    if not os.path.isdir(base):
        print(f"[INFO] {base} がありません。何もしません。")
        return 0

    files = []
    for p in glob.glob(f"{base}/**/*.json", recursive=True):
        norm = p.replace("\\", "/")
        if norm == f"{base}/index.json":
            continue
        files.append(norm)
    files = sorted(set(files))

    path = os.path.join(base, "index.json")
    before = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                before = json.load(f).get("files")
        except Exception:
            before = None

    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": datetime.now(JST).isoformat(),
            "files": files,
        }, f, ensure_ascii=False, indent=2)

    if before is None:
        print(f"[INFO] index.json を作成しました（{len(files)}件）")
    elif before != files:
        print(f"[INFO] index.json を作り直しました（{len(before)}件 → {len(files)}件）")
    else:
        print(f"[INFO] index.json は最新です（{len(files)}件）")
    return len(files)


if __name__ == "__main__":
    rebuild_index()
    sys.exit(0)
