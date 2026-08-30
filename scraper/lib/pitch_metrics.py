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
    terminal_by_type = defaultdict(lambda: {"pa": 0, "hits": 0, "hr": 0, "strikeouts": 0})
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
    results = [
        {"pitch_type": pitch_type, **values}
        for pitch_type, values in terminal_by_type.items()
    ]
    results.sort(key=lambda item: (item["pa"], item["hits"], item["hr"]), reverse=True)
    scope = _scope(rows)
    return {
        **scope,
        "pitches_seen": len(rows),
        "pitch_mix": _pitch_mix(rows),
        "swings": swings,
        "misses": misses,
        "whiff_rate": rounded_ratio(misses, swings) if misses is not None else None,
        "taken_pitches": taken,
        "called_strikes": called,
        "called_strike_rate": rounded_ratio(called, taken) if called is not None else None,
        "terminal_results_by_pitch": results,
    }
