"""Shared, source-data-only pitch metrics for editorial analysis.

The functions in this module never infer missing events.  A metric is returned as
``None`` (or an empty collection) when the required source fields are unavailable.
"""

from __future__ import annotations

from collections import Counter, defaultdict


def truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def integer(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def number(value, default=None):
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def rounded_ratio(numerator, denominator, digits=3):
    return round(numerator / denominator, digits) if denominator else None


def is_verified_strikeout_finish(row):
    """True only when this pitch verifiably ended the plate appearance in a strikeout."""
    if not truthy(row.get("is_last_pitch")):
        return False
    out_type = str(row.get("ab_out_type") or "").strip()
    result = str(row.get("ab_result") or "").strip()
    return out_type == "三振" and "三振" in result


def is_swinging_strikeout_finish(row):
    return is_verified_strikeout_finish(row) and str(row.get("ab_result") or "").strip().startswith("空振り三振")


def is_called_strikeout_finish(row):
    return is_verified_strikeout_finish(row) and str(row.get("ab_result") or "").strip().startswith("見逃し三振")


def _pitch_mix(rows):
    counts = Counter(str(row.get("pitch_type") or "").strip() for row in rows)
    counts.pop("", None)
    total = sum(counts.values())
    return [
        {"pitch_type": pitch_type, "pitches": pitches, "share": rounded_ratio(pitches, total)}
        for pitch_type, pitches in counts.most_common()
    ]


def _pitch_type_velocity(rows):
    """Return observed velocity by pitch type without filling missing readings."""
    grouped = defaultdict(list)
    pitch_counts = Counter()
    for row in rows:
        pitch_type = str(row.get("pitch_type") or "").strip()
        if not pitch_type:
            continue
        pitch_counts[pitch_type] += 1
        speed = number(row.get("speed_kmh"))
        if speed is not None and speed > 0:
            grouped[pitch_type].append(speed)
    result = []
    for pitch_type, pitches in pitch_counts.most_common():
        speeds = grouped.get(pitch_type, [])
        result.append({
            "pitch_type": pitch_type,
            "pitches": pitches,
            "pitches_with_speed": len(speeds),
            "avg_speed_kmh": round(sum(speeds) / len(speeds), 1) if speeds else None,
            "max_speed_kmh": round(max(speeds), 1) if speeds else None,
            "min_speed_kmh": round(min(speeds), 1) if speeds else None,
        })
    return result


def _velocity_gap(items):
    observed = [item for item in items if item.get("avg_speed_kmh") is not None]
    if len(observed) < 2:
        return None
    fastest = max(observed, key=lambda item: item["avg_speed_kmh"])
    slowest = min(observed, key=lambda item: item["avg_speed_kmh"])
    return {
        "fastest_pitch_type": fastest["pitch_type"],
        "fastest_avg_speed_kmh": fastest["avg_speed_kmh"],
        "slowest_pitch_type": slowest["pitch_type"],
        "slowest_avg_speed_kmh": slowest["avg_speed_kmh"],
        "gap_kmh": round(fastest["avg_speed_kmh"] - slowest["avg_speed_kmh"], 1),
    }


def _scope(rows):
    dates = sorted({str(row.get("date") or "") for row in rows if row.get("date")})
    game_ids = sorted({str(row.get("game_id") or "") for row in rows if row.get("game_id")})
    return {
        "date_start": dates[0] if dates else None,
        "date_end": dates[-1] if dates else None,
        "game_ids": game_ids,
    }


def summarize_pitcher_pitches(rows):
    """Summarize pitch selection, velocity, finish pitches, counts, and location."""
    rows = list(rows or [])
    if not rows:
        return None

    pitch_mix = _pitch_mix(rows)
    pitch_type_velocity = _pitch_type_velocity(rows)
    fastballs = [
        number(row.get("speed_kmh"))
        for row in rows
        if str(row.get("pitch_type") or "").strip() == "ストレート"
    ]
    fastballs = [speed for speed in fastballs if speed is not None and speed > 0]
    strikeout_pitches = Counter(
        str(row.get("pitch_type") or "").strip()
        for row in rows
        if is_verified_strikeout_finish(row) and str(row.get("pitch_type") or "").strip()
    )
    two_strike_rows = [row for row in rows if integer(row.get("strikes_before"), -1) == 2]
    zone_rows = [row for row in rows if str(row.get("in_zone") or "").strip()]
    in_zone = sum(truthy(row.get("in_zone")) for row in zone_rows)
    scope = _scope(rows)
    return {
        **scope,
        "pitches": len(rows),
        "pitch_mix": pitch_mix,
        "pitch_type_velocity": pitch_type_velocity,
        "velocity_gap": _velocity_gap(pitch_type_velocity),
        "fastball": {
            "pitches_with_speed": len(fastballs),
            "avg_speed_kmh": round(sum(fastballs) / len(fastballs), 1) if fastballs else None,
            "max_speed_kmh": round(max(fastballs), 1) if fastballs else None,
        },
        "strikeout_finishes": sum(strikeout_pitches.values()),
        "strikeout_finish_by_pitch": [
            {"pitch_type": pitch_type, "strikeouts": count}
            for pitch_type, count in strikeout_pitches.most_common()
        ],
        "two_strike_pitches": len(two_strike_rows),
        "two_strike_mix": _pitch_mix(two_strike_rows),
        "zone_seen": len(zone_rows),
        "in_zone": in_zone,
        "out_zone": len(zone_rows) - in_zone,
        "in_zone_rate": rounded_ratio(in_zone, len(zone_rows)),
        "out_zone_rate": rounded_ratio(len(zone_rows) - in_zone, len(zone_rows)),
    }


def summarize_batter_pitches(rows):
    """Summarize pitches seen and terminal plate-appearance results for batters."""
    rows = list(rows or [])
    if not rows:
        return None

    swing_rows = [row for row in rows if row.get("is_swing") not in (None, "")]
    has_miss_data = any(row.get("is_miss") not in (None, "") for row in rows)
    has_called_data = any(row.get("is_called") not in (None, "") for row in rows)
    swings = sum(truthy(row.get("is_swing")) for row in swing_rows)
    misses = sum(truthy(row.get("is_miss")) for row in rows) if has_miss_data else None
    taken = len(swing_rows) - swings
    called = sum(truthy(row.get("is_called")) for row in rows) if has_called_data else None
    terminal_by_type = defaultdict(lambda: {"pa": 0, "hits": 0, "hr": 0, "strikeouts": 0, "recorded_outs": 0, "results": Counter()})
    for row in rows:
        pitch_type = str(row.get("pitch_type") or "").strip()
        if not pitch_type or not truthy(row.get("is_last_pitch")):
            continue
        item = terminal_by_type[pitch_type]
        item["pa"] += 1
        if integer(row.get("ab_hit")) > 0:
            item["hits"] += 1
        if "本塁打" in str(row.get("ab_result") or ""):
            item["hr"] += 1
        if is_verified_strikeout_finish(row):
            item["strikeouts"] += 1
        if str(row.get("ab_out_type") or "").strip():
            item["recorded_outs"] += 1
        result = str(row.get("ab_result") or "").strip()
        if result:
            item["results"][result] += 1
    results = []
    for pitch_type, values in terminal_by_type.items():
        result_counts = values.pop("results")
        results.append({
            "pitch_type": pitch_type,
            **values,
            "results": [{"result": result, "count": count} for result, count in result_counts.most_common()],
        })
    results.sort(key=lambda item: (item["pa"], item["hits"], item["hr"]), reverse=True)
    scope = _scope(rows)
    terminal_rows = [row for row in rows if truthy(row.get("is_last_pitch"))]
    return {
        **scope,
        "pitches_seen": len(rows),
        "plate_appearances": len(terminal_rows),
        "pitch_mix": _pitch_mix(rows),
        "swings": swings,
        "misses": misses,
        "whiff_rate": rounded_ratio(misses, swings) if misses is not None else None,
        "taken_pitches": taken,
        "called_strikes": called,
        "called_strike_rate": rounded_ratio(called, taken) if called is not None else None,
        "terminal_results_by_pitch": results,
    }


def summarize_times_through_order(rows):
    """Summarize pitch usage by each batter's appearance number in a game.

    Appearance numbers are assigned only when game, batter and plate-appearance
    identifiers are present.  The counter resets for each game.  A one-turn sample
    intentionally returns an empty list because it cannot describe a change.
    """
    rows = list(rows or [])
    if not rows:
        return []
    ordered = sorted(rows, key=lambda row: (
        str(row.get("date") or ""),
        str(row.get("game_id") or ""),
        integer(row.get("atbat_no"), 0),
        str(row.get("atbat_index") or ""),
        integer(row.get("pitch_no"), 0),
    ))
    batter_counts = Counter()
    pa_turn = {}
    turn_rows = defaultdict(list)
    turn_pas = defaultdict(set)
    for row in ordered:
        game_id = str(row.get("game_id") or "").strip()
        batter_key = str(row.get("batter_key") or row.get("batter_id") or row.get("batter") or "").strip()
        atbat_id = str(row.get("atbat_index") or row.get("atbat_no") or "").strip()
        if not game_id or not batter_key or not atbat_id:
            continue
        pa_key = (game_id, atbat_id, batter_key)
        if pa_key not in pa_turn:
            count_key = (game_id, batter_key)
            batter_counts[count_key] += 1
            pa_turn[pa_key] = batter_counts[count_key]
        turn = pa_turn[pa_key]
        turn_rows[turn].append(row)
        turn_pas[turn].add(pa_key)
    if not turn_rows or max(turn_rows) < 2:
        return []
    output = []
    for turn in sorted(turn_rows):
        selected = turn_rows[turn]
        speeds = [number(row.get("speed_kmh")) for row in selected]
        speeds = [speed for speed in speeds if speed is not None and speed > 0]
        finish_rows = [row for row in selected if truthy(row.get("is_last_pitch"))]
        output.append({
            "turn": turn,
            "plate_appearances": len(turn_pas[turn]),
            "pitches": len(selected),
            "pitch_mix": _pitch_mix(selected),
            "avg_speed_kmh": round(sum(speeds) / len(speeds), 1) if speeds else None,
            "finish_pitch_mix": _pitch_mix(finish_rows),
        })
    return output
