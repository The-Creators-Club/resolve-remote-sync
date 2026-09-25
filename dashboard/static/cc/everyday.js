// The everyday pages' one behaviour of their own (UI redesign port phase 3).
//
// Transfers polls with hx-swap="none" + hx-select-oob, so the window frames
// stay put and only the lists change (plan 3.1). The shell's details keeper
// listens to ordinary swaps only; an out-of-band swap fires
// htmx:oobBeforeSwap / htmx:oobAfterSwap instead, so an open queue row would
// shut every two seconds. This keeps each details[data-key] as it was.
(function () {
  "use strict";
  var kept = {};
  document.addEventListener("htmx:oobBeforeSwap", function (evt) {
    var t = evt.detail && evt.detail.target;
    if (!t || !t.id || !t.querySelectorAll) return;
    var seen = {};
    t.querySelectorAll("details[data-key]").forEach(function (d) {
      seen[d.getAttribute("data-key")] = d.hasAttribute("open");
    });
    kept[t.id] = seen;
  });
  document.addEventListener("htmx:oobAfterSwap", function (evt) {
    var t = evt.detail && evt.detail.target;
    if (!t || !t.id) return;
    var live = document.getElementById(t.id);
    var seen = kept[t.id];
    delete kept[t.id];
    if (!live || !seen) return;
    live.querySelectorAll("details[data-key]").forEach(function (d) {
      var k = d.getAttribute("data-key");
      if (!(k in seen)) return;
      if (seen[k]) d.setAttribute("open", "");
      else d.removeAttribute("open");
    });
  });
})();
