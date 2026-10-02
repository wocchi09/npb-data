"""Supplementary public movement sources and conservative player enrichment.

Only the text AFTER Nikkan's player biography is a current movement. Dates on
that article are article-wide timestamps, never individual announcement dates.
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup

try:
    from .player_profiles import normalized_name
except ImportError:
    from player_profiles import normalized_name

NIKKAN = "https://www.nikkansports.com/baseball/news/202609280000276.html?mode=all"
SALARY_INDEX = "https://www.daily.co.jp/baseball/koukai/link_sys/table_link.json"
SALARY_BASE = "https://www.daily.co.jp/baseball/koukai/"


def name_key(name):
    # Explicit old/new character variant, not surname or fuzzy matching.
    return normalized_name(name).replace("當", "当")


# Reviewed full-name/registration-name pairs, scoped to team. No generic suffix
# matching: e.g. a different Martinez must never be joined by surname alone.
# Full names: https://hanshintigers.jp/news/topics/info_10212.html
# https://www3.hanshintigers.jp/news/topics/info_9856.html
# Registration names: Sportsnavi player IDs 2113277 / 2118424 / 2114830.
NAME_ALIASES = {("阪神", name_key(full)): name_key(short) for full, short in (
    ("アンソニー・マルティネス", "マルティネス"),
    ("スタンリー・コンスエグラ", "コンスエグラ"),
    ("ジーン・アルナエス", "アルナエス"),
)}


def player_key(team, name):
    return team, NAME_ALIASES.get((team, name_key(name)), name_key(name))


def neutral(text):
    return text.replace("戦力外通告", "来季契約なしの通知").replace("戦力外", "来季契約なし")


def parse_nikkan(html, teams, classify):
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one("#news.article-body")
    stamp = next((re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日(\d{1,2})時(\d{1,2})分", t.get_text())
                  for t in soup.select("time") if re.search(r"\d{4}年", t.get_text())), None)
    if body is None or not stamp:
        raise ValueError("日刊スポーツの記事本文・更新日時を確認できません")
    updated = datetime(*map(int, stamp.groups())).isoformat(timespec="minutes") + "+09:00"
    found, rows = set(), []
    for heading in body.select("h2"):
        team = heading.get_text(strip=True)
        if team not in teams:
            continue
        if team in found:
            raise ValueError("日刊スポーツの球団見出しが重複しています")
        found.add(team)
        block = heading.find_next_sibling()
        if block is None or block.name != "div" or "yellow" not in block.get("class", []):
            raise ValueError("日刊スポーツの選手欄形式が変わっています")
        for p in block.select("p"):
            span = p.select_one("span.black.bold")
            if span is None or not span.get_text(strip=True):
                continue
            bio = span.get_text(" ", strip=True)
            identity = re.match(r"(※?)(.+?)(投手|捕手|内野手|外野手|選手)（", bio)
            if not identity:
                # Coaches and staff are deliberately not treated as players.
                if re.search(r"投手|捕手|内野手|外野手|選手", bio):
                    raise ValueError("日刊スポーツの選手名を分離できません")
                continue
            tail = "".join(s.get_text(" ", strip=True) if hasattr(s, "get_text") else str(s)
                           for s in span.next_siblings).strip()
            if not tail.startswith("→"):
                raise ValueError("日刊スポーツの現在の動きを分離できません")
            note = tail.lstrip("→").strip()
            stages = [x.strip() for x in note.split("→") if x.strip()]
            cats = list(dict.fromkeys(classify(stage, "") for stage in stages))
            cats = [c for c in cats if c != "その他"] or ["その他"]
            # Keep a reported intention distinct from a confirmed retirement.
            intent = "引退" in note and any(w in note for w in ("決意", "意向", "検討"))
            if intent:
                cats = ["引退（意向）" if c == "引退" else c for c in cats]
            rows.append({
                "name": identity[2].strip(), "team": team, "player_id": None,
                "position": identity[3], "development_player": bool(identity[1]),
                "updated_date": updated[:10], "source_updated_at": updated,
                "date_kind": "記事全体の更新日", "status": neutral(stages[0]),
                "category": cats[0], "categories": cats, "note": neutral(note),
                "destination": None, "source": "日刊スポーツ", "source_url": NIKKAN,
                "confirmation": "報道（NPB公示とは別）", "profile_url": None,
            })
    if found != set(teams):
        raise ValueError("日刊スポーツの12球団欄を確認できません")
    return rows


def salary_links(entries, teams):
    links = {}
    for entry in entries:
        team = entry.get("headline", "").replace("ＤｅＮＡ", "DeNA")
        path = entry.get("url", "")
        if team in teams and re.fullmatch(r"tb\d+\.shtml", path):
            links[team] = urljoin(SALARY_BASE, path)
    if set(links) != set(teams):
        raise ValueError("年俸一覧の12球団リンクを確認できません")
    return links


def parse_salaries(html, team, url):
    soup = BeautifulSoup(html, "html.parser")
    section = soup.select_one("section.scoreContent")
    text = section.get_text(" ", strip=True) if section else ""
    year = re.search(r"(\d{4})年度契約更改[・･]([^\s]+)", text)
    if not year or year[2].replace("ＤｅＮＡ", "DeNA") != team or not re.search(r"推定.*単位は万円", text):
        raise ValueError("年俸の年度・球団・推定表記・単位を確認できません")
    tables = [table for table in section.select("table") if
              [re.sub(r"\s", "", x.get_text()) for x in table.select("th")][:4] == ["選手", "年俸", "増減", "増減額"]]
    if len(tables) != 1:
        raise ValueError("年俸表の列定義が変更されています")
    table = tables[0]
    rows = []
    for tr in table.select("tr"):
        cells = tr.find_all("td")
        if not cells:
            continue
        if len(cells) != 4:
            raise ValueError("年俸表の列数が変更されています")
        name, value = [x.get_text(" ", strip=True) for x in cells[:2]]
        if not name or "【" in name or "〖" in name:
            continue
        value = value.replace(",", "")
        if not re.fullmatch(r"\d+(?:\.\d+)?", value):
            continue  # Unknown or differently denominated amounts are NOT zero.
        rows.append({"name": name, "team": team, "season": year[1],
                     "amount_man_yen": float(value), "estimated": True,
                     "source": "デイリースポーツ 契約更改", "source_url": url})
    if not rows:
        raise ValueError("年俸表に確認できる金額がありません")
    return rows


STAT_FIELDS = {
    "pitching": ("games", "wins", "losses", "saves", "holds", "innings", "strikeouts", "era"),
    "batting": ("games", "plate_appearances", "at_bats", "hits", "home_runs", "runs_batted_in",
                "stolen_bases", "batting_average", "on_base_percentage", "slugging_percentage"),
}


def profile_stats(profile, season):
    result = {"season": str(season), "as_of": profile.get("fetched_at"),
              "stale": bool(profile.get("stale")), "source_url": profile.get("source_url"),
              "source": "NPB公式・既存選手プロフィール集計（一軍）", "yearly": [], "career": []}
    for kind, fields in STAT_FIELDS.items():
        def compact(row):
            return {"kind": kind, **{k: row[k] for k in fields if row.get(k) is not None}}
        for row in profile.get("yearly_" + kind) or []:
            if str(row.get("year")) == str(season):
                result["yearly"].append({"team": row.get("team"), **compact(row)})
        career = profile.get("career_" + kind)
        if career:
            result["career"].append(compact(career))
    return result


def merge_and_enrich(snapshots, profiles, salary_cache, season):
    by_name, by_id = {}, {}
    observed_ids = {}
    for snapshot in snapshots.values():
        for r in snapshot.get("rows", []):
            if r.get("player_id"):
                observed_ids.setdefault(player_key(r["team"], r["name"]), set()).add(str(r["player_id"]))
    for p in profiles:
        by_name.setdefault(player_key(p.get("team"), p.get("name")), []).append(p)
        if p.get("yahoo_player_id"):
            by_id.setdefault(str(p["yahoo_player_id"]), []).append(p)
    grouped = {}
    for snapshot in snapshots.values():
        for raw in snapshot.get("rows", []):
            row = dict(raw)
            name_identity = player_key(row["team"], row["name"])
            candidates = by_id.get(str(row.get("player_id")), []) if row.get("player_id") else []
            if not candidates:
                candidates = [p for p in by_name.get(name_identity, []) if not row.get("player_id") or not p.get("yahoo_player_id") or str(p["yahoo_player_id"]) == str(row["player_id"])]
            profile = candidates[0] if len(candidates) == 1 else None
            player_id = row.get("player_id") or (profile.get("yahoo_player_id") if profile else None)
            if not player_id and len(observed_ids.get(name_identity, set())) == 1:
                player_id = next(iter(observed_ids[name_identity]))
            key = (row["team"], "id:" + str(player_id) if player_id else "name:" + name_identity[1])
            row["stale"] = snapshot.get("stale", False)
            row["last_success_at"] = snapshot.get("last_success_at")
            row.setdefault("date_kind", "掲載元の選手更新日")
            row.setdefault("categories", [row["category"]])
            if key not in grouped:
                grouped[key] = {**row, "id": "|".join(key), "player_id": player_id,
                                "observations": [], "categories": [], "stats": profile_stats(profile, season) if profile else None}
            item = grouped[key]
            item["observations"].append(row)
            item["categories"] = list(dict.fromkeys(item["categories"] + row["categories"]))
            # Keep the two sources' notes separate, not a fabricated timeline.
            item["note"] = " / ".join(dict.fromkeys(x["note"] for x in item["observations"] if x.get("note")))
    for row in grouped.values():
        cached = salary_cache.get("teams", {}).get(row["team"], {})
        matches = [s for s in cached.get("rows", []) if player_key(s["team"], s["name"]) == player_key(row["team"], row["name"])]
        row["salary"] = {**matches[0], "as_of": cached.get("last_success_at"), "stale": cached.get("stale", False)} if len(matches) == 1 else None
    return sorted(grouped.values(), key=lambda r: (r["updated_date"], r["team"], r["name"]), reverse=True)
