"""bug-hunt 2026-09-03, territory dash-db-core.

Seven findings, all of them a rule this repo already states applied to one
more place: "a base rig holds no tick" on the READ side of the selections
model (dash-db-1), the id `notice()` hands back (dash-db-2), what a marker
write may leave inside a Syncthing folder (dash-db-3), the one-resolution
timestamp rule (dash-db-4), a sign-in method nobody implements (dash-core-1),
"no dashboard call follows a redirect" (dash-core-2), and `..` in a site path
list (dash-core-3).
"""

from __future__ import annotations

import datetime as dt
import os

import pytest

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import oidc
from ccsync_dashboard import provision
from ccsync_dashboard import site_store
from ccsync_dashboard.nas import NasError, TrueNASClient
from ccsync_dashboard.settings import Settings

NOW = "2026-09-03T10:00:00+00:00"


# ------------------------------------------------------------- dash-db-1

def _mixed_account(conn):
    """One person, one WIRED desktop and one remote laptop (the shape
    f27c181 / MULTI_BASE_RIG_PLAN §5 made supported), plus one project."""
    dbmod.record_known_editor(conn, "ed", source="admin", now=NOW)
    for machine, mode in (("DESK", "base"), ("LAP", "editor")):
        dbmod.upsert_machine(conn, "ed", machine, NOW)
        dbmod.upsert_machine_state(conn, "ed", machine, None, NOW, mode=mode)
    dbmod.upsert_project(conn, "projx", "2026/X", "/x", NOW)
    dbmod.upsert_project(conn, "projy", "2026/Y", "/y", NOW)
    conn.commit()


def test_a_wired_machine_never_inherits_the_unassigned_bucket(conn):
    """CR-28 was enforced on every WRITE path only. The bucket row is the
    one route left: the enforce cycle reads fetch_machine_selections and
    would offer a Syncthing share to the computer whose tree root IS the
    NAS share."""
    _mixed_account(conn)
    dbmod.add_selection(conn, "ed", "projx", "seed", NOW)          # machine=''
    conn.commit()

    assert dbmod.fetch_machine_selections(conn) == {"projx": [("ed", "LAP")]}
    assert dbmod.selections_for_machine(conn, "ed", "DESK") == []
    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ed", "LAP")] == ["projx"]


def test_the_bucket_still_reaches_every_editor_machine(conn):
    """The other direction: the new predicate must not make the bucket stop
    working for the machines it is FOR (the B16 under-share direction is safe
    for a removal, not for onboarding)."""
    dbmod.record_known_editor(conn, "ed", source="admin", now=NOW)
    for machine in ("LAP", "STUDIO"):
        dbmod.upsert_machine(conn, "ed", machine, NOW)
        dbmod.upsert_machine_state(conn, "ed", machine, None, NOW, mode="editor")
    dbmod.upsert_project(conn, "projx", "2026/X", "/x", NOW)
    dbmod.add_selection(conn, "ed", "projx", "seed", NOW)
    conn.commit()

    assert dbmod.fetch_machine_selections(conn) == {
        "projx": [("ed", "LAP"), ("ed", "STUDIO")]}


def test_copying_a_wired_machines_plan_is_refused_not_silently_empty(conn):
    """Since the bucket no longer reaches a base rig, its plan reads empty --
    and "copied 0 projects" is the answer that makes an admin believe the
    laptop was filled."""
    _mixed_account(conn)
    dbmod.add_selection(conn, "ed", "projx", "seed", NOW)
    conn.commit()

    with pytest.raises(ValueError) as excinfo:
        dbmod.copy_machine_plan(conn, "ed", "DESK", "LAP", "owen", NOW)
    assert "wired to the server" in str(excinfo.value)
    # ...and nothing was written to the target on the way out.
    assert [s["slug"] for s in dbmod.selections_for_machine(conn, "ed", "LAP")] == ["projx"]


# ------------------------------------------------------------- dash-db-2

def test_notice_returns_its_own_id_on_every_re_assert(conn):
    """SQLite does not touch last_insert_rowid() on the DO UPDATE path, so
    `cur.lastrowid` held the id of whatever was inserted most recently on
    this connection -- an audit row, here -- and it is truthy, which made the
    lookup below dead code and the returned id a dismiss target pointing at
    the wrong thing."""
    first = dbmod.notice(conn, "server_error", "error", "subj", body="a", now=NOW)
    for i in range(50):
        dbmod.audit(conn, "owen", "test.noise", f"s{i}", now=NOW)

    again = dbmod.notice(conn, "server_error", "error", "subj", body="b", now=NOW)
    assert again == first
    row = conn.execute(
        "SELECT id FROM notices WHERE kind='server_error' AND subject='subj'").fetchone()
    assert again == row["id"]


# ------------------------------------------------------------- dash-db-3

def test_a_marker_write_leaves_no_temp_file_inside_the_project(tmp_path, monkeypatch):
    """A project directory is a sendreceive Syncthing folder with
    ignoreDelete whose .stignore has no `*.tmp` pair: a temp file the
    fsWatcher catches mid-write is fanned out to every ticked editor and its
    removal is never propagated (the B12 / ytdl `.part` shape)."""
    projects = tmp_path / "Projects"
    project = projects / "2026" / "FF5" / "Animals"
    project.mkdir(parents=True)
    seen: list[list[str]] = []
    real_replace = os.replace

    def spy(src, dst):
        # What the watcher would see at the one moment the temp file exists.
        seen.append(sorted(p.name for p in project.iterdir()))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    provision.write_marker_data(project, {"slug": "animals", "includes": ["a"]})

    assert seen and all(names == [] for names in seen), seen
    assert provision.read_marker_data(project) == {"slug": "animals", "includes": ["a"]}
    assert sorted(p.name for p in project.iterdir()) == [provision.MARKER_FILENAME]
    # The temp file lived in the Projects dir and did not survive the replace.
    assert sorted(p.name for p in projects.iterdir()) == ["2026"]


def test_a_marker_rewrite_keeps_keys_it_does_not_own(tmp_path):
    project = tmp_path / "Projects" / "One"
    project.mkdir(parents=True)
    provision.write_marker_data(project, {"slug": "one", "includes": ["Assets/Luts"]})
    provision.write_marker(project, "one", created_by="self-heal")
    data = provision.read_marker_data(project)
    assert data["includes"] == ["Assets/Luts"]
    assert data["created_by"] == "self-heal"


# ------------------------------------------------------------- dash-db-4

def test_the_file_move_cutoff_fallback_has_the_stored_resolution():
    """Every stored timestamp comes from utcnow_iso(), which strips
    microseconds, and the comparison is lexicographic: a '.123456' fraction
    sorts above the '+00:00' it displaces and expires a row delivered in the
    same second one second early."""
    cutoff = dbmod._file_move_cutoff("not-a-timestamp", 7)
    assert "." not in cutoff, cutoff
    parsed = dt.datetime.fromisoformat(cutoff)
    assert parsed.microsecond == 0
    # And the happy path is unchanged.
    assert dbmod._file_move_cutoff("2026-09-03T10:00:00+00:00", 7).startswith("2026-08-27T10:00:00")


# ------------------------------------------------------------ dash-core-1

@pytest.mark.parametrize("raw", ["SMB", "Local", "local\n", " local"])
def test_a_miscased_auth_method_is_normalised_not_left_to_refuse_every_login(raw):
    """verify_credentials was the one consumer comparing the RAW value, so
    these four booted clean, described themselves as a valid method, let the
    wizard create the first admin, and then refused every password for ever."""
    settings = Settings.from_env({
        "DASH_AUTH_METHOD": raw,
        "DASH_SESSION_SECRET": "Kk3vZq7NpW2xR8tLm5Yc4Bd9Hs6Fj1Gu",
        "DASH_SMB_HOST": "nas",
        "DASH_LOCAL_USERS_DB": "x.db",
    })
    assert settings.auth_method == raw.strip().lower()
    assert [p for p in auth.check_boot_secrets(settings) if "DASH_AUTH_METHOD" in p] == []


def test_an_unknown_auth_method_refuses_to_boot_and_names_the_choices():
    settings = Settings(auth_method="smd",
                        session_secret="Kk3vZq7NpW2xR8tLm5Yc4Bd9Hs6Fj1Gu")
    problems = [p for p in auth.check_boot_secrets(settings) if "DASH_AUTH_METHOD" in p]
    assert len(problems) == 1
    assert "'smd'" in problems[0]
    for method in ("smb", "oidc", "local"):
        assert method in problems[0]


# ------------------------------------------------------------ dash-core-2

class _Redirect:
    status_code = 308
    headers = {"Location": "https://attacker.example/token"}

    def json(self):                                     # pragma: no cover
        raise AssertionError("a redirected token response must never be read")


def test_the_token_exchange_refuses_a_redirect_and_names_it(monkeypatch):
    """A 307/308 preserves method and body, and when the IdP does not
    advertise client_secret_basic the client secret rides in that body --
    `requests` strips an Authorization header across a host change, never a
    form field."""
    import requests

    seen = {}

    def fake_post(url, **kw):
        seen.update(kw)
        return _Redirect()

    monkeypatch.setattr(requests, "post", fake_post)
    with pytest.raises(oidc.OidcError) as excinfo:
        oidc._http_post_form("https://idp.example/token",
                             {"client_secret": "shhh"}, None)
    assert seen["allow_redirects"] is False
    assert "attacker.example" in str(excinfo.value)
    assert "308" in str(excinfo.value)


def test_the_discovery_get_still_follows_a_redirect(monkeypatch):
    """Deliberate carve-out: real IdPs 301 their .well-known document, the
    call carries no credential, and Discovery.get's issuer check bounds what
    the fetched document may claim."""
    import requests

    seen = {}

    class _Doc:
        status_code = 200

        def json(self):
            return {"issuer": "https://idp.example"}

    def fake_get(url, **kw):
        seen.update(kw)
        return _Doc()

    monkeypatch.setattr(requests, "get", fake_get)
    assert oidc._http_get_json("https://idp.example/.well-known/x")["issuer"]
    assert "allow_redirects" not in seen


def test_the_nas_client_refuses_a_redirect(monkeypatch):
    """The same rule on the NAS seam: these bodies carry a new editor's
    password."""
    seen = {}

    class FakeSession:
        def request(self, method, url, **kw):
            seen.update(kw)
            return _Redirect()

    client = TrueNASClient("nas.example", "truenas_admin", "pw",
                           session=FakeSession(), api_key="")
    with pytest.raises(NasError) as excinfo:
        client.post("/user", json_body={"password": "hunter2"})
    assert seen["allow_redirects"] is False
    assert "attacker.example" in str(excinfo.value)


# ------------------------------------------------------------ dash-core-3

@pytest.mark.parametrize("key", ["template_folders", "shared_asset_folders"])
@pytest.mark.parametrize("bad", [
    "../../etc/ccsync", "Assets/../../etc", "..\\..\\Windows",
    "/etc/ccsync", "\\\\nas\\share", "C:\\Windows",
])
def test_a_site_path_list_refuses_traversal_and_absolute_paths(key, bad):
    """setup_engine._run_storage mkdir's these under the tree root and the
    collector hands them to Syncthing as folder paths.
    _validate_canonical_prefix has refused `..` since it was written; the two
    list keys had only a control-character check."""
    with pytest.raises(site_store.SiteValidationError):
        site_store.validate(key, bad)


def test_a_site_path_list_still_accepts_the_shipped_defaults():
    assert site_store.validate(
        "shared_asset_folders", "Assets/B-roll Archive, Assets/Luts"
    ) == "Assets/B-roll Archive,Assets/Luts"


def test_shared_asset_folders_for_drops_traversal_defensively():
    """The DASH_SITE_SHARED_ASSETS environment value reaches this function
    without passing any validator."""
    assert provision.shared_asset_folders_for(["../../etc/ccsync"]) == [
        ("etc-ccsync", "etc/ccsync", "etc/ccsync")]
    assert provision.shared_asset_folders_for(["../.."]) == []
    assert provision.shared_asset_folders_for(["Assets/Luts"])[0][1] == "Assets/Luts"
