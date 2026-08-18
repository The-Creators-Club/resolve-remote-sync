"use strict";

/* ==========================================================================
   B-Roll Platform frontend. Vanilla JS, no build step, no frameworks.
   ========================================================================== */

const COMPANION_URL = "http://127.0.0.1:8899";

// Fixed vocabulary from schema.sql's quality_flags CHECK constraint / SPEC.md.
const QUALITY_FLAGS = [
  "shaky",
  "soft_focus",
  "overexposed",
  "underexposed",
  "noisy",
  "rolling_shutter",
];

// The sprite-sheet constants and geometry helpers (SPRITE_*, spriteGeometry,
// positionSprite, wireSpriteScrub) live in sprite.js since 2026-08-18: the
// client-folder viewer page (share.js) hover-scrubs the same sheets and must
// read them with the same arithmetic. index.html loads sprite.js first.
const SHUTTLE_RATES = [1, 2, 4, 8];

/* ---------------------------------------------------------------------- */
/* State                                                                   */
/* ---------------------------------------------------------------------- */

const SEARCH_MODES = ["hybrid", "keyword", "semantic"];
const SEARCH_SOURCES = ["all", "visual", "transcript"];

// The own-footage collection's slug. SITE DATA since 2026-08-17 (the server's
// BROLL_DEFAULT_COLLECTION -- docs/COMMERCIAL_READINESS.md item 4): it was the
// literal "creators_club", one customer's name, in this file and in every
// search URL. It is LEARNED from /api/tree, which names each root, so no
// spelling of it is compiled in here -- "downloads" is the only slug the
// product itself owns, and the other root is whatever this site calls it.
const COLLECTION_DOWNLOADS = "downloads";
let ownedCollection = "";

function isOwnedCollection(slug) {
  return !!slug && slug !== COLLECTION_DOWNLOADS && slug === ownedCollection;
}

function learnCollections(tree) {
  const owned = (tree || []).find((r) => r.collection !== COLLECTION_DOWNLOADS);
  if (owned) ownedCollection = owned.collection;
}

const state = {
  q: "",
  category: "",
  collection: "", // "" | "downloads" | <the own-footage slug> -- the tree root
  // `<share>::<rel/prefix>` from a clicked path crumb in the detail panel.
  // Independent of `category`/`collection`, which are the folder TREE's own
  // pair: the tree browses own-footage shoots by slug and downloads by
  // subject, so neither can express "this folder of this downloads share".
  path: "",
  tree: [],
  hiddenFlags: new Set(),
  mode: "hybrid", // "hybrid" | "keyword" | "semantic"
  sources: "all", // "all" | "visual" | "transcript"
  fuzzy: true,
  limit: 24,
  offset: 0,
  total: 0,
  lastResults: [],
  detail: null, // {video, segments, transcript, themes, quality_flags}
  detailHits: [], // search hits carried into the detail view (yellow seekbar bands)
  detailSeekTo: null, // seconds the detail view was opened at (kept in the URL)
  gridScrollY: 0, // scroll position to restore when leaving the detail view
  inPoint: null, // seconds
  outPoint: null, // seconds
  shuttleDir: 0, // -1, 0, +1
  shuttleRateIdx: 0,
  shuttleTimer: null,
};

/* ---------------------------------------------------------------------- */
/* Small utilities                                                        */
/* ---------------------------------------------------------------------- */

function $(sel) {
  return document.querySelector(sel);
}

function el(tag, opts) {
  const node = document.createElement(tag);
  if (opts) {
    if (opts.className) node.className = opts.className;
    if (opts.text !== undefined) node.textContent = opts.text;
    if (opts.html !== undefined) node.innerHTML = opts.html;
    if (opts.attrs) {
      for (const [k, v] of Object.entries(opts.attrs)) node.setAttribute(k, v);
    }
  }
  return node;
}

function escapeHtml(str) {
  return String(str)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

/** Snippets from the API use sentinel control chars (\x01/\x02) around
 * matched terms instead of raw HTML, so we escape everything first and only
 * then turn the sentinels into real <mark> elements -- this makes it
 * impossible for indexed text to inject markup. */
function renderHighlighted(snippetText) {
  if (!snippetText) return "";
  const escaped = escapeHtml(snippetText);
  return escaped
    .replaceAll("\x01", "<mark>")
    .replaceAll("\x02", "</mark>");
}

function basename(relPath) {
  const parts = relPath.split("/");
  return parts[parts.length - 1];
}

function formatDuration(seconds) {
  if (seconds == null) return "--:--";
  const s = Math.round(seconds);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

/** Editorial timecode HH:MM:SS:FF from seconds + fps. */
function timecode(seconds, fps) {
  if (seconds == null || !isFinite(seconds) || !fps) return "--:--:--:--";
  const totalFrames = Math.max(0, Math.round(seconds * fps));
  const ff = totalFrames % Math.round(fps);
  const totalSeconds = Math.floor(totalFrames / Math.round(fps));
  const ss = totalSeconds % 60;
  const mm = Math.floor(totalSeconds / 60) % 60;
  const hh = Math.floor(totalSeconds / 3600);
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(hh)}:${pad(mm)}:${pad(ss)}:${pad(ff)}`;
}

function toast(message, kind) {
  const container = $("#toast-container");
  const node = el("div", { className: `toast${kind ? " " + kind : ""}`, text: message });
  container.appendChild(node);
  setTimeout(() => node.remove(), 5000);
}

async function fetchJson(url, opts) {
  const res = await fetch(url, opts);
  let body = null;
  try {
    body = await res.json();
  } catch (e) {
    body = null;
  }
  if (!res.ok) {
    // Served from the cc_sync dashboard, the session can expire underneath a
    // long-open tab. The gate answers /broll/api with 401 JSON rather than a
    // 303 to an HTML login page precisely so this is detectable - otherwise the
    // SPA would try to parse the login page as JSON and report nonsense.
    // Standalone (no dashboard) nothing ever returns 401, so this never fires.
    if (res.status === 401 && window.location.pathname.startsWith("/broll")) {
      const back = encodeURIComponent(window.location.pathname);
      toast("Session expired, signing in again…", "error");
      window.location.assign(`/login?next=${back}`);
    }
    const detail = body && (body.detail || body.message);
    const err = new Error(detail || `HTTP ${res.status}`);
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body;
}

function debounce(fn, ms) {
  let t = null;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

/* ---------------------------------------------------------------------- */
/* Init                                                                    */
/* ---------------------------------------------------------------------- */

document.addEventListener("DOMContentLoaded", init);

function init() {
  loadDashboardTopbar();
  buildFlagToggles();
  wireHeader();
  wireModeAndFuzzyToggles();
  wireSourceToggle();
  wireDetailView();
  wireSettingsPanel();
  loadCategories();
  loadFolderTree();
  wireFolderClear();
  wireHistory();
  // applyHistoryState runs the initial search itself (and re-opens a detail
  // view if the URL carries one), so the page is deep-linkable and reloads
  // land where they were.
  applyHistoryState();
}

/* ---------------------------------------------------------------------- */
/* Dashboard topbar                                                        */
/* ---------------------------------------------------------------------- */

/* The static header in index.html is a fallback for the standalone dev loop.
 * Mounted at /broll/ this document-relative fetch resolves to the dashboard's
 * /partials/topbar, and the real header -- session, admin links, the whole nav
 * -- replaces the fallback, making this a page of the dashboard rather than an
 * imitation of one. Standalone the same fetch resolves inside THIS app, 404s,
 * and the fallback stays. Never made root-relative: see
 * tests/test_mounted_prefix.py. */
async function loadDashboardTopbar() {
  try {
    const res = await fetch("../partials/topbar?current=broll");
    // redirected = an expired session answered with the login PAGE; injecting
    // that into the header would be worse than keeping the fallback.
    if (!res.ok || res.redirected) return;
    const html = await res.text();
    if (!html.includes("data-dash-topbar")) return;
    document.getElementById("dash-topbar").innerHTML = html;
  } catch {
    /* dashboard unreachable -- the fallback header stands */
  }
}

/* ---------------------------------------------------------------------- */
/* History: the back button walks logical pages, not out to the dashboard  */
/* ---------------------------------------------------------------------- */

/* Navigation state lives in the URL hash (never the path: mounted at /broll/
 * the SPA must not invent server-side routes). Folder clicks, pagination and
 * opening a clip PUSH an entry; typing in the search box REPLACES, so Back
 * never crawls through half-typed queries. popstate re-applies whatever the
 * entry describes. */

let applyingHistory = false;

function currentHash() {
  const p = new URLSearchParams();
  if (state.q) p.set("q", state.q);
  if (state.category) p.set("cat", state.category);
  if (state.collection) p.set("coll", state.collection);
  if (state.path) p.set("path", state.path);
  if (state.offset) p.set("off", String(state.offset));
  if (state.detail) {
    p.set("v", String(state.detail.video.id));
    if (state.detailSeekTo != null) p.set("t", state.detailSeekTo.toFixed(2));
  }
  return "#" + p.toString();
}

function syncHistory(push) {
  if (applyingHistory) return; // popstate is re-applying, don't re-record it
  const hash = currentHash();
  if (push) history.pushState({ broll: true }, "", hash);
  else history.replaceState(history.state || { broll: true }, "", hash);
}

function wireHistory() {
  window.addEventListener("popstate", () => {
    applyHistoryState();
  });
}

async function applyHistoryState() {
  applyingHistory = true;
  try {
    const p = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    state.q = p.get("q") || "";
    state.category = p.get("cat") || "";
    state.collection = p.get("coll") || "";
    state.path = p.get("path") || "";
    state.offset = parseInt(p.get("off") || "0", 10) || 0;
    $("#q-input").value = state.q;
    syncCategorySelect();
    renderFolderTree();

    const vid = parseInt(p.get("v") || "", 10);
    let leftDetail = false;
    if (vid) {
      // Hits are not serialized, so a restored detail view has no yellow
      // bands -- they belong to the search interaction, not the clip.
      await openDetail(vid, p.has("t") ? parseFloat(p.get("t")) : null, null);
    } else if (state.detail) {
      closeDetail();
      leftDetail = true;
    }
    await runSearch();
    // closeDetail already restored the scroll, but re-running the search empties
    // the grid for an instant and the browser clamps the scroll to the height of
    // an empty page. So put it back once the cards exist again.
    if (leftDetail) window.scrollTo(0, state.gridScrollY || 0);
  } finally {
    applyingHistory = false;
  }
}

function wireFolderClear() {
  $("#folder-clear").addEventListener("click", () => selectFolder("", ""));
}

function wireModeAndFuzzyToggles() {
  const container = $("#mode-toggles");
  for (const btn of container.querySelectorAll(".mode-btn")) {
    btn.classList.toggle("active", btn.dataset.mode === state.mode);
    btn.addEventListener("click", () => {
      state.mode = btn.dataset.mode;
      for (const b of container.querySelectorAll(".mode-btn")) {
        b.classList.toggle("active", b === btn);
      }
      state.offset = 0;
      runSearch();
    });
  }

  const fuzzyCheckbox = $("#fuzzy-checkbox");
  fuzzyCheckbox.checked = state.fuzzy;
  fuzzyCheckbox.addEventListener("change", () => {
    state.fuzzy = fuzzyCheckbox.checked;
    state.offset = 0;
    runSearch();
  });
}

/** "All" / "Visuals" / "Transcript" -- restricts search to what's seen
 * (segments, including burned-in on-screen text) vs. what's said
 * (transcript_segments). Same wiring pattern as the mode toggle above. */
function wireSourceToggle() {
  const container = $("#source-toggles");
  for (const btn of container.querySelectorAll(".mode-btn")) {
    btn.classList.toggle("active", btn.dataset.source === state.sources);
    btn.addEventListener("click", () => {
      state.sources = btn.dataset.source;
      for (const b of container.querySelectorAll(".mode-btn")) {
        b.classList.toggle("active", b === btn);
      }
      state.offset = 0;
      runSearch();
    });
  }
}

function buildFlagToggles() {
  const container = $("#flag-toggles");
  for (const flag of QUALITY_FLAGS) {
    const label = el("label");
    const input = el("input", { attrs: { type: "checkbox" } });
    input.dataset.flag = flag;
    input.addEventListener("change", () => {
      if (input.checked) state.hiddenFlags.add(flag);
      else state.hiddenFlags.delete(flag);
      state.offset = 0;
      runSearch();
    });
    label.appendChild(input);
    label.appendChild(document.createTextNode(flag.replace("_", " ")));
    container.appendChild(label);
  }
}

function wireHeader() {
  const qInput = $("#q-input");
  const debounced = debounce(() => {
    state.q = qInput.value;
    state.offset = 0;
    // REPLACE, not push: Back must jump out of the search, not crawl back
    // through every debounced prefix of what was typed.
    syncHistory(false);
    runSearch();
  }, 250);
  qInput.addEventListener("input", debounced);

  $("#category-select").addEventListener("change", (e) => {
    state.category = e.target.value;
    // Same reason as selectFolder's (BROLL-3): the dropdown is the third way
    // into the same "where am I browsing" state, and leaving a crumb's path
    // filter ANDed underneath it is a reachable zero-result dead end.
    state.path = "";
    state.offset = 0;
    // Two controls onto one piece of state: the tree must not keep highlighting
    // a folder the dropdown has just navigated away from.
    renderFolderTree();
    syncHistory(true);
    runSearch();
  });

  $("#pager-prev").addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - state.limit);
    syncHistory(true);
    runSearch();
  });
  $("#pager-next").addEventListener("click", () => {
    state.offset = state.offset + state.limit;
    syncHistory(true);
    runSearch();
  });
}

async function loadCategories() {
  try {
    const categories = await fetchJson("api/categories");
    const select = $("#category-select");
    for (const cat of categories) {
      const depth = (cat.slug.match(/\//g) || []).length;
      const opt = el("option", { text: `${"  ".repeat(depth)}${cat.label}` });
      opt.value = cat.slug;
      select.appendChild(opt);
    }
  } catch (e) {
    console.error("failed to load categories", e);
  }
}

/* ---------------------------------------------------------------------- */
/* Folder tree                                                            */
/* ---------------------------------------------------------------------- */

/* The subject tree, two roots deep: Downloads (footage sourced from the web)
 * and Creators_Club (footage we shot). Folders are SUBJECT only -- what the
 * clip is about. Format, place and look are descriptors of what is likely
 * visually inside a clip, not places in the tree, so they stay as filters.
 *
 * A root with nothing in it is not rendered at all: an unconfigured deployment
 * has no own-footage shares, and an empty shelf is worse than no shelf. */
async function loadFolderTree() {
  try {
    state.tree = await fetchJson("api/tree");
    // The own-footage root names itself; nothing here spells it (item 4).
    learnCollections(state.tree);
  } catch (e) {
    console.error("failed to load folder tree", e);
    return;
  }
  renderFolderTree();
}

function renderFolderTree() {
  const body = $("#folder-tree-body");
  body.innerHTML = "";

  for (const root of state.tree) {
    if (!root.total) continue;

    const rootEl = el("div", { className: "tree-root" });
    const rootBtn = el("button", { className: "tree-node tree-node-root", type: "button" });
    rootBtn.innerHTML =
      `<span class="tree-name">${escapeHtml(root.label)}</span>` +
      `<span class="tree-count">${root.total}</span>`;
    if (state.collection === root.collection && !state.category) {
      rootBtn.classList.add("active");
    }
    rootBtn.addEventListener("click", () => selectFolder(root.collection, ""));
    rootEl.appendChild(rootBtn);

    for (const group of root.groups) {
      rootEl.appendChild(renderTreeNode(root.collection, group, 0));
    }
    body.appendChild(rootEl);
  }
}

/* One folder row plus its subtree, recursively.
 *
 * Creators_Club nests as deep as the shoot did (share :: event / day / camera),
 * so a fixed root>group>leaf renderer could only ever show the first two
 * levels - everything below was unreachable by clicking (2026-08-10). Downloads
 * is the same shape, two levels deep, and its leaves may arrive with no
 * "children" key at all, hence the `|| []`. */
function renderTreeNode(collection, node, depth) {
  const children = node.children || [];
  const wrap = el("div", { className: depth === 0 ? "tree-group" : "tree-subtree" });
  const open = state.collection === collection && isAncestorCategory(node.slug, state.category);

  const btn = el("button", {
    className: `tree-node ${depth === 0 ? "tree-node-group" : "tree-node-leaf"}`,
    type: "button",
  });
  // A leaf-less node (Uncategorised, a camera folder) gets no caret - there is
  // nothing to expand, and a caret that does nothing when clicked reads as
  // broken. The span stays either way so labels line up down the rail.
  const caret = children.length ? (open ? "▾" : "▸") : "";
  btn.innerHTML =
    `<span class="tree-caret">${caret}</span>` +
    `<span class="tree-name">${escapeHtml(node.label)}</span>` +
    `<span class="tree-count">${node.count}</span>`;
  btn.title = node.slug;
  // Depth is unbounded, so the indent is computed rather than one CSS class per
  // level. Depth 0 keeps the stylesheet's own padding.
  if (depth > 0) btn.style.paddingLeft = `${26 + (depth - 1) * 14}px`;
  if (state.collection === collection && state.category === node.slug) {
    btn.classList.add("active");
  }
  btn.addEventListener("click", () => selectFolder(collection, node.slug));
  wrap.appendChild(btn);

  if (children.length) {
    const kids = el("div", { className: `tree-children${open ? "" : " hidden"}` });
    for (const child of children) {
      kids.appendChild(renderTreeNode(collection, child, depth + 1));
    }
    wrap.appendChild(kids);
  }
  return wrap;
}

/** Is `slug` the selection itself, or on the path down to it? (Which is what
 * decides whether a node shows its children.) A bare startsWith is not enough:
 * "Whisky" must not count as an ancestor of "Whisky Bar", so the remainder has
 * to begin at a real separator - "::" under a share, " / " between shoot path
 * components, "/" between subject slugs. */
function isAncestorCategory(slug, category) {
  if (!slug || !category) return false;
  if (category === slug) return true;
  if (!category.startsWith(slug)) return false;
  const rest = category.slice(slug.length);
  return rest.startsWith("::") || rest.startsWith(" / ") || rest.startsWith("/");
}

/** One level up from a folder slug, "" at the top of either root. Shoot slugs
 * are "share::Event / Day 1 / A-cam" - the share joins with "::" and the path
 * under it with " / "; subject slugs nest with plain "/". */
function parentFolder(category) {
  if (!category) return "";
  const cut = category.indexOf("::");
  if (cut !== -1) {
    const share = category.slice(0, cut);
    const path = category.slice(cut + 2);
    const lastSep = path.lastIndexOf(" / ");
    return lastSep === -1 ? share : `${share}::${path.slice(0, lastSep)}`;
  }
  const lastSlash = category.lastIndexOf("/");
  return lastSlash === -1 ? "" : category.slice(0, lastSlash);
}

/** Point the category <select> at whatever state now says, from ONE place.
 *
 * Creators_Club folders are shoot paths (`ff4::Whisky / Interviews`), and
 * loadCategories only ever populates this control from /api/categories --
 * subject slugs. Assigning a <select> a value no option carries silently sets
 * selectedIndex = -1 and renders the box empty, which reads as a filter the
 * editor can neither see nor identify (the trap R15 fix 1 documents for the
 * ytdl project picker). applyHistoryState and jumpToSearch both guarded it;
 * selectFolder did not, so the same folder rendered two different ways
 * depending on whether it was reached by click or by Back (BROLL-WEB-8,
 * 2026-08-14). Hoisted rather than triplicated so the next writer of this
 * control cannot diverge again. */
function syncCategorySelect() {
  const select = $("#category-select");
  if (select) select.value = isOwnedCollection(state.collection) ? "" : state.category;
}

function selectFolder(collection, category) {
  // Clicking the folder you are already in backs out to its parent, so the
  // tree doubles as its own breadcrumb and there is no dead click. Exactly one
  // level: jumping straight back to the share from four levels down threw away
  // the descent the editor had just made.
  if (state.collection === collection && state.category === category) {
    category = parentFolder(category);
    if (!category && !state.category) collection = "";
  }
  state.collection = collection;
  state.category = category;
  // The crumb-derived path filter is ANDed with this one, and only
  // renderResultsMeta's own "clear folder" link ever reset it -- so navigating
  // the tree after clicking a detail-panel crumb produced a mutually exclusive
  // pair (collection=downloads AND path=ff4::Erosion), zero results, and a
  // "clear" button in the tree that could not escape it (BROLL-3, 2026-08-11).
  // Picking a folder in the tree IS choosing where to browse; it replaces the
  // previous choice rather than intersecting with it.
  state.path = "";
  state.offset = 0;
  syncCategorySelect();
  renderFolderTree();
  syncHistory(true);
  runSearch();
}

/* ---------------------------------------------------------------------- */
/* Search / grid                                                          */
/* ---------------------------------------------------------------------- */

/* Every runSearch takes the next token and only the newest one is allowed to
 * paint. Semantic mode costs a query embedding plus a brute-force scan, so a
 * folder click landing while an earlier text search is still in flight used to
 * be overwritten by that older response -- unfiltered results in the grid with
 * the folder highlighted in the sidebar, and no way to tell (BROLL-8,
 * 2026-08-11). A token rather than AbortController: a superseded response is
 * merely uninteresting, not worth tearing the connection down for. */
let searchToken = 0;

async function runSearch() {
  const token = ++searchToken;
  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  // Creators_Club folders are shoot paths, not subject slugs - own footage is
  // not model-indexed, so there is no subject to filter on.
  if (isOwnedCollection(state.collection)) {
    if (state.category) params.set("shoot", state.category);
  } else if (state.category) {
    params.set("category", state.category);
  }
  if (state.collection) params.set("collection", state.collection);
  if (state.path) params.set("path", state.path);
  if (state.hiddenFlags.size) params.set("flags", [...state.hiddenFlags].join(","));
  params.set("mode", state.mode);
  params.set("sources", state.sources);
  params.set("fuzzy", state.fuzzy ? "true" : "false");
  params.set("limit", state.limit);
  params.set("offset", state.offset);

  let data;
  try {
    data = await fetchJson(`api/search?${params.toString()}`);
  } catch (e) {
    if (token !== searchToken) return;
    toast(`Search failed: ${e.message}`, "error");
    return;
  }
  if (token !== searchToken) return; // a newer search is already authoritative

  state.total = data.total;
  state.lastResults = data.results;
  renderGrid(data.results);
  renderPager();
}

function renderPager() {
  const status = $("#pager-status");
  const shown = state.lastResults.length;
  const from = shown ? state.offset + 1 : 0;
  const to = state.offset + shown;
  status.textContent = `${from}–${to} of ${state.total}`;
  $("#pager-prev").disabled = state.offset <= 0;
  $("#pager-next").disabled = state.offset + state.limit >= state.total;
}

function renderGrid(results) {
  const grid = $("#results-grid");
  grid.innerHTML = "";
  renderResultsMeta();

  // Semantic-only rows ("match": "semantic" -- surfaced only by the vector
  // side, never a keyword result -- see app/search.py's module docstring)
  // are grouped after every keyword result, under a "Related" heading, so
  // an editor can tell a confident match from a suggestion at a glance.
  let relatedHeadingShown = false;
  for (const row of results) {
    if (row.match === "semantic" && !relatedHeadingShown) {
      grid.appendChild(
        el("div", { className: "results-related-heading", text: "Related" })
      );
      relatedHeadingShown = true;
    }
    grid.appendChild(buildCard(row));
  }
}

function buildCard(row) {
  const { video, hits } = row;
  const isSemanticOnly = row.match === "semantic";
  const card = el("div", { className: `card${isSemanticOnly ? " card-semantic" : ""}` });

  const thumb = el("div", { className: "card-thumb" });
  // One sheet cell tall, from the same geometry positionSprite offsets by --
  // a card sized off the SOURCE aspect ratio while the overlay is offset by
  // the sheet's own cell height shows a sliver of the next row (BROLL-1).
  thumb.style.height = `${spriteGeometry(video).cellHeight}px`;

  const poster = el("img", { className: "poster" });
  poster.src = `media/poster/${video.id}.jpg`;
  poster.loading = "lazy";
  // A few videos are real archive footage that never got a poster because
  // probe or proxy failed on a corrupt source. They belong in the library, so
  // show the placeholder rather than a broken-image icon -- and rather than
  // hiding the file, which would make a damaged source look like it isn't
  // there at all.
  poster.addEventListener("error", () => {
    poster.remove();
    thumb.classList.add("thumb-missing");
  });
  thumb.appendChild(poster);

  const spriteOverlay = el("div", { className: "sprite-overlay" });
  spriteOverlay.style.backgroundImage = `url(media/sprite/${video.id}.jpg)`;
  thumb.appendChild(spriteOverlay);

  if (video.duration_s != null) {
    thumb.appendChild(
      el("div", { className: "duration-badge", text: formatDuration(video.duration_s) })
    );
  }

  wireSpriteScrub(thumb, spriteOverlay, video);

  // A result's thumbnail shows the frame that MATCHED rather than the poster
  // (frame 0): in a long-form archive the poster is usually a slate or a wall,
  // and every card in a search then looks the same. The overlay stays visible
  // (.sprite-static) and hover-scrub still works on top of it, snapping back to
  // the hit frame on the way out. If the sprite sheet 404s the overlay simply
  // paints nothing and the poster/placeholder underneath shows through.
  if (hits.length && video.duration_s) {
    spriteOverlay.classList.add("sprite-static");
    positionSprite(spriteOverlay, video, hits[0].t_start);
    thumb.addEventListener("mouseleave", () => {
      positionSprite(spriteOverlay, video, hits[0].t_start);
    });
  }

  // Thumbnails ONLY -- no filename, category or hit chips under the image
  // (2026-08-10, by request): b-roll is chosen by eye, and a card of text under
  // every frame pulled the eye away from the one thing that matters. What the
  // text carried survives elsewhere: the filename/category as a hover tooltip,
  // the best hit as the card's click target, and every hit as a yellow band on
  // the detail seekbar.
  card.title = `${basename(video.rel_path)} - ${video.category || video.category_hint || "uncategorised"}`;
  card.appendChild(thumb);
  // Open at the moment that matched, not at 0:00. The whole point of a hit is
  // that the archive is long-form: the match is often minutes in, and landing
  // at the head of a 13-minute clip means hunting for what search already
  // found. hits[0] is the best-ranked hit (search returns them ordered), and
  // the chips above seek the same way. Browse mode has no hits -> null -> 0:00.
  const seekTo = hits.length ? hits[0].t_start : null;
  card.addEventListener("click", () => openDetail(video.id, seekTo, hits));
  // Client folders (clientfolders.js) hang their "+" on the card here. A soft
  // hook rather than a hard call so this file still runs standalone if that
  // script is ever not loaded.
  if (typeof cfDecorateCard === "function") cfDecorateCard(card, video);
  return card;
}

/* ---------------------------------------------------------------------- */
/* Detail view                                                            */
/* ---------------------------------------------------------------------- */

function wireDetailView() {
  $("#detail-back").addEventListener("click", () => {
    // The detail view is a history entry of its own, so the in-page button and
    // the browser's Back button must do the same thing - otherwise leaving by
    // one of them leaves a stale entry the other then walks back into.
    if (history.state && history.state.broll) {
      history.back();
    } else {
      closeDetail();
      syncHistory(true);
    }
  });

  const player = $("#player");
  player.addEventListener("timeupdate", updatePlayhead);
  player.addEventListener("loadedmetadata", updatePlayhead);
  // The probed duration_s is sometimes short, which put markers past the right
  // edge of the bar; the real duration only exists once metadata is in, so the
  // markers are laid out again here.
  player.addEventListener("loadedmetadata", renderSeekMarkers);
  player.addEventListener("loadedmetadata", applyPendingSeek);
  wireSeekQueue(player);
  wireSeekbarScrub(player);
  wireDragScrub(player);

  // Explicit modes, not the bare handler: an event object arriving as `mode`
  // would read as junk and be refused by the companion.
  $("#send-resolve-btn").addEventListener("click", () => sendToResolve("append"));
  $("#place-resolve-btn").addEventListener("click", () => sendToResolve("playhead"));

  document.addEventListener("keydown", onKeydown);
}

/* One seek in flight at a time.
 *
 * A drag fires pointermove far faster than the decoder can service seeks, and
 * assigning currentTime on every one makes the picture crawl seconds behind the
 * pointer as the element works through a backlog. Coalescing to "the most
 * recently requested time" instead keeps the scrub live: an intermediate target
 * the user has already dragged past is worthless. */
const seekQueue = { busy: false, pending: null };

function wireSeekQueue(player) {
  player.addEventListener("seeked", () => {
    if (seekQueue.pending != null) {
      const next = seekQueue.pending;
      seekQueue.pending = null;
      player.currentTime = next; // still busy: this is the next seek, not idle
      return;
    }
    seekQueue.busy = false;
  });
  // A new clip: whatever was in flight belongs to the old one.
  player.addEventListener("emptied", () => {
    seekQueue.busy = false;
    seekQueue.pending = null;
  });
}

function requestSeek(player, t) {
  const duration = player.duration || (state.detail && state.detail.video.duration_s) || 0;
  const target = Math.min(duration, Math.max(0, t));
  // Paint from the REQUESTED time, not the element's: the playhead and timecode
  // have to track the pointer even while the decoder is still catching up.
  showSeekTarget(target, duration);
  if (seekQueue.busy) {
    seekQueue.pending = target;
    return;
  }
  // Already there. Assigning anyway is a no-op that some browsers never answer
  // with "seeked", which would leave the queue busy forever and kill scrubbing
  // for the rest of the clip.
  if (target === player.currentTime) return;
  seekQueue.busy = true;
  player.currentTime = target;
}

function showSeekTarget(t, duration) {
  if (!state.detail) return;
  if (duration > 0) {
    $("#seekbar-playhead").style.left = `${Math.min(100, (t / duration) * 100)}%`;
  }
  $("#tc-current").textContent = timecode(t, state.detail.video.fps || 24);
}

/* Press-and-drag on the seekbar.
 *
 * ABSOLUTE, unlike the relative drag on the picture below: the bar IS the
 * timeline, so pressing at a point means "go there" and holding scrubs from
 * there. It replaced a plain click listener, which meant scrubbing along the
 * bar took a row of separate clicks. */
function wireSeekbarScrub(player) {
  const seekbar = $("#seekbar");
  let dragging = false;
  let wasPlaying = false;

  const seekToPointer = (e) => {
    const rect = seekbar.getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (e.clientX - rect.left) / (rect.width || 1)));
    requestSeek(player, frac * player.duration);
  };

  seekbar.addEventListener("pointerdown", (e) => {
    if (!state.detail || !player.duration || e.button !== 0) return;
    e.preventDefault();
    dragging = true;
    wasPlaying = !player.paused;
    seekbar.setPointerCapture(e.pointerId); // keep scrubbing outside the bar
    // A held shuttle rate would fight the drag for control of currentTime.
    resetShuttle();
    player.pause();
    seekToPointer(e);
  });

  seekbar.addEventListener("pointermove", (e) => {
    if (dragging) seekToPointer(e);
  });

  const end = (e) => {
    if (!dragging) return;
    dragging = false;
    if (seekbar.hasPointerCapture?.(e.pointerId)) seekbar.releasePointerCapture(e.pointerId);
    if (wasPlaying) player.play().catch(() => {});
  };
  seekbar.addEventListener("pointerup", end);
  seekbar.addEventListener("pointercancel", end);
}

// How far the pointer must travel before a press counts as a scrub rather than
// a click. Without it every play/pause click lands a few stray pixels of seek.
const SCRUB_THRESHOLD_PX = 4;

/* Drag anywhere on the video to scrub.
 *
 * RELATIVE, not absolute: the playhead moves by how far you drag, it does not
 * jump to where you pressed. On a seekbar absolute is right -- the bar IS the
 * timeline. On the picture it would mean every click on the image threw the
 * playhead somewhere else before you had moved at all, which makes clicking to
 * pause impossible. Dragging the full width of the player covers the full clip,
 * so the gearing matches the seekbar underneath it.
 */
function wireDragScrub(player) {
  let drag = null;

  player.addEventListener("pointerdown", (e) => {
    if (!state.detail || !player.duration || e.button !== 0) return;
    e.preventDefault();
    drag = {
      x: e.clientX,
      startTime: player.currentTime,
      wasPlaying: !player.paused,
      moved: false,
      width: player.getBoundingClientRect().width || 1,
    };
    player.setPointerCapture(e.pointerId);  // keep scrubbing outside the element
    player.classList.add("scrubbing");
    // A held shuttle rate would fight the drag for control of currentTime.
    resetShuttle();
    player.pause();
  });

  player.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x;
    if (!drag.moved && Math.abs(dx) < SCRUB_THRESHOLD_PX) return;
    drag.moved = true;
    requestSeek(player, drag.startTime + (dx / drag.width) * player.duration);
  });

  const end = (e) => {
    if (!drag) return;
    const wasDrag = drag.moved;
    const resume = drag.wasPlaying;
    drag = null;
    player.classList.remove("scrubbing");
    if (player.hasPointerCapture?.(e.pointerId)) player.releasePointerCapture(e.pointerId);
    if (!wasDrag) {
      // A clean click: the video has no native controls, so this is the only
      // pointer affordance for play/pause.
      togglePlayPause();
      return;
    }
    if (resume) player.play().catch(() => {});
  };
  player.addEventListener("pointerup", end);
  player.addEventListener("pointercancel", end);
}

async function openDetail(videoId, seekToSeconds, hits) {
  let data;
  try {
    data = await fetchJson(`api/videos/${videoId}`);
  } catch (e) {
    toast(`Could not load video: ${e.message}`, "error");
    return;
  }
  state.detail = data;
  // The hits that brought the editor here, carried in so the seekbar can show
  // WHERE the match was. They belong to the search, not the clip, which is why
  // they are passed rather than fetched.
  state.detailHits = hits || [];
  state.detailSeekTo = seekToSeconds;
  state.gridScrollY = window.scrollY;
  state.inPoint = null;
  state.outPoint = null;
  resetShuttle();
  syncHistory(true);

  // The WHOLE browse layout goes, not just the grid: the folder rail is a
  // full-height sticky column, so leaving it mounted kept a 210px gutter beside
  // the player and left the page scrolled halfway down the results.
  $("#browse-layout").classList.add("hidden");
  $("#detail-view").classList.remove("hidden");
  window.scrollTo(0, 0);

  const player = $("#player");
  player.src = `media/proxy/${videoId}.mp4`;
  player.playbackRate = 1;
  player.load();

  renderVideoMeta(data);
  renderSegmentList(data);
  renderTranscriptList(data);
  renderSeekMarkers();
  renderInOutRange();
  $("#tc-in").textContent = "--:--:--:--";
  $("#tc-out").textContent = "--:--:--:--";
  $("#tc-rate").textContent = "1x";

  // The seek itself is applied by applyPendingSeek off the ONE permanent
  // loadedmetadata handler, from state.detailSeekTo set above -- see there.
}

/** Jump to the timecode of the hit that brought the editor here, once this
 * clip's metadata is in (duration/seekability do not exist before that).
 *
 * Registered once on the persistent #player, not armed per-open with
 * {once:true}: that only detaches after it FIRES, so a clip whose proxy 404s
 * (an un-archived row's /media/proxy has nothing behind it) or that the editor
 * left before metadata arrived kept its listener attached -- and closeDetail's
 * removeAttribute("src") + load() fires `emptied`, never `loadedmetadata`, so
 * nothing cleared it. It then fired against the NEXT clip and silently opened
 * it two minutes in, at a timecode belonging to a different video (BROLL-WEB-4,
 * 2026-08-14). state.detailSeekTo is per-clip, set by openDetail and cleared by
 * closeDetail, so there is no listener state left to leak. */
function applyPendingSeek() {
  if (state.detailSeekTo == null) return;
  $("#player").currentTime = state.detailSeekTo;
  state.detailSeekTo = null;
}

function closeDetail() {
  const player = $("#player");
  player.pause();
  player.removeAttribute("src");
  player.load();
  state.detail = null;
  state.detailHits = [];
  state.detailSeekTo = null;
  resetShuttle();
  $("#detail-view").classList.add("hidden");
  $("#browse-layout").classList.remove("hidden");
  // Back to the row of results the clip was opened from, not to the top of a
  // freshly re-shown grid.
  window.scrollTo(0, state.gridScrollY || 0);
}

/** A piece of metadata you can click to search by it. Kept to <button> rather
 * than <a href>: every one of these is an in-page state change, and an anchor
 * would need its own href kept in step with currentHash() for no gain. */
function metaLink(text, onClick, extraClass) {
  const node = el("button", {
    className: `meta-link${extraClass ? " " + extraClass : ""}`,
    text,
    attrs: { type: "button" },
  });
  node.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    onClick();
  });
  return node;
}

/** Leave the detail view and run `mutate`'s search. PUSHes, so Back returns to
 * the clip you clicked out of rather than to whatever preceded it. */
function jumpToSearch(mutate) {
  closeDetail();
  state.offset = 0;
  mutate();
  syncCategorySelect();
  renderFolderTree();
  syncHistory(true);
  runSearch();
}

function renderVideoMeta(data) {
  const { video, themes, quality_flags } = data;
  const meta = $("#video-meta");
  meta.innerHTML = "";
  meta.appendChild(el("div", { className: "title", text: basename(video.rel_path) }));

  // The path, one clickable crumb per level. The share is a crumb too (the
  // whole share is a folder), and the filename is NOT -- it is the clip you
  // are already looking at. Every intermediate directory is selectable, so
  // ff4 / Erosion / Interviewees / Lin Tsung-yi / B-roll is five destinations,
  // not one.
  const parts = video.rel_path.split("/");
  const dirs = parts.slice(0, -1);
  const pathLine = el("div", { className: "meta-path" });
  pathLine.appendChild(
    metaLink(video.share, () =>
      jumpToSearch(() => {
        state.path = `${video.share}::`;
        state.q = "";
        $("#q-input").value = "";
      })
    )
  );
  dirs.forEach((name, i) => {
    pathLine.appendChild(el("span", { className: "meta-sep", text: "/" }));
    const prefix = dirs.slice(0, i + 1).join("/");
    pathLine.appendChild(
      metaLink(name, () =>
        jumpToSearch(() => {
          state.path = `${video.share}::${prefix}`;
          state.q = "";
          $("#q-input").value = "";
        })
      )
    );
  });
  pathLine.appendChild(el("span", { className: "meta-sep", text: "/" }));
  pathLine.appendChild(el("span", { text: basename(video.rel_path) }));
  pathLine.appendChild(
    el("span", {
      text: ` - ${formatDuration(video.duration_s)} @ ${video.fps || "?"}fps`,
    })
  );
  meta.appendChild(pathLine);

  const category = video.category || video.category_hint || "";
  const catLine = el("div", { text: "category: " });
  if (category) {
    catLine.appendChild(
      metaLink(category, () =>
        jumpToSearch(() => {
          state.path = "";
          state.collection = "";
          state.category = category;
          // Clear the query like the path and theme closures above do
          // (BROLL-12, 2026-08-11): "show me this category" carrying the
          // previous search term silently intersects the two and shows a
          // near-empty grid with nothing on screen saying why.
          state.q = "";
          $("#q-input").value = "";
        })
      )
    );
  } else {
    catLine.appendChild(el("span", { text: "none" }));
  }
  meta.appendChild(catLine);

  if (themes && themes.length) {
    // A theme is not a filter the API has -- it is a phrase the model wrote
    // about the footage -- so clicking one searches FOR it rather than
    // filtering BY it. Quoted, because a two-word theme searched loose
    // ("wind farm") is a different question from the theme itself.
    const themeLine = el("div", { text: "themes: " });
    themes.forEach((theme, i) => {
      if (i) themeLine.appendChild(el("span", { text: ", " }));
      themeLine.appendChild(
        metaLink(theme, () =>
          jumpToSearch(() => {
            state.path = "";
            state.q = `"${theme}"`;
            $("#q-input").value = `"${theme}"`;
          })
        )
      );
    });
    meta.appendChild(themeLine);
  }
  if (quality_flags && quality_flags.length) {
    meta.appendChild(el("div", { text: `flags: ${quality_flags.join(", ")}`, className: "muted" }));
  }
}

/** The label the folder tree shows for a slug, or the slug itself if the tree
 * has not loaded (or the slug came from a category crumb the tree omits --
 * folders with no videos in a root are not rendered). */
function treeLabel(slug) {
  const walk = (nodes) => {
    for (const n of nodes) {
      if (n.slug === slug) return n.label;
      const hit = walk(n.children || []);
      if (hit) return hit;
    }
    return null;
  };
  for (const root of state.tree) {
    const hit = walk(root.groups || []);
    if (hit) return hit;
  }
  return slug;
}

/** The line above the grid. It has to name the folder filter as well as the
 * query: a path crumb click can leave the grid showing a subset with an empty
 * search box, and "browsing all videos" over 40 results of 5000 is a lie.
 *
 * `category`/`collection` belong here for the same reason `path` does
 * (BROLL-11, 2026-08-11): clicking a category crumb in the detail panel
 * filters the grid, activates no tree node (the crumb's slug need not be a
 * rendered folder) and used to leave the line reading "browsing all videos". */
function renderResultsMeta() {
  const node = $("#results-meta");
  node.innerHTML = "";
  const bits = [];
  if (state.q) bits.push(`search: "${state.q}"`);
  if (state.collection || state.category) {
    const root = state.tree.find((r) => r.collection === state.collection);
    const names = [];
    if (state.collection) names.push(root ? root.label : state.collection);
    if (state.category) names.push(treeLabel(state.category));
    bits.push(`folder: ${names.join(" / ")}`);
  }
  if (state.path) {
    const [share, prefix] = state.path.split("::");
    bits.push(`folder: ${prefix ? `${share}/${prefix}` : share}`);
  }
  node.appendChild(el("span", { text: bits.length ? bits.join("  ·  ") : "browsing all videos" }));
  if (state.path) {
    node.appendChild(
      metaLink("clear folder", () => jumpToSearch(() => { state.path = ""; }), "meta-clear")
    );
  }
}

function renderSegmentList(data) {
  const { video, segments } = data;
  const list = $("#segment-list");
  list.innerHTML = "";
  for (const seg of segments) {
    const item = el("div", { className: "segment-item" });
    item.appendChild(
      el("div", {
        className: "seg-tc mono",
        text: `${timecode(seg.t_start, video.fps || 24)} – ${timecode(seg.t_end, video.fps || 24)}`,
      })
    );
    item.appendChild(el("div", { className: "seg-desc", text: seg.description }));
    if (seg.onscreen_text) {
      // .text (textContent) escapes automatically, same as seg-desc above --
      // onscreen_text/onscreen_text_en are arbitrary text read off screen by
      // the model, never trusted as markup.
      item.appendChild(
        el("div", { className: "seg-onscreen", text: `“${seg.onscreen_text}”` })
      );
      if (seg.onscreen_text_en) {
        item.appendChild(
          el("div", { className: "seg-onscreen-en", text: seg.onscreen_text_en })
        );
      }
    }
    item.addEventListener("click", () => {
      const player = $("#player");
      player.currentTime = seg.t_start;
      player.play().catch(() => {});
    });
    list.appendChild(item);
  }
}

/** Transcript cues (spoken word -- transcript_segments, distinct from the
 * visual segments list above it) in their own list, distinct style (see
 * .transcript-list in style.css), each clickable to seek the player like a
 * segment item. */
function renderTranscriptList(data) {
  const { video, transcript } = data;
  const section = $("#transcript-section");
  const list = $("#transcript-list");
  list.innerHTML = "";

  if (!transcript || !transcript.length) {
    section.classList.add("hidden");
    return;
  }
  section.classList.remove("hidden");

  for (const cue of transcript) {
    const item = el("div", { className: "segment-item" });
    item.appendChild(
      el("div", {
        className: "seg-tc mono",
        text: `${timecode(cue.t_start, video.fps || 24)} – ${timecode(cue.t_end, video.fps || 24)}`,
      })
    );
    // .text (textContent) escapes automatically -- transcript text is a
    // local whisper transcription, never trusted as markup (same rule as
    // onscreen_text/onscreen_text_en above).
    item.appendChild(el("div", { className: "seg-desc", text: cue.text }));
    item.addEventListener("click", () => {
      const player = $("#player");
      player.currentTime = cue.t_start;
      player.play().catch(() => {});
    });
    list.appendChild(item);
  }
}

/* Two layers on one bar: amber bands for the search hits that brought the
 * editor to this clip (so the matched moments are visible before a frame
 * plays), then the green ticks for the model's visual segment boundaries.
 *
 * Duration comes from the loaded media FIRST. The probed duration_s is
 * sometimes short (VFR sources, truncated recordings) and dividing by it drove
 * markers off the right-hand end of the bar - the cause of the stray green
 * ticks past the edge. Reads state rather than taking the payload so the
 * loadedmetadata re-render has something to re-render from. */
function renderSeekMarkers() {
  const markersEl = $("#seekbar-markers");
  markersEl.innerHTML = "";
  if (!state.detail) return;
  const { video, segments } = state.detail;
  const duration = $("#player").duration || video.duration_s || 0;
  if (!duration) return;

  for (const hit of state.detailHits || []) {
    if (hit.t_start == null || hit.t_start > duration) continue;
    const end = Math.min(hit.t_end != null ? hit.t_end : hit.t_start + 1, duration);
    const band = el("div", { className: "seekbar-hit" });
    band.style.left = `${(hit.t_start / duration) * 100}%`;
    // A floor on the width: a one-second hit in a thirteen-minute clip is
    // otherwise a band too thin to see, let alone aim at.
    band.style.width = `${Math.max(0.5, ((end - hit.t_start) / duration) * 100)}%`;
    markersEl.appendChild(band);
  }

  for (const seg of segments) {
    if (seg.t_start > duration) continue;
    const marker = el("div", { className: "seekbar-marker" });
    marker.style.left = `${Math.min(100, (seg.t_start / duration) * 100)}%`;
    markersEl.appendChild(marker);
  }
}

function updatePlayhead() {
  const player = $("#player");
  if (!state.detail) return;
  const duration = player.duration || state.detail.video.duration_s || 0;
  if (duration > 0) {
    $("#seekbar-playhead").style.left =
      `${Math.min(100, (player.currentTime / duration) * 100)}%`;
  }
  $("#tc-current").textContent = timecode(player.currentTime, state.detail.video.fps || 24);
}

function renderInOutRange() {
  const rangeEl = $("#seekbar-range");
  // Same duration fallback as the markers and the playhead: all three have to
  // agree or the in/out shading drifts against the ticks it brackets.
  const duration = state.detail
    ? $("#player").duration || state.detail.video.duration_s || 0
    : 0;

  // Each flag drops the moment ITS key lands - the shaded range still needs
  // both ends, but "did my I register?" must be answerable immediately.
  const place = (el, seconds) => {
    if (seconds == null || !duration) {
      el.style.display = "none";
      return;
    }
    el.style.display = "block";
    el.style.left = `${Math.min(100, (seconds / duration) * 100)}%`;
  };
  place($("#seekbar-in"), state.inPoint);
  place($("#seekbar-out"), state.outPoint);

  if (state.inPoint == null || state.outPoint == null || !duration) {
    rangeEl.style.display = "none";
    return;
  }
  const lo = Math.min(state.inPoint, state.outPoint);
  const hi = Math.max(state.inPoint, state.outPoint);
  rangeEl.style.display = "block";
  rangeEl.style.left = `${(lo / duration) * 100}%`;
  rangeEl.style.width = `${((hi - lo) / duration) * 100}%`;
}

/* ---------------------------------------------------------------------- */
/* Keyboard transport: space/K play-pause, J/L shuttle, arrows +-1 frame,  */
/* I/O in/out points, Enter send to Resolve.                              */
/* ---------------------------------------------------------------------- */

function onKeydown(e) {
  if (!state.detail) return;
  // Don't hijack typing in the search box etc.
  const tag = (e.target && e.target.tagName) || "";
  if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;

  const player = $("#player");
  const fps = state.detail.video.fps || 24;

  switch (e.key) {
    case " ":
    case "k":
    case "K":
      e.preventDefault();
      togglePlayPause();
      break;
    case "j":
    case "J":
      e.preventDefault();
      shuttle(-1);
      break;
    case "l":
    case "L":
      e.preventDefault();
      shuttle(1);
      break;
    case "ArrowLeft":
      e.preventDefault();
      resetShuttle();
      player.pause();
      player.currentTime = Math.max(0, player.currentTime - 1 / fps);
      break;
    case "ArrowRight":
      e.preventDefault();
      resetShuttle();
      player.pause();
      player.currentTime = Math.min(player.duration || Infinity, player.currentTime + 1 / fps);
      break;
    case "i":
    case "I":
      e.preventDefault();
      state.inPoint = player.currentTime;
      $("#tc-in").textContent = timecode(state.inPoint, fps);
      renderInOutRange();
      break;
    case "o":
    case "O":
      e.preventDefault();
      state.outPoint = player.currentTime;
      $("#tc-out").textContent = timecode(state.outPoint, fps);
      renderInOutRange();
      break;
    case "Enter":
      e.preventDefault();
      sendToResolve(e.shiftKey ? "playhead" : "append");
      break;
    default:
      break;
  }
}

function togglePlayPause() {
  const player = $("#player");
  resetShuttle();
  if (player.paused) player.play().catch(() => {});
  else player.pause();
}

/** J/L shuttle: L steps forward through increasing playback rates
 * (1x, 2x, 4x, 8x); J does the same in reverse. Since <video> playbackRate
 * can't go negative in browsers, reverse shuttle is simulated by stepping
 * currentTime backwards on a timer. */
function shuttle(dir) {
  const player = $("#player");
  if (state.shuttleDir === dir) {
    state.shuttleRateIdx = Math.min(SHUTTLE_RATES.length - 1, state.shuttleRateIdx + 1);
  } else {
    state.shuttleDir = dir;
    state.shuttleRateIdx = 0;
  }
  const rate = SHUTTLE_RATES[state.shuttleRateIdx];
  $("#tc-rate").textContent = `${dir < 0 ? "-" : ""}${rate}x`;

  if (dir > 0) {
    stopShuttleTimer();
    player.playbackRate = rate;
    player.play().catch(() => {});
  } else {
    player.pause();
    player.playbackRate = 1;
    startReverseShuttle(rate);
  }
}

function startReverseShuttle(rate) {
  const player = $("#player");
  stopShuttleTimer();
  const stepMs = 50;
  state.shuttleTimer = setInterval(() => {
    player.currentTime = Math.max(0, player.currentTime - (rate * stepMs) / 1000);
    if (player.currentTime <= 0) resetShuttle();
  }, stepMs);
}

function stopShuttleTimer() {
  if (state.shuttleTimer) {
    clearInterval(state.shuttleTimer);
    state.shuttleTimer = null;
  }
}

function resetShuttle() {
  stopShuttleTimer();
  state.shuttleDir = 0;
  state.shuttleRateIdx = 0;
  const player = $("#player");
  if (player) player.playbackRate = 1;
  const rateEl = $("#tc-rate");
  if (rateEl) rateEl.textContent = "1x";
}

/* ---------------------------------------------------------------------- */
/* Send to Resolve                                                        */
/* ---------------------------------------------------------------------- */

/* One send in flight at a time: while a clip is still syncing down from the
 * NAS this loop re-POSTs the same /insert body every 1.5s (the companion
 * joins the running download and answers with progress), and both the click
 * handler and the Enter shortcut land here. */
let sendInFlight = false;

function syncProgressLabel(progress) {
  if (progress && typeof progress.percent === "number") {
    return `SYNCING ${progress.percent}%`;
  }
  return "SYNCING…";
}

async function sendToResolve(mode = "append") {
  if (!state.detail || sendInFlight) return;
  const { video } = state.detail;
  const fps = video.fps || 24;

  if (state.inPoint == null || state.outPoint == null) {
    toast("Set both an in point (I) and an out point (O) first.", "error");
    return;
  }
  const inSeconds = Math.min(state.inPoint, state.outPoint);
  const outSeconds = Math.max(state.inPoint, state.outPoint);
  const inFrame = Math.round(inSeconds * fps);
  const outFrame = Math.round(outSeconds * fps);
  if (outFrame <= inFrame) {
    toast("Out point must be after in point.", "error");
    return;
  }

  const payload = {
    // insert_* is the clip's ARCHIVE identity (share "broll" + top-slot
    // path), which every companion can mount and fetch; the bare
    // share/rel_path is the ingest identity, which only machines with a
    // hand-written mount for that share can translate (the base rig
    // resolved ff3 to Z:\ and inserted from outside the tree, 2026-08-12).
    // The fallback keeps un-archived clips inserting exactly as before.
    share: video.insert_share || video.share,
    rel_path: video.insert_rel_path || video.rel_path,
    in_frame: inFrame,
    out_frame: outFrame,
    fps: fps,
    mode: mode,
  };

  // The active button carries the SYNCING label; both are disabled, because
  // "one send in flight" is per companion, not per button.
  const btn = $(mode === "playhead" ? "#place-resolve-btn" : "#send-resolve-btn");
  const otherBtn = $(mode === "playhead" ? "#send-resolve-btn" : "#place-resolve-btn");
  const originalLabel = btn ? btn.innerHTML : null;
  sendInFlight = true;
  if (btn) btn.disabled = true;
  if (otherBtn) otherBtn.disabled = true;
  let announcedSync = false;
  try {
    for (;;) {
      let res;
      try {
        res = await fetch(`${COMPANION_URL}/insert`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      } catch (e) {
        // A rejected fetch is NOT proof the companion is down: Chrome's
        // local-network permission can block a plain-HTTP dashboard origin
        // from reaching 127.0.0.1 with the identical error (seen live
        // 2026-08-12 -- the companion was healthy the whole time). Opening
        // /status directly in a tab is never gated, so it disambiguates.
        toast(
          "Couldn't reach the companion app. It may not be running, or your " +
          "browser blocked the connection (look for a “local network” " +
          "permission prompt, or allow it in site settings). Self-test: open " +
          "http://127.0.0.1:8899/status - if that shows ok:true, it's the " +
          "browser, not the companion. Downloads are in Settings.",
          "error"
        );
        return;
      }

      let body = null;
      try {
        body = await res.json();
      } catch (e) {
        body = null;
      }

      if (res.ok && body && body.state === "downloading") {
        if (!announcedSync) {
          announcedSync = true;
          toast("Clip isn't on this machine yet: syncing it down, then inserting.", "");
        }
        if (btn) btn.textContent = syncProgressLabel(body.progress);
        await new Promise((r) => setTimeout(r, 1500));
        continue;
      }

      if (!res.ok || !body || body.ok === false) {
        let message = (body && body.message) || `Companion returned HTTP ${res.status}`;
        // Fleet companions built before Place at Playhead existed (0.6.x-0.7.x)
        // answer an unknown mode with a bare "not implemented yet" -- true, but
        // it names no action. Newer builds refuse junk modes with their own
        // "needs an update" text, so only the legacy string is rewritten.
        if (mode === "playhead" && /not implemented yet/.test(message)) {
          message =
            "This companion build predates Place at Playhead. Update the " +
            "companion app (tray icon → check for updates), or use Append.";
        }
        toast(message, "error");
        return;
      }

      toast(body.message || "Sent to Resolve.", "success");
      return;
    }
  } finally {
    sendInFlight = false;
    if (btn) {
      btn.disabled = false;
      if (originalLabel != null) btn.innerHTML = originalLabel;
    }
    if (otherBtn) otherBtn.disabled = false;
  }
}

/* ---------------------------------------------------------------------- */
/* Settings panel                                                        */
/* ---------------------------------------------------------------------- */

function wireSettingsPanel() {
  $("#settings-btn").addEventListener("click", openSettings);
  $("#settings-close").addEventListener("click", closeSettings);
  $("#companion-recheck").addEventListener("click", checkCompanionStatus);
}

async function openSettings() {
  $("#settings-panel").classList.remove("hidden");
  await loadShares();
  checkCompanionStatus();
}

function closeSettings() {
  $("#settings-panel").classList.add("hidden");
}

async function loadShares() {
  const list = $("#shares-list");
  list.innerHTML = "";
  let shares;
  try {
    shares = await fetchJson("api/shares");
  } catch (e) {
    list.appendChild(el("div", { className: "muted small", text: "failed to load shares" }));
    return;
  }
  if (!shares.length) {
    list.appendChild(el("div", { className: "muted small", text: "no shares configured" }));
    return;
  }
  for (const s of shares) {
    const row = el("div", { className: "share-row" });
    row.innerHTML = `<span class="share-name mono">${escapeHtml(s.share)}</span> - <span class="share-desc">${escapeHtml(s.description)}</span>`;
    list.appendChild(row);
  }
}

async function checkCompanionStatus() {
  const dot = $("#companion-dot");
  const text = $("#companion-text");
  dot.className = "status-dot status-unknown";
  text.textContent = "checking…";
  try {
    const status = await fetchJson(`${COMPANION_URL}/status`);
    dot.className = `status-dot ${status.ok ? "status-ok" : "status-bad"}`;
    text.textContent = status.ok
      ? `connected (Resolve: ${status.resolve_connected ? "yes" : "no"}, v${status.version})`
      : "companion reports a problem";
  } catch (e) {
    dot.className = "status-dot status-bad";
    // Same caveat as the insert path: a blocked fetch (Chrome local-network
    // permission on an http:// dashboard origin) looks identical to a
    // stopped companion from here.
    text.textContent =
      "not reachable: companion not running, or the browser blocked local " +
      "connections (self-test: open http://127.0.0.1:8899/status)";
  }
}
