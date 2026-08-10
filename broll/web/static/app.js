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

const SPRITE_COLUMNS = 10;
const SPRITE_SECONDS_PER_FRAME = 2;
const SPRITE_CELL_WIDTH = 240;

const SHUTTLE_RATES = [1, 2, 4, 8];

/* ---------------------------------------------------------------------- */
/* State                                                                   */
/* ---------------------------------------------------------------------- */

const SEARCH_MODES = ["hybrid", "keyword", "semantic"];
const SEARCH_SOURCES = ["all", "visual", "transcript"];

const state = {
  q: "",
  category: "",
  collection: "", // "" | "downloads" | "creators_club" -- the folder-tree root
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
    // 303 to an HTML login page precisely so this is detectable — otherwise the
    // SPA would try to parse the login page as JSON and report nonsense.
    // Standalone (no dashboard) nothing ever returns 401, so this never fires.
    if (res.status === 401 && window.location.pathname.startsWith("/broll")) {
      const back = encodeURIComponent(window.location.pathname);
      toast("Session expired — signing in again…", "error");
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
  buildFlagToggles();
  wireHeader();
  wireModeAndFuzzyToggles();
  wireSourceToggle();
  wireDetailView();
  wireSettingsPanel();
  loadCategories();
  loadFolderTree();
  wireFolderClear();
  runSearch();
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
    runSearch();
  }, 250);
  qInput.addEventListener("input", debounced);

  $("#category-select").addEventListener("change", (e) => {
    state.category = e.target.value;
    state.offset = 0;
    // Two controls onto one piece of state: the tree must not keep highlighting
    // a folder the dropdown has just navigated away from.
    renderFolderTree();
    runSearch();
  });

  $("#pager-prev").addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - state.limit);
    runSearch();
  });
  $("#pager-next").addEventListener("click", () => {
    state.offset = state.offset + state.limit;
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
 * has no Creators_Club shares, and an empty shelf is worse than no shelf. */
async function loadFolderTree() {
  try {
    state.tree = await fetchJson("api/tree");
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
      `<span class="tree-name">${root.label}</span>` +
      `<span class="tree-count">${root.total}</span>`;
    if (state.collection === root.collection && !state.category) {
      rootBtn.classList.add("active");
    }
    rootBtn.addEventListener("click", () => selectFolder(root.collection, ""));
    rootEl.appendChild(rootBtn);

    for (const group of root.groups) {
      const groupWrap = el("div", { className: "tree-group" });
      const sep = group.slug && root.collection === "creators_club" ? "::" : "/";
      const open = state.category && state.category.split(sep)[0] === group.slug
        && state.collection === root.collection;

      const groupBtn = el("button", { className: "tree-node tree-node-group", type: "button" });
      // A leaf-less group (Uncategorised) gets no caret — there is nothing to
      // expand, and a caret that does nothing when clicked reads as broken.
      const caret = group.children.length ? (open ? "▾" : "▸") : "";
      groupBtn.innerHTML =
        `<span class="tree-caret">${caret}</span>` +
        `<span class="tree-name">${group.label}</span>` +
        `<span class="tree-count">${group.count}</span>`;
      if (state.collection === root.collection && state.category === group.slug) {
        groupBtn.classList.add("active");
      }
      groupBtn.addEventListener("click", () => selectFolder(root.collection, group.slug));
      groupWrap.appendChild(groupBtn);

      const kids = el("div", { className: `tree-children${open ? "" : " hidden"}` });
      for (const child of group.children) {
        const btn = el("button", { className: "tree-node tree-node-leaf", type: "button" });
        btn.innerHTML =
          `<span class="tree-name">${child.label}</span>` +
          `<span class="tree-count">${child.count}</span>`;
        btn.title = child.slug;
        if (state.collection === root.collection && state.category === child.slug) {
          btn.classList.add("active");
        }
        btn.addEventListener("click", () => selectFolder(root.collection, child.slug));
        kids.appendChild(btn);
      }
      groupWrap.appendChild(kids);
      rootEl.appendChild(groupWrap);
    }
    body.appendChild(rootEl);
  }
}

function selectFolder(collection, category) {
  // Clicking the folder you are already in backs out to its parent, so the
  // tree doubles as its own breadcrumb and there is no dead click.
  if (state.collection === collection && state.category === category) {
    // Back out one level. Subject slugs nest with "/", shoot slugs with "::".
    const sep = category.includes("::") ? "::" : "/";
    category = category.includes(sep) ? category.split(sep)[0] : "";
    if (!category && !state.category) collection = "";
  }
  state.collection = collection;
  state.category = category;
  state.offset = 0;
  const select = $("#category-select");
  if (select) select.value = category;
  renderFolderTree();
  runSearch();
}

/* ---------------------------------------------------------------------- */
/* Search / grid                                                          */
/* ---------------------------------------------------------------------- */

async function runSearch() {
  const params = new URLSearchParams();
  if (state.q) params.set("q", state.q);
  // Creators_Club folders are shoot paths, not subject slugs — own footage is
  // not model-indexed, so there is no subject to filter on.
  if (state.collection === "creators_club") {
    if (state.category) params.set("shoot", state.category);
  } else if (state.category) {
    params.set("category", state.category);
  }
  if (state.collection) params.set("collection", state.collection);
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
    toast(`Search failed: ${e.message}`, "error");
    return;
  }

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
  $("#results-meta").textContent = state.q
    ? `search: "${state.q}"`
    : "browsing all videos";

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
  thumb.style.height = video.width && video.height
    ? `${Math.round(SPRITE_CELL_WIDTH * (video.height / video.width))}px`
    : "135px";

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

  const body = el("div", { className: "card-body" });
  body.appendChild(el("div", { className: "card-filename", text: basename(video.rel_path) }));
  body.appendChild(
    el("div", { className: "card-category", text: video.category || video.category_hint || "—" })
  );

  const chips = el("div", { className: "card-hits" });
  for (const hit of hits.slice(0, 4)) {
    const isTranscript = hit.source === "transcript";
    const chip = el("div", {
      className: `hit-chip${isTranscript ? " hit-chip-transcript" : ""}`,
    });
    const tag = isTranscript ? "said" : "seen";
    chip.innerHTML = `<span class="hit-chip-tag">${tag}</span> ${timecode(hit.t_start, video.fps || 24)} ${renderHighlighted(hit.snippet)}`;
    chip.title = hit.description;
    chip.addEventListener("click", (e) => {
      e.stopPropagation();
      openDetail(video.id, hit.t_start);
    });
    chips.appendChild(chip);
  }
  body.appendChild(chips);

  card.appendChild(thumb);
  card.appendChild(body);
  // Open at the moment that matched, not at 0:00. The whole point of a hit is
  // that the archive is long-form: the match is often minutes in, and landing
  // at the head of a 13-minute clip means hunting for what search already
  // found. hits[0] is the best-ranked hit (search returns them ordered), and
  // the chips above seek the same way. Browse mode has no hits -> null -> 0:00.
  const seekTo = hits.length ? hits[0].t_start : null;
  card.addEventListener("click", () => openDetail(video.id, seekTo));
  return card;
}

function wireSpriteScrub(thumb, overlay, video) {
  const duration = video.duration_s || 0;
  const frameCount = Math.max(1, Math.ceil(duration / SPRITE_SECONDS_PER_FRAME));
  const cellHeight = video.width && video.height
    ? Math.round(SPRITE_CELL_WIDTH * (video.height / video.width))
    : 135;

  thumb.addEventListener("mousemove", (e) => {
    const rect = thumb.getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    const frame = Math.min(frameCount - 1, Math.floor(frac * frameCount));
    const col = frame % SPRITE_COLUMNS;
    const row = Math.floor(frame / SPRITE_COLUMNS);
    overlay.style.backgroundPosition = `-${col * SPRITE_CELL_WIDTH}px -${row * cellHeight}px`;
  });
}

/* ---------------------------------------------------------------------- */
/* Detail view                                                            */
/* ---------------------------------------------------------------------- */

function wireDetailView() {
  $("#detail-back").addEventListener("click", closeDetail);

  const seekbar = $("#seekbar");
  seekbar.addEventListener("click", (e) => {
    const video = $("#player");
    if (!state.detail || !video.duration) return;
    const rect = seekbar.getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    video.currentTime = frac * video.duration;
  });

  const player = $("#player");
  player.addEventListener("timeupdate", updatePlayhead);
  player.addEventListener("loadedmetadata", updatePlayhead);
  wireDragScrub(player);

  $("#send-resolve-btn").addEventListener("click", sendToResolve);

  document.addEventListener("keydown", onKeydown);
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
    const t = drag.startTime + (dx / drag.width) * player.duration;
    player.currentTime = Math.min(player.duration, Math.max(0, t));
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

async function openDetail(videoId, seekToSeconds) {
  let data;
  try {
    data = await fetchJson(`api/videos/${videoId}`);
  } catch (e) {
    toast(`Could not load video: ${e.message}`, "error");
    return;
  }
  state.detail = data;
  state.inPoint = null;
  state.outPoint = null;
  resetShuttle();

  $("#grid-view").classList.add("hidden");
  $("#detail-view").classList.remove("hidden");

  const player = $("#player");
  player.src = `media/proxy/${videoId}.mp4`;
  player.playbackRate = 1;
  player.load();

  renderVideoMeta(data);
  renderSegmentList(data);
  renderTranscriptList(data);
  renderSeekMarkers(data);
  renderInOutRange();
  $("#tc-in").textContent = "--:--:--:--";
  $("#tc-out").textContent = "--:--:--:--";
  $("#tc-rate").textContent = "1x";

  if (seekToSeconds != null) {
    player.addEventListener(
      "loadedmetadata",
      () => {
        player.currentTime = seekToSeconds;
      },
      { once: true }
    );
  }
}

function closeDetail() {
  const player = $("#player");
  player.pause();
  player.removeAttribute("src");
  player.load();
  state.detail = null;
  resetShuttle();
  $("#detail-view").classList.add("hidden");
  $("#grid-view").classList.remove("hidden");
}

function renderVideoMeta(data) {
  const { video, themes, quality_flags } = data;
  const meta = $("#video-meta");
  meta.innerHTML = "";
  meta.appendChild(el("div", { className: "title", text: basename(video.rel_path) }));
  meta.appendChild(
    el("div", {
      text: `${video.share}/${video.rel_path} — ${formatDuration(video.duration_s)} @ ${video.fps || "?"}fps`,
    })
  );
  meta.appendChild(el("div", { text: `category: ${video.category || video.category_hint || "—"}` }));
  if (themes && themes.length) {
    meta.appendChild(el("div", { text: `themes: ${themes.join(", ")}` }));
  }
  if (quality_flags && quality_flags.length) {
    meta.appendChild(el("div", { text: `flags: ${quality_flags.join(", ")}`, className: "muted" }));
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

function renderSeekMarkers(data) {
  const { video, segments } = data;
  const markersEl = $("#seekbar-markers");
  markersEl.innerHTML = "";
  const duration = video.duration_s || 0;
  if (!duration) return;
  for (const seg of segments) {
    const marker = el("div", { className: "seekbar-marker" });
    marker.style.left = `${(seg.t_start / duration) * 100}%`;
    markersEl.appendChild(marker);
  }
}

function updatePlayhead() {
  const player = $("#player");
  if (!state.detail) return;
  const duration = player.duration || state.detail.video.duration_s || 0;
  if (duration > 0) {
    $("#seekbar-playhead").style.left = `${(player.currentTime / duration) * 100}%`;
  }
  $("#tc-current").textContent = timecode(player.currentTime, state.detail.video.fps || 24);
}

function renderInOutRange() {
  const rangeEl = $("#seekbar-range");
  const duration = state.detail ? state.detail.video.duration_s || 0 : 0;
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
      sendToResolve();
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

async function sendToResolve() {
  if (!state.detail) return;
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
    share: video.share,
    rel_path: video.rel_path,
    in_frame: inFrame,
    out_frame: outFrame,
    fps: fps,
    mode: "append",
  };

  let res;
  try {
    res = await fetch(`${COMPANION_URL}/insert`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    toast("Companion app not running — download it from Settings", "error");
    return;
  }

  let body = null;
  try {
    body = await res.json();
  } catch (e) {
    body = null;
  }

  if (!res.ok || !body || body.ok === false) {
    const message = (body && body.message) || `Companion returned HTTP ${res.status}`;
    toast(message, "error");
    return;
  }

  toast(body.message || "Sent to Resolve.", "success");
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
    row.innerHTML = `<span class="share-name mono">${escapeHtml(s.share)}</span> — <span class="share-desc">${escapeHtml(s.description)}</span>`;
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
    text.textContent = "not reachable — companion app not running";
  }
}
