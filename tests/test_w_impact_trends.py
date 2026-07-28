import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scraper"))

from lib.w_impact_trends import build_rolling_trends  # noqa: E402


class WImpactTrendsTest(unittest.TestCase):
    def test_builds_batter_and_pitcher_rolling_points(self):
        players = [
            {"key": "b1", "name": "打者A", "team": "阪神", "position": "右"},
            {"key": "p1", "name": "投手A", "team": "阪神", "position": "投"},
        ]
        games = [
            {"date": "2026-07-01", "game_id": "g1", "home": "阪神", "away": "巨人"},
            {"date": "2026-07-05", "game_id": "g2", "home": "巨人", "away": "阪神"},
        ]
        batting = [
            {
                "date": "2026-07-01", "game_id": "g1", "player_key": "b1",
                "player": "打者A", "team": "阪神", "position": "右",
                "is_starter": "True", "ab": "4", "hits": "2", "singles": "1",
                "doubles": "1", "triples": "0", "hr": "0", "bb": "0",
                "hbp": "0", "sac": "0", "rbi": "1",
            },
            {
                "date": "2026-07-05", "game_id": "g2", "player_key": "b1",
                "player": "打者A", "team": "阪神", "position": "右",
                "is_starter": "True", "ab": "3", "hits": "1", "singles": "0",
                "doubles": "0", "triples": "0", "hr": "1", "bb": "1",
                "hbp": "0", "sac": "0", "rbi": "2",
            },
        ]
        pitching = [{
            "date": "2026-07-05", "game_id": "g2", "player_key": "p1",
            "player": "投手A", "team": "阪神", "is_starter": "True",
            "outs": "18", "earned_runs": "2", "so": "6", "bb": "1",
            "hbp": "0", "hr_allowed": "1", "decision": "勝",
        }]
        result = build_rolling_trends(
            players, games, batting, pitching, [], [],
            {"constants": {"セ": {"constant": 3.0}}},
        )

        self.assertEqual(result["latest_date"], "2026-07-05")
        batter = result["players"]["b1"]["batter"]
        pitcher = result["players"]["p1"]["pitcher"]
        self.assertEqual(len(batter["7"]), 2)
        self.assertEqual(len(batter["30"]), 2)
        self.assertEqual(batter["7"][-1]["pa"], 8)
        self.assertAlmostEqual(batter["7"][-1]["ops"], 1.5, places=3)
        self.assertEqual(pitcher["7"][-1]["games"], 1)
        self.assertEqual(pitcher["7"][-1]["era"], 3.0)
        self.assertIsNotNone(pitcher["7"][-1]["w_rating"])


if __name__ == "__main__":
    unittest.main()
