"""Two people, two episodes: the pool, the landing page and the slug.

docs/CARDS_TWO_PROJECTS.md phase 1 (2026-09-14). `test_cards_mount.py` still
owns the shim, the gate and the tunnel; this suite owns what the pool added.

The properties defended, each of them a way this goes wrong live:

  * A PATH IS NOT A KEY (CR-90). The slug is minted from an NFC-normalised,
    case-folded path, so a Mac's NFD spelling of an episode and everyone
    else's NFC spelling are ONE episode, not two engines on one folder.
  * ONE DATA DIR PER ENGINE. They used to share `<data>/cards`, where
    `project_pick.doc_save` is a read-merge-write through a fixed `.tmp` with
    no cross-process lock: two engines calling `remember()` at once truncate
    each other.
  * THE CAP IS A SENTENCE, NOT A SILENCE. There is no eviction, because
    `stop()` in the other repo does not stop the three `while True` threads,
    so the third entrant is refused with who is where and what to do.
  * THE LANDING PAGE NEEDS NO ENGINE. It is what a person sees exactly when
    every engine is busy, loading or broken.
  * `/api/root` IS BLOCKED. One click on the drawer's root menu would move
    engine A onto root B and make the pool's key a lie.
  * THE PHONE BREAKS FIRST. The old worker's scope covers the new URLs, so
    `/cards/sw.js` is a kill switch; and the manifest, icon and worker under
    the episode prefix must be reachable with no session or Chrome calls the
    page not installable (CR-100).
"""
from __future__ import annotations

import time
import unicodedata

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth, cards, cards_pool
from ccsync_dashboard.app import create_app

from test_cards_mount import (SECRET, fake_src, make_settings,  # noqa: F401
                              make_vault, open_episode)


# ------------------------------------------------------------------ the slug

def test_the_two_spellings_of_a_mac_path_are_one_episode():
    """CR-90: macOS listdir is NFD, the NAS and Windows are NFC, and
    `Matej Simalcik` in the two spellings is two byte strings. A slug minted
    off the raw path would be two engines on one folder, each rewriting the
    other's stores."""
    nfc = unicodedata.normalize("NFC", "X:/Vault/2026/FF5/Matej Šimalčík")
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd                                    # the premise
    assert cards_pool.slug_for(nfc) == cards_pool.slug_for(nfd)


def test_the_slug_ignores_case_and_separators_the_way_a_share_does():
    assert (cards_pool.slug_for("X:\\Vault\\FF5\\Civil Defence")
            == cards_pool.slug_for("x:/vault/ff5/civil defence/"))


def test_a_slug_is_url_shaped_even_for_a_root_with_no_ascii_in_it():
    """The readable half is decoration; the digest is what is load-bearing.
    A CJK episode name has no readable half and must still route."""
    slug = cards_pool.slug_for("X:/Vault/2026/FF5/台中無人機")
    assert cards_pool.is_slug(slug), slug
    assert slug != cards_pool.slug_for("X:/Vault/2026/FF5/台北無人機")


def test_two_episodes_do_not_share_a_slug():
    a = cards_pool.slug_for("X:/Vault/FF5/Civil Defence")
    b = cards_pool.slug_for("X:/Vault/FF5/Framing Formosa")
    assert a != b and cards_pool.is_slug(a) and cards_pool.is_slug(b)


def test_junk_in_the_path_is_not_a_slug():
    for junk in ("", "../etc", "a" * 60, "Civil Defence", "x/y"):
        assert cards_pool.is_slug(junk) is False


# -------------------------------------------------------------- the registry

def test_the_vault_scan_finds_episodes_and_not_their_insides(tmp_path):
    vault, roots, _ = make_vault(tmp_path, "Civil Defence", "Framing Formosa")
    (roots[0] / "Interviewees" / "Enoch" / "Clips").mkdir(parents=True)
    found = cards_pool.episodes(str(vault))
    assert [r["name"] for r in found] == ["Civil Defence", "Framing Formosa"]
    assert [r["show"] for r in found] == ["FF5", "FF5"]
    # ...and NOT the Interviewees folder that has a Clips in it: the walk
    # stops at the first folder that is itself an episode.
    assert all("Interviewees" not in r["root"] for r in found)


def test_the_scan_reaches_the_live_tree_which_is_four_deep(tmp_path):
    """The default depth is the DEPLOYED shape, not a guess (2026-09-14).

    `DASH_CARDS_VAULT_ROOT` is `/vault` -- the whole `vault_host` share -- and
    the episode `site.toml` names is `/vault/Vault/2026/FF5/Civil Defence`:
    Vault, 2026, FF5, episode. A three-level walk answers an empty list
    there, which is a landing page with nothing on it and nothing to explain
    why. Found before this page was ever deployed; keep it found.
    """
    vault = tmp_path / "vault"
    root = vault / "Vault" / "2026" / "FF5" / "Civil Defence"
    (root / "Interviewees").mkdir(parents=True)
    found = cards_pool.episodes(str(vault))
    assert [r["name"] for r in found] == ["Civil Defence"]
    assert found[0]["show"] == "FF5"


def test_a_vault_that_is_not_there_is_an_empty_list_not_a_raise(tmp_path):
    assert cards_pool.episodes(str(tmp_path / "gone")) == []
    assert cards_pool.episodes("") == []


# ------------------------------------------------------------------ the pool

class FakeEngine:
    def __init__(self, root):
        self.root = root
        self.stopped = False

    def stop(self):
        self.stopped = True

    def fleet_execute(self, *a, **kw):           # the pinned-executor seam
        return {}


def make_pool(cap=2, fail=""):
    built = []

    def build(root):
        if fail and fail in root:
            raise RuntimeError("no postgres")
        engine = FakeEngine(root)
        built.append(engine)
        return engine, object()

    return cards_pool.EnginePool(build, cap=cap), built


def settle(entry, timeout=5.0):
    end = time.monotonic() + timeout
    while entry.state == cards_pool.LOADING and time.monotonic() < end:
        time.sleep(0.005)
    return entry


def test_opening_the_same_episode_twice_is_one_engine():
    pool, built = make_pool()
    first, _ = pool.open("X:/Vault/FF5/Civil Defence")
    settle(first)
    again, refusal = pool.open("X:/Vault/FF5/Civil Defence/")   # same place
    assert refusal == "" and again is first
    assert len(built) == 1


def test_the_third_episode_is_refused_with_who_is_where():
    """No eviction: `stop()` upstream sets a flag the library worker, the
    tokens worker and the translator do not read, so an LRU would leak a
    sweep and a translator per evicted engine. The refusal is the feature."""
    pool, _ = make_pool(cap=2)
    a, _ = pool.open("X:/Vault/FF5/Civil Defence", name="Civil Defence")
    b, _ = pool.open("X:/Vault/FF5/Framing Formosa", name="Framing Formosa")
    settle(a), settle(b)
    pool.note_visit(a.slug, "alex")
    pool.note_visit(b.slug, "ruskin")
    third, refusal = pool.open("X:/Vault/FF6/Repro Rights", name="Repro Rights")
    assert third is None
    assert "2 episodes are already open" in refusal
    assert "Civil Defence (alex)" in refusal
    assert "Framing Formosa (ruskin)" in refusal
    assert "admin" in refusal                       # what to do about it


def test_closing_one_frees_the_seat_and_stops_that_engine():
    pool, built = make_pool(cap=1)
    a, _ = pool.open("X:/Vault/FF5/Civil Defence")
    settle(a)
    assert pool.open("X:/Vault/FF5/Framing Formosa")[0] is None
    assert "closed" in pool.drop(a.slug)
    assert built[0].stopped is True
    b, refusal = pool.open("X:/Vault/FF5/Framing Formosa")
    assert b is not None and refusal == ""


def test_an_episode_that_will_not_build_holds_no_seat():
    """A failed entry must not spend the cap: an episode with a broken
    PostgreSQL would otherwise lock a person out of the one that works."""
    pool, _ = make_pool(cap=1, fail="Broken")
    bad, _ = pool.open("X:/Vault/FF5/Broken")
    settle(bad)
    assert bad.state == cards_pool.FAILED
    good, refusal = pool.open("X:/Vault/FF5/Civil Defence")
    assert good is not None, refusal


def test_any_engine_answers_for_the_pinned_executor():
    """A pinned media job's paths are (root name, relative path) pairs
    resolved against the CONTAINER's mounts, so any engine's ffmpeg worker
    can run any job. What matters is that there may be none."""
    pool, _ = make_pool()
    assert pool.any_engine() is None
    entry, _ = pool.open("X:/Vault/FF5/Civil Defence")
    settle(entry)
    assert pool.any_engine() is entry.engine


def test_an_editor_is_in_exactly_one_episode_at_a_time():
    pool, _ = make_pool()
    a, _ = pool.open("X:/Vault/FF5/Civil Defence")
    b, _ = pool.open("X:/Vault/FF5/Framing Formosa")
    settle(a), settle(b)
    pool.note_visit(a.slug, "alex")
    assert pool.engine_for("alex") is a.engine
    pool.note_visit(b.slug, "alex")             # the laptop moved episode
    assert pool.engine_for("alex") is b.engine
    assert pool.engine_for("ruskin") is None
    assert pool.engine_for("") is None


def test_stop_all_stops_every_engine():
    pool, built = make_pool()
    for root in ("X:/Vault/FF5/A", "X:/Vault/FF5/B"):
        settle(pool.open(root)[0])
    pool.stop_all()
    assert [e.stopped for e in built] == [True, True]
    assert pool.entries() == []


# ------------------------------------------------------------ the data dirs

def test_every_engine_gets_its_own_data_dir(tmp_path, fake_src, monkeypatch):
    """They used to share `<data>/cards`, which holds the mirror, the
    picker's memory and the lane keys -- and `project_pick.doc_save` is a
    read-merge-write through a fixed `.tmp` with no cross-process lock."""
    monkeypatch.delenv("CARDS_SRC", raising=False)
    vault, roots, _ = make_vault(tmp_path, "Civil Defence", "Framing Formosa")
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=fake_src,
        cards_vault_root=str(vault)))
    entries = [open_episode(app, root) for root in roots]
    dirs = [e.engine.built["data_dir"] for e in entries]
    assert dirs[0] != dirs[1]
    assert all(d and str(tmp_path) in d for d in dirs)
    for entry, data in zip(entries, dirs):
        assert data.endswith(entry.slug)


def test_the_boot_root_in_cards_ui_json_is_not_read_any_more(tmp_path, fake_src,
                                                             monkeypatch):
    """It recorded "the root the UI last picked" for a container with one
    engine in it. With a pool it is at best meaningless and at worst a second
    engine on a root that already has one: the URL carries the key now."""
    monkeypatch.delenv("CARDS_SRC", raising=False)
    vault, roots, _ = make_vault(tmp_path, "Civil Defence", "Framing Formosa")
    data = tmp_path / "cards"
    data.mkdir()
    (data / "cards_ui.json").write_text('{"root": "%s"}'
                                        % str(roots[1]).replace("\\", "/"),
                                        encoding="utf-8")
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=fake_src,
        cards_vault_root=str(vault)))
    entry = open_episode(app, roots[0])
    assert entry.engine.root == str(roots[0])


# --------------------------------------------------------- the landing page

@pytest.fixture
def landing(tmp_path, fake_src, monkeypatch):
    monkeypatch.delenv("CARDS_SRC", raising=False)
    vault, roots, _ = make_vault(tmp_path, "Civil Defence", "Framing Formosa")
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=fake_src,
        cards_vault_root=str(vault), cards_engines=2))
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME,
                           auth.make_session_cookie(SECRET, "owen"))
        yield client, app, roots


def test_the_landing_page_draws_with_no_engine_at_all(landing):
    client, app, _ = landing
    assert app.state.cards_pool.entries() == []          # nothing built yet
    page = client.get("/cards/")
    assert page.status_code == 200
    assert "Civil Defence" in page.text
    assert "Framing Formosa" in page.text


def test_opening_an_episode_from_the_page_then_entering_it(landing):
    client, app, roots = landing
    slug = cards_pool.slug_for(str(roots[0]))
    opened = client.post("/cards/open", data={"slug": slug},
                         follow_redirects=False)
    assert opened.status_code == 303
    entry = app.state.cards_pool.get(slug)
    assert entry is not None
    while entry.state == cards_pool.LOADING:
        time.sleep(0.01)
    assert entry.state == cards_pool.READY
    assert client.get(f"/cards/p/{slug}/").status_code == 200


def test_an_episode_that_is_not_open_sends_a_navigation_to_the_landing_page(landing):
    """It never builds an engine in the request path: construction reads an
    episode off a share, and this runs on the event loop."""
    client, app, roots = landing
    slug = cards_pool.slug_for(str(roots[0]))
    resp = client.get(f"/cards/p/{slug}/", follow_redirects=False,
                      headers={"Accept": "text/html"})
    assert resp.status_code == 303
    assert resp.headers["location"].endswith(f"/cards/?want={slug}")
    assert app.state.cards_pool.entries() == []
    # ...and a FETCH gets JSON, never a login-page-shaped surprise.
    api = client.get(f"/cards/p/{slug}/api/state",
                     headers={"Accept": "application/json"})
    assert api.status_code == 409
    assert api.json()["landing"] == "/cards/"


def test_a_flat_page_url_from_before_the_pool_says_where_it_went(landing):
    client, app, _ = landing
    api = client.get("/cards/api/state", headers={"Accept": "application/json"})
    assert api.status_code == 404
    assert "one page per episode" in api.json()["error"]


def test_only_an_admin_closes_an_episode(landing):
    client, app, roots = landing
    entry = open_episode(app, roots[0])
    client.cookies.set(auth.COOKIE_NAME,
                       auth.make_session_cookie(SECRET, "jsmith"))
    client.post("/cards/close", data={"slug": entry.slug}, follow_redirects=False)
    assert app.state.cards_pool.get(entry.slug) is not None
    client.cookies.set(auth.COOKIE_NAME,
                       auth.make_session_cookie(SECRET, "owen"))
    client.post("/cards/close", data={"slug": entry.slug}, follow_redirects=False)
    assert app.state.cards_pool.get(entry.slug) is None


def test_the_cap_refusal_reaches_the_page(landing, monkeypatch):
    client, app, roots = landing
    app.state.cards_pool.cap = 1
    open_episode(app, roots[0])
    slug = cards_pool.slug_for(str(roots[1]))
    resp = client.post("/cards/open", data={"slug": slug},
                       follow_redirects=False)
    assert "refused=" in resp.headers["location"]
    page = client.get(resp.headers["location"])
    assert "already open" in page.text


# ----------------------------------------------------------- /api/root gone

def test_the_root_switch_is_blocked_inside_the_page(tmp_path, fake_src, monkeypatch):
    """A live route in the drawer. With one engine it WAS the feature; with
    an engine per episode it moves engine A onto root B -- which may already
    have an engine of its own."""
    monkeypatch.delenv("CARDS_SRC", raising=False)
    vault, roots, _ = make_vault(tmp_path)
    app = create_app(make_settings(
        tmp_path, cards_enabled=True, cards_src=fake_src,
        cards_vault_root=str(vault)))
    entry = open_episode(app, roots[0])
    with TestClient(app) as client:
        client.cookies.set(auth.COOKIE_NAME,
                           auth.make_session_cookie(SECRET, "owen"))
        for path in (f"/cards/p/{entry.slug}/api/root",
                     f"/cards/p/{entry.slug}/api/root/"):
            resp = client.post(path, json={"root": "X:/elsewhere"})
            assert resp.status_code == 200
            assert "one engine per episode" in resp.json()["error"]
        assert entry.engine.posts == []              # never reached the handler


# --------------------------------------------------------------- the phone

def test_the_flat_service_worker_is_a_kill_switch(landing):
    """Its scope is `/cards/`, which covers every `/cards/p/<slug>/` URL, and
    every navigation in scope goes through the old worker's own shellAnswer:
    a phone whose network verdict is "down" would be served the OLD page over
    the new project URL."""
    client, _, _ = landing
    resp = client.get("/cards/sw.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]
    assert "unregister()" in resp.text
    assert "addEventListener('fetch'" not in resp.text


def test_the_three_pwa_surfaces_are_open_under_the_episode_prefix(landing):
    """CR-100 and its 2026-09-04 sibling, one prefix deeper. A manifest is
    fetched WITHOUT the session cookie: behind the gate Chrome gets a 303 to
    /login, calls the page not installable, and the worker's periodic update
    fetch installs the login page as its own script."""
    client, app, roots = landing
    entry = open_episode(app, roots[0])
    client.cookies.clear()
    for name in ("sw.js", "manifest.webmanifest", "icon.svg"):
        resp = client.get(f"/cards/p/{entry.slug}/{name}",
                          follow_redirects=False)
        assert resp.status_code != 303, name
        assert "login" not in str(resp.headers.get("location", "")), name


def test_the_flat_manifest_and_icon_stay_open_for_an_older_install(landing):
    client, _, _ = landing
    client.cookies.clear()
    manifest = client.get("/cards/manifest.webmanifest", follow_redirects=False)
    assert manifest.status_code == 200
    assert manifest.json()["start_url"] == "/cards/"
    assert client.get("/cards/icon.svg", follow_redirects=False).status_code == 200


def test_the_open_pattern_never_widens_past_those_three():
    """The pattern is the thing that could quietly open the whole page."""
    from ccsync_dashboard.app import _open_path

    assert _open_path("/cards/p/civil-defence-1234abcd/sw.js") is True
    assert _open_path("/cards/p/civil-defence-1234abcd/api/state") is False
    assert _open_path("/cards/p/civil-defence-1234abcd/") is False
    assert _open_path("/cards/p/../sw.js") is False


def test_reopening_an_episode_serves_the_NEW_engine(landing):
    """A gate cached by slug alone would go on serving the engine that was
    closed -- stopped threads, its own idea of the cut -- for the life of the
    container, and the slug is deliberately stable across a close."""
    client, app, roots = landing
    first = open_episode(app, roots[0])
    assert client.get(f"/cards/p/{first.slug}/api/state").status_code == 200
    app.state.cards_pool.drop(first.slug)
    second = open_episode(app, roots[0])
    assert second.slug == first.slug and second.engine is not first.engine
    second.engine.audio_path = ""
    assert client.post(f"/cards/p/{second.slug}/api/plan",
                       json={"rev": 1}).status_code == 200
    assert second.engine.posts and first.engine is None


def test_an_episode_closed_while_it_was_opening_is_stopped_not_leaked():
    """The builder thread holds a half-built episode; `drop` takes the entry
    out from under it. Published anyway, that is an engine with running
    threads and nothing holding a reference to it -- the shape
    dash-release-jobs-1 cost us once already, one layer down."""
    import threading

    go = threading.Event()
    built = []

    def build(root):
        go.wait(5.0)
        engine = FakeEngine(root)
        built.append(engine)
        return engine, object()

    pool = cards_pool.EnginePool(build, cap=2)
    entry, _ = pool.open("X:/Vault/FF5/Civil Defence")
    assert pool.drop(entry.slug).startswith("closed")
    go.set()
    end = time.monotonic() + 5.0
    while not built and time.monotonic() < end:
        time.sleep(0.005)
    while built[0].stopped is False and time.monotonic() < end:
        time.sleep(0.005)
    assert built[0].stopped is True
    assert pool.entries() == []
