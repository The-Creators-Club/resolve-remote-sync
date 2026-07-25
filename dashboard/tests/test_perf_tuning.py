"""AUDIT_2 §4 performance items on the dashboard side.

P3  -- device entries get explicit TAILNET addresses instead of only
       "dynamic", and the relay/discovery kill-switch is OPT-IN.
P6  -- WAN folders get maxConcurrentWrites / pullerMaxPendingKiB.
P12 -- interval_inventory 300 -> 900.
P13 -- interval_completion 30 -> 60.
"""

from __future__ import annotations

import json

from ccsync_dashboard import provision
from ccsync_dashboard.settings import Settings
from ccsync_dashboard.syncthing_client import (
    DEFAULT_DEVICE_ADDRESSES,
    TAILNET_ONLY_OPTIONS,
    SyncthingClient,
    device_addresses_for,
)


class FakeSession:
    """Records every request; replies with `responses[(method, path)]`."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        path = url.split("//", 1)[-1].split("/", 1)[-1]
        self.calls.append(
            {"method": method, "url": url, "params": params, "body": json}
        )
        payload = self.responses.get((method, "/" + path), {})
        session = self

        class R:
            status_code = 200
            content = b"{}" if payload is None else b'{"x":1}'

            @staticmethod
            def json():
                return payload

        del session
        return R()


def _client(responses=None, **kwargs):
    session = FakeSession(responses)
    return SyncthingClient("http://st.local", "key", session=session, **kwargs), session


# -- P3: tailnet-first device addresses -------------------------------------


def test_device_addresses_put_the_tailnet_first_and_keep_dynamic_last():
    """"dynamic" means global discovery, which hands out the NAS's PUBLIC
    address; HiNet's inbound is blackholed and nothing forwards 22000, so
    Syncthing falls back to the public relay pool. Tailnet addresses first
    fix that; keeping "dynamic" LAST means a wrong tailnet IP degrades to
    today's behaviour instead of breaking the device outright."""
    assert device_addresses_for("100.64.1.5") == [
        "tcp://100.64.1.5:22000",
        "quic://100.64.1.5:22000",
        "dynamic",
    ]
    assert device_addresses_for("") == DEFAULT_DEVICE_ADDRESSES
    assert device_addresses_for("   ") == ["dynamic"]


def test_approve_device_stamps_the_configured_addresses():
    client, session = _client(
        {("GET", "/rest/config"): {"devices": []}},
        device_addresses=device_addresses_for("100.64.1.5"),
    )
    client.approve_device("DEV-1", "jsmith")

    post = next(c for c in session.calls if c["method"] == "POST")
    assert post["body"]["addresses"] == [
        "tcp://100.64.1.5:22000", "quic://100.64.1.5:22000", "dynamic",
    ]


def test_approve_device_default_is_unchanged_when_no_tailnet_ip_is_set():
    """An un-wired deployment must behave exactly as it does today."""
    client, session = _client({("GET", "/rest/config"): {"devices": []}})
    client.approve_device("DEV-1", "jsmith")
    post = next(c for c in session.calls if c["method"] == "POST")
    assert post["body"]["addresses"] == ["dynamic"]


def test_from_settings_wires_the_tailnet_ip():
    settings = Settings(
        syncthing_url="http://st.local", syncthing_api_key="k",
        syncthing_tailnet_ip="100.64.1.5",
    )
    client = SyncthingClient.from_settings(settings, session=FakeSession())
    assert client.device_addresses[0] == "tcp://100.64.1.5:22000"


def test_approve_device_never_rewrites_an_existing_device_s_addresses():
    """Sharing and addressing of already-known devices are somebody else's
    decision; this call only ever renames."""
    existing = {"deviceID": "DEV-1", "name": "old", "addresses": ["dynamic"]}
    client, session = _client(
        {("GET", "/rest/config"): {"devices": [existing]}},
        device_addresses=device_addresses_for("100.64.1.5"),
    )
    client.approve_device("DEV-1", "jsmith")
    put = next(c for c in session.calls if c["method"] == "PUT")
    assert put["body"]["addresses"] == ["dynamic"]
    assert put["body"]["name"] == "jsmith"


# -- P3: relay/discovery kill-switch is OPT-IN ------------------------------


def test_tailnet_only_options_are_not_applied_by_default():
    """The measured fleet state is a DERP-relayed path to the NAS, so
    disabling Syncthing's own relays today stops lane C rather than
    accelerating it. Default must be "change nothing, say what you would
    have changed"."""
    client, session = _client({("GET", "/rest/config/options"): {
        "relaysEnabled": True, "globalAnnounceEnabled": True,
        "natEnabled": True, "localAnnounceEnabled": True,
    }})
    pending = client.apply_tailnet_only_options(enabled=False)

    assert pending == {
        "relaysEnabled": False, "globalAnnounceEnabled": False, "natEnabled": False,
    }
    assert [c for c in session.calls if c["method"] == "PATCH"] == []


def test_tailnet_only_options_applied_when_explicitly_enabled():
    client, session = _client({("GET", "/rest/config/options"): {
        "relaysEnabled": True, "globalAnnounceEnabled": True,
        "natEnabled": True, "localAnnounceEnabled": True,
    }})
    client.apply_tailnet_only_options(enabled=True)

    patch = next(c for c in session.calls if c["method"] == "PATCH")
    assert patch["body"] == {
        "relaysEnabled": False, "globalAnnounceEnabled": False, "natEnabled": False,
    }


def test_local_discovery_is_never_disabled():
    """Keep localAnnounceEnabled true: it is how the base rig and any
    same-LAN editor find each other without discovery servers."""
    assert TAILNET_ONLY_OPTIONS["localAnnounceEnabled"] is True


def test_settings_default_leaves_the_relay_options_alone():
    assert Settings().syncthing_tailnet_only is False
    assert Settings().syncthing_tailnet_ip == ""
    env = Settings.from_env({})
    assert env.syncthing_tailnet_only is False
    assert env.syncthing_tailnet_ip == ""


def test_settings_read_the_tailnet_env_vars():
    env = Settings.from_env({
        "DASH_SYNCTHING_TAILNET_IP": " 100.64.1.5 ",
        "DASH_SYNCTHING_TAILNET_ONLY": "1",
    })
    assert env.syncthing_tailnet_ip == "100.64.1.5"
    assert env.syncthing_tailnet_only is True


# -- P6: WAN folder puller tuning -------------------------------------------


def test_folder_config_carries_the_wan_puller_tuning():
    cfg = provision.build_folder_config("slug", "2026/FF5/Alpha", "/data/Projects", ["DEV-1"])
    assert cfg["maxConcurrentWrites"] == 32
    assert cfg["pullerMaxPendingKiB"] == 65536
    # copiers/hashers stay at auto -- pinning them starves a box with many
    # folders.
    assert "copiers" not in cfg and "hashers" not in cfg


def test_folder_config_keeps_its_safety_properties():
    """Speed changes may not widen a deletion window: versioning and the
    send-receive type are not negotiable."""
    cfg = provision.build_folder_config("slug", "2026/FF5/Alpha", "/data/Projects", [])
    assert cfg["versioning"]["type"] == "staggered"
    assert cfg["type"] == "sendreceive"
    assert json.dumps(cfg)  # still JSON-serialisable for the REST call


# -- P12/P13: collector cadences --------------------------------------------


def test_inventory_interval_is_fifteen_minutes():
    """P12: _dir_signature is dir-mtime-only, so every file lane A uploads
    re-triggers the FULL per-file walk -- 100k stats plus a complete
    replace_nas_media rewrite every 5 minutes, on the box simultaneously
    serving SFTP and Syncthing."""
    assert Settings().interval_inventory == 900.0
    assert Settings.from_env({}).interval_inventory == 900.0


def test_completion_interval_is_sixty_seconds():
    """P13: completion polling scales as folders x devices and
    /rest/db/completion is computed on demand -- CPU taken from the
    Syncthing app that is supposed to be moving lane C bytes."""
    assert Settings().interval_completion == 60.0
    assert Settings.from_env({}).interval_completion == 60.0


def test_the_cadences_remain_overridable():
    env = Settings.from_env({
        "DASH_INTERVAL_INVENTORY": "300",
        "DASH_INTERVAL_COMPLETION": "30",
    })
    assert env.interval_inventory == 300.0
    assert env.interval_completion == 30.0
