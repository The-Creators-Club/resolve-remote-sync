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


def make_current(
    conn: sqlite3.Connection,
    settings,
    *,
    platform: str,
    version: str,
    kind: str = "companion",
) -> None:
    """Point `current` at an ALREADY PUBLISHED build, through the same gates a
    fresh publish passes. Raises `PackageStoreError`; commits nothing.

    bug-hunt-2026-09-03 dash-release-jobs-2: `db.set_current_package` carries
    the retraction check and nothing else, so the feed's `current` policy was a
    third door onto `is_current` that the REL-4 / SYS-13 ordering gate did not
    cover -- it could advertise a build `api._upgrade_info` then refuses to
    offer, which reads as a fleet that has quietly stopped upgrading while the
    Packages page says CURRENT. The gate lives here, beside the one in
    `store_verified_package`, so both doors ask the same question.

    THE SOAK AND THE UNSIGNED CHECK ARE HERE NOW (REL-1, usability sweep
    2026-09-04). The 2026-09-03 verifier note left them out because they are
    "answers a human gives, and the feed poller has no human in scope" -- and
    the owner's answer to that policy question is that a site on
    `[releases] policy = current` is exactly where a canary is worth MOST: it
    is the one place where a build nobody has run reaches a whole fleet with
    nobody watching. A site that wants the old behaviour sets
    `[releases] soak_minutes = 0`, which is why that floor is zero rather than
    a flag. `force` is never passed from here: the typed confirmation is a
    door a human stands at.
    """
    refusal = make_current_refusal(
        conn, settings, kind=kind, platform=platform, version=version,
        bootstrap_ok=True)
    if refusal is not None:
        raise PackageStoreError(*refusal)
    if not db.set_current_package(conn, platform, version, kind):
        raise PackageStoreError(
            409,
            f"{kind} {version} for {platform} cannot be made current: it has "
            f"been retracted by the vendor.",
        )


def _row_value(row: Any, key: str) -> Any:
    """A column an older database may not have yet: sqlite3.Row raises
    IndexError, not KeyError (db._row_value's reason, during a redeploy)."""
    try:
        return row[key]
    except (IndexError, KeyError, TypeError):
        return None


def _row_str(row: Any, key: str) -> str:
    value = _row_value(row, key)
    return "" if value is None else str(value)


# --------------------------------------------------------------- the soak gate
#
# REL-1 (usability sweep 2026-09-04). Both functions below LIVED IN api.py
# until this wave, which meant the gate stood at the three doors that are HTTP
# routes and at none of the doors that are not: the vendor feed's `current`
# policy (unattended, on a daily poller, the shape a second customer ships
# with) and `./tools/release_macos.sh --publish --make-current` -- the exact
# command CLAUDE.md tells the owner to run on the Mac -- both reached
# `store_verified_package(make_current=True)` and handed the whole fleet a
# build no computer anywhere had run.
#
# They are here, in the module that is the ONLY writer of companion_packages,
# for the same reason the min_version typo refusal and the REL-4 ordering gate
# are: a door that does not pass through this file cannot publish, so a gate
# in this file is a gate on every door. api.py keeps one-line re-exports so
# its three routes, ui.py's htmx twin and every existing import still name
# `api.make_current_refusal`.


def soak_minutes_for(conn: sqlite3.Connection, settings) -> int:
    """How long a staged build must have run somewhere before it may be made
    current (REL-1, resilience sweep 2026-08-28).

    A `meta` row wins over the environment so a site can change it without a
    redeploy, and the floor is ZERO minutes on purpose: an operator who wants
    the old behaviour back sets it to 0 rather than learning a force flag.
    """
    raw = db.meta_get(conn, "release_soak_minutes")
    if raw is None:
        raw = getattr(settings, "release_soak_minutes", db.DEFAULT_SOAK_MINUTES)
    try:
        return max(0, int(float(str(raw).strip())))
    except (TypeError, ValueError):
        return db.DEFAULT_SOAK_MINUTES


def make_current_refusal(
    conn: sqlite3.Connection, settings, *, kind: str, platform: str, version: str,
    force: bool = False, confirm: str = "", now: str | None = None,
    bootstrap_ok: bool = False,
) -> tuple[int, str] | None:
    """(status, detail) when this build may NOT be handed to the fleet, else
    None. THE gate (REL-1/SYS-6, REL-3, REL-4/SYS-13, 2026-08-28).

    One function because there are five doors into "make current" -- the JSON
    route, the Packages page's htmx twin, the roll-back button, a publish that
    asks for it in the same breath, and the feed's `current` policy -- and a
    gate that only three of them pass through is not a gate. Order matters: a
    recall and an ordering violation are facts about the BUILD and no
    confirmation overrides them, while the soak is a judgement about
    EVIDENCE, which an admin is allowed to overrule in front of a typed
    confirmation.

    `force` is a HUMAN's override and nothing else: the two unattended callers
    (the publish path below and the feed poller) never pass it, because there
    is nobody there to type a version number into a box. `bootstrap_ok` is
    their counterpart -- see where it is read, below.
    """
    row = db.get_package(conn, platform, version, kind)
    if row is None:
        return 404, f"no published {platform} {kind} package {version}"
    reason = _row_str(row, "retracted_reason")
    if _row_str(row, "retracted_at"):
        return 409, (
            f"{kind} {version} was RECALLED by the vendor"
            + (f": {reason}" if reason else "")
            + ". It cannot be made current. Roll the fleet back to a build "
              "that was not recalled."
        )
    requires = _row_str(row, "requires_dashboard")
    if blocks_on_dashboard_version(kind, requires):
        return 409, (
            f"{kind} {version} needs dashboard {requires} and this dashboard is "
            f"{VERSION}. Update the dashboard first, then make this build current."
        )
    if not _row_str(row, "signature") and not (
        force and str(confirm or "").strip() == str(version).strip()
    ):
        # UX-9 (resilience sweep 2026-08-28). An UNSIGNED build made current
        # stops every companion upgrading, silently: they verify the record
        # signature and refuse the offer, and the only signal anywhere was a
        # chip on this page. A judgement about evidence rather than a fact
        # about the build, so it goes through the SAME typed override the soak
        # gate uses -- one mechanism, not two.
        return 409, (
            f"{kind} {version} has no release signature. Companions verify "
            f"signatures, so making it current stops EVERY computer in the fleet "
            f"from updating, silently. Republish it through tools\\ship.cmd "
            f"instead. To make it current anyway, type the version number "
            f"({version}) into the confirmation box."
        )
    if _row_value(row, "ever_current"):
        # A ROLLBACK, not a rollout: this build has been what the fleet was
        # offered before, so the evidence the soak gate asks for already
        # exists. Gating it would put the gate in the way of the recovery it
        # exists to make possible (REL-1, 2026-08-28).
        return None
    if bootstrap_ok and release_trust.version_above(
            _row_str(db.get_current_package(conn, platform, kind=kind), "version"),
            version):
        # A DOWNGRADE asked for by an unattended door is a withdrawal, not a
        # rollout: the vendor's channel pointer moving backwards is how a bad
        # build is taken away from feed customers (release-pipeline-5), and a
        # soak gate that stood in front of it would pin every fleet on the
        # build being withdrawn. Same reasoning as `ever_current` above, for
        # the case where THIS dashboard never had the older build current.
        return None
    if bootstrap_ok and not db.get_current_package(conn, platform, kind=kind):
        # NOTHING IS CURRENT for this platform and kind, so there is no fleet
        # to protect: every computer is being offered nothing at all, which is
        # a worse state than one running an unsoaked build (REL-1, usability
        # sweep 2026-09-04). The bootstrap case -- a fresh site's first
        # publish, and the first macOS build on a site that has only ever had
        # Windows -- where gating would leave a brand-new customer with no
        # companion at all until somebody found the override.
        #
        # ONLY for the callers that pass `bootstrap_ok`: an unattended publish
        # (this module's own path, and the feed's). The admin standing at
        # [ MAKE CURRENT ] is refused exactly as before, with the typed
        # override in front of them -- there is a human there, and the 08-28
        # gate's whole sentence is written to that human.
        return None
    if kind != "companion" or force:
        if force and str(confirm or "").strip() != str(version).strip():
            return 409, (
                f"to override the soak gate, type the version number "
                f"({version}) into the confirmation box. Nothing changed."
            )
        return None
    soak_minutes = soak_minutes_for(conn, settings)
    if soak_minutes <= 0:
        # ZERO IS OFF, and it has to be, because the soak gate now stands at
        # the publish door as well (REL-1, usability sweep 2026-09-04). Zero
        # minutes was never a way out on its own: `db.soak_state` also wants
        # at least one computer to have REPORTED the build, which a build
        # published thirty seconds ago never has, so a site that set 0 would
        # have found every publish staged for ever. `[releases] soak_minutes
        # = 0` is the documented escape for a site that wants the pre-08-28
        # behaviour, and this is what makes that sentence true.
        return None
    soak = db.soak_state(conn, platform, version, soak_minutes, now)
    if soak["ok"]:
        return None
    if not soak["machines"]:
        detail = (
            f"no computer has reported {version} yet, so nothing has run it. "
            f"Push it to one computer first, leave it for "
            f"{soak['soak_minutes']} min, then make it current."
        )
    elif soak["reverted"]:
        detail = (
            f"{soak['reverted']} of the {soak['machines']} computers on {version} "
            f"had to be rolled back off it by the crash-loop guard."
        )
    elif soak.get("crashes_on_version"):
        # CR-191 (2026-09-04): "crashes" is the LIFETIME count on those
        # machines' disks and this used to refuse on it. The base rig's 16
        # UncleanExit markers (CR-144: the installer's Stop-Process, the Cards
        # test gate sweeping 8899, dev restarts) were all written weeks ago by
        # 0.9.66 and older, and they blocked 0.9.70 with a sentence that named
        # neither fact. What refuses now is a crash written SINCE this build
        # started running somewhere, and the sentence says which is which.
        detail = (
            f"{soak['machines']} computers on {version} have reported "
            f"{soak['crashes']} crash(es), and {soak['crashes_on_version']} "
            f"of those computers have crashed since {version} started running "
            f"there."
        )
    elif soak.get("crashes_unknown") and not any(
            d.get("crash_origin") == db.CRASHES_NONE for d in soak["detail"]):
        # "We could not tell" is not "fine" (resilience sweep 2026-08-28): a
        # companion that never sent a crash section has told us nothing about
        # whether this build stays up, and a soak is a claim that something
        # was observed. Since CR-191 this also covers a crash counter whose
        # newest file cannot be dated: a count nobody can attribute is not
        # evidence for the build either way.
        if soak["crashes"]:
            detail = (
                f"{soak['crashes']} crash(es) are on record on the "
                f"{soak['machines']} computers on {version} and nothing says "
                f"when they were written, so they cannot be told apart from "
                f"this build's."
            )
        else:
            detail = (
                f"no computer on {version} has reported its crash counter, so "
                f"nothing here says the build stays up."
            )
    else:
        detail = (
            f"{soak['machines']} computers have been on {version} for "
            f"{soak['minutes']} min; the soak is {soak['soak_minutes']} min."
        )
        if soak["crashes"] and not soak.get("crashes_unknown"):
            # CR-191: say it before the admin reads the number on the page and
            # concludes the build is crashing. These are old markers, and the
            # only thing holding the release back is the clock.
            detail += (
                f" The {soak['crashes']} crash(es) on record there were all "
                f"written before {version} started running, so none of them "
                f"are its."
            )
    return 409, (
        f"{version} has not soaked yet: {detail} Make it current anyway by "
        f"confirming the override."
    )


# The one sentence every door prints when a publish that asked to be made
# current was published STAGED instead. One string, because the Mac scripts,
# publish_latest, the ship and the feed's log line all have to say the same
# thing (REL-1): a publisher who reads "staged" in four wordings on four
# machines learns nothing about what the fleet is being offered.
STAGED_SENTENCE = (
    "published and STAGED: push it to one computer, let it soak, then MAKE "
    "CURRENT."
)


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
    notes: str = "",
) -> str:
    """Verify the release signature over the record the CALLER assembled
    (server-chosen filename, server-counted size, server- or feed-computed
    digest -- never anything an uploader merely asserted), move `part_path`
    into its final home, insert the `companion_packages` row, optionally make
    it current, optionally prune -- one transaction, committed once.

    Returns a NOTE for the publisher: "" when everything asked for was done,
    and the soak gate's own refusal sentence when `make_current` was asked for
    and refused (REL-1, usability sweep 2026-09-04). A publish is never 4xx'd
    for that: the bytes are fine, they are signed, they belong on the shelf --
    only the FLIP is in question, and refusing the whole publish is what made
    the feed re-download and re-discard the same 40 MB on every check.

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
        # APP-16 (2026-09-04): NOT added to `record` above, and that is the
        # whole point -- `notes` is outside the signature, so it is not in
        # the canonical bytes either door verifies. A "what's new" line that
        # could make a record unverifiable on an older companion would be a
        # sentence with the power to strand a machine (REL-7).
        notes=notes,
    )
    # THE FLIP, GATED (REL-1, usability sweep 2026-09-04). Asked AFTER the row
    # is inserted and INSIDE the same transaction, because the gate reads the
    # row: `retracted_at`, `requires_dashboard`, `signature` and
    # `ever_current` are facts about the record that has just been written, and
    # a copy of the predicate that read the arguments instead would be a second
    # gate to keep in step with the first. Nothing is committed yet, so a
    # refusal costs a `set_current_package` that never runs -- the publish
    # itself stands.
    #
    # The ORDERING refusal (REL-4 / SYS-13, 2026-08-28) used to live above this
    # as a raise that unlinked the .part and refused the whole publish; it is
    # inside make_current_refusal now and stages instead, which is what its own
    # comment always said should happen.
    note = ""
    if make_current:
        refusal = make_current_refusal(
            conn, settings, kind=kind, platform=platform, version=version,
            bootstrap_ok=True)
        if refusal is None:
            db.set_current_package(conn, platform, version, kind)
        else:
            note = f"{STAGED_SENTENCE} {refusal[1]}"
            log.warning("%s %s %s was published STAGED rather than made current "
                        "by %s: %s", kind, platform, version, published_by,
                        refusal[1])
    pruned = db.prune_companion_packages(conn, platform, kind=kind) if prune else []
    conn.commit()
    for row in pruned:
        unlink_package_file(settings, row)
    return note


# --------------------------------------------------- what is actually running
#
# SYS-7 (usability sweep 2026-09-04). The drift doctor is a PowerShell script
# on the base rig, run by hand, comparing repo vs built vs installed vs live --
# and a second customer has no base rig and no repo, so for them it does not
# exist. In-product, this dashboard already knows four of the five numbers and
# showed them on three different pages with no verdict anywhere. This is the
# verdict, in one read, for the HEALTH page's [ WHAT IS RUNNING ] box.
#
# Every branch is defensive and every failure is silence about THAT line, not
# an exception: this feeds a page whose whole job is to answer when other
# things cannot, and a box that 500s the health page would be the funniest
# possible bug to ship in this wave.


def _package_row_map(conn: sqlite3.Connection) -> dict[tuple[str, str], Any]:
    try:
        rows = db.fetch_companion_packages(conn)
    except Exception:                                                 # noqa: BLE001
        log.warning("could not read the published packages", exc_info=True)
        return {}
    return {(str(r["platform"]), str(r["version"])): r
            for r in rows if str(r["kind"] or "") == "companion"}


def what_is_running(conn: sqlite3.Connection, settings, app_state) -> dict[str, Any]:
    """Dashboard vs vendor, companion vs vendor, and who is on what.

    `newest_offered` is what the VENDOR has, read from `feed_offered` (v39's
    meta row, written by every feed check) rather than the process-local
    record cache, because a container restarted five minutes ago has an empty
    cache and an empty cache must not read as "the vendor is offering
    nothing". "" everywhere means NOT CHECKED, never "up to date".
    """
    out: dict[str, Any] = {
        "dashboard": {"running": VERSION, "newest_offered": "", "behind": False,
                      "image_mode": None},
        "companions": [],
        "feed_checked_at": "",
        "disagreements": [],
    }
    try:
        out["feed_checked_at"] = str(
            (db.get_feed_state(conn) or {}).get("last_checked_at") or "")
    except Exception:                                                 # noqa: BLE001
        pass
    # SYS-2: "why has this dashboard not updated itself", in the words the
    # feed poller last wrote -- including, in bind-mount mode, the exact
    # command the operator has to run on their wired computer, because there
    # the container cannot replace its own code at all.
    try:
        from . import release_feed

        out["dashboard_update_note"] = str(
            db.meta_get(conn, release_feed.AUTO_UPDATE_NOTE_KEY) or "")
    except Exception:                                                 # noqa: BLE001
        out["dashboard_update_note"] = ""

    # --- the dashboard's own code
    try:
        from . import dashboard_update, release_feed

        out["dashboard"]["image_mode"] = bool(dashboard_update.image_mode())
        newest = ""
        for record in release_feed.dashboard_records(
                release_feed.verified_records(app_state)):
            version = str(record.get("version") or "")
            if version and (not newest or release_trust.version_above(version, newest)):
                newest = version
        out["dashboard"]["newest_offered"] = newest
        out["dashboard"]["behind"] = bool(
            newest and release_trust.version_above(newest, VERSION))
    except Exception:                                                 # noqa: BLE001
        log.warning("could not read the vendor's dashboard records", exc_info=True)

    # --- the companion channel, per platform
    try:
        offered = db.get_feed_offered(conn)
    except Exception:                                                 # noqa: BLE001
        offered = {}
    rows = _package_row_map(conn)
    try:
        rollout = db.rollout_status(conn)["channels"]
    except Exception:                                                 # noqa: BLE001
        log.warning("could not read the rollout status", exc_info=True)
        rollout = []
    for channel in rollout:
        platform = str(channel.get("platform") or "")
        current = str(channel.get("current_version") or "")
        newest = ""
        for version in offered.get(platform, []):
            if version and (not newest or release_trust.version_above(version, newest)):
                newest = version
        # One line per BUILD the fleet is actually on, with the date this
        # dashboard published it. A version no row exists for is still listed:
        # a computer running something this server never published is the most
        # interesting line on the box, not one to drop for lack of a date.
        builds: dict[str, int] = {}
        builds[current] = int(channel.get("machines_on_current") or 0)
        for entry in channel.get("behind") or []:
            version = str(entry.get("version") or "")
            if version:
                builds[version] = builds.get(version, 0) + 1
        out["companions"].append({
            "platform": platform,
            "current": current,
            "current_published_at": _row_str(
                rows.get((platform, current)), "published_at"),
            "newest_offered": newest,
            "behind_vendor": bool(newest and release_trust.version_above(newest, current)),
            "machines_total": int(channel.get("machines_total") or 0),
            "machines_on_current": int(channel.get("machines_on_current") or 0),
            "builds": [
                {"version": version, "computers": count,
                 "published_at": _row_str(rows.get((platform, version)), "published_at"),
                 "is_current": version == current}
                for version, count in sorted(
                    builds.items(),
                    key=lambda kv: release_trust._version_tuple(kv[0]), reverse=True)
                if version
            ],
        })

    # --- the sentence, in SYS-2's wording
    dash = out["dashboard"]
    for entry in out["companions"]:
        if entry["behind_vendor"] and dash["behind"]:
            # The SYS-2 shape exactly: the vendor is offering a build this
            # server cannot hand out, and the reason is this server's own
            # version. Said once, about the dashboard, because updating it is
            # the single action that clears every line.
            out["disagreements"].append(
                f"A newer CC Sync build for {entry['platform']} "
                f"({entry['newest_offered']}) is on offer and the computers here "
                f"are being offered {entry['current']}. Update the dashboard "
                f"first: it is {VERSION} and the vendor is offering "
                f"{dash['newest_offered']}."
            )
        elif entry["behind_vendor"]:
            out["disagreements"].append(
                f"The vendor is offering {entry['newest_offered']} for "
                f"{entry['platform']} and the computers here are being offered "
                f"{entry['current']}."
            )
        elif entry["machines_total"] and entry["machines_on_current"] < entry["machines_total"]:
            out["disagreements"].append(
                f"{entry['machines_on_current']} of {entry['machines_total']} "
                f"{entry['platform']} computers are on {entry['current']}."
            )
    if dash["behind"] and not out["disagreements"]:
        out["disagreements"].append(
            f"This dashboard is {VERSION} and the vendor is offering "
            f"{dash['newest_offered']}."
        )
    return out
