"""Build rolling 5-game / 15-game player trends for W-Impact."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from .normalize import team_info
from .w_impact import calculate, number, truthy


def _sum(rows, key):
    return sum(number(row.get(key)) for row in rows)


def _date(value):
    return date.fromisoformat(str(value)[:10])


def _game_token(row):
    date_text = str(row.get("date") or "")[:10]
    return date_text, str(row.get("game_id") or date_text)


def _recent_player_rows(rows, as_of, window):
    """Select each player's latest N appearances through ``as_of``."""
    as_of_text = as_of.isoformat()
    grouped = defaultdict(list)
    for row in rows:
        key = row.get("player_key")
        if key and str(row.get("date") or "")[:10] <= as_of_text:
            grouped[key].append(row)

    selected = []
    selected_games = {}
    for key, player_rows in grouped.items():
        tokens = sorted({_game_token(row) for row in player_rows})[-window:]
        wanted = set(tokens)
        selected.extend(row for row in player_rows if _game_token(row) in wanted)
        selected_games[key] = wanted
    return selected, selected_games


def _related_rows(rows, key_field, selected_games, as_of):
    as_of_text = as_of.isoformat()
    return [
        row for row in rows
        if (
            row.get(key_field) in selected_games
            and str(row.get("date") or "")[:10] <= as_of_text
            and _game_token(row) in selected_games[row.get(key_field)]
        )
    ]


def _team_windows(games, as_of, window):
    counts = defaultdict(int)
    for game in games:
        if str(game.get("date") or "")[:10] > as_of.isoformat():
            continue
        for key in ("home", "away"):
            team = game.get(key)
            if team:
                counts[team] += 1
    return [
        {"team": team, "games": min(window, games)}
        for team, games in counts.items()
    ]


def _aggregate_players(base_players, batting_lines, pitching_lines, constants):
    base_by_key = {player.get("key"): player for player in base_players if player.get("key")}
    bat_by_key = defaultdict(list)
    pit_by_key = defaultdict(list)
    for row in batting_lines:
        if row.get("player_key"):
            bat_by_key[row["player_key"]].append(row)
    for row in pitching_lines:
        if row.get("player_key"):
            pit_by_key[row["player_key"]].append(row)

    result = []
    for key in sorted(set(bat_by_key) | set(pit_by_key)):
        source = base_by_key.get(key) or {}
        sample = (bat_by_key.get(key) or pit_by_key.get(key) or [{}])[0]
        player = {
            "key": key,
            "player_id": source.get("player_id") or sample.get("player_id"),
            "name": source.get("name") or sample.get("player"),
            "team": source.get("team") or sample.get("team"),
            "position": source.get("position"),
        }

        bat_rows = bat_by_key.get(key, [])
        if bat_rows:
            ab = _sum(bat_rows, "ab")
            hits = _sum(bat_rows, "hits")
            bb = _sum(bat_rows, "bb")
            hbp = _sum(bat_rows, "hbp")
            sac = _sum(bat_rows, "sac")
            singles = _sum(bat_rows, "singles")
            doubles = _sum(bat_rows, "doubles")
            triples = _sum(bat_rows, "triples")
            hr = _sum(bat_rows, "hr")
            pa = ab + bb + hbp + sac
            total_bases = singles + doubles * 2 + triples * 3 + hr * 4
            obp = (hits + bb + hbp) / pa if pa else None
            slg = total_bases / ab if ab else None
            player["batting"] = {
                "games": len({row.get("game_id") for row in bat_rows}),
                "pa": int(pa), "ab": int(ab), "hits": int(hits),
                "ops": (obp + slg) if obp is not None and slg is not None else None,
                "hr": int(hr), "rbi": int(_sum(bat_rows, "rbi")),
                "runs": int(_sum(bat_rows, "runs")),
                "sb": int(_sum(bat_rows, "sb")),
                "caught_stealing": int(_sum(bat_rows, "caught_stealing")),
                "baserunning_outs": int(_sum(bat_rows, "baserunning_outs")),
                "errors": int(_sum(bat_rows, "errors")),
            }

        pit_rows = pit_by_key.get(key, [])
        if pit_rows:
            outs = int(_sum(pit_rows, "outs"))
            innings = outs / 3
            earned_runs = _sum(pit_rows, "earned_runs")
            strikeouts = _sum(pit_rows, "so")
            walks = _sum(pit_rows, "bb")
            hit_batters = _sum(pit_rows, "hbp")
            home_runs = _sum(pit_rows, "hr_allowed")
            league = team_info(player["team"]).get("league")
            constant = number((constants.get(league) or {}).get("constant"), 3.1)
            fip = (
                (13 * home_runs + 3 * (walks + hit_batters) - 2 * strikeouts)
                / innings + constant
                if innings else None
            )
            decisions = [str(row.get("decision") or "") for row in pit_rows]
            wins = sum("勝" in decision for decision in decisions)
            losses = sum("敗" in decision for decision in decisions)
            saves = sum("Ｓ" in decision or decision == "S" for decision in decisions)
            holds = sum("Ｈ" in decision or decision == "H" for decision in decisions)
            relief_wins = sum(
                "勝" in str(row.get("decision") or "") and not truthy(row.get("is_starter"))
                for row in pit_rows
            )
            player["pitching"] = {
                "games": len({row.get("game_id") for row in pit_rows}),
                "outs": outs,
                "era": earned_runs * 9 / innings if innings else None,
                "fip": fip,
                "k9": strikeouts * 9 / innings if innings else None,
                "so": int(strikeouts), "bb": int(walks),
                "wins": wins, "losses": losses, "saves": saves,
                "holds": holds, "holds_est": holds,
                "relief_wins": relief_wins, "hp": holds + relief_wins,
            }
        result.append(player)
    return result


def _append_snapshot(output, calculated, as_of, window, active):
    date_text = as_of.isoformat()
    for kind, rows in (("batter", calculated["batters"]), ("pitcher", calculated["pitchers"])):
        for row in rows:
            key = row["player_key"]
            if key not in active[kind]:
                continue
            player = output.setdefault(key, {
                "name": row["name"], "team": row["team"],
                "batter": {"5": [], "15": []},
                "pitcher": {"5": [], "15": []},
            })
            stats = row.get("stats") or {}
            point = {
                "date": date_text,
                "w_rating": row.get("w_rating"),
                "w_value": row.get("w_value"),
                "games": stats.get("games", 0),
            }
            if kind == "batter":
                point.update({"ops": stats.get("ops"), "pa": stats.get("pa", 0)})
            else:
                point.update({
                    "era": stats.get("era"),
                    "innings": stats.get("innings", 0),
                })
            player[kind][str(window)].append(point)


def build_rolling_trends(
    players, games, batting_lines, pitching_lines, atbats,
    runner_events=None, fip_constants=None, windows=(5, 15),
):
    """Return rolling metrics based on each player's latest appearances."""
    game_dates = sorted({_date(game["date"]) for game in games if game.get("date")})
    if not game_dates:
        return {"latest_date": None, "windows": list(windows), "players": {}}

    latest = game_dates[-1]
    constants = (fip_constants or {}).get("constants", fip_constants or {})
    output = {}

    for window in windows:
        for as_of in game_dates:
            as_of_text = as_of.isoformat()
            bat_rows, bat_games = _recent_player_rows(
                batting_lines, as_of, window
            )
            pit_rows, _ = _recent_player_rows(
                pitching_lines, as_of, window
            )
            atbat_rows = _related_rows(
                atbats, "batter_key", bat_games, as_of
            )
            runner_rows = _related_rows(
                runner_events or [], "player_key", bat_games, as_of
            )
            window_players = _aggregate_players(
                players, bat_rows, pit_rows, constants
            )
            if not window_players:
                continue
            calculated = calculate(
                window_players, _team_windows(games, as_of, window),
                bat_rows, pit_rows, atbat_rows, runner_rows,
            )
            active = {
                "batter": {
                    row.get("player_key") for row in batting_lines
                    if str(row.get("date") or "")[:10] == as_of_text
                },
                "pitcher": {
                    row.get("player_key") for row in pitching_lines
                    if str(row.get("date") or "")[:10] == as_of_text
                },
            }
            _append_snapshot(output, calculated, as_of, window, active)

    for player in output.values():
        for kind in ("batter", "pitcher"):
            for window in windows:
                key = str(window)
                player[kind][key] = player[kind][key][-window:]

    return {
        "latest_date": latest.isoformat(),
        "mode": "player_appearances",
        "windows": list(windows),
        "players": output,
    }
