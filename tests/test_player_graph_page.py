import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PlayerGraphPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_navigation_and_view_are_registered(self):
        self.assertIn('id="vb-playergraph"', self.html)
        self.assertIn('id="playerGraphView"', self.html)
        self.assertIn('playergraph:"playerGraphView"', self.html)
        self.assertIn('else if(v==="playergraph") loadPlayerGraph()', self.html)

    def test_all_player_data_uses_prebuilt_lightweight_sources(self):
        self.assertIn("async function loadPlayerGraph", self.html)
        self.assertIn("getImpactTrends(year)", self.html)
        self.assertIn('players/stats.json?t=', self.html)
        self.assertNotIn("Promise.all(pgPlayers.map", self.html)

    def test_filters_comparison_and_metrics_exist(self):
        self.assertIn("function pgCandidates", self.html)
        self.assertIn("function pgAddPlayer", self.html)
        self.assertIn("pgSelectedKeys.length>=3", self.html)
        self.assertIn("選手名・背番号検索", self.html)
        for metric in ("OPS", "W-Rating", "W-Value", "防御率"):
            self.assertIn(metric, self.html)

    def test_chart_commentary_and_share_url_exist(self):
        self.assertIn("function pgChart", self.html)
        self.assertIn("function pgCommentary", self.html)
        self.assertIn("function pgShare", self.html)
        self.assertIn('view:"playergraph"', self.html)
        self.assertIn("記録のない項目は推測しません", self.html)

    def test_mobile_layout_is_supported(self):
        self.assertIn("@media(max-width:520px)", self.html)
        self.assertIn(".pg-layout{grid-template-columns:1fr;}", self.html)
        self.assertIn(".pg-chart-scroll", self.html)

    def test_stylish_chart_animation_and_tooltip_exist(self):
        self.assertIn("@keyframes pg-line-draw", self.html)
        self.assertIn('pathLength="1"', self.html)
        self.assertIn('class="latest-halo"', self.html)
        self.assertIn("function pgShowTooltip", self.html)
        self.assertIn('class="pg-chart-tooltip"', self.html)
        self.assertIn('linearGradient id="pg-gradient-', self.html)

    def test_animation_respects_accessibility_and_mobile_cost(self):
        self.assertIn("@media(prefers-reduced-motion:reduce)", self.html)
        self.assertIn(".pg-svg .area{display:none;}", self.html)
        self.assertIn(".pg-chart-stage::before{display:none;}", self.html)


if __name__ == "__main__":
    unittest.main()
