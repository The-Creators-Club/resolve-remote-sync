"""The detail API's insert_share/insert_rel_path -- what "Send to Resolve"
references.

Found 2026-08-12 on the base rig: the DB keys clips by INGEST share (ff3,
ff4, ...), v1 sent that identity to the companion verbatim, and a machine
with a hand-written mount for that share inserted the clip's PRE-archive
copy (share ff3 -> an out-of-tree drive, straight into the out-of-tree fixer
popup); every other machine got "no mount configured". An archived clip must
insert its ARCHIVE top-slot file under the "broll" share, which every
companion derives from local_root and can fetch from the NAS on demand.
"""

from __future__ import annotations

from pathlib import Path

from tests.factories import insert_video

APP_JS = Path(__file__).resolve().parents[1] / "static" / "app.js"


def _detail_video(client, video_id):
    r = client.get(f"/api/videos/{video_id}")
    assert r.status_code == 200
    return r.json()["video"]


def test_archived_clip_inserts_the_top_slot_file(client, conn, data_root):
    """The preview's sibling above Proxy/ -- the best media -- with its own
    extension, which routinely differs from the preview's .mp4 (Creators_Club
    top slots are the shoot's .mov editor proxies)."""
    shoot_dir = data_root / "Creators_Club" / "ff3" / "Day 1" / "A7s3"
    (shoot_dir / "Proxy").mkdir(parents=True)
    (shoot_dir / "road4819.mov").write_bytes(b"top slot")
    (shoot_dir / "Proxy" / "road4819.mp4").write_bytes(b"preview")

    vid = insert_video(
        conn, share="ff3", rel_path="Traffic/B-roll/Proxy/road4819.mov",
        archive_path="Creators_Club/ff3/Day 1/A7s3/Proxy/road4819.mp4",
    )

    video = _detail_video(client, vid)
    assert video["insert_share"] == "broll"
    assert video["insert_rel_path"] == "Creators_Club/ff3/Day 1/A7s3/road4819.mov"
    # The ingest identity is still there untouched for everything else.
    assert video["share"] == "ff3"


def test_a_stem_diverged_clip_falls_back_to_the_preview(client, conn, data_root):
    """Archive task #23's shape: no sibling shares the preview's stem. The
    preview itself is still in the archive on every machine -- degraded
    beats a share nobody can mount."""
    shoot_dir = data_root / "Downloads" / "energy" / "nuclear"
    (shoot_dir / "Proxy").mkdir(parents=True)
    (shoot_dir / "other_name.mp4").write_bytes(b"diverged")
    (shoot_dir / "Proxy" / "clip.mp4").write_bytes(b"preview")

    vid = insert_video(
        conn, share="ff2-e1-yt", rel_path="stuff/clip.mp4",
        archive_path="Downloads/energy/nuclear/Proxy/clip.mp4",
    )

    video = _detail_video(client, vid)
    assert video["insert_share"] == "broll"
    assert video["insert_rel_path"] == "Downloads/energy/nuclear/Proxy/clip.mp4"


def test_an_ambiguous_top_slot_also_falls_back(client, conn, data_root):
    """Two same-stem siblings (a .mov and a .mp4): guessing between them is
    exactly the mispairing dedupe exists to avoid."""
    shoot_dir = data_root / "Creators_Club" / "ff4" / "Day 2"
    (shoot_dir / "Proxy").mkdir(parents=True)
    (shoot_dir / "clip.mov").write_bytes(b"one")
    (shoot_dir / "clip.braw").write_bytes(b"two")
    (shoot_dir / "Proxy" / "clip.mp4").write_bytes(b"preview")

    vid = insert_video(
        conn, share="ff4", rel_path="x/Proxy/clip.mov",
        archive_path="Creators_Club/ff4/Day 2/Proxy/clip.mp4",
    )

    assert _detail_video(client, vid)["insert_rel_path"] == (
        "Creators_Club/ff4/Day 2/Proxy/clip.mp4")


def test_an_unarchived_clip_keeps_its_ingest_identity(client, conn):
    """Clips indexed but not yet placed by build_archive: exactly the old
    behaviour, nothing to point at in the archive yet."""
    vid = insert_video(conn, share="ff4", rel_path="Day 3/clip.mp4",
                       archive_path=None)

    video = _detail_video(client, vid)
    assert video["insert_share"] == "ff4"
    assert video["insert_rel_path"] == "Day 3/clip.mp4"


def test_a_missing_archive_directory_still_answers(client, conn):
    """archive_path rows whose tree hasn't landed on this DATA_ROOT (bare dev
    checkout): the detail view must not 500, and the preview fallback is the
    only defensible answer."""
    vid = insert_video(
        conn, share="ff3", rel_path="a/b.mov",
        archive_path="Creators_Club/ff3/Nowhere/Proxy/b.mp4",
    )

    video = _detail_video(client, vid)
    assert video["insert_share"] == "broll"
    assert video["insert_rel_path"] == "Creators_Club/ff3/Nowhere/Proxy/b.mp4"


# ---------------------------------------------------------------------------
# the `insert` object (docs/BROLL_PROXY_TIERS_PLAN.md section 5, 2026-09-17)
# ---------------------------------------------------------------------------
#
# The companion never fetches this route (audit F2): the PAGE forwards this
# object in the POST body it already sends, and a companion that does not
# understand it derives the proxy paths from the stem convention instead. So
# every field here is read by something that may be older or newer than the
# dashboard, and "absent" has to mean the same thing in both directions.


def _archived(conn, data_root, *, stem="clip", top_ext=".mov",
              edit_proxy=False, share="ff5", **row):
    shoot_dir = data_root / "Creators_Club" / share / "Day 1"
    (shoot_dir / "Proxy").mkdir(parents=True, exist_ok=True)
    if top_ext:
        (shoot_dir / f"{stem}{top_ext}").write_bytes(b"top slot")
    (shoot_dir / "Proxy" / f"{stem}.mp4").write_bytes(b"preview")
    if edit_proxy:
        (shoot_dir / "Proxy" / f"{stem}.mov").write_bytes(b"editing proxy")
    return insert_video(
        conn, share=share, rel_path=f"x/{stem}{top_ext or '.mp4'}",
        archive_path=f"Creators_Club/{share}/Day 1/Proxy/{stem}.mp4", **row)


def test_an_edit_weight_original_says_so(client, conn, data_root):
    """1080p H.264 at 7 Mbps IS its own editing proxy: downloading it is
    correct and a second file would waste the space twice. That is most of
    Creators_Club, whose top slots are the shoot's own editor proxies."""
    vid = _archived(conn, data_root, stem="light", height=1080, width=1920,
                    codec="h264", bitrate=7_000_000, frames=1674,
                    start_tc="12:05:55:26", fps=29.97)

    insert = _detail_video(client, vid)["insert"]

    assert insert["share"] == "broll"
    assert insert["original_rel"] == "Creators_Club/ff5/Day 1/light.mov"
    assert insert["preview_rel"] == "Creators_Club/ff5/Day 1/Proxy/light.mp4"
    assert insert["edit_proxy_rel"] is None
    assert insert["original_is_edit_weight"] is True
    assert insert["geometry"] == {"width": 1920, "height": 1080, "fps": 29.97,
                                  "frames": 1674, "start_tc": "12:05:55:26"}


def test_a_heavy_original_without_an_editing_proxy(client, conn, data_root):
    """A 6K ProRes camera master (the Johnny Harris shape, up to ~10 GB): not
    edit-weight, and nothing beside it yet. Phase 3 inserts the preview and
    has nothing to upgrade to."""
    vid = _archived(conn, data_root, stem="heavy", width=6064, height=3424,
                    codec="prores", bitrate=1_200_000_000)

    insert = _detail_video(client, vid)["insert"]

    assert insert["original_is_edit_weight"] is False
    assert insert["edit_proxy_rel"] is None
    assert insert["original_rel"] == "Creators_Club/ff5/Day 1/heavy.mov"


def test_a_heavy_original_with_an_editing_proxy_beside_it(client, conn, data_root):
    """`Proxy/<stem>.mov` next to `Proxy/<stem>.mp4`. Found by stem at request
    time, like the top slot: nothing records it, and one that arrives later
    has to show up without a re-index."""
    vid = _archived(conn, data_root, stem="both", top_ext=".braw",
                    edit_proxy=True, codec="hevc", height=2160,
                    bitrate=90_000_000)

    insert = _detail_video(client, vid)["insert"]

    assert insert["edit_proxy_rel"] == "Creators_Club/ff5/Day 1/Proxy/both.mov"
    assert insert["preview_rel"] == "Creators_Club/ff5/Day 1/Proxy/both.mp4"
    assert insert["original_rel"] == "Creators_Club/ff5/Day 1/both.braw"
    assert insert["original_is_edit_weight"] is False


def test_a_row_indexed_before_the_bitrate_column_answers_null(client, conn, data_root):
    """NULL bitrate is "cannot tell", and it must not collapse to False or
    True. Every one of the 7,255 rows indexed before migration 012 is this
    case, and a 0 read as "tiny" would send a remote editor a camera master."""
    vid = _archived(conn, data_root, stem="legacy", bitrate=None)

    insert = _detail_video(client, vid)["insert"]

    assert insert["original_is_edit_weight"] is None
    assert insert["geometry"]["frames"] is None
    assert insert["geometry"]["start_tc"] is None


def test_the_preview_only_fallback_reports_no_original(client, conn, data_root):
    """Archive task #23's stem-diverged clips: the preview itself is what gets
    inserted, and the object says so with a null `original_rel` rather than
    naming the preview twice. A reader must not mistake the fallback for a
    clip whose original happens to be the preview."""
    vid = _archived(conn, data_root, stem="alone", top_ext="",
                    bitrate=2_000_000)

    insert = _detail_video(client, vid)["insert"]
    video = _detail_video(client, vid)

    assert insert["original_rel"] is None
    assert insert["preview_rel"] == "Creators_Club/ff5/Day 1/Proxy/alone.mp4"
    # ...and the fields the page has always POSTed are unchanged.
    assert video["insert_rel_path"] == "Creators_Club/ff5/Day 1/Proxy/alone.mp4"


def test_an_unarchived_clip_still_gets_an_insert_object(client, conn):
    """The ingest identity, and no archive geometry to describe. The object is
    additive everywhere or it is a second contract."""
    vid = insert_video(conn, share="ff4", rel_path="Day 3/clip.mp4",
                       archive_path=None, bitrate=2_000_000)

    insert = _detail_video(client, vid)["insert"]

    assert insert["share"] == "ff4"
    assert insert["original_rel"] == "Day 3/clip.mp4"
    assert insert["preview_rel"] is None
    assert insert["edit_proxy_rel"] is None


def test_the_page_forwards_the_insert_object_to_the_companion():
    """The companion never fetches this API (audit F2), so the page's POST
    body is the ONLY way the object reaches it. `|| undefined` rather than
    `|| null`: JSON.stringify drops an undefined key entirely, and a companion
    that has never seen the field must receive exactly the body it always
    did."""
    source = APP_JS.read_text(encoding="utf-8")

    assert "insert: video.insert || undefined," in source


def test_a_missing_archive_directory_answers_without_a_proxy(client, conn):
    """A bare dev checkout, or a tree that has not landed on this DATA_ROOT.
    The detail view must not 500 and must not claim files it cannot see."""
    vid = insert_video(
        conn, share="ff3", rel_path="a/b.mov", bitrate=3_000_000,
        archive_path="Creators_Club/ff3/Nowhere/Proxy/b.mp4",
    )

    insert = _detail_video(client, vid)["insert"]

    assert insert["original_rel"] is None
    assert insert["edit_proxy_rel"] is None
    assert insert["preview_rel"] == "Creators_Club/ff3/Nowhere/Proxy/b.mp4"
