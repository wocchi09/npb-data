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
        (self.season / "roster" / "daily").mkdir(parents=True)
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
            writer.writerow({"date": "2026-03-01", "game_id": "g0", "away": "球団A", "home": "球団B"})
            writer.writerow({"date": "2026-04-01", "game_id": "g1", "away": "球団B", "home": "球団A"})
        (self.season / "roster" / "registration.json").write_text(json.dumps({
            "latest_date": "2026-04-01",
            "players": [
                {"npb_id": "1", "name": "選手A", "team": "球団A", "current_registered": True, "registered_days": 7},
                {"npb_id": "2", "name": "選手B", "team": "球団B", "current_registered": False, "registered_days": 2, "last_deregistered": "2026-02-01"},
            ]
        }, ensure_ascii=False), encoding="utf-8")
        (self.season / "roster" / "daily" / "2026-04-01.json").write_text(json.dumps({
            "registered": [{"npb_id": "1", "name": "選手A", "team": "球団A"}]
        }, ensure_ascii=False), encoding="utf-8")

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

    def test_season_files_keep_old_games_and_old_roster_players(self):
        exporter.build(self.base, self.out, "2026")
        with (self.out / "games_latest.csv").open(encoding="utf-8-sig", newline="") as fh:
            latest_games = list(csv.DictReader(fh))
        with (self.out / "games_season.csv").open(encoding="utf-8-sig", newline="") as fh:
            season_games = list(csv.DictReader(fh))
        with (self.out / "roster.csv").open(encoding="utf-8-sig", newline="") as fh:
            recent_roster = list(csv.DictReader(fh))
        with (self.out / "roster_season.csv").open(encoding="utf-8-sig", newline="") as fh:
            season_roster = list(csv.DictReader(fh))
        self.assertEqual([r["試合ID"] for r in latest_games], ["g1"])
        self.assertEqual({r["試合ID"] for r in season_games}, {"g0", "g1"})
        self.assertEqual([r["選手名"] for r in recent_roster], ["選手A"])
        self.assertEqual({r["選手名"] for r in season_roster}, {"選手A", "選手B"})


if __name__ == "__main__":
    unittest.main()
