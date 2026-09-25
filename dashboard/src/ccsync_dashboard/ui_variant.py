"""The terminal look's template overlay (docs/UI_REDESIGN_PORT_PLAN.md 7.0,
phase 0, 2026-09-25).

The CC Terminal redesign is ported page GROUP by page group behind a site
setting, `ui_terminal_groups`, and a per-browser cookie. Everything that
decides which look a response is drawn in lives here, so `ui._render` makes
one call and the rest of the product never asks.

The rules this module exists to keep, each one a failure somebody would
otherwise meet:

* ONE Jinja environment per effective group set, never one environment whose
  loader decides per request. Jinja caches a compiled template per
  environment under its name and only asks the loader again when the file's
  mtime changes, so a request-dependent loader would serve whichever variant
  it compiled first to everybody after it. Each set gets its own environment,
  built lazily, memoised, and cloned from the classic one with `overlay()` so
  autoescape and every other option come with it (a bare Environment
  defaults to autoescape OFF: stored XSS on every terminal page).
* The classic environment can never load `cc/*`, and a set's environment
  serves `cc/<name>` only for a template whose group is in the set.
* A partial is drawn in the look of the PAGE that asked for it (R23): the
  page sends the group set it was rendered with in `X-CC-UI`, signed, with a
  generation token; an htmx request with no header at all is classic, and
  gets `HX-Refresh` when a full load would now look different.
* Every resolved set is intersected with the groups THIS build has templates
  for, so a group stored early, or left on across a rollback, does nothing
  until its templates exist, and a page never reload-loops.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import mimetypes
import threading
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from jinja2 import BaseLoader, ChoiceLoader, FileSystemLoader, TemplateNotFound

from . import auth, site_store

log = logging.getLogger("ccsync.dashboard.ui_variant")

# .woff2 has no entry in Python 3.12's own table and python:3.12-slim ships no
# /etc/mime.types, so StaticFiles would send the fonts as text/plain (2.3).
mimetypes.add_type("font/woff2", ".woff2")

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
CC_DIR_NAME = "cc"

# The page groups, in the order the phases enable them (7.1).
GROUPS: tuple[str, ...] = ("chrome", "home", "everyday", "settings-fleet",
                           "settings-health", "apps")
ALL = "all"

# Every file under templates/cc/, mapped to exactly ONE group. A test fails
# on a file that is missing from this table, and the coverage hook in
# tests/conftest.py fails on an entry no terminal-parametrised test renders.
# Keys are paths relative to templates/, `cc/` included. Each phase adds its
# own rows in the commit that adds the templates.
TEMPLATE_GROUPS: dict[str, str] = {
    # phase 1 (chrome): the shell, the HUD and its furniture
    "cc/shell.html": "chrome",
    "cc/partials/topbar.html": "chrome",
    "cc/partials/settings_nav.html": "chrome",
    "cc/partials/stamp.html": "chrome",
    "cc/partials/halt_line.html": "chrome",
    "cc/partials/hint_sheet.html": "chrome",
    # phase 2 (home): the home and project pages and their partials
    "cc/fleet.html": "home",
    "cc/project.html": "home",
    "cc/partials/home_macros.html": "home",
    "cc/partials/fleet_grid.html": "home",
    "cc/partials/plan_changes.html": "home",
    "cc/partials/home_transfers.html": "home",
    "cc/partials/home_problems.html": "home",
    "cc/partials/home_collector.html": "home",
    "cc/partials/home_queue.html": "home",
    "cc/partials/home_fix_root.html": "home",
    "cc/partials/computer_answer.html": "home",
    "cc/partials/projects_tree.html": "home",
    "cc/partials/project_detail.html": "home",
    "cc/partials/bins.html": "home",
    "cc/partials/missing_files.html": "home",
    "cc/partials/project_roots.html": "home",
    "cc/partials/project_roots_browse.html": "home",
    # phase 5 (settings-health): Health, invariants, protection, alerts, recovery
    "cc/admin_health.html": "settings-health",
    "cc/admin_invariants.html": "settings-health",
    "cc/admin_protection.html": "settings-health",
    "cc/admin_alerts.html": "settings-health",
    "cc/admin_recovery.html": "settings-health",
    "cc/partials/invariant_checks.html": "settings-health",
    "cc/partials/protection.html": "settings-health",
    "cc/partials/admin_alerts.html": "settings-health",
    "cc/partials/recovery.html": "settings-health",
    "cc/partials/health_notices.html": "settings-health",
    "cc/partials/health_collector.html": "settings-health",
    "cc/partials/health_diagnostics.html": "settings-health",
    # phase 3 (everyday): transfers, project setup, installer, sign in,
    # help and the personal account page
    "cc/partials/ev_macros.html": "everyday",
    "cc/transfers.html": "everyday",
    "cc/partials/transfers.html": "everyday",
    "cc/project_setup.html": "everyday",
    "cc/partials/project_setup_panel.html": "everyday",
    "cc/installer.html": "everyday",
    "cc/login.html": "everyday",
    "cc/help.html": "everyday",
    "cc/account.html": "everyday",
    "cc/partials/account_you.html": "everyday",
    "cc/partials/account_password.html": "everyday",
    "cc/partials/account_computer.html": "everyday",
    "cc/partials/account_jobs.html": "everyday",
    "cc/partials/account_sessions.html": "everyday",
    "cc/partials/account_sync_keys.html": "everyday",
    "cc/partials/account_result.html": "everyday",
    "cc/partials/person_queue.html": "everyday",
    "cc/partials/person_fix_root.html": "everyday",
    # phase 4 (settings-fleet), second half (P4b): users, sync plans,
    # jobs, history, setup
    "cc/admin_users.html": "settings-fleet",
    "cc/partials/admin_users.html": "settings-fleet",
    "cc/partials/admin_sessions.html": "settings-fleet",
    "cc/partials/admin_report_tokens.html": "settings-fleet",
    "cc/partials/admin_suspend_button.html": "settings-fleet",
    "cc/partials/fleet_halt.html": "settings-fleet",
    "cc/partials/minted_secret.html": "settings-fleet",
    "cc/admin_assignments.html": "settings-fleet",
    "cc/admin_jobs.html": "settings-fleet",
    "cc/partials/admin_jobs.html": "settings-fleet",
    "cc/admin_audit.html": "settings-fleet",
    "cc/partials/admin_audit.html": "settings-fleet",
    "cc/setup.html": "settings-fleet",
    # phase 4 (settings-fleet), first half (P4a): Site and Packages
    "cc/admin_settings.html": "settings-fleet",
    "cc/partials/android_settings.html": "settings-fleet",
    "cc/admin_packages.html": "settings-fleet",
    "cc/partials/admin_packages.html": "settings-fleet",
    "cc/partials/admin_dashboard_update.html": "settings-fleet",
    # phase 6 (apps), first half: the /cards landing
    "cc/cards_landing.html": "apps",
}

# cc/ templates with NO classic twin (7.0, "new-named terminal partials"),
# addressed without the cc/ prefix and reachable only through the group
# filter. Every other file under templates/cc/ must shadow a classic path.
NEW_NAME_TEMPLATES: frozenset[str] = frozenset({
    "cc/shell.html",
    "cc/partials/halt_line.html", "cc/partials/hint_sheet.html",
    "cc/partials/home_transfers.html", "cc/partials/home_problems.html",
    "cc/partials/home_collector.html", "cc/partials/home_queue.html",
    "cc/partials/home_fix_root.html", "cc/partials/computer_answer.html",
    "cc/partials/projects_tree.html", "cc/partials/person_queue.html",
    "cc/partials/person_fix_root.html", "cc/partials/health_notices.html",
    "cc/partials/health_collector.html", "cc/partials/health_diagnostics.html",
    "cc/partials/ev_macros.html",
    "cc/partials/home_macros.html",
})

# Which group a full page belongs to, by its path (R23's reload hint and
# 7.0 step 2): the asking page's group is read off HX-Current-URL. Longest
# prefix wins; an exact entry ends with "$".
ROUTE_GROUPS: tuple[tuple[str, str], ...] = (
    ("/$", "home"),
    ("/project/", "home"),
    ("/transfers", "everyday"),
    ("/project-setup", "everyday"),
    ("/installer", "everyday"),
    ("/download", "everyday"),
    ("/login", "everyday"),
    ("/help", "everyday"),
    ("/account", "everyday"),
    ("/offline", "everyday"),
    ("/admin/settings", "settings-fleet"),
    ("/admin/users", "settings-fleet"),
    ("/admin/assignments", "settings-fleet"),
    ("/admin/packages", "settings-fleet"),
    ("/admin/jobs", "settings-fleet"),
    ("/admin/audit", "settings-fleet"),
    ("/setup", "settings-fleet"),
    ("/admin/health", "settings-health"),
    ("/admin/invariants", "settings-health"),
    ("/admin/protection", "settings-health"),
    ("/admin/alerts", "settings-health"),
    ("/admin/recovery", "settings-health"),
    ("/cards/", "apps"),
    ("/broll/", "apps"),
    ("/music/", "apps"),
    ("/ytdl/", "apps"),
)

# The first dashboard VERSION that parses X-CC-UI (R23's header floor). An
# image below it cannot answer a page's header, so enabling a group on one is
# refused where that can be checked.
HEADER_FLOOR = "0.7.61"

# Cookies (7.0, 3.4).
PREVIEW_COOKIE = "ccsync_ui"                 # cc (signed) | classic | absent
EFFECTIVE_COOKIE = "ccsync_ui_effective"     # "chrome.apps" | "chrome" | ""
PREVIEW_MAX_AGE = 180 * 24 * 3600
PREVIEW_MODES = ("off", "admins", "everyone")

# Request headers (R23).
H_SET = "x-cc-ui"
H_GEN = "x-cc-ui-gen"
H_SIG = "x-cc-ui-sig"
H_WANT = "X-CC-UI-Want"

# Per-group history of look changes, kept OUT of site_history (R24).
UI_GROUPS_HISTORY_KEY = "ui_groups_history"
UI_GROUPS_HISTORY_KEEP = 20


# ------------------------------------------------------------ build facts

_lock = threading.RLock()
_build_groups_cache: frozenset[str] | None = None
_gen_cache: dict[frozenset[str], str] = {}
_asset_hashes: dict[str, str] = {}


def refresh() -> None:
    """Forget every cached build fact (tests write templates; a restart does
    this for free)."""
    global _build_groups_cache
    with _lock:
        _build_groups_cache = None
        _gen_cache.clear()
        _asset_hashes.clear()
        _envs.clear()


def build_groups(templates_dir: Path | None = None) -> frozenset[str]:
    """The groups that have at least one `cc/` template in THIS build."""
    global _build_groups_cache
    base = Path(templates_dir or TEMPLATES_DIR)
    if templates_dir is None and _build_groups_cache is not None:
        return _build_groups_cache
    found = frozenset(group for name, group in TEMPLATE_GROUPS.items()
                      if (base / name).is_file())
    if templates_dir is None:
        _build_groups_cache = found
    return found


def asset_hash(path: str) -> str:
    """sha256[:10] of a static file's bytes, "" when it does not exist."""
    path = str(path).lstrip("/")
    with _lock:
        cached = _asset_hashes.get(path)
    if cached is not None:
        return cached
    try:
        digest = hashlib.sha256((STATIC_DIR / path).read_bytes()).hexdigest()[:10]
    except OSError:
        digest = ""
    with _lock:
        _asset_hashes[path] = digest
    return digest


def asset_url(path: str) -> str:
    """`/static/<path>?h=<content hash>` (2.5). A content hash, not VERSION:
    a same-version redeploy (a CSS hotfix, an OTA bundle) must still change
    the URL, or the service worker pairs new HTML with the cached old sheet."""
    path = str(path).lstrip("/")
    digest = asset_hash(path)
    return f"/static/{path}?h={digest}" if digest else f"/static/{path}"


def cc_assets() -> list[str]:
    """Every file under static/cc/, as paths relative to static/."""
    root = STATIC_DIR / CC_DIR_NAME
    if not root.is_dir():
        return []
    return sorted(p.relative_to(STATIC_DIR).as_posix()
                  for p in root.rglob("*") if p.is_file())


def font_files() -> list[str]:
    root = STATIC_DIR / "fonts"
    if not root.is_dir():
        return []
    return sorted(p.relative_to(STATIC_DIR).as_posix()
                  for p in root.iterdir() if p.suffix == ".woff2")


def precache_urls() -> list[str]:
    """What sw.js precaches beyond its own list (R8): the hashed cc/ sheets
    and scripts, and the fonts at their PLAIN urls (a static sheet's url()
    cannot carry the hash, and caches.match matches the query string)."""
    urls = [asset_url(p) for p in cc_assets()
            if p.endswith((".css", ".js"))]
    urls += [f"/static/{p}" for p in font_files()]
    return urls


def generation(groups: Iterable[str]) -> str:
    """The page-scoped content digest (R23): the asset hashes of what a cc
    shell loads plus the bytes of the cc/ templates of the groups in the set.
    "" for the empty set, which is never compared."""
    key = frozenset(groups)
    if not key:
        return ""
    with _lock:
        cached = _gen_cache.get(key)
    if cached is not None:
        return cached
    h = hashlib.sha256()
    for asset in cc_assets():
        h.update(asset.encode() + b"=" + asset_hash(asset).encode() + b"\n")
    for name in sorted(TEMPLATE_GROUPS):
        if TEMPLATE_GROUPS[name] in key:
            try:
                h.update(name.encode() + b"\n" + (TEMPLATES_DIR / name).read_bytes())
            except OSError:
                continue
    value = h.hexdigest()[:16]
    with _lock:
        _gen_cache[key] = value
    return value


def current_generation(groups: Iterable[str] | None = None) -> str:
    """The generation a page drawn now with `groups` carries (default: every
    group this build has)."""
    return generation(build_groups() if groups is None else groups)


# ------------------------------------------------------------ loaders

def _norm(name: str) -> str:
    return str(name).replace("\\", "/").lstrip("/")


class ClassicLoader(FileSystemLoader):
    """templates/, refusing every name under cc/: the group filter cannot be
    bypassed by asking for `cc/...` by name through the classic fallback."""

    def get_source(self, environment, template):
        if _norm(template).startswith(CC_DIR_NAME + "/"):
            raise TemplateNotFound(template)
        return super().get_source(environment, template)

    def list_templates(self):
        return [n for n in super().list_templates()
                if not _norm(n).startswith(CC_DIR_NAME + "/")]


class GroupFilteredLoader(BaseLoader):
    """Serves `cc/<name>` for a logical name (or for `cc/<name>` itself) only
    when that template's group is in the set FIXED at construction, so the
    environment's template cache is correct by construction."""

    def __init__(self, templates_dir: Path | str, groups: Iterable[str],
                 template_groups: dict[str, str] | None = None):
        self.groups = frozenset(groups)
        self.template_groups = TEMPLATE_GROUPS if template_groups is None else template_groups
        self._fs = FileSystemLoader(str(templates_dir))

    def get_source(self, environment, template):
        name = _norm(template)
        if not name.startswith(CC_DIR_NAME + "/"):
            name = f"{CC_DIR_NAME}/{name}"
        group = self.template_groups.get(name)
        if group is None or group not in self.groups:
            raise TemplateNotFound(template)
        return self._fs.get_source(environment, name)

    def list_templates(self):
        return sorted(n for n, g in self.template_groups.items() if g in self.groups)


# ------------------------------------------------------------ environments

# The coverage registry (R11): cc/ template FILES rendered inside a test that
# uses the `ui_variant` fixture. The fixture sets the contextvar; a test
# marked `ui_mechanism` never sets it, so the mechanism tests' own loads do
# not count as coverage.
class _Flag:
    """A process-wide switch with ContextVar's get/set/reset shape. Not a
    ContextVar: TestClient renders on its portal thread, which never sees a
    context variable the test thread set."""

    def __init__(self) -> None:
        self._value = False

    def get(self) -> bool:
        return self._value

    def set(self, value: bool) -> bool:
        old, self._value = self._value, bool(value)
        return old

    def reset(self, token: bool) -> None:
        self._value = bool(token)


RECORDING = _Flag()
RENDERED_CC_FILES: set[str] = set()

_classic_templates: Any = None          # the Jinja2Templates ui.py builds
_envs: dict[frozenset[str], Any] = {}   # set -> Jinja2Templates wrapper
_extra_loaders: list[BaseLoader] = []   # test-only (tests/templates/cc_probe.html)


def _record(env) -> None:
    original = env._load_template
    cc_root = str((TEMPLATES_DIR / CC_DIR_NAME).resolve())

    def load(name, globals):  # noqa: A002 - Jinja's own parameter name
        template = original(name, globals)
        if RECORDING.get():
            filename = str(Path(template.filename or "").resolve()) if template.filename else ""
            if filename.startswith(cc_root):
                RENDERED_CC_FILES.add(
                    Path(filename).relative_to(TEMPLATES_DIR.resolve()).as_posix())
        return template

    env._load_template = load


def install(templates) -> None:
    """Called once by ui.py on its Jinja2Templates: restrict the classic
    environment so it can never load cc/*, and register the two globals every
    template may read."""
    global _classic_templates
    _classic_templates = templates
    templates.env.loader = ClassicLoader(str(TEMPLATES_DIR))
    templates.env.globals["asset_url"] = asset_url
    templates.env.globals["ui_look_form"] = look_form_state
    templates.env.globals["ui_can_preview"] = can_preview
    templates.env.globals.setdefault("ui_groups", frozenset())
    templates.env.globals.setdefault("ui_groups_attr", "")
    templates.env.globals.setdefault("ui_hx_headers", [])


def can_preview(request) -> bool:
    """Template helper: may this signed-in browser switch to the cc look?"""
    try:
        user = auth.get_session_user(request)
        return bool(user) and preview_allowed(request.app.state.settings, request.app, user)
    except Exception:                                              # noqa: BLE001
        return False


def look_form_state(request) -> dict:
    """What the classic Settings page's look-groups form draws (R24): every
    group with whether this build has it and whether it is on, the stored
    value, who may preview, and the last few look changes. Read here, not in
    the page handler, so the Settings route is untouched."""
    from . import db

    settings = request.app.state.settings
    build = build_groups()
    stored_raw = "none"
    history: list[dict] = []
    try:
        conn = db.connect(settings.db_path)
        try:
            rows = site_store.get_all(conn)
            stored_raw = rows.get("ui_terminal_groups", "") or ""
            history = [e for e in (db.meta_get_json(conn, UI_GROUPS_HISTORY_KEY) or [])
                       if isinstance(e, dict)][:5]
        finally:
            conn.close()
    except Exception:                                              # noqa: BLE001
        log.exception("could not read the look settings for the Settings page")
    stored, _unknown = parse_groups(stored_raw)
    return {
        "groups": [{"name": g, "in_build": g in build, "on": g in stored} for g in GROUPS],
        "stored": stored_raw or "site",
        "follows_default": not stored_raw,
        "preview": preview_mode(settings, request.app),
        "history": history,
    }


def add_test_loader(loader: BaseLoader) -> None:
    """TEST ONLY: an extra loader appended to every per-set environment
    (phases 0-1 render `tests/templates/cc_probe.html`, a child of
    cc/shell.html, through it; never a production route)."""
    with _lock:
        _extra_loaders.append(loader)
        _envs.clear()


def remove_test_loader(loader: BaseLoader) -> None:
    with _lock:
        if loader in _extra_loaders:
            _extra_loaders.remove(loader)
        _envs.clear()


def sync_envs() -> None:
    """Copy the classic environment's globals and filters into every per-set
    environment built so far. `overlay()` already shares them by reference;
    this is the belt to that brace, for a global registered after a set's
    environment was built."""
    if _classic_templates is None:
        return
    base = _classic_templates.env
    with _lock:
        for wrapper in _envs.values():
            env = wrapper.env
            for key, value in base.globals.items():
                env.globals.setdefault(key, value)
            for key, value in base.filters.items():
                env.filters.setdefault(key, value)


def templates_for(groups: Iterable[str]):
    """The Jinja2Templates wrapper that renders `groups` (a concrete set).
    The empty set is the classic environment itself."""
    from fastapi.templating import Jinja2Templates

    key = frozenset(groups)
    if not key or _classic_templates is None:
        return _classic_templates
    with _lock:
        wrapper = _envs.get(key)
        if wrapper is not None:
            return wrapper
        base = _classic_templates.env
        loaders: list[BaseLoader] = [GroupFilteredLoader(TEMPLATES_DIR, key),
                                     ClassicLoader(str(TEMPLATES_DIR))]
        loaders.extend(_extra_loaders)
        env = base.overlay(loader=ChoiceLoader(loaders))
        _record(env)
        wrapper = Jinja2Templates(env=env)
        _envs[key] = wrapper
    sync_envs()
    return wrapper


def built_environments() -> list[Any]:
    """Every environment in play: classic first, then each set's."""
    with _lock:
        out = [_classic_templates.env] if _classic_templates is not None else []
        out.extend(w.env for w in _envs.values())
    return out


# ------------------------------------------------------------ the setting

def parse_groups(raw: str | Iterable[str] | None) -> tuple[frozenset[str], set[str]]:
    """(known groups, unknown names) of a stored or sent value. `none` and ""
    are the empty set; `all` is every group name."""
    if raw is None:
        return frozenset(), set()
    if isinstance(raw, str):
        items = [p.strip().lower() for p in raw.split(",")]
    else:
        items = [str(p).strip().lower() for p in raw]
    items = [p for p in items if p and p != "none"]
    if ALL in items:
        return frozenset(GROUPS), set()
    unknown = {p for p in items if p not in GROUPS}
    return frozenset(p for p in items if p in GROUPS), unknown


def validate_groups_value(raw: str) -> str:
    """site_store's validator for `ui_terminal_groups` (R24). Returns the
    normalised stored value: `none`, or the names in GROUPS order. Refuses,
    never corrects: an unknown name, a set without `chrome`, or a group this
    build has no templates for."""
    text = str(raw or "").strip().lower()
    if text in ("", "none"):
        return "none"
    if text == "site":
        raise site_store.SiteValidationError(
            "ui_terminal_groups", "'site' deletes the row; it is not a stored value")
    groups, unknown = parse_groups(text)
    if unknown:
        raise site_store.SiteValidationError(
            "ui_terminal_groups",
            f"unknown group(s): {', '.join(sorted(unknown))}; the groups are "
            + ", ".join(GROUPS))
    if groups and "chrome" not in groups:
        raise site_store.SiteValidationError(
            "ui_terminal_groups",
            "every group needs 'chrome' (the new header is part of every new page); "
            "add it, or turn the new look off with 'none'")
    missing = sorted(groups - build_groups())
    if missing:
        raise site_store.SiteValidationError(
            "ui_terminal_groups",
            f"this build has no templates for {', '.join(missing)} yet "
            "(waiting for its build)")
    return ",".join(g for g in GROUPS if g in groups) or "none"


def validate_preview_value(raw: str) -> str:
    text = str(raw or "").strip().lower() or "off"
    if text not in PREVIEW_MODES:
        raise site_store.SiteValidationError(
            "ui_preview", f"must be one of {', '.join(PREVIEW_MODES)}")
    return text


def site_groups(conn, settings, app: Any = None) -> frozenset[str]:
    """THE seam every reader of `ui_terminal_groups` goes through (the phase
    0 test fixture monkeypatches it). The stored set, not yet intersected
    with the build; a stored set without `chrome` counts as empty."""
    try:
        if conn is not None:
            value = site_store.resolved_manifest(conn, settings).get("ui_terminal_groups", "")
        else:
            value = site_store.manifest_for_app(app, settings).get("ui_terminal_groups", "")
    except Exception:                                              # noqa: BLE001
        log.exception("could not read ui_terminal_groups; drawing the classic look")
        return frozenset()
    groups, _unknown = parse_groups(value)
    if groups and "chrome" not in groups:
        return frozenset()
    return groups


def preview_mode(settings, app: Any = None) -> str:
    try:
        value = site_store.manifest_for_app(app, settings).get("ui_preview", "off")
    except Exception:                                              # noqa: BLE001
        return "off"
    value = str(value or "off").strip().lower()
    return value if value in PREVIEW_MODES else "off"


def preview_allowed(settings, app, username: str | None) -> bool:
    """May `username` see the cc preview (3.4)?"""
    if not username:
        return False
    mode = preview_mode(settings, app)
    if mode == "off":
        return False
    if mode == "everyone":
        return True
    return bool(auth.is_admin(settings, username))


# ------------------------------------------------------------ signing

def _secret(settings) -> bytes:
    return str(getattr(settings, "session_secret", "") or "").encode()


def _mac(settings, *parts: str) -> str:
    msg = "|".join(parts).encode("utf-8", "replace")
    return hmac.new(_secret(settings), msg, hashlib.sha256).hexdigest()[:32]


def sign_preview(settings, username: str) -> str:
    """The `cc` cookie value: signed over `cc` and the admin who set it, so a
    signed-out request can honour it for that admin's login preview and for
    nobody else (3.4)."""
    user = quote(str(username), safe="")
    return f"cc.{user}.{_mac(settings, 'ccui-preview', 'cc', str(username))}"


def read_preview(settings, value: str | None) -> str | None:
    """The username a `cc` cookie was signed for, or None."""
    if not value or not value.startswith("cc."):
        return None
    try:
        _cc, user_q, mac = value.split(".", 2)
    except ValueError:
        return None
    from urllib.parse import unquote

    user = unquote(user_q)
    good = _mac(settings, "ccui-preview", "cc", user)
    return user if hmac.compare_digest(good, mac) else None


def header_sig(settings, groups_text: str, gen: str, sid: str) -> str:
    return _mac(settings, "ccui-set", groups_text, gen, sid or "")


def groups_text(groups: Iterable[str]) -> str:
    g = frozenset(groups)
    return ",".join(x for x in GROUPS if x in g)


# ------------------------------------------------------------ resolution

class Resolution:
    """What `_render` needs to know about one request's look."""

    __slots__ = ("groups", "source", "refresh", "want", "conflict", "cannot_serve")

    def __init__(self, groups: frozenset[str], source: str, *, refresh: bool = False,
                 want: bool = False, conflict: bool = False, cannot_serve: bool = False):
        self.groups = groups
        self.source = source
        self.refresh = refresh          # htmx GET: answer HX-Refresh
        self.want = want                # send X-CC-UI-Want
        self.conflict = conflict        # htmx write: 409 plus Want
        self.cannot_serve = cannot_serve  # empty body rather than a fragment

    def __repr__(self) -> str:
        return f"<Resolution {sorted(self.groups)} via {self.source}>"


def page_group(path: str) -> str | None:
    """The group of the full page at `path` (ROUTE_GROUPS)."""
    path = path or "/"
    best: tuple[int, str] | None = None
    for prefix, group in ROUTE_GROUPS:
        if prefix.endswith("$"):
            if path == prefix[:-1]:
                return group
            continue
        if path.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), group)
    return best[1] if best else None


def _asking_page_group(request: Request) -> str | None:
    url = request.headers.get("hx-current-url", "")
    if not url:
        return None
    try:
        return page_group(urlsplit(url).path)
    except ValueError:
        return None


def _relevant(groups: frozenset[str], group: str | None) -> frozenset[str]:
    keep = {"chrome"}
    if group:
        keep.add(group)
    return frozenset(groups) & keep


def full_load_groups(request: Request) -> tuple[frozenset[str], str]:
    """The set a FULL load of this request would get now: the cookie, then
    the setting, intersected with this build (7.0)."""
    settings = request.app.state.settings
    build = build_groups()
    cookie = request.cookies.get(PREVIEW_COOKIE, "")
    if cookie == "classic":
        return frozenset(), "cookie-classic"
    if cookie.startswith("cc."):
        signer = read_preview(settings, cookie)
        user = auth.get_session_user(request)
        if signer:
            if user:
                ok = preview_allowed(settings, request.app, user)
            else:
                ok = (preview_mode(settings, request.app) != "off"
                      and bool(auth.is_admin(settings, signer)))
            if ok:
                return build, "cookie-cc"
    stored = site_groups(None, settings, request.app)
    return (stored & build if "chrome" in (stored & build) else frozenset()), "setting"


def resolve(request: Request) -> Resolution:
    """7.0's order: (1) a signed X-CC-UI header on an htmx request; (2) an
    htmx request with NO header is classic; (3) everything else follows the
    cookie, then the setting."""
    settings = request.app.state.settings
    build = build_groups()
    is_htmx = request.headers.get("hx-request", "").lower() == "true"
    write = request.method.upper() not in ("GET", "HEAD")
    if not is_htmx:
        groups, source = full_load_groups(request)
        return Resolution(groups, source)

    raw = request.headers.get(H_SET)
    if raw is None:
        # A page from before phase 0, or the frozen classic dashboard_update.js.
        full, _src = full_load_groups(request)
        differs = bool(_relevant(full, _asking_page_group(request)))
        return Resolution(frozenset(), "htmx-no-header",
                          refresh=differs and not write,
                          conflict=differs and write, want=differs)

    sent, unknown = parse_groups(raw)
    if raw.strip().lower() == ALL:
        sent = build
    if not sent and not unknown:
        # A fully classic page. Left alone unless a full load would now differ
        # for chrome or its own group: then the quiet reload line.
        full, _src = full_load_groups(request)
        want = bool(_relevant(full, _asking_page_group(request)))
        return Resolution(frozenset(), "header", want=want)

    gen_sent = request.headers.get(H_GEN)
    sig_sent = request.headers.get(H_SIG, "")
    sid = auth.get_session_id(request) or ""
    expect = header_sig(settings, groups_text(sent), gen_sent or "", sid)
    signed = bool(sig_sent) and hmac.compare_digest(expect, sig_sent)
    if unknown or (sent - build) or not signed:
        # "Cannot serve" (R23): a group this build has no templates for, a
        # name it does not know, or a signature that no longer verifies. The
        # page reloads itself; the reloaded page names only this build's
        # groups, so it happens once.
        return Resolution(sent & build, "header-cannot-serve", refresh=not write,
                          conflict=write, want=True, cannot_serve=True)
    groups = sent & build
    want = False
    if gen_sent is None or gen_sent != generation(groups):
        want = True
    full, _src = full_load_groups(request)
    group = _asking_page_group(request)
    if _relevant(full, group) != _relevant(groups, group):
        want = True
    return Resolution(groups, "header", want=want)


def hx_headers(request: Request, groups: frozenset[str]) -> list[tuple[str, str]]:
    """The keys a page adds to its hx-headers after X-CSRF-Token (R23). The
    empty set sends X-CC-UI with an empty value and nothing else."""
    if not groups:
        return [("X-CC-UI", "")]
    settings = request.app.state.settings
    text = groups_text(groups)
    gen = generation(groups)
    sid = auth.get_session_id(request) or ""
    return [("X-CC-UI", text), ("X-CC-UI-Gen", gen),
            ("X-CC-UI-Sig", header_sig(settings, text, gen, sid))]


def is_partial(name: str) -> bool:
    """A fragment is any template whose LAST directory is `partials`
    (`partials/x.html` and `cc/partials/x.html` alike)."""
    return _norm(name).split("/")[-2:-1] == ["partials"]


def effective_value(groups: frozenset[str]) -> str:
    """`ccsync_ui_effective`: dot-separated (a comma is not a legal
    cookie-octet and Starlette would quote it)."""
    return ".".join(g for g in ("chrome", "apps") if g in groups)


def set_effective_cookie(request: Request, response: Response,
                         groups: frozenset[str]) -> None:
    """Readable by the SPAs' first-paint script, Path=/ always. Only written
    when it would change, so a classic site never gets a Set-Cookie."""
    value = effective_value(groups)
    if request.cookies.get(EFFECTIVE_COOKIE, "") == value:
        return
    settings = request.app.state.settings
    if not value:
        response.delete_cookie(EFFECTIVE_COOKIE, path="/")
        return
    response.set_cookie(EFFECTIVE_COOKIE, value, max_age=PREVIEW_MAX_AGE, path="/",
                        samesite="lax", httponly=False,
                        secure=auth.cookie_secure(settings, request))


def render(request: Request, name: str, context: dict) -> Response:
    """`ui._render`'s last step: resolve the look, pick the environment,
    render, and attach the look's headers and cookie."""
    res = resolve(request)
    partial = is_partial(name)
    groups = res.groups
    context["ui_groups"] = groups
    context["ui_groups_attr"] = groups_text(groups)
    context["ui_hx_headers"] = hx_headers(request, groups)
    context.setdefault("oob", request.headers.get("hx-request", "").lower() == "true")
    headers = {}
    if res.want:
        headers[H_WANT] = "1"
    if res.conflict:
        return HTMLResponse("", status_code=409, headers=headers)
    if res.refresh and res.cannot_serve:
        headers["HX-Refresh"] = "true"
        return HTMLResponse("", status_code=200, headers=headers)
    wrapper = templates_for(groups)
    response = wrapper.TemplateResponse(request=request, name=name, context=context)
    if res.refresh:
        response.headers["HX-Refresh"] = "true"
    for key, value in headers.items():
        response.headers[key] = value
    if not partial:
        set_effective_cookie(request, response, groups)
    return response


# ------------------------------------------------------------ /ui/preview

router = APIRouter()


def _next_target(request: Request) -> str:
    from .ui import _safe_next

    raw = request.query_params.get("next", "")
    if raw:
        return _safe_next(raw)
    ref = request.headers.get("referer", "")
    if ref:
        try:
            parts = urlsplit(ref)
        except ValueError:
            return "/"
        if parts.netloc and parts.netloc == request.headers.get("host", ""):
            return _safe_next(parts.path + (f"?{parts.query}" if parts.query else ""))
    return "/"


@router.get("/ui/preview", include_in_schema=False)
def ui_preview(request: Request, variant: str = ""):
    """Write or clear this BROWSER's look cookie (3.4). `classic` and `site`
    work signed out (they only remove a look); `cc` needs a session whose
    role the `ui_preview` setting allows. Changes nothing server-side."""
    settings = request.app.state.settings
    variant = str(variant or "").strip().lower()
    if variant not in ("cc", "classic", "site"):
        raise HTTPException(status_code=400, detail="variant must be cc, classic or site")
    user = auth.get_session_user(request)
    if variant == "cc":
        if not user:
            raise HTTPException(status_code=403, detail="sign in to preview the new look")
        if not preview_allowed(settings, request.app, user):
            raise HTTPException(status_code=403,
                                detail="the new look's preview is not open to this account")
    response = RedirectResponse(_next_target(request), status_code=303)
    secure = auth.cookie_secure(settings, request)
    if variant == "site":
        response.delete_cookie(PREVIEW_COOKIE, path="/", samesite="lax",
                               secure=secure, httponly=True)
    else:
        value = sign_preview(settings, user) if variant == "cc" else "classic"
        response.set_cookie(PREVIEW_COOKIE, value, max_age=PREVIEW_MAX_AGE, path="/",
                            samesite="lax", secure=secure, httponly=True)
    return response


# ------------------------------------------------------------ /go/<panel>

# R13: panel anchors named from Python and templates resolve through here, so
# a panel that moves between pages (phase 5) moves in ONE table. Each entry is
# (source group, source href, destination group or None, destination href).
GO_PANELS: dict[str, tuple[str, str, str | None, str | None]] = {
    "notices": ("home", "/#server-notices", "settings-health", "/admin/health#server-notices"),
    "collector": ("home", "/#fleet-collector", "settings-health", "/admin/health#fleet-collector"),
    "diagnostics": ("home", "/#fleet-diagnostics", "settings-health",
                    "/admin/health#fleet-diagnostics"),
    "admin-fleet-halt": ("settings-fleet", "/admin/users#admin-fleet-halt", None, None),
    "ai-providers": ("settings-fleet", "/admin/settings#ai-providers", None, None),
    "restore": ("settings-health", "/admin/recovery#restore", None, None),
    "dashboard-update": ("settings-fleet", "/admin/packages#dashboard-update", None, None),
}


def go_href(panel: str, groups: frozenset[str]) -> str | None:
    """7.0's cross-group rule: the destination when its group is on, else the
    source (the same href in the terminal and the classic source page)."""
    entry = GO_PANELS.get(panel)
    if entry is None:
        return None
    _src_group, src, dst_group, dst = entry
    if dst_group and dst and dst_group in groups:
        return dst
    return src


@router.get("/go/{panel}", include_in_schema=False)
def go_panel(panel: str, request: Request):
    groups, _src = full_load_groups(request)
    href = go_href(panel, groups)
    if href is None:
        raise HTTPException(status_code=404, detail="no such panel")
    return RedirectResponse(href, status_code=303)
