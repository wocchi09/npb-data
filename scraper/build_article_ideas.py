"""Build compact, source-traceable story ideas for NPB ARTICLE LAB.

Output: data/{season}/_article_ideas.json

The browser reads only this compact artifact.  Every displayed number is copied from
an existing aggregate or calculated from collected CSV rows; missing values are never
invented.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

try:
    from scraper.build_story_insights import aggregate_batting, aggregate_pitching, build as build_story, integer, load_csv, num
    from scraper.lib.pitch_metrics import summarize_batter_pitches, summarize_pitcher_pitches, truthy
except ModuleNotFoundError:  # Direct execution: python scraper/build_article_ideas.py
    from build_story_insights import aggregate_batting, aggregate_pitching, build as build_story, integer, load_csv, num
    from lib.pitch_metrics import summarize_batter_pitches, summarize_pitcher_pitches, truthy

JST = timezone(timedelta(hours=9))
HAWKS = "ソフトバンク"
PACIFIC = {"ソフトバンク", "日本ハム", "オリックス", "楽天", "西武", "ロッテ"}
TYPE_LABELS = {"game": "試合", "player": "選手", "trend": "トレンド"}


def read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def rounded(value, digits=3):
    return None if value is None else round(float(value), digits)


def format_rate(value, digits=3):
    if value is None:
        return "データ不足"
    return f"{float(value):.{digits}f}".lstrip("0")


def format_signed(value, digits=3):
    if value is None:
        return "データ不足"
    return f"{float(value):+.{digits}f}"


def record_text(record):
    if not record:
        return "データ不足"
    return f"{integer(record.get('wins'))}勝{integer(record.get('losses'))}敗{integer(record.get('ties'))}分"


def source(dataset, date=None, game_id=None, fields=None, note=None):
    item = {"dataset": dataset}
    if date:
        item["date"] = date
    if game_id:
        item["game_id"] = str(game_id)
    if fields:
        item["fields"] = fields
    if note:
        item["note"] = note
    return item


def fact(label, value, metric, raw_value, src):
    return {"label": label, "value": value, "metric": metric, "raw_value": raw_value, "source": src}


def pitch_rows_for(rows, *, game_ids=None, pitcher_key=None, pitcher_name=None,
                   batter_key=None, batting_team=None, fielding_team=None):
    game_ids = {str(value) for value in (game_ids or []) if value not in (None, "")}
    selected = []
    for row in rows or []:
        if game_ids and str(row.get("game_id") or "") not in game_ids:
            continue
        if pitcher_key and str(row.get("pitcher_key") or row.get("pitcher_id") or "") != str(pitcher_key):
            continue
        if pitcher_name and str(row.get("pitcher") or "") != str(pitcher_name):
            continue
        if batter_key and str(row.get("batter_key") or row.get("batter_id") or "") != str(batter_key):
            continue
        if batting_team and row.get("batting_team") != batting_team:
            continue
        if fielding_team and row.get("fielding_team") != fielding_team:
            continue
        selected.append(row)
    return selected


def pitch_source(summary, fields, note=None):
    start = summary.get("date_start")
    end = summary.get("date_end")
    date = start if start == end else (f"{start}〜{end}" if start and end else start or end)
    game_ids = summary.get("game_ids") or []
    return source("pitches.csv", date, ",".join(game_ids) or None, fields, note)


def format_mix(items):
    return "、".join(
        f"{item['pitch_type']} {integer(item.get('pitches'))}球（{num(item.get('share')) * 100:.1f}%）"
        for item in items or []
        if item.get("pitch_type") and integer(item.get("pitches")) > 0
    )


def pitcher_pitch_facts(summary, label_prefix="投手"):
    if not summary:
        return [], [], []
    fields = ["pitcher_key", "pitch_type", "speed_kmh", "strikes_before", "in_zone", "is_last_pitch", "ab_result", "ab_out_type"]
    src = pitch_source(summary, fields)
    facts = [
        fact(f"{label_prefix}の投球数", f"{integer(summary.get('pitches'))}球", "pitch_count", summary.get("pitches"), src)
    ]
    mix = format_mix(summary.get("pitch_mix"))
    if mix:
        facts.append(fact(f"{label_prefix}の球種構成", mix, "pitch_mix", summary.get("pitch_mix"), src))
    fastball = summary.get("fastball") or {}
    if fastball.get("avg_speed_kmh") is not None and fastball.get("max_speed_kmh") is not None:
        facts.append(fact(
            "ストレート球速",
            f"平均{fastball['avg_speed_kmh']:.1f}km/h / 最速{fastball['max_speed_kmh']:.1f}km/h",
            "fastball_velocity", fastball, src,
        ))
    finishers = summary.get("strikeout_finish_by_pitch") or []
    finisher_text = "、".join(f"{row['pitch_type']} {integer(row.get('strikeouts'))}個" for row in finishers)
    if finisher_text:
        facts.append(fact("奪三振の決め球", finisher_text, "strikeout_finish_pitches", finishers, src))
    elif summary.get("strikeout_finishes") == 0:
        facts.append(fact("奪三振の決め球", "三振決着なし", "strikeout_finish_pitches", [], src))
    two_strike_mix = format_mix(summary.get("two_strike_mix"))
    if two_strike_mix:
        facts.append(fact(
            "2ストライク時の球種構成",
            f"計{integer(summary.get('two_strike_pitches'))}球：{two_strike_mix}",
            "two_strike_pitch_mix", summary.get("two_strike_mix"), src,
        ))
    if integer(summary.get("zone_seen")):
        facts.append(fact(
            "ゾーン内・外",
            f"ゾーン内 {num(summary.get('in_zone_rate')) * 100:.1f}% / 外 {num(summary.get('out_zone_rate')) * 100:.1f}%（判定{integer(summary.get('zone_seen'))}球）",
            "zone_rate", [summary.get("in_zone_rate"), summary.get("out_zone_rate"), summary.get("zone_seen")], src,
        ))
    cautions = []
    if integer(summary.get("pitches")) < 50:
        cautions.append(f"{label_prefix}のpitch集計は{integer(summary.get('pitches'))}球の小標本")
    return facts, cautions, [src]


def batter_pitch_facts(summary, label_prefix="打撃"):
    if not summary:
        return [], [], []
    fields = ["batter_key", "batting_team", "pitch_type", "is_swing", "is_miss", "is_called", "is_last_pitch", "ab_result", "ab_hit"]
    src = pitch_source(summary, fields)
    facts = []
    mix = format_mix(summary.get("pitch_mix"))
    if mix:
        facts.append(fact(
            f"{label_prefix}で見た球種",
            f"計{integer(summary.get('pitches_seen'))}球：{mix}",
            "pitches_seen_mix", summary.get("pitch_mix"), src,
        ))
    rates = []
    if summary.get("whiff_rate") is not None:
        rates.append(f"空振り率 {num(summary.get('whiff_rate')) * 100:.1f}%（空振り/スイング）")
    if summary.get("called_strike_rate") is not None:
        rates.append(f"見逃しストライク率 {num(summary.get('called_strike_rate')) * 100:.1f}%（見逃しストライク/非スイング）")
    if rates:
        facts.append(fact(
            "空振り・見逃し",
            " / ".join(rates),
            "swing_take_rates", [summary.get("whiff_rate"), summary.get("called_strike_rate")], src,
        ))
    results = summary.get("terminal_results_by_pitch") or []
    result_text = "、".join(
        f"{row['pitch_type']} {integer(row.get('pa'))}打席{integer(row.get('hits'))}安打"
        + (f"{integer(row.get('hr'))}本塁打" if integer(row.get("hr")) else "")
        + (f"{integer(row.get('strikeouts'))}三振" if integer(row.get("strikeouts")) else "")
        for row in results
    )
    if result_text:
        facts.append(fact("打席決着球種別", result_text, "terminal_results_by_pitch", results, src))
    cautions = []
    if integer(summary.get("pitches_seen")) < 30:
        cautions.append(f"{label_prefix}のpitch集計は{integer(summary.get('pitches_seen'))}球の小標本")
    return facts, cautions, [src]


def make_idea(*, idea_id, idea_type, team, title, theme, reason, facts, angles, cautions, source_refs, score):
    return {
        "id": idea_id,
        "type": idea_type,
        "type_label": TYPE_LABELS[idea_type],
        "team": team,
        "league": "パ" if team in PACIFIC else "セ",
        "scope": "hawks" if team == HAWKS else ("pacific" if team in PACIFIC else "all"),
        "title": title,
        "theme": theme,
        "reason": reason,
        "facts": facts,
        "angles": angles,
        "cautions": cautions,
        "source_refs": source_refs,
        "_score": score,
    }


def latest_hawks_game(story, data_date, pitching_lines=None, pitches=None):
    games = (story.get("latest_games") or {}).get("games") or []
    game = next((row for row in games if HAWKS in (row.get("home"), row.get("away"))), None)
    if not game:
        return None
    game_id = str(game.get("game_id") or "")
    opponent = game.get("away") if game.get("home") == HAWKS else game.get("home")
    hawks_score = integer(game.get("home_score") if game.get("home") == HAWKS else game.get("away_score"))
    opponent_score = integer(game.get("away_score") if game.get("home") == HAWKS else game.get("home_score"))
    result = "勝利" if hawks_score > opponent_score else ("敗戦" if hawks_score < opponent_score else "引き分け")
    offense = game.get("offense") if game.get("winner") == HAWKS else game.get("opponent_offense")
    offense = offense or {}
    hawks_pitching = [
        row for row in (pitching_lines or [])
        if str(row.get("game_id") or "") == game_id and row.get("team") == HAWKS
    ]
    starter_row = next((row for row in hawks_pitching if truthy(row.get("is_starter"))), None)
    starter = None
    if starter_row:
        starter = {
            "name": starter_row.get("player") or "-",
            "key": starter_row.get("player_key") or starter_row.get("player_id"),
            "innings": f"{integer(starter_row.get('outs')) // 3}.{integer(starter_row.get('outs')) % 3}",
            "outs": integer(starter_row.get("outs")),
            "earned_runs": integer(starter_row.get("earned_runs")),
            "runs_allowed": integer(starter_row.get("runs_allowed")),
            "so": integer(starter_row.get("so")),
            "bb": integer(starter_row.get("bb")),
            "hits_allowed": integer(starter_row.get("hits_allowed")),
            "pitches": integer(starter_row.get("pitches")),
        }
    elif game.get("winner") == HAWKS:
        starter = game.get("starter")
    bullpen = game.get("bullpen") if game.get("winner") == HAWKS else None
    src_game = source("games.csv", data_date, game_id, ["home_score", "away_score", "winner"])
    facts = [fact("試合結果", f"ソフトバンク {hawks_score}－{opponent_score} {opponent}", "score", [hawks_score, opponent_score], src_game)]
    if offense:
        facts.extend([
            fact("チーム安打", f"{integer(offense.get('hits'))}安打", "hits", integer(offense.get("hits")), source("batting_lines.csv", data_date, game_id, ["hits"])),
            fact("本塁打・四球", f"{integer(offense.get('hr'))}本塁打 / {integer(offense.get('bb'))}四球", "hr_bb", [integer(offense.get("hr")), integer(offense.get("bb"))], source("batting_lines.csv", data_date, game_id, ["hr", "bb"])),
        ])
    if starter:
        facts.append(fact("先発", f"{starter.get('name')} {starter.get('innings')}回 自責{integer(starter.get('earned_runs'))} 奪三振{integer(starter.get('so'))}", "starter_line", starter, source("pitching_lines.csv", data_date, game_id, ["player", "outs", "earned_runs", "so"])))
    if bullpen:
        facts.append(fact("救援陣", f"{bullpen.get('innings')}回 自責{integer(bullpen.get('earned_runs'))}", "bullpen_line", bullpen, source("pitching_lines.csv", data_date, game_id, ["outs", "earned_runs"])))
    pitch_cautions = []
    pitch_refs = []
    if starter:
        starter_rows = pitch_rows_for(
            pitches, game_ids=[game_id], pitcher_key=starter.get("key"),
            pitcher_name=None if starter.get("key") else starter.get("name"), fielding_team=HAWKS,
        )
        starter_summary = summarize_pitcher_pitches(starter_rows)
        extra, cautions, refs = pitcher_pitch_facts(starter_summary, "先発")
        facts.extend(extra); pitch_cautions.extend(cautions); pitch_refs.extend(refs)
    team_batting_rows = pitch_rows_for(pitches, game_ids=[game_id], batting_team=HAWKS)
    batting_summary = summarize_batter_pitches(team_batting_rows)
    extra, cautions, refs = batter_pitch_facts(batting_summary, "ホークス打線")
    facts.extend(extra); pitch_cautions.extend(cautions); pitch_refs.extend(refs)
    if result == "勝利":
        title = f"ホークスが{opponent}戦を{hawks_score}－{opponent_score}で勝利　数字から見えたポイント"
        reason = f"最新データ日のホークス戦は{result}。スコアだけで勝因を断定せず、打線・先発・救援のどこに目立つ数字があったかを整理できる。"
    else:
        title = f"ホークスの{opponent}戦を検証　{hawks_score}－{opponent_score}の数字から何が見える？"
        reason = f"最新データ日のホークス戦は{result}。結果だけでなく、打線・先発・救援の数字を分けて見ることで次戦への論点を探せる。"
    return make_idea(
        idea_id=f"hawks-game-{game_id}", idea_type="game", team=HAWKS, title=title,
        theme=f"{data_date}のホークス戦を、ボックススコアの事実から振り返る",
        reason=reason, facts=facts,
        angles=["得点と安打・四球の関係", "先発が作った試合展開", "救援陣が残した数字"],
        cautions=["勝因の因果推定ではなく、当日の集計値から目立つ要素を扱う", "守備位置や打球品質など未収集要素は評価しない", *pitch_cautions],
        source_refs=[src_game, source("batting_lines.csv", data_date, game_id), source("pitching_lines.csv", data_date, game_id), *pitch_refs], score=100,
    )


def team_trend_idea(trend, data_date, hawks=False):
    if not trend:
        return None
    team = trend.get("team")
    recent, season, delta = trend.get("recent") or {}, trend.get("season") or {}, trend.get("delta") or {}
    rr, sr = recent.get("record") or {}, season.get("record") or {}
    rb, sb = recent.get("batting") or {}, season.get("batting") or {}
    rp, sp = recent.get("pitching") or {}, season.get("pitching") or {}
    facts = [
        fact("直近10試合", record_text(rr), "recent_record", rr, source("games.csv", data_date, fields=["home", "away", "home_score", "away_score"])),
        fact("1試合平均得点", f"直近 {num(rr.get('runs_per_game')):.2f} / シーズン {num(sr.get('runs_per_game')):.2f}", "runs_per_game", [rr.get("runs_per_game"), sr.get("runs_per_game")], source("games.csv", data_date, fields=["home_score", "away_score"])),
        fact("OPS", f"直近 {format_rate(rb.get('ops'))} / シーズン {format_rate(sb.get('ops'))}", "ops", [rb.get("ops"), sb.get("ops")], source("batting_lines.csv", data_date, fields=["ab", "hits", "doubles", "triples", "hr", "bb", "hbp"])),
        fact("防御率", f"直近 {num(rp.get('era')):.2f} / シーズン {num(sp.get('era')):.2f}", "era", [rp.get("era"), sp.get("era")], source("pitching_lines.csv", data_date, fields=["outs", "earned_runs"])),
        fact("OPS変化", format_signed(delta.get("ops")), "ops_delta", delta.get("ops"), source("_story_insights.json", data_date)),
        fact("防御率変化", format_signed(delta.get("era"), 2), "era_delta", delta.get("era"), source("_story_insights.json", data_date)),
    ]
    wins = integer(rr.get("wins")); games = integer(rr.get("games"))
    ops_delta = num(delta.get("ops"), 0); era_delta = num(delta.get("era"), 0)
    mismatch = wins >= 6 and abs(ops_delta) < .025 and era_delta <= -.3
    if hawks and mismatch:
        title = "ホークスは本当に打線で勝っている？直近10試合を数字で確認"
        reason = f"直近10試合は{record_text(rr)}。一方、OPSはシーズン平均とほぼ同水準で、防御率は{abs(era_delta):.2f}改善している。勝敗と打撃指標が完全には一致しない点が記事の問いになる。"
        angles = ["勝率上昇とOPSが一致しているか", "防御率・失点ペースの変化", "得点増が長打以外から生まれている可能性"]
    else:
        title = f"{team}は直近10試合で何が変わった？シーズン平均と比較"
        change_text = "、".join(trend.get("changes") or [])
        reason = f"直近10試合は{record_text(rr)}。{change_text or '複数指標を比較すると変化の有無を確認できる'}。成績の良し悪しだけでなく、どの数字が動いたかを掘れる。"
        angles = ["勝敗と得点・失点の変化", "OPSと得点ペースの関係", "防御率と失点ペースの関係"]
    score = (35 if hawks else 0) + abs(ops_delta) * 180 + abs(era_delta) * 8 + abs(num(delta.get("runs_per_game"), 0)) * 4 + games
    return make_idea(
        idea_id=f"team-trend-{team}", idea_type="trend", team=team, title=title,
        theme=f"{team}の直近10試合をシーズン平均と比較する", reason=reason, facts=facts,
        angles=angles, cautions=["直近10試合の短期サンプル", "対戦相手・球場・日程の影響は未調整", "変化は原因を証明するものではない"],
        source_refs=[source("games.csv", data_date), source("batting_lines.csv", data_date), source("pitching_lines.csv", data_date), source("_story_insights.json", data_date)], score=score,
    )


def row_key(row):
    return str(row.get("player_key") or row.get("player_id") or row.get("player") or "")


def hawks_player_idea(games, batting, season_batting, pitches, data_date):
    hawks_games = sorted([g for g in games if HAWKS in (g.get("home"), g.get("away"))], key=lambda g: (g.get("date") or "", str(g.get("game_id") or "")))[-10:]
    game_ids = {str(g.get("game_id") or "") for g in hawks_games}
    groups = defaultdict(list)
    for row in batting:
        if row.get("team") == HAWKS and str(row.get("game_id") or "") in game_ids:
            groups[row_key(row)].append(row)
    season_map = {row_key(r): r for r in season_batting if r.get("team") == HAWKS}
    candidates = []
    for key, rows in groups.items():
        recent = aggregate_batting(rows); season = season_map.get(key)
        if not season or recent.get("pa", 0) < 20 or integer(season.get("pa")) < 80:
            continue
        recent_ops, season_ops = recent.get("ops"), num(season.get("ops"), None)
        if recent_ops is None or season_ops is None:
            continue
        delta = recent_ops - season_ops
        score = abs(delta) * 100 + min(recent.get("pa", 0), 45) / 10
        candidates.append((score, abs(delta), key, rows, recent, season, delta))
    if not candidates:
        return None
    _, _, key, rows, recent, season, delta = max(candidates)
    name = season.get("player") or rows[0].get("player") or "選手名不明"
    direction = "上がった" if delta >= 0 else "下がった"
    title = f"{name}の直近10試合で何が変わった？シーズン平均と比較"
    reason = f"直近のOPSは{format_rate(recent.get('ops'))}で、シーズンOPSから{format_signed(delta)}。短期の好不調を断定せず、安打・長打・四球・三振のどこが{direction}のかを確認できる。"
    recent_games = len({str(r.get("game_id") or "") for r in rows})
    facts = [
        fact("直近出場", f"{recent_games}試合 / {recent.get('pa')}打席", "recent_sample", [recent_games, recent.get("pa")], source("batting_lines.csv", data_date, fields=["game_id", "ab", "bb", "hbp", "sac"])),
        fact("直近OPS", format_rate(recent.get("ops")), "recent_ops", recent.get("ops"), source("batting_lines.csv", data_date)),
        fact("シーズンOPS", format_rate(season.get("ops")), "season_ops", num(season.get("ops"), None), source("season_batting.csv", data_date, fields=["ops"])),
        fact("OPS変化", format_signed(delta), "ops_delta", rounded(delta), source("batting_lines.csv + season_batting.csv", data_date)),
        fact("直近打撃", f"{recent.get('hits')}安打 {recent.get('hr')}本塁打 {recent.get('bb')}四球", "recent_events", [recent.get("hits"), recent.get("hr"), recent.get("bb")], source("batting_lines.csv", data_date, fields=["hits", "hr", "bb"])),
        fact("直近三振", f"{recent.get('so')}三振", "recent_so", recent.get("so"), source("batting_lines.csv", data_date, fields=["so"])),
    ]
    player_pitch_rows = pitch_rows_for(pitches, game_ids=game_ids, batter_key=key, batting_team=HAWKS)
    pitch_summary = summarize_batter_pitches(player_pitch_rows)
    pitch_facts, pitch_cautions, pitch_refs = batter_pitch_facts(pitch_summary, name)
    facts.extend(pitch_facts)
    return make_idea(
        idea_id=f"hawks-player-{key}", idea_type="player", team=HAWKS, title=title,
        theme=f"{name}の直近成績とシーズン成績の差を調べる", reason=reason, facts=facts,
        angles=["OPS変化を出塁と長打に分ける", "安打・本塁打・四球・三振の変化", "チームの得点や勝敗との同時期の動き"],
        cautions=["直近10試合の短期サンプル", "対戦投手・球場の影響は未調整", "OPSの変化だけで技術的原因は断定できない", *pitch_cautions],
        source_refs=[source("batting_lines.csv", data_date), source("season_batting.csv", data_date), *pitch_refs], score=85 + abs(delta) * 30,
    )


def hawks_two_strike_idea(story, pitches, data_date):
    quality = ((story.get("quality") or {}).get("two_strike") or {})
    if quality.get("definition_version") != 2 or not quality.get("validated"):
        return None
    candidates = [p for p in story.get("two_strike_pitchers") or [] if p.get("team") == HAWKS and integer(p.get("pitches")) >= 50]
    if not candidates:
        return None
    pitcher = max(candidates, key=lambda p: (integer(p.get("pitches")), num(p.get("k_finish_rate"))))
    name = pitcher.get("name") or "投手名不明"
    top = (pitcher.get("pitch_types") or [{}])[0]
    player_pitch_rows = pitch_rows_for(pitches, pitcher_key=pitcher.get("key"), fielding_team=HAWKS)
    pitch_summary = summarize_pitcher_pitches(player_pitch_rows)
    verified_src = (
        pitch_source(
            pitch_summary,
            ["pitcher_key", "pitch_type", "strikes_before", "is_last_pitch", "ab_result", "ab_out_type"],
            "_story_insights.jsonで検証済み定義により事前集計",
        )
        if pitch_summary
        else source("pitches.csv", data_date, fields=quality.get("source_fields"), note="pitch行が無いためgame_id特定不可")
    )
    facts = [
        fact("2ストライク後", f"{integer(pitcher.get('pitches'))}球", "two_strike_pitches", integer(pitcher.get("pitches")), verified_src),
        fact("三振決着球率", f"{num(pitcher.get('k_finish_rate')) * 100:.1f}%", "strikeout_finish_rate", pitcher.get("k_finish_rate"), verified_src),
        fact("空振り三振決着率", f"{num(pitcher.get('whiff_rate')) * 100:.1f}%", "swinging_strikeout_finish_rate", pitcher.get("whiff_rate"), verified_src),
        fact("最多球種", f"{top.get('pitch_type', 'データ不足')} {num(top.get('share')) * 100:.1f}%", "top_pitch", [top.get("pitch_type"), top.get("share")], verified_src),
    ]
    pitch_facts, pitch_cautions, pitch_refs = pitcher_pitch_facts(pitch_summary, name)
    facts.extend(pitch_facts)
    return make_idea(
        idea_id=f"hawks-two-strike-{pitcher.get('key')}", idea_type="player", team=HAWKS,
        title=f"{name}は追い込んでから何を投げている？2ストライク後の配球を検証",
        theme=f"{name}の2ストライク後の球種と三振決着を分析する",
        reason=f"2ストライク後を{integer(pitcher.get('pitches'))}球確認できる。最多球種と実際に三振で打席が終わった投球を分け、追い込んでからの傾向を記事にできる。",
        facts=facts, angles=["2ストライク後の球種構成", "三振決着に使われた球種", "右打者・左打者で配球が違うか"],
        cautions=["球種は収集データ上の分類", "三振決着は is_last_pitch・ab_out_type・ab_result を同時に確認", "配球傾向から意図や投球技術の原因は断定しない", *pitch_cautions],
        source_refs=[source("pitches.csv", data_date, fields=quality.get("source_fields")), source("_story_insights.json", data_date), *pitch_refs], score=80 + min(integer(pitcher.get("pitches")), 500) / 100,
    )


def build(season, base="data"):
    season = str(season); root = os.path.join(base, season); dataset = os.path.join(root, "dataset")
    output_path = os.path.join(root, "_article_ideas.json")
    os.makedirs(root, exist_ok=True)
    games = load_csv(os.path.join(dataset, "games.csv"))
    if not games:
        output = {"schema_version": 1, "season": season, "data_date": None, "generated_at": datetime.now(JST).isoformat(),
                  "status": "data_unavailable", "message": "収集済みの試合データがありません。", "ideas": []}
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(output, handle, ensure_ascii=False, separators=(",", ":"))
        print(f"[WARN] article ideas: no games ({dataset})")
        return output
    data_date = max(str(g.get("date") or "") for g in games if g.get("date"))
    story_path = os.path.join(root, "_story_insights.json")
    story = read_json(story_path)
    if not story or (story.get("latest_games") or {}).get("date") != data_date:
        story = build_story(season, base)
    batting = load_csv(os.path.join(dataset, "batting_lines.csv"))
    pitching = load_csv(os.path.join(dataset, "pitching_lines.csv"))
    pitches = load_csv(os.path.join(dataset, "pitches.csv"))
    season_batting = load_csv(os.path.join(dataset, "season_batting.csv"))
    ideas = []
    latest = latest_hawks_game(story, data_date, pitching, pitches)
    if latest:
        ideas.append(latest)
    trends = {row.get("team"): row for row in story.get("team_trends") or []}
    hawks_trend = team_trend_idea(trends.get(HAWKS), data_date, hawks=True)
    if hawks_trend:
        ideas.append(hawks_trend)
    player = hawks_player_idea(games, batting, season_batting, pitches, data_date)
    if player:
        ideas.append(player)
    pitch = hawks_two_strike_idea(story, pitches, data_date)
    if pitch:
        ideas.append(pitch)
    other_trends = [team_trend_idea(row, data_date) for row in trends.values() if row.get("team") in PACIFIC and row.get("team") != HAWKS]
    other_trends = [row for row in other_trends if row]
    for other in sorted(other_trends, key=lambda row: row["_score"], reverse=True):
        if len(ideas) >= 5:
            break
        ideas.append(other)
    # Keep the editorial mix stable: Hawks first (roughly 70–80%), then the strongest Pacific change.
    seen = set(); selected = []
    for row in ideas:
        if row["id"] in seen:
            continue
        seen.add(row["id"]); selected.append(row)
    selected = selected[:5]
    for rank, row in enumerate(selected, 1):
        row["rank"] = rank
        row.pop("_score", None)
    output = {
        "schema_version": 1, "season": season, "data_date": data_date,
        "generated_at": datetime.now(JST).isoformat(), "status": "ok",
        "selection_note": "最新の収集日を基準に、変化・不一致・問いが生まれる候補を優先。ホークス関連を中心に選定。",
        "source_summary": {"games": len(games), "batting_lines": len(batting), "pitching_lines": len(pitching), "pitches": len(pitches), "story_insights": os.path.basename(story_path)},
        "ideas": selected,
    }
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(output, handle, ensure_ascii=False, separators=(",", ":"))
    print(f"[INFO] article ideas: date={data_date} / ideas={len(selected)} / hawks={sum(1 for i in selected if i['team']==HAWKS)}")
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", required=True)
    parser.add_argument("--base", default="data")
    args = parser.parse_args()
    build(args.season, args.base)
    return 0


if __name__ == "__main__":
    sys.exit(main())
