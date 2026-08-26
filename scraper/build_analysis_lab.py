"""保存済みデータから分析ラボ用JSONを再生成する。"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.analysis_lab import (
    build_aging,
    build_backtest,
    build_condition_cube,
    build_quality,
    build_re24,
    build_similarity,
    build_wpa,
)


JST = timezone(timedelta(hours=9))


def load_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def load_csv(path):
    try:
        with open(path, encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))
    except OSError:
        return []


def build(season, base="data"):
    root = os.path.join(base, str(season))
    dataset = os.path.join(root, "dataset")
    games = load_csv(os.path.join(dataset, "games.csv"))
    atbats = load_csv(os.path.join(dataset, "atbats.csv"))
    pitches = load_csv(os.path.join(dataset, "pitches.csv"))
    batting_lines = load_csv(os.path.join(dataset, "batting_lines.csv"))
    pitching_lines = load_csv(os.path.join(dataset, "pitching_lines.csv"))
    players = (load_json(os.path.join(root, "players", "stats.json"), {}) or {}).get("players", [])
    profiles = (load_json(os.path.join(base, "masters", "player_profiles.json"), {}) or {}).get("players", [])
    if not games or not atbats or not players:
        raise RuntimeError("games / atbats / players の必須データがありません")

    re24 = build_re24(atbats)
    re24.pop("observations", None)
    output = {
        "season": str(season),
        "version": "1.0.0",
        "generated_at": datetime.now(JST).isoformat(),
        "principles": [
            "実測値・推定値・算出不能を区別する",
            "標本数とデータ取得率を併記する",
            "未来情報を学習期間へ混ぜず時系列で検証する",
        ],
        "aging": build_aging(profiles),
        "quality": build_quality(games, atbats, pitches, batting_lines, pitching_lines),
        "re24": re24,
        "wpa_est": build_wpa(atbats, games),
        "condition_cube": build_condition_cube(atbats),
        "similarity": build_similarity(players),
        "backtest": build_backtest(batting_lines, pitching_lines),
    }
    path = os.path.join(root, "analysis_lab.json")
    with open(path + ".tmp", "w", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False, separators=(",", ":"))
    os.replace(path + ".tmp", path)
    print(
        f"[INFO] 分析ラボ: {len(games)}試合 / {len(atbats)}打席 / "
        f"RE24野手{len(re24['batters'])}人 / 条件セル{len(output['condition_cube'])}件 / "
        f"{os.path.getsize(path) / 1024 / 1024:.2f}MB"
    )
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", required=True)
    parser.add_argument("--base", default="data")
    args = parser.parse_args()
    try:
        build(args.season, args.base)
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
