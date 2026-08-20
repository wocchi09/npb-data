"""Build day-over-day W-Impact leaderboard movement data."""

from __future__ import annotations

from datetime import date

from .w_impact import calculate
from .w_impact_trends import _aggregate_players, _team_windows


def _date_text(row):
    return str(row.get("date") or "")[:10]


def _through(rows, cutoff):
    return [row for row in rows if _date_text(row) and _date_text(row) <= cutoff]


def _snapshot(players, games, batting_lines, pitching_lines, atbats,
              runner_events, constants, cutoff):
    cutoff_date = date.fromisoformat(cutoff)
    bat = _through(batting_lines, cutoff)
    pit = _through(pitching_lines, cutoff)
    aggregated = _aggregate_players(players, bat, pit, constants)
    return calculate(
        aggregated,
        _team_windows(games, cutoff_date, 999),
        bat,
        pit,
        _through(atbats, cutoff),
        _through(runner_events, cutoff),
    )


def _rank_rows(current, previous, active_keys, kind):
    previous_by_league = {}
    for league in ("セ", "パ"):
        rows = [row for row in previous if row.get("league") == league]
        rows.sort(key=lambda row: (-float(row.get("w_value") or 0),
                                   -float(row.get("w_rating") or 0),
                                   str(row.get("name") or "")))
        previous_by_league[league] = {
            row.get("player_key"): (index + 1, row)
            for index, row in enumerate(rows)
        }

    output = {"セ": [], "パ": []}
    for league in ("セ", "パ"):
        rows = [row for row in current if row.get("league") == league]
        rows.sort(key=lambda row: (-float(row.get("w_value") or 0),
                                   -float(row.get("w_rating") or 0),
                                   str(row.get("name") or "")))
        for index, row in enumerate(rows):
            key = row.get("player_key")
            previous_entry = previous_by_league[league].get(key)
            previous_rank = previous_entry[0] if previous_entry else None
            previous_row = previous_entry[1] if previous_entry else {}
            stats = row.get("stats") or {}
            item = {
                "player_key": key,
                "player_id": row.get("player_id"),
                "name": row.get("name"),
                "team": row.get("team"),
                "current_rank": index + 1,
                "previous_rank": previous_rank,
                "rank_change": previous_rank - (index + 1) if previous_rank else None,
                "is_new": previous_rank is None,
                "w_value": row.get("w_value"),
                "w_value_change": round(
                    float(row.get("w_value") or 0) -
                    float(previous_row.get("w_value") or 0), 2
                ),
                "w_rating": row.get("w_rating"),
                "w_rating_change": round(
                    float(row.get("w_rating") or 0) -
                    float(previous_row.get("w_rating") or 0), 1
                ),
                "games": stats.get("games", (
                    row.get("batting_games", 0) + row.get("pitching_games", 0)
                )),
                "active_today": key in active_keys,
            }
            if kind == "pitcher":
                item["role"] = row.get("role")
                item["innings"] = stats.get("innings", 0)
            elif kind == "batter":
                item["position"] = stats.get("primary_position") or row.get("position")
                item["pa"] = stats.get("pa", 0)
            output[league].append(item)
    return output


def build_ranking_changes(players, games, batting_lines, pitching_lines,
                          atbats, runner_events=None, fip_constants=None,
                          current_result=None):
    """Compare cumulative W-Impact ranks on the latest two game dates."""
    dates = sorted({_date_text(game) for game in games if _date_text(game)})
    if len(dates) < 2:
        return {
            "current_date": dates[-1] if dates else None,
            "previous_date": None,
            "leagues": {"セ": {}, "パ": {}},
        }

    previous_date, current_date = dates[-2], dates[-1]
    constants = (fip_constants or {}).get("constants", fip_constants or {})
    current = current_result or _snapshot(
        players, games, batting_lines, pitching_lines, atbats,
        runner_events or [], constants, current_date,
    )
    previous = _snapshot(
        players, games, batting_lines, pitching_lines, atbats,
        runner_events or [], constants, previous_date,
    )

    batter_active = {
        row.get("player_key") for row in batting_lines
        if _date_text(row) == current_date and row.get("player_key")
    }
    pitcher_active = {
        row.get("player_key") for row in pitching_lines
        if _date_text(row) == current_date and row.get("player_key")
    }
    active = {
        "overall": batter_active | pitcher_active,
        "batter": batter_active,
        "pitcher": pitcher_active,
    }
    by_kind = {}
    for kind, key in (("overall", "overall"), ("batter", "batters"),
                      ("pitcher", "pitchers")):
        by_kind[kind] = _rank_rows(
            current.get(key, []), previous.get(key, []), active[kind], kind,
        )

    leagues = {"セ": {}, "パ": {}}
    for league in leagues:
        for kind in by_kind:
            leagues[league][kind] = by_kind[kind][league]

    return {
        "current_date": current_date,
        "previous_date": previous_date,
        "metric": "W-Impact ranking movement",
        "ranked_by": "W-Value (W-Rating tiebreak)",
        "leagues": leagues,
    }
