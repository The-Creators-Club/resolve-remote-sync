"use strict";

/* ==========================================================================
   Ingest panel: drag clips in, the editor's own machine indexes them.
   docs/BROLL_INGEST_PLAN.md §5 (browser mechanics), 2026-08-18.

   THREE PARTIES, and this file talks to two of them:
     - this app (document-relative `api/…` URLs, the session routes of
       app/routes_batches.py) mints the batch and owns the truth about it;
     - the editor's OWN companion (`http://127.0.0.1:8899`, absolute on
       purpose - a different process, not this app) stages the bytes and does
       the crunching.
   The browser never carries a work order: it hands the companion a batch uid
   and the companion fetches the manifest itself under the fleet token. Same
   principle as /music/send.

   A second classic script rather than a module or an addition to app.js: it
   shares app.js's helpers ($, el, toast, fetchJson, escapeHtml, debounce)
   through the global scope, which means NO NAME MAY BE DECLARED TWICE - two
   classic scripts share one global lexical environment and a duplicate `const`
   is a SyntaxError that takes the whole page down, search included. Everything
   here is therefore `ingest`/`ING` prefixed, and tests/test_ingest_ui.py fails
   the build if a name ever collides.
   ========================================================================== */

/* What the browser will even look at in a drop. THE CANONICAL LIST is
   `ccsync_dashboard.provision.VIDEO_EXTENSIONS`, published read-only by
   `GET /api/v1/site` as `video_extensions` precisely so a client reads it
   instead of growing a fourth copy (2026-08-17, COMMERCIAL_READINESS item 11).
   This constant is only the fallback for the standalone dev loop, where that
   endpoint 404s. */
const ING_VIDEO_EXTS_FALLBACK = [
  ".braw", ".mov", ".mp4", ".mxf", ".avi", ".mts", ".m2ts", ".mkv",
  ".r3d", ".crm", ".mpg", ".mpeg", ".wmv", ".webm", ".insv", ".360",
];

// schemas.MAX_BATCH_ITEMS. Enforced here too so a dropped card of 6,000 files
// is refused before 6,000 thumbnails are decoded, not after the server 422s.
const ING_MAX_ITEMS = 2000;
/* UX-17 (resilience sweep 2026-08-28). ING_MAX_ITEMS is a COUNT cap and was
   the only ceiling this panel had: dropping a 200 GB shoot started staging it,
   and the space refusal fired per file, mid-batch, once part of the drop was
   already on the disk. These two are the size half - a hard refusal against
   the companion's own free_bytes, and a confirmation (C-7) above a threshold
   where the honest answer is "this will run for hours". */
const ING_CONFIRM_BYTES = 50e9;
/* Rough, and deliberately so: the number exists to say "hours, not minutes"
   before an editor commits an evening to it. Measured throughput on the base
   rig is ~1.5 minutes per clip at Good on a 4090; a slower machine is worse.
*/
const ING_MINUTES_PER_CLIP = 1.5;

// archive_names.safe_name, character for character: exactly what Windows
// forbids and nothing else, so CJK shoot names survive. The server re-validates
// and answers 422 with the name it wanted (routes_batches._validated_share) -
// this is a courtesy, never the check.
const ING_UNSAFE = /[<>:"/\\|?*\x00-\x1f]/g;
const ING_MAX_STEM = 90;

// Two video decoders at a time. A dropped card is 200 clips; letting the
// browser open 200 <video> elements at once wedges the tab for minutes.
const ING_THUMB_CONCURRENCY = 2;
const ING_THUMB_W = 160;
const ING_THUMB_H = 90;
// A frame that is neither black leader nor past the end of a short clip.
const ING_THUMB_SEEK_FRACTION = 0.1;
const ING_THUMB_SEEK_MAX = 1;
const ING_THUMB_TIMEOUT_MS = 8000;

// Two uploads at a time, for the same reason: the companion writes them to a
// staging dir on the same disk it is about to read from.
const ING_UPLOAD_CONCURRENCY = 2;

const ING_LOOPBACK_POLL_MS = 1500;   // the companion's own view (plan §5)
const ING_SERVER_POLL_MS = 5000;     // the truth after a reload
const ING_BATCH_LIST_MS = 10000;

const ING_TIER_LABELS = {
  good: "Good: Qwen3-VL 4B, needs about 8 GB of VRAM",
  best: "Best: Qwen3-VL 8B, needs about 12 GB of VRAM",
};

/* The one place this file says "the companion is not answering". Repeated
   verbatim from the /insert path's lesson (2026-08-12): a rejected fetch is
   NOT proof the companion is down - Chrome's local-network permission blocks a
   plain-http dashboard origin from reaching 127.0.0.1 with the identical
   error. /status in a tab is never gated, so it disambiguates. */
const ING_COMPANION_HINT =
  "not reachable: companion not running, or the browser blocked local " +
  "connections (self-test: open http://127.0.0.1:8899/status in a tab; if " +
  "that shows ok:true it is the browser, not the companion)";

const ing = {
  open: false,
  items: [],          // the drop, in order
  stagingId: null,
  staged: false,      // prepare has answered for the CURRENT item set
  caps: null,         // GET /broll/ingest/capabilities, or null
  capsError: "",
  videoExts: ING_VIDEO_EXTS_FALLBACK.slice(),
  siteTier: "good",
  tier: "",           // "" until the site manifest / capabilities have spoken
  runMode: "idle",
  batchUid: null,
  batch: null,        // the server's view of the running batch
  batchItems: [],
  loopback: null,     // the companion's view (progress)
  notice: "",
  scope: "mine",
  adminAll: false,    // GET ?scope=all did not 403
  batches: [],
  expanded: "",       // batch uid whose per-clip list is open
  expandedItems: [],
  precheckKey: "",
  running: false,     // a batch has been dispatched from THIS page
  // `prepare`/`precheck` are debounce timeouts, not pollers: ingestStopPolling
  // must leave them alone or closing the drawer mid-typing loses the staging.
  timers: { loopback: null, server: null, list: null, prepare: null, precheck: null },
  thumbActive: 0,
  thumbQueue: [],
};

/* ---------------------------------------------------------------------- */
/* Wiring                                                                  */
/* ---------------------------------------------------------------------- */

document.addEventListener("DOMContentLoaded", ingestInit);

function ingestInit() {
  const btn = document.getElementById("ingest-btn");
  if (!btn) return;   // markup absent (a stale index.html) - stay inert
  btn.addEventListener("click", ingestToggle);
  $("#ingest-close").addEventListener("click", ingestClose);
  $("#ingest-recheck").addEventListener("click", () => ingestCapabilities(true));
  $("#ingest-notice-dismiss").addEventListener("click", () => ingestSetNotice(""));
  $("#ingest-pick-files").addEventListener("click", () => ingestPick("files"));
  $("#ingest-pick-folder").addEventListener("click", () => ingestPick("folder"));
  $("#ingest-run").addEventListener("click", ingestRun);
  $("#ingest-clear").addEventListener("click", ingestClearDrop);
  $("#ingest-pause").addEventListener("click", () => ingestControl("pause"));
  $("#ingest-resume").addEventListener("click", () => ingestControl("resume"));
  $("#ingest-start-now").addEventListener("click", () => ingestControl("start_now"));
  $("#ingest-pause-upload").addEventListener("click", ingestToggleUploadPause);
  $("#ingest-cancel").addEventListener("click", ingestCancelBatch);

  const share = $("#ingest-share");
  // Sanitised as they type, not on submit: an editor who typed `2026/07 shoot`
  // should see `2026_07 shoot` while the caret is still in the field, rather
  // than meet a 422 after the drop is staged.
  share.addEventListener("input", () => {
    // Once the editor has typed, a later drop never overwrites their name.
    share.dataset.touched = "1";
    const cleaned = ingestSafeName(share.value);
    if (cleaned !== share.value) {
      const at = share.selectionStart;
      share.value = cleaned;
      try { share.setSelectionRange(at, at); } catch { /* detached */ }
    }
    ingestSchedulePrecheck();
    ingestRenderSummary();
  });

  $("#ingest-keep-subfolders").addEventListener("change", () => {
    ingestSchedulePrecheck();
    ingestRenderPreview();
  });
  $("#ingest-upload-originals").addEventListener("change", ingestRenderSummary);
  for (const radio of document.querySelectorAll('input[name="ingest-run-mode"]')) {
    radio.addEventListener("change", () => {
      ing.runMode = radio.checked ? radio.value : ing.runMode;
      ingestRenderSummary();
    });
  }
  for (const tab of document.querySelectorAll("#ingest-scope-tabs .mode-btn")) {
    tab.addEventListener("click", () => {
      ing.scope = tab.dataset.scope;
      ingestSyncScopeTabs();
      ingestLoadBatches();
    });
  }
  // Escape closes the drawer from anywhere in it, including from inside the
  // shoot-name field: a fixed panel with no keyboard way out is a trap for
  // anyone not using a mouse. app.js's player shortcuts cannot collide --
  // they return early unless a clip detail is open and the target is not an
  // input.
  // UX-17: closing the tab mid-upload loses the un-run drop entirely (only a
  // DISPATCHED batch is re-attached on reload), and the bytes already streamed
  // into staging go with it. The browser shows its own wording; the string is
  // required for older engines and shown by none of them.
  window.addEventListener("beforeunload", (e) => {
    if (!ingestUploadsInFlight()) return undefined;
    e.preventDefault();
    e.returnValue = "Clips are still being copied to this computer.";
    return e.returnValue;
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && ing.open) ingestClose();
  });

  ingestSyncScopeTabs();
  ingestWireDropzone();
  ingestLoadSite();
  ingestRenderSummary();
}

function ingestToggle() {
  if (ing.open) ingestClose(); else ingestOpen();
}

function ingestOpen() {
  ing.open = true;
  $("#ingest-panel").classList.remove("hidden");
  ingestCapabilities(false);
  ingestLoadBatches();
  ingestProbeAdminScope();
  ingestStartPolling();
}

function ingestClose() {
  ing.open = false;
  $("#ingest-panel").classList.add("hidden");
  // Polling follows the panel: a batch's truth is in the database, so a closed
  // drawer costs nothing to stop and the server view is re-read on reopen.
  ingestStopPolling();
}

/* ---------------------------------------------------------------------- */
/* The drop: window-level, with a depth counter                            */
/* ---------------------------------------------------------------------- */

/* dragenter/dragleave fire per element crossed, not per window, so a naive
   handler flickers the veil off the moment the pointer moves between two
   cards. The counter is music/web/static/app.js's wireDropzone pattern. */
function ingestWireDropzone() {
  let depth = 0;
  const veil = $("#ingest-veil");
  const hasFiles = (e) =>
    e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");

  window.addEventListener("dragenter", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    depth++;
    veil.classList.add("on");
    $("#ingest-drop").classList.add("on");
  });
  // Without a preventDefault on dragover the browser navigates to the file.
  window.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
  window.addEventListener("dragleave", (e) => {
    if (!hasFiles(e)) return;
    depth = Math.max(0, depth - 1);
    if (!depth) {
      veil.classList.remove("on");
      $("#ingest-drop").classList.remove("on");
    }
  });
  window.addEventListener("drop", async (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    depth = 0;
    veil.classList.remove("on");
    $("#ingest-drop").classList.remove("on");
    if (!ing.open) ingestOpen();      // §5: a drop opens the panel
    await ingestCollect(e.dataTransfer);
  });
}

/* A DataTransfer is neutered the instant this handler yields, so every entry
   is taken SYNCHRONOUSLY first and only then walked. Reading dt.items after an
   await returns an empty list in Chrome - which looked exactly like "the drop
   contained no videos". */
async function ingestCollect(dt) {
  const roots = [];
  for (const item of Array.from(dt.items || [])) {
    const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
    if (entry) roots.push(entry);
  }
  const plainFiles = Array.from(dt.files || []);

  const out = [];
  // UX-17: a mixed drop used to discard its non-video half with no message at
  // all, so an editor who dropped a card folder saw "40 clips" where they had
  // dropped 60 files and never learned why.
  const skipped = { n: 0 };
  if (roots.length) {
    // A single dropped folder IS the shoot, so its own name is stripped from
    // rel_dir and offered as the shoot name instead. Two folders dropped
    // together are two shelves of one shoot, so their names stay in rel_dir -
    // stripping both would merge `Day1/A001` and `Day2/A001` into one folder.
    const onlyFolder = roots.length === 1 && roots[0].isDirectory ? roots[0].name : "";
    for (const entry of roots) await ingestWalkEntry(entry, onlyFolder, out, skipped);
    if (onlyFolder) ingestSuggestShare(onlyFolder);
  } else {
    // No entry API (Firefox pre-50, or a synthetic drop): flat files only.
    for (const file of plainFiles) {
      if (!ingestIsVideo(file.name)) { skipped.n++; continue; }
      const rel = (file.webkitRelativePath || "").split("/").slice(0, -1).join("/");
      out.push(ingestMakeItem(file.name, file.size, rel, "upload", null, file));
    }
  }
  if (skipped.n) {
    const total = out.length + skipped.n;
    toast(`${skipped.n} of ${total} files were not video and were left out.`, "warn");
  }
  ingestAddItems(out);
}

/** UX-17: the whole drop measured against the companion's own free space,
 *  BEFORE the first byte. Returns a refusal sentence, or "" to go ahead.
 *  A companion that has not answered yet, or one that could not measure the
 *  drive, refuses NOTHING: "I could not tell" must never read as "no". */
function ingestSpaceRefusal(items) {
  const staging = (ing.caps && ing.caps.staging) || null;
  if (!staging || typeof staging.free_bytes !== "number") return "";
  // Only uploads consume staging: a picked path is indexed where it is.
  const wanted = items.reduce(
    (sum, i) => sum + (i.source === "upload" ? (i.size || 0) : 0), 0);
  if (!wanted) return "";
  const floor = Number(staging.floor_bytes) || 0;
  if (staging.free_bytes >= wanted + floor) return "";
  return `That drop is ${ingestBytes(wanted)} and this computer has ` +
         `${ingestBytes(staging.free_bytes)} free where clips are staged` +
         (floor ? `, of which ${ingestBytes(floor)} is kept clear` : "") +
         ". Nothing was staged. Free some space, or drop fewer clips at a time.";
}

/* readEntries is documented to return AT MOST 100 entries per call in Chrome
   and to signal the end of the directory with an empty array - not with the
   first short read. Calling it once silently dropped every clip past the
   hundredth of a camera card. */
async function ingestWalkEntry(entry, stripTop, out, skipped) {
  if (out.length >= ING_MAX_ITEMS) return;
  if (entry.isFile) {
    if (!ingestIsVideo(entry.name)) { if (skipped) skipped.n++; return; }
    const file = await new Promise((res) => entry.file(res, () => res(null)));
    if (!file) return;
    out.push(ingestMakeItem(entry.name, file.size,
                            ingestRelDir(entry.fullPath, stripTop), "upload", null, file));
    return;
  }
  if (!entry.isDirectory) return;
  const reader = entry.createReader();
  for (;;) {
    const chunk = await new Promise((res) => reader.readEntries(res, () => res([])));
    if (!chunk.length) break;
    for (const child of chunk) {
      await ingestWalkEntry(child, stripTop, out, skipped);
      if (out.length >= ING_MAX_ITEMS) return;
    }
  }
}

/** `/Shoot/Day1/A001.MP4` minus the top folder and the file itself -> `Day1`. */
function ingestRelDir(fullPath, stripTop) {
  const parts = String(fullPath || "").split("/").filter(Boolean);
  parts.pop();                                    // the file
  if (stripTop && parts[0] === stripTop) parts.shift();
  return parts.join("/");
}

function ingestIsVideo(name) {
  const dot = String(name).lastIndexOf(".");
  if (dot <= 0) return false;
  return ing.videoExts.includes(String(name).slice(dot).toLowerCase());
}

function ingestMakeItem(name, size, relDir, source, path, file) {
  return {
    local_id: `i${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`,
    name: name,
    size: typeof size === "number" ? size : null,
    rel_dir: relDir || "",
    source: source,               // "upload" (bytes stream to staging) | "path"
    path: path || null,           // native picker only - indexed in place
    file: file || null,
    include: true,
    thumb: null,
    thumbTried: false,
    accepted: null,               // prepare's answer
    reason: "",
    uploading: false,
    uploadPercent: null,
    uploaded: false,
    uploadUrl: "",
    stagedIn: "",
    hash: "",
    probe: null,
    stageState: "",
    error: "",
    duplicate_of: null,
    duplicate_name: "",
    final_name: "",
    nodes: null,
  };
}

function ingestAddItems(items) {
  if (!items.length) {
    toast("Nothing there this app can index: b-roll takes video files " +
          `(${ing.videoExts.slice(0, 6).join(", ")}, …).`, "warn");
    return;
  }
  const room = ING_MAX_ITEMS - ing.items.length;
  if (room <= 0) {
    toast(`A batch holds at most ${ING_MAX_ITEMS} clips. Run this one first.`, "error");
    return;
  }
  if (items.length > room) {
    toast(`Only the first ${room} clips were taken: a batch holds ` +
          `${ING_MAX_ITEMS}.`, "warn");
    items = items.slice(0, room);
  }
  // UX-17: the WHOLE drop, refused before anything is staged. Deliberately
  // measured against what is already held plus what arrived: two 100 GB drops
  // in a row are the same 200 GB.
  const refusal = ingestSpaceRefusal([...ing.items, ...items]);
  if (refusal) {
    ingestSetNotice(refusal);
    toast(refusal, "error");
    return;
  }
  ing.items.push(...items);
  ing.staged = false;
  ing.precheckKey = "";
  if (!$("#ingest-share").value) ingestSuggestShare("");
  ingestRenderPreview();
  ingestRenderSummary();
  for (const item of items) if (item.file) ingestQueueThumb(item);
  ingestSchedulePrepare();
  // Final names are worth showing before a single byte has moved; the
  // duplicate answers arrive later, when the hashes do.
  ingestSchedulePrecheck();
}

function ingestClearDrop() {
  if (ing.running) return;
  ing.items = [];
  ing.stagingId = null;
  ing.staged = false;
  ing.precheckKey = "";
  ingestRenderPreview();
  ingestRenderSummary();
}

/** The default shoot name: the dropped folder, else today's date. */
function ingestSuggestShare(folderName) {
  const field = $("#ingest-share");
  if (field.value && field.dataset.touched === "1") return;
  const now = new Date();
  const stamp = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-` +
                `${String(now.getDate()).padStart(2, "0")}`;
  field.value = ingestSafeName(folderName || `${stamp} ingest`);
  ingestSchedulePrecheck();
}

/** archive_names.safe_name in JS. The server decides; this only spares a 422. */
function ingestSafeName(name) {
  let cleaned = String(name || "").replace(ING_UNSAFE, "_").replace(/[. ]+$/, "");
  if (cleaned.length > ING_MAX_STEM) {
    cleaned = cleaned.slice(0, ING_MAX_STEM).replace(/[. ]+$/, "");
  }
  return cleaned;
}

/* ---------------------------------------------------------------------- */
/* Thumbnails                                                              */
/* ---------------------------------------------------------------------- */

/* Dropped Files are decoded in the page (nothing has been uploaded yet, so
   there is no server that could make a poster). Formats no browser decodes -
   BRAW, R3D, most MXF - never produce one: the row says "no preview" until the
   companion's own thumb arrives from staging, which is ffmpeg's answer and
   understands all of them. */
function ingestQueueThumb(item) {
  ing.thumbQueue.push(item);
  ingestPumpThumbs();
}

function ingestPumpThumbs() {
  while (ing.thumbActive < ING_THUMB_CONCURRENCY && ing.thumbQueue.length) {
    const item = ing.thumbQueue.shift();
    ing.thumbActive++;
    ingestMakeThumb(item.file)
      .then((url) => { item.thumb = url; })
      .catch(() => { item.thumb = null; })
      .then(() => {
        item.thumbTried = true;
        ing.thumbActive--;
        ingestUpdateRow(item);
        ingestPumpThumbs();
      });
  }
}

function ingestMakeThumb(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const video = document.createElement("video");
    video.muted = true;
    video.preload = "metadata";
    video.playsInline = true;
    let done = false;
    const finish = (value, err) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      video.removeAttribute("src");
      try { video.load(); } catch { /* already torn down */ }
      URL.revokeObjectURL(url);
      if (err) reject(err); else resolve(value);
    };
    const timer = setTimeout(() => finish(null, new Error("timeout")),
                             ING_THUMB_TIMEOUT_MS);
    video.addEventListener("loadedmetadata", () => {
      const duration = video.duration;
      if (!isFinite(duration) || duration <= 0) return finish(null, new Error("no duration"));
      video.currentTime = Math.min(ING_THUMB_SEEK_MAX, duration * ING_THUMB_SEEK_FRACTION);
    });
    video.addEventListener("seeked", () => {
      try {
        const canvas = document.createElement("canvas");
        canvas.width = ING_THUMB_W;
        canvas.height = ING_THUMB_H;
        canvas.getContext("2d").drawImage(video, 0, 0, ING_THUMB_W, ING_THUMB_H);
        finish(canvas.toDataURL("image/jpeg", 0.7));
      } catch (e) {
        finish(null, e);
      }
    });
    video.addEventListener("error", () => finish(null, new Error("undecodable")));
    video.src = url;
  });
}

/** The companion's own thumbnail, once an item is staged. Absolute (loopback),
 *  like every other 8899 URL here. */
function ingestThumbUrl(item) {
  if (!ing.stagingId || item.stagedIn !== ing.stagingId) return "";
  return `${COMPANION_URL}/broll/ingest/thumb?staging_id=` +
         `${encodeURIComponent(ing.stagingId)}&local_id=${encodeURIComponent(item.local_id)}`;
}

/* ---------------------------------------------------------------------- */
/* The companion: capabilities, native picker, staging                     */
/* ---------------------------------------------------------------------- */

/** Every 8899 call goes through here so exactly one place knows that a
 *  rejected fetch is ambiguous, and so fetchJson's session-expiry redirect
 *  (which belongs to THIS app's routes) can never fire against the loopback. */
async function ingestLoopback(method, path, body) {
  const opts = { method: method };
  if (body !== undefined) {
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`${COMPANION_URL}${path}`, opts);
  let parsed = null;
  try { parsed = await res.json(); } catch { parsed = null; }
  if (!res.ok) {
    const err = new Error((parsed && (parsed.message || parsed.detail)) ||
                          `companion returned HTTP ${res.status}`);
    err.status = res.status;
    err.body = parsed;
    throw err;
  }
  return parsed;
}

async function ingestCapabilities(loud) {
  const dot = $("#ingest-dot");
  const text = $("#ingest-companion-text");
  dot.className = "status-dot status-unknown";
  text.textContent = "checking…";
  try {
    ing.caps = await ingestLoopback("GET", "/broll/ingest/capabilities");
    ing.capsError = "";
  } catch (e) {
    ing.caps = null;
    // A companion published before this feature existed answers 404 on every
    // /broll/ingest route - the same "editors need a republished companion"
    // gap /music/* had. Worth its own sentence: nothing is wrong with it.
    ing.capsError = e.status === 404
      ? "your companion app is too old for b-roll ingest: update it from the " +
        "tray icon (check for updates), then reload this page"
      : ING_COMPANION_HINT;
    dot.className = "status-dot status-bad";
    text.textContent = ing.capsError;
    ingestRenderTiers();
    ingestRenderSummary();
    if (loud) toast(ing.capsError, "error");
    return;
  }
  const caps = ing.caps;
  const gpu = caps.gpu || {};
  dot.className = `status-dot ${caps.ok ? "status-ok" : "status-bad"}`;
  const bits = [`v${caps.version || "?"}`];
  if (gpu.detail) bits.push(gpu.detail);
  else if (gpu.vram_gb) bits.push(`${gpu.vram_gb} GB VRAM`);
  else if (gpu.present === false) bits.push("no GPU");
  text.textContent = caps.ok
    ? `connected (${bits.join(", ")})`
    : `companion can't index yet: ${(caps.reasons || []).join("; ") || "unknown"}`;
  if (!ing.tier) ing.tier = ingestDefaultTier();
  ingestRenderTiers();
  ingestRenderSummary();
}

/** The site's chosen tier unless this GPU cannot hold it. */
function ingestDefaultTier() {
  const wanted = ing.siteTier || "good";
  if (ingestTierFits(wanted)) return wanted;
  const recommended = ing.caps && ing.caps.recommended_tier;
  if (recommended && ingestTierFits(recommended)) return recommended;
  return ingestTierFits("good") ? "good" : wanted;
}

/** capabilities publishes `tiers.{good,best}`. `fits` is the documented key
 *  (plan §4.1); `fit` is accepted too because the loopback half of this
 *  feature was written in parallel and one letter must not disable both
 *  models. Unknown (no capabilities yet) is NOT a refusal - the companion
 *  refuses the run itself, with the VRAM numbers in the message. */
function ingestTierInfo(tier) {
  const tiers = (ing.caps && ing.caps.tiers) || {};
  return tiers[tier] || null;
}

function ingestTierFits(tier) {
  const info = ingestTierInfo(tier);
  if (!info) return true;
  const fits = info.fits !== undefined ? info.fits : info.fit;
  return fits !== false;
}

async function ingestLoadSite() {
  // Document-relative: mounted at /broll this reaches the dashboard's
  // /api/v1/site; standalone it 404s and the fallbacks stand.
  try {
    const site = await fetchJson("../api/v1/site");
    if (site && site.indexer && site.indexer.model_tier) {
      ing.siteTier = site.indexer.model_tier;
    }
    if (Array.isArray(site && site.video_extensions) && site.video_extensions.length) {
      ing.videoExts = site.video_extensions.map((e) => String(e).toLowerCase());
    }
  } catch {
    /* standalone dev loop, or an older dashboard - fallbacks stand */
  }
  if (!ing.tier) ing.tier = ingestDefaultTier();
  ingestRenderTiers();
}

/** "Choose from this computer…": real paths, indexed where they are. */
async function ingestPick(kind) {
  let answer;
  try {
    answer = await ingestLoopback("POST", "/broll/ingest/pick", { kind: kind });
  } catch (e) {
    toast(e.status === 404 ? ing.capsError || ING_COMPANION_HINT : e.message, "error");
    return;
  }
  if (!answer || answer.ok === false) {
    if (answer && answer.message && answer.message !== "cancelled") {
      toast(answer.message, "error");
    }
    return;
  }
  const picked = (answer.files || [])
    .filter((f) => ingestIsVideo(f.name || f.path || ""))
    .map((f) => ingestMakeItem(f.name || "", f.size, f.rel_dir || "", "path", f.path, null));
  if (kind === "folder" && picked.length && picked[0].path) {
    // The folder the editor pointed at, taken from the first path so the shoot
    // name matches what a drag of the same folder would have produced.
    const parts = String(picked[0].path).replace(/\\/g, "/").split("/").filter(Boolean);
    const relDepth = picked[0].rel_dir ? picked[0].rel_dir.split("/").length : 0;
    const top = parts[parts.length - 2 - relDepth];
    if (top) ingestSuggestShare(top);
  }
  ingestAddItems(picked);
}

function ingestSchedulePrepare() {
  clearTimeout(ing.timers.prepare);
  // A multi-select drop arrives as several adds; one prepare for the settled
  // set beats one staging dir per keystroke of the mouse.
  ing.timers.prepare = setTimeout(ingestPrepare, 700);
}

async function ingestPrepare() {
  if (ing.running || !ing.items.length) return;
  // A drop opens the panel and the capability probe races the debounce; if the
  // probe has not landed yet, wait for it rather than returning silently -- a
  // prepare that never happens is a Run button that never enables, with
  // nothing on screen to say why.
  if (!ing.caps) await ingestCapabilities(false);
  if (!ing.caps) {
    ingestSetNotice(`Your companion app is not answering, so these clips cannot ` +
                    `be staged: ${ing.capsError || ING_COMPANION_HINT}`);
    return;
  }
  const body = {
    share_hint: $("#ingest-share").value,
    items: ing.items.map((it) => ({
      local_id: it.local_id,
      name: it.name,
      size: it.size,
      source: it.source,
      path: it.path || undefined,
      rel_dir: it.rel_dir,
    })),
  };
  let answer;
  try {
    answer = await ingestLoopback("POST", "/broll/ingest/prepare", body);
  } catch (e) {
    ingestSetNotice(`The companion could not stage this drop: ${e.message}`);
    return;
  }
  ing.stagingId = answer.staging_id || null;
  const byId = new Map((answer.items || []).map((r) => [r.local_id, r]));
  for (const item of ing.items) {
    const row = byId.get(item.local_id);
    if (!row) continue;
    item.accepted = row.accepted !== false;
    item.reason = row.reason || "";
    item.uploadUrl = row.upload_url || "";
    item.stagedIn = ing.stagingId;
    // A second drop re-stages EVERYTHING under a new staging id, so bytes that
    // reached the old one no longer exist as far as this batch is concerned.
    // Resetting here is what stops an item being "uploaded" into a directory
    // the companion has forgotten.
    item.uploaded = item.source === "path";
    item.uploadPercent = null;
    item.error = "";
    if (!item.accepted) item.include = false;
  }
  ing.staged = true;
  ingestRenderPreview();
  ingestStartPolling();
  ingestPumpUploads();
}

/* Bytes go up by XMLHttpRequest, not fetch: `upload.onprogress` is the only
   way a browser reports how far a request BODY has got, and a 4 GB camera file
   with no progress bar reads as a hung page. */
function ingestPumpUploads() {
  let active = ing.items.filter((i) => i.uploading).length;
  for (const item of ing.items) {
    if (active >= ING_UPLOAD_CONCURRENCY) break;
    if (item.source !== "upload" || !item.accepted || item.uploaded ||
        item.uploading || !item.include || item.error) continue;
    active++;
    ingestUploadItem(item);
  }
}

function ingestUploadItem(item) {
  item.uploading = true;
  item.uploadPercent = 0;
  ingestUpdateRow(item);
  const url = item.uploadUrl ||
    `${COMPANION_URL}/broll/ingest/upload/${encodeURIComponent(ing.stagingId)}/` +
    `${encodeURIComponent(item.local_id)}`;
  const xhr = new XMLHttpRequest();
  xhr.open("PUT", url.startsWith("http") ? url : `${COMPANION_URL}${url}`);
  xhr.setRequestHeader("Content-Type", "application/octet-stream");
  // The CSRF half of the loopback contract (plan §4.1): a custom header forces
  // a preflight, so a hostile page can never stream bytes into staging.
  xhr.setRequestHeader("X-CCSync-Ingest", "1");
  xhr.upload.onprogress = (e) => {
    item.uploadPercent = e.lengthComputable ? Math.round((e.loaded / e.total) * 100) : null;
    ingestUpdateRow(item);
  };
  const done = (ok, message) => {
    item.uploading = false;
    item.uploaded = ok;
    if (!ok) item.error = message;
    ingestUpdateRow(item);
    ingestPumpUploads();
  };
  xhr.onload = () => {
    let body = null;
    try { body = JSON.parse(xhr.responseText); } catch { body = null; }
    // 409 = these bytes are already in staging (a re-prepare of the same drop,
    // or a double click). That is success, not a failure to show an editor.
    if (xhr.status === 409) return done(true, "");
    if (xhr.status < 200 || xhr.status >= 300) {
      return done(false, (body && (body.message || body.detail)) ||
                         `upload failed (HTTP ${xhr.status})`);
    }
    if (body && body.hash) item.hash = body.hash;
    if (body && body.probe) item.probe = body.probe;
    item.uploadPercent = 100;
    done(true, "");
  };
  xhr.onerror = () => done(false, "upload failed. Is the companion still running?");
  xhr.send(item.file);
}

/* ---------------------------------------------------------------------- */
/* Polling: the companion 1.5 s, the server 5 s                            */
/* ---------------------------------------------------------------------- */

function ingestStartPolling() {
  ingestStopPolling();
  if (!ing.open) return;
  ing.timers.loopback = setInterval(ingestPollLoopback, ING_LOOPBACK_POLL_MS);
  ing.timers.server = setInterval(ingestPollServer, ING_SERVER_POLL_MS);
  ing.timers.list = setInterval(ingestLoadBatches, ING_BATCH_LIST_MS);
  ingestPollLoopback();
  ingestPollServer();
}

function ingestStopPolling() {
  for (const key of Object.keys(ing.timers)) {
    if (key === "prepare" || key === "precheck") continue;
    clearInterval(ing.timers[key]);
    ing.timers[key] = null;
  }
}

async function ingestPollLoopback() {
  if (!ing.open || (!ing.stagingId && !ing.batchUid)) return;
  let answer;
  try {
    answer = await ingestLoopback(
      "GET", `/broll/ingest/progress?staging_id=${encodeURIComponent(ing.stagingId || "")}`);
  } catch {
    ing.loopback = null;
    ingestRenderLive();
    return;
  }
  ing.loopback = answer;
  const staging = (answer && answer.staging && answer.staging.items) || [];
  const byId = new Map(staging.map((r) => [r.local_id, r]));
  for (const item of ing.items) {
    const row = byId.get(item.local_id);
    if (!row) continue;
    item.stageState = row.state || item.stageState;
    if (row.hash) item.hash = row.hash;
    if (row.probe) item.probe = row.probe;
    if (row.error) item.error = row.error;
    ingestUpdateRow(item);
  }
  ingestMaybePrecheck();
  ingestRenderLive();
}

async function ingestPollServer() {
  if (!ing.open || !ing.batchUid) return;
  try {
    const answer = await fetchJson(`api/ingest-batches/${encodeURIComponent(ing.batchUid)}`);
    ing.batch = answer.batch;
    ing.batchItems = answer.items || [];
    // The server is the truth after a reload - when it says the batch is over,
    // the live view stops claiming otherwise even if the companion is silent.
    if (["done", "done_with_errors", "cancelled", "failed"].includes(ing.batch.state)) {
      ing.running = false;
    }
  } catch {
    /* transient - the batch list poll will catch up */
  }
  ingestRenderLive();
}

/* ---------------------------------------------------------------------- */
/* Pre-check: duplicates and final names                                   */
/* ---------------------------------------------------------------------- */

function ingestSchedulePrecheck() {
  ing.precheckKey = "";
  clearTimeout(ing.timers.precheck);
  ing.timers.precheck = setTimeout(ingestMaybePrecheck, 400);
}

/** Runs once per (shoot name, keep-subfolders, set of hashes): a hash arriving
 *  from staging changes the answer, and nothing else does. */
function ingestMaybePrecheck() {
  if (ing.running || !ing.items.length) return;
  const share = $("#ingest-share").value;
  if (!share) return;
  const keep = $("#ingest-keep-subfolders").checked ? "1" : "0";
  const key = `${share}|${keep}|${ing.items.map((i) => `${i.local_id}:${i.hash}`).join(",")}`;
  if (key === ing.precheckKey) return;
  ing.precheckKey = key;
  ingestPrecheck(share, keep === "1");
}

async function ingestPrecheck(share, keepSubfolders) {
  let answer;
  try {
    answer = await fetchJson("api/ingest-batches/precheck", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        share: share,
        keep_subfolders: keepSubfolders,
        items: ing.items.map((it) => ({
          local_id: it.local_id,
          name: it.name,
          rel_dir: it.rel_dir,
          size: it.size,
          hash: it.hash || null,
          source: it.source,
        })),
      }),
    });
  } catch (e) {
    // 422 = the shoot name this app would have refused anyway; it carries the
    // name it wanted, which is more useful than the word "invalid".
    const suggestion = e.body && e.body.detail && e.body.detail.suggestion;
    $("#ingest-share-note").textContent = suggestion
      ? `the shoot name will be saved as “${suggestion}”`
      : "";
    // A 422 is deterministic (the name is wrong), so the key STAYS and the
    // poll does not re-ask twice a second; anything else is transient and is
    // worth retrying on the next tick.
    if (e.status !== 422) ing.precheckKey = "";
    return;
  }
  $("#ingest-share-note").textContent = "";
  const byId = new Map((answer.items || []).map((r) => [r.local_id, r]));
  for (const item of ing.items) {
    const row = byId.get(item.local_id);
    if (!row) continue;
    const wasDuplicate = item.duplicate_of;
    item.duplicate_of = row.duplicate_of;
    item.duplicate_name = row.duplicate_name || "";
    item.final_name = row.final_name || "";
    // Duplicates are unticked FOR the editor, once, the first time they are
    // discovered. Re-ticking one and then editing the shoot name must not
    // silently untick it again.
    if (item.duplicate_of && !wasDuplicate) item.include = false;
    ingestUpdateRow(item);
  }
  ingestRenderSummary();
}

/* ---------------------------------------------------------------------- */
/* Preview rows                                                            */
/* ---------------------------------------------------------------------- */

function ingestRenderPreview() {
  const box = $("#ingest-preview");
  box.innerHTML = "";
  $("#ingest-stage").classList.toggle("hidden", !ing.items.length);
  for (const item of ing.items) {
    item.nodes = null;
    box.appendChild(ingestBuildRow(item));
  }
  ingestRenderHead();
  ingestRenderSummary();
}

function ingestRenderHead() {
  const n = ing.items.length;
  const chosen = ing.items.filter((i) => i.include).length;
  $("#ingest-preview-head").textContent = n
    ? `${chosen} of ${n} clip${n === 1 ? "" : "s"} selected`
    : "";
}

function ingestBuildRow(item) {
  const row = el("div", { className: "ingest-row" });

  const tick = el("input");
  tick.type = "checkbox";
  tick.checked = item.include;
  tick.id = `ing-tick-${item.local_id}`;
  tick.addEventListener("change", () => {
    item.include = tick.checked;
    if (item.include) ingestPumpUploads();
    ingestRenderHead();
    ingestRenderSummary();
  });
  row.appendChild(tick);

  const thumb = el("div", { className: "ingest-thumb" });
  row.appendChild(thumb);

  const body = el("div", { className: "ingest-row-body" });
  const label = el("label", { className: "ingest-row-name" });
  label.setAttribute("for", tick.id);
  label.textContent = item.rel_dir ? `${item.rel_dir}/${item.name}` : item.name;
  body.appendChild(label);
  const meta = el("div", { className: "ingest-row-meta muted small" });
  body.appendChild(meta);
  const bar = el("div", { className: "ingest-bar hidden" });
  const fill = el("div", { className: "ingest-bar-fill" });
  bar.appendChild(fill);
  body.appendChild(bar);
  row.appendChild(body);

  item.nodes = { row, tick, thumb, meta, bar, fill };
  ingestUpdateRow(item);
  return row;
}

function ingestUpdateRow(item) {
  const n = item.nodes;
  if (!n) return;
  n.tick.checked = item.include;
  n.tick.disabled = ing.running || item.accepted === false;

  if (item.thumb && n.thumb.dataset.kind !== "img") {
    n.thumb.dataset.kind = "img";
    n.thumb.innerHTML = "";
    const img = el("img");
    img.src = item.thumb;
    img.alt = "";
    n.thumb.appendChild(img);
  } else if (!item.thumb) {
    const url = ingestThumbUrl(item);
    if (url && n.thumb.dataset.kind !== "companion") {
      // The companion's ffmpeg thumb: the answer for BRAW/R3D/MXF, which no
      // browser decodes. Falls back to the "no preview" text if it 404s.
      n.thumb.dataset.kind = "companion";
      n.thumb.innerHTML = "";
      const img = el("img");
      img.src = url;
      img.alt = "";
      img.addEventListener("error", () => {
        n.thumb.dataset.kind = "none";
        n.thumb.innerHTML = "";
        n.thumb.appendChild(el("span", { className: "muted small", text: "no preview" }));
      });
      n.thumb.appendChild(img);
    } else if (!url && item.thumbTried && n.thumb.dataset.kind !== "none") {
      n.thumb.dataset.kind = "none";
      n.thumb.textContent = "";
      n.thumb.appendChild(el("span", { className: "muted small", text: "no preview" }));
    }
  }

  const bits = [];
  if (item.size != null) bits.push(ingestBytes(item.size));
  if (item.probe && item.probe.duration_s) bits.push(formatDuration(item.probe.duration_s));
  if (item.source === "path") bits.push("indexed in place");
  if (item.final_name && item.final_name !== item.name) {
    bits.push(`will be saved as ${item.final_name}`);
  }
  n.meta.textContent = bits.join(" · ");
  n.meta.classList.remove("bad", "warn");

  if (item.accepted === false) {
    n.meta.textContent = item.reason || "the companion refused this clip";
    n.meta.classList.add("bad");
  } else if (item.error) {
    n.meta.textContent = item.error;
    n.meta.classList.add("bad");
  } else if (item.duplicate_of) {
    n.meta.textContent =
      `already in the archive: clip #${item.duplicate_of}` +
      (item.duplicate_name ? ` (${item.duplicate_name})` : "") +
      (bits.length ? ` · ${bits.join(" · ")}` : "");
    n.meta.classList.add("warn");
  }

  const uploading = item.uploading || (item.uploadPercent != null && !item.uploaded);
  n.bar.classList.toggle("hidden", !uploading);
  if (uploading) n.fill.style.width = `${item.uploadPercent == null ? 50 : item.uploadPercent}%`;
  ingestRenderHead();
}

/* ---------------------------------------------------------------------- */
/* Settings form                                                           */
/* ---------------------------------------------------------------------- */

function ingestRenderTiers() {
  const box = $("#ingest-tiers");
  if (!box) return;
  box.innerHTML = "";
  for (const tier of ["good", "best"]) {
    const info = ingestTierInfo(tier);
    const fits = ingestTierFits(tier);
    const label = el("label", { className: "radio-option" });
    const radio = el("input");
    radio.type = "radio";
    radio.name = "ingest-tier";
    radio.value = tier;
    radio.disabled = !fits || ing.running;
    radio.checked = tier === ing.tier;
    radio.addEventListener("change", () => {
      if (!radio.checked) return;
      ing.tier = tier;
      ingestRenderSummary();
    });
    const text = el("span", { text: ING_TIER_LABELS[tier] });
    label.appendChild(radio);
    label.appendChild(text);
    if (!fits) {
      // Named refusal, never a silently missing option: "Best is greyed out"
      // with no reason is the same bug as a tray that says nothing.
      const why = (info && (info.reason || info.detail)) ||
        `this machine's GPU can't hold it${ing.caps && ing.caps.gpu && ing.caps.gpu.vram_gb
          ? ` (${ing.caps.gpu.vram_gb} GB VRAM)` : ""}`;
      text.appendChild(el("span", { className: "muted small", text: why }));
    } else if (info && info.cached === false) {
      text.appendChild(el("span", {
        className: "muted small",
        text: `not downloaded yet${info.download_bytes || info.bytes
          ? `, about ${ingestBytes(info.download_bytes || info.bytes)}` : ""}`,
      }));
    }
    box.appendChild(label);
  }
}

function ingestRenderSummary() {
  const chosen = ing.items.filter((i) => i.include);
  const bytes = chosen.reduce((sum, i) => sum + (i.size || 0), 0);
  const when = ing.runMode === "foreground"
    ? "will run now" : "will run when you're away";
  const line = chosen.length
    ? `${chosen.length} clip${chosen.length === 1 ? "" : "s"}, ${ingestBytes(bytes)} - ${when}`
    : "nothing selected";
  $("#ingest-summary").textContent = line;
  const blocked = !chosen.length || ing.running || !ing.caps ||
                  !$("#ingest-share").value || !ing.staged;
  $("#ingest-run").disabled = blocked;
  $("#ingest-clear").disabled = ing.running;
  ingestRenderHead();
}

function ingestSetNotice(message) {
  ing.notice = message || "";
  const box = $("#ingest-notice");
  $("#ingest-notice-text").textContent = ing.notice;
  box.classList.toggle("hidden", !ing.notice);
}

/* ---------------------------------------------------------------------- */
/* Run                                                                     */
/* ---------------------------------------------------------------------- */

async function ingestRun() {
  const chosen = ing.items.filter((i) => i.include);
  if (!chosen.length) return;
  const share = $("#ingest-share").value;
  // UX-17 / C-7 (resilience sweep 2026-08-28): the consequence spelled out
  // before an evening of this machine's GPU is committed to it. Above the
  // threshold only: a four-clip drop does not need a dialog.
  const bytes = chosen.reduce((sum, i) => sum + (i.size || 0), 0);
  if (bytes >= ING_CONFIRM_BYTES) {
    const staging = (ing.caps && ing.caps.staging) || {};
    const free = typeof staging.free_bytes === "number"
      ? ingestBytes(staging.free_bytes) : "an unknown amount";
    const hours = Math.max(1, Math.round(chosen.length * ING_MINUTES_PER_CLIP / 60));
    if (!window.confirm(
      `This drop is ${ingestBytes(bytes)} across ${chosen.length} clips. ` +
      `Staging it needs ${ingestBytes(bytes)} free on this computer and it has ` +
      `${free}. Indexing will run for about ${hours} hours. Start it?`)) return;
  }
  const info = ingestTierInfo(ing.tier);
  if (info && info.cached === false) {
    // Plan §9 decision 6: consent for the download, with the byte count, BEFORE
    // anything starts - a 4 GB model on a hotel connection is the editor's
    // business, not ours.
    const size = info.download_bytes || info.bytes || info.size_bytes;
    const how = size ? `about ${ingestBytes(size)}` : "several gigabytes";
    if (!window.confirm(
      `The ${ing.tier} model isn't on this machine yet. Running this batch ` +
      `downloads it first (${how}). Continue?`)) return;
  }

  const settings = {
    tier: ing.tier || "good",
    run_mode: ing.runMode,
    upload_originals: $("#ingest-upload-originals").checked,
    keep_subfolders: $("#ingest-keep-subfolders").checked,
    transcribe: false,
  };
  $("#ingest-run").disabled = true;

  let created;
  try {
    created = await fetchJson("api/ingest-batches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        share: share,
        settings: settings,
        items: chosen.map((it) => ({
          local_id: it.local_id,
          name: it.name,
          rel_dir: it.rel_dir,
          size: it.size,
          hash: it.hash || null,
          source: it.source,
          duplicate_of: it.duplicate_of || null,
        })),
      }),
    });
  } catch (e) {
    const detail = e.body && e.body.detail;
    toast(typeof detail === "object" && detail ? detail.detail || e.message : e.message,
          "error");
    ingestRenderSummary();
    return;
  }

  ing.batchUid = created.uid;
  try {
    await ingestLoopback("POST", "/broll/ingest/run", {
      batch_uid: created.uid,
      staging_id: ing.stagingId,
      run_mode: ing.runMode,
      // `start_now` is what plan §4.1's table calls the same choice; the owner
      // review (§0) turned it into a mode. Both are sent so neither half of
      // this feature can be the one that decides.
      start_now: ing.runMode === "foreground",
    });
  } catch (e) {
    // 503 = the machine refused: the tier does not fit this GPU, or a
    // capability vanished between the probe and the click. PERSISTENT, not a
    // toast - the editor has to come back and change the model (plan §6).
    ingestSetNotice(
      e.status === 503
        ? `${e.message} The batch is queued on the server: change the model ` +
          `and run it again, or another of your machines can pick it up.`
        : `The companion did not take the batch: ${e.message}`);
    ingestLoadBatches();
    ingestRenderSummary();
    return;
  }

  ingestSetNotice("");
  ing.running = true;
  $("#ingest-live").classList.remove("hidden");
  toast(ing.runMode === "foreground"
    ? "Indexing started on this machine."
    : "Queued: it starts when you step away from this machine.", "success");
  ingestStartPolling();
  ingestLoadBatches();
  ingestRenderSummary();
}

/* ---------------------------------------------------------------------- */
/* Live view + controls                                                    */
/* ---------------------------------------------------------------------- */

function ingestRenderLive() {
  const box = $("#ingest-live-body");
  const live = $("#ingest-live");
  if (!ing.batchUid) {
    live.classList.add("hidden");
    return;
  }
  live.classList.remove("hidden");
  box.innerHTML = "";

  const batch = ing.batch;
  const lb = (ing.loopback && ing.loopback.batch) || null;
  const head = el("div", { className: "ingest-live-head" });
  head.textContent = batch
    ? `${batch.share} - ${batch.state}${batch.machine ? ` on ${batch.machine}` : ""}`
    : "waiting for the server…";
  box.appendChild(head);

  if (batch) {
    box.appendChild(el("div", {
      className: "muted small",
      text: `${batch.n_done} of ${batch.n_items} done · ${batch.n_live} in the archive · ` +
            `${batch.n_failed} failed · ${batch.n_duplicate} duplicate` +
            (batch.last_heartbeat_at ? ` · heartbeat ${ingestAgo(batch.last_heartbeat_at)}` : ""),
    }));
  }
  if (lb) {
    const bits = [];
    // The companion's `model` block is {tier, ready, percent, note}; the
    // note is "downloading" while the weights land and the percent is the
    // download's. Shown INSTEAD of the raw gate token: an editor watching
    // "no-model" for ten minutes read it as broken while 3.3 GB were in
    // fact arriving at 2 MB/s (owner, 2026-08-18).
    const model = lb.model || {};
    const fetching = model.note === "downloading" ||
                     (lb.gate === "no-model" && model.percent != null);
    if (fetching) {
      const pct = model.percent != null ? ` ${Math.round(model.percent)}%` : "";
      // rate/eta arrive from companion 0.9.1+ (parallel ranged download);
      // an older companion sends neither and the line falls back to "a few GB".
      const rate = model.rate_bytes_per_s > 0
        ? ` at ${(model.rate_bytes_per_s / 1e6).toFixed(0)} MB/s` : "";
      const eta = model.eta_seconds > 0
        ? `, about ${Math.max(1, Math.round(model.eta_seconds / 60))} min left` : "";
      bits.push(`downloading the ${ingTierLabel(model.tier || ing.tier)} model${pct}${rate}${eta}` +
                (!rate && pct ? " (a few GB, this can take a while on the first run)" : ""));
    } else if (lb.gate) {
      bits.push(ingGateLabel(lb.gate));
    }
    if (lb.current && lb.current.stage) {
      bits.push(`${lb.current.stage}${lb.current.percent != null ? ` ${lb.current.percent}%` : ""}`);
    }
    if (lb.upload) bits.push(`uploads: ${lb.upload.queued || 0} queued`);
    if (lb.upload_paused) bits.push("uploads paused");
    if (bits.length) box.appendChild(el("div", { className: "ingest-gate", text: bits.join(" · ") }));
  } else if (ing.running) {
    box.appendChild(el("div", {
      className: "muted small",
      text: "the companion isn't answering right now - the batch keeps its place " +
            "on the server (" + ING_COMPANION_HINT + ")",
    }));
  }

  if (ing.batchItems.length) {
    const list = el("div", { className: "ingest-item-states" });
    for (const item of ing.batchItems.slice(0, 200)) {
      const row = el("div", { className: `ingest-item-state state-${item.state}` });
      row.textContent = `${item.state.padEnd(10, " ")} ${item.rel_dir ? item.rel_dir + "/" : ""}${item.orig_name}` +
                        (item.error ? ` - ${item.error}` : "");
      list.appendChild(row);
    }
    box.appendChild(list);
  }

  const paused = !!(batch && batch.upload_paused) ||
                 !!(ing.loopback && ing.loopback.batch && ing.loopback.batch.upload_paused);
  $("#ingest-pause-upload").textContent = paused ? "Resume uploads" : "Pause uploads";
  const over = batch && ["done", "done_with_errors", "cancelled", "failed"].includes(batch.state);
  for (const id of ["#ingest-pause", "#ingest-resume", "#ingest-start-now",
                    "#ingest-pause-upload", "#ingest-cancel"]) {
    $(id).disabled = !!over;
  }
}

async function ingestControl(action) {
  try {
    const answer = await ingestLoopback("POST", "/broll/ingest/control", { action: action });
    toast(`Companion: ${(answer && answer.state) || action}.`, "");
  } catch (e) {
    toast(e.message, "error");
  }
  ingestPollLoopback();
}

async function ingestToggleUploadPause() {
  const paused = $("#ingest-pause-upload").textContent.startsWith("Pause");
  if (!ing.batchUid) return;
  try {
    // The DURABLE flag first: the server's `upload_paused` is what survives a
    // companion restart and what the fleet halt sets. The loopback call after
    // it is only so the queue stops within the second rather than the minute.
    await fetchJson(`api/ingest-batches/${encodeURIComponent(ing.batchUid)}/upload-paused`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paused: paused }),
    });
  } catch (e) {
    toast(e.message, "error");
    return;
  }
  try {
    await ingestLoopback("POST", "/broll/ingest/control",
                         { action: paused ? "pause_upload" : "resume_upload" });
  } catch {
    /* the server flag stands; the companion picks it up on its next heartbeat */
  }
  ingestPollServer();
}

function ingestCancelBatch() {
  if (!ing.batchUid) return;
  ingestCancelUid(ing.batchUid);
}

async function ingestCancelUid(uid) {
  if (!window.confirm(
    "Stop this batch? Clips already in the archive stay there; the rest are " +
    "dropped and their staged files are kept for a week.")) return;
  try {
    await fetchJson(`api/ingest-batches/${encodeURIComponent(uid)}/cancel`, { method: "POST" });
  } catch (e) {
    toast(e.message, "error");
    return;
  }
  // Cancel is a REQUEST (the companion learns on its next heartbeat, 410).
  // Telling the local companion directly as well only makes it stop sooner.
  if (uid === ing.batchUid) {
    try { await ingestLoopback("POST", "/broll/ingest/control", { action: "cancel" }); }
    catch { /* it will hear it from the heartbeat */ }
  }
  toast("Cancel requested: the machine stops within a heartbeat.", "");
  ingestPollServer();
  ingestLoadBatches();
}

/* ---------------------------------------------------------------------- */
/* Batch list                                                              */
/* ---------------------------------------------------------------------- */

/** The "All machines" tab exists only for an admin, and the SERVER decides
 *  who that is: `scope=all` 403s for everybody else, so the tab is shown when
 *  the call succeeds and never on a claim the page made about itself. */
async function ingestProbeAdminScope() {
  try {
    await fetchJson("api/ingest-batches?scope=all");
    ing.adminAll = true;
  } catch {
    ing.adminAll = false;
  }
  const tab = document.querySelector('#ingest-scope-tabs .mode-btn[data-scope="all"]');
  if (tab) tab.classList.toggle("hidden", !ing.adminAll);
}

function ingestSyncScopeTabs() {
  for (const tab of document.querySelectorAll("#ingest-scope-tabs .mode-btn")) {
    tab.classList.toggle("active", tab.dataset.scope === ing.scope);
  }
}

async function ingestLoadBatches() {
  if (!ing.open) return;
  try {
    const answer = await fetchJson(`api/ingest-batches?scope=${ing.scope}`);
    ing.batches = answer.batches || [];
  } catch (e) {
    if (e.status === 403 && ing.scope === "all") {
      ing.scope = "mine";
      ing.adminAll = false;
      ingestSyncScopeTabs();
      return ingestLoadBatches();
    }
    return;
  }
  // Reopening the page must not lose the running batch: the live view and its
  // buttons are re-attached to the newest batch of this editor's that has not
  // finished. The server's view is the truth after a reload (plan 5) -- the
  // loopback poll only ever adds detail to it.
  if (!ing.batchUid && ing.scope === "mine") {
    const live = ing.batches.find(
      (b) => ["queued", "claimed", "running"].includes(b.state));
    if (live) {
      ing.batchUid = live.uid;
      ing.running = true;
      ingestPollServer();
    }
  }
  ingestRenderBatches();
}

function ingestRenderBatches() {
  const box = $("#ingest-batch-list");
  box.innerHTML = "";
  if (!ing.batches.length) {
    box.appendChild(el("div", { className: "muted small", text: "no batches yet" }));
    return;
  }
  for (const batch of ing.batches) {
    const card = el("div", { className: `ingest-batch state-${batch.state}` });

    const head = el("div", { className: "ingest-batch-head" });
    head.appendChild(el("span", { className: "ingest-batch-share", text: batch.share }));
    head.appendChild(el("span", { className: "ingest-batch-state", text: batch.state }));
    card.appendChild(head);

    const who = [];
    if (ing.scope === "all" && batch.editor) who.push(batch.editor);
    who.push(batch.machine || "no machine yet");
    if (batch.last_heartbeat_at) who.push(`heartbeat ${ingestAgo(batch.last_heartbeat_at)}`);
    if (batch.settings) {
      who.push(batch.settings.tier || "good");
      who.push(batch.settings.run_mode === "foreground" ? "foreground" : "when idle");
    }
    card.appendChild(el("div", { className: "muted small", text: who.join(" · ") }));

    card.appendChild(el("div", {
      className: "muted small",
      text: `${batch.n_done}/${batch.n_items} done · ${batch.n_live} live · ` +
            `${batch.n_failed} failed · ${batch.n_duplicate} duplicate` +
            (batch.upload_paused ? " · uploads paused" : "") +
            (batch.cancel_requested ? " · cancelling" : ""),
    }));
    if (batch.error) {
      card.appendChild(el("div", { className: "ingest-row-meta bad small", text: batch.error }));
    }

    const actions = el("div", { className: "ingest-batch-actions" });
    const toggle = el("button", { className: "text-btn",
                                  text: ing.expanded === batch.uid ? "hide clips" : "clips" });
    toggle.type = "button";
    toggle.addEventListener("click", () => ingestExpand(batch.uid));
    actions.appendChild(toggle);
    if (!["done", "done_with_errors", "cancelled", "failed"].includes(batch.state)) {
      const stop = el("button", { className: "text-btn", text: "cancel" });
      stop.type = "button";
      stop.addEventListener("click", () => ingestCancelUid(batch.uid));
      actions.appendChild(stop);
    }
    card.appendChild(actions);

    if (ing.expanded === batch.uid) {
      const list = el("div", { className: "ingest-item-states" });
      for (const item of ing.expandedItems.slice(0, 200)) {
        list.appendChild(el("div", {
          className: `ingest-item-state state-${item.state}`,
          text: `${item.state} · ${item.rel_dir ? item.rel_dir + "/" : ""}${item.orig_name}` +
                (item.error ? ` - ${item.error}` : ""),
        }));
      }
      card.appendChild(list);
    }
    box.appendChild(card);
  }
}

async function ingestExpand(uid) {
  if (ing.expanded === uid) {
    ing.expanded = "";
    ing.expandedItems = [];
    ingestRenderBatches();
    return;
  }
  try {
    const answer = await fetchJson(`api/ingest-batches/${encodeURIComponent(uid)}`);
    ing.expanded = uid;
    ing.expandedItems = answer.items || [];
  } catch (e) {
    toast(e.message, "error");
    return;
  }
  ingestRenderBatches();
}

/* ---------------------------------------------------------------------- */
/* Formatting                                                              */
/* ---------------------------------------------------------------------- */

/** UX-17: is anything mid-flight that a reload would throw away? */
function ingestUploadsInFlight() {
  return ing.items.some((i) => i.uploading) ||
         (!ing.running && ing.items.some(
           (i) => i.source === "upload" && i.include && i.accepted !== false &&
                  !i.uploaded));
}

function ingestBytes(n) {
  const bytes = Number(n) || 0;
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${Math.round(bytes / 1e6)} MB`;
  if (bytes >= 1e3) return `${Math.round(bytes / 1e3)} kB`;
  return `${bytes} B`;
}

// The companion's gate tokens (broll_ingest.STATE_*), in words. Unknown
// tokens pass through so a future gate is still visible rather than blank.
const ING_GATE_LABELS = {
  "no-model": "waiting for the indexing model",
  "user-active": "waiting until you step away from the keyboard",
  "resolve-open": "waiting for DaVinci Resolve to close",
  "paused": "paused",
  "no-ffmpeg": "waiting for ffmpeg to be installed",
  "drive-absent": "waiting: the sync drive is not connected",
  "misconfigured": "waiting: this machine's sync config needs fixing",
  "tier-unfit": "this GPU cannot run the chosen model",
  "disabled": "b-roll ingest is off on this machine",
  "nothing-to-do": "nothing to do",
  "running": "indexing",
};
function ingGateLabel(gate) {
  return ING_GATE_LABELS[gate] || String(gate || "");
}
function ingTierLabel(tier) {
  return tier === "best" ? "Best" : tier === "good" ? "Good" : String(tier || "");
}

function ingestAgo(iso) {
  const then = Date.parse(iso);
  if (!then) return "never";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 90) return `${seconds}s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}
