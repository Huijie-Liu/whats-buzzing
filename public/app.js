const SOURCE_GROUPS = [
  { key: "news", label: "新闻" },
  { key: "hot", label: "热点" },
  { key: "analysis", label: "深度" },
];

const SOURCES = [
  { key: "reuters", label: "路透社", accent: "#ff8000", group: "news" },
  { key: "bloomberg", label: "彭博社", accent: "#0068ff", group: "news" },
  { key: "wsj", label: "华尔街日报", accent: "#333740", group: "news" },
  { key: "ap", label: "美联社", accent: "#ff322e", group: "news" },
  { key: "zhihu", label: "知乎热榜", accent: "#0066ff", group: "hot" },
  { key: "hn", label: "Hacker News", accent: "#f0652f", group: "hot" },
  { key: "google", label: "Google News 美国", accent: "#1a73e8", group: "hot" },
  { key: "google_zh", label: "Google News 中国", accent: "#34a853", group: "hot" },
  { key: "economist", label: "经济学人", accent: "#d71920", group: "analysis" },
  { key: "atlantic", label: "大西洋周刊", accent: "#111111", group: "analysis" },
  { key: "newyorker", label: "纽约客", accent: "#e60000", group: "analysis" },
  { key: "mit_tech", label: "MIT 科技评论", accent: "#ff5a00", group: "analysis" },
];

const MAX_ITEMS_PER_TAB = 50;
const READ_STORAGE_KEY = "readArticleIds";
const THEME_STORAGE_KEY = "themeMode";
const TRANSLATION_CACHE_KEY = "tlV2";
const MAX_READ_IDS = 2000;
const MAX_TRANSLATION_CACHE = 600;
const VISIBLE_BUFFER = 10;
const TRANSLATABLE_SOURCES = new Set([
  "hn",
  "economist",
  "reuters",
  "bloomberg",
  "wsj",
  "ap",
  "google",
  "atlantic",
  "newyorker",
  "mit_tech",
  "washingtonpost",
]);

let translationController = null;
let translationRunId = 0;

function initialSourceGroup() {
  const stored = localStorage.getItem("activeSourceGroup");
  return SOURCE_GROUPS.some((group) => group.key === stored) ? stored : "news";
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

const state = {
  activeGroup: initialSourceGroup(),
  items: [],
  sourceCounts: new Map(),
  withImages: true,
  theme: localStorage.getItem(THEME_STORAGE_KEY) || "light",
  loading: false,
  readIds: loadReadIds(),
};

let itemSeq = 0;

const els = {
  categoryTabs: document.querySelector("#categoryTabs"),
  feed: document.querySelector("#feed"),
  error: document.querySelector("#errorBox"),
  theme: document.querySelector("#themeButton"),
  template: document.querySelector("#articleTemplate"),
};

function escapeText(value) {
  return String(value ?? "");
}

function loadTranslationCache() {
  try {
    return JSON.parse(localStorage.getItem(TRANSLATION_CACHE_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveTranslationCache(cache) {
  const entries = Object.entries(cache);
  if (entries.length > MAX_TRANSLATION_CACHE) {
    entries.sort((a, b) => (b[1].savedAt || 0) - (a[1].savedAt || 0));
    cache = Object.fromEntries(entries.slice(0, MAX_TRANSLATION_CACHE));
  }
  try {
    localStorage.setItem(TRANSLATION_CACHE_KEY, JSON.stringify(cache));
  } catch { /* quota */ }
}

function saveReadIds() {
  const ids = Array.from(state.readIds).slice(-MAX_READ_IDS);
  state.readIds = new Set(ids);
  localStorage.setItem(READ_STORAGE_KEY, JSON.stringify(ids));
}

function markRead(item, node) {
  if (!item.id || state.readIds.has(item.id)) return;
  state.readIds.add(item.id);
  saveReadIds();
  node.classList.add("read");
}

function sourceMeta(sourceKey) {
  return SOURCES.find((source) => source.key === sourceKey);
}

function sourceGroup(sourceKey) {
  return sourceMeta(sourceKey)?.group || "news";
}

function activeGroupSources() {
  return SOURCES.filter((source) => source.group === state.activeGroup);
}

function isInActiveGroup(item) {
  return sourceGroup(item.source) === state.activeGroup;
}

function sourceCount(sourceKey) {
  return Math.min(state.sourceCounts.get(sourceKey) || 0, MAX_ITEMS_PER_TAB);
}

function setActiveGroup(groupKey) {
  if (!SOURCE_GROUPS.some((group) => group.key === groupKey)) return;
  state.activeGroup = groupKey;
  localStorage.setItem("activeSourceGroup", groupKey);
  render();
  startTranslationsForVisibleItems();
}

function prepareItem(item, translationCache = {}) {
  const cached = translationCache[item.id];
  if (cached?.titleZh) {
    return {
      ...item,
      titleOriginal: item.title || "",
      summaryOriginal: item.summary || "",
      titleZh: cached.titleZh,
      summaryZh: item.summary ? (cached.summaryZh || "") : "",
      translationStatus: "done",
    };
  }
  return {
    ...item,
    titleOriginal: item.title || "",
    summaryOriginal: item.summary || "",
    translationStatus: TRANSLATABLE_SOURCES.has(item.source) ? "pending" : "skipped",
  };
}

function displayTitle(item) {
  return item.titleZh || item.titleOriginal || item.title || item.summary || "Untitled";
}

function displaySummary(item) {
  // No original summary → show nothing, even if a stale translation is
  // cached (e.g. AP items that used to carry the publisher name).
  if (!(item.summaryOriginal || item.summary)) return "";
  if (item.summaryZh) return item.summaryZh;
  return item.summaryOriginal || item.summary || "";
}

function shouldTranslateItem(item) {
  return (
    TRANSLATABLE_SOURCES.has(item.source) &&
    item.translationStatus !== "streaming" &&
    item.translationStatus !== "queued" &&
    item.translationStatus !== "done" &&
    !item.titleZh
  );
}

function findItemById(id) {
  return state.items.find((item) => item.id === id);
}

function findArticleNode(id) {
  return Array.from(els.feed.querySelectorAll(".story")).find((node) => node.dataset.itemId === id);
}

function resetActiveTranslations() {
  state.items.forEach((item) => {
    if (item.translationStatus === "streaming" || item.translationStatus === "queued") {
      item.translationStatus = item.titleZh ? "done" : "pending";
    }
  });
}

function cancelTranslations() {
  translationRunId += 1;
  if (translationController) {
    translationController.abort();
    translationController = null;
  }
  resetActiveTranslations();
}

function setTheme(theme) {
  state.theme = theme === "dark" ? "dark" : "light";
  localStorage.setItem(THEME_STORAGE_KEY, state.theme);
  document.body.classList.toggle("theme-dark", state.theme === "dark");
  els.theme.querySelector("span").textContent = state.theme === "dark" ? "☀" : "☾";
  els.theme.setAttribute("aria-label", state.theme === "dark" ? "切换日间模式" : "切换夜间模式");
  els.theme.title = state.theme === "dark" ? "切换日间模式" : "切换夜间模式";
}

function formatRelativeTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const diff = Date.now() - date.getTime();
  const minutes = Math.max(0, Math.floor(diff / 60000));
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} 天前`;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function isLiveTitle(title) {
  return /^Live\b|^LIVE\b|^\[Live\]|^【直播】|直播\|/.test(title || "");
}

function renderCategoryTabs() {
  els.categoryTabs.replaceChildren();
  SOURCE_GROUPS.forEach((group) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "category-tab";
    button.classList.toggle("active", state.activeGroup === group.key);
    button.innerHTML = `<span>${group.label}</span>`;
    button.addEventListener("click", () => setActiveGroup(group.key));
    els.categoryTabs.append(button);
  });
}

// One entry per source in the active group, each carrying its own items
// sorted newest-first. This drives the column board.
function groupColumns() {
  return activeGroupSources().map((source) => {
    const items = state.items
      .filter((item) => item.source === source.key)
      .sort((a, b) => (b.publishedAt || "").localeCompare(a.publishedAt || ""))
      .slice(0, MAX_ITEMS_PER_TAB);
    return { source: source.key, label: source.label, accent: source.accent, items };
  });
}

// Flat list of every item currently on screen (across all columns) — used
// by the translation logic to pick candidates.
function displayedItems() {
  return groupColumns().flatMap((column) => column.items);
}

function renderArticle(item) {
  const node = els.template.content.firstElementChild.cloneNode(true);
  const mainUrl = item.url || item.discussionUrl || "#";
  const hasImage = state.withImages && Boolean(item.image);
  const markCurrentRead = () => markRead(item, node);
  const sourceKey = item.source || "";

  node.dataset.itemId = item.id || "";
  node.classList.add(`story-${sourceKey}`);
  node.classList.toggle("has-image", hasImage);
  node.classList.toggle("read", state.readIds.has(item.id));
  node.classList.toggle("translating", item.translationStatus === "streaming" || item.translationStatus === "queued");
  node.classList.toggle("translated", item.translationStatus === "done");
  node.style.setProperty("--source-color", item.accent || "#191b1f");

  const media = node.querySelector(".media");
  const img = node.querySelector("img");
  if (hasImage) {
    media.href = mainUrl;
    media.addEventListener("click", markCurrentRead);
    img.src = item.image;
    img.onerror = () => {
      img.remove();
      const err = document.createElement("div");
      err.className = "media-error";
      err.textContent = "无图";
      media.appendChild(err);
    };
  } else {
    media.remove();
  }

  const srcEl = node.querySelector(".source");
  srcEl.textContent = item.sourceLabel;
  const srcHome = sourceMeta(sourceKey)?.home || "#";
  if (srcHome !== "#") srcEl.href = srcHome;

  const time = node.querySelector("time");
  time.textContent = formatRelativeTime(item.publishedAt);
  if (item.publishedAt) time.dateTime = item.publishedAt;

  const hnStat = node.querySelector(".hn-stat");
  hnStat.remove();

  const title = node.querySelector(".title");
  title.href = mainUrl;
  title.textContent = escapeText(displayTitle(item));
  if (isLiveTitle(item.titleOriginal || item.title || "")) {
    const badge = document.createElement("span");
    badge.className = "live-badge";
    badge.textContent = "LIVE";
    title.appendChild(badge);
  }
  title.addEventListener("click", markCurrentRead);

  const summary = node.querySelector(".summary");
  const summaryText = displaySummary(item);
  summary.textContent = escapeText(summaryText);
  summary.hidden = !summaryText;

  const links = node.querySelector(".links");
  const expandBtn = node.querySelector(".expand-toggle");
  if (expandBtn) expandBtn.remove();

  // ---- Source-specific features ----

  // HN: prominent stats badges (points, comments) + author.
  // The comments badge doubles as the discussion link — no separate "讨论".
  if (sourceKey === "hn") {
    const statsEl = document.createElement("div");
    statsEl.className = "card-stats";

    const score = Number.isFinite(Number(item.score)) ? Number(item.score) : null;
    const comments = Number.isFinite(Number(item.comments)) ? Number(item.comments) : null;
    const discUrl = item.discussionUrl || mainUrl;

    if (score !== null) {
      const points = document.createElement("span");
      points.className = "stat-badge points";
      points.textContent = `▲ ${score}`;
      statsEl.appendChild(points);
    }
    if (comments !== null) {
      const commLink = document.createElement("a");
      commLink.className = "stat-badge comments";
      commLink.href = discUrl;
      commLink.target = "_blank";
      commLink.rel = "noreferrer";
      commLink.textContent = `💬 ${comments}`;
      commLink.addEventListener("click", markCurrentRead);
      statsEl.appendChild(commLink);
    }
    // Author (stored in summary by server)
    const author = (item.summaryOriginal || "").trim();
    if (author && !/^\d/.test(author)) {
      const auth = document.createElement("span");
      auth.className = "stat-badge author";
      auth.textContent = author;
      statsEl.appendChild(auth);
    }

    if (statsEl.children.length) {
      links.insertAdjacentElement("beforebegin", statsEl);
    }
  }

  // Zhihu: heat badge instead of time
  if (sourceKey === "zhihu") {
    if (item.score && item.score > 0) {
      const statsEl = document.createElement("div");
      statsEl.className = "card-stats";
      const heat = document.createElement("span");
      heat.className = "stat-badge heat";
      const heatStr = item.score >= 10000
        ? `${(item.score / 10000).toFixed(1)} 万热度`
        : `${item.score} 热度`;
      heat.textContent = `🔥 ${heatStr}`;
      statsEl.appendChild(heat);
      links.insertAdjacentElement("beforebegin", statsEl);
    }
  }

  // Google News: publisher badge in meta
  if (sourceKey === "google" || sourceKey === "google_zh") {
    const publisher = (item.summaryOriginal || "").trim();
    if (publisher && publisher.length < 40) {
      const pubBadge = document.createElement("span");
      pubBadge.className = "publisher-badge";
      pubBadge.textContent = publisher;
      srcEl.after(pubBadge);
    }
  }

  const discussion = node.querySelector(".discussion");
  // HN: the comments badge already links to the discussion — remove the text link.
  if (item.discussionUrl && item.discussionUrl.startsWith("http") && item.discussionUrl !== mainUrl && sourceKey !== "hn") {
    discussion.href = item.discussionUrl;
    discussion.addEventListener("click", markCurrentRead);
  } else {
    discussion.remove();
  }

  return node;
}

function updateArticleNode(item, animate = false) {
  const node = findArticleNode(item.id);
  if (!node) return;
  node.classList.toggle("translating", item.translationStatus === "streaming" || item.translationStatus === "queued");
  node.classList.toggle("translated", item.translationStatus === "done");

  const title = node.querySelector(".title");
  const summary = node.querySelector(".summary");
  title.textContent = escapeText(displayTitle(item));

  const summaryText = displaySummary(item);
  summary.textContent = escapeText(summaryText);
  summary.hidden = !summaryText;

  // Re-evaluate expand button after summary content changes
  const oldBtn = node.querySelector(".expand-toggle");
  if (oldBtn) oldBtn.remove();
  addExpandButtons();

  if (animate) {
    node.classList.remove("translation-swap");
    void node.offsetWidth;
    node.classList.add("translation-swap");
  }
}

function translationPayload(item) {
  return {
    id: item.id,
    source: item.source,
    title: item.titleOriginal || item.title || "",
    summary: item.summaryOriginal || item.summary || "",
  };
}

function handleTranslationEvent(event) {
  if (!event || !event.id) return;
  const item = findItemById(event.id);
  if (!item) return;

  if (event.type === "start" || event.type === "chunk") {
    if (item.translationStatus !== "streaming") {
      item.translationStatus = "streaming";
      updateArticleNode(item);
    }
    return;
  }

  if (event.type === "done") {
    item.titleZh = event.title || item.titleZh;
    item.summaryZh = event.summary || "";
    item.translationStatus = "done";
    updateArticleNode(item, true);
    const cache = loadTranslationCache();
    cache[item.id] = { titleZh: item.titleZh, summaryZh: item.summaryZh, savedAt: Date.now() };
    saveTranslationCache(cache);
    return;
  }

  if (event.type === "error") {
    item.translationStatus = "error";
    updateArticleNode(item);
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

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.trim() || runId !== translationRunId) continue;
        const event = JSON.parse(line);
        if (event.type === "complete") continue;
        handleTranslationEvent(event);
      }

      if (done) break;
    }

    if (buffer.trim() && runId === translationRunId) {
      const event = JSON.parse(buffer);
      if (event.type !== "complete") handleTranslationEvent(event);
    }
  } catch (error) {
    if (error.name !== "AbortError") {
      items.forEach((item) => {
        if (item.translationStatus === "streaming" || item.translationStatus === "queued") {
          item.translationStatus = "error";
          updateArticleNode(item);
        }
      });
    }
  } finally {
    if (runId === translationRunId) {
      translationController = null;
      drainPendingQueue();
    }
  }
}

function getVisibleItemIds() {
  const ids = new Set();
  const viewH = window.innerHeight;
  const viewW = window.innerWidth;
  const vMargin = viewH;
  const hMargin = viewW * 0.5;
  els.feed.querySelectorAll(".story").forEach((el) => {
    const r = el.getBoundingClientRect();
    const verticallyNear = r.bottom >= -vMargin && r.top <= viewH + vMargin;
    const horizontallyNear = r.right >= -hMargin && r.left <= viewW + hMargin;
    if (verticallyNear && horizontallyNear) {
      ids.add(el.dataset.itemId);
    }
  });
  return ids;
}

function translateBatch(batch) {
  if (!batch.length) return;
  batch.forEach((item) => {
    item.translationStatus = "queued";
    updateArticleNode(item);
  });
  translationController = new AbortController();
  const runId = ++translationRunId;
  streamTranslations(batch, runId, translationController.signal);
}

function startTranslationsForVisibleItems() {
  // Cancel any in-flight translation and restart with only what's in view
  translationRunId += 1;
  if (translationController) {
    translationController.abort();
    translationController = null;
  }
  resetActiveTranslations();

  const visibleIds = getVisibleItemIds();
  const pending = displayedItems().filter(shouldTranslateItem);
  if (!pending.length) return;

  const visible = pending.filter((item) => visibleIds.has(item.id));
  translateBatch(visible);
}

let scrollTimer = null;
let pendingQueue = [];

function onScrollTranslate() {
  if (scrollTimer) clearTimeout(scrollTimer);
  scrollTimer = setTimeout(() => {
    // If a translation is in flight, queue newly-visible items to pick up
    // after it finishes — don't cancel mid-stream.
    if (translationController) return;

    const visibleIds = getVisibleItemIds();
    const pending = displayedItems().filter(shouldTranslateItem);
    const needsWork = pending.filter((item) => visibleIds.has(item.id));
    if (!needsWork.length) return;

    translateBatch(needsWork);
  }, 250);
}

function drainPendingQueue() {
  if (!pendingQueue.length || translationController) return;
  const ids = new Set(pendingQueue);
  pendingQueue = [];
  const items = displayedItems().filter(item => ids.has(item.id) && shouldTranslateItem(item));
  if (items.length) {
    translateBatch(items);
  }
}

function renderSkeleton(count = 4) {
  const fragment = document.createDocumentFragment();
  for (let i = 0; i < count; i++) {
    const skel = document.createElement("div");
    skel.className = "skeleton";
    skel.style.animationDelay = `${i * 0.05}s`;
    skel.innerHTML =
      '<div class="bar meta"></div><div class="bar title"></div><div class="bar summary"></div>';
    fragment.appendChild(skel);
  }
  return fragment;
}

function renderColumnBody(column) {
  if (state.loading && !column.items.length) return renderSkeleton();
  if (!column.items.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "暂无内容";
    return empty;
  }
  const fragment = document.createDocumentFragment();
  column.items.forEach((item) => fragment.append(renderArticle(item)));
  return fragment;
}

// Renders the active group as a horizontal board of per-source columns,
// each independently scrollable. Item order within a column is newest-first.
function renderColumns() {
  const columns = groupColumns();
  els.feed.replaceChildren();
  const fragment = document.createDocumentFragment();
  columns.forEach((column) => {
    const col = document.createElement("section");
    col.className = "column";
    col.dataset.source = column.source;
    col.style.setProperty("--accent", column.accent || "#191b1f");

    const head = document.createElement("div");
    head.className = "column-head";
    head.innerHTML = `<span class="column-dot"></span><span class="column-name">${column.label}</span><b class="column-count">${sourceCount(column.source)}</b>`;

    const list = document.createElement("div");
    list.className = "column-list";
    list.append(renderColumnBody(column));

    col.append(head, list);
    fragment.append(col);
  });
  els.feed.append(fragment);
  restoreSelection();
}

function renderErrors(errors = []) {
  if (!errors.length) {
    els.error.hidden = true;
    els.error.textContent = "";
    return;
  }
  const names = errors.map((error) => SOURCES.find((source) => source.key === error.source)?.label || error.source);
  els.error.hidden = false;
  els.error.textContent = `部分来源暂时不可用：${names.join("、")}`;
}

function addExpandButtons() {
  // Defer until after the browser lays out the new cards so
  // scrollHeight / clientHeight reflect the clamped summary.
  requestAnimationFrame(() => {
    els.feed.querySelectorAll(".story .summary").forEach((summary) => {
      if (!summary.textContent.trim()) return;
      const story = summary.closest(".story");
      if (!story || story.querySelector(".expand-toggle")) return;
      // +1 px tolerance — only show the button when the text
      // genuinely overflows the 2-line clamp.
      if (summary.scrollHeight <= summary.clientHeight + 1) return;

      const btn = document.createElement("button");
      btn.className = "expand-toggle";
      btn.type = "button";
      btn.textContent = "展开";
      btn.addEventListener("click", () => {
        const expanded = story.classList.toggle("expanded");
        btn.textContent = expanded ? "收起" : "展开";
      });
      const links = story.querySelector(".links");
      const discussion = links.querySelector(".discussion");
      if (discussion) {
        links.insertBefore(btn, discussion);
      } else {
        links.appendChild(btn);
      }
    });
  });
}

function render() {
  renderCategoryTabs();
  renderColumns();
  addExpandButtons();
}

async function loadFeed() {
  cancelTranslations();
  state.loading = true;
  state.items = [];
  state.sourceCounts = new Map();
  itemSeq = 0;
  renderColumns();

  try {
    const response = await fetch("/api/feed?source=all", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    if (!response.body) throw new Error("浏览器不支持流式响应");

    const reader = response.body.getReader();
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
            const prepared = (event.items || []).map(item => {
              const p = prepareItem(item, translationCache);
              p._seq = ++itemSeq;
              return p;
            });
            state.items.push(...prepared);
            state.sourceCounts.set(event.key, event.count);
            state.loading = false;
            render();
            startTranslationsForVisibleItems();
          } else if (event.type === "done") {
            renderErrors(event.errors || []);
          }
        } catch { /* skip malformed lines */ }
      }

      if (done) break;
    }

  } catch (error) {
    els.error.hidden = false;
    els.error.textContent = `无法读取 feed：${error.message}`;
  } finally {
    state.loading = false;
    render();
    startTranslationsForVisibleItems();
  }
}

els.theme.addEventListener("click", () => setTheme(state.theme === "dark" ? "light" : "dark"));

// Scrolling now happens inside the per-column lists (vertical) and the
// board itself (horizontal), never on window. scroll events don't bubble
// but do reach the capture phase, so a single capturing listener on the
// board catches every inner scroll.
els.feed.addEventListener("scroll", onScrollTranslate, { capture: true, passive: true });

function columnLists() {
  return [...els.feed.querySelectorAll(".column-list")];
}

const scrollTopBtn = document.createElement("button");
scrollTopBtn.className = "scroll-top";
scrollTopBtn.type = "button";
scrollTopBtn.innerHTML = "&#8593;";
scrollTopBtn.setAttribute("aria-label", "回到顶部");
scrollTopBtn.addEventListener("click", () => {
  columnLists().forEach((list) => list.scrollTo({ top: 0, behavior: "smooth" }));
});
document.body.appendChild(scrollTopBtn);

els.feed.addEventListener("scroll", () => {
  const scrolled = columnLists().some((list) => list.scrollTop > 600);
  scrollTopBtn.classList.toggle("visible", scrolled);
}, { capture: true, passive: true });

let previewTimer = null;
let previewPopup = null;

function removePreview() {
  if (previewTimer) clearTimeout(previewTimer);
  if (previewPopup) {
    previewPopup.remove();
    previewPopup = null;
  }
}

// Hover shows the English original title + summary (only when it differs
// from what's displayed, i.e. for translated items). The original text is
// no longer shown inline under the translated title.
function showOriginal(anchor) {
  removePreview();
  const story = anchor.closest(".story");
  const item = story && findItemById(story.dataset.itemId);
  if (!item) return;

  const origTitle = (item.titleEn || item.titleOriginal || "").trim();
  const origSummary = (item.summaryOriginal || "").trim();
  const hasTitle = origTitle && origTitle !== displayTitle(item).trim();
  const hasSummary = origSummary && origSummary !== displaySummary(item).trim();
  if (!hasTitle && !hasSummary) return;

  previewTimer = setTimeout(() => {
    previewPopup = document.createElement("div");
    previewPopup.className = "preview-popup";
    if (hasTitle) {
      const t = document.createElement("div");
      t.className = "preview-title";
      t.textContent = origTitle;
      previewPopup.appendChild(t);
    }
    if (hasSummary) {
      const s = document.createElement("div");
      s.className = "preview-summary";
      s.textContent = origSummary;
      previewPopup.appendChild(s);
    }
    document.body.appendChild(previewPopup);

    const rect = anchor.getBoundingClientRect();
    previewPopup.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - 396))}px`;
    previewPopup.style.top = `${Math.min(rect.bottom + 6, window.innerHeight - 40)}px`;
  }, 350);
}

els.feed.addEventListener("mouseover", (e) => {
  const anchor = e.target.closest(".title, .summary");
  if (!anchor) {
    removePreview();
    return;
  }
  showOriginal(anchor);
});

els.feed.addEventListener("mouseout", (e) => {
  if (e.target.closest(".title, .summary")) removePreview();
});

els.feed.addEventListener("scroll", removePreview, { capture: true, passive: true });

/* ------------------------------------------------------------------ *
 *  Keyboard navigation (vim-style)
 *
 *  The current selection is tracked by article id (`vim.selectedId`),
 *  never by a cached DOM node or index. This is the key to being
 *  bug-free: the feed is rebuilt on nearly every interaction (filter,
 *  sort, theme, translation), so any node/index reference goes
 *  stale instantly. Resolving the id against the live DOM on each use
 *  keeps navigation correct across every re-render.
 * ------------------------------------------------------------------ */

const vim = {
  selectedId: null,
  pendingG: false,
  gTimer: null,
};

const HEADER_OFFSET = 84;

function feedCards() {
  return [...els.feed.querySelectorAll(".story")];
}

function cardIndexById(cards, id) {
  return id ? cards.findIndex((node) => node.dataset.itemId === id) : -1;
}

function columns() {
  return [...els.feed.querySelectorAll(".column")];
}

function cardsIn(columnEl) {
  return columnEl ? [...columnEl.querySelectorAll(".story")] : [];
}

// The board column that currently has focus: the one holding the selected
// card, or — when nothing is selected — the leftmost column still in view.
function firstVisibleColumn() {
  const viewW = window.innerWidth;
  const cols = columns();
  for (const col of cols) {
    const r = col.getBoundingClientRect();
    if (r.right > 8 && r.left < viewW) return col;
  }
  return cols[0] || null;
}

function focusedColumn() {
  if (vim.selectedId) {
    const node = feedCards().find((n) => n.dataset.itemId === vim.selectedId);
    if (node) return node.closest(".column");
  }
  return firstVisibleColumn();
}

function focusedColumnList() {
  return focusedColumn()?.querySelector(".column-list") || null;
}

// First card in a column whose bottom edge sits below the column's scroll
// viewport top — i.e. the first one actually visible inside that column.
function firstCardInColumn(columnEl) {
  const list = columnEl?.querySelector(".column-list");
  const cards = cardsIn(columnEl);
  if (!list || !cards.length) return null;
  const top = list.getBoundingClientRect().top;
  for (const card of cards) {
    if (card.getBoundingClientRect().bottom > top + 4) return card;
  }
  return cards[cards.length - 1];
}

function paintSelection(node) {
  els.feed.querySelectorAll(".story.selected").forEach((el) => {
    if (el !== node) el.classList.remove("selected");
  });
  if (node) node.classList.add("selected");
}

function clearSelection() {
  vim.selectedId = null;
  paintSelection(null);
}

// Re-apply the selection ring after the feed DOM is rebuilt. If the
// selected article is no longer present (filtered out, source changed),
// the selection is dropped cleanly.
function restoreSelection() {
  if (!vim.selectedId) return;
  const cards = feedCards();
  const idx = cardIndexById(cards, vim.selectedId);
  if (idx === -1) clearSelection();
  else paintSelection(cards[idx]);
}

function selectCard(node, { scroll = true } = {}) {
  if (!node) { clearSelection(); return; }
  vim.selectedId = node.dataset.itemId || null;
  paintSelection(node);
  if (!scroll) return;
  const r = node.getBoundingClientRect();
  const offscreen =
    r.top < HEADER_OFFSET || r.bottom > window.innerHeight - 16 ||
    r.left < 0 || r.right > window.innerWidth;
  // scrollIntoView walks every scrollable ancestor, so this scrolls both
  // the column vertically and the board horizontally as needed.
  if (offscreen) node.scrollIntoView({ block: "center", inline: "nearest", behavior: "smooth" });
}

// j/k move within the focused column only (never jump across columns).
function moveSelection(dir) {
  const col = focusedColumn();
  const cards = cardsIn(col);
  if (!cards.length) return;
  const current = cards.findIndex((n) => n.dataset.itemId === vim.selectedId);
  if (current === -1) { selectCard(firstCardInColumn(col)); return; }
  const next = Math.min(Math.max(current + dir, 0), cards.length - 1);
  selectCard(cards[next]);
}

// h/l (and n/p) switch to an adjacent column, scrolling the board to it.
function switchColumn(dir) {
  const cols = columns();
  if (!cols.length) return;
  let idx = cols.indexOf(focusedColumn());
  if (idx === -1) idx = 0;
  const next = cols[Math.min(Math.max(idx + dir, 0), cols.length - 1)];
  next.scrollIntoView({ inline: "start", block: "nearest", behavior: "smooth" });
  selectCard(firstCardInColumn(next), { scroll: false });
  startTranslationsForVisibleItems();
}

function openSelected() {
  const cards = feedCards();
  const idx = cardIndexById(cards, vim.selectedId);
  if (idx === -1) return;
  const node = cards[idx];
  const link = node.querySelector(".title[href]");
  if (!link || !link.href) return;
  const item = findItemById(vim.selectedId);
  if (item) markRead(item, node);
  window.open(link.href, "_blank", "noopener");
}

function cycleGroup(dir) {
  const idx = SOURCE_GROUPS.findIndex((g) => g.key === state.activeGroup);
  const next = SOURCE_GROUPS[(idx + dir + SOURCE_GROUPS.length) % SOURCE_GROUPS.length];
  setActiveGroup(next.key);
}

function isTypingTarget(node) {
  return !!node && (node.tagName === "INPUT" || node.tagName === "TEXTAREA" || node.isContentEditable);
}

function toggleHelp() {
  const existing = document.querySelector(".kbd-help");
  if (existing) { existing.remove(); return; }
  const rows = [
    ["j / k", "本列下一篇 / 上一篇"],
    ["h / l", "上一列 / 下一列"],
    ["Enter", "打开选中文章"],
    ["1 / 2 / 3", "新闻 / 热点 / 深度"],
    ["[ / ]", "上一组 / 下一组"],
    ["d / u", "本列向下 / 向上半页"],
    ["g g / G", "本列顶部 / 底部"],
    ["t", "明暗主题"],
    ["r", "刷新"],
    ["Esc", "取消选中 / 关闭"],
    ["?", "显示 / 隐藏帮助"],
  ];
  const overlay = document.createElement("div");
  overlay.className = "kbd-help";
  overlay.innerHTML =
    `<div class="kbd-card">` +
    `<div class="kbd-title">键盘快捷键</div>` +
    rows.map((r) => `<div class="kbd-row"><kbd>${r[0]}</kbd><span>${r[1]}</span></div>`).join("") +
    `</div>`;
  overlay.addEventListener("click", () => overlay.remove());
  document.body.appendChild(overlay);
}

function handleVimKey(e) {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key;

  // Escape blurs any focused input, closes popups, and clears selection.
  if (k === "Escape") {
    if (isTypingTarget(e.target)) e.target.blur();
    removePreview();
    document.querySelector(".kbd-help")?.remove();
    clearSelection();
    return;
  }

  if (isTypingTarget(e.target)) return;

  // A pending `g` only survives until the next keypress: anything other
  // than a second `g` cancels it, so `gg` is the only multi-key chord.
  if (vim.pendingG && k !== "g") {
    vim.pendingG = false;
    clearTimeout(vim.gTimer);
  }

  switch (k) {
    case "?":

      e.preventDefault();
      toggleHelp();
      break;
    case "Enter":
      e.preventDefault();
      openSelected();
      break;
    case "j":
    case "J":
      e.preventDefault();
      moveSelection(1);
      break;
    case "k":
    case "K":
      e.preventDefault();
      moveSelection(-1);
      break;
    case "h":
    case "H":
    case "p":
    case "P":
      e.preventDefault();
      switchColumn(-1);
      break;
    case "l":
    case "L":
    case "n":
    case "N":
      e.preventDefault();
      switchColumn(1);
      break;
    case "[":
      e.preventDefault();
      cycleGroup(-1);
      break;
    case "]":
      e.preventDefault();
      cycleGroup(1);
      break;
    case "d":
      e.preventDefault();
      focusedColumnList()?.scrollBy({ top: window.innerHeight * 0.5, behavior: "smooth" });
      break;
    case "u":
      e.preventDefault();
      focusedColumnList()?.scrollBy({ top: -window.innerHeight * 0.5, behavior: "smooth" });
      break;
    case "G":
      e.preventDefault();
      {
        const col = focusedColumn();
        const list = col?.querySelector(".column-list");
        const cards = cardsIn(col);
        if (list) list.scrollTo({ top: list.scrollHeight, behavior: "smooth" });
        if (cards.length) selectCard(cards[cards.length - 1], { scroll: false });
      }
      break;
    case "g":
      e.preventDefault();
      if (vim.pendingG) {
        vim.pendingG = false;
        clearTimeout(vim.gTimer);
        const col = focusedColumn();
        const list = col?.querySelector(".column-list");
        const cards = cardsIn(col);
        if (list) list.scrollTo({ top: 0, behavior: "smooth" });
        if (cards.length) selectCard(cards[0], { scroll: false });
      } else {
        vim.pendingG = true;
        clearTimeout(vim.gTimer);
        vim.gTimer = setTimeout(() => { vim.pendingG = false; }, 500);
      }
      break;
    case "r":
      e.preventDefault();
      loadFeed();
      break;
    case "t":
      e.preventDefault();
      setTheme(state.theme === "dark" ? "light" : "dark");
      break;
    case "1":
      e.preventDefault();
      setActiveGroup("news");
      break;
    case "2":
      e.preventDefault();
      setActiveGroup("hot");
      break;
    case "3":
      e.preventDefault();
      setActiveGroup("analysis");
      break;
    default:
      break;
  }
}

document.addEventListener("keydown", handleVimKey);

setTheme(state.theme);
loadFeed();
