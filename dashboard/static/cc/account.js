// The terminal /account page's small behaviours (UI redesign port phase 3,
// plan 2.1 and 3.3): a fork of static/account.js with the terminal classes.
// The classic file is untouched. Everything is delegated from document,
// because every panel here is re-rendered by htmx. Nothing here decides
// anything the server does not decide again: the counter and the match hint
// are hints, the last-kind guard is repeated by the route, and the add row
// only builds the URL of the existing toggle route (with view=none, so the
// answer is empty and no other page's markup reaches this one, R15).
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }

  function resultNote(tone, text) {
    var line = document.createElement("div");
    line.className = "note " + tone;
    line.setAttribute("role", "status");
    var span = document.createElement("span");
    span.className = "grow";
    span.textContent = text;
    line.appendChild(span);
    return line;
  }

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
      count.className = "hint acct-pw-hint" + (a.length && a.length < min ? " warn" : a.length ? " ok" : "");
    }
    var match = $("account-pw-match");
    if (match) {
      match.textContent = !b ? "type it again" : a === b ? "the two match" : "the two do not match yet";
      match.className = "hint acct-pw-hint" + (!b ? "" : a === b ? " ok" : " warn");
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
      slot.appendChild(resultNote("err", say));
    }
  });

  // ------------------------------------------- the last kind of fleet work
  // An empty kinds list means EVERY kind on the wire, so unticking the last
  // box would ask for the opposite of what was meant. Capture phase, so the
  // form's own htmx change listener never sees the event.
  document.addEventListener("change", function (evt) {
    var box = evt.target;
    if (!box || box.name !== "jobs_kinds" || box.checked) return;
    var form = box.form;
    if (!form) return;
    if (form.querySelectorAll('input[name="jobs_kinds"]:checked').length) return;
    evt.stopPropagation();
    box.checked = true;
    var say = form.getAttribute("data-last-kind") || "";
    var note = form.parentNode && form.parentNode.querySelector(".account-last-kind");
    if (!note) {
      note = resultNote("err", say);
      note.className += " account-last-kind";
      form.parentNode.insertBefore(note, form.nextSibling);
    } else {
      note.querySelector(".grow").textContent = say;
    }
  }, true);

  // ------------------------------------------------ tick a project here
  // The slug is a PATH segment of the existing toggle route, so a plain form
  // cannot carry it. A FULL tick onto a nearly full computer asks the UX-1
  // capacity question first, as every other tick does (a native confirm, as
  // classic: the answer is needed before the request is built).
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
      "/" + encodeURIComponent(select.value) + "/toggle?view=none&machine=" +
      encodeURIComponent(row.getAttribute("data-machine")) + "&mode=" + encodeURIComponent(mode);
    var panel = $(row.getAttribute("data-panel"));
    window.htmx.ajax("POST", url, { source: btn, swap: "none" }).then(function () {
      if (panel) window.htmx.trigger(panel, "account-refresh");
    });
  });
})();
