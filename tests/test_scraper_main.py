import re
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


def _atbat(idx, valid=True, result=None, out=None, pitch_count=1):
    """collect_gameのテスト用: parse_atbatが返す辞書の最小版。"""
    return {
        "index": idx, "valid": valid, "result_summary": result,
        "count": {"ball": 0, "strike": 0, "out": out},
        "pitch_count": pitch_count, "pitches": [{"no": i + 1} for i in range(pitch_count)],
        "batter": {"name": "打者"} if valid else None,
        "pitcher": {"name": "投手"} if valid else None,
        "runners": {"code": "b000"}, "score_at": None,
    }


class LooksInterruptedAtBatTest(unittest.TestCase):
    def test_flags_mid_count_and_pickoff_or_balk_results_under_three_outs(self):
        for result in ("ボール", "見逃し", "空振り", "ボール ＋1点", "1塁けん制", "1塁けん制 アウト", "ボーク"):
            with self.subTest(result=result):
                self.assertTrue(scraper_main.looks_interrupted_atbat(_atbat("x", result=result, out=2)))

    def test_does_not_flag_real_conclusions_or_a_completed_third_out(self):
        self.assertFalse(scraper_main.looks_interrupted_atbat(_atbat("x", result="見逃し三振", out=1)))
        self.assertFalse(scraper_main.looks_interrupted_atbat(_atbat("x", result="遊ゴロ", out=1)))
        self.assertFalse(scraper_main.looks_interrupted_atbat(_atbat("x", result="ボール", out=3)))
        self.assertFalse(scraper_main.looks_interrupted_atbat(_atbat("x", result="ボール", out=None)))


class IsRecoverableAtbatTest(unittest.TestCase):
    """
    実データで実際に踏んだ回帰: 中断ページに埋め込まれたリンクの先が、
    続きの打席ではなく守備交代/投手交代の告知（打者番号00・投球0球、
    打者名が投手名と同じ）だったケース。これを打席として採用してはいけない。
    """

    def test_rejects_a_non_atbat_announcement_page_linked_from_order_zero(self):
        bogus = _atbat("0720000", result="【守備】平沢：（打）→（右）", out=0, pitch_count=0)
        bogus["batter"] = {"name": "隅田 知一郎"}
        bogus["pitcher"] = {"name": "隅田 知一郎"}
        self.assertFalse(scraper_main.is_recoverable_atbat(bogus))

    def test_rejects_zero_pitch_pages_even_with_a_normal_looking_order(self):
        self.assertFalse(scraper_main.is_recoverable_atbat(_atbat("0120201", pitch_count=0)))

    def test_rejects_invalid_pages(self):
        self.assertFalse(scraper_main.is_recoverable_atbat(_atbat("0120201", valid=False)))

    def test_accepts_a_real_continuation(self):
        self.assertTrue(scraper_main.is_recoverable_atbat(_atbat("0120201", result="見逃し三振", out=3)))


class CollectGameRecoversInterruptedAtBatTest(unittest.TestCase):
    """
    打者の連番だけを進める巡回だと、牽制/ボークで打席が中断された続きの
    ページ（連番の1つ先ではないindex）を取りこぼす。ページ内リンクから
    そのindexを見つけて追いかけられることを検証する。
    """

    def _run(self, pages, discovered):
        # pages: idx（またはNone=起点/statsページ） -> parse_atbat結果
        # discovered: idx（またはNone） -> そのページから見つかるindexのリスト
        def fake_fetch(url):
            m = re.search(r"index=(\w+)", url)
            return m.group(1) if m else ("STATS" if url.endswith("/stats") else "START")

        def fake_parse_atbat(page, idx):
            return pages[page]

        def fake_extract(page):
            return discovered.get(page, [])

        with (
            patch.object(scraper_main, "fetch", side_effect=fake_fetch),
            patch.object(scraper_main, "parse_atbat", side_effect=fake_parse_atbat),
            patch.object(scraper_main, "extract_atbat_indexes", side_effect=fake_extract),
            patch.object(scraper_main, "parse_teams", return_value={
                "home": "ソフトバンク", "away": "西武", "home_full": "ソフトバンク",
                "away_full": "西武", "date_text": None,
            }),
            patch.object(scraper_main, "parse_stadium", return_value=None),
            patch.object(scraper_main, "detect_game_type", return_value="公式戦"),
            patch.object(scraper_main, "parse_score_list", return_value=[]),
            patch.object(scraper_main, "parse_homeruns", return_value=[]),
            patch.object(scraper_main, "parse_battery", return_value={}),
            patch.object(scraper_main, "parse_stats_page", return_value={
                "batting": {"away": [], "home": []}, "pitching": {"away": [], "home": []},
            }),
        ):
            return scraper_main.collect_game("2021039383")

    def test_recovers_the_real_final_out_after_a_pickoff_interruption(self):
        # 1回表: 1人だけで終了。1回裏: 1人目は普通に完了、2人目(order2)は
        # 牽制で中断（アウト2）。連番の次(order3)は存在しないので通常の巡回は
        # ここで終わるが、order2のページ自身に本当の続き"0120201"へのリンクが
        # 埋まっている。2回・3回は打席なしで試合終了とみなす。
        pages = {
            "0110100": _atbat("0110100", result="三ゴロ", out=1),
            "0110200": _atbat("0110200", valid=False),
            "0120100": _atbat("0120100", result="見逃し三振", out=1),
            "0120200": _atbat("0120200", result="1塁けん制", out=2),
            "0120201": _atbat("0120201", result="見逃し三振", out=3),
            "0120300": _atbat("0120300", valid=False),
            "0210100": _atbat("0210100", valid=False),
            "0220100": _atbat("0220100", valid=False),
            "0310100": _atbat("0310100", valid=False),
            "0320100": _atbat("0320100", valid=False),
        }
        discovered = {"0120200": ["0120201"]}

        game = self._run(pages, discovered)

        indexes = [a["index"] for a in game["atbats"]]
        self.assertEqual(indexes, ["0110100", "0120100", "0120200", "0120201"])
        recovered = game["atbats"][-1]
        self.assertEqual(recovered["result_summary"], "見逃し三振")
        self.assertEqual(recovered["count"]["out"], 3)
        # 表/裏の補完もされている（本来register()が付与する）
        self.assertEqual(recovered["batting_team"], "ソフトバンク")

    def test_does_not_mistake_a_defensive_substitution_announcement_for_the_real_continuation(self):
        # 実データで実際に踏んだケース: 中断ページのリンクの先が守備交代の
        # 告知（打者番号00・投球0球）だけで、本当の続きが見つからない場合。
        # 中断状態のまま（余計なでっち上げ打席を挿入せず）巡回を終える。
        bogus = _atbat("0120000", result="【守備】平沢：（打）→（右）", out=0, pitch_count=0)
        bogus["batter"] = {"name": "隅田 知一郎"}
        bogus["pitcher"] = {"name": "隅田 知一郎"}
        pages = {
            "0110100": _atbat("0110100", result="三ゴロ", out=1),
            "0110200": _atbat("0110200", valid=False),
            "0120100": _atbat("0120100", result="見逃し三振", out=1),
            "0120200": _atbat("0120200", result="1塁けん制", out=2),
            "0120000": bogus,
            "0120300": _atbat("0120300", valid=False),
            "0210100": _atbat("0210100", valid=False),
            "0220100": _atbat("0220100", valid=False),
            "0310100": _atbat("0310100", valid=False),
            "0320100": _atbat("0320100", valid=False),
        }
        discovered = {"0120200": ["0120000"]}

        game = self._run(pages, discovered)

        indexes = [a["index"] for a in game["atbats"]]
        self.assertEqual(indexes, ["0110100", "0120100", "0120200"])
        self.assertEqual(game["atbats"][-1]["result_summary"], "1塁けん制")
        self.assertEqual(game["atbats"][-1]["count"]["out"], 2)

    def test_skips_a_bogus_link_and_still_finds_the_real_continuation(self):
        # 中断ページに守備交代の告知と本当の続きの両方がリンクされていても、
        # 告知の方は無視して本当の続きだけを採用する。
        bogus = _atbat("0120000", result="【守備】平沢：（打）→（右）", out=0, pitch_count=0)
        bogus["batter"] = {"name": "隅田 知一郎"}
        bogus["pitcher"] = {"name": "隅田 知一郎"}
        pages = {
            "0110100": _atbat("0110100", result="三ゴロ", out=1),
            "0110200": _atbat("0110200", valid=False),
            "0120100": _atbat("0120100", result="見逃し三振", out=1),
            "0120200": _atbat("0120200", result="1塁けん制", out=2),
            "0120000": bogus,
            "0120201": _atbat("0120201", result="見逃し三振", out=3),
            "0120300": _atbat("0120300", valid=False),
            "0210100": _atbat("0210100", valid=False),
            "0220100": _atbat("0220100", valid=False),
            "0310100": _atbat("0310100", valid=False),
            "0320100": _atbat("0320100", valid=False),
        }
        discovered = {"0120200": ["0120000", "0120201"]}

        game = self._run(pages, discovered)

        indexes = [a["index"] for a in game["atbats"]]
        self.assertEqual(indexes, ["0110100", "0120100", "0120200", "0120201"])

    def test_normal_half_innings_are_unaffected(self):
        # 牽制も中断もない、素直な巡回。発見の仕組みが余計な取得をしないことを確認する。
        pages = {
            "0110100": _atbat("0110100", result="三ゴロ", out=1),
            "0110200": _atbat("0110200", result="中安打", out=1),
            "0110300": _atbat("0110300", result="併殺打", out=3),
            "0110400": _atbat("0110400", valid=False),
            "0120100": _atbat("0120100", result="空振り三振", out=1),
            "0120200": _atbat("0120200", result="空振り三振", out=2),
            "0120300": _atbat("0120300", result="見逃し三振", out=3),
            "0120400": _atbat("0120400", valid=False),
            "0210100": _atbat("0210100", valid=False),
            "0220100": _atbat("0220100", valid=False),
            "0310100": _atbat("0310100", valid=False),
            "0320100": _atbat("0320100", valid=False),
        }
        game = self._run(pages, discovered={})

        indexes = [a["index"] for a in game["atbats"]]
        self.assertEqual(indexes, ["0110100", "0110200", "0110300", "0120100", "0120200", "0120300"])


if __name__ == "__main__":
    unittest.main()
