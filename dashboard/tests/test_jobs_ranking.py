"""WHICH machine gets it, and why the others did not.

docs/TIMELINE-CARDS-INTO-CCSYNC.md phase 4 (2026-08-30). Phase 1 shipped a
one-point preference per kind and a grace window; phase 4 finished the table
and made it EXPLAINABLE, which is the half that matters:

  * the rank is an ordered list of signals per kind (nvenc for a proxy, a GPU
    with room for the model for whisper, the machine next to the media for
    the two cheap kinds), then least-loaded, then longest-idle;
  * `why` carries every able machine's rank TUPLE and the first component it
    lost on, in words. "Three machines could take this and it went to the one
    without the encoder" is a complaint, and a scheduler that cannot answer it
    is a scheduler nobody can debug (§6 phase 4's risk).

The grace window is still not a gate: every assertion here is about ORDER,
never about a machine being refused for being second.
"""
from __future__ import annotations

import pytest

from ccsync_dashboard import db as dbmod, jobs as jobs_mod


@pytest.fixture
def conn(tmp_path):
    c = dbmod.connect(tmp_path / "jobs.db")
    dbmod.migrate(c)
    yield c
    c.close()


def machine(conn, name, caps, mode="editor", editor="alex"):
    dbmod.upsert_machine_state(conn, editor, name, None, dbmod.utcnow_iso(),
                               mode=mode)
    dbmod.store_machine_capabilities(conn, editor, name, caps, dbmod.utcnow_iso())
    conn.commit()
    return (editor, name)


def facts(conn, key):
    return jobs_mod.fleet_facts(conn)[key]


MEDIA = {"ffmpeg": True, "ffprobe": True, "mounts": ["vault", "media"],
         "idle_seconds": 900, "cpu_count": 8}
GPU = {"whisper": True, "gpu_present": True, "mounts": ["vault"],
       "idle_seconds": 900}


# ------------------------------------------------------------ per kind

def test_a_proxy_prefers_the_machine_with_an_encoder(conn):
    plain = machine(conn, "cpu-box", dict(MEDIA))
    encoder = machine(conn, "nvenc-box", dict(MEDIA, nvenc=True))
    job = {"kind": "proxy-480p",
           "requires": {"ffmpeg": True, "ffprobe": True,
                        "mount": ["media", "vault"]}}
    order = [key for key, _score in
             jobs_mod.ranked_machines(job, jobs_mod.fleet_facts(conn))]
    assert order[0] == encoder
    assert plain in order


@pytest.mark.parametrize("kind", ["audio-extract", "peaks"])
def test_the_cheap_kinds_prefer_the_machine_next_to_the_media(conn, kind):
    """The base rig is next to the media, nobody sits at it, and an audio
    copy that runs there costs an editor nothing at all."""
    laptop = machine(conn, "laptop", dict(MEDIA, nvenc=True))
    base = machine(conn, "base-rig", dict(MEDIA), mode="base")
    job = {"kind": kind, "requires": {"ffmpeg": True, "ffprobe": True,
                                      "mount": ["media", "vault"]}}
    order = [key for key, _s in
             jobs_mod.ranked_machines(job, jobs_mod.fleet_facts(conn))]
    assert order == [base, laptop]


def test_whisper_prefers_a_gpu_the_model_actually_fits_in(conn):
    """A card with exactly the stated floor is a card that OOMs the moment
    anything else is on it. It still ranks -- below one with headroom."""
    tight = machine(conn, "tight", dict(GPU, gpu_vram_gb=6.0))
    roomy = machine(conn, "roomy", dict(GPU, gpu_vram_gb=24.0))
    job = {"kind": "whisper",
           "requires": {"whisper": True, "mount": "vault", "gpu_vram_gb": 6.0}}
    order = [key for key, _s in
             jobs_mod.ranked_machines(job, jobs_mod.fleet_facts(conn))]
    assert order == [roomy, tight]


def test_a_gpu_that_will_not_say_its_size_is_no_preference(conn):
    quiet = machine(conn, "quiet", dict(GPU, gpu_vram_gb=None))
    key = jobs_mod.rank_signals(facts(conn, quiet), "whisper",
                                {"requires": {"gpu_vram_gb": 6}})
    assert dict((n, have) for n, have, _w in key) == {"gpu_fits": False,
                                                      "gpu": True}


def test_rank_key_still_answers_without_the_job_row(conn):
    """Every caller that has only a kind in hand (the fleet page, a test)
    keeps working: `job` is optional and only `gpu_fits` reads it."""
    key = machine(conn, "box", dict(GPU, gpu_vram_gb=24.0))
    assert jobs_mod.rank_key(facts(conn, key), "whisper")[0] > 0


# --------------------------------------------------- the tie-breakers

def test_the_least_loaded_machine_wins_a_tie(conn):
    busy = machine(conn, "busy", dict(MEDIA, nvenc=True, load=4.0))
    idle = machine(conn, "calm", dict(MEDIA, nvenc=True, load=0.1))
    job = {"kind": "proxy-480p", "requires": {}}
    order = [k for k, _s in jobs_mod.ranked_machines(job, jobs_mod.fleet_facts(conn))]
    assert order == [idle, busy]


def test_the_longest_idle_machine_wins_when_everything_else_ties(conn):
    recent = machine(conn, "recent", dict(MEDIA, idle_seconds=400))
    away = machine(conn, "away", dict(MEDIA, idle_seconds=4000))
    job = {"kind": "peaks", "requires": {}}
    order = [k for k, _s in jobs_mod.ranked_machines(job, jobs_mod.fleet_facts(conn))]
    assert order == [away, recent]


def test_no_platform_load_average_is_not_a_penalty(conn):
    """None means Windows has no loadavg, not that the machine is idle-free.
    Ranking every Windows box below every Mac would be a fleet-wide decision
    taken on a fact about neither."""
    windows = machine(conn, "win", dict(MEDIA, load=None))
    mac = machine(conn, "mac", dict(MEDIA, load=0.0))
    job = {"kind": "peaks", "requires": {}}
    order = {k: s for k, s in
             jobs_mod.ranked_machines(job, jobs_mod.fleet_facts(conn))}
    assert order[windows] == order[mac]


# ------------------------------------------------------ the explanation

def test_why_names_the_thing_the_first_choice_had(conn):
    machine(conn, "cpu-box", dict(MEDIA))
    machine(conn, "nvenc-box", dict(MEDIA, nvenc=True))
    job_id = dbmod.create_job(conn, "proxy-480p",
                              {"root": "media", "rel_path": "a.mp4",
                               "out_root": "vault", "out_rel": "cache"},
                              {"ffmpeg": True, "ffprobe": True})
    conn.commit()
    answer = jobs_mod.explain(conn, job_id)
    lines = {m["machine"]: m for m in answer["machines"]}
    assert lines["nvenc-box"]["rank"] == 1
    assert lines["nvenc-box"]["why_not_first"] == ""
    assert "NVIDIA encoder" in lines["cpu-box"]["why_not_first"]
    assert "NVIDIA encoder" in lines["cpu-box"]["why"]


def test_why_carries_the_rank_tuple_and_the_signals(conn):
    machine(conn, "nvenc-box", dict(MEDIA, nvenc=True, load=0.5))
    job_id = dbmod.create_job(conn, "proxy-480p", {"root": "media"}, {})
    conn.commit()
    line = jobs_mod.explain(conn, job_id)["machines"][0]
    assert line["signals"] == {"nvenc": True}
    # preference, free slots, load, idle -- in that order, bigger is better
    assert line["score"] == [1.0, 0.0, -0.5, 900.0]


def test_a_machine_that_lost_on_load_is_told_so_and_not_on_hardware(conn):
    machine(conn, "busy", dict(MEDIA, nvenc=True, load=9.0))
    machine(conn, "calm", dict(MEDIA, nvenc=True, load=0.0))
    job_id = dbmod.create_job(conn, "proxy-480p", {"root": "media"}, {})
    conn.commit()
    lines = {m["machine"]: m for m in jobs_mod.explain(conn, job_id)["machines"]}
    assert lines["busy"]["why_not_first"] == "the first choice is less loaded"
