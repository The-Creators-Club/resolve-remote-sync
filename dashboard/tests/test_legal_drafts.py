"""CR-377 / L1 (2026-10-07): pins for the legal DRAFTS written for the free
open beta (docs/legal/BETA_AGREEMENT.md, DPA.md, SUPPORT_DATA_PROCEDURE.md,
docs/SUPPORTED_PLATFORMS.md) and the PRIVACY.md corrections.

What matters: the drafts exist and say they are drafts, the EULA's version
marker did not move (a bump re-parks every editor), PRIVACY points at the DPA
instead of "on request" and names the one sub-processor, and the README
indexes everything.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs"
LEGAL = DOCS / "legal"
DRAFTS = ("BETA_AGREEMENT.md", "DPA.md", "SUPPORT_DATA_PROCEDURE.md")


def _flat(p: Path) -> str:
    return re.sub(r"\s+", " ", p.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", DRAFTS)
def test_each_draft_is_marked_for_counsel(name):
    assert "DRAFT FOR COUNSEL" in (LEGAL / name).read_text(encoding="utf-8")[:400]


def test_eula_version_marker_is_unmoved():
    # The beta terms are a supplement; touching the EULA re-parks the fleet.
    assert "<!-- EULA-VERSION: 1.1 -->" in (LEGAL / "EULA.md").read_text(encoding="utf-8")


def test_beta_terms_cover_the_decided_points():
    t = _flat(LEGAL / "BETA_AGREEMENT.md").lower()
    for phrase in ("as is", "uptime", "set up again", "on notice",
                   "best effort", "unmanaged", "not code-signed"):
        assert phrase in t, phrase


def test_dpa_has_annexes_scc_and_subprocessors():
    t = _flat(LEGAL / "DPA.md")
    for phrase in ("Annex I", "Annex II", "Annex III", "Module Two",
                   "UK International Data Transfer Addendum", "Taiwan",
                   "Google Workspace", "GitHub", "only** when", "Art. 28"):
        assert phrase in t, phrase


def test_support_procedure_answers_the_questions_and_defaults_ai_to_no():
    t = _flat(LEGAL / "SUPPORT_DATA_PROCEDURE.md")
    for phrase in ("What may support ask for", "How it is sent",
                   "Where it is kept", "Deletion period", "Who may access",
                   "Remote sessions", "Decided by the owner, 2026-10-07: no"):
        assert phrase in t, phrase


def test_privacy_corrected():
    t = _flat(LEGAL / "PRIVACY.md")
    assert "no Customer data leaves the Customer's network for the Licensor" in t
    assert "Google Workspace" in t
    assert "docs/legal/DPA.md" in t
    assert "### Transfers" in t
    assert "can request one at contact@" not in t
    assert "we engage no sub-processor for it" not in t


def test_supported_platforms_states_the_matrix():
    t = _flat(DOCS / "SUPPORTED_PLATFORMS.md")
    for phrase in ("Windows 10 22H2", "Windows 11", "Apple silicon",
                   "Resolve Studio", "TrueNAS SCALE", "26", "DSM 7.2.1",
                   "paid Tailscale plan", "Unmanaged machines only"):
        assert phrase in t, phrase


def test_readme_indexes_the_new_documents():
    t = (DOCS / "README.md").read_text(encoding="utf-8")
    for link in ("legal/BETA_AGREEMENT.md", "legal/DPA.md",
                 "legal/SUPPORT_DATA_PROCEDURE.md", "SUPPORTED_PLATFORMS.md"):
        assert f"]({link})" in t, link


def test_overseer_round2_consistency_cr377():
    """CR-377 / GL-51, 2026-10-07: PRIVACY, DPA and beta terms must agree."""
    priv = _flat(DOCS / "legal" / "PRIVACY.md")
    assert "empty by default" not in priv
    assert "no phone-home" not in priv.lower()
    assert "DASH_RELEASE_FEED_URL" in priv
    assert "we delete it when the request is closed" not in priv
    assert "do not yet all carry" not in priv
    beta = _flat(DOCS / "legal" / "BETA_AGREEMENT.md")
    assert "docs/SUPPORTED_PLATFORMS.md" not in beta  # not a published page
    assert "Apple silicon" in beta
    for n in ("PRIVACY.md", "SUPPORT_DATA_PROCEDURE.md", "DPA.md"):
        t = _flat(DOCS / "legal" / n)
        assert "support mailbox contact@" not in t
    assert "SmartScreen and System Settings click-through guide is **owed**" in _flat(
        DOCS / "SUPPORTED_PLATFORMS.md")


def test_round2_drafts_unpublished_and_aligned_cr377():
    """CR-377 round 2, 2026-10-07: drafts stay out of /help; text matches code."""
    from ccsync_dashboard import published_docs as pd
    for n in DRAFTS:
        assert not pd.is_published("legal/" + n), n
    assert pd.is_published("legal/PRIVACY.md")
    priv = _flat(LEGAL / "PRIVACY.md")
    assert "optional release-feed" not in priv
    assert "at most daily" not in priv
    assert "support@thecreatorsclub.co" in priv
    sp = _flat(LEGAL / "SUPPORT_DATA_PROCEDURE.md")
    assert "sends nothing to the Licensor" not in sp
    assert "30 days after the request (ticket) is closed" in sp
    assert "[support address" not in sp
    assert "offline release key" not in _flat(LEGAL / "DPA.md")
    assert "when it installs the Software" not in _flat(LEGAL / "BETA_AGREEMENT.md")


def test_round2b_dpa_no_ai_and_drafts_refused_to_admins_cr377(tmp_path, monkeypatch):
    """CR-377 r2b: DPA states the AI no as a commitment; admins and case
    variants cannot read the drafts through /help either."""
    dpa = _flat(LEGAL / "DPA.md")
    assert "by default" not in dpa.split("Annex III")[-1]
    assert "open owner decision" not in dpa
    assert "acceptance of these terms by the administrator" not in _flat(
        LEGAL / "BETA_AGREEMENT.md")
    from ccsync_dashboard import help as h, published_docs as pd
    for rel in ("legal/dpa.md", "legal/DPA.MD", "legal/DPA.md"):
        assert not pd.is_published(rel), rel
    root = tmp_path / "docs"
    (root / "legal").mkdir(parents=True)
    for n in DRAFTS + ("PRIVACY.md",):
        (root / "legal" / n).write_text("# t\n", encoding="utf-8")
    monkeypatch.setenv("DASH_HELP_DOC", str(root / "legal" / "PRIVACY.md"))
    monkeypatch.setattr(h, "document_root", lambda: root)
    h.invalidate_index()
    for admin in (True, False):
        assert h.resolve_document("legal/DPA.md", admin) is None
        assert h.resolve_document("legal/dpa.md", admin) is None
        assert h.resolve_document("legal/PRIVACY.md", True) is not None
        rels = {e["rel"] for g in h.document_groups(admin) for e in g["entries"]}
        assert not any(r.split("/")[-1] in DRAFTS for r in rels)
    h.invalidate_index()
