"""The scratch-path guard: nothing in this harness deletes a path that isn't
demonstrably a `_bench` scratch subtree."""

from __future__ import annotations

from pathlib import Path

import pytest

from ccbench import guard


@pytest.fixture(autouse=True)
def _reset_override():
    guard.set_allow_destructive(False)
    yield
    guard.set_allow_destructive(False)


def test_remote_path_part_understands_rclone_specs():
    assert guard.remote_path_part(":sftp,host=h,user=u:Creators_Club/_bench/large/up") == (
        "Creators_Club/_bench/large/up"
    )
    # a parameter value may itself contain a colon (key_file=C:\...)
    assert guard.remote_path_part(":sftp,host=h,key_file=C:\\keys\\id:CC/_bench/x") == "CC/_bench/x"
    assert guard.remote_path_part("nas:Creators_Club/_bench/large") == "Creators_Club/_bench/large"
    assert guard.remote_path_part("E:\\scratch\\_bench\\large") == "E:\\scratch\\_bench\\large"


def test_is_scratch_path_accepts_bench_components():
    assert guard.is_scratch_path("Creators_Club/_bench/large/up")
    assert guard.is_scratch_path("\\\\nas\\pool\\Creators_Club\\_bench\\large\\up")
    assert guard.is_scratch_path(":smb,host=h:TheCreatorsPool/Creators_Club/_bench/small/down")
    assert guard.is_scratch_path("/tmp/ccbench-_bench-syncthing-xyz")


def test_is_scratch_path_rejects_live_tree_paths():
    assert not guard.is_scratch_path("Creators_Club")
    assert not guard.is_scratch_path("Creators_Club/Projects/2026/CCT/Season 1")
    assert not guard.is_scratch_path(":sftp,host=h,user=u:Creators_Club/Projects/2026")
    assert not guard.is_scratch_path("\\\\nas\\TheCreatorsPool\\Creators_Club")


def test_assert_scratch_path_refuses_non_bench_path():
    with pytest.raises(guard.DestructiveEndpointRefused) as exc:
        guard.assert_scratch_path("Creators_Club/Projects/2026/CCT", action="rclone purge")
    assert "_bench" in str(exc.value)
    assert "--allow-destructive-endpoint" in str(exc.value)


def test_allow_destructive_override_permits_any_path():
    guard.set_allow_destructive(True)
    guard.assert_scratch_path("Creators_Club/Projects/2026/CCT", action="rclone purge")


def test_safe_rmtree_refuses_and_leaves_files_intact(tmp_path: Path):
    live = tmp_path / "Creators_Club" / "Projects" / "2026"
    live.mkdir(parents=True)
    (live / "original.braw").write_bytes(b"irreplaceable")

    with pytest.raises(guard.DestructiveEndpointRefused):
        guard.safe_rmtree(live)

    assert (live / "original.braw").read_bytes() == b"irreplaceable"


def test_safe_rmtree_removes_a_bench_path(tmp_path: Path):
    scratch = tmp_path / "_bench" / "large"
    scratch.mkdir(parents=True)
    (scratch / "f.bin").write_bytes(b"scratch")

    guard.safe_rmtree(scratch)
    assert not scratch.exists()


def test_empty_dir_refuses_non_bench_destination(tmp_path: Path):
    dest = tmp_path / "Creators_Club" / "download"
    dest.mkdir(parents=True)
    (dest / "keep.mov").write_bytes(b"x")

    with pytest.raises(guard.DestructiveEndpointRefused):
        guard.empty_dir(dest)
    assert (dest / "keep.mov").exists()


def test_empty_dir_clears_a_bench_destination(tmp_path: Path):
    dest = tmp_path / "_bench_down" / "rclone_sftp" / "large" / "0"
    dest.mkdir(parents=True)
    (dest / "warm.bin").write_bytes(b"already here")

    guard.empty_dir(dest)
    assert dest.is_dir()
    assert list(dest.iterdir()) == []


def test_empty_dir_raises_when_the_destination_could_not_be_emptied(tmp_path: Path, monkeypatch):
    """`rmtree(ignore_errors=True)` can leave files behind without saying so --
    which is exactly how a warm destination survives into a timed download."""
    dest = tmp_path / "_bench_down" / "0"
    dest.mkdir(parents=True)
    (dest / "warm.bin").write_bytes(b"locked by another process")

    monkeypatch.setattr(guard.shutil, "rmtree", lambda *a, **k: None)  # the silent-failure case

    with pytest.raises(guard.CleanupFailed) as exc:
        guard.empty_dir(dest)
    assert "warm.bin" in str(exc.value)


def test_redact_hides_an_obscured_password_in_an_rclone_spec():
    """`rclone reveal` is the exact inverse of `rclone obscure`, so an obscured
    password is a live credential, not a hash."""
    spec = ":smb,host=nas,user=editor1,pass=Xy9_secretObscured:pool/Creators_Club/_bench/large/up"
    redacted = guard.redact(spec)
    assert "Xy9_secretObscured" not in redacted
    assert "pass=***" in redacted
    # everything else survives, so the message is still diagnosable
    assert "host=nas" in redacted
    assert "pool/Creators_Club/_bench/large/up" in redacted


def test_redact_leaves_credential_free_paths_alone():
    assert guard.redact("E:\\scratch\\_bench\\large") == "E:\\scratch\\_bench\\large"
    assert guard.redact(":sftp,host=h,user=u:CC/_bench") == ":sftp,host=h,user=u:CC/_bench"


def test_a_refusal_message_never_quotes_the_password():
    spec = ":smb,host=nas,user=editor1,pass=Xy9_secretObscured:pool/Creators_Club/Projects"
    with pytest.raises(guard.DestructiveEndpointRefused) as exc:
        guard.assert_scratch_path(spec, action="rclone purge")
    assert "Xy9_secretObscured" not in str(exc.value)


def test_rclone_cleanup_remote_refuses_config_derived_live_path(monkeypatch):
    """The audit's concrete scenario: bench.toml's remote_path edited from
    'Creators_Club/_bench' to 'Creators_Club' -> `rclone purge` must not run."""
    from ccbench.runners import _rclone_common

    calls = []
    monkeypatch.setattr(_rclone_common.subprocess, "run", lambda *a, **k: calls.append(a))

    with pytest.raises(guard.DestructiveEndpointRefused):
        _rclone_common.cleanup_remote(":sftp,host=nas,user=editor1:Creators_Club")
    assert calls == []

    _rclone_common.cleanup_remote(":sftp,host=nas,user=editor1:Creators_Club/_bench/large/up")
    assert len(calls) == 1


def test_robocopy_cleanup_endpoint_refuses_live_unc_path():
    from ccbench.runners import robocopy_smb

    endpoint = {"unc_path": "\\\\nas\\TheCreatorsPool\\Creators_Club"}
    with pytest.raises(guard.DestructiveEndpointRefused):
        robocopy_smb.cleanup_endpoint(endpoint, "large", "up")
