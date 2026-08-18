// Admin > Settings (ZERO_TOUCH_PLAN.md WP D, 2026-08-17). Plain fetch(),
// same reasoning as setup.js: PUT /api/v1/admin/site takes a JSON body
// ({values: {...}}), which a bare HTML form cannot post -- this page is
// always admin-session-gated (ui.page_admin_settings), so there is no
// first-run CSRF wrinkle to work around here, just the body shape.
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
            throw new Error(body.detail || ("HTTP " + resp.status));
          });
      }
      return resp.status === 204 ? null : resp.json();
    });
  }

  function showError(message) {
    var el = document.getElementById("settings-error");
    if (!el) return;
    if (!message) { el.style.display = "none"; el.textContent = ""; return; }
    el.style.display = "";
    el.textContent = "▲ " + message;
  }

  // ------------------------------------------------------- AI providers
  // 2026-08-18. The ordered chain, each provider's status, the key inputs and
  // the pin. Everything here is drawn from GET /api/v1/admin/ai-providers, so
  // the page can never show an order or a status the server does not agree
  // with -- and a key is only ever SENT (in a body), never received: the API
  // answers a mask.

  var AI_ERR = "ai-error";

  function showAiError(message) {
    var el = document.getElementById(AI_ERR);
    if (!el) return;
    if (!message) { el.style.display = "none"; el.textContent = ""; return; }
    el.style.display = "";
    el.textContent = "▲ " + message;
  }

  function chipClass(status) {
    if (status === "available") return "chip green";
    if (status === "not_signed_in" || status === "unknown") return "chip amber";
    if (status === "disabled_by_site") return "chip";
    return "chip red";
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  }

  function loadAiProviders() {
    if (!document.getElementById("ai-providers")) return;
    api("/api/v1/admin/ai-providers")
      .then(renderAiProviders)
      .catch(function (err) {
        showAiError("could not read the AI providers: " + err.message);
      });
  }

  function renderAiProviders(data) {
    showAiError("");
    var host = document.getElementById("ai-providers");
    host.textContent = "";
    (data.providers || []).forEach(function (p) {
      host.appendChild(providerRow(p, data));
    });

    var resolved = document.getElementById("ai-resolved");
    if (resolved) {
      resolved.textContent = data.resolved && data.resolved.name
        ? "YouTube downloader will use: " + data.resolved.label
          + " (" + data.resolved.reason + ")"
        : "YouTube downloader has NO usable AI provider: "
          + (data.resolved ? data.resolved.reason : "nothing is configured");
    }

    var pref = document.getElementById("ai-preference");
    if (pref && !pref.dataset.wired) {
      pref.dataset.wired = "1";
      (data.providers || []).forEach(function (p) {
        var opt = document.createElement("option");
        opt.value = p.name;
        opt.textContent = p.rank + ". " + p.label;
        pref.appendChild(opt);
      });
      pref.addEventListener("change", function () {
        api("/api/v1/admin/ai-providers/preference", {
          method: "PUT",
          body: JSON.stringify({preference: pref.value}),
        }).then(renderAiProviders)
          .catch(function (err) { showAiError("could not pin: " + err.message); });
      });
    }
    if (pref) pref.value = data.preference || "auto";

    var flag = document.getElementById("ai-cli-enabled");
    if (flag) {
      flag.checked = !!data.cli_enabled;
      if (!flag.dataset.wired) {
        flag.dataset.wired = "1";
        flag.addEventListener("change", function () {
          // The flag is a site_setting like the two YouTube ones, so it goes
          // through the manifest route rather than growing a second writer.
          var values = {};
          values["features.ai_cli_providers"] = flag.checked ? "1" : "0";
          api("/api/v1/admin/site", {
            method: "PUT", body: JSON.stringify({values: values}),
          }).then(loadAiProviders)
            .catch(function (err) {
              showAiError("could not change the CLI provider setting: " + err.message);
            });
        });
      }
    }
    var tos = document.getElementById("ai-cli-tos");
    if (tos) tos.textContent = data.cli_tos_note || "";
  }

  function providerRow(p, data) {
    var row = el("div", "ai-provider");
    var head = el("div", "ai-provider-head");
    head.appendChild(el("span", "ai-rank", p.rank + "."));
    head.appendChild(el("strong", null, p.label));
    head.appendChild(el("span", chipClass(p.status), p.status_label));
    if (data.resolved && data.resolved.name === p.name) {
      head.appendChild(el("span", "chip green", "in use"));
    }
    row.appendChild(head);
    if (p.detail) row.appendChild(el("div", "muted", p.detail));

    if (p.kind === "api") {
      row.appendChild(apiControls(p));
    } else if (p.status !== "disabled_by_site") {
      if (p.version) row.appendChild(el("div", "muted", p.version));
      row.appendChild(cliControls(p));
    }
    if (p.kind === "cli" && p.status !== "disabled_by_site") {
      row.appendChild(cliPathControl(p));
    }
    return row;
  }

  // ------------------------------------------------------ the setup wizard
  // 2026-08-18. The old row said "no `claude` on this container's PATH.
  // Install it on the dashboard host" -- a sentence with a shell in it, for
  // customers who do not have one. These four steps do it from the page:
  // notice, install, sign in, test. Every step is drawn from
  // GET .../{name}/setup, so two browsers can never disagree about what is
  // installed and a reload never loses where the admin got to.

  function cliControls(p) {
    var wrap = el("div", "ai-key");
    var open = el("button", "btn", p.installed_by_wizard ? "[ MANAGE ]" : "[ SET UP ]");
    open.type = "button";
    open.addEventListener("click", function () {
      openWizard(p, wrap.parentNode);
    });
    wrap.appendChild(open);
    wrap.appendChild(testButton(p));
    if (p.status === "not_signed_in" && p.login_command) {
      // Still printed: an admin with a shell may prefer it, and it is the
      // fallback when the pty sign-in cannot run (a dashboard that is not on
      // Linux answers the sign-in route with exactly that refusal).
      wrap.appendChild(el("span", "muted", "or run `" + p.login_command + "` on the host"));
    }
    return wrap;
  }

  function openWizard(p, host) {
    if (!host) return;
    var existing = host.querySelector(".ai-wizard");
    if (existing) { existing.parentNode.removeChild(existing); return; }
    var panel = el("div", "ai-wizard");
    panel.style.border = "1px dotted #2a2a31";
    panel.style.padding = "0.6rem";
    panel.style.marginTop = "0.4rem";
    host.appendChild(panel);
    var state = {name: p.name, panel: panel, step: 0, accepted: false,
                 timer: null, testOut: "", mode: "subscription", touched: false};
    refreshWizard(state);
  }

  function stopPolling(state) {
    if (state.timer) { window.clearTimeout(state.timer); state.timer = null; }
  }

  function stillOpen(state) {
    return state.panel && state.panel.parentNode;
  }

  function refreshWizard(state) {
    return api("/api/v1/admin/ai-providers/" + state.name + "/setup")
      .then(function (data) { state.data = data; drawWizard(state); return data; })
      .catch(function (err) {
        state.panel.textContent = "";
        state.panel.appendChild(el("div", "banner", "▲ " + err.message));
      });
  }

  function wizardError(state, message) {
    var box = state.panel.querySelector(".ai-wizard-error");
    if (!box) return;
    box.textContent = message ? "▲ " + message : "";
    box.style.display = message ? "" : "none";
  }

  function stepHead(n, title, done) {
    var head = el("div", null);
    head.appendChild(el("span", "ai-rank", n + "."));
    head.appendChild(document.createTextNode(" "));
    head.appendChild(el("strong", null, title));
    if (done) {
      head.appendChild(document.createTextNode(" "));
      head.appendChild(el("span", "chip green", "done"));
    }
    return head;
  }

  function drawWizard(state) {
    if (!stillOpen(state)) { stopPolling(state); return; }
    var data = state.data || {};
    var panel = state.panel;
    panel.textContent = "";
    var installed = !!(data.install && data.install.installed);
    var signedIn = !!data.signed_in;
    // Land on the first UNFINISHED step, until the admin moves themselves.
    if (!state.touched) {
      state.step = (!installed && !state.accepted) ? 0
        : (!installed ? 1 : (!signedIn ? 2 : 3));
    }

    var box = el("div", "banner ai-wizard-error", "");
    box.style.display = "none";
    panel.appendChild(box);

    if (!data.supported && data.unsupported_detail) {
      panel.appendChild(el("div", "muted", data.unsupported_detail));
    }

    if (state.step === 0) { drawNotice(state, data); return; }
    if (state.step === 1) { drawInstall(state, data); return; }
    if (state.step === 2) { drawSignIn(state, data); return; }
    drawDone(state, data);
  }

  function drawNotice(state, data) {
    var panel = state.panel;
    var notice = data.notice || {};
    panel.appendChild(stepHead(1, notice.title || "Notice", false));
    (notice.text || "").split("\n\n").forEach(function (para) {
      var node = el("div", "muted", para);
      node.style.marginTop = "0.3rem";
      panel.appendChild(node);
    });
    var label = el("label", null);
    label.style.display = "block";
    label.style.marginTop = "0.5rem";
    var check = document.createElement("input");
    check.type = "checkbox";
    label.appendChild(check);
    label.appendChild(document.createTextNode(" " + (notice.checkbox || "")));
    panel.appendChild(label);

    var next = el("button", "btn", "[ CONTINUE ]");
    next.type = "button";
    next.disabled = true;
    check.addEventListener("change", function () { next.disabled = !check.checked; });
    next.addEventListener("click", function () {
      state.accepted = true;
      state.touched = true;
      state.step = 1;
      if (data.cli_enabled) { drawWizard(state); return; }
      // Accepting this notice IS turning the feature on. The flag and the
      // sentence about whose subscription gets spent are one decision, and an
      // admin should not have to go and find a second checkbox for it.
      var values = {};
      values["features.ai_cli_providers"] = "1";
      api("/api/v1/admin/site", {method: "PUT", body: JSON.stringify({values: values})})
        .then(function () { return refreshWizard(state); })
        .then(loadAiProviders)
        .catch(function (err) { wizardError(state, err.message); });
    });
    var actions = el("div", null);
    actions.style.marginTop = "0.5rem";
    actions.appendChild(next);
    panel.appendChild(actions);
  }

  function mib(bytes) {
    return (Number(bytes || 0) / 1048576).toFixed(1) + " MiB";
  }

  function progressBar(percent) {
    var outer = el("div", null);
    outer.style.border = "1px solid #2a2a31";
    outer.style.height = "0.6rem";
    outer.style.marginTop = "0.3rem";
    outer.style.maxWidth = "24rem";
    var fill = el("div", null);
    fill.style.height = "100%";
    fill.style.width = Math.max(0, Math.min(100, Number(percent || 0))) + "%";
    fill.style.background = "var(--red)";
    outer.appendChild(fill);
    return outer;
  }

  function drawInstall(state, data) {
    var panel = state.panel;
    var install = data.install || {};
    panel.appendChild(stepHead(2, "Install " + data.label, !!install.installed));
    panel.appendChild(el("div", "muted", "from " + (data.publisher || "the publisher")
      + ", checked against its published sha256 before anything runs"));
    if (install.installed) {
      panel.appendChild(el("div", "muted", "installed: "
        + (install.installed_version || "")
        + (install.unverified
           ? " (the publisher had no checksum for this download; the sha256 of "
             + "what arrived is recorded instead)"
           : "")));
    }
    if (install.state === "running") {
      panel.appendChild(el("div", "muted", (install.step || "working") + ": "
        + mib(install.bytes) + (install.total ? " of " + mib(install.total) : "")
        + " (" + (install.percent || 0) + "%)"));
      panel.appendChild(progressBar(install.percent));
      pollInstall(state);
    } else if (install.state === "error" && install.error) {
      panel.appendChild(el("div", "banner", "▲ " + install.error));
    } else if (install.detail) {
      panel.appendChild(el("div", "muted", install.detail));
    }

    var actions = el("div", "ai-key");
    var go = el("button", "btn", install.installed ? "[ UPDATE ]" : "[ INSTALL ]");
    go.type = "button";
    go.disabled = install.state === "running" || !data.supported;
    go.addEventListener("click", function () {
      wizardError(state, "");
      go.disabled = true;
      api("/api/v1/admin/ai-providers/" + state.name + "/install", {method: "POST"})
        .then(function (status) {
          state.touched = true;
          state.data.install = status;
          drawWizard(state);
        })
        .catch(function (err) { go.disabled = false; wizardError(state, err.message); });
    });
    actions.appendChild(go);
    if (install.installed && install.state !== "running") {
      var next = el("button", "btn", "[ NEXT: SIGN IN ]");
      next.type = "button";
      next.addEventListener("click", function () {
        state.touched = true; state.step = 2; drawWizard(state);
      });
      actions.appendChild(next);
    }
    panel.appendChild(actions);
  }

  function pollInstall(state) {
    stopPolling(state);
    state.timer = window.setTimeout(function () {
      if (!stillOpen(state)) return;
      api("/api/v1/admin/ai-providers/" + state.name + "/install-status")
        .then(function (status) {
          state.data.install = status;
          // A finished install changes the row's chip as well as this panel.
          if (status.state !== "running") { state.touched = true; loadAiProviders(); }
          drawWizard(state);
        })
        .catch(function (err) { wizardError(state, err.message); });
    }, 1000);
  }

  function drawSignIn(state, data) {
    var panel = state.panel;
    var signin = data.signin || {};
    var done = signin.state === "signed_in" || !!data.signed_in;
    panel.appendChild(stepHead(3, "Sign in to " + data.label, done));

    if ((data.modes || []).length && !done) {
      var pick = el("label", "muted", "");
      var select = document.createElement("select");
      (data.modes || []).forEach(function (m) {
        var opt = document.createElement("option");
        opt.value = m.value; opt.textContent = m.label;
        select.appendChild(opt);
      });
      select.value = state.mode;
      select.addEventListener("change", function () { state.mode = select.value; });
      pick.appendChild(document.createTextNode("account type "));
      pick.appendChild(select);
      panel.appendChild(pick);
    }

    var waiting = signin.state === "awaiting_code" || signin.state === "awaiting_browser";
    var starting = signin.state === "starting" || signin.state === "awaiting_url"
      || signin.state === "verifying";

    if (done) {
      panel.appendChild(el("div", "muted", "signed in"
        + (signin.account ? " as " + signin.account : "")));
    } else if (waiting) {
      var link = document.createElement("a");
      link.className = "btn";
      link.href = signin.url || "#";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "[ OPEN " + data.label.toUpperCase() + " SIGN-IN ]";
      panel.appendChild(link);
      if (signin.user_code) {
        panel.appendChild(el("div", "muted",
          "type this code on that page: " + signin.user_code));
      }
      if (signin.state === "awaiting_code") {
        var wrap = el("div", "ai-key");
        var input = document.createElement("input");
        input.type = "text";
        input.autocomplete = "off";
        input.placeholder = "paste the code from that page";
        input.setAttribute("aria-label", data.label + " sign-in code");
        wrap.appendChild(input);
        var submit = el("button", "btn", "[ SUBMIT CODE ]");
        submit.type = "button";
        submit.addEventListener("click", function () {
          wizardError(state, "");
          submit.disabled = true;
          // The code travels in a BODY, and this page keeps no copy of it.
          api("/api/v1/admin/ai-providers/" + state.name + "/signin/code", {
            method: "POST", body: JSON.stringify({code: input.value}),
          }).then(function (status) {
            input.value = "";
            state.data.signin = status;
            drawWizard(state);
          }).catch(function (err) {
            submit.disabled = false;
            wizardError(state, err.message);
          });
        });
        wrap.appendChild(submit);
        panel.appendChild(wrap);
      }
      panel.appendChild(el("div", "muted", "waiting for the sign-in to finish"
        + (signin.expires_in ? " (" + signin.expires_in + "s left)" : "")));
      pollSignIn(state);
    } else if (starting) {
      panel.appendChild(el("div", "muted", "starting the sign-in"));
      pollSignIn(state);
    } else if (signin.state === "failed" || signin.state === "cancelled") {
      panel.appendChild(el("div", "banner", "▲ " + (signin.detail || signin.state)));
    }

    var actions = el("div", "ai-key");
    if (!done && !waiting && !starting) {
      var start = el("button", "btn", "[ OPEN " + data.label.toUpperCase() + " SIGN-IN ]");
      start.type = "button";
      start.addEventListener("click", function () {
        wizardError(state, "");
        start.disabled = true;
        api("/api/v1/admin/ai-providers/" + state.name + "/signin", {
          method: "POST", body: JSON.stringify({mode: state.mode}),
        }).then(function (status) {
          state.touched = true;
          state.data.signin = status;
          // Opened from the CLICK's own chain: a window.open from a later poll
          // is what a popup blocker eats.
          if (status.url) window.open(status.url, "_blank", "noopener");
          drawWizard(state);
        }).catch(function (err) {
          start.disabled = false;
          wizardError(state, err.message);
        });
      });
      actions.appendChild(start);
    }
    if (done) {
      var next = el("button", "btn", "[ NEXT: TEST ]");
      next.type = "button";
      next.addEventListener("click", function () {
        state.touched = true; state.step = 3; drawWizard(state);
      });
      actions.appendChild(next);
    } else if (waiting || starting) {
      var cancel = el("button", "btn", "[ CANCEL ]");
      cancel.type = "button";
      cancel.addEventListener("click", function () {
        stopPolling(state);
        api("/api/v1/admin/ai-providers/" + state.name + "/signin/cancel", {method: "POST"})
          .then(function () { return refreshWizard(state); })
          .catch(function (err) { wizardError(state, err.message); });
      });
      actions.appendChild(cancel);
    }
    panel.appendChild(actions);
  }

  function pollSignIn(state) {
    stopPolling(state);
    state.timer = window.setTimeout(function () {
      if (!stillOpen(state)) return;
      api("/api/v1/admin/ai-providers/" + state.name + "/signin")
        .then(function (status) {
          var was = (state.data.signin || {}).state;
          state.data.signin = status;
          if (status.state === "signed_in" && was !== "signed_in") {
            state.data.signed_in = true;
            loadAiProviders();
          }
          drawWizard(state);
        })
        .catch(function (err) { wizardError(state, err.message); });
    }, 1500);
  }

  function drawDone(state, data) {
    var panel = state.panel;
    var install = data.install || {};
    panel.appendChild(stepHead(4, "Test and finish", false));
    panel.appendChild(el("div", "muted",
      (install.installed_version ? data.label + " " + install.installed_version : data.label)
      + (data.signed_in ? " - signed in" : " - not signed in")));
    var out = el("div", "muted", state.testOut || "");
    var actions = el("div", "ai-key");

    var test = el("button", "btn", "[ TEST ]");
    test.type = "button";
    test.addEventListener("click", function () {
      out.textContent = "testing…";
      var started = Date.now();
      api("/api/v1/admin/ai-providers/" + state.name + "/test", {method: "POST"})
        .then(function (r) {
          state.testOut = (r.ok ? "OK: " : "FAILED: ") + r.detail
            + " (" + ((Date.now() - started) / 1000).toFixed(1) + "s)";
          out.textContent = state.testOut;
          loadAiProviders();
        })
        .catch(function (err) { out.textContent = "failed: " + err.message; });
    });
    actions.appendChild(test);

    if (data.signed_in) {
      var signout = el("button", "btn", "[ SIGN OUT ]");
      signout.type = "button";
      signout.addEventListener("click", function () {
        api("/api/v1/admin/ai-providers/" + state.name + "/signin", {method: "DELETE"})
          .then(function () {
            state.touched = true; state.step = 2;
            return refreshWizard(state);
          })
          .then(loadAiProviders)
          .catch(function (err) { wizardError(state, err.message); });
      });
      actions.appendChild(signout);
    }

    var update = el("button", "btn", "[ UPDATE ]");
    update.type = "button";
    update.addEventListener("click", function () {
      state.touched = true; state.step = 1; drawWizard(state);
    });
    actions.appendChild(update);

    var remove = el("button", "btn", "[ REMOVE ]");
    remove.type = "button";
    remove.addEventListener("click", function () {
      // Says what goes, because the sign-in goes with it: the credential lives
      // in the $HOME inside the tree being deleted.
      if (!window.confirm("Remove " + data.label + " and its sign-in from this "
                          + "server? The YouTube downloader will fall back to "
                          + "the next available provider.")) return;
      api("/api/v1/admin/ai-providers/" + state.name + "/install", {method: "DELETE"})
        .then(function () { state.touched = false; return refreshWizard(state); })
        .then(loadAiProviders)
        .catch(function (err) { wizardError(state, err.message); });
    });
    actions.appendChild(remove);

    panel.appendChild(actions);
    panel.appendChild(out);
  }

  function cliPathControl(p) {
    // Where the admin put a binary THEY installed. A typed path still wins
    // over anything the wizard installed (ai_providers.cli_path): an admin
    // pointing at a file is telling us about their host.
    var wrap = el("div", "ai-key");
    var input = document.createElement("input");
    input.type = "text";
    input.value = p.configured_path || "";
    input.placeholder = p.path || ("full path to `" + p.name.replace("_", " ") + "` (blank = search PATH)");
    input.setAttribute("aria-label", p.label + " executable path");
    wrap.appendChild(input);
    var save = el("button", "btn", "[ SAVE PATH ]");
    save.type = "button";
    save.addEventListener("click", function () {
      api("/api/v1/admin/ai-providers/" + p.name + "/path", {
        method: "PUT", body: JSON.stringify({path: input.value}),
      }).then(renderAiProviders)
        .catch(function (err) { showAiError("could not save the path: " + err.message); });
    });
    wrap.appendChild(save);
    return wrap;
  }

  function apiControls(p) {
    var wrap = el("div", "ai-key");
    if (p.key_source === "env") {
      wrap.appendChild(el("span", "muted",
        "key " + (p.masked || "") + " set by the deployment (" + p.env_var + ")"));
      wrap.appendChild(testButton(p));
      return wrap;
    }
    var input = document.createElement("input");
    input.type = "password";
    input.autocomplete = "off";
    input.placeholder = p.key_present ? p.masked : "paste a key";
    input.setAttribute("aria-label", p.label + " API key");
    wrap.appendChild(input);

    var set = el("button", "btn", "[ SET ]");
    set.type = "button";
    set.addEventListener("click", function () {
      // The key travels in the BODY. Never a query string: those land in
      // access logs, browser history and every proxy in between.
      api("/api/v1/admin/ai-providers/" + p.name + "/key", {
        method: "PUT", body: JSON.stringify({key: input.value}),
      }).then(function (d) { input.value = ""; renderAiProviders(d); })
        .catch(function (err) { showAiError("could not save the key: " + err.message); });
    });
    wrap.appendChild(set);

    if (p.key_present) {
      var clear = el("button", "btn", "[ CLEAR ]");
      clear.type = "button";
      clear.addEventListener("click", function () {
        api("/api/v1/admin/ai-providers/" + p.name + "/key", {method: "DELETE"})
          .then(renderAiProviders)
          .catch(function (err) { showAiError("could not clear the key: " + err.message); });
      });
      wrap.appendChild(clear);
    }
    wrap.appendChild(testButton(p));
    return wrap;
  }

  function testButton(p) {
    var out = el("span", "muted");
    var btn = el("button", "btn", "[ TEST ]");
    btn.type = "button";
    btn.addEventListener("click", function () {
      out.textContent = " testing…";
      api("/api/v1/admin/ai-providers/" + p.name + "/test", {method: "POST"})
        .then(function (r) { out.textContent = " " + (r.ok ? "OK: " : "FAILED: ") + r.detail; })
        .catch(function (err) { out.textContent = " failed: " + err.message; });
    });
    var wrap = el("span", "ai-test");
    wrap.appendChild(btn);
    wrap.appendChild(out);
    return wrap;
  }

  document.addEventListener("DOMContentLoaded", function () {
    var form = document.getElementById("settings-form");
    if (form) {
      form.addEventListener("submit", function (evt) {
        evt.preventDefault();
        var values = {};
        Array.prototype.forEach.call(form.elements, function (el) {
          if (!el.name) return;
          if (el.readOnly) return;   // auto-derived fields are display-only
          if (el.type === "checkbox") {
            values[el.name] = el.checked ? "1" : "0";
          } else if (el.type === "radio") {
            // Every radio in a group shares one `name`; only the checked one
            // contributes a value (an unchecked one must not overwrite it --
            // form.elements iterates the whole group in DOM order).
            if (el.checked) values[el.name] = el.value;
          } else {
            values[el.name] = el.value;
          }
        });
        api("/api/v1/admin/site", {method: "PUT", body: JSON.stringify({values: values})})
          .then(function () {
            document.getElementById("settings-saved").textContent = "saved";
            showError("");
          })
          .catch(function (err) { showError("could not save: " + err.message); });
      });
    }

    loadAiProviders();

    var importForm = document.getElementById("settings-import-form");
    if (importForm) {
      importForm.addEventListener("submit", function (evt) {
        evt.preventDefault();
        api("/api/v1/admin/site/import", {
          method: "POST",
          body: JSON.stringify({text: importForm.text.value}),
        }).then(function () {
          window.location.reload();
        }).catch(function (err) { showError("could not import: " + err.message); });
      });
    }
  });
})();
