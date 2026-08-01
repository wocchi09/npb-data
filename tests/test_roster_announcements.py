import unittest
from datetime import date

from scraper.roster_announcements import aggregate_snapshots, parse_announcement_page


def page(day="2026年7月31日"):
    return f"""
    <html><body>
      <h4>{day}の出場選手登録、登録抹消</h4>
      <h4>セントラル・リーグ</h4><div>
        <h5>出場選手登録</h5><div><table><tr>
          <td class="team">読売ジャイアンツ</td><td class="pos">投手</td>
          <td class="num">28</td><td><a href="/bis/players/11112222.html">山田　太郎</a></td>
        </tr></table></div>
        <h5>出場選手登録抹消</h5><div><table><tr>
          <td class="team">阪神タイガース</td><td class="pos">内野手</td>
          <td class="num">3</td><td><a href="/bis/players/99990000.html">佐藤　次郎</a></td>
        </tr></table></div>
      </div>
      <h4>パシフィック・リーグ</h4><div>
        <h5>出場選手登録</h5><div><table></table></div>
        <h5>出場選手登録抹消</h5><div><table></table></div>
      </div>
      <h4>出場選手一覧</h4><div class="three_column_wrap">
        <h5>読売ジャイアンツ</h5><div><table><tr>
          <td class="pos">投手</td><td class="num">28</td>
          <td><a href="/bis/players/11112222.html">山田　太郎</a></td>
        </tr></table></div>
        <h5>福岡ソフトバンクホークス</h5><div><table><tr>
          <td class="pos">外野手</td><td class="num">3</td>
          <td><a href="/bis/players/33334444.html">近藤　健介</a></td>
        </tr></table></div>
      </div>
    </body></html>
    """


class RosterAnnouncementTests(unittest.TestCase):
    def test_parse_daily_page(self):
        result = parse_announcement_page(page(), date(2026, 7, 31))
        self.assertEqual(result["registered_count"], 2)
        self.assertEqual(result["additions"][0]["npb_id"], "11112222")
        self.assertEqual(result["additions"][0]["team"], "巨人")
        self.assertEqual(result["removals"][0]["npb_id"], "99990000")
        self.assertIn("ソフトバンク", {player["team"] for player in result["registered"]})

    def test_rejects_wrong_date(self):
        with self.assertRaises(ValueError):
            parse_announcement_page(page(), date(2026, 7, 30))

    def test_registration_days_and_periods_use_snapshots(self):
        p = {"npb_id": "1", "name": "選手A", "team": "ソフトバンク", "position": "投", "number": "11"}
        snapshots = [
            {"date": "2026-03-26", "registered": [p], "additions": [], "removals": []},
            {"date": "2026-03-27", "registered": [p], "additions": [], "removals": []},
            {"date": "2026-03-28", "registered": [], "additions": [], "removals": [p]},
            {"date": "2026-03-29", "registered": [p], "additions": [p], "removals": []},
        ]
        result = aggregate_snapshots(snapshots, 2026, date(2026, 3, 26), date(2026, 3, 29))
        player = result["players"][0]
        self.assertEqual(player["registered_days"], 3)
        self.assertEqual(player["registration_count"], 2)
        self.assertTrue(player["current_registered"])
        self.assertEqual(player["last_deregistered"], "2026-03-28")
        self.assertEqual(player["periods"][0]["days"], 2)
        self.assertIsNone(player["periods"][1]["to"])

    def test_missing_snapshot_is_not_counted_or_treated_as_deregistration(self):
        p = {"npb_id": "1", "name": "選手A", "team": "ソフトバンク", "position": "投", "number": "11"}
        snapshots = [
            {"date": "2026-03-26", "registered": [p], "additions": [], "removals": []},
            {"date": "2026-03-28", "registered": [p], "additions": [], "removals": []},
        ]
        result = aggregate_snapshots(snapshots, 2026, date(2026, 3, 26), date(2026, 3, 28))
        player = result["players"][0]
        self.assertEqual(player["registered_days"], 2)
        self.assertEqual(player["registered_dates"], ["2026-03-26", "2026-03-28"])
        self.assertEqual(player["registration_count"], 1)
        self.assertEqual(player["periods"][0]["days"], 2)
        self.assertEqual(result["missing_dates"], ["2026-03-27"])


if __name__ == "__main__":
    unittest.main()
