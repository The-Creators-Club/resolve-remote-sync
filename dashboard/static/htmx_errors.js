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
    // ui-dash-static-7 (2026-09-25): the banner is fixed over the bottom of
    // the page, where it hid the last lines of every page and the assignments
    // page's error toasts (which only go away when clicked). Its height
    // depends on how many lines the reason wraps to on this screen, so the
    // CSS reads the measured value to pad the page and lift the toasts.
    if (document.body.style && document.body.style.setProperty) {
      document.body.style.setProperty("--stale-h", el.offsetHeight + "px");
    }
  }

  function clear() {
    lastOk = Date.now();
    delete document.body.dataset.stale;
    if (document.body.style && document.body.style.removeProperty) {
      document.body.style.removeProperty("--stale-h");
    }
    var el = document.getElementById(BANNER_ID);
    if (el && el.parentNode) el.parentNode.removeChild(el);
  }

  // ui-dash-static-2 (2026-09-25). The server's own reason for a refusal:
  // FastAPI's {"detail": "..."} (or a validation error's list of {msg}), the
  // CSRF origin gate's {"error": "..."}. Empty when the body is not JSON.
  function reasonOf(xhr) {
    var text = (xhr && typeof xhr.responseText === "string") ? xhr.responseText : "";
    if (!text) return "";
    try {
      var body = JSON.parse(text);
      var d = body && (body.detail != null ? body.detail : body.error);
      if (typeof d === "string") return d;
      if (Array.isArray(d)) {
        return d.map(function (x) { return (x && x.msg) ? String(x.msg) : String(x); })
          .join("; ");
      }
    } catch (e) {
      return "";
    }
    return "";
  }

  var REFUSAL_CLASS = "htmx-refusal";

  function dropRefusal(elt) {
    var host = (elt && elt.closest) ? (elt.closest("form, label") || elt) : null;
    var prev = host ? host.previousElementSibling : null;
    if (prev && prev.classList && prev.classList.contains(REFUSAL_CLASS)) {
      prev.parentNode.removeChild(prev);
    }
  }

  // ui-dash-static-2 (2026-09-25). A 4xx answer to a WRITE is a refusal from
  // a server that is up and answering, not an outage. It was painted as
  // "THIS PAGE HAS STOPPED UPDATING ... Reload the page", with the server's
  // reason thrown away, and the next successful poll anywhere took that away
  // again within a minute while the checkbox the browser had flipped stayed
  // flipped. So the reason goes beside the control that was pressed (the
  // same `.error-banner.form-error` look DUI-6 gives a refusal), a checkbox
  // goes back to what the server still holds, and the page is not marked
  // stale. A 403 is a SIGNED-IN person the route will not let do this
  // (routes answer `403 if user else 401`, and the CSRF gate answers 403
  // with its own "reload the page" detail); only a 401 is an ended session.
  function refuse(elt, status, reason) {
    if (!elt || !elt.parentNode || !elt.closest) return false;
    if (String(elt.tagName).toUpperCase() === "INPUT"
        && String(elt.type).toLowerCase() === "checkbox") {
      elt.checked = !elt.checked;
    }
    dropRefusal(elt);
    var host = elt.closest("form, label") || elt;
    if (!host.parentNode) return false;
    var note = document.createElement("div");
    note.className = "banner error-banner form-error " + REFUSAL_CLASS;
    note.setAttribute("role", "alert");
    var lead = status === 403 ? "▲ Not allowed: " : "▲ Refused: ";
    // textContent, never innerHTML: `reason` is the server's text.
    note.textContent = lead + (reason || (status === 403
      ? "this account cannot do that."
      : "the server answered " + status + " and gave no reason."));
    host.parentNode.insertBefore(note, host);
    if (note.scrollIntoView) note.scrollIntoView({block: "nearest"});
    return true;
  }

  document.addEventListener("htmx:beforeRequest", function (evt) {
    // A second press of the same control replaces its old refusal.
    if (evt.detail && evt.detail.elt) dropRefusal(evt.detail.elt);
  });

  document.addEventListener("htmx:responseError", function (evt) {
    var detail = evt.detail || {};
    var status = detail.xhr ? detail.xhr.status : 0;
    var cfg = detail.requestConfig || {};
    var verb = String(cfg.verb || "").toLowerCase();
    var elt = detail.elt || cfg.elt;
    // 401 is not an outage, it is a session that ended. Say which, because
    // the fix is different: one is "wait", the other is "sign in again".
    if (status === 401) {
      show("Your session has ended. Reload the page and sign in again.");
      return;
    }
    if (status >= 400 && status < 500 && verb && verb !== "get"
        && refuse(elt, status, reasonOf(detail.xhr))) {
      return;
    }
    if (status === 403) {
      var why = reasonOf(detail.xhr);
      show("The server refused this to your account (403)"
        + (why ? ": " + why : "") + ". Reload the page; if you were signed out, sign in again.");
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

  // ui-dash-main-2 / ui-dash-static-1 (2026-09-25): see liveRoot in the
  // DUI-6 block below. A chip swapped in by an outerHTML panel is only
  // reachable through the element the event fires on.
  function liveRoot(evt) {
    var detail = (evt && evt.detail) || {};
    var t = detail.target;
    if (t && t.isConnected === false && evt.target && evt.target.nodeType === 1) {
      return evt.target;
    }
    return t;
  }

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
    focusable(liveRoot(evt));
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

  // THE PATH BELONGS TO THE REQUEST, NOT TO THE PAGE (dash-mounts-ui-7,
  // 2026-09-11). This was one module-level slot, set on every write's
  // beforeRequest and consumed by the NEXT afterSwap whichever element that
  // swap belonged to - and the fleet grid polls every 15 s, with notices and
  // transfers on their own timers. Any of those settling between the click
  // and the write's own swap stole the slot, and the refusal stayed two
  // thousand pixels above the viewport: the DUI-6 symptom back again,
  // intermittently. The swap event carries its own requestConfig.elt, so the
  // path is read off the request that produced THIS swap; the WeakMap keyed
  // on the xhr is the fallback for an htmx that does not carry one, and it is
  // weak so an abandoned request is collected with its xhr.
  var pathFor = (typeof WeakMap === "function") ? new WeakMap() : null;

  function writePath(elt) {
    // Only a WRITE has a button behind it worth going back to; a poll's
    // hx-get must never claim the next error.
    if (!elt || !elt.getAttribute) return null;
    return elt.getAttribute("hx-post") || elt.getAttribute("hx-delete")
      || elt.getAttribute("hx-put") || null;
  }

  document.addEventListener("htmx:beforeRequest", function (evt) {
    var detail = evt.detail || {};
    var path = writePath(detail.elt);
    if (path && pathFor && detail.xhr) pathFor.set(detail.xhr, path);
  });

  // ui-dash-main-2 / ui-dash-static-1 (2026-09-25). htmx 1.9.12 fires
  // afterSwap on each NEW element but leaves the ORIGINAL target in
  // detail.target, and after an outerHTML swap that original has already been
  // removed from the document. Every panel this block was written for
  // (users, packages, jobs, report tokens, fleet halt) swaps outerHTML, so the
  // banner was searched for in the detached old panel, never found, and the
  // refusal stayed at the top: DUI-6 had never worked in a browser. The tests
  // that pinned it built detail.target as the NEW panel by hand, which htmx
  // never does. An innerHTML target is still connected and is used as before.
  function liveRoot(evt) {
    var detail = (evt && evt.detail) || {};
    var t = detail.target;
    if (t && t.isConnected === false && evt.target && evt.target.nodeType === 1) {
      return evt.target;
    }
    return t;
  }

  // Two forms can post to one path (Protection's two date acks). The one
  // whose hidden inputs match what was sent is the one that was pressed;
  // without a match the first is kept, which is what this did before.
  function sentBy(form, params) {
    if (!params || !form.querySelectorAll) return false;
    var hidden = form.querySelectorAll("input[type=hidden][name]");
    if (!hidden.length) return false;
    for (var i = 0; i < hidden.length; i++) {
      var name = hidden[i].getAttribute("name");
      var sent = (typeof params.get === "function") ? params.get(name) : params[name];
      if (sent == null || String(sent) !== hidden[i].value) return false;
    }
    return true;
  }

  document.addEventListener("htmx:afterSwap", function (evt) {
    var detail = evt.detail || {};
    var root = liveRoot(evt);
    var path = writePath(detail.requestConfig && detail.requestConfig.elt);
    if (!path && pathFor && detail.xhr && pathFor.has(detail.xhr)) {
      // NOT DELETED HERE (dash-mounts-ui-b-6, 2026-09-11). htmx fires
      // afterSwap once per settled element, and an out-of-band swap puts its
      // elements in that same list with the same xhr. Consuming the entry on
      // the first element left the OOB fragment - which is where a write
      // route's error strip arrives - with no path at all, so the banner
      // stayed above the viewport: DUI-6 again for that shape of response.
      // The map is weak and keyed on the xhr, so the entry dies with the
      // request whether we delete it or not.
      path = pathFor.get(detail.xhr);
    }
    if (!root || !root.querySelector || !path) return;
    // ui-dash-admin-5 (2026-09-25): `.result-banner` is a write's OUTCOME
    // that is not a refusal (a failed test send, a failed rehearsal, "the
    // test went out") on the panels that answer in `notice`. It lands two
    // screens above the button for exactly the same reason, so it moves the
    // same way. A refusal wins when a panel carries both.
    var banner = root.querySelector(".error-banner");
    var mark = "form-error";
    if (!banner) {
      banner = root.querySelector(".result-banner");
      mark = "form-result";
    }
    if (!banner) return;
    // Matched by reading the attributes rather than by building a selector
    // out of a URL: these paths carry slashes, and a query string would carry
    // characters that make an attribute selector mean something else.
    var form = null;
    var params = detail.requestConfig && detail.requestConfig.parameters;
    var candidates = root.querySelectorAll("[hx-post], [hx-delete], [hx-put]");
    for (var i = 0; i < candidates.length; i++) {
      var c = candidates[i];
      if (c.getAttribute("hx-post") === path || c.getAttribute("hx-delete") === path
          || c.getAttribute("hx-put") === path) {
        if (!form) form = c;
        if (sentBy(c, params)) { form = c; break; }
      }
    }
    if (!form || !form.parentNode) return;
    // ui-dash-admin-5 (2026-09-25): a form taller than half the screen (the
    // alert settings, one [ SAVE ] under twenty fields) is pressed at its
    // FOOT, so its answer goes above its last submit button rather than above
    // its first field, which is a screen away from where the admin is.
    var anchor = form;
    if (String(form.tagName).toUpperCase() === "FORM" && form.getBoundingClientRect
        && window.innerHeight && form.getBoundingClientRect().height > window.innerHeight / 2) {
      var buttons = form.querySelectorAll("button[type=submit], button:not([type])");
      if (buttons.length && buttons[buttons.length - 1].parentNode) {
        anchor = buttons[buttons.length - 1];
      }
    }
    banner.classList.add(mark);
    anchor.parentNode.insertBefore(banner, anchor);
    banner.scrollIntoView({block: "center"});
  });
})();

// ---------------------------------------------------------------------------
// A POLL NEVER WIPES WHAT SOMEBODY IS DOING INSIDE IT (ui-dash-main-3,
// ui-dash-admin-3, ui-dash-main-8; 2026-09-25).
//
// Most panels here refresh by replacing their own innerHTML on a timer, and
// several of them hold forms: MOVE and SHARE A FOLDER on the project page
// (every 10 s), CREATE / SET / ADD SSH KEY on Users and PUBLISH on Packages
// (every 30 s). Each beat emptied the text boxes, put the selects back and
// dropped focus, and a write still in flight (a NAS account create takes up
// to two minutes) had its busy form replaced by a fresh [ CREATE ] and its
// answer swapped into a box the poll had already detached - so the admin saw
// nothing and pressed CREATE again. On a phone the sidebar's beat closed the
// open projects sheet under the reader's thumb.
//
// So a poll's beat is SKIPPED, not delayed, while the panel it would replace
// has: focus in a field; a field typed into and not yet sent (for up to
// DIRTY_HOLD_MS after the last keystroke, so a form abandoned half-filled
// does not freeze the panel for the rest of the day); a write of its own in
// flight; or an open popover. The next beat after that is the normal one.
// A beat is a GET from an element whose hx-trigger polls ("every N"), which
// is also what pwa.js's visible-again refresh sends.
(function () {
  "use strict";

  var DIRTY_HOLD_MS = 5 * 60 * 1000;
  // A write's own request can die without htmx:afterRequest (a page kept in
  // the back/forward cache); past this a record no longer holds a poll.
  var INFLIGHT_MAX_MS = 5 * 60 * 1000;
  var edited = [];
  var inflight = [];

  function isTextField(el) {
    if (!el || !el.tagName) return false;
    var tag = el.tagName.toLowerCase();
    if (tag === "textarea" || tag === "select") return true;
    if (tag !== "input") return false;
    var type = (el.getAttribute("type") || "text").toLowerCase();
    return ["checkbox", "radio", "hidden", "submit", "button", "reset",
            "image", "file", "range", "color"].indexOf(type) < 0;
  }

  function sendsItself(el) {
    // A select or box that posts on change (hx-post on the field itself) is
    // replaced by its own answer; it is not a half-filled form.
    return el.hasAttribute("hx-post") || el.hasAttribute("hx-get")
      || el.hasAttribute("hx-put") || el.hasAttribute("hx-delete");
  }

  function isDirty(el) {
    if (el.tagName.toLowerCase() === "select") {
      for (var i = 0; i < el.options.length; i++) {
        if (el.options[i].selected !== el.options[i].defaultSelected) return true;
      }
      return false;
    }
    return el.value !== el.defaultValue;
  }

  function isPoll(elt, verb) {
    if (!elt || !elt.getAttribute || String(verb).toLowerCase() !== "get") return false;
    return /(^|,)\s*every\s/.test(elt.getAttribute("hx-trigger") || "");
  }

  function busy(root) {
    var active = document.activeElement;
    if (active && active !== document.body && root.contains(active)
        && isTextField(active) && !sendsItself(active)) return "focus";
    var now = Date.now();
    // Only fields somebody actually edited: a field a script filled, or a
    // select the server rendered with no `selected`, is not work to protect.
    // A record whose field a swap has removed is dropped here too.
    edited = edited.filter(function (r) {
      return now - r.at < DIRTY_HOLD_MS && r.el.isConnected !== false;
    });
    for (var i = 0; i < edited.length; i++) {
      if (root.contains(edited[i].el) && isDirty(edited[i].el)) return "typed";
    }
    inflight = inflight.filter(function (r) { return now - r.at < INFLIGHT_MAX_MS; });
    for (var j = 0; j < inflight.length; j++) {
      if (root.contains(inflight[j].elt)) return "write";
    }
    // ui-dash-main-6 (2026-09-25): a panel somebody opened INTO the polled
    // one, marked `data-poll-hold` (PROJECT ROOTS' [ BROWSE ] folder picker).
    // The 30 s beat emptied it three folders deep. Held for DIRTY_HOLD_MS
    // from the first beat that finds it: every step of the walk draws a new
    // one, and a picker left open over lunch must not freeze the list all day.
    var holds = root.querySelectorAll("[data-poll-hold]");
    for (var h = 0; h < holds.length; h++) {
      if (!holds[h].__pollHoldAt) holds[h].__pollHoldAt = now;
      if (now - holds[h].__pollHoldAt < DIRTY_HOLD_MS) return "open";
    }
    var pops = root.querySelectorAll("[popover]");
    for (var k = 0; k < pops.length; k++) {
      try {
        if (pops[k].matches(":popover-open")) return "open";
      } catch (e) {
        return null;
      }
    }
    return null;
  }

  function onEdit(evt) {
    var el = evt.target;
    if (!isTextField(el) || sendsItself(el)) return;
    edited = edited.filter(function (r) { return r.el !== el; });
    edited.push({el: el, at: Date.now()});
  }
  document.addEventListener("input", onEdit, true);
  document.addEventListener("change", onEdit, true);

  document.addEventListener("htmx:beforeRequest", function (evt) {
    var detail = evt.detail || {};
    var cfg = detail.requestConfig || {};
    var elt = detail.elt || cfg.elt;
    if (!isPoll(elt, cfg.verb)) return;
    var root = detail.target || elt;
    if (!root || !root.querySelectorAll) return;
    if (busy(root)) evt.preventDefault();
  });

  // beforeSend, not beforeRequest: a request some other listener cancels
  // never fires afterRequest, and would otherwise hold its panel's poll.
  document.addEventListener("htmx:beforeSend", function (evt) {
    var detail = evt.detail || {};
    var cfg = detail.requestConfig || {};
    var elt = detail.elt || cfg.elt;
    if (!elt || String(cfg.verb || "").toLowerCase() === "get") return;
    inflight.push({elt: elt, xhr: detail.xhr, at: Date.now()});
  });

  document.addEventListener("htmx:afterRequest", function (evt) {
    var xhr = evt.detail && evt.detail.xhr;
    inflight = inflight.filter(function (r) { return r.xhr !== xhr; });
  });
})();
