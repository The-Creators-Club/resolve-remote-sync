"""Moves inside Projects never replace a file that arrives between the exists() check and the rename.

api._rename_noreplace: Windows os.rename (refuses an existing target); Linux renameat2(RENAME_NOREPLACE)
via ctypes; a hard-link fallback for files and an mkdir-claim fallback for folders. The Linux branch is
exercised here by monkeypatching `os.name` and the renameat2 function.
"""
from __future__ import annotations

import errno
import os

import pytest

from ccsync_dashboard import api


def test_existing_target_is_refused_and_nothing_changes(tmp_path):
    src, dst = tmp_path / "a.mp4", tmp_path / "b.mp4"
    src.write_bytes(b"new")
    dst.write_bytes(b"precious")
    with pytest.raises(OSError):
        api._rename_noreplace(src, dst)
    assert src.read_bytes() == b"new" and dst.read_bytes() == b"precious"


def test_a_free_target_is_renamed(tmp_path):
    src, dst = tmp_path / "a.mp4", tmp_path / "b.mp4"
    src.write_bytes(b"x")
    api._rename_noreplace(src, dst)
    assert dst.read_bytes() == b"x" and not src.exists()


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(api.os, "name", "posix")
    monkeypatch.setattr(api, "_renameat2_cache", [])


def test_linux_uses_renameat2_with_the_noreplace_flag(tmp_path, linux, monkeypatch):
    seen = []

    def fake(a, s, b, d, flags):
        seen.append(flags)
        os.rename(s, d)
        return 0
    monkeypatch.setattr(api, "_renameat2_cache", [fake])
    (tmp_path / "a").write_bytes(b"1")
    api._rename_noreplace(tmp_path / "a", tmp_path / "b")
    assert seen == [1] and (tmp_path / "b").exists()


def test_linux_renameat2_eexist_is_raised_not_swallowed(tmp_path, linux, monkeypatch):
    import ctypes

    monkeypatch.setattr(api, "_renameat2_cache", [lambda *a: -1])
    monkeypatch.setattr(ctypes, "get_errno", lambda: errno.EEXIST)
    (tmp_path / "a").write_bytes(b"1")
    (tmp_path / "b").write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        api._rename_noreplace(tmp_path / "a", tmp_path / "b")
    assert (tmp_path / "b").read_bytes() == b"keep" and (tmp_path / "a").exists()


@pytest.mark.parametrize("err", [errno.EINVAL, errno.ENOSYS])
def test_linux_file_falls_back_to_link_then_unlink(tmp_path, linux, monkeypatch, err):
    import ctypes

    monkeypatch.setattr(api, "_renameat2_cache", [lambda *a: -1])
    monkeypatch.setattr(ctypes, "get_errno", lambda: err)
    (tmp_path / "a").write_bytes(b"1")
    api._rename_noreplace(tmp_path / "a", tmp_path / "b")
    assert (tmp_path / "b").read_bytes() == b"1" and not (tmp_path / "a").exists()
    (tmp_path / "c").write_bytes(b"2")
    with pytest.raises(FileExistsError):                       # link() refuses an existing target
        api._rename_noreplace(tmp_path / "c", tmp_path / "b")
    assert (tmp_path / "b").read_bytes() == b"1" and (tmp_path / "c").exists()


def test_linux_without_renameat2_uses_the_fallback(tmp_path, linux, monkeypatch):
    monkeypatch.setattr(api, "_renameat2_cache", [None])
    (tmp_path / "a").write_bytes(b"1")
    api._rename_noreplace(tmp_path / "a", tmp_path / "b")
    assert (tmp_path / "b").exists() and not (tmp_path / "a").exists()


def test_linux_folder_fallback_refuses_an_existing_empty_folder(tmp_path, linux, monkeypatch):
    monkeypatch.setattr(api, "_renameat2_cache", [None])
    src, dst = tmp_path / "s", tmp_path / "d"
    (src / "x").mkdir(parents=True)
    dst.mkdir()
    with pytest.raises(FileExistsError):
        api._rename_noreplace(src, dst)
    assert (src / "x").exists() and dst.is_dir() and not list(dst.iterdir())
    dst.rmdir()
    real = os.rename

    def posix_rename(a, b):                                    # POSIX rename() replaces an EMPTY directory
        if os.path.isdir(b) and not os.listdir(b):
            os.rmdir(b)
        real(a, b)
    monkeypatch.setattr(api.os, "rename", posix_rename)
    api._rename_noreplace(src, dst)
    assert (dst / "x").exists() and not src.exists()


def test_linux_folder_fallback_removes_its_claim_when_the_rename_fails(tmp_path, linux, monkeypatch):
    monkeypatch.setattr(api, "_renameat2_cache", [None])
    src, dst = tmp_path / "s", tmp_path / "d"
    src.mkdir()

    def boom(a, b):
        raise OSError(errno.EXDEV, "cross-device")
    monkeypatch.setattr(api.os, "rename", boom)
    with pytest.raises(OSError):
        api._rename_noreplace(src, dst)
    assert src.is_dir() and not dst.exists()
