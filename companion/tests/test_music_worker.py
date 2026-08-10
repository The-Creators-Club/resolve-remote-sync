"""music_worker: the three actions, against fake Resolve scripting objects.

REHOMED with the code (port step 8, 2026-08-10) from
music/web/musicweb/resolve_worker.py, which had no unit tests of its own --
its arithmetic was only ever proven on a scratch timeline in a live Resolve.
That check still has to be run by hand (Resolve, a real project, a throwaway
timeline), but every landmine the module's header names is pinned here so a
future edit cannot quietly reintroduce one:

  * AppendToTimeline without an explicit trackIndex/mediaType obeys the UI's
    destination-track buttons and can place NOTHING while reporting no error.
  * Appending to a track that does not exist returns an item yet places
    nothing -- AddTrack first.
  * A returned item is not proof of placement -- verify GetStart().
  * AppendToTimeline lands on the CURRENT timeline whatever object you hold.
  * endFrame is EXCLUSIVE: length = endFrame - startFrame. dur-1 makes a clip
    one frame short and every ripple computed from it is then wrong, so the
    ripple shifts by the ACTUALLY PLACED duration, not the requested one.
  * source frames come back a hair under the integer -- round(), never int().

The fakes below implement those behaviours rather than a friendly ideal API:
a fake that always places what it is asked to would pass code with any of
these bugs still in it.
"""

from __future__ import annotations

import json

import pytest

from ccsync_companion import music_worker


# ---------------------------------------------------------------------------
# Fake DaVinci Resolve scripting objects
# ---------------------------------------------------------------------------

FPS = 25


def _tc(frame: int, base: int = FPS) -> str:
    h, rest = divmod(frame, 3600 * base)
    m, rest = divmod(rest, 60 * base)
    s, f = divmod(rest, base)
    return "%02d:%02d:%02d:%02d" % (h, m, s, f)


class FakeMediaPoolItem:
    def __init__(self, name, path, frames=0, duration=None):
        self._name = name
        self._props = {"File Path": path, "Frames": frames, "Duration": duration}

    def GetName(self):
        return self._name

    def GetClipProperty(self, key=None):
        return self._props if key is None else self._props.get(key)


class FakeTimelineItem:
    """One clip on one audio track.

    GetLeftOffset returns a float a hair under the integer, exactly as Resolve
    does -- int() on it loses a frame, which is what round() is there for.
    """

    def __init__(self, mp, start, duration, left_offset=0, linked=None):
        self._mp = mp
        self._start = start
        self._duration = duration
        self._left_offset = left_offset
        self._linked = linked or []

    def GetStart(self):
        return self._start

    def GetEnd(self):
        return self._start + self._duration

    def GetDuration(self):
        return self._duration

    def GetLeftOffset(self):
        return self._left_offset - 0.0001 if self._left_offset else 0.0

    def GetMediaPoolItem(self):
        return self._mp

    def GetLinkedItems(self):
        return self._linked


class FakeFolder:
    def __init__(self, name):
        self._name = name
        self.clips = []
        self.subfolders = []

    def GetName(self):
        return self._name

    def GetClipList(self):
        return list(self.clips)

    def GetSubFolderList(self):
        return list(self.subfolders)


class FakeTimeline:
    def __init__(self, audio_tracks=2, playhead_frame=0, fps=FPS, unique_id="TL-1"):
        self.tracks = {i: [] for i in range(1, audio_tracks + 1)}
        self.playhead_frame = playhead_frame
        self.fps = fps
        self._unique_id = unique_id
        self.added_tracks = []
        self.add_track_result = True

    # -- identity / settings
    def GetName(self):
        return "Fake Timeline"

    def GetUniqueId(self):
        return self._unique_id

    def GetSetting(self, key):
        return str(self.fps) if key == "timelineFrameRate" else ""

    def GetStartFrame(self):
        return 0

    def GetCurrentTimecode(self):
        return _tc(self.playhead_frame, self.fps)

    # -- tracks
    def GetTrackCount(self, kind):
        return len(self.tracks) if kind == "audio" else 0

    def GetItemListInTrack(self, kind, index):
        if kind != "audio":
            return []
        return list(self.tracks.get(index, []))

    def AddTrack(self, kind, layout):
        self.added_tracks.append((kind, layout))
        if not self.add_track_result:
            return False
        self.tracks[len(self.tracks) + 1] = []
        return True

    def DeleteClips(self, items, ripple):
        for item in items:
            for track in self.tracks.values():
                if item in track:
                    track.remove(item)
        return True


class FakeMediaPool:
    def __init__(self, timeline, root=None):
        self.root = root or FakeFolder("Master")
        self.current = self.root
        self.timeline = timeline
        self.import_calls = []
        self.append_calls = []
        self.import_result = None
        # Landmine: an item comes back even when nothing was placed.
        self.place_nothing = False
        # Some clips are shorter than the caller thinks; the placed length is
        # what Resolve decides, and the ripple must follow THAT.
        self.max_placed_duration = None

    def GetRootFolder(self):
        return self.root

    def GetCurrentFolder(self):
        return self.current

    def SetCurrentFolder(self, folder):
        self.current = folder
        return True

    def AddSubFolder(self, parent, name):
        folder = FakeFolder(name)
        parent.subfolders.append(folder)
        return folder

    def ImportMedia(self, paths):
        self.import_calls.append(list(paths))
        if self.import_result is not None:
            return self.import_result
        item = FakeMediaPoolItem(paths[0].replace("\\", "/").rsplit("/", 1)[-1],
                                 paths[0], frames=100)
        self.current.clips.append(item)
        return [item]

    def AppendToTimeline(self, specs):
        spec = specs[0]
        self.append_calls.append(dict(spec))
        track_index = spec.get("trackIndex")
        record = spec.get("recordFrame", 0)
        # endFrame is EXCLUSIVE: this is the whole arithmetic under test.
        duration = spec["endFrame"] - spec["startFrame"]
        if self.max_placed_duration is not None:
            duration = min(duration, self.max_placed_duration)

        item = FakeTimelineItem(spec["mediaPoolItem"], record, duration,
                                left_offset=spec["startFrame"])

        if self.place_nothing:
            return [FakeTimelineItem(spec["mediaPoolItem"], -1, duration)]
        # Appending to a track that does not exist returns an item and places
        # nothing -- Resolve's behaviour, and the reason AddTrack comes first.
        if track_index is None or track_index not in self.timeline.tracks:
            return [FakeTimelineItem(spec["mediaPoolItem"], -1, duration)]
        # An occupied span refuses the same way.
        for existing in self.timeline.tracks[track_index]:
            if existing.GetStart() < record + duration and existing.GetEnd() > record:
                return [FakeTimelineItem(spec["mediaPoolItem"], -1, duration)]

        self.timeline.tracks[track_index].append(item)
        self.timeline.tracks[track_index].sort(key=lambda i: i.GetStart())
        return [item]


class FakeProject:
    def __init__(self, media_pool, timeline, name="Fake Project"):
        self._media_pool = media_pool
        self._timeline = timeline
        self._name = name

    def GetName(self):
        return self._name

    def GetCurrentTimeline(self):
        return self._timeline

    def GetMediaPool(self):
        return self._media_pool


class FakeResolve:
    def __init__(self, project):
        self._project = project

    def GetProjectManager(self):
        return self

    def GetCurrentProject(self):
        return self._project


@pytest.fixture
def stack(monkeypatch, tmp_path):
    """A connected fake Resolve: (timeline, media_pool, project, cue_path)."""
    timeline = FakeTimeline(audio_tracks=2, playhead_frame=100)
    media_pool = FakeMediaPool(timeline)
    project = FakeProject(media_pool, timeline)
    monkeypatch.setattr(music_worker.resolve_bridge, "connect",
                        lambda: FakeResolve(project))
    cue = tmp_path / "cue.wav"
    cue.write_bytes(b"RIFF")
    return timeline, media_pool, project, str(cue)


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------


def test_no_connection_names_the_reason_and_the_setting(monkeypatch):
    monkeypatch.setattr(music_worker.resolve_bridge, "connect", lambda: None)
    monkeypatch.setattr(music_worker.resolve_bridge, "describe_disconnection",
                        lambda: "DaVinci Resolve is not running")

    out = music_worker.run_request({"action": "status"})

    assert out["ok"] is False
    assert "DaVinci Resolve is not running" in out["error"]
    assert "External scripting" in out["error"]


def test_the_project_manager_window_counts_as_no_project(monkeypatch):
    """scriptapp() connects fine there and every later call returns None --
    the exact state the 90s timeout in music_server exists for."""
    monkeypatch.setattr(music_worker.resolve_bridge, "connect",
                        lambda: FakeResolve(None))
    out = music_worker.run_request({"action": "status"})
    assert out["ok"] is False
    assert "no project is open" in out["error"]


def test_the_scripting_environment_is_not_a_hardcoded_windows_path():
    """The rehomed original hardcoded C:\\ProgramData\\... -- this companion
    also ships on macOS and inside a PyInstaller bundle, where the modules
    path differs and fusionscript has to be pointed at OUR python3.dll.
    resolve_bridge already does all of that."""
    import inspect

    source = inspect.getsource(music_worker)
    assert "ProgramData" not in source
    assert "resolve_bridge.connect()" in source


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_reports_project_timeline_and_playhead(stack):
    timeline, _pool, _project, _cue = stack
    out = music_worker.run_request({"action": "status"})
    assert out == {"ok": True, "project": "Fake Project", "timeline": "Fake Timeline",
                   "fps": "25", "audio_tracks": 2, "timecode": "00:00:04:00"}


# ---------------------------------------------------------------------------
# bin
# ---------------------------------------------------------------------------


def test_bin_imports_into_the_music_bin_and_touches_no_timeline(stack):
    timeline, pool, _project, cue = stack
    out = music_worker.run_request({"action": "bin", "path": cue})

    assert out["ok"] is True
    assert "Music" in out["note"]
    assert pool.import_calls == [[cue]]
    assert [name for name in (f.GetName() for f in pool.root.subfolders)] == ["Music"]
    assert pool.append_calls == []
    assert all(track == [] for track in timeline.tracks.values())


def test_bin_is_idempotent_and_finds_the_clip_in_ANY_bin(stack):
    """Matched by file path across the whole pool, not by name inside one bin:
    a second import would give the project two media pool items for one cue."""
    _timeline, pool, _project, cue = stack
    other = FakeFolder("Somebody Else's Bin")
    other.clips.append(FakeMediaPoolItem("cue.wav", cue, frames=100))
    pool.root.subfolders.append(other)

    out = music_worker.run_request({"action": "bin", "path": cue})

    assert out["ok"] is True
    assert "already in the media pool" in out["note"]
    assert pool.import_calls == []


def test_bin_restores_the_current_folder_it_found(stack):
    """The editor's selected bin is UI state; importing must not move it."""
    _timeline, pool, _project, cue = stack
    theirs = FakeFolder("Interviews")
    pool.root.subfolders.append(theirs)
    pool.current = theirs

    music_worker.run_request({"action": "bin", "path": cue})

    assert pool.current is theirs


def test_a_refused_import_is_an_error_not_a_silent_success(stack):
    _timeline, pool, _project, cue = stack
    pool.import_result = []
    out = music_worker.run_request({"action": "bin", "path": cue})
    assert out["ok"] is False
    assert "refused to import" in out["error"]


# ---------------------------------------------------------------------------
# under -- first free audio track from A2 down
# ---------------------------------------------------------------------------


def test_under_places_on_A2_at_the_playhead(stack):
    timeline, pool, _project, cue = stack
    out = music_worker.run_request({"action": "under", "path": cue})

    assert out["ok"] is True
    assert out["track"] == "A2"
    assert out["frame"] == 100
    assert "nothing moved" in out["note"]
    assert [i.GetStart() for i in timeline.tracks[2]] == [100]
    assert timeline.tracks[1] == []


def test_under_never_uses_A1_even_when_A1_is_empty(stack):
    """A1 is sync/dialogue audio. Placing music there is the failure this
    whole "from A2 down" rule exists to prevent."""
    timeline, _pool, _project, cue = stack
    assert timeline.tracks[1] == []
    music_worker.run_request({"action": "under", "path": cue})
    assert timeline.tracks[1] == []


def test_under_skips_a_track_occupied_at_the_playhead(stack):
    timeline, _pool, _project, cue = stack
    timeline.tracks[2].append(
        FakeTimelineItem(FakeMediaPoolItem("other.wav", "x", 50), 90, 40))

    out = music_worker.run_request({"action": "under", "path": cue})

    assert out["track"] == "A3"
    assert timeline.added_tracks == [("audio", "stereo")]
    assert "new track" in out["note"]


def test_under_reuses_a_track_whose_clip_ends_before_the_playhead(stack):
    """Occupancy is [rec, rec+dur), not "has anything on it" -- otherwise
    every cue after the first would stack up a new track."""
    timeline, _pool, _project, cue = stack
    timeline.tracks[2].append(
        FakeTimelineItem(FakeMediaPoolItem("other.wav", "x", 50), 0, 100))

    out = music_worker.run_request({"action": "under", "path": cue})

    assert out["track"] == "A2"
    assert timeline.added_tracks == []


def test_under_adds_a_track_when_every_one_from_A2_is_busy(stack):
    timeline, _pool, _project, cue = stack
    for index in (1, 2):
        timeline.tracks[index].append(
            FakeTimelineItem(FakeMediaPoolItem("other.wav", "x", 50), 0, 500))

    out = music_worker.run_request({"action": "under", "path": cue})

    assert out["track"] == "A3"
    assert timeline.added_tracks == [("audio", "stereo")]
    assert [i.GetStart() for i in timeline.tracks[3]] == [100]


def test_under_reports_a_refused_AddTrack(stack):
    timeline, _pool, _project, cue = stack
    timeline.add_track_result = False
    for index in (1, 2):
        timeline.tracks[index].append(
            FakeTimelineItem(FakeMediaPoolItem("other.wav", "x", 50), 0, 500))

    out = music_worker.run_request({"action": "under", "path": cue})
    assert out["ok"] is False
    assert "could not add an audio track" in out["error"]


def test_the_append_always_carries_an_explicit_track_and_media_type(stack):
    """LANDMINE. Without trackIndex, AppendToTimeline obeys the timeline's
    destination-track buttons: with the destination toggled off it places
    NOTHING and reports no error."""
    _timeline, pool, _project, cue = stack
    music_worker.run_request({"action": "under", "path": cue})

    spec = pool.append_calls[0]
    assert spec["trackIndex"] == 2
    assert spec["mediaType"] == 2          # audio only
    assert spec["recordFrame"] == 100


def test_end_frame_is_exclusive_so_the_clip_is_its_full_length(stack):
    """LANDMINE. endFrame is EXCLUSIVE (length = endFrame - startFrame).
    dur-1 yields a clip one frame short, and every ripple computed from it is
    then one frame out."""
    timeline, pool, _project, cue = stack
    music_worker.run_request({"action": "under", "path": cue})

    spec = pool.append_calls[0]
    assert spec["startFrame"] == 0
    assert spec["endFrame"] == 100          # 100 frames of source, NOT 99
    placed = timeline.tracks[2][0]
    assert placed.GetDuration() == 100
    assert placed.GetEnd() == 200


def test_a_returned_item_is_not_proof_of_placement(stack):
    """LANDMINE. Resolve hands back an item for an append that placed
    nothing; only GetStart() says where (if anywhere) it landed."""
    timeline, pool, _project, cue = stack
    pool.place_nothing = True

    out = music_worker.run_request({"action": "under", "path": cue})

    assert out["ok"] is False
    assert "placement failed on A2 at frame 100" in out["error"]
    assert all(track == [] for track in timeline.tracks.values())


def test_a_swapped_current_timeline_places_nothing(stack):
    """LANDMINE. AppendToTimeline always lands on the CURRENT timeline
    whatever object you hold -- so if it changed under us, place nothing."""
    _timeline, pool, project, cue = stack
    other = FakeTimeline(audio_tracks=2, unique_id="TL-2")

    calls = {"n": 0}
    original = project.GetCurrentTimeline

    def _swapping():
        calls["n"] += 1
        return original() if calls["n"] == 1 else other

    project.GetCurrentTimeline = _swapping

    out = music_worker.run_request({"action": "under", "path": cue})

    assert out["ok"] is False
    assert "current timeline changed" in out["error"]
    assert pool.append_calls == []


def test_under_with_no_timeline_open(stack, monkeypatch):
    _timeline, _pool, project, cue = stack
    project.GetCurrentTimeline = lambda: None
    out = music_worker.run_request({"action": "under", "path": cue})
    assert out["ok"] is False
    assert "no timeline is open" in out["error"]


def test_an_audio_only_clip_with_no_frame_count_falls_back_to_duration(stack):
    """wavs routinely report no "Frames"; without the seconds fallback the
    cue would be placed one frame long."""
    _timeline, pool, _project, cue = stack
    pool.import_result = [FakeMediaPoolItem("cue.wav", cue, frames=0, duration=8.0)]

    music_worker.run_request({"action": "under", "path": cue})

    assert pool.append_calls[0]["endFrame"] == 200      # 8.0s * 25 fps


# ---------------------------------------------------------------------------
# insert -- ripple on one audio track
# ---------------------------------------------------------------------------


_DEFAULT_SOURCE = object()      # mp=None means "no media pool item", not "default"


def _occupy(timeline, track, start, duration, mp=_DEFAULT_SOURCE, left_offset=0,
            linked=None):
    if mp is _DEFAULT_SOURCE:
        mp = FakeMediaPoolItem("old.wav", "old", 400)
    item = FakeTimelineItem(mp, start, duration, left_offset, linked)
    timeline.tracks[track].append(item)
    return item


def test_insert_ripples_later_clips_by_exactly_the_cue_length(stack):
    timeline, pool, _project, cue = stack
    _occupy(timeline, 2, 100, 60)
    _occupy(timeline, 2, 200, 40)

    out = music_worker.run_request({"action": "insert", "path": cue})

    assert out["ok"] is True
    assert out["track"] == "A2"
    assert out["frame"] == 100
    assert "2 clip(s) rippled later" in out["note"]
    # cue: 100..200 (100 frames). The two old clips shift by 100, not 99.
    assert [(i.GetStart(), i.GetDuration()) for i in timeline.tracks[2]] == [
        (100, 100), (200, 60), (300, 40),
    ]


def test_the_ripple_shifts_by_the_ACTUALLY_placed_duration(stack):
    """LANDMINE, and the one found by the scratch-timeline test: a clip whose
    reported frame count disagrees with the placement by even one frame would
    otherwise leave a gap or an overlap on every rippled clip."""
    timeline, pool, _project, cue = stack
    pool.max_placed_duration = 90          # Resolve places 90, not the 100 asked
    _occupy(timeline, 2, 100, 60)

    music_worker.run_request({"action": "insert", "path": cue})

    assert pool.append_calls[0]["endFrame"] == 100      # asked for 100...
    placed = timeline.tracks[2][0]
    assert placed.GetDuration() == 90                  # ...got 90...
    assert timeline.tracks[2][1].GetStart() == 190     # ...so the shift is 90


def test_insert_leaves_clips_that_end_before_the_playhead_alone(stack):
    timeline, _pool, _project, cue = stack
    _occupy(timeline, 2, 0, 100)           # ends exactly at the playhead
    _occupy(timeline, 2, 150, 40)

    music_worker.run_request({"action": "insert", "path": cue})

    starts = [i.GetStart() for i in timeline.tracks[2]]
    assert starts == [0, 100, 250]


def test_insert_re_places_a_trimmed_clip_at_its_own_source_in_point(stack):
    """A rippled clip is deleted and re-appended, so its source in/out have to
    be carried across -- GetLeftOffset comes back a hair under the integer and
    int() would trim one more frame off every rippled clip."""
    timeline, pool, _project, cue = stack
    _occupy(timeline, 2, 100, 60, left_offset=1300)

    music_worker.run_request({"action": "insert", "path": cue})

    ripple = pool.append_calls[1]
    assert ripple["startFrame"] == 1300               # round(1299.9999), not 1299
    assert ripple["endFrame"] == 1360                 # exclusive: 60 frames
    assert ripple["trackIndex"] == 2
    assert ripple["mediaType"] == 2


def test_insert_refuses_when_an_affected_clip_is_linked_to_video(stack):
    """The expensive-to-notice-late failure: rippling one audio track under
    locked picture silently desyncs sync sound."""
    timeline, pool, _project, cue = stack
    _occupy(timeline, 2, 120, 60, linked=[object()])

    out = music_worker.run_request({"action": "insert", "path": cue})

    assert out["ok"] is False
    assert "linked to video at frame 120" in out["error"]
    assert "place underneath" in out["error"]
    # Refused BEFORE anything was deleted or placed.
    assert pool.append_calls == []
    assert [i.GetStart() for i in timeline.tracks[2]] == [120]


def test_insert_refuses_a_clip_with_no_media_pool_source(stack):
    """Compounds, fusion clips and generators cannot be re-appended, so the
    delete half of the ripple would destroy them."""
    timeline, pool, _project, cue = stack
    _occupy(timeline, 2, 140, 60, mp=None)

    out = music_worker.run_request({"action": "insert", "path": cue})

    assert out["ok"] is False
    assert "no media pool source" in out["error"]
    assert "frame 140" in out["error"]
    assert pool.append_calls == []
    assert len(timeline.tracks[2]) == 1


def test_insert_onto_an_empty_track_still_places_the_cue(stack):
    timeline, _pool, _project, cue = stack
    out = music_worker.run_request({"action": "insert", "path": cue})
    assert out["ok"] is True
    assert "0 clip(s) rippled later" in out["note"]
    assert [(i.GetStart(), i.GetDuration()) for i in timeline.tracks[2]] == [(100, 100)]


def test_insert_adds_the_track_when_the_requested_one_does_not_exist(stack):
    """LANDMINE. Appending to a track that does not exist returns an item and
    places nothing."""
    timeline, _pool, _project, cue = stack
    out = music_worker.run_request({"action": "insert", "path": cue, "track": 3})

    assert out["ok"] is True
    assert out["track"] == "A3"
    assert timeline.added_tracks == [("audio", "stereo")]
    assert [i.GetStart() for i in timeline.tracks[3]] == [100]


def test_insert_rolls_the_track_back_when_a_ripple_fails(stack):
    """Half a ripple is worse than none: the editor would be left with a gap
    and a silently moved cue."""
    timeline, pool, _project, cue = stack
    _occupy(timeline, 2, 100, 60, left_offset=10)

    real_append = pool.AppendToTimeline
    state = {"n": 0}

    def _failing(specs):
        state["n"] += 1
        if state["n"] == 2:                # the ripple re-append
            return [FakeTimelineItem(specs[0]["mediaPoolItem"], -1, 60)]
        return real_append(specs)

    pool.AppendToTimeline = _failing

    out = music_worker.run_request({"action": "insert", "path": cue})

    assert out["ok"] is False
    assert "rolled back 1/1 clip(s) on A2" in out["error"]
    assert [(i.GetStart(), i.GetDuration()) for i in timeline.tracks[2]] == [(100, 60)]


# ---------------------------------------------------------------------------
# The process contract: argv in, one line of JSON out
# ---------------------------------------------------------------------------


def test_a_bare_positional_json_argument_is_the_request():
    assert music_worker.request_from_argv(['{"action": "status"}']) == \
        {"action": "status"}


def test_the_frozen_flag_form_is_the_same_request():
    argv = ["--music-resolve-worker", '{"action": "bin", "path": "a.wav"}']
    assert music_worker.request_from_argv(argv) == {"action": "bin", "path": "a.wav"}


def test_the_flag_is_found_even_with_other_argv_around_it():
    argv = ["--whatever", music_worker.WORKER_FLAG, '{"action": "status"}', "--tail"]
    assert music_worker.request_from_argv(argv) == {"action": "status"}


def test_no_argument_at_all_is_an_empty_request():
    assert music_worker.request_from_argv([]) == {}
    assert music_worker.request_from_argv([music_worker.WORKER_FLAG]) == {}


def test_an_unknown_action_is_an_error_dict_not_an_exit_code():
    assert music_worker.run_request({"action": "nuke"}) == {
        "ok": False, "error": "unknown action 'nuke'"}
    assert music_worker.run_request({})["ok"] is False


def test_main_writes_one_line_of_json_to_fd_1(capfdbinary):
    """FD 1, not sys.stdout: in the windowed (console=False) frozen build
    sys.stdout can be None, and the AttributeError would reach the parent as
    "the worker produced no output"."""
    rc = music_worker.main(['{"action": "nuke"}'])
    out, _err = capfdbinary.readouterr()

    assert rc == 0
    payload = out.decode("utf-8")
    assert "\n" not in payload
    assert json.loads(payload) == {"ok": False, "error": "unknown action 'nuke'"}


def test_malformed_json_on_the_command_line_is_answered_not_raised(capfdbinary):
    rc = music_worker.main(["{not json"])
    out, _err = capfdbinary.readouterr()
    assert rc == 0
    answer = json.loads(out.decode("utf-8"))
    assert answer["ok"] is False
    assert "bad worker request" in answer["error"]


def test_non_ascii_survives_the_round_trip(capfdbinary, monkeypatch):
    monkeypatch.setattr(music_worker.resolve_bridge, "connect", lambda: None)
    monkeypatch.setattr(music_worker.resolve_bridge, "describe_disconnection",
                        lambda: "DaVinci Resolve 沒有在執行")
    music_worker.main(['{"action": "status"}'])
    out, _err = capfdbinary.readouterr()
    assert "沒有在執行" in json.loads(out.decode("utf-8"))["error"]
