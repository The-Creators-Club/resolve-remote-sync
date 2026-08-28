"""The shared tail of "verify a signed package record, then make it live".

Factored out of `api.api_publish_package` (ZERO_TOUCH_PLAN.md WP E,
2026-08-17) so the vendor release feed's unattended publisher
(`release_feed.publish_from_feed`) writes through the EXACT same
verify -> place-file -> insert -> make-current -> prune path a human PUT
does. Two callers, one implementation: a divergence here is precisely how a
build could become "published" through one door under different rules than
the other (e.g. the feed forgetting to verify the signature, or pruning
differently). Neither caller is allowed to touch `companion_packages`
directly for a publish -- this module is the only writer.

Raises `PackageStoreError` rather than `fastapi.HTTPException` on purpose:
this module has no FastAPI import and no request in scope, because the feed
can also reach it from the unattended background poller thread
(`release_feed.FeedPoller`), which is not inside a request at all. Each
caller translates `PackageStoreError` into whatever shape fits it (an
HTTPException in api.py/release_feed.py's routes, a log line in the poller).
"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from typing import Any

from . import VERSION, db, release_trust

log = logging.getLogger("ccsync.dashboard.package_store")


def blocks_on_dashboard_version(kind: str, requires_dashboard: str) -> bool:
    """Would offering this build break "deploy the dashboard before the
    companions" (REL-4 / SYS-13, resilience sweep 2026-08-28)?

    True only for a COMPANION record that names a dashboard version strictly
    above the one running. A record that names nothing (every record published
    before this wave) blocks nothing -- the field is optional and its absence
    means "no stated requirement", not "unknown, refuse".

    An UNPARSEABLE requirement blocks: `release_trust.version_above` answers
    None when it cannot compare, and a companion whose stated requirement
    cannot be read is exactly the case where guessing "probably fine" is how
    the B16 shape happens with the arrow reversed.
    """
    if str(kind or "") != "companion":
        return False
    wanted = str(requires_dashboard or "").strip()
    if not wanted:
        return False
    above = release_trust.version_above(wanted, VERSION)
    return True if above is None else bool(above)


class PackageStoreError(Exception):
    """`status_code`/`detail` mirror HTTPException's fields without importing
    FastAPI, so a caller with a Request can raise HTTPException(status_code,
    detail) verbatim and a caller without one (the feed poller) can just log
    `str(exc)`."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def package_file_path(settings, platform: str, filename: str) -> Path:
    return settings.packages_path() / platform / filename


def unlink_package_file(settings, row: sqlite3.Row | dict[str, Any]) -> None:
    try:
        package_file_path(settings, row["platform"], row["filename"]).unlink(missing_ok=True)
    except OSError:
        pass  # a stray file is harmless; the DB row is the source of truth


def store_verified_package(
    conn: sqlite3.Connection,
    settings,
    *,
    kind: str,
    platform: str,
    version: str,
    filename: str,
    sha256: str,
    size_bytes: int,
    min_version: str,
    published_at: str,
    signed_binary: bool,
    signature: str,
    pubkey_id: str,
    published_by: str,
    make_current: bool,
    prune: bool,
    part_path: Path,
    requires_dashboard: str = "",
    arch: str = "",
    git_sha: str = "",
    git_dirty: bool = False,
) -> None:
    """Verify the release signature over the record the CALLER assembled
    (server-chosen filename, server-counted size, server- or feed-computed
    digest -- never anything an uploader merely asserted), move `part_path`
    into its final home, insert the `companion_packages` row, optionally make
    it current, optionally prune -- one transaction, committed once.

    Raises `PackageStoreError` and leaves `part_path` UNLINKED on any
    refusal (nothing partially applied): the signature check runs before the
    file is moved, and the move+insert+current+prune below cannot fail
    independently of each other in a way that would leave a file on disk
    with no matching row, or a row with no file -- see the commit-then-unlink
    ordering, which is unchanged from the PUT route this was extracted from
    (DASH-3, 2026-08-14: committing before unlinking pruned files means a
    failed commit never deletes a file whose row survived).
    """
    record = {
        "kind": kind, "platform": platform, "version": version, "filename": filename,
        "sha256": sha256, "size_bytes": size_bytes, "min_version": min_version,
        "published_at": published_at, "signed_binary": bool(signed_binary),
    }
    # The OPTIONAL signed extras (REL-4/SYS-13, REL-16, 2026-08-28). Added to
    # the record only when the publisher actually sent one: an empty value
    # canonicalises as absent (release_trust.record_fields), which is what
    # keeps every record published before this wave verifying byte for byte.
    requires_dashboard = str(requires_dashboard or "").strip()
    arch = str(arch or "").strip()
    if requires_dashboard:
        record["requires_dashboard"] = requires_dashboard
    if arch:
        record["arch"] = arch
    # BEFORE the signature check, because a validly signed typo is exactly the
    # case this refuses (dash-release-ai-3, 2026-08-21): a record whose
    # min_version is above its own version raises every companion's permanent
    # downgrade floor past the build being offered, on nothing more than a
    # heavy report tick, and then refuses that build and every rollback to an
    # older one. Here rather than in the two routes so the human PUT and the
    # feed's auto-publish cannot disagree about it.
    if release_trust.min_version_exceeds_version(version, min_version):
        part_path.unlink(missing_ok=True)
        log.warning("REFUSED a self-refusing publish of %s %s %s by %s: min_version %s "
                    "is higher than the version itself",
                    kind, platform, version, published_by, min_version)
        raise PackageStoreError(
            400,
            f"min_version {min_version} is higher than the version being published "
            f"({version}), so every companion that saw this offer would raise its "
            f"downgrade floor above it and then refuse it. Nothing was published: "
            f"re-sign with a min_version at or below {version}.",
        )
    ok, detail = release_trust.verify_record(record, signature, settings.release_pubkeys)
    if not ok:
        part_path.unlink(missing_ok=True)
        log.warning("REFUSED an unverifiable publish of %s %s %s by %s: %s",
                    kind, platform, version, published_by, detail)
        raise PackageStoreError(
            400,
            f"release signature REJECTED ({detail}) -- nothing was published. "
            f"The signature must cover this exact record: kind={kind}, "
            f"platform={platform}, version={version}, filename={filename}, "
            f"sha256={sha256}, size_bytes={size_bytes}, min_version={min_version}, "
            f"published_at={published_at}, signed_binary={bool(signed_binary)}.",
        )
    if pubkey_id and pubkey_id != detail:
        # Advisory only: `detail` is the id of the key that ACTUALLY verified,
        # and that is what gets stored. A disagreement is worth a log line
        # during a rotation, never a refusal.
        log.info("publish declared pubkey_id %s but %s is what verified it",
                 pubkey_id, detail)

    # ORDERING (REL-4 / SYS-13, 2026-08-28): a companion build that needs a
    # newer dashboard than this one may be PUBLISHED here -- an admin who is
    # about to update the dashboard should be able to stage it -- but it must
    # never become what the fleet is offered. Checked in package_store rather
    # than in the two routes so the human PUT and the feed's `current` policy
    # cannot disagree, exactly as the min_version refusal above is.
    if make_current and blocks_on_dashboard_version(kind, requires_dashboard):
        part_path.unlink(missing_ok=True)
        raise PackageStoreError(
            409,
            f"{kind} {version} needs dashboard {requires_dashboard} and this "
            f"dashboard is {VERSION}. Update the dashboard first, then make this "
            f"build current. Nothing was published.",
        )

    dest_dir = settings.packages_path() / platform
    dest_dir.mkdir(parents=True, exist_ok=True)
    os.replace(part_path, dest_dir / filename)

    db.insert_companion_package(
        conn, version=version, platform=platform, filename=filename,
        sha256=sha256, size_bytes=size_bytes, published_by=published_by, now=published_at,
        kind=kind, signature=signature, pubkey_id=detail,
        min_version=min_version, signed_binary=bool(signed_binary),
        requires_dashboard=requires_dashboard, arch=arch,
        git_sha=str(git_sha or "").strip(), git_dirty=bool(git_dirty),
    )
    if make_current:
        db.set_current_package(conn, platform, version, kind)
    pruned = db.prune_companion_packages(conn, platform, kind=kind) if prune else []
    conn.commit()
    for row in pruned:
        unlink_package_file(settings, row)
