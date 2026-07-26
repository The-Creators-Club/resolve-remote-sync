"""Background collector: polls the server Syncthing instance into SQLite.

Structure mirrors the companion's SyncthingLane poll loop: a daemon thread
that never lets an exception escape, with `run_cycle()` split out so tests
can drive it synchronously. Per-kind cadences with exponential backoff
(15s doubling to backoff_max) on failure.

One-shot smoke mode, echoing the server scripts' conventions:
    SYNCTHING_GUI_URL=... SYNCTHING_API_KEY=... python -m ccsync_dashboard.collector --once
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable

from pathlib import Path

from . import db, provision
from .settings import Settings
from .syncthing_client import SyncthingClient, SyncthingError

log = logging.getLogger("ccsync.dashboard.collector")

# provision runs before config so a folder created for a new project dir is
# hydrated into the DB in the same cycle; enforce runs after config so it
# reconciles against a fresh device/folder picture.
KINDS = ("provision", "config", "enforce", "inventory", "connections", "completion", "remoteneed", "prune")
REMOTENEED_PERPAGE = 200
REMOTENEED_MAX_PAGES = 3
BACKOFF_BASE = 15.0

# Retention is the ONE cycle that must run even in a Syncthing-less
# deployment (settings.py fully supports one: reports + login work without
# it). Everything else needs the Syncthing REST API.
SYNCTHING_FREE_KINDS = ("prune",)

# Syncthing's own folder marker. Its presence is proof Syncthing has actually
# been serving a directory -- and its ABSENCE is Syncthing's only mass-delete
# guard, which is why both the retarget and the marker self-heal paths refuse
# to act on a directory that doesn't have one.
STFOLDER = ".stfolder"

# A retarget onto a directory holding less than this fraction of the media the
# dashboard last inventoried for that project is refused: a half-copied move
# would otherwise make the server's rescan mark ~everything deleted and
# propagate that to every editor (see the retarget sanity-check finding).
RETARGET_MIN_MEDIA_RATIO = 0.5


class Collector:
    def __init__(
        self,
        settings: Settings,
        client: SyncthingClient | None = None,
        now_fn: Callable[[], str] = db.utcnow_iso,
    ):
        self.settings = settings
        self.client = client or SyncthingClient.from_settings(settings)
        self.now_fn = now_fn
        self._stop = threading.Event()
        # nudge(): the loop's sleep is interrupted and these kinds run on the
        # next wake (<= ~5s) instead of waiting out their intervals. Ticking
        # a project used to start syncing only after interval_enforce -- up
        # to a minute of dead air after the click (2026-07-26).
        self._wake = threading.Event()
        self._nudge_lock = threading.Lock()
        self._nudge_kinds: set[str] = set()
        self._thread: threading.Thread | None = None
        # Caches refreshed by the config cycle.
        self._project_ids: dict[str, int] = {}      # folder slug -> projects.id
        self._device_ids: dict[str, int] = {}       # syncthing device ID -> devices.id
        self._folder_devices: dict[str, list[str]] = {}  # slug -> shared editor device IDs
        self._my_id = ""
        self._incomplete: dict[tuple[str, str], int] = {}  # (slug, device ID) -> needItems
        self._inventory_cursor = 0   # round-robin over projects for the NAS walk

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="dash-collector", daemon=True)
        self._thread.start()

    def nudge(self, kinds: tuple[str, ...] = ("config", "enforce", "connections", "completion")) -> None:
        """Run these kinds promptly (thread-safe, callable from request
        handlers via app.state.collector). Never raises."""
        try:
            with self._nudge_lock:
                self._nudge_kinds.update(kinds)
            self._wake.set()
        except Exception:
            log.debug("nudge failed", exc_info=True)

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def _interval(self, kind: str) -> float:
        s = self.settings
        return {
            "provision": s.interval_provision,
            "config": s.interval_config,
            "enforce": s.interval_enforce,
            "inventory": s.interval_inventory,
            "connections": s.interval_connections,
            "completion": s.interval_completion,
            "remoteneed": s.interval_remoteneed,
            "prune": s.interval_prune,
        }[kind]

    def _loop(self) -> None:
        conn = db.connect(self.settings.db_path)
        db.migrate(conn)
        next_due = {k: 0.0 for k in KINDS}
        backoff = {k: 0.0 for k in KINDS}
        try:
            while not self._stop.is_set():
                try:
                    due = [k for k in KINDS if time.monotonic() >= next_due[k]]
                    if due:
                        results = self.run_cycle(conn, due)
                        for kind in due:
                            if results.get(kind, False):
                                backoff[kind] = 0.0
                                next_due[kind] = time.monotonic() + self._interval(kind)
                            else:
                                backoff[kind] = min(
                                    max(backoff[kind] * 2, BACKOFF_BASE), self.settings.backoff_max
                                )
                                # Backoff DELAYS a kind, it never speeds it up:
                                # one failed hourly prune must not start
                                # retrying every 15s (see the backoff-replaces-
                                # the-interval finding).
                                next_due[kind] = time.monotonic() + max(
                                    backoff[kind], self._interval(kind)
                                )
                except Exception:
                    # Fault isolation of last resort: _timed already catches a
                    # runner's own exceptions, but its own db.record_poll_run
                    # call is unprotected -- e.g. a transient
                    # "database is locked" there must not kill this thread
                    # for good (nothing else restarts it, and prune/retention
                    # stops with it). Log-and-continue; the next tick retries.
                    log.exception("collector loop iteration failed; continuing")
                remaining = min(nd - time.monotonic() for nd in next_due.values())
                self._wake.wait(max(0.5, min(remaining, 5.0)))
                self._wake.clear()
                with self._nudge_lock:
                    nudged, self._nudge_kinds = set(self._nudge_kinds), set()
                for kind in nudged:
                    if kind in next_due:
                        next_due[kind] = 0.0
        finally:
            conn.close()

    # ------------------------------------------------------------ cycles

    def run_cycle(self, conn, kinds: list[str]) -> dict[str, bool]:
        """Run the given kinds in canonical order; returns kind -> ok."""
        kinds = list(kinds)
        # Completion/remoteneed need the config caches; hydrate first if empty.
        if not self._project_ids and any(k in kinds for k in ("completion", "remoteneed")):
            if "config" not in kinds:
                kinds.append("config")
        runners = {
            "provision": self._run_provision,
            "config": self._run_config,
            "enforce": self._run_enforce,
            "inventory": self._run_inventory,
            "connections": self._run_connections,
            "completion": self._run_completion,
            "remoteneed": self._run_remoteneed,
            "prune": self._run_prune,
        }
        results: dict[str, bool] = {}
        for kind in KINDS:
            if kind not in kinds:
                continue
            if kind in ("provision", "inventory") and not self.settings.projects_dir:
                results[kind] = True  # feature off: succeed silently, no poll_runs noise
                continue
            # Syncthing-less deployment: only retention runs (db.prune is
            # reachable ONLY from here, and eight tables grow without bound on
            # /data otherwise -- see the "no retention without Syncthing"
            # finding).
            if kind not in SYNCTHING_FREE_KINDS and not self.settings.syncthing_url:
                results[kind] = True
                continue
            # A failed hydration means completion/remoteneed would only walk
            # stale-or-empty caches; record them as failed, not vacuously ok.
            if kind in ("completion", "remoteneed") and results.get("config") is False:
                db.record_poll_run(conn, kind, self.now_fn(), self.now_fn(),
                                   False, "skipped: config hydration failed")
                conn.commit()
                results[kind] = False
                continue
            results[kind] = self._timed(conn, kind, runners[kind])
        return results

    def _timed(self, conn, kind: str, fn) -> bool:
        started = self.now_fn()
        try:
            fn(conn)
        except Exception as exc:  # fault isolation: a bad cycle must never kill the loop
            conn.rollback()
            level = logging.WARNING if isinstance(exc, SyncthingError) else logging.ERROR
            log.log(level, "poll %s failed: %s", kind, exc)
            db.record_poll_run(conn, kind, started, self.now_fn(), False, str(exc))
            conn.commit()
            return False
        db.record_poll_run(conn, kind, started, self.now_fn(), True, None)
        conn.commit()
        return True

    def _run_provision(self, conn) -> None:
        """Marker-driven discovery + reconcile (see provision.py's marker
        docs). Four jobs per cycle:

        1. self-heal: an existing Syncthing folder whose directory exists but
           lacks a marker gets one written -- but ONLY when that directory
           carries Syncthing's own .stfolder AND no other directory in the
           tree already claims the slug. Without those two guards, a freshly
           re-created empty dir at the old path gets stamped with the real
           project's identity, permanently deadlocking the duplicate-slug
           branch below and leaving the folder aimed at an empty directory
           (see the marker self-heal finding).
        2. verify ignores: EVERY existing folder's .stignore is compared
           against build_stignore_lines() and repaired when it differs. This
           is unconditional because a single failed set_ignores at creation
           time used to leave a folder indexing (and two-way deleting) every
           video file forever.
        3. retarget: a marker whose slug already has a Syncthing folder at a
           DIFFERENT path means the directory was moved/renamed on the NAS
           -- update the folder's path+label in place. Slug-keyed DB rows
           (selections, project_roots, completion, media) all survive; the
           data moved with the dir so Syncthing rescan finds identical
           hashes, no resync storm. Guarded by _retarget_ok().
        4. create: a marker whose slug has no folder yet is provisioned,
           using THE MARKER'S slug (not slugify(rel) -- an adopted/moved
           project's slug may not match its current path), unless the
           directory is a container of projects or sits inside one (see
           _creatable).

        Every slug is handled in its own try/except: one bad folder must
        never abort the cycle for the rest of the fleet.

        Never deletes folders: a folder whose dir vanished is left for the
        deactivation grace / a human."""
        projects_dir = Path(self.settings.projects_dir)
        if not projects_dir.is_dir():
            raise RuntimeError(f"DASH_PROJECTS_DIR does not exist: {projects_dir}")
        cfg = self.client.config()
        folders_by_id = {f["id"]: f for f in cfg.get("folders", [])}
        prefix = self.settings.syncthing_data_prefix.rstrip("/")

        # Scan markers FIRST: the self-heal guard needs to know whether the
        # slug it is about to stamp already lives somewhere else in the tree.
        scanned = provision.scan_project_dirs(projects_dir)
        by_slug: dict[str, list[str]] = {}
        for rel, slug in scanned:
            if slug is None:
                log.warning("unreadable project marker in %s -- skipping", rel)
                continue
            by_slug.setdefault(slug, []).append(rel)

        # -- 1. marker self-heal for known folders --------------------------
        for folder in folders_by_id.values():
            slug = folder["id"]
            path = str(folder.get("path", ""))
            if not path.startswith(prefix + "/"):
                continue
            rel = path[len(prefix) + 1:].strip("/")
            local = projects_dir / rel
            if not local.is_dir() or provision.read_marker(local) is not None:
                continue
            if not (local / STFOLDER).exists():
                log.warning(
                    "NOT writing a project marker for %s into %s: no %s there, so this is not "
                    "provably the directory Syncthing has been serving", slug, rel, STFOLDER)
                continue
            if by_slug.get(slug):
                log.warning(
                    "NOT writing a project marker for %s into %s: that identity already lives at "
                    "%s -- stamping it here would make two dirs claim the slug",
                    slug, rel, ", ".join(by_slug[slug]))
                continue
            try:
                provision.write_marker(local, slug)
                by_slug.setdefault(slug, []).append(rel)
                log.info("wrote missing project marker for %s (%s)", slug, rel)
            except OSError as exc:
                log.warning("could not write marker for %s: %s", slug, exc)

        # -- 2+3+4. reconcile scanned markers against folders ---------------
        # Per-slug fault isolation: one bad folder (a Syncthing 400 on a
        # container someone dropped a marker on, an unreadable dir) must not
        # stop every OTHER project being reconciled -- that is how one bad
        # marker froze provisioning fleet-wide, every 5 minutes, forever.
        # The failures are still RAISED at the end, so the cycle is recorded
        # as failed and retried with backoff (a failed .stignore repair, say,
        # must never be silently swallowed).
        failures: list[str] = []
        for slug, rels in by_slug.items():
            try:
                self._provision_slug(conn, slug, rels, folders_by_id, projects_dir, prefix)
            except Exception as exc:
                log.error("provision failed for %s (%s): %s", slug, ", ".join(rels), exc)
                failures.append(f"{slug}: {exc}")
        if failures:
            raise RuntimeError(
                f"{len(failures)} folder(s) failed to provision: " + "; ".join(failures)
            )

    def _provision_slug(
        self, conn, slug: str, rels: list[str], folders_by_id: dict, projects_dir: Path,
        prefix: str,
    ) -> None:
        """One scanned marker slug: retarget/relabel an existing folder, or
        create a missing one. See _run_provision for the four jobs."""
        existing = folders_by_id.get(slug)
        if len(rels) > 1:
            # Copied project dir: NEVER guess. If one rel matches the
            # current folder path, keep working with that one; else skip.
            current_rel = None
            if existing is not None:
                path = str(existing.get("path", ""))
                if path.startswith(prefix + "/"):
                    current_rel = path[len(prefix) + 1:].strip("/")
            matching = [r for r in rels if r == current_rel]
            log.warning("slug %s claimed by %d dirs (%s) -- %s",
                        slug, len(rels), ", ".join(rels),
                        "keeping current" if matching else "skipping all")
            if not matching:
                return
            rels = matching
        rel = rels[0]
        expected_path = f"{prefix}/{rel}"

        if existing is None:
            if not self._creatable(slug, rel, projects_dir):
                return
            # Created unshared: the selections table + enforce cycle
            # decide which editor devices get each folder.
            folder = provision.build_folder_config(slug, rel, prefix, [])
            self.client.add_folder(folder)
            self.client.set_ignores(slug, provision.build_stignore_lines())
            log.info("auto-provisioned syncthing folder %s (%s), unshared until ticked",
                     slug, rel)
            return

        self._ensure_ignores(slug)

        old_path = str(existing.get("path", "")).rstrip("/")
        if old_path != expected_path:
            if not self._retarget_ok(conn, slug, old_path, rel, projects_dir, prefix):
                return
            existing = dict(existing)
            existing["path"] = expected_path
            existing["label"] = rel
            self.client.put_folder(slug, existing)
            db.upsert_project(conn, slug, rel, expected_path, self.now_fn())
            conn.commit()
            log.warning("RETARGETED syncthing folder %s: %s -> %s (dir moved on the NAS)",
                        slug, old_path, expected_path)
        elif str(existing.get("label", "")) != rel:
            existing = dict(existing)
            existing["label"] = rel
            self.client.put_folder(slug, existing)
            log.info("fixed label drift on folder %s -> %s", slug, rel)

    @staticmethod
    def _creatable(slug: str, rel: str, projects_dir: Path) -> bool:
        """Refuse to provision a folder for a directory that is a CONTAINER
        of projects, or that sits inside one -- the same rule
        create_tree_project/adopt_folder already enforce on the dashboard.

        A marker is a plain JSON file on a share every editor can write. Drop
        one on Projects/2026/CCT/ and scan_project_dirs prunes there, hiding
        the three real projects underneath, while add_folder on the container
        either nests Syncthing folders (a folder whose path CONTAINS three
        others') or 400s -- and before the per-slug try/except that 400
        aborted the whole provision cycle, every cycle, forever."""
        target = projects_dir / Path(*[p for p in rel.split("/") if p])
        inside = provision.marked_ancestor(projects_dir, rel, include_self=False)
        if inside is not None:
            log.error(
                "REFUSING to provision folder %s (%s): it is inside an existing project "
                "(%s) -- projects cannot nest. Remove the stray %s marker.",
                slug, rel, inside, provision.MARKER_FILENAME)
            return False
        below = provision.marked_descendants(target)
        if below:
            log.error(
                "REFUSING to provision folder %s (%s): that directory CONTAINS project(s) "
                "(%s), so it is a container someone dropped a %s marker on -- provisioning "
                "it would hide them from discovery. Remove the container's marker.",
                slug, rel, ", ".join(below), provision.MARKER_FILENAME)
            return False
        return True

    def _ensure_ignores(self, slug: str) -> None:
        """Compare the folder's live .stignore against build_stignore_lines()
        and re-set it when it differs.

        A set_ignores that failed once (one dropped HTTP request while
        provisioning) previously left the folder with NO ignores forever: the
        old code only ever set them in the create branch. Lane C is
        sendreceive, so an ignore-less folder indexes every .braw/.mov and
        every Proxy/ dir, re-downloads them to every ticked editor, AND
        propagates an editor-side delete back to the NAS. Verification is
        therefore unconditional, every cycle."""
        want = provision.build_stignore_lines()
        try:
            current = self.client.get_ignores(slug)
        except SyncthingError as exc:
            # Read failure alone is not worth failing the cycle over (the next
            # cycle retries); a WRITE failure below deliberately propagates.
            log.warning("could not read ignores for folder %s: %s", slug, exc)
            return
        have = [str(line) for line in (current.get("ignore") or [])]
        if have == want:
            return
        self.client.set_ignores(slug, want)
        log.warning(
            "REPAIRED .stignore on folder %s: had %d line(s), expected %d -- video was "
            "unfiltered on this folder until now", slug, len(have), len(want))

    def _retarget_ok(
        self, conn, slug: str, old_path: str, new_rel: str, projects_dir: Path, prefix: str
    ) -> bool:
        """Sanity gate in front of every folder retarget.

        A retarget points a live Syncthing folder at a different directory.
        If that directory is a HALF-COPIED move (the marker is tiny and
        arrives first), Syncthing rescans, marks the not-yet-copied files
        deleted, and propagates that to every editor sharing the folder --
        with no .stversions copy, because the delete originates from the
        server's own rescan. So all three of these must hold:

          * the folder's CURRENT path no longer exists on disk (a move, not
            a copy),
          * the new directory carries Syncthing's .stfolder,
          * the new directory holds at least RETARGET_MIN_MEDIA_RATIO of the
            media the last NAS inventory recorded for this project.

        Refusals are logged loudly and re-evaluated next cycle -- nothing is
        ever deleted or reconfigured on a refusal."""
        new_dir = projects_dir / Path(*[p for p in new_rel.split("/") if p])

        if not old_path.startswith(prefix + "/"):
            log.error(
                "REFUSING to retarget folder %s -> %s: its current path %r is outside %s, so this "
                "container cannot verify what is there -- fix the folder by hand",
                slug, new_rel, old_path, prefix)
            return False
        old_rel = old_path[len(prefix) + 1:].strip("/")
        old_dir = projects_dir / Path(*[p for p in old_rel.split("/") if p])
        if old_dir.exists():
            log.error(
                "REFUSING to retarget folder %s: %s still exists on the NAS, so %s is a COPY, not "
                "a move -- retargeting would make Syncthing treat the un-copied files as deleted. "
                "Resolve the duplicate on the NAS.", slug, old_rel, new_rel)
            return False
        if not (new_dir / STFOLDER).exists():
            log.error(
                "REFUSING to retarget folder %s -> %s: no %s in that directory (an interrupted or "
                "still-running copy). Nothing changed.", slug, new_rel, STFOLDER)
            return False

        row = conn.execute("SELECT id FROM projects WHERE slug=?", (slug,)).fetchone()
        if row is not None:
            stored = db.fetch_nas_media_summary(conn, row["id"])
            expected = (stored["n_originals"] or 0) + (stored["n_proxies"] or 0)
            if expected:
                found = len(self._walk_media_files(new_dir))
                if found < expected * RETARGET_MIN_MEDIA_RATIO:
                    log.error(
                        "REFUSING to retarget folder %s -> %s: only %d media file(s) there against "
                        "%d in the last NAS inventory -- this looks like a copy still in flight. "
                        "Nothing changed.", slug, new_rel, found, expected)
                    return False
        return True

    def _run_config(self, conn) -> None:
        cfg = self.client.config()
        my_id = str(self.client.system_status().get("myID", "") or "")
        if not my_id:
            # An empty myID makes the NAS itself look like an editor: it gets
            # a completion bar, the collector polls Syncthing for its
            # completion against itself, and enforce would drop the server
            # device from every folder on every cycle. Keep the last known
            # value rather than adopting "" (see the empty-myID finding).
            log.error("syncthing reported an empty myID -- keeping the last known server device id")
            my_id = self._my_id
        self._my_id = my_id
        now = self.now_fn()
        for dev in cfg.get("devices", []):
            device_id = dev["deviceID"]
            self._device_ids[device_id] = db.upsert_device(
                conn, device_id, dev.get("name") or device_id, device_id == my_id, now
            )
        seen: list[str] = []
        self._folder_devices = {}
        for folder in cfg.get("folders", []):
            slug = folder["id"]
            self._project_ids[slug] = db.upsert_project(
                conn, slug, folder.get("label") or slug, folder.get("path", ""), now
            )
            seen.append(slug)
            self._folder_devices[slug] = [
                d["deviceID"] for d in folder.get("devices", []) if d["deviceID"] != my_id
            ]
        db.deactivate_missing_projects(conn, seen, now=now)

    def _run_enforce(self, conn) -> None:
        """Reconcile Syncthing folder shares with the selections table.

        Selections are the authority for MAPPED editor devices. Unmapped
        devices (name not a username) are never added or removed. Only the
        `devices` list of a folder is ever modified.
        """
        cfg = self.client.config()
        my_id = str(self.client.system_status().get("myID", "") or "")
        if not my_id:
            # Without the server's own device id, `desired` omits the server
            # from every folder -- a put_folder on EVERY folder, every cycle,
            # each of which restarts the folder in Syncthing. Skip the pass.
            log.error("skipping enforce: syncthing reported an empty myID")
            return
        folders = cfg.get("folders", [])
        id_to_editor: dict[str, str | None] = {
            d["deviceID"]: db.resolve_editor_username(d.get("name") or "")
            for d in cfg.get("devices", [])
            if d["deviceID"] != my_id
        }
        editor_devices: dict[str, set[str]] = {}
        for device_id, editor in id_to_editor.items():
            if editor:
                editor_devices.setdefault(editor, set()).add(device_id)

        if db.meta_get(conn, "selections_seeded") is None:
            now = self.now_fn()
            seeded = 0
            for folder in sorted(folders, key=lambda f: f.get("label") or f["id"]):
                for dev in folder.get("devices", []):
                    editor = id_to_editor.get(dev["deviceID"])
                    if editor and db.add_selection(conn, editor, folder["id"], "seed", now):
                        seeded += 1
            # Only claim the one-shot seed is DONE when the snapshot could
            # actually have produced selections. A first container start that
            # races Syncthing's own startup returns 200 with an empty device
            # list; flagging that as seeded makes the next enforce pass read
            # an empty selections table as authoritative and unshare every
            # editor from every folder, fleet-wide, silently (see the
            # seed-flag finding).
            if folders and any(editor for editor in id_to_editor.values()):
                db.meta_set(conn, "selections_seeded", now)
                # Commit the seed before the HTTP loop below: holding a write
                # transaction open across Syncthing calls is what makes an
                # editor's POST /api/v1/report 500 with "database is locked".
                conn.commit()
                log.info("seeded %d selections from existing folder shares", seeded)
            else:
                log.warning(
                    "not marking selections as seeded: %d folder(s), %d mapped editor device(s) "
                    "in this snapshot -- retrying next cycle",
                    len(folders), sum(1 for e in id_to_editor.values() if e))

        selections = db.fetch_all_selections(conn)
        plans: list[tuple[str, set[str], set[str]]] = []   # (slug, desired, actual)
        for folder in folders:
            slug = folder["id"]
            actual = {d["deviceID"] for d in folder.get("devices", [])}
            desired = {my_id}
            desired |= {d for d in actual if d in id_to_editor and id_to_editor[d] is None}
            for editor in selections.get(slug, []):
                desired |= editor_devices.get(editor, set())
            # devices outside the config snapshot entirely (shouldn't happen) stay put
            desired |= actual - set(id_to_editor) - {my_id}
            if desired == actual:
                continue
            plans.append((slug, desired, actual))

        # Blast-radius brake: a mass unshare is never a normal steady-state
        # outcome, it is the signature of a bad snapshot (Syncthing still
        # starting, devices not yet approved, a renamed device). Refuse the
        # removals -- additions still apply -- and say so loudly. Raise
        # DASH_ENFORCE_MAX_REMOVALS to override deliberately.
        removal_devices = {d for _slug, desired, actual in plans for d in (actual - desired)}
        limit = self.settings.enforce_max_share_removals
        skip_removals = len(removal_devices) > limit
        if skip_removals:
            log.error(
                "REFUSING to unshare %d device(s) in one enforce cycle (limit %d): %s. Additions "
                "still applied; raise DASH_ENFORCE_MAX_REMOVALS to override.",
                len(removal_devices), limit, ", ".join(sorted(removal_devices)))

        for slug, desired, actual in plans:
            if skip_removals:
                desired = desired | actual
                if desired == actual:
                    continue
            live = self.client.get_folder(slug)
            existing = {d["deviceID"]: d for d in live.get("devices", [])}
            live["devices"] = (
                [entry for device_id, entry in existing.items() if device_id in desired]
                + [{"deviceID": device_id, "introducedBy": ""}
                   for device_id in sorted(desired - set(existing))]
            )
            self.client.put_folder(slug, live)
            added = sorted(desired - actual)
            removed = sorted(actual - desired)
            log.info("enforced shares on %s: +%s -%s", slug, added or "[]", removed or "[]")

    def _run_inventory(self, conn) -> None:
        """Walk the NAS Projects tree for a bounded slice of projects each
        cycle, recording originals + proxies.

        The /projects mount is rw (the /project-setup create flow needs it --
        see deploy/compose.yaml); this cycle itself only ever reads.

        Scale strategy: a cheap dirs-only scan computes a signature of
        (dir_relpath, mtime_ns); when it matches the stored signature the
        expensive per-file walk is skipped entirely (steady state = no
        writes). At most `inventory_projects_per_cycle` projects are touched
        per cycle via a rotating cursor, so a cold start or mass change never
        walks the whole fleet in one tick.

        Every filesystem walk happens BEFORE the first write: an os.walk of a
        ZFS/NFS tree inside an open SQLite write transaction is what made
        editors' POST /api/v1/report 500 with "database is locked".
        """
        projects_dir = Path(self.settings.projects_dir)
        if not projects_dir.is_dir():
            raise RuntimeError(f"DASH_PROJECTS_DIR does not exist: {projects_dir}")
        active = conn.execute(
            "SELECT id, label, path FROM projects WHERE active=1 ORDER BY id"
        ).fetchall()
        if not active:
            return
        n = len(active)
        window = self.settings.inventory_projects_per_cycle
        start = self._inventory_cursor % n
        self._inventory_cursor = (start + window) % n
        selected = [active[(start + i) % n] for i in range(min(window, n))]

        now = self.now_fn()
        prefix = self.settings.syncthing_data_prefix.rstrip("/")
        # -- phase 1: read-only. Signatures + walks, nothing written. --------
        errors: list[tuple[int, str]] = []
        walked: list[tuple[int, str, list, str, int]] = []
        for row in selected:
            pid = row["id"]
            rel = self._project_rel(row, prefix)
            proj_dir = projects_dir / Path(*[p for p in rel.split("/") if p]) if rel else None
            if proj_dir is None or not proj_dir.is_dir():
                errors.append((pid, "project dir missing on NAS"))
                continue
            sig, n_dirs = self._dir_signature(proj_dir)
            if sig == db.nas_inventory_sig(conn, pid):
                continue  # unchanged since last walk -- skip the file scan
            walked.append((pid, rel, self._walk_media_files(proj_dir), sig, n_dirs))

        # -- phase 2: one short write burst ---------------------------------
        for pid, message in errors:
            db.record_inventory_error(conn, pid, message, now)
        for pid, rel, rows, sig, n_dirs in walked:
            db.replace_nas_media(conn, pid, rows, sig, n_dirs, now)
            log.info("inventory: %s -> %d media file(s)", rel, len(rows))

    @staticmethod
    def _project_rel(row, prefix: str) -> str:
        """The project's rel path under the Projects root.

        projects.path (the Syncthing folder path, kept in lockstep by the
        provision cycle) is authoritative; projects.label is only a fallback
        because a hand-created folder's label need not be the rel path at all
        -- using it made the walk miss and MEDIA PRESENCE read "NAS has 0
        originals" forever (see the inventory-keyed-on-label finding)."""
        path = str(row["path"] or "").replace("\\", "/").rstrip("/")
        if prefix and path.startswith(prefix + "/"):
            return path[len(prefix) + 1:].strip("/")
        return str(row["label"] or "").strip("/")

    @staticmethod
    def _dir_signature(proj_dir: Path) -> tuple[str, int]:
        import hashlib
        entries = []
        for dirpath, dirnames, _files in os.walk(proj_dir):
            dirnames.sort()
            try:
                mtime = os.stat(dirpath).st_mtime_ns
            except OSError:
                mtime = 0
            entries.append(f"{os.path.relpath(dirpath, proj_dir)}:{mtime}")
        digest = hashlib.sha1("\n".join(entries).encode("utf-8", "replace")).hexdigest()
        return digest, len(entries)

    @staticmethod
    def _walk_media_files(proj_dir: Path) -> list[tuple[str, str, str, int | None, int | None]]:
        rows: list[tuple[str, str, str, int | None, int | None]] = []
        for dirpath, dirnames, filenames in os.walk(proj_dir):
            dirnames.sort()
            for fn in filenames:
                ext = os.path.splitext(fn)[1]
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, proj_dir).replace(os.sep, "/")
                kind = provision.classify_media(rel.split("/"), ext)
                if kind is None:
                    continue
                try:
                    st = os.stat(full)
                    size, mtime = st.st_size, st.st_mtime_ns
                except OSError:
                    size, mtime = None, None
                rows.append((rel, kind, ext.lower(), size, mtime))
        return rows

    def _run_connections(self, conn) -> None:
        payload = self.client.connections()
        connected = {
            device_id: info.get("address") or None
            for device_id, info in payload.get("connections", {}).items()
            if info.get("connected")
        }
        db.set_connections(conn, connected, self.now_fn())

    def _run_completion(self, conn) -> None:
        """Poll every (folder, device) pair, THEN write.

        Two structural rules here, both from live incidents:
          * every Syncthing HTTP call happens before the first write, so the
            SQLite write transaction is never held open across ~120 sequential
            10s-timeout requests (that is what 500s an editor's report with
            "database is locked");
          * each pair is isolated, so one device erroring cannot roll back the
            rows already gathered for every other project/device.

        `_incomplete` is rebuilt from scratch (not popped in place) so a
        (slug, device) pair that drops out of _folder_devices -- an untick, a
        deleted editor device, a removed folder -- is pruned rather than
        lingering and making _run_remoteneed hit Syncthing with an unknown
        pair forever.
        """
        fresh: dict[tuple[str, str], int] = {}
        folder_status: list[tuple[int, str | None, str | None]] = []
        rows: list[tuple[int, int, dict, Any, Any]] = []
        for slug, shared in self._folder_devices.items():
            project_id = self._project_ids.get(slug)
            if project_id is None:
                continue
            try:
                status = self.client.db_status(slug)
            except Exception as exc:
                log.warning("db_status failed for %s: %s", slug, exc)
                continue
            global_items = status.get("globalFiles")
            global_bytes = status.get("globalBytes")
            # Syncthing's own folder health ("folder marker missing", "stopped",
            # a pull error) was previously read and thrown away, so a folder
            # that had stopped syncing entirely showed a stale-but-plausible
            # completion % forever.
            folder_status.append((
                project_id,
                str(status.get("state") or "") or None,
                str(status.get("error") or "") or None,
                # The folder's OWN need = what editors are pushing TO the
                # server (lane C uploads) -- shown on the transfers page.
                int(status.get("needTotalItems", 0) or 0),
                int(status.get("needBytes", 0) or 0),
            ))
            for device_id in shared:
                device_row = self._device_ids.get(device_id)
                if device_row is None:
                    continue
                try:
                    comp = self.client.completion(slug, device_id)
                except Exception as exc:
                    log.warning("completion failed for %s/%s: %s", slug, device_id, exc)
                    continue
                if "completion" not in comp:
                    # A 200 with an unexpected body is NOT "0% synced, nothing
                    # missing" -- recording that is indistinguishable from real
                    # data loss on the project page. Skip the row instead.
                    log.debug("completion response for %s/%s had no completion key: %r",
                              slug, device_id, comp)
                    continue
                rows.append((project_id, device_row, comp, global_items, global_bytes))
                completion = float(comp.get("completion", 0.0))
                need_items = int(comp.get("needItems", 0))
                if not (completion >= 100 and need_items == 0):
                    fresh[(slug, device_id)] = need_items

        now = self.now_fn()
        for project_id, state, error, f_need_items, f_need_bytes in folder_status:
            db.set_folder_status(conn, project_id, state, error, now,
                                 need_items=f_need_items, need_bytes=f_need_bytes)
        for project_id, device_row, comp, global_items, global_bytes in rows:
            completion = float(comp.get("completion", 0.0))
            need_items = int(comp.get("needItems", 0))
            db.upsert_completion(
                conn, project_id, device_row,
                completion=completion,
                need_items=need_items,
                need_bytes=int(comp.get("needBytes", 0)),
                need_deletes=int(comp.get("needDeletes", 0)),
                global_items=global_items,
                global_bytes=global_bytes,
                now=now,
            )
            if completion >= 100 and need_items == 0:
                db.clear_missing_files(conn, project_id, device_row)

        # Drop completion/missing rows for pairs no longer shared -- the
        # in-memory _incomplete map already pruned them, but the DB rows
        # lived forever and read as phantom sync backlog (see
        # db.prune_completion_not_shared). Guarded on a non-empty share map
        # so a Syncthing flap that briefly reports zero folders cannot
        # wipe the whole completion cache in one cycle.
        if self._folder_devices:
            valid_pairs: list[tuple[int, int]] = []
            for slug, shared in self._folder_devices.items():
                pid = self._project_ids.get(slug)
                if pid is None:
                    continue
                for device_id in shared:
                    drow = self._device_ids.get(device_id)
                    if drow is not None:
                        valid_pairs.append((pid, drow))
            pruned_pairs = db.prune_completion_not_shared(conn, valid_pairs)
            if pruned_pairs:
                log.info("completion: dropped %d stale (project, device) pair(s) "
                         "no longer shared", pruned_pairs)
        self._incomplete = fresh
        self._ingest_item_finished(conn, now)

    def _ingest_item_finished(self, conn, now: str) -> None:
        """Record files the SERVER finished receiving (Syncthing ItemFinished
        events) into transfer_history -- lane C uploads completed. A 420 MB
        mp3 crossed the LAN between two 60s polls and appeared in NO view
        (2026-07-26); the event stream doesn't blink. Never fails the cycle."""
        try:
            stored = int(db.meta_get(conn, "syncthing_last_event_id") or 0)
            # Event IDs restart at 1 when Syncthing restarts -- detect by
            # asking for the newest event unconditionally.
            newest = self.client.events(since=0, limit=1)
            newest_id = int(newest[-1].get("id", 0)) if newest else 0
            if newest_id < stored:
                stored = 0
            events = self.client.events(since=stored) if newest_id > stored else []
            if not events:
                return
            entries = []
            max_id = stored
            for ev in events:
                max_id = max(max_id, int(ev.get("id", 0)))
                data = ev.get("data") or {}
                if (ev.get("type") != "ItemFinished" or data.get("error")
                        or data.get("action") != "update" or data.get("type") != "file"):
                    continue
                slug = str(data.get("folder") or "")
                label = None
                for row in conn.execute("SELECT label FROM projects WHERE slug=?", (slug,)):
                    label = row["label"]
                if label is None:
                    continue
                # Attribute to the folder's single sharing editor when
                # unambiguous; the event doesn't say who sent the change.
                editors = set()
                for device_id in self._folder_devices.get(slug, []):
                    for r in conn.execute(
                        "SELECT editor_username FROM devices WHERE device_id=?", (device_id,)
                    ):
                        if r["editor_username"]:
                            editors.add(r["editor_username"])
                editor = editors.pop() if len(editors) == 1 else ""
                entries.append((editor, {
                    "lane": "lane_c_syncthing",
                    "name": f"Projects/{label}/{data.get('item', '')}",
                    "direction": "up",
                    "at": str(ev.get("time") or now),
                }))
            for editor, entry in entries:
                db.add_transfer_history(conn, editor, "", [entry], now)
            if max_id > stored:
                db.meta_set(conn, "syncthing_last_event_id", str(max_id))
        except Exception:
            log.debug("ItemFinished ingest failed", exc_info=True)

    def _run_remoteneed(self, conn) -> None:
        # Same shape as _run_completion: fetch every pair first, then write in
        # one burst, so no HTTP call happens inside the write transaction.
        gathered: list[tuple[int, int, list[tuple[str, int | None]], bool]] = []
        for (slug, device_id), need_items in list(self._incomplete.items()):
            project_id = self._project_ids.get(slug)
            device_row = self._device_ids.get(device_id)
            if project_id is None or device_row is None:
                continue
            try:
                files: list[tuple[str, int | None]] = []
                for page in range(1, REMOTENEED_MAX_PAGES + 1):
                    payload = self.client.remoteneed(slug, device_id, page, REMOTENEED_PERPAGE)
                    page_files = payload.get("files") or []
                    for entry in page_files:
                        if isinstance(entry, str):
                            files.append((entry, None))
                        else:
                            files.append((entry.get("name", "?"), entry.get("size")))
                    if len(page_files) < REMOTENEED_PERPAGE:
                        break
                gathered.append((project_id, device_row, files, need_items > len(files)))
            except Exception as exc:
                # One bad (slug, device) pair -- e.g. Syncthing errors on an
                # unknown folder/device combination that briefly outran the
                # config cache -- must not abort the whole cycle and stop
                # missing-file refresh fleet-wide (see the collector
                # _incomplete finding).
                log.warning("remoteneed failed for %s/%s: %s", slug, device_id, exc)

        now = self.now_fn()
        for project_id, device_row, files, truncated in gathered:
            db.replace_missing_files(conn, project_id, device_row, files, truncated, now)

    def _run_prune(self, conn) -> None:
        db.prune(conn, self.now_fn())


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Dashboard collector")
    ap.add_argument("--once", action="store_true", help="run one poll cycle and exit")
    ap.add_argument("--db", default=None, help="override DASH_DB_PATH")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings.from_env()
    if args.db:
        settings = Settings(**{**settings.__dict__, "db_path": args.db})
    if not settings.syncthing_url:
        print("FAILED: SYNCTHING_GUI_URL is not set")
        return 1

    conn = db.connect(settings.db_path)
    db.migrate(conn)
    collector = Collector(settings)
    if not args.once:
        print("use --once (the service runs the collector in-process via app.py)")
        return 2
    results = collector.run_cycle(
        conn, ["provision", "config", "connections", "completion", "remoteneed"]
    )
    for kind, ok in results.items():
        print(f"{kind}: {'ok' if ok else 'FAILED'}")
    for table in ("projects", "devices", "completion_current", "missing_files"):
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table}: {count} rows")
    conn.close()
    return sum(1 for ok in results.values() if not ok)


if __name__ == "__main__":
    raise SystemExit(main())
