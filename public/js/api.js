// =========================================================================
// api.js — Network layer: feed loading & AI summary
// =========================================================================

import { streamNdjson } from './utils.js';
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

    await streamNdjson(response, (event) => {
      if (event.type === "source") {
        const prepared = (event.items || []).map((item) => {
          item._seq = nextItemSeq();
          return item;
        });
        state.items.push(...prepared);
        state.sourceCounts.set(event.key, event.count);
        state.loading = false;
        loadFeed._onStateChange?.("render", { sourceKey: event.key });
      } else if (event.type === "translate") {
        const item = state.items.find((i) => i.id === event.itemId);
        if (item) {
          const field = event.field;
          if (!item[`${field}Original`]) {
            item[`${field}Original`] = item[field];
          }
          item[field] = event.translated;
          loadFeed._onStateChange?.("translate", {
            itemId: event.itemId,
            field,
          });
        }
      } else if (event.type === "done") {
        loadFeed._onStateChange?.("errors", event.errors || []);
      }
    });
  } catch (error) {
    loadFeed._onStateChange?.("error", error.message);
  } finally {
    state.loading = false;
  }
}

/** Hooks set by ui.js so api can trigger re-renders without importing ui. */
loadFeed._onStateChange = null;
export function setFeedStateHandler(fn) { loadFeed._onStateChange = fn; }

// ---- On-demand translation -----------------------------------------------

/** Request translation for a batch of visible items from one source.
 *  Streams translate events back and patches item state + DOM via the
 *  same _onStateChange bridge used by loadFeed. */
export async function translateVisible(sourceKey, items) {
  if (!items.length) return;

  const payload = {
    source: sourceKey,
    items: items.map((item) => ({
      id: item.id,
      title: item.title || "",
      summary: item.summary || "",
    })),
  };

  try {
    const response = await fetch("/api/translate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok || !response.body) return;

    await streamNdjson(response, (event) => {
      if (event.type === "translate") {
        const item = state.items.find((i) => i.id === event.itemId);
        if (item) {
          const field = event.field;
          if (!item[`${field}Original`]) {
            item[`${field}Original`] = item[field];
          }
          item[field] = event.translated;
          loadFeed._onStateChange?.("translate", {
            itemId: event.itemId,
            field,
          });
        }
      }
    });
  } catch { /* network error — silent, items stay untranslated */ }
}

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

let summaryReqId = 0;

export function startSummaryFetch() {
  if (summaryState.loading) return;
  runSummaryFetch();
}

/** Abort any in-flight request and start a fresh one. */
export function regenerateSummary() {
  if (summaryState.aborter) {
    summaryState.aborter.abort();
    summaryState.aborter = null;
  }
  summaryState.loading = false; // cleared so runSummaryFetch proceeds
  runSummaryFetch();
}

function runSummaryFetch() {
  const reqId = ++summaryReqId;
  summaryState.loading = true;
  summaryState.text    = null;
  summaryState.error   = null;
  summaryState.sources = {};
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
      if (!response.ok) {
        // Surface the server's reason (e.g. "items 过多") instead of a bare status.
        let detail = `HTTP ${response.status}`;
        try {
          const data = await response.json();
          if (data?.error) detail = data.error;
        } catch { /* keep status */ }
        throw new Error(detail);
      }
      if (!response.body) throw new Error("浏览器不支持流式响应");

      await streamNdjson(response, (event) => {
        if (reqId !== summaryReqId) return; // superseded
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
      });

      if (reqId !== summaryReqId) return;
      if (!summaryState.text?.trim()) {
        summaryState.error = "总结生成失败，请稍后重试。";
      }
    })
    .catch((error) => {
      if (reqId !== summaryReqId) return; // superseded
      if (error.name !== "AbortError") {
        summaryState.error = `请求失败：${error.message}`;
      }
    })
    .finally(() => {
      if (reqId !== summaryReqId) return; // superseded
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
