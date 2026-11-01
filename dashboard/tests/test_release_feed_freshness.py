"""GL-25b / bug-dash-release-4 (CR-371, 2026-10-07): a channel older than the
newest one already accepted is refused, so a replayed old signed channel
cannot roll a policy=current fleet back or hide a later recall."""
from __future__ import annotations

import json

from ccsync_dashboard import db as dbmod
from ccsync_dashboard import release_feed

from test_release_feed import (CHANNEL_URL, SIG_URL, env, make_channel,  # noqa: F401
                               make_record, patch_opener)

NEW = "2026-10-06T12:00:00Z"
OLD = "2026-09-01T12:00:00Z"


def test_refusal_helper_rules():
    f = release_feed.channel_replay_refusal
    assert f({"generated_at": NEW}, "") == ""                       # first ever check
    assert f({"generated_at": NEW}, NEW) == ""                      # same channel again
    assert f({"generated_at": "2026-10-07T00:00:00Z"}, NEW) == ""   # newer
    assert "OLDER" in f({"generated_at": OLD}, NEW)
    assert "no readable generated_at" in f({}, NEW)                 # dropping the field is no way round
    assert f({"generated_at": OLD}, "not a date") == ""             # our own bad value never wedges us
    # offset spelling compares as an instant, not as a string
    assert f({"generated_at": "2026-10-06T15:00:00+02:00"}, NEW) == ""


def _serve(monkeypatch, generated_at, version):
    record, body = make_record(version=version)
    channel, sig = make_channel([record])
    channel["generated_at"] = generated_at
    # re-sign after editing the signed document
    from test_release_feed import TEST_SEED, ed25519, base64
    sig = base64.b64encode(ed25519.sign(
        TEST_SEED, release_feed.canonical_channel_bytes(channel))).decode("ascii")
    patch_opener(monkeypatch, {CHANNEL_URL: json.dumps(channel).encode(),
                               SIG_URL: sig.encode(), record["url"]: body})


def test_a_replayed_older_channel_is_refused_and_changes_nothing(env, monkeypatch):
    client, conn, settings = env
    _serve(monkeypatch, NEW, "0.9.5")
    assert client.post("/api/v1/admin/feed/check").json()["ok"] is True

    _serve(monkeypatch, OLD, "0.9.0")
    r = client.post("/api/v1/admin/feed/check").json()
    assert r["ok"] is False and "OLDER" in r["error"]
    state = dbmod.get_feed_state(conn)
    assert state["last_channel_generated_at"] == NEW          # high-water mark kept
    assert "OLDER" in state["last_error"]
    # the offers are still the newer channel's
    assert [a["version"] for a in r["view"]["available"]] == ["0.9.5"]

    _serve(monkeypatch, NEW, "0.9.5")                          # the real channel recovers it
    assert client.post("/api/v1/admin/feed/check").json()["ok"] is True


# ---- GL-50 (CR-371 overseer round 2, 2026-10-07): a digest-pinned customer's update path

DIG = "sha256:" + "a" * 64
SFTP = "sha256:" + "b" * 64


def test_hint_prints_the_new_pinned_lines_not_a_bare_update_click():
    hint = release_feed.image_update_hint(
        "truenas", {"tag": "0.7.80", "digest": DIG, "sftp_digest": SFTP})
    assert f"ghcr.io/the-creators-club/ccsync:0.7.80@{DIG}" in hint
    assert f"ghcr.io/the-creators-club/ccsync-sftp:0.7.80@{SFTP}" in hint
    assert "redeploy" in hint and "re-pulls the old pinned image" in hint
    assert "—" not in hint                     # no em dash in visible text


def test_hint_without_a_digest_keeps_the_legacy_click_per_platform():
    for kind, text in (("truenas", "Apps > ccsync > Update"),
                       ("synology", "Container Manager > Project ccsync > Build")):
        assert release_feed.image_update_hint(kind, {"tag": "", "digest": ""}) == text
    assert release_feed.image_update_hint("", None).startswith("your NAS")


def test_the_printed_ref_matches_what_a_pinned_compose_carries():
    """The line the admin pastes must be the SAME shape tools/pin_compose_images.py
    writes into compose.appliance.yaml: <repo>:<version>@<digest>."""
    import re
    from pathlib import Path
    tools = Path(__file__).resolve().parents[2] / "tools"
    import sys
    sys.path.insert(0, str(tools))
    import pin_compose_images as pin
    text = (Path(__file__).resolve().parents[1] / "deploy" / "compose.appliance.yaml").read_text(
        encoding="utf-8")
    pinned = pin.pin(text, version="0.7.80", dashboard_digest=DIG, sftp_digest=SFTP)
    ref = release_feed.image_refs({"tag": "0.7.80", "digest": DIG, "sftp_digest": SFTP})[0]
    tail = ref.split("ccsync:", 1)[1]                         # 0.7.80@sha256:...
    assert re.search(r"ccsync\}:" + re.escape(tail) + '"', pinned)


def test_nas_update_hint_reads_the_signed_channel_image():
    from types import SimpleNamespace
    from ccsync_dashboard import dashboard_update
    state = SimpleNamespace()
    release_feed._cache(state)["channel"] = {"dashboard_image": {
        "tag": "0.7.80", "digest": DIG, "sftp_digest": SFTP}}
    out = dashboard_update.nas_update_hint(SimpleNamespace(nas_kind="synology"), state)
    assert f"ccsync:0.7.80@{DIG}" in out and "Container Manager > Project ccsync > Edit" in out


def test_hint_names_each_service_and_every_ref_pulls_cleanly():
    """Round 2 (2026-10-07): refs are whitespace-delimited with nothing after
    them, in the hint and in the two callers that wrap it."""
    import re
    from types import SimpleNamespace
    from ccsync_dashboard import alerts
    hint = release_feed.image_update_hint(
        "truenas", {"tag": "0.7.80", "digest": DIG, "sftp_digest": SFTP})
    assert "dashboard and secrets-init services: ghcr.io" in hint
    assert "sftp service: ghcr.io" in hint
    assert "install_dashboard_app.py" in hint and "[stack] image" in hint
    ref_re = re.compile(r"^ghcr\.io/[a-z-]+/[a-z-]+:[0-9.]+@sha256:[0-9a-f]{64}$")
    assert hint.endswith(SFTP)
    for tok in hint.split():
        if tok.startswith("ghcr.io/"):
            assert ref_re.match(tok), tok
    assert len([t for t in hint.split() if t.startswith("ghcr.io/")]) == 2
    tpl = (__import__("pathlib").Path(__file__).resolve().parents[1] / "templates"
           / "partials" / "fleet_grid.html").read_text(encoding="utf-8")
    assert "nas_hint }}." not in tpl
    src = (__import__("pathlib").Path(alerts.__file__)).read_text(encoding="utf-8")
    assert "or 'use your NAS app manager to update the ccsync container'}\"" in src
