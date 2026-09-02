"""保存済みデータから NPB DECISION LAB 用JSONを生成する。"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.decision_lab import build_all


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
    root = os.path.join(base, str(season))
    dataset = os.path.join(root, "dataset")
    games = load_csv(os.path.join(dataset, "games.csv"))
    atbats = load_csv(os.path.join(dataset, "atbats.csv"))
    batting_lines = load_csv(os.path.join(dataset, "batting_lines.csv"))
    pitching_lines = load_csv(os.path.join(dataset, "pitching_lines.csv"))
    season_batting = load_csv(os.path.join(dataset, "season_batting.csv"))
    season_pitching = load_csv(os.path.join(dataset, "season_pitching.csv"))
    profiles = (load_json(os.path.join(base, "masters", "player_profiles.json"), {}) or {}).get("players", [])
    standings = load_json(os.path.join(root, "standings.json"), {}) or {}
    if not games or not atbats:
        raise RuntimeError("games / atbats の必須データがありません")
    output = build_all(
        games, atbats, batting_lines, pitching_lines, season_batting,
        season_pitching, profiles, standings, season,
    )
    output.update({
        "version": "1.0.0",
        "generated_at": datetime.now(JST).isoformat(),
        "principles": ["取得済みデータだけを使用", "推定値は前提を明示", "小標本は信頼度を下げる"],
    })
    path = os.path.join(root, "decision_lab.json")
    with open(path + ".tmp", "w", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False, separators=(",", ":"))
    os.replace(path + ".tmp", path)
    print(
        f"[INFO] DECISION LAB: 勝率曲線{len(output['win_probability']['games'])}試合 / "
        f"球場補正野手{len(output['adjusted_metrics']['hitters'])}人 / "
        f"変化検知{len(output['change_alerts']['batters']) + len(output['change_alerts']['pitchers'])}件 / "
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
