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


def test_stignore_lines_cover_the_fixers_partial_temp_files():
    """AUDIT_2 CORE-H5: fix_clip copies to "<dest>.ccsync-tmp" then
    os.replace()s it. The extension patterns match by EXTENSION, so
    "A001.braw.ccsync-tmp" matched none of them -- if the process died
    mid-copy, lane C uploaded a half-written 12 GB BRAW to the NAS and fanned
    it out to every other ticked editor, permanently."""
    assert "(?i)**/*.ccsync-tmp" in STIGNORE_LINES
    assert "(?i)*.ccsync-tmp" in STIGNORE_LINES


# -- versioning (AUDIT_2 DEL-6) ---------------------------------------------


def test_accept_folder_creates_the_folder_with_staggered_versioning():
    """Editor-side folders had NO versioning: the safety net existed only on
    the server, so every propagated delete removed the editor's only copy."""
    admin, calls = _admin()
    admin.accept_folder(
        "abcd-nuclear", label="2026/FF5/Nuclear",
        local_path="/local/Projects/2026/FF5/Nuclear", offered_by_device_id="DEVICE-1",
    )
    versioning = calls[0]["body"]["versioning"]
    assert versioning["type"] == "staggered"
    assert versioning["params"] == {"cleanInterval": "3600", "maxAge": "2592000"}


def test_ensure_versioning_patches_a_folder_that_has_none():
    calls = []

    def fake_http_request(method, url, api_key, body, timeout):
        calls.append({"method": method, "url": url, "body": body})
        if method == "GET":
            return {"id": "abcd-nuclear", "path": "/local/x"}  # no versioning key
        return {}

    admin = SyncthingAdmin(
        syncthing_url="http://127.0.0.1:8384", api_key="k", http_request=fake_http_request
    )
    assert admin.ensure_versioning("abcd-nuclear") is True
    assert calls[-1]["method"] == "PATCH"
    assert calls[-1]["body"]["versioning"]["type"] == "staggered"


def test_ensure_versioning_is_a_noop_when_already_set():
    calls = []

    def fake_http_request(method, url, api_key, body, timeout):
        calls.append(method)
        return {"id": "abcd-nuclear", "versioning": {"type": "staggered", "params": {}}}

    admin = SyncthingAdmin(
        syncthing_url="http://127.0.0.1:8384", api_key="k", http_request=fake_http_request
    )
    assert admin.ensure_versioning("abcd-nuclear") is False
    assert calls == ["GET"]


def test_ensure_versioning_accepts_a_prefetched_folder_config():
    admin, calls = _admin()
    assert admin.ensure_versioning("abcd", folder={"versioning": {"type": "trashcan"}}) is False
    assert calls == []


# -- timeouts (AUDIT_2 L-11) ------------------------------------------------


def test_config_writes_use_the_longer_timeout():
    """Syncthing COMMITS THE CONFIG AND RESTARTS THE FOLDER on these calls,
    which on a rig with many folders routinely exceeds the 5 s read timeout.
    A timeout mid-sweep left every selected folder paused."""
    admin, calls = _admin()
    admin.set_folder_paused("abcd", True)
    admin.set_folder_path("abcd", "/new/path")
    admin.set_ignores("abcd", ["(?i)*.mov"])
    assert [c["timeout"] for c in calls] == [30.0, 30.0, 30.0]

    admin.folder_status("abcd")
    admin.get_config()
    assert [c["timeout"] for c in calls[3:]] == [5.0, 5.0]


# -- completion (AUDIT_2 P5) ------------------------------------------------


def test_completion_asks_what_the_remote_device_still_needs_from_us():
    admin, calls = _admin()
    admin.completion("abcd-nuclear", "NAS-DEVICE")
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == (
        "http://127.0.0.1:8384/rest/db/completion?folder=abcd-nuclear&device=NAS-DEVICE"
    )


def test_system_status_get():
    admin, calls = _admin()
    admin.system_status()
    assert calls[0]["url"] == "http://127.0.0.1:8384/rest/system/status"


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


# -- path diagnostics (AUDIT_2 P3/C-6) --------------------------------------


def test_connections_hits_the_system_connections_endpoint():
    """The one call that settles "is lane C relaying?" -- and nothing in
    production made it before."""
    admin, calls = _admin()
    admin.connections()
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "http://127.0.0.1:8384/rest/system/connections"


# -- maxFolderConcurrency (AUDIT_2 P4/C-1) ----------------------------------


def _admin_with_options(options):
    calls = []

    def fake_http_request(method, url, api_key, body, timeout):
        calls.append({"method": method, "url": url, "body": body, "timeout": timeout})
        if method == "GET" and url.endswith("/rest/config/options"):
            return dict(options)
        return {}

    admin = SyncthingAdmin(
        syncthing_url="http://127.0.0.1:8384", api_key="k", http_request=fake_http_request,
    )
    return admin, calls


def test_ensure_max_folder_concurrency_patches_when_unset():
    admin, calls = _admin_with_options({})
    assert admin.ensure_max_folder_concurrency(2) is True
    writes = [c for c in calls if c["method"] == "PATCH"]
    assert len(writes) == 1
    assert writes[0]["url"] == "http://127.0.0.1:8384/rest/config/options"
    assert writes[0]["body"] == {"maxFolderConcurrency": 2}
    # An options write commits the config, so it must use the long timeout.
    assert writes[0]["timeout"] == admin.config_write_timeout


def test_ensure_max_folder_concurrency_is_a_no_op_when_already_set():
    """Steady state must cost one GET and ZERO config commits -- the whole
    point of replacing the pause scheme is not writing config in a loop."""
    admin, calls = _admin_with_options({"maxFolderConcurrency": 2})
    assert admin.ensure_max_folder_concurrency(2) is False
    assert [c for c in calls if c["method"] == "PATCH"] == []


def test_ensure_max_folder_concurrency_ignores_a_zero_request():
    admin, calls = _admin_with_options({})
    assert admin.ensure_max_folder_concurrency(0) is False
    assert calls == []


# -- URL encoding of folder ids (AUDIT_3 L-10) ------------------------------


def test_folder_id_is_percent_encoded_in_the_path():
    """Folder IDs are dashboard project slugs, not constants of this
    codebase. A "/" or "?" in one silently addressed a DIFFERENT REST
    endpoint -- e.g. a PATCH meant to pause a folder landing elsewhere."""
    admin, calls = _admin()
    admin.set_folder_paused("weird/id?x=1#frag", True)
    assert calls[0]["url"] == (
        "http://127.0.0.1:8384/rest/config/folders/weird%2Fid%3Fx%3D1%23frag"
    )


def test_folder_id_is_encoded_for_query_parameter_endpoints():
    admin, calls = _admin()
    admin.folder_status("weird id&folder=other")
    admin.set_ignores("a/b", ["(?i)*.mov"])
    admin.completion("a b", "DEV ICE&x=1")

    assert calls[0]["url"] == (
        "http://127.0.0.1:8384/rest/db/status?folder=weird+id%26folder%3Dother"
    )
    assert calls[1]["url"] == "http://127.0.0.1:8384/rest/db/ignores?folder=a%2Fb"
    assert calls[2]["url"] == (
        "http://127.0.0.1:8384/rest/db/completion?folder=a+b&device=DEV+ICE%26x%3D1"
    )


def test_ordinary_slugs_keep_their_plain_urls():
    """The slugs production actually uses must not change shape."""
    admin, calls = _admin()
    admin.get_folder("abcd-2026-ff5-nuclear")
    admin.folder_status("abcd-2026-ff5-nuclear")
    assert calls[0]["url"] == (
        "http://127.0.0.1:8384/rest/config/folders/abcd-2026-ff5-nuclear"
    )
    assert calls[1]["url"] == (
        "http://127.0.0.1:8384/rest/db/status?folder=abcd-2026-ff5-nuclear"
    )


# -- per-home API-key fallback (alex_laptop, 2026-07-26) --------------------


def test_request_falls_back_across_homes_on_403(tmp_path, monkeypatch):
    """A preserved-but-stale managed home's key must not silence every
    sequencer write against a veteran instance from the stock home."""
    import urllib.error

    from ccsync_companion.sync import syncthing_lane as lane_mod

    monkeypatch.setattr(lane_mod.platform, "system", lambda: "Windows")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for rel, key in (("ccsync/syncthing-config/config.xml", "managed-key"),
                     ("Syncthing/config.xml", "stock-key")):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            f"<configuration><gui><apikey>{key}</apikey></gui></configuration>",
            encoding="utf-8",
        )

    seen = []

    def fake_http_request(method, url, api_key, body, timeout):
        seen.append(api_key)
        if api_key != "stock-key":
            raise urllib.error.HTTPError(url, 403, "Forbidden", None, None)
        return {"folders": []}

    admin = SyncthingAdmin(api_key="", http_request=fake_http_request)
    assert admin.get_config() == {"folders": []}
    assert seen == ["managed-key", "stock-key"]
    # The accepted key is remembered and tried first afterwards.
    seen.clear()
    admin.get_config()
    assert seen == ["stock-key"]


def test_request_raises_the_auth_error_when_every_key_is_rejected(tmp_path, monkeypatch):
    import urllib.error

    from ccsync_companion.sync import syncthing_lane as lane_mod

    monkeypatch.setattr(lane_mod.platform, "system", lambda: "Windows")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    p = tmp_path / "ccsync" / "syncthing-config" / "config.xml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "<configuration><gui><apikey>managed-key</apikey></gui></configuration>",
        encoding="utf-8",
    )

    def fake_http_request(method, url, api_key, body, timeout):
        raise urllib.error.HTTPError(url, 403, "Forbidden", None, None)

    admin = SyncthingAdmin(api_key="", http_request=fake_http_request)
    with pytest.raises(urllib.error.HTTPError):
        admin.get_config()
