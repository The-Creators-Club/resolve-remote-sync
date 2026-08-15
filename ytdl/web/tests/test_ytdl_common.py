"""The naming contract both executors run under (docs/YTDL_LOCAL_DOWNLOAD.md §5).

`ytdl_common` is vendored into the companion in phase 2, so these tests are the
server half of a parity pin: what they hold together here is what the two trees
must keep agreeing about, and the release-time parity check (tools/release.ps1,
the same mechanism that already refuses on installer drift) is what will hold
the copies together.

Divergence here is silent data skew fleet-wide: two spellings of one clip in
one canonical tree, discovered months later by an editor wondering why the
folder has the same video twice.
"""
import ast
import inspect
import json

from ytdlweb import worker, ytdl_common
from ytdlweb.vendor import downloader


def test_it_imports_nothing_from_this_app():
    """The companion has no ytdlweb, no FastAPI and no yt-dlp LIBRARY (it drives
    the standalone binary, plan §6). A vendored copy that imported any of them
    would not import at all on the other side of the fleet.

    Parsed rather than grepped: the module's prose says the word `ytdlweb`
    several times explaining exactly this, and a substring test would forbid
    the documentation of the rule it is enforcing."""
    tree = ast.parse(inspect.getsource(ytdl_common))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split('.')[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or '').split('.')[0])
    assert imported <= {'os', 'pathlib'}, f'stdlib only, got {sorted(imported)}'


def test_the_outtmpl_is_the_one_the_downloader_actually_uses():
    """One template string, not two. build_opts cannot be CALLED here (it
    imports yt_dlp's postprocessor lazily and this venv has no yt-dlp), so the
    pin is on its source -- which is also what a reviewer reads."""
    src = inspect.getsource(downloader.build_opts)
    assert f'"{ytdl_common.OUTTMPL}"' in src
    assert ytdl_common.outtmpl('/projects/x').endswith(ytdl_common.OUTTMPL)


_INFO = {
    'id': 'aaaaaaaaaaa', 'title': 'A clip', 'uploader': 'Some Channel',
    'channel': 'Some Channel Official', 'uploader_url': 'https://u',
    'channel_url': 'https://c', 'webpage_url': 'https://www.youtube.com/watch?v=x',
    'upload_date': '20260801', 'duration': 123.0,
}


def test_the_sidecar_builder_matches_the_sidecar_the_server_writes(tmp_path):
    """The Resolve credits script reads this file, so the field set is a
    published interface. The server's copy is written by the VENDORED
    downloader (which must not be edited); the companion's will be written by
    ytdl_common. This is where the two are held together."""
    video = tmp_path / 'A clip [aaaaaaaaaaa].mp4'
    video.write_bytes(b'x')
    written = json.loads(
        open(downloader._write_sidecar(_INFO, str(video)), encoding='utf-8').read())

    built = ytdl_common.credits_sidecar(_INFO)
    assert built == written
    # ...including the ORDER and the count. The plan's prose says nine fields;
    # the code has always written eight, and this is the number that is real.
    assert tuple(built) == ytdl_common.SIDECAR_FIELDS == tuple(written)
    assert len(ytdl_common.SIDECAR_FIELDS) == 8


def test_the_sidecar_goes_where_the_downloader_puts_it(tmp_path):
    video = tmp_path / 'A clip [aaaaaaaaaaa].mp4'
    video.write_bytes(b'x')
    assert ytdl_common.sidecar_path(str(video)) == \
        downloader._write_sidecar(_INFO, str(video))


def test_the_fallback_ladder_is_the_shared_one_the_worker_still_uses():
    """Moved out of worker.py on 2026-08-14; the worker's own answers must not
    have changed by a single rung (the whole point is that both executors make
    the SAME call on a truncated stream)."""
    heights = downloader.QUALITY_HEIGHTS
    for q in (*heights, 'audio', 'nonsense'):
        assert ytdl_common.lower_quality(q, heights) == worker._lower_quality(q)
    assert worker._lower_quality('1080p') == '720p'
    assert worker._lower_quality('best') == ytdl_common.BEST_FALLBACK_QUALITY
    # ...and the names the worker imported back are the shared objects
    assert worker.TRUNCATED_NOTE is ytdl_common.TRUNCATED_NOTE
    assert worker.BEST_FALLBACK_QUALITY is ytdl_common.BEST_FALLBACK_QUALITY
    assert worker._TRUNCATION_MARKERS is ytdl_common.TRUNCATION_MARKERS
    assert worker._stream_truncated is ytdl_common.stream_truncated


def test_the_quality_table_is_the_downloaders_own():
    """COPIED into ytdl_common for the companion (2026-08-14), because
    vendor/downloader.py is vendored verbatim and may not be edited and the
    companion cannot import it anyway. A copy is only safe while something
    fails when it drifts -- this is that something."""
    assert ytdl_common.QUALITY_HEIGHTS == downloader.QUALITY_HEIGHTS


def test_the_format_string_is_byte_identical_for_every_rung():
    """The `-f` argument is the request YouTube actually answers, so a
    divergence here is two executors downloading DIFFERENT streams for the
    same rung -- 1080p AVC on the NAS, 1080p VP9 on an editor's machine, one
    canonical tree, and nothing anywhere saying they differ.

    'audio' and an unknown rung are included: format_selector answers both
    (audio has its own branch, unknown falls through to the uncapped generic),
    and the companion refuses them at a different layer -- this pin is about
    the STRING, not about what the local executor chooses to run."""
    for quality in (*downloader.QUALITY_HEIGHTS, 'audio', 'nonsense'):
        for prefer_avc in (True, False):
            assert (ytdl_common.format_selector(quality, prefer_avc)
                    == downloader.format_selector(quality, prefer_avc)), quality
    # ...and the default argument, which is what both executors actually call
    # it with for h264 output.
    assert ytdl_common.format_selector('1080p') == downloader.format_selector('1080p')


def test_the_versions_are_integers_the_handshake_can_compare():
    """The manifest carries them and a companion compares them; a string
    '1' vs 1 would compare unequal in JSON for no reason anybody could see."""
    assert isinstance(ytdl_common.TEMPLATE_VERSION, int)
    assert isinstance(ytdl_common.SIDECAR_VERSION, int)
