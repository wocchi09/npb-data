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
            "抑えている打者 TOP5", "OPS上位投手 TOP5",
            "苦手な打者 TOP5", "OPS下位投手 TOP5",
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
        self.assertIn("good:byOpsDesc.slice(0,5)", self.html)
        self.assertIn("bad:byOpsAsc.slice(0,5)", self.html)
        self.assertIn("Number(b.avg)||0", self.html)
        self.assertIn("同OPSなら打率、対戦打席数", self.html)
        self.assertIn("打率 '+matchupRate(item.avg)", self.html)

    def test_matchup_rankings_show_verdict_and_confidence(self):
        for label in ("超得意", "得意", "普通", "苦手", "超苦手", "参考"):
            self.assertIn(label, self.html)
        for stars in ("★★★★★", "★★★★☆", "★★★☆☆", "★★☆☆☆", "★☆☆☆☆"):
            self.assertIn(stars, self.html)
        self.assertIn("信頼度：", self.html)
        self.assertIn("matchup-rank-pa", self.html)
        self.assertIn(".matchup-verdict.good", self.html)
        self.assertIn("matchupRankCard(isPitcher?\"抑えている打者 TOP5\":\"OPS上位投手 TOP5\",ranked.good,isPitcher,true)", self.html)

    def test_each_matchup_row_shows_verdict_and_confidence_with_documented_rules(self):
        self.assertIn("<th>判定</th><th>信頼度</th>", self.html)
        self.assertIn("var rowVerdict=matchupVerdict(row,isPitcher)", self.html)
        self.assertIn("matchup-confidence-cell", self.html)
        self.assertIn("成績の良し悪しではなく、対戦サンプルの多さ", self.html)
        self.assertIn('if(pa<10)return {label:"参考",tone:"normal"}', self.html)
        self.assertIn("被OPS .600未満＝得意", self.html)

    def test_batter_and_pitcher_labels_are_distinct(self):
        self.assertIn('対打者別の被打撃成績', self.html)
        self.assertIn('対投手別の打撃成績', self.html)
        self.assertIn('投手の防御率・失点は個別打者へ正確に配分できない', self.html)
        self.assertIn('被OPS', self.html)

    def test_pitcher_page_has_selectable_pitch_heatmap(self):
        for label in (
            "投球コース・ヒートマップ", "集計範囲", "シーズン", "対チーム", "1試合",
            "対戦球団", "打者の左右", "球種", "表示指標", "投球数", "投球割合", "空振り率",
            "等高線", "5×5数値", "詳細条件", "開始日", "終了日", "対戦打者",
            "イニング", "投球前カウント", "アウト", "走者状況", "投球結果",
            "最低球速", "最高球速", "スイング率", "見逃しストライク率", "平均球速",
        ):
            self.assertIn(label, self.html)
        self.assertIn('"/pitch_heatmaps/index.json?t="', self.html)
        self.assertIn('"/pitch_heatmaps/"+entry.file', self.html)
        self.assertIn('id="pitchHeatmapView"', self.html)
        self.assertIn('function pitchHeatmapChanged()', self.html)
        self.assertIn('pitchHeatmapState.scope==="team"', self.html)
        self.assertIn('pitchHeatmapState.scope==="game"', self.html)
        self.assertIn('item.misses/item.swings', self.html)
        self.assertIn('function drawPitchHeatmapSurface()', self.html)
        self.assertIn('id="pitchHeatCanvas"', self.html)
        self.assertIn("5×5のコース区分を滑らかに補間", self.html)
        self.assertIn("実際の投球座標を直接描いたものではなく", self.html)
        self.assertIn('pitchHeatmapState.runners==="risp"', self.html)
        self.assertIn('pitchHeatmapState.speedMin', self.html)

    def test_matchup_layout_is_mobile_responsive(self):
        self.assertIn('.matchup-controls{grid-template-columns:1fr 1fr;}', self.html)
        self.assertIn('.matchup-kpis{grid-template-columns:1fr;}', self.html)
        self.assertIn('.pitch-heatmap-controls{grid-template-columns:1fr;}', self.html)
        self.assertIn('.pitch-heatmap-advanced-grid{grid-template-columns:1fr;}', self.html)
        self.assertIn('.pitch-heatmap-layout{grid-template-columns:1fr;}', self.html)

    def test_readable_japanese_typography_is_applied(self):
        self.assertIn("family=Noto+Sans+JP:wght@400;500;600;700;800", self.html)
        self.assertIn("--font-ui:'Noto Sans JP'", self.html)
        self.assertIn("font-variant-numeric:tabular-nums lining-nums", self.html)
        self.assertIn("body *,button,input,select,textarea,svg text", self.html)


if __name__ == "__main__":
    unittest.main()
