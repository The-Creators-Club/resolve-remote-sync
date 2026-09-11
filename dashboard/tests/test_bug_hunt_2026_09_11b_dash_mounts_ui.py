"""The dash-mounts-ui half of the second 2026-09-11 bug hunt (CR-259).

One section per finding id, and every test here fails at f1eeb42 - the fix
pass this hunt was OF:

  res-fleet-2   the automatic crash-loop revert had no schema check, so the
                escape hatch could revert into a build whose db.migrate()
                raises on every boot, for ever, with no dashboard left.
  b-1           the per-cycle mount re-probe watched the bind MOUNTPOINT,
                which is still a directory after the export behind it goes.
  b-2           a tree that can NEVER pass check_tree stopped counting boots,
                so revert() became unreachable for the bundles the watchdog
                was written for.
  b-3           the stale-while-revalidate fetch was detached, so the worker
                could be killed before the cache write it exists for.
  b-5           the uid warning blamed APP_UID for a number it read off /data.
  b-6           the refusal banner's path was consumed by the FIRST swap of a
                response, so an out-of-band banner lost it.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
NODE = shutil.which("node")
SH = shutil.which("sh")


def _scr():
    """The image-side boot script, imported by path (it is not a package)."""
    sys.path.insert(0, str(REPO / "dashboard" / "deploy"))
    try:
        import select_code_root as module
    finally:
        sys.path.pop(0)
    return module


def _world(tmp_path, monkeypatch, *, user_version: int, previous_schema=None,
           attempts: int = 2):
    """A /data that has taken an OTA update to 0.7.43 which will not boot.

    The database is already migrated to the NEW tree's schema - which is what
    makes the revert dangerous: the previous tree's code cannot open it.
    """
    scr = _scr()
    code = tmp_path / "code"
    (code / "0.7.40").mkdir(parents=True)
    if previous_schema is not None:
        (code / "0.7.40" / "manifest.json").write_text(
            json.dumps({"kind": "dashboard", "version": "0.7.40",
                        "schema_version": previous_schema}), encoding="utf-8")
    (code / "current.json").write_text(json.dumps({
        "version": "0.7.43", "previous": "0.7.40",
        "applied_at": "2026-09-11T00:00:00Z"}), encoding="utf-8")
    (code / "boot_attempts.json").write_text(
        json.dumps({"version": "0.7.43", "attempts": attempts}), encoding="utf-8")

    db_path = tmp_path / "dashboard.db"
    conn = sqlite3.connect(db_path)
    conn.execute(f"PRAGMA user_version = {user_version}")
    conn.close()

    monkeypatch.setenv("DASH_DB_PATH", str(db_path))
    monkeypatch.setattr(scr, "DATA_DIR", tmp_path)
    monkeypatch.setattr(scr, "CODE_DIR", code)
    monkeypatch.setattr(scr, "CURRENT_JSON", code / "current.json")
    monkeypatch.setattr(scr, "BOOT_ATTEMPTS", code / "boot_attempts.json")
    monkeypatch.setattr(scr, "read_runtime_id", lambda: "rid")
    return scr, code


# ------------------------------------------------------------- res-fleet-2


def test_the_watchdog_does_not_revert_into_a_build_that_cannot_open_the_database(
        tmp_path, monkeypatch):
    """0.7.43 migrated the database to v52 and then failed its boot twice. The
    previous tree knows v50, so reverting to it means `database schema is newer
    than this build` out of migrate(), uncaught, on every boot - a container
    that crash-loops for ever with no page to fix it from."""
    scr, code = _world(tmp_path, monkeypatch, user_version=52, previous_schema=50)
    monkeypatch.setattr(scr, "check_tree", lambda v, r: ("/data/code/%s/src" % v, ""))

    assert scr.main() == 0

    current = json.loads((code / "current.json").read_text(encoding="utf-8"))
    assert current["version"] == "0.7.43", "reverted into a dead boot"
    assert not current.get("reverted_reason")
    assert "v50" in current["revert_refused_reason"]
    assert "v52" in current["revert_refused_reason"]


def test_the_refusal_is_cleared_once_the_applied_tree_boots_healthily(tmp_path,
                                                                      monkeypatch):
    """A banner that outlives the problem teaches an admin to ignore banners.
    The app clears boot_attempts once it has been up and healthy for a while,
    and that is the signal the refusal is over."""
    scr, code = _world(tmp_path, monkeypatch, user_version=52, previous_schema=50)
    monkeypatch.setattr(scr, "check_tree", lambda v, r: ("/data/code/%s/src" % v, ""))
    assert scr.main() == 0
    assert json.loads((code / "current.json").read_text(
        encoding="utf-8"))["revert_refused_reason"]

    (code / "boot_attempts.json").write_text(
        json.dumps({"version": "", "attempts": 0}), encoding="utf-8")
    assert scr.main() == 0

    current = json.loads((code / "current.json").read_text(encoding="utf-8"))
    assert "revert_refused_reason" not in current
    assert current["version"] == "0.7.43"


def test_the_watchdog_still_reverts_when_the_schema_allows_it(tmp_path, monkeypatch):
    """The guard is a refusal, not an off switch: a previous tree that knows
    the same schema (or a newer one) reverts exactly as before."""
    scr, code = _world(tmp_path, monkeypatch, user_version=52, previous_schema=52)
    monkeypatch.setattr(scr, "check_tree", lambda v, r: ("/data/code/%s/src" % v, ""))

    assert scr.main() == 0

    current = json.loads((code / "current.json").read_text(encoding="utf-8"))
    assert current["version"] == "0.7.40"
    assert current["reverted_from"] == "0.7.43"
    assert current["reverted_reason"]


def test_a_target_whose_schema_is_unknown_still_reverts(tmp_path, monkeypatch):
    """REL-10's third answer, kept: a tree applied before REL-10 carries no
    schema in its manifest, and blocking the escape hatch on a missing number
    would be worse than the risk it guards."""
    scr, code = _world(tmp_path, monkeypatch, user_version=52, previous_schema=None)
    monkeypatch.setattr(scr, "check_tree", lambda v, r: ("/data/code/%s/src" % v, ""))

    assert scr.main() == 0

    current = json.loads((code / "current.json").read_text(encoding="utf-8"))
    assert current["version"] == "0.7.40", "cannot tell must not refuse"


def test_the_image_is_judged_by_its_own_migration_list(tmp_path, monkeypatch):
    """`previous` is "" on the common shape (one OTA update over the image),
    so the target's schema is the IMAGE's own - read out of its db.py rather
    than imported, the way image_version() is read."""
    scr, code = _world(tmp_path, monkeypatch, user_version=99, previous_schema=None)
    monkeypatch.setattr(scr, "APP_ROOT", REPO / "dashboard")
    # The real repo as the image gives a real VERSION, and since CR-270
    # (2026-09-12) a tree the image has caught up with is RETIRED before the
    # revert logic runs. This test is about the revert's schema guard, so the
    # image must be OLDER than the 0.7.43 tree, as it was when it was written.
    monkeypatch.setattr(scr, "image_version", lambda: "0.7.42")
    (code / "current.json").write_text(json.dumps({
        "version": "0.7.43", "previous": ""}), encoding="utf-8")
    monkeypatch.setattr(scr, "check_tree", lambda v, r: ("/data/code/%s/src" % v, ""))

    from ccsync_dashboard import db as dbmod
    assert scr.image_schema_version() == dbmod.SCHEMA_VERSION

    assert scr.main() == 0
    current = json.loads((code / "current.json").read_text(encoding="utf-8"))
    assert current["version"] == "0.7.43", "reverted to an image that cannot migrate"
    assert current["revert_refused_reason"]


# ------------------------------------------------------------------- b-2


TREE_REFUSAL = "/data/code/0.7.43/manifest.json is missing or unreadable"


def test_a_tree_shaped_refusal_counts_towards_the_revert(tmp_path, monkeypatch):
    """dash-mounts-ui-8 stopped counting refusals so that a missing
    DASH_RELEASE_PUBKEYS could not blame a good bundle. The other half was not
    made: a refusal that can never clear itself stopped counting too, and
    revert() is reachable only through the counter."""
    scr, code = _world(tmp_path, monkeypatch, user_version=50, attempts=0)
    monkeypatch.setattr(scr, "check_tree", lambda v, r: ("", TREE_REFUSAL))

    assert scr.main() == 0
    state = json.loads((code / "boot_attempts.json").read_text(encoding="utf-8"))
    assert state == {"version": "0.7.43", "attempts": 1, "reason": TREE_REFUSAL}

    # The second boot reaches the ceiling; the third reverts, and says what
    # was actually wrong rather than "failed to reach a healthy boot".
    assert scr.main() == 0
    assert scr.main() == 0
    current = json.loads((code / "current.json").read_text(encoding="utf-8"))
    assert current["version"] == "0.7.40"
    assert TREE_REFUSAL in current["reverted_reason"]


def test_an_environment_shaped_refusal_is_still_free(tmp_path, monkeypatch):
    """The dash-mounts-ui-8 case itself, pinned against the constants
    check_tree returns rather than against a sentence typed twice."""
    scr, code = _world(tmp_path, monkeypatch, user_version=50, attempts=0)
    for reason in scr.ENV_REFUSALS:
        monkeypatch.setattr(scr, "check_tree", lambda v, r, _x=reason: ("", _x))
        assert scr.main() == 0
        assert json.loads((code / "boot_attempts.json").read_text(
            encoding="utf-8"))["attempts"] == 0

    verifier = ("/data/code/0.7.43/record.json does not verify: the image's own "
                "verifier could not be imported (No module named 'x')")
    assert scr.environment_refusal(verifier)
    assert not scr.environment_refusal(TREE_REFUSAL)


def test_check_tree_still_returns_the_two_environment_reasons_verbatim(tmp_path,
                                                                       monkeypatch):
    """The classifier compares against what check_tree returns, so the two
    must not drift: if the sentence is rewritten and the constant is not, a
    permanently refused tree starts counting again (or stops)."""
    scr, _ = _world(tmp_path, monkeypatch, user_version=50, attempts=0)
    monkeypatch.delenv("DASH_RELEASE_PUBKEYS", raising=False)
    root = scr.CODE_DIR / "0.7.43"
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(json.dumps(
        {"kind": "dashboard", "version": "0.7.43", "runtime_id": "rid"}),
        encoding="utf-8")
    (root / "record.json").write_text(json.dumps(
        {"kind": "dashboard", "version": "0.7.43", "runtime_id": "rid"}),
        encoding="utf-8")

    _, reason = scr.check_tree("0.7.43", "rid")
    assert reason == scr.ENV_REFUSALS[0]
    assert scr.environment_refusal(reason)


# ------------------------------------------------------------------- b-1


def test_a_bind_mount_that_goes_empty_is_seen_by_the_broll_re_probe(tmp_path,
                                                                    monkeypatch):
    """The recorded path used to be BROLL_DATA_ROOT, which on every shipped
    deployment is a bind-mount TARGET: the directory is still there when the
    export behind it goes, so os.path.isdir answered True in the exact failure
    the re-probe was written for (a NAS export flapping at 03:00) and B-ROLL
    stayed advertised while every request under it failed."""
    sys.path.insert(0, str(REPO / "dashboard" / "tests"))
    try:
        from test_broll_mount import _build_fake_broll
    finally:
        sys.path.pop(0)

    from ccsync_dashboard import broll, mount_status

    root = tmp_path / "broll-data"
    root.mkdir()
    monkeypatch.setenv("BROLL_DATA_ROOT", str(root))
    for name, module in _build_fake_broll("BROLL_DATA_ROOT").items():
        monkeypatch.setitem(sys.modules, name, module)

    mount_status.reset()
    mount_status.record("broll", mount_status.MOUNTED, "serving /broll")
    broll._init_broll_storage()
    assert mount_status.recheck() == {}, "a healthy mount must not be downgraded"

    # The flap: the mount point is still a directory, and everything that was
    # under it is gone with the export.
    for child in root.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    assert root.is_dir()

    changed = mount_status.recheck()
    assert changed.get("broll", ("", ""))[0] == mount_status.DEGRADED, changed

    # And it comes back when the export does, without a restart.
    broll._init_broll_storage()
    assert mount_status.recheck().get("broll", ("", ""))[0] == mount_status.MOUNTED
    mount_status.reset()


# ------------------------------------------------------------------- b-3

SW_HARNESS = r"""
// The Service Worker lifetime contract: the worker may be terminated once no
// extend-lifetime promise (respondWith's, waitUntil's) is pending. This
// harness kills it at that moment and records anything that tried to run
// afterwards, which is what a phone on a poor link does to a detached fetch.
const fs = require('fs'), vm = require('vm'), path = process.argv[2];
let handlers = {}, put = [], putAfterDeath = [], alive = 0, dead = false;
function extend(p) { alive++; Promise.resolve(p).catch(function () { }).then(check); }
function check() { alive--; setTimeout(function () { if (alive <= 0) dead = true; }, 0); }
function FakeResponse(body) { this.body = body; this.ok = true; this.type = 'basic';
  this.clone = function () { return this; }; }
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
      put: function (req) { (dead ? putAfterDeath : put).push(req.url);
                            return Promise.resolve(); }
    }); },
    keys: function () { return Promise.resolve([]); },
    match: function (req) {
      const url = (req && req.url) || req;
      return Promise.resolve(url.indexOf('/static/style.css') >= 0
        ? new FakeResponse('CACHED') : undefined);
    }
  },
  // A revalidation on a slow link: the response arrives well after the
  // cached one has been painted.
  fetch: function () { return new Promise(function (res) {
    setTimeout(function () { res(new FakeResponse('NETWORK')); }, 20); }); },
  Request: function (url) { this.url = url; },
  Response: function (body) { this.body = body; },
  URL: URL
};
sandbox.globalThis = sandbox;
vm.runInNewContext(fs.readFileSync(path, 'utf8').replace(/__VERSION__/g, 'x'), sandbox);
let answered = null;
const event = {
  request: { method: 'GET', url: 'https://nas.example/static/style.css', mode: 'no-cors' },
  respondWith: function (p) { answered = p; extend(p); },
  waitUntil: function (p) { extend(p); }
};
handlers['fetch'](event);
Promise.resolve(answered).then(function (res) {
  setTimeout(function () {
    console.log(JSON.stringify({ served: res && res.body, put: put,
                                 putAfterDeath: putAfterDeath }));
  }, 200);
});
"""


@pytest.mark.skipif(NODE is None, reason="no node on this machine")
def test_the_revalidation_is_an_extend_lifetime_promise(tmp_path):
    """dash-mounts-ui-5's fix returned the cached hit and left the fetch
    detached, so on the flaky mobile connection it was written for the worker
    could be killed before cache.put ran - and the phone was stale again next
    load, behind a fix that looked applied."""
    harness = tmp_path / "sw_lifetime_harness.js"
    harness.write_text(SW_HARNESS, encoding="utf-8")
    out = subprocess.run(
        [NODE, str(harness), str(REPO / "dashboard" / "static" / "sw.js")],
        capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["served"] == "CACHED", result
    assert result["putAfterDeath"] == [], "the worker was killed before the cache write"
    assert any("style.css" in u for u in result["put"]), result


# ------------------------------------------------------------------- b-5

UID_PRELUDE = """
id() { if [ "$1" = "-u" ]; then echo 3000; else echo 3000; fi; }
stat() { echo 0; }
"""


def _uid_block() -> str:
    """run.sh's uid advisory, lifted out so it can be executed on its own."""
    text = (REPO / "dashboard" / "deploy" / "run.sh").read_text(encoding="utf-8")
    start = text.index('expected_uid="${APP_UID:-}"')
    end = text.index('if [ -n "${APP_GID:-}" ]', start)
    return text[start:end]


@pytest.mark.skipif(SH is None, reason="no POSIX sh on this machine")
def test_the_uid_warning_blames_the_right_thing_when_it_read_the_number_off_data(
        tmp_path):
    """With APP_UID unset the number comes from /data, and the warning used to
    call it "(APP_UID)" and send the admin to compose's `user:` line - which on
    the case the fallback exists for (a /data docker created as root) is the
    one change that is wrong. The container is running as the right uid there;
    /data is not."""
    script = tmp_path / "uid.sh"
    script.write_text(UID_PRELUDE + _uid_block(), encoding="utf-8", newline="\n")
    env = dict(os.environ)
    env.pop("APP_UID", None)
    out = subprocess.run([SH, str(script)], capture_output=True, text=True,
                         timeout=30, env=env)
    assert out.returncode == 0, out.stderr
    assert "uid 0" in out.stderr, out.stderr
    assert "(APP_UID)" not in out.stderr, out.stderr
    assert "chown /data to 3000" in out.stderr, out.stderr


@pytest.mark.skipif(SH is None, reason="no POSIX sh on this machine")
def test_the_uid_warning_still_names_app_uid_when_app_uid_is_what_it_read(tmp_path):
    """Image mode, where the variable IS set: the original sentence, unchanged."""
    script = tmp_path / "uid.sh"
    script.write_text(UID_PRELUDE + _uid_block(), encoding="utf-8", newline="\n")
    env = dict(os.environ)
    env["APP_UID"] = "1026"
    out = subprocess.run([SH, str(script)], capture_output=True, text=True,
                         timeout=30, env=env)
    assert out.returncode == 0, out.stderr
    assert "uid 1026 (APP_UID)" in out.stderr, out.stderr
    assert "compose's `user:` line" in out.stderr, out.stderr


# ------------------------------------------------------------------- b-6

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
function panel(formPath, withBanner) {
  const banner = elt({}); banner.className = 'error-banner';
  banner.scrollIntoView = function () { };
  const form = elt({ 'hx-post': formPath });
  const moved = [];
  form.parentNode = { insertBefore: function (b, f) { moved.push(f.attrs['hx-post']); } };
  return {
    moved: moved,
    querySelector: function (sel) {
      return (sel === '.error-banner' && withBanner) ? banner : null; },
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

// One write, answered with a main partial PLUS an out-of-band error strip:
// htmx settles both elements and fires afterSwap once for each, with the same
// xhr. An htmx that carries no requestConfig on the event falls back to the
// WeakMap, which the first swap used to consume.
const button = elt({ 'hx-post': '/admin/packages/40/delete' });
const xhr = {};
fire('htmx:beforeRequest', { elt: button, xhr: xhr });
const mainPanel = panel('/admin/packages/40/delete', false);
fire('htmx:afterSwap', { target: mainPanel, xhr: xhr });
const oobPanel = panel('/admin/packages/40/delete', true);
fire('htmx:afterSwap', { target: oobPanel, xhr: xhr });
console.log(JSON.stringify({ oob: oobPanel.moved }));
"""


@pytest.mark.skipif(NODE is None, reason="no node on this machine")
def test_an_out_of_band_banner_still_reaches_its_button(tmp_path):
    """htmx fires afterSwap once per settled element and an OOB swap adds its
    elements to the same list. Deleting the WeakMap entry on the first one lost
    the path for the second - and the error strip is exactly the fragment that
    arrives out of band. The map is weak, so the entry dies with the xhr
    anyway."""
    harness = tmp_path / "htmx_oob_harness.js"
    harness.write_text(HTMX_HARNESS, encoding="utf-8")
    out = subprocess.run(
        [NODE, str(harness), str(REPO / "dashboard" / "static" / "htmx_errors.js")],
        capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["oob"] == ["/admin/packages/40/delete"], result
