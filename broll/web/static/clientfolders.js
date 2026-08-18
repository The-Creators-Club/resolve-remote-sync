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
  const openBtn = el("a", { className: "text-btn cf-open-link", text: "open", attrs: { href: field.value, target: "_blank", rel: "noopener" } });
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
  const name = el("div", { className: "cf-item-name" });
  name.textContent = item.missing
    ? `${basename(item.rel_path)} (no longer in the archive index)`
    : item.name;
  if (!item.missing && item.duration_s != null) {
    name.appendChild(el("span", { className: "muted", text: ` · ${formatDuration(item.duration_s)}` }));
  }
  body.appendChild(name);
  if (!item.missing) {
    const note = el("input", { attrs: { type: "text", placeholder: "caption the client sees (optional)", maxlength: "500" } });
    note.value = item.note || "";
    note.addEventListener("change", async () => {
      try {
        await fetchJson(`api/client-folders/${cf.current.id}/items/${item.video_id}/note`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ note: note.value }),
        });
        item.note = note.value;
      } catch (e) {
        toast(`Caption not saved: ${e.message}`, "error");
      }
    });
    body.appendChild(note);
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
      await fetchJson(`api/client-folders/${cf.current.id}/items/${item.video_id}`, { method: "DELETE" });
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
    row.appendChild(el("span", { className: "muted small", text: `${folder.n_items}` }));
    pop.appendChild(row);
  }
  const newBtn = el("button", { className: "text-btn cf-pop-new", text: "+ new folder…", attrs: { type: "button" } });
  newBtn.addEventListener("click", async () => {
    await cfCreateFlow(async (folder) => {
      await fetchJson(`api/client-folders/${folder.id}/items`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ video_ids: [video.id] }),
      });
      toast(`Added to "${folder.title}"`, "success");
      await cfLoadFolders(video.id);
      cfRenderPopover();
    });
  });
  pop.appendChild(newBtn);
  const manage = el("button", { className: "text-btn", text: "manage folders", attrs: { type: "button" } });
  manage.addEventListener("click", () => { cfClosePopover(); cfOpen(); });
  pop.appendChild(manage);
}

function cfPlacePopover(anchor) {
  const pop = $("#cf-popover");
  const r = anchor.getBoundingClientRect();
  const width = 260;
  let left = r.left;
  if (left + width > window.innerWidth - 8) left = window.innerWidth - width - 8;
  pop.style.left = `${Math.max(8, left)}px`;
  pop.style.top = `${r.bottom + 4}px`;
}

function cfClosePopover() {
  $("#cf-popover").classList.add("hidden");
  cf.popoverVideo = null;
  cf.popoverAnchor = null;
}

document.addEventListener("DOMContentLoaded", cfWirePanel);
