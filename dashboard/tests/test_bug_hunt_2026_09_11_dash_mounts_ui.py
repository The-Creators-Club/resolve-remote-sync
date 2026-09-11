"""The dash-mounts-ui half of the 2026-09-11 bug hunt (CR-243).

One file per finding id, and every test here fails at 40f931a:

  -1  /help served the whole internal docs tree to any signed-in editor, and
      all three shipping routes put it on a customer's server to begin with.
  -2  "safe to close" is computed for the PERSON and was worded per computer.
  -3  run.sh recorded `ok: true` for an unblock install it never performed.
  -4  CI gated a release on one of the seven installer test scripts.
  -5  a same-version redeploy left every installed phone on the old static.
  -6  the uid warning was dead in bind-mount mode, where it is needed.
  -7  the refusal banner's "move it to the button" could be stolen by a poll.
  -8  select_code_root counted a boot against a tree it never booted.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, help as help_page, published_docs, ui
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

REPO = Path(__file__).resolve().parents[2]
SECRET = "test-secret-value-hunt-0911-1234567890"


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                              admin_users=frozenset({"owen"})))
    with TestClient(app) as c:
        yield c


def as_user(client, user="jsmith"):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


@pytest.fixture
def docs(tmp_path, monkeypatch):
    """A docs tree of the shape a DEV CHECKOUT has: the customer-facing
    documents and the internal ones side by side."""
    root = tmp_path / "app" / "docs"
    (root / "legal").mkdir(parents=True)
    (root / "spikes").mkdir()
    (root / "_root").mkdir()
    (root / "HOW_IT_WORKS.md").write_text("# How CC Sync works\n", encoding="utf-8")
    (root / "EDITOR_SETUP.md").write_text("# Editor setup\n", encoding="utf-8")
    (root / "GOTCHAS.md").write_text("# Gotchas\n", encoding="utf-8")
    (root / "SECRETS.md").write_text("# Secrets\n", encoding="utf-8")
    (root / "legal" / "EULA.md").write_text("# Licence\n", encoding="utf-8")
    (root / "spikes" / "s1.md").write_text("# S1\n", encoding="utf-8")
    (root / "_root" / "KNOWN_BUGS.md").write_text("# Known bugs\n", encoding="utf-8")
    (root / "_root" / "CLAUDE.md").write_text("# Claude\n", encoding="utf-8")
    monkeypatch.setattr(help_page, "_root_candidates", lambda: [root])
    monkeypatch.setattr(help_page, "_candidates", lambda: [root / "HOW_IT_WORKS.md"])
    return root


# --------------------------------------------------------------- finding 1


def test_an_editor_cannot_read_the_internal_documents(docs):
    """The one that mattered: a `.md` under the docs root was served to
    anybody with a session, so an editor at a second customer could read the
    defect ledger, CLAUDE.md and the secrets runbook."""
    for rel in ("GOTCHAS.md", "SECRETS.md", "spikes/s1.md",
                "_root/KNOWN_BUGS.md", "_root/CLAUDE.md"):
        assert help_page.resolve_document(rel) is None, rel
        assert help_page.read_rel(rel) is None, rel


def test_an_editor_still_gets_the_customer_facing_documents(docs):
    for rel in ("HOW_IT_WORKS.md", "EDITOR_SETUP.md", "legal/EULA.md"):
        assert help_page.resolve_document(rel) is not None, rel


def test_the_admin_on_a_dev_checkout_still_reads_everything(docs):
    """The 2026-09-04 ask survives where it was aimed: the base rig. On a
    customer's server the shipping routes carry nothing else, so this branch
    finds nothing extra there."""
    assert help_page.resolve_document("GOTCHAS.md", True) is not None
    assert help_page.resolve_document("_root/KNOWN_BUGS.md", True) is not None


def test_the_index_lists_only_what_this_reader_may_open(docs):
    editor_rels = [e["rel"] for g in help_page.document_groups() for e in g["entries"]]
    assert sorted(editor_rels) == ["EDITOR_SETUP.md", "HOW_IT_WORKS.md",
                                   "legal/EULA.md"]
    admin_rels = [e["rel"] for g in help_page.document_groups(True) for e in g["entries"]]
    assert "GOTCHAS.md" in admin_rels and "_root/KNOWN_BUGS.md" in admin_rels


def test_the_route_refuses_an_editor_and_serves_an_admin(client, docs):
    """The route has no gate of its own - help.resolve_document is where a
    path from a URL is checked - so this is the end-to-end proof."""
    refused = as_user(client).get("/help/GOTCHAS.md")
    assert refused.status_code == 404
    assert "Gotchas" not in refused.text
    allowed = as_user(client, "owen").get("/help/GOTCHAS.md")
    assert allowed.status_code == 200
    assert "Gotchas" in allowed.text
    # ...and the guide is still the guide for everybody.
    assert as_user(client).get("/help/HOW_IT_WORKS.md").status_code == 200


def test_the_page_context_defaults_to_the_customer_facing_set(docs):
    """An audience gate that fails open is not a gate: a caller that forgets
    the flag gets the narrow answer."""
    context = help_page.page_context("SECRETS.md")
    assert context["help_not_found"] and context["help_html"] == ""


def test_the_three_shipping_routes_agree_with_the_one_list():
    """The image, the OTA bundle and the bind-mode deploy are built from
    published_docs.py. A Dockerfile cannot import it, so the Dockerfile and
    .dockerignore restate the list and this test is the seam."""
    files, trees = published_docs.published_sources()
    assert files and trees

    dockerfile = (REPO / "dashboard" / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    copied = [line for line in dockerfile.splitlines()
              if line.startswith("COPY ") and "/app/docs" in line]
    copied_sources = {src for line in copied for src in line.split()[1:-1]}
    # The two COPY lines that carried the whole tree (`docs` and `*.md` into
    # `_root/`) are gone by construction: this set is exactly the one list.
    assert copied_sources == set(files) | set(trees), copied

    ignore = (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines()
    reincluded = {line.strip() for line in ignore if line.strip().startswith("!docs")}
    assert reincluded == ({f"!{name}" for name in files}
                          | {f"!{name}/*.md" for name in trees}), reincluded

    sys.path.insert(0, str(REPO / "tools"))
    try:
        import build_dashboard_bundle as bundle
    finally:
        sys.path.pop(0)
    packed = {name for name, _ in bundle.collect_files(REPO) if name.startswith("docs/")}
    assert all(any(name == f or name.startswith(t + "/") for f in files for t in trees)
               for name in packed), sorted(packed)[:10]
    for name in ("docs/KNOWN_BUGS.md", "docs/_root/KNOWN_BUGS.md",
                 "docs/_root/CLAUDE.md", "docs/SECRETS.md", "docs/PRODUCT_REPO.md"):
        assert name not in packed, name
    assert bundle.ROOT_DOCS == ()


def test_no_bug_hunt_or_plan_document_is_published():
    """The list is a decision, not a filter, so this is the decision written
    down: an incident ledger, a plan or a sweep report must never be on it."""
    names = list(published_docs.PUBLISHED_DOCS)
    for name in names:
        lowered = name.lower()
        for banned in ("known_bugs", "claude", "spec", "secrets", "product_repo",
                       "bug-hunt", "sweep", "_plan", "commercial"):
            assert banned not in lowered, name
    assert published_docs.ROOT_DOCS == ()


# --------------------------------------------------------------- finding 2


def test_safe_to_close_names_the_machine_it_is_talking_about():
    view = {"transfers": [{"editor": "alex", "machine": "DESKTOP", "direction": "up",
                           "bytes_total": 1000, "bytes_done": 100, "speed_bps": 0}],
            "queues": []}
    out = ui.safe_to_close(view, "alex")
    assert out["safe"] is False
    assert "DESKTOP" in out["sentence"]
    # The sentence must not claim to know which computer the browser is on.
    assert "this computer" not in out["sentence"]


def test_safe_to_close_names_every_machine_that_owes_an_upload():
    view = {"transfers": [], "queues": [
        {"editor": "alex", "machine": "DESKTOP", "direction": "up",
         "n_files": 3, "bytes": 30},
        {"editor": "alex", "machine": "LAPTOP", "direction": "up",
         "n_files": 1, "bytes": 10},
    ]}
    out = ui.safe_to_close(view, "alex")
    assert "DESKTOP" in out["sentence"] and "LAPTOP" in out["sentence"]
    assert "those computers" in out["sentence"]


def test_the_safe_sentence_does_not_claim_a_computer_either():
    view = {"transfers": [], "queues": [
        {"editor": "alex", "machine": "DESKTOP", "direction": "down",
         "n_files": 2, "bytes": 20}]}
    out = ui.safe_to_close(view, "alex")
    assert out["safe"] is True
    assert "this computer" not in out["sentence"]


# --------------------------------------------------------------- finding 3

# The harness is test_run_sh_restart_loop's: a rewritten run.sh executed by a
# real `sh` against stub pip/python. Reused rather than copied, so a change to
# the boot script's shape is felt in one place.
from test_run_sh_restart_loop import build_world, run  # noqa: E402


@pytest.mark.skipif(shutil.which("sh") is None, reason="no POSIX sh on this machine")
def test_a_wiped_plugin_is_reinstalled_rather_than_marked_ok(tmp_path):
    """The stamp and the artefact are two different paths. With the stamp
    matching and `unblock-site` emptied, run.sh used to skip the install and
    write `ok: true, attempts: 0` for something it had never done, so
    /ytdl's health route reported the PO-token provider installed while every
    server download crawled the throttled HLS ladder."""
    world = build_world(tmp_path, image_mode=True, exits=["0"])
    import hashlib
    lock = world["app"] / "deploy" / "requirements-unblock.lock"
    (world["data"] / ".requirements-unblock-hash").write_text(
        hashlib.md5(lock.read_bytes()).hexdigest())
    site = world["data"] / "unblock-site"
    site.mkdir(parents=True, exist_ok=True)   # present, and EMPTY

    proc = run(world, DASH_SITE_YOUTUBE_UNBLOCK="1")
    assert proc.returncode == 0, proc.stderr
    pip_calls = world["pip_log"].read_text().splitlines()
    assert len(pip_calls) == 1, ("the install was skipped on the stamp alone", pip_calls)
    marker = [c for c in world["log"].read_text().splitlines() if c.startswith("MARKER ")]
    # One marker, from the install that actually ran (attempts=1), never the
    # attempts=0 backfill that asserted success on no evidence.
    assert marker and "attempts=1" in marker[-1], marker


@pytest.mark.skipif(shutil.which("sh") is None, reason="no POSIX sh on this machine")
def test_a_present_plugin_with_a_matching_stamp_still_backfills_the_marker(tmp_path):
    """The YTWEB-5 backfill is kept where it is honest: the stamp matches AND
    the plugin is on disk, so "installed" is a check we have made."""
    world = build_world(tmp_path, image_mode=True, exits=["0"])
    import hashlib
    lock = world["app"] / "deploy" / "requirements-unblock.lock"
    (world["data"] / ".requirements-unblock-hash").write_text(
        hashlib.md5(lock.read_bytes()).hexdigest())
    (world["data"] / "unblock-site" / "yt_dlp_plugins").mkdir(parents=True)

    proc = run(world, DASH_SITE_YOUTUBE_UNBLOCK="1")
    assert proc.returncode == 0, proc.stderr
    assert not world["pip_log"].exists() or not world["pip_log"].read_text().strip()
    marker = [c for c in world["log"].read_text().splitlines() if c.startswith("MARKER ")]
    assert marker and "ok=1" in marker[0] and "attempts=0" in marker[0], marker


# --------------------------------------------------------------- finding 4


def test_ci_runs_every_installer_script_by_enumerating_them():
    """`ls installer/tests/*.ps1` is the list, and CI named one of the seven.
    publish_latest.py publishes the newest GREEN CI run, so the glob is what
    makes a green run evidence about all of them - including the licence gate
    and the previous-install rollback."""
    text = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "installer/tests/*.ps1" in text
    assert "LASTEXITCODE" in text, "a bare foreach in pwsh fails nothing"
    # No script may be named: a name is a list that goes stale (this comment
    # has now been wrong twice in run_all_tests.ps1 for the same reason).
    for script in sorted((REPO / "installer" / "tests").glob("*.ps1")):
        assert f"-File installer/tests/{script.name}" not in text, script.name


# --------------------------------------------------------------- finding 5

NODE = shutil.which("node")

SW_HARNESS = r"""
const fs = require('fs'), vm = require('vm'), path = process.argv[2];
let handlers = {}, fetched = [], put = [];
function FakeResponse(body) { this.body = body; this.ok = true; this.type = 'basic';
  this.clone = function () { return this; }; }
const cacheStore = { 'ccsync-x': {} };
const sandbox = {
  console,
  self: {
    addEventListener: function (n, fn) { handlers[n] = fn; },
    location: { origin: 'https://nas.example' },
    skipWaiting: function () { return Promise.resolve(); },
    clients: { claim: function () { return Promise.resolve(); } }
  },
  caches: {
    open: function () { return Promise.resolve({
      add: function () { return Promise.resolve(); },
      put: function (req, res) { put.push(req.url); return Promise.resolve(); }
    }); },
    keys: function () { return Promise.resolve([]); },
    match: function (req) {
      const url = (req && req.url) || req;
      return Promise.resolve(url.indexOf('/static/style.css') >= 0
        ? new FakeResponse('CACHED') : undefined);
    }
  },
  fetch: function (req) { fetched.push(req.url); return Promise.resolve(new FakeResponse('NETWORK')); },
  Request: function (url) { this.url = url; },
  Response: function (body) { this.body = body; },
  URL: URL
};
sandbox.globalThis = sandbox;
vm.runInNewContext(fs.readFileSync(path, 'utf8').replace(/__VERSION__/g, 'x'), sandbox);
let answered = null;
const event = {
  request: { method: 'GET', url: 'https://nas.example/static/style.css', mode: 'no-cors' },
  respondWith: function (p) { answered = p; }
};
handlers['fetch'](event);
Promise.resolve(answered).then(function (res) {
  setTimeout(function () {
    console.log(JSON.stringify({ served: res && res.body, fetched: fetched, put: put }));
  }, 10);
});
"""


@pytest.mark.skipif(NODE is None, reason="no node on this machine")
def test_a_cached_static_asset_is_revalidated_in_the_background(tmp_path):
    """Cache-first with no revalidation meant a CSS or JS change shipped under
    an unchanged VERSION never reached an installed phone: the worker's own
    bytes are what invalidate the cache, and they had not changed. The cached
    copy is still what the phone paints - offline is when it matters most -
    but the network copy replaces it for the next load."""
    harness = tmp_path / "sw_harness.js"
    harness.write_text(SW_HARNESS, encoding="utf-8")
    out = subprocess.run(
        [NODE, str(harness), str(REPO / "dashboard" / "static" / "sw.js")],
        capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["served"] == "CACHED", result
    assert any("style.css" in u for u in result["fetched"]), result
    assert any("style.css" in u for u in result["put"]), result


# --------------------------------------------------------------- finding 6


def test_the_uid_warning_works_without_app_uid_in_the_environment():
    """APP_UID is in the container's environment in IMAGE mode only, so the
    warning written for COMMERCIAL_READINESS item 12 never fired on the
    bind-mount deployments it was written for."""
    text = (REPO / "dashboard" / "deploy" / "run.sh").read_text(encoding="utf-8")
    block = text.split("REQS=", 1)[0]
    assert "stat -c %u /data" in block
    assert 'expected_uid="${APP_UID:-}"' in block
    assert '[ -n "${APP_UID:-}" ] && [ "$(id -u)" != "$APP_UID" ]' not in block


# --------------------------------------------------------------- finding 7

HTMX_HARNESS = r"""
const fs = require('fs'), vm = require('vm'), path = process.argv[2];
let handlers = {};
function elt(attrs) {
  return {
    attrs: attrs || {},
    getAttribute: function (n) { return this.attrs[n] === undefined ? null : this.attrs[n]; },
    classList: { add: function () { } },
    closest: function () { return null; },
    hasAttribute: function () { return true; },
    setAttribute: function () { },
    parentNode: null
  };
}
function panel(formPath) {
  const banner = elt({}); banner.className = 'error-banner';
  banner.scrollIntoView = function () { };
  const form = elt({ 'hx-post': formPath });
  const moved = [];
  form.parentNode = { insertBefore: function (b, f) { moved.push(f.attrs['hx-post']); } };
  return {
    moved: moved,
    querySelector: function (sel) { return sel === '.error-banner' ? banner : null; },
    querySelectorAll: function () { return [form]; }
  };
}
const sandbox = {
  console, WeakMap: WeakMap, Date: Date, Math: Math,
  setInterval: function () { return 0; }, clearInterval: function () { },
  setTimeout: function () { return 0; },
  window: { addEventListener: function () { } },
  document: {
    addEventListener: function (n, fn) { (handlers[n] = handlers[n] || []).push(fn); },
    getElementById: function () { return null; },
    createElement: function () { return { setAttribute: function () { }, style: {} }; },
    body: { appendChild: function () { }, dataset: {} },
    activeElement: null
  }
};
sandbox.globalThis = sandbox;
vm.runInNewContext(fs.readFileSync(path, 'utf8'), sandbox);
function fire(name, detail) { (handlers[name] || []).forEach(function (fn) { fn({ detail: detail }); }); }

// The click on [ DELETE ], then a POLL settling before the write's own swap.
const button = elt({ 'hx-post': '/admin/packages/40/delete' });
const writeXhr = {};
fire('htmx:beforeRequest', { elt: button, xhr: writeXhr });
const pollXhr = {};
fire('htmx:beforeRequest', { elt: elt({ 'hx-get': '/partials/fleet' }), xhr: pollXhr });
const pollPanel = panel('/partials/fleet');
fire('htmx:afterSwap', { target: pollPanel, xhr: pollXhr,
                         requestConfig: { elt: elt({ 'hx-get': '/partials/fleet' }) } });
const writePanel = panel('/admin/packages/40/delete');
fire('htmx:afterSwap', { target: writePanel, xhr: writeXhr,
                         requestConfig: { elt: button } });
console.log(JSON.stringify({ poll: pollPanel.moved, write: writePanel.moved }));
"""


@pytest.mark.skipif(NODE is None, reason="no node on this machine")
def test_a_poll_settling_first_does_not_steal_the_refusal(tmp_path):
    """One module-level slot meant the NEXT swap consumed it, whichever
    element it belonged to - and the fleet grid polls every 15 s. The banner
    then stayed two thousand pixels above the viewport: DUI-6 again."""
    harness = tmp_path / "htmx_harness.js"
    harness.write_text(HTMX_HARNESS, encoding="utf-8")
    out = subprocess.run(
        [NODE, str(harness), str(REPO / "dashboard" / "static" / "htmx_errors.js")],
        capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["poll"] == [], result
    assert result["write"] == ["/admin/packages/40/delete"], result


# --------------------------------------------------------------- finding 8


def test_a_refused_tree_is_not_counted_as_a_failed_boot(tmp_path, monkeypatch):
    """The counter is the watchdog's whole premise ("a non-zero count here
    always means the last boot of this tree did not work"), and it was bumped
    before check_tree ran - so two boots with DASH_RELEASE_PUBKEYS missing
    from the deploy command reverted a perfectly good update and blamed the
    bundle."""
    sys.path.insert(0, str(REPO / "dashboard" / "deploy"))
    try:
        import select_code_root as scr
    finally:
        sys.path.pop(0)
    monkeypatch.setattr(scr, "CURRENT_JSON", tmp_path / "current.json")
    monkeypatch.setattr(scr, "STATE_DIR", tmp_path, raising=False)
    (tmp_path / "current.json").write_text(json.dumps({"version": "0.7.43"}),
                                           encoding="utf-8")
    monkeypatch.setattr(scr, "read_runtime_id", lambda: "")
    # dash-mounts-ui-b-2 (2026-09-11): only the ENVIRONMENT-shaped refusals are
    # free now, so the stub returns the constant check_tree really returns
    # rather than a paraphrase of it - a paraphrase would exercise the
    # tree-shaped branch and pin nothing about this finding.
    monkeypatch.setattr(scr, "check_tree", lambda v, r: ("", scr.ENV_REFUSALS[0]))
    bumped = []
    monkeypatch.setattr(scr, "bump_boot_attempts",
                        lambda v, reason="": bumped.append(v) or 1)

    assert scr.main() == 0
    assert bumped == [], "an environment-shaped refusal counted against the tree"


# ------------------------------------- comp-app-2, the rendering half
#
# The nine wave-3 `resolve_health` fields are persisted by dash-db-core /
# dash-api-jobs (`db.resolve_health_detail`); this is the half that puts them
# on the machine panel, beside the v38 counters they belong with.

WAVE_3 = {
    "connected": True,
    "project_open": "FF5 EP12",
    "wedged_seconds": 12.5,
    "wedged_call": "GetMediaPool",
    "missing_clips": [{"name": "a.mov", "path": "P:/x/a.mov"}],
    "non_canonical_refused": [{"name": "b.mov", "path": "P:/x/b.mov"}],
    "proxy_attach": {"attached": 3, "failed": 1, "why": "timecode"},
    "proxy_gaps": {"capped": 2, "low_space": "8 GB free", "truncated": True},
    "stills": {"ok": False, "status": "add-by-hand", "instruction": "point it at P:"},
}


@pytest.fixture
def fleet(tmp_path):
    """One admin, one computer that has reported."""
    app = create_app(Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                              report_token="sekrit-report-token-0911",
                              admin_users=frozenset({"owen"})))
    with TestClient(app) as client:
        def report(**guard):
            body = {"editor_name": "owen", "machine": "EDIT-PC",
                    "companion_version": "0.9.70", "lanes": [],
                    "reported_at": dbmod.utcnow_iso()}
            if guard:
                body["sync_guard"] = dict(guard)
            resp = client.post("/api/v1/report", json=body, headers={
                "X-CCSync-Token": "sekrit-report-token-0911",
                "X-CCSync-Identity": auth.make_identity_token(SECRET, "owen")})
            assert resp.status_code == 200, resp.text
        yield client, report


def test_the_machine_panel_shows_what_resolve_last_said(fleet):
    client, report = fleet
    report(resolve_health={"out_of_tree": 2, **WAVE_3})
    page = as_user(client, "owen").get("/partials/fleet")
    assert page.status_code == 200, page.text
    # One state line, whitespace-folded: the template wraps it for reading.
    line = " ".join(page.text.split())
    assert "Resolve: connected" in line
    assert 'project open: <span class="who">FF5 EP12</span>' in line
    assert "wedged 12 s in GetMediaPool" in line
    assert "proxies attached 3, failed 1 (timecode)" in line
    assert "proxy queue capped at 2" in line
    assert "stills: add-by-hand (point it at P:)" in line
    # The two lists are behind a count, because either can be fifty clips
    # long and this is a cell in a grid.
    assert "1 clip Resolve cannot find" in line
    assert "1 clip refused: the path is not the canonical one" in line
    assert "P:/x/a.mov" in line and "P:/x/b.mov" in line


def test_a_machine_that_has_not_sent_them_renders_nothing(fleet):
    """An older companion says nothing about Resolve, and nothing is what the
    panel says back: "could not check" must never render as a reassurance."""
    client, report = fleet
    report(resolve_health={"out_of_tree": 0})
    page = as_user(client, "owen").get("/partials/fleet")
    assert page.status_code == 200
    line = " ".join(page.text.split())
    assert "Resolve: " not in line
    assert "clip Resolve cannot find" not in line
