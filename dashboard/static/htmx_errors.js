// "This page has stopped updating" (DUI-2, usability + resilience sweep,
// 2026-09-04).
//
// htmx does not swap on a non-2xx and there was no htmx:responseError,
// htmx:sendError or htmx:timeout listener anywhere in the repo. So a partial
// that 500s, a container restart, a NAS reboot or a wifi drop simply left the
// last good render on screen for ever: green dots, live-looking lane chips and
// "updated 4s ago", on a dashboard that had been unreachable for an hour. The
// freshness stamp is polled now (partials/stamp.html); this is the half that
// says so out loud, WHERE THE USER IS, rather than leaving them to notice that
// a number stopped moving.
//
// Deliberately tiny and dependency-free: it is the last thing on the page that
// still has to work when everything else has stopped.
(function () {
  "use strict";

  var BANNER_ID = "htmx-stale-banner";
  // The moment of the last successful htmx exchange. Seeded at load: the page
  // itself came from the server, so at load time it IS current.
  var lastOk = Date.now();

  function ago(ms) {
    var s = Math.max(0, Math.round(ms / 1000));
    if (s < 60) return s + " seconds ago";
    var m = Math.round(s / 60);
    if (m < 60) return m + (m === 1 ? " minute ago" : " minutes ago");
    var h = Math.round(m / 60);
    return h + (h === 1 ? " hour ago" : " hours ago");
  }

  function banner() {
    var el = document.getElementById(BANNER_ID);
    if (el) return el;
    el = document.createElement("div");
    el.id = BANNER_ID;
    el.className = "banner alarm stale-banner";
    el.setAttribute("role", "alert");
    document.body.appendChild(el);
    return el;
  }

  function show(reason) {
    var el = banner();
    // textContent, never innerHTML: `reason` can carry a server's own error
    // text, and this file must not become a way to inject markup into every
    // page on the dashboard.
    el.textContent = "▲ THIS PAGE HAS STOPPED UPDATING (last update "
      + ago(Date.now() - lastOk) + "). Nothing below is current. "
      + reason;
    document.body.dataset.stale = String(lastOk);
  }

  function clear() {
    lastOk = Date.now();
    delete document.body.dataset.stale;
    var el = document.getElementById(BANNER_ID);
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }

  document.addEventListener("htmx:responseError", function (evt) {
    var status = (evt.detail && evt.detail.xhr) ? evt.detail.xhr.status : 0;
    // 401/403 is not an outage, it is a session that ended. Say which, because
    // the fix is different: one is "wait", the other is "sign in again".
    if (status === 401 || status === 403) {
      show("Your session has ended. Reload the page and sign in again.");
      return;
    }
    show("The server answered " + status + ". Reload the page to try again.");
  });

  document.addEventListener("htmx:sendError", function () {
    show("The server could not be reached. Reload the page to try again.");
  });

  document.addEventListener("htmx:timeout", function () {
    show("The server did not answer in time. Reload the page to try again.");
  });

  // Any successful exchange means the page is talking to the dashboard again.
  // afterRequest rather than afterSwap: a 204 or an out-of-band-only response
  // swaps nothing and is still proof of life.
  document.addEventListener("htmx:afterRequest", function (evt) {
    if (evt.detail && evt.detail.successful) clear();
  });
})();
