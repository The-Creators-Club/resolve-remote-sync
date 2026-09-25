"""The terminal look's test switch (docs/UI_REDESIGN_PORT_PLAN.md 7.1 phase 0,
R11). Imported by conftest.py; lives here so conftest stays small.

`ui_variant` is a parametrised fixture. For every non-classic parameter it
makes the SITE SETTING resolve to that parameter's groups through ONE seam,
`ccsync_dashboard.ui_variant.site_groups`, which every reader of
`ui_terminal_groups` goes through. So any app a test builds with its own
`create_app(...)` and its own tmp database draws the parameter's look with no
database write and no knowledge of which app it is.

    def test_x(ui_variant, tmp_path):
        client = TestClient(create_app(...))
        page = client.get("/").text
        ui_variant.check_page(page)          # data-ui-groups is the expected set
        client.get("/partials/stamp", headers=ui_variant.htmx_headers(client))

Parameters: `classic`, `chrome` (phase 1's set), and `all` (every group this
build has). Each phase adds its cumulative prefix (for example
`chrome,home` while phase 3 is built) to UI_VARIANT_PARAMS.

Coverage (R11): while a `ui_variant` test runs, every cc/ template FILE the
per-set environments load is recorded; at the end of a FULL run
(`pytest_sessionfinish`) any file in TEMPLATE_GROUPS that exists and was
never rendered fails the session. A subset run prints a notice instead.
Tests marked `@pytest.mark.ui_mechanism` never record.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from ccsync_dashboard import auth
from ccsync_dashboard import ui_variant as uv

UI_VARIANT_PARAMS = ("classic", "chrome", "all")

_GROUPS_ATTR = re.compile(r'<html[^>]*\bdata-ui-groups="([^"]*)"')


class UIVariant:
    """What a test needs to know about the look it is running under."""

    def __init__(self, name: str):
        self.name = name
        build = uv.build_groups()
        if name == "classic":
            self.setting = frozenset()
        elif name == "all":
            self.setting = frozenset(uv.GROUPS)
        else:
            self.setting, _unknown = uv.parse_groups(name)
        concrete = self.setting & build
        self.groups = concrete if "chrome" in concrete else frozenset()
        self.is_classic = not self.groups

    def __repr__(self) -> str:
        return f"<ui_variant {self.name} -> {sorted(self.groups)}>"

    def groups_attr(self) -> str:
        return uv.groups_text(self.groups)

    def page_groups(self, html: str) -> str | None:
        m = _GROUPS_ATTR.search(html)
        return m.group(1) if m else None

    def check_page(self, html: str) -> None:
        """A full page must carry exactly the expected set, so a render that
        quietly fell back to classic fails."""
        assert self.page_groups(html) == self.groups_attr(), (
            f"{self!r}: page rendered with data-ui-groups="
            f"{self.page_groups(html)!r}")

    def htmx_headers(self, client, current_url: str = "http://testserver/") -> dict:
        """The headers a real page of this look sends on an htmx request:
        HX-Request, the EXPANDED group list, the generation token and a valid
        signature over the client's own session."""
        headers = {"HX-Request": "true", "HX-Current-URL": current_url}
        text = uv.groups_text(self.groups)
        headers["X-CC-UI"] = text
        if self.groups:
            settings = client.app.state.settings
            gen = uv.generation(self.groups)
            sid = _sid_of(client)
            headers["X-CC-UI-Gen"] = gen
            headers["X-CC-UI-Sig"] = uv.header_sig(settings, text, gen, sid)
        return headers


def _sid_of(client) -> str:
    cookie = client.cookies.get(auth.COOKIE_NAME)
    if not cookie:
        return ""
    settings = client.app.state.settings
    return auth.session_id_for(settings.session_secret, cookie)


@pytest.fixture(params=UI_VARIANT_PARAMS)
def ui_variant(request, monkeypatch):
    variant = UIVariant(request.param)
    monkeypatch.setattr(uv, "site_groups",
                        lambda conn, settings, app=None: variant.setting)
    token = None
    if request.node.get_closest_marker("ui_mechanism") is None:
        token = uv.RECORDING.set(True)
    try:
        yield variant
    finally:
        if token is not None:
            uv.RECORDING.reset(token)


def configure(config) -> None:
    config.addinivalue_line(
        "markers", "ui_mechanism: an overlay/filter mechanism test; its template "
                   "loads never count as terminal coverage (R11)")


def sessionfinish(session, exitstatus) -> None:
    tests_dir = Path(__file__).resolve().parent
    wanted = {p.resolve() for p in tests_dir.glob("test_*.py")}
    collected = {Path(str(item.fspath)).resolve() for item in getattr(session, "items", [])}
    templates = uv.TEMPLATES_DIR
    existing = sorted(n for n in uv.TEMPLATE_GROUPS if (templates / n).is_file())
    missing = [n for n in existing if n not in uv.RENDERED_CC_FILES]
    if not (wanted and wanted <= collected):
        if missing:
            print(f"\n[ui_variant coverage] subset run: not checked "
                  f"({len(missing)} cc/ template(s) not rendered in this run)")
        return
    if missing:
        print("\n[ui_variant coverage] cc/ templates no terminal-parametrised test "
              "renders: " + ", ".join(missing))
        session.exitstatus = 1
