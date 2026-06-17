"""Unit tests for the feed parsers and helpers in server.py.

Run with:  python -m unittest discover -s tests
(uses only the stdlib — no extra dependencies)."""

import unittest

from server import (
    SOURCES,
    parse_rss,
    parse_atom,
    parse_google_rss,
    parse_reuters_sitemap,
    zhihu_item_url,
    normalize_date,
    upscale_image_url,
    extract_snippet,
    is_safe_url,
    dedupe_items,
    make_item,
    RateLimiter,
)


class ParseRSSTests(unittest.TestCase):
    def test_basic_rss_item(self):
        meta = SOURCES["economist"]
        raw = b"""<?xml version="1.0"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>The Economist</title>
    <lastBuildDate>Mon, 16 Jun 2025 10:00:00 GMT</lastBuildDate>
    <item>
      <title>World news headline</title>
      <link>https://www.economist.com/a-world-article</link>
      <description>Article description text</description>
      <pubDate>Mon, 16 Jun 2025 09:00:00 GMT</pubDate>
      <guid>guid-1</guid>
      <media:content url="https://example.com/img.png?width=400" />
    </item>
  </channel>
</rss>"""
        items, latest = parse_rss("economist", meta, raw)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["title"], "World news headline")
        self.assertEqual(item["url"], "https://www.economist.com/a-world-article")
        self.assertEqual(item["summary"], "Article description text")
        self.assertIn("img.png", item["image"])
        self.assertTrue(latest)

    def test_skips_items_without_title_or_link(self):
        meta = SOURCES["economist"]
        raw = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>No link</title></item>
  <item><link>https://x.com</link></item>
  <item><title>OK</title><link>https://y.com</link></item>
</channel></rss>"""
        items, _ = parse_rss("economist", meta, raw)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "OK")


class ParseAtomTests(unittest.TestCase):
    def test_basic_atom_entry(self):
        meta = SOURCES["verge"]
        raw = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:media="http://search.yahoo.com/mrss/">
  <updated>2025-06-16T10:00:00Z</updated>
  <entry>
    <title>Atom headline</title>
    <link href="https://www.theverge.com/atom-article" rel="alternate"/>
    <id>tag:theverge,2025:1</id>
    <published>2025-06-16T09:00:00Z</published>
    <summary>Atom summary</summary>
  </entry>
</feed>"""
        items, latest = parse_atom("verge", meta, raw)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Atom headline")
        self.assertEqual(items[0]["url"], "https://www.theverge.com/atom-article")
        self.assertEqual(items[0]["summary"], "Atom summary")
        self.assertTrue(latest)


class ParseGoogleRSSTests(unittest.TestCase):
    def test_strips_publisher_suffix_and_filters_print_edition(self):
        meta = SOURCES["google"]
        raw = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Some headline - Reuters</title>
    <link>https://news.google.com/r/articles/1</link>
    <source>Reuters</source>
    <pubDate>Mon, 16 Jun 2025 09:00:00 GMT</pubDate>
    <guid>g1</guid>
  </item>
  <item>
    <title>Print Edition - WSJ</title>
    <link>https://news.google.com/r/articles/2</link>
    <source>WSJ</source>
    <guid>g2</guid>
  </item>
</channel></rss>"""
        items, _ = parse_google_rss("google", meta, raw)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Some headline")
        self.assertEqual(items[0]["summary"], "Reuters")


class ParseReutersSitemapTests(unittest.TestCase):
    def test_parses_and_skips_localized(self):
        meta = SOURCES["reuters"]
        raw = b"""<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"
        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
  <url>
    <loc>https://www.reuters.com/world/an-article/</loc>
    <news:news>
      <news:title>An article</news:title>
      <news:publication_date>2025-06-16T09:00:00Z</news:publication_date>
    </news:news>
  </url>
  <url>
    <loc>https://www.reuters.com/es/a-spanish-article/</loc>
    <news:news>
      <news:title>Spanish article</news:title>
      <news:publication_date>2025-06-16T09:00:00Z</news:publication_date>
    </news:news>
  </url>
</urlset>"""
        items, latest = parse_reuters_sitemap("reuters", meta, raw)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "An article")
        self.assertTrue(latest)


class ZhihuHelperTests(unittest.TestCase):
    def test_zhihu_item_url_extracts_question_id(self):
        self.assertEqual(
            zhihu_item_url("https://api.zhihu.com/questions/123456/answers"),
            "https://www.zhihu.com/question/123456",
        )
        self.assertEqual(zhihu_item_url("not a url"), "not a url")


class UtilityTests(unittest.TestCase):
    def test_normalize_date_iso_and_rfc822(self):
        self.assertEqual(normalize_date("2025-06-16T09:00:00Z"), "2025-06-16T09:00:00Z")
        self.assertTrue(normalize_date("Mon, 16 Jun 2025 09:00:00 GMT").startswith("2025-06-16T09:00:00"))

    def test_upscale_image_url_bbc_and_google(self):
        bbc = upscale_image_url("https://ichef.bbci.co.uk/news/240/x.jpg")
        self.assertIn("/news/976/", bbc)
        google = upscale_image_url("https://lh3.googleusercontent.com/w200/p.jpg")
        self.assertIn("w800", google)

    def test_extract_snippet_from_meta_description(self):
        html = '<html><head><meta name="description" content="A short description"></head></html>'
        self.assertEqual(extract_snippet(html), "A short description")

    def test_dedupe_items_by_url(self):
        meta = SOURCES["economist"]
        a = make_item("economist", meta, title="A", url="https://x.com/a")
        b = make_item("economist", meta, title="B", url="https://x.com/a")
        c = make_item("economist", meta, title="C", url="https://x.com/c")
        self.assertEqual(len(dedupe_items([a, b, c])), 2)


class SafeUrlTests(unittest.TestCase):
    def test_rejects_non_http_schemes(self):
        self.assertFalse(is_safe_url("file:///etc/passwd"))
        self.assertFalse(is_safe_url("javascript:alert(1)"))

    def test_rejects_loopback(self):
        self.assertFalse(is_safe_url("http://127.0.0.1/admin"))
        self.assertFalse(is_safe_url("http://localhost/admin"))

    def test_rejects_link_local_metadata_endpoint(self):
        self.assertFalse(is_safe_url("http://169.254.169.254/latest/meta-data/"))

    def test_rejects_private_ranges(self):
        self.assertFalse(is_safe_url("http://10.0.0.1/"))
        self.assertFalse(is_safe_url("http://192.168.1.1/"))

    def test_allows_public_ip_literal(self):
        # 93.184.216.34 is a public address; using a literal avoids any DNS
        # lookup so the test stays offline and deterministic.
        self.assertTrue(is_safe_url("http://93.184.216.34/"))


class RateLimiterTests(unittest.TestCase):
    def test_allows_until_limit_then_blocks(self):
        lim = RateLimiter(max_calls=3, period=60)
        self.assertTrue(lim.allow("ip1", now=100.0))
        self.assertTrue(lim.allow("ip1", now=101.0))
        self.assertTrue(lim.allow("ip1", now=102.0))
        self.assertFalse(lim.allow("ip1", now=103.0))  # 4th blocked
        self.assertTrue(lim.allow("ip2", now=103.0))   # different key unaffected

    def test_window_slides(self):
        lim = RateLimiter(max_calls=2, period=10)
        self.assertTrue(lim.allow("ip1", now=100.0))
        self.assertTrue(lim.allow("ip1", now=105.0))
        self.assertFalse(lim.allow("ip1", now=109.0))  # still inside window
        self.assertTrue(lim.allow("ip1", now=111.0))   # window slid past t=100


if __name__ == "__main__":
    unittest.main()
