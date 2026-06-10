#!/usr/bin/env python3
import html
import json
import mimetypes
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
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
        "story_limit": 50,
    },
        "zhihu": {
        "label": "知乎热榜",
        "short": "Zhihu",
        "kind": "zhihu",
        "home": "https://www.zhihu.com/hot",
        "accent": "#0066ff",
        "story_limit": 50,
        "translate": False,
    },
    "economist": {
        "label": "经济学人",
        "short": "Economist",
        "kind": "rss",
        "home": "https://www.economist.com/latest",
        "accent": "#d71920",
        "story_limit": 50,
        "feeds": ["https://www.economist.com/latest/rss.xml"],
    },
    "reuters": {
        "label": "路透社",
        "short": "Reuters",
        "kind": "reuters_sitemap",
        "home": "https://www.reuters.com/",
        "accent": "#ff8000",
        "story_limit": 50,
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
        "story_limit": 50,
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
    "google": {
        "label": "Google News 美国",
        "short": "Google",
        "kind": "google_rss",
        "home": "https://news.google.com/topstories?hl=en-US&gl=US&ceid=US:en",
        "accent": "#1a73e8",
        "story_limit": 50,
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
        "label": "Google News 中文",
        "short": "Google 中文",
        "kind": "google_rss",
        "home": "https://news.google.com/topstories?hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "accent": "#34a853",
        "story_limit": 50,
        "translate": False,
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
        "feeds": ["https://www.theatlantic.com/feed/all/"],
    },
    "newyorker": {
        "label": "纽约客",
        "short": "NewYorker",
        "kind": "rss",
        "home": "https://www.newyorker.com/",
        "accent": "#e60000",
        "story_limit": 30,
        "feeds": ["https://www.newyorker.com/feed/everything"],
    },
    "aeon": {
        "label": "Aeon 深度",
        "short": "Aeon",
        "kind": "rss",
        "home": "https://aeon.co/",
        "accent": "#c45161",
        "story_limit": 20,
        "feeds": ["https://aeon.co/feed.rss"],
    },
    "mit_tech": {
        "label": "MIT 科技评论",
        "short": "MIT Tech",
        "kind": "rss",
        "home": "https://www.technologyreview.com/",
        "accent": "#ff5a00",
        "story_limit": 30,
        "feeds": ["https://www.technologyreview.com/feed/"],
    },
    "zhihu": {
        "label": "知乎热榜",
        "short": "知乎",
        "kind": "zhihu",
        "home": "https://www.zhihu.com/hot",
        "accent": "#0066ff",
        "story_limit": 30,
        "translate": False,
    },
    "washingtonpost": {
        "label": "华盛顿邮报",
        "short": "WaPo",
        "kind": "rss",
        "home": "https://www.washingtonpost.com/",
        "accent": "#1a1a1a",
        "story_limit": 50,
        "feeds": [
            "https://feeds.washingtonpost.com/rss/world",
            "https://feeds.washingtonpost.com/rss/national",
            "https://feeds.washingtonpost.com/rss/business",
            "https://feeds.washingtonpost.com/rss/politics",
            "https://feeds.washingtonpost.com/rss/technology",
        ],
    },
}

LOCALIZED_REUTERS_PREFIXES = ("/es/", "/de/", "/fr/", "/pt/", "/ja/", "/zh-hans/")
TAG_RE = re.compile(r"<[^>]+>")
_cache = {}


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
    return {}


CLAUDE_DEEPSEEK = claude_deepseek_config()
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
TRANSLATION_MODEL = (
    os.environ.get("DEEPSEEK_MODEL")
    or (CLAUDE_DEEPSEEK.get("model") if not DEEPSEEK_KEY else "")
    or "deepseek-chat"
)
_deepseek_client = openai.OpenAI(
    api_key=DEEPSEEK_KEY, base_url=DEEPSEEK_BASE_URL
) if DEEPSEEK_KEY and openai else None

_translation_cache: dict[str, str] = {}
DEFAULT_TRANSLATION_CACHE_FILE = (
    "/tmp/news-focus-translation-cache.json"
    if os.environ.get("VERCEL")
    else str(ROOT / ".translation_cache.json")
)
TRANSLATION_CACHE_FILE = Path(
    os.environ.get("TRANSLATION_CACHE_FILE", DEFAULT_TRANSLATION_CACHE_FILE)
)
MAX_CACHE_SIZE = 10000


def _load_translation_cache():
    global _translation_cache
    if TRANSLATION_CACHE_FILE.exists():
        try:
            _translation_cache = json.loads(TRANSLATION_CACHE_FILE.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            _translation_cache = {}


def _save_translation_cache():
    global _translation_cache
    if len(_translation_cache) > MAX_CACHE_SIZE:
        keys = list(_translation_cache.keys())[-MAX_CACHE_SIZE:]
        _translation_cache = {k: _translation_cache[k] for k in keys}
    try:
        TRANSLATION_CACHE_FILE.write_text(
            json.dumps(_translation_cache, ensure_ascii=False), "utf-8"
        )
    except OSError:
        pass


def _translate_chunk(chunk: list[str], start_idx: int) -> dict[int, str]:
    numbered = "\n\n".join(f"[{i + 1}] {t}" for i, t in enumerate(chunk))
    prompt = (
        "你是一个财经新闻翻译助手。请将以下编号的英文新闻标题或摘要翻译成简洁、地道的中文。"
        "保持原意，不要添加解释。每个翻译用 [编号] 中文译文的格式输出。\n\n" + numbered
    )
    resp = _deepseek_client.chat.completions.create(
        model=TRANSLATION_MODEL,
        messages=[
            {"role": "system", "content": "你是一个专业财经新闻翻译助手，翻译简洁准确。"},
            {"role": "user", "content": prompt},
        ],
        max_tokens=4096,
        temperature=0.1,
    )
    result = resp.choices[0].message.content or ""
    parsed: dict[int, str] = {}
    for line in result.strip().split("\n"):
        m = re.match(r"\[(\d+)\]\s*(.+)", line.strip())
        if m:
            parsed[int(m.group(1)) - 1] = m.group(2).strip()
    return parsed


def translate_batch(texts: list[str]) -> list[str]:
    if not _deepseek_client or not texts:
        return texts
    unique = list(dict.fromkeys(t for t in texts if t and t.strip()))
    uncached = [t for t in unique if t not in _translation_cache]
    if not uncached:
        return [_translation_cache.get(t, t) for t in texts]

    chunks = [uncached[i:i + 40] for i in range(0, len(uncached), 40)]
    for chunk_idx, chunk in enumerate(chunks):
        try:
            parsed = _translate_chunk(chunk, chunk_idx * 40)
        except Exception:
            continue
        for i, original in enumerate(chunk):
            translated = parsed.get(i, original)
            _translation_cache[original] = translated

    _save_translation_cache()
    return [_translation_cache.get(t, t) for t in texts]


def should_translate_source(source_key):
    return SOURCES.get(source_key, {}).get("translate", True)


def translatable_summary(source_key, summary):
    if source_key in {"hn", "google", "google_zh"}:
        return ""
    return summary


def translation_cache_key(title, summary):
    return "item-v1:" + title + "\n\n" + summary


def translation_prompt(title, summary):
    body = f"标题：{title}"
    if summary:
        body += f"\n摘要：{summary}"
    return (
        "请将下面的英文新闻翻译成简洁、地道的中文，保持原意，不要添加解释。"
        "只输出 JSON，不要 Markdown，不要代码块。JSON 格式必须是："
        '{"title":"中文标题","summary":"中文摘要"}。'
        "如果没有摘要，summary 输出空字符串。\n\n"
        + body
    )


def parse_translation_json(raw, fallback_title, fallback_summary):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    match = re.search(r"\{.*\}", raw, re.S)
    if match:
        try:
            parsed = json.loads(match.group(0))
            title = text(parsed.get("title")) or fallback_title
            summary = text(parsed.get("summary")) if fallback_summary else ""
            return {"title": title, "summary": summary}
        except (TypeError, json.JSONDecodeError):
            pass

    title_match = re.search(r"标题[:：]\s*(.+)", raw)
    summary_match = re.search(r"摘要[:：]\s*(.+)", raw)
    return {
        "title": text(title_match.group(1)) if title_match else text(raw) or fallback_title,
        "summary": text(summary_match.group(1)) if summary_match and fallback_summary else "",
    }


def request_json_stream(url, headers, payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", "replace").strip()
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue
                event_data = line[5:].strip()
                if event_data == "[DONE]":
                    break
                try:
                    yield json.loads(event_data)
                except json.JSONDecodeError:
                    continue
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        detail = " ".join(detail.split())[:500]
        raise RuntimeError(f"DeepSeek 翻译请求失败 HTTP {exc.code}: {detail}") from exc


def stream_openai_compatible_translation(title, summary):
    url = DEEPSEEK_BASE_URL.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": TRANSLATION_MODEL,
        "messages": [
            {"role": "system", "content": "你是一个专业新闻翻译助手，翻译简洁准确。"},
            {"role": "user", "content": translation_prompt(title, summary)},
        ],
        "max_tokens": 1200,
        "temperature": 0.1,
        "stream": True,
    }
    for event in request_json_stream(url, headers, payload):
        choices = event.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        content = delta.get("content", "")
        if content:
            yield content


def anthropic_messages_url(base_url):
    base_url = base_url.rstrip("/")
    if base_url.endswith("/v1"):
        return base_url + "/messages"
    return base_url + "/v1/messages"


def stream_anthropic_compatible_translation(title, summary):
    url = anthropic_messages_url(CLAUDE_DEEPSEEK["base_url"])
    headers = {
        "Authorization": f"Bearer {CLAUDE_DEEPSEEK['token']}",
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": TRANSLATION_MODEL,
        "system": "你是一个专业新闻翻译助手，翻译简洁准确。",
        "messages": [{"role": "user", "content": translation_prompt(title, summary)}],
        "max_tokens": 1200,
        "temperature": 0.1,
        "stream": True,
    }
    for event in request_json_stream(url, headers, payload):
        event_type = event.get("type")
        if event_type == "content_block_delta":
            delta = event.get("delta") or {}
            content = delta.get("text", "")
            if content:
                yield content
            continue

        choices = event.get("choices") or []
        if choices:
            delta = choices[0].get("delta") or {}
            content = delta.get("content", "")
            if content:
                yield content


def stream_deepseek_translation(title, summary):
    if DEEPSEEK_KEY:
        yield from stream_openai_compatible_translation(title, summary)
        return
    if CLAUDE_DEEPSEEK.get("token"):
        yield from stream_anthropic_compatible_translation(title, summary)
        return
    if _deepseek_client:
        stream = _deepseek_client.chat.completions.create(
            model=TRANSLATION_MODEL,
            messages=[
                {"role": "system", "content": "你是一个专业新闻翻译助手，翻译简洁准确。"},
                {"role": "user", "content": translation_prompt(title, summary)},
            ],
            max_tokens=1200,
            temperature=0.1,
            stream=True,
        )
        for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            content = getattr(delta, "content", "") if delta is not None else ""
            if content:
                yield content
        return
    raise RuntimeError("DeepSeek API 未配置：请设置 DEEPSEEK_API_KEY 或 Claude DeepSeek 配置")


def translation_events(items):
    for item in items[:50]:
        item_id = text(item.get("id"))
        source_key = text(item.get("source"))
        title = text(item.get("title"))
        summary = text(translatable_summary(source_key, item.get("summary", "")))
        if not item_id or not title or not should_translate_source(source_key):
            continue

        yield {"type": "start", "id": item_id}
        cache_key = translation_cache_key(title, summary)
        cached = _translation_cache.get(cache_key)
        if cached:
            try:
                yield {"type": "done", "id": item_id, **json.loads(cached)}
                continue
            except (TypeError, json.JSONDecodeError):
                pass

        raw = ""
        try:
            for delta in stream_deepseek_translation(title, summary):
                raw += delta
                yield {"type": "chunk", "id": item_id, "delta": delta}
            translated = parse_translation_json(raw, title, summary)
            _translation_cache[cache_key] = json.dumps(translated, ensure_ascii=False)
            _save_translation_cache()
            yield {"type": "done", "id": item_id, **translated}
        except Exception as exc:
            yield {"type": "error", "id": item_id, "message": str(exc)}


def translate_items(items: list[dict]) -> list[dict]:
    if not _deepseek_client or not items:
        return items
    texts: list[str] = []
    indices: list[int] = []
    for i, item in enumerate(items):
        if "titleEn" in item:
            continue
        if not SOURCES.get(item.get("source"), {}).get("translate", True):
            continue
        texts.append(item.get("title", ""))
        texts.append(item.get("summary", ""))
        indices.append(i)
    if not texts:
        return items
    translated = translate_batch(texts)
    for j, i in enumerate(indices):
        item = items[i]
        item["titleEn"] = item.get("title", "")
        item["summaryEn"] = item.get("summary", "")
        item["title"] = translated[j * 2] or item["title"]
        if item.get("source") != "hn":
            item["summary"] = translated[j * 2 + 1] or item.get("summary", "")
    return items


_load_translation_cache()


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
P_TAG_RE = re.compile(r"<p[^>]*>(.+?)</p>", re.DOTALL | re.IGNORECASE)
TITLE_RE = re.compile(r"<title[^>]*>(.+?)</title>", re.DOTALL | re.IGNORECASE)
BODY_TEXT_RE = re.compile(r"<body[^>]*>(.*?)</body>", re.DOTALL | re.IGNORECASE)
PREVIEW_CACHE: dict[str, tuple[float, str]] = {}
PREVIEW_CACHE_TTL = 600


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


def fetch_url(url, accept):
    headers = dict(REQUEST_HEADERS)
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
    with urllib.request.urlopen(request, timeout=12) as response:
        raw = response.read()
        content_type = response.headers.get("Content-Type", "")
        charset = "utf-8"
        if "charset=" in content_type:
            charset = content_type.split("charset=")[-1].split(";")[0].strip()
        return raw.decode(charset, errors="replace")


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
        "image": text(image),
        "publishedAt": normalize_date(published_at),
        "score": score,
        "comments": comments,
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
    limit = meta.get("story_limit", 50)
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
    media = item.find("media:content", NS)
    if media is None:
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
        if publisher:
            for separator in (" - ", " | "):
                suffix = f"{separator}{publisher}"
                if title.endswith(suffix):
                    title = title[: -len(suffix)]
                    break
        items.append(
            make_item(
                source_key,
                meta,
                title=title,
                url=link,
                summary=publisher,
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
        items.append(
            make_item(
                source_key,
                meta,
                title=title,
                url=link,
                summary=child_text(entry, "atom:summary", NS),
                image=media.attrib.get("url", "") if media is not None else "",
                published_at=child_text(entry, "atom:published", NS)
                or child_text(entry, "atom:updated", NS),
                item_id=child_text(entry, "atom:id", NS) or link,
            )
        )
    return items, latest


def is_localized_reuters_url(url):
    parsed = urllib.parse.urlparse(url)
    return parsed.path.startswith(LOCALIZED_REUTERS_PREFIXES)


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
    latest_values = []
    errors = []
    feed_results = []

    with ThreadPoolExecutor(max_workers=min(8, len(feeds))) as pool:
        jobs = {
            pool.submit(fetch_url, url, "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9"): (idx, url)
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
        items.extend(feed_items)
    latest = max((normalize_date(value) for value in latest_values), default="")
    return source_payload(source_key, items, latest)


def fetch_zhihu(source_key):
    meta = SOURCES[source_key]
    target = meta.get("story_limit", 50)
    raw = json.loads(
        fetch_url(
            f"https://api.zhihu.com/topstory/hot-lists/total?limit={target}",
            "application/json",
        ).decode("utf-8")
    )
    items = []
    for entry in raw.get("data", []):
        t = entry.get("target", {})
        if not t.get("title"):
            continue
        qid = str(t.get("id", ""))
        web_url = f"https://www.zhihu.com/question/{qid}" if qid else ""
        items.append(
            make_item(
                source_key,
                meta,
                title=t["title"],
                url=web_url,
                summary=t.get("excerpt", ""),
                published_at=datetime.fromtimestamp(t.get("created", 0), timezone.utc).isoformat(),
                item_id=qid,
                score=t.get("answer_count"),
                comments=t.get("follower_count"),
                discussion_url=web_url,
            )
        )
    return source_payload(source_key, items[:target], iso_now())


def fetch_hn(source_key):
    meta = SOURCES[source_key]
    target = meta.get("story_limit", 50)
    ids = json.loads(
        fetch_url(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            "application/json",
        ).decode("utf-8")
    )

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
    id_rank = {str(item_id): idx for idx, item_id in enumerate(ids)}
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

    target = meta.get("story_limit", 30)
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
    elif kind == "zhihu":
        payload = fetch_zhihu(source_key)
    elif kind == "rss":
        payload = fetch_feed_collection(source_key, parse_rss)
    elif kind == "google_rss":
        payload = fetch_feed_collection(source_key, parse_google_rss)
    elif kind == "atom":
        payload = fetch_feed_collection(source_key, parse_atom)
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

    now = time.time()
    cached = PREVIEW_CACHE.get(url)
    if cached and now - cached[0] < PREVIEW_CACHE_TTL:
        return {"snippet": cached[1]}, 200

    try:
        raw = fetch_preview_url(url)
        snippet = extract_snippet(raw)
    except Exception as exc:
        snippet = f"[预览不可用] {exc}"

    PREVIEW_CACHE[url] = (now, snippet)
    return {"snippet": snippet}, 200


def create_flask_app():
    if Flask is None:
        raise RuntimeError("Flask is required for the Vercel WSGI application")

    flask_app = Flask(__name__, static_folder=None)

    @flask_app.before_request
    def handle_api_preflight():
        if request.method == "OPTIONS" and request.path.startswith("/api/"):
            return cors_preflight_response()
        return None

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

    @flask_app.post("/api/translate")
    def flask_translate():
        if (request.content_length or 0) > 1_000_000:
            return json_response({"error": "request too large"}, status=413)

        payload = request.get_json(silent=True) or {}
        items = payload.get("items", [])
        if not isinstance(items, list):
            return json_response({"error": "Invalid items"}, status=400)

        def generate():
            clean_items = [item for item in items if isinstance(item, dict)]
            for event in translation_events(clean_items):
                yield json.dumps(event, ensure_ascii=False) + "\n"
            yield json.dumps({"type": "complete"}, ensure_ascii=False) + "\n"

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

        self.serve_static(parsed.path)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/translate":
            self.handle_translate()
            return
        self.send_error(404)

    def handle_preview(self, parsed):
        query = urllib.parse.parse_qs(parsed.query)
        url = query.get("url", [""])[0]
        if not url or not url.startswith(("http://", "https://")):
            self.send_json_error("invalid url", 400)
            return

        now = time.time()
        cached = PREVIEW_CACHE.get(url)
        if cached and now - cached[0] < PREVIEW_CACHE_TTL:
            self.send_json_ok({"snippet": cached[1]})
            return

        try:
            raw = fetch_preview_url(url)
            snippet = extract_snippet(raw)
            PREVIEW_CACHE[url] = (now, snippet)
            self.send_json_ok({"snippet": snippet})
        except Exception as exc:
            snippet = f"[预览不可用] {exc}"
            PREVIEW_CACHE[url] = (now, snippet)
            self.send_json_ok({"snippet": snippet})

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

    def handle_translate(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length > 1_000_000:
            self.send_error(413)
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

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        for event in translation_events([item for item in items if isinstance(item, dict)]):
            line = json.dumps(event, ensure_ascii=False).encode("utf-8") + b"\n"
            self.wfile.write(line)
            self.wfile.flush()
        self.wfile.write(json.dumps({"type": "complete"}).encode("utf-8") + b"\n")
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
