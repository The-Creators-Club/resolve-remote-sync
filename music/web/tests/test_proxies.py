"""128k mp3 preview proxies -- port step 6.

Two halves, both here because they are two ends of one contract: the generator
(`music_index/proxies.py`, base rig) decides what to write and where, and
`/api/audio/{id}` decides what to serve. The filename is the entire handshake
between them -- there is no database column -- so a test that only exercised one
side would happily pass while the two disagreed about it.

The indexer half is skipped rather than failed when `music/indexer` is not
checked out, matching how the app itself treats a web-only tree.
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from musicweb import config
from tests.conftest import AUDIO_BYTES

# Deliberately a different length from the seeded original: every Content-Range
# assertion below would still pass if the route served the wrong file when the
# two sizes matched.
PROXY_BYTES = b'ID3\x03\x00\x00\x00' + bytes(range(199)) * 7    # 1400 bytes
PROXIED_TRACK = 2        # 01JBF47TBD7T37HMG3WXZ8HQTS.mp3
BARE_TRACK = 1           # ES_Tense Pulse.wav -- no proxy, must still play


@pytest.fixture()
def proxied(seeded_db):
    """One track with a proxy on disk, removed again afterwards.

    Created here rather than in conftest because the *absence* of a proxy is
    what every other test in the suite relies on: `/api/audio/1` returning the
    original bytes is test_media_range's whole premise.
    """
    config.ensure_proxies_dir()
    path = config.proxy_path(PROXIED_TRACK)
    path.write_bytes(PROXY_BYTES)
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


# --------------------------------------------------------------- the route

def test_the_proxy_is_served_when_one_exists(client, proxied):
    r = client.get(f'/api/audio/{PROXIED_TRACK}')
    assert r.status_code == 200
    assert r.content == PROXY_BYTES
    assert r.headers['x-audio-source'] == 'proxy'


def test_range_over_a_proxy_reports_the_proxy_size(client, proxied):
    """206 keeps working, and every offset is the served file's.

    The inline player seeks with these; answering a range against the proxy
    with the original's total would make the client compute every later seek
    from a length the body does not have.
    """
    n = len(PROXY_BYTES)
    r = client.get(f'/api/audio/{PROXIED_TRACK}', headers={'Range': 'bytes=10-109'})
    assert r.status_code == 206
    assert r.headers['content-range'] == f'bytes 10-109/{n}'
    assert r.headers['content-length'] == '100'
    assert r.headers['accept-ranges'] == 'bytes'
    assert r.content == PROXY_BYTES[10:110]
    assert n != len(AUDIO_BYTES)                 # the assertions above mean something


def test_open_ended_range_over_a_proxy(client, proxied):
    n = len(PROXY_BYTES)
    r = client.get(f'/api/audio/{PROXIED_TRACK}', headers={'Range': 'bytes=1390-'})
    assert r.status_code == 206
    assert r.headers['content-range'] == f'bytes 1390-{n - 1}/{n}'
    assert r.content == PROXY_BYTES[-10:]


def test_original_query_param_serves_the_original(client, proxied):
    r = client.get(f'/api/audio/{PROXIED_TRACK}?original=1')
    assert r.status_code == 200
    assert r.content == AUDIO_BYTES
    assert r.headers['x-audio-source'] == 'original'


def test_original_query_param_ranges_against_the_original_size(client, proxied):
    n = len(AUDIO_BYTES)
    r = client.get(f'/api/audio/{PROXIED_TRACK}?original=1',
                   headers={'Range': 'bytes=0-49'})
    assert r.status_code == 206
    assert r.headers['content-range'] == f'bytes 0-49/{n}'
    assert r.content == AUDIO_BYTES[:50]


def test_a_track_with_no_proxy_still_serves_its_original(client, proxied):
    """The fallback. A generator run that has not reached this track yet, a
    track added since, or a data root shipped without proxies at all must play
    rather than 404."""
    assert not config.proxy_path(BARE_TRACK).exists()
    r = client.get(f'/api/audio/{BARE_TRACK}')
    assert r.status_code == 200
    assert r.content == AUDIO_BYTES
    assert r.headers['x-audio-source'] == 'original'


def test_the_fallback_keeps_range_working(client):
    n = len(AUDIO_BYTES)
    r = client.get(f'/api/audio/{BARE_TRACK}', headers={'Range': 'bytes=0-99'})
    assert r.status_code == 206
    assert r.headers['content-range'] == f'bytes 0-99/{n}'
    assert r.headers['x-audio-source'] == 'original'


def test_unknown_track_is_still_404_even_with_original(client):
    assert client.get('/api/audio/999?original=1').status_code == 404


# --------------------------------------------------------------- the layout

def test_proxies_live_under_the_data_root_keyed_by_id():
    assert config.PROXIES_DIR == config.DATA_ROOT / 'proxies'
    assert config.proxy_path(7) == config.PROXIES_DIR / '7.mp3'


def test_a_track_id_can_never_contribute_a_path_segment():
    """The router's `int` hint is not the only caller this has to survive."""
    with pytest.raises(ValueError):
        config.proxy_path('../../etc/passwd')


def test_importing_config_does_not_create_the_proxies_dir(tmp_path):
    """A mkdir at import scope makes an unwritable data root an ImportError,
    which the dashboard mount reports as ABSENT ("never shipped") when the
    truth is DEGRADED ("here, and not writable by this uid"). Same rule as
    ensure_data_root, pinned the same way."""
    data_root = tmp_path / 'never-created'
    env = dict(os.environ, DATA_ROOT=str(data_root),
               MUSIC_DATA_ROOT=str(data_root),
               PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    r = subprocess.run(
        [sys.executable, '-c',
         'from musicweb import config; print(config.PROXIES_DIR)'],
        env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert str(data_root) in r.stdout
    assert not data_root.exists()


def test_ensure_proxies_dir_creates_it(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'PROXIES_DIR', tmp_path / 'a' / 'b')
    assert config.ensure_proxies_dir().is_dir()
    config.ensure_proxies_dir()                  # idempotent


# --------------------------------------------------------------- the generator

if not config.add_indexer_to_path():
    pytest.skip('music/indexer is not checked out here', allow_module_level=True)

from music_index import proxies                                  # noqa: E402

WAV = {'codec': 'pcm_s16le', 'kbps': 1411.0, 'duration': 120.0, 'channels': 2}
FLAC = {'codec': 'flac', 'kbps': 900.0, 'duration': 120.0, 'channels': 2}
MP3_128 = {'codec': 'mp3', 'kbps': 128.0, 'duration': 120.0, 'channels': 2}
MP3_VBR = {'codec': 'mp3', 'kbps': 131.0, 'duration': 120.0, 'channels': 2}
MP3_320 = {'codec': 'mp3', 'kbps': 320.0, 'duration': 120.0, 'channels': 2}
AAC_132 = {'codec': 'aac', 'kbps': 132.0, 'duration': 120.0, 'channels': 2}
AAC_192 = {'codec': 'aac', 'kbps': 192.0, 'duration': 120.0, 'channels': 2}
OGG_88 = {'codec': 'vorbis', 'kbps': 88.0, 'duration': 120.0, 'channels': 2}


@pytest.mark.parametrize('info,pointless', [
    (WAV, False),
    (FLAC, False),          # lossless never trips the rule
    (MP3_128, True),
    (MP3_VBR, True),        # VBR overshoot: re-encoding gains nothing
    (MP3_320, False),       # 2.5x saving, worth the generation
    # Measured on the real library, not assumed: these two came out BIGGER
    # (.ogg 4.6 -> 6.7 MB, .aac 3.8 -> 3.7 MB) when the rule was mp3-only.
    (AAC_132, True),
    (OGG_88, True),
    (AAC_192, False),
    ({}, False),            # unprobeable: decide on the encode, not on nothing
])
def test_pointless_re_encodes_are_recognised(info, pointless):
    assert proxies.is_pointless(info) is pointless


def _age(path, seconds):
    """Move a file's mtime relative to now. Positive = into the future."""
    t = time.time() + seconds
    os.utime(path, (t, t))


def test_freshness_is_mtime_against_the_source(tmp_path):
    src, dst = tmp_path / 's.wav', tmp_path / '1.mp3'
    src.write_bytes(b'source')
    assert proxies.is_fresh(src, dst) is False           # no proxy yet
    dst.write_bytes(b'proxy')
    _age(dst, -3600)
    assert proxies.is_fresh(src, dst) is False           # stale: source is newer
    _age(dst, 3600)
    assert proxies.is_fresh(src, dst) is True
    dst.write_bytes(b'')
    _age(dst, 3600)
    assert proxies.is_fresh(src, dst) is False           # empty is not finished


def _no_encoding(monkeypatch):
    """Any call to the encoder is a test failure, not a slow test."""
    def boom(*a, **k):
        raise AssertionError('encoded when it should not have')
    monkeypatch.setattr(proxies, 'build_one', boom)


def test_an_already_small_mp3_is_skipped_and_nothing_is_written(tmp_path, monkeypatch):
    src = tmp_path / 'small.mp3'
    src.write_bytes(b'x' * 1000)
    dst = tmp_path / '5.mp3'
    monkeypatch.setattr(proxies, 'source_info', lambda p: MP3_128)
    _no_encoding(monkeypatch)

    outcome, before, after, codec = proxies.build_track(5, src, dest=dst)
    assert outcome == proxies.ALREADY_SMALL
    assert not dst.exists()
    # It is still served -- as the original -- so it counts at its own size.
    assert (before, after, codec) == (1000, 1000, 'mp3')


def test_forcing_does_not_re_encode_an_already_small_mp3(tmp_path, monkeypatch):
    src = tmp_path / 'small.mp3'
    src.write_bytes(b'x' * 1000)
    monkeypatch.setattr(proxies, 'source_info', lambda p: MP3_128)
    _no_encoding(monkeypatch)
    outcome = proxies.build_track(6, src, dest=tmp_path / '6.mp3', force=True)[0]
    assert outcome == proxies.ALREADY_SMALL


def test_a_current_proxy_is_left_alone(tmp_path, monkeypatch):
    src, dst = tmp_path / 'a.wav', tmp_path / '7.mp3'
    src.write_bytes(b'x' * 6000)
    dst.write_bytes(b'y' * 500)
    _age(dst, 3600)
    _no_encoding(monkeypatch)

    outcome, before, after, _ = proxies.build_track(7, src, dest=dst)
    assert (outcome, before, after) == (proxies.FRESH, 6000, 500)


def test_a_stale_proxy_is_rebuilt(tmp_path, monkeypatch):
    src, dst = tmp_path / 'a.wav', tmp_path / '8.mp3'
    src.write_bytes(b'x' * 6000)
    dst.write_bytes(b'old')
    _age(dst, -3600)
    monkeypatch.setattr(proxies, 'source_info', lambda p: WAV)
    monkeypatch.setattr(proxies, 'build_one', lambda *a, **k: 900)

    assert proxies.build_track(8, src, dest=dst) == (proxies.BUILT, 6000, 900,
                                                     'pcm_s16le')


def test_a_source_that_is_not_on_this_host(tmp_path):
    assert proxies.build_track(9, tmp_path / 'gone.wav') == (proxies.MISSING, 0, 0, '')


def test_build_all_totals_what_a_preview_costs_before_and_after(tmp_path, monkeypatch):
    """The saving figure counts skipped mp3s at their own size, because those
    are still served from the original -- otherwise the ratio flatters itself
    by ignoring every file it declined to shrink."""
    wav, mp3 = tmp_path / 'big.wav', tmp_path / 'small.mp3'
    wav.write_bytes(b'x' * 60_000_000)
    mp3.write_bytes(b'y' * 2_000_000)
    monkeypatch.setattr(proxies, 'source_info',
                        lambda p: MP3_128 if str(p).endswith('.mp3') else WAV)
    monkeypatch.setattr(proxies, 'build_one', lambda *a, **k: 1_900_000)
    monkeypatch.setattr(proxies, 'proxy_path', lambda i: tmp_path / f'{i}.mp3')

    s = proxies.build_all([(1, wav), (2, mp3), (3, tmp_path / 'gone.flac')],
                          jobs=2, log=lambda *a, **k: None)
    assert s['total'] == 3
    assert (s[proxies.BUILT], s[proxies.ALREADY_SMALL], s[proxies.MISSING]) == (1, 1, 1)
    assert s[proxies.FAILED] == 0
    assert s['before_bytes'] == 62_000_000
    assert s['after_bytes'] == 3_900_000
    assert s['skipped_codecs'] == {'mp3': 1}


def test_one_bad_file_does_not_take_the_run_down(tmp_path, monkeypatch):
    good, bad = tmp_path / 'g.wav', tmp_path / 'b.wav'
    good.write_bytes(b'x' * 100)
    bad.write_bytes(b'not audio')
    monkeypatch.setattr(proxies, 'source_info',
                        lambda p: {} if str(p).endswith('b.wav') else WAV)
    monkeypatch.setattr(proxies, 'build_one', lambda *a, **k: 40)
    monkeypatch.setattr(proxies, 'proxy_path', lambda i: tmp_path / f'{i}.mp3')

    s = proxies.build_all([(1, good), (2, bad)], jobs=1, log=lambda *a, **k: None)
    assert (s[proxies.BUILT], s[proxies.FAILED]) == (1, 1)
    assert s['failures'][0][0] == 2


def test_orphans_finds_reusable_ids_and_interrupted_encodes(tmp_path):
    for name in ('1.mp3', '2.mp3', '3.mp3', '3.mp3.part', 'notes.txt', 'x.mp3'):
        (tmp_path / name).write_bytes(b'')
    found = {p.name for p in proxies.orphans([1, 3], directory=tmp_path)}
    # 2 is gone from the DB, and SQLite reuses a freed rowid -- a stale proxy
    # would then be served as a completely different track's audio.
    assert found == {'2.mp3', '3.mp3.part', 'x.mp3'}
    assert not (tmp_path / 'notes.txt').name in found


def test_orphans_on_a_host_with_no_proxies_dir(tmp_path):
    assert proxies.orphans([1], directory=tmp_path / 'nope') == []


# ------------------------------------------------------------- with real ffmpeg

ffmpeg_only = pytest.mark.skipif(
    not Path(proxies.config.FFMPEG).exists(), reason='ffmpeg not on this host')


@ffmpeg_only
def test_a_real_encode_shrinks_the_file_and_lands_atomically(tmp_path):
    """End to end against the actual encoder: a wav in, a smaller mp3 out, of
    the same duration, with no .part left behind."""
    src = tmp_path / 'sine.wav'
    subprocess.run([proxies.config.FFMPEG, '-y', '-v', 'error', '-f', 'lavfi',
                    '-i', 'sine=frequency=440:duration=5', '-ar', '48000',
                    '-ac', '2', '-c:a', 'pcm_s16le', str(src)], check=True)
    info = proxies.source_info(src)
    assert info['codec'] == 'pcm_s16le'
    assert not proxies.is_pointless(info)

    dst = tmp_path / '42.mp3'
    size = proxies.build_one(src, dst, channels=info['channels'],
                             duration=info['duration'])
    assert dst.is_file() and size == dst.stat().st_size
    assert size < src.stat().st_size / 5
    assert not (tmp_path / '42.mp3.part').exists()

    out = proxies.source_info(dst)
    assert out['codec'] == 'mp3'
    assert abs(out['duration'] - 5.0) < 0.2
    assert 120 < out['kbps'] < 140


@ffmpeg_only
def test_an_estimated_source_duration_does_not_fake_a_truncation(tmp_path):
    """The real-library bug this check was rewritten for.

    Raw ADTS .aac reports `size * 8 / bit_rate` as its duration, which on this
    library overshoots the truth by 6-53%. Twenty-five complete proxies were
    rejected as "truncated" against it. Here the source is a real 5s file and
    the caller passes a wrong, inflated duration -- the encode must survive it,
    because the decode says otherwise.
    """
    src = tmp_path / 'sine.wav'
    subprocess.run([proxies.config.FFMPEG, '-y', '-v', 'error', '-f', 'lavfi',
                    '-i', 'sine=frequency=440:duration=5', '-ar', '44100',
                    '-ac', '2', '-c:a', 'pcm_s16le', str(src)], check=True)
    assert abs(proxies.decoded_duration(src) - 5.0) < 0.2

    dst = tmp_path / '44.mp3'
    assert proxies.build_one(src, dst, duration=11.0) > 0
    assert dst.is_file()


@ffmpeg_only
def test_a_genuinely_short_proxy_is_still_rejected(tmp_path, monkeypatch):
    """The safety net itself: neither yardstick agrees with the output."""
    src = tmp_path / 'sine.wav'
    subprocess.run([proxies.config.FFMPEG, '-y', '-v', 'error', '-f', 'lavfi',
                    '-i', 'sine=frequency=440:duration=5', '-ar', '44100',
                    '-ac', '2', '-c:a', 'pcm_s16le', str(src)], check=True)
    # stand in for an encoder that stopped a second in
    monkeypatch.setattr(proxies, 'source_info', lambda p: {'duration': 1.0})

    dst = tmp_path / '45.mp3'
    with pytest.raises(RuntimeError, match='truncated'):
        proxies.build_one(src, dst, duration=5.0)
    assert not dst.exists()                       # and nothing was published
    assert not (tmp_path / '45.mp3.part').exists()


@ffmpeg_only
def test_decoded_duration_of_something_undecodable_is_zero(tmp_path):
    junk = tmp_path / 'junk.aac'
    junk.write_bytes(b'\x00' * 500)
    assert proxies.decoded_duration(junk) == 0.0


@ffmpeg_only
def test_a_file_that_is_not_audio_fails_loudly(tmp_path):
    junk = tmp_path / 'junk.wav'
    junk.write_bytes(b'this is not audio' * 100)
    assert proxies.source_info(junk) == {}
    with pytest.raises(RuntimeError):
        proxies.build_track(43, junk, dest=tmp_path / '43.mp3')


# ---------------------------------------------------- the generator's driver
# make_proxies.py is a script, not a package; add_indexer_to_path() above is
# what makes it importable, and it needs no torch (unlike index_music.py).

def test_a_row_with_an_unknown_share_is_skipped_not_fatal(capsys):
    """MUSIC-12 (2026-08-11): `items_for` caught only PathTraversalError, but
    `resolve_path` raises UnknownShareError too -- a NULL or foreign `share`
    (one row) killed the whole run before a single track was encoded.
    `music_index.config` did not even re-export the class to catch it with."""
    import make_proxies

    assert make_proxies.config.UnknownShareError is config.UnknownShareError

    rows = [{'id': 1, 'share': config.SHARE, 'rel_path': 'good.wav'},
            {'id': 2, 'share': None, 'rel_path': 'null-share.wav'},
            {'id': 3, 'share': 'someone-elses', 'rel_path': 'foreign.wav'},
            {'id': 4, 'share': config.SHARE, 'rel_path': '../escape.wav'},
            {'id': 5, 'share': config.SHARE, 'rel_path': 'also-good.wav'}]

    items = make_proxies.items_for(rows)

    assert [tid for tid, _ in items] == [1, 5]
    out = capsys.readouterr().out
    for name in ('null-share.wav', 'foreign.wav', 'escape.wav'):
        assert name in out, f'{name} was skipped silently'


# --------------------------------------- music-4: the id a deleted track left

def test_pruning_a_track_takes_its_proxy_with_it(tmp_path, monkeypatch):
    """`tracks.id` is INTEGER PRIMARY KEY with no AUTOINCREMENT, so the next
    insert takes max(rowid)+1 -- the id of the highest row just deleted. The
    proxy is chosen on existence alone, so leaving it behind gives the NEXT
    track a deleted cue's audio (music-4, 2026-08-21). Deletion frees the id,
    so deletion removes the file."""
    from musicweb import db

    monkeypatch.setattr(config, 'PROXIES_DIR', tmp_path / 'proxies')
    con = db.connect(tmp_path / 'prune.db')
    db.init(con)
    try:
        for i, rel in enumerate(('a.wav', 'gone.wav'), start=1):
            con.execute('INSERT INTO tracks(id,rel_path,filename,embedding,dim) '
                        'VALUES(?,?,?,?,4)', (i, rel, rel, db.to_blob([0.5] * 4)))
        con.commit()
        config.ensure_proxies_dir()
        kept, doomed = config.proxy_path(1), config.proxy_path(2)
        kept.write_bytes(PROXY_BYTES)
        doomed.write_bytes(PROXY_BYTES)

        assert db.prune_missing(con, ['a.wav']) == ['gone.wav']

        assert not doomed.exists(), 'the freed id kept a proxy of other audio'
        assert kept.exists(), 'a surviving track lost its preview'
    finally:
        con.close()
