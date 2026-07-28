import csv
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scraper"))

import build_dataset
from lib.awards import aggregate_batter_period


class PeriodHitTypesTest(unittest.TestCase):
    def test_awards_json_is_not_a_game(self):
        self.assertFalse(build_dataset._is_game_file(
            "data/2026/awards/weekly/2026-07-20.json"))

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


if __name__ == "__main__":
    unittest.main()
