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
    # Secure flag on the session cookie. "auto" (the default) sets it only on
    # https requests, so today's plain-http LAN/tailnet deployment keeps
    # working while a future TLS front-end gets the flag for free the moment
    # it terminates https. "1"/"0" force it on/off.
    cookie_secure: str = "auto"

    # TrueNAS API access for the admin "add/approve users" section (creating
    # editor accounts, setting known passwords). Optional: that section is
    # simply unavailable (503) if truenas_pw is blank, same convention as
    # server/common.py's require_env -- everything else in the dashboard
    # keeps working without it.
    truenas_host: str = "192.168.0.102"
    truenas_user: str = "truenas_admin"
    truenas_pw: str = ""
    # TLS verification for those calls (they carry TRUENAS_PW). Default False
    # preserves the existing behaviour -- the NAS presents a self-signed cert
    # -- but it is a knob now: "1" to verify, or a path to a CA bundle.
    truenas_verify_ssl: bool | str = False
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

    # Serve the b-roll search UI at /broll from inside this process, so editors
    # get one URL and one login instead of a second service to reach and sign
    # in to. Off by default: the dashboard must not depend on the b-roll code
    # being present, and a deployment without it should behave exactly as
    # before. See broll.py.
    broll_enabled: bool = False
    # Shared secret the indexer presents as X-Ingest-Token to write into the
    # b-roll database. MANDATORY when broll_enabled: create_app refuses to
    # build an app with a blank, placeholder or short one rather than serve a
    # write path that a session cookie alone can reach (see
    # broll.check_ingest_token). Read from the same env var the b-roll app
    # itself reads, so the two can never disagree.
    broll_ingest_token: str = ""

    # Auto-provisioning: when projects_dir is a mounted copy of the server's
    # Projects tree, the collector creates a Syncthing folder (and shares it
    # with every known editor device) for any project dir that lacks one.
    # Empty string disables provisioning entirely.
    projects_dir: str = ""
    # Path prefix where the SYNCTHING app (not this container) sees the same
    # tree; must match install_syncthing_app.py's --container-mount.
    syncthing_data_prefix: str = "/data/Projects"

    # The NAS's TAILNET (100.x) address. When set, new Syncthing device
    # entries are created with tcp:// and quic:// addresses on it BEFORE
    # "dynamic", so an editor dials the tailnet directly instead of learning
    # the NAS's public address from global discovery and then falling back to
    # the public relay pool (AUDIT_2 P3). Empty = today's ["dynamic"] only.
    # Only helps once the NAS's 22000 tcp+udp is reachable on that IP through
    # the Syncthing app's container NAT -- verify before setting it.
    syncthing_tailnet_ip: str = ""
    # OPT-IN, and deliberately defaulted OFF: disable Syncthing's relays,
    # global discovery and NAT traversal so lane C is tailnet-or-nothing.
    # Measured on this fleet, the NAS Tailscale peer currently has an empty
    # CurAddr (DERP-relayed), so enabling this today would STOP lane C, not
    # accelerate it. Confirm a direct path first.
    syncthing_tailnet_only: bool = False

    # Collector cadences (seconds). Overridable for tests.
    interval_provision: float = 300.0
    interval_config: float = 120.0
    interval_enforce: float = 60.0
    # 900, not 300 (AUDIT_2 P12/§4.2): _dir_signature is dir-mtime-only, so
    # every new file lane A uploads changes its directory's mtime and the
    # FULL per-file walk re-runs each cycle -- 100k stats plus a full
    # replace_nas_media SQLite rewrite every 5 minutes, on the box
    # simultaneously serving SFTP and Syncthing, precisely while it is being
    # uploaded into. Trade-off: inventory freshness drops from 5 to 15 min.
    interval_inventory: float = 900.0
    inventory_projects_per_cycle: int = 8
    interval_connections: float = 15.0
    # 60, not 30 (AUDIT_2 P13): completion polling scales as
    # folders x devices, /rest/db/completion is computed on demand, and that
    # CPU comes off the Syncthing app that is supposed to be moving lane C
    # bytes. Trade-off: dashboard percentages update half as often.
    interval_completion: float = 60.0
    interval_remoteneed: float = 60.0
    interval_prune: float = 3600.0
    backoff_max: float = 300.0
    # Blast-radius brake on the enforce cycle: an enforce pass that would
    # unshare MORE than this many devices is refused (additions still apply)
    # and logged as an ERROR. A mass unshare is never a normal outcome -- it
    # means the config snapshot was bad. Raise it to override deliberately.
    enforce_max_share_removals: int = 3

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

        def verify_ssl(name: str) -> bool | str:
            raw = env.get(name, "").strip()
            if not raw or raw.lower() in ("0", "false", "no"):
                return False
            if raw.lower() in ("1", "true", "yes"):
                return True
            return raw   # a CA bundle path inside the container

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
            cookie_secure=(env.get("DASH_COOKIE_SECURE", "").strip().lower() or "auto"),
            truenas_host=env.get("TRUENAS_HOST", "192.168.0.102"),
            truenas_user=env.get("TRUENAS_USER", "truenas_admin"),
            truenas_pw=env.get("TRUENAS_PW", ""),
            truenas_verify_ssl=verify_ssl("TRUENAS_VERIFY_SSL"),
            broll_enabled=env.get("DASH_BROLL_ENABLED", "") == "1",
            broll_ingest_token=env.get("BROLL_INGEST_TOKEN", "").strip(),
            packages_dir=env.get("DASH_PACKAGES_DIR", ""),
            projects_dir=env.get("DASH_PROJECTS_DIR", ""),
            syncthing_data_prefix=env.get("DASH_SYNCTHING_DATA_PREFIX", "/data/Projects"),
            syncthing_tailnet_ip=env.get("DASH_SYNCTHING_TAILNET_IP", "").strip(),
            syncthing_tailnet_only=env.get("DASH_SYNCTHING_TAILNET_ONLY", "") == "1",
            interval_provision=num("DASH_INTERVAL_PROVISION", 300.0),
            interval_config=num("DASH_INTERVAL_CONFIG", 120.0),
            interval_enforce=num("DASH_INTERVAL_ENFORCE", 60.0),
            interval_inventory=num("DASH_INTERVAL_INVENTORY", 900.0),
            inventory_projects_per_cycle=int(num("DASH_INVENTORY_PROJECTS_PER_CYCLE", 8)),
            interval_connections=num("DASH_INTERVAL_CONNECTIONS", 15.0),
            interval_completion=num("DASH_INTERVAL_COMPLETION", 60.0),
            interval_remoteneed=num("DASH_INTERVAL_REMOTENEED", 60.0),
            interval_prune=num("DASH_INTERVAL_PRUNE", 3600.0),
            backoff_max=num("DASH_BACKOFF_MAX", 300.0),
            enforce_max_share_removals=int(num("DASH_ENFORCE_MAX_REMOVALS", 3)),
        )
