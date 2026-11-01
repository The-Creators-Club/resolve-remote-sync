"""CR-362 (prelaunch review GL-00 / GL-01 / GL-02, 2026-10-07): the appliance
boots into a dashboard a new customer can actually sign in to, knows where its
own Syncthing is, and trusts the vendor's key and feed with nothing typed.

The compose file is read as text (no YAML parser in this venv, same approach
as tools/tests/test_compose_appliance.py) and its dashboard `environment:`
block is fed to Settings.from_env, so what is pinned is the paste-and-boot
shape and not a hand-copied dict.
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from fastapi.testclient import TestClient

from ccsync_dashboard import auth, protection, setup_engine, vendor_defaults
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

REPO = Path(__file__).resolve().parents[2]
COMPOSE = REPO / "dashboard" / "deploy" / "compose.appliance.yaml"
COMPANION_PUBKEY_FILE = (REPO / "companion" / "src" / "ccsync_companion"
                         / "release_pubkey.py")
STRONG = "kX9-quiet-harbour-42-zephyr"


def _dashboard_env() -> dict[str, str]:
    """The `environment:` mapping of the `dashboard` service, with
    `${VAR:-default}` resolved to its default (the paste-it-unedited case)."""
    lines = COMPOSE.read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln == "  dashboard:")
    env: dict[str, str] = {}
    in_env = False
    for ln in lines[start + 1:]:
        if re.match(r"^  [a-z-]+:\s*$", ln):
            break
        if re.match(r"^    environment:\s*$", ln):
            in_env = True
            continue
        if in_env:
            if re.match(r"^    \S", ln):
                break
            m = re.match(r'^      ([A-Z0-9_]+): "(.*)"\s*$', ln)
            if m:
                value = re.sub(r"\$\{[A-Z_]+:-([^}]*)\}", r"\1", m.group(2))
                env[m.group(1)] = value
    return env


def _settings(tmp_path) -> Settings:
    env = _dashboard_env()
    env["DASH_DB_PATH"] = str(tmp_path / "d.db")
    env["DASH_SESSION_SECRET"] = STRONG   # what secrets_boot generates on boot
    env["DASH_PROJECTS_DIR"] = str(tmp_path)
    return Settings.from_env(env)


def test_the_compose_env_selects_local_accounts(tmp_path):
    # GL-00: the default is smb, which on this path means NAS logins against
    # an empty NAS address.
    assert _dashboard_env()["DASH_AUTH_METHOD"] == "local"
    assert _settings(tmp_path).auth_method == "local"


def test_boot_is_clean_and_the_first_admin_can_be_created(tmp_path):
    settings = _settings(tmp_path)
    assert auth.check_boot_secrets(settings) == []
    # No poller or collector against hosts that do not exist in a test.
    quiet = dataclasses.replace(settings, release_feed_url="", syncthing_url="")
    with TestClient(create_app(quiet)) as c:
        assert c.get("/api/v1/setup/status").json() == {
            "auth_method": "local", "users_exist": False}
        resp = c.post("/api/v1/setup/admin",
                      json={"username": "owner", "password": "correct-horse-battery"})
        assert resp.status_code == 200, resp.text
        assert c.get("/api/v1/me").json() == {"user": "owner", "is_admin": True}


def test_smb_with_no_nas_address_refuses_to_boot():
    problems = auth.check_boot_secrets(
        Settings(session_secret=STRONG, auth_method="smb", smb_host=""))
    assert any("DASH_SMB_HOST" in p and "local" in p for p in problems)


def test_smb_with_a_nas_address_and_login_off_still_boots():
    assert auth.check_boot_secrets(
        Settings(session_secret=STRONG, auth_method="smb", smb_host="nas.example")) == []
    # No session secret = login is off, a documented lab shape: not refused.
    assert auth.check_boot_secrets(Settings(auth_method="smb")) == []


def test_syncthing_gui_url_points_at_the_tailnet_namespace(tmp_path):
    # GL-01: syncthing runs in the tailscale service's network namespace.
    assert _dashboard_env()["SYNCTHING_GUI_URL"] == "http://tailscale:8384"
    assert _settings(tmp_path).syncthing_url == "http://tailscale:8384"


# ------------------------------------------------------- vendor key and feed

def test_the_appliance_trusts_the_vendor_key_and_feed_by_default(tmp_path):
    settings = _settings(tmp_path)
    assert settings.vendor_defaults is True
    assert settings.release_pubkeys == vendor_defaults.VENDOR_RELEASE_PUBKEYS
    assert settings.release_feed_url == vendor_defaults.VENDOR_FEED_URL
    assert settings.release_feed_url.startswith("https://")


def test_the_baked_key_equals_the_key_the_companion_trusts():
    """Two copies by necessity (two deployment units); a drift would make a
    vendor build verify on one side and be refused on the other."""
    text = COMPANION_PUBKEY_FILE.read_text(encoding="utf-8")
    block = re.search(r"RELEASE_PUBKEYS: tuple\[str, \.\.\.\] = \((.*?)\n\)", text, re.S)
    companion_keys = tuple(re.findall(r'"([A-Za-z0-9+/=]{44})"', block.group(1)))
    assert companion_keys, "could not read the companion's baked keys"
    assert set(vendor_defaults.VENDOR_RELEASE_PUBKEYS) <= set(companion_keys)


def test_the_environment_beats_the_baked_default_even_when_empty():
    """The studio renders both variables into its compose, possibly empty.
    Empty is a decision; a default must never replace it through an upgrade."""
    env = {"DASH_VENDOR_DEFAULTS": "1", "DASH_RELEASE_FEED_URL": "",
           "DASH_RELEASE_PUBKEYS": ""}
    s = Settings.from_env(env)
    assert s.release_feed_url == "" and s.release_pubkeys == ()
    other = Settings.from_env({
        "DASH_VENDOR_DEFAULTS": "1",
        "DASH_RELEASE_FEED_URL": "https://feed.example/channel.json",
        "DASH_RELEASE_PUBKEYS": vendor_defaults.VENDOR_RELEASE_PUBKEYS[0]})
    assert other.release_feed_url == "https://feed.example/channel.json"


def test_without_the_switch_nothing_is_defaulted():
    s = Settings.from_env({})
    assert s.release_feed_url == "" and s.release_pubkeys == ()
    assert s.vendor_defaults is False
    # A typo leaves it off.
    assert Settings.from_env({"DASH_VENDOR_DEFAULTS": "true"}).release_pubkeys == ()


def test_select_code_root_sees_the_same_default(monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "select_code_root_cr362", REPO / "dashboard" / "deploy" / "select_code_root.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "APP_ROOT", REPO / "dashboard")
    monkeypatch.delenv("DASH_RELEASE_PUBKEYS", raising=False)
    monkeypatch.delenv("DASH_VENDOR_DEFAULTS", raising=False)
    assert mod.release_pubkeys() == ()
    monkeypatch.setenv("DASH_VENDOR_DEFAULTS", "1")
    assert mod.release_pubkeys() == vendor_defaults.VENDOR_RELEASE_PUBKEYS
    monkeypatch.setenv("DASH_RELEASE_PUBKEYS", "")
    assert mod.release_pubkeys() == ()


# ---------------------------------------------- "who holds the private half"

class _Ctx:
    def __init__(self, settings):
        self.settings = settings

    def acks(self):
        return {}

    now = "2026-10-07T00:00:00+00:00"


def test_vendor_held_key_is_not_a_missing_backup():
    s = Settings(vendor_defaults=True,
                 release_pubkeys=vendor_defaults.VENDOR_RELEASE_PUBKEYS)
    out = protection._check_key_backup(_Ctx(s))
    assert out.state == "ok" and "vendor holds" in out.detail


def test_a_studio_with_the_same_key_still_has_to_back_it_up():
    # No vendor_defaults flag = the studio's own site, which holds the private
    # half on its base rig: the red line stays.
    s = Settings(release_pubkeys=vendor_defaults.VENDOR_RELEASE_PUBKEYS)
    out = protection._check_key_backup(_Ctx(s))
    assert out.state != "ok" and "vendor holds" not in out.detail


def test_the_wizard_names_the_vendors_key():
    from types import SimpleNamespace
    ctx = SimpleNamespace(settings=Settings(
        vendor_defaults=True, release_pubkeys=vendor_defaults.VENDOR_RELEASE_PUBKEYS))
    state = setup_engine._check_release_key(ctx)
    assert state.status == "ok" and "vendor" in state.detail
    todo = setup_engine._check_release_key(SimpleNamespace(settings=Settings()))
    assert todo.status == "todo" and "your release key" not in todo.detail
    assert "vendor" in todo.detail


# ---------------------------------------- overseer round 2 (2026-10-07)

def test_the_appliance_boots_with_the_vendor_feed_configured_and_checks_it(
        tmp_path, monkeypatch):
    """GL-02 asked for a boot WITH the feed configured (the earlier test blanked
    it). The vendor's private key is not in the tree, so the channel is signed
    with a test key that stands in for the pinned one; the URL is the real
    baked VENDOR_FEED_URL and the fetch is stubbed."""
    import base64
    import json

    from ccsync_dashboard import ed25519, release_feed

    seed = bytes(range(32))
    pub = base64.b64encode(ed25519.public_key(seed)).decode("ascii")
    channel = {"schema": 1, "generated_at": "2026-10-07T00:00:00Z",
               "channel": "stable", "packages": [],
               "dashboard_image": {"tag": "", "digest": ""}}
    sig = base64.b64encode(ed25519.sign(
        seed, release_feed.canonical_channel_bytes(channel))).decode("ascii")
    url = vendor_defaults.VENDOR_FEED_URL
    served = {url: json.dumps(channel).encode(), url + ".sig": sig.encode()}
    asked: list[str] = []

    def fake_fetch(u, *, cap, timeout=0):
        asked.append(u)
        return served[u]

    monkeypatch.setattr(release_feed, "_fetch_bytes", fake_fetch)
    settings = dataclasses.replace(_settings(tmp_path), release_pubkeys=(pub,),
                                   syncthing_url="")
    assert settings.release_feed_url == url        # the feed stays ON
    with TestClient(create_app(settings)) as c:
        made = c.post("/api/v1/setup/admin", json={
            "username": "owner", "password": "correct-horse-battery"})
        assert made.status_code == 200, made.text
        login = c.post("/api/v1/login", json={
            "username": "owner", "password": "correct-horse-battery"})
        assert login.status_code == 200, login.text
        r = c.post("/api/v1/admin/feed/check",
                   headers={"X-CSRF-Token": login.json()["csrf"]})
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True, r.json()
    assert url in asked


def test_the_auth_method_refusal_does_not_say_generate_secrets(tmp_path, monkeypatch):
    import pytest
    monkeypatch.delenv("DASH_DEV_INSECURE", raising=False)
    bad = dataclasses.replace(_settings(tmp_path), auth_method="smb", smb_host="",
                              nas_host="", dev_insecure=False)
    with pytest.raises(RuntimeError) as exc:
        create_app(bad)
    assert "DASH_AUTH_METHOD" in str(exc.value)
    assert "openssl rand" not in str(exc.value)


def test_a_vendor_build_is_not_asked_to_confirm_a_key_backup(tmp_path):
    from ccsync_dashboard import db as dbmod
    vendor = _settings(tmp_path)
    conn = dbmod.connect(tmp_path / "p.db")
    dbmod.migrate(conn)
    assert protection.page_view(conn, vendor)["show_key_ack"] is False
    # The studio's shape (no switch) and a caller that cannot say keep the row.
    studio = dataclasses.replace(vendor, vendor_defaults=False)
    assert protection.page_view(conn, studio)["show_key_ack"] is True
    assert protection.page_view(conn)["show_key_ack"] is True
    conn.close()


def test_the_protection_partial_hides_the_key_ack_row_on_a_vendor_build(tmp_path):
    from ccsync_dashboard import db as dbmod
    vendor = _settings(tmp_path)
    with TestClient(create_app(dataclasses.replace(vendor, syncthing_url=""))) as c:
        assert c.post("/api/v1/setup/admin", json={
            "username": "owner", "password": "correct-horse-battery"}).status_code == 200
        r = c.get("/admin/protection")
        assert r.status_code == 200, r.text[:300]
        assert "The release signing key is backed up" not in r.text
        assert "A restore from a backup was tried" in r.text
    studio = dataclasses.replace(vendor, vendor_defaults=False,
                                 db_path=str(tmp_path / "studio.db"), syncthing_url="")
    with TestClient(create_app(studio)) as c:
        c.post("/api/v1/setup/admin", json={
            "username": "owner", "password": "correct-horse-battery"})
        r = c.get("/admin/protection")
        assert "The release signing key is backed up" in r.text


def test_a_vendor_customer_flag_gets_the_vendor_page_end_to_end(tmp_path):
    """CR-362 round 2 (2026-10-07): the install_dashboard_app container carries
    DASH_VENDOR_CUSTOMER, not vendor_defaults. The page, the backup check and
    the wizard must treat it the same, and a studio with the same key not."""
    from types import SimpleNamespace
    from ccsync_dashboard import db as dbmod
    keys = vendor_defaults.VENDOR_RELEASE_PUBKEYS
    cust = Settings(vendor_customer=True, release_pubkeys=keys)
    conn = dbmod.connect(tmp_path / "vc.db")
    dbmod.migrate(conn)
    assert protection.page_view(conn, cust)["show_key_ack"] is False
    assert protection.page_view(conn, Settings(release_pubkeys=keys))["show_key_ack"] is True
    conn.close()
    out = protection._check_key_backup(_Ctx(cust))
    assert out.state == "ok" and "vendor holds" in out.detail
    state = setup_engine._check_release_key(SimpleNamespace(settings=cust))
    assert state.status == "ok" and "vendor" in state.detail
