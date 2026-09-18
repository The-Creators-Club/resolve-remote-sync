"""Regression tests for the 2026-09-18 fix pass, companion-media group (CR-284).

One test (or a small group) per finding, named after what the defect DID, not
after the function it lives in. Every one of these fails on the source as it
stood at 214869b + the first wave (CR-282); the ledger entry
`docs/bug-hunt-2026-09-18/ledger/companion-media.md` says which.

Nothing here talks to Resolve, the NAS, the network or a Tk dialog: the
media-pool objects are fakes with the three methods the bridge calls, and the
conftest's `_no_live_resolve` fixture stays in force throughout.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from ccsync_companion import broll_server
from ccsync_companion import broll_standins
from ccsync_companion import broll_vlm_sidecar
from ccsync_companion import music_clap_sidecar
from ccsync_companion import proxy_relink
from ccsync_companion import resolve_bridge
from ccsync_companion import timeline_cards_role as cards_role
from ccsync_companion import watcher as watcher_mod
from ccsync_companion import ytdl_executor as ex


@pytest.fixture(autouse=True)
def _own_ledger(tmp_path):
    """Every test gets its own stand-in ledger and no in-flight upgrades."""
    broll_standins.configure(tmp_path / "state" / "broll_standins.json")
    broll_server.reset_upgrades_in_flight()
    proxy_relink.reset_geometry_verdicts()
    proxy_relink.reset_refusals()
    proxy_relink.reset_fleet_standins()
    yield
    proxy_relink.reset_fleet_standins()
    broll_server.reset_upgrades_in_flight()
    broll_standins.configure(tmp_path / "state" / "broll_standins.json")


# ---------------------------------------------------------------------------
# CR-284A (comp-broll-tiers-2): one upgrade thread per stand-in, and a ceiling
# ---------------------------------------------------------------------------

def _standin(tmp_path, name="clip.mov", upgrade=broll_standins.UPGRADE_PENDING):
    path = tmp_path / name
    path.write_bytes(b"x" * 10)
    broll_standins.record(path, share="broll", rel_path=f"cc/{name}",
                          edit_proxy_rel=f"cc/Proxy/{Path(name).stem}.mov",
                          upgrade=upgrade, size=10)
    return path


def test_a_running_upgrade_is_not_started_again_by_the_next_cycle(tmp_path):
    """The relink cycle calls resume_pending_upgrades every 120 s for every
    row whose state is `pending` -- which is the state a RUNNING upgrade sits
    in. A 400 MB editing proxy over SFTP therefore stacked one thread per
    pass, and when the file landed every one of them called the Resolve
    worker: one child process per thread, for one clip."""
    path = _standin(tmp_path)
    started: list = []
    mounts = {"broll": str(tmp_path)}

    first = broll_server.resume_pending_upgrades(
        {}, mounts, starter=lambda fn: started.append(fn))
    second = broll_server.resume_pending_upgrades(
        {}, mounts, starter=lambda fn: started.append(fn))

    assert first == [str(path)]
    assert second == [], "the second cycle must not start a second thread"
    assert len(started) == 1


def test_an_upgrade_that_can_never_link_stops_costing_a_worker_child(tmp_path):
    """A row left `pending` because Resolve is open on another project (the
    deliberate branch in run_proxy_upgrade) had no attempt ceiling anywhere,
    so it cost one thread and one Resolve worker child every two minutes for
    the life of the machine."""
    path = _standin(tmp_path)
    for _ in range(broll_standins.UPGRADE_MAX_ATTEMPTS):
        broll_standins.set_upgrade(path, broll_standins.UPGRADE_PENDING,
                                   "Resolve is on another project",
                                   count_attempt=True)

    assert broll_standins.pending_upgrades() == []
    assert broll_server.resume_pending_upgrades({}, {"broll": str(tmp_path)},
                                                starter=lambda fn: None) == []
    # ...and it is VISIBLE rather than silent (CR-284N).
    owed = [e["local_path"] for e in broll_standins.given_up_upgrades()]
    assert owed == [str(path)]

    # An editor asking for that clip again hands the budget back.
    broll_server.start_proxy_upgrade({}, {"broll": str(tmp_path)}, "broll",
                                     str(path), "cc/Proxy/clip.mov",
                                     starter=lambda fn: None, asked_for=True)
    broll_server.reset_upgrades_in_flight()
    assert [e["local_path"] for e in broll_standins.pending_upgrades()] == [str(path)]


# ---------------------------------------------------------------------------
# CR-284B (comp-music-ytdl-jobs-1): the CLAP allow-list follows the feed
# ---------------------------------------------------------------------------

def test_the_clap_model_may_be_fetched_from_the_fleets_own_feed(monkeypatch):
    """The allow-list was four hard-coded GitHub patterns, while `feed_base`
    honours both `music_clap_feed_base` and the manifest's
    `release_feed_base`. Any fleet whose feed is not GitHub got a permanent
    refusal naming their own correctly configured host."""
    cfg = {"music_clap_feed_base": "https://dash.example.ts.net/feed"}
    url = "https://dash.example.ts.net/feed/music-clap-audio-1.onnx"

    assert music_clap_sidecar.host_allowed(url, cfg) is True
    # GitHub still works (this studio's own feed), and a host nobody
    # configured still does not.
    assert music_clap_sidecar.host_allowed(
        "https://github.com/o/r/releases/download/v1/x.onnx", cfg) is True
    assert music_clap_sidecar.host_allowed(
        "https://evil.test/x.onnx", cfg) is False
    # https stays a condition for a remote host...
    assert music_clap_sidecar.host_allowed(
        "http://dash.example.ts.net/feed/x.onnx", cfg) is False
    # ...and the override's own "a local directory server" is honoured.
    assert music_clap_sidecar.host_allowed(
        "http://127.0.0.1:8000/x.onnx",
        {"music_clap_feed_base": "http://127.0.0.1:8000"}) is True


# ---------------------------------------------------------------------------
# CR-284D (comp-resolve-4): the SHIPPED refresh, with nothing injected
# ---------------------------------------------------------------------------

class FakeClip:
    """The three calls replace_clip makes, and nothing else."""

    def __init__(self, path: str, frames: str = "1000",
                 after_frames: str | None = None):
        self.path = path
        self.frames = frames
        self.after_frames = after_frames
        self.replaced: list[str] = []

    def GetClipProperty(self, *args):
        return {"File Path": self.path, "Frames": self.frames,
                "Resolution": "1920x1080", "Proxy": "None"}

    def GetName(self):
        return os.path.basename(self.path)

    def ReplaceClip(self, path):
        self.replaced.append(path)
        if self.after_frames is not None:
            self.frames = self.after_frames
        return True


def test_apply_relinks_default_replace_fn_really_calls_replace_clip(tmp_path):
    """Every refresh test injected `replace_fn`, so the function app.py
    actually gets -- `resolve_bridge.replace_clip` -- was exercised nowhere,
    and it was the half that was broken. This calls apply_relinks with NO
    replace_fn: the real one runs, against a fake media pool item."""
    media = tmp_path / "clip.mov"
    media.write_bytes(b"x")
    clip = FakeClip(str(media), frames="1000", after_frames="6000")
    op = {"media_pool_item": clip, "media_pool_uid": "u1", "clip_name": "clip",
          "file_path": str(media), "old_proxy": "", "new_proxy": None,
          "stored_frames": 1000, "refresh": True, "reason": "refresh"}

    result = proxy_relink.apply_relinks(
        [op], link_fn=lambda item, path: {"ok": True},
        resolve_fn=lambda o: o["media_pool_item"])

    assert clip.replaced == [str(media)], "the shipped default never re-read the file"
    assert result["refreshed"] == 1


# ---------------------------------------------------------------------------
# CR-284E (proxy-tiers-1): the insert stops attaching the 540p preview
# ---------------------------------------------------------------------------

class ProxyClip(FakeClip):
    def __init__(self, path: str):
        super().__init__(path)
        self.linked: list[str] = []

    def LinkProxyMedia(self, path):
        self.linked.append(path)
        return True


def _with_proxy(tmp_path, ext: str) -> tuple[Path, Path]:
    media = tmp_path / "shot.mov"
    media.write_bytes(b"the real original")
    proxy_dir = tmp_path / "Proxy"
    proxy_dir.mkdir()
    proxy = proxy_dir / f"shot{ext}"
    proxy.write_bytes(b"preview")
    return media, proxy


def test_an_insert_does_not_attach_the_preview_over_a_real_original(tmp_path, monkeypatch):
    """Phase 3's one change for existing clips was built in the 120 s relink
    pass only. Every insert still linked `Proxy/<stem>.mp4`, and the pass can
    never take it back (it skips a clip whose proxy IS working), so the
    editor cut at 540p under a full-quality original, permanently, on the
    machine the whole feature is for."""
    media, _proxy = _with_proxy(tmp_path, ".mp4")
    clip = ProxyClip(str(media))
    monkeypatch.setattr(resolve_bridge.resolve_journal, "record",
                        lambda *a, **k: None)

    resolve_bridge._attach_adjacent_proxy(clip, str(media))

    assert clip.linked == []


def test_a_stand_in_still_gets_its_preview_attached(tmp_path, monkeypatch):
    """The clip's own file IS the preview there, so nothing is taken away and
    the editing-proxy upgrade is what improves it."""
    media, proxy = _with_proxy(tmp_path, ".mp4")
    broll_standins.record(media, size=media.stat().st_size)
    clip = ProxyClip(str(media))
    monkeypatch.setattr(resolve_bridge.resolve_journal, "record",
                        lambda *a, **k: None)

    resolve_bridge._attach_adjacent_proxy(clip, str(media))

    assert clip.linked == [str(proxy)]


def test_the_editing_proxy_is_still_attached_unconditionally(tmp_path, monkeypatch):
    """The `.mov` arm is the editing proxy and is exactly what the plan's
    table says a machine holding the original should link."""
    media, proxy = _with_proxy(tmp_path, ".mov")
    clip = ProxyClip(str(media))
    monkeypatch.setattr(resolve_bridge.resolve_journal, "record",
                        lambda *a, **k: None)

    resolve_bridge._attach_adjacent_proxy(clip, str(media))

    assert clip.linked == [str(proxy)]


# ---------------------------------------------------------------------------
# CR-284F (proxy-tiers-2 = broll-1 = comp-broll-tiers-4 = wire-4)
# ---------------------------------------------------------------------------
#
# The producer is `broll/web/app/routes_api.py::_insert_object`. Its shape for
# a clip with no original beside the preview is pinned by that repo's
# `broll/web/tests/test_insert_target.py::test_the_preview_only_fallback_
# reports_no_original`: `original_rel` is an explicit null, `rel_path` falls
# back to the preview's own rel, and the editing proxy (when there is one) is
# still named. That object, verbatim, is what goes through the receiver here.

PREVIEW_REL = "Creators_Club/ff5/Proxy/clip.mp4"
WEB_OBJECT_NO_ORIGINAL = {
    "share": "broll",
    "original_rel": None,
    "preview_rel": PREVIEW_REL,
    "edit_proxy_rel": "Creators_Club/ff5/Proxy/clip.mov",
    "original_is_edit_weight": False,
    "geometry": {"width": 3840, "height": 2160, "fps": 25,
                 "frames": 500, "start_tc": "00:00:00:00"},
}


def test_a_clip_with_no_original_is_preview_only_and_ledgers_nothing():
    """`original_rel: null` is the detail route's ANSWER for a clip whose
    original is not in the archive -- the stem-diverged clips, and every clip
    ingested with "upload originals" off or whose original has not landed
    yet. The companion read it as "the page said nothing", mapped it back
    onto the posted rel (which IS the preview), and planned a STAND-IN: fetch
    the preview onto its own path and ledger that genuine, lane-B-managed
    file as a lie about a 6K original that does not exist. `is_standin` then
    answered True for ever, because its size never changes."""
    tiers = broll_server.derive_insert_paths(WEB_OBJECT_NO_ORIGINAL, PREVIEW_REL)
    assert tiers["original_known"] is False

    plan = broll_server.plan_insert(False, False, tiers, wired=False)
    assert plan["action"] == broll_server.PLAN_PREVIEW_ONLY
    assert plan["fetch_rel"] == PREVIEW_REL
    assert plan["insert_rel"] == PREVIEW_REL
    assert plan["upgrade_rel"] is None


def test_a_clip_with_a_real_original_still_gets_its_stand_in():
    """The other half of the table, unchanged: a heavy original that IS in
    the archive is still fetched as a stand-in at its own path."""
    obj = dict(WEB_OBJECT_NO_ORIGINAL, original_rel="Creators_Club/ff5/clip.mov")
    tiers = broll_server.derive_insert_paths(obj, "Creators_Club/ff5/clip.mov")
    assert tiers["original_known"] is True

    plan = broll_server.plan_insert(False, False, tiers, wired=False)
    assert plan["action"] == broll_server.PLAN_FETCH_STANDIN


# ---------------------------------------------------------------------------
# CR-284G (proxy-tiers-3): "could not look" is not "there is none"
# ---------------------------------------------------------------------------

def test_an_archive_the_server_could_not_read_falls_back_to_the_old_route():
    """An OSError listing the archive folder inside the container is
    indistinguishable on the wire from "this clip has no original", which is
    what turned a ten-minute mount hiccup into a permanent false stand-in
    ledger row. With `known: false` the companion judges nothing off that
    object and downloads the file the editor asked for, which is what it did
    before the tiers existed."""
    obj = dict(WEB_OBJECT_NO_ORIGINAL, known=False,
               original_rel="Creators_Club/ff5/clip.mov")
    tiers = broll_server.derive_insert_paths(obj, "Creators_Club/ff5/clip.mov")

    plan = broll_server.plan_insert(False, False, tiers, wired=False)

    assert plan["action"] == broll_server.PLAN_FETCH_ORIGINAL
    assert "could not read" in plan["why"]


# ---------------------------------------------------------------------------
# CR-284J (proxy-tiers-6): a stand-in only under a container it could be
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ext", [".mxf", ".avi", ".mkv"])
def test_a_container_the_preview_is_not_gets_the_preview_instead(ext):
    """The stand-in is the preview's ISO-BMFF bytes under the ORIGINAL's
    name. The guard was the camera-raw set alone while the indexer scans
    `.mxf`, `.avi` and `.mkv` too, so an MXF original got an MP4 wearing an
    `.mxf` name -- which Resolve's MXF path either refuses silently or
    imports with the wrong container's geometry, after the ledger row has
    already been written."""
    original = f"Creators_Club/ff5/clip{ext}"
    obj = dict(WEB_OBJECT_NO_ORIGINAL, original_rel=original)
    tiers = broll_server.derive_insert_paths(obj, original)

    plan = broll_server.plan_insert(False, False, tiers, wired=False)

    assert plan["action"] == broll_server.PLAN_PREVIEW_ONLY
    assert plan["fetch_rel"] == PREVIEW_REL


@pytest.mark.parametrize("ext", [".mov", ".mp4", ".m4v"])
def test_the_containers_the_spike_covers_still_get_a_stand_in(ext):
    original = f"Creators_Club/ff5/clip{ext}"
    obj = dict(WEB_OBJECT_NO_ORIGINAL, original_rel=original)
    tiers = broll_server.derive_insert_paths(obj, original)

    assert broll_server.plan_insert(False, False, tiers, wired=False)["action"] \
        == broll_server.PLAN_FETCH_STANDIN


# ---------------------------------------------------------------------------
# CR-284K (tests-1): the ffmpeg gate a release can insist on
# ---------------------------------------------------------------------------

def test_a_missing_ffmpeg_is_a_failure_when_the_release_says_so(monkeypatch):
    """Twenty media-job tests sat behind a bare `shutil.which` skipif with no
    escape hatch, and pytest exits 0 on a skip: on both companion CI jobs and
    both release runners they vanished, so jobs_media.py's argv could break
    and the build would still be published."""
    from conftest import require_ffmpeg_or_skip

    monkeypatch.setenv("CCSYNC_REQUIRE_FFMPEG", "1")
    with pytest.raises(pytest.fail.Exception) as caught:
        require_ffmpeg_or_skip("no ffmpeg here")
    assert "CCSYNC_REQUIRE_FFMPEG" in str(caught.value)
    assert not isinstance(caught.value, pytest.skip.Exception)

    monkeypatch.delenv("CCSYNC_REQUIRE_FFMPEG")
    with pytest.raises(pytest.skip.Exception):
        require_ffmpeg_or_skip("no ffmpeg here")


# ---------------------------------------------------------------------------
# CR-284L (wire-3 = dash-cards-8): a discarded push is not a healthy agent
# ---------------------------------------------------------------------------

def _cards_role(answer: dict):
    role = cards_role.TimelineCardsRole.__new__(cards_role.TimelineCardsRole)
    role._lock = threading.RLock()
    role._wall = time.time
    role._last_http_status = None
    role._last_error = ""
    role._last_poll_at = None
    role._not_attached = ""
    role._seen = None
    role._timeline = ""
    role._project = ""
    role._state = cards_role.STATE_RUNNING
    role._detail = "serving the page"
    role._threads = [threading.current_thread()]   # alive, so health() gets past the gate
    role._since = time.time()
    role._loop_error = ""
    role._machine_name = "EDIT-1"
    role.cfg = {"dashboard_url": "https://dash.example",
                "dashboard_token": "t" * 32}
    role._request = lambda method, url, body, headers, timeout: (200, answer)
    role._headers = lambda: {}
    return role


def test_a_push_the_dashboard_threw_away_is_not_reported_as_serving():
    """`/cards/agent/state` answers 200 with `{"error": ...}` when the editor
    is in no episode -- deliberately, because a 4xx would put the loops into
    backoff. The client judged on the STATUS alone, so `_note_traffic`
    recorded the pushed timeline and the tray, the role's health and the
    fleet grid all said "serving timeline X" while every sweep was dropped on
    the floor."""
    note = ("alex is not in a Timeline Cards episode on this dashboard - "
            "open one at /cards/ and this agent attaches to it")
    role = _cards_role({"error": note})

    role.call("/agent/state", {"state": {"timeline": "E1", "project": "FF5"}})

    assert role._timeline == "", "a discarded push is not traffic served"
    health, detail = role.health()
    assert detail == note
    # The transport IS healthy: nothing raised, and the poll clock moved.
    assert health == cards_role.HEALTH_RUNNING
    assert role._last_poll_at is not None


def test_an_answer_with_no_refusal_records_the_timeline_as_before():
    role = _cards_role({})
    role.call("/agent/state", {"state": {"timeline": "E1", "project": "FF5"}})
    assert role._timeline == "E1"
    assert role.health()[1] == "serving the page"


# ---------------------------------------------------------------------------
# CR-284N (comp-broll-tiers-5): the ledger is pruned, and a failure is visible
# ---------------------------------------------------------------------------

def test_an_entry_whose_file_has_been_gone_for_a_month_is_forgotten(tmp_path):
    """Entries were added and never removed except by a `forget()` nothing
    called, and `all()` re-reads and re-sorts the whole file on every
    pending_upgrades() poll from the 120 s cycle."""
    state = tmp_path / "state" / "broll_standins.json"
    ledger = broll_standins.configure(state)
    # Under the archive, which is the only place a stand-in can be: CR-288C
    # (2026-09-18b) only prunes while that tree is demonstrably present.
    archive = tmp_path / "tree" / "Assets" / "B-roll Archive"
    archive.mkdir(parents=True)
    gone = archive / "vanished.mov"
    here = archive / "here.mov"
    gone.write_bytes(b"x")
    here.write_bytes(b"x")
    ledger.record(gone, size=1)
    ledger.record(here, size=1)
    gone.unlink()

    # Still there: absence alone never retires a row (the module's rule).
    assert len(broll_standins.all()) == 2

    payload = json.loads(state.read_text(encoding="utf-8"))
    for entry in payload["standins"].values():
        if entry["local_path"] == str(gone):
            entry["placed_at"] = time.time() - broll_standins.PRUNE_AFTER_SECONDS - 60
    state.write_text(json.dumps(payload), encoding="utf-8")
    broll_standins.configure(state)

    kept = [e["local_path"] for e in broll_standins.all()]
    assert kept == [str(here)]


# ---------------------------------------------------------------------------
# CR-284O (comp-music-ytdl-jobs-3): the b-roll model gate is https too
# ---------------------------------------------------------------------------

def test_the_vlm_allow_list_refuses_plain_http():
    """The music sibling refuses a non-https URL first; this one tested the
    hostname alone, so the weaker of two gates doing the same job is the one
    that would ship the day these URLs become site-derived."""
    https = "https://huggingface.co/o/r/resolve/main/model.gguf"
    assert broll_vlm_sidecar.host_allowed(https) is True
    assert broll_vlm_sidecar.host_allowed(https.replace("https://", "http://")) is False


# ---------------------------------------------------------------------------
# CR-284Q (comp-music-ytdl-jobs-5): a None returncode is not success
# ---------------------------------------------------------------------------

class _Proc:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_a_conversion_that_reported_no_return_code_is_not_a_success(tmp_path, monkeypatch):
    """`int(getattr(proc, "returncode", 1) or 0)` maps None onto 0, which is
    the success branch, so a runner that returns before the child is reaped
    would deliver a half-written `.editready.mp4` into swap_in -- which
    renames the good original aside."""
    monkeypatch.setattr(ex, "_ffprobe_binary", lambda cfg: "ffprobe")
    monkeypatch.setattr(ex, "_ffmpeg_binary", lambda cfg: "ffmpeg")
    outdir = tmp_path / "out"
    outdir.mkdir()
    name = "Clip [abc].mp4"
    (outdir / name).write_bytes(b"the download")
    probe = {"streams": [{"codec_type": "video", "codec_name": "vp9",
                          "r_frame_rate": "24/1", "avg_frame_rate": "24/1"},
                         {"codec_type": "audio", "codec_name": "aac"}]}

    def run(argv, timeout=None, on_spawn=None, **kwargs):
        if "ffprobe" in argv[0]:
            return _Proc(0, stdout=json.dumps(probe))
        # ffmpeg: a file lands, and the runner cannot say how it went.
        Path(argv[-1]).write_bytes(b"half a file")
        return _Proc(None, stderr="")

    job = ex.DownloadJob(7, ex.Deps({}, run_fn=run))
    delivered, note, error = job._ensure_edit_ready(str(outdir), name, "abc")

    assert error, "a conversion that reported nothing must not read as done"
    assert delivered == name
    assert (outdir / name).read_bytes() == b"the download"


# ---------------------------------------------------------------------------
# CR-284R (comp-resolve-3 = res-companion-5): a refresh is remembered
# ---------------------------------------------------------------------------

def test_a_clip_that_will_not_converge_is_refreshed_once_not_for_ever(tmp_path):
    """A clip whose stored Frames never agree with its file after a real
    ReplaceClip -- an mp4 with an edit list, a file Resolve reads at another
    rate -- was re-planned every pass, each one spending one of the eight
    allow_automatic grants a day, so genuine proxy relinks were rate-limited
    out for the rest of it."""
    media = tmp_path / "clip.mov"
    media.write_bytes(b"x")
    calls: list = []

    def replace(item, path, force=False):
        calls.append(path)
        return {"ok": True, "changed": True, "message": "re-read"}

    op = {"media_pool_item": object(), "media_pool_uid": "u", "clip_name": "c",
          "file_path": str(media), "old_proxy": "", "new_proxy": None,
          "stored_frames": 1000, "refresh": True, "reason": "refresh"}

    for _ in range(3):
        proxy_relink.apply_relinks(
            [dict(op)], link_fn=lambda i, p: {"ok": True},
            resolve_fn=lambda o: o["media_pool_item"], replace_fn=replace)
        # The next pass asks the same question about a file whose bytes have
        # not changed and whose clip still believes 1000 frames.
        assert proxy_relink.remembered_geometry_verdict(
            str(media), stored=1000) is False

    assert len(calls) == 3  # apply_relinks runs what it is given...
    # ...and plan_relinks is what must stop giving it (the memory above is
    # exactly what _geometry_disagrees consults first).


# ---------------------------------------------------------------------------
# CR-284S (comp-resolve-5): a refresh-only pass says what it did
# ---------------------------------------------------------------------------

def test_a_pass_that_only_refreshed_does_not_report_nothing_to_do(tmp_path):
    """`refreshed` had one producer and no consumer: a pass that re-read 40
    clips from their own files -- phase 3's whole mechanism -- produced an
    empty message, so app.py logged "proxy relink: nothing to do"."""
    media = tmp_path / "clip.mov"
    media.write_bytes(b"x")
    op = {"media_pool_item": object(), "media_pool_uid": "u", "clip_name": "c",
          "file_path": str(media), "old_proxy": "", "new_proxy": None,
          "stored_frames": 1000, "refresh": True, "reason": "refresh"}

    result = proxy_relink.apply_relinks(
        [op], link_fn=lambda i, p: {"ok": True},
        resolve_fn=lambda o: o["media_pool_item"],
        replace_fn=lambda i, p, force=False: {"ok": True, "changed": True})

    assert result["refreshed"] == 1
    assert "re-read 1 clip(s)" in result["message"]


# ---------------------------------------------------------------------------
# CR-284T (comp-resolve-6): a refresh that drops the proxy puts it back
# ---------------------------------------------------------------------------

def test_a_refresh_that_blanked_the_proxy_re_attaches_it(tmp_path):
    """ReplaceClip is the API's re-import path. If it clears the clip's proxy
    attachment, the clip played its original (or went offline on a remote
    rig) until the next pass, which is 120 s away at best and behind
    allow_automatic's 900 s bar at worst."""
    media = tmp_path / "clip.mov"
    media.write_bytes(b"x")
    proxy = tmp_path / "Proxy" / "clip.mov"
    proxy.parent.mkdir()
    proxy.write_bytes(b"p")
    linked: list = []

    op = {"media_pool_item": object(), "media_pool_uid": "u", "clip_name": "c",
          "file_path": str(media), "old_proxy": str(proxy),
          "reattach_proxy": str(proxy), "new_proxy": None,
          "stored_frames": 1000, "refresh": True, "reason": "refresh"}

    proxy_relink.apply_relinks(
        [op], link_fn=lambda i, p: linked.append(p) or {"ok": True},
        resolve_fn=lambda o: o["media_pool_item"],
        replace_fn=lambda i, p, force=False: {"ok": True, "changed": True},
        proxy_state_fn=lambda item: "None")

    assert linked == [str(proxy)]


def test_a_refresh_that_left_the_proxy_alone_re_attaches_nothing(tmp_path):
    media = tmp_path / "clip.mov"
    media.write_bytes(b"x")
    proxy = tmp_path / "Proxy" / "clip.mov"
    proxy.parent.mkdir()
    proxy.write_bytes(b"p")
    linked: list = []

    op = {"media_pool_item": object(), "media_pool_uid": "u", "clip_name": "c",
          "file_path": str(media), "old_proxy": str(proxy),
          "reattach_proxy": str(proxy), "new_proxy": None,
          "stored_frames": 1000, "refresh": True, "reason": "refresh"}

    proxy_relink.apply_relinks(
        [op], link_fn=lambda i, p: linked.append(p) or {"ok": True},
        resolve_fn=lambda o: o["media_pool_item"],
        replace_fn=lambda i, p, force=False: {"ok": True, "changed": True},
        proxy_state_fn=lambda item: "1920x1080")

    assert linked == []


def test_a_refresh_plans_the_proxy_it_is_playing(tmp_path):
    """The other half: plan_relinks is what carries the path, and only for a
    clip whose proxy is working."""
    ops = proxy_relink.plan_relinks(
        [{"file_path": r"P:\Assets\B-roll Archive\cc\clip.mov",
          "media_pool_uid": "u", "clip_name": "clip",
          "proxy_path": r"P:\Assets\B-roll Archive\cc\Proxy\clip.mov",
          "proxy_state": "1920x1080", "frames": 1000}],
        local_root="P:\\", canonical_prefix="P:\\", is_windows=True,
        exists_fn=lambda p: True, is_standin_fn=lambda p: False,
        frames_fn=lambda item: item.get("frames"),
        count_frames_fn=lambda p: 6000,
        stat_fn=lambda p: os.stat_result((0, 0, 0, 0, 0, 0, 7, 0, 1.0, 0)))

    assert len(ops) == 1 and ops[0]["refresh"] is True
    assert ops[0]["reattach_proxy"].endswith("Proxy\\clip.mov")


# ---------------------------------------------------------------------------
# CR-284U (comp-resolve-7): the archive exemption is not re-asked every 3 s
# ---------------------------------------------------------------------------

def test_the_archive_exemption_is_remembered_across_polls():
    """The verdict was cached per POLL, and the poll is every 3 s. A remote
    rig with a 200-clip proxy-only b-roll timeline -- the designed steady
    state -- paid roughly a thousand filesystem probes every three seconds on
    the thread the popup and fixer latency depend on, for a diagnostic
    count."""
    asked: list = []
    w = watcher_mod.TimelineWatcher.__new__(watcher_mod.TimelineWatcher)
    w.local_root = "P:\\"
    w.canonical_prefix = "P:\\"
    w._archive_exempt_fn = lambda path: asked.append(path) or True
    w._exempt_memo = {}
    path = r"P:\Assets\B-roll Archive\cc\clip.mov"

    for _ in range(5):                       # five polls, five fresh caches
        assert w._archive_exempt(path, {}) is True

    assert len(asked) == 1


def test_the_exemption_memory_expires(monkeypatch):
    """Short on purpose: the answer flips when a proxy lands or is deleted,
    and a long memory would keep a genuinely missing clip out of the count."""
    asked: list = []
    w = watcher_mod.TimelineWatcher.__new__(watcher_mod.TimelineWatcher)
    w.local_root = "P:\\"
    w.canonical_prefix = "P:\\"
    w._archive_exempt_fn = lambda path: asked.append(path) or True
    w._exempt_memo = {}
    path = r"P:\Assets\B-roll Archive\cc\clip.mov"

    now = [1000.0]
    monkeypatch.setattr(watcher_mod.time, "monotonic", lambda: now[0])
    w._archive_exempt(path, {})
    now[0] += watcher_mod.EXEMPT_TTL_SECONDS + 1
    w._archive_exempt(path, {})

    assert len(asked) == 2


# ---------------------------------------------------------------------------
# CR-284W (tests-2): a malformed object has looked at nothing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("insert", [
    {"preview_rel": "../../etc/passwd"},
    {"geometry": "1920x1080"},
    {"share": "broll", "original_rel": "Creators_Club/x/clip.mov"},
])
def test_a_malformed_insert_object_does_not_count_as_the_dashboard_looking(insert):
    """`from_page = True` was set for ANY dict, before a field was read, and
    plan_insert reads it as the licence to treat a null weight beside a
    STEM-CONVENTION editing proxy as "the server judged this original heavy"
    -- i.e. to place a stand-in for a clip nobody ever weighed."""
    rel = "Creators_Club/x/clip.mov"
    tiers = broll_server.derive_insert_paths(insert, rel)
    if "preview_rel" in insert or "geometry" in insert:
        # those two DO carry a tier field; the object is still refused field
        # by field, which is the behaviour the old test pinned
        assert tiers["preview_rel"] == "Creators_Club/x/Proxy/clip.mp4"
    else:
        assert tiers["from_page"] is False
        plan = broll_server.plan_insert(False, False, tiers, wired=False)
        assert plan["action"] == broll_server.PLAN_FETCH_ORIGINAL


# ---------------------------------------------------------------------------
# CR-284Y (tests-4): the ledger really cannot raise
# ---------------------------------------------------------------------------

def test_a_value_json_cannot_encode_does_not_raise_and_does_not_poison(tmp_path):
    """The test that claimed to cover this replaced `_persist_locked` -- the
    exact function whose failure it was about -- with `lambda self: False`.
    The real thing catches OSError only, `json.dumps` is inside that try, and
    the bad entry was inserted into `_entries` BEFORE the persist, so every
    later record() in the process raised too and the file was never
    written."""
    state = tmp_path / "state" / "broll_standins.json"
    broll_standins.configure(state)
    bad = tmp_path / "bad.mov"
    good = tmp_path / "good.mov"
    bad.write_bytes(b"x")
    good.write_bytes(b"x")

    broll_standins.record(bad, geometry={"fps": object()}, size=1)
    broll_standins.record(good, size=1)

    assert [e["local_path"] for e in broll_standins.all()] == [str(good)]
    assert state.is_file()


def test_a_write_that_really_cannot_land_is_not_an_exception(tmp_path, monkeypatch):
    """And the OSError half, raised from the thing that raises it."""
    broll_standins.configure(tmp_path / "state" / "broll_standins.json")
    clip = tmp_path / "clip.mov"
    clip.write_bytes(b"x")

    def boom(*args, **kwargs):
        raise OSError("the disk is full")

    monkeypatch.setattr(os, "replace", boom)

    entry = broll_standins.record(clip, size=1)

    assert entry["local_path"] == str(clip)
    assert broll_standins.is_standin(clip) is False


# ---------------------------------------------------------------------------
# CR-284Z (broll-indexer-2 = proxy-tiers-7, owed by webapps-tools): the
# `frames` column is not a container's claim
# ---------------------------------------------------------------------------

def test_a_containers_frame_claim_is_cross_checked_against_its_duration():
    """`frames` decides an offline clip's LENGTH on a remote editor's
    timeline, and it was `nb_frames` verbatim -- which this module's own
    count_frames docstring calls a claim rather than a count. The indexer's
    twin got the same cross-check in the same pass; two producers of one wire
    field must agree about how confident it is."""
    from ccsync_companion import ffmpeg_tools

    # 10 s at 25 fps: 250 is the claim the duration agrees with.
    assert ffmpeg_tools._plausible_frames(250, 10.0, 25.0) == 250
    assert ffmpeg_tools._plausible_frames(251, 10.0, 25.0) == 251   # rounding
    assert ffmpeg_tools._plausible_frames(2, 10.0, 25.0) is None    # a lie
    # Nothing to check it against is not a reason to throw it away.
    assert ffmpeg_tools._plausible_frames(250, None, 25.0) == 250
    assert ffmpeg_tools._plausible_frames(0, 10.0, 25.0) is None


def test_the_two_frame_count_rules_are_one_rule():
    """comp-broll-tiers-3's decision, pinned on both sides: EXACT. A
    tolerance on one producer and not the other is a fleet with two rules
    about the same file, which is what `frames_match` exists to prevent."""
    from ccsync_companion import ffmpeg_tools

    assert ffmpeg_tools.frames_match(1674, 1674) is True
    assert ffmpeg_tools.frames_match(1674, 1673) is False


def test_an_editing_proxy_that_is_the_preview_is_no_editing_proxy():
    """broll-4: the `Proxy/` arm builds `stem + ".mov"` the same way the
    detail route does, so a preview that is itself a `.mov` named one file
    twice -- a `heavy` verdict resting on an editing proxy that does not
    exist, and an upgrade owed against the file the clip already is."""
    rel = "Creators_Club/ff5/Proxy/clip.mov"

    tiers = broll_server.derive_insert_paths(None, rel)

    assert tiers["preview_rel"] == rel
    assert tiers["edit_proxy_rel"] is None
    # And the same pair arriving from a page is refused too.
    told = broll_server.derive_insert_paths(
        {"preview_rel": rel, "edit_proxy_rel": rel,
         "original_is_edit_weight": False}, rel)
    assert told["edit_proxy_rel"] is None


# ---------------------------------------------------------------------------
# CR-284H (proxy-tiers-4): the stand-in fact travels with the FLEET
# ---------------------------------------------------------------------------
#
# The contract is docs/bug-hunt-2026-09-18/ledger/dashboard.md, "proxy-tiers-4
# contract": the report carries `sync_guard.standins_placed = {rels,
# checked_at}` (archive-relative, NFC, max 200, never absolute) and the report
# REPLY answers `standins_known = {rels}`. Both directions are tested with the
# shape the other half really sends.

ARCHIVE_ROOT = "P:" + os.sep + "Assets" + os.sep + "B-roll Archive"


def test_the_report_carries_the_archive_rels_this_machine_stood_in_for(tmp_path):
    """The producer. A stand-in is placed on the REMOTE editor's machine and
    the ledger row is written there and nowhere else, so the wired rig - the
    only machine the plan's last table row is for - had an empty ledger for
    exactly those clips and nothing but a demux of the whole archive."""
    clip = tmp_path / "clip.mov"
    clip.write_bytes(b"the preview's bytes")
    broll_standins.record(clip, share="broll",
                          rel_path="Creators_Club/ff5/clip.mov",
                          original_rel="Creators_Club/ff5/clip.mov",
                          size=clip.stat().st_size)

    report = broll_standins.placed_report("P:" + os.sep, "P:" + os.sep)

    assert report["rels"] == ["Creators_Club/ff5/clip.mov"]
    assert report["checked_at"]
    # Never an absolute path: the vault is a drive letter here and a container
    # mount there.
    assert not any(":" in rel or rel.startswith("/") for rel in report["rels"])


def test_the_report_says_none_rather_than_saying_nothing(tmp_path):
    """An empty list is a positive statement. The dashboard REPLACES this
    machine's set from this section, so an absent one could never clear a
    stand-in that has been replaced."""
    assert broll_standins.placed_report()["rels"] == []


def test_the_fleet_report_is_bounded_and_deduplicated(tmp_path):
    for i in range(5):
        clip = tmp_path / f"clip{i}.mov"
        clip.write_bytes(b"x")
        broll_standins.record(clip, rel_path="Creators_Club/ff5/same.mov",
                              original_rel="Creators_Club/ff5/same.mov", size=1)

    assert broll_standins.placed_report(limit=3)["rels"] == \
        ["Creators_Club/ff5/same.mov"]
    assert len(broll_standins.placed_report(limit=2)["rels"]) <= 2


def _archive_item(rel: str, frames: int = 1000) -> dict:
    return {"file_path": ARCHIVE_ROOT + os.sep + rel.replace("/", os.sep),
            "media_pool_uid": "u", "clip_name": os.path.basename(rel),
            "proxy_path": "", "proxy_state": "None", "frames": frames}


def _plan_with(item: dict, counted: list) -> list:
    return proxy_relink.plan_relinks(
        [item], local_root="P:" + os.sep, canonical_prefix="P:" + os.sep,
        is_windows=(os.sep == "\\"),
        exists_fn=lambda p: True, is_standin_fn=lambda p: False,
        frames_fn=lambda i: i.get("frames"),
        count_frames_fn=lambda p: counted.append(p) or 6000,
        stat_fn=lambda p: os.stat_result((0, 0, 0, 0, 0, 0, 7, 0, 1.0, 0)))


def test_a_wired_rig_learns_from_the_fleet_without_demuxing_the_archive():
    """The consumer, fed the dashboard's real reply shape. The wired rig's own
    ledger is empty for these clips by construction, so before this the only
    thing left was `ffprobe -count_packets` over the whole archive."""
    counted: list = []
    proxy_relink.reset_fleet_standins()
    assert proxy_relink.note_fleet_standins(
        {"standins_known": {"rels": ["Creators_Club/ff5/clip.mov"]}}) is True

    ops = _plan_with(_archive_item("Creators_Club/ff5/clip.mov"), counted)

    assert len(ops) == 1 and ops[0]["refresh"] is True
    assert counted == [], "the fleet's answer must cost no probe at all"


def test_a_clip_the_fleet_has_not_heard_of_is_still_probed():
    """False from the dashboard is not proof: it only knows what machines have
    told it. A "no" falls through to the questions that were there before."""
    counted: list = []
    proxy_relink.reset_fleet_standins()
    proxy_relink.note_fleet_standins({"standins_known": {"rels": []}})

    ops = _plan_with(_archive_item("Creators_Club/ff5/other.mov"), counted)

    assert len(ops) == 1 and ops[0]["refresh"] is True    # the probe disagreed
    assert len(counted) == 1


def test_a_dashboard_that_does_not_know_behaves_exactly_as_before():
    """The third state, and the one that matters: an ABSENT `standins_known`
    is "this dashboard does not know", never "there are no stand-ins". A
    dashboard deployed behind the companions must not turn the demux off."""
    proxy_relink.reset_fleet_standins()

    assert proxy_relink.note_fleet_standins({"commands": {}}) is False
    assert proxy_relink.note_fleet_standins({}) is False
    assert proxy_relink.fleet_says_standin("Creators_Club/ff5/clip.mov") is None

    counted: list = []
    ops = _plan_with(_archive_item("Creators_Club/ff5/clip.mov"), counted)
    assert len(ops) == 1 and len(counted) == 1, "the probe must still run"


def test_a_mac_spelling_of_one_name_is_one_key():
    """CR-90 both ways: the reply is normalised on the way in and the report
    on the way out, because a path a Mac reported is not `==` a path anything
    else reported and this value is only ever compared."""
    nfd = "Creators_Club/Matej Šimalčík/clip.mov"
    nfc = "Creators_Club/Matej Šimalčík/clip.mov"
    proxy_relink.reset_fleet_standins()
    proxy_relink.note_fleet_standins({"standins_known": {"rels": [nfd]}})

    assert proxy_relink.fleet_says_standin(nfc) is True
