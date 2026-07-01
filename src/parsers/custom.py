"""Custom (non-feed) source fetchers: HN, Zhihu, Hupu."""

import json
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from src.config import (
    SOURCES, USER_AGENT,
    _CURL_CFFI_AVAILABLE,
)
from src.fetch import fetch_url, _curl_fetch
from src.parsers import (
    iso_now, text, make_item, source_payload,
)
from src.security import _SAFE_OPENER


# =========================================================================
# HN
# =========================================================================

def fetch_hn(source_key):
    meta = SOURCES[source_key]
    target = meta.get("story_limit", 20)
    ids = json.loads(
        fetch_url(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            "application/json",
        ).decode("utf-8")
    )

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


# =========================================================================
# Zhihu
# =========================================================================

def zhihu_item_url(api_url):
    m = re.search(r'/questions/(\d+)', api_url or "")
    if m:
        return f"https://www.zhihu.com/question/{m.group(1)}"
    return api_url or ""


def zhihu_score(detail_text):
    """Parse a Zhihu ``detail_text`` like "5234 万热度" or "12345 热度"
    into an int heat value, preserving the 万 multiplier so the UI can
    format consistently. Returns None when no number is found."""
    if not detail_text:
        return None
    text_val = str(detail_text)
    m = re.search(r"([\d,]+)\s*(万)?", text_val)
    if not m:
        return None
    num = int(m.group(1).replace(",", "")) if m.group(1) else 0
    if m.group(2):
        num *= 10000
    return num or None


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
            score=zhihu_score(entry.get("detail_text", "")),
        ))

    target = meta.get("story_limit", 20)
    return source_payload(source_key, items[:target], iso_now())


# =========================================================================
# Hupu (sub-forum scraping)
# =========================================================================

_HUPU_TITLE_RE = re.compile(
    r'<span class="t-title">(.+?)</span>.*?'
    r'<span class="t-lights">(\d+)亮</span>.*?'
    r'<span class="t-replies">(\d+)回复</span>',
)
_HUPU_POST_RE = re.compile(
    r'<div class="post-title"><a href="(/\d+\.html)"[^>]*class="p-title"[^>]*>([^<]+)</a></div>\s*'
    r'<div class="post-datum">(\d+)\s*/\s*\d+</div>',
)
_HUPU_LINK_RE = re.compile(r'<a href="(/\d+\.html)"')


def _fetch_hupu_html(url):
    """Fetch a Hupu page, returning decoded HTML or raising on failure."""
    raw = None
    if _CURL_CFFI_AVAILABLE:
        try:
            raw = _curl_fetch(url, {
                "User-Agent": USER_AGENT,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            })
        except (urllib.error.URLError, TimeoutError):
            pass
    if raw is None:
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        with _SAFE_OPENER.open(req, timeout=18) as resp:
            raw = resp.read()
    return raw.decode("utf-8", errors="replace")


def fetch_hupu_sub(source_key):
    meta = SOURCES[source_key]
    html_text = _fetch_hupu_html(meta["home"])

    items = []
    seen_urls = set()

    t_matches = len(_HUPU_TITLE_RE.findall(html_text))
    p_matches = len(_HUPU_POST_RE.findall(html_text))
    use_post_format = p_matches > t_matches
    if use_post_format:
        for m in _HUPU_POST_RE.finditer(html_text):
            post_url = "https://bbs.hupu.com" + m.group(1)
            title = m.group(2).strip()
            replies = m.group(3)
            if not title or post_url in seen_urls:
                continue
            seen_urls.add(post_url)
            item_id = m.group(1).lstrip("/").replace(".html", "")
            items.append(make_item(
                source_key, meta,
                title=title,
                url=post_url,
                summary=f"{replies}回复",
                published_at="",
                item_id=item_id,
                comments=int(replies) if replies.isdigit() else 0,
            ))
    else:
        for m in _HUPU_TITLE_RE.finditer(html_text):
            title = m.group(1).strip()
            lights = m.group(2)
            replies = m.group(3)
            if not title:
                continue
            start = max(0, m.start() - 200)
            fragment = html_text[start:m.end() + 200]
            link_m = _HUPU_LINK_RE.search(fragment)
            if not link_m:
                continue
            post_url = "https://bbs.hupu.com" + link_m.group(1)
            if post_url in seen_urls:
                continue
            seen_urls.add(post_url)
            item_id = link_m.group(1).lstrip("/").replace(".html", "")
            items.append(make_item(
                source_key, meta,
                title=title,
                url=post_url,
                summary=f"{lights}亮 · {replies}回复",
                published_at="",
                item_id=item_id,
                score=int(lights) if lights.isdigit() else 0,
                comments=int(replies) if replies.isdigit() else 0,
            ))

    target = meta.get("story_limit", 20)
    return source_payload(source_key, items[:target], iso_now())
