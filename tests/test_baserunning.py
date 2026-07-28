import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scraper"))

from lib.baserunning import (  # noqa: E402
    aggregate_runner_events,
    collect_game_runner_events,
)


class BaserunningTest(unittest.TestCase):
    def setUp(self):
        self.players = [
            {"key": "p1", "player_id": "1", "name": "大盛 穂", "team": "広島"},
            {"key": "p2", "player_id": "2", "name": "佐藤 輝明", "team": "阪神"},
            {"key": "p3", "player_id": "3", "name": "佐藤 蓮", "team": "阪神"},
        ]

    def test_official_steals_and_only_high_confidence_outs_are_collected(self):
        game = {
            "game_id": "g1", "away": "広島", "home": "阪神",
            "boxscore": {"batting": {
                "away": [{"player_id": "1", "name": "大盛 穂", "sb": 2}],
                "home": [],
            }},
            "atbats": [
                {"batting_team": "広島", "inning": 2, "top_bottom": "表",
                 "result_detail": "盗塁失敗（大盛）"},
                {"batting_team": "広島", "inning": 5, "top_bottom": "表",
                 "result_detail": "暴走（大盛）、本塁上タッチアウト（大盛）"},
                {"batting_team": "広島", "inning": 7, "top_bottom": "表",
                 "result_detail": "暴走（大盛）、リプレー検証後判定覆る"},
                {"batting_team": "阪神", "inning": 8, "top_bottom": "裏",
                 "result_detail": "挟まれる（佐藤）"},
                {"batting_team": "広島", "inning": 9, "top_bottom": "表",
                 "result_detail": "本塁上タッチアウト（大盛）"},
            ],
        }
        rows, diag = collect_game_runner_events(game, self.players, "2026-07-28")
        agg = aggregate_runner_events(rows)["p1"]
        self.assertEqual(agg["sb"], 2)
        self.assertEqual(agg["caught_stealing"], 1)
        self.assertEqual(agg["baserunning_outs"], 1)
        self.assertEqual(agg["baserunning_runs"], -0.4)
        self.assertEqual(diag["overturned_skipped"], 1)
        self.assertEqual(diag["unresolved"], 1)
        self.assertEqual(len(rows), 4)


if __name__ == "__main__":
    unittest.main()
