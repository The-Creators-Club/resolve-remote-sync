"""Regression tests for the 2026-09-11b bug hunt, server-tools territory
(CR-264): the deploy script under server/.

This hunt was OF the 2026-09-11 fix pass, so most of what is pinned here is a
same-day change that landed half of itself: the cards snapshot deploy that
made an uncommitted checkout INVISIBLE instead of merely dangerous
(server-tools-b-1), the escape hatch that leaves the previous deploy's record
standing (server-tools-b-3), the docs staging that can still raise out of a
function documented never to (server-tools-b-5), the prefix fallback that
turns a subtree export into a whole-repo one (server-tools-b-6) and the
propagation flag nothing offline can prove the middleware accepts
(server-tools-b-7).

Everything here runs against throwaway directories and a throwaway git
repository in tmp_path - no NAS, no network, and the real Timeline Cards
checkout is never read.

Run with:
    cd E:\\Projects\\Editing\\ccsync\\server
    ..\\dashboard\\.venv\\Scripts\\python.exe -m pytest tests/test_bug_hunt_2026_09_11b_server_tools.py -q
"""
from __future__ import annotations

import inspect
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import install_dashboard_app as ida  # noqa: E402

GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="git is required")


def git(repo, *args):
    proc = subprocess.run([GIT, *args], cwd=str(repo), capture_output=True, text=True)
    assert proc.returncode == 0, f"git {args} failed: {proc.stderr}"
    return proc.stdout.strip()


def make_repo(tmp_path, dirty=True):
    """A repo shaped like the Timeline Cards one: the package is in a subtree."""
    repo = tmp_path / "Editing"
    src = repo / "Resolve" / "MulticamPipeline"
    (src / "multicam_pipeline" / "cards").mkdir(parents=True)
    git(tmp_path, "init", str(repo))
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    (src / "multicam_pipeline" / "cards" / "handler.py").write_text(
        "COMMITTED\n", encoding="utf-8")
    (src / ".gitignore").write_text("scratch/\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "the cards page")
    head = git(repo, "rev-parse", "HEAD")
    if dirty:
        # The working copy an operator actually has open on the evening of a
        # Cards wave: an edit they have not committed and a file they have not
        # added. Neither is in the snapshot - that is the point of the change -
        # and until this fix nothing said so.
        (src / "multicam_pipeline" / "cards" / "handler.py").write_text(
            "HALF FINISHED\n", encoding="utf-8")
        (src / "multicam_pipeline" / "cards" / "experiment.py").write_text(
            "untracked\n", encoding="utf-8")
    return repo, src, head


# --------------------------------------------------------------------------
# server-tools-b-1: the snapshot ships a commit and used to say nothing at all
# about the edits it left behind
# --------------------------------------------------------------------------

@needs_git
def test_a_dirty_checkout_is_named_loudly_by_the_export(tmp_path, capsys):
    _repo, src, head = make_repo(tmp_path)

    tree, info, err = ida.export_cards_snapshot(src, "main", dest_parent=tmp_path)
    assert err == ""
    assert info["commit"] == head
    # the committed bytes ship, as before
    assert (tree / "multicam_pipeline" / "cards" / "handler.py").read_text(
        encoding="utf-8") == "COMMITTED\n"
    # ...and the two files that did NOT are counted and said out loud
    assert int(info["dirty_at_export"]) == 2
    out = capsys.readouterr()
    said = out.out + out.err
    assert "NOT in this deploy" in said
    assert "experiment.py" in said
    # the marker on the NAS carries the same fact
    marker = ida.read_cards_marker(tree / ida.CARDS_MARKER_NAME)
    assert marker["dirty_at_export"] == "2"


@needs_git
def test_a_clean_checkout_says_nothing(tmp_path, capsys):
    """The control: the note must not cry wolf on the ordinary deploy."""
    _repo, src, _head = make_repo(tmp_path, dirty=False)

    _tree, info, err = ida.export_cards_snapshot(src, "main", dest_parent=tmp_path)
    assert err == ""
    assert info["dirty_at_export"] == "0"
    out = capsys.readouterr()
    assert "NOT in this deploy" not in (out.out + out.err)


# --------------------------------------------------------------------------
# server-tools-b-3 / tests-5: every cards deploy leaves a record, and the
# record is written by the entry point main() actually calls
# --------------------------------------------------------------------------

@needs_git
def test_a_snapshot_deploy_records_the_commit(tmp_path, monkeypatch):
    _repo, src, head = make_repo(tmp_path, dirty=False)
    record = tmp_path / "state" / "cards_deployed.json"
    monkeypatch.setenv("CCSYNC_CARDS_RECORD", str(record))
    _tree, info, err = ida.export_cards_snapshot(src, "main", dest_parent=tmp_path)
    assert err == ""

    ida.record_cards_deploy(src, info, dry_run=False)
    saved = json.loads(record.read_text(encoding="utf-8"))
    assert saved["commit"] == head
    assert not saved.get("override")


def test_an_explicit_directory_deploy_invalidates_the_previous_record(tmp_path,
                                                                     monkeypatch):
    """server-tools-b-3. --cards-src-dir shipped a working directory and left
    the LAST snapshot's record standing, so the doctor answered OK about a
    tree that is nobody's commit."""
    record = tmp_path / "state" / "cards_deployed.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"commit": "a" * 40, "short": "a" * 12,
                                  "ref": "main", "repo": str(tmp_path)}) + "\n",
                      encoding="utf-8")
    monkeypatch.setenv("CCSYNC_CARDS_RECORD", str(record))
    override = tmp_path / "working-copy"
    override.mkdir()

    ida.record_cards_deploy(override, None, dry_run=False)

    saved = json.loads(record.read_text(encoding="utf-8"))
    assert saved.get("commit", "") == ""
    assert Path(saved["override"]) == override
    assert saved.get("exported")


def test_a_dry_run_records_nothing(tmp_path, monkeypatch):
    record = tmp_path / "state" / "cards_deployed.json"
    monkeypatch.setenv("CCSYNC_CARDS_RECORD", str(record))
    ida.record_cards_deploy(tmp_path / "anything", None, dry_run=True)
    assert not record.exists()


def test_the_deploy_writes_the_record_through_that_one_helper():
    """tests-5. A helper that is kept and stops being CALLED is invisible to
    every test that only drives the helper, and the record is the only thing
    the drift doctor can read."""
    body = inspect.getsource(ida.main)
    assert "record_cards_deploy(" in body
    # the old, snapshot-only call must not survive beside it: two writers is
    # how the override path came to have none.
    assert "write_cards_deploy_record(" not in body


# --------------------------------------------------------------------------
# server-tools-b-5: the docs staging is documented never to raise
# --------------------------------------------------------------------------

def test_a_published_docs_module_without_the_constants_is_not_a_traceback(
        tmp_path, monkeypatch):
    class Renamed:
        PUBLISHED_DOCUMENTS = ("HOW_IT_WORKS.md",)

    monkeypatch.setattr(ida, "published_docs_module", lambda: Renamed())
    staging = tmp_path / "staging"
    staging.mkdir()
    ida._stage_docs_tree(staging)  # must not raise AttributeError


def test_a_raising_staging_is_a_note_and_false(tmp_path, monkeypatch, capsys):
    """ship_dashboard_docs: 'every failure is a printed NOTE and False, never
    an exception' - and it runs AFTER the app swap, so an exception there
    skips the restart the swap requires."""
    docs = tmp_path / "docs"
    (docs / "legal").mkdir(parents=True)
    for name in ida.SHIPPED_DOCS:
        (docs / name).write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(ida, "LOCAL_DOCS_DIR", docs)
    monkeypatch.setattr(ida, "_stage_docs_tree",
                        lambda staging: (_ for _ in ()).throw(
                            AttributeError("PUBLISHED_DOCS")))
    monkeypatch.setattr(ida, "install_tree",
                        lambda *a, **k: pytest.fail("must not ship a half staged tree"))

    assert ida.ship_dashboard_docs("/mnt/tank/apps/x", False, "/tmp") is False
    said = capsys.readouterr()
    assert "NOT installed" in (said.out + said.err)


# --------------------------------------------------------------------------
# server-tools-b-6: an unrelatable src is not the repo root
# --------------------------------------------------------------------------

def test_a_src_that_does_not_sit_under_its_repo_root_is_refused(tmp_path,
                                                                monkeypatch):
    src = tmp_path / "cards"
    src.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    def fake_git_out(args, cwd=None):
        if args[:2] == ["rev-parse", "--show-toplevel"]:
            return True, str(elsewhere), ""
        return False, "", "not asked"

    monkeypatch.setattr(ida, "git_out", fake_git_out)
    root, prefix, err = ida.cards_repo_for(src)
    assert err, "a src outside its own repo root must not export the whole repo"
    assert str(src) in err and str(elsewhere) in err
    assert (root, prefix) == (None, "")


def test_a_src_that_is_the_repo_root_still_exports_the_whole_repo(tmp_path,
                                                                 monkeypatch):
    """The control: the one case the empty prefix is there for."""
    src = tmp_path / "cards"
    src.mkdir()
    monkeypatch.setattr(ida, "git_out",
                        lambda args, cwd=None: (True, str(src), "")
                        if args[:2] == ["rev-parse", "--show-toplevel"]
                        else (False, "", ""))
    root, prefix, err = ida.cards_repo_for(src)
    assert err == "" and prefix == "" and Path(root) == src


# --------------------------------------------------------------------------
# server-tools-b-7: rslave reaches TrueNAS's middleware and nothing offline
# can say it is accepted
# --------------------------------------------------------------------------

def test_the_propagation_flag_has_an_off_switch(monkeypatch):
    source = ("/mnt/tank/.zfs/snapshot", "Projects")
    monkeypatch.delenv("CCSYNC_SNAPSHOT_RSLAVE", raising=False)
    assert ida.snapshot_volumes(source) == [
        f"/mnt/tank/.zfs/snapshot:{ida.SNAPSHOT_MOUNT}:ro,rslave"]

    monkeypatch.setenv("CCSYNC_SNAPSHOT_RSLAVE", "0")
    assert ida.snapshot_volumes(source) == [
        f"/mnt/tank/.zfs/snapshot:{ida.SNAPSHOT_MOUNT}:ro"]


def test_a_refused_deploy_names_the_off_switch(monkeypatch):
    lines = ida.snapshot_refusal_hint(("/mnt/tank/.zfs/snapshot", "Projects"))
    assert lines and any("CCSYNC_SNAPSHOT_RSLAVE=0" in line for line in lines)
    assert ida.snapshot_refusal_hint(("", "")) == []
    monkeypatch.setenv("CCSYNC_SNAPSHOT_RSLAVE", "0")
    assert ida.snapshot_refusal_hint(("/mnt/tank/.zfs/snapshot", "Projects")) == []


# --------------------------------------------------------------------------
# Hand-off wave: dash-core-6 - the bind deploy's required docs set
# --------------------------------------------------------------------------

def test_the_required_docs_set_matches_the_dashboard_policy():
    """SHIPPED_DOCS is a hand-written copy of published_docs.REQUIRED_DOCS
    (server/ cannot import the dashboard package), so the two drift silently.
    The image's Dockerfile COPY names EDITOR_SETUP.md and a COPY of an absent
    file fails the build; the bind deploy used to ship a thinner /help without
    saying anything."""
    policy = (Path(__file__).resolve().parents[2] / "dashboard" / "src"
              / "ccsync_dashboard" / "published_docs.py").read_text(encoding="utf-8")
    required = policy.split("REQUIRED_DOCS")[1].split("\n")[0]
    for name in ida.SHIPPED_DOCS:
        assert name in required, f"{name} is shipped as required but is not in REQUIRED_DOCS"
    for name in ("HOW_IT_WORKS.md", "EDITOR_SETUP.md"):
        assert name in required and name in ida.SHIPPED_DOCS


def test_a_missing_editor_setup_refuses_the_docs_ship(tmp_path, monkeypatch, capsys):
    """The half the finding is about: with EDITOR_SETUP.md absent the deploy
    has to say so, not ship the rest and report success."""
    docs = tmp_path / "docs"
    (docs / "legal").mkdir(parents=True)
    (docs / "HOW_IT_WORKS.md").write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(ida, "LOCAL_DOCS_DIR", docs)
    monkeypatch.setattr(ida, "install_tree",
                        lambda *a, **k: pytest.fail("nothing may be shipped"))

    assert ida.ship_dashboard_docs("/mnt/tank/apps/x", False, "/tmp") is False
    said = capsys.readouterr()
    assert "EDITOR_SETUP.md" in (said.out + said.err)
