"""The public door: /share/{token}/... -- a client folder as its licensee sees it.

docs/CLIENT_FOLDERS.md, 2026-08-18. Everything under here is answered on the
strength of the token alone, to anyone, read-only:

    GET /share/{token}                    -> 303 to the trailing-slash form
    GET /share/{token}/                   -> the viewer page (share.html)
    GET /share/{token}/api/folder         -> title, description, contact, clips
    GET /share/{token}/api/videos/{id}    -> one clip's segments and metadata
    GET /share/{token}/media/proxy/{id}.mp4     (Range-capable, the 540p preview)
    GET /share/{token}/media/sprite/{id}.jpg
    GET /share/{token}/media/poster/{id}.jpg
    GET /share/assets/...                 -> the static tree (main.py mounts it)

WHY THE TRAILING SLASH IS LOAD-BEARING. The viewer page is plain static HTML
whose every URL is document-relative (`../assets/share.js`, `api/folder`,
`media/poster/12.jpg`) -- the same rule the b-roll SPA lives by so it works at
`/` and at `/broll/` alike (tests/test_mounted_prefix.py). Served at
`.../share/<token>/`, those resolve inside the token's own space; served at
`.../share/<token>` they would resolve one level up and every request would
carry the wrong path. It also means the ONE path prefix an operator has to
publish is `/broll/share` -- nothing on the page reaches for `/broll/static`
or `/broll/api`, so a Tailscale Funnel scoped to that prefix carries the whole
experience and nothing else of the dashboard.

WHAT NEVER LEAVES. `client_folders.PUBLIC_VIDEO_COLUMNS` is the allow-list of
`videos` columns; there is no `SELECT *` on this side of the app. No path, no
share name, no archive layout, no transcript (spoken words are indexed for
editors' search, not for a licensee's preview), no other folder's existence.
A dead link (revoked, expired, never existed, malformed) is one and the same
404 in every route -- a token that "exists but is revoked" is still a token
the caller was not given.

Media membership is checked PER REQUEST, not per page: a link that is revoked
while a client has the page open stops serving the next thumbnail, not the
next visit. `_live_folder` is the one dependency every route hangs off, so a
route added later cannot forget the check.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.responses import FileResponse, RedirectResponse, Response

from app import client_folders as cf
from app import config
from app.db import get_db
from app.media import serve_file_with_range
from app.routes_media import _proxy_path

router = APIRouter(prefix="/share")

# The client is not our fleet: nothing they fetch should be indexed by a
# search engine that finds the link in a forwarded email, and nothing they
# fetch should announce the NAS's URL to a third party in a Referer.
_PUBLIC_HEADERS = {
    "X-Robots-Tag": "noindex, nofollow, noarchive",
    "Referrer-Policy": "no-referrer",
}


def _with_public_headers(response: Response, cache: str) -> Response:
    for k, v in _PUBLIC_HEADERS.items():
        response.headers[k] = v
    response.headers["Cache-Control"] = cache
    return response


def _gone() -> HTTPException:
    return HTTPException(404, "This link is not available")


def _live_folder(token: str,
                 conn: sqlite3.Connection = Depends(cf.get_shares_db)) -> sqlite3.Row:
    """The folder behind `token`, if the link is good RIGHT NOW. 404 otherwise.

    Malformed tokens never reach the database (client_folders.valid_token), so
    `assets` -- the static mount that shares this prefix -- and any other
    path-shaped junk fall out here rather than being looked up.
    """
    folder = cf.get_folder_by_token(conn, token)
    if folder is None or not cf.is_live(folder):
        raise _gone()
    return folder


def _member_id(conn: sqlite3.Connection, index: sqlite3.Connection,
               folder: sqlite3.Row, video_id: int) -> int:
    """`video_id` if this folder may show it, else 404.

    The direct membership row is the common case and one indexed lookup. The
    fallback re-resolves the folder by (share, rel_path) for an archive that
    was rebuilt with new ids after the folder was made -- the same rule
    resolve_items applies when it draws the page, so a thumbnail the page
    shows is a thumbnail this will serve.
    """
    if cf.member_video_id(conn, folder["id"], video_id):
        return video_id
    if video_id in cf.public_video_ids(conn, index, folder["id"]):
        return video_id
    raise _gone()


def _gone_page() -> Response:
    """The two PAGE routes answer a dead link with a page a person can read,
    not the JSON `detail` every API route (rightly) gives a script. Same 404,
    same headers; only the body knows it is talking to a human."""
    return _with_public_headers(
        FileResponse(config.STATIC_DIR / "share_gone.html", media_type="text/html",
                     status_code=404),
        "private, no-store")


@router.get("/{token}")
def share_root(token: str, conn: sqlite3.Connection = Depends(cf.get_shares_db)) -> Response:
    """Send the browser to the trailing-slash form (see the module docstring).

    A RELATIVE Location on purpose: `<token>/` resolves against whatever URL
    the browser used to get here -- through the dashboard mount, through a
    Funnel on another port, standalone -- without this app having to know
    which. 303 rather than 307 so nothing but a GET is ever replayed.
    """
    folder = cf.get_folder_by_token(conn, token)
    if folder is None or not cf.is_live(folder):
        return _gone_page()
    return _with_public_headers(
        RedirectResponse(url=f"{token}/", status_code=303), "no-store")


@router.get("/{token}/")
def share_page(token: str, conn: sqlite3.Connection = Depends(cf.get_shares_db)) -> Response:
    folder = cf.get_folder_by_token(conn, token)
    if folder is None or not cf.is_live(folder):
        return _gone_page()
    return _with_public_headers(
        FileResponse(config.STATIC_DIR / "share.html", media_type="text/html"),
        "private, no-store")


@router.get("/{token}/api/folder")
def share_folder(token: str, folder: sqlite3.Row = Depends(_live_folder),
                 conn: sqlite3.Connection = Depends(cf.get_shares_db),
                 index: sqlite3.Connection = Depends(get_db)) -> Response:
    """The folder as the viewer draws it. Counts as a view: it is fetched
    once per page load, not per interaction, so view_count means "times the
    page was opened" and nothing finer."""
    items = cf.resolve_items(conn, index, folder["id"], public=True)
    cf.record_view(conn, folder["id"])
    body = {
        "title": folder["title"],
        "description": folder["description"],
        "contact": folder["contact"],
        "org": config.get_org_name(),
        "expires_at": folder["expires_at"],
        "n_items": len(items),
        "items": items,
    }
    return _with_public_headers(JSONResponse(body), "private, no-store")


@router.get("/{token}/api/videos/{video_id}")
def share_video(token: str, video_id: int, folder: sqlite3.Row = Depends(_live_folder),
                conn: sqlite3.Connection = Depends(cf.get_shares_db),
                index: sqlite3.Connection = Depends(get_db)) -> Response:
    """One clip: the public columns, its curator note, and its visual segments
    (what is on screen, when) so the client can read the clip as well as scrub
    it. Transcript, themes and quality flags are editors' tools and stay in."""
    vid = _member_id(conn, index, folder, video_id)
    row = index.execute("SELECT * FROM videos WHERE id = ?", (vid,)).fetchone()
    if row is None:
        raise _gone()
    v = dict(row)
    video = {k: v.get(k) for k in cf.PUBLIC_VIDEO_COLUMNS}
    video["name"] = cf._display_name(v["rel_path"])
    note_row = conn.execute(
        "SELECT note FROM client_folder_items WHERE folder_id = ? AND video_id = ?",
        (folder["id"], vid)).fetchone()
    segments = [
        {"t_start": r["t_start"], "t_end": r["t_end"], "description": r["description"],
         "setting": r["setting"], "motion": r["motion"]}
        for r in index.execute(
            "SELECT t_start, t_end, description, setting, motion FROM segments "
            "WHERE video_id = ? ORDER BY t_start ASC", (vid,))
    ]
    return _with_public_headers(JSONResponse({
        "video": video,
        "note": note_row["note"] if note_row else "",
        "segments": segments,
    }), "private, no-store")


# Media: the same files, the same Range handling, one more gate in front. An
# hour of private cache so a client scrubbing back and forth is not re-pulling
# sprite sheets through the funnel; `private` so nothing between here and the
# browser keeps a copy past that browser.
_MEDIA_CACHE = "private, max-age=3600"


@router.get("/{token}/media/proxy/{video_id}.mp4")
def share_proxy(token: str, video_id: int, request: Request,
                folder: sqlite3.Row = Depends(_live_folder),
                conn: sqlite3.Connection = Depends(cf.get_shares_db),
                index: sqlite3.Connection = Depends(get_db)) -> Response:
    vid = _member_id(conn, index, folder, video_id)
    return _with_public_headers(
        serve_file_with_range(request, _proxy_path(index, vid), "video/mp4"), _MEDIA_CACHE)


@router.get("/{token}/media/sprite/{video_id}.jpg")
def share_sprite(token: str, video_id: int, request: Request,
                 folder: sqlite3.Row = Depends(_live_folder),
                 conn: sqlite3.Connection = Depends(cf.get_shares_db),
                 index: sqlite3.Connection = Depends(get_db)) -> Response:
    vid = _member_id(conn, index, folder, video_id)
    path = config.get_sprites_dir() / f"{vid}.jpg"
    return _with_public_headers(
        serve_file_with_range(request, path, "image/jpeg"), _MEDIA_CACHE)


@router.get("/{token}/media/poster/{video_id}.jpg")
def share_poster(token: str, video_id: int, request: Request,
                 folder: sqlite3.Row = Depends(_live_folder),
                 conn: sqlite3.Connection = Depends(cf.get_shares_db),
                 index: sqlite3.Connection = Depends(get_db)) -> Response:
    vid = _member_id(conn, index, folder, video_id)
    path = config.get_posters_dir() / f"{vid}.jpg"
    return _with_public_headers(
        serve_file_with_range(request, path, "image/jpeg"), _MEDIA_CACHE)
