"""The folder tree's two roots: Downloads and Creators_Club.

Split by SHARE, because that is the only signal this app can see -- which side
of a proxy/original pair a share archives lives in the indexer's config, and the
web app does not read that file (it may not even be on the same machine).
"""
from __future__ import annotations

import pytest

from app.search import build_collection_clause
from tests.factories import insert_video


@pytest.fixture()
def creators(monkeypatch):
    monkeypatch.setenv("BROLL_CREATORS_SHARES", "mofa-disaster, other-shoot")


def _seed_both(conn):
    insert_video(conn, share="ff4-nuclear", rel_path="dl1.mov", category="energy/nuclear")
    insert_video(conn, share="ff4-nuclear", rel_path="dl2.mov", category="energy/nuclear")
    insert_video(conn, share="mofa-disaster", rel_path="own1.mov", category="security/emergency-disaster")


def test_creators_club_selects_only_configured_shares(client, conn, creators):
    _seed_both(conn)
    body = client.get("/api/search", params={"collection": "creators_club"}).json()
    assert body["total"] == 1
    assert body["results"][0]["video"]["share"] == "mofa-disaster"


def test_downloads_is_the_complement(client, conn, creators):
    _seed_both(conn)
    body = client.get("/api/search", params={"collection": "downloads"}).json()
    assert body["total"] == 2
    assert {r["video"]["share"] for r in body["results"]} == {"ff4-nuclear"}


def test_an_unlisted_share_is_a_download_not_invisible(client, conn, creators):
    """Expressed as NOT IN rather than an enumerated list on purpose: a share
    added to the archive but not yet to the config must still appear somewhere,
    rather than vanishing from both roots."""
    _seed_both(conn)
    insert_video(conn, share="brand-new-share", rel_path="x.mov", category="energy/nuclear")

    dl = client.get("/api/search", params={"collection": "downloads"}).json()
    cc = client.get("/api/search", params={"collection": "creators_club"}).json()

    assert dl["total"] + cc["total"] == 4, "every video is in exactly one root"
    assert "brand-new-share" in {r["video"]["share"] for r in dl["results"]}


def test_unconfigured_puts_everything_under_downloads(client, conn, monkeypatch):
    monkeypatch.delenv("BROLL_CREATORS_SHARES", raising=False)
    _seed_both(conn)
    assert client.get("/api/search", params={"collection": "downloads"}).json()["total"] == 3
    assert client.get("/api/search", params={"collection": "creators_club"}).json()["total"] == 0


def test_no_collection_returns_everything(client, conn, creators):
    _seed_both(conn)
    assert client.get("/api/search").json()["total"] == 3


def test_collection_composes_with_category(client, conn, creators):
    _seed_both(conn)
    body = client.get("/api/search", params={
        "collection": "downloads", "category": "energy"}).json()
    assert body["total"] == 2
    body = client.get("/api/search", params={
        "collection": "creators_club", "category": "energy"}).json()
    assert body["total"] == 0, "the two filters must AND, not OR"


def test_collection_composes_with_a_text_query(client, conn, creators):
    from tests.factories import insert_segment
    _seed_both(conn)
    vid = insert_video(conn, share="mofa-disaster", rel_path="own2.mov")
    insert_segment(conn, vid, description="firefighters running a drill", objects="hose")
    other = insert_video(conn, share="ff4-nuclear", rel_path="dl3.mov")
    insert_segment(conn, other, description="firefighters at a reactor", objects="hose")

    body = client.get("/api/search", params={
        "q": "firefighters", "collection": "creators_club"}).json()
    assert {r["video"]["rel_path"] for r in body["results"]} == {"own2.mov"}


def test_an_unknown_collection_value_is_ignored(client, conn, creators):
    """Same posture as `mode` and `sources`: fall back rather than error."""
    _seed_both(conn)
    assert client.get("/api/search", params={"collection": "nonsense"}).json()["total"] == 3


def test_the_clause_builder_emits_nothing_for_no_collection():
    assert build_collection_clause(None) == ("", [])


# --- the tree endpoint --------------------------------------------------------

def test_tree_groups_leaves_under_their_top_level(client, conn, creators):
    _seed_both(conn)
    tree = client.get("/api/tree").json()
    downloads = next(r for r in tree if r["collection"] == "downloads")

    assert downloads["label"] == "Downloads"
    assert downloads["total"] == 2
    energy = next(g for g in downloads["groups"] if g["slug"] == "energy")
    assert energy["count"] == 2
    assert energy["children"][0]["slug"] == "energy/nuclear"


def test_tree_counts_match_what_clicking_the_folder_returns(client, conn, creators):
    """A folder that promises 218 and delivers 190 is worse than no count."""
    _seed_both(conn)
    insert_video(conn, share="ff4-nuclear", rel_path="Proxy/skip.mov",
                 category="energy/nuclear", status="skipped")

    tree = client.get("/api/tree").json()
    downloads = next(r for r in tree if r["collection"] == "downloads")
    leaf = next(c for g in downloads["groups"] for c in g["children"]
                if c["slug"] == "energy/nuclear")

    searched = client.get("/api/search", params={
        "collection": "downloads", "category": "energy/nuclear"}).json()
    assert leaf["count"] == searched["total"]


def test_tree_omits_a_root_with_nothing_in_it(client, conn, monkeypatch):
    monkeypatch.delenv("BROLL_CREATORS_SHARES", raising=False)
    _seed_both(conn)
    tree = client.get("/api/tree").json()
    creators_root = next(r for r in tree if r["collection"] == "creators_club")
    assert creators_root["total"] == 0
    assert creators_root["groups"] == []


# --- clips with no subject at all ---------------------------------------------

def test_uncategorised_is_selectable(client, conn, creators):
    """163 videos describe only format, place and look ("news broadcast",
    "daytime", "interior") with no subject to file them under. Inventing one
    would be worse than admitting it — but without this they would be findable
    by search and invisible to browsing."""
    from app.search import UNCATEGORISED
    _seed_both(conn)
    insert_video(conn, share="ff4-nuclear", rel_path="nosubject.mov", category=None)

    body = client.get("/api/search", params={"category": UNCATEGORISED}).json()
    assert body["total"] == 1
    assert body["results"][0]["video"]["rel_path"] == "nosubject.mov"


def test_uncategorised_appears_last_in_the_tree(client, conn, creators):
    """It is a leftover pile, not a subject: ranking it by count would float it
    above real folders."""
    from app.search import UNCATEGORISED
    _seed_both(conn)
    for i in range(9):
        insert_video(conn, share="ff4-nuclear", rel_path=f"n{i}.mov", category=None)

    tree = client.get("/api/tree").json()
    downloads = next(r for r in tree if r["collection"] == "downloads")
    assert downloads["groups"][-1]["slug"] == UNCATEGORISED
    assert downloads["groups"][-1]["count"] == 9
    assert downloads["groups"][-1]["children"] == []


def test_a_real_category_is_unaffected_by_the_sentinel(client, conn, creators):
    _seed_both(conn)
    body = client.get("/api/search", params={"category": "energy/nuclear"}).json()
    assert body["total"] == 2


def test_uncategorised_excludes_clips_that_are_merely_not_indexed_yet(client, conn, creators):
    """The bug this guards: `category IS NULL` also matches every clip not yet
    through the indexer, because none of those has a category either. On the
    real archive that put 1,414 videos behind a folder labelled 163.

    "No subject was found in this clip" and "this clip has not been described
    yet" are different facts and must not share a folder.
    """
    from app.search import UNCATEGORISED
    insert_video(conn, share="s", rel_path="described.mov", category=None, status="indexed")
    for st in ("proxied", "discovered", "excluded", "error"):
        insert_video(conn, share="s", rel_path=f"{st}.mov", category=None, status=st)

    tree = client.get("/api/tree").json()
    downloads = next(r for r in tree if r["collection"] == "downloads")
    bucket = next(g for g in downloads["groups"] if g["slug"] == UNCATEGORISED)
    searched = client.get("/api/search", params={"category": UNCATEGORISED}).json()

    assert bucket["count"] == 1
    assert searched["total"] == 1, "a folder must deliver exactly what it promises"
    assert searched["results"][0]["video"]["rel_path"] == "described.mov"


# --- Creators_Club: organised by shoot, not subject ---------------------------

def test_creators_tree_is_built_from_paths_not_categories(client, conn, creators):
    """Own footage is deliberately not model-indexed (ShareConfig index: false),
    so it has no subject to browse by. The shoot's own folder tree — event, day,
    camera — already records how an editor looks for it, and reading it from
    rel_path is free and instant."""
    for cam, n in (("A74", 3), ("Fx3", 2)):
        for i in range(n):
            insert_video(conn, share="mofa-disaster",
                         rel_path=f"Day 1/{cam}/Proxy/clip{i}.mov",
                         category=None, status="organised")

    tree = client.get("/api/tree").json()
    cc = next(r for r in tree if r["collection"] == "creators_club")

    assert cc["total"] == 5
    shoot = cc["groups"][0]
    assert shoot["slug"] == "mofa-disaster"
    assert [c["label"] for c in shoot["children"]] == ["Day 1 / A74", "Day 1 / Fx3"]
    assert [c["count"] for c in shoot["children"]] == [3, 2]


def test_the_proxy_component_is_folded_out_of_the_label(client, conn, creators):
    """On a source="proxies" share every clip sits in a Proxy/ dir, so the
    component carries no information and would add a level of noise to every
    branch."""
    insert_video(conn, share="mofa-disaster", rel_path="Day 2/Fx3/Proxy/a.mov",
                 category=None, status="organised")
    tree = client.get("/api/tree").json()
    cc = next(r for r in tree if r["collection"] == "creators_club")
    assert cc["groups"][0]["children"][0]["label"] == "Day 2 / Fx3"


def test_clicking_a_shoot_folder_returns_its_clips(client, conn, creators):
    insert_video(conn, share="mofa-disaster", rel_path="Day 1/A74/Proxy/a.mov",
                 category=None, status="organised")
    insert_video(conn, share="mofa-disaster", rel_path="Day 1/Fx3/Proxy/b.mov",
                 category=None, status="organised")

    body = client.get("/api/search", params={"shoot": "mofa-disaster::Day 1 / A74"}).json()
    assert body["total"] == 1
    assert body["results"][0]["video"]["rel_path"] == "Day 1/A74/Proxy/a.mov"


def test_the_whole_shoot_is_selectable(client, conn, creators):
    insert_video(conn, share="mofa-disaster", rel_path="Day 1/A74/Proxy/a.mov",
                 category=None, status="organised")
    insert_video(conn, share="mofa-disaster", rel_path="Day 2/Fx3/Proxy/b.mov",
                 category=None, status="organised")
    assert client.get("/api/search", params={"shoot": "mofa-disaster"}).json()["total"] == 2


def test_shoot_tree_never_shows_the_excluded_camera_originals(client, conn, creators):
    """403 GB of camera originals are recorded as 'excluded' so they are neither
    indexed nor copied — they must not appear as browsable folders either."""
    insert_video(conn, share="mofa-disaster", rel_path="Day 1/A74/Proxy/a.mov",
                 category=None, status="organised")
    insert_video(conn, share="mofa-disaster", rel_path="Day 1/A74/a.MP4",
                 category=None, status="excluded")

    tree = client.get("/api/tree").json()
    cc = next(r for r in tree if r["collection"] == "creators_club")
    assert cc["total"] == 1
