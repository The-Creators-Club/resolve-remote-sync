"""The camera cards this computer reports to the Footage Sorter.

Protocol: footage-sorter docs/DASHBOARD-MODULE-PLAN.md, "Card ingest through
the companion", step 1. Fake card trees on tmp_path stand in for the readers
and a fake dashboard for the POST, so this runs on any machine.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from ccsync_companion import capabilities, job_paths, sorter_cards


def touch(root: Path, rel: str, data: bytes = b"x") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def wav_bytes(seconds: float, rate: int = 48000) -> bytes:
    n = int(seconds * rate * 2)
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    return (b"RIFF" + struct.pack("<I", 36 + n) + b"WAVE" + b"fmt "
            + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", n) + b"\0" * n)


# --------------------------------------------------------------- detection

def test_a_sony_card(tmp_path):
    touch(tmp_path, "PRIVATE/M4ROOT/CLIP/C0001.MP4")
    assert sorter_cards.classify(tmp_path) == "sony"


def test_an_empty_sony_card_is_still_a_sony_card(tmp_path):
    (tmp_path / "PRIVATE/M4ROOT/CLIP").mkdir(parents=True)
    assert sorter_cards.classify(tmp_path) == "sony"


def test_sony_outranks_a_drone_structure_on_the_same_card(tmp_path):
    touch(tmp_path, "PRIVATE/M4ROOT/CLIP/C0001.MP4")
    touch(tmp_path, "DCIM/100MEDIA/DJI_0001.MP4")
    assert sorter_cards.classify(tmp_path) == "sony"


def test_a_blackmagic_drive_is_bmcc(tmp_path):
    touch(tmp_path, "A001_01.braw")
    assert sorter_cards.classify(tmp_path) == "bmcc"


def test_a_macos_twin_of_a_braw_is_not_one(tmp_path):
    touch(tmp_path, "._A001_01.braw")
    assert sorter_cards.classify(tmp_path) is None


def test_a_drone_card(tmp_path):
    touch(tmp_path, "DCIM/100MEDIA/DJI_0001.MP4")
    assert sorter_cards.classify(tmp_path) == "drone"


def test_dcim_with_no_video_in_a_numbered_media_folder_is_not_a_drone(tmp_path):
    touch(tmp_path, "DCIM/100MEDIA/DJI_0001.JPG")
    touch(tmp_path, "DCIM/Camera/clip.mp4")
    # Not a drone by detect.js's rule; it does hold media, so it is generic.
    assert sorter_cards.classify(tmp_path) == "generic"


@pytest.mark.parametrize("name", ["MIC1 Wireless PRO 01.WAV", "240312_001.wav"])
def test_an_audio_card_by_the_recorders_file_names(tmp_path, name):
    touch(tmp_path, name, wav_bytes(0.1))
    assert sorter_cards.classify(tmp_path) == "audio"


def test_a_wav_with_some_other_name_is_not_audio_but_it_is_media(tmp_path):
    touch(tmp_path, "interview.wav", wav_bytes(0.1))
    assert sorter_cards.classify(tmp_path) == "generic"


def test_a_generic_card_holds_media_the_detectors_do_not_know(tmp_path):
    touch(tmp_path, "100GOPRO/GOPR0001.MP4")
    assert sorter_cards.classify(tmp_path) == "generic"


def test_a_stick_of_documents_is_not_a_card(tmp_path):
    touch(tmp_path, "report.docx")
    touch(tmp_path, "notes/todo.txt")
    assert sorter_cards.classify(tmp_path) is None


def test_an_empty_volume_is_not_a_card(tmp_path):
    assert sorter_cards.classify(tmp_path) is None


def test_media_under_a_recycle_bin_does_not_make_a_card(tmp_path):
    touch(tmp_path, "$RECYCLE.BIN/S-1/old.mp4")
    assert sorter_cards.classify(tmp_path) is None


# ----------------------------------------------------------------- listing

def test_the_listing_has_the_protocols_shape(tmp_path):
    touch(tmp_path, "PRIVATE/M4ROOT/CLIP/fx3_0001.MP4", b"v" * 1000)
    xml = "<NonRealTimeMeta>" + "a" * 6000 + "</NonRealTimeMeta>"
    touch(tmp_path, "PRIVATE/M4ROOT/CLIP/fx3_0001M01.XML", xml.encode())
    touch(tmp_path, "ZOOM0001.WAV", wav_bytes(2.5))
    listing = sorter_cards.list_card(tmp_path)
    assert set(listing) == {"files", "texts", "wav"}
    by_rel = {f[0]: f for f in listing["files"]}
    rel, size, mtime = by_rel["PRIVATE/M4ROOT/CLIP/fx3_0001.MP4"]
    assert size == 1000
    assert isinstance(mtime, float) and mtime > 1e12            # ms since the epoch
    assert set(by_rel) == {"PRIVATE/M4ROOT/CLIP/fx3_0001.MP4",
                           "PRIVATE/M4ROOT/CLIP/fx3_0001M01.XML", "ZOOM0001.WAV"}
    text = listing["texts"]["PRIVATE/M4ROOT/CLIP/fx3_0001M01.XML"]
    assert len(text) == sorter_cards.XML_BYTES and text.startswith("<NonRealTimeMeta>")
    assert listing["wav"] == {"ZOOM0001.WAV": 2.5}


def test_the_listing_skips_what_the_scanner_skips(tmp_path):
    touch(tmp_path, "DCIM/100MEDIA/a.mp4")
    for junk in (".DS_Store", "Thumbs.db", "desktop.ini", "._a.mp4",
                 "$RECYCLE.BIN/x.mp4", "System Volume Information/y.dat",
                 ".Trashes/z.mp4", ".fseventsd/log", "DCIM/.hidden/q.mp4",
                 "DCIM/100MEDIA/._a.mp4"):
        touch(tmp_path, junk)
    names = [f[0] for f in sorter_cards.list_card(tmp_path)["files"]]
    assert names == ["DCIM/100MEDIA/a.mp4"]


def test_describe_makes_the_whole_card_object(tmp_path):
    touch(tmp_path, "PRIVATE/M4ROOT/CLIP/a.MP4")
    card = sorter_cards.describe(
        {"serial": "1038701C", "label": "SD-3", "drive": "L:", "root": str(tmp_path),
         "capacity": 128, "free": 20}, "2026-11-09T02:57:00Z")
    assert {k: card[k] for k in ("serial", "label", "drive", "kind", "capacity",
                                 "free", "detectedAt")} == {
        "serial": "1038701C", "label": "SD-3", "drive": "L:", "kind": "sony",
        "capacity": 128, "free": 20, "detectedAt": "2026-11-09T02:57:00Z"}
    assert card["files"] and "texts" in card and "wav" in card


def test_describe_returns_none_for_not_a_card(tmp_path):
    touch(tmp_path, "readme.txt")
    assert sorter_cards.describe(
        {"serial": "A", "drive": "L:", "root": str(tmp_path)}, "t") is None


# -------------------------------------------------------------------- loop

class Dash:
    def __init__(self, status=200):
        self.status = status
        self.posts: list[tuple[str, dict, dict]] = []

    def request(self, method, url, body, headers, timeout):
        self.posts.append((url, body, headers))
        return self.status, {"ok": True}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_loop(tmp_path, vols, dash=None, clock=None, **cfg_over):
    dash = dash or Dash()
    clock = clock or Clock()
    cfg = {"dashboard_url": "http://dash.example", "dashboard_token": "tok",
           **cfg_over}

    def volumes(scope, skip=()):
        return [v for v in vols() if v["root"] not in skip]

    loop = sorter_cards.SorterCards(
        cfg, request_fn=dash.request, identity_token_fn=lambda: "ident",
        volumes_fn=volumes, clock=clock, machine_name="EDIT-PC")
    return loop, dash, clock


def a_volume(tmp_path, name="card1", serial="1038701C", free=100):
    root = tmp_path / name
    root.mkdir(exist_ok=True)
    return {"serial": serial, "label": "SD-3", "drive": "L:", "root": str(root),
            "capacity": 1000, "free": free, "removable": True}


@pytest.fixture(autouse=True)
def _clean_registry():
    sorter_cards._busy.clear()
    sorter_cards._known_drives.clear()
    yield
    sorter_cards._busy.clear()
    sorter_cards._known_drives.clear()


def test_it_posts_the_full_set_with_the_fleet_credentials(tmp_path):
    vol = a_volume(tmp_path)
    touch(Path(vol["root"]), "PRIVATE/M4ROOT/CLIP/a.MP4")
    loop, dash, _ = make_loop(tmp_path, lambda: [vol])
    assert loop.tick() == 200
    url, body, headers = dash.posts[0]
    assert url == "http://dash.example/sorter/agent/cards"
    assert headers["X-CCSync-Token"] == "tok"
    assert headers["X-CCSync-Identity"] == "ident"
    assert [c["serial"] for c in body["cards"]] == ["1038701C"]
    assert body["cards"][0]["kind"] == "sony"
    assert body["machine"] == "EDIT-PC"


def test_nothing_is_sent_again_until_the_set_changes(tmp_path):
    vol = a_volume(tmp_path)
    touch(Path(vol["root"]), "PRIVATE/M4ROOT/CLIP/a.MP4")
    loop, dash, clock = make_loop(tmp_path, lambda: [vol])
    loop.tick()
    clock.now += 20
    assert loop.tick() is None
    assert len(dash.posts) == 1
    # A clip is added to the card: the free space moves and the sizes change.
    touch(Path(vol["root"]), "PRIVATE/M4ROOT/CLIP/b.MP4", b"yy")
    vol["free"] = 90
    clock.now += 20
    assert loop.tick() == 200
    assert len(dash.posts) == 2
    assert len(dash.posts[1][1]["cards"][0]["files"]) == 2


def test_it_resends_every_five_minutes_while_a_card_is_present(tmp_path):
    vol = a_volume(tmp_path)
    touch(Path(vol["root"]), "PRIVATE/M4ROOT/CLIP/a.MP4")
    loop, dash, clock = make_loop(tmp_path, lambda: [vol])
    loop.tick()
    clock.now += sorter_cards.RESEND_SECONDS - 1
    assert loop.tick() is None
    clock.now += 2
    assert loop.tick() == 200
    assert len(dash.posts) == 2


def test_an_empty_set_is_sent_once_when_the_card_goes_and_then_left_alone(tmp_path):
    vols = [a_volume(tmp_path)]
    touch(Path(vols[0]["root"]), "PRIVATE/M4ROOT/CLIP/a.MP4")
    loop, dash, clock = make_loop(tmp_path, lambda: list(vols))
    loop.tick()
    vols.clear()
    clock.now += 20
    assert loop.tick() == 200
    assert dash.posts[-1][1]["cards"] == []
    for _ in range(3):
        clock.now += 400                      # no card: no 5-minute resend
        assert loop.tick() is None
    assert len(dash.posts) == 2


def test_a_volume_that_is_not_a_card_is_not_reported(tmp_path):
    vol = a_volume(tmp_path)
    touch(Path(vol["root"]), "notes.txt")
    loop, dash, _ = make_loop(tmp_path, lambda: [vol])
    loop.tick()
    assert dash.posts[0][1]["cards"] == []


@pytest.mark.parametrize("status", [404, 503])
def test_a_site_with_no_sorter_is_backed_off_quietly(tmp_path, status):
    vol = a_volume(tmp_path)
    touch(Path(vol["root"]), "PRIVATE/M4ROOT/CLIP/a.MP4")
    loop, dash, clock = make_loop(tmp_path, lambda: [vol], dash=Dash(status))
    assert loop.tick() == status
    clock.now += 60
    assert loop.tick() is None                       # backing off: no post, no read
    assert len(dash.posts) == 1
    clock.now += sorter_cards.NO_SORTER_BACKOFF_SECONDS
    dash.status = 200
    assert loop.tick() == 200


def test_a_refused_post_is_retried_not_marked_sent(tmp_path):
    vol = a_volume(tmp_path)
    touch(Path(vol["root"]), "PRIVATE/M4ROOT/CLIP/a.MP4")
    dash = Dash(500)
    loop, dash, clock = make_loop(tmp_path, lambda: [vol], dash=dash)
    loop.tick()
    dash.status = 200
    clock.now += 120
    assert loop.tick() == 200


def test_the_switch_turns_the_whole_thing_off(tmp_path):
    vol = a_volume(tmp_path)
    touch(Path(vol["root"]), "PRIVATE/M4ROOT/CLIP/a.MP4")
    loop, dash, _ = make_loop(tmp_path, lambda: [vol], sorter_cards_enabled=False)
    assert loop.tick() is None
    loop.start()
    assert loop._thread is None
    assert not dash.posts


def test_no_dashboard_means_nothing_is_read_or_sent(tmp_path):
    vol = a_volume(tmp_path)
    loop, dash, _ = make_loop(tmp_path, lambda: [vol], dashboard_url="")
    assert loop.tick() is None and not dash.posts


def test_a_card_being_copied_from_is_never_read(tmp_path, monkeypatch):
    vol = a_volume(tmp_path)
    touch(Path(vol["root"]), "PRIVATE/M4ROOT/CLIP/a.MP4")
    loop, dash, clock = make_loop(tmp_path, lambda: [vol])
    loop.tick()
    reads = []
    real = sorter_cards.list_card
    monkeypatch.setattr(sorter_cards, "list_card",
                        lambda root: reads.append(root) or real(root))
    vol["free"] = 1                               # would normally force a re-read
    with sorter_cards.ingest_busy(vol["serial"], vol["root"]):
        clock.now += sorter_cards.RESEND_SECONDS + 1
        loop.tick()
        assert not reads
        # ...and the card is still in the set it reports.
        assert [c["serial"] for c in dash.posts[-1][1]["cards"]] == [vol["serial"]]
    clock.now += 20
    loop.tick()
    assert reads                                  # released: read again


# ---------------------------------------------------------------- the pool

def test_the_pool_root_is_a_mount_only_when_set_and_present(tmp_path):
    (tmp_path / "tree").mkdir()
    pool = tmp_path / "pool"
    base = {"local_root": str(tmp_path / "tree")}
    assert "pool" not in job_paths.mounts(base)
    assert "pool" not in job_paths.mounts({**base, "jobs_pool_root": str(pool)})
    pool.mkdir()
    assert job_paths.mounts({**base, "jobs_pool_root": str(pool)}) == ["tree", "pool"]


def test_a_pool_path_is_placed_and_cannot_climb(tmp_path):
    (tmp_path / "pool").mkdir()
    cfg = {"jobs_pool_root": str(tmp_path / "pool")}
    placed = job_paths.resolve(cfg, "pool", "Footage/2026/a.mp4")
    assert placed == (tmp_path / "pool").resolve() / "Footage" / "2026" / "a.mp4"
    with pytest.raises(job_paths.JobPathError):
        job_paths.resolve(cfg, "pool", "../x")


def test_capabilities_report_the_card_ability_only_where_enabled(tmp_path, monkeypatch):
    on = capabilities.build({"sorter_cards_enabled": True}, use_cache=False)
    off = capabilities.build({"sorter_cards_enabled": False}, use_cache=False)
    assert on["sorter_cards"] is True and off["sorter_cards"] is False
    assert {"card-ingest", "drive-copy"} <= set(capabilities.KNOWN_KINDS)
