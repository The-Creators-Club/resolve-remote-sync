"""What an error says to the person who caused it, and what it says to the log.

COMMERCIAL_READINESS.md §C L "error detail leaks" (2026-08-17). Two shapes:

  * a handled failure whose exception TEXT names internals -- the NAS host and
    its API path, or an absolute /mnt/<pool>/<tenant>/... path -- echoed
    straight back through HTTPException(detail=str(exc)) on routes that are
    open (/api/v1/verify) or reachable by any signed-in editor;
  * an UNHANDLED one, which used to answer Starlette's plain-text "Internal
    Server Error" -- harmless in itself, but not JSON for the fetch() callers
    that get it, and tied to no request in any log.

Both now answer generically and log the detail.
"""
from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"


def make(tmp_path, name="err.db", **kw):
    return Settings(db_path=str(tmp_path / name), session_secret=SECRET,
                    admin_users=frozenset({"admin"}), **kw)


def test_an_unreachable_nas_does_not_leak_its_address_to_an_open_route(
        tmp_path, caplog):
    """/api/v1/verify is in app.py's _OPEN_EXACT -- it is how a companion
    bootstraps -- so anyone who can reach the port reads whatever it says."""
    settings = make(tmp_path, nas_kind="truenas", nas_pw="fake-pw",
                    nas_host="nas-internal.example", nas_user="truenas_admin")
    app = create_app(settings)
    app.state.credential_verifier = lambda s, u, p: True
    with caplog.at_level(logging.WARNING, logger="ccsync.dashboard.api"):
        with TestClient(app) as client:
            r = client.post("/api/v1/verify",
                            json={"username": "jsmith", "password": "pw"})
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "try again" in detail                     # still retryable, still actionable
    assert "nas-internal.example" not in detail
    assert "api/v2.0" not in detail
    # ...and the operator still gets the real reason.
    assert "fleet-membership check" in caplog.text


def test_an_unhandled_error_answers_json_and_logs_the_traceback(tmp_path, caplog):
    settings = make(tmp_path, name="boom.db")
    app = create_app(settings)

    @app.get("/api/v1/boom")
    def boom():
        raise RuntimeError("/mnt/tank/CustomerName/Projects is on fire")

    # raise_server_exceptions=False so the handler's RESPONSE is what we see;
    # Starlette re-raises afterwards, which is what uvicorn logs in production.
    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "admin"))
        with caplog.at_level(logging.ERROR, logger="ccsync.dashboard.app"):
            r = client.get("/api/v1/boom")

    assert r.status_code == 500
    assert r.json() == {"detail": "internal error"}
    assert "/mnt/tank" not in r.text                 # no path, no message, no frame
    assert "RuntimeError" not in r.text
    # The log has all of it, tied to the request.
    assert "GET /api/v1/boom" in caplog.text
    assert "/mnt/tank/CustomerName" in caplog.text


def test_project_creation_failures_do_not_hand_an_editor_the_nas_path(
        tmp_path, monkeypatch):
    """create_tree_project's OSError text carries the NAS's absolute path, and
    the route is reachable by any signed-in editor."""
    from ccsync_dashboard import api

    settings = make(tmp_path, name="proj.db")
    app = create_app(settings)

    def explode(*a, **kw):
        raise api.ProjectSetupError(
            "could not create the folders on the NAS -- ask an admin to check the "
            "dashboard log")

    monkeypatch.setattr(api, "create_tree_project", explode)
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "jsmith"))
        r = client.post("/api/v1/projects",
                        json={"parent_rel": "2026", "name": "New Job",
                              "resolve_project": "New Job"})
    assert r.status_code == 422
    assert "/mnt/" not in r.json()["detail"]
