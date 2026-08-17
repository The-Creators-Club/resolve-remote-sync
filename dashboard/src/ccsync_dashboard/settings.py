"""Environment-variable configuration.

Follows the server-script conventions (server/common.py): everything comes
from env vars, nothing secret is ever hardcoded. All knobs have defaults
except the Syncthing URL/key, which the collector needs to do anything.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

log = logging.getLogger("ccsync.dashboard.settings")

# Identity values that used to be this fleet's own addresses, hardcoded as
# defaults. Blanked 2026-08-17 (COMMERCIAL_READINESS.md item 10 /
# SYNOLOGY_PORT_PLAN.md WP0 step 1): a second site must not silently inherit
# the first site's NAS. Unset is WARNED about, never fatal -- the dashboard is
# what tells everyone whether their footage is syncing, and it keeps doing
# that with no NAS credentials at all (only /admin/users and the login probe
# depend on these).
_SITE_IDENTITY_ENV = {
    "smb_host": "DASH_SMB_HOST",
    "nas_host": "DASH_NAS_HOST (or TRUENAS_HOST)",
    "nas_user": "DASH_NAS_USER (or TRUENAS_USER)",
}


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
    # No tenant default: see _SITE_IDENTITY_ENV. Blank falls back to nas_host
    # in __post_init__ (the SMB server IS the NAS on both TrueNAS and DSM), so
    # a container whose env predates DASH_SMB_HOST -- every TrueNAS deploy
    # before 2026-08-17, until it is --recreate'd -- keeps logging editors in.
    # Only a deployment with NEITHER set fails, loudly, with the NAS's error.
    smb_host: str = ""
    session_secret: str = ""            # required for login; stable across deploys
    admin_users: frozenset[str] = frozenset()  # lowercase usernames
    # Secure flag on the session cookie. "auto" (the default) sets it only on
    # https requests, so today's plain-http LAN/tailnet deployment keeps
    # working while a future TLS front-end gets the flag for free the moment
    # it terminates https. "1"/"0" force it on/off.
    cookie_secure: str = "auto"

    # NAS API access for the admin "add/approve users" section (creating
    # editor accounts, setting known passwords). Optional: that section is
    # simply unavailable (503) if nas_pw is blank, same convention as
    # server/common.py's require_env -- everything else in the dashboard
    # keeps working without it.
    #
    # Which NAS: "truenas" (this fleet) or "synology" (SYNOLOGY_PORT_PLAN.md).
    # nas.factory.make_nas_client is the only reader; an unknown value is
    # refused there rather than falling back to a backend the operator did not
    # ask for.
    nas_kind: str = "truenas"
    nas_host: str = ""
    nas_user: str = ""
    nas_pw: str = ""
    # TLS verification for those calls (they carry the NAS password). Default
    # False preserves the existing behaviour -- the NAS presents a self-signed
    # cert -- but it is a knob: "1" to verify, or a path to a CA bundle.
    nas_verify_ssl: bool | str = False
    # Parent dir of editor homes on the NAS -- TrueNAS <pool>/homes,
    # Synology /var/services/homes. Was a tenant literal in the TrueNAS client
    # (HOME_PARENT) until 2026-08-17; now site.toml [tree] homes_parent, passed
    # into the container as DASH_NAS_HOMES_PARENT by the deploy.
    nas_homes_parent: str = ""
    # The account the dashboard STACK runs as on the NAS (site.toml [stack]
    # owner: `broll` on TrueNAS, `ccsync-svc` on DSM). Never an editor; it is
    # filtered out of every editor listing so a studio owner does not see the
    # plumbing account beside their people (2026-08-17, Users page review).
    nas_service_user: str = ""
    # Test-only escape hatch: overrides the https://<host>/... API base so
    # tests can point a backend client at a plain-http fake server instead of
    # also having to fake TLS. Never set from env; production always uses
    # nas_host.
    nas_base_url: str = ""

    # The truenas_* spelling of the five fields above, kept for one release
    # (SYNOLOGY_PORT_PLAN.md WP1, 2026-08-17). __post_init__ mirrors whichever
    # side was given onto the other, so old and new call sites read the same
    # value and neither has to know which name the caller used. The neutral
    # name wins when both are set.
    truenas_host: str = ""
    truenas_user: str = ""
    truenas_pw: str = ""
    truenas_verify_ssl: bool | str = False
    truenas_base_url: str = ""

    # ---------------------------------------------------------- site manifest
    # What GET /api/v1/site publishes: the handful of site-specific strings an
    # installer, the onboarding wizard and the companion otherwise had to be
    # told (or derive) per fleet -- SYNOLOGY_PORT_PLAN.md WP0 step 3. Every
    # one defaults to "" and is echoed verbatim: a blank field means "this
    # site has not been told", never another tenant's value. Nothing here is
    # secret (a Syncthing device ID is a public key), which is why the route
    # is open -- see api.api_site.
    site_org_name: str = ""
    site_tree_name: str = ""
    # The drive letter the editor tree is mapped at on Windows. Hardcoded to
    # P: everywhere in the companion by an explicit decision (2026-07-26); the
    # manifest states it rather than making a client guess.
    site_canonical_prefix: str = "P:\\"
    site_remote_root: str = ""
    site_smb_unc: str = ""
    site_sftp_host: str = ""
    # DSM often runs sshd off 22, and the port is implicit in today's rclone
    # stanzas (WP5).
    site_sftp_port: int = 22
    # rclone SFTP tuning the SERVER dictates, because it depends on the NAS's
    # sshd: DSM 7.2 ships OpenSSH 8.2p1, which lacks limits@openssh.com, and
    # rclone's 255Ki chunks (right for TrueNAS) truncate every download at
    # 539,000,832 bytes there -- 64Ki is that ceiling (measured 2026-08-17,
    # docs/synology-spikes-2026-08-17.md spike 6). "" / 0 = "server does not
    # say"; the companion then keeps its own default.
    site_sftp_chunk_size: str = ""
    site_sftp_concurrency: int = 0
    # rclone `shell_type` for the SFTP remote: "unix" on TrueNAS (editors have
    # a shell), "none" on Synology (editors are /sbin/nologin and rclone's
    # shell probing then fails). "" = companion/installer default ("unix").
    site_sftp_shell_type: str = ""
    site_rclone_remote: str = ""
    # Fallback only: the live Syncthing's own myID is preferred when it can be
    # read (api.api_site), because a stale ID here would point every new
    # editor at a device that no longer exists.
    site_nas_syncthing_id: str = ""
    site_dashboard_url: str = ""

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
    # Same idea for the shared asset libraries (the LUT library), which live
    # BESIDE Projects/ under Creators_Club rather than inside it -- so the
    # default is the sibling of syncthing_data_prefix's default. Blank
    # disables shared-folder provisioning without touching project folders.
    syncthing_assets_prefix: str = "/data/Assets"

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

    def __post_init__(self) -> None:
        """Keep the nas_* and truenas_* spellings of the same five values in
        lockstep, in both directions.

        Both are real fields (rather than one being a property) so that every
        existing construction site -- Settings(truenas_pw=...) in the suite,
        anything not yet migrated -- keeps working unchanged while new code
        reads settings.nas_*. The neutral name wins when a caller sets both,
        which is also what from_env does with DASH_NAS_* vs TRUENAS_*.
        """
        for neutral, legacy in (
            ("nas_host", "truenas_host"),
            ("nas_user", "truenas_user"),
            ("nas_pw", "truenas_pw"),
            ("nas_verify_ssl", "truenas_verify_ssl"),
            ("nas_base_url", "truenas_base_url"),
        ):
            new_value = getattr(self, neutral)
            old_value = getattr(self, legacy)
            effective = new_value if new_value else old_value
            object.__setattr__(self, neutral, effective)
            object.__setattr__(self, legacy, effective)
        # See smb_host: the SMB probe target defaults to the NAS itself. A
        # deploy that ran before DASH_SMB_HOST existed in the compose env would
        # otherwise refuse every login the moment this code lands (found by the
        # 2026-08-17 Synology bring-up; also true for the TrueNAS redeploy).
        if not self.smb_host and self.nas_host:
            object.__setattr__(self, "smb_host", self.nas_host)

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

        def verify_ssl(*names: str) -> bool | str:
            raw = ""
            for name in names:
                raw = env.get(name, "").strip()
                if raw:
                    break
            if not raw or raw.lower() in ("0", "false", "no"):
                return False
            if raw.lower() in ("1", "true", "yes"):
                return True
            return raw   # a CA bundle path inside the container

        def first(*names: str) -> str:
            """The first of `names` that is set, so DASH_NAS_* wins over the
            TRUENAS_* spelling it replaced (kept for one release, WP1)."""
            for name in names:
                value = env.get(name, "")
                if value:
                    return value
            return ""

        settings = cls(
            syncthing_url=env.get("SYNCTHING_GUI_URL", "").rstrip("/"),
            syncthing_api_key=env.get("SYNCTHING_API_KEY", ""),
            db_path=env.get("DASH_DB_PATH", "/data/dashboard.db"),
            port=int(num("DASH_PORT", 8480)),
            report_token=env.get("DASH_REPORT_TOKEN", ""),
            report_token_optional=env.get("DASH_REPORT_TOKEN_OPTIONAL", "") == "1",
            auth_method=env.get("DASH_AUTH_METHOD", "smb"),
            smb_host=env.get("DASH_SMB_HOST", ""),
            session_secret=env.get("DASH_SESSION_SECRET", ""),
            admin_users=frozenset(
                u.strip().lower() for u in env.get("DASH_ADMIN_USERS", "").split(",") if u.strip()
            ),
            cookie_secure=(env.get("DASH_COOKIE_SECURE", "").strip().lower() or "auto"),
            nas_kind=(env.get("DASH_NAS_KIND", "").strip().lower() or "truenas"),
            nas_host=first("DASH_NAS_HOST", "TRUENAS_HOST"),
            nas_user=first("DASH_NAS_USER", "TRUENAS_USER"),
            nas_pw=first("DASH_NAS_PW", "TRUENAS_PW"),
            nas_verify_ssl=verify_ssl("DASH_NAS_VERIFY_SSL", "TRUENAS_VERIFY_SSL"),
            nas_homes_parent=env.get("DASH_NAS_HOMES_PARENT", "").strip().rstrip("/"),
            nas_service_user=env.get("DASH_NAS_SERVICE_USER", "").strip(),
            site_org_name=env.get("DASH_SITE_ORG_NAME", "").strip(),
            site_tree_name=env.get("DASH_SITE_TREE_NAME", "").strip(),
            site_canonical_prefix=env.get("DASH_SITE_CANONICAL_PREFIX", "").strip() or "P:\\",
            site_remote_root=env.get("DASH_SITE_REMOTE_ROOT", "").strip(),
            site_smb_unc=env.get("DASH_SITE_SMB_UNC", "").strip(),
            site_sftp_host=env.get("DASH_SITE_SFTP_HOST", "").strip(),
            site_sftp_port=int(num("DASH_SITE_SFTP_PORT", 22)),
            site_sftp_chunk_size=env.get("DASH_SITE_SFTP_CHUNK_SIZE", "").strip(),
            site_sftp_concurrency=int(num("DASH_SITE_SFTP_CONCURRENCY", 0)),
            site_sftp_shell_type=env.get("DASH_SITE_SFTP_SHELL_TYPE", "").strip(),
            site_rclone_remote=env.get("DASH_SITE_RCLONE_REMOTE", "").strip(),
            site_nas_syncthing_id=env.get("DASH_SITE_NAS_SYNCTHING_ID", "").strip(),
            site_dashboard_url=env.get("DASH_SITE_DASHBOARD_URL", "").strip().rstrip("/"),
            broll_enabled=env.get("DASH_BROLL_ENABLED", "") == "1",
            broll_ingest_token=env.get("BROLL_INGEST_TOKEN", "").strip(),
            packages_dir=env.get("DASH_PACKAGES_DIR", ""),
            projects_dir=env.get("DASH_PROJECTS_DIR", ""),
            syncthing_data_prefix=env.get("DASH_SYNCTHING_DATA_PREFIX", "/data/Projects"),
            syncthing_assets_prefix=env.get("DASH_SYNCTHING_ASSETS_PREFIX", "/data/Assets"),
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
        settings.warn_about_unset_identity()
        return settings

    def warn_about_unset_identity(self) -> None:
        """Say once, loudly, which site-identity values this deployment is
        missing -- and carry on. These had hardcoded defaults until
        2026-08-17, so an operator upgrading into this release gets a log line
        naming the env vars they now have to set, instead of a login page that
        quietly fails against a NAS that isn't theirs.
        """
        missing = [var for attr, var in _SITE_IDENTITY_ENV.items() if not getattr(self, attr, "")]
        if missing:
            log.warning(
                "site identity not fully configured: %s unset. The dashboard still runs; "
                "editor login (SMB probe) and the admin Users section are what need these.",
                ", ".join(missing),
            )
