"""Fallback for opening judge.html: a stdlib-only local HTTP server, for the
one browser/OS combination where file:// doesn't cut it.

Chrome and Edge were verified (2026-08-18, via Playwright, see judge/README.md)
to load judge.html's frame thumbnails fine straight off disk with
file:///...judge.html — relative <img src> paths into ../bundle/ work under
file:// in both. Firefox restricts file:// XHR/fetch more aggressively and
image loading from a sibling directory has been unreliable there historically;
if a judge is on Firefox, or a corporate policy disables file:// entirely,
run this instead of double-clicking judge.html.

Binds 127.0.0.1 only (never 0.0.0.0) — this is local judging data, not
something to expose on the LAN. Serves the WHOLE local_vlm/ directory (not
just judge/) because judge.html's image paths are ../bundle/... — a server
rooted at judge/ would have to break out of its own root to reach them, which
http.server correctly refuses to do.

usage: python serve.py [--port 8000]
"""
from __future__ import annotations

import argparse
import functools
import http.server
import webbrowser
from pathlib import Path

LOCAL_VLM_DIR = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true", help="don't auto-open a tab")
    args = ap.parse_args()

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(LOCAL_VLM_DIR))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    url = f"http://127.0.0.1:{args.port}/judge/judge.html"
    print(f"serving {LOCAL_VLM_DIR} at {url} (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
