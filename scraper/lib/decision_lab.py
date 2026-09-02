"""意思決定ラボ用の事前集計。

公開済みの試合・選手データだけを使い、推測で欠損値を補わない。
予測値はすべて前提と標本数を出力側に残す。
"""

from __future__ import annotations

import math
import random
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from statistics import median

from .analysis_lab import build_wpa_timelines, integer, number, truthy


LEAGUES = {
    "セ": {"巨人", "阪神", "DeNA", "広島", "ヤクルト", "中日"},
    "パ": {"ソフトバンク", "日本ハム", "オリックス", "楽天", "西武", "ロッテ"},
}


def _iso(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _league(team):
    return next((name for name, teams in LEAGUES.items() if team in teams), "")


def _weighted(rows, value_key, weight_key):
    weight = sum(number(row.get(weight_key)) for row in rows)
    if not weight:
        return None
    return sum(number(row.get(value_key)) * number(row.get(weight_key)) for row in rows) / weight


def _safe_ratio(a, b):
    return a / b if b else None


def _batting_rate(rows):
    keys = ("ab", "hits", "singles", "doubles", "triples", "hr", "bb", "hbp", "sf", "sac", "so")
    sums = {key: sum(integer(row.get(key)) for row in rows) for key in keys}
    # batting_lines は pa を持たないため、公式打席構成から復元する。
    sums["pa"] = sum(
        integer(row.get("pa")) or (
            integer(row.get("ab")) + integer(row.get("bb")) + integer(row.get("hbp")) + integer(row.get("sac"))
        ) for row in rows
    )
    sacrifice_flies = sums["sf"] or sums["sac"]
    obp_den = sums["ab"] + sums["bb"] + sums["hbp"] + sacrifice_flies
    avg = _safe_ratio(sums["hits"], sums["ab"])
    obp = _safe_ratio(sums["hits"] + sums["bb"] + sums["hbp"], obp_den)
    slg = _safe_ratio(sums["singles"] + 2 * sums["doubles"] + 3 * sums["triples"] + 4 * sums["hr"], sums["ab"])
    return {
        **sums,
        "avg": avg,
        "obp": obp,
        "slg": slg,
        "ops": obp + slg if obp is not None and slg is not None else None,
    }


def _pitching_rate(rows):
    outs = sum(integer(row.get("outs")) for row in rows)
    earned = sum(integer(row.get("earned_runs")) for row in rows)
    hits = sum(integer(row.get("hits_allowed")) for row in rows)
    walks = sum(integer(row.get("bb")) for row in rows)
    strikeouts = sum(integer(row.get("so")) for row in rows)
    hr = sum(integer(row.get("hr_allowed")) for row in rows)
    innings = outs / 3
    return {
        "outs": outs,
        "innings": innings,
        "era": 9 * earned / innings if innings else None,
        "whip": (hits + walks) / innings if innings else None,
        "k9": 9 * strikeouts / innings if innings else None,
        "bb9": 9 * walks / innings if innings else None,
        "hr9": 9 * hr / innings if innings else None,
    }


def build_bullpen(pitching_lines, season_pitching, data_date):
    """直近登板から救援投手の負荷を可視化する。登板可否そのものは断定しない。"""
    target = _iso(data_date)
    if not target:
        return {"data_date": data_date, "teams": [], "rules": []}
    season_map = {row.get("player_key"): row for row in season_pitching}
    pool = defaultdict(list)
    for row in pitching_lines:
        if truthy(row.get("is_starter")) or not row.get("player_key") or not _iso(row.get("date")):
            continue
        pool[(row.get("team"), row.get("player_key"))].append(row)

    teams = defaultdict(list)
    for (team, key), rows in pool.items():
        rows.sort(key=lambda row: (row.get("date", ""), row.get("game_id", "")))
        latest = _iso(rows[-1].get("date"))
        if not latest or (target - latest).days > 21:
            continue
        by_date = defaultdict(int)
        for row in rows:
            by_date[row["date"]] += integer(row.get("pitches"))
        pitches_1 = by_date.get(target.isoformat(), 0)
        pitches_yesterday = by_date.get((target - timedelta(days=1)).isoformat(), 0)
        pitches_3 = sum(value for day, value in by_date.items() if 0 <= (target - _iso(day)).days <= 2)
        apps_3 = sum(1 for day in by_date if 0 <= (target - _iso(day)).days <= 2)
        apps_5 = sum(1 for day in by_date if 0 <= (target - _iso(day)).days <= 4)
        consecutive = 0
        cursor = target
        while by_date.get(cursor.isoformat(), 0):
            consecutive += 1
            cursor -= timedelta(days=1)
        workload = "通常"
        if pitches_yesterday >= 25 or pitches_3 >= 50 or consecutive >= 3:
            workload = "高負荷"
        elif pitches_yesterday >= 15 or pitches_3 >= 35 or apps_3 >= 2:
            workload = "注意"
        season_row = season_map.get(key, {})
        saves = integer(season_row.get("saves"))
        holds = integer(season_row.get("holds_official")) or integer(season_row.get("holds_est"))
        role = "抑え" if saves >= max(3, holds) else ("中継ぎ" if holds or len(rows) >= 5 else "救援")
        teams[team].append({
            "player_key": key,
            "name": rows[-1].get("player") or "",
            "role": role,
            "latest_date": latest.isoformat(),
            "days_since": (target - latest).days,
            "pitches_today": pitches_1,
            "pitches_yesterday": pitches_yesterday,
            "pitches_last_3_days": pitches_3,
            "apps_last_3_days": apps_3,
            "apps_last_5_days": apps_5,
            "consecutive_days": consecutive,
            "season_games": integer(season_row.get("games")),
            "saves": saves,
            "holds": holds,
            "workload": workload,
            "source": "dataset/pitching_lines.csv",
        })
    result = []
    level = {"高負荷": 0, "注意": 1, "通常": 2}
    for team in sorted(teams):
        players = sorted(teams[team], key=lambda row: (level[row["workload"]], row["days_since"], -row["pitches_last_3_days"], row["name"]))
        result.append({"team": team, "league": _league(team), "players": players})
    return {
        "data_date": data_date,
        "teams": result,
        "rules": [
            "高負荷: 前日25球以上、直近3日50球以上、または3日連続登板",
            "注意: 前日15球以上、直近3日35球以上、または直近3日で2登板",
            "通常: 上記以外。けが・移動・本人の状態は含まない",
        ],
        "note": "登板履歴だけから見た負荷の目安で、登板可能・不可能を断定する情報ではありません。",
    }


def _park_factors(games):
    by_team = defaultdict(lambda: {"home_runs": 0, "home_games": 0, "away_runs": 0, "away_games": 0, "stadiums": Counter()})
    for row in games:
        hs, aws = row.get("home_score"), row.get("away_score")
        if hs in (None, "") or aws in (None, ""):
            continue
        total = integer(hs) + integer(aws)
        home, away = row.get("home"), row.get("away")
        if home:
            by_team[home]["home_runs"] += total
            by_team[home]["home_games"] += 1
            if row.get("stadium"):
                by_team[home]["stadiums"][row["stadium"]] += 1
        if away:
            by_team[away]["away_runs"] += total
            by_team[away]["away_games"] += 1
    factors = []
    for team, item in by_team.items():
        home_rate = _safe_ratio(item["home_runs"], item["home_games"])
        away_rate = _safe_ratio(item["away_runs"], item["away_games"])
        if home_rate is None or away_rate in (None, 0):
            continue
        raw = home_rate / away_rate
        sample = min(item["home_games"], item["away_games"])
        shrunk = 1 + (raw - 1) * sample / (sample + 40)
        factors.append({
            "team": team,
            "league": _league(team),
            "stadium": item["stadiums"].most_common(1)[0][0] if item["stadiums"] else "",
            "home_games": item["home_games"],
            "away_games": item["away_games"],
            "home_runs_per_game": round(home_rate, 2),
            "away_runs_per_game": round(away_rate, 2),
            "raw": raw,
            "factor": shrunk,
        })
    weighted_mean = _weighted(factors, "factor", "home_games") or 1
    for item in factors:
        item["factor"] = round(item["factor"] / weighted_mean, 3)
        item["raw"] = round(item["raw"], 3)
    return sorted(factors, key=lambda row: row["factor"], reverse=True)


def build_adjusted_metrics(games, batting, pitching):
    parks = _park_factors(games)
    park_map = {row["team"]: row["factor"] for row in parks}
    batting_by_league = defaultdict(list)
    pitching_by_league = defaultdict(list)
    for row in batting:
        batting_by_league[row.get("league") or _league(row.get("team"))].append(row)
    for row in pitching:
        pitching_by_league[row.get("league") or _league(row.get("team"))].append(row)
    league_bat = {}
    league_pitch = {}
    for league, rows in batting_by_league.items():
        league_bat[league] = {
            "obp": _weighted(rows, "obp", "pa"), "slg": _weighted(rows, "slg", "pa"),
            "woba": _weighted(rows, "woba_est", "pa"),
        }
    for league, rows in pitching_by_league.items():
        league_pitch[league] = {"era": _weighted(rows, "era", "outs"), "fip": _weighted(rows, "fip", "outs")}
    hitters = []
    for row in batting:
        pa = integer(row.get("pa"))
        if pa < 25:
            continue
        league = row.get("league") or _league(row.get("team"))
        lg = league_bat.get(league, {})
        obp, slg, woba = number(row.get("obp")), number(row.get("slg")), number(row.get("woba_est"))
        if not lg.get("obp") or not lg.get("slg"):
            continue
        full_pf = park_map.get(row.get("team"), 1.0)
        exposure_pf = (1 + full_pf) / 2
        ops_plus = 100 * (obp / lg["obp"] + slg / lg["slg"] - 1) / exposure_pf
        wrc_plus = 100 * (woba / lg["woba"]) / exposure_pf if lg.get("woba") and woba else None
        hitters.append({
            "player_key": row.get("player_key"), "name": row.get("player"), "team": row.get("team"),
            "league": league, "position": row.get("position"), "pa": pa, "qualified": truthy(row.get("qualified")),
            "ops": round(number(row.get("ops")), 3), "woba": round(woba, 3), "park_factor": round(exposure_pf, 3),
            "ops_plus": round(ops_plus, 1), "wrc_plus_est": round(wrc_plus, 1) if wrc_plus is not None else None,
        })
    pitchers = []
    for row in pitching:
        outs = integer(row.get("outs"))
        if outs < 15:
            continue
        league = row.get("league") or _league(row.get("team"))
        lg = league_pitch.get(league, {})
        era, fip = number(row.get("era")), number(row.get("fip"))
        full_pf = park_map.get(row.get("team"), 1.0)
        exposure_pf = (1 + full_pf) / 2
        era_minus = 100 * era / lg["era"] / exposure_pf if lg.get("era") else None
        fip_minus = 100 * fip / lg["fip"] / exposure_pf if lg.get("fip") else None
        pitchers.append({
            "player_key": row.get("player_key"), "name": row.get("player"), "team": row.get("team"),
            "league": league, "innings": round(outs / 3, 1), "qualified": truthy(row.get("qualified")),
            "era": round(era, 2), "fip": round(fip, 2), "park_factor": round(exposure_pf, 3),
            "era_minus": round(era_minus, 1) if era_minus is not None else None,
            "fip_minus": round(fip_minus, 1) if fip_minus is not None else None,
        })
    hitters.sort(key=lambda row: (-row["ops_plus"], -row["pa"]))
    pitchers.sort(key=lambda row: (row["era_minus"] if row["era_minus"] is not None else 999, -row["innings"]))
    return {
        "parks": parks, "hitters": hitters, "pitchers": pitchers,
        "league_averages": {"batting": league_bat, "pitching": league_pitch},
        "method": "本拠地と遠征時の両軍合計得点/試合の比を40試合相当で1.000へ縮小し、平均1.000に正規化。選手補正は年間出場の半分を本拠地と仮定。",
        "caution": "単年の記述的パークファクターです。風向・屋根・対戦相手・実際の出場球場比率は未調整。wRC+は収集データ由来wOBAによる推定です。",
    }


def _draft_info(text):
    text = str(text or "")
    year = re.search(r"(\d{4})年", text)
    rank = re.search(r"(?:ドラフト|育成)\s*(\d+)位", text)
    return (int(year.group(1)) if year else None, int(rank.group(1)) if rank else None, "育成" if "育成" in text else "支配下")


def _career_volume(profile):
    bat = profile.get("career_batting") or {}
    pit = profile.get("career_pitching") or {}
    pa = integer(bat.get("plate_appearances"))
    innings_value = pit.get("innings")
    innings = number(innings_value)
    if innings_value not in (None, "") and "." in str(innings_value):
        whole, remainder = str(innings_value).split(".", 1)
        if remainder in {"0", "1", "2"}:
            innings = integer(whole) + integer(remainder) / 3
    if not innings:
        innings = number(pit.get("innings_pitched"))
    games = max(integer(bat.get("games")), integer(pit.get("games")))
    return pa, innings, games


def build_draft_review(profiles, season):
    cohorts = defaultdict(list)
    rounds = defaultdict(list)
    for profile in profiles:
        year, rank, route = _draft_info(profile.get("draft"))
        if year is None:
            continue
        pa, innings, games = _career_volume(profile)
        item = {
            "name": profile.get("name"), "team": profile.get("team"), "draft": profile.get("draft"),
            "year": year, "rank": rank, "route": route, "career_pa": pa,
            "career_innings": round(innings, 1), "career_games": games,
            "active": str(profile.get("team") or "") in set().union(*LEAGUES.values()),
        }
        cohorts[year].append(item)
        rounds[(route, rank)].append(item)
    output = []
    for year, players in sorted(cohorts.items(), reverse=True):
        pa_values = [p["career_pa"] for p in players]
        ip_values = [p["career_innings"] for p in players]
        debut = sum(1 for p in players if p["career_games"] > 0)
        output.append({
            "year": year, "players": len(players), "active": sum(1 for p in players if p["active"]),
            "debut": debut, "debut_rate": round(100 * debut / len(players), 1),
            "career_pa_total": sum(pa_values), "career_pa_median": round(median(pa_values), 1),
            "career_innings_total": round(sum(ip_values), 1), "career_innings_median": round(median(ip_values), 1),
            "top_batters": sorted([p for p in players if p["career_pa"]], key=lambda p: p["career_pa"], reverse=True)[:5],
            "top_pitchers": sorted([p for p in players if p["career_innings"]], key=lambda p: p["career_innings"], reverse=True)[:5],
        })
    round_rows = []
    for (route, rank), players in sorted(rounds.items(), key=lambda item: (item[0][0] == "育成", item[0][1] or 99)):
        if rank is None:
            continue
        debut = sum(1 for p in players if p["career_games"] > 0)
        round_rows.append({
            "route": route, "rank": rank, "players": len(players), "debut_rate": round(100 * debut / len(players), 1),
            "career_pa_per_player": round(sum(p["career_pa"] for p in players) / len(players), 1),
            "career_innings_per_player": round(sum(p["career_innings"] for p in players) / len(players), 1),
        })
    return {
        "cohorts": output, "rounds": round_rows,
        "note": f"プロフィールに取得済みの通算成績を使用。{season}年時点の生存者バイアスがあり、未取得選手・海外成績・二軍成績・WARは含みません。",
    }


def build_playoff_odds(standings, seed=2026, simulations=10000):
    rng = random.Random(seed)
    leagues = {}
    for league, rows in (("セ", standings.get("central", [])), ("パ", standings.get("pacific", []))):
        teams = []
        for row in rows:
            games = integer(row.get("games"))
            wins, losses, ties = integer(row.get("wins")), integer(row.get("losses")), integer(row.get("ties"))
            runs, allowed = integer(row.get("runs")), integer(row.get("runs_allowed"))
            observed = (wins + 0.5 * ties) / games if games else 0.5
            pyth = runs ** 1.83 / (runs ** 1.83 + allowed ** 1.83) if runs and allowed else observed
            blended = (0.65 * observed + 0.35 * pyth)
            strength = (blended * games + 0.5 * 20) / (games + 20)
            teams.append({"team": row.get("team"), "games": games, "wins": wins, "losses": losses, "ties": ties,
                          "games_left": integer(row.get("games_left")), "strength": strength, "pennant": 0, "cs": 0,
                          "wins_sum": 0})
        for _ in range(simulations):
            outcome = []
            for team in teams:
                extra = sum(1 for _game in range(team["games_left"]) if rng.random() < team["strength"])
                final_wins = team["wins"] + extra
                final_games = team["games"] + team["games_left"]
                rate = (final_wins + 0.5 * team["ties"]) / final_games if final_games else 0
                outcome.append((rate, rng.random(), team, final_wins))
            outcome.sort(key=lambda x: (x[0], x[1]), reverse=True)
            for rank, (_rate, _tie, team, final_wins) in enumerate(outcome, 1):
                team["wins_sum"] += final_wins
                if rank == 1:
                    team["pennant"] += 1
                if rank <= 3:
                    team["cs"] += 1
        leagues[league] = [{
            "team": team["team"], "games": team["games"], "games_left": team["games_left"],
            "strength": round(team["strength"], 3), "expected_wins": round(team["wins_sum"] / simulations, 1),
            "pennant_pct": round(100 * team["pennant"] / simulations, 1),
            "cs_pct": round(100 * team["cs"] / simulations, 1),
        } for team in sorted(teams, key=lambda x: x["pennant"], reverse=True)]
    return {
        "simulations": simulations, "leagues": leagues,
        "method": "現在勝率65%＋得失点からのピタゴラス勝率35%を混合し、20試合相当で.500へ縮小。残り試合を二項試行。",
        "caution": "残りの正確な対戦カード、先発、故障、引き分け発生率は未反映。順位確率は予言ではなく、現時点の感度分析です。",
    }


def build_change_alerts(batting_lines, pitching_lines):
    batters, pitchers = defaultdict(list), defaultdict(list)
    for row in batting_lines:
        if row.get("player_key"):
            batters[row["player_key"]].append(row)
    for row in pitching_lines:
        if row.get("player_key"):
            pitchers[row["player_key"]].append(row)
    batter_alerts = []
    for key, rows in batters.items():
        rows.sort(key=lambda r: (r.get("date", ""), r.get("game_id", "")))
        recent, prior = rows[-5:], rows[:-5]
        a, b = _batting_rate(recent), _batting_rate(prior)
        if a["pa"] < 12 or b["pa"] < 30 or a["ops"] is None or b["ops"] is None:
            continue
        delta = a["ops"] - b["ops"]
        if abs(delta) < 0.15:
            continue
        reliability = a["pa"] / (a["pa"] + 25)
        batter_alerts.append({
            "player_key": key, "name": rows[-1].get("player"), "team": rows[-1].get("team"),
            "direction": "上昇" if delta > 0 else "低下", "recent_games": len(recent), "recent_pa": a["pa"],
            "recent_ops": round(a["ops"], 3), "baseline_pa": b["pa"], "baseline_ops": round(b["ops"], 3),
            "delta": round(delta, 3), "signal": round(abs(delta) * reliability, 3),
            "confidence": "中" if a["pa"] >= 20 else "低", "source": "dataset/batting_lines.csv",
        })
    pitcher_alerts = []
    for key, rows in pitchers.items():
        rows.sort(key=lambda r: (r.get("date", ""), r.get("game_id", "")))
        recent, prior = rows[-3:], rows[:-3]
        a, b = _pitching_rate(recent), _pitching_rate(prior)
        starter = any(truthy(r.get("is_starter")) for r in recent)
        min_recent, min_prior = (18, 30) if starter else (6, 18)
        if a["outs"] < min_recent or b["outs"] < min_prior or a["era"] is None or b["era"] is None:
            continue
        delta = a["era"] - b["era"]
        if abs(delta) < 1.0:
            continue
        reliability = a["outs"] / (a["outs"] + (27 if starter else 12))
        pitcher_alerts.append({
            "player_key": key, "name": rows[-1].get("player"), "team": rows[-1].get("team"),
            "role": "先発" if starter else "救援", "direction": "改善" if delta < 0 else "悪化",
            "recent_games": len(recent), "recent_innings": round(a["innings"], 1), "recent_era": round(a["era"], 2),
            "recent_k9": round(a["k9"], 1) if a["k9"] is not None else None,
            "baseline_innings": round(b["innings"], 1), "baseline_era": round(b["era"], 2),
            "delta": round(delta, 2), "signal": round(abs(delta) * reliability, 2),
            "confidence": "中" if a["outs"] >= (30 if starter else 12) else "低", "source": "dataset/pitching_lines.csv",
        })
    batter_alerts.sort(key=lambda row: row["signal"], reverse=True)
    pitcher_alerts.sort(key=lambda row: row["signal"], reverse=True)
    return {
        "batters": batter_alerts[:40], "pitchers": pitcher_alerts[:40],
        "rules": ["野手: 直近5出場12打席以上、以前30打席以上、OPS差.150以上", "投手: 直近3登板とそれ以前を比較。役割別の最低投球回とERA差1.00以上"],
        "caution": "変化の検知であり、原因や今後の持続を示すものではありません。短期標本は信頼度を低く表示します。",
    }


def build_all(games, atbats, batting_lines, pitching_lines, season_batting, season_pitching, profiles, standings, season):
    dates = [row.get("date") for row in games if _iso(row.get("date"))]
    data_date = max(dates) if dates else ""
    return {
        "season": str(season),
        "data_date": data_date,
        "win_probability": build_wpa_timelines(atbats, games),
        "bullpen": build_bullpen(pitching_lines, season_pitching, data_date),
        "adjusted_metrics": build_adjusted_metrics(games, season_batting, season_pitching),
        "draft_review": build_draft_review(profiles, season),
        "playoff_odds": build_playoff_odds(standings, seed=integer(season)),
        "change_alerts": build_change_alerts(batting_lines, pitching_lines),
    }
