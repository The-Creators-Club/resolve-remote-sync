"""Regression tests for the 2026-09-18b fix pass, companion-media group (CR-288).

Every test here fails on the tree as it stood after the morning's pass
(CR-282/CR-284) and passes after CR-288. One test per finding, named after
what the defect DID. Nothing here talks to Resolve, the NAS, the network or a
Tk dialog: the insert's `fetcher`/`caller` seams and the ledger's own path
are the only things injected.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from ccsync_companion import broll_fetch
from ccsync_companion import broll_server
from ccsync_companion import broll_standins
from ccsync_companion import proxy_relink


@pytest.fixture(autouse=True)
def _own_ledger(tmp_path):
    broll_standins.configure(tmp_path / "state" / "broll_standins.json")
    broll_server.reset_upgrades_in_flight()
    proxy_relink.reset_geometry_verdicts()
    proxy_relink.reset_refusals()
    yield
    proxy_relink.reset_geometry_verdicts()
    proxy_relink.reset_refusals()


# ---------------------------------------------------------------------------
# CR-288A (comp-resolve-1 = regression-1): one key for the geometry verdict
# ---------------------------------------------------------------------------

def test_the_geometry_verdict_is_written_where_the_next_pass_reads_it(tmp_path):
    """The verdict was keyed on the spelling the PROBE could open and written
    back under the clip's linked (canonical) spelling. Wherever the two
    differ -- every macOS editor, every companion whose process has no P:
    mapping -- the memory never hit, so the same refresh was re-planned every
    120 s, each pass spending one of the eight allow_automatic grants a day
    until genuine proxy relinks were rate-limited out for the rest of it."""
    local_root = str(tmp_path / "tree")
    canonical = "P:\\"
    canonical_path = "P:\\Assets\\B-roll Archive\\CIA_City\\cam-1-001.mov"
    twin = str(Path(local_root) / "Assets" / "B-roll Archive" / "CIA_City"
               / "cam-1-001.mov")
    counted: list[str] = []

    def exists(path):
        return str(path) == twin

    def stat(path):
        if str(path) != twin:
            raise OSError("this process has no P:")
        return type("S", (), {"st_mtime": 1.0, "st_size": 10})()

    def count_frames(path):
        counted.append(str(path))
        return 900  # the file is the stand-in's length; the clip believes 1000

    item = {"file_path": canonical_path, "clip_name": "cam-1-001",
            "media_pool_uid": "u1", "media_pool_item": object(),
            "proxy_path": "", "proxy_state": "None", "frames": 1000}

    def plan():
        return proxy_relink.plan_relinks(
            [dict(item)], local_root, canonical,
            exists_fn=exists, stat_fn=stat, is_windows=True,
            is_standin_fn=lambda p: False,
            frames_fn=proxy_relink.stored_frames,
            count_frames_fn=count_frames)

    ops = plan()
    assert len(ops) == 1 and ops[0]["refresh"] is True

    # The forced ReplaceClip Resolve took: the verdict CR-284R exists to
    # remember.
    proxy_relink.apply_relinks(
        ops, link_fn=lambda i, p: {"ok": True}, stat_fn=stat,
        resolve_fn=lambda o: o["media_pool_item"],
        replace_fn=lambda i, p, force=False: {"ok": True, "changed": True})

    assert plan() == [], ("the verdict must be readable on the next pass on "
                          "the machine that wrote it")
    assert len(counted) == 1, "the whole-file demux must not run twice"


# ---------------------------------------------------------------------------
# CR-288B (proxy-tiers-1): an intent row that can be falsified
# ---------------------------------------------------------------------------

def _editor_cfg(tmp_path):
    return {"local_root": str(tmp_path), "mode": "editor",
            "canonical_prefix": "P:\\", "remote": "creators_club_sftp",
            "remote_root": "/mnt/tank/creators_club", "rclone_path": "rclone"}


def _body(rel="cc/ff5/clip.mov"):
    return {"share": "broll", "rel_path": rel, "in_frame": 0, "out_frame": 10,
            "mode": "append",
            "insert": {"original_rel": rel,
                       "preview_rel": "cc/ff5/Proxy/clip.mp4",
                       "edit_proxy_rel": "cc/ff5/Proxy/clip.mov",
                       "original_is_edit_weight": False,
                       "geometry": {"width": 6064, "height": 3424,
                                    "fps": 30.0, "frames": 1813}}}


def _archive(tmp_path, *parts):
    return tmp_path.joinpath("Assets", "B-roll Archive", *parts)


def test_a_download_that_never_started_leaves_no_standin_row(tmp_path):
    """At the two-download cap `poll_fetch` starts nothing and registers
    nothing (its own docstring), but the intent row had already been written
    -- and with no size it had no falsifier at all, so the ledger claimed for
    ever that a file no byte was ever fetched for was a stand-in, and the
    real 6K original arriving later could not clear it."""
    cfg = _editor_cfg(tmp_path)
    mounts = broll_server.resolve_mounts({}, cfg)

    status, body = broll_server.build_insert_response(
        _body(), mounts, ccsync_cfg=cfg,
        fetcher=lambda *a, **k: {"state": broll_fetch.STATE_BUSY,
                                 "message": "busy", "retry_after": 1.5},
        caller=lambda *a, **k: {"ok": True, "message": "inserted"})

    assert status == 200 and body.get("state") == "busy"
    assert broll_standins.all() == [], ("nothing was downloaded, so nothing "
                                        "may be remembered as a stand-in")


def test_a_fetch_that_blows_up_leaves_no_standin_row(tmp_path):
    """The same hole through the other door: an exception out of the fetch
    skipped every retirement branch below it."""
    cfg = _editor_cfg(tmp_path)
    mounts = broll_server.resolve_mounts({}, cfg)

    def boom(*a, **k):
        raise RuntimeError("rclone went away")

    with pytest.raises(RuntimeError):
        broll_server.build_insert_response(
            _body(), mounts, ccsync_cfg=cfg, fetcher=boom,
            caller=lambda *a, **k: {"ok": True})
    assert broll_standins.all() == []


ORIGINAL_GEOMETRY = {"width": 6064, "height": 3424, "fps": 30.0,
                     "frames": 1813, "start_tc": "12:09:12:22"}
PREVIEW_HEADER = {"width": 1920, "height": 1080, "fps": 30.0}


def _intent(tmp_path, name="clip.mov", geometry=ORIGINAL_GEOMETRY):
    """The row the insert path writes BEFORE the fetch, and its path."""
    media = _archive(tmp_path, "cc", "ff5", name)
    media.parent.mkdir(parents=True, exist_ok=True)
    broll_standins.record(media, share="broll",
                          rel_path=f"cc/ff5/{name}", geometry=geometry,
                          pending_fetch=True, size=None)
    return media


def test_an_intent_row_whose_stand_in_landed_unobserved_becomes_falsifiable(tmp_path):
    """A download nobody polled again (tab closed, laptop asleep) left a row
    with `size: None`, and `_entry_is_stale` reads a non-int size as "still a
    stand-in" unconditionally -- so the real original arriving at that path
    later could never falsify it."""
    media = _intent(tmp_path)
    assert broll_standins.is_standin(media) is True  # nothing there yet

    media.write_bytes(b"the preview's bytes")  # the download landed, unobserved
    # The header is the preview's, which is not the original's geometry: this
    # IS the stand-in we placed.
    assert broll_standins.settle_intents(
        probe_fn=lambda path: dict(PREVIEW_HEADER)) == 1
    assert broll_standins.is_standin(media) is True  # still the lie we placed
    assert broll_standins.get(media)["size"] == len(b"the preview's bytes")

    media.write_bytes(b"the real 6K original, an entirely different size")
    assert broll_standins.is_standin(media) is False
    assert broll_standins.is_stale(media) is True


def test_the_real_original_arriving_at_a_pending_path_retires_the_row(tmp_path):
    """Settling by PRESENCE would record the real original's own size as the
    stand-in's, and the size then never changes again: `is_standin` would
    answer True for the real 6K file for ever, the preview would be attached
    as its proxy and the rel broadcast to the fleet -- proxy-tiers-1's exact
    outcome, reached through the settlement. A stand-in IS the preview's
    bytes, so the file's own header decides."""
    media = _intent(tmp_path)
    # The fetch failed unobserved; lane B (or the editor) puts the real
    # original there instead.
    media.write_bytes(b"6K ProRes")

    assert broll_standins.settle_intents(
        probe_fn=lambda path: dict(ORIGINAL_GEOMETRY)) == 1
    assert broll_standins.get(media) is None
    assert broll_standins.is_standin(media) is False


def test_a_row_nothing_can_identify_is_left_pending(tmp_path):
    """No geometry on the row and no job record after a restart is "cannot
    tell", and a row that cannot be settled is not guessed at."""
    media = _intent(tmp_path, name="nogeom.mov", geometry=None)
    media.write_bytes(b"something")

    assert broll_standins.settle_intents(
        probe_fn=lambda path: None, job_state_fn=lambda dest: None) == 0
    entry = broll_standins.get(media)
    assert entry["pending_fetch"] is True and entry["size"] is None
    assert broll_standins.is_standin(media) is True

    # A header that cannot be read falls through to the same fallback, and
    # the fetch job's own record is what answers when it is still there.
    assert broll_standins.settle_intents(
        probe_fn=lambda path: None,
        job_state_fn=lambda dest: broll_fetch.STATE_DONE) == 1
    assert broll_standins.get(media)["pending_fetch"] is False


def test_a_fetch_the_registry_calls_failed_retires_the_row(tmp_path):
    """FAILED is an answer: no stand-in was placed, so the row goes rather
    than waiting out the six-hour expiry."""
    media = _intent(tmp_path, name="failed.mov", geometry=None)
    media.write_bytes(b"whatever lane B brought")

    assert broll_standins.settle_intents(
        probe_fn=lambda path: None,
        job_state_fn=lambda dest: broll_fetch.STATE_FAILED) == 1
    assert broll_standins.get(media) is None


def test_the_job_registry_is_read_without_starting_or_popping_anything(tmp_path):
    """`poll_fetch` cannot answer "how did that download end": it STARTS a
    job when there is none and POPS a terminal one on read. `job_state` is
    the read-only question, and None means cannot tell, never failed."""
    assert broll_fetch.job_state(str(tmp_path / "never-fetched.mov")) is None


def test_an_intent_row_for_a_download_that_never_landed_is_retired(tmp_path):
    """A fetch that failed and was never polled again left the same
    unfalsifiable row. It expires: an intent whose file has not appeared
    within INTENT_EXPIRY_SECONDS is describing nothing."""
    media = _archive(tmp_path, "cc", "ff5", "gone.mov")
    media.parent.mkdir(parents=True)
    entry = broll_standins.record(media, share="broll",
                                  rel_path="cc/ff5/gone.mov",
                                  pending_fetch=True, size=None)
    assert entry["pending_fetch"] is True
    led = broll_standins.ledger()
    led._entries[broll_standins.normalise_key(media)]["placed_at"] = (
        time.time() - broll_standins.INTENT_EXPIRY_SECONDS - 60)

    assert broll_standins.settle_intents() == 1
    assert broll_standins.get(media) is None
    assert broll_standins.is_standin(media) is False


# ---------------------------------------------------------------------------
# CR-288C (comp-broll-tiers-1): a prune that cannot tell does nothing
# ---------------------------------------------------------------------------

def test_a_tree_that_is_absent_for_one_poll_does_not_erase_the_ledger(
        tmp_path, monkeypatch):
    """An unplugged sync drive, a share not yet mapped or a NAS reboot makes
    every entry unstattable at once. The 30-day prune read that as "gone" and
    dropped every old row, and the next write of any kind persisted it -- so
    when the drive came back the companion called a 1080p H.264 lie the real
    original, and a render on that machine rendered it."""
    old = _archive(tmp_path, "cc", "old.mov")
    old.parent.mkdir(parents=True)
    broll_standins.record(old, share="broll", rel_path="cc/old.mov", size=7)
    led = broll_standins.ledger()
    led._entries[broll_standins.normalise_key(old)]["placed_at"] = (
        time.time() - broll_standins.PRUNE_AFTER_SECONDS - 60)
    led._persist_locked()
    led._loaded = False
    led._stamp = None

    # The drive is pulled: neither the file nor the archive root is there.
    monkeypatch.setattr(broll_standins, "_isdir", lambda path: False)
    assert len(broll_standins.all()) == 1, (
        "a prune that cannot see the tree must do nothing")

    # The drive is back and the file really is gone: the prune still works.
    monkeypatch.undo()
    led._loaded = False
    led._stamp = None
    assert broll_standins.all() == []


# ---------------------------------------------------------------------------
# CR-288E (overseer-1): an original that is still uploading is a KNOWN one
# ---------------------------------------------------------------------------

def _detail_insert(**overrides):
    """`routes_api._insert_object`'s real shape, as the page forwards it."""
    data = {
        "share": "broll",
        "original_rel": "creators/2026-09-18 ingest/A001.MP4",
        "preview_rel": "creators/2026-09-18 ingest/Proxy/A001.mp4",
        "edit_proxy_rel": "creators/2026-09-18 ingest/Proxy/A001.mov",
        "known": True,
        "original_is_edit_weight": False,
        "geometry": {"width": 6064, "height": 3424, "fps": 30.0,
                     "frames": 1813, "start_tc": "12:09:12:22"},
    }
    data.update(overrides)
    return data


def test_an_original_still_uploading_gets_a_stand_in_not_the_preview(tmp_path):
    """overseer-1 (2026-09-18b). The two-stage `/uploaded` (CR-284I) takes a
    clip live while its multi-GB original is still going up, and the server
    now answers that window with the original's EXPECTED archive path plus
    `original_pending: true`. That is a KNOWN original, so the insert takes
    the ordinary stand-in path; reading it as "there is no original" would
    give the editor PLAN_PREVIEW_ONLY - the preview imported at the PREVIEW's
    own path - and the clip's File Path would then be wrong on every machine
    the project travels to, for a 6K original that is on its way."""
    rel = "creators/2026-09-18 ingest/A001.MP4"
    tiers = broll_server.derive_insert_paths(
        _detail_insert(original_pending=True), rel)

    assert tiers["original_known"] is True
    assert tiers["original_pending"] is True
    assert tiers["original_rel"] == rel

    plan = broll_server.plan_insert(False, False, tiers, wired=False)
    assert plan["action"] == broll_server.PLAN_FETCH_STANDIN
    assert plan["fetch_rel"] == tiers["preview_rel"]
    assert plan["insert_rel"] is None          # at the ORIGINAL's own path
    assert plan["upgrade_rel"] == tiers["edit_proxy_rel"]


def test_an_explicit_null_original_is_still_preview_only(tmp_path):
    """The other state of the same field, unchanged: a clip the archive holds
    no original for at all (stem-diverged, or ingested with "upload
    originals" off) must never be ledgered as a stand-in."""
    rel = "creators/2026-09-18 ingest/Proxy/A001.mp4"
    tiers = broll_server.derive_insert_paths(
        _detail_insert(original_rel=None, original_pending=False), rel)

    assert tiers["original_known"] is False
    assert tiers["original_pending"] is False

    plan = broll_server.plan_insert(False, False, tiers, wired=False)
    assert plan["action"] == broll_server.PLAN_PREVIEW_ONLY
    assert plan["upgrade_rel"] is None


def test_a_null_original_that_also_claims_to_be_pending_is_still_no_original(tmp_path):
    """A server contradicting itself: the null wins, because refusing to
    invent an original is the safe half of the disagreement."""
    tiers = broll_server.derive_insert_paths(
        _detail_insert(original_rel=None, original_pending=True),
        "creators/2026-09-18 ingest/Proxy/A001.mp4")

    assert tiers["original_known"] is False
    assert tiers["original_pending"] is False
    assert broll_server.plan_insert(
        False, False, tiers, wired=False)["action"] == broll_server.PLAN_PREVIEW_ONLY


def test_a_dashboard_that_never_mentions_pending_behaves_exactly_as_today(tmp_path):
    """Absent is not false and not true: it is silence, and silence is the
    behaviour every deployed dashboard already has."""
    rel = "creators/2026-09-18 ingest/A001.MP4"
    tiers = broll_server.derive_insert_paths(_detail_insert(), rel)

    assert tiers["original_pending"] is False
    assert tiers["original_known"] is True
    assert broll_server.plan_insert(
        False, False, tiers, wired=False)["action"] == broll_server.PLAN_FETCH_STANDIN


def test_a_server_that_could_not_look_is_never_pending(tmp_path):
    """proxy-tiers-3's `known: false` means the server judged NOTHING, so no
    field in the object may be read as its judgement - this one included."""
    tiers = broll_server.derive_insert_paths(
        _detail_insert(known=False, original_pending=True),
        "creators/2026-09-18 ingest/A001.MP4")

    assert tiers["original_pending"] is False
    assert broll_server.plan_insert(
        False, False, tiers, wired=False)["action"] == broll_server.PLAN_FETCH_ORIGINAL
