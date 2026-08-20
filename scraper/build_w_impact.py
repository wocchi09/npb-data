"""Build the site-original W-Impact / W-Rating season leaderboard."""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.w_impact import BATTER_WEIGHTS, PITCHER_WEIGHTS, calculate
from lib.w_impact_trends import build_rolling_trends
from lib.ranking_changes import build_ranking_changes

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

    batting_lines = load_csv(f"{root}/dataset/batting_lines.csv")
    pitching_lines = load_csv(f"{root}/dataset/pitching_lines.csv")
    atbats = load_csv(f"{root}/dataset/atbats.csv")
    runner_events = load_csv(f"{root}/dataset/runner_events.csv")
    games = load_csv(f"{root}/dataset/games.csv")
    fip_constants = load_json(f"{root}/fip_constants.json") or {}

    result = calculate(
        pdata.get("players", []),
        tdata.get("teams", []),
        batting_lines,
        pitching_lines,
        atbats,
        runner_events,
    )
    output = {
        "season": str(season),
        "metric": "W-Impact",
        "version": "1.5.0",
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

    trend_result = build_rolling_trends(
        pdata.get("players", []), games, batting_lines, pitching_lines,
        atbats, runner_events, fip_constants,
    )
    trend_output = {
        "season": str(season),
        "metric": "W-Impact Trends",
        "version": "2.0.0",
        "generated_at": datetime.now(JST).isoformat(),
        "note": (
            "野手は出場、投手は登板を基準とする直近5試合・15試合の移動集計。"
            "欠場試合は数えず、W-Ratingは各期間の同一リーグ・"
            "同一投手役割で再標準化"
        ),
        **trend_result,
    }
    trend_path = f"{root}/w_impact_trends.json"
    with open(trend_path, "w", encoding="utf-8") as f:
        json.dump(trend_output, f, ensure_ascii=False, separators=(",", ":"))

    ranking_changes = build_ranking_changes(
        pdata.get("players", []), games, batting_lines, pitching_lines,
        atbats, runner_events, fip_constants, current_result=result,
    )
    ranking_output = {
        "season": str(season),
        "version": "1.0.0",
        "generated_at": datetime.now(JST).isoformat(),
        "note": (
            "シーズン累積W-Value順位を、最新試合日とその直前の試合日で比較。"
            "順位変動は前回順位－現在順位で、プラスが上昇です。"
        ),
        **ranking_changes,
    }
    ranking_path = f"{root}/w_impact_rank_changes.json"
    with open(ranking_path, "w", encoding="utf-8") as f:
        json.dump(ranking_output, f, ensure_ascii=False, separators=(",", ":"))
    print(
        f"[INFO] W-Impact: 野手{len(result['batters'])}人 / "
        f"投手{len(result['pitchers'])}人 / 総合{len(result['overall'])}人 / "
        f"推移{len(trend_result['players'])}人 / 順位変動2日比較"
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
