import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MatchupPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_dedicated_matchup_view_and_player_actions_exist(self):
        self.assertIn('id="matchupView"', self.html)
        self.assertIn('matchup:"matchupView"', self.html)
        self.assertIn("対投手成績を見る", self.html)
        self.assertIn("対打者成績を見る", self.html)
        self.assertIn("function openMatchups(key,kind)", self.html)

    def test_matchup_page_loads_preaggregated_player_json(self):
        self.assertIn('"/matchups/index.json?t="', self.html)
        self.assertIn('"/matchups/"+entry.file', self.html)
        self.assertIn('requestedView==="matchup"', self.html)
        self.assertIn('url.searchParams.set("player",matchupState.key)', self.html)

    def test_filters_and_sample_size_warning_exist(self):
        for label in ("相手選手", "シーズン", "相手球団", "相手の左右", "最低対戦打席"):
            self.assertIn(label, self.html)
        self.assertIn("少数打席では数値が大きく振れる", self.html)
        self.assertIn("row.pa>=Math.max(5,matchupState.minPa)", self.html)

    def test_batter_and_pitcher_labels_are_distinct(self):
        self.assertIn('対打者別の被打撃成績', self.html)
        self.assertIn('対投手別の打撃成績', self.html)
        self.assertIn('投手の防御率・失点は個別打者へ正確に配分できない', self.html)
        self.assertIn('被OPS', self.html)

    def test_matchup_layout_is_mobile_responsive(self):
        self.assertIn('.matchup-controls{grid-template-columns:1fr 1fr;}', self.html)
        self.assertIn('.matchup-kpis{grid-template-columns:1fr;}', self.html)

    def test_readable_japanese_typography_is_applied(self):
        self.assertIn("family=Noto+Sans+JP:wght@400;500;600;700;800", self.html)
        self.assertIn("--font-ui:'Noto Sans JP'", self.html)
        self.assertIn("font-variant-numeric:tabular-nums lining-nums", self.html)
        self.assertIn("body *,button,input,select,textarea,svg text", self.html)


if __name__ == "__main__":
    unittest.main()
