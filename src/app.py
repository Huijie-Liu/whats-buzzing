"""Flask application factory, routes, and feed streaming."""

import json
import urllib.error
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue

from flask import (
    Flask, Response, abort, request,
    send_from_directory, stream_with_context,
)

from src.cache import RateLimiter
from src.config import PUBLIC_DIR, HOST, PORT, SOURCES
from src.parsers import iso_now, fetch_source
from src.security import client_ip_from_headers, debug_enabled
from src.fetch import preview_payload, preview_image_payload
from src.ai import (
    CLAUDE_DEEPSEEK, DEEPSEEK_KEY, DEEPSEEK_BASE_URL, AI_MODEL, _deepseek_client,
    ai_translation_available,
    SUMMARY_LIMITER, SUMMARY_MAX_ITEMS,
    TRANSLATE_LIMITER, TRANSLATE_MAX_ITEMS,
    translate_events, summary_events,
)

PREVIEW_LIMITER = RateLimiter(max_calls=30, period=60)


# ── HTTP helpers ───────────────────────────────────────────────────────

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


# ── Feed streaming ─────────────────────────────────────────────────────

def stream_feed(query):
    requested = query.get("source", ["all"])[0]
    keys = list(SOURCES.keys()) if requested == "all" else [requested]
    keys = [key for key in keys if key in SOURCES]

    if not keys:
        yield json.dumps({"type": "done", "updatedAt": iso_now(), "errors": []}, ensure_ascii=False)
        return

    errors = []
    event_q = Queue()

    def process_source(key):
        try:
            payload = fetch_source(key)
            event_q.put(("source", payload))
        except (
            urllib.error.URLError, urllib.error.HTTPError,
            TimeoutError, ET.ParseError,
            json.JSONDecodeError, RuntimeError,
        ) as exc:
            event_q.put(("error", key, str(exc)))
        except Exception as exc:
            event_q.put(("error", key, f"unexpected: {exc}"))
        finally:
            event_q.put(("complete", key))

    with ThreadPoolExecutor(max_workers=min(5, len(keys))) as pool:
        for key in keys:
            pool.submit(process_source, key)

        completed = 0
        while True:
            event = event_q.get()
            kind = event[0]
            if kind == "source":
                payload = event[1]
                yield json.dumps({
                    "type": "source",
                    "key": payload["key"],
                    "label": payload["label"],
                    "short": payload["short"],
                    "accent": payload["accent"],
                    "count": len(payload["items"]),
                    "items": payload["items"],
                }, ensure_ascii=False)
            elif kind == "translate":
                _, source_key, item_id, field, translated = event
                yield json.dumps({
                    "type": "translate",
                    "source": source_key,
                    "itemId": item_id,
                    "field": field,
                    "translated": translated,
                }, ensure_ascii=False)
            elif kind == "error":
                errors.append({"source": event[1], "message": event[2]})
            elif kind == "complete":
                completed += 1
                if completed >= len(keys):
                    break

    yield json.dumps({
        "type": "done",
        "updatedAt": iso_now(),
        "errors": errors,
    }, ensure_ascii=False)


# ── Flask app factory ──────────────────────────────────────────────────

def create_flask_app():
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
            "has_openai": True,
            "_deepseek_client": bool(_deepseek_client),
            "ai_translation_available": ai_translation_available(),
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
        ip = client_ip_from_headers(request.headers, request.remote_addr or "")
        if not PREVIEW_LIMITER.allow(ip):
            return json_response({"error": "请求过于频繁，请稍后再试"}, status=429)
        payload, status = preview_payload(request.args.get("url", ""))
        return json_response(payload, status=status)

    @flask_app.get("/api/preview-image")
    def flask_preview_image():
        ip = client_ip_from_headers(request.headers, request.remote_addr or "")
        if not PREVIEW_LIMITER.allow(ip):
            return json_response({"error": "请求过于频繁，请稍后再试"}, status=429)
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

    @flask_app.post("/api/translate")
    def flask_translate():
        if (request.content_length or 0) > 500_000:
            return json_response({"error": "request too large"}, status=413)

        ip = client_ip_from_headers(request.headers, request.remote_addr or "")
        if not TRANSLATE_LIMITER.allow(ip):
            return json_response({"error": "请求过于频繁，请稍后再试"}, status=429)

        payload = request.get_json(silent=True) or {}
        source_key = payload.get("source", "")
        items = payload.get("items", [])
        if source_key not in SOURCES:
            return json_response({"error": "unknown source"}, status=400)
        if not isinstance(items, list):
            return json_response({"error": "invalid items"}, status=400)
        if len(items) > TRANSLATE_MAX_ITEMS:
            return json_response({"error": "too many items"}, status=400)

        clean_items = [item for item in items if isinstance(item, dict)]

        def generate():
            yield from (
                line + "\n"
                for line in translate_events(clean_items, source_key)
            )

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


# ── Static file serving ────────────────────────────────────────────────

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
