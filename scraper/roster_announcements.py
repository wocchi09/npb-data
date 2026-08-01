"""NPB公式の出場選手登録・抹消公示を収集し、登録日数を集計する。

各日の「出場選手一覧」を正として扱うため、イベントの訂正や再登録があっても
推測で状態を補わない。日次スナップショットは data/<season>/roster/daily に、
シーズン集計は data/<season>/roster/registration.json に保存する。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


JST = timezone(timedelta(hours=9))
BASE_URL = "https://npb.jp/announcement/roster/roster_{mmdd}.html"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}

TEAM_NAMES = {
    "阪神タイガース": "阪神",
    "横浜DeNAベイスターズ": "DeNA",
    "横浜ＤｅＮＡベイスターズ": "DeNA",
    "読売ジャイアンツ": "巨人",
    "中日ドラゴンズ": "中日",
    "広島東洋カープ": "広島",
    "東京ヤクルトスワローズ": "ヤクルト",
    "福岡ソフトバンクホークス": "ソフトバンク",
    "北海道日本ハムファイターズ": "日本ハム",
    "オリックス・バファローズ": "オリックス",
    "東北楽天ゴールデンイーグルス": "楽天",
    "埼玉西武ライオンズ": "西武",
    "千葉ロッテマリーンズ": "ロッテ",
}
POSITION_NAMES = {"投手": "投", "捕手": "捕", "内野手": "内", "外野手": "外"}


def clean(value: str | None) -> str:
    return " ".join((value or "").replace("\u3000", " ").split())


def player_from_row(row, default_team: str | None = None) -> dict | None:
    cells = row.find_all(["td", "th"])
    if not cells:
        return None
    by_class = {c.get("class", [""])[0]: clean(c.get_text(" ", strip=True)) for c in cells if c.get("class")}
    link = row.find("a", href=re.compile(r"/bis/players/(\d+)\.html"))
    if not link:
        return None
    match = re.search(r"/bis/players/(\d+)\.html", link.get("href", ""))
    if not match:
        return None
    texts = [clean(c.get_text(" ", strip=True)) for c in cells]
    team_raw = by_class.get("team") or default_team or ""
    pos_raw = by_class.get("pos") or (texts[0] if default_team and texts else "")
    number = by_class.get("num") or (texts[1] if default_team and len(texts) > 1 else "")
    return {
        "npb_id": match.group(1),
        "name": clean(link.get_text(" ", strip=True)),
        "team": TEAM_NAMES.get(clean(team_raw), clean(team_raw)),
        "position": POSITION_NAMES.get(clean(pos_raw), clean(pos_raw)),
        "number": clean(number),
    }


def rows_after_heading(heading) -> list:
    block = heading.find_next_sibling()
    return block.find_all("tr") if block else []


def parse_announcement_page(html: str, expected_date: date | None = None) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title = next(
        (h.get_text(" ", strip=True) for h in soup.find_all("h4") if "日の出場選手登録" in h.get_text()),
        "",
    )
    match = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", title)
    if not match:
        raise ValueError("公示日を確認できません")
    page_date = date(*map(int, match.groups()))
    if expected_date and page_date != expected_date:
        raise ValueError(f"公示日が一致しません: expected={expected_date} actual={page_date}")

    additions, removals = [], []
    for heading in soup.find_all("h5"):
        label = clean(heading.get_text(" ", strip=True))
        if label not in ("出場選手登録", "出場選手登録抹消"):
            continue
        league_heading = heading.find_previous("h4")
        league_text = clean(league_heading.get_text(" ", strip=True)) if league_heading else ""
        league = "セ" if "セントラル" in league_text else "パ" if "パシフィック" in league_text else ""
        target = additions if label == "出場選手登録" else removals
        for row in rows_after_heading(heading):
            player = player_from_row(row)
            if player:
                player["league"] = league
                target.append(player)

    roster_heading = next(
        (h for h in soup.find_all("h4") if clean(h.get_text(" ", strip=True)) == "出場選手一覧"),
        None,
    )
    if roster_heading is None:
        raise ValueError("出場選手一覧がありません")
    registered = []
    roster_block = roster_heading.find_next_sibling()
    while roster_block and "three_column_wrap" in (roster_block.get("class") or []):
        for team_heading in roster_block.find_all("h5"):
            team_raw = clean(team_heading.get_text(" ", strip=True))
            if team_raw not in TEAM_NAMES:
                continue
            for row in rows_after_heading(team_heading):
                player = player_from_row(row, team_raw)
                if player:
                    registered.append(player)
        roster_block = roster_block.find_next_sibling()
    if not registered:
        raise ValueError("登録選手を取得できません")

    registered.sort(key=lambda p: (p["team"], int(p["number"]) if p["number"].isdigit() else 9999, p["name"]))
    return {
        "date": page_date.isoformat(),
        "source": BASE_URL.format(mmdd=page_date.strftime("%m%d")),
        "registered_count": len(registered),
        "registered": registered,
        "additions": additions,
        "removals": removals,
    }


def fetch_page(day: date, session=requests) -> str:
    url = BASE_URL.format(mmdd=day.strftime("%m%d"))
    response = session.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text


def daterange(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def load_daily_files(daily_dir: Path, start: date, end: date) -> tuple[list[dict], list[str]]:
    snapshots, missing = [], []
    for day in daterange(start, end):
        path = daily_dir / f"{day.isoformat()}.json"
        if not path.exists():
            missing.append(day.isoformat())
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("date") == day.isoformat() and payload.get("registered"):
                snapshots.append(payload)
            else:
                missing.append(day.isoformat())
        except (OSError, json.JSONDecodeError):
            missing.append(day.isoformat())
    return snapshots, missing


def aggregate_snapshots(snapshots: list[dict], season: int, start: date, end: date) -> dict:
    snapshots = sorted(snapshots, key=lambda item: item["date"])
    covered_date_values = {date.fromisoformat(item["date"]) for item in snapshots}
    info: dict[str, dict] = {}
    active_dates: dict[str, list[date]] = defaultdict(list)
    removals: dict[str, list[str]] = defaultdict(list)
    dates = []

    for snap in snapshots:
        day = date.fromisoformat(snap["date"])
        dates.append({
            "date": snap["date"],
            "registered_count": snap.get("registered_count", len(snap.get("registered", []))),
            "additions": len(snap.get("additions", [])),
            "removals": len(snap.get("removals", [])),
        })
        for player in snap.get("registered", []):
            pid = player["npb_id"]
            info[pid] = dict(player)
            active_dates[pid].append(day)
        for player in snap.get("removals", []):
            removals[player["npb_id"]].append(snap["date"])
            info.setdefault(player["npb_id"], dict(player))

    latest_ids = {p["npb_id"] for p in snapshots[-1]["registered"]} if snapshots else set()
    players = []
    for pid, days in active_dates.items():
        days = sorted(set(days))
        periods = []
        period_start = period_end = days[0]
        for day in days[1:]:
            covered_absence = any(
                check in covered_date_values
                for check in daterange(period_end + timedelta(days=1), day - timedelta(days=1))
            ) if day > period_end + timedelta(days=1) else False
            if day == period_end + timedelta(days=1) or not covered_absence:
                period_end = day
            else:
                periods.append((period_start, period_end))
                period_start = period_end = day
        periods.append((period_start, period_end))
        current = pid in latest_ids
        record = dict(info[pid])
        record.update({
            "registered_days": len(days),
            "registered_dates": [day.isoformat() for day in days],
            "current_registered": current,
            "first_registered": days[0].isoformat(),
            "last_registered": days[-1].isoformat(),
            "last_deregistered": max(removals.get(pid, []), default=None),
            "registration_count": len(periods),
            "periods": [
                {
                    "from": begin.isoformat(),
                    "to": None if current and finish == days[-1] else finish.isoformat(),
                    "days": sum(begin <= day <= finish for day in days),
                }
                for begin, finish in periods
            ],
        })
        players.append(record)

    players.sort(key=lambda p: (not p["current_registered"], p["team"], -p["registered_days"], p["name"]))
    covered = {item["date"] for item in dates}
    expected = [d.isoformat() for d in daterange(start, end)]
    return {
        "season": season,
        "updated_at": datetime.now(JST).isoformat(),
        "source": "https://npb.jp/announcement/roster/",
        "counting_rule": "各日の出場選手一覧に掲載された日を1日として集計（抹消日は含めない）",
        "start_date": start.isoformat(),
        "latest_date": snapshots[-1]["date"] if snapshots else None,
        "covered_days": len(covered),
        "expected_days": len(expected),
        "missing_dates": [d for d in expected if d not in covered],
        "current_registered_count": len(latest_ids),
        "dates": dates,
        "players": players,
    }


def collect(season: int, start: date, end: date, data_root: Path, sleep_seconds: float = 0.5) -> dict:
    if start.year != season or end.year != season or end < start:
        raise ValueError("収集期間は同一シーズン内で指定してください")
    daily_dir = data_root / str(season) / "roster" / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    for day in daterange(start, end):
        path = daily_dir / f"{day.isoformat()}.json"
        if path.exists():
            continue
        print(f"[INFO] 公示を取得: {day}")
        try:
            payload = parse_announcement_page(fetch_page(day, session), day)
        except Exception as exc:
            print(f"[WARN] {day}: {exc}")
            continue
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if sleep_seconds:
            time.sleep(sleep_seconds)

    snapshots, missing = load_daily_files(daily_dir, start, end)
    result = aggregate_snapshots(snapshots, season, start, end)
    out_path = data_root / str(season) / "roster" / "registration.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"[INFO] 登録日数を集計: {len(result['players'])}人 / "
        f"{result['covered_days']}日（未取得 {len(missing)}日）"
    )
    return result


def main() -> int:
    today = datetime.now(JST).date()
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=today.year)
    parser.add_argument("--start-date", default=None, help="YYYY-MM-DD（省略時は3月26日）")
    parser.add_argument("--to-date", default=None, help="YYYY-MM-DD（省略時は今日）")
    parser.add_argument("--data-root", default="data")
    parser.add_argument("--sleep", type=float, default=0.5)
    args = parser.parse_args()
    start = date.fromisoformat(args.start_date or f"{args.season}-03-26")
    end = date.fromisoformat(args.to_date) if args.to_date else min(today, date(args.season, 12, 31))
    if not args.to_date and end < start:
        print(f"[INFO] {args.season}年の公示収集開始前です")
        return 0
    try:
        collect(args.season, start, end, Path(args.data_root), args.sleep)
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
