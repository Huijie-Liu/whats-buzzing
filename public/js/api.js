// =========================================================================
// api.js — Network layer: feed loading, translation streaming, AI summary
// =========================================================================

import {
  state, nextItemSeq, resetItemSeq,
  prepareItem, loadTranslationCache, saveTranslationCache,
  findItemById, shouldTranslateItem, translationPayload,
  TRANSLATABLE_SOURCES,
} from './core.js';

// Re-export for convenience (used by ui.js)
export { TRANSLATABLE_SOURCES };

// ---- Translation infrastructure -----------------------------------------

let translationController = null;
let translationRunId = 0;

export function cancelTranslations() {
  translationRunId += 1;
  if (translationController) {
    translationController.abort();
    translationController = null;
  }
}

/** Called by ui.js so the translation layer can update DOM nodes. */
let onTranslationEvent = null;
export function setTranslationHandler(fn) { onTranslationEvent = fn; }

function handleTranslationEvent(event) {
  if (!event?.id) return;
  const item = findItemById(event.id);
  if (!item) return;

  if (event.type === "start" || event.type === "chunk") {
    if (item.translationStatus !== "streaming") {
      item.translationStatus = "streaming";
      onTranslationEvent?.(item, { type: "update" });
    }
    return;
  }

  if (event.type === "done") {
    item.titleZh  = event.title || item.titleZh;
    item.summaryZh = event.summary || "";
    item.translationStatus = "done";
    onTranslationEvent?.(item, { type: "done" });
    const cache = loadTranslationCache();
    cache[item.id] = { titleZh: item.titleZh, summaryZh: item.summaryZh, savedAt: Date.now() };
    saveTranslationCache(cache);
    return;
  }

  if (event.type === "error") {
    item.translationStatus = "error";
    onTranslationEvent?.(item, { type: "update" });
  }
}

async function streamTranslations(items, runId, signal) {
  try {
    const response = await fetch("/api/translate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: items.map(translationPayload) }),
      signal,
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    if (!response.body) throw new Error("当前浏览器不支持流式响应");

    const reader  = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.trim() || runId !== translationRunId) continue;
        try { handleTranslationEvent(JSON.parse(line)); }
        catch { /* skip malformed JSON */ }
      }

      if (done) break;
    }

    if (buffer.trim() && runId === translationRunId) {
      try {
        const event = JSON.parse(buffer);
        if (event.type !== "complete") handleTranslationEvent(event);
      } catch { /* skip */ }
    }
  } catch (error) {
    if (error.name !== "AbortError") {
      items.forEach((item) => {
        if (item.translationStatus === "streaming" || item.translationStatus === "queued") {
          item.translationStatus = "error";
          onTranslationEvent?.(item, { type: "update" });
        }
      });
    }
  } finally {
    if (runId === translationRunId) {
      translationController = null;
      onTranslationEvent?.(null, { type: "drain" });
    }
  }
}

// ---- Translation scheduling ----------------------------------------------

export function resetAndCancelTranslations() {
  translationRunId += 1;
  if (translationController) {
    translationController.abort();
    translationController = null;
  }
  // Reset streaming/queued items back to pending
  state.items.forEach((item) => {
    if (item.translationStatus === "streaming" || item.translationStatus === "queued") {
      item.translationStatus = item.titleZh ? "done" : "pending";
    }
  });
}

/** Called by ui.js to get visible item ids from the DOM. */
let getVisibleIds = null;
export function setVisibleIdsGetter(fn) { getVisibleIds = fn; }

export function translateBatch(batch) {
  if (!batch.length) return;

  // Cancel any in-flight translation — its items will be reset below
  if (translationController) {
    translationController.abort();
    translationController = null;
  }
  translationRunId += 1;

  // Reset all streaming/queued items (from the aborted batch) back to pending
  state.items.forEach((item) => {
    if (item.translationStatus === "streaming" || item.translationStatus === "queued") {
      item.translationStatus = item.titleZh ? "done" : "pending";
      onTranslationEvent?.(item, { type: "update" });
    }
  });

  // Mark new batch items as queued
  batch.forEach((item) => {
    item.translationStatus = "queued";
    onTranslationEvent?.(item, { type: "update" });
  });

  translationController = new AbortController();
  const runId = ++translationRunId;
  streamTranslations(batch, runId, translationController.signal);
}

export function startTranslationsForVisible() {
  resetAndCancelTranslations();
  const visibleIds = getVisibleIds?.() || new Set();

  // Get displayed items via the callback (avoids circular import with ui.js)
  let getDisplayed = null;
  // Set by app.js after both modules are loaded
  startTranslationsForVisible._getDisplayed = startTranslationsForVisible._getDisplayed || (() => []);

  const pending = startTranslationsForVisible._getDisplayed().filter(shouldTranslateItem);
  if (!pending.length) return;
  translateBatch(pending.filter((item) => visibleIds.has(item.id)));
}

export function drainPendingQueue() {
  // Will be connected by app.js
  if (drainPendingQueue._drain) drainPendingQueue._drain();
}

// ---- Feed loading --------------------------------------------------------

export async function loadFeed() {
  cancelTranslations();
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
    const translationCache = loadTranslationCache();

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
              const p = prepareItem(item, translationCache);
              p._seq = nextItemSeq();
              return p;
            });
            state.items.push(...prepared);
            state.sourceCounts.set(event.key, event.count);
            state.loading = false;
            loadFeed._onStateChange?.("render");
            startTranslationsForVisible();
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
    startTranslationsForVisible();
  }
}

/** Hooks set by ui.js so api can trigger re-renders without importing ui. */
loadFeed._onStateChange = null;
export function setFeedStateHandler(fn) { loadFeed._onStateChange = fn; }

// Wire up the displayed items getter for translation scheduling
export function setDisplayedItemsGetter(fn) {
  startTranslationsForVisible._getDisplayed = fn;
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
    title: item.titleOriginal || item.title || "",
    summary: item.summaryOriginal || item.summary || "",
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
