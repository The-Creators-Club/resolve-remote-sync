// The this_dashboard window of the terminal Packages page (UI redesign port,
// phase 4, builder P4a, 2026-09-25; plan 3.3, 5.3). The cc copy of
// static/dashboard_update.js, which stays frozen for the classic page.
//
// Same routes, same bodies, same two-phase wait (poll our own status while
// the update runs, then /api/v1/health until a different version answers).
// What differs, and why:
//   - Clicks are matched with closest(): a keycap holds a <span class="t">,
//     and the classic handler read data-dashupd-* off evt.target itself, so a
//     click on the label did nothing.
//   - The progress line keeps its classes (classList), rather than having
//     className set to exactly "banner" or "muted".
//   - The two older-code flows are two select-plus-key pairs: an older bundle
//     on the feed (data-dashupd-apply + data-dashupd-older="1", the update
//     flow) and the tree or image rollback (data-dashupd-rollback, the
//     rollback flow). A select's change copies its value onto its key
//     (data-dashupd-for names the key), never one merged list.
//   - reloadPanel() sends the page's own hx-headers (X-CSRF-Token and the
//     X-CC-UI group set, R23): a partial follows the page that asked for it.
//     It obeys HX-Refresh (the "cannot serve" answer, an empty body) by
//     reloading instead of swapping the empty body over #dashboard-update,
//     and on a 409 carrying X-CC-UI-Want it shows the reload line and keeps
//     the panel.
(function () {
  "use strict";

  var PANEL = "dashboard-update";
  var STATUS_URL = "/api/v1/admin/dashboard-update/status";
  var APPLY_URL = "/api/v1/admin/dashboard-update/apply";
  var ROLLBACK_URL = "/api/v1/admin/dashboard-update/rollback";
  var PARTIAL_URL = "/partials/admin/dashboard-update";
  var RESTART_TIMEOUT_MS = 180000;

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf"]');
    return meta ? meta.content : "";
  }

  // The headers every htmx request on this page carries (body hx-headers).
  function pageHeaders() {
    var out = {};
    try {
      var raw = document.body && document.body.getAttribute("hx-headers");
      if (raw) out = JSON.parse(raw) || {};
    } catch (err) { out = {}; }
    if (!out["X-CSRF-Token"]) out["X-CSRF-Token"] = csrfToken();
    return out;
  }

  function panel() {
    return document.getElementById(PANEL);
  }

  function progress(text, isError) {
    var el = document.getElementById("dashupd-progress");
    if (!el) return;
    el.textContent = text;
    el.classList.toggle("note", !!isError);
    el.classList.toggle("err", !!isError);
    el.classList.toggle("muted", !isError);
  }

  function showReloadLine() {
    if (document.querySelector(".cc-reload")) return;
    var line = document.createElement("div");
    line.className = "cc-reload";
    line.setAttribute("role", "status");
    line.innerHTML = 'The dashboard look changed. <a href="">Reload</a> when you are ready.';
    document.body.appendChild(line);
  }

  function postJson(url, body) {
    return fetch(url, {
      method: "POST",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": csrfToken()},
      body: JSON.stringify(body)
    }).then(function (resp) {
      if (!resp.ok) {
        return resp.json().catch(function () { return {detail: resp.statusText}; })
          .then(function (data) { throw new Error(data.detail || ("HTTP " + resp.status)); });
      }
      return resp.json();
    });
  }

  function reloadPanel() {
    var headers = pageHeaders();
    headers["HX-Request"] = "true";
    return fetch(PARTIAL_URL, {headers: headers})
      .then(function (resp) {
        // R23: this page's look cannot be served any more. Reload rather than
        // swap the empty body over the panel (which would erase the progress
        // and refusal lines with it).
        if (resp.headers.get("HX-Refresh") === "true") {
          window.location.reload();
          return null;
        }
        if (resp.status === 409 && resp.headers.get("X-CC-UI-Want")) {
          showReloadLine();
          return null;
        }
        // An expired session answers 200 + HX-Redirect to an HX-Request:
        // reload so the browser follows it, never swap a login page in.
        if (!resp.ok || resp.headers.get("HX-Redirect")) {
          window.location.reload();
          return null;
        }
        return resp.text();
      })
      .then(function (html) {
        if (html === null || html === undefined) return;
        var host = panel();
        if (host && host.parentNode) host.outerHTML = html;
      })
      .catch(function () { /* the next page load will show the truth */ });
  }

  function watchProgress() {
    return new Promise(function (resolve) {
      var tick = function () {
        fetch(STATUS_URL).then(function (r) { return r.json(); }).then(function (state) {
          progress("working: " + state.step + (state.message ? ", " + state.message : ""), false);
          if (state.step === "restarting") { resolve("restarting"); return; }
          if (!state.in_progress) {
            resolve(state.last_error ? "failed:" + state.last_error : "done");
            return;
          }
          setTimeout(tick, 1000);
        }).catch(function () {
          // The process may already be going down: the success path.
          resolve("restarting");
        });
      };
      tick();
    });
  }

  function waitForNewVersion(expected, wasRunning) {
    var deadline = Date.now() + RESTART_TIMEOUT_MS;
    progress("restarting: the dashboard is offline for about ten seconds", false);
    return new Promise(function (resolve) {
      var tick = function () {
        fetch("/api/v1/health", {cache: "no-store"})
          .then(function (r) { return r.json(); })
          .then(function (body) {
            var now = body.version || "";
            var arrived = expected ? now === expected : (now && now !== wasRunning);
            if (arrived) { resolve(true); return; }
            if (Date.now() > deadline) { resolve(false); return; }
            setTimeout(tick, 1500);
          })
          .catch(function () {
            if (Date.now() > deadline) { resolve(false); return; }
            setTimeout(tick, 1500);
          });
      };
      setTimeout(tick, 2000);
    });
  }

  // ui-dash-static-4: a refused apply keeps its own line after the repaint.
  function showRefusal(text) {
    var prog = document.getElementById("dashupd-progress");
    if (!prog || !prog.parentNode) return;
    clearRefusal();
    var line = document.createElement("div");
    line.id = "dashupd-refusal";
    line.className = "note err";
    line.setAttribute("role", "alert");
    var span = document.createElement("span");
    span.className = "grow";
    span.textContent = "Not applied: " + text;
    line.appendChild(span);
    prog.parentNode.insertBefore(line, prog);
  }

  function clearRefusal() {
    var old = document.getElementById("dashupd-refusal");
    if (old && old.parentNode) old.parentNode.removeChild(old);
  }

  var applying = false;

  function runUpdate(version, wasRunning, button) {
    if (applying) return;
    applying = true;
    if (button) button.disabled = true;
    var settle = function () {
      applying = false;
      if (button && button.isConnected) button.disabled = false;
    };
    clearRefusal();
    progress("starting the update", false);
    postJson(APPLY_URL, {version: version, force: false})
      .then(function () { return true; }, function (err) {
        var reason = err.message || String(err);
        progress(reason, true);
        return reloadPanel().then(function () {
          showRefusal(reason);
          var prog = document.getElementById("dashupd-progress");
          if (prog && prog.getAttribute("data-in-progress") === "1") {
            watchProgress().then(function () { reloadPanel(); });
          }
          return false;
        });
      })
      .then(function (accepted) {
        if (!accepted) return null;
        return runAccepted(version, wasRunning);
      })
      .then(settle, settle);
  }

  function runAccepted(version, wasRunning) {
    return watchProgress()
      .then(function (outcome) {
        if (typeof outcome === "string" && outcome.indexOf("failed:") === 0) {
          progress(outcome.slice(7), true);
          return reloadPanel();
        }
        return waitForNewVersion(version, wasRunning).then(function (ok) {
          if (ok) { window.location.reload(); return null; }
          progress("the dashboard has not come back yet. It may still be restarting: "
                   + "reload this page in a minute, or check the container's logs.", true);
          return null;
        });
      })
      .catch(function (err) {
        progress(err.message || String(err), true);
        return reloadPanel();
      });
  }

  function onChange(evt) {
    var sel = evt.target;
    if (!sel || !sel.matches || !sel.matches("select[data-dashupd-for]")) return;
    var key = document.getElementById(sel.getAttribute("data-dashupd-for"));
    if (!key) return;
    if (key.hasAttribute("data-dashupd-apply")) {
      key.setAttribute("data-dashupd-apply", sel.value || "");
      key.disabled = !sel.value;
    } else if (key.hasAttribute("data-dashupd-rollback")) {
      key.setAttribute("data-dashupd-rollback", sel.value || "");
    }
  }

  function onClick(evt) {
    var el = evt.target && evt.target.closest
      ? evt.target.closest("[data-dashupd-apply], [data-dashupd-rollback]") : null;
    if (!el || el.disabled) return;

    if (el.hasAttribute("data-dashupd-apply")) {
      var applyVersion = el.getAttribute("data-dashupd-apply");
      if (!applyVersion) return;       // a select-plus-key with nothing chosen
      var running = panel();
      var wasRunning = running ? (running.getAttribute("data-running") || "") : "";
      var older = el.getAttribute("data-dashupd-older") === "1";
      var question = older
        ? "Roll this dashboard back to " + applyVersion + "?\n\n"
          + "It will be offline for about ten seconds while it restarts. "
          + "The databases are backed up first and stay as they are: they are "
          + "not taken back to an older copy."
        : "Update this dashboard to " + applyVersion + "?\n\n"
          + "It will be offline for about ten seconds while it restarts. "
          + "The databases are backed up first.";
      if (!window.confirm(question)) return;
      runUpdate(applyVersion, wasRunning, el);
      return;
    }

    var to = el.getAttribute("data-dashupd-rollback");
    var box = document.getElementById("dashupd-restore-db");
    var schema = document.getElementById("dashupd-schema");
    var restoreDb = (box && box.checked) ? (box.value || "") : "";
    var schemaSafe = !schema || schema.getAttribute("data-safe") === "1";
    var warning = restoreDb
      ? "The databases will be restored from " + restoreDb
        + ", so everything recorded since that backup is discarded."
      : (schemaSafe
          ? "The databases are NOT restored: use a backup for that."
          : "The databases stay where they are, and they are on a NEWER schema "
            + "than the build you are going back to. Tick the restore box, or "
            + "this will be refused.");
    if (!window.confirm("Roll this dashboard back to " + (to || "the image's own build") + "?\n\n"
                        + "It will be offline for about ten seconds. " + warning)) {
      return;
    }
    progress("rolling back", false);
    postJson(ROLLBACK_URL, {to_version: to, restore_db: restoreDb})
      .then(function () { return waitForNewVersion(to, ""); })
      .then(function (ok) {
        if (ok) { window.location.reload(); return; }
        progress("the dashboard has not come back yet. Reload this page in a minute.", true);
      })
      .catch(function (err) { progress(err.message || String(err), true); });
  }

  document.addEventListener("click", onClick);
  document.addEventListener("change", onChange);

  // A page loaded while an update is already running picks the watch up.
  document.addEventListener("htmx:afterSwap", function (evt) {
    var el = evt.detail && evt.detail.target ? evt.detail.target : null;
    if (!el || !el.querySelector) return;
    var prog = el.querySelector("#dashupd-progress");
    if (prog && prog.getAttribute("data-in-progress") === "1") {
      watchProgress().then(function () { reloadPanel(); });
    }
  });

  // Test seam (the d-ui harness drives reloadPanel against a stub).
  window.ccsyncDashUpdate = {reloadPanel: reloadPanel, onClick: onClick, onChange: onChange};
})();
