"""Regression tests for the 2026-09-18b mediums wave, companion-resolve (CR-293).

Each test fails on the tree as it stood before CR-293 and passes after it.
Nothing here talks to Resolve: `replace_fn` is injected, and the plan side is
pure by construction.
"""

from __future__ import annotations

import os

import pytest

from ccsync_companion import broll_standins
from ccsync_companion import proxy_relink


@pytest.fixture(autouse=True)
def _own_ledger(tmp_path):
    broll_standins.configure(tmp_path / "state" / "broll_standins.json")
    proxy_relink.reset_geometry_verdicts()
    proxy_relink.reset_refusals()
    yield
    proxy_relink.reset_geometry_verdicts()
    proxy_relink.reset_refusals()


# ---------------------------------------------------------------------------
# CR-293A (comp-resolve-2): a half-raised refresh is not a settled answer
# ---------------------------------------------------------------------------

def test_a_refresh_in_which_resolve_raised_is_not_remembered_for_ever(tmp_path):
    """`ok: False` covered the burst in which EVERY ReplaceClip raised. One of
    three raising (mid-render, a script-server flap) while the survivor did not
    move the geometry answered "settled", and the verdict is keyed on a
    (mtime, size) that never changes again once the original has arrived - so
    phase 3's one mechanism stayed disarmed for that clip for the life of the
    process."""
    media = tmp_path / "clip.mov"
    media.write_bytes(b"x")
    op = {"media_pool_item": object(), "media_pool_uid": "u", "clip_name": "c",
          "file_path": str(media), "old_proxy": "", "new_proxy": None,
          "stored_frames": 1000, "refresh": True, "reason": "refresh"}

    result = proxy_relink.apply_relinks(
        [dict(op)], link_fn=lambda i, p: {"ok": True},
        resolve_fn=lambda o: o["media_pool_item"],
        replace_fn=lambda i, p, force=False: {
            "ok": True, "changed": False, "retryable": True,
            "message": "Resolve did not answer cleanly"})

    assert proxy_relink.remembered_geometry_verdict(
        str(media), stored=1000) is None, "a flap must not settle the clip"
    # And it is still not a failure: REASON_NO_ANSWER would change what the
    # RES-3 channel reports about a clip nothing is wrong with.
    assert result["failures"] == []


def test_a_clean_refresh_that_did_not_move_is_still_remembered(tmp_path):
    """The other half: a pass in which Resolve took every call and the
    geometry did not move is the answer CR-284R exists to remember, and the
    fix must not cost that."""
    media = tmp_path / "clip.mov"
    media.write_bytes(b"x")
    op = {"media_pool_item": object(), "media_pool_uid": "u", "clip_name": "c",
          "file_path": str(media), "old_proxy": "", "new_proxy": None,
          "stored_frames": 1000, "refresh": True, "reason": "refresh"}

    proxy_relink.apply_relinks(
        [dict(op)], link_fn=lambda i, p: {"ok": True},
        resolve_fn=lambda o: o["media_pool_item"],
        replace_fn=lambda i, p, force=False: {"ok": True, "changed": False})

    assert proxy_relink.remembered_geometry_verdict(
        str(media), stored=1000) is False


def test_replace_clip_says_a_partly_raised_refresh_is_retryable(monkeypatch):
    """The producer of that flag, through the real function. Two of three
    attempts raise and the geometry never moves."""
    from ccsync_companion import resolve_bridge

    path = "C:\\x\\clip.mov"
    calls = {"n": 0}

    class Item:
        def GetClipProperty(self, *a):
            # The clip never re-reads the file: same geometry throughout.
            return {"File Path": path, "Frames": "300",
                    "Resolution": "1920x1080"}

        def ReplaceClip(self, p):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("the script server went away")
            return True

    monkeypatch.setattr(resolve_bridge.ui_state, "wait_while_menu_open",
                        lambda *a, **k: None)
    monkeypatch.setattr(resolve_bridge.time, "sleep", lambda s: None)

    out = resolve_bridge.replace_clip(Item(), path, tries=3,
                                      journal=False, force=True)

    assert out["ok"] is True and out["changed"] is False
    assert out["retryable"] is True


# ---------------------------------------------------------------------------
# CR-293B (comp-resolve-3): the `.mp4` refusal belongs to the archive
# ---------------------------------------------------------------------------

def _item(path: str) -> dict:
    return {"file_path": path, "media_pool_uid": "u",
            "clip_name": os.path.basename(path),
            "proxy_path": "", "proxy_state": "None", "frames": 1000}


def _exists(path) -> bool:
    # Only the `.mp4` proxy is beside the original: the pre-R14 estate, and
    # the archive's browser preview, are the same shape on disk.
    p = str(path).replace("/", "\\").lower()
    return not (p.endswith(".mov") and "\\proxy\\" in p)


def _plan(path: str, notes: list, tmp_path) -> list:
    return proxy_relink.plan_relinks(
        [_item(path)], local_root=str(tmp_path), canonical_prefix="P:\\",
        is_windows=True, exists_fn=_exists, notes=notes,
        is_standin_fn=lambda p: False,
        frames_fn=lambda i: i.get("frames"),
        count_frames_fn=lambda p: 1000,
        stat_fn=lambda p: os.stat_result((0, 0, 0, 0, 0, 0, 7, 0, 1.0, 0)))


def test_a_legacy_project_mp4_proxy_is_still_attached(tmp_path):
    """Every `.mp4` proxy made before R14 (2026-08-19) is a real editing
    proxy, and proxy_scan states in capitals that they stay valid and are
    never re-made. The archive-preview refusal was unscoped, so an editor's
    project clip played the 6K original for ever with no op and no note."""
    notes: list = []
    project = "P:\\Projects\\FF5\\Media\\A001.mov"

    ops = _plan(project, notes, tmp_path)

    assert len(ops) == 1
    assert ops[0]["new_proxy"].lower().endswith("a001.mp4")
    assert notes == []


def test_an_archive_preview_is_still_refused_and_now_says_so(tmp_path):
    """Inside the archive the rule is right and stays - but a refusal nobody
    can see is what sent "why is my proxy not attached" to the RES-3 channel
    with nothing in it."""
    notes: list = []
    archive = "P:\\Assets\\B-roll Archive\\CIA_City\\cam-1-001.mov"

    ops = _plan(archive, notes, tmp_path)

    assert ops == []
    assert len(notes) == 1
    assert notes[0]["reason"] == proxy_relink.REASON_ARCHIVE_PREVIEW
    assert notes[0]["path"].lower().endswith("cam-1-001.mp4")
