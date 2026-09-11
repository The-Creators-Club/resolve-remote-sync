"""What ships to /cards is a COMMIT, not somebody's working copy.

cards snapshot deploy, 2026-09-11. Until today the Timeline Cards tree reached
the NAS as a copy of a directory on the base rig, and the only thing keeping
half-finished edits out of it was a second checkout the operator moved and
`git clean`ed by hand. These tests are about the property that replaced that
discipline: `git archive <commit>:<subtree>` contains the TRACKED files of one
commit and nothing else.

Everything here runs against a throwaway git repository in tmp_path -- no NAS,
no network, and the real Timeline Cards checkout is never read.

Run with:
    cd E:\\Projects\\ccsync\\server
    ..\\dashboard\\.venv\\Scripts\\python.exe -m pytest tests/test_cards_snapshot.py -q
"""
import argparse
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import install_dashboard_app as ida  # noqa: E402

GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="git is required")

SUBTREE = "Resolve/MulticamPipeline"


def git(repo, *args):
    proc = subprocess.run([GIT, *args], cwd=str(repo), capture_output=True, text=True)
    assert proc.returncode == 0, f"git {args} failed: {proc.stderr}"
    return proc.stdout.strip()


def make_repo(tmp_path):
    """A repo shaped like the Timeline Cards one: the package is in a subtree.

    Two commits, so there is a commit that PREDATES the subtree -- the
    "Resolve/MulticamPipeline is absent at that commit" refusal needs one.
    """
    repo = tmp_path / "Editing"
    (repo / "Rendering").mkdir(parents=True)
    git(tmp_path, "init", str(repo))
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    (repo / "Rendering" / "notes.txt").write_text("older than cards\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "before Timeline Cards existed")
    before = git(repo, "rev-parse", "HEAD")

    src = repo / "Resolve" / "MulticamPipeline"
    (src / "multicam_pipeline" / "cards").mkdir(parents=True)
    (src / "multicam_pipeline" / "cards" / "handler.py").write_text(
        "COMMITTED\n", encoding="utf-8")
    (src / "multicam_pipeline" / "__init__.py").write_text("", encoding="utf-8")
    (src / ".gitignore").write_text("scratch/\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "the cards page")
    head = git(repo, "rev-parse", "HEAD")

    # The working copy an operator actually has open: an edit they have not
    # committed, a file they have not added, and something git is ignoring.
    (src / "multicam_pipeline" / "cards" / "handler.py").write_text(
        "HALF FINISHED\n", encoding="utf-8")
    (src / "multicam_pipeline" / "cards" / "experiment.py").write_text(
        "untracked\n", encoding="utf-8")
    (src / "scratch").mkdir()
    (src / "scratch" / "junk.bin").write_text("ignored\n", encoding="utf-8")
    return repo, src, before, head


@needs_git
def test_snapshot_is_the_commit_not_the_working_copy(tmp_path):
    repo, src, _before, head = make_repo(tmp_path)

    tree, info, err = ida.export_cards_snapshot(src, "main", dest_parent=tmp_path)
    assert err == ""
    handler = tree / "multicam_pipeline" / "cards" / "handler.py"
    # tracked, at the committed content -- not the edit sitting in the checkout
    assert handler.read_text(encoding="utf-8") == "COMMITTED\n"
    assert not (tree / "multicam_pipeline" / "cards" / "experiment.py").exists()
    assert not (tree / "scratch").exists()
    assert not (tree / ".git").exists()
    assert info["commit"] == head
    assert info["subtree"] == SUBTREE


@needs_git
def test_snapshot_carries_the_marker(tmp_path):
    repo, src, _before, head = make_repo(tmp_path)

    tree, info, err = ida.export_cards_snapshot(src, "main", dest_parent=tmp_path)
    assert err == ""
    marker = tree / ida.CARDS_MARKER_NAME
    assert marker.is_file()
    parsed = ida.read_cards_marker(marker)
    assert parsed["commit"] == head
    assert parsed["short"] == head[:12]
    assert parsed["ref"] == "main"
    assert Path(parsed["repo"]).resolve() == repo.resolve()
    assert parsed["subtree"] == SUBTREE
    assert parsed["subject"] == "the cards page"
    assert parsed["exported"]


@needs_git
def test_a_ref_that_does_not_exist_is_refused(tmp_path):
    _repo, src, _before, _head = make_repo(tmp_path)

    tree, info, err = ida.export_cards_snapshot(src, "no-such-branch",
                                                dest_parent=tmp_path)
    assert tree is None and info is None
    # the sentence has to name the ref: the next thing the operator does is
    # retype it
    assert "no-such-branch" in err
    assert "--cards-commit" in err


@needs_git
def test_a_commit_without_the_subtree_is_refused(tmp_path):
    _repo, src, before, _head = make_repo(tmp_path)

    tree, info, err = ida.export_cards_snapshot(src, before, dest_parent=tmp_path)
    assert tree is None and info is None
    assert SUBTREE in err
    assert before[:12] in err


@needs_git
def test_an_empty_archive_is_refused(tmp_path, monkeypatch):
    """An empty tree ships as a green healthcheck with no /cards behind it.

    git will not normally produce one (it tracks no empty directories), so the
    archive step is the thing stubbed here and nothing else is.
    """
    _repo, src, _before, _head = make_repo(tmp_path)
    real = ida.git_out

    def fake(args, cwd=None):
        if args and args[0] == "archive":
            out = Path(args[args.index("-o") + 1])
            with tarfile.open(out, "w"):
                pass
            return True, "", ""
        return real(args, cwd=cwd)

    monkeypatch.setattr(ida, "git_out", fake)
    tree, info, err = ida.export_cards_snapshot(src, "main", dest_parent=tmp_path)
    assert tree is None and info is None
    assert "EMPTY" in err


@needs_git
def test_resolve_prefers_the_snapshot_and_the_flag_pins_a_commit(tmp_path, monkeypatch):
    _repo, src, _before, head = make_repo(tmp_path)
    monkeypatch.setattr(ida, "SITE_CARDS_SRC", str(src))
    monkeypatch.delenv("CARDS_SRC", raising=False)
    args = argparse.Namespace(cards_commit="", cards_src_dir="")

    tree, info, err = ida.resolve_cards_tree(args)
    assert err == ""
    assert info["commit"] == head
    assert (tree / "multicam_pipeline" / "cards" / "handler.py").read_text(
        encoding="utf-8") == "COMMITTED\n"

    args.cards_commit = "no-such-branch"
    tree, info, err = ida.resolve_cards_tree(args)
    assert tree is None and info is None and "no-such-branch" in err


@needs_git
def test_an_explicit_directory_still_ships_as_it_stands(tmp_path, monkeypatch):
    """CARDS_SRC / --cards-src-dir keep the pre-2026-09-11 meaning."""
    _repo, src, _before, _head = make_repo(tmp_path)
    monkeypatch.setattr(ida, "SITE_CARDS_SRC", str(src))

    monkeypatch.setenv("CARDS_SRC", str(src))
    tree, info, err = ida.resolve_cards_tree(argparse.Namespace(cards_commit="",
                                                                cards_src_dir=""))
    assert err == "" and info is None and tree == src
    assert (tree / "multicam_pipeline" / "cards" / "experiment.py").exists()

    monkeypatch.delenv("CARDS_SRC", raising=False)
    tree, info, err = ida.resolve_cards_tree(
        argparse.Namespace(cards_commit="", cards_src_dir=str(src)))
    assert err == "" and info is None and tree == src


def test_a_src_that_is_not_a_checkout_ships_as_a_directory(tmp_path, monkeypatch):
    """A site whose Timeline Cards tree is a plain copy still gets a /cards."""
    plain = tmp_path / "cards-copy"
    (plain / "multicam_pipeline" / "cards").mkdir(parents=True)
    (plain / "multicam_pipeline" / "cards" / "handler.py").write_text("x\n",
                                                                     encoding="utf-8")
    monkeypatch.setattr(ida, "SITE_CARDS_SRC", str(plain))
    monkeypatch.delenv("CARDS_SRC", raising=False)
    monkeypatch.setattr(ida, "cards_repo_for",
                        lambda src: (None, "", f"{src} is not inside a git repository."))

    tree, info, err = ida.resolve_cards_tree(argparse.Namespace(cards_commit="",
                                                               cards_src_dir=""))
    assert err == "" and info is None and tree == plain


def test_no_named_src_is_no_cards_and_no_complaint(tmp_path, monkeypatch):
    monkeypatch.setattr(ida, "SITE_CARDS_SRC", "")
    monkeypatch.delenv("CARDS_SRC", raising=False)
    tree, info, err = ida.resolve_cards_tree(argparse.Namespace(cards_commit="",
                                                               cards_src_dir=""))
    assert (tree, info, err) == (None, None, "")


@needs_git
def test_the_deploy_record_is_what_the_drift_doctor_reads(tmp_path, monkeypatch):
    """The record is local, best effort, and holds the repo path.

    The drift doctor runs on the base rig with no NAS shell, so it reads this
    rather than the marker it shipped -- and it needs the repo path to answer
    "has main moved past it".
    """
    repo, src, _before, head = make_repo(tmp_path)
    record = tmp_path / "state" / "cards_deployed.json"
    monkeypatch.setenv("CCSYNC_CARDS_RECORD", str(record))
    _tree, info, err = ida.export_cards_snapshot(src, "main", dest_parent=tmp_path)
    assert err == ""

    ida.write_cards_deploy_record(info)
    saved = json.loads(record.read_text(encoding="utf-8"))
    assert saved["commit"] == head
    assert Path(saved["repo"]).resolve() == repo.resolve()

    # nothing has moved yet
    assert ida.cards_head_moved_on(info) == ""

    (src / "multicam_pipeline" / "cards" / "handler.py").write_text("NEXT\n",
                                                                   encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "later work")
    moved = ida.cards_head_moved_on(info)
    assert git(repo, "rev-parse", "HEAD")[:12] in moved
    assert head[:12] in moved


@needs_git
def test_an_unwritable_record_is_not_a_failed_deploy(tmp_path, monkeypatch):
    monkeypatch.setenv("CCSYNC_CARDS_RECORD", str(tmp_path / "nope" / "x" / "r.json"))
    monkeypatch.setattr(Path, "write_text",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("full")))
    ida.write_cards_deploy_record({"commit": "abc"})  # must not raise
