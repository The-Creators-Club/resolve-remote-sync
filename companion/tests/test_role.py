"""CompanionApp role wiring: a verified sign-in's role ("base"/"editor",
from the dashboard's DASH_ADMIN_USERS-derived /api/v1/verify response)
overrides sync_enabled dynamically -- see app.py's _apply_identity_role()
and effective_mode(). Identity state is injected directly (not via a real
HTTP round trip) since app.identity is a real IdentityManager instance
constructed inside CompanionApp.__init__; this mirrors test_identity.py's
own token-crafting helper for a valid, non-expired identity."""

from __future__ import annotations

import base64
import time
from typing import Any

from ccsync_companion.app import CompanionApp


def _token(username: str = "alex", ttl: int = 3600) -> str:
    # Same v2 identity shape identity.py's parse_token expects (it never
    # verifies the signature locally, only the format + expiry field) --
    # mirrors test_identity.py's helper.
    user_b64 = base64.urlsafe_b64encode(username.encode("utf-8")).rstrip(b"=").decode("ascii")
    return f"v2.identity.{user_b64}.{int(time.time()) + ttl}.deadbeef"


def _cfg(tmp_path, **overrides) -> dict[str, Any]:
    cfg = {
        "editor_name": "alex",
        "local_root": str(tmp_path / "root"),
        "canonical_prefix": "P:\\",
        "remote": "creators_club_sftp",
        "remote_root": "/mnt/tank/Creators_Club",
        "active_project": "",
        "poll_interval": 3,
        "log_path": str(tmp_path / "companion.log"),
        "dashboard_url": "",
        "popup_enabled": True,
        "sync_enabled": True,
        "lane_b_enabled": False,
        "require_login": True,
    }
    cfg.update(overrides)
    return cfg


def _sign_in_with_role(app: CompanionApp, username: str, role: str | None) -> None:
    """Directly install a valid identity (bypassing the HTTP call) and run
    the same post-sign-in hook sign_in() would, so _apply_identity_role()
    actually runs."""
    app.identity._identity = {"username": username, "token": _token(username), "role": role}
    app._apply_identity_role()


def test_base_role_disables_sync_even_though_config_says_enabled(tmp_path):
    app = _make_app(tmp_path, sync_enabled=True)
    assert app._sync_enabled is True  # nobody signed in yet -- static default
    _sign_in_with_role(app, "alex", "base")
    assert app._sync_enabled is False
    assert app.effective_mode() == "base"


def test_editor_role_keeps_sync_enabled(tmp_path):
    app = _make_app(tmp_path, sync_enabled=True)
    _sign_in_with_role(app, "jsmith", "editor")
    assert app._sync_enabled is True
    assert app.effective_mode() == "editor"


def test_editor_role_overrides_a_base_flagged_config(tmp_path):
    """A machine whose config.toml still says mode=base/sync_enabled=false
    (stale from before this feature, or just wrong) gets overridden by a
    real editor logging in -- role from login wins over the static file."""
    app = _make_app(tmp_path, sync_enabled=False, mode="base")
    assert app._sync_enabled is False
    _sign_in_with_role(app, "jsmith", "editor")
    assert app._sync_enabled is True


def test_no_role_from_dashboard_falls_back_to_static_config(tmp_path):
    app = _make_app(tmp_path, sync_enabled=False)
    _sign_in_with_role(app, "jsmith", None)  # older dashboard, no role field
    assert app._sync_enabled is False  # unchanged: static config still applies
    assert app.effective_mode() == "editor"  # config.toml's mode default


def test_sign_out_reverts_to_static_config(tmp_path):
    app = _make_app(tmp_path, sync_enabled=True)
    _sign_in_with_role(app, "alex", "base")
    assert app._sync_enabled is False
    app.identity.sign_out()
    app._apply_identity_role()
    assert app._sync_enabled is True  # back to config.toml's sync_enabled=true


def _make_app(tmp_path, **overrides) -> CompanionApp:
    return CompanionApp(_cfg(tmp_path, **overrides))
