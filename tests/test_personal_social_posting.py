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
        self.assertIn('.social-controls{grid-template-columns:1fr 1fr;}', self.html)
        self.assertIn('.social-actions .btn{flex:1;}', self.html)


if __name__ == "__main__":
    unittest.main()
