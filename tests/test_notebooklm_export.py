import csv
import json
import tempfile
import unittest
from pathlib import Path

from scraper import build_notebooklm as exporter


class NotebookLmExportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name) / "data"
        self.season = self.base / "2026"
        (self.season / "players").mkdir(parents=True)
        (self.season / "dataset").mkdir(parents=True)
        (self.season / "matchups" / "batters").mkdir(parents=True)
        self.out = Path(self.tmp.name) / "out"

        (self.season / "players" / "stats.json").write_text(json.dumps({
            "players": [{
                "key": "p1", "player_id": "1", "name": "選手A", "team": "球団A", "number": "1", "position": "外",
                "batting": {"games": 20, "pa": 40, "ab": 33, "hits": 11, "hr": 0, "rbi": 5, "sb": 0, "avg": .333, "obp": .5, "slg": .333, "ops": .833},
            }]
        }, ensure_ascii=False), encoding="utf-8")
        (self.season / "standings.json").write_text(json.dumps({
            "updated_at": "2026-04-01T22:00:00+09:00",
            "central": [{"rank": 1, "team": "球団A", "games": 1, "wins": 1, "losses": 0, "ties": 0}],
            "pacific": []
        }, ensure_ascii=False), encoding="utf-8")
        with (self.season / "dataset" / "games.csv").open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["date", "game_id", "away", "home", "stadium", "away_score", "home_score", "winner", "state", "win_pitcher", "lose_pitcher", "save_pitcher"])
            writer.writeheader()
            writer.writerow({"date": "2026-04-01", "game_id": "g1", "away": "球団B", "home": "球団A"})

    def tearDown(self):
        self.tmp.cleanup()

    def test_builds_every_required_csv_with_exact_headers(self):
        counts = exporter.build(self.base, self.out, "2026")
        self.assertEqual(set(counts), set(exporter.REQUIRED))
        exporter.validate_outputs(self.out)
        for name in exporter.REQUIRED:
            with (self.out / name).open(encoding="utf-8-sig", newline="") as fh:
                self.assertEqual(next(csv.reader(fh)), exporter.HEADERS[name])

    def test_missing_required_source_is_reported(self):
        (self.season / "players" / "stats.json").unlink()
        with self.assertRaisesRegex(FileNotFoundError, "必須データ"):
            exporter.build(self.base, self.out, "2026")

    def test_duplicate_players_are_not_introduced(self):
        path = self.season / "players" / "stats.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["players"].append(dict(doc["players"][0]))
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        exporter.build(self.base, self.out, "2026")
        with (self.out / "batting.csv").open(encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.DictReader(fh))
        keys = [(r["シーズン"], r["選手名"], r["球団"]) for r in rows]
        self.assertEqual(len(keys), len(set(keys)))

    def test_validation_rejects_missing_csv(self):
        exporter.build(self.base, self.out, "2026")
        (self.out / "teams.csv").unlink()
        with self.assertRaisesRegex(ValueError, "不足: teams.csv"):
            exporter.validate_outputs(self.out)


if __name__ == "__main__":
    unittest.main()
