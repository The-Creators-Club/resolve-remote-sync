'use strict';

// Every URL here is DOCUMENT-relative ('api/jobs'), never leading-slash. A
// leading slash resolves against the origin root, so mounted at /ytdl by the
// dashboard each one would hit the dashboard instead of this app. Relative
// works at both / and /ytdl/ with no build step and no injected base tag --
// see tests/test_mounted_prefix.py, which fails the build if one comes back.

const $ = s => document.querySelector(s);
const el = (tag, cls, txt) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (txt !== undefined) n.textContent = txt;
  return n;
};

// Phase -> [bar start %, bar end %]. Fixed segments, because the phases take
// wildly different amounts of time and a bar driven by "3 of 9 phases" would
// sit at 33% for four minutes. Within a segment the counters interpolate.
const PHASE_SPAN = {
  queued: [0, 3],
  generating_terms: [3, 12],
  searching: [12, 48],
  enriching: [48, 82],
  filtering: [82, 96],
  ready_for_review: [100, 100],
};
const PHASE_LABEL = {
  queued: 'queued',
  generating_terms: 'asking claude for search terms',
  searching: 'searching youtube',
  enriching: 'fetching metadata',
  filtering: 'filtering + checking for duplicates',
  ready_for_review: 'ready for review',
  downloading: 'downloading',
  done: 'done',
  failed: 'failed',
  cancelled: 'cancelled',
};

// The machine-readable prefixes worker.py writes into jobs.error. The whole
// point of them is that the fix is different in every case and an editor
// cannot tell them apart from a raw stderr dump.
const HINTS = [
  ['claude_auth:', 'Claude Code is not logged in on the server. An admin must run the one-time login — see ytdl/web/DEPLOY.md. Nothing else on this page is affected.'],
  ['claude_missing:', 'The claude CLI is not installed in the dashboard container. See ytdl/web/DEPLOY.md (it ships alongside ffmpeg).'],
  ['claude_timeout:', 'Claude did not answer in time. Try the search again; if it keeps happening the server is overloaded.'],
  ['claude_output:', 'Claude answered with something this app could not read. Trying again usually works.'],
];

const POLL_FAST = 1500;
const POLL_SLOW = 5000;
const BACKOFF_AFTER = 120000;   // 2 min of polling, then ease off
// Health is a cached read on the server (routes_api never probes claude per
// request), so re-asking is cheap -- but every open tab pays it, hence slow.
// Without it an admin who fixes claude leaves every open tab red until each
// editor reloads (YTDL-39, 2026-08-11).
const HEALTH_INTERVAL = 120000;

const WORKER_DEAD =
  'the pipeline worker is not running: jobs will queue and never start.';

const state = {
  jobId: null,
  attachToken: 0,      // bumped by every attach/detach; see stale() below
  manifest: null,      // {videos, terms, counts}
  termFilter: null,    // job_terms.id, or null for "everything"
  showFiltered: false,
  pollTimer: null,
  pollStart: 0,
};

// ---------------------------------------------------------------- helpers
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let detail = `${path} -> ${r.status}`;
    let info = null;
    try {
      const j = await r.json();
      const d = j.detail;
      // The structured detail, not just its message: the one-job-at-a-time 409
      // carries the job_id of the job it is refusing to duplicate, and dropping
      // it left the SPA unable to re-attach (YTDL-8, 2026-08-11).
      if (d && typeof d === 'object') info = d;
      detail = (typeof d === 'string' ? d : (d && d.detail) || detail);
    } catch { /* not JSON; the status line is all we have */ }
    const e = new Error(detail);
    e.status = r.status;
    e.info = info;
    throw e;
  }
  return r.json();
}

const post = (path, body) => api(path, {
  method: 'POST',
  headers: {'content-type': 'application/json'},
  body: JSON.stringify(body || {}),
});

const fmtDur = s => {
  if (!s && s !== 0) return '—';
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = Math.floor(s % 60);
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`
           : `${m}:${String(r).padStart(2, '0')}`;
};

const fmtTotal = s => {
  if (!s) return '0m';
  const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m`;
};

const fmtDate = d => d ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}` : '';

// Built with el()/textContent, never innerHTML: the text is server `detail`,
// and one future detail quoting a YouTube title would otherwise be XSS from a
// video someone else uploaded (YTDL-35, 2026-08-11).
function toast(text, bad, ms = 7000) {
  const t = $('#toast');
  t.textContent = '';
  t.appendChild(el('div', bad ? 'bad' : null, String(text)));
  t.classList.remove('hidden');
  clearTimeout(toast._t);
  if (ms) toast._t = setTimeout(() => t.classList.add('hidden'), ms);
}

// One banner line per CONCERN, all in #warn. They are independent and arrive
// in any order: loadHealth's all-clear used to erase loadProjects' "no
// projects ticked" ~100 ms after it appeared, leaving a disabled SEARCH button
// with no stated reason (YTDL-37), and a failed job's red line used to survive
// into the next, healthy job (YTDL-12). 2026-08-11.
const banners = new Map();

function setBanner(key, text, bad) {
  // Both no-op paths matter: poll() re-asserts its slots every 1.5 s and must
  // not rebuild the header on every tick.
  const cur = banners.get(key);
  if (text) {
    if (cur && cur.text === text && cur.bad === !!bad) return;
    banners.set(key, {text, bad: !!bad});
  } else if (!banners.delete(key)) return;
  const box = $('#warn');
  box.textContent = '';
  banners.forEach(b => box.appendChild(
    el('div', 'warnline' + (b.bad ? ' bad' : ''), b.text)));
}

// The session expired mid-job: polling 401s every 5 s forever and the bar
// freezes at whatever it last showed, which reads as a hung download of a job
// that finished hours ago (YTDL-10, 2026-08-11).
function sessionExpired() {
  stopPolling();
  setBanner('session', 'your dashboard session has expired — sign in to the '
            + 'dashboard again and reload this page. The job itself keeps '
            + 'running on the server.', true);
}

function hintFor(err) {
  if (!err) return null;
  for (const [prefix, hint] of HINTS) if (err.startsWith(prefix)) return hint;
  return err;
}

// ---------------------------------------------------------------- health
async function loadHealth() {
  let h;
  try {
    h = await api('api/health');
  } catch {
    return;                       // the page still works; a job will say why
  }
  const pip = $('#health');
  const claudeOk = h.claude === 'ok';
  pip.textContent = `claude ${h.claude}` + (h.yt_dlp === 'ok' ? '' : ' · yt-dlp missing');
  pip.className = 'rstatus ' + (claudeOk && h.yt_dlp === 'ok' ? 'on'
                                : h.claude === 'unknown' ? '' : 'off');
  // The health contract is ok|unauthenticated|missing|timeout|error|unknown.
  // timeout/error used to fall through to the all-clear, so a wedged claude
  // gave no pre-submit warning at all -- the one thing this banner exists for
  // (YTDL-11, 2026-08-11).
  if (h.claude === 'unauthenticated') {
    setBanner('health', HINTS[0][1], true);
  } else if (h.claude === 'missing') {
    setBanner('health', HINTS[1][1], true);
  } else if (h.claude === 'timeout') {
    setBanner('health', HINTS[2][1]);              // amber: it may answer next time
  } else if (h.claude === 'error') {
    setBanner('health', 'Claude Code failed on the server'
              + (h.claude_detail ? `: ${h.claude_detail}` : '')
              + '. Searches will fail until it works — see ytdl/web/DEPLOY.md.', true);
  } else if (h.yt_dlp !== 'ok') {
    setBanner('health', 'yt-dlp is not installed in this container — searching '
              + 'and downloading will both fail. See ytdl/web/DEPLOY.md.', true);
  } else {
    setBanner('health', null);
  }
  // Its own slot, because the poll response reports it too (YTDL-39).
  setBanner('worker', h.worker_alive === false ? WORKER_DEAD : null, true);
}

// ---------------------------------------------------------------- projects
async function loadProjects() {
  const sel = $('#project');
  sel.innerHTML = '';
  let r;
  try {
    r = await api('api/projects');
  } catch (e) {
    sel.appendChild(el('option', null, 'could not load projects'));
    return;
  }
  if (!r.projects_available) {
    sel.appendChild(el('option', null, 'no project list available'));
  }
  if (!r.projects.length) {
    if (r.projects_available) {
      sel.appendChild(el('option', null, 'you are not syncing any project'));
      setBanner('projects', 'You have no projects ticked on the dashboard, so '
                + 'there is nowhere to put downloads. Tick one on the '
                + 'dashboard first.');
    }
    $('#go').disabled = true;
    return;
  }
  setBanner('projects', null);
  $('#go').disabled = false;
  r.projects.forEach(p => {
    const o = el('option', null, p.label);
    o.value = p.slug;
    sel.appendChild(o);
  });
}

// ---------------------------------------------------------------- polling
function stopPolling() {
  if (state.pollTimer) clearTimeout(state.pollTimer);
  state.pollTimer = null;
}

function schedulePoll() {
  stopPolling();
  const elapsed = Date.now() - state.pollStart;
  state.pollTimer = setTimeout(poll, elapsed > BACKOFF_AFTER ? POLL_SLOW : POLL_FAST);
}

// Every await in poll() can land after the editor has attached a DIFFERENT
// job. A stale response used to re-render the old job over the new one's UI
// and -- if it was a TERMINAL one -- stopPolling() the new job's loop dead,
// freezing the page while the job ran to completion server-side (YTDL-9,
// 2026-08-11). The token also covers attach(same id) after a detach.
const stale = (id, token) => state.jobId !== id || state.attachToken !== token;

async function attach(jobId) {
  stopPolling();
  state.attachToken++;
  state.jobId = jobId;
  state.manifest = null;              // job A's videos must not render as B's
  state.termFilter = null;
  setBanner('job', null);
  state.pollStart = Date.now();
  location.hash = `job=${jobId}`;     // a refresh re-attaches to the same job
  await poll();
}

async function poll() {
  const id = state.jobId;
  const token = state.attachToken;
  if (!id) return;
  let r;
  try {
    r = await api(`api/jobs/${id}`);
  } catch (e) {
    if (stale(id, token)) return;
    if (e.status === 404) { detach(); return; }
    if (e.status === 401) { sessionExpired(); return; }
    schedulePoll();                    // a blip must not abandon a running job
    return;
  }
  if (stale(id, token)) return;
  const job = r.job;
  if (job.phase === 'downloading') {
    // The per-video dl_state/dl_error live in the manifest and the in-flight
    // percentages in r.progress; the download list below needs both. The
    // manifest fetch is one SQLite read -- cheap enough per tick.
    let m = null;
    try { m = await api(`api/jobs/${id}/manifest`); }
    catch { /* the bar still moves; the list catches up next tick */ }
    if (stale(id, token)) return;
    if (m) state.manifest = m;
  }
  // The explanation for a bar stuck at "queued" is in every poll response and
  // nothing read it (YTDL-39, 2026-08-11).
  setBanner('worker', r.worker_alive === false && !job.terminal ? WORKER_DEAD : null, true);
  renderProgress(job, r);

  if (job.phase === 'ready_for_review' || job.phase === 'done'
      || job.phase === 'failed' || job.phase === 'cancelled') {
    stopPolling();
    if (job.phase !== 'failed') {
      try {
        await loadManifest(id);
      } catch (e) {
        if (stale(id, token)) return;
        if (e.status === 401) { sessionExpired(); return; }
        // Polling has already stopped here, so one blip at exactly this tick
        // used to leave a full bar, no review grid and no way back but a
        // manual refresh (YTDL-34, 2026-08-11).
        schedulePoll();
        return;
      }
      if (stale(id, token)) return;
    }
    // Re-render the download list off the FINAL manifest, so the last rows
    // show done/failed (with the reason) rather than the last live tick.
    if (job.dl_total) renderProgress(job, r);
    if (job.phase === 'done' || job.phase === 'cancelled') loadRecent();
    return;
  }
  schedulePoll();
}

function detach() {
  stopPolling();
  state.attachToken++;                // orphan any poll response still in flight
  state.jobId = null;
  state.manifest = null;
  setBanner('job', null);
  location.hash = '';
  $('#progress').classList.add('hidden');
  $('#downloads').classList.add('hidden');
  $('#review').classList.add('hidden');
}

// ---------------------------------------------------------------- progress
function renderProgress(job, r) {
  // A job that was cancelled (or failed) mid-download has the same thing to
  // show as a finished one -- which clips landed and which did not. Without
  // cancelled/failed here, a cancel at clip 17 of 41 replaced that list with a
  // red 100% bar (YTDL-36, 2026-08-11).
  const downloading = job.phase === 'downloading'
                      || (job.dl_total > 0 && (job.phase === 'done'
                          || job.phase === 'cancelled' || job.phase === 'failed'));
  $('#progress').classList.toggle('hidden', downloading || job.phase === 'done');
  $('#downloads').classList.toggle('hidden', !downloading);

  // Cleared when the rendered job has no error: the banner belongs to the job
  // on screen, and a failed job's red line used to sit above the next,
  // healthy one all the way through review and download (YTDL-12).
  setBanner('job', job.error ? hintFor(job.error) : null,
            job.phase === 'failed');

  if (downloading) { renderDownloads(job, r); return; }

  const [lo, hi] = PHASE_SPAN[job.phase] || [0, 0];
  let frac = 0;
  if (job.phase === 'searching' && job.terms_total) frac = job.terms_done / job.terms_total;
  if (job.phase === 'enriching' && job.enrich_total) frac = job.enrich_done / job.enrich_total;
  const pct = job.phase === 'failed' || job.phase === 'cancelled'
    ? 100 : Math.min(100, lo + (hi - lo) * frac);

  $('#barfill').style.width = pct + '%';
  $('#barfill').classList.toggle('done', job.phase === 'ready_for_review');
  $('#phase').textContent = PHASE_LABEL[job.phase] || job.phase;

  const bits = [];
  const en = (r.terms || []).filter(t => t.lang === 'en').length;
  const zh = (r.terms || []).filter(t => t.lang === 'zh').length;
  if (job.terms_total) bits.push(`${job.terms_total} terms (${en} en / ${zh} zh)`);
  if (job.phase === 'searching') bits.push(`searched ${job.terms_done}/${job.terms_total}`);
  if (job.candidates) bits.push(`${job.candidates} candidates`);
  if (job.enrich_total) bits.push(`metadata ${job.enrich_done}/${job.enrich_total}`);
  const last = (r.terms || []).filter(t => t.searched).slice(-1)[0];
  if (last && job.phase === 'searching') bits.push(`latest: ${last.term} → ${last.hits} hits`);
  if (job.phase === 'failed') bits.push(job.error || 'failed');
  $('#ticker').textContent = bits.join(' · ');
  $('#cancel').classList.toggle('hidden', !!job.terminal);
}

function renderDownloads(job, r) {
  const total = job.dl_total || 0;
  const done = (job.dl_done || 0) + (job.dl_failed || 0);
  $('#dlfill').style.width = total ? (done * 100 / total) + '%' : '0';
  $('#dlfill').classList.toggle('done', job.phase === 'done');
  $('#dlphase').textContent = PHASE_LABEL[job.phase] || job.phase;
  $('#dlticker').textContent =
    `${job.dl_done || 0}/${total} downloaded` + (job.dl_failed ? ` · ${job.dl_failed} failed` : '');
  $('#cancel2').classList.toggle('hidden', !!job.terminal);

  const list = $('#dllist');
  list.innerHTML = '';
  const live = r.progress || {};
  // Every queued video gets a row -- pending, in flight, done, failed (with
  // its reason), skipped -- not just the ones currently moving. The manifest
  // is re-fetched each tick while downloading, so dl_state is current; the
  // live map overrides it for the file yt-dlp is actually writing.
  const vids = ((state.manifest && state.manifest.videos) || [])
    .filter(v => v.dl_state && v.dl_state !== 'none');
  if (!vids.length) {
    // A refresh mid-download, before the first manifest fetch lands: show
    // what the live map knows rather than nothing.
    Object.keys(live).forEach(vid => {
      const p = live[vid];
      const row = el('div', 'dlrow');
      row.appendChild(el('span', 'name', vid));
      row.appendChild(el('span', 'st', p.status === 'downloading'
        ? `${p.percent == null ? '…' : p.percent + '%'} ${p.speed || ''}`
        : p.status));
      list.appendChild(row);
    });
    return;
  }
  vids.forEach(v => {
    const p = live[v.video_id];
    const row = el('div', 'dlrow'
      + (v.dl_state === 'done' ? ' done' : '')
      + (v.dl_state === 'failed' ? ' failed' : ''));
    row.appendChild(el('span', 'name', v.title || v.video_id));
    let st;
    if (p && p.status === 'downloading') {
      st = `${p.percent == null ? '…' : p.percent + '%'} ${p.speed || ''}`;
    } else if (p && p.status && v.dl_state === 'downloading') {
      st = p.status;                     // 'merging', 'converting to H.264...'
    } else if (v.dl_state === 'failed') {
      st = 'failed — ' + (v.dl_error || 'see the server log');
    } else if (v.dl_state === 'skipped') {
      st = 'already downloaded';
    } else {
      st = v.dl_state;                   // 'pending', 'done', 'downloading'
    }
    row.appendChild(el('span', 'st', st));
    list.appendChild(row);
  });
}

// ---------------------------------------------------------------- manifest
async function loadManifest(jobId = state.jobId) {
  const m = await api(`api/jobs/${jobId}/manifest`);
  if (jobId !== state.jobId) return;   // a newer job owns the screen now
  state.manifest = m;
  $('#review').classList.remove('hidden');
  renderTerms();
  renderGrid();
}

function renderTerms() {
  const box = $('#termchips');
  box.innerHTML = '';
  // Counts are of what the grid will SHOW, not of every linked video: a chip
  // reading "(7)" over an empty grid reads as "the search lost my videos"
  // (YTDL-38, 2026-08-11). The full figure stays in the tooltip.
  const all = el('button', 'chip' + (state.termFilter === null ? ' on' : ''));
  all.appendChild(el('span', null, 'all terms'));
  all.appendChild(el('span', 'n', String(visibleVideos(null).length)));
  all.title = `${state.manifest.videos.length} found in total`;
  all.onclick = () => { state.termFilter = null; renderTerms(); renderGrid(); };
  box.appendChild(all);

  state.manifest.terms.forEach(t => {
    const c = el('button', 'chip'
      + (state.termFilter === t.id ? ' on' : '')
      + (t.source === 'user' ? ' user' : ''));
    c.appendChild(el('span', null, t.term));
    // REQ 5: a Chinese term is unreadable to most of the fleet without this.
    if (t.lang === 'zh' && t.english_gloss) {
      c.appendChild(el('span', 'gloss', '— ' + t.english_gloss));
    }
    const shown = visibleVideos(t.id).length;
    c.appendChild(el('span', 'n', String(shown)));
    c.title = (t.source === 'user' ? 'what you typed' : `generated (${t.lang})`)
      + (shown < t.videos ? ` · ${t.videos - shown} filtered out` : '');
    c.onclick = () => {
      state.termFilter = state.termFilter === t.id ? null : t.id;
      renderTerms(); renderGrid();
    };
    box.appendChild(c);
  });
}

function visibleVideos(termFilter = state.termFilter) {
  return state.manifest.videos.filter(v => {
    const filteredOut = !v.relevant || v.meta_error;
    if (filteredOut && !state.showFiltered) return false;
    if (termFilter !== null && !(v.term_ids || []).includes(termFilter)) return false;
    return true;
  });
}

function renderGrid() {
  const m = state.manifest;
  const c = m.counts;
  $('#counts').textContent =
    `${c.relevant} relevant · ${c.duplicates} already downloaded · ${c.irrelevant} filtered out`;
  const sf = $('#showfiltered');
  sf.classList.toggle('hidden', !c.irrelevant);
  sf.textContent = state.showFiltered ? '[ HIDE FILTERED OUT ]' : '[ SHOW FILTERED OUT ]';

  const grid = $('#grid');
  grid.innerHTML = '';
  const vis = visibleVideos();
  vis.forEach(v => grid.appendChild(card(v)));
  if (!vis.length) {
    // Never an empty grid with no explanation: the filter that is holding the
    // videos back is the one thing the editor needs told (YTDL-38).
    const held = m.videos.filter(v => state.termFilter === null
      || (v.term_ids || []).includes(state.termFilter)).length;
    grid.appendChild(el('div', 'gridempty', held
      ? `all ${held} filtered out — [ SHOW FILTERED OUT ] to see them`
      : 'nothing found for this term'));
  }

  const sel = m.videos.filter(v => v.selected && !v.duplicate);
  const secs = sel.reduce((a, v) => a + (v.duration || 0), 0);
  // Count AND total duration: the only disk-space proxy an editor has, and the
  // destination is the Projects pool that ops watches.
  $('#gridfoot').textContent =
    `${sel.length} selected · ${fmtTotal(secs)} of footage · into ${m.job.project_label}\\Youtube\\${m.job.term_dir}`;
  $('#download').textContent = `DOWNLOAD ${sel.length}`;
  $('#download').disabled = !sel.length || m.job.phase !== 'ready_for_review';
}

function card(v) {
  const filteredOut = !v.relevant || v.meta_error;
  const n = el('div', 'card'
    + (v.selected && !v.duplicate ? ' on' : '')
    + (v.duplicate ? ' dup' : '')
    + (filteredOut ? ' filtered' : ''));

  const img = el('img', 'thumb');
  // Straight from ytimg: no proxying through the NAS for 40 thumbnails, and
  // the fallback URL needs nothing but the video id, so a video whose metadata
  // fetch failed still shows one. no-referrer because the referrer would be
  // the dashboard's internal URL.
  img.loading = 'lazy';
  img.referrerPolicy = 'no-referrer';
  img.src = v.thumbnail || `https://i.ytimg.com/vi/${v.video_id}/mqdefault.jpg`;
  img.alt = '';
  n.appendChild(img);

  if (!v.duplicate) {
    const box = el('input', 'pick');
    box.type = 'checkbox';
    box.checked = !!v.selected;
    box.onclick = e => { e.stopPropagation(); toggle(v, box.checked); };
    n.appendChild(box);
  } else {
    n.appendChild(el('span', 'badge', `ALREADY IN ${v.duplicate_of || 'the tree'}`));
  }

  const meta = el('div', 'meta');
  const a = el('a', 'title', v.title || v.video_id);
  a.href = v.url;
  a.target = '_blank';
  a.rel = 'noreferrer';
  meta.appendChild(a);
  meta.appendChild(el('div', 'sub',
    [v.channel || '?', fmtDur(v.duration), fmtDate(v.upload_date)].filter(Boolean).join(' · ')));
  if (v.meta_error) meta.appendChild(el('div', 'why', 'unavailable'));
  else if (!v.relevant && v.relevance_note) meta.appendChild(el('div', 'why', v.relevance_note));
  n.appendChild(meta);

  n.onclick = () => { if (!v.duplicate) toggle(v, !v.selected); };
  return n;
}

// Per-video: the tail of the in-flight chain, and the sequence number of the
// last click. Unserialised POSTs raced -- last RESPONSE won in the browser
// while last REQUEST won in the database, so a quick check-then-uncheck could
// leave server yes / UI no, and DOWNLOAD takes what the database says
// (YTDL-33, 2026-08-11).
const _selQueue = new Map();
const _selSeq = new Map();

function toggle(v, selected) {
  // Optimistic, so the card follows the click immediately AND the next click
  // sends the opposite of what was clicked rather than of what the server has
  // last confirmed (a double-click used to send {selected:true} twice).
  const was = v.selected;
  v.selected = selected ? 1 : 0;
  renderGrid();

  const seq = (_selSeq.get(v.video_id) || 0) + 1;
  _selSeq.set(v.video_id, seq);
  const run = (_selQueue.get(v.video_id) || Promise.resolve()).then(async () => {
    let r = null, err = null;
    try {
      r = await post(`api/jobs/${state.jobId}/videos/${v.video_id}/select`, {selected});
    } catch (e) {
      err = e;
    }
    // A later click on the same card, or another job on screen, owns the
    // truth now -- this answer is history either way.
    if (_selSeq.get(v.video_id) !== seq || !state.manifest) return;
    if (err) {
      v.selected = was;                // back to what the server still has
      toast(err.message, true);
    } else {
      v.selected = r.selected ? 1 : 0;
      state.manifest.counts = r.counts;
    }
    renderGrid();
  });
  _selQueue.set(v.video_id, run);
  return run;
}

async function bulk(selected) {
  let r;
  try {
    r = await post(`api/jobs/${state.jobId}/select`,
                   {selected, scope: state.showFiltered ? 'all' : 'relevant'});
  } catch (e) {
    // Silent before: the grid simply did not change and the editor pressed
    // DOWNLOAD on a selection the server never made (YTDL-34, 2026-08-11).
    toast(e.message, true);
    return;
  }
  state.manifest.counts = r.counts;
  state.manifest.videos.forEach(v => {
    if (v.duplicate || v.meta_error) return;
    if (!state.showFiltered && !v.relevant) return;
    v.selected = selected ? 1 : 0;
  });
  renderGrid();
}

// ---------------------------------------------------------------- actions
async function runSearch() {
  const go = $('#go');
  // Disabled means either "no projects ticked" or "a POST is already in
  // flight", and Enter in the search box reaches here without the button:
  // a double-click created two active jobs, and the orphaned first one then
  // 409'd every later search naming a job_id nothing was tracking
  // (YTDL-25, 2026-08-11).
  if (go.disabled) return;
  const term = $('#q').value.trim();
  if (!term) return;
  const slug = $('#project').value;
  if (!slug) { toast('pick a project first', true); return; }
  go.disabled = true;
  try {
    const r = await post('api/jobs', {
      term, project_slug: slug,
      quality: $('#quality').value,
      period: $('#period').value || null,
    });
    // Only now: the server decides whether a second job is allowed, and
    // tearing the live view down first left the page showing nothing while
    // the refused-against job kept running (YTDL-8, 2026-08-11).
    detach();
    $('#progress').classList.remove('hidden');
    await attach(r.job_id);
  } catch (e) {
    if (e.status === 409 && e.info && e.info.job_id) {
      // The job the server refused to duplicate is exactly the one the editor
      // has lost sight of -- including a forgotten manifest from last week.
      toast(`${e.message} — showing it below`, false, 12000);
      $('#progress').classList.remove('hidden');
      await attach(e.info.job_id);
    } else {
      toast(e.message, true, 12000);
    }
  } finally {
    go.disabled = false;
  }
}

async function startDownload() {
  try {
    await post(`api/jobs/${state.jobId}/download`);
    $('#review').classList.add('hidden');
    state.pollStart = Date.now();
    await poll();
  } catch (e) {
    toast(e.message, true, 12000);
  }
}

async function cancelJob() {
  if (!state.jobId) return;
  try {
    await post(`api/jobs/${state.jobId}/cancel`);
    toast('cancelling — it stops after the video in flight');
  } catch (e) {
    toast(e.message, true);
  }
}

async function loadRecent() {
  let r;
  try {
    r = await api('api/jobs?limit=15');
  } catch { return; }
  const box = $('#recentlist');
  box.innerHTML = '';
  if (!r.jobs.length) { box.textContent = 'nothing yet'; return; }
  r.jobs.forEach(j => {
    const row = el('div', 'recentrow');
    row.appendChild(el('span', 'when', (j.created_at || '').slice(0, 16).replace('T', ' ')));
    row.appendChild(el('span', 'ph', j.phase));
    row.appendChild(el('span', 'name', `${j.term} → ${j.project_label}`));
    row.onclick = () => attach(j.id);
    box.appendChild(row);
  });
}

// ---------------------------------------------------------------- topbar
// The static header in index.html is a fallback for the standalone dev loop.
// Mounted at /ytdl/ this document-relative fetch resolves to the dashboard's
// /partials/topbar, and the real header -- session, admin links, the whole nav
// -- replaces the fallback, making this a page of the dashboard rather than an
// imitation of one. Standalone the same fetch resolves inside THIS app, 404s,
// and the fallback stays. Never made root-relative: see
// tests/test_mounted_prefix.py.
async function loadDashboardTopbar() {
  try {
    const r = await fetch('../partials/topbar?current=ytdl');
    // redirected = an expired session answered with the login PAGE; injecting
    // that into the header would be worse than keeping the fallback.
    if (!r.ok || r.redirected) return;
    const html = await r.text();
    if (!html.includes('data-dash-topbar')) return;
    document.getElementById('dash-topbar').innerHTML = html;
  } catch {
    /* dashboard unreachable -- the fallback header stands */
  }
}

// ---------------------------------------------------------------- init
async function init() {
  loadDashboardTopbar();
  $('#go').onclick = runSearch;
  $('#q').addEventListener('keydown', e => { if (e.key === 'Enter') runSearch(); });
  $('#cancel').onclick = cancelJob;
  $('#cancel2').onclick = cancelJob;
  $('#selall').onclick = () => bulk(true);
  $('#selnone').onclick = () => bulk(false);
  $('#download').onclick = startDownload;
  // renderTerms too: the chip counts are counts of what the grid shows.
  $('#showfiltered').onclick = () => {
    state.showFiltered = !state.showFiltered;
    renderTerms();
    renderGrid();
  };

  await loadProjects();
  loadHealth();
  // Re-asked on a slow interval so an admin who fixes claude (or restarts the
  // worker) does not have to walk the fleet asking for reloads (YTDL-39).
  setInterval(loadHealth, HEALTH_INTERVAL);
  loadRecent();

  // A refresh mid-job re-attaches rather than losing it: the pipeline runs on
  // the server and the tab is only a viewer.
  const m = /job=(\d+)/.exec(location.hash || '');
  if (m) {
    $('#progress').classList.remove('hidden');
    attach(Number(m[1]));
  }
}

init().catch(e => {
  document.querySelector('#recentlist').textContent = 'failed to load: ' + e.message;
});
