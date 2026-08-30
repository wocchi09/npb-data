import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scraper.build_article_ideas import build
from scraper.build_story_insights import build_two_strike
from scraper.lib.pitch_metrics import summarize_batter_pitches, summarize_pitcher_pitches


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class ArticleLabTests(unittest.TestCase):
    def test_pitch_metrics_aggregate_observed_pitch_rows(self):
        rows = [
            {"date": "2026-08-10", "game_id": "g10", "pitch_type": "ストレート", "speed_kmh": "150", "strikes_before": "2", "in_zone": "True", "is_swing": "True", "is_miss": "True", "is_called": "False", "is_last_pitch": "False", "ab_result": "空振り三振", "ab_out_type": "三振", "ab_hit": "0"},
            {"date": "2026-08-10", "game_id": "g10", "pitch_type": "ストレート", "speed_kmh": "148", "strikes_before": "2", "in_zone": "False", "is_swing": "False", "is_miss": "False", "is_called": "True", "is_last_pitch": "True", "ab_result": "見逃し三振", "ab_out_type": "三振", "ab_hit": "0"},
            {"date": "2026-08-10", "game_id": "g10", "pitch_type": "フォーク", "speed_kmh": "138", "strikes_before": "1", "in_zone": "False", "is_swing": "True", "is_miss": "False", "is_called": "False", "is_last_pitch": "True", "ab_result": "右安", "ab_out_type": "", "ab_hit": "1"},
        ]
        pitcher = summarize_pitcher_pitches(rows)
        batter = summarize_batter_pitches(rows)
        self.assertEqual(pitcher["pitches"], 3)
        self.assertEqual(pitcher["fastball"]["avg_speed_kmh"], 149.0)
        self.assertEqual(pitcher["strikeout_finish_by_pitch"], [{"pitch_type": "ストレート", "strikeouts": 1}])
        self.assertEqual(pitcher["two_strike_pitches"], 2)
        self.assertEqual(pitcher["in_zone_rate"], 0.333)
        self.assertEqual(batter["whiff_rate"], 0.5)
        self.assertEqual(batter["called_strike_rate"], 1.0)
        self.assertEqual(sum(row["hits"] for row in batter["terminal_results_by_pitch"]), 1)
        missing_flags = summarize_batter_pitches([{"date": "2026-08-10", "game_id": "g10", "pitch_type": "ストレート"}])
        self.assertIsNone(missing_flags["whiff_rate"])
        self.assertIsNone(missing_flags["called_strike_rate"])

    def test_two_strike_uses_verified_plate_appearance_end(self):
        rows = [
            {"strikes_before": 2, "pitcher_key": "p1", "pitcher": "実在 投手", "fielding_team": "ソフトバンク", "pit_hand": "右投", "is_last_pitch": "True", "ab_out_type": "三振", "ab_result": "空振り三振", "is_miss": "False", "is_called": "False", "pitch_type": "フォーク", "in_zone": "False", "speed_kmh": 140, "zone_label": "低め・外", "bat_hand": "右打"},
            {"strikes_before": 2, "pitcher_key": "p1", "pitcher": "実在 投手", "fielding_team": "ソフトバンク", "pit_hand": "右投", "is_last_pitch": "False", "ab_out_type": "", "ab_result": "", "is_miss": "True", "is_called": "False", "pitch_type": "フォーク", "in_zone": "False", "speed_kmh": 139, "zone_label": "低め・外", "bat_hand": "右打"},
            {"strikes_before": 2, "pitcher_key": "p1", "pitcher": "実在 投手", "fielding_team": "ソフトバンク", "pit_hand": "右投", "is_last_pitch": "True", "ab_out_type": "内野ゴロ", "ab_result": "二ゴロ", "is_miss": "False", "is_called": "True", "pitch_type": "ストレート", "in_zone": "True", "speed_kmh": 150, "zone_label": "真ん中", "bat_hand": "左打"},
            {"strikes_before": 2, "pitcher_key": "p1", "pitcher": "実在 投手", "fielding_team": "ソフトバンク", "pit_hand": "右投", "is_last_pitch": "True", "ab_out_type": "三振", "ab_result": "見逃し三振", "is_miss": "False", "is_called": "False", "pitch_type": "ストレート", "in_zone": "True", "speed_kmh": 151, "zone_label": "高め", "bat_hand": "左打"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pitches.csv"
            write_csv(path, rows)
            pitchers, quality = build_two_strike(str(path), min_pitches=1, include_quality=True)
        self.assertTrue(quality["validated"])
        self.assertEqual(quality["two_strike_pitches"], 4)
        self.assertEqual(quality["strikeout_finishes"], 2)
        self.assertEqual(quality["swinging_strikeout_finishes"], 1)
        self.assertEqual(quality["called_strikeout_finishes"], 1)
        self.assertEqual(quality["legacy_is_miss_true"], 1)
        self.assertEqual(pitchers[0]["k_finish_rate"], 0.5)

    def test_builder_outputs_five_traceable_real_data_ideas(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "data"; root = base / "2026"; dataset = root / "dataset"
            games = []
            batting = []
            for day in range(1, 11):
                game_id = f"g{day}"
                games.append({"date": f"2026-08-{day:02d}", "game_id": game_id, "home": "ソフトバンク", "away": "日本ハム", "home_score": 4, "away_score": 2, "winner": "ソフトバンク", "stadium": "みずほPayPay"})
                batting.append({"date": f"2026-08-{day:02d}", "game_id": game_id, "team": "ソフトバンク", "player": "実在 選手", "player_key": "p-real", "ab": 4, "runs": 1, "hits": 2, "rbi": 1, "so": 1, "bb": 1, "hbp": 0, "sac": 0, "doubles": 1, "triples": 0, "hr": 0})
            write_csv(dataset / "games.csv", games)
            write_csv(dataset / "batting_lines.csv", batting)
            write_csv(dataset / "pitching_lines.csv", [{"date": "2026-08-10", "game_id": "g10", "team": "ソフトバンク", "player": "実在 投手", "player_key": "p-pit", "is_starter": "True", "outs": 21, "earned_runs": 1, "runs_allowed": 1, "so": 7, "bb": 1, "hits_allowed": 4, "pitches": 100}])
            pitch_fields = {"date": "2026-08-10", "game_id": "g10", "speed_kmh": 150, "zone_row": 2, "zone_col": 2, "zone_label": "真ん中", "in_zone": "True", "is_swing": "True", "is_miss": "False", "is_called": "False", "is_last_pitch": "True", "ab_result": "中安", "ab_out_type": "", "ab_hit": 1, "strikes_before": 2}
            write_csv(dataset / "pitches.csv", [
                {**pitch_fields, "batting_team": "日本ハム", "fielding_team": "ソフトバンク", "batter": "相手 打者", "batter_key": "p-opp-bat", "pitcher": "実在 投手", "pitcher_key": "p-pit", "pitch_type": "ストレート"},
                {**pitch_fields, "batting_team": "ソフトバンク", "fielding_team": "日本ハム", "batter": "実在 選手", "batter_key": "p-real", "pitcher": "相手 投手", "pitcher_key": "p-opp-pit", "pitch_type": "フォーク"},
            ])
            write_csv(dataset / "season_batting.csv", [{"player_key": "p-real", "player": "実在 選手", "team": "ソフトバンク", "pa": 300, "ops": 0.700}])
            trend = lambda team, recent_ops, season_ops, recent_era, season_era: {"team": team, "recent": {"record": {"games": 10, "wins": 7, "losses": 3, "ties": 0, "runs_per_game": 4.5, "allowed_per_game": 2.5}, "batting": {"ops": recent_ops}, "pitching": {"era": recent_era}}, "season": {"record": {"games": 100, "wins": 55, "losses": 43, "ties": 2, "runs_per_game": 3.8, "allowed_per_game": 3.3}, "batting": {"ops": season_ops}, "pitching": {"era": season_era}}, "delta": {"ops": recent_ops-season_ops, "era": recent_era-season_era, "runs_per_game": .7, "allowed_per_game": -.8}, "changes": ["防御率が改善"]}
            story = {"latest_games": {"date": "2026-08-10", "games": [{"game_id": "g10", "home": "ソフトバンク", "away": "日本ハム", "home_score": 4, "away_score": 2, "winner": "ソフトバンク", "offense": {"hits": 9, "hr": 1, "bb": 4}, "starter": {"name": "実在 投手", "innings": "7.0", "earned_runs": 1, "so": 7}, "bullpen": {"innings": "2.0", "earned_runs": 0}}]}, "team_trends": [trend("ソフトバンク", .710, .700, 2.40, 3.10), trend("日本ハム", .800, .690, 4.60, 3.20)], "quality": {"two_strike": {"definition_version": 2, "validated": True, "source_fields": ["strikes_before", "is_last_pitch", "ab_result", "ab_out_type"]}}, "two_strike_pitchers": [{"key": "p-pit", "name": "実在 投手", "team": "ソフトバンク", "pitches": 100, "k_finish_rate": .22, "whiff_rate": .17, "pitch_types": [{"pitch_type": "フォーク", "share": .45}]}]}
            root.mkdir(parents=True, exist_ok=True)
            (root / "_story_insights.json").write_text(json.dumps(story, ensure_ascii=False), encoding="utf-8")
            output = build("2026", str(base))
            saved = json.loads((root / "_article_ideas.json").read_text(encoding="utf-8"))
        self.assertEqual(output["data_date"], "2026-08-10")
        self.assertEqual(len(saved["ideas"]), 5)
        self.assertEqual(sum(i["team"] == "ソフトバンク" for i in saved["ideas"]), 4)
        self.assertTrue(all(i["source_refs"] for i in saved["ideas"]))
        self.assertIn("実在 選手", json.dumps(saved, ensure_ascii=False))
        game_idea = next(i for i in saved["ideas"] if i["type"] == "game")
        hitter_idea = next(i for i in saved["ideas"] if i["id"] == "hawks-player-p-real")
        pitcher_idea = next(i for i in saved["ideas"] if i["id"] == "hawks-two-strike-p-pit")
        self.assertIn("先発の投球数", {item["label"] for item in game_idea["facts"]})
        self.assertIn("ホークス打線で見た球種", {item["label"] for item in game_idea["facts"]})
        self.assertTrue(any(item["source"]["dataset"] == "pitches.csv" for item in hitter_idea["facts"]))
        self.assertTrue(any(item["source"]["dataset"] == "pitches.csv" for item in pitcher_idea["facts"]))
        for idea in (game_idea, hitter_idea, pitcher_idea):
            for item in (fact for fact in idea["facts"] if fact["source"]["dataset"] == "pitches.csv"):
                self.assertEqual(item["source"]["date"], "2026-08-10")
                self.assertEqual(item["source"]["game_id"], "g10")

    def test_no_data_writes_safe_empty_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = build("2026", str(Path(tmp) / "data"))
            self.assertEqual(output["status"], "data_unavailable")
            self.assertEqual(output["ideas"], [])

    @unittest.skipUnless(shutil.which("node"), "Node.js is required")
    def test_prompt_and_brief_generation_in_javascript(self):
        script = f"const a=require({json.dumps(str(ROOT / 'article_lab.js'))});const i={{type:'trend',team:'ソフトバンク',title:'題',theme:'テーマ',reason:'理由',facts:[{{label:'OPS',value:'.700',source:{{dataset:'season.csv',date:'2026-08-10'}}}}],angles:['論点'],cautions:['注意'],source_refs:[{{dataset:'season.csv',date:'2026-08-10'}}]}};console.log(JSON.stringify({{brief:a.buildBrief(i,'2026-08-10'),prompt:a.fillPrompt('X {{{{TITLE}}}} {{{{FACTS}}}}',i,'2026-08-10')}}));"
        result = subprocess.run(["node", "-e", script], cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8")
        payload = json.loads(result.stdout)
        self.assertIn("Article Brief", payload["brief"])
        self.assertIn("source: season.csv / 2026-08-10", payload["brief"])
        self.assertIn("X 題", payload["prompt"])

    def test_page_prompt_and_workflow_contract(self):
        html = (ROOT / "article_lab.html").read_text(encoding="utf-8")
        js = (ROOT / "article_lab.js").read_text(encoding="utf-8")
        prompt = (ROOT / "prompts" / "article_writer.md").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
        self.assertIn("Claude用プロンプトを生成", js)
        self.assertIn("copyButton", html)
        self.assertIn("downloadButton", html)
        self.assertIn("{{ARTICLE_BRIEF}}", prompt)
        self.assertLess(workflow.index("build_story_insights.py"), workflow.index("build_article_ideas.py"))


if __name__ == "__main__":
    unittest.main()
