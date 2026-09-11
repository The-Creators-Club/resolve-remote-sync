"""bug-hunt 2026-09-11b, territory dash-core (CR-257).

The hunt was OF the morning's fix pass, so most of these are the other half
of a fix that landed once: a warn that outlived the condition it described
(dash-core-1), a backoff whose clamp came after the overflow (dash-core-3),
a pair written independently and read atomically (dash-core-4), an index
re-walked on every render (dash-core-5), a COPY that hard-fails on a document
the policy calls best effort (dash-mounts-ui-b-4), and a login-gate carve-out
that outlived its route (security-2).
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from ccsync_dashboard import (help as help_page, internal_sftp, published_docs,
                              secrets_boot, sessions, setup_engine)
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

REPO = Path(__file__).resolve().parents[2]
SECRET = "s" * 32
TOKEN = "9f3c1ab27d4e5608bc19af730d25e8641c07b9a3f2de5061"


# ------------------------------------------------------------- dash-core-1

def test_a_stored_eula_warn_stops_gating_only_while_the_licence_is_missing(
        conn, monkeypatch, tmp_path):
    """The warn carve-out (dash-core-6) has to be a fact about the BUILD, not
    a row: nothing re-runs _check_eula on its own, so a warn written by a
    build with no docs/legal survived the OTA bundle that brought the licence
    and no human ever accepted it."""
    monkeypatch.setattr(setup_engine, "EULA_PATH", tmp_path / "missing.md")
    ctx = setup_engine.SetupContext(conn, Settings(session_secret=SECRET))
    assert setup_engine.run_check(ctx, "eula").status == "warn"
    assert "eula" not in setup_engine.outstanding_required(conn)

    landed = tmp_path / "EULA.md"
    landed.write_text("<!-- EULA-VERSION: 3 -->\n# Licence\n", encoding="utf-8")
    monkeypatch.setattr(setup_engine, "EULA_PATH", landed)
    # The stored row still says `warn`; the licence is on disk, so the wizard
    # must ask for it again.
    assert setup_engine.load_state(conn, "eula").status == "warn"
    assert "eula" in setup_engine.outstanding_required(conn)
    assert "eula" in dict(setup_engine.outstanding_for_done(conn))


# ------------------------------------------------------------- dash-core-3

def test_the_login_backoff_survives_a_thousand_recorded_failures(tmp_path):
    """`BASE * (2 ** (failures - limit))` is evaluated before min() clamps it,
    so past ~1024 failures the multiply raised OverflowError - not an
    sqlite3.OperationalError, so it escaped the store into the login route and
    500'd every further failed sign-in for that key."""
    store = sessions.SessionStore(tmp_path / "backoff.db")
    store.ensure_schema()
    now = "2026-09-11T12:00:00+00:00"
    conn = sqlite3.connect(tmp_path / "backoff.db")
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO login_attempts "
            "(scope, key, failures, first_failure, last_failure, blocked_until) "
            "VALUES ('user', 'jsmith', 1100, ?, ?, NULL)", (now, now))
    conn.close()

    store.record_failure("jsmith", now=now)         # raised OverflowError

    blocked = store.throttled("jsmith", now=now)
    assert 0 < blocked <= sessions.LOGIN_BACKOFF_MAX_SECONDS


# ------------------------------------------------------------- dash-core-4

def test_a_half_set_uid_pair_is_not_written_to_internal_env(tmp_path):
    """The writer emitted the two independently and the reader takes the pair
    or neither, so APP_UID alone left the sidecar and the dashboard disagreeing
    about file ownership with nothing said anywhere."""
    secrets_boot._write_sidecar_env_files(
        {"CCSYNC_INTERNAL_TOKEN": "t" * 40, "APP_UID": "3000"}, tmp_path)
    written = (tmp_path / "internal.env").read_text(encoding="utf-8")
    assert "CCSYNC_INTERNAL_TOKEN=" in written
    assert "APP_UID=" not in written and "APP_GID=" not in written

    secrets_boot._write_sidecar_env_files(
        {"CCSYNC_INTERNAL_TOKEN": "t" * 40, "APP_UID": "3000", "APP_GID": "3001"},
        tmp_path)
    both = (tmp_path / "internal.env").read_text(encoding="utf-8")
    assert "APP_UID=3000" in both and "APP_GID=3001" in both


def test_a_half_set_uid_pair_is_logged_by_the_reader(monkeypatch, caplog):
    monkeypatch.setenv("APP_UID", "3000")
    monkeypatch.delenv("APP_GID", raising=False)
    with caplog.at_level(logging.WARNING, logger=internal_sftp.log.name):
        internal_sftp._uid_gid()
    assert any("APP_UID" in r.getMessage() and "APP_GID" in r.getMessage()
               for r in caplog.records), caplog.text


# ------------------------------------------------------------- dash-core-5

def test_the_help_index_is_not_re_walked_on_every_render(monkeypatch):
    """185 documents on a dev checkout: one rglob, ~370 stats and 185 opens,
    on every /help render and every internal link click."""
    help_page.invalidate_index()
    real = help_page._iter_markdown
    calls = []

    def counted(root):
        calls.append(root)
        return real(root)

    monkeypatch.setattr(help_page, "_iter_markdown", counted)
    first = help_page.document_groups(True)
    second = help_page.document_groups(True)
    assert first == second
    assert len(calls) == 1, calls
    # ...and the audiences do not share an entry list.
    editor = help_page.document_groups(False)
    assert len(calls) == 2
    admin_rels = {e["rel"] for g in first for e in g["entries"]}
    editor_rels = {e["rel"] for g in editor for e in g["entries"]}
    assert editor_rels <= admin_rels
    help_page.invalidate_index()


# ------------------------------------------------------- dash-mounts-ui-b-4

def test_the_image_only_hard_copies_documents_the_policy_calls_required():
    """A COPY that names a missing file fails the BUILD, so every document the
    Dockerfile names by hand must be one whose absence the OTA bundler and the
    bind-mode deploy also refuse - otherwise the three shipping routes
    disagree about how bad the absence is."""
    dockerfile = (REPO / "dashboard" / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    copied = [line for line in dockerfile.splitlines()
              if line.startswith("COPY ") and "/app/docs" in line]
    named = {src for line in copied for src in line.split()[1:-1]}
    required_files, required_trees = published_docs.published_sources(required_only=True)
    assert named <= set(required_files) | set(required_trees), named


# --------------------------------------------------------------- security-2

def test_the_broll_fleet_batch_list_has_no_login_gate_carve_out(tmp_path):
    """broll-3 deleted GET /api/fleet/ingest/batches; the carve-out that let a
    bare fleet token skip login_gate for that exact path stayed. A collection
    path admitted with no session and no route behind it hands a session-gate
    bypass to whoever adds the next route there."""
    settings = Settings(session_secret=SECRET, report_token=TOKEN,
                        db_path=str(tmp_path / "d.db"))
    app = create_app(settings)
    with TestClient(app) as c:
        for path in ("/broll/api/fleet/ingest/batches",
                     "/broll/api/fleet/ingest/batches/"):
            r = c.get(path, headers={"X-CCSync-Token": TOKEN},
                      follow_redirects=False)
            assert r.status_code == 401, (path, r.status_code)


# ------------------------------------------- hand-off wave: settings.py

def test_an_explicit_release_feed_signature_url_is_read_from_the_environment():
    """dash-release-jobs-5 (hand-off wave, 2026-09-11b): a pre-signed feed URL
    cannot have `.sig` derived from it (the SigV4 signature covers the object
    key), so the operator must be able to name both URLs. Empty stays empty,
    so every existing deployment keeps the derivation."""
    assert Settings.from_env({"DASH_SESSION_SECRET": SECRET}).release_feed_sig_url == ""
    s = Settings.from_env({
        "DASH_SESSION_SECRET": SECRET,
        "DASH_RELEASE_FEED_URL": "https://example.invalid/channel.json?token=a",
        "DASH_RELEASE_FEED_SIG_URL": "  https://example.invalid/channel.json.sig?token=b  ",
    })
    assert s.release_feed_sig_url == "https://example.invalid/channel.json.sig?token=b"


def test_a_signature_url_with_no_feed_url_is_named_at_boot(caplog):
    """Half a configured pair is the CR-257d shape: the feed is disabled, so
    the signature URL is read by nothing and nothing would say so."""
    with caplog.at_level(logging.WARNING, logger="ccsync.dashboard.settings"):
        Settings.from_env({
            "DASH_SESSION_SECRET": SECRET,
            "DASH_RELEASE_FEED_SIG_URL": "https://example.invalid/c.json.sig",
        })
    assert any("DASH_RELEASE_FEED_SIG_URL" in r.getMessage() for r in caplog.records)
