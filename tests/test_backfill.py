import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scraper"))

import backfill  # noqa: E402


def _atbat(idx, inning, top_bottom, valid=True, result=None, out=None):
    return {
        "index": idx, "inning": inning, "top_bottom": top_bottom,
        "valid": valid, "result_summary": result,
        "count": {"ball": 0, "strike": 0, "out": out},
        "pitches": [],
        "batter": {"name": "打者"} if valid else None,
        "pitcher": {"name": "投手"} if valid else None,
    }


class FindInterruptedHalfInningsTest(unittest.TestCase):
    def test_flags_a_non_final_half_inning_stuck_before_three_outs(self):
        g = {
            "atbats": [
                _atbat("0110100", 1, "表", result="三ゴロ", out=1),
                _atbat("0110200", 1, "表", result="併殺打", out=3),
                _atbat("0120100", 1, "裏", result="見逃し三振", out=1),
                _atbat("0120200", 1, "裏", result="1塁けん制", out=2),
                _atbat("0210100", 2, "表", result="三振", out=1),
            ]
        }
        groups = backfill.find_interrupted_half_innings(g)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0][-1]["index"], "0120200")
        self.assertTrue(backfill.needs_atbats(g))

    def test_ignores_the_games_last_half_inning(self):
        # サヨナラ・コールドなど、最後の半イニングがアウト3未満で終わるのは正常。
        g = {
            "atbats": [
                _atbat("0110100", 1, "表", result="三ゴロ", out=1),
                _atbat("0120100", 1, "裏", result="ボール", out=1),
            ]
        }
        self.assertEqual(backfill.find_interrupted_half_innings(g), [])
        self.assertFalse(backfill.needs_atbats(g))

    def test_normal_completed_innings_are_not_flagged(self):
        g = {
            "atbats": [
                _atbat("0110100", 1, "表", result="三ゴロ", out=1),
                _atbat("0110200", 1, "表", result="見逃し三振", out=2),
                _atbat("0110300", 1, "表", result="併殺打", out=3),
                _atbat("0120100", 1, "裏", result="安打", out=0),
            ]
        }
        self.assertEqual(backfill.find_interrupted_half_innings(g), [])
        self.assertFalse(backfill.needs_atbats(g))

    def test_empty_atbats_is_not_flagged(self):
        self.assertEqual(backfill.find_interrupted_half_innings({"atbats": []}), [])
        self.assertFalse(backfill.needs_atbats({"atbats": []}))
        self.assertFalse(backfill.needs_atbats({}))


class RepairAtbatsTest(unittest.TestCase):
    def test_recovers_the_missing_conclusion_and_updates_the_atbat_list(self):
        g = {
            "game_id": "2021039383", "away": "西武", "home": "ソフトバンク",
            "atbats": [
                _atbat("0110100", 1, "表", result="三ゴロ", out=1),
                _atbat("0120100", 1, "裏", result="見逃し三振", out=1),
                _atbat("0120200", 1, "裏", result="1塁けん制", out=2),
                _atbat("0210100", 2, "表", result="三振", out=1),
            ],
        }
        pages = {"0120201": _atbat("0120201", 1, "裏", result="見逃し三振", out=3)}
        discovered = {"0120200": ["0120201"]}

        def fake_fetch_atbat(game_id, idx):
            self.assertEqual(game_id, "2021039383")
            if idx == "0120200":
                return ("PAGE-0120200", g["atbats"][2])  # 中断ページを取り直した想定
            if idx in pages:
                return (f"PAGE-{idx}", pages[idx])
            return None

        def fake_extract(page):
            for idx, links in discovered.items():
                if page == f"PAGE-{idx}" or page == "PAGE-0120200" and idx == "0120200":
                    return links
            return []

        with (
            patch.object(backfill, "fetch_atbat", side_effect=fake_fetch_atbat),
            patch.object(backfill, "extract_atbat_indexes", side_effect=fake_extract),
        ):
            touched = backfill.repair_atbats(g)

        self.assertEqual(touched, ["1回裏: 1打席分を復元"])
        indexes = [a["index"] for a in g["atbats"]]
        self.assertEqual(indexes, ["0110100", "0120100", "0120200", "0120201", "0210100"])
        recovered = g["atbats"][3]
        self.assertEqual(recovered["result_summary"], "見逃し三振")
        self.assertEqual(recovered["count"]["out"], 3)
        self.assertEqual(recovered["batting_team"], "ソフトバンク")
        self.assertEqual(recovered["fielding_team"], "西武")

    def test_no_change_when_nothing_new_is_discoverable(self):
        g = {
            "game_id": "2021039383", "away": "西武", "home": "ソフトバンク",
            "atbats": [
                _atbat("0120100", 1, "裏", result="見逃し三振", out=1),
                _atbat("0120200", 1, "裏", result="1塁けん制", out=2),
                _atbat("0210100", 2, "表", result="三振", out=1),
            ],
        }
        before = [dict(a) for a in g["atbats"]]

        with (
            patch.object(backfill, "fetch_atbat", return_value=("PAGE", g["atbats"][1])),
            patch.object(backfill, "extract_atbat_indexes", return_value=[]),
        ):
            touched = backfill.repair_atbats(g)

        self.assertEqual(touched, [])
        self.assertEqual(g["atbats"], before)

    def test_needs_atbats_gates_backfill_game_and_updates_counts(self):
        g = {
            "game_id": "2021039383", "away": "西武", "home": "ソフトバンク",
            "atbats": [
                _atbat("0120100", 1, "裏", result="見逃し三振", out=1),
                _atbat("0120200", 1, "裏", result="1塁けん制", out=2),
                _atbat("0210100", 2, "表", result="三振", out=1),
            ],
        }
        for ab in g["atbats"]:
            ab["pitches"] = [{"no": 1}]

        def fake_fetch_atbat(game_id, idx):
            if idx == "0120200":
                return ("PAGE-0120200", g["atbats"][1])
            if idx == "0120201":
                extra = _atbat("0120201", 1, "裏", result="空振り三振", out=3)
                extra["pitches"] = [{"no": 1}, {"no": 2}]
                return ("PAGE-0120201", extra)
            return None

        # backfill_gameはpathからJSONを読み書きするので、一時ファイル経由で確認する。
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(g, f)
            path = f.name
        try:
            with (
                patch.object(backfill, "fetch_atbat", side_effect=fake_fetch_atbat),
                patch.object(backfill, "extract_atbat_indexes",
                             side_effect=lambda page: ["0120201"] if page == "PAGE-0120200" else []),
            ):
                result = backfill.backfill_game(path, ["atbats"])
            self.assertEqual(result["status"], "updated")
            self.assertEqual(result["got"], ["atbats"])
            with open(path, encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["atbat_count"], 4)
            self.assertEqual(saved["pitch_count"], 5)
            self.assertIn("backfilled_at", saved)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
