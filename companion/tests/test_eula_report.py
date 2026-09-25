"""LG-5 on the companion: the `eula` report section.

docs/LEGAL_GAP_FEATURES_PLAN.md section 5 (2026-09-25). The dashboard shows
which licence each computer accepted. What this side must guarantee: the
section is the on-disk record's three facts and nothing else (no path, no
text), it is absent when there is no usable record ("not reported", never
"not accepted"), and it rides heavy reports only.
"""
from __future__ import annotations

import json

from ccsync_companion import eula as eula_mod
from ccsync_companion import reporter as reporter_mod


def _write(path, data):
    path.write_text(json.dumps(data) if not isinstance(data, str) else data,
                    encoding="utf-8")
    return path


def test_the_block_is_the_three_facts_and_nothing_else(tmp_path):
    path = _write(tmp_path / "eula_accepted.json", {
        "version": "1.1", "accepted_at": "2026-09-25T09:00:00+00:00",
        "eula_sha256": "a" * 64, "installer_path": "C:/Users/x/Downloads/setup.exe"})
    block = eula_mod.report_block(path)
    assert block == {"version": "1.1", "accepted_at": "2026-09-25T09:00:00+00:00",
                     "eula_sha256": "a" * 64}
    assert set(block) == set(eula_mod.REPORT_KEYS)


def test_no_record_or_an_unusable_one_is_none(tmp_path):
    assert eula_mod.report_block(tmp_path / "missing.json") is None
    assert eula_mod.report_block(_write(tmp_path / "bad.json", "{not json")) is None
    assert eula_mod.report_block(_write(tmp_path / "list.json", [1, 2])) is None
    assert eula_mod.report_block(_write(tmp_path / "nover.json", {"accepted_at": "x"})) is None


def test_a_hand_edited_record_is_capped(tmp_path):
    path = _write(tmp_path / "e.json", {"version": "9" * 500, "accepted_at": "x" * 500,
                                        "eula_sha256": "f" * 500})
    block = eula_mod.report_block(path)
    assert len(block["version"]) <= 32
    assert len(block["accepted_at"]) <= 64
    assert len(block["eula_sha256"]) <= 64


def test_the_default_path_is_the_acceptance_record():
    # conftest accepts the EULA for every test (_eula_already_accepted).
    block = eula_mod.report_block()
    assert block is not None
    assert block["version"] == eula_mod.read_acceptance()["version"]


class _Status:
    def __init__(self):
        self.name, self.state, self.queued, self.transferring = "a", "idle", 0, 0
        self.last_error = self.last_sync = self.detail = self.current_project = None
        self.bytes_done = self.bytes_total = self.speed_bps = self.eta_seconds = None
        self.transfers = []


def _reporter(get_eula):
    return reporter_mod.DashboardReporter(
        lambda: [_Status()], {"dashboard_url": "https://dash.example"},
        get_site=lambda: None, get_eula=get_eula)


def test_it_rides_heavy_reports_only():
    rep = _reporter(lambda: {"version": "1.1", "accepted_at": "t", "eula_sha256": "s"})
    assert rep._build_payload(light=False)["eula"]["version"] == "1.1"
    assert "eula" not in rep._build_payload(light=True)


def test_no_record_means_no_section_never_a_false_one():
    rep = _reporter(lambda: None)
    assert "eula" not in rep._build_payload(light=False)


def test_a_failing_getter_costs_the_section_not_the_report():
    def boom():
        raise OSError("disk")
    payload = _reporter(boom)._build_payload(light=False)
    assert "eula" not in payload
    assert payload["lanes"]
