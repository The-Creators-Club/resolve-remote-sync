"""A local dashboard with Timeline Cards mounted on a STUB engine, for run.js.

    python tools/cards_offline/serve.py --worktree <repo> --port 8491 --work <dir> --page-src <.../multicam_pipeline/cards>

The picker (/cards/) is the dashboard's own and is exercised for real. An
episode page is the REAL one: the stub handler serves `page.py` and `page/`
copied from the Timeline Cards checkout (`--page-src`, or $CARDS_PAGE_SRC), so
its own worker and 15-offline.js are the shipped bytes. Only the engine is a
stub (empty state), which is why run.js proves an episode OPENS offline and
nothing about a downloaded cut list's contents.

Writes <work>/cookie.txt and cookie_name.txt: a hand-minted session, the way
the dashboard's own tests sign in (DASH_DEV_INSECURE).
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import textwrap
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--worktree", default=str(Path(__file__).resolve().parents[2]))
ap.add_argument("--port", type=int, default=8491)
ap.add_argument("--work", required=True)
ap.add_argument("--page-src", default=os.environ.get("CARDS_PAGE_SRC", ""))
a = ap.parse_args()
WORK = Path(a.work)
WORK.mkdir(parents=True, exist_ok=True)
os.environ["DASH_DEV_INSECURE"] = "1"
os.environ.pop("CARDS_SRC", None)
sys.path.insert(0, str(Path(a.worktree) / "dashboard" / "src"))

REAL = Path(a.page_src)
if not (REAL / "page.py").is_file():
    sys.exit("--page-src (or $CARDS_PAGE_SRC) must be the Timeline Cards "
             "multicam_pipeline/cards directory (it holds page.py and page/)")
src = WORK / "checkout"
pkg = src / "multicam_pipeline" / "cards"
if src.exists():
    shutil.rmtree(src)
pkg.mkdir(parents=True)
(src / "multicam_pipeline" / "__init__.py").write_text("")
(pkg / "__init__.py").write_text("")
shutil.copy(REAL / "page.py", pkg / "page.py")
shutil.copytree(REAL / "page", pkg / "page")
(pkg / "handler.py").write_text(textwrap.dedent('''
    from http.server import BaseHTTPRequestHandler
    from urllib.parse import urlparse
    import json
    from multicam_pipeline.cards.page import (ICON_SVG, render_manifest,
                                              render_page, render_sw)

    def make_handler(engine):
        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
                d = body if isinstance(body, bytes) else body.encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(d)))
                self.end_headers()
                self.wfile.write(d)

            def do_GET(self):
                u = urlparse(self.path)
                if u.path == "/manifest.webmanifest":
                    self._send(200, render_manifest(), "application/manifest+json")
                elif u.path == "/icon.svg":
                    self._send(200, ICON_SVG, "image/svg+xml")
                elif u.path in ("/", "/index.html"):
                    self._send(200, render_page(""), "text/html; charset=utf-8")
                elif u.path == "/sw.js":
                    self._send(200, render_sw(), "text/javascript; charset=utf-8",
                               {"Cache-Control": "no-store"})
                elif u.path == "/api/state":
                    self._send(200, json.dumps({"version": 1, "cards": [], "root": engine.root}))
                else:
                    self._send(404, "{}")

            def do_POST(self):
                self._send(200, "{}")
        return H
'''))
(pkg / "project_agent.py").write_text(textwrap.dedent('''
    class ProjectAgentEngine:
        def __init__(self, path, root, token, **kw):
            self.root = root
            self.agent_name = None
            self.access_key = ""
            self.media_map = []
            self.claude_runner = None

        def start(self): pass
        def stop(self): pass
        def tick(self): pass
        def state(self, q): return {"version": 1, "root": self.root}
'''))
vault = WORK / "vault"
for n in ("Civil Defence", "Framing Formosa", "Pangolins"):
    r = vault / "FF5" / n
    (r / "Interviewees").mkdir(parents=True, exist_ok=True)
    (r / "Script Docs").mkdir(parents=True, exist_ok=True)
    (r / "Script Docs" / "main.cut.md").write_text("x")
projects = WORK / "Projects"
projects.mkdir(exist_ok=True)

from ccsync_dashboard import auth, cards  # noqa: E402
from ccsync_dashboard.app import create_app  # noqa: E402
from ccsync_dashboard.settings import Settings  # noqa: E402

SECRET = "test-secret-not-a-real-one"
s = Settings(db_path=str(WORK / "dash.db"), session_secret=SECRET,
             admin_users=frozenset({"owen"}), projects_dir=str(projects),
             report_token="tok", cards_enabled=True, cards_src=str(src),
             cards_vault_root=str(vault), cards_token="ct")
app = create_app(s)
assert app.state.cards_status == cards.MOUNTED, app.state.cards_detail
(WORK / "cookie.txt").write_text(auth.make_session_cookie(SECRET, "owen"))
(WORK / "cookie_name.txt").write_text(auth.COOKIE_NAME)
import uvicorn  # noqa: E402

uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")
