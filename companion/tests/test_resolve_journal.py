"""resolve_journal — the save point / undo journal behind every media-pool
edit (COMMERCIAL_READINESS.md item 9, 2026-08-17).

No Resolve anywhere: this module is pure bookkeeping, and the point of it
being pure is that the guarantee ("we can say what we changed") holds even
when Resolve refuses to export.
"""

from __future__ import annotations

import json
import threading

import pytest

from ccsync_companion import resolve_journal


@pytest.fixture(autouse=True)
def _fresh_journal():
    """The module keeps its open-burst and rate-limit state in globals (one
    companion, one Resolve), so without this a test inherits the previous
    one's session. conftest's _isolate_ccsync_home already redirects HOME."""
    resolve_journal.reset_for_tests()
    yield
    resolve_journal.reset_for_tests()


class TestSlug:
    def test_a_project_name_can_never_escape_the_journal_directory(self):
        # Resolve project names carry / and : freely.
        slug = resolve_journal.project_slug(r"FF4 / interviews: v2.")
        assert "/" not in slug and "\\" not in slug and ":" not in slug
        assert not slug.endswith(".")

    def test_blank_names_still_get_a_directory(self):
        assert resolve_journal.project_slug("") == "_unknown"
        assert resolve_journal.project_slug(None) == "_unknown"


class TestRecording:
    def test_one_burst_is_one_file(self):
        for i in range(3):
            resolve_journal.record(
                resolve_journal.KIND_REPLACE_CLIP, "FF5",
                clip_name=f"A00{i}", old_path=f"F:/a{i}.mov", new_path=f"P:/a{i}.mov",
                source="fix-all",
            )
        files = resolve_journal.sessions("FF5")
        assert len(files) == 1
        entries = resolve_journal.read_session(files[0])["entries"]
        assert [e["new"] for e in entries] == ["P:/a0.mov", "P:/a1.mov", "P:/a2.mov"]
        assert {e["source"] for e in entries} == {"fix-all"}

    def test_a_quiet_gap_starts_a_new_file(self):
        clock = [1000.0]
        resolve_journal.record(resolve_journal.KIND_REPLACE_CLIP, "FF5",
                               new_path="P:/a.mov", clock=lambda: clock[0])
        clock[0] += resolve_journal.SESSION_GAP_SECONDS + 1
        resolve_journal.record(resolve_journal.KIND_REPLACE_CLIP, "FF5",
                               new_path="P:/b.mov", clock=lambda: clock[0])
        assert len(resolve_journal.sessions("FF5")) == 2

    def test_the_file_is_valid_json_with_the_project_and_save_point(self):
        resolve_journal.note_save_point("FF5", saved=True, backup="C:/x/FF5.drp")
        resolve_journal.record(resolve_journal.KIND_REPLACE_CLIP, "FF5",
                               old_path="F:/a.mov", new_path="P:/a.mov")
        path = resolve_journal.latest_session("FF5")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["project"] == "FF5"
        assert data["saved"] is True
        assert data["backup"] == "C:/x/FF5.drp"
        assert data["entries"][0]["old"] == "F:/a.mov"

    def test_a_proxy_entry_remembers_which_clip_it_belonged_to(self):
        # old/new are PROXY paths for a proxy repoint, so the clip's own path
        # is the only thing that identifies it on the way back.
        resolve_journal.record(
            resolve_journal.KIND_LINK_PROXY, "FF5", clip_name="A001",
            clip_path="P:/x/A001.braw", old_path="", new_path="P:/x/Proxy/A001.mov",
        )
        entry = resolve_journal.read_session(
            resolve_journal.latest_session("FF5"))["entries"][0]
        assert entry["clip_path"] == "P:/x/A001.braw"

    def test_one_file_is_bounded(self, monkeypatch):
        monkeypatch.setattr(resolve_journal, "MAX_ENTRIES_PER_SESSION", 3)
        for i in range(10):
            resolve_journal.record(resolve_journal.KIND_REPLACE_CLIP, "FF5",
                                   new_path=f"P:/{i}.mov")
        entries = resolve_journal.read_session(
            resolve_journal.latest_session("FF5"))["entries"]
        assert len(entries) == 3

    def test_an_unwritable_home_does_not_raise(self, monkeypatch):
        # A relink that fixes Media Offline must not be stopped by a journal
        # that cannot be written.
        def boom(*a, **kw):
            raise OSError("read-only")

        monkeypatch.setattr(resolve_journal, "_write", boom)
        assert resolve_journal.record(
            resolve_journal.KIND_REPLACE_CLIP, "FF5", new_path="P:/a.mov") is None


class TestRateLimit:
    def test_the_first_automatic_pass_always_wins(self):
        assert resolve_journal.allow_automatic("FF5", "canon-relink") is True

    def test_a_second_pass_inside_the_window_is_refused(self):
        clock = [100.0]
        assert resolve_journal.allow_automatic("FF5", "canon-relink",
                                               clock=lambda: clock[0]) is True
        clock[0] += 10
        assert resolve_journal.allow_automatic("FF5", "canon-relink",
                                               clock=lambda: clock[0]) is False

    def test_the_window_expires(self):
        clock = [100.0]
        resolve_journal.allow_automatic("FF5", "canon-relink", clock=lambda: clock[0])
        clock[0] += resolve_journal.AUTOMATIC_MIN_INTERVAL_SECONDS + 1
        assert resolve_journal.allow_automatic("FF5", "canon-relink",
                                               clock=lambda: clock[0]) is True

    def test_projects_and_sources_are_limited_independently(self):
        assert resolve_journal.allow_automatic("FF5", "canon-relink") is True
        assert resolve_journal.allow_automatic("FF6", "canon-relink") is True
        assert resolve_journal.allow_automatic("FF5", "auto-proxy-relink") is True
        assert resolve_journal.allow_automatic("FF5", "canon-relink") is False

    def test_seconds_until_does_not_claim_the_slot(self):
        assert resolve_journal.seconds_until_automatic("FF5", "canon-relink") == 0.0
        assert resolve_journal.allow_automatic("FF5", "canon-relink") is True
        assert resolve_journal.seconds_until_automatic("FF5", "canon-relink") > 0


class TestSavePointInterval:
    def test_the_first_edit_of_a_project_takes_a_save_point(self):
        assert resolve_journal.save_point_due("FF5", clock=lambda: 0.0) is True

    def test_a_second_edit_moments_later_does_not(self):
        clock = [0.0]
        resolve_journal.save_point_due("FF5", clock=lambda: clock[0])
        clock[0] += 1
        assert resolve_journal.save_point_due("FF5", clock=lambda: clock[0]) is False

    def test_a_later_burst_does(self):
        clock = [0.0]
        resolve_journal.save_point_due("FF5", clock=lambda: clock[0])
        clock[0] += resolve_journal.SAVE_POINT_INTERVAL_SECONDS + 1
        assert resolve_journal.save_point_due("FF5", clock=lambda: clock[0]) is True


def test_old_journals_are_swept():
    import os
    import time

    old_clock = time.time() - (resolve_journal.RETENTION_DAYS + 1) * 86400
    resolve_journal.record(resolve_journal.KIND_REPLACE_CLIP, "FF5",
                           new_path="P:/a.mov", clock=lambda: old_clock)
    stale = resolve_journal.latest_session("FF5")
    os.utime(stale, (old_clock, old_clock))
    resolve_journal.reset_for_tests()

    resolve_journal.record(resolve_journal.KIND_REPLACE_CLIP, "FF5", new_path="P:/b.mov")
    remaining = resolve_journal.sessions("FF5")
    assert stale not in remaining
    assert len(remaining) == 1


def test_old_rollback_exports_are_swept_too():
    """comp-resolve-4, 2026-08-21: only `*.json` was ever swept, so the `.drp`
    save_project() exports beside them grew in the editor's home forever --
    while RESOLVE_EDIT_SAFETY.md's Housekeeping told the admin they did not."""
    import os
    import time

    old_clock = time.time() - (resolve_journal.RETENTION_DAYS + 1) * 86400
    resolve_journal.record(resolve_journal.KIND_REPLACE_CLIP, "FF5",
                           new_path="P:/a.mov", clock=lambda: old_clock)
    stale_export = resolve_journal.journal_root() / "FF5" / "20260101-000000.drp"
    stale_export.write_bytes(b"drp")
    os.utime(stale_export, (old_clock, old_clock))
    fresh_export = resolve_journal.journal_root() / "FF5" / "20260820-000000.drp"
    fresh_export.write_bytes(b"drp")
    resolve_journal.reset_for_tests()

    # A new burst is what runs the sweep.
    resolve_journal.record(resolve_journal.KIND_REPLACE_CLIP, "FF5", new_path="P:/b.mov")

    assert not stale_export.exists()
    assert fresh_export.exists()


class TestRateLimitSurvivesARestart:
    """RES-2 (resilience sweep 2026-08-28): the two bars on the UNPROMPTED
    rewrites were module globals, so an OTA, a crash, an EULA park or the
    editor reopening the tray reset them -- and a machine with a wrong
    canonical_prefix then rewrote hundreds of clip paths again on every
    launch."""

    @staticmethod
    def _restart():
        """Everything a new process loses, without losing the disk state."""
        resolve_journal._automatic_at.clear()
        resolve_journal._automatic_daily.clear()
        resolve_journal._auto_state_loaded = False

    def test_the_window_is_still_barred_after_a_restart(self):
        clock = [1_750_000_000.0]
        assert resolve_journal.allow_automatic(
            "FF5", "canon-relink", clock=lambda: clock[0]) is True
        assert resolve_journal.auto_state_path().exists()

        self._restart()
        clock[0] += 60
        assert resolve_journal.allow_automatic(
            "FF5", "canon-relink", clock=lambda: clock[0]) is False

        self._restart()
        clock[0] += resolve_journal.AUTOMATIC_MIN_INTERVAL_SECONDS
        assert resolve_journal.allow_automatic(
            "FF5", "canon-relink", clock=lambda: clock[0]) is True

    def test_a_stamp_from_the_future_is_treated_as_now(self):
        """A clock put back (or a state file copied off another machine) must
        not bar the pass until the date arrives."""
        resolve_journal.allow_automatic(
            "FF5", "canon-relink", clock=lambda: 2_000_000_000.0)
        self._restart()
        now = 1_750_000_000.0
        assert resolve_journal.allow_automatic(
            "FF5", "canon-relink", clock=lambda: now) is False
        self._restart()
        assert resolve_journal.allow_automatic(
            "FF5", "canon-relink",
            clock=lambda: now + resolve_journal.AUTOMATIC_MIN_INTERVAL_SECONDS + 1,
        ) is True

    def test_unreadable_state_does_not_stop_a_relink(self, monkeypatch):
        resolve_journal.auto_state_path().parent.mkdir(parents=True, exist_ok=True)
        resolve_journal.auto_state_path().write_text("{not json", encoding="utf-8")
        self._restart()
        assert resolve_journal.allow_automatic("FF5", "canon-relink") is True


class TestDailyCap:
    def test_a_project_gets_at_most_N_automatic_rewrites_a_day(self, caplog):
        clock = [1_750_000_000.0]
        step = resolve_journal.AUTOMATIC_MIN_INTERVAL_SECONDS + 1
        allowed = 0
        for _ in range(20):
            if resolve_journal.allow_automatic("FF5", "canon-relink",
                                               clock=lambda: clock[0]):
                allowed += 1
            clock[0] += step
        assert allowed == resolve_journal.AUTOMATIC_MAX_PER_DAY

    def test_the_cap_says_what_to_do_about_it(self, caplog):
        clock = [1_750_000_000.0]
        step = resolve_journal.AUTOMATIC_MIN_INTERVAL_SECONDS + 1
        with caplog.at_level("WARNING"):
            for _ in range(resolve_journal.AUTOMATIC_MAX_PER_DAY + 2):
                resolve_journal.allow_automatic("FF5", "canon-relink",
                                                clock=lambda: clock[0])
                clock[0] += step
        assert "configuration problem" in caplog.text
        # The wording the tray really uses (bug-hunt-2026-09-03 comp-ui-2):
        # there is no Copy diagnostics item in the right-click menu, it is a
        # button inside Settings.
        assert "Tray > Settings > COPY DIAGNOSTICS FOR YOUR ADMIN" in caplog.text

    def test_the_next_day_is_a_new_allowance(self):
        clock = [1_750_000_000.0]
        step = resolve_journal.AUTOMATIC_MIN_INTERVAL_SECONDS + 1
        for _ in range(resolve_journal.AUTOMATIC_MAX_PER_DAY + 3):
            resolve_journal.allow_automatic("FF5", "canon-relink",
                                            clock=lambda: clock[0])
            clock[0] += step
        assert resolve_journal.allow_automatic(
            "FF5", "canon-relink", clock=lambda: clock[0]) is False
        clock[0] += 86400
        assert resolve_journal.allow_automatic(
            "FF5", "canon-relink", clock=lambda: clock[0]) is True

    def test_the_cap_is_per_project(self):
        clock = [1_750_000_000.0]
        step = resolve_journal.AUTOMATIC_MIN_INTERVAL_SECONDS + 1
        for _ in range(resolve_journal.AUTOMATIC_MAX_PER_DAY + 3):
            resolve_journal.allow_automatic("FF5", "canon-relink",
                                            clock=lambda: clock[0])
            clock[0] += step
        assert resolve_journal.allow_automatic(
            "FF5", "canon-relink", clock=lambda: clock[0]) is False
        assert resolve_journal.allow_automatic(
            "FF6", "canon-relink", clock=lambda: clock[0]) is True

    def test_the_cap_counts_both_unprompted_sources_together(self):
        """Two sources rewriting the same project all day is one fault seen
        twice, not two allowances."""
        clock = [1_750_000_000.0]
        step = resolve_journal.AUTOMATIC_MIN_INTERVAL_SECONDS + 1
        allowed = 0
        for i in range(30):
            source = "canon-relink" if i % 2 else "auto-proxy-relink"
            if resolve_journal.allow_automatic("FF5", source,
                                               clock=lambda: clock[0]):
                allowed += 1
            clock[0] += step
        assert allowed == resolve_journal.AUTOMATIC_MAX_PER_DAY


class TestConcurrentRecording:
    """bug-hunt-2026-09-03 comp-resolve-1. FIX ALL (tray thread), the 120 s
    proxy-relink pass (media-tree thread), the watcher's automatic relink and
    a b-roll /insert canonicalisation (HTTP thread) all record into the same
    burst file, and none of them holds the bridge's API lock while they do.
    An unlocked read-append-write lost all but a handful of the entries -- an
    edit undo_last_relink would then silently not put back."""

    def test_every_thread_s_entry_survives(self):
        threads = []
        errors: list[BaseException] = []
        start = threading.Barrier(8)

        def worker(n: int) -> None:
            try:
                start.wait(10)
                for i in range(20):
                    resolve_journal.record(
                        resolve_journal.KIND_REPLACE_CLIP, "FF5",
                        clip_name=f"t{n}-{i}", old_path=f"F:/{n}-{i}.mov",
                        new_path=f"P:/{n}-{i}.mov", source="fix-all",
                    )
            except BaseException as exc:                      # pragma: no cover
                errors.append(exc)

        for n in range(8):
            thread = threading.Thread(target=worker, args=(n,), daemon=True)
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join(60)

        assert not errors
        files = resolve_journal.sessions("FF5")
        assert len(files) == 1
        names = {e["clip"] for e in resolve_journal.read_session(files[0])["entries"]}
        assert names == {f"t{n}-{i}" for n in range(8) for i in range(20)}

    def test_the_tmp_file_is_not_shared_between_writers(self, tmp_path):
        """On Windows the loser of the fixed-name race gets a PermissionError
        out of os.replace, not merely a lost entry."""
        first = resolve_journal._tmp_path(tmp_path / "a.json")
        seen = []

        def other() -> None:
            seen.append(resolve_journal._tmp_path(tmp_path / "a.json"))

        thread = threading.Thread(target=other)
        thread.start()
        thread.join(10)
        assert seen and seen[0] != first
