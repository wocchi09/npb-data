import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RosterAnnouncementsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_roster_view_is_available_from_stats_menu(self):
        self.assertIn("id=\"vb-roster\"", self.html)
        self.assertIn("id=\"rosterView\"", self.html)
        self.assertIn('else if(v==="roster") loadRosterAnnouncements()', self.html)

    def test_player_list_includes_registration_status(self):
        self.assertIn('["roster_status","一軍"]', self.html)
        self.assertIn('["registered_days","登録日数"]', self.html)
        self.assertIn('sel("plRegistered"', self.html)
        self.assertIn("一軍登録中のみ", self.html)

    def test_registration_days_are_calculated_for_selected_date(self):
        self.assertIn("function registeredDaysAt(player, selectedDate)", self.html)
        self.assertIn("登録日は含み、抹消日は含みません", self.html)
        self.assertIn("missing_dates", self.html)

    def test_registered_players_are_grouped_by_team(self):
        self.assertIn('class="roster-team-groups"', self.html)
        self.assertIn('class="roster-team-block"', self.html)
        self.assertIn("TEAM_ORDER_PA.concat(TEAM_ORDER_SE)", self.html)
        self.assertIn("data-roster-team", self.html)

    def test_daily_workflow_exists(self):
        workflow = (ROOT / ".github" / "workflows" / "roster_announcements.yml").read_text(encoding="utf-8")
        self.assertIn("scraper/roster_announcements.py", workflow)
        self.assertIn('cron: "35 13 * * *"', workflow)


if __name__ == "__main__":
    unittest.main()
