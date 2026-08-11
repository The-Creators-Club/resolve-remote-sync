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

const state = {
  jobId: null,
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
    try {
      const j = await r.json();
      const d = j.detail;
      detail = (typeof d === 'string' ? d : (d && d.detail) || detail);
    } catch { /* not JSON; the status line is all we have */ }
    const e = new Error(detail);
    e.status = r.status;
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

function toast(html, ms = 7000) {
  const t = $('#toast');
  t.innerHTML = html;
  t.classList.remove('hidden');
  clearTimeout(toast._t);
  if (ms) toast._t = setTimeout(() => t.classList.add('hidden'), ms);
}

function warn(text, bad) {
  const w = $('#warn');
  if (!text) { w.classList.add('hidden'); return; }
  w.textContent = text;
  w.classList.toggle('bad', !!bad);
  w.classList.remove('hidden');
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
  if (h.claude === 'unauthenticated') {
    warn(HINTS[0][1], true);
  } else if (h.claude === 'missing') {
    warn(HINTS[1][1], true);
  } else if (h.yt_dlp !== 'ok') {
    warn('yt-dlp is not installed in this container — searching and downloading '
         + 'will both fail. See ytdl/web/DEPLOY.md.', true);
  } else if (!h.worker_alive) {
    warn('the pipeline worker is not running: jobs will queue and never start.', true);
  } else {
    warn(null);
  }
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
      warn('You have no projects ticked on the dashboard, so there is nowhere '
           + 'to put downloads. Tick one on the dashboard first.');
    }
    $('#go').disabled = true;
    return;
  }
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

async function attach(jobId) {
  state.jobId = jobId;
  state.pollStart = Date.now();
  location.hash = `job=${jobId}`;     // a refresh re-attaches to the same job
  await poll();
}

async function poll() {
  if (!state.jobId) return;
  let r;
  try {
    r = await api(`api/jobs/${state.jobId}`);
  } catch (e) {
    if (e.status === 404) { detach(); return; }
    schedulePoll();                    // a blip must not abandon a running job
    return;
  }
  const job = r.job;
  if (job.phase === 'downloading') {
    // The per-video dl_state/dl_error live in the manifest and the in-flight
    // percentages in r.progress; the download list below needs both. The
    // manifest fetch is one SQLite read -- cheap enough per tick.
    try { state.manifest = await api(`api/jobs/${state.jobId}/manifest`); }
    catch { /* the bar still moves; the list catches up next tick */ }
  }
  renderProgress(job, r);

  if (job.phase === 'ready_for_review' || job.phase === 'done'
      || job.phase === 'failed' || job.phase === 'cancelled') {
    stopPolling();
    if (job.phase !== 'failed') await loadManifest();
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
  state.jobId = null;
  state.manifest = null;
  location.hash = '';
  $('#progress').classList.add('hidden');
  $('#downloads').classList.add('hidden');
  $('#review').classList.add('hidden');
}

// ---------------------------------------------------------------- progress
function renderProgress(job, r) {
  const downloading = job.phase === 'downloading'
                      || (job.dl_total > 0 && job.phase === 'done');
  $('#progress').classList.toggle('hidden', downloading || job.phase === 'done');
  $('#downloads').classList.toggle('hidden', !downloading);

  if (job.error) {
    warn(hintFor(job.error), job.phase === 'failed');
  }

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
async function loadManifest() {
  const m = await api(`api/jobs/${state.jobId}/manifest`);
  state.manifest = m;
  $('#review').classList.remove('hidden');
  renderTerms();
  renderGrid();
}

function renderTerms() {
  const box = $('#termchips');
  box.innerHTML = '';
  const all = el('button', 'chip' + (state.termFilter === null ? ' on' : ''));
  all.appendChild(el('span', null, 'all terms'));
  all.appendChild(el('span', 'n', String(state.manifest.videos.length)));
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
    c.appendChild(el('span', 'n', String(t.videos)));
    c.title = t.source === 'user' ? 'what you typed' : `generated (${t.lang})`;
    c.onclick = () => {
      state.termFilter = state.termFilter === t.id ? null : t.id;
      renderTerms(); renderGrid();
    };
    box.appendChild(c);
  });
}

function visibleVideos() {
  return state.manifest.videos.filter(v => {
    const filteredOut = !v.relevant || v.meta_error;
    if (filteredOut && !state.showFiltered) return false;
    if (state.termFilter !== null && !(v.term_ids || []).includes(state.termFilter)) return false;
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
  visibleVideos().forEach(v => grid.appendChild(card(v)));

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

async function toggle(v, selected) {
  try {
    const r = await post(`api/jobs/${state.jobId}/videos/${v.video_id}/select`, {selected});
    v.selected = r.selected ? 1 : 0;
    state.manifest.counts = r.counts;
    renderGrid();
  } catch (e) {
    toast(`<div class="bad">${e.message}</div>`);
  }
}

async function bulk(selected) {
  const r = await post(`api/jobs/${state.jobId}/select`,
                       {selected, scope: state.showFiltered ? 'all' : 'relevant'});
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
  const term = $('#q').value.trim();
  if (!term) return;
  const slug = $('#project').value;
  if (!slug) { toast('<div class="bad">pick a project first</div>'); return; }
  detach();
  try {
    const r = await post('api/jobs', {
      term, project_slug: slug,
      quality: $('#quality').value,
      period: $('#period').value || null,
    });
    $('#progress').classList.remove('hidden');
    await attach(r.job_id);
  } catch (e) {
    toast(`<div class="bad">${e.message}</div>`, 12000);
  }
}

async function startDownload() {
  try {
    await post(`api/jobs/${state.jobId}/download`);
    $('#review').classList.add('hidden');
    state.pollStart = Date.now();
    await poll();
  } catch (e) {
    toast(`<div class="bad">${e.message}</div>`, 12000);
  }
}

async function cancelJob() {
  if (!state.jobId) return;
  try {
    await post(`api/jobs/${state.jobId}/cancel`);
    toast('cancelling — it stops after the video in flight');
  } catch (e) {
    toast(`<div class="bad">${e.message}</div>`);
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
  $('#showfiltered').onclick = () => { state.showFiltered = !state.showFiltered; renderGrid(); };

  await loadProjects();
  loadHealth();
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
