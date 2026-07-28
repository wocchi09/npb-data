"""W-Impact / W-Rating calculation.

This is a transparent site-original contribution index, not WAR or UZR.
Only recorded events are scored. Missing defensive tracking data is never
estimated.
"""

from __future__ import annotations

import math
from collections import defaultdict

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
        r["player_key"]: max(-3.0, min(3.0, (number(r["raw"].get(key)) - mean) / sd))
        if sd > 1e-9 else 0.0
        for r in rows
    }


def _rating(weighted_z):
    return round(max(40.0, min(180.0, 100 + 15 * weighted_z)), 1)


def _component_rating(z):
    return round(max(40.0, min(160.0, 100 + 15 * z)), 1)


def _league(player):
    lg = team_info(player.get("team")).get("league")
    return lg if lg in ("セ", "パ") else None


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


def calculate(players, teams, batting_lines, pitching_lines, atbats):
    team_games = {t.get("team"): int(number(t.get("games"))) for t in teams}
    batter_roles = collect_batter_roles(batting_lines)
    pitcher_roles = collect_pitcher_roles(pitching_lines)
    clutch = collect_clutch(atbats)

    league_bat = {}
    for lg in ("セ", "パ"):
        rows = [p for p in players if _league(p) == lg and number((p.get("batting") or {}).get("pa")) > 0]
        total_pa = sum(number((p.get("batting") or {}).get("pa")) for p in rows)
        league_bat[lg] = {
            "ops": sum(number((p.get("batting") or {}).get("ops")) *
                       number((p.get("batting") or {}).get("pa")) for p in rows) / total_pa
            if total_pa else 0,
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
        ops_adj = shrink(number(batting.get("ops")), ops_mean, pa, 50)

        risp_quality = ((c["risp_hits"] + 0.35 * c["risp_rbi"]) / c["risp_pa"]
                        if c["risp_pa"] else 0)
        late_quality = ((c["late_hits"] + 0.35 * c["late_rbi"]) / c["late_pa"]
                        if c["late_pa"] else 0)
        clutch_raw = shrink(0.6 * risp_quality + 0.4 * late_quality, 0.25,
                            c["risp_pa"] + c["late_pa"], 25)
        baserunning_raw = number(batting.get("sb")) * 100 / max(pa, 1)

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
            "raw": {
                "batting": ops_adj, "clutch": clutch_raw,
                "baserunning": baserunning_raw, "defense": defense_raw,
                "role": role_raw, "versatility": versatility_raw,
                "availability": games / tg,
            },
            "stats": {
                "games": int(games), "pa": int(pa), "ops": batting.get("ops"),
                "qualified_pa": bool(required_pa and pa >= required_pa),
                "required_pa": round(required_pa, 1),
                "hr": int(number(batting.get("hr"))), "rbi": int(number(batting.get("rbi"))),
                "sb": int(number(batting.get("sb"))), "errors": int(number(batting.get("errors"))),
                "starts": role["starts"], "pinch_hit_apps": role["pinch_hit_apps"],
                "pinch_run_apps": role["pinch_run_apps"], "def_sub_apps": role["def_sub_apps"],
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
        role_data = pitcher_roles[p.get("key")]
        role_name = _pitcher_role(pitching, role_data)
        outs = number(pitching.get("outs"))
        ip = outs / 3
        required_innings = team_games.get(p.get("team"), 0)
        fip = number(pitching.get("fip"), number(pitching.get("era"), 9))
        era = number(pitching.get("era"), 9)
        k9 = number(pitching.get("k9"))
        quality_sample = ip
        pitching_raw = -shrink(fip, 4.0, quality_sample, 20)
        run_raw = -shrink(era, 4.0, quality_sample, 20)
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
        pitchers.append({
            "player_key": p.get("key"), "player_id": p.get("player_id"),
            "name": p.get("name"), "team": p.get("team"), "league": lg,
            "role": role_name,
            "raw": {
                "pitching": pitching_raw, "dominance": dominance_raw,
                "run_prevention": run_raw, "role": role_raw,
                "availability": games / max(team_games.get(p.get("team"), 1), 1),
            },
            "stats": {
                "games": games, "innings": round(ip, 1), "era": pitching.get("era"),
                "qualified_ip": bool(required_innings and ip >= required_innings),
                "required_innings": required_innings,
                "fip": pitching.get("fip"), "k9": pitching.get("k9"),
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
            weighted = sum(z_by_component[name][key] * weight
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
                weighted = sum(z_by_component[name][key] * weight
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
                "qualified_pa": False, "qualified_ip": False,
            })
            item[f"{kind}_w_value"] = row["w_value"]
            item[f"{kind}_w_rating"] = row["w_rating"]
            if kind == "batter":
                item["qualified_pa"] = row["stats"]["qualified_pa"]
            else:
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
    overall.sort(key=lambda x: (-x["w_value"], -(x["w_rating"] or 0)))

    return {"batters": batters, "pitchers": pitchers, "overall": overall}
