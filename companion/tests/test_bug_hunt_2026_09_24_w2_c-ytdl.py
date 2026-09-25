"""Wave 2 of the 2026-09-24 hunt's fix pass, group c-ytdl (2026-09-25).

bug-comp-ytdl-2 (its residual: the in-place fallback), bug-comp-ytdl-3,
bug-comp-ytdl-4, bug-comp-ytdl-5 and the c-ytdl half of ui-copy-4.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(__file__))

from ccsync_companion import sidecar_tools  # noqa: E402
from ccsync_companion import ytdl_executor as ex  # noqa: E402
from ccsync_companion import ytdlp_manager as ytdlp_mod  # noqa: E402
from test_ytdl_executor import (  # noqa: E402  (sibling test module)
    VID1, FakeTools, _deps_with_tools, _probe, _visible_during_conversion,
    make_cfg, make_deps, outdir_for, run_job, ytdlp,
)
import test_sweep_2026_09_04_copy as vocab  # noqa: E402

__all__ = ["ytdlp"]  # the fixture, re-exported for pytest's lookup


# ---------------------------------------------------------------------------
# bug-comp-ytdl-2: a stop mid-conversion after the staging rename was refused
# ---------------------------------------------------------------------------


def test_a_stop_mid_in_place_conversion_leaves_no_convert_needed_clip(
        tmp_path, ytdlp, monkeypatch):
    """The highs wave staged the original off its deliverable name; when that
    rename is refused (a scanner holding the just-closed file) the conversion
    runs in place, and a [ STOP ] then left the VP9 original under
    `<title> [id].mp4` for the importer and lane A. It is moved aside on the
    way out now, and the sweep removes it."""
    tools = FakeTools(ytdlp, probe=_probe(vcodec="vp9"))
    deps, fleet = _deps_with_tools(tmp_path, ytdlp, tools)
    real_replace = os.replace
    refused = {"n": 0}

    def refuse_the_first_staging(src, dst):
        if (str(dst).endswith(ex.SOURCE_STAGING_SUFFIX + ".mp4")
                and refused["n"] == 0):
            refused["n"] += 1
            raise PermissionError("a scanner has it open")
        return real_replace(src, dst)

    monkeypatch.setattr(ex.os, "replace", refuse_the_first_staging)
    job_ref: dict = {}
    real_call = tools.__call__

    def stopping(argv, timeout, on_spawn=None, on_line=None):
        result = real_call(argv, timeout, on_spawn, on_line)
        if os.path.basename(str(argv[0])).lower().startswith("ffmpeg"):
            job_ref["job"]._lease_lost.set()
        return result

    deps.run = stopping
    job = ex.DownloadJob(7, deps)
    job_ref["job"] = job
    job.run()

    assert refused["n"] == 1, "the in-place fallback was not exercised"
    outdir = outdir_for(tmp_path)
    assert _visible_during_conversion(outdir) == []
    assert fleet.state_sequence == [(VID1, "downloading")]


# ---------------------------------------------------------------------------
# bug-comp-ytdl-5: nothing could be renamed into place
# ---------------------------------------------------------------------------


def test_a_conversion_nothing_could_place_is_a_failed_clip_not_a_litter_name(
        tmp_path, ytdlp, monkeypatch):
    """Every rename of the converted file refused: the clip used to be posted
    `done` at `<stem>.editready.mp4`, a name clear_partials deletes and the
    importer never files. It is a failure now, and the original is put back
    and kept as `.failed` (YTDL-3's evidence) rather than removed first."""
    tools = FakeTools(ytdlp, probe=_probe(vcodec="vp9", acodec="opus"))
    deps, fleet = _deps_with_tools(tmp_path, ytdlp, tools)
    real_replace = os.replace

    def the_converted_file_is_held(src, dst):
        name = Path(str(src)).name
        if name.endswith(ex.EDITREADY_SUFFIX + ".mp4") and ".source." not in name:
            raise PermissionError("Access is denied")
        return real_replace(src, dst)

    monkeypatch.setattr(ex.os, "replace", the_converted_file_is_held)

    job = run_job(deps)

    assert [s for _v, s in fleet.state_sequence] == ["downloading", "failed"]
    body = fleet.body_for(VID1, "failed")
    assert "could be renamed into place" in (body.get("error") or "")
    assert (job.done, job.failed) == (0, 1)
    outdir = outdir_for(tmp_path)
    kept = [p for p in outdir.iterdir() if p.name.endswith(ex.DISOWNED_SUFFIX)]
    assert [p.read_bytes() for p in kept] == [b"video bytes"], \
        "the original was removed before the swap could fail"
    assert _visible_during_conversion(outdir) == []


# ---------------------------------------------------------------------------
# bug-comp-ytdl-3: a refused heartbeat ends the job
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403, 404])
def test_a_refused_heartbeat_raises_credential_lost(tmp_path, status):
    def request(method, url, body, headers, timeout):
        return status, {"detail": "missing or invalid X-CCSync-Token"}

    client = ex.FleetClient(ex.Deps(make_cfg(tmp_path), request_fn=request),
                            "editor2")
    with pytest.raises(ex.CredentialLost) as info:
        client.heartbeat(7)
    assert isinstance(info.value, ex.LeaseLost)
    assert f"HTTP {status}" in str(info.value)


@pytest.mark.parametrize("status", [200, 500, 502, 503])
def test_a_blip_or_a_renewal_is_not_a_verdict(tmp_path, status):
    def request(method, url, body, headers, timeout):
        return status, {"ok": status == 200}

    client = ex.FleetClient(ex.Deps(make_cfg(tmp_path), request_fn=request),
                            "editor2")
    client.heartbeat(7)  # no raise


def test_the_heartbeat_loop_stops_the_job_and_says_why(tmp_path):
    """An editor signed out mid-job: every call is 403, the server never says
    410 to this caller, and the old loop carried on to the last clip."""
    deps = make_deps(tmp_path)
    job = ex.DownloadJob(7, deps)

    class Refused:
        def heartbeat(self, job_id):
            raise ex.CredentialLost("the dashboard refused (HTTP 403)")

    job.client = Refused()
    runner = threading.Thread(target=job._heartbeat_loop, args=(0.01,),
                              daemon=True)
    runner.start()
    runner.join(5)
    assert not runner.is_alive()
    assert job._should_stop()
    reason = job.snapshot()["handed_back_reason"]
    assert "sign-in" in reason and "server" in reason
    assert "—" not in reason


# ---------------------------------------------------------------------------
# bug-comp-ytdl-4: a failed pass retries soon, not tomorrow
# ---------------------------------------------------------------------------


class _Waits:
    """A stop event that records each wait and ends the loop after `n`."""

    def __init__(self, n: int):
        self.waits: list = []
        self.n = n

    def wait(self, timeout):
        self.waits.append(timeout)
        return len(self.waits) > self.n

    def is_set(self):
        return len(self.waits) > self.n

    def set(self):
        self.n = -1

    def clear(self):
        pass


def _run_loop(monkeypatch, ytdl_actions, sidecar_actions, enabled=True):
    mgr = ytdlp_mod.YtDlpManager({"ytdl_local_downloads": enabled})
    monkeypatch.setattr(type(mgr), "enabled", property(lambda self: enabled))
    ytdl_iter = iter(ytdl_actions)
    side_iter = iter(sidecar_actions)

    def fake_ensure(min_version=None):
        action = next(ytdl_iter)
        if action == "raise":
            raise RuntimeError("boom")
        # (action, ok) spells a pass whose ok disagrees with its action
        if isinstance(action, tuple):
            action, ok = action
            return {"ok": ok, "action": action, "message": action}
        return {"ok": action != "failed", "action": action, "message": action}

    def fake_side(cfg=None, github_open=None, available_fn=None):
        action = next(side_iter)
        return {"ok": action != "failed", "action": action, "message": action}

    monkeypatch.setattr(mgr, "ensure", fake_ensure)
    monkeypatch.setattr(sidecar_tools, "ensure", fake_side)
    monkeypatch.setattr(sidecar_tools, "ensure_ffmpeg_pair", fake_side)
    waits = _Waits(len(ytdl_actions))
    mgr._stop_event = waits
    mgr._loop()
    return waits.waits[1:]  # [0] is INITIAL_DELAY_SECONDS


def test_a_failed_install_retries_with_backoff_then_settles_daily(monkeypatch):
    waits = _run_loop(monkeypatch, ["failed"] * 4 + ["installed", "none"],
                      ["none"] * 6)
    # HEAD waited the daily interval after a failed pass: behaviour first,
    # before any name this fix introduced
    assert waits[0] <= 900
    first = ytdlp_mod.FAILED_RETRY_FIRST_SECONDS
    assert waits == [first, first * 2, first * 4, first * 8,
                     ytdlp_mod.CHECK_INTERVAL_SECONDS,
                     ytdlp_mod.CHECK_INTERVAL_SECONDS]


def test_a_failed_sidecar_pass_or_a_raise_also_retries_soon(monkeypatch):
    waits = _run_loop(monkeypatch, ["none", "raise"], ["failed", "none"])
    first = ytdlp_mod.FAILED_RETRY_FIRST_SECONDS
    assert waits == [first, first * 2]


def test_the_backoff_never_exceeds_the_ordinary_cadence(monkeypatch):
    waits = _run_loop(monkeypatch, ["failed"] * 12, ["none"] * 12)
    assert max(waits) == ytdlp_mod.CHECK_INTERVAL_SECONDS
    # and with the feature off, never slower than the 15-minute recheck
    waits = _run_loop(monkeypatch, ["disabled"] * 4, ["failed"] * 4,
                      enabled=False)
    assert waits == [ytdlp_mod.FAILED_RETRY_FIRST_SECONDS,
                     ytdlp_mod.FAILED_RETRY_FIRST_SECONDS * 2,
                     ytdlp_mod.DISABLED_RECHECK_SECONDS,
                     ytdlp_mod.DISABLED_RECHECK_SECONDS]


def test_an_enabled_pass_that_leaves_ok_false_also_retries_soon(monkeypatch):
    # Review round: installed-but-unreadable and updated-but-still-short
    # publish ok=False without ACTION_FAILED, and capabilities() refuses
    # every job on ok=False just the same.
    first = ytdlp_mod.FAILED_RETRY_FIRST_SECONDS
    waits = _run_loop(monkeypatch,
                      [("installed", False), ("updated", False), "none"],
                      ["none"] * 3)
    assert waits == [first, first * 2, ytdlp_mod.CHECK_INTERVAL_SECONDS]
    # the override is the editor's to fix and nothing here touches it:
    # retrying it sooner cannot help, so it keeps the daily cadence
    waits = _run_loop(monkeypatch, [("checked", False)] * 2, ["none"] * 2)
    assert waits == [ytdlp_mod.CHECK_INTERVAL_SECONDS] * 2


def test_an_installed_but_unreadable_binary_is_rechecked_soon(monkeypatch):
    # Through the real ensure(): the install lands, the first --version times
    # out (a cold binary under an AV scan), and the next pass reads it.
    mgr = ytdlp_mod.YtDlpManager({"ytdl_local_downloads": True})
    monkeypatch.setattr(type(mgr), "enabled", property(lambda self: True))
    monkeypatch.setattr(type(mgr), "override_path", property(lambda self: ""))
    versions = iter([None, None, "2026.09.20", "2026.09.20"])
    monkeypatch.setattr(ytdlp_mod, "version", lambda **kw: next(versions))
    monkeypatch.setattr(mgr, "install", lambda: True)
    monkeypatch.setattr(mgr, "fetch_min_version", lambda: None)
    monkeypatch.setattr(mgr, "_enforce_max_age", lambda current, floor: None)
    ok_side = {"ok": True, "action": "none", "message": "none"}
    monkeypatch.setattr(sidecar_tools, "ensure", lambda *a, **k: ok_side)
    seen = []
    real_ensure = mgr.ensure

    def recording_ensure(min_version=None):
        status = real_ensure(min_version)
        seen.append((status["action"], status["ok"]))
        return status

    monkeypatch.setattr(mgr, "ensure", recording_ensure)
    waits = _Waits(2)
    mgr._stop_event = waits
    mgr._loop()
    assert seen == [("installed", False), ("none", True)]
    # HEAD waited the daily interval after the unreadable install
    assert waits.waits[1] == ytdlp_mod.FAILED_RETRY_FIRST_SECONDS
    assert waits.waits[2] == ytdlp_mod.CHECK_INTERVAL_SECONDS


# ---------------------------------------------------------------------------
# ui-copy-4 (c-ytdl's half): the vocabulary scan over this group's modules
# ---------------------------------------------------------------------------

# NOTICE_TEXT is the legal notice, pinned to TEXT_VERSION and kept word for
# word in step with ytdlweb.attestation.NOTICE_TEXT (DRAFT FOR COUNSEL): its
# wording changes with a version bump on both sides, never in a copy sweep.
_ALLOWED = {"ytdl_attestation.py": {"NOTICE_TEXT"}}

C_YTDL_MODULES = ("ytdl_executor.py", "ytdl_server.py", "ytdl_common.py",
                  "ytdl_cookies.py", "ytdl_attestation.py", "youtube_import.py",
                  "ytdlp_manager.py")


@pytest.mark.parametrize("name", C_YTDL_MODULES)
def test_no_retired_word_in_a_ytdl_sentence(name):
    from ccsync_companion import ytdl_attestation
    exempt = {getattr(ytdl_attestation, attr)
              for attr in _ALLOWED.get(name, ())}
    bad = []
    for text in vocab._sentences(vocab.SRC / name):
        if text in vocab.VOCABULARY_ALLOWED or text in exempt:
            continue
        found = vocab._WORD_RE.findall(text)
        if found:
            bad.append((sorted(set(w.lower() for w in found)), text))
    assert not bad, f"{name} says a retired word to an editor: {bad}"


def test_the_capability_reasons_say_computer():
    for reason in (ex.REASON_NO_DASHBOARD, ex.REASON_NO_EDITOR,
                   ex.REASON_NO_IDENTITY, ex.REASON_NO_FFMPEG,
                   ex.REASON_TREE_ABSENT):
        assert "machine" not in reason and "computer" in reason
        assert "—" not in reason


# ---------------------------------------------------------------------------
# Owed round (2026-09-25)
# ---------------------------------------------------------------------------
# logic-ytdl-jobs-3 (from music-ytdl): a claim refused for a reason about THIS
# computer is said to the page's hand-back watcher; the ordinary refusals stay
# quiet.

from test_ytdl_executor import FakeFleet, manifest_for  # noqa: E402


def _refused(tmp_path, ytdlp, status, body):
    fleet = FakeFleet(manifest_for())
    fleet.claim_status = status
    fleet.claim_body = body
    deps = make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp)
    job = run_job(deps)
    assert len(fleet.calls) == 1 and ytdlp.calls == []
    return ex.progress_row(job.snapshot())


@pytest.mark.parametrize("status,detail,words", [
    (403, {"detail": "you have not accepted the YouTube download terms.",
           "reason": "attestation", "version": 1}, "download terms"),
    (403, {"detail": "yt-dlp 2020.01.01 is older than the fleet minimum "
           "2026.08.01", "reason": "ytdlp_version",
           "min_ytdlp_version": "2026.08.01"}, "2026.08.01"),
    (403, {"detail": "missing or invalid X-CCSync-Token"}, "sign-in"),
    # An older server's bare 403 string: no reason code, still the
    # credential shape, so it IS said.
    (403, "no", "sign-in"),
    (401, "not signed in", "sign-in"),
    # Review round 2026-09-25: routes_fleet's own identity refusals carry a
    # reason code. 'identity' is the expired 30-day token, a retired key or
    # a deleted user - the commonest refusal of all.
    (403, {"detail": "a valid X-CCSync-Identity is required: sign in again "
           "from the CC Sync tray", "reason": "identity"}, "sign-in"),
    (403, {"detail": "this report token belongs to a different editor",
           "reason": "identity_mismatch"}, "sign-in"),
    (409, {"detail": "editor2 is already downloading this job on DESK-A",
           "claimed_by": "editor2", "claimed_machine": "m1"}, "DESK-A"),
    (410, {"detail": "template skew", "reason": "template_version"},
     "names downloaded clips"),
    (410, {"detail": "sidecar skew", "reason": "sidecar_version"},
     "clip credits"),
    (410, {"detail": "this job is 2160p, which that computer does not run",
           "reason": "out_of_scope", "quality": "2160p"}, "2160p"),
])
def test_a_refusal_about_this_computer_is_handed_back_in_words(
        tmp_path, ytdlp, status, detail, words):
    row = _refused(tmp_path, ytdlp, status, {"detail": detail})
    assert row["phase"] == "handed_back"
    reason = row["handed_back_reason"]
    assert words in reason
    assert "—" not in reason and "machine" not in reason.lower()
    if status != 409:
        assert "The server is downloading these clips." in reason


@pytest.mark.parametrize("status,body", [
    # Another editor's live lease is theirs, legitimately.
    (409, {"detail": {"detail": "sam is already downloading this job",
                      "claimed_by": "sam"}}),
    (410, {"detail": {"detail": "this job is done, not downloading",
                      "reason": "phase"}}),
    (410, {"detail": {"detail": "cancelled", "reason": "cancelled"}}),
    (410, {"detail": {"detail": "server", "reason": "created_widened"}}),
    (410, {"detail": {"detail": "pinned", "reason": "mode_lock"}}),
    (410, {"detail": {"detail": "race", "reason": "race"}}),
    (500, {"detail": "boom"}),
    # The server is missing its own secret: nothing this computer or its
    # editor can do about it, so it is not put to them.
    (403, {"detail": {"detail": "identity is not configured",
                      "reason": "identity_unconfigured"}}),
    # A reason code this build does not know is not guessed at.
    (403, {"detail": {"detail": "something new", "reason": "brand_new"}}),
])
def test_an_ordinary_refusal_stays_quiet(tmp_path, ytdlp, status, body):
    row = _refused(tmp_path, ytdlp, status, body)
    assert row["phase"] == "finished"
    assert row["handed_back_reason"] is None


def test_an_unreachable_dashboard_is_still_quiet(tmp_path, ytdlp):
    fleet = FakeFleet(manifest_for())
    fleet.transport_error = True
    job = run_job(make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp))
    assert job.snapshot()["handed_back_reason"] is None


# bug-wire-7 (from c-broll-music): the ytdl header carries the minted
# machine id, and one that cannot be a Latin-1 header value is simply not
# sent (34a3c8f, _header_safe); the body field still carries it. Guard only.

def test_a_non_latin1_machine_id_never_reaches_a_header(tmp_path, ytdlp,
                                                        monkeypatch):
    monkeypatch.setattr(ex.machine_mod, "machine_id", lambda *a, **k: "剪輯-PC")
    fleet = FakeFleet(manifest_for())
    fleet.claim_status = 410
    fleet.claim_body = {"detail": {"detail": "x", "reason": "phase"}}
    run_job(make_deps(tmp_path, fleet=fleet, ytdlp=ytdlp))
    _method, _path, body, headers = fleet.calls[0]
    assert "X-CCSync-Machine" not in headers
    for value in headers.values():
        str(value).encode("latin-1")
    assert body["machine_id"] == "剪輯-PC"
