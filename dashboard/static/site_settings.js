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
        : "YouTube downloader has NO usable AI provider — "
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
    } else if (p.status === "not_signed_in") {
      // WE CANNOT COMPLETE AN INTERACTIVE OAUTH FROM THIS PAGE, and must not
      // look as though we could: the admin is given the exact command and
      // told where to run it.
      var hint = el("div", "muted");
      hint.appendChild(document.createTextNode("Sign in ON THE DASHBOARD HOST: "));
      hint.appendChild(el("code", null, p.login_command || ""));
      row.appendChild(hint);
      row.appendChild(testButton(p));
    } else if (p.status !== "disabled_by_site") {
      if (p.version) row.appendChild(el("div", "muted", p.version));
      row.appendChild(testButton(p));
    }
    if (p.kind === "cli" && p.status !== "disabled_by_site") {
      row.appendChild(cliPathControl(p));
    }
    return row;
  }

  function cliPathControl(p) {
    // The ONLY writable thing about a CLI provider: where the admin put the
    // binary. There is no install button, on purpose -- CC Sync ships and
    // fetches neither CLI.
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
        .then(function (r) { out.textContent = " " + (r.ok ? "OK — " : "FAILED — ") + r.detail; })
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
