import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scraper"))

from lib.w_impact import _confidence, build_context_adjustments  # noqa: E402


class WImpactConfidenceContextTest(unittest.TestCase):
    def test_confidence_labels_are_monotonic_and_explain_sample_size(self):
        self.assertEqual(_confidence(20)["label"], "低い")
        self.assertEqual(_confidence(45)["label"], "参考")
        self.assertEqual(_confidence(60)["label"], "標準")
        self.assertEqual(_confidence(80)["label"], "高い")
        self.assertEqual(_confidence(95)["label"], "非常に高い")
        self.assertEqual(_confidence(95)["stars"], "★★★★★")

    def test_context_adjustment_is_shrunk_and_bounded(self):
        batting = [
            self.bat("b1", "ソフトバンク", "日本ハム", "エスコン", "g1", 4, 2, 1, 1),
            self.bat("b2", "日本ハム", "ソフトバンク", "エスコン", "g1", 4, 0, 0, 0),
            self.bat("b3", "オリックス", "ソフトバンク", "京セラD大阪", "g2", 4, 0, 0, 0),
            self.bat("b1", "ソフトバンク", "オリックス", "京セラD大阪", "g2", 4, 1, 0, 0),
        ]
        pitching = [
            self.pitch("p1", "日本ハム", "ソフトバンク", "エスコン", 270, 20),
            self.pitch("p2", "ソフトバンク", "日本ハム", "エスコン", 270, 60),
            self.pitch("p3", "オリックス", "ソフトバンク", "京セラD大阪", 270, 40),
        ]
        model = build_context_adjustments(batting, pitching)
        batter = model["batters"]["b1"]
        pitcher = model["pitchers"]["p1"]
        for item in (batter, pitcher):
            self.assertGreaterEqual(item["adjustment"], 0.90)
            self.assertLessEqual(item["adjustment"], 1.10)
            self.assertIn("park_factor", item)
            self.assertIn("opponent_factor", item)
        self.assertEqual(model["method"], "season_shrunk_park_opponent_v1")

    def test_ui_displays_confidence_and_adjustment_method(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn("データ信頼度", html)
        self.assertIn("球場・対戦相手補正", html)
        self.assertIn("impactConfidenceBadge", html)
        self.assertIn("impactContextCell", html)
        self.assertIn("標準以上（55点〜）", html)

    @staticmethod
    def bat(key, team, opponent, stadium, game, ab, hits, doubles, hr):
        singles = max(hits - doubles - hr, 0)
        return {
            "player_key": key, "team": team, "opponent": opponent,
            "stadium": stadium, "game_id": game, "ab": ab, "hits": hits,
            "bb": 0, "hbp": 0, "sac": 0, "runs": hits,
            "singles": singles, "doubles": doubles, "triples": 0, "hr": hr,
        }

    @staticmethod
    def pitch(key, team, opponent, stadium, outs, runs):
        return {
            "player_key": key, "team": team, "opponent": opponent,
            "stadium": stadium, "outs": outs, "runs_allowed": runs,
        }


if __name__ == "__main__":
    unittest.main()
