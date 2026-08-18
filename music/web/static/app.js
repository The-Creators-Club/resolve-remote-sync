'use strict';

const $ = s => document.querySelector(s);
const el = (tag, cls, txt) => {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (txt !== undefined) n.textContent = txt;
  return n;
};

const CAT_ABBR = {genre: 'g', mood: 'm', instrument: 'i', use_case: 'u', texture: 't'};
const AXIS_HELP = {
  arousal: ['calm', 'intense'],
  valence: ['dark', 'bright'],
  tension: ['resolved', 'tense'],
  organic: ['electronic', 'acoustic'],
};
const EXAMPLES = [
  'tense driving synth pulse',
  'warm nostalgic piano',
  'hopeful build for a montage payoff',
  'sparse ominous drone under an interview',
  'triumphant orchestral finale',
  'playful quirky plucked strings',
  'traditional east asian strings',
  'gritty industrial percussion',
];
const RESOLVE_ACTIONS = [
  ['bin', 'import to bin', 'Import into the Music bin in the media pool. Nothing is placed on a timeline.'],
  ['under', 'place underneath', 'Place at the playhead on the first free audio track from A2 down. Nothing moves.'],
  ['insert', 'insert at playhead', 'Ripple insert on A2: clips at or after the playhead on that track shift later. Refuses if that track is linked to video.'],
];

const state = {
  facet: null, axis: null,
  bpm: {min: null, max: null},
  dur: {min: null, max: null},
  playing: null,      // track id whose pane is open
  tracks: [],
  peaks: new Map(),   // id -> Uint8Array
  // Monotonic request token. Search, similar and filter all render into the
  // same list and their responses do not come back in the order they were
  // sent -- a slow search landing after the filter that replaced it used to
  // overwrite it (MUSIC-9, 2026-08-11). Only the newest issued query renders.
  seq: 0,
};

const audio = () => $('#audio');

// ---------------------------------------------------------------- helpers
const fmtDur = s => {
  if (!s && s !== 0) return '-';
  const m = Math.floor(s / 60), r = Math.floor(s % 60);
  return `${m}:${String(r).padStart(2, '0')}`;
};

// Every URL here is DOCUMENT-relative ('api/stats'), never leading-slash. A
// leading slash resolves against the origin root, so mounted at /music by the
// dashboard each one would hit the dashboard instead of this app. Relative
// works at both / and /music/ with no build step and no injected base tag --
// see tests/test_mounted_prefix.py.
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${path} -> ${r.status}`);
  return r.json();
}

// Takes a NODE, not markup (MUSIC-15, 2026-08-11): what goes in here is
// server-supplied -- indexer rel_paths, raw ffmpeg stderr, filenames that
// safe_upload_name does not filter for HTML -- and it used to be assigned to
// innerHTML. Build content with el()/textContent.
function toast(node, ms = 6000) {
  const t = $('#toast');
  t.textContent = '';
  t.appendChild(node);
  t.classList.remove('hidden');
  clearTimeout(toast._t);
  if (ms) toast._t = setTimeout(() => t.classList.add('hidden'), ms);
}

// ---------------------------------------------------------------- waveform
async function loadPeaks(id) {
  if (state.peaks.has(id)) return state.peaks.get(id);
  const r = await fetch(`api/peaks/${id}`);
  // A 404/500 body is JSON, and drawing it as a waveform then CACHING it left
  // the track with permanent garbage peaks until a reload (MUSIC-4,
  // 2026-08-11). Nothing but a real answer is remembered.
  if (!r.ok) return new Uint8Array(0);
  const buf = new Uint8Array(await r.arrayBuffer());
  state.peaks.set(id, buf);
  return buf;
}

function drawWave(canvas, peaks, progress) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.clientHeight;
  if (!w || !h) return;
  if (canvas.width !== Math.round(w * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  if (!peaks || !peaks.length) return;

  const BAR = 2, GAP = 1, step = BAR + GAP;
  const bars = Math.max(1, Math.floor(w / step));
  const per = peaks.length / bars;
  const mid = h / 2;
  // Bars strictly BEFORE the playhead are played, and the count is rounded, not
  // floored (MUSIC-14, 2026-08-11): `i <= floor(...)` painted bar 0 red at
  // progress 0 -- every "→ Resolve" open showed a track as already playing --
  // and never filled the last bar at progress 1.
  const played = Math.round(bars * (progress || 0));

  for (let i = 0; i < bars; i++) {
    // peak of the source bucket, so transients survive the downsample
    let v = 0;
    const a = Math.floor(i * per), b = Math.max(a + 1, Math.floor((i + 1) * per));
    for (let j = a; j < b && j < peaks.length; j++) if (peaks[j] > v) v = peaks[j];
    const bh = Math.max(1.5, (v / 255) * (h - 4));
    // Theme colors, hardcoded because canvas cannot read CSS vars cheaply:
    // played = --red, unplayed = --border (style.css).
    ctx.fillStyle = i < played ? '#ff2140' : '#2a2a31';
    ctx.fillRect(i * step, mid - bh / 2, BAR, bh);
  }
}

// ---------------------------------------------------------------- player pane
let _onResize = null;

function closePane() {
  if (_onResize) { window.removeEventListener('resize', _onResize); _onResize = null; }
  const open = document.querySelector('.pane.open');
  if (open) {
    open.classList.remove('open');
    setTimeout(() => open.remove(), 280);
  }
  document.querySelectorAll('.track').forEach(r => {
    r.classList.remove('playing');
    const b = r.querySelector('.play');
    if (b) b.textContent = '▶';
  });
  state.playing = null;
}

async function openPane(row, t, autoplay) {
  if (state.playing === t.id) return;
  closePane();
  state.playing = t.id;
  row.classList.add('playing');

  const pane = el('div', 'pane');
  const inner = el('div', 'paneinner');

  const wrap = el('div', 'wavewrap');
  const canvas = el('canvas', 'wave');
  wrap.appendChild(canvas);
  inner.appendChild(wrap);

  const bar = el('div', 'paneb');
  const pbtn = el('button', 'pbtn', '❚❚');
  const time = el('div', 'ptime', `0:00 / ${fmtDur(t.duration)}`);
  const acts = el('div', 'pacts');
  const msg = el('div', 'rmsg');

  RESOLVE_ACTIONS.forEach(([action, label, help]) => {
    const b = el('button', 'rs', label);
    b.title = help;
    b.onclick = () => sendToResolve(t, action, b, msg);
    acts.appendChild(b);
  });
  const sim = el('button', null, 'similar');
  sim.onclick = () => showSimilar(t);
  acts.appendChild(sim);
  const rev = el('button', null, 'reveal');
  rev.onclick = () => revealOnThisMachine(t, rev, msg);
  acts.appendChild(rev);

  bar.append(pbtn, time, acts);
  inner.append(bar, msg);
  pane.appendChild(inner);
  row.after(pane);
  requestAnimationFrame(() => pane.classList.add('open'));

  const a = audio();
  a.src = `api/audio/${t.id}`;
  if (autoplay) a.play().catch(() => {});

  // Everything up to the peaks fetch is synchronous ON PURPOSE (MUSIC-8,
  // 2026-08-11). The pane is already on screen and animating by here, and the
  // handlers used to be assigned after `await loadPeaks` -- so pause and seek
  // were dead for the length of that round-trip, seconds over Tailscale when
  // /api/peaks has to rebuild a waveform with ffmpeg.
  let peaks = new Uint8Array(0);
  const dur = () => a.duration || t.duration || 1;
  const paint = () => drawWave(canvas, peaks, a.currentTime / dur());
  paint();

  const tick = () => {
    if (state.playing !== t.id) return;
    paint();
    time.textContent = `${fmtDur(a.currentTime)} / ${fmtDur(dur())}`;
    pbtn.textContent = a.paused ? '▶' : '❚❚';
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);

  pbtn.onclick = () => { a.paused ? a.play().catch(() => {}) : a.pause(); };
  wrap.onclick = e => {
    const r = wrap.getBoundingClientRect();
    a.currentTime = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * dur();
    paint();
  };
  _onResize = () => { if (state.playing === t.id) paint(); };
  window.addEventListener('resize', _onResize);

  peaks = await loadPeaks(t.id).catch(() => new Uint8Array(0));
  if (state.playing !== t.id) return;        // pane closed while we waited
  paint();
}

function togglePlay(row, t) {
  const a = audio();
  if (state.playing === t.id) {
    a.paused ? a.play().catch(() => {}) : a.pause();
    return;
  }
  openPane(row, t, true);
}

// ---------------------------------------------------------------- resolve
// These calls go to the EDITOR'S OWN MACHINE, not to this server, and are
// therefore the only absolute URLs in this file.
//
// The web app is served from the NAS. Its 127.0.0.1 is the NAS, so it cannot
// reach the Resolve an editor is sitting in front of -- only that editor's
// browser can. So the page talks to the ccsync companion's loopback server
// directly, exactly as the b-roll UI's "Send to Resolve" does. Do not "fix"
// this by proxying it through the API: that would drive Resolve on the NAS.
//
// The companion translates (share, rel_path) to whatever the library is
// mounted at locally -- P:\Assets\Music for an editor, W:\... on the base rig
// -- which is why the DB stores the pair and never an absolute path.
const COMPANION = 'http://127.0.0.1:8899';

async function companion(path, opts) {
  const r = await fetch(COMPANION + path, opts);
  if (!r.ok) throw new Error(`companion ${r.status}`);
  return r.json();
}

async function sendToResolve(t, action, btn, msg) {
  const acts = btn.parentElement.querySelectorAll('button');
  acts.forEach(b => { b.disabled = true; });
  msg.className = 'rmsg';
  msg.textContent = 'talking to Resolve…';
  try {
    const payload = {action, share: t.share || 'music', rel_path: t.rel_path};
    let r;
    // The library is not a synced folder, so on a remote editor's machine the
    // track is usually NOT here yet: the companion pulls it down on demand and
    // answers state:"downloading" with progress until it is (2026-08-16, the
    // same contract as the b-roll insert). Re-POST the identical body every
    // 1.5 s; the poll that finds the file in place performs the send.
    let announced = false;
    for (;;) {
      r = await companion('/music/send', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      if (r && r.state === 'downloading') {
        const pct = r.progress && Number.isInteger(r.progress.percent) ? r.progress.percent : null;
        msg.className = 'rmsg';
        msg.textContent = announced
          ? (pct == null ? 'syncing the track to this machine…' : `syncing the track to this machine: ${pct}%`)
          : 'track isn’t on this machine yet: syncing it down, then sending…';
        announced = true;
        await new Promise(res => setTimeout(res, 1500));
        continue;
      }
      break;
    }
    msg.className = 'rmsg ' + (r.ok ? 'ok' : 'err');
    msg.textContent = r.ok ? (r.note || 'done') : (r.error || 'failed');
  } catch (e) {
    msg.className = 'rmsg err';
    // The two failure shapes were INVERTED here (2026-08-12): an Error
    // starting "companion" comes from companion() after the tray app
    // ANSWERED with an HTTP error -- it is running; while a TypeError from
    // fetch() means the request never reached 127.0.0.1 -- companion down,
    // OR the browser blocked local connections (Chrome's local-network
    // permission on an http:// dashboard origin does exactly this).
    msg.textContent = e.message.startsWith('companion')
      ? `the companion answered but refused the request (${e.message}), see its log`
      : 'couldn’t reach the ccsync companion: tray app not running, or the '
        + 'browser blocked local connections (self-test: open '
        + 'http://127.0.0.1:8899/status)';
  } finally {
    acts.forEach(b => { b.disabled = false; });
    refreshResolveStatus();
  }
}

// Reveal goes to the companion too (MUSIC-6, 2026-08-14). It used to GET
// `api/reveal/<id>`, which ran Explorer on whatever host served the page: the
// base rig standalone, and on the NAS a 200 {"ok": false} that this handler
// threw away -- so for every editor the button did nothing at all, silently,
// forever. Only the editor's own browser can reach the editor's own Explorer.
async function revealOnThisMachine(t, btn, msg) {
  btn.disabled = true;
  msg.className = 'rmsg';
  msg.textContent = 'opening the folder…';
  try {
    const r = await companion('/music/reveal', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({share: t.share || 'music', rel_path: t.rel_path}),
    });
    msg.className = 'rmsg ' + (r.ok ? 'ok' : 'err');
    msg.textContent = r.ok ? (r.message || 'opened') : (r.error || r.message || 'failed');
  } catch (e) {
    msg.className = 'rmsg err';
    // Same two shapes sendToResolve distinguishes -- and one more here: a
    // companion older than the build that added /music/reveal answers 404,
    // which arrives as "companion 404" rather than as silence.
    msg.textContent = e.message.startsWith('companion')
      ? `the companion refused the request (${e.message}): an older build has `
        + 'no reveal; update the tray app'
      : 'couldn’t reach the ccsync companion: tray app not running, or the '
        + 'browser blocked local connections (self-test: open '
        + 'http://127.0.0.1:8899/status)';
  } finally {
    btn.disabled = false;
  }
}

async function refreshResolveStatus() {
  const s = $('#rstatus');
  try {
    const r = await companion('/music/status');
    if (r.ok) {
      s.className = 'rstatus on';
      s.textContent = `Resolve · ${r.timeline || r.project || 'connected'}`;
      s.title = `project ${r.project || 'none'} · timeline ${r.timeline || 'none open'}`;
    } else {
      s.className = 'rstatus off';
      s.textContent = 'Resolve · off';
      s.title = r.error || 'not connected';
    }
  } catch {
    s.className = 'rstatus off';
    s.textContent = 'Resolve · off';
  }
}

// ---------------------------------------------------------------- rendering
function trackRow(t, showMatch) {
  const row = el('div', 'track');
  row.dataset.id = t.id;

  const play = el('button', 'play', '▶');
  play.onclick = () => togglePlay(row, t);
  row.appendChild(play);

  const mid = el('div');
  mid.appendChild(el('div', 'tname', t.filename));

  const meta = el('div', 'tmeta');
  meta.appendChild(el('span', 'pill', fmtDur(t.duration)));
  if (t.bpm) meta.appendChild(el('span', 'pill', `${Math.round(t.bpm)} bpm`));
  if (t.music_key) meta.appendChild(el('span', 'pill', t.music_key));

  for (const cat of ['genre', 'mood', 'instrument', 'use_case']) {
    const tags = (t.tags && t.tags[cat]) || [];
    (cat === 'mood' ? tags.slice(0, 2) : tags.slice(0, 1)).forEach(tag => {
      const p = el('span', `pill ${CAT_ABBR[cat]} click`, tag.label);
      p.title = `${cat} · score ${tag.score} · ${tag.pct}th percentile`;
      p.onclick = e => { e.stopPropagation(); selectFacet(cat, tag.label); };
      meta.appendChild(p);
    });
  }
  mid.appendChild(meta);
  row.appendChild(mid);

  const right = el('div', 'tright');
  if (showMatch && t.match !== undefined) right.appendChild(el('div', 'match', `${t.match}%`));
  const btns = el('div', 'rowbtns');
  const sim = el('button', null, 'similar');
  sim.onclick = () => showSimilar(t);
  btns.appendChild(sim);
  const res = el('button', null, '→ Resolve');
  res.onclick = () => openPane(row, t, false);
  btns.appendChild(res);
  right.appendChild(btns);
  row.appendChild(right);
  return row;
}

function render(tracks, headline, showMatch) {
  // #audio lives OUTSIDE #list and has no controls, so wiping the list while a
  // preview played left it running with nothing to stop it (MUSIC-5,
  // 2026-08-11) -- closePane() also clears state.playing and the row markers.
  closePane();
  const a = audio();
  if (a) a.pause();
  state.tracks = tracks;
  const head = $('#resulthead');
  head.textContent = '';
  head.appendChild(el('span', null, headline));
  head.appendChild(el('span', 'muted', `${tracks.length} track${tracks.length === 1 ? '' : 's'}`));

  const list = $('#list');
  list.textContent = '';
  if (!tracks.length) {
    list.appendChild(el('div', 'empty', 'Nothing matches. Try a looser description or clear the filters.'));
    return;
  }
  const frag = document.createDocumentFragment();
  tracks.forEach(t => frag.appendChild(trackRow(t, showMatch)));
  list.appendChild(frag);
}

// ---------------------------------------------------------------- queries
function filterParams() {
  const p = new URLSearchParams();
  if (state.facet) { p.set('category', state.facet.category); p.set('label', state.facet.label); }
  if (state.axis) { p.set('axis', state.axis.axis); p.set('axis_min', state.axis.min); }
  if (state.bpm.min) p.set('bpm_min', state.bpm.min);
  if (state.bpm.max) p.set('bpm_max', state.bpm.max);
  if (state.dur.min) p.set('dur_min', state.dur.min);
  if (state.dur.max) p.set('dur_max', state.dur.max);
  return p;
}

// Every query goes out with a token and renders only if it is still the newest
// one issued (MUSIC-9, 2026-08-11). A text search costs a CLAP embed and a
// filter is a plain SELECT, so typing a query and then clicking a facet
// reliably raced -- the search's results landed last and replaced the filter
// the user was looking at, with the wrong headline over them.
async function loadTracks() {
  const bits = [];
  if (state.facet) bits.push(`${state.facet.category}: ${state.facet.label}`);
  if (state.axis) bits.push(`${state.axis.axis} ≥ ${state.axis.min}`);
  if (state.bpm.min || state.bpm.max) bits.push(`${state.bpm.min || 0}–${state.bpm.max || '∞'} bpm`);
  const seq = ++state.seq;
  const {tracks} = await api('api/tracks?' + filterParams().toString());
  if (seq !== state.seq) return;
  render(tracks, bits.length ? bits.join('  ·  ') : 'All tracks', false);
}

async function runSearch(q) {
  if (!q.trim()) return loadTracks();
  $('#q').value = q;
  render([], 'Searching…', false);
  const pool = $('#pool').value;
  const seq = ++state.seq;
  const {tracks} = await api('api/search', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({query: q, k: 60, pool}),
  });
  if (seq !== state.seq) return;
  render(tracks, `“${q}” · ${pool === 'mean' ? 'whole track' : 'any moment'}`, true);
}

async function showSimilar(t) {
  render([], 'Finding similar…', false);
  const seq = ++state.seq;
  const {tracks} = await api(`api/similar/${t.id}?k=25`);
  if (seq !== state.seq) return;
  render(tracks, `Similar to ${t.filename}`, true);
}

function selectFacet(category, label) {
  state.facet = (state.facet && state.facet.category === category
                 && state.facet.label === label) ? null : {category, label};
  $('#q').value = '';
  paintFacets();
  loadTracks();
}

// ---------------------------------------------------------------- sidebar
let FACETS = {};

function paintFacets() {
  const box = $('#facets');
  box.textContent = '';
  for (const [cat, labels] of Object.entries(FACETS)) {
    if (cat.startsWith('_')) continue;
    const sec = el('section', 'facet');
    sec.appendChild(el('h2', null, cat.replace('_', ' ')));
    const chips = el('div', 'chips');
    labels.forEach(l => {
      const c = el('button', 'chip');
      c.appendChild(el('span', null, l.label));
      c.appendChild(el('span', 'n', l.count));
      if (state.facet && state.facet.category === cat && state.facet.label === l.label) {
        c.classList.add('on');
      }
      c.onclick = () => selectFacet(cat, l.label);
      chips.appendChild(c);
    });
    sec.appendChild(chips);
    box.appendChild(sec);
  }
}

function paintAxes(axes) {
  const box = $('#axes');
  box.textContent = '';
  axes.forEach(axis => {
    const wrap = el('div', 'axis');
    const lab = el('div', 'lab');
    const [lo, hi] = AXIS_HELP[axis] || ['low', 'high'];
    lab.appendChild(el('span', null, `${axis}: ${lo} → ${hi}`));
    const val = el('span', 'val', 'off');
    lab.appendChild(val);
    wrap.appendChild(lab);

    const r = el('input');
    r.type = 'range'; r.min = 0; r.max = 100; r.value = 0; r.step = 5;
    r.oninput = () => { val.textContent = r.value === '0' ? 'off' : `top ${100 - r.value}%`; };
    r.onchange = () => {
      box.querySelectorAll('input[type=range]').forEach(o => {
        if (o !== r) { o.value = 0; o.parentElement.querySelector('.val').textContent = 'off'; }
      });
      state.axis = r.value === '0' ? null : {axis, min: +r.value};
      loadTracks();
    };
    wrap.appendChild(r);
    box.appendChild(wrap);
  });
}

// ---------------------------------------------------------------- ingest
function wireDropzone() {
  const zone = $('#drop');
  let depth = 0;
  const hasFiles = e => e.dataTransfer &&
    Array.from(e.dataTransfer.types || []).includes('Files');

  window.addEventListener('dragenter', e => {
    if (!hasFiles(e)) return;
    e.preventDefault(); depth++; zone.classList.add('on');
  });
  window.addEventListener('dragover', e => { if (hasFiles(e)) e.preventDefault(); });
  window.addEventListener('dragleave', e => {
    if (!hasFiles(e)) return;
    depth = Math.max(0, depth - 1);
    if (!depth) zone.classList.remove('on');
  });
  window.addEventListener('drop', async e => {
    if (!hasFiles(e)) return;
    e.preventDefault(); depth = 0; zone.classList.remove('on');
    // Both halves of the DataTransfer are read HERE, synchronously: it is
    // neutered the instant either handler yields, and `files` is what the
    // fallback below needs after ingest.js has had its await.
    const files = Array.from(e.dataTransfer.files || []);
    // The companion flow takes the drop when this editor has one (music
    // ingest step 4): their own machine analyses the audio and uploads it,
    // instead of the browser posting it here for the base rig to index.
    // `miHandleDrop` answers false when there is no companion (or one too old
    // for /music/ingest/*), which falls through to that older path -- it is
    // the documented fallback, not a dead branch.
    if (typeof miHandleDrop === 'function' && await miHandleDrop(e.dataTransfer, files)) {
      return;
    }
    if (files.length) await ingest(files);
  });
}

// Two possible answers, and the toast must not conflate them. On the base rig
// the file is decoded, embedded and tagged inside the request, so it really is
// in the library by the time this returns. On a host with no GPU it has only
// been landed in the share and queued - claiming a bpm and a key there, or
// even "added", would be a lie that sends the editor searching for a cue that
// is not indexed yet.
async function ingest(files) {
  const uploading = document.createDocumentFragment();
  uploading.appendChild(el('div', 'row',
    `Uploading ${files.length} file${files.length === 1 ? '' : 's'}…`));
  uploading.appendChild(el('div', 'muted',
    'checking for duplicates: this can take a few seconds each'));
  toast(uploading, 0);
  const fd = new FormData();
  files.forEach(f => fd.append('files', f, f.name));
  try {
    const r = await api('api/ingest', {method: 'POST', body: fd});
    const out = document.createDocumentFragment();
    const n = r.results.length;
    // The mode, not the count: "Queued 0/2" is the right thing to say when a
    // queueing host rejected both files as duplicates.
    const head = el('div', 'row');
    head.appendChild(el('strong', null, r.mode === 'queued'
      ? `Queued ${r.queued}/${n}` : `Added ${r.added}/${n}`));
    out.appendChild(head);
    if (r.mode === 'queued' && r.queued) {
      out.appendChild(el('div', 'muted',
        'nothing was analysed: this host has no GPU. They are in the library and '
        + 'will not be searchable until the base rig indexes them'
        + (r.pending > r.queued ? ` (${r.pending} waiting in all)` : '') + '.'));
    }
    r.results.forEach(x => {
      const tc = x.transcoded ? ' (transcoded to mp3)' : '';
      if (x.status === 'queued')
        out.appendChild(el('div', 'row',
          `◷ ${x.name}${tc} - ${fmtDur(x.duration)}, queued for indexing`));
      else if (x.ok)
        out.appendChild(el('div', 'row good', `✓ ${x.name}${tc} - ${fmtDur(x.duration)}`
          + (x.bpm ? ', ' + Math.round(x.bpm) + ' bpm' : '')));
      else
        // x.name and x.error carry indexer rel_paths and raw ffmpeg stderr,
        // neither of them filtered for HTML by safe_upload_name (MUSIC-15).
        out.appendChild(el('div', 'row bad', `✕ ${x.name} - ${x.error}`));
    });
    toast(out, 9000);
    if (r.added) {
      FACETS = await api('api/facets');
      paintFacets();
      const s = await api('api/stats');
      $('#stats').textContent =
        `${s.tracks} tracks · ${s.hours}h · ${s.gb} GB · ${s.model || 'unindexed'}`;
      const added = r.results.filter(x => x.ok && x.track).map(x => x.track);
      // ++seq: this render is the newest answer, so a query still in flight
      // must not land on top of it (MUSIC-9).
      ++state.seq;
      if (added.length) render(added, `Just added`, false);
      else await loadTracks();
    }
  } catch (e) {
    toast(el('div', 'row bad', `Ingest failed: ${e.message}`), 9000);
  }
}

// ---------------------------------------------------------------- topbar
// The static header in index.html is a fallback for the standalone dev loop.
// Mounted at /music/ this document-relative fetch resolves to the dashboard's
// /partials/topbar, and the real header -- session, admin links, the whole nav
// -- replaces the fallback, making this a page of the dashboard rather than an
// imitation of one. Standalone the same fetch resolves inside THIS app, 404s,
// and the fallback stays. Never made root-relative: see
// tests/test_mounted_prefix.py.
async function loadDashboardTopbar() {
  try {
    const r = await fetch('../partials/topbar?current=music');
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
  const s = await api('api/stats');
  $('#stats').textContent =
    `${s.tracks} tracks · ${s.hours}h · ${s.gb} GB · ${s.model || 'unindexed'}`;

  FACETS = await api('api/facets');
  paintFacets();
  paintAxes(FACETS._axes || []);

  const ex = $('#examples');
  EXAMPLES.forEach(q => {
    const b = el('button', null, q);
    b.onclick = () => runSearch(q);
    ex.appendChild(b);
  });

  $('#go').onclick = () => runSearch($('#q').value);
  $('#pool').onchange = () => { if ($('#q').value.trim()) runSearch($('#q').value); };
  $('#q').addEventListener('keydown', e => { if (e.key === 'Enter') runSearch($('#q').value); });
  $('#clear').onclick = () => {
    $('#q').value = '';
    state.facet = null; state.axis = null;
    state.bpm = {min: null, max: null}; state.dur = {min: null, max: null};
    ['bpmMin', 'bpmMax', 'durMin', 'durMax'].forEach(i => { $('#' + i).value = ''; });
    document.querySelectorAll('#axes input[type=range]').forEach(r => {
      r.value = 0; r.parentElement.querySelector('.val').textContent = 'off';
    });
    paintFacets(); loadTracks();
  };
  $('#applyRange').onclick = () => {
    state.bpm = {min: +$('#bpmMin').value || null, max: +$('#bpmMax').value || null};
    state.dur = {min: +$('#durMin').value || null, max: +$('#durMax').value || null};
    loadTracks();
  };

  audio().addEventListener('ended', () => {
    const b = document.querySelector('.pbtn');
    if (b) b.textContent = '▶';
  });

  wireDropzone();
  refreshResolveStatus();
  setInterval(refreshResolveStatus, 30000);
  await loadTracks();
}

init().catch(e => {
  document.querySelector('#list').textContent = 'Failed to load: ' + e.message;
});
