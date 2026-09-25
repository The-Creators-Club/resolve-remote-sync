"""CR-335 (2026-09-25): the Packages page's MAKE CURRENT, as the owner met it.

"clicking make current, there is a long delay before it happens, and no
visual feedback ... I had to click it multiple times. In this page, latest
builds should be at the top, older builds underneath."

What was really going on (fleet_audit on the live dashboard): the macOS 0.9.77
clicks were REFUSED by the soak gate every time, the refusal was drawn at the
top of the panel (or carried by htmx_errors.js to the OTHER, identical form
for the same build further down), and Windows 0.9.77 became current a couple
of minutes later through the feed poller's `current` policy, with no audit
entry to say so. Four things are defended here:

  * every list is newest first;
  * every MAKE CURRENT button has a busy label and disables itself while its
    request is in flight;
  * a refusal is drawn ON THE ROW that was clicked, and the top-of-panel
    banner (the one the script moves) is not also drawn for it;
  * an unattended promotion leaves an audit row.
"""
from __future__ import annotations

import re

from ccsync_dashboard import db as dbmod
from ccsync_dashboard import ui

from test_packages import as_user, env, insert_unsigned_package  # noqa: F401


def test_every_list_is_newest_first():
    rows = [{"kind": "companion", "platform": "macos", "version": v}
            for v in ("0.9.9", "0.9.77", "0.9.10", "0.9.7+dirty", "junk")]
    groups = ui._kind_platform_groups(rows)
    got = [r["version"] for r in groups[0]["platforms"][0]["rows"]]
    assert got == ["0.9.77", "0.9.10", "0.9.9", "0.9.7+dirty", "junk"]


def test_a_make_current_button_says_it_is_working_and_cannot_be_double_clicked(env):  # noqa: F811
    client, conn, settings = env
    as_user(client, "owen")
    insert_unsigned_package(conn, settings, "windows", "9.9.9")
    html = client.get("/partials/admin/packages").text
    forms = re.findall(r'<form[^>]*hx-post="/partials/admin/packages/current"[^>]*>', html)
    assert forms
    for form in forms:
        assert 'hx-disabled-elt="this"' in form and 'hx-indicator="this"' in form
    # The busy label the key shows while its request is in flight (hx-indicator
    # on the form swaps `.t` for `.busy-t`).
    assert '<span class="t">make current</span><span class="busy-t">making it current</span>' in html


def test_a_refusal_is_drawn_on_the_row_that_was_clicked(env):  # noqa: F811
    client, conn, settings = env
    as_user(client, "owen")
    insert_unsigned_package(conn, settings, "windows", "9.9.9")
    insert_unsigned_package(conn, settings, "windows", "9.9.8", body=b"other-bytes")
    html = client.post("/partials/admin/packages/current",
                       data={"kind": "companion", "platform": "windows",
                             "version": "9.9.9"}).text
    assert dbmod.get_current_package(conn, "windows") is None
    # Not the top-of-panel banner the script moves to the FIRST matching form.
    assert "error-banner" not in html
    rows = re.split(r'<tr class="pkg-row">', html)
    refused = [r for r in rows if "row-refusal" in r]
    assert len(refused) == 1
    assert "9.9.9" in refused[0] and "no release signature" in refused[0]
    assert "9.9.8" not in refused[0]


def test_an_unattended_promotion_leaves_an_audit_row(env, monkeypatch):  # noqa: F811
    """The package_store publish door (make_current=1 through a publish) is
    the unattended path this file can drive without a feed; release_feed's
    current-policy branch writes the same row."""
    client, conn, settings = env
    from test_packages import publish_platform

    as_user(client, "owen")
    r = publish_platform(client, "windows", "1.2.3", make_current=1)
    assert r.status_code in (200, 201), r.text
    assert dbmod.get_current_package(conn, "windows")["version"] == "1.2.3"
    rows = conn.execute(
        "SELECT action, subject FROM fleet_audit WHERE action='package.make_current'"
    ).fetchall()
    assert ("package.make_current", "1.2.3") in [tuple(r) for r in rows]
