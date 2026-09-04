"""SYS-5: the customer explainer and the companion cannot drift apart again.

`docs/HOW_IT_WORKS.md` is the one document a customer is handed, and it is
served by this dashboard at `/help`. On 2026-09-03 its "the rest of the tray
menu" table listed nine items, five of which had not been in the menu since
CR-88 (2026-08-27) moved them into the companion's Settings window, which the
document did not mention at all. Nothing anywhere noticed for a fortnight,
because a document is exactly the kind of truth that drifts silently.

So this reads the companion's own source. The companion has its own venv and
is not importable from here, and it must not become a dependency of this
suite either, so the read is a regex over the file: the dashboard suite is
where this belongs (the dashboard is what serves the document), and a
scan test is the pattern the copy rules already use.

Two halves, and they fail differently on purpose:
  * a label that left `tray.py` / `settings_window.py` fails the "still in
    the source" half, which says: the product changed, fix the document;
  * a label that is in the source and not in the document fails the other
    half, which says the same thing from the other side.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs" / "HOW_IT_WORKS.md"
TRAY = REPO / "companion" / "src" / "ccsync_companion" / "tray.py"
SETTINGS_WINDOW = REPO / "companion" / "src" / "ccsync_companion" / "settings_window.py"

pytestmark = pytest.mark.skipif(
    not TRAY.is_file() or not SETTINGS_WINDOW.is_file(),
    reason="the companion tree is not in this checkout (a deployed dashboard)",
)

# The items the right-click menu shows on a healthy, signed-in computer: the
# CR-88 ten-item layout as `_build_menu` renders it today. Conditional items
# (the licence prompt, the two resume actions, the update offer, the YouTube
# stop) are deliberately not here -- a document that promised them would be
# wrong on every machine that is working.
ALWAYS_IN_THE_MENU = (
    "Sync now",
    "Open my sync drive",
    "Open dashboard",
    "Settings",
    "Restart CCSync",
)

# Items whose label the menu builds from state, matched on the stable half.
STATEFUL_MENU_ITEMS = (
    ("Pause syncing", "Pause syncing"),
    ("Take fleet jobs now", "Take fleet jobs now"),
    ("Quit CCSync", "Quit CCSync"),
)


def _menu_section() -> str:
    """Section 6.6 of the document, and nothing else."""
    text = DOC.read_text(encoding="utf-8")
    start = text.index("### 6.6 ")
    return text[start:text.index("### ", start + 8)]


def _settings_section() -> str:
    text = DOC.read_text(encoding="utf-8")
    start = text.index("### 6.7 ")
    return text[start:text.index("### ", start + 8)]


@pytest.mark.parametrize("label", ALWAYS_IN_THE_MENU)
def test_the_menu_labels_are_still_in_the_tray(label: str) -> None:
    assert f'MenuItem("{label}' in TRAY.read_text(encoding="utf-8"), (
        f"{label!r} is no longer a tray menu item: HOW_IT_WORKS.md section 6.6 "
        "describes it and has to change with it")


@pytest.mark.parametrize("label", ALWAYS_IN_THE_MENU)
def test_the_document_lists_every_menu_item(label: str) -> None:
    assert label in _menu_section(), (
        f"the tray menu has {label!r} and HOW_IT_WORKS.md section 6.6 does not")


@pytest.mark.parametrize("source_fragment,doc_fragment", STATEFUL_MENU_ITEMS)
def test_the_stateful_items_agree(source_fragment: str, doc_fragment: str) -> None:
    assert source_fragment in TRAY.read_text(encoding="utf-8")
    assert doc_fragment in _menu_section()


def test_the_document_promises_nothing_the_menu_dropped() -> None:
    """The five rows CR-88 moved into Settings, which the document kept for a
    fortnight after they stopped existing."""
    section = _menu_section()
    for gone in ("Open my project folder", "Grade from server originals",
                 "Copy diagnostics for your admin", "Open log", "| Advanced |"):
        assert gone not in section, (
            f"{gone!r} left the tray menu at CR-88 and lives in the Settings "
            "window (section 6.7)")


def _section_titles() -> list[str]:
    """Every `Section("TITLE", ...)` the settings window can build, plus the
    one that comes from a constant."""
    text = SETTINGS_WINDOW.read_text(encoding="utf-8")
    titles = set(re.findall(r'Section\(\s*"([A-Z][A-Z \']*)"', text))
    constant = re.search(r'^SYNCING_SECTION\s*=\s*"([^"]+)"', text, re.M)
    if constant:
        titles.add(constant.group(1))
    return sorted(titles)


def test_the_settings_sections_are_all_in_the_document() -> None:
    titles = _section_titles()
    # A regex that stopped matching would pass this test vacuously.
    assert len(titles) >= 6, f"only found {titles}: the scan has stopped working"
    section = _settings_section()
    missing = [title for title in titles if f"**{title}**" not in section]
    assert not missing, (
        "the companion's Settings window has sections HOW_IT_WORKS.md section "
        "6.7 does not describe: " + ", ".join(missing))


def test_the_document_describes_no_section_the_window_does_not_have() -> None:
    described = set(re.findall(r"\| \*\*([A-Z][A-Z \']*)\*\* \|", _settings_section()))
    unknown = sorted(described - set(_section_titles()))
    assert not unknown, (
        "HOW_IT_WORKS.md section 6.7 describes Settings sections that do not "
        "exist: " + ", ".join(unknown))


def test_the_help_buttons_the_document_names_exist() -> None:
    """SYS-21(a) put the document behind two buttons; section 6.7 says so."""
    text = SETTINGS_WINDOW.read_text(encoding="utf-8")
    for label in ("COPY DIAGNOSTICS FOR YOUR ADMIN", "HOW CC SYNC WORKS",
                  "WHAT DO THESE MEAN?"):
        assert label in text
        assert label in _settings_section()
