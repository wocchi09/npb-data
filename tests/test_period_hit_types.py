import csv
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scraper"))

import build_dataset
from lib.awards import (
    aggregate_batter_period,
    aggregate_pitcher_period,
    score_weekly_batter,
    score_weekly_starter,
)
from rebuild_stats import blank_batting, calc_rate_stats, merge_official_batting


class PeriodHitTypesTest(unittest.TestCase):
    def test_awards_json_is_not_a_game(self):
        self.assertFalse(build_dataset._is_game_file(
            "data/2026/awards/weekly/2026-07-20.json"))
        self.assertFalse(build_dataset._is_game_file("data/2026/war.json"))
        self.assertFalse(build_dataset._is_game_file("data/2026/w_impact.json"))
        self.assertFalse(build_dataset._is_game_file("data/2026/w_impact_trends.json"))

    def test_batting_line_contains_hit_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            game_dir = os.path.join(tmp, "data", "2026", "07", "01")
            os.makedirs(game_dir)
            game = {
                "game_id": "1",
                "home": "巨人",
                "away": "阪神",
                "result": {"home_score": 0, "away_score": 1},
                "boxscore": {
                    "batting": {
                        "away": [{
                            "name": "テスト 選手", "player_id": "123",
                            "ab": 3, "runs": 1, "hits": 3, "rbi": 1,
                            "so": 0, "bb": 0, "hbp": 0, "sac": 0,
                            "sb": 0, "errors": 0, "hr": 1,
                        }],
                        "home": [],
                    },
                    "pitching": {"away": [], "home": []},
                },
                "atbats": [
                    {"valid": True, "batter": {"name": "テスト 選手", "player_id": "123"},
                     "result_summary": "左安打", "pitches": []},
                    {"valid": True, "batter": {"name": "テスト 選手", "player_id": "123"},
                     "result_summary": "右２塁打", "pitches": []},
                    {"valid": True, "batter": {"name": "テスト 選手", "player_id": "123"},
                     "result_summary": "右本塁打 ＋1点", "pitches": []},
                ],
            }
            with open(os.path.join(game_dir, "1.json"), "w", encoding="utf-8") as f:
                json.dump(game, f, ensure_ascii=False)

            base = os.path.join(tmp, "data")
            build_dataset.build("2026", base, "csv")
            path = os.path.join(base, "2026", "dataset", "batting_lines.csv")
            with open(path, encoding="utf-8-sig", newline="") as f:
                row = next(csv.DictReader(f))

            self.assertEqual(row["singles"], "1")
            self.assertEqual(row["doubles"], "1")
            self.assertEqual(row["triples"], "0")
            self.assertEqual(row["hr"], "1")
            self.assertEqual(row["unclassified_hits"], "0")

    def test_period_slg_uses_all_hit_types(self):
        agg = aggregate_batter_period([{
            "ab": 4, "hits": 4, "singles": 1, "doubles": 1,
            "triples": 1, "hr": 1, "bb": 0, "hbp": 0,
        }])
        self.assertEqual(agg["slg"], 2.5)
        self.assertEqual(agg["ops"], 3.5)
        self.assertEqual(agg["singles"], 1)
        self.assertEqual(agg["doubles"], 1)
        self.assertEqual(agg["triples"], 1)

    def test_period_award_output_contains_hit_type_counts(self):
        agg = aggregate_batter_period([{
            "ab": 4, "hits": 4, "singles": 1, "doubles": 1,
            "triples": 1, "hr": 1, "bb": 0, "hbp": 0,
        }])
        scored = score_weekly_batter(
            "テスト 選手", "巨人", "一", agg, [agg], 1,
        )
        self.assertEqual(scored["stats"]["singles"], 1)
        self.assertEqual(scored["stats"]["doubles"], 1)
        self.assertEqual(scored["stats"]["triples"], 1)

    def test_batter_small_sample_is_reduced_by_games_and_pa(self):
        agg = aggregate_batter_period([{
            "ab": 4, "hits": 2, "singles": 2, "doubles": 0,
            "triples": 0, "hr": 0, "bb": 0, "hbp": 0,
        }])
        scored = score_weekly_batter(
            "テスト 選手", "巨人", "一", agg, [agg], 24,
        )
        self.assertLess(scored["sample_coverage"], 0.1)
        self.assertLess(scored["sample_multiplier"], 0.7)
        self.assertEqual(scored["team_games"], 24)

    def test_one_start_is_penalized_in_month_but_not_week(self):
        agg = aggregate_pitcher_period([{
            "outs": 21, "earned_runs": 0, "runs_allowed": 0,
            "so": 8, "bb": 1, "hits_allowed": 3, "hr_allowed": 0,
            "decision": "勝",
        }])
        week = score_weekly_starter(
            "テスト 投手", "巨人", agg, [agg], team_games=6,
        )
        month = score_weekly_starter(
            "テスト 投手", "巨人", agg, [agg], team_games=24,
        )
        self.assertEqual(week["workload_multiplier"], 1)
        self.assertLess(month["workload_multiplier"], 0.7)
        self.assertLess(month["score"], week["score"])

    def test_season_walks_and_hit_by_pitch_are_separate(self):
        batting = blank_batting()
        merge_official_batting(batting, {
            "ab": 2, "hits": 1, "hr": 0, "rbi": 0,
            "bb": 1, "hbp": 1, "sac": 0, "so": 0,
            "runs": 0, "sb": 0, "errors": 0,
        })
        rates = calc_rate_stats(batting)
        self.assertEqual(batting["bb"], 1)
        self.assertEqual(batting["hbp"], 1)
        self.assertEqual(rates["obp"], 0.75)


if __name__ == "__main__":
    unittest.main()
