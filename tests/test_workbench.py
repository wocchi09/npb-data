import csv
import json
import tempfile
import unittest
from pathlib import Path
from scraper.build_workbench import build, change_candidates, value, windows


class WorkbenchTests(unittest.TestCase):
    def test_missing_and_nonfinite_values(self):
        for raw in ['', None, 'nan', 'inf', 'no']:
            self.assertIsNone(value('speed_kmh', raw))
        self.assertIsNone(value('is_miss', 'unknown'))
        self.assertFalse(value('is_miss', 'False'))

    def test_calendar_windows_are_disjoint_and_30_days(self):
        self.assertEqual(['2026-03-03', '2026-04-01', '2026-04-02', '2026-05-01'], windows('2026-05-01'))

    def test_build_deduplicates_preserves_ids_and_roundtrips(self):
        with tempfile.TemporaryDirectory() as base:
            dataset = Path(base) / '2026' / 'dataset'
            dataset.mkdir(parents=True)
            row = dict(date='2026-05-01', game_id='123', atbat_index='0110200', pitch_no='1',
                       batter_key='p1', batter='打者', pitcher_key='p2', pitcher='投手',
                       batting_team='A', fielding_team='B', speed_kmh='', pitch_type='ストレート')
            for name in ['pitches', 'atbats']:
                with (dataset / (name + '.csv')).open('w', encoding='utf-8', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=row.keys())
                    writer.writeheader()
                    writer.writerows([row, row])
            manifest = build('2026', base)
            self.assertEqual({'atbats': 1, 'pitches': 1}, manifest['duplicates_removed'])
            self.assertEqual(2, len(manifest['players']))
            player = manifest['players'][0]
            data = json.loads((dataset / 'workbench' / (player['id'] + '.json')).read_text(encoding='utf-8'))
            self.assertEqual('0110200', data['atbats'][0][2])
            self.assertIsNone(data['pitches'][0][5])
            self.assertEqual(manifest, build('2026', base))

    def test_alerts_require_sample_and_exclude_unknown_classification(self):
        player = {'id': 'p', 'name': '投手', 'role': 'pitcher', 'team': 'A'}
        periods = ['2026-04-01', '2026-04-30', '2026-05-01', '2026-05-30']
        rows = [dict(date=day, pitch_type='ストレート', speed_kmh=speed, is_swing='True', is_miss='')
                for day, speed in [('2026-04-01', '150'), ('2026-05-01', '148')] for _ in range(30)]
        alerts = change_candidates(player, rows, periods)
        self.assertEqual(1, len(alerts))
        self.assertEqual(-2, alerts[0]['change'])
        self.assertEqual(30, alerts[0]['n_a'])
        self.assertEqual([], change_candidates(player, rows[1:], periods))


if __name__ == '__main__':
    unittest.main()
