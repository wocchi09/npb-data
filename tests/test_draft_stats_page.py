import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DraftStatsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")
        cls.profiles = json.loads(
            (ROOT / "data" / "masters" / "player_profiles.json").read_text(encoding="utf-8")
        )["players"]

    def test_draft_page_is_available_from_stats_navigation(self):
        self.assertIn('id="vb-draft"', self.html)
        self.assertIn("setView('draft')", self.html)
        self.assertIn('id="draftView"', self.html)
        self.assertIn('else if(v==="draft") loadDraftStats();', self.html)
        self.assertIn('requestedView==="draft"', self.html)

    def test_draft_year_is_parsed_only_from_recorded_profile_text(self):
        self.assertIn("function draftInfo(profile)", self.html)
        self.assertIn('var match=/^(\\d{4})年/.exec(text);', self.html)
        self.assertIn("if(!match) return null;", self.html)
        self.assertIn("未取得の選手は推測せず対象外", self.html)
        recorded = [player["draft"] for player in self.profiles if player.get("draft")]
        self.assertTrue(recorded)
        self.assertTrue(all(re.match(r"^\d{4}年", value) for value in recorded))

    def test_season_career_and_entry_filters_exist(self):
        for label in (
            "ドラフト年度別成績",
            "ドラフト年度",
            "NPB通算",
            "野手",
            "投手",
            "指名区分",
            "支配下",
            "育成",
        ):
            self.assertIn(label, self.html)
        self.assertIn('entry:/育成選手ドラフト/.test(text)?"development":"regular"', self.html)
        self.assertIn("profile.career_batting", self.html)
        self.assertIn("profile.career_pitching", self.html)
        self.assertIn("draftSeasonRows", self.html)
        self.assertIn("draftCareerRows", self.html)

    def test_player_names_open_existing_player_detail(self):
        self.assertIn("async function openCohortPlayer(npbId)", self.html)
        self.assertIn("showPlayerDetail(player.key)", self.html)
        self.assertIn("openCohortPlayer", self.html)


if __name__ == "__main__":
    unittest.main()
