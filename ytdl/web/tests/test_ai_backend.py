"""The provider layer: who is asked, how, and how each one fails (2026-08-18).

`test_claude_cli.py` still owns the Anthropic path and the prompts -- it was
the only backend until today and its assertions are unchanged, which is the
point of the shim. This file is about everything the chain added: the lookup
the dashboard installs, the two urllib providers, the two CLI adapters, and
the rule that a CLI is never run for a site that did not turn the feature on.

NOTHING HERE PUTS A REQUEST ON THE WIRE. The HTTP providers are exercised
through `ai_backend._opener`, which is replaced; the CLI providers through
`subprocess.run`, likewise. A key never appears in an assertion message
either -- the `Provider.__repr__` test is the one that pins that.
"""
import json
import os

import pytest

from ytdlweb import ai_backend, claude_cli, config


@pytest.fixture(autouse=True)
def _no_lookup():
    """Every test starts with no dashboard callback installed, and leaves none
    behind: it is a module global, so one leaked fake would decide the
    provider for every test that ran after it."""
    ai_backend.clear_provider_lookup()
    yield
    ai_backend.clear_provider_lookup()


def provider(name, **kw):
    kw.setdefault('api_key', 'sk-test-0000000000000000abcd')
    return ai_backend.Provider(name, **kw)


# ------------------------------------------------------------ the lookup seam

def test_the_chain_order_is_the_one_the_product_asked_for():
    assert ai_backend.PROVIDER_ORDER == (
        'claude_code', 'anthropic_api', 'codex', 'openai_api', 'deepseek_api')


def test_the_dashboards_answer_is_used_and_re_read_every_call():
    answers = [{'provider': 'openai_api', 'api_key': 'k1'},
               {'provider': 'deepseek_api', 'api_key': 'k2'}]
    ai_backend.set_provider_lookup(lambda: answers.pop(0))
    assert ai_backend.current_provider().name == 'openai_api'
    # THE POINT of the callback: a key entered on Settings must take effect
    # without a container restart, so nothing is cached between calls.
    assert ai_backend.current_provider().name == 'deepseek_api'


def test_a_lookup_that_names_nothing_is_an_auth_failure_not_a_crash():
    ai_backend.set_provider_lookup(lambda: {'provider': '', 'detail': 'no key anywhere'})
    with pytest.raises(claude_cli.ClaudeError) as e:
        ai_backend.current_provider()
    assert e.value.prefix == ai_backend.ERR_AUTH
    assert 'no key anywhere' in str(e.value)


def test_a_lookup_that_raises_is_an_auth_failure_naming_the_settings_page():
    def boom():
        raise RuntimeError('database is locked')

    ai_backend.set_provider_lookup(boom)
    with pytest.raises(claude_cli.ClaudeError) as e:
        ai_backend.current_provider()
    assert e.value.prefix == ai_backend.ERR_AUTH
    assert 'Settings' in str(e.value)
    # The dashboard's exception text is NOT pasted through: only its type.
    assert 'database is locked' not in str(e.value)


def test_an_unknown_provider_name_is_refused():
    ai_backend.set_provider_lookup(lambda: {'provider': 'gemini_api'})
    with pytest.raises(claude_cli.ClaudeError) as e:
        ai_backend.current_provider()
    assert e.value.prefix == ai_backend.ERR_AUTH
    assert 'gemini_api' in str(e.value)


def test_with_no_lookup_the_environment_decides(monkeypatch):
    monkeypatch.setattr(config, 'ANTHROPIC_API_KEY', '')
    monkeypatch.setattr(config, 'OPENAI_API_KEY', 'sk-openai')
    assert ai_backend.current_provider().name == 'openai_api'
    monkeypatch.setattr(config, 'ANTHROPIC_API_KEY', 'sk-ant')
    assert ai_backend.current_provider().name == 'anthropic_api'


def test_the_environment_fallback_never_selects_a_cli(monkeypatch):
    """A standalone run has no way to read `[features] ai_cli_providers`, so
    it must never shell out to whatever `claude` is on PATH -- that is the
    2026-08-17 finding walking back in through a side door."""
    monkeypatch.setattr(config, 'ANTHROPIC_API_KEY', '')
    monkeypatch.setattr(config, 'OPENAI_API_KEY', '')
    monkeypatch.setattr(config, 'DEEPSEEK_API_KEY', '')
    assert ai_backend.current_provider().name not in ai_backend.CLI_PROVIDERS


def test_a_provider_never_prints_its_key():
    p = provider('openai_api', api_key='sk-super-secret-value')
    assert 'secret' not in repr(p)
    assert 'sk-' not in repr(p)
    assert 'key=set' in repr(p)


# --------------------------------------------------- openai / deepseek (HTTP)

class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, outcome):
        self.outcome = outcome
        self.requests = []
        self.timeouts = []

    def open(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return FakeResponse(self.outcome)


@pytest.fixture()
def http(monkeypatch):
    def install(outcome):
        fake = FakeOpener(outcome)
        monkeypatch.setattr(ai_backend, '_opener', fake)
        return fake

    return install


def _ok_payload(text='{"terms": []}'):
    return {'choices': [{'message': {'content': text}}]}


def test_openai_posts_the_documented_request(http):
    fake = http(_ok_payload('hello'))
    text = ai_backend.complete('be helpful', 'a topic',
                               provider=provider('openai_api', model='gpt-x'),
                               timeout=42)
    assert text == 'hello'
    req = fake.requests[0]
    assert req.full_url == 'https://api.openai.com/v1/chat/completions'
    body = json.loads(req.data)
    assert body['model'] == 'gpt-x'
    # THE SPLIT SURVIVES: our instructions in the system turn, the untrusted
    # material in the user turn -- the same posture as the Anthropic path.
    assert body['messages'] == [{'role': 'system', 'content': 'be helpful'},
                                {'role': 'user', 'content': 'a topic'}]
    assert 'tools' not in body
    assert fake.timeouts == [42.0]
    assert req.get_header('Authorization').startswith('Bearer ')


def test_deepseek_is_the_same_call_at_its_own_base_url(http):
    fake = http(_ok_payload('ok'))
    ai_backend.complete('s', 'u', provider=provider('deepseek_api'))
    assert fake.requests[0].full_url == 'https://api.deepseek.com/chat/completions'
    assert json.loads(fake.requests[0].data)['model'] == config.DEEPSEEK_MODEL


def test_a_configured_base_url_wins(http):
    fake = http(_ok_payload('ok'))
    ai_backend.complete('s', 'u', provider=provider(
        'openai_api', base_url='https://gateway.internal/v1/'))
    assert fake.requests[0].full_url == 'https://gateway.internal/v1/chat/completions'


def test_content_parts_are_joined(http):
    http({'choices': [{'message': {'content': [{'text': 'a'}, {'text': 'b'}]}}]})
    assert ai_backend.complete('s', 'u', provider=provider('openai_api')) == 'ab'


@pytest.mark.parametrize('status,prefix', [
    (401, ai_backend.ERR_AUTH),
    (403, ai_backend.ERR_AUTH),
    (408, ai_backend.ERR_TIMEOUT),
    (429, ai_backend.ERR_OUTPUT),
    (500, ai_backend.ERR_OUTPUT),
])
def test_http_statuses_classify_into_the_four_prefixes(http, status, prefix):
    import urllib.error

    http(urllib.error.HTTPError('u', status, 'boom', {}, None))
    with pytest.raises(claude_cli.ClaudeError) as e:
        ai_backend.complete('s', 'u', provider=provider('openai_api'))
    assert e.value.prefix == prefix
    assert e.value.provider == 'openai_api'


def test_a_timeout_is_a_timeout(http):
    import urllib.error

    http(urllib.error.URLError(TimeoutError('timed out')))
    with pytest.raises(claude_cli.ClaudeError) as e:
        ai_backend.complete('s', 'u', provider=provider('deepseek_api'))
    assert e.value.prefix == ai_backend.ERR_TIMEOUT


def test_an_unreachable_endpoint_is_missing(http):
    import urllib.error

    http(urllib.error.URLError('no route to host'))
    with pytest.raises(claude_cli.ClaudeError) as e:
        ai_backend.complete('s', 'u', provider=provider('openai_api'))
    assert e.value.prefix == ai_backend.ERR_MISSING


def test_an_unreadable_body_is_an_output_error(http):
    class Junk(FakeOpener):
        def open(self, request, timeout=None):
            class R:
                def read(self):
                    return b'<html>proxy error</html>'

                def __enter__(self):
                    return self

                def __exit__(self, *exc):
                    return False

            return R()

    import urllib.error  # noqa: F401 - keeps the import shape of its siblings

    fake = http(_ok_payload())
    fake.open = Junk(None).open
    with pytest.raises(claude_cli.ClaudeError) as e:
        ai_backend.complete('s', 'u', provider=provider('openai_api'))
    assert e.value.prefix == ai_backend.ERR_OUTPUT


def test_a_blank_key_never_reaches_the_network(http):
    fake = http(_ok_payload())
    with pytest.raises(claude_cli.ClaudeError) as e:
        ai_backend.complete('s', 'u', provider=ai_backend.Provider('openai_api'))
    assert e.value.prefix == ai_backend.ERR_AUTH
    assert fake.requests == []
    # The ops text names both places a key can come from.
    assert 'OPENAI_API_KEY' in str(e.value)
    assert 'Settings' in str(e.value)


def test_an_empty_reply_is_an_output_error(http):
    http(_ok_payload(''))
    with pytest.raises(claude_cli.ClaudeError) as e:
        ai_backend.complete('s', 'u', provider=provider('openai_api'))
    assert e.value.prefix == ai_backend.ERR_OUTPUT
    assert 'empty' in str(e.value)


def test_a_redirect_is_refused_rather_than_followed():
    """A credential must never be replayed to a Location somebody else chose
    (docs/GOTCHAS.md §12's rule, in the one place this app carries a key)."""
    handler = ai_backend._NoRedirect()
    assert handler.redirect_request(None, None, 302, 'Found', {}, 'http://elsewhere') is None


# ----------------------------------------------------------------- the CLIs

class FakeProc:
    def __init__(self, returncode=0, stdout='', stderr=''):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


@pytest.fixture()
def run_cli(monkeypatch):
    calls = []

    def install(outcome):
        def fake_run(argv, **kw):
            calls.append((argv, kw))
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        monkeypatch.setattr(ai_backend.subprocess, 'run', fake_run)
        return calls

    return install


def cli(name='claude_code', **kw):
    kw.setdefault('cli_path', '/usr/local/bin/claude')
    kw.setdefault('cli_enabled', True)
    return ai_backend.Provider(name, **kw)


def test_a_cli_provider_is_refused_when_the_site_flag_is_off(run_cli):
    calls = run_cli(FakeProc(stdout='never'))
    with pytest.raises(claude_cli.ClaudeError) as e:
        ai_backend.complete('s', 'u', provider=cli(cli_enabled=False))
    assert e.value.prefix == ai_backend.ERR_AUTH
    assert 'ai_cli_providers' in str(e.value)
    assert calls == []                       # nothing was executed at all


def test_claude_code_gets_the_prompt_on_stdin_never_argv(run_cli):
    calls = run_cli(FakeProc(stdout='{"terms": []}'))
    text = ai_backend.complete('INSTRUCTIONS', '<topic>hostile</topic>',
                               provider=cli(), timeout=30)
    assert text == '{"terms": []}'
    argv, kw = calls[0]
    assert argv[0] == '/usr/local/bin/claude'
    assert '-p' in argv
    # A search term in an argv element lands in `ps` output; and the whole
    # prompt/data split was impossible to state when it was one argv string.
    assert not any('hostile' in a for a in argv)
    assert 'INSTRUCTIONS' in kw['input'] and 'hostile' in kw['input']
    assert kw['input'].index('INSTRUCTIONS') < kw['input'].index('hostile')
    assert kw['timeout'] == 30.0


def test_the_cli_subprocess_never_inherits_the_containers_api_keys(run_cli, monkeypatch):
    """An admin who picked a CLI provider wants their SUBSCRIPTION used. Claude
    Code prefers ANTHROPIC_API_KEY when it is in the environment, so leaving it
    there would silently bill the customer's API key instead -- invisible until
    the invoice."""
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-should-not-be-inherited')
    calls = run_cli(FakeProc(stdout='ok'))
    ai_backend.complete('s', 'u', provider=cli())
    assert 'ANTHROPIC_API_KEY' not in calls[0][1]['env']


def test_the_dashboards_env_overlay_reaches_the_subprocess(run_cli, monkeypatch):
    """`$HOME` is the whole point (2026-08-18). The dashboard's setup wizard
    signs the CLI in under `<data>/tools/<tool>/home`, and a job that ran with
    the container's own HOME would be told to log in by a CLI that IS logged
    in -- with the Settings page cheerfully reporting "signed in" about the
    other one."""
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-should-not-be-inherited')
    calls = run_cli(FakeProc(stdout='ok'))
    ai_backend.complete('s', 'u', provider=cli(cli_env={
        'HOME': '/data/tools/claude-code/home',
        'CLAUDE_CODE_OAUTH_TOKEN': 'sk-ant-oat01-TOKEN',
    }))
    env = calls[0][1]['env']
    assert env['HOME'] == '/data/tools/claude-code/home'
    # The token the dashboard holds is a CREDENTIAL and is passed through; the
    # container's API keys are still stripped, in the same call.
    assert env['CLAUDE_CODE_OAUTH_TOKEN'] == 'sk-ant-oat01-TOKEN'
    assert 'ANTHROPIC_API_KEY' not in env


def test_a_provider_never_prints_its_env_overlay(run_cli):
    """`repr` of a Provider ends up in log lines, tracebacks and pytest diffs,
    and the overlay can carry an OAuth token."""
    text = repr(cli(cli_env={'CLAUDE_CODE_OAUTH_TOKEN': 'sk-ant-oat01-TOKEN'}))
    assert 'sk-ant' not in text
    assert 'env=1' in text


def test_no_overlay_is_the_old_behaviour(run_cli):
    """A deployment whose admin installed the CLI on the host themselves gets
    exactly the environment it always got: keys stripped, nothing added."""
    calls = run_cli(FakeProc(stdout='ok'))
    ai_backend.complete('s', 'u', provider=cli())
    env = calls[0][1]['env']
    assert env.get('HOME') == os.environ.get('HOME')


def test_codex_uses_its_own_non_interactive_form(run_cli):
    calls = run_cli(FakeProc(stdout='ok'))
    ai_backend.complete('s', 'u', provider=cli('codex', cli_path='/usr/bin/codex'))
    assert calls[0][0][:2] == ['/usr/bin/codex', 'exec']


def test_a_missing_binary_is_classified_missing(run_cli):
    run_cli(FileNotFoundError())
    with pytest.raises(claude_cli.ClaudeError) as e:
        ai_backend.complete('s', 'u', provider=cli())
    assert e.value.prefix == ai_backend.ERR_MISSING


def test_a_cli_provider_with_no_path_never_runs_anything(run_cli):
    calls = run_cli(FakeProc(stdout='never'))
    with pytest.raises(claude_cli.ClaudeError) as e:
        ai_backend.complete('s', 'u', provider=cli(cli_path=''))
    assert e.value.prefix == ai_backend.ERR_MISSING
    assert calls == []


def test_a_cli_timeout_is_classified_timeout(run_cli):
    import subprocess

    run_cli(subprocess.TimeoutExpired('claude', 5))
    with pytest.raises(claude_cli.ClaudeError) as e:
        ai_backend.complete('s', 'u', provider=cli())
    assert e.value.prefix == ai_backend.ERR_TIMEOUT


@pytest.mark.parametrize('stderr', [
    'Invalid API key · Please run /login',
    'You are not logged in.',
    'error: authentication required',
])
def test_a_logged_out_cli_is_an_auth_failure_pointing_at_the_host(run_cli, stderr):
    run_cli(FakeProc(returncode=1, stderr=stderr))
    with pytest.raises(claude_cli.ClaudeError) as e:
        ai_backend.complete('s', 'u', provider=cli())
    assert e.value.prefix == ai_backend.ERR_AUTH
    # We cannot complete an interactive OAuth from a web page, so the message
    # has to send the admin to the host itself.
    assert 'ON THAT HOST' in str(e.value)


def test_any_other_non_zero_exit_is_an_output_error(run_cli):
    run_cli(FakeProc(returncode=2, stderr='unrecognised flag --nope'))
    with pytest.raises(claude_cli.ClaudeError) as e:
        ai_backend.complete('s', 'u', provider=cli())
    assert e.value.prefix == ai_backend.ERR_OUTPUT
    # The CLI's own stderr is passed through: it is what names the flag.
    assert '--nope' in str(e.value)


# ------------------------------------------------------- through claude_cli

def test_the_two_calls_go_through_the_chain(http, monkeypatch):
    """generate_terms is the real call site; it must reach whichever provider
    the dashboard named, with the prompts unchanged."""
    ai_backend.set_provider_lookup(lambda: {'provider': 'openai_api', 'api_key': 'k'})
    http(_ok_payload(json.dumps({'terms': [{'q': 'a drone shot', 'lang': 'en'}]})))
    out = claude_cli.generate_terms('algal reef')
    assert out == [{'q': 'a drone shot', 'lang': 'en', 'english_gloss': None}]


def test_the_health_cache_records_which_provider_answered(http):
    ai_backend.set_provider_lookup(lambda: {'provider': 'deepseek_api', 'api_key': 'k'})
    http(_ok_payload('ok'))
    claude_cli.refresh_health(force=True)
    assert claude_cli.health()['claude'] == 'ok'
    assert claude_cli.health()['provider'] == 'deepseek_api'
