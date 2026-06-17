// =========================================================================
// ui.js — DOM rendering, keyboard navigation, modals & interaction
// =========================================================================

import {
  state, SOURCES, SOURCE_GROUPS,
  toText, formatRelativeTime, isLiveTitle, escapeHtml,
  activeGroupSources, sourceCount, setActiveGroup,
  findItemById, markRead,
  groupColumns, displayedItems,
} from './core.js';

import {
  loadFeed,
  setFeedStateHandler,
  summaryState,
  startSummaryFetch,
  regenerateSummary,
  setSummaryRefreshHandler,
} from './api.js';

// =========================================================================
// DOM references (lazy — resolved after DOM ready)
// =========================================================================

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

let els = {};
function cacheElements() {
  els = {
    categoryTabs:  $("#categoryTabs"),
    feed:           $("#feed"),
    error:          $("#errorBox"),
    theme:          $("#themeButton"),
    template:       $("#articleTemplate"),
    summaryButton:  $("#summaryButton"),
  };
}

// =========================================================================
// Theme
// =========================================================================

export function setTheme(theme) {
  state.theme = theme === "dark" ? "dark" : "light";
  localStorage.setItem("themeMode", state.theme);
  document.body.classList.toggle("theme-dark", state.theme === "dark");
  const span = els.theme.querySelector("span");
  if (span) {
    span.textContent = state.theme === "dark" ? "☀" : "☾";
  }
  const label = state.theme === "dark" ? "切换日间模式" : "切换夜间模式";
  els.theme.setAttribute("aria-label", label);
  els.theme.title = label;
}

// =========================================================================
// Rendering: Category tabs
// =========================================================================

function renderCategoryTabs() {
  els.categoryTabs.replaceChildren();
  SOURCE_GROUPS.forEach((group) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "category-tab";
    btn.classList.toggle("active", state.activeGroup === group.key);
    btn.innerHTML = `<span>${group.label}</span>`;
    btn.addEventListener("click", () => {
      setActiveGroup(group.key);
      resetFeedScroll();
      render();
    });
    els.categoryTabs.append(btn);
  });
}

// =========================================================================
// Rendering: Article cards
// =========================================================================

function renderArticle(item) {
  const node   = els.template.content.firstElementChild.cloneNode(true);
  const mainUrl   = item.url || item.discussionUrl || "#";
  const hasImage  = state.withImages && Boolean(item.image);
  const sourceKey = item.source || "";

  node.dataset.itemId = item.id || "";
  if (sourceKey) node.classList.add(`story-${sourceKey}`);
  node.classList.toggle("has-image",  hasImage);
  node.classList.toggle("read",       state.readIds.has(item.id));
  node.style.setProperty("--source-color", item.accent || "#191b1f");

  // --- Media (image) ---
  const media = node.querySelector(".media");
  const img   = node.querySelector("img");
  if (hasImage) {
    media.href = mainUrl;
    media.addEventListener("click", () => tryMarkRead(item, node));
    img.src = item.image;
    img.alt = toText(item.title || item.summary || "");
    img.onerror = () => {
      img.remove();
      const err = document.createElement("div");
      err.className = "media-error";
      err.textContent = "无图";
      media.appendChild(err);
    };
  } else {
    media.remove();
    // Lazy-load og:image for items without a feed image but with a real article URL.
    // Skip Google News: its pages are JS SPAs with a shared generic og:image.
    if (item.url && item.url.startsWith("http") && !item.url.includes("news.google.com")) {
      scheduleLazyImage(node, item.url);
    }
  }

  // --- Time (rendered in the links row) ---
  const time = node.querySelector("time");
  time.textContent = formatRelativeTime(item.publishedAt);
  if (item.publishedAt) time.dateTime = item.publishedAt;

  // --- Title ---
  const title = node.querySelector(".title");
  title.href = mainUrl;
  title.textContent = toText(item.title || item.summary || "Untitled");
  if (isLiveTitle(item.title || "")) {
    const badge = document.createElement("span");
    badge.className = "live-badge";
    badge.textContent = "LIVE";
    title.appendChild(badge);
  }
  title.addEventListener("click", () => tryMarkRead(item, node));

  // --- Summary ---
  const summary = node.querySelector(".summary");
  const summaryText = item.summary || "";
  summary.textContent = toText(summaryText);
  summary.hidden = !summaryText;

  // --- Links row ---
  const links = node.querySelector(".links");

  // Remove template's expand-toggle (re-added later by addExpandButtons)
  node.querySelector(".expand-toggle")?.remove();

  // --- Source-specific features ---
  buildSourceFeatures(node, item, sourceKey, mainUrl, links);

  // --- Discussion link ---
  const discussion = node.querySelector(".discussion");
  if (item.discussionUrl?.startsWith("http") && item.discussionUrl !== mainUrl && sourceKey !== "hn") {
    discussion.href = item.discussionUrl;
    discussion.addEventListener("click", () => tryMarkRead(item, node));
  } else {
    discussion.remove();
  }

  // --- Move time into links row ---
  const timeEl = node.querySelector("time");
  if (timeEl) {
    timeEl.classList.add("card-time");
    if (sourceKey === "hn") {
      const hnStats = node.querySelector(".card-stats");
      (hnStats || links).insertBefore(timeEl, (hnStats || links).firstChild);
    } else {
      links.insertBefore(timeEl, links.firstChild);
    }
  }

  return node;
}

function tryMarkRead(item, node) {
  if (markRead(item)) {
    node.classList.add("read");
  }
}

function buildSourceFeatures(node, item, sourceKey, mainUrl, links) {
  // --- HN: points + comments badges ---
  if (sourceKey === "hn") {
    const statsEl = document.createElement("div");
    statsEl.className = "card-stats";

    const badgeGroup = document.createElement("span");
    badgeGroup.className = "hn-badges";

    const score    = Number.isFinite(Number(item.score))    ? Number(item.score)    : null;
    const comments = Number.isFinite(Number(item.comments)) ? Number(item.comments) : null;
    const discUrl  = item.discussionUrl || mainUrl;

    if (score !== null) {
      const pts = document.createElement("span");
      pts.className = "stat-badge points";
      pts.textContent = `▲ ${score}`;
      badgeGroup.appendChild(pts);
    }
    if (comments !== null) {
      const comm = document.createElement("a");
      comm.className = "stat-badge comments";
      comm.href = discUrl;
      comm.target = "_blank";
      comm.rel = "noreferrer";
      comm.textContent = `💬 ${comments}`;
      comm.addEventListener("click", () => tryMarkRead(item, node));
      badgeGroup.appendChild(comm);
    }

    if (badgeGroup.children.length) {
      statsEl.appendChild(badgeGroup);
    }

    if (statsEl.children.length) {
      links.insertAdjacentElement("beforebegin", statsEl);
    }
  }

  // --- Zhihu: heat badge ---
  if (sourceKey === "zhihu" && item.score > 0) {
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

  // --- Google News: publisher badge ---
  if (sourceKey === "google" || sourceKey === "google_zh") {
    const publisher = (item.summary || "").trim();
    if (publisher && publisher.length < 40) {
      const badge = document.createElement("span");
      badge.className = "publisher-badge";
      badge.textContent = publisher;
      links.appendChild(badge);
    }
  }
}

// =========================================================================
// Lazy preview images (og:image)
// =========================================================================

// Cache — avoid re-fetching the same article URL
const lazyImageCache = new Map();

// IntersectionObserver: loads og:image when a card nears the viewport
let lazyImageObserver = null;

function ensureLazyImageObserver() {
  if (lazyImageObserver) return;
  lazyImageObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (!entry.isIntersecting) return;
      const node = entry.target;
      lazyImageObserver.unobserve(node);
      const url = node.dataset.lazyImageUrl;
      if (!url) return;
      loadLazyImage(node, url);
    });
  }, { rootMargin: "400px" });
}

function scheduleLazyImage(node, articleUrl) {
  if (!articleUrl || lazyImageCache.has(articleUrl)) {
    if (lazyImageCache.has(articleUrl)) {
      const cached = lazyImageCache.get(articleUrl);
      if (cached) applyLazyImage(node, cached);
    }
    return;
  }
  ensureLazyImageObserver();
  node.dataset.lazyImageUrl = articleUrl;
  lazyImageObserver.observe(node);
}

async function loadLazyImage(node, articleUrl) {
  if (lazyImageCache.has(articleUrl)) {
    const cached = lazyImageCache.get(articleUrl);
    if (cached) applyLazyImage(node, cached);
    return;
  }
  try {
    const resp = await fetch(`/api/preview-image?url=${encodeURIComponent(articleUrl)}`);
    if (!resp.ok) { lazyImageCache.set(articleUrl, null); return; }
    const data = await resp.json();
    const img = data.image || "";
    lazyImageCache.set(articleUrl, img || null);
    if (img) applyLazyImage(node, img);
  } catch {
    lazyImageCache.set(articleUrl, null);
  }
}

function applyLazyImage(node, imageUrl) {
  let media = node.querySelector(".media");
  if (!media) {
    media = document.createElement("a");
    media.className = "media";
    media.target = "_blank";
    media.rel = "noreferrer";
    const titleLink = node.querySelector(".title[href]");
    media.href = titleLink?.href || "#";
    media.addEventListener("click", () => {
      const item = findItemById(node.dataset.itemId);
      if (item) tryMarkRead(item, node);
    });
    node.insertBefore(media, node.firstChild);
  }

  let img = media.querySelector("img");
  if (!img) {
    img = document.createElement("img");
    img.alt = "";
    img.loading = "lazy";
    media.appendChild(img);
  }
  const item = findItemById(node.dataset.itemId);
  img.alt = toText(item?.title || item?.summary || "");
  img.src = imageUrl;
  img.onerror = () => {
    img.remove();
    const err = document.createElement("div");
    err.className = "media-error";
    err.textContent = "无图";
    media.appendChild(err);
  };

  node.classList.add("has-image");
  node.classList.add("lazy-image-loaded");
}

// =========================================================================
// Rendering: Columns & skeletons
// =========================================================================

function renderColumnBody(column) {
  if (!column.items.length) {
    const frag = document.createDocumentFragment();
    return frag;
  }
  const frag = document.createDocumentFragment();
  column.items.forEach((item) => frag.append(renderArticle(item)));
  return frag;
}

function renderColumns() {
  const columns = groupColumns();
  els.feed.replaceChildren();
  const frag = document.createDocumentFragment();

  columns.forEach((col) => {
    const columnEl = document.createElement("section");
    columnEl.className = "column";
    columnEl.dataset.source = col.source;
    columnEl.style.setProperty("--accent", col.accent || "#191b1f");

    const head = document.createElement("div");
    head.className = "column-head";
    head.innerHTML = [
      '<span class="column-dot"></span>',
      `<span class="column-name">${col.label}</span>`,
      `<b class="column-count">${sourceCount(col.source)}</b>`,
    ].join("");

    const list = document.createElement("div");
    list.className = "column-list";
    list.append(renderColumnBody(col));

    columnEl.append(head, list);
    frag.append(columnEl);
  });

  els.feed.append(frag);
  restoreSelection();
}

function renderErrors(errors = []) {
  if (!errors.length) {
    els.error.hidden = true;
    els.error.textContent = "";
    return;
  }
  const names = errors.map((e) => SOURCES.find((s) => s.key === e.source)?.label || e.source);
  els.error.hidden = false;
  els.error.textContent = `部分来源暂时不可用：${names.join("、")}`;
}

// =========================================================================
// Expand buttons (placed after layout so we can measure clamp overflow)
// =========================================================================

function addExpandButtons() {
  requestAnimationFrame(() => {
    $$(".story .summary").forEach((summary) => {
      if (!summary.textContent.trim()) return;
      const story = summary.closest(".story");
      if (!story || story.querySelector(".expand-toggle")) return;
      if (summary.scrollHeight <= summary.clientHeight + 1) return;

      const btn = document.createElement("button");
      btn.className = "expand-toggle";
      btn.type = "button";
      btn.textContent = "展开";
      btn.addEventListener("click", () => {
        const expanded = story.classList.toggle("expanded");
        btn.textContent = expanded ? "收起" : "展开";
      });

      // Zhihu: expand in card-stats row
      if (story.classList.contains("story-zhihu")) {
        const stats = story.querySelector(".card-stats");
        if (stats) { stats.appendChild(btn); return; }
      }

      const links = story.querySelector(".links");
      const disc  = links?.querySelector(".discussion");
      if (disc) links.insertBefore(btn, disc);
      else links?.appendChild(btn);
    });
  });
}

// =========================================================================
// Master render
// =========================================================================

export function render() {
  renderCategoryTabs();
  renderColumns();
  addExpandButtons();
}

// =========================================================================
// Scroll-to-top button
// =========================================================================

function initScrollTop() {
  const btn = document.createElement("button");
  btn.className = "scroll-top";
  btn.type = "button";
  btn.innerHTML = "&#8593;";
  btn.setAttribute("aria-label", "回到顶部");
  btn.addEventListener("click", () => {
    $$(".column-list").forEach((list) => list.scrollTo({ top: 0, behavior: "smooth" }));
  });
  document.body.appendChild(btn);

  els.feed.addEventListener("scroll", () => {
    const scrolled = $$(".column-list").some((list) => list.scrollTop > 600);
    btn.classList.toggle("visible", scrolled);
  }, { capture: true, passive: true });
}

// =========================================================================
// Scroll helpers
// =========================================================================

function resetFeedScroll() {
  els.feed.scrollLeft = 0;
  $$(".column-list").forEach((list) => { list.scrollTop = 0; });
}

// =========================================================================
// AI Summary modal
// =========================================================================

// Focus management for overlay dialogs (a11y: focus move-in, trap, restore)
const focusStack = [];

function trapFocus(e) {
  if (e.key !== "Tab") return;
  const overlay = e.currentTarget;
  const f = [...overlay.querySelectorAll(
    'a[href],button:not([disabled]),input:not([disabled]),[tabindex]:not([tabindex="-1"])'
  )].filter((el) => el.offsetParent !== null);
  if (!f.length) return;
  const first = f[0];
  const last  = f[f.length - 1];
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault();
    last.focus();
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault();
    first.focus();
  }
}

function mountOverlay(overlay) {
  focusStack.push(document.activeElement);
  overlay.tabIndex = -1;
  overlay.addEventListener("keydown", trapFocus);
}

function unmountOverlay(overlay) {
  overlay.removeEventListener("keydown", trapFocus);
  const prev = focusStack.pop();
  if (prev && typeof prev.focus === "function") {
    try { prev.focus(); } catch { /* ignore */ }
  }
}

function dismissSummaryModal() {
  if (summaryState.modal) {
    unmountOverlay(summaryState.modal);
    summaryState.modal.remove();
    summaryState.modal = null;
  }
}

function buildSummaryBody() {
  if (summaryState.error) {
    return `<div class="summary-text summary-error">${summaryState.error}</div>`;
  }
  if (summaryState.loading) {
    const partial = summaryState.text || "";
    return partial
      ? `<div class="summary-text streaming">${escapeHtml(partial).replace(/\n/g, '<br>')}<span class="summary-cursor">|</span></div>`
      : `<div class="summary-loading">
             <span class="summary-spinner"></span>
             <span>正在生成总结...</span>
           </div>
           <div class="summary-skeleton">
             <div class="summary-sk-line"></div>
             <div class="summary-sk-line short"></div>
             <div class="summary-sk-line"></div>
             <div class="summary-sk-line short"></div>
             <div class="summary-sk-line medium"></div>
           </div>`;
  }
  if (summaryState.text) {
    const { toc, html } = parseSummary(summaryState.text);
    const nav = toc.length > 1
      ? `<nav class="summary-toc" aria-label="板块导航">${toc.map((s) =>
          `<button class="toc-chip" type="button" data-target="${s.id}">${s.label}</button>`
        ).join("")}</nav>`
      : "";
    return `${nav}<div class="summary-text">${html}</div>`;
  }
  return '<div class="summary-text">当前没有可总结的内容。</div>';
}

// Parse the streamed markdown-ish text into section blocks.
// Returns { toc: [{id,label}], html: string }.
function parseSummary(text) {
  let html = escapeHtml(text);

  // Citations: [0] [1][2] -> inline badges
  html = html.replace(/\[(\d+)\]/g, (_m, num) => {
    const src = summaryState.sources[num];
    if (!src?.url) return `[${num}]`;
    return `<a class="cite-badge" href="${escapeHtml(src.url)}" target="_blank" rel="noreferrer" style="--cite-color:${escapeHtml(src.accent)}" title="${escapeHtml(src.label)}">${escapeHtml(src.short)}</a>`;
  });

  // Cluster consecutive badges
  html = html.replace(/((?:<a class="cite-badge"[^>]*>.*?<\/a>[^\S\n]*)+)/g, '<span class="cite-cluster">$1</span>');

  // Bold (**heading**)
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

  // Sections split by double-newline
  const sections = html.split(/\n\n+/);
  const toc = [];
  const blocks = sections.map((section, i) => {
    section = section.trim();
    if (!section) return "";

    const lines = section.split(/\n/);
    const heading = lines[0].trim();
    const bodyLines = lines.slice(1);
    const id = `sum-sec-${i}`;
    if (heading) toc.push({ id, label: heading.replace(/<[^>]+>/g, "") });

    if (!bodyLines.length) {
      return `<div class="summary-section" id="${id}">${heading}</div>`;
    }

    // Bullet lines ("- "/"• ") become <li>; other lines become <p> (e.g. Leaders analysis).
    let body = "";
    let bullets = [];
    const flush = () => {
      if (bullets.length) { body += `<ul>${bullets.join("")}</ul>`; bullets = []; }
    };
    for (const line of bodyLines) {
      const t = line.trim();
      if (!t) continue;
      if (/^[-•]\s*/.test(t)) {
        bullets.push(`<li>${t.replace(/^[-•]\s*/, "")}</li>`);
      } else {
        flush();
        body += `<p>${t}</p>`;
      }
    }
    flush();

    return `<div class="summary-section" id="${id}">${heading}${body}</div>`;
  });

  return { toc, html: blocks.filter(Boolean).join("") };
}

function renderSummaryMarkdown(text) {
  return parseSummary(text).html;
}

function refreshModalBody() {
  if (!summaryState.modal) return;
  const body = summaryState.modal.querySelector(".summary-card-body");
  if (body) body.innerHTML = buildSummaryBody();

  const title = summaryState.modal.querySelector(".summary-title");
  if (title) {
    if (summaryState.loading) {
      title.innerHTML = '<span class="summary-spinner"></span> AI 正在生成今日要闻总结...';
    } else if (summaryState.error) {
      title.textContent = '⚠️ 总结生成失败';
    } else {
      title.textContent = '✨ AI 今日要闻总结';
    }
  }

  const copy  = summaryState.modal.querySelector("#summaryCopy");
  const regen = summaryState.modal.querySelector("#summaryRegen");
  if (copy)  copy.disabled  = summaryState.loading || !summaryState.text;
  if (regen) regen.disabled = summaryState.loading;
}

function buildSummaryModal() {
  dismissSummaryModal();

  const modal = document.createElement("div");
  modal.className = "summary-overlay";
  modal.setAttribute("role", "dialog");
  modal.setAttribute("aria-modal", "true");
  modal.setAttribute("aria-labelledby", "summary-title");
  summaryState.modal = modal;

  const statusIcon = summaryState.loading
    ? '<span class="summary-spinner"></span>'
    : summaryState.error ? '⚠️' : '✨';

  const headerText = summaryState.loading
    ? 'AI 正在生成今日要闻总结...'
    : summaryState.error ? '总结生成失败' : 'AI 今日要闻总结';

  modal.innerHTML = `
    <div class="summary-card">
      <div class="summary-card-header">
        <span class="summary-title" id="summary-title">${statusIcon} ${headerText}</span>
        <div class="summary-actions">
          <button class="summary-action" id="summaryCopy" type="button" aria-label="复制总结" title="复制">⧉</button>
          <button class="summary-action" id="summaryRegen" type="button" aria-label="重新生成" title="重新生成">↻</button>
          <button class="summary-close" type="button" aria-label="关闭">✕</button>
        </div>
      </div>
      <div class="summary-card-body">${buildSummaryBody()}</div>
    </div>`;

  modal.querySelector(".summary-close").addEventListener("click", dismissSummaryModal);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) dismissSummaryModal();
  });

  // Copy / regenerate actions
  const copyBtn = modal.querySelector("#summaryCopy");
  copyBtn.addEventListener("click", async () => {
    const text = summaryState.text || "";
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      copyBtn.classList.add("copied");
      copyBtn.title = "已复制";
      setTimeout(() => { copyBtn.classList.remove("copied"); copyBtn.title = "复制"; }, 1200);
    } catch { /* clipboard unavailable */ }
  });
  const regenBtn = modal.querySelector("#summaryRegen");
  regenBtn.addEventListener("click", () => {
    if (!summaryState.loading) regenerateSummary();
  });

  // TOC chip clicks (delegated) -> scroll to section
  const body = modal.querySelector(".summary-card-body");
  body.addEventListener("click", (e) => {
    const chip = e.target.closest(".toc-chip");
    if (!chip) return;
    const target = body.querySelector(`#${chip.dataset.target}`);
    target?.scrollIntoView({ block: "start", behavior: "smooth" });
  });

  document.body.appendChild(modal);
  mountOverlay(modal);
  modal.querySelector(".summary-close").focus();

  // Sync action-button disabled states
  refreshModalBody();

  // Auto-scroll while streaming
  if (summaryState.loading) {
    const observer = new MutationObserver(() => { body.scrollTop = body.scrollHeight; });
    observer.observe(body, { childList: true, characterData: true, subtree: true });
    const check = setInterval(() => {
      if (!summaryState.loading || !summaryState.modal) {
        observer.disconnect();
        clearInterval(check);
      }
    }, 500);
  }

  return modal;
}

function openSummaryModal() {
  buildSummaryModal();
}

function onSummaryClick() {
  if (!summaryState.loading && !summaryState.text) {
    startSummaryFetch();
  }
  openSummaryModal();
}

function updateSummaryButton() {
  const btn = els.summaryButton;
  btn.classList.toggle("summary-loading", summaryState.loading);
  btn.classList.toggle("summary-done", !summaryState.loading && !!summaryState.text);
  if (summaryState.loading) {
    btn.setAttribute("aria-label", "AI 总结生成中...");
    btn.title = "AI 总结生成中...";
  } else if (summaryState.text) {
    btn.setAttribute("aria-label", "AI 今日要闻总结（已完成）");
    btn.title = "AI 今日要闻总结（已完成）";
  } else {
    btn.setAttribute("aria-label", "AI 总结今日要闻");
    btn.title = "AI 总结今日要闻";
  }
}

// =========================================================================
// Keyboard navigation (vim-style)
// =========================================================================

const vim = { selectedId: null, pendingG: false, gTimer: null };
const HEADER_OFFSET = 84;

function feedCards()     { return $$(".story"); }
function columnEls()     { return $$(".column"); }
function cardsIn(col)    { return col ? [...col.querySelectorAll(".story")] : []; }

function cardIndexById(cards, id) {
  return id ? cards.findIndex((n) => n.dataset.itemId === id) : -1;
}

function firstVisibleColumn() {
  const vW = window.innerWidth;
  for (const col of columnEls()) {
    const r = col.getBoundingClientRect();
    if (r.right > 8 && r.left < vW) return col;
  }
  return columnEls()[0] || null;
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

function firstCardInColumn(col) {
  const list  = col?.querySelector(".column-list");
  const cards = cardsIn(col);
  if (!list || !cards.length) return null;
  const top = list.getBoundingClientRect().top;
  for (const card of cards) {
    if (card.getBoundingClientRect().bottom > top + 4) return card;
  }
  return cards[cards.length - 1];
}

function paintSelection(node) {
  $$(".story.selected").forEach((el) => { if (el !== node) el.classList.remove("selected"); });
  if (node) node.classList.add("selected");
}

function clearSelection() {
  vim.selectedId = null;
  paintSelection(null);
}

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
  const offscreen = r.top < HEADER_OFFSET || r.bottom > window.innerHeight - 16 ||
                    r.left < 0 || r.right > window.innerWidth;
  if (offscreen) node.scrollIntoView({ block: "center", inline: "nearest", behavior: "smooth" });
}

function moveSelection(dir) {
  const col   = focusedColumn();
  const cards = cardsIn(col);
  if (!cards.length) return;
  const current = cards.findIndex((n) => n.dataset.itemId === vim.selectedId);
  if (current === -1) { selectCard(firstCardInColumn(col)); return; }
  selectCard(cards[Math.min(Math.max(current + dir, 0), cards.length - 1)]);
}

function switchColumn(dir) {
  const cols = columnEls();
  if (!cols.length) return;
  let idx = cols.indexOf(focusedColumn());
  if (idx === -1) idx = 0;
  const next = cols[Math.min(Math.max(idx + dir, 0), cols.length - 1)];
  next.scrollIntoView({ inline: "start", block: "nearest", behavior: "smooth" });
  selectCard(firstCardInColumn(next), { scroll: false });
}

function openSelected() {
  const cards = feedCards();
  const idx = cardIndexById(cards, vim.selectedId);
  if (idx === -1) return;
  const node = cards[idx];
  const link = node.querySelector(".title[href]");
  if (!link?.href) return;
  const item = findItemById(vim.selectedId);
  if (item) tryMarkRead(item, node);
  const a = document.createElement("a");
  a.href = link.href;
  a.target = "_blank";
  a.rel = "noreferrer";
  a.click();
}

function cycleGroup(dir) {
  const idx = SOURCE_GROUPS.findIndex((g) => g.key === state.activeGroup);
  const next = SOURCE_GROUPS[(idx + dir + SOURCE_GROUPS.length) % SOURCE_GROUPS.length];
  setActiveGroup(next.key);
  resetFeedScroll();
  render();
}

function isTypingTarget(el) {
  return !!el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable);
}

function toggleHelp() {
  const existing = document.querySelector(".kbd-help");
  if (existing) { unmountOverlay(existing); existing.remove(); return; }
  const rows = [
    ["j / k", "本列下一篇 / 上一篇"], ["h / l", "上一列 / 下一列"],
    ["Enter", "打开选中文章"], ["1 / 2 / 3", "新闻 / 热点 / 深度"],
    ["[ / ]", "上一组 / 下一组"], ["d / u", "本列向下 / 向上半页"],
    ["g g / G", "本列顶部 / 底部"], ["t", "明暗主题"],
    ["r", "刷新"], ["Esc", "取消选中 / 关闭"], ["?", "显示 / 隐藏帮助"],
  ];
  const overlay = document.createElement("div");
  overlay.className = "kbd-help";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-labelledby", "kbd-title");
  overlay.innerHTML =
    '<div class="kbd-card">' +
    '<div class="kbd-title" id="kbd-title">键盘快捷键</div>' +
    rows.map((r) => `<div class="kbd-row"><kbd>${r[0]}</kbd><span>${r[1]}</span></div>`).join("") +
    '</div>';
  overlay.addEventListener("click", (e) => { if (e.target === overlay) { unmountOverlay(overlay); overlay.remove(); } });
  document.body.appendChild(overlay);
  mountOverlay(overlay);
  overlay.focus();
}

function handleVimKey(e) {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key;

  if (k === "Escape") {
    if (isTypingTarget(e.target)) e.target.blur();
    document.querySelector(".kbd-help")?.remove();
    dismissSummaryModal();
    clearSelection();
    return;
  }

  if (isTypingTarget(e.target)) return;

  if (vim.pendingG && k !== "g") {
    vim.pendingG = false;
    clearTimeout(vim.gTimer);
  }

  switch (k) {
    case "?":  e.preventDefault(); toggleHelp(); break;
    case "Enter": e.preventDefault(); openSelected(); break;
    case "j": case "J": e.preventDefault(); moveSelection(1); break;
    case "k": case "K": e.preventDefault(); moveSelection(-1); break;
    case "h": case "H": case "p": case "P": e.preventDefault(); switchColumn(-1); break;
    case "l": case "L": case "n": case "N": e.preventDefault(); switchColumn(1); break;
    case "[": e.preventDefault(); cycleGroup(-1); break;
    case "]": e.preventDefault(); cycleGroup(1); break;
    case "d": e.preventDefault(); focusedColumnList()?.scrollBy({ top: window.innerHeight * 0.5, behavior: "smooth" }); break;
    case "u": e.preventDefault(); focusedColumnList()?.scrollBy({ top: -window.innerHeight * 0.5, behavior: "smooth" }); break;
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
    case "r": e.preventDefault(); loadFeed(); break;
    case "t": e.preventDefault(); setTheme(state.theme === "dark" ? "light" : "dark"); break;
    case "1": e.preventDefault(); setActiveGroup("news"); resetFeedScroll(); render(); break;
    case "2": e.preventDefault(); setActiveGroup("hot"); resetFeedScroll(); render(); break;
    case "3": e.preventDefault(); setActiveGroup("analysis"); resetFeedScroll(); render(); break;
  }
}

// =========================================================================
// Wiring: connect api.js callbacks to ui.js functions
// =========================================================================

function setupApiBridge() {
  // Feed state changes
  setFeedStateHandler((action, payload) => {
    switch (action) {
      case "loading": renderColumns(); break;
      case "render":  render(); resetFeedScroll(); break;
      case "errors":  renderErrors(payload); break;
      case "error":   els.error.hidden = false; els.error.textContent = `无法读取 feed：${payload}`; break;
    }
  });

  // Summary refresh handler
  setSummaryRefreshHandler((action) => {
    switch (action) {
      case "button": updateSummaryButton(); break;
      case "modal":  refreshModalBody(); break;
      case "flash":
        els.summaryButton.classList.add("summary-flash");
        setTimeout(() => els.summaryButton.classList.remove("summary-flash"), 1200);
        break;
    }
  });
}

// =========================================================================
// Event binding
// =========================================================================

function bindEvents() {
  // Theme
  els.theme.addEventListener("click", () =>
    setTheme(state.theme === "dark" ? "light" : "dark"));

  // AI Summary button
  els.summaryButton.addEventListener("click", onSummaryClick);

  // Keyboard
  document.addEventListener("keydown", handleVimKey);

  // Escape key also closes summary modal
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && summaryState.modal) {
      dismissSummaryModal();
    }
  });
}

// =========================================================================
// Initialization
// =========================================================================

export function init() {
  cacheElements();
  setupApiBridge();
  bindEvents();
  initScrollTop();
  setTheme(state.theme);
  loadFeed();
}
