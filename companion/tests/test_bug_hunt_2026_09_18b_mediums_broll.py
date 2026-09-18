"""2026-09-18b mediums wave, companion-broll (CR-294).

proxy-tiers-3: the b-roll detail route's `known: false` outage guard is about
to start carrying `original_is_edit_weight: true` - a deliberate lie, aimed at
the 0.9.65..0.9.74 builds that have never heard of `known` and read that one
field to decide whether a clip is heavy enough to deserve a stand-in. These
tests pin what a build that DOES understand `known` does with it: nothing.
"""

from ccsync_companion import broll_server


def _outage_insert(**overrides):
    """`routes_api._insert_object`'s shape while the archive folder is
    unreadable: the listing raised, so there is no original and no editing
    proxy to name, `known` is false, and (once the server half lands) the
    weight is forced true for the benefit of older companions."""
    data = {
        "share": "broll",
        "original_rel": None,
        "preview_rel": "creators/2026-09-18 ingest/Proxy/A001.mp4",
        "edit_proxy_rel": None,
        "known": False,
        "original_is_edit_weight": True,
        "geometry": {"width": 6064, "height": 3424, "fps": 30.0,
                     "frames": 1813, "start_tc": "12:09:12:22"},
    }
    data.update(overrides)
    return data


def test_a_known_false_object_carries_no_weight_judgement_forward():
    """The forced `true` is for old builds only. Carrying it into the derived
    tiers would mean a later reader here - a log line today, a decision
    tomorrow - believing a 6K original is already small enough to edit with,
    on the one object whose entire point is that the server judged nothing."""
    rel = "creators/2026-09-18 ingest/Proxy/A001.mp4"
    tiers = broll_server.derive_insert_paths(_outage_insert(), rel)

    assert tiers["known"] is False
    assert tiers["original_is_edit_weight"] is None
    assert tiers["from_page"] is False
    # Read off the `videos` row, never off the failed listing: still an answer.
    assert tiers["geometry"]["height"] == 3424


def test_the_outage_object_still_fetches_the_file_the_editor_asked_for():
    """With or without the lie, the plan is the pre-phase-3 route: download
    the posted path, never a stand-in, never a ledger row that outlives the
    outage."""
    rel = "creators/2026-09-18 ingest/Proxy/A001.mp4"
    plan = broll_server.plan_insert(
        False, False, broll_server.derive_insert_paths(_outage_insert(), rel),
        wired=False)

    assert plan["action"] == broll_server.PLAN_FETCH_ORIGINAL
    assert plan["fetch_rel"] is None
    assert plan["upgrade_rel"] is None


def test_a_healthy_object_keeps_its_weight():
    """The reset is scoped to `known is False`. A healthy heavy clip must keep
    `False` here, or every stand-in in the feature stops being planned."""
    rel = "creators/2026-09-18 ingest/A001.MP4"
    tiers = broll_server.derive_insert_paths(
        _outage_insert(known=True, original_is_edit_weight=False,
                       original_rel=rel,
                       edit_proxy_rel="creators/2026-09-18 ingest/Proxy/A001.mov"),
        rel)

    assert tiers["original_is_edit_weight"] is False
    plan = broll_server.plan_insert(False, False, tiers, wired=False)
    assert plan["action"] == broll_server.PLAN_FETCH_STANDIN


def test_a_rolled_back_dashboard_in_an_outage_is_preview_only():
    """Deploy-order insurance (brief rule 7). A dashboard rolled back below
    the `known` fix answers an outage with `original_rel: null` and no `known`
    key at all. This build must still refuse to ledger the archive's own
    preview as a stand-in for an original it was simply unable to see: the
    explicit null is what decides, and the answer is the preview itself."""
    rel = "creators/2026-09-18 ingest/Proxy/A001.mp4"
    body = _outage_insert(original_is_edit_weight=False)
    body.pop("known")
    tiers = broll_server.derive_insert_paths(body, rel)

    assert tiers["original_known"] is False
    plan = broll_server.plan_insert(False, False, tiers, wired=False)
    assert plan["action"] == broll_server.PLAN_PREVIEW_ONLY
    assert plan["insert_rel"] == tiers["preview_rel"]
