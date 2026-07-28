"""共通の走塁イベント抽出・選手解決・得点換算。

盗塁成功は公式ボックススコアを正とする。盗塁失敗と走塁死は
result_detail に選手名と明確な根拠語がある場合だけ採用し、
通常のタッチアウトからは推測しない。
"""

from __future__ import annotations

import re
from collections import defaultdict

from .normalize import clean_name, normalize_team, player_key


SB_RUN_VALUE = 0.20
CS_RUN_VALUE = -0.40
BASERUNNING_OUT_VALUE = -0.40

EVENT_RUN_VALUES = {
    "stolen_base": SB_RUN_VALUE,
    "caught_stealing": CS_RUN_VALUE,
    "baserunning_out": BASERUNNING_OUT_VALUE,
}

_NAME_VARIANTS = str.maketrans({
    "髙": "高", "﨑": "崎", "濵": "浜", "濱": "浜",
    "邉": "辺", "邊": "辺", "齋": "斎", "澤": "沢",
})
_CAUGHT_STEALING = re.compile(r"盗塁失敗[（(]([^）)]+)[）)]")
_BASERUNNING_OUT = re.compile(
    r"(?:暴走|ボーンヘッド|オーバーラン|けん制飛び出し|飛び出し|"
    r"挟まれる|打球判断を誤る|慌てて戻る|走路をはみ出る|"
    r"ベースコーチャーと接触)[（(]([^）)]+)[）)]"
)


def normalize_runner_name(value):
    return re.sub(r"[\s\u3000]", "", str(value or "")).translate(_NAME_VARIANTS)


def _string_id(value):
    return str(value) if value not in (None, "") else None


def players_from_game(game):
    """公式打撃行から、その試合で名前解決に使う選手一覧を作る。"""
    out = []
    box = game.get("boxscore") or {}
    teams = {
        "away": normalize_team(game.get("away")),
        "home": normalize_team(game.get("home")),
    }
    for side in ("away", "home"):
        for row in ((box.get("batting") or {}).get(side) or []):
            name = clean_name(row.get("name"))
            key = player_key(row.get("player_id"), name)
            if name and key:
                out.append({
                    "key": key,
                    "player_id": row.get("player_id"),
                    "name": name,
                    "team": teams[side],
                })
    return out


def _player_index(players):
    by_team = defaultdict(list)
    for player in players or []:
        if player.get("key") and player.get("name") and player.get("team"):
            by_team[normalize_team(player["team"])].append(player)
    return by_team


def _resolve(by_team, team, token):
    token = normalize_runner_name(token)
    candidates = []
    for player in by_team.get(normalize_team(team), []):
        full = normalize_runner_name(player.get("name"))
        if full == token or full.startswith(token):
            candidates.append(player)
    return candidates[0] if len(candidates) == 1 else None


def collect_game_runner_events(game, players=None, date=None):
    """1試合を、選手を特定できた走塁イベントの行へ変換する。"""
    players = list(players or players_from_game(game))
    by_team = _player_index(players)
    gid = game.get("game_id")
    rows = []
    diag = {
        "details_scanned": 0,
        "stolen_base": 0,
        "caught_stealing": 0,
        "baserunning_out": 0,
        "unresolved": 0,
        "overturned_skipped": 0,
    }

    # 盗塁成功は公式ボックススコアの選手別件数を使用する。
    box = game.get("boxscore") or {}
    teams = {
        "away": normalize_team(game.get("away")),
        "home": normalize_team(game.get("home")),
    }
    for side in ("away", "home"):
        team = teams[side]
        for batter in ((box.get("batting") or {}).get(side) or []):
            count = int(batter.get("sb") or 0)
            key = player_key(batter.get("player_id"), batter.get("name"))
            for sequence in range(1, count + 1):
                rows.append({
                    "date": date,
                    "game_id": gid,
                    "inning": None,
                    "top_bottom": None,
                    "batting_team": team,
                    "player": clean_name(batter.get("name")),
                    "player_id": _string_id(batter.get("player_id")),
                    "player_key": key,
                    "event_type": "stolen_base",
                    "event_sequence": str(sequence),
                    "run_value": SB_RUN_VALUE,
                    "result_detail": "",
                    "source": "official_boxscore",
                })
                diag["stolen_base"] += 1

    for ab_index, ab in enumerate(game.get("atbats") or [], start=1):
        detail = str(ab.get("result_detail") or "")
        if not detail:
            continue
        diag["details_scanned"] += 1
        if "判定覆る" in detail:
            diag["overturned_skipped"] += 1
            continue

        caught_names = set(_CAUGHT_STEALING.findall(detail))
        out_names = set(_BASERUNNING_OUT.findall(detail)) - caught_names
        for event_type, names in (
            ("caught_stealing", caught_names),
            ("baserunning_out", out_names),
        ):
            for token in names:
                player = _resolve(by_team, ab.get("batting_team"), token)
                if not player:
                    diag["unresolved"] += 1
                    continue
                rows.append({
                    "date": date,
                    "game_id": gid,
                    "inning": ab.get("inning"),
                    "top_bottom": ab.get("top_bottom"),
                    "batting_team": normalize_team(ab.get("batting_team")),
                    "player": player.get("name"),
                    "player_id": _string_id(player.get("player_id")),
                    "player_key": player.get("key"),
                    "event_type": event_type,
                    "event_sequence": str(ab.get("index") or ab_index),
                    "run_value": EVENT_RUN_VALUES[event_type],
                    "result_detail": detail,
                    "source": "result_detail_high_confidence",
                })
                diag[event_type] += 1
    return rows, diag


def aggregate_runner_events(events):
    """イベント行を選手別件数・得点へ集約する。"""
    out = defaultdict(lambda: {
        "sb": 0,
        "caught_stealing": 0,
        "baserunning_outs": 0,
        "baserunning_runs": 0.0,
    })
    for event in events or []:
        key = event.get("player_key")
        if not key:
            continue
        event_type = event.get("event_type")
        if event_type == "stolen_base":
            out[key]["sb"] += 1
        elif event_type == "caught_stealing":
            out[key]["caught_stealing"] += 1
        elif event_type == "baserunning_out":
            out[key]["baserunning_outs"] += 1
        out[key]["baserunning_runs"] += float(
            event.get("run_value", EVENT_RUN_VALUES.get(event_type, 0)) or 0
        )
    for values in out.values():
        values["baserunning_runs"] = round(values["baserunning_runs"], 2)
    return out
