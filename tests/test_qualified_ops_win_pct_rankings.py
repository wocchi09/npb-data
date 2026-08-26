import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class QualifiedOpsWinPctRankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_dashboard_ops_and_win_pct_use_qualified_lists(self):
        self.assertIn('rankBlock("OPS", qb,', self.html)
        self.assertIn('rankBlock("勝率", qp,', self.html)
        self.assertNotIn('rankBlock("OPS", lp,', self.html)
        self.assertNotIn('rankBlock("勝率", lp,', self.html)

    def test_season_auto_filter_includes_ops_and_win_pct(self):
        self.assertIn("var RATE_STATS = {avg:1, ops:1, era:1, win_pct:1};", self.html)
        self.assertIn("var STRICT_QUALIFIED_STATS = {ops:1, win_pct:1};", self.html)
        self.assertIn('!STRICT_QUALIFIED_STATS[seasonSort]', self.html)

    def test_dashboard_explains_qualification(self):
        self.assertIn("OPSは規定打席、勝率は規定投球回到達者のみ", self.html)


if __name__ == "__main__":
    unittest.main()
