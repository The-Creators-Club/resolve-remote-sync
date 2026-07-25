"""SyncthingAdmin tests: a fake http_request records calls so we can assert
on method/path/body without a real Syncthing instance -- in the style of
test_syncthing_lane.py."""

from __future__ import annotations

import pytest

from ccsync_companion.sync.syncthing_admin import STIGNORE_LINES, SyncthingAdmin


def _admin(**kwargs):
    calls = []

    def fake_http_request(method, url, api_key, body, timeout):
        calls.append({"method": method, "url": url, "api_key": api_key, "body": body, "timeout": timeout})
        return {}

    admin = SyncthingAdmin(
        syncthing_url="http://127.0.0.1:8384",
        api_key="testkey",
        http_request=fake_http_request,
        **kwargs,
    )
    return admin, calls


def test_set_folder_paused_sends_patch_true():
    admin, calls = _admin()
    admin.set_folder_paused("abcd-nuclear", True)
    assert len(calls) == 1
    call = calls[0]
    assert call["method"] == "PATCH"
    assert call["url"] == "http://127.0.0.1:8384/rest/config/folders/abcd-nuclear"
    assert call["body"] == {"paused": True}
    assert call["api_key"] == "testkey"


def test_set_folder_paused_sends_patch_false():
    admin, calls = _admin()
    admin.set_folder_paused("abcd-nuclear", False)
    assert calls[0]["body"] == {"paused": False}


def test_pending_folders_passthrough():
    def fake_http_request(method, url, api_key, body, timeout):
        assert method == "GET"
        assert url == "http://127.0.0.1:8384/rest/cluster/pending/folders"
        return {"abcd-nuclear": {"offeredBy": {"DEVICE-1": {"time": "now", "label": "Nuclear"}}}}

    admin = SyncthingAdmin(syncthing_url="http://127.0.0.1:8384", api_key="testkey", http_request=fake_http_request)
    result = admin.pending_folders()
    assert result == {"abcd-nuclear": {"offeredBy": {"DEVICE-1": {"time": "now", "label": "Nuclear"}}}}


def test_accept_folder_posts_config_paused_then_ignores_then_unpauses():
    admin, calls = _admin()
    admin.accept_folder(
        "abcd-nuclear", label="2026/FF5/Nuclear",
        local_path="/local/Projects/2026/FF5/Nuclear",
        offered_by_device_id="DEVICE-1",
    )
    assert len(calls) == 3

    config_call = calls[0]
    assert config_call["method"] == "POST"
    assert config_call["url"] == "http://127.0.0.1:8384/rest/config/folders"
    body = config_call["body"]
    assert body["id"] == "abcd-nuclear"
    assert body["label"] == "2026/FF5/Nuclear"
    assert body["path"] == "/local/Projects/2026/FF5/Nuclear"
    assert body["type"] == "sendreceive"
    # Created paused: set_ignores must land before Syncthing can pull
    # anything, or a hand-provisioned/older server folder would start
    # duplicating the video/Proxy content lanes A/B already carry.
    assert body["paused"] is True
    assert body["fsWatcherEnabled"] is True
    assert body["ignorePerms"] is False
    assert body["devices"] == [{"deviceID": "DEVICE-1", "introducedBy": ""}]

    ignores_call = calls[1]
    assert ignores_call["method"] == "POST"
    assert ignores_call["url"] == "http://127.0.0.1:8384/rest/db/ignores?folder=abcd-nuclear"
    assert ignores_call["body"] == {"ignore": STIGNORE_LINES}

    unpause_call = calls[2]
    assert unpause_call["method"] == "PATCH"
    assert unpause_call["url"] == "http://127.0.0.1:8384/rest/config/folders/abcd-nuclear"
    assert unpause_call["body"] == {"paused": False}


def test_accept_folder_leaves_folder_paused_when_set_ignores_fails():
    calls = []

    def fake_http_request(method, url, api_key, body, timeout):
        calls.append({"method": method, "url": url, "body": body})
        if method == "POST" and "ignores" in url:
            raise RuntimeError("syncthing unreachable")
        return {}

    admin = SyncthingAdmin(
        syncthing_url="http://127.0.0.1:8384", api_key="testkey", http_request=fake_http_request,
    )

    with pytest.raises(RuntimeError):
        admin.accept_folder(
            "abcd-nuclear", label="2026/FF5/Nuclear",
            local_path="/local/Projects/2026/FF5/Nuclear",
            offered_by_device_id="DEVICE-1",
        )

    # Only the paused-create and the failed set_ignores attempt happened --
    # no unpause PATCH, so the folder is left paused rather than silently
    # syncing without the video/Proxy ignores in place.
    assert [c["method"] for c in calls] == ["POST", "POST"]
    assert calls[0]["body"]["paused"] is True


def test_stignore_lines_include_braw_and_proxy_patterns():
    assert "(?i)*.braw" in STIGNORE_LINES
    assert "(?i)Proxy" in STIGNORE_LINES
    assert "(?i)**/Proxy" in STIGNORE_LINES
    assert "(?i)**/Proxy/**" in STIGNORE_LINES
    # every video extension from rclone_lane.VIDEO_EXTS must be covered too,
    # so lane C never carries what lanes A/B already own.
    from ccsync_companion.sync.rclone_lane import VIDEO_EXTS

    for ext in VIDEO_EXTS:
        assert f"(?i)*{ext}" in STIGNORE_LINES


def test_set_ignores_direct_call():
    admin, calls = _admin()
    admin.set_ignores("abcd-nuclear", ["(?i)*.mov"])
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "http://127.0.0.1:8384/rest/db/ignores?folder=abcd-nuclear"
    assert calls[0]["body"] == {"ignore": ["(?i)*.mov"]}


def test_folder_status_get():
    admin, calls = _admin()
    admin.folder_status("abcd-nuclear")
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "http://127.0.0.1:8384/rest/db/status?folder=abcd-nuclear"


def test_get_config_get():
    admin, calls = _admin()
    admin.get_config()
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "http://127.0.0.1:8384/rest/config"


def test_api_key_resolved_from_config_xml_when_not_configured(tmp_path):
    config_path = tmp_path / "config.xml"
    config_path.write_text(
        "<configuration><gui><apikey>fromxml</apikey></gui></configuration>", encoding="utf-8"
    )
    calls = []

    def fake_http_request(method, url, api_key, body, timeout):
        calls.append(api_key)
        return {}

    admin = SyncthingAdmin(
        syncthing_url="http://127.0.0.1:8384", api_key="", http_request=fake_http_request,
        config_xml_path=config_path,
    )
    admin.get_config()
    assert calls[0] == "fromxml"
