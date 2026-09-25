"""The 2026-09-24 hunt, dashboard templates (webapps-ops group).

ui-dash-admin-1: a project label (a folder name anyone with write access to
the tree chooses) was spliced into the SOURCE of an inline handler. Jinja's
HTML autoescape is decoded by the browser before the handler compiles, so it
protects nothing there: "Editor's Cut" was a SyntaxError (the ARCHIVE form
then submitted with no confirm) and a crafted name ran as script. The sweep
found the same shape in the MOVE form's hx-on::confirm.

Each test renders the real page through the app and then does what the
browser does: HTML-unescapes the attribute and, when node is on PATH,
compiles and runs the handler with a stub confirm().
"""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"
SLUG = "2026-editors-cut"
# An apostrophe (the reported break), a double quote and a backslash (the
# MOVE form's string was "-quoted), and a payload that would run if spliced.
LABEL = "2026/Editor's \"Cut\" \\ x');window.__pwned=1;('"


@pytest.fixture
def client(tmp_path):
    settings = Settings(db_path=str(tmp_path / "t.db"), session_secret=SECRET,
                        admin_users=frozenset({"owen"}))
    app = create_app(settings)
    with TestClient(app) as c:
        conn = dbmod.connect(tmp_path / "t.db")
        now = dbmod.utcnow_iso()
        dbmod.upsert_project(conn, SLUG, LABEL, f"/data/{SLUG}", now)
        dbmod.record_known_editor(conn, "editor1", source="admin", now=now)
        conn.commit()
        conn.close()
        c.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        yield c


def _attr(tag: str, name: str) -> str:
    m = re.search(rf'\s{re.escape(name)}="([^"]*)"', tag, re.S)
    assert m, f"no {name} on {tag[:200]}"
    return html.unescape(m.group(1))


def _form_tag(body: str, marker: str) -> str:
    for tag in re.findall(r"<form\b[^>]*>", body, re.S):
        if marker in tag:
            return tag
    raise AssertionError(f"no form containing {marker!r}")


def _run_handler(source: str, this: dict, event: dict | None = None) -> dict:
    """Compile `source` as the browser would (a function body) and run it
    with a stub confirm(); -> {"compiled", "message", "pwned"}."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not on PATH")
    script = f"""
var out = {{compiled: false, message: null, pwned: false}};
var window = {{confirm: function (m) {{ out.message = m; return false; }}}};
var confirm = window.confirm;
var src = {json.dumps(source)};
var fn;
try {{ fn = new Function('event', src); out.compiled = true; }} catch (e) {{ out.error = String(e); }}
if (fn) {{
  var ctx = {json.dumps(this)};
  ctx.querySelector = function (sel) {{ return ctx.fields[sel]; }};
  var ev = {json.dumps(event or {})};
  ev.preventDefault = function () {{}};
  ev.detail = {{issueRequest: function () {{}}}};
  try {{ fn.call(ctx, ev); }} catch (e) {{ out.error = String(e); }}
}}
out.pwned = !!window.__pwned;
process.stdout.write(JSON.stringify(out));
"""
    res = subprocess.run([node, "-e", script], capture_output=True, text=True,
                         timeout=30, check=False)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


# ------------------------------------------------------------ ui-dash-admin-1

def test_the_archive_confirm_never_carries_the_label_in_its_source(client):
    body = client.get("/admin/assignments?editor=editor1&machine=*").text
    tag = _form_tag(body, "/partials/admin/projects/archive")
    handler = _attr(tag, "onsubmit")
    assert "Cut" not in handler and "__pwned" not in handler, handler
    assert _attr(tag, "data-archive-label") == LABEL


def test_the_archive_confirm_compiles_and_asks_about_the_real_name(client):
    body = client.get("/admin/assignments?editor=editor1&machine=*").text
    tag = _form_tag(body, "/partials/admin/projects/archive")
    out = _run_handler(_attr(tag, "onsubmit"),
                       {"dataset": {"archiveLabel": _attr(tag, "data-archive-label")}})
    assert out["compiled"], out
    assert not out["pwned"], out
    assert out["message"] and out["message"].startswith(f"Archive {LABEL}?"), out


def test_the_move_confirm_never_carries_the_label_in_its_source(client):
    body = client.get(f"/partials/project/{SLUG}").text
    tag = _form_tag(body, "move-form")
    handler = _attr(tag, "hx-on::confirm")
    assert "Cut" not in handler and "__pwned" not in handler, handler
    assert _attr(tag, "data-project-label") == LABEL

    fields = {"[name=path]": {"value": "B-roll/A001.braw"},
              "[name=to_slug]": {"selectedIndex": 0, "options": [{"text": "Other"}]},
              "[name=to_path]": {"value": ""}}
    out = _run_handler(handler,
                       {"dataset": {"projectLabel": _attr(tag, "data-project-label")},
                        "fields": fields},
                       {})
    assert out["compiled"], out
    assert not out["pwned"], out
    assert f"from {LABEL} to Other" in (out["message"] or ""), out


def test_no_template_splices_a_string_value_into_an_inline_handler():
    """The sweep, pinned: every `on*=` / `hx-on*=` attribute in every
    dashboard template carries server values only as a number (`| int`). A
    string goes in a data- attribute and is read from the DOM."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "templates"
    bad = []
    for path in sorted(root.rglob("*.html")):
        # Jinja comments first: one inside the MOVE handler holds a raw `"`,
        # which would end the attribute early and hide the rest of it.
        text = re.sub(r"\{#.*?#\}", "", path.read_text(encoding="utf-8"), flags=re.S)
        for m in re.finditer(r'\s((?:hx-)?on[\w:.-]*)="([^"]*)"', text, re.S):
            for expr in re.findall(r"\{\{(.*?)\}\}", m.group(2), re.S):
                if not re.search(r"\|\s*int\s*$", expr.strip()) \
                        and not re.fullmatch(r"\s*''\s+if\s+.*\s+else\s+'s'\s*", expr):
                    bad.append(f"{path.relative_to(root)}: {m.group(1)} {{{{{expr}}}}}")
    assert not bad, "\n".join(bad)
