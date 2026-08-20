"""選手別のシーズン対戦成績JSONを生成する。

入力:
    data/{season}/dataset/atbats.csv

出力:
    data/{season}/matchups/index.json
    data/{season}/matchups/batters/{player_key}.json
    data/{season}/matchups/pitchers/{player_key}.json
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sys


COUNT_FIELDS = (
    "pa", "ab", "hit", "single", "double", "triple", "hr", "bb", "ibb",
    "hbp", "so", "sf", "sh", "gidp", "error", "rbi", "sb", "cs",
)

# 選手別JSON内の回別分析用イベント。
# [game, inning, opponent_hand, pa, ab, hit, single, double, triple, hr,
#  bb, hbp, so, sf, sh, gidp, error, rbi, pitches, recorded_outs]
INNING_EVENT_FIELDS = (
    "pa", "ab", "hit", "single", "double", "triple", "hr", "bb",
    "hbp", "so", "sf", "sh", "gidp", "error", "rbi", "pitches",
)


def _number(value):
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _rate(numerator, denominator):
    return round(numerator / denominator, 4) if denominator else None


def _hand_code(value):
    value = str(value or "")
    if "右" in value:
        return 1
    if "左" in value:
        return 2
    return 0


def _is_home(row, kind):
    team = row.get("batting_team" if kind == "batter" else "fielding_team")
    return bool(team and team == row.get("home"))


def _record_game(player, row, kind):
    game_id = row.get("game_id") or f"{row.get('date') or '-'}-{row.get('home') or '-'}"
    if game_id not in player["_game_index"]:
        player["_game_index"][game_id] = len(player["games"])
        player["games"].append({
            "id": game_id,
            "date": row.get("date") or "",
            "opponent": row.get("fielding_team" if kind == "batter" else "batting_team") or "-",
            "is_home": _is_home(row, kind),
            "stadium": row.get("stadium") or "-",
        })
    return player["_game_index"][game_id]


def _inning_event(row, game_index, kind, recorded_outs):
    opponent_hand = row.get("pit_hand" if kind == "batter" else "bat_hand")
    return [
        game_index,
        _number(row.get("inning")),
        _hand_code(opponent_hand),
        *[_number(row.get(field)) for field in INNING_EVENT_FIELDS],
        recorded_outs,
    ]


def _filename(key):
    value = str(key or "")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    if safe and len(safe) <= 80:
        return safe + ".json"
    return hashlib.sha1(value.encode("utf-8")).hexdigest() + ".json"


def _new_player(row, kind):
    prefix = "batter" if kind == "batter" else "pitcher"
    team_field = "batting_team" if kind == "batter" else "fielding_team"
    hand_field = "bat_hand" if kind == "batter" else "pit_hand"
    return {
        "key": row.get(prefix + "_key"),
        "player_id": row.get(prefix + "_id") or None,
        "name": row.get(prefix) or "-",
        "team": row.get(team_field) or "-",
        "hand": row.get(hand_field) or "-",
    }


def _new_opponent(row, kind):
    prefix = "pitcher" if kind == "batter" else "batter"
    team_field = "fielding_team" if kind == "batter" else "batting_team"
    hand_field = "pit_hand" if kind == "batter" else "bat_hand"
    item = {
        "player_key": row.get(prefix + "_key"),
        "player_id": row.get(prefix + "_id") or None,
        "name": row.get(prefix) or "-",
        "team": row.get(team_field) or "-",
        "hand": row.get(hand_field) or "-",
        "_games": set(),
    }
    for field in COUNT_FIELDS:
        item[field] = 0
    return item


def _finish_opponent(item):
    result = {key: value for key, value in item.items() if key != "_games"}
    result["games"] = len(item["_games"])
    hits = result["hit"]
    total_bases = result["single"] + result["double"] * 2 + result["triple"] * 3 + result["hr"] * 4
    obp_denominator = result["ab"] + result["bb"] + result["hbp"] + result["sf"]
    bip_denominator = result["ab"] - result["so"] - result["hr"] + result["sf"]
    result["hits"] = hits
    del result["hit"]
    result["tb"] = total_bases
    result["avg"] = _rate(hits, result["ab"])
    result["obp"] = _rate(hits + result["bb"] + result["hbp"], obp_denominator)
    result["slg"] = _rate(total_bases, result["ab"])
    result["ops"] = round(result["obp"] + result["slg"], 4) if result["obp"] is not None and result["slg"] is not None else None
    result["babip"] = _rate(hits - result["hr"], bip_denominator)
    result["bb_pct"] = _rate(result["bb"], result["pa"])
    result["k_pct"] = _rate(result["so"], result["pa"])
    return result


def aggregate(rows):
    buckets = {"batter": {}, "pitcher": {}}
    latest_date = None
    half_outs = {}
    for row in rows:
        date = row.get("date")
        if date and (latest_date is None or date > latest_date):
            latest_date = date
        half_key = (row.get("game_id"), row.get("inning"), row.get("top_bottom"))
        reported_outs = max(0, min(3, _number(row.get("outs"))))
        previous_outs = half_outs.get(half_key, 0)
        recorded_outs = max(0, reported_outs - previous_outs)
        half_outs[half_key] = reported_outs
        for kind in ("batter", "pitcher"):
            owner_prefix = "batter" if kind == "batter" else "pitcher"
            opponent_prefix = "pitcher" if kind == "batter" else "batter"
            owner_key = row.get(owner_prefix + "_key")
            opponent_key = row.get(opponent_prefix + "_key")
            if not owner_key or not opponent_key:
                continue
            player = buckets[kind].setdefault(owner_key, {
                "player": _new_player(row, kind),
                "opponents": {},
                "games": [],
                "events": [],
                "_game_index": {},
            })
            player["player"] = _new_player(row, kind)
            game_index = _record_game(player, row, kind)
            player["events"].append(_inning_event(row, game_index, kind, recorded_outs))
            opponent = player["opponents"].setdefault(opponent_key, _new_opponent(row, kind))
            opponent["name"] = row.get(opponent_prefix) or opponent["name"]
            opponent["team"] = row.get("fielding_team" if kind == "batter" else "batting_team") or opponent["team"]
            opponent["hand"] = row.get("pit_hand" if kind == "batter" else "bat_hand") or opponent["hand"]
            opponent["_games"].add(row.get("game_id"))
            for field in COUNT_FIELDS:
                opponent[field] += _number(row.get(field))
    return buckets, latest_date


def add_baserunning_events(buckets, atbats, runner_events):
    """打席へ正確に結び付く盗塁・盗塁死だけを対戦別に加える。"""
    contexts = {
        (row.get("game_id"), row.get("atbat_index")): row
        for row in atbats
        if row.get("game_id") and row.get("atbat_index")
    }
    added = 0
    for event in runner_events:
        event_type = event.get("event_type")
        if event_type not in ("stolen_base", "caught_stealing"):
            continue
        # official_boxscore 行は投手・イニングを持たないため対戦別には使わない。
        if event.get("source") != "result_detail_high_confidence":
            continue
        context = contexts.get((event.get("game_id"), event.get("event_sequence")))
        runner_key = event.get("player_key")
        pitcher_key = context and context.get("pitcher_key")
        if not runner_key or not pitcher_key:
            continue
        field = "sb" if event_type == "stolen_base" else "cs"
        batter_bucket = buckets["batter"].get(runner_key)
        pitcher_bucket = buckets["pitcher"].get(pitcher_key)
        batter_matchup = batter_bucket and batter_bucket["opponents"].get(pitcher_key)
        pitcher_matchup = pitcher_bucket and pitcher_bucket["opponents"].get(runner_key)
        if batter_matchup is not None:
            batter_matchup[field] += 1
        if pitcher_matchup is not None:
            pitcher_matchup[field] += 1
        if batter_matchup is not None or pitcher_matchup is not None:
            added += 1
    return added


def _clear_json_files(directory):
    os.makedirs(directory, exist_ok=True)
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        if name.endswith(".json") and os.path.isfile(path):
            os.remove(path)


def write_matchups(season, buckets, latest_date, base="data"):
    root = os.path.join(base, str(season), "matchups")
    index = {"season": str(season), "updated_through": latest_date, "batters": [], "pitchers": []}
    for kind, directory_name, index_name in (
        ("batter", "batters", "batters"),
        ("pitcher", "pitchers", "pitchers"),
    ):
        directory = os.path.join(root, directory_name)
        _clear_json_files(directory)
        for key, value in sorted(buckets[kind].items()):
            opponents = [_finish_opponent(item) for item in value["opponents"].values()]
            opponents.sort(key=lambda item: (-item["pa"], item["name"]))
            filename = _filename(key)
            payload = {
                "season": str(season),
                "updated_through": latest_date,
                "kind": kind,
                "player": value["player"],
                "opponents": opponents,
                "games": value["games"],
                "inning_events": value["events"],
            }
            with open(os.path.join(directory, filename), "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            index[index_name].append({
                **value["player"],
                "file": f"{directory_name}/{filename}",
                "opponents": len(opponents),
                "pa": sum(item["pa"] for item in opponents),
            })
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "index.json"), "w", encoding="utf-8") as handle:
        json.dump(index, handle, ensure_ascii=False, indent=2)
    return index


def build(season, base="data"):
    source = os.path.join(base, str(season), "dataset", "atbats.csv")
    if not os.path.exists(source):
        raise FileNotFoundError(f"打席データがありません: {source}")
    with open(source, encoding="utf-8-sig", newline="") as handle:
        atbats = list(csv.DictReader(handle))
    buckets, latest_date = aggregate(atbats)
    runner_source = os.path.join(base, str(season), "dataset", "runner_events.csv")
    baserunning_events = 0
    if os.path.exists(runner_source):
        with open(runner_source, encoding="utf-8-sig", newline="") as handle:
            baserunning_events = add_baserunning_events(buckets, atbats, csv.DictReader(handle))
    index = write_matchups(season, buckets, latest_date, base)
    print(
        f"[INFO] matchups: 打者{len(index['batters']):,}人 / "
        f"投手{len(index['pitchers']):,}人 / 走塁{baserunning_events:,}件 / "
        f"{latest_date or '-'}時点"
    )
    return index


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", required=True)
    parser.add_argument("--base", default="data")
    args = parser.parse_args()
    build(args.season, args.base)
    return 0


if __name__ == "__main__":
    sys.exit(main())
