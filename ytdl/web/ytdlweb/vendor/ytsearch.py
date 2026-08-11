r"""YouTube search + metadata enrichment, vendored from batch_dl.py (2026-08-11).

Everything here is that script's search half with its terminal removed: the
`print()` progress became a callback, argparse and the manifest/download driver
are gone (worker.py owns those now), and `enrich()` additionally captures
`info["thumbnail"]` because the review grid is built out of thumbnails.

What deliberately did NOT change:
  - PERIOD_SP. Passing YouTube's own `sp=` filter through the /results URL makes
    YouTube do the date filtering, which beats fetching everything and
    discarding it.
  - the net_opts: `js_runtimes {deno,node}` + `remote_components ejs:github`.
    YouTube requires solving JS challenges for full-quality formats now, and
    the slim container has neither runtime -- hence the static deno binary the
    deploy ships (DEPLOY.md). Without it high-quality formats simply fail.
  - existing_ids()'s `[id]` filename regex. It is what catches clips that were
    hand-copied or downloaded before the ledger existed, so it is the half of
    the dedupe that does not trust the database.

Cookies come from a FILE (`YTDL_COOKIES_FILE` -> yt-dlp's `cookiefile`), never
`cookiesfrombrowser`: there is no browser and no profile for uid 3000 in the
container.

yt_dlp is imported inside each function -- see vendor/__init__.py.
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote_plus

from ytdlweb import config


def net_opts() -> dict:
    """Extra yt-dlp opts shared by search/metadata/download calls."""
    opts = {
        "js_runtimes": {"deno": {}, "node": {}},
        "remote_components": ["ejs:github"],
        # batch_dl runs these against an anonymous NAS IP; a transient 403 or a
        # throttle must not lose a whole term.
        "retries": 5,
        "extractor_retries": 3,
    }
    if config.COOKIES_FILE:
        opts["cookiefile"] = config.COOKIES_FILE
    return opts


# YouTube search-page "sp" filter values for upload date.
PERIOD_SP = {
    "hour":  "EgIIAQ%3D%3D",
    "today": "EgIIAg%3D%3D",
    "week":  "EgIIAw%3D%3D",
    "month": "EgIIBA%3D%3D",
    "year":  "EgIIBQ%3D%3D",
}

_ID_RE = re.compile(r"\[([A-Za-z0-9_-]{11})\]")


def parse_duration(s: str) -> int:
    """'90' -> 90, '1:30' -> 90, '1:02:03' -> 3723 (seconds)."""
    parts = str(s).split(":")
    if not all(p.strip().isdigit() for p in parts):
        raise ValueError(f"bad duration: {s!r}")
    total = 0
    for p in parts:
        total = total * 60 + int(p)
    return total


def fmt_duration(sec) -> str:
    if not sec:
        return "?"
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def existing_id_locations(outdir) -> dict[str, str]:
    """{video id: the folder it sits in} for everything under outdir.

    The id comes from the `[id]` yt-dlp puts in every filename, so this sees
    files no database knows about -- pre-ledger downloads, and clips an editor
    copied in by hand. That is the point: it is the dedupe half that does not
    trust the ledger.
    """
    found: dict[str, str] = {}
    root = Path(outdir)
    if not root.is_dir():
        return found
    for p in root.rglob("*"):
        if p.is_file():
            m = _ID_RE.search(p.stem)
            if m:
                found.setdefault(m.group(1), p.parent.name)
    return found


def existing_ids(outdir) -> set[str]:
    """Video ids already present anywhere under outdir, from '[id]' in names."""
    return set(existing_id_locations(outdir))


# ---- search ----------------------------------------------------------------

def search(query: str, max_results: int, period: str | None = None) -> list[dict]:
    """Flat-search YouTube, return candidate entries (id/url/title only)."""
    import yt_dlp  # lazy: see vendor/__init__.py

    if period:
        url = (f"https://www.youtube.com/results?search_query={quote_plus(query)}"
               f"&sp={PERIOD_SP[period]}")
    else:
        url = f"ytsearch{max_results}:{query}"

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": max_results,
        **net_opts(),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    entries = [e for e in (info.get("entries") or []) if e and e.get("id")]
    return entries[:max_results]


def enrich(entries: list[dict], jobs: int = 4, progress=None) -> list[dict]:
    """Fetch full metadata for each candidate (dates, real durations, views).

    Unavailable / private / live entries come back with an 'error' field rather
    than raising -- one dead video must not cost the other forty.

    `progress` is called once per completed entry as progress(done, total); it
    replaces batch_dl's carriage-return print, and it is what moves the SPA's
    metadata counter. It is called from a pool thread, so the caller's callback
    has to be safe there (worker.py's just commits one UPDATE).
    """
    import yt_dlp  # lazy: see vendor/__init__.py

    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, **net_opts()}

    def fetch(e):
        url = e.get("url") or f"https://www.youtube.com/watch?v={e['id']}"
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            return {
                "id": info.get("id"),
                "url": info.get("webpage_url") or url,
                "title": info.get("title"),
                "channel": info.get("channel") or info.get("uploader"),
                "duration": info.get("duration"),
                "upload_date": info.get("upload_date"),
                "view_count": info.get("view_count"),
                # The review grid falls back to i.ytimg.com/vi/<id>/mqdefault.jpg
                # when this is missing, so it is a nicety, not a dependency.
                "thumbnail": info.get("thumbnail"),
                "is_live": bool(info.get("is_live")),
                "skip": False,
            }
        except Exception as exc:  # noqa: BLE001
            return {"id": e.get("id"), "url": url,
                    "title": e.get("title"), "error": str(exc)[:200]}

    results = {}
    total = len(entries)
    with ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        futures = {ex.submit(fetch, e): i for i, e in enumerate(entries)}
        done = 0
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()
            done += 1
            if progress:
                progress(done, total)
    return [results[i] for i in sorted(results)]
