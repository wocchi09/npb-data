import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scraper"))

from lib.war import (  # noqa: E402
    calc_batter_war,
    calc_pitcher_war,
    league_run_env,
    replacement_fip,
    replacement_level,
)


class WarTest(unittest.TestCase):
    def setUp(self):
        self.players = [
            {
                "name": "規定打者",
                "team": "阪神",
                "position": "遊",
                "positions": [{"pos": "遊", "games": 40}],
                "batting": {
                    "games": 40, "pa": 150, "ops": 0.850,
                    "runs": 25, "sb": 5,
                },
            },
            {
                "name": "控え打者",
                "team": "阪神",
                "position": "一",
                "batting": {
                    "games": 20, "pa": 60, "ops": 0.650,
                    "runs": 8, "sb": 0,
                },
            },
            {
                "name": "投手",
                "team": "阪神",
                "position": "投",
                "pitching": {"outs": 90, "innings": "30", "fip": 2.50},
            },
        ]
        self.team_games = {"阪神": 40}

    def test_replacement_level_uses_non_qualified_batters(self):
        replacement = replacement_level(self.players, self.team_games)
        self.assertEqual(replacement["セ"]["ops"], 0.650)
        self.assertEqual(replacement["セ"]["players"], 1)

    def test_batter_war_contains_expected_components(self):
        env = league_run_env(self.players)
        replacement = replacement_level(self.players, self.team_games)
        result = calc_batter_war(
            self.players[0], env, replacement, self.team_games
        )
        self.assertIsNotNone(result)
        self.assertTrue(result["qualified"])
        self.assertGreater(result["components"]["r_bat"], 0)
        self.assertGreater(result["components"]["r_pos"], 0)

    def test_pitcher_war_uses_fip_and_real_innings(self):
        env = {"セ": {"rpw": 10.0}}
        replacement = {"セ": {"fip": 4.50}}
        result = calc_pitcher_war(self.players[2], env, replacement)
        self.assertIsNotNone(result)
        self.assertEqual(result["war"], 0.67)
        self.assertEqual(result["components"]["innings"], 30.0)

    def test_replacement_fip_is_league_era_plus_one(self):
        result = replacement_fip({
            "セ": {"league_era": 3.26},
            "パ": {"league_era": 3.51},
        })
        self.assertEqual(result["セ"]["fip"], 4.26)
        self.assertEqual(result["パ"]["fip"], 4.51)

    def test_missing_inputs_do_not_create_a_war_row(self):
        env = {"セ": {"rpw": 10.0}}
        replacement = {"セ": {"ops": 0.650}}
        player = {
            "team": "阪神",
            "batting": {"games": 1, "pa": 4, "ops": None},
        }
        self.assertIsNone(
            calc_batter_war(player, env, replacement, self.team_games)
        )


if __name__ == "__main__":
    unittest.main()
