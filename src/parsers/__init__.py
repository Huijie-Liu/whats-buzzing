"""Feed parser registry, shared utilities, and source fetching.

Adding a new source kind:
1. Write the parser/fetcher function in ``feed_parsers.py`` or ``custom.py``.
2. Add a ``kind`` → callable entry to ``PARSER_REGISTRY`` below.
3. Add the source config to ``SOURCES`` in ``src/config.py``.
"""

import html as _html
import json
import re
import threading
import time
import urllib.error
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from src.cache import TTLLRU
from src.config import SOURCES, NS, CACHE_SECONDS
from src.fetch import fetch_url, upscale_image_url

# ── Shared regex & module-level state ──────────────────────────────────

TAG_RE = re.compile(r"<[^>]+>")
_cache = {}
_cache_lock = threading.Lock()


# ── Text / XML helpers ─────────────────────────────────────────────────

def iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def text(value):
    if isinstance(value, str):
        return " ".join(value.split())
    return ""


def clean_html(value):
    return text(_html.unescape(TAG_RE.sub(" ", value or "")))


def child_text(node, path, namespaces=None):
    if node is None:
        return ""
    child = node.find(path, namespaces or {})
    if child is None:
        return ""
    return clean_html("".join(child.itertext()))


def normalize_date(value):
    value = text(value)
    if not value:
        return ""
    try:
        if value.endswith("Z"):
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            parsed = datetime.fromisoformat(value)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


# ── Item construction ──────────────────────────────────────────────────

def make_item(
    source_key,
    meta,
    *,
    title,
    url,
    summary="",
    image="",
    published_at="",
    item_id="",
    score=None,
    comments=None,
    discussion_url="",
    rank=None,
):
    stable_id = item_id or url or title
    return {
        "id": f"{source_key}:{stable_id}",
        "source": source_key,
        "sourceLabel": meta["label"],
        "sourceShort": meta["short"],
        "accent": meta["accent"],
        "title": text(title),
        "summary": clean_html(summary),
        "url": text(url),
        "discussionUrl": text(discussion_url),
        "image": text(upscale_image_url(image)),
        "publishedAt": normalize_date(published_at),
        "score": score,
        "comments": comments,
        "rank": rank,
        "tags": [],
    }


def dedupe_items(items):
    seen = set()
    output = []
    for item in items:
        key = item.get("url") or item.get("id")
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output


def source_payload(source_key, items, latest_build_time=""):
    meta = SOURCES[source_key]
    items = dedupe_items(items)
    limit = meta.get("story_limit", 20)
    if limit and len(items) > limit:
        items = items[:limit]
    return {
        "key": source_key,
        "label": meta["label"],
        "short": meta["short"],
        "accent": meta["accent"],
        "home": meta["home"],
        "latestBuildTime": normalize_date(latest_build_time),
        "items": items,
    }


# ── Feed collection (shared by RSS / Atom / Google / Discourse / Sitemap) ──

def fetch_feed_collection(source_key, parser):
    meta = SOURCES[source_key]
    feeds = meta["feeds"]
    extra_headers = meta.get("headers")
    latest_values = []
    errors = []
    feed_results = []

    with ThreadPoolExecutor(max_workers=min(8, len(feeds))) as pool:
        jobs = {
            pool.submit(
                fetch_url, url,
                "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9",
                extra_headers,
            ): (idx, url)
            for idx, url in enumerate(feeds)
        }
        for job in as_completed(jobs):
            idx, url = jobs[job]
            try:
                parsed_items, latest = parser(source_key, meta, job.result())
                feed_results.append((idx, parsed_items))
                if latest:
                    latest_values.append(latest)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ET.ParseError) as exc:
                errors.append(f"{url}: {exc}")

    if not feed_results and errors:
        raise RuntimeError("; ".join(errors))
    feed_results.sort(key=lambda x: x[0])
    items = []
    for _, feed_items in feed_results:
        for it in feed_items:
            it["rank"] = len(items) + 1
            items.append(it)
    latest = max((normalize_date(value) for value in latest_values), default="")
    return source_payload(source_key, items, latest)


# ── Parser registry & dispatcher ───────────────────────────────────────

def _feed_collection(parser):
    """Wrap a parse_* function so PARSER_REGISTRY entries are uniform."""
    return lambda source_key: fetch_feed_collection(source_key, parser)


# Import parser functions lazily to avoid circular imports.
# The registry maps ``kind`` → ``callable(source_key) -> payload``.

def _build_registry():
    from src.parsers.feed_parsers import (
        parse_rss, parse_atom, parse_google_rss,
        parse_discourse, parse_reuters_sitemap,
    )
    from src.parsers.custom import fetch_hn, fetch_zhihu, fetch_hupu_sub

    return {
        "rss": _feed_collection(parse_rss),
        "atom": _feed_collection(parse_atom),
        "google_rss": _feed_collection(parse_google_rss),
        "discourse": _feed_collection(parse_discourse),
        "reuters_sitemap": _feed_collection(parse_reuters_sitemap),
        "zhihu": fetch_zhihu,
        "hn": fetch_hn,
        "hupu_sub": fetch_hupu_sub,
    }


PARSER_REGISTRY = None  # populated on first use


def _get_registry():
    global PARSER_REGISTRY
    if PARSER_REGISTRY is None:
        PARSER_REGISTRY = _build_registry()
    return PARSER_REGISTRY


def fetch_source(source_key):
    now = time.time()
    with _cache_lock:
        cached = _cache.get(source_key)
        if cached and now - cached["time"] < CACHE_SECONDS:
            return cached["payload"]

    kind = SOURCES[source_key]["kind"]
    handler = _get_registry().get(kind)
    if handler is None:
        raise RuntimeError(f"Unknown source kind: {kind}")
    payload = handler(source_key)

    with _cache_lock:
        _cache[source_key] = {"time": now, "payload": payload}
    return payload
