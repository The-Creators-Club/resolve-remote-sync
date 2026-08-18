"""`index: false` — a share that gets every local stage and no paid one.

Our own shoots do not need describing to be usable: we know what we shot, and
the shoot's folder tree (event / day / camera) already organises it the way an
editor looks for it. They stay browsable, previewable and speech-searchable,
because all of that is local and free — only the model call is skipped.
"""
from __future__ import annotations

import parallel_claude
import pytest
from broll_index import pipeline
from broll_index.config import Config, DbConfig, SamplingConfig, ShareConfig
from broll_index.pipeline import ORGANISED_STATUS
from broll_index.storage.sqlite_backend import SqliteBackend


def _cfg(tmp_path, *, index: bool) -> Config:
    return Config(
        shares={"own": ShareConfig(root=str(tmp_path), index=index),
                "dl": ShareConfig(root=str(tmp_path))},
        data_root=tmp_path / "_data",
        db=DbConfig(mode="sqlite", path=str(tmp_path / "broll.db")),
        model="haiku",
        sampling=SamplingConfig(),
    )


def test_the_model_stage_is_skipped_and_the_clip_is_marked_organised(
    tmp_path, schema_path, monkeypatch
):
    db = SqliteBackend(tmp_path / "b.db", schema_path=schema_path)
    vid = db.upsert_video("own", "Proxy/a.mov", status="proxied", duration_s=10.0)
    (tmp_path / "Proxy").mkdir(exist_ok=True)
    (tmp_path / "Proxy" / "a.mov").write_bytes(b"x")

    called = []
    monkeypatch.setattr(pipeline, "stage_describe", lambda *a, **k: called.append(1))

    pipeline._process_video(_cfg(tmp_path, index=False), db, db.get_video(vid),
                            model="haiku", requested_stages={"claude"})

    assert not called, "index:false must never spend a model call"
    assert db.get_video(vid)["status"] == ORGANISED_STATUS


def test_organised_is_not_indexed(tmp_path, schema_path, monkeypatch):
    """'indexed' would claim segments and themes that do not exist."""
    assert ORGANISED_STATUS != "indexed"


def test_an_organised_clip_leaves_the_work_queue(tmp_path, schema_path, monkeypatch):
    """Left at 'proxied' it would sit in the queue forever and keep the watchdog
    respawning the run."""
    db = SqliteBackend(tmp_path / "b2.db", schema_path=schema_path)
    vid = db.upsert_video("own", "Proxy/a.mov", status="proxied", duration_s=10.0)
    (tmp_path / "Proxy").mkdir(exist_ok=True)
    (tmp_path / "Proxy" / "a.mov").write_bytes(b"x")
    monkeypatch.setattr(pipeline, "stage_describe", lambda *a, **k: None)

    pipeline._process_video(_cfg(tmp_path, index=False), db, db.get_video(vid),
                            model="haiku", requested_stages={"claude"})

    remaining = {v["id"] for v in db.videos_by_status(["discovered", "probed", "proxied"])}
    assert vid not in remaining


def test_an_indexable_share_is_unaffected(tmp_path, schema_path, monkeypatch):
    db = SqliteBackend(tmp_path / "b3.db", schema_path=schema_path)
    vid = db.upsert_video("dl", "a.mov", status="proxied", duration_s=10.0)
    (tmp_path / "a.mov").write_bytes(b"x")
    called = []
    monkeypatch.setattr(pipeline, "stage_describe", lambda *a, **k: called.append(1))

    pipeline._process_video(_cfg(tmp_path, index=False), db, db.get_video(vid),
                            model="haiku", requested_stages={"claude"})

    assert called, "a normal share must still be indexed"


def test_eligible_ids_excludes_an_opted_out_share(tmp_path, schema_path):
    """Excluded from the work queue too, not just rejected on arrival — so the
    run's total reflects what it will actually do."""
    db_path = tmp_path / "b4.db"
    db = SqliteBackend(db_path, schema_path=schema_path)
    keep = db.upsert_video("dl", "a.mov", status="proxied")
    db.upsert_video("own", "Proxy/b.mov", status="proxied")
    db.close()

    assert parallel_claude.eligible_ids(str(db_path)) == sorted(
        [keep] + [i for i in parallel_claude.eligible_ids(str(db_path)) if i != keep])
    assert parallel_claude.eligible_ids(str(db_path), skip_shares={"own"}) == [keep]


def test_no_skip_shares_is_the_old_behaviour(tmp_path, schema_path):
    db_path = tmp_path / "b5.db"
    db = SqliteBackend(db_path, schema_path=schema_path)
    a = db.upsert_video("dl", "a.mov", status="proxied")
    b = db.upsert_video("own", "Proxy/b.mov", status="proxied")
    db.close()
    assert parallel_claude.eligible_ids(str(db_path)) == sorted([a, b])
    assert parallel_claude.eligible_ids(str(db_path), skip_shares=set()) == sorted([a, b])


def test_config_parses_the_flag(tmp_path):
    import yaml
    from broll_index.config import load_config
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({
        "shares": {"own": {"root": "R:/x", "index": False}, "dl": {"root": "R:/y"}},
        "data_root": str(tmp_path),
        "db": {"mode": "sqlite", "path": str(tmp_path / "b.db")},
    }), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.shares["own"].index is False
    assert cfg.shares["dl"].index is True, "shares default to indexable"


def test_contact_sheets_are_skipped_too(tmp_path, schema_path, monkeypatch):
    """Sheets are the images sent to the model and nothing else reads them. On
    an index:false share, building them is a full scene-detection decode per
    clip producing output nobody will ever open — the heaviest local stage,
    spent on nothing."""
    db = SqliteBackend(tmp_path / "b6.db", schema_path=schema_path)
    vid = db.upsert_video("own", "Proxy/a.mov", status="proxied", duration_s=10.0)
    (tmp_path / "Proxy").mkdir(exist_ok=True)
    (tmp_path / "Proxy" / "a.mov").write_bytes(b"x")

    frames, claude = [], []
    monkeypatch.setattr(pipeline, "stage_frames", lambda *a, **k: frames.append(1))
    monkeypatch.setattr(pipeline, "stage_describe", lambda *a, **k: claude.append(1))

    pipeline._process_video(_cfg(tmp_path, index=False), db, db.get_video(vid),
                            model="haiku", requested_stages={"frames", "claude"})

    assert not frames, "no sheets without a model call to feed"
    assert not claude
    assert db.get_video(vid)["status"] == ORGANISED_STATUS


def test_an_indexable_share_still_gets_its_sheets(tmp_path, schema_path, monkeypatch):
    db = SqliteBackend(tmp_path / "b7.db", schema_path=schema_path)
    vid = db.upsert_video("dl", "a.mov", status="proxied", duration_s=10.0)
    (tmp_path / "a.mov").write_bytes(b"x")
    frames = []
    monkeypatch.setattr(pipeline, "stage_frames", lambda *a, **k: frames.append(1))
    monkeypatch.setattr(pipeline, "stage_describe", lambda *a, **k: None)

    pipeline._process_video(_cfg(tmp_path, index=False), db, db.get_video(vid),
                            model="haiku", requested_stages={"frames"})

    assert frames, "a normal share must still build contact sheets"


def test_the_proxy_itself_is_still_built(tmp_path, schema_path, monkeypatch):
    """The proxy is NOT waste even though the source is already a proxy: these
    are 10-bit HEVC, which browsers cannot play, so the H.264 copy is what makes
    the clip previewable at all."""
    db = SqliteBackend(tmp_path / "b8.db", schema_path=schema_path)
    vid = db.upsert_video("own", "Proxy/a.mov", status="probed", duration_s=10.0)
    (tmp_path / "Proxy").mkdir(exist_ok=True)
    (tmp_path / "Proxy" / "a.mov").write_bytes(b"x")

    built = []
    monkeypatch.setattr(pipeline, "stage_proxy", lambda *a, **k: (
        built.append(1), db.update_video(vid, status="proxied")))

    pipeline._process_video(_cfg(tmp_path, index=False), db, db.get_video(vid),
                            model="haiku", requested_stages={"proxy"})

    assert built, "index:false must not skip the proxy — it is what makes it playable"


# --- index:false is a decision that can be revisited ---------------------------

def test_flipping_index_back_on_reopens_an_organised_clip(tmp_path, schema_path):
    """Without this, `organised` is a one-way door: nothing in
    STAGE_PREREQ_STATUS accepts it, so a share indexed later would sit there
    forever, invisible to every runner while looking finished."""
    db = SqliteBackend(tmp_path / "r1.db", schema_path=schema_path)
    vid = db.upsert_video("own", "Proxy/a.mov", status=ORGANISED_STATUS)

    reopened = pipeline.reopen_if_now_indexable(
        _cfg(tmp_path, index=True), db, db.get_video(vid))

    assert reopened["status"] == "proxied", "back to where the clip actually stopped"
    assert db.get_video(vid)["status"] == "proxied"


def test_it_stays_organised_while_the_share_is_still_opted_out(tmp_path, schema_path):
    db = SqliteBackend(tmp_path / "r2.db", schema_path=schema_path)
    vid = db.upsert_video("own", "Proxy/a.mov", status=ORGANISED_STATUS)

    same = pipeline.reopen_if_now_indexable(
        _cfg(tmp_path, index=False), db, db.get_video(vid))

    assert same["status"] == ORGANISED_STATUS


@pytest.mark.parametrize("status", ["discovered", "probed", "proxied", "indexed", "skipped"])
def test_reopening_never_touches_a_clip_at_any_other_status(tmp_path, schema_path, status):
    db = SqliteBackend(tmp_path / f"r3-{status}.db", schema_path=schema_path)
    vid = db.upsert_video("own", "a.mov", status=status)
    out = pipeline.reopen_if_now_indexable(_cfg(tmp_path, index=True), db, db.get_video(vid))
    assert out["status"] == status


def test_reopened_clips_get_their_sheets_and_index(tmp_path, schema_path, monkeypatch):
    """The whole point: after the flip, a re-run treats them like any other
    share — sheets built from the proxy they already have, then indexed."""
    db = SqliteBackend(tmp_path / "r4.db", schema_path=schema_path)
    vid = db.upsert_video("own", "Proxy/a.mov", status=ORGANISED_STATUS, duration_s=10.0)
    (tmp_path / "Proxy").mkdir(exist_ok=True)
    (tmp_path / "Proxy" / "a.mov").write_bytes(b"x")

    frames, claude = [], []
    monkeypatch.setattr(pipeline, "stage_frames", lambda *a, **k: frames.append(1))
    monkeypatch.setattr(pipeline, "stage_describe", lambda *a, **k: claude.append(1))

    pipeline._process_video(_cfg(tmp_path, index=True), db, db.get_video(vid),
                            model="haiku", requested_stages={"frames", "claude"})

    assert frames, "sheets are built on the way back in"
    assert claude, "and then it is indexed"


def test_the_local_runner_can_see_an_organised_clip(tmp_path, schema_path):
    """It must be in the work queue at all, or the reopen never runs."""
    import parallel_local
    db_path = tmp_path / "r5.db"
    db = SqliteBackend(db_path, schema_path=schema_path)
    vid = db.upsert_video("own", "Proxy/a.mov", status=ORGANISED_STATUS)
    db.close()
    assert vid in parallel_local.eligible_ids(str(db_path))


def test_the_serial_runner_can_see_an_organised_clip_too(tmp_path, schema_path, monkeypatch):
    """Same requirement, the other runner — and it did not hold (BROLL-IDX-4,
    2026-08-14). run_pipeline's work list was ["discovered","probed","proxied"],
    so `broll-index run` on a re-enabled share printed "processed 0 video(s)" and
    left its clips sitting at 'organised': the reopen that rescues them lives in
    _process_video, which only ever sees rows the query returned."""
    db = SqliteBackend(tmp_path / "r6.db", schema_path=schema_path)
    vid = db.upsert_video("own", "Proxy/a.mov", status=ORGANISED_STATUS, duration_s=10.0)
    (tmp_path / "Proxy").mkdir(exist_ok=True)
    (tmp_path / "Proxy" / "a.mov").write_bytes(b"x")

    frames, claude = [], []
    monkeypatch.setattr(pipeline, "stage_frames", lambda *a, **k: frames.append(1))
    monkeypatch.setattr(pipeline, "stage_describe", lambda *a, **k: claude.append(1))

    count = pipeline.run_pipeline(_cfg(tmp_path, index=True), db, model="haiku",
                                  stages=["frames", "claude"])

    assert count == 1, "the re-enabled clip must reach the runner at all"
    assert db.get_video(vid)["status"] == "proxied", "reopened where it stopped"
    assert frames and claude, "then treated like any other share"


def test_the_serial_runner_leaves_a_still_opted_out_clip_resting(
    tmp_path, schema_path, monkeypatch
):
    """Widening the work list must not start spending on shares that opted out:
    every status-gated stage declines a row that stays 'organised'."""
    db = SqliteBackend(tmp_path / "r7.db", schema_path=schema_path)
    vid = db.upsert_video("own", "Proxy/a.mov", status=ORGANISED_STATUS, duration_s=10.0)
    (tmp_path / "Proxy").mkdir(exist_ok=True)
    (tmp_path / "Proxy" / "a.mov").write_bytes(b"x")

    frames, claude = [], []
    monkeypatch.setattr(pipeline, "stage_frames", lambda *a, **k: frames.append(1))
    monkeypatch.setattr(pipeline, "stage_describe", lambda *a, **k: claude.append(1))

    pipeline.run_pipeline(_cfg(tmp_path, index=False), db, model="haiku",
                          stages=["frames", "claude"])

    assert not frames and not claude
    assert db.get_video(vid)["status"] == ORGANISED_STATUS


# --- transcribe: false ---------------------------------------------------------

def test_transcription_is_skipped_when_the_share_opts_out(tmp_path, schema_path, monkeypatch):
    """Our own b-roll is cutaways and atmosphere with incidental crew chatter.
    Transcribing it costs GPU time to produce cues that are noise in the search
    index -- worse than nothing, since a query can match a grip saying
    "is it rolling"."""
    db = SqliteBackend(tmp_path / "t1.db", schema_path=schema_path)
    vid = db.upsert_video("own", "Proxy/a.mov", status="proxied", duration_s=10.0)
    (tmp_path / "Proxy").mkdir(exist_ok=True)
    (tmp_path / "Proxy" / "a.mov").write_bytes(b"x")

    called = []
    monkeypatch.setattr(pipeline, "stage_transcribe", lambda *a, **k: called.append(1))

    cfg = _cfg(tmp_path, index=False)
    cfg.shares["own"].transcribe = False
    pipeline._process_video(cfg, db, db.get_video(vid), model="haiku",
                            requested_stages={"transcribe"})

    assert not called


def test_transcription_still_runs_by_default(tmp_path, schema_path, monkeypatch):
    db = SqliteBackend(tmp_path / "t2.db", schema_path=schema_path)
    vid = db.upsert_video("dl", "a.mov", status="proxied", duration_s=10.0)
    (tmp_path / "a.mov").write_bytes(b"x")
    called = []
    monkeypatch.setattr(pipeline, "stage_transcribe", lambda *a, **k: called.append(1))

    pipeline._process_video(_cfg(tmp_path, index=True), db, db.get_video(vid),
                            model="haiku", requested_stages={"transcribe"})

    assert called, "shares default to transcribed"


def test_config_parses_the_transcribe_flag(tmp_path):
    import yaml
    from broll_index.config import load_config
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({
        "shares": {"own": {"root": "R:/x", "transcribe": False}, "dl": {"root": "R:/y"}},
        "data_root": str(tmp_path),
        "db": {"mode": "sqlite", "path": str(tmp_path / "b.db")},
    }), encoding="utf-8")
    cfg = load_config(p)
    assert cfg.shares["own"].transcribe is False
    assert cfg.shares["dl"].transcribe is True
