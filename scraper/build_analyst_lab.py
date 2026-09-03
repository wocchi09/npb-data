"""保存済みデータから NPB ANALYST LAB 用JSONを生成する。"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.analyst_lab import build_all


JST = timezone(timedelta(hours=9))


def load_csv(path):
    try:
        with open(path, encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return []


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8-sig") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def build(season, base="data"):
    root = os.path.join(base, str(season)); dataset = os.path.join(root, "dataset")
    inputs = {name: load_csv(os.path.join(dataset, name + ".csv")) for name in (
        "games", "atbats", "pitches", "batting_lines", "pitching_lines", "runner_events", "season_batting", "season_teams"
    )}
    if not inputs["games"] or not inputs["atbats"]:
        raise RuntimeError("games / atbats の必須データがありません")
    output = build_all(
        inputs["games"], inputs["atbats"], inputs["pitches"], inputs["batting_lines"],
        inputs["pitching_lines"], inputs["runner_events"], inputs["season_batting"], inputs["season_teams"],
        load_json(os.path.join(root, "w_impact.json"), {}) or {},
    )
    output.update({"season": str(season), "version": "1.0.0", "generated_at": datetime.now(JST).isoformat(),
                   "principles": ["標本数を表示", "相関と因果を区別", "取得できない値を推測しない"]})
    path = os.path.join(root, "analyst_lab.json")
    with open(path + ".tmp", "w", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False, separators=(",", ":"))
    os.replace(path + ".tmp", path)
    print(
        f"[INFO] ANALYST LAB: 仮説{len(output['hypotheses'])}件 / "
        f"投手コンディション{len(output['pitcher_condition']['games'])}登板 / "
        f"対戦{len(output['shrunk_matchups']['pairs'])}組 / "
        f"変化点{len(output['change_points']['batting']) + len(output['change_points']['pitching'])}件 / "
        f"{os.path.getsize(path) / 1024 / 1024:.2f}MB"
    )
    return output


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--season", required=True); parser.add_argument("--base", default="data")
    args = parser.parse_args()
    try:
        build(args.season, args.base); return 0
    except Exception as exc:
        print(f"[ERROR] {exc}"); return 1


if __name__ == "__main__":
    raise SystemExit(main())
