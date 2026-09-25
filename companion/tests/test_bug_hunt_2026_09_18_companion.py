"""The ninth fleet hunt's companion-side highs (2026-09-18).

One file per finding group, each test named for the behaviour it pins rather
than for the id, with the id in the docstring. Everything here runs with no
Resolve, no network and no rclone binary: the seams these findings live on are
exactly the ones the product injects.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from ccsync_companion import file_moves as file_moves_mod
from ccsync_companion.sync import server_locate
from ccsync_companion.sync.rclone_lane import DIRECTION_DOWN, RcloneLane


@pytest.fixture(autouse=True)
def _stub_rclone_available(monkeypatch):
    monkeypatch.setattr(
        "ccsync_companion.sync.rclone_lane.rclone_available",
        lambda rclone_path: (True, rclone_path),
    )


# -- res-companion-2: lane B follows a hand move, and the command that -------
#    follows must still relink Resolve
#
# The PRODUCER is lane B's own `_relocate_trashed` against a real
# ServerLocator answer; the RECEIVER is `file_moves.apply_move` with the same
# ledger object the companion wires to both. Nothing here is stubbed between
# them, because the defect was that the two ends never met.


def _locator(answer):
    def request(method, url, body, headers, timeout):
        return 200, answer
    return server_locate.ServerLocator(
        {"dashboard_url": "http://dash.example", "dashboard_token": "tok"},
        request_fn=request)


def _lane_b(tmp_path, ledger, *, projects, answer):
    (tmp_path / "local").mkdir(parents=True, exist_ok=True)
    lane = RcloneLane(
        direction=DIRECTION_DOWN,
        local_root=str(tmp_path / "local"),
        remote="nas",
        remote_root="Creators_Club",
        state_dir=tmp_path / "state",
        locator=_locator(answer),
        project_rel_fn=projects.get,
        on_relocated=ledger.record_relocation,
    )
    return lane


def _move(**over):
    move = {
        "id": 41,
        "from_project_rel": "2026/CCT/Season 1", "from_rel": "Proxy/gold.mp4",
        "to_project_rel": "2026/FF5/Talent Gap", "to_rel": "Interviewees/Proxy/gold.mp4",
        "is_dir": False, "requested_by": "owen",
    }
    move.update(over)
    return move


def _follow_the_move(tmp_path, ledger):
    """Lane B's half: the file is in this pass's trash and the server says it
    now lives under FF5, so lane B renames it there itself."""
    lane = _lane_b(
        tmp_path, ledger,
        projects={"cct": "Projects/2026/CCT/Season 1",
                  "ff5": "Projects/2026/FF5/Talent Gap"},
        answer={"walked": True, "as_of": "2026-09-18T10:00:00Z", "files": [
            {"name": "gold.mp4", "size": 7, "found": [
                {"project_slug": "ff5",
                 "rel_path": "Interviewees/Proxy/gold.mp4"}]}]},
    )
    backup = Path(lane.local_root) / ".ccsync-trash" / "20260918-100000"
    trashed = backup / "Proxy" / "gold.mp4"
    trashed.parent.mkdir(parents=True, exist_ok=True)
    trashed.write_bytes(b"x" * 7)
    lane._last_backup_dir = str(backup)
    lane._relocate_trashed("Projects/2026/CCT/Season 1")
    dest = (Path(lane.local_root) / "Projects/2026/FF5/Talent Gap"
            / "Interviewees" / "Proxy" / "gold.mp4")
    assert dest.is_file(), "lane B did not follow the move - the test is not set up"
    return lane


def test_the_move_command_after_lane_b_followed_it_still_relinks_resolve(tmp_path):
    """res-companion-2: lane B renamed the local copy minutes before the
    dashboard's detection delivered the same move as a command. The command
    used to find nothing at the old path, answer ok with no paths, and app.py
    then skipped the Resolve relink and recorded the move as done - every clip
    under the moved folder Media Offline while the MOVES history said the
    machine had followed."""
    ledger = file_moves_mod.FileMoveLedger(tmp_path / "state")
    lane = _follow_the_move(tmp_path, ledger)

    ok, detail, paths = file_moves_mod.apply_move(
        _move(), str(lane.local_root), ledger=ledger)
    assert ok is True
    assert paths is not None, "no paths means app.py skips _relink_moved_result"
    old_local, new_local = paths
    assert old_local.endswith(os.path.join("Season 1", "Proxy", "gold.mp4"))
    assert Path(new_local).is_file()
    assert "proxy download" in detail  # ui-copy-4 (2026-09-25): was "lane B"


def test_a_machine_that_only_downloaded_the_file_still_says_nothing_moved(tmp_path):
    """The narrowing that keeps the resume honest: a machine which never held
    the old path, but which syncs the DESTINATION project and downloaded the
    file there, wrote no relocation note and must answer exactly as 0.9.74
    did. Otherwise every such machine claims to have made the move."""
    ledger = file_moves_mod.FileMoveLedger(tmp_path / "state")
    local_root = tmp_path / "local"
    dest = (local_root / "Projects/2026/FF5/Talent Gap"
            / "Interviewees" / "Proxy" / "gold.mp4")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"x" * 7)

    ok, detail, paths = file_moves_mod.apply_move(
        _move(), str(local_root), ledger=ledger)
    assert (ok, paths) == (True, None)
    assert detail == "nothing at the old path on this computer"  # ui-copy-4 (2026-09-25)


def test_the_relocation_note_ages_out(tmp_path):
    """The note is evidence about one pass, not a permanent claim: a move
    command that arrives a week later must not resume from it."""
    clock = {"t": 1000.0}
    ledger = file_moves_mod.FileMoveLedger(tmp_path / "state", now=lambda: clock["t"])
    ledger.record_relocation(str(tmp_path / "old.mp4"), str(tmp_path / "new.mp4"))
    assert ledger.relocation_to(str(tmp_path / "old.mp4"), str(tmp_path / "new.mp4"))
    clock["t"] += file_moves_mod.RELOCATION_MAX_AGE_SECONDS + 1
    assert not ledger.relocation_to(str(tmp_path / "old.mp4"), str(tmp_path / "new.mp4"))


def test_the_note_survives_a_restart_and_keeps_the_move_entries(tmp_path):
    """It is written into the file-move ledger, which the companion reloads at
    start - a note only in memory would be lost to exactly the restart this
    feature has to survive."""
    ledger = file_moves_mod.FileMoveLedger(tmp_path / "state")
    ledger.record(_move(), True, "moved")
    ledger.record_relocation(str(tmp_path / "old.mp4"), str(tmp_path / "new.mp4"))
    reopened = file_moves_mod.FileMoveLedger(tmp_path / "state")
    assert reopened.entry(41) is not None
    assert reopened.relocation_to(str(tmp_path / "old.mp4"), str(tmp_path / "new.mp4"))


# -- comp-resolve-1: the stand-in geometry refresh must actually happen ------


class _FakeClip:
    """A media pool item with the two properties replace_clip reads.

    ReplaceClip re-reads the file, which is the whole mechanism: here that is
    modelled as the geometry changing on the call, the way Resolve behaves
    when the bytes under a clip were swapped.
    """

    def __init__(self, path, frames="1813", resolution="1920x1080",
                 becomes=("8534", "6144x3240"), raises=False):
        self.path = path
        self.frames, self.resolution = frames, resolution
        self.becomes, self.raises = becomes, raises
        self.replace_calls = []

    def GetClipProperty(self, *args):
        return {"File Path": self.path, "Frames": self.frames,
                "Resolution": self.resolution}

    def GetName(self):
        return "clip.mov"

    def ReplaceClip(self, path):
        self.replace_calls.append(path)
        if self.raises:
            raise RuntimeError("fusionscript went away")
        if self.becomes is not None:
            self.frames, self.resolution = self.becomes
        return True


@pytest.fixture
def quiet_bridge(monkeypatch):
    """No save point, no journal, no live Resolve - and a loud failure if the
    refresh path reaches for any of them."""
    from ccsync_companion import resolve_bridge, resolve_journal

    monkeypatch.setattr(resolve_bridge.ui_state, "wait_while_menu_open",
                        lambda *a, **k: None)
    monkeypatch.setattr(resolve_bridge, "_before_mutation",
                        lambda source: pytest.fail(
                            "a refresh must not take a save point: old_path == "
                            "new_path, so there is nothing to roll back"))
    monkeypatch.setattr(resolve_journal, "record",
                        lambda *a, **k: pytest.fail(
                            "a refresh must not write an undo entry that undoes "
                            "nothing"))
    return resolve_bridge


ARCHIVE_CLIP = "P:\\Assets\\B-roll Archive\\cc\\ff5\\clip.mov"
LOCAL_ROOT = "F:\\Creators_Club"
PREFIX = "P:\\"


def test_the_refresh_really_calls_replace_clip_on_the_clips_own_path(quiet_bridge):
    """comp-resolve-1: phase 3 has one mechanism, ReplaceClip(<the same
    path>), and `replace_clip` short-circuited on exactly that with "Already
    linked" - so nothing was ever re-read, while the pass counted a refresh
    and spent an allow_automatic grant every 120 s."""
    clip = _FakeClip(ARCHIVE_CLIP)

    result = quiet_bridge.replace_clip(clip, ARCHIVE_CLIP, tries=1, force=True)

    assert clip.replace_calls == [ARCHIVE_CLIP]
    assert result["ok"] is True and result["changed"] is True


def test_without_force_the_short_circuit_is_exactly_as_it_was(quiet_bridge):
    """fixer.py and popup.py rely on it to avoid a needless save point."""
    clip = _FakeClip(ARCHIVE_CLIP)

    result = quiet_bridge.replace_clip(clip, ARCHIVE_CLIP, tries=1)

    assert clip.replace_calls == []
    assert result["ok"] is True and "Already linked" in result["message"]


def test_a_refresh_whose_replace_clip_raised_every_time_is_not_a_success(
        quiet_bridge):
    """The verifier's warning: with `force` the old success test (`after ==
    norm_new`) is vacuously true, so a forced call that failed every attempt
    would report success and the clip would be believed re-read."""
    clip = _FakeClip(ARCHIVE_CLIP, raises=True)

    result = quiet_bridge.replace_clip(clip, ARCHIVE_CLIP, tries=2, force=True)

    assert result["ok"] is False
    assert result.get("changed") is False


def test_a_refresh_that_changed_no_geometry_says_so(quiet_bridge):
    """Resolve took the call and nothing moved. Not a failure - but not a
    refresh either, and the caller has to be able to tell."""
    clip = _FakeClip(ARCHIVE_CLIP, becomes=None)

    result = quiet_bridge.replace_clip(clip, ARCHIVE_CLIP, tries=1, force=True)

    assert clip.replace_calls == [ARCHIVE_CLIP]
    assert result["ok"] is True and result["changed"] is False


def test_the_relink_pass_asks_for_the_forced_call():
    """apply_relinks is the only caller of the refresh, and it has to ask for
    `force` or the short-circuit answers it again."""
    from ccsync_companion import proxy_relink

    seen = {}
    op = {"media_pool_item": object(), "media_pool_uid": "uid-1",
          "clip_name": "clip.mov", "file_path": ARCHIVE_CLIP, "old_proxy": "",
          "new_proxy": None, "refresh": True, "reason": "refresh"}

    def replace_fn(item, file_path, *, force=False):
        seen["force"] = force
        return {"ok": True, "changed": True}

    result = proxy_relink.apply_relinks(
        [op], link_fn=lambda *a: pytest.fail("no proxy to link"),
        resolve_fn=lambda o: o["media_pool_item"], replace_fn=replace_fn)

    assert seen["force"] is True
    assert result["refreshed"] == 1


class _Stat2:
    def __init__(self, mtime=1.0, size=2):
        self.st_mtime, self.st_size = mtime, size


def test_a_refresh_that_changed_nothing_is_not_counted_and_not_asked_again():
    """comp-resolve-1's fourth condition: a refresh that changes nothing must
    not spend an allow_automatic grant every pass for ever."""
    from ccsync_companion import proxy_relink

    op = {"media_pool_item": object(), "media_pool_uid": "uid-1",
          "clip_name": "clip.mov", "file_path": ARCHIVE_CLIP, "old_proxy": "",
          "new_proxy": None, "refresh": True, "reason": "refresh"}

    result = proxy_relink.apply_relinks(
        [op], link_fn=lambda *a: pytest.fail("no proxy to link"),
        resolve_fn=lambda o: o["media_pool_item"],
        replace_fn=lambda item, file_path, *, force=False: {
            "ok": True, "changed": False},
        stat_fn=lambda p: _Stat2())

    assert result["refreshed"] == 0
    assert result["failed"] == 0
    assert proxy_relink.remembered_geometry_verdict(
        ARCHIVE_CLIP, lambda p: _Stat2()) is False


# -- comp-resolve-2: the cheap question first, and the answer remembered -----


@pytest.fixture(autouse=True)
def _clean_verdicts():
    from ccsync_companion import proxy_relink

    proxy_relink.reset_geometry_verdicts()
    yield
    proxy_relink.reset_geometry_verdicts()


def _disagrees(**kwargs):
    from ccsync_companion import proxy_relink

    exists = kwargs.pop("exists", lambda p: True)
    frames_fn = kwargs.pop("frames_fn", proxy_relink.stored_frames)
    count_frames_fn = kwargs.pop("count_frames_fn")
    return proxy_relink._geometry_disagrees(
        ARCHIVE_CLIP, {"frames": "1813"}, LOCAL_ROOT, PREFIX,
        frames_fn, count_frames_fn, exists, **kwargs)


def test_a_clip_that_agrees_is_probed_once_and_never_again():
    """comp-resolve-2: `ffprobe -count_packets` is a full demux with a 60 s
    timeout, serial, on the media-tree thread. On the wired rig the archive IS
    the pool and every original IS present, so this read the whole archive off
    the SMB share every 120 s, for ever."""
    asked = []

    def count(path):
        asked.append(path)
        return 1813

    for _pass in range(5):
        assert _disagrees(count_frames_fn=count,
                          stat_fn=lambda p: _Stat2()) is False
    assert len(asked) == 1


def test_a_file_whose_bytes_changed_is_asked_again():
    """The memory is keyed on (mtime, size): the bytes changing is the whole
    event this feature exists to notice, so the verdict can never go stale
    silently."""
    asked = []
    current = {"stat": _Stat2(1.0, 2)}

    def count(path):
        asked.append(path)
        return 1813

    assert _disagrees(count_frames_fn=count,
                      stat_fn=lambda p: current["stat"]) is False
    current["stat"] = _Stat2(9.0, 400)
    assert _disagrees(count_frames_fn=count,
                      stat_fn=lambda p: current["stat"]) is False
    assert len(asked) == 2


def test_the_header_estimate_answers_without_the_full_demux():
    """The cheap question first: duration x fps is one open of the header
    instead of a demux of every packet in a 2 GB file."""
    def count(path):
        pytest.fail("the exact count must not be paid when the header agrees")

    assert _disagrees(count_frames_fn=count,
                      header_frames_fn=lambda p: 1814,
                      stat_fn=lambda p: _Stat2()) is False


def test_a_header_that_disagrees_still_pays_for_the_exact_count():
    asked = []
    assert _disagrees(count_frames_fn=lambda p: asked.append(p) or 8534,
                      header_frames_fn=lambda p: 8530,
                      stat_fn=lambda p: _Stat2()) is True
    assert asked == [ARCHIVE_CLIP]


def test_the_stand_in_ledger_answers_free_of_charge():
    """A path the ledger has an entry for whose file is no longer the size we
    placed IS a replaced stand-in, and no probe of any kind is needed."""
    assert _disagrees(
        count_frames_fn=lambda p: pytest.fail("no probe may run"),
        header_frames_fn=lambda p: pytest.fail("no probe may run"),
        is_stale_fn=lambda p: True,
        stat_fn=lambda p: _Stat2()) is True


def test_the_watchdog_heartbeat_is_stamped_per_clip_not_per_pass():
    """A serial run of ffprobes over a slow share looks exactly like a wedged
    thread to LaneWatchdog, which restarts it mid-probe - so neither the
    library walk nor the relink ever completes."""
    beats = []
    _disagrees(count_frames_fn=lambda p: 8534, header_frames_fn=lambda p: None,
               on_probe=lambda: beats.append(1), stat_fn=lambda p: _Stat2())
    assert beats, "no heartbeat was stamped around the probe"


# ---------------------------------------------------------------------------
# wire-1: a non-409 refusal of /items/{uid}/uploaded
# ---------------------------------------------------------------------------
#
# The RECEIVER is the real `_pump_uploads`; the PRODUCER's body is the shape
# `broll/web/app/ingest_batches.py` raises at :1141 and :1157 --
# `HTTPException(400, {"detail": <sentence>, "reason": <word>})`, which
# FastAPI serialises as {"detail": {...}}. `broll/web/tests/test_fleet_ingest.py`
# pins that shape from the server's side, so the two halves cannot drift.

import sys as _sys                                                  # noqa: E402
from pathlib import Path as _Path                                   # noqa: E402

_sys.path.insert(0, str(_Path(__file__).resolve().parent))

from ccsync_companion import broll_ingest                           # noqa: E402
from test_broll_ingest import (FakeQueue, FakeServer,               # noqa: E402
                               make_ingestor, stage_one_clip)

WRONG_EDIT_PROXY = {"detail": {
    "detail": "the editing proxy must be creators/2026-08-18 ingest/Proxy/A001.mov",
    "reason": "wrong_edit_proxy"}}


def _uploading_item(tmp_path, server):
    ing = make_ingestor(tmp_path, server=server, queue=FakeQueue())
    staging = stage_one_clip(ing, tmp_path)
    ing.run("b" * 32, staging, "foreground")
    return ing, ing._batch["items"][0]


def test_a_refusal_no_retry_can_fix_ends_the_item_and_says_why(tmp_path):
    """wire-1: `_pump_uploads` handled 200 and 409 and LOGGED everything else.
    The item kept `uploading` with every rel landed, so each pump recomputed
    `missing = []` and posted the identical body again - no attempt counter,
    no ceiling, the batch lease heartbeated the whole time, and this machine
    409ing every later drop. The server grew its first non-409 refusals of
    this route this week, and the companion could not see them."""
    server = FakeServer()
    server.uploaded_status = 400
    server.uploaded_body = WRONG_EDIT_PROXY
    ing, item = _uploading_item(tmp_path, server)

    for _ in range(3):
        ing.tick()

    assert item["stage"] == broll_ingest.ITEM_FAILED
    assert "editing proxy must be" in item["error"]
    assert server.released(), "a terminal item has to release its batch"


def test_a_server_that_is_merely_busy_is_retried_and_then_ended(tmp_path):
    """wire-2 is deliberately NOT in scope, so a 5xx must stay retryable: the
    mounted b-roll app answers 500 where the parent answers 503 for a busy
    database, and treating that as terminal would only move the loss."""
    server = FakeServer()
    server.uploaded_status = 503
    server.uploaded_body = {"detail": "the dashboard's database is busy; try again"}
    ing, item = _uploading_item(tmp_path, server)

    ing.tick()
    assert item["stage"] == broll_ingest.ITEM_UPLOADING, "a 503 is the moment, not the clip"
    assert 0 < int(item["upload_attempts"]) < broll_ingest.MAX_UPLOAD_ATTEMPTS

    for _ in range(broll_ingest.MAX_UPLOAD_ATTEMPTS + 2):
        ing.tick()

    # ...but it does not wait for ever either.
    assert item["stage"] == broll_ingest.ITEM_FAILED
    assert server.released()


def test_the_happy_path_is_untouched(tmp_path):
    server = FakeServer()
    ing, item = _uploading_item(tmp_path, server)

    for _ in range(3):
        ing.tick()

    assert item["stage"] == broll_ingest.ITEM_LIVE
    assert not item.get("upload_attempts")
