import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PlayerProfilesPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_player_profiles_are_loaded_and_joined_by_npb_id(self):
        self.assertIn('data/masters/player_profiles.json?t=', self.html)
        self.assertIn("function playerProfileIndex()", self.html)
        self.assertIn("profile: profileIdx[String(r.npb_id)]||null", self.html)

    def test_detail_shows_profile_and_career_totals(self):
        for label in (
            "生年月日", "ふりがな", "経歴・出身校", "ドラフト", "NPB通算成績",
            "通算打撃成績", "通算投手成績", "NPB公式 個人年度別成績",
        ):
            self.assertIn(label, self.html)
        self.assertIn("CAREER_BATTING_COLS", self.html)
        self.assertIn("CAREER_PITCHING_COLS", self.html)

    def test_unknown_birthplace_is_not_inferred(self):
        self.assertIn("出身都道府県は公式個人成績ページに記載がないため推測していません", self.html)
        scraper = (ROOT / "scraper" / "player_profiles.py").read_text(encoding="utf-8")
        self.assertIn('"birthplace": None', scraper)

    def test_weekly_workflow_exists(self):
        workflow = (ROOT / ".github" / "workflows" / "player_profiles.yml").read_text(encoding="utf-8")
        self.assertIn("scraper/player_profiles.py", workflow)
        self.assertIn('cron: "0 0 * * 1"', workflow)
        self.assertIn("timeout-minutes: 60", workflow)


if __name__ == "__main__":
    unittest.main()
