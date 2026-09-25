"""bug-comp-ytdl-1 (2026-09-24), the NAS worker's half.

The vendored ensure_edit_ready re-encoded the landed `<title> [id].<ext>` IN
PLACE, so for the whole conversion the VP9 original sat in the canonical tree
under its deliverable name. A re-encode past 120 s let the base rig's importer
(which reads the NAS tree over the share, 120 s settle) file it into the
Resolve pool, and the swap then delivered a second clip beside it. The
original is now staged under `<stem>.source.editready.<ext>` while ffmpeg runs,
the same name the companion's executor uses.

subprocess.run is the seam, as in test_downloader.py: nothing shells out.
"""
import types
from pathlib import Path

import pytest

from ytdlweb import worker
from ytdlweb.vendor import downloader

VID = 'aaaaaaaaaaa'
VP9 = ('{"streams": [{"codec_type": "video", "codec_name": "vp9", '
       '"avg_frame_rate": "30/1", "r_frame_rate": "30/1"}, '
       '{"codec_type": "audio", "codec_name": "opus"}]}')


def _deliverables(outdir):
    """Every name a clip consumer would take: the worker's own rule, and the
    importer's anchoring rule (stem ends in `[id]`, not litter)."""
    return sorted(p.name for p in Path(outdir).iterdir()
                  if p.stem.endswith(f'[{VID}]') and not worker._sweepable(p.name)
                  and not p.name.endswith(worker.DISOWNED_SUFFIX))


@pytest.mark.parametrize('ext', ['.mp4', '.webm'])
def test_a_long_conversion_never_leaves_the_original_under_its_deliverable_name(
        monkeypatch, tmp_path, ext):
    src = tmp_path / f'Some Channel - A clip [{VID}]{ext}'
    src.write_bytes(b'vp9 original')
    seen = {}

    def run(cmd, **_kw):
        if 'ffprobe' in cmd[0]:
            return types.SimpleNamespace(returncode=0, stdout=VP9, stderr='')
        # ffmpeg "running": this is the window a consumer must not see a clip in
        seen['during'] = _deliverables(tmp_path)
        seen['landed'] = worker._landed_file(tmp_path, VID)
        Path(cmd[-1]).write_bytes(b'converted')
        return types.SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(downloader.subprocess, 'run', run)
    out = downloader.ensure_edit_ready(str(src), 'h264')

    assert seen == {'during': [], 'landed': None}
    final = tmp_path / f'Some Channel - A clip [{VID}].mp4'
    assert out == str(final)
    assert final.read_bytes() == b'converted'
    # one clip afterwards, and no staged copy left over
    assert sorted(p.name for p in tmp_path.iterdir()) == [final.name]


def test_a_failed_conversion_puts_the_original_back_for_the_disown(
        monkeypatch, tmp_path):
    """YTDL-3's evidence: the worker renames what a failed attempt left to
    `.failed`, but skips a sweepable name, so the staged original has to be
    back under its own name before the RuntimeError leaves."""
    src = tmp_path / f'Some Channel - A clip [{VID}].mp4'
    src.write_bytes(b'vp9 original')

    def run(cmd, **_kw):
        if 'ffprobe' in cmd[0]:
            return types.SimpleNamespace(returncode=0, stdout=VP9, stderr='')
        return types.SimpleNamespace(returncode=1, stdout='', stderr='disk full')

    monkeypatch.setattr(downloader.subprocess, 'run', run)
    with pytest.raises(RuntimeError, match='Edit-ready conversion failed'):
        downloader.ensure_edit_ready(str(src), 'h264')
    assert src.read_bytes() == b'vp9 original'
    worker._disown_output(tmp_path, VID, before=set())
    assert sorted(p.name for p in tmp_path.iterdir()) == [src.name + '.failed']


def test_a_guessed_conversion_that_fails_still_delivers_as_downloaded(
        monkeypatch, tmp_path):
    src = tmp_path / f'Some Channel - A clip [{VID}].mp4'
    src.write_bytes(b'as downloaded')

    def run(cmd, **_kw):
        return types.SimpleNamespace(returncode=1, stdout='', stderr='nope')

    monkeypatch.setattr(downloader.subprocess, 'run', run)
    assert downloader.ensure_edit_ready(str(src), 'h264') == str(src)
    assert sorted(p.name for p in tmp_path.iterdir()) == [src.name]


def test_no_ffmpeg_keeps_the_download_under_its_own_name(monkeypatch, tmp_path):
    src = tmp_path / f'Some Channel - A clip [{VID}].mp4'
    src.write_bytes(b'as downloaded')

    def run(cmd, **_kw):
        if 'ffprobe' in cmd[0]:
            return types.SimpleNamespace(returncode=0, stdout=VP9, stderr='')
        raise FileNotFoundError('ffmpeg')

    monkeypatch.setattr(downloader.subprocess, 'run', run)
    assert downloader.ensure_edit_ready(str(src), 'h264') == str(src)
    assert src.read_bytes() == b'as downloaded'


def test_a_staged_original_left_by_a_kill_is_litter_to_every_sweep(tmp_path):
    """A container killed mid-ffmpeg leaves the staged file behind. It must be
    what _clear_partials (next attempt) and _sweep_stale (a day) remove, and
    never what _landed_file reads as the clip."""
    staged = Path(downloader.staged_source_name(
        str(tmp_path / f'Some Channel - A clip [{VID}].webm')))
    staged.write_bytes(b'x')
    assert worker._sweepable(staged.name)
    assert worker._landed_file(tmp_path, VID) is None
    worker._clear_partials(tmp_path, VID)
    assert not staged.exists()
