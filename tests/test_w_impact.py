import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scraper"))

from lib.w_impact import (  # noqa: E402
    calculate,
    collect_batter_roles,
    positions_from_text,
)


class WImpactTest(unittest.TestCase):
    def test_positions_ignore_substitution_markers(self):
        self.assertEqual(positions_from_text("打一三"), ["一", "三"])
        self.assertEqual(positions_from_text("走右"), ["右"])
        self.assertEqual(positions_from_text("打"), [])

    def test_substitution_roles_are_counted_separately(self):
        roles = collect_batter_roles([
            {"player_key": "p1", "sub_type": "代打", "position": "打一",
             "ab": "1", "hits": "1", "bb": "0", "hbp": "0", "sac": "0", "rbi": "1"},
            {"player_key": "p1", "sub_type": "代走", "position": "走右",
             "runs": "1", "sb": "1"},
            {"player_key": "p1", "sub_type": "守備", "position": "右"},
        ])["p1"]
        self.assertEqual(roles["pinch_hit_apps"], 1)
        self.assertEqual(roles["pinch_run_apps"], 1)
        self.assertEqual(roles["def_sub_apps"], 1)
        self.assertEqual(dict(roles["position_apps"]), {"右": 1})

    def test_calculation_outputs_batter_pitcher_and_overall(self):
        players = [
            {"key": "b1", "name": "打者A", "team": "阪神", "position": "遊",
             "batting": {"games": 10, "pa": 40, "ops": .900, "hr": 2,
                         "rbi": 8, "sb": 2, "errors": 0}},
            {"key": "b2", "name": "打者B", "team": "阪神", "position": "一",
             "batting": {"games": 10, "pa": 40, "ops": .600, "hr": 0,
                         "rbi": 2, "sb": 0, "errors": 2}},
            {"key": "p1", "name": "投手A", "team": "阪神", "position": "投",
             "pitching": {"games": 2, "outs": 36, "fip": 2.5, "era": 2.0,
                          "k9": 9.0, "wins": 2, "saves": 0, "holds_est": 0}},
            {"key": "p2", "name": "投手B", "team": "阪神", "position": "投",
             "pitching": {"games": 2, "outs": 30, "fip": 5.0, "era": 5.0,
                          "k9": 5.0, "wins": 0, "saves": 0, "holds_est": 0}},
        ]
        batting_lines = [
            {"player_key": "b1", "position": "遊", "is_starter": "True"},
            {"player_key": "b2", "position": "一", "is_starter": "True"},
        ]
        pitching_lines = [
            {"player_key": "p1", "is_starter": "True", "is_qs": "True"},
            {"player_key": "p2", "is_starter": "True", "is_qs": "False"},
        ]
        result = calculate(
            players, [{"team": "阪神", "games": 10}],
            batting_lines, pitching_lines, [],
        )
        self.assertEqual(len(result["batters"]), 2)
        self.assertEqual(len(result["pitchers"]), 2)
        self.assertEqual(len(result["overall"]), 4)
        batter_a = next(x for x in result["batters"] if x["player_key"] == "b1")
        batter_b = next(x for x in result["batters"] if x["player_key"] == "b2")
        self.assertGreater(batter_a["w_rating"], batter_b["w_rating"])
        self.assertTrue(batter_a["stats"]["qualified_pa"])
        self.assertEqual(batter_a["stats"]["required_pa"], 31.0)
        pitcher_a = next(x for x in result["pitchers"] if x["player_key"] == "p1")
        pitcher_b = next(x for x in result["pitchers"] if x["player_key"] == "p2")
        self.assertGreater(pitcher_a["w_rating"], pitcher_b["w_rating"])
        self.assertTrue(pitcher_a["stats"]["qualified_ip"])
        overall_batter = next(x for x in result["overall"] if x["player_key"] == "b1")
        overall_pitcher = next(x for x in result["overall"] if x["player_key"] == "p1")
        self.assertTrue(overall_batter["qualified_pa"])
        self.assertTrue(overall_pitcher["qualified_ip"])


if __name__ == "__main__":
    unittest.main()
