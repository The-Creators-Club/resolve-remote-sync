r"""Reveal is the EDITOR'S file manager, so it is not a route of this app.

MUSIC-6 (2026-08-14): `GET /api/reveal/{id}` ran `explorer /select,<path>` on
whatever host served the page. Port step 8 moved the Resolve actions off this
server for exactly that reason and left reveal behind: on the NAS container
`os.name != 'nt'`, so it answered 200 `{"ok": false, "path": "/mnt/tank/..."}`
-- a success as far as app.js's `api()` was concerned, discarded by a bare
`.catch(() => {})`. Every editor's reveal button did nothing, ever, with no
message, and the response handed the browser the NAS's absolute filesystem
path that the (share, rel_path) model exists to keep out of the payload.

It now goes browser -> `POST /music/reveal` on the editor's own companion
(127.0.0.1:8899), beside `/music/send`, translated against THAT machine's
mounts. What this file pins is that nothing here serves it any more, and that
the page asks the companion for it.

The older shell-injection guard this file used to hold (MUSIC-2, 2026-08-11:
`x&calc.mp3` through cmd.exe) moved with the route -- it is the companion's
`reveal_command`, which builds an argv list and never a command string.
"""
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / 'static'
APP_JS = (STATIC / 'app.js').read_text(encoding='utf-8')


def test_this_app_no_longer_serves_reveal(client):
    """A 404, not a dead 200: whatever the browser is told, it must not be
    told that revealing worked."""
    assert client.get('/api/reveal/1').status_code == 404


def test_no_route_of_this_app_is_a_reveal():
    """Belt to the 404's braces: a route by another name would be the same bug.
    The container has no Explorer and the NAS's Finder is nobody's."""
    from musicweb.main import app
    assert not [r for r in app.routes
                if 'reveal' in str(getattr(r, 'path', ''))]


def test_nothing_in_the_web_half_spawns_a_process():
    src = (Path(__file__).resolve().parent.parent
           / 'musicweb' / 'routes_ingest.py').read_text(encoding='utf-8')
    # subprocess is still how ffprobe/ffmpeg are reached; a Popen that nothing
    # waits for is what a file manager launch looks like.
    assert 'Popen' not in src


def test_the_page_asks_the_companion_to_reveal():
    assert "companion('/music/reveal'" in APP_JS
    assert 'api(`api/reveal' not in APP_JS


def test_reveal_sends_the_pair_and_never_a_path():
    """Same contract as /music/send: the page is served from the NAS, so only
    the editor's companion knows where the library is on their machine."""
    at = APP_JS.index("companion('/music/reveal'")
    body = APP_JS[at:at + 400]
    assert 'JSON.stringify({share:' in body
    assert 'rel_path: t.rel_path' in body


def test_a_reveal_failure_is_reported_and_not_swallowed():
    """The bug was silence. A companion that is missing, blocked or too old to
    know the route has to reach the editor as words in the pane."""
    at = APP_JS.index('async function revealOnThisMachine')
    fn = APP_JS[at:APP_JS.index('async function refreshResolveStatus')]
    assert 'msg.textContent' in fn
    assert 'catch (e)' in fn
    assert '.catch(() => {})' not in fn
