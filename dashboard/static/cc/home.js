/* CC Terminal: the home and project pages (UI port phase 2, group `home`).
 *
 *   find box  filters the projects tree. The box sits OUTSIDE the tree's
 *             30 s swap target, so its text survives a beat, and the filter
 *             is re-applied to whatever htmx settles in .tree-body. IME-safe
 *             (5.1, wave 6): nothing is filtered while a Zhuyin or Pinyin
 *             composition is open, only on compositionend, and both sides
 *             are compared NFC-normalised and lower-cased (CR-90's rule for
 *             a compare-only value). The "/" key focuses it.
 *   hash      /#fleet-collector opens the collector sub-window it names.
 *
 * No storage, no network: the tick is the checkbox's own hx-post.
 */
(function () {
  "use strict";

  function norm(s) {
    s = String(s || "");
    try { s = s.normalize("NFC"); } catch (e) { /* old engine: compare raw */ }
    return s.toLowerCase();
  }

  function applyFilter(box) {
    var win = box.closest(".win") || document;
    var body = win.querySelector(".tree-body");
    if (!body) return;
    var q = norm(box.value).trim();
    var rows = body.querySelectorAll(".row.proj");
    var shown = 0;
    rows.forEach(function (r) {
      var hit = !q || norm(r.getAttribute("data-name")).indexOf(q) !== -1;
      r.classList.toggle("cc-filtered", !hit);
      if (hit) shown += 1;
    });
    // Groups: hidden when nothing under them matches; opened while a filter
    // is typed so a match is visible, and left to the keeper otherwise.
    var groups = Array.prototype.slice.call(body.querySelectorAll("details.proj-group")).reverse();
    groups.forEach(function (g) {
      var any = g.querySelector(".row.proj:not(.cc-filtered)");
      g.classList.toggle("cc-filtered", !!q && !any);
      if (q && any && !g.open) { g.open = true; g.setAttribute("data-cc-filter-open", ""); }
      if (!q && g.hasAttribute("data-cc-filter-open")) { g.open = false; g.removeAttribute("data-cc-filter-open"); }
    });
    var none = body.querySelector(".tree-nomatch");
    if (none) none.hidden = !(q && rows.length && shown === 0);
  }

  function boxes() { return document.querySelectorAll(".home-page .tree-find"); }

  document.addEventListener("input", function (e) {
    var box = e.target;
    if (!box.classList || !box.classList.contains("tree-find")) return;
    if (e.isComposing) return;
    applyFilter(box);
  });
  document.addEventListener("compositionend", function (e) {
    var box = e.target;
    if (box.classList && box.classList.contains("tree-find")) applyFilter(box);
  });

  document.addEventListener("keydown", function (e) {
    if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey || e.isComposing) return;
    var t = e.target;
    var tag = t && t.tagName ? t.tagName.toLowerCase() : "";
    if (tag === "input" || tag === "textarea" || tag === "select" || (t && t.isContentEditable)) return;
    var box = boxes()[0];
    if (!box) return;
    e.preventDefault();
    box.focus();
  });

  document.addEventListener("htmx:afterSettle", function (e) {
    var el = e.target;
    if (!el || !el.classList || !el.classList.contains("tree-body")) return;
    var win = el.closest(".win");
    var box = win && win.querySelector(".tree-find");
    if (box && box.value) applyFilter(box);
  });

  // Once per hash: a reader who folds it again is not overruled by the next
  // 15 s beat.
  var opened = "";
  function openHashed() {
    var id = (location.hash || "").slice(1);
    if (!id || id === opened) return;
    var el = document.getElementById(id);
    if (el && el.tagName && el.tagName.toLowerCase() === "details") {
      el.open = true;
      opened = id;
    }
  }
  window.addEventListener("hashchange", function () { opened = ""; openHashed(); });
  document.addEventListener("htmx:afterSettle", openHashed);
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", openHashed);
  else openHashed();
})();
