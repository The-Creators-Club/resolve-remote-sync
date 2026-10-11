"""`/cards`: which episode, which cut file. The page that needs no engine.

docs/CARDS_TWO_PROJECTS.md phase 1 and 1b (2026-09-14).

Three jobs, and the first one is the reason this is a dashboard route and not
a route of the mounted page:

  * **IT DRAWS WITH NO ENGINE.** The landing page is what a person sees when
    every engine is busy, still loading, or failed to build -- which is
    exactly when a page served BY an engine could not answer. It reads the
    vault with `os.scandir` and the pool's own state, and nothing else.
  * **IT IS WHERE AN EPISODE IS OPENED**, in the pool's builder thread, so no
    request ever waits on a share. The button posts, the page polls
    `state.json`, and "opening" is a state a person can watch rather than a
    spinner that means nothing.
  * **IT OWNS THE FLAT PWA SURFACES** -- `sw.js`, the manifest and the icon at
    `/cards/...` -- because a phone that installed this app before today is
    pointed at them.

THE SERVICE WORKER AT `/cards/sw.js` WAS A KILL SWITCH from 2026-09-14 to
2026-10-11 (now CARDS_SW below, which keeps its one guarantee). The installed worker's scope is `/cards/`, which covers every new
`/cards/p/<slug>/` URL, and every navigation in scope goes through its own
`shellAnswer`: a phone whose network verdict is "down" would be served the
OLD FLAT PAGE over the new project URL, with the old page's queued edits
behind it. So the path it updates from serves a worker that unregisters
itself and takes its caches with it. The real worker registers per project,
from the page, document-relative (`navigator.serviceWorker.register('sw.js')`
in 15-offline.js), which under the new prefix is already the right scope --
that half needed no change in the other repo.

The routes are registered BEFORE the mount (cards.mount_cards), because
Starlette matches in order and the mount would otherwise swallow them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from . import auth, cards_catalog, cards_pool

log = logging.getLogger("ccsync.dashboard.cards")

router = APIRouter()

# The cookie that remembers the last episode, so the landing page can offer
# "carry on with ..." at the top. IT IS NOT THE ROUTING KEY -- the URL is
# (docs/CARDS_TWO_PROJECTS.md §3). A session-held key would forbid the
# everyday pair this whole feature is for: one account, laptop and phone, two
# different episodes at once.
LAST_COOKIE = "ccsync_cards_last"
LAST_MAX_AGE = 90 * 24 * 3600

# How long the landing page's episode scan is reused. The vault is a network
# share and this page polls itself while an episode opens; re-walking three
# levels of it every two seconds would be the most expensive thing on the
# dashboard.
SCAN_TTL_SECONDS = 30.0

_scan: dict[str, Any] = {"at": 0.0, "vault": "", "rows": []}

# How many of the reader's own most recent episodes the picker lists above
# the folders (2026-09-24).
RECENT_COUNT = 5


def _pool(request: Request) -> Any:
    return getattr(request.app.state, "cards_pool", None)


# Words the phrases below already use for somebody who is not a name. A
# display name spelt like one of them would read as the phrase's own word
# ("you opened it 3 min ago" about somebody else), so it falls back to the
# sign-in name instead (account page 2026-09-25).
_PHRASE_WORDS = frozenset({"you", "somebody", "nobody", "someone"})


def _display_names(request: Request) -> dict[str, str]:
    """account_api's cached display-name map (account page 2026-09-25,
    ACCOUNT_PAGE_FEATURES.md 6.2). {} on any failure: this page must draw
    regardless, and a sign-in name is the D-6 default anyway."""
    try:
        from . import account_api

        return dict(account_api.display_names_for(request.app) or {})
    except Exception:  # noqa: BLE001 - a label must never fail a page
        log.exception("Timeline Cards picker: could not read display names")
        return {}


def _label(names: dict[str, str], username: str) -> str:
    """The display name for the phrases a PERSON reads. The JSON fields
    (`occupants`, `last_in`) stay sign-in names: they are keys."""
    who = str(username or "")
    shown = names.get(who) or names.get(who.strip().lower()) or ""
    if not shown or shown.strip().casefold() in _PHRASE_WORDS:
        return who
    return shown


def _episodes(request: Request) -> list[dict]:
    from . import cards

    vault = cards.vault_root(request.app.state.settings)
    now = time.monotonic()
    if _scan["vault"] == vault and now - _scan["at"] < SCAN_TTL_SECONDS:
        return list(_scan["rows"])
    rows = cards_pool.episodes(vault)
    _scan.update({"at": now, "vault": vault, "rows": rows})
    return list(rows)


def _state(request: Request) -> dict:
    """What the page draws and what `state.json` answers. Never raises."""
    pool = _pool(request)
    open_by_slug = {}
    if pool is not None:
        open_by_slug = {e.slug: e.as_dict() for e in pool.entries()}
    rows = []
    for row in _episodes(request):
        entry = open_by_slug.pop(row["slug"], None)
        rows.append({**row, "state": (entry or {}).get("state", ""),
                     "detail": (entry or {}).get("detail", ""),
                     "occupants": (entry or {}).get("occupants", []),
                     # security-1 (2026-09-18b mediums): the vault row wins
                     # for name/show, so these two have to be carried across
                     # explicitly or the page would never see them.
                     "last_in": (entry or {}).get("last_in", ""),
                     "last_in_seconds": (entry or {}).get("last_in_seconds"),
                     "opening_seconds": (entry or {}).get("opening_seconds"),
                     "href": f"/cards/p/{row['slug']}/"})
    # An episode that is open but no longer under the vault scan (a share
    # that went away, a folder renamed) is still listed: it holds a seat, and
    # an admin cannot close what the page will not show.
    for entry in open_by_slug.values():
        rows.append({**entry, "href": f"/cards/p/{entry['slug']}/"})
    live = [r for r in rows if r.get("state") in
            (cards_pool.LOADING, cards_pool.READY)]
    # security-2 / dash-cards-2 (2026-09-18): whether THIS reader may close
    # each episode, so the template can draw the button rather than guessing
    # from `session_is_admin` alone. A `failed` entry is closable by anybody
    # (it has no occupant and no engine): that is the admin door dash-cards-2
    # asks for, widened to everyone because there is nothing to take away.
    me = auth.get_session_user(request) or ""
    admin = auth.is_admin(request.app.state.settings, me)
    names = _display_names(request)
    _catalogue(request, rows, me, names)
    for row in rows:
        # account page 2026-09-25: "in it now" by display name; the sign-in
        # names stay in `occupants` (and in the row's title) as the keys.
        row["occupants_shown"] = [_label(names, o)
                                  for o in (row.get("occupants") or [])]
        # security-1 (2026-09-18b mediums): the presser is TOLD who was last
        # in and when. The idle release measures served requests, so an editor
        # working offline in Cards looks like nobody at all after fifteen
        # minutes; naming the last occupant is the fact that turns a blind
        # press into a judgement. "" when nobody has ever been in it.
        row["last_in_phrase"] = _last_in_phrase(
            _label(names, row.get("last_in") or ""), row.get("last_in_seconds"))
        row["opening_phrase"] = _opening_phrase(row.get("state") or "",
                                                row.get("opening_seconds"))
        # logic-cards-1 (2026-09-25): the CONFIRM names the person the press
        # takes the episode from, never the presser. `last_in` is whoever sent
        # the newest request, which is usually the person about to press, so
        # the confirm read "ruskin is in it now" to ruskin while alex was
        # editing in it.
        other = pool.get(row.get("slug", "")) if pool is not None else None
        other_phrase = ""
        if other is not None:
            other_who, other_ago = other.last_in_other_than(me)
            other_phrase = _last_in_phrase(_label(names, other_who), other_ago)
        row["close_prompt"] = _close_prompt(row.get("name") or "this episode",
                                            other_phrase)
        row["may_close"] = bool(
            pool is not None
            and row.get("state") in (cards_pool.LOADING, cards_pool.READY,
                                     cards_pool.FAILED)
            and not pool.may_close(row.get("slug", ""), me, admin))
    return {
        "episodes": rows,
        "cap": getattr(pool, "cap", cards_pool.DEFAULT_CAP),
        "open": len(live),
        "ready": [r["slug"] for r in rows if r.get("state") == cards_pool.READY],
        "me": auth.get_session_user(request) or "",
    }


def _catalogue(request: Request, rows: list[dict], me: str,
               names: dict[str, str] | None = None) -> None:
    """Add what the picker sorts, filters and folds on. Never raises.

    2026-09-24 (cards_catalog's docstring): the folder path under the vault
    (less the levels every episode shares), the year, when THIS person and
    when anybody last opened it, its size once the walker has one, and its
    newest modification. A failure here leaves the rows as they were, and
    the page still draws: every field below has a blank the template reads.
    """
    from . import cards

    try:
        settings = request.app.state.settings
        vault = cards.vault_root(settings)
        anyone, mine = cards_catalog.opened(settings, me)
        sizes = cards_catalog.sizes(settings, [r for r in rows if r.get("root")])
        paths = [cards_catalog.folder_parts(vault, r.get("root") or "")
                 for r in rows]
        # An open entry whose root has left the scan has no parts; it must
        # not make every other episode keep the shared levels (Fable review,
        # 2026-09-25).
        cut = cards_catalog.strip_common([p for p in paths if p])
        now = time.time()
        me_key = (me or "").strip().lower()
    except Exception:  # noqa: BLE001 - the picker must draw regardless
        log.exception("Timeline Cards picker: could not read its catalogue")
        return
    for row, full in zip(rows, paths):
        # Per row, so one row's bad value (a far-future mtime from a camera
        # with an unset clock) cannot strip the catalogue from every row
        # after it (Fable review, 2026-09-25).
        try:
            _catalogue_row(row, full, cut, sizes, anyone, mine, now, me_key,
                           names or {})
        except Exception:  # noqa: BLE001
            log.exception("Timeline Cards picker: could not describe %s",
                          row.get("slug", "?"))


def _catalogue_row(row: dict, full: list[str], cut: int, sizes: dict,
                   anyone: dict, mine: dict, now: float, me_key: str,
                   names: dict[str, str] | None = None) -> None:
    slug = row.get("slug", "")
    parts = full[cut:]
    size = sizes.get(slug) or {}
    modified = size.get("newest") or row.get("mtime")
    last = anyone.get(slug) or {}
    by = str(last.get("by") or "")
    row["parts"] = parts
    row["path_label"] = " / ".join(parts)
    # The year from the UNSTRIPPED path: on the live vault every
    # episode is under one year folder, which is exactly the level
    # strip_common removes (Fable review, 2026-09-25).
    row["year"] = cards_catalog.year_of(full, modified)
    row["opened_mine"] = mine.get(slug)
    row["opened_any"] = last.get("at")
    # The sign-in name behind "who opened it", for the row's title (account
    # page 2026-09-25): the phrase carries the display name.
    row["opened_by"] = "" if row["opened_mine"] else by
    if row["opened_mine"]:
        row["opened_phrase"] = ("you opened it "
                                + cards_catalog.ago_phrase(now - row["opened_mine"]))
    elif row["opened_any"]:
        who = "you" if by == me_key else (_label(names or {}, by) or "somebody")
        row["opened_phrase"] = (f"{who} opened it "
                                + cards_catalog.ago_phrase(now - row["opened_any"]))
    else:
        row["opened_phrase"] = "never opened"
    row["bytes"] = size.get("bytes") if "bytes" in size else None
    row["size_label"] = (cards_catalog.human_bytes(row["bytes"])
                         if row["bytes"] is not None else "")
    row["size_partial"] = bool(size.get("partial"))
    row["modified"] = modified
    row["modified_label"] = cards_catalog.date_label(modified)


def _close_prompt(name: str, last_in_phrase: str) -> str:
    """What the [ CLOSE ] confirm asks. security-1 (2026-09-18b mediums).

    Closing is not free (`EnginePool.drop`) and, since the seat is stamped by
    served requests only, the presser may be taking the episode from somebody
    who is working offline in it. So the question names them and says what
    happens to work a disconnected browser is still holding.
    """
    who = f" {last_in_phrase}." if last_in_phrase else ""
    return (f"Close {name}?{who} Anything an offline browser has not sent yet "
            "stays in that browser until it reconnects.")


def _opening_phrase(state: str, seconds: float | None) -> str:
    """"opening for 4 min", or "" under a minute or when not opening.

    logic-cards-7 (2026-09-25): an episode stuck on a hung share read
    "OPENING" all afternoon with nothing to tell it from a slow one. The
    pool gives up at BUILD_DEADLINE_SECONDS; until then the row says how long.
    """
    if state != cards_pool.LOADING or seconds is None or seconds < 60:
        return ""
    return (f"opening for {int(seconds // 60)} min; it gives up at "
            f"{int(cards_pool.BUILD_DEADLINE_SECONDS // 60)} min")


def _last_in_phrase(who: str, ago: float | None) -> str:
    """"ruskin was last in 22 min ago", or "" when nobody ever was.

    security-1 (2026-09-18b mediums). Minutes, never seconds: the number is
    read to decide whether somebody is still working, and a second-level
    number invites a race nobody can win.
    """
    if not who or ago is None:
        return ""
    if ago < 60:
        return f"{who} is in it now"
    return f"{who} was last in {int(ago // 60)} min ago"


@router.get("/cards", include_in_schema=False)
def cards_bare(request: Request) -> Response:
    """`/cards` -> `/cards/`. The page's own URLs are document-relative."""
    return RedirectResponse("/cards/", status_code=303)


@router.get("/cards/", include_in_schema=False)
def cards_landing(request: Request) -> Response:
    from . import ui

    state = _state(request)
    last = request.cookies.get(LAST_COOKIE, "")
    want = str(request.query_params.get("want") or "")
    refusal = str(request.query_params.get("refused") or "")
    by_slug = {row["slug"]: row for row in state["episodes"]}
    episodes = state["episodes"]
    recent = sorted((r for r in episodes if r.get("opened_mine")),
                    key=lambda r: r["opened_mine"], reverse=True)[:RECENT_COUNT]
    years = sorted({r.get("year") for r in episodes if r.get("year")},
                   reverse=True)
    return ui._render(request, "cards_landing.html", {
        "nav_current": "cards",
        "episodes": episodes,
        "tree": cards_catalog.build_tree(episodes),
        "recent": recent,
        "years": years,
        "cap": state["cap"],
        "open_count": state["open"],
        "carry_on": by_slug.get(last) if last in by_slug else None,
        "want": by_slug.get(want) if want in by_slug else None,
        "refusal": refusal,
    })


@router.get("/cards/state.json", include_in_schema=False)
def cards_state(request: Request) -> Any:
    """What the page polls while an episode opens."""
    return JSONResponse(_state(request))


@router.post("/cards/open", include_in_schema=False)
async def cards_open(request: Request) -> Response:
    """Open an episode, or say why not. Always a redirect: this is a form.

    The CSRF posture is the mount's own (`_CSRF_ORIGIN_ONLY_PREFIXES` covers
    `/cards/`): a browser attaches `Origin` to every cross-site POST, and
    this route changes nothing a forged one could not change by clicking the
    button in an honest tab.
    """
    form = await request.form()
    slug = str(form.get("slug") or "")
    pool = _pool(request)
    if pool is None:
        return RedirectResponse("/cards/?refused=Timeline+Cards+is+not+mounted",
                                status_code=303)
    # bug-dash-cards-jobs-6 (2026-09-25): this route is `async` (it awaits the
    # form), and once the 30 s scan cache has lapsed `_episodes` walks four
    # levels of the vault share. On the event loop that stalled the whole
    # single-worker dashboard - fleet reports, every page - for as long as
    # the share took, and for ever on a share that hangs. The GET routes are
    # plain `def` and already ran in the threadpool; this one did not.
    rows = await asyncio.to_thread(_episodes, request)
    row = next((r for r in rows if r["slug"] == slug), None)
    if row is None:
        return RedirectResponse("/cards/?refused=that+episode+is+not+in+the+vault",
                                status_code=303)
    entry, refusal = pool.open(row["root"], name=row["name"], show=row["show"])
    if entry is None:
        from urllib.parse import quote

        return RedirectResponse(f"/cards/?refused={quote(refusal)}",
                                status_code=303)
    pool.note_visit(entry.slug, auth.get_session_user(request) or "")
    # Off the event loop: a file write, and a stalled data dataset must not
    # stall every request (Fable review, 2026-09-25).
    await asyncio.to_thread(cards_catalog.note_opened,
                            request.app.state.settings, entry.slug,
                            auth.get_session_user(request) or "")
    response = RedirectResponse(f"/cards/?want={entry.slug}", status_code=303)
    # security-3 (2026-09-18): ONE helper decides `secure` for every cookie
    # this server sets. `request.url.scheme` is `http` behind a TLS terminator
    # (Tailscale Serve, the funnel port), so on a site that sets
    # DASH_COOKIE_SECURE=1 the session cookie carried Secure and this one did
    # not. The payload here is only a slug, but the rule is what stops the next
    # cookie from being a credential.
    remember(response, entry.slug,
             auth.cookie_secure(request.app.state.settings, request))
    return response


@router.post("/cards/close", include_in_schema=False)
async def cards_close(request: Request) -> Response:
    """Close an episode, which frees a seat.

    NOT EVICTION AND NOT FREE: `EnginePool.drop` says what it does and does
    not do, and what it does not do is stop the other repo's three `while
    True` threads. Taking an episode away from whoever is IN it is still the
    act that must not happen by accident, which is why an admin is still the
    only person who can do that.

    security-2 (2026-09-18): but this used to be admin-only FULL STOP, with no
    self-close and no idle release, while opening was available to every
    session. Two mistaken opens by one non-admin therefore parked the whole
    feature - on the surface a phone stages a cut on - until an admin was found
    or the container restarted, and the cap's refusal told the blocked editor
    to "leave it", which frees nothing. `pool.may_close` is the rule: your own
    episode, or one nobody has been in for 15 minutes, or you are an admin.
    """
    from urllib.parse import quote

    settings = request.app.state.settings
    user = auth.get_session_user(request)
    form = await request.form()
    slug = str(form.get("slug") or "")
    pool = _pool(request)
    if pool is None:
        return RedirectResponse("/cards/", status_code=303)
    refusal = pool.may_close(slug, user or "", auth.is_admin(settings, user))
    if refusal:
        return RedirectResponse(f"/cards/?refused={quote(refusal)}",
                                status_code=303)
    log.info("Timeline Cards: %s closed %s", user, slug)
    # bug-dash-cards-jobs-6 (2026-09-25): `drop` calls the engine's `stop()`
    # (the other repo's code, which may join a worker) and shuts down the
    # episode's WSGI executor. Neither belongs on the event loop.
    await asyncio.to_thread(pool.drop, slug)
    return RedirectResponse("/cards/", status_code=303)


# ------------------------------------------------------ the flat PWA surfaces

# THE WORKER AT `/cards/sw.js` IS THE APP'S FRONT DOOR OFFLINE (2026-10-11,
# Alex, boarding a plane: "Mobile timeline cards is stuck on this icon
# loading. And I need it to work fully offline" / "the whole thing works end
# to end launched from zero on an aeroplane, as long as you've opened it once
# before getting on" / "you should be able to launch any project file which
# has been downloaded").
#
# Until today this path served a KILL SWITCH (no fetch handler, unregister on
# activate). That was right while `/cards/` was a page nobody launched into,
# but 0.7.73 made `/cards/` the installed app's start_url, and nothing then
# answered it without the server: the dashboard's own worker passes `/cards/`
# through (static/sw.js PASS_THROUGH) and each episode's worker is scoped to
# `/cards/p/<slug>/`. So a phone on a plane, or on a tailnet whose server is a
# black hole, sat on the splash for as long as the connect took.
#
# What the kill switch was FOR still holds: the old flat page's worker shared
# this script URL and this scope, so these bytes replace that worker, and
# nothing here ever serves the old flat page. It answers three things only:
#
#   * `/cards/` itself: the network against an 8 s deadline (twice the episode
#     worker's SHELL_MS: the vault scan behind this page is slower), and the last list it saw when the
#     server does not answer. The saved copy is served with a `cards-offline`
#     meta, which static/cards_offline.js reads to turn the page into the
#     offline picker. A sign-out (the gate's redirect) deletes the saved copy:
#     this page names who opened what, and a signed-out phone should not keep
#     it.
#   * the page's own assets (/static/, the icon, the manifest): cache first,
#     refreshed behind. They are content-hashed (asset_url), so a hit is
#     never stale; the cache is NOT rotated by version, because a saved page
#     names the hashes it was drawn with and must still find them offline.
#   * a navigation to `/cards/p/<slug>/` that reaches THIS worker, which only
#     happens when that episode has no worker of its own on this phone (a
#     longer scope always wins): the network, and the offline list instead of
#     a hang when there is none.
#
# Everything else, `state.json` and every API route included, is untouched.
# Media and each episode's shell are the episode worker's (the Cards repo's
# page/sw.js); this worker deletes nothing but its own saved page.
CARDS_SW = r"""// CC Sync dashboard: the Timeline Cards app's front door, offline.
// cards_landing.py CARDS_SW has the reasoning. version: %VER%
const LANDING = 'cards-landing';
const PAGE = '/cards/';
const NAV_MS = 8000;

self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

function raced(p, ms) {
  return new Promise((res, rej) => {
    const t = setTimeout(() => rej(new Error('no answer in ' + ms + ' ms')), ms);
    p.then(v => { clearTimeout(t); res(v); }, err => { clearTimeout(t); rej(err); });
  });
}

function pageKey() { return new Request(new URL(PAGE, self.location.origin).href); }

async function savePage(r) {
  if (!r || !r.ok || r.type !== 'basic' || r.redirected) return;
  if ((r.headers.get('Content-Type') || '').indexOf('text/html') < 0) return;
  const body = await r.blob();
  const cache = await caches.open(LANDING);
  await cache.put(pageKey(), new Response(body, {headers: {
    'Content-Type': 'text/html; charset=utf-8',
    'X-Cards-Saved-At': String(Date.now())}}));
}

async function forgetPage() {
  try { const c = await caches.open(LANDING); await c.delete(pageKey()); } catch (err) {}
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
}

// The episodes whose page this phone can open with no network: every
// episode worker files its shell under its own `/cards/p/<slug>/`.
async function savedEpisodes() {
  const out = [];
  for (const name of await caches.keys()) {
    if (name.indexOf('cards-shell-') !== 0) continue;
    const c = await caches.open(name);
    for (const req of await c.keys()) {
      const m = /\/cards\/p\/([^/]+)\/$/.exec(new URL(req.url).pathname);
      if (m && out.indexOf(m[1]) < 0) out.push(m[1]);
    }
  }
  return out;
}

async function offlinePage() {
  const cache = await caches.open(LANDING);
  const hit = await cache.match(pageKey());
  if (hit) {
    const at = hit.headers.get('X-Cards-Saved-At') || '0';
    const text = (await hit.text()).replace(/<head[^>]*>/i,
      m => m + '<meta name="cards-offline" content="' + esc(at) + '">');
    return new Response(text, {headers: {'Content-Type': 'text/html; charset=utf-8'}});
  }
  // never saved: still better than a splash screen
  const slugs = await savedEpisodes();
  const links = slugs.map(s => '<li><a style="color:#8ab4ff" href="/cards/p/' +
    encodeURIComponent(s) + '/">' +
    esc(s.replace(/-[0-9a-f]{8}$/, '').replace(/-/g, ' ')) + '</a></li>').join('');
  return new Response('<!doctype html><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<title>Timeline Cards: offline</title>' +
    '<body style="background:#15171c;color:#dde;font:16px system-ui;padding:24px">' +
    '<h1 style="font-size:20px">The server cannot be reached</h1>' +
    '<p>The episode list has not been saved on this phone yet. Open the app ' +
    'once with a connection and it will be.</p>' +
    (links ? '<p>Episodes this phone can open offline:</p><ul>' + links + '</ul>' : '') +
    '<p><a style="color:#8ab4ff" href="/cards/">Try again</a></p>',
    {headers: {'Content-Type': 'text/html; charset=utf-8'}});
}

async function navAnswer(e, url) {
  const isPage = url.pathname === PAGE;
  if (navigator.onLine === false) return offlinePage();
  let r;
  try {
    r = await raced(fetch(e.request), NAV_MS);
  } catch (err) {
    return offlinePage();
  }
  // a dark TrueNAS app behind Tailscale Serve answers 502, not a timeout
  if (r.status >= 500) return offlinePage();
  if (isPage) {
    if (r.type === 'opaqueredirect' || (r.redirected && /\/login/.test(r.url))) {
      e.waitUntil(forgetPage());
    } else if (!url.searchParams.has('want') && !url.searchParams.has('refused')) {
      e.waitUntil(savePage(r.clone()).catch(() => null));
    }
  }
  return r;
}

async function assetAnswer(e) {
  const req = e.request;
  const hit = await caches.match(req);
  const live = fetch(req).then(async r => {
    if (r && r.ok && r.type === 'basic') {
      const c = await caches.open(LANDING);
      await c.put(req, r.clone());
    }
    return r;
  });
  if (hit) {
    e.waitUntil(live.catch(() => null));
    return hit;
  }
  try {
    return await live;
  } catch (err) {
    const loose = await caches.match(req, {ignoreSearch: true});
    if (loose) return loose;
    throw err;
  }
}

function isAsset(url) {
  return url.pathname.indexOf('/static/') === 0 || url.pathname === '/favicon.ico' ||
    url.pathname === '/cards/icon.svg' || url.pathname === '/cards/manifest.webmanifest';
}

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  let url;
  try { url = new URL(req.url); } catch (err) { return; }
  if (url.origin !== self.location.origin) return;
  if (req.mode === 'navigate') {
    if (url.pathname === PAGE || url.pathname.indexOf('/cards/p/') === 0) {
      e.respondWith(navAnswer(e, url));
    }
    return;
  }
  if (isAsset(url)) e.respondWith(assetAnswer(e));
});

// The first visit is drawn BEFORE this worker controls the page, so neither
// the page nor its assets came through here: static/cards_offline.js hands
// over what it loaded, and this saves it, so the very next launch can be
// offline.
self.addEventListener('message', e => {
  const msg = e.data || {};
  if (msg.type !== 'cards-landing-save') return;
  e.waitUntil((async () => {
    const cache = await caches.open(LANDING);
    if (msg.page) {
      try { await savePage(await fetch(PAGE, {credentials: 'same-origin'})); } catch (err) {}
    }
    for (const u of (msg.assets || [])) {
      try {
        const url = new URL(u, self.location.origin);
        if (url.origin !== self.location.origin || !isAsset(url)) continue;
        if (await cache.match(url.href)) continue;
        const r = await fetch(url.href, {credentials: 'same-origin'});
        if (r.ok && r.type === 'basic') await cache.put(url.href, r);
      } catch (err) {}
    }
    if (e.source) e.source.postMessage({type: 'cards-landing-saved'});
  })());
});
"""


@router.get("/cards/sw.js", include_in_schema=False)
def cards_sw(request: Request) -> Response:
    # The version in the bytes, so every release re-installs the worker.
    from . import VERSION

    return Response(CARDS_SW.replace("%VER%", VERSION),
                    media_type="text/javascript; charset=utf-8",
                    headers={"cache-control": "no-cache"})


# The installed phone app is ONE app whose front door is this landing page
# (Alex, 2026-10-06: "the mobile app should default to taking you first to the
# cards page of the dash so you can choose which to open. Right now on mobile
# once you're in a cut file there's no way to back out"). Until today each
# episode page's manifest came from its engine, relative: `start_url` and
# `scope` "." resolved to `/cards/p/<slug>/`, so an app installed from a cut
# file opened on that cut file for ever, and `/cards/` was OUTSIDE its scope.
#
# THE ID IS "/cards/" AND NOT THE ENGINE'S ".", deliberately. A manifest `id`
# is resolved against the ORIGIN of start_url, not against the manifest or
# the page (W3C appmanifest, "processing the id member"; Chrome does the
# same), so the engine's "." has always meant `https://<dash>/` -- the very id
# the dashboard's own manifest claims (static/manifest.webmanifest, "id": "/").
# Keeping it would make the landing page, which links the DASHBOARD's
# manifest through shell.html, a valid update source for the Cards app: the
# first update check after start_url moved here would turn the installed
# Cards icon into a "CC Sync" app opening on `/`. "/cards/" is the id this
# route has carried since 2026-09-14 (linked by nothing until today). Every
# Cards app installed before today carries the engine's id, so a phone
# installs it once more (docs/CARDS_TWO_PROJECTS.md section 13).
APP_ID = "/cards/"
APP_START = "/cards/"
APP_SCOPE = "/cards/"


def app_manifest() -> dict:
    """The Cards app's manifest, served at `/cards/` AND under every episode.

    The checkout's `render_manifest()` is the source of what the app LOOKS
    like (fullscreen, portrait, its colours, its name), so the phone app is
    the one the Cards repo designed; this only moves its identity, front door
    and scope onto the dashboard's layout. Imported lazily and by name, like
    the icon: this answers before any engine exists, and a checkout that
    cannot be imported must still leave the app installable.
    """
    data: dict = {
        "name": "Timeline Cards", "short_name": "Cards",
        "description": "Which episode, and which cut list.",
        "display": "standalone",
        "background_color": "#0b0b0b", "theme_color": "#0b0b0b",
    }
    try:
        from multicam_pipeline.cards import page as cards_page

        theirs = json.loads(cards_page.render_manifest())
        if isinstance(theirs, dict):
            data.update(theirs)
    except Exception:  # noqa: BLE001 - the fallback is the point
        pass
    data.update({
        "id": APP_ID, "start_url": APP_START, "scope": APP_SCOPE,
        # Absolute, and the landing's own route: a relative `icon.svg` under
        # an episode prefix would resolve to the ENGINE's icon, which answers
        # only while that episode is open.
        "icons": [{"src": "/cards/icon.svg", "sizes": "any",
                   "type": "image/svg+xml", "purpose": "any"},
                  {"src": "/cards/icon.svg", "sizes": "any",
                   "type": "image/svg+xml", "purpose": "maskable"}],
    })
    return data


def _manifest_response() -> Response:
    return Response(json.dumps(app_manifest(), ensure_ascii=False),
                    media_type="application/manifest+json; charset=utf-8",
                    headers={"cache-control": "no-cache"})


@router.get("/cards/manifest.webmanifest", include_in_schema=False)
def cards_manifest(request: Request) -> Response:
    """The app's manifest, as linked by the landing page itself.

    Fetched without the session cookie (which is why app.py keeps this path
    open, CR-100), and it names nothing a login page would not.
    """
    return _manifest_response()


@router.get("/cards/p/{slug}/manifest.webmanifest", include_in_schema=False)
def cards_episode_manifest(slug: str) -> Response:
    """The SAME manifest under an episode's prefix (2026-10-06).

    The page links `manifest.webmanifest` document-relative, which lands
    here, ahead of the mount, instead of on the engine: an episode page
    installs the one Cards app, opening on the landing page with every
    episode inside its scope. Served whether or not the episode is open --
    it names no episode. Open to the login gate through app._OPEN_PATTERN,
    GET only, exactly as the engine's copy was.
    """
    if not cards_pool.is_slug(slug):
        return JSONResponse({"error": "not found"}, status_code=404)
    return _manifest_response()


_ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
         '<rect width="64" height="64" rx="10" fill="#0b0b0b"/>'
         '<rect x="10" y="16" width="20" height="32" rx="3" fill="#e5484d"/>'
         '<rect x="34" y="16" width="20" height="32" rx="3" fill="#f2f2f2"/>'
         '</svg>')


@router.get("/cards/icon.svg", include_in_schema=False)
def cards_icon(request: Request) -> Response:
    """The installed app's icon. The checkout's own if it has one.

    Imported lazily and by name: this route answers before any engine exists,
    and a checkout that cannot be imported must still leave the landing page
    installable rather than 500 on its icon.
    """
    svg = _ICON
    try:
        from multicam_pipeline.cards import page as cards_page

        svg = getattr(cards_page, "ICON_SVG", "") or _ICON
    except Exception:  # noqa: BLE001 - the fallback is the point
        pass
    return Response(svg, media_type="image/svg+xml; charset=utf-8")


def remember(response: Response, slug: str, secure: bool) -> None:
    """Set the carry-on cookie. Used by the dispatcher's visit recording."""
    response.set_cookie(LAST_COOKIE, slug, max_age=LAST_MAX_AGE,
                        httponly=True, samesite="lax", secure=secure)


__all__ = ["router", "remember", "LAST_COOKIE", "CARDS_SW"]
