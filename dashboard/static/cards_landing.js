// THE /cards PICKER (2026-09-24, Alex: "ordered by most recently opened ...
// filterable by year, by last opened, by largest, by date, alphabetically,
// and also searchable").
//
// The page is complete without this file: the folders are <details>, every
// button is a real form, and the server draws the tree alphabetically. This
// file only
//   * ORDERS every folder's contents (and the folders themselves, by what
//     they hold) by LAST OPENED (default), DATE, LARGEST or A - Z;
//   * FILTERS by year and by the search line, unfolding the folders that hold
//     a match and folding them back when the search is cleared;
//   * offers a flat LIST view, which moves the rows out of the tree and back
//     (each row remembers the folder it came from);
//   * REMEMBERS the order, the view, the year and which folders you left
//     unfolded, in localStorage, and the search in sessionStorage, so the
//     reload that follows an episode becoming READY lands where you were;
//   * POLLS state.json while an episode is opening and reloads once its state
//     moves. It used to be a meta refresh every 3 s, which would reload the
//     page out from under somebody typing in the search box.
//
// Storage can be blocked outright (private mode, a locked-down profile):
// every access is in a try/catch and the fallback is the defaults.
(function () {
  'use strict';

  var page = document.querySelector('.cl');
  var tree = document.getElementById('cl-tree');
  if (!page || !tree) return;
  var list = document.getElementById('cl-list');
  var input = document.getElementById('cl-q');
  var clearBtn = page.querySelector('.cl-clear');
  var searchBox = page.querySelector('.cl-search');
  var none = page.querySelector('.cl-none');
  var countEl = page.querySelector('.cl-count');
  var foldBox = page.querySelector('.cl-fold');
  var recent = page.querySelector('.cl-recent');

  var KEY = 'ccsync.cards.picker';
  var QKEY = 'ccsync.cards.picker.q';
  var SORTS = ['opened', 'modified', 'bytes', 'name'];

  function load() {
    try {
      var v = JSON.parse(window.localStorage.getItem(KEY) || '{}');
      return v && typeof v === 'object' ? v : {};
    } catch (e) { return {}; }
  }
  function save() {
    try { window.localStorage.setItem(KEY, JSON.stringify(prefs)); } catch (e) { /* blocked */ }
  }
  function saveQuery(q) {
    try { window.sessionStorage.setItem(QKEY, q); } catch (e) { /* blocked */ }
  }
  function loadQuery() {
    try { return window.sessionStorage.getItem(QKEY) || ''; } catch (e) { return ''; }
  }

  var prefs = load();
  if (!prefs.open || typeof prefs.open !== 'object') prefs.open = {};
  var sort = SORTS.indexOf(prefs.sort) >= 0 ? prefs.sort : 'opened';
  var view = prefs.view === 'list' ? 'list' : 'tree';
  var year = typeof prefs.year === 'string' ? prefs.year : '';
  // A remembered year that has left the vault is ALL, never an empty page.
  if (year && !chipFor('data-year', year)) year = '';

  function chipFor(attr, value) {
    var chips = page.querySelectorAll('.cl-chip[' + attr + ']');
    for (var i = 0; i < chips.length; i++) {
      if (chips[i].getAttribute(attr) === value) return chips[i];
    }
    return null;
  }

  function num(el, attr) {
    var v = parseFloat(el.getAttribute(attr));
    return isNaN(v) ? 0 : v;
  }

  // ---------------------------------------------------------------- model
  var rows = Array.prototype.slice.call(tree.querySelectorAll('.cl-ep'));
  var folders = Array.prototype.slice.call(tree.querySelectorAll('details.cl-folder'));
  rows.forEach(function (r) {
    r._home = r.parentNode;
    r._name = r.getAttribute('data-name') || '';
    r._search = r.getAttribute('data-search') || '';
    r._year = r.getAttribute('data-year') || '';
    r._opened = num(r, 'data-opened');
    r._openedAny = num(r, 'data-opened-any');
    r._bytes = num(r, 'data-bytes');
    if (r.getAttribute('data-bytes') === '-1') r._bytes = -1;
    r._modified = num(r, 'data-modified');
    var n = r.querySelector('.cl-name-text');
    r._nameEl = n;
    r._text = n ? n.textContent : '';
  });
  folders.forEach(function (f) {
    f._key = f.getAttribute('data-key') || '';
    f._rows = rows.filter(function (r) { return f.contains(r); });
    f._name = ((f.querySelector('.cl-fname') || {}).textContent || '').toLowerCase();
    f._count = f.querySelector('.cl-fcount');
    f._opened = 0; f._openedAny = 0; f._modified = 0; f._bytes = -1;
    var unknown = false;
    f._rows.forEach(function (r) {
      f._opened = Math.max(f._opened, r._opened);
      f._openedAny = Math.max(f._openedAny, r._openedAny);
      f._modified = Math.max(f._modified, r._modified);
      if (r._bytes >= 0) f._bytes = Math.max(f._bytes, 0) + r._bytes;
      else unknown = true;
    });
    var sizeEl = f.querySelector('.cl-fsize');
    if (sizeEl && f._bytes >= 0) sizeEl.textContent = human(f._bytes) + (unknown ? '+' : '');
  });

  function human(n) {
    var units = ['B', 'KB', 'MB', 'GB', 'TB'];
    var i = 0;
    while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
    return (i < 2 ? Math.round(n) : n.toFixed(1)) + ' ' + units[i];
  }

  // ---------------------------------------------------------------- order
  function byName(a, b) {
    return a._name.localeCompare(b._name, undefined, {numeric: true, sensitivity: 'base'});
  }
  function compare(a, b) {
    var d = 0;
    if (sort === 'opened') {
      d = (b._opened - a._opened) || (b._openedAny - a._openedAny);
    } else if (sort === 'modified') {
      d = b._modified - a._modified;
    } else if (sort === 'bytes') {
      d = b._bytes - a._bytes;
    }
    return d || byName(a, b);
  }

  function orderContainer(box) {
    var kids = Array.prototype.slice.call(box.children);
    var fs = kids.filter(function (k) { return k.classList.contains('cl-folder'); });
    var es = kids.filter(function (k) { return k.classList.contains('cl-ep'); });
    fs.sort(compare);
    es.sort(compare);
    fs.concat(es).forEach(function (k) { box.appendChild(k); });
  }

  function arrange() {
    if (view === 'list') {
      var sorted = rows.slice().sort(compare);
      sorted.forEach(function (r) { list.appendChild(r); });
      tree.hidden = true;
      list.hidden = false;
      page.classList.add('cl-is-list');
    } else {
      rows.forEach(function (r) { if (r.parentNode !== r._home) r._home.appendChild(r); });
      orderContainer(tree);
      folders.forEach(function (f) {
        var kids = f.querySelector('.cl-kids');
        if (kids) orderContainer(kids);
      });
      list.hidden = true;
      tree.hidden = false;
      page.classList.remove('cl-is-list');
    }
    if (foldBox) foldBox.hidden = view === 'list';
  }

  // --------------------------------------------------------------- filter
  function terms() {
    var q = (input ? input.value : '').trim().toLowerCase();
    return q ? q.split(/\s+/) : [];
  }

  function highlight(r, ts) {
    var el = r._nameEl;
    if (!el) return;
    var text = r._text;
    var lower = text.toLowerCase();
    while (el.firstChild) el.removeChild(el.firstChild);
    if (!ts.length || lower.length !== text.length) {
      el.appendChild(document.createTextNode(text));
      return;
    }
    var marks = new Array(text.length);
    ts.forEach(function (t) {
      var at = lower.indexOf(t);
      while (t && at >= 0) {
        for (var i = at; i < at + t.length; i++) marks[i] = true;
        at = lower.indexOf(t, at + t.length);
      }
    });
    var i = 0;
    while (i < text.length) {
      var j = i;
      while (j < text.length && !!marks[j] === !!marks[i]) j++;
      var chunk = text.slice(i, j);
      if (marks[i]) {
        var m = document.createElement('mark');
        m.className = 'cl-hl';
        m.textContent = chunk;
        el.appendChild(m);
      } else {
        el.appendChild(document.createTextNode(chunk));
      }
      i = j;
    }
  }

  function matches(search, y, ts) {
    if (year && y !== year) return false;
    for (var i = 0; i < ts.length; i++) {
      if (search.indexOf(ts[i]) < 0) return false;
    }
    return true;
  }

  function filter() {
    var ts = terms();
    var searching = ts.length > 0;
    var shown = 0;
    rows.forEach(function (r) {
      var ok = matches(r._search, r._year, ts);
      r.hidden = !ok;
      if (ok) shown++;
      highlight(r, ts);
    });
    folders.forEach(function (f) {
      var visible = 0;
      f._rows.forEach(function (r) { if (!r.hidden) visible++; });
      f.hidden = visible === 0;
      if (f._count) {
        f._count.textContent = (searching || year) && visible !== f._rows.length
          ? visible + ' of ' + f._rows.length : String(f._rows.length);
      }
      if (searching) {
        f.open = visible > 0;
      } else {
        f.open = wantOpen(f);
      }
    });
    if (recent) {
      var tiles = recent.querySelectorAll('[data-search]');
      var any = 0;
      Array.prototype.forEach.call(tiles, function (t) {
        var ok = !year || t.getAttribute('data-year') === year;
        t.hidden = !ok;
        if (ok) any++;
      });
      recent.hidden = searching || any === 0;
    }
    if (countEl) {
      var total = rows.length;
      countEl.textContent = shown === total
        ? total + (total === 1 ? ' episode' : ' episodes')
        : shown + ' of ' + total + ' episodes';
    }
    if (none) none.hidden = shown > 0;
    if (view === 'list') list.hidden = shown === 0;
    else tree.hidden = shown === 0;
    if (clearBtn) clearBtn.hidden = !searching;
    if (searchBox) searchBox.classList.toggle('is-active', searching);
  }

  function wantOpen(f) {
    if (Object.prototype.hasOwnProperty.call(prefs.open, f._key)) return !!prefs.open[f._key];
    return f.getAttribute('data-default-open') === '1';
  }

  // ------------------------------------------------------------- controls
  function press(attr, value) {
    var chips = page.querySelectorAll('.cl-chip[' + attr + ']');
    Array.prototype.forEach.call(chips, function (c) {
      c.setAttribute('aria-pressed', c.getAttribute(attr) === value ? 'true' : 'false');
    });
  }

  function refresh() {
    press('data-sort', sort);
    press('data-view', view);
    press('data-year', year);
    arrange();
    filter();
  }

  page.addEventListener('click', function (ev) {
    var chip = ev.target.closest ? ev.target.closest('.cl-chip') : null;
    if (chip) {
      if (chip.hasAttribute('data-sort')) sort = chip.getAttribute('data-sort');
      else if (chip.hasAttribute('data-view')) view = chip.getAttribute('data-view');
      else if (chip.hasAttribute('data-year')) year = chip.getAttribute('data-year');
      prefs.sort = sort; prefs.view = view; prefs.year = year;
      save();
      refresh();
      return;
    }
    var sum = ev.target.closest ? ev.target.closest('summary.cl-sum') : null;
    if (sum && !terms().length) {
      // The click is about to flip it: remember where it is going. Not while
      // a search is folding things for you - that is the search's state.
      var f = sum.parentNode;
      prefs.open[f._key] = !f.open;
      save();
      return;
    }
    if (ev.target.closest && ev.target.closest('.cl-unfold')) setAll(true);
    else if (ev.target.closest && ev.target.closest('.cl-refold')) setAll(false);
    else if (ev.target.closest && ev.target.closest('.cl-reset')) {
      year = ''; prefs.year = ''; save();
      if (input) input.value = '';
      saveQuery('');
      refresh();
    }
  });

  function setAll(open) {
    folders.forEach(function (f) { prefs.open[f._key] = open; f.open = open; });
    save();
  }

  if (input) {
    input.value = loadQuery();
    input.addEventListener('input', function () {
      saveQuery(input.value);
      filter();
    });
    input.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') {
        input.value = '';
        saveQuery('');
        filter();
      } else if (ev.key === 'Enter') {
        // Exactly one episode left: Enter is its button. More than one is a
        // search still being typed, and nothing happens.
        var left = rows.filter(function (r) { return !r.hidden; });
        if (left.length !== 1) return;
        var go = left[0].querySelector('.cl-act a.cl-btn-go, .cl-act form[action$="/open"] button');
        if (go) { ev.preventDefault(); go.click(); }
      }
    });
  }
  if (clearBtn) {
    clearBtn.addEventListener('click', function () {
      input.value = '';
      saveQuery('');
      filter();
      input.focus();
    });
  }
  document.addEventListener('keydown', function (ev) {
    if (ev.key !== '/' || ev.ctrlKey || ev.metaKey || ev.altKey || !input) return;
    var t = ev.target;
    var tag = t && t.tagName ? t.tagName.toLowerCase() : '';
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || (t && t.isContentEditable)) return;
    ev.preventDefault();
    input.focus();
    input.select();
  });

  refresh();
  window.requestAnimationFrame(function () { page.classList.add('cl-live'); });

  // ---------------------------------------------------- while one opens
  var watching = rows.some(function (r) { return r.getAttribute('data-state') === 'loading'; });
  if (watching && window.fetch) {
    var delay = 3000;
    var tick = function () {
      if (document.visibilityState === 'hidden') { setTimeout(tick, delay); return; }
      fetch('state.json', {credentials: 'same-origin', headers: {Accept: 'application/json'}})
        .then(function (res) { if (!res.ok) throw new Error(String(res.status)); return res.json(); })
        .then(function (state) {
          delay = 3000;
          var now = {};
          (state.episodes || []).forEach(function (e) { now[e.slug] = e.state || ''; });
          var moved = rows.some(function (r) {
            var slug = r.getAttribute('data-slug');
            return Object.prototype.hasOwnProperty.call(now, slug) &&
              now[slug] !== (r.getAttribute('data-state') || '');
          });
          if (moved) { window.location.reload(); return; }
          setTimeout(tick, delay);
        })
        .catch(function () {
          // A dropped poll is not a reason to stop: back off to 15 s.
          delay = Math.min(delay * 2, 15000);
          setTimeout(tick, delay);
        });
    };
    setTimeout(tick, delay);
  }
})();
