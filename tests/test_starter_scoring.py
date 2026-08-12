import csv
import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scraper"))

from lib.awards import (  # noqa: E402
    _starter_innings_score,
    aggregate_pitcher_period,
    score_daily_starter,
    score_weekly_starter,
)
from build_period_awards import build_period  # noqa: E402


def starter_row(outs, strikeouts, hits, earned_runs=0, runs_allowed=0):
    return {
        "name": "テスト投手",
        "_team": "テスト球団",
        "innings": f"{outs / 3:.1f}",
        "outs": outs,
        "earned_runs": earned_runs,
        "runs_allowed": runs_allowed,
        "so": strikeouts,
        "bb": 0,
        "hbp": 0,
        "hits_allowed": hits,
        "hr_allowed": 0,
        "balk": 0,
        "decision": "勝",
        "is_starter": True,
    }


class StarterScoringTest(unittest.TestCase):
    def test_innings_keep_value_after_six(self):
        points = {"ip6": 15, "ip7": 17.5, "ip8": 18.75, "ip9": 20}
        self.assertEqual(_starter_innings_score(6, 20, points), 15)
        self.assertEqual(_starter_innings_score(7, 20, points), 17.5)
        self.assertEqual(_starter_innings_score(8, 20, points), 18.75)
        self.assertEqual(_starter_innings_score(9, 20, points), 20)

    def test_daily_hqs_seven_innings_beats_six_inning_qs(self):
        six = starter_row(18, 5, 5)
        seven = starter_row(21, 4, 6)
        context = {"winner": "テスト球団"}

        six_score = score_daily_starter(six, context)
        seven_score = score_daily_starter(seven, context)

        self.assertGreater(seven_score["score"], six_score["score"])
        self.assertEqual(six_score["breakdown"]["innings"], 15)
        self.assertEqual(seven_score["breakdown"]["innings"], 17.5)
        self.assertIn("QS", six_score["reasons"])
        self.assertIn("HQS", seven_score["reasons"])

    def test_period_hqs_beats_six_inning_qs(self):
        six = aggregate_pitcher_period([starter_row(18, 5, 5)])
        seven = aggregate_pitcher_period([starter_row(21, 4, 6)])
        # 百分位はリーグ全体で比較する。2人だけだと1位満点・2位0点に
        # なるため、実際の週間ランキングに近い人数と分布を用意する。
        pool = [six, seven] + [
            {"era": 0, "whip": 0.5 + i * 0.1, "so": i}
            for i in range(11)
        ]

        six_score = score_weekly_starter(
            "毛利 海大", "ロッテ", six, pool, team_games=3,
        )
        seven_score = score_weekly_starter(
            "上沢 直之", "ソフトバンク", seven, pool, team_games=4,
        )

        self.assertGreater(seven_score["score"], six_score["score"])
        self.assertEqual(six_score["breakdown"]["qs"], 12)
        self.assertEqual(seven_score["breakdown"]["qs"], 20)

    def test_complete_game_achievement_is_not_lost_to_innings_cap(self):
        complete = starter_row(27, 7, 8, earned_runs=2, runs_allowed=2)
        score = score_daily_starter(complete, {"winner": "テスト球団"})

        self.assertEqual(score["breakdown"]["innings"], 20)
        self.assertEqual(score["breakdown"]["achievement"], 2)
        self.assertIn("完投", score["reasons"])

    def test_period_builder_uses_only_starts_and_starter_pool(self):
        fields = [
            "date", "player_key", "player", "team", "is_starter", "outs",
            "earned_runs", "runs_allowed", "so", "bb", "hits_allowed",
            "hr_allowed", "decision",
        ]
        rows = [
            ["2026-08-04", "a", "先発兼任A", "ソフトバンク", "True", 18, 0, 0, 5, 0, 5, 0, "勝"],
            ["2026-08-04", "a", "先発兼任A", "ソフトバンク", "False", 3, 0, 0, 3, 0, 0, 0, ""],
            ["2026-08-04", "b", "先発B", "日本ハム", "True", 21, 1, 1, 4, 1, 5, 0, "敗"],
            ["2026-08-05", "c", "救援C", "ロッテ", "False", 3, 0, 0, 3, 0, 0, 0, ""],
        ]
        with tempfile.TemporaryDirectory() as base:
            dataset = os.path.join(base, "2026", "dataset")
            os.makedirs(dataset)
            with open(os.path.join(dataset, "pitching_lines.csv"), "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(fields)
                writer.writerows(rows)
            with open(os.path.join(dataset, "games.csv"), "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["date", "home", "away"])
                writer.writerow(["2026-08-04", "ソフトバンク", "日本ハム"])
                writer.writerow(["2026-08-05", "ロッテ", "楽天"])

            result = build_period(
                "weekly", "テスト週", "2026-08-03", "2026-08-09", "2026", base,
            )

        starters = result["leagues"]["パ"]["pitcher_ranking"]["先発"]
        mixed = next(row for row in starters if row["name"] == "先発兼任A")
        self.assertTrue(mixed["stat_line"].startswith("1試合 6.0回"))
        self.assertEqual(mixed["breakdown"]["innings"], 15)


if __name__ == "__main__":
    unittest.main()
