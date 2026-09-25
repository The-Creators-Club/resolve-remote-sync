"""bug-comp-core-1, round 2 (2026-09-25): the dashboard is the only defence
for the first release that carries the companion's crash_looped gate.

Companion 0.9.77 has no such gate. If the first release carrying it
crash-loops, the machine reverts onto 0.9.77, and 0.9.77 would reinstall the
build it fled from the report reply's offer or from a standing [ UPDATE NOW ]
push. The dashboard keeps `upgrade_reverted_from` per machine
(db.store_upgrade_state) past the companion's one-shot send, so the refusal
is made here, for that version, on that machine.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from ccsync_dashboard import alerts, auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"
TOKEN = "r" * 30
NOW = "2026-09-25T12:00:00+00:00"
FLED = "0.9.78"
RESTORED = "0.9.77"


def _env(tmp_path, current=FLED, push=None):
    settings = Settings(db_path=str(tmp_path / "fled.db"), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}),
                        auth_method="local")
    app = create_app(settings)
    c = dbmod.connect(settings.db_path)
    dbmod.migrate(c)
    now = dbmod.utcnow_iso()
    for version in sorted({FLED, current}):
        dbmod.insert_companion_package(
            c, version=version, platform="windows", filename=f"c-{version}.exe",
            sha256="a" * 64, size_bytes=1, published_by="owen", now=now,
            kind="companion", signature="sig", pubkey_id="k", min_version="",
            signed_binary=False, requires_dashboard="", arch="")
    dbmod.set_current_package(c, "windows", current, "companion")
    dbmod.upsert_machine(c, "jsmith", "EDIT-PC", now)
    if push:
        dbmod.request_machine_update(c, "jsmith", "EDIT-PC", push, "owen", now)
    c.commit()
    c.close()
    return settings, app


def _report(app, version=RESTORED, upgrade=None):
    body = {"editor_name": "jsmith", "machine": "EDIT-PC", "platform": "windows",
            "arch": "x86_64", "companion_version": version,
            "reported_at": NOW, "lanes": []}
    if upgrade is not None:
        body["sync_guard"] = {"upgrade": upgrade}
    r = TestClient(app).post(
        "/api/v1/report", json=body,
        headers={"X-CCSync-Token": TOKEN,
                 "X-CCSync-Identity": auth.make_identity_token(SECRET, "jsmith")})
    assert r.status_code == 200, r.text
    return r.json()


# What the restored build sends on its first report after the revert: the
# one-shot marker plus the give-up record the fleeing build wrote.
REVERT = {"reverted_from": FLED, "version": FLED, "attempts": 8,
          "last_error": "crash-looped"}


def test_the_offer_withholds_the_build_this_machine_fled(tmp_path):
    _settings, app = _env(tmp_path)
    reply = _report(app, upgrade=REVERT)
    assert "upgrade" not in reply
    assert "kept crashing" in reply.get("upgrade_none_reason", "")

    # The companion clears reverted_from after one accepted report; the
    # dashboard's copy is what keeps the refusal standing.
    reply = _report(app)
    assert "upgrade" not in reply


def test_a_standing_push_of_the_fled_build_is_withdrawn(tmp_path):
    settings, app = _env(tmp_path, push=FLED)
    reply = _report(app, upgrade=REVERT)
    assert "upgrade" not in reply.get("commands", {})
    assert "upgrade" not in reply
    reply = _report(app)
    assert "upgrade" not in reply.get("commands", {})
    c = dbmod.connect(settings.db_path)
    try:
        assert dbmod.machine_update_request(c, "jsmith", "EDIT-PC") is None
    finally:
        c.close()


def test_an_admin_push_after_the_revert_is_sent(tmp_path):
    settings, app = _env(tmp_path)
    _report(app, upgrade=REVERT)
    c = dbmod.connect(settings.db_path)
    dbmod.request_machine_update(c, "jsmith", "EDIT-PC", FLED, "owen",
                                 dbmod.utcnow_iso())
    c.commit()
    c.close()
    reply = _report(app)
    assert reply["upgrade"]["version"] == FLED
    assert reply["commands"]["upgrade"]["version"] == FLED


def test_a_newer_build_is_offered_as_usual(tmp_path):
    _settings, app = _env(tmp_path, current="0.9.79")
    reply = _report(app, upgrade=REVERT)
    assert reply["upgrade"]["version"] == "0.9.79"


def test_another_machine_is_still_offered_the_build(tmp_path):
    _settings, app = _env(tmp_path)
    _report(app, upgrade=REVERT)
    r = TestClient(app).post(
        "/api/v1/report",
        json={"editor_name": "jsmith", "machine": "LAPTOP", "platform": "windows",
              "arch": "x86_64", "companion_version": RESTORED,
              "reported_at": NOW, "lanes": []},
        headers={"X-CCSync-Token": TOKEN,
                 "X-CCSync-Identity": auth.make_identity_token(SECRET, "jsmith")})
    assert r.json()["upgrade"]["version"] == FLED


def test_the_packages_page_says_why(tmp_path):
    _settings, app = _env(tmp_path)
    _report(app, upgrade=REVERT)
    client = TestClient(app)
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    html = client.get("/partials/admin/packages").text
    assert f"it kept crashing on {FLED} and rolled itself back" in html
    assert "—" not in html


def test_the_grid_chip_reads_a_crash_loop_as_a_crash_loop(tmp_path):
    _settings, app = _env(tmp_path)
    _report(app, upgrade=REVERT)
    client = TestClient(app)
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    html = client.get("/partials/fleet").text
    assert '<span class="w">update kept crashing</span>' in html
    assert "kept crashing on it and was rolled back" in html
    assert "Antivirus quarantine" not in html


class _Ctx:
    def __init__(self, guard):
        self._guard = guard
        self.editors = [{"editor_username": "jsmith", "machine": "EDIT-PC"}]

    def guard(self, e):
        return self._guard

    def name(self, who):
        return who


def test_the_alert_does_not_send_the_admin_to_install_the_fled_build():
    found = alerts._check_upgrade_failed(_Ctx({
        "upgrade_version": FLED, "upgrade_attempts": 8,
        "upgrade_last_error": "crash-looped"}))
    assert len(found) == 1
    text = alerts._finding_body(found[0])
    assert "kept crashing" in text
    assert "Do not install" in text
    assert "downloading the same file" not in text
    assert "install the build by hand" not in text


def test_a_download_failure_keeps_its_own_alert():
    found = alerts._check_upgrade_failed(_Ctx({
        "upgrade_version": FLED, "upgrade_attempts": 8,
        "upgrade_last_error": "sha256 mismatch"}))
    assert "downloading the same file" in alerts._finding_body(found[0])


def test_both_push_doors_refuse_the_fled_build_in_words(tmp_path):
    """Fable review (2026-09-25): the companion refuses a push of the build it
    fled ("crash-looped" on 0.9.78, REL-8's "given up" on 0.9.77), so a push
    let through here sat "asked" for ever. Both doors now say why instead."""
    _settings, app = _env(tmp_path)
    _report(app, upgrade=REVERT)
    client = TestClient(app)
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    csrf = client.get("/partials/admin/packages")
    api_resp = client.post("/api/v1/admin/machines/jsmith/EDIT-PC/update",
                           json={"version": FLED},
                           headers={"Origin": "http://testserver"})
    assert api_resp.status_code == 409, api_resp.text
    assert "kept crashing" in api_resp.json()["detail"]
    page = client.post("/partials/admin/machines/update",
                       data={"editor": "jsmith", "machine": "EDIT-PC"},
                       headers={"Origin": "http://testserver"})
    assert "will not install that build again" in page.text
    c = dbmod.connect(_settings.db_path)
    assert not dbmod.pending_machine_request(c, "jsmith", "EDIT-PC")["update"]
    c.close()
    assert csrf.status_code == 200


def test_the_packages_row_offers_no_update_now_for_the_fled_build(tmp_path):
    _settings, app = _env(tmp_path)
    _report(app, upgrade=REVERT)
    client = TestClient(app)
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
    html = client.get("/partials/admin/packages").text
    row = html[html.index("it kept crashing on"):]
    row = row[:row.index("</tr>")]
    assert ">update now<" not in row
    assert "/partials/admin/machines/update\"" not in row
