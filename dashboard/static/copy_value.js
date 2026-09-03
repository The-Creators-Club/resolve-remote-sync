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

  function flash(btn) {
    var was = btn.textContent;
    btn.textContent = btn.getAttribute("data-copied-label") || "[ COPIED ]";
    setTimeout(function () { btn.textContent = was; }, 2000);
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
        if (src) select(src);
      });
      return;
    }
    if (src) select(src);
  });
})();
