"""CR-380 (2026-11-01): the VP9 guard. A timeline whose ORIGINAL media is VP9
fails a full-resolution render in Resolve Studio, and the H.264 proxies hide
it until then. ffprobe is stubbed, the dialog is a recording stub, and the
guard's worker body (run_pending) is driven inline: no Tk, no thread, no
Resolve."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ccsync_companion import config as config_mod
from ccsync_companion import vp9_guard
from ccsync_companion.paths import clear_prefix_cache
from ccsync_companion.vp9_guard import DISMISS, SUPPRESS, VP9Guard
from ccsync_companion.watcher import TimelineWatcher


class Rig:
    def __init__(self, tmp_path: Path, codecs: dict[str, object], answer=DISMISS,
                 enabled=True):
        self.media = tmp_path / "media"
        self.media.mkdir(exist_ok=True)
        self.codecs = codecs          # file name -> codec str, None, or Exception
        self.answer = answer
        self.enabled = enabled
        self.probed: list[str] = []
        self.shown: list[tuple[str, str]] = []
        self.state_dir = tmp_path / "state"
        self.now = 1000.0
        self.guard = self._build()

    def _build(self) -> VP9Guard:
        return VP9Guard(
            enabled_fn=lambda: self.enabled,
            ffmpeg_path_fn=lambda: "ffmpeg",
            state_dir=self.state_dir,
            show_fn=self._show,
            probe_fn=self._probe,
            clock=lambda: self.now,
            start_thread=False,
        )

    def restart(self) -> None:
        """A new guard over the same state dir: a companion restart."""
        self.guard = self._build()

    def _show(self, title, body):
        self.shown.append((title, body))
        return self.answer

    def _probe(self, ffmpeg, path):
        name = Path(path).name
        self.probed.append(name)
        value = self.codecs.get(name)
        if isinstance(value, Exception):
            raise value
        return {"codec": value}

    def clip(self, name, track=1, index=0, clip_name=None, track_type="video"):
        path = self.media / name
        if not path.exists():
            path.write_bytes(b"x" * 10)
        return {"file_path": str(path), "clip_name": clip_name or name,
                "track_type": track_type, "track_index": track, "item_index": index}

    def poll(self, *items, project="Proj", uid="tl-1"):
        self.guard.observe({"ok": True, "items": list(items),
                            "project_name": project, "timeline_uid": uid})
        self.guard.run_pending()


def test_vp9_clip_warns_and_names_the_clip(tmp_path):
    rig = Rig(tmp_path, {"yt.mp4": "vp9"})
    rig.poll(rig.clip("yt.mp4", track=2, index=4, clip_name="Interview"))
    assert len(rig.shown) == 1
    title, body = rig.shown[0]
    assert "Interview (yt.mp4)" in body
    assert "V2 clip 5" in body
    assert "WILL FAIL to render" in body
    assert "H.264" in body and "relink" in body
    assert "\u2014" not in title + body


@pytest.mark.parametrize("codec", ["h264", "av1", "hevc", "prores"])
def test_other_codecs_do_not_warn(tmp_path, codec):
    rig = Rig(tmp_path, {"a.mp4": codec})
    rig.poll(rig.clip("a.mp4"))
    assert rig.shown == []


def test_audio_items_are_not_probed(tmp_path):
    rig = Rig(tmp_path, {"a.mp4": "vp9"})
    rig.poll(rig.clip("a.mp4", track_type="audio"))
    assert rig.probed == [] and rig.shown == []


@pytest.mark.parametrize("outcome", [RuntimeError("ffprobe blew up"), None, ""])
def test_probe_failure_is_unknown_not_vp9(tmp_path, outcome):
    rig = Rig(tmp_path, {"a.mp4": outcome})
    rig.poll(rig.clip("a.mp4"))
    assert rig.shown == []


def test_unknown_is_retried_later_and_a_real_answer_then_warns(tmp_path):
    rig = Rig(tmp_path, {"a.mp4": RuntimeError("drive asleep")})
    clip = rig.clip("a.mp4")
    rig.poll(clip)
    assert rig.shown == []
    # Inside the retry window it is not asked again...
    rig.now += vp9_guard.CHECK_INTERVAL_SECONDS + 1
    rig.codecs["a.mp4"] = "vp9"
    rig.poll(clip)
    assert rig.probed == ["a.mp4"] and rig.shown == []
    # ...after it, the real answer is believed.
    rig.now += vp9_guard.UNKNOWN_RETRY_SECONDS + 1
    rig.poll(clip)
    assert len(rig.shown) == 1


def test_missing_original_is_unknown(tmp_path):
    rig = Rig(tmp_path, {})
    ghost = {"file_path": str(rig.media / "gone.mp4"), "clip_name": "g",
             "track_type": "video", "track_index": 1, "item_index": 0}
    rig.poll(ghost)
    assert rig.probed == [] and rig.shown == []


def test_cache_hit_avoids_reprobe_in_memory_and_after_restart(tmp_path):
    rig = Rig(tmp_path, {"a.mp4": "h264"})
    clip = rig.clip("a.mp4")
    rig.poll(clip)
    rig.now += vp9_guard.CHECK_INTERVAL_SECONDS + 1
    rig.poll(clip)
    assert rig.probed == ["a.mp4"]
    rig.restart()
    rig.poll(clip)
    assert rig.probed == ["a.mp4"]


def test_changed_file_is_reprobed(tmp_path):
    rig = Rig(tmp_path, {"a.mp4": "vp9"})
    clip = rig.clip("a.mp4")
    rig.poll(clip)
    assert len(rig.shown) == 1
    # Converted in place: new size, so the cache key no longer matches.
    Path(clip["file_path"]).write_bytes(b"y" * 99)
    rig.codecs["a.mp4"] = "h264"
    rig.now += vp9_guard.CHECK_INTERVAL_SECONDS + 1
    rig.poll(clip)
    assert rig.probed == ["a.mp4", "a.mp4"]


def test_unchanged_timeline_is_not_rechecked_inside_the_interval(tmp_path):
    rig = Rig(tmp_path, {"a.mp4": "vp9"})
    clip = rig.clip("a.mp4")
    rig.poll(clip)
    rig.guard.observe({"items": [clip], "project_name": "Proj", "timeline_uid": "tl-1"})
    assert rig.guard._pending is None


def test_session_does_not_repeat_but_new_vp9_clip_warns_again(tmp_path):
    rig = Rig(tmp_path, {"a.mp4": "vp9", "b.mp4": "vp9"})
    a = rig.clip("a.mp4")
    rig.poll(a)
    rig.poll(a, rig.clip("c.mp4"))       # timeline changed, still no news
    rig.codecs["c.mp4"] = "h264"
    assert len(rig.shown) == 1
    rig.poll(a, rig.clip("b.mp4", index=1))
    assert len(rig.shown) == 2
    assert "b.mp4" in rig.shown[1][1] and "a.mp4" in rig.shown[1][1]


def test_stop_warning_suppresses_that_timeline_across_restarts(tmp_path):
    rig = Rig(tmp_path, {"a.mp4": "vp9"}, answer=SUPPRESS)
    a = rig.clip("a.mp4")
    rig.poll(a)
    assert len(rig.shown) == 1
    state = json.loads((rig.state_dir / vp9_guard.STATE_FILENAME).read_text())
    assert state["timelines"]["Proj|tl-1"]["project"] == "Proj"
    rig.restart()
    rig.poll(a)
    assert len(rig.shown) == 1


def test_suppression_is_per_project_and_timeline(tmp_path):
    rig = Rig(tmp_path, {"a.mp4": "vp9"}, answer=SUPPRESS)
    a = rig.clip("a.mp4")
    rig.poll(a)
    rig.poll(a, uid="tl-2")
    rig.poll(a, project="Other")
    assert len(rig.shown) == 3


def test_new_vp9_clip_rewarns_after_suppression(tmp_path):
    rig = Rig(tmp_path, {"a.mp4": "vp9", "b.mp4": "vp9"}, answer=SUPPRESS)
    a = rig.clip("a.mp4")
    rig.poll(a)
    rig.restart()
    rig.poll(a, rig.clip("b.mp4", index=1))
    assert len(rig.shown) == 2
    assert "b.mp4" in rig.shown[1][1]
    # ...and now both are acknowledged.
    rig.restart()
    rig.poll(a, rig.clip("b.mp4", index=1))
    assert len(rig.shown) == 2


def test_dialog_that_could_not_be_shown_is_retried(tmp_path):
    rig = Rig(tmp_path, {"a.mp4": "vp9"}, answer=None)
    a = rig.clip("a.mp4")
    rig.poll(a)
    assert len(rig.shown) == 1
    rig.answer = DISMISS
    rig.poll(a)                           # next poll, inside the interval
    assert len(rig.shown) == 2
    rig.poll(a)
    assert len(rig.shown) == 2


def test_disabled_guard_does_nothing(tmp_path):
    rig = Rig(tmp_path, {"a.mp4": "vp9"}, enabled=False)
    rig.poll(rig.clip("a.mp4"))
    assert rig.probed == [] and rig.shown == []


def test_config_key_defaults_on_and_turns_off():
    assert config_mod.DEFAULTS["vp9_guard"] is True
    assert vp9_guard.enabled({}) is True
    assert vp9_guard.enabled({"vp9_guard": False}) is False
    assert vp9_guard.enabled({"vp9_guard": "false"}) is False
    assert vp9_guard.enabled({"vp9_guard": True}) is True


def test_long_lists_are_capped_in_the_message():
    groups = [{"path": f"/m/f{i}.mp4", "clip_name": f"c{i}",
               "positions": ["V1 clip 1"]} for i in range(30)]
    body = vp9_guard.build_message("P", groups)
    assert "and 18 more files" in body
    assert "\u2014" not in body


def test_watcher_hands_each_successful_poll_to_the_hook(tmp_path):
    clear_prefix_cache()
    seen = []
    result = {"ok": True, "message": "", "items": [], "project_name": "P",
              "timeline_uid": "u"}
    watcher = TimelineWatcher(
        local_root=str(tmp_path), canonical_prefix="P:\\",
        get_timeline_items=lambda: result,
        on_timeline_scanned=seen.append,
    )
    watcher.poll_once()
    assert seen == [result]


def test_a_raising_hook_never_breaks_the_poll(tmp_path):
    def boom(_result):
        raise RuntimeError("nope")
    watcher = TimelineWatcher(
        local_root=str(tmp_path), canonical_prefix="P:\\",
        get_timeline_items=lambda: {"ok": True, "message": "", "items": [],
                                    "project_name": "P"},
        on_timeline_scanned=boom,
    )
    assert watcher.poll_once()["ok"] is True


def test_app_wires_the_guard_into_its_watcher(tmp_path):
    from test_app import _make_app
    app = _make_app(tmp_path)
    assert app.watcher._on_timeline_scanned == app._vp9_guard.observe
