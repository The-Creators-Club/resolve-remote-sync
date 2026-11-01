"""CR-378 (GL-17 beta half / GL-42 beta decision, 2026-10-07): the offline
release key as a passphrase-protected file.

Pins: the public key is byte-identical across encrypt (no rotation); the
plaintext is never replaced before the encrypted copy verifies; a wrong
passphrase or a tampered file refuses; the passphrase is asked once per
process and comes from the env for a child; a plaintext key still loads but
warns; backup of an encrypted key copies the encrypted bytes; pubkey, trusted
and bake never need the passphrase; the passphrase is never printed.
"""
from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(REPO / "companion" / "src"))

import release_key as rk  # noqa: E402
from ccsync_companion import ed25519  # noqa: E402

PASS = "correct horse battery staple"


@pytest.fixture(autouse=True)
def _fast_scrypt(monkeypatch):
    monkeypatch.setattr(rk, "SCRYPT_N", 2 ** 10)
    monkeypatch.delenv(rk.PASSPHRASE_ENV, raising=False)
    rk._passphrase_cache.clear()
    rk._warned_plaintext.clear()


@pytest.fixture
def plain(tmp_path):
    path = tmp_path / "release.key"
    assert rk.main(["--path", str(path), "new"]) == 0
    return path


def _encrypt(path, monkeypatch, passphrase=PASS):
    monkeypatch.setattr(rk, "ask_passphrase", lambda p, confirm=False: passphrase)
    rc = rk.main(["--path", str(path), "encrypt"])
    monkeypatch.undo()
    monkeypatch.setattr(rk, "SCRYPT_N", 2 ** 10)
    rk._passphrase_cache.clear()
    return rc


def test_encrypt_keeps_the_public_key_and_removes_the_plaintext(plain, monkeypatch, capsys):
    seed = rk.read_secret(plain)
    pub = rk.read_public(plain)
    assert _encrypt(plain, monkeypatch) == 0
    text = plain.read_text(encoding="utf-8")
    assert rk._HEADER_ENC in text
    assert base64.b64encode(seed).decode() not in text
    assert rk.is_encrypted(plain)
    assert rk.read_public(plain) == pub == ed25519.public_key(seed)
    monkeypatch.setenv(rk.PASSPHRASE_ENV, PASS)
    assert rk.read_secret(plain) == seed
    assert PASS not in capsys.readouterr().out


def test_short_passphrase_changes_nothing(plain, monkeypatch):
    before = plain.read_text(encoding="utf-8")
    assert _encrypt(plain, monkeypatch, "short") == 1
    assert plain.read_text(encoding="utf-8") == before
    assert not plain.with_name("release.key.enc.tmp").exists()


def test_failed_verification_leaves_plaintext_untouched(plain, monkeypatch):
    before = plain.read_text(encoding="utf-8")
    monkeypatch.setattr(rk, "decrypt_seed",
                        lambda env, pw: (_ for _ in ()).throw(ValueError("boom")))
    monkeypatch.setattr(rk, "ask_passphrase", lambda p, confirm=False: PASS)
    assert rk.main(["--path", str(plain), "encrypt"]) == 1
    assert plain.read_text(encoding="utf-8") == before
    assert not plain.with_name("release.key.enc.tmp").exists()


def test_wrong_passphrase_and_tamper_refuse(plain, monkeypatch):
    _encrypt(plain, monkeypatch)
    monkeypatch.setenv(rk.PASSPHRASE_ENV, "not the right one at all")
    with pytest.raises(SystemExit) as exc:
        rk.read_secret(plain)
    assert "wrong passphrase" in str(exc.value)
    # flip a byte of the envelope's ciphertext
    rk._passphrase_cache.clear()
    env = rk._find_envelope(plain)
    ct = bytearray(base64.b64decode(env["ct"]))
    ct[0] ^= 1
    env["ct"] = base64.b64encode(bytes(ct)).decode()
    with pytest.raises(ValueError):
        rk.decrypt_seed(env, PASS)


def test_asked_once_per_process(plain, monkeypatch):
    _encrypt(plain, monkeypatch)
    calls = []
    monkeypatch.setattr(rk.getpass, "getpass", lambda prompt="": calls.append(prompt) or PASS)
    monkeypatch.setattr(rk, "_has_console", lambda: True)
    a = rk.read_secret(plain)
    b = rk.read_secret(plain)
    assert a == b and len(calls) == 1


def test_no_terminal_and_no_env_refuses_actionably(plain, monkeypatch):
    _encrypt(plain, monkeypatch)
    monkeypatch.setattr(rk.sys, "stdin", type("T", (), {"isatty": lambda self: False})())
    with pytest.raises(SystemExit) as exc:
        rk.read_secret(plain)
    assert rk.PASSPHRASE_ENV in str(exc.value)


def test_plaintext_still_loads_but_warns(plain, capsys):
    rk.read_secret(plain)
    err = capsys.readouterr().err
    assert "UNENCRYPTED" in err and "release_key.py encrypt" in err


def test_pubkey_trusted_bake_and_status_need_no_passphrase(plain, monkeypatch, capsys, tmp_path):
    pub = base64.b64encode(rk.read_public(plain)).decode()
    _encrypt(plain, monkeypatch)
    monkeypatch.setattr(rk.sys, "stdin", type("T", (), {"isatty": lambda self: False})())
    capsys.readouterr()
    assert rk.main(["--path", str(plain), "pubkey", "--quiet"]) == 0
    assert capsys.readouterr().out.strip() == pub
    assert rk.main(["--path", str(plain), "trusted", "--quiet"]) == 0
    assert capsys.readouterr().out.strip() == pub
    assert rk.main(["--path", str(plain), "status"]) == 0
    assert capsys.readouterr().out.strip() == "encrypted"
    target = tmp_path / "release_pubkey.py"
    target.write_text("RELEASE_PUBKEYS: tuple[str, ...] = (\n)\n", encoding="utf-8")
    assert rk.main(["--path", str(plain), "bake", "--target", str(target)]) == 0
    assert pub in target.read_text(encoding="utf-8")


def test_backup_of_an_encrypted_key_copies_the_encrypted_file(plain, monkeypatch, tmp_path):
    seed_line = base64.b64encode(rk.read_secret(plain)).decode()
    _encrypt(plain, monkeypatch)
    dest = tmp_path / "usb" / "release.key"
    assert rk.main(["--path", str(plain), "backup", "--to", str(dest)]) == 0
    assert dest.read_bytes() == plain.read_bytes()
    assert seed_line not in dest.read_text(encoding="utf-8")


def test_unlock_for_run_exports_for_children(plain, monkeypatch):
    _encrypt(plain, monkeypatch)
    monkeypatch.setenv(rk.PASSPHRASE_ENV, PASS)
    assert rk.unlock_for_run(plain) is True
    monkeypatch.setenv(rk.PASSPHRASE_ENV, "wrong wrong wrong wrong")
    rk._passphrase_cache.clear()
    with pytest.raises(SystemExit):
        rk.unlock_for_run(plain)


def test_unlock_for_run_is_a_noop_for_plaintext(plain):
    assert rk.unlock_for_run(plain) is False


def test_ship_and_publish_latest_ask_once():
    ship = (TOOLS / "ship.ps1").read_text(encoding="utf-8")
    assert "CCSYNC_RELEASE_KEY_PASSPHRASE" in ship and "-AsSecureString" in ship
    latest = (TOOLS / "publish_latest.py").read_text(encoding="utf-8")
    assert "unlock_for_run" in latest


def test_pubkey_and_trusted_on_a_plaintext_key_write_nothing_to_stderr(plain, capsys):
    # release.ps1's key-parity probe runs under EAP=Stop: any stderr is fatal there.
    capsys.readouterr()
    assert rk.main(["--path", str(plain), "pubkey", "--quiet"]) == 0
    assert rk.main(["--path", str(plain), "pubkey"]) == 0
    assert capsys.readouterr().err == ""


def test_check_accepts_right_and_refuses_wrong_passphrase(plain, monkeypatch, capsys):
    assert _encrypt(plain, monkeypatch) == 0
    monkeypatch.setenv(rk.PASSPHRASE_ENV, "wrong wrong wrong wrong")
    assert rk.main(["--path", str(plain), "check"]) == 1
    rk._passphrase_cache.clear()
    monkeypatch.setenv(rk.PASSPHRASE_ENV, PASS)
    assert rk.main(["--path", str(plain), "check"]) == 0


def test_failed_swap_leaves_the_plaintext_key_intact(plain, monkeypatch):
    seed = rk.read_secret(plain)
    monkeypatch.setattr(rk, "ask_passphrase", lambda p, confirm=False: PASS)
    real = rk.os.replace
    calls = []

    def flaky(a, b):
        calls.append(a)
        if len(calls) == 2:
            raise PermissionError("locked")
        return real(a, b)
    monkeypatch.setattr(rk.os, "replace", flaky)
    assert rk.main(["--path", str(plain), "encrypt"]) == 1
    monkeypatch.setattr(rk.os, "replace", real)
    assert not rk.is_encrypted(plain)
    assert rk.read_secret(plain) == seed


def test_ship_checks_the_passphrase_and_skips_dashboard_only():
    ship = (TOOLS / "ship.ps1").read_text(encoding="utf-8")
    assert "release_key.py\") --path $relKeyFile check" in ship
    assert "-not $DashboardOnly -and (Test-Path -LiteralPath $relKeyFile)" in ship
