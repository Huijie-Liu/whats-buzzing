// =========================================================================
// utils.js — Shared utilities used across the frontend
// =========================================================================

// ---- DOM helpers -------------------------------------------------------

/** Shorthand for document.querySelector. */
export function $(sel) { return document.querySelector(sel); }

/** Shorthand for document.querySelectorAll (returns an array). */
export function $$(sel) { return [...document.querySelectorAll(sel)]; }

// ---- String utilities --------------------------------------------------

export function toText(value) {
  return String(value ?? "");
}

export function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

export function isLiveTitle(title) {
  return /^Live\b|^LIVE\b|^\[Live\]|^【直播】|直播\|/.test(title || "");
}

export function formatRelativeTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const diff = Date.now() - date.getTime();
  const minutes = Math.max(0, Math.floor(diff / 60000));
  if (minutes < 1)  return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24)   return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 7)     return `${days} 天前`;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }).format(date);
}


// ---- NDJSON stream reader ---------------------------------------------

/**
 * Read an NDJSON stream from a fetch Response body.
 *
 * Calls ``onEvent(event)`` for each parsed JSON object.  Returns a promise
 * that resolves when the stream ends (or rejects on stream error).
 *
 * Usage::
 *
 *   const response = await fetch("/api/feed?source=all");
 *   await streamNdjson(response, (event) => {
 *     if (event.type === "source") { ... }
 *   });
 */
export async function streamNdjson(response, onEvent) {
  if (!response.body) throw new Error("浏览器不支持流式响应");

  const reader  = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const event = JSON.parse(line);
        onEvent(event);
      } catch { /* skip malformed */ }
    }

    if (done) break;
  }
}
