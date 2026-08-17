"""External-SSD root guard tests (root_guard.py).

Every darwin behaviour here is exercised from Windows through the module's
injected seams (is_darwin/isdir_fn/ismount_fn/listdir_fn/run_fn/clock), same
convention as test_shutdown_guard.py's macOS half: no test may depend on the
host OS, and nothing here spawns diskutil.

The load-bearing one is the GHOST DIRECTORY: an empty leftover at
/Volumes/<Name> on the boot disk, for which os.path.isdir answers True. If
the guard believed it, lane B's `rclone sync` would fill the Mac's internal
disk with the project that belongs on the SSD.
"""

from __future__ import annotations

import json
import plistlib
import threading

from ccsync_companion import root_guard as rg


ROOT = "/Volumes/T7/Creators_Club"
MOUNT = "/Volumes/T7"
UUID = "AAAA1111-BBBB-2222-CCCC-333333333333"


def _plist(uuid: str) -> bytes:
    return plistlib.dumps({"VolumeUUID": uuid, "FilesystemType": "apfs"})


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _probe(**overrides):
    """probe_root with every seam fed and nothing touching the real host."""
    kwargs = dict(
        local_root=ROOT,
        is_darwin=True,
        isdir_fn=lambda p: True,
        ismount_fn=lambda p: True,
        listdir_fn=lambda p: [],
        run_fn=lambda argv, timeout=0: None,
        clock=_Clock(),
        record={},
        cache={},
    )
    kwargs.update(overrides)
    return rg.probe_root(**kwargs)


# -- mount point derivation -------------------------------------------------


def test_mount_point_for_external_volume_roots():
    assert rg.mount_point_for(ROOT) == MOUNT
    assert rg.mount_point_for(MOUNT) == MOUNT
    assert rg.mount_point_for("/Volumes/My Drive 2/Creators_Club") == "/Volumes/My Drive 2"


def test_mount_point_for_is_none_off_volumes():
    assert rg.mount_point_for("/Users/owen/Creators_Club") is None
    assert rg.mount_point_for("C:\\Creators_Club") is None
    assert rg.mount_point_for("") is None
    assert rg.mount_point_for(None) is None


# -- the probe --------------------------------------------------------------


def test_windows_probe_is_isdir_only(tmp_path):
    """Byte-identical to the pre-guard behaviour: no mount check, no
    diskutil, no /Volumes listing -- Windows has no ghost-mount failure."""
    touched: list[str] = []

    def _ismount(path):
        touched.append(path)
        return False

    assert _probe(is_darwin=False, isdir_fn=lambda p: True, ismount_fn=_ismount) == rg.ROOT_PRESENT
    assert _probe(is_darwin=False, isdir_fn=lambda p: False, ismount_fn=_ismount) == rg.ROOT_ABSENT
    assert touched == []


def test_windows_probe_never_spawns_diskutil():
    spawned: list[list] = []

    def _run(argv, timeout=0):
        spawned.append(argv)
        return _plist(UUID)

    assert _probe(
        is_darwin=False, isdir_fn=lambda p: False, run_fn=_run,
        record={"volume_uuid": UUID},
    ) == rg.ROOT_ABSENT
    assert spawned == []


def test_darwin_present_needs_both_isdir_and_a_real_mount():
    assert _probe(isdir_fn=lambda p: True, ismount_fn=lambda p: True) == rg.ROOT_PRESENT


def test_ghost_directory_is_absent_not_present():
    """THE failure this module exists for: an empty leftover directory at
    /Volumes/T7 on the BOOT volume. isdir() says yes; ismount() says no; and
    believing isdir is how an editor's internal disk fills up overnight."""
    assert _probe(isdir_fn=lambda p: True, ismount_fn=lambda p: False) == rg.ROOT_ABSENT


def test_unplugged_drive_is_absent():
    assert _probe(isdir_fn=lambda p: False, ismount_fn=lambda p: False) == rg.ROOT_ABSENT


def test_darwin_root_off_volumes_is_isdir_only():
    """~/Creators_Club on the internal disk: there is no volume to be
    mounted, so the mount check must not be applied to it."""
    assert _probe(
        local_root="/Users/owen/Creators_Club",
        isdir_fn=lambda p: True, ismount_fn=lambda p: False,
    ) == rg.ROOT_PRESENT


def test_ghost_directory_with_a_recorded_uuid_is_misplaced():
    """The drive IS plugged in -- macOS mounted it at '/Volumes/T7 1'
    because the leftover directory occupies /Volumes/T7."""
    seen: list[str] = []

    def _run(argv, timeout=0):
        seen.append(argv[-1])
        return _plist(UUID) if argv[-1] == "/Volumes/T7 1" else _plist("OTHER-UUID")

    state = _probe(
        isdir_fn=lambda p: True,
        ismount_fn=lambda p: p != ROOT and p != MOUNT,
        listdir_fn=lambda p: ["Macintosh HD", "T7 1"],
        run_fn=_run,
        record={"volume_uuid": UUID, "mount_point": MOUNT, "local_root": ROOT},
    )
    assert state == rg.ROOT_MISPLACED
    # The expected mount point is skipped, never asked about.
    assert MOUNT not in seen


def test_misplaced_is_undetectable_without_a_recorded_uuid():
    """macos_bootstrap.sh tolerates a volume diskutil gave no UUID for, so
    the guard must too: `absent` says the same thing with less detail."""
    def _run(argv, timeout=0):
        raise AssertionError("diskutil must not be spawned with no UUID to match")

    assert _probe(
        isdir_fn=lambda p: False, ismount_fn=lambda p: False,
        listdir_fn=lambda p: ["T7 1"], run_fn=_run, record={"volume_uuid": ""},
    ) == rg.ROOT_ABSENT


def test_a_volume_mounted_at_the_expected_point_is_not_misplaced():
    """The drive is where it belongs but the tree is not on it (wrong drive,
    or someone deleted the folder). That is absent, not misplaced."""
    assert _probe(
        isdir_fn=lambda p: False, ismount_fn=lambda p: p == MOUNT,
        listdir_fn=lambda p: ["T7"], run_fn=lambda argv, timeout=0: _plist(UUID),
        record={"volume_uuid": UUID},
    ) == rg.ROOT_ABSENT


def test_blank_local_root_is_unknown_not_absent():
    """A blank local_root is a CONFIG error (validate_config says so). Calling
    it a disconnected drive would send the editor hunting for a cable."""
    assert _probe(local_root="") == rg.ROOT_UNKNOWN
    assert _probe(local_root=None) == rg.ROOT_UNKNOWN


def test_probe_never_raises_and_reports_unknown():
    def _boom(path):
        raise OSError("no")

    assert _probe(ismount_fn=_boom) == rg.ROOT_UNKNOWN
    assert _probe(isdir_fn=_boom) == rg.ROOT_UNKNOWN


def test_an_unlistable_volumes_dir_degrades_to_absent():
    def _boom(path):
        raise PermissionError("nope")

    assert _probe(
        isdir_fn=lambda p: False, ismount_fn=lambda p: False,
        listdir_fn=_boom, record={"volume_uuid": UUID},
    ) == rg.ROOT_ABSENT


# -- diskutil parsing + caching ---------------------------------------------


def test_parse_volume_uuid_reads_a_real_plist():
    assert rg.parse_volume_uuid(_plist(UUID)) == UUID


def test_parse_volume_uuid_falls_back_to_the_regex():
    """Mirrors macos_bootstrap.sh's plutil-then-sed pair: a payload plistlib
    cannot load must not cost us the one field that separates `misplaced`
    from `absent`."""
    broken = (
        b"<plist><dict><key>VolumeUUID</key><string>" + UUID.encode() + b"</string>"
    )  # deliberately truncated -- no closing tags
    assert rg.parse_volume_uuid(broken) == UUID


def test_parse_volume_uuid_of_nothing_is_none():
    assert rg.parse_volume_uuid(None) is None
    assert rg.parse_volume_uuid(b"") is None
    assert rg.parse_volume_uuid(b"not a plist at all") is None


def test_diskutil_answers_are_cached_for_the_ttl():
    clock = _Clock()
    cache: dict = {}
    calls: list[list] = []

    def _run(argv, timeout=0):
        calls.append(argv)
        return _plist(UUID)

    for _ in range(5):
        assert rg.volume_uuid(MOUNT, run_fn=_run, clock=clock, cache=cache) == UUID
    assert len(calls) == 1

    clock.advance(rg.DISKUTIL_CACHE_SECONDS - 1)
    rg.volume_uuid(MOUNT, run_fn=_run, clock=clock, cache=cache)
    assert len(calls) == 1

    clock.advance(2)
    rg.volume_uuid(MOUNT, run_fn=_run, clock=clock, cache=cache)
    assert len(calls) == 2


def test_a_uuidless_volume_is_cached_too():
    """Otherwise a volume diskutil will not describe costs a process spawn on
    every 5 s poll for as long as it stays plugged in."""
    calls: list[list] = []
    cache: dict = {}

    def _run(argv, timeout=0):
        calls.append(argv)
        return None

    assert rg.volume_uuid(MOUNT, run_fn=_run, clock=_Clock(), cache=cache) is None
    assert rg.volume_uuid(MOUNT, run_fn=_run, clock=_Clock(), cache=cache) is None
    assert len(calls) == 1


# -- the volume record -------------------------------------------------------


def test_write_and_read_the_volume_record(tmp_path):
    path = tmp_path / "volume.json"
    assert rg.write_volume_record(
        {"volume_uuid": UUID, "mount_point": MOUNT, "local_root": ROOT}, path
    ) is True
    assert rg.read_volume_record(path) == {
        "volume_uuid": UUID, "mount_point": MOUNT, "local_root": ROOT,
    }
    # Atomic: the temp file is replaced, never left beside the record.
    # Named siblings, not "tmp_path holds exactly one entry" (2026-08-17):
    # conftest's _eula_already_accepted writes the licence record into
    # tmp_path/.ccsync, so the whole-directory form was measuring the
    # fixture, not the write. What this test is about is that
    # write_volume_record leaves no .tmp beside its own output.
    siblings = [p.name for p in tmp_path.iterdir() if p.is_file()]
    assert siblings == ["volume.json"]


def test_read_volume_record_tolerates_everything(tmp_path):
    assert rg.read_volume_record(tmp_path / "missing.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert rg.read_volume_record(bad) is None
    listy = tmp_path / "list.json"
    listy.write_text("[1, 2]", encoding="utf-8")
    assert rg.read_volume_record(listy) is None


def test_refresh_records_the_volume_on_a_present_sighting(tmp_path):
    path = tmp_path / "volume.json"
    record = rg.refresh_volume_record(
        ROOT, is_darwin=True, run_fn=lambda argv, timeout=0: _plist(UUID),
        clock=_Clock(), cache={}, record_path=path,
    )
    assert record == {"volume_uuid": UUID, "mount_point": MOUNT, "local_root": ROOT}
    assert json.loads(path.read_text(encoding="utf-8"))["volume_uuid"] == UUID


def test_refresh_does_not_rewrite_an_unchanged_record(tmp_path, monkeypatch):
    path = tmp_path / "volume.json"
    rg.write_volume_record(
        {"volume_uuid": UUID, "mount_point": MOUNT, "local_root": ROOT}, path
    )
    writes: list = []
    monkeypatch.setattr(rg, "write_volume_record",
                        lambda record, p=None: writes.append(record) or True)
    rg.refresh_volume_record(
        ROOT, is_darwin=True, run_fn=lambda argv, timeout=0: _plist(UUID),
        clock=_Clock(), cache={}, record_path=path,
    )
    assert writes == []


def test_refresh_keeps_a_known_uuid_when_diskutil_goes_quiet(tmp_path):
    """Overwriting it with "" would throw away the only thing that can tell
    `misplaced` from `absent` on the next unplug."""
    path = tmp_path / "volume.json"
    rg.write_volume_record(
        {"volume_uuid": UUID, "mount_point": MOUNT, "local_root": ROOT}, path
    )
    rg.refresh_volume_record(
        ROOT, is_darwin=True, run_fn=lambda argv, timeout=0: None,
        clock=_Clock(), cache={}, record_path=path,
    )
    assert rg.read_volume_record(path)["volume_uuid"] == UUID


def test_refresh_is_a_no_op_off_darwin_and_off_volumes(tmp_path):
    path = tmp_path / "volume.json"
    assert rg.refresh_volume_record(ROOT, is_darwin=False, record_path=path) is None
    assert rg.refresh_volume_record(
        "/Users/owen/Creators_Club", is_darwin=True, record_path=path
    ) is None
    assert not path.exists()


# -- local_root_is_removable (the startup demotion's gate) -------------------


def test_a_volumes_root_on_darwin_is_removable():
    assert rg.local_root_is_removable(ROOT, record={}, is_darwin=True) is True


def test_an_internal_root_is_not_removable():
    assert rg.local_root_is_removable(
        "/Users/owen/Creators_Club", record={}, is_darwin=True) is False
    assert rg.local_root_is_removable("C:\\Creators_Club", record={}, is_darwin=False) is False
    assert rg.local_root_is_removable("", record={}, is_darwin=True) is False


def test_the_volume_record_makes_a_root_removable_on_any_host():
    assert rg.local_root_is_removable(
        ROOT, record={"local_root": ROOT}, is_darwin=False) is True
    assert rg.local_root_is_removable(
        ROOT, record={"local_root": "/Volumes/OTHER/Creators_Club"}, is_darwin=False
    ) is False


# -- RootGuard: transitions --------------------------------------------------


class _Recorder:
    def __init__(self) -> None:
        self.absent: list[str] = []
        self.present = 0

    def on_absent(self, state):
        self.absent.append(state)

    def on_present(self):
        self.present += 1


def _guard(states, rec, **overrides):
    """A guard whose probe answers from `states` (popped left to right)."""
    kwargs = dict(
        local_root=ROOT,
        on_present=rec.on_present,
        on_absent=rec.on_absent,
        poll_seconds=0.01,
        is_darwin=True,
    )
    kwargs.update(overrides)
    guard = rg.RootGuard(**kwargs)
    queue = list(states)

    def _fake_probe(*args, **kw):
        return queue.pop(0) if queue else (states[-1] if states else rg.ROOT_UNKNOWN)

    return guard, _fake_probe


def test_callbacks_fire_on_transitions_only(monkeypatch):
    rec = _Recorder()
    states = [rg.ROOT_PRESENT, rg.ROOT_PRESENT, rg.ROOT_ABSENT, rg.ROOT_ABSENT,
              rg.ROOT_PRESENT]
    guard, probe = _guard(states, rec)
    monkeypatch.setattr(rg, "probe_root", probe)

    for _ in states:
        guard.probe_once()

    assert rec.present == 2       # the initial sighting, then the reconnect
    assert rec.absent == [rg.ROOT_ABSENT]
    assert guard.state == rg.ROOT_PRESENT


def test_the_first_sample_always_fires(monkeypatch):
    """A companion that starts with the drive already unplugged has to be
    told now, not at the next replug."""
    rec = _Recorder()
    guard, probe = _guard([rg.ROOT_ABSENT], rec)
    monkeypatch.setattr(rg, "probe_root", probe)
    guard.probe_once()
    assert rec.absent == [rg.ROOT_ABSENT]
    assert rec.present == 0


def test_absent_to_misplaced_fires_again(monkeypatch):
    """They need different sentences: `misplaced` is the only one the editor
    must act on (eject, delete the leftover folder, replug)."""
    rec = _Recorder()
    guard, probe = _guard([rg.ROOT_ABSENT, rg.ROOT_MISPLACED, rg.ROOT_MISPLACED], rec)
    monkeypatch.setattr(rg, "probe_root", probe)
    for _ in range(3):
        guard.probe_once()
    assert rec.absent == [rg.ROOT_ABSENT, rg.ROOT_MISPLACED]


def test_unknown_changes_nothing(monkeypatch):
    """A probe that failed is not news. Letting it become a state would pause
    and resume an editor's sync on alternate polls."""
    rec = _Recorder()
    guard, probe = _guard(
        [rg.ROOT_PRESENT, rg.ROOT_UNKNOWN, rg.ROOT_UNKNOWN, rg.ROOT_PRESENT], rec
    )
    monkeypatch.setattr(rg, "probe_root", probe)
    for _ in range(4):
        guard.probe_once()
    assert rec.present == 1
    assert rec.absent == []
    assert guard.state == rg.ROOT_PRESENT
    assert guard.present() is True


def test_a_raising_callback_never_kills_the_guard(monkeypatch):
    """The guard is the only thing that notices the drive coming BACK -- a
    callback that raises must not take that with it."""
    calls: list[str] = []

    def _boom(*args):
        calls.append("fired")
        raise RuntimeError("callback exploded")

    guard = rg.RootGuard(ROOT, on_present=_boom, on_absent=_boom, is_darwin=True)
    monkeypatch.setattr(rg, "probe_root",
                        lambda *a, **k: rg.ROOT_ABSENT if len(calls) == 0 else rg.ROOT_PRESENT)
    guard.probe_once()
    guard.probe_once()
    assert calls == ["fired", "fired"]
    assert guard.state == rg.ROOT_PRESENT


def test_present_is_true_while_unknown():
    """Read by the watcher gate and the shutdown-reason suppressor: neither
    may be switched off by a probe that has not answered yet."""
    guard = rg.RootGuard(ROOT, is_darwin=True)
    assert guard.state == rg.ROOT_UNKNOWN
    assert guard.present() is True


def test_start_polls_and_stop_ends_the_thread(monkeypatch):
    seen = threading.Event()

    def _probe(*args, **kwargs):
        seen.set()
        return rg.ROOT_PRESENT

    monkeypatch.setattr(rg, "probe_root", _probe)
    guard = rg.RootGuard(ROOT, poll_seconds=0.01, is_darwin=True)
    guard.start()
    try:
        assert seen.wait(5.0), "the guard never polled"
    finally:
        guard.stop()
    assert guard._thread is None  # noqa: SLF001


# -- COMP-GUARD-4: a probe in flight when stop() lands must not start lanes --


def test_a_probe_that_outlives_stop_does_not_fire_its_callback(monkeypatch):
    """app.shutdown stops the guard because its callbacks START LANES, and
    one firing during teardown leaves a sequencer and an rclone child running
    in a process that is exiting. stop() joins for 2.5 s and returns
    regardless -- a darwin probe running `diskutil info -plist` per mounted
    volume (10 s each) easily outlives that."""
    rec = _Recorder()
    guard = rg.RootGuard(ROOT, on_present=rec.on_present, on_absent=rec.on_absent,
                         poll_seconds=0.01, is_darwin=True)

    def _slow_probe(*args, **kwargs):
        # The stop lands WHILE this probe is running.
        guard.stop()
        return rg.ROOT_PRESENT

    monkeypatch.setattr(rg, "probe_root", _slow_probe)
    assert guard.probe_once() == rg.ROOT_PRESENT
    assert rec.present == 0, "a transition seen during teardown must not start lanes"
    # ...and the transition is not RECORDED either: a later start() must still
    # see it, or the lanes never come back after the drive does.
    assert guard.state == rg.ROOT_UNKNOWN


def test_fire_is_gated_on_the_stop_event_too(monkeypatch):
    rec = _Recorder()
    guard = rg.RootGuard(ROOT, on_present=rec.on_present, on_absent=rec.on_absent,
                         is_darwin=True)
    guard.stop()
    guard._fire(rg.ROOT_PRESENT)  # noqa: SLF001
    guard._fire(rg.ROOT_ABSENT)  # noqa: SLF001
    assert rec.present == 0 and rec.absent == []


def test_stop_keeps_a_thread_that_did_not_finish(monkeypatch):
    """SYNC-15's precedent (_WindowsShutdownGuard.stop): dropping the
    reference let a later start() -- which clears _stop_event -- spawn a
    SECOND poller beside one that never saw the set."""
    release = threading.Event()
    started = threading.Event()

    def _wedged_probe(*args, **kwargs):
        started.set()
        release.wait(10.0)
        return rg.ROOT_PRESENT

    monkeypatch.setattr(rg, "probe_root", _wedged_probe)
    guard = rg.RootGuard(ROOT, poll_seconds=0.01, is_darwin=True)
    guard.start()
    try:
        assert started.wait(5.0), "the guard never polled"
        first = guard._thread  # noqa: SLF001
        guard.stop()           # joins 2.0 s, times out
        assert guard._thread is first, "the wedged thread must be kept, not dropped"  # noqa: SLF001

        guard.start()          # must NOT spawn a rival poller
        assert guard._thread is first  # noqa: SLF001
    finally:
        release.set()
        guard.stop()


def test_a_nonsense_poll_interval_falls_back():
    guard = rg.RootGuard(ROOT, poll_seconds="soon")
    assert guard._poll_seconds == rg.POLL_SECONDS  # noqa: SLF001


def test_the_module_logs_under_the_ccsync_logger():
    """setup_logging() only ever attaches handlers to "ccsync" -- a record
    emitted under "ccsync_companion.root_guard" is swallowed silently in the
    windowed build (see shutdown_guard.py's note)."""
    assert rg.log.name == "ccsync.root_guard"


# -- item 16: macOS is blocking us, as opposed to the drive being out -------
#
# The companion is ad-hoc signed, so its Full Disk Access identity is a hash
# of the binary and every self-upgrade presents as a different program
# needing a fresh grant. On a Mac whose root is an external volume the tree
# then becomes unreadable with NO error naming the cause -- the drive is
# plugged in, the folder is right there, and every read comes back EPERM.
# Exercised from Windows through the same injected seams as everything above.


def _denied(*paths):
    """A listdir that refuses `paths` the way macOS does and answers the rest."""
    def _listdir(path):
        if str(path) in paths:
            raise PermissionError(13, "Operation not permitted")
        return []
    return _listdir


def _blocked(**overrides):
    kwargs = dict(
        local_root=ROOT,
        is_darwin=True,
        listdir_fn=_denied(ROOT),
        ismount_fn=lambda p: True,
    )
    kwargs.update(overrides)
    return rg.access_is_blocked(**kwargs)


def test_a_denied_root_on_a_mounted_volume_is_macos_blocking_us():
    assert _blocked() is True


def test_a_denied_volume_counts_even_when_the_root_reports_missing():
    """An unreadable parent hides its children: the root inside it can come
    back ENOENT while the volume itself is the thing being refused."""
    def _listdir(path):
        if path == MOUNT:
            raise PermissionError(1, "Operation not permitted")
        raise FileNotFoundError(2, "No such file or directory")

    assert _blocked(listdir_fn=_listdir) is True


def test_an_unplugged_drive_is_not_a_permissions_problem():
    """probe_root already calls this `absent` and says the right thing about
    it. Telling the editor to re-grant Full Disk Access instead would send
    them into System Settings over a drive that is in their bag."""
    def _listdir(path):
        raise FileNotFoundError(2, "No such file or directory")

    assert _blocked(listdir_fn=_listdir) is False


def test_a_denied_read_on_an_UNMOUNTED_volume_is_not_reported():
    """The ghost-directory case: something at /Volumes/T7 on the boot disk
    that we cannot read. The drive is still out, and that is the story."""
    assert _blocked(ismount_fn=lambda p: False) is False


def test_a_readable_tree_is_not_blocked():
    assert _blocked(listdir_fn=lambda p: ["Projects"]) is False


def test_windows_never_reports_a_block():
    """No-op off darwin, and it must not even touch the disk to say so."""
    def _never(path):
        raise AssertionError("the disk was read on a non-darwin host")

    assert rg.access_is_blocked(ROOT, is_darwin=False, listdir_fn=_never) is False


def test_a_blank_local_root_is_not_a_block():
    assert rg.access_is_blocked("", is_darwin=True, listdir_fn=_denied("")) is False


def test_an_internal_disk_root_still_reports_a_denied_read():
    """There is no volume to confirm for ~/Creators_Club, and TCC covers
    Desktop/Documents/Downloads too."""
    root = "/Users/editor1/Creators_Club"
    assert rg.access_is_blocked(
        root, is_darwin=True, listdir_fn=_denied(root)) is True


def test_a_denied_read_reported_as_a_bare_oserror_still_counts():
    """Not every filesystem raises the PermissionError subclass; some hand
    back an OSError carrying EACCES/EPERM."""
    import errno

    def _listdir(path):
        exc = OSError("nope")
        exc.errno = errno.EACCES
        raise exc

    assert _blocked(listdir_fn=_listdir) is True


def test_an_exotic_failure_is_not_called_a_permissions_problem():
    def _listdir(path):
        raise RuntimeError("something else entirely")

    assert _blocked(listdir_fn=_listdir) is False


def test_a_raising_ismount_never_escapes():
    def _boom(path):
        raise RuntimeError("no")

    assert _blocked(ismount_fn=_boom) is False
