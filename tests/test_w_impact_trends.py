import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scraper"))

from lib.w_impact_trends import build_rolling_trends  # noqa: E402


class WImpactTrendsTest(unittest.TestCase):
    def test_builds_batter_and_pitcher_appearance_windows(self):
        players = [
            {"key": "b1", "name": "打者A", "team": "阪神", "position": "右"},
            {"key": "p1", "name": "投手A", "team": "阪神", "position": "投"},
        ]
        dates = [
            "2026-04-01", "2026-04-15", "2026-05-01",
            "2026-05-20", "2026-06-10", "2026-07-05",
        ]
        games = [
            {
                "date": day, "game_id": f"g{index}",
                "home": "阪神", "away": "巨人",
            }
            for index, day in enumerate(dates, 1)
        ]
        games.append({
            "date": "2026-06-20", "game_id": "missed",
            "home": "阪神", "away": "巨人",
        })
        batting = []
        pitching = []
        for index, day in enumerate(dates, 1):
            batting.append({
                "date": day, "game_id": f"g{index}", "player_key": "b1",
                "player": "打者A", "team": "阪神", "position": "右",
                "is_starter": "True", "ab": "4", "hits": "1", "singles": "1",
                "doubles": "0", "triples": "0", "hr": "0", "bb": "0",
                "hbp": "0", "sac": "0", "rbi": "2",
            })
            pitching.append({
                "date": day, "game_id": f"g{index}", "player_key": "p1",
                "player": "投手A", "team": "阪神", "is_starter": "True",
                "outs": "3", "earned_runs": "5" if index == 1 else "1",
                "so": "1", "bb": "0", "hbp": "0", "hr_allowed": "0",
                "decision": "",
            })
        result = build_rolling_trends(
            players, games, batting, pitching, [], [],
            {"constants": {"セ": {"constant": 3.0}}},
        )

        self.assertEqual(result["latest_date"], "2026-07-05")
        self.assertEqual(result["mode"], "player_appearances")
        self.assertEqual(result["windows"], [5, 15])
        batter = result["players"]["b1"]["batter"]
        pitcher = result["players"]["p1"]["pitcher"]
        self.assertEqual(len(batter["5"]), 5)
        self.assertEqual(len(batter["15"]), 6)
        self.assertEqual(batter["5"][0]["date"], "2026-04-15")
        self.assertEqual(batter["5"][-1]["games"], 5)
        self.assertEqual(batter["5"][-1]["pa"], 20)
        self.assertAlmostEqual(batter["5"][-1]["ops"], 0.5, places=3)
        self.assertEqual(batter["15"][-1]["games"], 6)
        self.assertEqual(pitcher["5"][-1]["games"], 5)
        self.assertEqual(pitcher["5"][-1]["era"], 9.0)
        self.assertEqual(pitcher["15"][-1]["games"], 6)
        self.assertEqual(pitcher["15"][-1]["era"], 15.0)
        self.assertIsNotNone(pitcher["5"][-1]["w_rating"])


if __name__ == "__main__":
    unittest.main()
