"""
成績再集計スクリプト（冪等）
=============================
保存済みの試合JSONだけを唯一の正として、選手・チームのシーズン成績を
毎回ゼロから再生成する。前日累計への加算はしない（二重加算を構造的に防ぐ）。

使い方:
    python scraper/rebuild_stats.py --season 2026
    python scraper/rebuild_stats.py --date 2026-07-19   # その日を含むシーズンを再集計

出力:
    data/masters/players.json      … 選手マスター（ID・名前・所属・背番号・投打）
    data/masters/teams.json        … チームマスター
    data/{season}/players/stats.json … 選手シーズン成績
    data/{season}/teams/stats.json   … チームシーズン成績
"""

import argparse
import glob
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.normalize import (
    normalize_team, team_info, player_key, clean_name, TEAMS,
)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def find_games(season, base="data"):
    files = []
    for p in glob.glob(f"{base}/{season}/**/*.json", recursive=True):
        name = os.path.basename(p)
        if name.startswith("_") or name == "index.json":
            continue
        # players/ teams/ 配下の集計ファイルは除外
        if "/players/" in p.replace("\\", "/") or "/teams/" in p.replace("\\", "/"):
            continue
        files.append(p)
    return sorted(files)


def blank_batting():
    return {
        "games": 0, "pa": 0, "ab": 0, "hits": 0, "singles": 0,
        "doubles": 0, "triples": 0, "hr": 0, "rbi": 0, "bb": 0,
        "so": 0, "runs": 0,
    }


def blank_pitching():
    return {
        "games": 0, "batters_faced": 0, "pitches": 0, "hits_allowed": 0,
        "hr_allowed": 0, "so": 0, "bb": 0, "hbp": 0, "outs": 0,
        "runs_allowed": 0, "earned_runs": 0, "wins": 0, "losses": 0, "saves": 0,
    }


def calc_pitching_rates(p: dict) -> dict:
    """防御率・WHIP・K/9・BB/9 を計算（0除算対策込み）"""
    outs = p.get("outs", 0)
    ip = outs / 3 if outs else 0
    era = round(p["earned_runs"] * 9 / ip, 2) if ip else None
    whip = round((p["hits_allowed"] + p["bb"]) / ip, 2) if ip else None
    k9 = round(p["so"] * 9 / ip, 2) if ip else None
    bb9 = round(p["bb"] * 9 / ip, 2) if ip else None
    kbb = round(p["so"] / p["bb"], 2) if p["bb"] else None
    return {
        "innings": f"{outs // 3}.{outs % 3}" if outs % 3 else str(outs // 3),
        "era": era, "whip": whip, "k9": k9, "bb9": bb9, "k_bb": kbb,
    }


def merge_official_batting(dst: dict, row: dict):
    """公式ボックススコアの打撃行を累計に加算"""
    dst["pa"] += row["ab"] + row["bb"] + row["hbp"] + row["sac"]
    dst["ab"] += row["ab"]
    dst["hits"] += row["hits"]
    dst["hr"] += row["hr"]
    dst["rbi"] += row["rbi"]
    dst["bb"] += row["bb"] + row["hbp"]
    dst["so"] += row["so"]
    dst["runs"] += row["runs"]
    dst["sb"] = dst.get("sb", 0) + row["sb"]
    dst["errors"] = dst.get("errors", 0) + row["errors"]
    # 単打は「安打 - 本塁打」で近似（二塁打/三塁打は公式表に無いため）
    dst["singles"] += max(0, row["hits"] - row["hr"])


def merge_official_pitching(dst: dict, row: dict):
    """公式ボックススコアの投手行を累計に加算"""
    dst["outs"] += row.get("outs", 0)
    dst["pitches"] += row["pitches"]
    dst["batters_faced"] += row["batters_faced"]
    dst["hits_allowed"] += row["hits_allowed"]
    dst["hr_allowed"] += row["hr_allowed"]
    dst["so"] += row["so"]
    dst["bb"] += row["bb"]
    dst["hbp"] += row.get("hbp", 0)
    dst["runs_allowed"] += row.get("runs_allowed", 0)
    dst["earned_runs"] += row.get("earned_runs", 0)
    d = row.get("decision") or ""
    if "勝" in d:
        dst["wins"] += 1
    if "敗" in d:
        dst["losses"] += 1
    if "Ｓ" in d or "S" in d:
        dst["saves"] += 1


def classify_batting(result_summary: str) -> dict:
    """打席結果テキストから打撃イベントを分類（取れる範囲のみ・推測で埋めない）"""
    rs = result_summary or ""
    ev = {"pa": 1, "ab": 0, "hit": 0, "single": 0, "double": 0,
          "triple": 0, "hr": 0, "bb": 0, "so": 0}

    # 四死球（打数に数えない）
    if "四球" in rs or "死球" in rs:
        ev["bb"] = 1
        return ev
    # 犠打・犠飛（打数に数えない）
    if "犠打" in rs or "犠飛" in rs:
        return ev

    # ここからは打数にカウント
    ev["ab"] = 1
    if "三振" in rs:
        ev["so"] = 1
    elif "本塁打" in rs:
        ev["hit"] = ev["hr"] = 1
    elif "三塁打" in rs:
        ev["hit"] = ev["triple"] = 1
    elif "二塁打" in rs:
        ev["hit"] = ev["double"] = 1
    elif "安打" in rs and "併殺" not in rs:
        ev["hit"] = ev["single"] = 1
    return ev


def calc_rate_stats(b: dict) -> dict:
    """打率・出塁率・長打率・OPSなどを計算（0除算対策込み）"""
    ab = b["ab"]
    pa = b["pa"]
    hits = b["hits"]
    tb = b["singles"] + 2 * b["doubles"] + 3 * b["triples"] + 4 * b["hr"]
    avg = round(hits / ab, 3) if ab else None
    obp_den = ab + b["bb"]  # 犠飛は未取得のため簡易式
    obp = round((hits + b["bb"]) / obp_den, 3) if obp_den else None
    slg = round(tb / ab, 3) if ab else None
    ops = round((obp or 0) + (slg or 0), 3) if (obp is not None and slg is not None) else None
    bb_pct = round(b["bb"] / pa, 3) if pa else None
    k_pct = round(b["so"] / pa, 3) if pa else None
    return {"avg": avg, "obp": obp, "slg": slg, "ops": ops,
            "bb_pct": bb_pct, "k_pct": k_pct, "tb": tb}


def rebuild(season, base="data"):
    games = find_games(season, base)
    print(f"[INFO] {season}シーズン: {len(games)}試合を再集計")

    players = {}       # player_key -> master info
    bat = {}           # player_key -> batting counts
    pit = {}           # player_key -> pitching counts
    team_stats = {}    # team -> counts
    seen_game_per_player_bat = {}   # (pkey, game_id) 出場ゲーム重複防止
    seen_game_per_player_pit = {}

    for path in games:
        try:
            g = load_json(path)
        except Exception as e:
            print(f"[WARN] 読み込み失敗 {path}: {e}")
            continue

        gid = g.get("game_id")
        home = normalize_team(g.get("home"))
        away = normalize_team(g.get("away"))
        for t in (home, away):
            if t and t not in team_stats:
                team_stats[t] = {"games": 0, "runs": 0, "runs_allowed": 0,
                                 "hits": 0, "hr": 0, "wins": 0, "losses": 0}
        if home:
            team_stats[home]["games"] += 1
        if away:
            team_stats[away]["games"] += 1

        # ===== 公式ボックススコアがあればそれを最優先で使う（正確） =====
        box = g.get("boxscore")
        used_official = False
        if box and (box.get("batting") or box.get("pitching")):
            used_official = True
            side_team = {"away": away, "home": home}

            for side in ("away", "home"):
                team = side_team.get(side)
                for row in (box.get("batting", {}).get(side) or []):
                    k = player_key(row.get("player_id"), row.get("name"))
                    if not k:
                        continue
                    if k not in players:
                        players[k] = {
                            "key": k, "player_id": row.get("player_id"),
                            "name": clean_name(row.get("name")), "team": team,
                            "number": None, "hand": None,
                            "position": row.get("position"),
                        }
                    if k not in bat:
                        bat[k] = blank_batting()
                    if (k, gid) not in seen_game_per_player_bat:
                        seen_game_per_player_bat[(k, gid)] = True
                        bat[k]["games"] += 1
                    merge_official_batting(bat[k], row)
                    if team and team in team_stats:
                        team_stats[team]["hits"] += row.get("hits", 0)
                        team_stats[team]["hr"] += row.get("hr", 0)

                for row in (box.get("pitching", {}).get(side) or []):
                    k = player_key(row.get("player_id"), row.get("name"))
                    if not k:
                        continue
                    if k not in players:
                        players[k] = {
                            "key": k, "player_id": row.get("player_id"),
                            "name": clean_name(row.get("name")), "team": team,
                            "number": None, "hand": None,
                        }
                    if k not in pit:
                        pit[k] = blank_pitching()
                    if (k, gid) not in seen_game_per_player_pit:
                        seen_game_per_player_pit[(k, gid)] = True
                        pit[k]["games"] += 1
                    merge_official_pitching(pit[k], row)

            # チーム得点はスコアボードの公式値を使う
            sb = box.get("scoreboard") or {}
            for side in ("away", "home"):
                s = sb.get(side)
                t = side_team.get(side)
                if s and t and t in team_stats:
                    team_stats[t]["runs"] += s.get("runs", 0)
                    other = "home" if side == "away" else "away"
                    if sb.get(other):
                        team_stats[t]["runs_allowed"] += sb[other].get("runs", 0)

        # ===== 打席データからの補完（背番号・投打・公式が無い場合の推定） =====
        for ab in g.get("atbats", []):
            b = ab.get("batter") or {}
            p = ab.get("pitcher") or {}
            bteam = normalize_team(ab.get("batting_team"))
            fteam = normalize_team(ab.get("fielding_team"))

            # 打者：マスター情報（背番号・投打）を補完
            bkey = player_key(b.get("player_id"), b.get("name"))
            if bkey:
                if bkey not in players:
                    players[bkey] = {
                        "key": bkey,
                        "player_id": b.get("player_id"),
                        "name": clean_name(b.get("name")),
                        "team": bteam,
                        "number": b.get("number"),
                        "hand": b.get("hand"),
                    }
<<<<<<< HEAD
                else:
                    # 背番号・投打は打席データにしか無いので埋める
                    if not players[bkey].get("number"):
                        players[bkey]["number"] = b.get("number")
                    if not players[bkey].get("hand"):
                        players[bkey]["hand"] = b.get("hand")
=======
                # batは選手登録と独立して初期化（投手が打席に立つ場合に備える）
                if bkey not in bat:
                    bat[bkey] = blank_batting()
                # 出場試合数（同一試合1回だけ）
                if (bkey, gid) not in seen_game_per_player_bat:
                    seen_game_per_player_bat[(bkey, gid)] = True
                    bat[bkey]["games"] += 1
>>>>>>> 21616bc0a0e7f53e165d2ef58cac57890d2ac517

                # 公式成績が無い試合のみ、打席結果から推定して集計
                if not used_official:
                    if bkey not in bat:
                        bat[bkey] = blank_batting()
                    if (bkey, gid) not in seen_game_per_player_bat:
                        seen_game_per_player_bat[(bkey, gid)] = True
                        bat[bkey]["games"] += 1
                    ev = classify_batting(ab.get("result_summary"))
                    bb = bat[bkey]
                    bb["pa"] += ev["pa"]; bb["ab"] += ev["ab"]
                    bb["hits"] += ev["hit"]; bb["singles"] += ev["single"]
                    bb["doubles"] += ev["double"]; bb["triples"] += ev["triple"]
                    bb["hr"] += ev["hr"]; bb["bb"] += ev["bb"]; bb["so"] += ev["so"]
                    m = re.search(r"＋(\d+)点", ab.get("result_summary") or "")
                    if m:
                        bb["rbi"] += int(m.group(1))
                        if bteam and bteam in team_stats:
                            team_stats[bteam]["runs"] += int(m.group(1))

            # 投手：マスター情報を補完
            pkey = player_key(p.get("player_id"), p.get("name"))
            if pkey:
                if pkey not in players:
                    players[pkey] = {
                        "key": pkey,
                        "player_id": p.get("player_id"),
                        "name": clean_name(p.get("name")),
                        "team": fteam,
                        "number": p.get("number"),
                        "hand": p.get("hand"),
                    }
                else:
                    if not players[pkey].get("number"):
                        players[pkey]["number"] = p.get("number")
                    if not players[pkey].get("hand"):
                        players[pkey]["hand"] = p.get("hand")

                if not used_official:
                    if pkey not in pit:
                        pit[pkey] = blank_pitching()
                    if (pkey, gid) not in seen_game_per_player_pit:
                        seen_game_per_player_pit[(pkey, gid)] = True
                        pit[pkey]["games"] += 1
                    pp = pit[pkey]
                    pp["batters_faced"] += 1
                    pp["pitches"] += ab.get("pitch_count", 0)
                    ev = classify_batting(ab.get("result_summary"))
                    pp["hits_allowed"] += ev["hit"]
                    pp["hr_allowed"] += ev["hr"]
                    pp["so"] += ev["so"]
                    pp["bb"] += ev["bb"]

    # --- 出力を組み立て ---
    player_out = []
    for k, info in players.items():
        entry = dict(info)
        if k in bat:
            entry["batting"] = {**bat[k], **calc_rate_stats(_fill(bat[k]))}
        if k in pit:
            entry["pitching"] = {**pit[k], **calc_pitching_rates(pit[k])}
        player_out.append(entry)
    player_out.sort(key=lambda x: (x.get("team") or "", x.get("name") or ""))

    # マスター（成績を除いた基本情報）
    master = [{"key": p["key"], "player_id": p["player_id"], "name": p["name"],
               "team": p["team"], "number": p["number"], "hand": p["hand"]}
              for p in player_out]

    team_out = []
    for t, s in team_stats.items():
        info = team_info(t)
        team_out.append({"team": t, "mini": info["mini"], "league": info["league"], **s})
    team_out.sort(key=lambda x: (x.get("league") or "", -x.get("runs", 0)))

    save_json(f"{base}/masters/players.json", {"count": len(master), "players": master})
    save_json(f"{base}/masters/teams.json",
              {"teams": [{"name": n, **v} for n, v in TEAMS.items()]})
    save_json(f"{base}/{season}/players/stats.json",
              {"season": season, "count": len(player_out), "players": player_out})
    save_json(f"{base}/{season}/teams/stats.json",
              {"season": season, "teams": team_out})

    print(f"[INFO] 選手{len(player_out)}人・チーム{len(team_out)}件を再集計・保存")
    return len(player_out)


def _fill(b):
    """calc_rate_stats用にキーを補完"""
    d = blank_batting()
    d.update(b)
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default=None)
    ap.add_argument("--date", default=None, help="この日を含むシーズンを再集計")
    ap.add_argument("--base", default="data")
    args = ap.parse_args()

    season = args.season
    if not season and args.date:
        season = args.date.split("-")[0]
    if not season:
        print("[ERROR] --season または --date を指定してください")
        return 1

    rebuild(season, args.base)
    return 0


if __name__ == "__main__":
    sys.exit(main())
