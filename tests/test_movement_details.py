import unittest

from scraper.movement_details import parse_nikkan, parse_salaries, salary_links, merge_and_enrich, profile_stats
from scraper.player_movements import TEAMS, category, collect_snapshot


def nikkan(bio="試験太郎投手（30＝15年巨人→19年FAで楽天）", note="→戦力外→育成再契約打診"):
    return '<time>[2026年9月30日8時37分]</time><div id="news" class="article-body">' + "".join(
        f'<h2>{t}</h2><div class="yellow"><p><span class="black bold">{bio if t == "楽天" else ""}</span>{note if t == "楽天" else ""}</p></div>' for t in TEAMS) + '</div>'


def salary(value="8,000", heading="2026年度契約更改・楽天", unit="金額は推定（単位は万円）"):
    return f'<section class="scoreContent">{heading}<table><tr><th>選　手</th><th>年俸</th><th>増減</th><th>増減額</th></tr><tr><td>試験　太郎</td><td>{value}</td><td>□</td><td>0</td></tr></table>{unit}</section>'


def record(name="試験 太郎", pid=None, team="楽天"):
    return {"name": name, "team": team, "player_id": pid, "updated_date": "2026-09-28", "category": "自由契約", "note": "自由契約"}


class MovementDetailsTest(unittest.TestCase):
    def test_bio_history_not_current_fa(self):
        r = parse_nikkan(nikkan(), TEAMS, category)[0]
        self.assertEqual(r["name"], "試験太郎")
        self.assertEqual(r["categories"], ["自由契約", "育成契約関連"])
        self.assertEqual(r["date_kind"], "記事全体の更新日")
        self.assertEqual(r["source_updated_at"], "2026-09-30T08:37+09:00")
        self.assertNotIn("戦力外", r["note"])
        self.assertNotIn("announcement_date", r)

    def test_intention_and_incomplete_biography(self):
        r = parse_nikkan(nikkan(bio="※試験太郎投手（30＝15年巨人→楽天", note="→戦力外→引退を決意"), TEAMS, category)[0]
        self.assertTrue(r["development_player"])
        self.assertIn("引退（意向）", r["categories"])
        self.assertNotIn("引退", r["categories"])
        r = parse_nikkan(nikkan(note="→退団→現役続行希望"), TEAMS, category)[0]
        self.assertEqual(r["category"], "退団")

    def test_bad_source_structure_rejected(self):
        for html in ("", nikkan().replace("<h2>楽天</h2>", ""), nikkan().replace("→戦力外→育成再契約打診", "不明")):
            with self.assertRaises(ValueError):
                parse_nikkan(html, TEAMS, category)

    def test_salary_requires_year_team_units_and_number(self):
        r = parse_salaries(salary(), "楽天", "source")[0]
        self.assertEqual(r["amount_man_yen"], 8000)
        self.assertEqual(r["season"], "2026")
        self.assertTrue(r["estimated"])
        for html in (salary(heading="契約更改・楽天"), salary(unit="金額不明"), salary(value="不明"), salary(heading="2026年度契約更改・阪神")):
            with self.assertRaises(ValueError):
                parse_salaries(html, "楽天", "source")

    def test_salary_nav_whitelist(self):
        with self.assertRaises(ValueError):
            salary_links([{"headline": "楽天", "url": "https://evil.test/tb1.shtml"}], TEAMS)

    def test_merge_without_master_id_and_name_variants(self):
        snapshots = {"sports": {"rows": [record("日當 直喜", "123")]}, "nikkan": {"rows": [record("日当直喜")]}}
        profiles = [{"name": "日當 直喜", "team": "楽天", "career_pitching": {"games": 0, "wins": 0}, "yearly_pitching": []}]
        result = merge_and_enrich(snapshots, profiles, {}, "2026")
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["observations"]), 2)
        self.assertEqual(result[0]["stats"]["career"][0]["games"], 0)
        self.assertEqual(result[0]["stats"]["yearly"], [])

    def test_ambiguous_ids_and_names_not_guessed(self):
        snapshots = {"sports": {"rows": [record(pid="1"), record(pid="2")]}, "nikkan": {"rows": [record("試験太郎")]}}
        profiles = [{"name": "試験 太郎", "team": "楽天"}, {"name": "試験太郎", "team": "楽天"}]
        result = merge_and_enrich(snapshots, profiles, {}, "2026")
        self.assertEqual(len(result), 3)
        self.assertTrue(all(r["stats"] is None for r in result))

    def test_reviewed_alias_is_team_scoped(self):
        rows = [record("マルティネス", "1", "阪神"), record("アンソニー・マルティネス", team="阪神"), record("アンソニー・マルティネス", team="日本ハム")]
        result = merge_and_enrich({"a": {"rows": rows}}, [], {}, "2026")
        self.assertEqual(len(result), 2)
        self.assertEqual(len(next(r for r in result if r["team"] == "阪神")["observations"]), 2)

    def test_unknown_salary_and_transfer_year_splits(self):
        p = {"yearly_batting": [{"year": "2026", "team": "楽天", "games": 2}, {"year": "2026", "team": "巨人", "games": 1}, {"year": "2025", "games": 15}]}
        stats = profile_stats(p, "2026")
        self.assertEqual(len(stats["yearly"]), 2)
        self.assertNotIn("hits", stats["yearly"][0])
        result = merge_and_enrich({"a": {"rows": [record()]}}, [], {}, "2026")
        self.assertIsNone(result[0]["salary"])

    def test_source_failure_preserves_previous_and_recovery_clears_warning(self):
        old = {"rows": [record()], "last_success_at": "2026-09-28"}
        def fail(_):
            raise ValueError("changed markup")
        stale = collect_snapshot(lambda _: "html", "url", fail, old, "2026-09-30")
        self.assertEqual(stale["rows"], old["rows"])
        self.assertEqual(stale["last_success_at"], "2026-09-28")
        self.assertTrue(stale["stale"])
        recovered = collect_snapshot(lambda _: "html", "url", lambda _: [], stale, "2026-10-01")
        self.assertFalse(recovered["stale"])
        self.assertNotIn("error", recovered)
        self.assertEqual(recovered["rows"], [])


if __name__ == "__main__":
    unittest.main()
