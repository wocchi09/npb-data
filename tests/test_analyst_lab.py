import json
import unittest
from pathlib import Path

from scraper.lib.analyst_lab import batting_summary, build_elo, build_shrunk_matchups


ROOT = Path(__file__).resolve().parents[1]


class AnalystLabTests(unittest.TestCase):
    def test_page_navigation_and_daily_workflow_are_connected(self):
        html = (ROOT / "analyst_lab.html").read_text(encoding="utf-8")
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/daily.yml").read_text(encoding="utf-8")
        self.assertIn("NPB ANALYST LAB", html)
        self.assertIn("analyst_lab.html", index)
        self.assertIn("build_analyst_lab.py", workflow)
        for label in ("仮説検証", "采配", "投手状態", "配球", "縮小対戦", "球団レーダー", "選手層", "Elo", "変化点", "分析ノート"):
            self.assertIn(label, html)

    def test_generated_json_contains_all_sections(self):
        payload = json.loads((ROOT / "data/2026/analyst_lab.json").read_text(encoding="utf-8"))
        for key in ("hypotheses", "manager_decisions", "pitcher_condition", "pitch_sequences", "shrunk_matchups", "team_radar", "depth", "elo", "change_points"):
            self.assertIn(key, payload)
        self.assertEqual(5, len(payload["hypotheses"]))
        self.assertEqual(12, len(payload["team_radar"]["teams"]))
        self.assertEqual(12, len(payload["elo"]["teams"]))
        self.assertTrue(payload["pitcher_condition"]["games"])
        self.assertTrue(payload["pitch_sequences"]["players"])

    def test_batting_summary_accepts_dataset_plural_columns(self):
        summary = batting_summary([{"ab": "4", "hits": "2", "singles": "1", "doubles": "1", "bb": "1"}])
        self.assertEqual(2, summary["hit"])
        self.assertEqual(0.5, summary["avg"])
        self.assertEqual(1.35, summary["ops"])

    def test_matchup_shrinkage_moves_small_sample_toward_average(self):
        rows = []
        for i in range(5):
            rows.append({"batter_key": "b", "batter": "打者", "batting_team": "A", "pitcher_key": "p", "pitcher": "投手", "fielding_team": "B", "ab": "1", "hit": "1", "single": "1"})
        for i in range(20):
            rows.append({"batter_key": "other", "batter": "別打者", "batting_team": "A", "pitcher_key": "other-p", "pitcher": "別投手", "fielding_team": "B", "ab": "1"})
        result = build_shrunk_matchups(rows)
        pair = next(row for row in result["pairs"] if row["batter_key"] == "b")
        prior_ops = result["league_prior"]["obp"] + result["league_prior"]["slg"]
        self.assertLess(pair["shrunk_ops"], pair["raw_ops"])
        self.assertGreater(pair["shrunk_ops"], prior_ops)

    def test_elo_is_deterministic(self):
        games = [
            {"date": "2026-04-01", "game_id": "1", "home": "ソフトバンク", "away": "日本ハム", "winner": "ソフトバンク"},
            {"date": "2026-04-02", "game_id": "2", "home": "日本ハム", "away": "ソフトバンク", "winner": "日本ハム"},
        ]
        self.assertEqual(build_elo(games), build_elo(games))


if __name__ == "__main__":
    unittest.main()
