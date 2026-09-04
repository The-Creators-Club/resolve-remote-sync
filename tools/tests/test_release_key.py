"""tools/release_key.py -- the offline signing key, and the copy of it.

REL-14 (usability + resilience sweep, 2026-09-04): `~/.ccsync-release/release.key`
is 32 bytes on one profile on one workstation, deliberately never on GitHub,
and its loss is unrecoverable for every fleet that exists -- every companion
trusts only the keys baked into the binary it is already running. The strongest
statement of that fact lived on line 668 of a 1200-line runbook, `new` said
nothing about backing anything up, and there was no `backup` command at all.

There is deliberately NO passphrase wrap: the in-tree crypto
(`ccsync_companion.ed25519`) signs and verifies and does not encrypt, and a
homemade construction protecting the one secret in this product that must never
be guessable is worse than the problem. What these tests pin instead is that
the copy IS the key, that the tool says so, and that the fact is recorded.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(REPO / "companion" / "src"))

import release_key as rk  # noqa: E402


@pytest.fixture
def key(tmp_path):
    path = tmp_path / "release.key"
    rk.main(["--path", str(path), "new"])
    return path


def test_new_ends_with_the_backup_warning(tmp_path, capsys):
    rc = rk.main(["--path", str(tmp_path / "release.key"), "new"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "BACK IT UP NOW" in out
    # The cost, in the terms the owner meets it in -- the same voice `bake`
    # uses for a replaced key.
    assert "no fleet anywhere can ever be offered another build" in out
    assert "release_key.py backup --to" in out


def test_backup_writes_a_usable_copy_of_the_key(key, tmp_path, capsys):
    dest = tmp_path / "usb" / "release.key"
    dest.parent.mkdir()
    assert rk.main(["--path", str(key), "backup", "--to", str(dest)]) == 0
    out = capsys.readouterr().out
    # The copy is the key, and the tool says so rather than implying an
    # encrypted backup it does not make.
    assert "THAT FILE IS THE PRIVATE KEY" in out
    assert rk.read_secret(dest) == rk.read_secret(key)


def test_backup_to_a_directory_names_the_file_itself(key, tmp_path):
    folder = tmp_path / "vault"
    folder.mkdir()
    assert rk.main(["--path", str(key), "backup", "--to", str(folder)]) == 0
    assert (folder / "release.key").is_file()


def test_backup_never_silently_overwrites_an_existing_copy(key, tmp_path, capsys):
    dest = tmp_path / "copy.key"
    dest.write_text("something that might be the ONLY copy\n", encoding="utf-8")
    assert rk.main(["--path", str(key), "backup", "--to", str(dest)]) == 1
    assert "NOT overwriting" in capsys.readouterr().out
    assert rk.main(["--path", str(key), "backup", "--to", str(dest), "--force"]) == 0
    assert rk.read_secret(dest) == rk.read_secret(key)


def test_print_gives_the_line_a_password_manager_takes(key, capsys):
    assert rk.main(["--path", str(key), "backup", "--print"]) == 0
    out = capsys.readouterr().out
    assert "THIS LINE IS THE PRIVATE KEY" in out
    line = [ln for ln in out.splitlines() if ln.startswith("ccsync-release-key-v1")]
    assert len(line) == 1
    raw = base64.b64decode(line[0].split()[1], validate=True)
    assert raw == rk.read_secret(key)


def test_a_backup_is_recorded_beside_the_key_and_points_at_the_page(key, capsys):
    """`backed_up_at` is a DATE, like the protection page's own line: "the key
    is backed up" is a claim that ages. Beside the key rather than inside it,
    because the key file's format is one line of base64 that gets copied to an
    offline medium and read back by read_secret."""
    assert rk.main(["--path", str(key), "backup", "--print"]) == 0
    record = json.loads(rk.backup_record_path(key).read_text(encoding="utf-8"))
    assert record["backed_up_at"].endswith("Z")
    assert record["pubkey_id"]
    assert record["where"]
    # No JSON twin exists for the protection page's [ RECORD ] form (it is an
    # admin-session htmx post), and this script has no dashboard credential and
    # no business acquiring one, so it prints the instruction.
    out = capsys.readouterr().out
    assert "PROTECTION" in out and "I HAVE BACKED IT UP" in out


def test_backup_with_neither_to_nor_print_is_a_usage_error(key):
    with pytest.raises(SystemExit):
        rk.main(["--path", str(key), "backup"])
