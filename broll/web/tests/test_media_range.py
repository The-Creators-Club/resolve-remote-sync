from __future__ import annotations

FIXTURE_BYTES = bytes(i % 256 for i in range(2000))


def _write_proxy(data_root, video_id: int) -> None:
    proxies_dir = data_root / "proxies"
    proxies_dir.mkdir(parents=True, exist_ok=True)
    (proxies_dir / f"{video_id}.mp4").write_bytes(FIXTURE_BYTES)


def test_no_range_header_returns_full_file(client, data_root):
    _write_proxy(data_root, 42)
    r = client.get("/media/proxy/42.mp4")
    assert r.status_code == 200
    assert r.content == FIXTURE_BYTES
    assert r.headers["content-length"] == str(len(FIXTURE_BYTES))
    assert r.headers["accept-ranges"] == "bytes"


def test_explicit_range(client, data_root):
    _write_proxy(data_root, 43)
    r = client.get("/media/proxy/43.mp4", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206
    assert r.content == FIXTURE_BYTES[0:10]
    assert r.headers["content-range"] == f"bytes 0-9/{len(FIXTURE_BYTES)}"
    assert r.headers["content-length"] == "10"


def test_mid_file_explicit_range(client, data_root):
    _write_proxy(data_root, 44)
    r = client.get("/media/proxy/44.mp4", headers={"Range": "bytes=500-599"})
    assert r.status_code == 206
    assert r.content == FIXTURE_BYTES[500:600]
    assert r.headers["content-range"] == f"bytes 500-599/{len(FIXTURE_BYTES)}"


def test_open_ended_range(client, data_root):
    _write_proxy(data_root, 45)
    r = client.get("/media/proxy/45.mp4", headers={"Range": "bytes=1900-"})
    assert r.status_code == 206
    assert r.content == FIXTURE_BYTES[1900:]
    size = len(FIXTURE_BYTES)
    assert r.headers["content-range"] == f"bytes 1900-{size - 1}/{size}"


def test_suffix_range(client, data_root):
    _write_proxy(data_root, 46)
    r = client.get("/media/proxy/46.mp4", headers={"Range": "bytes=-100"})
    assert r.status_code == 206
    assert r.content == FIXTURE_BYTES[-100:]
    size = len(FIXTURE_BYTES)
    assert r.headers["content-range"] == f"bytes {size - 100}-{size - 1}/{size}"


def test_range_beyond_file_size_is_416(client, data_root):
    _write_proxy(data_root, 47)
    size = len(FIXTURE_BYTES)
    r = client.get("/media/proxy/47.mp4", headers={"Range": f"bytes={size + 100}-{size + 200}"})
    assert r.status_code == 416
    assert r.headers["content-range"] == f"bytes */{size}"


def test_missing_file_is_404(client, data_root):
    r = client.get("/media/proxy/9999.mp4")
    assert r.status_code == 404


def test_sprite_and_poster_serve_plain_files(client, data_root):
    sprites_dir = data_root / "sprites"
    posters_dir = data_root / "posters"
    sprites_dir.mkdir(parents=True, exist_ok=True)
    posters_dir.mkdir(parents=True, exist_ok=True)
    (sprites_dir / "48.jpg").write_bytes(b"\xff\xd8fakejpegsprite")
    (posters_dir / "48.jpg").write_bytes(b"\xff\xd8fakejpegposter")

    r_sprite = client.get("/media/sprite/48.jpg")
    assert r_sprite.status_code == 200
    assert r_sprite.content == b"\xff\xd8fakejpegsprite"

    r_poster = client.get("/media/poster/48.jpg")
    assert r_poster.status_code == 200
    assert r_poster.content == b"\xff\xd8fakejpegposter"


# --- serving from the shared archive tree -------------------------------------

def test_proxy_is_served_from_the_archive_path(client, conn, data_root):
    """The archive tree is the same media editors link against in Resolve.
    Serving from it means one copy on the NAS, not 54.7 GB twice."""
    from tests.factories import insert_video
    vid = insert_video(conn, share="broll", rel_path="a.mov")
    rel = "Downloads/energy/nuclear/Proxy/reactor.mp4"
    dest = data_root / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"ARCHIVE-BYTES")
    conn.execute("UPDATE videos SET archive_path = ? WHERE id = ?", (rel, vid))
    conn.commit()

    r = client.get(f"/media/proxy/{vid}.mp4")
    assert r.status_code == 200
    assert r.content == b"ARCHIVE-BYTES"


def test_it_falls_back_to_the_flat_proxies_dir(client, conn, data_root):
    """A build is incremental; a clip indexed between builds must still preview."""
    from tests.factories import insert_video
    vid = insert_video(conn, share="broll", rel_path="b.mov")
    proxies = data_root / "proxies"
    proxies.mkdir(parents=True, exist_ok=True)
    (proxies / f"{vid}.mp4").write_bytes(b"FLAT-BYTES")

    r = client.get(f"/media/proxy/{vid}.mp4")
    assert r.status_code == 200
    assert r.content == b"FLAT-BYTES"


def test_a_stale_archive_path_falls_back_rather_than_404ing(client, conn, data_root):
    from tests.factories import insert_video
    vid = insert_video(conn, share="broll", rel_path="c.mov")
    proxies = data_root / "proxies"
    proxies.mkdir(parents=True, exist_ok=True)
    (proxies / f"{vid}.mp4").write_bytes(b"FLAT-BYTES")
    conn.execute("UPDATE videos SET archive_path = ? WHERE id = ?",
                 ("Downloads/gone/Proxy/missing.mp4", vid))
    conn.commit()

    assert client.get(f"/media/proxy/{vid}.mp4").content == b"FLAT-BYTES"


def test_an_escaping_archive_path_is_refused(client, conn, data_root):
    """A row's text must never be able to address the rest of the filesystem."""
    from tests.factories import insert_video
    vid = insert_video(conn, share="broll", rel_path="d.mov")
    conn.execute("UPDATE videos SET archive_path = ? WHERE id = ?",
                 ("../../../../Windows/win.ini", vid))
    conn.commit()

    # Falls back to the (absent) flat proxy -> 404, never the traversed file.
    r = client.get(f"/media/proxy/{vid}.mp4")
    assert r.status_code == 404
