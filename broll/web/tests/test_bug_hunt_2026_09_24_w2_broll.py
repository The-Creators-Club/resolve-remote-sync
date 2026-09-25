"""The 2026-09-24 hunt's wave-2 fixes in broll/web (mediums and lows).

  * bug-broll-1 / logic-broll-music-1: after a renumbering index rebuild, a
    client-folder item's STORED id can be another clip's CURRENT id. Remove,
    note, the popover tick, "already in the folder" and the public detail's
    caption each matched `stored id OR current name`, so one click removed two
    clips from a live client link and a new clip was refused as `already`.
  * bug-broll-2 (server half): /api/ingest/index and /moved resolve the clip
    by (share, rel_path) when the body names it.
  * bug-wire-2: a companion identity signed with a RETIRED session key
    (DASH_SESSION_SECRET_PREVIOUS) is accepted, as the dashboard accepts it.
  * bug-broll-4: a cancelled release from a machine whose lease another of
    the same editor's machines has since taken is refused.
  * logic-broll-music-4: the curator's own look at a client link is not
    counted as the client opening it.
  * ui-broll-web-1 / ui-broll-web-3: pinned against the static files (the
    frontend has no build step); ui-broll-web-3's key handler is also run
    under node when node is on PATH.
  * chunk 2, ui-broll-web-2 and -4 .. -11 (all lows): the share page's brand,
    copy, captions, disabled buttons and failure headline; the SPA's rail
    offset, the send-to-Resolve buttons across clip changes, and the client
    folder popover. CSS/HTML pinned as text, behaviour run under node.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import client_folders as cf
from app import ingest_batches
from app.main import app as broll_app
from tests.conftest import SESSION_SECRET, fleet_headers
from tests.factories import insert_video

STATIC = Path(__file__).resolve().parent.parent / "static"


def _create(client, title="For Acme"):
    r = client.post("api/client-folders", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()


def _add(client, folder_id, *video_ids):
    r = client.post(f"api/client-folders/{folder_id}/items", json={"video_ids": list(video_ids)})
    assert r.status_code == 200, r.text
    return r.json()


def _panel(client, folder_id):
    return client.get(f"api/client-folders/{folder_id}").json()["items"]


@pytest.fixture()
def renumbered(as_editor, conn):
    """The finding's shape: A stored as 5, B stored as 9; a rebuild then gives
    A id 7, B id 5, and a brand new clip C id 9."""
    a = insert_video(conn, id=5, share="ff3", rel_path="day1/A.mov", hash="ha")
    b = insert_video(conn, id=9, share="ff3", rel_path="day1/B.mov", hash="hb")
    folder = _create(as_editor)
    _add(as_editor, folder["id"], a, b)
    conn.execute("DELETE FROM videos")
    conn.commit()
    insert_video(conn, id=7, share="ff3", rel_path="day1/A.mov", hash="ha")
    insert_video(conn, id=5, share="ff3", rel_path="day1/B.mov", hash="hb")
    insert_video(conn, id=9, share="ff3", rel_path="day1/C.mov", hash="hc")
    return folder


# --- bug-broll-1 / logic-broll-music-1 -----------------------------------------------

def test_removing_one_clip_in_the_panel_removes_that_clip_only(as_editor, renumbered):
    folder = renumbered
    items = _panel(as_editor, folder["id"])
    assert [(i["name"], i["id"]) for i in items] == [("A", 7), ("B", 5)]
    a = items[0]
    # What the panel sends: the stored id in the path, the ledger row as item_id.
    assert a["video_id"] == 5 and a["item_id"]
    r = as_editor.delete(
        f"api/client-folders/{folder['id']}/items/{a['video_id']}?item_id={a['item_id']}")
    assert r.status_code == 204, r.text
    assert [i["name"] for i in _panel(as_editor, folder["id"])] == ["B"], \
        "removing A also removed B from the client's live link"
    theirs = TestClient(broll_app).get(f"/share/{folder['token']}/api/folder").json()
    assert [i["name"] for i in theirs["items"]] == ["B"]


def test_a_bare_current_id_removes_the_clip_that_id_names_now(as_editor, renumbered):
    """The card popover sends the CURRENT id. 5 is B now; A's stale stored 5
    must not come along with it."""
    folder = renumbered
    r = as_editor.delete(f"api/client-folders/{folder['id']}/items/5")
    assert r.status_code == 204, r.text
    assert [i["name"] for i in _panel(as_editor, folder["id"])] == ["A"]


def test_a_note_lands_on_one_clip_and_the_public_caption_is_that_clips(as_editor, renumbered):
    folder = renumbered
    a = _panel(as_editor, folder["id"])[0]
    r = as_editor.put(
        f"api/client-folders/{folder['id']}/items/{a['video_id']}/note?item_id={a['item_id']}",
        json={"note": "the harbour at dusk"})
    assert r.status_code == 200, r.text
    notes = {i["name"]: i["note"] for i in _panel(as_editor, folder["id"])}
    assert notes == {"A": "the harbour at dusk", "B": ""}

    anon = TestClient(broll_app)
    # B is current id 5, which is A's stale stored id: B's detail must not
    # carry A's caption.
    assert anon.get(f"/share/{folder['token']}/api/videos/5").json()["note"] == ""
    assert anon.get(f"/share/{folder['token']}/api/videos/7").json()["note"] == \
        "the harbour at dusk"


def test_a_new_clip_whose_id_an_old_item_carries_is_added(as_editor, renumbered):
    folder = renumbered
    tick = as_editor.get("api/client-folders", params={"video_id": 9}).json()["folders"]
    assert [f["contains"] for f in tick if f["id"] == folder["id"]] == [False], \
        "the popover ticked a folder that does not hold C"
    out = _add(as_editor, folder["id"], 9)
    assert out == {"added": [9], "already": [], "n_items": 3}
    assert [i["name"] for i in _panel(as_editor, folder["id"])] == ["A", "B", "C"]
    theirs = TestClient(broll_app).get(f"/share/{folder['token']}/api/folder").json()
    assert sorted(i["id"] for i in theirs["items"]) == [5, 7, 9]
    # ...and a clip already in the folder is still `already`, by what it IS.
    again = _add(as_editor, folder["id"], 7, 5)
    assert again["added"] == [] and again["already"] == [7, 5]


def test_an_old_panel_sending_no_item_id_still_reaches_a_missing_clip(as_editor, conn):
    """A clip that left the index: the panel lists it as missing and must be
    able to pull it out by its stored id."""
    gone = insert_video(conn, share="ff3", rel_path="day1/gone.mov")
    folder = _create(as_editor)
    _add(as_editor, folder["id"], gone)
    conn.execute("DELETE FROM videos WHERE id = ?", (gone,))
    conn.commit()
    [item] = _panel(as_editor, folder["id"])
    assert item["missing"] is True and item["item_id"]
    assert as_editor.delete(
        f"api/client-folders/{folder['id']}/items/{gone}").status_code == 204
    assert _panel(as_editor, folder["id"]) == []


def test_an_item_id_from_another_folder_matches_nothing(as_editor, conn):
    v = insert_video(conn, share="ff3", rel_path="day1/x.mov")
    one, two = _create(as_editor, "one"), _create(as_editor, "two")
    _add(as_editor, one["id"], v)
    _add(as_editor, two["id"], v)
    item_in_two = _panel(as_editor, two["id"])[0]["item_id"]
    r = as_editor.delete(f"api/client-folders/{one['id']}/items/{v}?item_id={item_in_two}")
    assert r.status_code == 404
    assert len(_panel(as_editor, two["id"])) == 1


def test_the_panel_names_its_rows_by_item_id():
    js = (STATIC / "clientfolders.js").read_text(encoding="utf-8")
    assert "function cfItemQuery(" in js
    assert "/items/${item.video_id}/note${cfItemQuery(item)}" in js
    assert "/items/${item.video_id}${cfItemQuery(item)}" in js


# --- bug-broll-2 (server half) --------------------------------------------------------

def test_ingest_index_resolves_by_path_when_the_body_names_one(client, conn):
    canonical_one = insert_video(conn, share="broll", rel_path="old/indexed.mov",
                                 status="indexed")
    fresh = insert_video(conn, share="broll", rel_path="new/clip.mov", status="discovered")
    # The indexer's local shadow numbered the new clip 1, which here is
    # someone else's clip.
    r = client.post("/api/ingest/index", json={
        "video_id": canonical_one, "share": "broll", "rel_path": "new/clip.mov",
        "themes": ["harbour"], "segments": [], "model": "m"})
    assert r.status_code == 200, r.text
    themes = {row["video_id"] for row in conn.execute("SELECT video_id FROM themes")}
    assert themes == {fresh}
    assert conn.execute("SELECT status FROM videos WHERE id = ?", (fresh,)).fetchone()[0] \
        == "indexed"

    r = client.post("/api/ingest/moved", json={
        "video_id": canonical_one, "share": "broll", "rel_path": "new/clip.mov",
        "new_rel_path": "cat/clip.mov"})
    assert r.status_code == 200, r.text
    paths = dict(conn.execute("SELECT id, rel_path FROM videos").fetchall())
    assert paths == {canonical_one: "old/indexed.mov", fresh: "cat/clip.mov"}


def test_ingest_index_with_an_unknown_path_is_a_404(client, conn):
    v = insert_video(conn, share="broll", rel_path="a.mov")
    r = client.post("/api/ingest/index", json={
        "video_id": v, "share": "broll", "rel_path": "nope.mov", "segments": []})
    assert r.status_code == 404


def test_an_id_only_body_is_answered_as_before(client, conn):
    v = insert_video(conn, share="broll", rel_path="a.mov")
    assert client.post("/api/ingest/index", json={
        "video_id": v, "themes": ["t"], "segments": []}).status_code == 200
    assert client.post("/api/ingest/index", json={
        "video_id": 0, "segments": []}).status_code == 404


# --- bug-wire-2 ------------------------------------------------------------------------

def _queue(client, editor="jsmith"):
    client.headers.update({"X-CCSync-User": editor})
    r = client.post("/api/ingest-batches", json={
        "share": "E2E", "settings": {"tier": "good"},
        "items": [{"local_id": "l0", "name": "A000.MP4", "size": 1234, "hash": "h0",
                   "source": "upload", "rel_dir": ""}]})
    assert r.status_code == 200, r.text
    return r.json()["uid"]


def _claim(client, uid, machine="EDIT-01", headers=None):
    return client.post(
        f"/api/fleet/ingest/batches/{uid}/claim",
        json={"machine": machine, "companion_version": "0.9.78", "tier": "good",
              "capabilities": {}},
        headers=headers or fleet_headers("jsmith", machine))


def test_an_identity_signed_with_a_retired_key_is_accepted(client, monkeypatch):
    from app import identity
    retired = "the-retired-session-secret-0123456789"
    uid = _queue(client)
    headers = fleet_headers()
    headers["X-CCSync-Identity"] = identity.make_identity_token(retired, "jsmith")

    monkeypatch.delenv("DASH_SESSION_SECRET_PREVIOUS", raising=False)
    assert _claim(client, uid, headers=headers).status_code == 403

    monkeypatch.setenv("DASH_SESSION_SECRET_PREVIOUS", f" ,{retired} , other-old-key")
    r = _claim(client, uid, headers=headers)
    assert r.status_code == 200, r.text


def test_a_key_that_was_never_ours_is_still_refused(client, monkeypatch):
    from app import identity
    uid = _queue(client)
    headers = fleet_headers()
    headers["X-CCSync-Identity"] = identity.make_identity_token("somebody-else-entirely-00", "jsmith")
    monkeypatch.setenv("DASH_SESSION_SECRET_PREVIOUS", "the-retired-session-secret-0123456789")
    assert _claim(client, uid, headers=headers).status_code == 403


def test_previous_secrets_parse_like_the_dashboards(monkeypatch):
    from app import config
    monkeypatch.setenv("DASH_SESSION_SECRET_PREVIOUS", " a , ,b,")
    assert config.get_previous_session_secrets() == ("a", "b")
    monkeypatch.delenv("DASH_SESSION_SECRET_PREVIOUS")
    assert config.get_previous_session_secrets() == ()
    assert SESSION_SECRET  # the current key is untouched by any of this


# --- bug-broll-4 -------------------------------------------------------------------------

def test_a_stale_machine_cannot_cancel_a_batch_another_machine_took_over(client, conn):
    uid = _queue(client)
    assert _claim(client, uid, machine="EDIT-01").status_code == 200
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    conn.execute("UPDATE ingest_batches SET lease_expires_at = ? WHERE uid = ?", (past, uid))
    conn.commit()
    assert _claim(client, uid, machine="EDIT-02").status_code == 200

    r = client.post(f"/api/fleet/ingest/batches/{uid}/release",
                    json={"state": "cancelled", "summary": {"reason": "tray"}},
                    headers=fleet_headers("jsmith", "EDIT-01"))
    assert r.status_code == 410, r.text
    assert r.json()["detail"]["reason"] == "other_machine"
    batch = ingest_batches.get_batch(conn, uid)
    assert batch["state"] not in ingest_batches.BATCH_TERMINAL
    assert conn.execute("SELECT COUNT(*) FROM videos WHERE status = ?",
                        (ingest_batches.VIDEO_STATUS_INGESTING,)).fetchone()[0] == 1


def test_the_holder_and_an_expired_lease_can_still_cancel(client, conn):
    uid = _queue(client)
    assert _claim(client, uid, machine="EDIT-01").status_code == 200
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    conn.execute("UPDATE ingest_batches SET lease_expires_at = ? WHERE uid = ?", (past, uid))
    conn.commit()
    # Nobody took it over: the relaxation this route exists for.
    r = client.post(f"/api/fleet/ingest/batches/{uid}/release",
                    json={"state": "cancelled"}, headers=fleet_headers("jsmith", "EDIT-01"))
    assert r.status_code == 200, r.text
    assert ingest_batches.get_batch(conn, uid)["state"] == "cancelled"


# --- logic-broll-music-4 ----------------------------------------------------------------

def test_the_curators_own_look_is_not_a_client_view(as_editor, conn):
    v = insert_video(conn, share="ff3", rel_path="day1/x.mov")
    folder = _create(as_editor)
    _add(as_editor, folder["id"], v)
    tok = folder["token"]
    # Through the dashboard gate with a session: X-CCSync-User is stamped.
    assert as_editor.get(f"/share/{tok}/api/folder").status_code == 200
    anon = TestClient(broll_app)
    # The panel's "open" link, from a public base where no cookie rides.
    assert anon.get(f"/share/{tok}/api/folder?preview=1").status_code == 200
    assert as_editor.get(f"api/client-folders/{folder['id']}").json()["view_count"] == 0
    anon.get(f"/share/{tok}/api/folder")
    assert as_editor.get(f"api/client-folders/{folder['id']}").json()["view_count"] == 1


def test_the_open_link_and_the_viewer_carry_preview():
    js = (STATIC / "clientfolders.js").read_text(encoding="utf-8")
    assert "href: `${field.value}?preview=1`" in js
    share = (STATIC / "share.js").read_text(encoding="utf-8")
    assert '"api/folder?preview=1"' in share


# --- ui-broll-web-1 -------------------------------------------------------------------------

def test_the_phone_detail_column_can_shrink_below_a_long_filename():
    css = (STATIC / "share.css").read_text(encoding="utf-8")
    assert ".share-layout { grid-template-columns: minmax(0, 1fr); }" in css
    assert ".share-layout .video-meta .title" in css
    assert "overflow-wrap: anywhere" in css


# --- ui-broll-web-3 -------------------------------------------------------------------------

def _function(js: str, name: str) -> str:
    start = js.index(f"function {name}(")
    return js[start:js.index("\n}", start) + 2]


_HARNESS = r"""
const calls = [];
const nodes = {};
function mkNode(id, hidden) {
  return { id, classList: { contains: (c) => c === "hidden" ? nodes[id].hidden : false },
           hidden };
}
for (const id of ["cf-panel", "ingest-panel", "settings-panel", "cf-popover"]) nodes[id] = mkNode(id, true);
const player = { currentTime: 1, duration: 10, paused: true, pause() {}, play() { return Promise.resolve(); } };
const document = { querySelector: (sel) => nodes[sel.replace("#", "")] || null };
function $(sel) { return sel === "#player" ? player : { textContent: "" }; }
const state = { detail: { video: { fps: 24 } } };
function sendToResolve(mode) { calls.push("send:" + mode); }
function togglePlayPause() { calls.push("toggle"); }
function resetShuttle() {}
function shuttle() {}
function timecode() { return ""; }
function renderInOutRange() {}
__FUNCS__
function target(tag, inside) {
  return { tagName: tag, isContentEditable: false,
           closest: (sel) => {
             if (inside && sel === "#" + inside) return {};
             if (sel.startsWith("#")) return null;
             return (tag === "BUTTON" || tag === "A") ? {} : null;
           } };
}
function press(key, t, shift) {
  let prevented = false;
  onKeydown({ key, shiftKey: !!shift, target: t, preventDefault() { prevented = true; } });
  return prevented;
}
const out = {};
out.enterOnDetailButton = press("Enter", target("BUTTON")); out.c1 = calls.splice(0);
out.shiftEnterOnDetailButton = press("Enter", target("BUTTON"), true); out.c2 = calls.splice(0);
out.enterOnBody = press("Enter", target("DIV")); out.c3 = calls.splice(0);
out.spaceOnDetailButton = press(" ", target("BUTTON")); out.c4 = calls.splice(0);
nodes["cf-panel"].hidden = false;
out.enterWithDrawerOpen = press("Enter", target("BUTTON", "cf-panel")); out.c5 = calls.splice(0);
out.spaceWithDrawerOpen = press(" ", target("DIV")); out.c6 = calls.splice(0);
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")
def test_detail_hotkeys_leave_drawers_and_focused_buttons_alone(tmp_path):
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    funcs = [_function(js, "onKeydown"), _function(js, "hotkeysYieldToOverlay"),
             _function(js, "isActivatable")]
    start = js.index("const HOTKEY_OVERLAYS")
    funcs.insert(0, js[start:js.index(";", start) + 1])
    script = tmp_path / "harness.js"
    script.write_text(_HARNESS.replace("__FUNCS__", "\n".join(funcs)), encoding="utf-8")
    out = json.loads(subprocess.run(["node", str(script)], check=True,
                                    capture_output=True, text=True).stdout)
    # A focused button in the detail view keeps Enter.
    assert out["enterOnDetailButton"] is False and out["c1"] == []
    # Shift+Enter stays insert-at-playhead; Enter off a control still appends.
    assert out["c2"] == ["send:playhead"]
    assert out["enterOnBody"] is True and out["c3"] == ["send:append"]
    # Space stays play/pause even on a focused button (see the comment in app.js).
    assert out["c4"] == ["toggle"]
    # With a drawer open, no key is the clip's.
    assert out["enterWithDrawerOpen"] is False and out["c5"] == []
    assert out["spaceWithDrawerOpen"] is False and out["c6"] == []


# ===========================================================================================
# Chunk 2 (2026-09-25): ui-broll-web-2, -4 .. -11. The frontend has no build step, so the CSS
# and HTML are pinned as text and the behaviour is run under node against a small fake DOM.
# ===========================================================================================

_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")

_FAKE_DOM = r"""
function mkEl(tag) {
  const n = { tagName: String(tag).toUpperCase(), children: [], listeners: {}, attrs: {},
    style: {}, _text: "", disabled: false, checked: false, className: "", hidden: false,
    classList: { _s: new Set(),
      add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
      contains(c) { return this._s.has(c); },
      toggle(c, on) { if (on === undefined) on = !this._s.has(c); on ? this._s.add(c) : this._s.delete(c); } },
    appendChild(c) { this.children.push(c); c.parent = this; return c; },
    append(...cs) { for (const c of cs) this.children.push(typeof c === "string" ? { _text: c, children: [] } : c); },
    after(c) { if (this.parent) this.parent.children.push(c); else this._after = c; },
    addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
    setAttribute(k, v) { this.attrs[k] = String(v); if (k === "title") this.title = String(v); },
    removeAttribute(k) { delete this.attrs[k]; if (k === "title") delete this.title; },
    get textContent() { return this._text + this.children.map((c) => c.textContent !== undefined ? c.textContent : c._text).join(""); },
    set textContent(v) { this._text = String(v); this.children = []; },
    get innerHTML() { return this._text; },
    set innerHTML(v) { this._text = String(v); this.children = []; },
  };
  return n;
}
function fire(n, type, ev) { return Promise.all((n.listeners[type] || []).map((f) => f(ev || { currentTarget: n, target: n }))); }
function walk(n, pred, out = []) { if (pred(n)) out.push(n); for (const c of n.children || []) walk(c, pred, out); return out; }
const byId = {};
const document = {
  createElement: mkEl,
  getElementById: (id) => byId[id] || null,
  querySelector: (sel) => byId[sel.replace(/^#/, "")] || null,
  documentElement: { style: { props: {}, setProperty(k, v) { this.props[k] = v; } } },
};
function $(sel) { return document.querySelector(sel); }
function el(tag, opts) {
  const node = document.createElement(tag);
  if (opts) {
    if (opts.className) node.className = opts.className;
    if (opts.text !== undefined) node.textContent = opts.text;
    if (opts.attrs) for (const [k, v] of Object.entries(opts.attrs)) node.setAttribute(k, v);
  }
  return node;
}
const toasts = [];
function toast(m, k) { toasts.push([k || "", m]); }
const tick = () => new Promise((r) => setImmediate(r));
"""


def _run_node(tmp_path, body: str) -> dict:
    script = tmp_path / "harness.js"
    script.write_text(_FAKE_DOM + body, encoding="utf-8")
    run = subprocess.run(["node", str(script)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout.strip().splitlines()[-1])


def _fn(js: str, name: str) -> str:
    """_function, keeping an `async` in front (an async body would not parse without it)."""
    body = _function(js, name)
    start = js.index(f"function {name}(")
    return "async " + body if js[max(0, start - 6):start] == "async " else body


def _static(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


# --- ui-broll-web-2 / -7 / -8 / -9: the share page's CSS and copy ---------------------------

def test_the_share_brand_may_shrink_and_wrap_a_long_org_name():
    css = _static("share.css")
    # `.topbar > *` (style.css) is flex 0 0 auto + nowrap; the brand must override both.
    assert ".share-header .topbar > .brand { flex: 0 1 auto; min-width: 0; white-space: normal; }" in css
    assert ".share-header #share-org { flex: 0 1 auto; min-width: 0; overflow-wrap: anywhere; }" in css


def test_the_share_page_does_not_tell_a_phone_to_hover():
    html = _static("share.html")
    assert "Hover a thumbnail to scrub through the clip. Click it" not in html
    assert "Tap or click a clip to play the preview" in html
    css = _static("share.css")
    assert "@media (hover: none) {\n  .share-body .keyhelp { display: none; }\n}" in css


def test_the_share_caption_shows_three_whole_lines():
    css = _static("share.css")
    rule = css[css.index(".share-caption {"):]
    rule = rule[:rule.index("}")]
    assert "max-height: 3.9em" not in rule
    assert "-webkit-line-clamp: 3;" in rule
    # overflow clips at the padding box: bottom padding showed a sliver of line four.
    assert "padding: 5px 7px 0;" in rule and "margin-bottom: 6px;" in rule
    assert "max-height: calc(4.2em + 6px);" in rule


def test_a_disabled_text_button_looks_disabled():
    css = _static("style.css")
    rule = ".text-btn:disabled,\n.text-btn:disabled:hover { color: var(--muted); cursor: default; text-shadow: none; }"
    assert rule in css
    # After the :hover rule, so the tie of specificity goes to the disabled look.
    assert css.index(rule) > css.index(".text-btn:hover {")


# --- ui-broll-web-10: a transient failure is not "This link is not available" ---------------

_SHARE_INIT = r"""
const location = { search: "", reload() { globalThis.reloaded = true; } };
const window = { addEventListener() {} };
document.addEventListener = () => {};
for (const id of ["share-back", "share-player", "share-prev", "share-next", "share-title",
                  "share-desc", "share-howto", "share-org", "share-footer-org"]) byId[id] = mkEl("div");
byId["share-desc"].parent = mkEl("div");
const share = {};
function shareStep() {} function shareApplyHash() {} function shareKeydown() {}
function shareBack() {} function shareExplainPlaybackFailure() {}
let FAIL = null;
async function fetchJson() { throw FAIL; }
__FUNC__
(async () => {
  const out = {};
  for (const status of [404, 502, undefined]) {
    for (const id of Object.keys(byId)) { byId[id].textContent = ""; byId[id].classList._s.clear(); }
    byId["share-desc"].parent.children = [];
    const e = new Error(status ? "HTTP " + status : "Failed to fetch"); e.status = status;
    FAIL = e;
    await shareInit();
    const extra = byId["share-desc"].parent.children;
    if (extra.length) await fire(extra[0], "click");
    out[String(status)] = { title: byId["share-title"].textContent, desc: byId["share-desc"].textContent,
      howtoHidden: byId["share-howto"].classList.contains("hidden"),
      retry: extra.map((b) => b.textContent), reloaded: !!globalThis.reloaded };
    globalThis.reloaded = false;
  }
  console.log(JSON.stringify(out));
})();
"""


@_node
def test_a_transient_share_failure_offers_a_retry_not_a_dead_link(tmp_path):
    js = _static("share.js")
    out = _run_node(tmp_path, _SHARE_INIT.replace("__FUNC__", _fn(js, "shareInit")))
    assert out["404"]["title"] == "This link is not available"
    assert out["404"]["retry"] == []
    for key in ("502", "undefined"):
        got = out[key]
        assert got["title"] == "The preview could not load just now"
        assert "HTTP" not in got["desc"] and "Failed to fetch" not in got["desc"]
        assert got["retry"] == ["Try again"] and got["reloaded"] is True
        assert got["howtoHidden"] is True
    assert out["404"]["howtoHidden"] is True


# --- ui-broll-web-4: the rail parks under the header's MEASURED height -----------------------

_HEADER = r"""
let observed = null;
class ResizeObserver { constructor(cb) { this.cb = cb; } observe(n) { observed = this; } }
const window = { addEventListener() {} };
const header = mkEl("header"); byId["app-header"] = header;
let height = 98;
header.getBoundingClientRect = () => ({ height });
__FUNC__
trackHeaderHeight();
const first = document.documentElement.style.props["--header-h"];
height = 231.4;                     // the topbar injected, the controls re-wrapped
observed.cb();
console.log(JSON.stringify({ first, after: document.documentElement.style.props["--header-h"] }));
"""


@_node
def test_the_rail_offset_follows_the_real_header(tmp_path):
    js = _static("app.js")
    assert "trackHeaderHeight();\n  loadDashboardTopbar();" in js
    out = _run_node(tmp_path, _HEADER.replace("__FUNC__", _fn(js, "trackHeaderHeight")))
    assert out == {"first": "98px", "after": "232px"}


# --- ui-broll-web-6: the send in flight is named, and never painted onto another clip -------

_SEND = r"""
const window = { addEventListener() {} };
const COMPANION_URL = "http://127.0.0.1:8899";
const send = mkEl("button"); send.innerHTML = "Append to Timeline &#9166;"; byId["send-resolve-btn"] = send;
const place = mkEl("button"); place.innerHTML = "Place at Playhead"; byId["place-resolve-btn"] = place;
const state = { detail: null, inPoint: 1, outPoint: 2 };
const A = { video: { id: 1, rel_path: "day1/A001.mov", fps: 25 } };
const B = { video: { id: 2, rel_path: "day1/B002.mov", fps: 25 } };
function basename(p) { return p.split("/").pop(); }
let gate; const answers = [];
async function fetch() {
  const a = answers.shift();
  if (a === "wait") await new Promise((r) => { gate = r; });
  const body = a === "wait" ? { ok: true, state: "done", message: "Inserted." } : a;
  return { ok: true, status: 200, json: async () => body };
}
const setTimeout = (fn) => { fn(); };
__FUNCS__
(async () => {
  const out = {};
  state.detail = A;
  answers.push({ ok: true, state: "downloading", progress: { percent: 40 } }, "wait");
  const p = sendToResolve("append");
  await tick(); await tick();
  out.onA = { label: send.textContent, disabled: send.disabled && place.disabled };
  state.detail = B; state.inPoint = 3; state.outPoint = 4;   // openDetail(B)
  renderSendButtons();
  out.onB = { label: send.innerHTML, disabled: send.disabled, title: send.title || "" };
  toasts.length = 0;
  await sendToResolve("append");                             // Enter on B while A is in flight
  out.pressOnB = toasts.splice(0);
  gate(); await p;
  out.done = toasts.splice(0);
  out.after = { label: send.innerHTML, disabled: send.disabled, title: send.title || null };
  console.log(JSON.stringify(out));
})();
"""


@_node
def test_a_send_in_flight_is_not_painted_onto_the_next_clip(tmp_path):
    js = _static("app.js")
    funcs = [_fn(js, n) for n in ("syncProgressLabel", "sendShowingInFlightClip",
                                        "sendClipMessage", "renderSendButtons", "sendToResolve")]
    decl = "let sendInFlight = false;\nlet sendClip = null;\nlet sendOriginalLabels = null;\n"
    out = _run_node(tmp_path, _SEND.replace("__FUNCS__", decl + "\n".join(funcs)))
    assert out["onA"] == {"label": "SYNCING 40%", "disabled": True}
    # Clip B shows its own labels; the buttons stay held (one send per companion) and say why.
    assert out["onB"]["label"] == "Append to Timeline &#9166;"
    assert out["onB"]["disabled"] is True
    assert 'Still sending "A001.mov"' in out["onB"]["title"]
    assert out["pressOnB"] and 'Still sending "A001.mov"' in out["pressOnB"][0][1]
    # The result names the clip that actually went in, since B is on screen.
    assert out["done"] == [["success", '"A001.mov": Inserted.']]
    assert out["after"] == {"label": "Append to Timeline &#9166;", "disabled": False, "title": None}
    # openDetail and closeDetail both redraw the buttons.
    for name in ("openDetail", "closeDetail"):
        assert "renderSendButtons();" in _function(js, name)


# --- ui-broll-web-5 / -11: the popover ---------------------------------------------------------

_POPOVER = r"""
const window = { innerWidth: 1366, innerHeight: 800, prompt: () => "New client" };
const pop = mkEl("div"); byId["cf-popover"] = pop;
let popHeight = 300;
Object.defineProperty(pop, "scrollHeight", { get: () => popHeight });
const cf = { open: false, folders: [{ id: 1, title: "Acme", n_items: 3, contains: false }],
             popoverVideo: null, popoverAnchor: null };
const calls = [];
let failItems = false;
async function fetchJson(url, opts) {
  calls.push(`${(opts && opts.method) || "GET"} ${url}`);
  if (url === "api/client-folders" && opts && opts.method === "POST") return { id: 9, title: "New client" };
  if (url.endsWith("/items") && failItems) { const e = new Error("Video 5 not found"); e.status = 404; throw e; }
  if (url.startsWith("api/client-folders?video_id=")) {
    cf.folders = [{ id: 1, title: "Acme", n_items: 4, contains: true }, { id: 9, title: "New client", n_items: 0, contains: false }];
    return { folders: cf.folders };
  }
  return {};
}
async function cfLoadFolders(videoId) { const d = await fetchJson(`api/client-folders?video_id=${videoId}`); cf.folders = d.folders; return d; }
function cfOpenFolder() {} function cfOpen() {} function cfClosePopover() {}
__FUNCS__
function anchorAt(top, bottom) { return { getBoundingClientRect: () => ({ left: 100, top, bottom }) }; }
(async () => {
  const out = {};
  const video = { id: 5 };
  cf.popoverVideo = video; cf.popoverAnchor = anchorAt(40, 60);
  cfRenderPopover();
  // (a) ticking a folder redraws its count
  const box = walk(pop, (n) => n.tagName === "INPUT")[0];
  const count = walk(pop, (n) => n.className === "muted small cf-pop-count")[0];
  box.checked = true;
  await fire(box, "change");
  out.count = count ? count.textContent : null;
  // ui-broll-web-5: the add after "+ new folder" fails
  failItems = true; toasts.length = 0;
  const newBtn = walk(pop, (n) => n.className === "text-btn cf-pop-new")[0];
  let unhandled = null;
  process.on("unhandledRejection", (e) => { unhandled = String(e); });
  await fire(newBtn, "click").catch((e) => { unhandled = String(e); });
  await tick();
  out.toasts = toasts.splice(0);
  out.unhandled = unhandled;
  out.redrawnTitles = walk(pop, (n) => n.className === "cf-pop-title").map((n) => n.textContent);
  // (b) placement: under a card near the bottom it flips above; near the top it stays below
  popHeight = 300;
  cfPlacePopover(anchorAt(700, 722));
  out.nearBottom = { top: pop.style.top, maxHeight: pop.style.maxHeight };
  cfPlacePopover(anchorAt(40, 62));
  out.nearTop = { top: pop.style.top, maxHeight: pop.style.maxHeight };
  popHeight = 2000;   // taller than either side: the bigger side, scrolling inside it
  cfPlacePopover(anchorAt(500, 522));
  out.tooTall = { top: pop.style.top, maxHeight: pop.style.maxHeight };
  console.log(JSON.stringify(out));
})();
"""


@_node
def test_the_popover_counts_reports_and_stays_on_screen(tmp_path):
    js = _static("clientfolders.js")
    funcs = [_fn(js, n) for n in ("cfCreateFlow", "cfRenderPopover", "cfPlacePopover")]
    out = _run_node(tmp_path, _POPOVER.replace("__FUNCS__", "\n".join(funcs)))
    assert out["count"] == "4"
    assert out["unhandled"] is None
    kinds = [k for k, _ in out["toasts"]]
    assert kinds == ["success", "error"], out["toasts"]
    assert 'Folder "New client" was created, but the clip was not added' in out["toasts"][1][1]
    # The popover is redrawn with the new folder in it even though the add failed.
    assert out["redrawnTitles"] == ["Acme", "New client"]
    # 800 px window: under an anchor at 722 there are 66 px; above it, 688.
    assert out["nearBottom"] == {"top": "396px", "maxHeight": "688px"}
    assert out["nearTop"] == {"top": "66px", "maxHeight": "726px"}
    # 488 above vs 266 below: above, scrolling within the 488 px it has.
    assert out["tooTall"] == {"top": "8px", "maxHeight": "488px"}


def test_the_card_plus_is_reachable_by_keyboard_and_touch():
    css = _static("style.css")
    assert ".cf-card-add:focus-visible { opacity: 1; }" in css
    assert "@media (hover: none) {\n  .cf-card-add { opacity: 1; }\n}" in css
    pop = css[css.index(".cf-popover {"):]
    pop = pop[:pop.index("}")]
    assert "max-height: 60vh;" in pop and "overflow-y: auto;" in pop


# ===========================================================================================
# Chunk 3 (2026-09-25): ui-broll-web-12 .. -18 (all lows). Same method as chunk 2: behaviour
# run under node against the fake DOM, CSS and HTML pinned as text.
# ===========================================================================================

def _const(js: str, name: str) -> str:
    start = js.index(f"const {name}")
    return js[start:js.index(";", start) + 1]


# --- ui-broll-web-12: a caption typed just before a reorder survives the redraw --------------

_CAPTION = r"""
const view = mkEl("div"); byId["cf-detail-view"] = view;
const cf = { current: { id: 3, items: [
  { id: 11, video_id: 11, item_id: 101, name: "A.mov", note: "" },
  { id: 12, video_id: 12, item_id: 102, name: "B.mov", note: "" },
  { id: 13, video_id: 13, item_id: 103, name: "C.mov", note: "" } ] } };
function basename(p) { return p; } function formatDuration() { return ""; } function openDetail() {}
let release; let failNext = false; const puts = [];
async function fetchJson(url, opts) {
  if (opts && opts.method === "PUT" && url.includes("/note")) {
    puts.push([url, JSON.parse(opts.body).note]);
    await new Promise((r) => { release = r; });
    if (failNext) { failNext = false; throw new Error("HTTP 500"); }
  }
  return {};
}
function cfRenderFolder() {
  view.children = [];
  cf.current.items.forEach((item, idx) => view.appendChild(cfItemRow(item, idx, cf.current.items.length)));
}
function noteOf(name) {
  const row = view.children.find((r) => walk(r, (n) => n.className === "cf-item-name")[0].textContent.startsWith(name));
  return { field: walk(row, (n) => n.tagName === "INPUT")[0],
           mark: walk(row, (n) => String(n.className || "").includes("cf-note-saved"))[0] };
}
__FUNCS__
(async () => {
  const out = {};
  cfRenderFolder();
  // Type into B's caption, then press C's up arrow: blur -> change (PUT starts) -> click.
  const b = noteOf("B.mov");
  b.field.value = "Harbour at dusk";
  const saving = fire(b.field, "change");
  await cfMove(2, -1);
  out.redrawn = noteOf("B.mov").field.value;
  out.markBefore = noteOf("B.mov").mark.textContent;
  release(); await saving; await tick();
  out.markAfter = noteOf("B.mov").mark.textContent;
  out.put = puts[0];
  // Review round: the mark is a sibling of the name span, never inside the
  // part of the line that is ellipsized.
  const line = walk(view.children.find((r) => walk(r, (n) => n.className === "cf-item-name")[0].textContent.startsWith("B.mov")),
                    (n) => n.className === "cf-item-name")[0];
  out.lineKids = line.children.map((c) => c.className);
  // A failed save goes back to the server's caption in the model and says so.
  const a = noteOf("A.mov");
  a.field.value = "never stored"; failNext = true; toasts.length = 0;
  const failing = fire(a.field, "change");
  await tick(); release(); await failing;
  out.failedModel = cf.current.items.find((i) => i.name === "A.mov").note;
  out.failToasts = toasts.splice(0);
  out.failMark = noteOf("A.mov").mark.textContent;
  console.log(JSON.stringify(out));
  process.exit(0);
})();
"""


@_node
def test_a_caption_typed_before_a_reorder_is_not_redrawn_away(tmp_path):
    js = _static("clientfolders.js")
    funcs = [_const(js, "cfNoteFields"), _fn(js, "cfItemQuery"), _fn(js, "cfFlashSaved"),
             _fn(js, "cfItemRow"), _fn(js, "cfMove")]
    out = _run_node(tmp_path, _CAPTION.replace("__FUNCS__", "\n".join(funcs)))
    # On HEAD the redrawn field read "" while the server stored the new caption.
    assert out["redrawn"] == "Harbour at dusk"
    assert out["put"] == ["api/client-folders/3/items/12/note?item_id=102", "Harbour at dusk"]
    # A save that worked now says so, on the row that shows the clip after the redraw.
    assert out["markBefore"] == "" and out["markAfter"] == "saved"
    assert out["failedModel"] == ""
    assert out["failToasts"] == [["error", "Caption not saved: HTTP 500"]]
    assert out["failMark"] == ""
    # Review round (2026-09-25): on the first fix the mark sat inside a line that
    # was `overflow: hidden; text-overflow: ellipsis` as a whole, so a ~60-char
    # clip name pushed "saved" past the clip edge (rendered in headless Chrome
    # at the 460 px panel: mark right 1429 vs line right 1208). Only the name
    # span may shrink now; the fake DOM has no layout, so the CSS is pinned too.
    assert out["lineKids"] == ["cf-item-name-text", "small cf-note-saved"]
    css = _static("style.css")
    rule = lambda sel: re.search(r"(?m)^" + re.escape(sel) + r" \{([^}]*)\}", css).group(1)
    line = rule(".cf-item-name")
    assert "display: flex" in line and "overflow" not in line and "ellipsis" not in line
    name_text = rule(".cf-item-name-text")
    assert "text-overflow: ellipsis" in name_text and "min-width: 0" in name_text
    assert "flex: none" in rule(".cf-note-saved") and "flex: none" in rule(".cf-item-dur")


# --- ui-broll-web-13: the header buttons say what they open ----------------------------------

def test_the_header_has_no_second_hamburger_or_gear():
    html = _static("index.html")
    cf_btn = html[html.index('<button id="cf-btn"'):]
    cf_btn = cf_btn[:cf_btn.index("</button>")]
    settings = html[html.index('<button id="settings-btn"'):]
    settings = settings[:settings.index("</button>")]
    assert "&#9776;" not in cf_btn and cf_btn.endswith(">client folders")
    assert "&#9881;" not in settings and settings.endswith(">tray + shares")
    assert "<h2>Tray and shares</h2>" in html
    assert ".icon-btn.label-btn {" in _static("style.css")


# --- ui-broll-web-14 / -15: the Running box ---------------------------------------------------

_LIVE = r"""
for (const id of ["ingest-live-body", "ingest-live", "ingest-pause", "ingest-resume",
                  "ingest-start-now", "ingest-pause-upload", "ingest-cancel"]) byId[id] = mkEl("div");
const ing = { batchUid: "b1", batch: { share: "ff3", state: "running", upload_paused: false },
              loopback: null, batchItems: [{ state: "proxies_live", rel_dir: "Taipei", orig_name: "A001.mov" },
                                           { state: "queued", rel_dir: "", orig_name: "B.mov" }],
              running: true, tier: "good" };
function ingestBatchStateText() { return "indexing"; } function ingestBatchCounts() { return ""; }
function ingestAgo() { return ""; } function ingTierLabel(t) { return t; }
const ING_COMPANION_HINT = "hint";
let answer = null; const posted = [];
async function ingestLoopback(method, path, body) { posted.push(body.action); return answer; }
function ingestPollLoopback() {}
__FUNCS__
function shown() {
  const vis = (id) => !byId[id].classList.contains("hidden");
  return { pause: vis("ingest-pause"), resume: vis("ingest-resume"), startNow: vis("ingest-start-now"),
           pauseDisabled: byId["ingest-pause"].disabled };
}
(async () => {
  const out = {};
  ing.loopback = { batch: { gate: "running", paused: false } };
  ingestRenderLive();
  out.rows = walk(byId["ingest-live-body"], (n) => String(n.className || "").startsWith("ingest-item-state ")).map((n) => n.textContent);
  out.running = shown();
  ing.loopback = { batch: { gate: "paused", paused: true } };
  ingestRenderLive(); out.paused = shown();
  ing.loopback = { batch: { gate: "user-active", paused: false } };
  ingestRenderLive(); out.userActive = shown();
  ing.loopback = { batch: { gate: "paused" } };            // a companion that sends no flag
  ingestRenderLive(); out.noFlag = shown();
  ing.loopback = null;                                       // the tray is not answering
  ingestRenderLive(); out.noTray = shown();
  answer = { ok: true, state: "running" };
  await ingestControl("resume");
  out.toast = toasts.splice(0);
  console.log(JSON.stringify(out));
})();
"""


@_node
def test_the_running_box_speaks_words_and_offers_only_what_applies(tmp_path):
    js = _static("ingest.js")
    funcs = [_const(js, "ING_GATE_LABELS"), _fn(js, "ingGateLabel"),
             _const(js, "ING_ITEM_STATE_TEXT"), _fn(js, "ingestItemStateText"),
             _const(js, "ING_START_NOW_GATES"), _fn(js, "ingestRenderLive"), _fn(js, "ingestControl")]
    out = _run_node(tmp_path, _LIVE.replace("__FUNCS__", "\n".join(funcs)))
    # ui-broll-web-14: the batch card's words, not the server's token.
    assert out["rows"][0].startswith("original still owed Taipei/A001.mov")
    assert not any("proxies_live" in r for r in out["rows"])
    # ui-broll-web-15: one of Pause/Resume, and Start now only while it is waiting on the editor.
    assert out["running"] == {"pause": True, "resume": False, "startNow": False, "pauseDisabled": False}
    assert out["paused"] == {"pause": False, "resume": True, "startNow": False, "pauseDisabled": False}
    assert out["userActive"] == {"pause": True, "resume": False, "startNow": True, "pauseDisabled": False}
    assert out["noFlag"]["resume"] is True and out["noFlag"]["pause"] is False
    assert out["noTray"] == {"pause": True, "resume": False, "startNow": False, "pauseDisabled": True}
    assert out["toast"] == [["", "CC Sync tray: indexing."]]


# --- ui-broll-web-16: the fallback toast names the mode the page switched to ---------------

_MODES = r"""
const container = mkEl("div"); byId["mode-toggles"] = container;
const buttons = ["hybrid", "keyword", "semantic"].map((m) => { const b = mkEl("button"); b.dataset = { mode: m }; return b; });
container.querySelectorAll = () => buttons;
const state = { mode: "semantic", modeAvailable: null };
__FUNCS__
const out = {};
state.modeAvailable = { keyword: { available: true, reason: "" },
  semantic: { available: false, reason: "No clips have been prepared for meaning-based search yet, so it can only find nothing." },
  hybrid: { available: true, reason: "Keyword only right now: the meaning-based half of this search is not available." } };
out.hopped = applyModeAvailability();
out.mode = state.mode;
out.active = buttons.filter((b) => b.classList.contains("active")).map((b) => b.dataset.mode);
out.toast = toasts.splice(0);
console.log(JSON.stringify(out));
"""


@_node
def test_the_mode_fallback_toast_names_hybrid(tmp_path):
    js = _static("app.js")
    out = _run_node(tmp_path, _MODES.replace("__FUNCS__", _fn(js, "applyModeAvailability")))
    assert out["hopped"] is True and out["mode"] == "hybrid" and out["active"] == ["hybrid"]
    [[kind, text]] = out["toast"]
    assert kind == "warn"
    assert "by keyword instead" not in text
    assert "Switched to Hybrid, which is searching by keyword only for now." in text


# --- ui-broll-web-17: an error toast stays until dismissed -----------------------------------

_TOAST = r"""
const timers = [];
const setTimeout = (fn, ms) => { timers.push([fn, ms]); };
function mkNode(tag) {
  const n = mkEl(tag);
  n.remove = () => { const p = n.parent; if (p) p.children = p.children.filter((c) => c !== n); n.parent = null; };
  n.classList.contains = (c) => (" " + n.className + " ").includes(" " + c + " ");
  return n;
}
document.createElement = mkNode;
const container = mkNode("div"); byId["toast-container"] = container;
__FUNCS__
const out = {};
const long = "Couldn't reach the CC Sync tray. " + "x".repeat(300);
toast(long, "error");
toast("Saved", "success");
out.timers = timers.map(([, ms]) => ms);
for (const [fn] of timers.splice(0)) fn();              // every timer fires
out.left = container.children.map((n) => n.className);
out.text = container.children[0].children[0].textContent;
toast(long, "error");                                   // the same error again: one copy
out.afterRepeat = container.children.length;
for (let i = 0; i < 6; i += 1) toast("upload " + i + " failed", "error");
out.capped = container.children.length;
const close = container.children[0].children[1];
fire(close, "click");
out.afterDismiss = container.children.length;
toast("w".repeat(400), "warn");
out.warnMs = timers.pop()[1];
console.log(JSON.stringify(out));
"""


@_node
def test_an_error_toast_stays_until_dismissed(tmp_path):
    js = _static("app.js")
    funcs = [_const(js, "TOAST_MAX_STICKY"), _fn(js, "toastLifetimeMs"), _fn(js, "toast")]
    out = _run_node(tmp_path, _TOAST.replace("__FUNCS__", "\n".join(funcs)))
    # Only the success toast is timed; on HEAD both were, at 5000 ms.
    assert out["timers"] == [5000]
    assert out["left"] == ["toast error"]
    assert out["text"].startswith("Couldn't reach the CC Sync tray.")
    assert out["afterRepeat"] == 1
    assert out["capped"] == 4
    assert out["afterDismiss"] == 3
    assert out["warnMs"] == 15000
    css = _static("style.css")
    assert ".toast-close {" in css and "user-select: text;" in css


# --- ui-broll-web-18: a narrow layout --------------------------------------------------------

def test_the_spa_has_a_narrow_layout():
    css = _static("style.css")
    block = css[css.index("@media (max-width: 700px) {"):]
    block = block[:block.index("\n}\n") + 3]
    for rule in (".flag-toggles { flex: 1 1 100%; flex-wrap: wrap; white-space: normal;",
                 "#browse-layout { flex-direction: column;",
                 ".detail-layout { grid-template-columns: minmax(0, 1fr); }",
                 "position: static;"):
        assert rule in block, rule
    # The cards keep their 240 px: sprite.js positions the scrub sheet in 240 px cells.
    assert "240px" not in block and "minmax(160px" not in block


# --- owed round: bug-wire-7 (server half) -------------------------------------------------
# A companion on a computer whose name is not Latin-1 cannot send X-CCSync-Machine
# (http.client raises), so since the c-broll-music fix it sends the name
# percent-encoded in X-CCSync-Machine-Pct. The server must read that twin, or
# such a machine has no machine check at all.

CJK_MACHINE = "剪輯-PC"


def _pct_headers(editor="jsmith", machine=CJK_MACHINE):
    import urllib.parse
    h = fleet_headers(editor, "x")
    h.pop("X-CCSync-Machine")
    h["X-CCSync-Machine-Pct"] = urllib.parse.quote(machine, safe="")
    return h


def test_a_pct_declared_machine_that_does_not_hold_the_batch_gets_410(client, conn):
    uid = _queue(client)
    assert _claim(client, uid, machine="EDIT-01").status_code == 200
    r = client.post(f"/api/fleet/ingest/batches/{uid}/heartbeat", json={},
                    headers=_pct_headers(machine=CJK_MACHINE))
    assert r.status_code == 410, r.text
    assert r.json()["detail"]["reason"] == "other_machine"


def test_the_cjk_holder_passes_the_machine_check_via_the_pct_header(client, conn):
    uid = _queue(client)
    assert _claim(client, uid, machine=CJK_MACHINE,
                  headers=_pct_headers()).status_code == 200
    assert ingest_batches.get_batch(conn, uid)["machine"] == CJK_MACHINE
    r = client.post(f"/api/fleet/ingest/batches/{uid}/heartbeat", json={},
                    headers=_pct_headers())
    assert r.status_code == 200, r.text


def test_a_stale_cjk_machine_cannot_cancel_a_batch_another_took_over(client, conn):
    uid = _queue(client)
    assert _claim(client, uid, machine=CJK_MACHINE,
                  headers=_pct_headers()).status_code == 200
    past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    conn.execute("UPDATE ingest_batches SET lease_expires_at = ? WHERE uid = ?", (past, uid))
    conn.commit()
    assert _claim(client, uid, machine="EDIT-02").status_code == 200
    r = client.post(f"/api/fleet/ingest/batches/{uid}/release",
                    json={"state": "cancelled"}, headers=_pct_headers())
    assert r.status_code == 410, r.text
    assert r.json()["detail"]["reason"] == "other_machine"


def test_the_plain_header_wins_and_a_malformed_pct_is_a_410_not_a_500(client, conn):
    uid = _queue(client)
    assert _claim(client, uid, machine="EDIT-01").status_code == 200
    both = fleet_headers("jsmith", "EDIT-01")
    both["X-CCSync-Machine-Pct"] = "LAPTOP-02"
    assert client.post(f"/api/fleet/ingest/batches/{uid}/heartbeat", json={},
                       headers=both).status_code == 200
    bad = _pct_headers()
    bad["X-CCSync-Machine-Pct"] = "%FF%FE"
    r = client.post(f"/api/fleet/ingest/batches/{uid}/heartbeat", json={}, headers=bad)
    assert r.status_code == 410, r.text


# --- owed round: ui-dash-static-5 parity ----------------------------------------------

def _contrast(fg: str, bg: str) -> float:
    def lum(h):
        h = h.lstrip("#")
        out = []
        for i in (0, 2, 4):
            c = int(h[i:i + 2], 16) / 255
            out.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
        return 0.2126 * out[0] + 0.7152 * out[1] + 0.0722 * out[2]
    a, b = sorted((lum(fg), lum(bg)), reverse=True)
    return (a + 0.05) / (b + 0.05)


def test_muted_text_meets_aa_on_every_surface_and_the_gone_page():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    tok = {k: v for k, v in re.findall(r"--(bg|panel|field|muted):\s*(#[0-9a-fA-F]{6})", css)}
    for surface in ("bg", "panel", "field"):
        assert _contrast(tok["muted"], tok[surface]) >= 4.5, surface
    gone = (STATIC / "share_gone.html").read_text(encoding="utf-8")
    p = re.search(r"\bp\s*\{\s*color:\s*(#[0-9a-fA-F]{6})", gone).group(1)
    assert _contrast(p, "#0a0a0d") >= 4.5


def test_the_injected_drawer_close_meets_aa_on_bg():
    # /broll injects the dashboard topbar (app.js fetches ../partials/topbar)
    # and styles it only with this stylesheet, so its drawer close control was
    # still --red-dim (1.86:1) after the dashboard's copy moved to --red.
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    tok = dict(re.findall(r"--(bg|red|red-dim|red-hot):\s*(#[0-9a-fA-F]{6})", css))
    rule = re.search(r"\.drawer-close\s*\{[^}]*?color:\s*var\(--([a-z-]+)\)", css)
    assert rule, "no .drawer-close colour rule"
    assert _contrast(tok[rule.group(1)], tok["bg"]) >= 4.5, rule.group(1)
