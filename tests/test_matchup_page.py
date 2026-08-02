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
        self.assertIn("最低'+ranked.minPa+'打席以上", self.html)
        self.assertIn("row.pa>=matchupState.minPa", self.html)

    def test_matchup_summary_uses_reliable_ops_rankings_for_batters(self):
        for label in (
            "対戦が多い打者 TOP5", "対戦が多い投手 TOP5",
            "抑えている打者 TOP5", "得意な投手 TOP5",
            "苦手な打者 TOP5", "苦手な投手 TOP5",
        ):
            self.assertIn(label, self.html)
        for label in ("打席", "打数", "安打", "四死球", "本塁打", "盗塁", "奪三振", "被OPS"):
            self.assertIn(label, self.html)
        self.assertIn("MATCHUP_RANKING_DEFAULT_MIN_PA=10", self.html)
        self.assertIn("function matchupRankingMinPa()", self.html)
        self.assertIn("row.pa>=minPa", self.html)
        self.assertIn("row.pa>=ranked.minPa", self.html)
        self.assertIn("Number(b.ops)||0)-(Number(a.ops)||0", self.html)
        self.assertIn("Number(a.ops)||0)-(Number(b.ops)||0", self.html)
        self.assertIn("Number(row.ops)>=.900", self.html)
        self.assertIn("Number(row.ops)<.600", self.html)

    def test_matchup_rankings_show_verdict_and_confidence(self):
        for label in ("超得意", "得意", "普通", "苦手", "超苦手"):
            self.assertIn(label, self.html)
        for stars in ("★★★★★", "★★★★☆", "★★★☆☆", "★★☆☆☆", "★☆☆☆☆"):
            self.assertIn(stars, self.html)
        self.assertIn("信頼度：", self.html)
        self.assertIn("matchup-rank-pa", self.html)
        self.assertIn(".matchup-verdict.good", self.html)
        self.assertIn("matchupRankCard(isPitcher?\"抑えている打者 TOP5\":\"得意な投手 TOP5\",ranked.good,isPitcher,true)", self.html)

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
