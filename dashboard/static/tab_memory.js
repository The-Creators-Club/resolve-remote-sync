// A TAB OPENS WHERE YOU LEFT IT (CR-188, Alex, 2026-09-04).
//
// "when you switch tabs it should remember your position from the last time
// you were in X or Y tab." The dashboard's tabs are the topbar destinations
// (SYNC STATUS, TRANSFERS, B-ROLL, MUSIC, CARDS, SETTINGS) and the Settings
// strip pages, and every one of them is a FULL PAGE NAVIGATION: the browser
// gives a fresh document, at the top, with every <details> back at its
// server-rendered default. On a phone, where the owner asked for this, the
// Settings pages are long and the fleet grid is longer, so "go and look at
// Packages, come back" cost two thumb journeys every time.
//
// This is not the browser's own back/forward restoration, which already works
// and which we deliberately leave alone (history.scrollRestoration is never
// touched here): this remembers the position per PAGE, so arriving at
// /admin/packages from anywhere lands where that page was last read.
//
// Constraints that shaped it:
//   * The dashboard is INSTALLABLE (manifest.webmanifest, MOBILE_PLAN.md 3.3).
//     sessionStorage is the right lifetime for a browser tab (gone when the
//     tab closes), but an installed PWA on a phone is killed and relaunched
//     by the OS with no warning, so the entry is written to localStorage as
//     well and read from there when the session copy is missing. The local
//     copy EXPIRES (MAX_AGE_MS): a position from yesterday is not a position.
//   * Storage can be blocked outright (private mode, a locked-down profile,
//     an iframe). Every access is in a try/catch and the failure mode is a
//     page that behaves exactly as it did before this file existed.
//   * The panels arrive LATE. Half of what makes these pages tall comes from
//     hx-trigger="load" fragments, so at DOMContentLoaded the document is
//     often 600 px of skeleton and scrolling to y=1800 would silently clamp
//     to the bottom of nothing. We wait for the height, up to RESTORE_MS.
//   * A deep link WINS. /#server-notices and /admin/users#admin-fleet-halt
//     are the product's own links (DUI-7, base.html) and the reader asked for
//     that anchor, not for where they were last time.
//   * The reader wins too: the first wheel, touch or key abandons a restore
//     that has not landed. A page that yanks itself out from under a thumb is
//     worse than a page that opens at the top.
//
// No visual cue by request (Alex, 2026-09-04): it should just feel like the
// page was left where it was.
(function () {
  "use strict";

  // The mounted SPAs render their own documents and never include base.html,
  // so this file is not loaded there. The check is belt and braces for the
  // day one of them starts borrowing the dashboard's static assets: they are
  // single-page, they keep their own state, and a scroll restore aimed at a
  // view they have already replaced would be a jump to nowhere.
  var SPA_PREFIXES = ["/broll", "/music", "/ytdl", "/cards"];

  var PREFIX = "ccsync.tab:";
  // Eight hours: long enough to cover a working day's tab, short enough that
  // the phone that was left on the jobs page overnight opens at the top.
  var MAX_AGE_MS = 8 * 60 * 60 * 1000;
  // At most one write per half second while a page is being read; the events
  // that mean "you are leaving" write unconditionally.
  var SAVE_INTERVAL_MS = 500;
  // How long we keep waiting for the polled fragments to make the page tall
  // enough to hold the remembered position.
  var RESTORE_MS = 3000;
  var POLL_MS = 100;

  // The query keys that SELECT THE VIEW rather than decorate it: the same
  // path with a different one of these is a different page to a reader.
  // ?finished=1 is the jobs page's finished-jobs view. Anything else (a
  // search box, a highlight, a cache buster) shares one key with the plain
  // page, which is what makes "come back to Settings" work at all.
  var VIEW_KEYS = ["editor", "finished", "kind", "machine", "project", "tab", "view"];

  function isSpa() {
    var path = "";
    try {
      path = location.pathname || "";
    } catch (e) {
      return true;
    }
    for (var i = 0; i < SPA_PREFIXES.length; i++) {
      if (path === SPA_PREFIXES[i] || path.indexOf(SPA_PREFIXES[i] + "/") === 0) return true;
    }
    return false;
  }

  if (isSpa()) return;

  // -- storage -------------------------------------------------------------

  function usable(name) {
    try {
      var s = window[name];
      if (!s) return null;
      s.setItem(PREFIX + "probe", "1");
      s.removeItem(PREFIX + "probe");
      return s;
    } catch (e) {
      return null;
    }
  }

  var SESSION = usable("sessionStorage");
  var LOCAL = usable("localStorage");

  // Query parsing by hand rather than URLSearchParams: this file has to work
  // in whatever WebView an editor's phone ships, and the parse is four lines.
  function viewQuery() {
    var search = "";
    try {
      search = location.search || "";
    } catch (e) {
      return "";
    }
    if (search.charAt(0) === "?") search = search.slice(1);
    if (!search) return "";
    var found = {};
    search.split("&").forEach(function (pair) {
      if (!pair) return;
      var eq = pair.indexOf("=");
      var k = eq < 0 ? pair : pair.slice(0, eq);
      var v = eq < 0 ? "" : pair.slice(eq + 1);
      if (v !== "" && VIEW_KEYS.indexOf(k) >= 0 && !(k in found)) found[k] = v;
    });
    var parts = [];
    VIEW_KEYS.forEach(function (k) {
      if (k in found) parts.push(k + "=" + found[k]);
    });
    return parts.length ? "?" + parts.join("&") : "";
  }

  function pageKey() {
    var path = "/";
    try {
      path = location.pathname || "/";
    } catch (e) {
      path = "/";
    }
    return PREFIX + path + viewQuery();
  }

  function write(key, entry) {
    var raw;
    try {
      raw = JSON.stringify(entry);
    } catch (e) {
      return;
    }
    [SESSION, LOCAL].forEach(function (s) {
      if (!s) return;
      try {
        s.setItem(key, raw);
      } catch (e) {
        // A full or blocked store is not an error worth a page's attention.
      }
    });
  }

  function read(key) {
    var stores = [SESSION, LOCAL];
    for (var i = 0; i < stores.length; i++) {
      if (!stores[i]) continue;
      var entry = null;
      try {
        var raw = stores[i].getItem(key);
        if (raw) entry = JSON.parse(raw);
      } catch (e) {
        entry = null;
      }
      if (!entry || typeof entry !== "object") continue;
      if (typeof entry.t !== "number" || (Date.now() - entry.t) > MAX_AGE_MS) continue;
      return entry;
    }
    return null;
  }

  // -- what a position is --------------------------------------------------

  function scrollY() {
    return Math.round(window.scrollY || window.pageYOffset || 0);
  }

  function maxScroll() {
    var doc = document.documentElement || {};
    var body = document.body || {};
    var h = Math.max(doc.scrollHeight || 0, body.scrollHeight || 0);
    return Math.max(0, h - (window.innerHeight || 0));
  }

  function allDetails() {
    try {
      return Array.prototype.slice.call(document.querySelectorAll("details"));
    } catch (e) {
      return [];
    }
  }

  // An id, or the data-key base.html's own open/closed keeper uses: the bins
  // and sidebar panels are keyed rather than identified, and they are exactly
  // the sections a reader leaves open.
  function detailsId(d) {
    if (d.id) return d.id;
    var key = d.getAttribute ? d.getAttribute("data-key") : null;
    return key ? "key:" + key : null;
  }

  function openDetails() {
    var out = [];
    allDetails().forEach(function (d) {
      if (!d.hasAttribute || !d.hasAttribute("open")) return;
      var id = detailsId(d);
      if (id && out.indexOf(id) < 0) out.push(id);
    });
    // A cap, because this is written on every hidden tab: a page with two
    // hundred open sections is a page whose scrollY is the real answer.
    return out.slice(0, 100);
  }

  var SECTION_SELECTOR = "h1[id], h2[id], h3[id], h4[id], section[id]";

  // The last heading at or above the top of the viewport. It is the fallback
  // for a page that never grows back to its old height (a fleet grid with
  // fewer rows today), where "roughly this part of the page" beats the top.
  function nearestSection() {
    var y = scrollY();
    var best = null;
    var bestTop = -1;
    var nodes;
    try {
      nodes = Array.prototype.slice.call(document.querySelectorAll(SECTION_SELECTOR));
    } catch (e) {
      return null;
    }
    nodes.forEach(function (el) {
      if (!el.id || !el.getBoundingClientRect) return;
      var top;
      try {
        top = el.getBoundingClientRect().top + y;
      } catch (e) {
        return;
      }
      if (top <= y + 8 && top >= bestTop) {
        bestTop = top;
        best = el.id;
      }
    });
    return best;
  }

  // -- saving --------------------------------------------------------------

  // True until the restore has landed or been given up on. A save while the
  // page is still at the top would overwrite the position with 0, which is
  // exactly what a fast tab switch would do.
  var quiet = true;
  var pending = null;
  var deadlineAt = 0;
  var timer = null;
  var lastSave = 0;

  function save() {
    if (quiet) return;
    write(pageKey(), {
      y: scrollY(),
      details: openDetails(),
      section: nearestSection(),
      t: Date.now()
    });
    lastSave = Date.now();
  }

  function saveThrottled() {
    if (Date.now() - lastSave < SAVE_INTERVAL_MS) return;
    save();
  }

  // -- restoring -----------------------------------------------------------

  function stop() {
    pending = null;
    quiet = false;
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  }

  function reopen(entry) {
    var wanted = entry.details || [];
    if (!wanted.length) return;
    allDetails().forEach(function (d) {
      var id = detailsId(d);
      if (!id || wanted.indexOf(id) < 0) return;
      if (d.setAttribute && (!d.hasAttribute || !d.hasAttribute("open"))) {
        d.setAttribute("open", "");
      }
    });
  }

  function attempt() {
    if (!pending) return;
    // Before the height test, never after: an open section is part of what
    // makes the page tall enough to hold the remembered scrollY.
    reopen(pending);
    var want = pending.y || 0;
    if (want <= 0) {
      stop();
      return;
    }
    if (maxScroll() >= want - 2) {
      window.scrollTo(0, want);
      stop();
      return;
    }
    if (Date.now() >= deadlineAt) {
      var el = pending.section ? document.getElementById(pending.section) : null;
      if (el && el.scrollIntoView) el.scrollIntoView();
      else window.scrollTo(0, maxScroll());
      stop();
    }
  }

  function start() {
    // A fragment in the URL is a deep link somebody asked for; it wins.
    var hash = "";
    try {
      hash = location.hash || "";
    } catch (e) {
      hash = "";
    }
    if (hash.length > 1) {
      quiet = false;
      return;
    }
    var entry = read(pageKey());
    if (!entry) {
      quiet = false;
      return;
    }
    pending = entry;
    deadlineAt = Date.now() + RESTORE_MS;
    attempt();
    if (pending && timer === null) {
      timer = setInterval(attempt, POLL_MS);
    }
  }

  // -- wiring --------------------------------------------------------------

  document.addEventListener("htmx:afterSettle", function () {
    if (pending) attempt();
    else saveThrottled();
  });

  // Passive and throttled: a scroll listener on every page of the dashboard
  // must cost nothing on a phone. This is the belt for the browsers that skip
  // pagehide on a same-site navigation.
  try {
    window.addEventListener("scroll", saveThrottled, {passive: true});
  } catch (e) {
    window.addEventListener("scroll", saveThrottled);
  }

  // pagehide fires on a navigation away and on the phone's own "app went to
  // the background"; visibilitychange catches the tab switch that never
  // unloads. Both, because neither is reliable on its own across iOS,
  // Android and the desktop.
  window.addEventListener("pagehide", function () { save(); });
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "hidden") save();
  });

  // Back/forward out of the bfcache: the browser has already restored the
  // whole document, scroll included. Do not touch it.
  window.addEventListener("pageshow", function (evt) {
    if (evt && evt.persisted) stop();
  });

  ["wheel", "touchstart", "keydown", "mousedown"].forEach(function (type) {
    var abandon = function () {
      if (pending) stop();
      else quiet = false;
    };
    try {
      document.addEventListener(type, abandon, {passive: true, capture: true});
    } catch (e) {
      document.addEventListener(type, abandon, true);
    }
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start);
  } else {
    start();
  }

  // The seam tests/test_tab_memory.py drives. Nothing on a page reads it.
  window.__ccsyncTabMemory = {
    key: pageKey,
    save: function () { quiet = false; save(); },
    read: read,
    restore: start
  };
})();
