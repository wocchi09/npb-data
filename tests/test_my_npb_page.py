import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "index.html").read_text(encoding="utf-8")


class MyNpbPageTests(unittest.TestCase):
    def test_my_npb_is_rendered_at_top_of_dashboard(self):
        self.assertIn("function renderMyNpb(", HTML)
        self.assertIn('var h=renderMyNpb(latestDate,games,players,year)+\'<div class="dashgrid">\';', HTML)

    def test_my_npb_settings_are_local_only_and_limited_to_five_players(self):
        self.assertIn('var MY_NPB_KEY="npbMyNpbV1";', HTML)
        self.assertIn("localStorage.setItem(MY_NPB_KEY", HTML)
        self.assertIn(".slice(0,5)", HTML)
        self.assertIn("推し選手は5人まで登録できます", HTML)

    def test_my_npb_uses_existing_games_players_and_roster_data(self):
        self.assertIn("myNpbTeamGame(saved.team,latestDate,games)", HTML)
        self.assertIn("selected.map(myNpbPlayerCard)", HTML)
        self.assertIn('/roster/registration.json?t=', HTML)
        self.assertIn("一軍登録", HTML)

    def test_my_npb_has_mobile_layout_and_accessible_cards(self):
        self.assertIn("@media(max-width:560px)", HTML)
        self.assertIn(".mynpb-players{grid-template-columns:1fr}", HTML)
        self.assertIn('role="button" tabindex="0"', HTML)
