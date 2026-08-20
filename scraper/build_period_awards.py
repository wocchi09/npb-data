"""
週間・月間MVP・ベストメンバーの算出
=====================================
dataset/batting_lines.csv・pitching_lines.csv（1選手1試合の記録）を
期間で束ねて集計する。日刊のように打席を1球ずつ追う必要が無いぶん軽い。

  週間: 月曜0時〜日曜23:59（仕様書9章）。週の途中は月曜〜最新試合日で暫定集計
  月間: 1日〜末日（仕様書に無い区分だが、同じ考え方で追加）

保存先:
  data/{season}/awards/weekly/{月曜日の日付}.json
  data/{season}/awards/monthly/{YYYY-MM}.json

使い方:
    python scraper/build_period_awards.py --season 2026
    python scraper/build_period_awards.py --season 2026 --kind weekly
    python scraper/build_period_awards.py --season 2026 --kind monthly
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.awards import (
    aggregate_batter_period, aggregate_pitcher_period, load_config,
    score_weekly_batter, score_weekly_closer, score_weekly_reliever,
    score_weekly_starter,
)
from lib.normalize import normalize_team, team_info

JST = timezone(timedelta(hours=9))


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def num(v, cast=int):
    try:
        return cast(v)
    except (TypeError, ValueError):
        return 0


def bool_(v):
    return str(v).strip().lower() == "true"


def week_monday(date_str):
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")


def week_range(monday):
    d = datetime.strptime(monday, "%Y-%m-%d")
    sunday = d + timedelta(days=6)
    return monday, sunday.strftime("%Y-%m-%d")


def month_range(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    start = f"{y:04d}-{m:02d}-01"
    if m == 12:
        end = f"{y+1:04d}-01-01"
    else:
        end = f"{y:04d}-{m+1:02d}-01"
    end = (datetime.strptime(end, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    return start, end


def _team_games_map(season, base, date_from=None, date_to=None):
    """対象期間内のチーム試合数。期間表彰でシーズン累計を使わない。"""
    rows = read_csv(f"{base}/{season}/dataset/games.csv")
    if date_from and date_to:
        rows = [r for r in rows if date_from <= r.get("date", "") <= date_to]
    out = {}
    for row in rows:
        for field in ("home", "away"):
            team = normalize_team(row.get(field))
            if team and team != "引分":
                out[team] = out.get(team, 0) + 1
    if out:
        return out

    # 旧データセット向けフォールバック。
    path = f"{base}/{season}/teams/stats.json"
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return {
            t["team"]: t.get("games") or 0
            for t in json.load(f).get("teams", []) if t.get("team")
        }


def _positions_map(season, base):
    """選手の主守備位置（players/stats.json から）"""
    path = f"{base}/{season}/players/stats.json"
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        players = json.load(f).get("players", [])
    out = {}
    for p in players:
        if p.get("name"):
            out[p["name"]] = p.get("position")
    return out


def build_period(kind, label, date_from, date_to, season, base="data", cfg=None):
    cfg = cfg or load_config()
    bl = read_csv(f"{base}/{season}/dataset/batting_lines.csv")
    pl = read_csv(f"{base}/{season}/dataset/pitching_lines.csv")
    bl = [r for r in bl if date_from <= r.get("date", "") <= date_to]
    pl = [r for r in pl if date_from <= r.get("date", "") <= date_to]
    if not bl and not pl:
        return None

    team_games = _team_games_map(season, base, date_from, date_to)
    positions = _positions_map(season, base)

    # --- 選手ごとにグループ化 ---
    def group(rows, key_field="player_key"):
        g = {}
        for r in rows:
            k = r.get(key_field) or r.get("player") or ""
            g.setdefault(k, []).append(r)
        return g

    bat_g = group(bl)
    pit_g = group(pl)

    # 打者を数値化して期間集計
    bat_aggs = {}
    for k, rows in bat_g.items():
        first = rows[0]
        team = normalize_team(first.get("team"))
        numeric = [{
            "ab": num(r.get("ab")), "hits": num(r.get("hits")),
            # 新形式は各長打列を持つ。旧CSVを読む場合だけ、残りを単打として補う。
            "singles": (num(r.get("singles"))
                        if r.get("singles") not in (None, "")
                        else max(0, num(r.get("hits")) - num(r.get("doubles"))
                                 - num(r.get("triples")) - num(r.get("hr")))),
            "doubles": num(r.get("doubles")),
            "triples": num(r.get("triples")), "hr": num(r.get("hr")),
            "bb": num(r.get("bb")), "hbp": num(r.get("hbp")),
            "sac": num(r.get("sac")), "so": num(r.get("so")),
            "rbi": num(r.get("rbi")), "runs": num(r.get("runs")), "sb": num(r.get("sb")),
            "caught_stealing": num(r.get("caught_stealing")),
            "baserunning_outs": num(r.get("baserunning_outs")),
            "baserunning_runs": num(r.get("baserunning_runs")),
            "errors": num(r.get("errors")), "is_starter": bool_(r.get("is_starter")),
        } for r in rows]
        agg = aggregate_batter_period(numeric)
        bat_aggs[k] = {"name": first.get("player"), "team": team,
                       "position": positions.get(first.get("player")), "agg": agg}

    pit_aggs = {}
    for k, rows in pit_g.items():
        first = rows[0]
        team = normalize_team(first.get("team"))
        starts = sum(1 for r in rows if bool_(r.get("is_starter")))
        numeric = [{
            "outs": num(r.get("outs")), "earned_runs": num(r.get("earned_runs")),
            "runs_allowed": num(r.get("runs_allowed")), "so": num(r.get("so")),
            "bb": num(r.get("bb")), "hits_allowed": num(r.get("hits_allowed")),
            "hr_allowed": num(r.get("hr_allowed")), "decision": r.get("decision") or "",
            "is_starter": bool_(r.get("is_starter")),
        } for r in rows]
        agg = aggregate_pitcher_period(numeric)
        starter_agg = aggregate_pitcher_period([r for r in numeric if r["is_starter"]])
        relief_agg = aggregate_pitcher_period([r for r in numeric if not r["is_starter"]])
        role = "先発" if starts >= len(rows) / 2 and starts > 0 else None
        pit_aggs[k] = {"name": first.get("player"), "team": team, "starts": starts,
                       "games": len(rows), "agg": agg, "starter_agg": starter_agg,
                       "relief_agg": relief_agg, "role_hint": role}

    result = {"awardType": kind, "label": label, "date_from": date_from, "date_to": date_to,
              "scoreVersion": cfg.get("periodScoreVersion", cfg.get("scoreVersion")),
              "generated_at": datetime.now(JST).isoformat(),
              "note": (
                  "利用可能データのみで算出。期間内のチーム試合数を基準に、"
                  "野手は試合数・打席、投手は登板数・投球回で出場量補正"
              ),
              "leagues": {}}

    for lg in ("セ", "パ"):
        lg_bat = [v for v in bat_aggs.values() if team_info(v["team"]).get("league") == lg]
        lg_pit = [v for v in pit_aggs.values() if team_info(v["team"]).get("league") == lg]
        pool = [v["agg"] for v in lg_bat]

        scored = []
        for v in lg_bat:
            tg = team_games.get(v["team"])
            s = score_weekly_batter(v["name"], v["team"], v["position"], v["agg"], pool, tg, cfg)
            scored.append(s)
        scored.sort(key=lambda x: -x["score"])

        # 投手：先発／中継ぎ／抑え に振り分ける。期間中に役割が混在した
        # 選手も、先発評価には先発登板だけ、救援評価には救援登板だけを使う。
        starters, relievers, closers = [], [], []
        starter_values = [
            v for v in lg_pit
            if v["role_hint"] == "先発"
            or v["starts"] >= max(v["games"] - v["starts"], 1)
        ]
        relief_values = [v for v in lg_pit if v not in starter_values]
        closer_values = [v for v in relief_values if v["relief_agg"]["saves"] > 0]
        middle_values = [v for v in relief_values if v not in closer_values]
        starter_pool = [v["starter_agg"] for v in starter_values]
        reliever_pool = [v["relief_agg"] for v in middle_values]
        closer_pool = [v["relief_agg"] for v in closer_values]

        for v in starter_values:
            agg = v["starter_agg"]
            starters.append(score_weekly_starter(
                v["name"], v["team"], agg, starter_pool, cfg, team_games.get(v["team"])
            ))
        for v in closer_values:
            agg = v["relief_agg"]
            closers.append(score_weekly_closer(
                v["name"], v["team"], agg, closer_pool, cfg, team_games.get(v["team"])
            ))
        for v in middle_values:
            agg = v["relief_agg"]
            relievers.append(score_weekly_reliever(
                v["name"], v["team"], agg, reliever_pool, cfg, team_games.get(v["team"])
            ))
        starters.sort(key=lambda x: -x["score"])
        relievers.sort(key=lambda x: -x["score"])
        closers.sort(key=lambda x: -x["score"])
        all_p = starters + relievers + closers
        all_p.sort(key=lambda x: -x["score"])

        best, used = {}, set()
        for pos in cfg["best_member_positions"].get(lg, []):
            cand = [b for b in scored if (b.get("position") or "").startswith(pos)
                    and b["name"] not in used]
            if cand:
                best[pos] = cand[0]
                used.add(cand[0]["name"])

        result["leagues"][lg] = {
            "batter_mvp": scored[0] if scored else None,
            "pitcher_mvp": all_p[0] if all_p else None,
            "best_batters": best,
            "best_pitchers": {
                "先発": starters[0] if starters else None,
                "中継ぎ": relievers[0] if relievers else None,
                "抑え": closers[0] if closers else None,
            },
            "batter_ranking": scored[:15],
            "pitcher_ranking": {"先発": starters[:10], "中継ぎ": relievers[:10], "抑え": closers[:10]},
        }

    return result


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def all_weeks(season, base):
    """収集済みデータから、対象となる週（月曜日）の一覧を作る"""
    cal_path = f"{base}/{season}/calendar.json"
    if not os.path.exists(cal_path):
        return []
    with open(cal_path, encoding="utf-8") as f:
        days = list(json.load(f).get("days", {}).keys())
    return sorted({week_monday(d) for d in days})


def all_months(season, base):
    cal_path = f"{base}/{season}/calendar.json"
    if not os.path.exists(cal_path):
        return []
    with open(cal_path, encoding="utf-8") as f:
        days = list(json.load(f).get("days", {}).keys())
    return sorted({d[:7] for d in days})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--kind", choices=["weekly", "monthly", "both"], default="both")
    ap.add_argument("--base", default="data")
    args = ap.parse_args()
    cfg = load_config()

    made = 0
    if args.kind in ("weekly", "both"):
        for monday in all_weeks(args.season, args.base):
            start, end = week_range(monday)
            r = build_period("weekly", f"{start}〜{end}", start, end, args.season, args.base, cfg)
            if not r:
                continue
            save_json(f"{args.base}/{args.season}/awards/weekly/{monday}.json", r)
            made += 1
            for lg in ("セ", "パ"):
                b = r["leagues"][lg]["batter_mvp"]
                if b:
                    print(f"  週{monday} {lg}・野手MVP {b['name']}（{b['team']}）{b['score']}点")

    if args.kind in ("monthly", "both"):
        for ym in all_months(args.season, args.base):
            start, end = month_range(ym)
            r = build_period("monthly", ym, start, end, args.season, args.base, cfg)
            if not r:
                continue
            save_json(f"{args.base}/{args.season}/awards/monthly/{ym}.json", r)
            made += 1
            for lg in ("セ", "パ"):
                b = r["leagues"][lg]["batter_mvp"]
                if b:
                    print(f"  月{ym} {lg}・野手MVP {b['name']}（{b['team']}）{b['score']}点")

    print(f"[INFO] 期間表彰を{made}件作成しました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
