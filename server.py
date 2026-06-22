#!/usr/bin/env python3
import html
import ipaddress
import json
import mimetypes
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import openai
except ImportError:
    openai = None

try:
    from flask import (
        Flask,
        Response,
        abort,
        request,
        send_from_directory,
        stream_with_context,
    )
except ImportError:
    Flask = None
    Response = None
    abort = None
    request = None
    send_from_directory = None
    stream_with_context = None


ROOT = Path(__file__).resolve().parent
PUBLIC_DIR = ROOT / "public"
HOST = "127.0.0.1"
PORT = int(os.environ.get("PORT", "8765"))
CACHE_SECONDS = 180

REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 NewsFocus/1.0",
    "Accept-Language": "en-US,en;q=0.9",
}

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "dc": "http://purl.org/dc/elements/1.1/",
    "discourse": "http://www.discourse.org/",
    "image": "http://www.google.com/schemas/sitemap-image/1.1",
    "media": "http://search.yahoo.com/mrss/",
    "news": "http://www.google.com/schemas/sitemap-news/0.9",
    "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
}

SOURCES = {
    "hn": {
        "label": "Hacker News",
        "short": "HN",
        "kind": "hn",
        "home": "https://news.ycombinator.com/",
        "accent": "#f0652f",
        "story_limit": 20,
    },
    "economist": {
        "label": "经济学人",
        "short": "Economist",
        "kind": "rss",
        "home": "https://www.economist.com/latest",
        "accent": "#d71920",
        "story_limit": 20,
        "feeds": ["https://www.economist.com/latest/rss.xml"],
    },
    "reuters": {
        "label": "路透社",
        "short": "Reuters",
        "kind": "reuters_sitemap",
        "home": "https://www.reuters.com/",
        "accent": "#ff8000",
        "story_limit": 20,
        "feeds": [
            "https://www.reuters.com/arc/outboundfeeds/news-sitemap/?outputType=xml",
            "https://www.reuters.com/arc/outboundfeeds/news-sitemap/?outputType=xml&from=100",
            "https://www.reuters.com/arc/outboundfeeds/news-sitemap/?outputType=xml&from=200",
        ],
    },
    "bloomberg": {
        "label": "彭博社",
        "short": "Bloomberg",
        "kind": "rss",
        "home": "https://www.bloomberg.com/",
        "accent": "#0068ff",
        "story_limit": 20,
        "feeds": [
            "https://feeds.bloomberg.com/markets/news.rss",
            "https://feeds.bloomberg.com/economics/news.rss",
            "https://feeds.bloomberg.com/technology/news.rss",
            "https://feeds.bloomberg.com/politics/news.rss",
            "https://feeds.bloomberg.com/industries/news.rss",
            "https://feeds.bloomberg.com/wealth/news.rss",
            "https://feeds.bloomberg.com/green/news.rss",
            "https://feeds.bloomberg.com/businessweek/news.rss",
            "https://feeds.bloomberg.com/pursuits/news.rss",
        ],
    },
    "guardian": {
        "label": "卫报",
        "short": "Guardian",
        "kind": "rss",
        "home": "https://www.theguardian.com/",
        "accent": "#052962",
        "story_limit": 20,
        "feeds": [
            "https://www.theguardian.com/world/rss",
            "https://www.theguardian.com/us-news/rss",
            "https://www.theguardian.com/uk-news/rss",
            "https://www.theguardian.com/business/rss",
            "https://www.theguardian.com/technology/rss",
            "https://www.theguardian.com/politics/rss",
        ],
    },
    "bbc": {
        "label": "BBC",
        "short": "BBC",
        "kind": "rss",
        "home": "https://www.bbc.com/news",
        "accent": "#b80000",
        "story_limit": 20,
        "feeds": [
            "https://feeds.bbci.co.uk/news/world/rss.xml",
            "https://feeds.bbci.co.uk/news/uk/rss.xml",
            "https://feeds.bbci.co.uk/news/business/rss.xml",
            "https://feeds.bbci.co.uk/news/technology/rss.xml",
            "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
            "https://feeds.bbci.co.uk/news/politics/rss.xml",
        ],
    },
    "verge": {
        "label": "The Verge",
        "short": "Verge",
        "kind": "atom",
        "home": "https://www.theverge.com/",
        "accent": "#e2127a",
        "story_limit": 20,
        "feeds": ["https://www.theverge.com/rss/index.xml"],
    },
    "google": {
        "label": "Google News 美国",
        "short": "Google",
        "kind": "google_rss",
        "home": "https://news.google.com/topstories?hl=en-US&gl=US&ceid=US:en",
        "accent": "#1a73e8",
        "story_limit": 20,
        "feeds": [
            "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/headlines/section/topic/NATION?hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=en-US&gl=US&ceid=US:en",
            "https://news.google.com/rss/headlines/section/topic/HEALTH?hl=en-US&gl=US&ceid=US:en",
        ],
    },
    "google_zh": {
        "label": "Google News 中国",
        "short": "Google 中国",
        "kind": "google_rss",
        "home": "https://news.google.com/topstories?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "accent": "#34a853",
        "story_limit": 20,
        "feeds": [
            "https://news.google.com/rss?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            "https://news.google.com/rss/headlines/section/topic/WORLD?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            "https://news.google.com/rss/headlines/section/topic/NATION?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            "https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            "https://news.google.com/rss/headlines/section/topic/HEALTH?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        ],
    },
    "atlantic": {
        "label": "大西洋周刊",
        "short": "Atlantic",
        "kind": "atom",
        "home": "https://www.theatlantic.com/",
        "accent": "#111111",
        "story_limit": 20,
        "feeds": ["https://www.theatlantic.com/feed/all/"],
    },
    "newyorker": {
        "label": "纽约客",
        "short": "NewYorker",
        "kind": "rss",
        "home": "https://www.newyorker.com/",
        "accent": "#e60000",
        "story_limit": 20,
        "feeds": ["https://www.newyorker.com/feed/everything"],
    },
    "mit_tech": {
        "label": "MIT 科技评论",
        "short": "MIT Tech",
        "kind": "rss",
        "home": "https://www.technologyreview.com/",
        "accent": "#ff5a00",
        "story_limit": 20,
        "feeds": ["https://www.technologyreview.com/feed/"],
    },
    "zhihu": {
        "label": "知乎热榜",
        "short": "知乎",
        "kind": "zhihu",
        "home": "https://www.zhihu.com/hot",
        "accent": "#0066ff",
        "story_limit": 20,
    },
    "washingtonpost": {
        "label": "华盛顿邮报",
        "short": "WaPo",
        "kind": "rss",
        "home": "https://www.washingtonpost.com/",
        "accent": "#1a1a1a",
        "story_limit": 20,
        "feeds": [
            "https://feeds.washingtonpost.com/rss/world",
            "https://feeds.washingtonpost.com/rss/national",
            "https://feeds.washingtonpost.com/rss/business",
            "https://feeds.washingtonpost.com/rss/politics",
            "https://feeds.washingtonpost.com/rss/technology",
        ],
    },
    "linux_do": {
        "label": "LINUX DO",
        "short": "LINUX DO",
        "kind": "discourse",
        "home": "https://linux.do/new",
        "accent": "#0088cc",
        "story_limit": 20,
        "feeds": ["https://linux.do/latest.rss"],
        "headers": {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    },
    "linux_do_top": {
        "label": "LINUX DO 热榜",
        "short": "LINUX DO 热榜",
        "kind": "discourse",
        "home": "https://linux.do/top",
        "accent": "#0a8ed6",
        "story_limit": 20,
        "feeds": ["https://linux.do/top/daily.rss"],
        "headers": {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    },
}

LOCALIZED_REUTERS_PREFIXES = ("/es/", "/de/", "/fr/", "/pt/", "/ja/", "/zh-hans/")
TAG_RE = re.compile(r"<[^>]+>")
_cache = {}


# =========================================================================
# Infrastructure: TTL+LRU cache, rate limiter, SSRF guard
# =========================================================================

class TTLLRU:
    """Tiny TTL + LRU cache.  Evicts the oldest entry when full and drops
    expired entries on read.  Stored values may be anything — including
    empty strings — since ``None`` is reserved as the miss sentinel."""

    def __init__(self, ttl, maxsize):
        self.ttl = ttl
        self.maxsize = maxsize
        self._store: OrderedDict = OrderedDict()

    def get(self, key, now):
        item = self._store.get(key)
        if item is None:
            return None
        ts, value = item
        if now - ts > self.ttl:
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return value

    def set(self, key, value, now):
        self._store[key] = (now, value)
        self._store.move_to_end(key)
        while len(self._store) > self.maxsize:
            self._store.popitem(last=False)


class RateLimiter:
    """Sliding-window per-key limiter backed by an in-process dict.  Good
    enough to deter abuse on a single instance; state is not shared across
    serverless replicas."""

    def __init__(self, max_calls, period):
        self.max_calls = max_calls
        self.period = period
        self._hits: dict = {}

    def allow(self, key, now=None):
        now = now if now is not None else time.time()
        hits = [t for t in self._hits.get(key, []) if now - t < self.period]
        if len(hits) >= self.max_calls:
            self._hits[key] = hits
            if len(self._hits) > 4096:
                self._hits = {k: v for k, v in self._hits.items() if v}
            return False
        hits.append(now)
        self._hits[key] = hits
        return True


SUMMARY_LIMITER = RateLimiter(max_calls=5, period=60)
# The feed can yield up to ~620 items (14 sources × up to 50 each), and the
# frontend sends every loaded item to /api/summary. Cap above that ceiling so
# a full feed never trips the limit; DeepSeek's context comfortably holds it.
SUMMARY_MAX_ITEMS = 650


# Networks the preview endpoints must never reach: RFC1918, loopback,
# link-local (incl. cloud metadata), CGNAT, and the IPv6 equivalents.
# NOTE: 198.18.0.0/15 (RFC 2544 benchmarking) is intentionally NOT blocked —
# some local proxies (e.g. Clash fake-ip) resolve public domains into that
# range, and blocking it would disable all previews in those environments.
# 198.18/15 is not a routable internal-services range, so leaving it open
# does not create an SSRF path.
_BLOCKED_NETWORKS = [
    ipaddress.ip_network(n) for n in (
        "0.0.0.0/8",        # "this" network
        "10.0.0.0/8",       # RFC1918
        "100.64.0.0/10",    # CGNAT
        "127.0.0.0/8",      # loopback
        "169.254.0.0/16",   # link-local (incl. cloud metadata)
        "172.16.0.0/12",    # RFC1918
        "192.168.0.0/16",   # RFC1918
        "224.0.0.0/4",      # multicast
        "240.0.0.0/4",      # reserved
        "::1/128",          # IPv6 loopback
        "fc00::/7",         # IPv6 unique-local
        "fe80::/10",        # IPv6 link-local
    )
]


def _is_blocked_ip(ip):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return any(addr in net for net in _BLOCKED_NETWORKS)


def is_safe_url(url):
    """Reject URLs whose host resolves to a private / loopback / link-local
    IP.  Guards the preview endpoints against SSRF (e.g. clients pointing
    the server at 169.254.169.254 or an internal service).  A DNS-rebinding
    race between resolution and connection is still theoretically possible;
    this stops the common case of a literal internal IP or hostname."""
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        if _is_blocked_ip(info[4][0]):
            return False
    return True


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Follow redirects but re-validate every hop with ``is_safe_url`` so a
    public URL can't 302 into an internal address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_safe_url(newurl):
            raise urllib.error.URLError("blocked redirect to unsafe url")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_SAFE_OPENER = urllib.request.build_opener(_SafeRedirectHandler)


def client_ip_from_headers(headers, fallback=""):
    """Originating client IP from the first ``X-Forwarded-For`` hop, falling
    back to the socket peer address."""
    xff = headers.get("X-Forwarded-For", "") if headers else ""
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return fallback


def debug_enabled():
    """/api/debug is local-only by default; opt in on Vercel production via
    ``ENABLE_DEBUG=1``."""
    if os.environ.get("ENABLE_DEBUG"):
        return True
    return os.environ.get("VERCEL_ENV") not in ("production",)


def read_json_file(path):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def claude_deepseek_config():
    def clean(value):
        return " ".join(value.split()) if isinstance(value, str) else ""

    paths = [
        Path.home() / ".claude" / "settings.local.json",
        Path.home() / ".claude" / "settings.json",
        Path.home() / ".claude.json",
    ]
    for path in paths:
        data = read_json_file(path)
        if not isinstance(data, dict):
            continue
        env = data.get("env")
        if not isinstance(env, dict):
            continue
        base_url = clean(env.get("ANTHROPIC_BASE_URL", ""))
        token = clean(env.get("ANTHROPIC_AUTH_TOKEN", ""))
        if not token or "deepseek" not in base_url.lower():
            continue
        model = (
            clean(env.get("ANTHROPIC_MODEL", ""))
            or clean(env.get("ANTHROPIC_DEFAULT_SONNET_MODEL", ""))
            or "deepseek-chat"
        )
        return {
            "base_url": base_url.rstrip("/"),
            "model": model,
            "token": token,
            "path": str(path),
        }
    base_url = clean(os.environ.get("ANTHROPIC_BASE_URL", ""))
    token = clean(os.environ.get("ANTHROPIC_AUTH_TOKEN", ""))
    if token and "deepseek" in base_url.lower():
        model = (
            clean(os.environ.get("ANTHROPIC_MODEL", ""))
            or clean(os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", ""))
            or "deepseek-chat"
        )
        return {
            "base_url": base_url.rstrip("/"),
            "model": model,
            "token": token,
            "path": "env",
        }
    return {}


CLAUDE_DEEPSEEK = claude_deepseek_config()
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
AI_MODEL = (
    os.environ.get("DEEPSEEK_MODEL")
    or (CLAUDE_DEEPSEEK.get("model") if not DEEPSEEK_KEY else "")
    or "deepseek-chat"
)
_deepseek_client = openai.OpenAI(
    api_key=DEEPSEEK_KEY, base_url=DEEPSEEK_BASE_URL
) if DEEPSEEK_KEY and openai else None


def _call_ai_api_stream(prompt):
    """Call the AI API with streaming. Yields text chunks for real-time parsing."""
    if DEEPSEEK_KEY:
        client = openai.OpenAI(api_key=DEEPSEEK_KEY, base_url=DEEPSEEK_BASE_URL)
        stream = client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": "你是一个专业新闻翻译助手，翻译简洁准确。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=4096,
            temperature=0.1,
            stream=True,
        )
        for chunk in stream:
            content = None
            if chunk.choices:
                delta = getattr(chunk.choices[0], "delta", None)
                if delta is not None:
                    content = getattr(delta, "content", "")
            if content:
                yield content
        return

    if CLAUDE_DEEPSEEK.get("token"):
        base = CLAUDE_DEEPSEEK["base_url"].rstrip("/")
        if base.endswith("/v1"):
            url = base + "/messages"
        else:
            url = base + "/v1/messages"
        headers = {
            "Authorization": f"Bearer {CLAUDE_DEEPSEEK['token']}",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        payload = {
            "model": AI_MODEL,
            "system": "你是一个专业新闻翻译助手，翻译简洁准确。",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4096,
            "temperature": 0.1,
            "stream": True,
        }
        data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", "replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    event_data = line[5:].strip()
                    if event_data == "[DONE]":
                        break
                    try:
                        event = json.loads(event_data)
                    except json.JSONDecodeError:
                        continue
                    # Anthropic format
                    if event.get("type") == "content_block_delta":
                        text = (event.get("delta") or {}).get("text", "")
                        if text:
                            yield text
                        continue
                    # OpenAI-compatible format (fallback)
                    choices = event.get("choices") or []
                    if choices:
                        delta = choices[0].get("delta") or {}
                        text = delta.get("content", "")
                        if text:
                            yield text
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            detail = " ".join(detail.split())[:500]
            raise RuntimeError(f"翻译请求失败 HTTP {exc.code}: {detail}") from exc
        return

    if _deepseek_client:
        stream = _deepseek_client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": "你是一个专业新闻翻译助手，翻译简洁准确。"},
                {"role": "user", "content": prompt},
            ],
            max_tokens=4096,
            temperature=0.1,
            stream=True,
        )
        for chunk in stream:
            content = None
            if chunk.choices:
                delta = getattr(chunk.choices[0], "delta", None)
                if delta is not None:
                    content = getattr(delta, "content", "")
            if content:
                yield content
        return

    raise RuntimeError("翻译 API 未配置：请设置 DEEPSEEK_API_KEY 或 Claude DeepSeek 配置")


def _build_summary_data(items):
    """Number every item and build the prompt + a source lookup map.

    Returns (prompt, sources) where *sources* is a dict mapping index
    strings to {url, label, short, accent}.
    """
    numbered_lines = []
    sources = {}
    idx = 0

    for item in items:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        source = item.get("source", "unknown")
        meta = SOURCES.get(source, {})
        label = meta.get("label", source)
        summary = (item.get("summary") or "").strip()

        line = f"[{idx}] 【{label}】{title}"
        if summary:
            line += f" — {summary[:100]}"
        numbered_lines.append(line)

        sources[str(idx)] = {
            "url": item.get("url") or item.get("discussionUrl") or "",
            "label": label,
            "short": meta.get("short", source),
            "accent": meta.get("accent", "#191b1f"),
        }
        idx += 1

    if not numbered_lines:
        return "", {}

    today_str = datetime.now(timezone.utc).strftime("%Y年%m月%d日")
    prompt = (
        f"你是一位《经济学人》（The Economist）周刊风格的资深编辑。"
        f"以下是{today_str}前后全球新闻标题汇总，每条新闻有唯一编号。\n\n"
        + "\n".join(numbered_lines)
        + "\n\n"
        f"请用中文撰写一份「本周世界」风格的要闻简报（700字以内），"
        f"严格按以下固定板块与顺序输出。\n\n"
        f"格式要求：\n"
        f"- 每个板块以 **板块名** 作为标题，独占一行\n"
        f"- 板块下每条要点以 \"- \" 开头分行列出，简明如电讯\n"
        f"- 每条要点末尾标注引用的新闻编号，如 [0]、[2][5]\n"
        f"- 没有相关新闻的板块直接跳过，不要输出空板块\n"
        f"- 「本周世界」两栏用简短一句话速览；「领袖」给出编辑视角的趋势判断；"
        f"其余板块为地区或主题要闻\n\n"
        f"板块顺序：\n"
        f"1. **本周世界｜政治** — 全球政治、冲突、外交、选举速览\n"
        f"2. **本周世界｜商业** — 全球商业、市场、央行、宏观经济速览\n"
        f"3. **领袖** — 本周最值得关注的趋势或判断（编辑视角，1–2 条）\n"
        f"4. **美国与美洲**\n"
        f"5. **欧洲**\n"
        f"6. **亚洲**\n"
        f"7. **中国** — 集中汇总所有与中国相关的新闻\n"
        f"8. **中东与非洲**\n"
        f"9. **商业与金融** — 企业动态、产业变迁、投融资、宏观与贸易\n"
        f"10. **科技** — AI、航天、生物医药、互联网\n"
        f"11. **文化与社会** — 文化、艺术、社会议题\n\n"
        f"输出示例：\n"
        f"**本周世界｜政治**\n"
        f"- 中东局势持续紧张，多国呼吁停火 [3][7]\n"
        f"- 欧盟通过新数据保护法案 [12]\n\n"
        f"**本周世界｜商业**\n"
        f"- 美联储维持利率不变，通胀压力仍在 [0]\n\n"
        f"**领袖**\n"
        f"- 全球供应链正从效率优先转向安全优先，重塑产业格局 [5][9]\n\n"
        f"【重要】严格遵循上述格式与板块顺序。每个要点必须带编号引用。"
        f"语言克制、简洁、有判断力，像《经济学人》的电讯与简报。"
    )
    return prompt, sources


def summary_events(items):
    """Stream AI-generated daily news summary for the given items.

    The ``done`` event carries both ``text`` and ``sources`` (a dict
    mapping citation index strings to article metadata).
    """
    if not items:
        yield {"type": "error", "message": "没有可总结的内容"}
        return

    prompt, sources = _build_summary_data(items)
    if not prompt:
        yield {"type": "error", "message": "没有可总结的内容"}
        return

    yield {"type": "start"}

    try:
        buffer = ""
        for chunk in _call_ai_api_stream(prompt):
            buffer += chunk
            yield {"type": "chunk", "text": chunk}

        yield {"type": "done", "text": buffer, "sources": sources}
    except Exception as exc:
        yield {"type": "error", "message": str(exc)}

    yield {"type": "complete"}


def iso_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def text(value):
    if isinstance(value, str):
        return " ".join(value.split())
    return ""


def clean_html(value):
    return text(html.unescape(TAG_RE.sub(" ", value or "")))


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
PREVIEW_CACHE_TTL = 600
IMAGE_CACHE_TTL = 3600
PREVIEW_CACHE = TTLLRU(PREVIEW_CACHE_TTL, 500)
IMAGE_CACHE = TTLLRU(IMAGE_CACHE_TTL, 500)


def extract_snippet(html_text):
    m = META_DESC_RE.search(html_text)
    if m:
        desc = m.group(1) or m.group(2)
        if desc:
            return clean_html(desc)[:500]

    parts = []
    for p_html in P_TAG_RE.findall(html_text):
        cleaned = clean_html(p_html)
        if len(cleaned) > 30:
            parts.append(cleaned)
        if len(" ".join(parts)) > 500:
            break
    if parts:
        return " ".join(parts)[:500]

    m = TITLE_RE.search(html_text)
    if m:
        title = clean_html(m.group(1))
        if len(title) > 10:
            return title[:500]

    return ""


def extract_og_image(html_text):
    m = OG_IMAGE_RE.search(html_text)
    if m:
        url = m.group(1) or m.group(2)
        if url:
            url = html.unescape(url).strip()
            if url.startswith("http"):
                return url
    return ""


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


def fetch_url(url, accept, extra_headers=None):
    headers = dict(REQUEST_HEADERS)
    if extra_headers:
        headers.update(extra_headers)
    headers["Accept"] = accept
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=18) as response:
        return response.read()


def fetch_preview_url(url):
    parsed = urllib.parse.urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
        "Referer": origin + "/",
        "DNT": "1",
        "Upgrade-Insecure-Requests": "1",
    }
    request = urllib.request.Request(url, headers=headers)
    with _SAFE_OPENER.open(request, timeout=12) as response:
        raw = response.read()
        content_type = response.headers.get("Content-Type", "")
        charset = "utf-8"
        if "charset=" in content_type:
            charset = content_type.split("charset=")[-1].split(";")[0].strip()
        return raw.decode(charset, errors="replace")


def fetch_preview_image(url):
    """Fetch og:image from the given URL.  Returns "" on failure.  Cached."""
    parsed = urllib.parse.urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8",
        "Referer": origin + "/",
        "DNT": "1",
    }
    request = urllib.request.Request(url, headers=headers)
    with _SAFE_OPENER.open(request, timeout=10) as response:
        raw = response.read()
        content_type = response.headers.get("Content-Type", "")
        charset = "utf-8"
        if "charset=" in content_type:
            charset = content_type.split("charset=")[-1].split(";")[0].strip()
        image = extract_og_image(raw.decode(charset, errors="replace"))
        return upscale_image_url(image)


def upscale_image_url(url):
    """Rewrite known low-res image URLs to request larger / higher-quality versions."""
    # Guardian: already handled — rss_image() picks the largest width variant
    # BBC: ichef.bbci.co.uk — replace {N} width in path with 976
    if "ichef.bbci.co.uk" in url or "ichef.bbc.co.uk" in url:
        url = re.sub(r"/news/\d+/", "/news/976/", url)
        url = re.sub(r"/standard/\d+/", "/standard/976/", url)
        return url
    # Google CDN cached images (e.g. from Google News) — bump width param
    if "googleusercontent.com" in url:
        url = re.sub(r"w\d+", "w800", url)
        return url
    return url


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


def rss_image(item):
    # Collect all media:content URLs — pick the largest by width if multiple exist
    candidates = []
    for media in item.findall("media:content", NS):
        url = media.attrib.get("url")
        if url:
            # Extract width from URL query param or path for sorting
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
        # Skip Google News section/index artifacts (e.g. WSJ "Print Edition").
        if title.strip().lower().startswith("print edition"):
            continue
        if publisher:
            for separator in (" - ", " | "):
                suffix = f"{separator}{publisher}"
                if title.endswith(suffix):
                    title = title[: -len(suffix)]
                    break
        summary = publisher
        items.append(
            make_item(
                source_key,
                meta,
                title=title,
                url=link,
                summary=summary,
                image=rss_image(item),
                published_at=child_text(item, "pubDate"),
                item_id=child_text(item, "guid") or link,
            )
        )
    return items, latest


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


def is_localized_reuters_url(url):
    parsed = urllib.parse.urlparse(url)
    return parsed.path.startswith(LOCALIZED_REUTERS_PREFIXES)


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


def parse_reuters_sitemap(source_key, meta, raw):
    root = ET.fromstring(raw)
    items = []
    latest = ""
    for url_node in root.findall("sm:url", NS):
        loc = child_text(url_node, "sm:loc", NS)
        if not loc or is_localized_reuters_url(loc):
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


def fetch_feed_collection(source_key, parser):
    meta = SOURCES[source_key]
    feeds = meta["feeds"]
    extra_headers = meta.get("headers")
    latest_values = []
    errors = []
    feed_results = []

    with ThreadPoolExecutor(max_workers=min(8, len(feeds))) as pool:
        jobs = {
            pool.submit(fetch_url, url, "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9", extra_headers): (idx, url)
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


def fetch_hn(source_key):
    meta = SOURCES[source_key]
    target = meta.get("story_limit", 20)
    ids = json.loads(
        fetch_url(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            "application/json",
        ).decode("utf-8")
    )

    # Build rank lookup: 1-indexed position on the HN front page
    id_rank = {str(item_id): idx + 1 for idx, item_id in enumerate(ids)}

    def fetch_item(item_id):
        raw = fetch_url(
            f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json",
            "application/json",
        )
        item = json.loads(raw.decode("utf-8"))
        if item.get("type") != "story" or item.get("dead") or item.get("deleted"):
            return None
        discussion_url = f"https://news.ycombinator.com/item?id={item_id}"
        return make_item(
            source_key,
            meta,
            title=item.get("title", ""),
            url=item.get("url") or discussion_url,
            summary=item.get("by", ""),
            published_at=datetime.fromtimestamp(item.get("time", 0), timezone.utc).isoformat(),
            item_id=str(item_id),
            score=item.get("score"),
            comments=item.get("descendants"),
            discussion_url=discussion_url,
            rank=id_rank.get(str(item_id)),
        )

    items = []
    batch_size = max(25, target + 25)
    for start in range(0, len(ids), batch_size):
        if len(items) >= target:
            break
        batch = ids[start:start + batch_size]
        with ThreadPoolExecutor(max_workers=16) as pool:
            jobs = [pool.submit(fetch_item, item_id) for item_id in batch]
            for job in as_completed(jobs):
                item = job.result()
                if item:
                    items.append(item)
        if len(items) >= target:
            break
    items.sort(key=lambda item: id_rank.get(item["id"].split(":")[-1], 999999))
    return source_payload(source_key, items, iso_now())


def zhihu_item_url(api_url):
    m = re.search(r'/questions/(\d+)', api_url or "")
    if m:
        return f"https://www.zhihu.com/question/{m.group(1)}"
    return api_url or ""


def fetch_zhihu(source_key):
    meta = SOURCES[source_key]
    raw = fetch_url("https://api.zhihu.com/topstory/hot-list?limit=50", "application/json")
    data = json.loads(raw.decode("utf-8"))
    items = []

    for entry in (data.get("data") or []):
        target = entry.get("target") or {}
        title = text(target.get("title") or target.get("title_area", {}).get("text", ""))
        api_url = text(target.get("url", ""))
        url = zhihu_item_url(api_url)
        if not title or not url:
            continue

        thumb = ""
        children = entry.get("children") or []
        if children:
            thumb = text(children[0].get("thumbnail", ""))

        items.append(make_item(
            source_key, meta,
            title=title,
            url=url,
            summary=text(target.get("excerpt", "")),
            image=thumb,
            published_at="",
            item_id=str(target.get("id", "")),
            score=int(re.sub(r"[^\d]", "", entry.get("detail_text", "0")) or 0) or None,
        ))

    target = meta.get("story_limit", 20)
    return source_payload(source_key, items[:target], iso_now())


def fetch_source(source_key):
    now = time.time()
    cached = _cache.get(source_key)
    if cached and now - cached["time"] < CACHE_SECONDS:
        return cached["payload"]

    kind = SOURCES[source_key]["kind"]
    if kind == "zhihu":
        payload = fetch_zhihu(source_key)
    elif kind == "hn":
        payload = fetch_hn(source_key)
    elif kind == "rss":
        payload = fetch_feed_collection(source_key, parse_rss)
    elif kind == "google_rss":
        payload = fetch_feed_collection(source_key, parse_google_rss)
    elif kind == "atom":
        payload = fetch_feed_collection(source_key, parse_atom)
    elif kind == "discourse":
        payload = fetch_feed_collection(source_key, parse_discourse)
    elif kind == "reuters_sitemap":
        payload = fetch_feed_collection(source_key, parse_reuters_sitemap)
    else:
        raise RuntimeError(f"Unknown source kind: {kind}")

    _cache[source_key] = {"time": now, "payload": payload}
    return payload


def stream_feed(query):
    requested = query.get("source", ["all"])[0]
    keys = list(SOURCES.keys()) if requested == "all" else [requested]
    keys = [key for key in keys if key in SOURCES]

    errors = []
    source_order = {key: index for index, key in enumerate(SOURCES.keys())}

    with ThreadPoolExecutor(max_workers=min(5, len(keys) or 1)) as pool:
        jobs = {pool.submit(fetch_source, key): key for key in keys}
        for job in as_completed(jobs):
            key = jobs[job]
            try:
                payload = job.result()
                yield json.dumps({
                    "type": "source",
                    "key": payload["key"],
                    "label": payload["label"],
                    "short": payload["short"],
                    "accent": payload["accent"],
                    "count": len(payload["items"]),
                    "items": payload["items"],
                }, ensure_ascii=False)
            except (
                urllib.error.URLError,
                urllib.error.HTTPError,
                TimeoutError,
                ET.ParseError,
                json.JSONDecodeError,
                RuntimeError,
            ) as exc:
                errors.append({"source": key, "message": str(exc)})

    yield json.dumps({
        "type": "done",
        "updatedAt": iso_now(),
        "errors": errors,
    }, ensure_ascii=False)


def api_headers(*, stream=False):
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "no-cache, no-transform" if stream else "no-store",
    }
    if stream:
        headers["X-Accel-Buffering"] = "no"
    return headers


def cors_preflight_response():
    return Response(
        status=204,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
    )


def json_response(data, status=200):
    return Response(
        json.dumps(data, ensure_ascii=False),
        status=status,
        content_type="application/json; charset=utf-8",
        headers=api_headers(),
    )


def parse_flask_query():
    return {key: request.args.getlist(key) for key in request.args.keys()}


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
        # Don't cache failures — a transient blip shouldn't pin a
        # "preview unavailable" message for the full TTL.
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
    # Cache the (possibly empty) result so repeated lookups are free.
    IMAGE_CACHE.set(url, image, now)
    return {"image": image}, 200


def create_flask_app():
    if Flask is None:
        raise RuntimeError("Flask is required for the Vercel WSGI application")

    flask_app = Flask(__name__, static_folder=None)

    @flask_app.before_request
    def handle_api_preflight():
        if request.method == "OPTIONS" and request.path.startswith("/api/"):
            return cors_preflight_response()
        return None

    @flask_app.get("/api/debug")
    def flask_debug():
        if not debug_enabled():
            abort(404)
        return json_response({
            "has_deepseek_key": bool(DEEPSEEK_KEY),
            "has_claude_token": bool(CLAUDE_DEEPSEEK.get("token")),
            "claude_base_url": CLAUDE_DEEPSEEK.get("base_url", ""),
            "deepseek_base_url": DEEPSEEK_BASE_URL,
            "model": AI_MODEL,
            "has_openai": openai is not None,
            "_deepseek_client": bool(_deepseek_client),
        })

    @flask_app.after_request
    def add_cors_headers(response):
        response.headers.setdefault("Access-Control-Allow-Origin", "*")
        return response

    @flask_app.route("/api/<path:_path>", methods=["OPTIONS"])
    def api_options(_path):
        return cors_preflight_response()

    @flask_app.route("/api/feed", methods=["GET", "HEAD"])
    def flask_feed():
        headers = api_headers(stream=True)
        if request.method == "HEAD":
            return Response(
                status=200,
                content_type="application/x-ndjson; charset=utf-8",
                headers=headers,
            )

        def generate():
            yield from (line + "\n" for line in stream_feed(parse_flask_query()))

        return Response(
            stream_with_context(generate()),
            content_type="application/x-ndjson; charset=utf-8",
            headers=headers,
        )

    @flask_app.get("/api/preview")
    def flask_preview():
        payload, status = preview_payload(request.args.get("url", ""))
        return json_response(payload, status=status)

    @flask_app.get("/api/preview-image")
    def flask_preview_image():
        payload, status = preview_image_payload(request.args.get("url", ""))
        return json_response(payload, status=status)

    @flask_app.post("/api/summary")
    def flask_summary():
        if (request.content_length or 0) > 2_000_000:
            return json_response({"error": "request too large"}, status=413)

        ip = client_ip_from_headers(request.headers, request.remote_addr or "")
        if not SUMMARY_LIMITER.allow(ip):
            return json_response({"error": "请求过于频繁，请稍后再试"}, status=429)

        payload = request.get_json(silent=True) or {}
        items = payload.get("items", [])
        if not isinstance(items, list):
            return json_response({"error": "Invalid items"}, status=400)
        if len(items) > SUMMARY_MAX_ITEMS:
            return json_response({"error": "items 过多"}, status=400)

        def generate():
            clean_items = [item for item in items if isinstance(item, dict)]
            for event in summary_events(clean_items):
                yield json.dumps(event, ensure_ascii=False) + "\n"

        return Response(
            stream_with_context(generate()),
            content_type="application/x-ndjson; charset=utf-8",
            headers=api_headers(stream=True),
        )

    @flask_app.get("/")
    def flask_index():
        return serve_public_file("index.html")

    @flask_app.get("/<path:filename>")
    def flask_static(filename):
        return serve_public_file(filename)

    return flask_app


def serve_public_file(filename):
    safe_path = urllib.parse.unquote(filename).lstrip("/") or "index.html"
    target = (PUBLIC_DIR / safe_path).resolve()
    if PUBLIC_DIR not in target.parents and target != PUBLIC_DIR:
        abort(404)
    if target.is_dir():
        safe_path = str(Path(safe_path) / "index.html")
        target = (PUBLIC_DIR / safe_path).resolve()
    if not target.exists():
        abort(404)

    response = send_from_directory(PUBLIC_DIR, safe_path)
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


app = create_flask_app() if Flask is not None else None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/feed":
            query = urllib.parse.parse_qs(parsed.query)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-transform")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            for line in stream_feed(query):
                self.wfile.write(line.encode("utf-8") + b"\n")
                self.wfile.flush()
            return

        if parsed.path == "/api/preview":
            self.handle_preview(parsed)
            return

        if parsed.path == "/api/preview-image":
            self.handle_preview_image(parsed)
            return

        self.serve_static(parsed.path)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/summary":
            self.handle_summary()
            return
        self.send_error(404)

    def handle_preview(self, parsed):
        query = urllib.parse.parse_qs(parsed.query)
        url = query.get("url", [""])[0]
        payload, status = preview_payload(url)
        if status == 200:
            self.send_json_ok(payload)
        else:
            self.send_json_error(payload.get("error", "error"), status)

    def handle_preview_image(self, parsed):
        query = urllib.parse.parse_qs(parsed.query)
        url = query.get("url", [""])[0]
        payload, status = preview_image_payload(url)
        if status == 200:
            self.send_json_ok(payload)
        else:
            self.send_json_error(payload.get("error", "error"), status)

    def send_json_ok(self, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json_error(self, message, code):
        body = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_summary(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > 2_000_000:
            self.send_error(413)
            return

        ip = client_ip_from_headers(
            self.headers, self.client_address[0] if self.client_address else ""
        )
        if not SUMMARY_LIMITER.allow(ip):
            self.send_json_error("请求过于频繁，请稍后再试", 429)
            return

        try:
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_error(400, "Invalid JSON")
            return

        items = payload.get("items", [])
        if not isinstance(items, list):
            self.send_error(400, "Invalid items")
            return
        if len(items) > SUMMARY_MAX_ITEMS:
            self.send_json_error("items 过多", 400)
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        for event in summary_events([item for item in items if isinstance(item, dict)]):
            line = json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n"
            self.wfile.write(line)
            self.wfile.flush()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_HEAD(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/feed":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            return
        self.serve_static(parsed.path, head_only=True)

    def serve_static(self, request_path, head_only=False):
        safe_path = urllib.parse.unquote(request_path).lstrip("/") or "index.html"
        target = (PUBLIC_DIR / safe_path).resolve()
        if PUBLIC_DIR not in target.parents and target != PUBLIC_DIR:
            self.send_error(404)
            return
        if target.is_dir():
            target = target / "index.html"
        if not target.exists():
            self.send_error(404)
            return

        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head_only:
            self.wfile.write(body)

    def log_message(self, fmt, *args):
        print("%s - %s" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"News Focus running at http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
