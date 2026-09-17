"""The editing proxy that arrives behind the editor (plan section 6, step 5).

The stand-in puts the preview's bytes under the original's name so the clip
can exist at all; this is the good proxy landing afterwards and being linked,
in its own fetch lane (audit F7) and through the one-shot Resolve child that
keeps scriptapp() to a single caller per process (CR-68). 2026-09-17.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ccsync_companion import broll_fetch, broll_server, broll_standins, music_worker


@pytest.fixture(autouse=True)
def ledger(tmp_path):
    led = broll_standins.configure(tmp_path / "state" / "broll_standins.json")
    yield led
    broll_standins.configure(broll_standins.default_state_path())


@pytest.fixture(autouse=True)
def no_real_jobs():
    """The fetch registry is module state; a test that registers a job must
    not leave it for the next one."""
    broll_fetch._JOBS.clear()
    yield
    broll_fetch._JOBS.clear()


def _cfg(tmp_path):
    return {"local_root": str(tmp_path), "mode": "editor",
            "canonical_prefix": "P:\\", "remote": "nas",
            "remote_root": "/mnt/tank/cc", "rclone_path": "rclone"}


def _archive(tmp_path, *parts):
    return tmp_path.joinpath("Assets", "B-roll Archive", *parts)


@pytest.fixture
def placed(tmp_path):
    """A stand-in already on disk and in the ledger, its upgrade owed."""
    standin = _archive(tmp_path, "cc", "ff5", "clip.mov")
    standin.parent.mkdir(parents=True, exist_ok=True)
    standin.write_bytes(b"preview bytes")
    broll_standins.record(standin, share="broll", rel_path="cc/ff5/clip.mov",
                          preview_rel="cc/ff5/Proxy/clip.mp4",
                          edit_proxy_rel="cc/ff5/Proxy/clip.mov",
                          upgrade=broll_standins.UPGRADE_PENDING)
    return standin


def _mounts(tmp_path):
    return broll_server.resolve_mounts({}, _cfg(tmp_path))


def test_the_upgrade_downloads_to_the_proxys_own_path_and_links_it_once(
        tmp_path, placed):
    fetches, links = [], []

    def fetcher(cfg, rel_path, dest, **kwargs):
        fetches.append({"rel": rel_path, "dest": dest, **kwargs})
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"the editing proxy")
        return {"state": broll_fetch.STATE_DONE}

    def caller(action, **kwargs):
        links.append({"action": action, **kwargs})
        return {"ok": True, "message": "Proxy relinked"}

    result = broll_server.run_proxy_upgrade(
        _cfg(tmp_path), _mounts(tmp_path), "broll", str(placed),
        "cc/ff5/Proxy/clip.mov", fetcher=fetcher, caller=caller,
        sleep=lambda _s: None)

    proxy = str(_archive(tmp_path, "cc", "ff5", "Proxy", "clip.mov"))
    assert result["ok"] is True
    assert fetches[0]["rel"] == "cc/ff5/Proxy/clip.mov"
    assert fetches[0]["dest"] == proxy
    # Its own lane: nobody is waiting for this, so it must not be able to
    # make somebody who IS waiting answer busy (audit F7).
    assert fetches[0]["background"] is True
    assert links == [{"action": music_worker.BROLL_LINK_PROXY_ACTION,
                      "path": str(placed), "proxy_path": proxy}]
    assert broll_standins.get(placed)["upgrade"] == broll_standins.UPGRADE_DONE


def test_an_upgrade_already_done_is_not_done_twice(tmp_path, placed):
    broll_standins.set_upgrade(placed, broll_standins.UPGRADE_DONE)

    result = broll_server.run_proxy_upgrade(
        _cfg(tmp_path), _mounts(tmp_path), "broll", str(placed),
        "cc/ff5/Proxy/clip.mov",
        fetcher=lambda *a, **k: pytest.fail("nothing to download"),
        caller=lambda *a, **k: pytest.fail("nothing to link"))

    assert result["ok"] is True


def test_a_download_in_flight_is_waited_for_not_abandoned(tmp_path, placed):
    states = [{"state": broll_fetch.STATE_DOWNLOADING, "progress": {}},
              {"state": broll_fetch.STATE_BUSY, "message": "another one first"},
              {"state": broll_fetch.STATE_DONE}]
    waits = []

    def fetcher(cfg, rel_path, dest, **kwargs):
        answer = states.pop(0)
        if answer["state"] == broll_fetch.STATE_DONE:
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            Path(dest).write_bytes(b"proxy")
        return answer

    result = broll_server.run_proxy_upgrade(
        _cfg(tmp_path), _mounts(tmp_path), "broll", str(placed),
        "cc/ff5/Proxy/clip.mov", fetcher=fetcher,
        caller=lambda *a, **k: {"ok": True, "message": "linked"},
        sleep=waits.append)

    assert result["ok"] is True
    assert waits == [broll_server.UPGRADE_POLL_SECONDS] * 2


def test_a_failed_download_is_failed_and_nothing_is_linked(tmp_path, placed):
    result = broll_server.run_proxy_upgrade(
        _cfg(tmp_path), _mounts(tmp_path), "broll", str(placed),
        "cc/ff5/Proxy/clip.mov",
        fetcher=lambda *a, **k: {"state": broll_fetch.STATE_FAILED,
                                 "message": "sftp: no such file"},
        caller=lambda *a, **k: pytest.fail("nothing to link"),
        sleep=lambda _s: None)

    assert result["ok"] is False
    entry = broll_standins.get(placed)
    assert entry["upgrade"] == broll_standins.UPGRADE_FAILED
    assert "sftp: no such file" in entry["upgrade_note"]


def test_a_download_that_never_finishes_ends_at_the_deadline(tmp_path, placed):
    clock = iter([0.0, 0.0, 10.0, 999.0])

    result = broll_server.run_proxy_upgrade(
        _cfg(tmp_path), _mounts(tmp_path), "broll", str(placed),
        "cc/ff5/Proxy/clip.mov",
        fetcher=lambda *a, **k: {"state": broll_fetch.STATE_DOWNLOADING},
        caller=lambda *a, **k: pytest.fail("nothing to link"),
        sleep=lambda _s: None, clock=lambda: next(clock),
        deadline_seconds=60.0)

    assert result["ok"] is False
    assert broll_standins.get(placed)["upgrade"] == broll_standins.UPGRADE_FAILED


def test_a_resolve_that_did_not_link_it_stays_pending(tmp_path, placed):
    """Resolve closed, or on another project. The file is on disk now, so
    the next cycle is all this needs -- which is why the state is persisted
    at all."""
    def fetcher(cfg, rel_path, dest, **kwargs):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"proxy")
        return {"state": broll_fetch.STATE_DONE}

    result = broll_server.run_proxy_upgrade(
        _cfg(tmp_path), _mounts(tmp_path), "broll", str(placed),
        "cc/ff5/Proxy/clip.mov", fetcher=fetcher,
        caller=lambda *a, **k: {"ok": False, "error": "no project is open in Resolve"},
        sleep=lambda _s: None)

    assert result["ok"] is False
    entry = broll_standins.get(placed)
    assert entry["upgrade"] == broll_standins.UPGRADE_PENDING
    assert "no project is open" in entry["upgrade_note"]


def test_a_pending_upgrade_survives_a_restart_and_is_retried(tmp_path, placed):
    """The ledger is the memory: a fresh process reads the same file and the
    relink cycle starts what is owed."""
    proxy = _archive(tmp_path, "cc", "ff5", "Proxy", "clip.mov")
    proxy.parent.mkdir(parents=True, exist_ok=True)
    proxy.write_bytes(b"the editing proxy, downloaded before the restart")
    broll_standins.configure(broll_standins.default_state_path())
    broll_standins.configure(tmp_path / "state" / "broll_standins.json")

    assert [entry["local_path"] for entry in broll_standins.pending_upgrades()] \
        == [str(placed)]

    started = []
    resumed = broll_server.resume_pending_upgrades(
        _cfg(tmp_path), _mounts(tmp_path), starter=lambda fn: started.append(fn))

    assert resumed == [str(placed)]
    assert len(started) == 1


def test_resume_skips_an_upgrade_that_is_already_done(tmp_path, placed):
    broll_standins.set_upgrade(placed, broll_standins.UPGRADE_DONE)

    assert broll_server.resume_pending_upgrades(
        _cfg(tmp_path), _mounts(tmp_path),
        starter=lambda fn: pytest.fail("nothing is owed")) == []


def test_a_thread_that_cannot_start_leaves_the_row_pending(tmp_path, placed):
    def boom(_fn):
        raise RuntimeError("can't start new thread")

    assert broll_server.start_proxy_upgrade(
        _cfg(tmp_path), _mounts(tmp_path), "broll", str(placed),
        "cc/ff5/Proxy/clip.mov", starter=boom) is False
    assert broll_standins.get(placed)["upgrade"] == broll_standins.UPGRADE_PENDING


# ---------------------------------------------------------------------------
# The worker action (music_worker.BROLL_LINK_PROXY_ACTION)
# ---------------------------------------------------------------------------


class _Clip:
    def __init__(self, path):
        self._props = {"File Path": path}

    def GetClipProperty(self, key=None):
        return self._props if key is None else self._props.get(key)

    def GetName(self):
        return "clip.mov"


class _Folder:
    def __init__(self, clips):
        self._clips = clips

    def GetClipList(self):
        return list(self._clips)

    def GetSubFolderList(self):
        return []


class _Pool:
    def __init__(self, clips):
        self._root = _Folder(clips)

    def GetRootFolder(self):
        return self._root


@pytest.fixture
def worker_pool(monkeypatch):
    """music_worker.connect() answering with a fake media pool."""
    def install(clips):
        monkeypatch.setattr(music_worker, "connect",
                            lambda: (object(), object(), _Pool(clips)))
        monkeypatch.setattr(music_worker, "canonical_fn_from_config",
                            lambda: None)
    return install


def test_the_worker_links_the_proxy_to_the_clip_at_that_path(worker_pool, monkeypatch):
    clip = _Clip(r"F:\Creators_Club\Assets\B-roll Archive\cc\clip.mov")
    worker_pool([clip])
    linked = []
    monkeypatch.setattr(music_worker.resolve_bridge, "link_proxy_media",
                        lambda item, path, source="manual": linked.append(
                            (item, path, source)) or {"ok": True, "message": "done"})

    out = music_worker.run_request({
        "action": music_worker.BROLL_LINK_PROXY_ACTION,
        "path": r"F:\Creators_Club\Assets\B-roll Archive\cc\clip.mov",
        "proxy_path": r"F:\Creators_Club\Assets\B-roll Archive\cc\Proxy\clip.mov",
    })

    assert out["ok"] is True
    assert linked[0][0] is clip
    # Through the bridge, so the save point and the undo journal happen.
    assert linked[0][2] == "broll_proxy_upgrade"


def test_a_clip_no_longer_in_the_pool_is_said_so_not_crashed_on(worker_pool):
    worker_pool([])

    out = music_worker.run_request({
        "action": music_worker.BROLL_LINK_PROXY_ACTION,
        "path": r"F:\x\clip.mov", "proxy_path": r"F:\x\Proxy\clip.mov"})

    assert out["ok"] is False
    assert out["reason"] == "not_in_pool"


def test_a_refusal_comes_back_as_an_error_the_upgrade_can_record(
        worker_pool, monkeypatch):
    clip = _Clip(r"F:\x\clip.mov")
    worker_pool([clip])
    monkeypatch.setattr(
        music_worker.resolve_bridge, "link_proxy_media",
        lambda item, path, source="manual": {
            "ok": False, "reason": "refused",
            "message": "Resolve wouldn't accept it as this clip's proxy"})

    out = music_worker.run_request({
        "action": music_worker.BROLL_LINK_PROXY_ACTION,
        "path": r"F:\x\clip.mov", "proxy_path": r"F:\x\Proxy\clip.mov"})

    assert out["ok"] is False
    assert "wouldn't accept" in out["error"]


# ---------------------------------------------------------------------------
# The second lane (audit F7)
# ---------------------------------------------------------------------------


def test_a_background_download_does_not_use_up_a_foreground_slot(tmp_path):
    """Two inserts in a row must not park the next Send to Resolve behind
    hundreds of MB of editing proxy."""
    cfg = _cfg(tmp_path)
    started = []

    def runner(job, cmd):
        started.append(job)

    for i in range(broll_fetch.MAX_CONCURRENT_BACKGROUND_FETCHES):
        answer = broll_fetch.poll_fetch(cfg, f"Proxy/p{i}.mov",
                                        str(tmp_path / f"p{i}.mov"),
                                        runner=runner, background=True)
        assert answer["state"] == broll_fetch.STATE_DOWNLOADING

    # The background lane is full...
    full = broll_fetch.poll_fetch(cfg, "Proxy/another.mov",
                                  str(tmp_path / "another.mov"),
                                  runner=runner, background=True)
    assert full["state"] == broll_fetch.STATE_BUSY

    # ...and the foreground lane has not noticed.
    for i in range(broll_fetch.MAX_CONCURRENT_FETCHES):
        answer = broll_fetch.poll_fetch(cfg, f"clip{i}.mov",
                                        str(tmp_path / f"clip{i}.mov"),
                                        runner=runner)
        assert answer["state"] == broll_fetch.STATE_DOWNLOADING


def test_a_foreground_download_does_not_use_up_the_background_slot(tmp_path):
    cfg = _cfg(tmp_path)

    for i in range(broll_fetch.MAX_CONCURRENT_FETCHES):
        broll_fetch.poll_fetch(cfg, f"clip{i}.mov", str(tmp_path / f"clip{i}.mov"),
                               runner=lambda job, cmd: None)

    answer = broll_fetch.poll_fetch(cfg, "Proxy/p.mov", str(tmp_path / "p.mov"),
                                    runner=lambda job, cmd: None, background=True)

    assert answer["state"] == broll_fetch.STATE_DOWNLOADING
