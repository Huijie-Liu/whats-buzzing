// =========================================================================
// core.js — State management, storage, utilities & configuration
// =========================================================================

// ---- Configuration -------------------------------------------------------

export const SOURCE_GROUPS = [
  { key: "news",     label: "新闻" },
  { key: "hot",      label: "热点" },
  { key: "analysis", label: "深度" },
];

export const SOURCES = [
  { key: "reuters",    label: "路透社",       accent: "#ff8000", group: "news" },
  { key: "bloomberg",  label: "彭博社",       accent: "#0068ff", group: "news" },
  { key: "guardian",   label: "卫报",         accent: "#052962", group: "news" },
  { key: "bbc",        label: "BBC",          accent: "#b80000", group: "news" },
  { key: "washingtonpost", label: "华盛顿邮报", accent: "#1a1a1a", group: "news" },
  { key: "zhihu",      label: "知乎热榜",     accent: "#0066ff", group: "hot" },
  { key: "hn",         label: "Hacker News",  accent: "#f0652f", group: "hot" },
  { key: "google",     label: "Google News 美国", accent: "#1a73e8", group: "hot" },
  { key: "google_zh",  label: "Google News 中国", accent: "#34a853", group: "hot" },
  { key: "economist",  label: "经济学人",     accent: "#d71920", group: "analysis" },
  { key: "verge",      label: "The Verge",    accent: "#e2127a", group: "analysis" },
  { key: "atlantic",   label: "大西洋周刊",   accent: "#111111", group: "analysis" },
  { key: "newyorker",  label: "纽约客",       accent: "#e60000", group: "analysis" },
  { key: "mit_tech",   label: "MIT 科技评论", accent: "#ff5a00", group: "analysis" },
];

export const MAX_ITEMS_PER_TAB     = 50;
export const READ_STORAGE_KEY      = "readArticleIds";
export const THEME_STORAGE_KEY     = "themeMode";
export const MAX_READ_IDS          = 2000;

// ---- State ---------------------------------------------------------------

function initialSourceGroup() {
  const stored = localStorage.getItem("activeSourceGroup");
  return SOURCE_GROUPS.some((g) => g.key === stored) ? stored : "news";
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

export function setActiveGroup(groupKey) {
  if (!SOURCE_GROUPS.some((g) => g.key === groupKey)) return;
  state.activeGroup = groupKey;
  localStorage.setItem("activeSourceGroup", groupKey);
}

// ---- Utilities -----------------------------------------------------------

export function toText(value) {
  return String(value ?? "");
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

export function isLiveTitle(title) {
  return /^Live\b|^LIVE\b|^\[Live\]|^【直播】|直播\|/.test(title || "");
}

export function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ---- Column grouping -----------------------------------------------------

// Sources that are already ranked by the server (e.g. HN top stories,
// Zhihu hot list) — preserve the server order instead of sorting by time.
const RANKED_SOURCES = new Set(["hn", "zhihu", "google", "google_zh"]);

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
