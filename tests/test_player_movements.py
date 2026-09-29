import unittest
from pathlib import Path
from scraper.player_movements import TEAMS, category, destination, parse_transfers


def page(note="自由契約", player="テスト 選手", status="退団"):
    sections = []
    for index, team in enumerate(TEAMS):
        content = "データがありません"
        if team == "楽天":
            content = f'''<table class="bb-transferTable"><thead><tr>
            <th>更新日</th><th>状況</th><th>選手名</th><th>守備</th><th>備考</th>
            </tr></thead><tbody><tr><td>2026/9/28</td><td>{status}</td>
            <td><a href="/npb/player/123/top">{player}</a> ※</td><td>投手</td><td>{note}</td></tr></tbody></table>'''
        sections.append(f'<section id="{index}"><header><h3>{team}</h3></header>{content}</section>')
    return "".join(sections)


class PlayerMovementsTest(unittest.TestCase):
    def test_real_columns_and_source(self):
        row = parse_transfers(page())[0]
        self.assertEqual(row["name"], "テスト 選手")
        self.assertEqual(row["updated_date"], "2026-09-28")
        self.assertEqual(row["category"], "自由契約")
        self.assertTrue(row["development_player"])
        self.assertIsNone(row["destination"])
        self.assertEqual(row["source_url"], "https://baseball.yahoo.co.jp/npb/transfer#9")
        self.assertNotIn("announcement_date", row)

    def test_fa_stages_are_not_confused(self):
        for text, expected in [("国内FA権取得", "FA権取得"), ("海外ＦＡ宣言", "FA宣言"),
                               ("FA移籍", "FA移籍"), ("FA", "FA（区分未確認）"),
                               ("引退", "引退"), ("交換トレード", "トレード")]:
            self.assertEqual(category("退団", text), expected)

    def test_neutral_wording_keeps_original_source(self):
        row = parse_transfers(page("戦力外通告、育成契約を打診"))[0]
        self.assertEqual(row["category"], "自由契約")
        self.assertNotIn("戦力外", row["note"])
        self.assertIn("戦力外", row["source_note"])
        self.assertIn("打診", row["note"])

    def test_destinations_must_be_explicit(self):
        self.assertEqual(destination("ソフトバンクへ移籍"), "ソフトバンク")
        self.assertEqual(destination("移籍先：日本ハム"), "日本ハム")
        self.assertIsNone(destination("ソフトバンクとの対戦、今後は未定"))
        self.assertIsNone(destination("自由契約"))

    def test_bad_or_partial_html_fails(self):
        for html in ("", "<h1>Unavailable</h1>", page().replace("楽天", "不明球団"),
                     page().replace("<th>更新日</th>", "<th>発表日</th>"),
                     page().replace("2026/9/28", "不明")):
            with self.assertRaises(ValueError):
                parse_transfers(html)

    def test_explicit_empty_and_deduplication(self):
        empty = "".join(f'<section><h3>{t}</h3>データがありません</section>' for t in TEAMS)
        self.assertEqual(parse_transfers(empty), [])
        html = page()
        row = html.split("<tbody>")[1].split("</tbody>")[0]
        self.assertEqual(len(parse_transfers(html.replace(row, row + row))), 1)

    def test_home_link_and_table(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn('id:"movements-home-link"', (root / "game_story.js").read_text(encoding="utf-8"))
        html = (root / "contract_news.html").read_text(encoding="utf-8")
        self.assertIn('id="movements-body"', html)
        self.assertIn('src="player_movements.js"', html)


if __name__ == "__main__":
    unittest.main()
