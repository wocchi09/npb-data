"""Publish compact per-player evidence and reproducible 30-day change candidates.

No network access or optional dependencies. Called by build_analyst_lab.py.
"""
import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

PITCH_COLUMNS = 'date game_id atbat_index pitch_no pitch_type speed_kmh zone_label count_before is_swing is_miss in_zone pitch_result'.split()
AB_COLUMNS = 'date game_id atbat_index batter pitcher bat_hand pit_hand risp result pa ab hit single double triple hr bb hbp sf so'.split()
NUMERIC = set('pitch_no speed_kmh pa ab hit single double triple hr bb hbp sf so'.split())
BOOLEAN = {'is_swing', 'is_miss', 'in_zone', 'risp'}


def value(key, raw):
    if raw is None or raw == '':
        return None
    if key in BOOLEAN:
        return {'true': True, 'false': False, '1': True, '0': False}.get(str(raw).lower())
    if key in NUMERIC:
        try:
            result = float(raw)
            return result if math.isfinite(result) else None
        except (ValueError, TypeError):
            return None
    return raw


def compact(row, columns):
    return [value(key, row.get(key)) for key in columns]


def read_rows(path):
    with path.open(encoding='utf-8-sig', newline='') as handle:
        yield from csv.DictReader(handle)


def write_json(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')
    temp.replace(path)


def windows(last):
    end = date.fromisoformat(last)
    return [(end - timedelta(days=59)).isoformat(), (end - timedelta(days=30)).isoformat(),
            (end - timedelta(days=29)).isoformat(), end.isoformat()]


def change_candidates(player, rows, periods):
    a0, a1, b0, b1 = periods
    groups = [[r for r in rows if lo <= r['date'] <= hi] for lo, hi in [(a0, a1), (b0, b1)]]
    result = []

    def add(metric, before, after, na, nb, threshold, unit):
        if before is not None and after is not None and abs(after - before) >= threshold:
            result.append({'player': player['id'], 'name': player['name'], 'role': player['role'],
                           'team': player['team'], 'metric': metric, 'before': before, 'after': after,
                           'n_a': na, 'n_b': nb, 'change': after - before, 'unit': unit,
                           'score': abs(after - before) / threshold})

    speeds = [[value('speed_kmh', r.get('speed_kmh')) for r in rs if r.get('pitch_type') == 'ストレート'] for rs in groups]
    speeds = [[s for s in ss if s is not None and s > 0] for ss in speeds]
    if player['role'] == 'pitcher' and all(len(s) >= 30 for s in speeds):
        add('直球平均球速', *(sum(s) / len(s) for s in speeds), *(len(s) for s in speeds), 1.5, 'km/h')
    swings = [[r for r in rs if value('is_swing', r.get('is_swing')) is True and value('is_miss', r.get('is_miss')) is not None] for rs in groups]
    if all(len(s) >= 50 for s in swings):
        add('空振り率', *(sum(value('is_miss', r['is_miss']) for r in s) / len(s) for s in swings), *(len(s) for s in swings), .08, 'rate')
    mixes = [Counter(r['pitch_type'] for r in rs if r.get('pitch_type')) for rs in groups]
    totals = [sum(c.values()) for c in mixes]
    if player['role'] == 'pitcher' and all(n >= 100 for n in totals):
        for kind in sorted(set(mixes[0]) | set(mixes[1])):
            add('球種割合：' + kind, mixes[0][kind] / totals[0], mixes[1][kind] / totals[1], *totals, .10, 'rate')
    return result


def build(season, base='data'):
    dataset = Path(base) / str(season) / 'dataset'
    out = dataset / 'workbench'
    out.mkdir(parents=True, exist_ok=True)
    players = {}
    atbats, pitches = defaultdict(list), defaultdict(list)
    seen_ab, seen_pitch = set(), set()
    duplicates = {'atbats': 0, 'pitches': 0}
    dates = set()
    for name, columns, destination, seen in [('atbats', AB_COLUMNS, atbats, seen_ab), ('pitches', PITCH_COLUMNS, pitches, seen_pitch)]:
        for row in read_rows(dataset / (name + '.csv')):
            day = row.get('date', '')
            try:
                date.fromisoformat(day)
            except ValueError:
                continue
            if not row.get('game_id') or not row.get('atbat_index'):
                continue
            identity = (day, row['game_id'], row['atbat_index']) + ((row.get('pitch_no'),) if name == 'pitches' else ())
            if identity in seen:
                duplicates[name] += 1
                continue
            seen.add(identity)
            dates.add(day)
            for role, team in [('batter', 'batting_team'), ('pitcher', 'fielding_team')]:
                key = row.get(role + '_key')
                if not key:
                    continue
                pid = role + '-' + hashlib.sha256(key.encode()).hexdigest()[:20]
                if pid not in players:
                    players[pid] = {'id': pid, 'key': key, 'role': role, 'name': row.get(role) or key, 'teams': set()}
                if row.get(team):
                    players[pid]['teams'].add(row[team])
                destination[pid].append(compact(row, columns))
    if not dates or not atbats:
        raise RuntimeError('比較用の打席データがありません')
    periods = windows(max(dates))
    manifest, alerts = [], []
    for pid, player in sorted(players.items()):
        player['team'] = ' / '.join(sorted(player.pop('teams')))
        ab = sorted(atbats[pid], key=lambda r: (r[0], r[1], r[2]))
        ps = sorted(pitches[pid], key=lambda r: (r[0], r[1], r[2], r[3] or 0))
        rows = [dict(zip(PITCH_COLUMNS, r)) for r in ps]
        alerts.extend(change_candidates(player, rows, periods))
        body = {'player': player, 'ab_columns': AB_COLUMNS, 'pitch_columns': PITCH_COLUMNS, 'atbats': ab, 'pitches': ps}
        write_json(out / (pid + '.json'), body)
        manifest.append({**player, 'atbats': len(ab), 'pitches': len(ps)})
    alerts.sort(key=lambda a: (-a['score'], a['player'], a['metric']))
    result = {'version': 1, 'season': str(season), 'first_date': min(dates), 'data_date': max(dates),
              'periods': periods, 'players': manifest, 'alerts': alerts, 'duplicates_removed': duplicates}
    write_json(out / 'index.json', result)
    print(f'[INFO] Workbench: {len(players)} players / {len(alerts)} change candidates')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--season', required=True)
    parser.add_argument('--base', default='data')
    args = parser.parse_args()
    build(args.season, args.base)
