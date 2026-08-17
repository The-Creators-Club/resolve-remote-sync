// Admin assignment matrix (2026-08-17): every checkbox here is a plain
// fetch straight at the SAME PUT/DELETE /api/v1/selection/{editor}/{slug}
// the ?as= editor switcher's checkboxes use (auth.can_manage doesn't care
// whether an admin got to the editor's name via ?as= or by writing it into
// the URL directly). No new write endpoint exists for this page -- "tick
// all" / "untick all" just replay that one write per cell, sequentially, so
// there is never a second selection store to fall out of sync with the
// first.
(function () {
  "use strict";

  var grid = document.getElementById("assign-grid");
  if (!grid) return;

  var CSRF = (document.querySelector('meta[name="csrf"]') || {}).content || "";

  function toast(message, kind) {
    var host = document.getElementById("assign-toast");
    if (!host) return;
    var el = document.createElement("div");
    el.className = "toast " + (kind || "ok");
    el.textContent = message;
    host.appendChild(el);
    // Auto-dismiss: this is a confirmation, not something worth keeping
    // around, and a pile of stale toasts from a fast "tick all" would bury
    // the grid's own scrollbar.
    setTimeout(function () {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 4000);
  }

  function selectionUrl(editor, slug) {
    return "/api/v1/selection/" + encodeURIComponent(editor) + "/" + encodeURIComponent(slug);
  }

  // One write, used by both a single click and the column tools. Marks the
  // box "saving" (CSS pulse) and disabled for the round trip so a second
  // click mid-flight cannot race the first.
  function writeCell(box, checked) {
    box.disabled = true;
    box.classList.add("is-saving");
    return fetch(selectionUrl(box.dataset.editor, box.dataset.slug), {
      method: checked ? "PUT" : "DELETE",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": CSRF },
    }).then(function (resp) {
      if (!resp.ok) {
        return resp.json().catch(function () { return {}; }).then(function (body) {
          throw new Error(body.detail || ("HTTP " + resp.status));
        });
      }
      return resp.json();
    }).finally(function () {
      box.disabled = false;
      box.classList.remove("is-saving");
    });
  }

  grid.addEventListener("change", function (evt) {
    var box = evt.target;
    if (!box.classList || !box.classList.contains("matrix-check")) return;
    var wanted = box.checked;
    writeCell(box, wanted).catch(function (err) {
      box.checked = !wanted;   // rollback: the browser already flipped it
      toast('could not update "' + box.dataset.editor + '": ' + err.message, "err");
    });
  });

  function columnBoxes(editor) {
    return Array.prototype.filter.call(
      grid.querySelectorAll(".matrix-check"),
      function (b) { return b.dataset.editor === editor; }
    );
  }

  // Sequential on purpose: a fleet can have ~100 projects, and firing every
  // write for one editor at once would be a hundred simultaneous rows
  // hitting that editor's selection queue -- easy to reorder (position is
  // insertion order), hard to reason about if one of them 404s midway.
  function runColumn(editor, wanted) {
    var boxes = columnBoxes(editor).filter(function (b) { return b.checked !== wanted; });
    if (!boxes.length) return;
    var i = 0;
    var failed = 0;
    (function next() {
      if (i >= boxes.length) {
        if (failed) {
          toast(failed + " of " + boxes.length + " change(s) failed for " + editor, "err");
        } else {
          toast((wanted ? "ticked all for " : "unticked all for ") + editor, "ok");
        }
        return;
      }
      var box = boxes[i++];
      box.checked = wanted;
      writeCell(box, wanted).catch(function () {
        box.checked = !wanted;
        failed += 1;
      }).then(next);
    })();
  }

  grid.addEventListener("click", function (evt) {
    var allBtn = evt.target.closest && evt.target.closest("[data-col-all]");
    var noneBtn = evt.target.closest && evt.target.closest("[data-col-none]");
    if (allBtn) runColumn(allBtn.getAttribute("data-col-all"), true);
    if (noneBtn) runColumn(noneBtn.getAttribute("data-col-none"), false);
  });

  var filter = document.getElementById("assign-filter");
  if (filter) {
    filter.addEventListener("input", function () {
      var needle = filter.value.trim().toLowerCase();
      var rows = grid.querySelectorAll("tbody tr");
      for (var i = 0; i < rows.length; i++) {
        var label = rows[i].getAttribute("data-project-label") || "";
        rows[i].style.display = (!needle || label.indexOf(needle) !== -1) ? "" : "none";
      }
    });
  }
})();
