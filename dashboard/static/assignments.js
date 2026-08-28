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

  // UX-1 (resilience sweep 2026-08-28): the capacity preflight. Twelve
  // projects and 4 TB of proxies onto a 500 GB MacBook used to be one silent
  // click: every tick succeeded, lane B had no free-space check, rclone
  // filled the disk and the machine became unusable for Resolve too.
  //
  // The two figures are rendered into the cell by the page (the NAS proxy
  // bytes for the project, the free space this computer last reported), so a
  // click needs no round trip. The rule below MIRRORS health.capacity_warning
  // and health.DISK_RED_FREE_BYTES on the server: warn once the tick would
  // land within 20 GB of full, or once it is more than half of what is left.
  // It REFUSES NOTHING -- the owner may know something we do not.
  var RED_FREE_BYTES = 20 * 1024 * 1024 * 1024;
  var WARN_FRACTION = 0.5;

  function fmtBytes(n) {
    var value = Number(n);
    var units = ["B", "KB", "MB", "GB"];
    var i = 0;
    while (value >= 1024 && i < units.length - 1) { value /= 1024; i += 1; }
    if (units[i] === "GB" && value >= 1024) return (value / 1024).toFixed(1) + " TB";
    return value.toFixed(0) + " " + units[i];
  }

  function numberOr(value, fallback) {
    if (value === undefined || value === null || value === "") return fallback;
    var n = Number(value);
    return isNaN(n) ? fallback : n;
  }

  // null when either figure is unknown, or when it fits with room to spare.
  function capacitySentence(what, proxyBytes, machine, freeBytes, verb) {
    if (!proxyBytes || freeBytes === null) return null;
    var fitsWithRoom = (proxyBytes + RED_FREE_BYTES <= freeBytes)
      && (proxyBytes < freeBytes * WARN_FRACTION);
    if (fitsWithRoom) return null;
    var sentence = what + " " + (verb || "is") + " " + fmtBytes(proxyBytes) + " of proxies. "
      + machine + " has " + fmtBytes(freeBytes) + " free.";
    if (proxyBytes > freeBytes) sentence += " That is more than will fit.";
    return sentence;
  }

  function confirmCapacity(sentence) {
    if (!sentence) return true;
    return window.confirm(sentence + "

Sync it there anyway?");
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
      if (wanted && !confirmCapacity(capacitySentence(
            box.dataset.projectLabel || box.dataset.slug,
            numberOr(box.dataset.proxyBytes, 0),
            box.dataset.machineLabel || box.dataset.machine || box.dataset.editor,
            numberOr(box.dataset.freeBytes, null)))) {
        box.checked = false;   // the browser already flipped it
        return;
      }
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
  function runColumn(editor, machine, wanted, freeBytes, machineLabel) {
    var who = machine ? (editor + " on " + machine) : editor;
    var boxes = columnBoxes(editor, machine).filter(function (b) { return b.checked !== wanted; });
    if (!boxes.length) return;
    if (wanted) {
      // The COLUMN TOTAL (UX-1): [ ALL ] is the click the finding was written
      // about, and one project at a time each looked affordable.
      var total = 0;
      var known = 0;
      for (var b = 0; b < boxes.length; b++) {
        var bytes = numberOr(boxes[b].dataset.proxyBytes, null);
        if (bytes !== null) { total += bytes; known += 1; }
      }
      var what = boxes.length + " project" + (boxes.length === 1 ? "" : "s");
      if (known < boxes.length) {
        what += " (" + known + " of them measured)";
      }
      if (!confirmCapacity(capacitySentence(
            what, total, machineLabel || machine || editor,
            freeBytes === undefined ? null : freeBytes,
            boxes.length === 1 ? "is" : "are"))) {
        return;
      }
    }
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
                allBtn.getAttribute("data-col-machine"), true,
                numberOr(allBtn.getAttribute("data-col-free"), null),
                allBtn.getAttribute("data-col-label"));
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
