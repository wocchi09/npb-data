"""NPB分析ラボ用の再現可能な集計ロジック。外部データや未取得値は推測しない。"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date


def number(value, default=0.0):
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def integer(value, default=0):
    return int(number(value, default))


def truthy(value):
    return str(value).strip().lower() in {"1", "true", "yes"}


def base_code(row):
    return ("1" if truthy(row.get("r1")) else "-") + ("2" if truthy(row.get("r2")) else "-") + ("3" if truthy(row.get("r3")) else "-")


def runs_on_play(row):
    result = str(row.get("result") or "")
    found = re.findall(r"[+＋](\d+)点", result)
    described = sum(int(x) for x in found)
    return max(described, integer(row.get("rbi")))


def state_key(outs, bases):
    return f"{max(0, min(2, int(outs)))}|{bases}"


def _group_halves(atbats):
    groups = defaultdict(list)
    for row in atbats:
        groups[(row.get("game_id"), row.get("inning"), row.get("top_bottom"))].append(row)
    for rows in groups.values():
        rows.sort(key=lambda x: (integer(x.get("atbat_no")), str(x.get("atbat_index") or "")))
    return groups


def build_re24(atbats):
    """24塁状況の期待得点と打者・投手RE24を同じ観測から算出する。"""
    observations = []
    for (_, _, _), rows in _group_halves(atbats).items():
        plays = [runs_on_play(row) for row in rows]
        future = 0
        future_runs = [0] * len(rows)
        for index in range(len(rows) - 1, -1, -1):
            future += plays[index]
            future_runs[index] = future
        previous_outs = 0
        for index, row in enumerate(rows):
            before = state_key(previous_outs, base_code(row))
            outs_after = integer(row.get("outs"), previous_outs)
            if index + 1 < len(rows):
                after = state_key(outs_after, base_code(rows[index + 1]))
            else:
                after = "END"
            observations.append({
                "row": row, "before": before, "after": after,
                "runs": plays[index], "future_runs": future_runs[index],
            })
            previous_outs = outs_after

    totals = defaultdict(float)
    counts = defaultdict(int)
    for obs in observations:
        totals[obs["before"]] += obs["future_runs"]
        counts[obs["before"]] += 1
    expected = {key: totals[key] / counts[key] for key in counts}

    states = []
    for outs in range(3):
        for bits in range(8):
            bases = ("1" if bits & 1 else "-") + ("2" if bits & 2 else "-") + ("3" if bits & 4 else "-")
            key = state_key(outs, bases)
            states.append({
                "key": key, "outs": outs, "bases": bases,
                "expected_runs": round(expected.get(key, 0.0), 3),
                "sample": counts.get(key, 0),
            })

    batter = defaultdict(lambda: {"name": "", "team": "", "pa": 0, "re24": 0.0})
    pitcher = defaultdict(lambda: {"name": "", "team": "", "pa": 0, "re24": 0.0})
    for obs in observations:
        row = obs["row"]
        value = obs["runs"] + (0.0 if obs["after"] == "END" else expected.get(obs["after"], 0.0)) - expected.get(obs["before"], 0.0)
        bk = row.get("batter_key") or row.get("batter")
        pk = row.get("pitcher_key") or row.get("pitcher")
        if bk:
            item = batter[bk]
            item.update({"player_key": bk, "name": row.get("batter") or "", "team": row.get("batting_team") or ""})
            item["pa"] += 1
            item["re24"] += value
        if pk:
            item = pitcher[pk]
            item.update({"player_key": pk, "name": row.get("pitcher") or "", "team": row.get("fielding_team") or ""})
            item["pa"] += 1
            item["re24"] -= value
    def finish(pool):
        result = []
        for item in pool.values():
            item = dict(item)
            item["re24"] = round(item["re24"], 2)
            item["re24_per_100"] = round(item["re24"] * 100 / item["pa"], 2) if item["pa"] else None
            result.append(item)
        return sorted(result, key=lambda x: x["re24"], reverse=True)
    return {"states": states, "batters": finish(batter), "pitchers": finish(pitcher), "observations": observations}


def _inning_number(row):
    return max(1, integer(row.get("inning"), 1))


def _wp_key(inning, top_bottom, diff, outs, bases):
    inning_bucket = min(10, inning)
    return f"{inning_bucket}|{top_bottom}|{max(-5, min(5, diff))}|{max(0, min(2, outs))}|{bases}"


def _baseline_home_wp(inning, top_bottom, home_diff):
    remaining = max(0.55, 9.5 - inning - (0.5 if top_bottom == "裏" else 0.0))
    logit = 0.12 + 0.92 * home_diff / math.sqrt(remaining)
    return 1.0 / (1.0 + math.exp(-max(-8.0, min(8.0, logit))))


def build_wpa(atbats, games):
    """同シーズン実測をベイズ縮小したNPB独自の推定勝利確率/WPA。"""
    # 公式最終スコアを取得できた試合だけをモデル学習・WPA集計へ使う。
    game_map = {
        str(g.get("game_id")): g for g in games
        if g.get("home_score") not in (None, "") and g.get("away_score") not in (None, "")
    }
    by_game = defaultdict(list)
    for row in atbats:
        game_id = str(row.get("game_id"))
        if game_id in game_map:
            by_game[game_id].append(row)
    exact_wins = defaultdict(float)
    exact_counts = defaultdict(int)
    prepared = []
    for game_id, rows in by_game.items():
        game = game_map.get(game_id, {})
        home, away = game.get("home"), game.get("away")
        winner = game.get("winner")
        rows.sort(key=lambda x: (str(x.get("date")), integer(x.get("atbat_no")), str(x.get("atbat_index") or "")))
        home_score = away_score = 0
        previous_half = None
        previous_outs = 0
        for row in rows:
            half = (row.get("inning"), row.get("top_bottom"))
            if half != previous_half:
                previous_outs = 0
                previous_half = half
            inning = _inning_number(row)
            top_bottom = row.get("top_bottom") or "表"
            bases = base_code(row)
            key = _wp_key(inning, top_bottom, home_score - away_score, previous_outs, bases)
            home_win = 1.0 if winner == home else (0.0 if winner == away else 0.5)
            exact_wins[key] += home_win
            exact_counts[key] += 1
            scored = runs_on_play(row)
            after_home, after_away = home_score, away_score
            if row.get("batting_team") == home:
                after_home += scored
            else:
                after_away += scored
            prepared.append({
                "row": row, "key": key, "inning": inning, "top_bottom": top_bottom,
                "outs_before": previous_outs, "bases": bases,
                "home_score": home_score, "away_score": away_score,
                "after_home": after_home, "after_away": after_away,
                "winner": winner, "home": home, "away": away,
            })
            home_score, away_score = after_home, after_away
            previous_outs = integer(row.get("outs"), previous_outs)

    def estimate(inning, top_bottom, home_diff, outs, bases):
        baseline = _baseline_home_wp(inning, top_bottom, home_diff)
        key = _wp_key(inning, top_bottom, home_diff, outs, bases)
        n = exact_counts.get(key, 0)
        empirical = exact_wins.get(key, 0.0) / n if n else baseline
        weight = n / (n + 30.0)
        return baseline * (1.0 - weight) + empirical * weight, n

    batters = defaultdict(lambda: {"name": "", "team": "", "pa": 0, "wpa": 0.0})
    pitchers = defaultdict(lambda: {"name": "", "team": "", "pa": 0, "wpa": 0.0})
    for index, item in enumerate(prepared):
        row = item["row"]
        before, sample = estimate(item["inning"], item["top_bottom"], item["home_score"] - item["away_score"], item["outs_before"], item["bases"])
        same_half = index + 1 < len(prepared) and prepared[index + 1]["row"].get("game_id") == row.get("game_id") and prepared[index + 1]["row"].get("inning") == row.get("inning") and prepared[index + 1]["row"].get("top_bottom") == row.get("top_bottom")
        if same_half:
            nxt = prepared[index + 1]
            after, _ = estimate(item["inning"], item["top_bottom"], item["after_home"] - item["after_away"], integer(row.get("outs")), nxt["bases"])
        else:
            next_inning = item["inning"] if item["top_bottom"] == "表" else item["inning"] + 1
            next_half = "裏" if item["top_bottom"] == "表" else "表"
            game = game_map.get(str(row.get("game_id")), {})
            is_last = index + 1 >= len(prepared) or prepared[index + 1]["row"].get("game_id") != row.get("game_id")
            if is_last:
                after = 1.0 if game.get("winner") == item["home"] else (0.0 if game.get("winner") == item["away"] else 0.5)
            else:
                after, _ = estimate(next_inning, next_half, item["after_home"] - item["after_away"], 0, "---")
        batting_home = row.get("batting_team") == item["home"]
        value = (after - before) if batting_home else (before - after)
        bk = row.get("batter_key") or row.get("batter")
        pk = row.get("pitcher_key") or row.get("pitcher")
        if bk:
            b = batters[bk]; b.update({"player_key": bk, "name": row.get("batter") or "", "team": row.get("batting_team") or ""}); b["pa"] += 1; b["wpa"] += value
        if pk:
            p = pitchers[pk]; p.update({"player_key": pk, "name": row.get("pitcher") or "", "team": row.get("fielding_team") or ""}); p["pa"] += 1; p["wpa"] -= value
    def finish(pool):
        result = []
        for item in pool.values():
            item = dict(item); item["wpa"] = round(item["wpa"], 3)
            result.append(item)
        return sorted(result, key=lambda x: x["wpa"], reverse=True)
    table = [{"key": key, "sample": exact_counts[key], "home_win_rate": round(exact_wins[key] / exact_counts[key], 3)} for key in exact_counts]
    return {"batters": finish(batters), "pitchers": finish(pitchers), "state_samples": table, "model_prior": "ロジスティック事前分布＋同一状況30件相当で縮小"}


def build_condition_cube(atbats):
    cells = defaultdict(lambda: defaultdict(int))
    for rows in _group_halves(atbats).values():
        previous_outs = 0
        for row in rows:
            inning = _inning_number(row)
            inning_group = "1-3" if inning <= 3 else ("4-6" if inning <= 6 else ("7-9" if inning <= 9 else "10+"))
            runners = "得点圏" if truthy(row.get("r2")) or truthy(row.get("r3")) else ("走者あり" if truthy(row.get("r1")) else "走者なし")
            key = (
                row.get("batting_team") or "不明", row.get("bat_hand") or "不明",
                row.get("pit_hand") or "不明", inning_group, runners,
                str(max(0, min(2, previous_outs))),
                "ホーム" if row.get("batting_team") == row.get("home") else "ビジター",
            )
            cell = cells[key]
            for field in ("pa", "ab", "hit", "single", "double", "triple", "hr", "bb", "hbp", "so", "rbi"):
                cell[field] += integer(row.get(field))
            previous_outs = integer(row.get("outs"), previous_outs)
    result = []
    names = ("team", "bat_hand", "pit_hand", "inning", "runners", "outs", "home_away")
    for key, stats in cells.items():
        row = dict(zip(names, key)); row.update(stats); result.append(row)
    return result


def _mean_sd(values):
    if not values:
        return 0.0, 1.0
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return mean, math.sqrt(variance) or 1.0


def build_similarity(players):
    configs = {
        "batter": ("batting", "pa", 50, ["avg", "obp", "slg", "iso", "bb_pct", "k_pct", "babip", "bsr_est"]),
        "pitcher": ("pitching", "outs", 30, ["era", "whip", "k9", "bb9", "hr9", "k_pct", "bb_pct", "lob_pct_est"]),
    }
    output = {}
    for kind, (section, volume, minimum, fields) in configs.items():
        eligible = [p for p in players if p.get(section) and number(p[section].get(volume)) >= minimum]
        usable = {field: [number(p[section].get(field)) for p in eligible if p[section].get(field) is not None] for field in fields}
        scales = {field: _mean_sd(values) for field, values in usable.items()}
        vectors = {}
        for player in eligible:
            if sum(player[section].get(field) is not None for field in fields) < max(4, len(fields) - 2):
                continue
            vectors[player.get("key")] = [
                (number(player[section].get(field), scales[field][0]) - scales[field][0]) / scales[field][1]
                for field in fields
            ]
        rows = []
        for player in eligible:
            key = player.get("key")
            if key not in vectors:
                continue
            distances = []
            for other in eligible:
                other_key = other.get("key")
                if other_key == key or other_key not in vectors:
                    continue
                distance = math.sqrt(sum((a - b) ** 2 for a, b in zip(vectors[key], vectors[other_key])) / len(fields))
                distances.append((distance, other))
            distances.sort(key=lambda x: x[0])
            rows.append({
                "player_key": key, "name": player.get("name"), "team": player.get("team"),
                "sample": player[section].get(volume),
                "similar": [{"player_key": x[1].get("key"), "name": x[1].get("name"), "team": x[1].get("team"), "score": round(100 * math.exp(-x[0]), 1)} for x in distances[:5]],
            })
        output[kind] = {"fields": fields, "minimum": minimum, "players": rows}
    return output


def _rate_batting(lines):
    ab = sum(integer(x.get("ab")) for x in lines)
    hits = sum(integer(x.get("hits")) for x in lines)
    bb = sum(integer(x.get("bb")) for x in lines)
    hbp = sum(integer(x.get("hbp")) for x in lines)
    sac = sum(integer(x.get("sac")) for x in lines)
    tb = sum(integer(x.get("singles")) + 2 * integer(x.get("doubles")) + 3 * integer(x.get("triples")) + 4 * integer(x.get("hr")) for x in lines)
    obp = (hits + bb + hbp) / (ab + bb + hbp + sac) if ab + bb + hbp + sac else None
    slg = tb / ab if ab else None
    return (obp + slg) if obp is not None and slg is not None else None, ab + bb + hbp + sac


def build_backtest(batting_lines, pitching_lines):
    dates = sorted({x.get("date") for x in batting_lines if x.get("date")})
    cutoff = dates[max(0, int(len(dates) * 0.7) - 1)] if dates else None
    train_all = [x for x in batting_lines if cutoff and x.get("date") <= cutoff]
    league_ops, _ = _rate_batting(train_all)
    by_batter = defaultdict(list)
    for row in batting_lines:
        by_batter[row.get("player_key") or row.get("player")].append(row)
    batter_rows = []
    for key, lines in by_batter.items():
        train = [x for x in lines if x.get("date") <= cutoff]
        test = [x for x in lines if x.get("date") > cutoff]
        train_ops, train_pa = _rate_batting(train); actual, test_pa = _rate_batting(test)
        if train_ops is None or actual is None or train_pa < 50 or test_pa < 20:
            continue
        prediction = (train_ops * train_pa + league_ops * 100) / (train_pa + 100)
        batter_rows.append({"player_key": key, "name": lines[-1].get("player"), "team": lines[-1].get("team"), "train_pa": train_pa, "test_pa": test_pa, "prediction": round(prediction, 3), "actual": round(actual, 3), "error": round(abs(prediction - actual), 3)})

    def pitching_rate(lines):
        outs = sum(integer(x.get("outs")) for x in lines); er = sum(integer(x.get("earned_runs")) for x in lines)
        return (er * 27 / outs if outs else None), outs
    train_pitch = [x for x in pitching_lines if cutoff and x.get("date") <= cutoff]
    league_era, _ = pitching_rate(train_pitch)
    by_pitcher = defaultdict(list)
    for row in pitching_lines:
        by_pitcher[row.get("player_key") or row.get("player")].append(row)
    pitcher_rows = []
    for key, lines in by_pitcher.items():
        train = [x for x in lines if x.get("date") <= cutoff]; test = [x for x in lines if x.get("date") > cutoff]
        train_era, train_outs = pitching_rate(train); actual, test_outs = pitching_rate(test)
        if train_era is None or actual is None or train_outs < 60 or test_outs < 30:
            continue
        prediction = (train_era * train_outs + league_era * 90) / (train_outs + 90)
        pitcher_rows.append({"player_key": key, "name": lines[-1].get("player"), "team": lines[-1].get("team"), "train_innings": round(train_outs / 3, 1), "test_innings": round(test_outs / 3, 1), "prediction": round(prediction, 2), "actual": round(actual, 2), "error": round(abs(prediction - actual), 2)})

    def summary(rows):
        return {"players": len(rows), "mae": round(sum(x["error"] for x in rows) / len(rows), 3) if rows else None}
    return {"cutoff": cutoff, "method": "シーズン日付70%で時間分割。選手実績をリーグ平均100打席/30回相当へ縮小", "batters": sorted(batter_rows, key=lambda x: x["error"]), "pitchers": sorted(pitcher_rows, key=lambda x: x["error"]), "summary": {"batting_ops": summary(batter_rows), "pitching_era": summary(pitcher_rows)}}


def _age_on_july_first(birthdate, season):
    try:
        born = date.fromisoformat(str(birthdate))
    except (TypeError, ValueError):
        return None
    return season - born.year - (1 if (born.month, born.day) > (7, 1) else 0)


def _innings(value):
    text = str(value or "0")
    whole, _, fraction = text.partition(".")
    return integer(whole) + integer(fraction) / 3


def build_aging(profiles):
    bat_age = defaultdict(lambda: {"pa": 0, "ops_sum": 0.0, "players": set()})
    pit_age = defaultdict(lambda: {"ip": 0.0, "era_sum": 0.0, "players": set()})
    careers = []
    for profile in profiles:
        series_b, series_p = [], []
        for row in profile.get("yearly_batting") or []:
            season = integer(row.get("year")); age = _age_on_july_first(profile.get("birthdate"), season)
            pa = integer(row.get("plate_appearances")); obp = row.get("on_base_percentage"); slg = row.get("slugging_percentage")
            if age is None or pa <= 0 or obp is None or slg is None: continue
            ops = number(obp) + number(slg); series_b.append({"year": season, "age": age, "team": row.get("team"), "pa": pa, "ops": round(ops, 3)})
            if pa >= 50:
                bat_age[age]["pa"] += pa; bat_age[age]["ops_sum"] += ops * pa; bat_age[age]["players"].add(profile.get("npb_id"))
        for row in profile.get("yearly_pitching") or []:
            season = integer(row.get("year")); age = _age_on_july_first(profile.get("birthdate"), season); ip = _innings(row.get("innings")); era = row.get("era")
            if age is None or ip <= 0 or era is None: continue
            series_p.append({"year": season, "age": age, "team": row.get("team"), "innings": round(ip, 1), "era": round(number(era), 2)})
            if ip >= 10:
                pit_age[age]["ip"] += ip; pit_age[age]["era_sum"] += number(era) * ip; pit_age[age]["players"].add(profile.get("npb_id"))
        if len(series_b) >= 2 or len(series_p) >= 2:
            careers.append({"npb_id": profile.get("npb_id"), "name": profile.get("name"), "team": profile.get("team"), "birthdate": profile.get("birthdate"), "batting": series_b, "pitching": series_p})
    batting_curve = [{"age": age, "players": len(v["players"]), "pa": v["pa"], "ops": round(v["ops_sum"] / v["pa"], 3)} for age, v in sorted(bat_age.items()) if len(v["players"]) >= 3]
    pitching_curve = [{"age": age, "players": len(v["players"]), "innings": round(v["ip"], 1), "era": round(v["era_sum"] / v["ip"], 2)} for age, v in sorted(pit_age.items()) if len(v["players"]) >= 3]
    return {"age_definition": "各年度7月1日時点の満年齢", "batting_curve": batting_curve, "pitching_curve": pitching_curve, "careers": careers}


def build_quality(games, atbats, pitches, batting_lines, pitching_lines):
    def coverage(rows, fields):
        total = len(rows)
        return {field: round(sum(row.get(field) not in (None, "") for row in rows) * 100 / total, 1) if total else 0.0 for field in fields}
    dates = sorted({x.get("date") for x in games if x.get("date")})
    return {
        "range": {"start": dates[0] if dates else None, "end": dates[-1] if dates else None},
        "counts": {"games": len(games), "atbats": len(atbats), "pitches": len(pitches), "batting_lines": len(batting_lines), "pitching_lines": len(pitching_lines)},
        "coverage_pct": {
            "games": coverage(games, ["home_score", "away_score", "winner", "stadium"]),
            "atbats": coverage(atbats, ["batter_id", "pitcher_id", "result", "outs", "r1", "r2", "r3"]),
            "pitches": coverage(pitches, ["pitch_type", "speed_kmh", "zone_row", "zone_col", "pitch_result"]),
        },
        "warnings": [
            "RE24の得点は打席結果の得点表記と打点の大きい方を使用。暴投など打席途中の得点は取りこぼす可能性があります。",
            "WPAはNPB公式値ではなく、当サイト収集試合から作った縮小推定モデルです。",
            "予測は将来保証ではなく時系列ホールドアウトによる検証値です。",
            "年齢曲線は現在の選手プロフィールに載る現役選手の過去成績が対象で、引退選手を含まない生存者バイアスがあります。",
        ],
    }
