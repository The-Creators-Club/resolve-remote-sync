"""proxy_relink tests — the 2026-08-01 incident, in miniature.

Windows path handling is exercised with is_windows=True from any host OS,
the same way test_paths.py does it.
"""

from __future__ import annotations

import logging

import pytest

from ccsync_companion import proxy_relink


@pytest.fixture(autouse=True)
def _clean_refusal_memory():
    """The refusal memory is module-global (it has to outlive a pass), so one
    test's refusal must not answer another's question -- the same rule the
    ffmpeg_tools probe caches and resolve_bridge's session state are reset
    under."""
    proxy_relink.reset_refusals()
    yield
    proxy_relink.reset_refusals()


LOCAL_ROOT = r"F:\Creators_Club"
CANON = "P:\\"

PANEL = r"P:\Projects\2026\CCT\Event 1.exe Videos for Event\Interviews\Panel"
BRAW = PANEL + r"\A001_04182004_C061.braw"
GOOD_PROXY = PANEL + r"\Proxy\A001_04182004_C061.mov"
STALE_PROXY = r"G:\Temp Transfer\Creators Club\Panel\Proxy\A001_04182004_C061.mov"


def exists_only(*present):
    normalized = {p.lower().replace("/", "\\") for p in present}

    def _exists(path):
        return str(path).lower().replace("/", "\\") in normalized

    return _exists


def item(file_path, proxy_path="", proxy_state="", name="clip", mpi=None):
    return {
        "file_path": file_path,
        "proxy_path": proxy_path,
        "proxy_state": proxy_state,
        "clip_name": name,
        "media_pool_item": mpi if mpi is not None else object(),
    }


def plan(items, exists):
    return proxy_relink.plan_relinks(
        items, LOCAL_ROOT, CANON, exists_fn=exists, is_windows=True
    )


# -- the convention has one home ----------------------------------------------


def test_proxy_scan_imports_the_convention_rather_than_redeclaring_it():
    """Two copies of "an adjacent Proxy/ dir, same stem, .mov or .mp4" would
    drift, and the failure is silent both ways: proxy_scan queueing an encode
    for a clip proxy_relink can already attach, or reporting a gap that isn't
    one. `is`, not `==`: a re-declared tuple with the same contents is
    exactly the drift this guards against (2026-08-10)."""
    from ccsync_companion import proxy_scan

    assert proxy_scan.PROXY_EXTENSIONS is proxy_relink.PROXY_EXTENSIONS
    assert proxy_scan.PROXY_DIR_NAME is proxy_relink.PROXY_DIR_NAME


# -- proxy_is_working ---------------------------------------------------------


def test_resolution_means_working_offline_and_none_do_not():
    # Resolve stores the proxy's RESOLUTION when it resolves.
    assert proxy_relink.proxy_is_working("1920x1080")
    assert proxy_relink.proxy_is_working("1620x1080")  # the real Panel clip
    assert not proxy_relink.proxy_is_working("Offline")
    assert not proxy_relink.proxy_is_working("None")
    assert not proxy_relink.proxy_is_working("")
    assert not proxy_relink.proxy_is_working(None)


# -- path derivation ----------------------------------------------------------


def test_expected_proxy_paths_are_the_adjacent_proxy_folder():
    assert proxy_relink.expected_proxy_paths(BRAW, is_windows=True) == [
        PANEL + r"\Proxy\A001_04182004_C061.mov",
        PANEL + r"\Proxy\A001_04182004_C061.mp4",
    ]


def test_find_proxy_returns_canonical_spelling_even_when_found_via_local_root():
    """The P: mapping is per-logon-session, so a process that can't see it
    must still be able to prove the file exists -- via local_root -- and must
    still link the CANONICAL path so the project stays fleet-portable."""
    local_twin = LOCAL_ROOT + GOOD_PROXY[2:]
    found = proxy_relink.find_proxy_on_disk(
        BRAW, LOCAL_ROOT, CANON, exists_fn=exists_only(local_twin), is_windows=True
    )
    assert found == GOOD_PROXY


# -- planning -----------------------------------------------------------------


def test_stale_g_drive_proxy_is_repointed_at_the_synced_copy():
    """The incident: proxy attached to a drive that never existed here."""
    ops = plan([item(BRAW, STALE_PROXY, "Offline")], exists_only(GOOD_PROXY))
    assert len(ops) == 1
    assert ops[0]["new_proxy"] == GOOD_PROXY
    assert ops[0]["old_proxy"] == STALE_PROXY
    assert ops[0]["reason"] == "stale"


def test_clip_with_no_proxy_attached_gets_one_when_it_is_on_disk():
    ops = plan([item(BRAW, "", "None")], exists_only(GOOD_PROXY))
    assert len(ops) == 1 and ops[0]["reason"] == "unlinked"


def test_working_proxy_is_left_alone():
    ops = plan([item(BRAW, GOOD_PROXY, "1920x1080")], exists_only(GOOD_PROXY))
    assert ops == []


def test_out_of_tree_media_is_never_touched():
    """267 of ruskin's 431 clips were BM Cloud media with broken proxies --
    the editor's own business, not this system's."""
    bm = r"F:\[BM Cloud]\Exhibition Videos\Downloads\clip.mp4"
    bm_proxy = r"F:\[BM Cloud]\Exhibition Videos\Downloads\Proxy\clip.mov"
    assert plan([item(bm, bm_proxy, "Offline")], exists_only(bm_proxy)) == []


def test_no_proxy_on_disk_yet_is_not_an_op():
    """Lane B hasn't delivered it -- that's lane B's problem, not a relink."""
    assert plan([item(BRAW, STALE_PROXY, "Offline")], exists_only()) == []


def test_already_pointing_here_but_still_offline_does_not_churn():
    """Unreadable file, not a wrong address. Relinking every 120 s would
    rewrite the project forever for no gain."""
    ops = plan([item(BRAW, GOOD_PROXY, "Offline")], exists_only(GOOD_PROXY))
    assert ops == []


def test_local_root_spelling_of_an_original_is_in_tree_too():
    local_orig = LOCAL_ROOT + BRAW[2:]
    local_proxy = LOCAL_ROOT + GOOD_PROXY[2:]
    ops = plan([item(local_orig, "", "None")], exists_only(local_proxy))
    assert len(ops) == 1 and ops[0]["new_proxy"] == local_proxy


def test_unreadable_item_does_not_stop_the_rest():
    class Hostile(dict):
        def get(self, *a, **k):
            raise RuntimeError("boom")

    ops = plan([Hostile(), item(BRAW, STALE_PROXY, "Offline")], exists_only(GOOD_PROXY))
    assert len(ops) == 1


def test_exists_fn_that_raises_is_treated_as_absent():
    def boom(_):
        raise OSError("no such drive")

    assert plan([item(BRAW, STALE_PROXY, "Offline")], boom) == []


# -- macOS editors: a canonical original on a posix host ----------------------
#
# is_windows=False is the posix host (the same seam test_paths.py uses). The
# original is still spelled `P:\...` -- that is what the fleet's project
# databases store -- so the proxy beside it must be derived with ntpath and
# linked in canonical spelling, while the "does it exist" probe goes to the
# local twin under local_root.

MAC_ROOT = "/Volumes/T7/Creators_Club"
MAC_PANEL = r"P:\Projects\2026\CCT\Interviews\Panel"
MAC_BRAW = MAC_PANEL + r"\A001_04182004_C061.braw"
MAC_PROXY = MAC_PANEL + r"\Proxy\A001_04182004_C061.mov"
MAC_TWIN_PROXY = MAC_ROOT + "/Projects/2026/CCT/Interviews/Panel/Proxy/A001_04182004_C061.mov"


def exists_any_spelling(*present):
    wanted = {p.lower().replace("\\", "/") for p in present}
    return lambda path: str(path).lower().replace("\\", "/") in wanted


def test_mac_canonical_original_derives_an_all_backslash_proxy_path():
    """posixpath.dirname("P:\\...\\a.braw") answers the whole string, and
    posixpath.join would emit `P:\\...\\Proxy/a.mov` into the project."""
    got = proxy_relink.expected_proxy_paths(MAC_BRAW, is_windows=False)
    assert got == [
        MAC_PANEL + r"\Proxy\A001_04182004_C061.mov",
        MAC_PANEL + r"\Proxy\A001_04182004_C061.mp4",
    ]
    assert all("/" not in p for p in got)


def test_mac_canonical_original_is_in_tree():
    assert proxy_relink.is_in_tree(MAC_BRAW, MAC_ROOT, CANON, is_windows=False)
    assert proxy_relink.is_in_tree(
        MAC_ROOT + "/Projects/2026/a.braw", MAC_ROOT, CANON, is_windows=False
    )
    assert not proxy_relink.is_in_tree(
        "/Users/jane/Movies/a.mov", MAC_ROOT, CANON, is_windows=False
    )


def test_mac_proxy_is_found_via_the_local_twin_and_linked_canonically():
    found = proxy_relink.find_proxy_on_disk(
        MAC_BRAW, MAC_ROOT, CANON,
        exists_fn=exists_any_spelling(MAC_TWIN_PROXY), is_windows=False,
    )
    assert found == MAC_PROXY


def test_mac_stale_g_drive_proxy_is_repointed_at_the_canonical_copy():
    ops = proxy_relink.plan_relinks(
        [item(MAC_BRAW, STALE_PROXY, "Offline", name="")],
        MAC_ROOT, CANON,
        exists_fn=exists_any_spelling(MAC_TWIN_PROXY), is_windows=False,
    )
    assert len(ops) == 1
    assert ops[0]["new_proxy"] == MAC_PROXY
    # the fallback name comes from basename(), which posixpath would answer
    # with the whole `P:\...` string
    assert ops[0]["clip_name"] == "A001_04182004_C061.braw"
    assert ops[0]["reason"] == "stale"


def test_mac_proxy_that_is_not_synced_down_yet_is_not_an_op():
    ops = proxy_relink.plan_relinks(
        [item(MAC_BRAW, STALE_PROXY, "Offline")],
        MAC_ROOT, CANON, exists_fn=exists_any_spelling(), is_windows=False,
    )
    assert ops == []


# -- applying -----------------------------------------------------------------


def test_apply_reports_counts_and_keeps_going_past_a_refusal():
    calls = []

    def link_fn(mpi, path):
        calls.append(path)
        # Resolve refuses a mismatched proxy (wrong timecode/frame count).
        return {"ok": "bad" not in path, "message": "mismatch"}

    ops = [
        {"media_pool_item": object(), "clip_name": "a", "new_proxy": "P:\\good.mov", "old_proxy": ""},
        {"media_pool_item": object(), "clip_name": "b", "new_proxy": "P:\\bad.mov", "old_proxy": ""},
        {"media_pool_item": object(), "clip_name": "c", "new_proxy": "P:\\good2.mov", "old_proxy": ""},
    ]
    result = proxy_relink.apply_relinks(ops, link_fn)
    assert len(calls) == 3
    assert result["relinked"] == 2
    assert result["failed"] == 1
    assert result["failures"] == ["b"]
    assert result["ok"] is False


def test_apply_survives_a_raising_link_fn():
    def link_fn(mpi, path):
        raise RuntimeError("fusionscript went away")

    result = proxy_relink.apply_relinks(
        [{"media_pool_item": object(), "clip_name": "a", "new_proxy": "P:\\x.mov"}], link_fn
    )
    assert result["relinked"] == 0 and result["failed"] == 1


def test_apply_with_nothing_to_do_is_silent():
    result = proxy_relink.apply_relinks([], lambda *_: {"ok": True})
    assert result == {"ok": True, "relinked": 0, "failed": 0, "failures": [], "message": ""}
# -- a proxy Resolve refuses is not re-offered every 120 s (COMP-MEDIA-5) -----


class _Stat:
    def __init__(self, mtime, size):
        self.st_mtime = float(mtime)
        self.st_size = int(size)


OTHER_BRAW = PANEL + r"\A002_04182004_C062.braw"
OTHER_PROXY = PANEL + r"\Proxy\A002_04182004_C062.mov"


def _stat_for(files):
    """A stat seam over {path: (mtime, size)}; anything else "is not there",
    the same shape exists_only has."""
    table = {p.lower().replace("/", "\\"): v for p, v in files.items()}

    def _stat(path):
        try:
            mtime, size = table[str(path).lower().replace("/", "\\")]
        except KeyError:
            raise OSError("not there")
        return _Stat(mtime, size)

    return _stat


def _refused_once(stat_fn):
    """Plan the panel clip, have Resolve refuse it, and hand back the plan."""
    items = [item(BRAW, STALE_PROXY, "Offline", name="A001")]
    ops = proxy_relink.plan_relinks(
        items, LOCAL_ROOT, CANON, exists_fn=exists_only(GOOD_PROXY),
        is_windows=True, stat_fn=stat_fn,
    )
    assert len(ops) == 1 and ops[0]["new_proxy"] == GOOD_PROXY
    proxy_relink.apply_relinks(
        ops, lambda mpi, path: {"ok": False, "message": "timecode mismatch"}, stat_fn,
    )
    return items


def _plan_again(items, stat_fn):
    return proxy_relink.plan_relinks(
        items, LOCAL_ROOT, CANON, exists_fn=exists_only(GOOD_PROXY),
        is_windows=True, stat_fn=stat_fn,
    )


def test_a_refused_proxy_is_not_planned_again_next_pass():
    """A refusal leaves NOTHING on the clip -- proxy_path stays "" and
    proxy_state stays "None" -- so the identical op was regenerated every
    120 s, for one _API_LOCK'd LinkProxyMedia and one WARNING per clip per
    pass, for ever."""
    stat = _stat_for({GOOD_PROXY: (1000.0, 4096)})
    items = _refused_once(stat)

    assert _plan_again(items, stat) == []


def test_a_re_encoded_proxy_re_arms_the_pairing():
    """The repair for a refused proxy IS a new file (proxy_gen re-encoding it
    with the right timecode, lane B re-delivering it, the archive sweep
    remuxing it), so a changed (mtime, size) has to be a new question."""
    items = _refused_once(_stat_for({GOOD_PROXY: (1000.0, 4096)}))

    fresh = _stat_for({GOOD_PROXY: (2000.0, 5120)})
    ops = _plan_again(items, fresh)

    assert len(ops) == 1 and ops[0]["new_proxy"] == GOOD_PROXY


def test_a_refusal_of_one_proxy_does_not_silence_another_clip():
    stat = _stat_for({GOOD_PROXY: (1000.0, 4096), OTHER_PROXY: (1000.0, 4096)})
    _refused_once(stat)

    ops = proxy_relink.plan_relinks(
        [item(OTHER_BRAW, STALE_PROXY, "Offline", name="A002")],
        LOCAL_ROOT, CANON, exists_fn=exists_only(OTHER_PROXY),
        is_windows=True, stat_fn=stat,
    )

    assert len(ops) == 1 and ops[0]["new_proxy"] == OTHER_PROXY


def test_one_warning_per_pass_not_one_per_refused_clip(caplog):
    """R15 fix 4's shape: the pass says how many and which one to look at,
    and the per-clip detail goes to DEBUG. 200 refused clips every 120 s is
    ~144,000 lines a day into the log that rotates every 5 MB."""
    ops = [
        {"media_pool_item": object(), "clip_name": name,
         "file_path": rf"P:\Projects\{name}.braw",
         "new_proxy": rf"P:\Projects\Proxy\{name}.mov", "old_proxy": ""}
        for name in ("a", "b", "c")
    ]
    stat = _stat_for({})

    with caplog.at_level(logging.DEBUG, logger="ccsync.proxy_relink"):
        result = proxy_relink.apply_relinks(
            ops, lambda mpi, path: {"ok": False, "message": "mismatch"}, stat,
        )

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "3 proxy link(s) refused" in warnings[0]
    assert "first: a" in warnings[0]
    # The detail is still THERE, just not at WARNING.
    assert sum(1 for r in caplog.records if r.levelno == logging.DEBUG) == 3
    # ...and the contract app and the tray read is unchanged.
    assert result["relinked"] == 0
    assert result["failed"] == 3
    assert result["failures"] == ["a", "b", "c"]
    assert result["ok"] is False


def test_a_link_that_raises_is_not_remembered_as_a_refusal(caplog):
    """fusionscript going away says nothing about the pairing -- remembering
    it would skip a clip Resolve never answered about."""
    stat = _stat_for({GOOD_PROXY: (1000.0, 4096)})
    items = [item(BRAW, STALE_PROXY, "Offline", name="A001")]
    ops = _plan_again(items, stat)

    def _boom(mpi, path):
        raise RuntimeError("fusionscript went away")

    with caplog.at_level(logging.DEBUG, logger="ccsync.proxy_relink"):
        proxy_relink.apply_relinks(ops, _boom, stat)

    assert len(_plan_again(items, stat)) == 1
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1 and "link failed for A001" in warnings[0]


def test_a_successful_relink_leaves_no_memory_behind():
    stat = _stat_for({GOOD_PROXY: (1000.0, 4096)})
    items = [item(BRAW, STALE_PROXY, "Offline", name="A001")]
    ops = _plan_again(items, stat)

    proxy_relink.apply_relinks(ops, lambda mpi, path: {"ok": True}, stat)

    assert proxy_relink.is_refused(BRAW, GOOD_PROXY, stat) is False
