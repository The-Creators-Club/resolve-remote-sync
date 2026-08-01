"""proxy_relink tests — the 2026-08-01 incident, in miniature.

Windows path handling is exercised with is_windows=True from any host OS,
the same way test_paths.py does it.
"""

from __future__ import annotations

from ccsync_companion import proxy_relink

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
