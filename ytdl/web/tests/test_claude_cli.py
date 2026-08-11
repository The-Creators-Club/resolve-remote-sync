"""The `claude -p` wrapper: envelope parsing, and the four error prefixes.

The prefixes are the contract with the SPA -- each maps to a different ops
instruction, and "an admin must run the one-time login" is useless if a logged
-out CLI is reported as a parse failure. Everything here drives the real
functions with a fake subprocess.run; nothing spawns a process.
"""
import json
import subprocess

import pytest

from ytdlweb import claude_cli, config


class FakeProc:
    def __init__(self, stdout='', stderr='', returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def envelope(result, is_error=False):
    return json.dumps({'type': 'result', 'subtype': 'success',
                       'is_error': is_error, 'result': result})


@pytest.fixture()
def run(monkeypatch):
    """Replace subprocess.run and hand the test the recorded argv."""
    calls = []

    def _fake(cmd, **kw):
        calls.append({'cmd': cmd, 'env': kw.get('env') or {}, 'cwd': kw.get('cwd')})
        outcome = calls[-1]['outcome'] = _fake.outcome
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    _fake.outcome = FakeProc(envelope('{"ok": true}'))
    monkeypatch.setattr(claude_cli.subprocess, 'run', _fake)
    _fake.calls = calls
    return _fake


def test_the_command_line_is_the_documented_one(run):
    claude_cli.ask_json('hello')
    cmd = run.calls[0]['cmd']
    assert cmd[0] == config.CLAUDE_BIN
    assert cmd[1:3] == ['-p', 'hello']
    assert '--output-format' in cmd and 'json' in cmd
    assert cmd[cmd.index('--model') + 1] == config.CLAUDE_MODEL
    # No shell, so the quotes the docs put around * are the shell's job and
    # must not be part of the argument.
    assert cmd[cmd.index('--disallowed-tools') + 1] == '*'


def test_home_is_set_for_the_subprocess_only(run, monkeypatch):
    """uid 3000 has no passwd entry, so claude needs to be told where its
    credentials are -- but exporting HOME globally would change it for the
    dashboard and everything else in the container."""
    before = dict(claude_cli.os.environ)
    claude_cli.ask_json('hello')
    env = run.calls[0]['env']
    assert env['HOME'] == config.CLAUDE_HOME
    assert env['CLAUDE_CONFIG_DIR'].endswith('.claude')
    assert dict(claude_cli.os.environ) == before
    assert run.calls[0]['cwd'] == str(config.DATA_ROOT)


def test_the_envelope_result_is_what_gets_parsed(run):
    run.outcome = FakeProc(envelope('{"terms": []}'))
    assert claude_cli.ask_json('x') == {'terms': []}


def test_a_fenced_reply_is_unwrapped(run):
    run.outcome = FakeProc(envelope('```json\n{"terms": [1]}\n```'))
    assert claude_cli.ask_json('x') == {'terms': [1]}


def test_a_reply_wrapped_in_prose_still_parses(run):
    run.outcome = FakeProc(envelope('Sure! {"terms": [1]} hope that helps'))
    assert claude_cli.ask_json('x') == {'terms': [1]}


def test_unparseable_output_is_retried_once_then_classified(run):
    run.outcome = FakeProc(envelope('I am not going to answer in JSON.'))
    with pytest.raises(claude_cli.ClaudeError) as e:
        claude_cli.ask_json('x')
    assert e.value.prefix == claude_cli.ERR_OUTPUT
    assert len(run.calls) == 2                 # one retry, not more


def test_a_missing_binary_is_claude_missing(run):
    run.outcome = FileNotFoundError()
    with pytest.raises(claude_cli.ClaudeError) as e:
        claude_cli.ask_json('x')
    assert e.value.prefix == claude_cli.ERR_MISSING
    assert len(run.calls) == 1                 # never retried: it will not appear


def test_a_timeout_is_claude_timeout(run):
    run.outcome = subprocess.TimeoutExpired(cmd='claude', timeout=180)
    with pytest.raises(claude_cli.ClaudeError) as e:
        claude_cli.ask_json('x')
    assert e.value.prefix == claude_cli.ERR_TIMEOUT
    assert len(run.calls) == 1


@pytest.mark.parametrize('stderr', [
    'Invalid API key · Please run /login',
    'Not logged in. Run `claude /login` to authenticate.',
    'OAuth token expired',
    'error: no valid credentials found',
])
def test_every_logged_out_shape_is_claude_auth(run, stderr):
    run.outcome = FakeProc('', stderr, returncode=1)
    with pytest.raises(claude_cli.ClaudeError) as e:
        claude_cli.ask_json('x')
    assert e.value.prefix == claude_cli.ERR_AUTH
    assert 'one-time login' in str(e.value)


def test_a_logged_out_cli_that_exits_zero_is_still_claude_auth(run):
    """It answers 0 with prose telling you to log in often enough that only
    checking the exit code would report it as a parse failure."""
    run.outcome = FakeProc(envelope('Please run /login to authenticate first.'))
    with pytest.raises(claude_cli.ClaudeError) as e:
        claude_cli.ask_json('x')
    assert e.value.prefix == claude_cli.ERR_AUTH


def test_an_is_error_envelope_is_reported(run):
    run.outcome = FakeProc(envelope('model overloaded', is_error=True))
    with pytest.raises(claude_cli.ClaudeError) as e:
        claude_cli.ask_json('x')
    assert e.value.prefix == claude_cli.ERR_OUTPUT


# ------------------------------------------------------------- call #1: terms

def test_generate_terms_returns_en_and_zh_with_glosses(run):
    run.outcome = FakeProc(envelope(json.dumps({'terms': [
        {'q': 'algal reef taiwan', 'lang': 'en'},
        {'q': '藻礁 三接', 'lang': 'zh', 'english_gloss': 'algal reef third terminal'},
    ]})))
    out = claude_cli.generate_terms('algal reef')
    assert out[0] == {'q': 'algal reef taiwan', 'lang': 'en', 'english_gloss': None}
    assert out[1]['english_gloss'] == 'algal reef third terminal'
    assert 'Traditional Chinese' in run.calls[0]['cmd'][2]
    assert 'english_gloss' in run.calls[0]['cmd'][2]


def test_a_missing_gloss_asks_once_more_before_anything_is_dropped(run, monkeypatch):
    """REQ 5 rests on the gloss, and a missing one is what a retry fixes --
    ask_json's own retry covers unparseable output only, so this is where the
    promise is kept (YTDL-20)."""
    replies = [
        json.dumps({'terms': [{'q': '藻礁 三接', 'lang': 'zh'}]}),
        json.dumps({'terms': [{'q': '藻礁 三接', 'lang': 'zh',
                               'english_gloss': 'algal reef third terminal'}]}),
    ]

    def _seq(cmd, **kw):
        run.calls.append({'cmd': cmd, 'env': kw.get('env') or {}, 'cwd': kw.get('cwd')})
        return FakeProc(envelope(replies.pop(0)))

    monkeypatch.setattr(claude_cli.subprocess, 'run', _seq)
    out = claude_cli.generate_terms('x')
    assert [t['english_gloss'] for t in out] == ['algal reef third terminal']
    assert len(run.calls) == 2


def test_one_glossless_query_does_not_lose_the_whole_search(run):
    """YTDL-20: 19 good terms plus one missing gloss used to fail the job at
    `generating_terms` and lose the lot."""
    run.outcome = FakeProc(envelope(json.dumps({'terms': [
        {'q': 'algal reef taiwan', 'lang': 'en'},
        {'q': '藻礁 三接', 'lang': 'zh'},
    ]})))
    out = claude_cli.generate_terms('x')
    assert [t['q'] for t in out] == ['algal reef taiwan']
    assert len(run.calls) == 2                 # asked again first, then dropped


def test_a_reply_of_nothing_but_glossless_queries_is_still_an_error(run):
    run.outcome = FakeProc(envelope(json.dumps({'terms': [
        {'q': '藻礁 三接', 'lang': 'zh'}]})))
    with pytest.raises(claude_cli.ClaudeError) as e:
        claude_cli.generate_terms('x')
    assert e.value.prefix == claude_cli.ERR_OUTPUT


def test_duplicate_and_malformed_terms_are_dropped(run):
    run.outcome = FakeProc(envelope(json.dumps({'terms': [
        {'q': 'Reef', 'lang': 'en'},
        {'q': 'reef', 'lang': 'en'},        # same query, different case
        {'q': '', 'lang': 'en'},
        {'q': 'x', 'lang': 'klingon'},
        'not even a dict',
    ]})))
    assert [t['q'] for t in claude_cli.generate_terms('x')] == ['Reef']


def test_no_usable_terms_is_an_output_error(run):
    run.outcome = FakeProc(envelope('{"terms": []}'))
    with pytest.raises(claude_cli.ClaudeError) as e:
        claude_cli.generate_terms('x')
    assert e.value.prefix == claude_cli.ERR_OUTPUT


# ---------------------------------------------------------- call #2: relevance

def _videos(n):
    return [{'id': f'vid{i:08d}', 'title': f'title {i}', 'channel': 'c',
             'duration': 60} for i in range(n)]


def test_relevance_batches_by_index_and_keeps_reasons_short(run):
    run.outcome = FakeProc(envelope(json.dumps({
        'keep': [0, 2], 'drop': [{'i': 1, 'why': 'unrelated gaming stream'}]})))
    out = claude_cli.filter_relevance('topic', _videos(3))
    assert out['vid00000000'] == (True, '')
    assert out['vid00000001'] == (False, 'unrelated gaming stream')
    assert out['vid00000002'] == (True, '')
    assert '10 words max' in run.calls[0]['cmd'][2]


def test_relevance_runs_one_call_per_batch(run):
    run.outcome = FakeProc(envelope('{"keep": [], "drop": []}'))
    claude_cli.filter_relevance('topic', _videos(85), batch=40)
    assert len(run.calls) == 3            # 40 + 40 + 5


def test_a_video_the_model_never_mentioned_is_simply_absent(run):
    """The caller leaves those relevant: an omission must never silently hide a
    video from the editor."""
    run.outcome = FakeProc(envelope('{"keep": [0], "drop": []}'))
    out = claude_cli.filter_relevance('topic', _videos(3))
    assert set(out) == {'vid00000000'}


def test_a_null_keep_list_degrades_instead_of_failing_the_job(run):
    """YTDL-13: {"keep": null} is what "I kept nothing" comes back as, and the
    TypeError it used to raise escaped the caller's ClaudeError-only except --
    killing a twenty-minute job at `filtering` where the design says degrade."""
    run.outcome = FakeProc(envelope(
        '{"keep": null, "drop": [{"i": 0, "why": "gaming stream"}]}'))
    out = claude_cli.filter_relevance('topic', _videos(2))
    assert out == {'vid00000000': (False, 'gaming stream')}

    run.outcome = FakeProc(envelope('{"keep": 3, "drop": null}'))
    assert claude_cli.filter_relevance('topic', _videos(2)) == {}


def test_out_of_range_indices_are_ignored(run):
    run.outcome = FakeProc(envelope('{"keep": [0, 99, "x"], "drop": [{"i": -1}]}'))
    out = claude_cli.filter_relevance('topic', _videos(2))
    assert set(out) == {'vid00000000'}


# ---------------------------------------------------------------- health

def test_the_health_probe_classifies_and_caches(run, monkeypatch):
    run.outcome = FakeProc('', 'Please run /login', returncode=1)
    assert claude_cli.refresh_health(force=True)['claude'] == 'unauthenticated'
    assert claude_cli.health()['claude'] == 'unauthenticated'

    run.outcome = FakeProc(envelope('ok'))
    assert claude_cli.refresh_health(force=True)['claude'] == 'ok'


def test_health_is_not_re_probed_inside_the_interval(run):
    run.outcome = FakeProc(envelope('ok'))
    claude_cli.refresh_health(force=True)
    n = len(run.calls)
    claude_cli.refresh_health()
    assert len(run.calls) == n, 'a wedged claude must not become one subprocess per call'


def test_a_working_call_writes_the_cache_back_to_ok(run):
    """YTDL-5: the cache could only degrade. One transient timeout showed red
    on every editor's page until the container was restarted -- including after
    an admin had verified the login by hand, so the documented ops procedure
    appeared not to work."""
    claude_cli.note_failure(claude_cli.ClaudeError(claude_cli.ERR_TIMEOUT, 'blip'))
    assert claude_cli.health()['claude'] == 'timeout'

    run.outcome = FakeProc(envelope('{"terms": [1]}'))
    claude_cli.ask_json('x')                   # the path the worker actually uses
    assert claude_cli.health()['claude'] == 'ok'
    assert claude_cli.health()['detail'] == ''


def test_note_failure_updates_the_cache_without_running_anything(run):
    claude_cli.refresh_health(force=True)
    n = len(run.calls)
    claude_cli.note_failure(claude_cli.ClaudeError(claude_cli.ERR_MISSING, 'gone'))
    assert claude_cli.health()['claude'] == 'missing'
    assert len(run.calls) == n
