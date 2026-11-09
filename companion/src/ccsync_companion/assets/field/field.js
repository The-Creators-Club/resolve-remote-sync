/* Field backup page. Served by the CC Sync companion (field_server.py); talks only to it. No
   network beyond 127.0.0.1, no libraries. Everything from the server goes into the page as
   text nodes (textContent), never as markup. */
'use strict';
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var S = { data: null, card: null, ticks: new Set(), ticksInit: false, sigs: {}, lanes: {}, busy: false, timer: null };

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = text;
    return n;
  }
  function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
  function chip(text, cls) { return el('span', 'chip' + (cls ? ' ' + cls : ''), text); }

  function fmtBytes(n) {
    n = Number(n) || 0;
    var u = ['B', 'KB', 'MB', 'GB', 'TB'], i = 0;
    while (n >= 1000 && i < u.length - 1) { n /= 1000; i++; }
    return (i === 0 ? n.toFixed(0) : n < 100 ? n.toFixed(1) : n.toFixed(0)) + ' ' + u[i];
  }
  function fmtEta(s) {
    if (s === null || s === undefined) return '';
    s = Math.round(s);
    if (s < 90) return s + ' s';
    if (s < 5400) return Math.round(s / 60) + ' min';
    return (s / 3600).toFixed(1) + ' h';
  }
  function ago(ts) {
    if (!ts) return 'never';
    var s = Math.max(0, Date.now() / 1000 - ts);
    if (s < 60) return 'just now';
    if (s < 3600) return Math.round(s / 60) + ' min ago';
    if (s < 172800) return Math.round(s / 3600) + ' h ago';
    return Math.round(s / 86400) + ' days ago';
  }
  var KIND_NAMES = { ours: 'Ours', laptop: 'Laptop', nas: 'Home NAS', client: 'Client drive', card: 'Card', unknown: 'Kind not set' };
  var CARD_KINDS = { sony: 'Sony', bmcc: 'Blackmagic', drone: 'Drone', audio: 'Audio', generic: 'Card' };

  function api(path, body) {
    var opts = body === undefined ? { cache: 'no-store' } :
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
    return fetch(path, opts).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (!r.ok || j.ok === false) { var e = new Error(j.error || ('HTTP ' + r.status)); e.status = r.status; throw e; }
        return j;
      });
    });
  }
  var toastTimer = null;
  function toast(msg) {
    var t = $('toast'); t.textContent = msg; t.hidden = false;
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.hidden = true; }, 9000);
  }

  // ------------------------------------------------------------------------------- header
  function renderChips(d) {
    var box = $('chips'); clear(box);
    var s = d.sync || {};
    if (s.pending) box.appendChild(chip(s.pending + ' waiting to send', 'warn'));
    if (s.online === true) box.appendChild(chip('Ledger online', 'ok'));
    else if (s.online === false) box.appendChild(chip('Offline', 'line warn'));
    else box.appendChild(chip(s.dashboard ? 'Ledger not asked yet' : 'No dashboard', 'line'));
    var c = d.copier || {};
    var cc = chip(c.name || 'copier', 'line ok'); cc.title = c.verify || ''; box.appendChild(cc);
    box.appendChild(chip(d.machine || '', 'line'));
  }

  // -------------------------------------------------------------------------------- cards
  function renderCards(d) {
    var cards = d.cards || [];
    if (!cards.some(function (c) { return c.serial === S.card; })) S.card = cards.length ? cards[0].serial : null;
    var sig = JSON.stringify([S.card, cards.map(function (c) { return [c.serial, c.label, c.files, c.bytes, c.verdict, c.copying]; })]);
    if (S.sigs.cards === sig) return;
    S.sigs.cards = sig;
    var box = $('cards'); clear(box);
    if (!cards.length) {
      box.appendChild(el('div', 'empty', 'No card in a reader. Put one in; this page looks every few seconds.'));
      return;
    }
    cards.forEach(function (c) {
      var wrapper = el('div', 'card'); wrapper.setAttribute('aria-current', c.serial === S.card ? 'true' : 'false');
      var b = el('button', 'cardbtn'); b.type = 'button';
      b.setAttribute('aria-pressed', c.serial === S.card ? 'true' : 'false');
      var row = el('div', 'row');
      row.appendChild(el('span', 'name', c.label));
      row.appendChild(chip(CARD_KINDS[c.kind] || c.kind, 'line'));
      if (c.copying) row.appendChild(chip('Copying', ''));
      b.appendChild(row);
      b.appendChild(el('div', 'meta', c.files + ' files · ' + fmtBytes(c.bytes) + ' · ' + c.drive + ' · lands in "' + c.folder + '"'));
      var v = c.verdict || {};
      var vb = el('div', 'verdict ' + (v.state === 'safe' ? (v.flags && v.flags.indexOf('laptop-only') >= 0 ? 'laptop' : 'safe') : v.state === 'unsafe' ? 'unsafe' : ''));
      var big = v.state === 'safe' ? (v.flags && v.flags.indexOf('laptop-only') >= 0 ? 'Safe to format · laptop only' : 'Safe to format')
        : v.state === 'unsafe' ? 'Not safe to format' : 'Nothing to back up';
      vb.appendChild(el('span', 'big', big));
      vb.appendChild(el('span', 'sub', v.headline || ''));
      b.appendChild(vb);
      (v.notes || []).forEach(function (n) { b.appendChild(el('div', 'meta', n)); });
      wrapper.appendChild(b);
      if (v.atRisk && v.atRisk.length) {
        var det = el('details'); det.appendChild(el('summary', null, 'Files that are short of copies (' + (v.tracked - v.safe) + ')'));
        var ul = el('ul');
        v.atRisk.forEach(function (f) { ul.appendChild(el('li', null, f.path + ' (' + (f.counted || 0) + ' counting, ' + f.copies + ' in all)')); });
        det.appendChild(ul); wrapper.appendChild(det);
      }
      b.addEventListener('click', function () { S.card = c.serial; S.sigs.cards = ''; S.sigs.dests = ''; render(S.data); });
      box.appendChild(wrapper);
    });
  }

  // ---------------------------------------------------------------------------- destinations
  function selectedCard() {
    var cs = (S.data && S.data.cards) || [];
    for (var i = 0; i < cs.length; i++) if (cs[i].serial === S.card) return cs[i];
    return null;
  }
  function renderDests(d) {
    var dests = d.destinations || [];
    if (!S.ticksInit) {
      (d.lastDests || []).forEach(function (id) {
        var m = dests.filter(function (x) { return x.id === id && x.present; })[0];
        if (m) S.ticks.add(id);
      });
      S.ticksInit = true;
    }
    var card = selectedCard();
    var per = (card && card.verdict && card.verdict.perDest) || {};
    var sig = JSON.stringify([S.card, dests.map(function (x) { return [x.id, x.label, x.kind, x.present, x.why, x.busy, x.detail, x.settable, x.removable]; }), per, Array.from(S.ticks)]);
    var box = $('dests');
    if (S.sigs.dests !== sig) {
      S.sigs.dests = sig; clear(box);
      if (!dests.length) box.appendChild(el('div', 'empty', 'No drive to copy to. Plug one in, or add a folder below.'));
      dests.forEach(function (x) {
        var row = el('div', 'dest' + (S.ticks.has(x.id) ? ' ticked' : '') + (x.present ? '' : ' absent'));
        row.dataset.id = x.id;
        var cb = el('input'); cb.type = 'checkbox'; cb.checked = S.ticks.has(x.id) && x.present; cb.disabled = !x.present || x.busy;
        cb.setAttribute('aria-label', 'Copy to ' + x.label);
        cb.addEventListener('change', function () {
          if (cb.checked) S.ticks.add(x.id); else S.ticks.delete(x.id);
          row.classList.toggle('ticked', cb.checked); S.sigs.dests = ''; updateGo(); api('/field/api/remember', { dests: Array.from(S.ticks) }).catch(function () { });
        });
        row.appendChild(cb);
        var name = el('div', 'name');
        name.appendChild(el('span', null, x.label));
        name.appendChild(chip({ drive: 'Drive', folder: 'Folder', pool: 'NAS' }[x.type] || x.type, 'line'));
        name.appendChild(chip(KIND_NAMES[x.kind] || x.kind, x.counts ? 'line ok' : (x.kind === 'unknown' ? 'line warn' : 'line')));
        if (x.settable) {
          var sel = el('select'); sel.setAttribute('aria-label', 'What ' + x.label + ' is');
          [['', 'Set kind…'], ['ours', 'Ours (counts)'], ['laptop', 'Laptop (counts, flagged)'], ['client', 'Client drive (never counts)'], ['unknown', 'Not set']].forEach(function (o) {
            var op = el('option', null, o[1]); op.value = o[0]; sel.appendChild(op);
          });
          sel.addEventListener('change', function () {
            if (!sel.value) return;
            api('/field/api/kind', { volumeId: x.volumeId, kind: sel.value }).then(function () { refresh(true); }).catch(function (e) { toast(e.message); });
          });
          name.appendChild(sel);
        }
        if (x.removable) {
          var rm = el('button', 'btn small', 'Remove'); rm.type = 'button';
          rm.addEventListener('click', function () { api('/field/api/folder/remove', { path: x.id.replace(/^folder:/, '') }).then(function () { refresh(true); }); });
          name.appendChild(rm);
        }
        row.appendChild(name);
        var sub = el('div', 'sub'); sub.dataset.sub = '1'; row.appendChild(sub);
        if (x.why) row.appendChild(el('div', 'why', x.why));
        var p = per[x.id];
        if (p && p.of) row.appendChild(el('div', 'sub', 'Already holds ' + p.have + ' of ' + p.of + ' files on this card'));
        box.appendChild(row);
      });
    }
    dests.forEach(function (x) {   // numbers that move are updated in place, so an open menu survives
      var row = box.querySelector('[data-id="' + (window.CSS && CSS.escape ? CSS.escape(x.id) : x.id) + '"] [data-sub]');
      if (row) row.textContent = x.detail + (x.free !== null && x.free !== undefined ? ' · ' + fmtBytes(x.free) + ' free' : '');
    });
    updateGo();
  }

  function updateGo() {
    var go = $('go'), note = $('go-note');
    var card = selectedCard();
    var dests = ((S.data && S.data.destinations) || []).filter(function (x) { return S.ticks.has(x.id) && x.present && !x.busy; });
    var why = '';
    if (S.busy) why = 'Starting…';
    else if (!card) why = 'Put a card in a reader.';
    else if (card.copying) why = 'This card is being copied.';
    else if (!dests.length) why = 'Tick where to copy it.';
    go.disabled = !!why;
    go.textContent = dests.length > 1 ? 'Copy to all (' + dests.length + ')' : 'Copy to all';
    if (why) { note.textContent = why; note.className = 'note'; }
    else {
      var folder = card.folder;
      note.className = 'note';
      note.textContent = 'Only what is not already there is copied; nothing is overwritten. Lands in "' + folder + '".';
    }
  }

  // ------------------------------------------------------------------------------------ runs
  var STATE_TEXT = { queued: 'Waiting', planning: 'Looking', checking: 'Checking', copying: 'Copying', done: 'Done',
    attention: 'Needs a look', failed: 'Failed', stopped: 'Stopped', refused: 'Not started' };
  var STATE_CLS = { done: 'ok', attention: 'warn', failed: 'bad', stopped: 'bad', refused: 'bad' };

  function laneEl(l) {
    var key = l.runId + '|' + l.dest;
    var n = S.lanes[key];
    if (n) return n;
    n = { root: el('div', 'lane') };
    var head = el('div', 'lane-head');
    n.name = el('span', 'name'); n.kind = el('span', 'chip line'); n.st = el('span', 'chip'); n.pct = el('span', 'pct mono');
    head.appendChild(n.name); head.appendChild(n.kind); head.appendChild(n.st); head.appendChild(n.pct);
    n.bar = el('div', 'bar'); n.fill = el('i'); n.bar.appendChild(n.fill);
    n.stats = el('div', 'stats'); n.cur = el('div', 'cur'); n.msg = el('div', 'msg'); n.prob = el('ul', 'problems');
    [head, n.bar, n.stats, n.cur, n.msg, n.prob].forEach(function (x) { n.root.appendChild(x); });
    S.lanes[key] = n;
    return n;
  }
  function updateLane(l) {
    var n = laneEl(l);
    var verifying = l.state === 'copying' && l.phase === 'verify';
    n.root.className = 'lane ' + l.state;
    n.name.textContent = l.label;
    n.kind.textContent = KIND_NAMES[l.volumeKind] || l.volumeKind;
    n.st.className = 'chip ' + (STATE_CLS[l.state] || '');
    n.st.textContent = verifying ? 'Verifying' : (l.state === 'checking' ? 'Checking what is there' : STATE_TEXT[l.state] || l.state);
    n.pct.textContent = Math.floor(l.percent) + '%';
    n.fill.style.width = Math.max(0, Math.min(100, l.percent)) + '%';
    var parts = [fmtBytes(l.bytesDone) + ' of ' + fmtBytes(l.bytesTotal)];
    if (l.bps > 0) parts.push(fmtBytes(l.bps) + '/s');
    if (l.etaS !== null && l.etaS !== undefined) parts.push('ETA ' + fmtEta(l.etaS));
    parts.push(l.filesDone + ' of ' + l.filesTotal + ' files');
    if (l.copier && l.state === 'copying') parts.push(l.copier === 'teracopy' ? 'TeraCopy' : 'built-in copier');
    n.stats.textContent = l.state === 'refused' ? '' : parts.join(' · ');
    n.cur.textContent = (l.state === 'copying' || l.state === 'checking') ? (l.current || l.stage || '') : '';
    n.msg.textContent = l.message || '';
    n.msg.className = 'msg' + (l.state === 'failed' || l.state === 'refused' || l.state === 'stopped' ? ' bad' : '');
    var pk = JSON.stringify(l.problems);
    if (n.pk !== pk) {
      n.pk = pk; clear(n.prob);
      l.problems.forEach(function (p) { n.prob.appendChild(el('li', null, p.path + ': ' + p.why)); });
    }
    return n.root;
  }
  function renderRuns(d) {
    var box = $('runs');
    var runs = (d.runs || []).slice(0, 3);
    var ids = JSON.stringify(runs.map(function (r) { return [r.id, r.running, r.lanes.map(function (l) { return l.dest; })]; }));
    if (S.sigs.runs !== ids) {
      S.sigs.runs = ids; clear(box);
      if (!runs.length) box.appendChild(el('div', 'empty', 'Nothing copying. Pick a card, tick where it goes, and press Copy to all.'));
      runs.forEach(function (r) {
        var wrap = el('div', 'run'); wrap.dataset.run = r.id;
        var head = el('div', 'run-head');
        head.appendChild(el('span', 't', (r.card.label || r.card.serial) + ' → ' + r.folder));
        var stop = el('button', 'btn small', 'Stop'); stop.type = 'button'; stop.dataset.stop = r.id;
        stop.addEventListener('click', function () { api('/field/api/cancel', { runId: r.id }).then(function () { refresh(true); }); });
        head.appendChild(stop);
        wrap.appendChild(head);
        r.lanes.forEach(function (l) { wrap.appendChild(laneEl(l).root); });
        box.appendChild(wrap);
      });
    }
    runs.forEach(function (r) {
      r.lanes.forEach(updateLane);
      var stop = box.querySelector('[data-stop="' + r.id + '"]');
      if (stop) { stop.hidden = !r.running; stop.textContent = r.cancelled ? 'Stopping…' : 'Stop'; stop.disabled = r.cancelled; }
    });
  }

  // ------------------------------------------------------------------------------------ ledger
  function renderSync(d) {
    var s = d.sync || {};
    var sig = JSON.stringify([s.pending, s.online, s.at, s.error, s.running, s.mirrorRows, s.mirrorPulledAt, s.flushed, s.dashboard]);
    if (S.sigs.sync === sig) return;
    S.sigs.sync = sig;
    var box = $('sync'); clear(box);
    var kv = el('dl', 'kv');
    function row(k, v) { kv.appendChild(el('dt', null, k)); kv.appendChild(el('dd', null, v)); }
    row('Waiting to send', String(s.pending || 0) + ' copies');
    row('Last tried', s.at ? ago(s.at) : 'not yet');
    row('Ledger on this laptop', (s.mirrorRows || 0) + ' copies, updated ' + ago(s.mirrorPulledAt));
    box.appendChild(kv);
    if (s.error) box.appendChild(el('div', 'msg', s.error));
    else if (!s.dashboard) box.appendChild(el('div', 'msg', 'No dashboard is set up here. Copies are kept on this laptop.'));
    var b = el('button', 'btn', s.running ? 'Sending…' : 'Send and refresh now'); b.type = 'button'; b.disabled = !!s.running || !s.dashboard;
    b.addEventListener('click', function () { api('/field/api/sync', {}).then(function () { setTimeout(function () { refresh(true); }, 1500); }); });
    box.appendChild(b);
  }

  // -------------------------------------------------------------------------------------- loop
  function render(d) {
    if (!d) return;
    S.data = d;
    renderChips(d); renderCards(d); renderDests(d); renderRuns(d); renderSync(d);
  }
  function anyRunning() { return !!(S.data && (S.data.runs || []).some(function (r) { return r.running; })); }
  function refresh(force) {
    return api('/field/api/state' + (force ? '?refresh=1' : '')).then(render).catch(function () {
      clear($('chips')); $('chips').appendChild(chip('Companion not answering', 'bad'));
    }).then(schedule);
  }
  function schedule() {
    clearTimeout(S.timer);
    S.timer = setTimeout(function () {
      if (document.hidden) { schedule(); return; }
      refresh(false);
    }, anyRunning() ? 1000 : 4000);
  }

  $('refresh').addEventListener('click', function () { refresh(true); });
  $('add-folder').addEventListener('submit', function (ev) {
    ev.preventDefault();
    var inp = $('folder-path'), v = inp.value.trim();
    if (!v) return;
    api('/field/api/folder', { path: v }).then(function () { inp.value = ''; return refresh(true); }).catch(function (e) { toast(e.message); });
  });
  $('go').addEventListener('click', function () {
    var card = selectedCard();
    if (!card) return;
    var ids = Array.from(S.ticks);
    S.busy = true; updateGo();
    api('/field/api/copy', { serial: card.serial, dests: ids }).then(function () { S.busy = false; return refresh(true); })
      .catch(function (e) { S.busy = false; updateGo(); toast(e.message); });
  });
  document.addEventListener('visibilitychange', function () { if (!document.hidden) refresh(false); });
  refresh(true);
})();
