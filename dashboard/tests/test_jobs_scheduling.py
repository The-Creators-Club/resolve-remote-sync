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


def queue(conn, kind, inputs=None, requires=None, ago_seconds=0,
          forced=False, target_machine=None):
    """One job, optionally aged: the grace period is measured from
    `created_at`, so a test about "after a minute" moves the JOB, not a
    clock."""
    inputs = MEDIA_INPUTS if inputs is None else inputs
    if requires is None:
        requires = jobs_mod.default_requires(kind, inputs)
    now = dbmod.parse_iso(dbmod.utcnow_iso()) - dt.timedelta(seconds=ago_seconds)
    job_id = dbmod.create_job(conn, kind, inputs, requires, now=now.isoformat(),
                              forced=forced, target_machine=target_machine)
    conn.commit()
    return job_id


def in_minutes(minutes):
    """A volunteer deadline, as the person at a machine would set it from
    their tray."""
    return (dbmod.parse_iso(dbmod.utcnow_iso())
            + dt.timedelta(minutes=minutes)).isoformat()


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
    assert answer["summary"] == ("no computer can take this job right now: 2 of "
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


# ------------------------------------------------------- section 10: force
#
# Alex, after reading phase 4: "Is there an ability to force start the
# proxy/whisper workflow in the companion, without waiting for someone's idle
# PC to process it?" Everything the scheduler knew how to say was a reason to
# WAIT. These are the three levers that answer it, and every one of them is on
# trial here for the same property: WHAT IT DOES NOT BYPASS. "Force" means "do
# not wait for anybody to leave their desk"; a scheduler that read it as "run
# it anywhere" would hand GPU work to a laptop with no GPU, start jobs under a
# fleet halt, and make the halt button a lie.


def test_a_forced_job_goes_to_a_machine_with_somebody_sitting_at_it(conn):
    """The whole point of the lever. Nobody is idle, and the work starts."""
    machine(conn, "jsmith", "EDIT-PC", dict(MEDIA_CAPS, idle_seconds=0))
    ordinary = queue(conn, "proxy-480p")
    forced = queue(conn, "proxy-480p", forced=True)
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC")
    assert offers["offered"] == [forced]
    assert offers["forced"] == [forced]
    assert offers["refused"][ordinary] == jobs_mod.REFUSE_NOT_IDLE


def test_a_forced_job_skips_the_cooldown_of_a_machine_that_just_failed_one(conn):
    """The cooldown is there so one bad machine cannot eat a retry budget in
    a minute. An admin who says "now" has decided to spend it anyway."""
    machine(conn, "jsmith", "EDIT-PC", MEDIA_CAPS)
    until = (dbmod.parse_iso(dbmod.utcnow_iso())
             + dt.timedelta(seconds=600)).isoformat()
    conn.execute("UPDATE machine_state SET jobs_cooldown_until=?, "
                 "jobs_cooldown_reason=? WHERE machine=?",
                 (until, "ffmpeg died here", "EDIT-PC"))
    conn.commit()
    ordinary = queue(conn, "peaks")
    forced = queue(conn, "peaks", forced=True)
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC")
    assert offers["refused"][ordinary] == jobs_mod.REFUSE_COOLDOWN
    assert forced in offers["offered"]


def test_a_forced_job_has_no_grace_window(conn):
    """"Do not wait" cannot mean "wait sixty seconds for the machine with the
    encoder". Both are asked at once and the compare-and-set decides, which
    is what the claim has always been for."""
    machine(conn, "jsmith", "CPU-PC", dict(MEDIA_CAPS, nvenc=False))
    machine(conn, "ruskin", "GPU-PC", dict(MEDIA_CAPS, nvenc=True))
    job_id = queue(conn, "proxy-480p", forced=True)
    assert jobs_mod.offers_for_machine(conn, "jsmith", "CPU-PC")["offered"] == [job_id]
    assert jobs_mod.offers_for_machine(conn, "ruskin", "GPU-PC")["offered"] == [job_id]


@pytest.mark.parametrize("caps,reason", [
    ({"ffmpeg": False, "ffprobe": False}, jobs_mod.REFUSE_CAPABILITY),
    ({"jobs_enabled": False}, jobs_mod.REFUSE_JOBS_DISABLED),
    ({"job_kinds": ["whisper"]}, jobs_mod.REFUSE_KIND_NOT_ALLOWED),
])
def test_force_does_not_bypass_a_machine_that_cannot_or_may_not(conn, caps, reason):
    """THE LIST OF THINGS FORCE DOES NOT SKIP is the whole safety of the
    feature. A capability filter it could skip would be a job that claims and
    then fails; an allow-list it could skip would make `jobs_kinds` a
    suggestion."""
    machine(conn, "jsmith", "EDIT-PC", dict(MEDIA_CAPS, **caps))
    job_id = queue(conn, "proxy-480p", forced=True)
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC")
    assert offers["offered"] == []
    assert offers["refused"][job_id] == reason


def test_force_does_not_bypass_a_fleet_halt(conn):
    """The halt is the one control an admin has over a fleet in trouble, and
    a lever that could talk past it would make it a lie."""
    machine(conn, "jsmith", "EDIT-PC", MEDIA_CAPS)
    dbmod.set_fleet_halt(conn, True, "owen", "the NAS is full")
    conn.commit()
    job_id = queue(conn, "peaks", forced=True)
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC")
    assert offers["refused"][job_id] == jobs_mod.REFUSE_FLEET_HALT


def test_the_forced_list_is_a_subset_of_the_offered_one(conn):
    """It rides the reply so a companion can claim through its OWN closed
    gate. A dashboard naming a job here it had not also offered would be
    pushing work rather than offering it."""
    machine(conn, "jsmith", "EDIT-PC", MEDIA_CAPS)
    ordinary = queue(conn, "peaks")
    forced = queue(conn, "peaks", forced=True)
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC")
    assert set(offers["offered"]) == {ordinary, forced}
    assert offers["forced"] == [forced]


# ------------------------------------------------------ section 10: target

def test_a_targeted_job_is_offered_to_that_machine_and_nobody_else(conn):
    machine(conn, "jsmith", "EDIT-PC", MEDIA_CAPS)
    machine(conn, "ruskin", "OTHER-PC", MEDIA_CAPS)
    job_id = queue(conn, "peaks", target_machine="EDIT-PC")
    assert jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC")["offered"] == [job_id]
    other = jobs_mod.offers_for_machine(conn, "ruskin", "OTHER-PC")
    assert other["offered"] == []
    assert other["refused"][job_id] == jobs_mod.REFUSE_NOT_TARGET


@pytest.mark.parametrize("target", ["EDIT-PC", "edit-pc", " Edit-PC ",
                                    "jsmith/EDIT-PC", "JSMITH/edit-pc"])
def test_a_target_is_matched_case_insensitively_and_may_name_the_editor(
        conn, target):
    """The name an admin types is the one they read off the fleet grid, and
    neither spelling is canonical. `editor/machine` is accepted because two
    editors' laptops can carry the same machine name."""
    machine(conn, "jsmith", "EDIT-PC", MEDIA_CAPS)
    job_id = queue(conn, "peaks", target_machine=target)
    assert jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC")["offered"] == [job_id]


def test_the_editor_half_of_a_target_has_to_match_too(conn):
    """Otherwise `ruskin/EDIT-PC` would run on jsmith's EDIT-PC, which is
    work done on a computer nobody asked about."""
    machine(conn, "jsmith", "EDIT-PC", MEDIA_CAPS)
    job_id = queue(conn, "peaks", target_machine="ruskin/EDIT-PC")
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC")
    assert offers["refused"][job_id] == jobs_mod.REFUSE_NOT_TARGET


def test_a_target_nobody_answers_to_is_accepted_and_says_so(conn):
    """An unknown name is a job that waits VISIBLY. Refusing it at submit
    time would make an admin guess at a spelling with nothing to check it
    against, and that machine may be switched on tomorrow."""
    machine(conn, "jsmith", "EDIT-PC", MEDIA_CAPS)
    answer = jobs_mod.explain(conn, queue(conn, "peaks", target_machine="LAPTOP-9"))
    assert answer["schedulable"] is False
    assert answer["reason_code"] == jobs_mod.REASON_TARGET_UNKNOWN
    # NOT transient: a client told to keep waiting for a machine that has
    # never reported is a lane that spins for ever over a typo.
    assert answer["transient"] is False
    assert "LAPTOP-9" in answer["summary"]
    assert answer["capable"] == 0


def test_a_target_that_is_here_but_busy_is_transient_and_named(conn):
    machine(conn, "jsmith", "EDIT-PC", dict(MEDIA_CAPS, idle_seconds=0))
    machine(conn, "ruskin", "OTHER-PC", MEDIA_CAPS)
    answer = jobs_mod.explain(conn, queue(conn, "peaks", target_machine="EDIT-PC"))
    assert answer["schedulable"] is False
    assert answer["reason_code"] == jobs_mod.REASON_TARGET_AWAY
    assert answer["transient"] is True
    assert "EDIT-PC" in answer["summary"]


def test_a_target_that_cannot_do_the_work_is_not_a_transient_answer(conn):
    """"Wait for that one machine" is only honest while that machine could
    ever finish it. Its own refusal passes straight through."""
    machine(conn, "jsmith", "EDIT-PC", dict(MEDIA_CAPS, ffmpeg=False, ffprobe=False))
    answer = jobs_mod.explain(conn, queue(conn, "peaks", target_machine="EDIT-PC"))
    assert answer["reason_code"] == jobs_mod.REASON_NO_CAPABLE
    assert answer["transient"] is False


def test_a_targeted_job_has_no_grace_window_either(conn):
    """There is one candidate, so a preference among candidates has nothing
    left to decide."""
    machine(conn, "jsmith", "CPU-PC", dict(MEDIA_CAPS, nvenc=False))
    machine(conn, "ruskin", "GPU-PC", dict(MEDIA_CAPS, nvenc=True))
    job_id = queue(conn, "proxy-480p", target_machine="CPU-PC")
    assert jobs_mod.offers_for_machine(conn, "jsmith", "CPU-PC")["offered"] == [job_id]


def test_a_target_does_not_bypass_that_machines_own_gates(conn):
    """`--on` chooses WHO, never WHETHER. Without `--now` the named machine
    still waits for its editor to stand up."""
    machine(conn, "jsmith", "EDIT-PC", dict(MEDIA_CAPS, idle_seconds=0))
    job_id = queue(conn, "peaks", target_machine="EDIT-PC")
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC")
    assert offers["refused"][job_id] == jobs_mod.REFUSE_NOT_IDLE


def test_on_and_now_together_are_the_admins_whole_lever(conn):
    """The pair section 10.5 points at, instead of a dashboard button that
    volunteers somebody else's computer for them."""
    machine(conn, "jsmith", "EDIT-PC", dict(MEDIA_CAPS, idle_seconds=0))
    machine(conn, "ruskin", "OTHER-PC", MEDIA_CAPS)
    job_id = queue(conn, "peaks", forced=True, target_machine="EDIT-PC")
    assert jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC")["offered"] == [job_id]
    assert jobs_mod.offers_for_machine(conn, "ruskin", "OTHER-PC")["offered"] == []


# --------------------------------------------------- section 10: volunteer

def test_volunteering_opens_the_idle_floor_while_somebody_works(conn):
    machine(conn, "jsmith", "EDIT-PC",
            dict(MEDIA_CAPS, idle_seconds=0, volunteer_until=in_minutes(30)))
    job_id = queue(conn, "proxy-480p")
    assert jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC")["offered"] == [job_id]


def test_the_timer_running_out_closes_the_gate_with_no_message_from_anyone(conn):
    """The deadline is the whole mechanism: a companion that crashes, or a
    person who forgets, does not leave a machine volunteering for ever."""
    machine(conn, "jsmith", "EDIT-PC",
            dict(MEDIA_CAPS, idle_seconds=0, volunteer_until=in_minutes(-1)))
    job_id = queue(conn, "peaks")
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC")
    assert offers["refused"][job_id] == jobs_mod.REFUSE_NOT_IDLE


@pytest.mark.parametrize("value", ["", None, "soon", "2026-13-45T99:00:00"])
def test_an_unreadable_volunteer_deadline_is_not_a_volunteer(value):
    """idle_seconds' direction, again: a value this server cannot read must
    never be the reason work starts under somebody's hands."""
    assert jobs_mod.is_volunteering({"volunteer_until": value}) is False


def test_volunteering_does_not_bypass_the_capability_filter(conn):
    """A person saying "use my machine" is not a person saying "run work my
    machine cannot do"."""
    machine(conn, "jsmith", "EDIT-PC",
            dict(MEDIA_CAPS, ffmpeg=False, ffprobe=False, idle_seconds=0,
                 volunteer_until=in_minutes(30)))
    job_id = queue(conn, "peaks")
    offers = jobs_mod.offers_for_machine(conn, "jsmith", "EDIT-PC")
    assert offers["refused"][job_id] == jobs_mod.REFUSE_CAPABILITY


def test_volunteering_survives_the_round_trip_through_the_row(conn):
    """Stored beside the other capabilities and read back under the name the
    companion sends -- the one decoding, like every other value in
    _capabilities_of."""
    machine(conn, "jsmith", "EDIT-PC",
            dict(MEDIA_CAPS, volunteer_until="2026-08-30T12:00:00+00:00"))
    caps = dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC")
    assert caps["volunteer_until"] == "2026-08-30T12:00:00+00:00"
    assert jobs_mod.is_volunteering(caps, "2026-08-30T11:59:00+00:00") is True
    assert jobs_mod.is_volunteering(caps, "2026-08-30T12:00:01+00:00") is False


def test_a_companion_that_says_nothing_is_not_volunteering(conn):
    """Every build older than 0.9.61 sends no such key, and NULL must read as
    "not volunteering" rather than as anything at all."""
    machine(conn, "jsmith", "EDIT-PC", MEDIA_CAPS)
    caps = dbmod.machine_capabilities(conn, "jsmith", "EDIT-PC")
    assert caps["volunteer_until"] is None
    assert jobs_mod.is_volunteering(caps) is False


def test_a_volunteer_gets_first_refusal_over_better_hardware(conn):
    """The only rank signal about a PERSON, and it leads every kind's list: a
    machine whose editor said "go ahead" costs nobody anything, which beats
    an encoder on a machine somebody merely walked away from."""
    machine(conn, "ruskin", "GPU-PC", dict(MEDIA_CAPS, nvenc=True))
    machine(conn, "jsmith", "CPU-PC",
            dict(MEDIA_CAPS, nvenc=False, idle_seconds=0,
                 volunteer_until=in_minutes(30)))
    job_id = queue(conn, "proxy-480p")
    assert jobs_mod.offers_for_machine(conn, "jsmith", "CPU-PC")["offered"] == [job_id]
    assert jobs_mod.offers_for_machine(conn, "ruskin", "GPU-PC")["offered"] == []


# ---------------------------------------------------- section 10: the claim

def test_a_claim_narrowed_by_ids_takes_only_those(conn):
    """A companion whose own gate is shut claims the forced jobs and only
    those, so an editor at their keyboard is interrupted by the job somebody
    asked for and by nothing else on the queue."""
    machine(conn, "jsmith", "EDIT-PC", MEDIA_CAPS)
    ordinary = queue(conn, "peaks")
    forced = queue(conn, "peaks", forced=True)
    job = dbmod.claim_next_job(conn, "jsmith", "EDIT-PC", MEDIA_CAPS,
                               allowed_ids=[ordinary, forced], ids=[forced])
    assert job["id"] == forced


def test_ids_intersect_the_offer_and_never_widen_it(conn):
    """Asking for a job must not hand out one the scheduler refused: `ids`
    narrows what was offered, it does not replace it."""
    machine(conn, "jsmith", "EDIT-PC", MEDIA_CAPS)
    offered = queue(conn, "peaks")
    not_offered = queue(conn, "peaks")
    job = dbmod.claim_next_job(conn, "jsmith", "EDIT-PC", MEDIA_CAPS,
                               allowed_ids=[offered], ids=[not_offered])
    assert job is None


def test_the_row_carries_both_levers_back_as_a_bool_and_a_name(conn):
    """The shape both halves of this contract read: `forced` is a BOOL out
    here and an INTEGER in the column, because 0/1 in a JSON body is the kind
    of thing a client gets subtly wrong."""
    job = dbmod.get_job(conn, queue(conn, "peaks", forced=True,
                                    target_machine="EDIT-PC"))
    assert job["forced"] is True
    assert job["target_machine"] == "EDIT-PC"
    plain = dbmod.get_job(conn, queue(conn, "peaks"))
    assert plain["forced"] is False
    assert plain["target_machine"] == ""


# ---------------------------------------------- CMEDIA-1: the third consumer
#
# Usability sweep 2026-09-03. B-roll indexing and proxy generation negotiate on
# the editor's own computer ("indexing beats proxy generation") and the job
# runner was outside the agreement: both gates open on the same event (nobody
# at the keyboard), so a whisper job was claimed onto a computer already
# holding 8-12 GB of VLM weights, OOM'd, and earned that computer the
# per-machine cooldown for a fault it did not have.
#
# TWO SOURCES, ON PURPOSE. The companion sends its own gate in
# `capabilities.jobs_gate` with the sentence beside it, which is what the
# report and the claim read; that is a fact about this second, so it is not
# given a column. `explain` answers from the database long afterwards, so it
# reads the flags that ARE stored - `ingest_active`, `music_ingest_active` -
# on the row it already selects.


def gate(reason, detail=""):
    """The capabilities section a companion busy with its own work reports."""
    return {"jobs_gate": {"reason": reason, "detail": detail}}


def indexing(conn, editor, name, what="broll"):
    """A stubbed report from a computer that is indexing right now."""
    section = {"active": True, "state": "running", "done": 3, "total": 12}
    dbmod.upsert_machine_state(
        conn, editor, name, None, dbmod.utcnow_iso(),
        ingest=section if what == "broll" else None,
        music=section if what == "music" else None)
    conn.commit()


def test_a_computer_indexing_b_roll_is_refused_and_the_why_says_what_it_is_doing(conn):
    machine(conn, "jsmith", "EDIT-PC", MEDIA_CAPS)
    indexing(conn, "jsmith", "EDIT-PC")
    answer = jobs_mod.explain(conn, queue(conn, "peaks"))
    line = answer["machines"][0]
    assert line["ok"] is False
    assert line["reason"] == jobs_mod.REFUSE_LOCAL_WORK
    assert line["why"] == "this computer is busy indexing b-roll"


def test_a_computer_embedding_music_is_refused_too(conn):
    machine(conn, "jsmith", "EDIT-PC", MEDIA_CAPS)
    indexing(conn, "jsmith", "EDIT-PC", what="music")
    answer = jobs_mod.explain(conn, queue(conn, "peaks"))
    assert answer["machines"][0]["why"] == "this computer is busy indexing music"


def test_the_companions_own_gate_wins_and_can_say_proxies(conn):
    """The stored flags know about indexing; only the computer knows it is
    three minutes into a proxy encode, so the gate it just sent is preferred
    wherever there is one - the report reply and the claim."""
    machine(conn, "jsmith", "EDIT-PC", MEDIA_CAPS)
    facts = jobs_mod.machine_facts(
        conn, "jsmith", "EDIT-PC",
        capabilities=dict(MEDIA_CAPS, **gate("local_work", "busy making proxies")))
    reason, why = jobs_mod.policy_refusal(facts, "peaks")
    assert reason == jobs_mod.REFUSE_LOCAL_WORK
    assert why == "this computer is busy making proxies"


def test_a_busy_computer_is_offered_nothing_on_its_own_report(conn):
    machine(conn, "jsmith", "EDIT-PC", MEDIA_CAPS)
    queue(conn, "peaks")
    offers = jobs_mod.offers_for_machine(
        conn, "jsmith", "EDIT-PC",
        capabilities=dict(MEDIA_CAPS, **gate("local_work", "busy indexing b-roll")))
    assert offers["offered"] == []


def test_with_no_other_candidate_the_job_level_answer_is_all_busy(conn):
    """The distinction the Timeline Cards client acts on: `all_busy` is
    transient, so it waits; `no_capable_machine` would send it off to do the
    work itself for ever."""
    machine(conn, "jsmith", "EDIT-PC", MEDIA_CAPS)
    indexing(conn, "jsmith", "EDIT-PC")
    answer = jobs_mod.explain(conn, queue(conn, "peaks"))
    assert answer["schedulable"] is False
    assert answer["reason_code"] == jobs_mod.REASON_ALL_BUSY
    assert answer["transient"] is True
    # It CAN do this kind of work; it is busy, which is a different number.
    assert answer["capable"] == 1


def test_local_work_is_not_idle_for_the_ranking(conn):
    """The saturated computer used to be FIRST: nobody is at the keyboard, so
    it had been idle longest. Policy refuses it before rank_key ever sees it,
    so the free computer wins even though it has been idle for an hour and the
    busy one for two minutes."""
    machine(conn, "jsmith", "BUSY-PC", dict(MEDIA_CAPS, idle_seconds=3600))
    indexing(conn, "jsmith", "BUSY-PC")
    machine(conn, "leso", "FREE-PC", dict(MEDIA_CAPS, idle_seconds=120))
    able = jobs_mod.ranked_machines(
        dbmod.get_job(conn, queue(conn, "peaks")), jobs_mod.fleet_facts(conn),
        dbmod.utcnow_iso())
    assert [key for key, _score in able] == [("leso", "FREE-PC")]


def test_a_gate_reason_this_build_does_not_know_is_not_a_refusal(conn):
    """A dashboard that invents refusals from strings it has never seen is a
    queue that stops for a typo in a newer companion."""
    machine(conn, "jsmith", "EDIT-PC", MEDIA_CAPS)
    facts = jobs_mod.machine_facts(
        conn, "jsmith", "EDIT-PC",
        capabilities=dict(MEDIA_CAPS, **gate("quantum_flux", "busy being new")))
    assert jobs_mod.policy_refusal(facts, "peaks") == ("", "")
    assert jobs_mod.local_work_words({"jobs_gate": "not even a mapping"}) == ""
    assert jobs_mod.local_work_words({}) == ""
    assert jobs_mod.local_work_words(None) == ""


def test_local_work_with_no_detail_still_says_something(conn):
    """A companion that sends the state and no sentence must not produce an
    empty refusal: "" would render as a computer refused for no reason."""
    machine(conn, "jsmith", "EDIT-PC", MEDIA_CAPS)
    facts = jobs_mod.machine_facts(
        conn, "jsmith", "EDIT-PC",
        capabilities=dict(MEDIA_CAPS, **gate("local_work")))
    assert jobs_mod.policy_refusal(facts, "peaks")[1] == (
        "this computer is busy with its own media work")
