"""W-Impact / W-Rating calculation.

This is a transparent site-original contribution index, not WAR or UZR.
Only recorded events are scored. Missing defensive tracking data is never
estimated.
"""

from __future__ import annotations

import math
from collections import defaultdict

from .baserunning import (
    BASERUNNING_OUT_VALUE,
    CS_RUN_VALUE,
    SB_RUN_VALUE,
    aggregate_runner_events,
)
from .normalize import team_info


FIELD_POSITIONS = ("捕", "一", "二", "三", "遊", "左", "中", "右", "指")
POSITION_DIFFICULTY = {
    "捕": 8.0, "遊": 6.0, "二": 3.0, "中": 3.0, "三": 1.0,
    "左": 0.0, "右": 0.0, "一": -2.0, "指": -5.0,
}
POSITION_GROUP = {
    "捕": "battery", "一": "infield", "二": "infield", "三": "infield",
    "遊": "infield", "左": "outfield", "中": "outfield", "右": "outfield",
    "指": "dh",
}

BATTER_WEIGHTS = {
    "batting": 0.45,
    "clutch": 0.15,
    "baserunning": 0.08,
    "defense": 0.12,
    "role": 0.10,
    "versatility": 0.05,
    "availability": 0.05,
}
PITCHER_WEIGHTS = {
    "pitching": 0.50,
    "dominance": 0.15,
    "run_prevention": 0.15,
    "role": 0.15,
    "availability": 0.05,
}
def number(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def truthy(value):
    return str(value).lower() in ("1", "true", "yes")


def _dedupe_players(players):
    """Keep the most complete row when a collected player key is duplicated."""
    unique = {}
    without_key = []

    def volume(player):
        batting = player.get("batting") or {}
        pitching = player.get("pitching") or {}
        return (
            number(batting.get("games")) + number(pitching.get("games")),
            number(batting.get("pa")) + number(pitching.get("outs")) / 3,
            number(batting.get("ab")) + number(pitching.get("games")),
        )

    for player in players:
        key = player.get("key")
        if not key:
            without_key.append(player)
            continue
        current = unique.get(key)
        if current is None or volume(player) > volume(current):
            unique[key] = player
    return list(unique.values()) + without_key


def positions_from_text(value):
    """Return actual fielding positions from strings such as '打一' or '一三'."""
    text = str(value or "")
    return [p for p in FIELD_POSITIONS if p in text]


def shrink(value, mean, sample, prior):
    weight = sample / (sample + prior) if sample > 0 else 0
    return value * weight + mean * (1 - weight)


def _z_values(rows, key):
    values = [number(r["raw"].get(key)) for r in rows]
    if not values:
        return {}
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    sd = math.sqrt(variance)
    return {
        r["player_key"]: (number(r["raw"].get(key)) - mean) / sd
        if sd > 1e-9 else 0.0
        for r in rows
    }


def _rating(weighted_z):
    return round(max(40.0, min(180.0, 100 + 15 * weighted_z)), 1)


def _component_rating(z):
    # tanhで上下限へ滑らかに近づけ、複数選手の上限張り付きを防ぐ。
    return round(100 + 60 * math.tanh(z / 4), 1)


def _weighted_z(z):
    """Prevent one extreme component from dominating the total rating."""
    return max(-4.0, min(4.0, z))


def _league(player):
    lg = team_info(player.get("team")).get("league")
    return lg if lg in ("セ", "パ") else None


def _clamp(value, low, high):
    return max(low, min(high, value))


def _confidence(score):
    """Return a transparent sample-size confidence label for display."""
    score = int(round(_clamp(score, 0, 100)))
    if score >= 90:
        label, level = "非常に高い", 5
    elif score >= 75:
        label, level = "高い", 4
    elif score >= 55:
        label, level = "標準", 3
    elif score >= 35:
        label, level = "参考", 2
    else:
        label, level = "低い", 1
    return {
        "score": score,
        "label": label,
        "level": level,
        "stars": "★" * level + "☆" * (5 - level),
    }


def _line_pa(row):
    return sum(number(row.get(key)) for key in ("ab", "bb", "hbp", "sac"))


def _line_tb(row):
    return (
        number(row.get("singles")) + number(row.get("doubles")) * 2
        + number(row.get("triples")) * 3 + number(row.get("hr")) * 4
    )


def build_context_adjustments(batting_lines, pitching_lines):
    """Build shrunk park and opponent-strength adjustments from collected lines.

    The factors are intentionally conservative. Park factors use team-game runs
    and regress 20 team-games toward 1.00. Opponent offense/pitching strength is
    also regressed toward the league mean. No missing event is estimated.
    """
    team_bat = defaultdict(lambda: defaultdict(float))
    team_pitch = defaultdict(lambda: defaultdict(float))
    park_team_games = defaultdict(dict)

    for row in batting_lines:
        team = row.get("team")
        lg = team_info(team).get("league")
        if lg not in ("セ", "パ"):
            continue
        bucket = team_bat[team]
        for key in ("ab", "hits", "bb", "hbp", "sac"):
            bucket[key] += number(row.get(key))
        bucket["tb"] += _line_tb(row)
        game_id, stadium = row.get("game_id"), row.get("stadium")
        if game_id and stadium:
            game_key = f"{game_id}|{team}"
            item = park_team_games[lg].setdefault(game_key, {
                "stadium": stadium, "runs": 0.0,
            })
            item["runs"] += number(row.get("runs"))

    for row in pitching_lines:
        team = row.get("team")
        lg = team_info(team).get("league")
        if lg not in ("セ", "パ"):
            continue
        bucket = team_pitch[team]
        bucket["outs"] += number(row.get("outs"))
        bucket["runs"] += number(row.get("runs_allowed"))

    league_ops = {}
    league_ra9 = {}
    team_ops = {}
    team_ra9 = {}
    for lg in ("セ", "パ"):
        batting_teams = [t for t in team_bat if team_info(t).get("league") == lg]
        pitching_teams = [t for t in team_pitch if team_info(t).get("league") == lg]
        totals = defaultdict(float)
        for team in batting_teams:
            for key, value in team_bat[team].items():
                totals[key] += value
        league_pa = totals["ab"] + totals["bb"] + totals["hbp"] + totals["sac"]
        league_obp = ((totals["hits"] + totals["bb"] + totals["hbp"]) / league_pa
                      if league_pa else 0.0)
        league_slg = totals["tb"] / totals["ab"] if totals["ab"] else 0.0
        league_ops[lg] = league_obp + league_slg
        total_outs = sum(team_pitch[t]["outs"] for t in pitching_teams)
        total_runs = sum(team_pitch[t]["runs"] for t in pitching_teams)
        league_ra9[lg] = total_runs * 27 / total_outs if total_outs else 4.0

        for team in batting_teams:
            b = team_bat[team]
            pa = b["ab"] + b["bb"] + b["hbp"] + b["sac"]
            obp = (b["hits"] + b["bb"] + b["hbp"]) / pa if pa else league_obp
            slg = b["tb"] / b["ab"] if b["ab"] else league_slg
            raw = obp + slg
            team_ops[team] = shrink(raw, league_ops[lg], pa, 600)
        for team in pitching_teams:
            p = team_pitch[team]
            ip = p["outs"] / 3
            raw = p["runs"] * 9 / ip if ip else league_ra9[lg]
            team_ra9[team] = shrink(raw, league_ra9[lg], ip, 180)

    park_factors = {}
    for lg in ("セ", "パ"):
        games = list(park_team_games[lg].values())
        league_mean = sum(x["runs"] for x in games) / len(games) if games else 1.0
        by_park = defaultdict(list)
        for item in games:
            by_park[item["stadium"]].append(item["runs"])
        for stadium, rows in by_park.items():
            raw = (sum(rows) / len(rows)) / league_mean if league_mean else 1.0
            shrunk = shrink(raw, 1.0, len(rows), 20)
            park_factors[(lg, stadium)] = round(_clamp(shrunk, 0.85, 1.15), 3)

    batter_context = defaultdict(lambda: {"weight": 0.0, "park": 0.0, "opponent": 0.0})
    for row in batting_lines:
        key, team = row.get("player_key"), row.get("team")
        lg, weight = team_info(team).get("league"), _line_pa(row)
        if not key or lg not in ("セ", "パ") or weight <= 0:
            continue
        park = park_factors.get((lg, row.get("stadium")), 1.0)
        opponent = row.get("opponent")
        # A lower opponent RA9 means a harder pitching staff.
        opp_factor = (league_ra9[lg] / team_ra9.get(opponent, league_ra9[lg])
                      if league_ra9[lg] else 1.0)
        item = batter_context[key]
        item["weight"] += weight
        item["park"] += park * weight
        item["opponent"] += opp_factor * weight

    pitcher_context = defaultdict(lambda: {"weight": 0.0, "park": 0.0, "opponent": 0.0})
    for row in pitching_lines:
        key, team = row.get("player_key"), row.get("team")
        lg, weight = team_info(team).get("league"), number(row.get("outs"))
        if not key or lg not in ("セ", "パ") or weight <= 0:
            continue
        park = park_factors.get((lg, row.get("stadium")), 1.0)
        opponent = row.get("opponent")
        opp_factor = (team_ops.get(opponent, league_ops[lg]) / league_ops[lg]
                      if league_ops[lg] else 1.0)
        item = pitcher_context[key]
        item["weight"] += weight
        item["park"] += park * weight
        item["opponent"] += opp_factor * weight

    def finish(source, pitcher=False):
        result = {}
        for key, item in source.items():
            weight = item["weight"]
            park = item["park"] / weight if weight else 1.0
            opponent = item["opponent"] / weight if weight else 1.0
            environment = park * opponent
            # Batter: neutral OPS = OPS * opponent difficulty / park.
            # Pitcher: neutral run rate = observed rate / run environment.
            adjustment = 1 / environment if pitcher else opponent / park
            result[key] = {
                "park_factor": round(park, 3),
                "opponent_factor": round(opponent, 3),
                "adjustment": round(_clamp(adjustment, 0.90, 1.10), 3),
                "sample": round(weight, 1),
            }
        return result

    return {
        "batters": finish(batter_context),
        "pitchers": finish(pitcher_context, pitcher=True),
        "park_factors": {f"{lg}|{park}": factor
                         for (lg, park), factor in park_factors.items()},
        "method": "season_shrunk_park_opponent_v1",
    }


def collect_batter_roles(batting_lines):
    roles = defaultdict(lambda: {
        "starts": 0, "pinch_hit_apps": 0, "pinch_hit_pa": 0,
        "pinch_hit_hits": 0, "pinch_hit_on_base": 0, "pinch_hit_rbi": 0,
        "pinch_run_apps": 0, "pinch_run_runs": 0, "pinch_run_sb": 0,
        "def_sub_apps": 0, "position_apps": defaultdict(int),
    })
    for row in batting_lines:
        key = row.get("player_key")
        if not key:
            continue
        role = roles[key]
        sub_type = row.get("sub_type") or ""
        ab = number(row.get("ab"))
        bb = number(row.get("bb"))
        hbp = number(row.get("hbp"))
        sac = number(row.get("sac"))
        hits = number(row.get("hits"))
        if truthy(row.get("is_starter")):
            role["starts"] += 1
        if sub_type == "代打":
            role["pinch_hit_apps"] += 1
            role["pinch_hit_pa"] += ab + bb + hbp + sac
            role["pinch_hit_hits"] += hits
            role["pinch_hit_on_base"] += hits + bb + hbp
            role["pinch_hit_rbi"] += number(row.get("rbi"))
        elif sub_type == "代走":
            role["pinch_run_apps"] += 1
            role["pinch_run_runs"] += number(row.get("runs"))
            role["pinch_run_sb"] += number(row.get("sb"))

        field_positions = positions_from_text(row.get("position"))
        if sub_type == "守備" and field_positions and "投" not in str(row.get("position")):
            role["def_sub_apps"] += 1
        if sub_type not in ("代打", "代走"):
            for pos in field_positions:
                role["position_apps"][pos] += 1
    return roles


def collect_clutch(atbats):
    clutch = defaultdict(lambda: {
        "risp_pa": 0, "risp_hits": 0, "risp_rbi": 0,
        "late_pa": 0, "late_hits": 0, "late_rbi": 0,
    })
    for row in atbats:
        key = row.get("batter_key")
        if not key:
            continue
        item = clutch[key]
        pa = number(row.get("pa"))
        hit = number(row.get("hit"))
        rbi = number(row.get("rbi"))
        if truthy(row.get("risp")):
            item["risp_pa"] += pa
            item["risp_hits"] += hit
            item["risp_rbi"] += rbi
        if number(row.get("inning")) >= 7:
            item["late_pa"] += pa
            item["late_hits"] += hit
            item["late_rbi"] += rbi
    return clutch


def collect_pitcher_roles(pitching_lines):
    roles = defaultdict(lambda: {
        "starts": 0, "relief_apps": 0, "scoreless_relief": 0,
        "qs": 0, "saves_in_lines": 0,
    })
    for row in pitching_lines:
        key = row.get("player_key")
        if not key:
            continue
        role = roles[key]
        if truthy(row.get("is_starter")):
            role["starts"] += 1
            if truthy(row.get("is_qs")):
                role["qs"] += 1
        else:
            role["relief_apps"] += 1
            if number(row.get("earned_runs")) == 0:
                role["scoreless_relief"] += 1
        decision = str(row.get("decision") or "")
        if "Ｓ" in decision or decision == "S":
            role["saves_in_lines"] += 1
    return roles


def _pitcher_role(pitching, role):
    games = int(number(pitching.get("games")))
    starts = role["starts"]
    saves = int(number(pitching.get("saves")))
    if starts and starts >= max(1, games - starts):
        return "先発"
    if saves >= max(2, int(games * 0.15)):
        return "抑え"
    return "中継ぎ"


def calculate(players, teams, batting_lines, pitching_lines, atbats,
              runner_events=None):
    players = _dedupe_players(players)
    team_games = {t.get("team"): int(number(t.get("games"))) for t in teams}
    batter_roles = collect_batter_roles(batting_lines)
    pitcher_roles = collect_pitcher_roles(pitching_lines)
    clutch = collect_clutch(atbats)
    event_agg = aggregate_runner_events(runner_events)
    runner_diag = {
        "source": "runner_events" if runner_events else "players/stats.json",
        "events": len(runner_events or []),
    }
    context_model = build_context_adjustments(batting_lines, pitching_lines)

    def runner_stats(player):
        batting = player.get("batting") or {}
        shared = event_agg.get(player.get("key"))
        if shared:
            return shared
        sb = int(number(batting.get("sb")))
        cs = int(number(batting.get("caught_stealing")))
        outs = int(number(batting.get("baserunning_outs")))
        return {
            "sb": sb,
            "caught_stealing": cs,
            "baserunning_outs": outs,
            "baserunning_runs": round(
                SB_RUN_VALUE * sb + CS_RUN_VALUE * cs
                + BASERUNNING_OUT_VALUE * outs, 2
            ),
        }

    league_bat = {}
    for lg in ("セ", "パ"):
        rows = [p for p in players if _league(p) == lg and number((p.get("batting") or {}).get("pa")) > 0]
        total_pa = sum(number((p.get("batting") or {}).get("pa")) for p in rows)
        total_baserunning = sum(runner_stats(p)["baserunning_runs"] for p in rows)
        league_bat[lg] = {
            "ops": sum(number((p.get("batting") or {}).get("ops")) *
                       number((p.get("batting") or {}).get("pa")) for p in rows) / total_pa
            if total_pa else 0,
            "baserunning": total_baserunning * 100 / total_pa if total_pa else 0,
        }

    batters = []
    for p in players:
        batting = p.get("batting") or {}
        pa = number(batting.get("pa"))
        lg = _league(p)
        if not lg or pa <= 0:
            continue
        role = batter_roles[p.get("key")]
        c = clutch[p.get("key")]
        games = number(batting.get("games"))
        tg = max(team_games.get(p.get("team"), 0), 1)
        required_pa = team_games.get(p.get("team"), 0) * 3.1
        ops_mean = league_bat[lg]["ops"]
        context = context_model["batters"].get(p.get("key"), {
            "park_factor": 1.0, "opponent_factor": 1.0,
            "adjustment": 1.0, "sample": 0.0,
        })
        ops_raw = number(batting.get("ops"))
        ops_neutral = ops_raw * context["adjustment"]
        ops_adj = shrink(ops_neutral, ops_mean, pa, 50)
        volume_ratio = min(pa / max(required_pa, 150), 1)
        game_ratio = min(games / max(tg, 40), 1)
        coverage_ratio = min(context["sample"] / max(pa, 1), 1)
        confidence = _confidence(
            100 * (volume_ratio * 0.70 + game_ratio * 0.20
                   + coverage_ratio * 0.10)
        )

        risp_quality = ((c["risp_hits"] + 0.35 * c["risp_rbi"]) / c["risp_pa"]
                        if c["risp_pa"] else 0)
        late_quality = ((c["late_hits"] + 0.35 * c["late_rbi"]) / c["late_pa"]
                        if c["late_pa"] else 0)
        clutch_raw = shrink(0.6 * risp_quality + 0.4 * late_quality, 0.25,
                            c["risp_pa"] + c["late_pa"], 25)
        runner = runner_stats(p)
        baserunning_net = runner["baserunning_runs"]
        baserunning_rate = baserunning_net * 100 / max(pa, 1)
        # 走塁機会が少ない選手の率をリーグ平均へ戻し、上限張り付きを抑える。
        baserunning_raw = shrink(
            baserunning_rate, league_bat[lg]["baserunning"], pa, 80
        )

        position_apps = dict(role["position_apps"])
        total_pos_apps = sum(position_apps.values())
        defense_difficulty = (
            sum(POSITION_DIFFICULTY[pos] * apps for pos, apps in position_apps.items())
            / total_pos_apps if total_pos_apps else POSITION_DIFFICULTY.get(p.get("position"), 0)
        )
        error_rate = number(batting.get("errors")) * 10 / max(games, 1)
        defense_raw = defense_difficulty - error_rate * 2

        threshold = max(3, round(tg * 0.05))
        qualified_positions = [pos for pos, apps in position_apps.items() if apps >= threshold]
        max_position_apps = max(position_apps.values(), default=0)
        primary_candidates = [
            pos for pos, apps in position_apps.items() if apps == max_position_apps
        ]
        roster_position = p.get("position")
        primary_position = (
            roster_position if roster_position in primary_candidates
            else next((pos for pos in FIELD_POSITIONS if pos in primary_candidates), None)
        )
        groups = {POSITION_GROUP[pos] for pos in qualified_positions}
        versatility_raw = min(
            max(len(qualified_positions) - 1, 0) + max(len(groups) - 1, 0) * 0.5,
            3.0,
        )

        ph_success = role["pinch_hit_on_base"] / max(role["pinch_hit_pa"], 1)
        pr_success = (role["pinch_run_runs"] + role["pinch_run_sb"]) / max(role["pinch_run_apps"], 1)
        role_raw = (
            ph_success * math.sqrt(role["pinch_hit_apps"])
            + pr_success * 0.7 * math.sqrt(role["pinch_run_apps"])
            + role["def_sub_apps"] / tg
        )
        batters.append({
            "player_key": p.get("key"), "player_id": p.get("player_id"),
            "name": p.get("name"), "team": p.get("team"), "league": lg,
            "position": p.get("position"),
            "confidence": confidence,
            "context": context,
            "raw": {
                "batting": ops_adj, "clutch": clutch_raw,
                "baserunning": baserunning_raw, "defense": defense_raw,
                "role": role_raw, "versatility": versatility_raw,
                "availability": games / tg,
            },
            "stats": {
                "games": int(games), "pa": int(pa), "ops": batting.get("ops"),
                "ops_context_adjusted": round(ops_neutral, 3),
                "avg": batting.get("avg"), "obp": batting.get("obp"),
                "slg": batting.get("slg"), "iso": batting.get("iso"),
                "babip": batting.get("babip"), "bb_pct": batting.get("bb_pct"),
                "k_pct": batting.get("k_pct"), "bb_k": batting.get("bb_k"),
                "woba_est": batting.get("woba_est"),
                "wraa_est": batting.get("wraa_est"),
                "wrc_est": batting.get("wrc_est"),
                "wrc_plus_est": batting.get("wrc_plus_est"),
                "rc27": batting.get("rc27"), "xr27": batting.get("xr27"),
                "gpa": batting.get("gpa"), "seca": batting.get("seca"),
                "ta": batting.get("ta"), "bsr_est": batting.get("bsr_est"),
                "qualified_pa": bool(required_pa and pa >= required_pa),
                "required_pa": round(required_pa, 1),
                "caught_stealing": runner["caught_stealing"],
                "baserunning_outs": runner["baserunning_outs"],
                "baserunning_net_runs": round(baserunning_net, 2),
                "hr": int(number(batting.get("hr"))), "rbi": int(number(batting.get("rbi"))),
                "sb": int(number(batting.get("sb"))), "errors": int(number(batting.get("errors"))),
                "starts": role["starts"], "pinch_hit_apps": role["pinch_hit_apps"],
                "pinch_run_apps": role["pinch_run_apps"], "def_sub_apps": role["def_sub_apps"],
                "position_apps": position_apps,
                "primary_position": primary_position,
                "qualified_positions": qualified_positions,
            },
        })

    pitchers = []
    for p in players:
        pitching = p.get("pitching") or {}
        games = int(number(pitching.get("games")))
        lg = _league(p)
        if not lg or games <= 0:
            continue
        tg = max(team_games.get(p.get("team"), 0), 1)
        role_data = pitcher_roles[p.get("key")]
        role_name = _pitcher_role(pitching, role_data)
        outs = number(pitching.get("outs"))
        ip = outs / 3
        required_innings = team_games.get(p.get("team"), 0)
        fip = number(pitching.get("fip"), number(pitching.get("era"), 9))
        era = number(pitching.get("era"), 9)
        k9 = number(pitching.get("k9"))
        quality_sample = ip
        context = context_model["pitchers"].get(p.get("key"), {
            "park_factor": 1.0, "opponent_factor": 1.0,
            "adjustment": 1.0, "sample": 0.0,
        })
        fip_neutral = fip * context["adjustment"]
        era_neutral = era * context["adjustment"]
        pitching_raw = -shrink(fip_neutral, 4.0, quality_sample, 20)
        run_raw = -shrink(era_neutral, 4.0, quality_sample, 20)
        dominance_raw = shrink(k9, 7.5, quality_sample, 20)
        if role_name == "先発":
            role_raw = role_data["qs"] / max(role_data["starts"], 1)
        elif role_name == "抑え":
            role_raw = number(pitching.get("saves")) / max(games, 1) * 2
        else:
            # 公式ホールドと推定ホールドは同じ登板を含み得るため重複加算しない。
            holds = max(number(pitching.get("holds_est")), number(pitching.get("holds")))
            role_raw = (
                role_data["scoreless_relief"] / max(role_data["relief_apps"], 1)
                + holds / max(games, 1)
            )
        coverage_ratio = min(context["sample"] / max(outs, 1), 1)
        if role_name == "先発":
            innings_ratio = min(ip / max(required_innings, 60), 1)
            starts_ratio = min(role_data["starts"] / max(tg / 6, 10), 1)
            confidence_score = 100 * (
                innings_ratio * 0.70 + starts_ratio * 0.20
                + coverage_ratio * 0.10
            )
        else:
            app_ratio = min(games / max(tg * 0.40, 20), 1)
            innings_ratio = min(ip / max(tg * 0.35, 20), 1)
            confidence_score = 100 * (
                app_ratio * 0.55 + innings_ratio * 0.35
                + coverage_ratio * 0.10
            )
        pitchers.append({
            "player_key": p.get("key"), "player_id": p.get("player_id"),
            "name": p.get("name"), "team": p.get("team"), "league": lg,
            "role": role_name,
            "confidence": _confidence(confidence_score),
            "context": context,
            "raw": {
                "pitching": pitching_raw, "dominance": dominance_raw,
                "run_prevention": run_raw, "role": role_raw,
                "availability": games / max(team_games.get(p.get("team"), 1), 1),
            },
            "stats": {
                "games": games, "innings": round(ip, 1), "era": pitching.get("era"),
                "era_context_adjusted": round(era_neutral, 2),
                "qualified_ip": bool(required_innings and ip >= required_innings),
                "required_innings": required_innings,
                "fip": pitching.get("fip"),
                "fip_context_adjusted": round(fip_neutral, 2),
                "k9": pitching.get("k9"),
                "bb9": pitching.get("bb9"), "hr9": pitching.get("hr9"),
                "whip": pitching.get("whip"), "k_bb": pitching.get("k_bb"),
                "k_pct": pitching.get("k_pct"), "bb_pct": pitching.get("bb_pct"),
                "lob_pct_est": pitching.get("lob_pct_est"),
                "wins": int(number(pitching.get("wins"))),
                "saves": int(number(pitching.get("saves"))),
                "holds": int(max(number(pitching.get("holds_est")),
                                 number(pitching.get("holds")))),
                "starts": role_data["starts"], "qs": role_data["qs"],
                "scoreless_relief": role_data["scoreless_relief"],
            },
        })

    for lg in ("セ", "パ"):
        group = [r for r in batters if r["league"] == lg]
        z_by_component = {key: _z_values(group, key) for key in BATTER_WEIGHTS}
        for row in group:
            key = row["player_key"]
            components = {name: _component_rating(z_by_component[name][key])
                          for name in BATTER_WEIGHTS}
            weighted = sum(_weighted_z(z_by_component[name][key]) * weight
                           for name, weight in BATTER_WEIGHTS.items())
            row["components"] = components
            row["w_rating"] = _rating(weighted)
            opportunity = row["stats"]["pa"] / 100 + (
                row["stats"]["pinch_run_apps"] + row["stats"]["def_sub_apps"]
            ) * 0.03
            row["w_value"] = round((row["w_rating"] - 70) / 30 * opportunity, 2)
            del row["raw"]

        for role_name in ("先発", "中継ぎ", "抑え"):
            pgroup = [r for r in pitchers if r["league"] == lg and r["role"] == role_name]
            z_by_component = {key: _z_values(pgroup, key) for key in PITCHER_WEIGHTS}
            for row in pgroup:
                key = row["player_key"]
                row["components"] = {
                    name: _component_rating(z_by_component[name][key])
                    for name in PITCHER_WEIGHTS
                }
                weighted = sum(_weighted_z(z_by_component[name][key]) * weight
                               for name, weight in PITCHER_WEIGHTS.items())
                row["w_rating"] = _rating(weighted)
                opportunity = row["stats"]["innings"] / 30 + row["stats"]["games"] / 25
                row["w_value"] = round((row["w_rating"] - 70) / 30 * opportunity, 2)
                del row["raw"]

    batters.sort(key=lambda x: (-x["w_value"], -x["w_rating"]))
    pitchers.sort(key=lambda x: (-x["w_value"], -x["w_rating"]))
    combined = {}
    for kind, rows in (("batter", batters), ("pitcher", pitchers)):
        for row in rows:
            item = combined.setdefault(row["player_key"], {
                "player_key": row["player_key"], "player_id": row["player_id"],
                "name": row["name"], "team": row["team"], "league": row["league"],
                "batter_w_value": 0.0, "pitcher_w_value": 0.0,
                "batter_w_rating": None, "pitcher_w_rating": None,
                "batting_games": 0, "pitching_games": 0,
                "qualified_pa": False, "qualified_ip": False,
                "batter_confidence": None, "pitcher_confidence": None,
                "batter_context": None, "pitcher_context": None,
            })
            item[f"{kind}_w_value"] = row["w_value"]
            item[f"{kind}_w_rating"] = row["w_rating"]
            item[f"{kind}_confidence"] = row.get("confidence")
            item[f"{kind}_context"] = row.get("context")
            if kind == "batter":
                item["batting_games"] = row["stats"]["games"]
                item["qualified_pa"] = row["stats"]["qualified_pa"]
            else:
                item["pitching_games"] = row["stats"]["games"]
                item["qualified_ip"] = row["stats"]["qualified_ip"]
    overall = list(combined.values())
    for row in overall:
        row["w_value"] = round(row["batter_w_value"] + row["pitcher_w_value"], 2)
        rating_values = (
            (row["batter_w_rating"], abs(row["batter_w_value"])),
            (row["pitcher_w_rating"], abs(row["pitcher_w_value"])),
        )
        rating_values = [(rating, max(weight, 0.01)) for rating, weight in rating_values
                         if rating is not None]
        total_weight = sum(weight for _, weight in rating_values)
        row["w_rating"] = (
            round(sum(rating * weight for rating, weight in rating_values) / total_weight, 1)
            if total_weight else None
        )
        confidence_values = (
            (row.get("batter_confidence"), abs(row["batter_w_value"])),
            (row.get("pitcher_confidence"), abs(row["pitcher_w_value"])),
        )
        confidence_values = [
            (value, max(weight, 0.01)) for value, weight in confidence_values
            if value is not None
        ]
        confidence_weight = sum(weight for _, weight in confidence_values)
        confidence_score = (
            sum(value["score"] * weight for value, weight in confidence_values)
            / confidence_weight if confidence_weight else 0
        )
        row["confidence"] = _confidence(confidence_score)
        context_values = (
            (row.get("batter_context"), abs(row["batter_w_value"])),
            (row.get("pitcher_context"), abs(row["pitcher_w_value"])),
        )
        context_values = [
            (value, max(weight, 0.01)) for value, weight in context_values
            if value is not None
        ]
        context_weight = sum(weight for _, weight in context_values)
        if context_weight:
            row["context"] = {
                field: round(sum(value[field] * weight for value, weight in context_values)
                             / context_weight, 3)
                for field in ("park_factor", "opponent_factor", "adjustment")
            }
    overall.sort(key=lambda x: (-x["w_value"], -(x["w_rating"] or 0)))

    return {
        "batters": batters, "pitchers": pitchers, "overall": overall,
        "runner_event_diagnostics": runner_diag,
        "context_adjustment": {
            "method": context_model["method"],
            "park_factors": context_model["park_factors"],
            "note": (
                "球場得点係数と対戦相手の攻守強度をシーズン実績から算出し、"
                "少標本はリーグ平均へ縮小。補正倍率は0.90〜1.10に制限"
            ),
        },
    }
