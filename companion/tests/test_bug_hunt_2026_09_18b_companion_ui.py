"""The 2026-09-18b mediums wave, companion UI (CR-292).

comp-ui-1 and comp-ui-4 are the two halves CR-283P's rehearsal screen missed:
the FIRST file of a FIX ALL rehearsal, and the whole CONSOLIDATE window. No
test here opens a Tk root: `perform_fix_all` is pure worker-thread code, and
ProgressWindow._tick is driven against stand-in widgets (its __init__ makes
none).
"""
from __future__ import annotations

from typing import Any

import pytest

from ccsync_companion import fixer, popup


@pytest.fixture
def rehearsing(monkeypatch):
    """`fixer_dry_run = true` on this machine, cache reset both ways."""
    fixer.reset_dry_run_cache()
    monkeypatch.setattr(fixer, "dry_run_default", lambda: True)
    yield
    fixer.reset_dry_run_cache()


# -- comp-ui-1: the FIRST file of a rehearsal ------------------------------


def test_the_first_file_of_a_rehearsal_is_already_checking(tmp_path, monkeypatch,
                                                           rehearsing):
    """comp-ui-1: `rehearsing` was learned from the first `dry_run` ANSWER,
    and the progress keys for a file are published BEFORE the copy is called.
    So file 1 of every rehearsal - and the whole run when there is one dead
    link, the common FIX ALL case - was published with the real byte totals
    and drew `Copying "a.braw": 0 B of 12.7 GB` under two bars that never
    move, which is the exact screen CR-283P was written to remove.
    """
    path = tmp_path / "a.braw"
    path.write_bytes(b"x" * 1024)
    rows = [{"file_path": str(path), "clip_name": "a.braw",
             "suggested_dest": "Footage/a.braw", "media_pool_items": []}]

    # The product path passes NO fix_clip_fn; stub the call seam so the real
    # fixer.fix_clip (and Resolve with it) is never reached.
    monkeypatch.setattr(popup, "call_fix_clip",
                        lambda *a, **k: {"ok": True, "dry_run": True,
                                         "message": "would copy"})

    published: list[dict[str, Any]] = []
    popup.perform_fix_all(rows, {}, str(tmp_path), state_fn=published.append)

    mid = [p for p in published if p.get("name")]
    assert mid, "the per-file publishes are the screen under test"
    first = mid[0]
    assert first["rehearsing"] is True
    assert first["file_bytes_total"] == 0
    assert first["batch_bytes_total"] == 0
    assert popup.format_file_progress(
        first["name"], first["file_bytes_done"], first["file_bytes_total"],
        None, None, rehearsal=bool(first["rehearsing"])) == 'Checking "a.braw"'


def test_an_injected_fix_clip_still_decides_its_own_rehearsal(tmp_path, monkeypatch,
                                                              rehearsing):
    """comp-ui-1: the seed is only for the real fixer. A caller that injects
    its own copier (every test double, and anything embedding this loop) is
    not governed by this machine's `fixer_dry_run`, so its first file must
    still be published as a real copy."""
    path = tmp_path / "b.braw"
    path.write_bytes(b"x" * 2048)
    rows = [{"file_path": str(path), "clip_name": "b.braw",
             "suggested_dest": "Footage/b.braw", "media_pool_items": []}]

    published: list[dict[str, Any]] = []
    popup.perform_fix_all(rows, {}, str(tmp_path),
                          fix_clip_fn=lambda *a, **k: {"ok": True},
                          state_fn=published.append)

    first = [p for p in published if p.get("name")][0]
    assert first["rehearsing"] is False
    assert first["file_bytes_total"] == 2048


# -- comp-ui-4: the CONSOLIDATE window -------------------------------------


class _Label:
    def __init__(self) -> None:
        self.text = ""

    def config(self, **kw: Any) -> None:
        self.text = kw.get("text", self.text)


class _Bar(dict):
    """A ttk.Progressbar answers to item assignment and nothing else here."""


def _headless_window() -> popup.ProgressWindow:
    """A ProgressWindow with stand-in widgets and a root that only schedules.

    ProgressWindow.__init__ builds NO Tk objects (the widgets are made in
    _build_and_show), so this needs no display and frees no interpreter -
    CR-93 is not in play.
    """
    window = popup.ProgressWindow("COPYING THIS PROJECT'S MEDIA IN")
    window._file_label = _Label()
    window._batch_label = _Label()
    window._file_bar = _Bar()
    window._batch_bar = _Bar()

    class _Root:
        def after(self, *_a: Any) -> None:
            pass

    window.root = _Root()
    return window


def test_the_consolidate_window_says_checking_on_a_rehearsal(rehearsing):
    """comp-ui-4: run_consolidation publishes the real `file_bytes_total` /
    `batch_bytes_total` and no `rehearsing` key, so the consolidate window sat
    at `File 7 of 412: 0 B of 800 GB done` with "Copying" beside each clip for
    a whole rehearsal. _tick now falls back to the cached `fixer_dry_run`
    answer when the publisher says nothing."""
    window = _headless_window()
    window.publish({"index": 7, "total": 412, "name": "A001_C012.braw",
                    "file_bytes_done": 0, "file_bytes_total": 12_700_000_000,
                    "batch_bytes_done": 0, "batch_bytes_total": 800_000_000_000})
    window._tick()

    assert window._file_label.text == 'Checking "A001_C012.braw"'
    assert window._batch_label.text == "File 7 of 412"
    assert window._batch_bar["value"] == int(1000 * 7 / 412)
    assert window._file_bar["value"] == 0


def test_a_real_consolidate_copy_is_untouched(monkeypatch):
    """comp-ui-4: the fallback must not change the screen of the run everyone
    actually does. With `fixer_dry_run` off the window still says Copying and
    still draws its batch bar off bytes."""
    fixer.reset_dry_run_cache()
    monkeypatch.setattr(fixer, "dry_run_default", lambda: False)
    window = _headless_window()
    window.publish({"index": 2, "total": 4, "name": "A001_C012.braw",
                    "file_bytes_done": 500, "file_bytes_total": 1000,
                    "batch_bytes_done": 500, "batch_bytes_total": 2000})
    window._tick()

    assert window._file_label.text.startswith('Copying "A001_C012.braw"')
    assert "of" in window._batch_label.text and "done" in window._batch_label.text
    assert window._batch_bar["value"] == 250
    assert window._file_bar["value"] == 500


def test_the_upload_phase_headline_is_never_a_rehearsal(rehearsing):
    """comp-ui-4: a phase with its own headline (the lane A upload) carries
    real bytes, so the fallback must leave it alone. A rehearsal never reaches
    it - app.py skips the upload when nothing was copied in - and if the two
    ever meet, real progress must not be relabelled as a rehearsal."""
    window = _headless_window()
    window.publish({"headline": "Uploading to the server", "index": 1, "total": 1,
                    "batch_bytes_done": 500, "batch_bytes_total": 1000})
    window._tick()

    assert window._batch_label.text.endswith("done")
    assert window._batch_bar["value"] == 500
