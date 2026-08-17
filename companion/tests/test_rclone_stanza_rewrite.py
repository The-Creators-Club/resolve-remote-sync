"""macos_bootstrap.sh's rclone.conf stanza rewrite must never lose a remote.

MAC-9, live on the first real Mac: the rewrite passed a seven-line stanza
through `awk -v stanza=...`. macOS ships BWK awk, which rejects a -v value
containing a newline, exits 2 and writes nothing -- and the script mv'd that
empty output over rclone.conf. An editor re-running the installer lost every
remote in the file. GNU awk accepts multi-line -v values, so no Linux or CI
run ever saw it.

These tests run the real function out of the real script, under the real
`awk` of whatever machine they run on -- which is the only way this class of
bug is visible. Extracted between sentinels like
tests/test_resolve_mapping_helper.py does with the Resolve mapping helper, so
the code under test is the code the installer runs.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

BOOTSTRAP = Path(__file__).resolve().parent.parent.parent / "installer" / "macos_bootstrap.sh"
SENTINEL_BEGIN = "# ---CCSYNC-RCLONE-STANZA-BEGIN---"
SENTINEL_END = "# ---CCSYNC-RCLONE-STANZA-END---"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("awk") is None,
    reason="needs bash and awk (the point of the test is the local awk)",
)

STANZA = """[creators_club_sftp]
type = sftp
host = truenas.example.ts.net
user = editor1
port = 22
key_file = /Users/editor1/.ssh/ccsync_ed25519
shell_type = unix
"""

ORIGINAL = """[creators_club_sftp]
type = sftp
host = old.example.net
user = olduser

[someone_elses_backup]
type = s3
access_key_id = AKIAEXAMPLE
secret_access_key = shhh
"""


def _extract_function() -> str:
    lines = BOOTSTRAP.read_text(encoding="utf-8").splitlines()
    begins = [i for i, line in enumerate(lines) if line.strip() == SENTINEL_BEGIN]
    ends = [i for i, line in enumerate(lines) if line.strip() == SENTINEL_END]
    assert len(begins) == 1 and len(ends) == 1, (
        f"{BOOTSTRAP} must contain exactly one {SENTINEL_BEGIN}/{SENTINEL_END} pair"
    )
    assert begins[0] < ends[0]
    return "\n".join(lines[begins[0]:ends[0] + 1]) + "\n"


def _run(tmp_path: Path, conf: Path, stanza: str = STANZA, name: str = "creators_club_sftp"):
    script = tmp_path / "harness.sh"
    script.write_text(
        _extract_function()
        + '\nrewrite_rclone_stanza "$1" "$2" "$3"\necho "rc=$?"\n',
        encoding="utf-8",
    )
    return subprocess.run(
        ["bash", str(script), str(conf), name, stanza],
        capture_output=True, encoding="utf-8", errors="replace", timeout=30,
    )


def test_the_target_stanza_is_replaced(tmp_path):
    conf = tmp_path / "rclone.conf"
    conf.write_text(ORIGINAL, encoding="utf-8")

    result = _run(tmp_path, conf)

    assert "rc=0" in result.stdout, result.stderr
    text = conf.read_text(encoding="utf-8")
    assert "host = truenas.example.ts.net" in text
    assert "user = editor1" in text
    assert "old.example.net" not in text
    assert "olduser" not in text


def test_every_other_remote_survives(tmp_path):
    """The whole point of rewriting rather than overwriting -- and exactly
    what MAC-9 destroyed."""
    conf = tmp_path / "rclone.conf"
    conf.write_text(ORIGINAL, encoding="utf-8")

    _run(tmp_path, conf)

    text = conf.read_text(encoding="utf-8")
    assert "[someone_elses_backup]" in text
    assert "AKIAEXAMPLE" in text
    assert "secret_access_key = shhh" in text


def test_the_file_is_never_left_empty(tmp_path):
    """The MAC-9 signature: 0 bytes where a config used to be."""
    conf = tmp_path / "rclone.conf"
    conf.write_text(ORIGINAL, encoding="utf-8")

    _run(tmp_path, conf)

    assert conf.stat().st_size > 0
    assert conf.read_text(encoding="utf-8").count("[") >= 2


def test_a_multiline_stanza_does_not_reach_awk_dash_v(tmp_path):
    """The regression proper. On BWK awk (macOS) a newline in a -v value is a
    hard error; if the stanza ever goes back through -v, this fails on a Mac
    and passes on GNU awk -- so assert on the FILE, which is platform-neutral,
    and on awk staying quiet."""
    conf = tmp_path / "rclone.conf"
    conf.write_text(ORIGINAL, encoding="utf-8")

    result = _run(tmp_path, conf)

    assert "newline in string" not in (result.stderr or "")
    assert "rc=0" in result.stdout
    assert conf.read_text(encoding="utf-8").startswith("[")


def test_a_backup_is_kept(tmp_path):
    conf = tmp_path / "rclone.conf"
    conf.write_text(ORIGINAL, encoding="utf-8")

    _run(tmp_path, conf)

    backups = list(tmp_path.glob("rclone.conf.ccsync-backup-*"))
    assert len(backups) == 1
    assert "old.example.net" in backups[0].read_text(encoding="utf-8")


def test_a_missing_config_fails_without_creating_one(tmp_path):
    conf = tmp_path / "rclone.conf"

    result = _run(tmp_path, conf)

    assert "rc=0" not in result.stdout
    assert not conf.exists()


def test_no_temp_files_are_left_behind(tmp_path):
    conf = tmp_path / "rclone.conf"
    conf.write_text(ORIGINAL, encoding="utf-8")

    _run(tmp_path, conf)

    assert list(tmp_path.glob("rclone.conf.ccsync.*")) == []
