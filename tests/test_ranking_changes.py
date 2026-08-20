import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scraper"))

from lib.ranking_changes import build_ranking_changes  # noqa: E402


class RankingChangesTest(unittest.TestCase):
    def test_compares_latest_two_game_dates_and_marks_active_players(self):
        players = [
            {"key": "a", "player_id": "1", "name": "上昇", "team": "巨人", "position": "外"},
            {"key": "b", "player_id": "2", "name": "下降", "team": "巨人", "position": "内"},
        ]
        games = [
            {"date": "2026-04-01", "game_id": "g1", "home": "巨人", "away": "阪神"},
            {"date": "2026-04-02", "game_id": "g2", "home": "巨人", "away": "阪神"},
        ]
        batting = [
            {"date": "2026-04-01", "game_id": "g1", "player_key": "a", "player_id": "1", "player": "上昇", "team": "巨人", "ab": 1, "hits": 0},
            {"date": "2026-04-01", "game_id": "g1", "player_key": "b", "player_id": "2", "player": "下降", "team": "巨人", "ab": 1, "hits": 1, "singles": 1},
            {"date": "2026-04-02", "game_id": "g2", "player_key": "a", "player_id": "1", "player": "上昇", "team": "巨人", "ab": 1, "hits": 1, "hr": 1, "rbi": 4},
        ]
        result = build_ranking_changes(players, games, batting, [], [], [])

        self.assertEqual(result["previous_date"], "2026-04-01")
        self.assertEqual(result["current_date"], "2026-04-02")
        rows = result["leagues"]["セ"]["batter"]
        by_key = {row["player_key"]: row for row in rows}
        self.assertTrue(by_key["a"]["active_today"])
        self.assertFalse(by_key["b"]["active_today"])
        self.assertGreater(by_key["a"]["rank_change"], 0)

    def test_requires_two_game_dates(self):
        result = build_ranking_changes([], [], [], [], [], [])
        self.assertIsNone(result["current_date"])
        self.assertIsNone(result["previous_date"])


if __name__ == "__main__":
    unittest.main()
