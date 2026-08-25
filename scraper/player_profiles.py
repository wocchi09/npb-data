"""NPB公式の個人年度別成績から現役選手のプロフィールと通算成績を取得する。

入力は ``data/masters/npb_roster.json``。公式選手IDがある選手だけを対象にし、
取得できない値を0で補完しない。過去に取得済みの選手で通信・解析に失敗した場合は、
前回値を残して ``stale`` を付ける。

使い方:
    python scraper/player_profiles.py
    python scraper/player_profiles.py --team ソフトバンク
    python scraper/player_profiles.py --limit 5 --sleep 0
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

import requests
from bs4 import BeautifulSoup


JST = timezone(timedelta(hours=9))
PROFILE_URL = "https://npb.jp/bis/players/{npb_id}.html"
YAHOO_PROFILE_URL = "https://baseball.yahoo.co.jp/npb/player/{player_id}/top"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}
DEFAULT_SLEEP_SEC = 2.0

PITCHING_FIELDS = {
    "登板": "games",
    "勝利": "wins",
    "敗北": "losses",
    "セーブ": "saves",
    "H": "holds",
    "HP": "hold_points",
    "完投": "complete_games",
    "完封勝": "shutouts",
    "無四球": "no_walk_games",
    "勝率": "win_pct",
    "打者": "batters_faced",
    "投球回": "innings",
    "安打": "hits_allowed",
    "本塁打": "home_runs_allowed",
    "四球": "walks",
    "死球": "hit_batters",
    "三振": "strikeouts",
    "暴投": "wild_pitches",
    "ボーク": "balks",
    "失点": "runs",
    "自責点": "earned_runs",
    "防御率": "era",
}

BATTING_FIELDS = {
    "試合": "games",
    "打席": "plate_appearances",
    "打数": "at_bats",
    "得点": "runs",
    "安打": "hits",
    "二塁打": "doubles",
    "三塁打": "triples",
    "本塁打": "home_runs",
    "塁打": "total_bases",
    "打点": "runs_batted_in",
    "盗塁": "stolen_bases",
    "盗塁刺": "caught_stealing",
    "犠打": "sacrifice_hits",
    "犠飛": "sacrifice_flies",
    "四球": "walks",
    "死球": "hit_by_pitch",
    "三振": "strikeouts",
    "併殺打": "grounded_into_double_plays",
    "打率": "batting_average",
    "長打率": "slugging_percentage",
    "出塁率": "on_base_percentage",
}

RATE_KEYS = {
    "win_pct", "era", "batting_average", "slugging_percentage",
    "on_base_percentage",
}


def clean(value: str | None) -> str:
    return " ".join((value or "").replace("\u3000", " ").split())


def iso_birthdate(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", value)
    if not match:
        match = re.search(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", value)
    if not match:
        return None
    return f"{int(match.group(1)):04d}-{int(match.group(2)):02d}-{int(match.group(3)):02d}"


def typed_value(key: str, value: str) -> Any:
    text = clean(value).replace(",", "")
    if not text or text == "-":
        return None
    if key == "innings":
        return text.replace(" ", "")
    if key in RATE_KEYS:
        try:
            return float(text)
        except ValueError:
            return None
    try:
        return int(text)
    except ValueError:
        return None


def parse_total_table(soup: BeautifulSoup, table_id: str, field_map: dict[str, str]) -> dict | None:
    table = soup.select_one(f"table#{table_id}")
    if table is None or table.thead is None or table.tfoot is None:
        return None
    headers = [clean(cell.get_text("", strip=True)) for cell in table.thead.find_all("th")]
    total_row = table.tfoot.find("tr")
    if total_row is None:
        return None
    # 投球回セル内には小数部表示用の入れ子tableがあるため、直下セルだけを読む。
    cells = [clean(cell.get_text("", strip=True)) for cell in total_row.find_all(["th", "td"], recursive=False)]
    if len(headers) != len(cells):
        return None
    result = {}
    for header, value in zip(headers, cells):
        key = field_map.get(header)
        if key:
            result[key] = typed_value(key, value)
    return result or None


def parse_yearly_table(soup: BeautifulSoup, table_id: str, field_map: dict[str, str]) -> list[dict]:
    """年度別表をページ表示順のまま返す。移籍年の同一年複数行も保持する。"""
    table = soup.select_one(f"table#{table_id}")
    if table is None or table.thead is None or table.tbody is None:
        return []
    headers = [clean(cell.get_text("", strip=True)) for cell in table.thead.find_all("th")]
    rows = []
    for tr in table.tbody.find_all("tr", recursive=False):
        cells = [clean(cell.get_text("", strip=True)) for cell in tr.find_all(["th", "td"], recursive=False)]
        if len(headers) != len(cells):
            continue
        record = {}
        for header, value in zip(headers, cells):
            if header == "年度":
                record["year"] = value
            elif header == "所属球団":
                record["team"] = value
            else:
                key = field_map.get(header)
                if key:
                    record[key] = typed_value(key, value)
        if record.get("year") and record.get("team"):
            rows.append(record)
    return rows


def parse_career_teams(soup: BeautifulSoup) -> list[str]:
    teams = []
    for table_id in ("tablefix_p", "tablefix_b"):
        table = soup.select_one(f"table#{table_id}")
        if table is None or table.tbody is None:
            continue
        for row in table.tbody.find_all("tr", recursive=False):
            cell = row.select_one("td.team")
            team = clean(cell.get_text("", strip=True)) if cell else ""
            if team and team not in teams:
                teams.append(team)
    return teams


def parse_profile(html: str, npb_id: str, roster_player: dict | None = None) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    roster_player = roster_player or {}
    bio = {}
    for row in soup.select("#pc_bio tr"):
        th, td = row.find("th"), row.find("td")
        if th and td:
            bio[clean(th.get_text("", strip=True))] = clean(td.get_text("", strip=True))

    name_node = soup.select_one("#pc_v_name li#pc_v_name")
    kana_node = soup.select_one("#pc_v_kana")
    team_node = soup.select_one("#pc_v_team")
    number_node = soup.select_one("#pc_v_no")
    name = clean(name_node.get_text("", strip=True)) if name_node else clean(roster_player.get("name"))
    if not name:
        raise ValueError("選手名を取得できません")

    height_cm = weight_kg = None
    size_match = re.search(r"(\d+)cm\s*[／/]\s*(\d+)kg", bio.get("身長／体重", ""))
    if size_match:
        height_cm, weight_kg = int(size_match.group(1)), int(size_match.group(2))

    birthdate = iso_birthdate(bio.get("生年月日")) or iso_birthdate(roster_player.get("birthdate"))
    pitching = parse_total_table(soup, "tablefix_p", PITCHING_FIELDS)
    batting = parse_total_table(soup, "tablefix_b", BATTING_FIELDS)
    yearly_pitching = parse_yearly_table(soup, "tablefix_p", PITCHING_FIELDS)
    yearly_batting = parse_yearly_table(soup, "tablefix_b", BATTING_FIELDS)
    source_url = PROFILE_URL.format(npb_id=npb_id)
    return {
        "npb_id": str(npb_id),
        "name": name,
        "reading": clean(kana_node.get_text("", strip=True)) if kana_node else None,
        "team": clean(roster_player.get("team")) or (clean(team_node.get_text("", strip=True)) if team_node else None),
        "official_team_name": clean(team_node.get_text("", strip=True)) if team_node else None,
        "number": clean(roster_player.get("number")) or (clean(number_node.get_text("", strip=True)) if number_node else None),
        "position": bio.get("ポジション") or None,
        "throws_bats": bio.get("投打") or None,
        "height_cm": height_cm,
        "weight_kg": weight_kg,
        "birthdate": birthdate,
        "career": bio.get("経歴") or None,
        "draft": bio.get("ドラフト") or None,
        # NPB個人成績ページには出身地がない。Yahoo!の選手IDを確認できた場合だけ後段で補完する。
        "birthplace": None,
        "birthplace_source_url": None,
        "yahoo_player_id": None,
        "career_teams": parse_career_teams(soup),
        "career_pitching": pitching,
        "career_batting": batting,
        "yearly_pitching": yearly_pitching,
        "yearly_batting": yearly_batting,
        "has_career_pitching": pitching is not None,
        "has_career_batting": batting is not None,
        "source_url": source_url,
        "fetched_at": datetime.now(JST).isoformat(),
        "stale": False,
    }


def fetch_profile(npb_id: str, session: requests.Session | None = None) -> str:
    client = session or requests
    response = client.get(PROFILE_URL.format(npb_id=npb_id), headers=HEADERS, timeout=30)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def fetch_yahoo_profile(player_id: str, session: requests.Session | None = None) -> str:
    client = session or requests
    response = client.get(YAHOO_PROFILE_URL.format(player_id=player_id), headers=HEADERS, timeout=30)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def parse_yahoo_birthplace(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for item in soup.select(".bb-profile__item"):
        title = item.select_one(".bb-profile__title") or item.find("dt")
        value = item.select_one(".bb-profile__text") or item.find("dd")
        if title and value and clean(title.get_text("", strip=True)) == "出身地":
            return clean(value.get_text("", strip=True)) or None
    return None


NAME_VARIANTS = str.maketrans({
    "髙": "高", "﨑": "崎", "濵": "浜", "濱": "浜", "邉": "辺", "邊": "辺",
    "齋": "斎", "齊": "斉", "澤": "沢", "栁": "柳", "德": "徳", "眞": "真",
})


def normalized_name(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").translate(NAME_VARIANTS)
    return re.sub(r"[\s・.．,，]", "", text).lower()


def yahoo_player_index(players_master: dict) -> tuple[dict, dict]:
    """(氏名,球団)と、氏名が一意な場合の2経路でYahoo選手IDを引けるようにする。"""
    by_name_team = {}
    by_name_candidates = {}
    for player in players_master.get("players", []):
        player_id = player.get("player_id")
        name_key = normalized_name(player.get("name"))
        if not player_id or not name_key:
            continue
        team = clean(player.get("team"))
        by_name_team[(name_key, team)] = str(player_id)
        by_name_candidates.setdefault(name_key, set()).add(str(player_id))
    by_unique_name = {
        name: next(iter(ids)) for name, ids in by_name_candidates.items() if len(ids) == 1
    }
    return by_name_team, by_unique_name


def load_json(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def collect(
    roster_path: str = "data/masters/npb_roster.json",
    out_path: str = "data/masters/player_profiles.json",
    players_path: str = "data/masters/players.json",
    team: str | None = None,
    limit: int | None = None,
    sleep_sec: float = DEFAULT_SLEEP_SEC,
    yahoo_sleep_sec: float = 1.0,
) -> dict:
    roster = load_json(roster_path, {})
    roster_players = [p for p in roster.get("players", []) if p.get("npb_id")]
    if team:
        roster_players = [p for p in roster_players if p.get("team") == team]
    if limit is not None:
        roster_players = roster_players[: max(0, limit)]
    if not roster_players:
        raise RuntimeError("取得対象の公式選手IDがありません")

    previous = load_json(out_path, {})
    previous_by_id = {str(p.get("npb_id")): p for p in previous.get("players", []) if p.get("npb_id")}
    yahoo_by_name_team, yahoo_by_unique_name = yahoo_player_index(load_json(players_path, {}))
    output_by_id = dict(previous_by_id) if (team or limit is not None) else {}
    failures = []
    enrichment_failures = []
    session = requests.Session()

    for index, roster_player in enumerate(roster_players, 1):
        npb_id = str(roster_player["npb_id"])
        try:
            html = fetch_profile(npb_id, session)
            profile = parse_profile(html, npb_id, roster_player)
            old = previous_by_id.get(npb_id) or {}
            name_key = normalized_name(profile.get("name") or roster_player.get("name"))
            yahoo_id = (
                old.get("yahoo_player_id")
                or yahoo_by_name_team.get((name_key, clean(roster_player.get("team"))))
                or yahoo_by_unique_name.get(name_key)
            )
            profile["yahoo_player_id"] = str(yahoo_id) if yahoo_id else None

            # 出身地は変更しないため、一度取得できた値は再利用して外部アクセスを抑える。
            if old.get("birthplace"):
                profile["birthplace"] = old["birthplace"]
                profile["birthplace_source_url"] = old.get("birthplace_source_url")
            elif yahoo_id:
                try:
                    yahoo_html = fetch_yahoo_profile(str(yahoo_id), session)
                    birthplace = parse_yahoo_birthplace(yahoo_html)
                    if birthplace:
                        profile["birthplace"] = birthplace
                        profile["birthplace_source_url"] = YAHOO_PROFILE_URL.format(player_id=yahoo_id)
                    else:
                        enrichment_failures.append({
                            "npb_id": npb_id, "yahoo_player_id": str(yahoo_id),
                            "name": profile.get("name"), "error": "出身地を確認できませんでした",
                        })
                except Exception as exc:
                    enrichment_failures.append({
                        "npb_id": npb_id, "yahoo_player_id": str(yahoo_id),
                        "name": profile.get("name"), "error": str(exc),
                    })
                if yahoo_sleep_sec > 0:
                    time.sleep(yahoo_sleep_sec)
            output_by_id[npb_id] = profile
            print(f"[INFO] {index}/{len(roster_players)} {roster_player.get('name')}: 取得")
        except Exception as exc:  # 個別失敗で全選手を失わない
            failures.append({"npb_id": npb_id, "name": roster_player.get("name"), "error": str(exc)})
            old = previous_by_id.get(npb_id)
            if old:
                old = dict(old)
                old["stale"] = True
                old["last_error"] = str(exc)
                output_by_id[npb_id] = old
            print(f"[WARN] {index}/{len(roster_players)} {roster_player.get('name')}: {exc}")
        if sleep_sec > 0 and index < len(roster_players):
            time.sleep(sleep_sec)

    players = sorted(output_by_id.values(), key=lambda p: (p.get("team") or "", p.get("name") or ""))
    payload = {
        "updated_at": datetime.now(JST).isoformat(),
        "source": "https://npb.jp/bis/players/",
        "enrichment_source": "https://baseball.yahoo.co.jp/npb/player/",
        "scope": "NPB公式選手IDのある現役支配下選手。出身地は確認できたYahoo選手IDから補完し、未取得値は推測しない。",
        "count": len(players),
        "birthplace_count": sum(1 for player in players if player.get("birthplace")),
        "requested_count": len(roster_players),
        "failure_count": len(failures),
        "failures": failures,
        "enrichment_failure_count": len(enrichment_failures),
        "enrichment_failures": enrichment_failures,
        "players": players,
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    temp_path = out_path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, out_path)
    print(f"[INFO] {len(players)}人を {out_path} に保存（今回失敗 {len(failures)}件）")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--roster", default="data/masters/npb_roster.json")
    parser.add_argument("--out", default="data/masters/player_profiles.json")
    parser.add_argument("--players", default="data/masters/players.json", help="Yahoo選手IDを含む選手マスター")
    parser.add_argument("--team", default=None, help="内部球団名（例: ソフトバンク）")
    parser.add_argument("--limit", type=int, default=None, help="動作確認用の取得人数上限")
    parser.add_argument("--sleep", type=float, default=DEFAULT_SLEEP_SEC, help="選手ごとの待機秒数")
    parser.add_argument("--yahoo-sleep", type=float, default=1.0, help="Yahoo初回取得時の待機秒数")
    args = parser.parse_args()
    payload = collect(
        args.roster, args.out, args.players, args.team, args.limit,
        max(0, args.sleep), max(0, args.yahoo_sleep),
    )
    # 一部失敗は前回値を残すため成功扱い。全件失敗かつ前回値なしだけ失敗にする。
    return 1 if payload["failure_count"] == payload["requested_count"] and not payload["players"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
