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
# How long the loop waits before retrying its own db.connect+db.migrate. Short:
# the case this exists for is the app's startup migration holding the write lock
# for a moment (DASH-8), not an outage.
DB_OPEN_RETRY_SECONDS = 5.0

# Retention is the ONE cycle that must run even in a Syncthing-less
# deployment (settings.py fully supports one: reports + login work without
# it). Everything else needs the Syncthing REST API.
SYNCTHING_FREE_KINDS = ("prune",)

# Syncthing's own folder marker. Its presence is proof Syncthing has actually
# been serving a directory -- and its ABSENCE is Syncthing's only mass-delete
# guard, which is why both the retarget and the marker self-heal paths refuse
# to act on a directory that doesn't have one.
STFOLDER = ".stfolder"

# Per-folder settings the collector REPAIRS on existing folders, not just sets
# at create time (KNOWN_BUGS B19). `setup_syncthing_folder.py --force` PUTs a
# whole folder object built from scratch, so it silently reset both knobs to
# Syncthing's defaults -- and unlike .stignore there was no repair pass, so a
# project re-forced to fix its path pulled at maxConcurrentWrites=2 over the
# WAN forever with nothing logged. Folders created by the server script rather
# than by this collector never got the tuning at all.
#
# The canonical values live in provision.build_folder_config (one source of
# truth); this list is only which of its keys are repairable drift. Deliberately
# NOT the whole folder object: `devices` is the enforce cycle's, `path`/`label`
# are the retarget branch's, and `versioning` must never be silently rewritten.
#
# `ignoreDelete` (delete-protection, 2026-08-11,
# docs/delete-protection-ignoredelete.md) is repairable drift too: the
# companion's per-turn ensure_ignore_delete reaches only each editor's OWN
# Syncthing, so this pass is the one path that retrofits the flag onto the
# NAS's pre-existing folders -- the authoritative copies the policy exists to
# protect. Re-asserting it each cycle is the doc's "temporarily lift the flag"
# runbook working as designed, not churn: the flag only PATCHes when it drifted.
FOLDER_TUNING_KEYS = ("maxConcurrentWrites", "pullerMaxPendingKiB", "ignoreDelete")


def folder_tuning_drift(folder: dict) -> dict:
    """{key: canonical value} for every tuned knob the live folder disagrees
    with (missing counts as disagreeing). Empty dict = nothing to repair."""
    canonical = provision.build_folder_config("_", "_", "/_", [])
    return {
        key: canonical[key]
        for key in FOLDER_TUNING_KEYS
        if folder.get(key) != canonical[key]
    }


# A retarget onto a directory holding less than this fraction of the media the
# dashboard last inventoried for that project is refused: a half-copied move
# would otherwise make the server's rescan mark ~everything deleted and
# propagate that to every editor (see the retarget sanity-check finding).
RETARGET_MIN_MEDIA_RATIO = 0.5

# Per-call timeout for the completion pass's db_status/completion reads
# (ops-efficiency-5, 2026-08-21). See Collector._completion_call_timeout.
COMPLETION_CALL_TIMEOUT_SECONDS = 3.0


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
        # Device IDs already warned about in _run_enforce (username-shaped
        # name, no matching editor account -- see B16). Warn-once, not every
        # cycle forever.
        self._warned_unknown_editor: set[str] = set()
        # ...and the same warn-once for a machine whose reported Syncthing
        # device this server has not approved (dash-admin-6, 2026-08-21).
        self._warned_unapproved_device: set[str] = set()
        # Where the last completion cycle ran out of its wall-clock budget, so
        # the next one starts there instead of re-polling the same head of the
        # list for ever (ops-efficiency-5, 2026-08-21).
        self._completion_cursor = 0
        # THIS SITE's shared asset libraries, refreshed once per cycle from
        # site_settings (dash-admin-3 / CR-58, 2026-08-21). Seeded from
        # provision.py's import-time env/default copy so a Collector that is
        # never handed a connection behaves exactly as it did before.
        self._shared_folders: list[tuple[str, str, str]] = list(
            provision.SHARED_ASSET_FOLDERS)
        self._shared_folder_ids: frozenset[str] = frozenset(
            provision.SHARED_ASSET_FOLDER_IDS)
        # Loop liveness for app.CollectorWatchdog (ops-efficiency-6,
        # 2026-08-21): monotonic, stamped at the top of every iteration. A
        # thread that is alive but has not stamped this in minutes is wedged
        # inside one call, which is a different fault from a thread that died.
        self._heartbeat = time.monotonic()

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        self._heartbeat = time.monotonic()
        self._thread = threading.Thread(target=self._loop, name="dash-collector", daemon=True)
        self._thread.start()

    def thread_died(self) -> bool:
        """start() ran, stop() did not, and the loop thread is gone.

        Deliberately False for a collector that was STOPPED (ops-efficiency-6,
        2026-08-21): shutdown, and the suite's own `collector.stop()`, must
        never read as the fault the watchdog exists to recover from.
        """
        if self._stop.is_set():
            return False
        thread = self._thread
        return thread is not None and not thread.is_alive()

    def seconds_since_heartbeat(self) -> float:
        """How long the loop has been inside one iteration. 0.0 whenever the
        question does not apply (never started, stopped, already dead), so a
        caller can treat any positive number as real."""
        thread = self._thread
        if self._stop.is_set() or thread is None or not thread.is_alive():
            return 0.0
        return max(0.0, time.monotonic() - self._heartbeat)

    def restart(self) -> bool:
        """Start a replacement loop thread after the old one died. False when
        that is not what happened (stopped on purpose, or still running) --
        two loop threads sharing one collector would double every write."""
        if self._stop.is_set():
            return False
        thread = self._thread
        if thread is not None and thread.is_alive():
            return False
        self.start()
        return True

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
        conn = None
        next_due = {k: 0.0 for k in KINDS}
        backoff = {k: 0.0 for k in KINDS}
        try:
            while not self._stop.is_set():
                # Before anything that can block: this is the loop saying it
                # is still going round (ops-efficiency-6).
                self._heartbeat = time.monotonic()
                if conn is None:
                    # INSIDE the try, and retried: connect+migrate used to sit
                    # above it, so a "database is locked" against the app's own
                    # startup migration killed this thread outright and leaked
                    # the connection. Nothing restarts it, so db.prune -- which
                    # is reachable only from here -- never ran again for the
                    # life of the process (KNOWN_BUGS DASH-8, 2026-08-11).
                    try:
                        conn = db.connect(self.settings.db_path)
                        db.migrate(conn)
                    except Exception:
                        log.exception("collector could not open %s; retrying in %.0fs",
                                      self.settings.db_path, DB_OPEN_RETRY_SECONDS)
                        self._stop.wait(DB_OPEN_RETRY_SECONDS)
                        continue
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
            if conn is not None:
                conn.close()

    # ------------------------------------------------------------ cycles

    def run_cycle(self, conn, kinds: list[str]) -> dict[str, bool]:
        """Run the given kinds in canonical order; returns kind -> ok."""
        kinds = list(kinds)
        self._refresh_shared_folders(conn)
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

    def _refresh_shared_folders(self, conn) -> None:
        """Re-read this site's shared asset libraries, once per cycle.

        dash-admin-3 / CR-58, 2026-08-21: an admin who adds `Assets/SFX` on
        Settings got a manifest that advertised folder id `assets-sfx` to
        every installer while this collector -- which is what actually creates
        and shares the folder -- went on reading `provision.SHARED_ASSET_
        FOLDERS`, the value the container BOOTED with. Per cycle rather than
        per process for the same reason the /ytdl gate is per request: the
        admin ticks a box and the fleet follows, without a redeploy.

        Failure keeps the previous list. An unreadable site_settings must not
        empty the shared-folder set: `_run_enforce` reads that set to decide
        which folders have no tick to consult, and an empty one there is the
        B16 shape (every editor unshared from the LUT library on one bad
        read).
        """
        try:
            from . import site_store

            resolved = site_store.shared_asset_folders(conn, self.settings)
        except Exception as exc:  # noqa: BLE001
            log.warning("could not read the site's shared asset folders (%s); "
                        "keeping the previous list", exc)
            return
        if not resolved:
            return
        self._shared_folders = list(resolved)
        self._shared_folder_ids = frozenset(fid for fid, _rel, _label in resolved)

    def _timed(self, conn, kind: str, fn) -> bool:
        started = self.now_fn()
        try:
            # A runner may return a note (completion's "partial: ...",
            # ops-efficiency-5): it succeeded, and the health panel gets to
            # say what it did not finish. None for every other cycle.
            note = fn(conn)
        except Exception as exc:  # fault isolation: a bad cycle must never kill the loop
            conn.rollback()
            level = logging.WARNING if isinstance(exc, SyncthingError) else logging.ERROR
            log.log(level, "poll %s failed: %s", kind, exc)
            db.record_poll_run(conn, kind, started, self.now_fn(), False, str(exc))
            conn.commit()
            return False
        db.record_poll_run(conn, kind, started, self.now_fn(), True,
                           note if isinstance(note, str) else None)
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
        # -- 5. shared asset libraries -------------------------------------
        # Deliberately after the project loop and outside its per-slug fault
        # isolation's failure list, but on the same cycle: a broken LUT
        # library must not stop projects provisioning, and vice versa.
        try:
            self._ensure_shared_folders(folders_by_id)
        except Exception as exc:
            log.error("shared asset folder provisioning failed: %s", exc)
            failures.append(f"shared-assets: {exc}")

        if failures:
            raise RuntimeError(
                f"{len(failures)} folder(s) failed to provision: " + "; ".join(failures)
            )

    def _ensure_shared_folders(self, folders_by_id: dict) -> None:
        """Create/repair the fleet-wide asset libraries (the LUT library).

        These are NOT projects: no marker, no tick, no entry in the dashboard
        project list, and they live beside Projects/ rather than inside it --
        so none of the marker scan, retarget or _creatable logic above
        applies to them. What they share with projects is everything below
        the identity layer: the same folder tuning, the same staggered
        versioning, and an unconditionally-repaired .stignore.

        The .stignore is the ASSET list (provision.build_asset_stignore_lines),
        never the project list. Repairing one of these with the project list
        would ignore nothing that matters here and would churn the file every
        cycle against the companion, which writes the asset list -- so the id
        check in _ensure_ignores is load-bearing, not cosmetic.

        Sharing is handled by _run_enforce, which gives these folders every
        mapped editor device unconditionally (there is no tick to consult).
        """
        prefix = (self.settings.syncthing_assets_prefix or "").rstrip("/")
        if not prefix:
            return
        for folder_id, rel, label in self._shared_folders:
            # rel is "Assets/<name>"; the prefix already points AT Assets.
            leaf = rel.split("/", 1)[1] if "/" in rel else rel
            path = f"{prefix}/{leaf}"
            existing = folders_by_id.get(folder_id)
            if existing is None:
                # Created unshared, exactly like a project folder: the enforce
                # cycle below adds the server's own device and every mapped
                # editor. Creating it with a device list here would race
                # enforce and, on a first cycle where myID is not known yet,
                # write an empty device id into the config.
                self.client.add_folder(
                    provision.build_shared_folder_config(folder_id, label, path, [])
                )
                self.client.set_ignores(folder_id, provision.build_asset_stignore_lines())
                log.info(
                    "auto-provisioned shared asset folder %s at %s -- it will be shared "
                    "with every editor on the next enforce cycle", folder_id, path)
                continue
            if str(existing.get("path", "")).rstrip("/") != path:
                # Never silently retarget a live folder: unlike a project
                # move (which has a marker travelling with the directory to
                # prove intent) a path mismatch here means someone changed
                # DASH_SYNCTHING_ASSETS_PREFIX or edited the folder by hand,
                # and repointing would make Syncthing call every file at the
                # old path deleted and propagate that to the whole fleet.
                log.error(
                    "shared asset folder %s is at %r, not the configured %r -- leaving it "
                    "alone. Fix the folder in the Syncthing GUI or set "
                    "DASH_SYNCTHING_ASSETS_PREFIX to match.",
                    folder_id, existing.get("path"), path)
                continue
            self._ensure_ignores(folder_id)
            drift = folder_tuning_drift(existing)
            if drift:
                repaired = dict(existing)
                repaired.update(drift)
                self.client.put_folder(folder_id, repaired)
                log.warning(
                    "REPAIRED folder settings on shared asset folder %s: %s",
                    folder_id, ", ".join(f"{k}={v}" for k, v in sorted(drift.items())))

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
            other = self._duplicate_path_folder(slug, expected_path, folders_by_id)
            if other is not None:
                log.error(
                    "REFUSING to provision folder %s (%s): folder %s is ALREADY serving "
                    "that directory. This is the folder-id divergence: the collector "
                    "keys on the marker's immutable slug, while "
                    "setup_syncthing_folder.py derives the id with slugify(rel) -- so a "
                    "MOVED project gets a second Syncthing folder over the same dir, "
                    "which no editor is shared with. Delete the stray folder in "
                    "Syncthing (keep the one editors are on), or pass --slug %s to the "
                    "server script.", slug, rel, other, slug)
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

        # Folder-settings drift is repaired in the SAME put as any path/label
        # change, so a drifted folder that also moved costs one config write
        # rather than two (each of which restarts the folder in Syncthing).
        drift = folder_tuning_drift(existing)
        old_path = str(existing.get("path", "")).rstrip("/")
        if old_path != expected_path:
            if not self._retarget_ok(conn, slug, old_path, rel, projects_dir, prefix):
                return
            existing = dict(existing)
            existing["path"] = expected_path
            existing["label"] = rel
            existing.update(drift)
            self.client.put_folder(slug, existing)
            db.upsert_project(conn, slug, rel, expected_path, self.now_fn())
            conn.commit()
            log.warning("RETARGETED syncthing folder %s: %s -> %s (dir moved on the NAS)",
                        slug, old_path, expected_path)
        elif str(existing.get("label", "")) != rel:
            existing = dict(existing)
            existing["label"] = rel
            existing.update(drift)
            self.client.put_folder(slug, existing)
            log.info("fixed label drift on folder %s -> %s", slug, rel)
        elif drift:
            existing = dict(existing)
            existing.update(drift)
            self.client.put_folder(slug, existing)
            log.warning(
                "REPAIRED folder settings on folder %s: %s -- this folder was running "
                "on Syncthing's defaults (WAN puller tuning, delete protection), "
                "with nothing logged",
                slug,
                ", ".join(f"{k}={v}" for k, v in sorted(drift.items())))

    @staticmethod
    def _duplicate_path_folder(
        slug: str, expected_path: str, folders_by_id: dict
    ) -> str | None:
        """The id of an existing folder already serving `expected_path`, or
        None. Two Syncthing folders over one directory each index and pull it
        independently -- and only one of them is the folder editors are shared
        with, so the other silently diverges."""
        want = str(expected_path).rstrip("/")
        for folder_id, folder in folders_by_id.items():
            if folder_id == slug:
                continue
            if str(folder.get("path", "")).rstrip("/") == want:
                return folder_id
        return None

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
        therefore unconditional, every cycle.

        A shared asset folder gets the ASSET list instead. Both this and the
        companion write their folder's .stignore repeatedly (here every
        provision cycle, there every startup), so getting this wrong does not
        merely apply the wrong patterns -- it makes the two ends fight over
        the file forever, rewriting it every cycle."""
        want = (
            provision.build_asset_stignore_lines()
            if slug in self._shared_folder_ids
            else provision.build_stignore_lines()
        )
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
        if not my_id:
            # ...and on the FIRST cycle there is no last known value to keep,
            # so every device -- the NAS included -- was upserted is_server=0
            # and the server showed up as a phantom editor row until a later
            # good cycle. _run_enforce has always skipped the pass here; this
            # one only said it did (KNOWN_BUGS DASH-7, 2026-08-11).
            log.error("skipping config: syncthing reported an empty myID and none is known yet")
            return
        self._my_id = my_id
        now = self.now_fn()
        # One query per cycle, not one per device: the device -> editor mapping
        # is only allowed to name an account the dashboard actually knows
        # about (see db.resolve_editor_username / B16).
        #
        # An EMPTY known set means a database that has never seeded -- the same
        # bootstrap hole _run_enforce's seed pass documents. Fall back to the
        # shape-only mapping there, or a first cycle would label every device
        # unmapped and the fleet views would come up blank until the enforce
        # pass ran. The label is display/attribution only; the authority for
        # unsharing is the validated mapping in _run_enforce.
        known_editors = db.known_editor_usernames(conn) or None
        for dev in cfg.get("devices", []):
            device_id = dev["deviceID"]
            self._device_ids[device_id] = db.upsert_device(
                conn, device_id, dev.get("name") or device_id, device_id == my_id, now,
                known_editors=known_editors,
            )
        seen: list[str] = []
        self._folder_devices = {}
        for folder in cfg.get("folders", []):
            slug = folder["id"]
            if slug in self._shared_folder_ids:
                # A shared asset library is a Syncthing folder but NOT a
                # project: no row, so it never shows up in the project list,
                # the tick UI, the per-project pages or the inventory walk
                # (which scans Projects/ and would find nothing for it).
                # Deliberately also kept out of `seen` below -- adding it
                # there would be harmless, but only by accident.
                continue
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
        devices are never added or removed. Only the `devices` list of a
        folder is ever modified.

        "Mapped" means the device's name resolves to an editor account the
        dashboard has a POSITIVE record of -- not merely one that is
        username-SHAPED. Machine names look exactly like usernames, so a
        device approved as `editor-laptop` used to resolve to an editor with no
        selections rows, which read as "ticked for nothing" and got it
        unshared from every folder it was on (KNOWN_BUGS B16).
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
        devices = [d for d in cfg.get("devices", []) if d["deviceID"] != my_id]

        if db.meta_get(conn, "selections_seeded") is None:
            # THE SEED IS THE BOOTSTRAP, so it deliberately uses the
            # shape-only mapping: on a fresh database there are no known
            # editors yet, and requiring one here would deadlock (no
            # selections -> no known editors -> no selections). It is safe
            # because seeding only ever ADDS a selection for a share that
            # already exists -- it can never produce a removal -- and every
            # editor it seeds is recorded as known, which is what the enforce
            # pass below then validates against.
            shape_map: dict[str, str | None] = {
                d["deviceID"]: db.resolve_editor_username(d.get("name") or "")
                for d in devices
            }
            now = self.now_fn()
            seeded = 0
            for folder in sorted(folders, key=lambda f: f.get("label") or f["id"]):
                if folder["id"] in self._shared_folder_ids:
                    # Seeding a tick for a shared asset library would put a
                    # non-project slug into every editor's selection list --
                    # visible in the tick UI and handed to their sequencer as
                    # a project to sync. These folders are shared
                    # unconditionally below; they never need a row.
                    continue
                for dev in folder.get("devices", []):
                    editor = shape_map.get(dev["deviceID"])
                    if not editor:
                        continue
                    # Seed onto the COMPUTER that device is, when the registry
                    # knows it; onto the unassigned bucket when it does not,
                    # which is what every pre-WP1 share resolves to and what
                    # the first report from that machine adopts.
                    known = db.machine_by_device_id(conn, dev["deviceID"])
                    machine = known["machine"] if known else db.ANY_MACHINE
                    if db.add_selection(conn, editor, folder["id"], "seed", now,
                                        machine=machine):
                        db.record_known_editor(conn, editor, "seed", now)
                        seeded += 1
            # Only claim the one-shot seed is DONE when the snapshot could
            # actually have produced selections. A first container start that
            # races Syncthing's own startup returns 200 with an empty device
            # list; flagging that as seeded makes the next enforce pass read
            # an empty selections table as authoritative and unshare every
            # editor from every folder, fleet-wide, silently (see the
            # seed-flag finding).
            if folders and any(editor for editor in shape_map.values()):
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
                    len(folders), sum(1 for e in shape_map.values() if e))

        # Resolved AFTER the seed, so anything it just recorded counts.
        known_editors = db.known_editor_usernames(conn)
        id_to_editor: dict[str, str | None] = {
            d["deviceID"]: db.resolve_editor_username(d.get("name") or "", known_editors)
            for d in devices
        }
        editor_devices: dict[str, set[str]] = {}
        for device_id, editor in id_to_editor.items():
            if editor:
                editor_devices.setdefault(editor, set()).add(device_id)
        for dev in devices:
            name = str(dev.get("name") or "")
            device_id = dev["deviceID"]
            # Username-SHAPED but not a known account: almost always a MACHINE
            # name (editor-laptop, edit-pc) approved as a device. Treated as
            # unmapped, i.e. left exactly as it is. Warned once per device per
            # process -- every 60s forever would be noise, and silence here is
            # what made B16 invisible.
            if (id_to_editor.get(device_id) is None
                    and db.resolve_editor_username(name) is not None
                    and device_id not in self._warned_unknown_editor):
                self._warned_unknown_editor.add(device_id)
                log.warning(
                    "device %r (%s) has a username-shaped name that matches no editor "
                    "account the dashboard knows -- treating it as UNMAPPED and leaving "
                    "its folder shares alone. If this really is an editor, tick a project "
                    "for them (or rename the device to their username).",
                    name, device_id)

        # PER COMPUTER since v24 (MULTI_MACHINE_PLAN.md WP3). A folder is
        # shared with a DEVICE, and a device is one machine -- but until the
        # machine registry existed the only way back from a device to a plan
        # was its owner's name, so both of one person's computers got every
        # project either was ticked for. `machine_devices` is the exact map;
        # a device that is not in it (never reported a machine_id, or its
        # Syncthing identity was regenerated) falls back to the person, which
        # is precisely the old behaviour and the safe direction.
        selections = db.fetch_machine_selections(conn)
        editor_selections = db.fetch_all_selections(conn)
        machine_devices: dict[tuple[str, str], str] = {}
        for row in db.fetch_machines(conn):
            device_id = row.get("syncthing_device_id")
            if device_id:
                machine_devices[(row["editor_username"], row["machine"])] = device_id
        mapped_device_ids = set(machine_devices.values())
        plans: list[tuple[str, set[str], set[str]]] = []   # (slug, desired, actual)
        for folder in folders:
            slug = folder["id"]
            actual = {d["deviceID"] for d in folder.get("devices", [])}
            desired = {my_id}
            # An UNMAPPED device is left exactly as it is -- but the REGISTRY
            # decides what unmapped means now, not the label (data-model-4,
            # 2026-08-21). A device approved straight in the Syncthing GUI
            # carries a hostname (DESKTOP-LQQ41TC) that resolves to no
            # editor, so it was frozen here: every tick added a share to it
            # (through machine_devices) and no untick ever removed one, i.e.
            # half of that machine's plan was dead. A device a companion has
            # reported IS a known computer with a known plan, whatever its
            # label says. Removals stay under the blast-radius brake below.
            desired |= {d for d in actual
                        if d in id_to_editor and id_to_editor[d] is None
                        and d not in mapped_device_ids}
            if slug in self._shared_folder_ids:
                # A shared asset library has no tick to consult: every editor
                # the dashboard knows about gets it, always. Reading
                # `selections` for one of these would find no rows and unshare
                # it from the entire fleet on the first cycle after it is
                # created -- the B16 failure shape, arrived at by a different
                # route.
                # NOT `devices`: that is the pass-wide device list, and
                # rebinding it here to a set of ids was harmless only because
                # nothing read it afterwards (KNOWN_BUGS DASH-6, 2026-08-11).
                for editor_device_ids in editor_devices.values():
                    desired |= editor_device_ids
            else:
                for editor, machine in selections.get(slug, []):
                    device_id = machine_devices.get((editor, machine))
                    if device_id and device_id not in id_to_editor:
                        # NOT APPROVED YET (dash-admin-6 / comp-lane-c-1,
                        # 2026-08-21). machines.syncthing_device_id is
                        # self-reported by the companion the moment it has a
                        # local Syncthing, which is typically before an admin
                        # approves the pending device on the NAS. Syncthing's
                        # own config prepare (ensureExistingDevices) silently
                        # drops a folder-device entry naming a device it does
                        # not have, so the PUT returned 200, `actual` never
                        # gained the id, and this cycle recomputed the same
                        # diff and rewrote config.xml every 60 s while the log
                        # claimed "+[<id>]" -- an admin reading it believes
                        # the share exists.
                        if device_id not in self._warned_unapproved_device:
                            self._warned_unapproved_device.add(device_id)
                            log.warning(
                                "%s/%s reports Syncthing device %s, which this server has "
                                "not approved -- its shares CANNOT be made yet. Approve the "
                                "pending device (Admin > Devices) and the next cycle will "
                                "share its projects.", editor, machine, device_id)
                        continue
                    if device_id:
                        desired.add(device_id)
                # ...plus every device of a ticked editor that no machine
                # claims. A per-machine plan cannot address a device the
                # registry has never seen, and dropping it here would unshare
                # a working editor the moment they upgraded the dashboard
                # ahead of their companion (the B16 failure shape again).
                for editor in editor_selections.get(slug, []):
                    desired |= {
                        d for d in editor_devices.get(editor, set())
                        if d not in mapped_device_ids
                    }
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
        #
        # COUNTED IN SHARE REMOVALS -- (folder, device) pairs -- not distinct
        # devices. The old device count meant ONE device being unshared from
        # all 40 folders scored 1 and sailed under the limit, which is exactly
        # the shape of the B16 failure it was supposed to catch: the setting
        # is named max_share_removals and now measures share removals.
        removals = [(slug, d) for slug, desired, actual in plans for d in (actual - desired)]
        removal_devices = {d for _slug, d in removals}
        limit = self.settings.enforce_max_share_removals
        skip_removals = len(removals) > limit
        if skip_removals:
            log.error(
                "REFUSING %d share removal(s) in one enforce cycle (limit %d): %d device(s) "
                "(%s) across %d folder(s). Additions still applied; raise "
                "DASH_ENFORCE_MAX_REMOVALS to override.",
                len(removals), limit, len(removal_devices),
                ", ".join(sorted(removal_devices)),
                len({slug for slug, _d in removals}))

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

    def _run_completion(self, conn) -> str | None:
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

        A WALL-CLOCK BUDGET bounds the cycle (ops-efficiency-5, 2026-08-21).
        This is one thread running every due kind in series, so a Syncthing
        that HANGS rather than refuses (a pool import, a stuck scan, a GUI
        under load) turned ~120 sequential 10 s-timeout calls into up to 20
        minutes during which no tick was enforced, connections never
        refreshed (editors flip to offline after 15 minutes) and
        /api/v1/health said ok=false. Past the budget the pass stops issuing
        NEW calls, writes what it has, and a rotating cursor makes the next
        cycle start where this one stopped -- so a slow fleet converges more
        slowly instead of starving enforce. Recorded as `partial` in
        poll_runs, because a health panel that cannot say why is the harder
        failure to diagnose.
        """
        fresh: dict[tuple[str, str], int] = {}
        folder_status: list[tuple[int, str | None, str | None]] = []
        rows: list[tuple[int, int, dict, Any, Any]] = []
        budget = float(getattr(self.settings, "completion_budget_seconds", 0.0) or 0.0)
        deadline = (time.monotonic() + budget) if budget > 0 else None
        call_timeout = self._completion_call_timeout()
        pairs = list(self._folder_devices.items())
        total = len(pairs)
        start = (self._completion_cursor % total) if total else 0
        polled: set[str] = set()
        left = 0
        # Rotated, so the folders the budget cut off last time are polled
        # FIRST this time. Without it the head of the list is refreshed for
        # ever and the tail never is.
        for offset, (slug, shared) in enumerate(
                [pairs[(start + i) % total] for i in range(total)]):
            # Only at a folder boundary: a half-polled folder would write a
            # `fresh` entry for some of its devices and drop the rest, which
            # reads as "that pair is fully synced".
            if deadline is not None and offset and time.monotonic() >= deadline:
                left = total - offset
                self._completion_cursor = (start + offset) % total
                log.warning(
                    "completion: %.0fs budget spent after %d of %d folder(s); the rest "
                    "run next cycle (DASH_COMPLETION_BUDGET_SECONDS)",
                    budget, offset, total)
                break
            polled.add(slug)
            project_id = self._project_ids.get(slug)
            if project_id is None:
                continue
            try:
                status = self.client.db_status(slug, timeout=call_timeout)
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
                    comp = self.client.completion(slug, device_id,
                                                  timeout=call_timeout)
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
        else:
            # for-else: reached only when the loop was NOT cut short by the
            # budget, i.e. every folder was polled, so the next pass starts
            # from the top again.
            self._completion_cursor = 0

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
        # Pairs whose folder this pass never reached keep their last known
        # need count: `fresh` prunes what is no longer shared, and a folder
        # left for the next cycle is not that (ops-efficiency-5).
        self._incomplete = {
            **{pair: n for pair, n in self._incomplete.items()
               if pair[0] not in polled and pair[0] in self._folder_devices},
            **fresh,
        }
        self._ingest_item_finished(conn, now)
        return f"partial: {left} folder(s) left for the next cycle" if left else None

    def _completion_call_timeout(self) -> float:
        """The per-call timeout for the completion pass (ops-efficiency-5,
        2026-08-21).

        These are the SMALLEST reads Syncthing serves and there are ~120 of
        them in a row on one thread. At the client default of 10 s a single
        hung pair eats a third of the whole cycle budget; three of them eat
        it all and enforce, connections and the health signal queue behind
        them. Never LONGER than the client is configured for, so a deployment
        that deliberately runs a tight client is not stretched by this.
        """
        return min(float(getattr(self.client, "timeout", 10.0) or 10.0),
                   COMPLETION_CALL_TIMEOUT_SECONDS)

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
