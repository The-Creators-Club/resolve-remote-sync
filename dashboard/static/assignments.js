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
    // DUI-5 (usability + resilience sweep, 2026-09-04): an ERROR stays until
    // it is clicked. "3 of 40 change(s) failed" used to vanish after four
    // seconds, from a corner of a page the admin was not looking at, and the
    // copy-plan path reloaded the window before its toast could be read at
    // all. A success still auto-dismisses: it is a confirmation, and a pile
    // of them from a fast "tick all" would bury the grid's own scrollbar.
    if (kind === "err") {
      el.title = "click to dismiss";
      el.addEventListener("click", function () {
        if (el.parentNode) el.parentNode.removeChild(el);
      });
      return;
    }
    setTimeout(function () {
      if (el.parentNode) el.parentNode.removeChild(el);
    }, 4000);
  }

  // DCORE-9 (usability sweep 2026-09-04): an EXPIRED SESSION is not an error
  // to toast. htmx's own polls handle expiry (HX-Redirect), but they only run
  // while the tab is visible -- so an admin coming back to a tab that sat in
  // the background overnight got the checkbox flipped back and `could not
  // tick <project>: login required`, which reads as a permissions bug. Every
  // fetch on this page routes its rejection through here first: a 401 sends
  // the browser to the login page with THIS page as ?next=, so signing in
  // lands back on the grid they were ticking.
  function signedOut(err) {
    if (!err || err.status !== 401) return false;
    window.location.href = (err.login || "/login") + "?next="
      + encodeURIComponent(window.location.pathname + window.location.search);
    return true;
  }

  // The rejection every fetch below throws: `detail` for a human, `status`
  // and `login` for signedOut().
  function httpError(resp, body) {
    var err = new Error((body && body.detail) || ("HTTP " + resp.status));
    err.status = resp.status;
    err.login = body && body.login;
    return err;
  }

  // What a cell is called, for a message a human reads. DUI-5: every toast on
  // this page named the EDITOR ("could not update jsmith") in a grid where the
  // editor is a whole column and the thing that failed is one cell.
  function cellLabel(box) {
    var project = box.dataset.projectLabel || box.dataset.slug || "that project";
    var machine = box.dataset.machineLabel || box.dataset.machine || box.dataset.editor;
    return machine ? (project + " on " + machine) : project;
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
    // bug-hunt-2026-09-03 dash-mounts-ui-1: the blank line between the two
    // sentences was written as two RAW newlines inside this literal, which is
    // a parse error for the whole file -- and the file is one IIFE, so every
    // listener in it (a tick, [ ALL ], the wired re-lock) was unregistered
    // and a click on the matrix wrote nothing, silently. Escaped, always.
    return window.confirm(sentence + "\n\nSync it there anyway?");
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
          throw httpError(resp, body);
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
      writeCell(box, wanted, "full").then(function () {
        // CR-28 follow-up (2026-08-30): a wired box that was ticked stays
        // enabled only so it can be unticked (template rule). Once that
        // untick lands, re-lock it -- the server refuses a re-tick anyway
        // (409), and a wired cell that stayed clickable would just invite
        // that refusal instead of explaining it up front.
        if (box.dataset.wired === "1" && !wanted) {
          box.disabled = true;
          box.title = (box.dataset.machineLabel || box.dataset.editor)
            + " is wired to the NAS: it works directly off the tree, so a new sync cannot be ticked here";
        }
      }).catch(function (err) {
        box.checked = !wanted;   // rollback: the browser already flipped it
        setUpmode(upBox, upWas);
        if (signedOut(err)) return;
        toast("could not tick " + cellLabel(box) + ": " + err.message, "err");
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
        if (signedOut(err)) return;
        toast("could not set upload-only for " + cellLabel(box) + ": " + err.message, "err");
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

  // The label a running column shows, and the flag its loop checks. DUI-5:
  // a column run gave no progress at all -- individual checkbox pulses inside
  // a grid that scrolls sideways -- and navigating away mid-run left the
  // column half applied with nothing said.
  function runProgress(btn, done, total) {
    if (!btn) return;
    if (btn.dataset.idleLabel === undefined) btn.dataset.idleLabel = btn.textContent;
    btn.textContent = "[ " + done + " / " + total + " ... ]";
    btn.title = "click to stop after the change that is in flight";
  }

  function runDone(btn) {
    if (!btn) return;
    if (btn.dataset.idleLabel !== undefined) btn.textContent = btn.dataset.idleLabel;
    btn.title = btn.dataset.idleTitle || "";
    delete btn.dataset.running;
  }

  // Sequential on purpose: a fleet can have ~100 projects, and firing every
  // write for one editor at once would be a hundred simultaneous rows
  // hitting that editor's selection queue -- easy to reorder (position is
  // insertion order), hard to reason about if one of them 404s midway.
  function runColumn(editor, machine, wanted, freeBytes, machineLabel, btn) {
    var who = machine ? (editor + " on " + machine) : editor;
    var boxes = columnBoxes(editor, machine).filter(function (b) { return b.checked !== wanted; });
    if (!boxes.length) return;
    if (!wanted) {
      // DUI-5 (2026-09-04): [ NONE ] fired straight into a loop of DELETEs
      // over a whole computer's plan with nothing asked, in a page where
      // unticking ONE project asks. confirmCapacity was only ever called on
      // the way in, so the destructive half of the pair was the unguarded
      // one.
      var what = boxes.length + " project" + (boxes.length === 1 ? "" : "s");
      if (!window.confirm(
            "Untick all " + what + " for " + who + "?\n\n"
            + "Their copies stay on disk. Nothing new comes down and proxy "
            + "sync stops for all of them.")) {
        return;
      }
    }
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
    var failed = [];
    var stoppedByAuth = false;
    if (btn) { btn.dataset.running = "1"; runProgress(btn, 0, boxes.length); }
    (function next() {
      if (stoppedByAuth) { runDone(btn); return; }
      // DUI-5: [ STOP ]. The button becomes its own stop control while the
      // run is going, and the flag is checked HERE rather than mid-write, so
      // a stop never leaves a request half made.
      var stopped = btn && btn.dataset.running !== "1";
      if (i >= boxes.length || stopped) {
        runDone(btn);
        if (failed.length) {
          // DUI-5: name them. "3 of 40 change(s) failed" left the admin with
          // no way to find out which three except by reading 40 checkboxes.
          toast((stopped ? "stopped after " + i + " of " + boxes.length + ". " : "")
                + failed.length + " of " + boxes.length + " change(s) failed: "
                + failed.slice(0, 6).join(", ")
                + (failed.length > 6 ? ", and " + (failed.length - 6) + " more" : ""),
                "err");
        } else if (stopped) {
          toast("stopped after " + i + " of " + boxes.length + " for " + who, "ok");
        } else {
          toast((wanted ? "ticked all for " : "unticked all for ") + who, "ok");
        }
        return;
      }
      var box = boxes[i++];
      runProgress(btn, i, boxes.length);
      box.checked = wanted;
      // A column tool only ever ADDS full ticks or REMOVES ticks: an
      // upload-only cell is already checked, so [ ALL ] skips it (the filter
      // above) and [ NONE ] unticks it like any other.
      if (!wanted) setUpmode(siblingBox(box, "matrix-upmode"), false);
      writeCell(box, wanted, "full").catch(function (err) {
        box.checked = !wanted;
        // DCORE-9: a signed-out column run stops HERE. Grinding through
        // another 39 writes that will all 401 leaves the grid half applied
        // and the admin looking at a pile of failures with one cause.
        if (signedOut(err)) { stoppedByAuth = true; return; }
        failed.push(box.dataset.projectLabel || box.dataset.slug);
      }).then(next);
    })();
  }

  grid.addEventListener("click", function (evt) {
    var allBtn = evt.target.closest && evt.target.closest("[data-col-all]");
    var noneBtn = evt.target.closest && evt.target.closest("[data-col-none]");
    var btn = allBtn || noneBtn;
    // A second click on a running column is the [ STOP ] (DUI-5): the loop
    // reads this flag before each write.
    if (btn && btn.dataset.running === "1") {
      btn.dataset.running = "0";
      return;
    }
    if (allBtn) {
      runColumn(allBtn.getAttribute("data-col-all"),
                allBtn.getAttribute("data-col-machine"), true,
                numberOr(allBtn.getAttribute("data-col-free"), null),
                allBtn.getAttribute("data-col-label"), allBtn);
    }
    if (noneBtn) {
      runColumn(noneBtn.getAttribute("data-col-none"),
                noneBtn.getAttribute("data-col-machine"), false,
                null, noneBtn.getAttribute("data-col-label"), noneBtn);
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
    // DCORE-2 (2026-09-04): this handler fires on `change` -- a stray scroll
    // over a focused select is enough -- and the route behind it DELETEs the
    // target's whole plan before inserting the source's rows. Nothing asked,
    // and the only feedback was "copied 8 project(s)", which never mentioned
    // the 14 that were removed. The two counts are already in the DOM (this
    // grid renders every column for this editor), so the question can name
    // both sides without a round trip.
    var sourceTicked = columnBoxes(editor, source).filter(function (b) { return b.checked; });
    var targetTicked = columnBoxes(editor, target).filter(function (b) { return b.checked; });
    var sourceSlugs = {};
    sourceTicked.forEach(function (b) { sourceSlugs[b.dataset.slug] = true; });
    var losing = targetTicked.filter(function (b) { return !sourceSlugs[b.dataset.slug]; });
    if (!sourceTicked.length) {
      // A source with an empty plan copies nothing and silently empties the
      // target. Refused here, and the route should refuse it too (DCORE-2
      // asks the JSON API for a 409).
      sel.value = "";
      toast(source + " has no projects ticked. Copying it would leave "
            + target + " with nothing.", "err");
      return;
    }
    if (!window.confirm(
          "Replace " + target + "'s " + targetTicked.length + " project(s) with "
          + source + "'s " + sourceTicked.length + "?\n\n"
          + (losing.length
             ? target + " stops syncing " + losing.length + " of them: "
               + losing.slice(0, 6).map(function (b) {
                   return b.dataset.projectLabel || b.dataset.slug;
                 }).join(", ")
               + (losing.length > 6 ? ", and " + (losing.length - 6) + " more" : "") + "."
             : "Nothing is removed from " + target + "."))) {
      sel.value = "";
      return;
    }
    sel.disabled = true;
    fetch("/api/v1/admin/machines/" + encodeURIComponent(editor) + "/" +
          encodeURIComponent(target) + "/copy-plan?source=" + encodeURIComponent(source), {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRF-Token": CSRF },
    }).then(function (resp) {
      if (!resp.ok) {
        return resp.json().catch(function () { return {}; }).then(function (body) {
          throw httpError(resp, body);
        });
      }
      return resp.json();
    }).then(function (body) {
      // The reload is deliberate (the whole column changes), which is also
      // why this toast has never been read by anybody: DUI-5. The count that
      // matters is on the confirm above, before the write.
      toast("copied " + body.projects + " project(s) from " + source + " to " + target, "ok");
      window.location.reload();
    }).catch(function (err) {
      sel.disabled = false;
      sel.value = "";
      if (signedOut(err)) return;
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
