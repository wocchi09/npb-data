"""Collect public Sportsnavi headline metadata, not full articles or player statuses."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
JST = timezone(timedelta(hours=9))
LIST_URL = "https://sports.yahoo.co.jp/list/news/npb"
KEYWORDS = ("戦力外", "自由契約", "来季契約", "契約を結ば")
TEAMS = {
    "ソフトバンク": ("ソフトバンク", "ホークス"),
    "日本ハム": ("日本ハム", "日ハム", "ファイターズ"),
    "オリックス": ("オリックス", "バファローズ"),
    "楽天": ("楽天", "イーグルス"), "西武": ("西武", "ライオンズ"),
    "ロッテ": ("ロッテ", "マリーンズ"), "巨人": ("巨人", "ジャイアンツ"),
    "阪神": ("阪神", "タイガース"), "DeNA": ("DeNA", "ＤｅＮＡ", "ベイスターズ"),
    "広島": ("広島", "カープ"), "ヤクルト": ("ヤクルト", "スワローズ"),
    "中日": ("中日", "ドラゴンズ"),
}
RELEVANT = re.compile(r"戦力外|自由契約|来季.{0,8}契約|契約.{0,6}(結ば|更新しない|満了|解除|終了)")
SPECULATIVE = re.compile(r"予想|候補|可能性|去就|か[？?]|どうなる|振り返|あの時|昨年|当時")
OUT_OF_SCOPE = re.compile(r"(?:BC|ＢＣ|独立|四国|九州アジア)リーグ|メジャー|MLB|ＭＬＢ")
COMMENTARY = re.compile(r"ヤフコメ|期待外れ|終わった|振り返|あの時|当時|候補を予想")
# These are publisher credits as shown by Sportsnavi / Yahoo! Sports.  We use
# them only for filtering the already-public listing; articles are never
# scraped from the individual publisher sites.
FEATURED_OUTLETS = ("日刊スポーツ", "スポーツ報知", "スポニチアネックス", "サンケイスポーツ", "中日スポーツ", "デイリースポーツ")


def normalize_name(value):
    return re.sub(r"[\s・･]", "", unicodedata.normalize("NFKC", value))


def enrich_articles(rows, players):
    for row in rows:
        headline = normalize_name(row["title"])
        # Exact full-name matches only; not inferred from surnames or former teams.
        row["mentioned_players"] = sorted({p["name"] for p in players
            if len(normalize_name(p.get("name", ""))) >= 3
            and normalize_name(p["name"]) in headline
            and (not row["teams"] or p.get("team") in row["teams"])})
        row["player_name_source"] = "data/masters/npb_roster.json"
        row["is_commentary"] = bool(COMMENTARY.search(row["title"]))
    return rows


def article_url(value):
    parsed = urlsplit(value)
    if parsed.scheme != "https" or parsed.hostname not in {"news.yahoo.co.jp", "sports.yahoo.co.jp"}:
        return None
    if not re.match(r"^/(articles|column/detail)/[A-Za-z0-9_-]+/?$", parsed.path):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def outlet_type(publisher):
    """Return a conservative label based solely on Sportsnavi's credit."""
    normalized = unicodedata.normalize("NFKC", publisher or "")
    return "主要野球ニュース" if any(outlet in normalized for outlet in FEATURED_OUTLETS) else "その他の配信元"


def parse_listing(html, since, until):
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("li.cm-timeLine__item")
    if not items:
        # Explicit zero is valid; an error page / changed markup must not look like zero news.
        count = soup.select_one("#allSearchResultCount")
        if count and count.get("value") == "0":
            return [], []
        raise ValueError("ニュース一覧の形式を確認できません（既存データは保持します）")
    rows, dates = [], []
    for item in items:
        title_el = item.select_one(".cm-timeLine__itemTitle")
        link = item.select_one("a.cm-timeLine__itemArticleLink")
        stamp = item.select_one("time")
        if not title_el or not link or not stamp:
            raise ValueError("ニュースの見出し・リンク・日時が不足しています")
        title = title_el.get_text(" ", strip=True)
        match = re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})", stamp.get_text(" ", strip=True))
        if not match:
            raise ValueError("ニュースの配信日時を解析できません")
        published = datetime(*map(int, match.groups()), tzinfo=JST)
        dates.append(published.date())
        url = article_url(link.get("href", ""))
        if not url or not since <= published.date() <= until or not RELEVANT.search(title) or OUT_OF_SCOPE.search(title):
            continue
        credit = item.select_one(".cm-timeLine__itemCredit")
        teams = [team for team, aliases in TEAMS.items() if any(alias in title for alias in aliases)]
        # Display heading is our neutral description. Original wording is retained separately.
        topic = "自由契約に関する記事" if "自由契約" in title else "来季契約・契約終了に関する記事"
        publisher = credit.get_text(" ", strip=True) if credit else "配信元未確認"
        rows.append({
            "id": hashlib.sha256(url.encode()).hexdigest()[:20],
            "title": title, "display_title": topic, "teams": teams,
            "published_at": published.isoformat(timespec="minutes"),
            "publisher": publisher, "outlet_type": outlet_type(publisher),
            "url": url, "source": "スポーツナビ ニュース一覧",
            "context": "予想・回顧を含む可能性" if SPECULATIVE.search(title) else "関連報道・本文確認が必要",
            "status": "news_only",
        })
    return rows, dates


def collect(since, until, previous, pages=5, session=None, pause=1.0):
    session = session or requests.Session()
    records = {r["id"]: r for r in previous.get("articles", [])
               if since.isoformat() <= r["published_at"][:10] <= until.isoformat()
               and not OUT_OF_SCOPE.search(r["title"])}
    searches = []
    for keyword in KEYWORDS:
        covered = False
        fetched = 0
        total = None
        scanned = 0
        for page in range(1, pages + 1):
            base = LIST_URL if page == 1 else "https://sports.yahoo.co.jp/list/fragment/more/news/npb/PC"
            params = {"genre": "npb", "keyword": keyword} if page == 1 else {"page": page, "keyword": keyword}
            url = base + "?" + urlencode(params)
            response = session.get(url, timeout=30)
            response.raise_for_status()
            response.encoding = "utf-8"
            rows, dates = parse_listing(response.text, since, until)
            for row in rows:
                records[row["id"]] = row
            fetched += 1
            scanned += len(dates)
            count = BeautifulSoup(response.text, "html.parser").select_one("#allSearchResultCount")
            if count and str(count.get("value", "")).isdigit():
                total = int(count.get("value"))
            covered = not dates or min(dates) < since or (total is not None and total <= scanned) or len(dates) < 20
            time.sleep(pause)
            if covered:
                break
        searches.append({"keyword": keyword, "pages": fetched, "reached_start_or_end": covered})
    return {
        "schema_version": 1, "season": since.year,
        "since": since.isoformat(), "through": until.isoformat(),
        "checked_at": datetime.now(JST).isoformat(timespec="seconds"),
        "source_url": LIST_URL + "?genre=npb", "teams": list(TEAMS),
        "searches": searches, "coverage_limited": any(not x["reached_start_or_end"] for x in searches),
        "articles": sorted(records.values(), key=lambda r: (r["published_at"], r["id"]), reverse=True),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", type=date.fromisoformat, default=date(2026, 9, 28))
    parser.add_argument("--until", type=date.fromisoformat, default=datetime.now(JST).date())
    parser.add_argument("--pages", type=int, default=5)
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "contract_news.json")
    args = parser.parse_args()
    if not 1 <= args.pages <= 10:
        parser.error("--pages は1〜10")
    previous = json.loads(args.output.read_text(encoding="utf-8")) if args.output.exists() else {}
    result = collect(args.since, args.until, previous, args.pages)
    roster = ROOT / "data" / "masters" / "npb_roster.json"
    players = json.loads(roster.read_text(encoding="utf-8")).get("players", []) if roster.exists() else []
    enrich_articles(result["articles"], players)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Only replace after every search succeeded. Failures leave the last good file intact.
    temp = args.output.with_suffix(".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(args.output)
    print(f"契約関連ニュース: {len(result['articles'])}件 / {result['checked_at']}")


if __name__ == "__main__":
    main()
