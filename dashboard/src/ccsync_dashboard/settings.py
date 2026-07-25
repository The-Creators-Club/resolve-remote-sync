"""Environment-variable configuration.

Follows the server-script conventions (server/common.py): everything comes
from env vars, nothing secret is ever hardcoded. All knobs have defaults
except the Syncthing URL/key, which the collector needs to do anything.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class Settings:
    syncthing_url: str = ""
    syncthing_api_key: str = ""
    db_path: str = "/data/dashboard.db"
    port: int = 8480
    report_token: str = ""
    # Reports are rejected when no token is configured, unless explicitly
    # opted out (lab use). The UI itself is tailnet-gated, not the API write.
    report_token_optional: bool = False

    # Login (per-editor project selection). Phase-0 verified: SMB session
    # setup on :445 is the only credential check that works for non-admin
    # TrueNAS users on 25.10 (middleware auth rejects them outright).
    auth_method: str = "smb"
    smb_host: str = "192.168.0.102"
    session_secret: str = ""            # required for login; stable across deploys
    admin_users: frozenset[str] = frozenset()  # lowercase usernames

    # TrueNAS API access for the admin "add/approve users" section (creating
    # editor accounts, setting known passwords). Optional: that section is
    # simply unavailable (503) if truenas_pw is blank, same convention as
    # server/common.py's require_env -- everything else in the dashboard
    # keeps working without it.
    truenas_host: str = "192.168.0.102"
    truenas_user: str = "truenas_admin"
    truenas_pw: str = ""
    # Test-only escape hatch: overrides the https://<host>/api/v2.0 base so
    # tests can point TrueNASClient at a plain-http fake server instead of
    # also having to fake TLS. Never set from env; production always uses
    # truenas_host.
    truenas_base_url: str = ""

    # Published companion builds (the upgrade channel). Empty = default to a
    # "packages" dir next to the SQLite file, which in production lands under
    # /data -- the only volume that survives a redeploy -- with no compose
    # change needed.
    packages_dir: str = ""

    # Auto-provisioning: when projects_dir is a mounted copy of the server's
    # Projects tree, the collector creates a Syncthing folder (and shares it
    # with every known editor device) for any project dir that lacks one.
    # Empty string disables provisioning entirely.
    projects_dir: str = ""
    # Path prefix where the SYNCTHING app (not this container) sees the same
    # tree; must match install_syncthing_app.py's --container-mount.
    syncthing_data_prefix: str = "/data/Projects"

    # Collector cadences (seconds). Overridable for tests.
    interval_provision: float = 300.0
    interval_config: float = 120.0
    interval_enforce: float = 60.0
    interval_inventory: float = 300.0
    inventory_projects_per_cycle: int = 8
    interval_connections: float = 15.0
    interval_completion: float = 30.0
    interval_remoteneed: float = 60.0
    interval_prune: float = 3600.0
    backoff_max: float = 300.0

    def packages_path(self) -> Path:
        return Path(self.packages_dir) if self.packages_dir else Path(self.db_path).parent / "packages"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env

        def num(name: str, default: float) -> float:
            raw = env.get(name, "")
            try:
                return float(raw) if raw else default
            except ValueError:
                return default

        return cls(
            syncthing_url=env.get("SYNCTHING_GUI_URL", "").rstrip("/"),
            syncthing_api_key=env.get("SYNCTHING_API_KEY", ""),
            db_path=env.get("DASH_DB_PATH", "/data/dashboard.db"),
            port=int(num("DASH_PORT", 8480)),
            report_token=env.get("DASH_REPORT_TOKEN", ""),
            report_token_optional=env.get("DASH_REPORT_TOKEN_OPTIONAL", "") == "1",
            auth_method=env.get("DASH_AUTH_METHOD", "smb"),
            smb_host=env.get("DASH_SMB_HOST", "192.168.0.102"),
            session_secret=env.get("DASH_SESSION_SECRET", ""),
            admin_users=frozenset(
                u.strip().lower() for u in env.get("DASH_ADMIN_USERS", "").split(",") if u.strip()
            ),
            truenas_host=env.get("TRUENAS_HOST", "192.168.0.102"),
            truenas_user=env.get("TRUENAS_USER", "truenas_admin"),
            truenas_pw=env.get("TRUENAS_PW", ""),
            packages_dir=env.get("DASH_PACKAGES_DIR", ""),
            projects_dir=env.get("DASH_PROJECTS_DIR", ""),
            syncthing_data_prefix=env.get("DASH_SYNCTHING_DATA_PREFIX", "/data/Projects"),
            interval_provision=num("DASH_INTERVAL_PROVISION", 300.0),
            interval_config=num("DASH_INTERVAL_CONFIG", 120.0),
            interval_enforce=num("DASH_INTERVAL_ENFORCE", 60.0),
            interval_inventory=num("DASH_INTERVAL_INVENTORY", 300.0),
            inventory_projects_per_cycle=int(num("DASH_INVENTORY_PROJECTS_PER_CYCLE", 8)),
            interval_connections=num("DASH_INTERVAL_CONNECTIONS", 15.0),
            interval_completion=num("DASH_INTERVAL_COMPLETION", 30.0),
            interval_remoteneed=num("DASH_INTERVAL_REMOTENEED", 60.0),
            interval_prune=num("DASH_INTERVAL_PRUNE", 3600.0),
            backoff_max=num("DASH_BACKOFF_MAX", 300.0),
        )
