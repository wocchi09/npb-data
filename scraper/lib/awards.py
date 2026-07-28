"""
MVP・ベストメンバーのスコア計算
================================
仕様書「NPB 日刊・週間 MVP／ベストメンバー 選出基準」に基づく採点。

★取得できないデータは推測で補完しない★（仕様書14章）
走塁の細目（三盗・本盗・盗塁死・好走塁・タッチアップ・走塁死・牽制死）と
守備の加点項目（好守備・補殺・併殺貢献・盗塁阻止・捕逸）は取得できないため
採点対象外とし、換算スコアで正規化して比較する。

    換算スコア = 獲得点 ÷ 利用可能な最大点 × 100
"""

import json
import os
import re

_CONFIG = None


def load_config(path=None):
    """配点設定を読む（1度読んだら使い回す）"""
    global _CONFIG
    if _CONFIG is not None:
        return _CONFIG
    if path is None:
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "awards_config.json")
    with open(path, encoding="utf-8") as f:
        _CONFIG = json.load(f)
    return _CONFIG


def fmt_rate(value, digits=3):
    """
    打率・出塁率・長打率・OPS・勝率など「1.000を超えない率」の表記を
    NPBの慣例（先頭の0を消す）に統一する。例: 0.333 → ".333" / 0.000 → ".000"
    1.000ちょうど・1を超える値はそのまま表示する（OPSは1を超えることがあるため）。
    """
    if value is None:
        return "-"
    s = f"{value:.{digits}f}"
    if s.startswith("0."):
        s = s[1:]
    elif s.startswith("-0."):
        s = "-" + s[2:]
    return s


def _cap(value, limit):
    """カテゴリごとの上限を適用する"""
    return min(value, limit) if limit is not None else value


# ---------------------------------------------------------------- 試合の文脈

def _score_map(score_at):
    m = {}
    for s in (score_at or []):
        if s.get("team") is not None and s.get("score") is not None:
            m[s["team"]] = s["score"]
    return m


def build_context(game, classify):
    """
    1試合ぶんの打席を、採点に必要な情報つきで並べ直す。

    classify は打席結果テキストを分類する関数（lib.events.classify_result）。
    打席ごとに次を持たせる:
      打者・守備側・イニング・表裏・アウト・走者・得点圏
      打席前の点差・その打席の打点・打席後の点差
      同点打／勝ち越し打／逆転打／サヨナラ打／決勝打
    """
    home = game.get("home")
    away = game.get("away")
    res = game.get("result") or {}
    hs, as_ = res.get("home_score"), res.get("away_score")

    atbats = [a for a in (game.get("atbats") or []) if a.get("valid", True)]
    out = []
    for i, ab in enumerate(atbats):
        b = ab.get("batter") or {}
        p = ab.get("pitcher") or {}
        r = ab.get("runners") or {}
        cnt = ab.get("count") or {}
        ev = classify(ab.get("result_summary"))

        bteam = ab.get("batting_team")
        fteam = ab.get("fielding_team")
        sm = _score_map(ab.get("score_at"))
        diff_before = None
        if bteam in sm and fteam in sm:
            diff_before = sm[bteam] - sm[fteam]
        runs_in = ev.get("rbi", 0)
        diff_after = None if diff_before is None else diff_before + runs_in

        out.append({
            "i": i,
            "batter": b.get("name"), "batter_id": b.get("player_id"),
            "pitcher": p.get("name"), "pitcher_id": p.get("player_id"),
            "batting_team": bteam, "fielding_team": fteam,
            "inning": ab.get("inning") or 0,
            "tb": ab.get("top_bottom") or "",
            "outs": cnt.get("out"),
            "r1": bool(r.get("first")), "r2": bool(r.get("second")),
            "r3": bool(r.get("third")),
            "risp": bool(r.get("second") or r.get("third")),
            "bases_loaded": bool(r.get("first") and r.get("second") and r.get("third")),
            "ev": ev,
            "result": ab.get("result_summary") or "",
            "diff_before": diff_before, "runs_in": runs_in, "diff_after": diff_after,
            "pitch_count": ab.get("pitch_count") or 0,
            "is_last": i == len(atbats) - 1,
            # あとで埋める
            "tying": False, "go_ahead": False, "comeback": False,
            "walkoff": False, "game_winning": False,
        })

    # --- 同点打・勝ち越し打・逆転打・サヨナラ打 ---
    for a in out:
        db, da = a["diff_before"], a["diff_after"]
        if db is None or da is None or a["runs_in"] <= 0:
            continue
        if db < 0 and da == 0:
            a["tying"] = True
        elif db == 0 and da > 0:
            a["go_ahead"] = True
        elif db < 0 and da > 0:
            a["comeback"] = True
        # サヨナラ＝最後の打席・裏の攻撃・それまでリードしていない
        if a["is_last"] and a["tb"] == "裏" and db <= 0 and da > 0:
            a["walkoff"] = True

    # --- 決勝打（勝ちチームが最後にリードを奪った打席）---
    winner = None
    if hs is not None and as_ is not None:
        winner = home if hs > as_ else (away if as_ > hs else None)
    if winner:
        for a in reversed(out):
            if a["batting_team"] != winner or a["runs_in"] <= 0:
                continue
            db, da = a["diff_before"], a["diff_after"]
            if db is not None and da is not None and db <= 0 < da:
                a["game_winning"] = True
                break

    ctx = {"atbats": out, "home": home, "away": away, "winner": winner,
           "home_score": hs, "away_score": as_}
    track_baserunning(ctx)
    return ctx


# ---------------------------------------------------------------- 走塁

def track_baserunning(ctx):
    """
    走者の進塁を追い、標準より多く進んだ「好走塁」を検出する。

    考え方:
      公式の塁コードは各打席の開始時点の値。そこで
        ・標準的な進塁（単打なら1つ、二塁打なら2つ進む）を仮定した予測
        ・次の打席で実際に記録されている塁コード
      を比べると、余分に進んだ分が分かる。
      得点した場合は打点から判定できるので、イニング最後の打席でも分かる。

    ★判定できるのは走者が1人だけの打席に限る★
      走者が2人以上いると、どの走者がどこまで進んだか特定できないため、
      仕様書14章に従って加点しない（推測で埋めない）。

    戻り値:
      { 走者キー: {"name":.., "extra":余分な進塁の回数,
                   "score_from_first":一塁から長打で生還した回数} }
      と、判定の内訳（診断用）
    """
    atbats = ctx["atbats"]
    halves = {}
    for a in atbats:
        halves.setdefault((a["inning"], a["tb"]), []).append(a)

    credit = {}
    diag = {"judged": 0, "extra": 0, "multi_runner_skip": 0, "unknown_skip": 0}

    def key_of(name, pid):
        return f"id:{pid}" if pid else f"nm:{name}"

    for _, seq in sorted(halves.items()):
        # 塁上の走者を追う（名前と選手IDの組）
        bases = {1: None, 2: None, 3: None}
        for idx, a in enumerate(seq):
            official = {1: a["r1"], 2: a["r2"], 3: a["r3"]}
            # 公式の塁コードと答え合わせ（塁の有無は常に公式値が正しい）
            for b in (1, 2, 3):
                if official[b] and not bases[b]:
                    bases[b] = ("?", None)     # いるはずだが誰か分からない
                if not official[b]:
                    bases[b] = None
            a["_runners"] = {b: (bases[b][0] if bases[b] else None) for b in (1, 2, 3)}

            ev = a["ev"]
            adv = (1 if ev.get("single") else 2 if ev.get("double")
                   else 3 if ev.get("triple") else 0)

            # --- 余分な進塁の判定（安打のときだけ）---
            if adv and not ev.get("hr"):
                on = [b for b in (1, 2, 3) if bases[b]]
                if len(on) > 1:
                    diag["multi_runner_skip"] += 1
                elif len(on) == 1:
                    fb = on[0]
                    rname, rpid = bases[fb]
                    if rname == "?":
                        diag["unknown_skip"] += 1
                    else:
                        std = min(fb + adv, 4)      # 標準で到達する塁（4は本塁）
                        actual = None
                        if a["runs_in"] >= 1:
                            actual = 4              # 生還した
                        elif idx + 1 < len(seq):
                            nx = seq[idx + 1]
                            no = {1: nx["r1"], 2: nx["r2"], 3: nx["r3"]}
                            batter_base = adv if adv <= 3 else None
                            others = [b for b in (1, 2, 3) if no[b] and b != batter_base]
                            if len(others) == 1:
                                actual = others[0]
                        if actual is not None:
                            diag["judged"] += 1
                            if actual > std:
                                k = key_of(rname, rpid)
                                c = credit.setdefault(
                                    k, {"name": rname, "player_id": rpid,
                                        "extra": 0, "score_from_first": 0, "detail": []})
                                hit_name = ("単打" if adv == 1 else
                                            "二塁打" if adv == 2 else "三塁打")
                                if fb == 1 and adv >= 2 and actual == 4:
                                    c["score_from_first"] += 1
                                    c["detail"].append(f"{hit_name}で一塁から生還")
                                else:
                                    c["extra"] += 1
                                    to = "本塁" if actual == 4 else f"{actual}塁"
                                    c["detail"].append(f"{hit_name}で{fb}塁から{to}へ")
                                diag["extra"] += 1

            # --- 次の打席に向けて塁の状態を進める（標準的な進塁）---
            b = a.get("batter"), a.get("batter_id")
            rs = a["result"]
            if ev.get("hr"):
                bases = {1: None, 2: None, 3: None}
            elif adv:
                for i in (3, 2, 1):
                    if bases[i]:
                        to = i + adv
                        bases[to] = bases[i] if to <= 3 else None
                        bases[i] = None
                if adv <= 3:
                    bases[adv] = b
            elif ev.get("bb") or ev.get("hbp"):
                # 押し出しで詰まっている塁だけ進む
                if bases[1]:
                    if bases[2]:
                        if bases[3]:
                            bases[3] = None
                        bases[3] = bases[2]
                    bases[2] = bases[1]
                bases[1] = b
            elif ev.get("error"):
                for i in (3, 2, 1):
                    if bases[i]:
                        to = i + 1
                        bases[to] = bases[i] if to <= 3 else None
                        bases[i] = None
                bases[1] = b
            elif ev.get("sf") or ev.get("sh"):
                for i in (3, 2, 1):
                    if bases[i]:
                        to = i + 1
                        bases[to] = bases[i] if to <= 3 else None
                        bases[i] = None
            elif ev.get("gidp"):
                bases[1] = None
            # ゴロ・フライ・三振は走者そのまま

    ctx["baserunning"] = credit
    ctx["baserunning_diag"] = diag
    return credit


# ---------------------------------------------------------------- 野手

def score_daily_batter(row, ctx, cfg=None):
    """
    1選手1試合の打撃を採点する。
    row は公式ボックススコアの打撃行（打数・安打・打点などが入る）。
    """
    cfg = cfg or load_config()
    c = cfg["daily_batter"]
    cats = c["categories"]
    B, R, C, D, T, P = (c["basicBatting"], c["runProduction"], c["clutch"],
                        c["baserunning"], c["teamWin"], c["penalty"])

    name = row.get("name")
    team = row.get("team")
    # この選手の打席だけを取り出す（同姓同名を避けるため選手IDを優先）
    pid = row.get("player_id")
    mine = [a for a in ctx["atbats"]
            if (pid and a["batter_id"] == pid) or (not pid and a["batter"] == name)]

    reasons, minus_reasons = [], []

    # --- A. 打撃基礎点 ---
    singles = doubles = triples = hrs = 0
    bb = hbp = sf = 0
    for a in mine:
        e = a["ev"]
        singles += e.get("single", 0)
        doubles += e.get("double", 0)
        triples += e.get("triple", 0)
        hrs += e.get("hr", 0)
        bb += e.get("bb", 0)
        hbp += e.get("hbp", 0)
        sf += e.get("sf", 0)
    hits = singles + doubles + triples + hrs

    basic = (singles * B["single"] + doubles * B["double"] +
             triples * B["triple"] + hrs * B["hr"] +
             bb * B["bb"] + hbp * B["hbp"] + sf * B["sf"])
    if hits >= 4:
        basic += B["four_hits_bonus"]
        reasons.append(f"{hits}安打")
    elif hits == 3:
        basic += B["three_hits_bonus"]
        reasons.append("猛打賞")
    if hrs:
        reasons.append(f"本塁打{hrs}本" if hrs > 1 else "本塁打")
    basic = _cap(basic, cats["basicBatting"]["max"])

    # --- B. 長打・得点貢献点 ---
    rbi = sum(a["runs_in"] for a in mine)
    runs = row.get("runs") or 0
    prod = rbi * R["rbi_each"] + runs * R["run_each"]
    if rbi:
        reasons.append(f"{rbi}打点")

    # 同一打席で複数条件を満たす場合は高い方だけを採る（仕様書4-1の注記）
    for a in mine:
        vals = []
        if a["walkoff"]:
            vals.append((R["walkoff_hit"], "サヨナラ打"))
        if a["game_winning"]:
            vals.append((R["game_winning_hit"], "決勝打"))
        if a["comeback"]:
            vals.append((R["comeback_hit"], "逆転打"))
        if a["go_ahead"]:
            vals.append((R["go_ahead_hit"], "勝ち越し打"))
        if a["tying"]:
            vals.append((R["tying_hit"], "同点打"))
        if vals:
            v, label = max(vals, key=lambda x: x[0])
            prod += v
            reasons.append(label)
        # 満塁本塁打
        if a["ev"].get("hr") and a["bases_loaded"]:
            prod += R["grand_slam_bonus"]
            reasons.append("満塁本塁打")
    if hrs >= 2:
        prod += (hrs - 1) * R["multi_hr_each"]
    prod = _cap(prod, cats["runProduction"]["max"])

    # --- C. 勝負強さ点 ---
    clutch = 0
    risp_ab = risp_hit = risp_bb = 0
    two_out_risp = late_hit = late_hr = 0
    for a in mine:
        e = a["ev"]
        if not a["risp"]:
            pass
        else:
            if e.get("bb"):
                risp_bb += 1
            if e.get("ab"):
                risp_ab += 1
                if e.get("hit"):
                    risp_hit += 1
                    if a["outs"] == 2:
                        two_out_risp += 1
        # 終盤の競った場面
        if (a["inning"] >= C["late_inning_from"] and a["diff_before"] is not None
                and abs(a["diff_before"]) <= C["close_score_diff"]):
            if e.get("hr"):
                late_hr += 1
            elif e.get("hit"):
                late_hit += 1

    clutch += risp_hit * C["risp_hit"] + risp_bb * C["risp_bb"]
    clutch += two_out_risp * C["two_out_risp_hit"]
    clutch += late_hit * C["late_close_hit"] + late_hr * C["late_close_hr"]
    if risp_ab and risp_hit == risp_ab:
        clutch += C["risp_perfect_bonus"]
    if risp_hit >= 2:
        clutch += C["risp_multi_hit_bonus"]
    if risp_hit:
        reasons.append(f"得点圏{risp_ab}打数{risp_hit}安打")
    if late_hr:
        reasons.append("終盤の競り合いで本塁打")
    clutch = _cap(clutch, cats["clutch"]["max"])

    # --- D. 走塁点（盗塁＋余分な進塁）---
    sb = row.get("sb") or 0
    baser = sb * D["sb"]
    if sb:
        reasons.append(f"盗塁{sb}")
    br = (ctx.get("baserunning") or {}).get(
        f"id:{pid}" if pid else f"nm:{name}")
    if br:
        baser += br["extra"] * D.get("extra_base", 1)
        baser += br["score_from_first"] * D.get("score_from_first", 1.5)
        for d in br["detail"]:
            reasons.append(d)
    baser = _cap(baser, cats["baserunning"]["available_max"])

    # --- E. 守備点（加点項目はデータなし）---
    defense = 0

    # --- F. チーム勝利補正 ---
    win = 0
    if ctx["winner"] and team == ctx["winner"]:
        win += T["team_win"]
        if any(a["game_winning"] for a in mine):
            win += T["game_winning_hit_in_win"]
    win = _cap(win, cats["teamWin"]["max"])

    # --- G. マイナス点 ---
    so = row.get("so") or 0
    penalty = max(so * P["so_each"], P["so_cap"])
    risp_so = sum(1 for a in mine if a["risp"] and a["ev"].get("so"))
    penalty += risp_so * P["risp_so_each"]
    gidp = sum(1 for a in mine if a["ev"].get("gidp"))
    for a in mine:
        if a["ev"].get("gidp"):
            penalty += P["bases_loaded_gidp"] if a["bases_loaded"] else P["gidp"]
    err = row.get("errors") or 0
    penalty += err * P["error"]
    if so:
        minus_reasons.append(f"三振{so}")
    if gidp:
        minus_reasons.append(f"併殺打{gidp}")
    if err:
        minus_reasons.append(f"失策{err}")

    total = basic + prod + clutch + baser + defense + win + penalty

    # --- 打席数による補正（仕様書15章）---
    pa = len(mine)
    mult = c["pa_multiplier"].get(str(pa))
    if mult:
        total *= mult

    avail = sum(v["available_max"] for v in cats.values())
    return {
        "name": name, "team": team, "player_id": pid,
        "position": row.get("position"), "order": row.get("order"),
        "raw": round(total, 2),
        "score": round(total / avail * 100, 2) if avail else 0,
        "available_max": avail,
        "pa": pa,
        "breakdown": {
            "basicBatting": round(basic, 2), "runProduction": round(prod, 2),
            "clutch": round(clutch, 2), "baserunning": round(baser, 2),
            "defense": defense, "teamWin": round(win, 2),
            "penalty": round(penalty, 2),
        },
        "stat_line": _batter_line(row, hits),
        "reasons": reasons, "minus_reasons": minus_reasons,
        "keys": {"hits": hits, "hr": hrs, "rbi": rbi, "runs": runs,
                 "risp_hit": risp_hit, "risp_ab": risp_ab, "so": so, "sb": sb},
    }


def _batter_line(row, hits):
    ab = row.get("ab") or 0
    parts = [f"{ab}打数{hits}安打"]
    if row.get("hr"):
        parts.append(f"{row['hr']}本塁打")
    if row.get("rbi"):
        parts.append(f"{row['rbi']}打点")
    if row.get("runs"):
        parts.append(f"{row['runs']}得点")
    if row.get("sb"):
        parts.append(f"{row['sb']}盗塁")
    return "、".join(parts)


# ---------------------------------------------------------------- 投手

def _role_of(index, row, ctx, pitchers):
    """先発・抑え・中継ぎのどれかを判定する（仕様書5章）"""
    if index == 0:
        return "先発"
    dec = row.get("decision") or ""
    if "Ｓ" in dec or "S" in dec:
        return "抑え"
    # 最後に投げた投手も抑え扱い（同点9回を無失点など）
    if pitchers and row is pitchers[-1]:
        last_inning = max((a["inning"] for a in ctx["atbats"]), default=0)
        mine = [a for a in ctx["atbats"]
                if a["pitcher_id"] == row.get("player_id") or a["pitcher"] == row.get("name")]
        if mine and max(a["inning"] for a in mine) >= last_inning:
            return "抑え"
    return "中継ぎ"


def _pitcher_atbats(row, ctx):
    pid = row.get("player_id")
    name = row.get("name")
    return [a for a in ctx["atbats"]
            if (pid and a["pitcher_id"] == pid) or (not pid and a["pitcher"] == name)]


def score_daily_starter(row, ctx, cfg=None):
    cfg = cfg or load_config()
    c = cfg["daily_starter"]
    cats = c["categories"]
    I, PR, K, W, WC, P = (c["innings"], c["prevention"], c["strikeout"],
                          c["whip"], c["winContrib"], c["penalty"])

    outs = row.get("outs") or 0
    ip = outs / 3
    er = row.get("earned_runs") or 0
    ra = row.get("runs_allowed") or 0
    so = row.get("so") or 0
    bb = row.get("bb") or 0
    hbp = row.get("hbp") or 0
    ha = row.get("hits_allowed") or 0
    hra = row.get("hr_allowed") or 0
    balk = row.get("balk") or 0
    dec = row.get("decision") or ""
    reasons, minus = [], []

    # --- 投球回 ---
    inn = ip * I["per_inning"]
    if outs >= 24:
        inn += I["bonus_8"]
    elif outs >= 21:
        inn += I["bonus_7"]
    elif outs >= 18:
        inn += I["bonus_6"]
    if outs >= 27:
        inn += I["complete_game"]
        reasons.append("完投")
        if ra == 0:
            inn += I["shutout"]
            reasons.append("完封")
            if ha == 0:
                inn += I["no_hitter"]
                reasons.append("ノーヒットノーラン")
                if bb == 0 and hbp == 0 and (row.get("batters_faced") or 0) == 27:
                    inn += I["perfect_game"]
                    reasons.append("完全試合")
    inn = _cap(inn, cats["innings"]["max"])

    # --- 失点抑制 ---
    prev = (PR["er_0"] if er == 0 else PR["er_1"] if er == 1 else
            PR["er_2"] if er == 2 else PR["er_3"] if er == 3 else PR["er_4plus"])
    if er == 0 and outs >= 15:
        reasons.append("無失点")
    prev = _cap(prev, cats["prevention"]["max"])

    # --- 奪三振 ---
    ks = so * K["per_k"]
    if so >= 10:
        ks += K["ten_k_bonus"]
        reasons.append(f"{so}奪三振")
    if ip:
        k9 = so * 9 / ip
        if k9 >= K["high_k_rate_per9"]:
            ks += K["high_k_rate_max"]
    ks = _cap(ks, cats["strikeout"]["max"])

    # --- WHIP ---
    whip = (ha + bb) / ip if ip else None
    ws = 0
    if whip is not None:
        ws = (W["t050"] if whip <= 0.50 else W["t080"] if whip <= 0.80 else
              W["t100"] if whip <= 1.00 else W["t120"] if whip <= 1.20 else
              W["t150"] if whip <= 1.50 else 0)
    ws = _cap(ws, cats["whip"]["max"])

    # --- 勝利貢献 ---
    wc = 0
    is_qs = outs >= 18 and er <= 3
    is_hqs = outs >= 21 and er <= 2
    if "勝" in dec:
        wc += WC["win"]
        reasons.append("勝利投手")
    if is_hqs:
        wc += WC["hqs"]
        reasons.append("HQS")
    elif is_qs:
        wc += WC["qs"]
        reasons.append("QS")
    if ctx["winner"] and row.get("_team") == ctx["winner"]:
        wc += WC["team_win"]
    wc = _cap(wc, cats["winContrib"]["max"])

    # --- 減点 ---
    pen = (hra * P["hr_allowed"] + bb * P["bb"] + hbp * P["hbp"] +
           balk * P["balk"])
    if outs < 15:
        pen += P["under_5_innings"]
        minus.append("5回未満")
        if outs < 9:
            pen += P["under_3_innings_extra"]
    if "敗" in dec:
        pen += P["loss"]
        minus.append("敗戦")
    if hra:
        minus.append(f"被本塁打{hra}")

    total = inn + prev + ks + ws + wc + pen
    avail = sum(v["available_max"] for v in cats.values())
    return {
        "name": row.get("name"), "team": row.get("_team"),
        "player_id": row.get("player_id"), "role": "先発",
        "raw": round(total, 2),
        "score": round(total / avail * 100, 2) if avail else 0,
        "available_max": avail,
        "breakdown": {"innings": round(inn, 2), "prevention": round(prev, 2),
                      "strikeout": round(ks, 2), "whip": round(ws, 2),
                      "winContrib": round(wc, 2), "penalty": round(pen, 2)},
        "stat_line": (f"{row.get('innings','')}回 {ra}失点 自責{er} "
                      f"{so}奪三振 被安打{ha} 与四球{bb}"
                      + (f" WHIP{whip:.2f}" if whip is not None else "")),
        "reasons": reasons, "minus_reasons": minus,
        "keys": {"outs": outs, "er": er, "so": so, "whip": whip,
                 "qs": is_qs, "hqs": is_hqs},
    }


def _relief_situation(row, ctx):
    """救援投手が登板した場面（最初に投げた打席の状況）"""
    mine = _pitcher_atbats(row, ctx)
    if not mine:
        return None
    a = mine[0]
    # 投手から見た点差＝守備側の点差
    diff = None
    if a["diff_before"] is not None:
        diff = -a["diff_before"]      # 打者側の点差を反転
    return {"diff": diff, "risp": a["risp"], "bases_loaded": a["bases_loaded"],
            "outs": a["outs"], "inning": a["inning"],
            "runners": sum([a["r1"], a["r2"], a["r3"]])}


def score_daily_reliever(row, ctx, cfg=None):
    cfg = cfg or load_config()
    c = cfg["daily_reliever"]
    cats, BS, S, P = c["categories"], c["base"], c["situation"], c["penalty"]

    outs = row.get("outs") or 0
    er = row.get("earned_runs") or 0
    so = row.get("so") or 0
    bb = (row.get("bb") or 0) + (row.get("hbp") or 0)
    ha = row.get("hits_allowed") or 0
    hra = row.get("hr_allowed") or 0
    dec = row.get("decision") or ""
    reasons, minus = [], []

    base = outs * BS["per_out"] + so * BS["per_k"]
    if er == 0 and outs >= 1:
        base += BS["scoreless"]
        reasons.append("無失点")
    if ha == 0 and outs >= 1:
        base += BS["no_hit"]
    if bb == 0 and outs >= 1:
        base += BS["no_walk"]
    if row.get("_hold"):
        base += BS["hold"]
        reasons.append("ホールド")
    if "勝" in dec:
        base += BS["win"]
        reasons.append("勝利投手")
    if outs >= 6 and er == 0:
        base += BS["multi_inning_scoreless"]
        reasons.append("複数回無失点")
    base = _cap(base, cats["base"]["max"])

    # --- 場面加点 ---
    sit = 0
    st = _relief_situation(row, ctx)
    if st and st["diff"] is not None and abs(st["diff"]) <= S["blowout_diff"]:
        if st["diff"] == 0:
            sit += S["tied"]
            reasons.append("同点で登板")
        elif st["diff"] == 1:
            sit += S["lead_1"]
            reasons.append("1点リードで登板")
        elif st["diff"] == -1:
            sit += S["behind_1"]
        if st["bases_loaded"]:
            sit += S["bases_loaded"]
            reasons.append("満塁で登板")
        elif st["risp"]:
            sit += S["risp"]
            reasons.append("得点圏に走者を置いて登板")
            if st["outs"] == 0:
                sit += S["no_out_risp_bonus"]
    sit = _cap(sit, cats["situation"]["available_max"])

    pen = er * P["earned_run"] + hra * P["hr_allowed"] + bb * P["bb"]
    if "敗" in dec:
        pen += P["loss"]
        minus.append("敗戦")
    if er:
        minus.append(f"自責{er}")

    total = base + sit + pen
    avail = sum(v["available_max"] for v in cats.values())
    return {
        "name": row.get("name"), "team": row.get("_team"),
        "player_id": row.get("player_id"), "role": "中継ぎ",
        "raw": round(total, 2),
        "score": round(total / avail * 100, 2) if avail else 0,
        "available_max": avail,
        "breakdown": {"base": round(base, 2), "situation": round(sit, 2),
                      "penalty": round(pen, 2)},
        "stat_line": f"{row.get('innings','')}回 {so}奪三振 自責{er} 被安打{ha}",
        "reasons": reasons, "minus_reasons": minus,
        "keys": {"outs": outs, "er": er, "so": so},
    }


def score_daily_closer(row, ctx, cfg=None):
    cfg = cfg or load_config()
    c = cfg["daily_closer"]
    cats, BS, S, P = c["categories"], c["base"], c["situation"], c["penalty"]

    outs = row.get("outs") or 0
    er = row.get("earned_runs") or 0
    so = row.get("so") or 0
    bb = (row.get("bb") or 0) + (row.get("hbp") or 0)
    ha = row.get("hits_allowed") or 0
    hra = row.get("hr_allowed") or 0
    dec = row.get("decision") or ""
    has_save = "Ｓ" in dec or "S" in dec
    reasons, minus = [], []

    base = outs * BS["per_out"] + so * BS["per_k"]
    if has_save:
        base += BS["save"]
        reasons.append("セーブ")
        if outs == 4:
            base += BS["four_out_save"]
        elif outs >= 5:
            base += BS["five_out_save"]
    if er == 0 and outs >= 1:
        base += BS["scoreless"]
        reasons.append("無失点")
    # 3者凡退（3アウト・走者を出していない）
    if outs >= 3 and ha == 0 and bb == 0 and (row.get("batters_faced") or 0) == 3:
        base += BS["three_up_three_down"]
        reasons.append("3者凡退")
    if so >= 2:
        base += BS["multi_k_bonus"]
    base = _cap(base, cats["base"]["max"])

    # --- 場面加点 ---
    sit = 0
    st = _relief_situation(row, ctx)
    if st:
        if has_save and st["diff"] is not None:
            if st["diff"] == 1:
                sit += S["save_diff_1"]
                reasons.append("1点差セーブ")
            elif st["diff"] == 2:
                sit += S["save_diff_2"]
        if st["risp"]:
            sit += S["risp"]
        elif st["runners"]:
            sit += S["runners_on"]
        if (not has_save and st["diff"] == 0 and er == 0
                and st["inning"] >= 9):
            sit += S["tied_final_scoreless"]
            reasons.append("同点の最終回を無失点")
    sit = _cap(sit, cats["situation"]["max"])

    pen = er * P["earned_run"] + hra * P["hr_allowed"] + bb * P["bb"]
    if "敗" in dec:
        pen += P["loss"]
        minus.append("敗戦")
    if er:
        minus.append(f"自責{er}")

    total = base + sit + pen
    avail = sum(v["available_max"] for v in cats.values())
    return {
        "name": row.get("name"), "team": row.get("_team"),
        "player_id": row.get("player_id"), "role": "抑え",
        "raw": round(total, 2),
        "score": round(total / avail * 100, 2) if avail else 0,
        "available_max": avail,
        "breakdown": {"base": round(base, 2), "situation": round(sit, 2),
                      "penalty": round(pen, 2)},
        "stat_line": f"{row.get('innings','')}回 {so}奪三振 自責{er}",
        "reasons": reasons, "minus_reasons": minus,
        "keys": {"outs": outs, "er": er, "so": so, "save": has_save},
    }


def classify_pitcher_roles(game, ctx):
    """試合の投手を役割ごとに分ける。戻り値は (行, 役割, チーム) の並び"""
    box = game.get("boxscore") or {}
    pit = box.get("pitching") or {}
    out = []
    for side, team in (("away", game.get("away")), ("home", game.get("home"))):
        rows = pit.get(side) or []
        for i, row in enumerate(rows):
            row = dict(row)
            row["_team"] = team
            out.append((row, _role_of(i, row, ctx, rows), team))
    return out


# ---------------------------------------------------------------- 期間集計（週間・月間共通）

def _pct(rank, n):
    """順位を0〜1の百分位に変換する（1位が1.0）"""
    if n <= 1:
        return 1.0
    return 1 - (rank - 1) / (n - 1)


def _percentile_score(values, my_value, max_pt, higher_is_better=True):
    """
    リーグ内の分布の中で my_value が何点分にあたるかを返す。
    値が無い（None）比較対象は除外する。
    """
    vals = [v for v in values if v is not None]
    if my_value is None or not vals:
        return 0.0
    vals_sorted = sorted(vals, reverse=higher_is_better)
    # 同値は同順位にする
    rank = 1
    for v in vals_sorted:
        if (higher_is_better and v > my_value) or (not higher_is_better and v < my_value):
            rank += 1
    return round(_pct(rank, len(vals_sorted)) * max_pt, 2)


def aggregate_batter_period(rows):
    """1選手ぶんの batting_lines 行（複数試合）を期間集計する"""
    g = len(rows)
    ab = sum(r.get("ab") or 0 for r in rows)
    hits = sum(r.get("hits") or 0 for r in rows)
    singles = sum(r.get("singles") or 0 for r in rows)
    doubles = sum(r.get("doubles") or 0 for r in rows)
    triples = sum(r.get("triples") or 0 for r in rows)
    hr = sum(r.get("hr") or 0 for r in rows)
    bb = sum(r.get("bb") or 0 for r in rows)
    hbp = sum(r.get("hbp") or 0 for r in rows)
    so = sum(r.get("so") or 0 for r in rows)
    rbi = sum(r.get("rbi") or 0 for r in rows)
    runs = sum(r.get("runs") or 0 for r in rows)
    sb = sum(r.get("sb") or 0 for r in rows)
    errors = sum(r.get("errors") or 0 for r in rows)
    starts = sum(1 for r in rows if r.get("is_starter"))

    pa = ab + bb + hbp  # 犠打・犠飛はここでは持たないため簡易PA
    tb = singles + doubles * 2 + triples * 3 + hr * 4
    avg = hits / ab if ab else None
    obp = (hits + bb + hbp) / pa if pa else None
    slg = tb / ab if ab else None
    ops = (obp + slg) if (obp is not None and slg is not None) else None

    return {
        "games": g, "ab": ab, "hits": hits, "hr": hr, "rbi": rbi, "runs": runs,
        "sb": sb, "so": so, "errors": errors, "starts": starts, "pa": pa,
        "extra_base_hits": doubles + triples + hr,
        "avg": avg, "obp": obp, "slg": slg, "ops": ops,
        "gidp": 0,  # batting_lines に併殺列がないため対象外（推測しない）
    }


def score_weekly_batter(name, team, position, agg, league_pool, team_games, cfg=None):
    """
    週間野手スコア。リーグ内の他選手（league_pool = 同リーグの agg のリスト）と
    比較した百分位で「打撃内容」等を採点する（仕様書9-2）。
    """
    cfg = cfg or load_config()
    c = cfg["weekly_batter"]
    cats = c["categories"]
    reasons = []

    # --- 打撃内容：リーグ内百分位 ---
    B = c["battingContent"]
    content = 0
    content += _percentile_score([p["ops"] for p in league_pool], agg["ops"], B["ops"])
    content += _percentile_score([p["avg"] for p in league_pool], agg["avg"], B["avg"])
    content += _percentile_score([p["obp"] for p in league_pool], agg["obp"], B["obp"])
    content += _percentile_score([p["slg"] for p in league_pool], agg["slg"], B["slg"])
    content = _cap(content, cats["battingContent"]["max"])
    if agg["ops"] is not None:
        reasons.append(f"OPS {fmt_rate(agg['ops'])}")

    # --- 長打・得点貢献：リーグ最多に対する割合 ---
    R = c["runProduction"]
    prod = 0
    for src_key, pt in (("hr", R["hr"]), ("rbi", R["rbi"]), ("runs", R["run"])):
        mx = max([p[src_key] for p in league_pool] + [0])
        prod += (agg[src_key] / mx * pt) if mx else 0
    mx_xbh = max([p["extra_base_hits"] for p in league_pool] + [0])
    prod += (agg["extra_base_hits"] / mx_xbh * R["extra_base_hits"]) if mx_xbh else 0
    prod = _cap(prod, cats["runProduction"]["max"])
    if agg["hr"]:
        reasons.append(f"{agg['hr']}本塁打")
    if agg["rbi"]:
        reasons.append(f"{agg['rbi']}打点")

    # --- 出場量 ---
    T = c["playingTime"]
    need_pa = (team_games or 0) * c["min_pa_games_factor"]
    pt = 0
    if need_pa:
        pt += min(agg["pa"] / need_pa, 1) * T["qualified_pa"]
    if team_games:
        pt += min(agg["starts"] / team_games, 1) * T["starts"]
        pt += min(agg["games"] / team_games, 1) * T["appearance_rate"]
    pt = _cap(pt, cats["playingTime"]["max"])

    # --- 走塁・守備（盗塁のみ）---
    D = c["defenseBaser"]
    db = _cap(agg["sb"] * D["sb"], cats["defenseBaser"]["available_max"])
    if agg["sb"]:
        reasons.append(f"盗塁{agg['sb']}")

    # --- 勝負強さ（得点圏は集計に含まれないため、現状は0で明示）---
    clutch = 0

    # --- チーム勝利貢献（省略：試合ごとの勝敗紐付けが必要なため0）---
    team_win = 0

    # --- マイナス ---
    P = c["penalty"]
    pen = 0
    if agg["ab"]:
        so_rate = agg["so"] / agg["ab"]
        pen += max(-so_rate * 10, P["so_rate_max"])
    pen += agg["errors"] * P["error_each"]

    total = content + prod + clutch + pt + db + team_win + pen

    mult = 1.0
    if need_pa and agg["pa"] < need_pa:
        mult = c["min_pa_multiplier"]

    avail = sum(v["available_max"] for v in cats.values())
    raw = total * mult
    return {
        "name": name, "team": team, "position": position,
        "raw": round(raw, 2),
        "score": round(raw / avail * 100, 2) if avail else 0,
        "available_max": avail,
        "breakdown": {"battingContent": round(content, 2), "runProduction": round(prod, 2),
                      "clutch": clutch, "playingTime": round(pt, 2),
                      "defenseBaser": round(db, 2), "teamWin": team_win,
                      "penalty": round(pen, 2)},
        "stat_line": (f"{agg['games']}試合 {agg['ab']}打数{agg['hits']}安打 "
                      f"打率{fmt_rate(agg['avg'])}" if agg['avg'] is not None else f"{agg['games']}試合") +
                     (f" OPS{fmt_rate(agg['ops'])}" if agg['ops'] is not None else "") +
                     f" {agg['hr']}本 {agg['rbi']}点",
        "reasons": reasons, "minus_reasons": [],
        "under_min_pa": need_pa and agg["pa"] < need_pa,
    }


def aggregate_pitcher_period(rows):
    outs = sum(r.get("outs") or 0 for r in rows)
    er = sum(r.get("earned_runs") or 0 for r in rows)
    ra = sum(r.get("runs_allowed") or 0 for r in rows)
    so = sum(r.get("so") or 0 for r in rows)
    bb = sum(r.get("bb") or 0 for r in rows)
    ha = sum(r.get("hits_allowed") or 0 for r in rows)
    hra = sum(r.get("hr_allowed") or 0 for r in rows)
    saves = sum(1 for r in rows if "Ｓ" in (r.get("decision") or "") or "S" in (r.get("decision") or ""))
    wins = sum(1 for r in rows if "勝" in (r.get("decision") or ""))
    losses = sum(1 for r in rows if "敗" in (r.get("decision") or ""))
    qs = sum(1 for r in rows if (r.get("outs") or 0) >= 18 and (r.get("earned_runs") or 0) <= 3)
    hqs = sum(1 for r in rows if (r.get("outs") or 0) >= 21 and (r.get("earned_runs") or 0) <= 2)
    holds = sum(r.get("_hold_count") or 0 for r in rows)
    ip = outs / 3
    return {
        "games": len(rows), "outs": outs, "ip": ip, "er": er, "ra": ra,
        "so": so, "bb": bb, "ha": ha, "hra": hra, "saves": saves,
        "wins": wins, "losses": losses, "qs": qs, "hqs": hqs, "holds": holds,
        "era": round(er * 9 / ip, 2) if ip else None,
        "whip": round((ha + bb) / ip, 2) if ip else None,
        "k9": round(so * 9 / ip, 2) if ip else None,
    }


def score_weekly_starter(name, team, agg, league_pool, cfg=None):
    cfg = cfg or load_config()
    c = cfg["weekly_starter"]
    cats = c["categories"]
    reasons = []
    era = _percentile_score([p["era"] for p in league_pool], agg["era"],
                             cats["era"]["max"], higher_is_better=False)
    innings = min(agg["ip"] / 6, 1) * cats["innings"]["max"] if agg["games"] else 0
    whip = _percentile_score([p["whip"] for p in league_pool], agg["whip"],
                              cats["whip"]["max"], higher_is_better=False)
    k = _percentile_score([p["so"] for p in league_pool], agg["so"], cats["strikeout"]["max"])
    qs = min((agg["hqs"] * 1.5 + agg["qs"]) / max(agg["games"], 1), 1) * cats["qs"]["max"]
    wc = min(agg["wins"] / max(agg["games"], 1), 1) * cats["winContrib"]["max"]
    total = era + innings + whip + k + qs + wc
    if agg["wins"]:
        reasons.append(f"{agg['wins']}勝{agg['losses']}敗")
    if agg["hqs"]:
        reasons.append(f"HQS{agg['hqs']}")
    elif agg["qs"]:
        reasons.append(f"QS{agg['qs']}")
    avail = sum(v["available_max"] for v in cats.values())
    return {
        "name": name, "team": team, "role": "先発",
        "raw": round(total, 2), "score": round(total / avail * 100, 2) if avail else 0,
        "available_max": avail,
        "breakdown": {"era": round(era, 2), "innings": round(innings, 2),
                      "whip": round(whip, 2), "strikeout": round(k, 2),
                      "qs": round(qs, 2), "winContrib": round(wc, 2)},
        "stat_line": (f"{agg['games']}試合 {agg['ip']:.1f}回 防御率"
                      f"{agg['era']:.2f}" if agg['era'] is not None else f"{agg['games']}試合")
                     + f" {agg['so']}奪三振 WHIP{agg['whip']:.2f}" if agg['whip'] is not None else "",
        "reasons": reasons, "minus_reasons": [],
    }


def score_weekly_reliever(name, team, agg, league_pool, cfg=None):
    cfg = cfg or load_config()
    c = cfg["weekly_reliever"]
    cats = c["categories"]
    reasons = []
    scoreless = (1 - agg["er"] / max(agg["ip"], 0.1)) if agg["ip"] else 0
    sr = max(scoreless, 0) * cats["scorelessRate"]["max"]
    holds = min(agg["holds"] / 3, 1) * cats["holds"]["max"]
    content = _percentile_score([p["whip"] for p in league_pool], agg["whip"],
                                 cats["content"]["max"], higher_is_better=False)
    appear = min(agg["games"] / 4, 1) * cats["appearances"]["max"]
    total = sr + holds + content + appear
    mult = 1.0
    if agg["games"] == 1:
        mult = c["single_appearance_multiplier"]
    elif agg["games"] == 2:
        mult = c["two_appearance_multiplier"]
    if agg["holds"]:
        reasons.append(f"ホールド{agg['holds']}")
    avail = sum(v["available_max"] for v in cats.values())
    raw = total * mult
    return {
        "name": name, "team": team, "role": "中継ぎ",
        "raw": round(raw, 2), "score": round(raw / avail * 100, 2) if avail else 0,
        "available_max": avail,
        "breakdown": {"scorelessRate": round(sr, 2), "holds": round(holds, 2),
                      "content": round(content, 2), "appearances": round(appear, 2)},
        "stat_line": f"{agg['games']}試合 {agg['ip']:.1f}回 自責{agg['er']} {agg['so']}奪三振",
        "reasons": reasons, "minus_reasons": [],
    }


def score_weekly_closer(name, team, agg, league_pool, cfg=None):
    cfg = cfg or load_config()
    c = cfg["weekly_closer"]
    cats = c["categories"]
    reasons = []
    saves = min(agg["saves"] / 3, 1) * cats["saves"]["max"]
    save_rate = cats["saveRate"]["max"] if agg["saves"] and agg["losses"] == 0 else 0
    scoreless = max(1 - agg["er"] / max(agg["ip"], 0.1), 0) * cats["scorelessRate"]["max"] if agg["ip"] else 0
    whip = _percentile_score([p["whip"] for p in league_pool], agg["whip"],
                              cats["whip"]["max"], higher_is_better=False)
    k = _percentile_score([p["so"] for p in league_pool], agg["so"], cats["strikeout"]["max"])
    appear = min(agg["games"] / 3, 1) * cats["appearances"]["max"]
    total = saves + save_rate + scoreless + whip + k + appear
    if agg["saves"]:
        reasons.append(f"セーブ{agg['saves']}")
    avail = sum(v["available_max"] for v in cats.values())
    return {
        "name": name, "team": team, "role": "抑え",
        "raw": round(total, 2), "score": round(total / avail * 100, 2) if avail else 0,
        "available_max": avail,
        "breakdown": {"saves": round(saves, 2), "saveRate": round(save_rate, 2),
                      "scorelessRate": round(scoreless, 2), "whip": round(whip, 2),
                      "strikeout": round(k, 2), "appearances": round(appear, 2)},
        "stat_line": f"{agg['games']}試合 {agg['saves']}S 自責{agg['er']} {agg['so']}奪三振",
        "reasons": reasons, "minus_reasons": [],
    }
