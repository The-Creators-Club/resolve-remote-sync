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

THE SERVICE WORKER AT `/cards/sw.js` IS NOW A KILL SWITCH, and that is not
tidiness. The installed worker's scope is `/cards/`, which covers every new
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

import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from . import auth, cards_pool

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


def _pool(request: Request) -> Any:
    return getattr(request.app.state, "cards_pool", None)


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
                     "href": f"/cards/p/{row['slug']}/"})
    # An episode that is open but no longer under the vault scan (a share
    # that went away, a folder renamed) is still listed: it holds a seat, and
    # an admin cannot close what the page will not show.
    for entry in open_by_slug.values():
        rows.append({**entry, "href": f"/cards/p/{entry['slug']}/"})
    live = [r for r in rows if r.get("state") in
            (cards_pool.LOADING, cards_pool.READY)]
    return {
        "episodes": rows,
        "cap": getattr(pool, "cap", cards_pool.DEFAULT_CAP),
        "open": len(live),
        "ready": [r["slug"] for r in rows if r.get("state") == cards_pool.READY],
        "me": auth.get_session_user(request) or "",
    }


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
    return ui._render(request, "cards_landing.html", {
        "nav_current": "cards",
        "episodes": state["episodes"],
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
    row = next((r for r in _episodes(request) if r["slug"] == slug), None)
    if row is None:
        return RedirectResponse("/cards/?refused=that+episode+is+not+in+the+vault",
                                status_code=303)
    entry, refusal = pool.open(row["root"], name=row["name"], show=row["show"])
    if entry is None:
        from urllib.parse import quote

        return RedirectResponse(f"/cards/?refused={quote(refusal)}",
                                status_code=303)
    pool.note_visit(entry.slug, auth.get_session_user(request) or "")
    response = RedirectResponse(f"/cards/?want={entry.slug}", status_code=303)
    response.set_cookie(LAST_COOKIE, entry.slug, max_age=LAST_MAX_AGE,
                        httponly=True, samesite="lax",
                        secure=request.url.scheme == "https")
    return response


@router.post("/cards/close", include_in_schema=False)
async def cards_close(request: Request) -> Response:
    """An admin closes an idle episode, which frees a seat.

    NOT EVICTION AND NOT FREE: `EnginePool.drop` says what it does and does
    not do, and what it does not do is stop the other repo's three `while
    True` threads. Admin only, because taking an episode away from whoever is
    in it is exactly the act that must not happen by accident.
    """
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    if not auth.is_admin(settings, user):
        return RedirectResponse("/cards/?refused=only+an+admin+can+close+an+episode",
                                status_code=303)
    form = await request.form()
    pool = _pool(request)
    if pool is not None:
        log.info("Timeline Cards: %s closed %s", user, form.get("slug"))
        pool.drop(str(form.get("slug") or ""))
    return RedirectResponse("/cards/", status_code=303)


# ------------------------------------------------------ the flat PWA surfaces

KILL_SW = """\
// CC Sync dashboard: the Timeline Cards page moved to /cards/p/<episode>/.
// docs/CARDS_TWO_PROJECTS.md phase 1b. This worker's only job is to stop
// being a worker: its scope is /cards/, so the copy installed before that
// change intercepts every navigation into the new project URLs and, when its
// own network verdict is "down", answers them with the OLD page. The browser
// fetches this path on its periodic update check and on navigation, which is
// what makes a kill switch the one thing that can reach it.
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil((async () => {
  try { for (const k of await caches.keys()) await caches.delete(k); } catch (err) {}
  try { await self.registration.unregister(); } catch (err) {}
  try {
    const all = await self.clients.matchAll({type: 'window'});
    for (const c of all) c.navigate(c.url);
  } catch (err) {}
})()));
// Nothing is intercepted in the meantime: no fetch handler at all means the
// browser goes to the network, which is the behaviour this replaces.
"""


@router.get("/cards/sw.js", include_in_schema=False)
def cards_sw(request: Request) -> Response:
    return Response(KILL_SW, media_type="text/javascript; charset=utf-8",
                    headers={"cache-control": "no-cache"})


@router.get("/cards/manifest.webmanifest", include_in_schema=False)
def cards_manifest(request: Request) -> Response:
    """The LANDING page's manifest, for a phone that installed `/cards/`.

    Fetched without the session cookie (which is why app.py keeps this path
    open, CR-100), and it names nothing a login page would not: an app that
    was installed before the episodes existed opens the landing page and
    chooses one. Each episode's own manifest is served by its engine under
    its own prefix, with `id`/`scope`/`start_url` relative -- so an episode
    installed from the phone is its own app, which is what a person means
    when they install two.
    """
    return Response(json.dumps({
        "name": "Timeline Cards", "short_name": "Cards", "id": "/cards/",
        "description": "Which episode, and which cut list.",
        "start_url": "/cards/", "scope": "/cards/", "display": "standalone",
        "background_color": "#0b0b0b", "theme_color": "#0b0b0b",
        "icons": [{"src": "/cards/icon.svg", "sizes": "any",
                   "type": "image/svg+xml", "purpose": "any maskable"}],
    }), media_type="application/manifest+json; charset=utf-8")


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


__all__ = ["router", "remember", "LAST_COOKIE", "KILL_SW"]
