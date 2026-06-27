"""Unit tests for the feed parsers and helpers in server.py.

Run with:  python -m unittest discover -s tests
(uses only the stdlib — no extra dependencies)."""

import json
import os
import unittest

from server import (
    SOURCES,
    parse_rss,
    parse_atom,
    parse_google_rss,
    parse_reuters_sitemap,
    parse_discourse,
    zhihu_item_url,
    zhihu_score,
    normalize_date,
    upscale_image_url,
    extract_snippet,
    is_safe_url,
    dedupe_items,
    make_item,
    RateLimiter,
    TTLLRU,
    client_ip_from_headers,
    debug_enabled,
    should_translate_source,
    should_translate_summary,
    translate_items,
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


class ParseDiscourseTests(unittest.TestCase):
    def test_parses_discourse_rss_with_image_and_strips_noise(self):
        meta = SOURCES["linux_do"]
        raw = b"""<?xml version="1.0"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:discourse="http://www.discourse.org/">
  <channel>
    <title>LINUX DO</title>
    <lastBuildDate>Mon, 22 Jun 2026 00:23:16 +0000</lastBuildDate>
    <item>
      <title>Pinned announcement</title>
      <link>https://linux.do/t/topic/100</link>
      <discourse:topicPinned>Yes</discourse:topicPinned>
      <pubDate>Mon, 22 Jun 2026 00:00:00 +0000</pubDate>
      <guid>linux.do-topic-100</guid>
    </item>
    <item>
      <title>Test topic</title>
      <link>https://linux.do/t/topic/2445150</link>
      <dc:creator><![CDATA[someone]]></dc:creator>
      <discourse:topicPinned>No</discourse:topicPinned>
      <description><![CDATA[<p>Hello world</p><div class="lightbox-wrapper"><a class="lightbox" href="https://cdn3.ldstatic.com/original/4X/a.jpeg"><img src="https://cdn3.ldstatic.com/optimized/4X/a_2_689x435.jpeg" alt="image"></a></div><p><small>1 \xe4\xb8\xaa\xe5\xb8\x96\xe5\xad\x90 - 1 \xe4\xbd\x8d\xe5\x8f\x82\xe4\xb8\x8e\xe8\x80\x85</small></p><p><a href="https://linux.do/t/topic/2445150">\xe9\x98\x85\xe8\xaf\xbb\xe5\xae\x8c\xe6\x95\xb4\xe8\xaf\x9d\xe9\xa2\x98</a></p>]]></description>
      <pubDate>Mon, 22 Jun 2026 00:23:16 +0000</pubDate>
      <guid>linux.do-topic-2445150</guid>
    </item>
    <item>
      <title>No description</title>
      <link>https://linux.do/t/topic/999</link>
      <pubDate>Mon, 22 Jun 2026 00:00:00 +0000</pubDate>
      <guid>linux.do-topic-999</guid>
    </item>
    <item>
      <title>English noise</title>
      <link>https://linux.do/t/topic/888</link>
      <description><![CDATA[<p>Some content</p><p><small>3 posts - 3 participants</small></p><p><a href="https://linux.do/t/topic/888">Read full topic</a></p>]]></description>
      <pubDate>Mon, 22 Jun 2026 00:00:00 +0000</pubDate>
      <guid>linux.do-topic-888</guid>
    </item>
  </channel>
</rss>"""
        items, latest = parse_discourse("linux_do", meta, raw)
        self.assertEqual(len(items), 3)
        self.assertTrue(latest)

        first = items[0]
        self.assertEqual(first["title"], "Test topic")
        self.assertEqual(first["url"], "https://linux.do/t/topic/2445150")
        self.assertIn("optimized/4X/a_2_689x435.jpeg", first["image"])
        self.assertIn("Hello world", first["summary"])
        self.assertNotIn("\u9605\u8bfb\u5b8c\u6574\u8bdd\u9898", first["summary"])
        self.assertNotIn("\u4e2a\u5e16\u5b50", first["summary"])

        second = items[1]
        self.assertEqual(second["title"], "No description")
        self.assertEqual(second["image"], "")

        third = items[2]
        self.assertEqual(third["title"], "English noise")
        self.assertIn("Some content", third["summary"])
        self.assertNotIn("Read full topic", third["summary"])
        self.assertNotIn("participants", third["summary"])

        titles = [it["title"] for it in items]
        self.assertNotIn("Pinned announcement", titles)


class ZhihuHelperTests(unittest.TestCase):
    def test_zhihu_item_url_extracts_question_id(self):
        self.assertEqual(
            zhihu_item_url("https://api.zhihu.com/questions/123456/answers"),
            "https://www.zhihu.com/question/123456",
        )
        self.assertEqual(zhihu_item_url("not a url"), "not a url")


class ZhihuScoreTests(unittest.TestCase):
    def test_wan_multiplier(self):
        self.assertEqual(zhihu_score("5234 万热度"), 52340000)

    def test_wan_without_space(self):
        self.assertEqual(zhihu_score("5234万热度"), 52340000)

    def test_plain_number(self):
        self.assertEqual(zhihu_score("12345 热度"), 12345)

    def test_comma_thousands(self):
        self.assertEqual(zhihu_score("1,234 万热度"), 12340000)

    def test_none_for_missing(self):
        self.assertIsNone(zhihu_score(""))
        self.assertIsNone(zhihu_score(None))
        self.assertIsNone(zhihu_score("无热度"))

    def test_zero_returns_none(self):
        self.assertIsNone(zhihu_score("0 热度"))


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

    def test_prunes_stale_keys(self):
        lim = RateLimiter(max_calls=5, period=10)
        for i in range(1000):
            lim.allow(f"ip{i}", now=0.0)
        # After a sweep (triggered once per period), all stale keys at t=0
        # must be gone once we advance past the period.
        lim.allow("fresh", now=100.0)
        # Re-allowing an old key must behave as a fresh start, not a block.
        self.assertTrue(lim.allow("ip0", now=100.0))


class TTLLRUTests(unittest.TestCase):
    def test_miss_returns_none(self):
        c = TTLLRU(ttl=10, maxsize=4)
        self.assertIsNone(c.get("x", now=0))

    def test_set_then_get(self):
        c = TTLLRU(ttl=10, maxsize=4)
        c.set("a", "v", now=0)
        self.assertEqual(c.get("a", now=1), "v")

    def test_expires_after_ttl(self):
        c = TTLLRU(ttl=10, maxsize=4)
        c.set("a", "v", now=0)
        self.assertIsNone(c.get("a", now=11))

    def test_lru_eviction_evicts_oldest_unused(self):
        c = TTLLRU(ttl=100, maxsize=2)
        c.set("a", 1, now=0)
        c.set("b", 2, now=0)
        c.get("a", now=1)  # touch a -> b becomes oldest
        c.set("c", 3, now=2)  # over capacity -> evict b
        self.assertEqual(c.get("a", now=3), 1)
        self.assertIsNone(c.get("b", now=3))
        self.assertEqual(c.get("c", now=3), 3)

    def test_stores_empty_string(self):
        c = TTLLRU(ttl=10, maxsize=4)
        c.set("a", "", now=0)
        self.assertEqual(c.get("a", now=1), "")


class ClientIpTests(unittest.TestCase):
    def test_xff_rightmost_hop(self):
        # Spoofed left hop + proxy-appended real IP -> take the rightmost.
        h = {"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}
        self.assertEqual(client_ip_from_headers(h, "peer"), "5.6.7.8")

    def test_xff_single_hop(self):
        h = {"X-Forwarded-For": "1.2.3.4"}
        self.assertEqual(client_ip_from_headers(h, "peer"), "1.2.3.4")

    def test_prefers_vercel_header(self):
        h = {"x-vercel-forwarded-for": "9.9.9.9", "X-Forwarded-For": "1.2.3.4"}
        self.assertEqual(client_ip_from_headers(h, "peer"), "9.9.9.9")

    def test_prefers_real_ip_over_xff(self):
        h = {"x-real-ip": "8.8.8.8", "X-Forwarded-For": "1.2.3.4"}
        self.assertEqual(client_ip_from_headers(h, "peer"), "8.8.8.8")

    def test_fallback_when_no_headers(self):
        self.assertEqual(client_ip_from_headers({}, "peer"), "peer")

    def test_fallback_when_none(self):
        self.assertEqual(client_ip_from_headers(None, "peer"), "peer")


class DebugEnabledTests(unittest.TestCase):
    def setUp(self):
        self._saved_env = dict(os.environ)
        os.environ.pop("ENABLE_DEBUG", None)
        os.environ.pop("VERCEL_ENV", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._saved_env)

    def test_default_enabled(self):
        self.assertTrue(debug_enabled())

    def test_disabled_in_production(self):
        os.environ["VERCEL_ENV"] = "production"
        self.assertFalse(debug_enabled())

    def test_enable_debug_zero_does_not_enable_in_production(self):
        os.environ["VERCEL_ENV"] = "production"
        os.environ["ENABLE_DEBUG"] = "0"
        self.assertFalse(debug_enabled())

    def test_enable_debug_one_enables_in_production(self):
        os.environ["VERCEL_ENV"] = "production"
        os.environ["ENABLE_DEBUG"] = "1"
        self.assertTrue(debug_enabled())


class TranslationSourceTests(unittest.TestCase):
    def setUp(self):
        import server
        self._old_available = server.ai_translation_available
        server.ai_translation_available = lambda: True

    def tearDown(self):
        import server
        server.ai_translation_available = self._old_available

    def test_chinese_sources_not_translatable(self):
        for key in ("zhihu", "google_zh", "linux_do", "linux_do_top"):
            self.assertFalse(should_translate_source(key), f"{key} should not translate")

    def test_english_sources_translatable(self):
        for key in ("hn", "economist", "reuters", "bloomberg", "guardian", "bbc"):
            self.assertTrue(should_translate_source(key), f"{key} should translate")

    def test_summary_translatable_only_for_prose_sources(self):
        # Sources with meaningful prose summaries
        for key in ("economist", "bloomberg", "guardian", "bbc", "verge"):
            self.assertTrue(should_translate_summary(key), f"{key} summary should translate")
        # Sources with no/useless summaries
        for key in ("hn", "reuters", "google", "google_zh", "zhihu"):
            self.assertFalse(should_translate_summary(key), f"{key} summary should NOT translate")


class TranslationJsonParseTests(unittest.TestCase):
    def test_parses_plain_json(self):
        from server import _parse_translation_json
        self.assertEqual(_parse_translation_json('{"0":"你好"}'), {"0": "你好"})

    def test_parses_markdown_fenced_json(self):
        from server import _parse_translation_json
        self.assertEqual(
            _parse_translation_json('```json\n{"0":"你好","1":"世界"}\n```'),
            {"0": "你好", "1": "世界"},
        )

    def test_parses_json_with_leading_prose(self):
        from server import _parse_translation_json
        self.assertEqual(
            _parse_translation_json('Here is the result: {"0":"你好"} done.'),
            {"0": "你好"},
        )

    def test_empty_returns_empty_dict(self):
        from server import _parse_translation_json
        self.assertEqual(_parse_translation_json(""), {})
        self.assertEqual(_parse_translation_json("no json here"), {})


class TranslateItemsTests(unittest.TestCase):
    def setUp(self):
        import server
        self._old_available = server.ai_translation_available
        server.ai_translation_available = lambda: True
        self._old_call = server._call_ai_api_stream
        # Clear translation cache so prior tests don't interfere.
        server.TRANSLATION_CACHE._store.clear()

    def tearDown(self):
        import server
        server.ai_translation_available = self._old_available
        server._call_ai_api_stream = self._old_call
        server.TRANSLATION_CACHE._store.clear()

    def _mock_translations(self, mapping):
        """Make _call_ai_api_stream return a JSON string of *mapping*."""
        import server
        server._call_ai_api_stream = lambda prompt, **kw: iter([json.dumps(mapping)])

    def test_translates_title_and_preserves_original(self):
        self._mock_translations({"0": "你好世界", "1": "简短摘要"})
        meta = SOURCES["economist"]
        items = [
            make_item("economist", meta, title="Hello World",
                      url="https://x.com/a", summary="A short summary"),
            make_item("economist", meta, title="Second Story",
                      url="https://x.com/b", summary=""),
        ]
        translate_items(items, "economist")
        self.assertEqual(items[0]["title"], "你好世界")
        self.assertEqual(items[0]["titleOriginal"], "Hello World")
        self.assertEqual(items[0]["summary"], "简短摘要")
        self.assertEqual(items[0]["summaryOriginal"], "A short summary")
        # No summary -> no summaryOriginal
        self.assertNotIn("summaryOriginal", items[1])

    def test_skips_chinese_sources(self):
        import server
        calls = []
        server._call_ai_api_stream = lambda prompt, **kw: calls.append(prompt) or iter(["{}"])
        meta = SOURCES["zhihu"]
        items = [make_item("zhihu", meta, title="知乎热榜标题", url="https://zhihu.com/q/1")]
        translate_items(items, "zhihu")
        self.assertEqual(items[0]["title"], "知乎热榜标题")  # unchanged
        self.assertEqual(calls, [])  # no AI calls

    def test_skips_summary_for_non_prose_sources(self):
        # HN: title translated, summary (author name) NOT translated
        self._mock_translations({"0": "Show HN: 一个项目"})
        meta = SOURCES["hn"]
        items = [make_item("hn", meta, title="Show HN: Foo",
                           url="https://x.com/a", summary="tptacek")]
        translate_items(items, "hn")
        self.assertEqual(items[0]["title"], "Show HN: 一个项目")
        self.assertEqual(items[0]["titleOriginal"], "Show HN: Foo")
        self.assertNotIn("summaryOriginal", items[0])

    def test_skips_already_translated_items(self):
        """Items with titleOriginal are not re-sent to the AI."""
        import server
        calls = []
        server._call_ai_api_stream = lambda prompt, **kw: calls.append(prompt) or iter(["{}"])
        meta = SOURCES["economist"]
        item = make_item("economist", meta, title="Hello", url="https://x.com/a")
        item["titleOriginal"] = "Hello"
        item["title"] = "你好"
        translate_items([item], "economist")
        self.assertEqual(calls, [])  # nothing to translate

    def test_ai_failure_leaves_items_unchanged(self):
        import server
        server._call_ai_api_stream = lambda prompt, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
        meta = SOURCES["economist"]
        items = [make_item("economist", meta, title="Hello", url="https://x.com/a")]
        translate_items(items, "economist")
        self.assertEqual(items[0]["title"], "Hello")  # unchanged

    def test_cache_hit_skips_ai_call(self):
        """Second call with the same texts should not hit the AI again."""
        import server
        calls = []
        self._mock_translations({"0": "你好"})
        meta = SOURCES["economist"]
        items = [make_item("economist", meta, title="Hello", url="https://x.com/a")]

        def counting_call(prompt, **kw):
            calls.append(prompt)
            return iter([json.dumps({"0": "你好"})])

        server._call_ai_api_stream = counting_call
        translate_items(items, "economist")
        self.assertEqual(len(calls), 1)

        # Second call with same text -> should hit cache, no new AI call.
        items2 = [make_item("economist", meta, title="Hello", url="https://x.com/b")]
        translate_items(items2, "economist")
        self.assertEqual(len(calls), 1)  # still 1
        self.assertEqual(items2[0]["title"], "你好")

    def test_batch_fallback_on_truncated_json(self):
        """When the first batch returns unparseable JSON, retry in smaller batches."""
        import server
        call_count = [0]

        def mock_call(prompt, **kw):
            call_count[0] += 1
            # First call (full batch) returns truncated JSON.
            # Subsequent calls (small batches) succeed.
            if call_count[0] == 1:
                return iter(['{"0":"第一条译文","1":"第二'])  # truncated
            return iter(['{"0":"第一条译文"}'])  # small batch succeeds

        server._call_ai_api_stream = mock_call
        meta = SOURCES["economist"]
        # Need >10 jobs to trigger the fallback path.
        items = [
            make_item("economist", meta, title=f"Title {i}", url=f"https://x.com/{i}")
            for i in range(15)
        ]
        translate_items(items, "economist")
        # At least the first item should be translated via the fallback.
        self.assertEqual(items[0]["title"], "第一条译文")
        self.assertEqual(items[0]["titleOriginal"], "Title 0")
        # Multiple calls: 1 initial + at least 1 fallback batch.
        self.assertGreater(call_count[0], 1)


if __name__ == "__main__":
    unittest.main()
