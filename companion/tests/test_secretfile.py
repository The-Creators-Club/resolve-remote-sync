"""Owner-only permissions on the files under ~/.ccsync that hold credentials.

COMMERCIAL_READINESS.md item 15 (2026-08-17): identity.json and config.toml
were written at the process default umask -- 0644 on POSIX, and on Windows
whatever the profile directory's ACL happened to be inherited from, which on a
shared or domain-joined machine is routinely readable by other local accounts.

The Windows half cannot be asserted by reading a mode bit (there is none), so
these drive the icacls invocation through a fake subprocess and pin the
arguments -- in particular that inheritance is stripped and the owner granted
in ONE call, because two calls leave a window in which the file has no ACEs at
all and a crash in between leaves identity.json unreadable by its own owner.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys

import pytest

from ccsync_companion import secretfile


class FakeRun:
    """Records subprocess.run calls; answers with a chosen returncode."""

    def __init__(self, returncode=0, output=b""):
        self.returncode = returncode
        self.output = output
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, self.returncode, stdout=self.output)


@pytest.fixture
def secret(tmp_path):
    path = tmp_path / "identity.json"
    path.write_text('{"token": "sekrit"}', encoding="utf-8")
    return path


# ------------------------------------------------------------------- windows

def test_windows_strips_inheritance_and_grants_the_owner_in_one_call(
        secret, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(secretfile.sys, "platform", "win32")
    monkeypatch.setattr(secretfile.subprocess, "run", fake)
    monkeypatch.setenv("USERDOMAIN", "EDITPC")
    monkeypatch.setenv("USERNAME", "owen")

    assert secretfile.harden(secret) is True
    assert len(fake.calls) == 1                      # ONE call: see the docstring
    cmd, kwargs = fake.calls[0]
    assert cmd[0] == "icacls"
    assert cmd[1] == str(secret)
    assert "/inheritance:r" in cmd
    assert "/grant:r" in cmd
    assert "EDITPC\\owen:(R,W)" in cmd
    # list-argv, never a shell -- the path is attacker-influenced only in the
    # sense that a username is in it, but this package never builds command
    # lines as strings.
    assert "shell" not in kwargs


def test_windows_without_a_domain_grants_the_bare_username(secret, monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(secretfile.sys, "platform", "win32")
    monkeypatch.setattr(secretfile.subprocess, "run", fake)
    monkeypatch.delenv("USERDOMAIN", raising=False)
    monkeypatch.setenv("USERNAME", "owen")

    assert secretfile.harden(secret) is True
    assert "owen:(R,W)" in fake.calls[0][0]


def test_a_failing_icacls_is_a_warning_not_a_crash(secret, monkeypatch, caplog):
    monkeypatch.setattr(secretfile.sys, "platform", "win32")
    monkeypatch.setattr(secretfile.subprocess, "run",
                        FakeRun(returncode=5, output=b"Access is denied."))
    monkeypatch.setenv("USERNAME", "owen")

    assert secretfile.harden(secret) is False
    assert "icacls refused" in caplog.text


def test_an_exploding_subprocess_is_a_warning_not_a_crash(secret, monkeypatch):
    def boom(cmd, **kwargs):
        raise OSError("no icacls on this box")

    monkeypatch.setattr(secretfile.sys, "platform", "win32")
    monkeypatch.setattr(secretfile.subprocess, "run", boom)
    monkeypatch.setenv("USERNAME", "owen")

    assert secretfile.harden(secret) is False        # never raises: see module


def test_no_username_in_the_environment_is_refused_not_guessed(secret, monkeypatch):
    monkeypatch.setattr(secretfile.sys, "platform", "win32")
    monkeypatch.setattr(secretfile.subprocess, "run", FakeRun())
    monkeypatch.delenv("USERNAME", raising=False)
    monkeypatch.delenv("USERDOMAIN", raising=False)

    assert secretfile.harden(secret) is False


# --------------------------------------------------------------------- posix

def test_posix_chmods_to_0600(secret, monkeypatch):
    calls = []
    monkeypatch.setattr(secretfile.sys, "platform", "linux")
    monkeypatch.setattr(secretfile.os, "chmod", lambda p, m: calls.append((p, m)))

    assert secretfile.harden(secret) is True
    assert calls == [(secret, 0o600)]


@pytest.mark.skipif(sys.platform == "win32",
                    reason="mode bits are meaningless on Windows -- see the module")
def test_posix_really_removes_group_and_other(secret):
    os.chmod(secret, 0o644)
    assert secretfile.harden(secret) is True
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600


def test_a_missing_file_is_a_warning_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(secretfile.sys, "platform", "linux")
    assert secretfile.harden(tmp_path / "gone.json") is False
