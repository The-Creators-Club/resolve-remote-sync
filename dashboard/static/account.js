// The /account page's small behaviours (account page 2026-09-25,
// docs/ACCOUNT_PAGE_FEATURES.md 6.1). Everything is delegated from document,
// because every panel here is re-rendered by htmx and a listener bound to an
// element would survive exactly one swap. Nothing here decides anything the
// server does not decide again: the counter and the match hint are hints, the
// last-kind guard is repeated by the route, and the add row only builds the
// URL of the existing toggle route.
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }

  // ------------------------------------------------ the password hints
  function pwHints() {
    var form = $("account-pw-form");
    if (!form) return;
    var min = parseInt(form.getAttribute("data-min") || "12", 10) || 12;
    var a = ($("account-pw1") || {}).value || "";
    var b = ($("account-pw2") || {}).value || "";
    var count = $("account-pw-count");
    if (count) {
      count.textContent = !a.length ? ("0 of " + min + " characters")
        : a.length < min ? (a.length + " of " + min + " characters: " + (min - a.length) + " more to go")
        : (a.length + " characters: long enough");
      count.className = "field-hint " + (a.length && a.length < min ? "amber" : a.length ? "ok" : "muted");
    }
    var match = $("account-pw-match");
    if (match) {
      match.textContent = !b ? "type it again" : a === b ? "the two match" : "the two do not match yet";
      match.className = "field-hint " + (!b ? "muted" : a === b ? "ok" : "amber");
    }
  }
  document.addEventListener("input", function (evt) {
    var id = evt.target && evt.target.id;
    if (id === "account-pw1" || id === "account-pw2") pwHints();
  });
  document.addEventListener("change", function (evt) {
    if (!evt.target || evt.target.id !== "account-pw-show") return;
    ["account-pw0", "account-pw1", "account-pw2"].forEach(function (id) {
      var el = $(id);
      if (el) el.type = evt.target.checked ? "text" : "password";
    });
  });
  // The two refusals a browser can make on its own, before anything is sent.
  // The server makes both again, in the same words.
  document.addEventListener("htmx:confirm", function (evt) {
    var form = evt.target;
    if (!form || form.id !== "account-pw-form") return;
    var min = parseInt(form.getAttribute("data-min") || "12", 10) || 12;
    var a = ($("account-pw1") || {}).value || "";
    var b = ($("account-pw2") || {}).value || "";
    var say = "";
    if (a.length < min) say = "The new password needs at least " + min + " characters. Nothing changed.";
    else if (a !== b) say = "The two new passwords are not the same. Nothing changed.";
    if (!say) return;
    evt.preventDefault();
    var slot = $("account-pw-result");
    if (slot) {
      slot.textContent = "";
      var line = document.createElement("div");
      line.className = "account-result red";
      line.setAttribute("role", "status");
      line.textContent = say;
      slot.appendChild(line);
    }
  });

  // ------------------------------------------- the last kind of fleet work
  // 4.8: an empty kinds list means EVERY kind on the wire, so unticking the
  // last box would ask for the opposite of what was meant. Capture phase, so
  // the form's own htmx change listener never sees the event.
  document.addEventListener("change", function (evt) {
    var box = evt.target;
    if (!box || box.name !== "jobs_kinds" || box.checked) return;
    var form = box.form;
    if (!form) return;
    var left = form.querySelectorAll('input[name="jobs_kinds"]:checked').length;
    if (left) return;
    evt.stopPropagation();
    box.checked = true;
    var say = form.getAttribute("data-last-kind") || "";
    var note = form.parentNode && form.parentNode.querySelector(".account-last-kind");
    if (!note) {
      note = document.createElement("div");
      note.className = "account-result red account-last-kind";
      note.setAttribute("role", "status");
      form.parentNode.insertBefore(note, form.nextSibling);
    }
    note.textContent = say;
  }, true);

  // ------------------------------------------------ tick a project here
  // The slug is a PATH segment of the existing toggle route, so a plain form
  // cannot carry it. A FULL tick onto a nearly full computer asks the UX-1
  // capacity question first, as every other tick does.
  document.addEventListener("click", function (evt) {
    var btn = evt.target && evt.target.closest && evt.target.closest(".account-add [data-add-mode]");
    if (!btn) return;
    var row = btn.closest(".account-add");
    var select = row && row.querySelector("select");
    if (!select || !select.value || !window.htmx) return;
    var mode = btn.getAttribute("data-add-mode");
    var option = select.options[select.selectedIndex];
    var warning = option ? (option.getAttribute("data-warning") || "") : "";
    if (mode === "full" && warning && !window.confirm(warning + " Sync it there anyway?")) return;
    var url = "/partials/selection/" + encodeURIComponent(row.getAttribute("data-editor")) +
      "/" + encodeURIComponent(select.value) + "/toggle?machine=" +
      encodeURIComponent(row.getAttribute("data-machine")) + "&mode=" + encodeURIComponent(mode);
    var panel = $(row.getAttribute("data-panel"));
    window.htmx.ajax("POST", url, { source: btn, swap: "none" }).then(function () {
      if (panel) window.htmx.trigger(panel, "account-refresh");
    });
  });
})();
