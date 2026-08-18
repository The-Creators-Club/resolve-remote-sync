"""What the ingest panel must keep doing, pinned against its own source.

Asserted against the source text for the same reason `test_filter_state.py` and
`test_detail_view_state.py` are: the frontend is vanilla JS with no build step
and no test runner in this repo, and pinning the intent here beats not pinning
it at all (docs/BROLL_INGEST_PLAN.md §5).

Three of these are not style checks, they are the bugs this panel can have:

  * **a duplicate global name.** `ingest.js` is a second CLASSIC script, so it
    shares one global lexical environment with `app.js`; a re-declared `const`
    is a SyntaxError that takes the WHOLE page down -- search included, for a
    feature the editor was not even using. Nothing in a browser warns about it
    until it happens.
  * **a one-shot `readEntries`.** It returns at most 100 entries per call in
    Chrome and signals the end of a directory with an empty array, not with a
    short read. Calling it once silently loses every clip past the hundredth of
    a camera card -- silently, because the drop still "works".
  * **a hostile page streaming bytes into staging.** The `X-CCSync-Ingest`
    header is what forces a CORS preflight on the octet-stream PUT (plan §4.1);
    without it the upload route would be a simple request any origin can make.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "static"
INGEST_JS = STATIC / "ingest.js"
APP_JS = STATIC / "app.js"
INDEX_HTML = STATIC / "index.html"
STYLE_CSS = STATIC / "style.css"

# `function foo(` / `const foo =` / `let foo` at the START of a line: exactly
# what a classic script contributes to the shared global scope.
_TOP_LEVEL = re.compile(
    r"^(?:function\s+([A-Za-z_$][\w$]*)"
    r"|(?:const|let|var)\s+([A-Za-z_$][\w$]*))", re.M)


@pytest.fixture(scope="module")
def js() -> str:
    return INGEST_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def html() -> str:
    return INDEX_HTML.read_text(encoding="utf-8")


def _top_level_names(text: str) -> set[str]:
    return {m.group(1) or m.group(2) for m in _TOP_LEVEL.finditer(text)}


# --- the shared global scope --------------------------------------------------

def test_ingest_js_declares_no_name_app_js_already_declares(js):
    clash = _top_level_names(js) & _top_level_names(APP_JS.read_text(encoding="utf-8"))
    assert not clash, (
        "two classic scripts share one global lexical environment: a duplicate "
        f"declaration is a SyntaxError that blanks the whole page -- {sorted(clash)}"
    )


def test_both_scripts_are_loaded_and_ingest_comes_second(html):
    app_at = html.index('src="static/app.js"')
    ingest_at = html.index('src="static/ingest.js"')
    assert app_at < ingest_at, "ingest.js uses app.js's helpers ($, el, toast, fetchJson)"
    assert 'type="module"' not in html, (
        "a module would not see app.js's globals, and there is no build step here"
    )


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_shipped_scripts_parse():
    """`node --check` where node happens to exist. Cheap, and the only thing in
    this repo that would have caught an unbalanced brace before an editor did."""
    for path in (APP_JS, INGEST_JS):
        subprocess.run(["node", "--check", str(path)], check=True,
                       capture_output=True, text=True)


# --- the drop (plan §5) -------------------------------------------------------

def test_the_drop_zone_is_the_window_with_a_depth_counter(js):
    for event in ("dragenter", "dragover", "dragleave", "drop"):
        assert f'window.addEventListener("{event}"' in js, event
    assert "depth++" in js and "Math.max(0, depth - 1)" in js, (
        "dragenter/dragleave fire per element crossed, so a counter is the only "
        "way the veil does not flicker (music's wireDropzone pattern)"
    )


def test_a_drop_opens_the_panel(js):
    assert "if (!ing.open) ingestOpen();" in js


def test_folders_are_traversed_with_readentries_until_it_returns_empty(js):
    assert "webkitGetAsEntry" in js
    body = js[js.index("async function ingestWalkEntry"):]
    body = body[:body.index("\n}")]
    assert "for (;;)" in body and "readEntries" in body, "one call loses clip 101 onwards"
    assert "if (!chunk.length) break;" in body


def test_the_datatransfer_is_read_before_the_first_await(js):
    """`dt.items` is neutered the moment the handler yields."""
    body = js[js.index("async function ingestCollect"):]
    body = body[:body.index("\n}")]
    first_await = body.index("await ")
    assert body.index("webkitGetAsEntry") < first_await, (
        "every entry must be taken synchronously first -- reading dt.items after "
        "an await returns nothing in Chrome, which looks like an empty drop"
    )


def test_rel_dir_drops_the_top_folder(js):
    body = js[js.index("function ingestRelDir"):]
    body = body[:body.index("\n}")]
    assert "parts.pop()" in body, "the file itself is not part of rel_dir"
    assert "parts.shift()" in body


def test_the_drop_is_filtered_by_the_shared_video_extension_list(js):
    """`provision.VIDEO_EXTENSIONS`, published as `video_extensions` by
    GET /api/v1/site -- read, never re-invented (COMMERCIAL_READINESS item 11)."""
    assert "site.video_extensions" in js
    assert "ING_VIDEO_EXTS_FALLBACK" in js
    for ext in (".braw", ".mov", ".mp4", ".mxf", ".r3d"):
        assert f'"{ext}"' in js, ext


def test_the_batch_cap_matches_the_servers(js):
    assert "const ING_MAX_ITEMS = 2000;" in js, "schemas.MAX_BATCH_ITEMS"


# --- thumbnails ---------------------------------------------------------------

def test_thumbnails_seek_a_tenth_in_capped_at_one_second(js):
    assert "const ING_THUMB_SEEK_FRACTION = 0.1;" in js
    assert "const ING_THUMB_SEEK_MAX = 1;" in js
    assert "Math.min(ING_THUMB_SEEK_MAX, duration * ING_THUMB_SEEK_FRACTION)" in js


def test_thumbnails_are_drawn_on_a_160x90_canvas_two_at_a_time(js):
    assert "const ING_THUMB_W = 160;" in js and "const ING_THUMB_H = 90;" in js
    assert "const ING_THUMB_CONCURRENCY = 2;" in js
    assert 'toDataURL("image/jpeg"' in js
    assert "ing.thumbActive < ING_THUMB_CONCURRENCY" in js


def test_an_undecodable_clip_says_no_preview_until_the_companion_thumb_arrives(js):
    assert '"no preview"' in js
    assert "/broll/ingest/thumb?staging_id=" in js


# --- staging, upload, pre-check ----------------------------------------------

def test_uploads_go_two_at_a_time_by_xmlhttprequest(js):
    assert "const ING_UPLOAD_CONCURRENCY = 2;" in js
    assert "new XMLHttpRequest()" in js, "fetch cannot report request-body progress"
    assert "xhr.upload.onprogress" in js
    assert "active >= ING_UPLOAD_CONCURRENCY" in js


def test_the_upload_put_carries_the_csrf_header_and_octet_stream(js):
    assert 'xhr.open("PUT"' in js
    assert 'xhr.setRequestHeader("Content-Type", "application/octet-stream")' in js
    assert 'xhr.setRequestHeader("X-CCSync-Ingest", "1")' in js, (
        "the custom header is what forces the preflight -- without it any origin "
        "could stream bytes into staging (plan §4.1)"
    )


def test_a_409_on_upload_is_success(js):
    assert "if (xhr.status === 409) return done(true" in js


def test_duplicates_come_back_unticked_and_named(js):
    assert "already in the archive — clip #" in js
    assert "if (item.duplicate_of && !wasDuplicate) item.include = false;" in js


def test_the_final_name_is_shown(js):
    assert "will be saved as ${item.final_name}" in js


# --- the settings form --------------------------------------------------------

def test_the_default_tier_comes_from_the_site_manifest(js):
    assert 'fetchJson("../api/v1/site")' in js
    assert "site.indexer.model_tier" in js
    assert 'siteTier: "good"' in js, "fallback when the manifest cannot be read"


def test_a_tier_that_does_not_fit_is_disabled_with_the_reason(js):
    body = js[js.index("function ingestRenderTiers"):]
    body = body[:body.index("\n}\n")]
    assert "radio.disabled = !fits" in body
    assert "info.reason" in body, "a greyed-out option with no reason is a bug"


def test_the_run_mode_radio_defaults_to_idle(js, html):
    assert 'value="idle" checked' in html
    assert 'value="foreground"' in html
    assert 'runMode: "idle"' in js
    # The one-line help under each choice (owner review, plan §0).
    assert "pauses the moment you come back" in html
    assert "keeps going while you work" in html


def test_transcription_is_present_but_disabled(js, html):
    assert "Transcribe speech" in html
    assert "phase 2" in html
    assert "transcribe: false" in js, "the server 422s on a true (plan §4.3)"


def test_the_shoot_name_is_sanitised_like_archive_names_safe_name(js):
    assert 'const ING_UNSAFE = /[<>:"/\\\\|?*\\x00-\\x1f]/g;' in js
    assert "const ING_MAX_STEM = 90;" in js
    body = js[js.index("function ingestSafeName"):]
    body = body[:body.index("\n}")]
    assert "replace(ING_UNSAFE" in body and "ING_MAX_STEM" in body


def test_the_default_shoot_name_is_the_folder_or_a_dated_ingest(js):
    body = js[js.index("function ingestSuggestShare"):]
    body = body[:body.index("\n}")]
    assert "${stamp} ingest" in body
    assert "folderName ||" in body


def test_the_summary_line_says_when_it_will_run(js):
    """"N clips, X GB — will run when you're away" (plan §5). The mode has to be
    IN the sentence: an editor who chose Foreground and read "when you're away"
    would walk off, and one who chose idle and read "now" would sit and wait."""
    body = js[js.index("function ingestRenderSummary"):]
    body = body[:body.index("\n}")]
    assert '"will run now"' in body
    assert '"will run when you\'re away"' in body
    assert 'ing.runMode === "foreground"' in body
    assert "ingestBytes(bytes)" in body


def test_an_uncached_model_is_confirmed_with_its_size_before_run(js):
    body = js[js.index("async function ingestRun"):]
    body = body[:body.index("\n}\n")]
    assert "info.cached === false" in body
    assert "window.confirm(" in body
    assert "download_bytes" in body, "the editor is told how many bytes, not just 'a model'"


# --- run, live view, controls -------------------------------------------------

def test_run_creates_the_batch_here_then_hands_the_uid_to_the_companion(js):
    body = js[js.index("async function ingestRun"):]
    body = body[:body.index("\n}\n")]
    create_at = body.index('fetchJson("api/ingest-batches"')
    dispatch_at = body.index('"/broll/ingest/run"')
    assert create_at < dispatch_at, (
        "the browser must never be the source of a work order: the server mints "
        "the batch, the companion fetches the manifest under the fleet token"
    )
    assert "batch_uid: created.uid" in body
    assert "run_mode: ing.runMode" in body
    assert "start_now: ing.runMode === \"foreground\"" in body


def test_a_vram_refusal_is_a_persistent_notice_not_a_toast(js):
    body = js[js.index("async function ingestRun"):]
    body = body[:body.index("\n}\n")]
    assert "e.status === 503" in body
    assert "ingestSetNotice(" in body, (
        "a 503 from run names the VRAM the tier needs and the VRAM this GPU has "
        "-- it has to still be on screen when the editor comes back to change it"
    )
    notice = js[js.index("function ingestSetNotice"):]
    notice = notice[:notice.index("\n}")]
    assert "classList.toggle(\"hidden\", !ing.notice)" in notice


def test_the_two_poll_intervals_are_the_ones_the_plan_names(js):
    assert "const ING_LOOPBACK_POLL_MS = 1500;" in js
    assert "const ING_SERVER_POLL_MS = 5000;" in js
    assert "/broll/ingest/progress?staging_id=" in js
    assert "`api/ingest-batches/${encodeURIComponent(ing.batchUid)}`" in js


def test_every_control_button_exists_and_is_wired(js, html):
    for element in ("ingest-pause", "ingest-resume", "ingest-start-now",
                    "ingest-pause-upload", "ingest-cancel"):
        assert f'id="{element}"' in html, element
        assert f'$("#{element}")' in js, element
    for action in ("pause", "resume", "start_now", "pause_upload", "resume_upload",
                   "cancel"):
        assert f'"{action}"' in js, action


def test_pausing_uploads_writes_the_durable_server_flag_first(js):
    body = js[js.index("async function ingestToggleUploadPause"):]
    body = body[:body.index("\n}\n")]
    server_at = body.index("/upload-paused")
    loopback_at = body.index('"/broll/ingest/control"')
    assert server_at < loopback_at, (
        "the server's upload_paused is what survives a companion restart and "
        "what the fleet halt sets; the loopback call only makes it prompt"
    )


def test_cancel_asks_the_server_and_confirms_first(js):
    body = js[js.index("async function ingestCancelUid"):]
    body = body[:body.index("\n}\n")]
    assert "window.confirm(" in body
    assert "/cancel`" in body
    assert "Clips already in the archive stay there" in body


def test_reopening_the_page_re_attaches_the_running_batch(js):
    """The live view and its buttons must come back after a reload.

    The batch lives in the database, not in this tab: an editor who closed the
    page and came back would otherwise see a batch in the list with no way to
    pause or cancel it, which is the "in-memory-only" mistake in a browser
    (docs/SYNC_SAFETY.md's rule, one layer up).
    """
    body = js[js.index("async function ingestLoadBatches"):]
    body = body[:body.index("\n}\n")]
    assert '["queued", "claimed", "running"].includes(b.state)' in body
    assert "ing.batchUid = live.uid" in body


def test_prepare_waits_for_the_capability_probe_instead_of_giving_up(js):
    """A drop opens the panel, so the probe and the prepare debounce race."""
    body = js[js.index("async function ingestPrepare"):]
    body = body[:body.index("\n}\n")]
    assert "if (!ing.caps) await ingestCapabilities(false);" in body
    assert "ingestSetNotice(" in body, "a silent no-op is a Run button that never enables"


def test_a_restage_forgets_what_was_uploaded_to_the_old_staging_dir(js):
    body = js[js.index("async function ingestPrepare"):]
    body = body[:body.index("\n}\n")]
    assert 'item.uploaded = item.source === "path";' in body
    assert "item.uploadPercent = null;" in body


# --- the batch list -----------------------------------------------------------

def test_the_all_machines_tab_appears_only_when_the_server_allows_it(js, html):
    assert 'data-scope="all"' in html
    assert 'class="mode-btn hidden"' in html, "hidden until the probe succeeds"
    body = js[js.index("async function ingestProbeAdminScope"):]
    body = body[:body.index("\n}\n")]
    assert 'fetchJson("api/ingest-batches?scope=all")' in body
    assert "ing.adminAll = false" in body
    assert "classList.toggle(\"hidden\", !ing.adminAll)" in body


def test_a_403_on_scope_all_falls_back_to_mine(js):
    body = js[js.index("async function ingestLoadBatches"):]
    body = body[:body.index("\n}\n")]
    assert 'e.status === 403 && ing.scope === "all"' in body
    assert 'ing.scope = "mine"' in body


def test_the_batch_list_shows_machine_heartbeat_and_counts(js):
    body = js[js.index("function ingestRenderBatches"):]
    body = body[:body.index("\n}\n")]
    assert "batch.machine" in body and "no machine yet" in body
    assert "ingestAgo(batch.last_heartbeat_at)" in body
    for counter in ("n_done", "n_items", "n_live", "n_failed", "n_duplicate"):
        assert counter in body, counter


# --- the companion-absent state ----------------------------------------------

def test_an_unreachable_companion_uses_the_standard_hint(js):
    assert "http://127.0.0.1:8899/status" in js, (
        "the /status self-test is the ONLY way to tell a stopped companion from "
        "a browser blocking local-network access (2026-08-12)"
    )
    assert "status-dot status-bad" in js and "status-ok" in js


def test_a_companion_too_old_for_ingest_says_so(js):
    """Every /broll/ingest route 404s on a build published before this feature --
    the same gap /music/* had. Not the same message as "not running"."""
    assert "e.status === 404" in js
    assert "too old for b-roll ingest" in js


# --- theme --------------------------------------------------------------------

def test_the_panel_carries_the_dashboards_checkbox_and_radio_paint():
    css = STYLE_CSS.read_text(encoding="utf-8")
    assert 'input[type="checkbox"] {' in css and 'input[type="radio"] {' in css
    assert "appearance: none;" in css
    assert 'input[type="checkbox"]:focus-visible' in css, "Tab + Space must be visible"
    assert "data:image/svg+xml" in css, "the check mark is inline -- no external asset"


def test_the_panel_ships_no_external_asset(html):
    assert "cdn" not in html.lower()
    for tag in ("<img src=\"http", "<script src=\"http", 'href="http'):
        assert tag not in html, tag


# --- the one place this file runs the JS instead of reading it ---------------

# ingest.js touches the DOM only inside functions and one DOMContentLoaded
# registration, so a two-property stub is enough to load it in a bare V8 and
# call a pure function out of it. That buys a REAL parity check against the
# server's own sanitiser, which no amount of source-reading can give.
_NODE_HARNESS = """
const fs = require('fs'), vm = require('vm');
const ctx = {document: {addEventListener() {}}, window: {}, console};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
const cases = JSON.parse(process.argv[3]);
console.log(JSON.stringify(cases.map(
    c => vm.runInContext('ingestSafeName(' + JSON.stringify(c) + ')', ctx))));
"""

_SAFE_NAME_CASES = [
    "A001_C003",
    "2026/07 shoot",              # a slash would be a second directory level
    "back\\slash",
    '<>:"|?*bad',                 # exactly what Windows forbids, and only that
    "中文素材",                     # must survive intact -- the archive is full of these
    "a" * 120,                    # MAX_STEM
    "trailing dots... ",
]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_pages_shoot_name_sanitiser_matches_the_servers(tmp_path):
    """`ingestSafeName` must agree with `archive_names.safe_name`.

    It is a COURTESY, not the check -- routes_batches._validated_share refuses
    anything else with a 422 naming the name it wanted. But an editor who has
    just staged 40 GB should not meet that 422, and the two implementations
    drifting is how they would: the same shoot would be legal while typing and
    illegal on Run.

    The empty string is the one deliberate divergence and is excluded: Python
    answers "untitled" (a name must exist by the time a folder is made), while
    an empty field stays empty here so the caret is not fighting the editor --
    Run is disabled until they type something, so "" never reaches the server.
    """
    from app.archive_names import safe_name

    harness = tmp_path / "harness.js"
    harness.write_text(_NODE_HARNESS, encoding="utf-8")
    done = subprocess.run(
        ["node", str(harness), str(INGEST_JS), json.dumps(_SAFE_NAME_CASES)],
        capture_output=True, text=True, encoding="utf-8", check=True)
    assert json.loads(done.stdout) == [safe_name(c) for c in _SAFE_NAME_CASES]
