// THE /cards PICKER, OFFLINE (2026-10-11, Alex: "the whole thing works end to
// end launched from zero on an aeroplane, as long as you've opened it once
// before getting on" / "you should be able to launch any project file which
// has been downloaded. There should be a mark for downloaded projects").
//
// The worker is cards_landing.py CARDS_SW. This file is the page's half:
//   * REGISTERS it (scope /cards/), and on a visit the worker did not serve
//     hands it the page and every asset this page loaded, so the first visit
//     is already enough for the next launch to work with no network;
//   * MARKS every episode holding a cut list downloaded on this device
//     ("downloaded"), with one button per cut list, and lists them all in an
//     "on this device" window at the top;
//   * LAUNCHES one: it names the copy in `cards_offline_last`, which is the
//     key the episode page's 15-offline.js oflLoad adopts on a cold offline
//     open (one origin, one localStorage), then goes to that episode;
//   * when the worker served the saved copy (`meta[name=cards-offline]`),
//     says so and disables what needs the server.
//
// What "downloaded" means is the episode page's own store, read only: the
// IndexedDB `cards-offline` index (one row per copy, keyed by the cut list's
// path on the server), plus the episode's own worker having saved its page
// (`cards-shell-*` holds `/cards/p/<slug>/`). A copy with no saved page
// cannot open offline, and is shown as such rather than as a button that
// would land on nothing.
(function () {
  'use strict';

  var page = document.querySelector('.cl');
  if (!page) return;
  var savedAt = document.querySelector('meta[name="cards-offline"]');
  // WORKING OFFLINE BY CHOICE (Alex, 2026-10-22: "enable offline mode even
  // if I'm online, in all the apps, and in the browser"). The episode page
  // keeps the switch in this same origin's localStorage (the Timeline Cards
  // repo's 15-offline.js OFLFORCE), so the list honours it too: offline
  // mode with the server up. In the Windows / Android app the app's own
  // local server holds the same switch (docs/NATIVE-APPS.md there).
  var FORCEKEY = 'cards_force_offline';
  var forced = false;
  try { forced = localStorage.getItem(FORCEKEY) === '1'; } catch (e) { /* no storage: never forced */ }
  var inApp = location.hostname === '127.0.0.1' && location.port === '47823';
  var offline = !!savedAt || forced;
  function setForced(on) {
    try { if (on) localStorage.setItem(FORCEKEY, '1'); else localStorage.removeItem(FORCEKEY); } catch (e) { /* */ }
    var tell = inApp
      ? fetch('/__app/api/offline', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                     body: JSON.stringify({on: !!on})}).catch(function () { return null; })
      : Promise.resolve(null);
    tell.then(function () { window.location.href = '/cards/'; });
  }

  // ------------------------------------------------------------- the worker
  // Registers it, makes sure the phone is running THIS release's bytes, and
  // hands over what this visit loaded. Three things the first draft got
  // wrong, each found by driving a real Chrome (tools/cards_offline_launch.js):
  //   * `register()` of a URL already registered does NOT look for new bytes,
  //     so a phone still holding an older worker at /cards/sw.js kept it until
  //     Chrome's own once-a-day check. `reg.update()` asks now.
  //   * a fresh worker claims this page while `ready` is resolving, so the
  //     old "was the page served by us?" test (`controller` is ours) was true
  //     on the very first visit, nothing saved the PAGE, and the next launch
  //     had assets and no page. Whether THIS document went through a worker
  //     is on the navigation entry (workerStart), and the worker itself also
  //     saves the page whenever it has none.
  //   * a worker that takes the page over LATER (the update above) is not the
  //     one that was messaged: `controllerchange` hands over again.
  function handOver(reg) {
    var to = navigator.serviceWorker.controller || (reg && reg.active);
    if (!to) return;
    var viaWorker = false;
    try {
      var nav = performance.getEntriesByType('navigation')[0];
      viaWorker = !!(nav && nav.workerStart > 0);
    } catch (e) { /* no timing API: the worker saves the page when it has none */ }
    var assets = [];
    try {
      (performance.getEntriesByType('resource') || []).forEach(function (en) {
        assets.push(en.name);
      });
    } catch (e) { /* no timing API: the tags below are enough */ }
    document.querySelectorAll('link[href], script[src]').forEach(function (el) {
      assets.push(el.href || el.src);
    });
    to.postMessage({type: 'cards-landing-save', page: !viaWorker, assets: assets});
  }
  if (window.isSecureContext && 'serviceWorker' in navigator && !offline) {
    var regd = null;
    navigator.serviceWorker.addEventListener('controllerchange', function () { handOver(regd); });
    navigator.serviceWorker.register('/cards/sw.js', {scope: '/cards/'})
      .then(function (reg) {
        regd = reg;
        try { reg.update().catch(function () { /* offline: nothing to learn */ }); } catch (e) { /* */ }
        return navigator.serviceWorker.ready;
      })
      .then(function (reg) { regd = reg; handOver(reg); })
      .catch(function () { /* no worker: the page still works online */ });
  }

  // -------------------------------------------------------------- the store
  function readIndex() {
    return new Promise(function (res) {
      if (!window.indexedDB) { res({}); return; }
      var rq;
      try { rq = indexedDB.open('cards-offline'); } catch (e) { res({}); return; }
      // no store yet means nothing downloaded: do not create it from here
      rq.onupgradeneeded = function () { try { rq.transaction.abort(); } catch (e) { /* */ } };
      rq.onerror = function () { res({}); };
      rq.onsuccess = function () {
        var db = rq.result;
        try {
          var g = db.transaction('kv', 'readonly').objectStore('kv').get('index');
          g.onsuccess = function () { db.close(); res(g.result && typeof g.result === 'object' ? g.result : {}); };
          g.onerror = function () { db.close(); res({}); };
        } catch (e) { db.close(); res({}); }
      };
    });
  }

  function savedShells() {
    if (!window.caches) return Promise.resolve({});
    return caches.keys().then(function (names) {
      return Promise.all(names.filter(function (n) { return n.indexOf('cards-shell-') === 0; })
        .map(function (n) { return caches.open(n).then(function (c) { return c.keys(); }); }));
    }).then(function (lists) {
      var out = {};
      lists.forEach(function (reqs) {
        reqs.forEach(function (r) {
          var m = /\/cards\/p\/([^/]+)\/$/.exec(new URL(r.url).pathname);
          if (m) out[m[1]] = true;
        });
      });
      return out;
    }).catch(function () { return {}; });
  }

  function norm(p) {
    p = String(p || '');
    try { p = p.normalize('NFC'); } catch (e) { /* */ }
    return p.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
  }

  // ---------------------------------------------------------------- drawing
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function baseName(p) { return String(p || '').split(/[\\/]/).pop(); }
  function when(ms) {
    if (!ms) return '';
    try { return new Date(Number(ms)).toLocaleString(); } catch (e) { return ''; }
  }

  function launch(key, slug, row) {
    try { localStorage.setItem('cards_offline_last', key); } catch (e) { /* */ }
    var state = row ? row.getAttribute('data-state') : '';
    if (offline || state === 'ready' || !row) {
      window.location.href = '/cards/p/' + encodeURIComponent(slug) + '/';
      return;
    }
    // online and not open on the server: open it the ordinary way, and the
    // dispatcher brings this browser in when it is ready
    var form = row.querySelector('form[action="/cards/open"]');
    if (form) form.submit();
    else window.location.href = '/cards/p/' + encodeURIComponent(slug) + '/';
  }

  function copyButton(c) {
    var b = el('button', 'key sm primary cl-offline-open');
    b.type = 'button';
    b.appendChild(el('span', 't', 'open ' + (c.file || 'cut list')));
    b.title = 'Opens the copy of ' + (c.file || 'this cut list') + ' saved on this device'
      + (c.q ? '. ' + c.q + ' edit' + (c.q === 1 ? '' : 's') + ' wait to sync.' : '.');
    b.addEventListener('click', function () { launch(c.key, c.slug, c.row); });
    return b;
  }

  function draw(copies) {
    var bySlug = {};
    copies.forEach(function (c) { if (c.slug) (bySlug[c.slug] = bySlug[c.slug] || []).push(c); });

    // the mark on every row and tile of an episode with a copy
    Object.keys(bySlug).forEach(function (slug) {
      var list = bySlug[slug];
      var ok = list.some(function (c) { return c.shell; });
      page.querySelectorAll('.cl-ep[data-slug="' + slug + '"]').forEach(function (row) {
        var nameLine = row.querySelector('.cl-name');
        var tag = el('span', 'tag ' + (ok ? 'ok' : 'warn') + ' cl-badge cl-badge-offline',
                     ok ? 'downloaded' : 'downloaded, page not saved');
        tag.title = ok ? 'A cut list of this episode is saved on this device and opens with no network.'
                       : 'A cut list is saved, but this episode\'s page is not: open the episode once with a connection.';
        if (nameLine) nameLine.appendChild(tag);
        if (!ok) return;
        var line = el('div', 'enote cl-note cl-offline-line');
        list.forEach(function (c) { if (c.shell) line.appendChild(copyButton(c)); });
        var info = row.querySelector('.cl-info');
        if (info) info.appendChild(line);
      });
    });

    // everything on this device, at the top
    var usable = copies.filter(function (c) { return c.slug && c.shell; });
    var stranded = copies.filter(function (c) { return !(c.slug && c.shell); });
    if (!usable.length && !stranded.length) return;
    var win = el('section', 'win cl-offline');
    win.setAttribute('aria-label', 'Cut lists on this device');
    var bar = el('div', 'bar');
    bar.appendChild(el('h2', 't', 'ON THIS DEVICE'));
    bar.appendChild(el('span', 'bar-rule'));
    bar.appendChild(el('span', 'meta', usable.length + ' cut list' + (usable.length === 1 ? '' : 's') + ' open offline'));
    win.appendChild(bar);
    var body = el('div', 'body vstack');
    usable.concat(stranded).forEach(function (c) {
      var r = el('div', 'ep cl-ep-offline');
      // .ep is a grid whose first column is the state icon (components.css):
      // without one the name was squeezed into the 2ch icon column and
      // wrapped a letter to a line on a phone.
      var ico = el('span', 'ico cl-ico', '\u25AA');
      ico.setAttribute('aria-hidden', 'true');
      r.appendChild(ico);
      var info = el('div', 'cl-info');
      var nm = el('div', 'nmline');
      nm.appendChild(el('span', 'nm', (c.episode || 'unknown episode') + ': ' + (c.file || 'cut list')));
      info.appendChild(nm);
      var bits = [];
      if (c.cuts) bits.push(c.cuts + ' cuts');
      if (c.q) bits.push(c.q + ' edit' + (c.q === 1 ? '' : 's') + ' waiting to sync');
      if (c.when) bits.push('saved ' + when(c.when));
      if (!c.slug) bits.push('its episode is not in this list');
      else if (!c.shell) bits.push('the episode page is not saved: open the episode once with a connection');
      info.appendChild(el('div', 'meta', bits.join(', ')));
      r.appendChild(info);
      var act = el('div', 'act');
      if (c.slug && c.shell) act.appendChild(copyButton(c));
      r.appendChild(act);
      body.appendChild(r);
    });
    win.appendChild(body);
    var before = page.querySelector('.cl-panel') || page.querySelector('.cl-browse');
    if (before) before.parentNode.insertBefore(win, before);
    else page.appendChild(win);
  }

  function offlineMode() {
    var at = Number(savedAt ? savedAt.getAttribute('content') || 0 : 0);
    var note = el('div', 'note warn cl-offline-note');
    note.setAttribute('role', 'status');
    note.appendChild(el('span', 'tag solid warn', 'offline'));
    note.appendChild(el('span', 'grow', forced
      ? 'You are working offline by choice. Cut lists marked downloaded open from this device, and their'
        + ' edits wait here until you go back online. Opening or closing anything else needs the server.'
      : 'The server cannot be reached. This is the episode list as of ' + (when(at) || 'your last visit')
      + '. Cut lists marked downloaded open from this device and sync when the server is back.'
      + ' Opening or closing anything else needs the server.'));
    var head = page.querySelector('.head');
    if (head && head.nextSibling) head.parentNode.insertBefore(note, head.nextSibling);
    else page.insertBefore(note, page.firstChild);
    page.querySelectorAll('form[action="/cards/open"] button, form[action="/cards/close"] button')
      .forEach(function (b) { b.disabled = true; b.title = 'Needs the server, which cannot be reached.'; });
    if (forced) {
      var back = el('button', 'key sm primary', 'go back online');
      back.type = 'button';
      back.addEventListener('click', function () { setForced(false); });
      note.appendChild(back);
    } else {
      var retry = el('a', 'key sm', 'try the server again');
      retry.href = '/cards/';
      note.appendChild(retry);
    }
  }

  function onlineSwitch() {
    var bar = el('div', 'enote cl-note cl-offline-switch');
    var b = el('button', 'key sm', 'work offline');
    b.type = 'button';
    b.title = 'Use the cut lists downloaded on this device even with the server up, as on a plane.'
      + ' Nothing goes to the server until you go back online.';
    b.addEventListener('click', function () { setForced(true); });
    bar.appendChild(b);
    var head = page.querySelector('.head');
    if (head && head.nextSibling) head.parentNode.insertBefore(bar, head.nextSibling);
    else page.insertBefore(bar, page.firstChild);
  }

  if (offline) offlineMode();
  else onlineSwitch();

  Promise.all([readIndex(), savedShells()]).then(function (got) {
    var index = got[0], shells = got[1];
    var keys = Object.keys(index);
    if (!keys.length) return;
    var roots = [];
    page.querySelectorAll('.cl-ep[data-slug][data-root]').forEach(function (row) {
      roots.push({slug: row.getAttribute('data-slug'), root: norm(row.getAttribute('data-root')), row: row,
                  name: (row.querySelector('.cl-name-text') || {}).textContent || ''});
    });
    var shellSlugs = Object.keys(shells);
    var copies = keys.map(function (key) {
      var ix = index[key] || {};
      var path = norm(ix.path || key);
      var best = null;
      roots.forEach(function (r) {
        if (r.root && (path === r.root || path.indexOf(r.root + '/') === 0)
            && (!best || r.root.length > best.root.length)) best = r;
      });
      // no path to go by, and only one episode page saved: that is the one
      if (!best && shellSlugs.length === 1) {
        roots.forEach(function (r) { if (r.slug === shellSlugs[0]) best = r; });
      }
      return {key: key, file: ix.file || baseName(ix.path || key), q: ix.q | 0, cuts: ix.cuts | 0,
              when: ix.when, slug: best ? best.slug : '', row: best ? best.row : null,
              episode: best ? best.name.trim() : '', shell: !!(best && shells[best.slug])};
    });
    copies.sort(function (a, b) { return (b.when || 0) - (a.when || 0); });
    draw(copies);
  });
})();
