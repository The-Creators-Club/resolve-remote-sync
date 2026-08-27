"""CompanionApp role wiring, since 2026-08-27 (MULTI_BASE_RIG_PLAN.md
WP0/WP1's follow-up): the role belongs to the COMPUTER (config.toml's
`mode`), not to the signed-in person. A verified sign-in's role
("base"/"editor", from the dashboard's DASH_ADMIN_USERS-derived
/api/v1/verify response) is READ-ONLY diagnostic data now -- see
app.py's _apply_identity_role() and effective_mode() -- and never touches
`_sync_enabled` or what effective_mode() reports, in EITHER direction.

Before this date, a dashboard role of "base" DISABLED sync (monotonically:
it could only ever disable, never enable) on a machine whose own config
said mode="editor" -- which is exactly what put an admin's own laptop,
signed in as the admin account, into the base rig's no-sync state despite
being an ordinary editor computer (the bug this file used to guard the
FIX for, CORE-C1, is now guarded from the other side: identity.role must
have NO effect at all).

Identity state is injected directly (not via a real HTTP round trip) since
app.identity is a real IdentityManager instance constructed inside
CompanionApp.__init__; this mirrors test_identity.py's own token-crafting
helper for a valid, non-expired identity."""

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


def test_a_base_role_from_the_dashboard_no_longer_disables_sync(tmp_path):
    """THE bug this whole file used to guard the disable-behaviour of: an
    admin's own laptop, signed in as the admin account (role="base" from
    /verify), is an ordinary editor computer -- config.toml says mode
    "editor" -- and must keep syncing."""
    app = _make_app(tmp_path, sync_enabled=True)
    assert app._sync_enabled is True  # nobody signed in yet -- static default
    _sign_in_with_role(app, "owen", "base")
    assert app._sync_enabled is True
    assert app.effective_mode() == "editor"


def test_an_editor_role_never_mattered_and_still_does_not(tmp_path):
    app = _make_app(tmp_path, sync_enabled=True)
    _sign_in_with_role(app, "jsmith", "editor")
    assert app._sync_enabled is True
    assert app.effective_mode() == "editor"


def test_a_role_can_never_move_sync_enabled_off_a_base_flagged_config(tmp_path):
    """A machine whose config.toml says mode="base"/sync_enabled=false stays
    that way whatever the dashboard's admin-derived role says -- unchanged
    from before 2026-08-27, just for a simpler reason now: role is never
    consulted for sync_enabled at all."""
    app = _make_app(tmp_path, sync_enabled=False, mode="base")
    assert app._sync_enabled is False
    _sign_in_with_role(app, "jsmith", "editor")
    assert app._sync_enabled is False
    assert app.effective_mode() == "base"


def test_a_role_can_never_move_sync_enabled_off_an_editor_flagged_config(tmp_path):
    """The other direction, mirrored: role="base" from the dashboard must
    not disable an editor computer's sync either -- see the module
    docstring for why this is the whole point of the 2026-08-27 change."""
    app = _make_app(tmp_path, sync_enabled=True, mode="editor")
    assert app._sync_enabled is True
    _sign_in_with_role(app, "jsmith", "base")
    assert app._sync_enabled is True
    assert app.effective_mode() == "editor"


def test_no_role_from_dashboard_changes_nothing(tmp_path):
    app = _make_app(tmp_path, sync_enabled=False)
    _sign_in_with_role(app, "jsmith", None)  # older dashboard, no role field
    assert app._sync_enabled is False  # unchanged: static config still applies
    assert app.effective_mode() == "editor"  # config.toml's mode default


def test_sign_out_changes_nothing_about_sync_enabled_either(tmp_path):
    app = _make_app(tmp_path, sync_enabled=True)
    _sign_in_with_role(app, "owen", "base")
    assert app._sync_enabled is True
    app.identity.sign_out()
    app._apply_identity_role()
    assert app._sync_enabled is True  # config.toml's sync_enabled=true, still


def test_a_wired_machine_owned_by_a_non_admin_reports_base(tmp_path):
    """WP0's original case still holds, now for a simpler reason: Billy's
    office desktop works directly off the NAS, and Billy is not a dashboard
    admin -- so /verify hands his sign-in role="editor" on every one of his
    three computers. The machine's own config.toml is the ONLY thing
    effective_mode() reads now, so this was never in doubt."""
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


def test_the_admins_own_laptop_is_no_longer_punished_for_who_signed_in(tmp_path):
    """The bug that motivated this change (2026-08-27): the owner's own
    laptop, signed into the dashboard as the admin account (role="base"),
    is an ordinary editor computer with its own local_root. It must report
    "editor" and keep syncing -- the opposite of what identity.role alone
    used to decide."""
    app = _make_app(tmp_path, sync_enabled=True, mode="editor")
    _sign_in_with_role(app, "alex", "base")
    assert app.effective_mode() == "editor"
    assert app._sync_enabled is True


def _make_app(tmp_path, **overrides) -> CompanionApp:
    return CompanionApp(_cfg(tmp_path, **overrides))
