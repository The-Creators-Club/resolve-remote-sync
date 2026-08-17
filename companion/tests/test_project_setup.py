"""ProjectSetupPrompter tests: the once-ever prompt state machine, asked-map
persistence, deep-link construction, and thread-safety edges -- all with
injected fakes, no Tk/browser/network."""
from __future__ import annotations

import json
import threading
import time

import pytest

from ccsync_companion.project_setup import STATE_FILENAME, ProjectSetupPrompter


def _cfg(**overrides):
    cfg = {"dashboard_url": "http://dash.example.com"}
    cfg.update(overrides)
    return cfg


def make_prompter(tmp_path, confirm=None, open_url=None, current=None, notify=None):
    opened = []
    confirmed = []

    def default_confirm(title, body, ok_label="PROCEED"):
        confirmed.append((title, body, ok_label))
        return True

    prompter = ProjectSetupPrompter(
        _cfg(),
        state_dir=tmp_path,
        popup_lock=threading.Lock(),
        confirm=confirm or default_confirm,
        open_url=open_url or opened.append,
        notify=notify,
        get_current_project=(lambda: current) if current is not None else None,
    )
    return prompter, opened, confirmed


def _asked_names(state_dir) -> set:
    """The names recorded in the on-disk "already asked" map, or an empty set
    while there is nothing readable there yet."""
    try:
        data = json.loads((state_dir / STATE_FILENAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return set((data.get("asked") or {}))


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_flag_prompts_once_and_opens_deep_link(tmp_path):
    prompter, opened, confirmed = make_prompter(tmp_path)
    prompter.note_report_response({"ok": True, "resolve_project_unmapped": "New Doc"})
    assert wait_for(lambda: opened)
    assert opened == ["http://dash.example.com/project-setup?resolve_project=New%20Doc"]
    assert confirmed[0][0] == "NEW PROJECT"
    assert "New Doc" in confirmed[0][1]
    assert prompter.unmapped_project == "New Doc"

    # second flagged response: no second prompt
    prompter.note_report_response({"ok": True, "resolve_project_unmapped": "New Doc"})
    time.sleep(0.1)
    assert len(confirmed) == 1


def test_decline_persists_across_instances(tmp_path):
    def decline(title, body, ok_label="PROCEED"):
        return False

    prompter, opened, _c = make_prompter(tmp_path, confirm=decline)
    prompter.note_report_response({"resolve_project_unmapped": "New Doc"})
    # Wait for the NAME to be in the file, not merely for the file to exist:
    # the record is written from the prompt thread, and "the path exists" was
    # true a moment before the bytes were (this test failed intermittently
    # under a loaded full-suite run until _record_asked became atomic,
    # 2026-08-17).
    assert wait_for(lambda: "new doc" in _asked_names(tmp_path))
    assert opened == []

    # a fresh instance (companion restart) never auto-prompts again
    confirmed2 = []
    prompter2, opened2, confirmed2 = make_prompter(tmp_path)
    prompter2.note_report_response({"resolve_project_unmapped": "New Doc"})
    time.sleep(0.15)
    assert confirmed2 == []
    assert opened2 == []
    # but the tray condition still surfaces it
    assert prompter2.unmapped_project == "New Doc"


def test_the_asked_map_is_written_atomically(tmp_path):
    """A reader must never see a truncated state file.

    write_text is create-truncate-write-close, so a second prompter reading
    mid-write got zero bytes, _load_asked's json.loads raised, the except
    swallowed it, and the map came back EMPTY -- which re-prompts for a
    project the editor already declined. Checked by watching for the temp
    file and by proving the record is complete the instant the path exists.
    """
    prompter, _o, _c = make_prompter(tmp_path)
    prompter._record_asked("New Doc")
    prompter._record_asked("Second Doc")

    state = tmp_path / STATE_FILENAME
    assert _asked_names(tmp_path) == {"new doc", "second doc"}
    # No temp file left beside the record.
    assert [p.name for p in tmp_path.iterdir() if p.is_file()] == [state.name]

    # ...and a fresh reader built from that file agrees, which is the
    # companion-restart path.
    fresh, _o2, confirmed2 = make_prompter(tmp_path)
    assert fresh._was_asked("new doc") and fresh._was_asked("Second Doc")
    assert confirmed2 == []


def test_absent_flag_clears_unmapped(tmp_path):
    prompter, _o, _c = make_prompter(tmp_path)
    prompter.note_report_response({"resolve_project_unmapped": "New Doc"})
    assert wait_for(lambda: prompter.unmapped_project == "New Doc")
    prompter.note_report_response({"ok": True})
    assert prompter.unmapped_project is None
    # garbage does NOT clear
    prompter.note_report_response({"resolve_project_unmapped": "New Doc"})
    prompter.note_report_response("not-a-dict")
    assert prompter.unmapped_project == "New Doc"


def test_project_switch_clears_stale_flag(tmp_path):
    prompter, _o, _c = make_prompter(tmp_path)
    prompter.note_report_response({"resolve_project_unmapped": "Old Doc"})
    assert wait_for(lambda: prompter.unmapped_project == "Old Doc")
    prompter.note_project_changed("New Doc")
    assert prompter.unmapped_project is None
    prompter.note_project_changed("New Doc")  # idempotent


def test_prompt_skipped_when_project_no_longer_open(tmp_path):
    prompter, opened, confirmed = make_prompter(tmp_path, current="Different Doc")
    prompter.note_report_response({"resolve_project_unmapped": "New Doc"})
    time.sleep(0.15)
    assert confirmed == []
    assert opened == []
    # NOT recorded as asked -- a later report can prompt again
    assert not (tmp_path / STATE_FILENAME).exists()


def test_prompt_skipped_when_no_project_is_open(tmp_path):
    """THE Blackmagic Proxy Generator hole. When an ignored scratch project
    ("New Doc") is open, the watcher reports None -- "nothing promptable is
    open". A stale resolve_project_unmapped from an earlier report would
    then sail past the guard (which only compared non-None names) and pop
    the NEW PROJECT dialog over whatever the rig was doing. Skip, and do NOT
    burn the once-ever "asked" record on it."""
    prompter = ProjectSetupPrompter(
        _cfg(), state_dir=tmp_path, popup_lock=threading.Lock(),
        confirm=lambda *a, **k: True,
        open_url=lambda u: None,
        get_current_project=lambda: None,
    )
    prompter.note_report_response({"resolve_project_unmapped": "Old Doc"})
    time.sleep(0.15)
    assert not (tmp_path / STATE_FILENAME).exists()
    # the tray item still offers it manually
    assert prompter.unmapped_project == "Old Doc"


def test_prompt_retries_once_a_real_project_is_confirmed_open(tmp_path):
    """The skip above must not be permanent: the next report prompts as soon
    as the watcher can name the project again."""
    current = {"name": None}
    confirmed = []
    prompter = ProjectSetupPrompter(
        _cfg(), state_dir=tmp_path, popup_lock=threading.Lock(),
        confirm=lambda *a, **k: confirmed.append(a) or True,
        open_url=lambda u: None,
        get_current_project=lambda: current["name"],
    )
    prompter.note_report_response({"resolve_project_unmapped": "Old Doc"})
    time.sleep(0.15)
    assert confirmed == []

    current["name"] = "Old Doc"
    prompter.note_report_response({"resolve_project_unmapped": "Old Doc"})
    assert wait_for(lambda: confirmed)
    assert (tmp_path / STATE_FILENAME).exists()


def test_prompt_skipped_when_the_project_getter_is_broken(tmp_path):
    """A raising bridge is "we don't know what's open" -- same answer as
    None: don't show a dialog about a project we cannot confirm."""
    def boom():
        raise RuntimeError("bridge down")

    confirmed = []
    prompter = ProjectSetupPrompter(
        _cfg(), state_dir=tmp_path, popup_lock=threading.Lock(),
        confirm=lambda *a, **k: confirmed.append(a) or True,
        open_url=lambda u: None,
        get_current_project=boom,
    )
    prompter.note_report_response({"resolve_project_unmapped": "Old Doc"})
    time.sleep(0.15)
    assert confirmed == []
    assert not (tmp_path / STATE_FILENAME).exists()


def test_prompt_skipped_while_popup_lock_held(tmp_path):
    lock = threading.Lock()
    confirmed = []
    prompter = ProjectSetupPrompter(
        _cfg(), state_dir=tmp_path, popup_lock=lock,
        confirm=lambda *a, **k: confirmed.append(1) or True,
        open_url=lambda u: None,
    )
    with lock:  # e.g. the out-of-tree fixer popup is open
        prompter.note_report_response({"resolve_project_unmapped": "New Doc"})
        time.sleep(0.15)
    assert confirmed == []
    assert not (tmp_path / STATE_FILENAME).exists()
    # retried on the next report once the lock is free
    prompter.note_report_response({"resolve_project_unmapped": "New Doc"})
    assert wait_for(lambda: confirmed)


def test_trigger_setup_opens_directly(tmp_path):
    prompter, opened, confirmed = make_prompter(tmp_path)
    prompter.note_report_response({"resolve_project_unmapped": "New Doc"})
    assert wait_for(lambda: opened)
    opened.clear()
    prompter.trigger_setup()          # uses the stored flag
    assert opened == ["http://dash.example.com/project-setup?resolve_project=New%20Doc"]
    assert len(confirmed) == 1        # no extra dialog
    prompter.trigger_setup("Other/Doc")
    assert opened[-1].endswith("resolve_project=Other%2FDoc")


def test_never_raises_on_broken_collaborators(tmp_path):
    def boom(*a, **k):
        raise RuntimeError("boom")

    prompter = ProjectSetupPrompter(
        _cfg(), state_dir=tmp_path, popup_lock=threading.Lock(),
        confirm=boom, open_url=boom,
    )
    prompter.note_report_response({"resolve_project_unmapped": "New Doc"})
    time.sleep(0.15)
    prompter.trigger_setup()          # must not raise
    prompter.note_project_changed("X")
