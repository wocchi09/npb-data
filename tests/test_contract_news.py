import unittest
from datetime import date
from scraper.contract_news import article_url, collect, enrich_articles, outlet_type, parse_listing


def listing(title="【阪神】2選手と来季契約を結ばないと発表", stamp="2026/9/28 12:01", url="https://news.yahoo.co.jp/articles/abc123"):
    return f'''<input id="allSearchResultCount" value="1"><li class="cm-timeLine__item">
    <a class="cm-timeLine__itemArticleLink" href="{url}"><p class="cm-timeLine__itemTitle">{title}</p>
    <small class="cm-timeLine__itemCredit">テスト媒体</small><time>{stamp}</time></a></li>'''


class ContractNewsTest(unittest.TestCase):
    def test_dates_source_and_status_are_not_invented(self):
        rows, _ = parse_listing(listing(), date(2026, 9, 28), date(2026, 9, 28))
        self.assertEqual(rows[0]["teams"], ["阪神"])
        self.assertEqual(rows[0]["publisher"], "テスト媒体")
        self.assertEqual(rows[0]["outlet_type"], "その他の配信元")
        self.assertEqual(rows[0]["status"], "news_only")
        self.assertEqual(rows[0]["published_at"], "2026-09-28T12:01+09:00")
        for stamp in ("2025/9/28 12:01", "2026/9/27 12:01", "2026/9/29 12:01"):
            rows, _ = parse_listing(listing(stamp=stamp), date(2026, 9, 28), date(2026, 9, 28))
            self.assertEqual(rows, [])

    def test_unrelated_and_speculation(self):
        self.assertEqual(parse_listing(listing(title="阪神が逆転勝利"), date(2026, 9, 28), date(2026, 9, 28))[0], [])
        rows, _ = parse_listing(listing(title="【中日】来季の戦力外候補を予想"), date(2026, 9, 28), date(2026, 9, 28))
        self.assertEqual(rows[0]["context"], "予想・回顧を含む可能性")
        self.assertNotIn("戦力外", rows[0]["display_title"])

    def test_bad_markup_fails_instead_of_claiming_zero(self):
        with self.assertRaises(ValueError):
            parse_listing("<html>temporary error</html>", date(2026, 9, 28), date(2026, 9, 28))
        self.assertEqual(parse_listing('<input id="allSearchResultCount" value="0">', date(2026, 9, 28), date(2026, 9, 28)), ([], []))
        self.assertIsNone(article_url("https://news.yahoo.co.jp.evil.example/articles/abc"))
        self.assertIsNone(article_url("javascript:alert(1)"))
        self.assertEqual(article_url("https://news.yahoo.co.jp/articles/abc?source=test"), "https://news.yahoo.co.jp/articles/abc")

    def test_non_npb_and_full_name_mentions(self):
        rows, _ = parse_listing(listing(title="BCリーグ 元阪神GMとの契約解除"), date(2026, 9, 28), date(2026, 9, 28))
        self.assertEqual(rows, [])

    def test_featured_outlets_are_labeled_from_the_visible_credit_only(self):
        self.assertEqual(outlet_type("スポニチアネックス"), "主要野球ニュース")
        self.assertEqual(outlet_type("スポーツ報知"), "主要野球ニュース")
        self.assertEqual(outlet_type("未知の配信元"), "その他の配信元")
        rows, _ = parse_listing(listing(title="【楽天】酒居知史に来季契約の通告"), date(2026, 9, 28), date(2026, 9, 28))
        enrich_articles(rows, [{"name": "酒居 知史", "team": "楽天"}, {"name": "酒居 別人", "team": "楽天"}])
        self.assertEqual(rows[0]["mentioned_players"], ["酒居 知史"])
        self.assertEqual(rows[0]["status"], "news_only")

    def test_collection_merges_and_deduplicates_and_preserves_on_error(self):
        class Response:
            text = listing()
            def raise_for_status(self): pass
        class Session:
            def get(self, *args, **kwargs): return Response()
        old, _ = parse_listing(listing(url="https://news.yahoo.co.jp/articles/older"), date(2026, 9, 28), date(2026, 9, 28))
        previous = {"articles": old}
        result = collect(date(2026, 9, 28), date(2026, 9, 28), previous, session=Session(), pause=0)
        self.assertEqual(len(result["articles"]), 2)
        self.assertEqual(len(previous["articles"]), 1)
        self.assertFalse(result["coverage_limited"])
        class Failed:
            def get(self, *args, **kwargs): raise RuntimeError("network failed")
        with self.assertRaises(RuntimeError):
            collect(date(2026, 9, 28), date(2026, 9, 28), previous, session=Failed(), pause=0)
        self.assertEqual(len(previous["articles"]), 1)

    def test_pagination_stops_at_total_from_first_page(self):
        item = listing().split('value="1">', 1)[1]
        class Response:
            def __init__(self, text): self.text = text
            def raise_for_status(self): pass
        class Session:
            urls = []
            def get(self, url, **kwargs):
                self.urls.append(url)
                if "fragment" in url:
                    self.assert_page(url)
                    return Response(item * 20)
                return Response('<input id="allSearchResultCount" value="40">' + item * 20)
            def assert_page(self, url):
                if "page=2&" not in url: raise AssertionError("Requested beyond last page")
        session = Session()
        result = collect(date(2026, 9, 28), date(2026, 9, 28), {}, session=session, pause=0)
        self.assertEqual(len(session.urls), 8)
        self.assertTrue(all(row["pages"] == 2 for row in result["searches"]))
        self.assertFalse(result["coverage_limited"])


if __name__ == "__main__":
    unittest.main()
