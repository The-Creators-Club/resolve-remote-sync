// The setup wizard's client (ZERO_TOUCH_PLAN.md WP D, 2026-08-17).
//
// Plain fetch(), not htmx, on purpose: this page is reachable with NO
// session during the narrow first-run window (setup_routes.first_run_open),
// and its second step CREATES the session the rest of the wizard then runs
// under -- a full navigation between "no session" and "has a session" is the
// simplest way to get a CSRF token that is actually bound to the cookie the
// browser is about to start sending (see auth.csrf_token: an anonymous
// request gets "", and base.html's <meta name="csrf"> is only as fresh as
// the last full page render). So: reload the page after anything that might
// have started a session; everything else just re-fetches the task list.
(function () {
  "use strict";

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf"]');
    return meta ? meta.content : "";
  }

  function api(path, opts) {
    opts = opts || {};
    opts.headers = Object.assign({"X-CSRF-Token": csrfToken()}, opts.headers || {});
    if (opts.body && !(opts.headers["Content-Type"])) {
      opts.headers["Content-Type"] = "application/json";
    }
    return fetch(path, opts).then(function (resp) {
      if (!resp.ok) {
        return resp.json().catch(function () { return {detail: resp.statusText}; })
          .then(function (body) {
            var err = new Error(body.detail || ("HTTP " + resp.status));
            err.status = resp.status;
            throw err;
          });
      }
      return resp.status === 204 ? null : resp.json();
    });
  }

  // DUI-6 (usability sweep 2026-09-03). Two faults, one fix. The banner is at
  // the very top of a page whose checklist is at the bottom, so a refusal
  // from [ DO IT ] on the last row was announced off screen; and
  // showError(null) had NO CALL SITE, so a transient failure stayed on the
  // page through every subsequent success. `anchor` is the element that was
  // clicked: the message goes into a slot inside that step, and everything
  // else clears first, every time.
  function clearErrors() {
    var top = document.getElementById("setup-error");
    if (top) { top.style.display = "none"; top.textContent = ""; }
    document.querySelectorAll(".setup-step-error").forEach(function (el) {
      if (el.parentNode) el.parentNode.removeChild(el);
    });
  }

  function errorSlot(anchor) {
    var host = anchor && anchor.closest
      ? (anchor.closest("form") || anchor.closest("tr") || anchor.closest("section"))
      : null;
    if (!host) return null;
    var slot = document.createElement("div");
    slot.className = "banner error-banner form-error setup-step-error";
    host.appendChild(slot);
    return slot;
  }

  function showError(message, anchor) {
    clearErrors();
    if (!message) return;
    var el = errorSlot(anchor) || document.getElementById("setup-error");
    if (!el) return;
    el.style.display = "";
    el.textContent = "\u25B2 " + message;
    if (el.scrollIntoView) el.scrollIntoView({block: "center"});
  }

  // -------------------------------------------------------------- EULA

  function loadEula() {
    api("/api/v1/setup/eula").then(function (data) {
      document.getElementById("setup-eula-text").textContent =
        data.text || "(no EULA shipped in this build)";
      var box = document.getElementById("setup-eula-checkbox");
      var btn = document.getElementById("setup-eula-accept");
      if (!data.text) { btn.disabled = true; return; }
      box.addEventListener("change", function () { btn.disabled = !box.checked; });
    }).catch(function (err) { showError("could not load the EULA: " + err.message); });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var acceptBtn = document.getElementById("setup-eula-accept");
    if (acceptBtn) {
      acceptBtn.addEventListener("click", function () {
        api("/api/v1/setup/eula", {method: "POST"}).then(function (state) {
          clearErrors();
          document.getElementById("setup-eula-status").textContent =
            "accepted (" + state.detail + ")";
          refreshTasks();
        }).catch(function (err) {
          showError("could not accept the EULA: " + err.message, acceptBtn);
        });
      });
    }
  });

  // ----------------------------------------------------------- admin step

  function loadAdminStep() {
    var body = document.getElementById("setup-admin-body");
    api("/api/v1/setup/status").then(function () {
      renderAdminForm(body);
    }).catch(function (err) {
      if (err.status === 404) {
        body.innerHTML = '<span class="muted">not available in this build</span>';
      } else if (err.status === 401 || err.status === 403) {
        // Already signed in as a non-first-run admin, or the first-run
        // window has closed (an account already exists) -- either way,
        // nothing to do here.
        body.innerHTML = '<span class="muted">an admin account already exists</span>';
      } else {
        body.innerHTML = '<span class="muted">could not check: ' + err.message + '</span>';
      }
    });
  }

  function renderAdminForm(body) {
    body.innerHTML =
      '<form id="setup-admin-form">' +
      '<label>USERNAME<br><input type="text" name="username" autocomplete="username"></label> ' +
      '<label>PASSWORD<br><input type="password" name="password" autocomplete="new-password"></label> ' +
      '<button class="btn" type="submit">[ CREATE ]</button></form>';
    document.getElementById("setup-admin-form").addEventListener("submit", function (evt) {
      evt.preventDefault();
      var form = evt.target;
      var payload = {
        username: form.username.value.trim(),
        password: form.password.value,
      };
      api("/api/v1/setup/admin", {method: "POST", body: JSON.stringify(payload)})
        .then(function () {
          // A session cookie now exists -- reload for a CSRF token bound to
          // it (see the module docstring above).
          window.location.reload();
        })
        .catch(function (err) {
          showError("could not create the admin account: " + err.message, form);
        });
    });
  }

  // ---------------------------------------------------------------- studio

  document.addEventListener("DOMContentLoaded", function () {
    var form = document.getElementById("setup-studio-form");
    if (!form) return;
    form.addEventListener("submit", function (evt) {
      evt.preventDefault();
      var values = {
        org_name: form.org_name.value,
        org_short: form.org_short.value,
        tree_name: form.tree_name.value,
        canonical_prefix: form.canonical_prefix.value,
        template_folders: form.template_folders.value,
      };
      // Blank fields are dropped rather than sent as an empty write -- an
      // admin leaving DRIVE LETTER blank must not clobber the "P:\\"
      // built-in default with a validation error.
      Object.keys(values).forEach(function (k) { if (!values[k]) delete values[k]; });
      api("/api/v1/admin/site", {method: "PUT", body: JSON.stringify({values: values})})
        .then(function () {
          clearErrors();
          document.getElementById("setup-studio-status").textContent = "saved";
          refreshTasks();
        })
        .catch(function (err) { showError("could not save: " + err.message, form); });
    });
  });

  // ------------------------------------------------------ alert destination

  // SYS-1(b) (usability sweep 2026-09-03). The SAVE goes through the task's
  // own run() (POST /api/v1/setup/alerts), so the checklist row below and
  // this form can never report different things.
  document.addEventListener("DOMContentLoaded", function () {
    var form = document.getElementById("setup-alerts-form");
    if (!form) return;
    var status = document.getElementById("setup-alerts-status");
    form.addEventListener("submit", function (evt) {
      evt.preventDefault();
      var payload = {
        email: form.email.value.trim(),
        webhook: form.webhook.value.trim(),
      };
      api("/api/v1/setup/alerts", {method: "POST", body: JSON.stringify(payload)})
        .then(function (state) {
          clearErrors();
          status.textContent = state.detail || state.status;
          refreshTasks();
        })
        .catch(function (err) {
          showError("could not save a destination: " + err.message, form);
        });
    });
    var testBtn = document.getElementById("setup-alerts-test");
    if (testBtn) {
      testBtn.addEventListener("click", function () {
        testBtn.disabled = true;
        status.textContent = "sending...";
        api("/api/v1/setup/alerts/test", {method: "POST"})
          .then(function (result) {
            clearErrors();
            status.textContent = result.ok
              ? ("test sent to " + (result.sent_to || "the destination you set") + ".")
              : ("the test could not be sent: " + result.detail);
            refreshTasks();
          })
          .catch(function (err) {
            showError("could not send a test: " + err.message, testBtn);
          })
          .finally(function () { testBtn.disabled = false; });
      });
    }
  });

  // -------------------------------------------------------------- checklist

  var STATUS_CLASS = {ok: "green", warn: "amber", fail: "red", todo: "", skipped: ""};

  function renderTasks(data) {
    var tbody = document.getElementById("setup-tasks-body");
    tbody.innerHTML = "";
    data.tasks.forEach(function (task) {
      var tr = document.createElement("tr");
      // The anchor Done's own row links to (SYS-18).
      tr.id = "setup-task-" + task.id;
      var chipClass = STATUS_CLASS[task.status] || "";
      var detail = task.detail || "";
      // A recorded skip outlives the next CHECK, which writes the row back to
      // what the world looks like. Said out loud so a step an admin accepted
      // never reads as done, and never as forgotten either.
      if (task.skip_recorded_at && task.status !== "skipped") {
        detail += ' <span class="muted">(you chose to skip this on '
          + task.skip_recorded_at.slice(0, 10) + ')</span>';
      }
      tr.innerHTML =
        '<td>' + task.title + (task.optional ? ' <span class="muted">(optional)</span>' : '') + '</td>' +
        '<td><span class="chip ' + chipClass + '">' + task.status.toUpperCase() + '</span></td>' +
        '<td class="muted">' + detail + '</td>' +
        '<td class="task-actions"></td>';
      if (task.id === "done") {
        renderDoneLinks(tr, data.outstanding_for_done || []);
      }
      var actions = tr.querySelector(".task-actions");
      actions.appendChild(actionButton("CHECK", function (btn) { return taskAction(task.id, "check", btn); }));
      if (task.can_run) {
        actions.appendChild(actionButton(task.run_label || "DO IT",
                                         function (btn) { return taskAction(task.id, "run", btn); }));
      }
      if (task.optional && task.status !== "skipped") {
        // A step Done waits for is skipped on purpose or not at all, so its
        // button says what pressing it means (SYS-18).
        actions.appendChild(actionButton(task.gate ? "SKIP - I understand" : "SKIP",
                                         function (btn) { return taskAction(task.id, "skip", btn); }));
      }
      tbody.appendChild(tr);
    });
  }

  // Done names what it is waiting for, and every name is a link to the row
  // that fixes it (SYS-18): a sentence listing five titles is otherwise
  // something a reader has to match up against the table by eye.
  function renderDoneLinks(tr, outstanding) {
    if (!outstanding.length) return;
    var cell = tr.children[2];
    outstanding.forEach(function (item) {
      cell.appendChild(document.createTextNode(" "));
      var link = document.createElement("a");
      link.href = "#setup-task-" + item.id;
      link.textContent = "[ " + item.title.toUpperCase() + " ]";
      cell.appendChild(link);
    });
  }

  function actionButton(label, onClick) {
    var btn = document.createElement("button");
    btn.className = "btn";
    btn.type = "button";
    btn.textContent = "[ " + label + " ]";
    btn.style.marginRight = "0.3rem";
    btn.addEventListener("click", function () {
      btn.disabled = true;
      onClick(btn).finally(function () { btn.disabled = false; });
    });
    return btn;
  }

  function taskAction(id, action, anchor) {
    return api("/api/v1/setup/tasks/" + encodeURIComponent(id) + "/" + action, {method: "POST"})
      .then(function () { clearErrors(); return refreshTasks(); })
      .catch(function (err) {
        showError("could not " + action + " " + id + ": " + err.message, anchor);
      });
  }

  function refreshTasks() {
    return api("/api/v1/setup/tasks").then(renderTasks)
      .catch(function (err) { showError("could not load the checklist: " + err.message); });
  }

  document.addEventListener("DOMContentLoaded", function () {
    loadEula();
    loadAdminStep();
    refreshTasks();
  });
})();
