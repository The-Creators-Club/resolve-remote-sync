"""Phase 3: which file Send to Resolve downloads, imports and links.

The decision table is docs/BROLL_PROXY_TIERS_PLAN.md section 6, and this file
is that table plus the wiring around it (2026-09-17). Nothing here needs a
live Resolve, ffmpeg or a NAS: the insert's `fetcher` and `caller` seams and
the ledger's own path are all injected.
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


def _tiers(preview_rel="cc/ff5/Proxy/clip.mp4", edit_proxy_rel="cc/ff5/Proxy/clip.mov",
           weight=False, original_rel="cc/ff5/clip.mov", geometry=None,
           from_page=True):
    return {"preview_rel": preview_rel, "edit_proxy_rel": edit_proxy_rel,
            "original_is_edit_weight": weight, "original_rel": original_rel,
            "geometry": geometry, "from_page": from_page}


# ---------------------------------------------------------------------------
# The table itself (pure)
# ---------------------------------------------------------------------------


def test_the_original_on_disk_is_imported_and_nothing_is_linked():
    plan = broll_server.plan_insert(True, False, _tiers(), wired=False)

    assert plan["action"] == broll_server.PLAN_IMPORT_ORIGINAL
    assert plan["fetch_rel"] is None
    assert plan["insert_rel"] is None
    # The 540p preview is no longer offered as this clip's proxy: the file
    # under the clip IS the quality (plan section 6, wired/remote rows).
    assert plan["upgrade_rel"] is None


def test_a_ledgered_stand_in_is_imported_where_it_lies_and_still_owes_its_proxy():
    """It counts as absent for "is the original here", but it is already
    placed, so the answer is to import that path -- and the upgrade may run."""
    plan = broll_server.plan_insert(True, True, _tiers(), wired=False)

    assert plan["action"] == broll_server.PLAN_IMPORT_ORIGINAL
    assert plan["upgrade_rel"] == "cc/ff5/Proxy/clip.mov"


def test_an_edit_weight_original_downloads_the_top_slot_exactly_as_today():
    plan = broll_server.plan_insert(False, False, _tiers(weight=True), wired=False)

    assert plan["action"] == broll_server.PLAN_FETCH_ORIGINAL
    assert plan["fetch_rel"] is None


def test_an_unknown_weight_with_no_editing_proxy_is_todays_behaviour():
    """Every row indexed before the bitrate column answers null. With no
    editing proxy to prove the server judged it heavy, the safe answer is the
    one that has always worked."""
    plan = broll_server.plan_insert(
        False, False, _tiers(weight=None, edit_proxy_rel=None), wired=False)

    assert plan["action"] == broll_server.PLAN_FETCH_ORIGINAL


def test_an_unknown_weight_with_an_editing_proxy_the_page_named_is_heavy():
    """Only an original judged heavier than edit weight ever gets a `.mov`
    made for it (wave B), so the null there is an old row, not a real
    "cannot tell"."""
    plan = broll_server.plan_insert(False, False, _tiers(weight=None), wired=False)

    assert plan["action"] == broll_server.PLAN_FETCH_STANDIN


def test_the_stem_conventions_guess_is_not_evidence_of_weight():
    """No insert object means the page never looked: `Proxy/<stem>.mov` is
    what the convention would be called, not a file anybody saw."""
    plan = broll_server.plan_insert(
        False, False, _tiers(weight=None, from_page=False), wired=False)

    assert plan["action"] == broll_server.PLAN_FETCH_ORIGINAL


@pytest.mark.parametrize("ext", [".braw", ".r3d", ".crm", ".BRAW"])
def test_a_camera_raw_original_gets_a_preview_only_insert(ext):
    """Resolve reads those with its own decoder: a renamed H.264 is not one,
    so the clip lands at the PREVIEW's path instead (spike, section 3)."""
    plan = broll_server.plan_insert(
        False, False, _tiers(original_rel=f"cc/ff5/clip{ext}"), wired=False)

    assert plan["action"] == broll_server.PLAN_PREVIEW_ONLY
    assert plan["fetch_rel"] == "cc/ff5/Proxy/clip.mp4"
    assert plan["insert_rel"] == "cc/ff5/Proxy/clip.mp4"
    assert plan["upgrade_rel"] is None


def test_a_heavy_ordinary_container_gets_the_stand_in():
    plan = broll_server.plan_insert(False, False, _tiers(), wired=False)

    assert plan["action"] == broll_server.PLAN_FETCH_STANDIN
    assert plan["fetch_rel"] == "cc/ff5/Proxy/clip.mp4"
    # Imported at the ORIGINAL's own path: that is what keeps the project
    # right for the wired rig that holds the real file.
    assert plan["insert_rel"] is None
    assert plan["upgrade_rel"] == "cc/ff5/Proxy/clip.mov"


def test_a_heavy_original_with_no_known_preview_falls_back_to_the_original():
    plan = broll_server.plan_insert(
        False, False, _tiers(preview_rel=None), wired=False)

    assert plan["action"] == broll_server.PLAN_FETCH_ORIGINAL


def test_a_wired_rig_never_gets_a_stand_in():
    """Its tree IS the server's tree: a file missing there is missing at the
    source, and today's "is the share mounted?" is the right answer."""
    plan = broll_server.plan_insert(False, False, _tiers(), wired=True)

    assert plan["action"] == broll_server.PLAN_FETCH_ORIGINAL


@pytest.mark.parametrize("cfg,wired", [
    ({"mode": "base", "local_root": "F:/tree", "canonical_prefix": "P:\\"}, True),
    ({"mode": "editor", "local_root": "P:\\", "canonical_prefix": "P:\\"}, True),
    ({"mode": "editor", "local_root": "p:/", "canonical_prefix": "P:\\"}, True),
    ({"mode": "editor", "local_root": "F:/tree", "canonical_prefix": "P:\\"}, False),
    ({"mode": "editor", "local_root": "", "canonical_prefix": "P:\\"}, False),
    ({}, False),
])
def test_wired_is_the_computers_own_setting_or_a_tree_that_is_the_prefix(cfg, wired):
    assert broll_server._is_wired(cfg) is wired


# ---------------------------------------------------------------------------
# The wiring: which file is fetched, where to, and when the ledger is written
# ---------------------------------------------------------------------------


def _editor_cfg(tmp_path):
    return {
        "local_root": str(tmp_path),
        "mode": "editor",
        "canonical_prefix": "P:\\",
        "remote": "creators_club_sftp",
        "remote_root": "/mnt/tank/creators_club",
        "rclone_path": "rclone",
    }


def _body(rel="cc/ff5/clip.mov", insert=None):
    body = {"share": "broll", "rel_path": rel, "in_frame": 0, "out_frame": 10,
            "mode": "append"}
    if insert is not None:
        body["insert"] = insert
    return body


def _page_insert(**overrides):
    data = {
        "original_rel": "cc/ff5/clip.mov",
        "preview_rel": "cc/ff5/Proxy/clip.mp4",
        "edit_proxy_rel": "cc/ff5/Proxy/clip.mov",
        "original_is_edit_weight": False,
        "geometry": {"width": 6064, "height": 3424, "fps": 30.0,
                     "frames": 1813, "start_tc": "12:09:12:22"},
    }
    data.update(overrides)
    return data


def _archive(tmp_path, *parts):
    return tmp_path.joinpath("Assets", "B-roll Archive", *parts)


@pytest.fixture
def lands(tmp_path):
    """A fetcher that lands the file it is asked for and records the call."""
    calls = []

    def fetcher(ccsync_cfg, rel_path, dest, **kwargs):
        calls.append({"rel": rel_path, "dest": dest, **kwargs})
        target = Path(dest)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"preview bytes")
        return {"state": broll_fetch.STATE_DONE}

    fetcher.calls = calls
    return fetcher


@pytest.fixture
def worker():
    """The one-shot Resolve child, replaced by a recorder."""
    calls = []

    def caller(action, **kwargs):
        calls.append({"action": action, **kwargs})
        return {"ok": True, "message": "Inserted clip.mov (10 frames)"}

    caller.calls = calls
    return caller


def test_the_stand_in_fetches_the_preview_to_the_originals_own_path(
        tmp_path, lands, worker, monkeypatch):
    monkeypatch.setattr(broll_server, "start_proxy_upgrade",
                        lambda *a, **k: True)
    cfg = _editor_cfg(tmp_path)
    mounts = broll_server.resolve_mounts({}, cfg)

    status, body = broll_server.build_insert_response(
        _body(insert=_page_insert()), mounts, ccsync_cfg=cfg,
        fetcher=lands, caller=worker)

    assert status == 200 and body["ok"] is True
    assert lands.calls[0]["rel"] == "cc/ff5/Proxy/clip.mp4"
    assert lands.calls[0]["dest"] == str(_archive(tmp_path, "cc", "ff5", "clip.mov"))
    # ...and THAT path is what Resolve imported: the clip's File Path is the
    # canonical original.
    assert worker.calls[0]["action"] == music_worker.BROLL_INSERT_ACTION
    assert worker.calls[0]["path"] == str(_archive(tmp_path, "cc", "ff5", "clip.mov"))


def test_the_ledger_is_written_before_the_import(tmp_path, lands, monkeypatch):
    """A stand-in Resolve has already imported and the ledger does not know
    about is the failure the ledger exists to prevent."""
    monkeypatch.setattr(broll_server, "start_proxy_upgrade", lambda *a, **k: True)
    cfg = _editor_cfg(tmp_path)
    mounts = broll_server.resolve_mounts({}, cfg)
    dest = str(_archive(tmp_path, "cc", "ff5", "clip.mov"))
    seen = {}

    def caller(action, **kwargs):
        seen["ledgered_at_import_time"] = broll_standins.is_standin(dest)
        return {"ok": True, "message": "inserted"}

    broll_server.build_insert_response(
        _body(insert=_page_insert()), mounts, ccsync_cfg=cfg,
        fetcher=lands, caller=caller)

    assert seen["ledgered_at_import_time"] is True
    entry = broll_standins.get(dest)
    assert entry["preview_rel"] == "cc/ff5/Proxy/clip.mp4"
    assert entry["edit_proxy_rel"] == "cc/ff5/Proxy/clip.mov"
    assert entry["geometry"]["frames"] == 1813
    assert entry["upgrade"] == broll_standins.UPGRADE_PENDING


def test_a_failed_fetch_records_no_stand_in(tmp_path, worker):
    cfg = _editor_cfg(tmp_path)
    mounts = broll_server.resolve_mounts({}, cfg)

    status, body = broll_server.build_insert_response(
        _body(insert=_page_insert()), mounts, ccsync_cfg=cfg,
        fetcher=lambda *a, **k: {"state": broll_fetch.STATE_FAILED,
                                 "message": "sftp: permission denied"},
        caller=worker)

    assert status == 200 and body["ok"] is False
    assert "couldn't sync the clip from the NAS" in body["message"]
    assert broll_standins.all() == []
    assert worker.calls == []


def test_a_download_in_flight_answers_the_page_the_shape_it_understands(
        tmp_path, worker):
    cfg = _editor_cfg(tmp_path)
    mounts = broll_server.resolve_mounts({}, cfg)

    status, body = broll_server.build_insert_response(
        _body(insert=_page_insert()), mounts, ccsync_cfg=cfg,
        fetcher=lambda *a, **k: {"state": broll_fetch.STATE_DOWNLOADING,
                                 "progress": {"percent": 40}},
        caller=worker)

    assert status == 200
    assert body["state"] == "downloading"
    assert "40%" in body["message"]
    # comp-broll-tiers-1 (2026-09-18): the intent row is ALREADY there. This
    # assertion used to read `broll_standins.all() == []`, which pinned the
    # defect: the download runs on a daemon thread with no callback, so a page
    # that stops polling left the preview's bytes at the original's name with
    # nothing in the ledger. The row carries no size yet (nothing has landed),
    # and `_entry_is_stale` reads that as "still a stand-in".
    (entry,) = broll_standins.all()
    assert entry["local_path"] == str(_archive(tmp_path, "cc", "ff5", "clip.mov"))
    assert entry["size"] is None and entry["upgrade"] is None
    assert broll_standins.is_standin(entry["local_path"]) is True


def test_a_download_that_finishes_after_the_page_gave_up_is_still_ledgered(
        tmp_path, worker):
    """comp-broll-tiers-1 / res-companion-1: the editor closes the tab (or
    switches to Resolve, or the companion restarts) after the "syncing 40%"
    toast, and the rclone job finishes on its own. Nothing polls again, so
    nothing reaches the `state == done` branch that used to be the ledger's
    only writer - and the file lands under the ORIGINAL's 6K name holding the
    1080p preview's bytes. The next Send to Resolve then imports it as the
    original for ever, and a render on this machine renders the preview."""
    cfg = _editor_cfg(tmp_path)
    mounts = broll_server.resolve_mounts({}, cfg)
    dest = _archive(tmp_path, "cc", "ff5", "clip.mov")
    finish = {}

    def fetcher(ccsync_cfg, rel_path, dest_path, **kwargs):
        # The real job's shape: the answer comes back while the bytes are
        # still arriving, and the thread finishes them later.
        def land():
            Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
            Path(dest_path).write_bytes(b"the preview's bytes")
        finish["land"] = land
        return {"state": broll_fetch.STATE_DOWNLOADING, "progress": {"percent": 40}}

    broll_server.build_insert_response(
        _body(insert=_page_insert()), mounts, ccsync_cfg=cfg,
        fetcher=fetcher, caller=worker)
    finish["land"]()                       # the page is gone; the job is not

    assert broll_standins.is_standin(str(dest)) is True
    entry = broll_standins.get(str(dest))
    assert entry["preview_rel"] == "cc/ff5/Proxy/clip.mp4"
    assert entry["geometry"]["frames"] == 1813


def test_a_busy_lane_still_answers_busy_for_a_stand_in(tmp_path, worker):
    cfg = _editor_cfg(tmp_path)
    mounts = broll_server.resolve_mounts({}, cfg)

    status, body = broll_server.build_insert_response(
        _body(insert=_page_insert()), mounts, ccsync_cfg=cfg,
        fetcher=lambda *a, **k: {"state": broll_fetch.STATE_BUSY,
                                 "message": broll_fetch.BUSY_MESSAGE},
        caller=worker)

    assert status == 200
    assert body["ok"] is True and body["state"] == "busy"


def test_a_camera_raw_insert_lands_at_the_previews_own_path(
        tmp_path, lands, worker):
    cfg = _editor_cfg(tmp_path)
    mounts = broll_server.resolve_mounts({}, cfg)
    insert = _page_insert(original_rel="cc/ff5/clip.braw")

    status, body = broll_server.build_insert_response(
        _body(rel="cc/ff5/clip.braw", insert=insert), mounts, ccsync_cfg=cfg,
        fetcher=lands, caller=worker)

    assert status == 200 and body["ok"] is True
    preview = str(_archive(tmp_path, "cc", "ff5", "Proxy", "clip.mp4"))
    assert lands.calls[0]["rel"] == "cc/ff5/Proxy/clip.mp4"
    assert lands.calls[0]["dest"] == preview
    assert worker.calls[0]["path"] == preview
    # Nothing was lied about, so nothing is in the ledger.
    assert broll_standins.all() == []


def test_an_edit_weight_original_still_downloads_the_top_slot(
        tmp_path, lands, worker):
    cfg = _editor_cfg(tmp_path)
    mounts = broll_server.resolve_mounts({}, cfg)

    broll_server.build_insert_response(
        _body(insert=_page_insert(original_is_edit_weight=True)), mounts,
        ccsync_cfg=cfg, fetcher=lands, caller=worker)

    assert lands.calls[0]["rel"] == "cc/ff5/clip.mov"
    assert lands.calls[0]["dest"] == str(_archive(tmp_path, "cc", "ff5", "clip.mov"))
    assert broll_standins.all() == []


def test_an_original_already_on_disk_downloads_nothing(tmp_path, worker):
    cfg = _editor_cfg(tmp_path)
    mounts = broll_server.resolve_mounts({}, cfg)
    clip = _archive(tmp_path, "cc", "ff5", "clip.mov")
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"the real original")

    status, body = broll_server.build_insert_response(
        _body(insert=_page_insert()), mounts, ccsync_cfg=cfg,
        fetcher=lambda *a, **k: pytest.fail("nothing to download"),
        caller=worker)

    assert status == 200 and body["ok"] is True
    assert worker.calls[0]["path"] == str(clip)


def test_re_inserting_a_stand_in_imports_it_without_downloading_again(
        tmp_path, worker, monkeypatch):
    """The second Send to Resolve of the same clip: the lie is already on
    disk and in the ledger, so the insert is an ordinary import of that
    path."""
    upgrades = []
    monkeypatch.setattr(broll_server, "start_proxy_upgrade",
                        lambda *a, **k: upgrades.append(a) or True)
    cfg = _editor_cfg(tmp_path)
    mounts = broll_server.resolve_mounts({}, cfg)
    clip = _archive(tmp_path, "cc", "ff5", "clip.mov")
    clip.parent.mkdir(parents=True, exist_ok=True)
    clip.write_bytes(b"preview bytes")
    broll_standins.record(clip, share="broll", rel_path="cc/ff5/clip.mov",
                          edit_proxy_rel="cc/ff5/Proxy/clip.mov")

    status, body = broll_server.build_insert_response(
        _body(insert=_page_insert()), mounts, ccsync_cfg=cfg,
        fetcher=lambda *a, **k: pytest.fail("the stand-in is already here"),
        caller=worker)

    assert status == 200 and body["ok"] is True
    assert worker.calls[0]["path"] == str(clip)
    # ...and it still owes its editing proxy.
    assert upgrades


def test_the_upgrade_starts_only_after_a_successful_insert(
        tmp_path, lands, monkeypatch):
    started = []
    monkeypatch.setattr(broll_server, "start_proxy_upgrade",
                        lambda *a, **k: started.append(a[4]) or True)
    cfg = _editor_cfg(tmp_path)
    mounts = broll_server.resolve_mounts({}, cfg)

    broll_server.build_insert_response(
        _body(insert=_page_insert()), mounts, ccsync_cfg=cfg, fetcher=lands,
        caller=lambda action, **kw: {"ok": False, "message": "no timeline is open"})
    assert started == []

    broll_server.build_insert_response(
        _body(insert=_page_insert()), mounts, ccsync_cfg=cfg, fetcher=lands,
        caller=lambda action, **kw: {"ok": True, "message": "inserted"})
    assert started == ["cc/ff5/Proxy/clip.mov"]


def test_a_companion_with_no_page_object_behaves_exactly_as_before(
        tmp_path, lands, worker):
    """An older dashboard sends no `insert`: weight unknown, and the stem
    convention's `.mov` guess is not evidence the server judged it heavy,
    because the page never looked. Today's behaviour, unchanged."""
    cfg = _editor_cfg(tmp_path)
    mounts = broll_server.resolve_mounts({}, cfg)

    broll_server.build_insert_response(
        _body(), mounts, ccsync_cfg=cfg, fetcher=lands, caller=worker)

    assert lands.calls[0]["rel"] == "cc/ff5/clip.mov"
    assert broll_standins.all() == []
