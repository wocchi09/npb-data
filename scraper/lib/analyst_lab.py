"""NPB ANALYST LAB 用の再現可能な事前集計。"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from statistics import mean

from .analysis_lab import integer, number, truthy
from .pitch_metrics import summarize_pitcher_pitches


TEAMS = ["巨人", "阪神", "DeNA", "広島", "ヤクルト", "中日", "ソフトバンク", "日本ハム", "オリックス", "楽天", "西武", "ロッテ"]


def ratio(a, b):
    return a / b if b else None


def rounded(value, digits=3):
    return round(value, digits) if value is not None else None


def batting_summary(rows):
    aliases = {"hit": ("hit", "hits"), "single": ("single", "singles"), "double": ("double", "doubles"), "triple": ("triple", "triples")}
    fields = ("pa", "ab", "hit", "single", "double", "triple", "hr", "bb", "hbp", "sf", "sh", "so", "rbi")
    sums = {}
    for key in fields:
        names = aliases.get(key, (key,))
        sums[key] = sum(next((integer(row.get(name)) for name in names if row.get(name) not in (None, "")), 0) for row in rows)
    if not sums["sf"] and not sums["sh"]:
        sums["sf"] = sum(integer(row.get("sac")) for row in rows)
    if not sums["pa"]:
        sums["pa"] = sums["ab"] + sums["bb"] + sums["hbp"] + sums["sf"] + sums["sh"]
    avg = ratio(sums["hit"], sums["ab"])
    obp = ratio(sums["hit"] + sums["bb"] + sums["hbp"], sums["ab"] + sums["bb"] + sums["hbp"] + sums["sf"])
    slg = ratio(sums["single"] + 2 * sums["double"] + 3 * sums["triple"] + 4 * sums["hr"], sums["ab"])
    return {**sums, "avg": rounded(avg), "obp": rounded(obp), "slg": rounded(slg), "ops": rounded(obp + slg) if obp is not None and slg is not None else None}


def _hypothesis(label, question, metric, a_label, a, b_label, b, caveat):
    av, bv = a.get(metric), b.get(metric)
    return {
        "id": label, "question": question, "metric": metric.upper(),
        "group_a": {"label": a_label, "value": rounded(av), "n": a.get("pa") or a.get("games") or 0},
        "group_b": {"label": b_label, "value": rounded(bv), "n": b.get("pa") or b.get("games") or 0},
        "difference": rounded(av - bv) if av is not None and bv is not None else None,
        "caveat": caveat,
    }


def build_hypotheses(atbats, pitches, batting_lines, pitching_lines, games):
    output = []
    risp = batting_summary([r for r in atbats if truthy(r.get("risp"))])
    no_risp = batting_summary([r for r in atbats if not truthy(r.get("risp"))])
    output.append(_hypothesis("risp", "得点圏では打撃結果が変わるか？", "ops", "得点圏", risp, "非得点圏", no_risp, "打順・投手・点差を調整していない記述比較です。"))

    home = batting_summary([r for r in batting_lines if truthy(r.get("is_home"))])
    away = batting_summary([r for r in batting_lines if not truthy(r.get("is_home"))])
    output.append(_hypothesis("home", "ホームとビジターでOPSは違うか？", "ops", "ホーム", home, "ビジター", away, "球場と対戦相手の構成差を含みます。"))

    pa_first = {}
    terminal = {}
    for row in pitches:
        key = (row.get("game_id"), row.get("atbat_index"))
        if integer(row.get("pitch_no")) == 1:
            pa_first[key] = truthy(row.get("is_swing"))
        if truthy(row.get("is_last_pitch")):
            terminal[key] = row
    swing_rows, take_rows = [], []
    for key, row in terminal.items():
        target = swing_rows if pa_first.get(key) else take_rows
        target.append({
            "pa": 1, "ab": 0 if any(x in str(row.get("ab_result") or "") for x in ("四球", "死球", "犠打", "犠飛")) else 1,
            "hit": integer(row.get("ab_hit")), "single": 1 if integer(row.get("ab_hit")) and not any(x in str(row.get("ab_result") or "") for x in ("二塁打", "三塁打", "本塁打")) else 0,
            "double": 1 if "二塁打" in str(row.get("ab_result") or "") else 0, "triple": 1 if "三塁打" in str(row.get("ab_result") or "") else 0,
            "hr": 1 if "本塁打" in str(row.get("ab_result") or "") else 0, "bb": 1 if "四球" in str(row.get("ab_result") or "") else 0,
            "hbp": 1 if "死球" in str(row.get("ab_result") or "") else 0,
        })
    output.append(_hypothesis("first_pitch", "初球スイング時はOPSが高いか？", "ops", "初球スイング", batting_summary(swing_rows), "初球見送り", batting_summary(take_rows), "選手能力や初球の甘さを調整しておらず、初球を振る因果効果ではありません。"))

    game_map = {str(g.get("game_id")): g for g in games}
    deep, short = {"wins": 0, "games": 0}, {"wins": 0, "games": 0}
    seen = set()
    for row in pitching_lines:
        if not truthy(row.get("is_starter")):
            continue
        gid, team = str(row.get("game_id")), row.get("team")
        if (gid, team) in seen:
            continue
        seen.add((gid, team)); bucket = deep if integer(row.get("outs")) >= 21 else short; bucket["games"] += 1
        if game_map.get(gid, {}).get("winner") == team:
            bucket["wins"] += 1
    for bucket in (deep, short):
        bucket["win_pct"] = ratio(bucket["wins"], bucket["games"])
    output.append(_hypothesis("starter7", "先発が7回以上投げた試合は勝率が高いか？", "win_pct", "7回以上", deep, "7回未満", short, "好投したから長く投げた逆因果を強く含みます。"))
    relief = defaultdict(lambda: {"runs": 0, "seen": False})
    for row in pitching_lines:
        if not truthy(row.get("is_starter")):
            key = (str(row.get("game_id")), row.get("team")); relief[key]["runs"] += integer(row.get("runs_allowed")); relief[key]["seen"] = True
    clean, allowed = {"wins": 0, "games": 0}, {"wins": 0, "games": 0}
    for (gid, team), item in relief.items():
        bucket = clean if item["runs"] == 0 else allowed; bucket["games"] += 1; bucket["wins"] += game_map.get(gid, {}).get("winner") == team
    for bucket in (clean, allowed): bucket["win_pct"] = ratio(bucket["wins"], bucket["games"])
    output.append(_hypothesis("relief_zero", "救援無失点の試合はどれだけ勝率が高いか？", "win_pct", "救援無失点", clean, "救援失点あり", allowed, "勝っているチームほど有利な場面で救援を使う選択効果を含みます。"))
    return output


def build_manager_decisions(atbats, batting_lines, runner_events, pitching_lines, games):
    game_map = {str(g.get("game_id")): g for g in games}
    teams = defaultdict(lambda: {"bunt": {"attempts": 0, "success": 0}, "pinch": {"pa": 0, "hits": 0, "on_base": 0, "rbi": 0}, "running": {"attempts": 0, "success": 0, "run_value": 0.0}, "hooks": {"games": 0, "scoreless": 0, "runs": 0}})
    for row in atbats:
        if integer(row.get("sh")) or "犠打" in str(row.get("result") or ""):
            item = teams[row.get("batting_team")]["bunt"]; item["attempts"] += 1; item["success"] += 1 if integer(row.get("sh")) else 0
    for row in batting_lines:
        if row.get("sub_type") == "代打":
            item = teams[row.get("team")]["pinch"]
            pa = integer(row.get("ab")) + integer(row.get("bb")) + integer(row.get("hbp")) + integer(row.get("sac"))
            item["pa"] += pa; item["hits"] += integer(row.get("hits")); item["on_base"] += integer(row.get("hits")) + integer(row.get("bb")) + integer(row.get("hbp")); item["rbi"] += integer(row.get("rbi"))
    for row in runner_events:
        if row.get("event_type") in ("stolen_base", "caught_stealing"):
            item = teams[row.get("batting_team")]["running"]; item["attempts"] += 1; item["success"] += row.get("event_type") == "stolen_base"; item["run_value"] += number(row.get("run_value"))
    relief_by_game = defaultdict(list)
    for row in pitching_lines:
        if not truthy(row.get("is_starter")):
            relief_by_game[(str(row.get("game_id")), row.get("team"))].append(row)
    for (_gid, team), rows in relief_by_game.items():
        item = teams[team]["hooks"]; runs = sum(integer(r.get("runs_allowed")) for r in rows); item["games"] += 1; item["runs"] += runs; item["scoreless"] += runs == 0
    output = []
    for team in TEAMS:
        item = teams[team]
        item["team"] = team
        item["bunt"]["success_rate"] = rounded(ratio(item["bunt"]["success"], item["bunt"]["attempts"]))
        item["pinch"]["obp"] = rounded(ratio(item["pinch"]["on_base"], item["pinch"]["pa"]))
        item["running"]["success_rate"] = rounded(ratio(item["running"]["success"], item["running"]["attempts"]))
        item["running"]["run_value"] = rounded(item["running"]["run_value"], 1)
        item["hooks"]["scoreless_rate"] = rounded(ratio(item["hooks"]["scoreless"], item["hooks"]["games"]))
        output.append(item)
    return {"teams": output, "note": "記録された結果の集計であり、選ばなかった代替策との反実仮想比較ではありません。監督の判断能力を直接評価する指標ではありません。"}


def _pitch_rates(rows):
    speeds = [number(r.get("speed_kmh")) for r in rows if r.get("pitch_type") == "ストレート" and number(r.get("speed_kmh")) > 0]
    known_swing = [r for r in rows if r.get("is_swing") not in (None, "")]
    swings = sum(truthy(r.get("is_swing")) for r in known_swing)
    misses = sum(truthy(r.get("is_miss")) for r in known_swing)
    strikes = sum(truthy(r.get("is_called")) or truthy(r.get("is_swing")) and not truthy(r.get("is_ball")) for r in rows)
    return {"pitches": len(rows), "fastball_avg": rounded(mean(speeds), 1) if speeds else None, "fastballs": len(speeds), "strike_rate": rounded(ratio(strikes, len(rows))), "whiff_rate": rounded(ratio(misses, swings))}


def build_pitcher_condition(pitches):
    grouped = defaultdict(list)
    for row in pitches:
        if row.get("pitcher_key"):
            grouped[(row.get("game_id"), row.get("pitcher_key"))].append(row)
    games = []
    for (gid, key), rows in grouped.items():
        if len(rows) < 40:
            continue
        rows.sort(key=lambda r: (integer(r.get("atbat_no")), integer(r.get("pitch_no"))))
        segments = []
        for start in range(0, len(rows), 25):
            selected = rows[start:start + 25]
            values = _pitch_rates(selected); values["label"] = f"{start + 1}-{start + len(selected)}球"; segments.append(values)
        first = next((s for s in segments if s["fastball_avg"] is not None and s["fastballs"] >= 3), None)
        last = next((s for s in reversed(segments) if s["fastball_avg"] is not None and s["fastballs"] >= 3), None)
        drop = rounded(last["fastball_avg"] - first["fastball_avg"], 1) if first and last and first is not last else None
        games.append({"game_id": gid, "date": rows[0].get("date"), "player_key": key, "name": rows[0].get("pitcher"), "team": rows[0].get("fielding_team"), "opponent": rows[0].get("batting_team"), "pitches": len(rows), "segments": segments, "fastball_change": drop, "alert": drop is not None and drop <= -1.5})
    games.sort(key=lambda r: (r["date"], r["pitches"]), reverse=True)
    return {"games": games, "alerts": sorted([g for g in games if g["alert"]], key=lambda g: g["fastball_change"])[:50], "note": "球速低下は疲労の診断ではありません。配球、計測、気温、意図的な出力調整の影響を含みます。"}


def build_pitch_sequences(pitches):
    by_pitcher_pa = defaultdict(list)
    pitcher_info = {}
    for row in pitches:
        key = row.get("pitcher_key")
        if not key or not row.get("pitch_type"):
            continue
        pitcher_info[key] = {"player_key": key, "name": row.get("pitcher"), "team": row.get("fielding_team")}
        by_pitcher_pa[(key, row.get("game_id"), row.get("atbat_index"))].append(row)
    counts = defaultdict(Counter); outcomes = defaultdict(lambda: defaultdict(lambda: {"n": 0, "miss": 0, "inplay": 0}))
    totals = Counter()
    for (key, _gid, _ab), rows in by_pitcher_pa.items():
        rows.sort(key=lambda r: integer(r.get("pitch_no")))
        totals[key] += len(rows)
        for before, after in zip(rows, rows[1:]):
            a, b = before.get("pitch_type"), after.get("pitch_type"); counts[key][(a, b)] += 1
            o = outcomes[key][(a, b)]; o["n"] += 1; o["miss"] += truthy(after.get("is_miss")); o["inplay"] += truthy(after.get("is_inplay"))
    players = []
    for key, total in totals.most_common(150):
        transitions = []
        for (a, b), count in counts[key].most_common(15):
            o = outcomes[key][(a, b)]
            transitions.append({"from": a, "to": b, "n": count, "share": rounded(ratio(count, sum(v for (x, _), v in counts[key].items() if x == a))), "next_whiff_rate": rounded(ratio(o["miss"], o["n"])), "next_inplay_rate": rounded(ratio(o["inplay"], o["n"]))})
        players.append({**pitcher_info[key], "pitches": total, "transitions": transitions})
    return {"players": players, "note": "連続する2球の記述集計です。結果差は球種選択の因果効果を示しません。"}


def build_shrunk_matchups(atbats, prior_pa=20):
    all_stats = batting_summary(atbats)
    prior = {"hit": ratio(all_stats["hit"], all_stats["ab"]) or 0, "obp": all_stats["obp"] or 0, "slg": all_stats["slg"] or 0}
    grouped = defaultdict(list); info = {}
    for row in atbats:
        bk, pk = row.get("batter_key"), row.get("pitcher_key")
        if not bk or not pk:
            continue
        grouped[(bk, pk)].append(row)
        info[(bk, pk)] = {"batter_key": bk, "batter": row.get("batter"), "batter_team": row.get("batting_team"), "pitcher_key": pk, "pitcher": row.get("pitcher"), "pitcher_team": row.get("fielding_team")}
    pairs = []
    for key, rows in grouped.items():
        stats = batting_summary(rows)
        if stats["pa"] < 5:
            continue
        shrunk_avg = (stats["hit"] + prior["hit"] * prior_pa) / (stats["ab"] + prior_pa)
        shrunk_obp = ((stats["obp"] or 0) * stats["pa"] + prior["obp"] * prior_pa) / (stats["pa"] + prior_pa)
        shrunk_slg = ((stats["slg"] or 0) * stats["ab"] + prior["slg"] * prior_pa) / (stats["ab"] + prior_pa)
        confidence = 5 if stats["pa"] >= 30 else 4 if stats["pa"] >= 20 else 3 if stats["pa"] >= 15 else 2 if stats["pa"] >= 10 else 1
        pairs.append({**info[key], "pa": stats["pa"], "ab": stats["ab"], "hits": stats["hit"], "hr": stats["hr"], "raw_avg": stats["avg"], "raw_ops": stats["ops"], "shrunk_avg": rounded(shrunk_avg), "shrunk_ops": rounded(shrunk_obp + shrunk_slg), "confidence": confidence, "stars": "★" * confidence + "☆" * (5 - confidence)})
    pairs.sort(key=lambda r: (-r["pa"], r["batter"], r["pitcher"]))
    return {"pairs": pairs, "prior_pa": prior_pa, "league_prior": {"avg": rounded(prior["hit"]), "obp": rounded(prior["obp"]), "slg": rounded(prior["slg"])}, "note": f"リーグ平均{prior_pa}打席相当を事前分布として縮小。相性の原因や将来成績を保証しません。"}


def _z_scores(values, higher=True):
    valid = [v for v in values.values() if v is not None]
    mu = mean(valid) if valid else 0; sd = math.sqrt(mean([(v - mu) ** 2 for v in valid])) if valid else 1
    if not sd: sd = 1
    return {k: round(max(50, min(150, 100 + (15 if higher else -15) * (v - mu) / sd)), 1) if v is not None else None for k, v in values.items()}


def build_team_radar(season_batting, pitching_lines, season_teams, games):
    bat_rows = defaultdict(list)
    for row in season_batting: bat_rows[row.get("team")].append(row)
    ops, iso, discipline, baserun = {}, {}, {}, {}
    for team in TEAMS:
        rows = bat_rows[team]; pa = sum(integer(r.get("pa")) for r in rows)
        ops[team] = sum(number(r.get("ops")) * integer(r.get("pa")) for r in rows) / pa if pa else None
        iso[team] = sum(number(r.get("iso")) * integer(r.get("pa")) for r in rows) / pa if pa else None
        discipline[team] = sum((number(r.get("bb_pct")) - number(r.get("k_pct"))) * integer(r.get("pa")) for r in rows) / pa if pa else None
        baserun[team] = sum(number(r.get("bsr_est")) for r in rows) if rows else None
    der = {r.get("team"): number(r.get("der"), None) for r in season_teams}
    starter, relief = {}, {}
    for team in TEAMS:
        rows = [r for r in pitching_lines if r.get("team") == team]
        for target, flag in ((starter, True), (relief, False)):
            selected = [r for r in rows if truthy(r.get("is_starter")) == flag]; outs = sum(integer(r.get("outs")) for r in selected); er = sum(integer(r.get("earned_runs")) for r in selected)
            target[team] = 27 * er / outs if outs else None
    close = {}
    for team in TEAMS:
        one = [g for g in games if team in (g.get("home"), g.get("away")) and abs(integer(g.get("home_score")) - integer(g.get("away_score"))) <= 1]
        close[team] = ratio(sum(g.get("winner") == team for g in one), len(one))
    components = {"打撃": _z_scores(ops), "長打": _z_scores(iso), "選球": _z_scores(discipline), "走塁": _z_scores(baserun), "守備": _z_scores(der), "先発": _z_scores(starter, False), "救援": _z_scores(relief, False), "接戦": _z_scores(close)}
    teams = []
    for team in TEAMS:
        values = {name: score.get(team) for name, score in components.items()}
        teams.append({"team": team, "scores": values, "overall": rounded(mean([v for v in values.values() if v is not None]), 1), "raw": {"ops": rounded(ops[team]), "iso": rounded(iso[team]), "der": rounded(der.get(team)), "starter_era": rounded(starter[team], 2), "relief_era": rounded(relief[team], 2), "close_win_pct": rounded(close[team])}})
    teams.sort(key=lambda r: r["overall"], reverse=True)
    return {"teams": teams, "scale": "リーグ横断平均100・標準偏差15・50〜150に制限", "note": "各要素は同じ勝利価値ではありません。接戦成績は変動が大きく、守備はチームDERによる近似です。"}


def build_depth(w_impact):
    groups = defaultdict(list)
    for row in w_impact.get("batters", []):
        pos = (row.get("stats") or {}).get("primary_position") or row.get("position") or "野手"
        groups[(row.get("team"), pos)].append({"name": row.get("name"), "player_key": row.get("player_key"), "w_value": number(row.get("w_value")), "rating": number(row.get("w_rating")), "role": pos})
    for row in w_impact.get("pitchers", []):
        stats = row.get("stats") or {}; role = stats.get("role") or stats.get("primary_role") or row.get("role") or "投手"
        groups[(row.get("team"), role)].append({"name": row.get("name"), "player_key": row.get("player_key"), "w_value": number(row.get("w_value")), "rating": number(row.get("w_rating")), "role": role})
    output = []
    for (team, role), players in groups.items():
        players.sort(key=lambda p: p["w_value"], reverse=True); top = players[:3]; positive = sum(max(0, p["w_value"]) for p in players)
        share = max(0, top[0]["w_value"]) / positive if positive and top else None
        depth_score = sum(max(0, p["w_value"]) for p in top[1:])
        output.append({"team": team, "role": role, "players": top, "top_share": rounded(share), "depth_value": rounded(depth_score, 2), "risk": "集中" if share is not None and share >= .6 else "標準" if depth_score >= 1 else "薄い"})
    output.sort(key=lambda r: (TEAMS.index(r["team"]) if r["team"] in TEAMS else 99, r["role"]))
    return {"groups": output, "note": "W-Valueの上位3人による簡易デプス。二軍成績、故障、契約、将来予測は含みません。"}


def build_elo(games, k=20, home_advantage=35):
    ratings = defaultdict(lambda: 1500.0); sos_sum = Counter(); sos_games = Counter(); history = defaultdict(list)
    ordered = sorted(games, key=lambda g: (g.get("date", ""), str(g.get("game_id", ""))))
    for game in ordered:
        home, away = game.get("home"), game.get("away"); winner = game.get("winner")
        if home not in TEAMS or away not in TEAMS or winner not in (home, away, "引き分け", "引分"):
            continue
        rh, ra = ratings[home], ratings[away]; expected = 1 / (1 + 10 ** ((ra - (rh + home_advantage)) / 400)); actual = 1 if winner == home else 0 if winner == away else .5
        change = k * (actual - expected); sos_sum[home] += ra; sos_games[home] += 1; sos_sum[away] += rh; sos_games[away] += 1
        ratings[home] += change; ratings[away] -= change
        history[home].append({"date": game.get("date"), "rating": round(ratings[home], 1)}); history[away].append({"date": game.get("date"), "rating": round(ratings[away], 1)})
    teams = []
    for team in TEAMS:
        points = history[team]; before = points[-11]["rating"] if len(points) > 10 else 1500
        teams.append({"team": team, "rating": round(ratings[team], 1), "last10_change": round(ratings[team] - before, 1), "schedule_strength": round(sos_sum[team] / sos_games[team], 1) if sos_games[team] else None, "history": points[-60:]})
    teams.sort(key=lambda r: r["rating"], reverse=True)
    return {"teams": teams, "k": k, "home_advantage": home_advantage, "note": "全チーム1500開始、ホーム補正35、K=20。点差・選手構成・将来日程は未反映です。"}


def _best_split(series, min_side, value_fn):
    best = None
    for i in range(min_side, len(series) - min_side + 1):
        a, b = value_fn(series[:i]), value_fn(series[i:])
        if a is None or b is None: continue
        score = abs(b - a) * math.sqrt(min(i, len(series) - i))
        if best is None or score > best[0]: best = (score, i, a, b)
    return best


def build_change_points(batting_lines, pitches):
    batters = defaultdict(list)
    for row in batting_lines:
        if row.get("player_key"): batters[row["player_key"]].append(row)
    batting = []
    for key, rows in batters.items():
        rows.sort(key=lambda r: (r.get("date", ""), r.get("game_id", "")))
        if len(rows) < 14: continue
        split = _best_split(rows, 6, lambda x: batting_summary(x)["ops"])
        if not split: continue
        score, i, before, after = split
        if abs(after - before) < .12: continue
        batting.append({"player_key": key, "name": rows[-1].get("player"), "team": rows[-1].get("team"), "date": rows[i].get("date"), "games_before": i, "games_after": len(rows)-i, "before": rounded(before), "after": rounded(after), "change": rounded(after-before), "score": rounded(score)})
    by_pitcher_game = defaultdict(list)
    for row in pitches:
        if row.get("pitcher_key") and row.get("pitch_type") == "ストレート" and number(row.get("speed_kmh")) > 0:
            by_pitcher_game[(row.get("pitcher_key"), row.get("game_id"))].append(row)
    pitcher_series = defaultdict(list)
    for (key, _gid), rows in by_pitcher_game.items():
        if len(rows) >= 3: pitcher_series[key].append({"date": rows[0].get("date"), "name": rows[0].get("pitcher"), "team": rows[0].get("fielding_team"), "velocity": mean(number(r.get("speed_kmh")) for r in rows)})
    pitching = []
    for key, rows in pitcher_series.items():
        rows.sort(key=lambda r:r["date"])
        if len(rows) < 8: continue
        split = _best_split(rows, 3, lambda x: mean(r["velocity"] for r in x))
        if not split: continue
        score, i, before, after = split
        if abs(after-before) < 1.0: continue
        pitching.append({"player_key":key,"name":rows[-1]["name"],"team":rows[-1]["team"],"date":rows[i]["date"],"games_before":i,"games_after":len(rows)-i,"before":rounded(before,1),"after":rounded(after,1),"change":rounded(after-before,1),"score":rounded(score,1)})
    batting.sort(key=lambda r:r["score"],reverse=True); pitching.sort(key=lambda r:r["score"],reverse=True)
    return {"batting":batting[:60],"pitching":pitching[:60],"note":"全候補点から差が最大になる分割点を探索した記述的検知です。多重比較の影響があり、原因や持続性を示しません。"}


def build_all(games, atbats, pitches, batting_lines, pitching_lines, runner_events, season_batting, season_teams, w_impact):
    latest = max((g.get("date", "") for g in games), default="")
    return {
        "data_date": latest,
        "hypotheses": build_hypotheses(atbats, pitches, batting_lines, pitching_lines, games),
        "manager_decisions": build_manager_decisions(atbats, batting_lines, runner_events, pitching_lines, games),
        "pitcher_condition": build_pitcher_condition(pitches),
        "pitch_sequences": build_pitch_sequences(pitches),
        "shrunk_matchups": build_shrunk_matchups(atbats),
        "team_radar": build_team_radar(season_batting, pitching_lines, season_teams, games),
        "depth": build_depth(w_impact),
        "elo": build_elo(games),
        "change_points": build_change_points(batting_lines, pitches),
    }
