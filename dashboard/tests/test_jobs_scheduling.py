"""Which machine gets which kind of work, and why it can say so.

docs/TIMELINE-CARDS-INTO-CCSYNC.md phase 1 (2026-08-30). Phase 0 offered every
queued job to every capable idle machine and let the compare-and-set sort it
out; this suite is about the three things phase 1 added on top, each of which
is a way a fleet quietly does the wrong thing:

  * THE REQUIREMENTS OF A KIND ARE NOT A MATTER OF OPINION. A media recipe
    needs ffmpeg, ffprobe and BOTH of the roots the job names -- reading the
    rush and writing the cache are two different filesystems here -- and a
    submitter that forgets one queues work a machine claims and cannot
    finish.
  * A PREFERENCE MUST NEVER BE A GATE. The machine with the encoder gets
    first refusal at a proxy and the base rig gets first refusal at the cheap
    I/O-bound kinds, but sixty seconds later EVERY capable machine is offered
    the job. A scheduler that can starve a queue is worse than one with no
    opinion at all, because the symptom is identical to an empty fleet.
  * THE CHEAP KINDS HAVE A LOWER FLOOR. Making a laptop wait five minutes of
    stillness before it will copy an audio track is how a lane sits on a
    spinner while capable machines do nothing.
"""
from __future__ import annotations

import datetime as dt

import pytest

from ccsync_dashboard import db as dbmod, jobs as jobs_mod

MEDIA_INPUTS = {
    "root": "media", "rel_path": "FF5/Civil Defence/Interview 3.mp4",
    "out_root": "vault",
    "out_rel": "Vault/2026/FF5/Civil Defence/Script Docs/remote_audio/source",
}

MEDIA_CAPS = {
    "ffmpeg": True, "ffprobe": True, "mounts": ["tree", "vault", "media"],
    "idle_seconds": 900, "cpu_count": 8,
}


@pytest.fixture
def conn(tmp_path):
    c = dbmod.connect(tmp_path / "jobs.db")
    dbmod.migrate(c)
    yield c
    c.close()


def machine(conn, editor, name, caps, mode="editor"):
    dbmod.upsert_machine_state(conn, editor, name, None, dbmod.utcnow_iso(),
                               mode=mode)
    dbmod.store_machine_capabilities(conn, editor, name, caps, dbmod.utcnow_iso())
    conn.commit()


def queue(conn, kind, inputs=None, requires=None, ago_seconds=0):
    """One job, optionally aged: the grace period is measured from
    `created_at`, so a test about "after a minute" moves the JOB, not a
    clock."""
    inputs = MEDIA_INPUTS if inputs is None else inputs
    if requires is None:
        requires = jobs_mod.default_requires(kind, inputs)
    now = dbmod.parse_iso(dbmod.utcnow_iso()) - dt.timedelta(seconds=ago_seconds)
    job_id = dbmod.create_job(conn, kind, inputs, requires, now=now.isoformat())
    conn.commit()
    return job_id


# --------------------------------------------------- requirements per kind

@pytest.mark.parametrize("kind", ["proxy-480p", "audio-extract", "peaks"])
def test_a_media_kind_needs_ffmpeg_ffprobe_and_both_roots(kind):
    assert jobs_mod.default_requires(kind, MEDIA_INPUTS) == {
        "ffmpeg": True, "ffprobe": True, "mount": ["media", "vault"]}


def test_one_root_named_twice_is_asked_for_once():
    """A job whose output goes back into the root it read from (Timeline
    Cards on a machine where the vault IS the media root) must not ask for
    the same mount twice -- the requirement would still pass, but the
    sentence on the why page would read like a bug."""
    inputs = dict(MEDIA_INPUTS, root="vault")
    assert jobs_mod.default_requires("peaks", inputs)["mount"] == ["vault"]


def test_whisper_keeps_stating_its_own_requirements():
    """Phase 0's decision stands: a VRAM floor is a property of the model the
    submitter chose, and a dashboard that invented one would be deciding
    something it does not know."""
    assert jobs_mod.default_requires("whisper", MEDIA_INPUTS) == {}


def test_a_machine_with_ffmpeg_but_no_ffprobe_is_refused(conn):
    """The two are separate capabilities for exactly this case: ffprobe is
    what decides the proxy's GOP and proves the audio came out the length it
    went in, so a machine without it would claim the work and then guess."""
    machine(conn, "jsmith", "NO-PROBE", dict(MEDIA_CAPS, ffprobe=False))
    job_id = queue(conn, "proxy-480p")
    answer = jobs_mod.explain(conn, job_id)
    assert answer["schedulable"] is False
    assert answer["machines"][0]["reason"] == jobs_mod.REFUSE_CAPABILITY
    assert "ffprobe" in answer["machines"][0]["why"]


def test_a_machine_missing_one_of_the_two_roots_is_refused(conn):
    """Reading the rush and writing the cache are two filesystems: the
    footage share is read-only where Timeline Cards runs, and a machine with
    the vault but no media mount fails halfway through, not at the start."""
    machine(conn, "jsmith", "NO-MEDIA", dict(MEDIA_CAPS, mounts=["tree", "vault"]))
    job_id = queue(conn, "audio-extract")
    answer = jobs_mod.explain(conn, job_id)
    assert answer["schedulable"] is False
    assert "media" in answer["machines"][0]["why"]


# --------------------------------------------------------------- the floor

def test_the_cheap_kinds_have_a_lower_idle_floor():
    assert jobs_mod.idle_floor("whisper") == 300
    assert jobs_mod.idle_floor("proxy-480p") == 300
    assert jobs_mod.idle_floor("audio-extract") == 60
    assert jobs_mod.idle_floor("peaks") == 60


def test_a_machine_idle_two_minutes_takes_the_audio_but_not_the_proxy(conn):
    """The same machine, the same instant, two answers -- because an audio
    copy is seconds and an x264 encode is minutes."""
    machine(conn, "jsmith", "EDIT-PC", dict(MEDIA_CAPS, idle_seconds=120))
    audio = queue(conn, "audio-extract")
    proxy = queue(conn, "proxy-480p")
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC")
    assert offers["offered"] == [audio]
    assert offers["refused"][proxy] == jobs_mod.REFUSE_NOT_IDLE


def test_an_unreadable_idle_answer_still_takes_no_work_of_any_kind(conn):
    """idle.py's contract, carried into the cheap kinds too: None means
    cannot tell means NOT IDLE. A lower floor is not a looser rule."""
    machine(conn, "jsmith", "EDIT-PC", dict(MEDIA_CAPS, idle_seconds=None))
    job_id = queue(conn, "peaks")
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC")
    assert offers["offered"] == []
    assert offers["refused"][job_id] == jobs_mod.REFUSE_NOT_IDLE


# ---------------------------------------------------------------- the rank

def test_nvenc_gets_first_refusal_at_a_proxy(conn):
    machine(conn, "jsmith", "CPU-PC", dict(MEDIA_CAPS, nvenc=False))
    machine(conn, "ruskin", "GPU-PC", dict(MEDIA_CAPS, nvenc=True))
    job_id = queue(conn, "proxy-480p")
    assert jobs_mod.offers_for_machine(conn, "ruskin", "GPU-PC")["offered"] == [job_id]
    refused = jobs_mod.offers_for_machine(conn, "jsmith", "CPU-PC")
    assert refused["offered"] == []
    assert refused["refused"][job_id] == jobs_mod.REFUSE_NOT_PREFERRED


def test_the_base_rig_gets_first_refusal_at_the_cheap_kinds(conn):
    """It is the machine next to the media and nobody sits at it, so an audio
    copy that runs there costs an editor nothing at all."""
    machine(conn, "jsmith", "EDIT-PC", MEDIA_CAPS)
    machine(conn, "owen", "BASE-RIG", MEDIA_CAPS, mode="base")
    job_id = queue(conn, "audio-extract")
    assert jobs_mod.offers_for_machine(conn, "owen", "BASE-RIG")["offered"] == [job_id]
    assert jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC")["offered"] == []


def test_the_base_rig_has_no_claim_on_a_proxy(conn):
    """The preference is per KIND and not a general seniority: an encoder
    beats being the base rig at a 480p encode, and the table says so."""
    machine(conn, "jsmith", "GPU-PC", dict(MEDIA_CAPS, nvenc=True))
    machine(conn, "owen", "BASE-RIG", dict(MEDIA_CAPS, nvenc=False), mode="base")
    job_id = queue(conn, "proxy-480p")
    assert jobs_mod.offers_for_machine(conn, "jsmith", "GPU-PC")["offered"] == [job_id]
    assert jobs_mod.offers_for_machine(conn, "owen", "BASE-RIG")["offered"] == []


def test_a_preference_expires_so_a_queue_cannot_starve(conn):
    """THE PROPERTY THIS WHOLE FEATURE IS ALLOWED TO EXIST FOR. The machine
    with the encoder was offered it twice and did not take it (asleep, its
    report lost, its companion out of date); a minute later the CPU machine
    is offered it, and the work gets done slowly instead of never."""
    machine(conn, "jsmith", "CPU-PC", dict(MEDIA_CAPS, nvenc=False))
    machine(conn, "ruskin", "GPU-PC", dict(MEDIA_CAPS, nvenc=True))
    job_id = queue(conn, "proxy-480p",
                   ago_seconds=jobs_mod.RANK_GRACE_SECONDS + 1)
    assert jobs_mod.offers_for_machine(conn, "jsmith", "CPU-PC")["offered"] == [job_id]


def test_two_equally_good_machines_are_offered_it_together(conn):
    """A tie is offered to BOTH, because the compare-and-set is what decides
    between them -- which is the whole reason the claim is a CAS and not a
    read-then-write."""
    machine(conn, "jsmith", "GPU-A", dict(MEDIA_CAPS, nvenc=True))
    machine(conn, "ruskin", "GPU-B", dict(MEDIA_CAPS, nvenc=True))
    job_id = queue(conn, "proxy-480p")
    assert jobs_mod.offers_for_machine(conn, "jsmith", "GPU-A")["offered"] == [job_id]
    assert jobs_mod.offers_for_machine(conn, "ruskin", "GPU-B")["offered"] == [job_id]


def test_the_least_loaded_of_two_equals_wins(conn):
    """Second in §4.4's order, after capability: two machines with the same
    encoder, one already holding a job."""
    machine(conn, "jsmith", "BUSY", dict(MEDIA_CAPS, nvenc=True))
    machine(conn, "ruskin", "FREE", dict(MEDIA_CAPS, nvenc=True))
    held = queue(conn, "peaks")
    assert dbmod.claim_job(conn, held, "jsmith", "BUSY")
    conn.commit()
    job_id = queue(conn, "proxy-480p")
    assert jobs_mod.offers_for_machine(conn, "ruskin", "FREE")["offered"] == [job_id]
    # ...and the busy one is refused for the reason that is actually true of
    # it, which is that it is busy, not that it is second choice.
    refused = jobs_mod.offers_for_machine(conn, "jsmith", "BUSY")
    assert refused["refused"][job_id] == jobs_mod.REFUSE_BUSY_WITH_JOB


def test_the_longest_idle_of_two_equals_wins(conn):
    """Third and last: nothing here ever tie-breaks on a NAME, because
    ranking machines alphabetically is how one computer ends up doing all the
    work of a fleet."""
    machine(conn, "aaa", "JUST-LEFT", dict(MEDIA_CAPS, nvenc=True, idle_seconds=310))
    machine(conn, "zzz", "LONG-GONE", dict(MEDIA_CAPS, nvenc=True, idle_seconds=9000))
    job_id = queue(conn, "proxy-480p")
    assert jobs_mod.offers_for_machine(conn, "zzz", "LONG-GONE")["offered"] == [job_id]
    assert jobs_mod.offers_for_machine(conn, "aaa", "JUST-LEFT")["offered"] == []


def test_a_missing_load_average_is_not_a_penalty(conn):
    """Windows has no `getloadavg`, and reporting null must not rank every
    Windows machine below every Mac for a reason that says nothing about how
    busy either is."""
    windows = dict(MEDIA_CAPS, nvenc=True, load=None)
    posix = dict(MEDIA_CAPS, nvenc=True, load=0.0)
    assert (jobs_mod.rank_key({"capabilities": windows, "mode": "editor"},
                              "proxy-480p")
            == jobs_mod.rank_key({"capabilities": posix, "mode": "editor"},
                                 "proxy-480p"))


# ----------------------------------------------------------------- the why

def test_why_names_the_order_and_not_just_the_yes(conn):
    """"Three machines can take this and it went to the one without the
    encoder" is a scheduling complaint this page has to be able to answer."""
    machine(conn, "jsmith", "CPU-PC", dict(MEDIA_CAPS, nvenc=False))
    machine(conn, "ruskin", "GPU-PC", dict(MEDIA_CAPS, nvenc=True))
    answer = jobs_mod.explain(conn, queue(conn, "proxy-480p"))
    assert answer["schedulable"] is True
    ranks = {(m["editor"], m["machine"]): m.get("rank") for m in answer["machines"]}
    assert ranks[("ruskin", "GPU-PC")] == 1
    assert ranks[("jsmith", "CPU-PC")] == 2
    first = [m for m in answer["machines"] if m.get("rank") == 1][0]
    assert "first choice" in first["why"]


def test_why_on_a_fleet_that_cannot_do_it_at_all_says_so_in_one_sentence(conn):
    machine(conn, "jsmith", "EDIT-PC", dict(MEDIA_CAPS, ffmpeg=False, ffprobe=False))
    machine(conn, "ruskin", "OTHER-PC", dict(MEDIA_CAPS, ffmpeg=False, ffprobe=False))
    answer = jobs_mod.explain(conn, queue(conn, "peaks"))
    assert answer["schedulable"] is False
    assert answer["summary"] == ("no machine can take this job right now: 2 of "
                                "2 cannot do this kind of work")


def test_the_grid_map_carries_a_readable_label_and_a_null_percent(conn):
    """`PROXY-480P` is the shape of a database value; the chip is read by a
    person. And an un-heartbeated job's percent is null, never 0 -- 0% is a
    machine that looks stuck."""
    machine(conn, "jsmith", "EDIT-PC", MEDIA_CAPS)
    job_id = queue(conn, "proxy-480p")
    assert dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC")
    conn.commit()
    chip = dbmod.fetch_running_jobs_map(conn)[("jsmith", "EDIT-PC")]
    assert chip["label"] == "PROXY 480p"
    assert chip["percent"] is None


def test_a_heartbeat_records_progress_and_a_silent_one_does_not_erase_it(conn):
    """COALESCE, not an overwrite: a peaks pass that heartbeats with no
    fraction must not blank the number a proxy left behind, and a runner that
    stops reporting one must not read as "back to the start"."""
    machine(conn, "jsmith", "EDIT-PC", MEDIA_CAPS)
    job_id = queue(conn, "proxy-480p")
    assert dbmod.claim_job(conn, job_id, "jsmith", "EDIT-PC")
    assert dbmod.heartbeat_job(conn, job_id, "jsmith", "EDIT-PC", progress=0.615)
    assert dbmod.fetch_running_jobs_map(conn)[("jsmith", "EDIT-PC")]["percent"] == 62
    assert dbmod.heartbeat_job(conn, job_id, "jsmith", "EDIT-PC", progress=None)
    assert dbmod.fetch_running_jobs_map(conn)[("jsmith", "EDIT-PC")]["percent"] == 62


def test_progress_outside_zero_to_one_is_clamped_not_stored(conn):
    """A runner that divides by a duration ffprobe guessed low would report
    140%, and the chip would say so for ever."""
    assert dbmod.clamp_progress(1.4) == 1.0
    assert dbmod.clamp_progress(-0.2) == 0.0
    assert dbmod.clamp_progress("nonsense") is None
    assert dbmod.clamp_progress(None) is None


def test_the_retry_budget_is_shorter_for_a_deterministic_recipe():
    """A recipe is deterministic and cheap, so a second machine failing the
    same clip the same way is evidence about the CLIP."""
    assert dbmod.job_retry_budget("whisper") == 3
    assert dbmod.job_retry_budget("proxy-480p") == 3
    assert dbmod.job_retry_budget("audio-extract") == 2
    assert dbmod.job_retry_budget("peaks") == 2


def test_the_two_pinned_kinds_are_still_unknown_here():
    """§4.2's last two rows must never become schedulable: every edit is a
    synthetic keystroke into whatever Resolve has open on ONE machine, and a
    scheduler that moved one to an idle machine has moved it into the wrong
    timeline."""
    assert "conform" not in dbmod.JOB_KINDS
    assert "resolve-edit" not in dbmod.JOB_KINDS


def test_a_pinned_kind_that_somehow_reached_the_queue_is_never_offered(conn):
    machine(conn, "jsmith", "EDIT-PC", MEDIA_CAPS)
    job_id = queue(conn, "resolve-edit", requires={})
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC")
    assert offers["offered"] == []
    assert offers["refused"][job_id] == jobs_mod.REFUSE_KIND_UNKNOWN
    assert jobs_mod.explain(conn, job_id)["schedulable"] is False
