"""Fault injection, wave 2: the server half of SYS-10's nine.

SYS-10 (usability + resilience sweep 2026-09-03,
`docs/usability-resilience-sweep-2026-09-03/SYS.md`): the 28 fault injections
this repo had were all parameterised over the shapes of the sweep BEFORE last,
and everything in CR-125..CR-154 was found by the owner using the product
instead. This module is the sibling of `test_fault_injection.py`, written
against the newer ledger and on the same two rules:

1. **Every assertion is an OBSERVABLE** - the row that survived, the notice a
   person is handed, the refusal a route makes. Never a log line: sixteen
   `log.error` diagnoses reaching only the container log is the exact defect
   (UX-10) the self-diagnosis wave was built to close, and a test that
   asserted the call would have passed throughout.
2. **Nothing here sleeps, spawns or reaches the network,** and nothing depends
   on the platform - this suite runs on the macOS CI runner too.

Five injections:

  1. a vendor build this dashboard is too old to hand out (SYS-2)
  2. a mounted app's manifest fetched with no session (CR-100)
  3. a template rendering a control the route would refuse (SYS-3 / CR-95)
  4. a report whose second project fails mid-write (CR-141)
  5. a dashboard that has never talked to Syncthing (CR-154)
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import VERSION
from ccsync_dashboard import api as apimod
from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import release_feed
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s"
NOW = "2026-09-04T12:00:00+00:00"

DASHBOARD_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = DASHBOARD_ROOT / "templates"
SOURCE = DASHBOARD_ROOT / "src" / "ccsync_dashboard"


@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "dash.db"
    settings = Settings(db_path=str(db_path), report_token="sekrit",
                        session_secret=SECRET, admin_users=frozenset({"admin"}))
    app = create_app(settings)
    # raise_server_exceptions=False: injection 4 makes a write RAISE inside
    # the route on purpose, and what is under test is the state the database
    # is left in, not the traceback.
    with TestClient(app, raise_server_exceptions=False) as client:
        conn = dbmod.connect(db_path)
        apimod._IGNORED_SECTION_LOGGED.clear()
        yield client, conn, settings
        conn.close()


def _headers(editor: str = "jsmith"):
    return {"X-CCSync-Token": "sekrit",
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


# -- 1: a build this dashboard is too old to hand out (SYS-2) -------------
#
# "Deploy the dashboard before the companions" is enforced by REL-4/SYS-13:
# a companion record whose `requires_dashboard` is above this build is STAGED,
# never made current. That refusal is correct, and until wave 1 its only
# statement was a log line - so the site then read as fully up to date on the
# fleet grid, in the weekly report and on the Packages page while every
# computer in the fleet had quietly stopped updating. This is the one case
# that can never self-heal: the refused build is not in `companion_packages`,
# so "N releases behind" counts it as zero.


def _feed_record(version: str, requires: str, platform: str = "windows") -> dict:
    return {"kind": "companion", "platform": platform, "version": version,
            "requires_dashboard": requires, "filename": f"ccsync-{version}.exe",
            "sha256": "0" * 64, "url": "https://example.invalid/x"}


@pytest.mark.parametrize("requires,refused", [
    # The shape that happens: the vendor ships a companion that needs a
    # dashboard this site has not taken yet.
    ("99.0.0", True),
    # An UNPARSEABLE requirement blocks too (package_store's rule): a stated
    # requirement that cannot be read is exactly where guessing "probably
    # fine" produces the B16 shape with the arrow reversed.
    ("not-a-version", True),
    # ...and the ordinary case, which must stay silent or the banner cries
    # wolf on every check and gets ignored the way the log was (CR-139's
    # findings-about-nothing are how a panel stops being read).
    ("0.0.1", False),
])
def test_a_build_this_dashboard_is_too_old_for_is_a_notice_not_a_log_line(
        env, requires, refused):
    """SYS-2. Two durable facts per check, and both are observables: the
    NOTICE a person is handed on the home page, and the record of what the
    vendor offers, which is what lets the fleet be measured against the
    vendor's channel rather than against this dashboard's own shelf."""
    _client, conn, _settings = env
    records = [_feed_record("0.9.99", requires)]

    answer = release_feed.record_offer_state(conn, records, NOW)

    # What the vendor offers is recorded either way: an empty picture means
    # UNKNOWN (no check has run), never "the vendor has nothing".
    assert dbmod.get_feed_offered(conn) == {"windows": ["0.9.99"]}

    found = [n for n in dbmod.open_notices(conn) if n["kind"] == "feed_publish_refused"]
    if not refused:
        assert answer == [] and not found
        return
    assert answer == ["companion/windows 0.9.99"]
    assert found, "the fleet stopped updating and every page said nothing was wrong"
    assert found[0]["severity"] == "error"
    assert "0.9.99" in found[0]["body"] and VERSION in found[0]["body"]
    assert found[0]["fix"], "a notice with no next action is a log line"


def test_the_refusal_clears_itself_once_the_dashboard_is_updated(env):
    """The half that keeps the panel honest: a finding that could not clear
    would send an operator to look at a thing that is already fixed (CR-140's
    rule - a finding the operator cannot clear is worse than no finding)."""
    _client, conn, _settings = env
    release_feed.record_offer_state(conn, [_feed_record("0.9.99", "99.0.0")], NOW)
    assert [n for n in dbmod.open_notices(conn) if n["kind"] == "feed_publish_refused"]

    # The next check, with the same build now within reach.
    release_feed.record_offer_state(conn, [_feed_record("0.9.99", "0.0.1")], NOW)
    assert not [n for n in dbmod.open_notices(conn)
                if n["kind"] == "feed_publish_refused"]


# -- 2: a mounted app's manifest fetched with no session (CR-100) ---------
#
# A browser fetches a manifest WITHOUT the session cookie. Behind the outer
# login gate Chrome got a 303 to /login in place of `/cards/manifest.webmanifest`,
# judged the page not installable, and "Install" on the phone made a plain
# shortcut that opens with a URL bar ("no certificate", Alex, 2026-09-02).
# SYS-11 is the same class not yet closed - the next mount that ships a PWA
# will do it again - so the assertion here is on the GATE, per path, and it
# holds whether or not the cards checkout is present on this machine.


OPEN_TO_A_BROWSER_WITH_NO_SESSION = (
    "/manifest.webmanifest",
    "/sw.js",
    "/offline",
    "/favicon.ico",
    # The Timeline Cards page's own two (CR-100). Its manifest is
    # document-relative with scope ".", so these are the paths a phone asks
    # for before anyone has signed in.
    "/cards/manifest.webmanifest",
    "/cards/icon.svg",
)


@pytest.mark.parametrize("path", OPEN_TO_A_BROWSER_WITH_NO_SESSION)
def test_an_installable_surface_is_never_sent_to_the_login_page(env, path):
    """CR-100. The contract, not the copy: the gate must not answer a
    REDIRECT for these, whatever the mount behind them is doing. A 404 (no
    cards checkout on this machine) still proves the property - the request
    reached routing instead of being turned away at the door."""
    client, _conn, _settings = env

    r = client.get(path, follow_redirects=False)

    assert r.status_code not in (301, 302, 303, 307, 308), (
        f"{path} was redirected to {r.headers.get('location')!r} with no session; "
        "a manifest or an icon that 303s installs nothing and explains nothing")
    assert "/login" not in (r.headers.get("location") or "")


@pytest.mark.parametrize("path", ["/cards/", "/cards/api/state", "/settings"])
def test_the_pages_behind_those_surfaces_still_need_a_session(env, path):
    """The converse, and the reason the list above is exact rather than a
    `/cards/` prefix: opening a manifest must not open the app."""
    client, _conn, _settings = env

    r = client.get(path, follow_redirects=False)

    assert r.status_code in (301, 302, 303, 307, 308, 401, 403), (
        f"{path} answered {r.status_code} with no session")


# -- 3: a control the route would refuse (SYS-3 / CR-95) ------------------
#
# CR-95: every checkbox in a wired column rendered `disabled`, ticked or not,
# so a stale tick sat greyed out with nothing on the page able to send the
# DELETE the route had always allowed - "as a wired user I cannot assign any
# project ... they're all greyed out". The class is a template making a policy
# decision the route does not share. So: every `disabled`/`readonly` in the
# templates must either be CONDITIONAL on something the server computes (the
# route's own predicate, by name), or be listed below as cosmetic with a
# reason. A greyed-out control whose grey exists only in the HTML is a rule
# nobody can find and nobody can test.

# Cosmetic disables: the control is not a way of expressing a server policy at
# all. Keyed by template AND by the control's own id/name, with a reason each -
# a per-FILE entry would let the next unconditional disable into an
# already-listed template unseen, which is how an allow-list becomes a way of
# passing rather than a way of saying why.
COSMETIC_DISABLES = {
    "admin_settings.html#manifest.features.ai_cli_providers": (
        "a display-only mirror of features.ai_cli_providers: the real switch "
        "is accepting the notice in the AI providers section below, and this "
        "box exists to show the resulting state (CLAUDE.md: accepting the "
        "wizard's notice is what turns the feature on)"),
    "setup.html#setup-eula-accept": (
        "[ ACCEPT ] on the EULA, enabled by setup.js once the checkbox is "
        "ticked. The server does not refuse it - setup_api.setup_admin's own "
        "'no users yet' gate is the real one - so there is no route predicate "
        "to name; the disable is 'read it first'"),
}

_TAG = re.compile(r"<(?:input|button|select|textarea|option|fieldset)\b[^>]*>",
                  re.IGNORECASE | re.DOTALL)
_JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.DOTALL)
_COMMENT = re.compile(r"\{#.*?#\}", re.DOTALL)
_QUOTED = re.compile(r'"[^"]*"|\'[^\']*\'')
_WORD = re.compile(r"(?<![\w-])(disabled|readonly)(?![\w-])")
_IF = re.compile(r"\{%-?\s*(?:el)?if\s+(.+?)\s*-?%\}", re.DOTALL)
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# The control's own name: `id="..."` or `name="..."`, whichever comes first.
_MARKER = re.compile(r"""(?:id|name)=["']([^"'{}]+)["']""")
_DOTTED = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+")


def _control_name(tag: str) -> str:
    """What to call this control in the allow-list: its `id`/`name`, or - for
    a display-only box that submits nothing, which is exactly the shape a
    cosmetic disable takes - the dotted context path it renders."""
    marker = _MARKER.search(tag)
    if marker:
        return marker.group(1)
    dotted = _DOTTED.findall(tag)
    return dotted[0] if dotted else "<unnamed>"


def _blank(text: str, pattern: re.Pattern, skip: list[tuple[int, int]] = ()) -> str:
    """Replace every match with spaces, keeping every offset true - line
    numbers and "which `{% if %}` is this under" both depend on them."""
    out = list(text)
    for m in pattern.finditer(text):
        if any(s <= m.start() < e for s, e in skip):
            continue
        for i in range(m.start(), m.end()):
            if out[i] != "\n":
                out[i] = " "
    return "".join(out)

# Jinja/template words that are never a server predicate.
_NOT_PREDICATES = {"if", "not", "and", "or", "in", "is", "defined", "none",
                   "true", "false", "elif", "else", "endif", "checked",
                   "disabled", "readonly", "length", "get"}


def _disable_sites() -> list[tuple[str, int, str, str, str]]:
    """(template, line, kind, guard, key) for every disabled/readonly ATTRIBUTE.

    Three things are blanked first, each because it is prose or data rather
    than a disable: `{# a comment explaining the disable #}` (CR-95's own
    template has one, and it says the word), and quoted HTML attribute values
    OUTSIDE a jinja expression - `name="disabled"`, `title="a disabled account
    ..."` in partials/admin_users.html. Quotes inside `{{ "disabled" if x }}`
    are kept, because there the string IS the attribute.

    `kind` is "static" or "conditional"; the guard is the jinja expression
    that decides it, either the one the word sits inside or the nearest
    `{% if %}` above it in the same tag; `key` is `template#id-or-name`, the
    allow-list key, so that list names CONTROLS and not files.
    """
    sites = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        raw_text = path.read_text(encoding="utf-8")
        text = _blank(raw_text, _COMMENT)
        rel = str(path.relative_to(TEMPLATES)).replace("\\", "/")
        for tag in _TAG.finditer(text):
            raw = tag.group(0)
            jinja = [(m.start(), m.end()) for m in _JINJA.finditer(raw)]
            scrubbed = _blank(raw, _QUOTED, skip=jinja)
            key = f"{rel}#{_control_name(raw)}"
            for hit in _WORD.finditer(scrubbed):
                line = text.count("\n", 0, tag.start() + hit.start()) + 1
                inside = [raw[s:e] for s, e in jinja if s <= hit.start() < e]
                if inside:
                    sites.append((rel, line, "conditional", inside[0], key))
                    continue
                conditions = _IF.findall(raw[:hit.start()])
                if conditions:
                    sites.append((rel, line, "conditional", conditions[-1], key))
                else:
                    sites.append((rel, line, "static", "", key))
    return sites


_SET = re.compile(r"\{%-?\s*set\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*-?%\}",
                  re.DOTALL)


def _predicate_names(rel: str, guard: str, hops: int = 3) -> set[str]:
    """The names the guard really turns on, following `{% set %}` one template
    at a time. `{% set is_auto = key in auto_derived %}` is a local alias for
    something the ROUTE put in the context (`setup_routes` fills
    `manifest["auto_derived"]`), and a check that stopped at `is_auto` would
    report a rule that lives only in the HTML when it does not."""
    local = dict(_SET.findall((TEMPLATES / rel).read_text(encoding="utf-8")))
    names = {n for n in _IDENT.findall(guard) if n.lower() not in _NOT_PREDICATES}
    for _ in range(hops):
        expanded = set()
        for name in names:
            if name in local:
                expanded |= {n for n in _IDENT.findall(local[name])
                             if n.lower() not in _NOT_PREDICATES and n != name}
            else:
                expanded.add(name)
        if expanded == names:
            break
        names = expanded
    return names


def test_the_scan_finds_the_controls_it_is_meant_to_guard():
    """A guard that silently matches nothing guards nothing - and this one is
    a regex over HTML, which is exactly the kind of check that quietly stops
    matching. CR-95's own template must be in the list."""
    sites = _disable_sites()
    assert len(sites) >= 5, f"the disable scan found only {sites}"
    assert any(rel == "admin_assignments.html" and kind == "conditional"
               for rel, _line, kind, _guard, _key in sites), (
        "CR-95's own control is no longer being scanned")
    # And the three false positives the scrubber exists for.
    users = [s for s in sites if s[0] == "partials/admin_users.html"]
    assert users == [], f"data and prose read as a disable: {users}"


@pytest.mark.parametrize(
    "rel,line,kind,guard,key",
    [pytest.param(*s, id=f"{s[0]}:{s[1]}") for s in _disable_sites()],
)
def test_every_greyed_out_control_is_either_the_routes_rule_or_documented(
        rel, line, kind, guard, key):
    """SYS-3 / CR-95. Either the server computes the grey (so the same
    predicate can be found in the source, and the route can be asked what it
    would do), or the grey is cosmetic and says why here."""
    if kind == "static":
        reason = COSMETIC_DISABLES.get(key)
        assert reason, (
            f"{rel}:{line} ({key}) renders a control disabled unconditionally. Either "
            f"guard it on what the ROUTE decides (CR-95: a wired column greyed "
            f"out the untick the route had always allowed), or add it to "
            f"COSMETIC_DISABLES with the reason it is only cosmetic.")
        return
    names = _predicate_names(rel, guard)
    assert names, f"{rel}:{line} is guarded by an expression with no name in it: {guard!r}"
    hits = {n for n in names
            if any(re.search(rf"\b{re.escape(n)}\b", p.read_text(encoding="utf-8"))
                   for p in SOURCE.rglob("*.py"))}
    assert hits, (
        f"{rel}:{line} greys a control on {sorted(names)}, and no route or view "
        f"in dashboard/src names any of them - so the rule exists only in the "
        f"HTML and nothing server-side enforces it (SYS-3).")


# -- 4: a report whose second project fails mid-write (CR-141) ------------
#
# Twelve `database is locked` failures in 27 minutes of live 0.7.28, every
# victim blocked on its FIRST write: they were not slow, they were queued
# behind `api_report`, which took ONE transaction per report and replaced up
# to 6000 rows per ticked project inside it. The fix commits after the fleet
# state and again after EACH project, which makes a report 1+N+M transactions
# instead of one - "a report is no longer atomic" is a CONTRACT now, and this
# is the injection that pins it: a project that fails must not roll back the
# projects already written.


def _manifest(rel: str, n: int) -> dict:
    return {"n_originals": n, "bytes_originals": n * 1000, "n_proxies": 0,
            "bytes_proxies": 0, "truncated": False,
            "originals": [(f"{rel}/A{i:03d}.mov", 1000) for i in range(n)]}


def _media_rows(conn, slug: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM editor_media WHERE project_slug=?", (slug,)).fetchone()[0]


def test_a_report_whose_second_project_fails_keeps_the_firsts_rows(env, monkeypatch):
    """CR-141. The observable is what survives in the database: the first
    project's file list, written and COMMITTED before the second one was
    attempted. Under the old one-transaction shape the failure took the whole
    report with it, including the fleet state - so a machine reporting a
    project the writer choked on vanished from the grid entirely."""
    client, conn, _settings = env
    for slug in ("ff5", "ff6"):
        dbmod.upsert_project(conn, slug, slug, f"/projects/{slug}", NOW)
    conn.commit()

    real = dbmod.replace_editor_media
    seen: list[str] = []

    def flaky(conn_, editor, machine, slug, files, now):
        seen.append(slug)
        if len(seen) == 2:
            raise sqlite3.OperationalError("database is locked")
        return real(conn_, editor, machine, slug, files, now)

    monkeypatch.setattr(dbmod, "replace_editor_media", flaky)

    r = client.post("/api/v1/report", json={
        "editor_name": "JSmith",
        "machine": "EDIT-PC",
        "companion_version": "0.9.66",
        "reported_at": NOW,
        "lanes": [{"name": "lane_c_syncthing", "state": "idle", "queued": 0,
                   "transferring": 0, "last_error": None, "last_sync": None,
                   "detail": None}],
        "local_manifest": {"ff5": _manifest("ff5", 3), "ff6": _manifest("ff6", 3)},
    }, headers=_headers())

    assert r.status_code == 500, "the injected write really did fail"
    assert len(seen) == 2

    # The fleet state, written and committed before the manifest loop: the
    # machine is on the grid even though its report ended badly.
    assert [row["machine"] for row in dbmod.fetch_machines(conn)] == ["EDIT-PC"]
    # ...and the first project's rows are intact. `seen[0]` rather than "ff5"
    # because dict order is the wire's, not ours.
    assert _media_rows(conn, seen[0]) == 3, (
        "a later project's failure rolled back a project already written "
        "(CR-141: each project's replace is its own transaction)")
    assert _media_rows(conn, seen[1]) == 0


def test_the_next_report_heals_the_project_that_failed(env, monkeypatch):
    """Why the lost atomicity is safe, asserted rather than asserted-in-prose:
    both media tables are a FULL REPLACE per (editor, machine, project) and
    the same machine reports again a minute later, so the worst case is one
    cycle of staleness in one project's file list."""
    client, conn, _settings = env
    for slug in ("ff5", "ff6"):
        dbmod.upsert_project(conn, slug, slug, f"/projects/{slug}", NOW)
    conn.commit()

    real = dbmod.replace_editor_media
    fail = {"now": True}

    def flaky(conn_, editor, machine, slug, files, now):
        if fail["now"] and slug == "ff6":
            raise sqlite3.OperationalError("database is locked")
        return real(conn_, editor, machine, slug, files, now)

    monkeypatch.setattr(dbmod, "replace_editor_media", flaky)
    body = {
        "editor_name": "JSmith", "machine": "EDIT-PC",
        "companion_version": "0.9.66", "reported_at": NOW,
        "lanes": [{"name": "lane_c_syncthing", "state": "idle", "queued": 0,
                   "transferring": 0, "last_error": None, "last_sync": None,
                   "detail": None}],
        "local_manifest": {"ff5": _manifest("ff5", 3), "ff6": _manifest("ff6", 2)},
    }
    client.post("/api/v1/report", json=body, headers=_headers())
    assert _media_rows(conn, "ff6") == 0

    fail["now"] = False
    r = client.post("/api/v1/report", json=body, headers=_headers())

    assert r.status_code == 200
    assert _media_rows(conn, "ff5") == 3 and _media_rows(conn, "ff6") == 2


# -- 5: a dashboard that has never talked to Syncthing (CR-154) -----------
#
# `GET /api/v1/health` answered `syncthing_reachable: true`, and an overall
# `ok`, on a deployment with no Syncthing at all: the collector's list of
# kinds that may run WITHOUT Syncthing grew to ("prune", "invariants",
# "alerts") and the query that reads the evidence still excluded 'prune' with
# a literal, so the first cycle's `invariants` row was read as proof that
# Syncthing had been reached. Three doors take that endpoint at its word - the
# container healthcheck, ship's post-deploy poll and the wizard's connection
# test - so lane C being dead fleet-wide looked healthy to every automatic
# check that exists.


@pytest.mark.parametrize("kind", dbmod.SYNCTHING_FREE_KINDS)
def test_a_cycle_that_needs_no_syncthing_is_not_evidence_that_it_was_reached(
        env, kind):
    """CR-154. Parameterised over the constant itself, because the defect was
    the two ends of the list drifting apart: a kind added to the collector's
    gate and not to the query is this bug again, and this test is what makes
    adding one impossible to do silently."""
    client, conn, _settings = env
    dbmod.record_poll_run(conn, kind, NOW, NOW, True, None)
    conn.commit()

    assert dbmod.fetch_collector_status(conn)["syncthing_reachable"] is False
    # With the companion credential: an unauthenticated caller gets only
    # {ok, version} (the roster used to be readable by anyone on the port).
    body = client.get("/api/v1/health", headers=_headers()).json()
    assert body["syncthing_reachable"] is False, (
        f"a successful '{kind}' cycle was read as proof Syncthing answered")


def test_a_real_syncthing_backed_cycle_still_counts(env):
    """The converse: the endpoint must still be able to say yes, or the three
    automatic checks that read it become permanently useless."""
    client, conn, _settings = env
    dbmod.record_poll_run(conn, "syncthing", dbmod.utcnow_iso(),
                          dbmod.utcnow_iso(), True, None)
    conn.commit()

    assert dbmod.fetch_collector_status(conn)["syncthing_reachable"] is True
    assert client.get("/api/v1/health", headers=_headers()
                      ).json()["syncthing_reachable"] is True


# -- the registry ----------------------------------------------------------


WAVE2_FAULTS = {
    "feed_build_refused": "SYS-2",
    "manifest_with_no_session": "CR-100 / SYS-11",
    "greyed_out_without_a_rule": "SYS-3 / CR-95",
    "report_project_fails_mid_write": "CR-141",
    "syncthing_never_reached": "CR-154",
}


def test_every_wave_two_injection_has_a_section():
    """The parent module's pin, on this file."""
    body = Path(__file__).read_text(encoding="utf-8")
    for number in range(1, 6):
        assert f"# -- {number}:" in body, f"no injection section for fault {number}"
    assert len(WAVE2_FAULTS) == 5
    for fault, closes in WAVE2_FAULTS.items():
        assert closes, f"{fault} closes no ledger entry"
