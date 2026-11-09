"""The volume report: this computer's drives, posted to the Footage Sorter's ledger.

footage-sorter docs/LEDGER-BROWSER-DESIGN.md, "The companion" item 1. No drives and no dashboard: the volume
lister, the HTTP call and the clock are fakes.
"""
from __future__ import annotations

import sys

import pytest

from ccsync_companion import sorter_cards, sorter_volumes
from ccsync_companion.sorter_volumes import VolumeReporter

GIB = 1024 ** 3


@pytest.fixture(autouse=True)
def _clean_registry():
    sorter_cards._busy.clear()
    yield
    sorter_cards._busy.clear()


def vol(serial="AAAA0001", label="FIELD", drive="D:", capacity=1000 * GIB, free=500 * GIB, removable=False,
        system=False, fs="NTFS"):
    return {"serial": serial, "label": label, "drive": drive, "root": drive + "\\", "capacity": capacity,
            "free": free, "removable": removable, "fs": fs,
            "drive_type": "removable" if removable else "fixed", "system": system}


class Rig:
    def __init__(self, vols=None, **cfg):
        self.vols = list(vols if vols is not None else [vol()])
        self.t = 0.0
        self.posts = []
        self.status = 200
        self.answer = {"scan": []}
        self.scopes = []
        base = {"dashboard_url": "http://dash.example", "dashboard_token": "tok"}
        base.update(cfg)
        self.r = VolumeReporter(base, request_fn=self.request, identity_token_fn=lambda: "ident",
                                volumes_fn=self.volumes, clock=lambda: self.t, machine_name="razer")

    def volumes(self, scope, skip=()):
        self.scopes.append((scope, set(skip)))
        return [dict(v) for v in self.vols if v["root"] not in skip]

    def request(self, method, url, body, headers, timeout):
        if isinstance(self.status, Exception):
            raise self.status
        self.posts.append((method, url, body, headers))
        return self.status, self.answer

    def tick(self, advance=0.0):
        self.t += advance
        return self.r.tick()


def test_the_first_tick_posts_every_drive_with_its_facts():
    rig = Rig([vol(), vol("C0DE0002", "Windows", "C:", system=True), vol("5D5D0003", "CIB_D1", "E:", removable=True, fs="exFAT")])
    assert rig.tick() == 200
    method, url, body, headers = rig.posts[0]
    assert (method, url) == ("POST", "http://dash.example/sorter/agent/volumes")
    assert headers["X-CCSync-Token"] == "tok" and headers["X-CCSync-Identity"] == "ident"
    assert body["machine"] == "razer" and body["digest"]
    by = {v["serial"]: v for v in body["volumes"]}
    assert set(by) == {"AAAA0001", "C0DE0002", "5D5D0003"}
    assert by["AAAA0001"] == {"serial": "AAAA0001", "label": "FIELD", "fs": "NTFS", "size": 1000 * GIB,
                              "free": 500 * GIB, "driveType": "fixed", "system": False, "removable": False,
                              "drive": "D:"}
    assert by["C0DE0002"]["system"] is True
    assert by["5D5D0003"]["driveType"] == "removable" and by["5D5D0003"]["fs"] == "exFAT"
    assert rig.scopes[0][0] == "all"                       # fixed drives included


def test_nothing_is_posted_again_while_nothing_changes():
    rig = Rig()
    rig.tick()
    for _ in range(20):
        assert rig.tick(10) is None
    assert len(rig.posts) == 1


def test_it_resends_every_five_minutes_changed_or_not():
    rig = Rig()
    rig.tick()
    assert rig.tick(299) is None
    assert rig.tick(2) == 200 and len(rig.posts) == 2


def test_a_drive_plugged_in_or_pulled_is_posted_at_once_but_not_faster_than_the_gap():
    rig = Rig()
    rig.tick()
    rig.vols.append(vol("5D5D0003", "CIB_D1", "E:", removable=True))
    assert rig.tick(1) is None                             # a loose port chattering: wait out the gap
    assert rig.tick(sorter_volumes.CHANGE_GAP_SECONDS) == 200
    assert {v["serial"] for v in rig.posts[-1][2]["volumes"]} == {"AAAA0001", "5D5D0003"}
    rig.vols.pop()
    assert rig.tick(sorter_volumes.CHANGE_GAP_SECONDS) == 200
    assert {v["serial"] for v in rig.posts[-1][2]["volumes"]} == {"AAAA0001"}


def test_a_relabelled_or_reformatted_drive_is_a_change():
    rig = Rig()
    rig.tick()
    rig.vols[0]["label"] = "FIELD2"
    assert rig.tick(20) == 200
    rig.vols[0]["fs"] = "exFAT"
    assert rig.tick(20) == 200


def test_free_space_alone_is_debounced_and_needs_a_real_move():
    rig = Rig()
    rig.tick()
    rig.vols[0]["free"] -= 10 * GIB                        # a copy running: moves every tick
    for _ in range(5):
        assert rig.tick(10) is None                        # within the minute: nothing
    rig.vols[0]["free"] -= 10 * GIB
    assert rig.tick(20) == 200                             # a real move, a minute on
    assert rig.posts[-1][2]["volumes"][0]["free"] == 480 * GIB
    rig.vols[0]["free"] -= 1000                            # a few KB: never worth a post
    assert rig.tick(120) is None
    assert len(rig.posts) == 2


def test_free_space_rides_a_post_that_goes_out_for_another_reason():
    rig = Rig()
    rig.tick()
    rig.vols[0]["free"] -= 100                             # nothing worth a post...
    rig.tick(sorter_volumes.RESEND_SECONDS + 1)            # ...until the five-minute resend carries it
    assert rig.posts[-1][2]["volumes"][0]["free"] == 500 * GIB - 100


def test_the_digest_ignores_free_space():
    a = [sorter_volumes.to_wire(vol(free=1))]
    b = [sorter_volumes.to_wire(vol(free=2))]
    assert sorter_volumes.structure_digest(a) == sorter_volumes.structure_digest(b)
    c = [sorter_volumes.to_wire(vol(label="X"))]
    assert sorter_volumes.structure_digest(a) != sorter_volumes.structure_digest(c)


def test_a_volume_being_copied_from_is_not_touched_and_is_reported_as_last_seen():
    rig = Rig([vol("5D5D0003", "SD-3", "L:", removable=True)])
    rig.tick()
    with sorter_cards.ingest_busy("5D5D0003", "L:\\"):
        rig.vols[0]["free"] = 1                            # the lister must not even be asked about it
        rig.tick(sorter_volumes.RESEND_SECONDS + 1)
    scope, skip = rig.scopes[-1]
    assert "L:\\" in skip
    sent = rig.posts[-1][2]["volumes"]
    assert [v["serial"] for v in sent] == ["5D5D0003"] and sent[0]["free"] == 500 * GIB


@pytest.mark.parametrize("status,backoff", [(404, 600), (503, 600), (403, 300), (500, 60)])
def test_a_refusal_backs_off_and_a_site_without_a_sorter_is_quiet(status, backoff, caplog):
    rig = Rig()
    rig.status = status
    with caplog.at_level("INFO", logger="ccsync.sortervolumes"):
        assert rig.tick() == status
    assert rig.tick(backoff - 5) is None and len(rig.posts) == 1
    rig.status = 200
    assert rig.tick(10) == 200
    if status in (404, 503):
        assert not [r for r in caplog.records if r.levelname in ("WARNING", "ERROR")]


def test_an_unreachable_dashboard_retries_in_half_a_minute():
    rig = Rig()
    rig.status = OSError("down")
    assert rig.tick() is None
    rig.status = 200
    assert rig.tick(10) is None
    assert rig.tick(25) == 200


def test_it_does_nothing_without_a_dashboard_a_token_or_when_off():
    assert Rig(dashboard_url="").tick() is None
    assert Rig(dashboard_token="").tick() is None
    off = Rig(sorter_ledger_enabled=False)
    assert off.tick() is None and off.posts == []
    off.r.start()
    assert off.r._thread is None


@pytest.mark.parametrize("raw,want", [(True, True), (False, False), ("false", False), ("0", False), ("yes", True), ("", False)])
def test_the_switch_tolerates_a_hand_edited_string(raw, want):
    assert sorter_volumes.enabled({"sorter_ledger_enabled": raw}) is want
    assert sorter_volumes.enabled({}) is True


def test_the_answer_is_kept_for_the_log_and_never_needed():
    rig = Rig()
    rig.answer = {"scan": [{"volumeId": "vol:AAAA0001", "roots": [""], "jobId": 9}]}
    assert rig.tick() == 200 and rig.r.last_answer == rig.answer
    rig2 = Rig()
    rig2.answer = None                                     # an old dashboard's empty body
    assert rig2.tick() == 200


def test_the_loop_runs_and_stops():
    rig = Rig()
    rig.r.scan_seconds = 1
    rig.r.start()
    try:
        import time
        deadline = time.time() + 5
        while not rig.posts and time.time() < deadline:
            time.sleep(0.02)
    finally:
        rig.r.stop()
    assert rig.posts and rig.r._thread is None


# ----------------------------------------------------- the lister itself

def test_list_volumes_all_carries_the_report_fields_on_this_machine():
    vols = sorter_cards.list_volumes("all")
    if sys.platform not in ("win32", "darwin"):
        assert vols == []
        return
    assert vols, "this machine has at least one drive"
    for v in vols:
        assert set(v) >= {"serial", "label", "drive", "root", "capacity", "free", "removable", "fs", "drive_type", "system"}
        assert v["drive_type"] in ("fixed", "removable") and isinstance(v["system"], bool)
        assert v["serial"] and v["capacity"] >= 0
    assert sum(1 for v in vols if v["system"]) <= 1


def test_list_volumes_removable_scope_has_no_fixed_drives():
    for v in sorter_cards.list_volumes("removable"):
        assert v["removable"] is True and v["drive_type"] == "removable"


# ----------------------------------------------------- capability and config switches

def test_the_capability_follows_the_switch(tmp_path):
    from ccsync_companion import capabilities as caps_mod
    caps_mod.reset_cache()
    on = caps_mod.build({"local_root": str(tmp_path), "ffmpeg_path": "ffmpeg"}, use_cache=False)
    assert on["sorter_ledger"] is True and on["sorter_cards"] is True
    off = caps_mod.build({"local_root": str(tmp_path), "ffmpeg_path": "ffmpeg", "sorter_ledger_enabled": False},
                         use_cache=False)
    assert off["sorter_ledger"] is False and off["sorter_cards"] is True        # independent of the card switch
    assert "ledger-scan" in caps_mod.KNOWN_KINDS and caps_mod.job_kinds({"jobs_kinds": "ledger-scan"}) == ["ledger-scan"]


def test_the_config_defaults_carry_the_switches():
    from ccsync_companion import config as config_mod
    d = config_mod.DEFAULTS
    assert d["sorter_ledger_enabled"] is True and d["sorter_ledger_volume_seconds"] == 10
    assert d["ledger_outbox_path"] == "" and d["ledger_mirror_path"] == ""
