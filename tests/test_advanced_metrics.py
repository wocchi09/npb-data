import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scraper"))

from rebuild_stats import (  # noqa: E402
    _woba_parts,
    calc_league_batting_contexts,
    calc_pitching_rates,
    calc_rate_stats,
    calc_weighted_batting,
)


class AdvancedMetricsTest(unittest.TestCase):
    def batting_line(self):
        return {
            "games": 30,
            "pa": 110,
            "ab": 100,
            "runs": 18,
            "hits": 30,
            "singles": 20,
            "doubles": 6,
            "triples": 1,
            "hr": 3,
            "rbi": 20,
            "bb": 8,
            "ibb": 0,
            "hbp": 2,
            "so": 20,
            "sf": 0,
            "sh": 0,
            "gidp": 3,
            "gidp_opportunities": 20,
            "sb": 5,
            "caught_stealing": 2,
            "baserunning_outs": 1,
            "errors": 0,
        }

    def test_batting_metrics_are_calculated_from_recorded_events(self):
        result = calc_rate_stats(self.batting_line())
        self.assertEqual(result["bb_k"], 0.4)
        self.assertEqual(result["gpa"], 0.281)
        self.assertGreater(result["rc27"], 0)
        self.assertGreater(result["xr27"], 0)
        self.assertEqual(result["wsb"], 0.2)
        self.assertEqual(result["ubr_est"], -0.4)
        self.assertEqual(result["bsr_est"], -0.2)

    def test_weighted_metrics_use_each_league_context(self):
        line = self.batting_line()
        players = {"p1": {"team": "阪神"}}
        contexts = calc_league_batting_contexts({"p1": line}, players)
        weighted = calc_weighted_batting(line, contexts["セ"])
        self.assertIsNotNone(weighted["woba_est"])
        self.assertAlmostEqual(weighted["wraa_est"], 0.0, places=2)
        self.assertEqual(weighted["wrc_plus_est"], 100.0)

    def test_woba_recalculates_singles_from_hit_types(self):
        line = self.batting_line()
        expected = _woba_parts(line)
        line["singles"] = line["hits"] - line["hr"]  # 公式表の一時補完値
        self.assertEqual(_woba_parts(line), expected)

    def test_pitching_rate_metrics(self):
        result = calc_pitching_rates({
            "outs": 90,
            "batters_faced": 130,
            "hits_allowed": 25,
            "hr_allowed": 3,
            "so": 35,
            "bb": 10,
            "hbp": 2,
            "runs_allowed": 12,
            "earned_runs": 10,
            "wins": 3,
            "losses": 1,
            "holds_est": 0,
            "relief_wins": 0,
        })
        self.assertEqual(result["hr9"], 0.9)
        self.assertEqual(result["k_pct"], 0.269)
        self.assertEqual(result["bb_pct"], 0.077)
        self.assertEqual(result["k_bb"], 3.5)
        self.assertIsNotNone(result["lob_pct_est"])


if __name__ == "__main__":
    unittest.main()
