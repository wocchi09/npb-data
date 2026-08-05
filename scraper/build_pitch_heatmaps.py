"""投手別の選択式コースヒートマップJSONを生成する。

入力:
    data/{season}/dataset/pitches.csv

出力:
    data/{season}/pitch_heatmaps/index.json
    data/{season}/pitch_heatmaps/pitchers/{player_key}.json

各投球は [zone, pitch_type, batter_hand, swing, miss] の5要素へ圧縮する。
zone は上から行優先の 0〜24、左右は 0=不明 / 1=右 / 2=左。
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sys


def _filename(key):
    value = str(key or "")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    if safe and len(safe) <= 80:
        return safe + ".json"
    return hashlib.sha1(value.encode("utf-8")).hexdigest() + ".json"


def _truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _hand_code(value):
    value = str(value or "")
    if "右" in value:
        return 1
    if "左" in value:
        return 2
    return 0


def _zone(row):
    try:
        grid_row = int(row.get("zone_row", ""))
        grid_col = int(row.get("zone_col", ""))
    except (TypeError, ValueError):
        return None
    if not (0 <= grid_row < 5 and 0 <= grid_col < 5):
        return None
    return grid_row * 5 + grid_col


def aggregate(rows):
    pitchers = {}
    latest_date = None
    for row in rows:
        zone = _zone(row)
        key = row.get("pitcher_key")
        if not key or zone is None:
            continue
        date = row.get("date") or ""
        if date and (latest_date is None or date > latest_date):
            latest_date = date
        pitcher = pitchers.setdefault(key, {
            "player": {
                "key": key,
                "player_id": row.get("pitcher_id") or None,
                "name": row.get("pitcher") or "-",
                "team": row.get("fielding_team") or "-",
                "hand": row.get("pit_hand") or "-",
            },
            "pitch_types": [],
            "_pitch_type_index": {},
            "games": {},
        })
        player = pitcher["player"]
        player.update({
            "player_id": row.get("pitcher_id") or player["player_id"],
            "name": row.get("pitcher") or player["name"],
            "team": row.get("fielding_team") or player["team"],
            "hand": row.get("pit_hand") or player["hand"],
        })
        pitch_type = row.get("pitch_type") or "不明"
        if pitch_type not in pitcher["_pitch_type_index"]:
            pitcher["_pitch_type_index"][pitch_type] = len(pitcher["pitch_types"])
            pitcher["pitch_types"].append(pitch_type)
        type_index = pitcher["_pitch_type_index"][pitch_type]
        game_id = row.get("game_id") or f"{date}-{row.get('batting_team') or '-'}"
        game = pitcher["games"].setdefault(game_id, {
            "id": game_id,
            "date": date,
            "opponent": row.get("batting_team") or "-",
            "p": [],
        })
        game["p"].append([
            zone,
            type_index,
            _hand_code(row.get("bat_hand")),
            1 if _truthy(row.get("is_swing")) else 0,
            1 if _truthy(row.get("is_miss")) else 0,
        ])
    return pitchers, latest_date


def _clear_json_files(directory):
    os.makedirs(directory, exist_ok=True)
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        if name.endswith(".json") and os.path.isfile(path):
            os.remove(path)


def write_heatmaps(season, pitchers, latest_date, base="data"):
    root = os.path.join(base, str(season), "pitch_heatmaps")
    directory = os.path.join(root, "pitchers")
    _clear_json_files(directory)
    index = {"season": str(season), "updated_through": latest_date, "pitchers": []}
    for key, value in sorted(pitchers.items()):
        games = sorted(value["games"].values(), key=lambda game: (game["date"], game["id"]))
        filename = _filename(key)
        payload = {
            "season": str(season),
            "updated_through": latest_date,
            "player": value["player"],
            "pitch_types": value["pitch_types"],
            "games": games,
        }
        with open(os.path.join(directory, filename), "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        pitch_count = sum(len(game["p"]) for game in games)
        index["pitchers"].append({
            **value["player"],
            "file": f"pitchers/{filename}",
            "games": len(games),
            "pitches": pitch_count,
        })
    os.makedirs(root, exist_ok=True)
    with open(os.path.join(root, "index.json"), "w", encoding="utf-8") as handle:
        json.dump(index, handle, ensure_ascii=False, indent=2)
    return index


def build(season, base="data"):
    source = os.path.join(base, str(season), "dataset", "pitches.csv")
    if not os.path.exists(source):
        raise FileNotFoundError(f"投球データがありません: {source}")
    with open(source, encoding="utf-8-sig", newline="") as handle:
        pitchers, latest_date = aggregate(csv.DictReader(handle))
    index = write_heatmaps(season, pitchers, latest_date, base)
    pitch_count = sum(item["pitches"] for item in index["pitchers"])
    print(
        f"[INFO] pitch heatmaps: 投手{len(index['pitchers']):,}人 / "
        f"コース付き投球{pitch_count:,}球 / {latest_date or '-'}時点"
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
