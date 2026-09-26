"""The stand-in ledger: what this machine has lied about, and to whom.

docs/BROLL_PROXY_TIERS_PLAN.md section 6, phase 3 task 1 (2026-09-17).
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest

from ccsync_companion import broll_fetch, broll_server, broll_standins
from ccsync_companion.sync import sequencer


@pytest.fixture
def led(tmp_path):
    """A ledger of its own per test -- the module singleton is a process
    singleton and would otherwise leak between tests."""
    ledger = broll_standins.configure(tmp_path / "state" / "broll_standins.json")
    yield ledger
    broll_standins.configure(broll_standins.default_state_path())


def _standin(tmp_path, name="clip.mov", body=b"preview bytes"):
    path = tmp_path / name
    path.write_bytes(body)
    return path


def test_an_entry_survives_a_restart(led, tmp_path):
    """Never in memory only: the file is the ledger, and a second ledger
    object reading the same path sees the same entry."""
    path = _standin(tmp_path)
    led.record(path, share="broll", rel_path="cc/clip.mov",
               original_rel="cc/clip.mov", preview_rel="cc/Proxy/clip.mp4",
               edit_proxy_rel="cc/Proxy/clip.mov",
               geometry={"width": 1920, "height": 1080})

    reborn = broll_standins.StandinLedger(led.path)

    assert reborn.is_standin(path) is True
    entry = reborn.get(path)
    assert entry["edit_proxy_rel"] == "cc/Proxy/clip.mov"
    assert entry["geometry"]["width"] == 1920
    assert entry["local_path"] == str(path)


def test_a_path_nobody_recorded_is_not_a_standin(led, tmp_path):
    assert broll_standins.is_standin(_standin(tmp_path)) is False
    assert broll_standins.all() == []


def test_forget_drops_the_entry_and_says_whether_there_was_one(led, tmp_path):
    path = _standin(tmp_path)
    led.record(path)

    assert led.forget(path) is True
    assert led.is_standin(path) is False
    assert led.forget(path) is False


def test_the_key_folds_case_separators_and_unicode_form(led, tmp_path):
    """CR-90: a path a Mac reported is not `==` a path anything else
    reported, and Windows folds case. One file, one entry, either spelling."""
    folder = tmp_path / "Matej \u0160imal\u010d\u00edk"
    folder.mkdir()
    path = folder / "clip.mov"
    path.write_bytes(b"preview")
    led.record(path)

    decomposed = unicodedata.normalize("NFD", str(path))

    assert led.is_standin(decomposed) is True
    assert led.get(decomposed) is not None
    # ...and one entry, not two.
    led.record(decomposed)
    assert len(led.all()) == 1


def test_a_replaced_stand_in_is_stale_not_a_stand_in(led, tmp_path):
    """The real original arriving at that path is what falsifies the entry:
    a different size means the lie is gone, and the clip Resolve built from
    the stand-in now needs its one replace_clip (spike, second half)."""
    path = _standin(tmp_path, body=b"preview bytes")
    led.record(path)

    path.write_bytes(b"the real 6K original, much longer than the preview")

    assert led.is_standin(path) is False
    assert led.is_stale(path) is True


def test_an_absent_file_leaves_the_entry_standing(led, tmp_path):
    path = _standin(tmp_path)
    led.record(path)
    path.unlink()

    assert led.is_standin(path) is True
    assert led.is_stale(path) is False


def test_a_corrupt_file_is_an_empty_ledger_and_one_warning(led, tmp_path, caplog):
    led.path.parent.mkdir(parents=True, exist_ok=True)
    led.path.write_text("{not json", encoding="utf-8")

    with caplog.at_level("WARNING", logger="ccsync.broll"):
        assert led.all() == []
        assert led.is_standin(tmp_path / "clip.mov") is False
        assert led.all() == []

    warnings = [r for r in caplog.records if "not readable JSON" in r.getMessage()]
    assert len(warnings) == 1


def test_a_write_that_cannot_land_is_not_an_exception(led, tmp_path, monkeypatch):
    """A ledger that cannot be persisted costs a forgotten stand-in, never
    an insert.

    tests-4 (2026-09-18): this used to monkeypatch `_persist_locked` -- the
    exact function whose failure it claims to cover -- with
    `lambda self: False`, so it proved only that a False return is tolerated.
    The real one catches OSError and nothing else, and `json.dumps` sits
    inside that try. Raise from the things that raise.
    """
    import os as os_mod

    def boom(*args, **kwargs):
        raise OSError("the disk is full")

    monkeypatch.setattr(os_mod, "replace", boom)

    entry = led.record(_standin(tmp_path))

    assert entry["local_path"].endswith("clip.mov")
    assert led.all() == [], "a write that did not land left nothing behind"


def test_record_logs_the_warning_that_names_the_stand_in(led, tmp_path, caplog):
    """Plan section 6's third reader, v1: one WARNING at insert time. No
    dialog, but the log names the file a render would render."""
    with caplog.at_level("WARNING", logger="ccsync.broll"):
        led.record(_standin(tmp_path))

    assert any("now holds the PREVIEW's bytes" in r.getMessage()
               for r in caplog.records)


def test_pending_upgrades_are_the_ones_still_owed(led, tmp_path):
    with_proxy = _standin(tmp_path, "a.mov")
    without = _standin(tmp_path, "b.mov")
    led.record(with_proxy, edit_proxy_rel="cc/Proxy/a.mov",
               upgrade=broll_standins.UPGRADE_PENDING)
    led.record(without, edit_proxy_rel=None,
               upgrade=broll_standins.UPGRADE_PENDING)

    pending = led.pending_upgrades()

    assert [entry["local_path"] for entry in pending] == [str(with_proxy)]

    led.set_upgrade(with_proxy, broll_standins.UPGRADE_DONE)
    assert led.pending_upgrades() == []
    assert led.get(with_proxy)["upgrade"] == broll_standins.UPGRADE_DONE


def test_an_upgrade_state_for_an_unknown_path_changes_nothing(led, tmp_path):
    assert led.set_upgrade(tmp_path / "nobody.mov",
                           broll_standins.UPGRADE_DONE) is False


def test_the_file_on_disk_is_json_with_a_version(led, tmp_path):
    led.record(_standin(tmp_path))

    data = json.loads(led.path.read_text(encoding="utf-8"))

    assert data["version"] == 1
    assert len(data["standins"]) == 1


def test_a_second_process_writing_the_file_is_seen(led, tmp_path):
    """The one-shot Resolve worker and a future CLI are other processes; the
    memory in front of the file is a cache, not the truth."""
    path = _standin(tmp_path)
    led.record(path)
    other = broll_standins.StandinLedger(led.path)
    assert other.is_standin(path) is True

    led.forget(path)

    assert other.is_standin(path) is False


# ---------------------------------------------------------------------------
# The archive prefix, and the three constants that must stay in step
# ---------------------------------------------------------------------------


def test_the_archive_rel_matches_both_of_its_other_copies():
    assert broll_standins.ARCHIVE_REL == broll_server.BROLL_ARCHIVE_REL
    assert "/".join(broll_standins.ARCHIVE_REL) == broll_fetch.ARCHIVE_REMOTE_REL


@pytest.mark.parametrize("path,expected", [
    (r"P:\Assets\B-roll Archive\cc\clip.mov", True),
    (r"p:/assets/b-roll archive/cc/clip.mov", True),
    (r"P:\Projects\ff5\clip.mov", False),
    (r"F:\Creators_Club\Assets\B-roll Archive\cc\clip.mov", True),
    (r"F:\Creators_Club\Projects\ff5\clip.mov", False),
    ("", False),
])
def test_is_under_archive_judges_both_spellings(path, expected):
    assert broll_standins.is_under_archive(
        path, local_root=r"F:\Creators_Club", canonical_prefix="P:\\") is expected


# ---------------------------------------------------------------------------
# Reader 2 (plan section 6): lane A must never upload a stand-in
# ---------------------------------------------------------------------------


def test_lane_a_can_never_see_the_archive_at_all():
    """The plan names lane A's upload filter as a reader of this ledger. It
    does not need to be one, and this test is why (2026-09-17): every lane A
    run is scoped to `Projects/<rel_path>` of ONE selected project, and a
    rel_path that could climb out of it is refused before any path is built.
    So `Assets/B-roll Archive`, where every stand-in lives, is never inside a
    lane A source. Code in the filter would be dead code; a test is the
    honest form of the guarantee, and it fails the day the scope widens."""
    assert sequencer.PROJECTS_PREFIX == "Projects/"

    # The one place lane A is given a scope, and what it is given.
    source = Path(sequencer.__file__).read_text(encoding="utf-8")
    lane_a_calls = [line.strip() for line in source.splitlines()
                    if "_run_lane(self.lane_a" in line]
    # may_hand_off (CR-347, 2026-09-26) changes when lane A returns, never
    # what it is scoped to: a handed-off child keeps this same subpath.
    assert lane_a_calls == [
        'outcomes["a"] = self._run_lane(self.lane_a, subpath, budget, may_hand_off=True)']
    assert 'subpath = f"{PROJECTS_PREFIX}{rel_path}"' in source

    # ...and that rel cannot climb back out into Assets/.
    assert sequencer._item_rel({"rel_path": "../Assets/B-roll Archive"}) is None
    assert sequencer._item_rel({"rel_path": "/Assets/B-roll Archive"}) is None
    assert sequencer._item_rel({"rel_path": "2026/CCT/Show"}) == "2026/CCT/Show"
