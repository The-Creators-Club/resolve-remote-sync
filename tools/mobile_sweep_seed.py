#!/usr/bin/env python3
"""A seeded dashboard for the mobile sweep to photograph.

MOBILE_PLAN.md M0, 2026-08-30. `tools/mobile_sweep.js` measures pages, and a
page with no rows in it measures nothing: an empty fleet grid has no table to
overflow, an empty transfers window has no long filename to push the layout
sideways, and the phone layout would pass every check while being unusable on
real data. So this starts a REAL dashboard on a throwaway data dir with
enough rows that every page has its hard case on it.

    python tools/mobile_sweep_seed.py --port 8499

prints the URL and the admin credentials and stays up until Ctrl+C.

Everything here goes through `db.py`'s own writers and `local_users.py`'s own
account creation -- no monkeypatching, no INSERTs of our own. The reason is
that a fixture which writes the tables by hand drifts from what a companion's
report actually produces, and then the sweep is measuring a page nobody will
ever see. The cost is that a few states cannot be faked (see SEED NOTES at
the foot of this file).

The auth method is `local` (ZERO_TOUCH_PLAN.md WP C) precisely because it is
the one that needs no NAS: the sweep has to be able to log in on a machine
with no TrueNAS and no SMB server anywhere near it.
"""
from __future__ import annotations

import argparse
import atexit
import secrets
import shutil
import socket
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# Same insertion tests/conftest.py does, and for the same reason: this tool is
# run from a worktree and must import THAT worktree's dashboard, never the
# main checkout's copy that happens to be installed in the venv.
sys.path.insert(0, str(REPO / "dashboard" / "src"))

from ccsync_dashboard import db as dbmod  # noqa: E402
from ccsync_dashboard import local_users  # noqa: E402
from ccsync_dashboard.app import create_app  # noqa: E402
from ccsync_dashboard.settings import Settings  # noqa: E402

# The three editors and the five machines. Names are invented and deliberately
# unlike anyone in the real fleet: a screenshot of this ends up in docs/.
EDITORS = ("jsmith", "mrivera", "tchen")
MACHINES = (
    # (editor, machine, platform, companion version, what it is here to show)
    ("jsmith", "JSMITH-STUDIO", "windows", "0.9.54", "healthy, lane A moving"),
    ("jsmith", "JSMITH-MBP", "macos", "0.9.54", "lane B breaker tripped"),
    ("mrivera", "RIVERA-TOWER", "windows", "0.9.54", "halted by the operator"),
    ("mrivera", "RIVERA-LAPTOP", "windows", "0.9.53", "running a job at 37 percent"),
    ("tchen", "TCHEN-RIG", "windows", "0.9.49", "out of date, lane C erroring"),
)
PROJECTS = (
    ("2026-ff5-elections", "2026/FF5/Elections", "/mnt/tank/Projects/2026/FF5/Elections"),
    ("2026-ff5-animals", "2026/FF5/Animals", "/mnt/tank/Projects/2026/FF5/Animals"),
)
# Long on purpose. The longest cell is what decides whether a table can be
# stacked on a phone or has to scroll, so the seed has to contain one.
LONG_CLIP = ("A017_C019_0830QP_001 - Mei-Hsiu Hwang interview, second unit, "
             "take 4 (handheld).mov")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def seed(conn, admin: str) -> None:
    """Fill an empty, migrated database. One `now` throughout, so nothing on a
    page can be off by the seconds this function takes."""
    now = dbmod.utcnow_iso()

    for editor in EDITORS:
        dbmod.record_known_editor(conn, editor, "seed", now)

    project_ids = {}
    for slug, label, path in PROJECTS:
        project_ids[slug] = dbmod.upsert_project(conn, slug, label, path, now)

    # A Syncthing device per machine plus the server, and a completion row per
    # (project, device): the fleet grid's project cards read these, and with no
    # devices at all the densest widget on the site renders as one empty row.
    dbmod.upsert_device(conn, "SERVER-DEVICEID-AAAAAAA", "truenas", True, now)
    for i, (editor, machine, platform, version, _why) in enumerate(MACHINES):
        device_id = f"DEVICE{i}-{machine}-XXXXXXX"
        dbmod.upsert_machine(conn, editor, machine, now,
                             machine_id=f"mid-{i:04d}", platform=platform,
                             syncthing_device_id=device_id)
        dbmod.upsert_device(conn, device_id, machine, False, now,
                            known_editors={editor})

    dbmod.set_connections(
        conn,
        {f"DEVICE{i}-{m[1]}-XXXXXXX": (now if i != 4 else None)
         for i, m in enumerate(MACHINES)},
        now,
    )

    _seed_machine_states(conn, now)
    _seed_lanes(conn, now)
    _seed_media(conn, project_ids, now)
    _seed_selections(conn, admin, now)
    _seed_transfers(conn, now)
    _seed_jobs(conn, now)
    _seed_notices_and_alerts(conn, now)
    _seed_packages(conn, admin, now)
    conn.commit()


def _seed_machine_states(conn, now: str) -> None:
    """One machine_state row per machine, with the guard section that puts the
    breaker / halt / disk chips on the grid.

    The guard dict is flatten_sync_guard()'s shape (db.upsert_machine_state's
    docstring names it); writing the columns directly would skip the latch
    rules that decide whether a chip can ever clear.
    """
    common = {"trash_bytes": 2 * 1024**3, "trash_count": 412, "skipped_exists": 39,
              "at": now, "disk_at": now, "rotation_seconds": 900,
              "disk_root_total_bytes": 4 * 1024**4}

    dbmod.upsert_machine_state(
        conn, "jsmith", "JSMITH-STUDIO", "P:\\Projects", now,
        resolve_project="FF5 Elections E2", verified=True, platform="windows",
        companion_version="0.9.54", mode="wired", client_reported_at=now,
        guard=dict(common, breaker_tripped=False, halt_active=False,
                   disk_root_free_bytes=900 * 1024**3),
        proxy={"missing": 0, "state": "ok", "left": 0},
    )
    dbmod.upsert_machine_state(
        conn, "jsmith", "JSMITH-MBP", "/Volumes/P/Projects", now,
        resolve_project="FF5 Animals E1", verified=True, platform="macos",
        companion_version="0.9.54", mode="remote", client_reported_at=now,
        guard=dict(common, breaker_tripped=True,
                   breaker_reason="lane B would have deleted 1,204 files that "
                                  "the server no longer offers",
                   breaker_at=now, halt_active=False,
                   sync_conflicts=7, crash_count=2, crash_newest=now,
                   disk_root_free_bytes=41 * 1024**3),
    )
    dbmod.upsert_machine_state(
        conn, "mrivera", "RIVERA-TOWER", "P:\\Projects", now,
        resolve_project=None, verified=True, platform="windows",
        companion_version="0.9.54", mode="wired", client_reported_at=now,
        guard=dict(common, breaker_tripped=False, halt_active=True,
                   halt_scope="machine",
                   halt_reason="paused by the operator while the tower's "
                               "second disk is replaced",
                   disk_root_free_bytes=7 * 1024**3,
                   blocked_reason="halted", blocked_since=now),
    )
    dbmod.upsert_machine_state(
        conn, "mrivera", "RIVERA-LAPTOP", "P:\\Projects", now,
        resolve_project="FF5 Animals E1", verified=True, platform="windows",
        companion_version="0.9.53", mode="remote", client_reported_at=now,
        guard=dict(common, breaker_tripped=False, halt_active=False,
                   disk_root_free_bytes=120 * 1024**3),
        ingest={"active": True, "batch": "b-2026-08-30-01", "state": "indexing",
                "done": 37, "total": 100, "failed": 1, "clip": LONG_CLIP,
                "percent": 37.0, "tier": "standard", "at": now},
    )
    dbmod.upsert_machine_state(
        conn, "tchen", "TCHEN-RIG", None, now,
        resolve_project="FF5 Elections E1", verified=False, platform="windows",
        companion_version="0.9.49", mode="remote", client_reported_at=now,
        guard=dict(common, breaker_tripped=False, halt_active=False,
                   folders_unfiltered=2,
                   folders_unfiltered_names="2026-ff5-animals, shared-assets",
                   supervisor_supervising=False, supervisor_attempts=14,
                   supervisor_last_error="Syncthing exited 1 (config in use)",
                   restarts_count_24h=6, restarts_last_at=now,
                   restarts_last_error="lane C watchdog restarted Syncthing",
                   stalled_lane="B", stalled_seconds=2700, stalled_killed=True,
                   stalled_at=now,
                   disk_root_free_bytes=2 * 1024**3),
    )


def _seed_lanes(conn, now: str) -> None:
    """Three lanes per machine, in the mix of states the grid has chips for.

    The lane vocabulary is api.py's LaneReport model: idle, syncing, error,
    paused. "Halted" and "breaker tripped" are NOT lane states -- they are the
    guard latches above, which is exactly why the grid needs both (item 9).
    """
    lanes = {
        "JSMITH-STUDIO": [
            ("A", "syncing", 3, 1, None, "uploading originals", 41 * 1024**3,
             96 * 1024**3, 82e6, 640.0),
            ("B", "idle", 0, 0, None, None, None, None, None, None),
            ("C", "syncing", 118, 4, None, "shared assets", None, None, None, None),
        ],
        "JSMITH-MBP": [
            ("A", "idle", 0, 0, None, None, None, None, None, None),
            ("B", "paused", 1204, 0, "breaker tripped", "lane B is held", None,
             None, None, None),
            ("C", "idle", 0, 0, None, None, None, None, None, None),
        ],
        "RIVERA-TOWER": [
            ("A", "paused", 61, 0, None, "halted", None, None, None, None),
            ("B", "paused", 0, 0, None, "halted", None, None, None, None),
            ("C", "paused", 0, 0, None, "halted", None, None, None, None),
        ],
        "RIVERA-LAPTOP": [
            ("A", "syncing", 12, 2, None, LONG_CLIP, 3 * 1024**3, 8 * 1024**3,
             12e6, 410.0),
            ("B", "syncing", 340, 6, None, "pulling proxies", 18 * 1024**3,
             52 * 1024**3, 31e6, 1090.0),
            ("C", "idle", 0, 0, None, None, None, None, None, None),
        ],
        "TCHEN-RIG": [
            ("A", "error", 0, 0,
             "rclone: failed to open source object: Access is denied.", None,
             None, None, None, None),
            ("B", "error", 88, 0, "connection reset by peer", None, None, None,
             None, None),
            ("C", "error", 0, 0, "Syncthing is not running on this machine",
             None, None, None, None, None),
        ],
    }
    by_machine = {m: (e, v) for e, m, _p, v, _w in MACHINES}
    for machine, rows in lanes.items():
        editor, version = by_machine[machine]
        for (lane, state, queued, transferring, error, detail, done, total,
             speed, eta) in rows:
            dbmod.upsert_lane_report(
                conn, editor_username=editor, machine=machine, lane=lane,
                state=state, queued=queued, transferring=transferring,
                last_error=error, last_sync=now, detail=detail,
                companion_version=version, reported_at=now, received_at=now,
                current_project=PROJECTS[0][0] if lane == "A" else None,
                bytes_done=done, bytes_total=total, speed_bps=speed,
                eta_seconds=eta, state_since=now,
            )


def _seed_media(conn, project_ids: dict, now: str) -> None:
    """The NAS inventory, each machine's rollup, and the Resolve bin trees the
    project page's BINS panel renders."""
    for slug, _label, _path in PROJECTS:
        rows = [
            (f"Footage/Day {d:02d}/A0{d:02d}_C0{c:02d}_0830QP_001.mov",
             "original", ".mov", 12_000_000_000 + c, None)
            for d in range(1, 4) for c in range(1, 9)
        ]
        rows.append((f"Footage/Day 01/{LONG_CLIP}", "original", ".mov",
                     41_000_000_000, None))
        dbmod.replace_nas_media(conn, project_ids[slug], rows,
                                f"sig-{slug}", 6, now, force=True)
        dbmod.set_folder_status(conn, project_ids[slug], "idle", None, now,
                                need_items=0, need_bytes=0)

    bins = [
        ("Interviews/Day 01", "A001_C001_0830QP_001", "P:\\...\\A001_C001.mov",
         "video", True),
        ("Interviews/Day 01", LONG_CLIP, f"P:\\...\\{LONG_CLIP}", "video", False),
        ("Interviews/Day 02", "A002_C004_0830QP_001", "P:\\...\\A002_C004.mov",
         "video", True),
        ("B-roll/Reef", "GX010233", "P:\\...\\GX010233.MP4", "video", True),
        ("B-roll/Reef", "GX010234", "P:\\...\\GX010234.MP4", "video", False),
        ("Audio", "ZOOM0041_Tr1", "P:\\...\\ZOOM0041_Tr1.WAV", "audio", True),
    ]
    for editor, machine, _platform, _version, _why in MACHINES[:4]:
        for slug, _label, _path in PROJECTS:
            dbmod.upsert_editor_media_project(
                conn, editor=editor, machine=machine, slug=slug, mode="editor",
                n_originals=21, bytes_originals=260 * 1024**3,
                n_proxies=25, bytes_proxies=9 * 1024**3, truncated=False, now=now)
            dbmod.replace_editor_media(
                conn, editor, machine, slug,
                [(f"Footage/Day 01/A001_C{i:03d}_0830QP_001.mov", "original",
                  12_000_000_000) for i in range(1, 22)], now)
            dbmod.replace_media_tree(conn, editor, machine, slug, bins, now)


def _seed_selections(conn, admin: str, now: str) -> None:
    """Who syncs what. add_selection writes the audit row too, which is what
    puts content on /admin/audit and in the plan-changes panel."""
    dbmod.add_selection(conn, "jsmith", PROJECTS[0][0], created_by=admin, now=now,
                        machine="JSMITH-STUDIO")
    dbmod.add_selection(conn, "jsmith", PROJECTS[1][0], created_by=admin, now=now,
                        machine="JSMITH-MBP", sync_mode=dbmod.SYNC_MODE_UPLOAD_ONLY)
    dbmod.add_selection(conn, "mrivera", PROJECTS[0][0], created_by=admin, now=now,
                        machine="RIVERA-TOWER")
    dbmod.add_selection(conn, "mrivera", PROJECTS[1][0], created_by="mrivera", now=now,
                        machine="RIVERA-LAPTOP")
    dbmod.add_selection(conn, "tchen", PROJECTS[1][0], created_by=admin, now=now,
                        machine="TCHEN-RIG")


def _seed_transfers(conn, now: str) -> None:
    """Twelve live rows, which is what the plan asks for, plus a history tail
    so the /transfers page has both halves. Twelve is the number that makes
    the home page's 35vh window scroll instead of merely existing."""
    live = {
        ("jsmith", "JSMITH-STUDIO"): [
            ("A", "A001_C001_0830QP_001.mov", "up", 0.61),
            ("A", "A001_C002_0830QP_001.mov", "up", 0.12),
            ("C", "shared-assets/LUTs/FF5_Show.cube", "down", 0.94),
        ],
        ("mrivera", "RIVERA-LAPTOP"): [
            ("A", LONG_CLIP, "up", 0.37),
            ("B", "Proxies/Day 02/A002_C004_0830QP_001.mov", "down", 0.55),
            ("B", "Proxies/Day 02/A002_C005_0830QP_001.mov", "down", 0.08),
            ("B", "Proxies/Day 02/A002_C006_0830QP_001.mov", "down", 0.03),
        ],
        ("jsmith", "JSMITH-MBP"): [
            ("A", "Interviews/Day 03/A003_C011_0830QP_001.mov", "up", 0.44),
            ("A", "Interviews/Day 03/A003_C012_0830QP_001.mov", "up", 0.02),
        ],
        ("tchen", "TCHEN-RIG"): [
            ("A", "Stills/DSC_9912.NEF", "up", 0.77),
            ("A", "Stills/DSC_9913.NEF", "up", 0.21),
            ("C", "shared-assets/Fonts/FF5-Display.otf", "down", 0.66),
        ],
    }
    for (editor, machine), rows in live.items():
        dbmod.replace_active_transfers(conn, editor, machine, [
            {"lane": lane, "name": name, "direction": direction,
             "bytes_done": int(12 * 1024**3 * pct), "bytes_total": 12 * 1024**3,
             "percentage": pct * 100, "speed_bps": 42e6,
             "eta_seconds": 900 * (1 - pct),
             "project_slug": PROJECTS[0][0]}
            for lane, name, direction, pct in rows
        ], now)
        dbmod.add_transfer_history(conn, editor, machine, [
            {"lane": lane, "name": name, "direction": direction, "at": now}
            for lane, name, direction, _pct in rows
        ], now)


def _seed_jobs(conn, now: str) -> None:
    """Four queued jobs and one running at 37 percent.

    The running one is a claim by a real machine through db.claim_job, not a
    row with state='running' written by hand: the claim is compare-and-set and
    the page reads the lease it sets (docs/API.md 6c). "Forced" and "targeted"
    jobs are in the plan's §10 wish list and do not exist in this schema yet,
    so these are plain -- as MOBILE_PLAN.md §M0 allows.
    """
    dbmod.create_job(conn, dbmod.JOB_KIND_WHISPER,
                     {"root": "media", "rel_path": f"Footage/Day 01/{LONG_CLIP}"},
                     requires={"capabilities": ["whisper"]},
                     created_by="owen", priority=10, now=now)
    dbmod.create_job(conn, dbmod.JOB_KIND_PROXY_480P,
                     {"root": "media", "rel_path": "Footage/Day 02/A002_C004.mov"},
                     created_by="owen", now=now)
    dbmod.create_job(conn, dbmod.JOB_KIND_AUDIO_EXTRACT,
                     {"root": "media", "rel_path": "Footage/Day 02/A002_C005.mov"},
                     created_by="mrivera", now=now)
    dbmod.create_job(conn, dbmod.JOB_KIND_PEAKS,
                     {"root": "media", "rel_path": "Audio/ZOOM0041_Tr1.WAV"},
                     created_by="mrivera", now=now)
    running = dbmod.create_job(
        conn, dbmod.JOB_KIND_PROXY_480P,
        {"root": "media", "rel_path": f"Footage/Day 01/{LONG_CLIP}"},
        created_by="owen", now=now)
    dbmod.claim_job(conn, running, "mrivera", "RIVERA-LAPTOP", now=now)
    dbmod.heartbeat_job(conn, running, "mrivera", "RIVERA-LAPTOP", now=now,
                        note="ffmpeg pass 1", progress=0.37)


def _seed_notices_and_alerts(conn, now: str) -> None:
    dbmod.notice(conn, "machine_disk_low", "error",
                 subject="TCHEN-RIG has 2 GB free",
                 body="The lane A upload will stop when the disk fills. "
                      "Free space on the media drive or move the project off it.",
                 fix="Ask Tchen to empty the Syncthing trash on TCHEN-RIG.",
                 now=now)
    dbmod.notice(conn, "machine_trash_oversize", "warn",
                 subject="JSMITH-MBP is holding 2 GB of Syncthing trash",
                 body="Versioned deletes on this machine have not been pruned.",
                 now=now)
    dbmod.notice(conn, "editor_without_machine", "warn",
                 subject="tchen has a plan but no machine reporting for it",
                 body="A plan that no computer holds syncs nothing.", now=now)
    dbmod.notice(conn, "syncthing_unreachable", "info",
                 subject="the collector reached Syncthing on the second try",
                 body="One cycle failed and the next one succeeded.", now=now)
    dbmod.record_alert(conn, "machine_disk_low", "TCHEN-RIG has 2 GB free",
                       "ops@example.invalid", True,
                       detail="smtp, 1 recipient", now=now)


def _seed_packages(conn, admin: str, now: str) -> None:
    """Two published companion builds with one current per platform, which is
    what /admin/packages and /installer both render off."""
    for platform, filename in (("windows", "ccsync-companion-0.9.54-win64.exe"),
                               ("macos", "ccsync-companion-0.9.54-macos.pkg")):
        for version in ("0.9.53", "0.9.54"):
            dbmod.insert_companion_package(
                conn, version=version, platform=platform,
                filename=filename.replace("0.9.54", version),
                sha256=secrets.token_hex(32), size_bytes=118_000_000,
                published_by=admin, now=now, signature="", pubkey_id="",
                min_version="0.9.40", signed_binary=True, arch="x86_64")
        dbmod.set_current_package(conn, platform, "0.9.54")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=0,
                    help="port to serve on (default: a free one)")
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address (default 127.0.0.1; leave it there -- "
                         "this dashboard has seeded credentials in it)")
    ap.add_argument("--admin", default="owen", help="the admin username to create")
    ap.add_argument("--password", default="",
                    help="the admin password (default: a fresh random one)")
    ap.add_argument("--data", default="",
                    help="data dir to use and KEEP (default: a temp dir, removed "
                         "on exit)")
    args = ap.parse_args()

    port = args.port or free_port()
    password = args.password or ("sweep-" + secrets.token_urlsafe(9))
    if args.data:
        data = Path(args.data)
        data.mkdir(parents=True, exist_ok=True)
    else:
        data = Path(tempfile.mkdtemp(prefix="ccsync-mobile-sweep-"))
        atexit.register(shutil.rmtree, data, True)

    db_path = data / "dashboard.db"
    conn = dbmod.connect(db_path)
    dbmod.migrate(conn)
    # The accounts first: local_users.create_user is the real writer, so the
    # admin the sweep signs in as is an account the Users page can also show,
    # disable and delete -- which is the page's own hard case.
    local_users.create_user(conn, args.admin, password, "admin",
                            created_by=args.admin)
    for editor in EDITORS:
        local_users.create_user(conn, editor, "seed-" + secrets.token_urlsafe(9),
                                "editor", created_by=args.admin)
    conn.commit()
    seed(conn, args.admin)
    conn.close()

    settings = Settings(
        db_path=str(db_path),
        # A real random secret, not "s"*32: check_boot_secrets refuses a weak
        # one, and DASH_DEV_INSECURE would turn off the CSRF check the sweep's
        # login is supposed to exercise.
        session_secret=secrets.token_urlsafe(48),
        admin_users=frozenset({args.admin}),
        auth_method="local",
        port=port,
    )
    app = create_app(settings)

    url = f"http://{args.host}:{port}"
    print("")
    print(f"  URL       {url}")
    print(f"  user      {args.admin}")
    print(f"  password  {password}")
    print(f"  data      {data}")
    print("")
    print("  node tools/mobile_sweep.js --url %s --user %s --password %s"
          % (url, args.admin, password))
    print("")
    print("  Ctrl+C to stop.")
    print("", flush=True)

    import uvicorn

    uvicorn.run(app, host=args.host, port=port, workers=1, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# SEED NOTES -- what this could not produce with the real writers, 2026-08-30:
#
#  * /admin/users lists NAS accounts through the NAS client, and there is no
#    NAS here, so that page shows its "no NAS configured" banner over the
#    local accounts. That IS a real state (the appliance shape), and it is the
#    narrower page, so the sweep measures the easier case there.
#  * /admin/recovery and /admin/protection report on snapshots and dataset
#    protection read live from TrueNAS; with no NAS they render their
#    unavailable states. Same call: real, and narrower than the populated one.
#  * "Forced" and "targeted" jobs (MOBILE_PLAN.md §M0) have no columns in the
#    v41 jobs schema on this branch, so the four queued jobs are plain.
#  * The fleet halt is left OFF: a fleet-wide halt banner is on every page and
#    would sit at the top of all seventeen screenshots. One machine-scope halt
#    (RIVERA-TOWER) carries the same layout risk on the page that owns it.
