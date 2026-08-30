// The phone half of the dashboard: service-worker registration, polling
// discipline, and the install chip (MOBILE_PLAN.md 4 M4, 2026-08-30).
//
// base.html loads this DEFERRED and BEFORE htmx, by contract (3.3). That
// order is the whole trick behind the interval rewrite: both scripts are
// deferred, so they run in document order after parsing and before
// DOMContentLoaded -- this file therefore sees the fully parsed page while
// htmx has not yet read a single hx-trigger. Nodes htmx swaps in later are
// caught on htmx:beforeProcessNode, which 1.9.12 fires before it reads the
// trigger specs off the element (a rewrite on htmx:load would be too late,
// and re-processing the node would double-bind its poll).
(function () {
  'use strict';

  // A coarse pointer pays for a poll twice: the radio wakes and the base rig
  // runs --workers 1. These are the only two cadences the pages use that are
  // worth slowing; 15s and 30s are already fine on a phone. Kept as a table
  // because tests/test_pwa.py reads it -- the pair IS the contract.
  var SLOWER = { '2s': '10s', '5s': '15s' };

  var COARSE = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;
  var STANDALONE = (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches)
    || window.navigator.standalone === true;

  // "every 2s" and "every 2s [document.visibilityState === 'visible']" alike;
  // the filter and any other trigger in the comma list are left untouched.
  function slowTrigger(spec) {
    return String(spec).replace(/every\s+(\d+m?s)/g, function (whole, interval) {
      return SLOWER[interval] ? 'every ' + SLOWER[interval] : whole;
    });
  }

  function slowPolls(root) {
    if (!COARSE || !root || !root.querySelectorAll) return;
    var nodes = [];
    if (root.getAttribute && root.getAttribute('hx-trigger')) nodes.push(root);
    Array.prototype.push.apply(nodes, root.querySelectorAll('[hx-trigger]'));
    nodes.forEach(function (el) {
      var spec = el.getAttribute('hx-trigger');
      var slowed = slowTrigger(spec);
      if (slowed !== spec) el.setAttribute('hx-trigger', slowed);
    });
  }

  // -- polling, and what a hidden tab costs -------------------------------
  // The visibility FILTER on each hx-trigger (M1/M2/M3) stops the next poll;
  // it does nothing about the one already in flight when the phone goes in a
  // pocket, and a partial that forgot the filter has nothing at all. This is
  // the belt: abort on hidden, one refresh on visible so the page the editor
  // comes back to is not two minutes stale.
  function polledElements() {
    return Array.prototype.slice.call(
      document.querySelectorAll('[hx-trigger*="every "]'));
  }

  var VERBS = ['get', 'post', 'put', 'patch', 'delete'];

  function refresh(el) {
    if (!window.htmx) return;
    for (var i = 0; i < VERBS.length; i++) {
      var attr = 'hx-' + VERBS[i];
      if (!el.hasAttribute(attr)) continue;
      window.htmx.ajax(VERBS[i].toUpperCase(), el.getAttribute(attr), {
        source: el,
        target: el,
        swap: el.getAttribute('hx-swap') || 'innerHTML'
      });
      return;
    }
  }

  function onVisibility() {
    if (!window.htmx) return;
    var hidden = document.visibilityState === 'hidden';
    polledElements().forEach(function (el) {
      if (hidden) window.htmx.trigger(el, 'htmx:abort');
      else refresh(el);
    });
  }

  // -- the install chip ---------------------------------------------------
  // Chrome fires beforeinstallprompt when the site is installable and lets
  // the page keep the event to fire later; there is no other way to offer an
  // install from our own chrome. Nothing is rendered in an installed window
  // (there is nothing left to install) and nothing is rendered if M1's slot
  // is absent, so this can never invent UI where the drawer has no room.
  var deferredPrompt = null;

  function showInstall() {
    if (STANDALONE || !deferredPrompt) return;
    var slot = document.getElementById('install-slot');
    if (!slot || slot.querySelector('.install-btn')) return;
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn chip tap install-btn';
    btn.textContent = '[ INSTALL ]';
    btn.addEventListener('click', function () {
      if (!deferredPrompt) return;
      var prompted = deferredPrompt;
      deferredPrompt = null;
      btn.remove();
      prompted.prompt();
    });
    slot.appendChild(btn);
  }

  // -- wiring -------------------------------------------------------------
  slowPolls(document);
  document.addEventListener('htmx:beforeProcessNode', function (evt) {
    slowPolls(evt.target);
  });
  document.addEventListener('visibilitychange', onVisibility);

  window.addEventListener('beforeinstallprompt', function (evt) {
    evt.preventDefault();
    deferredPrompt = evt;
    showInstall();
  });
  document.addEventListener('DOMContentLoaded', showInstall);

  // A service worker needs a secure origin (https, or localhost in dev). The
  // dashboard is plain http on a LAN until a site puts it behind Tailscale
  // serve (MOBILE_PLAN.md M6), and calling register() there throws -- so ask
  // first and stay silent when the answer is no.
  if (window.isSecureContext && 'serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(function (err) {
        // Never a page-breaking failure: the dashboard works without it.
        if (window.console) console.log('service worker not registered:', err);
      });
    });
  }

  // Exposed for tests/test_pwa.py and for a console poke; not an API.
  window.ccsyncPwa = {
    SLOWER: SLOWER,
    slowTrigger: slowTrigger,
    slowPolls: slowPolls,
    polledElements: polledElements
  };
})();
