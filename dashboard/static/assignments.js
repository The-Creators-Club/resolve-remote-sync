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

  // ?machine= (2026-08-18): the plan belongs to a COMPUTER, so every cell
  // names one. A cell for an editor whose companion has never reported has
  // an empty machine and writes without the parameter, which the dashboard
  // reads as "every computer this person has" -- for them, none yet, so it
  // lands in the unassigned bucket their first report adopts.
  function selectionUrl(editor, slug, machine, mode) {
    var url = "/api/v1/selection/" + encodeURIComponent(editor) + "/" + encodeURIComponent(slug);
    var params = [];
    if (machine) params.push("machine=" + encodeURIComponent(machine));
    if (mode) params.push("mode=" + encodeURIComponent(mode));
    if (params.length) url += "?" + params.join("&");
    return url;
  }

  // One write, used by both a single click and the column tools. Marks the
  // box "saving" (CSS pulse) and disabled for the round trip so a second
  // click mid-flight cannot race the first. `mode` rides the PUT only
  // ("full" or "upload_only"); a DELETE is an untick whatever the mode was.
  function writeCell(box, checked, mode) {
    box.disabled = true;
    box.classList.add("is-saving");
    return fetch(selectionUrl(box.dataset.editor, box.dataset.slug, box.dataset.machine,
                              checked ? mode : ""), {
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

  // The two boxes of one cell: the tick and its upload-only qualifier.
  function siblingBox(box, cls) {
    var cell = box.closest && box.closest("td");
    return cell ? cell.querySelector("." + cls) : null;
  }

  function setUpmode(upBox, on) {
    if (!upBox) return;
    upBox.checked = on;
    var label = upBox.closest && upBox.closest(".assign-upmode");
    if (label) label.classList.toggle("on", on);
  }

  grid.addEventListener("change", function (evt) {
    var box = evt.target;
    if (!box.classList) return;
    if (box.classList.contains("matrix-check")) {
      // The main tick. Ticking is always a FULL tick; unticking clears the
      // upload-only qualifier with it (the row is gone either way).
      var wanted = box.checked;
      var upBox = siblingBox(box, "matrix-upmode");
      var upWas = upBox ? upBox.checked : false;
      setUpmode(upBox, false);
      writeCell(box, wanted, "full").catch(function (err) {
        box.checked = !wanted;   // rollback: the browser already flipped it
        setUpmode(upBox, upWas);
        toast('could not update "' + box.dataset.editor + '": ' + err.message, "err");
      });
      return;
    }
    if (box.classList.contains("matrix-upmode")) {
      // The qualifier: on = tick as upload-only (ticking the project if it
      // was not), off = back to a full tick. Never an untick.
      var on = box.checked;
      var mainBox = siblingBox(box, "matrix-check");
      var mainWas = mainBox ? mainBox.checked : false;
      if (mainBox) mainBox.checked = true;
      setUpmode(box, on);
      writeCell(box, true, on ? "upload_only" : "full").catch(function (err) {
        setUpmode(box, !on);
        if (mainBox) mainBox.checked = mainWas;
        toast('could not update "' + box.dataset.editor + '": ' + err.message, "err");
      });
    }
  });

  function columnBoxes(editor, machine) {
    return Array.prototype.filter.call(
      grid.querySelectorAll(".matrix-check"),
      function (b) {
        return b.dataset.editor === editor && (b.dataset.machine || "") === (machine || "");
      }
    );
  }

  // Sequential on purpose: a fleet can have ~100 projects, and firing every
  // write for one editor at once would be a hundred simultaneous rows
  // hitting that editor's selection queue -- easy to reorder (position is
  // insertion order), hard to reason about if one of them 404s midway.
  function runColumn(editor, machine, wanted) {
    var who = machine ? (editor + " on " + machine) : editor;
    var boxes = columnBoxes(editor, machine).filter(function (b) { return b.checked !== wanted; });
    if (!boxes.length) return;
    var i = 0;
    var failed = 0;
    (function next() {
      if (i >= boxes.length) {
        if (failed) {
          toast(failed + " of " + boxes.length + " change(s) failed for " + who, "err");
        } else {
          toast((wanted ? "ticked all for " : "unticked all for ") + who, "ok");
        }
        return;
      }
      var box = boxes[i++];
      box.checked = wanted;
      // A column tool only ever ADDS full ticks or REMOVES ticks: an
      // upload-only cell is already checked, so [ ALL ] skips it (the filter
      // above) and [ NONE ] unticks it like any other.
      if (!wanted) setUpmode(siblingBox(box, "matrix-upmode"), false);
      writeCell(box, wanted, "full").catch(function () {
        box.checked = !wanted;
        failed += 1;
      }).then(next);
    })();
  }

  grid.addEventListener("click", function (evt) {
    var allBtn = evt.target.closest && evt.target.closest("[data-col-all]");
    var noneBtn = evt.target.closest && evt.target.closest("[data-col-none]");
    if (allBtn) {
      runColumn(allBtn.getAttribute("data-col-all"),
                allBtn.getAttribute("data-col-machine"), true);
    }
    if (noneBtn) {
      runColumn(noneBtn.getAttribute("data-col-none"),
                noneBtn.getAttribute("data-col-machine"), false);
    }
  });

  // "copy from ..." (2026-08-18): a new computer starts with an empty plan on
  // purpose, so this is the one click that fills it from another of the same
  // person's machines. A full reload afterwards, deliberately: the whole
  // column changes, and re-deriving 100 checkboxes in JS from a response is
  // how the grid and the database drift apart.
  grid.addEventListener("change", function (evt) {
    var sel = evt.target;
    if (!sel.classList || !sel.classList.contains("assign-copy")) return;
    var source = sel.value;
    if (!source) return;
    var editor = sel.getAttribute("data-copy-editor");
    var target = sel.getAttribute("data-copy-target");
    sel.disabled = true;
    fetch("/api/v1/admin/machines/" + encodeURIComponent(editor) + "/" +
          encodeURIComponent(target) + "/copy-plan?source=" + encodeURIComponent(source), {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": CSRF },
    }).then(function (resp) {
      if (!resp.ok) {
        return resp.json().catch(function () { return {}; }).then(function (body) {
          throw new Error(body.detail || ("HTTP " + resp.status));
        });
      }
      return resp.json();
    }).then(function (body) {
      toast("copied " + body.projects + " project(s) from " + source + " to " + target, "ok");
      window.location.reload();
    }).catch(function (err) {
      sel.disabled = false;
      sel.value = "";
      toast("could not copy the plan: " + err.message, "err");
    });
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
