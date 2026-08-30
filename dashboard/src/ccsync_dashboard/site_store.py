"""The site manifest as DATA (ZERO_TOUCH_PLAN.md WP D / §3.2, §5, 2026-08-17).

Until now `GET /api/v1/site` (api.py) republished `DASH_SITE_*` environment
variables verbatim -- set once at deploy time by `install_dashboard_app.py`,
changeable only by `--recreate`ing the container. An appliance customer has
no shell to set an env var in (§1's bar), so the wizard's "Your studio" step
(§3.5 step 3) has to be able to WRITE this, and the write has to survive a
redeploy without a compose edit. This module is that write path: a
`site_settings` table (key/value, `db.py` migration v18) that `api_site`
prefers over the environment.

**Precedence, per key: the DB row if one exists, else the `Settings` object's
`site_*` value (which is itself env-or-default), else "".** This is what
makes the switch invisible to every deployment running today: the table
starts empty, so every existing TrueNAS/Synology site keeps serving exactly
the `DASH_SITE_*` values it always has (`tests/test_site.py` pins the
response of an env-only app byte-for-byte) until an admin visits Settings and
saves something, or the one-time seed below runs.

**The seed.** On first boot, if the table is EMPTY and the process
environment carries any `DASH_SITE_*` variable, those values are copied into
the table once (`seed_from_env_once`, called from `app.py`'s lifespan). After
that the DB is authoritative -- a LATER change to the container's env is
*not* picked up, on purpose: once an admin (or the seed) has put a value in
the DB, silently overriding it from an env var the operator may not even
remember setting would be exactly the "wrong-tenant support incident"
`ARCHITECTURE.md` §6 already warns the open route about, just moved from
"another site's value" to "a stale value from six deploys ago". A deployment
that never sets any `DASH_SITE_*` (a fresh appliance) never seeds: the table
stays empty until the wizard's own writes populate it, and until then the
manifest serves the built-in defaults (`P:\\`, `CC Sync`, ...), which is
exactly "the wizard's answers" before anyone has answered anything.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from typing import Any, Iterable, Mapping

log = logging.getLogger("ccsync.dashboard.site_store")

TABLE = "site_settings"

# Every key this store owns, and how to read/write it. `kind` decides
# validation AND how `resolved_manifest` shapes the value for API/template
# consumers: "str" (trimmed, control-chars refused), "int", "bool" (stored as
# "1"/"0" text, per the work package), "csv" (comma list, stored/joined the
# same way DASH_SITE_TEMPLATE_FOLDERS already is in provision.py).
#
# Deliberately exactly the manifest fields named in the work package -- not
# `video_extensions` (product-fixed, never site data, see provision.py) and
# not report/session secrets (secrets_boot.py's job, never this table: a
# database backup must not be a working fleet credential any more than
# editor_report_tokens is, see db.py SCHEMA_V15).
KEYS: dict[str, str] = {
    "org_name": "str",
    "org_short": "str",
    "product_name": "str",
    # The tray/window mark every editor in this fleet wears -- a bare asset
    # name the companion build ships, or an absolute path on the editor's
    # machine. Blank = the product's own mark (2026-08-18).
    "brand_logo": "str",
    "tree_name": "str",
    "canonical_prefix": "str",
    "remote_root": "str",
    "smb_unc": "str",
    "sftp_host": "str",
    "sftp_port": "int",
    "sftp_chunk_size": "str",
    "sftp_concurrency": "int",
    "sftp_shell_type": "str",
    "rclone_remote": "str",
    "nas_syncthing_id": "str",
    "dashboard_url": "str",
    "template_folders": "csv",
    "shared_asset_folders": "csv",
    "nas_kind": "str",
    "features.youtube_download": "bool",
    "features.youtube_unblock": "bool",
    # Whether the YouTube downloader may use a Claude Code / Codex CLI the
    # CUSTOMER installed on the dashboard host (2026-08-18, ai_providers.py).
    # A site feature like the two above -- so it is settable here, importable
    # from a site.toml `[features]` block and exportable -- but deliberately
    # NOT published by `api_site`: no companion, installer or indexer has any
    # use for it, and the open manifest gains a field only when a client
    # needs one.
    "features.ai_cli_providers": "bool",
    # Whether editors' companions apply a published build without anyone
    # clicking (2026-08-18). Published by api_site, unlike ai_cli_providers:
    # the companion is exactly the client that needs to read it.
    "features.auto_update": "bool",
    # Which LOCAL vision model the b-roll indexer loads -- "good" (Qwen3-VL
    # 4B) or "best" (Qwen3-VL 8B), chosen by how much VRAM the indexing
    # machine has (2026-08-18). Validated against MODEL_TIERS in validate()
    # below, the same way canonical_prefix gets its own special-cased
    # validator rather than the generic "str" one.
    "indexer_model_tier": "str",
    # The Android app (MOBILE_PLAN.md §4 M5, 2026-08-30). A TWA is only a real
    # app -- no URL bar -- if the ORIGIN vouches for the APK, so the dashboard
    # has to serve `/.well-known/assetlinks.json` naming the package and every
    # certificate allowed to sign it. Site data, not product data: each studio
    # signs its own build, and an appliance customer has no shell to drop a
    # file in. A LIST of fingerprints because a hand-over (upload key ->
    # release key, or a rebuilt debug key) has two valid signers at once, and
    # dropping the old one mid-rollout bricks every installed copy.
    "android.package_name": "str",
    "android.sha256_cert_fingerprints": "csv",
}

# What `keytool -list` and Play Console both print: 32 hex byte pairs, colon
# separated. Pinned as a regex because a fingerprint that is one pair short
# (or that arrived with the "SHA256: " label still attached) produces an
# assetlinks.json Chrome silently refuses -- and "silently" is the whole
# problem docs/ANDROID.md leads with (2026-08-30).
_FINGERPRINT_RE = None      # compiled lazily below, next to its validator

# A Java package name, which is what Android requires of an application id:
# dot-separated segments, each starting with a letter or underscore. Not a
# hostname: `tools/android/twa_manifest.py` reverses the origin's host into
# one and has to repair labels a DNS name allows and Java does not (a leading
# digit, a hyphen), so this check is what proves it did.
_PACKAGE_SEGMENT_RE = None

# The two model tiers the b-roll indexer ships, and the only values
# `indexer_model_tier` accepts. Mirrors broll/indexer's `local_models.TIERS`
# labels ("good"/"best") -- the indexer reads this exact spelling out of the
# manifest, so it must never drift from what that module expects.
MODEL_TIERS = ("good", "best")

# Which keys are DERIVED once the Tailscale sidecar (WP B) and the SFTP
# sidecar (WP C) exist -- read-only in the Settings UI whenever a live value
# is available, per the work package. Listed here (not computed) because
# ui.py's admin_settings.html needs to know which fields to grey out without
# importing WP B/C's not-yet-existing modules; each is re-checked against a
# live value at render time (ui.page_admin_settings), so a deployment without
# WP B/C simply never greys them out.
AUTO_DERIVED_KEYS = frozenset({"dashboard_url", "sftp_host", "nas_syncthing_id"})

# UX-21 (resilience sweep 2026-08-28): the three keys both installers and
# every companion read out of the manifest, per that finding's own wording --
# a SAVE that changes one of these gets the same site_history snapshot an
# IMPORT does, not just an import.
TREE_KEYS = ("canonical_prefix", "tree_name", "remote_root")

# Substrings that make a key name look secret-shaped. None of KEYS matches
# today -- a report/session secret or an AI provider key never lives in this
# table, by design (see this module's docstring) -- but the import diff and
# the undo response (UX-21, resilience sweep 2026-08-28) put arbitrary
# site_settings values on the wire, so a key added later that LOOKS like one
# is masked here rather than trusted to stay off this table forever.
_SECRET_KEY_HINTS = ("password", "secret", "token", "api_key", "apikey", "private_key")

_CANONICAL_PREFIX_WINDOWS_RE = None  # set below, after re import


class SiteValidationError(ValueError):
    """A value that failed KEYS' validation. `.key` is which one."""

    def __init__(self, key: str, message: str) -> None:
        super().__init__(f"{key}: {message}")
        self.key = key


def _validate_canonical_prefix(value: str) -> str:
    import re

    value = value.strip()
    if not value:
        raise SiteValidationError("canonical_prefix", "must not be blank")
    if re.match(r"^[A-Za-z]:\\?$", value):
        return value if value.endswith("\\") else value + "\\"
    if value.startswith("/") and ".." not in value.split("/"):
        return value.rstrip("/") or "/"
    raise SiteValidationError(
        "canonical_prefix",
        "must be a Windows drive letter like 'P:\\\\' or a POSIX absolute path like '/mnt/tree'",
    )


def _validate_int(key: str, raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    try:
        value = int(raw)
    except ValueError:
        raise SiteValidationError(key, f"{raw!r} is not a whole number")
    if value < 0:
        raise SiteValidationError(key, "must not be negative")
    return str(value)


def _validate_bool(key: str, raw: str) -> str:
    """"1"/"0" only (matching DASH_SITE_YOUTUBE_* / DASH_BROLL_ENABLED's own
    rule: an unset, empty, misspelt or "true"-shaped value is never silently
    accepted as one of the two states -- the caller must say which)."""
    raw = raw.strip()
    if raw in ("1", "0", ""):
        return raw or "0"
    raise SiteValidationError(key, "must be '1' or '0'")


def _validate_str(key: str, raw: str) -> str:
    raw = str(raw or "").strip()
    if any(ord(ch) < 32 for ch in raw):
        raise SiteValidationError(key, "must not contain control characters")
    return raw


def _validate_model_tier(raw: str) -> str:
    value = str(raw or "").strip().lower()
    if value not in MODEL_TIERS:
        raise SiteValidationError(
            "indexer_model_tier",
            f"must be one of {', '.join(MODEL_TIERS)} (got {raw!r})",
        )
    return value


def _validate_csv(key: str, raw: str) -> str:
    items = [p.strip() for p in str(raw or "").split(",")]
    items = [p for p in items if p]
    for item in items:
        if any(ord(ch) < 32 for ch in item):
            raise SiteValidationError(key, "must not contain control characters")
    return ",".join(items)


def _validate_nas_kind(raw: str) -> str:
    """One of the backends `nas.factory` can actually build, lower-cased.

    dash-admin-7, 2026-08-21: this was the generic "str" validator, so
    Settings and a pasted site.toml both accepted "TrueNAS" or "qnap" and
    published it verbatim to every installer in `GET /api/v1/site` -- and
    "TrueNAS" is not equal to "truenas" for any client comparing exactly --
    while the dashboard's own client kept using `DASH_NAS_KIND`. Case is
    normalised (the factory lower-cases too, so "TrueNAS" is an admin naming
    the right backend); a kind no factory can build is refused outright,
    because that is a manifest that lies about which NAS this is.
    """
    value = str(raw or "").strip().lower()
    if not value:
        raise SiteValidationError("nas_kind", "must not be blank")
    try:
        from .nas.factory import NAS_KINDS

        kinds = tuple(NAS_KINDS)
    except Exception:                                              # noqa: BLE001
        # A build without the factory (or one mid-refactor) must not make the
        # Settings page unusable -- fall back to accepting the trimmed value.
        return value
    if value not in kinds:
        raise SiteValidationError(
            "nas_kind", f"must be one of {', '.join(sorted(kinds))} (got {raw!r})")
    return value


def _validate_android_package(raw: str) -> str:
    """The APK's application id, or "" for "this site has no Android app".

    Blank is a legitimate answer (the field ships empty and the asset-links
    route answers `[]` until both halves are set), so an admin who clears it
    is turning the app off, not making a mistake.
    """
    import re

    global _PACKAGE_SEGMENT_RE
    if _PACKAGE_SEGMENT_RE is None:
        _PACKAGE_SEGMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
    value = str(raw or "").strip()
    if not value:
        return ""
    segments = value.split(".")
    if len(segments) < 2 or not all(_PACKAGE_SEGMENT_RE.match(s) for s in segments):
        raise SiteValidationError(
            "android.package_name",
            "must be an Android package name like 'net.ts.example.ccsync': "
            "two or more dot-separated parts, each starting with a letter or "
            f"underscore (got {raw!r})",
        )
    return value


def _validate_android_fingerprints(raw: str) -> str:
    """Zero or more SHA-256 certificate fingerprints, normalised to upper case
    and stored comma-joined (the "csv" shape every list key in this table
    uses).

    Accepts newlines as well as commas because the Settings field is a
    textarea, one per line -- which is how `keytool -list -v` and Play Console
    hand them over, and asking an admin to re-punctuate a value they pasted is
    how the wrong one gets typed. A leading "SHA256:" label is stripped for
    the same reason.
    """
    import re

    global _FINGERPRINT_RE
    if _FINGERPRINT_RE is None:
        _FINGERPRINT_RE = re.compile(r"^(?:[0-9A-F]{2}:){31}[0-9A-F]{2}$")
    text = str(raw or "").replace("\r", "\n")
    items = [p.strip() for p in re.split(r"[,\n]", text)]
    out: list[str] = []
    for item in items:
        if not item:
            continue
        if item.upper().startswith("SHA256:"):
            item = item[len("SHA256:"):].strip()
        item = item.upper()
        if not _FINGERPRINT_RE.match(item):
            raise SiteValidationError(
                "android.sha256_cert_fingerprints",
                f"{item!r} is not a SHA-256 fingerprint: 32 colon-separated "
                "hex pairs, as `keytool -list` prints them",
            )
        if item not in out:                 # a paste of the same key twice
            out.append(item)
    return ",".join(out)


def validate(key: str, raw: str) -> str:
    """Normalise+validate one field. Raises SiteValidationError; never
    guesses a corrected value silently (an admin who fat-fingers a port
    number gets told, not auto-rounded)."""
    kind = KEYS.get(key)
    if kind is None:
        raise SiteValidationError(key, "not a recognised site setting")
    if key == "canonical_prefix":
        return _validate_canonical_prefix(raw)
    if key == "nas_kind":
        return _validate_nas_kind(raw)
    if key == "indexer_model_tier":
        return _validate_model_tier(raw)
    if key == "android.package_name":
        return _validate_android_package(raw)
    if key == "android.sha256_cert_fingerprints":
        return _validate_android_fingerprints(raw)
    if kind == "int":
        return _validate_int(key, raw)
    if kind == "bool":
        return _validate_bool(key, raw)
    if kind == "csv":
        return _validate_csv(key, raw)
    return _validate_str(key, raw)


def get_all(conn: sqlite3.Connection) -> dict[str, str]:
    """Every row currently in the table, key -> raw stored value. A key with
    no row is simply absent (never a blank-string entry) -- that absence is
    what `resolved_manifest` reads as "fall through to Settings"."""
    rows = conn.execute(f"SELECT key, value FROM {TABLE}").fetchall()
    return {row["key"]: row["value"] for row in rows}


def table_is_empty(conn: sqlite3.Connection) -> bool:
    return conn.execute(f"SELECT 1 FROM {TABLE} LIMIT 1").fetchone() is None


def validate_many(values: Mapping[str, str]) -> dict[str, str]:
    """`set_many`'s validate-first half, split out (UX-21, resilience sweep
    2026-08-28) so a caller can validate a would-be write -- and diff it
    against the current values -- WITHOUT performing it. Raises on the first
    bad field, same as `set_many`, so a preview can never approve something
    the apply would then refuse."""
    normalized: dict[str, str] = {}
    for key, raw in values.items():
        normalized[key] = validate(key, raw)
    return normalized


def set_many(
    conn: sqlite3.Connection, values: Mapping[str, str], updated_by: str
) -> dict[str, str]:
    """Validate every field in `values` FIRST (so a form with one bad field
    changes nothing rather than half-applying), then upsert them all in one
    transaction. Returns the normalised values actually stored. Caller
    commits (matches every other write helper in this codebase, e.g.
    db.upsert_project) -- api routes commit after calling this."""
    normalized = validate_many(values)
    now = None
    from . import db as dbmod

    now = dbmod.utcnow_iso()
    for key, value in normalized.items():
        conn.execute(
            f"INSERT INTO {TABLE} (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
            "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
            (key, value, now, updated_by),
        )
    return normalized


def _looks_secret(key: str) -> bool:
    lowered = key.lower()
    return any(hint in lowered for hint in _SECRET_KEY_HINTS)


def _display(key: str, value: str) -> str:
    """UX-21 (resilience sweep 2026-08-28): the value a diff response is
    allowed to show. Masks whole rather than partial -- a short value mostly
    unmasked defeats the point (see ai_providers.mask's own reasoning) -- and
    only for a key that looks secret-shaped; every KEYS entry today does not,
    so this is a no-op in the shipped product."""
    if _looks_secret(key) and value:
        return "********"
    return value


def diff_against_current(
    conn: sqlite3.Connection, settings: Any, normalized: Mapping[str, str],
) -> list[dict[str, str]]:
    """What applying `normalized` (already-validated site_settings values,
    e.g. `validate_many`'s return) would CHANGE, compared against what is
    stored or falls through right now. Raw values, unmasked -- this is the
    building block `db.record_site_change` snapshots so an undo can actually
    restore them; a caller putting this on the wire (the import preview, the
    undo response) must run it through `mask_changes` first (UX-21,
    resilience sweep 2026-08-28).

    Read BEFORE the caller writes: `set_many` upserts in place, so a diff
    computed after the write would compare the new values against
    themselves."""
    db_values = get_all(conn)
    changes: list[dict[str, str]] = []
    for key in normalized:                        # dict order = TOML/form order
        new_value = normalized[key]
        current = db_values.get(key, _settings_fallback(key, settings))
        if current == new_value:
            continue
        changes.append({"key": key, "from": current, "to": new_value})
    return changes


def mask_changes(changes: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    """The masked copy of a `diff_against_current` list that is safe to
    return over HTTP (UX-21, resilience sweep 2026-08-28) -- see `_display`."""
    return [
        {"key": c["key"], "from": _display(c["key"], c["from"]), "to": _display(c["key"], c["to"])}
        for c in changes
    ]


def seed_from_env_once(conn: sqlite3.Connection, settings: Any) -> bool:
    """Copy this deployment's DASH_SITE_* env into the table, exactly once.

    Gate is `os.environ` itself (not `settings`, which already carries
    product defaults like canonical_prefix="P:\\" even on a fresh install
    with NO env set at all) -- so a from-scratch appliance with zero
    DASH_SITE_* variables never seeds, and the table stays empty until the
    wizard's own writes populate it. Returns whether it seeded, for the
    caller's boot log.
    """
    if not table_is_empty(conn):
        return False
    if not any(k.startswith("DASH_SITE_") and v.strip() for k, v in os.environ.items()):
        return False
    values = {
        "org_name": settings.site_org_name,
        "org_short": settings.site_org_short,
        "product_name": settings.site_product_name,
        "brand_logo": settings.site_brand_logo,
        "tree_name": settings.site_tree_name,
        "canonical_prefix": settings.site_canonical_prefix,
        "remote_root": settings.site_remote_root,
        "smb_unc": settings.site_smb_unc,
        "sftp_host": settings.site_sftp_host,
        "sftp_port": str(settings.site_sftp_port),
        "sftp_chunk_size": settings.site_sftp_chunk_size,
        "sftp_concurrency": str(settings.site_sftp_concurrency),
        "sftp_shell_type": settings.site_sftp_shell_type,
        "rclone_remote": settings.site_rclone_remote,
        "nas_syncthing_id": settings.site_nas_syncthing_id,
        "dashboard_url": settings.site_dashboard_url,
        "nas_kind": settings.nas_kind,
        "features.youtube_download": "1" if settings.site_feature_youtube_download else "0",
        "features.youtube_unblock": "1" if settings.site_feature_youtube_unblock else "0",
        "features.ai_cli_providers": "1" if settings.site_feature_ai_cli_providers else "0",
        "features.auto_update": "1" if settings.site_feature_auto_update else "0",
        "indexer_model_tier": settings.site_indexer_model_tier,
    }
    # template_folders / shared_asset_folders come from provision.py (its own
    # DASH_SITE_TEMPLATE_FOLDERS / DASH_SITE_SHARED_ASSETS env reader, applied
    # at import time) rather than Settings, which does not carry them --
    # provision.py IS the canonical copy (see its module docstring) and this
    # seed must not invent a second one.
    from . import provision

    values["template_folders"] = ",".join(provision.TEMPLATE_FOLDERS)
    values["shared_asset_folders"] = ",".join(rel for _fid, rel, _label in provision.SHARED_ASSET_FOLDERS)
    values = {k: v for k, v in values.items() if str(v or "").strip()}
    if not values:
        return False
    set_many(conn, values, updated_by="seed:env")
    conn.commit()
    log.info("site_settings seeded from DASH_SITE_* environment (%d field(s)); "
             "the database is now authoritative for the site manifest -- a later "
             "env change will not be picked up automatically", len(values))
    return True


def resolved_manifest(conn: sqlite3.Connection, settings: Any) -> dict[str, Any]:
    """The manifest `api_site` serves: DB row wins per key, else `settings`.

    Shapes values to their PYTHON type (int/bool/list), not the raw stored
    string -- callers (api.api_site, ui.page_admin_settings) should never
    have to know this is backed by a text-value table.
    """
    return _shape(get_all(conn), settings)


def _shape(db_values: Mapping[str, str], settings: Any) -> dict[str, Any]:
    """`resolved_manifest`'s body, given the rows already read.

    Split out 2026-08-21 (product-surface-2) so a caller that cannot open a
    connection -- `manifest_for_app` when the database is momentarily
    unreadable -- can still produce the same shape from `settings` alone
    instead of raising through a page render.
    """
    from . import provision

    def pick(key: str) -> str:
        if key in db_values:
            return db_values[key]
        return _settings_fallback(key, settings)

    template_raw = pick("template_folders")
    template_folders = (
        [p.strip() for p in template_raw.split(",") if p.strip()]
        if "template_folders" in db_values
        else list(provision.TEMPLATE_FOLDERS)
    )
    shared_raw = pick("shared_asset_folders")
    if "shared_asset_folders" in db_values:
        rels = [p.strip() for p in shared_raw.split(",") if p.strip()]
        shared_asset_folders = [
            {"id": fid, "rel": rel, "label": label}
            for fid, rel, label in provision.shared_asset_folders_for(rels)
        ]
    else:
        shared_asset_folders = [
            {"id": fid, "rel": rel, "label": label}
            for fid, rel, label in provision.SHARED_ASSET_FOLDERS
        ]

    def as_int(key: str, default: int) -> int:
        raw = pick(key)
        try:
            return int(raw) if str(raw).strip() else default
        except (TypeError, ValueError):
            return default

    def as_bool(key: str) -> bool:
        return pick(key).strip() == "1"

    return {
        "org_name": pick("org_name"),
        "org_short": pick("org_short"),
        "product_name": pick("product_name") or "CC Sync",
        "brand_logo": pick("brand_logo"),
        "tree_name": pick("tree_name"),
        "canonical_prefix": pick("canonical_prefix") or "P:\\",
        "remote_root": pick("remote_root"),
        "smb_unc": pick("smb_unc"),
        "sftp_host": pick("sftp_host"),
        "sftp_port": as_int("sftp_port", 22),
        "sftp_chunk_size": pick("sftp_chunk_size"),
        "sftp_concurrency": as_int("sftp_concurrency", 0),
        "sftp_shell_type": pick("sftp_shell_type"),
        "rclone_remote": pick("rclone_remote"),
        "nas_syncthing_id": pick("nas_syncthing_id"),
        "dashboard_url": pick("dashboard_url"),
        "template_folders": template_folders,
        "shared_asset_folders": shared_asset_folders,
        "nas_kind": pick("nas_kind") or "truenas",
        "features": {
            "youtube_download": as_bool("features.youtube_download"),
            "youtube_unblock": as_bool("features.youtube_unblock"),
            "ai_cli_providers": as_bool("features.ai_cli_providers"),
            "auto_update": as_bool("features.auto_update"),
        },
        # A NEW top-level object (2026-08-18), not another flat key -- same
        # shape convention as "features" above, and room for more indexer
        # knobs later without another manifest field. `pick` above already
        # falls through DB -> Settings (itself validated to good/best in
        # Settings.__post_init__); the `in MODEL_TIERS` check is only a last
        # defensive line, not the enforcement -- set_many() is.
        "indexer": {
            "model_tier": (
                pick("indexer_model_tier")
                if pick("indexer_model_tier") in MODEL_TIERS else "good"
            ),
        },
        # The Android app's identity (MOBILE_PLAN.md §4 M5, 2026-08-30). Its
        # own object for the same reason "features" and "indexer" are: one
        # more manifest field per knob turns this response into a flat bag.
        # Deliberately NOT published by `api.api_site` -- no installer,
        # companion or indexer has any use for it, and the one client that
        # does (Chrome, verifying the TWA) reads it from
        # `/.well-known/assetlinks.json` in the shape Google defines, not
        # from here.
        "android": {
            "package_name": pick("android.package_name"),
            "sha256_cert_fingerprints": [
                p.strip() for p in pick("android.sha256_cert_fingerprints").split(",")
                if p.strip()
            ],
        },
        # For the Settings page: which fields the DB actually overrides,
        # vs. which are still falling through to Settings/defaults.
        "_from_db": sorted(k for k in KEYS if k in db_values),
    }


# ------------------------------------------------------- the ONE feature gate

# Every `[features]` flag, and the `Settings` attribute that answers for it
# when no row exists. One mapping so a new flag is one line here rather than
# a new `if` in whichever module happens to gate on it (2026-08-21,
# product-surface-1: `youtube_download` had TWO readers -- this table, which
# the manifest and every companion read, and `settings.site_feature_*`, which
# the /ytdl mount read -- and an admin ticking the box on Settings moved only
# one of them).
FEATURE_SETTINGS_ATTRS = {
    "youtube_download": "site_feature_youtube_download",
    "youtube_unblock": "site_feature_youtube_unblock",
    "ai_cli_providers": "site_feature_ai_cli_providers",
    "auto_update": "site_feature_auto_update",
}


def feature_enabled(conn: sqlite3.Connection, settings: Any, name: str) -> bool:
    """Whether this site turned `[features] <name>` on.

    THE predicate. Same DB-row-then-environment precedence every other
    manifest key gets (see this module's docstring): a row of "0" is an admin
    who switched the feature OFF and beats a `DASH_SITE_*=1` left in the
    container's environment. FAILS CLOSED -- an unknown flag name, an
    unreadable table or a settings object that does not carry the attribute
    all read as off, because off is the vendor build's shape (CLAUDE.md,
    "Optional features are off in the vendor build").
    """
    attr = FEATURE_SETTINGS_ATTRS.get(str(name or "").strip())
    if attr is None:
        return False
    try:
        row = conn.execute(
            f"SELECT value FROM {TABLE} WHERE key = ?", (f"features.{name}",)
        ).fetchone()
    except sqlite3.Error:
        row = None
    if row is not None:
        return str(row["value"]).strip() == "1"
    return bool(getattr(settings, attr, False))


# ------------------------------------------- the manifest, without a connection
# `ui._render` runs on every page and has no `conn` in hand, and the brand it
# paints is a manifest field (product-surface-2, 2026-08-21). Opening a
# connection per render for three strings would be a new query on the hot
# path, so the resolved manifest is cached on `app.state` and dropped whenever
# a site write lands (setup_routes' PUT/import call `invalidate`). The cache
# is process-local and rebuilt on demand, so a second worker or a restart
# simply re-reads the table -- it is never the authority, only a copy.
_CACHE_ATTR = "site_manifest_cache"


def invalidate(app: Any) -> None:
    """Drop the cached manifest. Called by every writer of `site_settings`;
    a missed call would leave a page rendering the previous brand until the
    next restart, which is why the writers live next to each other in
    setup_routes.py."""
    state = getattr(app, "state", None)
    if state is not None and hasattr(state, _CACHE_ATTR):
        try:
            delattr(state, _CACHE_ATTR)
        except AttributeError:
            pass


def manifest_for_app(app: Any, settings: Any = None) -> dict[str, Any]:
    """`resolved_manifest` for a caller holding only the app (a template
    render). Cached; never raises -- a database that cannot be opened falls
    back to the `Settings`-only shape, because a page that cannot paint its
    own header is worse than a page painting the deploy-time default."""
    state = getattr(app, "state", None)
    if settings is None:
        settings = getattr(state, "settings", None)
    cached = getattr(state, _CACHE_ATTR, None) if state is not None else None
    if cached is not None:
        return cached
    manifest: dict[str, Any]
    try:
        from . import db as dbmod

        conn = dbmod.connect(settings.db_path)
        try:
            manifest = resolved_manifest(conn, settings)
        finally:
            conn.close()
    except Exception as exc:                                       # noqa: BLE001
        log.warning("could not read the site manifest for this render (%s); "
                    "falling back to the deploy-time values", exc)
        manifest = _shape({}, settings)
    if state is not None:
        setattr(state, _CACHE_ATTR, manifest)
    return manifest


def template_folders(conn: sqlite3.Connection, settings: Any) -> list[str]:
    """The project template THIS site uses, DB-first (dash-admin-3,
    2026-08-21). `provision.TEMPLATE_FOLDERS` is the import-time env/default
    copy and is only the fallback now: the wizard makes `template_folders` a
    REQUIRED answer, so the folder list a create actually lays down has to be
    the answer, not the value the container booted with."""
    return list(resolved_manifest(conn, settings)["template_folders"])


def shared_asset_folders(conn: sqlite3.Connection, settings: Any) -> list[tuple[str, str, str]]:
    """(id, rel, label) triples for this site's shared asset libraries,
    DB-first, in `provision.SHARED_ASSET_FOLDERS`' own shape so a caller can
    swap one for the other (dash-admin-3, 2026-08-21)."""
    return [
        (str(item["id"]), str(item["rel"]), str(item["label"]))
        for item in resolved_manifest(conn, settings)["shared_asset_folders"]
    ]


def _settings_fallback(key: str, settings: Any) -> str:
    mapping = {
        "org_name": settings.site_org_name,
        "org_short": settings.site_org_short,
        "product_name": settings.site_product_name,
        "brand_logo": settings.site_brand_logo,
        "tree_name": settings.site_tree_name,
        "canonical_prefix": settings.site_canonical_prefix,
        "remote_root": settings.site_remote_root,
        "smb_unc": settings.site_smb_unc,
        "sftp_host": settings.site_sftp_host,
        "sftp_port": str(settings.site_sftp_port),
        "sftp_chunk_size": settings.site_sftp_chunk_size,
        "sftp_concurrency": str(settings.site_sftp_concurrency),
        "sftp_shell_type": settings.site_sftp_shell_type,
        "rclone_remote": settings.site_rclone_remote,
        "nas_syncthing_id": settings.site_nas_syncthing_id,
        "dashboard_url": settings.site_dashboard_url,
        "nas_kind": settings.nas_kind,
        "features.youtube_download": "1" if settings.site_feature_youtube_download else "0",
        "features.youtube_unblock": "1" if settings.site_feature_youtube_unblock else "0",
        "features.ai_cli_providers": "1" if settings.site_feature_ai_cli_providers else "0",
        "features.auto_update": "1" if settings.site_feature_auto_update else "0",
        "indexer_model_tier": settings.site_indexer_model_tier,
        "template_folders": "",
        "shared_asset_folders": "",
        # No DASH_SITE_ANDROID_* environment twin, on purpose (2026-08-30):
        # these two are set by an admin pasting what a build printed, which is
        # a Settings action and never a deploy-time one. Blank means "no
        # Android app configured", which is what a fresh site is.
        "android.package_name": "",
        "android.sha256_cert_fingerprints": "",
    }
    return str(mapping.get(key, ""))


# --------------------------------------------------------------- export/import

# Section for each key, in `site.example.toml`'s own naming -- so Export
# produces text an admin could hand to `server/common.py`'s loader for a
# migration (§5: "site.toml is retired as an interface, kept only as an
# EXPORT format"). Not a byte-identical round trip with that file (this store
# owns a strict subset; secrets, [nas] host/admin_user, [apps] root and
# [stack] are not here at all -- an export is a starting point, not a
# replacement for reading INSTALL.md).
_SECTIONS: list[tuple[str, list[str]]] = [
    ("nas", ["nas_kind"]),
    ("tree", ["tree_name", "remote_root", "smb_unc", "template_folders",
              "shared_asset_folders"]),
    ("net", ["dashboard_url", "sftp_host", "sftp_port", "sftp_chunk_size",
             "sftp_concurrency", "sftp_shell_type", "rclone_remote"]),
    ("syncthing", ["nas_syncthing_id"]),
    ("site", ["org_name", "org_short", "product_name", "brand_logo",
              "canonical_prefix"]),
    ("features", ["features.youtube_download", "features.youtube_unblock",
                  "features.ai_cli_providers", "features.auto_update"]),
    ("indexer", ["indexer_model_tier"]),
    # The Android app rides the same export/import/history path as every other
    # manifest field (MOBILE_PLAN.md §4 M5, 2026-08-30) -- a NAS migration
    # that lost the asset links would relaunch every editor's app with a URL
    # bar and nothing saying why.
    ("android", ["android.package_name", "android.sha256_cert_fingerprints"]),
]

# toml key name (section-local) for each manifest key, where it differs from
# the manifest key itself -- mirrors site.example.toml's own spelling.
_TOML_KEY_NAMES = {
    "nas_kind": "kind",
    "nas_syncthing_id": "device_id",
    "sftp_shell_type": "shell_type",
    "shared_asset_folders": "shared_assets",
    "features.youtube_download": "youtube_download",
    "features.youtube_unblock": "youtube_unblock",
    "features.ai_cli_providers": "ai_cli_providers",
    "features.auto_update": "auto_update",
    "indexer_model_tier": "model_tier",
    "android.package_name": "package_name",
    "android.sha256_cert_fingerprints": "sha256_cert_fingerprints",
}


def _toml_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def export_toml(conn: sqlite3.Connection, settings: Any) -> str:
    """This site's DB values (falling through to Settings, exactly like the
    manifest route) as `site.toml`-shaped text -- Settings -> Export."""
    manifest = resolved_manifest(conn, settings)
    lines = [
        "# CC Sync site manifest -- exported from the dashboard's Settings page.",
        "# See site.example.toml for the full annotated reference; this export",
        "# carries only the fields the dashboard itself stores (site_settings).",
        "",
    ]
    flat = {
        "nas_kind": manifest["nas_kind"],
        "tree_name": manifest["tree_name"],
        "remote_root": manifest["remote_root"],
        "smb_unc": manifest["smb_unc"],
        "template_folders": manifest["template_folders"],
        "shared_asset_folders": [f["rel"] for f in manifest["shared_asset_folders"]],
        "dashboard_url": manifest["dashboard_url"],
        "sftp_host": manifest["sftp_host"],
        "sftp_port": manifest["sftp_port"],
        "sftp_chunk_size": manifest["sftp_chunk_size"],
        "sftp_concurrency": manifest["sftp_concurrency"],
        "sftp_shell_type": manifest["sftp_shell_type"],
        "rclone_remote": manifest["rclone_remote"],
        "nas_syncthing_id": manifest["nas_syncthing_id"],
        "org_name": manifest["org_name"],
        "org_short": manifest["org_short"],
        "product_name": manifest["product_name"],
        "brand_logo": manifest["brand_logo"],
        "canonical_prefix": manifest["canonical_prefix"],
        "features.youtube_download": manifest["features"]["youtube_download"],
        "features.youtube_unblock": manifest["features"]["youtube_unblock"],
        "features.ai_cli_providers": manifest["features"]["ai_cli_providers"],
        "features.auto_update": manifest["features"]["auto_update"],
        "indexer_model_tier": manifest["indexer"]["model_tier"],
        "android.package_name": manifest["android"]["package_name"],
        "android.sha256_cert_fingerprints": manifest["android"]["sha256_cert_fingerprints"],
    }
    for section, keys in _SECTIONS:
        lines.append(f"[{section}]")
        for key in keys:
            toml_key = _TOML_KEY_NAMES.get(key, key)
            value = flat[key]
            if isinstance(value, bool):
                lines.append(f"{toml_key} = {'true' if value else 'false'}")
            elif isinstance(value, int):
                lines.append(f"{toml_key} = {value}")
            elif isinstance(value, list):
                rendered = ", ".join(f'"{_toml_escape(v)}"' for v in value)
                lines.append(f"{toml_key} = [{rendered}]")
            else:
                lines.append(f'{toml_key} = "{_toml_escape(str(value))}"')
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def import_toml(text: str) -> dict[str, str]:
    """Parse pasted `site.toml`-shaped text into {site_settings key: raw
    string value}, ready for `set_many`. Uses `tomllib` (stdlib since 3.11,
    matching this project's floor -- see pyproject.toml) rather than a
    hand-rolled parser: a customer's real site.toml is a legitimate input
    (the migration path in ZERO_TOUCH_PLAN.md §6 step 1: "Run the wizard;
    import site.toml"), and it can carry sections ([apps], [stack], secrets
    comments) this store does not own -- those are silently ignored rather
    than refused, since an import is additive to what this store knows.
    """
    import tomllib

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SiteValidationError("_toml", f"could not parse: {exc}")
    reverse_toml_key = {v: k for k, v in _TOML_KEY_NAMES.items()}
    out: dict[str, str] = {}
    for section, keys in _SECTIONS:
        table = data.get(section)
        if not isinstance(table, dict):
            continue
        for toml_key, raw_value in table.items():
            manifest_key = reverse_toml_key.get(toml_key, toml_key)
            if manifest_key not in KEYS:
                continue
            if isinstance(raw_value, bool):
                out[manifest_key] = "1" if raw_value else "0"
            elif isinstance(raw_value, list):
                out[manifest_key] = ",".join(str(v) for v in raw_value)
            else:
                out[manifest_key] = str(raw_value)
    return out
