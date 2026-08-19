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
// The prefixes are unchanged since 2026-08-17; what two of them MEAN is not.
// The server stopped shelling out to the `claude` CLI and now calls the
// Anthropic API with a key the customer supplies, so claude_auth: is "set
// ANTHROPIC_API_KEY", not "run the one-time login", and claude_missing: is a
// broken container rather than a missing binary an operator forgot to install
// (docs/COMMERCIAL_READINESS.md item 1).
//
// 2026-08-18: there are five possible backends now (dashboard Settings -> AI
// providers), so the wording says "AI provider" rather than naming Anthropic
// -- the prefixes themselves are still the four above because an editor's
// cached bundle and the server have to agree on them.
const HINTS = [
  ['claude_auth:', 'This deployment has no working AI provider credential. An admin must add one on the dashboard: Settings → AI providers (or set ANTHROPIC_API_KEY on the container). See ytdl/web/DEPLOY.md. Nothing else on this page is affected.'],
  ['claude_missing:', 'The dashboard container cannot reach the configured AI provider (missing SDK or CLI, or no route out). See ytdl/web/DEPLOY.md.'],
  ['claude_timeout:', 'The AI provider did not answer in time. Try the search again; if it keeps happening the server is overloaded.'],
  ['claude_output:', 'The AI provider answered with something this app could not read. Trying again usually works.'],
];

// Display names for GET api/health's `ai_provider`. Mirrors
// ytdlweb.ai_backend.PROVIDER_ORDER; an unknown value falls back to the old
// word rather than showing a raw key.
const PROVIDER_NAMES = {
  claude_code: 'claude code',
  anthropic_api: 'claude api',
  codex: 'codex',
  openai_api: 'openai',
  deepseek_api: 'deepseek',
};

// The shot-type checkboxes. Mirrors ytdlweb.claude_cli.SHOT_TYPES -- key,
// label and default tick -- and tests/test_static_app.py compares the two
// tables key for key, because the server owns the prompt fragments and this
// list is only their names. `group` is layout ('footage' = shots OF the
// subject, 'coverage' = somebody talking about it); `short` is what fits in a
// Recent searches row.
const SHOT_TYPES = [
  {key: 'aerial', label: 'Aerial / drone', on: true, group: 'footage', short: 'aerial'},
  {key: 'establishing', label: 'Establishing / exteriors', on: true, group: 'footage', short: 'establishing'},
  {key: 'walkthrough', label: 'Walk-through / POV / street', on: true, group: 'footage', short: 'walk-through'},
  {key: 'timelapse', label: 'Timelapse', on: true, group: 'footage', short: 'timelapse'},
  {key: 'event', label: 'Ceremonies / events / protests', on: true, group: 'footage', short: 'events'},
  {key: 'raw', label: 'Raw / uncut / no commentary', on: true, group: 'footage', short: 'raw'},
  {key: 'interview', label: 'Interviews / talking heads', on: false, group: 'coverage', short: 'interviews'},
  {key: 'news', label: 'News reports', on: false, group: 'coverage', short: 'news'},
  {key: 'commentary', label: 'Commentary / analysis / reaction', on: false, group: 'coverage', short: 'commentary'},
];
// Per browser, not per job: an editor cutting one film ticks the same boxes all
// week, and re-ticking them on every visit is exactly the friction the fixed
// bias was replaced to avoid.
const SHOTS_KEY = 'ytdl.shot_types';

// WHAT THE SEARCH IS FOR (2026-08-18, the owner: "if you're downloading for
// montages, you ideally just want news clips with lots of relevant audio.
// Maybe we should have a mode for 'visuals' and 'news montages'"). Mirrors
// ytdlweb.claude_cli.MODES -- key, label and the preset ticks -- and
// tests/test_static_app.py compares the two tables key for key, because the
// SERVER owns both rubrics and this file owns only the words on the toggle.
//
// `preset` is what CHOOSING a mode ticks. It is a starting point, not a rule:
// the editor adjusts the boxes afterwards and what they leave ticked is what
// gets posted, in either mode.
const SEARCH_MODES = [
  {key: 'visuals', label: 'VISUALS', short: 'visuals',
   preset: ['aerial', 'establishing', 'walkthrough', 'timelapse', 'event', 'raw'],
   hint: 'B-roll to cut UNDER something else: footage of the subject, and the '
         + 'clip audio is usually thrown away'},
  {key: 'news', label: 'NEWS MONTAGE', short: 'news montage',
   preset: ['interview', 'news', 'commentary'],
   hint: 'A montage made OF the reporting: clips whose own audio carries the '
         + 'story, so speech about the subject is what counts'},
];
const DEFAULT_MODE = 'visuals';
// Remembered per browser like the ticks and the candidate cap are.
const MODE_KEY = 'ytdl.search_mode';

// How many candidates one search may collect. Mirrors
// ytdlweb.config.CANDIDATE_CAPS -- the server validates against its own list
// and tests/test_static_app.py compares the two -- because each candidate is a
// metadata request at YouTube, and 112 of those in a burst is where the NAS's
// IP got refused outright (2026-08-11). 100 is the default for that reason;
// 400 is there for a genuinely thin topic, chosen rather than stumbled into.
const CANDIDATE_CAPS = [50, 100, 200, 400];
const DEFAULT_CAP = 100;
// Remembered like the shot ticks are, and for the same reason: the editor who
// needs 400 for a thin topic needs it all afternoon.
const CAP_KEY = 'ytdl.max_candidates';

// The destination, remembered for a blunter reason than the other two: with
// nothing remembered the picker sits on whatever the server listed FIRST, and
// on 2026-08-14 sixteen term folders meant for 2026/FF5/Energy Transition
// (position 3 in that editor's list) landed in 2026/CCT/Creator Profiles/
// Season 1 (position 1) one search at a time -- reported as "the folder select
// keeps switching back to Creator Profiles".
const PROJECT_KEY = 'ytdl.project';

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

// The companion's loopback server, the way b-roll and music reach it. The
// SECOND deliberate absolute URL in this file (after the ytimg thumbnail), and
// for the opposite reason to the relative ones: this must NOT resolve against
// the dashboard's origin -- the page is served from the NAS and the thing being
// asked to open a folder is the editor's OWN machine. Only their companion
// knows where the Projects tree is mounted there, which is why the request
// carries a path relative to that root and never a drive letter.
const COMPANION_URL = 'http://127.0.0.1:8899';

// One page of download history. Small because the panel is a list of pictures
// at the bottom of a page nobody scrolls to first, and the ledger is permanent
// -- the fleet's whole download history is a table that only grows.
const HISTORY_PAGE = 24;

const state = {
  jobId: null,
  attachToken: 0,      // bumped by every attach/detach; see stale() below
  localDownload: false,// the server's YTDL_LOCAL_DOWNLOAD flag, off until health
                       // says otherwise: with it off this page never speaks to
                       // the companion about downloads and shows no executor
                       // badge (docs/YTDL_LOCAL_DOWNLOAD.md §10, phase 1)
  manifest: null,      // {videos, terms, counts}
  termFilter: null,    // job_terms.id, or null for "everything"
  showFiltered: false,
  shots: new Set(),    // ticked shot-type keys; init() fills it
  searchMode: DEFAULT_MODE,  // 'visuals' | 'news' -- which rubric the two AI
                       // passes run under; init() fills it from localStorage
  collapsed: new Set(),// folded-away panel ids; initPanels() fills it
  phase: null,         // the last phase this page SAW for the attached job:
                       // "newly reached ready_for_review" is a transition, not
                       // a state (see forceExpandReview)
  pollTimer: null,
  pollStart: 0,
  historyOffset: 0,    // how many ledger rows are already on screen
  // The rights/ToS attestation (COMMERCIAL_READINESS.md item 2, 2026-08-17).
  // FALSE until the server says otherwise: an editor who has not accepted, and
  // a page that could not ask, are the same state here, and it is the one that
  // keeps the GO buttons disabled.
  attested: false,
  attestVersion: '',
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
  if (!s && s !== 0) return '-';
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

// For the panel-header summaries, which are read at a glance: "1 clips" reads
// as a bug in the count rather than as a count of one.
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

// A stored (forward-slash) relative path as an editor reads it. split/join
// rather than a replace with a regex literal: a slash-escaping pattern puts a
// slash immediately after an opening bracket, which is exactly the shape
// tests/test_mounted_prefix.py refuses to see in a shipped asset. Deny by
// default is the point of that guard (YTDL-42), so this file works around it
// rather than the other way round.
const winPath = s => String(s || '').split('/').join('\\');
// Everything but the last segment of a backslash path -- the FOLDER a file is
// in, which is what a "reveal" is actually about.
const winParent = s => String(s || '').slice(0, Math.max(0, String(s || '').lastIndexOf('\\')));

// One thumbnail, for the review card and the download row alike. Straight from
// ytimg: no proxying 40 images through the NAS, and the FALLBACK URL needs
// nothing but the video id -- which is why a pasted link gets a picture at all,
// since a url job never runs an enrich phase and its `thumbnail` is always NULL
// (2026-08-11). A video whose metadata fetch failed shows one for the same
// reason. no-referrer because the referrer would be the dashboard's internal
// URL. The one deliberate absolute URL in this file besides the [ DASHBOARD ]
// link -- see tests/test_mounted_prefix.py.
function thumb(v, cls) {
  const img = el('img', cls);
  img.loading = 'lazy';
  img.referrerPolicy = 'no-referrer';
  img.src = v.thumbnail || `https://i.ytimg.com/vi/${v.video_id}/mqdefault.jpg`;
  img.alt = '';
  return img;
}

// Built with el()/textContent, never innerHTML: the text is server `detail`,
// and one future detail quoting a YouTube title would otherwise be XSS from a
// video someone else uploaded (YTDL-35, 2026-08-11).
//
// `action` is {label, run} and is how a dead end becomes something the editor
// can act on -- the no-companion path offers [ COPY PATH ] rather than only
// naming a folder they would have to retype. Absent (every other caller) the
// toast is exactly the one div it has always been.
function toast(text, bad, ms = 7000, action) {
  const t = $('#toast');
  t.textContent = '';
  t.appendChild(el('div', bad ? 'bad' : null, String(text)));
  if (action) {
    const b = el('button', 'text-btn', action.label);
    b.onclick = action.run;
    t.appendChild(b);
  }
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
  setBanner('session', 'your dashboard session has expired. Sign in to the '
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
  // The phase-1 flag (docs/YTDL_LOCAL_DOWNLOAD.md §10). Read strictly: a server
  // that predates the field, a flag that is off, and a health fetch that failed
  // outright all leave this page dispatching nothing and badging nothing, which
  // is the rollback story -- flag off is byte-for-byte the old page.
  state.localDownload = h.local_download === true;
  // The switch follows the flag, on every health tick and not just at boot:
  // loadHealth is re-asked on an interval so an admin who turns the feature on
  // does not have to walk the fleet asking for reloads (YTDL-39), and the
  // control that feature owns should appear on the same terms.
  initLocalSwitch();
  const pip = $('#health');
  const claudeOk = h.claude === 'ok';
  // The AI backend is chosen by the dashboard's Settings -> AI providers page
  // now (2026-08-18), so the pip names the one in force rather than always
  // saying "claude" -- an admin who pinned DeepSeek and reads "claude ok" has
  // been told nothing. A server too old to send `ai_provider` (or a call that
  // has not resolved one yet) falls back to the old word.
  const aiName = PROVIDER_NAMES[h.ai_provider] || 'claude';
  pip.textContent = `${aiName} ${h.claude}` + (h.yt_dlp === 'ok' ? '' : ' · yt-dlp missing');
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
    // Names the provider the failure came from: with five possible
    // backends, "Claude Code failed" over an Anthropic-API "credit balance is
    // too low" sent the owner looking at the wrong provider (2026-08-18).
    setBanner('health', `${aiName} failed on the server`
              + (h.claude_detail ? `: ${h.claude_detail}` : '')
              + '. Searches will fail until it works. An admin can change the '
              + 'provider or its credential on the dashboard: Settings > AI providers.', true);
  } else if (h.yt_dlp !== 'ok') {
    setBanner('health', 'yt-dlp is not installed in this container, so searching '
              + 'and downloading will both fail. See ytdl/web/DEPLOY.md.', true);
  } else {
    setBanner('health', null);
  }
  // Its own slot, because the poll response reports it too (YTDL-39).
  setBanner('worker', h.worker_alive === false ? WORKER_DEAD : null, true);
}

// ---------------------------------------------------------------- projects

function loadProject() {
  // localStorage throws outright in some privacy modes, and a page that cannot
  // remember where the last download went must still be able to search.
  try { return localStorage.getItem(PROJECT_KEY); }
  catch { return null; /* unreadable or absent: whatever the list starts on */ }
}

function saveProject() {
  try { localStorage.setItem(PROJECT_KEY, $('#project').value); }
  catch { /* it still applies to this search, just not the next visit */ }
}

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
    // BOTH submit buttons: the destination picker is shared, so with no
    // project neither a search nor a paste has anywhere to land.
    $('#go').disabled = true;
    $('#golinks').disabled = true;
    return;
  }
  setBanner('projects', null);
  $('#go').disabled = false;
  $('#golinks').disabled = false;
  r.projects.forEach(p => {
    const o = el('option', null, p.label);
    o.value = p.slug;
    sel.appendChild(o);
  });
  // After the options exist, and only for a slug the server still offers: a
  // project this editor has since unticked is no longer in the list, and
  // assigning a <select> a value none of its options carry selects NOTHING in
  // some browsers -- which would hand runSearch an empty `$('#project').value`
  // and refuse every search. An unknown slug falls back in silence to the
  // first option, which is what the page did before 2026-08-14.
  const saved = loadProject();
  if (r.projects.some(p => p.slug === saved)) sel.value = saved;
  sel.onchange = saveProject;
}

// ------------------------------------------------------------- shot types
// Per-search, not per-fleet: what the two Claude passes look for. The ticks
// are the editor's, remembered here and posted with the job; the SERVER stores
// them on the job row and composes the prompts, so this file knows the names
// and nothing about what they mean.

const searchModeOf = key =>
  SEARCH_MODES.find(m => m.key === key) || SEARCH_MODES[0];

// The ticks a mode starts from, and what an unvisited mode is ticked to. The
// visuals preset and the `on` flags in the table above are the same six keys:
// both mirror the server (its MODES presets and its SHOT_TYPES defaults), and
// test_static_app.py compares each of them against it rather than against
// each other.
const presetShots = mode => searchModeOf(mode).preset.slice();

// The ticks are remembered PER MODE: the boxes mean different things in a
// b-roll search and a news montage, so an editor who tunes one must not come
// back to find the other re-tuned. `visuals` deliberately keeps the original
// key, so the ticks every editor already has survive this build.
const shotsKeyFor = mode => (mode === DEFAULT_MODE ? SHOTS_KEY
                                                   : `${SHOTS_KEY}.${mode}`);

// In TABLE order, always -- so two editors who ticked the same boxes post the
// same list and an old localStorage value cannot smuggle in a key this build
// dropped (the server would refuse the whole job over it).
const shotKeys = () => SHOT_TYPES.filter(s => state.shots.has(s.key)).map(s => s.key);

function loadShots(mode) {
  // localStorage throws outright in some privacy modes, so a page that cannot
  // remember the ticks still has to be able to search.
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(shotsKeyFor(mode))); }
  catch { /* unreadable or absent: fall back to this mode's preset */ }
  if (!Array.isArray(saved)) return presetShots(mode);
  return SHOT_TYPES.filter(s => saved.includes(s.key)).map(s => s.key);
}

function saveShots() {
  try {
    localStorage.setItem(shotsKeyFor(state.searchMode),
                         JSON.stringify(shotKeys()));
  } catch { /* the choice still applies to this search, just not the next visit */ }
}

// ------------------------------------------------------------ search mode
// The toggle left of the boxes. It picks which rubric the SERVER composes for
// both AI passes; this file knows the two names, the two presets and nothing
// about what they mean.

function loadSearchMode() {
  let saved = null;
  try { saved = localStorage.getItem(MODE_KEY); }
  catch { /* unreadable or absent: the default */ }
  // Validated against THIS build's list, never trusted: the server refuses a
  // mode it does not know, so a stale value would 400 every search.
  return SEARCH_MODES.some(m => m.key === saved) ? saved : DEFAULT_MODE;
}

function saveSearchMode() {
  try { localStorage.setItem(MODE_KEY, state.searchMode); }
  catch { /* it still applies to this search, just not the next visit */ }
}

// Choosing a mode applies ITS preset to the boxes -- but only the first time,
// because the ticks are then remembered per mode: coming back to a mode
// restores what the editor left it on, not the preset. Re-choosing the mode
// you are already in does nothing at all, so a second click can never throw a
// selection away.
function setSearchMode(key) {
  const mode = searchModeOf(key).key;
  if (mode === state.searchMode) return;
  state.searchMode = mode;
  saveSearchMode();
  state.shots = new Set(loadShots(mode));
  renderSearchModes();
  renderShots();
}

function renderSearchModes() {
  const box = $('#modes');
  box.textContent = '';
  SEARCH_MODES.forEach(m => {
    const on = state.searchMode === m.key;
    // A real <button> with aria-pressed, like the panel headers are real
    // buttons: this is a control, and it is the first thing on the row.
    const b = el('button', 'modebtn' + (on ? ' on' : ''), `[ ${m.label} ]`);
    b.type = 'button';
    b.title = m.hint;
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    b.onclick = () => setSearchMode(m.key);
    box.appendChild(b);
  });
}

// What a job WAS run under, for the job header, the review header and Recent
// searches. An absent or unknown value is a row from before the column existed
// (or a server that predates it): say nothing rather than claim a rubric it
// never ran under.
function searchModeSummary(mode) {
  const m = SEARCH_MODES.find(x => x.key === mode);
  return m ? m.short : '';
}

// All ticked and none ticked are the same instruction to the server -- no bias
// at all -- and an editor who has just cleared every box deserves to be told
// that rather than left expecting a filter that is not running.
function renderShotNote() {
  const n = state.shots.size;
  $('#shotnote').textContent =
    n === 0 ? 'nothing ticked: no bias, claude searches and filters on the topic alone'
    : n === SHOT_TYPES.length ? 'everything ticked: no bias, claude searches and filters on the topic alone'
    : '';
}

function renderShots() {
  const box = $('#shots');
  box.textContent = '';
  let group = null;
  SHOT_TYPES.forEach(s => {
    if (s.group !== group) {
      group = s.group;
      box.appendChild(el('span', 'shothead',
                         group === 'footage' ? 'shots of it:' : 'also keep:'));
    }
    const lab = el('label', 'shot' + (state.shots.has(s.key) ? ' on' : ''));
    const pick = el('input', 'shotbox');
    pick.type = 'checkbox';
    pick.value = s.key;
    pick.checked = state.shots.has(s.key);
    // Only this label is touched, never a re-render: replacing the input the
    // editor just clicked would take the focus ring with it.
    pick.onchange = () => {
      if (pick.checked) state.shots.add(s.key); else state.shots.delete(s.key);
      lab.classList.toggle('on', pick.checked);
      saveShots();
      renderShotNote();
    };
    lab.appendChild(pick);
    lab.appendChild(el('span', null, s.label));
    box.appendChild(lab);
  });
  renderShotNote();
}

// What a job WAS run with, for the manifest header and Recent searches. An
// absent list is a job row from before the column existed (or a server that
// predates it): say nothing rather than claim a selection it never had.
function shotSummary(list, long) {
  if (!Array.isArray(list)) return '';
  if (!list.length || list.length === SHOT_TYPES.length) return 'no shot-type filter';
  const picked = SHOT_TYPES.filter(s => list.includes(s.key));
  return picked.map(s => long ? s.label : s.short).join(long ? ' · ' : '+');
}

// ---------------------------------------------------------- candidate cap
// The other per-search dial: how far the search is allowed to go before it
// stops collecting. The SERVER enforces it where candidates accumulate; this
// file only picks the number and remembers it.

function loadCap() {
  let saved = null;
  // localStorage throws outright in some privacy modes, and a page that cannot
  // remember the number must still be able to search.
  try { saved = Number(localStorage.getItem(CAP_KEY)); }
  catch { /* unreadable or absent: the default */ }
  // Validated against THIS build's list, never trusted: the server refuses a
  // number it does not know, so a stale value would 400 every search.
  return CANDIDATE_CAPS.includes(saved) ? saved : DEFAULT_CAP;
}

function saveCap() {
  try { localStorage.setItem(CAP_KEY, String(capValue())); }
  catch { /* it still applies to this search, just not the next visit */ }
}

// Always one of CANDIDATE_CAPS, whatever the DOM holds.
function capValue() {
  const n = Number($('#maxcand').value);
  return CANDIDATE_CAPS.includes(n) ? n : DEFAULT_CAP;
}

function renderCaps() {
  const sel = $('#maxcand');
  sel.innerHTML = '';
  CANDIDATE_CAPS.forEach(n => {
    const o = el('option', null, `${n} candidates`);
    o.value = String(n);
    sel.appendChild(o);
  });
  sel.value = String(loadCap());
  sel.onchange = saveCap;
}

// What a job WAS run with, for the manifest header and Recent searches. An
// absent number is a job row (or a server) from before the column existed:
// say nothing rather than claim a ceiling it never had.
function capSummary(n) {
  return CANDIDATE_CAPS.includes(Number(n)) ? `up to ${Number(n)} candidates` : '';
}

// ------------------------------------------------------ collapsible panels
// "there should be a way to collapse the search results that are open"
// (owner, 2026-08-11). A real search lands ~74 cards in the review grid, and
// everything stacked under it -- Recent searches, the download history -- is
// then off the bottom of the screen. So every bulky panel collapses, and its
// HEADER keeps the count: a collapsed panel still says "74 clips · 61
// selected" or "3/7 downloaded", because collapsing hides bulk, not meaning.
//
// `body` is the one element that disappears; anything that must survive a
// collapse (the phase, the counters, the summary spans) lives in the header
// beside the toggle. Each toggle is a real <button id="<id>toggle"> in the
// markup -- keyboard-reachable and announced -- not a div with an onclick.
const PANELS = [
  {id: 'review', title: 'REVIEW', body: 'reviewbody'},
  {id: 'downloads', title: 'DOWNLOADS', body: 'dllist'},
  {id: 'recent', title: 'RECENT SEARCHES', body: 'recentlist'},
  {id: 'history', title: 'DOWNLOAD HISTORY', body: 'historybody'},
];
// One key holding the collapsed ids, remembered exactly as the shot ticks and
// the candidate cap are (SHOTS_KEY / CAP_KEY): an editor who folds the history
// away has folded it away, not folded it away until they next open the page.
const COLLAPSE_KEY = 'ytdl.collapsed';

function loadCollapsed() {
  // localStorage throws outright in some privacy modes, and a page that cannot
  // remember which panels were folded must still show all of them.
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(COLLAPSE_KEY)); }
  catch { /* unreadable, absent or not JSON: everything starts open */ }
  if (!Array.isArray(saved)) return [];
  // Validated against THIS build's panels, in table order: an id a later build
  // renamed would otherwise sit in the set forever, hiding nothing and coming
  // back on every save.
  return PANELS.filter(p => saved.includes(p.id)).map(p => p.id);
}

function saveCollapsed() {
  try {
    localStorage.setItem(COLLAPSE_KEY, JSON.stringify(
      PANELS.filter(p => state.collapsed.has(p.id)).map(p => p.id)));
  } catch { /* it still applies to this visit, just not the next */ }
}

// The caret, the announced state and the body, all from the one Set -- so the
// markup's own [-] is never more than the pre-JS fallback.
function applyPanel(p) {
  const on = state.collapsed.has(p.id);
  $('#' + p.body).classList.toggle('hidden', on);
  const btn = $('#' + p.id + 'toggle');
  btn.textContent = (on ? '[+] ' : '[-] ') + p.title;
  btn.setAttribute('aria-expanded', on ? 'false' : 'true');
}

function togglePanel(id) {
  const p = PANELS.find(x => x.id === id);
  if (!p) return;
  if (!state.collapsed.delete(id)) state.collapsed.add(id);
  saveCollapsed();
  applyPanel(p);
}

// The one exception to "a collapse is the editor's". A job that has just
// ARRIVED at ready_for_review has clips waiting to be picked, and a review
// panel folded away an hour ago would make the new search look like it did
// nothing -- which is exactly the "nothing is visible for review" this page
// caused once already (2026-08-11). The stored state goes with it, so the
// panel does not silently re-collapse on the next visit.
//
// Deliberately driven by the phase TRANSITION and not by the phase (poll()
// keeps `state.phase`): attaching to a job that was already at
// ready_for_review -- a deep link, a 409 re-attach, a reload -- has not newly
// reached anything, so a collapse the editor made after this stays made.
function forceExpandReview() {
  if (!state.collapsed.has('review')) return;
  state.collapsed.delete('review');
  saveCollapsed();
  applyPanel(PANELS.find(p => p.id === 'review'));
}

function initPanels() {
  state.collapsed = new Set(loadCollapsed());
  PANELS.forEach(p => {
    $('#' + p.id + 'toggle').onclick = () => togglePanel(p.id);
    applyPanel(p);
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
  state.phase = null;                 // job B's phases are not job A's
  // The hand-back link is one-shot per attachment, not per page: job B may be
  // local when job A was already handed back (docs/YTDL_LOCAL_DOWNLOAD.md §9).
  $('#dlserver').disabled = false;
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
  // A job that has just ARRIVED at review must be shown even if the panel was
  // folded away -- and only on the arrival, so a collapse made afterwards
  // stands (see forceExpandReview). Read before anything awaits again, since
  // the manifest fetch below is where a second tick could overtake it.
  const seen = state.phase;
  state.phase = job.phase;
  if (job.phase === 'ready_for_review' && seen && seen !== 'ready_for_review') {
    forceExpandReview();
  }
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
    if (job.phase === 'done' || job.phase === 'cancelled') {
      loadRecent();
      // The clips this job landed are ledger rows now, and the panel that
      // lists them is on the same screen -- from the top, because they are the
      // newest rows there are.
      loadHistory();
    }
    return;
  }
  schedulePoll();
}

function detach() {
  stopPolling();
  state.attachToken++;                // orphan any poll response still in flight
  state.jobId = null;
  state.manifest = null;
  state.phase = null;
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
  // FIRST, and before any counter: which rubric this search is running under
  // is the thing that explains everything the phases below are doing. A url
  // job is never searched, so it has none to name.
  const mode = job.kind === 'urls' ? '' : searchModeSummary(job.mode);
  if (mode) bits.push('mode: ' + mode);
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

// How much of ONE video the live map says is on disk. Anything missing (before
// the first progress_hook fires) or outside 0-100 counts as nothing rather than
// dragging the bar backwards.
const livePct = p => (p && p.percent != null
  ? Math.min(100, Math.max(0, Number(p.percent) || 0)) / 100 : 0);

function renderDownloads(job, r) {
  const total = job.dl_total || 0;
  const done = (job.dl_done || 0) + (job.dl_failed || 0);
  const live = r.progress || {};
  // Every queued video gets a row -- pending, in flight, done, failed (with
  // its reason), skipped -- not just the ones currently moving. The manifest
  // is re-fetched each tick while downloading, so dl_state is current; the
  // live map overrides it for the file yt-dlp is actually writing.
  const vids = ((state.manifest && state.manifest.videos) || [])
    .filter(v => v.dl_state && v.dl_state !== 'none');

  // The bar counted WHOLE videos (dl_done + dl_failed), so a one-video job --
  // which is every pasted link -- sat at 0% for the entire download and read
  // as hung (2026-08-11). The in-flight fraction is the same live map the rows
  // below print, folded into the same bar.
  //
  // Only videos the manifest still calls 'downloading' may be added: a live
  // entry lingers at percent 100 / status 'merging' AFTER dl_done has counted
  // that video, so summing the map blindly double-counts and overshoots.
  const inflight = vids.length
    ? vids.reduce((a, v) => a + (v.dl_state === 'downloading'
                                 ? livePct(live[v.video_id]) : 0), 0)
    // No manifest yet (a refresh mid-download): the live map is all there is,
    // and only its 'downloading' entries can still be uncounted by dl_done.
    : Object.keys(live).reduce((a, k) => a + (live[k] && live[k].status === 'downloading'
                                              ? livePct(live[k]) : 0), 0);
  // Rounded because (1 + 0.2) * 100 / 2 is 60.000000000000007 in floating
  // point, and that string goes straight into a style attribute.
  const pct = total
    ? Math.round(Math.min(100, (done + inflight) * 100 / total) * 10) / 10 : 0;
  $('#dlfill').style.width = pct + '%';
  $('#dlfill').classList.toggle('done', job.phase === 'done');
  $('#dlphase').textContent = PHASE_LABEL[job.phase] || job.phase;
  $('#dlticker').textContent =
    `${job.dl_done || 0}/${total} downloaded` + (job.dl_failed ? ` · ${job.dl_failed} failed` : '');
  $('#cancel2').classList.toggle('hidden', !!job.terminal);
  // WHOSE machine is fetching these clips, off this tick's payload (§9).
  renderMode(job);

  const list = $('#dllist');
  list.innerHTML = '';
  if (!vids.length) {
    // A refresh mid-download, before the first manifest fetch lands: show
    // what the live map knows rather than nothing.
    Object.keys(live).forEach(vid => {
      const p = live[vid];
      const row = el('div', 'dlrow');
      // The id is all this branch has, and it is all the fallback URL needs.
      row.appendChild(thumb({video_id: vid}, 'dlthumb'));
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
    row.appendChild(thumb(v, 'dlthumb'));
    row.appendChild(el('span', 'name', v.title || v.video_id));
    let st;
    if (p && p.status === 'downloading') {
      st = `${p.percent == null ? '…' : p.percent + '%'} ${p.speed || ''}`;
    } else if (p && p.status && v.dl_state === 'downloading') {
      st = p.status;                     // 'merging', 'converting to H.264...'
    } else if (v.dl_state === 'failed') {
      st = 'failed: ' + (v.dl_error || 'see the server log');
    } else if (v.dl_state === 'skipped') {
      st = 'already downloaded';
    } else if (v.dl_state === 'done' && v.dl_error) {
      // A note on a DONE row is the quality downgrade the worker had to make
      // (SAQBbd1Rxmo, 2026-08-13: YouTube served f137 truncated from two IPs
      // and only the 720p rung would come down). The clip is here; nothing
      // else in the UI would ever say it is not the rung that was asked for.
      st = 'done: ' + v.dl_error;
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
  // A url job has no manifest to review: its videos are exactly the links the
  // editor pasted and they are already downloading. The rows are still needed
  // (renderDownloads reads state.manifest), but the grid would offer a
  // selection nobody is being asked to make, over cards with no metadata.
  if (m.job.kind === 'urls') return;
  $('#review').classList.remove('hidden');
  renderTerms();
  renderGrid();
}

function renderTerms() {
  // The ticks and the ceiling this search actually ran with -- not the ones in
  // the header, which are whatever the editor has since changed them to.
  const mode = searchModeSummary(state.manifest.job.mode);
  const shots = shotSummary(state.manifest.job.shot_types, true);
  const cap = capSummary(state.manifest.job.max_candidates);
  $('#jobshots').textContent =
    [mode ? 'mode: ' + mode : '', shots ? 'shot types: ' + shots : '', cap]
      .filter(Boolean).join(' · ');

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
      c.appendChild(el('span', 'gloss', '(' + t.english_gloss + ')'));
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
      ? `all ${held} filtered out: [ SHOW FILTERED OUT ] to see them`
      : 'nothing found for this term'));
  }

  const sel = m.videos.filter(v => v.selected && !v.duplicate);
  const secs = sel.reduce((a, v) => a + (v.duration || 0), 0);
  // Count AND total duration: the only disk-space proxy an editor has, and the
  // destination is the Projects pool that ops watches.
  $('#gridfoot').textContent =
    `${sel.length} selected · ${fmtTotal(secs)} of footage · into ${m.job.project_label}\\Youtube\\${m.job.term_dir}`;
  // The same two numbers in the panel HEADER, which survives a collapse: what
  // is in there and how much of it is picked is the whole reason to unfold it
  // again (2026-08-11).
  $('#reviewsum').textContent =
    `${plural(vis.length, 'clip', 'clips')} · ${sel.length} selected`;
  $('#download').textContent = `DOWNLOAD ${sel.length}`;
  // `done` as well as `ready_for_review` (CR-35, 2026-08-19). start_download
  // has accepted both since YTDL-16 -- pressing DOWNLOAD on a finished job is
  // the documented way to fetch the clips that failed, and mark_pending re-
  // queues exactly the rows that failed or were never fetched -- but this line
  // did not, so the button died the moment the first download finished. The
  // editor's only route to a SECOND clip out of a grid of 67 was another whole
  // search: another Claude spend, another twenty minutes of yt-dlp (an editor,
  // 2026-08-19). The 400 for "nothing new is selected" and the 409 for "you
  // already have a job running" are the server's to give, and both already
  // arrive as a toast; a permanently grey button is not a better error message.
  $('#download').disabled =
    !sel.length || !['ready_for_review', 'done'].includes(m.job.phase);
}

function card(v) {
  const filteredOut = !v.relevant || v.meta_error;
  const n = el('div', 'card'
    + (v.selected && !v.duplicate ? ' on' : '')
    + (v.duplicate ? ' dup' : '')
    + (filteredOut ? ' filtered' : ''));

  // The same picture, and the same id-only fallback, as a download row -- see
  // thumb() up in the helpers.
  n.appendChild(thumb(v, 'thumb'));

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
      // Which rubric both AI passes run under. Always sent; the server
      // refuses a mode it does not know rather than reading it as the
      // default, so this must never send anything but a key from the table.
      mode: state.searchMode,
      // Always sent, even when it is every box or none: the server tells an
      // omitted field (an old client, which gets the defaults) apart from an
      // empty one (this editor asked for no bias).
      shot_types: shotKeys(),
      // Always one of CANDIDATE_CAPS; the server refuses anything else rather
      // than clamping it, so this must never send the raw DOM value.
      max_candidates: capValue(),
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
      // Loud, red and specific: a quiet amber "showing it below" over a
      // four-day-old review read as "SEARCH does nothing" (owner, 2026-08-18).
      toast(`A previous search is still open below (job #${e.info.job_id}). ` +
            `Finish its review or press CANCEL on it, then search again. ` +
            `(${e.message})`, true, 15000);
      $('#progress').classList.remove('hidden');
      await attach(e.info.job_id);
    } else {
      toast(e.message, true, 12000);
    }
  } finally {
    go.disabled = false;
  }
}

// The second box: "download exactly these". Deliberately NOT folded into
// runSearch -- the endpoint, the validation and the disabled-button guard are
// per-button, and one shared submitter would either disable the wrong button
// or need a flag argument for every difference. Everything AFTER the POST is
// shared: detach/attach, the banner slots, the 409 re-attach (YTDL-8).
async function runUrls() {
  const btn = $('#golinks');
  if (btn.disabled) return;           // no project, or a POST already in flight
  const urls = $('#urls').value.trim();
  if (!urls) return;
  const slug = $('#project').value;
  if (!slug) { toast('pick a project first', true); return; }
  btn.disabled = true;
  try {
    // The links and the shared destination pickers, and nothing else: a paste
    // has the same destination choice a search has, which is the project
    // (owner's call, 2026-08-11), and its clips land in that project's Youtube
    // root because there is no term to sort individual downloads by.
    const r = await post('api/jobs/urls', {
      urls, project_slug: slug,
      quality: $('#quality').value,
    });
    // GET LINKS offers the job to this editor's machine too (CR-36,
    // 2026-08-19). It never did: dispatchLocal lived only in startDownload,
    // the review-grid path, so EVERY pasted link this fleet has ever fetched
    // downloaded on the NAS -- and since 2026-08-16 no lane brings a YouTube
    // original back down, so the editor who pasted the link was the one person
    // guaranteed not to end up with the clip. A paste has no review step, so
    // this is the only place the offer can be made.
    //
    // Same contract as startDownload's: not awaited, the server has already
    // accepted the job, and a companion that cannot take it changes nothing.
    dispatchLocal(r.job_id, $('#quality').value);
    detach();
    $('#progress').classList.remove('hidden');
    await attach(r.job_id);
    if (r.skipped && r.skipped.length) {
      // Never silently: a link that fetches nothing because the fleet already
      // has it is the answer to "why did I only get two of my four".
      toast(`${r.queued} queued · ${r.skipped.length} already in the tree`,
            false, 12000);
    }
  } catch (e) {
    if (e.status === 409 && e.info && e.info.job_id) {
      toast(`${e.message}, showing it below`, false, 12000);
      $('#progress').classList.remove('hidden');
      await attach(e.info.job_id);
    } else {
      toast(e.message, true, 12000);
    }
  } finally {
    btn.disabled = false;
  }
}

async function startDownload() {
  const jobId = state.jobId;
  try {
    await post(`api/jobs/${jobId}/download`);
    // Only after the SERVER has accepted the selection: the job is downloading
    // either way from here, and offering it to this editor's own machine is a
    // shortcut on top of that, never a precondition for it
    // (docs/YTDL_LOCAL_DOWNLOAD.md §2, step 1). Deliberately not awaited -- the
    // probe below is allowed a whole second to time out and the review panel
    // must not sit there for it.
    //
    // The quality is the JOB's, off the manifest this page is reviewing -- not
    // the header's picker, which is whatever the editor has since changed it
    // to. It is the one thing the dispatcher may decide with, because a
    // companion that does not run this rung would take the lease and hand it
    // straight back (COMP-BROLL-10); the work order itself still comes from
    // the server (§8).
    dispatchLocal(jobId, state.manifest && state.manifest.job
      ? state.manifest.job.quality : null);
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
    // The old copy said "it stops after the video in flight" for EVERY phase.
    // On a job parked in ready_for_review nothing is in flight and nothing ever
    // will be, so it read as a cancel that had not worked and the editor was
    // left blocked by their own job (owner hit this on job 42, 2026-08-19).
    // The phase is on screen already, so say the one thing that differs.
    toast(state.phase === 'downloading'
      ? 'cancelling: it stops after the video in flight'
      : 'cancelled');
  } catch (e) {
    toast(e.message, true);
  }
}

// ------------------------------------------------ requester-first downloads
// docs/YTDL_LOCAL_DOWNLOAD.md §2: a job's clips can be fetched by the machine
// that ASKED for them instead of by the NAS. YouTube is hostile to one static
// IP making bulk anonymous requests (2026-08-13: five clips refused outright),
// and a clip born on the requester's machine is theirs immediately rather than
// after a NAS download plus a sync hop down.
//
// The browser is the only party that can see both the dashboard and the
// editor's own loopback, so it is the dispatcher -- and what it dispatches is a
// JOB ID and nothing else. The urls, the quality, the destination and the
// naming template all reach the companion from the SERVER over its own
// token-authed channel; this is the music-send rule ("never trust the page with
// a path") extended to never trusting it with the work order either (§2, §8).
//
// EVERY failure below is silent and lands on the server worker downloading
// exactly as it does today (§11): no companion, a companion too old for these
// routes, a browser blocking local connections, a stale yt-dlp, a claim that
// lost the race to another tab. This is a fast path, not a feature an editor
// has to watch fail -- the clips arrive either way and the only visible
// difference is the badge in the downloads header (§9).

// One second, then the FIRST probe is abandoned. It sits between the editor
// clicking DOWNLOAD and the page showing them the job, so nothing listening on
// 8899 must never cost more than that.
const PROBE_MS = 1000;

// ...but a companion that IS there and merely busy gets a second, longer go
// (2026-08-19). Measured on a live editor machine: /ytdl/capabilities answers
// in 3-6 ms warm and 3.9 s while the companion is mid-sync-pass -- a request
// that does no I/O still waits behind whatever else holds the interpreter. With
// one 1 s attempt that machine silently downloaded on the server EVERY time:
// 45 jobs out of 45 across the whole fleet, which read as "requester-first
// downloads don't work" rather than as a timeout. Retried ONLY on a timeout,
// never on a refusal, so a machine with no tray app still fails in milliseconds.
// Costs the editor nothing visible either way: startDownload never awaits this,
// and a late claim is the handover the lease design is already built around.
const PROBE_RETRY_MS = 5000;

// The one companion refusal the editor can fix (the YouTube terms in the tray)
// is said once; everything else in the fast path stays silent (see §11 and
// test_the_probe_is_bounded_and_every_failure_of_it_is_silent).
let lastCompanionRefusal = "";
function explainCompanionRefusal(reason) {
  if (reason === lastCompanionRefusal) return;
  lastCompanionRefusal = reason;
  toast("Please first accept the download terms in the companion: right-click the " +
        "tray icon, then 'Accept YouTube Terms'. This download runs on the server instead.",
        true, 12000);
}

// The editor's own switch (2026-08-19, the owner: "we need a switch for
// download locally and we need an error and some feedback for when it doesn't
// do it"). Remembered per browser, defaulting to ON: requester-first is what
// puts an editor's clips on their own disk, and since 2026-08-16 no lane
// brings a YouTube original back down from the NAS.
//
// It is a PREFERENCE, not a promise. Unticked means "do not even ask this
// machine"; ticked means "ask, and tell me what the answer was" -- which is
// the part that was missing. The server still decides, and every refusal path
// below now ends at a sentence rather than at silence.
const LOCAL_KEY = 'ytdl.local';

function localWanted() {
  if (!state.localDownload) return false;      // the fleet flag is off
  const box = $('#localdl');
  // `!== false` and not a truthiness test: an absent element, or one served by
  // a cached index.html from before this switch existed, must behave the way
  // the page did WITHOUT the switch -- which is "offer it to this machine".
  // Reading `undefined` as "unticked" would have turned a stale asset into a
  // silent, fleet-wide opt-out of the whole feature.
  return !box || box.checked !== false;
}

function initLocalSwitch() {
  const label = $('#locallabel');
  const box = $('#localdl');
  if (!label || !box) return;
  // Hidden entirely when the fleet flag is off: a switch for a feature the
  // server will not honour is worse than no switch (§10, phase 1).
  label.classList.toggle('hidden', !state.localDownload);
  try {
    const saved = localStorage.getItem(LOCAL_KEY);
    if (saved !== null) box.checked = saved === '1';
  } catch { /* privacy mode: the default (on) applies to this visit */ }
  box.onchange = () => {
    try { localStorage.setItem(LOCAL_KEY, box.checked ? '1' : '0'); }
    catch { /* it still applies to this download */ }
    toast(box.checked
      ? 'downloads will be offered to this machine first'
      : 'downloads will run on the server. YouTube originals only sync '
        + 'upwards, so you can fetch one later from the download history.');
  };
}

// Why this machine is not doing the download, said ONCE per reason. §11 used
// to keep every machine-side refusal quiet on the grounds that the editor
// could not act on it and the server would do the job anyway. That was wrong
// in the one way that mattered: the clips then live on the NAS and no lane
// brings them down, so "the server did it" is not a detail, it is the whole
// outcome (the owner, 2026-08-19).
let lastLocalNote = '';
function noteLocalSkipped(why) {
  if (why === lastLocalNote) return;
  lastLocalNote = why;
  toast(`Downloading on the server: ${why}. YouTube originals only sync `
        + 'upwards, so use the download history to fetch a clip onto this '
        + 'machine.', false, 12000);
}

// Is there a companion on this machine willing to do the work? 200 with
// ok:false is a companion saying WHY not (no yt-dlp, disk nearly full, an older
// naming template than the server's -- §5/§6); it is a no, like every other
// answer that is not a yes.
async function companionCapabilities() {
  let body = null;
  // Told apart so the sentence at the bottom can be the true one: a refused
  // connection is "no tray app", an abort is "it never answered".
  let unreachable = false;
  for (const budget of [PROBE_MS, PROBE_RETRY_MS]) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), budget);
    let timedOut = false;
    try {
      const res = await fetch(`${COMPANION_URL}/ytdl/capabilities`, {signal: ctl.signal});
      if (!res.ok) {                       // 404: a companion predating 0.8.0
        noteLocalSkipped('the CC Sync companion on this machine is too old to '
                         + 'download YouTube clips (upgrade it from the tray)');
        return null;
      }
      body = await res.json();
    } catch (e) {
      // Nothing listening, the abort above, or Chrome's local-network
      // permission refusing a plain-HTTP origin. Only the abort is worth a
      // second go: the other two answer instantly and would answer the same.
      timedOut = !!(e && e.name === 'AbortError');
      unreachable = !timedOut;
    } finally {
      clearTimeout(timer);
    }
    if (body || !timedOut) break;
  }
  if (body && body.ok === true) return body;
  // Every refusal now ENDS AT A SENTENCE. §11 used to keep machine-side ones
  // quiet -- an old yt-dlp, no ffmpeg -- on the grounds that the editor could
  // not act on them and the server would do the job anyway. Since 2026-08-16
  // "the server did it" means the clip stays on the NAS, so that reasoning
  // stopped holding and the owner asked for the feedback out loud
  // (2026-08-19). The terms refusal keeps its own louder toast: it is the one
  // an editor fixes in the tray in ten seconds.
  if (body && /terms/i.test(String(body.reason || ""))) {
    explainCompanionRefusal(String(body.reason));
  } else if (body) {
    noteLocalSkipped(String(body.reason || 'this machine declined the job'));
  } else if (unreachable) {
    noteLocalSkipped('the CC Sync companion is not answering on this machine '
                     + '(is the tray app running? self-test: open '
                     + 'http://127.0.0.1:8899/status)');
  } else {
    noteLocalSkipped('the CC Sync companion did not answer in time');
  }
  return null;
}

// One DISPATCH per submission: no polling of the loopback and no second
// handover attempt. A companion that was not there when the editor clicked
// DOWNLOAD is not going to be handed a job that the server has already
// started, and a retry loop against a machine that is asleep would be a
// background fetch nobody ever sees fail. (companionCapabilities does retry a
// probe that TIMED OUT -- see PROBE_RETRY_MS -- which is the opposite case: a
// companion that is there and answering, just not within a second.)
async function dispatchLocal(jobId, quality) {
  if (!jobId) return false;
  // The editor's switch is read HERE, at the moment of dispatch, rather than
  // remembered from page load: unticking it mid-session has to take effect on
  // the next download and not the next reload. Unticked is a deliberate
  // choice, so it says nothing -- noteLocalSkipped is for the times the page
  // TRIED and could not.
  if (!localWanted()) return false;
  const cap = await companionCapabilities();
  if (!cap) return false;
  // The rungs that companion actually runs (COMP-BROLL-10). The server refuses
  // an out-of-scope claim too, and would be right to -- but a claim refused is
  // still a round trip and a log line for a job this page already knew was not
  // theirs. A companion that does not declare the field, or a quality this page
  // does not know, dispatches exactly as before.
  if (Array.isArray(cap.scope_qualities) && quality
      && !cap.scope_qualities.includes(quality)) {
    noteLocalSkipped(`this machine only downloads `
      + `${cap.scope_qualities.join(', ')} and this job is ${quality}`);
    return false;
  }
  try {
    const res = await fetch(`${COMPANION_URL}/ytdl/download`, {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      // The whole work order. Anything else here would be the page telling the
      // companion what to download, which is the thing §8 forbids.
      body: JSON.stringify({job_id: jobId}),
    });
    // 202 dispatched; 409 already busy, 503 declined (its claim was refused, or
    // the capability went away between the probe and now) -- and any of those
    // simply means the server worker keeps the job, which it has all along.
    if (res.status === 202) return true;
    noteLocalSkipped(res.status === 409
      ? 'this machine is already downloading another job'
      : `this machine declined the job (HTTP ${res.status})`);
    return false;
  } catch {
    noteLocalSkipped('the CC Sync companion stopped answering between the '
                     + 'check and the hand-off');
    return false;
  }
}

// §9: the executor, named. A silent swap between machines is how editors
// conclude a feature is broken (the 2026-08-11 hash-pinning lesson), so this is
// derived from the poll payload on EVERY tick and remembered nowhere -- when a
// lease expires and the server reclaims the job (§3), the badge flips on its
// own within a poll and the hand-back link disappears with it.
function renderMode(job) {
  const badge = $('#dlmode');
  const btn = $('#dlserver');
  // Flag off, or a server that predates the field: no badge and no link, i.e.
  // the header this page has always had (§10, phase 1).
  const mode = state.localDownload ? job.download_mode : null;
  const live = job.phase === 'downloading';
  badge.textContent = mode === 'local' ? 'downloading on your machine'
    : mode === 'server' ? 'downloading on the server' : '';
  // Which editor holds the lease, for the case the answer is surprising -- a
  // title rather than a line, because for a local job it is always this editor.
  badge.title = job.claimed_by ? `claimed by ${job.claimed_by}` : '';
  badge.classList.toggle('local', mode === 'local');
  badge.classList.toggle('hidden', !live || !badge.textContent);
  // Only while THIS machine holds it: handing back a job the server is already
  // doing is a no-op with a confusing button attached.
  btn.classList.toggle('hidden', !live || mode !== 'local');
}

// "download on the server instead" (§9): the escape hatch for an editor who is
// tethered, on hotel wifi, or about to close the laptop. Per-job on purpose --
// there is no global toggle, because a per-job link is self-documenting and
// cannot be left on by accident. The server flips the mode and reclaims; this
// page changes nothing itself and finds out from the next poll, exactly as it
// finds out about a reclaim it did not ask for.
async function lockToServer() {
  const btn = $('#dlserver');
  if (btn.disabled || !state.jobId) return;   // one-shot: a second click is the
  btn.disabled = true;                        // same request, not a second one
  try {
    await post(`api/jobs/${state.jobId}/mode-lock`, {mode: 'server'});
    toast('handing this job back to the server: it picks up whatever your '
          + 'machine has not finished');
  } catch (e) {
    // A deliberate human action, unlike the dispatch above: this one says so
    // when it fails, and comes back so a blip is not a dead end.
    toast(e.message, true, 12000);
    btn.disabled = false;
  }
}

async function loadRecent() {
  let r;
  try {
    r = await api('api/jobs?limit=15');
  } catch { return; }
  const box = $('#recentlist');
  box.innerHTML = '';
  // In the header, so a folded-away panel still says whether there is anything
  // in it.
  $('#recentsum').textContent =
    r.jobs.length ? plural(r.jobs.length, 'search', 'searches') : 'nothing yet';
  if (!r.jobs.length) { box.textContent = 'nothing yet'; return; }
  r.jobs.forEach(j => {
    const row = el('div', 'recentrow');
    row.appendChild(el('span', 'when', (j.created_at || '').slice(0, 16).replace('T', ' ')));
    row.appendChild(el('span', 'ph', j.phase));
    // A search has a topic; a paste has neither a topic nor a folder any more
    // (its clips go straight into the project's Youtube root), so naming its
    // empty `term` would print a dangling arrow.
    row.appendChild(el('span', 'name', j.kind === 'urls'
      ? `links → ${j.project_label}\\Youtube`
      : `${j.term} → ${j.project_label}`));
    // A paste is never searched or filtered, so it has neither a mode, shot
    // types nor a candidate ceiling to show -- its videos are the links that
    // were pasted.
    const mode = j.kind === 'urls' ? '' : searchModeSummary(j.mode);
    if (mode) row.appendChild(el('span', 'modesum', mode));
    const shots = j.kind === 'urls' ? '' : shotSummary(j.shot_types);
    if (shots) row.appendChild(el('span', 'shotsum', shots));
    const cap = j.kind === 'urls' ? '' : capSummary(j.max_candidates);
    if (cap) row.appendChild(el('span', 'capsum', `max ${Number(j.max_candidates)}`));
    row.onclick = () => attach(j.id);
    box.appendChild(row);
  });
}

// --------------------------------------------------------- download history
// The permanent ledger, newest first, fleet-wide -- the same rows the ALREADY
// IN badge is built from, so the panel and the badge cannot disagree about
// where a clip is. Paged, because the ledger outlives every job in it and
// nothing ever prunes it.

async function loadHistory(more) {
  const box = $('#historylist');
  const offset = more ? state.historyOffset : 0;
  let r;
  try {
    r = await api(`api/downloads?limit=${HISTORY_PAGE}&offset=${offset}`);
  } catch (e) {
    // Never fatal and never a toast: this panel is history, and the page's job
    // is the search above it.
    if (!more) { box.textContent = ''; box.appendChild(el('div', 'muted', 'could not load the download history')); }
    return;
  }
  // Never trusted to be a list: this panel is the bottom of the page, and a
  // server that answered something unexpected must cost the history and not
  // the search above it.
  const items = (r && r.downloads) || [];
  if (!more) { box.innerHTML = ''; state.historyOffset = 0; }
  // The ledger's own size, in the panel HEADER rather than in the list: it is
  // the one number that has to survive this panel being folded away.
  $('#historysum').textContent = r.total ? plural(r.total, 'clip', 'clips') : 'nothing yet';
  if (!items.length && !state.historyOffset) {
    box.textContent = 'nothing downloaded yet';
    $('#historymore').classList.add('hidden');
    $('#historynote').textContent = '';
    return;
  }
  items.forEach(d => box.appendChild(historyRow(d)));
  state.historyOffset = offset + items.length;
  $('#historymore').classList.toggle('hidden', !r.has_more);
  $('#historynote').textContent =
    `showing ${state.historyOffset} of ${r.total}. Click a clip to open its folder`;
}

function historyRow(d) {
  const row = el('div', 'histrow');
  // The ledger row carries the video id, so the id-only ytimg fallback always
  // has a picture even for a clip whose title arrived from a pasted link and
  // whose `thumbnail` was never fetched.
  row.appendChild(thumb(d, 'histthumb'));

  const meta = el('div', 'histmeta');
  // textContent, always: a title is a string YouTube gave us, i.e. a string
  // somebody else chose (YTDL-35's rule, applied to the ledger).
  meta.appendChild(el('div', 'name', d.title || d.video_id));
  // The destination as it exists on disk, for both shapes: a search's clip is
  // in Youtube\<term>, a pasted one is in Youtube itself. `folder_path` is
  // derived server-side from the stored rel_path, so this line cannot invent a
  // folder that is not there.
  meta.appendChild(el('div', 'sub',
    [`${d.project_label}\\${winPath(d.folder_path || 'Youtube')}`,
     d.channel || '', d.downloaded_by || ''].filter(Boolean).join(' · ')));
  row.appendChild(meta);

  row.appendChild(el('span', 'when',
    (d.downloaded_at || '').slice(0, 16).replace('T', ' ')));

  if (d.reveal_path) {
    row.title = 'open this clip\'s folder on this machine';
    row.onclick = () => reveal(d);
  } else {
    // A row from a build that recorded no path (YTDL-15's shape). Shown, never
    // clickable: there is no folder to name.
    row.classList.add('nopath');
  }
  return row;
}

// Open the containing folder ON THE EDITOR'S MACHINE. A browser cannot, so it
// goes through the companion's loopback server exactly as b-roll's "Send to
// Resolve" does -- and the body is a path relative to the PROJECTS ROOT, never
// an absolute one: this page is served from the NAS and only the companion
// knows the tree is at P:\Projects there (or /Volumes/<SSD>/... on a Mac).
//
// DEGRADES, never errors. No companion, a companion too old to know the route,
// or a Mac build that has not shipped yet all end at the same place: say where
// the clip is and offer to copy the path, which is what the editor was going to
// do with the folder anyway.
async function reveal(d) {
  let res;
  try {
    res = await fetch(`${COMPANION_URL}/ytdl/reveal`, {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify({rel_path: d.reveal_path}),
    });
  } catch {
    // A rejected fetch also happens when the browser blocks a plain-HTTP
    // dashboard origin from reaching 127.0.0.1 (Chrome's local-network
    // permission) with a perfectly healthy companion behind it (2026-08-12).
    noCompanion(d, 'couldn’t reach the CC Sync companion: it may not be '
                + 'running, or the browser blocked local connections (self-test: '
                + 'open http://127.0.0.1:8899/status)');
    return;
  }
  if (res.status === 404) {
    // The tray app is there but predates this route: an upgrade, not a bug.
    noCompanion(d, 'your companion is too old to open folders; it will be able '
                + 'to after the next upgrade');
    return;
  }
  let body = null;
  try { body = await res.json(); } catch { /* not JSON; status is all we have */ }
  // `absent` is the companion saying "the NAS has this clip and I do not"
  // (CR-32). It rides on BOTH answers: ok:false when there was nothing to open
  // at all, and ok:true when the folder opened but the clip was not in it. Both
  // are the same dead end for the editor, and both are now offerable.
  if (body && body.absent) {
    offerFetch(d, (body && body.message) || 'that clip is not on this machine');
    return;
  }
  if (!res.ok || !body || body.ok === false) {
    const message = (body && (body.message || body.error))
      || `the companion answered HTTP ${res.status}`;
    noCompanion(d, message);
    return;
  }
  toast((body && body.message) || 'opened the folder on this machine');
}

// ------------------------------------------------- getting a clip off the NAS
//
// CR-32 (2026-08-19). A job that ran on the SERVER leaves its originals on the
// NAS, and lane B has not carried the Youtube tree down since 2026-08-16 -- so
// until this button there was no route at all by which the editor who asked for
// the clip could end up holding it. Measured on one live job: 2 clips on the
// editor's disk, 20 on the NAS. (Written without a leading slash on purpose:
// test_mounted_prefix scans the shipped bytes, comments included, and a
// root-relative-looking token is exactly what it is there to catch.)
//
// Offered at the moment the editor hits the wall rather than as a permanent
// button on every row: the page cannot know which clips are local, and a
// [ GET ] beside a clip that is already here is a button that does nothing.

const FETCH_POLL_MS = 1500;

function offerFetch(d, why) {
  toast(`${why}`, false, 20000,
        {label: '[ GET IT FROM THE NAS ]', run: () => runFetch(d)});
}

async function runFetch(d) {
  let res;
  try {
    res = await fetch(`${COMPANION_URL}/ytdl/fetch`, {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify({rel_path: d.reveal_path}),
    });
  } catch {
    noCompanion(d, 'couldn’t reach the CC Sync companion to fetch that clip');
    return;
  }
  if (res.status === 404) {
    // The route landed in 0.9.4. An older tray app is an upgrade away from
    // this working, which is a different sentence from "it is broken".
    noCompanion(d, 'your companion is too old to fetch clips from the NAS; it '
                + 'will be able to after the next upgrade');
    return;
  }
  let body = null;
  try { body = await res.json(); } catch { /* status is all we have */ }
  if (!res.ok || !body) {
    noCompanion(d, `the companion answered HTTP ${res.status}`);
    return;
  }
  if (body.state === 'downloading') {
    // One poll chain per click, and the companion's own registry is what stops
    // two of them becoming two rclones: jobs are keyed by destination, so a
    // second click joins the first download instead of racing it.
    toast(fetchLine(d, body), false, FETCH_POLL_MS * 2);
    setTimeout(() => runFetch(d), FETCH_POLL_MS);
    return;
  }
  if (body.ok) {
    // Here now. Open the folder, which is what the original click was for.
    toast(body.message || 'the clip is on this machine now');
    reveal(d);
    return;
  }
  noCompanion(d, body.message || 'the download failed');
}

// The progress line, degrading to a bare "downloading" whenever the companion
// sends no numbers (the first poll, always) rather than showing "NaN%".
function fetchLine(d, body) {
  const p = body.progress || {};
  const name = winPath(d.reveal_path).split('\\').pop();
  // `percent` is present only once rclone has reported a total (broll_fetch's
  // FetchJob.progress computes it there and nowhere else), so its absence is
  // the ordinary first-poll state, not an error.
  return Number.isFinite(p.percent)
    ? `getting ${name} from the NAS - ${p.percent}%`
    : `getting ${name} from the NAS...`;
}

// The dead end, made useful. The FOLDER, not the file -- opening it is what
// the click was for -- and no drive letter, because this page genuinely does
// not know one (P: on Windows, /Volumes/<SSD> on a Mac). Named AND copyable:
// retyping a project label with three slashes in it out of a toast is not a
// fallback anybody uses.
function noCompanion(d, why) {
  const folder = 'Projects\\' + winParent(winPath(d.reveal_path));
  toast(`${why}. The clip is in ${folder} on your sync drive (P: on Windows)`,
        false, 15000,
        {label: '[ COPY PATH ]', run: () => copyText(folder)});
}

// Best effort by design: clipboard access is permissioned, absent on old
// browsers and refused outright in some privacy modes, and the path is already
// on screen in the toast either way.
function copyText(text) {
  try {
    const clip = typeof navigator !== 'undefined' && navigator.clipboard;
    if (!clip) { toast('copy it from the line above', true); return; }
    Promise.resolve(clip.writeText(text))
      .then(() => toast('path copied'))
      .catch(() => toast('copy it from the line above', true));
  } catch {
    toast('copy it from the line above', true);
  }
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
// -------------------------------------------------- the rights attestation
// COMMERCIAL_READINESS.md item 2 (2026-08-17). The server owns the wording and
// the record; this renders both, and disables the two GO buttons until the
// current wording is accepted. The buttons are disabled rather than hidden:
// an editor who has used this page for months must see that the thing they
// know is still there and why it is not clickable.

async function loadAttestation() {
  let info;
  try {
    info = await api('api/attestation');
  } catch {
    // An old server without the route, or a blip. Leave the page as it was:
    // the SERVER is the gate, so a page that cannot ask is a page whose
    // searches will simply be refused with the reason attached.
    return;
  }
  $('#legalcopyright').textContent = info.copyright_notice || '';
  $('#legalrate').textContent = info.rate_disclaimer || '';
  $('#attesttitle').textContent = info.title || 'Before you download';
  $('#attesttext').textContent = info.text || '';
  state.attestVersion = info.version || '';
  setAttested(!!info.accepted);
}

function setAttested(accepted) {
  state.attested = accepted;
  $('#attest').classList.toggle('hidden', accepted);
  for (const id of ['#go', '#golinks', '#download']) {
    const el = document.querySelector(id);
    if (el) {
      el.disabled = !accepted;
      el.title = accepted ? el.dataset.title || el.title
                          : 'Accept the download terms at the top of this page first';
    }
  }
}

async function acceptAttestation() {
  try {
    const info = await post('api/attestation', {version: state.attestVersion});
    setAttested(!!info.accepted);
    toast('Recorded. Thank you.');
  } catch (e) {
    // A 409 means the wording changed while this page was open; reloading is
    // the only honest fix, because accepting text that is no longer current
    // would record agreement to something nobody displayed.
    toast(e.message);
    if (e.status === 409) location.reload();
  }
}

async function init() {
  loadDashboardTopbar();
  // Before anything is awaited: the boxes are part of the SEARCH form and must
  // be on screen (and ticked as this editor left them) from the first paint.
  state.searchMode = loadSearchMode();
  state.shots = new Set(loadShots(state.searchMode));
  renderSearchModes();
  renderShots();
  renderCaps();
  // Also before anything is awaited: a panel this editor folded away must not
  // flash open for the length of a fetch on every visit.
  initPanels();
  $('#go').onclick = runSearch;
  $('#q').addEventListener('keydown', e => { if (e.key === 'Enter') runSearch(); });
  $('#golinks').onclick = runUrls;
  // Ctrl/Cmd+Enter, not Enter: the links box is a textarea and Enter is how a
  // second link gets onto its own line.
  $('#urls').addEventListener('keydown', e => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) runUrls();
  });
  $('#cancel').onclick = cancelJob;
  $('#cancel2').onclick = cancelJob;
  $('#dlserver').onclick = lockToServer;
  $('#selall').onclick = () => bulk(true);
  $('#selnone').onclick = () => bulk(false);
  $('#download').onclick = startDownload;
  // renderTerms too: the chip counts are counts of what the grid shows.
  $('#showfiltered').onclick = () => {
    state.showFiltered = !state.showFiltered;
    renderTerms();
    renderGrid();
  };
  $('#historymore').onclick = () => loadHistory(true);

  $('#attestaccept').onclick = acceptAttestation;
  // AWAITED, and before the job is attached: everything the search form can do
  // is refused by the server without this, so the notice has to be on screen
  // before an editor types into a box that is about to 403.
  await loadAttestation();

  await loadProjects();
  loadHealth();
  // Re-asked on a slow interval so an admin who fixes claude (or restarts the
  // worker) does not have to walk the fleet asking for reloads (YTDL-39).
  setInterval(loadHealth, HEALTH_INTERVAL);
  loadRecent();
  loadHistory();

  await openingJob();
}

// What this page shows on load, in precedence order (2026-08-11, found live:
// a finished paste job pinned in the hash while a `ready_for_review` job with
// 74 relevant clips sat unshown, and the editor concluded the feature was
// broken):
//
//   1. an ACTIVE job always wins, and the hash is rewritten to match. The
//      editor's one non-terminal job is the one thing on the server that is
//      either moving or waiting for them -- and `ready_for_review` counts as
//      active (db.active_job), which is precisely the case that hurts: it
//      blocks every new search with a 409 (YTDL-25) while the page shows
//      something else and nothing on screen says why.
//   2. otherwise a `#job=` hash is honoured even though it is terminal. Those
//      deep links are what the Recent searches list writes, and a finished
//      job's manifest is a thing people come back to.
//   3. nothing either way: nothing is attached, as before.
//
// The active job is ASKED FOR rather than inferred from the recent list: one
// row, in SQL, from the same db.active_job the 409 path uses -- inferring it
// here would be a second definition of "active" to keep in step.
async function openingJob() {
  const m = /job=(\d+)/.exec(location.hash || '');
  let active = null;
  try {
    active = (await api('api/jobs/active')).job;
  } catch {
    // An old server (no such route) or a blip. The hash is still better than
    // nothing, so this must not stop rule 2.
  }
  const id = (active && active.id) || (m ? Number(m[1]) : null);
  if (!id) return;
  $('#progress').classList.remove('hidden');
  await attach(id);          // attach() writes location.hash, so the URL agrees
}

init().catch(e => {
  document.querySelector('#recentlist').textContent = 'failed to load: ' + e.message;
});
