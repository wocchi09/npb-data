import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PersonalSocialPostingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_personal_page_is_hidden_until_enabled_on_device(self):
        self.assertIn('id="vb-social" style="display:none"', self.html)
        self.assertIn('params.get("share")==="1"', self.html)
        self.assertIn('localStorage.setItem(PERSONAL_POSTING_KEY,"1")', self.html)
        self.assertIn('social:"socialView"', self.html)
        self.assertIn('else if(v==="social") loadSocial()', self.html)

    def test_all_requested_team_hashtags_are_registered(self):
        expected = {
            "ソフトバンク": "#sbhawks",
            "日本ハム": "#lovefighters",
            "オリックス": "#bs2026",
            "楽天": "#rakuteneagles",
            "西武": "#seibulions",
            "ロッテ": "#chibalotte",
            "阪神": "#tigers",
            "DeNA": "#baystars",
            "巨人": "#giants",
            "中日": "#dragons",
            "広島": "#carp",
            "ヤクルト": "#swallows",
        }
        for team, hashtag in expected.items():
            self.assertIn(f'"{team}":"{hashtag}"', self.html)

    def test_npb_tag_and_relevant_team_tags_are_built(self):
        self.assertIn('return ["#NPB"].concat(', self.html)
        self.assertIn('TEAM_HASHTAGS[team]', self.html)
        self.assertIn('socialTags(teams)', self.html)

    def test_home_run_text_uses_team_abbreviation_and_detail(self):
        self.assertIn('var team=hrTeam(shell,hr);', self.html)
        self.assertIn('"（"+String(tMini(row.team)||"-")+"）"', self.html)
        self.assertIn('String(row.number)+"号 "', self.html)
        self.assertIn('String(row.detail||"")', self.html)

    def test_long_posts_are_split_with_safety_margin(self):
        self.assertIn('socialWeightedLength(probe)>250', self.html)
        self.assertIn('"（全"+total+"本・"+(index+1)+"/"+parts+"）"', self.html)
        self.assertIn('length+" / 280"', self.html)

    def test_x_composer_and_copy_actions_exist(self):
        self.assertIn('https://x.com/intent/post?text=', self.html)
        self.assertIn('navigator.clipboard.writeText(text)', self.html)
        self.assertIn('>Xで投稿</button>', self.html)
        self.assertIn('>本文をコピー</button>', self.html)

    def test_player_graph_gets_personal_post_action(self):
        self.assertIn('function pgPostPlayer(key)', self.html)
        self.assertIn('>X投稿文を作る</button>', self.html)
        self.assertIn('socialTags([player.team])', self.html)

    def test_mobile_social_layout_is_present(self):
        self.assertIn('.social-controls{grid-template-columns:repeat(2,minmax(0,1fr));}', self.html)
        self.assertIn('.social-actions .btn{flex:1;}', self.html)

    def test_social_date_is_fixed_to_yyyymmdd(self):
        self.assertIn('label>日付（yyyymmdd）</label>', self.html)
        self.assertIn('input type="text" inputmode="numeric" maxlength="8"', self.html)
        self.assertIn('function socialDateCompact(date)', self.html)
        self.assertIn('function socialDateISO(value)', self.html)
        self.assertIn('socialLoadDateInput(this.value)', self.html)

    def test_social_fields_do_not_overlap(self):
        self.assertIn('width:100%;box-sizing:border-box;', self.html)
        self.assertIn('@media(max-width:900px)', self.html)

    def test_daily_post_categories_are_available(self):
        expected = [
            "本日の本塁打",
            "試合結果",
            "勝敗・セーブ投手",
            "注目打者・投手",
            "先発投手成績",
            "日刊MVP",
            "日刊ベストメンバー",
            "シーズン節目",
        ]
        for label in expected:
            self.assertIn(label, self.html)
        self.assertIn("function socialPitcherHighlightPosts()", self.html)
        self.assertIn("num(row.so)>=10", self.html)

    def test_detailed_games_and_daily_awards_are_loaded(self):
        self.assertIn("gamePath(socialState.date,game.game_id)", self.html)
        self.assertIn('"/awards/daily/"+socialState.date+".json', self.html)
        self.assertIn('"/players/stats.json?t="', self.html)
        self.assertIn("socialState.games=loaded[0].filter(Boolean)", self.html)

    def test_abbreviated_decision_pitcher_names_resolve_to_full_names_and_teams(self):
        self.assertIn("function socialPitcherInfo(game,name,decision)", self.html)
        self.assertIn("rowName.indexOf(target)===0", self.html)
        self.assertIn("info.decision===decision", self.html)
        self.assertIn('parts.push(label+" "+info.name+(team?', self.html)

    def test_data_completeness_warning_is_rendered(self):
        self.assertIn("function socialCompletenessText()", self.html)
        self.assertIn("未取得または試合途中のデータがあります", self.html)
        self.assertIn("全試合終了", self.html)
        self.assertIn('id="socialCompleteness"', self.html)

    def test_posting_history_and_next_unposted_navigation_exist(self):
        self.assertIn('var SOCIAL_HISTORY_KEY="npbPostingHistory"', self.html)
        self.assertIn("function socialTogglePosted(index)", self.html)
        self.assertIn("function socialNextUnposted()", self.html)
        self.assertIn("投稿済みにする", self.html)
        self.assertIn("この日をすべて未投稿に戻す", self.html)

    def test_template_and_no_homer_option_are_saved_locally(self):
        self.assertIn('var SOCIAL_TEMPLATE_KEY="npbPostingTemplate"', self.html)
        self.assertIn("function socialSaveTemplate()", self.html)
        self.assertIn('id="socialPrefix"', self.html)
        self.assertIn('id="socialSuffix"', self.html)
        self.assertIn('id="socialNoHr"', self.html)

    def test_milestones_are_season_only_and_latest_day_only(self):
        self.assertIn("socialState.date!==dashData.date", self.html)
        self.assertIn("今季\"+v+\"本塁打", self.html)
        self.assertIn("今季\"+v+\"安打", self.html)
        self.assertIn("今季\"+v+\"奪三振", self.html)
        self.assertIn("シーズン節目は最新日のみ判定", self.html)


if __name__ == "__main__":
    unittest.main()
