"""Build compact, source-traceable story ideas for NPB ARTICLE LAB.

Output: data/{season}/_article_ideas.json

The browser reads only this compact artifact.  Every displayed number is copied from
an existing aggregate or calculated from collected CSV rows; missing values are never
invented.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

try:
    from scraper.build_story_insights import aggregate_batting, aggregate_pitching, build as build_story, integer, load_csv, num
    from scraper.lib.pitch_metrics import summarize_batter_pitches, summarize_pitcher_pitches, summarize_times_through_order, truthy
except ModuleNotFoundError:  # Direct execution: python scraper/build_article_ideas.py
    from build_story_insights import aggregate_batting, aggregate_pitching, build as build_story, integer, load_csv, num
    from lib.pitch_metrics import summarize_batter_pitches, summarize_pitcher_pitches, summarize_times_through_order, truthy

JST = timezone(timedelta(hours=9))
HAWKS = "ソフトバンク"
PACIFIC = {"ソフトバンク", "日本ハム", "オリックス", "楽天", "西武", "ロッテ"}
CENTRAL = {"巨人", "阪神", "DeNA", "広島", "ヤクルト", "中日"}
NPB_TEAMS = [
    "ソフトバンク", "日本ハム", "オリックス", "楽天", "西武", "ロッテ",
    "巨人", "阪神", "DeNA", "広島", "ヤクルト", "中日",
]
TYPE_LABELS = {"game": "試合", "player": "選手", "trend": "トレンド"}
MIN_GAME_BATTER_PA = 3


def read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def rounded(value, digits=3):
    return None if value is None else round(float(value), digits)


def format_rate(value, digits=3):
    if value is None:
        return "データ不足"
    return f"{float(value):.{digits}f}".lstrip("0")


def format_signed(value, digits=3):
    if value is None:
        return "データ不足"
    return f"{float(value):+.{digits}f}"


def record_text(record):
    if not record:
        return "データ不足"
    return f"{integer(record.get('wins'))}勝{integer(record.get('losses'))}敗{integer(record.get('ties'))}分"


def source(dataset, date=None, game_id=None, fields=None, note=None):
    item = {"dataset": dataset}
    if date:
        item["date"] = date
    if game_id:
        item["game_id"] = str(game_id)
    if fields:
        item["fields"] = fields
    if note:
        item["note"] = note
    return item


def fact(label, value, metric, raw_value, src):
    return {"label": label, "value": value, "metric": metric, "raw_value": raw_value, "source": src}


def pitch_rows_for(rows, *, game_ids=None, pitcher_key=None, pitcher_name=None,
                   batter_key=None, batting_team=None, fielding_team=None):
    game_ids = {str(value) for value in (game_ids or []) if value not in (None, "")}
    selected = []
    for row in rows or []:
        if game_ids and str(row.get("game_id") or "") not in game_ids:
            continue
        if pitcher_key and str(row.get("pitcher_key") or row.get("pitcher_id") or "") != str(pitcher_key):
            continue
        if pitcher_name and str(row.get("pitcher") or "") != str(pitcher_name):
            continue
        if batter_key and str(row.get("batter_key") or row.get("batter_id") or "") != str(batter_key):
            continue
        if batting_team and row.get("batting_team") != batting_team:
            continue
        if fielding_team and row.get("fielding_team") != fielding_team:
            continue
        selected.append(row)
    return selected


def pitch_source(summary, fields, note=None):
    start = summary.get("date_start")
    end = summary.get("date_end")
    date = start if start == end else (f"{start}〜{end}" if start and end else start or end)
    game_ids = summary.get("game_ids") or []
    return source("pitches.csv", date, ",".join(game_ids) or None, fields, note)


def format_mix(items):
    return "、".join(
        f"{item['pitch_type']} {integer(item.get('pitches'))}球（{num(item.get('share')) * 100:.1f}%）"
        for item in items or []
        if item.get("pitch_type") and integer(item.get("pitches")) > 0
    )


def pitcher_pitch_facts(summary, label_prefix="投手"):
    if not summary:
        return [], [], []
    fields = ["pitcher_key", "pitch_type", "speed_kmh", "strikes_before", "in_zone", "is_last_pitch", "ab_result", "ab_out_type"]
    src = pitch_source(summary, fields)
    facts = [
        fact(f"{label_prefix}の投球数", f"{integer(summary.get('pitches'))}球", "pitch_count", summary.get("pitches"), src)
    ]
    mix = format_mix(summary.get("pitch_mix"))
    if mix:
        facts.append(fact(f"{label_prefix}の球種構成", mix, "pitch_mix", summary.get("pitch_mix"), src))
    fastball = summary.get("fastball") or {}
    if fastball.get("avg_speed_kmh") is not None and fastball.get("max_speed_kmh") is not None:
        facts.append(fact(
            "ストレート球速",
            f"平均{fastball['avg_speed_kmh']:.1f}km/h / 最速{fastball['max_speed_kmh']:.1f}km/h",
            "fastball_velocity", fastball, src,
        ))
    gap = summary.get("velocity_gap") or {}
    if gap.get("gap_kmh") is not None:
        facts.append(fact(
            "球種間の球速差",
            f"{gap['fastest_pitch_type']}平均{gap['fastest_avg_speed_kmh']:.1f}km/h → "
            f"{gap['slowest_pitch_type']}平均{gap['slowest_avg_speed_kmh']:.1f}km/h "
            f"（差{gap['gap_kmh']:.1f}km/h）",
            "pitch_velocity_gap", gap, src,
        ))
    finishers = summary.get("strikeout_finish_by_pitch") or []
    finisher_text = "、".join(f"{row['pitch_type']} {integer(row.get('strikeouts'))}個" for row in finishers)
    if finisher_text:
        facts.append(fact("奪三振の決め球", finisher_text, "strikeout_finish_pitches", finishers, src))
    elif summary.get("strikeout_finishes") == 0:
        facts.append(fact("奪三振の決め球", "三振決着なし", "strikeout_finish_pitches", [], src))
    two_strike_mix = format_mix(summary.get("two_strike_mix"))
    if two_strike_mix:
        facts.append(fact(
            "2ストライク時の球種構成",
            f"計{integer(summary.get('two_strike_pitches'))}球：{two_strike_mix}",
            "two_strike_pitch_mix", summary.get("two_strike_mix"), src,
        ))
    if integer(summary.get("zone_seen")):
        facts.append(fact(
            "ゾーン内・外",
            f"ゾーン内 {num(summary.get('in_zone_rate')) * 100:.1f}% / 外 {num(summary.get('out_zone_rate')) * 100:.1f}%（判定{integer(summary.get('zone_seen'))}球）",
            "zone_rate", [summary.get("in_zone_rate"), summary.get("out_zone_rate"), summary.get("zone_seen")], src,
        ))
    cautions = []
    if integer(summary.get("pitches")) < 50:
        cautions.append(f"{label_prefix}のpitch集計は{integer(summary.get('pitches'))}球の小標本")
    return facts, cautions, [src]


def batter_pitch_facts(summary, label_prefix="打撃"):
    if not summary:
        return [], [], []
    fields = ["batter_key", "batting_team", "pitch_type", "is_swing", "is_miss", "is_called", "is_last_pitch", "ab_result", "ab_hit"]
    src = pitch_source(summary, fields)
    facts = []
    mix = format_mix(summary.get("pitch_mix"))
    if mix:
        facts.append(fact(
            f"{label_prefix}で見た球種",
            f"計{integer(summary.get('pitches_seen'))}球：{mix}",
            "pitches_seen_mix", summary.get("pitch_mix"), src,
        ))
    rates = []
    if summary.get("whiff_rate") is not None:
        rates.append(f"空振り率 {num(summary.get('whiff_rate')) * 100:.1f}%（空振り/スイング）")
    if summary.get("called_strike_rate") is not None:
        rates.append(f"見逃しストライク率 {num(summary.get('called_strike_rate')) * 100:.1f}%（見逃しストライク/非スイング）")
    if rates:
        facts.append(fact(
            "空振り・見逃し",
            " / ".join(rates),
            "swing_take_rates", [summary.get("whiff_rate"), summary.get("called_strike_rate")], src,
        ))
    results = summary.get("terminal_results_by_pitch") or []
    result_text = "、".join(
        f"{row['pitch_type']} {integer(row.get('pa'))}打席{integer(row.get('hits'))}安打"
        + (f"{integer(row.get('hr'))}本塁打" if integer(row.get("hr")) else "")
        + (f"{integer(row.get('strikeouts'))}三振" if integer(row.get("strikeouts")) else "")
        + (f"{integer(row.get('recorded_outs'))}記録アウト" if integer(row.get("recorded_outs")) else "")
        for row in results
    )
    if result_text:
        facts.append(fact("打席決着球種別", result_text, "terminal_results_by_pitch", results, src))
    cautions = []
    if integer(summary.get("pitches_seen")) < 30:
        cautions.append(f"{label_prefix}のpitch集計は{integer(summary.get('pitches_seen'))}球の小標本")
    return facts, cautions, [src]


def innings_text(outs):
    if outs in (None, ""):
        return None
    outs = integer(outs)
    return f"{outs // 3}.{outs % 3}"


def player_identity(row, prefix):
    key = row.get(f"{prefix}_key") or row.get(f"{prefix}_id")
    name = row.get(prefix)
    team_field = "fielding_team" if prefix == "pitcher" else "batting_team"
    return str(key or name or ""), name or "", row.get(team_field) or ""


def matching_pitching_lines(rows, player_key, name, team):
    exact = [row for row in rows or [] if player_key and str(row.get("player_key") or row.get("player_id") or "") == str(player_key)]
    if exact:
        return exact
    return [row for row in rows or [] if row.get("player") == name and (not team or row.get("team") == team)]


def pitcher_material(rows, pitching_lines=None):
    rows = list(rows or [])
    summary = summarize_pitcher_pitches(rows)
    if not summary:
        return None
    _, name, team = player_identity(rows[0], "pitcher")
    player_key = rows[0].get("pitcher_key") or rows[0].get("pitcher_id")
    lines = matching_pitching_lines(pitching_lines, player_key, name, team)
    starts = sum(truthy(row.get("is_starter")) for row in lines)
    relief = max(0, len(lines) - starts)
    if starts and relief:
        role = "先発・救援"
    elif starts:
        role = "先発"
    elif relief:
        role = "救援"
    else:
        role = "データ不足"
    outs = sum(integer(row.get("outs")) for row in lines) if lines else None
    tto = summarize_times_through_order(rows)
    src = pitch_source(
        summary,
        ["game_id", "atbat_no", "atbat_index", "pitch_no", "batter_key", "pitcher_key", "pitch_type", "speed_kmh", "strikes_before", "in_zone", "is_last_pitch", "ab_result", "ab_out_type"],
    )
    sample_note = None
    if role in {"救援", "先発・救援"}:
        sample_note = f"救援登板を含むn={integer(summary.get('pitches'))}球。小標本では傾向を断定しない"
    elif integer(summary.get("pitches")) < 50:
        sample_note = f"n={integer(summary.get('pitches'))}球の小標本。傾向を断定しない"
    return {
        "player_key": player_key,
        "name": name,
        "team": team,
        "role": role,
        "appearances": len({str(row.get("game_id") or "") for row in lines}) if lines else len(summary.get("game_ids") or []),
        "starts": starts,
        "relief_appearances": relief,
        "innings": innings_text(outs),
        "outs": outs,
        "pitches": summary.get("pitches"),
        "pitch_mix": summary.get("pitch_mix"),
        "fastball": summary.get("fastball"),
        "pitch_type_velocity": summary.get("pitch_type_velocity"),
        "velocity_gap": summary.get("velocity_gap"),
        "strikeout_finish_by_pitch": summary.get("strikeout_finish_by_pitch"),
        "two_strike": {
            "pitches": summary.get("two_strike_pitches"),
            "pitch_mix": summary.get("two_strike_mix"),
        },
        "zone": {
            "seen": summary.get("zone_seen"),
            "in_zone": summary.get("in_zone"),
            "out_zone": summary.get("out_zone"),
            "in_zone_rate": summary.get("in_zone_rate"),
            "out_zone_rate": summary.get("out_zone_rate"),
        },
        "times_through_order": tto,
        "sample_note": sample_note,
        "source": src,
    }


def batter_material(rows, minimum_pa=MIN_GAME_BATTER_PA):
    rows = list(rows or [])
    summary = summarize_batter_pitches(rows)
    if not summary:
        return None
    player_key, name, team = player_identity(rows[0], "batter")
    pa = integer(summary.get("plate_appearances"))
    game_count = len(summary.get("game_ids") or [])
    sample_note = (
        f"{pa}打席・{integer(summary.get('pitches_seen'))}球の1試合標本。傾向を断定しない"
        if game_count <= 1 else
        f"{game_count}試合・{pa}打席・{integer(summary.get('pitches_seen'))}球。1試合より信頼度は高いが短期傾向の理由は断定しない"
    )
    src = pitch_source(
        summary,
        ["game_id", "atbat_no", "atbat_index", "pitch_no", "batter_key", "pitcher_key", "pitch_type", "is_swing", "is_miss", "is_called", "is_last_pitch", "ab_result", "ab_out_type", "ab_hit"],
    )
    return {
        "player_key": player_key or None,
        "name": name,
        "team": team,
        "plate_appearances": pa,
        "pitches_seen": summary.get("pitches_seen"),
        "article_eligible": pa >= minimum_pa,
        "minimum_pa_for_article": minimum_pa,
        "pitch_mix": summary.get("pitch_mix"),
        "swings": summary.get("swings"),
        "misses": summary.get("misses"),
        "whiff_rate": summary.get("whiff_rate"),
        "taken_pitches": summary.get("taken_pitches"),
        "called_strikes": summary.get("called_strikes"),
        "called_strike_rate": summary.get("called_strike_rate"),
        "terminal_results_by_pitch": summary.get("terminal_results_by_pitch"),
        "sample_note": sample_note,
        "source": src,
    }


def team_batting_material(rows):
    rows = list(rows or [])
    summary = summarize_batter_pitches(rows)
    if not summary:
        return None
    src = pitch_source(
        summary,
        ["game_id", "batting_team", "pitch_type", "is_swing", "is_miss", "is_called", "is_last_pitch", "ab_result", "ab_out_type", "ab_hit"],
    )
    return {
        "team": rows[0].get("batting_team") or "",
        "plate_appearances": summary.get("plate_appearances"),
        "pitches_seen": summary.get("pitches_seen"),
        "pitch_mix": summary.get("pitch_mix"),
        "whiff_rate": summary.get("whiff_rate"),
        "called_strike_rate": summary.get("called_strike_rate"),
        "terminal_results_by_pitch": summary.get("terminal_results_by_pitch"),
        "source": src,
    }


def build_game_pitch_material(pitches, pitching_lines, game_id):
    game_rows = pitch_rows_for(pitches, game_ids=[game_id])
    if not game_rows:
        return None
    game_lines = [row for row in pitching_lines or [] if str(row.get("game_id") or "") == str(game_id)]
    pitcher_groups = defaultdict(list)
    team_groups = defaultdict(list)
    batter_groups = defaultdict(list)
    for row in game_rows:
        pitcher_key, pitcher_name, fielding_team = player_identity(row, "pitcher")
        if pitcher_key:
            pitcher_groups[(fielding_team, pitcher_key, pitcher_name)].append(row)
        batting_team = row.get("batting_team") or ""
        if batting_team:
            team_groups[batting_team].append(row)
        batter_key, batter_name, _ = player_identity(row, "batter")
        if batter_key:
            batter_groups[(batting_team, batter_key, batter_name)].append(row)
    pitchers = [pitcher_material(rows, game_lines) for rows in pitcher_groups.values()]
    teams = [team_batting_material(rows) for rows in team_groups.values()]
    batters = [batter_material(rows) for rows in batter_groups.values()]
    pitchers = [row for row in pitchers if row]
    teams = [row for row in teams if row]
    batters = [row for row in batters if row]
    pitchers.sort(key=lambda row: (row.get("team") or "", 0 if row.get("role") == "先発" else 1, row.get("name") or ""))
    teams.sort(key=lambda row: row.get("team") or "")
    batters.sort(key=lambda row: (row.get("team") or "", -integer(row.get("plate_appearances")), row.get("name") or ""))
    summary = summarize_batter_pitches(game_rows)
    return {
        "scope": {
            "date": summary.get("date_start") if summary else None,
            "game_id": str(game_id),
            "dataset": "pitches.csv",
            "pitches": len(game_rows),
            "minimum_pa_for_batter_article": MIN_GAME_BATTER_PA,
        },
        "pitchers": pitchers,
        "team_batting": teams,
        "batters": batters,
    }


def tto_fact(material, label_prefix):
    turns = (material or {}).get("times_through_order") or []
    if len(turns) < 2:
        return None
    parts = []
    for row in turns:
        top = (row.get("pitch_mix") or [{}])[0]
        top_text = f" / 最多{top.get('pitch_type')} {num(top.get('share')) * 100:.1f}%" if top.get("pitch_type") else ""
        parts.append(f"{integer(row.get('turn'))}巡目 n={integer(row.get('pitches'))}球{top_text}")
    return fact(
        f"{label_prefix}の巡目別配球",
        "、".join(parts),
        "times_through_order",
        turns,
        material.get("source"),
    )


def _row_player_key(row):
    return str(row.get("player_key") or row.get("player_id") or f"{row.get('team', '')}:{row.get('player', '')}")


def _window_rows(rows, limit=None):
    ordered_games = sorted(
        {(str(row.get("game_id") or ""), str(row.get("date") or "")) for row in rows if row.get("game_id")},
        key=lambda item: (item[1], item[0]),
    )
    if limit:
        ordered_games = ordered_games[-limit:]
    game_ids = {game_id for game_id, _ in ordered_games}
    selected = [row for row in rows if not game_ids or str(row.get("game_id") or "") in game_ids]
    dates = [date for _, date in ordered_games if date]
    return selected, {
        "games": len(ordered_games),
        "date_start": min(dates) if dates else None,
        "date_end": max(dates) if dates else None,
        "latest_game_id": ordered_games[-1][0] if ordered_games else None,
    }


def _periods(rows, aggregator):
    periods = {}
    for name, limit in (("latest", 1), ("recent5", 5), ("recent10", 10), ("season", None)):
        selected, scope = _window_rows(rows, limit)
        periods[name] = {**scope, "stats": aggregator(selected)}
    return periods


def _compact_batter_pitch(summary):
    if not summary:
        return None
    return {
        "pitches_seen": summary.get("pitches_seen"),
        "plate_appearances": summary.get("plate_appearances"),
        "whiff_rate": summary.get("whiff_rate"),
        "called_strike_rate": summary.get("called_strike_rate"),
        "pitch_mix": (summary.get("pitch_mix") or [])[:5],
        "date_start": summary.get("date_start"),
        "date_end": summary.get("date_end"),
    }


def _compact_pitcher_pitch(summary):
    if not summary:
        return None
    return {
        "pitches": summary.get("pitches"),
        "fastball": summary.get("fastball"),
        "pitch_mix": (summary.get("pitch_mix") or [])[:6],
        "two_strike_pitches": summary.get("two_strike_pitches"),
        "two_strike_mix": (summary.get("two_strike_mix") or [])[:5],
        "strikeout_finish_by_pitch": (summary.get("strikeout_finish_by_pitch") or [])[:5],
        "zone_seen": summary.get("zone_seen"),
        "in_zone_rate": summary.get("in_zone_rate"),
        "out_zone_rate": summary.get("out_zone_rate"),
        "date_start": summary.get("date_start"),
        "date_end": summary.get("date_end"),
    }


def _team_record(games, team):
    wins = losses = ties = runs = allowed = 0
    for game in games:
        is_home = game.get("home") == team
        scored = integer(game.get("home_score") if is_home else game.get("away_score"))
        conceded = integer(game.get("away_score") if is_home else game.get("home_score"))
        runs += scored
        allowed += conceded
        if scored > conceded:
            wins += 1
        elif scored < conceded:
            losses += 1
        else:
            ties += 1
    count = len(games)
    return {
        "games": count, "wins": wins, "losses": losses, "ties": ties,
        "runs": runs, "allowed": allowed,
        "runs_per_game": rounded(runs / count, 2) if count else None,
        "allowed_per_game": rounded(allowed / count, 2) if count else None,
    }


def build_custom_context(games, batting, pitching, season_batting, season_pitching, pitches, data_date):
    """Build a compact, browser-safe index for user-authored article themes."""
    batter_lines = defaultdict(list)
    pitcher_lines = defaultdict(list)
    batter_pitches = defaultdict(list)
    pitcher_pitches = defaultdict(list)
    for row in batting:
        if row.get("player"):
            batter_lines[_row_player_key(row)].append(row)
    for row in pitching:
        if row.get("player"):
            pitcher_lines[_row_player_key(row)].append(row)
    for row in pitches:
        batter_key = str(row.get("batter_key") or row.get("batter_id") or "")
        pitcher_key = str(row.get("pitcher_key") or row.get("pitcher_id") or "")
        if batter_key:
            batter_pitches[batter_key].append(row)
        if pitcher_key:
            pitcher_pitches[pitcher_key].append(row)

    season_bat_index = defaultdict(list)
    season_pit_index = defaultdict(list)
    for row in season_batting:
        season_bat_index[_row_player_key(row)].append(row)
    for row in season_pitching:
        season_pit_index[_row_player_key(row)].append(row)

    players = []
    for kind, grouped, season_index, pitch_grouped in (
        ("batter", batter_lines, season_bat_index, batter_pitches),
        ("pitcher", pitcher_lines, season_pit_index, pitcher_pitches),
    ):
        for key, rows in grouped.items():
            rows.sort(key=lambda row: (str(row.get("date") or ""), str(row.get("game_id") or "")))
            latest = rows[-1]
            team_history = sorted({str(row.get("team") or "") for row in rows if row.get("team")})
            period_data = _periods(rows, aggregate_batting if kind == "batter" else aggregate_pitching)
            season_rows = season_index.get(key) or []
            season_row = next((row for row in season_rows if row.get("team") == latest.get("team")), season_rows[-1] if season_rows else {})
            if kind == "batter":
                advanced = {name: rounded(num(season_row.get(name)), 3) if season_row.get(name) not in (None, "") else None for name in (
                    "iso", "babip", "bb_pct", "k_pct", "woba_est", "wrc_plus_est", "bsr_est",
                )}
                pitch_profile = _compact_batter_pitch(summarize_batter_pitches(pitch_grouped.get(key, [])))
            else:
                advanced = {name: rounded(num(season_row.get(name)), 3) if season_row.get(name) not in (None, "") else None for name in (
                    "fip", "k9", "bb9", "hr9", "k_bb", "k_pct", "bb_pct", "lob_pct_est",
                )}
                pitch_profile = _compact_pitcher_pitch(summarize_pitcher_pitches(pitch_grouped.get(key, [])))
            players.append({
                "id": f"{kind}:{key}", "kind": kind, "key": key,
                "name": latest.get("player") or "-", "team": latest.get("team") or "-",
                "league": latest.get("league") or ("パ" if latest.get("team") in PACIFIC else "セ"),
                "team_history": team_history, "periods": period_data,
                "advanced": advanced, "pitch_profile": pitch_profile,
            })
    players.sort(key=lambda row: (0 if row.get("team") == HAWKS else 1, row.get("team") or "", row.get("kind") or "", row.get("name") or ""))

    teams = []
    observed_teams = {name for game in games for name in (game.get("home"), game.get("away")) if name}
    observed_teams.update(row.get("team") for row in batting if row.get("team"))
    observed_teams.update(row.get("team") for row in pitching if row.get("team"))
    team_names = [team for team in NPB_TEAMS if team in observed_teams]
    team_names.extend(sorted(observed_teams.difference(NPB_TEAMS)))
    for team in team_names:
        team_games = sorted([game for game in games if team in (game.get("home"), game.get("away"))], key=lambda row: (str(row.get("date") or ""), str(row.get("game_id") or "")))
        periods = {}
        for name, limit in (("latest", 1), ("recent5", 5), ("recent10", 10), ("season", None)):
            selected_games = team_games[-limit:] if limit else team_games
            ids = {str(row.get("game_id") or "") for row in selected_games}
            dates = [str(row.get("date") or "") for row in selected_games if row.get("date")]
            periods[name] = {
                "games": len(selected_games), "date_start": min(dates) if dates else None,
                "date_end": max(dates) if dates else None,
                "latest_game_id": str(selected_games[-1].get("game_id") or "") if selected_games else None,
                "record": _team_record(selected_games, team),
                "batting": aggregate_batting([row for row in batting if row.get("team") == team and str(row.get("game_id") or "") in ids]),
                "pitching": aggregate_pitching([row for row in pitching if row.get("team") == team and str(row.get("game_id") or "") in ids]),
            }
        league = "パ" if team in PACIFIC else ("セ" if team in CENTRAL else "不明")
        teams.append({"team": team, "league": league, "periods": periods})

    recent_games = sorted(games, key=lambda row: (str(row.get("date") or ""), str(row.get("game_id") or "")), reverse=True)[:120]
    compact_games = [{
        "game_id": str(row.get("game_id") or ""), "date": row.get("date"),
        "home": row.get("home"), "away": row.get("away"), "stadium": row.get("stadium"),
        "home_score": integer(row.get("home_score")), "away_score": integer(row.get("away_score")), "winner": row.get("winner"),
    } for row in recent_games]
    return {
        "data_date": data_date,
        "periods": ["latest", "recent5", "recent10", "season"],
        "teams": teams, "players": players, "games": compact_games,
        "sources": ["games.csv", "batting_lines.csv", "pitching_lines.csv", "season_batting.csv", "season_pitching.csv", "pitches.csv"],
        "note": "自由入力から対象を照合し、収集済みデータだけを根拠として使用。選択されていない対象や欠損値は推測しない。",
    }


def make_idea(*, idea_id, idea_type, team, title, theme, reason, facts, angles, cautions, source_refs, score, extra_stats=None):
    idea = {
        "id": idea_id,
        "type": idea_type,
        "type_label": TYPE_LABELS[idea_type],
        "team": team,
        "league": "パ" if team in PACIFIC else "セ",
        "scope": "hawks" if team == HAWKS else ("pacific" if team in PACIFIC else "all"),
        "title": title,
        "theme": theme,
        "reason": reason,
        "facts": facts,
        "angles": angles,
        "cautions": cautions,
        "source_refs": source_refs,
        "_score": score,
    }
    if extra_stats:
        idea["extra_stats"] = extra_stats
    return idea


def latest_team_game(story, data_date, pitching_lines=None, pitches=None, team=HAWKS):
    games = (story.get("latest_games") or {}).get("games") or []
    game = next((row for row in games if team in (row.get("home"), row.get("away"))), None)
    if not game:
        return None
    game_id = str(game.get("game_id") or "")
    opponent = game.get("away") if game.get("home") == team else game.get("home")
    team_score = integer(game.get("home_score") if game.get("home") == team else game.get("away_score"))
    opponent_score = integer(game.get("away_score") if game.get("home") == team else game.get("home_score"))
    result = "勝利" if team_score > opponent_score else ("敗戦" if team_score < opponent_score else "引き分け")
    offense = game.get("offense") if game.get("winner") == team else game.get("opponent_offense")
    offense = offense or {}
    team_pitching = [
        row for row in (pitching_lines or [])
        if str(row.get("game_id") or "") == game_id and row.get("team") == team
    ]
    starter_row = next((row for row in team_pitching if truthy(row.get("is_starter"))), None)
    starter = None
    if starter_row:
        starter = {
            "name": starter_row.get("player") or "-",
            "key": starter_row.get("player_key") or starter_row.get("player_id"),
            "innings": f"{integer(starter_row.get('outs')) // 3}.{integer(starter_row.get('outs')) % 3}",
            "outs": integer(starter_row.get("outs")),
            "earned_runs": integer(starter_row.get("earned_runs")),
            "runs_allowed": integer(starter_row.get("runs_allowed")),
            "so": integer(starter_row.get("so")),
            "bb": integer(starter_row.get("bb")),
            "hits_allowed": integer(starter_row.get("hits_allowed")),
            "pitches": integer(starter_row.get("pitches")),
        }
    elif game.get("winner") == team:
        starter = game.get("starter")
    reliever_rows = [row for row in team_pitching if row is not starter_row]
    bullpen = aggregate_pitching(reliever_rows) if reliever_rows else (game.get("bullpen") if game.get("winner") == team else None)
    src_game = source("games.csv", data_date, game_id, ["home_score", "away_score", "winner"])
    facts = [fact("試合結果", f"{team} {team_score}－{opponent_score} {opponent}", "score", [team_score, opponent_score], src_game)]
    if offense:
        facts.extend([
            fact("チーム安打", f"{integer(offense.get('hits'))}安打", "hits", integer(offense.get("hits")), source("batting_lines.csv", data_date, game_id, ["hits"])),
            fact("本塁打・四球", f"{integer(offense.get('hr'))}本塁打 / {integer(offense.get('bb'))}四球", "hr_bb", [integer(offense.get("hr")), integer(offense.get("bb"))], source("batting_lines.csv", data_date, game_id, ["hr", "bb"])),
        ])
    if starter:
        facts.append(fact("先発", f"{starter.get('name')} {starter.get('innings')}回 自責{integer(starter.get('earned_runs'))} 奪三振{integer(starter.get('so'))}", "starter_line", starter, source("pitching_lines.csv", data_date, game_id, ["player", "outs", "earned_runs", "so"])))
    if bullpen:
        facts.append(fact("救援陣", f"{bullpen.get('innings')}回 自責{integer(bullpen.get('earned_runs'))}", "bullpen_line", bullpen, source("pitching_lines.csv", data_date, game_id, ["outs", "earned_runs"])))
    pitch_cautions = []
    pitch_refs = []
    if starter:
        starter_rows = pitch_rows_for(
            pitches, game_ids=[game_id], pitcher_key=starter.get("key"),
            pitcher_name=None if starter.get("key") else starter.get("name"), fielding_team=team,
        )
        starter_summary = summarize_pitcher_pitches(starter_rows)
        extra, cautions, refs = pitcher_pitch_facts(starter_summary, "先発")
        facts.extend(extra); pitch_cautions.extend(cautions); pitch_refs.extend(refs)
    team_batting_rows = pitch_rows_for(pitches, game_ids=[game_id], batting_team=team)
    batting_summary = summarize_batter_pitches(team_batting_rows)
    team_label = "ホークス" if team == HAWKS else team
    extra, cautions, refs = batter_pitch_facts(batting_summary, f"{team_label}打線")
    facts.extend(extra); pitch_cautions.extend(cautions); pitch_refs.extend(refs)
    game_pitch_material = build_game_pitch_material(pitches, pitching_lines, game_id)
    if game_pitch_material:
        scope = game_pitch_material.get("scope") or {}
        material_src = source(
            "pitches.csv", data_date, game_id,
            ["pitcher_key", "batter_key", "atbat_no", "pitch_no", "pitch_type", "speed_kmh", "is_swing", "is_miss", "is_called", "is_last_pitch"],
        )
        facts.append(fact(
            "1球データ素材",
            f"{integer(scope.get('pitches'))}球 / 登板{len(game_pitch_material.get('pitchers') or [])}投手 / 打者{len(game_pitch_material.get('batters') or [])}人",
            "pitch_material_coverage",
            [scope.get("pitches"), len(game_pitch_material.get("pitchers") or []), len(game_pitch_material.get("batters") or [])],
            material_src,
        ))
        if starter:
            starter_material = next((row for row in game_pitch_material.get("pitchers") or []
                                     if row.get("team") == team and
                                     ((starter.get("key") and str(row.get("player_key") or "") == str(starter.get("key")))
                                      or row.get("name") == starter.get("name"))), None)
            round_fact = tto_fact(starter_material, starter.get("name") or "先発")
            if round_fact:
                facts.append(round_fact)
        pitch_refs.append(material_src)
        pitch_cautions.extend([
            "救援投手は1試合の投球数が少ないため、extra_stats内のn（投球数）を確認し傾向を断定しない",
            "個人打者は1試合4〜5打席程度の小標本。extra_statsは記事素材であり、単独で傾向を断定しない",
            "巡目別配球は同一打者の登場回数による観測上の区分。配球を変えた理由はデータから断定しない",
        ])
    if result == "勝利":
        title = f"{team_label}が{opponent}戦を{team_score}－{opponent_score}で勝利　数字から見えたポイント"
        reason = f"最新データ日の{team_label}戦は{result}。スコアだけで勝因を断定せず、打線・先発・救援のどこに目立つ数字があったかを整理できる。"
    else:
        title = f"{team_label}の{opponent}戦を検証　{team_score}－{opponent_score}の数字から何が見える？"
        reason = f"最新データ日の{team_label}戦は{result}。結果だけでなく、打線・先発・救援の数字を分けて見ることで次戦への論点を探せる。"
    return make_idea(
        idea_id=f"{'hawks' if team == HAWKS else 'team-' + team}-game-{game_id}", idea_type="game", team=team, title=title,
        theme=f"{data_date}の{team_label}戦を、ボックススコアの事実から振り返る",
        reason=reason, facts=facts,
        angles=["得点と安打・四球の関係", "先発が作った試合展開", "救援陣が残した数字"],
        cautions=["勝因の因果推定ではなく、当日の集計値から目立つ要素を扱う", "守備位置や打球品質など未収集要素は評価しない", *pitch_cautions],
        source_refs=[src_game, source("batting_lines.csv", data_date, game_id), source("pitching_lines.csv", data_date, game_id), *pitch_refs], score=100,
        extra_stats={"pitch_data": game_pitch_material} if game_pitch_material else None,
    )


def latest_hawks_game(story, data_date, pitching_lines=None, pitches=None):
    """Backward-compatible wrapper for existing callers and tests."""
    return latest_team_game(story, data_date, pitching_lines, pitches, HAWKS)


def team_trend_idea(trend, data_date, hawks=False):
    if not trend:
        return None
    team = trend.get("team")
    recent, season, delta = trend.get("recent") or {}, trend.get("season") or {}, trend.get("delta") or {}
    rr, sr = recent.get("record") or {}, season.get("record") or {}
    rb, sb = recent.get("batting") or {}, season.get("batting") or {}
    rp, sp = recent.get("pitching") or {}, season.get("pitching") or {}
    facts = [
        fact("直近10試合", record_text(rr), "recent_record", rr, source("games.csv", data_date, fields=["home", "away", "home_score", "away_score"])),
        fact("1試合平均得点", f"直近 {num(rr.get('runs_per_game')):.2f} / シーズン {num(sr.get('runs_per_game')):.2f}", "runs_per_game", [rr.get("runs_per_game"), sr.get("runs_per_game")], source("games.csv", data_date, fields=["home_score", "away_score"])),
        fact("OPS", f"直近 {format_rate(rb.get('ops'))} / シーズン {format_rate(sb.get('ops'))}", "ops", [rb.get("ops"), sb.get("ops")], source("batting_lines.csv", data_date, fields=["ab", "hits", "doubles", "triples", "hr", "bb", "hbp"])),
        fact("防御率", f"直近 {num(rp.get('era')):.2f} / シーズン {num(sp.get('era')):.2f}", "era", [rp.get("era"), sp.get("era")], source("pitching_lines.csv", data_date, fields=["outs", "earned_runs"])),
        fact("OPS変化", format_signed(delta.get("ops")), "ops_delta", delta.get("ops"), source("_story_insights.json", data_date)),
        fact("防御率変化", format_signed(delta.get("era"), 2), "era_delta", delta.get("era"), source("_story_insights.json", data_date)),
    ]
    wins = integer(rr.get("wins")); games = integer(rr.get("games"))
    ops_delta = num(delta.get("ops"), 0); era_delta = num(delta.get("era"), 0)
    mismatch = wins >= 6 and abs(ops_delta) < .025 and era_delta <= -.3
    if hawks and mismatch:
        title = "ホークスは本当に打線で勝っている？直近10試合を数字で確認"
        reason = f"直近10試合は{record_text(rr)}。一方、OPSはシーズン平均とほぼ同水準で、防御率は{abs(era_delta):.2f}改善している。勝敗と打撃指標が完全には一致しない点が記事の問いになる。"
        angles = ["勝率上昇とOPSが一致しているか", "防御率・失点ペースの変化", "得点増が長打以外から生まれている可能性"]
    else:
        title = f"{team}は直近10試合で何が変わった？シーズン平均と比較"
        change_text = "、".join(trend.get("changes") or [])
        reason = f"直近10試合は{record_text(rr)}。{change_text or '複数指標を比較すると変化の有無を確認できる'}。成績の良し悪しだけでなく、どの数字が動いたかを掘れる。"
        angles = ["勝敗と得点・失点の変化", "OPSと得点ペースの関係", "防御率と失点ペースの関係"]
    score = (35 if hawks else 0) + abs(ops_delta) * 180 + abs(era_delta) * 8 + abs(num(delta.get("runs_per_game"), 0)) * 4 + games
    return make_idea(
        idea_id=f"team-trend-{team}", idea_type="trend", team=team, title=title,
        theme=f"{team}の直近10試合をシーズン平均と比較する", reason=reason, facts=facts,
        angles=angles, cautions=["直近10試合の短期サンプル", "対戦相手・球場・日程の影響は未調整", "変化は原因を証明するものではない"],
        source_refs=[source("games.csv", data_date), source("batting_lines.csv", data_date), source("pitching_lines.csv", data_date), source("_story_insights.json", data_date)], score=score,
    )


def row_key(row):
    return str(row.get("player_key") or row.get("player_id") or row.get("player") or "")


def team_player_idea(games, batting, season_batting, pitches, data_date, team=HAWKS):
    team_games = sorted([g for g in games if team in (g.get("home"), g.get("away"))], key=lambda g: (g.get("date") or "", str(g.get("game_id") or "")))[-10:]
    game_ids = {str(g.get("game_id") or "") for g in team_games}
    groups = defaultdict(list)
    for row in batting:
        if row.get("team") == team and str(row.get("game_id") or "") in game_ids:
            groups[row_key(row)].append(row)
    season_map = {row_key(r): r for r in season_batting if r.get("team") == team}
    candidates = []
    for key, rows in groups.items():
        recent = aggregate_batting(rows); season = season_map.get(key)
        if not season or recent.get("pa", 0) < 20 or integer(season.get("pa")) < 80:
            continue
        recent_ops, season_ops = recent.get("ops"), num(season.get("ops"), None)
        if recent_ops is None or season_ops is None:
            continue
        delta = recent_ops - season_ops
        score = abs(delta) * 100 + min(recent.get("pa", 0), 45) / 10
        candidates.append((score, abs(delta), key, rows, recent, season, delta))
    if not candidates:
        return None
    _, _, key, rows, recent, season, delta = max(candidates)
    name = season.get("player") or rows[0].get("player") or "選手名不明"
    direction = "上がった" if delta >= 0 else "下がった"
    title = f"{name}の直近10試合で何が変わった？シーズン平均と比較"
    reason = f"直近のOPSは{format_rate(recent.get('ops'))}で、シーズンOPSから{format_signed(delta)}。短期の好不調を断定せず、安打・長打・四球・三振のどこが{direction}のかを確認できる。"
    recent_games = len({str(r.get("game_id") or "") for r in rows})
    facts = [
        fact("直近出場", f"{recent_games}試合 / {recent.get('pa')}打席", "recent_sample", [recent_games, recent.get("pa")], source("batting_lines.csv", data_date, fields=["game_id", "ab", "bb", "hbp", "sac"])),
        fact("直近OPS", format_rate(recent.get("ops")), "recent_ops", recent.get("ops"), source("batting_lines.csv", data_date)),
        fact("シーズンOPS", format_rate(season.get("ops")), "season_ops", num(season.get("ops"), None), source("season_batting.csv", data_date, fields=["ops"])),
        fact("OPS変化", format_signed(delta), "ops_delta", rounded(delta), source("batting_lines.csv + season_batting.csv", data_date)),
        fact("直近打撃", f"{recent.get('hits')}安打 {recent.get('hr')}本塁打 {recent.get('bb')}四球", "recent_events", [recent.get("hits"), recent.get("hr"), recent.get("bb")], source("batting_lines.csv", data_date, fields=["hits", "hr", "bb"])),
        fact("直近三振", f"{recent.get('so')}三振", "recent_so", recent.get("so"), source("batting_lines.csv", data_date, fields=["so"])),
    ]
    player_pitch_rows = pitch_rows_for(pitches, game_ids=game_ids, batter_key=key, batting_team=team)
    pitch_summary = summarize_batter_pitches(player_pitch_rows)
    pitch_facts, pitch_cautions, pitch_refs = batter_pitch_facts(pitch_summary, name)
    facts.extend(pitch_facts)
    player_material = batter_material(player_pitch_rows)
    return make_idea(
        idea_id=f"{'hawks' if team == HAWKS else 'team-' + team}-player-{key}", idea_type="player", team=team, title=title,
        theme=f"{name}の直近成績とシーズン成績の差を調べる", reason=reason, facts=facts,
        angles=["OPS変化を出塁と長打に分ける", "安打・本塁打・四球・三振の変化", "チームの得点や勝敗との同時期の動き"],
        cautions=["直近10試合の短期サンプル", "対戦投手・球場の影響は未調整", "OPSの変化だけで技術的原因は断定できない", "複数試合の横断集計は1試合より信頼度が高いが、配球の理由までは断定しない", *pitch_cautions],
        source_refs=[source("batting_lines.csv", data_date), source("season_batting.csv", data_date), *pitch_refs], score=85 + abs(delta) * 30,
        extra_stats={"player_batting": player_material} if player_material else None,
    )


def hawks_player_idea(games, batting, season_batting, pitches, data_date):
    """Backward-compatible wrapper for the Hawks-priority editorial feed."""
    return team_player_idea(games, batting, season_batting, pitches, data_date, HAWKS)


def team_two_strike_idea(story, pitches, pitching_lines, data_date, team=HAWKS):
    quality = ((story.get("quality") or {}).get("two_strike") or {})
    if quality.get("definition_version") != 2 or not quality.get("validated"):
        return None
    candidates = [p for p in story.get("two_strike_pitchers") or [] if p.get("team") == team and integer(p.get("pitches")) >= 50]
    if not candidates:
        return None
    pitcher = max(candidates, key=lambda p: (integer(p.get("pitches")), num(p.get("k_finish_rate"))))
    name = pitcher.get("name") or "投手名不明"
    top = (pitcher.get("pitch_types") or [{}])[0]
    player_pitch_rows = pitch_rows_for(pitches, pitcher_key=pitcher.get("key"), fielding_team=team)
    pitch_summary = summarize_pitcher_pitches(player_pitch_rows)
    verified_src = (
        pitch_source(
            pitch_summary,
            ["pitcher_key", "pitch_type", "strikes_before", "is_last_pitch", "ab_result", "ab_out_type"],
            "_story_insights.jsonで検証済み定義により事前集計",
        )
        if pitch_summary
        else source("pitches.csv", data_date, fields=quality.get("source_fields"), note="pitch行が無いためgame_id特定不可")
    )
    facts = [
        fact("2ストライク後", f"{integer(pitcher.get('pitches'))}球", "two_strike_pitches", integer(pitcher.get("pitches")), verified_src),
        fact("三振決着球率", f"{num(pitcher.get('k_finish_rate')) * 100:.1f}%", "strikeout_finish_rate", pitcher.get("k_finish_rate"), verified_src),
        fact("空振り三振決着率", f"{num(pitcher.get('whiff_rate')) * 100:.1f}%", "swinging_strikeout_finish_rate", pitcher.get("whiff_rate"), verified_src),
        fact("最多球種", f"{top.get('pitch_type', 'データ不足')} {num(top.get('share')) * 100:.1f}%", "top_pitch", [top.get("pitch_type"), top.get("share")], verified_src),
    ]
    pitch_facts, pitch_cautions, pitch_refs = pitcher_pitch_facts(pitch_summary, name)
    facts.extend(pitch_facts)
    player_material = pitcher_material(player_pitch_rows, pitching_lines)
    round_fact = tto_fact(player_material, name)
    if round_fact:
        facts.append(round_fact)
    return make_idea(
        idea_id=f"{'hawks' if team == HAWKS else 'team-' + team}-two-strike-{pitcher.get('key')}", idea_type="player", team=team,
        title=f"{name}は追い込んでから何を投げている？2ストライク後の配球を検証",
        theme=f"{name}の2ストライク後の球種と三振決着を分析する",
        reason=f"2ストライク後を{integer(pitcher.get('pitches'))}球確認できる。最多球種と実際に三振で打席が終わった投球を分け、追い込んでからの傾向を記事にできる。",
        facts=facts, angles=["2ストライク後の球種構成", "三振決着に使われた球種", "右打者・左打者で配球が違うか"],
        cautions=["球種は収集データ上の分類", "三振決着は is_last_pitch・ab_out_type・ab_result を同時に確認", "巡目は試合ごとに同一打者の登場回数を数え、1巡しかない登板は比較対象外", "複数試合を横断した傾向でも、配球を選んだ理由や意図は断定しない", "配球傾向から意図や投球技術の原因は断定しない", *pitch_cautions],
        source_refs=[source("pitches.csv", data_date, fields=quality.get("source_fields")), source("_story_insights.json", data_date), *pitch_refs], score=80 + min(integer(pitcher.get("pitches")), 500) / 100,
        extra_stats={"player_pitching": player_material} if player_material else None,
    )


def hawks_two_strike_idea(story, pitches, pitching_lines, data_date):
    """Backward-compatible wrapper for the Hawks-priority editorial feed."""
    return team_two_strike_idea(story, pitches, pitching_lines, data_date, HAWKS)


def build(season, base="data"):
    season = str(season); root = os.path.join(base, season); dataset = os.path.join(root, "dataset")
    output_path = os.path.join(root, "_article_ideas.json")
    os.makedirs(root, exist_ok=True)
    games = load_csv(os.path.join(dataset, "games.csv"))
    if not games:
        output = {"schema_version": 2, "season": season, "data_date": None, "generated_at": datetime.now(JST).isoformat(),
                  "status": "data_unavailable", "message": "収集済みの試合データがありません。", "ideas": [], "team_ideas": [],
                  "custom_context": {"data_date": None, "teams": [], "players": [], "games": [], "sources": []}}
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(output, handle, ensure_ascii=False, separators=(",", ":"))
        print(f"[WARN] article ideas: no games ({dataset})")
        return output
    data_date = max(str(g.get("date") or "") for g in games if g.get("date"))
    story_path = os.path.join(root, "_story_insights.json")
    story = read_json(story_path)
    if not story or (story.get("latest_games") or {}).get("date") != data_date:
        story = build_story(season, base)
    batting = load_csv(os.path.join(dataset, "batting_lines.csv"))
    pitching = load_csv(os.path.join(dataset, "pitching_lines.csv"))
    pitches = load_csv(os.path.join(dataset, "pitches.csv"))
    season_batting = load_csv(os.path.join(dataset, "season_batting.csv"))
    season_pitching = load_csv(os.path.join(dataset, "season_pitching.csv"))
    ideas = []
    latest = latest_hawks_game(story, data_date, pitching, pitches)
    if latest:
        ideas.append(latest)
    trends = {row.get("team"): row for row in story.get("team_trends") or []}
    hawks_trend = team_trend_idea(trends.get(HAWKS), data_date, hawks=True)
    if hawks_trend:
        ideas.append(hawks_trend)
    player = hawks_player_idea(games, batting, season_batting, pitches, data_date)
    if player:
        ideas.append(player)
    pitch = hawks_two_strike_idea(story, pitches, pitching, data_date)
    if pitch:
        ideas.append(pitch)
    other_trends = [team_trend_idea(row, data_date) for row in trends.values() if row.get("team") in PACIFIC and row.get("team") != HAWKS]
    other_trends = [row for row in other_trends if row]
    for other in sorted(other_trends, key=lambda row: row["_score"], reverse=True):
        if len(ideas) >= 5:
            break
        ideas.append(other)
    # Keep the editorial mix stable: Hawks first (roughly 70–80%), then the strongest Pacific change.
    seen = set(); selected = []
    for row in ideas:
        if row["id"] in seen:
            continue
        seen.add(row["id"]); selected.append(row)
    selected = selected[:5]
    for rank, row in enumerate(selected, 1):
        row["rank"] = rank
        row.pop("_score", None)

    # Build a separate editorial catalog for every observed NPB club.  The
    # default five-item Hawks-first feed above stays unchanged; selecting a
    # specific club in ARTICLE LAB switches to this catalog.
    observed_teams = {name for game in games for name in (game.get("home"), game.get("away")) if name}
    catalog_teams = [team for team in NPB_TEAMS if team in observed_teams]
    catalog_teams.extend(sorted(observed_teams.difference(NPB_TEAMS)))
    team_ideas = []
    for team in catalog_teams:
        candidates = [
            latest_team_game(story, data_date, pitching, pitches, team),
            team_trend_idea(trends.get(team), data_date, hawks=team == HAWKS),
            team_player_idea(games, batting, season_batting, pitches, data_date, team),
            team_two_strike_idea(story, pitches, pitching, data_date, team),
        ]
        team_ideas.extend(row for row in candidates if row)
    deduped_catalog = []
    seen_catalog = set()
    for row in sorted(team_ideas, key=lambda item: item.get("_score", 0), reverse=True):
        if row["id"] in seen_catalog:
            continue
        seen_catalog.add(row["id"])
        deduped_catalog.append(row)
    for rank, row in enumerate(deduped_catalog, 1):
        row["rank"] = rank
        row.pop("_score", None)
    output = {
        "schema_version": 2, "season": season, "data_date": data_date,
        "generated_at": datetime.now(JST).isoformat(), "status": "ok",
        "selection_note": "最新の収集日を基準に、変化・不一致・問いが生まれる候補を優先。初期表示はホークス中心、球団を選べば12球団それぞれの候補に切り替わります。",
        "source_summary": {"games": len(games), "batting_lines": len(batting), "pitching_lines": len(pitching), "pitches": len(pitches), "story_insights": os.path.basename(story_path)},
        "ideas": selected,
        "team_ideas": deduped_catalog,
        "custom_context": build_custom_context(games, batting, pitching, season_batting, season_pitching, pitches, data_date),
    }
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False, separators=(",", ":"))
    covered_teams = len({row.get("team") for row in deduped_catalog if row.get("team")})
    print(f"[INFO] article ideas: date={data_date} / ideas={len(selected)} / hawks={sum(1 for i in selected if i['team']==HAWKS)} / team_catalog={len(deduped_catalog)} ideas for {covered_teams} teams")
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", required=True)
    parser.add_argument("--base", default="data")
    args = parser.parse_args()
    build(args.season, args.base)
    return 0


if __name__ == "__main__":
    sys.exit(main())
