// =========================================================================
// api.js — Network layer: feed loading & AI summary
// =========================================================================

import {
  state, nextItemSeq, resetItemSeq,
} from './core.js';

// ---- Feed loading --------------------------------------------------------

export async function loadFeed() {
  state.loading = true;
  state.items = [];
  state.sourceCounts = new Map();
  resetItemSeq();

  // Notify UI to show skeletons
  if (loadFeed._onStateChange) loadFeed._onStateChange("loading");

  try {
    const response = await fetch("/api/feed?source=all", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
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
          if (event.type === "source") {
            const prepared = (event.items || []).map((item) => {
              item._seq = nextItemSeq();
              return item;
            });
            state.items.push(...prepared);
            state.sourceCounts.set(event.key, event.count);
            state.loading = false;
            loadFeed._onStateChange?.("render");
          } else if (event.type === "done") {
            loadFeed._onStateChange?.("errors", event.errors || []);
          }
        } catch { /* skip malformed */ }
      }

      if (done) break;
    }
  } catch (error) {
    loadFeed._onStateChange?.("error", error.message);
  } finally {
    state.loading = false;
    loadFeed._onStateChange?.("render");
  }
}

/** Hooks set by ui.js so api can trigger re-renders without importing ui. */
loadFeed._onStateChange = null;
export function setFeedStateHandler(fn) { loadFeed._onStateChange = fn; }

// ---- AI Summary ----------------------------------------------------------

export const summaryState = {
  text: null,
  loading: false,
  error: null,
  sources: {},
  aborter: null,
  modal: null,
};

/** Called by ui.js when the summary modal needs a refresh. */
let onSummaryRefresh = null;
export function setSummaryRefreshHandler(fn) { onSummaryRefresh = fn; }

function buildSummaryPayload() {
  return state.items.map((item) => ({
    source: item.source,
    title: item.title || "",
    summary: item.summary || "",
    url: item.url || "",
    discussionUrl: item.discussionUrl || "",
  }));
}

export function startSummaryFetch() {
  if (summaryState.loading) return;

  summaryState.loading = true;
  summaryState.text   = null;
  summaryState.error  = null;
  onSummaryRefresh?.("button");

  const payload = buildSummaryPayload();
  if (!payload.length) {
    summaryState.loading = false;
    summaryState.error = "当前没有可总结的内容。";
    onSummaryRefresh?.("button");
    return;
  }

  summaryState.aborter = new AbortController();

  fetch("/api/summary", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items: payload }),
    signal: summaryState.aborter.signal,
  })
    .then(async (response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
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
            if (event.type === "chunk") {
              summaryState.text = (summaryState.text || "") + event.text;
              onSummaryRefresh?.("modal");
            } else if (event.type === "done") {
              summaryState.text = event.text || summaryState.text;
              if (event.sources) summaryState.sources = event.sources;
              summaryState.loading = false;
              onSummaryRefresh?.("button");
              onSummaryRefresh?.("modal");
            } else if (event.type === "error") {
              summaryState.error = `总结生成失败：${event.message}`;
              onSummaryRefresh?.("modal");
            }
          } catch { /* skip malformed */ }
        }

        if (done) break;
      }

      if (!summaryState.text?.trim()) {
        summaryState.error = "总结生成失败，请稍后重试。";
      }
    })
    .catch((error) => {
      if (error.name !== "AbortError") {
        summaryState.error = `请求失败：${error.message}`;
      }
    })
    .finally(() => {
      summaryState.loading = false;
      summaryState.aborter = null;
      onSummaryRefresh?.("button");
      onSummaryRefresh?.("modal");
      // Signal ui to flash the button
      if (summaryState.text && !summaryState.error) {
        onSummaryRefresh?.("flash");
      }
    });
}
