"""Build the site-original W-Impact / W-Rating season leaderboard."""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.w_impact import BATTER_WEIGHTS, PITCHER_WEIGHTS, calculate

JST = timezone(timedelta(hours=9))


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def build(season, base="data"):
    root = f"{base}/{season}"
    pdata = load_json(f"{root}/players/stats.json")
    tdata = load_json(f"{root}/teams/stats.json")
    if not pdata or not tdata:
        print("[ERROR] players/stats.json または teams/stats.json がありません")
        return None

    result = calculate(
        pdata.get("players", []),
        tdata.get("teams", []),
        load_csv(f"{root}/dataset/batting_lines.csv"),
        load_csv(f"{root}/dataset/pitching_lines.csv"),
        load_csv(f"{root}/dataset/atbats.csv"),
        load_csv(f"{root}/dataset/runner_events.csv"),
    )
    output = {
        "season": str(season),
        "metric": "W-Impact",
        "version": "1.4.0",
        "generated_at": datetime.now(JST).isoformat(),
        "note": (
            "サイト独自の総合貢献指数。WAR・UZRではありません。"
            "守備はポジション難度、失策、守備交代、複数守備の参考評価であり、"
            "守備範囲は含みません。取得できない項目は推測していません。"
        ),
        "scale": {"average": 100, "excellent": 120, "elite": 140},
        "weights": {"batter": BATTER_WEIGHTS, "pitcher": PITCHER_WEIGHTS},
        **result,
    }
    path = f"{root}/w_impact.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(
        f"[INFO] W-Impact: 野手{len(result['batters'])}人 / "
        f"投手{len(result['pitchers'])}人 / 総合{len(result['overall'])}人"
    )
    return output


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--base", default="data")
    args = ap.parse_args()
    return 0 if build(args.season, args.base) is not None else 1


if __name__ == "__main__":
    sys.exit(main())
