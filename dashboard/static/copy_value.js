// [ COPY ] for the values an admin has to transcribe (DUI-1, usability +
// resilience sweep, 2026-09-04).
//
// A generated password and a fresh fleet token are shown exactly once, and
// until now the only way to take them off the page was to select 40 characters
// of monospace by hand. Nothing else on the dashboard that must be copied
// (a sha256, a device id) had a button either.
//
// Delegated from the document: the elements these buttons sit in arrive by
// htmx swap, so a listener bound at load to the button itself would be bound
// to nothing.
(function () {
  "use strict";

  function select(el) {
    // The fallback, and the thing that runs on http:// origins where
    // navigator.clipboard does not exist at all: leave the value selected so
    // one keystroke finishes the job.
    try {
      var range = document.createRange();
      range.selectNodeContents(el);
      var sel = window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    } catch (err) { /* selection is a nicety; never break the click */ }
  }

  // ui-dash-static-8 (2026-09-25): the idle label is read ONCE and kept on
  // the button. flash() used to save whatever the button said, so a second
  // click inside the 2 s window saved "[ COPIED ]" as the label to go back
  // to, and the button said COPIED for good over a password nobody copied.
  function flash(btn, label) {
    if (!btn.hasAttribute("data-idle-label")) {
      btn.setAttribute("data-idle-label", btn.textContent);
    }
    if (btn._copyTimer) clearTimeout(btn._copyTimer);
    btn.textContent = label || btn.getAttribute("data-copied-label") || "[ COPIED ]";
    btn._copyTimer = setTimeout(function () {
      btn._copyTimer = null;
      btn.textContent = btn.getAttribute("data-idle-label");
    }, 2000);
  }

  // ui-dash-static-8: on a plain-http origin navigator.clipboard is absent,
  // and the click used to select the value and change nothing on the button,
  // so the admin could not tell whether a one-time password was copied.
  // execCommand("copy") still works there from a click; when it does not,
  // the button says what is left to do.
  function legacyCopy(src, text) {
    var ok = false;
    var scratch = null;
    try {
      if (src) {
        select(src);
      } else {
        scratch = document.createElement("textarea");
        scratch.value = text;
        scratch.setAttribute("readonly", "");
        scratch.style.position = "fixed";
        scratch.style.top = "-1000px";
        document.body.appendChild(scratch);
        scratch.select();
      }
      ok = !!(document.execCommand && document.execCommand("copy"));
    } catch (err) {
      ok = false;
    }
    if (scratch && scratch.parentNode) scratch.parentNode.removeChild(scratch);
    return ok;
  }

  function fallback(btn, src, text) {
    if (legacyCopy(src, text)) { flash(btn); return; }
    if (src) {
      select(src);
      flash(btn, "[ SELECTED - PRESS CTRL+C ]");
    } else {
      flash(btn, "[ COULD NOT COPY ]");
    }
  }

  document.addEventListener("click", function (evt) {
    var btn = evt.target.closest && evt.target.closest(".copy-btn");
    if (!btn) return;
    var id = btn.getAttribute("data-copy-from");
    var src = id ? document.getElementById(id) : null;
    var text = src ? src.textContent.trim() : (btn.getAttribute("data-copy-value") || "");
    if (!text) return;
    evt.preventDefault();
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        flash(btn);
      }).catch(function () {
        fallback(btn, src, text);
      });
      return;
    }
    fallback(btn, src, text);
  });
})();
