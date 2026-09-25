"""The 2026-09-24 hunt, wave 2 (mediums and lows), the YouTube page's half.

Every test here fails on HEAD 4462a2a and passes after the fix beside it; the
ids are the hunt's (`docs/bug-hunt-2026-09-24/hunters/*.md`) and are cited at
the code sites. The page is driven in node with only the functions under test
extracted (the harness in test_static_app.py is for whole-page races); node is
not a dependency of this app, so those tests skip without it and the source
checks always run.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parent.parent / 'static' / 'app.js'
NODE = shutil.which('node')
needs_node = pytest.mark.skipif(NODE is None, reason='node is not installed')


def _src():
    return APP_JS.read_text(encoding='utf-8')


def _function(body, name):
    start = body.index(f'function {name}(')
    if body[start - 6:start] == 'async ':
        start -= 6
    end = body.index('\n}\n', start) + 3
    return body[start:end]


def _node(script, tmp_path):
    f = tmp_path / 'case.js'
    f.write_text(script, encoding='utf-8')
    out = subprocess.run([NODE, str(f)], capture_output=True, text=True,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


# --------------------------------------------------------------------------
# ui-music-ytdl-web-2: a click on the title must not tick or untick the clip
# --------------------------------------------------------------------------

@needs_node
def test_clicking_a_clip_title_does_not_change_its_selection(tmp_path):
    """The title is an <a target=_blank> inside the card and the card's
    onclick toggles the selection. HEAD's link had no handler, so the click
    bubbled: previewing a clip flipped what DOWNLOAD would take."""
    card = _function(_src(), 'card')
    got = _node(r"""
const toggled = [];
function el(tag, cls, text) {
  return {tag, className: cls || '', textContent: text || '', children: [],
          parent: null, style: {},
          appendChild(c) { c.parent = this; this.children.push(c); return c; }};
}
const thumb = () => el('img');
const fmtDur = () => '1:00', fmtDate = () => '2026';
function toggle(v, on) { toggled.push(on); }
function find(n, cls) {
  if (n.className === cls) return n;
  for (const c of n.children) { const f = find(c, cls); if (f) return f; }
  return null;
}
function click(node) {
  const e = {stopped: false, stopPropagation() { this.stopped = true; }};
  for (let x = node; x && !e.stopped; x = x.parent) if (x.onclick) x.onclick(e);
}
""" + card + r"""
const v = {video_id: 'abc', title: 'A clip', url: 'https://youtu.be/abc',
           selected: 1, relevant: true, channel: 'c'};
const n = card(v);
click(find(n, 'title'));
const afterTitle = toggled.length;
click(find(n, 'meta'));
console.log(JSON.stringify({afterTitle, afterCard: toggled.length}));
""", tmp_path)
    assert got['afterTitle'] == 0, 'opening the clip on YouTube changed its tick'
    assert got['afterCard'] == 1, 'a click on the card body must still toggle'


# --------------------------------------------------------------------------
# logic-ytdl-jobs-3: the page never said why this computer gave a job back
# --------------------------------------------------------------------------

def _hand_back_block():
    body = _src()
    start = body.index('const HAND_BACK_WATCH_MS')
    end = body.index('// A speed the companion reported.')
    return body[start:end]


REASON = ('This computer has 2.0 GB free and this download needs about 6.0 GB, '
          'so the server is downloading it instead.')


def _watch(tmp_path, rows):
    return _node(r"""
const toasts = [];
function toast(t) { toasts.push(String(t)); }
const PROBE_MS = 1000, COMPANION_URL = 'http://127.0.0.1:8899';
let localProgressOff = false;
const answers = """ + json.dumps(rows) + r""";
let calls = 0;
global.fetch = async () => {
  const jobs = answers[Math.min(calls, answers.length - 1)];
  calls++;
  return {ok: true, status: 200, json: async () => ({jobs})};
};
const realSet = setTimeout;
global.setTimeout = (fn, ms) => realSet(fn, 0);
""" + _hand_back_block() + r"""
(async () => {
  await watchHandBack(7);
  console.log(JSON.stringify({toasts, calls}));
})();
""", tmp_path)


@needs_node
def test_a_hand_back_after_the_202_is_said_once_in_the_companions_words(tmp_path):
    rows = [
        [{'job_id': 7, 'phase': 'starting', 'running': True}],
        [{'job_id': 7, 'phase': 'handed_back', 'running': False,
          'title': 'gulf coast', 'handed_back_reason': REASON}],
    ]
    got = _watch(tmp_path, rows)
    assert len(got['toasts']) == 1, got
    assert REASON in got['toasts'][0]
    assert 'gulf coast' in got['toasts'][0]
    assert '—' not in got['toasts'][0]


@needs_node
def test_another_jobs_row_and_the_editors_own_stop_are_not_announced(tmp_path):
    rows = [
        [{'job_id': 6, 'phase': 'handed_back', 'handed_back_reason': REASON}],
        [{'job_id': 7, 'phase': 'cancelled', 'running': False,
          'handed_back_reason': 'You stopped it.'}],
    ]
    got = _watch(tmp_path, rows)
    assert got['toasts'] == [], got
    assert got['calls'] == 2, 'a cancelled row ends the watch'


def test_the_202_starts_the_watch_and_a_local_poll_reads_the_reason_too():
    body = _src()
    dispatch = _function(body, 'dispatchLocal')
    assert 'watchHandBack(jobId)' in dispatch
    assert dispatch.index('watchHandBack(jobId)') < dispatch.index('return true')
    assert 'announceHandBack(jobId, mine)' in _function(body, 'pollLocalProgress')


# --------------------------------------------------------------------------
# logic-ytdl-jobs-4: the terms toast named a right-click item CR-88 removed
# --------------------------------------------------------------------------

def _terms_toast(tmp_path, reason):
    body = _src()
    start = body.index('let lastCompanionRefusal')
    end = body.index('\n}\n', body.index('function explainCompanionRefusal(')) + 3
    return _node(r"""
const toasts = [];
function toast(t) { toasts.push(String(t)); }
""" + body[start:end] + r"""
explainCompanionRefusal(""" + json.dumps(reason) + r""");
console.log(JSON.stringify(toasts));
""", tmp_path)


@needs_node
def test_the_terms_toast_names_the_route_the_companion_gave(tmp_path):
    """HEAD dropped the companion's reason and said "right-click the tray
    icon, then 'Accept YouTube Terms'": the right-click menu has had no such
    item since CR-88 (companion 0.9.54). The reason carries the route
    (ytdl_executor.REASON_NOT_ATTESTED + ui_copy.YOUTUBE_TERMS)."""
    reason = ('the YouTube terms have not been accepted on this computer: '
              'Tray > Settings > Accept YouTube Terms')
    [said] = _terms_toast(tmp_path, reason)
    assert 'Tray > Settings > Accept YouTube Terms' in said, said
    assert 'right-click' not in said, said
    assert 'runs on the server instead' in said
    assert '—' not in said


@needs_node
def test_a_reason_without_a_route_gets_the_current_one(tmp_path):
    [said] = _terms_toast(tmp_path, 'the YouTube terms were not accepted')
    assert 'Tray > Settings > Accept YouTube Terms' in said, said
    assert 'right-click' not in said, said


def test_the_fallback_route_is_the_companions_constant():
    """The page cannot import ui_copy; this pins the copy so a rename there
    is noticed here (the 2026-09-03 sweep's "that string breaks silently")."""
    ui_copy = (Path(__file__).resolve().parents[3] / 'companion' / 'src'
               / 'ccsync_companion' / 'ui_copy.py')
    if not ui_copy.exists():
        pytest.skip('companion tree not beside this checkout')
    import re
    m = re.search(r'^YOUTUBE_TERMS = "([^"]+)"',
                  ui_copy.read_text(encoding='utf-8'), re.M)
    assert m and f"TERMS_ROUTE_FALLBACK = '{m.group(1)}'" in _src()


# --------------------------------------------------------------------------
# ui-music-ytdl-web-10: Recent searches printed the database's phase enum
# --------------------------------------------------------------------------

@needs_node
def test_recent_searches_use_the_progress_strips_words(tmp_path):
    body = _src()
    start = body.index('const PHASE_LABEL = {')
    table = body[start:body.index('};', start) + 2]
    got = _node(r"""
function el(tag, cls, text) {
  return {tag, className: cls || '', textContent: text || '', title: '',
          children: [], appendChild(c) { this.children.push(c); return c; }};
}
const box = el('div');
const $ = s => s === '#recentlist' ? box : {textContent: ''};
const plural = (n, a, b) => `${n} ${n === 1 ? a : b}`;
const searchModeSummary = () => '', termScopeSummary = () => '';
const dateSummary = () => '', shotSummary = () => '', capSummary = () => '';
function attach() {}
async function api() {
  return {jobs: [{id: 1, phase: 'ready_for_review', term: 't', project_label: 'P',
                  created_at: '2026-09-23T09:10'},
                 {id: 2, phase: 'terms_review', term: 't', project_label: 'P'},
                 {id: 3, phase: 'some_new_phase', term: 't', project_label: 'P'}]};
}
""" + table + '\n' + _function(body, 'loadRecent') + r"""
loadRecent().then(() => {
  const ph = box.children.map(r => r.children.find(c => c.className === 'ph'));
  console.log(JSON.stringify(ph.map(p => p.textContent)));
});
""", tmp_path)
    assert got == ['ready for review', 'pick the search terms',
                   'some_new_phase'], got


# --------------------------------------------------------------------------
# ui-music-ytdl-web-3: the terms lock on SEARCH / GET LINKS / DOWNLOAD
# --------------------------------------------------------------------------

def _lock_harness():
    body = _src()
    sync = ''
    if 'function syncSubmitButtons(' in body:
        sync = body[body.index('const ATTEST_TITLE'):
                    body.index('\n}\n', body.index('function syncSubmitButtons(')) + 3]
    return r"""
function mkButton(title) {
  const attrs = title ? {title} : {};
  return {disabled: false, dataset: {},
          get title() { return attrs.title || ''; },
          set title(v) { attrs.title = v; },
          removeAttribute(k) { delete attrs[k]; }};
}
const buttons = {'#go': mkButton(''),
                 '#golinks': mkButton('Downloads exactly these videos'),
                 '#download': mkButton('')};
const attest = {classList: {toggle() {}}};
global.document = {querySelector: s => buttons[s] || null};
const sel = {innerHTML: '', value: '', appendChild() {}};
const $ = s => s === '#attest' ? attest : s === '#project' ? sel : buttons[s];
const state = {manifest: null};
const toasts = [];
function toast(t) { toasts.push(String(t)); }
function renderGrid() {}
""" + _function(body, 'setAttested') + sync + r"""
function snap() {
  return Object.fromEntries(Object.entries(buttons).map(
    ([k, b]) => [k, [b.disabled, b.title]]));
}
"""


@needs_node
def test_the_project_loader_does_not_undo_the_terms_lock(tmp_path):
    """init awaits loadAttestation (which locks) and then loadProjects, which
    at HEAD set both submit buttons back to enabled whenever a project
    existed. Accepting then restores each button's OWN tooltip: HEAD read
    `dataset.title`, which nothing set, and kept the lock's sentence."""
    body = _src()
    got = _node(_lock_harness() + r"""
function el() { return {}; }
function setBanner() {}
function localWanted() { return false; }
function loadProject() { return ''; }
function saveProject() {}
let localMachine = '';
async function api() { return {projects_available: true,
                                projects: [{slug: 'a', label: 'A'}]}; }
""" + _function(body, 'loadProjects') + r"""
(async () => {
  setAttested(false);
  await loadProjects();
  const locked = snap();
  setAttested(true);
  console.log(JSON.stringify({locked, open: snap()}));
})();
""", tmp_path)
    assert got['locked']['#go'][0] is True, got
    assert got['locked']['#golinks'][0] is True, got
    assert got['open']['#go'][0] is False and got['open']['#golinks'][0] is False
    assert got['open']['#golinks'][1] == 'Downloads exactly these videos', got
    assert got['open']['#go'][1] == '', got


@needs_node
def test_accepting_does_not_unlock_over_no_projects(tmp_path):
    """HEAD's setAttested(true) enabled SEARCH over "you are not syncing any
    project"."""
    got = _node(_lock_harness() + r"""
buttons['#go'].disabled = true; buttons['#golinks'].disabled = true;
state.hasProjects = false;
setAttested(true);
console.log(JSON.stringify(snap()));
""", tmp_path)
    assert got['#go'][0] is True and got['#golinks'][0] is True, got


@needs_node
def test_a_finished_submit_does_not_unlock_either(tmp_path):
    """runSearch/runUrls' `finally` re-enabled the button unconditionally."""
    body = _src()
    for name, flag in (('runSearch', 'searching'), ('runUrls', 'linking')):
        fn = _function(body, name)
        tail = fn[fn.rindex('finally'):]
        assert f'state.{flag} = false' in tail, name
        assert 'syncSubmitButtons()' in tail, name
        assert '.disabled = false' not in tail, name
    got = _node(_lock_harness() + r"""
setAttested(false);
state.searching = true; syncSubmitButtons();
state.searching = false; syncSubmitButtons();
console.log(JSON.stringify(snap()));
""", tmp_path)
    assert got['#go'][0] is True, got


def test_download_stays_locked_until_the_terms_are_accepted():
    fn = _function(_src(), 'renderGrid')
    at = fn.index("$('#download').disabled")
    assert 'state.attested === false' in fn[at:fn.index(';', at)]


# --------------------------------------------------------------------------
# ui-music-ytdl-web-1: the page had no phone layout
# --------------------------------------------------------------------------

def test_the_search_row_wraps_and_a_phone_gets_a_layout():
    """HEAD: `.search-bar` was a non-wrapping flex row of six controls that
    cannot shrink (847 px) and the stylesheet had no @media rule at all.
    Measured in headless Chrome with this stylesheet: 500 px wide, HEAD
    scrollWidth 912, fixed 500; 1280 and 1000 px render identically."""
    css = (APP_JS.parent / 'style.css').read_text(encoding='utf-8')
    import re
    bar = re.search(r'\n\.search-bar \{([^}]*)\}', css).group(1)
    assert 'flex-wrap: wrap' in bar, bar
    m = re.search(r'@media \(max-width: 600px\) \{(.*?)\n\}', css, re.S)
    assert m, 'no narrow layout'
    assert '.search-bar > #q' in m.group(1)


# --------------------------------------------------------------------------
# Owed round (2026-09-25): bug-wire-2, an identity signed with a retired
# dashboard key is accepted on the fleet routes, accept-only
# --------------------------------------------------------------------------

from fastapi import HTTPException  # noqa: E402

from ytdlweb import config, identity, routes_fleet  # noqa: E402

CURRENT = 'the-current-session-secret-0123'
RETIRED = 'a-retired-session-secret-0123456789'


def test_an_identity_signed_with_a_retired_key_is_accepted(monkeypatch):
    """HEAD verified against SESSION_SECRET alone: for a whole rotation drain
    every un-re-signed machine's claims 403'd and the NAS took every job."""
    monkeypatch.setattr(config, 'SESSION_SECRET', CURRENT)
    monkeypatch.setenv('DASH_SESSION_SECRET_PREVIOUS', f' ,{RETIRED}, ')
    token = identity.make_identity_token(RETIRED, 'jsmith')
    assert routes_fleet.require_identity(token) == 'jsmith'


def test_previous_secrets_parse_like_the_dashboards(monkeypatch):
    monkeypatch.setenv('DASH_SESSION_SECRET_PREVIOUS', ' a , ,b,, ')
    assert config.session_secrets_previous() == ('a', 'b')
    monkeypatch.delenv('DASH_SESSION_SECRET_PREVIOUS', raising=False)
    assert config.session_secrets_previous() == ()


def test_a_key_that_was_never_ours_is_still_refused(monkeypatch):
    monkeypatch.setattr(config, 'SESSION_SECRET', CURRENT)
    monkeypatch.setenv('DASH_SESSION_SECRET_PREVIOUS', RETIRED)
    with pytest.raises(HTTPException) as exc:
        routes_fleet.require_identity(
            identity.make_identity_token('never-ours-secret-0123456789', 'jsmith'))
    assert exc.value.status_code == 403
    assert exc.value.detail['reason'] == 'identity'


def test_a_retired_key_does_not_stand_in_for_an_unset_current_one(monkeypatch):
    monkeypatch.setattr(config, 'SESSION_SECRET', '')
    monkeypatch.setenv('DASH_SESSION_SECRET_PREVIOUS', RETIRED)
    with pytest.raises(HTTPException) as exc:
        routes_fleet.require_identity(identity.make_identity_token(RETIRED, 'jsmith'))
    assert exc.value.detail['reason'] == 'identity_unconfigured'


# ui-dash-static-5 parity: the page's muted text clears AA on every surface.

def _lum(h):
    h = h.lstrip('#')
    def ch(v):
        v = int(v, 16) / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(h[i:i + 2]) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def test_muted_text_meets_aa_on_every_surface():
    import re
    css = (APP_JS.parent / 'style.css').read_text(encoding='utf-8')
    tok = dict(re.findall(r'--(bg|panel|field|muted):\s*(#[0-9a-fA-F]{6})', css))
    fg = _lum(tok['muted'])
    for surface in ('bg', 'panel', 'field'):
        assert (fg + 0.05) / (_lum(tok[surface]) + 0.05) >= 4.5, surface


def test_the_drawer_close_control_meets_aa_on_the_drawer_panel():
    # ui-dash-static owed round 2 (2026-09-25): was var(--red-dim), 1.78:1.
    import re
    css = (APP_JS.parent / 'style.css').read_text(encoding='utf-8')
    tok = dict(re.findall(r'--([a-z-]+):\s*(#[0-9a-fA-F]{6})', css))
    m = re.search(r'\.drawer-close\s*\{[^}]*?color:\s*var\(--([a-z-]+)\)', css)
    assert m, 'no .drawer-close colour'
    fg, bg = _lum(tok[m.group(1)]), _lum(tok['panel'])
    assert (max(fg, bg) + 0.05) / (min(fg, bg) + 0.05) >= 4.5, m.group(1)
