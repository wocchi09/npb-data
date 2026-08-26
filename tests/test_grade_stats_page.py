import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GradeStatsPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_grade_page_is_available_from_stats_navigation(self):
        self.assertIn('id="vb-grade"', self.html)
        self.assertIn("setView('grade')", self.html)
        self.assertIn('id="gradeView"', self.html)
        self.assertIn('else if(v==="grade") loadGradeStats();', self.html)

    def test_academic_year_uses_april_second_boundary(self):
        self.assertIn("function academicYearFromBirthdate", self.html)
        self.assertIn("(month<4||(month===4&&day===1))?year-1:year", self.html)
        self.assertIn('year+"年4月2日〜"+(year+1)+"年4月1日生まれ"', self.html)
        self.assertIn("Object.keys(counts).map(Number).sort", self.html)
        self.assertIn("years.map(function(year)", self.html)

    def test_season_and_career_batter_pitcher_views_exist(self):
        for label in ("学年別成績", "シーズン", "NPB通算", "野手", "投手"):
            self.assertIn(label, self.html)
        self.assertIn("profile.career_batting", self.html)
        self.assertIn("profile.career_pitching", self.html)
        self.assertIn("data/"+"\"+year+\""+"/players/stats.json", self.html)
        self.assertIn('gradeKind==="batter"&&profile.position==="投手"', self.html)

    def test_unknown_birthdates_are_not_assigned_a_grade(self):
        self.assertIn('if(!match) return null;', self.html)
        self.assertIn("生年月日を確認できた選手のみ", self.html)


if __name__ == "__main__":
    unittest.main()
