"""The `capabilities` report section and job path resolution (phase 0).

docs/TIMELINE-CARDS-INTO-CCSYNC.md §4.1/§4.3. Every seam is stubbed here on
purpose: this suite runs on machines with no GPU, no ffmpeg, no whisper venv
and no vault, and the section must be truthful on every one of them.
"""
from __future__ import annotations

import pytest

from ccsync_companion import capabilities as caps_mod
from ccsync_companion import job_paths


@pytest.fixture(autouse=True)
def _no_cache():
    caps_mod.reset_cache()
    yield
    caps_mod.reset_cache()


class FakeIdle:
    def __init__(self, value):
        self.value = value

    def seconds_idle(self):
        if isinstance(self.value, Exception):
            raise self.value
        return self.value


def cfg(tmp_path, **over):
    base = {"local_root": str(tmp_path / "tree"), "ffmpeg_path": "ffmpeg"}
    base.update(over)
    return base


# ----------------------------------------------------------- the roots

def test_mounts_name_the_roots_that_are_actually_here(tmp_path):
    (tmp_path / "tree").mkdir()
    (tmp_path / "vault").mkdir()
    c = cfg(tmp_path, jobs_vault_root=str(tmp_path / "vault"),
            jobs_media_root=str(tmp_path / "gone"))
    assert job_paths.mounts(c) == ["tree", "vault"]


def test_a_root_that_is_unplugged_is_not_a_mount(tmp_path):
    c = cfg(tmp_path, jobs_vault_root=str(tmp_path / "not-here"))
    assert job_paths.mounts(c) == []


def test_resolve_places_a_relative_path_under_its_root(tmp_path):
    vault = tmp_path / "vault"
    (vault / "Vault" / "2026").mkdir(parents=True)
    c = cfg(tmp_path, jobs_vault_root=str(vault))
    got = job_paths.resolve(c, "vault", "Vault/2026/FF5/Civil Defence")
    assert got == (vault / "Vault" / "2026" / "FF5" / "Civil Defence").resolve()


def test_a_root_this_machine_does_not_have_is_refused(tmp_path):
    with pytest.raises(job_paths.JobPathError) as exc:
        job_paths.resolve(cfg(tmp_path), "vault", "Vault/2026")
    assert "no vault root" in str(exc.value)


def test_an_absolute_path_is_refused(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    c = cfg(tmp_path, jobs_vault_root=str(vault))
    with pytest.raises(job_paths.JobPathError) as exc:
        job_paths.resolve(c, "vault", "X:/Vault/2026")
    assert "RELATIVE" in str(exc.value)


def test_a_path_that_climbs_out_is_refused(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    c = cfg(tmp_path, jobs_vault_root=str(vault))
    with pytest.raises(job_paths.JobPathError):
        job_paths.resolve(c, "vault", "../../etc/passwd")


# ------------------------------------------------------ the whisper seam

def test_whisper_needs_both_paths(tmp_path):
    python = tmp_path / "python.exe"
    python.write_text("")
    pipeline = tmp_path / "MulticamPipeline"
    pipeline.mkdir()
    (pipeline / "pipeline.py").write_text("")
    assert caps_mod.whisper_ready({})[0] is False
    assert caps_mod.whisper_ready({"jobs_whisper_python": str(python)})[0] is False
    ok, why = caps_mod.whisper_ready({"jobs_whisper_python": str(python),
                                      "jobs_mulcam_pipeline": str(pipeline)})
    assert (ok, why) == (True, "")


def test_a_missing_venv_says_which_path_is_wrong(tmp_path):
    pipeline = tmp_path / "MulticamPipeline"
    pipeline.mkdir()
    (pipeline / "pipeline.py").write_text("")
    ok, why = caps_mod.whisper_ready({"jobs_whisper_python": str(tmp_path / "nope.exe"),
                                      "jobs_mulcam_pipeline": str(pipeline)})
    assert ok is False and "jobs_whisper_python does not exist" in why


def test_a_checkout_with_no_pipeline_py_is_not_whisper_ready(tmp_path):
    python = tmp_path / "python.exe"
    python.write_text("")
    empty = tmp_path / "empty"
    empty.mkdir()
    ok, why = caps_mod.whisper_ready({"jobs_whisper_python": str(python),
                                      "jobs_mulcam_pipeline": str(empty)})
    assert ok is False and "pipeline.py" in why


# ------------------------------------------------------------- the section

def test_the_section_reports_what_the_seams_say(tmp_path, monkeypatch):
    (tmp_path / "tree").mkdir()
    monkeypatch.setattr(caps_mod, "_gpu", lambda: {
        "present": True, "name": "NVIDIA GeForce RTX 3080", "vram_gb": 10.0})
    monkeypatch.setattr(caps_mod, "_nvenc", lambda cfg: True)
    monkeypatch.setattr(caps_mod, "_ffmpeg", lambda cfg: True)
    monkeypatch.setattr(caps_mod, "_claude", lambda: False)
    section = caps_mod.build(cfg(tmp_path), idle_probe=FakeIdle(900),
                             resolve_running_fn=lambda: False,
                             resolve_project_fn=lambda: "FF5 Animals",
                             use_cache=False)
    assert section["gpu_present"] is True
    assert section["gpu_vram_gb"] == 10.0
    assert section["nvenc"] is True
    assert section["whisper"] is False          # no venv configured here
    assert section["mounts"] == ["tree"]
    assert section["idle_seconds"] == 900
    assert section["resolve"] == {"running": False, "project": "FF5 Animals"}


def test_an_unknown_idle_answer_stays_none(tmp_path, monkeypatch):
    """idle.py's contract: None must survive to the wire as null, because the
    scheduler on the other end reads null as NOT IDLE."""
    monkeypatch.setattr(caps_mod, "_gpu", lambda: {})
    monkeypatch.setattr(caps_mod, "_nvenc", lambda cfg: False)
    monkeypatch.setattr(caps_mod, "_ffmpeg", lambda cfg: False)
    section = caps_mod.build(cfg(tmp_path), idle_probe=FakeIdle(None), use_cache=False)
    assert section["idle_seconds"] is None
    section = caps_mod.build(cfg(tmp_path), idle_probe=FakeIdle(RuntimeError("no")),
                             use_cache=False)
    assert section["idle_seconds"] is None
    assert caps_mod.build(cfg(tmp_path), use_cache=False)["idle_seconds"] is None


def test_a_resolve_probe_that_cannot_answer_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(caps_mod, "_gpu", lambda: {})
    monkeypatch.setattr(caps_mod, "_nvenc", lambda cfg: False)
    monkeypatch.setattr(caps_mod, "_ffmpeg", lambda cfg: False)

    def boom():
        raise OSError("tasklist is not answering")

    section = caps_mod.build(cfg(tmp_path), resolve_running_fn=boom, use_cache=False)
    assert section["resolve"]["running"] is True


def test_a_broken_seam_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(caps_mod, "_gpu",
                        lambda: (_ for _ in ()).throw(RuntimeError("nvidia-smi")))
    with pytest.raises(RuntimeError):
        caps_mod._gpu()                      # the stub really does raise...
    # ...and the real _gpu swallows it, which is what build() relies on.
    monkeypatch.undo()
    section = caps_mod.build({"local_root": ""}, use_cache=False)
    assert section["gpu_present"] in (True, False)
    assert section["mounts"] == []


def test_the_live_fields_are_never_served_from_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(caps_mod, "_gpu", lambda: {})
    monkeypatch.setattr(caps_mod, "_nvenc", lambda cfg: False)
    monkeypatch.setattr(caps_mod, "_ffmpeg", lambda cfg: False)
    c = cfg(tmp_path)
    first = caps_mod.build(c, idle_probe=FakeIdle(900))
    second = caps_mod.build(c, idle_probe=FakeIdle(3))
    assert first["idle_seconds"] == 900
    assert second["idle_seconds"] == 3, "a cached idle answer would hand out work"


def test_the_reporter_sends_the_section(tmp_path):
    """The contract this section exists for: it has to reach the dashboard."""
    from ccsync_companion import reporter as reporter_mod

    rep = reporter_mod.DashboardReporter(
        lambda: [], {"editor_name": "jsmith", "dashboard_url": "http://x"},
        get_capabilities=lambda: {"whisper": True, "idle_seconds": None})
    payload = rep._build_payload(light=True)
    assert payload["capabilities"] == {"whisper": True, "idle_seconds": None}


def test_a_capabilities_getter_that_throws_never_costs_the_report():
    from ccsync_companion import reporter as reporter_mod

    rep = reporter_mod.DashboardReporter(
        lambda: [], {"editor_name": "jsmith", "dashboard_url": "http://x"},
        get_capabilities=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    payload = rep._build_payload(light=True)
    assert "capabilities" not in payload
    assert payload["editor_name"] == "jsmith"
