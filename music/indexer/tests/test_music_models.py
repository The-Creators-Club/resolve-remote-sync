"""The music model catalogue: pinned, self-consistent, and honest about it.

Cheap tests on purpose -- the expensive verification (cosine vs torch) lives
in the exporter, which cannot run in CI. What CAN be pinned here is that the
sha256s are real, that the filenames carry the version they claim, and that an
unpinned entry says so rather than being downloaded.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import music_models                                              # noqa: E402

HEX64 = re.compile(r'^[0-9a-f]{64}$')


def test_the_default_model_exists():
    assert music_models.DEFAULT_MODEL in music_models.MODELS
    assert music_models.model()['dim'] == 512


@pytest.mark.parametrize('key', sorted(music_models.MODELS))
def test_filenames_carry_the_version(key):
    entry = music_models.MODELS[key]
    onnx, params = music_models.filenames(key)
    assert onnx == f'music-clap-audio-{entry["version"]}.onnx'
    assert params == f'music-clap-audio-{entry["version"]}.params.json'
    # The sha/size tables are keyed by filename, so a version bump that forgets
    # one of them would ship a pin for a file nobody downloads.
    assert set(entry['sha256']) == {onnx, params}
    assert set(entry['size_bytes']) == {onnx, params}


@pytest.mark.parametrize('key', sorted(music_models.MODELS))
def test_every_pin_is_a_real_digest_and_a_real_size(key):
    entry = music_models.MODELS[key]
    for name, digest in entry['sha256'].items():
        if digest == music_models.UNPINNED:
            pytest.skip(f'{name} is not pinned yet')
        assert HEX64.match(digest), f'{name}: {digest!r} is not a sha256'
        assert entry['size_bytes'][name] > 0


def test_is_pinned_is_false_when_a_digest_is_a_placeholder(monkeypatch):
    entry = dict(music_models.model())
    entry['sha256'] = dict(entry['sha256'])
    entry['sha256'][entry['onnx_name']] = music_models.UNPINNED
    monkeypatch.setitem(music_models.MODELS, 'clap-audio-test', entry)
    assert not music_models.is_pinned('clap-audio-test')
    assert music_models.is_pinned()                 # the real one is


def test_urls_hang_off_the_feed_base_and_never_a_hardcoded_host():
    got = music_models.urls('https://feed.example.test/v1/')
    onnx, params = music_models.filenames()
    assert got[onnx] == f'https://feed.example.test/v1/{onnx}'
    assert got[params] == f'https://feed.example.test/v1/{params}'
    assert 'http' not in music_models.FEED_URL_TEMPLATE


def test_the_artefact_is_a_flat_sibling_of_channel_json():
    """GitHub Releases has one flat asset namespace per tag and no
    directories, so a `models/` (or any other) path segment is a URL that
    404s on the host this feed is actually served from
    (docs/RELEASE_FEED.md 3.1)."""
    for url in music_models.urls('https://feed.example.test/v1').values():
        assert url.count('/') == 'https://feed.example.test/v1/x'.count('/')


def test_no_feed_base_is_a_refusal_not_a_default():
    with pytest.raises(ValueError) as exc:
        music_models.urls('')
    assert 'feed' in str(exc.value)


def test_unknown_model_and_unknown_file_name_themselves():
    with pytest.raises(ValueError) as exc:
        music_models.model('clap-video')
    assert 'clap-audio' in str(exc.value)
    with pytest.raises(ValueError) as exc:
        music_models.expected_sha256('music-clap-audio-1.tokenizer.json')
    assert 'music-clap-audio-1.onnx' in str(exc.value)


def test_expected_sha256_matches_the_table():
    onnx, _ = music_models.filenames()
    assert (music_models.expected_sha256(onnx)
            == music_models.model()['sha256'][onnx])
