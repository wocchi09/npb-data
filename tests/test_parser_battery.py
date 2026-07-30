import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scraper"))

from parser import parse_battery  # noqa: E402


class BatteryParserTest(unittest.TestCase):
    def test_parses_home_and_away_batteries(self):
        html = """
        <table>
          <tbody>
            <tr><th class="bb-splitsTable__head--battery">バッテリー</th></tr>
            <tr><td class="bb-splitsTable__data">先発A、中継A - 捕手A</td></tr>
          </tbody>
        </table>
        <table>
          <tbody>
            <tr><th class="bb-splitsTable__head--battery">バッテリー</th></tr>
            <tr><td class="bb-splitsTable__data">先発B、抑えB - 捕手B</td></tr>
          </tbody>
        </table>
        """

        battery = parse_battery(html)

        self.assertEqual(battery["home"], "先発A、中継A - 捕手A")
        self.assertEqual(battery["away"], "先発B、抑えB - 捕手B")
        self.assertEqual(battery["text"], battery["home"])

    def test_keeps_legacy_text_for_single_battery(self):
        html = """
        <table><tbody>
          <tr><th class="bb-splitsTable__head--battery">バッテリー</th></tr>
          <tr><td class="bb-splitsTable__data">投手 - 捕手</td></tr>
        </tbody></table>
        """

        battery = parse_battery(html)

        self.assertEqual(
            battery,
            {"text": "投手 - 捕手", "home": "投手 - 捕手"},
        )


if __name__ == "__main__":
    unittest.main()
