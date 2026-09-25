"use strict";

/* ==========================================================================
   Client folders: curate clips for a prospective licensee, hand them a link.
   docs/CLIENT_FOLDERS.md (2026-08-18).

   A third CLASSIC script beside app.js and ingest.js. It shares their global
   scope, so every top-level name here is prefixed `cf` / `CF_` (the pattern
   ingest.js set with `ing`/`ingest*`): a duplicate declaration is a
   SyntaxError that blanks the whole page. tests/test_client_folders_ui.py
   pins that, and the document-relative URL rule (every fetch below is
   `api/client-folders...`, never `/api/...`).

   Two ways in:
     * the panel (header button): list folders, open one, edit title /
       description / contact / expiry, reorder and caption its clips, copy or
       revoke or rotate its link, see how often it was opened;
     * the "+" on every result card and the "+ client folder" button in the
       detail view, which open a small popover: tick the folders this clip
       should be in, or make a new one on the spot.

   The panel is a right-hand drawer like #ingest-panel and #settings-panel; it
   closes them when it opens so two drawers never stack.
   ========================================================================== */

const cf = {
  open: false,
  folders: [],
  publicBase: "",
  isAdmin: false,
  user: "",
  current: null, // the folder open in the detail view: {id, ..., items}
  popoverVideo: null, // the video the popover is about
  popoverAnchor: null,
};

/* ---------------------------------------------------------------------- */
/* Small helpers                                                           */
/* ---------------------------------------------------------------------- */

/** The link a client gets for `folder`: the public base (if the admin set
 * one) with the viewer path resolved against THIS page's own location, so the
 * mount prefix (`/broll/`) is whatever it really is and never spelled here.
 * With no base, the dashboard's own origin -- which reaches only inside the
 * tailnet, and the panel says so. */
/* bug-broll-1 (2026-09-25): the panel's own rows are named by their LEDGER
   row id. `item.video_id` is the id the clip was STORED under, which after a
   renumbering index rebuild can be another clip's current id, and the server
   used to act on both: one click removed two clips from a live client link. */
function cfItemQuery(item) {
  return item && item.item_id != null ? `?item_id=${encodeURIComponent(item.item_id)}` : "";
}

function cfShareUrl(folder) {
  const rel = `share/${folder.token}/`;
  const local = new URL(rel, document.baseURI);
  if (!cf.publicBase) return local.href;
  const pub = new URL(cf.publicBase);
  local.protocol = pub.protocol;
  local.host = pub.host;
  return local.href;
}

function cfFmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function cfStatusChip(folder) {
  const chip = el("span", { className: `cf-chip cf-chip-${folder.status}`, text: folder.status });
  if (folder.status === "live" && folder.expires_at) {
    chip.title = `expires ${cfFmtDate(folder.expires_at)}`;
  } else if (folder.status === "revoked") {
    chip.title = `revoked ${cfFmtDate(folder.revoked_at)}`;
  } else if (folder.status === "expired") {
    chip.title = `expired ${cfFmtDate(folder.expires_at)}`;
  }
  return chip;
}

async function cfCopy(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Link copied", "success");
  } catch (e) {
    // Clipboard needs a secure context (https or localhost); over plain http
    // on a tailnet IP it throws. Fall back to selecting the field so a Ctrl+C
    // still works.
    const field = $("#cf-link-field");
    if (field) { field.focus(); field.select(); }
    toast("Copy failed: select the link and press Ctrl+C", "warn");
  }
}

/* ---------------------------------------------------------------------- */
/* Loading                                                                 */
/* ---------------------------------------------------------------------- */

async function cfLoadFolders(videoId) {
  const url = videoId != null ? `api/client-folders?video_id=${videoId}` : "api/client-folders";
  const data = await fetchJson(url);
  cf.folders = data.folders || [];
  cf.publicBase = data.public_base_url || "";
  cf.isAdmin = !!data.is_admin;
  cf.user = data.user || "";
  return data;
}

/* ---------------------------------------------------------------------- */
/* The panel                                                               */
/* ---------------------------------------------------------------------- */

function cfWirePanel() {
  const btn = $("#cf-btn");
  if (!btn) return;
  btn.addEventListener("click", () => (cf.open ? cfClose() : cfOpen()));
  $("#cf-close").addEventListener("click", cfClose);
  $("#cf-new").addEventListener("click", () => cfCreateFlow());
  $("#cf-refresh").addEventListener("click", () => cfRenderList());
  $("#cf-base-save").addEventListener("click", cfSaveBase);
  const detailBtn = $("#cf-add-detail-btn");
  if (detailBtn) {
    detailBtn.addEventListener("click", (e) => {
      const video = state.detail && state.detail.video;
      if (!video) return;
      cfOpenPopover(video, e.currentTarget);
    });
  }
  // Popover dismissal: any click outside it, or Escape.
  document.addEventListener("click", (e) => {
    const pop = $("#cf-popover");
    if (pop.classList.contains("hidden")) return;
    if (pop.contains(e.target) || (cf.popoverAnchor && cf.popoverAnchor.contains(e.target))) return;
    cfClosePopover();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("#cf-popover").classList.contains("hidden")) {
      cfClosePopover();
      e.stopPropagation();
    }
  }, true);
}

async function cfOpen() {
  cf.open = true;
  // One drawer at a time (the ingest and settings panels share this edge).
  if (typeof ingestClose === "function" && typeof ing !== "undefined" && ing.open) ingestClose();
  if (typeof closeSettings === "function") closeSettings();
  $("#cf-panel").classList.remove("hidden");
  cfShowList();
  await cfRenderList();
}

function cfClose() {
  cf.open = false;
  $("#cf-panel").classList.add("hidden");
}

function cfShowList() {
  cf.current = null;
  $("#cf-detail-view").classList.add("hidden");
  $("#cf-list-view").classList.remove("hidden");
}

async function cfRenderList() {
  const list = $("#cf-list");
  list.innerHTML = "";
  list.appendChild(el("div", { className: "muted small", text: "loading…" }));
  try {
    await cfLoadFolders();
  } catch (e) {
    list.innerHTML = "";
    list.appendChild(el("div", { className: "cf-error", text: `Could not load client folders: ${e.message}` }));
    return;
  }
  list.innerHTML = "";
  $("#cf-admin").classList.toggle("hidden", !cf.isAdmin);
  $("#cf-base-input").value = cf.publicBase;
  if (!cf.publicBase) {
    const warn = el("div", { className: "cf-notice" });
    warn.appendChild(el("span", {
      text: cf.isAdmin
        ? "No public link base is set: links only work for people on the tailnet. Set it below once Funnel is on."
        : "No public link base is set: links only work for people on the tailnet. Ask an admin (docs/CLIENT_FOLDERS.md).",
    }));
    list.appendChild(warn);
  }
  if (!cf.folders.length) {
    list.appendChild(el("div", { className: "muted small", text: "No client folders yet. Make one, then add clips from the + on any thumbnail." }));
    return;
  }
  for (const folder of cf.folders) {
    const row = el("div", { className: "cf-row" });
    const head = el("div", { className: "cf-row-head" });
    head.appendChild(el("span", { className: "cf-row-title", text: folder.title }));
    head.appendChild(cfStatusChip(folder));
    row.appendChild(head);
    const meta = el("div", { className: "cf-row-meta muted small" });
    const bits = [
      `${folder.n_items} clip${folder.n_items === 1 ? "" : "s"}`,
      `by ${folder.created_by}`,
      folder.view_count ? `opened ${folder.view_count}x` : "never opened",
    ];
    meta.textContent = bits.join(" · ");
    row.appendChild(meta);
    row.addEventListener("click", () => cfOpenFolder(folder.id));
    list.appendChild(row);
  }
}

async function cfCreateFlow(afterCreate) {
  const title = window.prompt("Name for the new client folder (the client sees this):");
  if (title == null) return null;
  if (!title.trim()) { toast("A folder needs a title", "warn"); return null; }
  let folder;
  try {
    folder = await fetchJson("api/client-folders", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: title.trim() }),
    });
  } catch (e) {
    toast(`Could not create the folder: ${e.message}`, "error");
    return null;
  }
  toast(`Created "${folder.title}"`, "success");
  if (afterCreate) return afterCreate(folder);
  if (cf.open) await cfOpenFolder(folder.id);
  return folder;
}

async function cfSaveBase() {
  const value = $("#cf-base-input").value.trim();
  try {
    const data = await fetchJson("api/client-folders/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ public_base_url: value }),
    });
    cf.publicBase = data.public_base_url || "";
    toast(cf.publicBase ? `Public link base set to ${cf.publicBase}` : "Public link base cleared", "success");
    await cfRenderList();
  } catch (e) {
    toast(`Not saved: ${e.message}`, "error");
  }
}

/* ---------------------------------------------------------------------- */
/* One folder                                                              */
/* ---------------------------------------------------------------------- */

async function cfOpenFolder(folderId) {
  let folder;
  try {
    folder = await fetchJson(`api/client-folders/${folderId}`);
  } catch (e) {
    toast(`Could not open the folder: ${e.message}`, "error");
    return;
  }
  cf.current = folder;
  $("#cf-list-view").classList.add("hidden");
  const view = $("#cf-detail-view");
  view.classList.remove("hidden");
  cfRenderFolder();
}

function cfRenderFolder() {
  const folder = cf.current;
  const view = $("#cf-detail-view");
  view.innerHTML = "";

  const back = el("button", { className: "text-btn", text: "← all folders", attrs: { type: "button" } });
  back.addEventListener("click", () => { cfShowList(); cfRenderList(); });
  view.appendChild(back);

  const head = el("div", { className: "cf-detail-head" });
  head.appendChild(el("h3", { className: "cf-detail-title", text: folder.title }));
  head.appendChild(cfStatusChip(folder));
  view.appendChild(head);

  // --- the link ---------------------------------------------------------
  const linkBox = el("div", { className: "cf-linkbox" });
  linkBox.appendChild(el("div", { className: "cf-field-label", text: "Client link" }));
  const linkRow = el("div", { className: "cf-link-row" });
  const field = el("input", { attrs: { type: "text", id: "cf-link-field", readonly: "readonly", spellcheck: "false" } });
  field.value = cfShareUrl(folder);
  linkRow.appendChild(field);
  const copyBtn = el("button", { className: "primary-btn", text: "Copy", attrs: { type: "button" } });
  copyBtn.addEventListener("click", () => cfCopy(field.value));
  linkRow.appendChild(copyBtn);
  // logic-broll-music-4 (2026-09-25): `?preview=1` so the curator checking
  // their own link is not counted as the client opening it. Only on this
  // button: the field above, and so the copied link, stays clean.
  const openBtn = el("a", { className: "text-btn cf-open-link", text: "open", attrs: { href: `${field.value}?preview=1`, target: "_blank", rel: "noopener" } });
  linkRow.appendChild(openBtn);
  linkBox.appendChild(linkRow);
  const linkNote = el("div", { className: "muted small" });
  if (folder.status !== "live") {
    linkNote.textContent = folder.status === "revoked"
      ? "This link is revoked: anyone opening it sees \"not available\". Reactivate or rotate to hand out a working one."
      : "This link has expired. Change the expiry (or clear it) to bring it back.";
  } else if (!cf.publicBase) {
    linkNote.textContent = "Reachable inside the tailnet only until an admin sets the public link base.";
  } else {
    linkNote.textContent = folder.view_count
      ? `Opened ${folder.view_count} time${folder.view_count === 1 ? "" : "s"}, last ${cfFmtDate(folder.last_viewed_at)}.`
      : "Not opened yet.";
  }
  linkBox.appendChild(linkNote);
  const linkActions = el("div", { className: "cf-actions" });
  if (folder.status === "revoked") {
    linkActions.appendChild(cfActionBtn("Reactivate link", () => cfFolderAction("reactivate")));
  } else {
    linkActions.appendChild(cfActionBtn("Revoke link", () => {
      if (window.confirm("Revoke this link? Anyone who has it will see \"not available\" until you reactivate it.")) {
        cfFolderAction("revoke");
      }
    }));
  }
  linkActions.appendChild(cfActionBtn("New link", () => {
    if (window.confirm("Issue a new link? The old one stops working immediately.")) {
      cfFolderAction("rotate");
    }
  }));
  linkBox.appendChild(linkActions);
  view.appendChild(linkBox);

  // --- details form -----------------------------------------------------
  const form = el("div", { className: "cf-form" });
  form.appendChild(cfField("Title", "cf-f-title", "input", folder.title));
  form.appendChild(cfField("Description (shown to the client)", "cf-f-desc", "textarea", folder.description || ""));
  form.appendChild(cfField("Contact for licensing (email or a line of text)", "cf-f-contact", "input", folder.contact || ""));
  const expWrap = el("label", { className: "cf-field" });
  expWrap.appendChild(el("span", { className: "cf-field-label", text: "Link expires" }));
  const expSel = el("select", { attrs: { id: "cf-f-expires" } });
  // "keep" leaves the expiry as it is (which, with none set, IS never).
  const expOptions = folder.expires_at
    ? [["keep", `keep (${cfFmtDate(folder.expires_at)})`], ["never", "never"]]
    : [["keep", "never"]];
  expOptions.push(["7", "in 7 days"], ["30", "in 30 days"], ["90", "in 90 days"]);
  for (const [value, label] of expOptions) {
    const opt = el("option", { text: label, attrs: { value } });
    expSel.appendChild(opt);
  }
  expWrap.appendChild(expSel);
  form.appendChild(expWrap);
  const saveRow = el("div", { className: "cf-actions" });
  const saveBtn = el("button", { className: "primary-btn", text: "Save details", attrs: { type: "button" } });
  saveBtn.addEventListener("click", cfSaveDetails);
  saveRow.appendChild(saveBtn);
  form.appendChild(saveRow);
  view.appendChild(form);

  // --- clips ------------------------------------------------------------
  const clipsHead = el("h3", { text: `Clips (${folder.items.length})` });
  view.appendChild(clipsHead);
  if (!folder.items.length) {
    view.appendChild(el("div", { className: "muted small", text: "Empty. Hover any thumbnail in the grid and press its + to add it here." }));
  }
  const list = el("div", { className: "cf-items" });
  folder.items.forEach((item, idx) => list.appendChild(cfItemRow(item, idx, folder.items.length)));
  view.appendChild(list);

  // --- danger -----------------------------------------------------------
  const danger = el("div", { className: "cf-actions cf-danger" });
  danger.appendChild(cfActionBtn("Delete folder", async () => {
    if (!window.confirm(`Delete "${folder.title}" and its link? This cannot be undone.`)) return;
    try {
      await fetchJson(`api/client-folders/${folder.id}`, { method: "DELETE" });
      toast("Folder deleted", "success");
      cfShowList();
      cfRenderList();
    } catch (e) {
      toast(`Not deleted: ${e.message}`, "error");
    }
  }));
  view.appendChild(danger);
}

function cfActionBtn(label, onClick) {
  const b = el("button", { className: "text-btn", text: label, attrs: { type: "button" } });
  b.addEventListener("click", onClick);
  return b;
}

function cfField(label, id, tag, value) {
  const wrap = el("label", { className: "cf-field" });
  wrap.appendChild(el("span", { className: "cf-field-label", text: label }));
  const input = el(tag, { attrs: tag === "input" ? { type: "text", id } : { id, rows: "3" } });
  input.value = value;
  wrap.appendChild(input);
  return wrap;
}

function cfItemRow(item, idx, total) {
  const row = el("div", { className: `cf-item${item.missing ? " cf-item-missing" : ""}` });
  const thumb = el("div", { className: "cf-item-thumb" });
  if (!item.missing) {
    const img = el("img", { attrs: { alt: "" } });
    img.src = `media/poster/${item.id}.jpg`;
    img.loading = "lazy";
    img.addEventListener("error", () => img.remove());
    thumb.appendChild(img);
    thumb.title = "open in the archive";
    thumb.addEventListener("click", () => openDetail(item.id, null, []));
  }
  row.appendChild(thumb);

  const body = el("div", { className: "cf-item-body" });
  // ui-broll-web-12 review (2026-09-25): the line is a flex row and only the
  // name itself is ellipsized. With the ellipsis on the whole line, a camera
  // name of ~30 characters pushed the duration and the "saved" mark past the
  // clip edge, so a save that worked still showed nothing.
  const name = el("div", { className: "cf-item-name" });
  name.appendChild(el("span", { className: "cf-item-name-text", text: item.missing
    ? `${basename(item.rel_path)} (no longer in the archive index)`
    : item.name }));
  if (!item.missing && item.duration_s != null) {
    name.appendChild(el("span", { className: "muted cf-item-dur", text: ` · ${formatDuration(item.duration_s)}` }));
  }
  body.appendChild(name);
  if (!item.missing) {
    const note = el("input", { attrs: { type: "text", placeholder: "caption the client sees (optional)", maxlength: "500" } });
    note.value = item.note || "";
    const saved = el("span", { className: "small cf-note-saved", text: "" });
    // ui-broll-web-12 (2026-09-25): the model is updated BEFORE the PUT is
    // awaited. Pressing a move arrow straight after typing blurs the field
    // (change fires, the PUT starts) and the click then redraws every row from
    // cf.current.items at once; with the assignment after the await, the
    // redrawn field showed the OLD caption while the server held the new one.
    // The redraw may also have replaced this row, so the "saved" mark and a
    // failure's revert go to whichever field shows this item NOW.
    cfNoteFields.set(item, { note, saved });
    note.addEventListener("change", async () => {
      const folderId = cf.current.id;
      const previous = item.note || "";
      const wanted = note.value;
      item.note = wanted;
      try {
        await fetchJson(`api/client-folders/${folderId}/items/${item.video_id}/note${cfItemQuery(item)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ note: wanted }),
        });
        const shown = cfNoteFields.get(item);
        if (shown && item.note === wanted) cfFlashSaved(shown.saved);
      } catch (e) {
        // Back to what the server holds, unless a later edit has already
        // replaced it. The field keeps the typed words so they are not lost;
        // editing it again is the retry.
        if (item.note === wanted) item.note = previous;
        toast(`Caption not saved: ${e.message}`, "error");
      }
    });
    body.appendChild(note);
    name.appendChild(saved);
  }
  row.appendChild(body);

  const ctl = el("div", { className: "cf-item-ctl" });
  const up = el("button", { className: "text-btn", text: "▲", attrs: { type: "button", title: "move up" } });
  up.disabled = idx === 0;
  up.addEventListener("click", () => cfMove(idx, -1));
  const down = el("button", { className: "text-btn", text: "▼", attrs: { type: "button", title: "move down" } });
  down.disabled = idx === total - 1;
  down.addEventListener("click", () => cfMove(idx, +1));
  const rm = el("button", { className: "text-btn cf-remove", text: "✕", attrs: { type: "button", title: "remove from this folder" } });
  rm.addEventListener("click", async () => {
    try {
      await fetchJson(`api/client-folders/${cf.current.id}/items/${item.video_id}${cfItemQuery(item)}`, { method: "DELETE" });
      cf.current.items.splice(idx, 1);
      cfRenderFolder();
    } catch (e) {
      toast(`Not removed: ${e.message}`, "error");
    }
  });
  ctl.append(up, down, rm);
  row.appendChild(ctl);
  return row;
}

// ui-broll-web-12 (2026-09-25): item -> the caption field and "saved" mark that
// currently draw it. A WeakMap so a redraw simply replaces the entry and a
// dropped folder's items take theirs with them.
const cfNoteFields = new WeakMap();

function cfFlashSaved(mark) {
  if (!mark) return;
  mark.textContent = "saved";
  clearTimeout(mark._cfTimer);
  mark._cfTimer = setTimeout(() => { mark.textContent = ""; }, 1800);
}

async function cfMove(idx, delta) {
  const items = cf.current.items;
  const j = idx + delta;
  if (j < 0 || j >= items.length) return;
  [items[idx], items[j]] = [items[j], items[idx]];
  cfRenderFolder();
  try {
    await fetchJson(`api/client-folders/${cf.current.id}/order`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video_ids: items.map((i) => i.video_id) }),
    });
  } catch (e) {
    toast(`Order not saved: ${e.message}`, "error");
  }
}

async function cfSaveDetails() {
  const folder = cf.current;
  const body = {
    title: $("#cf-f-title").value,
    description: $("#cf-f-desc").value,
    contact: $("#cf-f-contact").value,
  };
  const exp = $("#cf-f-expires").value;
  if (exp === "never") body.expires_at = null;
  else if (exp !== "keep") {
    const d = new Date(Date.now() + parseInt(exp, 10) * 86400 * 1000);
    body.expires_at = d.toISOString();
  }
  try {
    const updated = await fetchJson(`api/client-folders/${folder.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    Object.assign(cf.current, updated);
    toast("Saved", "success");
    cfRenderFolder();
  } catch (e) {
    toast(`Not saved: ${e.message}`, "error");
  }
}

async function cfFolderAction(action) {
  try {
    const updated = await fetchJson(`api/client-folders/${cf.current.id}/${action}`, { method: "POST" });
    Object.assign(cf.current, updated);
    cfRenderFolder();
    toast(action === "revoke" ? "Link revoked" : action === "rotate" ? "New link issued" : "Link reactivated", "success");
  } catch (e) {
    toast(`Failed: ${e.message}`, "error");
  }
}

/* ---------------------------------------------------------------------- */
/* Cards: the "+" and its popover                                          */
/* ---------------------------------------------------------------------- */

/** Called by app.js's buildCard for every result card. */
function cfDecorateCard(card, video) {
  const btn = el("button", {
    className: "cf-card-add",
    text: "+",
    attrs: { type: "button", title: "Add to a client folder" },
  });
  btn.addEventListener("click", (e) => {
    // The card's own click opens the detail view; this one must not.
    e.stopPropagation();
    e.preventDefault();
    cfOpenPopover(video, btn);
  });
  card.appendChild(btn);
}

async function cfOpenPopover(video, anchor) {
  const pop = $("#cf-popover");
  cf.popoverVideo = video;
  cf.popoverAnchor = anchor;
  pop.innerHTML = "";
  pop.appendChild(el("div", { className: "cf-pop-head", text: "Add to client folder" }));
  pop.appendChild(el("div", { className: "muted small", text: "loading…" }));
  pop.classList.remove("hidden");
  cfPlacePopover(anchor);
  try {
    await cfLoadFolders(video.id);
  } catch (e) {
    pop.innerHTML = "";
    pop.appendChild(el("div", { className: "cf-error", text: e.status === 401 ? "Sign in to use client folders" : `Could not load: ${e.message}` }));
    return;
  }
  cfRenderPopover();
}

function cfRenderPopover() {
  const pop = $("#cf-popover");
  const video = cf.popoverVideo;
  pop.innerHTML = "";
  pop.appendChild(el("div", { className: "cf-pop-head", text: "Add to client folder" }));
  if (!cf.folders.length) {
    pop.appendChild(el("div", { className: "muted small", text: "No folders yet." }));
  }
  for (const folder of cf.folders) {
    const row = el("label", { className: "cf-pop-row" });
    const box = el("input", { attrs: { type: "checkbox" } });
    box.checked = !!folder.contains;
    // ui-broll-web-11 (2026-09-25): the count beside the title is redrawn on
    // a toggle; it used to keep the number from when the popover opened.
    const count = el("span", { className: "muted small cf-pop-count", text: `${folder.n_items}` });
    box.addEventListener("change", async () => {
      box.disabled = true;
      try {
        if (box.checked) {
          await fetchJson(`api/client-folders/${folder.id}/items`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ video_ids: [video.id] }),
          });
          folder.contains = true;
          folder.n_items += 1;
          toast(`Added to "${folder.title}"`, "success");
        } else {
          await fetchJson(`api/client-folders/${folder.id}/items/${video.id}`, { method: "DELETE" });
          folder.contains = false;
          folder.n_items = Math.max(0, folder.n_items - 1);
          toast(`Removed from "${folder.title}"`);
        }
        count.textContent = `${folder.n_items}`;
        // Keep an open panel honest.
        if (cf.current && cf.current.id === folder.id) cfOpenFolder(folder.id);
      } catch (e) {
        box.checked = !box.checked;
        toast(`Failed: ${e.message}`, "error");
      } finally {
        box.disabled = false;
      }
    });
    row.appendChild(box);
    row.appendChild(el("span", { className: "cf-pop-title", text: folder.title }));
    row.appendChild(count);
    pop.appendChild(row);
  }
  const newBtn = el("button", { className: "text-btn cf-pop-new", text: "+ new folder…", attrs: { type: "button" } });
  newBtn.addEventListener("click", async () => {
    await cfCreateFlow(async (folder) => {
      // ui-broll-web-5 (2026-09-25): the folder exists by now, so a failed add
      // must say so. Unguarded, it was an unhandled rejection after a green
      // "Created" toast, the popover was never redrawn to show the new
      // folder, and the editor sent a client link to an empty folder.
      try {
        await fetchJson(`api/client-folders/${folder.id}/items`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ video_ids: [video.id] }),
        });
        toast(`Added to "${folder.title}"`, "success");
      } catch (e) {
        toast(`Folder "${folder.title}" was created, but the clip was not added: ${e.message}`, "error");
      }
      // The popover may have been closed or moved to another clip meanwhile.
      if (cf.popoverVideo !== video) return folder;
      try {
        await cfLoadFolders(video.id);
      } catch (e) {
        /* the list below is the one the popover already had */
      }
      if (cf.popoverVideo === video) cfRenderPopover();
      return folder;
    });
  });
  pop.appendChild(newBtn);
  const manage = el("button", { className: "text-btn", text: "manage folders", attrs: { type: "button" } });
  manage.addEventListener("click", () => { cfClosePopover(); cfOpen(); });
  pop.appendChild(manage);
  // The list is taller now than the "loading" placeholder it was placed as.
  if (cf.popoverAnchor) cfPlacePopover(cf.popoverAnchor);
}

/* ui-broll-web-11 (2026-09-25): placed under the anchor with no vertical
 * clamp, a fixed popover under a card near the bottom of the window (or the
 * detail view's "+ client folder" under the player) ran off the screen where
 * nothing could scroll to it. It now goes on whichever side of the anchor has
 * room, or more room, and scrolls inside the room it got. */
function cfPlacePopover(anchor) {
  const pop = $("#cf-popover");
  const r = anchor.getBoundingClientRect();
  const width = 260;
  const margin = 8;
  let left = r.left;
  if (left + width > window.innerWidth - margin) left = window.innerWidth - width - margin;
  pop.style.left = `${Math.max(margin, left)}px`;
  const below = window.innerHeight - r.bottom - 4 - margin;
  const above = r.top - 4 - margin;
  pop.style.maxHeight = "none";
  const height = pop.scrollHeight;
  if (height <= below || below >= above) {
    pop.style.top = `${r.bottom + 4}px`;
    pop.style.maxHeight = `${Math.max(80, below)}px`;
  } else {
    const shown = Math.min(height, above);
    pop.style.top = `${Math.max(margin, r.top - 4 - shown)}px`;
    pop.style.maxHeight = `${Math.max(80, above)}px`;
  }
}

function cfClosePopover() {
  $("#cf-popover").classList.add("hidden");
  cf.popoverVideo = null;
  cf.popoverAnchor = null;
}

document.addEventListener("DOMContentLoaded", cfWirePanel);
