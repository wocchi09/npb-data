import unittest

from scraper.player_profiles import (
    iso_birthdate,
    normalized_name,
    parse_profile,
    parse_yahoo_birthplace,
    yahoo_player_index,
)


PROFILE_HTML = """
<html><body>
<div id="pc_v_name"><ul>
  <li id="pc_v_no">10</li><li id="pc_v_team">福岡ソフトバンクホークス</li>
  <li id="pc_v_name">上沢　直之</li><li id="pc_v_kana">うわさわ・なおゆき</li>
</ul></div>
<div id="pc_bio"><table>
  <tr><th>ポジション</th><td>投手</td></tr><tr><th>投打</th><td>右投右打</td></tr>
  <tr><th>身長／体重</th><td>188cm／89kg</td></tr>
  <tr><th>生年月日</th><td>1994年2月6日</td></tr>
  <tr><th>経歴</th><td>専大松戸高</td></tr><tr><th>ドラフト</th><td>2011年ドラフト6位</td></tr>
</table></div>
<table id="tablefix_p"><thead><tr>
  <th>年度</th><th>所属球団</th><th>登板</th><th>勝利</th><th>敗北</th><th>投球回</th><th>三振</th><th>防御率</th>
</tr></thead><tbody><tr><td class="year">2026</td><td class="team">福岡ソフトバンク</td><td>18</td><td>8</td><td>6</td><td>101.2</td><td>87</td><td>2.74</td></tr></tbody>
<tfoot><tr><th></th><th>通　算</th><th>212</th><th>89</th><th>72</th><th>1359<table><tr><td>.1</td></tr></table></th><th>1115</th><th>3.11</th></tr></tfoot></table>
<table id="tablefix_b"><thead><tr>
  <th>年度</th><th>所属球団</th><th>試合</th><th>打席</th><th>打数</th><th>安打</th><th>本塁打</th><th>打率</th><th>長打率</th><th>出塁率</th>
</tr></thead><tbody>
<tr><td class="year">2025</td><td class="team">北海道日本ハム</td><td>1</td><td>2</td><td>2</td><td>1</td><td>0</td><td>.500</td><td>.500</td><td>.500</td></tr>
<tr><td class="year">2025</td><td class="team">福岡ソフトバンク</td><td>2</td><td>3</td><td>3</td><td>1</td><td>0</td><td>.333</td><td>.333</td><td>.333</td></tr>
</tbody>
<tfoot><tr><th></th><th>通 算</th><th>212</th><th>32</th><th>28</th><th>3</th><th>0</th><th>.107</th><th>.143</th><th>.107</th></tr></tfoot></table>
</body></html>
"""


class PlayerProfileParserTests(unittest.TestCase):
    def test_profile_and_career_totals_are_parsed(self):
        player = parse_profile(
            PROFILE_HTML,
            "51355135",
            {"name": "上沢 直之", "team": "ソフトバンク", "number": "10"},
        )
        self.assertEqual(player["name"], "上沢 直之")
        self.assertEqual(player["reading"], "うわさわ・なおゆき")
        self.assertEqual(player["team"], "ソフトバンク")
        self.assertEqual(player["birthdate"], "1994-02-06")
        self.assertEqual(player["career"], "専大松戸高")
        self.assertEqual(player["draft"], "2011年ドラフト6位")
        self.assertIsNone(player["birthplace"])
        self.assertEqual(player["career_teams"], ["福岡ソフトバンク", "北海道日本ハム"])
        self.assertEqual(player["career_pitching"]["games"], 212)
        self.assertEqual(player["career_pitching"]["innings"], "1359.1")
        self.assertEqual(player["career_pitching"]["era"], 3.11)
        self.assertEqual(player["career_batting"]["plate_appearances"], 32)
        self.assertEqual(player["career_batting"]["batting_average"], 0.107)
        self.assertEqual(player["yearly_pitching"][0]["year"], "2026")
        self.assertEqual(player["yearly_pitching"][0]["games"], 18)
        self.assertEqual(player["yearly_pitching"][0]["innings"], "101.2")
        self.assertEqual(len(player["yearly_batting"]), 2)
        self.assertEqual(player["yearly_batting"][0]["team"], "北海道日本ハム")
        self.assertEqual(player["yearly_batting"][1]["team"], "福岡ソフトバンク")

    def test_absent_career_tables_remain_unknown(self):
        html = PROFILE_HTML.split('<table id="tablefix_p">')[0] + "</body></html>"
        player = parse_profile(html, "1", {"name": "新人 選手", "birthdate": "2000.01.02"})
        self.assertFalse(player["has_career_pitching"])
        self.assertFalse(player["has_career_batting"])
        self.assertIsNone(player["career_pitching"])
        self.assertIsNone(player["career_batting"])
        self.assertEqual(player["yearly_pitching"], [])
        self.assertEqual(player["yearly_batting"], [])
        self.assertEqual(player["birthdate"], "1994-02-06")

    def test_birthdate_formats(self):
        self.assertEqual(iso_birthdate("2001年12月3日"), "2001-12-03")
        self.assertEqual(iso_birthdate("2001.12.03"), "2001-12-03")
        self.assertIsNone(iso_birthdate("不明"))

    def test_yahoo_birthplace_is_parsed_without_guessing(self):
        html = '''<div class="bb-profile__item"><dt class="bb-profile__title">出身地</dt>
          <dd class="bb-profile__text">岡山</dd></div>'''
        self.assertEqual(parse_yahoo_birthplace(html), "岡山")
        self.assertIsNone(parse_yahoo_birthplace("<html></html>"))

    def test_yahoo_id_index_uses_team_and_only_unique_name_fallback(self):
        master = {"players": [
            {"name": "髙橋 光成", "team": "西武", "player_id": "1500056"},
            {"name": "同姓 同名", "team": "西武", "player_id": "1"},
            {"name": "同姓同名", "team": "巨人", "player_id": "2"},
        ]}
        by_team, by_unique = yahoo_player_index(master)
        self.assertEqual(by_team[(normalized_name("高橋光成"), "西武")], "1500056")
        self.assertEqual(by_unique[normalized_name("高橋光成")], "1500056")
        self.assertNotIn(normalized_name("同姓同名"), by_unique)


if __name__ == "__main__":
    unittest.main()
