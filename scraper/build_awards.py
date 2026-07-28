"""
日刊MVP・ベストメンバーの算出
================================
その日の全試合から、リーグごとに次を選ぶ。

  日刊野手MVP   … 野手総合点1位
  日刊投手MVP   … 先発・中継ぎ・抑えを役割内で標準化して比較（仕様書10章）
  日刊ベストメンバー … ポジションごとの1位＋投手3部門

結果は data/{season}/awards/daily/{date}.json に保存する。
スコアの内訳と選出理由も一緒に保存するので、あとから根拠を確認できる。

使い方:
    python scraper/build_awards.py --date 2026-07-25
    python scraper/build_awards.py --season 2026        # 収集済みの全日
"""

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.awards import (
    build_context, classify_pitcher_roles, load_config,
    score_daily_batter, score_daily_closer, score_daily_reliever,
    score_daily_starter,
)
from lib.events import classify_result
from lib.normalize import normalize_team, team_info

JST = timezone(timedelta(hours=9))

# 集計しない試合の種別（オールスター・CS・日本シリーズ）
EXCLUDED_TYPES = ("オールスター", "CS", "日本シリーズ")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def games_of_day(date, base="data"):
    y, m, d = date.split("-")
    out = []
    for p in sorted(glob.glob(f"{base}/{y}/{m}/{d}/*.json")):
        name = os.path.basename(p)
        if name.startswith("_"):
            continue
        try:
            g = load_json(p)
        except Exception as e:
            print(f"[WARN] 読み込み失敗 {p}: {e}")
            continue
        if (g.get("atbat_count") or 0) <= 0:
            continue
        if (g.get("game_type") or "公式戦") in EXCLUDED_TYPES:
            continue
        out.append(g)
    return out


# 役割内標準化を使う最少人数。これ未満だと標準偏差が意味を持たないため、
# 換算スコアをそのまま比較に使う（1試合だと各役割1〜2人しかいないことがある）
MIN_FOR_STANDARDIZE = 4


def standardize(items, key="raw"):
    """
    役割内で標準化する（仕様書10章）: 50 + 10×(値-平均)÷標準偏差

    ただし人数が少ないと標準偏差が0または不安定になり、
    成績が良い投手も悪い投手も同じ50点になってしまう。
    そのため人数が足りないときは換算スコアをそのまま使う。
    """
    n = len(items)
    if n == 0:
        return
    vals = [x[key] for x in items]
    avg = sum(vals) / n
    var = sum((v - avg) ** 2 for v in vals) / n
    sd = var ** 0.5

    if n < MIN_FOR_STANDARDIZE or sd == 0:
        for x in items:
            x["z"] = x["score"]          # 換算スコアで比較する
            x["z_method"] = "換算スコア"
        return
    for x in items:
        x["z"] = round(50 + 10 * (x[key] - avg) / sd, 2)
        x["z_method"] = "役割内標準化"


def _inning_weight(outs):
    """
    投手MVPを比べるときの投球回の重み。
    短いイニングの好投も評価しつつ、長いイニングを投げた投手を上に置く。
      1イニング(3アウト)=0.72 / 2イニング=0.80 / 5イニング=0.94 / 7イニング=1.0
    """
    if outs <= 0:
        return 0.0
    ip = outs / 3
    if ip >= 7:
        return 1.0
    return round(0.65 + 0.05 * ip, 3)


def make_comment(kind, x):
    """選出理由の文章を組み立てる"""
    good = "／".join(x.get("reasons") or [])
    if kind == "batter":
        head = x.get("stat_line", "")
        if good:
            return f"{head}。{good}を記録し、リーグ最高評価。"
        return f"{head}。打撃内容でリーグ最高評価。"
    head = x.get("stat_line", "")
    if good:
        return f"{head}。{good}。"
    return f"{head}。"


def build_daily(date, base="data", cfg=None):
    cfg = cfg or load_config()
    games = games_of_day(date, base)
    if not games:
        return None

    batters = {"セ": [], "パ": []}
    pitchers = {"セ": {"先発": [], "中継ぎ": [], "抑え": []},
                "パ": {"先発": [], "中継ぎ": [], "抑え": []}}

    for g in games:
        ctx = build_context(g, classify_result)
        box = g.get("boxscore") or {}

        # --- 野手 ---
        for side, team in (("away", g.get("away")), ("home", g.get("home"))):
            team = normalize_team(team)
            lg = team_info(team).get("league")
            if lg not in batters:
                continue
            for row in (box.get("batting") or {}).get(side) or []:
                row = dict(row)
                row["team"] = team
                if not row.get("name"):
                    continue
                s = score_daily_batter(row, ctx, cfg)
                s["game_id"] = g.get("game_id")
                s["opponent"] = normalize_team(
                    g.get("home") if side == "away" else g.get("away"))
                s["is_starter"] = row.get("is_starter")
                s["sub_type"] = row.get("sub_type")
                batters[lg].append(s)

        # --- 投手 ---
        for row, role, team in classify_pitcher_roles(g, ctx):
            team = normalize_team(team)
            lg = team_info(team).get("league")
            if lg not in pitchers:
                continue
            row["_team"] = team
            if role == "先発":
                s = score_daily_starter(row, ctx, cfg)
            elif role == "抑え":
                s = score_daily_closer(row, ctx, cfg)
            else:
                s = score_daily_reliever(row, ctx, cfg)
            s["game_id"] = g.get("game_id")
            pitchers[lg][role].append(s)

    result = {
        "awardType": "daily",
        "date": date,
        "scoreVersion": cfg.get("scoreVersion"),
        "generated_at": datetime.now(JST).isoformat(),
        "note": (
            "利用可能データのみで算出。盗塁成功・盗塁失敗・高確度の走塁死を反映し、"
            "取得できない守備の細目は対象外"
        ),
        "games": len(games),
        "leagues": {},
    }

    for lg in ("セ", "パ"):
        bs = sorted(batters[lg], key=lambda x: -x["score"])
        for role in ("先発", "中継ぎ", "抑え"):
            standardize(pitchers[lg][role])

        # 投手MVPは役割内標準化スコアで比較する。
        # ただし仕様書10章のとおり「投球回・試合結果への影響」も加味しないと、
        # 1イニングの抑えが7回を投げた先発を上回ってしまう。
        all_p = []
        for role in ("先発", "中継ぎ", "抑え"):
            all_p.extend(pitchers[lg][role])
        for x in all_p:
            outs = (x.get("keys") or {}).get("outs") or 0
            # 投球回による重み（3アウトで1.0、少ないほど控えめに評価する）
            x["mvp_value"] = round((x.get("z") or 0) * _inning_weight(outs), 2)
        all_p.sort(key=lambda x: (-x["mvp_value"], -x["score"]))

        # ベストメンバー（ポジションごとの1位。同じ選手は重複させない）
        best, used = {}, set()
        for pos in cfg["best_member_positions"].get(lg, []):
            cand = [b for b in bs
                    if (b.get("position") or "").startswith(pos)
                    and b["name"] not in used
                    and not (b.get("sub_type") in ("代打", "代走"))]
            if cand:
                best[pos] = cand[0]
                used.add(cand[0]["name"])

        best_p = {}
        for role in ("先発", "中継ぎ", "抑え"):
            lst = sorted(pitchers[lg][role], key=lambda x: -x["score"])
            if lst:
                best_p[role] = lst[0]

        mvp_b = bs[0] if bs else None
        mvp_p = all_p[0] if all_p else None
        if mvp_b:
            mvp_b = dict(mvp_b)
            mvp_b["comment"] = make_comment("batter", mvp_b)
            mvp_b["margin"] = round(mvp_b["score"] - bs[1]["score"], 2) if len(bs) > 1 else None
        if mvp_p:
            mvp_p = dict(mvp_p)
            mvp_p["comment"] = make_comment("pitcher", mvp_p)
            mvp_p["margin"] = (round((mvp_p.get("z") or 0) - (all_p[1].get("z") or 0), 2)
                               if len(all_p) > 1 else None)

        result["leagues"][lg] = {
            "batter_mvp": mvp_b,
            "pitcher_mvp": mvp_p,
            "best_batters": best,
            "best_pitchers": best_p,
            "batter_ranking": bs[:15],
            "pitcher_ranking": {r: sorted(pitchers[lg][r], key=lambda x: -x["score"])[:10]
                                for r in ("先発", "中継ぎ", "抑え")},
        }

    return result


def all_dates(season, base="data"):
    out = []
    for p in glob.glob(f"{base}/{season}/*/*/_summary.json"):
        m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/", p.replace("\\", "/"))
        if m:
            out.append(f"{m.group(1)}-{m.group(2)}-{m.group(3)}")
    return sorted(set(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="対象日 YYYY-MM-DD")
    ap.add_argument("--season", default=None, help="その年の収集済み全日を対象にする")
    ap.add_argument("--base", default="data")
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    cfg = load_config(args.config)

    dates = []
    if args.date:
        dates = [args.date]
    elif args.season:
        dates = all_dates(args.season, args.base)
    else:
        print("[ERROR] --date または --season を指定してください")
        return 1

    made = 0
    for d in dates:
        r = build_daily(d, args.base, cfg)
        if not r:
            continue
        season = d.split("-")[0]
        save_json(f"{args.base}/{season}/awards/daily/{d}.json", r)
        made += 1
        for lg in ("セ", "パ"):
            b = r["leagues"][lg]["batter_mvp"]
            p = r["leagues"][lg]["pitcher_mvp"]
            if b:
                print(f"  {d} {lg}・野手MVP {b['name']}（{b['team']}）{b['score']}点 "
                      f"— {b['stat_line']}")
            if p:
                print(f"  {d} {lg}・投手MVP {p['name']}（{p['team']}）{p['score']}点 "
                      f"[{p['role']}] — {p['stat_line']}")

    print(f"[INFO] 日刊表彰を{made}日ぶん作成しました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
