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
def _looks_like_ed25519_pubkey(value: str) -> bool:
    """base64 of exactly 32 bytes (COMMERCIAL_READINESS.md item 4, 2026-08-17)."""
    import base64

    if not value:
        return False
    try:
        return len(base64.b64decode(value, validate=True)) == 32
    except Exception:
        return False


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
    # Whether the ONE shared fleet token above is still accepted, alongside the
    # per-editor tokens an admin mints on the Users page (COMMERCIAL_READINESS.md
    # item 15, 2026-08-17). True today because every deployed companion holds
    # only the shared token, and turning it off before the fleet has migrated
    # takes every machine off the dashboard at once. TURN IT OFF
    # (DASH_SHARED_REPORT_TOKEN_ENABLED=0) once the boot log stops naming
    # machines on the shared credential -- that is the whole point of the
    # per-editor tokens: revocable per person, and not one leak away from the
    # entire fleet.
    shared_report_token_enabled: bool = True

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
    # Whose X-Forwarded-Proto is believed (COMMERCIAL_READINESS.md item 6/H1,
    # 2026-08-17). It used to be everyone's: any host on the tailnet could
    # send the header and decide whether the Secure flag went on. csv of IPs
    # and/or CIDRs; the default is loopback only, which is where Tailscale
    # Serve and a compose-network sidecar both arrive. A dashboard published
    # through a proxy on the DOCKER HOST is seen as coming from the bridge
    # gateway (e.g. 172.17.0.1) -- add it here, or set DASH_COOKIE_SECURE=1
    # and skip the question entirely (which is the documented recipe).
    trusted_proxies: str = "127.0.0.1,::1"
    # Server-side session lifetimes (seconds). Idle is refreshed by activity,
    # absolute never is. See sessions.py.
    session_idle_seconds: float = 12 * 3600
    session_absolute_seconds: float = 7 * 24 * 3600
    # THE test/dev escape hatch, and the only one. It turns off the boot-time
    # secret-strength refusal and the "an unknown session id is not a session"
    # rule, both of which the suite would otherwise trip on every hand-minted
    # cookie and every `session_secret="test-secret"`. create_app also honours
    # the DASH_DEV_INSECURE env var, the same way it honours BROLL_INGEST_TOKEN
    # from the environment, so the suite can set it once. It is logged, loudly,
    # at every boot: it must never be set on a deployment.
    dev_insecure: bool = False

    # ---------------------------------------------------------------- OIDC
    # DASH_AUTH_METHOD=oidc (COMMERCIAL_READINESS.md item 12, 2026-08-17). The
    # seam already existed with one implementation ("smb"); this is the second.
    # Blank issuer + method "oidc" is refused at boot rather than silently
    # falling back to passwords.
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_scopes: str = "openid profile email"
    # The claim the REST of the dashboard keys on. Every join in this app --
    # Syncthing device names, selections, NAS accounts -- is a NAS username, so
    # the IdP has to be told to publish one that matches. preferred_username is
    # what Keycloak/Authentik/Entra all put a login name in.
    oidc_username_claim: str = "preferred_username"
    # Admin mapping: a claim to look at (e.g. "groups" or "roles") and the
    # value(s) that grant admin. Empty claim = admin comes from
    # DASH_ADMIN_USERS alone, which is the safe default.
    oidc_admin_claim: str = ""
    oidc_admin_values: frozenset[str] = frozenset()
    # Absolute redirect URI registered with the IdP. Blank = derived from the
    # request, which is right behind a single known front-end and wrong behind
    # anything that rewrites Host -- so it is settable.
    oidc_redirect_url: str = ""

    # ------------------------------------------------------- local accounts
    # DASH_AUTH_METHOD=local (WP C, docs/ZERO_TOUCH_PLAN.md §3.3, 2026-08-17):
    # local_users.py is the identity provider instead of an SMB probe against
    # a NAS -- see auth.verify_credentials/is_admin. Nothing else is needed
    # here; the tables live in the same dashboard.db every other migration
    # already writes.

    # The bearer token internal_sftp.py's two routes require (CCSYNC_INTERNAL_TOKEN).
    # Blank is a valid, common state: a deployment with no sftp sidecar yet
    # (every fleet before WP C ships) needs neither route, and the routes
    # themselves answer 503 rather than authenticating everyone when this is
    # unset -- see internal_sftp._configured_token, which also tries a file
    # under <data dir>/secrets/ (agent D's wizard-generated secret) before
    # giving up.
    internal_token: str = ""

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
    # A SCOPED TrueNAS API key, PREFERRED over nas_pw when both are set
    # (DASH_NAS_API_KEY / TRUENAS_API_KEY, written by the deploy). The password
    # in this container is root-equivalent and readable with `docker inspect`
    # or from any code execution inside it, while this UI only ever calls
    # user/group/sharing.smb -- COMMERCIAL_READINESS.md item 6, finding H3.
    # Mint one with `python server/create_api_key.py`. TrueNAS only: DSM has no
    # API-key concept, so a Synology site keeps using the password.
    nas_api_key: str = ""
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
    # The same organisation, short enough for a topbar or a tray tooltip
    # ("CC" for "Creators Club"). Blank means "use org_name"; both blank means
    # "use the product name", which is what an unbranded install shows
    # (2026-08-17, COMMERCIAL_READINESS.md item 10).
    site_org_short: str = ""
    # THE VENDOR'S product name, not the customer's -- it is the one brand
    # string in this file that has a non-blank default, because every
    # deployment is running the same product and a blank window title helps
    # nobody. A reseller who ships this under their own name sets it.
    site_product_name: str = "CC Sync"
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

    # OPTIONAL FEATURES this site has turned on, published in the manifest as
    # `features` (COMMERCIAL_READINESS.md items 2 + 3, 2026-08-17). BOTH
    # DEFAULT OFF, and off is the vendor build's shape: the customer decides
    # whether downloading third-party YouTube material is lawful for them, so
    # /ytdl is not mounted, the fleet download routes 404 and every companion
    # hides its YouTube items until this site says otherwise
    # (docs/legal/YOUTUBE_FEATURE_NOTICE.md).
    #
    # `youtube_unblock` is narrower still and is the customer asserting they
    # may get past YouTube's anti-automation measures: it is what provisions
    # the PO-token provider, the deno n-challenge solver and the cookie
    # sign-in. It means nothing without site_feature_youtube_download.
    site_feature_youtube_download: bool = False
    site_feature_youtube_unblock: bool = False

    # Published companion builds (the upgrade channel). Empty = default to a
    # "packages" dir next to the SQLite file, which in production lands under
    # /data -- the only volume that survives a redeploy -- with no compose
    # change needed.
    packages_dir: str = ""

    # Base64 Ed25519 public keys the publish route accepts release signatures
    # from (DASH_RELEASE_PUBKEYS, comma- or whitespace-separated). Empty means
    # the upgrade channel is UNAUTHENTICATED, and publishing is refused rather
    # than falling back -- a dashboard that will accept an unsigned build is
    # one compromise away from handing the fleet an arbitrary binary it then
    # renames over the running companion (COMMERCIAL_READINESS.md item 4,
    # 2026-08-17). A customer's dashboard pins the VENDOR's key here; a vendor
    # rotating a key lists both for the overlap release.
    release_pubkeys: tuple[str, ...] = ()

    # The vendor-hosted signed feed (ZERO_TOUCH_PLAN.md WP E, 2026-08-17):
    # "we publish once, every dashboard pulls". Empty = the feed is DISABLED
    # and the dashboard behaves exactly as it did before this existed -- no
    # background thread, no network call, no admin section beyond "how to
    # configure it". Must be https (release_feed.py refuses anything else at
    # fetch time, same as the no-redirect rule the companion's own upgrade
    # client already enforces against the dashboard itself).
    release_feed_url: str = ""
    # manual   = "Check now" / "Publish" are the only ways a feed build ever
    #            reaches this dashboard's packages -- the default, because an
    #            unattended write to the upgrade channel is not something a
    #            fresh install should opt into by omission.
    # stage    = new feed records are auto-published but never made current
    #            (an admin still flips [ MAKE CURRENT ]).
    # current  = auto-published AND made current -- full hands-off. An
    #            invalid value falls back to "manual" with a boot warning
    #            (see __post_init__) rather than silently picking a stronger
    #            posture than asked for.
    release_feed_policy: str = "manual"
    # Poll cadence in seconds for the background thread started in app.py's
    # lifespan (guarded by release_feed_url being set). Default matches "we
    # check daily, and on demand" from the plan.
    release_feed_interval: float = 86400.0

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
        # DASH_DEV_INSECURE is honoured from the environment even for a
        # hand-built Settings (2026-08-17, COMMERCIAL_READINESS.md item 15).
        # The dashboard's suite constructs Settings(...) directly in sixteen
        # files with a deliberately weak `session_secret` and hand-minted
        # cookies; making the one dev flag reachable here is what lets the
        # boot-time secret floor and the unknown-session rule be strict
        # EVERYWHERE ELSE instead of being softened into uselessness. Same
        # precedent as create_app reading BROLL_INGEST_TOKEN from the
        # environment.
        if not self.dev_insecure and os.environ.get("DASH_DEV_INSECURE", "") == "1":
            object.__setattr__(self, "dev_insecure", True)
        # DASH_REPORT_TOKEN_OPTIONAL is one env var away from unauthenticated
        # writes to the fleet's status, so it is no longer a shipped code path
        # (COMMERCIAL_READINESS.md item 15): it now does nothing at all unless
        # the dev flag is also on, and says so.
        if self.report_token_optional and not self.dev_insecure:
            object.__setattr__(self, "report_token_optional", False)
            log.error(
                "DASH_REPORT_TOKEN_OPTIONAL is set but IGNORED: it makes /api/v1/report "
                "an unauthenticated write path and is not a shipped configuration. Set "
                "DASH_REPORT_TOKEN instead (a lab may set DASH_DEV_INSECURE=1 as well)."
            )
        # See smb_host: the SMB probe target defaults to the NAS itself. A
        # deploy that ran before DASH_SMB_HOST existed in the compose env would
        # otherwise refuse every login the moment this code lands (found by the
        # 2026-08-17 Synology bring-up; also true for the TrueNAS redeploy).
        if not self.smb_host and self.nas_host:
            object.__setattr__(self, "smb_host", self.nas_host)
        # An unrecognised DASH_RELEASE_FEED_POLICY falls back to the safest
        # posture ("manual") rather than being coerced upward -- a typo must
        # never turn into unattended auto-current (ZERO_TOUCH_PLAN.md WP E,
        # 2026-08-17).
        if self.release_feed_policy not in ("manual", "stage", "current"):
            log.warning(
                "DASH_RELEASE_FEED_POLICY=%r is not one of manual/stage/current -- "
                "using manual", self.release_feed_policy,
            )
            object.__setattr__(self, "release_feed_policy", "manual")

    def packages_path(self) -> Path:
        return Path(self.packages_dir) if self.packages_dir else Path(self.db_path).parent / "packages"

    def secrets_path(self, name: str) -> Path:
        """<data dir>/secrets/<name> -- the directory agent D's SetupEngine
        generates first-boot secrets into (docs/ZERO_TOUCH_PLAN.md §3.2's
        "openssl rand x5" row); this dashboard only ever READS from it."""
        return Path(self.db_path).parent / "secrets" / name

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
            # Default TRUE, and only an explicit "0" turns it off: a typo in
            # this variable must not silently disconnect the fleet.
            shared_report_token_enabled=(
                env.get("DASH_SHARED_REPORT_TOKEN_ENABLED", "").strip() != "0"),
            auth_method=env.get("DASH_AUTH_METHOD", "smb"),
            smb_host=env.get("DASH_SMB_HOST", ""),
            session_secret=env.get("DASH_SESSION_SECRET", ""),
            admin_users=frozenset(
                u.strip().lower() for u in env.get("DASH_ADMIN_USERS", "").split(",") if u.strip()
            ),
            cookie_secure=(env.get("DASH_COOKIE_SECURE", "").strip().lower() or "auto"),
            trusted_proxies=(env.get("DASH_TRUSTED_PROXIES", "").strip() or "127.0.0.1,::1"),
            session_idle_seconds=num("DASH_SESSION_IDLE_SECONDS", 12 * 3600),
            session_absolute_seconds=num("DASH_SESSION_ABSOLUTE_SECONDS", 7 * 24 * 3600),
            dev_insecure=env.get("DASH_DEV_INSECURE", "") == "1",
            oidc_issuer=env.get("DASH_OIDC_ISSUER", "").strip().rstrip("/"),
            oidc_client_id=env.get("DASH_OIDC_CLIENT_ID", "").strip(),
            oidc_client_secret=env.get("DASH_OIDC_CLIENT_SECRET", ""),
            oidc_scopes=(env.get("DASH_OIDC_SCOPES", "").strip() or "openid profile email"),
            oidc_username_claim=(env.get("DASH_OIDC_USERNAME_CLAIM", "").strip()
                                 or "preferred_username"),
            oidc_admin_claim=env.get("DASH_OIDC_ADMIN_CLAIM", "").strip(),
            oidc_admin_values=frozenset(
                v.strip().lower() for v in env.get("DASH_OIDC_ADMIN_VALUES", "").split(",")
                if v.strip()
            ),
            oidc_redirect_url=env.get("DASH_OIDC_REDIRECT_URL", "").strip(),
            internal_token=env.get("CCSYNC_INTERNAL_TOKEN", "").strip(),
            nas_kind=(env.get("DASH_NAS_KIND", "").strip().lower() or "truenas"),
            nas_host=first("DASH_NAS_HOST", "TRUENAS_HOST"),
            nas_user=first("DASH_NAS_USER", "TRUENAS_USER"),
            nas_pw=first("DASH_NAS_PW", "TRUENAS_PW"),
            nas_api_key=first("DASH_NAS_API_KEY", "TRUENAS_API_KEY"),
            nas_verify_ssl=verify_ssl("DASH_NAS_VERIFY_SSL", "TRUENAS_VERIFY_SSL"),
            nas_homes_parent=env.get("DASH_NAS_HOMES_PARENT", "").strip().rstrip("/"),
            nas_service_user=env.get("DASH_NAS_SERVICE_USER", "").strip(),
            site_org_name=env.get("DASH_SITE_ORG_NAME", "").strip(),
            site_org_short=env.get("DASH_SITE_ORG_SHORT", "").strip(),
            site_product_name=env.get("DASH_SITE_PRODUCT_NAME", "").strip() or "CC Sync",
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
            # "1" and nothing else, matching DASH_BROLL_ENABLED: an unset,
            # empty, misspelt or "true"-shaped value all mean OFF, because the
            # off state is the one that is safe to be wrong about here.
            site_feature_youtube_download=env.get("DASH_SITE_YOUTUBE_DOWNLOAD", "") == "1",
            site_feature_youtube_unblock=env.get("DASH_SITE_YOUTUBE_UNBLOCK", "") == "1",
            broll_enabled=env.get("DASH_BROLL_ENABLED", "") == "1",
            broll_ingest_token=env.get("BROLL_INGEST_TOKEN", "").strip(),
            packages_dir=env.get("DASH_PACKAGES_DIR", ""),
            # Only entries that actually decode to a 32-byte Ed25519 key are
            # kept: the shipped compose sets "REPLACE_ME", and a placeholder
            # left in place must produce "no release key configured" (a 503
            # naming the variable) rather than "signature rejected" on every
            # publish, which reads like a broken signing key instead of an
            # unfinished deployment.
            release_pubkeys=tuple(
                k for k in (
                    part.strip()
                    for part in env.get("DASH_RELEASE_PUBKEYS", "").replace(",", " ").split()
                ) if _looks_like_ed25519_pubkey(k)
            ),
            release_feed_url=env.get("DASH_RELEASE_FEED_URL", "").strip(),
            release_feed_policy=(env.get("DASH_RELEASE_FEED_POLICY", "").strip().lower() or "manual"),
            release_feed_interval=num("DASH_RELEASE_FEED_INTERVAL", 86400.0),
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
