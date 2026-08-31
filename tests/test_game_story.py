import json
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GameStoryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_story_tab_and_explanation_exist(self):
        self.assertIn('["story","試合ストーリー"]', self.html)
        self.assertIn("function renderGameStory(g)", self.html)
        self.assertIn("公式WPAではなく", self.html)
        self.assertIn("story.pitching_changes", self.html)
        self.assertIn('src="game_story.js"', self.html)

    def test_home_has_direct_story_and_article_lab_links(self):
        script = (ROOT / "game_story.js").read_text(encoding="utf-8")
        self.assertIn('id:"story-lab-home-link"', script)
        self.assertIn('href:"story_insights.html"', script)
        self.assertIn('id:"article-lab-home-link"', script)
        self.assertIn('href:"article_lab.html"', script)
        self.assertIn("最新データから今日の記事ネタを見つけ", script)

    def test_every_game_has_inning_pitch_summary_and_filters(self):
        self.assertIn("回別配球サマリー", self.html)
        self.assertIn("function summarizeInningPitches(ps)", self.html)
        self.assertIn("function renderInningPitchSummary(ps,active,g)", self.html)
        self.assertIn('pitchFilter = {team:"all", pitcher:"all", type:"all", inning:"all"}', self.html)
        self.assertIn('<span class="lb">回</span><select id="fi"', self.html)
        self.assertIn("function setAnalysisInning(key)", self.html)
        self.assertIn('team: ab.fielding_team||"", batTeam: ab.batting_team||""', self.html)
        self.assertIn("ゾーン内率は5×5コース座標の中央3×3", self.html)
        self.assertNotIn("function renderHawksInningPitchSummary", self.html)

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_story_classifies_lead_events(self):
        script = r"""
const {buildGameStory}=require('./game_story.js');
const score=(a,h)=>[{team:'A',score:a},{team:'H',score:h}];
const ab=(inning,half,team,a,h,name)=>({inning,top_bottom:half,batting_team:team,
  batter:{name},pitcher:{name:'投手'},score_at:score(a,h),result_summary:'安打 ＋1点'});
const game={away:'A',home:'H',result:{away_score:2,home_score:3},atbats:[
  ab(1,'表','A',1,0,'先制打者'),ab(3,'裏','H',1,1,'同点打者'),
  ab(5,'表','A',2,1,'勝越打者'),ab(8,'裏','H',2,3,'逆転打者')]};
process.stdout.write(JSON.stringify(buildGameStory(game).events.map(x=>x.type)));
"""
        output = subprocess.check_output(
            ["node", "-e", script], cwd=ROOT, text=True, encoding="utf-8"
        )
        self.assertEqual(json.loads(output), ["先制", "同点", "勝ち越し", "逆転"])


if __name__ == "__main__":
    unittest.main()
