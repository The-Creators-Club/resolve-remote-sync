// The terminal look's page groups on the classic Settings page (UI port R24,
// phase 0). Sends ONLY {values: {ui_terminal_groups: "<csv>" | "none" |
// "site"}}: never a field of #settings-form, and that form's save never sends
// this key. `chrome` is ticked and locked while any other group is on,
// because every other group's pages are built inside the new header.
(function () {
  "use strict";

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf"]');
    return meta ? meta.getAttribute("content") || "" : "";
  }

  function boxes(form) {
    return Array.prototype.slice.call(form.querySelectorAll("input[data-ui-group]"));
  }

  function syncChrome(form) {
    var chrome = form.querySelector("input[data-ui-chrome]");
    if (!chrome) return;
    var others = boxes(form).some(function (b) { return b !== chrome && b.checked; });
    if (others) chrome.checked = true;
    chrome.disabled = others || chrome.hasAttribute("data-no-build");
  }

  function send(form, value) {
    var result = document.getElementById("ui-groups-result");
    if (result) result.textContent = "saving...";
    return fetch("/api/v1/admin/site", {
      method: "PUT",
      credentials: "same-origin",
      headers: {"Content-Type": "application/json", "X-CSRF-Token": csrfToken()},
      body: JSON.stringify({values: {ui_terminal_groups: value}})
    }).then(function (resp) {
      return resp.json().catch(function () { return {}; }).then(function (body) {
        if (!resp.ok) throw new Error((body && body.detail) || ("HTTP " + resp.status));
        return body;
      });
    }).then(function (body) {
      var stored = document.getElementById("ui-groups-stored");
      if (stored) stored.textContent = (body && body.ui_terminal_groups) || value;
      if (result) result.textContent = "saved. Each browser gets it on its next page load.";
    }).catch(function (err) {
      if (result) result.textContent = "not saved: " + err.message;
    });
  }

  function init() {
    var form = document.getElementById("ui-groups-form");
    if (!form) return;
    var chrome = form.querySelector("input[data-ui-chrome]");
    if (chrome && chrome.disabled) chrome.setAttribute("data-no-build", "");
    syncChrome(form);
    form.addEventListener("change", function () { syncChrome(form); });
    form.addEventListener("submit", function (evt) {
      evt.preventDefault();
      var on = boxes(form).filter(function (b) { return b.checked; })
        .map(function (b) { return b.value; });
      send(form, on.length ? on.join(",") : "none");
    });
    var reset = document.getElementById("ui-groups-default");
    if (reset) reset.addEventListener("click", function () { send(form, "site"); });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
