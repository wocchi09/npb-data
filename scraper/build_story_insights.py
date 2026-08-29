"""Build compact story-oriented insights for the GitHub Pages viewer.

Outputs:
    data/{season}/_story_insights.json

The leading underscore is intentional: build_dataset.py already ignores JSON files whose
basename starts with "_", so this generated artifact is never mistaken for a game file.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))


def load_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def num(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def integer(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def ratio(a, b):
    return (a / b) if b else None


def rounded(value, digits=3):
    if value is None:
        return None
    return round(float(value), digits)


def outs_to_ip(outs):
    outs = int(outs or 0)
    return f"{outs // 3}.{outs % 3}"


def aggregate_batting(rows):
    total = defaultdict(float)
    for row in rows:
        for key in (
            "ab", "runs", "hits", "rbi", "so", "bb", "hbp", "sac",
            "singles", "doubles", "triples", "hr",
        ):
            total[key] += num(row.get(key))
    pa = total["ab"] + total["bb"] + total["hbp"] + total["sac"]
    tb = total["singles"] + 2 * total["doubles"] + 3 * total["triples"] + 4 * total["hr"]
    avg = ratio(total["hits"], total["ab"])
    obp = ratio(total["hits"] + total["bb"] + total["hbp"], pa)
    slg = ratio(tb, total["ab"])
    ops = None if obp is None or slg is None else obp + slg
    return {
        "pa": int(pa), "ab": int(total["ab"]), "runs": int(total["runs"]),
        "hits": int(total["hits"]), "rbi": int(total["rbi"]), "so": int(total["so"]),
        "bb": int(total["bb"]), "hbp": int(total["hbp"]), "hr": int(total["hr"]),
        "avg": rounded(avg), "obp": rounded(obp), "slg": rounded(slg), "ops": rounded(ops),
    }


def aggregate_pitching(rows):
    total = defaultdict(float)
    for row in rows:
        mapping = {
            "outs": "outs", "earned_runs": "er", "runs_allowed": "runs", "so": "so",
            "bb": "bb", "hits_allowed": "hits", "hr_allowed": "hr", "pitches": "pitches",
            "batters_faced": "bf",
        }
        for src, dst in mapping.items():
            total[dst] += num(row.get(src))
    innings = total["outs"] / 3
    return {
        "outs": int(total["outs"]), "innings": outs_to_ip(total["outs"]),
        "earned_runs": int(total["er"]), "runs_allowed": int(total["runs"]),
        "so": int(total["so"]), "bb": int(total["bb"]), "hits_allowed": int(total["hits"]),
        "hr_allowed": int(total["hr"]), "pitches": int(total["pitches"]),
        "era": rounded((total["er"] * 9 / innings) if innings else None, 2),
        "whip": rounded(((total["hits"] + total["bb"]) / innings) if innings else None, 2),
        "k9": rounded((total["so"] * 9 / innings) if innings else None, 2),
    }


def player_batting_summary(row):
    if not row:
        return None
    return {"name": row.get("player") or "-", "hits": integer(row.get("hits")),
            "hr": integer(row.get("hr")), "rbi": integer(row.get("rbi")),
            "runs": integer(row.get("runs")), "bb": integer(row.get("bb"))}


def pitcher_line(row):
    if not row:
        return None
    return {"name": row.get("player") or "-", "innings": outs_to_ip(integer(row.get("outs"))),
            "outs": integer(row.get("outs")), "earned_runs": integer(row.get("earned_runs")),
            "runs_allowed": integer(row.get("runs_allowed")), "so": integer(row.get("so")),
            "bb": integer(row.get("bb")), "hits_allowed": integer(row.get("hits_allowed")),
            "pitches": integer(row.get("pitches"))}


def latest_game_stories(games, batting_lines, pitching_lines):
    dated = [g for g in games if g.get("date")]
    if not dated:
        return {"date": None, "games": []}
    latest = max(g["date"] for g in dated)
    out = []
    for game in [g for g in dated if g.get("date") == latest]:
        home_score = integer(game.get("home_score"), -1)
        away_score = integer(game.get("away_score"), -1)
        if home_score < 0 or away_score < 0:
            continue
        home, away = game.get("home") or "-", game.get("away") or "-"
        winner = game.get("winner")
        if winner not in (home, away):
            out.append({"game_id": game.get("game_id"), "home": home, "away": away,
                        "home_score": home_score, "away_score": away_score,
                        "stadium": game.get("stadium"), "winner": None,
                        "headline": "引き分け", "note": "勝因カードは勝敗が付いた試合のみ表示します。"})
            continue
        loser = away if winner == home else home
        game_id = str(game.get("game_id") or "")
        win_bat = [r for r in batting_lines if str(r.get("game_id") or "") == game_id and r.get("team") == winner]
        lose_bat = [r for r in batting_lines if str(r.get("game_id") or "") == game_id and r.get("team") == loser]
        win_pit = [r for r in pitching_lines if str(r.get("game_id") or "") == game_id and r.get("team") == winner]
        offense, opponent_offense = aggregate_batting(win_bat), aggregate_batting(lose_bat)
        top_batter = max(win_bat, key=lambda r: (integer(r.get("rbi")) * 4 + integer(r.get("hr")) * 3
                          + integer(r.get("hits")) * 1.5 + integer(r.get("runs")) + integer(r.get("bb")) * 0.5), default=None)
        starter = next((r for r in win_pit if truthy(r.get("is_starter"))), win_pit[0] if win_pit else None)
        bullpen = aggregate_pitching([r for r in win_pit if r is not starter])
        tags = []
        if offense["hr"] > opponent_offense["hr"]: tags.append("長打で優位")
        if offense["bb"] > opponent_offense["bb"]: tags.append("四球で出塁")
        if starter and integer(starter.get("outs")) >= 18 and integer(starter.get("earned_runs")) <= 3: tags.append("先発が試合作る")
        if bullpen["outs"] >= 6 and bullpen["earned_runs"] == 0: tags.append("救援無失点")
        if not tags: tags.append("総合力で上回る")
        tb, sp = player_batting_summary(top_batter), pitcher_line(starter)
        headline_parts = []
        if tb: headline_parts.append(f"{tb['name']} {tb['hits']}安打{tb['rbi']}打点")
        if sp: headline_parts.append(f"{sp['name']} {sp['innings']}回 自責{sp['earned_runs']}")
        out.append({"game_id": game.get("game_id"), "home": home, "away": away,
                    "home_score": home_score, "away_score": away_score, "stadium": game.get("stadium"),
                    "winner": winner, "loser": loser, "margin": abs(home_score-away_score),
                    "headline": " / ".join(headline_parts) or f"{winner}が勝利", "tags": tags[:4],
                    "offense": offense, "opponent_offense": opponent_offense, "top_batter": tb,
                    "starter": sp, "bullpen": bullpen,
                    "note": "勝因の断定ではなく、当日のボックススコアから目立った勝利要素を抽出しています。"})
    return {"date": latest, "games": out}


def team_game_rows(games, team):
    rows = [g for g in games if g.get("home") == team or g.get("away") == team]
    return sorted(rows, key=lambda g: (g.get("date") or "", str(g.get("game_id") or "")))


def game_record(rows, team):
    wins = losses = ties = runs = allowed = 0
    for g in rows:
        home = g.get("home") == team
        rf = integer(g.get("home_score") if home else g.get("away_score"))
        ra = integer(g.get("away_score") if home else g.get("home_score"))
        runs += rf; allowed += ra
        if rf > ra: wins += 1
        elif rf < ra: losses += 1
        else: ties += 1
    n = len(rows)
    return {"games": n, "wins": wins, "losses": losses, "ties": ties, "runs": runs, "allowed": allowed,
            "runs_per_game": rounded(runs/n if n else None, 2), "allowed_per_game": rounded(allowed/n if n else None, 2)}


def build_team_trends(games, batting_lines, pitching_lines):
    teams = sorted({x for g in games for x in (g.get("home"), g.get("away")) if x})
    result = []
    for team in teams:
        season_games = team_game_rows(games, team); recent_games = season_games[-10:]
        season_ids = {str(g.get("game_id") or "") for g in season_games}
        recent_ids = {str(g.get("game_id") or "") for g in recent_games}
        season_bat = aggregate_batting([r for r in batting_lines if r.get("team") == team and str(r.get("game_id") or "") in season_ids])
        recent_bat = aggregate_batting([r for r in batting_lines if r.get("team") == team and str(r.get("game_id") or "") in recent_ids])
        season_pit = aggregate_pitching([r for r in pitching_lines if r.get("team") == team and str(r.get("game_id") or "") in season_ids])
        recent_pit = aggregate_pitching([r for r in pitching_lines if r.get("team") == team and str(r.get("game_id") or "") in recent_ids])
        season_rec, recent_rec = game_record(season_games, team), game_record(recent_games, team)
        ops_delta = None if season_bat["ops"] is None or recent_bat["ops"] is None else recent_bat["ops"] - season_bat["ops"]
        era_delta = None if season_pit["era"] is None or recent_pit["era"] is None else recent_pit["era"] - season_pit["era"]
        runs_delta = None if season_rec["runs_per_game"] is None or recent_rec["runs_per_game"] is None else recent_rec["runs_per_game"] - season_rec["runs_per_game"]
        allowed_delta = None if season_rec["allowed_per_game"] is None or recent_rec["allowed_per_game"] is None else recent_rec["allowed_per_game"] - season_rec["allowed_per_game"]
        changes=[]
        if ops_delta is not None and ops_delta >= .05: changes.append("打線のOPS上昇")
        elif ops_delta is not None and ops_delta <= -.05: changes.append("打線のOPS低下")
        if runs_delta is not None and runs_delta >= .5: changes.append("得点ペース上昇")
        elif runs_delta is not None and runs_delta <= -.5: changes.append("得点ペース低下")
        if era_delta is not None and era_delta <= -.5: changes.append("防御率が改善")
        elif era_delta is not None and era_delta >= .5: changes.append("防御率が悪化")
        if allowed_delta is not None and allowed_delta <= -.5: changes.append("失点ペース改善")
        elif allowed_delta is not None and allowed_delta >= .5: changes.append("失点ペース悪化")
        if not changes: changes.append("シーズン平均から大幅な変化なし")
        result.append({"team": team, "recent": {"record": recent_rec, "batting": recent_bat, "pitching": recent_pit},
                       "season": {"record": season_rec, "batting": season_bat, "pitching": season_pit},
                       "delta": {"ops": rounded(ops_delta), "era": rounded(era_delta,2),
                                 "runs_per_game": rounded(runs_delta,2), "allowed_per_game": rounded(allowed_delta,2)},
                       "changes": changes[:4]})
    return result


def new_pitcher_bucket(row):
    return {"key": row.get("pitcher_key") or row.get("pitcher_id") or row.get("pitcher") or "-",
            "name": row.get("pitcher") or "-", "team": row.get("fielding_team") or "-", "hand": row.get("pit_hand") or "-",
            "pitches":0,"k_finish":0,"miss":0,"called":0,"zone_seen":0,"out_zone":0,
            "types":defaultdict(lambda:{"pitches":0,"k_finish":0,"miss":0,"speed_sum":0,"speed_n":0,"zones":Counter()}),
            "hands":{"right":{"pitches":0,"k_finish":0,"types":Counter()},"left":{"pitches":0,"k_finish":0,"types":Counter()}}}


def summarize_hand(bucket):
    total=bucket["pitches"]
    if not total: return {"pitches":0,"k_finish_rate":None,"top_pitch":None,"top_pitch_share":None}
    top=bucket["types"].most_common(1)
    return {"pitches":total,"k_finish_rate":rounded(bucket["k_finish"]/total),
            "top_pitch":top[0][0] if top else None,"top_pitch_share":rounded(top[0][1]/total) if top else None}


def is_verified_strikeout_finish(row):
    """Return True only when this pitch actually ended the plate appearance in a strikeout."""
    if not truthy(row.get("is_last_pitch")):
        return False
    out_type = str(row.get("ab_out_type") or "").strip()
    result = str(row.get("ab_result") or "").strip()
    return out_type == "三振" and "三振" in result


def is_swinging_strikeout_finish(row):
    return is_verified_strikeout_finish(row) and str(row.get("ab_result") or "").strip().startswith("空振り三振")


def is_called_strikeout_finish(row):
    return is_verified_strikeout_finish(row) and str(row.get("ab_result") or "").strip().startswith("見逃し三振")


def build_two_strike(path, min_pitches=25, include_quality=False):
    pitchers={}
    quality={"definition_version":2,"validated":False,"two_strike_pitches":0,"strikeout_finishes":0,
             "swinging_strikeout_finishes":0,"called_strikeout_finishes":0,"legacy_is_miss_true":0,
             "source_fields":["strikes_before","is_last_pitch","ab_result","ab_out_type"]}
    if not os.path.exists(path): return ([],quality) if include_quality else []
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if integer(row.get("strikes_before"),-1)!=2: continue
            quality["two_strike_pitches"]+=1
            if truthy(row.get("is_miss")): quality["legacy_is_miss_true"]+=1
            key=row.get("pitcher_key") or row.get("pitcher_id") or row.get("pitcher")
            if not key: continue
            bucket=pitchers.setdefault(key,new_pitcher_bucket(row)); bucket["pitches"]+=1
            k_finish=is_verified_strikeout_finish(row)
            swing_finish=is_swinging_strikeout_finish(row)
            called_finish=is_called_strikeout_finish(row)
            if k_finish: quality["strikeout_finishes"]+=1
            if swing_finish: quality["swinging_strikeout_finishes"]+=1
            if called_finish: quality["called_strikeout_finishes"]+=1
            if k_finish: bucket["k_finish"]+=1
            if swing_finish: bucket["miss"]+=1
            if called_finish: bucket["called"]+=1
            inz=str(row.get("in_zone") or "").strip()
            if inz:
                bucket["zone_seen"]+=1
                if not truthy(inz): bucket["out_zone"]+=1
            pitch_type=row.get("pitch_type") or "不明"; ptype=bucket["types"][pitch_type]; ptype["pitches"]+=1
            if k_finish: ptype["k_finish"]+=1
            if swing_finish: ptype["miss"]+=1
            speed=num(row.get("speed_kmh"),0)
            if speed>0: ptype["speed_sum"]+=speed; ptype["speed_n"]+=1
            zone=row.get("zone_label")
            if zone: ptype["zones"][zone]+=1
            bat_hand=str(row.get("bat_hand") or ""); hand_key="right" if "右" in bat_hand else ("left" if "左" in bat_hand else None)
            if hand_key:
                hb=bucket["hands"][hand_key]; hb["pitches"]+=1; hb["types"][pitch_type]+=1
                if k_finish: hb["k_finish"]+=1
    out=[]
    for bucket in pitchers.values():
        if bucket["pitches"]<min_pitches: continue
        types=[]
        for name,stat in bucket["types"].items():
            n=stat["pitches"]; top_zone=stat["zones"].most_common(1)
            types.append({"pitch_type":name,"pitches":n,"share":rounded(n/bucket["pitches"]),
                          "k_finish_rate":rounded(stat["k_finish"]/n if n else None),
                          "whiff_rate":rounded(stat["miss"]/n if n else None),
                          "avg_speed":rounded(stat["speed_sum"]/stat["speed_n"],1) if stat["speed_n"] else None,
                          "top_zone":top_zone[0][0] if top_zone else None})
        types.sort(key=lambda item:item["pitches"],reverse=True)
        eligible=[x for x in types if x["pitches"]>=10 and x["k_finish_rate"] is not None]
        best=max(eligible,key=lambda x:x["k_finish_rate"],default=None)
        out.append({"key":bucket["key"],"name":bucket["name"],"team":bucket["team"],"hand":bucket["hand"],
                    "pitches":bucket["pitches"],"k_finish_rate":rounded(bucket["k_finish"]/bucket["pitches"]),
                    "whiff_rate":rounded(bucket["miss"]/bucket["pitches"]),"called_finish_rate":rounded(bucket["called"]/bucket["pitches"]),
                    "out_zone_rate":rounded(bucket["out_zone"]/bucket["zone_seen"]) if bucket["zone_seen"] else None,
                    "pitch_types":types[:8],"best_finisher":best,
                    "vs_right":summarize_hand(bucket["hands"]["right"]),"vs_left":summarize_hand(bucket["hands"]["left"])})
    out.sort(key=lambda item:(item["team"],item["name"]))
    quality["validated"]=quality["two_strike_pitches"]>0 and quality["strikeout_finishes"]>0
    return (out,quality) if include_quality else out


def build(season, base="data"):
    root=os.path.join(base,str(season)); dataset=os.path.join(root,"dataset")
    games=load_csv(os.path.join(dataset,"games.csv")); batting=load_csv(os.path.join(dataset,"batting_lines.csv")); pitching=load_csv(os.path.join(dataset,"pitching_lines.csv"))
    if not games: raise FileNotFoundError(f"games.csv がありません: {dataset}")
    two_strike, two_strike_quality=build_two_strike(os.path.join(dataset,"pitches.csv"),include_quality=True)
    output={"season":str(season),"generated_at":datetime.now(JST).isoformat(),
            "latest_games":latest_game_stories(games,batting,pitching),
            "two_strike_pitchers":two_strike,
            "team_trends":build_team_trends(games,batting,pitching),
            "quality":{"two_strike":two_strike_quality},
            "notes":{"win_factors":"勝因の因果推定ではなく、当日のボックススコアから目立った要素を抽出。",
                     "two_strike":"strikes_before=2 の投球のみを集計。is_last_pitch=true かつ ab_out_type=三振で、ab_resultにも三振が記録された投球だけを三振決着として扱う。",
                     "team_trends":"直近10試合と収集済みシーズン全体を比較。短期成績は対戦相手・球場・日程の影響を受ける。"}}
    path=os.path.join(root,"_story_insights.json")
    with open(path,"w",encoding="utf-8") as handle: json.dump(output,handle,ensure_ascii=False,separators=(",",":"))
    print(f"[INFO] story insights: latest={output['latest_games']['date']} / pitchers={len(output['two_strike_pitchers'])} / teams={len(output['team_trends'])}")
    return output


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--season",required=True); parser.add_argument("--base",default="data"); args=parser.parse_args(); build(args.season,args.base); return 0


if __name__=="__main__": sys.exit(main())
