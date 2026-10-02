"""Collect structured Sportsnavi transfer rows, without inferring official NPB status."""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

try:
    from .movement_details import NIKKAN, SALARY_INDEX, parse_nikkan, parse_salaries, salary_links, merge_and_enrich
except ImportError:
    from movement_details import NIKKAN, SALARY_INDEX, parse_nikkan, parse_salaries, salary_links, merge_and_enrich

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://baseball.yahoo.co.jp/npb/transfer"
TEAMS = ("阪神", "DeNA", "巨人", "中日", "広島", "ヤクルト", "ソフトバンク", "日本ハム", "オリックス", "楽天", "西武", "ロッテ")
JST = timezone(timedelta(hours=9))


def category(status, note):
    text = status + " " + note
    if "引退" in text:
        return "引退"
    if "契約解除" in text:
        return "契約解除"
    if "FA" in text or "ＦＡ" in text:
        if "取得" in text:
            return "FA権取得"
        if "宣言" in text:
            return "FA宣言"
        if "移籍" in text:
            return "FA移籍"
        return "FA（区分未確認）"
    if "自由契約" in text or "戦力外" in text:
        return "自由契約"
    if "トレード" in text:
        return "トレード"
    if "育成" in text:
        return "育成契約関連"
    if "移籍" in text:
        return "移籍"
    if "契約を結ば" in text or "来季契約なし" in text:
        return "来季契約なし"
    return status if status in ("入団", "退団") else "その他"


def destination(note):
    # Only extract an explicitly directed destination. Never guess from team mentions.
    match = re.search(r"(?:移籍先|入団先)\s*[:：]\s*([^、。\n]+)", note)
    if not match:
        match = re.search(r"(?:^|[、。\s])([^、。\s]+?)(?:へ|に)(?:移籍|入団)", note)
    return match.group(1).strip() if match else None


def parse_transfers(html):
    soup = BeautifulSoup(html, "html.parser")
    found, records = set(), {}
    for heading in soup.select("h3"):
        team = heading.get_text(strip=True)
        if team not in TEAMS:
            continue
        section = heading.find_parent("section")
        if section is None or team in found:
            raise ValueError("球団別入退団ブロックの形式が不正です")
        found.add(team)
        table = section.select_one("table.bb-transferTable")
        if table is None:
            if "データがありません" not in section.get_text():
                raise ValueError(f"{team}: 表もデータなし表示も確認できません")
            continue
        if [th.get_text(strip=True) for th in table.select("thead th")] != ["更新日", "状況", "選手名", "守備", "備考"]:
            raise ValueError("入退団表の列定義が変更されています")
        for tr in table.select("tbody tr"):
            cells = tr.find_all("td", recursive=False)
            if len(cells) != 5:
                raise ValueError("入退団表の列数が不正です")
            stamp, status, player, position, note = [c.get_text(" ", strip=True) for c in cells]
            parts = re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})", stamp)
            if not parts:
                raise ValueError("更新日を確認できません")
            updated = date(*map(int, parts.groups())).isoformat()
            link = cells[2].select_one("a")
            href = link.get("href", "") if link else ""
            match = re.fullmatch(r"/npb/player/(\d+)/top", href)
            name = link.get_text(" ", strip=True) if link else player.replace("※", "").strip()
            if not name or not status:
                raise ValueError("選手名または状況がありません")
            player_id = match.group(1) if match else None
            identity = f"{team}|{player_id or name}|{updated}|{status}|{note}"
            key = hashlib.sha256(identity.encode()).hexdigest()[:20]
            records[key] = {
                "id": key, "player_id": player_id, "name": name, "team": team,
                "updated_date": updated, "status": status, "category": category(status, note),
                "position": position, "development_player": "※" in player,
                "note": note.replace("戦力外通告", "来季契約なしの通知").replace("戦力外", "来季契約なし"),
                "destination": destination(note), "source_note": note,
                "source_url": SOURCE + ("#" + section["id"] if section.get("id", "").isdigit() else ""),
                "source": "スポーツナビ 入退団情報", "confirmation": "スポナビ掲載（NPB公示とは別）",
                "profile_url": "https://baseball.yahoo.co.jp" + href if match else None,
            }
    if found != set(TEAMS):
        raise ValueError("12球団すべての入退団欄を確認できません（前回データを保持）")
    return sorted(records.values(), key=lambda r: (r["updated_date"], r["team"], r["name"]), reverse=True)


def read_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def collect_snapshot(fetch, url, parse, old, now):
    try:
        rows = parse(fetch(url))
        return {"url": url, "checked_at": now, "last_success_at": now, "stale": False, "rows": rows}
    except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
        print(f"WARNING {url}: {exc}")
        return {**old, "url": url, "checked_at": now, "stale": True,
                "error": "今回の取得・形式確認に失敗。前回取得分を表示します。" if old.get("rows") else "未取得。元サイトをご確認ください。",
                "rows": old.get("rows", [])}


def main():
    now_dt = datetime.now(JST)
    now = now_dt.isoformat(timespec="seconds")
    output = ROOT / "data" / "player_movements.json"
    old = read_json(output, {})
    snapshots = old.get("snapshots", {})
    if not snapshots and old.get("movements"):
        snapshots["sportsnavi"] = {"rows": old["movements"], "last_success_at": old.get("checked_at")}
    session = requests.Session()
    session.headers["User-Agent"] = "NPB-data public movement collector (github.com/wocchi09/npb-data)"

    def fetch(url):
        response = session.get(url, timeout=30)
        response.raise_for_status()
        return response.content

    snapshots = {
        "sportsnavi": collect_snapshot(fetch, SOURCE, parse_transfers, snapshots.get("sportsnavi", {}), now),
        "nikkan": collect_snapshot(fetch, NIKKAN, lambda html: parse_nikkan(html, TEAMS, category), snapshots.get("nikkan", {}), now),
    }
    salary_path = ROOT / "data" / "movement_salaries.json"
    cache = read_json(salary_path, {"teams": {}})
    # Full names, explicit year and 万円 only. Refresh each team at most daily.
    due = [t for t in TEAMS if not cache["teams"].get(t, {}).get("last_success_at") or
           now_dt - datetime.fromisoformat(cache["teams"][t]["last_success_at"]) >= timedelta(days=1)]
    if due:
        try:
            links = salary_links(json.loads(fetch(SALARY_INDEX)), TEAMS)
            for team in due:
                cache["teams"][team] = collect_snapshot(fetch, links[team],
                    lambda html, t=team: parse_salaries(html, t, links[t]), cache["teams"].get(team, {}), now)
                time.sleep(0.5)
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            print(f"WARNING 年俸ナビ取得失敗: {exc}")
            for team in due:
                cache["teams"][team] = {**cache["teams"].get(team, {}), "stale": True, "checked_at": now, "error": "年俸一覧の取得に失敗"}
        save_json(salary_path, cache)
    profiles = read_json(ROOT / "data" / "masters" / "player_profiles.json", {"players": []})
    # Use the existing dataset's season rather than silently relabeling old stats.
    season = max((int(r["year"]) for p in profiles["players"] for kind in ("batting", "pitching")
                  for r in (p.get("yearly_" + kind) or []) if str(r.get("year", "")).isdigit()), default=now_dt.year)
    rows = merge_and_enrich(snapshots, profiles["players"], cache, season)
    result = {"schema_version": 2, "checked_at": now, "source_url": SOURCE, "teams": list(TEAMS),
              "season": str(season), "snapshots": snapshots,
              "sources": {k: {a: b for a, b in v.items() if a != "rows"} for k, v in snapshots.items()},
              "salary_sources": {k: {a: b for a, b in v.items() if a != "rows"} for k, v in cache["teams"].items()},
              "movements": rows}
    save_json(output, result)
    print(f"選手動向: {len(rows)}件 / {result['checked_at']}")


if __name__ == "__main__":
    main()
