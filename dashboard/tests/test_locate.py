"""`POST /api/v1/files/locate` -- where else on the NAS a file lives.

docs/HAND_MOVES_ON_THE_SERVER.md phase 2. The route is what turns a hand move
on the NAS from "lane B trashed 69 files and parked itself" into a rename, so
the cases that matter here are the ones where an over-eager answer would move
an editor's footage somewhere it does not belong: two candidates, no
candidate, and an inventory that has never been walked at all.
"""
from __future__ import annotations

import unicodedata

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, db as dbmod, locate as locate_mod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret-not-a-real-one"
TOKEN = "companion-token-not-a-real-one"
NOW = "2026-09-11T19:00:00Z"


@pytest.fixture
def env(tmp_path):
    projects = tmp_path / "tree" / "Projects"
    projects.mkdir(parents=True)
    settings = Settings(db_path=str(tmp_path / "locate.db"), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}),
                        projects_dir=str(projects))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(settings.db_path)
        yield client, conn
        conn.close()


def hdr(editor="jsmith"):
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def seed(conn, slug, rows, now=NOW):
    pid = dbmod.upsert_project(conn, slug, slug, f"Projects/{slug}", now)
    assert dbmod.replace_nas_media(
        conn, pid, [(rel, "original", ".mov", size, 1) for rel, size in rows],
        f"sig-{slug}", 1, now, force=True)
    conn.commit()
    return pid


def ask(client, files, editor="jsmith"):
    return client.post("/api/v1/files/locate", json={"files": files}, headers=hdr(editor))


def test_found_in_the_project_it_was_taken_from(env):
    client, conn = env
    seed(conn, "cct-s1", [("Interviews/gold.mov", 1234)])
    body = ask(client, [{"name": "gold.mov", "size": 1234}]).json()
    assert body["walked"] is True
    assert body["as_of"] == NOW
    (entry,) = body["files"]
    assert entry["name"] == "gold.mov" and entry["size"] == 1234
    assert entry["found"] == [{"project_slug": "cct-s1",
                               "rel_path": "Interviews/gold.mov"}]


def test_found_in_another_project_is_the_whole_point(env):
    """The move that started this: out of the project the machine syncs, into
    one it does not. A per-project answer would have said "deleted"."""
    client, conn = env
    seed(conn, "cct-s1", [("Interviews/other.mov", 99)])
    seed(conn, "ff5-talent-gap", [("Interviewees/gold.mov", 1234)])
    (entry,) = ask(client, [{"name": "gold.mov", "size": 1234}]).json()["files"]
    assert entry["found"] == [{"project_slug": "ff5-talent-gap",
                               "rel_path": "Interviewees/gold.mov"}]


def test_two_places_come_back_as_two(env):
    """Ambiguity is reported, never resolved here (design section 6). The
    companion declines to move a file with more than one candidate."""
    client, conn = env
    seed(conn, "a", [("One/gold.mov", 1234)])
    seed(conn, "b", [("Two/gold.mov", 1234)])
    (entry,) = ask(client, [{"name": "gold.mov", "size": 1234}]).json()["files"]
    assert sorted(f["project_slug"] for f in entry["found"]) == ["a", "b"]


def test_a_different_size_is_not_the_same_file(env):
    client, conn = env
    seed(conn, "cct-s1", [("Interviews/gold.mov", 1234)])
    body = ask(client, [{"name": "gold.mov", "size": 4321},
                        {"name": "never-existed.mov", "size": 1234}]).json()
    assert [e["found"] for e in body["files"]] == [[], []]
    # The order asked is the order answered: the caller matches by position
    # as well as by name.
    assert [e["name"] for e in body["files"]] == ["gold.mov", "never-existed.mov"]


def test_an_archived_project_is_not_a_destination(env):
    client, conn = env
    seed(conn, "old", [("Interviews/gold.mov", 1234)])
    conn.execute("UPDATE projects SET active=0 WHERE slug='old'")
    conn.commit()
    (entry,) = ask(client, [{"name": "gold.mov", "size": 1234}]).json()["files"]
    assert entry["found"] == []


def test_never_walked_says_so(env):
    """"Not found" from an empty inventory means "not known", and the
    companion must change nothing on it."""
    client, conn = env
    body = ask(client, [{"name": "gold.mov", "size": 1234}]).json()
    assert body["walked"] is False
    assert body["as_of"] == ""
    assert body["files"][0]["found"] == []


def test_a_mac_spelling_matches_the_nas_spelling(env):
    """CR-90: the trashed name came off a Mac's disk (NFD), the inventory off
    the NAS (NFC). Compared as bytes they are two different files, and every
    accented name would read as a deletion."""
    client, conn = env
    nfc = unicodedata.normalize("NFC", "Matej Simalčík.mov")
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd
    seed(conn, "cct-s1", [(f"Interviews/{nfc}", 77)])
    (entry,) = ask(client, [{"name": nfd, "size": 77}]).json()["files"]
    assert entry["found"] == [{"project_slug": "cct-s1",
                               "rel_path": f"Interviews/{nfc}"}]
    # The path handed back is the server's own spelling: it is what the
    # companion renames to, and there the bytes on disk are the truth.
    assert entry["found"][0]["rel_path"].endswith(nfc)


def test_a_path_is_reduced_to_its_basename(env):
    """A caller that sends the old relative path is asking about its name:
    the path is exactly what stopped being true."""
    client, conn = env
    seed(conn, "cct-s1", [("Interviews/gold.mov", 1234)])
    (entry,) = ask(client, [{"name": "Old/Place/gold.mov", "size": 1234}]).json()["files"]
    assert entry["found"][0]["rel_path"] == "Interviews/gold.mov"


def test_the_cap_is_a_413_with_a_sentence(env):
    client, conn = env
    seed(conn, "cct-s1", [("Interviews/gold.mov", 1234)])
    files = [{"name": f"f{i}.mov", "size": i}
             for i in range(locate_mod.MAX_LOCATE_FILES + 1)]
    r = ask(client, files)
    assert r.status_code == 413
    assert str(locate_mod.MAX_LOCATE_FILES) in r.json()["detail"]
    # ...and exactly the cap is answered.
    assert ask(client, files[:locate_mod.MAX_LOCATE_FILES]).status_code == 200


def test_the_fleet_credential_is_required(env):
    client, conn = env
    seed(conn, "cct-s1", [("Interviews/gold.mov", 1234)])
    body = {"files": [{"name": "gold.mov", "size": 1234}]}
    # No credential at all, and a wrong one, never reach the route: the login
    # gate answers them, exactly as it does the jobs claim beside it.
    assert client.post("/api/v1/files/locate", json=body).status_code == 401
    assert client.post("/api/v1/files/locate", json=body,
                       headers={"X-CCSync-Token": "wrong"}).status_code == 401
    # A token with no signed identity is refused too: this answer drives a
    # rename on an editor's disk, so the caller has to be a verified machine.
    assert client.post("/api/v1/files/locate", json=body,
                       headers={"X-CCSync-Token": TOKEN}).status_code == 403


def test_duplicate_questions_are_asked_once(env):
    client, conn = env
    seed(conn, "cct-s1", [("Interviews/gold.mov", 1234)])
    body = ask(client, [{"name": "gold.mov", "size": 1234},
                        {"name": "gold.mov", "size": 1234}]).json()
    assert len(body["files"]) == 1
