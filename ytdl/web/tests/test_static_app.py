"""The SPA's own behaviour, exercised rather than eyeballed.

`static/app.js` is where the 2026-08-11 hunt found its frontend cluster
(YTDL-8/9/10/11/12/25/33/34/35/36/37/38/39) and nothing in this suite touched
it: the other test files talk to the API, and test_mounted_prefix.py greps the
asset bytes. Both are blind to "a stale poll response killed the new job's
timer".

So this file runs the real app.js, unmodified, inside a `node --experimental`-
free `vm` context with a ~150-line DOM/fetch/timer shim (below, written to
tmp_path so nothing lands in the tree). The timers are FAKE and the fetches are
scripted, which is what makes the races deterministic: "job A's terminal
response lands after job C attached" is a scenario here, not a Tuesday.

**node is not a dependency of this app** -- the container has deno for yt-dlp
and nothing else -- so every harness test SKIPS when node is missing, and the
plain source assertions at the bottom always run. If you are looking at a skip
report and wondering: install node, or trust the source checks.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / 'static'
APP_JS = STATIC / 'app.js'
NODE = shutil.which('node')


# --------------------------------------------------------------- the harness
# One string, deliberately: this file owns it, it is an input to a subprocess
# rather than source of the app, and a second checked-in .mjs would be one more
# thing to keep in step with app.js.
HARNESS = r"""
'use strict';
const fs = require('node:fs');
const vm = require('node:vm');

const APP = fs.readFileSync(process.argv[2], 'utf8');
const INDEX = fs.readFileSync(process.argv[3], 'utf8');
const tick = () => new Promise(r => setImmediate(r));
const flush = async (n = 30) => { for (let i = 0; i < n; i++) await tick(); };

// The classes each id CARRIES IN THE MARKUP -- read out of index.html rather
// than listed here, because "starts hidden" is the whole assertion in half the
// scenarios and a shim that invented its own initial state would pass tests
// the browser fails.
const INITIAL = (() => {
  const out = {};
  for (const m of INDEX.matchAll(/<[a-z0-9]+\s[^>]*>/gi)) {
    const id = /\bid="([^"]+)"/.exec(m[0]);
    const cls = /\bclass="([^"]+)"/.exec(m[0]);
    if (id) out[id[1]] = cls ? cls[1] : '';
  }
  return out;
})();

// ---- the smallest DOM that app.js actually uses -------------------------
class N {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.className = '';
    this._text = ''; this.style = {}; this.disabled = false; this.value = '';
    this.onclick = null; this._listeners = {}; this.attrs = {};
  }
  // Only the collapsible panel headers use these (aria-expanded), and they are
  // half of what makes a header a CONTROL rather than a div: a scenario has to
  // be able to read what a screen reader would be told.
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  get classList() {
    const self = this;
    const parts = () => self.className.split(' ').filter(Boolean);
    return {
      add(c) { const p = parts(); if (!p.includes(c)) p.push(c); self.className = p.join(' '); },
      remove(c) { self.className = parts().filter(x => x !== c).join(' '); },
      toggle(c, on) { const has = parts().includes(c); const want = on === undefined ? !has : !!on;
                      want ? this.add(c) : this.remove(c); },
      contains(c) { return parts().includes(c); },
    };
  }
  appendChild(c) { this.children.push(c); return c; }
  addEventListener(ev, fn) { (this._listeners[ev] = this._listeners[ev] || []).push(fn); }
  set textContent(v) { this._text = String(v); this.children = []; }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  set innerHTML(v) { this._text = String(v); this.children = []; }
  get innerHTML() { return this._text; }
  get hidden() { return this.classList.contains('hidden'); }
  // Everything the app inserted, flattened -- how a test counts cards/banners.
  descendants() { return this.children.flatMap(c => [c, ...c.descendants()]); }
  byClass(c) { return this.descendants().filter(n => (' ' + n.className + ' ').includes(' ' + c + ' ')); }
}

function makeContext(handler, seed, hash) {
  const els = new Map();
  const get = id => {
    if (!els.has(id)) {
      const n = new N('div');
      n.className = INITIAL[id] === undefined ? '' : INITIAL[id];
      els.set(id, n);
    }
    return els.get(id);
  };
  const document = {
    createElement: tag => new N(tag),
    querySelector: sel => get(sel.replace('#', '')),
    getElementById: id => get(id),
  };
  const timers = {
    next: 1, pending: new Map(), intervals: 0,
    set(fn, ms) { const id = this.next++; this.pending.set(id, {fn, ms}); return id; },
    clear(id) { this.pending.delete(id); },
    async fire() {
      const due = [...this.pending.values()];
      this.pending.clear();
      for (const t of due) await t.fn();
      await flush();
    },
  };
  const calls = [];
  const fetchStub = async (url, opts) => {
    const method = (opts && opts.method) || 'GET';
    const body = opts && opts.body ? JSON.parse(opts.body) : null;
    calls.push({method, url, body});
    // A real fetch REJECTS when its signal aborts, and the companion probe's
    // whole point is that a hung loopback costs one second and then nothing
    // (docs/YTDL_LOCAL_DOWNLOAD.md §2). A handler that never settles + the fake
    // 1 s timer is how a scenario spells "the companion did not answer".
    let onAbort = null;
    const aborted = new Promise((_, rej) => {
      onAbort = () => rej(Object.assign(new Error('aborted'), {name: 'AbortError'}));
    });
    aborted.catch(() => {});     // the abort may land after the race settled;
    const signal = opts && opts.signal;   // an unhandled rejection kills node
    if (signal) signal.addEventListener('abort', onAbort);
    const res = signal ? await Promise.race([handler(method, url, body), aborted])
                       : await handler(method, url, body);
    const status = res.status === undefined ? 200 : res.status;
    return {
      ok: status >= 200 && status < 300,
      status,
      redirected: !!res.redirected,
      json: async () => res.json === undefined ? {} : res.json,
      text: async () => res.text === undefined ? '' : res.text,
    };
  };
  // Enough localStorage for the shot-type ticks. Seedable, because "the boxes
  // this editor left ticked last week come back" is the whole feature and a
  // fresh sandbox has nothing in it.
  const store = Object.assign({}, seed || {});
  const localStorage = {
    getItem: k => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: k => { delete store[k]; },
  };
  // The no-companion fallback offers to copy the path. Permissioned and absent
  // in older browsers, so app.js guards it -- but the harness needs a real one
  // to prove the offer actually copies something.
  const copied = [];
  const navigator = {clipboard: {writeText: async t => { copied.push(String(t)); }}};
  const ctx = {
    // `hash` is seedable because "the page was opened on #job=4" is the whole
    // premise of the opening-job scenarios.
    document, location: {hash: hash || ''}, console, localStorage, navigator,
    fetch: fetchStub,
    // node's own, not a shim: the companion probe builds one per call and the
    // 1 s bound is the only thing standing between a hung tray app and an
    // editor watching a review panel that will not go away.
    AbortController,
    setTimeout: (fn, ms) => timers.set(fn, ms),
    clearTimeout: id => timers.clear(id),
    setInterval: (fn, ms) => { timers.intervals++; return -1; },
    clearInterval: () => {},
  };
  vm.createContext(ctx);
  return {ctx, els, get, timers, calls, store, copied};
}

async function boot(handler, seed, hash) {
  const h = makeContext(handler, seed, hash);
  vm.runInContext(APP, h.ctx, {filename: 'app.js'});
  // Top-level const/let are lexical, not properties of the sandbox, so they
  // have to be re-exported. One at a time and forgivingly, so this harness can
  // also be pointed at an OLDER app.js (how the scenarios below were checked
  // to fail before the fix) without dying on the first renamed symbol.
  vm.runInContext(
    'globalThis.__ = {};'
    + '["state","banners","poll","attach","detach","runSearch","runUrls",'
    + '"toggle","bulk","loadHealth","loadProjects","loadManifest","loadRecent",'
    + '"renderProgress","renderTerms","renderGrid","toast","setBanner",'
    + '"visibleVideos","SHOT_TYPES","shotKeys","shotSummary","renderShots",'
    + '"startDownload","dispatchLocal","lockToServer","renderMode",'
    + '"SEARCH_MODES","setSearchMode","searchModeSummary",'
    + '"SEARCH_SCOPES","setTermScope","termScopeSummary","dateSummary"]'
    + '.forEach(k => { try { globalThis.__[k] = eval(k); } catch (e) {} });', h.ctx);
  await flush();
  h.app = h.ctx.__;
  // "Is the poll loop armed" -- specifically the poll's own timer, since the
  // toast's auto-hide is a pending timer too.
  h.polling = () => {
    const id = h.ctx.__.state.pollTimer;
    return id !== null && id !== undefined && h.timers.pending.has(id);
  };
  h.banners = () => h.ctx.__.banners
    ? [...h.ctx.__.banners.entries()].map(([k, v]) => [k, v.text, v.bad]) : [];
  h.warnLines = () => h.get('warn').children.map(c => c.textContent);
  // Everything on screen in the banner area, however it is structured -- so
  // the "does this warning survive?" scenarios measure the bug and not the
  // markup (they must fail against the pre-fix single-element app.js too).
  h.warnText = () => h.get('warn').hidden ? '' : h.get('warn').textContent;
  return h;
}

// ---- canned server shapes ----------------------------------------------
const JOB = (over = {}) => Object.assign({
  id: 1, phase: 'searching', terminal: false, error: null,
  terms_total: 3, terms_done: 1, enrich_total: 0, enrich_done: 0,
  candidates: 0, dl_total: 0, dl_done: 0, dl_failed: 0,
  project_label: '2026/FF5/Energy', term_dir: 'algal reef',
}, over);
const POLLRES = (job, over = {}) => Object.assign({
  job, terms: [], counts: {relevant: 0, duplicates: 0, irrelevant: 0},
  progress: {}, worker_alive: true,
}, over);
const MANIFEST = (over = {}) => Object.assign({
  job: JOB({phase: 'ready_for_review', terminal: false}),
  videos: [], terms: [], counts: {relevant: 0, duplicates: 0, irrelevant: 0},
}, over);
const VIDEO = (id, over = {}) => Object.assign({
  video_id: id, title: id + ' title', url: 'https://youtu.be/' + id,
  channel: 'ch', duration: 60, upload_date: '20260801', thumbnail: null,
  relevant: 1, meta_error: null, duplicate: 0, selected: 0, term_ids: [1],
  dl_state: 'none',
}, over);

// One ledger row as /api/downloads serves it.
const DL = (id, over = {}) => Object.assign({
  video_id: id, title: id + ' title', channel: 'Test Channel',
  project_slug: 's', project_label: '2026/FF5/Energy', term: 'algal reef',
  term_dir: 'algal reef', folder: 'algal reef',
  folder_path: 'Youtube/algal reef',
  rel_path: `Youtube/algal reef/Channel [${id}].mp4`,
  reveal_path: `2026/FF5/Energy/Youtube/algal reef/Channel [${id}].mp4`,
  thumbnail: null, job_id: 1, downloaded_by: 'owen',
  downloaded_at: '2026-08-11T09:30:00+00:00',
}, over);

// health/projects/topbar/active/history answers every scenario needs before it
// gets going. The last two are asked for on EVERY page load now, so a scenario
// about anything else must not have to script them.
function baseline(method, url) {
  if (url.startsWith('api/health')) {
    return {json: {claude: 'ok', claude_detail: '', yt_dlp: 'ok',
                   worker_alive: true, cookies: false}};
  }
  if (url.startsWith('api/projects')) {
    return {json: {projects: [{slug: 's', label: '2026/FF5/Energy'}],
                   projects_available: true, error: null}};
  }
  if (url === 'api/jobs/active') return {json: {job: null}};
  if (url.startsWith('api/downloads')) {
    return {json: {downloads: [], total: 0, limit: 24, offset: 0, has_more: false}};
  }
  if (url.startsWith('api/jobs?')) return {json: {jobs: []}};
  if (url.includes('partials/topbar')) return {status: 404};
  return null;
}

// ---- scenarios ----------------------------------------------------------
const scenarios = {};

// YTDL-8: a refused SEARCH must not tear down the job it was refused against.
scenarios['refused_search_reattaches'] = async () => {
  const h = await boot(async (method, url, body) => {
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === 'api/jobs') {
      return {status: 409, json: {detail: {detail: 'you already have a job in progress',
                                           job_id: 77, phase: 'ready_for_review'}}};
    }
    if (url === 'api/jobs/77') return {json: POLLRES(JOB({id: 77, phase: 'searching'}))};
    return {json: {}};
  });
  h.get('q').value = 'reef';
  h.get('project').value = 's';
  await h.app.runSearch();
  await flush();
  return {job_id: h.app.state.jobId,
          progress_hidden: h.get('progress').hidden,
          toast: h.get('toast').textContent,
          go_disabled: h.get('go').disabled};
};

// YTDL-8b: a plain failure leaves the job that IS attached alone.
scenarios['failed_search_keeps_the_live_job'] = async () => {
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === 'api/jobs') {
      return {status: 400, json: {detail: 'unknown quality'}};
    }
    if (url.startsWith('api/jobs/5/manifest')) return {json: MANIFEST()};
    if (url === 'api/jobs/5') return {json: POLLRES(JOB({id: 5, phase: 'enriching'}))};
    return {json: {}};
  });
  await h.app.attach(5);
  await flush();
  h.get('q').value = 'reef';
  h.get('project').value = 's';
  await h.app.runSearch();
  await flush();
  return {job_id: h.app.state.jobId,
          progress_hidden: h.get('progress').hidden,
          polling: h.polling()};
};

// YTDL-25 (frontend half): #go is disabled while the POST is in flight, and
// the Enter-key path respects it.
scenarios['go_is_disabled_while_posting'] = async () => {
  let release, seen = [];
  const gate = new Promise(r => { release = r; });
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === 'api/jobs') { await gate; return {json: {job_id: 9}}; }
    if (url === 'api/jobs/9') return {json: POLLRES(JOB({id: 9}))};
    return {json: {}};
  });
  h.get('q').value = 'reef';
  h.get('project').value = 's';
  const p = h.app.runSearch();
  await flush();
  const during = h.get('go').disabled;
  const p2 = h.app.runSearch();     // the double-click / second Enter
  await flush();
  seen = h.calls.filter(c => c.method === 'POST' && c.url === 'api/jobs').length;
  release();
  await Promise.all([p, p2]);       // not awaited before release: the second
  await flush();                    // POST would be waiting on the same gate
  return {disabled_during: during, posts: seen, disabled_after: h.get('go').disabled};
};

// YTDL-9: job A's late TERMINAL response must not kill job C's loop.
scenarios['stale_terminal_response_cannot_kill_the_new_loop'] = async () => {
  let release;
  const gate = new Promise(r => { release = r; });
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (url === 'api/jobs/1') { await gate; return {json: POLLRES(JOB({id: 1, phase: 'done', terminal: true, dl_total: 0}))}; }
    if (url.startsWith('api/jobs/1/manifest')) return {json: MANIFEST({videos: [VIDEO('AAAAAAAAAAA')]})};
    if (url === 'api/jobs/3') return {json: POLLRES(JOB({id: 3, phase: 'searching'}))};
    if (url.startsWith('api/jobs/3/manifest')) return {json: MANIFEST({videos: []})};
    return {json: {}};
  });
  const slow = h.app.attach(1);       // deliberately not awaited: it is in flight
  await flush();
  await h.app.attach(3);              // the editor's next SEARCH landed
  await flush();
  const armed = h.polling();
  release();
  await slow;
  await flush();
  return {job_id: h.app.state.jobId,
          armed_before: armed,
          still_polling: h.polling(),
          manifest_videos: (h.app.state.manifest || {videos: []}).videos.length,
          review_hidden: h.get('review').hidden};
};

// YTDL-10: a 401 stops the loop and says so.
scenarios['session_expiry_stops_the_poll'] = async () => {
  let n = 0;
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (url === 'api/jobs/4') {
      n++;
      if (n === 1) return {json: POLLRES(JOB({id: 4, phase: 'downloading', dl_total: 3, dl_done: 1}))};
      return {status: 401, json: {detail: 'not signed in'}};
    }
    if (url.startsWith('api/jobs/4/manifest')) return {json: MANIFEST({videos: []})};
    return {json: {}};
  });
  await h.app.attach(4);
  await flush();
  await h.timers.fire();              // the tick that 401s
  return {polling: h.polling(), banners: h.banners(), text: h.warnText()};
};

// YTDL-34: a blip on the TERMINAL manifest fetch retries instead of leaving a
// full bar and no grid.
scenarios['terminal_manifest_blip_retries'] = async () => {
  let manifests = 0;
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (url === 'api/jobs/6') return {json: POLLRES(JOB({id: 6, phase: 'ready_for_review'}))};
    if (url.startsWith('api/jobs/6/manifest')) {
      manifests++;
      if (manifests === 1) return {status: 503, json: {detail: 'gateway'}};
      return {json: MANIFEST({videos: [VIDEO('BBBBBBBBBBB')]})};
    }
    return {json: {}};
  });
  await h.app.attach(6);
  await flush();
  const retrying = h.polling();
  await h.timers.fire();
  return {retrying, review_hidden: h.get('review').hidden,
          cards: h.get('grid').byClass('card').length, manifests};
};

// YTDL-11/37: timeout warns, and the health all-clear does not erase the
// projects warning.
scenarios['banner_slots_are_independent'] = async () => {
  const h = await boot(async (method, url) => {
    if (url.startsWith('api/health')) {
      return {json: {claude: 'timeout', claude_detail: 'x', yt_dlp: 'ok',
                     worker_alive: true, cookies: false}};
    }
    if (url.startsWith('api/projects')) {
      return {json: {projects: [], projects_available: true, error: null}};
    }
    const b = baseline(method, url); if (b) return b;
    return {json: {}};
  });
  await flush();
  return {banners: h.banners(), warns: h.warnLines(), text: h.warnText(),
          go_disabled: h.get('go').disabled};
};

// YTDL-12: the failed job's banner does not survive into the next job.
scenarios['job_error_banner_is_cleared_by_the_next_job'] = async () => {
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (url === 'api/jobs/10') return {json: POLLRES(JOB({id: 10, phase: 'failed', terminal: true, error: 'claude_timeout: no answer'}))};
    if (url === 'api/jobs/11') return {json: POLLRES(JOB({id: 11, phase: 'searching'}))};
    if (url.startsWith('api/jobs/11/manifest')) return {json: MANIFEST({videos: []})};
    return {json: {}};
  });
  await h.app.attach(10);
  await flush();
  const after_failure = h.warnText();
  await h.app.attach(11);
  await flush();
  return {after_failure, after_retry: h.warnText()};
};

// YTDL-39: the dead worker is reported by every poll; the UI must read it.
scenarios['dead_worker_is_reported'] = async () => {
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (url === 'api/jobs/12') return {json: POLLRES(JOB({id: 12, phase: 'queued'}), {worker_alive: false})};
    return {json: {}};
  });
  await h.app.attach(12);
  await flush();
  return {text: h.warnText(), intervals: h.timers.intervals};
};

// YTDL-36: a cancel mid-download keeps the which-clips-landed list.
scenarios['cancelled_mid_download_keeps_the_list'] = async () => {
  const vids = [VIDEO('CCCCCCCCCCC', {dl_state: 'done', selected: 1}),
                VIDEO('DDDDDDDDDDD', {dl_state: 'pending', selected: 1})];
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (url === 'api/jobs/13') {
      return {json: POLLRES(JOB({id: 13, phase: 'cancelled', terminal: true,
                                 dl_total: 2, dl_done: 1}))};
    }
    if (url.startsWith('api/jobs/13/manifest')) return {json: MANIFEST({videos: vids})};
    return {json: {}};
  });
  await h.app.attach(13);
  await flush();
  return {downloads_hidden: h.get('downloads').hidden,
          progress_hidden: h.get('progress').hidden,
          rows: h.get('dllist').byClass('dlrow').length};
};

// YTDL-33: rapid check/uncheck -- the DB and the UI must end up agreeing.
scenarios['rapid_toggles_are_serialised'] = async () => {
  const order = [];
  const h = await boot(async (method, url, body) => {
    const b = baseline(method, url); if (b) return b;
    if (url.startsWith('api/jobs/14/manifest')) return {json: MANIFEST({videos: [VIDEO('EEEEEEEEEEE')]})};
    if (url === 'api/jobs/14') return {json: POLLRES(JOB({id: 14, phase: 'ready_for_review'}))};
    if (url.includes('/videos/') && method === 'POST') {
      order.push(body.selected);
      // The CHECK answers slower than the UNCHECK: unserialised, the check's
      // response lands last and re-ticks a card the database has as unticked.
      await flush(body.selected ? 6 : 1);
      return {json: {ok: true, selected: body.selected,
                     counts: {relevant: 1, duplicates: 0, irrelevant: 0}}};
    }
    return {json: {}};
  });
  await h.app.attach(14);
  await flush();
  const v = h.app.state.manifest.videos[0];
  const a = h.app.toggle(v, true);
  const optimistic = v.selected;       // the card follows the click at once
  const b2 = h.app.toggle(v, false);
  await Promise.all([a, b2]);
  await flush();
  return {order, optimistic, final: v.selected,
          foot: h.get('gridfoot').textContent};
};

// YTDL-38: chip counts agree with the grid, and an all-filtered term says so.
scenarios['chip_counts_match_the_grid'] = async () => {
  const vids = [VIDEO('FFFFFFFFFFF', {relevant: 1, term_ids: [1]}),
                VIDEO('GGGGGGGGGGG', {relevant: 0, term_ids: [2]}),
                VIDEO('HHHHHHHHHHH', {relevant: 0, term_ids: [2]})];
  const manifest = MANIFEST({
    videos: vids,
    terms: [{id: 1, term: 'reef', lang: 'en', english_gloss: null, source: 'user', hits: 1, videos: 1},
            {id: 2, term: 'algae', lang: 'en', english_gloss: null, source: 'claude', hits: 2, videos: 2}],
    counts: {relevant: 1, duplicates: 0, irrelevant: 2},
  });
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (url.startsWith('api/jobs/15/manifest')) return {json: manifest};
    if (url === 'api/jobs/15') return {json: POLLRES(JOB({id: 15, phase: 'ready_for_review'}))};
    return {json: {}};
  });
  await h.app.attach(15);
  await flush();
  const chipCounts = h.get('termchips').byClass('chip')
    .map(c => c.byClass('n').map(x => x.textContent).join(''));
  // now click the all-filtered term the way the chip's own handler does
  h.app.state.termFilter = 2;
  h.app.renderTerms(); h.app.renderGrid();
  return {chipCounts,
          cards_for_filtered_term: h.get('grid').byClass('card').length,
          empty_state: h.get('grid').byClass('gridempty').map(n => n.textContent)};
};

// YTDL-35: a hostile server detail reaches the toast as TEXT.
scenarios['toast_does_not_parse_html'] = async () => {
  const evil = '<img src=x onerror=alert(1)>';
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === 'api/jobs') return {status: 400, json: {detail: evil}};
    return {json: {}};
  });
  h.get('q').value = 'reef';
  h.get('project').value = 's';
  await h.app.runSearch();
  await flush();
  const t = h.get('toast');
  return {text: t.textContent, html_children: t.descendants().map(n => n.tagName),
          raw: t.innerHTML};
};

// The second box: paste links, download exactly those. Same submit shape as
// SEARCH (disable-while-in-flight, detach only after the POST is accepted,
// 409 re-attach) against a different endpoint.
scenarios['pasted_links_start_a_job'] = async () => {
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === 'api/jobs/urls') {
      return {json: {job_id: 21, phase: 'queued', term_dir: '', folder: 'Youtube',
                     queued: 1, skipped: [{video_id: 'IIIIIIIIIII',
                                           duplicate_of: '2025/FF4/Nuclear/old'}]}};
    }
    if (url === 'api/jobs/21') {
      return {json: POLLRES(JOB({id: 21, kind: 'urls', phase: 'queued'}))};
    }
    return {json: {}};
  });
  h.get('urls').value = ' https://youtu.be/JJJJJJJJJJJ \n https://youtu.be/IIIIIIIIIII ';
  h.get('project').value = 's';
  h.get('quality').value = '1080p';
  await h.app.runUrls();
  await flush();
  const post = h.calls.filter(c => c.url === 'api/jobs/urls')[0];
  return {job_id: h.app.state.jobId, body: post && post.body,
          progress_hidden: h.get('progress').hidden,
          toast: h.get('toast').textContent,
          disabled_after: h.get('golinks').disabled};
};

scenarios['links_button_is_disabled_while_posting'] = async () => {
  let release;
  const gate = new Promise(r => { release = r; });
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === 'api/jobs/urls') { await gate; return {json: {job_id: 22}}; }
    if (url === 'api/jobs/22') return {json: POLLRES(JOB({id: 22, kind: 'urls'}))};
    return {json: {}};
  });
  h.get('urls').value = 'https://youtu.be/JJJJJJJJJJJ';
  h.get('project').value = 's';
  const p = h.app.runUrls();
  await flush();
  const during = h.get('golinks').disabled;
  const p2 = h.app.runUrls();          // the double-click
  await flush();
  const posts = h.calls.filter(c => c.url === 'api/jobs/urls').length;
  release();
  await Promise.all([p, p2]);
  await flush();
  return {disabled_during: during, posts, disabled_after: h.get('golinks').disabled};
};

// YTDL-8's shape on the new button: one active job per editor, so a paste can
// be refused against a running SEARCH and must show it rather than nothing.
scenarios['refused_paste_reattaches'] = async () => {
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === 'api/jobs/urls') {
      return {status: 409, json: {detail: {detail: 'you already have a job in progress',
                                           job_id: 23, phase: 'searching'}}};
    }
    if (url === 'api/jobs/23') return {json: POLLRES(JOB({id: 23, phase: 'searching'}))};
    return {json: {}};
  });
  h.get('urls').value = 'https://youtu.be/JJJJJJJJJJJ';
  h.get('project').value = 's';
  await h.app.runUrls();
  await flush();
  return {job_id: h.app.state.jobId, progress_hidden: h.get('progress').hidden,
          toast: h.get('toast').textContent, polling: h.polling()};
};

// A url job has no manifest to review: the grid would offer a selection nobody
// is being asked for, over cards with no metadata behind them.
// The SAME finished-download shape twice, differing only in `kind` -- so the
// hidden grid is the branch doing its job and not just a section that never
// got shown (#review starts hidden in the markup).
scenarios['a_url_job_shows_downloads_not_a_review_grid'] = async () => {
  const vids = [VIDEO('JJJJJJJJJJJ', {dl_state: 'done', selected: 1, title: null}),
                VIDEO('IIIIIIIIIII', {dl_state: 'skipped', selected: 0, duplicate: 1})];
  const done = over => JOB(Object.assign(
    {phase: 'done', terminal: true, dl_total: 2, dl_done: 2, term_dir: 'reef links'},
    over));
  const jobs = {24: done({id: 24, kind: 'urls'}), 25: done({id: 25, kind: 'search'})};
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    for (const id of [24, 25]) {
      if (url === `api/jobs/${id}`) return {json: POLLRES(jobs[id])};
      if (url.startsWith(`api/jobs/${id}/manifest`)) {
        return {json: MANIFEST({job: jobs[id], videos: vids})};
      }
    }
    return {json: {}};
  });
  await h.app.attach(24);
  await flush();
  const urlJob = {review_hidden: h.get('review').hidden,
                  downloads_hidden: h.get('downloads').hidden,
                  rows: h.get('dllist').byClass('dlrow').length,
                  row_text: h.get('dllist').byClass('dlrow').map(n => n.textContent)};
  await h.app.attach(25);
  await flush();
  return Object.assign(urlJob, {search_review_hidden: h.get('review').hidden,
                                search_cards: h.get('grid').byClass('card').length});
};

// ---- the download panel -------------------------------------------------
// The bar was `(dl_done + dl_failed) / dl_total` -- WHOLE videos -- so a
// one-video job, which is every pasted link, sat at 0% for the entire download
// and read as hung (2026-08-11). The per-video percentage was already on the
// page in the row text; it just never reached the bar.

scenarios['the_bar_moves_inside_a_single_video'] = async () => {
  const vids = [VIDEO('PPPPPPPPPPP', {dl_state: 'downloading', selected: 1})];
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (url === 'api/jobs/71') {
      return {json: POLLRES(JOB({id: 71, kind: 'urls', phase: 'downloading',
                                 dl_total: 1, dl_done: 0}),
                            {progress: {PPPPPPPPPPP: {percent: 40, speed: '3.1MiB/s',
                                                      status: 'downloading'}}})};
    }
    if (url.startsWith('api/jobs/71/manifest')) return {json: MANIFEST({videos: vids})};
    return {json: {}};
  });
  await h.app.attach(71);
  await flush();
  return {width: h.get('dlfill').style.width,
          ticker: h.get('dlticker').textContent,
          rows: h.get('dllist').byClass('dlrow').map(n => n.textContent)};
};

// The trap in folding the live map in: an entry LINGERS at percent 100 /
// 'merging' after dl_done has already counted that video, so a blind sum
// double-counts it and the bar overshoots (here: 110% clamped to a full bar
// while half the job is still to download).
scenarios['a_merging_video_is_not_counted_twice'] = async () => {
  const vids = [VIDEO('QQQQQQQQQQQ', {dl_state: 'done', selected: 1}),
                VIDEO('RRRRRRRRRRR', {dl_state: 'downloading', selected: 1})];
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (url === 'api/jobs/72') {
      return {json: POLLRES(JOB({id: 72, phase: 'downloading', dl_total: 2, dl_done: 1}),
                            {progress: {QQQQQQQQQQQ: {percent: 100, speed: null,
                                                      status: 'merging'},
                                        RRRRRRRRRRR: {percent: 20, speed: '1.0MiB/s',
                                                      status: 'downloading'}}})};
    }
    if (url.startsWith('api/jobs/72/manifest')) return {json: MANIFEST({videos: vids})};
    return {json: {}};
  });
  await h.app.attach(72);
  await flush();
  return {width: h.get('dlfill').style.width,
          rows: h.get('dllist').byClass('dlrow').map(n => n.textContent)};
};

// A refresh mid-download, before the first manifest fetch lands: no dl_state to
// read, so the live map's own 'downloading' status is what separates the video
// still arriving from the one dl_done has already counted.
scenarios['the_bar_falls_back_to_the_live_map'] = async () => {
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (url === 'api/jobs/73') {
      return {json: POLLRES(JOB({id: 73, phase: 'downloading', dl_total: 2, dl_done: 1}),
                            {progress: {SSSSSSSSSSS: {percent: 100, speed: null,
                                                      status: 'merging'},
                                        TTTTTTTTTTT: {percent: 50, speed: '2.0MiB/s',
                                                      status: 'downloading'}}})};
    }
    if (url.startsWith('api/jobs/73/manifest')) return {status: 503, json: {detail: 'gateway'}};
    return {json: {}};
  });
  await h.app.attach(73);
  await flush();
  return {width: h.get('dlfill').style.width,
          manifest: h.app.state.manifest,
          rows: h.get('dllist').byClass('dlrow').map(n => n.textContent),
          thumbs: h.get('dllist').byClass('dlthumb').map(n => n.src)};
};

// Every row shows the clip, not just its title -- and the fallback URL needs
// nothing but the video id, which is the whole point: a url job never runs an
// enrich phase, so `thumbnail` is NULL for every pasted link.
scenarios['thumbnails_on_the_download_rows'] = async () => {
  const STORED = 'https://i.ytimg.com/vi/UUUUUUUUUUU/hqdefault.jpg';
  const jobs = {
    74: JOB({id: 74, kind: 'search', phase: 'downloading', dl_total: 2, dl_done: 1}),
    75: JOB({id: 75, kind: 'urls', phase: 'downloading', dl_total: 1, dl_done: 0}),
    76: JOB({id: 76, kind: 'search', phase: 'ready_for_review'}),
  };
  const vids = {
    74: [VIDEO('UUUUUUUUUUU', {dl_state: 'done', selected: 1, thumbnail: STORED}),
         VIDEO('VVVVVVVVVVV', {dl_state: 'downloading', selected: 1})],
    75: [VIDEO('WWWWWWWWWWW', {dl_state: 'downloading', selected: 1, title: null})],
    76: [VIDEO('XXXXXXXXXXX'), VIDEO('YYYYYYYYYYY', {thumbnail: STORED})],
  };
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    for (const id of [74, 75, 76]) {
      if (url === `api/jobs/${id}`) return {json: POLLRES(jobs[id])};
      if (url.startsWith(`api/jobs/${id}/manifest`)) {
        return {json: MANIFEST({job: jobs[id], videos: vids[id]})};
      }
    }
    return {json: {}};
  });
  const rowThumbs = () => h.get('dllist').byClass('dlthumb').map(n => n.src);
  await h.app.attach(74);
  await flush();
  const search_thumbs = rowThumbs();
  await h.app.attach(75);
  await flush();
  const url_thumbs = rowThumbs();
  await h.app.attach(76);
  await flush();
  return {search_thumbs, url_thumbs,
          card_thumbs: h.get('grid').byClass('thumb').map(n => n.src)};
};

// ---- the shot-type checkboxes -------------------------------------------
// "just make it a series of check boxes so the user can decide and tweak it"
// (2026-08-11). The ticks are the editor's, remembered between visits, and
// posted with the search -- the server owns what they MEAN.

const shotBoxes = h => h.get('shots').descendants().filter(n => n.tagName === 'input');
const clickShot = (h, key, on) => {
  const b = shotBoxes(h).find(x => x.value === key);
  b.checked = on;
  b.onchange();                       // what a click does; the shim fires none
};

scenarios['shot_type_boxes_post_what_is_ticked'] = async () => {
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === 'api/jobs') return {json: {job_id: 31}};
    if (url === 'api/jobs/31') return {json: POLLRES(JOB({id: 31, phase: 'queued'}))};
    return {json: {}};
  });
  const initial = shotBoxes(h).map(b => [b.value, !!b.checked]);
  clickShot(h, 'raw', false);
  clickShot(h, 'interview', true);
  h.get('q').value = 'reef';
  h.get('project').value = 's';
  await h.app.runSearch();
  await flush();
  const post = h.calls.filter(c => c.method === 'POST' && c.url === 'api/jobs')[0];
  return {initial, body: post && post.body,
          labels: h.get('shots').textContent,
          stored: h.store['ytdl.shot_types'],
          note: h.get('shotnote').textContent};
};

scenarios['shot_types_come_back_from_localstorage'] = async () => {
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === 'api/jobs') return {json: {job_id: 32}};
    if (url === 'api/jobs/32') return {json: POLLRES(JOB({id: 32}))};
    return {json: {}};
  }, {'ytdl.shot_types': JSON.stringify(['interview', 'aerial', 'klingon'])});
  const ticked = shotBoxes(h).filter(b => b.checked).map(b => b.value);
  h.get('q').value = 'reef';
  h.get('project').value = 's';
  await h.app.runSearch();
  await flush();
  const post = h.calls.filter(c => c.method === 'POST' && c.url === 'api/jobs')[0];
  return {ticked, posted: post && post.body.shot_types};
};

// All ticked and none ticked are the same instruction (no bias), and an editor
// who has just cleared every box must be told so rather than left expecting a
// filter that is not running.
scenarios['the_degenerate_selections_say_so'] = async () => {
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    return {json: {}};
  });
  const keys = h.app.SHOT_TYPES.map(s => s.key);
  keys.forEach(k => clickShot(h, k, false));
  const none = {note: h.get('shotnote').textContent, posted: h.app.shotKeys(),
                stored: h.store['ytdl.shot_types']};
  keys.forEach(k => clickShot(h, k, true));
  return {none, all_note: h.get('shotnote').textContent,
          all_posted: h.app.shotKeys().length,
          // ...and a normal selection says nothing at all
          some_note: (clickShot(h, 'news', false), h.get('shotnote').textContent)};
};

// An old search has to stay interpretable: what it was RUN with, not what the
// header happens to be ticked to now.
scenarios['the_selection_shows_on_the_job_and_recent_views'] = async () => {
  const recent = [
    {id: 41, kind: 'search', term: 'reef', project_label: '2026/FF5/Energy',
     phase: 'done', created_at: '2026-08-11T09:00:00', shot_types: ['aerial', 'raw']},
    {id: 42, kind: 'urls', term: 'links', project_label: '2026/FF5/Energy',
     phase: 'done', created_at: '2026-08-11T09:10:00', shot_types: ['aerial']},
    {id: 43, kind: 'search', term: 'wind', project_label: '2026/FF5/Energy',
     phase: 'done', created_at: '2026-08-11T09:20:00', shot_types: []},
  ];
  const manifest = MANIFEST({
    job: JOB({id: 41, phase: 'ready_for_review', shot_types: ['aerial', 'raw']}),
    videos: [VIDEO('KKKKKKKKKKK')],
    terms: [{id: 1, term: 'reef', lang: 'en', english_gloss: null,
             source: 'user', hits: 1, videos: 1}],
    counts: {relevant: 1, duplicates: 0, irrelevant: 0},
  });
  const h = await boot(async (method, url) => {
    if (url.startsWith('api/jobs?')) return {json: {jobs: recent}};
    const b = baseline(method, url); if (b) return b;
    if (url.startsWith('api/jobs/41/manifest')) return {json: manifest};
    if (url === 'api/jobs/41') return {json: POLLRES(manifest.job)};
    return {json: {}};
  });
  // the editor's CURRENT ticks are something else entirely
  clickShot(h, 'aerial', false);
  await h.app.attach(41);
  await flush();
  return {jobshots: h.get('jobshots').textContent,
          rows: h.get('recentlist').byClass('recentrow')
                 .map(r => r.byClass('shotsum').map(s => s.textContent).join(''))};
};

// ---- the search mode -----------------------------------------------------
// 2026-08-18: [ VISUALS ] [ NEWS MONTAGE ], left of the boxes. Choosing one
// presets the boxes and is posted with the search; the ticks are then
// remembered PER MODE, because the boxes mean different things in a b-roll
// search and a montage made of the reporting.

const modeButtons = h => h.get('modes').children;
const clickMode = (h, label) => {
  const b = modeButtons(h).find(x => x.textContent.includes(label));
  b.onclick();
};
const ticked = h => shotBoxes(h).filter(b => b.checked).map(b => b.value);

scenarios['the_mode_presets_the_boxes_and_is_posted'] = async () => {
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === 'api/jobs') return {json: {job_id: 61}};
    if (url === 'api/jobs/61') return {json: POLLRES(JOB({id: 61, phase: 'queued'}))};
    return {json: {}};
  });
  const buttons = modeButtons(h).map(b => [b.textContent, b.className,
                                           b.getAttribute('aria-pressed')]);
  const visuals_ticks = ticked(h);
  clickMode(h, 'NEWS MONTAGE');
  const news_ticks = ticked(h);
  const news_buttons = modeButtons(h).map(b => b.className);
  // ...and the editor can still adjust the boxes afterwards
  clickShot(h, 'aerial', true);
  h.get('q').value = 'reef';
  h.get('project').value = 's';
  await h.app.runSearch();
  await flush();
  const post = h.calls.filter(c => c.method === 'POST' && c.url === 'api/jobs')[0];
  // read the store BEFORE switching back, or the last click is what it says
  const stored = {mode: h.store['ytdl.search_mode'],
                  news: h.store['ytdl.shot_types.news'],
                  visuals: h.store['ytdl.shot_types']};
  // back to visuals: the ticks that mode was left on, not the news ones
  clickMode(h, 'VISUALS');
  return {buttons, visuals_ticks, news_ticks, news_buttons,
          body: post && post.body,
          stored_mode: stored.mode,
          stored_news: stored.news,
          stored_visuals: stored.visuals,
          back: ticked(h)};
};

scenarios['the_mode_and_its_ticks_come_back_from_localstorage'] = async () => {
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === 'api/jobs') return {json: {job_id: 62}};
    if (url === 'api/jobs/62') return {json: POLLRES(JOB({id: 62}))};
    return {json: {}};
  }, {'ytdl.search_mode': 'news',
      'ytdl.shot_types.news': JSON.stringify(['aerial', 'news'])});
  const start = ticked(h);
  h.get('q').value = 'reef';
  h.get('project').value = 's';
  await h.app.runSearch();
  await flush();
  const post = h.calls.filter(c => c.method === 'POST' && c.url === 'api/jobs')[0];
  return {start, posted: post && post.body,
          lit: modeButtons(h).map(b => b.className)};
};

// The server refuses a mode it does not know, so a value this build no longer
// offers would 400 every search from this browser until localStorage was
// cleared by hand -- the same rule the candidate cap runs under.
scenarios['a_stale_mode_falls_back_to_the_default'] = async () => {
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === 'api/jobs') return {json: {job_id: 63}};
    if (url === 'api/jobs/63') return {json: POLLRES(JOB({id: 63}))};
    return {json: {}};
  }, {'ytdl.search_mode': 'montage-2000'});
  h.get('q').value = 'reef';
  h.get('project').value = 's';
  await h.app.runSearch();
  await flush();
  const post = h.calls.filter(c => c.method === 'POST' && c.url === 'api/jobs')[0];
  return {posted: post && post.body.mode, ticks: ticked(h)};
};

// A manifest can sit at review for a week: "why is this full of press
// conferences" has to be answerable from the page, not from memory.
scenarios['the_mode_shows_on_the_running_job_and_the_recent_views'] = async () => {
  const recent = [
    {id: 44, kind: 'search', term: 'reef', project_label: '2026/FF5/Energy',
     phase: 'done', created_at: '2026-08-18T09:00:00', mode: 'news',
     shot_types: ['interview', 'news', 'commentary']},
    {id: 45, kind: 'search', term: 'wind', project_label: '2026/FF5/Energy',
     phase: 'done', created_at: '2026-08-18T09:10:00', mode: 'visuals',
     shot_types: ['aerial']},
    {id: 46, kind: 'urls', term: '', project_label: '2026/FF5/Energy',
     phase: 'done', created_at: '2026-08-18T09:20:00', mode: 'visuals'},
    // a row from before the column existed claims nothing at all
    {id: 47, kind: 'search', term: 'lng', project_label: '2026/FF5/Energy',
     phase: 'done', created_at: '2026-08-18T09:30:00', shot_types: ['aerial']},
  ];
  const running = JOB({id: 44, phase: 'searching', mode: 'news',
                       terms_total: 4, terms_done: 2});
  const manifest = MANIFEST({
    job: JOB({id: 44, phase: 'ready_for_review', mode: 'news',
              shot_types: ['interview', 'news'], max_candidates: 100}),
    videos: [VIDEO('LLLLLLLLLLL')],
    terms: [{id: 1, term: 'reef', lang: 'en', english_gloss: null,
             source: 'user', hits: 1, videos: 1}],
    counts: {relevant: 1, duplicates: 0, irrelevant: 0},
  });
  const h = await boot(async (method, url) => {
    if (url.startsWith('api/jobs?')) return {json: {jobs: recent}};
    const b = baseline(method, url); if (b) return b;
    if (url.startsWith('api/jobs/44/manifest')) return {json: manifest};
    if (url === 'api/jobs/44') return {json: POLLRES(running)};
    return {json: {}};
  });
  await h.app.attach(44);
  await flush();
  const ticker = h.get('ticker').textContent;
  // the review header is the manifest's own, not the poll's: it says what the
  // job on screen was RUN with, whatever the search bar is set to now
  await h.app.loadManifest(44);
  await flush();
  return {ticker, jobshots: h.get('jobshots').textContent,
          rows: h.get('recentlist').byClass('recentrow')
                 .map(r => r.byClass('modesum').map(m => m.textContent).join(''))};
};

// ---- the candidate-limit dropdown ---------------------------------------
// The other per-search dial, beside quality/date: how many candidates the
// search may collect, i.e. how many metadata calls it makes at YouTube. 100 by
// default because 112 rapid ones is where the NAS's IP was refused outright
// (2026-08-11). Remembered per browser like the shot ticks are.

const capSelect = h => h.get('maxcand');

scenarios['the_candidate_limit_defaults_and_is_posted_with_the_search'] = async () => {
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === 'api/jobs') return {json: {job_id: 51}};
    if (url === 'api/jobs/51') return {json: POLLRES(JOB({id: 51, phase: 'queued'}))};
    return {json: {}};
  });
  const initial = capSelect(h).value;
  const options = capSelect(h).children.map(o => [o.value, o.textContent]);
  h.get('q').value = 'reef';
  h.get('project').value = 's';
  await h.app.runSearch();
  await flush();
  const post = h.calls.filter(c => c.method === 'POST' && c.url === 'api/jobs')[0];
  return {initial, options, body: post && post.body};
};

scenarios['a_changed_candidate_limit_is_posted_and_remembered'] = async () => {
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === 'api/jobs') return {json: {job_id: 52}};
    if (url === 'api/jobs/52') return {json: POLLRES(JOB({id: 52}))};
    return {json: {}};
  });
  capSelect(h).value = '400';
  capSelect(h).onchange();              // what picking an option does
  h.get('q').value = 'a thin topic';
  h.get('project').value = 's';
  await h.app.runSearch();
  await flush();
  const post = h.calls.filter(c => c.method === 'POST' && c.url === 'api/jobs')[0];
  return {posted: post && post.body.max_candidates, stored: h.store['ytdl.max_candidates']};
};

scenarios['the_candidate_limit_comes_back_from_localstorage'] = async () => {
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === 'api/jobs') return {json: {job_id: 53}};
    if (url === 'api/jobs/53') return {json: POLLRES(JOB({id: 53}))};
    return {json: {}};
  }, {'ytdl.max_candidates': '200'});
  h.get('q').value = 'reef';
  h.get('project').value = 's';
  await h.app.runSearch();
  await flush();
  const post = h.calls.filter(c => c.method === 'POST' && c.url === 'api/jobs')[0];
  return {value: capSelect(h).value, posted: post && post.body.max_candidates};
};

// A number this build no longer offers (or junk) must not be posted: the
// server refuses one it does not know, which would 400 every search this
// browser ever made until localStorage was cleared by hand.
scenarios['a_stale_candidate_limit_falls_back_to_the_default'] = async () => {
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === 'api/jobs') return {json: {job_id: 54}};
    if (url === 'api/jobs/54') return {json: POLLRES(JOB({id: 54}))};
    return {json: {}};
  }, {'ytdl.max_candidates': '9999'});
  const value = capSelect(h).value;
  capSelect(h).value = 'nonsense';      // and a DOM nobody can explain either
  h.get('q').value = 'reef';
  h.get('project').value = 's';
  await h.app.runSearch();
  await flush();
  const post = h.calls.filter(c => c.method === 'POST' && c.url === 'api/jobs')[0];
  return {value, posted: post && post.body.max_candidates};
};

// What a job was RUN with, on the manifest header and in Recent searches --
// the answer to "why did that search find so much more than this one". An
// absent number (an old row, an old server) is shown as nothing at all.
scenarios['the_candidate_limit_shows_on_the_job_and_recent_views'] = async () => {
  const recent = [
    {id: 61, kind: 'search', term: 'reef', project_label: '2026/FF5/Energy',
     phase: 'done', created_at: '2026-08-11T09:00:00', shot_types: [],
     max_candidates: 400},
    {id: 62, kind: 'urls', term: 'links', project_label: '2026/FF5/Energy',
     phase: 'done', created_at: '2026-08-11T09:10:00', shot_types: [],
     max_candidates: 100},
    {id: 63, kind: 'search', term: 'wind', project_label: '2026/FF5/Energy',
     phase: 'done', created_at: '2026-08-11T09:20:00', shot_types: []},
  ];
  const manifest = MANIFEST({
    job: JOB({id: 61, phase: 'ready_for_review', shot_types: ['aerial'],
              max_candidates: 400}),
    videos: [VIDEO('LLLLLLLLLLL')],
    terms: [{id: 1, term: 'reef', lang: 'en', english_gloss: null,
             source: 'user', hits: 1, videos: 1}],
    counts: {relevant: 1, duplicates: 0, irrelevant: 0},
  });
  const h = await boot(async (method, url) => {
    if (url.startsWith('api/jobs?')) return {json: {jobs: recent}};
    const b = baseline(method, url); if (b) return b;
    if (url.startsWith('api/jobs/61/manifest')) return {json: manifest};
    if (url === 'api/jobs/61') return {json: POLLRES(manifest.job)};
    return {json: {}};
  });
  await h.app.attach(61);
  await flush();
  return {jobshots: h.get('jobshots').textContent,
          rows: h.get('recentlist').byClass('recentrow')
                 .map(r => r.byClass('capsum').map(s => s.textContent).join(''))};
};

// ---- the destination project -------------------------------------------
// The picker had no memory at all, so every page load put it back on the
// project the server happened to list FIRST. Live, 2026-08-14: 16 term folders
// meant for 2026/FF5/Energy Transition (position 3) landed in 2026/CCT/Creator
// Profiles/Season 1 (position 1), which the editor experienced as "the folder
// select keeps switching back to Creator Profiles".

const PROJECTS = [
  {slug: 'cct-s1', label: '2026/CCT/Creator Profiles/Season 1'},
  {slug: 'ff5-nuclear', label: '2026/FF5/Nuclear'},
  {slug: 'ff5-energy', label: '2026/FF5/Energy Transition'},
];

// Three projects rather than baseline()'s one: "the third one comes back" is
// the whole assertion, and against a one-project list every bug passes.
const projectPage = (seed, jobId) => boot(async (method, url) => {
  if (url.startsWith('api/projects')) {
    return {json: {projects: PROJECTS, projects_available: true, error: null}};
  }
  const b = baseline(method, url); if (b) return b;
  if (method === 'POST' && url === 'api/jobs') return {json: {job_id: jobId}};
  if (url === `api/jobs/${jobId}`) return {json: POLLRES(JOB({id: jobId}))};
  return {json: {}};
}, seed);

// CR-72 follow-up (2026-08-31). The picker's widening rule is per MACHINE, and
// the ONLY thing that can tell this browser which computer it is sitting at is
// the companion on the loopback. So boot asks /ytdl/capabilities once and puts
// the hostname on the /api/projects request.
//
// `cap` scripts that companion; `flag` is the fleet's local-download switch,
// because the probe is gated on it -- with the feature off the page must not
// touch 127.0.0.1 at all (the invariant test_with_the_flag_off... pins), and it
// does not need to: a server-side download widens the picker on its own.
const pickerPage = (cap, flag = true) => boot(async (method, url) => {
  if (url.startsWith('api/health')) {
    return {json: {claude: 'ok', claude_detail: '', yt_dlp: 'ok',
                   worker_alive: true, cookies: false, local_download: flag}};
  }
  if (url === CAP_URL) return cap ? cap() : {status: 404, json: {}};
  if (url.startsWith('api/projects')) {
    return {json: {projects: PROJECTS, projects_available: true, error: null}};
  }
  const b = baseline(method, url); if (b) return b;
  return {json: {}};
});

const projectQuery = h => (h.calls.filter(c => c.url.startsWith('api/projects'))
  .map(c => c.url));

scenarios['the_picker_says_which_computer_is_asking'] = async () => {
  // A companion that names the machine. Deliberately ok:false -- a tray app
  // that cannot take the DOWNLOAD (old yt-dlp, no ffmpeg) is still this
  // computer, and a wired rig works off the whole tree whoever fetches.
  const named = await pickerPage(() => ({json: {ok: false, reason: 'yt-dlp too old',
                                                machine: 'owen-rig', mode: 'base'}}));
  // No companion at all: the request must carry no machine, which is exactly
  // what an SPA from before this change sent.
  const none = await pickerPage(null);
  // A companion too old to know the field: same thing, no invention.
  const old = await pickerPage(() => ({json: {ok: true, editor: 'owen'}}));
  // Feature off: the loopback is never touched, so there is nothing to send.
  const off = await pickerPage(() => ({json: {ok: true, machine: 'owen-rig'}}), false);
  return {named: projectQuery(named), none: projectQuery(none),
          old: projectQuery(old), off: projectQuery(off),
          off_loopback: off.calls.filter(c => c.url.startsWith('http://127')).length};
};

scenarios['picking_a_project_remembers_it'] = async () => {
  const h = await projectPage(null, 91);
  const sel = h.get('project');
  sel.value = 'ff5-energy';
  sel.onchange();                       // what picking an option does
  return {stored: h.store['ytdl.project'],
          options: sel.children.map(o => [o.value, o.textContent]),
          wired: typeof sel.onchange === 'function'};
};

scenarios['the_remembered_project_comes_back_and_is_posted'] = async () => {
  const h = await projectPage({'ytdl.project': 'ff5-energy'}, 92);
  const restored = h.get('project').value;
  h.get('q').value = 'reef';            // deliberately NOT setting the project:
  await h.app.runSearch();              // the restore is what has to reach the POST
  await flush();
  const post = h.calls.filter(c => c.method === 'POST' && c.url === 'api/jobs')[0];
  return {restored, posted: post && post.body.project_slug};
};

// A project this editor has since unticked on the dashboard is not in the list
// any more. Assigning a <select> a value none of its options carry selects
// NOTHING in some browsers, which would leave runSearch with no slug at all --
// so an unknown slug must be left alone, silently, on the first option.
scenarios['a_project_that_is_gone_falls_back_silently'] = async () => {
  const h = await projectPage({'ytdl.project': 'deleted-last-month'}, 93);
  const sel = h.get('project');
  return {value: sel.value,
          options: sel.children.map(o => o.value),
          banners: h.banners(),
          go_disabled: h.get('go').disabled};
};

// ---- the download history ----------------------------------------------
// "once a video is downloaded we need a history like the original youtube
// download utility which shows thumbnails, titles, and allows the user to open
// in folder by clicking on it" (owner, 2026-08-11). The open half cannot be
// done by a browser at all -- it goes through the companion's loopback server,
// exactly as b-roll's Send to Resolve does, and must degrade when nothing
// answers rather than error.

const REVEAL_URL = 'http://127.0.0.1:8899/ytdl/reveal';

scenarios['history_lists_the_ledger_and_opens_a_folder'] = async () => {
  // A search's clip, a PASTE's (which is in the Youtube root, with no folder
  // of its own), and a row from a build that recorded no path at all.
  const page = {downloads: [DL('AAAAAAAAAAA'),
                            DL('BBBBBBBBBBB', {thumbnail: 'https://i.ytimg.com/vi/BBBBBBBBBBB/hqdefault.jpg',
                                               downloaded_by: 'sam',
                                               title: '<img src=x onerror=alert(1)>',
                                               term: '', term_dir: '',
                                               folder: 'Youtube',
                                               folder_path: 'Youtube',
                                               rel_path: 'Youtube/Channel [BBBBBBBBBBB].mp4',
                                               reveal_path: '2026/FF5/Energy/Youtube/Channel [BBBBBBBBBBB].mp4'}),
                            DL('CCCCCCCCCCC', {reveal_path: null})],
                total: 3, limit: 24, offset: 0, has_more: false};
  const h = await boot(async (method, url, body) => {
    if (url.startsWith('api/downloads')) return {json: page};
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === REVEAL_URL) {
      return {json: {ok: true, message: 'opened the folder'}};
    }
    return {json: {}};
  });
  const rows = h.get('historylist').byClass('histrow');
  rows[0].onclick();
  await flush();
  const call = h.calls.filter(c => c.url === REVEAL_URL)[0];
  return {rows: rows.map(r => r.textContent),
          thumbs: h.get('historylist').byClass('histthumb').map(n => n.src),
          titles: h.get('historylist').byClass('name').map(n => n.textContent),
          nopath: rows.map(r => r.className),
          clickable: rows.map(r => typeof r.onclick === 'function'),
          note: h.get('historynote').textContent,
          more_hidden: h.get('historymore').hidden,
          body: call && call.body,
          toast: h.get('toast').textContent};
};

scenarios['history_degrades_with_no_companion'] = async () => {
  const page = {downloads: [DL('DDDDDDDDDDD')], total: 1, limit: 24,
                offset: 0, has_more: false};
  const h = await boot(async (method, url) => {
    if (url.startsWith('api/downloads')) return {json: page};
    const b = baseline(method, url); if (b) return b;
    if (url === REVEAL_URL) {
      // What a browser does when nothing is listening on 8899: the fetch
      // itself rejects, before any status exists.
      throw new Error('Failed to fetch');
    }
    return {json: {}};
  });
  h.get('historylist').byClass('histrow')[0].onclick();
  await flush();
  const t = h.get('toast');
  const button = t.descendants().filter(n => n.tagName === 'button')[0];
  const text = t.textContent;
  button.onclick();
  await flush();
  return {text, raw: t.innerHTML, button: !!button, label: button && button.textContent,
          copied: h.copied, after_copy: t.textContent};
};

scenarios['history_says_so_when_the_companion_is_too_old'] = async () => {
  const page = {downloads: [DL('EEEEEEEEEEE')], total: 1, limit: 24,
                offset: 0, has_more: false};
  const h = await boot(async (method, url) => {
    if (url.startsWith('api/downloads')) return {json: page};
    const b = baseline(method, url); if (b) return b;
    // A companion that IS running but predates the route.
    if (url === REVEAL_URL) return {status: 404, json: {ok: false, message: 'not found: /ytdl/reveal'}};
    return {json: {}};
  });
  h.get('historylist').byClass('histrow')[0].onclick();
  await flush();
  return {toast: h.get('toast').textContent};
};

scenarios['history_refuses_to_dump_the_whole_ledger'] = async () => {
  const pages = {
    0: {downloads: [DL('FFFFFFFFFFF'), DL('GGGGGGGGGGG')], total: 3, limit: 24,
        offset: 0, has_more: true},
    2: {downloads: [DL('HHHHHHHHHHH')], total: 3, limit: 24, offset: 2,
        has_more: false},
  };
  const h = await boot(async (method, url) => {
    if (url.startsWith('api/downloads')) {
      const m = /offset=(\d+)/.exec(url);
      return {json: pages[m ? Number(m[1]) : 0] || pages[0]};
    }
    const b = baseline(method, url); if (b) return b;
    return {json: {}};
  });
  const first = {rows: h.get('historylist').byClass('histrow').length,
                 more_hidden: h.get('historymore').hidden,
                 note: h.get('historynote').textContent};
  await h.get('historymore').onclick();
  await flush();
  return {first, urls: h.calls.filter(c => c.url.startsWith('api/downloads')).map(c => c.url),
          rows: h.get('historylist').byClass('histrow').length,
          more_hidden: h.get('historymore').hidden,
          note: h.get('historynote').textContent};
};

// ---- what the page attaches to on load ----------------------------------
// Found live, 2026-08-11: a finished paste job was pinned in the hash while a
// ready_for_review job with 74 relevant clips sat unshown -- and because
// ready_for_review counts as the editor's one ACTIVE job (YTDL-25), it was also
// silently 409ing every new search they tried.

const openingHandler = (active, jobs) => async (method, url) => {
  if (url === 'api/jobs/active') return {json: {job: active}};
  const b = baseline(method, url); if (b) return b;
  for (const id of Object.keys(jobs)) {
    if (url === `api/jobs/${id}`) return {json: POLLRES(jobs[id])};
    if (url.startsWith(`api/jobs/${id}/manifest`)) {
      return {json: MANIFEST({job: jobs[id], videos: [VIDEO('ZZZZZZZZZZZ')],
                              terms: [{id: 1, term: 'reef', lang: 'en',
                                       english_gloss: null, source: 'user',
                                       hits: 1, videos: 1}],
                              counts: {relevant: 1, duplicates: 0, irrelevant: 0}})};
    }
  }
  return {json: {}};
};

const OPENING_JOBS = {
  4: JOB({id: 4, kind: 'urls', phase: 'done', terminal: true, dl_total: 1, dl_done: 1}),
  5: JOB({id: 5, phase: 'ready_for_review', terminal: false}),
};

scenarios['an_active_job_beats_a_stale_hash'] = async () => {
  const h = await boot(openingHandler(OPENING_JOBS[5], OPENING_JOBS), null,
                       'job=4');
  await flush();
  return {job_id: h.app.state.jobId, hash: h.ctx.location.hash,
          review_hidden: h.get('review').hidden,
          polled: h.calls.filter(c => c.url === 'api/jobs/4').length};
};

scenarios['a_terminal_hash_still_deep_links'] = async () => {
  const h = await boot(openingHandler(null, OPENING_JOBS), null, 'job=4');
  await flush();
  return {job_id: h.app.state.jobId, hash: h.ctx.location.hash,
          downloads_hidden: h.get('downloads').hidden};
};

scenarios['no_hash_and_no_active_job_attaches_nothing'] = async () => {
  const h = await boot(openingHandler(null, OPENING_JOBS), null, '');
  await flush();
  return {job_id: h.app.state.jobId, hash: h.ctx.location.hash,
          progress_hidden: h.get('progress').hidden,
          polling: h.polling()};
};

// The owner, 2026-08-30: "I just submitted 12 youtube links to be downloaded
// but I clicked away and came back and it seems to have eaten them" -- the
// downloads were fine (server-side, 27 clips landed), only the page came back
// showing nothing. A fresh page load (no hash: he came back to the bare URL,
// not a bookmarked #job=) must re-read BOTH halves of "what is my downloader
// doing" -- the active job AND the queue behind it -- the same way it would
// have looked had the tab never closed.
const AWAY_ACTIVE = JOB({id: 9, kind: 'urls', phase: 'downloading',
                         terminal: false, dl_total: 12, dl_done: 7,
                         term_dir: '', project_label: '2026/FF5/Energy'});
const AWAY_QUEUE = [
  {id: 10, term: '', kind: 'urls', project_label: '2026/FF5/Water',
   phase: 'queued', position: 1, created_at: '2026-08-30T10:00:00+00:00'},
  {id: 11, term: 'reef protest', kind: 'search', project_label: '2026/FF5/Water',
   phase: 'queued', position: 2, created_at: '2026-08-30T10:00:00+00:00'},
];

scenarios['a_paste_and_leave_still_shows_the_running_job_and_the_queue'] = async () => {
  const h = await boot(async (method, url) => {
    if (url === 'api/jobs/active') {
      return {json: {job: AWAY_ACTIVE, queue: AWAY_QUEUE}};
    }
    const b = baseline(method, url); if (b) return b;
    if (url === `api/jobs/${AWAY_ACTIVE.id}`) return {json: POLLRES(AWAY_ACTIVE)};
    return {json: {}};
  }, null, '');
  await flush();
  return {
    job_id: h.app.state.jobId,
    hash: h.ctx.location.hash,
    progress_hidden: h.get('progress').hidden,
    downloads_hidden: h.get('downloads').hidden,
    queue_hidden: h.get('queue').hidden,
    queue_rows: h.get('queuelist').byClass('queuerow').length,
    // Both halves asked for fresh, on THIS load -- not carried over from a
    // session that never existed on this tab.
    asked_active: h.calls.filter(c => c.url === 'api/jobs/active').length,
    asked_recent: h.calls.filter(c => c.url.startsWith('api/jobs?')).length,
  };
};

// The other half: by the time he looked, the paste had ALREADY finished (no
// active job at all) -- the clips still have to be found, in Recent searches,
// without a click.
const AWAY_DONE = JOB({id: 12, kind: 'urls', phase: 'done', terminal: true,
                       dl_total: 12, dl_done: 12, term_dir: '',
                       project_label: '2026/FF5/Energy'});

scenarios['a_finished_paste_still_shows_in_recent_on_a_fresh_load'] = async () => {
  const h = await boot(async (method, url) => {
    if (url === 'api/jobs/active') return {json: {job: null, queue: []}};
    if (url.startsWith('api/jobs?')) {
      return {json: {jobs: [AWAY_DONE]}};
    }
    const b = baseline(method, url); if (b) return b;
    return {json: {}};
  }, null, '');
  await flush();
  return {
    recentsum: h.get('recentsum').textContent,
    recent_rows: h.get('recentlist').byClass('recentrow').length,
    job_id: h.app.state.jobId,
  };
};

// An older server has no such route. The hash is still better than nothing.
scenarios['a_missing_active_route_falls_back_to_the_hash'] = async () => {
  const h = await boot(async (method, url) => {
    if (url === 'api/jobs/active') return {status: 404, json: {detail: 'nope'}};
    const b = baseline(method, url); if (b) return b;
    return openingHandler(null, OPENING_JOBS)(method, url);
  }, null, 'job=4');
  await flush();
  return {job_id: h.app.state.jobId, hash: h.ctx.location.hash};
};

// ---- the collapsible panels ---------------------------------------------
// "there should be a way to collapse the search results that are open"
// (owner, 2026-08-11). A real search lands ~74 cards in the review grid and
// everything stacked under it -- Recent searches, the download history -- is
// off the bottom of the screen. Every bulky panel folds to its HEADER, and the
// header keeps the count: folding must hide bulk, not meaning.

const PANEL_BODY = {review: 'reviewbody', downloads: 'dllist',
                    recent: 'recentlist', history: 'historybody'};

const panelState = h => {
  const out = {};
  for (const id of Object.keys(PANEL_BODY)) {
    out[id] = {folded: h.get(PANEL_BODY[id]).hidden,
               label: h.get(id + 'toggle').textContent,
               aria: h.get(id + 'toggle').getAttribute('aria-expanded')};
  }
  return out;
};

// A page with something in every panel: one ready_for_review job of three
// clips, a recent list, and a ledger page out of a 7-clip history.
const REVIEW_JOB = JOB({id: 81, phase: 'ready_for_review'});
const REVIEW_MANIFEST = MANIFEST({
  job: REVIEW_JOB,
  videos: [VIDEO('AAAAAAAAAA1', {selected: 1}), VIDEO('AAAAAAAAAA2', {selected: 1}),
           VIDEO('AAAAAAAAAA3')],
  terms: [{id: 1, term: 'reef', lang: 'en', english_gloss: null, source: 'user',
           hits: 3, videos: 3}],
  counts: {relevant: 3, duplicates: 0, irrelevant: 0},
});

const fullPage = (seed, hash) => boot(async (method, url) => {
  if (url.startsWith('api/jobs?')) {
    return {json: {jobs: [{id: 81, kind: 'search', term: 'reef',
                           project_label: '2026/FF5/Energy',
                           phase: 'ready_for_review', shot_types: [],
                           created_at: '2026-08-11T09:00:00'}]}};
  }
  if (url.startsWith('api/downloads')) {
    return {json: {downloads: [DL('BBBBBBBBBB1'), DL('BBBBBBBBBB2')], total: 7,
                   limit: 24, offset: 0, has_more: false}};
  }
  const b = baseline(method, url); if (b) return b;
  if (url === 'api/jobs/81') return {json: POLLRES(REVIEW_JOB)};
  if (url.startsWith('api/jobs/81/manifest')) return {json: REVIEW_MANIFEST};
  return {json: {}};
}, seed, hash);

scenarios['every_stacked_panel_folds_to_its_header'] = async () => {
  const h = await fullPage();
  await h.app.attach(81);
  await flush();
  const open = panelState(h);
  const filled = {review: h.get('reviewsum').textContent,
                  recent: h.get('recentsum').textContent,
                  history: h.get('historysum').textContent,
                  cards: h.get('grid').byClass('card').length,
                  rows: h.get('recentlist').byClass('recentrow').length,
                  ledger: h.get('historylist').byClass('histrow').length};
  Object.keys(PANEL_BODY).forEach(id => h.get(id + 'toggle').onclick());
  const folded = panelState(h);
  const summaries = {review: h.get('reviewsum').textContent,
                     recent: h.get('recentsum').textContent,
                     history: h.get('historysum').textContent};
  h.get('reviewtoggle').onclick();          // and open again
  return {open, filled, folded, summaries, stored: h.store['ytdl.collapsed'],
          reopened: panelState(h).review,
          // folding the BODY must not undo loadManifest's un-hiding of the
          // section itself -- the header is the thing left to click
          review_section_hidden: h.get('review').hidden};
};

// The downloads panel folds its LIST only: the phase, the counter, [ CANCEL ]
// and the bar are the job talking, and a job in flight must not go quiet
// because its list of rows was put away.
scenarios['a_folded_download_list_still_shows_the_job'] = async () => {
  const vids = [VIDEO('CCCCCCCCCC1', {dl_state: 'done', selected: 1}),
                VIDEO('CCCCCCCCCC2', {dl_state: 'downloading', selected: 1})];
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (url === 'api/jobs/82') {
      return {json: POLLRES(JOB({id: 82, phase: 'downloading', dl_total: 7, dl_done: 3}),
                            {progress: {CCCCCCCCCC2: {percent: 50, speed: '2.0MiB/s',
                                                      status: 'downloading'}}})};
    }
    if (url.startsWith('api/jobs/82/manifest')) return {json: MANIFEST({videos: vids})};
    return {json: {}};
  });
  await h.app.attach(82);
  await flush();
  const rows = h.get('dllist').byClass('dlrow').length;
  h.get('downloadstoggle').onclick();
  const folded = {list: h.get('dllist').hidden,
                  panel: h.get('downloads').hidden,
                  phase: h.get('dlphase').textContent,
                  ticker: h.get('dlticker').textContent,
                  cancel_hidden: h.get('cancel2').hidden,
                  width: h.get('dlfill').style.width,
                  label: h.get('downloadstoggle').textContent};
  await h.timers.fire();                    // a live tick must not unfold it
  return {rows, folded, after_a_tick: h.get('dllist').hidden,
          ticker_after: h.get('dlticker').textContent};
};

scenarios['folded_panels_come_back_from_localstorage'] = async () => {
  const h = await fullPage({'ytdl.collapsed': JSON.stringify(['recent', 'history'])});
  const start = panelState(h);
  h.get('recenttoggle').onclick();          // open one
  h.get('reviewtoggle').onclick();          // fold another
  return {start, stored: h.store['ytdl.collapsed'], after: panelState(h)};
};

// A key this build no longer has (or junk, or the wrong shape) must not fold
// nothing forever, and must not stop the page: the same contract loadShots()
// and loadCap() have.
scenarios['a_stale_collapsed_key_is_ignored'] = async () => {
  const h = await fullPage({'ytdl.collapsed': JSON.stringify(['klingon', 'history'])});
  const unknown = panelState(h);
  h.get('recenttoggle').onclick();          // the rewrite drops what it never knew
  const junk = await fullPage({'ytdl.collapsed': 'not json at all'});
  const shaped = await fullPage({'ytdl.collapsed': JSON.stringify({review: true})});
  return {unknown, rewritten: h.store['ytdl.collapsed'],
          junk: panelState(junk), shaped: panelState(shaped),
          junk_cards: junk.get('historylist').byClass('histrow').length};
};

// The one behavioural exception: a job that has just ARRIVED at review unfolds
// the panel and clears its stored fold, or an editor who folded the grid runs a
// new search and sees nothing happen -- the "nothing is visible for review"
// confusion this page already caused once (2026-08-11).
scenarios['a_job_arriving_at_review_unfolds_the_panel'] = async () => {
  let polls = 0;
  const job = JOB({id: 83, phase: 'ready_for_review'});
  const manifest = MANIFEST({
    job, videos: [VIDEO('DDDDDDDDDD1', {selected: 1})],
    terms: [{id: 1, term: 'reef', lang: 'en', english_gloss: null, source: 'user',
             hits: 1, videos: 1}],
    counts: {relevant: 1, duplicates: 0, irrelevant: 0},
  });
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (url === 'api/jobs/83') {
      polls++;
      return {json: POLLRES(polls === 1 ? JOB({id: 83, phase: 'searching'}) : job)};
    }
    if (url.startsWith('api/jobs/83/manifest')) return {json: manifest};
    return {json: {}};
  }, {'ytdl.collapsed': JSON.stringify(['review', 'recent'])});
  const before = panelState(h);
  await h.app.attach(83);                   // tick 1: still searching
  await flush();
  const searching = h.get('reviewbody').hidden;
  await h.timers.fire();                    // tick 2: ready for review
  const arrived = {folded: h.get('reviewbody').hidden,
                   stored: h.store['ytdl.collapsed'],
                   label: h.get('reviewtoggle').textContent,
                   aria: h.get('reviewtoggle').getAttribute('aria-expanded'),
                   sum: h.get('reviewsum').textContent,
                   cards: h.get('grid').byClass('card').length,
                   // only the review panel: the others are the editor's
                   recent_folded: h.get('recentlist').hidden};
  // ...and a fold made AFTER the arrival sticks. Seeing the SAME phase again is
  // not a new arrival, so even a re-poll leaves it folded.
  h.get('reviewtoggle').onclick();
  const manual = {folded: h.get('reviewbody').hidden,
                  stored: h.store['ytdl.collapsed']};
  await h.app.poll();
  await flush();
  return {before, searching, arrived, manual, polls,
          after_another_poll: h.get('reviewbody').hidden,
          stored_at_the_end: h.store['ytdl.collapsed']};
};

// The other half of "newly reaches": a job that was ALREADY at review when the
// page attached to it -- a deep link, a 409 re-attach, a reload -- has not
// arrived anywhere, so the editor's fold stands. The grid is still BUILT
// underneath it, so opening it is one click and no fetch.
scenarios['attaching_to_an_old_review_respects_the_fold'] = async () => {
  const h = await fullPage({'ytdl.collapsed': JSON.stringify(['review'])});
  await h.app.attach(81);
  await flush();
  const folded = {body: h.get('reviewbody').hidden,
                  section: h.get('review').hidden,
                  stored: h.store['ytdl.collapsed'],
                  sum: h.get('reviewsum').textContent,
                  label: h.get('reviewtoggle').textContent,
                  cards: h.get('grid').byClass('card').length};
  h.get('reviewtoggle').onclick();
  return {folded, after_unfold: h.get('reviewbody').hidden,
          stored_after: h.store['ytdl.collapsed']};
};

// ---- requester-first downloads ------------------------------------------
// docs/YTDL_LOCAL_DOWNLOAD.md §§2/9/10. The SPA's whole part in this is: probe
// the editor's own companion when the server says the feature is on, hand it a
// job id, and name the executor in the header. Every one of those has to be
// invisible when it fails -- the clips arrive from the NAS either way -- so the
// scenarios below are mostly about what does NOT happen.

const CAP_URL = 'http://127.0.0.1:8899/ytdl/capabilities';
const LOCAL_DL_URL = 'http://127.0.0.1:8899/ytdl/download';

// Everything this page said to 127.0.0.1, in order.
const loopback = h => h.calls.filter(c => c.url.startsWith('http://127.0.0.1:8899'))
  .map(c => ({method: c.method, url: c.url, body: c.body}));

// Everything the page asked the loopback WHILE DISPATCHING, i.e. after the
// page had finished booting. Since 2026-08-31 boot itself asks
// /ytdl/capabilities once, to learn which computer this browser is sitting at
// for the project picker (CR-72 follow-up) -- a different question from "can
// this machine take the job", asked at a different time. The invariants below
// are about the DISPATCH ("one probe, one POST, and no retry loop"), so they
// measure from the end of boot rather than from the start of the page.
const dispatchedBy = h => loopback(h).slice(h._loopbackAtBoot || 0);

// A page with one reviewed job (90) ready to submit. `flag` is the server's
// phase-1 switch as api/health reports it -- UNDEFINED means a server that
// predates the field at all, which is not the same test as `false`. `cap`/`dl`
// script the companion's two routes; `mode` is what the server then says about
// the job (a function of the poll number, for the reclaim case).
function dispatchPage(opts) {
  const {flag, cap, dl, lock, mode, quality} = opts || {};
  let started = false, downloadPolls = 0;
  // Marked at the END of boot, not at the start of submit(): some scenarios
  // below drive app.dispatchLocal() directly and never submit at all, and
  // they measure the same "what did the DISPATCH ask" invariant.
  const marked = h => {
    h._loopbackAtBoot = loopback(h).length;
    h._callsAtBoot = h.calls.length;
    return h;
  };
  return boot(async (method, url, body) => {
    if (url.startsWith('api/health')) {
      const j = {claude: 'ok', claude_detail: '', yt_dlp: 'ok',
                 worker_alive: true, cookies: false};
      if (flag !== undefined) j.local_download = flag;
      return {json: j};
    }
    const b = baseline(method, url); if (b) return b;
    // The companion. Absent by default: 404 is what a tray app that predates
    // 0.8.0 answers, and it is the fleet's normal state through all of phase 1.
    if (url === CAP_URL) return cap ? cap() : {status: 404, json: {}};
    if (url === LOCAL_DL_URL) return dl ? dl() : {status: 503, json: {ok: false}};
    if (method === 'POST' && url === 'api/jobs/90/download') {
      started = true;
      return {json: {ok: true}};
    }
    if (method === 'POST' && url === 'api/jobs/90/mode-lock') {
      return lock ? lock(body) : {json: {ok: true, download_mode: 'server'}};
    }
    if (url === 'api/jobs/90') {
      if (!started) return {json: POLLRES(JOB({id: 90, phase: 'ready_for_review'}))};
      downloadPolls++;
      const m = typeof mode === 'function' ? mode(downloadPolls) : mode;
      return {json: POLLRES(JOB({id: 90, phase: 'downloading', dl_total: 1,
                                 dl_done: 0, download_mode: m,
                                 claimed_by: m === 'local' ? 'owen' : null}))};
    }
    if (url.startsWith('api/jobs/90/manifest')) {
      return {json: MANIFEST({job: JOB({id: 90, phase: 'ready_for_review',
                                        quality}),
                              videos: [VIDEO('AAAAAAAAAA9', {selected: 1,
                                                             dl_state: 'pending'})]})};
    }
    return {json: {}};
  }).then(marked);
}

const submit = async h => {
  await h.app.attach(90);
  await flush();
  await h.app.startDownload();
  await flush(20);
  return h;
};

const CAPABLE = () => ({json: {ok: true, editor: 'owen',
                               ytdlp_version: '2026.08.10', free_bytes: 9e11}});
const ACCEPTED = () => ({status: 202, json: {ok: true, job_id: 90}});

// §10 phase 1: the flag is what makes any of this exist. Off -- or absent, on a
// server that has not been deployed yet -- the page must not so much as LOOK at
// 127.0.0.1, and must not badge a download_mode the server sent anyway.
scenarios['the_server_flag_gates_the_whole_feature'] = async () => {
  const off = await submit(await dispatchPage(
    {flag: false, mode: 'local', cap: CAPABLE, dl: ACCEPTED}));
  const older = await submit(await dispatchPage(
    {mode: 'local', cap: CAPABLE, dl: ACCEPTED}));
  return {off: dispatchedBy(off), older: dispatchedBy(older),
          // ...and the server was still given the selection, as always
          submitted: off.calls.filter(c => c.url === 'api/jobs/90/download').length,
          badge_hidden: off.get('dlmode').hidden,
          badge_text: off.get('dlmode').textContent,
          link_hidden: off.get('dlserver').hidden,
          downloads_hidden: off.get('downloads').hidden};
};

// The happy path (§2, steps 1-3): probe, then one POST carrying a job id and
// nothing else. Never twice -- there is no retry loop and no polling of the
// loopback, so a dozen later ticks add no calls.
scenarios['a_capable_companion_is_handed_the_job'] = async () => {
  const h = await submit(await dispatchPage(
    {flag: true, mode: 'local', cap: CAPABLE, dl: ACCEPTED}));
  const dispatched = dispatchedBy(h);
  await h.timers.fire();
  await h.timers.fire();
  return {dispatched, after_more_polls: dispatchedBy(h).length,
          // the server's own accept comes FIRST: the job downloads either way
          // Sliced at the boot mark for dispatchedBy()'s reason: boot's own
          // picker probe is not part of the order this pins.
          order: h.calls.slice(h._callsAtBoot || 0).map(c => c.url)
            .filter(u => u === 'api/jobs/90/download' || u.startsWith('http://127')),
          badge: h.get('dlmode').textContent,
          badge_hidden: h.get('dlmode').hidden,
          badge_class: h.get('dlmode').className,
          badge_title: h.get('dlmode').title,
          link_hidden: h.get('dlserver').hidden,
          review_hidden: h.get('review').hidden,
          toast_hidden: h.get('toast').hidden};
};

// §11's whole first column, one scenario: every way the companion can fail to
// be a companion ends with no dispatch, no error, and the server worker doing
// the job exactly as it does today.
scenarios['a_companion_that_cannot_take_it_is_never_handed_it'] = async () => {
  const run = over => dispatchPage(Object.assign(
    {flag: true, mode: 'server'}, over)).then(submit);
  // nothing listening (or the browser refusing a local connection)
  const dead = await run({cap: () => { throw new Error('Failed to fetch'); }});
  const old = await run({cap: () => ({status: 404, json: {}})});          // pre-0.8.0
  const unable = await run({cap: () => ({json: {ok: false, reason: 'yt-dlp too old'}})});
  const refused = await run({cap: CAPABLE, dl: () => ({status: 503, json: {ok: false}})});
  const busy = await run({cap: CAPABLE, dl: () => ({status: 409, json: {ok: false}})});
  // the ONE refusal the editor can fix themselves: the terms, not yet accepted
  // in the tray (owner, 2026-08-18) -- said out loud, still server-side
  const terms = await run({cap: () => ({json: {ok: false,
    reason: "the YouTube terms have not been accepted on this machine: tray > 'Accept YouTube Terms...'"}})});
  return {dead: dispatchedBy(dead), old: dispatchedBy(old), unable: dispatchedBy(unable),
          refused: dispatchedBy(refused).map(c => c.url),
          busy: dispatchedBy(busy).map(c => c.url),
          // every one of them now SAYS SO (2026-08-19, the owner). Silence was
          // the old rule and it stopped being defensible when "the server did
          // it" started meaning "the clip stays on the NAS".
          spoken: [dead, old, unable, refused, busy]
            .map(p => [p.get('toast').hidden, p.get('toast').textContent]),
          terms: {calls: dispatchedBy(terms).map(c => c.url),
                  toast_hidden: terms.get('toast').hidden,
                  toast_text: terms.get('toast').textContent,
                  badge: terms.get('dlmode').textContent},
          // and every one of them is downloading, on the server
          badges: [dead, old, unable, refused, busy]
            .map(p => p.get('dlmode').textContent)};
};

// The companion that answers NOTHING -- a wedged tray, a machine that went to
// sleep between the click and the probe. The abort is what makes this a
// one-second cost instead of a promise that never settles, so the scenario
// waits for the dispatch to actually give up rather than for the call count to
// stay put (which it would either way).
scenarios['a_hung_probe_is_abandoned_after_a_second'] = async () => {
  const hang = () => new Promise(() => {});
  // What the EDITOR sees meanwhile: startDownload never awaits the probe, so
  // the review panel is away and the job is on screen downloading regardless.
  const page = await submit(await dispatchPage(
    {flag: true, mode: 'server', cap: hang}));
  const during = {calls: dispatchedBy(page).length,
                  review_hidden: page.get('review').hidden,
                  downloads_hidden: page.get('downloads').hidden,
                  badge: page.get('dlmode').textContent,
                  toast_hidden: page.get('toast').hidden};

  // And the probe itself: called directly, because the only way to see it give
  // up is its own return value -- the call COUNT stays at one whether it was
  // abandoned after PROBE_MS or is still waiting for a tray app that will
  // never answer.
  const h = await dispatchPage({flag: true, mode: 'server', cap: hang});
  await h.app.attach(90);
  await flush();
  const p = h.app.dispatchLocal(90);
  await flush();
  await h.timers.fire();                  // the PROBE_MS abort
  await flush();
  await h.timers.fire();                  // ...and the PROBE_RETRY_MS one
  await flush();
  // Bounded on purpose: an unbounded await on a probe that was never abandoned
  // would hang the whole harness instead of failing this one scenario.
  const stuck = {};
  const out = await Promise.race([p, flush(50).then(() => stuck)]);
  // calls === 2 because a TIMED-OUT probe is retried once (PROBE_RETRY_MS,
  // 2026-08-19). A hung tray app therefore costs both budgets and then gives
  // up -- still bounded, which is the whole point of this scenario.
  return {during, abandoned: out === false, never_gave_up: out === stuck,
          calls: dispatchedBy(h).length};
};

// COMP-BROLL-10: the local executor only runs the rungs it can NAME correctly
// (480p/720p/1080p -- the rest need the server's transcode, whose filename it
// cannot reproduce). It declares that in its capabilities, and a job outside it
// is never dispatched: the claim would be taken and handed straight back. A
// companion that declares nothing behaves exactly as it did before the field.
scenarios['an_out_of_scope_job_is_never_handed_over'] = async () => {
  const SCOPED = () => ({json: {ok: true, editor: 'owen',
                                ytdlp_version: '2026.08.10', free_bytes: 9e11,
                                scope_qualities: ['480p', '720p', '1080p']}});
  const run = (q, capfn) => dispatchPage(
    {flag: true, mode: 'server', quality: q, cap: capfn, dl: ACCEPTED}).then(submit);
  const inScope = await run('1080p', SCOPED);
  const outOfScope = await run('2160p', SCOPED);
  const undeclared = await run('2160p', CAPABLE);
  return {in_scope: dispatchedBy(inScope).map(c => c.url),
          out_of_scope: dispatchedBy(outOfScope).map(c => c.url),
          undeclared: dispatchedBy(undeclared).map(c => c.url),
          // the server was still given the selection in every case
          submitted: [inScope, outOfScope, undeclared]
            .map(p => p.calls.filter(c => c.url === 'api/jobs/90/download').length),
          spoken: [outOfScope.get('toast').hidden, outOfScope.get('toast').textContent]};
};

// §9: the badge is derived from the poll payload every tick and remembered
// nowhere, so a lease that expires and is reclaimed server-side (§3) flips it
// on its own -- which is the point, because a silent executor swap is how
// editors conclude a feature is broken.
scenarios['the_badge_flips_when_the_server_reclaims'] = async () => {
  const h = await submit(await dispatchPage(
    {flag: true, cap: CAPABLE, dl: ACCEPTED,
     mode: n => (n <= 2 ? 'local' : 'server')}));
  const local = {badge: h.get('dlmode').textContent,
                 cls: h.get('dlmode').className,
                 title: h.get('dlmode').title,
                 link_hidden: h.get('dlserver').hidden};
  await h.timers.fire();                  // poll 2: still ours
  const still = h.get('dlmode').textContent;
  await h.timers.fire();                  // poll 3: the server took it back
  return {local, still, reclaimed: h.get('dlmode').textContent,
          reclaimed_cls: h.get('dlmode').className,
          reclaimed_title: h.get('dlmode').title,
          link_hidden_after: h.get('dlserver').hidden,
          dispatches: dispatchedBy(h).length};
};

// The per-job escape hatch (§9). One POST however many times it is clicked, to
// a document-relative URL, and the page changes nothing itself: it finds out
// from the next poll, exactly as it finds out about a reclaim it did not ask
// for.
scenarios['handing_the_job_back_posts_once'] = async () => {
  const h = await submit(await dispatchPage(
    {flag: true, cap: CAPABLE, dl: ACCEPTED,
     mode: n => (n <= 1 ? 'local' : 'server')}));
  const btn = h.get('dlserver');
  const before = btn.hidden;
  btn.onclick();
  btn.onclick();                          // the double-click
  await flush();
  const posts = h.calls.filter(c => c.url.includes('mode-lock'));
  const after_click = {badge: h.get('dlmode').textContent, disabled: btn.disabled};
  await h.timers.fire();                  // ...and the next poll is the truth
  return {before, posts, after_click, toast: h.get('toast').textContent,
          badge_after_poll: h.get('dlmode').textContent,
          link_hidden_after: btn.hidden};
};

// A blip on that POST must not leave the editor with a dead button and no
// explanation: this one is a deliberate human action, unlike the dispatch.
scenarios['a_refused_hand_back_says_so_and_comes_back'] = async () => {
  const h = await submit(await dispatchPage(
    {flag: true, mode: 'local', cap: CAPABLE, dl: ACCEPTED,
     lock: () => ({status: 503, json: {detail: 'the lease is already gone'}})}));
  const btn = h.get('dlserver');
  btn.onclick();
  await flush();
  return {toast: h.get('toast').textContent, disabled: btn.disabled,
          hidden: btn.hidden};
};

// A search refused against a review nobody downloaded from can now discard it
// and go (owner, 2026-08-24): the parked job is the ONE non-terminal phase
// with nothing in flight, so cancelling it is safe, and the refused payload is
// re-sent as-is. The harness has no window.confirm, so scenarios opt in.
scenarios['blocked_search_offers_discard_and_retries'] = async () => {
  let posts = 0;
  const h = await boot(async (method, url, body) => {
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === 'api/jobs') {
      posts++;
      if (posts === 1) {
        return {status: 409, json: {detail: {detail: 'you already have a job in progress',
                                             job_id: 77, phase: 'ready_for_review'}}};
      }
      return {json: {job_id: 88, phase: 'queued'}};
    }
    if (method === 'POST' && url === 'api/jobs/77/cancel') {
      return {json: {ok: true, phase: 'cancelled'}};
    }
    if (url === 'api/jobs/88') return {json: POLLRES(JOB({id: 88, phase: 'searching'}))};
    return {json: {}};
  });
  h.ctx.confirm = () => true;
  h.get('q').value = 'reef';
  h.get('project').value = 's';
  await h.app.runSearch();
  await flush();
  const cancel_calls = h.calls.filter(c => c.method === 'POST'
                                           && c.url === 'api/jobs/77/cancel').length;
  return {posts, cancel_calls, job_id: h.app.state.jobId,
          go_disabled: h.get('go').disabled, polling: h.polling()};
};

// Declining the offer is the OLD behaviour exactly: re-attach, loud toast,
// nothing cancelled. (No-confirm-at-all is pinned by refused_search_reattaches
// above -- the guard treats an absent confirm as a decline too.)
scenarios['declining_the_discard_keeps_the_parked_review'] = async () => {
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === 'api/jobs') {
      return {status: 409, json: {detail: {detail: 'you already have a job in progress',
                                           job_id: 77, phase: 'ready_for_review'}}};
    }
    if (url === 'api/jobs/77') return {json: POLLRES(JOB({id: 77, phase: 'searching'}))};
    return {json: {}};
  });
  h.ctx.confirm = () => false;
  h.get('q').value = 'reef';
  h.get('project').value = 's';
  await h.app.runSearch();
  await flush();
  return {job_id: h.app.state.jobId,
          cancels: h.calls.filter(c => c.url.endsWith('/cancel')).length,
          toast: h.get('toast').textContent};
};

// The same offer on GET LINKS: a paste is refused against a parked review by
// the same one-job rule, and had the same dead end.
scenarios['blocked_paste_offers_discard_and_retries'] = async () => {
  let posts = 0;
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === 'api/jobs/urls') {
      posts++;
      if (posts === 1) {
        return {status: 409, json: {detail: {detail: 'you already have a job in progress',
                                             job_id: 77, phase: 'ready_for_review'}}};
      }
      return {json: {job_id: 90, phase: 'queued', queued: 1, skipped: []}};
    }
    if (method === 'POST' && url === 'api/jobs/77/cancel') {
      return {json: {ok: true, phase: 'cancelled'}};
    }
    if (url === 'api/jobs/90') return {json: POLLRES(JOB({id: 90, phase: 'downloading', dl_total: 1}))};
    return {json: {}};
  });
  h.ctx.confirm = () => true;
  h.get('urls').value = 'https://youtu.be/JJJJJJJJJJJ';
  h.get('project').value = 's';
  await h.app.runUrls();
  await flush();
  const cancel_calls = h.calls.filter(c => c.method === 'POST'
                                           && c.url === 'api/jobs/77/cancel').length;
  return {posts, cancel_calls, job_id: h.app.state.jobId,
          golinks_disabled: h.get('golinks').disabled};
};

// The review header's own way out: [ CANCEL SEARCH ] on a parked review
// cancels it and CLEARS the page -- a cancelled review left on screen reads
// as a cancel that did not work.
scenarios['review_offers_cancel_search_and_clears_the_page'] = async () => {
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (url === 'api/jobs/9') {
      return {json: POLLRES(JOB({id: 9, phase: 'ready_for_review'}))};
    }
    if (url === 'api/jobs/9/manifest') {
      return {json: MANIFEST({job: JOB({id: 9, phase: 'ready_for_review'})})};
    }
    if (method === 'POST' && url === 'api/jobs/9/cancel') {
      return {json: {ok: true, phase: 'cancelled'}};
    }
    return {json: {}};
  });
  await h.app.attach(9);
  await flush();
  const visible_at_review = !h.get('discard').hidden;
  h.ctx.confirm = () => true;
  await h.get('discard').onclick();
  await flush();
  const cancelled = h.calls.some(c => c.method === 'POST' && c.url === 'api/jobs/9/cancel');
  return {visible_at_review, cancelled,
          review_hidden: h.get('review').hidden,
          progress_hidden: h.get('progress').hidden,
          job_id: h.app.state.jobId,
          toast: h.get('toast').textContent};
};

// A done job's review is the re-download view (CR-35): nothing to cancel, so
// the button is not there to press.
scenarios['a_done_reviews_grid_has_no_cancel_search'] = async () => {
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (url === 'api/jobs/9') {
      return {json: POLLRES(JOB({id: 9, phase: 'done', terminal: true}))};
    }
    if (url === 'api/jobs/9/manifest') {
      return {json: MANIFEST({job: JOB({id: 9, phase: 'done', terminal: true})})};
    }
    return {json: {}};
  });
  await h.app.attach(9);
  await flush();
  return {discard_hidden: h.get('discard').hidden};
};

// ---- the term scope + date range ------------------------------------------
// 2026-08-25: [ EN + ZH ] [ ENGLISH ONLY ] [ CHINESE ONLY ] [ MY TERM ONLY ]
// on its own row above the search box, remembered like the mode; and two
// date inputs beside it that are posted with the search and NOT remembered.

const scopeButtons = h => h.get('scopes').children;
const clickScope = (h, label) => {
  const b = scopeButtons(h).find(x => x.textContent.includes(label));
  b.onclick();
};

scenarios['the_scope_and_dates_are_posted_with_the_search'] = async () => {
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === 'api/jobs') return {json: {job_id: 71}};
    if (url === 'api/jobs/71') return {json: POLLRES(JOB({id: 71, phase: 'queued'}))};
    return {json: {}};
  });
  const buttons = scopeButtons(h).map(b => [b.textContent, b.className,
                                            b.getAttribute('aria-pressed')]);
  const note_before = h.get('scopenote').textContent;
  const clear_before = h.get('dateclear').className;
  clickScope(h, 'MY TERM ONLY');
  const lit = scopeButtons(h).map(b => b.className);
  const note_after = h.get('scopenote').textContent;
  h.get('datefrom').value = '2019-01-01';
  h.get('dateto').value = '2019-12-31';
  // the inputs' own change event is what shows [ CLEAR ]
  (h.get('datefrom')._listeners.change || []).forEach(fn => fn());
  const clear_after = h.get('dateclear').className;
  h.get('q').value = 'reef';
  h.get('project').value = 's';
  await h.app.runSearch();
  await flush();
  const post = h.calls.filter(c => c.method === 'POST' && c.url === 'api/jobs')[0];
  // the mode and its ticks are untouched by the scope: they are separate dials
  const mode_lit = modeButtons(h).map(b => b.className);
  h.get('dateclear').onclick();
  return {buttons, note_before, note_after, lit, clear_before, clear_after,
          body: post && post.body, stored: h.store['ytdl.term_scope'],
          mode_lit, ticks: ticked(h),
          cleared: [h.get('datefrom').value, h.get('dateto').value,
                    h.get('dateclear').className]};
};

scenarios['the_scope_comes_back_from_localstorage_and_a_stale_one_does_not'] = async () => {
  const out = {};
  for (const [name, seed] of [['saved', 'zh'], ['stale', 'klingon']]) {
    const h = await boot(async (method, url) => {
      const b = baseline(method, url); if (b) return b;
      if (method === 'POST' && url === 'api/jobs') return {json: {job_id: 72}};
      if (url === 'api/jobs/72') return {json: POLLRES(JOB({id: 72}))};
      return {json: {}};
    }, {'ytdl.term_scope': seed});
    h.get('q').value = 'reef';
    h.get('project').value = 's';
    await h.app.runSearch();
    await flush();
    const post = h.calls.filter(c => c.method === 'POST' && c.url === 'api/jobs')[0];
    out[name] = {posted: post && post.body.term_scope,
                 dates: post && [post.body.date_from, post.body.date_to],
                 lit: scopeButtons(h).map(b => b.className)};
  }
  return out;
};

scenarios['the_scope_and_dates_show_on_the_running_job_and_the_recent_views'] = async () => {
  const recent = [
    {id: 54, kind: 'search', term: 'reef', project_label: '2026/FF5/Energy',
     phase: 'done', created_at: '2026-08-25T09:00:00', mode: 'visuals',
     term_scope: 'zh', date_from: '20190101', date_to: '20191231',
     shot_types: ['aerial']},
    {id: 55, kind: 'search', term: 'wind', project_label: '2026/FF5/Energy',
     phase: 'done', created_at: '2026-08-25T09:10:00', mode: 'visuals',
     term_scope: 'exact', date_from: null, date_to: '20200101',
     shot_types: ['aerial']},
    // the default scope and no range claim nothing: the usual search
    {id: 56, kind: 'search', term: 'lng', project_label: '2026/FF5/Energy',
     phase: 'done', created_at: '2026-08-25T09:20:00', mode: 'visuals',
     term_scope: 'both', date_from: null, date_to: null, shot_types: ['aerial']},
    // a paste has none of it, whatever the row carries
    {id: 57, kind: 'urls', term: '', project_label: '2026/FF5/Energy',
     phase: 'done', created_at: '2026-08-25T09:30:00', mode: 'visuals',
     term_scope: 'en'},
    // a row from before the columns existed claims nothing at all
    {id: 58, kind: 'search', term: 'solar', project_label: '2026/FF5/Energy',
     phase: 'done', created_at: '2026-08-25T09:40:00', shot_types: ['aerial']},
  ];
  const running = JOB({id: 54, phase: 'searching', mode: 'visuals',
                       term_scope: 'en', date_from: '20190101', date_to: null,
                       terms_total: 4, terms_done: 2});
  const manifest = MANIFEST({
    job: JOB({id: 54, phase: 'ready_for_review', mode: 'news',
              term_scope: 'exact', date_from: '20190101', date_to: '20191231',
              shot_types: ['interview', 'news'], max_candidates: 100}),
    videos: [VIDEO('LLLLLLLLLLL')],
    terms: [{id: 1, term: 'reef', lang: 'en', english_gloss: null,
             source: 'user', hits: 1, videos: 1}],
    counts: {relevant: 1, duplicates: 0, irrelevant: 0},
  });
  const h = await boot(async (method, url) => {
    if (url.startsWith('api/jobs?')) return {json: {jobs: recent}};
    const b = baseline(method, url); if (b) return b;
    if (url.startsWith('api/jobs/54/manifest')) return {json: manifest};
    if (url === 'api/jobs/54') return {json: POLLRES(running)};
    return {json: {}};
  });
  await h.app.attach(54);
  await flush();
  const ticker = h.get('ticker').textContent;
  await h.app.loadManifest(54);
  await flush();
  return {ticker, jobshots: h.get('jobshots').textContent,
          rows: h.get('recentlist').byClass('recentrow')
                 .map(r => r.byClass('scopesum').map(m => m.textContent).join(' | '))};
};

// ---- the evidence pips + the retry button (WP5/WP6, 2026-08-26) -----------
// CR-80: the strip was green all day while nothing could download, because
// every pip reported configuration. These scenarios are about what the strip
// says when the server tells it what actually happened -- and, just as much,
// about what it says when the server is too old to tell it anything.

const pips = h => ['health', 'healthytdlp', 'healthpot', 'healthdl', 'healthcanary']
  .map(id => ({id, text: h.get(id).textContent, cls: h.get(id).className,
               hidden: h.get(id).hidden, title: h.get(id).title}));

// A health payload with the whole WP5 contract on it.
const HEALTH5 = (over = {}) => Object.assign({
  claude: 'ok', claude_detail: '', yt_dlp: 'ok', worker_alive: true,
  cookies: false, yt_dlp_version: '2026.08.19', cookies_state: 'empty',
  pot_provider: 'ok',
  paths: {anonymous: {ok: true, error: '', at: Math.round(Date.now() / 1000) - 720,
                      video_id: 'AAAAAAAAAA1', source: 'download'}},
  last_download: {ok: true, error: '', at: Math.round(Date.now() / 1000) - 720,
                  video_id: 'AAAAAAAAAA1', source: 'download', path: 'anonymous'},
  canary: {enabled: false, last: null},
}, over);

scenarios['the_strip_reports_evidence_when_the_server_sends_it'] = async () => {
  const h = await boot(async (method, url) => {
    if (url.startsWith('api/health')) return {json: HEALTH5()};
    const b = baseline(method, url); if (b) return b;
    return {json: {}};
  });
  await flush();
  return {pips: pips(h)};
};

scenarios['a_broken_path_and_a_dead_sidecar_are_red'] = async () => {
  const h = await boot(async (method, url) => {
    if (url.startsWith('api/health')) {
      return {json: HEALTH5({
        pot_provider: 'unreachable',
        cookies_state: 'present',
        last_download: {ok: false, error: 'The page needs to be reloaded.',
                        at: Math.round(Date.now() / 1000) - 7200,
                        video_id: 'AAAAAAAAAA1', source: 'download',
                        path: 'cookies'},
        canary: {enabled: true, last: {ok: false, error: 'HTTP Error 403',
                                       at: Math.round(Date.now() / 1000) - 300,
                                       video_id: 'AAAAAAAAAA2',
                                       source: 'canary', path: 'anonymous'}},
      })};
    }
    const b = baseline(method, url); if (b) return b;
    return {json: {}};
  });
  await flush();
  return {pips: pips(h)};
};

// An unconfigured sidecar is not a fault, and a canary nobody enabled is not a
// pip: neither is something an editor can act on.
scenarios['the_quiet_states_are_grey_or_absent'] = async () => {
  const h = await boot(async (method, url) => {
    if (url.startsWith('api/health')) {
      return {json: HEALTH5({pot_provider: 'unconfigured', cookies_state: 'none',
                             last_download: null})};
    }
    const b = baseline(method, url); if (b) return b;
    return {json: {}};
  });
  await flush();
  return {pips: pips(h)};
};

// THE degradation test: baseline() is the pre-WP5 payload, key for key.
scenarios['a_server_without_the_new_keys_paints_the_old_strip'] = async () => {
  const h = await boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    return {json: {}};
  });
  await flush();
  return {pips: pips(h)};
};

// ---- WP6: the retry ------------------------------------------------------
// `job` is what api/jobs/95 and its manifest both report; `videos` are the
// manifest's rows (a `failed` job never fetches one -- poll() skips the
// manifest for that phase -- which is exactly why the count has a fallback).
function retryPage(job, videos, opts) {
  const {downloadStatus, downloadDetail} = opts || {};
  return boot(async (method, url) => {
    const b = baseline(method, url); if (b) return b;
    if (method === 'POST' && url === 'api/jobs/95/download') {
      return downloadStatus
        ? {status: downloadStatus, json: {detail: downloadDetail}}
        : {json: {ok: true}};
    }
    if (url === 'api/jobs/95') return {json: POLLRES(job)};
    if (url.startsWith('api/jobs/95/manifest')) {
      return {json: MANIFEST({job, videos: videos || []})};
    }
    return {json: {}};
  });
}

const retryView = h => ({
  label: h.get('dlretry').textContent,
  hidden: h.get('dlretry').hidden,
  note: h.get('dlnote').textContent,
  note_hidden: h.get('dlnote').hidden,
  panel_hidden: h.get('downloads').hidden,
});

scenarios['a_done_job_with_failures_can_be_retried'] = async () => {
  const job = JOB({id: 95, phase: 'done', terminal: true, kind: 'urls',
                   dl_total: 3, dl_done: 1, dl_failed: 2});
  const h = await retryPage(job, [
    VIDEO('AAAAAAAAAA1', {dl_state: 'done'}),
    VIDEO('AAAAAAAAAA2', {dl_state: 'failed', dl_error: 'The page needs to be reloaded.'}),
    VIDEO('AAAAAAAAAA3', {dl_state: 'failed', dl_error: 'The page needs to be reloaded.'}),
  ]);
  await h.app.attach(95);
  await flush();
  const before = retryView(h);
  await h.get('dlretry').onclick();
  await flush();
  return {before, after: retryView(h), toast: h.get('toast').textContent,
          posts: h.calls.filter(c => c.method === 'POST').map(c => c.url)};
};

// The count is the manifest's when the poll has not carried one: a page
// refreshed onto a terminal job renders before dl_failed is in hand.
scenarios['the_count_falls_back_to_the_manifest_rows'] = async () => {
  const job = JOB({id: 95, phase: 'done', terminal: true, kind: 'urls',
                   dl_total: 2, dl_done: 1, dl_failed: 0});
  const h = await retryPage(job, [
    VIDEO('AAAAAAAAAA1', {dl_state: 'done'}),
    VIDEO('AAAAAAAAAA2', {dl_state: 'failed', dl_error: 'HTTP Error 403'}),
  ]);
  await h.app.attach(95);
  await flush();
  return retryView(h);
};

// The download-phase circuit breaker parks the job in `failed` with an
// instruction on it. That sentence is the reason the button below it is worth
// pressing (or is not), so it is repeated where the decision is made.
scenarios['a_parked_job_shows_the_breakers_note_above_the_button'] = async () => {
  const job = JOB({id: 95, phase: 'failed', terminal: true, kind: 'urls',
                   dl_total: 30, dl_done: 1, dl_failed: 5,
                   error: 'stopped after 5 clips failed the same way: the '
                          + 'signed-in session is being refused. An admin can '
                          + 'clear the cookie jar and retry.'});
  const h = await retryPage(job, null);
  await h.app.attach(95);
  await flush();
  return retryView(h);
};

scenarios['a_failed_job_with_no_downloads_is_offered_nothing'] = async () => {
  const job = JOB({id: 95, phase: 'failed', terminal: true,
                   dl_total: 0, dl_done: 0, dl_failed: 0,
                   error: 'claude_auth: no provider'});
  const h = await retryPage(job, null);
  await h.app.attach(95);
  await flush();
  return retryView(h);
};

scenarios['a_refused_retry_is_said_out_loud'] = async () => {
  const job = JOB({id: 95, phase: 'failed', terminal: true, kind: 'urls',
                   dl_total: 3, dl_done: 0, dl_failed: 3, error: 'parked'});
  const h = await retryPage(job, null,
                            {downloadStatus: 409,
                             downloadDetail: 'this job has nothing to download'});
  await h.app.attach(95);
  await flush();
  await h.get('dlretry').onclick();
  await flush();
  return {toast: h.get('toast').textContent,
          disabled: h.get('dlretry').disabled,
          hidden: h.get('dlretry').hidden};
};

// ---- run them -----------------------------------------------------------
(async () => {
  const out = {};
  for (const [name, fn] of Object.entries(scenarios)) {
    try { out[name] = await fn(); }
    catch (e) { out[name] = {harness_error: String(e && e.stack || e)}; }
  }
  process.stdout.write(JSON.stringify(out));
})();
"""


@pytest.fixture(scope='module')
def spa(tmp_path_factory):
    """Every scenario's result, from one node run (booting app.js is ~ms)."""
    if not NODE:
        pytest.skip('node is not installed; the source assertions still run')
    harness = tmp_path_factory.mktemp('spa') / 'harness.cjs'
    harness.write_text(HARNESS, encoding='utf-8')
    # encoding='utf-8' is not optional: node writes UTF-8, Windows decodes
    # subprocess output as cp1252 by default, and a shot-type label carrying a
    # '·' then arrives as 'Â·' -- a test failure with no bug behind it.
    proc = subprocess.run([NODE, str(harness), str(APP_JS), str(STATIC / 'index.html')],
                          capture_output=True, text=True, encoding='utf-8',
                          timeout=120)
    assert proc.returncode == 0, f'harness failed:\n{proc.stderr}'
    # node exits 0 and silent if a scenario's promise never settles, which is
    # its own kind of bug report -- say so rather than dying in json.loads.
    assert proc.stdout.strip(), f'the harness settled nothing:\n{proc.stderr}'
    data = json.loads(proc.stdout)
    for name, result in data.items():
        assert 'harness_error' not in result, f'{name}: {result["harness_error"]}'
    return data


# ------------------------------------------------------------------ YTDL-8
def test_a_refused_search_re_attaches_to_the_job_it_was_refused_against(spa):
    """SEARCH used to detach BEFORE the POST was validated: the server 409'd,
    the progress panel was already gone, and the running job was invisible
    until the editor guessed to click it in Recent searches."""
    r = spa['refused_search_reattaches']
    assert r['job_id'] == 77, r
    assert r['progress_hidden'] is False
    assert 'already have a job' in r['toast']
    assert r['go_disabled'] is False        # and the button came back


# ---------------------------------------------- the parked-review way out
def test_a_blocked_search_can_discard_the_undownloaded_review_and_go(spa):
    """Owner, 2026-08-24: one job per editor, so a search nobody downloaded
    from blocked every later search until the editor found the small
    [ CANCEL ] on the progress strip. ready_for_review is the one non-terminal
    phase with nothing in flight, so the refused search may offer to cancel it
    and re-send itself."""
    r = spa['blocked_search_offers_discard_and_retries']
    assert r['cancel_calls'] == 1, r
    assert r['posts'] == 2, 'the refused payload was not re-sent'
    assert r['job_id'] == 88, 'the page did not attach the NEW job'
    assert r['polling'] is True
    assert r['go_disabled'] is False


def test_declining_the_discard_keeps_the_parked_review(spa):
    r = spa['declining_the_discard_keeps_the_parked_review']
    assert r['cancels'] == 0, 'declining the confirm must cancel nothing'
    assert r['job_id'] == 77, 'the old re-attach behaviour must survive a decline'
    assert 'CANCEL SEARCH' in r['toast']


def test_a_blocked_paste_gets_the_same_discard_offer(spa):
    r = spa['blocked_paste_offers_discard_and_retries']
    assert r['cancel_calls'] == 1, r
    assert r['posts'] == 2
    assert r['job_id'] == 90
    assert r['golinks_disabled'] is False


def test_the_review_itself_offers_cancel_search_and_clears_the_page(spa):
    """The review header's [ CANCEL SEARCH ]: same cancel as the progress
    strip, but where the editor is looking, and the page is cleared after --
    a cancelled review left on screen reads as a cancel that did not work."""
    r = spa['review_offers_cancel_search_and_clears_the_page']
    assert r['visible_at_review'] is True, 'the button must show on a parked review'
    assert r['cancelled'] is True
    assert r['review_hidden'] is True and r['progress_hidden'] is True
    assert r['job_id'] is None
    assert 'cancelled' in r['toast']


def test_a_done_reviews_grid_has_no_cancel_search_button(spa):
    """A done job's review is the re-download view (CR-35): nothing to cancel."""
    assert spa['a_done_reviews_grid_has_no_cancel_search']['discard_hidden'] is True


def test_a_failed_search_leaves_the_running_job_attached(spa):
    r = spa['failed_search_keeps_the_live_job']
    assert r['job_id'] == 5, r
    assert r['progress_hidden'] is False
    assert r['polling'] is True, 'the live job stopped polling on someone else\'s error'


# ----------------------------------------------------------------- YTDL-25
def test_the_search_button_is_disabled_while_the_post_is_in_flight(spa):
    """A double-click created two active jobs; the orphaned first one then
    409'd every later search naming a job_id the SPA was not tracking."""
    r = spa['go_is_disabled_while_posting']
    assert r['disabled_during'] is True
    assert r['posts'] == 1, f"{r['posts']} jobs created by a double-click"
    assert r['disabled_after'] is False


# ------------------------------------------------------------------ YTDL-9
def test_a_stale_terminal_poll_response_cannot_kill_the_new_jobs_loop(spa):
    """The one that froze the page: job A's slow final poll landed after job C
    attached, ran stopPolling() and returned without rescheduling."""
    r = spa['stale_terminal_response_cannot_kill_the_new_loop']
    assert r['job_id'] == 3, r
    assert r['armed_before'] is True
    assert r['still_polling'] is True, 'the stale response cleared the new timer'
    assert r['manifest_videos'] == 0, "job A's manifest rendered over job C"
    assert r['review_hidden'] is True


# ----------------------------------------------------------------- YTDL-10
def test_a_401_stops_polling_and_says_the_session_expired(spa):
    r = spa['session_expiry_stops_the_poll']
    assert r['polling'] is False, 'still retrying a 401 every 5 s'
    keys = [b[0] for b in r['banners']]
    assert 'session' in keys, r['banners']
    assert 'expired' in r['text'], r['text']


# ----------------------------------------------------------------- YTDL-34
def test_a_blip_on_the_terminal_manifest_fetch_retries(spa):
    """Polling has already stopped at that tick, so without a retry the editor
    gets a full green bar, no review grid and no way back but a refresh."""
    r = spa['terminal_manifest_blip_retries']
    assert r['retrying'] is True, 'no retry armed after the manifest fetch failed'
    assert r['review_hidden'] is False
    assert r['cards'] == 1
    assert r['manifests'] == 2


# -------------------------------------------------------------- YTDL-11/37
def test_health_timeout_warns_and_does_not_erase_the_projects_warning(spa):
    r = spa['banner_slots_are_independent']
    keys = [b[0] for b in r['banners']]
    assert 'health' in keys and 'projects' in keys, r['banners']
    assert len(r['warns']) == 2, r['warns']
    assert 'did not answer in time' in r['text'], r['text']
    assert 'no projects ticked' in r['text'].lower(), r['text']
    assert r['go_disabled'] is True


# ----------------------------------------------------------------- YTDL-12
def test_a_failed_jobs_banner_does_not_survive_into_the_next_job(spa):
    r = spa['job_error_banner_is_cleared_by_the_next_job']
    # "The AI provider did not answer in time" since 2026-08-18: there are
    # five possible backends now, so the hint text stopped naming one.
    assert 'did not answer in time' in r['after_failure'], r
    assert r['after_retry'] == '', r['after_retry']


# ----------------------------------------------------------------- YTDL-39
def test_a_dead_worker_is_warned_about_from_the_poll_response(spa):
    r = spa['dead_worker_is_reported']
    assert 'worker is not running' in r['text'], r['text']
    assert r['intervals'] >= 1, 'health is never re-fetched after page load'


# ----------------------------------------------------------------- YTDL-36
def test_a_cancel_mid_download_still_shows_which_clips_landed(spa):
    r = spa['cancelled_mid_download_keeps_the_list']
    assert r['downloads_hidden'] is False, 'the per-video list was replaced by a red bar'
    assert r['progress_hidden'] is True
    assert r['rows'] == 2


# ----------------------------------------------------------------- YTDL-33
def test_rapid_selection_toggles_end_with_the_ui_agreeing_with_the_server(spa):
    """Unserialised, the LAST RESPONSE won in the browser while the LAST
    REQUEST won in the database -- and DOWNLOAD takes what the database says."""
    r = spa['rapid_toggles_are_serialised']
    assert r['order'] == [True, False], r['order']
    assert r['optimistic'] == 1, 'the card did not follow the click'
    assert r['final'] == 0, 'UI and server disagree after a check/uncheck'
    assert '0 selected' in r['foot'], r['foot']


# ----------------------------------------------------------------- YTDL-38
def test_term_chip_counts_agree_with_the_visible_grid(spa):
    r = spa['chip_counts_match_the_grid']
    assert r['chipCounts'] == ['1', '1', '0'], r['chipCounts']   # all terms, reef, algae
    assert r['cards_for_filtered_term'] == 0
    assert r['empty_state'] and 'filtered out' in r['empty_state'][0], r['empty_state']


# ----------------------------------------------------------------- YTDL-35
def test_a_server_detail_reaches_the_toast_as_text_not_markup(spa):
    r = spa['toast_does_not_parse_html']
    assert '<img' in r['text'], r          # shown verbatim to the editor
    assert r['html_children'] == ['div'], r['html_children']
    assert '<img' not in r['raw'], 'the detail was assigned as innerHTML'


# ------------------------------------------------------- the paste-links box
def test_the_picker_tells_the_server_which_computer_is_asking(spa):
    """CR-72 follow-up (2026-08-31), the client half; owner: "I can still only
    select /animals as a destination on the base rig".

    The server has taken a `machine` since 2026-08-30, and `_wired` answers
    for that machine alone -- but nothing sent one, because a page served from
    the NAS knows the person and never the computer. The companion's
    /ytdl/capabilities now names it, and boot asks once.

    The three negative cases matter as much as the positive one: no companion,
    a companion too old for the field, and the fleet flag off must all send
    the request an older SPA sent, because the server reads a missing
    `machine` as "unknown", and unknown is not wired.
    """
    r = spa['the_picker_says_which_computer_is_asking']
    assert any('machine=owen-rig' in u for u in r['named']), r['named']
    assert all('machine=' not in u for u in r['none']), r['none']
    assert all('machine=' not in u for u in r['old']), r['old']
    assert all('machine=' not in u for u in r['off']), r['off']
    # ...and with the feature off the page did not so much as look at 8899.
    assert r['off_loopback'] == 0, r['off_loopback']


def test_pasting_links_posts_the_whole_form_and_attaches_the_job(spa):
    """The form is the LINKS and the shared destination pickers, plus the
    2026-08-30 folder box and the CR-72 follow-up's `local` flag -- an empty
    folder box (this scenario never touches it) still posts '', which is a
    paste's clips going into the project's Youtube root, exactly as every
    paste has since 2026-08-11."""
    r = spa['pasted_links_start_a_job']
    assert r['job_id'] == 21, r
    assert r['body'] == {'urls': 'https://youtu.be/JJJJJJJJJJJ \n https://youtu.be/IIIIIIIIIII',
                         'project_slug': 's', 'quality': '1080p', 'folder': '',
                         'local': False}, r['body']
    assert r['progress_hidden'] is False
    # the ledger's answer is not silent: it is why 2 links fetched 1 clip
    assert 'already in the tree' in r['toast'], r['toast']
    assert r['disabled_after'] is False


def test_the_links_button_is_disabled_while_its_post_is_in_flight(spa):
    """The same guard SEARCH got for YTDL-25: a double-click on a paste would
    lose the race against the one-active-job index and 409 itself."""
    r = spa['links_button_is_disabled_while_posting']
    assert r['disabled_during'] is True
    assert r['posts'] == 1, f"{r['posts']} jobs created by a double-click"
    assert r['disabled_after'] is False


def test_a_refused_paste_re_attaches_to_the_job_it_was_refused_against(spa):
    r = spa['refused_paste_reattaches']
    assert r['job_id'] == 23, r
    assert r['progress_hidden'] is False
    assert 'already have a job' in r['toast']
    assert r['polling'] is True


def test_a_url_job_renders_its_downloads_and_no_review_grid(spa):
    """The rows still have to render (renderDownloads reads state.manifest), so
    the branch returns AFTER storing it -- and the identical search job proves
    the grid is being withheld rather than merely never reached."""
    r = spa['a_url_job_shows_downloads_not_a_review_grid']
    assert r['review_hidden'] is True, 'a url job offered a selection to review'
    assert r['downloads_hidden'] is False
    assert r['rows'] == 2, r
    assert any('already downloaded' in t for t in r['row_text']), r['row_text']
    assert r['search_review_hidden'] is False, r
    assert r['search_cards'] == 2, r


# ---------------------------------------------------------- the download bar
def test_the_bar_advances_while_a_single_video_is_still_downloading(spa):
    """The pasted-link case, which is one video per job: the bar counted
    COMPLETED videos, so it sat at 0% for the whole download and read as hung
    while the row beside it happily printed '40%'."""
    r = spa['the_bar_moves_inside_a_single_video']
    assert r['width'] == '40%', r
    assert r['ticker'].startswith('0/1 downloaded'), r['ticker']
    assert any('40%' in t for t in r['rows']), r['rows']


def test_a_video_that_is_merging_is_not_added_to_the_bar_twice(spa):
    """A live entry lingers at percent 100 / 'merging' AFTER dl_done has
    counted that video. Summing the map blindly makes that 110% -- a full bar
    with half the job still to fetch."""
    r = spa['a_merging_video_is_not_counted_twice']
    assert r['width'] == '60%', r        # (1 done + 0.2 in flight) of 2
    assert len(r['rows']) == 2, r['rows']


def test_the_bar_reads_the_live_map_when_no_manifest_has_landed_yet(spa):
    """A refresh mid-download: with no dl_state to read, only the live map's
    own 'downloading' status separates the video still arriving from the one
    already counted."""
    r = spa['the_bar_falls_back_to_the_live_map']
    assert r['manifest'] is None, 'the scenario did not exercise the fallback'
    assert r['width'] == '75%', r        # (1 done + 0.5 in flight) of 2
    assert len(r['rows']) == 2, r['rows']
    assert r['thumbs'] == [
        'https://i.ytimg.com/vi/SSSSSSSSSSS/mqdefault.jpg',
        'https://i.ytimg.com/vi/TTTTTTTTTTT/mqdefault.jpg'], r['thumbs']


def test_every_download_row_shows_a_thumbnail(spa):
    """Both halves: a search job has a stored thumbnail, and a url job never
    ran an enrich phase so `thumbnail` is NULL for every pasted link -- the
    id-only ytimg fallback is the only picture there can be."""
    r = spa['thumbnails_on_the_download_rows']
    assert r['search_thumbs'] == [
        'https://i.ytimg.com/vi/UUUUUUUUUUU/hqdefault.jpg',
        'https://i.ytimg.com/vi/VVVVVVVVVVV/mqdefault.jpg'], r['search_thumbs']
    assert r['url_thumbs'] == [
        'https://i.ytimg.com/vi/WWWWWWWWWWW/mqdefault.jpg'], r['url_thumbs']
    # ...and the review card, which is where the trick came from, still has its
    assert r['card_thumbs'] == [
        'https://i.ytimg.com/vi/XXXXXXXXXXX/mqdefault.jpg',
        'https://i.ytimg.com/vi/UUUUUUUUUUU/hqdefault.jpg'], r['card_thumbs']


# ------------------------------------------------------- the shot-type boxes
def test_the_boxes_start_on_the_documented_defaults_and_post_what_is_ticked(spa):
    r = spa['shot_type_boxes_post_what_is_ticked']
    assert r['initial'] == [['aerial', True], ['establishing', True],
                            ['walkthrough', True], ['timelapse', True],
                            ['event', True], ['raw', True],
                            ['interview', False], ['news', False],
                            ['commentary', False]], r['initial']
    assert r['body']['shot_types'] == ['aerial', 'establishing', 'walkthrough',
                                       'timelapse', 'event', 'interview'], r['body']
    # ...as part of the same submit, not a second request
    assert r['body']['term'] == 'reef' and r['body']['project_slug'] == 's'
    # the boxes are labelled, and grouped so nine of them do not read as a wall
    assert 'Aerial / drone' in r['labels'] and 'News reports' in r['labels']
    assert 'shots of it:' in r['labels'] and 'also keep:' in r['labels']
    assert r['note'] == '', 'a normal selection needs no note'


def test_the_ticks_are_remembered_between_visits(spa):
    """Per browser, not per job: an editor cutting one film ticks the same
    boxes all week."""
    r = spa['shot_type_boxes_post_what_is_ticked']
    assert json.loads(r['stored']) == ['aerial', 'establishing', 'walkthrough',
                                       'timelapse', 'event', 'interview']

    back = spa['shot_types_come_back_from_localstorage']
    assert back['ticked'] == ['aerial', 'interview'], back
    # a key this build no longer has is dropped rather than posted: the server
    # refuses unknown keys and would fail the whole search over it
    assert back['posted'] == ['aerial', 'interview'], back


def test_both_degenerate_selections_are_explained_rather_than_left_to_surprise(spa):
    r = spa['the_degenerate_selections_say_so']
    assert r['none']['posted'] == []
    assert 'no bias' in r['none']['note'], r['none']['note']
    assert json.loads(r['none']['stored']) == []
    assert r['all_posted'] == 9
    assert 'no bias' in r['all_note'], r['all_note']
    assert r['some_note'] == '', 'a normal selection is not annotated'


def test_a_finished_search_still_says_what_it_was_run_with(spa):
    """The header shows what the editor has ticked NOW; a week-old manifest has
    to show what it was actually searched and filtered with."""
    r = spa['the_selection_shows_on_the_job_and_recent_views']
    assert r['jobshots'] == 'shot types: Aerial / drone · Raw / uncut / no commentary', r
    # recent rows: a search shows its selection compactly, one that ticked
    # nothing says so, and a paste (never searched) shows none at all
    assert r['rows'] == ['aerial+raw', '', 'no shot-type filter'], r['rows']


# ---------------------------------------------------------- the search mode
def test_the_toggle_offers_two_modes_and_presets_the_boxes(spa):
    """The owner's ask, 2026-08-18: a montage made OF the reporting wants clips
    whose AUDIO carries the story, which is the opposite selection from b-roll
    to cut under a narrator. Choosing the mode does the ticking; the editor
    still adjusts it afterwards."""
    r = spa['the_mode_presets_the_boxes_and_is_posted']
    assert [b[0] for b in r['buttons']] == ['[ VISUALS ]', '[ NEWS MONTAGE ]'], r
    assert r['buttons'][0][1] == 'modebtn on' and r['buttons'][1][1] == 'modebtn'
    assert [b[2] for b in r['buttons']] == ['true', 'false'], 'announced state'
    assert r['visuals_ticks'] == ['aerial', 'establishing', 'walkthrough',
                                  'timelapse', 'event', 'raw'], r
    assert r['news_ticks'] == ['interview', 'news', 'commentary'], r
    assert r['news_buttons'] == ['modebtn', 'modebtn on'], r
    # ...and the whole thing is ONE submit: mode and the adjusted boxes
    assert r['body']['mode'] == 'news', r['body']
    assert r['body']['shot_types'] == ['aerial', 'interview', 'news',
                                       'commentary'], r['body']


def test_the_ticks_are_remembered_per_mode(spa):
    """The boxes mean different things in the two modes, so tuning one must not
    re-tune the other -- and `visuals` keeps the ORIGINAL localStorage key, so
    the ticks every editor already has survive this build."""
    r = spa['the_mode_presets_the_boxes_and_is_posted']
    assert r['stored_mode'] == 'news', r
    assert json.loads(r['stored_news']) == ['aerial', 'interview', 'news',
                                            'commentary'], r
    # absent, not empty: nothing wrote the visuals key at all (an undefined
    # value does not survive the harness's JSON hop, which is the assertion)
    assert r.get('stored_visuals') is None, 'the visuals ticks were touched'
    # switching back restores what visuals was left on, not the news selection
    assert r['back'] == ['aerial', 'establishing', 'walkthrough', 'timelapse',
                         'event', 'raw'], r

    back = spa['the_mode_and_its_ticks_come_back_from_localstorage']
    assert back['start'] == ['aerial', 'news'], back
    assert back['posted']['mode'] == 'news', back
    assert back['posted']['shot_types'] == ['aerial', 'news'], back
    assert back['lit'] == ['modebtn', 'modebtn on'], back


def test_a_stale_mode_is_never_posted(spa):
    """The server refuses a mode it does not know rather than reading it as the
    default, so a value this build no longer offers would 400 every search from
    this browser."""
    r = spa['a_stale_mode_falls_back_to_the_default']
    assert r['posted'] == 'visuals', r
    assert r['ticks'][0] == 'aerial' and 'interview' not in r['ticks'], r


def test_every_view_of_a_job_says_which_mode_it_ran_under(spa):
    r = spa['the_mode_shows_on_the_running_job_and_the_recent_views']
    assert r['ticker'].startswith('mode: news montage'), r['ticker']
    assert r['jobshots'].startswith('mode: news montage · shot types: '), r
    # a search says its mode, a paste has none (never searched), and a row from
    # before the column claims nothing
    assert r['rows'] == ['news montage', 'visuals', '', ''], r['rows']


# --------------------------------------------- the candidate-limit dropdown
def test_the_limit_dropdown_offers_the_menu_and_defaults_to_100(spa):
    """100 because 112 rapid metadata calls is the only measured point at which
    YouTube has cut this NAS off (2026-08-11) -- a normal search sits just under
    the one threshold in evidence."""
    r = spa['the_candidate_limit_defaults_and_is_posted_with_the_search']
    assert r['initial'] == '100', r
    assert r['options'] == [['50', '50 candidates'], ['100', '100 candidates'],
                            ['200', '200 candidates'], ['400', '400 candidates']], r
    # ...as part of the same submit, not a second request
    assert r['body']['max_candidates'] == 100, r['body']
    assert r['body']['term'] == 'reef' and r['body']['project_slug'] == 's'


def test_the_chosen_limit_is_posted_and_remembered_between_visits(spa):
    """Per browser, like the shot ticks: the editor who needs 400 for a thin
    topic needs it all afternoon."""
    r = spa['a_changed_candidate_limit_is_posted_and_remembered']
    assert r['posted'] == 400, r
    assert r['stored'] == '400', r

    back = spa['the_candidate_limit_comes_back_from_localstorage']
    assert back['value'] == '200' and back['posted'] == 200, back


def test_a_stale_or_junk_limit_is_never_posted(spa):
    """The server refuses a number it does not know rather than clamping it, so
    a value this build no longer offers would 400 every search from this
    browser until localStorage was cleared by hand."""
    r = spa['a_stale_candidate_limit_falls_back_to_the_default']
    assert r['value'] == '100', r
    assert r['posted'] == 100, r


def test_a_finished_search_says_what_limit_it_ran_under(spa):
    r = spa['the_candidate_limit_shows_on_the_job_and_recent_views']
    assert r['jobshots'] == 'shot types: Aerial / drone · up to 400 candidates', r
    # a search shows its ceiling, a paste (never searched) shows none, and a
    # row from before the column existed claims nothing
    assert r['rows'] == ['max 400', '', ''], r['rows']


# ------------------------------------------------------ the destination picker
def test_the_picked_project_is_remembered_between_visits(spa):
    """It had no memory at all, so every load put it back on whatever the
    server listed first. Live, 2026-08-14: 16 term folders meant for
    2026/FF5/Energy Transition landed in 2026/CCT/Creator Profiles/Season 1."""
    r = spa['picking_a_project_remembers_it']
    assert r['wired'] is True, 'nothing is listening for a change of project'
    assert r['stored'] == 'ff5-energy', r
    # ...and the list itself is still the server's, in the server's order
    assert r['options'] == [['cct-s1', '2026/CCT/Creator Profiles/Season 1'],
                            ['ff5-nuclear', '2026/FF5/Nuclear'],
                            ['ff5-energy', '2026/FF5/Energy Transition']], r


def test_the_remembered_project_is_restored_and_reaches_the_post(spa):
    """Restoring the DOM value is only half of it: the submit path reads
    `$('#project').value`, so the restore has to be what the job is created
    with, not a cosmetic selection."""
    r = spa['the_remembered_project_comes_back_and_is_posted']
    assert r['restored'] == 'ff5-energy', r
    assert r['posted'] == 'ff5-energy', r


def test_a_remembered_project_that_is_no_longer_offered_is_not_restored(spa):
    """localStorage outlives a dashboard tick: assigning a <select> a value
    none of its options carry selects NOTHING in some browsers, which would
    leave runSearch with an empty slug and refuse every search."""
    r = spa['a_project_that_is_gone_falls_back_silently']
    assert r['value'] != 'deleted-last-month', r
    # the harness's <select> has no implicit first-option default, so "left
    # alone" reads as '' here -- in a browser that IS the first option, i.e.
    # exactly the behaviour this picker had before 2026-08-14
    assert r['value'] == '', r
    assert r['options'] == ['cct-s1', 'ff5-nuclear', 'ff5-energy'], \
        'the fallback came from an empty list, not a real one'
    # silently: a stale key is not the editor's problem to be warned about, and
    # the page still works
    assert r['banners'] == [], r['banners']
    assert r['go_disabled'] is False, r


# ------------------------------------------------------ the download history
def test_the_history_lists_the_ledger_with_a_thumbnail_and_a_destination(spa):
    """"once a video is downloaded we need a history like the original youtube
    download utility which shows thumbnails, titles, and allows the user to open
    in folder by clicking on it" (owner, 2026-08-11)."""
    r = spa['history_lists_the_ledger_and_opens_a_folder']
    assert len(r['rows']) == 3, r['rows']
    # the stored thumbnail when there is one, the id-only ytimg fallback when
    # there is not -- which is every pasted link, since a url job never enriches
    assert r['thumbs'] == [
        'https://i.ytimg.com/vi/AAAAAAAAAAA/mqdefault.jpg',
        'https://i.ytimg.com/vi/BBBBBBBBBBB/hqdefault.jpg',
        'https://i.ytimg.com/vi/CCCCCCCCCCC/mqdefault.jpg'], r['thumbs']
    # title, destination, who -- and a hostile title arrives as TEXT (YTDL-35):
    # these come from YouTube, so they are strings somebody else chose
    assert r['titles'][1] == '<img src=x onerror=alert(1)>', r['titles']
    # the destination, honestly, for BOTH shapes: a search's clip is in a term
    # folder, a pasted one is in the project's Youtube root itself
    assert '2026/FF5/Energy\\Youtube\\algal reef' in r['rows'][0], r['rows'][0]
    assert '2026/FF5/Energy\\Youtube ' in r['rows'][1], r['rows'][1]
    assert 'Youtube\\ ' not in r['rows'][1], 'a dangling separator for the root'
    assert 'sam' in r['rows'][1], r['rows'][1]
    assert '2026-08-11 09:30' in r['rows'][0], r['rows'][0]
    assert r['note'].startswith('showing 3 of 3'), r['note']
    assert r['more_hidden'] is True


def test_clicking_a_history_row_asks_the_companion_to_open_the_folder(spa):
    """A browser cannot open a local folder from an http page, so this goes to
    the companion's loopback exactly as b-roll's Send to Resolve does -- with a
    path relative to the PROJECTS ROOT, never an absolute one: the page is
    served from the NAS and only the companion knows where P: is."""
    r = spa['history_lists_the_ledger_and_opens_a_folder']
    assert r['body'] == {
        'rel_path': '2026/FF5/Energy/Youtube/algal reef/Channel [AAAAAAAAAAA].mp4'
    }, r['body']
    assert not r['body']['rel_path'].startswith('/'), r['body']
    assert 'opened the folder' in r['toast'], r['toast']
    # a ledger row with no path recorded is history with nothing to open, and
    # must not pretend to be clickable
    assert r['clickable'] == [True, True, False], r['clickable']
    assert 'nopath' in r['nopath'][2], r['nopath']


def test_no_companion_shows_the_path_instead_of_an_error(spa):
    """The b-roll rule: an absent companion is a message, not a failure. Here it
    also has to be USEFUL -- the editor was going to open that folder, so name
    it and offer to copy it rather than saying "not running" and stopping."""
    r = spa['history_degrades_with_no_companion']
    # 2026-08-12: a rejected fetch is NOT proof the companion is down (a
    # browser local-network block looks identical), so the message may no
    # longer assert "not running" as fact -- it hedges and offers the
    # loopback self-test instead.
    assert 'may not be running' in r['text'], r['text']
    assert '127.0.0.1:8899/status' in r['text'], r['text']
    assert 'Projects\\2026\\FF5\\Energy\\Youtube\\algal reef' in r['text'], r['text']
    assert 'P: on Windows' in r['text'], r['text']    # no drive letter is known
    assert r['button'] is True and '[ COPY PATH ]' in r['label']
    assert r['copied'] == ['Projects\\2026\\FF5\\Energy\\Youtube\\algal reef'], r['copied']
    assert 'copied' in r['after_copy'], r['after_copy']
    assert '<' not in r['raw'], 'the toast was assigned as innerHTML'


def test_a_companion_that_predates_the_route_says_upgrade_not_error(spa):
    """404 from a companion that IS running: an upgrade, and the fleet gets it
    through the dashboard's channel -- nothing the editor can fix by retrying."""
    r = spa['history_says_so_when_the_companion_is_too_old']
    assert 'too old' in r['toast'], r['toast']
    assert 'Youtube\\algal reef' in r['toast'], r['toast']


def test_the_history_is_paged_and_asks_for_the_next_page_by_offset(spa):
    """The ledger is permanent and fleet-wide, so the panel never asks for all
    of it -- and [ OLDER ] appends rather than replacing."""
    r = spa['history_refuses_to_dump_the_whole_ledger']
    assert r['first']['rows'] == 2 and r['first']['more_hidden'] is False
    assert r['first']['note'].startswith('showing 2 of 3'), r['first']['note']
    assert r['urls'] == ['api/downloads?limit=24&offset=0',
                         'api/downloads?limit=24&offset=2'], r['urls']
    assert r['rows'] == 3, 'the second page replaced the first instead of appending'
    assert r['more_hidden'] is True
    assert r['note'].startswith('showing 3 of 3'), r['note']


# ------------------------------------------------ what the page opens on
def test_an_active_job_beats_a_stale_hash_and_rewrites_it(spa):
    """Found live, 2026-08-11: a finished paste job was pinned in `#job=4` while
    a ready_for_review job with 74 relevant clips sat unshown -- and because
    ready_for_review counts as the editor's one ACTIVE job, it was also silently
    409ing every new search they tried, with nothing on screen saying why."""
    r = spa['an_active_job_beats_a_stale_hash']
    assert r['job_id'] == 5, r
    assert r['hash'] == 'job=5', 'the URL still names the job nobody is looking at'
    assert r['review_hidden'] is False, 'the manifest was not shown'
    assert r['polled'] == 0, 'the stale job was attached to as well'


def test_a_terminal_hash_still_deep_links_when_nothing_is_active(spa):
    """Those links are what the Recent searches list writes, and a finished
    job's manifest is a thing people come back to."""
    r = spa['a_terminal_hash_still_deep_links']
    assert r['job_id'] == 4, r
    assert r['hash'] == 'job=4'
    assert r['downloads_hidden'] is False    # a finished paste shows its clips


def test_no_hash_and_no_active_job_attaches_nothing(spa):
    r = spa['no_hash_and_no_active_job_attaches_nothing']
    assert r['job_id'] is None, r
    assert r['hash'] == '' and r['progress_hidden'] is True
    assert r['polling'] is False, 'polling a job that does not exist'


def test_a_server_without_the_active_route_still_honours_the_hash(spa):
    r = spa['a_missing_active_route_falls_back_to_the_hash']
    assert r['job_id'] == 4, r


def test_a_paste_and_leave_is_never_mistaken_for_a_loss(spa):
    """The owner, 2026-08-30: "I just submitted 12 youtube links to be
    downloaded but I clicked away and came back and it seems to have eaten
    them" -- the downloads were fine server-side, only the page came back
    showing nothing. A bare reload (no `#job=`) has to re-ask BOTH halves of
    "what is my downloader doing" -- the running job AND the queue behind it
    -- and show them exactly as they would have looked had the tab stayed
    open, so a paste-and-leave never reads as data loss."""
    r = spa['a_paste_and_leave_still_shows_the_running_job_and_the_queue']
    assert r['job_id'] == 9, r                     # attached to the running job
    assert r['hash'] == 'job=9'
    assert r['progress_hidden'] is True and r['downloads_hidden'] is False, \
        'a downloading job shows its clip list, not the phase bar'
    assert r['queue_hidden'] is False and r['queue_rows'] == 2, \
        'the two jobs still waiting behind it must still be on screen'
    # >= 1, not == 1: loadQueue() is also re-asked once the first poll sees the
    # phase (poll()'s own "seen !== job.phase" rule), which is a second ask of
    # the SAME fresh answer, not a stale one carried over from nowhere.
    assert r['asked_active'] >= 1, 'the active job must be asked for fresh'
    assert r['asked_recent'] == 1, 'the recent list must be asked for fresh too'


def test_a_finished_paste_still_shows_in_recent_on_a_fresh_load(spa):
    """The other half of the same report: by the time he looked, the paste had
    already finished. No active job means nothing to attach to, but the clips
    it landed must still be right there in Recent searches -- no click, no
    hash, nothing remembered from a session that never existed on this tab."""
    r = spa['a_finished_paste_still_shows_in_recent_on_a_fresh_load']
    assert r['job_id'] is None, r        # nothing IS active -- correctly so
    assert '1' in r['recentsum'], r['recentsum']
    assert r['recent_rows'] == 1, r


# ------------------------------------------------------ the collapsible panels
# "there should be a way to collapse the search results that are open" (owner,
# 2026-08-11). ~74 review cards own the page and push Recent searches and the
# download history off the bottom of it.

PANELS = ('review', 'downloads', 'recent', 'history')


def test_every_stacked_panel_folds_away_and_comes_back(spa):
    r = spa['every_stacked_panel_folds_to_its_header']
    # everything open to begin with, and every header says so both ways
    for pid in PANELS:
        assert r['open'][pid]['folded'] is False, (pid, r['open'])
        assert r['open'][pid]['label'].startswith('[-] '), r['open'][pid]
        assert r['open'][pid]['aria'] == 'true', r['open'][pid]
    # ...with something in each of them to fold
    assert r['filled']['cards'] == 3 and r['filled']['rows'] == 1, r['filled']
    assert r['filled']['ledger'] == 2, r['filled']

    for pid in PANELS:
        assert r['folded'][pid]['folded'] is True, (pid, r['folded'])
        assert r['folded'][pid]['label'].startswith('[+] '), r['folded'][pid]
        assert r['folded'][pid]['aria'] == 'false', r['folded'][pid]
    # the title stays in the header: a folded panel still names itself
    assert r['folded']['review']['label'] == '[+] REVIEW', r['folded']['review']
    assert r['folded']['history']['label'] == '[+] DOWNLOAD HISTORY', r['folded']

    assert r['reopened']['folded'] is False, r['reopened']
    assert r['reopened']['aria'] == 'true', r['reopened']
    # and the section is only ever the header + the body, never re-hidden whole
    assert r['review_section_hidden'] is False, r


def test_a_folded_panel_still_says_what_is_in_it(spa):
    """The point of the whole feature: folding hides bulk, not meaning. A
    header that reads "[+] REVIEW" and nothing else is a search result the
    editor has to unfold to find out they already looked at."""
    r = spa['every_stacked_panel_folds_to_its_header']
    assert r['filled']['review'] == '3 clips · 2 selected', r['filled']
    assert r['filled']['recent'] == '1 search', r['filled']
    assert r['filled']['history'] == '7 clips', r['filled']
    # ...and every one of them survives the fold unchanged
    assert r['summaries'] == {'review': '3 clips · 2 selected',
                              'recent': '1 search',
                              'history': '7 clips'}, r['summaries']


def test_a_folded_download_list_still_reports_the_running_job(spa):
    """The downloads panel folds its LIST only. The phase, the counter, the bar
    and [ CANCEL ] are the job talking -- a download in flight must not go
    quiet because its rows were put away."""
    r = spa['a_folded_download_list_still_shows_the_job']
    assert r['rows'] == 2, r
    f = r['folded']
    assert f['list'] is True and f['panel'] is False, f
    assert f['phase'] == 'downloading', f
    assert f['ticker'].startswith('3/7 downloaded'), f
    assert f['cancel_hidden'] is False, 'no way to cancel a folded download'
    assert f['width'] == '50%', f          # (3 done + 0.5 in flight) of 7
    assert f['label'] == '[+] DOWNLOADS', f
    # the next poll tick re-renders the list; it must not unfold it
    assert r['after_a_tick'] is True, 'a poll tick reopened the folded list'
    assert r['ticker_after'].startswith('3/7 downloaded'), r


def test_the_folds_are_remembered_between_visits(spa):
    """Exactly as the shot ticks and the candidate cap are: one key holding the
    ids that are folded."""
    r = spa['folded_panels_come_back_from_localstorage']
    assert r['start']['recent']['folded'] is True, r['start']
    assert r['start']['history']['folded'] is True, r['start']
    assert r['start']['review']['folded'] is False, r['start']
    assert r['start']['recent']['label'] == '[+] RECENT SEARCHES', r['start']
    # written back in table order, whatever order they were clicked in
    assert json.loads(r['stored']) == ['review', 'history'], r['stored']
    assert r['after']['recent']['folded'] is False, r['after']
    assert r['after']['review']['folded'] is True, r['after']


def test_a_stale_or_junk_collapsed_key_is_ignored(spa):
    """localStorage throws outright in some privacy modes and outlives every
    build: an id this one no longer has must be dropped, not kept folding
    nothing."""
    r = spa['a_stale_collapsed_key_is_ignored']
    assert r['unknown']['history']['folded'] is True, r['unknown']
    assert r['unknown']['review']['folded'] is False, r['unknown']
    # 'klingon' is gone from the rewrite rather than carried forever
    assert json.loads(r['rewritten']) == ['recent', 'history'], r['rewritten']
    # junk and the wrong shape both mean "everything open", and neither costs
    # the page: the history behind it still loaded
    for pid in PANELS:
        assert r['junk'][pid]['folded'] is False, (pid, r['junk'])
        assert r['shaped'][pid]['folded'] is False, (pid, r['shaped'])
    assert r['junk_cards'] == 2, r['junk_cards']


def test_a_job_arriving_at_review_opens_a_folded_review_panel(spa):
    """The one behavioural exception. Otherwise an editor folds the grid, runs
    a new search, and watches nothing happen -- which is exactly the "nothing
    is visible for review" this page caused once already (2026-08-11)."""
    r = spa['a_job_arriving_at_review_unfolds_the_panel']
    assert r['before']['review']['folded'] is True, r['before']
    assert r['searching'] is True, 'unfolded before there was anything to review'
    assert r['polls'] >= 2, r['polls']
    a = r['arrived']
    assert a['folded'] is False, 'the review arrived into a folded panel'
    assert a['aria'] == 'true' and a['label'] == '[-] REVIEW', a
    assert a['cards'] == 1 and a['sum'] == '1 clip · 1 selected', a
    # the stored fold goes with it, or the panel re-folds itself next visit
    assert json.loads(a['stored']) == ['recent'], a['stored']
    # and only the review panel: the others are the editor's
    assert a['recent_folded'] is True, a


def test_a_fold_made_after_the_review_arrived_sticks(spa):
    """The force-open is driven by the phase TRANSITION, not by the phase, so
    a re-render (or a re-poll) of the same ready_for_review job cannot keep
    re-opening a panel the editor has just put away."""
    r = spa['a_job_arriving_at_review_unfolds_the_panel']
    assert r['manual']['folded'] is True, r['manual']
    assert json.loads(r['manual']['stored']) == ['review', 'recent'], r['manual']
    assert r['after_another_poll'] is True, 'a re-poll reopened the folded grid'
    assert json.loads(r['stored_at_the_end']) == ['review', 'recent'], r


def test_attaching_to_a_job_already_at_review_leaves_the_fold_alone(spa):
    """"Newly reaches" is the rule: a deep link, a 409 re-attach or a reload of
    a job that was already waiting has not arrived anywhere. The grid is built
    under the fold either way, so opening it is one click and no fetch."""
    r = spa['attaching_to_an_old_review_respects_the_fold']
    f = r['folded']
    assert f['body'] is True, 'a reload undid the editor\'s fold'
    assert f['section'] is False, 'the header went with the grid'
    assert json.loads(f['stored']) == ['review'], f['stored']
    assert f['sum'] == '3 clips · 2 selected', f    # still says what is in there
    assert f['label'] == '[+] REVIEW', f
    assert f['cards'] == 3, 'the grid was not built under the fold'
    assert r['after_unfold'] is False, r
    assert json.loads(r['stored_after']) == [], r['stored_after']


# ------------------------------------------- requester-first downloads (§2/9)
# docs/YTDL_LOCAL_DOWNLOAD.md. Phase 1 is the SPA half: probe the editor's own
# companion, hand it a job id, name the executor. It ships with the server flag
# OFF and reaches a fleet with no companion that answers these routes, so
# "nothing happens" is the behaviour under test far more than "it works".

CAPABILITIES = 'http://127.0.0.1:8899/ytdl/capabilities'
LOCAL_DOWNLOAD = 'http://127.0.0.1:8899/ytdl/download'


def test_with_the_flag_off_the_page_never_looks_at_the_loopback(spa):
    """§10, phase 1: flag off is byte-for-byte the old page. The scenario's
    server answers a capable companion AND reports download_mode=local, so
    every part of this is the flag's doing and nothing else's."""
    r = spa['the_server_flag_gates_the_whole_feature']
    assert r['off'] == [], r['off']
    # ...and the same for a server too old to have the field at all
    assert r['older'] == [], r['older']
    assert r['submitted'] == 1, 'the selection did not reach the server'
    assert r['downloads_hidden'] is False, 'the job is downloading, as always'
    assert r['badge_hidden'] is True and r['badge_text'] == '', r
    assert r['link_hidden'] is True, r


def test_a_capable_companion_is_probed_then_handed_the_job_id(spa):
    """§2 steps 2-3. One probe, one dispatch, a body of exactly {job_id} --
    the companion gets everything else from the server under its own token,
    because a page may not be trusted with the work order (§8)."""
    r = spa['a_capable_companion_is_handed_the_job']
    assert [c['method'] for c in r['dispatched']] == ['GET', 'POST'], r['dispatched']
    assert r['dispatched'][0]['url'] == CAPABILITIES, r['dispatched']
    assert r['dispatched'][1]['url'] == LOCAL_DOWNLOAD, r['dispatched']
    assert r['dispatched'][1]['body'] == {'job_id': 90}, r['dispatched']
    # the server accepted the selection BEFORE any of it: the job downloads
    # either way, and this is only a shortcut on top of that
    assert r['order'] == ['api/jobs/90/download', CAPABILITIES, LOCAL_DOWNLOAD], r['order']
    # exactly one attempt per submission -- no retry loop, no loopback polling
    assert r['after_more_polls'] == 2, r
    assert r['badge'] == 'downloading on your machine', r
    assert r['badge_hidden'] is False and 'local' in r['badge_class'].split(), r
    assert r['badge_title'] == 'claimed by owen', r
    assert r['link_hidden'] is False, 'no way back to the server'
    assert r['review_hidden'] is True and r['toast_hidden'] is True, r


def test_no_companion_no_dispatch_and_the_editor_is_told_why(spa):
    """§11's first column, REVERSED on 2026-08-19 at the owner's request:
    "we need an error and some feedback for when it doesn't do it".

    Nothing listening, a tray predating the routes, a stale yt-dlp, a claim
    that lost the race, a companion already busy: all five still end at the
    server worker doing the job exactly as before -- and all five now say so.
    The old rule (silence, because the editor could not act on it and the
    server would do the job anyway) stopped holding on 2026-08-16, when lane B
    stopped bringing YouTube originals down: from then on "the server did it"
    was not a detail, it was the difference between having the footage and
    not."""
    r = spa['a_companion_that_cannot_take_it_is_never_handed_it']
    for name in ('dead', 'old', 'unable'):
        assert [c['url'] for c in r[name]] == [CAPABILITIES], f'{name}: {r[name]}'
    # a probe that says yes and a dispatch that is declined/busy: attempted
    # once, consequence nil
    assert r['refused'] == [CAPABILITIES, LOCAL_DOWNLOAD], r['refused']
    assert r['busy'] == [CAPABILITIES, LOCAL_DOWNLOAD], r['busy']
    for hidden, said in r['spoken']:
        assert hidden is False, 'a failed fast path said nothing at all'
        assert 'Downloading on the server' in said, said
        # ...and every one of them names what to do about the clip that is now
        # only on the NAS, which is the whole reason this stopped being silent.
        assert 'download history' in said, said
    assert r['badges'] == ['downloading on the server'] * 5, r['badges']
    # ...except the terms, which are the editor's to accept: probed, not
    # dispatched, told in the owner's words, and still downloading server-side
    assert r['terms']['calls'] == [CAPABILITIES], r['terms']
    assert r['terms']['toast_hidden'] is False, 'the terms refusal was silent'
    assert 'accept the download terms in the companion' in r['terms']['toast_text']
    assert 'Accept YouTube Terms' in r['terms']['toast_text']
    assert r['terms']['badge'] == 'downloading on the server', r['terms']


def test_a_probe_that_is_never_answered_is_abandoned(spa):
    """§2 step 2's timeout, the failure mode with no error to catch: a wedged
    tray app, or a laptop that slept between the click and the probe. The
    editor's page has already moved on, and the probe gives up by itself."""
    r = spa['a_hung_probe_is_abandoned_after_a_second']
    assert r['during'] == {'calls': 1, 'review_hidden': True,
                           'downloads_hidden': False,
                           'badge': 'downloading on the server',
                           'toast_hidden': True}, r['during']
    assert r['never_gave_up'] is False, \
        'the probe has no timeout: it waits on the companion forever'
    assert r['abandoned'] is True, r
    # Two probes, not one: a companion that TIMES OUT gets a single longer
    # second go (PROBE_RETRY_MS, 2026-08-19). Both are bounded, and neither is
    # a dispatch -- what must never happen is handing the job over.
    assert r['calls'] == 2, 'the abandoned probe still dispatched'


def test_a_job_this_machine_cannot_name_correctly_is_not_dispatched(spa):
    """COMP-BROLL-10 (2026-08-14): the executor runs 480p/720p/1080p and says
    so. A 2160p job handed over would be claimed, read off the manifest, found
    out of scope and abandoned -- a lease taken for nothing. A companion that
    declares no scope is one that predates the field, and it is dispatched to
    exactly as it was before."""
    r = spa['an_out_of_scope_job_is_never_handed_over']
    assert r['in_scope'] == [CAPABILITIES, LOCAL_DOWNLOAD], r['in_scope']
    assert r['out_of_scope'] == [CAPABILITIES], r['out_of_scope']
    assert r['undeclared'] == [CAPABILITIES, LOCAL_DOWNLOAD], r['undeclared']
    assert r['submitted'] == [1, 1, 1], 'the server lost a selection'
    hidden, said = r['spoken']
    assert hidden is False, 'the out-of-scope skip was silent (CR: 2026-08-19)'
    assert 'only downloads' in said, said


def test_the_badge_flips_on_its_own_when_the_server_reclaims(spa):
    """§3/§9: the lease expires (laptop closed, tray upgraded), the server takes
    the job back, and the header says so within a poll -- because the badge is
    read off the payload and remembered nowhere."""
    r = spa['the_badge_flips_when_the_server_reclaims']
    assert r['local']['badge'] == 'downloading on your machine', r['local']
    assert 'local' in r['local']['cls'].split(), r['local']
    assert r['local']['title'] == 'claimed by owen', r['local']
    assert r['local']['link_hidden'] is False, r['local']
    assert r['still'] == 'downloading on your machine', r
    assert r['reclaimed'] == 'downloading on the server', r
    assert 'local' not in r['reclaimed_cls'].split(), r
    assert r['reclaimed_title'] == '', r
    assert r['link_hidden_after'] is True, 'a job the server owns offered a hand-back'
    assert r['dispatches'] == 2, 'the reclaim re-dispatched'


def test_the_hand_back_posts_once_and_waits_for_the_poll(spa):
    """§9's per-job escape hatch. One request however many clicks, document-
    relative like every other API call here, and the page asserts nothing about
    the mode itself -- the next poll is the truth."""
    r = spa['handing_the_job_back_posts_once']
    assert r['before'] is False, 'the link was not offered on a local job'
    assert len(r['posts']) == 1, r['posts']
    assert r['posts'][0]['url'] == 'api/jobs/90/mode-lock', r['posts'][0]
    assert r['posts'][0]['method'] == 'POST'
    assert r['posts'][0]['body'] == {'mode': 'server'}, r['posts'][0]
    assert r['after_click']['disabled'] is True, 'clickable twice'
    assert r['after_click']['badge'] == 'downloading on your machine', \
        'the page decided the mode itself instead of asking'
    assert 'server' in r['toast']
    assert r['badge_after_poll'] == 'downloading on the server', r
    assert r['link_hidden_after'] is True, r


def test_a_refused_hand_back_is_said_out_loud(spa):
    """The one action here that is NOT a silent fast path: the editor asked for
    this, so a failure says so and the button comes back."""
    r = spa['a_refused_hand_back_says_so_and_comes_back']
    assert 'lease is already gone' in r['toast'], r
    assert r['disabled'] is False, 'a blip left a dead button'
    assert r['hidden'] is False, r


# ------------------------------- the evidence pips (WP5, CR-80, 2026-08-26)
def _pip(result, pip_id):
    return next(p for p in result['pips'] if p['id'] == pip_id)


def test_the_strip_names_the_yt_dlp_the_server_is_running(spa):
    """CR-80: "which yt-dlp is this container on" took a docker exec, and the
    answer was the whole bug (2026.07.04 has no working anonymous path)."""
    r = spa['the_strip_reports_evidence_when_the_server_sends_it']
    pip = _pip(r, 'healthytdlp')
    assert pip['text'] == 'yt-dlp 2026.08.19', pip
    assert 'on' in pip['cls'] and pip['hidden'] is False, pip


def test_the_last_real_download_is_what_the_downloads_pip_reports(spa):
    """`cookies: true` meant "a path is set" and stayed green through a day of
    total failure. The pip reports the last attempt that actually ran, on which
    path, and how long ago; the jar's state is a footnote on it."""
    r = spa['the_strip_reports_evidence_when_the_server_sends_it']
    pip = _pip(r, 'healthdl')
    assert pip['text'] == 'last download: anonymous, 12 min ago', pip
    assert 'on' in pip['cls'], pip
    # the CR-80 parked state, said in words rather than as a boolean
    assert 'holds no cookies' in pip.get('title', ''), pip


def test_a_working_sidecar_is_a_pip_and_a_disabled_canary_is_not(spa):
    r = spa['the_strip_reports_evidence_when_the_server_sends_it']
    assert _pip(r, 'healthpot')['text'] == 'PO token ok', r
    canary = _pip(r, 'healthcanary')
    assert canary['text'] == '' and canary['hidden'] is True, canary


def test_a_dead_sidecar_a_failed_download_and_a_failed_canary_are_red(spa):
    """CR-73 sat undetected for days behind a sidecar that was configured and
    unreachable, which is the same shape of lie `cookies: true` told."""
    r = spa['a_broken_path_and_a_dead_sidecar_are_red']
    pot = _pip(r, 'healthpot')
    assert pot['text'] == 'PO token unreachable' and 'off' in pot['cls'], pot
    dl = _pip(r, 'healthdl')
    assert dl['text'] == 'last download: cookies failed, 2 hr ago', dl
    assert 'off' in dl['cls'], dl
    # the reason is in the title, not in a pip nobody can read at a glance
    assert 'The page needs to be reloaded.' in dl.get('title', ''), dl
    canary = _pip(r, 'healthcanary')
    assert canary['text'] == 'canary failed, 5 min ago', canary
    assert 'off' in canary['cls'] and canary['hidden'] is False, canary
    assert 'HTTP Error 403' in canary.get('title', ''), canary


def test_an_unconfigured_sidecar_is_grey_and_not_a_fault(spa):
    """Plenty of deployments never need a PO-token sidecar; a red pip for one
    that was never asked for is the noise that makes a strip unreadable."""
    r = spa['the_quiet_states_are_grey_or_absent']
    pot = _pip(r, 'healthpot')
    assert pot['text'] == 'PO token off', pot
    assert 'on' not in pot['cls'] and 'off' not in pot['cls'], pot
    dl = _pip(r, 'healthdl')
    assert dl['text'] == 'no downloads yet', dl
    assert 'no cookie jar' in dl.get('title', ''), dl


def test_a_server_without_the_new_keys_paints_exactly_the_old_strip(spa):
    """The degradation contract: WP5 ships to the fleet as a dashboard deploy,
    and a cached bundle talking to an older server (or the reverse) must not
    grow four empty boxes."""
    r = spa['a_server_without_the_new_keys_paints_the_old_strip']
    assert _pip(r, 'health')['text'] == 'claude ok', r
    for pip_id in ('healthytdlp', 'healthpot', 'healthdl', 'healthcanary'):
        pip = _pip(r, pip_id)
        assert pip['text'] == '', pip
        assert pip['hidden'] is True, pip


# ------------------------------------ the retry button (WP6, 2026-08-26)
def test_a_done_job_with_failures_offers_a_retry_that_posts_the_download(spa):
    """The CR-80 recovery was one POST api/jobs/28/download, which re-queued
    exactly the 29 failed rows. Until now the only control that reached it was
    DOWNLOAD on the review grid, which a done job no longer shows."""
    r = spa['a_done_job_with_failures_can_be_retried']
    assert r['before']['hidden'] is False, r['before']
    assert r['before']['label'] == '[ RETRY 2 FAILED ]', r['before']
    assert r['posts'] == ['api/jobs/95/download'], r['posts']
    assert 'failed' in r['toast'], r['toast']


def test_the_failure_count_falls_back_to_the_manifest(spa):
    r = spa['the_count_falls_back_to_the_manifest_rows']
    assert r['label'] == '[ RETRY 1 FAILED ]', r
    assert r['hidden'] is False, r


def test_a_parked_job_prints_its_note_above_the_retry(spa):
    """WP6's circuit breaker parks the job in `failed` with an instruction on
    `job.error`; that sentence is what decides whether retrying is worth
    anything, so it is repeated beside the button and not only in the banner
    at the top of the page."""
    r = spa['a_parked_job_shows_the_breakers_note_above_the_button']
    assert r['note_hidden'] is False, r
    assert 'signed-in session is being refused' in r['note'], r
    assert r['hidden'] is False and r['label'] == '[ RETRY 5 FAILED ]', r


def test_a_failed_job_with_no_downloads_offers_no_retry(spa):
    """The server 409s it, and an offer that cannot be honoured is worse than
    no offer at all."""
    r = spa['a_failed_job_with_no_downloads_is_offered_nothing']
    assert r['hidden'] is True, r
    assert r['note_hidden'] is True, r
    assert r['panel_hidden'] is True, r


def test_a_refused_retry_is_said_out_loud_and_the_button_comes_back(spa):
    r = spa['a_refused_retry_is_said_out_loud']
    assert 'nothing to download' in r['toast'], r
    assert r['disabled'] is False, 'a 409 left a dead button'
    assert r['hidden'] is False, r


# --------------------------------------------------- source-level assertions
# These run with or without node: they are the cheap backstop for the shapes
# the harness proves, so a rewrite that reintroduces one is caught even on a
# machine with no JS runtime.

def _js():
    return APP_JS.read_text(encoding='utf-8')


def _html():
    return (STATIC / 'index.html').read_text(encoding='utf-8')


def _css():
    return (STATIC / 'style.css').read_text(encoding='utf-8')


def test_the_download_bar_counts_the_video_in_flight_not_just_finished_ones():
    js = _js()
    body = js[js.index('function renderDownloads('):js.index('async function loadManifest(')]
    assert '(done + inflight)' in body, body
    # the double-count guard: only what the MANIFEST still calls downloading
    assert "v.dl_state === 'downloading'" in body, body
    # ...and the no-manifest-yet branch, which has only the live status to go on
    assert "live[k].status === 'downloading'" in body, body


def test_the_rows_and_the_cards_share_one_thumbnail_helper():
    """The row picture IS the card's trick -- ytimg direct, id-only fallback --
    so it is one function, not two that can drift."""
    js = _js()
    assert 'function thumb(v, cls)' in js, js
    rows = js[js.index('function renderDownloads('):js.index('async function loadManifest(')]
    assert rows.count('thumb(') == 2, rows      # the manifest rows and the fallback rows
    card = js[js.index('function card(v)'):js.index('const _selQueue')]
    assert "thumb(v, 'thumb')" in card, card


def test_the_shot_type_row_sits_above_the_search_box():
    """Owner's call, 2026-08-11: the ticks are what the topic is read WITH, so
    they are chosen before it is typed."""
    html = _html()
    assert html.index('class="ctrl-row shotrow"') < html.index('<input id="q"'), \
        'the shot-type checkboxes are back below the search bar'
    # still inside the header controls, and still the same two elements
    assert html.index('class="header-controls"') < html.index('class="ctrl-row shotrow"')
    row = html[html.index('class="ctrl-row shotrow"'):html.index('<div class="ctrl-row">')]
    assert 'id="shots"' in row and 'id="shotnote"' in row, row


def test_a_ticked_shot_box_carries_no_red_left_edge():
    """The dashboard's "current selection" idiom is a 2px red inset accent; the
    owner does not want it beside a checkbox, which says ticked by itself."""
    css = _css()
    block = css[css.index('.shot.on {'):css.index('}', css.index('.shot.on {'))]
    assert 'box-shadow' not in block, block
    # ...but it must still read as selected
    assert 'var(--field)' in block and 'border-color' in block, block


def test_the_toast_never_assigns_innerhtml():
    """YTDL-35: every other server-derived string in this SPA goes through
    el()/textContent; the toast was the one hole."""
    js = _js()
    body = js[js.index('function toast('):js.index('const banners')]
    assert 'innerHTML' not in body, body
    assert 'textContent' in body and 'appendChild' in body


def test_no_caller_passes_markup_to_the_toast():
    assert '<div class="bad">' not in _js()


def test_poll_guards_every_await_with_the_ownership_token():
    """YTDL-9: the guard is what makes a late response harmless, so it must
    survive the next edit to poll()."""
    js = _js()
    body = js[js.index('async function poll()'):js.index('function detach()')]
    assert body.count('stale(id, token)') >= 4, body
    assert 'state.attachToken' in js and 'attachToken++' in js


def test_the_poll_stops_on_a_401():
    js = _js()
    assert 'e.status === 401' in js and 'sessionExpired()' in js


def test_the_search_button_is_guarded_in_source():
    js = _js()
    body = js[js.index('async function runSearch()'):js.index('async function startDownload()')]
    assert 'go.disabled = true' in body and 'go.disabled = false' in body
    assert body.index('detach()') > body.index("post('api/jobs'"), \
        'YTDL-8: detach() must come AFTER the POST is accepted'
    assert 'e.info.job_id' in body


def test_the_links_button_is_guarded_in_source():
    """Same three properties as runSearch, on the second submit path: the
    button is the in-flight lock, the live job is only torn down AFTER the
    server accepts (YTDL-8), and a 409 carries the job to re-attach to."""
    js = _js()
    body = js[js.index('async function runUrls()'):js.index('async function startDownload()')]
    assert 'btn.disabled = true' in body and 'btn.disabled = false' in body
    assert body.index('detach()') > body.index("post('api/jobs/urls'")
    assert 'e.info.job_id' in body


def test_the_links_box_posts_a_document_relative_url():
    """A leading slash here would hit the DASHBOARD's /api/jobs/urls under the
    mount. test_mounted_prefix.py scans the bytes; this names the URL."""
    assert "post('api/jobs/urls'" in _js()


def test_a_url_job_is_not_offered_a_review_grid():
    js = _js()
    body = js[js.index('async function loadManifest('):js.index('function renderTerms()')]
    assert "m.job.kind === 'urls'" in body, body


def test_health_covers_every_state_the_contract_emits():
    """YTDL-11: the contract is ok|unauthenticated|missing|timeout|error|
    unknown and two of them used to hit the all-clear."""
    js = _js()
    body = js[js.index('async function loadHealth()'):js.index('// ------', js.index('async function loadHealth()'))]
    for stateName in ('unauthenticated', 'missing', 'timeout', 'error'):
        assert f"h.claude === '{stateName}'" in body, stateName


def test_the_banner_is_per_concern_not_one_shared_line():
    """YTDL-37: one element meant the last speaker erased the others."""
    js = _js()
    assert 'function setBanner(' in js
    assert 'function warn(' not in js, 'the single-slot warn() came back'
    for key in ("'health'", "'projects'", "'worker'", "'job'", "'session'"):
        assert f'setBanner({key}' in js, key


def test_health_is_re_fetched_on_a_slow_interval():
    js = _js()
    assert 'setInterval(loadHealth, HEALTH_INTERVAL)' in js
    assert 'const HEALTH_INTERVAL = ' in js


# The one duplication this feature carries: the server owns the prompt
# fragments, the SPA owns the labels beside the boxes, and both need the keys.
_SHOT_ROW = re.compile(
    r"\{key: '([a-z]+)', label: '([^']+)', on: (true|false), "
    r"group: '([a-z]+)', short: '([^']+)'\}")


def test_the_shot_type_table_matches_the_servers_key_for_key():
    """A key the server does not know is a 400 on every search; a label that
    drifts is an editor ticking a box that does something else."""
    from ytdlweb import claude_cli

    rows = _SHOT_ROW.findall(_js())
    assert len(rows) == len(claude_cli.SHOT_TYPES), rows
    assert [r[0] for r in rows] == list(claude_cli.SHOT_TYPES), 'order differs'
    for key, label, on, group, short in rows:
        frag = claude_cli.SHOT_TYPES[key]
        assert label == frag['label'], key
        assert (on == 'true') is frag['default'], key
        assert group == frag['group'], key
        assert short.strip(), key


_CAPS_LINE = re.compile(r'const CANDIDATE_CAPS = \[([\d, ]+)\];')


def test_the_candidate_limit_choices_match_the_servers():
    """The second duplication this feature carries (config -> the dropdown, and
    config -> migration 006's SQL default): the server refuses a number that is
    not on ITS list, so a drift here is a 400 on every search."""
    from ytdlweb import config

    m = _CAPS_LINE.search(_js())
    assert m, 'the CANDIDATE_CAPS table is gone or reshaped'
    assert [int(x) for x in m.group(1).split(',')] == list(config.CANDIDATE_CAPS)
    assert f'const DEFAULT_CAP = {config.DEFAULT_MAX_CANDIDATES};' in _js()
    assert "const CAP_KEY = 'ytdl.max_candidates'" in _js()


def test_the_search_posts_a_validated_limit_and_the_paste_posts_none():
    """A url job does no searching, so a ceiling on the search would be a field
    that changes nothing -- and the raw DOM value is never posted, because an
    unlisted number is refused rather than clamped."""
    js = _js()
    body = js[js.index('async function runSearch()'):js.index('async function runUrls()')]
    assert 'max_candidates: capValue()' in body, body
    paste = js[js.index('async function runUrls()'):js.index('async function startDownload()')]
    assert 'max_candidates' not in paste, paste


def test_the_limit_is_validated_against_this_builds_list_on_the_way_in_and_out():
    js = _js()
    for fn in ('function loadCap()', 'function capValue()'):
        body = js[js.index(fn):js.index('}', js.index('return', js.index(fn)))]
        assert 'CANDIDATE_CAPS.includes(' in body, fn
    # ...and localStorage is never allowed to break the page (see loadShots)
    body = js[js.index('function loadCap()'):js.index('function capValue()')]
    assert body.count('try {') >= 2 and body.count('catch') >= 2, body


_MODE_ROW = re.compile(
    r"\{key: '([a-z]+)', label: '([^']+)', short: '([^']+)',\s*\n"
    r"\s*preset: \[([^\]]*)\]")


def test_the_search_mode_table_matches_the_servers():
    """The third duplication this feature carries (claude_cli.MODES -> the
    toggle): the server refuses a mode that is not on ITS list, so a drift here
    is a 400 on every search -- and a preset that drifts silently ticks the
    wrong boxes for the montage the editor picked."""
    from ytdlweb import claude_cli

    rows = _MODE_ROW.findall(_js())
    assert len(rows) == len(claude_cli.MODES), rows
    assert [r[0] for r in rows] == list(claude_cli.MODES), 'order differs'
    for key, label, short, preset in rows:
        keys = [k.strip().strip("'") for k in preset.split(',') if k.strip()]
        assert tuple(keys) == claude_cli.MODES[key]['preset'], key
        assert label.strip() and short.strip(), key
    assert f"const DEFAULT_MODE = '{claude_cli.DEFAULT_MODE}';" in _js()


def test_the_search_posts_the_mode_and_the_paste_posts_none():
    """A url job is never searched, so a rubric for the search would be a field
    that changes nothing -- and the mode posted is always a key from the table,
    because the server refuses one it does not know."""
    js = _js()
    body = js[js.index('async function runSearch()'):js.index('async function runUrls()')]
    assert 'mode: state.searchMode' in body, body
    paste = js[js.index('async function runUrls()'):js.index('async function startDownload()')]
    assert 'mode:' not in paste, paste


def test_the_two_groups_of_boxes_are_captioned_on_the_page():
    """2026-08-18: nine labels in two unexplained groups read as "one of these
    is mandatory". The page says what they are, in the markup, so it is there
    before a single fetch lands."""
    html = _html()
    assert 'SHOTS OF IT = footage of the subject' in html
    assert 'ALSO KEEP = people talking about it' in html
    assert 'id="modes"' in html
    # the toggle is FIRST on the row: it presets the boxes beside it
    assert html.index('id="modes"') < html.index('id="shots"')


def test_the_search_posts_the_ticked_shot_types_in_source():
    js = _js()
    body = js[js.index('async function runSearch()'):js.index('async function runUrls()')]
    assert 'shot_types: shotKeys()' in body, body
    # ...and the paste box does NOT: a url job is never searched or filtered
    paste = js[js.index('async function runUrls()'):js.index('async function startDownload()')]
    assert 'shot_types' not in paste, paste


def test_the_paste_box_has_a_folder_field_again():
    """Owner, 2026-08-30, reversing 2026-08-11: "there should be a way to
    manually input the name of the folder/bin you want links you are
    downloading to go into". #urlfolder is in the markup, posted with the
    paste, styled, and remembered like the project is (blank still means the
    Youtube root, exactly as every paste has landed since 2026-08-11)."""
    js, html, css = _js(), _html(), _css()
    assert 'id="urlfolder"' in html, html[html.index('id="urls"'):][:400]
    paste = js[js.index('async function runUrls()'):js.index('async function startDownload()')]
    assert "folder: box ? box.value.trim() : ''" in paste, paste
    assert "$('#urlfolder')" in paste, paste
    assert '#urlfolder' in css
    assert "const URL_FOLDER_KEY = 'ytdl.url_folder';" in js


def test_the_reveal_goes_to_the_companion_loopback_with_a_relative_path():
    """The ONLY way a page served from the NAS can open a folder on the
    editor's machine -- b-roll's precedent, and the same reason its
    tests/test_mounted_prefix.py tolerates one absolute URL. The body carries a
    path relative to the Projects root: the page must not learn a drive
    letter."""
    js = _js()
    assert "const COMPANION_URL = 'http://127.0.0.1:8899';" in js
    # Sliced to reveal() ALONE. It used to run to `function noCompanion(`,
    # which stopped being the next thing in the file when CR-32 put the fetch
    # between them -- and the count below then read the fetch's error paths as
    # reveal's.
    body = js[js.index('async function reveal(d)'):
              js.index('// ------------------------------------------------- '
                       'getting a clip off the NAS')]
    assert '`${COMPANION_URL}/ytdl/reveal`' in body, body
    assert 'rel_path: d.reveal_path' in body, body
    # every failure shape ends at the same place: a message and the path --
    # nothing listening, a companion too old for the route, and any refusal
    assert body.count('noCompanion(') == 3, body
    # ...and the ONE answer that is not a failure: the clip is on the NAS, so
    # it is offered rather than mourned (CR-32).
    assert body.count('offerFetch(') == 1, body


def test_the_absent_companion_never_reaches_an_error_state():
    js = _js()
    body = js[js.index('function noCompanion('):js.index('function copyText(')]
    assert 'COPY PATH' in body and 'toast(' in body
    # the clipboard is permissioned and absent in older browsers, so it is
    # guarded rather than assumed
    copy = js[js.index('function copyText('):js.index('// ------', js.index('function copyText('))]
    assert 'navigator.clipboard' in copy and 'try {' in copy and 'catch' in copy


def test_the_history_asks_for_a_page_not_the_whole_ledger():
    js = _js()
    body = js[js.index('async function loadHistory('):js.index('function historyRow(')]
    assert "api/downloads?limit=${HISTORY_PAGE}&offset=${offset}" in body, body
    assert 'const HISTORY_PAGE = ' in js
    # server-derived text only ever through el()/textContent (YTDL-35): a title
    # is a string YouTube gave us
    row = js[js.index('function historyRow('):js.index('// Open the containing folder')]
    assert 'innerHTML' not in row, row
    assert "el('div', 'name', d.title || d.video_id)" in row, row


def test_the_page_prefers_the_active_job_over_the_hash_in_source():
    """The precedence itself, so a later edit to init() cannot quietly restore
    "whatever the URL says" (found live, 2026-08-11)."""
    js = _js()
    body = js[js.index('async function openingJob()'):js.index('init().catch(')]
    assert "api('api/jobs/active')" in body, body
    assert '(active && active.id) || (m ? Number(m[1]) : null)' in body, body
    # an old server without the route must not stop the hash working
    assert 'catch' in body, body


def test_every_panel_header_is_a_real_button_not_a_div_with_an_onclick():
    """Keyboard-reachable and announced, for free: a <button> takes tab focus
    and fires on space/enter with no key handling of this app's own, and
    aria-expanded/aria-controls tell a screen reader what the click does."""
    html = _html()
    for pid, title in (('review', 'REVIEW'), ('downloads', 'DOWNLOADS'),
                       ('recent', 'RECENT SEARCHES'),
                       ('history', 'DOWNLOAD HISTORY')):
        m = re.search(r'<button id="%stoggle"[^>]*>\[-\] %s</button>' % (pid, title),
                      html, re.S)
        assert m, f'{pid}: no <button> header'
        tag = m.group(0)
        assert 'type="button"' in tag, tag       # inside no form, but never a submit
        assert 'class="ptoggle"' in tag, tag
        assert 'aria-expanded="true"' in tag, tag
        body = re.search(r'aria-controls="([^"]+)"', tag)
        assert body, tag
        # the thing it claims to control has to exist
        assert f'id="{body.group(1)}"' in html, body.group(1)
    # ...and nothing else in the page pretends to be a control
    assert 'panelhead" onclick' not in html and '<div class="ptoggle"' not in html


def test_the_folded_panels_are_remembered_exactly_like_every_other_choice():
    """Same shape as SHOTS_KEY/CAP_KEY: one key, guarded both directions,
    validated against THIS build's list on the way in and on the way out."""
    js = _js()
    assert "const COLLAPSE_KEY = 'ytdl.collapsed'" in js
    body = js[js.index('function loadCollapsed()'):js.index('function applyPanel(')]
    assert body.count('try {') >= 2 and body.count('catch') >= 2, body
    assert 'Array.isArray(saved)' in body, body
    # an id this build does not have is dropped, in both directions
    assert body.count('PANELS.filter(') == 2, body


def test_the_panel_header_carries_the_caret_and_the_announced_state():
    js = _js()
    body = js[js.index('function applyPanel('):js.index('function togglePanel(')]
    assert "'[+] '" in body and "'[-] '" in body, body
    assert "setAttribute('aria-expanded'" in body, body
    assert 'classList.toggle(' in body, body


def test_the_review_panel_is_forced_open_only_when_a_job_ARRIVES_at_review():
    """The transition, not the phase: a re-render of the same job must not keep
    re-opening a panel the editor folded, and a job that was already waiting
    when the page attached has not newly reached anything."""
    js = _js()
    body = js[js.index('async function poll()'):js.index('function detach()')]
    assert 'forceExpandReview()' in body, body
    assert "seen && seen !== 'ready_for_review'" in body, body
    # the phase this page last SAW is per attachment, or job B would inherit A's
    attached = js[js.index('async function attach('):js.index('async function poll()')]
    assert 'state.phase = null' in attached, attached
    detached = js[js.index('function detach()'):js.index('function renderProgress(')]
    assert 'state.phase = null' in detached, detached
    # the stored fold is cleared with it, or the panel re-folds next visit
    force = js[js.index('function forceExpandReview()'):js.index('function initPanels()')]
    assert 'saveCollapsed()' in force and "state.collapsed.delete('review')" in force


def test_a_folded_panel_header_still_carries_the_count():
    """The summary spans live in the HEADER, outside the body that disappears
    -- that is the whole difference between folding bulk away and hiding the
    answer."""
    js, html = _js(), _html()
    for sid, body in (('reviewsum', 'reviewbody'), ('recentsum', 'recentlist'),
                      ('historysum', 'historybody')):
        assert f'id="{sid}"' in html, sid
        assert html.index(f'id="{sid}"') < html.index(f'id="{body}"'), sid
        assert f"$('#{sid}')" in js, sid
    # the downloads panel's summary is the phase and counter it already had
    start = html.index('<div class="prow panelhead">')
    head = html[start:html.index('<div class="bar">', start)]
    assert 'id="dlphase"' in head and 'id="dlticker"' in head, head
    assert 'id="cancel2"' in head, head


def test_localstorage_is_never_allowed_to_break_the_page():
    """It throws outright in some privacy modes, and a page that cannot
    remember the ticks must still be able to search."""
    js = _js()
    body = js[js.index('function loadShots(mode)'):js.index('function renderShotNote()')]
    # loadShots/saveShots and loadSearchMode/saveSearchMode: four accesses, four
    # guards. The mode is remembered exactly like the ticks it presets.
    assert body.count('try {') >= 4 and body.count('catch') >= 4, body
    assert "const SHOTS_KEY = 'ytdl.shot_types'" in js
    assert "const MODE_KEY = 'ytdl.search_mode'" in js


def test_the_destination_project_is_remembered_like_every_other_choice():
    """Same shape as SHOTS_KEY/CAP_KEY/COLLAPSE_KEY: one key, guarded both
    directions, and validated against what the SERVER just listed on the way in
    -- the restore has to happen after the options exist, or it selects
    nothing (2026-08-14)."""
    js = _js()
    assert "const PROJECT_KEY = 'ytdl.project'" in js
    guard = js[js.index('function loadProject()'):js.index('async function loadProjects()')]
    assert guard.count('try {') >= 2 and guard.count('catch') >= 2, guard
    body = js[js.index('async function loadProjects()'):js.index('const searchModeOf')]
    assert body.index('loadProject()') > body.index('sel.appendChild(o)'), \
        'the restore runs before the options exist'
    # only a slug the server still offers, and the change is what saves it
    assert 'r.projects.some(p => p.slug === saved)' in body, body
    assert 'sel.onchange = saveProject' in body, body


# --- requester-first downloads: the shapes, for a machine with no node --------

def _dispatch():
    js = _js()
    return js[js.index('async function dispatchLocal('):js.index('function renderMode(')]


def test_the_local_dispatch_is_gated_on_the_servers_own_flag():
    """docs/YTDL_LOCAL_DOWNLOAD.md §10: phase 1 deploys with YTDL_LOCAL_DOWNLOAD
    off and soaks on the live dashboard, which only holds if the flag is read
    strictly -- absent means off, and off means this page is what it was."""
    js = _js()
    health = js[js.index('async function loadHealth()'):js.index('// ------', js.index('async function loadHealth()'))]
    assert 'state.localDownload = h.local_download === true;' in health, health
    # The gate moved into localWanted() when the editor's own switch was added
    # (2026-08-19). Both halves still have to hold: the fleet flag is checked
    # FIRST and answers false on its own, so a fleet that never enabled the
    # feature cannot be opted back into it by a checkbox.
    js = _js()
    wanted = js[js.index('function localWanted()'):js.index('function initLocalSwitch()')]
    assert 'if (!state.localDownload) return false;' in wanted, wanted
    assert 'if (!localWanted()) return false;' in _dispatch(), _dispatch()


def test_the_switch_defaults_to_on_when_the_page_has_no_checkbox():
    """A cached index.html from before the switch existed still has to dispatch.
    Reading a missing `checked` as "unticked" would have made a stale asset a
    silent, fleet-wide opt-out of requester-first downloads."""
    js = _js()
    wanted = js[js.index('function localWanted()'):js.index('function initLocalSwitch()')]
    assert 'box.checked !== false' in wanted, wanted


def test_the_links_button_offers_the_job_to_this_machine_too():
    """CR-36 (2026-08-19): dispatchLocal lived only in startDownload, the
    review-grid path, so EVERY pasted link this fleet ever fetched downloaded
    on the NAS -- and since 2026-08-16 no lane brings a YouTube original back
    down, so the editor who pasted the link was the one person guaranteed not
    to end up with the clip. A paste has no review step, so runUrls is the only
    place the offer can be made."""
    js = _js()
    body = js[js.index('async function runUrls()'):js.index('async function startDownload()')]
    assert 'dispatchLocal(' in body, body
    # AFTER the server has accepted it, exactly as startDownload does: the job
    # downloads either way, and the offer is a shortcut on top (§2 step 1).
    assert body.index('dispatchLocal(') > body.index("post('api/jobs/urls'"), body


def test_the_probe_is_bounded_and_every_failure_of_it_is_explained():
    """§2 step 2: 1 s, then the server path. It sits between the editor clicking
    DOWNLOAD and the page moving on, and a tray app that is wedged (or a browser
    refusing the local connection) must cost that second and nothing else.

    The BOUND is unchanged; the silence is not. Every exit now ends at
    noteLocalSkipped (2026-08-19, the owner) -- see
    test_no_companion_no_dispatch_and_the_editor_is_told_why for why."""
    js = _js()
    assert 'const PROBE_MS = 1000;' in js
    # ...and ONE longer second go for a companion that is there but busy
    # (2026-08-19; 3.9 s measured mid-sync-pass). Both budgets are bounded and
    # both are tried in the same loop, so "abandoned" still means abandoned.
    assert 'const PROBE_RETRY_MS = 5000;' in js
    body = js[js.index('async function companionCapabilities('):js.index('async function dispatchLocal(')]
    assert '`${COMPANION_URL}/ytdl/capabilities`' in body, body
    assert 'new AbortController()' in body and 'ctl.abort()' in body, body
    assert 'for (const budget of [PROBE_MS, PROBE_RETRY_MS])' in body, body
    assert 'setTimeout(() => ctl.abort(), budget)' in body, body
    # the retry is for a TIMEOUT only: nothing listening still fails at once
    assert "e.name === 'AbortError'" in body, body
    assert 'if (body || !timedOut) break;' in body, body
    # the timer is only half of it: the signal has to reach the fetch
    assert '{signal: ctl.signal}' in body, body
    assert 'clearTimeout(timer)' in body, body
    # 200 with ok:false is a companion saying why not; it is a no like any other
    assert 'body.ok === true' in body, body
    assert 'if (!res.ok) {' in body, body
    # EVERY exit says why. The four the probe itself can reach -- a 404 (a
    # companion predating the routes), a reasoned no, an unreachable loopback,
    # and a timeout -- plus the two dispatchLocal can (out of scope, and a
    # refused hand-off).
    assert body.count('noteLocalSkipped(') == 4, body
    assert _dispatch().count('noteLocalSkipped(') >= 2, _dispatch()
    # ...still through ONE funnel that says each reason once, so a poll or a
    # re-click cannot turn an explanation into a stream of them.
    note = js[js.index('function noteLocalSkipped('):js.index('// Is there a companion')]
    assert 'if (why === lastLocalNote) return;' in note, note
    # The terms refusal keeps its own louder wording: it is the one an editor
    # fixes in the tray in ten seconds (owner, 2026-08-18).
    assert '/terms/i.test(' in body and 'explainCompanionRefusal(' in body, body


def test_the_dispatch_carries_a_job_id_and_nothing_else():
    """§2/§8: the browser is the dispatcher because it is the only party that
    can see both sides -- but the work order is not its to give. Urls, quality,
    destination and template all reach the companion from the server."""
    js = _js()
    assert "const COMPANION_URL = 'http://127.0.0.1:8899';" in js
    body = _dispatch()
    assert '`${COMPANION_URL}/ytdl/download`' in body, body
    assert 'JSON.stringify({job_id: jobId})' in body, body
    assert 'res.status === 202' in body, body
    # exactly one attempt per submission: no loop, no retry, no timer
    for banned in ('for (', 'while (', 'setTimeout', 'setInterval'):
        assert banned not in body, banned


def test_the_dispatch_respects_a_companions_declared_scope():
    """COMP-BROLL-10: the one thing this page may decide with, and it decides
    it the safe way round -- a companion that declares no scope, or a quality
    the page does not know, is dispatched to exactly as before."""
    body = _dispatch()
    assert 'Array.isArray(cap.scope_qualities)' in body, body
    assert 'cap.scope_qualities.includes(quality)' in body, body
    assert 'async function dispatchLocal(jobId, quality)' in _js()


def test_the_dispatch_happens_only_after_the_server_accepts_the_selection():
    """§2 step 1: the job is downloading server-side from the moment the POST
    is accepted, and nothing about the companion is allowed to be a
    precondition for that -- nor to make the editor wait for a probe."""
    js = _js()
    body = js[js.index('async function startDownload()'):js.index('async function cancelJob()')]
    assert body.index('dispatchLocal(jobId') > body.index('post(`api/jobs/${jobId}/download`)'), body
    assert 'await dispatchLocal' not in body, 'the review panel now waits on the probe'
    # ...and the quality it hands the dispatcher is the JOB's, off the manifest
    # under review -- never the header picker, which is whatever the editor has
    # changed it to since (COMP-BROLL-10, 2026-08-14)
    assert 'state.manifest.job.quality' in body, body
    assert "$('#quality')" not in body, body


def test_the_executor_badge_is_derived_from_the_payload_and_nothing_else():
    """§9: it must flip on a reclaim the page never asked for (§3), so it is
    read off every poll response and remembered nowhere -- the only local thing
    it consults is the server's own feature flag."""
    js = _js()
    body = js[js.index('function renderMode('):js.index('async function lockToServer(')]
    assert 'job.download_mode' in body and "job.phase === 'downloading'" in body, body
    assert 'downloading on your machine' in body, body
    assert 'downloading on the server' in body, body
    assert 'job.claimed_by' in body, body
    assert 'state.' not in body.replace('state.localDownload', ''), \
        'the badge grew a piece of state that can go stale'
    # ...and it is rendered from the same tick as the bar and the counter
    rows = js[js.index('function renderDownloads('):js.index('async function loadManifest(')]
    assert 'renderMode(job)' in rows, rows


def test_the_hand_back_is_document_relative_and_one_shot():
    """A leading slash would hit the DASHBOARD's api under the mount
    (test_mounted_prefix.py scans the bytes; this names the URL), and a second
    click is the same request, not a second one."""
    js = _js()
    body = js[js.index('async function lockToServer('):js.index('// -------', js.index('async function lockToServer('))]
    assert "post(`api/jobs/${state.jobId}/mode-lock`, {mode: 'server'})" in body, body
    assert 'if (btn.disabled' in body and 'btn.disabled = true' in body, body
    # the page never decides the mode itself: §9's "then relies on polling"
    assert 'download_mode' not in body, body
    # ...and the one-shot is per ATTACHMENT: job B may be local when job A was
    # handed back
    attached = js[js.index('async function attach('):js.index('async function poll()')]
    assert "$('#dlserver').disabled = false" in attached, attached


def test_the_badge_and_the_link_live_in_the_downloads_header():
    """Both hidden in the markup: with the flag off (the whole of phase 1 on
    the live dashboard) nothing new may appear on this page at all."""
    html = _html()
    start = html.index('<div class="prow panelhead">')
    head = html[start:html.index('<div class="bar">', start)]
    assert 'id="dlmode" class="dlmode hidden"' in head, head
    assert '<button id="dlserver" class="text-btn hidden"' in head, head
    assert head.index('id="dlmode"') < head.index('id="dlserver"'), head
    assert head.index('id="dlserver"') < head.index('id="cancel2"'), head
    js = _js()
    assert "$('#dlserver').onclick = lockToServer;" in js


def test_the_executor_badge_reads_as_a_status_chip_not_a_warning():
    """The server doing the download is the ordinary case and the whole of
    phase 1 -- it must not look like something went wrong."""
    css = _css()
    plain = css[css.index('.dlmode {'):css.index('}', css.index('.dlmode {'))]
    assert 'var(--muted)' in plain, plain
    assert 'var(--red)' not in plain and 'var(--amber)' not in plain, plain
    local = css[css.index('.dlmode.local {'):css.index('}', css.index('.dlmode.local {'))]
    assert 'var(--green)' in local, local
    # beside the badge it acts on, not shoved to the right edge with [ CANCEL ]
    assert '#dlserver { margin-left: 0; }' in css


def test_download_stays_available_on_a_finished_job_in_source():
    """CR-35 (2026-08-19). start_download has accepted `done` as well as
    `ready_for_review` since YTDL-16 -- pressing DOWNLOAD on a finished job is
    the documented retry, and the one route to a clip the editor did not pick
    the first time. The grid's button did not agree, so it greyed out for good
    the moment the first download finished and the only way to a second clip
    out of 67 was another whole search (an editor, 2026-08-19).
    """
    js = _js()
    body = js[js.index("$('#download').textContent"):
              js.index('function card(v)')]
    assert "'ready_for_review'" in body and "'done'" in body
    # ...and it is still disabled with nothing ticked: the button's OTHER job.
    assert '!sel.length' in body


def test_an_absent_clip_is_offered_a_fetch_in_source():
    """CR-32: reveal's `absent` is what turns "it is on the NAS" from a dead
    end into a download. Both halves pinned -- the flag the companion sets and
    the route the page calls -- because either alone is a button that does
    nothing."""
    js = _js()
    assert 'body.absent' in js
    assert '/ytdl/fetch' in js
    body = js[js.index('async function runFetch(d)'):js.index('function fetchLine(d, body)')]
    # A 404 is an old companion, not a broken feature: same distinction reveal
    # already makes.
    assert 'res.status === 404' in body
    # The poll is what shows progress; without it the toast lies about a
    # download that is still running.
    assert "body.state === 'downloading'" in body and 'setTimeout' in body


# ------------------------------------------------ the term scope + dates
# 2026-08-25, the owner: "let you search 'only english', 'only chinese' or
# 'single search term only'", and "there should also be a date selector".


def test_the_scope_toggle_offers_the_four_scopes_and_posts_the_choice(spa):
    r = spa['the_scope_and_dates_are_posted_with_the_search']
    assert [b[0] for b in r['buttons']] == ['[ EN + ZH ]', '[ ENGLISH ONLY ]',
                                            '[ CHINESE ONLY ]', '[ MY TERM ONLY ]'], r
    assert [b[1] for b in r['buttons']] == ['modebtn on', 'modebtn', 'modebtn', 'modebtn']
    assert [b[2] for b in r['buttons']] == ['true', 'false', 'false', 'false']
    # the default needs no note; the exact search explains itself
    assert r['note_before'] == ''
    assert 'no claude expansion' in r['note_after'] and 'candidate limit' in r['note_after']
    assert r['lit'] == ['modebtn', 'modebtn', 'modebtn', 'modebtn on'], r
    # ONE submit carries the scope and both dates, as the ISO strings the
    # inputs emit; the server turns them into YYYYMMDD
    assert r['body']['term_scope'] == 'exact', r['body']
    assert r['body']['date_from'] == '2019-01-01' and r['body']['date_to'] == '2019-12-31'
    assert r['body']['mode'] == 'visuals', 'the mode is a separate dial'
    assert r['stored'] == 'exact'
    assert r['mode_lit'] == ['modebtn on', 'modebtn'] and r['ticks'][0] == 'aerial'


def test_the_date_clear_shows_only_when_a_date_is_set_and_clears_both(spa):
    r = spa['the_scope_and_dates_are_posted_with_the_search']
    assert 'hidden' in r['clear_before'].split(), r
    assert 'hidden' not in r['clear_after'].split(), r
    assert r['cleared'][0] == '' and r['cleared'][1] == ''
    assert 'hidden' in r['cleared'][2].split()


def test_the_scope_is_remembered_but_the_dates_are_not(spa):
    """A chinese-only week is a week; a date range is one search, and one
    silently carried into the next would drop most of what it found."""
    r = spa['the_scope_comes_back_from_localstorage_and_a_stale_one_does_not']
    assert r['saved']['posted'] == 'zh', r
    assert r['saved']['lit'] == ['modebtn', 'modebtn', 'modebtn on', 'modebtn']
    assert r['saved']['dates'] == [None, None], 'a fresh page has no range'
    # the server refuses a scope it does not know, so a stale value would 400
    # every search from this browser until localStorage was cleared by hand
    assert r['stale']['posted'] == 'both', r
    assert r['stale']['lit'] == ['modebtn on', 'modebtn', 'modebtn', 'modebtn']


def test_every_view_of_a_job_says_how_it_was_narrowed(spa):
    r = spa['the_scope_and_dates_show_on_the_running_job_and_the_recent_views']
    assert 'search in: english only' in r['ticker'], r['ticker']
    assert 'uploaded from 2019-01-01' in r['ticker'], r['ticker']
    assert r['ticker'].index('mode:') < r['ticker'].index('search in:') < r['ticker'].index('terms')
    assert r['jobshots'].startswith(
        'mode: news montage · search in: my term only · uploaded 2019-01-01 to 2019-12-31 · '), r
    assert r['rows'] == ['chinese only | uploaded 2019-01-01 to 2019-12-31',
                         'my term only | uploaded up to 2020-01-01',
                         '', '', ''], r['rows']


_SCOPE_ROW = re.compile(r"\{key: '([a-z]+)', label: '([^']+)', short: '([^']*)',")


def test_the_scope_table_matches_the_servers():
    """Same duplication the mode carries (claude_cli.TERM_SCOPES -> the
    toggle): the server refuses a scope that is not on ITS list, so a drift
    here is a 400 on every search."""
    from ytdlweb import claude_cli

    js = _js()
    block = js[js.index('const SEARCH_SCOPES = ['):js.index('const DEFAULT_SCOPE')]
    rows = _SCOPE_ROW.findall(block)
    assert [r[0] for r in rows] == list(claude_cli.TERM_SCOPES), rows
    for key, label, short in rows:
        assert label.strip(), key
        # the default is unlabelled on a job (the usual search); every other
        # scope names itself
        assert bool(short) == (key != claude_cli.DEFAULT_TERM_SCOPE), key
    assert f"const DEFAULT_SCOPE = '{claude_cli.DEFAULT_TERM_SCOPE}';" in js


def test_the_search_posts_the_scope_and_dates_and_the_paste_posts_none():
    js = _js()
    body = js[js.index('async function runSearch()'):js.index('async function runUrls()')]
    assert 'term_scope: state.termScope' in body, body
    assert '...dateRange()' in body, body
    paste = js[js.index('async function runUrls()'):js.index('async function startDownload()')]
    assert 'term_scope' not in paste and 'dateRange' not in paste, paste


def test_the_scope_row_and_the_date_inputs_are_in_the_markup():
    html = _html()
    for needle in ('id="scopes"', 'id="scopenote"', 'id="datefrom"', 'id="dateto"',
                   'id="dateclear"', 'type="date"'):
        assert needle in html, needle
    # the scope row sits between the shot boxes and the search box: chosen
    # before the topic is typed, like the mode and the boxes are
    assert html.index('id="modes"') < html.index('id="scopes"') < html.index('id="q"')
    # and [ CLEAR ] starts hidden: nothing to clear on a fresh page
    assert re.search(r'id="dateclear"[^>]*class="[^"]*\bhidden\b', html)


# ----------------- WP5/WP6 in source, for a machine with no node (2026-08-26)

def _evidence():
    js = _js()
    return js[js.index('function renderEvidence('):js.index('async function loadHealth()')]


def test_every_new_health_key_is_read_with_a_null_guard():
    """The strip is shipped by a dashboard deploy and read by whatever bundle
    the browser has cached, in both directions. `== null` (not `!h.x`) is the
    guard, because 'empty' / false / 0 are all real answers."""
    body = _evidence()
    for key in ('yt_dlp_version', 'cookies_state', 'pot_provider',
                'last_download', 'canary'):
        assert f'h.{key} == null' in body, key
    # the canary's two halves are guarded too: enabled must be strictly true,
    # and a canary that has never run is not a pip
    assert 'canary.enabled !== true' in body, body
    assert 'canary.last == null' in body, body


def test_the_pips_hide_themselves_rather_than_drawing_empty_boxes():
    js = _js()
    setpip = js[js.index('function setPip('):js.index('function renderEvidence(')]
    assert "pip.className = 'rstatus '" in setpip, setpip
    assert "(text ? '' : ' hidden')" in setpip, setpip
    # a cached index.html from before WP5 has none of these elements
    assert 'if (!pip) return;' in setpip, setpip


def test_the_relative_time_helper_says_no_em_dash_units():
    js = _js()
    ago = js[js.index('function agoText('):js.index('// One pip on the health strip')]
    for unit in ('sec ago', 'min ago', 'hr ago', 'days ago'):
        assert unit in ago, unit


def test_the_new_pips_are_in_the_markup_and_start_hidden():
    html = _html()
    for pip_id in ('healthytdlp', 'healthpot', 'healthdl', 'healthcanary'):
        assert re.search(rf'id="{pip_id}"[^>]*class="[^"]*\brstatus\b', html), pip_id
        assert re.search(rf'id="{pip_id}"[^>]*class="[^"]*\bhidden\b', html), pip_id
    # they sit beside the pip they extend, not in some other corner
    assert html.index('id="health"') < html.index('id="healthytdlp"')


def test_the_retry_posts_the_document_relative_download_url():
    """test_mounted_prefix.py pins the whole bundle, but this one is worth its
    own line: `/api/jobs/...` here would 404 against the dashboard root under
    the /ytdl mount (YTDL-42)."""
    js = _js()
    body = js[js.index('async function retryFailed()'):js.index('// How much of ONE video')]
    assert 'post(`api/jobs/${jobId}/download`)' in body, body
    assert '/api/jobs' not in body, body


def test_the_retry_is_offered_only_on_a_terminal_job_with_failures():
    js = _js()
    body = js[js.index('function renderRetry('):js.index('async function retryFailed()')]
    assert "job.phase === 'done' || job.phase === 'failed'" in body, body
    assert 'failed > 0' in body, body
    # the note is the job's own error, through the same hint table the banner
    # uses -- one field, one wording, wherever a failure is printed
    assert 'hintFor(job.error)' in body, body


def test_the_retry_button_and_its_note_are_in_the_markup():
    html = _html()
    assert '[ RETRY FAILED ]' in html, html
    assert re.search(r'id="dlretry"[^>]*class="[^"]*\bhidden\b', html)
    assert re.search(r'id="dlnote"[^>]*class="[^"]*\bhidden\b', html)
    # the note is ABOVE the button: it is what decides whether pressing it is
    # worth anything
    assert html.index('id="dlnote"') < html.index('id="dlretry"')
    # and both are inside the downloads panel, which is only on screen for a
    # job that has download rows at all
    assert html.index('id="downloads"') < html.index('id="dlnote"') < html.index('id="dllist"')


def test_the_retry_is_wired_up_and_rendered_for_every_phase():
    js = _js()
    assert "$('#dlretry').onclick = retryFailed;" in js, 'the button does nothing'
    prog = js[js.index('function renderProgress('):js.index('// [ RETRY N FAILED ]')]
    assert 'renderRetry(job);' in prog, \
        'the offer left by the last job outlives it unless every render clears it'


# ------------------------------------------- the term review + the queue
# 2026-08-30. Source assertions rather than harness scenarios, so they run on a
# machine with no node: what they pin is the markup and the wiring, which is
# where the two features can silently stop existing.

def test_the_term_review_is_in_the_markup_and_starts_hidden():
    html = _html()
    assert re.search(r'id="terms"[^>]*class="[^"]*\bhidden\b', html), html
    assert '[ TICK ALL ]' in html and '[ UNTICK ALL ]' in html
    assert 'SEARCH WITH THESE' in html
    assert 'id="termlist"' in html and 'id="termcount"' in html
    # ...above the review grid, because it comes before it in the job's life
    assert html.index('id="terms"') < html.index('id="review"')


def test_the_term_review_rows_are_a_tick_a_term_and_a_bracket():
    js = _js()
    body = js[js.index('function renderTermReview('):js.index('function renderTermCount(')]
    assert "job.phase === 'terms_review'" in body, body
    assert "box2.type = 'checkbox'" in body, body
    # the bracket is only drawn when there is something to put in it
    assert "t.translation || t.english_gloss" in body, body
    assert "'(' + tr + ')'" in body, body


def test_ticking_updates_the_count_without_a_round_trip():
    """The owner asked for ticking, not for a request per click. The count
    comes off the Set in the browser; the server hears about it once."""
    js = _js()
    body = js[js.index('function renderTermReview('):js.index('async function searchWithTheseTerms(')]
    assert 'renderTermCount(terms)' in body, body
    assert 'post(' not in body, 'ticking must not talk to the server'
    count = js[js.index('function renderTermCount('):js.index('function setAllTerms(')]
    assert '${n} of ${terms.length} terms' in count, count


def test_tick_all_and_untick_all_rewrite_the_whole_set():
    js = _js()
    body = js[js.index('function setAllTerms('):js.index('async function searchWithTheseTerms(')]
    assert 'new Set(on ? terms.map(t => t.id) : [])' in body, body
    assert "$('#termsall').onclick = () => setAllTerms(true);" in js
    assert "$('#termsnone').onclick = () => setAllTerms(false);" in js


def test_search_with_these_posts_the_set_then_continues():
    js = _js()
    body = js[js.index('async function searchWithTheseTerms('):
              js.index('// ----------------------------------------------------------------- queue')]
    assert 'post(`api/jobs/${jobId}/terms`, {enabled: [...state.termsOn]})' in body, body
    assert 'post(`api/jobs/${jobId}/terms/continue`)' in body, body
    # document-relative, like every other URL in this bundle (YTDL-42)
    assert '/api/jobs' not in body, body
    assert "$('#termsgo').onclick = searchWithTheseTerms;" in js


def test_the_queue_is_in_the_markup_and_starts_hidden():
    html = _html()
    assert re.search(r'id="queue"[^>]*class="[^"]*\bhidden\b', html), html
    assert 'id="queuelist"' in html
    # under the running job and above Recent searches: it is what the running
    # job is ahead of
    assert html.index('id="downloads"') < html.index('id="queue"') < \
        html.index('id="recent"')


def test_a_queue_row_names_the_job_and_offers_the_three_controls():
    js = _js()
    body = js[js.index('function renderQueue('):js.index('async function moveInQueue(')]
    for label in ('[ UP ]', '[ DOWN ]', '[ CANCEL ]'):
        assert label in body, body
    assert 'j.project_label' in body and 'j.term' in body, body
    assert "'pasted links'" in body, 'a url job has no term to print'
    # an empty queue is hidden rather than drawn as an empty box
    assert "classList.toggle('hidden', !q.length)" in body, body


def test_the_queue_moves_and_cancels_through_the_documented_routes():
    js = _js()
    move = js[js.index('async function moveInQueue('):js.index('async function cancelQueued(')]
    assert 'post(`api/jobs/${jobId}/queue/move`, {position})' in move, move
    cancel = js[js.index('async function cancelQueued('):
                js.index('// How much of ONE video')]
    assert 'post(`api/jobs/${jobId}/cancel`)' in cancel, cancel
    assert '/api/jobs' not in move + cancel


def test_the_search_form_says_queued_behind_instead_of_refusing():
    """The owner's queue, from the search box's point of view: a second search
    is no longer a red 409 toast naming a job the editor has lost sight of."""
    js = _js()
    body = js[js.index('function announceQueued('):js.index('const confirmDiscard')]
    assert 'queued_behind' in body, body
    assert 'queued behind ${plural(n' in body, body
    assert 'if (!n) return;' in body, 'the first search of the day says nothing'
    assert 'announceQueued(r);' in js


def test_the_queue_is_read_from_the_active_route_and_not_every_tick():
    js = _js()
    body = js[js.index('async function loadQueue('):js.index('function renderQueue(')]
    assert "api('api/jobs/active')" in body, body
    poll = js[js.index('async function poll()'):js.index('function detach()')]
    assert 'if (seen !== job.phase) loadQueue();' in poll, poll
