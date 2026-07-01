// =========================================================================
// core.js — State management, storage, utilities & configuration
// =========================================================================

import { toText, formatRelativeTime, isLiveTitle, escapeHtml } from './utils.js';

// ---- Configuration -------------------------------------------------------

export const SOURCE_GROUPS = [
  { key: "hot",       label: "热点" },
  { key: "general",   label: "综合" },
  { key: "business",  label: "财经" },
  { key: "tech",      label: "科技" },
  { key: "sports",    label: "体育" },
];

export const SOURCES = [
  { key: "zhihu",      label: "知乎热榜",       accent: "#0066ff", group: "hot" },
  { key: "linux_do_top", label: "LINUX DO 热榜", accent: "#0a8ed6", group: "hot" },
  { key: "hn",         label: "Hacker News",    accent: "#f0652f", group: "hot" },
  { key: "google_zh",  label: "Google News 中国", accent: "#34a853", group: "hot" },
  { key: "reuters",    label: "路透社",         accent: "#ff8000", group: "general" },
  { key: "bbc",        label: "BBC",            accent: "#b80000", group: "general" },
  { key: "guardian",   label: "卫报",           accent: "#052962", group: "general" },
  { key: "washingtonpost", label: "华盛顿邮报", accent: "#1a1a1a", group: "general" },
  { key: "atlantic",   label: "大西洋周刊",     accent: "#111111", group: "general" },
  { key: "newyorker",  label: "纽约客",         accent: "#e60000", group: "general" },
  { key: "bloomberg",  label: "彭博社",         accent: "#0068ff", group: "business" },
  { key: "economist",  label: "经济学人",       accent: "#d71920", group: "business" },
  { key: "verge",      label: "The Verge",      accent: "#e2127a", group: "tech" },
  { key: "mit_tech",   label: "MIT 科技评论",   accent: "#ff5a00", group: "tech" },
  { key: "linux_do",   label: "LINUX DO",       accent: "#0088cc", group: "tech" },
  { key: "hupu_nba",   label: "虎扑-篮球",     accent: "#c41230", group: "sports" },
  { key: "hupu_soccer", label: "虎扑-足球",     accent: "#019f4b", group: "sports" },
  { key: "hupu_lol",   label: "虎扑-LOL",      accent: "#6b3fa0", group: "sports" },
];

export const MAX_ITEMS_PER_TAB     = 50;
export const READ_STORAGE_KEY      = "readArticleIds";
export const THEME_STORAGE_KEY     = "themeMode";
export const MAX_READ_IDS          = 2000;

// ---- State ---------------------------------------------------------------

function initialSourceGroup() {
  const stored = localStorage.getItem("activeSourceGroup");
  return SOURCE_GROUPS.some((g) => g.key === stored) ? stored : "hot";
}

function loadReadIds() {
  try {
    const parsed = JSON.parse(localStorage.getItem(READ_STORAGE_KEY) || "[]");
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter(Boolean).slice(-MAX_READ_IDS));
  } catch {
    return new Set();
  }
}

let _itemSeq = 0;

export const state = {
  activeGroup: initialSourceGroup(),
  items: [],
  sourceCounts: new Map(),
  withImages: true,
  theme: localStorage.getItem(THEME_STORAGE_KEY) || "light",
  loading: false,
  readIds: loadReadIds(),
};

export function nextItemSeq() { return ++_itemSeq; }
export function resetItemSeq() { _itemSeq = 0; }

// ---- Storage helpers ----------------------------------------------------

export function saveReadIds() {
  const ids = Array.from(state.readIds).slice(-MAX_READ_IDS);
  state.readIds = new Set(ids);
  localStorage.setItem(READ_STORAGE_KEY, JSON.stringify(ids));
}

export function markRead(item) {
  if (!item.id || state.readIds.has(item.id)) return false;
  state.readIds.add(item.id);
  saveReadIds();
  return true;
}

// ---- Source helpers ------------------------------------------------------

export function sourceMeta(sourceKey) {
  return SOURCES.find((s) => s.key === sourceKey);
}

export function sourceGroup(sourceKey) {
  return sourceMeta(sourceKey)?.group || "news";
}

export function activeGroupSources() {
  return SOURCES.filter((s) => s.group === state.activeGroup);
}

export function isInActiveGroup(item) {
  return sourceGroup(item.source) === state.activeGroup;
}

export function sourceCount(sourceKey) {
  return Math.min(state.sourceCounts.get(sourceKey) || 0, MAX_ITEMS_PER_TAB);
}

// Sources whose content is already Chinese — skip translation.
// Read from the config injected in index.html (kept in sync with
// NON_TRANSLATABLE_SOURCES in server.py); fall back to a hardcoded list
// so a missing config never breaks the page.
const _cfg = (window.__BUZZING_CONFIG__ || {});
const NON_TRANSLATABLE_SOURCES = new Set(
  _cfg.nonTranslatableSources || ["zhihu", "google_zh", "linux_do", "linux_do_top", "hupu_nba", "hupu_soccer", "hupu_lol"]
);

export function shouldTranslateSource(sourceKey) {
  return !NON_TRANSLATABLE_SOURCES.has(sourceKey);
}

export function setActiveGroup(groupKey) {
  if (!SOURCE_GROUPS.some((g) => g.key === groupKey)) return;
  state.activeGroup = groupKey;
  localStorage.setItem("activeSourceGroup", groupKey);
}

// ---- Column grouping -----------------------------------------------------

// Sources that are already ranked by the server (e.g. HN top stories,
// Zhihu hot list) — preserve the server order instead of sorting by time.
const RANKED_SOURCES = new Set(["zhihu", "google_zh", "linux_do_top", "hupu_nba", "hupu_soccer", "hupu_lol", "hn"]);

/** One entry per source in the active group.  Ranked sources keep
 *  server order; the rest are sorted newest-first. */
export function groupColumns() {
  return activeGroupSources().map((source) => {
    let items = state.items.filter((item) => item.source === source.key);
    if (RANKED_SOURCES.has(source.key)) {
      // Preserve server rank order (items already sorted by rank)
      items.sort((a, b) => (a.rank ?? 9999) - (b.rank ?? 9999));
    } else {
      items.sort((a, b) => (b.publishedAt || "").localeCompare(a.publishedAt || ""));
    }
    items = items.slice(0, MAX_ITEMS_PER_TAB);
    return { source: source.key, label: source.label, accent: source.accent, items };
  });
}

/** Flat list of every item currently on screen (across all columns). */
export function displayedItems() {
  return groupColumns().flatMap((col) => col.items);
}

export function findItemById(id) {
  return state.items.find((item) => item.id === id);
}
