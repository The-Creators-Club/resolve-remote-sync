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

// ---------------------------------------------------------------------------
// A CHIP EXPLAINS ITSELF ON A PHONE (DUI-3, usability sweep 2026-09-03).
//
// Every chip on the fleet grid carried its cause and its next action in
// `title=` alone. A touch device has no hover, so on the page whose whole
// reason for being opened on a phone is "is anything red", the entire
// explanatory layer was unreachable: eighteen labels in one LANES cell, each
// of them mute. A tap now opens a small sheet with the same sentence the
// tooltip carries (the prose itself lives in ui.CHIP_HELP, so the two cannot
// drift), and tab + Enter reaches it for keyboard users.
//
// In this file rather than a new one because base.html already loads it on
// every page: a second <script> for fifty lines is a request every editor's
// browser pays for.
(function () {
  "use strict";

  var SHEET_ID = "chip-sheet";

  function sheet() {
    return document.getElementById(SHEET_ID);
  }

  function close() {
    var el = sheet();
    if (el) el.hidden = true;
  }

  function open(chip) {
    var el = sheet();
    if (!el) return;
    var text = chip.getAttribute("data-chip-detail") || chip.getAttribute("title") || "";
    if (!text) return;
    // textContent, never innerHTML: a chip's text can carry a Syncthing
    // error, a file name or a companion's own message.
    el.querySelector(".chip-sheet-label").textContent =
      (chip.textContent || "").trim();
    el.querySelector(".chip-sheet-text").textContent = text;
    el.hidden = false;
  }

  function target(node) {
    if (!node || !node.closest) return null;
    // A chip that is a LINK or sits in a control is that control first: the
    // job chip goes to the jobs page, and taking that away to show a tooltip
    // would be a worse page, not a better one.
    if (node.closest("a, button, input, select, textarea, label")) return null;
    return node.closest("[data-chip-detail], .chip[title], .dot[title]");
  }

  document.addEventListener("click", function (evt) {
    if (!evt.target || !evt.target.closest) return;
    var el = sheet();
    if (el && !el.hidden && evt.target.closest("#" + SHEET_ID)) {
      close();
      return;
    }
    var chip = target(evt.target);
    if (!chip) {
      close();
      return;
    }
    evt.preventDefault();
    open(chip);
  });

  document.addEventListener("keydown", function (evt) {
    if (evt.key === "Escape") { close(); return; }
    if (evt.key !== "Enter" && evt.key !== " ") return;
    var chip = target(document.activeElement);
    if (!chip) return;
    evt.preventDefault();
    open(chip);
  });

  // Reachable by keyboard, on the first render and after every swap: the
  // grid replaces its own chips every 15 s.
  function focusable(root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll("[data-chip-detail], .chip[title]").forEach(function (c) {
      if (c.closest("a, button, input, select, textarea, label")) return;
      if (!c.hasAttribute("tabindex")) c.setAttribute("tabindex", "0");
    });
  }

  document.addEventListener("DOMContentLoaded", function () { focusable(document); });
  document.addEventListener("htmx:afterSwap", function (evt) {
    focusable(evt.detail && evt.detail.target);
  });
})();

// ---------------------------------------------------------------------------
// THE REFUSAL RENDERS BESIDE THE BUTTON THAT CAUSED IT (DUI-6, sweep
// 2026-09-03).
//
// Every htmx panel here returns its whole self with `error` painted in a
// banner at the TOP and swaps outerHTML, which preserves scroll position. So
// an admin who clicks [ DELETE ] on the fortieth package row, or [ SET ] on
// the last user's password, got their refusal roughly two thousand pixels
// above the viewport and saw nothing happen at all.
//
// The panels mark their error banner `.error-banner`. Here we remember which
// control issued the request and, after the swap, move that banner to the
// control that came back in its place - matched on the request path, which is
// the one thing that survives an outerHTML swap. No match (a poll, or an
// error with no button behind it) leaves the banner exactly where the
// template put it: the top-of-panel banner is still right for those.
(function () {
  "use strict";

  var lastPath = null;

  document.addEventListener("htmx:beforeRequest", function (evt) {
    var elt = evt.detail && evt.detail.elt;
    var path = elt && elt.getAttribute && (elt.getAttribute("hx-post")
      || elt.getAttribute("hx-delete") || elt.getAttribute("hx-put"));
    // Only a WRITE has a button behind it worth going back to; a poll's
    // hx-get must never claim the next error.
    lastPath = path || null;
  });

  document.addEventListener("htmx:afterSwap", function (evt) {
    var root = evt.detail && evt.detail.target;
    if (!root || !root.querySelector || !lastPath) return;
    var path = lastPath;
    lastPath = null;
    var banner = root.querySelector(".error-banner");
    if (!banner) return;
    // Matched by reading the attributes rather than by building a selector
    // out of a URL: these paths carry slashes, and a query string would carry
    // characters that make an attribute selector mean something else.
    var form = null;
    var candidates = root.querySelectorAll("[hx-post], [hx-delete], [hx-put]");
    for (var i = 0; i < candidates.length; i++) {
      var c = candidates[i];
      if (c.getAttribute("hx-post") === path || c.getAttribute("hx-delete") === path
          || c.getAttribute("hx-put") === path) { form = c; break; }
    }
    if (!form || !form.parentNode) return;
    banner.classList.add("form-error");
    form.parentNode.insertBefore(banner, form);
    banner.scrollIntoView({block: "center"});
  });
})();
