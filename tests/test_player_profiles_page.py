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

    def test_detail_shows_profile_and_yearly_career_stats(self):
        for label in (
            "生年月日", "ふりがな", "経歴・出身校", "ドラフト", "出身地",
            "NPB年度別・通算成績", "年度別・通算打撃成績", "年度別・通算投手成績",
            "NPB公式 個人年度別成績", "Yahoo!スポーツナビ",
        ):
            self.assertIn(label, self.html)
        self.assertIn("CAREER_BATTING_COLS", self.html)
        self.assertIn("CAREER_PITCHING_COLS", self.html)
        self.assertIn("function yearlyStatsTable", self.html)
        self.assertIn("profile.yearly_batting", self.html)
        self.assertIn("profile.yearly_pitching", self.html)

    def test_unknown_birthplace_is_not_inferred(self):
        self.assertIn("出身地は確認できるYahoo選手IDがない場合は未取得（推測なし）", self.html)
        scraper = (ROOT / "scraper" / "player_profiles.py").read_text(encoding="utf-8")
        self.assertIn('"birthplace": None', scraper)
        self.assertIn("parse_yahoo_birthplace", scraper)

    def test_weekly_workflow_exists(self):
        workflow = (ROOT / ".github" / "workflows" / "player_profiles.yml").read_text(encoding="utf-8")
        self.assertIn("scraper/player_profiles.py", workflow)
        self.assertIn('cron: "0 0 * * 1"', workflow)
        self.assertIn("timeout-minutes: 90", workflow)


if __name__ == "__main__":
    unittest.main()
