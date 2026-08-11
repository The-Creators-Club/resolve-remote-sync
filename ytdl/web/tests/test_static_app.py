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
    this.onclick = null; this._listeners = {};
  }
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
    const res = await handler(method, url, body);
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
    + '"visibleVideos","SHOT_TYPES","shotKeys","shotSummary","renderShots"]'
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
  thumbnail: null, job_id: 1, downloaded_by: 'alex',
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
    assert 'Claude did not answer in time' in r['after_failure'], r
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
def test_pasting_links_posts_the_whole_form_and_attaches_the_job(spa):
    """The form is the LINKS and the shared destination pickers, and nothing
    else: there is no folder field any more (owner, 2026-08-11), because a
    paste's clips go into the project's Youtube root."""
    r = spa['pasted_links_start_a_job']
    assert r['job_id'] == 21, r
    assert r['body'] == {'urls': 'https://youtu.be/JJJJJJJJJJJ \n https://youtu.be/IIIIIIIIIII',
                         'project_slug': 's', 'quality': '1080p'}, r['body']
    assert 'folder' not in r['body'], r['body']
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
    assert 'not running' in r['text'], r['text']
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


def test_the_search_posts_the_ticked_shot_types_in_source():
    js = _js()
    body = js[js.index('async function runSearch()'):js.index('async function runUrls()')]
    assert 'shot_types: shotKeys()' in body, body
    # ...and the paste box does NOT: a url job is never searched or filtered
    paste = js[js.index('async function runUrls()'):js.index('async function startDownload()')]
    assert 'shot_types' not in paste, paste


def test_the_paste_box_has_no_folder_field_left_anywhere():
    """Owner, 2026-08-11: a paste's destination is the project, and its clips go
    into that project's Youtube root -- there is no folder to name, in the
    markup, in the POST or in the stylesheet."""
    js, html, css = _js(), _html(), _css()
    assert 'id="folder"' not in html, html[html.index('id="urls"'):][:400]
    paste = js[js.index('async function runUrls()'):js.index('async function startDownload()')]
    assert 'folder:' not in paste, paste          # not posted
    assert "$('#folder')" not in paste, paste     # and not read
    assert '#folder' not in css


def test_the_reveal_goes_to_the_companion_loopback_with_a_relative_path():
    """The ONLY way a page served from the NAS can open a folder on the
    editor's machine -- b-roll's precedent, and the same reason its
    tests/test_mounted_prefix.py tolerates one absolute URL. The body carries a
    path relative to the Projects root: the page must not learn a drive
    letter."""
    js = _js()
    assert "const COMPANION_URL = 'http://127.0.0.1:8899';" in js
    body = js[js.index('async function reveal(d)'):js.index('function noCompanion(')]
    assert '`${COMPANION_URL}/ytdl/reveal`' in body, body
    assert 'rel_path: d.reveal_path' in body, body
    # every failure shape ends at the same place: a message and the path --
    # nothing listening, a companion too old for the route, and any refusal
    assert body.count('noCompanion(') == 3, body


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


def test_localstorage_is_never_allowed_to_break_the_page():
    """It throws outright in some privacy modes, and a page that cannot
    remember the ticks must still be able to search."""
    js = _js()
    body = js[js.index('function loadShots()'):js.index('function renderShotNote()')]
    assert body.count('try {') >= 2 and body.count('catch') >= 2, body
    assert "const SHOTS_KEY = 'ytdl.shot_types'" in js
