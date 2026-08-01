from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class InsightsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.script = (ROOT / "insights.js").read_text(encoding="utf-8")
        cls.styles = (ROOT / "insights.css").read_text(encoding="utf-8")

    def test_insights_is_grouped_under_analysis_navigation(self):
        self.assertIn("id=\"vb-insights\"", self.html)
        self.assertIn("id=\"insightsView\"", self.html)
        self.assertIn('else if(v==="insights"&&typeof loadInsights==="function") loadInsights()', self.html)
        self.assertIn('get("view")==="insights"', self.script)

    def test_all_requested_insight_sections_exist(self):
        for label in (
            "今日のまとめ",
            "選手カルテ",
            "対戦プレビュー",
            "好調・不調",
            "公示タイムライン",
            "球団ダッシュボード",
        ):
            with self.subTest(label=label):
                self.assertIn(label, self.script)

    def test_form_detection_declares_sample_limits(self):
        self.assertIn("直近5試合OPS", self.script)
        self.assertIn("直近3登板防御率", self.script)
        self.assertIn("信頼度", self.script)

    def test_existing_data_sources_are_reused(self):
        self.assertIn('loadSplitFile("batting_lines")', self.script)
        self.assertIn('loadSplitFile("pitching_lines")', self.script)
        self.assertIn('loadSplitFile("games")', self.script)
        self.assertIn("loadRegistrationData()", self.script)

    def test_mobile_layout_is_defined(self):
        self.assertIn("@media(max-width:680px)", self.styles)
        self.assertIn(".insight-tabs", self.styles)
        self.assertIn(".insight-team-grid", self.styles)


if __name__ == "__main__":
    unittest.main()
