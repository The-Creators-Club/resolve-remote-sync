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

function makeContext(handler) {
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
  const ctx = {
    document, location: {hash: ''}, console,
    fetch: fetchStub,
    setTimeout: (fn, ms) => timers.set(fn, ms),
    clearTimeout: id => timers.clear(id),
    setInterval: (fn, ms) => { timers.intervals++; return -1; },
    clearInterval: () => {},
  };
  vm.createContext(ctx);
  return {ctx, els, get, timers, calls};
}

async function boot(handler) {
  const h = makeContext(handler);
  vm.runInContext(APP, h.ctx, {filename: 'app.js'});
  // Top-level const/let are lexical, not properties of the sandbox, so they
  // have to be re-exported. One at a time and forgivingly, so this harness can
  // also be pointed at an OLDER app.js (how the scenarios below were checked
  // to fail before the fix) without dying on the first renamed symbol.
  vm.runInContext(
    'globalThis.__ = {};'
    + '["state","banners","poll","attach","detach","runSearch","runUrls",'
    + '"toggle","bulk","loadHealth","loadProjects","loadManifest",'
    + '"renderProgress","renderTerms","renderGrid","toast","setBanner",'
    + '"visibleVideos"]'
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

// health/projects/topbar answers every scenario needs before it gets going.
function baseline(method, url) {
  if (url.startsWith('api/health')) {
    return {json: {claude: 'ok', claude_detail: '', yt_dlp: 'ok',
                   worker_alive: true, cookies: false}};
  }
  if (url.startsWith('api/projects')) {
    return {json: {projects: [{slug: 's', label: '2026/FF5/Energy'}],
                   projects_available: true, error: null}};
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
      return {json: {job_id: 21, phase: 'queued', term_dir: 'reef links',
                     queued: 1, skipped: [{video_id: 'IIIIIIIIIII',
                                           duplicate_of: '2025/FF4/Nuclear/old'}]}};
    }
    if (url === 'api/jobs/21') {
      return {json: POLLRES(JOB({id: 21, kind: 'urls', phase: 'queued'}))};
    }
    return {json: {}};
  });
  h.get('urls').value = ' https://youtu.be/JJJJJJJJJJJ \n https://youtu.be/IIIIIIIIIII ';
  h.get('folder').value = 'reef links';
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
    proc = subprocess.run([NODE, str(harness), str(APP_JS), str(STATIC / 'index.html')],
                          capture_output=True, text=True, timeout=120)
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
    r = spa['pasted_links_start_a_job']
    assert r['job_id'] == 21, r
    assert r['body'] == {'urls': 'https://youtu.be/JJJJJJJJJJJ \n https://youtu.be/IIIIIIIIIII',
                         'project_slug': 's', 'quality': '1080p',
                         'folder': 'reef links'}, r['body']
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


# --------------------------------------------------- source-level assertions
# These run with or without node: they are the cheap backstop for the shapes
# the harness proves, so a rewrite that reintroduces one is caught even on a
# machine with no JS runtime.

def _js():
    return APP_JS.read_text(encoding='utf-8')


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
