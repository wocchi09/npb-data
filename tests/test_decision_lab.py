import json
import unittest
from pathlib import Path

from scraper.lib.analysis_lab import build_wpa_timelines
from scraper.lib.decision_lab import build_change_alerts, build_playoff_odds


ROOT = Path(__file__).resolve().parents[1]


class DecisionLabTests(unittest.TestCase):
    def test_page_and_daily_workflow_are_connected(self):
        html = (ROOT / "decision_lab.html").read_text(encoding="utf-8")
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        workflow = (ROOT / ".github/workflows/daily.yml").read_text(encoding="utf-8")
        self.assertIn("NPB DECISION LAB", html)
        self.assertIn("decision_lab.html", index)
        self.assertIn("build_decision_lab.py", workflow)
        for label in ("試合勝率", "ブルペン", "補正指標", "ドラフト", "優勝・CS", "変化アラート"):
            self.assertIn(label, html)

    def test_generated_json_contains_all_six_sections(self):
        path = ROOT / "data/2026/decision_lab.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        for key in ("win_probability", "bullpen", "adjusted_metrics", "draft_review", "playoff_odds", "change_alerts"):
            self.assertIn(key, payload)
        self.assertTrue(payload["win_probability"]["games"])
        self.assertEqual(12, len(payload["bullpen"]["teams"]))

    def test_win_probability_keeps_game_timeline_and_swings(self):
        games = [{"date": "2026-01-01", "game_id": "g1", "home": "B", "away": "A", "home_score": "1", "away_score": "0", "winner": "B"}]
        atbats = [
            {"date": "2026-01-01", "game_id": "g1", "inning": "1", "top_bottom": "表", "batting_team": "A", "fielding_team": "B", "atbat_no": "1", "atbat_index": "1", "outs": "1", "batter": "a", "pitcher": "p", "result": "三振"},
            {"date": "2026-01-01", "game_id": "g1", "inning": "1", "top_bottom": "裏", "batting_team": "B", "fielding_team": "A", "atbat_no": "2", "atbat_index": "2", "outs": "0", "batter": "b", "pitcher": "q", "result": "本塁打＋1点", "rbi": "1"},
        ]
        result = build_wpa_timelines(atbats, games)
        self.assertEqual(1, len(result["games"]))
        self.assertEqual(2, len(result["games"][0]["timeline"]))
        self.assertTrue(result["games"][0]["top_swings"])

    def test_batter_alert_uses_reconstructed_plate_appearances(self):
        rows = []
        for i in range(12):
            rows.append({"date": f"2026-04-{i+1:02d}", "game_id": str(i), "player_key": "p1", "player": "打者", "team": "A", "ab": "4", "hits": "1", "singles": "1"})
        for i in range(5):
            rows.append({"date": f"2026-05-{i+1:02d}", "game_id": f"r{i}", "player_key": "p1", "player": "打者", "team": "A", "ab": "4", "hits": "3", "singles": "2", "hr": "1"})
        result = build_change_alerts(rows, [])
        self.assertEqual("上昇", result["batters"][0]["direction"])
        self.assertGreaterEqual(result["batters"][0]["recent_pa"], 12)

    def test_playoff_simulation_is_reproducible(self):
        rows = [{"team": str(i), "games": 100, "wins": 50 + i, "losses": 50 - i, "ties": 0, "runs": 400 + i, "runs_allowed": 400 - i, "games_left": 10} for i in range(6)]
        standings = {"central": rows, "pacific": rows}
        one = build_playoff_odds(standings, seed=7, simulations=100)
        two = build_playoff_odds(standings, seed=7, simulations=100)
        self.assertEqual(one, two)


if __name__ == "__main__":
    unittest.main()
