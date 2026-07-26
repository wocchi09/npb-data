"""
分析用データセット生成（1行=1球のロング形式）
================================================
保存済みの試合JSONから、分析ツール（pandas / DuckDB / Power BI）が
そのまま読める平坦なテーブルを生成する。

集計済みJSONではなく「このCSVを唯一の正」として扱えるようにするのが目的。
新しい分析軸が欲しくなっても、集計スクリプトを書き換えずに
groupby だけで対応できる。

使い方:
    python scraper/build_dataset.py --season 2026
    python scraper/build_dataset.py --season 2026 --format both

出力（data/{season}/dataset/ 配下）:
    pitches.csv         1行=1球（全部入り。これがメイン）
    atbats.csv          1行=1打席
    batting_lines.csv   1行=1選手1試合（公式打撃成績）
    pitching_lines.csv  1行=1投手1試合（公式投手成績・先発フラグ付き）
    games.csv           1行=1試合
"""

import argparse
import csv
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.normalize import normalize_team, team_info, player_key, clean_name
from lib.events import classify_result, classify_pitch, count_before


# ---------- 入出力 ----------

def find_games(season, base="data"):
    """その年の試合JSONを集める（集計ファイルや出力先は除外）"""
    out = []
    for p in glob.glob(f"{base}/{season}/**/*.json", recursive=True):
        norm = p.replace("\\", "/")
        name = os.path.basename(norm)
        if name.startswith("_") or name == "index.json":
            continue
        if "/players/" in norm or "/teams/" in norm or "/dataset/" in norm:
            continue
        out.append(norm)
    return sorted(out)


def date_from_path(path):
    m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", path.replace("\\", "/"))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def write_table(rows, cols, out_dir, name, fmt):
    """CSV（と可能ならParquet）を書き出す"""
    os.makedirs(out_dir, exist_ok=True)
    written = []

    if fmt in ("csv", "both"):
        path = os.path.join(out_dir, name + ".csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        written.append(path)

    if fmt in ("parquet", "both"):
        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
            table = pa.Table.from_pylist(
                [{c: r.get(c) for c in cols} for r in rows]
            )
            path = os.path.join(out_dir, name + ".parquet")
            pq.write_table(table, path, compression="snappy")
            written.append(path)
        except ImportError:
            print("[INFO] pyarrow が未インストールのため Parquet はスキップ（CSVのみ出力）")

    return written


# ---------- 列定義 ----------

PITCH_COLS = [
    "date", "game_id", "home", "away", "stadium", "stadium_side",
    "inning", "top_bottom", "half", "batting_team", "fielding_team",
    "atbat_index", "atbat_no",
    "batter", "batter_id", "batter_key", "bat_hand",
    "pitcher", "pitcher_id", "pitcher_key", "pit_hand",
    "outs", "r1", "r2", "r3", "runners_code", "risp",
    "pitch_no", "balls_before", "strikes_before", "count_before",
    "pitch_type", "speed_kmh",
    "zone_row", "zone_col", "zone_label", "in_zone",
    "pitch_result", "pitch_kind",
    "is_swing", "is_miss", "is_called", "is_foul", "is_ball", "is_inplay",
    "is_last_pitch",
    "ab_result", "ab_out_type", "ab_hit", "ab_rbi",
]

ATBAT_COLS = [
    "date", "game_id", "home", "away", "stadium",
    "inning", "top_bottom", "half", "batting_team", "fielding_team",
    "atbat_index", "atbat_no",
    "batter", "batter_id", "batter_key", "bat_hand",
    "pitcher", "pitcher_id", "pitcher_key", "pit_hand",
    "outs", "r1", "r2", "r3", "risp",
    "pitches", "result", "out_type", "direction",
    "pa", "ab", "hit", "single", "double", "triple", "hr",
    "bb", "hbp", "so", "sf", "sh", "gidp", "error", "rbi",
]

BAT_LINE_COLS = [
    "date", "game_id", "team", "opponent", "is_home",
    "player", "player_id", "player_key",
    "order", "position", "is_starter", "sub_type",
    "season_avg", "ab", "runs", "hits", "rbi", "so", "bb", "hbp",
    "sac", "sb", "errors", "hr",
]

PIT_LINE_COLS = [
    "date", "game_id", "team", "opponent", "is_home",
    "player", "player_id", "player_key", "decision", "is_starter",
    "season_era", "innings", "outs", "pitches", "batters_faced",
    "hits_allowed", "hr_allowed", "so", "bb", "hbp", "balk",
    "runs_allowed", "earned_runs", "is_qs",
]

GAME_COLS = [
    "date", "game_id", "home", "away", "stadium", "home_score", "away_score",
    "winner", "state", "win_pitcher", "lose_pitcher", "save_pitcher",
    "atbat_count", "pitch_count",
]


# ---------- 変換 ----------

def build(season, base="data", fmt="both"):
    files = find_games(season, base)
    print(f"[INFO] {season}シーズン: {len(files)}試合を読み込み")

    pitches, atbats, bat_lines, pit_lines, games = [], [], [], [], []

    for path in files:
        try:
            with open(path, encoding="utf-8") as f:
                g = json.load(f)
        except Exception as e:
            print(f"[WARN] 読み込み失敗 {path}: {e}")
            continue

        date = date_from_path(path)
        gid = g.get("game_id")
        home = normalize_team(g.get("home"))
        away = normalize_team(g.get("away"))
        res = g.get("result") or {}

        # ---- games ----
        hs, as_ = res.get("home_score"), res.get("away_score")
        winner = None
        if hs is not None and as_ is not None:
            winner = home if hs > as_ else (away if as_ > hs else "引分")
        games.append({
            "date": date, "game_id": gid, "home": home, "away": away,
            "stadium": g.get("stadium"),
            "home_score": hs, "away_score": as_, "winner": winner,
            "state": res.get("state"),
            "win_pitcher": res.get("win_pitcher"),
            "lose_pitcher": res.get("lose_pitcher"),
            "save_pitcher": res.get("save_pitcher"),
            "atbat_count": g.get("atbat_count"),
            "pitch_count": g.get("pitch_count"),
        })

        # ---- 公式ボックススコア ----
        box = g.get("boxscore") or {}
        side_team = {"away": away, "home": home}
        for side in ("away", "home"):
            team = side_team[side]
            opp = side_team["home" if side == "away" else "away"]

            for row in (box.get("batting", {}) or {}).get(side, []) or []:
                bat_lines.append({
                    "date": date, "game_id": gid, "team": team,
                    "opponent": opp, "is_home": side == "home",
                    "player": clean_name(row.get("name")),
                    "player_id": row.get("player_id"),
                    "player_key": player_key(row.get("player_id"), row.get("name")),
                    "order": row.get("order"),
                    "position": row.get("position"),
                    "is_starter": row.get("is_starter"),
                    "sub_type": row.get("sub_type"),
                    "season_avg": row.get("season_avg"),
                    "ab": row.get("ab"), "runs": row.get("runs"),
                    "hits": row.get("hits"), "rbi": row.get("rbi"),
                    "so": row.get("so"), "bb": row.get("bb"),
                    "hbp": row.get("hbp"), "sac": row.get("sac"),
                    "sb": row.get("sb"), "errors": row.get("errors"),
                    "hr": row.get("hr"),
                })

            plist = (box.get("pitching", {}) or {}).get(side, []) or []
            for i, row in enumerate(plist):
                outs = row.get("outs") or 0
                er = row.get("earned_runs") or 0
                # クオリティスタート＝先発で6回以上・自責3以下
                is_starter = (i == 0)
                pit_lines.append({
                    "date": date, "game_id": gid, "team": team,
                    "opponent": opp, "is_home": side == "home",
                    "player": clean_name(row.get("name")),
                    "player_id": row.get("player_id"),
                    "player_key": player_key(row.get("player_id"), row.get("name")),
                    "decision": row.get("decision"),
                    "is_starter": is_starter,
                    "season_era": row.get("season_era"),
                    "innings": row.get("innings"), "outs": outs,
                    "pitches": row.get("pitches"),
                    "batters_faced": row.get("batters_faced"),
                    "hits_allowed": row.get("hits_allowed"),
                    "hr_allowed": row.get("hr_allowed"),
                    "so": row.get("so"), "bb": row.get("bb"),
                    "hbp": row.get("hbp"), "balk": row.get("balk"),
                    "runs_allowed": row.get("runs_allowed"),
                    "earned_runs": er,
                    "is_qs": bool(is_starter and outs >= 18 and er <= 3),
                })

        # ---- 打席・投球 ----
        for ab_no, ab in enumerate(g.get("atbats", []), start=1):
            if not ab.get("valid", True):
                continue
            b = ab.get("batter") or {}
            p = ab.get("pitcher") or {}
            r = ab.get("runners") or {}
            cnt = ab.get("count") or {}
            rs = ab.get("result_summary")
            ev = classify_result(rs)

            bteam = normalize_team(ab.get("batting_team"))
            fteam = normalize_team(ab.get("fielding_team"))
            tb = ab.get("top_bottom")
            r1, r2, r3 = bool(r.get("first")), bool(r.get("second")), bool(r.get("third"))

            common = {
                "date": date, "game_id": gid, "home": home, "away": away,
                "stadium": g.get("stadium"),
                "inning": ab.get("inning"), "top_bottom": tb,
                "half": f"{ab.get('inning')}{tb}",
                "batting_team": bteam, "fielding_team": fteam,
                "atbat_index": ab.get("index"), "atbat_no": ab_no,
                "batter": clean_name(b.get("name")), "batter_id": b.get("player_id"),
                "batter_key": player_key(b.get("player_id"), b.get("name")),
                "bat_hand": b.get("hand"),
                "pitcher": clean_name(p.get("name")), "pitcher_id": p.get("player_id"),
                "pitcher_key": player_key(p.get("player_id"), p.get("name")),
                "pit_hand": p.get("hand"),
                "outs": cnt.get("out"),
                "r1": r1, "r2": r2, "r3": r3,
                "risp": r2 or r3,          # 得点圏
            }

            plist = ab.get("pitches") or []
            atbats.append({
                **common,
                "runners_code": r.get("code"),
                "pitches": len(plist),
                "result": rs, "out_type": ev["out_type"],
                "direction": ev["direction"],
                "pa": ev["pa"], "ab": ev["ab"], "hit": ev["hit"],
                "single": ev["single"], "double": ev["double"],
                "triple": ev["triple"], "hr": ev["hr"],
                "bb": ev["bb"], "hbp": ev["hbp"], "so": ev["so"],
                "sf": ev["sf"], "sh": ev["sh"], "gidp": ev["gidp"],
                "error": ev["error"], "rbi": ev["rbi"],
            })

            for i, pt in enumerate(plist):
                bb_, ss_ = count_before(plist, i)
                pc = classify_pitch(pt.get("result"), pt.get("kind"))
                c = pt.get("course") or {}
                gr, gc = c.get("grid_row"), c.get("grid_col")
                # 5×5の中央3×3をストライクゾーンとみなす
                in_zone = None
                if gr is not None and gc is not None:
                    in_zone = (1 <= gr <= 3) and (1 <= gc <= 3)

                pitches.append({
                    **common,
                    "runners_code": r.get("code"),
                    "stadium_side": "home" if bteam == home else "away",
                    "pitch_no": pt.get("no", i + 1),
                    "balls_before": bb_, "strikes_before": ss_,
                    "count_before": f"{bb_}-{ss_}",
                    "pitch_type": pt.get("type"),
                    "speed_kmh": pt.get("speed_kmh"),
                    "zone_row": gr, "zone_col": gc,
                    "zone_label": c.get("label"), "in_zone": in_zone,
                    "pitch_result": pt.get("result"), "pitch_kind": pt.get("kind"),
                    "is_swing": pc["is_swing"], "is_miss": pc["is_miss"],
                    "is_called": pc["is_called"], "is_foul": pc["is_foul"],
                    "is_ball": pc["is_ball"], "is_inplay": pc["is_inplay"],
                    "is_last_pitch": i == len(plist) - 1,
                    "ab_result": rs, "ab_out_type": ev["out_type"],
                    "ab_hit": ev["hit"], "ab_rbi": ev["rbi"],
                })

    out_dir = os.path.join(base, str(season), "dataset")
    tables = [
        (pitches, PITCH_COLS, "pitches"),
        (atbats, ATBAT_COLS, "atbats"),
        (bat_lines, BAT_LINE_COLS, "batting_lines"),
        (pit_lines, PIT_LINE_COLS, "pitching_lines"),
        (games, GAME_COLS, "games"),
    ]
    for rows, cols, name in tables:
        paths = write_table(rows, cols, out_dir, name, fmt)
        print(f"[INFO] {name}: {len(rows):,}行 → {', '.join(os.path.basename(p) for p in paths)}")

    return {"pitches": len(pitches), "atbats": len(atbats), "games": len(games)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default=None)
    ap.add_argument("--date", default=None, help="この日を含むシーズンを対象にする")
    ap.add_argument("--base", default="data")
    ap.add_argument("--format", default="both", choices=["csv", "parquet", "both"])
    args = ap.parse_args()

    season = args.season or (args.date.split("-")[0] if args.date else None)
    if not season:
        print("[ERROR] --season または --date を指定してください")
        return 1

    build(season, args.base, args.format)
    return 0


if __name__ == "__main__":
    sys.exit(main())
