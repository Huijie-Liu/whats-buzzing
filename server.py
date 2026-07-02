#!/usr/bin/env python3
"""What's Buzzing — multi-source news aggregator.

Thin entry point.  All domain logic lives in ``src/``.
This module re-exports the public API so existing callers
(tests, Vercel ``api/index.py``) are unaffected by internal restructuring.
"""

# ── Flask app (Vercel WSGI entry point) ────────────────────────────────
from src.app import create_flask_app

app = create_flask_app()


# ── Re-exports for backward compatibility (tests import from server) ───
from src.config import (
    ROOT, PUBLIC_DIR, HOST, PORT, CACHE_SECONDS,
    REQUEST_HEADERS, USER_AGENT,
    NS, SOURCES,
    NON_TRANSLATABLE_SOURCES, SUMMARY_TRANSLATABLE_SOURCES,
    _CURL_CFFI_AVAILABLE, curl_cffi, CurlFollow,
)

from src.cache import TTLLRU, RateLimiter
from src.security import (
    is_safe_url, _SAFE_OPENER,
    client_ip_from_headers, debug_enabled,
)

from src.parsers import (
    TAG_RE, text, clean_html, child_text, normalize_date,
    iso_now, make_item, dedupe_items, source_payload,
    fetch_source, fetch_feed_collection,
)

from src.parsers.feed_parsers import (
    parse_rss, rss_image, parse_atom, atom_link,
    parse_google_rss, parse_discourse, parse_reuters_sitemap,
    DISCOURSE_NOISE_RE, LOCALIZED_REUTERS_PREFIXES,
)

from src.parsers.custom import (
    fetch_hn, fetch_zhihu, zhihu_item_url, zhihu_score,
    fetch_hupu_sub,
)

from src.fetch import (
    META_DESC_RE, OG_IMAGE_RE, P_TAG_RE, TITLE_RE,
    PREVIEW_CACHE_TTL, IMAGE_CACHE_TTL, PREVIEW_MAX_BYTES,
    PREVIEW_CACHE, IMAGE_CACHE,
    _curl_fetch, fetch_url, read_limited,
    fetch_preview_url, fetch_preview_image,
    extract_snippet, extract_og_image, upscale_image_url,
    preview_payload, preview_image_payload,
)

from src.ai import (
    CLAUDE_DEEPSEEK, DEEPSEEK_KEY, DEEPSEEK_BASE_URL, AI_MODEL,
    _deepseek_client,
    ai_translation_available, should_translate_source, should_translate_summary,
    SUMMARY_LIMITER, SUMMARY_MAX_ITEMS, TRANSLATE_LIMITER, TRANSLATE_MAX_ITEMS,
    TRANSLATION_CACHE_TTL, TRANSLATION_CACHE,
    TRANSLATION_SYSTEM_PROMPT, SUMMARY_SYSTEM_PROMPT,
    translate_items, translate_events,
    _call_ai_api_stream, _build_summary_data, summary_events,
    _parse_translation_json, _run_translation_jobs,
)

from src.app import (
    PREVIEW_LIMITER,
    api_headers, cors_preflight_response, json_response,
    parse_flask_query, stream_feed,
)


# ── Dev server ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    from werkzeug.serving import make_server
    srv = make_server(HOST, PORT, app, threaded=True)
    print(f"What's Buzzing running at http://{HOST}:{PORT}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
