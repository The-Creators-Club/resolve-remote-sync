"""The relink pass after phase 3: no preview over a real original, and the
one ReplaceClip a stand-in-born clip needs.

Audit F1 + docs/BROLL_PROXY_TIERS_PLAN.md section 6 (2026-09-17). The pass
runs every 120 s over the whole media pool, so it is the thing that would
quietly undo phase 3 two minutes after every insert.
"""

from __future__ import annotations

import pytest

from ccsync_companion import proxy_relink

LOCAL_ROOT = r"F:\Creators_Club"
PREFIX = "P:\\"
ORIGINAL = r"P:\Assets\B-roll Archive\cc\ff5\clip.mov"
PREVIEW = r"P:\Assets\B-roll Archive\cc\ff5\Proxy\clip.mp4"
EDIT_PROXY = r"P:\Assets\B-roll Archive\cc\ff5\Proxy\clip.mov"


@pytest.fixture(autouse=True)
def _forget_geometry_verdicts():
    """comp-resolve-2 (2026-09-18) gave the geometry check an in-process
    memory keyed on (file, mtime, size, stored frames), so a clip that agrees
    is never probed twice. These tests all use one path and one fake stat, so
    without this they would answer each other's questions."""
    proxy_relink.reset_geometry_verdicts()
    yield
    proxy_relink.reset_geometry_verdicts()


def _item(**overrides):
    item = {"file_path": ORIGINAL, "media_pool_item": object(),
            "media_pool_uid": "uid-1", "clip_name": "clip.mov",
            "proxy_path": "", "proxy_state": "None"}
    item.update(overrides)
    return item


def _exists(*present):
    known = {proxy_relink._norm(p, proxy_relink._plat_for(p, True)) for p in present}

    def check(path):
        return proxy_relink._norm(path, proxy_relink._plat_for(path, True)) in known

    return check


def _plan(items, exists, **kwargs):
    kwargs.setdefault("is_standin_fn", lambda _path: False)
    return proxy_relink.plan_relinks(items, LOCAL_ROOT, PREFIX,
                                     exists_fn=exists, is_windows=True,
                                     stat_fn=lambda p: _Stat(), **kwargs)


class _Stat:
    st_mtime = 1.0
    st_size = 2


def test_an_mp4_preview_is_not_offered_to_a_clip_whose_original_is_here():
    """The 540p/1080p `Proxy/<stem>.mp4` is the BROWSER preview. Attaching it
    to a clip whose real original is on this machine makes the editor cut at
    preview quality with nothing on screen to say so (audit F1)."""
    ops = _plan([_item()], _exists(ORIGINAL, PREVIEW))

    assert ops == []


def test_an_mp4_preview_is_offered_when_the_original_is_absent():
    """The remote editor's steady state, and today's behaviour: something is
    better than Media Offline."""
    ops = _plan([_item()], _exists(PREVIEW))

    assert [op["new_proxy"] for op in ops] == [PREVIEW]


def test_an_mp4_preview_is_offered_over_a_stand_in():
    """The file at the original's path IS that preview's bytes, so there is
    no better quality to protect."""
    ops = _plan([_item()], _exists(ORIGINAL, PREVIEW),
                is_standin_fn=lambda path: True)

    assert [op["new_proxy"] for op in ops] == [PREVIEW]


def test_a_mov_editing_proxy_is_always_offered():
    """proxy_gen's and the Blackmagic Proxy Generator's own output: the
    editing proxy is what a proxy attachment is FOR."""
    ops = _plan([_item()], _exists(ORIGINAL, EDIT_PROXY, PREVIEW))

    assert [op["new_proxy"] for op in ops] == [EDIT_PROXY]


def test_a_working_proxy_is_still_left_alone():
    """The pass has never swapped a playing proxy and must not start: that is
    what keeps a preview the editor is cutting with from being yanked out
    from under them mid-sentence."""
    ops = _plan([_item(proxy_state="1920x1080", proxy_path=PREVIEW)],
                _exists(ORIGINAL, EDIT_PROXY))

    assert ops == []


# ---------------------------------------------------------------------------
# The wired rig's refresh
# ---------------------------------------------------------------------------


def test_a_clip_whose_stored_frames_disagree_with_its_file_is_refreshed():
    """A clip born from a stand-in on another machine: 1080p and 3,255 frames
    stored over a 6K file of 1,813. Resolve does not re-read it; only
    ReplaceClip on the same path does (spike, section 3)."""
    ops = _plan([_item(frames=3255, proxy_state="1920x1080", proxy_path=EDIT_PROXY)],
                _exists(ORIGINAL, EDIT_PROXY),
                frames_fn=proxy_relink.stored_frames,
                count_frames_fn=lambda _path: 1813)

    assert len(ops) == 1
    assert ops[0]["refresh"] is True
    assert ops[0]["file_path"] == ORIGINAL
    assert ops[0]["reason"] == "refresh"


def test_a_clip_that_agrees_with_its_file_is_not_refreshed():
    ops = _plan([_item(frames=1813, proxy_state="1920x1080", proxy_path=EDIT_PROXY)],
                _exists(ORIGINAL, EDIT_PROXY),
                frames_fn=proxy_relink.stored_frames,
                count_frames_fn=lambda _path: 1813)

    assert ops == []


@pytest.mark.parametrize("stored,counted", [(None, 1813), (3255, None), (3255, 0)])
def test_an_answer_nobody_can_give_is_not_a_disagreement(stored, counted):
    """A check that cannot run must not condemn good media."""
    ops = _plan([_item(frames=stored, proxy_state="1920x1080")],
                _exists(ORIGINAL),
                frames_fn=proxy_relink.stored_frames,
                count_frames_fn=lambda _path: counted)

    assert ops == []


def test_a_stand_in_is_never_refreshed_against_its_own_file():
    """Of course its frame count disagrees with the original's -- it IS the
    preview. Refreshing it would bake the preview's geometry in on purpose."""
    ops = _plan([_item(frames=1813, proxy_state="1920x1080")],
                _exists(ORIGINAL),
                is_standin_fn=lambda _path: True,
                frames_fn=proxy_relink.stored_frames,
                count_frames_fn=lambda _path: 3255)

    assert ops == []


def test_project_footage_is_never_probed_for_a_refresh():
    """Scoped to the archive: a stand-in is the only thing that can leave a
    clip's stored geometry disagreeing with its file, and ffprobing a
    1,300-clip pool every 120 s would cost more than the whole pass."""
    project_clip = r"P:\Projects\ff5\clip.mov"
    ops = _plan([_item(file_path=project_clip, frames=3255,
                       proxy_state="1920x1080")],
                _exists(project_clip),
                frames_fn=proxy_relink.stored_frames,
                count_frames_fn=lambda _p: pytest.fail("nothing to probe here"))

    assert ops == []


def test_the_refresh_runs_before_the_proxy_link():
    calls = []
    op = {"media_pool_item": object(), "media_pool_uid": "uid-1",
          "clip_name": "clip.mov", "file_path": ORIGINAL, "old_proxy": "",
          "new_proxy": EDIT_PROXY, "refresh": True, "reason": "refresh"}

    result = proxy_relink.apply_relinks(
        [op],
        link_fn=lambda item, path: calls.append(("link", path)) or {"ok": True},
        resolve_fn=lambda o: o["media_pool_item"],
        replace_fn=lambda item, path: calls.append(("replace", path)) or {"ok": True},
    )

    assert calls == [("replace", ORIGINAL), ("link", EDIT_PROXY)]
    assert result["refreshed"] == 1
    assert result["relinked"] == 1


def test_a_refresh_only_op_links_nothing():
    op = {"media_pool_item": object(), "media_pool_uid": "uid-1",
          "clip_name": "clip.mov", "file_path": ORIGINAL, "old_proxy": "",
          "new_proxy": None, "refresh": True, "reason": "refresh"}

    result = proxy_relink.apply_relinks(
        [op],
        link_fn=lambda *a: pytest.fail("there is no proxy to link"),
        resolve_fn=lambda o: o["media_pool_item"],
        replace_fn=lambda item, path: {"ok": True},
    )

    assert result["refreshed"] == 1
    assert result["ok"] is True


def test_a_refusal_after_a_failed_refresh_is_not_remembered():
    """Resolve would be judging the new proxy against the stand-in's frame
    count, and a refusal on those terms is remembered for ever (COMP-MEDIA-5's
    brake working against us)."""
    proxy_relink.reset_refusals()
    op = {"media_pool_item": object(), "media_pool_uid": "uid-1",
          "clip_name": "clip.mov", "file_path": ORIGINAL, "old_proxy": "",
          "new_proxy": EDIT_PROXY, "refresh": True, "reason": "refresh"}

    result = proxy_relink.apply_relinks(
        [op],
        link_fn=lambda *a: pytest.fail("nothing may be linked after a failed refresh"),
        resolve_fn=lambda o: o["media_pool_item"],
        replace_fn=lambda item, path: {"ok": False, "message": "Resolve said no"},
        stat_fn=lambda p: _Stat(),
    )

    assert result["failed"] == 1
    assert result["refreshed"] == 0
    assert proxy_relink.is_refused(ORIGINAL, EDIT_PROXY, lambda p: _Stat()) is False
    proxy_relink.reset_refusals()


def test_the_frame_counter_asks_ffprobe_once_per_file_per_pass():
    asked = []
    counter = proxy_relink.frame_counter("ffmpeg")
    import ccsync_companion.ffmpeg_tools as ffmpeg_tools
    real = ffmpeg_tools.count_frames
    ffmpeg_tools.count_frames = lambda exe, path: asked.append(path) or 42
    try:
        assert counter(ORIGINAL) == 42
        assert counter(ORIGINAL.lower()) == 42
    finally:
        ffmpeg_tools.count_frames = real

    assert len(asked) == 1
