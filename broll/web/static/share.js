"use strict";

/* ==========================================================================
   The client folder viewer (share.html): what a prospective licensee sees.
   docs/CLIENT_FOLDERS.md, 2026-08-18.

   Deliberately NOT app.js: that file is 1,700 lines of editor's tooling
   (search modes, the folder tree, in/out points, J/K/L, Send to Resolve, the
   companion loopback) and every one of those would be a thing to hide, and to
   keep hidden, on a page for someone who has no account and no companion. So
   this is the browse-and-preview quarter of it, written for one folder: a
   grid of hover-scrub thumbnails, a preview player, and what is in each clip.
   The sprite arithmetic is shared through sprite.js -- one copy, on purpose.

   Every URL is document-relative (`api/folder`, `media/poster/12.jpg`): the
   page lives at .../share/<token>/ and everything it needs lives under that
   same prefix. tests/test_mounted_prefix.py pins it, and it is what lets a
   Funnel publish only that prefix.
   ========================================================================== */

const share = {
  folder: null,
  items: [],
  byId: new Map(),
  currentIdx: -1,
  gridScrollY: 0,
};

/* ---------------------------------------------------------------------- */
/* Helpers (their own copies: app.js is not loaded here)                  */
/* ---------------------------------------------------------------------- */

function $(sel) {
  return document.querySelector(sel);
}

function el(tag, opts) {
  const node = document.createElement(tag);
  if (opts) {
    if (opts.className) node.className = opts.className;
    if (opts.text !== undefined) node.textContent = opts.text;
    if (opts.attrs) {
      for (const [k, v] of Object.entries(opts.attrs)) node.setAttribute(k, v);
    }
  }
  return node;
}

function formatDuration(seconds) {
  if (seconds == null) return "--:--";
  const s = Math.round(seconds);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, "0")}`;
}

function toast(message, kind) {
  const container = $("#toast-container");
  const node = el("div", { className: `toast${kind ? " " + kind : ""}`, text: message });
  container.appendChild(node);
  setTimeout(() => node.remove(), 5000);
}

async function fetchJson(url) {
  const res = await fetch(url);
  let body = null;
  try {
    body = await res.json();
  } catch (e) {
    body = null;
  }
  if (!res.ok) {
    const err = new Error((body && body.detail) || `HTTP ${res.status}`);
    err.status = res.status;
    throw err;
  }
  return body;
}

/** "1920x1080, 25 fps, 0:42, shot 2026-05-03" -- what a buyer wants to know. */
function describeVideo(v) {
  const bits = [];
  if (v.width && v.height) bits.push(`${v.width}x${v.height}`);
  if (v.fps) bits.push(`${Math.round(v.fps * 100) / 100} fps`);
  if (v.duration_s != null) bits.push(formatDuration(v.duration_s));
  if (v.shot_date) bits.push(`shot ${v.shot_date}`);
  return bits.join(" · ");
}

/* UX-19 (resilience sweep 2026-08-28): the two sentences a client gets when
 * the folder changed under them. Membership is checked per request, so a clip
 * the editor removed while this page was open 404s on its next fetch and the
 * browser's own broken-video box was all there was to see. Kept as constants
 * because the same two are reachable from three places (the poster, the
 * player, the detail fetch). */
const CLIP_GONE_TEXT = "This clip is no longer in this folder. Refresh the page to see what is.";
const CLIP_UNPLAYABLE_TEXT = "This clip could not be played just now. Refresh the page to see what is in this folder.";

/** Show (or clear, with "") the message under the player. */
function shareClipGone(text) {
  const box = $("#share-clip-gone");
  if (!box) return;
  box.textContent = text || "";
  box.classList.toggle("hidden", !text);
}

/** The <video> element reports "it broke" and never why -- no status, no body.
 * Ask the API about the same clip: a 404 there is the removal, anything else
 * is a network or codec problem, and the two must not read as one thing. */
async function shareExplainPlaybackFailure(videoId) {
  try {
    await fetchJson(`api/videos/${videoId}`);
  } catch (e) {
    if (e && e.status === 404) {
      shareClipGone(CLIP_GONE_TEXT);
      return;
    }
  }
  shareClipGone(CLIP_UNPLAYABLE_TEXT);
}

function contactNode(contact) {
  const text = (contact || "").trim();
  if (!text) return null;
  const wrap = el("span");
  wrap.append("To licence any of this footage, contact ");
  // A bare email address becomes a mailto with the folder named in the
  // subject; anything else (a phone number, "ask for Alex") is shown as typed.
  if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(text)) {
    const subject = encodeURIComponent(`Licence enquiry: ${share.folder.title}`);
    const a = el("a", { text, attrs: { href: `mailto:${text}?subject=${subject}` } });
    wrap.appendChild(a);
  } else {
    wrap.append(text);
  }
  wrap.append(".");
  return wrap;
}

/* ---------------------------------------------------------------------- */
/* Init                                                                    */
/* ---------------------------------------------------------------------- */

document.addEventListener("DOMContentLoaded", shareInit);

async function shareInit() {
  $("#share-back").addEventListener("click", shareBack);
  // UX-19: one listener for the page's lifetime, reading the clip that is
  // open right now -- the player element is reused for every clip.
  $("#share-player").addEventListener("error", () => {
    const video = share.items[share.currentIdx];
    if (video) shareExplainPlaybackFailure(video.id);
  });
  $("#share-prev").addEventListener("click", () => shareStep(-1));
  $("#share-next").addEventListener("click", () => shareStep(+1));
  window.addEventListener("popstate", shareApplyHash);
  document.addEventListener("keydown", shareKeydown);

  let data;
  try {
    data = await fetchJson("api/folder");
  } catch (e) {
    $("#share-title").textContent = "This link is not available";
    $("#share-desc").textContent = e.status === 404
      ? "The preview you were sent has been closed or has expired. Please ask whoever sent it for a fresh link."
      : `Could not load the folder (${e.message}). Please try again in a moment.`;
    return;
  }
  share.folder = data;
  share.items = data.items || [];
  share.byId = new Map(share.items.map((v, i) => [v.id, i]));

  document.title = `${data.title} - footage preview`;
  $("#share-org").textContent = (data.org || "Footage").toUpperCase();
  $("#share-footer-org").textContent = data.org || "";
  $("#share-title").textContent = data.title;
  $("#share-desc").textContent = data.description || "";
  $("#share-desc").classList.toggle("hidden", !data.description);
  const n = share.items.length;
  $("#share-count").textContent = `${n} clip${n === 1 ? "" : "s"}`;
  const contact = contactNode(data.contact);
  if (contact) {
    $("#share-contact").appendChild(contact);
    $("#share-contact").classList.remove("hidden");
    $("#share-footer-contact").appendChild(contactNode(data.contact));
  }
  if (data.expires_at) {
    const when = new Date(data.expires_at);
    if (!isNaN(when.getTime())) {
      $("#share-footer-org").textContent += `  ·  this preview is available until ${when.toLocaleDateString()}`;
    }
  }

  shareRenderGrid();
  shareApplyHash();
}

/* ---------------------------------------------------------------------- */
/* Grid                                                                    */
/* ---------------------------------------------------------------------- */

function shareRenderGrid() {
  const grid = $("#share-grid");
  grid.innerHTML = "";
  $("#share-empty").classList.toggle("hidden", share.items.length > 0);
  share.items.forEach((video, idx) => grid.appendChild(shareCard(video, idx)));
}

function shareCard(video, idx) {
  const card = el("div", { className: "card" });
  const thumb = el("div", { className: "card-thumb" });
  thumb.style.height = `${spriteGeometry(video).cellHeight}px`;

  const poster = el("img", { className: "poster", attrs: { alt: "" } });
  poster.src = `media/poster/${video.id}.jpg`;
  poster.loading = "lazy";
  poster.addEventListener("error", () => {
    poster.remove();
    thumb.classList.add("thumb-missing");
  });
  thumb.appendChild(poster);

  const overlay = el("div", { className: "sprite-overlay" });
  overlay.style.backgroundImage = `url(media/sprite/${video.id}.jpg)`;
  thumb.appendChild(overlay);

  if (video.duration_s != null) {
    thumb.appendChild(el("div", { className: "duration-badge", text: formatDuration(video.duration_s) }));
  }
  wireSpriteScrub(thumb, overlay, video);
  card.appendChild(thumb);

  const caption = el("div", { className: "share-caption" });
  caption.appendChild(el("span", { className: "share-caption-name", text: video.name }));
  if (video.note) {
    caption.append(" - ");
    caption.append(video.note);
  }
  card.appendChild(caption);
  card.title = video.note ? `${video.name}: ${video.note}` : video.name;
  card.addEventListener("click", () => shareOpen(idx, "push"));
  return card;
}

/* ---------------------------------------------------------------------- */
/* Detail                                                                  */
/* ---------------------------------------------------------------------- */

function shareApplyHash() {
  const m = /^#v=(\d+)$/.exec(location.hash);
  if (m && share.byId.has(Number(m[1]))) {
    shareOpen(share.byId.get(Number(m[1])), false);
  } else {
    shareClose(false);
  }
}

/** `nav`: "push" from the grid (Back returns to the grid), "replace" when
 * stepping prev/next inside the detail (Back STILL returns to the grid, not
 * to the previous clip), false when applying the URL that is already there. */
async function shareOpen(idx, nav) {
  const video = share.items[idx];
  if (!video) return;
  if (share.currentIdx < 0) share.gridScrollY = window.scrollY;
  share.currentIdx = idx;
  if (nav === "push") history.pushState({ share: true }, "", `#v=${video.id}`);
  else if (nav === "replace") history.replaceState({ share: true }, "", `#v=${video.id}`);

  $("#share-grid-view").classList.add("hidden");
  $("#share-detail").classList.remove("hidden");
  window.scrollTo(0, 0);
  $("#share-pos").textContent = `${idx + 1} / ${share.items.length}`;
  $("#share-prev").disabled = idx === 0;
  $("#share-next").disabled = idx === share.items.length - 1;

  const player = $("#share-player");
  shareClipGone("");
  player.src = `media/proxy/${video.id}.mp4`;
  player.load();

  const meta = $("#share-meta");
  meta.innerHTML = "";
  meta.appendChild(el("div", { className: "title", text: video.name }));
  meta.appendChild(el("div", { text: describeVideo(video) }));
  if (video.note) meta.appendChild(el("div", { className: "share-note", text: video.note }));

  const list = $("#share-segments");
  list.innerHTML = "";
  list.appendChild(el("div", { className: "muted small", text: "loading…" }));
  let detail;
  try {
    detail = await fetchJson(`api/videos/${video.id}`);
  } catch (e) {
    list.innerHTML = "";
    if (e && e.status === 404) {
      // UX-19: membership is re-checked per request, so a clip the editor
      // removed a moment ago 404s here while the page still shows it. Say
      // what happened instead of leaving a silent, empty panel.
      shareClipGone(CLIP_GONE_TEXT);
    } else {
      list.appendChild(el("div", { className: "muted small", text: "No description available." }));
    }
    return;
  }
  if (share.currentIdx !== idx) return; // the client moved on while we fetched
  list.innerHTML = "";
  if (!detail.segments.length) {
    list.appendChild(el("div", { className: "muted small", text: "No description available." }));
  }
  for (const seg of detail.segments) {
    const item = el("div", { className: "segment-item" });
    item.appendChild(el("div", { className: "seg-tc", text: `${formatDuration(seg.t_start)} - ${formatDuration(seg.t_end)}` }));
    const desc = [seg.description, seg.setting].filter(Boolean).join(" · ");
    item.appendChild(el("div", { className: "seg-desc", text: desc || "(no description)" }));
    item.addEventListener("click", () => {
      player.currentTime = seg.t_start;
      player.play().catch(() => {});
    });
    list.appendChild(item);
  }
}

function shareClose(push) {
  const player = $("#share-player");
  player.pause();
  player.removeAttribute("src");
  player.load();
  share.currentIdx = -1;
  shareClipGone("");
  $("#share-detail").classList.add("hidden");
  $("#share-grid-view").classList.remove("hidden");
  if (push) history.pushState(null, "", location.pathname);
  window.scrollTo(0, share.gridScrollY || 0);
}

/** Back to the grid. Through history when the detail entry is ours, so the
 * browser's own Back does the same thing; straight to the grid when the
 * client LANDED on a #v= link, where history.back() would leave the page. */
function shareBack() {
  if (history.state && history.state.share) history.back();
  else shareClose(true);
}

function shareStep(delta) {
  const next = share.currentIdx + delta;
  if (share.currentIdx < 0 || next < 0 || next >= share.items.length) return;
  shareOpen(next, "replace");
}

function shareKeydown(e) {
  if (share.currentIdx < 0) return;
  if (e.target && /^(INPUT|TEXTAREA)$/.test(e.target.tagName)) return;
  if (e.key === "Escape") {
    shareBack();
  } else if (e.key === "ArrowLeft") {
    shareStep(-1);
  } else if (e.key === "ArrowRight") {
    shareStep(+1);
  } else if (e.key === " ") {
    const player = $("#share-player");
    if (player.paused) player.play().catch(() => {});
    else player.pause();
    e.preventDefault();
  }
}
