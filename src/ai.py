"""AI translation and summary generation via DeepSeek."""

import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from src.cache import RateLimiter, TTLLRU
from src.config import SOURCES, NON_TRANSLATABLE_SOURCES, SUMMARY_TRANSLATABLE_SOURCES

# ── DeepSeek configuration ─────────────────────────────────────────────

try:
    import openai
except ImportError:
    openai = None


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


def ai_translation_available():
    """True when at least one DeepSeek backend is configured."""
    return _deepseek_client is not None or bool(CLAUDE_DEEPSEEK.get("token"))


def should_translate_source(source_key):
    return ai_translation_available() and source_key not in NON_TRANSLATABLE_SOURCES


def should_translate_summary(source_key):
    return source_key in SUMMARY_TRANSLATABLE_SOURCES


# ── Rate limiters ──────────────────────────────────────────────────────

SUMMARY_LIMITER = RateLimiter(max_calls=5, period=60)
SUMMARY_MAX_ITEMS = 650
TRANSLATE_LIMITER = RateLimiter(max_calls=30, period=60)
TRANSLATE_MAX_ITEMS = 100

# ── Translation ────────────────────────────────────────────────────────

TRANSLATION_CACHE_TTL = 24 * 3600
TRANSLATION_CACHE = TTLLRU(TRANSLATION_CACHE_TTL, 5000)

TRANSLATION_SYSTEM_PROMPT = "你是一个专业新闻翻译助手，翻译简洁准确。"
SUMMARY_SYSTEM_PROMPT = "你是一位资深新闻编辑，擅长撰写简洁有力的要闻简报。"


def _call_ai_api_stream(prompt, *, system_prompt=TRANSLATION_SYSTEM_PROMPT, max_tokens=4096):
    """Call the AI API with streaming. Yields text chunks for real-time parsing."""
    if _deepseek_client:
        for chunk in _call_deepseek_sdk(prompt, system_prompt, max_tokens):
            yield chunk
        return

    if CLAUDE_DEEPSEEK.get("token"):
        for chunk in _call_deepseek_http(prompt, system_prompt, max_tokens):
            yield chunk
        return

    raise RuntimeError("翻译 API 未配置：请设置 DEEPSEEK_API_KEY 或 Claude DeepSeek 配置")


def _call_deepseek_sdk(prompt, system_prompt, max_tokens):
    """Stream via the OpenAI-compatible SDK."""
    stream = _deepseek_client.chat.completions.create(
        model=AI_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        max_tokens=max_tokens,
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


def _call_deepseek_http(prompt, system_prompt, max_tokens):
    """Stream via Anthropic-format HTTP (Claude Code relay)."""
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
        "system": system_prompt,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "stream": True,
    }
    data_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
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


# ── Translation helpers ────────────────────────────────────────────────

def _parse_translation_json(text):
    """Extract a dict of {index: translated_text} from the AI response."""
    if not text:
        return {}
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    return {}


def _build_translation_prompt(jobs):
    """Build the batch translation prompt for a list of (item, field, original)."""
    numbered = [f"[{i}] {original}" for i, (_, _, original) in enumerate(jobs)]
    return (
        "将以下英文新闻标题和摘要翻译为简体中文，保持简洁准确的新闻风格。"
        "人名、机构名、专有名词保留原文或使用常见中文译名。\n"
        "输出 JSON 对象，key 为编号字符串，value 为译文。\n"
        "不要输出任何多余内容，只输出 JSON。\n\n"
        + "\n".join(numbered)
        + '\n\n输出格式：{"0":"译文","1":"译文",...}'
    )


def _translate_batch(jobs, max_tokens=8192):
    """Translate a list of (item, field, original) jobs in a single AI call."""
    if not jobs:
        return {}
    prompt = _build_translation_prompt(jobs)
    try:
        full_text = "".join(
            _call_ai_api_stream(
                prompt,
                system_prompt=TRANSLATION_SYSTEM_PROMPT,
                max_tokens=max_tokens,
            )
        )
        result = _parse_translation_json(full_text)
        if isinstance(result, dict) and result:
            return result
    except Exception as exc:
        print(f"[translate] AI call failed ({len(jobs)} items): {exc}",
              file=sys.stderr)
    return {}


def _apply_translations(jobs, translations, source_key, event_q=None):
    """Apply a ``{str(index): text}`` dict to *jobs* in place."""
    for i, (item, field, original) in enumerate(jobs):
        translated = translations.get(str(i), "")
        if not isinstance(translated, str):
            translated = str(translated)
        translated = translated.strip()
        if translated and translated != original:
            item[f"{field}Original"] = item[field]
            item[field] = translated
            if event_q is not None:
                event_q.put(("translate", source_key, item["id"], field, translated))


def _run_translation_jobs(jobs):
    """Resolve translations for a list of (item, field, original) jobs.

    Checks the translation cache first; on a miss performs a single batch
    AI call, and if that returns nothing (truncated JSON) retries in
    smaller chunks.  Returns ``{str(index): translated_text}`` or ``{}``
    on failure.  Caches successful results."""
    if not jobs:
        return {}

    cache_key = hashlib.sha256(
        "\x00".join(original for _, _, original in jobs).encode("utf-8")
    ).hexdigest()
    now = time.time()
    cached = TRANSLATION_CACHE.get(cache_key, now)
    if cached is not None:
        return cached

    translations = _translate_batch(jobs, max_tokens=8192)

    if not translations and len(jobs) > 10:
        batch_size = 10
        translations = {}
        for start in range(0, len(jobs), batch_size):
            batch = jobs[start:start + batch_size]
            batch_result = _translate_batch(batch, max_tokens=8192)
            for local_i, text in batch_result.items():
                try:
                    absolute_i = start + int(local_i)
                except (TypeError, ValueError):
                    continue
                if 0 <= absolute_i < len(jobs):
                    translations[str(absolute_i)] = text

    if translations:
        TRANSLATION_CACHE.set(cache_key, translations, now)
    return translations


def translate_items(items, source_key, event_q=None):
    """Translate titles (and summaries where meaningful) for non-Chinese
    sources using DeepSeek batch translation."""
    if not should_translate_source(source_key) or not items:
        return items

    do_summary = should_translate_summary(source_key)

    jobs = []
    for item in items:
        if not item.get("titleOriginal"):
            title = item.get("title") or ""
            if title:
                jobs.append((item, "title", title))
        if do_summary and not item.get("summaryOriginal"):
            summary = item.get("summary") or ""
            if summary:
                jobs.append((item, "summary", summary))

    if not jobs:
        return items

    translations = _run_translation_jobs(jobs)
    if translations:
        _apply_translations(jobs, translations, source_key, event_q)
    return items


def translate_events(items_data, source_key):
    """Stream translation events for a batch of items requested by the client."""
    if not should_translate_source(source_key) or not items_data:
        yield json.dumps({"type": "done"}, ensure_ascii=False)
        return

    do_summary = should_translate_summary(source_key)

    jobs = []
    for item_data in items_data:
        item_id = item_data.get("id", "")
        title = (item_data.get("title") or "").strip()
        if title:
            jobs.append(({"id": item_id}, "title", title))
        if do_summary:
            summary = (item_data.get("summary") or "").strip()
            if summary:
                jobs.append(({"id": item_id}, "summary", summary))

    if not jobs:
        yield json.dumps({"type": "done"}, ensure_ascii=False)
        return

    translations = _run_translation_jobs(jobs)

    for i, (item, field, original) in enumerate(jobs):
        translated = translations.get(str(i), "")
        if not isinstance(translated, str):
            translated = str(translated)
        translated = translated.strip()
        if translated and translated != original:
            yield json.dumps({
                "type": "translate",
                "itemId": item["id"],
                "field": field,
                "translated": translated,
            }, ensure_ascii=False)

    yield json.dumps({"type": "done"}, ensure_ascii=False)


# ── Summary generation ─────────────────────────────────────────────────

def _build_summary_data(items):
    """Number every item and build the prompt + a source lookup map."""
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
    """Stream AI-generated daily news summary for the given items."""
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
        for chunk in _call_ai_api_stream(
            prompt,
            system_prompt=SUMMARY_SYSTEM_PROMPT,
            max_tokens=4096,
        ):
            buffer += chunk
            yield {"type": "chunk", "text": chunk}

        yield {"type": "done", "text": buffer, "sources": sources}
    except Exception as exc:
        yield {"type": "error", "message": str(exc)}

    yield {"type": "complete"}
