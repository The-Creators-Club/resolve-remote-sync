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


# ----------------------------------------------------------- the shot types
# 2026-08-11 (morning): the editor's complaint was "the youtube search should
# prioritise visuals -- if we search 'presidential palace' we're looking for
# visuals of presidential palace". `taiwan presidential palace` had returned 336
# candidates of news packages, studio panels and commentary, and both AI stages
# were given a fixed visual bias.
#
# (afternoon): "just make it a series of check boxes so the user can decide and
# tweak it". The fragments are per shot type now and the ticks compose them.
# The DEFAULT selection reproduces the morning's behaviour, which is what the
# first block below is: the same assertions, against the default ticks.

def _prompt(run, i=0):
    """The prompt claude was actually handed. argv[2] by the -p contract that
    test_the_command_line_is_the_documented_one pins."""
    return run.calls[i]['cmd'][2]


def _terms_reply():
    return FakeProc(envelope(json.dumps({'terms': [
        {'q': 'presidential office building taipei aerial', 'lang': 'en'},
        {'q': '總統府 空拍', 'lang': 'zh', 'english_gloss': 'presidential office drone'},
    ]})))


ALL_SHOTS = list(claude_cli.SHOT_TYPES)


def test_the_default_ticks_are_the_six_footage_types(run):
    """The defaults ARE the old fixed bias, so an editor who touches nothing
    gets exactly the search the fleet had before the checkboxes."""
    assert claude_cli.DEFAULT_SHOT_TYPES == (
        'aerial', 'establishing', 'walkthrough', 'timelapse', 'event', 'raw')
    assert claude_cli.COVERAGE_KEYS == ('interview', 'news', 'commentary')
    assert set(claude_cli.FOOTAGE_KEYS) | set(claude_cli.COVERAGE_KEYS) == set(ALL_SHOTS)
    # Every key carries both stages' text, in both languages the fleet searches.
    for key, frag in claude_cli.SHOT_TYPES.items():
        assert frag['label'].strip(), key
        assert frag['seek'].strip() and frag['keep'].strip(), key
        assert frag['group'] in ('footage', 'coverage'), key
        assert any('一' <= ch <= '鿿' for ch in frag['seek']), key
        # avoid/drop belong to the coverage half alone: an unticked footage
        # type is not sought, but it is never thrown away.
        has_off_text = 'avoid' in frag or 'drop' in frag
        assert has_off_text == (frag['group'] == 'coverage'), key
    for key in claude_cli.COVERAGE_KEYS:
        assert claude_cli.SHOT_TYPES[key]['avoid'].strip(), key
        assert claude_cli.SHOT_TYPES[key]['drop'].strip(), key


def test_the_term_prompt_asks_for_footage_of_the_topic_not_coverage_about_it(run):
    run.outcome = _terms_reply()
    claude_cli.generate_terms('taiwan presidential palace')
    p = _prompt(run)
    assert claude_cli.term_bias() in p, 'the composed bias must reach the model'
    assert 'FOOTAGE OF' in p
    for phrasing in ('establishing shot', 'exterior', 'aerial', 'drone footage',
                     'walking tour', 'timelapse', 'ceremony', 'no commentary',
                     '4K'):
        assert phrasing in p, phrasing


def test_the_term_prompt_steers_away_from_the_types_left_unticked(run):
    run.outcome = _terms_reply()
    claude_cli.generate_terms('x')
    p = _prompt(run)
    assert 'AVOID' in p
    for phrasing in ('breaking', 'news update', 'analysis', 'commentary',
                     'debate', 'interview', 'reaction', 'podcast'):
        assert phrasing in p, phrasing
    # The Chinese half of the same list: a zh query for 專訪 is a talking head
    # in any language, and this fleet searches en+zh.
    for phrasing in ('專訪', '快訊', '政論', '評論'):
        assert phrasing in p, phrasing


def test_the_chinese_half_gets_its_own_footage_idioms(run):
    """Not translations of the English ones: 空拍 is how a Taiwanese drone shot
    is filed, 完整版 is how the unedited full-length version is."""
    run.outcome = _terms_reply()
    claude_cli.generate_terms('x')
    p = _prompt(run)
    for idiom in ('空拍',        # aerial / drone
                  '縮時',        # timelapse
                  '街景',        # street view
                  '導覽',        # guided walk-through
                  '完整版',  # full version
                  '無旁白',  # no narration
                  '典禮'):       # ceremony
        assert idiom in p, idiom


def test_the_shot_type_bias_did_not_disturb_the_term_output_contract(run):
    """The JSON envelope, the gloss requirement and the 8-12 per language are
    the contract worker.py and the manifest rest on -- the bias is additional
    prose, not a redesign."""
    run.outcome = _terms_reply()
    out = claude_cli.generate_terms('x', shot_types=['aerial', 'interview'])
    p = _prompt(run)
    assert '8 to 12 queries in English' in p
    assert '8 to 12 queries in Traditional Chinese' in p
    assert 'Every Chinese query MUST carry "english_gloss"' in p
    assert '{"terms": [' in p and '{{' not in p, 'the doubled braces must render'
    assert '{bias}' not in p and '{topic}' not in p
    assert out[1] == {'q': '總統府 空拍', 'lang': 'zh',
                      'english_gloss': 'presidential office drone'}


def test_the_relevance_prompt_drops_studio_and_keeps_real_footage(run):
    run.outcome = FakeProc(envelope('{"keep": [0], "drop": []}'))
    claude_cli.filter_relevance('taiwan presidential palace', _videos(2))
    p = _prompt(run)
    assert claude_cli.filter_bias() in p
    for drop in ('studio segments', 'news anchors', 'interviews',
                 'commentary', 'reaction videos', 'compilations',
                 'heavy overlays'):
        assert drop in p, drop
    for keep in ('establishing shots', 'exteriors', 'aerials', 'drone',
                 'walking tours', 'timelapses', 'ceremonies'):
        assert keep in p, keep
    # The zh half of the drop list: 政論節目 is a panel show whatever the
    # channel is called.
    assert '專訪' in p and '政論節目' in p


def test_the_relevance_prompt_prefers_longer_steadier_less_edited(run):
    """The listing already carries the duration, so this is actionable."""
    run.outcome = FakeProc(envelope('{"keep": [0], "drop": []}'))
    claude_cli.filter_relevance('topic', _videos(2))
    p = _prompt(run)
    assert 'LONGER, steadier, less-edited' in p
    assert 'KEEP it' in p, 'when in doubt keep: an omission must not hide a clip'
    assert '0. title 0 | c | 1:00' in p


def test_the_shot_type_bias_did_not_disturb_the_relevance_output_contract(run):
    run.outcome = FakeProc(envelope('{"keep": [0], "drop": []}'))
    claude_cli.filter_relevance('topic', _videos(3), shot_types=['event'])
    p = _prompt(run)
    assert '{"keep": [0, 3, 4], "drop": [{"i": 1, "why": "reason, 10 words max"}]}' in p
    assert 'Every index from 0 to 2 must appear exactly once' in p
    assert '{{' not in p and '{bias}' not in p and '{listing}' not in p


def test_one_call_per_batch_composes_the_bias_once_and_identically(run):
    """The selection cannot change mid-job, and a manifest whose second batch
    was judged by different rules than its first is not one manifest."""
    run.outcome = FakeProc(envelope('{"keep": [], "drop": []}'))
    claude_cli.filter_relevance('topic', _videos(85), shot_types=['aerial'],
                                batch=40)
    assert len(run.calls) == 3
    bias = claude_cli.filter_bias(['aerial'])
    assert all(bias in _prompt(run, i) for i in range(3))


def test_the_biased_filter_still_degrades_rather_than_failing(run):
    """YTDL-13's guard is upstream of the prompt text and stays that way."""
    run.outcome = FakeProc(envelope('{"keep": null, "drop": null}'))
    assert claude_cli.filter_relevance('topic', _videos(2),
                                       shot_types=['aerial']) == {}


# ------------------------------------------- the ticks compose the fragments

def test_each_ticked_type_puts_its_own_phrasings_in_the_term_prompt():
    """A fragment appears when its box is ticked and not otherwise -- the whole
    point of the checkboxes."""
    only_aerial = claude_cli.term_bias(['aerial'])
    assert '空拍' in only_aerial and 'drone footage' in only_aerial
    for absent in ('縮時', 'timelapse', 'walking tour', '完整版', '典禮'):
        assert absent not in only_aerial, absent

    only_timelapse = claude_cli.term_bias(['timelapse'])
    assert '縮時' in only_timelapse and 'hyperlapse' in only_timelapse
    assert '空拍' not in only_timelapse


def test_ticking_a_coverage_type_stops_it_being_avoided_and_starts_it_being_sought():
    """Ticking `interview` means the editor WANTS talking heads: the avoid line
    has to go, and the seek line has to arrive."""
    off = claude_cli.term_bias(['aerial'])
    on = claude_cli.term_bias(['aerial', 'interview'])
    assert 'sit-down interview' in off, 'unticked: an AVOID line'
    assert 'AVOID' in off and '專訪' in off
    assert 'Interviews / talking heads: interview' in on, 'ticked: a SEEK line'
    # ...and it is no longer in the avoid list, which still holds the other two
    avoid_block = on[on.index('AVOID'):]
    assert 'talking head' not in avoid_block
    assert 'breaking news' in avoid_block and 'reaction' in avoid_block


def test_ticking_a_coverage_type_stops_the_filter_dropping_it():
    """The half an editor actually notices: with `interview` on, an interview
    must not be thrown away by the pass that runs after the search."""
    off = claude_cli.filter_bias(claude_cli.DEFAULT_SHOT_TYPES)
    on = claude_cli.filter_bias(list(claude_cli.DEFAULT_SHOT_TYPES) + ['interview'])
    assert 'interviews and talk/panel shows' in off
    drop_block = on[:on.index('KEEP')]
    assert 'interviews and talk/panel shows' not in drop_block
    assert '政論節目' not in drop_block
    keep_block = on[on.index('KEEP'):]
    assert 'interviews, talking heads and panel discussions' in keep_block
    # the two the editor did NOT tick are still dropped
    assert 'news anchors' in drop_block and 'reaction videos' in drop_block


def test_an_unticked_footage_type_is_not_sought_but_is_never_dropped():
    """The asymmetry, stated: an editor who wants aerials has not thereby
    banned timelapses, but one who left `news` off IS saying no to news."""
    bias = claude_cli.filter_bias(['aerial'])
    drop_block = bias[:bias.index('KEEP')]
    for footage in ('timelapse', 'walking tour', 'ceremon', 'establishing'):
        assert footage not in drop_block.lower(), footage
    assert 'news anchors' in drop_block


def test_a_coverage_only_selection_does_not_ask_for_pictures_over_talking():
    """PRIORITISE VISUALS is asserted only when a footage type is ticked."""
    assert 'PRIORITISE VISUALS' in claude_cli.term_bias(['aerial'])
    assert 'PRIORITISE VISUALS' not in claude_cli.term_bias(['interview'])
    assert 'Interviews / talking heads' in claude_cli.term_bias(['interview'])
    # ...and the footage-quality drop line goes with it: an interview IS a
    # talking head, not an over-edited compilation.
    assert 'heavy overlays' in claude_cli.filter_bias(['aerial'])
    assert 'heavy overlays' not in claude_cli.filter_bias(['interview'])


def test_the_uncut_preference_belongs_to_the_raw_box():
    assert 'LONGER, steadier' in claude_cli.filter_bias(['raw'])
    assert 'LONGER, steadier' not in claude_cli.filter_bias(['aerial'])


@pytest.mark.parametrize('selection', [[], ALL_SHOTS])
def test_all_ticked_and_none_ticked_both_mean_no_bias(selection):
    """A filter told to keep everything and drop everything is incoherent, and
    a filter told to keep every kind is a no-op -- so both are decided here
    rather than left to emerge from the loops."""
    terms = claude_cli.term_bias(selection)
    filt = claude_cli.filter_bias(selection)
    assert terms == claude_cli.term_bias([] if selection else ALL_SHOTS)
    assert filt == claude_cli.filter_bias([] if selection else ALL_SHOTS)
    assert 'NO SHOT-TYPE PREFERENCE' in terms and 'NO SHOT-TYPE PREFERENCE' in filt
    assert 'AVOID' not in terms
    assert 'DROP' in filt and 'KEEP it' in filt
    # nothing is dropped for being the wrong KIND of video, only for being the
    # wrong topic
    for kind in ('studio segments', 'interviews and talk', 'reaction videos',
                 'establishing shots', 'aerials'):
        assert kind not in filt, kind


def test_the_neutral_selection_still_reaches_the_model_intact(run):
    """Both degenerate cases go down the same prompt path as any other, so the
    envelope and the retry are untouched by them."""
    run.outcome = _terms_reply()
    out = claude_cli.generate_terms('x', shot_types=[])
    assert [t['q'] for t in out] == ['presidential office building taipei aerial',
                                     '總統府 空拍']
    p = _prompt(run)
    assert 'NO SHOT-TYPE PREFERENCE' in p
    assert '8 to 12 queries in English' in p and '{bias}' not in p


def test_an_unknown_or_repeated_key_costs_a_fragment_not_a_search():
    """This is fed from a job row that another build may have written; the API
    is where a bad key is refused, not here."""
    assert claude_cli.normalise_shot_types(['aerial', 'aerial']) == ('aerial',)
    assert claude_cli.normalise_shot_types(['nope']) == ()
    assert claude_cli.normalise_shot_types(['NEWS', ' raw ']) == ('raw', 'news')
    # ...and the order is the table's, whatever the caller sent
    assert claude_cli.normalise_shot_types(['raw', 'aerial']) == ('aerial', 'raw')
    # None is "nobody said", which is the defaults -- NOT the empty selection
    assert claude_cli.normalise_shot_types(None) == claude_cli.DEFAULT_SHOT_TYPES
    assert claude_cli.term_bias(None) == claude_cli.term_bias(
        claude_cli.DEFAULT_SHOT_TYPES)
    assert claude_cli.term_bias(None) != claude_cli.term_bias([])


def test_the_bias_is_one_fragment_table_and_nothing_else(run):
    """Tuning what a shot type means must be an edit to SHOT_TYPES, not a hunt
    through the two prompts."""
    src = (claude_cli.__file__).replace('.pyc', '.py')
    with open(src, encoding='utf-8') as fh:
        body = fh.read()
    term_prompt = body[body.index('_TERM_PROMPT = '):body.index('def generate_terms')]
    rel_prompt = body[body.index('_RELEVANCE_PROMPT = '):body.index('RELEVANCE_BATCH')]
    for prompt in (term_prompt, rel_prompt):
        assert '{bias}' in prompt
        for leaked in ('drone', '空拍', 'timelapse', '專訪', 'studio'):
            assert leaked not in prompt, leaked


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
