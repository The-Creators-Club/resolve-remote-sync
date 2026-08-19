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


def _token(username: str = "owen", ttl: int = 3600) -> str:
    # Same v2 identity shape identity.py's parse_token expects (it never
    # verifies the signature locally, only the format + expiry field) --
    # mirrors test_identity.py's helper.
    user_b64 = base64.urlsafe_b64encode(username.encode("utf-8")).rstrip(b"=").decode("ascii")
    return f"v2.identity.{user_b64}.{int(time.time()) + ttl}.deadbeef"


def _make_local_root(tmp_path) -> str:
    """local_root must EXIST: validate_config flags a missing one as an error
    that stops syncing, and since 0.4.5 an error genuinely does stop the
    lanes (DEL-3) and suppress the out-of-tree popup (CORE-H1). A test config
    pointing at a directory that was never created is a misconfigured
    install, not a working one."""
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    return str(root)

def _cfg(tmp_path, **overrides) -> dict[str, Any]:
    cfg = {
        "editor_name": "owen",
        "local_root": _make_local_root(tmp_path),
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
    _sign_in_with_role(app, "owen", "base")
    assert app._sync_enabled is False
    assert app.effective_mode() == "base"


def test_editor_role_keeps_sync_enabled(tmp_path):
    app = _make_app(tmp_path, sync_enabled=True)
    _sign_in_with_role(app, "jsmith", "editor")
    assert app._sync_enabled is True
    assert app.effective_mode() == "editor"


def test_editor_role_can_never_enable_sync_on_a_base_flagged_config(tmp_path):
    """INVERTED 2026-07-25 (AUDIT_2 CORE-C1) -- this test previously asserted
    the opposite, and the behaviour it blessed was the single most dangerous
    thing in the companion.

    `_apply_identity_role` was `self._sync_enabled = (role != "base")`, so any
    sign-in by an account outside DASH_ADMIN_USERS force-ENABLED the sync
    lanes on a machine whose config says mode="base"/sync_enabled=false. On
    the base rig `local_root` IS the live NAS SMB share (T:\\Creators_Club),
    and lane B is a deleting `rclone sync` DOWNWARD from that user's empty
    SFTP home -- i.e. it would delete the NAS's real Proxy/ files under every
    selected project. With require_login=false and a stale identity.json this
    needed no user action at all.

    The role is now MONOTONIC: it may only ever disable sync. A machine that
    says it does not sync stays that way whatever the server says; the fix
    for a genuinely mis-flagged machine is to correct its config.toml, which
    is a deliberate local act rather than a side effect of somebody's login.
    """
    app = _make_app(tmp_path, sync_enabled=False, mode="base")
    assert app._sync_enabled is False
    _sign_in_with_role(app, "jsmith", "editor")
    assert app._sync_enabled is False
    # REVERSED 2026-08-19 (docs/MULTI_BASE_RIG_PLAN.md WP0). This used to
    # assert "editor" -- the reported mode followed the dashboard so an admin
    # could SEE the disagreement rather than have it silently resolved. That
    # reasoning assumed the role was about a machine; it is derived from the
    # dashboard's ADMIN list, so it is about the PERSON, and it said "editor"
    # for every wired office machine whose owner is not an admin. The cost of
    # believing it: `machine_state.mode` is what CR-28's queue exclusion
    # reads, so such a machine sat in [ QUEUED ] under a GETTING READY chip
    # that could never clear. Surfacing the disagreement is the dashboard's
    # job (WP2's chip), not the reported truth's.
    assert app.effective_mode() == "base"


def test_no_role_from_dashboard_falls_back_to_static_config(tmp_path):
    app = _make_app(tmp_path, sync_enabled=False)
    _sign_in_with_role(app, "jsmith", None)  # older dashboard, no role field
    assert app._sync_enabled is False  # unchanged: static config still applies
    assert app.effective_mode() == "editor"  # config.toml's mode default


def test_sign_out_reverts_to_static_config(tmp_path):
    app = _make_app(tmp_path, sync_enabled=True)
    _sign_in_with_role(app, "owen", "base")
    assert app._sync_enabled is False
    app.identity.sign_out()
    app._apply_identity_role()
    assert app._sync_enabled is True  # back to config.toml's sync_enabled=true


def test_a_wired_machine_owned_by_a_non_admin_reports_base(tmp_path):
    """WP0, the case the whole plan exists for: Billy's office desktop works
    directly off the NAS, and Billy is not a dashboard admin -- so /verify
    hands his sign-in role="editor" on every one of his three computers. The
    machine's own file is what knows which one this is."""
    app = _make_app(tmp_path, sync_enabled=False, mode="base")
    _sign_in_with_role(app, "billy", "editor")
    assert app.effective_mode() == "base"
    assert app._sync_enabled is False


def test_a_remote_machine_of_the_same_person_still_reports_editor(tmp_path):
    """...and his laptop, same account, same role, is untouched."""
    app = _make_app(tmp_path, sync_enabled=True)
    _sign_in_with_role(app, "billy", "editor")
    assert app.effective_mode() == "editor"
    assert app._sync_enabled is True


def _make_app(tmp_path, **overrides) -> CompanionApp:
    return CompanionApp(_cfg(tmp_path, **overrides))
