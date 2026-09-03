// The Dashboard section of the Packages page (ZERO_TOUCH_PLAN.md WP K,
// 2026-08-18): apply a signed code update, watch it, and come back when the
// new process answers.
//
// Plain fetch() rather than htmx, for one reason: this is the only panel in
// the dashboard whose own server stops answering half way through the
// interaction. htmx would swap a failed poll's error into the page and lose
// the state that says what we are waiting for. So the panel is loaded by
// htmx once and driven from here afterwards.
//
// The wait has two phases, and they are different problems:
//   1. while the update runs, poll our own status route every second;
//   2. once it reports "restarting", poll /api/v1/health until a DIFFERENT
//      version answers -- the connection is refused or reset for a few
//      seconds in between, which is expected and not an error to show.
(function () {
  "use strict";

  var PANEL = "dashboard-update";
  var STATUS_URL = "/api/v1/admin/dashboard-update/status";
  var APPLY_URL = "/api/v1/admin/dashboard-update/apply";
  var ROLLBACK_URL = "/api/v1/admin/dashboard-update/rollback";
  var PARTIAL_URL = "/partials/admin/dashboard-update";
  // Long enough to cover a slow NAS restarting a container with a cold page
  // cache; short enough that a genuinely dead dashboard says so rather than
  // spinning forever.
  var RESTART_TIMEOUT_MS = 180000;

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf"]');
    return meta ? meta.content : "";
  }

  function panel() {
    return document.getElementById(PANEL);
  }

  function progress(text, isError) {
    var el = document.getElementById("dashupd-progress");
    if (!el) return;
    el.textContent = text;
    el.className = isError ? "banner" : "muted";
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
    return fetch(PARTIAL_URL, {headers: {"HX-Request": "true"}})
      .then(function (resp) {
        // bug-hunt-2026-09-03 dash-mounts-ui-3, the DASH-4 shape again: we
        // send HX-Request, so login_gate answers an expired session with a
        // 200-and-HX-Redirect instead of a 303. Only htmx understands that
        // header; a plain fetch would swap the LOGIN DOCUMENT into the
        // packages panel. Reload the page so the browser follows the
        // redirect and the admin sees the sign-in page, not a nested form.
        if (!resp.ok || resp.headers.get("HX-Redirect")) {
          window.location.reload();
          return null;
        }
        return resp.text();
      })
      .then(function (html) {
        if (html === null) return;
        var host = panel();
        if (host && host.parentNode) host.outerHTML = html;
      })
      .catch(function () { /* the next page load will show the truth */ });
  }

  // Poll our own status until the update is no longer in progress.
  function watchProgress(version) {
    return new Promise(function (resolve) {
      var tick = function () {
        fetch(STATUS_URL).then(function (r) { return r.json(); }).then(function (state) {
          progress("working: " + state.step + (state.message ? " - " + state.message : ""), false);
          if (state.step === "restarting") { resolve("restarting"); return; }
          if (!state.in_progress) {
            resolve(state.last_error ? "failed:" + state.last_error : "done");
            return;
          }
          setTimeout(tick, 1000);
        }).catch(function () {
          // The process may already be going down: that is the success path
          // for the last poll, so hand over to the health wait rather than
          // calling it an error.
          resolve("restarting");
        });
      };
      tick();
    });
  }

  // Poll /api/v1/health until the version answering it is the one we asked
  // for (or simply a different one, for a rollback where the target is the
  // image's own build).
  function waitForNewVersion(expected, wasRunning) {
    var deadline = Date.now() + RESTART_TIMEOUT_MS;
    progress("restarting - the dashboard is offline for about ten seconds", false);
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

  function runUpdate(version, wasRunning) {
    progress("starting the update", false);
    postJson(APPLY_URL, {version: version, force: false})
      .then(function () { return watchProgress(version); })
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
        reloadPanel();
      });
  }

  function onClick(evt) {
    var target = evt.target;
    if (!target || !target.getAttribute) return;

    var applyVersion = target.getAttribute("data-dashupd-apply");
    if (applyVersion) {
      var running = document.getElementById(PANEL);
      var wasRunning = running ? (running.getAttribute("data-running") || "") : "";
      if (!window.confirm("Update this dashboard to " + applyVersion + "?\n\n"
                          + "It will be offline for about ten seconds while it restarts. "
                          + "The databases are backed up first.")) {
        return;
      }
      runUpdate(applyVersion, wasRunning);
      return;
    }

    if (target.hasAttribute("data-dashupd-rollback")) {
      var to = target.getAttribute("data-dashupd-rollback");
      // REL-10 (resilience sweep 2026-08-28): restore_db used to be hardcoded
      // to "", so the one control that keeps the database and the code in step
      // could not be reached from this page at all.
      var box = document.getElementById("dashupd-restore-db");
      var panel = document.getElementById("dashupd-schema");
      var restoreDb = (box && box.checked) ? (box.value || "") : "";
      var schemaSafe = !panel || panel.getAttribute("data-safe") === "1";
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
  }

  document.addEventListener("click", onClick);

  // A page loaded while an update is already running (a second admin, or a
  // reload mid-update) picks the watch back up rather than showing a frozen
  // "working" line forever.
  document.addEventListener("htmx:afterSwap", function (evt) {
    var el = evt.detail && evt.detail.target ? evt.detail.target : null;
    if (!el || !el.querySelector) return;
    var prog = el.querySelector("#dashupd-progress");
    if (prog && prog.getAttribute("data-in-progress") === "1") {
      watchProgress("").then(function () { reloadPanel(); });
    }
  });
})();
