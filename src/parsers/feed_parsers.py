"""XML-feed parsers: RSS, Atom, Google News RSS, Discourse, Reuters sitemap."""

import html as _html
import re
import time
import urllib.error
import xml.etree.ElementTree as ET

from src.config import (
    SOURCES, NS, USER_AGENT, _CURL_CFFI_AVAILABLE,
)
from src.fetch import _curl_fetch
from src.parsers import (
    child_text, clean_html, make_item, normalize_date,
)

LOCALIZED_REUTERS_PREFIXES = ("/es/", "/de/", "/fr/", "/pt/", "/ja/", "/zh-hans/")


# =========================================================================
# RSS
# =========================================================================

def rss_image(item):
    # Collect all media:content URLs — pick the largest by width if multiple exist
    candidates = []
    for media in item.findall("media:content", NS):
        url = media.attrib.get("url")
        if url:
            m = re.search(r"width=(\d+)", url)
            w = int(m.group(1)) if m else 0
            candidates.append((w, url))
    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[-1][1]  # largest width

    media = item.find("media:thumbnail", NS)
    if media is not None and media.attrib.get("url"):
        return media.attrib["url"]
    for enclosure in item.findall("enclosure"):
        if enclosure.attrib.get("type", "").startswith("image/") and enclosure.attrib.get("url"):
            return enclosure.attrib["url"]
    return ""


def parse_rss(source_key, meta, raw):
    root = ET.fromstring(raw)
    channel = root.find("channel")
    if channel is None:
        return [], ""
    latest = child_text(channel, "lastBuildDate") or child_text(channel, "pubDate")
    items = []
    for item in channel.findall("item"):
        title = child_text(item, "title")
        link = child_text(item, "link")
        if not title or not link:
            continue
        items.append(
            make_item(
                source_key,
                meta,
                title=title,
                url=link,
                summary=child_text(item, "description"),
                image=rss_image(item),
                published_at=child_text(item, "pubDate"),
                item_id=child_text(item, "guid") or link,
            )
        )
    return items, latest


# =========================================================================
# Atom
# =========================================================================

def atom_link(entry):
    links = entry.findall("atom:link", NS)
    alternate = [link for link in links if link.attrib.get("rel", "alternate") == "alternate"]
    link = (alternate or links or [None])[0]
    return link.attrib.get("href", "") if link is not None else ""


def parse_atom(source_key, meta, raw):
    root = ET.fromstring(raw)
    latest = child_text(root, "atom:updated", NS)
    items = []
    for entry in root.findall("atom:entry", NS):
        title = child_text(entry, "atom:title", NS)
        link = atom_link(entry)
        if not title or not link:
            continue
        media = entry.find("media:content", NS)
        img = media.attrib.get("url", "") if media is not None else ""
        # Fallback: extract first <img> from content HTML (e.g. The Verge)
        if not img:
            content = entry.find("atom:content", NS)
            if content is not None and content.text:
                m = re.search(r'<img[^>]+src="([^"]+)"', content.text)
                if m:
                    img = m.group(1)
        items.append(
            make_item(
                source_key,
                meta,
                title=title,
                url=link,
                summary=child_text(entry, "atom:summary", NS),
                image=img,
                published_at=child_text(entry, "atom:published", NS)
                or child_text(entry, "atom:updated", NS),
                item_id=child_text(entry, "atom:id", NS) or link,
            )
        )
    return items, latest


# =========================================================================
# Google News RSS
# =========================================================================

_GOOGLE_IMAGES_CACHE = {}
_GOOGLE_IMAGES_CACHE_TTL = 180

_PUBLISHER_DOMAINS = {
    "bbc.co.uk": "bbc", "bbc.com": "bbc", "files.bbci": "bbc", "ichef.bbci": "bbc",
    "nyt.com": "the new york times", "nytimes.com": "the new york times",
    "brightspotcdn": "npr", "npr.org": "npr",
    "media.cnn.com": "cnn", "cnn.com": "cnn",
    "washingtonpost.com": "the washington post",
    "theguardian.com": "the guardian", "guim.co.uk": "the guardian",
    "wsj.com": "the wall street journal",
    "reuters.com": "reuters",
    "bloomberg.com": "bloomberg", "bloomberglaw.com": "bloomberg",
    "nbcnews.com": "nbc news",
    "abcnews.go.com": "abc news", "abcotvs.com": "abc news",
    "cbsnews.com": "cbs news", "cbsnewsstatic.com": "cbs news",
    "foxnews.com": "fox news",
    "politico.com": "politico", "politico.eu": "politico.eu",
    "thehill.com": "the hill",
    "axios.com": "axios",
    "vox.com": "vox",
    "apnews.com": "associated press",
    "usatoday.com": "usa today",
    "cnbc.com": "cnbc",
    "aljazeera.com": "al jazeera",
    "france24.com": "france 24",
    "yahoo.com": "yahoo", "yimg.com": "yahoo",
    "ft.com": "financial times",
    "theverge.com": "the verge",
    "deadline.com": "deadline",
    "variety.com": "variety",
    "space.com": "space",
    "engadget.com": "engadget",
    "cnet.com": "cnet",
    "9to5google.com": "9to5google", "9to5mac.com": "9to5google",
}


def _unescape_unicode(s):
    """Decode \\uXXXX escape sequences in a string."""
    return re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m.group(1), 16)), s)


def _guess_publisher_from_url(url):
    """Guess a publisher name from an image URL domain."""
    url_lower = url.lower()
    for domain_pattern, name in _PUBLISHER_DOMAINS.items():
        if domain_pattern in url_lower:
            return name
    return ""


def _fetch_google_homepage_images(home_url):
    """Scrape a Google News homepage and return a list of (image_url, publisher) pairs
    in page order.  Publisher names are normalised for matching against RSS <source>."""
    now = time.time()
    cached = _GOOGLE_IMAGES_CACHE.get(home_url)
    if cached and now - cached[0] < _GOOGLE_IMAGES_CACHE_TTL:
        return cached[1]

    if not _CURL_CFFI_AVAILABLE:
        _GOOGLE_IMAGES_CACHE[home_url] = (now, [])
        return []

    try:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        }
        raw = _curl_fetch(home_url, headers, timeout=15)
        html_text = raw.decode("utf-8", errors="replace")
    except Exception:
        _GOOGLE_IMAGES_CACHE[home_url] = (now, [])
        return []

    html_decoded = _unescape_unicode(html_text)
    imgs = re.findall(r'"(https?://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"', html_decoded)

    result = []
    seen = set()
    for img in imgs:
        img = _html.unescape(img)
        if "google" in img.lower() or "gstatic" in img.lower():
            continue
        if img in seen:
            continue
        seen.add(img)
        publisher = _guess_publisher_from_url(img)
        result.append((img, publisher))

    _GOOGLE_IMAGES_CACHE[home_url] = (now, result)
    return result


def _match_google_images(items, home_url):
    """Enrich Google News RSS items with images from the homepage."""
    if not items:
        return
    image_pairs = _fetch_google_homepage_images(home_url)
    if not image_pairs:
        return

    publisher_idx = {}
    publisher_pool = {}
    for img_url, publisher in image_pairs:
        if publisher:
            publisher_pool.setdefault(publisher, []).append(img_url)

    for item in items:
        publisher_name = (item.get("summary") or "").strip().lower()
        pool = publisher_pool.get(publisher_name)
        if pool:
            idx = publisher_idx.get(publisher_name, 0)
            if idx < len(pool):
                item["image"] = pool[idx]
                publisher_idx[publisher_name] = idx + 1


def parse_google_rss(source_key, meta, raw):
    root = ET.fromstring(raw)
    channel = root.find("channel")
    if channel is None:
        return [], ""
    latest = child_text(channel, "lastBuildDate") or child_text(channel, "pubDate")
    items = []
    for item in channel.findall("item"):
        title = child_text(item, "title")
        link = child_text(item, "link")
        publisher = child_text(item, "source")
        if not title or not link:
            continue
        if title.strip().lower().startswith("print edition"):
            continue
        if publisher:
            for separator in (" - ", " | "):
                suffix = f"{separator}{publisher}"
                if title.endswith(suffix):
                    title = title[:-len(suffix)]
                    break
        summary = publisher
        items.append(
            make_item(
                source_key,
                meta,
                title=title,
                url=link,
                summary=summary,
                image="",
                published_at=child_text(item, "pubDate"),
                item_id=child_text(item, "guid") or link,
            )
        )
    home_url = meta.get("home", "")
    if home_url:
        _match_google_images(items, home_url)
    return items, latest


# =========================================================================
# Discourse
# =========================================================================

DISCOURSE_NOISE_RE = re.compile(
    r"\s*\d+\s+(?:个帖子|posts?)\s*-\s*\d+\s+(?:位参与者|participants?)\s+"
    r"(?:阅读完整话题|Read full topic)\s*$",
    re.IGNORECASE,
)


def parse_discourse(source_key, meta, raw):
    root = ET.fromstring(raw)
    channel = root.find("channel")
    if channel is None:
        return [], ""
    latest = child_text(channel, "lastBuildDate") or child_text(channel, "pubDate")
    items = []
    for item in channel.findall("item"):
        pinned = child_text(item, "discourse:topicPinned", NS).strip().lower()
        if pinned == "yes":
            continue
        title = child_text(item, "title")
        link = child_text(item, "link")
        if not title or not link:
            continue
        desc_elem = item.find("description")
        raw_desc = desc_elem.text if desc_elem is not None else ""
        img = ""
        if raw_desc:
            m = re.search(r'<img[^>]+src="([^"]+)"', raw_desc)
            if m:
                img = m.group(1)
        summary = DISCOURSE_NOISE_RE.sub("", clean_html(raw_desc)).strip()
        items.append(
            make_item(
                source_key,
                meta,
                title=title,
                url=link,
                summary=summary,
                image=img,
                published_at=child_text(item, "pubDate"),
                item_id=child_text(item, "guid") or link,
            )
        )
    return items, latest


# =========================================================================
# Reuters sitemap
# =========================================================================

def _is_localized_reuters_url(url):
    from urllib.parse import urlparse
    parsed = urlparse(url)
    return parsed.path.startswith(LOCALIZED_REUTERS_PREFIXES)


def parse_reuters_sitemap(source_key, meta, raw):
    root = ET.fromstring(raw)
    items = []
    latest = ""
    for url_node in root.findall("sm:url", NS):
        loc = child_text(url_node, "sm:loc", NS)
        if not loc or _is_localized_reuters_url(loc):
            continue
        news_node = url_node.find("news:news", NS)
        title = child_text(news_node, "news:title", NS)
        published = child_text(news_node, "news:publication_date", NS) or child_text(
            url_node, "sm:lastmod", NS
        )
        image = child_text(url_node, "image:image/image:loc", NS)
        if not title:
            continue
        latest = max(latest, normalize_date(published))
        items.append(
            make_item(
                source_key,
                meta,
                title=title,
                url=loc,
                image=image,
                published_at=published,
                item_id=loc,
            )
        )
    return items, latest
