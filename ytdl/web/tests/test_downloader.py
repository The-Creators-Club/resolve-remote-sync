"""The vendored downloader's decisions, with ffmpeg/ffprobe and yt-dlp as seams.

Nothing here shells out or touches the network: `subprocess.run` is replaced
where the module calls it, and the two functions that need a YoutubeDL are
exercised through the object's own surface (`prepare_filename`). That is the
same property that lets the app mount in a container that has neither -- and
these are the paths where a wrong answer is SILENT: a file delivered in a codec
Resolve cannot decode, or a ledger row pointing at nothing.
"""
import json
import os
import types
from pathlib import Path
from unittest import mock

import pytest

from ytdlweb.vendor import downloader


# ------------------------------------------------------------ format selector

@pytest.mark.parametrize('quality', ['best', '1440p', '2160p'])
def test_above_1080p_asks_for_the_best_stream_not_the_avc_one(quality):
    """YTDL-4 (2026-08-11): yt-dlp takes the first SATISFIABLE alternative, and
    `[height<=2160][vcodec^=avc1]` is satisfied by the 1080p AVC stream nearly
    every video has. Prepending it capped 4K jobs at 1080p, reported success,
    and made the whole ensure_edit_ready path for high-res sources dead code."""
    fmt = downloader.format_selector(quality, prefer_avc=True)
    assert 'avc1' not in fmt
    assert fmt == downloader.format_selector(quality, prefer_avc=False)


@pytest.mark.parametrize('quality', ['1080p', '720p', '480p'])
def test_at_or_below_1080p_avc_is_still_preferred(quality):
    """Where YouTube actually serves AVC, asking for it saves the re-encode."""
    fmt = downloader.format_selector(quality, prefer_avc=True)
    assert fmt.startswith(f'bestvideo[height<={quality[:-1]}][vcodec^=avc1]')
    # ...and the generic selector is still the last alternative
    assert fmt.endswith(downloader.format_selector(quality, prefer_avc=False))


def test_the_selector_still_bounds_the_height_it_asks_for():
    assert '[height<=2160]' in downloader.format_selector('2160p')
    assert '[height<=' not in downloader.format_selector('best')


# ------------------------------------------------------------ where it landed

class FakeYdl:
    """Just the surface _final_filepath uses."""

    def __init__(self, guess, raises=False):
        self.guess = guess
        self.raises = raises

    def prepare_filename(self, info):
        if self.raises:
            raise RuntimeError('no output template for this info dict')
        return self.guess


def test_the_landed_path_comes_from_yt_dlps_own_record(tmp_path):
    """YTDL-15 (2026-08-11): requested_downloads carries the path AFTER the
    merge and the post-processors; prepare_filename only predicts one."""
    real = tmp_path / 'Chan - T [aaaaaaaaaaa].mkv'
    real.write_bytes(b'x')
    info = {'requested_downloads': [{'filepath': str(real)}]}
    ydl = FakeYdl(str(tmp_path / 'Chan - T [aaaaaaaaaaa].webm'))
    assert downloader._final_filepath(ydl, info) == str(real)


def test_a_merged_extension_is_found_when_yt_dlp_recorded_nothing(tmp_path):
    landed = tmp_path / 'Chan - T [aaaaaaaaaaa].mp4'
    landed.write_bytes(b'x')
    ydl = FakeYdl(str(tmp_path / 'Chan - T [aaaaaaaaaaa].webm'))
    assert downloader._final_filepath(ydl, {}) == str(landed)


def test_nothing_on_disk_is_none_not_a_path_that_does_not_exist(tmp_path):
    """None is the contract the worker's ledger guard reads: a path that does
    not exist would become a ledger row pointing at nothing, forever."""
    ydl = FakeYdl(str(tmp_path / 'Chan - T [aaaaaaaaaaa].webm'))
    assert downloader._final_filepath(ydl, {}) is None
    assert downloader._final_filepath(ydl, {'requested_downloads': [{}]}) is None
    assert downloader._final_filepath(FakeYdl(None, raises=True), {}) is None


def test_a_recorded_path_that_vanished_falls_back_rather_than_lying(tmp_path):
    landed = tmp_path / 'Chan - T [aaaaaaaaaaa].mp4'
    landed.write_bytes(b'x')
    info = {'requested_downloads': [{'filepath': str(tmp_path / 'gone.mp4')}]}
    ydl = FakeYdl(str(landed))
    assert downloader._final_filepath(ydl, info) == str(landed)


# ----------------------------------------------------------------- the probe

def _fake_run(monkeypatch, returncode=0, stdout='', stderr='', calls=None):
    def run(cmd, **_kw):
        if calls is not None:
            calls.append(cmd)
        return types.SimpleNamespace(returncode=returncode, stdout=stdout,
                                     stderr=stderr)
    monkeypatch.setattr(downloader.subprocess, 'run', run)


def _streams(vcodec='h264', acodec='aac', avg='30/1', r='30/1'):
    return json.dumps({'streams': [
        {'codec_type': 'video', 'codec_name': vcodec,
         'avg_frame_rate': avg, 'r_frame_rate': r},
        {'codec_type': 'audio', 'codec_name': acodec}]})


def test_a_failed_probe_is_not_the_same_as_an_audio_only_file(monkeypatch):
    """YTDL-22 (2026-08-11): probe_streams returned {} on any failure, which
    ensure_edit_ready read as "no video stream, nothing to fix" -- so a
    container whose /opt/ffmpeg has no ffprobe delivered every VP9/Opus download
    unconverted and silent."""
    _fake_run(monkeypatch, returncode=1, stderr='ffprobe: not found')
    assert downloader.probe_streams('x.mp4').get('_probe_error')

    _fake_run(monkeypatch, returncode=0, stdout='{"streams": []}')
    probe = downloader.probe_streams('x.mp4')
    assert probe == {'streams': []} and not probe.get('_probe_error')

    _fake_run(monkeypatch, returncode=0, stdout='not json at all')
    assert downloader.probe_streams('x.mp4').get('_probe_error')


def test_an_unprobeable_file_is_converted_on_suspicion(monkeypatch, tmp_path):
    src = tmp_path / 'clip.mp4'
    src.write_bytes(b'x')
    cmds = []

    def run(cmd, **_kw):
        cmds.append(cmd)
        if 'ffprobe' in cmd[0]:
            return types.SimpleNamespace(returncode=1, stdout='', stderr='boom')
        (tmp_path / 'clip.editready.mp4').write_bytes(b'converted')
        return types.SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(downloader.subprocess, 'run', run)
    out = downloader.ensure_edit_ready(str(src), 'h264')
    assert out == str(src)                       # swapped back over the original
    assert src.read_bytes() == b'converted'
    assert any('libx264' in c for c in cmds[-1])


def test_a_conversion_we_only_guessed_at_is_not_fatal(monkeypatch, tmp_path):
    """An audio-only download makes `-map 0:v:0` fail outright. Losing the video
    over a conversion ffprobe never said was needed is worse than delivering it
    as downloaded."""
    src = tmp_path / 'clip.m4a'
    src.write_bytes(b'audio')
    said = []

    def run(cmd, **_kw):
        return types.SimpleNamespace(returncode=1, stdout='', stderr='no video')

    monkeypatch.setattr(downloader.subprocess, 'run', run)
    assert downloader.ensure_edit_ready(str(src), 'h264',
                                        on_status=said.append) == str(src)
    assert src.read_bytes() == b'audio'
    assert any('could not probe' in s for s in said)


def test_a_genuinely_audio_only_file_is_still_left_alone(monkeypatch, tmp_path):
    src = tmp_path / 'clip.m4a'
    src.write_bytes(b'audio')
    _fake_run(monkeypatch, stdout=json.dumps(
        {'streams': [{'codec_type': 'audio', 'codec_name': 'aac'}]}))
    assert downloader.ensure_edit_ready(str(src), 'h264') == str(src)


def test_a_real_conversion_failure_still_raises(monkeypatch, tmp_path):
    """The worker turns this into a failed row (and disowns the leftover);
    silently returning the VP9 file is what YTDL-22 must NOT become."""
    src = tmp_path / 'clip.mp4'
    src.write_bytes(b'x')

    def run(cmd, **_kw):
        if 'ffprobe' in cmd[0]:
            return types.SimpleNamespace(returncode=0, stdout=_streams(vcodec='vp9'),
                                         stderr='')
        return types.SimpleNamespace(returncode=1, stdout='', stderr='disk full')

    monkeypatch.setattr(downloader.subprocess, 'run', run)
    with pytest.raises(RuntimeError, match='Edit-ready conversion failed'):
        downloader.ensure_edit_ready(str(src), 'h264')


# ------------------------------------------------------------- frame rates

@pytest.mark.parametrize('avg,r', [
    ('30/1', '30/1'),
    ('24000/1001', '24/1'),        # the same rate, differently reduced-ish
    ('30000/1001', '2997/100'),
    ('25/1', '25/1'),
    (None, '30/1'),                # unreadable: not worth a re-encode
])
def test_equal_frame_rates_are_not_vfr(avg, r):
    """YTDL-23 (2026-08-11): comparing ffprobe's raw fraction STRINGS made
    every one of these read as VFR and triggered a full libx264 re-encode --
    generation loss plus minutes of container CPU on a file that was fine."""
    assert downloader._same_rate(avg, r)


@pytest.mark.parametrize('avg,r', [
    ('9723/1000', '30/1'),         # a screen recording: genuinely variable
    ('15/1', '30/1'),
])
def test_a_genuinely_variable_frame_rate_is_still_caught(avg, r):
    assert not downloader._same_rate(avg, r)


def test_an_avc_file_at_a_reduced_frame_rate_is_stream_copied(monkeypatch, tmp_path):
    """The whole point: an AVC/AAC download must cost nothing."""
    src = tmp_path / 'clip.mp4'
    src.write_bytes(b'avc')
    _fake_run(monkeypatch, stdout=_streams(avg='24000/1001', r='24/1'))
    assert downloader.ensure_edit_ready(str(src), 'h264') == str(src)
    assert src.read_bytes() == b'avc'


# ------------------------------------------------------ the scratch directory

def test_yt_dlps_scratch_dir_is_the_outdir_and_never_the_process_cwd(tmp_path):
    """CR-33 (2026-08-19): every clip whose format ladder made yt-dlp TEST a
    format died instantly with

        [Errno 13] Permission denied: '/tmpf1m0z55x.tmp'

    yt-dlp resolves its scratch dir as sanitize_path(join(paths['home'],
    paths['temp']), force=windowsfilenames). With no `paths` that is
    sanitize_path('', force=True), which is os.path.normpath('') == '.' -- and
    the container's cwd is '/', which uid 3000 cannot write. Nothing in this
    repo ever named that path, which is what made it hard to find.

    The assertion is on `paths['home']` rather than on the resolved scratch dir
    because the resolution is yt-dlp's; what this file owns is that we hand it
    a real, writable, absolute directory instead of nothing at all.
    """
    opts = downloader.build_opts(str(tmp_path), quality='1080p')
    assert opts['paths'] == {'home': str(tmp_path)}


def test_the_scratch_dir_did_not_move_the_output_filename(tmp_path):
    """`home` is joined with the filename, and the outtmpl is ABSOLUTE -- so
    os.path.join keeps the absolute half and the naming contract with
    ytdl_common (which the companion's outtmpl has to match byte for byte) is
    untouched. This is the half of CR-33's fix that could have gone wrong
    silently: a clip filed one directory up would still download.
    """
    yt_dlp = pytest.importorskip('yt_dlp')
    opts = downloader.build_opts(str(tmp_path), quality='1080p')
    info = {'id': 'abc123', 'title': 'A Clip', 'uploader': 'Someone', 'ext': 'mp4'}

    with_paths = yt_dlp.YoutubeDL(dict(opts, quiet=True)).prepare_filename(info)
    without = dict(opts)
    without.pop('paths')
    bare = yt_dlp.YoutubeDL(dict(without, quiet=True)).prepare_filename(info)

    assert with_paths == bare
    assert str(tmp_path) in with_paths


def test_temp_is_left_alone_so_partials_stay_beside_their_clip(tmp_path):
    """Setting paths['temp'] would move `.part` files and fragments out of the
    clip's folder, and the partial-cleanup, dedupe and disown paths in worker.py
    all rglob that folder. CR-33 deliberately set only `home`.
    """
    opts = downloader.build_opts(str(tmp_path), quality='1080p')
    assert 'temp' not in opts['paths']


def test_fragments_download_in_parallel_and_the_knob_is_bounded(tmp_path, monkeypatch):
    """CR-74 (2026-08-24): with a PO token YouTube still SABR-forces the https
    formats away, so nearly every server download is an m3u8 ladder -- whose
    fragments were fetched ONE at a time, at whatever pace YouTube gives a
    single connection (3-4 MiB/s sustained on a long clip, measured live,
    against 53 MiB/s with six in flight). The env override is an operator
    lever; junk and out-of-range values must not take the download down."""
    monkeypatch.delenv(downloader.FRAGMENT_JOBS_ENV, raising=False)
    opts = downloader.build_opts(str(tmp_path), quality='1080p')
    assert opts['concurrent_fragment_downloads'] == 6

    monkeypatch.setenv(downloader.FRAGMENT_JOBS_ENV, '3')
    assert downloader.fragment_jobs() == 3
    monkeypatch.setenv(downloader.FRAGMENT_JOBS_ENV, '0')
    assert downloader.fragment_jobs() == 1        # 1 is the old behaviour
    monkeypatch.setenv(downloader.FRAGMENT_JOBS_ENV, '99')
    assert downloader.fragment_jobs() == 16       # bulk-automation ceiling
    monkeypatch.setenv(downloader.FRAGMENT_JOBS_ENV, 'junk')
    assert downloader.fragment_jobs() == 6


# ------------------------------------------------ the mtime and the swap (YT-3/YT-6)

def test_the_finished_file_is_not_stamped_with_youtubes_upload_date(tmp_path):
    """YT-3 (resilience sweep 2026-08-28): without --no-mtime yt-dlp stamps the
    media response's Last-Modified on the finished file, which for YouTube is
    usually the upload date. The canonical tree IS the download workspace, and
    every consumer that gates on age reads that date: the companion's lane A
    `--min-age 120s` most of all, which is the only thing standing between a
    still-converting original and `copy --ignore-existing` making it the
    fleet's permanent copy of the clip."""
    opts = downloader.build_opts(str(tmp_path), quality='1080p')
    assert opts['updatetime'] is False


def test_the_fallback_deliverable_keeps_the_id_last_in_its_stem(tmp_path):
    """YT-6: `<stem>.editready.mp4` was a deliverable that no sweep could
    touch (it was the clip) and no dedupe could recognise (its stem ended
    `.editready`, not `[id]`), so the companion's importer filed it into the
    media pool as a SECOND clip. The marker goes in front of the bracket."""
    assert (downloader.converted_name('/x/Chan - T [abcdefghijk].mp4')
            == str(Path('/x/Chan - T.converted [abcdefghijk].mp4')))
    # a title with brackets of its own keeps them: only the LAST group is the id
    assert (downloader.converted_name('/x/Chan - T [live] [abcdefghijk].mp4')
            == str(Path('/x/Chan - T [live].converted [abcdefghijk].mp4')))
    # and a name this executor did not write is at least distinguishable
    assert (downloader.converted_name('/x/whatever.mp4')
            == str(Path('/x/whatever.converted.mp4')))


def test_a_locked_original_delivers_under_the_converted_name_with_a_note(tmp_path):
    """The Windows case YT-6 is about: the clip is open in the editor's Resolve
    project, so neither the delete nor the rename-aside is allowed. The work is
    kept, under a name whose stem still ends in `[id]`, and the note that
    explains it now reaches the clip row and not only the live progress dict."""
    original = tmp_path / 'Chan - T [abcdefghijk].webm'
    tmp = tmp_path / 'Chan - T [abcdefghijk].editready.mp4'
    original.write_bytes(b'vp9')
    tmp.write_bytes(b'h264')
    final = str(tmp_path / 'Chan - T [abcdefghijk].mp4')

    def refuse(*a, **kw):
        raise OSError('Access is denied')

    notes = []
    real_replace = os.replace

    def replace(src, dst):
        if str(dst).endswith('.original.webm') or str(dst) == final:
            raise OSError('Access is denied')
        return real_replace(src, dst)

    with mock.patch('os.remove', refuse), mock.patch('os.replace', replace):
        got = downloader._swap_in(str(tmp), final, str(original), None, notes)

    assert Path(got).name == 'Chan - T.converted [abcdefghijk].mp4'
    assert Path(got).exists() and original.exists()
    assert notes and 'was in use' in notes[0]
    assert 'saved as Chan - T.converted [abcdefghijk].mp4' in notes[0]
