"""NotebookLM / Google Sheets向けの軽量CSVを生成する。

既存の集計済みJSON/CSVだけを読み、欠損値は推測しない。
出力先は公開URLを固定できる data/notebooklm/。
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

JST = timezone(timedelta(hours=9))
REQUIRED = (
    "batting.csv", "pitching.csv", "teams.csv", "games_latest.csv",
    "matchups.csv", "roster.csv", "form_players.csv", "metadata.csv",
    "glossary.csv",
)

HEADERS = {
    "batting.csv": ["シーズン", "集計基準日", "選手名", "球団", "背番号", "守備位置", "試合数", "打席数", "打数", "安打", "本塁打", "打点", "盗塁", "打率", "出塁率", "長打率", "OPS", "wRC+推定", "W-Impact", "直近5試合OPS", "一軍登録日数", "サンプル不足フラグ", "データの説明"],
    "pitching.csv": ["シーズン", "集計基準日", "選手名", "球団", "背番号", "投手役割", "登板数", "投球回", "打者数", "勝", "敗", "セーブ", "ホールド", "防御率", "FIP", "WHIP", "奪三振率", "与四球率", "W-Impact", "直近5登板W-Impact", "一軍登録日数", "サンプル不足フラグ", "データの説明"],
    "teams.csv": ["シーズン", "集計基準日", "リーグ", "順位", "球団", "試合数", "勝", "敗", "引分", "勝率", "ゲーム差", "得点", "失点", "得失点差", "本塁打", "盗塁", "チーム打率", "チーム防御率", "残り試合", "データの説明"],
    "games_latest.csv": ["シーズン", "集計基準日", "試合日", "試合ID", "ビジター", "ホーム", "球場", "ビジター得点", "ホーム得点", "勝者", "試合状態", "勝利投手", "敗戦投手", "セーブ投手", "データの説明"],
    "matchups.csv": ["シーズン", "集計基準日", "打者名", "打者球団", "投手名", "投手球団", "対戦打席", "対戦打数", "安打", "本塁打", "四球", "三振", "打率", "出塁率", "長打率", "OPS", "サンプル不足フラグ", "データの説明"],
    "roster.csv": ["シーズン", "集計基準日", "選手名", "球団", "背番号", "守備位置", "一軍登録状況", "一軍登録日数", "直近登録日", "直近抹消日", "データの説明"],
    "form_players.csv": ["シーズン", "集計基準日", "選手名", "球団", "区分", "期間", "期間終了日", "試合数または登板数", "打席数", "投球回", "OPS", "防御率", "W-Impact", "W-Value", "調子判定", "サンプル不足フラグ", "データの説明"],
    "metadata.csv": ["項目", "値", "説明"],
    "glossary.csv": ["指標", "対象", "意味", "注意点"],
}


def read_json(path: Path, required: bool = False) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"必須データがありません: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSONを読み込めません: {path}: {exc}") from exc


def write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    rows = list(rows)
    header = HEADERS[path.name]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def latest_season(base: Path, requested: str | None) -> str:
    if requested:
        return str(requested)
    seasons = sorted(p.name for p in base.iterdir() if p.is_dir() and p.name.isdigit())
    if not seasons:
        raise FileNotFoundError(f"シーズンディレクトリがありません: {base}")
    return seasons[-1]


def latest_date(season_dir: Path, standings: dict[str, Any], trends: dict[str, Any]) -> str:
    candidates = [trends.get("latest_date")]
    stamp = standings.get("updated_at")
    if stamp:
        candidates.append(str(stamp)[:10])
    dataset = season_dir / "dataset" / "games.csv"
    if dataset.exists():
        with dataset.open(encoding="utf-8-sig", newline="") as fh:
            candidates.extend(row.get("date") for row in csv.DictReader(fh))
    return max((str(x) for x in candidates if x), default="")


def last_trend(trends: dict[str, Any], key: str, kind: str, window: str = "5") -> dict[str, Any]:
    values = (((trends.get("players") or {}).get(key) or {}).get(kind) or {}).get(window) or []
    return values[-1] if values else {}


def roster_info(season_dir: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    summary = read_json(season_dir / "roster" / "registration.json")
    latest = summary.get("latest_date")
    daily = read_json(season_dir / "roster" / "daily" / f"{latest}.json") if latest else {}
    current = {str(p.get("npb_id") or p.get("name")): p for p in daily.get("registered", [])}
    players = summary.get("players") or summary.get("player_days") or []
    by_key: dict[str, dict[str, Any]] = {}
    for p in players:
        for key in (p.get("npb_id"), p.get("player_id"), p.get("name")):
            if key:
                by_key[str(key)] = p
    return by_key, list(current.values()), summary


def registration_days(index: dict[str, dict[str, Any]], player: dict[str, Any]) -> Any:
    item = index.get(str(player.get("player_id"))) or index.get(str(player.get("name"))) or {}
    return item.get("registered_days", item.get("days", ""))


def impact_maps(impact: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        {str(x.get("player_key")): x for x in impact.get("batters", [])},
        {str(x.get("player_key")): x for x in impact.get("pitchers", [])},
    )


def build_batting(players: list[dict[str, Any]], season: str, cutoff: str, trends: dict[str, Any], impacts: dict[str, Any], roster: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    seen = set()
    for p in players:
        b = p.get("batting") or {}
        key = str(p.get("key") or p.get("player_id") or p.get("name"))
        # NotebookLMのGoogle Sheets上限を考慮し、極小サンプルは対話用出力から除く。
        if int(b.get("pa") or 0) < 20 or key in seen:
            continue
        seen.add(key)
        recent = last_trend(trends, str(p.get("key")), "batter")
        pa = int(b.get("pa") or 0)
        rows.append({
            "シーズン": season, "集計基準日": cutoff, "選手名": p.get("name", ""), "球団": p.get("team", ""),
            "背番号": p.get("number", ""), "守備位置": p.get("position", ""), "試合数": b.get("games", ""), "打席数": pa,
            "打数": b.get("ab", ""), "安打": b.get("hits", ""), "本塁打": b.get("hr", ""), "打点": b.get("rbi", ""),
            "盗塁": b.get("sb", ""), "打率": b.get("avg", ""), "出塁率": b.get("obp", ""), "長打率": b.get("slg", ""),
            "OPS": b.get("ops", ""), "wRC+推定": b.get("wrc_plus_est", ""), "W-Impact": (impacts.get(str(p.get("key"))) or {}).get("w_rating", ""),
            "直近5試合OPS": recent.get("ops", ""), "一軍登録日数": registration_days(roster, p),
            "サンプル不足フラグ": "はい" if pa < 50 else "いいえ",
            "データの説明": "シーズン累計の打撃成績。直近値は出場した直近5試合。",
        })
    return sorted(rows, key=lambda x: (str(x["球団"]), -int(x["打席数"] or 0), str(x["選手名"])))


def pitcher_role(p: dict[str, Any], impact: dict[str, Any]) -> str:
    role = (impact.get("stats") or {}).get("role") or impact.get("role")
    if role:
        return str(role)
    q = p.get("pitching") or {}
    starts = int(q.get("starts") or 0)
    games = int(q.get("games") or 0)
    if starts and starts >= games / 2:
        return "先発"
    if q.get("saves"):
        return "救援（抑え含む）"
    return "救援" if games else ""


def build_pitching(players: list[dict[str, Any]], season: str, cutoff: str, trends: dict[str, Any], impacts: dict[str, Any], roster: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    seen = set()
    for p in players:
        q = p.get("pitching") or {}
        key = str(p.get("key") or p.get("player_id") or p.get("name"))
        if int(q.get("games") or 0) < 3 or key in seen:
            continue
        seen.add(key)
        imp = impacts.get(str(p.get("key"))) or {}
        recent = last_trend(trends, str(p.get("key")), "pitcher")
        games = int(q.get("games") or 0)
        rows.append({
            "シーズン": season, "集計基準日": cutoff, "選手名": p.get("name", ""), "球団": p.get("team", ""),
            "背番号": p.get("number", ""), "投手役割": pitcher_role(p, imp), "登板数": games, "投球回": q.get("innings", ""),
            "打者数": q.get("batters_faced", ""), "勝": q.get("wins", ""), "敗": q.get("losses", ""), "セーブ": q.get("saves", ""),
            "ホールド": q.get("holds", q.get("holds_est", "")), "防御率": q.get("era", ""), "FIP": q.get("fip", ""), "WHIP": q.get("whip", ""),
            "奪三振率": q.get("k9", ""), "与四球率": q.get("bb9", ""), "W-Impact": imp.get("w_rating", ""),
            "直近5登板W-Impact": recent.get("w_rating", ""), "一軍登録日数": registration_days(roster, p),
            "サンプル不足フラグ": "はい" if games < 10 else "いいえ",
            "データの説明": "シーズン累計の投手成績。直近値は登板した直近5試合。",
        })
    return sorted(rows, key=lambda x: (str(x["球団"]), -int(x["登板数"] or 0), str(x["選手名"])))


def build_teams(standings: dict[str, Any], season: str, cutoff: str) -> list[dict[str, Any]]:
    rows = []
    for league_key, league_name in (("central", "セ"), ("pacific", "パ")):
        for t in standings.get(league_key, []):
            rows.append({
                "シーズン": season, "集計基準日": cutoff, "リーグ": league_name, "順位": t.get("rank", ""), "球団": t.get("team", ""),
                "試合数": t.get("games", ""), "勝": t.get("wins", ""), "敗": t.get("losses", ""), "引分": t.get("ties", ""),
                "勝率": t.get("pct", ""), "ゲーム差": t.get("gb", ""), "得点": t.get("runs", ""), "失点": t.get("runs_allowed", ""),
                "得失点差": (t.get("runs") - t.get("runs_allowed")) if isinstance(t.get("runs"), (int, float)) and isinstance(t.get("runs_allowed"), (int, float)) else "",
                "本塁打": t.get("hr", ""), "盗塁": t.get("sb", ""), "チーム打率": t.get("avg", ""), "チーム防御率": t.get("era", ""),
                "残り試合": t.get("games_left", ""), "データの説明": "NPB順位表の集計値。",
            })
    return rows


def build_games(season_dir: Path, season: str, cutoff: str, days: int = 7) -> list[dict[str, Any]]:
    path = season_dir / "dataset" / "games.csv"
    if not path.exists():
        raise FileNotFoundError(f"必須データがありません: {path}")
    floor = datetime.fromisoformat(cutoff).date() - timedelta(days=days - 1) if cutoff else None
    rows = []
    seen = set()
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for g in csv.DictReader(fh):
            game_id = str(g.get("game_id") or "")
            if not g.get("date") or not game_id or game_id in seen:
                continue
            if floor and g.get("date") and datetime.fromisoformat(g["date"]).date() < floor:
                continue
            seen.add(game_id)
            rows.append({
                "シーズン": season, "集計基準日": cutoff, "試合日": g.get("date", ""), "試合ID": g.get("game_id", ""),
                "ビジター": g.get("away", ""), "ホーム": g.get("home", ""), "球場": g.get("stadium", ""),
                "ビジター得点": g.get("away_score", ""), "ホーム得点": g.get("home_score", ""), "勝者": g.get("winner", ""),
                "試合状態": g.get("state", ""), "勝利投手": g.get("win_pitcher", ""), "敗戦投手": g.get("lose_pitcher", ""),
                "セーブ投手": g.get("save_pitcher", ""), "データの説明": f"集計基準日までの直近{days}日間の試合。",
            })
    return sorted(rows, key=lambda x: (str(x["試合日"]), str(x["試合ID"])), reverse=True)


def build_matchups(season_dir: Path, season: str, cutoff: str, minimum_pa: int = 5, per_batter: int = 3) -> list[dict[str, Any]]:
    root = season_dir / "matchups" / "batters"
    if not root.exists():
        return []
    rows = []
    seen = set()
    for path in sorted(root.glob("*.json")):
        data = read_json(path)
        batter = data.get("player") or {}
        opponents = sorted(data.get("opponents", []), key=lambda x: int(x.get("pa") or 0), reverse=True)
        for p in [x for x in opponents if int(x.get("pa") or 0) >= minimum_pa][:per_batter]:
            pa = int(p.get("pa") or 0)
            pair = (str(batter.get("key") or batter.get("name")), str(p.get("player_key") or p.get("name")))
            if pair in seen:
                continue
            seen.add(pair)
            rows.append({
                "シーズン": season, "集計基準日": cutoff, "打者名": batter.get("name", ""), "打者球団": batter.get("team", ""),
                "投手名": p.get("name", ""), "投手球団": p.get("team", ""), "対戦打席": pa, "対戦打数": p.get("ab", ""),
                "安打": p.get("hits", ""), "本塁打": p.get("hr", ""), "四球": p.get("bb", ""), "三振": p.get("so", ""),
                "打率": p.get("avg", ""), "出塁率": p.get("obp", ""), "長打率": p.get("slg", ""), "OPS": p.get("ops", ""),
                "サンプル不足フラグ": "はい" if pa < 10 else "いいえ",
                "データの説明": "当該打者と投手のシーズン対戦成績。打席数が少ない値の解釈に注意。",
            })
    return rows


def build_roster(current: list[dict[str, Any]], summary: dict[str, Any], season: str, cutoff: str) -> list[dict[str, Any]]:
    history = summary.get("players") or summary.get("player_days") or []
    if history:
        source = history
    else:
        source = current
    rows = []
    current_ids = {str(x.get("npb_id") or x.get("name")) for x in current}
    recent_floor = datetime.fromisoformat(cutoff).date() - timedelta(days=30) if cutoff else None
    for p in source:
        key = str(p.get("npb_id") or p.get("player_id") or p.get("name"))
        is_current = bool(p.get("current_registered", key in current_ids))
        removed = p.get("last_deregistered")
        if not is_current and recent_floor and (not removed or datetime.fromisoformat(removed).date() < recent_floor):
            continue
        rows.append({
            "シーズン": season, "集計基準日": cutoff, "選手名": p.get("name", ""), "球団": p.get("team", ""),
            "背番号": p.get("number", ""), "守備位置": p.get("position", ""),
            "一軍登録状況": "登録中" if is_current else "登録外", "一軍登録日数": p.get("registered_days", p.get("days", "")),
            "直近登録日": p.get("last_registered", p.get("first_registered", "")), "直近抹消日": p.get("last_deregistered", ""),
            "データの説明": "NPB出場選手登録の取得済み日を集計。未取得日は登録日数に含めない。",
        })
    return sorted(rows, key=lambda x: (str(x["球団"]), 0 if x["一軍登録状況"] == "登録中" else 1, str(x["選手名"])))


def form_label(rating: Any) -> str:
    if not isinstance(rating, (int, float)):
        return "判定不可"
    return "好調" if rating >= 115 else ("不調" if rating <= 85 else "標準")


def build_form(trends: dict[str, Any], season: str, cutoff: str) -> list[dict[str, Any]]:
    candidates = []
    for player in (trends.get("players") or {}).values():
        for kind, label in (("batter", "野手"), ("pitcher", "投手")):
            for window in ("5", "15"):
                values = ((player.get(kind) or {}).get(window) or [])
                if not values:
                    continue
                x = values[-1]
                sample = int(x.get("pa") or x.get("games") or 0)
                candidates.append({
                    "シーズン": season, "集計基準日": cutoff, "選手名": player.get("name", ""), "球団": player.get("team", ""),
                    "区分": label, "期間": f"直近{window}出場", "期間終了日": x.get("date", ""), "試合数または登板数": x.get("games", ""),
                    "打席数": x.get("pa", ""), "投球回": x.get("innings", ""), "OPS": x.get("ops", ""), "防御率": x.get("era", ""),
                    "W-Impact": x.get("w_rating", ""), "W-Value": x.get("w_value", ""), "調子判定": form_label(x.get("w_rating")),
                    "サンプル不足フラグ": "はい" if sample < (15 if kind == "batter" else 5) else "いいえ",
                    "データの説明": "欠場を数えず、実際に出場または登板した試合による移動集計。",
                })
    # 区分・期間ごとに好調上位40人、不調下位40人を残す。
    rows = []
    for kind in ("野手", "投手"):
        for period in ("直近5出場", "直近15出場"):
            group = [x for x in candidates if x["区分"] == kind and x["期間"] == period and isinstance(x["W-Impact"], (int, float))]
            group.sort(key=lambda x: float(x["W-Impact"]), reverse=True)
            selected = group[:25] + group[-25:]
            seen = set()
            for row in selected:
                key = (row["選手名"], row["球団"], row["区分"], row["期間"])
                if key not in seen:
                    rows.append(row)
                    seen.add(key)
    return sorted(rows, key=lambda x: (str(x["区分"]), str(x["期間"]), -float(x["W-Impact"])))


def glossary() -> list[dict[str, str]]:
    return [
        {"指標": "OPS", "対象": "野手", "意味": "出塁率と長打率の合計。打撃の総合的な強さの目安。", "注意点": "走塁・守備・球場差を含まない。打席数が少ないと変動が大きい。"},
        {"指標": "wRC+推定", "対象": "野手", "意味": "リーグ平均を100とした得点創出力の推定値。", "注意点": "球場補正なし。固定線形加重による独自推定で公式記録ではない。"},
        {"指標": "FIP", "対象": "投手", "意味": "本塁打・四死球・奪三振を中心に投手の責任範囲を評価する指標。", "注意点": "守備や打球結果を十分に反映しない。定数は収集データに基づく。"},
        {"指標": "WHIP", "対象": "投手", "意味": "1投球回あたりに許した走者（安打と与四球）。", "注意点": "失点そのものや長打の重みは表さない。"},
        {"指標": "W-Impact", "対象": "野手・投手", "意味": "平均100として打撃・投球・役割・出場継続性などを統合したサイト独自の総合貢献指数。", "注意点": "WAR・UZR・NPB公式指標ではない。守備範囲は含まず、取得できない項目は推測していない。役割別・リーグ別の相対評価。"},
        {"指標": "W-Value", "対象": "野手・投手", "意味": "W-Impactの評価と出場量を組み合わせた累積的な貢献量。", "注意点": "サイト独自値で、異なる版の値を直接比較しない。"},
        {"指標": "サンプル不足フラグ", "対象": "全般", "意味": "打席・登板・対戦数が少なく値が安定しにくいことを示す。", "注意点": "『はい』の行は結論ではなく参考情報として扱う。"},
        {"指標": "一軍登録日数", "対象": "選手", "意味": "取得できた日次の出場選手登録一覧に掲載された日数。", "注意点": "取得欠損日は数えない。支配下登録日数や実働日数ではない。"},
    ]


def validate_outputs(out_dir: Path) -> None:
    errors = []
    for name in REQUIRED:
        path = out_dir / name
        if not path.exists():
            errors.append(f"不足: {name}")
            continue
        with path.open(encoding="utf-8-sig", newline="") as fh:
            reader = csv.reader(fh)
            actual = next(reader, [])
        if actual != HEADERS[name]:
            errors.append(f"ヘッダー不一致: {name}")
    if errors:
        raise ValueError("NotebookLM CSV検証失敗: " + "; ".join(errors))


def build(base: Path, out_dir: Path, season_arg: str | None = None) -> dict[str, int]:
    season = latest_season(base, season_arg)
    season_dir = base / season
    players_doc = read_json(season_dir / "players" / "stats.json", required=True)
    standings = read_json(season_dir / "standings.json", required=True)
    trends = read_json(season_dir / "w_impact_trends.json")
    impact = read_json(season_dir / "w_impact.json")
    cutoff = latest_date(season_dir, standings, trends)
    roster_index, current_roster, roster_summary = roster_info(season_dir)
    bat_impact, pit_impact = impact_maps(impact)
    players = players_doc.get("players") or []
    tables = {
        "batting.csv": build_batting(players, season, cutoff, trends, bat_impact, roster_index),
        "pitching.csv": build_pitching(players, season, cutoff, trends, pit_impact, roster_index),
        "teams.csv": build_teams(standings, season, cutoff),
        "games_latest.csv": build_games(season_dir, season, cutoff),
        "matchups.csv": build_matchups(season_dir, season, cutoff),
        "roster.csv": build_roster(current_roster, roster_summary, season, cutoff),
        "form_players.csv": build_form(trends, season, cutoff),
        "metadata.csv": [
            {"項目": "シーズン", "値": season, "説明": "対象シーズン"},
            {"項目": "集計基準日", "値": cutoff, "説明": "収録データの最終試合日または更新日"},
            {"項目": "生成日時", "値": datetime.now(JST).isoformat(timespec="seconds"), "説明": "CSVを生成した日本時間"},
            {"項目": "公開元", "値": "https://github.com/wocchi09/npb-data", "説明": "データと生成コードのリポジトリ"},
            {"項目": "欠損方針", "値": "空欄", "説明": "取得できない値は推測せず空欄にする"},
            {"項目": "選手データ制限", "値": "野手20打席以上・投手3登板以上", "説明": "Google Sheetsソースのトークン上限を考慮"},
            {"項目": "対戦データ制限", "値": "各打者の対戦打席上位3投手（5打席以上）", "説明": "Google Sheetsソースのトークン上限を考慮"},
            {"項目": "登録データ制限", "値": "現在登録中または直近30日以内に抹消", "説明": "直近の登録・抹消を優先"},
            {"項目": "調子データ制限", "値": "区分・期間ごとの上位25人と下位25人", "説明": "好調・不調を質問しやすくしつつデータ量を抑制"},
            {"項目": "試合データ期間", "値": "直近7日", "説明": "Google Sheetsソースのトークン上限を考慮"},
        ],
        "glossary.csv": glossary(),
    }
    counts = {name: write_csv(out_dir / name, rows) for name, rows in tables.items()}
    validate_outputs(out_dir)
    for name, count in counts.items():
        print(f"[INFO] {name}: {count:,}行")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season")
    parser.add_argument("--base", default="data")
    parser.add_argument("--output", default="data/notebooklm")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    out_dir = Path(args.output)
    try:
        if args.validate_only:
            validate_outputs(out_dir)
            print("[INFO] NotebookLM CSV: 必須ファイルとヘッダーは正常です")
        else:
            build(Path(args.base), out_dir, args.season)
    except (FileNotFoundError, ValueError, OSError) as exc:
        print(f"[ERROR] {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
