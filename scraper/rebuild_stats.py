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


def rebuild_index(base="data"):
    """
    data/index.json を実ファイルから作り直す。

    収集時の追記だけだと、再収集で消えたファイルのパスが残り続け、
    サイト側の試合数が実際より多く表示されてしまう。
    ここで毎回「実在するファイルだけ」の一覧に作り直す。
    """
    files = []
    for p in glob.glob(f"{base}/**/*.json", recursive=True):
        norm = p.replace("\\", "/")
        # data/YYYY/MM/DD/*.json だけを対象にする
        if not re.search(r"/\d{4}/\d{2}/\d{2}/[^/]+\.json$", norm):
            continue
        # サイト側は "data/..." の相対パスで読むので、その形に揃える
        m = re.search(r"(data/\d{4}/\d{2}/\d{2}/[^/]+\.json)$", norm)
        files.append(m.group(1) if m else norm)
    files = sorted(set(files))

    index_path = os.path.join(base, "index.json")
    old_n = 0
    if os.path.exists(index_path):
        try:
            with open(index_path, encoding="utf-8") as f:
                old_n = len(json.load(f).get("files", []))
        except Exception:
            old_n = 0

    from datetime import datetime, timedelta, timezone
    jst = timezone(timedelta(hours=9))
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump({"updated_at": datetime.now(jst).isoformat(), "files": files},
                  f, ensure_ascii=False, indent=2)

    games = len([x for x in files if not os.path.basename(x).startswith("_")])
    if old_n and old_n != len(files):
        print(f"[INFO] index.json を再構築: {old_n}件 → {len(files)}件"
              f"（実在しない {old_n - len(files)}件を除去）")
    print(f"[INFO] 実在する試合ファイル: {games}件")
    return files


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
    "date", "game_id", "stadium", "team", "opponent", "is_home",
    "player", "player_id", "player_key",
    "order", "position", "is_starter", "sub_type",
    "season_avg", "ab", "runs", "hits", "rbi", "so", "bb", "hbp",
    "sac", "sb", "errors", "hr",
]

PIT_LINE_COLS = [
    "date", "game_id", "stadium", "team", "opponent", "is_home",
    "player", "player_id", "player_key", "decision", "is_starter",
    "season_era", "innings", "outs", "pitches", "batters_faced",
    "hits_allowed", "hr_allowed", "so", "bb", "hbp", "balk",
    "runs_allowed", "earned_runs", "is_qs",
]

SEASON_BAT_COLS = [
    "season", "player_key", "player_id", "player", "team", "league", "number",
    "hand", "position", "qualified",
    "games", "pa", "ab", "runs", "hits", "singles", "doubles", "triples", "hr",
    "rbi", "bb", "so", "sb", "errors", "tb",
    "avg", "obp", "slg", "ops", "bb_pct", "k_pct",
]

SEASON_PIT_COLS = [
    "season", "player_key", "player_id", "player", "team", "league", "number",
    "hand", "qualified",
    "games", "innings", "outs", "batters_faced", "pitches",
    "hits_allowed", "hr_allowed", "so", "bb", "hbp",
    "runs_allowed", "earned_runs", "wins", "losses", "saves",
    "holds_official", "holds_est", "relief_wins", "hp",
    "era", "whip", "k9", "bb9", "k_bb", "win_pct",
]

SEASON_TEAM_COLS = [
    "season", "team", "mini", "league",
    "games", "wins", "losses", "runs", "runs_allowed", "run_diff", "hits", "hr",
]

GAME_COLS = [
    "date", "game_id", "home", "away", "stadium", "home_score", "away_score",
    "winner", "state", "win_pitcher", "lose_pitcher", "save_pitcher",
    "atbat_count", "pitch_count",
]


# ---------- 変換 ----------

def season_tables(season, base="data"):
    """
    rebuild_stats.py が作った集計JSONを、そのままCSVにできる平坦な行に変換する。
    再集計をやり直すのではなく、既にある集計結果を読むだけ。
    """
    from lib.normalize import team_info as _ti

    bat_rows, pit_rows, team_rows = [], [], []

    ppath = f"{base}/{season}/players/stats.json"
    if os.path.exists(ppath):
        with open(ppath, encoding="utf-8") as f:
            players = json.load(f).get("players", [])

        # 規定の判定に使うチーム試合数（収集済みベース）
        team_games = {}
        tpath = f"{base}/{season}/teams/stats.json"
        if os.path.exists(tpath):
            with open(tpath, encoding="utf-8") as f:
                for t in json.load(f).get("teams", []):
                    if t.get("team"):
                        team_games[t["team"]] = t.get("games") or 0

        import math
        for p in players:
            team = p.get("team")
            lg = _ti(team).get("league")
            tg = team_games.get(team) or 0

            b = p.get("batting")
            if b and (b.get("pa") or 0) > 0:
                need = math.ceil(tg * 3.1) if tg else None
                bat_rows.append({
                    "season": season, "player_key": p.get("key"),
                    "player_id": p.get("player_id"), "player": p.get("name"),
                    "team": team, "league": lg, "number": p.get("number"),
                    "hand": p.get("hand"), "position": p.get("position"),
                    "qualified": (need is not None and (b.get("pa") or 0) >= need),
                    "games": b.get("games"), "pa": b.get("pa"), "ab": b.get("ab"),
                    "runs": b.get("runs"), "hits": b.get("hits"),
                    "singles": b.get("singles"), "doubles": b.get("doubles"),
                    "triples": b.get("triples"), "hr": b.get("hr"),
                    "rbi": b.get("rbi"), "bb": b.get("bb"), "so": b.get("so"),
                    "sb": b.get("sb"), "errors": b.get("errors"), "tb": b.get("tb"),
                    "avg": b.get("avg"), "obp": b.get("obp"), "slg": b.get("slg"),
                    "ops": b.get("ops"), "bb_pct": b.get("bb_pct"),
                    "k_pct": b.get("k_pct"),
                })

            q = p.get("pitching")
            if q and (q.get("outs") or 0) > 0:
                need_o = tg * 3 if tg else None
                pit_rows.append({
                    "season": season, "player_key": p.get("key"),
                    "player_id": p.get("player_id"), "player": p.get("name"),
                    "team": team, "league": lg, "number": p.get("number"),
                    "hand": p.get("hand"),
                    "qualified": (need_o is not None and (q.get("outs") or 0) >= need_o),
                    "games": q.get("games"), "innings": q.get("innings"),
                    "outs": q.get("outs"), "batters_faced": q.get("batters_faced"),
                    "pitches": q.get("pitches"),
                    "hits_allowed": q.get("hits_allowed"),
                    "hr_allowed": q.get("hr_allowed"), "so": q.get("so"),
                    "bb": q.get("bb"), "hbp": q.get("hbp"),
                    "runs_allowed": q.get("runs_allowed"),
                    "earned_runs": q.get("earned_runs"),
                    "wins": q.get("wins"), "losses": q.get("losses"),
                    "saves": q.get("saves"),
                    "holds_official": q.get("holds"),
                    "holds_est": q.get("holds_est"),
                    "relief_wins": q.get("relief_wins"), "hp": q.get("hp"),
                    "era": q.get("era"), "whip": q.get("whip"),
                    "k9": q.get("k9"), "bb9": q.get("bb9"),
                    "k_bb": q.get("k_bb"), "win_pct": q.get("win_pct"),
                })

    tpath = f"{base}/{season}/teams/stats.json"
    if os.path.exists(tpath):
        with open(tpath, encoding="utf-8") as f:
            for t in json.load(f).get("teams", []):
                team_rows.append({
                    "season": season, "team": t.get("team"), "mini": t.get("mini"),
                    "league": t.get("league"), "games": t.get("games"),
                    "wins": t.get("wins"), "losses": t.get("losses"),
                    "runs": t.get("runs"), "runs_allowed": t.get("runs_allowed"),
                    "run_diff": (t.get("runs") or 0) - (t.get("runs_allowed") or 0),
                    "hits": t.get("hits"), "hr": t.get("hr"),
                })

    return bat_rows, pit_rows, team_rows


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
                    "date": date, "game_id": gid, "stadium": g.get("stadium"), "team": team,
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
                    "date": date, "game_id": gid, "stadium": g.get("stadium"), "team": team,
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

    # 収集ファイル一覧を実ファイルから作り直す（試合数の食い違いを防ぐ）
    try:
        rebuild_index(base)
    except Exception as e:
        print(f"[WARN] index.json の再構築に失敗: {e}")

    out_dir = os.path.join(base, str(season), "dataset")
    # 集計済みのシーズン成績（rebuild_stats.py の出力）もCSV化する
    sb, sp, st = season_tables(season, base)

    tables = [
        (pitches, PITCH_COLS, "pitches"),
        (atbats, ATBAT_COLS, "atbats"),
        (bat_lines, BAT_LINE_COLS, "batting_lines"),
        (pit_lines, PIT_LINE_COLS, "pitching_lines"),
        (games, GAME_COLS, "games"),
        (sb, SEASON_BAT_COLS, "season_batting"),
        (sp, SEASON_PIT_COLS, "season_pitching"),
        (st, SEASON_TEAM_COLS, "season_teams"),
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
