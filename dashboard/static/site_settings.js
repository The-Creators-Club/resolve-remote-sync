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
