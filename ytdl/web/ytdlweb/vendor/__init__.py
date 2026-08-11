"""Vendored from the standalone `yt-credit-downloader` utility
(E:\\Projects\\Utilities\\yt-credit-downloader), 2026-08-11.

`downloader.py` is that repo's file kept as close to verbatim as the container
allows -- it is the thing the downstream DaVinci Resolve credits script depends
on, so its metadata behaviour (artist/comment tags, meta_* custom tags AND the
.credits.json sidecar) must not drift. `ytsearch.py` is `batch_dl.py`'s search
half with the argparse/print layer removed, because in here the progress goes
to a database and a poll endpoint instead of a terminal.

The ONE change made to both: `import yt_dlp` happens inside the functions that
need it, never at module scope. A venv without yt-dlp must degrade per-route
(the search job fails with a readable error) rather than break `import
ytdlweb.main` -- an ImportError there is reported by the dashboard mount as
ABSENT, i.e. "the ytdl tree was never shipped", which is the wrong problem.
It also means the test suite needs no yt-dlp at all.
"""
