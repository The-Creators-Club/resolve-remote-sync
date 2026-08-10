"""The folder tree's two roots: Downloads and Creators_Club.

Split by SHARE, because that is the only signal this app can see -- which side
of a proxy/original pair a share archives lives in the indexer's config, and the
web app does not read that file (it may not even be on the same machine). It
learns it second-hand instead: the deploy-time BROLL_CREATORS_SHARES list, plus
every source='proxies' row the indexer pushes into share_roots.
"""
from __future__ import annotations

import pytest

from app.search import build_collection_clause
from tests.factories import insert_video


@pytest.fixture()
def creators(monkeypatch):
    monkeypatch.setenv("BROLL_CREATORS_SHARES", "mofa-disaster, other-shoot")


def _push_share_root(conn, share, source, root="/mnt/tank/Creators_Club"):
    """What the indexer writes at the end of a run (migration 006)."""
    conn.execute(
        "INSERT INTO share_roots (share, root, source) VALUES (?, ?, ?)",
        (share, root, source),
    )
    conn.commit()


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
    """The creators set became derived from the DB, so the builder takes a
    connection — but it stays optional, because every caller that only wants to
    know "is there a collection filter at all" has no reason to open one."""
    assert build_collection_clause(None) == ("", [])


# --- shares the indexer pushed (share_roots) ----------------------------------

def test_a_pushed_proxies_share_is_our_footage_without_an_env_edit(client, conn, monkeypatch):
    """The FF4 bug (2026-08-10): a freshly indexed shoot share filed itself under
    Downloads and stayed there until someone SSHed to the NAS to add it to an env
    var. source='proxies' already states that the archived original IS our own
    Proxy/*.mov, so the archive has to sort itself the moment the indexer says so.
    """
    monkeypatch.delenv("BROLL_CREATORS_SHARES", raising=False)
    _push_share_root(conn, "ff4-whisky", "proxies")
    insert_video(conn, share="ff4-whisky", rel_path="Whisky/Proxy/a.mov",
                 category=None, status="organised")

    cc = client.get("/api/search", params={"collection": "creators_club"}).json()
    dl = client.get("/api/search", params={"collection": "downloads"}).json()
    assert cc["total"] == 1
    assert dl["total"] == 0, "it must leave Downloads, not appear in both"

    tree = client.get("/api/tree").json()
    creators_root = next(r for r in tree if r["collection"] == "creators_club")
    assert [g["slug"] for g in creators_root["groups"]] == ["ff4-whisky"]


def test_a_pushed_originals_share_stays_a_download(client, conn, monkeypatch):
    """source='originals' is footage we archived as it arrived, i.e. not ours.
    The derivation keys on what the flag MEANS, so a share must not become ours
    merely by being known to the table."""
    monkeypatch.delenv("BROLL_CREATORS_SHARES", raising=False)
    _push_share_root(conn, "pond5", "originals")
    insert_video(conn, share="pond5", rel_path="stock/a.mov", category="energy/nuclear")

    cc = client.get("/api/search", params={"collection": "creators_club"}).json()
    dl = client.get("/api/search", params={"collection": "downloads"}).json()
    assert cc["total"] == 0
    assert dl["total"] == 1


def test_the_env_list_and_the_pushed_shares_are_unioned(client, conn, creators):
    """BROLL_CREATORS_SHARES stays as the deploy-time override rather than being
    replaced: a share is ours because the operator said so, because the indexer
    said so, or both — and losing either signal would silently re-file footage."""
    _push_share_root(conn, "ff4-whisky", "proxies")
    insert_video(conn, share="ff4-whisky", rel_path="Whisky/Proxy/a.mov",
                 category=None, status="organised")
    insert_video(conn, share="mofa-disaster", rel_path="Day 1/Proxy/b.mov",
                 category=None, status="organised")
    insert_video(conn, share="pond5", rel_path="stock/c.mov", category=None)

    cc = client.get("/api/search", params={"collection": "creators_club"}).json()
    dl = client.get("/api/search", params={"collection": "downloads"}).json()
    assert {r["video"]["share"] for r in cc["results"]} == {"ff4-whisky", "mofa-disaster"}
    assert {r["video"]["share"] for r in dl["results"]} == {"pond5"}


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

    day = shoot["children"][0]
    assert (day["slug"], day["label"]) == ("mofa-disaster::Day 1", "Day 1")
    assert day["count"] == 5, "a folder's count is everything beneath it, not its own files"
    assert [(c["slug"], c["label"], c["count"]) for c in day["children"]] == [
        ("mofa-disaster::Day 1 / A74", "A74", 3),
        ("mofa-disaster::Day 1 / Fx3", "Fx3", 2),
    ]


def test_the_proxy_component_is_folded_out_of_the_label(client, conn, creators):
    """On a source="proxies" share every clip sits in a Proxy/ dir, so the
    component carries no information and would add a level of noise to every
    branch."""
    insert_video(conn, share="mofa-disaster", rel_path="Day 2/Fx3/Proxy/a.mov",
                 category=None, status="organised")
    tree = client.get("/api/tree").json()
    cc = next(r for r in tree if r["collection"] == "creators_club")

    day = cc["groups"][0]["children"][0]
    assert (day["slug"], day["label"]) == ("mofa-disaster::Day 2", "Day 2")
    cam = day["children"][0]
    assert (cam["slug"], cam["label"]) == ("mofa-disaster::Day 2 / Fx3", "Fx3")
    assert cam["children"] == [], "Proxy must not survive as a level of its own"


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


def test_the_shoot_tree_mirrors_the_real_folders_all_the_way_down(client, conn, creators):
    """`Whisky/Interviews/黃培峻 Huang Pei-jun` is a real branch of the FF4 share,
    and an editor asks for that interview by the person's name. A day/camera list
    one level deep cannot offer it — the sidebar has to be the folder tree."""
    insert_video(conn, share="mofa-disaster",
                 rel_path="Whisky/Interviews/黃培峻 Huang Pei-jun/Proxy/a.mov",
                 category=None, status="organised")

    tree = client.get("/api/tree").json()
    cc = next(r for r in tree if r["collection"] == "creators_club")

    whisky = cc["groups"][0]["children"][0]
    assert (whisky["slug"], whisky["label"]) == ("mofa-disaster::Whisky", "Whisky")
    interviews = whisky["children"][0]
    assert (interviews["slug"], interviews["label"]) == (
        "mofa-disaster::Whisky / Interviews", "Interviews")
    person = interviews["children"][0]
    assert person["slug"] == "mofa-disaster::Whisky / Interviews / 黃培峻 Huang Pei-jun"
    assert person["label"] == "黃培峻 Huang Pei-jun"
    assert person["count"] == 1


def test_folders_below_the_depth_cap_fold_into_their_parent(client, conn, creators):
    """Past three levels a shoot's folders are camera-roll bookkeeping
    (CARD1/CLIP0001), which would shatter one interview across a dozen branches.
    Those clips are not dropped, they count towards the folder an editor clicks."""
    insert_video(conn, share="mofa-disaster",
                 rel_path="Whisky/Interviews/黃培峻 Huang Pei-jun/Proxy/a.mov",
                 category=None, status="organised")
    insert_video(conn, share="mofa-disaster",
                 rel_path="Whisky/Interviews/黃培峻 Huang Pei-jun/CARD1/Proxy/b.mov",
                 category=None, status="organised")

    tree = client.get("/api/tree").json()
    cc = next(r for r in tree if r["collection"] == "creators_club")
    person = cc["groups"][0]["children"][0]["children"][0]["children"][0]

    assert person["label"] == "黃培峻 Huang Pei-jun"
    assert person["count"] == 2, "the deeper clip still lives here"
    assert person["children"] == []


def test_clicking_a_nested_folder_returns_only_what_is_under_it(client, conn, creators):
    """Every node's slug is the exact string the shoot filter parses, at any
    depth — a branch an editor can see but not select is worse than no branch."""
    insert_video(conn, share="mofa-disaster",
                 rel_path="Whisky/Interviews/黃培峻 Huang Pei-jun/Proxy/a.mov",
                 category=None, status="organised")
    insert_video(conn, share="mofa-disaster", rel_path="Whisky/Distillery/Proxy/b.mov",
                 category=None, status="organised")
    insert_video(conn, share="mofa-disaster", rel_path="Day 1/A74/Proxy/c.mov",
                 category=None, status="organised")

    body = client.get("/api/search", params={
        "shoot": "mofa-disaster::Whisky / Interviews"}).json()
    assert body["total"] == 1
    assert body["results"][0]["video"]["rel_path"] == (
        "Whisky/Interviews/黃培峻 Huang Pei-jun/Proxy/a.mov")


def test_browsing_hides_the_camera_originals_of_a_proxies_share(client, conn, monkeypatch):
    """The FF4 shoot's camera .MP4s are recorded as 'excluded' — kept for the
    conform manifest, never indexed, never copied, so they have no proxy, poster
    or sprite. Browsing them produced a wall of ghost "no preview" cards beside
    the very proxies they belong to, and a total that overstated the library
    (2026-08-10)."""
    monkeypatch.delenv("BROLL_CREATORS_SHARES", raising=False)
    _push_share_root(conn, "ff4-whisky", "proxies")
    insert_video(conn, share="ff4-whisky", rel_path="Whisky/Proxy/a.mov",
                 category=None, status="indexed")
    insert_video(conn, share="ff4-whisky", rel_path="Whisky/a.MP4",
                 category=None, status="excluded")

    body = client.get("/api/search").json()
    assert [r["video"]["rel_path"] for r in body["results"]] == ["Whisky/Proxy/a.mov"]
    assert body["total"] == 1, "the count must not include what the grid refuses to show"
