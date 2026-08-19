"""proxy_scan tests: which originals the rest of the fleet cannot see.

Real tmp_path trees, in test_manifest.py's style -- the walk rules (pruning
Proxy/, the settle window, the AppleDouble sidecars) are exactly the part
that a mocked filesystem would let drift away from the real one. Clips are
aged with os.utime because a file written NOW is inside the settle window by
construction.
"""

from __future__ import annotations

import os
import time

import pytest

from ccsync_companion import proxy_scan

# Comfortably older than the 120 s settle window used throughout.
SETTLED = 3600.0


def _make_project(tmp_path, year="2026", series="FF5", project="Nuclear"):
    from conftest import write_project_marker

    project_dir = tmp_path / "Projects" / year / series / project
    write_project_marker(project_dir, slug=project.lower())
    return project_dir


def _clip(path, size=1000, age=SETTLED, at=None):
    """A settled original of `size` bytes, `age` seconds old.

    `at` pins the mtime to an exact value -- two files created back to back
    are microseconds apart on NTFS, which is enough to decide a sort order
    the caller wanted to be a tie.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    stamp = float(at) if at is not None else time.time() - age
    os.utime(path, (stamp, stamp))
    return path


def _scan(project_dir, **kwargs):
    kwargs.setdefault("min_age_seconds", 120)
    return proxy_scan.scan_project(str(project_dir), **kwargs)


# -- classify_footage ---------------------------------------------------------


@pytest.mark.parametrize(
    "path, expected",
    [
        # The tokenizer edge this design exists for: "yt" IS a substring of
        # "Nayth", and a substring match would drop a whole shoot to 540p.
        (r"P:\Projects\2026\CCT\Nayth Interview\A001.mp4", proxy_scan.KIND_OWN),
        (r"P:\Projects\2026\CCT\Kyoto Trip\clip.mp4", proxy_scan.KIND_OWN),
        # ...and the one whole-component equality would miss: the folder is
        # really called "YouTube Downloads".
        (r"P:\Projects\2026\CCT\YouTube Downloads\ref.mp4", proxy_scan.KIND_PREVIEW),
        (r"P:\Projects\2026\CCT\Downloads\ref.mp4", proxy_scan.KIND_PREVIEW),
        (r"P:\Projects\2026\CCT\yt-dlp\ref.mkv", proxy_scan.KIND_PREVIEW),
        ("/Volumes/T7/Creators_Club/Projects/2026/youtube/ref.mp4",
         proxy_scan.KIND_PREVIEW),
        # Camera extension beats the path tokens outright.
        (r"P:\Projects\2026\CCT\Downloads\A001.mxf", proxy_scan.KIND_OWN),
        (r"P:\Projects\2026\CCT\YouTube Downloads\A001.braw", proxy_scan.KIND_OWN),
        # Nothing to go on -> own footage (the expensive, safe default).
        (r"P:\Projects\2026\CCT\Interviews\Panel\B002.mp4", proxy_scan.KIND_OWN),
        ("", proxy_scan.KIND_OWN),
        (None, proxy_scan.KIND_OWN),
    ],
)
def test_classification_table(path, expected):
    assert proxy_scan.classify_footage(path) == expected


# -- generation_state ---------------------------------------------------------


@pytest.mark.parametrize("ext", [".braw", ".r3d", ".crm", "BRAW", ".BRAW"])
def test_raw_formats_need_resolve(ext):
    """ffmpeg has no decoder for any of these -- counted, never queued."""
    assert proxy_scan.generation_state(ext) == proxy_scan.GEN_NEEDS_RESOLVE


@pytest.mark.parametrize("ext", [".insv", ".360"])
def test_three_sixty_formats_are_skipped(ext):
    assert proxy_scan.generation_state(ext) == proxy_scan.GEN_SKIP


@pytest.mark.parametrize("ext", [".mov", ".mp4", ".mxf", ".mts", ".mkv", "", None])
def test_everything_else_is_generatable(ext):
    assert proxy_scan.generation_state(ext) == proxy_scan.GEN_GENERATE


# -- path helpers -------------------------------------------------------------


def test_expected_proxies_is_proxy_relinks_list(tmp_path):
    from ccsync_companion import proxy_relink

    original = str(tmp_path / "Panel" / "A001.braw")
    assert proxy_scan.expected_proxies(original) == proxy_relink.expected_proxy_paths(
        original
    )


def test_partial_path_is_the_generated_proxy_plus_partial(tmp_path):
    """Bound to GENERATED_EXT rather than spelling the container out: it moved
    from .mp4 to .mov on 2026-08-19 (R14, so BPG can see companion output) and
    a literal here is eight tests that break for no reason next time."""
    original = tmp_path / "Panel" / "A001.mov"
    assert proxy_scan.partial_path(str(original)) == str(
        tmp_path / "Panel" / "Proxy" / f"A001{proxy_scan.GENERATED_EXT}.partial"
    )


def test_the_generated_container_is_one_the_fleet_already_accepts():
    """The switch is only safe because both extensions were proxies all along:
    PROXY_EXTENSIONS is what proxy_scan, proxy_relink and Resolve's
    adjacent-Proxy auto-link all read, so the .mp4 estate on disk stays valid
    and nothing re-encodes it."""
    assert proxy_scan.GENERATED_EXT in proxy_scan.PROXY_EXTENSIONS


def test_partial_path_of_nothing_is_empty():
    assert proxy_scan.partial_path("") == ""
    assert proxy_scan.partial_path(None) == ""


def test_is_bpg_busy_sees_both_sidecars(tmp_path):
    original = tmp_path / "Panel" / "A001.mov"
    assert proxy_scan.is_bpg_busy(str(original)) is False

    tmp_sidecar = tmp_path / "Panel" / "Proxy" / ".A001.tmp"
    tmp_sidecar.parent.mkdir(parents=True)
    tmp_sidecar.write_bytes(b"growing")
    assert proxy_scan.is_bpg_busy(str(original)) is True

    tmp_sidecar.unlink()
    (tmp_path / "Panel" / "Proxy" / ".A001.lock").write_bytes(b"")
    assert proxy_scan.is_bpg_busy(str(original)) is True


def test_is_bpg_busy_survives_a_raising_probe(tmp_path):
    def boom(_path):
        raise OSError("the share went away")

    assert proxy_scan.is_bpg_busy(str(tmp_path / "A001.mov"), exists_fn=boom) is False


# -- scan_project: the gap ----------------------------------------------------


def test_an_uncovered_clip_is_missing_and_queued(tmp_path):
    project = _make_project(tmp_path)
    _clip(project / "Interviews" / "A001.mov", size=500)

    gap = _scan(project)
    assert gap["missing"] == 1
    assert gap["own"] == 1
    assert gap["preview"] == 0
    assert [clip["path"] for clip in gap["clips"]] == [
        str(project / "Interviews" / "A001.mov")
    ]
    assert gap["clips"][0]["kind"] == proxy_scan.KIND_OWN
    assert gap["clips"][0]["size"] == 500
    assert gap["truncated"] is False


def test_a_youtube_download_is_queued_as_a_preview(tmp_path):
    project = _make_project(tmp_path)
    _clip(project / "YouTube Downloads" / "ref.mp4")

    gap = _scan(project)
    assert gap["missing"] == 1 and gap["preview"] == 1 and gap["own"] == 0
    assert gap["clips"][0]["kind"] == proxy_scan.KIND_PREVIEW


def test_braw_is_counted_but_never_queued(tmp_path):
    """The BRAW gap is real -- nobody else can see the clip -- but ffmpeg
    cannot decode it, so the only honest answer is "run BPG"."""
    project = _make_project(tmp_path)
    _clip(project / "A001.braw")
    _clip(project / "B001.r3d")

    gap = _scan(project)
    assert gap["missing"] == 2
    assert gap["needs_resolve"] == 2
    assert gap["braw"] == 1  # .r3d is needs_resolve but not BRAW
    assert gap["clips"] == []
    assert gap["own"] == 0 and gap["preview"] == 0


def test_the_counts_add_up(tmp_path):
    project = _make_project(tmp_path)
    _clip(project / "A001.braw")
    _clip(project / "B001.mov")
    _clip(project / "Downloads" / "ref.mp4")

    gap = _scan(project)
    assert gap["own"] + gap["preview"] + gap["needs_resolve"] == gap["missing"] == 3


def test_insv_and_360_are_skipped_entirely(tmp_path):
    """A flat 1080p proxy of a dual-fisheye original is a preview of
    nothing, and Resolve would not attach it to the stitched clip either."""
    project = _make_project(tmp_path)
    _clip(project / "360" / "VID_001.insv")
    _clip(project / "360" / "VID_002.360")

    gap = _scan(project)
    assert gap["missing"] == 0 and gap["clips"] == []


@pytest.mark.parametrize("proxy_ext", [".mov", ".mp4"])
def test_a_proxy_at_either_extension_is_coverage(proxy_ext, tmp_path):
    """BPG writes .mov, this generator writes .mp4, and both count -- a
    second copy at the other extension is exactly the two-writers race."""
    project = _make_project(tmp_path)
    _clip(project / "Interviews" / "A001.mov")
    proxy = project / "Interviews" / "Proxy" / ("A001" + proxy_ext)
    proxy.parent.mkdir(parents=True)
    proxy.write_bytes(b"proxy")

    gap = _scan(project)
    assert gap["missing"] == 0 and gap["clips"] == []


def test_proxies_never_queue_themselves(tmp_path):
    """Proxy/ is pruned. Without that, `Proxy/A001.mp4` has no
    `Proxy/Proxy/A001.mp4` beside it and looks missing forever."""
    project = _make_project(tmp_path)
    _clip(project / "Interviews" / "Proxy" / "A001.mp4")
    _clip(project / "Interviews" / "proxy" / "B001.mp4")  # any case

    gap = _scan(project)
    assert gap["missing"] == 0 and gap["clips"] == []


def test_trash_and_hidden_dirs_are_pruned(tmp_path):
    """Files under lane B's backup-dir are already deleted as far as the
    tree is concerned (rclone_lane.TRASH_DIR_NAME)."""
    project = _make_project(tmp_path)
    _clip(project / ".ccsync-trash" / "Interviews" / "A001.mov")
    _clip(project / ".stversions" / "B001.mov")

    gap = _scan(project)
    assert gap["missing"] == 0 and gap["clips"] == []


def test_appledouble_sidecars_are_skipped(tmp_path):
    """`._A001.mov` keeps the original's extension, so it is a video file by
    every other test here -- and it is a 4 KB resource fork (KNOWN_BUGS 12)."""
    project = _make_project(tmp_path)
    _clip(project / "Interviews" / "._A001.mov", size=4096)

    gap = _scan(project)
    assert gap["missing"] == 0 and gap["clips"] == []


def test_the_settle_window_ignores_a_file_still_landing(tmp_path):
    """A clip mid-copy is a file in flight, not a gap."""
    project = _make_project(tmp_path)
    _clip(project / "fresh.mov", age=10)

    assert _scan(project)["missing"] == 0


def test_a_settled_file_is_a_gap(tmp_path):
    project = _make_project(tmp_path)
    _clip(project / "settled.mov", age=300)

    assert _scan(project)["missing"] == 1


def test_zero_byte_files_are_ignored(tmp_path):
    """A placeholder or a failed copy: nothing to encode, and reporting it
    sends an editor hunting for a clip that has no bytes."""
    project = _make_project(tmp_path)
    _clip(project / "empty.mov", size=0)

    assert _scan(project)["missing"] == 0


def test_non_video_files_are_ignored(tmp_path):
    """Same definition of "a video file" as the sync lanes: if a lane would
    not carry it, its absence downstream is not a proxy gap."""
    project = _make_project(tmp_path)
    _clip(project / "notes.txt")
    _clip(project / "music.wav")
    _clip(project / "Project.drp")

    assert _scan(project)["missing"] == 0


def test_a_clip_bpg_is_mid_way_through_is_neither_missing_nor_queued(tmp_path):
    project = _make_project(tmp_path)
    _clip(project / "Interviews" / "A001.mov")
    sidecar = project / "Interviews" / "Proxy" / ".A001.tmp"
    sidecar.parent.mkdir(parents=True)
    sidecar.write_bytes(b"2.3 GB, growing")

    gap = _scan(project)
    assert gap["missing"] == 0 and gap["clips"] == []


# -- scan_project: caps and ordering -------------------------------------------


def test_the_queue_is_capped_newest_first(tmp_path):
    project = _make_project(tmp_path)
    total = proxy_scan.MAX_QUEUE_PER_PROJECT + 5
    for index in range(total):
        # index 0 is the newest (SETTLED old); each later one is a minute
        # older, so the expected order is unambiguous.
        _clip(project / f"clip{index:04d}.mov", age=SETTLED + index * 60)

    gap = _scan(project)
    assert gap["missing"] == total  # counts stay exact
    assert len(gap["clips"]) == proxy_scan.MAX_QUEUE_PER_PROJECT
    assert gap["truncated"] is True
    assert os.path.basename(gap["clips"][0]["path"]) == "clip0000.mov"
    assert os.path.basename(gap["clips"][-1]["path"]) == (
        f"clip{proxy_scan.MAX_QUEUE_PER_PROJECT - 1:04d}.mov"
    )


def test_ties_are_broken_deterministically(tmp_path):
    """Same mtime to the tick -- the queue must still come out in the same
    order on the next scan, or the generator restarts a different clip."""
    project = _make_project(tmp_path)
    stamp = time.time() - SETTLED
    for name in ("c.mov", "a.mov", "b.mov"):
        _clip(project / name, at=stamp)

    order = [os.path.basename(clip["path"]) for clip in _scan(project)["clips"]]
    assert order == ["a.mov", "b.mov", "c.mov"]


def test_two_originals_sharing_a_proxy_name_queue_only_the_newest(tmp_path):
    """COMP-MEDIA-2: `A001.mov` and `A001.mp4` in one directory both map to
    `Proxy/A001.mp4`, so queuing both puts two ffmpegs on one `.partial` -- the
    drain runs 4 wide. Both stay COUNTED: they really are missing, and the
    stem convention (shared with BPG and Resolve's adjacent-Proxy auto-link)
    has no second name to offer."""
    project = _make_project(tmp_path)
    _clip(project / "A001.mov", at=time.time() - SETTLED)
    _clip(project / "A001.mp4", at=time.time() - SETTLED - 600)
    _clip(project / "A002.mov", at=time.time() - SETTLED)

    gap = _scan(project)

    assert gap["missing"] == 3
    assert gap["own"] == 3
    queued = sorted(os.path.basename(clip["path"]) for clip in gap["clips"])
    assert queued == ["A001.mov", "A002.mov"]


def test_the_same_stem_in_two_directories_is_not_a_collision(tmp_path):
    """Each directory has its own Proxy/ -- only a shared parent collides."""
    project = _make_project(tmp_path)
    _clip(project / "Day1" / "A001.mov")
    _clip(project / "Day2" / "A001.mov")

    assert len(_scan(project)["clips"]) == 2


def test_a_capped_clip_never_takes_a_queue_slot(tmp_path):
    """COMP-MEDIA-4: the cap is applied BEFORE the 500-clip truncation, or a
    project whose newest 500 clips have all failed reports an empty queue for
    ever while the older encodable ones are never offered to ffmpeg."""
    project = _make_project(tmp_path)
    total = proxy_scan.MAX_QUEUE_PER_PROJECT + 5
    for index in range(total):
        _clip(project / f"clip{index:04d}.mov", age=SETTLED + index * 60)

    # The newest 500 have "failed": exactly the 0.6.1 muxer night's shape.
    capped = {
        os.path.join(str(project), f"clip{index:04d}.mov")
        for index in range(proxy_scan.MAX_QUEUE_PER_PROJECT)
    }
    gap = _scan(project, skip_fn=lambda clip: clip["path"] in capped)

    assert gap["missing"] == total, "the count is still the truth"
    assert gap["capped"] == proxy_scan.MAX_QUEUE_PER_PROJECT
    assert [os.path.basename(clip["path"]) for clip in gap["clips"]] == [
        f"clip{index:04d}.mov" for index in range(total - 5, total)
    ]


def test_a_skip_predicate_that_raises_does_not_skip(tmp_path):
    """Never trusted: the whole module's bias is that a failure costs
    information, never work."""
    project = _make_project(tmp_path)
    _clip(project / "A001.mov")

    def boom(_clip):
        raise RuntimeError("the failure map went away")

    gap = _scan(project, skip_fn=boom)
    assert len(gap["clips"]) == 1
    assert gap["capped"] == 0


# -- scan_project: never raises ------------------------------------------------


def test_a_missing_project_dir_is_an_empty_gap(tmp_path):
    gap = _scan(tmp_path / "nope")
    assert gap == proxy_scan.empty_gap()


def test_a_stat_that_raises_skips_the_file(tmp_path):
    """A file that vanishes between the listing and the stat -- or a share
    that went away mid-walk -- is skipped, never an exception."""
    project = _make_project(tmp_path)
    _clip(project / "A001.mov")

    def boom(_path):
        raise OSError("gone")

    assert _scan(project, stat_fn=boom) == proxy_scan.empty_gap()


def test_a_nonsense_min_age_still_scans(tmp_path):
    """A hand-edited "2m" in the config must not stop the scan."""
    project = _make_project(tmp_path)
    _clip(project / "A001.mov")

    assert _scan(project, min_age_seconds="2m")["missing"] == 1


# -- scan_missing_proxies ------------------------------------------------------


def test_blank_local_root_is_empty_not_an_error():
    for root in ("", None, "   "):
        result = proxy_scan.scan_missing_proxies(root)
        assert result["projects"] == {}
        assert result["totals"]["missing"] == 0


def test_missing_local_root_is_empty(tmp_path):
    """An editor whose SSD is unplugged sees a scan with nothing in it, not
    a failure."""
    result = proxy_scan.scan_missing_proxies(str(tmp_path / "not-mounted"))
    assert result["projects"] == {}


def test_totals_add_up_across_projects(tmp_path):
    first = _make_project(tmp_path, project="Nuclear")
    second = _make_project(tmp_path, series="FF4", project="Solar")
    _clip(first / "A001.mov")
    _clip(first / "A002.braw")
    _clip(second / "Downloads" / "ref.mp4")

    result = proxy_scan.scan_missing_proxies(str(tmp_path), min_age_seconds=120)
    assert set(result["projects"]) == {"2026/FF5/Nuclear", "2026/FF4/Solar"}
    totals = result["totals"]
    assert totals["missing"] == 3
    assert totals["braw"] == 1 and totals["needs_resolve"] == 1
    assert totals["own"] == 1 and totals["preview"] == 1
    assert totals["queued"] == 2
    assert totals["projects"] == 2
    assert totals["dropped"] == 0
    assert totals["truncated"] is False


def test_a_fully_covered_project_still_appears(tmp_path):
    """"This project is fine" is an answer the tray needs to tell apart from
    "this project was capped out of the scan"."""
    project = _make_project(tmp_path)
    _clip(project / "A001.mov")
    proxy = project / "Proxy" / "A001.mov"
    proxy.parent.mkdir(parents=True)
    proxy.write_bytes(b"proxy")

    result = proxy_scan.scan_missing_proxies(str(tmp_path))
    assert result["projects"]["2026/FF5/Nuclear"]["missing"] == 0


def test_the_project_cap_keeps_the_selected_one(tmp_path):
    """65 projects, cap 64 (manifest.MAX_PROJECTS): the ticked project
    survives even though it is the least recently touched."""
    stamp = time.time()
    for index in range(65):
        project = _make_project(tmp_path, project=f"P{index:02d}")
        # Oldest last, so without prioritisation P64 is the one dropped.
        touched = stamp - index * 100
        os.utime(project, (touched, touched))

    selected = {"2026/FF5/P64"}
    result = proxy_scan.scan_missing_proxies(str(tmp_path), selected_rels=selected)

    assert len(result["projects"]) == proxy_scan.manifest.MAX_PROJECTS == 64
    assert "2026/FF5/P64" in result["projects"]
    assert "2026/FF5/P63" not in result["projects"]  # dropped in its place
    assert result["totals"]["dropped"] == 1
    assert result["totals"]["projects"] == 64


def test_one_unreadable_project_does_not_stop_the_sweep(tmp_path):
    _clip(_make_project(tmp_path, project="Nuclear") / "A001.mov")
    _clip(_make_project(tmp_path, project="Solar") / "B001.mov")

    real_stat = os.stat

    def flaky(path):
        if "Nuclear" in str(path):
            raise RuntimeError("boom")
        return real_stat(path)

    result = proxy_scan.scan_missing_proxies(str(tmp_path), stat_fn=flaky)
    assert result["projects"]["2026/FF5/Nuclear"]["missing"] == 0
    assert result["projects"]["2026/FF5/Solar"]["missing"] == 1
