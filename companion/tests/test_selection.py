"""Selection client tests: dashboard fetch, on-disk cache fallback, and
disabled/never-raise behavior -- in the style of test_reporter.py (injected
fake HTTP)."""

from __future__ import annotations

import json
import logging

import pytest

from ccsync_companion.selection import SelectionClient


def _cfg(**overrides):
    cfg = {
        "editor_name": "Alex",
        "dashboard_url": "http://dash.example.com",
        "dashboard_token": "tok123",
    }
    cfg.update(overrides)
    return cfg


_SAMPLE = [
    {"slug": "abcd-2026-ff5-nuclear", "label": "Nuclear", "rel_path": "2026/FF5/Nuclear", "position": 0, "active": True},
    {"slug": "efgh-2026-ff5-blast", "label": "Blast", "rel_path": "2026/FF5/Blast", "position": 1, "active": True},
]


# -- fetch -----------------------------------------------------


def test_fetch_success_writes_cache_and_returns_list(tmp_path):
    calls = []

    def fake_get(url, headers, timeout):
        calls.append((url, headers, timeout))
        return {"editor": "alex", "generated_at": "2026-07-24T00:00:00Z", "selection": _SAMPLE}

    client = SelectionClient(_cfg(), tmp_path, http_get=fake_get)
    result = client.fetch()

    assert result == _SAMPLE
    cache_path = tmp_path / "selection.json"
    assert cache_path.exists()
    cached = json.loads(cache_path.read_text(encoding="utf-8"))
    assert "fetched_at" in cached
    # Cache now stores the FULL response under "response", not just the
    # "selection" list, so the sticky "project_roots" mapping survives a
    # restart too -- see get_project_roots().
    assert cached["response"]["selection"] == _SAMPLE
    assert cached["response"]["editor"] == "alex"


def test_fetch_url_uses_lowercased_editor_name(tmp_path):
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        return {"selection": []}

    client = SelectionClient(_cfg(editor_name="Alex"), tmp_path, http_get=fake_get)
    client.fetch()
    assert calls[0] == "http://dash.example.com/api/v1/selection/alex"


def test_fetch_url_quotes_editor_name_with_space(tmp_path):
    # S-8: an unquoted space/non-ASCII editor_name breaks the URL entirely
    # (InvalidURL / UnicodeEncodeError from http.client) -- see
    # project_setup.py's quote(name, safe="") for the pattern this mirrors.
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        return {"selection": []}

    client = SelectionClient(_cfg(editor_name="alex chen"), tmp_path, http_get=fake_get)
    client.fetch()
    assert calls[0] == "http://dash.example.com/api/v1/selection/alex%20chen"


def test_fetch_uses_editor_name_fn_when_provided(tmp_path):
    # Selection identity finding: the editor name must be re-evaluated per
    # fetch via editor_name_fn (e.g. app.py's editor_identity(), which
    # reflects a tray sign-in), not pinned to cfg["editor_name"] at
    # construction time.
    calls = []
    names = iter(["alex", "jamie"])

    def fake_get(url, headers, timeout):
        calls.append(url)
        return {"selection": []}

    client = SelectionClient(
        _cfg(editor_name="ignored-config-name"), tmp_path, http_get=fake_get,
        editor_name_fn=lambda: next(names),
    )
    client.fetch()
    client.fetch()
    assert calls[0].endswith("/selection/alex")
    assert calls[1].endswith("/selection/jamie")


def test_fetch_skips_request_when_editor_name_fn_returns_blank(tmp_path):
    # A blank/None editor identity (not signed in yet, require_login=true)
    # must not hit /api/v1/selection/ at all -- that 404s every poll
    # forever instead of just falling back to the cache/none like any
    # other fetch failure.
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        return {"selection": []}

    client = SelectionClient(
        _cfg(editor_name="ignored-config-name"), tmp_path, http_get=fake_get,
        editor_name_fn=lambda: None,
    )
    assert client.fetch() is None
    assert calls == []


def test_fetch_skips_request_when_editor_name_fn_returns_whitespace(tmp_path):
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        return {"selection": []}

    client = SelectionClient(
        _cfg(), tmp_path, http_get=fake_get, editor_name_fn=lambda: "   ",
    )
    assert client.fetch() is None
    assert calls == []


def test_get_falls_back_to_cache_when_editor_name_fn_blank(tmp_path):
    def fake_get_ok(url, headers, timeout):
        return {"selection": _SAMPLE}

    seeding_client = SelectionClient(_cfg(), tmp_path, http_get=fake_get_ok)
    seeding_client.fetch()  # populate cache under a real fetch

    client = SelectionClient(
        _cfg(), tmp_path, http_get=lambda *a: (_ for _ in ()).throw(RuntimeError()),
        editor_name_fn=lambda: None,
    )
    selection, source = client.get()
    assert selection == _SAMPLE
    assert source == "cache"


def test_fetch_sends_token_header(tmp_path):
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(headers)
        return {"selection": []}

    client = SelectionClient(_cfg(dashboard_token="secret"), tmp_path, http_get=fake_get)
    client.fetch()
    assert calls[0]["X-CCSync-Token"] == "secret"


def test_fetch_omits_token_header_when_blank(tmp_path):
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(headers)
        return {"selection": []}

    client = SelectionClient(_cfg(dashboard_token=""), tmp_path, http_get=fake_get)
    client.fetch()
    assert "X-CCSync-Token" not in calls[0]


def test_fetch_failure_returns_none_and_does_not_raise(tmp_path):
    def failing_get(url, headers, timeout):
        raise RuntimeError("connection refused")

    client = SelectionClient(_cfg(), tmp_path, http_get=failing_get)
    assert client.fetch() is None


def test_fetch_failure_logs_once_per_streak(tmp_path, caplog):
    def failing_get(url, headers, timeout):
        raise RuntimeError("boom")

    client = SelectionClient(_cfg(), tmp_path, http_get=failing_get)
    with caplog.at_level(logging.DEBUG, logger="ccsync.selection"):
        client.fetch()
        client.fetch()

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    debugs = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert len(warnings) == 1
    assert len(debugs) == 1


def test_fetch_bad_shape_returns_none(tmp_path):
    def fake_get(url, headers, timeout):
        return {"nope": "not a selection"}

    client = SelectionClient(_cfg(), tmp_path, http_get=fake_get)
    assert client.fetch() is None


# -- disabled -----------------------------------------------------


def test_disabled_when_dashboard_url_blank(tmp_path):
    client = SelectionClient(_cfg(dashboard_url=""), tmp_path, http_get=lambda *a: None)
    assert client.enabled is False
    assert client.fetch() is None


# -- cache -----------------------------------------------------


def test_load_cached_reads_previously_written_cache(tmp_path):
    def fake_get(url, headers, timeout):
        return {"selection": _SAMPLE}

    client = SelectionClient(_cfg(), tmp_path, http_get=fake_get)
    client.fetch()

    client2 = SelectionClient(_cfg(), tmp_path, http_get=lambda *a: (_ for _ in ()).throw(RuntimeError()))
    assert client2.load_cached() == _SAMPLE


def test_load_cached_missing_file_returns_none(tmp_path):
    client = SelectionClient(_cfg(), tmp_path, http_get=lambda *a: None)
    assert client.load_cached() is None


def test_load_cached_malformed_json_returns_none(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "selection.json").write_text("not json {{{", encoding="utf-8")
    client = SelectionClient(_cfg(), tmp_path, http_get=lambda *a: None)
    assert client.load_cached() is None


# -- get() combined -----------------------------------------------------


def test_get_returns_live_when_fetch_succeeds(tmp_path):
    def fake_get(url, headers, timeout):
        return {"selection": _SAMPLE}

    client = SelectionClient(_cfg(), tmp_path, http_get=fake_get)
    selection, source = client.get()
    assert selection == _SAMPLE
    assert source == "live"


def test_get_falls_back_to_cache_when_fetch_fails(tmp_path):
    def fake_get_ok(url, headers, timeout):
        return {"selection": _SAMPLE}

    client = SelectionClient(_cfg(), tmp_path, http_get=fake_get_ok)
    client.fetch()  # populate cache

    def fake_get_fail(url, headers, timeout):
        raise RuntimeError("down")

    client2 = SelectionClient(_cfg(), tmp_path, http_get=fake_get_fail)
    selection, source = client2.get()
    assert selection == _SAMPLE
    assert source == "cache"


def test_get_returns_none_source_when_no_cache_and_fetch_fails(tmp_path):
    def failing_get(url, headers, timeout):
        raise RuntimeError("down")

    client = SelectionClient(_cfg(), tmp_path, http_get=failing_get)
    selection, source = client.get()
    assert selection is None
    assert source == "none"


def test_get_returns_none_source_when_disabled(tmp_path):
    client = SelectionClient(_cfg(dashboard_url=""), tmp_path, http_get=lambda *a: None)
    selection, source = client.get()
    assert selection is None
    assert source == "none"


# -- full-response cache round trip -----------------------------------------------


_SAMPLE_ROOTS = [
    {"resolve_project": "CCT Creator Profiles", "slug": "abcd-2026-creators-s1",
     "rel_path": "2026/Creator Profiles/Season 1", "source": "auto"},
]


def test_fetch_caches_full_response_including_project_roots(tmp_path):
    def fake_get(url, headers, timeout):
        return {"selection": _SAMPLE, "project_roots": _SAMPLE_ROOTS}

    client = SelectionClient(_cfg(), tmp_path, http_get=fake_get)
    client.fetch()

    cached = json.loads((tmp_path / "selection.json").read_text(encoding="utf-8"))
    assert cached["response"]["project_roots"] == _SAMPLE_ROOTS


def test_load_cached_still_returns_selection_list_from_full_response_cache(tmp_path):
    def fake_get(url, headers, timeout):
        return {"selection": _SAMPLE, "project_roots": _SAMPLE_ROOTS}

    client = SelectionClient(_cfg(), tmp_path, http_get=fake_get)
    client.fetch()

    client2 = SelectionClient(_cfg(), tmp_path, http_get=lambda *a: (_ for _ in ()).throw(RuntimeError()))
    assert client2.load_cached() == _SAMPLE


def test_load_cached_tolerates_old_cache_format(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    old_format = {"fetched_at": "2026-01-01T00:00:00Z", "selection": _SAMPLE}
    (tmp_path / "selection.json").write_text(json.dumps(old_format), encoding="utf-8")

    client = SelectionClient(_cfg(), tmp_path, http_get=lambda *a: None)
    assert client.load_cached() == _SAMPLE


def test_get_falls_back_to_cache_preserves_full_response_across_instances(tmp_path):
    def fake_get(url, headers, timeout):
        return {"selection": _SAMPLE, "project_roots": _SAMPLE_ROOTS}

    client = SelectionClient(_cfg(), tmp_path, http_get=fake_get)
    client.fetch()  # populate cache

    def fake_get_fail(url, headers, timeout):
        raise RuntimeError("down")

    client2 = SelectionClient(_cfg(), tmp_path, http_get=fake_get_fail)
    selection, source = client2.get()
    assert selection == _SAMPLE
    assert source == "cache"
    assert client2.get_project_roots() == {
        "cct creator profiles": "Projects/2026/Creator Profiles/Season 1",
    }


# -- get_project_roots -----------------------------------------------------


def test_get_project_roots_empty_when_never_fetched(tmp_path):
    client = SelectionClient(_cfg(), tmp_path, http_get=lambda *a: None)
    assert client.get_project_roots() == {}


def test_get_project_roots_empty_when_field_absent_older_server(tmp_path):
    def fake_get(url, headers, timeout):
        return {"selection": _SAMPLE}  # no "project_roots" key at all

    client = SelectionClient(_cfg(), tmp_path, http_get=fake_get)
    client.fetch()
    assert client.get_project_roots() == {}


def test_get_project_roots_maps_live_response_case_insensitively_with_projects_prefix(tmp_path):
    def fake_get(url, headers, timeout):
        return {"selection": _SAMPLE, "project_roots": _SAMPLE_ROOTS}

    client = SelectionClient(_cfg(), tmp_path, http_get=fake_get)
    client.fetch()

    roots = client.get_project_roots()
    assert roots == {"cct creator profiles": "Projects/2026/Creator Profiles/Season 1"}
    # lookup must be case-insensitive on the caller's side too -- the key
    # itself is stored lowercased.
    assert "CCT Creator Profiles".lower() in roots


def test_get_project_roots_uses_cache_when_no_live_fetch_this_run(tmp_path):
    def fake_get(url, headers, timeout):
        return {"selection": _SAMPLE, "project_roots": _SAMPLE_ROOTS}

    seeding_client = SelectionClient(_cfg(), tmp_path, http_get=fake_get)
    seeding_client.fetch()

    client = SelectionClient(_cfg(), tmp_path, http_get=lambda *a: (_ for _ in ()).throw(RuntimeError()))
    assert client.get_project_roots() == {
        "cct creator profiles": "Projects/2026/Creator Profiles/Season 1",
    }


def test_get_project_roots_ignores_entries_missing_required_fields(tmp_path):
    roots_with_gap = [
        {"resolve_project": "", "slug": "x", "rel_path": "2026/A/B", "source": "auto"},
        {"resolve_project": "Show", "slug": "y", "rel_path": "", "source": "auto"},
        {"resolve_project": "Good Show", "slug": "z", "rel_path": "2026/C/D", "source": "admin"},
    ]

    def fake_get(url, headers, timeout):
        return {"selection": [], "project_roots": roots_with_gap}

    client = SelectionClient(_cfg(), tmp_path, http_get=fake_get)
    client.fetch()
    assert client.get_project_roots() == {"good show": "Projects/2026/C/D"}


# -- project_roots rel_path containment (AUDIT_3 H-2) -----------------------


@pytest.mark.parametrize(
    "rel",
    ["../../../Windows/Temp/x", "2026/../../../evil", "\\evil", "/evil", "C:/evil", ".."],
)
def test_unsafe_project_root_rel_paths_are_dropped(tmp_path, rel, caplog):
    """Every other consumer of a dashboard rel_path validates it
    (sequencer._item_is_valid, repath._item_is_valid) -- this one built
    f"Projects/{rel_path}" from it unchecked, and that string becomes both a
    popup-fixer copy destination and the subpath app.consolidate_project
    hands to lane A, i.e. `rclone copy <outside the tree> nas:...`."""
    def fake_get(url, headers, timeout):
        return {
            "selection": _SAMPLE,
            "project_roots": [
                {"resolve_project": "Evil", "rel_path": rel},
                {"resolve_project": "Good", "rel_path": "2026/FF5/Nuclear"},
            ],
        }

    client = SelectionClient(_cfg(), tmp_path, http_get=fake_get)
    with caplog.at_level(logging.WARNING, logger="ccsync.selection"):
        mapping, source = client.project_roots_result()

    assert source == "live"
    assert "evil" not in mapping
    assert mapping == {"good": "Projects/2026/FF5/Nuclear"}
    assert any("rel_path" in r.message for r in caplog.records)


def test_project_roots_normalizes_a_trailing_slash(tmp_path):
    def fake_get(url, headers, timeout):
        return {
            "selection": _SAMPLE,
            "project_roots": [{"resolve_project": "Nuclear", "rel_path": "2026/FF5/Nuclear/"}],
        }

    client = SelectionClient(_cfg(), tmp_path, http_get=fake_get)
    mapping, _source = client.project_roots_result()
    assert mapping == {"nuclear": "Projects/2026/FF5/Nuclear"}


# -- TTL config keys (AUDIT_3 M-5) -----------------------------------------


def test_ttls_come_from_config_and_survive_a_hand_edited_value(tmp_path, caplog):
    """SelectionClient is built inside CompanionApp.__init__, so a bad value
    here used to raise before the tray/logging existed -- the windowed exe
    simply vanishing."""
    client = SelectionClient(
        _cfg(selection_fetch_ttl=5, project_roots_ttl=45), tmp_path, http_get=lambda *a: {}
    )
    assert client.fetch_ttl == 5.0
    assert client.project_roots_ttl == 45.0

    with caplog.at_level(logging.ERROR, logger="ccsync.config"):
        broken = SelectionClient(
            _cfg(selection_fetch_ttl="30s", project_roots_ttl=None), tmp_path,
            http_get=lambda *a: {},
        )
    assert broken.fetch_ttl == 30.0  # packaged default
    assert broken.project_roots_ttl == 300.0


# -- identity header on selection reads -------------------------------------


def test_fetch_sends_both_the_dashboard_token_and_the_identity_token(tmp_path):
    """The dashboard's selection endpoint requires X-CCSync-Identity as well
    as the fleet-wide X-CCSync-Token (the same rule /api/v1/report follows).
    A fetch carrying only the shared token 401s, and every managed editor
    then runs off its cached selection with no visible cause."""
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(dict(headers))
        return {"selection": _SAMPLE}

    client = SelectionClient(
        _cfg(), tmp_path, http_get=fake_get, identity_token_fn=lambda: "v2.identity.abc",
    )
    client.fetch()

    assert calls[0]["X-CCSync-Token"] == "tok123"
    assert calls[0]["X-CCSync-Identity"] == "v2.identity.abc"


def test_fetch_is_still_attempted_when_not_signed_in(tmp_path):
    """Graceful degrade: no identity means no header (never an empty one),
    the request still goes out, and a 401 lands on the existing
    fetch-failure path."""
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(dict(headers))
        return {"selection": _SAMPLE}

    client = SelectionClient(
        _cfg(), tmp_path, http_get=fake_get, identity_token_fn=lambda: None,
    )
    assert client.fetch() == _SAMPLE
    assert "X-CCSync-Identity" not in calls[0]
    assert calls[0]["X-CCSync-Token"] == "tok123"


def test_a_raising_identity_getter_never_breaks_the_fetch(tmp_path):
    def _boom():
        raise RuntimeError("identity manager is gone")

    def fake_get(url, headers, timeout):
        assert "X-CCSync-Identity" not in headers
        return {"selection": _SAMPLE}

    client = SelectionClient(_cfg(), tmp_path, http_get=fake_get, identity_token_fn=_boom)
    assert client.fetch() == _SAMPLE


def test_a_401_falls_back_to_the_cache_exactly_like_any_other_failure(tmp_path, caplog):
    import urllib.error

    def ok_get(url, headers, timeout):
        return {"selection": _SAMPLE}

    SelectionClient(_cfg(), tmp_path, http_get=ok_get).fetch()  # warm the cache

    def unauthorized(url, headers, timeout):
        raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)

    client = SelectionClient(
        _cfg(), tmp_path, http_get=unauthorized, identity_token_fn=lambda: None,
    )
    with caplog.at_level(logging.WARNING, logger="ccsync.selection"):
        selection, source = client.get()

    assert selection == _SAMPLE and source == "cache"


# -- SYNC-14: a stale mapping must never be labelled "live" -----------------


def _roots_response(rel="2026/FF5/Nuclear"):
    return {"selection": _SAMPLE,
            "project_roots": [{"resolve_project": "Nuclear", "rel_path": rel}]}


def test_a_failed_refresh_labels_the_mapping_cache_not_live(tmp_path):
    """SYNC-14. A failed fetch() leaves _last_response untouched, and the
    next line returned it tagged "live" -- so with the dashboard down the
    base rig filed media under a superseded root with full confidence, which
    is the CORE-H9 outcome by another door."""
    state = {"up": True}

    def fake_get(url, headers, timeout):
        if not state["up"]:
            raise OSError("dashboard unreachable")
        return _roots_response()

    client = SelectionClient(_cfg(), tmp_path, http_get=fake_get)
    mapping, source = client.project_roots_result()
    assert source == "live"

    state["up"] = False
    client._last_response_at -= client.project_roots_ttl + 1   # the TTL runs out

    mapping, source = client.project_roots_result()

    assert source == "cache"
    assert mapping == {"nuclear": "Projects/2026/FF5/Nuclear"}


def test_a_successful_refresh_is_still_live(tmp_path):
    """The other half: an expired TTL that refreshes cleanly must not be
    demoted -- "cache" would be just as much of a lie."""
    served = {"rel": "2026/FF5/Nuclear"}

    def fake_get(url, headers, timeout):
        return _roots_response(served["rel"])

    client = SelectionClient(_cfg(), tmp_path, http_get=fake_get)
    client.project_roots_result()

    served["rel"] = "2026/FF5/Nuclear Reissue"
    client._last_response_at -= client.project_roots_ttl + 1

    mapping, source = client.project_roots_result()

    assert source == "live"
    assert mapping == {"nuclear": "Projects/2026/FF5/Nuclear Reissue"}


def test_nothing_known_and_nothing_cached_is_still_unreachable(tmp_path):
    def fake_get(url, headers, timeout):
        raise OSError("dashboard unreachable")

    client = SelectionClient(_cfg(), tmp_path, http_get=fake_get)
    mapping, source = client.project_roots_result()

    assert (mapping, source) == ({}, "unreachable")
