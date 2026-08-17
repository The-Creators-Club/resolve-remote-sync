from __future__ import annotations

from tests.factories import insert_video


def test_ingest_video_upsert_by_share_rel_path(client):
    body = {
        "share": "broll",
        "rel_path": "military/naval/clip_9001.mov",
        "hash": "abc123",
        "size_bytes": 1000,
        "duration_s": 12.5,
        "fps": 24.0,
        "width": 1920,
        "height": 1080,
        "codec": "h264",
    }
    r1 = client.post("/api/ingest/video", json=body)
    assert r1.status_code == 200
    id1 = r1.json()["id"]

    # Re-post with a changed field: should update the same row, not create
    # a second one (upsert by (share, rel_path)).
    body2 = dict(body, hash="def456", duration_s=13.0)
    r2 = client.post("/api/ingest/video", json=body2)
    assert r2.status_code == 200
    id2 = r2.json()["id"]
    assert id1 == id2

    detail = client.get(f"/api/videos/{id1}").json()
    assert detail["video"]["hash"] == "def456"
    assert detail["video"]["duration_s"] == 13.0


def test_ingest_index_atomic_replace(client, conn):
    video_id = insert_video(conn, share="broll", rel_path="military/naval/clip_9002.mov")

    first = {
        "video_id": video_id,
        "themes": ["naval exercise", "harbor"],
        "quality_flags": ["shaky"],
        "category_hint": "military/naval",
        "segments": [
            {
                "t_start": 0.0,
                "t_end": 5.0,
                "description": "first pass description",
                "objects": ["ship", "sea"],
                "setting": "harbor",
                "motion": "static",
            }
        ],
    }
    r1 = client.post("/api/ingest/index", json=first)
    assert r1.status_code == 200

    detail1 = client.get(f"/api/videos/{video_id}").json()
    assert len(detail1["segments"]) == 1
    assert detail1["segments"][0]["description"] == "first pass description"
    assert detail1["quality_flags"] == ["shaky"]
    assert detail1["themes"] == ["naval exercise", "harbor"]
    assert detail1["video"]["status"] == "indexed"
    assert detail1["video"]["indexed_at"] is not None

    # Re-index with different data: old segments/themes/flags must be gone,
    # replaced atomically, not appended to.
    second = {
        "video_id": video_id,
        "themes": ["different theme"],
        "quality_flags": [],
        "category_hint": "military/naval",
        "segments": [
            {
                "t_start": 0.0,
                "t_end": 3.0,
                "description": "second pass segment one",
                "objects": ["a"],
                "setting": "x",
                "motion": "y",
            },
            {
                "t_start": 3.0,
                "t_end": 6.0,
                "description": "second pass segment two",
                "objects": ["b"],
                "setting": "x",
                "motion": "y",
            },
        ],
    }
    r2 = client.post("/api/ingest/index", json=second)
    assert r2.status_code == 200

    detail2 = client.get(f"/api/videos/{video_id}").json()
    descriptions = {s["description"] for s in detail2["segments"]}
    assert descriptions == {"second pass segment one", "second pass segment two"}
    assert detail2["quality_flags"] == []
    assert detail2["themes"] == ["different theme"]

    # The old segment text must not be searchable anymore (FTS index kept
    # in sync via the delete+insert, not left stale).
    r = client.get("/api/search", params={"q": "first pass"})
    assert r.json()["total"] == 0


def test_ingest_index_round_trips_onscreen_text(client, conn):
    """POST /api/ingest/index must accept and persist onscreen_text /
    onscreen_text_en (SPEC.md "Claude indexing output contract"), and older
    callers that omit them entirely must still work (default to '')."""
    video_id = insert_video(conn, share="broll", rel_path="news/clip_9010.mov")

    body = {
        "video_id": video_id,
        "themes": ["police operation"],
        "quality_flags": [],
        "category_hint": "news",
        "segments": [
            {
                "t_start": 0.0,
                "t_end": 8.5,
                "description": "Grey navy frigate moored at a concrete pier",
                "objects": ["navy ship", "warship", "惡龍", "Evil Dragon"],
                "setting": "harbor, overcast daylight",
                "motion": "slow pan left",
                "onscreen_text": "華視新聞 | 警匪激烈槍戰 惡龍中彈落網",
                "onscreen_text_en": "CTS News | Fierce police shootout, suspect 'Evil Dragon' captured",
            },
            {
                # Older-style segment with no onscreen_text keys at all --
                # must default to "" rather than reject the request.
                "t_start": 8.5,
                "t_end": 12.0,
                "description": "second segment, no on-screen text fields sent",
                "objects": ["b"],
                "setting": "x",
                "motion": "y",
            },
        ],
    }
    r = client.post("/api/ingest/index", json=body)
    assert r.status_code == 200

    detail = client.get(f"/api/videos/{video_id}").json()
    segs = {s["description"]: s for s in detail["segments"]}

    seg1 = segs["Grey navy frigate moored at a concrete pier"]
    assert seg1["onscreen_text"] == "華視新聞 | 警匪激烈槍戰 惡龍中彈落網"
    assert seg1["onscreen_text_en"] == (
        "CTS News | Fierce police shootout, suspect 'Evil Dragon' captured"
    )

    seg2 = segs["second segment, no on-screen text fields sent"]
    assert seg2["onscreen_text"] == ""
    assert seg2["onscreen_text_en"] == ""

    # And it's actually searchable both ways (dual-tokenizer union).
    r_cjk = client.get("/api/search", params={"q": "激烈槍"})
    assert video_id in {row["video"]["id"] for row in r_cjk.json()["results"]}
    r_en = client.get("/api/search", params={"q": "Evil Dragon"})
    assert video_id in {row["video"]["id"] for row in r_en.json()["results"]}


def test_ingest_index_unknown_video_404(client):
    r = client.post(
        "/api/ingest/index",
        json={"video_id": 999999, "themes": [], "quality_flags": [], "segments": []},
    )
    assert r.status_code == 404


def test_ingest_moved_updates_rel_path(client, conn):
    video_id = insert_video(
        conn, share="broll", rel_path="inbox/clip_9003.mov", in_inbox=1, status="indexed"
    )
    r = client.post(
        "/api/ingest/moved",
        json={"video_id": video_id, "new_rel_path": "military/naval/clip_9003.mov"},
    )
    assert r.status_code == 200

    detail = client.get(f"/api/videos/{video_id}").json()
    assert detail["video"]["rel_path"] == "military/naval/clip_9003.mov"
    assert detail["video"]["in_inbox"] == 0
    assert detail["video"]["status"] == "sorted"


def test_ingest_requires_token_when_configured(client, monkeypatch):
    monkeypatch.setenv("BROLL_INGEST_TOKEN", "secret-token")
    body = {"share": "broll", "rel_path": "needs-token.mov"}

    # An EMPTY header rather than no header at all: conftest's client sends a
    # default X-Ingest-Token on every request and httpx merges it in, so "" is
    # how a test reaches the no-credential branch through this fixture.
    r_no_header = client.post(
        "/api/ingest/video", json=body, headers={"X-Ingest-Token": ""}
    )
    assert r_no_header.status_code == 401

    r_wrong = client.post(
        "/api/ingest/video", json=body, headers={"X-Ingest-Token": "wrong"}
    )
    assert r_wrong.status_code == 401

    r_ok = client.post(
        "/api/ingest/video", json=body, headers={"X-Ingest-Token": "secret-token"}
    )
    assert r_ok.status_code == 200


def test_ingest_refuses_when_no_token_is_configured(client, monkeypatch):
    """No BROLL_INGEST_TOKEN = the write path is CLOSED, not open.

    This pins the deletion of the old dev-mode branch (COMMERCIAL_READINESS.md
    item 15, 2026-08-17): an unconfigured server used to accept ingest from
    anyone who could reach it, which is a repoint-every-clip primitive. The
    previous test here asserted 200 for exactly this request.
    """
    monkeypatch.delenv("BROLL_INGEST_TOKEN", raising=False)
    body = {"share": "broll", "rel_path": "dev-mode.mov"}

    r = client.post("/api/ingest/video", json=body)
    assert r.status_code == 503
    assert "BROLL_INGEST_TOKEN" in r.json()["detail"]

    # ...and no token an attacker guesses opens it either.
    r_guess = client.post(
        "/api/ingest/video", json=body, headers={"X-Ingest-Token": ""}
    )
    assert r_guess.status_code == 503


def test_ingest_token_check_survives_a_non_ascii_header(client, monkeypatch):
    """A non-ASCII X-Ingest-Token is a 401, never a 500.

    hmac.compare_digest raises TypeError on a str carrying anything above
    U+007F; the dashboard's own gate met this as DASH-5 (2026-08-11) and
    answered a refusal with a traceback.
    """
    monkeypatch.setenv("BROLL_INGEST_TOKEN", "secret-token")
    r = client.post(
        "/api/ingest/video",
        json={"share": "broll", "rel_path": "non-ascii.mov"},
        # bytes, because httpx refuses to encode a non-ASCII str header at all;
        # starlette decodes it latin-1, which is what reaches the handler.
        headers={"X-Ingest-Token": "sécret-token".encode("utf-8")},
    )
    assert r.status_code == 401


def test_ingest_shares_records_origin_facts(client, conn):
    """The web app cannot derive share -> source root; the indexer pushes it.
    Without this the origin manifest can record a share name and a relative path
    with nothing to resolve them against at conform time."""
    r = client.post("/api/ingest/shares", json=[
        {"share": "ff4-nuclear", "root": "Z:/FF4/Nuclear/Youtube"},
        {"share": "mofa-disaster", "root": "Z:/MOFA/Event",
         "source": "proxies", "description": "own footage", "indexed": False},
    ])
    assert r.status_code == 200
    assert r.json()["shares"] == 2

    rows = {x["share"]: x for x in conn.execute("SELECT * FROM share_roots")}
    assert rows["mofa-disaster"]["source"] == "proxies"
    assert rows["mofa-disaster"]["indexed"] == 0
    assert rows["ff4-nuclear"]["source"] == "originals", "sane default"


def test_ingest_shares_upserts_rather_than_duplicating(client, conn):
    for root in ("Z:/old", "Z:/new"):
        client.post("/api/ingest/shares", json=[{"share": "s", "root": root}])
    rows = conn.execute("SELECT root FROM share_roots").fetchall()
    assert len(rows) == 1
    assert rows[0]["root"] == "Z:/new"


def test_ingest_shares_rejects_an_unknown_source(client):
    r = client.post("/api/ingest/shares",
                    json=[{"share": "s", "root": "Z:/x", "source": "nonsense"}])
    assert r.status_code == 422, "a bad source is a validation error, not a DB crash"
