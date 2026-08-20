import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RankingChangesPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_navigation_and_view_exist(self):
        self.assertIn("今日のランキング変動", self.html)
        self.assertIn('id="rankMoveView"', self.html)
        self.assertIn("else if(v===\"rankmove\") loadRankMovers()", self.html)

    def test_page_loads_generated_rank_change_data(self):
        self.assertIn('w_impact_rank_changes.json?t=', self.html)
        self.assertIn("rankMoveBadge", self.html)
        self.assertIn("最大上昇", self.html)
        self.assertIn("最大下降", self.html)
        self.assertIn("本日出場", self.html)

    def test_mobile_layout_hides_secondary_columns(self):
        self.assertIn("rankmove-hide-mobile", self.html)
        self.assertIn("@media(max-width:760px)", self.html)


if __name__ == "__main__":
    unittest.main()
