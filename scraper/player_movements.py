"""Collect structured Sportsnavi transfer rows, without inferring official NPB status."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://baseball.yahoo.co.jp/npb/transfer"
TEAMS = ("阪神", "DeNA", "巨人", "中日", "広島", "ヤクルト", "ソフトバンク", "日本ハム", "オリックス", "楽天", "西武", "ロッテ")
JST = timezone(timedelta(hours=9))


def category(status, note):
    text = status + " " + note
    if "引退" in text:
        return "引退"
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


def main():
    response = requests.get(SOURCE, timeout=30)
    response.raise_for_status()
    rows = parse_transfers(response.content)
    output = ROOT / "data" / "player_movements.json"
    result = {"schema_version": 1, "checked_at": datetime.now(JST).isoformat(timespec="seconds"),
              "source_url": SOURCE, "teams": list(TEAMS), "movements": rows}
    temp = output.with_suffix(".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(output)
    print(f"選手動向: {len(rows)}件 / {result['checked_at']}")


if __name__ == "__main__":
    main()
