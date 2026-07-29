import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scraper"))

import main as scraper_main  # noqa: E402


class NonGameStateTest(unittest.TestCase):
    def test_detects_cancelled_and_no_game_states(self):
        for state in ("ノーゲーム", "降雨ノーゲーム", "試合中止"):
            with self.subTest(state=state):
                self.assertTrue(scraper_main.is_non_game_state(state))

    def test_does_not_match_completed_or_missing_state(self):
        for state in ("試合終了", "延長戦終了", None):
            with self.subTest(state=state):
                self.assertFalse(scraper_main.is_non_game_state(state))


class CollectDayNonGameTest(unittest.TestCase):
    def setUp(self):
        self.date = datetime(2026, 4, 26, tzinfo=scraper_main.JST)

    def test_all_non_games_record_the_day_without_saving_games(self):
        skipped = {
            "game_id": "2021038775",
            "skip": True,
            "skip_reason": "non_game",
            "state": "ノーゲーム",
            "atbats": [],
        }
        with (
            patch.object(scraper_main, "find_game_ids", return_value=["2021038775"]),
            patch.object(scraper_main, "clean_day_folder") as clean_day,
            patch.object(scraper_main, "collect_game", return_value=skipped),
            patch.object(
                scraper_main,
                "record_no_game_day",
                return_value="data/2026/no_games.json",
            ) as record_no_game,
            patch.object(scraper_main, "update_index") as update_index,
            patch.object(scraper_main, "save_game") as save_game,
            patch.object(scraper_main, "save_summary") as save_summary,
        ):
            result = scraper_main.collect_day(self.date)

        clean_day.assert_called_once_with(self.date)
        record_no_game.assert_called_once_with(self.date)
        update_index.assert_called_once_with(["data/2026/no_games.json"])
        save_game.assert_not_called()
        save_summary.assert_not_called()
        self.assertEqual(result["games"], 0)
        self.assertEqual(result["skipped"], 1)

    def test_mixed_day_saves_only_the_completed_game(self):
        cancelled = {
            "game_id": "cancelled",
            "skip": True,
            "skip_reason": "non_game",
            "state": "試合中止",
            "atbats": [],
        }
        completed = {
            "game_id": "completed",
            "atbats": [{"result": "安打"}],
            "pitch_count": 123,
        }
        with (
            patch.object(
                scraper_main,
                "find_game_ids",
                return_value=["cancelled", "completed"],
            ),
            patch.object(scraper_main, "clean_day_folder"),
            patch.object(
                scraper_main,
                "collect_game",
                side_effect=[cancelled, completed],
            ),
            patch.object(scraper_main, "record_no_game_day") as record_no_game,
            patch.object(
                scraper_main,
                "save_game",
                return_value="data/2026/04/26/completed.json",
            ) as save_game,
            patch.object(
                scraper_main,
                "save_summary",
                return_value="data/2026/04/26/summary.json",
            ),
            patch.object(scraper_main, "update_index") as update_index,
        ):
            result = scraper_main.collect_day(self.date)

        record_no_game.assert_not_called()
        save_game.assert_called_once_with(completed, self.date)
        update_index.assert_called_once_with(
            [
                "data/2026/04/26/completed.json",
                "data/2026/04/26/summary.json",
            ]
        )
        self.assertEqual(result["games"], 1)
        self.assertEqual(result["pitches"], 123)
        self.assertEqual(result["skipped"], 1)


if __name__ == "__main__":
    unittest.main()
