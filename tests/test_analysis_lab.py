import unittest

from scraper.lib.analysis_lab import base_code, build_condition_cube, build_re24, runs_on_play


class AnalysisLabTest(unittest.TestCase):
    def row(self, no, **extra):
        data = {
            "game_id": "g1", "inning": "1", "top_bottom": "表",
            "atbat_no": str(no), "outs": "0", "r1": "", "r2": "", "r3": "",
            "batter": f"打者{no}", "pitcher": "投手", "batting_team": "A",
            "fielding_team": "B", "home": "B", "pa": "1", "ab": "1",
        }
        data.update(extra)
        return data

    def test_run_and_base_parsing(self):
        self.assertEqual(3, runs_on_play({"result": "＋2点", "rbi": "3"}))
        self.assertEqual("1-3", base_code({"r1": "1", "r2": "", "r3": "true"}))

    def test_re24_has_all_24_states(self):
        rows = [self.row(1, result="安打", hit="1", single="1", r1="1"),
                self.row(2, result="本塁打＋2点", hr="1", hit="1", rbi="2", outs="0"),
                self.row(3, result="三振", so="1", outs="1")]
        result = build_re24(rows)
        self.assertEqual(24, len(result["states"]))
        self.assertEqual(3, result["batters"][0]["pa"] if len(result["batters"]) == 1 else sum(x["pa"] for x in result["batters"]))

    def test_condition_uses_outs_before_play(self):
        rows = [self.row(1, result="三振", so="1", outs="1"), self.row(2, result="三振", so="1", outs="2")]
        cube = build_condition_cube(rows)
        self.assertEqual({"0", "1"}, {x["outs"] for x in cube})


if __name__ == "__main__":
    unittest.main()
