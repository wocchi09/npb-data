"""大会別集計が公式戦と混ざらないことを確認する。"""

import json
import tempfile
import unittest
from pathlib import Path

from scraper.rebuild_stats import find_games, rebuild


class PostseasonStatsTest(unittest.TestCase):
    def test_competitions_are_aggregated_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "data"
            for number, competition in enumerate(("公式戦", "CS", "日本シリーズ"), 1):
                folder = base / "2026" / "10" / f"{number:02d}"
                folder.mkdir(parents=True)
                game = {
                    "game_id": str(number),
                    "game_type": competition,
                    "home": "巨人",
                    "away": "阪神",
                    "atbats": [{
                        "batter": {"player_id": str(number), "name": f"選手{number}"},
                        "pitcher": {"player_id": f"p{number}", "name": f"投手{number}"},
                        "batting_team": "巨人",
                        "fielding_team": "阪神",
                        "result_summary": "安打",
                        "pitch_count": 1,
                    }],
                }
                (folder / f"{number}.json").write_text(
                    json.dumps(game, ensure_ascii=False), encoding="utf-8"
                )

            outputs = (
                ("公式戦", base / "2026"),
                ("CS", base / "2026" / "postseason" / "cs"),
                ("日本シリーズ", base / "2026" / "postseason" / "japan_series"),
            )
            for number, (competition, folder) in enumerate(outputs, 1):
                rebuild("2026", str(base), competition)
                data = json.loads((folder / "players" / "stats.json").read_text(encoding="utf-8"))
                batters = [p for p in data["players"] if p.get("batting")]
                self.assertEqual([p["name"] for p in batters], [f"選手{number}"])
                self.assertEqual(data["competition"], competition)
                teams = json.loads((folder / "teams" / "stats.json").read_text(encoding="utf-8"))
                self.assertEqual(teams["competition"], competition)

            self.assertEqual(len(find_games("2026", str(base))), 3)


if __name__ == "__main__":
    unittest.main()
