"""Send to Resolve waits its turn instead of failing when the machine is busy.

CMEDIA-7 of the usability + resilience sweep (2026-09-03), browser half, built
2026-09-04. `broll_fetch`'s per-machine download cap is documented in the
companion as relying on the page: "the web UI re-POSTs every 1.5 s anyway, so
'busy' IS the retry mechanism". It did not - this loop only ever polled while
`state === "downloading"`, so an editor who pressed [ + Resolve ] while two
camera originals were in flight got a red toast and had to remember to come
back in an hour.

Both answers are accepted on purpose: `{ok: true, state: "busy",
retry_after}` from companion 0.9.67+, and the older `{ok: false}` whose message
is the only thing distinguishing it from a real failure. A page that only
understood the new shape would leave every editor on an older build exactly
where they were.
"""
from __future__ import annotations

from pathlib import Path

APP_JS = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(
    encoding="utf-8")


def _send_body() -> str:
    body = APP_JS[APP_JS.index("async function sendToResolve"):]
    return body[:body.index("\n}\n")]


def test_a_busy_companion_is_polled_not_toasted():
    body = _send_body()
    assert 'body.state === "busy"' in body
    assert "/already downloading/i.test(body.message)" in body, (
        "the older shape is an ok:false whose message is the only tell")
    assert body.index('body.state === "busy"') < body.index("if (!res.ok || !body"), (
        "the busy branch has to come before the generic failure branch, or it "
        "is never reached")


def test_the_wait_honours_the_companions_retry_after():
    body = _send_body()
    assert "Number(body && body.retry_after) || 1.5" in body


def test_the_editor_is_told_once_what_is_being_waited_for():
    body = _send_body()
    assert "Waiting for this computer's other downloads to finish." in body
    assert "announcedBusy" in body


def test_the_queue_wait_has_an_end():
    """A wait with no end is the shape of the bug above it (BROLL-17)."""
    body = _send_body()
    assert "busyUntil" in body
    assert "15 * 60 * 1000" in body
