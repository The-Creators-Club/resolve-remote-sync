'use strict';

/* ==========================================================================
   Ingest panel: drop music in, the editor's own machine analyses it.
   docs/MUSIC_INGEST_PLAN.md step 4, 2026-08-18. b-roll's ingest.js, one
   library over -- read that file's header first; everything below is the same
   three-party shape with the differences music actually has.

   THREE PARTIES, and this file talks to two of them:
     - this app (document-relative `api/...` URLs, the session routes of
       musicweb/routes_batches.py) mints the batch and owns the truth about it;
     - the editor's OWN companion (`http://127.0.0.1:8899`, absolute on
       purpose - a different process, not this app) stages the bytes, embeds
       them with the CLAP audio tower and uploads the audio to the library.
   The browser never carries a work order: it hands the companion a batch uid
   and the companion fetches the manifest itself under the fleet token. Same
   principle as /music/send.

   A second classic script rather than a module or an addition to app.js: it
   shares app.js's helpers ($, el, toast, fmtDur) through the global scope,
   which means NO NAME MAY BE DECLARED TWICE - two classic scripts share one
   global lexical environment and a duplicate `const` is a SyntaxError that
   takes the whole page down, search included. Everything here is therefore
   `mi`/`MI_` prefixed, and tests/test_ingest_ui.py fails the build if a name
   ever collides.

   WHAT IS DIFFERENT FROM B-ROLL, and why:
     - no model tier and no VRAM anything. There is one CLAP artefact, it runs
       on the CPU, and the only thing an editor consents to is its download.
     - no shoot name and no sub-folders. The library is FLAT: `db.unique_dest`
       lands everything under the share root, so there is nothing to name.
     - the fallback is real and already exists. A machine with no companion
       (or one too old for /music/ingest/*) uploads through the browser to
       `POST api/ingest`, which lands the file in the library and leaves a
       base-rig queue row. That is the loop this feature replaces, kept.
   ========================================================================== */

/* What the browser will even look at in a drop. `musicweb.ingest_batches.
   AUDIO_EXTS`, and the server publishes its own list at
   `api/ingest-batches/limits` -- this constant is the fallback for the moment
   before that call lands, and for the standalone dev loop. */
const MI_AUDIO_EXTS_FALLBACK = [
  '.wav', '.mp3', '.flac', '.aac', '.m4a', '.ogg', '.aiff', '.aif', '.opus',
];

// musicweb.config.MAX_BATCH_ITEMS. Enforced here too so a dropped sample
// library is refused before 4,000 rows are built, not after the server 422s.
const MI_MAX_ITEMS = 500;

// Two uploads at a time: the companion writes them to a staging dir on the
// same disk it is about to read from.
const MI_UPLOAD_CONCURRENCY = 2;

const MI_LOOPBACK_POLL_MS = 1500;   // the companion's own view
const MI_SERVER_POLL_MS = 5000;     // the truth after a reload
const MI_BATCH_LIST_MS = 10000;
const MI_QUEUE_POLL_MS = 15000;     // the base rig's queue (MUSIC-7)

/* A batch in one of these is over. The list existed twice as a literal before
   MUSIC-9 (2026-09-04) needed a third reader: the transition INTO one of them
   is what refreshes the library the editor is looking at. */
const MI_TERMINAL_STATES = ['done', 'done_with_errors', 'cancelled', 'failed'];

/* The one place this file says "the companion is not answering". Repeated
   verbatim from the /music/send path's lesson: a rejected fetch is NOT proof
   the companion is down - Chrome's local-network permission blocks a
   plain-http dashboard origin from reaching 127.0.0.1 with the identical
   error. /status in a tab is never gated, so it disambiguates. */
const MI_COMPANION_HINT =
  'not reachable: the CC Sync tray is not running, or the browser blocked ' +
  'local connections (self-test: open http://127.0.0.1:8899/status in a tab; ' +
  'if that shows ok:true it is the browser, not the tray)';

const MI_TOO_OLD =
  'your CC Sync tray is too old for music ingest: take the update it offers, ' +
  'then reload this page. Until then, dropped tracks are uploaded here and ' +
  'indexed on the indexing computer.';

/* MUSIC-12 (usability sweep, 2026-09-03): the cards used to render the server
   enum straight, so a batch header read `done_with_errors on DESKTOP-7K2` and
   a track read `queued_for_base_rig - drums.wav`. The state machine's names
   are exact and stay exact in the database, on the wire and in the CSS class;
   these are the sentences an editor reads instead. The raw value goes in
   `title=` on every one of them, because support asks for it by name.

   `queued_for_base_rig` is the one that most needs a sentence: it does NOT
   queue anything (musicweb/ingest_batches.py:86-100, KNOWN_BUGS MUSIC-ING-2).
   The audio is still on the editor's own machine and dropping it again is the
   only thing that moves it, so the words say that and nothing else. */
const MI_BATCH_WORDS = {
  queued: 'waiting for your computer',
  claimed: 'starting',
  running: 'working',
  done: 'all done',
  done_with_errors: 'finished, some tracks failed',
  cancelled: 'cancelled',
  failed: 'failed',
};

const MI_ITEM_WORDS = {
  pending: 'waiting',
  transcoding: 'converting',
  embedding: 'analysing',
  indexed: 'analysed',
  uploading: 'uploading',
  live: 'in the library',
  duplicate: 'already in the library',
  failed: 'failed',
  cancelled: 'cancelled',
  skipped: 'skipped',
  queued_for_base_rig: "couldn't be analysed here - drop it again to upload it instead",
};

/* An unknown state is shown as it came, never blanked: a dashboard deployed
   ahead of this page must not turn a real state into an empty card. */
const miWords = (map, state) => map[state] || String(state || '');

/* MUSIC-12: batch cards carried no time at all, so yesterday's batch and this
   morning's looked identical. Coarse on purpose - the exact stamp is in the
   tooltip and nobody schedules anything by this line. */
function miAgo(iso) {
  const t = Date.parse(iso || '');
  if (!Number.isFinite(t)) return '';
  const secs = Math.max(0, (Date.now() - t) / 1000);
  if (secs < 90) return 'just now';
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? 'yesterday' : `${days} days ago`;
}

const mi = {
  open: false,
  items: [],          // the drop, in order
  stagingId: null,
  staged: false,      // prepare has answered for the CURRENT item set
  caps: null,         // GET /music/ingest/capabilities, or null
  capsError: '',
  audioExts: MI_AUDIO_EXTS_FALLBACK.slice(),
  runMode: 'idle',
  batchUid: null,
  batch: null,        // the server's view of the running batch
  batchItems: [],
  loopback: null,     // the companion's view (progress)
  notice: '',
  scope: 'mine',
  adminAll: false,
  batches: [],
  expanded: '',       // batch uid whose per-track list is open
  expandedItems: [],
  precheckKey: '',
  running: false,
  queue: null,        // GET api/ingest/queue, or null (MUSIC-7)
  seenStates: {},     // batch uid -> the last state this page saw it in
  timers: {loopback: null, server: null, list: null, queue: null,
           prepare: null, precheck: null},
};

/* ---------------------------------------------------------------------- */
/* Wiring                                                                  */
/* ---------------------------------------------------------------------- */

document.addEventListener('DOMContentLoaded', miInit);

function miInit() {
  const panel = document.getElementById('mi-panel');
  if (!panel) return;            // markup absent (a stale index.html) - stay inert
  $('#mi-close').addEventListener('click', miClose);
  $('#mi-recheck').addEventListener('click', () => miCapabilities(true));
  $('#mi-notice-dismiss').addEventListener('click', () => miSetNotice(''));
  $('#mi-pick-files').addEventListener('click', () => miPick('files'));
  $('#mi-pick-folder').addEventListener('click', () => miPick('folder'));
  $('#mi-run').addEventListener('click', miRun);
  $('#mi-clear').addEventListener('click', miClearDrop);
  $('#mi-pause').addEventListener('click', () => miControl('pause'));
  $('#mi-resume').addEventListener('click', () => miControl('resume'));
  $('#mi-start-now').addEventListener('click', () => miControl('start_now'));
  $('#mi-pause-upload').addEventListener('click', miToggleUploadPause);
  $('#mi-cancel').addEventListener('click', miCancelBatch);

  for (const radio of document.querySelectorAll('input[name="mi-run-mode"]')) {
    radio.addEventListener('change', () => {
      mi.runMode = radio.checked ? radio.value : mi.runMode;
      miRenderSummary();
    });
  }
  for (const tab of document.querySelectorAll('#mi-scope-tabs .mode-btn')) {
    tab.addEventListener('click', () => {
      mi.scope = tab.dataset.scope;
      miSyncScopeTabs();
      miLoadBatches();
    });
  }
  // Escape closes the panel from anywhere in it: a fixed panel with no
  // keyboard way out is a trap for anyone not using a mouse.
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && mi.open) miClose();
  });

  miSyncScopeTabs();
  miLoadLimits();
  miRenderSummary();
}

function miOpen() {
  mi.open = true;
  $('#mi-panel').classList.remove('hidden');
  miCapabilities(false);
  miLoadBatches();
  miProbeAdminScope();
  miStartPolling();
}

function miClose() {
  mi.open = false;
  $('#mi-panel').classList.add('hidden');
  // Polling follows the panel: a batch's truth is in the database, so a closed
  // panel costs nothing to stop and the server view is re-read on reopen.
  miStopPolling();
}

/* ---------------------------------------------------------------------- */
/* The drop                                                                */
/* ---------------------------------------------------------------------- */

/** app.js's `wireDropzone` calls this FIRST and falls back to the browser
 *  upload when it answers false.
 *
 *  `dt` is neutered the instant this function yields, so every entry is taken
 *  SYNCHRONOUSLY before the first await -- reading dt.items afterwards returns
 *  an empty list in Chrome, which looks exactly like "the drop contained no
 *  audio". `files` is the same drop as a plain array, captured by the caller
 *  for the same reason and handed back untouched when this declines.
 */
async function miHandleDrop(dt, files) {
  const roots = [];
  for (const item of Array.from((dt && dt.items) || [])) {
    const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
    if (entry) roots.push(entry);
  }
  const plain = Array.from(files || (dt && dt.files) || []);

  // The companion decides whether this flow happens at all, and it is asked
  // BEFORE anything is collected or shown: an editor whose companion is off
  // must get the old upload, not a panel that then says it cannot work.
  await miCapabilities(false);
  if (!mi.caps) return false;

  const out = [];
  if (roots.length) {
    for (const entry of roots) await miWalkEntry(entry, out);
  } else {
    for (const file of plain) {
      out.push(miMakeItem(file.name, file.size, 'upload', null, file));
    }
  }
  if (!out.length) {
    toast(el('div', 'row', 'Nothing there this app can index: music takes ' +
             mi.audioExts.slice(0, 6).join(', ') + ' and similar.'));
    return true;         // handled: falling through would re-refuse it
  }
  if (!mi.open) miOpen();
  miAddItems(out);
  return true;
}

/* readEntries is documented to return AT MOST 100 entries per call in Chrome
   and to signal the end of the directory with an empty array - not with the
   first short read. Calling it once silently drops every file past the
   hundredth of a sample library. */
async function miWalkEntry(entry, out) {
  if (out.length >= MI_MAX_ITEMS) return;
  if (entry.isFile) {
    if (!miIsAudio(entry.name)) return;
    const file = await new Promise(res => entry.file(res, () => res(null)));
    if (!file) return;
    out.push(miMakeItem(entry.name, file.size, 'upload', null, file));
    return;
  }
  if (!entry.isDirectory) return;
  const reader = entry.createReader();
  for (;;) {
    const chunk = await new Promise(res => reader.readEntries(res, () => res([])));
    if (!chunk.length) break;
    for (const child of chunk) {
      await miWalkEntry(child, out);
      if (out.length >= MI_MAX_ITEMS) return;
    }
  }
}

function miIsAudio(name) {
  const dot = String(name).lastIndexOf('.');
  if (dot <= 0) return false;
  return mi.audioExts.includes(String(name).slice(dot).toLowerCase());
}

function miMakeItem(name, size, source, path, file) {
  return {
    local_id: `m${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`,
    name: name,
    size: typeof size === 'number' ? size : null,
    source: source,               // "upload" (bytes stream to staging) | "path"
    path: path || null,           // native picker only - analysed in place
    file: file || null,
    include: true,
    accepted: null,               // prepare's answer
    reason: '',
    uploading: false,
    uploadPercent: null,
    uploaded: false,
    uploadUrl: '',
    stagedIn: '',
    hash: '',
    probe: null,
    stageState: '',
    error: '',
    duplicate_of: null,
    duplicate_name: '',
    final_name: '',
    nodes: null,
  };
}

function miAddItems(items) {
  const room = MI_MAX_ITEMS - mi.items.length;
  if (room <= 0) {
    toast(el('div', 'row bad',
             `A batch holds at most ${MI_MAX_ITEMS} tracks. Run this one first.`));
    return;
  }
  if (items.length > room) {
    toast(el('div', 'row',
             `Only the first ${room} tracks were taken: a batch holds ${MI_MAX_ITEMS}.`));
    items = items.slice(0, room);
  }
  mi.items.push(...items);
  mi.staged = false;
  mi.precheckKey = '';
  miRenderPreview();
  miRenderSummary();
  miSchedulePrepare();
  // Final names are worth showing before a byte has moved; the duplicate
  // answers arrive later, when the hashes do.
  miSchedulePrecheck();
}

function miClearDrop() {
  if (mi.running) return;
  mi.items = [];
  mi.stagingId = null;
  mi.staged = false;
  mi.precheckKey = '';
  miRenderPreview();
  miRenderSummary();
}

/* ---------------------------------------------------------------------- */
/* This app's own routes                                                   */
/* ---------------------------------------------------------------------- */

/** Document-relative, and it parses the error body -- app.js's `api()` throws
 *  a bare status, and the panel needs the server's reason (a 422 that names
 *  which files are not audio, a 403 on `scope=all`). */
async function miApi(path, opts) {
  const res = await fetch(path, opts);
  let parsed = null;
  try { parsed = await res.json(); } catch { parsed = null; }
  if (!res.ok) {
    const detail = parsed && parsed.detail;
    const message = (detail && typeof detail === 'object' && detail.detail)
      || (typeof detail === 'string' ? detail : '')
      || `${path} -> ${res.status}`;
    const err = new Error(message);
    err.status = res.status;
    err.body = parsed;
    throw err;
  }
  return parsed;
}

/** The extension list and the batch cap, said by the server that enforces
 *  them. Hardcoding them here is how the two drift. */
async function miLoadLimits() {
  try {
    const limits = await miApi('api/ingest-batches/limits');
    if (Array.isArray(limits.audio_exts) && limits.audio_exts.length) {
      mi.audioExts = limits.audio_exts.map(e => String(e).toLowerCase());
    }
  } catch {
    /* not signed in yet, or the standalone dev loop - the fallbacks stand */
  }
}

/* ---------------------------------------------------------------------- */
/* The companion                                                           */
/* ---------------------------------------------------------------------- */

/** Every 8899 call goes through here so exactly one place knows that a
 *  rejected fetch is ambiguous. */
async function miLoopback(method, path, body) {
  const opts = {method: method};
  if (body !== undefined) {
    opts.headers = {'Content-Type': 'application/json'};
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`${COMPANION}${path}`, opts);
  let parsed = null;
  try { parsed = await res.json(); } catch { parsed = null; }
  if (!res.ok) {
    const err = new Error((parsed && (parsed.message || parsed.detail)) ||
                          `the CC Sync tray returned HTTP ${res.status}`);
    err.status = res.status;
    err.body = parsed;
    throw err;
  }
  return parsed;
}

async function miCapabilities(loud) {
  const dot = $('#mi-dot');
  const text = $('#mi-companion-text');
  if (dot) dot.className = 'status-dot status-unknown';
  if (text) text.textContent = 'checking…';
  try {
    mi.caps = await miLoopback('GET', '/music/ingest/capabilities');
    mi.capsError = '';
  } catch (e) {
    mi.caps = null;
    // A companion published before this feature answers 404 on every
    // /music/ingest route -- the same "editors need a republished companion"
    // gap /music/send had. Worth its own sentence: nothing is wrong with it.
    mi.capsError = e.status === 404 ? MI_TOO_OLD : MI_COMPANION_HINT;
    if (dot) dot.className = 'status-dot status-bad';
    if (text) text.textContent = mi.capsError;
    miRenderSummary();
    if (loud) toast(el('div', 'row bad', mi.capsError));
    return;
  }
  const caps = mi.caps;
  const clap = caps.clap || {};
  if (dot) dot.className = `status-dot ${caps.ok ? 'status-ok' : 'status-bad'}`;
  const bits = [`v${caps.version || '?'}`];
  if (clap.cached === false && clap.download_bytes) {
    bits.push(`model not downloaded yet, about ${miBytes(clap.download_bytes)}`);
  } else if (clap.cached) {
    bits.push('model ready');
  }
  if (text) {
    text.textContent = caps.ok
      ? `connected (${bits.join(', ')})`
      : `the CC Sync tray can't index yet: ${(caps.reasons || []).join('; ') || 'unknown'}`;
  }
  if (Array.isArray(caps.audio_exts) && caps.audio_exts.length) {
    mi.audioExts = caps.audio_exts.map(e => String(e).toLowerCase());
  }
  miRenderSummary();
}

/** "Choose from this computer…": real paths, analysed where they are. */
async function miPick(kind) {
  let answer;
  try {
    answer = await miLoopback('POST', '/music/ingest/pick', {kind: kind});
  } catch (e) {
    toast(el('div', 'row bad',
             e.status === 404 ? MI_TOO_OLD : (e.message || MI_COMPANION_HINT)));
    return;
  }
  if (!answer || answer.ok === false) {
    if (answer && answer.message && answer.message !== 'cancelled') {
      toast(el('div', 'row bad', answer.message));
    }
    return;
  }
  const picked = (answer.files || [])
    .filter(f => miIsAudio(f.name || f.path || ''))
    .map(f => miMakeItem(f.name || '', f.size, 'path', f.path, null));
  if (!mi.open) miOpen();
  miAddItems(picked);
}

function miSchedulePrepare() {
  clearTimeout(mi.timers.prepare);
  // A multi-select drop arrives as several adds; one prepare for the settled
  // set beats one staging dir per file.
  mi.timers.prepare = setTimeout(miPrepare, 700);
}

async function miPrepare() {
  if (mi.running || !mi.items.length) return;
  if (!mi.caps) await miCapabilities(false);
  if (!mi.caps) {
    miSetNotice(`The CC Sync tray is not answering, so these tracks cannot ` +
                `be staged: ${mi.capsError || MI_COMPANION_HINT}`);
    return;
  }
  const body = {
    items: mi.items.map(it => ({
      local_id: it.local_id,
      name: it.name,
      size: it.size,
      source: it.source,
      path: it.path || undefined,
    })),
  };
  let answer;
  try {
    answer = await miLoopback('POST', '/music/ingest/prepare', body);
  } catch (e) {
    miSetNotice(`The CC Sync tray could not stage this drop: ${e.message}`);
    return;
  }
  mi.stagingId = answer.staging_id || null;
  const byId = new Map((answer.items || []).map(r => [r.local_id, r]));
  for (const item of mi.items) {
    const row = byId.get(item.local_id);
    if (!row) continue;
    item.accepted = row.accepted !== false;
    item.reason = row.reason || '';
    item.uploadUrl = row.upload_url || '';
    item.stagedIn = mi.stagingId;
    // A second drop re-stages EVERYTHING under a new staging id, so bytes that
    // reached the old one no longer exist as far as this batch is concerned.
    item.uploaded = item.source === 'path';
    item.uploadPercent = null;
    item.error = '';
    if (!item.accepted) item.include = false;
  }
  mi.staged = true;
  miRenderPreview();
  miStartPolling();
  miPumpUploads();
}

/* Bytes go up by XMLHttpRequest, not fetch: `upload.onprogress` is the only
   way a browser reports how far a request BODY has got, and a 400 MB stem with
   no progress bar reads as a hung page. */
function miPumpUploads() {
  let active = mi.items.filter(i => i.uploading).length;
  for (const item of mi.items) {
    if (active >= MI_UPLOAD_CONCURRENCY) break;
    if (item.source !== 'upload' || !item.accepted || item.uploaded ||
        item.uploading || !item.include || item.error) continue;
    active++;
    miUploadItem(item);
  }
}

function miUploadItem(item) {
  item.uploading = true;
  item.uploadPercent = 0;
  miUpdateRow(item);
  const url = item.uploadUrl ||
    `/music/ingest/upload/${encodeURIComponent(mi.stagingId)}/` +
    `${encodeURIComponent(item.local_id)}`;
  const xhr = new XMLHttpRequest();
  xhr.open('PUT', url.startsWith('http') ? url : `${COMPANION}${url}`);
  xhr.setRequestHeader('Content-Type', 'application/octet-stream');
  // The CSRF half of the loopback contract: a custom header forces a
  // preflight, so a hostile page can never stream bytes into staging.
  xhr.setRequestHeader('X-CCSync-Ingest', '1');
  xhr.upload.onprogress = e => {
    item.uploadPercent = e.lengthComputable ? Math.round((e.loaded / e.total) * 100) : null;
    miUpdateRow(item);
  };
  const done = (ok, message) => {
    item.uploading = false;
    item.uploaded = ok;
    if (!ok) item.error = message;
    miUpdateRow(item);
    miPumpUploads();
  };
  xhr.onload = () => {
    let body = null;
    try { body = JSON.parse(xhr.responseText); } catch { body = null; }
    // 409 = these bytes are already in staging (a re-prepare of the same drop,
    // or a double click). That is success, not a failure to show an editor.
    if (xhr.status === 409) return done(true, '');
    if (xhr.status < 200 || xhr.status >= 300) {
      return done(false, (body && (body.message || body.detail)) ||
                         `upload failed (HTTP ${xhr.status})`);
    }
    if (body && body.hash) item.hash = body.hash;
    if (body && body.probe) item.probe = body.probe;
    item.uploadPercent = 100;
    done(true, '');
  };
  xhr.onerror = () => done(false, 'upload failed. Is the CC Sync tray still running?');
  xhr.send(item.file);
}

/* ---------------------------------------------------------------------- */
/* Polling                                                                 */
/* ---------------------------------------------------------------------- */

function miStartPolling() {
  miStopPolling();
  if (!mi.open) return;
  mi.timers.loopback = setInterval(miPollLoopback, MI_LOOPBACK_POLL_MS);
  mi.timers.server = setInterval(miPollServer, MI_SERVER_POLL_MS);
  mi.timers.list = setInterval(miLoadBatches, MI_BATCH_LIST_MS);
  mi.timers.queue = setInterval(miLoadQueue, MI_QUEUE_POLL_MS);
  miPollLoopback();
  miPollServer();
  miLoadQueue();
}

function miStopPolling() {
  for (const key of Object.keys(mi.timers)) {
    // `prepare`/`precheck` are debounce timeouts, not pollers: closing the
    // panel mid-drop must not lose the staging.
    if (key === 'prepare' || key === 'precheck') continue;
    clearInterval(mi.timers[key]);
    mi.timers[key] = null;
  }
}

async function miPollLoopback() {
  if (!mi.open || (!mi.stagingId && !mi.batchUid)) return;
  let answer;
  try {
    answer = await miLoopback(
      'GET', `/music/ingest/progress?staging_id=${encodeURIComponent(mi.stagingId || '')}`);
  } catch {
    mi.loopback = null;
    miRenderLive();
    return;
  }
  mi.loopback = answer;
  const staging = (answer && answer.staging && answer.staging.items) || [];
  const byId = new Map(staging.map(r => [r.local_id, r]));
  for (const item of mi.items) {
    const row = byId.get(item.local_id);
    if (!row) continue;
    item.stageState = row.state || item.stageState;
    if (row.hash) item.hash = row.hash;
    if (row.probe) item.probe = row.probe;
    if (row.error) item.error = row.error;
    miUpdateRow(item);
  }
  miMaybePrecheck();
  miRenderLive();
}

async function miPollServer() {
  if (!mi.open || !mi.batchUid) return;
  try {
    const answer = await miApi(`api/ingest-batches/${encodeURIComponent(mi.batchUid)}`);
    mi.batch = answer.batch;
    mi.batchItems = answer.items || [];
    // The server is the truth after a reload - when it says the batch is over,
    // the live view stops claiming otherwise even if the companion is silent.
    if (MI_TERMINAL_STATES.includes(mi.batch.state)) {
      mi.running = false;
    }
    miNoteBatchState(mi.batch);
  } catch {
    /* transient - the batch list poll will catch up */
  }
  miRenderLive();
}

/* MUSIC-9 (2026-09-04): nothing in this file touched the library view, so a
   batch reaching `done` left the results list, the facets and the header stats
   exactly as they were and the only way to see the new tracks was to reload
   the page. The refresh fires on the TRANSITION into a terminal state, never
   on first sight of one: a page opened on last week's finished batches must
   not re-render the list under the editor. */
function miNoteBatchState(batch) {
  if (!batch || !batch.uid) return;
  const was = mi.seenStates[batch.uid];
  mi.seenStates[batch.uid] = batch.state;
  if (!was || was === batch.state) return;
  if (MI_TERMINAL_STATES.includes(was) || !MI_TERMINAL_STATES.includes(batch.state)) return;
  miAfterBatch(batch);
}

function miAfterBatch(batch) {
  miLoadQueue();
  toast(el('div', 'row', `Ingest ${miWords(MI_BATCH_WORDS, batch.state)}: `
                         + 'the library below is refreshed, newest first.'));
  // `refreshLibrary` lives in app.js, which always loads first - the guard is
  // for a stale index.html that has one script and not the other.
  if (typeof refreshLibrary === 'function') refreshLibrary(true);
}

/* ---------------------------------------------------------------------- */
/* The base rig's queue (MUSIC-7)                                          */
/* ---------------------------------------------------------------------- */

/** `GET api/ingest/queue` has always carried the counts, the pending rows and
 *  every parked failure's reason, and until 2026-09-04 nothing in the browser
 *  read it: a queued upload that cannot be analysed is parked, never retried,
 *  so the reason existed only in the log of whichever indexer run hit it. */
async function miLoadQueue() {
  if (!mi.open) return;
  try {
    mi.queue = await miApi('api/ingest/queue');
  } catch {
    return;                     // transient: the next tick asks again
  }
  miRenderQueue();
}

function miRenderQueue() {
  const box = $('#mi-queue');
  if (!box) return;             // stale index.html
  const body = $('#mi-queue-body');
  const q = mi.queue || {};
  const counts = q.counts || {};
  const pending = q.pending || [];
  const failed = q.failed || [];
  box.classList.toggle('hidden', !counts.pending && !counts.failed);
  body.innerHTML = '';
  if (counts.pending) {
    body.appendChild(el('div', 'row',
      `Waiting for the indexing computer: ${counts.pending} track`
      + `${counts.pending === 1 ? '' : 's'}. They are in the library already and `
      + 'are not searchable until the indexing computer indexes them.'));
    for (const row of pending.slice(0, 20)) {
      body.appendChild(el('div', 'mi-row-meta', `◷ ${row.orig_name || row.rel_path}`));
    }
  }
  if (counts.failed) {
    body.appendChild(el('div', 'row bad',
      `${counts.failed} could not be analysed. Nothing retries these on their `
      + 'own: fix the file and drop it again.'));
    for (const row of failed.slice(0, 20)) {
      // orig_name and error carry a filename and raw ffmpeg stderr, neither
      // filtered for HTML (MUSIC-15) - el() sets textContent, never innerHTML.
      body.appendChild(el('div', 'mi-row-meta bad',
        `✕ ${row.orig_name || row.rel_path} - ${row.error || 'no reason recorded'}`));
    }
  }
}

/* ---------------------------------------------------------------------- */
/* Pre-check: duplicates and final names                                   */
/* ---------------------------------------------------------------------- */

function miSchedulePrecheck() {
  mi.precheckKey = '';
  clearTimeout(mi.timers.precheck);
  mi.timers.precheck = setTimeout(miMaybePrecheck, 400);
}

/** Runs once per set of (hash, duration): a hash arriving from staging changes
 *  the answer, and nothing else does. */
function miMaybePrecheck() {
  if (mi.running || !mi.items.length) return;
  const key = mi.items.map(i => `${i.local_id}:${i.hash}:${miDuration(i) || ''}`).join(',');
  if (key === mi.precheckKey) return;
  mi.precheckKey = key;
  miPrecheck();
}

async function miPrecheck() {
  let answer;
  try {
    answer = await miApi('api/ingest-batches/precheck', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        items: mi.items.map(it => ({
          local_id: it.local_id,
          name: it.name,
          size: it.size,
          duration: miDuration(it),
          content_hash: it.hash || null,
          source: it.source,
        })),
      }),
    });
  } catch {
    mi.precheckKey = '';        // transient: ask again on the next tick
    return;
  }
  const byId = new Map((answer.items || []).map(r => [r.local_id, r]));
  for (const item of mi.items) {
    const row = byId.get(item.local_id);
    if (!row) continue;
    const wasDuplicate = item.duplicate_of;
    item.duplicate_of = row.duplicate_of;
    item.duplicate_name = row.duplicate_name || '';
    item.final_name = row.final_name || '';
    // Duplicates and re-encodes are unticked FOR the editor, once, the first
    // time they are discovered. Re-ticking one must not silently untick it
    // again on the next poll.
    if (item.duplicate_of && !wasDuplicate) item.include = false;
    miUpdateRow(item);
  }
  miRenderSummary();
}

function miDuration(item) {
  const probe = item.probe || {};
  const seconds = probe.duration_s !== undefined ? probe.duration_s : probe.duration;
  return typeof seconds === 'number' && seconds > 0 ? seconds : null;
}

/* ---------------------------------------------------------------------- */
/* Preview rows                                                            */
/* ---------------------------------------------------------------------- */

function miRenderPreview() {
  const box = $('#mi-preview');
  box.innerHTML = '';
  $('#mi-stage').classList.toggle('hidden', !mi.items.length);
  // MUSIC-3: the panel opens from a button now, not only from a drop, so the
  // empty case has to say what it takes and what happens next.
  const hint = $('#mi-drop-empty');
  if (hint) hint.classList.toggle('hidden', !!mi.items.length);
  for (const item of mi.items) {
    item.nodes = null;
    box.appendChild(miBuildRow(item));
  }
  miRenderHead();
  miRenderSummary();
}

function miRenderHead() {
  const n = mi.items.length;
  const chosen = mi.items.filter(i => i.include).length;
  $('#mi-preview-head').textContent = n
    ? `${chosen} of ${n} track${n === 1 ? '' : 's'} selected`
    : '';
}

function miBuildRow(item) {
  const row = el('div', 'mi-row');

  const tick = el('input');
  tick.type = 'checkbox';
  tick.checked = item.include;
  tick.id = `mi-tick-${item.local_id}`;
  tick.addEventListener('change', () => {
    item.include = tick.checked;
    if (item.include) miPumpUploads();
    miRenderHead();
    miRenderSummary();
  });
  row.appendChild(tick);

  const body = el('div', 'mi-row-body');
  const label = el('label', 'mi-row-name', item.name);
  label.setAttribute('for', tick.id);
  body.appendChild(label);
  const meta = el('div', 'mi-row-meta muted');
  body.appendChild(meta);
  const bar = el('div', 'mi-bar hidden');
  const fill = el('div', 'mi-bar-fill');
  bar.appendChild(fill);
  body.appendChild(bar);
  row.appendChild(body);

  item.nodes = {row, tick, meta, bar, fill};
  miUpdateRow(item);
  return row;
}

function miUpdateRow(item) {
  const n = item.nodes;
  if (!n) return;
  n.tick.checked = item.include;
  n.tick.disabled = mi.running || item.accepted === false;

  const bits = [];
  if (item.size != null) bits.push(miBytes(item.size));
  const seconds = miDuration(item);
  if (seconds) bits.push(fmtDur(seconds));
  if (item.source === 'path') bits.push('analysed where it is');
  if (item.final_name && item.final_name !== item.name) {
    bits.push(`will be saved as ${item.final_name}`);
  }
  n.meta.textContent = bits.join(' · ');
  n.meta.classList.remove('bad', 'warn');

  if (item.accepted === false) {
    n.meta.textContent = item.reason || 'the CC Sync tray refused this track';
    n.meta.classList.add('bad');
  } else if (item.error) {
    n.meta.textContent = item.error;
    n.meta.classList.add('bad');
  } else if (item.duplicate_of) {
    // BOTH defences land here: a byte-identical file and a re-encode under
    // (near enough) the same name and length. The editor is shown what was
    // found and unticks or keeps it -- exactly as the old upload path
    // reported a duplicate rather than silently dropping it.
    n.meta.textContent =
      `already in the library as ${item.duplicate_name || `track #${item.duplicate_of}`}` +
      (bits.length ? ` · ${bits.join(' · ')}` : '');
    n.meta.classList.add('warn');
  }

  const uploading = item.uploading || (item.uploadPercent != null && !item.uploaded);
  n.bar.classList.toggle('hidden', !uploading);
  if (uploading) n.fill.style.width = `${item.uploadPercent == null ? 50 : item.uploadPercent}%`;
  miRenderHead();
}

/* ---------------------------------------------------------------------- */
/* Settings + run                                                          */
/* ---------------------------------------------------------------------- */

function miRenderSummary() {
  const chosen = mi.items.filter(i => i.include);
  const bytes = chosen.reduce((sum, i) => sum + (i.size || 0), 0);
  const when = mi.runMode === 'foreground'
    ? 'will run now' : "will run when you're away";
  $('#mi-summary').textContent = chosen.length
    ? `${chosen.length} track${chosen.length === 1 ? '' : 's'}, ${miBytes(bytes)} - ${when}`
    : 'nothing selected';
  $('#mi-run').disabled = !chosen.length || mi.running || !mi.caps || !mi.staged;
  $('#mi-clear').disabled = mi.running;
  miRenderHead();
}

function miSetNotice(message) {
  mi.notice = message || '';
  $('#mi-notice-text').textContent = mi.notice;
  $('#mi-notice').classList.toggle('hidden', !mi.notice);
}

async function miRun() {
  const chosen = mi.items.filter(i => i.include);
  if (!chosen.length) return;
  const clap = (mi.caps && mi.caps.clap) || {};
  if (clap.cached === false && clap.download_bytes) {
    // Consent for the download, with the byte count, BEFORE anything starts:
    // 280 MB on a hotel connection is the editor's business, not ours.
    if (!window.confirm(
      `The music indexing model isn't on this computer yet. Running this batch ` +
      `downloads it first (about ${miBytes(clap.download_bytes)}). Continue?`)) return;
  }

  $('#mi-run').disabled = true;
  let created;
  try {
    created = await miApi('api/ingest-batches', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        settings: {run_mode: mi.runMode},
        items: chosen.map(it => ({
          local_id: it.local_id,
          name: it.name,
          size: it.size,
          duration: miDuration(it),
          content_hash: it.hash || null,
          source: it.source,
        })),
      }),
    });
  } catch (e) {
    toast(el('div', 'row bad', e.message));
    miRenderSummary();
    return;
  }

  mi.batchUid = created.uid;
  try {
    await miLoopback('POST', '/music/ingest/run', {
      batch_uid: created.uid,
      staging_id: mi.stagingId,
      run_mode: mi.runMode,
    });
  } catch (e) {
    // 503 = the machine refused: no onnxruntime, no release feed to fetch the
    // model from, or a capability that vanished between the probe and the
    // click. PERSISTENT, not a toast - the batch is queued on the server and
    // another of this editor's machines can pick it up.
    miSetNotice(
      e.status === 503
        ? `${e.message} The batch is queued on the server: another of your ` +
          `computers can run it, or drop the tracks again to upload them here ` +
          `and let the indexing computer index them.`
        : `The CC Sync tray did not take the batch: ${e.message}`);
    miLoadBatches();
    miRenderSummary();
    return;
  }

  miSetNotice('');
  mi.running = true;
  $('#mi-live').classList.remove('hidden');
  toast(el('div', 'row good', mi.runMode === 'foreground'
    ? 'Analysing on this computer now.'
    : 'Queued: it starts when you step away from this computer.'));
  miStartPolling();
  miLoadBatches();
  miRenderSummary();
}

/* ---------------------------------------------------------------------- */
/* Live view + controls                                                    */
/* ---------------------------------------------------------------------- */

/* One track's line, in both places tracks are listed (the live panel and an
   expanded batch card). MUSIC-12: the words, not the enum; the enum stays in
   the class name, which the CSS colours by, and in `title=`. */
function miItemLine(item) {
  const node = el('div', `mi-item-state state-${item.state}`,
    `${miWords(MI_ITEM_WORDS, item.state)} · ${item.orig_name}` +
    (item.error ? ` - ${item.error}` : ''));
  node.title = item.state;
  return node;
}

function miRenderLive() {
  const box = $('#mi-live-body');
  const live = $('#mi-live');
  if (!mi.batchUid) {
    live.classList.add('hidden');
    return;
  }
  live.classList.remove('hidden');
  box.innerHTML = '';

  const batch = mi.batch;
  const lb = (mi.loopback && mi.loopback.batch) || null;
  // MUSIC-12: the sentence, with the enum kept in the tooltip for support.
  const head = el('div', 'mi-live-head', batch
    ? `${miWords(MI_BATCH_WORDS, batch.state)}${batch.machine ? ` on ${batch.machine}` : ''}`
    : 'waiting for the server…');
  if (batch) head.title = batch.state;
  box.appendChild(head);

  if (batch) {
    box.appendChild(el('div', 'muted',
      `${batch.n_done} of ${batch.n_items} done · ${batch.n_live} in the library · ` +
      `${batch.n_failed} failed · ${batch.n_duplicate} duplicate`));
  }
  if (lb) {
    const bits = [];
    if (lb.gate) bits.push(lb.gate);
    if (lb.current && lb.current.stage) {
      bits.push(`${lb.current.name || ''} ${lb.current.stage}`.trim());
    }
    if (lb.model && lb.model.percent != null) {
      bits.push(`downloading the model ${lb.model.percent}%`);
    }
    if (lb.upload) bits.push(`uploads: ${lb.upload.queued || 0} queued`);
    if (lb.upload_paused) bits.push('uploads paused');
    if (bits.length) box.appendChild(el('div', 'mi-gate', bits.join(' · ')));
  } else if (mi.running) {
    box.appendChild(el('div', 'muted',
      "the CC Sync tray isn't answering right now - the batch keeps its place on " +
      'the server (' + MI_COMPANION_HINT + ')'));
  }

  if (mi.batchItems.length) {
    const list = el('div', 'mi-item-states');
    for (const item of mi.batchItems.slice(0, 200)) {
      list.appendChild(miItemLine(item));
    }
    box.appendChild(list);
  }

  const paused = !!(batch && batch.upload_paused) || !!(lb && lb.upload_paused);
  $('#mi-pause-upload').textContent = paused ? 'Resume uploads' : 'Pause uploads';
  const over = batch && MI_TERMINAL_STATES.includes(batch.state);
  for (const id of ['#mi-pause', '#mi-resume', '#mi-start-now',
                    '#mi-pause-upload', '#mi-cancel']) {
    $(id).disabled = !!over;
  }
}

async function miControl(action) {
  try {
    const answer = await miLoopback('POST', '/music/ingest/control', {action: action});
    toast(el('div', 'row', `CC Sync tray: ${(answer && answer.state) || action}.`));
  } catch (e) {
    toast(el('div', 'row bad', e.message));
  }
  miPollLoopback();
}

async function miToggleUploadPause() {
  const paused = $('#mi-pause-upload').textContent.startsWith('Pause');
  if (!mi.batchUid) return;
  try {
    // The DURABLE flag first: the server's `upload_paused` is what survives a
    // companion restart. The loopback call after it is only so the queue stops
    // within the second rather than the minute.
    await miApi(`api/ingest-batches/${encodeURIComponent(mi.batchUid)}/upload-paused`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({paused: paused}),
    });
  } catch (e) {
    toast(el('div', 'row bad', e.message));
    return;
  }
  try {
    await miLoopback('POST', '/music/ingest/control',
                     {action: paused ? 'pause_upload' : 'resume_upload'});
  } catch {
    /* the server flag stands; the companion picks it up on its next heartbeat */
  }
  miPollServer();
}

function miCancelBatch() {
  if (mi.batchUid) miCancelUid(mi.batchUid);
}

async function miCancelUid(uid) {
  if (!window.confirm(
    'Stop this batch? Tracks already in the library stay there; the rest are ' +
    'dropped and their staged files are kept.')) return;
  try {
    await miApi(`api/ingest-batches/${encodeURIComponent(uid)}/cancel`, {method: 'POST'});
  } catch (e) {
    toast(el('div', 'row bad', e.message));
    return;
  }
  // Cancel is a REQUEST (the companion learns on its next heartbeat, 410).
  // Telling the local companion directly as well only makes it stop sooner.
  if (uid === mi.batchUid) {
    try { await miLoopback('POST', '/music/ingest/control', {action: 'cancel'}); }
    catch { /* it will hear it from the heartbeat */ }
  }
  toast(el('div', 'row', 'Cancel requested: the computer stops within a heartbeat.'));
  miPollServer();
  miLoadBatches();
}

/* ---------------------------------------------------------------------- */
/* Batch list                                                              */
/* ---------------------------------------------------------------------- */

/** The "All machines" tab exists only for an admin, and the SERVER decides
 *  who that is: `scope=all` 403s for everybody else, so the tab is shown when
 *  the call succeeds and never on a claim the page made about itself. */
async function miProbeAdminScope() {
  try {
    await miApi('api/ingest-batches?scope=all');
    mi.adminAll = true;
  } catch {
    mi.adminAll = false;
  }
  const tab = document.querySelector('#mi-scope-tabs .mode-btn[data-scope="all"]');
  if (tab) tab.classList.toggle('hidden', !mi.adminAll);
}

function miSyncScopeTabs() {
  for (const tab of document.querySelectorAll('#mi-scope-tabs .mode-btn')) {
    tab.classList.toggle('active', tab.dataset.scope === mi.scope);
  }
}

async function miLoadBatches() {
  if (!mi.open) return;
  try {
    const answer = await miApi(`api/ingest-batches?scope=${mi.scope}`);
    mi.batches = answer.batches || [];
    // MUSIC-9: the list poll sees a batch this page is not "running" itself,
    // which is the common case after a reload.
    for (const b of mi.batches) miNoteBatchState(b);
  } catch (e) {
    if (e.status === 403 && mi.scope === 'all') {
      mi.scope = 'mine';
      mi.adminAll = false;
      miSyncScopeTabs();
      return miLoadBatches();
    }
    return;
  }
  // Reopening the page must not lose the running batch: the live view and its
  // buttons are re-attached to the newest unfinished batch of this editor's.
  if (!mi.batchUid && mi.scope === 'mine') {
    const live = mi.batches.find(b => ['queued', 'claimed', 'running'].includes(b.state));
    if (live) {
      mi.batchUid = live.uid;
      mi.running = true;
      miPollServer();
    }
  }
  miRenderBatches();
}

function miRenderBatches() {
  const box = $('#mi-batch-list');
  box.innerHTML = '';
  if (!mi.batches.length) {
    box.appendChild(el('div', 'muted', 'no batches yet'));
    return;
  }
  for (const batch of mi.batches) {
    const card = el('div', `mi-batch state-${batch.state}`);

    const head = el('div', 'mi-batch-head');
    // MUSIC-12: the sentence, the enum in the tooltip, and a time - without
    // one, yesterday's batch and this morning's looked identical.
    const state = el('span', 'mi-batch-state', miWords(MI_BATCH_WORDS, batch.state));
    state.title = batch.state;
    head.appendChild(state);
    if (mi.scope === 'all' && batch.editor) {
      head.appendChild(el('span', 'muted', batch.editor));
    }
    const when = miAgo(batch.updated_at || batch.created_at);
    if (when) {
      const stamp = el('span', 'muted', when);
      stamp.title = batch.created_at ? `started ${batch.created_at}` : '';
      head.appendChild(stamp);
    }
    card.appendChild(head);

    const who = [batch.machine || 'no computer yet'];
    if (batch.settings) {
      who.push(batch.settings.run_mode === 'foreground' ? 'foreground' : 'when idle');
    }
    card.appendChild(el('div', 'muted', who.join(' · ')));
    card.appendChild(el('div', 'muted',
      // MUSIC-12: `live` is the item enum; the panel above already says "in
      // the library" for the same number and the two lines are read together.
      `${batch.n_done}/${batch.n_items} done · ${batch.n_live} in the library · ` +
      `${batch.n_failed} failed · ${batch.n_duplicate} duplicate` +
      (batch.upload_paused ? ' · uploads paused' : '') +
      (batch.cancel_requested ? ' · cancelling' : '')));
    if (batch.error) card.appendChild(el('div', 'mi-row-meta bad', batch.error));

    const actions = el('div', 'mi-batch-actions');
    const toggle = el('button', 'text-btn',
                      mi.expanded === batch.uid ? 'hide tracks' : 'tracks');
    toggle.type = 'button';
    toggle.addEventListener('click', () => miExpand(batch.uid));
    actions.appendChild(toggle);
    if (!MI_TERMINAL_STATES.includes(batch.state)) {
      const stop = el('button', 'text-btn', 'cancel');
      stop.type = 'button';
      stop.addEventListener('click', () => miCancelUid(batch.uid));
      actions.appendChild(stop);
    }
    card.appendChild(actions);

    if (mi.expanded === batch.uid) {
      const list = el('div', 'mi-item-states');
      for (const item of mi.expandedItems.slice(0, 200)) {
        list.appendChild(miItemLine(item));
      }
      card.appendChild(list);
    }
    box.appendChild(card);
  }
}

async function miExpand(uid) {
  if (mi.expanded === uid) {
    mi.expanded = '';
    mi.expandedItems = [];
    miRenderBatches();
    return;
  }
  try {
    const answer = await miApi(`api/ingest-batches/${encodeURIComponent(uid)}`);
    mi.expanded = uid;
    mi.expandedItems = answer.items || [];
  } catch (e) {
    toast(el('div', 'row bad', e.message));
    return;
  }
  miRenderBatches();
}

/* ---------------------------------------------------------------------- */
/* Formatting                                                              */
/* ---------------------------------------------------------------------- */

function miBytes(n) {
  const bytes = Number(n) || 0;
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${Math.round(bytes / 1e6)} MB`;
  if (bytes >= 1e3) return `${Math.round(bytes / 1e3)} kB`;
  return `${bytes} B`;
}
