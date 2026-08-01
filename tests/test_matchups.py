import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scraper"))

import build_matchups


class MatchupBuilderTests(unittest.TestCase):
    def test_aggregate_calculates_batter_and_pitcher_rates(self):
        rows = [
            self.row(result={"pa": 1, "ab": 1, "hit": 1, "double": 1, "rbi": 1}),
            self.row(game_id="g2", result={"pa": 1, "ab": 1, "so": 1}),
            self.row(game_id="g2", result={"pa": 1, "ab": 0, "bb": 1}),
        ]
        buckets, latest = build_matchups.aggregate(rows)
        batter = build_matchups._finish_opponent(buckets["batter"]["p1"]["opponents"]["p2"])
        pitcher = build_matchups._finish_opponent(buckets["pitcher"]["p2"]["opponents"]["p1"])

        self.assertEqual(latest, "2026-07-31")
        self.assertEqual(batter["games"], 2)
        self.assertEqual(batter["pa"], 3)
        self.assertEqual(batter["hits"], 1)
        self.assertEqual(batter["double"], 1)
        self.assertEqual(batter["avg"], 0.5)
        self.assertEqual(batter["obp"], 0.6667)
        self.assertEqual(batter["slg"], 1.0)
        self.assertEqual(batter["ops"], 1.6667)
        self.assertEqual(pitcher["ops"], batter["ops"])

    def test_write_matchups_creates_lightweight_player_files_and_index(self):
        buckets, latest = build_matchups.aggregate([self.row()])
        with tempfile.TemporaryDirectory() as temp:
            index = build_matchups.write_matchups("2026", buckets, latest, temp)
            batter_entry = index["batters"][0]
            player_path = Path(temp) / "2026" / "matchups" / batter_entry["file"]
            payload = json.loads(player_path.read_text(encoding="utf-8"))

            self.assertTrue(player_path.exists())
            self.assertEqual(payload["player"]["name"], "打者 一郎")
            self.assertEqual(payload["opponents"][0]["name"], "投手 二郎")
            self.assertTrue((Path(temp) / "2026" / "matchups" / "index.json").exists())

    def test_high_confidence_baserunning_is_added_to_both_sides(self):
        atbat = self.row()
        atbat["atbat_index"] = "0820300"
        buckets, _ = build_matchups.aggregate([atbat])
        event = {
            "game_id": atbat["game_id"],
            "event_sequence": "0820300",
            "player_key": atbat["batter_key"],
            "event_type": "stolen_base",
            "source": "result_detail_high_confidence",
        }
        added = build_matchups.add_baserunning_events(buckets, [atbat], [event])
        batter = buckets["batter"][atbat["batter_key"]]["opponents"][atbat["pitcher_key"]]
        pitcher = buckets["pitcher"][atbat["pitcher_key"]]["opponents"][atbat["batter_key"]]
        self.assertEqual(added, 1)
        self.assertEqual(batter["sb"], 1)
        self.assertEqual(pitcher["sb"], 1)

    def test_boxscore_only_steals_are_not_guessed_against_a_pitcher(self):
        atbat = self.row()
        atbat["atbat_index"] = "0820300"
        buckets, _ = build_matchups.aggregate([atbat])
        event = {
            "game_id": atbat["game_id"],
            "event_sequence": "1",
            "player_key": atbat["batter_key"],
            "event_type": "stolen_base",
            "source": "official_boxscore",
        }
        added = build_matchups.add_baserunning_events(buckets, [atbat], [event])
        batter = buckets["batter"][atbat["batter_key"]]["opponents"][atbat["pitcher_key"]]
        self.assertEqual(added, 0)
        self.assertEqual(batter["sb"], 0)

    @staticmethod
    def row(game_id="g1", result=None):
        row = {
            "date": "2026-07-31",
            "game_id": game_id,
            "batting_team": "ソフトバンク",
            "fielding_team": "日本ハム",
            "batter": "打者 一郎",
            "batter_id": "1",
            "batter_key": "p1",
            "bat_hand": "左打",
            "pitcher": "投手 二郎",
            "pitcher_id": "2",
            "pitcher_key": "p2",
            "pit_hand": "右投",
        }
        for field in build_matchups.COUNT_FIELDS:
            row[field] = 0
        row.update(result or {"pa": 1, "ab": 1, "hit": 1, "single": 1})
        return row


if __name__ == "__main__":
    unittest.main()
