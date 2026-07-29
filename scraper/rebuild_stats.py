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
from lib.holds import estimate_holds
from lib.baserunning import aggregate_runner_events, collect_game_runner_events
from lib.events import classify_result
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


# 試合データではない管理ファイル（集計結果や設定）
MANAGED_FILES = {
    "index.json", "calendar.json", "no_games.json", "exclude.json",
    "standings.json", "npb_roster.json", "fip_constants.json",
        "war.json", "w_impact.json", "w_impact_trends.json",
}
MANAGED_DIRS = ("/players/", "/teams/", "/dataset/", "/masters/", "/awards/")


def _is_game_file(path: str) -> bool:
    norm = path.replace("\\", "/")
    name = norm.split("/")[-1]
    if name.startswith("_") or name in MANAGED_FILES:
        return False
    return not any(d in norm for d in MANAGED_DIRS)

def find_games(season, base="data"):
    """その年の試合JSONだけを集める（集計結果や設定ファイルは除外）"""
    return sorted(p for p in glob.glob(f"{base}/{season}/**/*.json", recursive=True)
                  if _is_game_file(p))


def is_valid_name(name) -> bool:
    """
    選手名として妥当かを判定する。
    - 空・None は不可
    - 数字だけの文字列は不可（チーム合計行を選手として拾った場合の保険）
    """
    if not name:
        return False
    s = str(name).strip()
    if not s:
        return False
    if s.replace(".", "").replace(",", "").isdigit():
        return False
    return True


def blank_batting():
    return {
        "games": 0, "pa": 0, "ab": 0, "hits": 0, "singles": 0, "ibb": 0,
        "doubles": 0, "triples": 0, "hr": 0, "rbi": 0, "bb": 0, "hbp": 0,
        "so": 0, "runs": 0, "sf": 0, "sh": 0, "gidp": 0,
        "gidp_opportunities": 0, "sb": 0, "caught_stealing": 0,
        "baserunning_outs": 0, "baserunning_runs": 0.0, "errors": 0,
    }


def blank_pitching():
    return {
        "games": 0, "batters_faced": 0, "pitches": 0, "hits_allowed": 0,
        "hr_allowed": 0, "so": 0, "bb": 0, "hbp": 0, "outs": 0,
        "runs_allowed": 0, "earned_runs": 0, "wins": 0, "losses": 0, "saves": 0,
        "holds": 0, "holds_est": 0, "relief_wins": 0,
    }


def calc_league_fip_constants(pit: dict, players: dict) -> dict:
    """
    リーグごとのFIP定数を、そのシーズンの実測値から算出する。
      FIP定数C = リーグ防御率 － (13×被本塁打 + 3×与四球 － 2×奪三振) ÷ リーグ投球回

    NPBには公式のFIP定数が無いため、セ・パそれぞれ自前で算出する
    （セ・パで投高打低の傾向が異なるため、リーグを分けて計算する）。
    シーズン序盤はサンプルが少なく値が不安定になる点に注意。
    """
    totals = {"セ": {"outs": 0, "er": 0, "hr": 0, "bb": 0, "so": 0},
              "パ": {"outs": 0, "er": 0, "hr": 0, "bb": 0, "so": 0}}
    for k, q in pit.items():
        team = (players.get(k) or {}).get("team")
        lg = team_info(team).get("league") if team else None
        if lg not in totals:
            continue
        t = totals[lg]
        t["outs"] += q.get("outs", 0)
        t["er"] += q.get("earned_runs", 0)
        t["hr"] += q.get("hr_allowed", 0)
        t["bb"] += q.get("bb", 0) + q.get("hbp", 0)
        t["so"] += q.get("so", 0)

    constants = {}
    for lg, t in totals.items():
        ip = t["outs"] / 3
        if ip <= 0:
            constants[lg] = None
            continue
        league_era = t["er"] * 9 / ip
        raw = (13 * t["hr"] + 3 * t["bb"] - 2 * t["so"]) / ip
        constants[lg] = {
            "constant": round(league_era - raw, 2),
            "league_era": round(league_era, 2),
            "innings": round(ip, 1),
            "sample_note": "序盤はサンプルが少なく変動しやすい" if ip < 300 else None,
        }
    return constants


def calc_pitching_rates(p: dict) -> dict:
    """投手の基本・率指標を計算（0除算対策込み）。"""
    outs = p.get("outs", 0)
    ip = outs / 3 if outs else 0
    bf = p.get("batters_faced", 0)
    era = round(p["earned_runs"] * 9 / ip, 2) if ip else None
    whip = round((p["hits_allowed"] + p["bb"]) / ip, 2) if ip else None
    k9 = round(p["so"] * 9 / ip, 2) if ip else None
    bb9 = round(p["bb"] * 9 / ip, 2) if ip else None
    hr9 = round(p["hr_allowed"] * 9 / ip, 2) if ip else None
    kbb = round(p["so"] / p["bb"], 2) if p["bb"] else None
    k_pct = round(p["so"] / bf, 3) if bf else None
    bb_pct = round(p["bb"] / bf, 3) if bf else None
    # FanGraphs等で使われる簡易推定式。個々の走者の生還を追跡した実測LOB%ではない。
    lob_num = p["hits_allowed"] + p["bb"] + p.get("hbp", 0) - p["runs_allowed"]
    lob_den = (
        p["hits_allowed"] + p["bb"] + p.get("hbp", 0)
        - 1.4 * p["hr_allowed"]
    )
    lob_pct_est = (
        round(max(0.0, min(1.0, lob_num / lob_den)), 3)
        if lob_den > 0 else None
    )
    # 勝率（勝敗がついた試合が1つも無ければ None）
    dec = p.get("wins", 0) + p.get("losses", 0)
    win_pct = round(p.get("wins", 0) / dec, 3) if dec else None
    return {
        "innings": f"{outs // 3}.{outs % 3}" if outs % 3 else str(outs // 3),
        "era": era, "whip": whip, "k9": k9, "bb9": bb9, "hr9": hr9,
        "k_bb": kbb, "k_pct": k_pct, "bb_pct": bb_pct,
        "lob_pct_est": lob_pct_est,
        "win_pct": win_pct,
        # ホールドポイント＝ホールド＋救援勝利（ホールドは推定値）
        "hp": (p.get("holds_est", 0) or 0) + (p.get("relief_wins", 0) or 0),
    }


def merge_official_batting(dst: dict, row: dict):
    """公式ボックススコアの打撃行を累計に加算"""
    dst["pa"] += row["ab"] + row["bb"] + row["hbp"] + row["sac"]
    dst["ab"] += row["ab"]
    dst["hits"] += row["hits"]
    dst["hr"] += row["hr"]
    dst["rbi"] += row["rbi"]
    dst["bb"] += row["bb"]
    dst["hbp"] += row["hbp"]
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
    # ホールド。取得元が記録していれば H として入るが、
    # 出していない場合は 0 のままになる（推測では埋めない）
    if "Ｈ" in d or "H" in d:
        dst["holds"] = dst.get("holds", 0) + 1


# 二塁打・三塁打は「二塁打」（漢数字）と「2塁打」（数字）の両方の表記がある。
# lib/events.py の判定と揃えるため同じパターンを使う。
_DOUBLE_RE = re.compile(r"(?:二|2|２)塁打")
_TRIPLE_RE = re.compile(r"(?:三|3|３)塁打")


def classify_batting(result_summary: str) -> dict:
    """打席結果テキストから打撃イベントを分類（取れる範囲のみ・推測で埋めない）"""
    rs = result_summary or ""
    ev = {"pa": 1, "ab": 0, "hit": 0, "single": 0, "double": 0,
          "triple": 0, "hr": 0, "bb": 0, "ibb": 0, "so": 0, "sf": 0}

    # 四死球（打数に数えない）。敬遠＝故意四球も四球に含める
    if "敬遠" in rs or "四球" in rs or "死球" in rs:
        ev["bb"] = 1
        if "敬遠" in rs or "故意四球" in rs:
            ev["ibb"] = 1
        return ev
    # 犠打・犠飛（打数に数えない。犠飛はBABIP・出塁率の分母に使うため区別する）
    if "犠飛" in rs:
        ev["sf"] = 1
        return ev
    if "犠打" in rs:
        return ev

    # ここからは打数にカウント
    ev["ab"] = 1
    if "三振" in rs:
        ev["so"] = 1
    elif "本塁打" in rs:
        ev["hit"] = ev["hr"] = 1
    elif _TRIPLE_RE.search(rs):
        ev["hit"] = ev["triple"] = 1
    elif _DOUBLE_RE.search(rs):
        ev["hit"] = ev["double"] = 1
    elif "安打" in rs and "併殺" not in rs:
        ev["hit"] = ev["single"] = 1
    return ev


def calc_rate_stats(b: dict) -> dict:
    """
    打率・出塁率・長打率・OPS・ISO・BABIPを計算（0除算対策込み）。

    単打は「安打 － 本塁打 － 二塁打 － 三塁打」から実測で求め直す。
    （二塁打・三塁打は打席テキストから復元した実測値のため、これで正確になる）
    """
    ab = b["ab"]
    pa = b["pa"]
    hits = b["hits"]
    hr = b["hr"]
    doubles = b["doubles"]
    triples = b["triples"]
    so = b["so"]
    sf = b.get("sf", 0)
    singles = max(0, hits - hr - doubles - triples)
    tb = singles + 2 * doubles + 3 * triples + 4 * hr

    avg = round(hits / ab, 3) if ab else None
    obp_den = ab + b["bb"] + b.get("hbp", 0) + sf
    obp = round((hits + b["bb"] + b.get("hbp", 0)) / obp_den, 3) if obp_den else None
    slg = round(tb / ab, 3) if ab else None
    ops = round((obp or 0) + (slg or 0), 3) if (obp is not None and slg is not None) else None
    bb_pct = round(b["bb"] / pa, 3) if pa else None
    k_pct = round(b["so"] / pa, 3) if pa else None
    bb_k = round(b["bb"] / b["so"], 2) if b["so"] else None

    # ISO（純粋な長打力） = 長打率 － 打率
    iso = round(slg - avg, 3) if (slg is not None and avg is not None) else None

    # BABIP（インプレー打球の打率） = (安打－本塁打) ÷ (打数－三振－本塁打＋犠飛)
    babip_den = ab - so - hr + sf
    babip = round((hits - hr) / babip_den, 3) if babip_den > 0 else None

    # 現在の集計列だけで再現できる古典的な得点創出・打撃総合指標。
    cs = b.get("caught_stealing", 0)
    gidp = b.get("gidp", 0)
    sh = b.get("sh", 0)
    hbp = b.get("hbp", 0)
    bb = b["bb"]
    sb = b.get("sb", 0)
    offensive_outs = ab - hits + cs + gidp + sf + sh
    rc_den = ab + bb + hbp
    rc = ((hits + bb + hbp) * tb / rc_den) if rc_den else None
    rc27 = rc * 27 / offensive_outs if rc is not None and offensive_outs > 0 else None
    xr = (
        0.50 * singles + 0.72 * doubles + 1.04 * triples + 1.44 * hr
        + 0.34 * (bb - b.get("ibb", 0) + hbp) + 0.25 * b.get("ibb", 0)
        + 0.18 * sb - 0.32 * cs - 0.09 * (ab - hits - so)
        - 0.098 * so - 0.37 * gidp + 0.37 * sf + 0.04 * sh
    )
    xr27 = xr * 27 / offensive_outs if offensive_outs > 0 else None
    gpa = ((1.8 * obp + slg) / 4) if obp is not None and slg is not None else None
    seca = (
        (tb - hits + bb + hbp + sb - cs) / ab
        if ab else None
    )
    ta_den = ab - hits + cs + gidp
    total_average = (
        (tb + bb + hbp + sb) / ta_den
        if ta_den > 0 else None
    )
    wsb = 0.20 * sb - 0.40 * cs
    ubr_est = -0.40 * b.get("baserunning_outs", 0)
    bsr_est = wsb + ubr_est

    return {"avg": avg, "obp": obp, "slg": slg, "ops": ops,
            "bb_pct": bb_pct, "k_pct": k_pct, "bb_k": bb_k, "tb": tb,
            "singles": singles, "iso": iso, "babip": babip,
            "rc": round(rc, 2) if rc is not None else None,
            "rc27": round(rc27, 2) if rc27 is not None else None,
            "xr": round(xr, 2), "xr27": round(xr27, 2) if xr27 is not None else None,
            "gpa": round(gpa, 3) if gpa is not None else None,
            "seca": round(seca, 3) if seca is not None else None,
            "ta": round(total_average, 3) if total_average is not None else None,
            "wsb": round(wsb, 2), "ubr_est": round(ubr_est, 2),
            "bsr_est": round(bsr_est, 2)}


WOBA_WEIGHTS = {
    "ubb": 0.69, "hbp": 0.72, "single": 0.89,
    "double": 1.27, "triple": 1.62, "hr": 2.10,
}
WOBA_SCALE = 1.15


def _woba_parts(b: dict) -> tuple[float, float]:
    """固定線形加重による推定wOBAの分子・分母を返す。"""
    ubb = max(0, b.get("bb", 0) - b.get("ibb", 0))
    # 公式ボックススコアの一時集計では singles が「安打－本塁打」のため、
    # 二塁打・三塁打を差し引いて真の単打数を必ずここで作り直す。
    singles = max(
        0,
        b.get("hits", 0)
        - b.get("hr", 0)
        - b.get("doubles", 0)
        - b.get("triples", 0),
    )
    numerator = (
        WOBA_WEIGHTS["ubb"] * ubb
        + WOBA_WEIGHTS["hbp"] * b.get("hbp", 0)
        + WOBA_WEIGHTS["single"] * singles
        + WOBA_WEIGHTS["double"] * b.get("doubles", 0)
        + WOBA_WEIGHTS["triple"] * b.get("triples", 0)
        + WOBA_WEIGHTS["hr"] * b.get("hr", 0)
    )
    denominator = (
        b.get("ab", 0) + ubb + b.get("hbp", 0) + b.get("sf", 0)
    )
    return numerator, denominator


def calc_league_batting_contexts(bat: dict, players: dict) -> dict:
    """セ・パ別の推定wOBA平均と1打席あたり得点を実測値から作る。"""
    totals = {
        "セ": {"woba_num": 0.0, "woba_den": 0.0, "pa": 0, "runs": 0},
        "パ": {"woba_num": 0.0, "woba_den": 0.0, "pa": 0, "runs": 0},
    }
    for key, b in bat.items():
        lg = team_info((players.get(key) or {}).get("team")).get("league")
        if lg not in totals:
            continue
        num, den = _woba_parts(b)
        totals[lg]["woba_num"] += num
        totals[lg]["woba_den"] += den
        totals[lg]["pa"] += b.get("pa", 0)
        totals[lg]["runs"] += b.get("runs", 0)
    contexts = {}
    for lg, t in totals.items():
        contexts[lg] = {
            "woba": t["woba_num"] / t["woba_den"] if t["woba_den"] else None,
            "runs_per_pa": t["runs"] / t["pa"] if t["pa"] else None,
            "pa": t["pa"],
        }
    return contexts


def calc_weighted_batting(b: dict, context: dict | None) -> dict:
    """
    固定係数による推定wOBA系指標。
    wRC+は球場補正を行わないため、正式値ではなく「球場未補正の推定値」とする。
    """
    num, den = _woba_parts(b)
    woba = num / den if den else None
    lg_woba = (context or {}).get("woba")
    runs_per_pa = (context or {}).get("runs_per_pa")
    pa = b.get("pa", 0)
    if woba is None or lg_woba is None:
        return {"woba_est": None, "wraa_est": None,
                "wrc_est": None, "wrc_plus_est": None}
    wraa = (woba - lg_woba) / WOBA_SCALE * pa
    wrc = (
        ((woba - lg_woba) / WOBA_SCALE + runs_per_pa) * pa
        if runs_per_pa is not None else None
    )
    wrc_plus = (
        100 * (((woba - lg_woba) / WOBA_SCALE + runs_per_pa) / runs_per_pa)
        if runs_per_pa and runs_per_pa > 0 else None
    )
    return {
        "woba_est": round(woba, 3),
        "wraa_est": round(wraa, 2),
        "wrc_est": round(wrc, 2) if wrc is not None else None,
        "wrc_plus_est": round(wrc_plus, 0) if wrc_plus is not None else None,
    }


# シーズン成績に含めない試合の種別。
# 交流戦は公式戦の一部なので除外しない。
EXCLUDED_TYPES = ("オールスター", "CS", "日本シリーズ")


def load_manual_exclude(season, base="data") -> dict:
    """
    自動判定で拾えない試合を手作業で除外するための設定を読む。

    data/{season}/exclude.json の例:
        {
          "dates": ["2026-07-24", "2026-07-25"],
          "date_ranges": [["2026-10-11", "2026-11-05"]],
          "game_ids": ["2021039999"]
        }
    """
    path = os.path.join(base, str(season), "exclude.json")
    if not os.path.exists(path):
        return {"dates": set(), "ranges": [], "game_ids": set()}
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except Exception as e:
        print(f"[WARN] exclude.json の読み込みに失敗: {e}")
        return {"dates": set(), "ranges": [], "game_ids": set()}
    return {
        "dates": set(d.get("dates") or []),
        "ranges": [tuple(x) for x in (d.get("date_ranges") or []) if len(x) == 2],
        "game_ids": set(str(x) for x in (d.get("game_ids") or [])),
    }


def is_manually_excluded(rule: dict, day: str | None, gid) -> bool:
    if gid is not None and str(gid) in rule["game_ids"]:
        return True
    if not day:
        return False
    if day in rule["dates"]:
        return True
    for a, b in rule["ranges"]:
        if a <= day <= b:
            return True
    return False


def rebuild(season, base="data"):
    games = find_games(season, base)
    print(f"[INFO] {season}シーズン: {len(games)}試合を再集計")
    manual = load_manual_exclude(season, base)

    players = {}       # player_key -> master info
    bat = {}           # player_key -> batting counts
    pit = {}           # player_key -> pitching counts
    team_stats = {}    # team -> counts
    holds_found = 0                 # 推定ホールドの検出数（ログ用）
    ibb_found = 0                   # 敬遠（故意四球）の検出数（ログ用）
    excluded = {}                   # 除外した試合の内訳（種別 -> 件数）
    day_excluded = {}               # 日付 -> 成績から除外した試合数
    day_excluded_type = {}          # 日付 -> 除外の理由（表示用）
    seen_game_per_player_bat = {}   # (pkey, game_id) 出場ゲーム重複防止
    seen_game_per_player_pit = {}
    pos_count = {}                  # player_key -> {守備位置: 出場数}
    runner_games = []               # 除外対象を除いた (game, date)

    # 日別の試合数を数える（打席が1つも無いファイルは試合として数えない）
    day_games = {}      # "YYYY-MM-DD" -> 有効な試合数
    day_pitches = {}    # "YYYY-MM-DD" -> 投球数
    day_files = {}      # "YYYY-MM-DD" -> ディスク上のファイル数
    day_empty = {}      # "YYYY-MM-DD" -> 打席0件のファイル数
    day_mismatch = {}   # "YYYY-MM-DD" -> 開催日がフォルダと違うファイル数
    empty_games = []    # 打席0件のファイル（過去のバグ由来のゴミ）
    seen_gid_date = {}  # game_id -> 最初に見つけた日付（別日重複の検出用）
    dup_games = []

    for path in games:
        try:
            g = load_json(path)
        except Exception as e:
            print(f"[WARN] 読み込み失敗 {path}: {e}")
            continue

        gid = g.get("game_id")
        home = normalize_team(g.get("home"))
        away = normalize_team(g.get("away"))

        # --- 日別の集計（無効なファイルは試合として数えない）---
        import re as _re
        dm = _re.search(r"/(\d{4})/(\d{2})/(\d{2})/", path.replace("\\", "/"))
        day = f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}" if dm else None
        if day:
            day_files[day] = day_files.get(day, 0) + 1

        # --- シーズン成績に含めない試合か判定する ---
        # ここでは抜けない。試合そのものは閲覧できるようにカレンダーには残し、
        # 成績の集計だけを飛ばす。
        gtype = g.get("game_type") or "公式戦"
        reason = None
        if gtype in EXCLUDED_TYPES:
            reason = gtype
        elif is_manually_excluded(manual, day, gid):
            reason = "手動指定"

        # 試合ページの開催日（game_date）がフォルダの日付と違う場合は記録する
        gdate = (g.get("game_date") or "").strip()
        if gdate and day and gdate != day:
            day_mismatch[day] = day_mismatch.get(day, 0) + 1

        n_ab = g.get("atbat_count") or len(g.get("atbats") or [])
        if n_ab <= 0:
            empty_games.append(path)
            if day:
                day_empty[day] = day_empty.get(day, 0) + 1
            continue          # 打席が無いファイルは集計対象から除外する
        if gid:
            if gid in seen_gid_date and day and seen_gid_date[gid] != day:
                dup_games.append((gid, seen_gid_date[gid], day))
            elif day:
                seen_gid_date[gid] = day
        if day:
            day_games[day] = day_games.get(day, 0) + 1
            day_pitches[day] = day_pitches.get(day, 0) + (g.get("pitch_count") or 0)

        # ここから先が成績の集計。除外対象はここで抜ける
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            if day:
                day_excluded[day] = day_excluded.get(day, 0) + 1
                day_excluded_type[day] = reason
            continue
        runner_games.append((g, day))

        for t in (home, away):
            if t and t not in team_stats:
                team_stats[t] = {"games": 0, "runs": 0, "runs_allowed": 0,
                                 "hits": 0, "hr": 0, "wins": 0, "losses": 0,
                                 "bip": 0, "bip_outs": 0}
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
            # この試合のホールドをルールから推定する（公式記録ではない）
            try:
                est_holds = estimate_holds(g)
            except Exception as e:
                print(f"[WARN] ホールド推定に失敗 {gid}: {e}")
                est_holds = {}

            for side in ("away", "home"):
                team = side_team.get(side)
                for row in (box.get("batting", {}).get(side) or []):
                    k = player_key(row.get("player_id"), row.get("name"))
                    if not k or not is_valid_name(row.get("name")):
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
                    # 守備位置の出場回数を数える（「走指」などの交代表記は先頭以外も含む）
                    ps = (row.get("position") or "").strip()
                    if ps:
                        pos_count.setdefault(k, {})
                        pos_count[k][ps] = pos_count[k].get(ps, 0) + 1
                    merge_official_batting(bat[k], row)
                    if team and team in team_stats:
                        team_stats[team]["hits"] += row.get("hits", 0)
                        team_stats[team]["hr"] += row.get("hr", 0)

                for pit_order, row in enumerate(box.get("pitching", {}).get(side) or []):
                    k = player_key(row.get("player_id"), row.get("name"))
                    if not k or not is_valid_name(row.get("name")):
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

                    # 推定ホールド（1試合1個まで）。選手IDで引き、無ければ名前で
                    pid = row.get("player_id")
                    nm_raw = row.get("name") or ""
                    nm_key = "nm:" + nm_raw.replace(" ", "").replace("　", "")
                    if (pid and est_holds.get("id:" + str(pid))) \
                            or est_holds.get(nm_key) or est_holds.get(nm_raw):
                        pit[k]["holds_est"] += 1
                        holds_found += 1
                    # 救援勝利（先発以外の勝利）＝ホールドポイントの計算に使う
                    if pit_order > 0 and "勝" in (row.get("decision") or ""):
                        pit[k]["relief_wins"] += 1

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
            if bkey and not is_valid_name(b.get("name")):
                bkey = None
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
                else:
                    # 背番号・投打は打席データにしか無いので埋める
                    if not players[bkey].get("number"):
                        players[bkey]["number"] = b.get("number")
                    if not players[bkey].get("hand"):
                        players[bkey]["hand"] = b.get("hand")

                # 敬遠・二塁打・三塁打・犠飛などは公式ボックススコアに列が無いため、
                # 公式成績を使う試合でも打席結果のテキストから常に復元する。
                # （以前は使わない試合でしか拾えておらず、長打率が過小評価されていた）
                ev_extra = classify_result(ab.get("result_summary"))
                if bkey:
                    if bkey not in bat:
                        bat[bkey] = blank_batting()
                    eb = bat[bkey]
                    if ev_extra.get("ibb"):
                        eb["ibb"] = eb.get("ibb", 0) + 1
                        ibb_found += 1
                    eb["doubles"] += ev_extra["double"]
                    eb["triples"] += ev_extra["triple"]
                    eb["sf"] = eb.get("sf", 0) + ev_extra.get("sf", 0)
                    eb["sh"] = eb.get("sh", 0) + ev_extra.get("sh", 0)
                    eb["gidp"] = eb.get("gidp", 0) + ev_extra.get("gidp", 0)
                    runners = ab.get("runners") or {}
                    count = ab.get("count") or {}
                    if (
                        runners.get("first")
                        and int(count.get("out") or 0) < 2
                        and ev_extra.get("ab")
                    ):
                        eb["gidp_opportunities"] = (
                            eb.get("gidp_opportunities", 0) + 1
                        )

                # 球団DER。四球・死球・三振・本塁打・犠打を除いた打球を分母にし、
                # 安打または相手失策にならずアウトにした打球を分子にする。
                if fteam and fteam in team_stats:
                    is_bip = bool(
                        (ev_extra.get("ab") and not ev_extra.get("so")
                         and not ev_extra.get("hr"))
                        or ev_extra.get("sf")
                    )
                    if is_bip:
                        team_stats[fteam]["bip"] += 1
                        if not ev_extra.get("hit") and not ev_extra.get("error"):
                            team_stats[fteam]["bip_outs"] += 1

                # 公式成績が無い試合のみ、残りの項目も打席結果から推定して集計
                if not used_official:
                    if bkey not in bat:
                        bat[bkey] = blank_batting()
                    if (bkey, gid) not in seen_game_per_player_bat:
                        seen_game_per_player_bat[(bkey, gid)] = True
                        bat[bkey]["games"] += 1
                    ev = ev_extra
                    bb = bat[bkey]
                    bb["pa"] += ev["pa"]; bb["ab"] += ev["ab"]
                    bb["hits"] += ev["hit"]; bb["singles"] += ev["single"]
                    # doubles/triples/sf は上ですでに加算済みなのでここでは足さない
                    bb["hr"] += ev["hr"]; bb["bb"] += ev["bb"]
                    bb["hbp"] += ev.get("hbp", 0); bb["so"] += ev["so"]
                    m = re.search(r"＋(\d+)点", ab.get("result_summary") or "")
                    if m:
                        bb["rbi"] += int(m.group(1))
                        if bteam and bteam in team_stats:
                            team_stats[bteam]["runs"] += int(m.group(1))

            # 投手：マスター情報を補完
            pkey = player_key(p.get("player_id"), p.get("name"))
            if pkey and not is_valid_name(p.get("name")):
                pkey = None
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

    # --- 共通走塁イベントを選手へ集約 ---
    runner_events = []
    runner_diag = {
        "details_scanned": 0, "stolen_base": 0, "caught_stealing": 0,
        "baserunning_out": 0, "unresolved": 0, "overturned_skipped": 0,
    }
    for game, game_day in runner_games:
        rows, diag = collect_game_runner_events(game, players.values(), game_day)
        runner_events.extend(rows)
        for key in runner_diag:
            runner_diag[key] += diag.get(key, 0)
    runner_by_player = aggregate_runner_events(runner_events)
    for key, batting in bat.items():
        running = runner_by_player.get(key) or {}
        # 盗塁成功は従来どおり公式成績を正とし、共通イベントとの不一致時も上書きしない。
        batting["caught_stealing"] = running.get("caught_stealing", 0)
        batting["baserunning_outs"] = running.get("baserunning_outs", 0)
        batting["baserunning_runs"] = round(
            (batting.get("sb", 0) * 0.20)
            - (batting["caught_stealing"] * 0.40)
            - (batting["baserunning_outs"] * 0.40),
            2,
        )

    # --- 出力を組み立て ---
    player_out = []
    skipped = 0
    # FIP定数はリーグ全体の投手成績が要るため、選手ごとの出力を作る前に計算しておく
    fip_constants = calc_league_fip_constants(pit, players)
    batting_contexts = calc_league_batting_contexts(bat, players)

    for k, info in players.items():
        # 名前が取れていない／合計行を拾ってしまった等の異常データは出力しない
        if not is_valid_name(info.get("name")):
            skipped += 1
            continue
        entry = dict(info)
        # 出場した守備位置（多い順）。最頻値を主守備位置とする
        pc = pos_count.get(k) or {}
        if pc:
            ordered = sorted(pc.items(), key=lambda x: (-x[1], x[0]))
            entry["positions"] = [{"pos": p_, "games": n_} for p_, n_ in ordered]
            entry["position"] = ordered[0][0]
        elif k in pit:
            entry["position"] = "投"
        entry["is_pitcher"] = k in pit
        if k in bat:
            lg = team_info(entry.get("team")).get("league")
            filled_bat = _fill(bat[k])
            entry["batting"] = {
                **bat[k],
                **calc_rate_stats(filled_bat),
                **calc_weighted_batting(filled_bat, batting_contexts.get(lg)),
            }
        if k in pit:
            entry["pitching"] = {**pit[k], **calc_pitching_rates(pit[k])}
            lg = team_info(entry.get("team")).get("league")
            c = fip_constants.get(lg)
            outs = pit[k].get("outs", 0)
            ip = outs / 3
            if c and c.get("constant") is not None and ip > 0:
                q = pit[k]
                fip = (13 * q.get("hr_allowed", 0) + 3 * (q.get("bb", 0) + q.get("hbp", 0))
                       - 2 * q.get("so", 0)) / ip + c["constant"]
                entry["pitching"]["fip"] = round(fip, 2)
                entry["pitching"]["fip_constant"] = c["constant"]
            else:
                entry["pitching"]["fip"] = None
        player_out.append(entry)
    player_out.sort(key=lambda x: (x.get("team") or "", x.get("name") or ""))

    # マスター（成績を除いた基本情報）
    master = [{"key": p["key"], "player_id": p["player_id"], "name": p["name"],
               "team": p["team"], "number": p["number"], "hand": p["hand"]}
              for p in player_out]

    team_out = []
    for t, s in team_stats.items():
        info = team_info(t)
        der = round(s["bip_outs"] / s["bip"], 3) if s.get("bip") else None
        team_out.append({
            "team": t, "mini": info["mini"], "league": info["league"],
            **s, "der": der,
        })
    team_out.sort(key=lambda x: (x.get("league") or "", -x.get("runs", 0)))

    # 「試合がなかった日」の記録があれば読み込む（未収集の日と区別するため）
    no_games = []
    ng_path = f"{base}/{season}/no_games.json"
    if os.path.exists(ng_path):
        try:
            with open(ng_path, encoding="utf-8") as f:
                no_games = sorted(set(json.load(f).get("dates", [])))
        except Exception as e:
            print(f"[WARN] no_games.json の読み込みに失敗: {e}")

    # 日別の試合数（ダッシュボードのカレンダー・概況が参照する正しい集計）
    total_games = sum(day_games.values())
    total_pitches = sum(day_pitches.values())
    save_json(f"{base}/{season}/calendar.json", {
        "season": season,
        "total_games": total_games,
        "total_pitches": total_pitches,
        "days": dict(sorted(day_games.items())),
        "pitches_by_day": dict(sorted(day_pitches.items())),
        "no_games": no_games,
        # 成績には入れないが試合としては見られる日（オールスターなど）
        "excluded_days": dict(sorted(day_excluded.items())),
        "excluded_types": dict(sorted(day_excluded_type.items())),
    })
    if excluded:
        detail = "・".join(f"{k}{v}件" for k, v in sorted(excluded.items()))
        print(f"[INFO] シーズン成績から除外: {sum(excluded.values())}試合（{detail}）")
    print(f"[INFO] 日別集計: {len(day_games)}日 / 有効{total_games}試合 / {total_pitches:,}球")
    if no_games:
        print(f"[INFO] 試合がなかった日として記録済み: {len(no_games)}日")

    # 日別の内訳（カレンダーと合わない原因を追えるようにする）
    all_days = sorted(set(list(day_files.keys()) + list(day_games.keys())))
    if all_days:
        print("[INFO] 日別内訳（ファイル数 / 有効 / 打席0件 / 開催日ズレ）")
        for dd in all_days:
            fnum = day_files.get(dd, 0)
            gnum = day_games.get(dd, 0)
            enum = day_empty.get(dd, 0)
            mnum = day_mismatch.get(dd, 0)
            flag = ""
            if gnum == 0:
                flag = "  ← 有効な試合が0（カレンダーに出ません）"
            elif enum or mnum:
                flag = "  ← 要確認"
            print(f"    {dd}  files={fnum:3}  valid={gnum:3}  empty={enum:3}  mismatch={mnum:3}{flag}")
    if empty_games:
        print(f"[WARN] 打席が0件のファイル {len(empty_games)}件を集計から除外しました"
              f"（例: {empty_games[0]}）")
    if dup_games:
        print(f"[WARN] 同じ試合IDが別の日にも保存されています {len(dup_games)}件"
              f"（例: {dup_games[0]}）")

    save_json(f"{base}/masters/players.json", {"count": len(master), "players": master})
    save_json(f"{base}/masters/teams.json",
              {"teams": [{"name": n, **v} for n, v in TEAMS.items()]})
    save_json(f"{base}/{season}/players/stats.json",
              {"season": season, "count": len(player_out),
               "runner_event_diagnostics": runner_diag,
               "advanced_metric_context": {
                   "woba_weights": WOBA_WEIGHTS,
                   "woba_scale": WOBA_SCALE,
                   "league": {
                       lg: {
                           "woba": round(c["woba"], 3) if c.get("woba") is not None else None,
                           "runs_per_pa": (
                               round(c["runs_per_pa"], 4)
                               if c.get("runs_per_pa") is not None else None
                           ),
                           "pa": c.get("pa", 0),
                       }
                       for lg, c in batting_contexts.items()
                   },
                   "note": "wOBA系は固定線形加重、wRC+は球場未補正の推定値",
               },
               "players": player_out})
    save_json(f"{base}/{season}/teams/stats.json",
              {"season": season, "teams": team_out})

    if skipped:
        print(f"[WARN] 名前が取得できない選手データ {skipped}件をスキップしました")
    # FIP定数を診断用に保存（画面の説明表示にも使う）
    save_json(f"{base}/{season}/fip_constants.json", {
        "season": season, "constants": fip_constants,
        "formula": "FIP = (13*被本塁打 + 3*(与四球+与死球) - 2*奪三振) / 投球回 + リーグ定数",
    })
    print(f"[INFO] FIP定数: セ={((fip_constants.get('セ') or {}).get('constant'))} "
          f"パ={((fip_constants.get('パ') or {}).get('constant'))}")
    print(f"[INFO] 推定ホールド: {holds_found}件を検出")
    print(
        f"[INFO] 走塁イベント: 盗塁{runner_diag['stolen_base']} / "
        f"盗塁失敗{runner_diag['caught_stealing']} / "
        f"走塁死{runner_diag['baserunning_out']} "
        f"（選手未解決{runner_diag['unresolved']}）"
    )
    if ibb_found:
        print(f"[INFO] 敬遠（故意四球）: {ibb_found}件を検出")
    else:
        print("[INFO] 敬遠（故意四球）: 0件（取得元が「敬遠」と表記していない可能性があります）")
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
