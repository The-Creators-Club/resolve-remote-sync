"""The detail API's insert_share/insert_rel_path -- what "Send to Resolve"
references.

Found 2026-08-12 on the base rig: the DB keys clips by INGEST share (ff3,
ff4, ...), v1 sent that identity to the companion verbatim, and a machine
with a hand-written mount for that share inserted the clip's PRE-archive
copy (share ff3 -> Z:\\Cablewrap\\..., straight into the out-of-tree fixer
popup); every other machine got "no mount configured". An archived clip must
insert its ARCHIVE top-slot file under the "broll" share, which every
companion derives from local_root and can fetch from the NAS on demand.
"""

from __future__ import annotations

from tests.factories import insert_video


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
