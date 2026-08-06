import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scraper"))

import build_pitch_heatmaps


class PitchHeatmapBuilderTests(unittest.TestCase):
    def test_aggregate_groups_games_and_encodes_filters(self):
        rows = [
            self.row(),
            self.row(game_id="g2", date="2026-08-01", opponent="阪神", pitch_type="フォーク", hand="右打", row="4", col="1", swing="False", miss="False"),
            self.row(game_id="g2", date="2026-08-01", row="9"),
        ]
        pitchers, latest = build_pitch_heatmaps.aggregate(rows)
        item = pitchers["p2"]

        self.assertEqual(latest, "2026-08-01")
        self.assertEqual(item["pitch_types"], ["ストレート", "フォーク"])
        self.assertEqual(len(item["games"]), 2)
        self.assertEqual(item["batters"][0]["name"], "打者 一郎")
        self.assertEqual(item["games"]["g1"]["home"], "日本ハム")
        self.assertEqual(item["games"]["g1"]["stadium"], "エスコン")
        self.assertEqual(item["games"]["g1"]["p"][0], [7, 0, 2, 1, 1, 7, 1, 2, 2, 5, 3, 148, 0])
        self.assertEqual(item["games"]["g2"]["p"][0], [21, 1, 1, 0, 0, 7, 1, 2, 2, 5, 2, 148, 0])

    def test_build_writes_lightweight_player_file_and_index(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "2026" / "dataset"
            source.mkdir(parents=True)
            rows = [self.row(), self.row(game_id="g2", date="2026-08-01", opponent="阪神")]
            with (source / "pitches.csv").open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
                writer.writeheader()
                writer.writerows(rows)

            index = build_pitch_heatmaps.build("2026", temp)
            entry = index["pitchers"][0]
            payload_path = Path(temp) / "2026" / "pitch_heatmaps" / entry["file"]
            payload = json.loads(payload_path.read_text(encoding="utf-8"))

            self.assertEqual(entry["games"], 2)
            self.assertEqual(entry["pitches"], 2)
            self.assertEqual(payload["player"]["name"], "投手 二郎")
            self.assertEqual(payload["games"][1]["opponent"], "阪神")
            self.assertEqual(payload["batters"][0]["name"], "打者 一郎")
            self.assertTrue((Path(temp) / "2026" / "pitch_heatmaps" / "index.json").exists())

    @staticmethod
    def row(game_id="g1", date="2026-07-31", opponent="ソフトバンク", pitch_type="ストレート", hand="左打", row="1", col="2", swing="True", miss="True"):
        return {
            "date": date,
            "game_id": game_id,
            "batting_team": opponent,
            "fielding_team": "日本ハム",
            "home": "日本ハム",
            "away": opponent,
            "stadium": "エスコン",
            "batter": "打者 一郎",
            "batter_id": "1",
            "batter_key": "p1",
            "bat_hand": hand,
            "pitcher": "投手 二郎",
            "pitcher_id": "2",
            "pitcher_key": "p2",
            "pit_hand": "右投",
            "pitch_type": pitch_type,
            "zone_row": row,
            "zone_col": col,
            "is_swing": swing,
            "is_miss": miss,
            "is_called": "True" if str(miss).lower() == "false" else "False",
            "is_foul": "False",
            "is_ball": "False",
            "is_inplay": "False",
            "inning": "7",
            "balls_before": "1",
            "strikes_before": "2",
            "outs": "2",
            "r1": "True",
            "r2": "False",
            "r3": "True",
            "speed_kmh": "148",
        }


if __name__ == "__main__":
    unittest.main()
