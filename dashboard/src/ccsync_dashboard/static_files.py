"""The dashboard's /static mount, with explicit caching (UI port R8, phase 0).

Plain StaticFiles sends validators and no Cache-Control, so browsers cache
heuristically for hours, and the service worker's revalidation goes through
that same HTTP cache: a deploy that changes a shared classic script
(htmx_errors.js, pwa.js) was not seen until the heuristic ran out.

  * a `?h=` URL whose hash is the CURRENT content hash of that file:
    immutable for a year (the URL changes when the bytes do);
  * a `?h=` URL with any other hash: no-store. StaticFiles ignores the query,
    so without this a request for `cc/hud.css?h=OLD` during a restart window
    or a rollback would stamp the NEW bytes immutable under the OLD hash;
  * /static/fonts/*: immutable. A changed font is a new file name, which a
    checked-in manifest test enforces;
  * everything else: no-cache (always revalidate; a 304 is cheap).
"""
from __future__ import annotations

from urllib.parse import parse_qs

from fastapi.staticfiles import StaticFiles

from . import ui_variant

IMMUTABLE = "public, max-age=31536000, immutable"


class CachedStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code not in (200, 304):
            return response
        rel = str(path).replace("\\", "/").lstrip("/")
        query = parse_qs((scope.get("query_string") or b"").decode("latin-1"))
        sent = (query.get("h") or [""])[0]
        if rel.startswith("fonts/"):
            value = IMMUTABLE
        elif sent:
            value = IMMUTABLE if sent == ui_variant.asset_hash(rel) else "no-store"
        else:
            value = "no-cache"
        response.headers["Cache-Control"] = value
        return response
