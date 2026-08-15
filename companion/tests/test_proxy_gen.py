"""proxy_gen tests: the state machine, with no ffmpeg and no threads.

Every collaborator that touches the world is a constructor seam, so these
tests drive the worker one tick and one clip at a time -- `tick()`,
`scan_once()` and `encode_once()` exist for exactly this. What is NOT faked
is the filesystem: the re-verify, the first-writer-wins publish and the
partial handling are the parts that must agree with a real directory, so they
run against real tmp_path trees in test_proxy_scan.py's style.

The property under most of this file is "never under the user's hands":
idle.py's None (cannot tell) must never become an encode, and a user coming
back mid-encode must leave nothing behind.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

from ccsync_companion import proxy_gen, proxy_scan

# Comfortably older than the 120 s settle window.
SETTLED = 3600.0


class _Idle:
    """An idle probe that answers whatever the test says, including None."""

    def __init__(self, seconds=None):
        self.seconds = seconds

    def seconds_idle(self):
        return self.seconds


class _Raiser:
    def seconds_idle(self):
        raise RuntimeError("no idle counter here")


class _FakeFfmpeg:
    """Stands in for proxy_gen._run_ffmpeg -- the ONE seam every subprocess
    goes through (the encode and the verification decode alike).

    It writes the output file itself, because the publish step re-checks the
    disk and os.replace()s a real file; a fake that returned rc 0 without
    producing anything would test a code path that cannot exist.
    """

    def __init__(self):
        self.calls: list[list[str]] = []
        self.stop_reason = None        # what should_stop() should be made to say
        self.encode_returncode = 0
        self.encode_stderr = ""
        self.verify_stderr = ""
        self.timed_out = False
        self.nvenc_fails = False       # first (GPU) attempt fails, CPU one works
        self.written_bytes = b"proxy"

    @staticmethod
    def _is_verify(cmd) -> bool:
        return "null" in cmd and "-f" in cmd

    def __call__(self, cmd, should_stop, ceiling):
        self.calls.append(list(cmd))
        result = {"returncode": 0, "stderr": "", "interrupted": None, "timed_out": False}
        # The real runner polls should_stop() every 2 s; the fake asks once,
        # which is enough to exercise every caller of the answer.
        reason = should_stop()
        if reason:
            # A killed ffmpeg has already written SOME bytes -- that partial
            # is exactly what the caller has to clean up, so the fake leaves
            # one behind rather than testing an empty directory.
            if not self._is_verify(cmd):
                with open(cmd[-1], "wb") as handle:
                    handle.write(b"half an encode")
            result["interrupted"] = reason
            return result
        if self.timed_out and not self._is_verify(cmd):
            result["timed_out"] = True
            return result
        if self._is_verify(cmd):
            result["stderr"] = self.verify_stderr
            return result
        if self.nvenc_fails and "hevc_nvenc" in cmd:
            result["returncode"] = 1
            result["stderr"] = "No capable devices found"
            return result
        result["returncode"] = self.encode_returncode
        result["stderr"] = self.encode_stderr
        if result["returncode"] == 0:
            with open(cmd[-1], "wb") as handle:
                handle.write(self.written_bytes)
        return result


def _probe(duration=60.0, timecode="01:00:00:00"):
    def _fn(ffmpeg_path, path):
        return {
            "duration_s": duration, "fps": 25.0, "width": 3840, "height": 2160,
            "codec": "hevc", "has_audio": True, "audio_channels": 2,
            "timecode": timecode,
        }
    return _fn


def _cfg(tmp_path, **overrides):
    cfg = {
        "local_root": str(tmp_path),
        "proxy_notify_enabled": True,
        "proxy_gen_enabled": True,
        "ffmpeg_path": "ffmpeg",
        "proxy_gen_idle_seconds": 300,
        "proxy_gen_min_age_seconds": 120,
        "proxy_scan_interval": 900,
    }
    cfg.update(overrides)
    return cfg


def _make_gen(tmp_path, cfg=None, **kwargs):
    kwargs.setdefault("idle_probe", _Idle(9999))
    kwargs.setdefault("probe_fn", _probe())
    kwargs.setdefault("available_fn", lambda path: (True, "/usr/bin/ffmpeg"))
    kwargs.setdefault("encoders_fn", lambda path: frozenset({"libx265", "libx264"}))
    kwargs.setdefault("scan_fn", lambda *a, **k: {
        "projects": {}, "totals": proxy_scan._empty_totals()})
    kwargs.setdefault("encode_fn", _FakeFfmpeg())
    return proxy_gen.ProxyGenerator(cfg or _cfg(tmp_path), tmp_path / "state", **kwargs)


def _original(tmp_path, name="A001.mp4", age=SETTLED, size=1000):
    """A settled original inside a project, aged past the settle window."""
    path = tmp_path / "Projects" / "2026" / "FF5" / "Nuclear" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    stamp = time.time() - age
    os.utime(path, (stamp, stamp))
    return path


def _clip(path, kind=proxy_scan.KIND_OWN):
    stat = os.stat(path)
    return {"path": str(path), "kind": kind,
            "size": stat.st_size, "mtime": stat.st_mtime}


def _scan_result(clips, rel="2026/FF5/Nuclear", **totals):
    gap = proxy_scan.empty_gap()
    gap["clips"] = list(clips)
    gap["missing"] = totals.get("missing", len(clips))
    gap["braw"] = totals.get("braw", 0)
    gap["needs_resolve"] = totals.get("needs_resolve", gap["braw"])
    gap[proxy_scan.KIND_OWN] = totals.get("own", len(clips))
    result_totals = proxy_scan._empty_totals()
    for key in ("missing", "braw", "needs_resolve", proxy_scan.KIND_OWN,
                proxy_scan.KIND_PREVIEW):
        result_totals[key] = gap[key]
    result_totals["queued"] = len(clips)
    result_totals["projects"] = 1
    return {"projects": {rel: gap}, "totals": result_totals}


# -- the gate, in order -------------------------------------------------------


def test_the_gate_says_disabled_when_generation_is_off(tmp_path):
    gen = _make_gen(tmp_path, _cfg(tmp_path, proxy_gen_enabled=False))
    assert gen._gate() == proxy_gen.STATE_DISABLED


def test_the_gate_says_drive_absent_before_anything_else(tmp_path):
    """An unplugged SSD outranks every other answer: there is nothing to
    scan and nothing to encode, and saying "paused" would send the editor
    looking at the wrong menu item."""
    gen = _make_gen(tmp_path, root_present_fn=lambda: False, paused_fn=lambda: True)
    assert gen._gate() == proxy_gen.STATE_DRIVE_ABSENT


def test_pause_gates_encoding(tmp_path):
    gen = _make_gen(tmp_path, paused_fn=lambda: True)
    assert gen._gate() == proxy_gen.STATE_PAUSED


def test_config_problems_gate_encoding(tmp_path):
    gen = _make_gen(tmp_path, blocked_fn=lambda: True)
    assert gen._gate() == proxy_gen.STATE_MISCONFIGURED


def test_a_missing_ffmpeg_is_notifier_only_and_warns_once(tmp_path, caplog):
    gen = _make_gen(tmp_path, available_fn=lambda path: (False, "ffmpeg not found on PATH"))
    with caplog.at_level("WARNING", logger="ccsync.proxy_gen"):
        assert gen._gate() == proxy_gen.STATE_NO_FFMPEG
        assert gen._gate() == proxy_gen.STATE_NO_FFMPEG
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1, "a missing ffmpeg is the expected state, not a log storm"
    assert "still TELL you" in warnings[0].getMessage()


def test_an_empty_queue_is_nothing_to_do_not_user_active(tmp_path):
    """Order matters: with nothing queued the answer must not depend on
    whether anyone is at the keyboard."""
    gen = _make_gen(tmp_path, idle_probe=_Idle(0))
    assert gen._gate() == proxy_gen.STATE_NOTHING_TO_DO


def test_a_user_at_the_keyboard_stops_encoding(tmp_path):
    gen = _make_gen(tmp_path, idle_probe=_Idle(10))
    gen._queue = [{"path": "x.mp4"}]
    assert gen._gate() == proxy_gen.STATE_USER_ACTIVE


def test_an_unknowable_idle_time_is_never_idle(tmp_path):
    """idle.py's whole contract: None means cannot tell means NOT idle."""
    gen = _make_gen(tmp_path, idle_probe=_Idle(None))
    gen._queue = [{"path": "x.mp4"}]
    assert gen._gate() == proxy_gen.STATE_USER_ACTIVE


def test_an_idle_probe_that_raises_is_also_never_idle(tmp_path):
    gen = _make_gen(tmp_path, idle_probe=_Raiser())
    gen._queue = [{"path": "x.mp4"}]
    assert gen._gate() == proxy_gen.STATE_USER_ACTIVE


def test_idle_past_the_threshold_runs(tmp_path):
    gen = _make_gen(tmp_path, idle_probe=_Idle(300))
    gen._queue = [{"path": "x.mp4"}]
    assert gen._gate() == proxy_gen.STATE_RUNNING


def test_a_forced_run_skips_the_idle_gate_only(tmp_path):
    gen = _make_gen(tmp_path, idle_probe=_Idle(0), paused_fn=lambda: False)
    gen._queue = [{"path": "x.mp4"}]
    gen.request_run()
    assert gen._gate() == proxy_gen.STATE_RUNNING
    # ...but not the gates above it.
    gen._paused_fn = lambda: True
    assert gen._gate() == proxy_gen.STATE_PAUSED


def test_the_resolve_gate_is_opt_in_and_fails_closed(tmp_path):
    """An unattended render is invisible to any idle probe, so a check that
    cannot answer must not be read as "the GPU is free"."""
    cfg = _cfg(tmp_path, proxy_gen_skip_while_resolve_running=True)
    gen = _make_gen(tmp_path, cfg, resolve_running_fn=lambda: True)
    gen._queue = [{"path": "x.mp4"}]
    assert gen._gate() == proxy_gen.STATE_RESOLVE_OPEN

    def _boom():
        raise RuntimeError("tasklist is unavailable")

    gen = _make_gen(tmp_path, cfg, resolve_running_fn=_boom)
    gen._queue = [{"path": "x.mp4"}]
    assert gen._gate() == proxy_gen.STATE_RESOLVE_OPEN

    # Off by default: the same running Resolve does not gate anything.
    gen = _make_gen(tmp_path, resolve_running_fn=lambda: True)
    gen._queue = [{"path": "x.mp4"}]
    assert gen._gate() == proxy_gen.STATE_RUNNING


# -- scanning + the queue -----------------------------------------------------


def test_scan_builds_one_newest_first_queue_across_projects(tmp_path):
    old = {"path": "old.mp4", "kind": "own", "size": 1, "mtime": 100.0}
    new = {"path": "new.mp4", "kind": "own", "size": 1, "mtime": 900.0}
    result = {
        "projects": {
            "2026/A/One": {**proxy_scan.empty_gap(), "clips": [old], "missing": 1, "own": 1},
            "2026/A/Two": {**proxy_scan.empty_gap(), "clips": [new], "missing": 1, "own": 1},
        },
        "totals": {**proxy_scan._empty_totals(), "missing": 2, "own": 2, "projects": 2},
    }
    gen = _make_gen(tmp_path, scan_fn=lambda *a, **k: result)
    gen.scan_once()
    assert [c["path"] for c in gen._queue] == ["new.mp4", "old.mp4"]
    assert [c["project"] for c in gen._queue] == ["2026/A/Two", "2026/A/One"]
    assert gen.gap()["missing"] == 2
    assert gen.gap()["left"] == 2


def test_braw_is_counted_but_never_queued(tmp_path):
    """ffmpeg cannot decode BRAW at any quality, so it is reported ("run the
    Blackmagic Proxy Generator") and never attempted."""
    result = _scan_result([], missing=4, braw=4, needs_resolve=4, own=0)
    gen = _make_gen(tmp_path, scan_fn=lambda *a, **k: result)
    gen.scan_once()
    assert gen.gap()["braw"] == 4
    assert gen.gap()["missing"] == 4
    assert gen._queue == []
    assert gen._gate() == proxy_gen.STATE_NOTHING_TO_DO


def test_a_scan_that_blows_up_leaves_the_worker_alive(tmp_path):
    def _boom(*a, **k):
        raise RuntimeError("the tree went away mid-walk")

    gen = _make_gen(tmp_path, scan_fn=_boom)
    gen.scan_once()
    assert gen.gap()["missing"] == 0
    assert gen._scan_due() is False, "a failed scan still costs a cadence slot"


def test_the_scan_cadence_is_forced_on_start_and_by_a_run_request(tmp_path):
    clock = {"now": 0.0}
    gen = _make_gen(tmp_path, clock=lambda: clock["now"])
    assert gen._scan_due() is True          # never scanned
    gen.scan_once()
    assert gen._scan_due() is False
    clock["now"] = 899.0
    assert gen._scan_due() is False
    clock["now"] = 901.0
    assert gen._scan_due() is True

    clock["now"] = 902.0
    gen.scan_once()
    assert gen._scan_due() is False
    gen.request_run()
    assert gen._scan_due() is True, "\"make them now\" must not wait for the cadence"


def test_the_drive_coming_back_forces_a_rescan(tmp_path):
    present = {"value": False}
    scans = {"count": 0}

    def _scan(*a, **k):
        scans["count"] += 1
        return {"projects": {}, "totals": proxy_scan._empty_totals()}

    gen = _make_gen(tmp_path, root_present_fn=lambda: present["value"], scan_fn=_scan)
    gen.tick()
    assert scans["count"] == 0, "nothing is scannable with the tree unplugged"
    present["value"] = True
    gen.tick()
    assert scans["count"] == 1


# -- one clip, end to end -----------------------------------------------------


def test_a_clip_is_encoded_verified_and_published(tmp_path):
    src = _original(tmp_path)
    ffmpeg = _FakeFfmpeg()
    gen = _make_gen(tmp_path, encode_fn=ffmpeg)
    gen._queue = [_clip(src)]

    assert gen.encode_once() == proxy_gen.RESULT_DONE

    final = src.parent / "Proxy" / "A001.mp4"
    assert final.is_file()
    assert not (src.parent / "Proxy" / "A001.mp4.partial").exists()
    assert gen.gap()["generated"] == 1
    # The encode wrote the .partial, never the final name: a half-written file
    # under a final name is one lane B would hand to the whole fleet.
    encode_cmd = ffmpeg.calls[0]
    assert encode_cmd[-1].endswith(".mp4.partial")
    # ...and the source timecode rode along (LinkProxyMedia refuses without it).
    assert "-timecode" in encode_cmd and "01:00:00:00" in encode_cmd
    # The verification decode really ran, on the partial.
    assert any(_FakeFfmpeg._is_verify(cmd) for cmd in ffmpeg.calls)


def test_a_youtube_download_gets_the_broll_preview_spec(tmp_path):
    src = _original(tmp_path, name="downloads_clip.mp4")
    ffmpeg = _FakeFfmpeg()
    gen = _make_gen(tmp_path, encode_fn=ffmpeg)
    gen._queue = [_clip(src, kind=proxy_scan.KIND_PREVIEW)]

    assert gen.encode_once() == proxy_gen.RESULT_DONE
    cmd = ffmpeg.calls[0]
    assert "libx264" in cmd and "540" in " ".join(cmd)
    # No metadata/timecode carrying on this tier -- the output has to stay
    # interchangeable with one the b-roll indexer produced.
    assert "-timecode" not in cmd and "-map_metadata" not in cmd


def test_a_clip_whose_proxy_arrived_meanwhile_is_dropped_silently(tmp_path):
    """Lane B delivering the proxy while the clip sat in the queue is the
    system working. It must not encode, and must not be counted as an error."""
    src = _original(tmp_path)
    (src.parent / "Proxy").mkdir()
    (src.parent / "Proxy" / "A001.mov").write_bytes(b"delivered by lane B")
    ffmpeg = _FakeFfmpeg()
    gen = _make_gen(tmp_path, encode_fn=ffmpeg)
    gen._queue = [_clip(src)]

    assert gen.encode_once() == proxy_gen.RESULT_SKIPPED
    assert ffmpeg.calls == []
    assert gen.gap()["failed"] == 0


def test_a_clip_bpg_is_working_on_is_never_touched(tmp_path):
    """Two encoders writing one stem is the two-writers race this whole
    design avoids -- BPG's `.<stem>.tmp`/`.lock` sidecars say it owns this."""
    src = _original(tmp_path)
    (src.parent / "Proxy").mkdir()
    (src.parent / "Proxy" / ".A001.tmp").write_bytes(b"2.3 GB of in-flight render")
    ffmpeg = _FakeFfmpeg()
    gen = _make_gen(tmp_path, encode_fn=ffmpeg)
    gen._queue = [_clip(src)]

    assert gen.encode_once() == proxy_gen.RESULT_SKIPPED
    assert ffmpeg.calls == []


def test_a_vanished_or_still_settling_original_is_dropped(tmp_path):
    src = _original(tmp_path)
    clip = _clip(src)
    ffmpeg = _FakeFfmpeg()
    gen = _make_gen(tmp_path, encode_fn=ffmpeg)

    src.unlink()
    assert gen.encode_once(clip) == proxy_gen.RESULT_SKIPPED

    # Re-copied a moment ago: inside the settle window again, so not yet ours.
    fresh = _original(tmp_path, age=1.0)
    assert gen.encode_once(_clip(fresh)) == proxy_gen.RESULT_SKIPPED
    assert ffmpeg.calls == []


def test_first_writer_wins_at_publish_time(tmp_path):
    """The proxy can appear DURING the encode -- lane B, or BPG finishing.
    Overwriting it would replace a file Resolve may have open with one we
    just made, so ours is thrown away instead."""
    src = _original(tmp_path)
    ffmpeg = _FakeFfmpeg()
    winner = src.parent / "Proxy" / "A001.mov"

    class _RacingFfmpeg(_FakeFfmpeg):
        def __call__(self, cmd, should_stop, ceiling):
            result = super().__call__(cmd, should_stop, ceiling)
            if not self._is_verify(cmd):
                winner.write_bytes(b"somebody else got there first")
            return result

    ffmpeg = _RacingFfmpeg()
    gen = _make_gen(tmp_path, encode_fn=ffmpeg)
    gen._queue = [_clip(src)]

    assert gen.encode_once() == proxy_gen.RESULT_DONE
    assert winner.read_bytes() == b"somebody else got there first"
    assert not (src.parent / "Proxy" / "A001.mp4").exists()
    assert not (src.parent / "Proxy" / "A001.mp4.partial").exists()


def test_a_publish_that_hits_a_sharing_violation_leaves_the_partial(tmp_path, monkeypatch):
    """Resolve holds proxies open without share-delete (GOTCHAS:354-357), so
    on the base rig os.replace can simply be refused. The half-made file is
    excluded from every lane, so leaving it costs disk and nothing else."""
    src = _original(tmp_path)
    gen = _make_gen(tmp_path)
    gen._queue = [_clip(src)]

    def _refuse(a, b):
        raise PermissionError(32, "The process cannot access the file")

    monkeypatch.setattr(os, "replace", _refuse)
    assert gen.encode_once() == proxy_gen.RESULT_FAILED
    assert (src.parent / "Proxy" / "A001.mp4.partial").is_file()
    assert gen.gap()["failed"] == 1


# -- stopping ------------------------------------------------------------------


def test_the_user_coming_back_kills_the_encode_and_requeues_the_front(tmp_path):
    """The feature's central promise. Nothing left behind, and the clip is
    first in line next time -- dropping it to the back would mean a machine
    whose user keeps returning never finishes the same first clip."""
    src = _original(tmp_path)
    other = {"path": "later.mp4", "kind": "own", "size": 1, "mtime": 1.0}
    idle = _Idle(9999)
    ffmpeg = _FakeFfmpeg()
    gen = _make_gen(tmp_path, encode_fn=ffmpeg, idle_probe=idle)
    gen._queue = [_clip(src), other]

    class _ReturningUser(_FakeFfmpeg):
        def __call__(self, cmd, should_stop, ceiling):
            idle.seconds = 3  # the mouse moved
            return super().__call__(cmd, should_stop, ceiling)

    gen._encode_fn = _ReturningUser()
    assert gen.encode_once() == proxy_gen.RESULT_INTERRUPTED
    assert not (src.parent / "Proxy" / "A001.mp4.partial").exists()
    assert not (src.parent / "Proxy" / "A001.mp4").exists()
    assert gen._queue[0]["path"] == str(src)
    assert len(gen._queue) == 2


def test_an_idle_probe_that_goes_dark_mid_encode_also_stops(tmp_path):
    src = _original(tmp_path)
    idle = _Idle(9999)
    gen = _make_gen(tmp_path, idle_probe=idle)

    class _GoesDark(_FakeFfmpeg):
        def __call__(self, cmd, should_stop, ceiling):
            idle.seconds = None  # cannot tell any more
            return super().__call__(cmd, should_stop, ceiling)

    gen._encode_fn = _GoesDark()
    gen._queue = [_clip(src)]
    assert gen.encode_once() == proxy_gen.RESULT_INTERRUPTED


def test_a_forced_run_keeps_encoding_while_the_user_works(tmp_path):
    """"Don't wait until I'm away" means exactly that -- the mid-encode kill
    poll must not undo the button the editor just pressed."""
    src = _original(tmp_path)
    gen = _make_gen(tmp_path, idle_probe=_Idle(0))
    gen._queue = [_clip(src)]
    gen.request_run()
    assert gen.encode_once() == proxy_gen.RESULT_DONE


def test_shutdown_stops_the_encode(tmp_path):
    src = _original(tmp_path)
    gen = _make_gen(tmp_path)
    gen._queue = [_clip(src)]
    gen.stop()
    assert gen.encode_once() == proxy_gen.RESULT_INTERRUPTED
    assert not (src.parent / "Proxy" / "A001.mp4.partial").exists()


def test_pausing_stops_the_encode_in_flight(tmp_path):
    """Pause means "stop moving bytes". An encode that runs to completion
    twenty minutes after the editor paused is the thing they pressed it to
    stop -- the scan and the notification keep going, which is the half
    pause deliberately does not gate."""
    src = _original(tmp_path)
    paused = {"value": False}
    gen = _make_gen(tmp_path, paused_fn=lambda: paused["value"])

    class _PausesMidway(_FakeFfmpeg):
        def __call__(self, cmd, should_stop, ceiling):
            paused["value"] = True
            return super().__call__(cmd, should_stop, ceiling)

    gen._encode_fn = _PausesMidway()
    gen._queue = [_clip(src)]
    assert gen.encode_once() == proxy_gen.RESULT_INTERRUPTED


def test_cancel_run_empties_the_queue_for_this_cycle_only(tmp_path):
    src = _original(tmp_path)
    gen = _make_gen(tmp_path)
    gen._queue = [_clip(src), {"path": "later.mp4", "kind": "own", "size": 1, "mtime": 1.0}]
    gen.cancel_run()
    state = gen._drain_queue()
    assert state == proxy_gen.STATE_NOTHING_TO_DO
    assert gen._queue == []
    assert not gen._cancel.is_set()
    # Not a disable: the next scan puts the work straight back.
    gen._scan_fn = lambda *a, **k: _scan_result([_clip(src)])
    gen.scan_once()
    assert len(gen._queue) == 1


def test_stop_while_an_encode_runs_still_kills_it(tmp_path):
    """The half of "Stop making proxies" that must not change: a click while
    ffmpeg is running kills the child and leaves no partial behind."""
    src = _original(tmp_path)
    gen = _make_gen(tmp_path)

    class _CancelsMidway(_FakeFfmpeg):
        def __call__(self, cmd, should_stop, ceiling):
            gen.cancel_run()
            return super().__call__(cmd, should_stop, ceiling)

    gen._encode_fn = _CancelsMidway()
    gen._queue = [_clip(src)]

    assert gen.encode_once() == proxy_gen.RESULT_INTERRUPTED
    assert gen._cancel.is_set(), "an encode was in flight -- the flag is the kill"
    assert not os.path.exists(proxy_scan.partial_path(str(src)))


def test_stop_with_nothing_encoding_does_not_arm_the_next_drain(tmp_path):
    """COMP-MEDIA-7: `_cancel` is only ever cleared by a drain that RAN, and
    the tray shows "Stop making proxies" from a snapshot -- so a click after
    rule 1 has already ended the drain (i.e. the moment the editor touches the
    keyboard) used to latch the flag until that night's drain, which then died
    on its first clip and dropped the whole freshly scanned queue."""
    src = _original(tmp_path)
    gen = _make_gen(tmp_path)
    gen._queue = [_clip(src), {"path": "later.mp4", "kind": "own",
                               "size": 1, "mtime": 1.0}]

    gen.cancel_run()

    assert not gen._cancel.is_set()
    assert gen._queue == [], "the cycle's queue is still dropped"

    # That night: the scan refills and the drain does the work.
    gen._scan_fn = lambda *a, **k: _scan_result([_clip(src)])
    gen.scan_once()
    assert gen._drain_queue() == proxy_gen.STATE_NOTHING_TO_DO
    assert gen.gap()["generated"] == 1
    assert gen.gap()["failed"] == 0


def test_a_stuck_encode_is_killed_and_counted(tmp_path):
    src = _original(tmp_path)
    ffmpeg = _FakeFfmpeg()
    ffmpeg.timed_out = True
    gen = _make_gen(tmp_path, encode_fn=ffmpeg)
    gen._queue = [_clip(src)]

    assert gen.encode_once() == proxy_gen.RESULT_FAILED
    assert not (src.parent / "Proxy" / "A001.mp4.partial").exists()
    assert gen.gap()["failed"] == 1


def test_the_stuck_ceiling_is_a_floor_plus_a_multiple_of_the_duration(tmp_path):
    """A 30 s clip gets the 30-minute floor; a 2-hour one gets 60x its own
    length, because "slow" and "wedged" are different for a long source."""
    src = _original(tmp_path)
    ceilings: list[float] = []

    def _record(cmd, should_stop, ceiling):
        ceilings.append(ceiling)
        return {"returncode": 1, "stderr": "", "interrupted": None, "timed_out": False}

    gen = _make_gen(tmp_path, encode_fn=_record, probe_fn=_probe(duration=30.0))
    gen.encode_once(_clip(src))
    assert ceilings[0] == proxy_gen.STUCK_FLOOR_SECONDS

    ceilings.clear()
    gen = _make_gen(tmp_path, encode_fn=_record, probe_fn=_probe(duration=7200.0))
    gen.encode_once(_clip(src))
    assert ceilings[0] == 7200.0 * proxy_gen.STUCK_DURATION_FACTOR


# -- NVENC, verification, error memory ----------------------------------------


def test_a_failed_gpu_encode_retries_once_on_the_cpu(tmp_path):
    """NVENC being LISTED is not proof it will run (no GPU, sessions taken,
    a driver that fell over). One retry, never a loop."""
    src = _original(tmp_path)
    ffmpeg = _FakeFfmpeg()
    ffmpeg.nvenc_fails = True
    gen = _make_gen(
        tmp_path, encode_fn=ffmpeg,
        encoders_fn=lambda path: frozenset({"hevc_nvenc", "libx265"}),
    )
    gen.scan_once()  # this is what detects the encoders
    assert gen._nvenc is True
    gen._queue = [_clip(src)]

    assert gen.encode_once() == proxy_gen.RESULT_DONE
    encodes = [c for c in ffmpeg.calls if not _FakeFfmpeg._is_verify(c)]
    assert len(encodes) == 2
    assert "hevc_nvenc" in encodes[0] and "libx265" in encodes[1]
    assert gen.gap()["failed"] == 0, "a retry that worked is not a failure"


def test_a_cpu_encode_that_fails_is_not_retried_again(tmp_path):
    src = _original(tmp_path)
    ffmpeg = _FakeFfmpeg()
    ffmpeg.encode_returncode = 1
    gen = _make_gen(tmp_path, encode_fn=ffmpeg)
    gen._queue = [_clip(src)]

    assert gen.encode_once() == proxy_gen.RESULT_FAILED
    encodes = [c for c in ffmpeg.calls if not _FakeFfmpeg._is_verify(c)]
    assert len(encodes) == 1


def test_a_proxy_that_does_not_decode_is_never_published(tmp_path):
    """Measured on the b-roll archive: 17% of proxies made under concurrent
    NVENC decoded with "Invalid NAL unit size" while reporting the right
    duration and resolution. Only a real decode catches that."""
    src = _original(tmp_path)
    ffmpeg = _FakeFfmpeg()
    ffmpeg.verify_stderr = "[hevc @ 0x1] Invalid NAL unit size (1 > 0).\n"
    gen = _make_gen(tmp_path, encode_fn=ffmpeg)
    gen._queue = [_clip(src)]

    assert gen.encode_once() == proxy_gen.RESULT_FAILED
    assert not (src.parent / "Proxy" / "A001.mp4").exists()
    assert not (src.parent / "Proxy" / "A001.mp4.partial").exists()


def test_a_proxy_shorter_than_its_source_is_never_published(tmp_path):
    """A decode that stops cleanly after 4 of 60 seconds reports no errors
    at all -- the duration check is the other half of verification."""
    src = _original(tmp_path)
    durations = iter([60.0, 4.0])  # source, then the finished proxy

    def _probe_fn(ffmpeg_path, path):
        return {"duration_s": next(durations), "timecode": None}

    gen = _make_gen(tmp_path, probe_fn=_probe_fn)
    gen._queue = [_clip(src)]
    assert gen.encode_once() == proxy_gen.RESULT_FAILED
    assert not (src.parent / "Proxy" / "A001.mp4").exists()


def test_a_proxy_a_hair_short_is_fine(tmp_path):
    """The last GOP and a trailing audio frame legitimately round 60.00 s
    down -- 0.97, not 1.0, or every good proxy would be condemned."""
    src = _original(tmp_path)
    durations = iter([60.0, 59.5])

    def _probe_fn(ffmpeg_path, path):
        return {"duration_s": next(durations), "timecode": None}

    gen = _make_gen(tmp_path, probe_fn=_probe_fn)
    gen._queue = [_clip(src)]
    assert gen.encode_once() == proxy_gen.RESULT_DONE


def test_unreadable_media_is_counted_not_crashed_on(tmp_path):
    src = _original(tmp_path)

    def _boom(ffmpeg_path, path):
        raise proxy_gen.ffmpeg_tools.UnreadableMediaError("moov atom not found")

    gen = _make_gen(tmp_path, probe_fn=_boom)
    gen._queue = [_clip(src)]
    assert gen.encode_once() == proxy_gen.RESULT_FAILED
    assert gen.gap()["failed"] == 1


def test_three_failures_take_a_clip_out_of_the_queue(tmp_path):
    src = _original(tmp_path)
    ffmpeg = _FakeFfmpeg()
    ffmpeg.encode_returncode = 1
    gen = _make_gen(tmp_path, encode_fn=ffmpeg)
    clip = _clip(src)

    for _ in range(3):
        assert gen.encode_once(dict(clip)) == proxy_gen.RESULT_FAILED
    # The cap is reached: further attempts do not even reach ffmpeg...
    before = len(ffmpeg.calls)
    assert gen.encode_once(dict(clip)) == proxy_gen.RESULT_SKIPPED
    assert len(ffmpeg.calls) == before
    # ...and the next scan does not put it back in the queue.
    gen._scan_fn = lambda *a, **k: _scan_result([dict(clip)])
    gen.scan_once()
    assert gen._queue == []


def test_the_verification_decode_gets_the_encodes_ceiling(tmp_path):
    """MED-2: it used to be a flat 30 minutes while the encode's scaled with
    the source. A multi-hour clip encoded fine and then blew that ceiling
    decoding its own ~20 GB HEVC back off the share -- the partial discarded,
    the whole encode thrown away, and three passes later the clip capped for
    good with the log blaming the file."""
    src = _original(tmp_path)
    seen: list[tuple[bool, float]] = []

    class _Recording(_FakeFfmpeg):
        def __call__(self, cmd, should_stop, ceiling):
            seen.append((self._is_verify(cmd), ceiling))
            return super().__call__(cmd, should_stop, ceiling)

    gen = _make_gen(tmp_path, encode_fn=_Recording(), probe_fn=_probe(duration=7200.0))
    assert gen.encode_once(_clip(src)) == proxy_gen.RESULT_DONE

    expected = 7200.0 * proxy_gen.STUCK_DURATION_FACTOR
    assert seen == [(False, expected), (True, expected)]


def test_a_short_clips_verification_still_gets_the_floor(tmp_path):
    src = _original(tmp_path)
    seen: list[tuple[bool, float]] = []

    class _Recording(_FakeFfmpeg):
        def __call__(self, cmd, should_stop, ceiling):
            seen.append((self._is_verify(cmd), ceiling))
            return super().__call__(cmd, should_stop, ceiling)

    gen = _make_gen(tmp_path, encode_fn=_Recording(), probe_fn=_probe(duration=30.0))
    assert gen.encode_once(_clip(src)) == proxy_gen.RESULT_DONE
    assert seen == [(False, proxy_gen.STUCK_FLOOR_SECONDS),
                    (True, proxy_gen.STUCK_FLOOR_SECONDS)]


def test_make_them_now_forgets_the_failure_cap(tmp_path):
    """MED-6: scan_once filters capped clips OUT of the queue, so after the
    0.6.1 muxer night capped every clip on this rig, the one user-facing retry
    there is -- "Make the missing proxies now" -- scanned, found everything
    capped, and did nothing at all."""
    src = _original(tmp_path)
    ffmpeg = _FakeFfmpeg()
    ffmpeg.encode_returncode = 1
    gen = _make_gen(tmp_path, encode_fn=ffmpeg)
    clip = _clip(src)
    for _ in range(3):
        gen.encode_once(dict(clip))
    assert gen._is_capped(clip) is True

    gen.request_run()

    assert gen._is_capped(clip) is False
    gen._scan_fn = lambda *a, **k: _scan_result([dict(clip)])
    gen.scan_once()
    assert [c["path"] for c in gen._queue] == [str(src)]


def test_the_scan_is_told_which_clips_are_capped(tmp_path):
    """COMP-MEDIA-4: the per-project queue is capped at 500 NEWEST-first, and
    the generator used to filter capped clips out only AFTER that truncation.
    A project whose newest 500 had all failed therefore reported an empty
    queue every 900 s -- for ever, since _failures is only cleared by the tray
    or a restart -- while the older encodable clips were never even scanned."""
    src = _original(tmp_path)
    ffmpeg = _FakeFfmpeg()
    ffmpeg.encode_returncode = 1
    gen = _make_gen(tmp_path, encode_fn=ffmpeg)
    clip = _clip(src)
    for _ in range(3):
        gen.encode_once(dict(clip))

    asked: dict = {}

    def _scan(root, selected, min_age, **kwargs):
        asked["skip_fn"] = kwargs.get("skip_fn")
        return _scan_result([])

    gen._scan_fn = _scan
    gen.scan_once()

    assert asked["skip_fn"] is not None
    assert asked["skip_fn"](dict(clip)) is True
    assert asked["skip_fn"](_clip(_original(tmp_path, name="B002.mp4"))) is False


def test_capped_clips_are_counted_so_the_log_can_say_why_nothing_runs(tmp_path):
    """"1040 missing, 0 queued" said nothing at all about why the machine had
    stopped trying (COMP-MEDIA-4)."""
    result = _scan_result([], missing=1040, own=1040)
    result["totals"]["capped"] = 1040
    gen = _make_gen(tmp_path, scan_fn=lambda *a, **k: result)
    gen.scan_once()

    assert gen.gap()["missing"] == 1040
    assert gen._queue == []
    assert gen._totals["capped"] == 1040


def test_two_originals_never_write_the_same_partial(tmp_path):
    """Rule 2, against the generator itself: `A001.mov` and `A001.mp4` share
    `Proxy/A001.mp4.partial`, and since the drain went parallel two workers
    could hold that one file at once (COMP-MEDIA-2)."""
    first = _original(tmp_path, name="A001.mov")
    second = _original(tmp_path, name="A001.mp4")
    gen = _make_gen(tmp_path)
    partial = proxy_scan.partial_path(str(first))
    assert partial == proxy_scan.partial_path(str(second))

    claimed: list[str] = []

    class _WhileEncoding(_FakeFfmpeg):
        def __call__(self, cmd, should_stop, ceiling):
            # Re-entered while the first encode is "running": the second
            # worker must be refused the file, not join it.
            if not claimed:
                claimed.append("in")
                assert gen.encode_once(_clip(second)) == proxy_gen.RESULT_SKIPPED
            return super().__call__(cmd, should_stop, ceiling)

    gen._encode_fn = _WhileEncoding()
    assert gen.encode_once(_clip(first)) == proxy_gen.RESULT_DONE
    assert claimed == ["in"]
    # ...and the claim is released again, so the twin is only ever refused
    # while an encode really is in flight.
    assert gen._partials == set()


def test_a_refused_partial_is_not_lost_for_ever(tmp_path):
    """The skip is a claim, not a cap: nothing is recorded against the clip."""
    src = _original(tmp_path)
    gen = _make_gen(tmp_path)
    clip = _clip(src)
    assert gen._claim_partial(proxy_scan.partial_path(str(src))) is True

    assert gen.encode_once(dict(clip)) == proxy_gen.RESULT_SKIPPED
    assert gen._failures == {}

    gen._release_partial(proxy_scan.partial_path(str(src)))
    assert gen.encode_once(dict(clip)) == proxy_gen.RESULT_DONE


def test_a_changed_file_gets_a_fresh_three_attempts(tmp_path):
    """The usual cause of three failures in a row is a truncated download.
    The editor re-downloads it -- a new (mtime, size) is a different file."""
    src = _original(tmp_path)
    ffmpeg = _FakeFfmpeg()
    ffmpeg.encode_returncode = 1
    gen = _make_gen(tmp_path, encode_fn=ffmpeg)
    clip = _clip(src)
    for _ in range(3):
        gen.encode_once(dict(clip))
    assert gen._is_capped(clip) is True

    src.write_bytes(b"y" * 5000)
    stamp = time.time() - SETTLED
    os.utime(src, (stamp, stamp))
    assert gen._is_capped(_clip(src)) is False


def test_the_failure_memory_is_never_persisted(tmp_path):
    """Deliberate: a blacklist on disk turns one bad night for the GPU into
    a permanent refusal to ever proxy those clips."""
    src = _original(tmp_path)
    ffmpeg = _FakeFfmpeg()
    ffmpeg.encode_returncode = 1
    gen = _make_gen(tmp_path, encode_fn=ffmpeg)
    gen.encode_once(_clip(src))
    written = [p.name for p in (tmp_path / "state").glob("*")] if (tmp_path / "state").is_dir() else []
    assert "proxy_failures.json" not in written


# -- notification --------------------------------------------------------------


def _notifier():
    sent: list[tuple[str, str]] = []
    return sent, lambda msg, title="ccsync-companion": sent.append((msg, title))


def test_one_toast_per_episode_naming_the_biggest_gap(tmp_path):
    sent, notify = _notifier()
    result = {
        "projects": {
            "2026/A/Small": {**proxy_scan.empty_gap(), "missing": 2, "own": 2},
            "2026/A/Nuclear": {**proxy_scan.empty_gap(), "missing": 12, "own": 12},
        },
        "totals": {**proxy_scan._empty_totals(), "missing": 14, "own": 14, "projects": 2},
    }
    gen = _make_gen(tmp_path, notify=notify, scan_fn=lambda *a, **k: result)
    gen.scan_once()
    assert gen._maybe_notify() is not None
    assert len(sent) == 1
    # Both numbers, each labelled: Nuclear's own 12 and the machine's 14. This
    # line used to assert "14 clips" beside the project name, i.e. the machine
    # total presented as the project's -- the reading that sent someone hunting
    # for 1046 clips in a project holding 438 (2026-08-10).
    assert "12 clips in Nuclear" in sent[0][0]
    assert "14 on this machine" in sent[0][0]
    # Same unchanged gap, next scan cycle: silence.
    gen.scan_once()
    assert gen._maybe_notify() is None
    assert len(sent) == 1


def test_the_latch_clears_when_the_gap_closes(tmp_path):
    sent, notify = _notifier()
    gap = {"missing": 3, "own": 3}
    gen = _make_gen(
        tmp_path, notify=notify,
        scan_fn=lambda *a, **k: {
            "projects": {"2026/A/One": {**proxy_scan.empty_gap(), **gap}},
            "totals": {**proxy_scan._empty_totals(), **gap},
        },
    )
    gen.scan_once()
    gen._maybe_notify()
    assert len(sent) == 1

    gap.update({"missing": 0, "own": 0})
    gen.scan_once()
    assert gen._maybe_notify() is None
    assert gen._notified_episode is False, "a closed gap makes the next one a new episode"


def test_the_cooldown_survives_a_restart(tmp_path):
    """A companion that restarts every morning must not re-nag about a gap
    the editor has already decided about."""
    sent, notify = _notifier()
    now = {"t": 1_000_000.0}
    scan = lambda *a, **k: {  # noqa: E731
        "projects": {"2026/A/One": {**proxy_scan.empty_gap(), "missing": 3, "own": 3}},
        "totals": {**proxy_scan._empty_totals(), "missing": 3, "own": 3},
    }
    gen = _make_gen(tmp_path, notify=notify, scan_fn=scan, wall_clock=lambda: now["t"])
    gen.scan_once()
    gen._maybe_notify()
    assert len(sent) == 1
    assert (tmp_path / "state" / proxy_gen.NOTIFY_STATE_FILENAME).is_file()

    # A whole new process, an hour later.
    later = _make_gen(tmp_path, notify=notify, scan_fn=scan,
                      wall_clock=lambda: now["t"] + 3600)
    later.scan_once()
    assert later._maybe_notify() is None
    assert len(sent) == 1

    # A day and a bit later it may speak again.
    tomorrow = _make_gen(tmp_path, notify=notify, scan_fn=scan,
                         wall_clock=lambda: now["t"] + 90000)
    tomorrow.scan_once()
    assert tomorrow._maybe_notify() is not None
    assert len(sent) == 2


def test_the_toast_says_what_will_actually_happen(tmp_path):
    totals = {**proxy_scan._empty_totals(), "missing": 5, "own": 5}
    gen = _make_gen(tmp_path)
    gen._ffmpeg_ok = True
    assert "while you're away" in gen._notify_text("2026/A/One", totals)

    gen.generation_enabled = False
    assert "Ask your admin" in gen._notify_text("2026/A/One", totals)

    gen.generation_enabled = True
    gen._ffmpeg_ok = False
    assert "no ffmpeg" in gen._notify_text("2026/A/One", totals)

    braw = {**proxy_scan._empty_totals(), "missing": 4, "needs_resolve": 4, "braw": 4}
    gen._ffmpeg_ok = True
    assert "Blackmagic Proxy Generator" in gen._notify_text("2026/A/One", braw)


def test_the_toast_never_reports_the_machine_total_under_one_project_name(tmp_path):
    """It read "1046 clips in Energy Transition have no proxy" when the 1046
    was seven projects and Energy Transition held 438 -- so the reader goes
    hunting for a thousand clips in a project that has 438 (base rig,
    2026-08-10). Both numbers appear, each labelled."""
    totals = {**proxy_scan._empty_totals(), "missing": 1046, "own": 1046}
    gen = _make_gen(tmp_path)
    gen._ffmpeg_ok = True

    text = gen._notify_text("2026/FF5/Energy Transition", totals, 438)
    assert "438 clips in Energy Transition" in text
    assert "1046 on this machine" in text

    # One project holding the whole gap says the number once, not twice.
    single = gen._notify_text("2026/A/One", {**totals, "missing": 5}, 5)
    assert "5 clips in One" in single and "on this machine" not in single

    # And an unknown project still names the total rather than nothing.
    assert "1046" in gen._notify_text("", totals, 0)


def test_notification_can_be_switched_off(tmp_path):
    sent, notify = _notifier()
    gen = _make_gen(
        tmp_path, _cfg(tmp_path, proxy_notify_enabled=False), notify=notify,
        scan_fn=lambda *a, **k: {
            "projects": {"2026/A/One": {**proxy_scan.empty_gap(), "missing": 3, "own": 3}},
            "totals": {**proxy_scan._empty_totals(), "missing": 3, "own": 3},
        },
    )
    gen.scan_once()
    assert gen._maybe_notify() is None
    assert sent == []


def test_a_notifier_that_raises_never_reaches_the_worker(tmp_path):
    def _boom(msg, title="x"):
        raise RuntimeError("no tray backend")

    gen = _make_gen(
        tmp_path, notify=_boom,
        scan_fn=lambda *a, **k: {
            "projects": {"2026/A/One": {**proxy_scan.empty_gap(), "missing": 3, "own": 3}},
            "totals": {**proxy_scan._empty_totals(), "missing": 3, "own": 3},
        },
    )
    gen.scan_once()
    assert gen._maybe_notify() is not None  # it tried, and survived


# -- what the tray and the reporter read --------------------------------------


def test_gap_and_coverage_are_cheap_reads(tmp_path):
    gen = _make_gen(tmp_path, scan_fn=lambda *a, **k: _scan_result(
        [{"path": "a.mp4", "kind": "own", "size": 1, "mtime": 2.0}],
        missing=3, braw=1, needs_resolve=1, own=2,
    ))
    gen.scan_once()
    gap = gen.gap()
    assert gap["missing"] == 3 and gap["braw"] == 1 and gap["left"] == 1
    assert gap["encoding"] is False and gap["can_generate"] is True

    coverage = gen.coverage()
    assert coverage["state"] == proxy_gen.STATE_NOTHING_TO_DO
    assert coverage["missing"] == 3
    assert coverage["ffmpeg"] is True
    assert coverage["scanned_at"]
    assert coverage["projects"]["2026/FF5/Nuclear"]["missing"] == 3
    # The per-clip queue is NOT in the payload: it is a work list, and 500
    # paths per project would be a report the dashboard refuses (B6).
    assert "clips" not in coverage["projects"]["2026/FF5/Nuclear"]


def test_fully_covered_projects_are_not_reported(tmp_path):
    """A base rig with 64 clean projects would otherwise send 64 rows of
    zeroes on every tick."""
    result = {
        "projects": {
            "2026/A/Clean": proxy_scan.empty_gap(),
            "2026/A/Gappy": {**proxy_scan.empty_gap(), "missing": 1, "own": 1},
        },
        "totals": {**proxy_scan._empty_totals(), "missing": 1, "own": 1, "projects": 2},
    }
    gen = _make_gen(tmp_path, scan_fn=lambda *a, **k: result)
    gen.scan_once()
    assert list(gen.coverage()["projects"]) == ["2026/A/Gappy"]


def test_block_reason_is_none_unless_something_is_encoding(tmp_path):
    gen = _make_gen(tmp_path)
    assert gen.block_reason() is None
    gen._mark_encoding("A001.mp4")          # what encode_once() does per clip
    gen._queue = [{"path": "b.mp4"}]
    reason = gen.block_reason()
    assert reason and "proxies" in reason
    # The clip in flight counts as left to do: it is off the queue but not
    # finished, and this sentence is what holds a shutdown back.
    assert "2 clip(s) left" in reason
    gen._clear_encoding()
    assert gen.block_reason() is None


def test_the_gap_shrinks_as_the_queue_drains(tmp_path):
    """Otherwise the tray keeps saying "3 clips have no proxy" for the rest
    of the 15-minute scan interval while it is busy fixing them."""
    src = _original(tmp_path)
    gen = _make_gen(tmp_path, scan_fn=lambda *a, **k: _scan_result([_clip(src)], missing=3, own=3))
    gen.scan_once()
    assert gen.gap()["missing"] == 3
    assert gen.encode_once() == proxy_gen.RESULT_DONE
    assert gen.gap()["missing"] == 2


# -- the tick + lifecycle ------------------------------------------------------


def test_a_tick_scans_notifies_and_encodes(tmp_path):
    src = _original(tmp_path)
    sent, notify = _notifier()
    gen = _make_gen(
        tmp_path, notify=notify,
        scan_fn=lambda *a, **k: _scan_result([_clip(src)]),
    )
    state = gen.tick()
    assert state == proxy_gen.STATE_NOTHING_TO_DO  # the queue drained
    assert (src.parent / "Proxy" / "A001.mp4").is_file()
    assert len(sent) == 1


def test_a_tick_notifies_but_never_encodes_when_generation_is_off(tmp_path):
    """The editor default (derived from lane_b_enabled): telling costs
    nothing and never touches a byte."""
    src = _original(tmp_path)
    sent, notify = _notifier()
    ffmpeg = _FakeFfmpeg()
    gen = _make_gen(
        tmp_path, _cfg(tmp_path, proxy_gen_enabled=False), notify=notify,
        encode_fn=ffmpeg, scan_fn=lambda *a, **k: _scan_result([_clip(src)]),
    )
    assert gen.tick() == proxy_gen.STATE_DISABLED
    assert len(sent) == 1
    assert ffmpeg.calls == []
    assert not (src.parent / "Proxy").exists()


def test_a_tick_that_raises_never_kills_the_thread(tmp_path):
    """One bad tick must not end the worker: this feature's whole value is
    that it keeps telling you about the gap."""
    gen = _make_gen(tmp_path)
    ticks = {"count": 0}

    def _boom():
        ticks["count"] += 1
        gen.stop()  # end the loop after this one, without an exception path
        raise RuntimeError("everything is on fire")

    gen.tick = _boom  # the loop's own try/except is what is under test
    gen._loop()       # returns rather than propagating
    assert ticks["count"] == 1


# -- the parallel drain --------------------------------------------------------
#
# 2026-08-11, owner-approved: "maxed out while the machine is idle, demote when
# Resolve is using the machine". The idle gate above is what makes the first
# half safe -- an unforced encode only ever runs on a machine nobody is sitting
# at -- and these are the tests for the second half and for the width itself.


class _BlockingFfmpeg(_FakeFfmpeg):
    """A fake encoder that PARKS in the encode until the test lets it go.

    The only way to ask "were two clips being encoded at the same time?" of a
    drain that finishes in microseconds. `expect` encodes park before all_in is
    set; `peak` is the most that were ever inside at once, which is the number
    the demotion rule is about. Verification decodes pass straight through --
    they run after the encode, and blocking them would deadlock the release.
    """

    def __init__(self, expect=2, timeout=10.0):
        super().__init__()
        self.expect = expect
        self.timeout = timeout
        self.release = threading.Event()
        self.all_in = threading.Event()
        self._guard = threading.Lock()
        self.in_flight = 0
        self.peak = 0

    def __call__(self, cmd, should_stop, ceiling):
        if self._is_verify(cmd):
            return super().__call__(cmd, should_stop, ceiling)
        with self._guard:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
            if self.in_flight >= self.expect:
                self.all_in.set()
        try:
            self.release.wait(self.timeout)
        finally:
            with self._guard:
                self.in_flight -= 1
        # AFTER the release, so a test that makes the user come back while the
        # encodes are parked gets the interrupt answer the real runner's 2 s
        # poll would have given it.
        return super().__call__(cmd, should_stop, ceiling)


def _drain_in_background(gen):
    thread = threading.Thread(target=gen._drain_queue, daemon=True)
    thread.start()
    return thread


def test_the_default_width_is_two_on_a_cpu_and_four_with_nvenc(tmp_path):
    """Derived, not configured: most machines should not have to know what an
    NVENC session is. libx264 already multithreads, so CPU-only stops at 2."""
    gen = _make_gen(tmp_path)
    assert gen._worker_width() == proxy_gen.DEFAULT_WORKERS_CPU == 2

    gen = _make_gen(
        tmp_path, encoders_fn=lambda path: frozenset({"hevc_nvenc", "libx265"}))
    gen.scan_once()          # where _nvenc is answered
    assert gen._worker_width() == proxy_gen.DEFAULT_WORKERS_NVENC == 4


def test_the_worker_knob_overrides_the_default_in_either_direction(tmp_path):
    nvenc = {"encoders_fn": lambda path: frozenset({"hevc_nvenc", "libx265"})}

    gen = _make_gen(tmp_path, _cfg(tmp_path, proxy_gen_workers=6))
    assert gen._worker_width() == 6

    # Down as well as up: one worker is the old serial drain, on purpose.
    gen = _make_gen(tmp_path, _cfg(tmp_path, proxy_gen_workers=1), **nvenc)
    gen.scan_once()
    assert gen._worker_width() == 1

    gen = _make_gen(tmp_path, _cfg(tmp_path, proxy_gen_workers=64))
    assert gen._worker_width() == proxy_gen.MAX_WORKERS == 8


@pytest.mark.parametrize("value", [None, "", 0, -3, "banana"])
def test_a_missing_or_nonsense_worker_count_derives_the_default(tmp_path, value):
    """coerce_numeric's contract: construction never raises on a hand-edited
    value, and a width invented from `"banana"` would be worse than the
    derived one."""
    gen = _make_gen(tmp_path, _cfg(tmp_path, proxy_gen_workers=value))
    assert gen.workers is None
    assert gen._worker_width() == proxy_gen.DEFAULT_WORKERS_CPU


def test_a_drain_encodes_several_clips_at_once(tmp_path):
    """The whole point: two clips in flight together on an idle machine."""
    first, second = _original(tmp_path, "A001.mp4"), _original(tmp_path, "A002.mp4")
    ffmpeg = _BlockingFfmpeg(expect=2)
    gen = _make_gen(tmp_path, encode_fn=ffmpeg)
    gen._queue = [_clip(first), _clip(second)]

    thread = _drain_in_background(gen)
    assert ffmpeg.all_in.wait(10), "the second clip never started while the first ran"
    assert ffmpeg.peak == 2
    assert len(gen.gap()["encoding_now"]) == 2
    ffmpeg.release.set()
    thread.join(timeout=30)

    assert not thread.is_alive()
    assert (first.parent / "Proxy" / "A001.mp4").is_file()
    assert (second.parent / "Proxy" / "A002.mp4").is_file()


def test_resolve_running_demotes_the_drain_to_one_encode(tmp_path):
    """An UNATTENDED RENDER is the one thing serialism ever protected, and it
    is invisible to the idle probe. Four proxies would take the same NVENC
    sessions, so while Resolve is up the drain acts as one worker."""
    clips = [_original(tmp_path, name) for name in ("A001.mp4", "A002.mp4", "A003.mp4")]
    ffmpeg = _BlockingFfmpeg(expect=1, timeout=2.0)
    gen = _make_gen(
        tmp_path, encode_fn=ffmpeg, resolve_running_fn=lambda: True,
        encoders_fn=lambda path: frozenset({"hevc_nvenc", "libx265"}),
    )
    gen.scan_once()
    assert gen._worker_width() == 4          # it is NOT the width that shrinks
    gen._queue = [_clip(path) for path in clips]

    thread = _drain_in_background(gen)
    assert ffmpeg.all_in.wait(10)
    assert gen.gap()["encoding_count"] == 1
    ffmpeg.release.set()
    thread.join(timeout=60)

    assert not thread.is_alive()
    assert ffmpeg.peak == 1, "Resolve was rendering and four ffmpegs joined it"
    assert all((path.parent / "Proxy" / path.name).is_file() for path in clips)


def test_a_demotion_probe_that_cannot_answer_demotes(tmp_path):
    """Same fail-closed reading as the gate's: a check that cannot answer must
    not be taken as "the GPU is free"."""
    def _boom():
        raise RuntimeError("tasklist is unavailable")

    gen = _make_gen(tmp_path, resolve_running_fn=_boom)
    assert gen._resolve_running_cached() is True
    # ...and it is asked once per TTL, not once per pickup: the real probe is a
    # process spawn and every waiting worker asks (MED-9's family).
    asked = {"count": 0}

    def _count():
        asked["count"] += 1
        return True

    gen = _make_gen(tmp_path, resolve_running_fn=_count)
    for _ in range(5):
        assert gen._resolve_running_cached() is True
    assert asked["count"] == 1


def test_skip_while_resolve_running_still_skips_the_drain_entirely(tmp_path):
    """Demotion is the DEFAULT behaviour; the opt-in knob is unchanged and
    takes precedence -- it stops the drain before a worker exists."""
    src = _original(tmp_path)
    ffmpeg = _BlockingFfmpeg(expect=1, timeout=1.0)
    gen = _make_gen(
        tmp_path, _cfg(tmp_path, proxy_gen_skip_while_resolve_running=True),
        encode_fn=ffmpeg, resolve_running_fn=lambda: True,
        scan_fn=lambda *a, **k: _scan_result([_clip(src)]),
    )
    assert gen.tick() == proxy_gen.STATE_RESOLVE_OPEN
    assert ffmpeg.calls == []
    assert not (src.parent / "Proxy").exists()


def test_a_forced_run_drains_at_the_full_width(tmp_path):
    """"Make the missing proxies now" is asking for exactly that: the away
    gate is skipped AND the machine is used at full width."""
    first, second = _original(tmp_path, "A001.mp4"), _original(tmp_path, "A002.mp4")
    ffmpeg = _BlockingFfmpeg(expect=2)
    gen = _make_gen(tmp_path, encode_fn=ffmpeg, idle_probe=_Idle(0))  # user is here
    gen._queue = [_clip(first), _clip(second)]
    gen.request_run()

    thread = _drain_in_background(gen)
    assert ffmpeg.all_in.wait(10)
    assert ffmpeg.peak == 2
    ffmpeg.release.set()
    thread.join(timeout=30)

    assert not thread.is_alive()
    assert (first.parent / "Proxy" / "A001.mp4").is_file()
    assert (second.parent / "Proxy" / "A002.mp4").is_file()


def test_the_user_coming_back_stops_every_worker_and_requeues_them_all(tmp_path):
    """The central promise, unchanged per encode and now applied to all of
    them at once: nothing left behind, and every aborted clip back at the
    FRONT (their order among themselves is completion order, which between
    equally-newest clips buys nothing to make deterministic)."""
    first, second = _original(tmp_path, "A001.mp4"), _original(tmp_path, "A002.mp4")
    later = {"path": "later.mp4", "kind": "own", "size": 1, "mtime": 1.0}
    idle = _Idle(9999)
    ffmpeg = _BlockingFfmpeg(expect=2)
    gen = _make_gen(tmp_path, encode_fn=ffmpeg, idle_probe=idle)
    gen._queue = [_clip(first), _clip(second), later]

    thread = _drain_in_background(gen)
    assert ffmpeg.all_in.wait(10)
    idle.seconds = 3          # the mouse moved, with two encodes in flight
    ffmpeg.release.set()
    thread.join(timeout=30)

    assert not thread.is_alive()
    for path in (first, second):
        assert not (path.parent / "Proxy" / f"{path.name}.partial").exists()
        assert not (path.parent / "Proxy" / path.name).exists()
    assert len(gen._queue) == 3
    assert {clip["path"] for clip in gen._queue[:2]} == {str(first), str(second)}
    assert gen._queue[2] is later
    assert gen.gap()["encoding"] is False


def test_the_gap_says_how_many_clips_are_in_flight(tmp_path):
    """`encoding` stays a BOOL -- the tray renders it as one and hashes it into
    _menu_fingerprint (UI-3), so the menu must not rebuild every time a
    different clip starts. The detail lives in the two keys beside it, and
    `_current` still answers with a single path for anything older."""
    gen = _make_gen(tmp_path)
    gen._queue = [{"path": "c.mp4"}]
    assert gen.gap()["encoding"] is False
    assert gen.gap()["encoding_now"] == [] and gen.gap()["encoding_count"] == 0
    assert gen._current is None

    gen._mark_encoding("a.mp4")
    assert gen.gap()["encoding"] is True
    assert gen.gap()["encoding_count"] == 1
    assert gen._current == "a.mp4"
    # Two in flight are two clips still to come, on top of the one queued.
    assert gen.gap()["left"] == 2

    done = threading.Event()

    def _second_worker():
        gen._mark_encoding("b.mp4")
        done.set()

    thread = threading.Thread(target=_second_worker)
    thread.start()
    thread.join(timeout=5)
    assert done.is_set()

    assert gen.gap()["encoding"] is True
    assert gen.gap()["encoding_count"] == 2
    assert set(gen.gap()["encoding_now"]) == {"a.mp4", "b.mp4"}
    assert gen.gap()["left"] == 3
    # The oldest encode in flight: the one-path view is only ever unambiguous
    # with one worker, and that case must read exactly as it did before.
    assert gen._current == "a.mp4"
    assert "2 at once" in (gen.block_reason() or "")


# -- the BPG hand-off ----------------------------------------------------------


class _RecordingBpg:
    """A BpgLauncher-shaped object that records what it was asked."""

    def __init__(self, enabled=True):
        self.enabled = enabled
        self.calls: list[dict] = []

    def maybe_launch(self, *, queue_empty, needs_resolve, user_away, watch_dirs=()):
        self.calls.append({"queue_empty": queue_empty,
                           "needs_resolve": needs_resolve,
                           "user_away": user_away,
                           "watch_dirs": list(watch_dirs)})
        return None


class _CountingIdle:
    def __init__(self, seconds):
        self.seconds = seconds
        self.asked = 0

    def seconds_idle(self):
        self.asked += 1
        return self.seconds


@pytest.mark.parametrize("state", [
    proxy_gen.STATE_PAUSED,
    proxy_gen.STATE_MISCONFIGURED,
    proxy_gen.STATE_DRIVE_ABSENT,
    proxy_gen.STATE_RUNNING,
])
def test_bpg_is_not_launched_from_a_state_that_forbids_it(tmp_path, state):
    """MED-7: the gate was only "the ffmpeg queue is empty", so a PAUSED base
    rig still spawned Resolve.exe -pg -- and nothing in this module ever stops
    it. Paused means the editor pressed stop; misconfigured and drive-absent
    mean there is nothing sane to watch."""
    launcher = _RecordingBpg()
    gen = _make_gen(tmp_path, bpg_launcher=launcher)
    gen._totals["needs_resolve"] = 6

    gen._maybe_launch_bpg(state)

    assert launcher.calls == []


def test_a_paused_machine_does_not_launch_bpg_through_a_whole_tick(tmp_path):
    """The same rule where it actually bites: a real tick on a paused rig."""
    launcher = _RecordingBpg()
    gen = _make_gen(tmp_path, bpg_launcher=launcher, paused_fn=lambda: True)
    gen._totals["needs_resolve"] = 6

    assert gen.tick() == proxy_gen.STATE_PAUSED
    assert launcher.calls == []


def test_bpg_is_launched_once_there_is_nothing_for_ffmpeg_to_do(tmp_path):
    launcher = _RecordingBpg()
    gen = _make_gen(tmp_path, bpg_launcher=launcher)
    gen._totals["needs_resolve"] = 6

    gen._maybe_launch_bpg(proxy_gen.STATE_NOTHING_TO_DO)

    assert len(launcher.calls) == 1
    assert launcher.calls[0]["queue_empty"] is True
    assert launcher.calls[0]["needs_resolve"] == 6


def test_bpg_is_not_launched_while_a_worker_is_still_encoding(tmp_path):
    """"The ffmpeg queue is empty" stopped meaning "ffmpeg is idle" the day the
    drain went parallel (2026-08-11): the last clips come OFF the queue while
    they encode, and BPG taking the GPU while four of them finish is the exact
    contention the sequencing exists to prevent."""
    launcher = _RecordingBpg()
    src = _original(tmp_path)
    ffmpeg = _BlockingFfmpeg(expect=1)
    gen = _make_gen(tmp_path, bpg_launcher=launcher, encode_fn=ffmpeg)
    gen._totals["needs_resolve"] = 6
    gen._queue = [_clip(src)]

    thread = _drain_in_background(gen)
    assert ffmpeg.all_in.wait(10)
    assert gen._queue == []                      # the queue IS empty...
    gen._maybe_launch_bpg(proxy_gen.STATE_NOTHING_TO_DO)
    assert launcher.calls[-1]["queue_empty"] is False, "...but a clip is encoding"

    ffmpeg.release.set()
    thread.join(timeout=30)
    assert not thread.is_alive()

    gen._maybe_launch_bpg(proxy_gen.STATE_NOTHING_TO_DO)
    assert launcher.calls[-1]["queue_empty"] is True


def test_the_idle_probe_is_handed_over_uncalled(tmp_path):
    """MED-8: `user_away=self._user_is_away()` was evaluated eagerly on every
    15 s tick on every machine, and BPG discards it on its first line -- every
    Mac editor forked ioreg ~5,700 times a day for it."""
    launcher = _RecordingBpg()
    idle = _CountingIdle(9999)
    gen = _make_gen(tmp_path, bpg_launcher=launcher, idle_probe=idle)
    gen._totals["needs_resolve"] = 6

    gen._maybe_launch_bpg(proxy_gen.STATE_NOTHING_TO_DO)

    assert callable(launcher.calls[0]["user_away"])
    assert idle.asked == 0
    # ...and it still answers correctly when the launcher does ask.
    assert launcher.calls[0]["user_away"]() is True
    assert idle.asked == 1


def test_a_disabled_launcher_costs_nothing_at_all(tmp_path):
    """The early return that never fired: self._bpg is never None in the app,
    so a Mac (where BPG does not exist) paid the whole gate every tick."""
    launcher = _RecordingBpg(enabled=False)
    idle = _CountingIdle(9999)
    gen = _make_gen(tmp_path, bpg_launcher=launcher, idle_probe=idle)
    gen._totals["needs_resolve"] = 6

    gen._maybe_launch_bpg(proxy_gen.STATE_NOTHING_TO_DO)

    assert launcher.calls == []
    assert idle.asked == 0


def test_a_launcher_that_raises_is_still_not_fatal(tmp_path):
    class _Boom:
        enabled = True

        def maybe_launch(self, **kw):
            raise RuntimeError("Resolve is not installed after all")

    gen = _make_gen(tmp_path, bpg_launcher=_Boom())
    gen._totals["needs_resolve"] = 6
    gen._maybe_launch_bpg(proxy_gen.STATE_NOTHING_TO_DO)  # must not raise


def test_start_is_a_no_op_when_both_halves_are_off(tmp_path):
    gen = _make_gen(
        tmp_path, _cfg(tmp_path, proxy_gen_enabled=False, proxy_notify_enabled=False))
    gen.start()
    assert gen._thread is None


def test_start_stop_join_is_survivable_in_any_order(tmp_path):
    gen = _make_gen(tmp_path)
    gen.join()          # never started
    gen.start()
    gen.start()         # twice
    gen.stop()
    gen.join(timeout=5.0)
    assert not gen._thread.is_alive()


# -- the stale-partial sweep ---------------------------------------------------


def test_stale_partials_are_reported_never_deleted(tmp_path):
    """The same refusal as fixer.sweep_stale_tmp_files: nothing on the
    filesystem proves some other process isn't writing that file right now,
    and an automatic delete here would be this system's only unprompted
    removal of a file under local_root."""
    proxy_dir = tmp_path / "Projects" / "2026" / "FF5" / "Nuclear" / "Proxy"
    proxy_dir.mkdir(parents=True)
    stale = proxy_dir / "A001.mp4.partial"
    stale.write_bytes(b"half an encode")
    old = time.time() - (24 * 3600)
    os.utime(stale, (old, old))
    live = proxy_dir / "A002.mp4.partial"
    live.write_bytes(b"being written right now")
    (proxy_dir / "A003.mp4").write_bytes(b"a finished proxy")
    # A .partial OUTSIDE a Proxy dir is rclone's own marker, not ours.
    elsewhere = tmp_path / "Projects" / "2026" / "FF5" / "Nuclear" / "upload.mov.partial"
    elsewhere.write_bytes(b"rclone")
    os.utime(elsewhere, (old, old))

    found = proxy_gen.sweep_stale_partials(str(tmp_path))
    assert found == [str(stale)]
    assert stale.is_file(), "the sweep must never delete anything"
    assert live.is_file()


def test_the_sweep_never_raises_on_a_missing_tree(tmp_path):
    assert proxy_gen.sweep_stale_partials("") == []
    assert proxy_gen.sweep_stale_partials(str(tmp_path / "not-there")) == []


# -- the runner itself (no real ffmpeg: a fake Popen, per the suite's rule) ---


class _FakeProc:
    """A Popen-shaped object. `polls` is what poll() answers in order, so a
    test can say "still running, still running, then exit 0"."""

    def __init__(self, polls, stderr_lines=()):
        self._polls = list(polls)
        self._last = None
        self.stderr = _FakeStream(stderr_lines)
        self.killed = 0
        self.waited: list = []

    def poll(self):
        if self._polls:
            self._last = self._polls.pop(0)
        return self._last

    def kill(self):
        self.killed += 1
        self._polls = [-9]

    def wait(self, timeout=None):
        self.waited.append(timeout)
        return -9


class _FakeStream:
    def __init__(self, lines):
        self._lines = list(lines)
        self.closed = False

    def readline(self):
        return self._lines.pop(0) if self._lines else ""

    def close(self):
        self.closed = True


def test_the_stderr_reader_is_bounded_and_closes_the_pipe():
    """The pipe's OS buffer is ~64 KB and a full one BLOCKS ffmpeg forever
    -- the classic Popen deadlock. Bounded, because an encoder that
    complains once per frame would otherwise be a memory leak."""
    import collections

    sink = collections.deque(maxlen=3)
    stream = _FakeStream([f"line {i}\n" for i in range(10)])
    proxy_gen._drain(stream, sink)
    assert list(sink) == ["line 7", "line 8", "line 9"]
    assert stream.closed is True


def test_the_stderr_reader_never_raises():
    class _Broken:
        def readline(self):
            raise OSError("the pipe went away")

        def close(self):
            raise OSError("so did the handle")

    proxy_gen._drain(_Broken(), [])  # must not propagate


def test_killing_a_child_is_bounded(caplog):
    """rclone_lane._end_probe's idiom: a process stuck in an uninterruptible
    kernel wait cannot be killed at all, and an unbounded wait() here would
    hang the very thread whose job is to be responsive."""
    proc = _FakeProc([None])
    proxy_gen._kill(proc)
    assert proc.killed == 1
    assert proc.waited and proc.waited[0] is not None

    class _Stubborn(_FakeProc):
        def kill(self):
            raise OSError("no such process")

        def wait(self, timeout=None):
            raise RuntimeError("still there")

    with caplog.at_level("WARNING", logger="ccsync.proxy_gen"):
        proxy_gen._kill(_Stubborn([None]))  # must not raise
    assert "did not die" in " ".join(r.getMessage() for r in caplog.records)


def test_the_runner_polls_until_the_child_exits(tmp_path, monkeypatch):
    proc = _FakeProc([None, None, 0], stderr_lines=["a warning\n"])
    monkeypatch.setattr(proxy_gen, "_default_popen", lambda cmd: proc)
    gen = _make_gen(tmp_path)
    gen._stop_event = _NoWait()

    result = gen._run_ffmpeg(["ffmpeg", "-i", "x"], lambda: None, 999.0)
    assert result["returncode"] == 0
    assert result["interrupted"] is None and result["timed_out"] is False
    assert result["stderr"] == "a warning"
    assert proc.killed == 0


def test_the_runner_kills_on_the_first_stop_answer(tmp_path, monkeypatch):
    proc = _FakeProc([None, None, None])
    monkeypatch.setattr(proxy_gen, "_default_popen", lambda cmd: proc)
    gen = _make_gen(tmp_path)
    gen._stop_event = _NoWait()

    result = gen._run_ffmpeg(["ffmpeg"], lambda: "you're back at the keyboard", 999.0)
    assert result["interrupted"] == "you're back at the keyboard"
    assert proc.killed == 1


def test_the_runner_kills_a_child_past_the_ceiling(tmp_path, monkeypatch):
    proc = _FakeProc([None] * 10)
    monkeypatch.setattr(proxy_gen, "_default_popen", lambda cmd: proc)
    ticks = iter([0.0, 1.0, 5000.0, 5000.0])
    gen = _make_gen(tmp_path, clock=lambda: next(ticks))
    gen._stop_event = _NoWait()

    result = gen._run_ffmpeg(["ffmpeg"], lambda: None, 1800.0)
    assert result["timed_out"] is True
    assert proc.killed == 1


def test_stderr_still_being_written_does_not_break_the_never_raise_contract(
        tmp_path, monkeypatch):
    """MED-13: reader.join(timeout=5) can time out -- a _kill that failed to
    reap the child leaves the reader appending -- and joining a deque another
    thread is mutating raises "deque mutated during iteration", out of the one
    function whose whole contract is that it never raises."""
    class _MutatingDeque(list):
        def __iter__(self):
            raise RuntimeError("deque mutated during iteration")

    class _FakeCollections:
        @staticmethod
        def deque(maxlen=None):
            return _MutatingDeque()

    proc = _FakeProc([None, 0], stderr_lines=["a warning\n"])
    monkeypatch.setattr(proxy_gen, "_default_popen", lambda cmd: proc)
    monkeypatch.setattr(proxy_gen, "collections", _FakeCollections)
    gen = _make_gen(tmp_path)
    gen._stop_event = _NoWait()

    result = gen._run_ffmpeg(["ffmpeg"], lambda: None, 999.0)

    assert result["returncode"] == 0
    assert result["stderr"] == ""


def test_a_spawn_that_fails_is_a_failure_not_a_crash(tmp_path, monkeypatch):
    def _boom(cmd):
        raise FileNotFoundError("ffmpeg is not there any more")

    monkeypatch.setattr(proxy_gen, "_default_popen", _boom)
    gen = _make_gen(tmp_path)
    result = gen._run_ffmpeg(["ffmpeg"], lambda: None, 60.0)
    assert result["returncode"] is None
    assert "could not start ffmpeg" in result["stderr"]


class _NoWait:
    """A stop event whose wait() returns instantly -- the poll interval is
    2 s of real time and no test may pay it."""

    def is_set(self):
        return False

    def wait(self, timeout=None):
        return False

    def set(self):
        pass

    def clear(self):
        pass


def test_the_encoder_is_spawned_below_normal_with_no_window(windows, monkeypatch):
    """A windowed build (build.spec, console=False) flashes a console per
    spawn without CREATE_NO_WINDOW, and this spawns one per clip,
    unattended -- which would be a strobe light. BelowNormal is what covers
    the two seconds before the kill poll notices the user is back."""
    import subprocess as sp

    captured: dict = {}

    class _Popen:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            self.pid = 4321

    monkeypatch.setattr(sp, "Popen", _Popen)
    proxy_gen._default_popen(["ffmpeg", "-i", "x"])

    flags = captured["kwargs"]["creationflags"]
    assert flags & sp.CREATE_NO_WINDOW
    assert flags & 0x00004000  # BELOW_NORMAL_PRIORITY_CLASS
    assert captured["kwargs"]["stderr"] is sp.PIPE
    assert captured["kwargs"]["stdin"] is sp.DEVNULL


def test_posix_renices_after_the_spawn(monkeypatch):
    """os.setpriority AFTER the fork, never preexec_fn: preexec_fn runs
    between fork and exec and is documented as unsafe in a threaded program
    -- and this whole module IS a thread."""
    import subprocess as sp
    import sys as sys_mod

    monkeypatch.setattr(sys_mod, "platform", "darwin")
    monkeypatch.setattr(sp, "Popen", lambda cmd, **kw: type("P", (), {"pid": 99})())
    calls: list = []
    monkeypatch.setattr(os, "setpriority", lambda which, who, prio: calls.append((who, prio)),
                        raising=False)
    monkeypatch.setattr(os, "PRIO_PROCESS", 0, raising=False)

    proxy_gen._default_popen(["ffmpeg"])
    assert calls == [(99, proxy_gen.ENCODE_NICE)]


def test_a_failed_renice_is_a_slower_machine_not_a_failed_encode(monkeypatch):
    import subprocess as sp
    import sys as sys_mod

    monkeypatch.setattr(sys_mod, "platform", "linux")
    monkeypatch.setattr(sp, "Popen", lambda cmd, **kw: type("P", (), {"pid": 99})())

    def _boom(*a):
        raise PermissionError("not allowed")

    monkeypatch.setattr(os, "setpriority", _boom, raising=False)
    monkeypatch.setattr(os, "PRIO_PROCESS", 0, raising=False)
    assert proxy_gen._default_popen(["ffmpeg"]) is not None
