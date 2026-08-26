"""The download canary (docs/YTDL_RESILIENCE_PLAN.md WP5, 2026-08-26).

Nothing here touches the network: ytdl_canary._extract is the seam, and every
test replaces it. The suite also runs with YTDL_WORKER=0 (conftest), which the
canary honours for the same reason the worker does -- a test suite must not be
able to start a thread that talks to YouTube on a timer.
"""
import pytest

from ytdlweb import config, ytdl_canary, ytdl_evidence

BOT_CHECK = "Sign in to confirm you're not a bot"


@pytest.fixture()
def canary(tmp_path, monkeypatch):
    """A canary with a tmp evidence mirror and no extractor installed yet."""
    monkeypatch.setattr(ytdl_evidence, '_state_path',
                        lambda: tmp_path / 'ytdl_evidence.json')
    monkeypatch.setattr(config, 'CANARY_URL',
                        'https://www.youtube.com/watch?v=jNQXAC9IVRw')
    ytdl_evidence.reset()
    yield
    ytdl_evidence.reset()


class FakeExtract:
    """Records (url, cookies_file) per call and raises what it was told to."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def __call__(self, url, cookies_file=None):
        self.calls.append((url, cookies_file))
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if isinstance(outcome, Exception):
            raise outcome
        return {'id': 'jNQXAC9IVRw'}


def _jar(tmp_path, monkeypatch, contents):
    path = tmp_path / 'cookies.txt'
    path.write_text(contents, encoding='utf-8')
    monkeypatch.setattr(config, 'COOKIES_FILE', str(path))
    return path


REAL_JAR = ('# Netscape HTTP Cookie File\n'
            '.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tvalue\n')


# ------------------------------------------------------------ off by default

def test_the_canary_ships_off():
    """Section 7 of the plan: real automated traffic to YouTube on a fixed
    cadence is the owner's decision, not a default."""
    assert config._canary_interval(None) == 0
    assert config._canary_interval('') == 0
    assert config._canary_interval('0') == 0
    assert config._canary_interval('nightly') == 0
    assert config._canary_interval('-60') == 0
    assert ytdl_canary.enabled() is False
    assert ytdl_canary.ensure_started() is False


def test_a_configured_interval_has_a_five_minute_floor():
    """An operator who types 5 must not get a five-second metronome pointed at
    the endpoint that bot-checked this IP in the first place (2026-08-11)."""
    assert config._canary_interval('5') == config.CANARY_MIN_INTERVAL_SECONDS
    assert config._canary_interval('300') == 300
    assert config._canary_interval('3600') == 3600


def test_ytdl_worker_0_means_no_canary_either(monkeypatch):
    """The switch that keeps both suites (and the dashboard's fake ytdlweb)
    from spawning ytdl's background threads covers this one too."""
    monkeypatch.setattr(config, 'CANARY_INTERVAL_SECONDS', 300)
    assert ytdl_canary.enabled() is True
    assert ytdl_canary.ensure_started() is False       # YTDL_WORKER=0, conftest
    assert ytdl_canary.is_alive() is False


# ------------------------------------------------------------------- a tick

def test_a_working_anonymous_path_is_recorded_and_costs_no_cookie_call(canary,
                                                                       monkeypatch):
    fake = FakeExtract(None)
    monkeypatch.setattr(ytdl_canary, '_extract', fake)
    ytdl_canary.tick()

    assert [c[1] for c in fake.calls] == [None]
    snap = ytdl_evidence.snapshot()
    assert snap[ytdl_evidence.PATH_ANONYMOUS]['ok'] is True
    assert snap[ytdl_evidence.PATH_ANONYMOUS]['source'] == 'canary'
    assert snap[ytdl_evidence.PATH_ANONYMOUS]['video_id'] == 'jNQXAC9IVRw'
    assert ytdl_evidence.PATH_COOKIES not in snap


def test_a_bot_check_falls_back_to_the_jar(canary, tmp_path, monkeypatch):
    """The same order WP3 puts the real downloads in: anonymous, and the jar
    only when the IP is being challenged."""
    _jar(tmp_path, monkeypatch, REAL_JAR)
    fake = FakeExtract(RuntimeError(BOT_CHECK), None)
    monkeypatch.setattr(ytdl_canary, '_extract', fake)
    ytdl_canary.tick()

    assert [c[1] for c in fake.calls] == [None, config.COOKIES_FILE]
    snap = ytdl_evidence.snapshot()
    assert snap[ytdl_evidence.PATH_ANONYMOUS]['ok'] is False
    assert 'not a bot' in snap[ytdl_evidence.PATH_ANONYMOUS]['error']
    assert snap[ytdl_evidence.PATH_COOKIES]['ok'] is True
    assert snap[ytdl_evidence.PATH_COOKIES]['source'] == 'canary'


def test_both_paths_blocked_is_recorded_on_both(canary, tmp_path, monkeypatch):
    """CR-80's shape, which is the one an operator most needs named: the jar is
    refused AND there is nothing anonymous to fall back to."""
    _jar(tmp_path, monkeypatch, REAL_JAR)
    fake = FakeExtract(RuntimeError(BOT_CHECK),
                       RuntimeError('The page needs to be reloaded.'))
    monkeypatch.setattr(ytdl_canary, '_extract', fake)
    ytdl_canary.tick()

    snap = ytdl_evidence.snapshot()
    assert snap[ytdl_evidence.PATH_ANONYMOUS]['ok'] is False
    assert snap[ytdl_evidence.PATH_COOKIES]['ok'] is False
    assert 'needs to be reloaded' in snap[ytdl_evidence.PATH_COOKIES]['error']


def test_an_ordinary_failure_does_not_reach_for_the_cookies(canary, tmp_path,
                                                            monkeypatch):
    """Only a BOT CHECK justifies the second call. A private video, a network
    blip or a 500 says nothing about which path works."""
    _jar(tmp_path, monkeypatch, REAL_JAR)
    fake = FakeExtract(RuntimeError('Video unavailable'))
    monkeypatch.setattr(ytdl_canary, '_extract', fake)
    ytdl_canary.tick()

    assert [c[1] for c in fake.calls] == [None]
    assert ytdl_evidence.PATH_COOKIES not in ytdl_evidence.snapshot()


def test_a_header_only_jar_is_never_tried(canary, tmp_path, monkeypatch):
    """CR-80 parked the flagged jar as its two header lines with the path still
    set. Re-testing an empty file every five minutes would record a permanent,
    meaningless failure on the cookies path."""
    _jar(tmp_path, monkeypatch, '# Netscape HTTP Cookie File\n')
    fake = FakeExtract(RuntimeError(BOT_CHECK))
    monkeypatch.setattr(ytdl_canary, '_extract', fake)
    ytdl_canary.tick()

    assert [c[1] for c in fake.calls] == [None]
    assert ytdl_evidence.PATH_COOKIES not in ytdl_evidence.snapshot()


def test_a_tick_never_raises(canary, monkeypatch):
    """A diagnostic that can break the thing it diagnoses is worse than none."""
    def boom(url, cookies_file=None):
        raise ValueError('anything at all')

    monkeypatch.setattr(ytdl_canary, '_extract', boom)
    ytdl_canary.tick()
    assert ytdl_evidence.snapshot()[ytdl_evidence.PATH_ANONYMOUS]['ok'] is False


def test_the_classifier_is_the_workers_one(canary, monkeypatch):
    """One definition of "bot check", not two: the canary imports worker's
    lazily rather than keeping a copy that can drift (plan WP4)."""
    from ytdlweb import worker

    assert ytdl_canary._bot_checked(BOT_CHECK) is worker._bot_checked(BOT_CHECK)
    assert ytdl_canary._bot_checked('Video unavailable') is False
