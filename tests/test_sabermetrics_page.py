import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SabermetricsPageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.data = json.loads(
            (ROOT / "data" / "2026" / "w_impact.json").read_text(encoding="utf-8")
        )

    def test_page_is_wired_into_navigation(self):
        self.assertIn('id="vb-sabermetrics"', self.html)
        self.assertIn('id="sabermetricsView"', self.html)
        self.assertIn('else if(v==="sabermetrics") loadSabermetrics()', self.html)

    def test_page_has_chart_commentary_and_optional_local_ai(self):
        self.assertIn("function saberBarChart", self.html)
        self.assertIn("function saberRadar", self.html)
        self.assertIn("function saberCommentary", self.html)
        self.assertIn("function saberGenerateAI", self.html)
        self.assertIn('typeof LanguageModel==="undefined"', self.html)
        self.assertNotIn("api.openai.com", self.html)

    def test_displayed_metrics_exist_in_generated_data(self):
        batter_keys = {
            "wrc_plus_est",
            "woba_est",
            "ops",
            "iso",
            "bb_pct",
            "k_pct",
            "bb_k",
            "rc27",
            "xr27",
            "bsr_est",
        }
        pitcher_keys = {
            "era",
            "fip",
            "whip",
            "k_pct",
            "bb_pct",
            "k_bb",
            "lob_pct_est",
            "k9",
        }

        qualified_batters = [
            row["stats"]
            for row in self.data["batters"]
            if row.get("stats", {}).get("qualified_pa")
        ]
        qualified_pitchers = [
            row["stats"]
            for row in self.data["pitchers"]
            if row.get("stats", {}).get("qualified_ip")
        ]

        self.assertTrue(qualified_batters)
        self.assertTrue(qualified_pitchers)
        for key in batter_keys:
            self.assertTrue(any(row.get(key) is not None for row in qualified_batters), key)
        for key in pitcher_keys:
            self.assertTrue(any(row.get(key) is not None for row in qualified_pitchers), key)


if __name__ == "__main__":
    unittest.main()
