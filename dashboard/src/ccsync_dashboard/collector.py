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
from typing import Callable

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


class Collector:
    def __init__(
        self,
        settings: Settings,
        client: SyncthingClient | None = None,
        now_fn: Callable[[], str] = db.utcnow_iso,
    ):
        self.settings = settings
        self.client = client or SyncthingClient(settings.syncthing_url, settings.syncthing_api_key)
        self.now_fn = now_fn
        self._stop = threading.Event()
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

    def stop(self) -> None:
        self._stop.set()
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
                            next_due[kind] = time.monotonic() + backoff[kind]
                remaining = min(nd - time.monotonic() for nd in next_due.values())
                self._stop.wait(max(0.5, min(remaining, 5.0)))
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
        """Create (and share to every known editor device) a Syncthing folder
        for any project dir on disk that doesn't have one yet. Never touches
        existing folders."""
        projects_dir = Path(self.settings.projects_dir)
        if not projects_dir.is_dir():
            raise RuntimeError(f"DASH_PROJECTS_DIR does not exist: {projects_dir}")
        cfg = self.client.config()
        existing_ids = {f["id"] for f in cfg.get("folders", [])}
        for rel in provision.scan_project_dirs(projects_dir):
            slug = provision.slugify(rel)
            if slug in existing_ids:
                continue
            # Created unshared: the selections table + enforce cycle decide
            # which editor devices get each folder.
            folder = provision.build_folder_config(
                slug, rel, self.settings.syncthing_data_prefix, []
            )
            self.client.add_folder(folder)
            self.client.set_ignores(slug, provision.build_stignore_lines())
            log.info("auto-provisioned syncthing folder %s (%s), unshared until ticked",
                     slug, rel)

    def _run_config(self, conn) -> None:
        cfg = self.client.config()
        self._my_id = self.client.system_status().get("myID", "")
        now = self.now_fn()
        for dev in cfg.get("devices", []):
            device_id = dev["deviceID"]
            self._device_ids[device_id] = db.upsert_device(
                conn, device_id, dev.get("name") or device_id, device_id == self._my_id, now
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
                d["deviceID"] for d in folder.get("devices", []) if d["deviceID"] != self._my_id
            ]
        db.deactivate_missing_projects(conn, seen, now=now)

    def _run_enforce(self, conn) -> None:
        """Reconcile Syncthing folder shares with the selections table.

        Selections are the authority for MAPPED editor devices. Unmapped
        devices (name not a username) are never added or removed. Only the
        `devices` list of a folder is ever modified.
        """
        cfg = self.client.config()
        my_id = self.client.system_status().get("myID", "")
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
            db.meta_set(conn, "selections_seeded", now)
            log.info("seeded %d selections from existing folder shares", seeded)

        selections = db.fetch_all_selections(conn)
        for folder in folders:
            slug = folder["id"]
            actual = {d["deviceID"] for d in folder.get("devices", [])}
            desired = {my_id} if my_id else set()
            desired |= {d for d in actual if d in id_to_editor and id_to_editor[d] is None}
            for editor in selections.get(slug, []):
                desired |= editor_devices.get(editor, set())
            # devices outside the config snapshot entirely (shouldn't happen) stay put
            desired |= actual - set(id_to_editor) - ({my_id} if my_id else set())
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
        """Walk the NAS Projects tree (read-only /projects mount) for a
        bounded slice of projects each cycle, recording originals + proxies.

        Scale strategy: a cheap dirs-only scan computes a signature of
        (dir_relpath, mtime_ns); when it matches the stored signature the
        expensive per-file walk is skipped entirely (steady state = no
        writes). At most `inventory_projects_per_cycle` projects are touched
        per cycle via a rotating cursor, so a cold start or mass change never
        walks the whole fleet in one tick.
        """
        projects_dir = Path(self.settings.projects_dir)
        if not projects_dir.is_dir():
            raise RuntimeError(f"DASH_PROJECTS_DIR does not exist: {projects_dir}")
        active = conn.execute(
            "SELECT id, label FROM projects WHERE active=1 ORDER BY id"
        ).fetchall()
        if not active:
            return
        n = len(active)
        window = self.settings.inventory_projects_per_cycle
        start = self._inventory_cursor % n
        self._inventory_cursor = (start + window) % n
        selected = [active[(start + i) % n] for i in range(min(window, n))]

        now = self.now_fn()
        for row in selected:
            pid, label = row["id"], row["label"]
            proj_dir = projects_dir / label
            if not proj_dir.is_dir():
                db.record_inventory_error(conn, pid, "project dir missing on NAS", now)
                continue
            sig, n_dirs = self._dir_signature(proj_dir)
            if sig == db.nas_inventory_sig(conn, pid):
                continue  # unchanged since last walk -- skip the file scan
            rows = self._walk_media_files(proj_dir)
            db.replace_nas_media(conn, pid, rows, sig, n_dirs, now)
            log.info("inventory: %s -> %d media file(s)", label, len(rows))

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
        for slug, shared in self._folder_devices.items():
            project_id = self._project_ids[slug]
            status = self.client.db_status(slug)
            global_items = status.get("globalFiles")
            global_bytes = status.get("globalBytes")
            for device_id in shared:
                device_row = self._device_ids.get(device_id)
                if device_row is None:
                    continue
                comp = self.client.completion(slug, device_id)
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
                    now=self.now_fn(),
                )
                if completion >= 100 and need_items == 0:
                    db.clear_missing_files(conn, project_id, device_row)
                    self._incomplete.pop((slug, device_id), None)
                else:
                    self._incomplete[(slug, device_id)] = need_items

    def _run_remoteneed(self, conn) -> None:
        for (slug, device_id), need_items in list(self._incomplete.items()):
            project_id = self._project_ids.get(slug)
            device_row = self._device_ids.get(device_id)
            if project_id is None or device_row is None:
                continue
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
            truncated = need_items > len(files)
            db.replace_missing_files(conn, project_id, device_row, files, truncated, self.now_fn())

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
