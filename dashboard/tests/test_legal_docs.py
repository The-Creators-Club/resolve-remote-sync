"""LG-16's legal-document drift pins (docs/LEGAL_GAP_FEATURES_PLAN.md §5, G9,
2026-09-25).

The five documents in docs/legal/ are counsel-cleared text. They describe
the product as it is, and where a missing feature would change a statement
they carry an `<!-- ENG-GAP: <id> -->` marker on the paragraph that says so.
A marker is removed only by replacing that paragraph with the plan's §8
wording once the feature exists in the tree. These tests make the two ways
that goes wrong loud:

* a marker removed without its paragraph being rewritten, or a new one
  added, changes the set below, so the change has to be made on purpose;
* a marker with a misspelt id is not one of the six the plan names.

Plus the two facts every other reader of these files relies on: the version
lines parse (the EULA's matches its `EULA-VERSION` marker, which is what
sends editors back through acceptance), and the three EULA copies are
byte-identical (the /setup copy, the companion's and the wizard's).
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pytest

from ccsync_dashboard import setup_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
LEGAL = REPO_ROOT / "docs" / "legal"

DOCUMENTS = ("EULA.md", "PRIVACY.md", "TELEMETRY.md", "THIRD_PARTY_NOTICES.md",
             "YOUTUBE_FEATURE_NOTICE.md")

# THIRD_PARTY_NOTICES is generated around a hand block and carries no
# version line of its own; the other four do.
VERSIONED = ("EULA.md", "PRIVACY.md", "TELEMETRY.md", "YOUTUBE_FEATURE_NOTICE.md")

# The six ids the cleared documents use (plan §1). Anything else is a typo.
KNOWN_ENG_GAPS = frozenset({
    "telemetry-opt-out-switches",       # LG-1
    "telemetry-export",                 # LG-2
    "per-editor-telemetry-purge",       # LG-3
    "refuse-cleartext-dashboard-url",   # LG-4
    "companion-frozen-psycopg2",        # LG-11
    "prune-last-run-visibility",        # LG-17
})

# The markers still in the text, as (document, id). EMPTY since
# 2026-09-25: the last two (LG-1, `telemetry-opt-out-switches`, in PRIVACY
# section 6 and TELEMETRY "What can be turned off") were replaced with plan
# section 8.1 as amended in the G9 ledger once the site half landed
# (`api_site` publishes `telemetry`, FIELDS carries the undo_detail rows).
# A new marker is a new gap and has to be added here on purpose.
EXPECTED_ENG_GAPS: frozenset[tuple[str, str]] = frozenset()

_MARKER = re.compile(r"<!--\s*ENG-GAP:\s*([^\s>]+)\s*-->")
_VERSION_LINE = re.compile(
    r"^\*\*Version (\d+\.\d+), (\d{4}-\d{2}-\d{2})\.\*\*", re.MULTILINE)


def _text(name: str) -> str:
    return (LEGAL / name).read_text(encoding="utf-8")


def _markers() -> set[tuple[str, str]]:
    return {(name, m.group(1)) for name in DOCUMENTS
            for m in _MARKER.finditer(_text(name))}


def test_every_document_is_there():
    missing = [name for name in DOCUMENTS if not (LEGAL / name).is_file()]
    assert not missing, f"docs/legal/ has lost {missing}"


@pytest.mark.parametrize("name", VERSIONED)
def test_the_version_line_parses(name):
    found = _VERSION_LINE.findall(_text(name))
    assert len(found) == 1, (
        f"{name}: expected exactly one '**Version x.y, YYYY-MM-DD.**' line, "
        f"found {len(found)}")
    version, date = found[0]
    dt.date.fromisoformat(date)
    assert tuple(int(p) for p in version.split(".")) >= (1, 0)


def test_the_eula_marker_parses_and_matches_its_version_line():
    text = _text("EULA.md")
    marker = setup_engine.eula_marker_version(text)
    assert marker and re.fullmatch(r"\d+\.\d+", marker), (
        "docs/legal/EULA.md has lost or garbled its EULA-VERSION marker; "
        "/setup, the companion and the wizard all read it")
    (version, _date), = _VERSION_LINE.findall(text)
    assert version == marker, (
        f"EULA.md says 'Version {version}' but its marker says {marker}: a "
        "wording change must bump both, because the marker is what sends "
        "editors back through acceptance")


def test_the_eng_gap_markers_are_exactly_the_expected_ones():
    found = _markers()
    assert found == EXPECTED_ENG_GAPS, (
        "ENG-GAP markers changed. Added: "
        f"{sorted(found - EXPECTED_ENG_GAPS)}; removed: "
        f"{sorted(EXPECTED_ENG_GAPS - found)}. A marker comes out only with "
        "its paragraph replaced by docs/LEGAL_GAP_FEATURES_PLAN.md §8's "
        "wording, once the feature is in the tree; update EXPECTED_ENG_GAPS "
        "in the same change")


def test_every_marker_is_a_known_id():
    unknown = sorted({i for _n, i in _markers()} - KNOWN_ENG_GAPS)
    assert not unknown, f"unknown ENG-GAP ids (typo?): {unknown}"


def test_a_marker_still_sits_on_a_paragraph_that_says_the_feature_is_missing():
    # A marker kept on a paragraph someone already rewrote would claim a gap
    # the text no longer states (or hide one it does). Every remaining marker
    # must be followed, within its paragraph, by the "does not currently"
    # phrasing the cleared documents use for a missing feature.
    for name in DOCUMENTS:
        text = _text(name).replace("\r\n", "\n")
        for m in _MARKER.finditer(text):
            paragraph = text[m.end():].lstrip().split("\n\n", 1)[0]
            assert "not currently" in paragraph, (
                f"{name}: the ENG-GAP {m.group(1)} marker no longer sits on a "
                "paragraph describing a missing feature")


def test_the_three_eula_copies_are_byte_identical():
    canonical = (LEGAL / "EULA.md").read_bytes()
    copies = (
        REPO_ROOT / "companion" / "src" / "ccsync_companion" / "assets" / "EULA.md",
        REPO_ROOT / "onboarding" / "assets" / "EULA.md",
    )
    for copy in copies:
        assert copy.is_file(), f"{copy.relative_to(REPO_ROOT)} is missing"
        assert copy.read_bytes() == canonical, (
            f"{copy.relative_to(REPO_ROOT)} differs from docs/legal/EULA.md; "
            "the three copies ship as one licence and must be byte-identical")


# ---------------------------------------------------------------------------
# Claims tied to code (G9 review round, 2026-09-25). Each pin reads the code
# that makes a sentence true or false and checks the docs say the matching
# thing, in BOTH directions: a doc that promises what the code does not do
# fails, and so does a caveat left behind once the code lands. The reviewer
# found four such sentences the marker test could not see, because none of
# them sat on a marked paragraph.

DOCS = REPO_ROOT / "docs"


def _doc(rel: str) -> str:
    return (DOCS / rel).read_text(encoding="utf-8").replace("\r\n", "\n")


def _flat(text: str) -> str:
    # Wrapped prose: a phrase may break across lines.
    return re.sub(r"\s+", " ", text)


def _source(module: str, name: str) -> str:
    import importlib
    import inspect
    return inspect.getsource(getattr(importlib.import_module(module), name))


def _lg1_site_half_landed() -> bool:
    # G2b hand-off 1 (api_site publishes `telemetry`) and G1a's review-round
    # FIELDS rows with the `undo_detail` mask. Both, or the LG-1 wording in
    # plan 8.1 is not true of a site switch (G9 ledger).
    fields = (REPO_ROOT / "dashboard" / "src" / "ccsync_dashboard"
              / "telemetry_fields.py").read_text(encoding="utf-8")
    return ('"telemetry"' in _source("ccsync_dashboard.api", "api_site")
            and "undo_detail" in fields and "skipped_exists" in fields)


def test_no_sentence_points_at_the_switches_while_lg1_is_still_marked():
    # Review point 1: PRIVACY 8 said "the switches in section 6 are what stop
    # that" while section 6's marked paragraph says no such setting exists.
    if ("PRIVACY.md", "telemetry-opt-out-switches") not in _markers():
        return
    for rel, phrase in (("legal/PRIVACY.md", "switches in section 6"),
                        ("API.md", "the LG-1 switches are what stop it")):
        assert phrase not in _flat(_doc(rel)), (
            f"docs/{rel} relies on the LG-1 switches ('{phrase}') while "
            "PRIVACY section 6 still says they do not exist")


def test_lg1_markers_go_once_the_site_half_lands():
    # Review point 6: the markers are a release blocker, not a follow-up.
    # When the code lands this fails until plan 8.1 is applied, the markers
    # are removed, EXPECTED_ENG_GAPS is emptied and the two pending notes go.
    if not _lg1_site_half_landed():
        return
    assert not {m for m in _markers() if m[1] == "telemetry-opt-out-switches"}, (
        "api_site publishes `telemetry` and FIELDS carries the undo_detail "
        "rows: apply plan 8.1 (as amended in the G9 ledger) now")
    assert "Pending as of" not in _doc("CONFIG.md")
    assert "pending as of 2026-09-25" not in _doc("API.md")


def test_config_pending_note_names_the_fields_gap_while_it_is_open():
    # Review point 5: the [telemetry] table claims the site strip withholds
    # undo answers' text and lane A's samples; FIELDS cannot yet.
    fields = (REPO_ROOT / "dashboard" / "src" / "ccsync_dashboard"
              / "telemetry_fields.py").read_text(encoding="utf-8")
    if "undo_detail" in fields and "skipped_exists" in fields:
        return
    note = _flat(_doc("CONFIG.md"))
    assert "undo_detail" in note and "skipped_exists.samples" in note, (
        "docs/CONFIG.md [telemetry] claims a site strip FIELDS cannot do yet "
        "and its pending note does not say so")


def _product_calls_validate_for_save() -> bool:
    roots = [REPO_ROOT / "companion" / "src", REPO_ROOT / "onboarding"]
    for root in roots:
        for path in root.rglob("*.py"):
            if "tests" in path.parts:
                continue
            if "for_save=True" in path.read_text(encoding="utf-8", errors="replace"):
                return True
    return False


def test_no_doc_names_validate_config_as_what_refuses_a_save_it_never_sees():
    # Review point 2: only tests pass for_save=True; the wizard refuses the
    # address through steps.dashboard_url_problem.
    if _product_calls_validate_for_save():
        return
    for rel, phrase in (
            ("legal/TELEMETRY.md", "`config.validate_config` rejects it"),
            ("CONFIG.md", "(the wizard's save)"),
            ("GOTCHAS.md", "only a save does")):
        assert phrase not in _flat(_doc(rel)), (
            f"docs/{rel} says validate_config(for_save=True) refuses a save, "
            "but no product code calls it")


def test_the_delete_and_its_youtube_history_are_described_as_the_code_does_it():
    # Review point 3: a delete pseudonymises finished YouTube jobs
    # (forget_requester) and never deletes them (forget_history), so it
    # keeps more than an erase does. Either direction must match the code.
    deletes_them = "forget_history" in _source(
        "ccsync_dashboard.api", "_forget_elsewhere")
    privacy = _flat(_doc("legal/PRIVACY.md"))
    api_md = _flat(_doc("API.md"))
    caveats = ("a delete keeps them" in privacy,
               "except finished YouTube jobs" in api_md)
    if deletes_them:
        assert not any(caveats), (
            "_forget_elsewhere now calls forget_history: drop the delete's "
            "YouTube exception from PRIVACY 8 and the API.md DELETE row")
    else:
        assert all(caveats), (
            "a delete keeps finished YouTube jobs, and PRIVACY 8 / the API.md "
            "DELETE row must say so")


def test_report_via_is_described_with_the_untrusted_proxy_caveat():
    # Review point 4: DASH_TRUSTED_PROXIES defaults to loopback and Tailscale
    # Serve reaches the container from the bridge gateway, so an https report
    # through Serve is recorded as http_local. The caveat may go only when
    # that default stops being loopback-only.
    from ccsync_dashboard import settings as settings_mod
    if settings_mod.Settings.from_env({}).trusted_proxies != "127.0.0.1,::1":
        return
    for rel in ("legal/TELEMETRY.md", "legal/PRIVACY.md"):
        assert "not configured to trust" in _flat(_doc(rel)), (
            f"docs/{rel} states report_via without the untrusted-proxy caveat")
