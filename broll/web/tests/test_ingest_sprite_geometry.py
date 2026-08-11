"""Sprite geometry survives the ingest hop, and reaches the browser on the row.

The indexer measures the sheet it built (cell size, columns, cell count,
interval) because the browser cannot re-derive any of it -- see
migrations/009_sprite_geometry.sql and the indexer's build_sprite. Co-located,
that is a plain UPDATE; over HTTP it rides the /api/ingest/video upsert, which
is also what every scan and probe posts, so the geometry has to survive being
absent from those (BROLL-1/BROLL-2, 2026-08-11).
"""
from __future__ import annotations

from tests.factories import insert_video

BASE = {"share": "ff4", "rel_path": "Day 1/Proxy/a.mov"}
GEOMETRY = {
    "sprite_cell_w": 240,
    "sprite_cell_h": 136,
    "sprite_cols": 10,
    "sprite_cells": 240,
    "sprite_interval_s": 12.67,
}


def test_ingest_records_the_geometry(client):
    vid = client.post("/api/ingest/video", json={**BASE, **GEOMETRY}).json()["id"]

    video = client.get(f"/api/videos/{vid}").json()["video"]
    assert {k: video[k] for k in GEOMETRY} == GEOMETRY


def test_a_later_scan_does_not_blank_it(client):
    """A scan posts hash/size only, and a probe posts dimensions. Neither knows
    anything about the sheet, and `excluded.x` would overwrite it with NULL --
    the same reason `category` is COALESCEd on this upsert."""
    vid = client.post("/api/ingest/video", json={**BASE, **GEOMETRY}).json()["id"]

    client.post("/api/ingest/video", json={**BASE, "hash": "abc", "size_bytes": 12})

    video = client.get(f"/api/videos/{vid}").json()["video"]
    assert video["sprite_cell_h"] == 136
    assert video["sprite_interval_s"] == 12.67


def test_a_re_sprite_overwrites_it(client):
    """The regeneration path: the whole point is that re-running build_sprite
    makes a legacy row exact."""
    vid = client.post("/api/ingest/video", json={**BASE, **GEOMETRY}).json()["id"]

    client.post("/api/ingest/video",
                json={**BASE, **GEOMETRY, "sprite_cell_h": 428, "sprite_interval_s": 2.0})

    video = client.get(f"/api/videos/{vid}").json()["video"]
    assert video["sprite_cell_h"] == 428
    assert video["sprite_interval_s"] == 2.0


def test_a_legacy_row_reports_no_geometry_rather_than_a_default(client, conn):
    """NULL is what tells the browser to fall back to its old heuristics. A
    zero or a plausible-looking default would silently claim the sheet had been
    measured, which for 7,117 live sheets it has not."""
    vid = insert_video(conn, share="ff4", rel_path="old.mov")

    video = client.get(f"/api/videos/{vid}").json()["video"]
    assert video["sprite_cell_w"] is None
    assert video["sprite_cell_h"] is None
    assert video["sprite_cells"] is None
    assert video["sprite_interval_s"] is None


def test_the_geometry_rides_along_on_search_results(client, conn):
    """The grid positions overlays from the search payload, not from a
    per-card /api/videos fetch."""
    client.post("/api/ingest/video", json={**BASE, **GEOMETRY})

    results = client.get("/api/search").json()["results"]
    assert results[0]["video"]["sprite_cell_h"] == 136
