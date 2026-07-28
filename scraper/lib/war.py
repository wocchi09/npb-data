"""
守備貢献を含まない簡易WARの計算。

取得データには打球位置・速度などがないため、野手の守備貢献
（R_field）は推測せず、打撃・走塁・併殺・守備位置補正だけを扱う。
正式なWARではなく、サイト内で同じシーズン・リーグの選手を比較する
ための参考値である。
"""

from __future__ import annotations

from typing import Any

from .normalize import team_info


# 162試合換算で一般的に使われる守備位置補正値。
# NPBは143試合制なので、実際の出場試合数 / 143 で按分する。
POSITION_ADJUSTMENT = {
    "捕": 12.5,
    "一": -12.5,
    "二": 2.5,
    "三": 2.5,
    "遊": 7.5,
    "左": -7.5,
    "中": 2.5,
    "右": -7.5,
    "指": -17.5,
    "打指": -17.5,
    "打": -17.5,
}

NPB_SEASON_GAMES = 143
DEFAULT_RPW = 10.0


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _league(player: dict) -> str | None:
    league = team_info(player.get("team")).get("league")
    return league if league in ("セ", "パ") else None


def _innings(value: Any, outs: Any = None) -> float:
    """野球表記の投球回（例: 12.2）を実投球回へ変換する。"""
    if outs is not None:
        out_count = int(_number(outs))
        if out_count > 0:
            return out_count / 3
    if value in (None, ""):
        return 0.0
    text = str(value)
    if "." not in text:
        return _number(text)
    whole, fraction = text.split(".", 1)
    if fraction in ("0", "1", "2"):
        return _number(whole) + int(fraction) / 3
    return _number(value)


def league_run_env(players: list[dict]) -> dict[str, dict[str, float]]:
    """
    リーグ別の得点環境とRPW（1勝に必要な得点）を求める。

    チーム試合数を直接受け取らないため、打席数からリーグの攻撃試合数を
    推定する。1チーム1試合あたり38打席を基準とし、得点環境に応じて
    RPWを調整する。サンプル不足時は10点を使用する。
    """
    totals = {
        "セ": {"runs": 0.0, "pa": 0.0},
        "パ": {"runs": 0.0, "pa": 0.0},
    }
    for player in players:
        league = _league(player)
        batting = player.get("batting") or {}
        if league and batting:
            totals[league]["runs"] += _number(batting.get("runs"))
            totals[league]["pa"] += _number(batting.get("pa"))

    result = {}
    for league, total in totals.items():
        estimated_team_games = total["pa"] / 38.0 if total["pa"] else 0.0
        runs_per_team_game = (
            total["runs"] / estimated_team_games if estimated_team_games else 0.0
        )
        # 1勝に必要な得点は両軍合計の1試合得点のおおむね1.1倍。
        rpw = runs_per_team_game * 2 * 1.1 if runs_per_team_game else DEFAULT_RPW
        # シーズン序盤など極端な値にならない範囲に制限する。
        rpw = min(max(rpw, 7.0), 13.0)
        result[league] = {
            "runs": int(total["runs"]),
            "pa": int(total["pa"]),
            "runs_per_team_game": round(runs_per_team_game, 3),
            "rpw": round(rpw, 3),
        }
    return result


def replacement_level(
    players: list[dict], team_games: dict[str, int]
) -> dict[str, dict[str, float | int | None]]:
    """
    リーグ別のリプレイスメントOPSを求める。

    各チームの規定打席（試合数×3.1）未満かつ打席のある野手を対象に、
    少打席選手の過大な影響を避けるため打席加重平均を使う。
    """
    samples = {"セ": [], "パ": []}
    for player in players:
        league = _league(player)
        batting = player.get("batting") or {}
        pa = _number(batting.get("pa"))
        ops = batting.get("ops")
        games = _number(team_games.get(player.get("team")))
        if (
            league
            and pa > 0
            and ops is not None
            and (not games or pa < games * 3.1)
        ):
            samples[league].append((_number(ops), pa))

    result = {}
    for league, rows in samples.items():
        total_pa = sum(pa for _, pa in rows)
        ops = sum(value * pa for value, pa in rows) / total_pa if total_pa else None
        result[league] = {
            "ops": round(ops, 3) if ops is not None else None,
            "players": len(rows),
            "pa": int(total_pa),
        }
    return result


def replacement_fip(
    fip_constants: dict[str, dict | None]
) -> dict[str, dict[str, float | None]]:
    """リーグ平均防御率+1.00をリプレイスメントFIPとする。"""
    result = {}
    for league in ("セ", "パ"):
        values = fip_constants.get(league) or {}
        league_era = values.get("league_era")
        result[league] = {
            "league_era": _number(league_era) if league_era is not None else None,
            "fip": round(_number(league_era) + 1.0, 2)
            if league_era is not None
            else None,
        }
    return result


def _position_adjustment(player: dict, games: float) -> float:
    positions = player.get("positions") or []
    if positions:
        total_games = sum(max(_number(p.get("games")), 0) for p in positions)
        if total_games:
            weighted = sum(
                POSITION_ADJUSTMENT.get(p.get("pos"), 0.0)
                * max(_number(p.get("games")), 0)
                for p in positions
            ) / total_games
            return weighted * games / NPB_SEASON_GAMES
    return POSITION_ADJUSTMENT.get(player.get("position"), 0.0) * games / NPB_SEASON_GAMES


def calc_batter_war(
    player: dict,
    run_env: dict[str, dict[str, float]],
    replacement: dict[str, dict[str, float | int | None]],
    team_games: dict[str, int],
) -> dict | None:
    """1選手の守備抜き簡易野手WARを返す。"""
    league = _league(player)
    batting = player.get("batting") or {}
    pa = _number(batting.get("pa"))
    ops = batting.get("ops")
    replacement_ops = (replacement.get(league) or {}).get("ops") if league else None
    if not league or pa <= 0 or ops is None or replacement_ops is None:
        return None

    games = _number(batting.get("games"))
    r_bat = (_number(ops) - _number(replacement_ops)) * pa * 0.2
    r_baser = _number(batting.get("sb")) * 0.2
    r_dp = 0.0  # 併殺打の集計値がないため推測しない
    r_pos = _position_adjustment(player, games)
    rpw = _number((run_env.get(league) or {}).get("rpw"), DEFAULT_RPW)
    runs_above_replacement = r_bat + r_baser + r_dp + r_pos
    war = runs_above_replacement / rpw if rpw else 0.0

    required_pa = _number(team_games.get(player.get("team"))) * 3.1
    return {
        "war": round(war, 2),
        "qualified": bool(required_pa and pa >= required_pa),
        "components": {
            "r_bat": round(r_bat, 2),
            "r_baser": round(r_baser, 2),
            "r_dp": round(r_dp, 2),
            "r_pos": round(r_pos, 2),
            "runs_above_replacement": round(runs_above_replacement, 2),
            "replacement_ops": round(_number(replacement_ops), 3),
            "rpw": round(rpw, 3),
            "pa": int(pa),
        },
    }


def calc_pitcher_war(
    player: dict,
    run_env: dict[str, dict[str, float]],
    replacement: dict[str, dict[str, float | None]],
) -> dict | None:
    """1選手のFIPベース簡易投手WARを返す。"""
    league = _league(player)
    pitching = player.get("pitching") or {}
    fip = pitching.get("fip")
    innings = _innings(pitching.get("innings"), pitching.get("outs"))
    replacement_value = (replacement.get(league) or {}).get("fip") if league else None
    if not league or innings <= 0 or fip is None or replacement_value is None:
        return None

    rpw = _number((run_env.get(league) or {}).get("rpw"), DEFAULT_RPW)
    runs_above_replacement = (
        (_number(replacement_value) - _number(fip)) * innings / 9
    )
    war = runs_above_replacement / rpw if rpw else 0.0
    return {
        "war": round(war, 2),
        "components": {
            "fip": round(_number(fip), 2),
            "replacement_fip": round(_number(replacement_value), 2),
            "innings": round(innings, 1),
            "runs_above_replacement": round(runs_above_replacement, 2),
            "rpw": round(rpw, 3),
        },
    }
