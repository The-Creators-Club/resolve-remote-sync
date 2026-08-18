"""What the music ingest panel must keep doing, pinned against its own source.

Asserted against the source text for the reason b-roll's `test_ingest_ui.py`
gives: the frontend is vanilla JS with no build step and no test runner in this
repo, and pinning the intent here beats not pinning it at all
(docs/MUSIC_INGEST_PLAN.md step 4).

Four of these are not style checks, they are the bugs this panel can have:

  * **a duplicate global name.** `ingest.js` is a second CLASSIC script, so it
    shares one global lexical environment with `app.js`; a re-declared `const`
    is a SyntaxError that takes the WHOLE page down -- search included, for a
    feature the editor was not even using. Nothing in a browser warns about it
    until it happens.
  * **a one-shot `readEntries`.** It returns at most 100 entries per call in
    Chrome and signals the end of a directory with an empty array, not with a
    short read. Calling it once silently loses every track past the hundredth
    of a sample library.
  * **a lost fallback.** A machine with no companion (or one too old for
    /music/ingest/*) must still be able to add music: the browser upload that
    lands the file in the library and queues it for the base rig is the loop
    this feature replaces, and it is kept.
  * **a hostile page streaming bytes into staging.** The `X-CCSync-Ingest`
    header is what forces a CORS preflight on the octet-stream PUT; without it
    the upload route would be a simple request any origin can make.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / 'static'
INGEST_JS = STATIC / 'ingest.js'
APP_JS = STATIC / 'app.js'
INDEX_HTML = STATIC / 'index.html'
STYLE_CSS = STATIC / 'style.css'

# `function foo(` / `const foo =` / `let foo` at the START of a line: exactly
# what a classic script contributes to the shared global scope.
_TOP_LEVEL = re.compile(
    r"^(?:function\s+([A-Za-z_$][\w$]*)"
    r"|(?:const|let|var)\s+([A-Za-z_$][\w$]*))", re.M)


@pytest.fixture(scope='module')
def js() -> str:
    return INGEST_JS.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def app_js() -> str:
    return APP_JS.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def html() -> str:
    return INDEX_HTML.read_text(encoding='utf-8')


def _top_level_names(text: str) -> set[str]:
    return {m.group(1) or m.group(2) for m in _TOP_LEVEL.finditer(text)}


# --- the shared global scope --------------------------------------------------

def test_ingest_js_declares_no_name_app_js_already_declares(js, app_js):
    clash = _top_level_names(js) & _top_level_names(app_js)
    assert not clash, (
        'two classic scripts share one global lexical environment: a duplicate '
        f'declaration is a SyntaxError that blanks the whole page -- {sorted(clash)}')


def test_both_scripts_are_loaded_and_ingest_comes_second(html):
    app_at = html.index('src="app.js"')
    ingest_at = html.index('src="ingest.js"')
    assert app_at < ingest_at, "ingest.js uses app.js's helpers ($, el, toast, fmtDur)"
    assert 'type="module"' not in html, (
        'a module would not see app.js\'s globals, and there is no build step here')


def test_every_url_in_the_panel_is_document_relative(js, html):
    """The one rule this whole app is built on (tests/test_mounted_prefix.py):
    mounted at /music/, a leading slash resolves against the dashboard's origin
    root. The loopback URLs are the deliberate exception -- they are a
    DIFFERENT process on 127.0.0.1 and go through `COMPANION`."""
    root_relative = re.compile(r"""["'`(]/(?:api|media|static)/""")
    assert not root_relative.search(js)
    assert '`${COMPANION}${path}`' in js, 'every 8899 call goes through one place'
    assert "src=\"ingest.js\"" in html and 'src="/ingest.js"' not in html


@pytest.mark.skipif(shutil.which('node') is None, reason='node not installed')
def test_the_shipped_scripts_parse():
    """`node --check` where node happens to exist. Cheap, and the only thing in
    this repo that would have caught an unbalanced brace before an editor
    did."""
    for path in (APP_JS, INGEST_JS):
        subprocess.run(['node', '--check', str(path)], check=True,
                       capture_output=True, text=True)


# --- the drop, and the fallback it must not eat ------------------------------

def test_the_drop_handler_offers_the_companion_flow_first(app_js):
    """app.js keeps the drop wiring it always had; the companion flow is one
    branch inside it, and `miHandleDrop` answering false is what keeps the old
    NAS-queue upload reachable."""
    body = app_js[app_js.index('function wireDropzone'):]
    body = body[:body.index('\n}\n')]
    assert "typeof miHandleDrop === 'function'" in body
    assert 'await miHandleDrop(e.dataTransfer, files)' in body
    assert 'if (files.length) await ingest(files);' in body, (
        'the browser upload is the documented fallback for a machine with no '
        'companion, not a dead branch')


def test_the_datatransfer_is_read_before_the_first_await(app_js, js):
    """`dt.items`/`dt.files` are neutered the moment either handler yields."""
    caller = app_js[app_js.index("window.addEventListener('drop'"):]
    caller = caller[:caller.index('\n  });')]
    assert caller.index('e.dataTransfer.files') < caller.index('await miHandleDrop')

    body = js[js.index('async function miHandleDrop'):]
    body = body[:body.index('\n}\n')]
    first_await = body.index('await ')
    assert body.index('webkitGetAsEntry') < first_await, (
        'every entry must be taken synchronously first -- reading dt.items after '
        'an await returns nothing in Chrome, which looks like an empty drop')


def test_the_capability_probe_runs_before_anything_is_shown(js):
    """An editor whose companion is off must get the old upload, not a panel
    that then tells them it cannot work."""
    body = js[js.index('async function miHandleDrop'):]
    body = body[:body.index('\n}\n')]
    assert body.index('await miCapabilities(false)') < body.index('miOpen()')
    assert 'if (!mi.caps) return false;' in body


def test_folders_are_traversed_with_readentries_until_it_returns_empty(js):
    assert 'webkitGetAsEntry' in js
    body = js[js.index('async function miWalkEntry'):]
    body = body[:body.index('\n}\n')]
    assert 'for (;;)' in body and 'readEntries' in body, 'one call loses track 101 onwards'
    assert 'if (!chunk.length) break;' in body


def test_the_drop_is_filtered_by_the_servers_own_extension_list(js):
    """`musicweb.ingest_batches.AUDIO_EXTS`, published by
    GET api/ingest-batches/limits -- read, never re-invented."""
    assert "miApi('api/ingest-batches/limits')" in js
    assert 'MI_AUDIO_EXTS_FALLBACK' in js
    for ext in ('.wav', '.mp3', '.flac', '.aac', '.m4a', '.ogg', '.aiff', '.opus'):
        assert f"'{ext}'" in js, ext


def test_the_batch_cap_matches_the_servers(js):
    assert 'const MI_MAX_ITEMS = 500;' in js, 'musicweb.config.MAX_BATCH_ITEMS'


# --- staging, upload, pre-check ----------------------------------------------

def test_uploads_go_two_at_a_time_by_xmlhttprequest(js):
    assert 'const MI_UPLOAD_CONCURRENCY = 2;' in js
    assert 'new XMLHttpRequest()' in js, 'fetch cannot report request-body progress'
    assert 'xhr.upload.onprogress' in js
    assert 'active >= MI_UPLOAD_CONCURRENCY' in js


def test_the_upload_put_carries_the_csrf_header_and_octet_stream(js):
    assert "xhr.open('PUT'" in js
    assert "xhr.setRequestHeader('Content-Type', 'application/octet-stream')" in js
    assert "xhr.setRequestHeader('X-CCSync-Ingest', '1')" in js, (
        'the custom header is what forces the preflight -- without it any origin '
        'could stream bytes into staging')


def test_a_409_on_upload_is_success(js):
    assert 'if (xhr.status === 409) return done(true' in js


def test_the_precheck_sends_what_both_duplicate_defences_need(js):
    """Normalised stem + duration (the only one that can see a re-encode, since
    transcoding changes every byte) AND the whole-file blake2b."""
    body = js[js.index('async function miPrecheck'):]
    body = body[:body.index('\n}\n')]
    assert 'duration: miDuration(it)' in body
    assert 'content_hash: it.hash || null' in body
    assert "miApi('api/ingest-batches/precheck'" in body


def test_duplicates_come_back_unticked_named_and_with_the_reason(js):
    assert 'already in the library as ${item.duplicate_name' in js
    assert 'if (item.duplicate_of && !wasDuplicate) item.include = false;' in js
    assert "n.meta.classList.add('warn')" in js


def test_the_final_name_is_shown(js):
    assert 'will be saved as ${item.final_name}' in js


def test_a_restage_forgets_what_was_uploaded_to_the_old_staging_dir(js):
    body = js[js.index('async function miPrepare'):]
    body = body[:body.index('\n}\n')]
    assert "item.uploaded = item.source === 'path';" in body
    assert 'item.uploadPercent = null;' in body


def test_prepare_waits_for_the_capability_probe_instead_of_giving_up(js):
    body = js[js.index('async function miPrepare'):]
    body = body[:body.index('\n}\n')]
    assert 'if (!mi.caps) await miCapabilities(false);' in body
    assert 'miSetNotice(' in body, 'a silent no-op is a Run button that never enables'


# --- settings and run ---------------------------------------------------------

def test_there_is_no_tier_and_no_shoot_name(js, html):
    """Music has ONE model, and the library is flat: `db.unique_dest` lands
    everything under the share root. A tier picker or a folder field here would
    be a control with nothing behind it."""
    # The CONTROLS, which is what an editor can actually click: the words
    # themselves appear in both files' comments, saying why there are none.
    ids = set(re.findall(r'id="([^"]+)"', html))
    for control in ('mi-tier', 'mi-tiers', 'mi-share', 'mi-keep-subfolders'):
        assert control not in ids, control
    assert 'name="mi-tier"' not in html
    assert 'mi.tier' not in js and 'settings: {run_mode: mi.runMode}' in js


def test_the_run_mode_radio_defaults_to_idle(js, html):
    assert 'value="idle" checked' in html
    assert 'value="foreground"' in html
    assert "runMode: 'idle'" in js
    # The one-line help under each choice.
    assert 'pauses the moment you come back' in html
    assert 'keeps going while you work' in html


def test_the_summary_line_says_when_it_will_run(js):
    body = js[js.index('function miRenderSummary'):]
    body = body[:body.index('\n}\n')]
    assert "'will run now'" in body
    assert '"will run when you\'re away"' in body
    assert "mi.runMode === 'foreground'" in body


def test_an_uncached_model_is_confirmed_with_its_size_before_run(js):
    body = js[js.index('async function miRun'):]
    body = body[:body.index('\n}\n')]
    assert 'clap.cached === false' in body
    assert 'window.confirm(' in body
    assert 'download_bytes' in body, "the editor is told how many bytes, not just 'a model'"


def test_run_creates_the_batch_here_then_hands_the_uid_to_the_companion(js):
    body = js[js.index('async function miRun'):]
    body = body[:body.index('\n}\n')]
    create_at = body.index("miApi('api/ingest-batches'")
    dispatch_at = body.index("'/music/ingest/run'")
    assert create_at < dispatch_at, (
        'the browser must never be the source of a work order: the server mints '
        'the batch, the companion fetches the manifest under the fleet token')
    assert 'batch_uid: created.uid' in body
    assert 'run_mode: mi.runMode' in body


def test_a_refusal_from_run_is_a_persistent_notice_not_a_toast(js):
    body = js[js.index('async function miRun'):]
    body = body[:body.index('\n}\n')]
    assert 'e.status === 503' in body
    assert 'miSetNotice(' in body
    # ...and it names the way out, which for music is the fallback path.
    assert 'let the base rig index them' in body
    notice = js[js.index('function miSetNotice'):]
    notice = notice[:notice.index('\n}\n')]
    assert "classList.toggle('hidden', !mi.notice)" in notice


# --- the live view ------------------------------------------------------------

def test_the_two_poll_intervals_are_the_ones_the_plan_names(js):
    assert 'const MI_LOOPBACK_POLL_MS = 1500;' in js
    assert 'const MI_SERVER_POLL_MS = 5000;' in js
    assert '/music/ingest/progress?staging_id=' in js
    assert '`api/ingest-batches/${encodeURIComponent(mi.batchUid)}`' in js


def test_every_control_button_exists_and_is_wired(js, html):
    for element in ('mi-pause', 'mi-resume', 'mi-start-now',
                    'mi-pause-upload', 'mi-cancel'):
        assert f'id="{element}"' in html, element
        assert f"$('#{element}')" in js, element
    for action in ('pause', 'resume', 'start_now', 'pause_upload', 'resume_upload',
                   'cancel'):
        assert f"'{action}'" in js, action


def test_pausing_uploads_writes_the_durable_server_flag_first(js):
    body = js[js.index('async function miToggleUploadPause'):]
    body = body[:body.index('\n}\n')]
    server_at = body.index('/upload-paused')
    loopback_at = body.index("'/music/ingest/control'")
    assert server_at < loopback_at, (
        "the server's upload_paused is what survives a companion restart; the "
        'loopback call only makes it prompt')


def test_cancel_asks_the_server_and_confirms_first(js):
    body = js[js.index('async function miCancelUid'):]
    body = body[:body.index('\n}\n')]
    assert 'window.confirm(' in body
    assert '/cancel`' in body
    assert 'Tracks already in the library stay there' in body


def test_reopening_the_page_re_attaches_the_running_batch(js):
    """The batch lives in the database, not in this tab: an editor who closed
    the page and came back would otherwise see a batch in the list with no way
    to pause or cancel it -- the "in-memory-only" mistake, in a browser."""
    body = js[js.index('async function miLoadBatches'):]
    body = body[:body.index('\n}\n')]
    assert "['queued', 'claimed', 'running'].includes(b.state)" in body
    assert 'mi.batchUid = live.uid' in body


def test_the_all_machines_tab_appears_only_when_the_server_allows_it(js, html):
    assert 'data-scope="all"' in html
    assert 'class="mode-btn hidden"' in html, 'hidden until the probe succeeds'
    body = js[js.index('async function miProbeAdminScope'):]
    body = body[:body.index('\n}\n')]
    assert "miApi('api/ingest-batches?scope=all')" in body
    assert 'mi.adminAll = false' in body


def test_a_403_on_scope_all_falls_back_to_mine(js):
    body = js[js.index('async function miLoadBatches'):]
    body = body[:body.index('\n}\n')]
    assert "e.status === 403 && mi.scope === 'all'" in body
    assert "mi.scope = 'mine'" in body


# --- the companion-absent state ----------------------------------------------

def test_an_unreachable_companion_uses_the_standard_hint(js):
    assert 'http://127.0.0.1:8899/status' in js, (
        'the /status self-test is the ONLY way to tell a stopped companion from '
        'a browser blocking local-network access')
    assert 'status-dot status-bad' in js and 'status-ok' in js


def test_a_companion_too_old_for_music_ingest_says_so(js):
    """Every /music/ingest route 404s on a build published before this feature.
    Not the same message as "not running", and it names what happens instead."""
    assert 'e.status === 404' in js
    assert 'too old for music ingest' in js
    assert 'indexed on the base rig' in js


# --- theme --------------------------------------------------------------------

def test_the_panel_has_styles_and_ships_no_external_asset(html):
    css = STYLE_CSS.read_text(encoding='utf-8')
    for klass in ('.mi-panel', '.mi-row', '.mi-notice', '.status-dot', '.mode-btn'):
        assert klass in css, klass
    assert 'cdn' not in html.lower()
    for tag in ('<img src="http', '<script src="http', 'href="http'):
        assert tag not in html, tag
