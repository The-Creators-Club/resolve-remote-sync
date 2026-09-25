// The setup wizard's client, terminal look (UI redesign port phase 4, group
// settings-fleet, 2026-09-25). A fork of static/setup.js, which stays frozen
// for the classic page: the same fetch() calls to the same routes, the same
// ids and form names, the same reload after the admin account is created
// (a CSRF token has to be bound to the session that step starts; see the
// classic file's header). What differs:
//   - labels are plain words (the key face uppercases them by CSS); nothing
//     here wraps a label in brackets (plan 3.5, R12);
//   - the step strip and each step window's bar carry the checklist's status
//     for that step, so the page reads top to bottom;
//   - "Your studio" is prefilled from GET /api/v1/admin/site when signed in,
//     and a save sends only the fields the admin CHANGED or filled, so an
//     untouched default is never written down as an explicit value;
//   - an error is shown inside the step that failed and unfolds its window
//     (a refusal in a folded window would be invisible, plan 3.1);
//   - server text goes in through textContent, never innerHTML.
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
            var detail = body.detail;
            if (detail && typeof detail !== "string") detail = JSON.stringify(detail);
            var err = new Error(detail || ("HTTP " + resp.status));
            err.status = resp.status;
            throw err;
          });
      }
      return resp.status === 204 ? null : resp.json();
    });
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function reveal(node) {
    if (node && typeof window.ccsyncRevealField === "function") window.ccsyncRevealField(node);
  }

  // DUI-6: the message goes into a slot inside the step that failed, and
  // every older message clears first.
  function clearErrors() {
    var top = document.getElementById("setup-error");
    if (top) { top.style.display = "none"; top.textContent = ""; }
    document.querySelectorAll(".setup-step-error").forEach(function (node) {
      if (node.parentNode) node.parentNode.removeChild(node);
    });
  }

  function errorSlot(anchor) {
    var host = anchor && anchor.closest
      ? (anchor.closest("form") || anchor.closest("td") || anchor.closest(".body") || anchor.closest("section"))
      : null;
    if (!host) return null;
    var slot = el("div", "note err error-banner form-error setup-step-error");
    slot.setAttribute("role", "alert");
    host.appendChild(slot);
    return slot;
  }

  function showError(message, anchor) {
    clearErrors();
    if (!message) return;
    var node = errorSlot(anchor) || document.getElementById("setup-error");
    if (!node) return;
    node.style.display = "";
    node.textContent = message;
    reveal(node);
    if (node.scrollIntoView) node.scrollIntoView({block: "center"});
  }

  // ------------------------------------------------------------ status tags

  var TAG_CLASS = {ok: "ok", warn: "warn", fail: "err", todo: "mute", skipped: "mute"};
  var STATUS_WORD = {ok: "done", warn: "check this", fail: "failed", todo: "to do", skipped: "skipped"};

  function statusTag(status) {
    var tag = el("span", "tag " + (TAG_CLASS[status] || "mute"), STATUS_WORD[status] || status);
    return tag;
  }

  function paintSteps(tasks) {
    var byId = {};
    tasks.forEach(function (t) { byId[t.id] = t; });
    document.querySelectorAll(".setup-step-status[data-task]").forEach(function (slot) {
      var task = byId[slot.getAttribute("data-task")];
      slot.textContent = "";
      slot.appendChild(task ? statusTag(task.status) : el("span", "tag mute", "not listed"));
    });
    document.querySelectorAll("#setup-strip .s[data-task]").forEach(function (link) {
      var task = byId[link.getAttribute("data-task")];
      link.classList.toggle("done", !!task && (task.status === "ok" || task.status === "skipped"));
    });
    var cur = null;
    document.querySelectorAll("#setup-strip .s[data-task]").forEach(function (link) {
      link.classList.remove("cur");
      link.removeAttribute("aria-current");
      if (!cur && !link.classList.contains("done")) cur = link;
    });
    if (cur) { cur.classList.add("cur"); cur.setAttribute("aria-current", "step"); }
  }

  // ------------------------------------------------------------------ EULA

  function loadEula() {
    api("/api/v1/setup/eula").then(function (data) {
      document.getElementById("setup-eula-text").textContent =
        data.text || "(no EULA shipped in this build)";
      var box = document.getElementById("setup-eula-checkbox");
      var btn = document.getElementById("setup-eula-accept");
      if (!data.text) { btn.disabled = true; return; }
      box.addEventListener("change", function () { btn.disabled = !box.checked; });
    }).catch(function (err) {
      showError("could not load the EULA: " + err.message, document.getElementById("setup-eula-text"));
    });
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

  // ------------------------------------------------------------ admin step

  function loadAdminStep() {
    var body = document.getElementById("setup-admin-body");
    api("/api/v1/setup/status").then(function () {
      renderAdminForm(body);
    }).catch(function (err) {
      body.textContent = "";
      var msg;
      if (err.status === 404) msg = "not available in this build";
      else if (err.status === 401 || err.status === 403) msg = "an admin account already exists";
      else msg = "could not check: " + err.message;
      body.appendChild(el("span", "muted", msg));
    });
  }

  function field(labelText, id, type, name, autocomplete) {
    var row = el("div", "form-row");
    var lbl = el("label", "lbl", labelText);
    lbl.setAttribute("for", id);
    var inp = el("input", "inp");
    inp.id = id; inp.type = type; inp.name = name;
    inp.setAttribute("autocomplete", autocomplete);
    row.appendChild(lbl); row.appendChild(inp);
    return row;
  }

  function renderAdminForm(body) {
    body.textContent = "";
    var form = el("form", "form");
    form.id = "setup-admin-form";
    form.appendChild(field("username", "setup-admin-user", "text", "username", "username"));
    form.appendChild(field("password", "setup-admin-pw", "password", "password", "new-password"));
    var row = el("div", "form-row");
    row.appendChild(el("span"));
    var btn = el("button", "key primary");
    btn.type = "submit";
    btn.title = "Makes the first admin account and signs you in with it.";
    btn.appendChild(el("span", "t", "create"));
    row.appendChild(btn);
    form.appendChild(row);
    body.appendChild(form);
    form.addEventListener("submit", function (evt) {
      evt.preventDefault();
      var payload = {
        username: form.username.value.trim(),
        password: form.password.value,
      };
      api("/api/v1/setup/admin", {method: "POST", body: JSON.stringify(payload)})
        .then(function () { window.location.reload(); })
        .catch(function (err) {
          showError("could not create the admin account: " + err.message, form);
        });
    });
  }

  // ---------------------------------------------------------------- studio

  var STUDIO_KEYS = ["org_name", "org_short", "tree_name", "canonical_prefix", "template_folders"];
  var prefilled = {};

  function prefillStudio(form) {
    var main = document.getElementById("setup-main");
    if (!main || !main.getAttribute("data-signed-in")) return;
    api("/api/v1/admin/site").then(function (site) {
      if (!site) return;
      STUDIO_KEYS.forEach(function (k) {
        var v = site[k];
        if (Array.isArray(v)) v = v.join(", ");
        if (v === undefined || v === null) v = "";
        v = String(v);
        var input = form[k];
        // Never over what the admin has already typed.
        if (!input || input.value) return;
        input.value = v;
        prefilled[k] = v;
      });
    }).catch(function () { /* a first-run visitor has no admin session: blank is right */ });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var form = document.getElementById("setup-studio-form");
    if (!form) return;
    prefillStudio(form);
    form.addEventListener("submit", function (evt) {
      evt.preventDefault();
      var values = {};
      STUDIO_KEYS.forEach(function (k) {
        var v = form[k].value;
        // Blank is dropped (an empty DRIVE LETTER must not clobber the
        // built-in default), and so is a value still equal to what was
        // prefilled: only what the admin changed is written.
        if (!v) return;
        if (Object.prototype.hasOwnProperty.call(prefilled, k) && prefilled[k] === v) return;
        values[k] = v;
      });
      var status = document.getElementById("setup-studio-status");
      if (!Object.keys(values).length) {
        clearErrors();
        status.textContent = "nothing changed";
        return;
      }
      api("/api/v1/admin/site", {method: "PUT", body: JSON.stringify({values: values})})
        .then(function () {
          clearErrors();
          Object.keys(values).forEach(function (k) { prefilled[k] = values[k]; });
          status.textContent = "saved";
          refreshTasks();
        })
        .catch(function (err) { showError("could not save: " + err.message, form); });
    });
  });

  // ------------------------------------------------------ alert destination

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

  function actionButton(label, tip, onClick) {
    var btn = el("button", "key sm");
    btn.type = "button";
    if (tip) btn.title = tip;
    btn.appendChild(el("span", "t", label));
    btn.addEventListener("click", function () {
      btn.disabled = true;
      onClick(btn).finally(function () { btn.disabled = false; });
    });
    return btn;
  }

  function renderTasks(data) {
    var tbody = document.getElementById("setup-tasks-body");
    tbody.textContent = "";
    data.tasks.forEach(function (task) {
      var tr = document.createElement("tr");
      tr.id = "setup-task-" + task.id;
      var tdStep = el("td", "", task.title);
      tdStep.setAttribute("data-label", "step");
      if (task.optional) {
        tdStep.appendChild(document.createTextNode(" "));
        tdStep.appendChild(el("span", "muted", "(optional)"));
      }
      var tdStatus = el("td");
      tdStatus.setAttribute("data-label", "status");
      tdStatus.appendChild(statusTag(task.status));
      var tdDetail = el("td", "muted", task.detail || "");
      tdDetail.setAttribute("data-label", "detail");
      if (task.skip_recorded_at && task.status !== "skipped") {
        tdDetail.appendChild(document.createTextNode(" "));
        tdDetail.appendChild(el("span", "muted",
          "(you chose to skip this on " + task.skip_recorded_at.slice(0, 10) + ")"));
      }
      if (task.id === "done") renderDoneLinks(tdDetail, data.outstanding_for_done || []);
      var actions = el("td", "task-actions");
      actions.setAttribute("data-label", "");
      var wrap = el("div", "inline");
      actions.appendChild(wrap);
      wrap.appendChild(actionButton("check", "Looks again at how this step stands. Changes nothing.",
        function (btn) { return taskAction(task.id, "check", btn); }));
      if (task.can_run) {
        wrap.appendChild(actionButton((task.run_label || "do it").toLowerCase(), task.description || "",
          function (btn) { return taskAction(task.id, "run", btn); }));
      }
      if (task.optional && task.status !== "skipped") {
        wrap.appendChild(actionButton(task.gate ? "skip, I understand" : "skip",
          task.gate ? "Setup counts as done without this step. You can come back and do it later."
                    : "Marks this optional step as skipped. You can still do it later.",
          function (btn) { return taskAction(task.id, "skip", btn); }));
      }
      tr.appendChild(tdStep); tr.appendChild(tdStatus); tr.appendChild(tdDetail); tr.appendChild(actions);
      tbody.appendChild(tr);
    });
    paintSteps(data.tasks);
  }

  // Done names what it is waiting for, each name a link to its row (SYS-18).
  function renderDoneLinks(cell, outstanding) {
    outstanding.forEach(function (item) {
      cell.appendChild(document.createTextNode(" "));
      var link = el("a", "hi", item.title);
      link.href = "#setup-task-" + item.id;
      cell.appendChild(link);
    });
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
      .catch(function (err) {
        showError("could not load the checklist: " + err.message,
                  document.getElementById("setup-tasks-table"));
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    loadEula();
    loadAdminStep();
    refreshTasks();
  });
})();
