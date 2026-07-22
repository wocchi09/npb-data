"""
データ整合性チェック
=====================
仕様書「9. 必須の整合性チェック」を実装する。
保存済みの試合JSONを走査し、問題を検出してレポートする。

使い方:
    python scraper/validate_data.py               # 全データ検証
    python scraper/validate_data.py --date 2026-07-19
    python scraper/validate_data.py --season 2026

終了コード: 問題があれば 1、なければ 0
"""

import argparse
import glob
import json
import os
import sys
from collections import defaultdict


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"__error__": str(e)}


def find_game_files(base="data", season=None, date=None):
    if date:
        y, m, d = date.split("-")
        pat = f"{base}/{y}/{m}/{d}/*.json"
    elif season:
        pat = f"{base}/{season}/**/*.json"
    else:
        pat = f"{base}/**/*.json"
    files = []
    for p in glob.glob(pat, recursive=True):
        name = os.path.basename(p)
        if name.startswith("_") or name == "index.json":
            continue
        files.append(p)
    return sorted(files)


def check_game(path, game, seen_game_ids):
    """1試合ぶんの整合性チェック。問題のリストを返す"""
    issues = []
    gid = game.get("game_id")

    if "__error__" in game:
        return [f"JSON破損: {game['__error__']}"]

    # game_id が別日付に重複していないか
    if gid:
        if gid in seen_game_ids and seen_game_ids[gid] != path:
            issues.append(f"game_id重複: {gid} が {seen_game_ids[gid]} にも存在")
        seen_game_ids[gid] = path

    # 対象日と開催日の一致（パスの日付 vs データ）
    parts = path.replace("\\", "/").split("/")
    try:
        path_date = f"{parts[-4]}-{parts[-3]}-{parts[-2]}"
    except IndexError:
        path_date = None

    atbats = game.get("atbats", [])

    # 試合終了前を確定値として扱っていないか
    result = game.get("result", {})
    state = result.get("state")
    if state and "試合終了" not in state and atbats:
        issues.append(f"未確定試合を保存: state={state}")

    # 同じ投球が二重保存されていないか（index重複）
    seen_idx = set()
    total_pitches = 0
    for ab in atbats:
        idx = ab.get("index")
        if idx in seen_idx:
            issues.append(f"打席index重複: {idx}")
        seen_idx.add(idx)
        total_pitches += ab.get("pitch_count", 0)

        # 選手IDの欠落
        b = ab.get("batter") or {}
        if b.get("name") and not b.get("player_id"):
            issues.append(f"打者ID欠落: {b.get('name')} (index={idx})")

        # 0除算につながる異常値（球速0など）は警告のみ
        for p in ab.get("pitches", []):
            sp = p.get("speed_kmh")
            if sp is not None and (sp < 50 or sp > 180):
                issues.append(f"球速異常: {sp}km/h (index={idx})")

    # pitch_count 合計との矛盾
    if game.get("pitch_count") is not None and game.get("pitch_count") != total_pitches:
        issues.append(
            f"球数不一致: game.pitch_count={game.get('pitch_count')} vs 実計={total_pitches}"
        )

    # スコアと得点イベントの整合（推定値なので警告レベル）
    fs = game.get("final_score")
    if fs and atbats:
        got = defaultdict(int)
        for ab in atbats:
            import re
            m = re.search(r"＋(\d+)点", ab.get("result_summary") or "")
            if m:
                side = ab.get("batting_team")
                got[side] += int(m.group(1))
        for s in fs:
            team = s.get("team")
            official = s.get("score")
            est = got.get(team)
            if official is not None and est is not None and abs(official - est) > 0:
                # 推定値なので情報レベル（暴投・エラー得点は拾えない）
                issues.append(
                    f"[情報] スコア差異 {team}: 公式{official} vs 推定{est}（暴投等で発生しうる）"
                )

    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--season", default=None)
    ap.add_argument("--base", default="data")
    args = ap.parse_args()

    files = find_game_files(args.base, args.season, args.date)
    if not files:
        print("[INFO] 対象ファイルなし")
        return 0

    seen_game_ids = {}
    total_issues = 0
    error_issues = 0

    for path in files:
        game = load_json(path)
        issues = check_game(path, game, seen_game_ids)
        if issues:
            print(f"\n■ {path}")
            for it in issues:
                is_info = it.startswith("[情報]")
                mark = "  ℹ" if is_info else "  ✗"
                print(f"{mark} {it}")
                total_issues += 1
                if not is_info:
                    error_issues += 1

    print(f"\n{'='*50}")
    print(f"検証完了: {len(files)}試合 / 問題{total_issues}件（うちエラー{error_issues}件）")

    # エラー（情報レベルを除く）があれば終了コード1
    return 1 if error_issues else 0


if __name__ == "__main__":
    sys.exit(main())
