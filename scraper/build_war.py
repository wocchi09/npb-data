"""
簡易WAR（守備抜き）の算出・保存
==================================

rebuild_stats.py が作った players/stats.json・teams/stats.json・
fip_constants.json を読み、選手ごとの簡易WARを算出して保存する。

★このWARには守備貢献が含まれません★（理由は lib/war.py の説明を参照）

保存先: data/{season}/war.json

使い方:
    python scraper/build_war.py --season 2026
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib.normalize import team_info
from lib.war import (
    calc_batter_war, calc_pitcher_war, league_run_env,
    replacement_fip, replacement_level,
)


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def build(season, base="data"):
    ppath = f"{base}/{season}/players/stats.json"
    pdata = load_json(ppath)
    if not pdata:
        print(f"[WARN] {ppath} がありません。先に rebuild_stats.py を実行してください。")
        return None

    players = pdata.get("players", [])
    tdata = load_json(f"{base}/{season}/teams/stats.json") or {"teams": []}
    team_games = {t["team"]: t.get("games") or 0 for t in tdata["teams"] if t.get("team")}
    fip_c = load_json(f"{base}/{season}/fip_constants.json") or {}
    fip_constants = fip_c.get("constants", {})

    run_env = league_run_env(players)
    repl = replacement_level(players, team_games)
    repl_fip = replacement_fip(fip_constants)

    batters, pitchers = [], []
    for p in players:
        bw = calc_batter_war(p, run_env, repl, team_games)
        if bw:
            batters.append({
                "player_key": p.get("key"), "player_id": p.get("player_id"),
                "name": p.get("name"), "team": p.get("team"),
                "position": p.get("position"), **bw,
            })
        pw = calc_pitcher_war(p, run_env, repl_fip)
        if pw:
            pitchers.append({
                "player_key": p.get("key"), "player_id": p.get("player_id"),
                "name": p.get("name"), "team": p.get("team"), **pw,
            })

    batters.sort(key=lambda x: -x["war"])
    pitchers.sort(key=lambda x: -x["war"])

    result = {
        "season": season,
        "note": ("守備貢献（R_field）を含まない簡易値です。取得元のデータに"
                 "打球の速度・到達地点等が無いため、守備範囲や失点抑止を"
                 "算出できません。参考値としてご利用ください。"),
        "methodology": {
            "batter": "WAR = (R_bat + R_baser + R_dp + R_pos) / RPW （R_field除く）",
            "pitcher": "WAR = (リプレイスメントFIP - 投手FIP) × 投球回 / 9 / RPW",
            "position_adjustment_source": "資料提供値（162試合換算・シーズン試合数按分）",
            "replacement_level_source": "規定打席未満の全野手平均OPS（NPB実データから算出）",
            "replacement_fip_source": "リーグ平均防御率+1.00（セイバーメトリクスの一般的経験則）",
        },
        "run_environment": run_env,
        "replacement_level": repl,
        "replacement_fip": repl_fip,
        "batters": batters,
        "pitchers": pitchers,
    }
    save_json(f"{base}/{season}/war.json", result)

    print(f"[INFO] 野手WAR: {len(batters)}人 / 投手WAR: {len(pitchers)}人")
    for lg in ("セ", "パ"):
        top_b = [b for b in batters if team_info(b["team"]).get("league") == lg]
        if top_b:
            b0 = top_b[0]
            print(f"  {lg}・野手WAR 1位 {b0['name']}（{b0['team']}）{b0['war']}")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--base", default="data")
    args = ap.parse_args()
    result = build(args.season, args.base)
    # 入力不足を「成功」として扱うと、Actionsが緑のままWARだけ更新されない。
    return 0 if result is not None else 1


if __name__ == "__main__":
    sys.exit(main())
