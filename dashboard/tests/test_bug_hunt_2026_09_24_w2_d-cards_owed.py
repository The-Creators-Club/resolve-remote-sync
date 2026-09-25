"""Wave 2 of the 2026-09-24 hunt's fix pass, the owed round for d-cards /
d-api: bug-comp-media-3's optional half.

The companion refuses an `out_stem` that is no file name on any machine at
claim time (job_paths.safe_stem, retryable=False). POST /api/v1/jobs now
refuses the same four shapes before the job is queued, and deliberately not
the Windows-only ':' and '\\'. The refusal tests fail on HEAD 4462a2a because
the POST answered 200 and queued the job.
"""
from __future__ import annotations

import pytest

from ccsync_dashboard import jobs as jobs_mod

from test_jobs import admin_client, env  # noqa: F401
from test_jobs_contract import companion

MEDIA_INPUTS = {"root": "vault", "rel_path": "FF5/Rushes/A001.mov",
                "out_root": "cards", "out_rel": "ep/proxies"}

REFUSED = ["C:/Windows/Temp/x", "/etc/cron.d/x", "../../../x",
           "Interview 1/2", "..", " . ", "a\x00b", "tab\there", "del\x7f"]
ALLOWED = ["Interview 3 (wide) - v2.final", "Q&A: Ruskin", "back\\slash",
           "C:x", "  padded  "]


def _post(client, kind, stem):
    return client.post("/api/v1/jobs", json={
        "kind": kind, "inputs": dict(MEDIA_INPUTS, out_stem=stem)})


def _count(conn):
    return conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]


@pytest.mark.parametrize("kind", ["proxy-480p", "audio-extract", "peaks"])
@pytest.mark.parametrize("stem", REFUSED)
def test_a_stem_no_machine_can_write_is_refused_at_submit(env, kind, stem):
    client, conn, _settings = env
    admin_client(client)
    r = _post(client, kind, stem)
    assert r.status_code == 422, r.text
    assert "out_stem" in r.json()["detail"]
    assert "\u2014" not in r.json()["detail"]
    assert _count(conn) == 0


@pytest.mark.parametrize("stem", ALLOWED)
def test_a_windows_only_or_ordinary_name_is_still_queued(env, stem):
    # ':' and '\\' are plain on a Mac and on the dashboard's Linux engine,
    # which is where a job every Windows machine gave back gets made.
    client, conn, _settings = env
    admin_client(client)
    r = _post(client, "proxy-480p", stem)
    assert r.status_code == 200, r.text
    assert _count(conn) == 1


@pytest.mark.parametrize("stem", [None, "", "   "])
def test_a_missing_stem_falls_back_to_the_source_and_is_queued(env, stem):
    client, conn, _settings = env
    admin_client(client)
    inputs = dict(MEDIA_INPUTS)
    if stem is not None:
        inputs["out_stem"] = stem
    r = client.post("/api/v1/jobs", json={"kind": "peaks", "inputs": inputs})
    assert r.status_code == 200, r.text


def test_a_kind_that_has_no_stem_is_not_judged_by_one():
    assert jobs_mod.out_stem_problem("whisper", {"out_stem": "a/b"}) is None


def test_the_submit_rule_is_the_companions_fleet_wide_rule():
    """Both directions: a name the dashboard refuses is one no machine would
    write, and a name it lets through is one a non-Windows claimant writes."""
    _caps, job_paths, _runner = companion()
    for stem in REFUSED:
        assert jobs_mod.out_stem_problem("proxy-480p", {"out_stem": stem})
        with pytest.raises(job_paths.JobPathError) as err:
            job_paths.safe_stem(stem.strip(), windows=False)
        assert err.value.retryable is False
    for stem in ALLOWED:
        assert jobs_mod.out_stem_problem("proxy-480p", {"out_stem": stem}) is None
        assert job_paths.safe_stem(stem.strip(), windows=False) == stem.strip()
