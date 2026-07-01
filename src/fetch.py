"""URL fetching, preview extraction, and image helpers."""

import html as _html
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from src.cache import TTLLRU
from src.config import REQUEST_HEADERS, USER_AGENT, _CURL_CFFI_AVAILABLE
from src.security import is_safe_url, _SAFE_OPENER

# ── Caches ─────────────────────────────────────────────────────────────

PREVIEW_CACHE_TTL = 600
IMAGE_CACHE_TTL = 3600
PREVIEW_MAX_BYTES = 1_000_000
PREVIEW_CACHE = TTLLRU(PREVIEW_CACHE_TTL, 500)
IMAGE_CACHE = TTLLRU(IMAGE_CACHE_TTL, 500)

# ── Regexes for snippet / OG extraction ────────────────────────────────

META_DESC_RE = re.compile(
    r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]+content=["\']([^"\']+)["\']'
    r'|<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:name|property)=["\'](?:description|og:description)["\']',
    re.IGNORECASE,
)
OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']'
    r'|<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    re.IGNORECASE,
)
P_TAG_RE = re.compile(r"<p[^>]*>(.+?)</p>", re.DOTALL | re.IGNORECASE)
TITLE_RE = re.compile(r"<title[^>]*>(.+?)</title>", re.DOTALL | re.IGNORECASE)
BODY_TEXT_RE = re.compile(r"<body[^>]*>(.*?)</body>", re.DOTALL | re.IGNORECASE)

# Strip-tags regex (duplicated from parsers to avoid circular import)
_TAG_RE = re.compile(r"<[^>]+>")


# ── Text helpers ───────────────────────────────────────────────────────

def _text(value):
    if isinstance(value, str):
        return " ".join(value.split())
    return ""


def _clean_html(value):
    return _text(_html.unescape(_TAG_RE.sub(" ", value or "")))


# ── Snippet / OG extraction ────────────────────────────────────────────

def extract_snippet(html_text):
    m = META_DESC_RE.search(html_text)
    if m:
        desc = m.group(1) or m.group(2)
        if desc:
            return _clean_html(desc)[:500]

    parts = []
    for p_html in P_TAG_RE.findall(html_text):
        cleaned = _clean_html(p_html)
        if len(cleaned) > 30:
            parts.append(cleaned)
        if len(" ".join(parts)) > 500:
            break
    if parts:
        return " ".join(parts)[:500]

    m = TITLE_RE.search(html_text)
    if m:
        title = _clean_html(m.group(1))
        if len(title) > 10:
            return title[:500]

    return ""


_HUPU_IMAGE_CACHE = {}  # post_id → image_url (short-lived, cleared per request)


def extract_og_image(html_text):
    m = OG_IMAGE_RE.search(html_text)
    if m:
        url = m.group(1) or m.group(2)
        if url:
            url = _html.unescape(url).strip()
            if url.startswith("http"):
                return url
    # Hupu: extract from Next.js __NEXT_DATA__ SSR payload
    if 'hoopchina' in html_text or 'hupu' in html_text:
        img = _extract_hupu_image(html_text)
        if img:
            return img
    return ""


def _extract_hupu_image(html_text):
    """Extract the first post image from a Hupu post detail page's
    ``__NEXT_DATA__`` SSR JSON payload.

    Scans ``thread.cardList[].image`` and ``thread.content`` for images.
    Returns ``""`` if no image is found."""
    import json as _json
    m = re.search(
        r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',
        html_text, re.DOTALL,
    )
    if not m:
        return ""
    try:
        data = _json.loads(m.group(1))
    except (ValueError, _json.JSONDecodeError):
        return ""

    def _first_str(pool):
        """Depth-first walk for a string that looks like an image URL."""
        if isinstance(pool, str):
            return pool if (pool.startswith("http") and _looks_like_image(pool)) else None
        if isinstance(pool, dict):
            for key in ("image", "cover", "imgs", "img", "images"):
                val = pool.get(key)
                if isinstance(val, str) and val.startswith("http") and _looks_like_image(val):
                    return val
            for val in pool.values():
                result = _first_str(val)
                if result:
                    return result
        if isinstance(pool, list):
            for item in pool:
                result = _first_str(item)
                if result:
                    return result
        return None

    detail = data.get("props", {}).get("pageProps", {}).get("detail", {})
    if not isinstance(detail, dict):
        return ""
    thread = detail.get("thread")
    if isinstance(thread, dict):
        img = _first_str(thread.get("cardList"))
        if img:
            # Upgrade to HTTPS for mixed-content safety
            if img.startswith("http://"):
                img = "https://" + img[7:]
            return img
    return ""


def _looks_like_image(url):
    """True if *url* appears to be a real image (not a UI asset like a logo)."""
    bad = ("logo", "icon", "avatar", "error", "favicon", "bg.", "static/")
    url_lower = url.lower()
    return not any(b in url_lower for b in bad) and any(
        url_lower.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif")
    )


def upscale_image_url(url):
    """Rewrite known low-res image URLs to request larger / higher-quality versions."""
    if "ichef.bbci.co.uk" in url or "ichef.bbc.co.uk" in url:
        url = re.sub(r"/news/\d+/", "/news/976/", url)
        url = re.sub(r"/standard/\d+/", "/standard/976/", url)
        return url
    if "googleusercontent.com" in url:
        url = re.sub(r"w\d+", "w800", url)
        return url
    return url


# ── HTTP fetching ──────────────────────────────────────────────────────

def _curl_fetch(url, headers, timeout=18):
    """Fetch *url* with curl_cffi (Chrome 131 TLS fingerprint, SSRF-safe redirects)."""
    import curl_cffi
    from curl_cffi import CurlFollow
    try:
        resp = curl_cffi.requests.get(
            url,
            headers=headers,
            timeout=timeout,
            impersonate="chrome131",
            allow_redirects=CurlFollow.SAFE,
        )
        resp.raise_for_status()
        return resp.content
    except curl_cffi.requests.exceptions.Timeout as e:
        raise TimeoutError(str(e)) from e
    except curl_cffi.requests.exceptions.HTTPError as e:
        raise urllib.error.URLError(f"HTTP error: {e}") from e
    except curl_cffi.requests.exceptions.RequestException as e:
        raise urllib.error.URLError(str(e)) from e


def fetch_url(url, accept, extra_headers=None):
    headers = dict(REQUEST_HEADERS)
    if extra_headers:
        headers.update(extra_headers)
    headers["Accept"] = accept
    if _CURL_CFFI_AVAILABLE:
        if not is_safe_url(url):
            raise urllib.error.URLError(f"unsafe url: {url}")
        return _curl_fetch(url, headers)
    req = urllib.request.Request(url, headers=headers)
    with _SAFE_OPENER.open(req, timeout=18) as response:
        return response.read()


def read_limited(response, limit=PREVIEW_MAX_BYTES):
    """Read at most *limit* bytes from a remote response."""
    return response.read(limit)


def fetch_preview_url(url):
    parsed = urllib.parse.urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
        "Referer": origin + "/",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
    }
    if _CURL_CFFI_AVAILABLE:
        try:
            raw = _curl_fetch(url, headers, timeout=12)
            return raw.decode("utf-8", errors="replace")
        except (urllib.error.URLError, TimeoutError):
            pass
    request = urllib.request.Request(url, headers=headers)
    with _SAFE_OPENER.open(request, timeout=12) as response:
        raw = read_limited(response)
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


def fetch_preview_image(url):
    """Fetch og:image from the given URL.  Returns "" on failure.  Cached."""
    parsed = urllib.parse.urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
        "Referer": origin + "/",
    }
    if _CURL_CFFI_AVAILABLE:
        try:
            raw = _curl_fetch(url, headers, timeout=18)
            html_text = raw.decode("utf-8", errors="replace")
            image = extract_og_image(html_text)
            return upscale_image_url(image)
        except (urllib.error.URLError, TimeoutError):
            pass
    request = urllib.request.Request(url, headers=headers)
    request.add_header("DNT", "1")
    with _SAFE_OPENER.open(request, timeout=10) as response:
        raw = read_limited(response)
        charset = response.headers.get_content_charset() or "utf-8"
        image = extract_og_image(raw.decode(charset, errors="replace"))
        return upscale_image_url(image)


# ── Preview payload helpers (used by Flask routes) ─────────────────────

def preview_payload(url):
    if not url or not url.startswith(("http://", "https://")):
        return {"error": "invalid url"}, 400
    if not is_safe_url(url):
        return {"error": "url not allowed"}, 403

    now = time.time()
    cached = PREVIEW_CACHE.get(url, now)
    if cached is not None:
        return {"snippet": cached}, 200

    try:
        raw = fetch_preview_url(url)
        snippet = extract_snippet(raw)
    except Exception as exc:
        return {"snippet": f"[预览不可用] {exc}"}, 200

    PREVIEW_CACHE.set(url, snippet, now)
    return {"snippet": snippet}, 200


def preview_image_payload(url):
    if not url or not url.startswith(("http://", "https://")):
        return {"error": "invalid url"}, 400
    if not is_safe_url(url):
        return {"error": "url not allowed"}, 403

    now = time.time()
    cached = IMAGE_CACHE.get(url, now)
    if cached is not None:
        return {"image": cached}, 200

    try:
        image = fetch_preview_image(url)
    except Exception:
        image = ""
    IMAGE_CACHE.set(url, image, now)
    return {"image": image}, 200
