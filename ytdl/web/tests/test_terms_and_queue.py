"""The term review and the queue (2026-08-30).

The owner, verbatim: "youtube downloader should show a list of the search terms
it is going to use (for chinese ones, it should show a translation in
brackets). They begin all ticked and then you can untick individual ones or
untick all, or tick all. there should also be a queue so you can queue up
multiple searches."

Two features on one phase machine, so one file: the review is a new STOP
between generating_terms and searching, and the queue is what replaced "one job
per editor, 409 on the second". They meet in db.claim_next_job, where a job
parked for a person deliberately does NOT hold that person's queue up.

The worker is driven through worker.run_job() and db.claim_next_job() directly,
like the rest of this suite: YTDL_WORKER=0 is set in conftest and no daemon
thread is racing these rows.
"""
from tests.conftest import OTHER_USER, PROJECTS, USER
from ytdlweb import db, worker


def _wire(fake_youtube, results):
    fake_youtube.results = results
    fake_youtube.meta = {}
    fake_youtube.fail_terms = set()
    return fake_youtube


def _search_job(con, user=USER, term='algal reef controversy', project=0, **over):
    slug, label, _ = PROJECTS[project]
    return db.create_job(con, user, term, term.replace(' ', '-'), slug, label,
                         max_per_term=5, **over)


# --------------------------------------------------------- 1. the term review

def test_a_job_stops_at_the_term_review_with_every_term_ticked(
        con, review_job, fake_claude, fake_youtube):
    """The stop itself. Nothing has been searched when the worker returns."""
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa']})
    worker.run_job(con, review_job['id'])

    assert db.get_job(con, review_job['id'])['phase'] == 'terms_review'
    assert fake_youtube.searched == []
    terms = db.terms(con, review_job['id'])
    assert [t['term'] for t in terms] == [
        'algal reef controversy', 'algal reef taiwan', 'lng terminal protest',
        '藻礁 三接 爭議']
    assert all(t['enabled'] for t in terms), 'they begin all ticked'


def test_the_review_is_a_no_op_wait_the_worker_will_not_walk_past(
        con, review_job, fake_claude, fake_youtube):
    """Like ready_for_review: no handler, no timer, no default. A second tick
    of the loop must not decide for the editor."""
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa']})
    worker.run_job(con, review_job['id'])
    worker.run_job(con, review_job['id'])
    worker.run_job(con, review_job['id'])
    assert db.get_job(con, review_job['id'])['phase'] == 'terms_review'
    assert fake_youtube.searched == []
    # ...and the loop does not spin on it either: a parked job is not claimable
    assert db.claim_next_job(con) is None


def test_a_chinese_term_carries_its_translation_and_an_english_one_does_not(
        con, review_job, fake_claude, fake_youtube):
    """"for chinese ones, it should show a translation in brackets". The gloss
    the SAME Claude call already produced, under the name the review speaks --
    no second turn is spent on it."""
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa']})
    worker.run_job(con, review_job['id'])

    by_term = {t['term']: t for t in db.terms(con, review_job['id'])}
    assert by_term['藻礁 三接 爭議']['translation'] == \
        'algal reef third LNG terminal dispute'
    assert by_term['algal reef taiwan']['translation'] is None
    assert fake_claude.calls.count(('terms', 'algal reef controversy')) == 1


def test_the_editors_own_chinese_term_is_glossed_from_the_same_reply(
        con, fake_claude, fake_youtube):
    """The row that would otherwise have no bracket: it is written BEFORE the
    model is asked anything, and for a topic typed in Chinese it is the one an
    editor most needs translated. Matched on the text the model echoed back --
    no extra call is made for it."""
    fake_claude.terms = [
        {'q': '藻礁', 'lang': 'zh', 'english_gloss': 'algal reef',
         'translation': 'algal reef'},
        {'q': '藻礁 公投', 'lang': 'zh', 'english_gloss': 'algal reef referendum',
         'translation': 'algal reef referendum'},
    ]
    job_id = _search_job(con, term='藻礁')
    _wire(fake_youtube, {'藻礁': ['aaaaaaaaaaa']})
    worker.run_job(con, job_id)

    own = db.terms(con, job_id)[0]
    assert (own['term'], own['source']) == ('藻礁', 'user')
    assert own['translation'] == 'algal reef'


def test_auto_terms_skips_the_stop_and_searches_everything(
        con, job, fake_claude, fake_youtube):
    """The headless path: a script posts {auto_terms: true} because nobody is
    watching its job to press the button for it."""
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa'],
                         'algal reef taiwan': ['bbbbbbbbbbb'],
                         'lng terminal protest': ['ccccccccccc'],
                         '藻礁 三接 爭議': ['ddddddddddd']})
    worker.run_job(con, job['id'])

    fresh = db.get_job(con, job['id'])
    assert fresh['phase'] == 'ready_for_review'
    assert fresh['terms_total'] == 4 and fresh['terms_done'] == 4
    assert all(t['enabled'] for t in db.terms(con, job['id']))


def test_an_exact_search_never_stops_at_a_review_of_one_term(
        con, fake_claude, fake_youtube):
    """`exact` has one term, the editor's own text, generated by nobody:
    parking that in front of them to confirm what they just typed would be a
    click for no information."""
    job_id = _search_job(con, term='reef', term_scope='exact', project=1)
    _wire(fake_youtube, {'reef': ['aaaaaaaaaaa']})
    worker.run_job(con, job_id)
    assert db.get_job(con, job_id)['phase'] == 'ready_for_review'


def test_only_the_ticked_terms_are_searched_and_counted(
        con, review_job, fake_claude, fake_youtube):
    """The whole point of the untick: an unticked term is not searched late or
    searched quietly, it is never looked at -- and terms_total is the number
    the progress bar counts up to."""
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa'],
                         'algal reef taiwan': ['bbbbbbbbbbb'],
                         'lng terminal protest': ['ccccccccccc'],
                         '藻礁 三接 爭議': ['ddddddddddd']})
    worker.run_job(con, review_job['id'])

    keep = [t['id'] for t in db.terms(con, review_job['id'])
            if t['term'] in ('algal reef controversy', '藻礁 三接 爭議')]
    assert db.set_terms_enabled(con, review_job['id'], keep) == 2
    db.set_phase(con, review_job['id'], 'searching')
    worker.run_job(con, review_job['id'])

    fresh = db.get_job(con, review_job['id'])
    assert fresh['phase'] == 'ready_for_review'
    assert [q for q, _n, _p in fake_youtube.searched] == \
        ['algal reef controversy', '藻礁 三接 爭議']
    assert fresh['terms_total'] == 2 and fresh['terms_done'] == 2
    assert {v['video_id'] for v in db.videos(con, review_job['id'])} == \
        {'aaaaaaaaaaa', 'ddddddddddd'}


def test_the_selection_can_be_sent_as_term_text_as_well_as_ids(
        con, review_job, fake_claude, fake_youtube):
    """A script driving this by hand has the queries it just read, not the row
    ids. Anything unrecognised is ignored rather than refused; the answer is
    how many ended up ticked, which is the number a caller checks."""
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa']})
    worker.run_job(con, review_job['id'])
    assert db.set_terms_enabled(con, review_job['id'],
                               ['lng terminal protest', 'never generated']) == 1
    assert [t['term'] for t in db.enabled_terms(con, review_job['id'])] == \
        ['lng terminal protest']


def test_a_review_job_can_be_cancelled_outright(
        con, review_job, fake_claude, fake_youtube):
    """YTDL-1's rule reaches the new phase: nothing is in flight, so the flag
    alone would be a cancel that never happened."""
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa']})
    worker.run_job(con, review_job['id'])
    assert db.cancel_now(con, review_job['id']) is True
    assert db.get_job(con, review_job['id'])['phase'] == 'cancelled'


# ---------------------------------------------------------------- 2. the queue

def test_the_second_job_waits_and_starts_when_the_first_stops_being_busy(con):
    """The queue's whole behaviour in one walk: one job runs, the next waits,
    and it becomes claimable the moment the first is no longer busy."""
    first = _search_job(con)
    second = _search_job(con, term='offshore wind', project=1)
    assert db.claim_next_job(con)['id'] == first

    db.set_phase(con, first, 'searching')
    assert db.claim_next_job(con)['id'] == first, 'work in flight comes first'

    db.set_phase(con, first, 'done')
    assert db.claim_next_job(con)['id'] == second


def test_a_job_waiting_for_a_person_does_not_hold_up_that_persons_queue(con):
    """The reason terms_review and ready_for_review are not BUSY. A manifest
    nobody has looked at for a week used to block every later search (YTDL-25's
    409); now the next one runs while they get to it."""
    for parked in ('terms_review', 'ready_for_review'):
        con.execute('DELETE FROM jobs')
        con.commit()
        first = _search_job(con)
        second = _search_job(con, term='offshore wind', project=1)
        db.set_phase(con, first, parked)
        assert db.claim_next_job(con)['id'] == second, parked


def test_two_editors_queues_are_independent(con):
    """One editor's running job must never hold another editor's search back:
    the NOT EXISTS is scoped to created_by and nothing else."""
    mine = _search_job(con)
    db.set_phase(con, mine, 'downloading')
    theirs = db.create_job(con, OTHER_USER, 'wind', 'wind', PROJECTS[1][0],
                           PROJECTS[1][1])
    assert db.claim_next_job(con)['id'] == mine       # in flight first
    db.set_phase(con, mine, 'enriching')
    # ...and with mine mid-phase, theirs is the next thing a free worker takes
    assert [j['id'] for j in db.queued_jobs(con, OTHER_USER)] == [theirs]
    assert db.queued_jobs(con, USER) == []
    db.set_phase(con, mine, 'ready_for_review')
    assert db.claim_next_job(con)['id'] == theirs


def test_the_queue_runs_in_its_own_order_not_in_id_order(con):
    """What [ UP ] and [ DOWN ] are for. The stored positions decide, and the
    whole queue is renumbered so no two rows can share one."""
    a = _search_job(con, term='a')
    b = _search_job(con, term='b')
    c = _search_job(con, term='c')
    db.set_phase(con, a, 'searching')                 # something is busy

    assert db.move_in_queue(con, USER, c, 1) == [c, b]
    assert [j['queue_position'] for j in db.queued_jobs(con, USER)] == [1, 2]
    db.set_phase(con, a, 'done')
    assert db.claim_next_job(con)['id'] == c


def test_a_move_is_clamped_rather_than_refused(con):
    """[ UP ] on the first row is a no-op an editor will press, not an error."""
    a = _search_job(con, term='a')
    b = _search_job(con, term='b')
    assert db.move_in_queue(con, USER, a, 0) == [a, b]
    assert db.move_in_queue(con, USER, a, 99) == [b, a]
    assert db.move_in_queue(con, USER, 9999, 1) is None


def test_a_cancelled_queue_entry_leaves_the_rest_in_order(con):
    """A queue with a hole in its numbering still hands the next arrival a
    place at the back."""
    a = _search_job(con, term='a')
    b = _search_job(con, term='b')
    db.cancel_now(con, a)
    third = _search_job(con, term='c')
    assert [j['id'] for j in db.queued_jobs(con, USER)] == [b, third]
    assert db.get_job(con, third)['queue_position'] == 3


def test_a_local_download_lease_still_hides_a_job_from_the_worker(con):
    """docs/YTDL_LOCAL_DOWNLOAD.md §3, unchanged by the queue: a job the
    requester's companion is downloading right now is invisible to the loop,
    and the editor's NEXT job is what the worker sees instead."""
    mine = _search_job(con)
    later = _search_job(con, term='offshore wind', project=1)
    db.set_phase(con, mine, 'downloading')
    assert db.claim_download(con, mine, USER, 300, machine='m1')
    assert db.claim_next_job(con) is None, \
        'a leased download is not busy work the loop may take, but it IS busy'


# ------------------------------------------------------------- 3. the routes

def _headers(user):
    return {'x-ccsync-user': user}


def _reviewing(con, review_job, fake_claude, fake_youtube):
    """Walk the fixture job to the term review and hand back its term ids."""
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa'],
                         'algal reef taiwan': ['bbbbbbbbbbb'],
                         'lng terminal protest': ['ccccccccccc'],
                         '藻礁 三接 爭議': ['ddddddddddd']})
    worker.run_job(con, review_job['id'])
    return [t['id'] for t in db.terms(con, review_job['id'])]


def test_the_poll_carries_every_term_with_its_translation_and_tick(
        client, con, review_job, fake_claude, fake_youtube):
    """What the SPA renders the review from. One shape (db.term_dict), so the
    poll and the manifest cannot drift apart by a field again."""
    _reviewing(con, review_job, fake_claude, fake_youtube)
    r = client.get(f'/api/jobs/{review_job["id"]}').json()
    assert r['job']['phase'] == 'terms_review'
    zh = [t for t in r['terms'] if t['lang'] == 'zh'][0]
    assert zh['translation'] == 'algal reef third LNG terminal dispute'
    assert zh['enabled'] is True
    en = [t for t in r['terms'] if t['term'] == 'algal reef taiwan'][0]
    assert en['translation'] is None, 'nothing to print in brackets'
    assert en['enabled'] is True


def test_the_ticks_are_posted_once_and_the_rest_are_cleared(
        client, con, review_job, fake_claude, fake_youtube):
    ids = _reviewing(con, review_job, fake_claude, fake_youtube)
    r = client.post(f'/api/jobs/{review_job["id"]}/terms',
                    json={'enabled': [ids[0], ids[2]]})
    assert r.status_code == 200
    assert r.json() == {'ok': True, 'enabled': 2, 'total': 4}
    assert [t['id'] for t in db.enabled_terms(con, review_job['id'])] == \
        [ids[0], ids[2]]

    # ...and a second post is the whole set again, not a delta
    client.post(f'/api/jobs/{review_job["id"]}/terms', json={'enabled': [ids[1]]})
    assert [t['id'] for t in db.enabled_terms(con, review_job['id'])] == [ids[1]]


def test_continue_moves_the_job_to_searching_with_the_ticked_count(
        client, con, review_job, fake_claude, fake_youtube):
    ids = _reviewing(con, review_job, fake_claude, fake_youtube)
    client.post(f'/api/jobs/{review_job["id"]}/terms', json={'enabled': ids[:2]})
    r = client.post(f'/api/jobs/{review_job["id"]}/terms/continue')
    assert r.status_code == 200
    assert r.json() == {'ok': True, 'phase': 'searching', 'terms': 2}
    fresh = db.get_job(con, review_job['id'])
    assert fresh['phase'] == 'searching' and fresh['terms_total'] == 2


def test_continuing_with_nothing_ticked_is_a_400(
        client, con, review_job, fake_claude, fake_youtube):
    """UNTICK ALL is a legal thing to be looking at and an illegal thing to
    search: the phase does not move, so the editor still has their terms."""
    _reviewing(con, review_job, fake_claude, fake_youtube)
    assert client.post(f'/api/jobs/{review_job["id"]}/terms',
                       json={'enabled': []}).status_code == 200
    r = client.post(f'/api/jobs/{review_job["id"]}/terms/continue')
    assert r.status_code == 400
    assert 'tick at least one' in r.json()['detail']
    assert db.get_job(con, review_job['id'])['phase'] == 'terms_review'


def test_both_term_routes_refuse_a_job_that_is_not_at_the_review(
        client, con, review_job, fake_claude, fake_youtube):
    """The phase IS the permission: before it there are no terms, and after it
    the search has already run on them."""
    ids = _reviewing(con, review_job, fake_claude, fake_youtube)
    db.set_phase(con, review_job['id'], 'searching')
    for path, body in ((f'/api/jobs/{review_job["id"]}/terms', {'enabled': ids}),
                       (f'/api/jobs/{review_job["id"]}/terms/continue', {})):
        r = client.post(path, json=body)
        assert r.status_code == 409, path
        assert r.json()['detail']['phase'] == 'searching'


def test_the_term_routes_are_another_editors_404(
        client, con, review_job, fake_claude, fake_youtube):
    """A job belongs to the editor who created it, filtered in SQL: another
    editor gets "there is no such job", which is all they are entitled to."""
    ids = _reviewing(con, review_job, fake_claude, fake_youtube)
    r = client.post(f'/api/jobs/{review_job["id"]}/terms',
                    json={'enabled': ids}, headers=_headers(OTHER_USER))
    assert r.status_code == 404


def test_auto_terms_from_the_api_skips_the_review(client, con, fake_claude,
                                                  fake_youtube):
    """The headless path, end to end. The SPA never sends this field."""
    r = client.post('/api/jobs', json={'term': 'algal reef controversy',
                                       'project_slug': PROJECTS[0][0],
                                       'auto_terms': True})
    job_id = r.json()['job_id']
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa'],
                         'algal reef taiwan': ['bbbbbbbbbbb'],
                         'lng terminal protest': ['ccccccccccc'],
                         '藻礁 三接 爭議': ['ddddddddddd']})
    worker.run_job(con, job_id)
    assert db.get_job(con, job_id)['phase'] == 'ready_for_review'


def test_an_ordinary_api_job_stops_for_the_person_who_asked(
        client, con, fake_claude, fake_youtube):
    r = client.post('/api/jobs', json={'term': 'algal reef controversy',
                                       'project_slug': PROJECTS[0][0]})
    job_id = r.json()['job_id']
    _wire(fake_youtube, {'algal reef controversy': ['aaaaaaaaaaa']})
    worker.run_job(con, job_id)
    assert db.get_job(con, job_id)['phase'] == 'terms_review'


def test_the_active_route_answers_the_running_job_and_the_queue(client, con):
    first = client.post('/api/jobs', json={'term': 'a',
                                           'project_slug': PROJECTS[0][0]}).json()
    db.set_phase(con, first['job_id'], 'searching')
    second = client.post('/api/jobs', json={'term': 'b',
                                            'project_slug': PROJECTS[1][0]}).json()
    third = client.post('/api/jobs', json={'term': 'c',
                                           'project_slug': PROJECTS[0][0]}).json()

    r = client.get('/api/jobs/active').json()
    assert r['job']['id'] == first['job_id']
    assert [q['id'] for q in r['queue']] == [second['job_id'], third['job_id']]
    assert [q['position'] for q in r['queue']] == [1, 2]
    assert r['queue'][0]['term'] == 'b'
    assert r['queue'][0]['project_label'] == PROJECTS[1][1]
    # another editor sees none of it
    assert client.get('/api/jobs/active',
                      headers=_headers(OTHER_USER)).json() == {
        'job': None, 'queue': [], 'waiting': []}


def test_the_running_job_is_never_also_a_queue_row(client, con):
    """Between "created" and "claimed" the head of the queue IS the active job,
    and a page showing it twice would offer [ UP ] on the thing that is about
    to run."""
    only = client.post('/api/jobs', json={'term': 'a',
                                          'project_slug': PROJECTS[0][0]}).json()
    r = client.get('/api/jobs/active').json()
    assert r['job']['id'] == only['job_id']
    assert r['queue'] == []


def test_moving_a_queued_job_rewrites_the_whole_order(client, con):
    running = client.post('/api/jobs', json={'term': 'a',
                                             'project_slug': PROJECTS[0][0]}).json()
    db.set_phase(con, running['job_id'], 'searching')
    b = client.post('/api/jobs', json={'term': 'b',
                                       'project_slug': PROJECTS[0][0]}).json()
    c = client.post('/api/jobs', json={'term': 'c',
                                       'project_slug': PROJECTS[0][0]}).json()

    r = client.post(f'/api/jobs/{c["job_id"]}/queue/move', json={'position': 1})
    assert r.status_code == 200
    assert [q['id'] for q in r.json()['queue']] == [c['job_id'], b['job_id']]
    assert [q['position'] for q in r.json()['queue']] == [1, 2]


def test_moving_a_job_that_is_no_longer_queued_is_a_409(client, con):
    """The worker started it while the page was deciding. The phase comes back
    with the refusal so the SPA can re-render instead of guessing."""
    running = client.post('/api/jobs', json={'term': 'a',
                                             'project_slug': PROJECTS[0][0]}).json()
    db.set_phase(con, running['job_id'], 'searching')
    r = client.post(f'/api/jobs/{running["job_id"]}/queue/move',
                    json={'position': 1})
    assert r.status_code == 409
    assert r.json()['detail']['phase'] == 'searching'


def test_a_queued_job_is_cancelled_by_the_route_that_already_exists(client, con):
    running = client.post('/api/jobs', json={'term': 'a',
                                             'project_slug': PROJECTS[0][0]}).json()
    db.set_phase(con, running['job_id'], 'searching')
    waiting = client.post('/api/jobs', json={'term': 'b',
                                             'project_slug': PROJECTS[0][0]}).json()
    assert client.post(f'/api/jobs/{waiting["job_id"]}/cancel').json()['phase'] \
        == 'cancelled'
    assert client.get('/api/jobs/active').json()['queue'] == []


def test_a_queued_job_is_not_claimable_by_a_companion_until_it_downloads(
        client, con):
    """docs/YTDL_LOCAL_DOWNLOAD.md section 3, unchanged: the claim route's own
    phase check is what refuses it, and a job waiting in the queue has not
    reached the download phase."""
    waiting = client.post('/api/jobs', json={'term': 'a',
                                             'project_slug': PROJECTS[0][0]}).json()
    job = db.get_job(con, waiting['job_id'])
    assert job['phase'] == 'queued'
    assert job['download_mode'] == db.MODE_SERVER and job['claimed_by'] is None
