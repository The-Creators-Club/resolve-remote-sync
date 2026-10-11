"""Gear identify: a photo from thecreatorsclub.co/gear -> a packing-list entry.

POST /api/v1/gear/identify  {image: base64 JPEG, categories: [..]}
                            -> {ok, suggestion: {name, category, weight_g, qty, note, confidence}}

The website's gear page (functions/gear/api/[[route]].js in the TheCreatorsClub
repo) forwards a phone photo here, through the `dash-auth` tunnel and its
Cloudflare Access service token, with `X-Gear-Token`. The answer comes from
the Claude Code CLI already signed in on this host (the same binary
`ai_providers.cli_path` finds for Timeline Cards) -- never the API.

ONE HOT CLI, AN HOUR AT A TIME (2026-10-11, the owner's spec): the first photo
starts `claude -p` in stream-json mode and later photos are further turns of
the same process, so they skip the start-up (measured on the base rig: 5.7 s
cold, 1.8 s warm). It is closed an hour after the LAST photo, by a timer
thread, and the next photo starts a fresh one. It is also recycled after
MAX_TURNS photos, so a busy packing day never grows one conversation without
bound. One photo at a time (a lock): a stream-json session is one
conversation, and two phones' photos interleaved in it would cross answers.

The CLI gets no tools (`--tools ""`), no session persistence, and the data
root's gear scratch dir as its working directory, like cards_ai's runner.

Auth: this route is outside the session login (the website is not a browser
with a dashboard cookie). `login_gate` lets it through only with the right
`X-Gear-Token`, and the route checks it again. The token is not a new secret
to plumb through the installer: it is HMAC-SHA256(DASH_SESSION_SECRET,
"gear-identify"), so rotating the session secret rotates it too, and the
website's GEAR_IDENTIFY_TOKEN must then be set to the new value
(`python -m ccsync_dashboard.gear_ai --token` prints it from the environment).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from . import ai_providers, api, cli_tools, db as dbmod

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")

PATH = "/api/v1/gear/identify"
IDLE_SECONDS = 3600.0
MAX_TURNS = 40
TURN_TIMEOUT = 120.0
MAX_IMAGE_B64 = 2_800_000
MODEL = os.environ.get("DASH_GEAR_MODEL", "opus")

SYSTEM = (
    "You identify film and video production gear from phone photos taken while "
    "packing for a trip, for a shared packing list. Every message is a NEW photo: "
    "describe only that photo, never an earlier one. If several different things "
    "are in it, describe the main one. Reply with ONE JSON object and nothing else, "
    "with exactly these keys: "
    '"name" (short list name: brand and model when identifiable, else a plain '
    'description, e.g. "Sennheiser locking 3.5mm to 3.5mm cable"), '
    '"category" (one of the categories given, or a new short one if none fits), '
    '"weight_g" (integer estimate of ONE unit in grams, the published spec if you '
    'know it, 0 if no sensible estimate), '
    '"qty" (integer, how many identical units are in the photo, at least 1), '
    '"note" (one short line a packer would find useful: connectors, capacity, '
    'size; "" if nothing useful), '
    '"confidence" ("high", "medium" or "low").'
)


def token_for(session_secret: str) -> str:
    """The gear token both ends derive from DASH_SESSION_SECRET."""
    if not session_secret:
        return ""
    return hmac.new(session_secret.encode("utf-8"), b"gear-identify", hashlib.sha256).hexdigest()


def token_ok(settings: Any, presented: str) -> bool:
    expected = token_for(str(getattr(settings, "session_secret", "") or ""))
    return bool(expected) and api.token_ok(expected, presented or "")


class GearError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class HotClaude:
    """One `claude -p` stream-json process, kept for IDLE_SECONDS after its last use."""

    def __init__(self, argv_fn, env_fn, cwd_fn, idle: float = IDLE_SECONDS,
                 max_turns: int = MAX_TURNS, clock=time.monotonic):
        self._argv_fn, self._env_fn, self._cwd_fn = argv_fn, env_fn, cwd_fn
        self._idle, self._max_turns, self._clock = idle, max_turns, clock
        self._lock = threading.Lock()          # one photo at a time
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue | None = None
        self._turns = 0
        self._last = 0.0
        self._reaper: threading.Thread | None = None
        self._stop_reaper = threading.Event()

    # -- process lifetime --------------------------------------------------
    def _start(self) -> None:
        argv = self._argv_fn()
        self._proc = subprocess.Popen(  # noqa: S603 - argv, never a shell
            argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", env=self._env_fn(), cwd=str(self._cwd_fn()), bufsize=1)
        self._lines = queue.Queue()
        out, lines = self._proc.stdout, self._lines

        def pump():
            for line in out:
                lines.put(line)
            lines.put(None)                    # EOF
        threading.Thread(target=pump, name="gear-claude-stdout", daemon=True).start()
        self._turns = 0
        log.info("gear identify: Claude Code started (pid %s)", self._proc.pid)
        if self._reaper is None or not self._reaper.is_alive():
            self._stop_reaper.clear()
            self._reaper = threading.Thread(target=self._reap, name="gear-claude-idle", daemon=True)
            self._reaper.start()

    def _close(self, why: str) -> None:
        proc, self._proc, self._lines = self._proc, None, None
        if proc is None:
            return
        try:
            proc.stdin.close()
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001 - closing is best effort
            proc.kill()
        log.info("gear identify: Claude Code closed (%s)", why)

    def _reap(self) -> None:
        while not self._stop_reaper.wait(30.0):
            if self.close_if_idle() or self._proc is None:
                return

    def close_if_idle(self) -> bool:
        """Close the CLI if nobody has sent a photo for IDLE_SECONDS; True if it did."""
        with self._lock:
            if self._proc is not None and self._clock() - self._last >= self._idle:
                self._close("an hour with no photo")
                return True
            return False

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def shutdown(self) -> None:
        with self._lock:
            self._stop_reaper.set()
            self._close("dashboard stopping")

    # -- one photo ----------------------------------------------------------
    def ask(self, content: list, timeout: float = TURN_TIMEOUT) -> str:
        with self._lock:
            self._last = self._clock()
            if self.running() and self._turns >= self._max_turns:
                self._close(f"{self._max_turns} photos in one session")
            if not self.running():
                self._close("not running")
                self._start()
            msg = {"type": "user", "message": {"role": "user", "content": content}}
            try:
                self._proc.stdin.write(json.dumps(msg) + "\n")
                self._proc.stdin.flush()
            except (OSError, ValueError):
                self._close("stdin closed")
                raise GearError(502, "Claude Code stopped; try again")
            self._turns += 1
            deadline = time.monotonic() + timeout
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    self._close("no answer in time")
                    raise GearError(504, f"Claude Code did not answer within {timeout:.0f}s")
                try:
                    line = self._lines.get(timeout=left)
                except queue.Empty:
                    continue
                if line is None:
                    self._close("exited")
                    raise GearError(502, "Claude Code exited (is it signed in on the NAS?)")
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("type") != "result":
                    continue
                self._last = self._clock()
                if ev.get("is_error") or ev.get("subtype") != "success":
                    raise GearError(502, "Claude Code: " + str(ev.get("result") or ev.get("subtype"))[:200])
                return str(ev.get("result") or "")


def parse_suggestion(text: str) -> dict:
    """The reply's JSON object, tidied; a reply wrapped in ``` fences still parses."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise GearError(502, "Claude gave no suggestion")
    try:
        s = json.loads(m.group(0))
    except ValueError:
        raise GearError(502, "Claude gave an unexpected answer") from None
    if not isinstance(s, dict) or not str(s.get("name") or "").strip():
        raise GearError(502, "Claude gave no name")

    def num(v, lo, hi, default):
        try:
            return max(lo, min(hi, int(round(float(v)))))
        except (TypeError, ValueError):
            return default
    conf = str(s.get("confidence") or "").lower()
    return {
        "name": str(s["name"]).strip()[:80],
        "category": str(s.get("category") or "").strip()[:40],
        "weight_g": num(s.get("weight_g"), 0, 999_999, 0),
        "qty": num(s.get("qty"), 1, 99, 1),
        "note": str(s.get("note") or "").strip()[:200],
        "confidence": conf if conf in ("high", "medium", "low") else "low",
    }


def _scratch(settings: Any) -> Path:
    root = Path(str(getattr(settings, "db_path", "") or ".")).parent / "gear"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError:
        return Path(".")
    return root


def _cli_path(settings: Any) -> str:
    conn = dbmod.connect(settings.db_path)
    try:
        return ai_providers.cli_path(conn, ai_providers.CLAUDE_CODE, settings)
    finally:
        conn.close()


_hot: HotClaude | None = None
_hot_lock = threading.Lock()


def hot_for(settings: Any) -> HotClaude:
    global _hot
    with _hot_lock:
        if _hot is None:
            def argv():
                path = _cli_path(settings)
                if not path:
                    raise GearError(503, "Claude Code is not installed on the NAS (Settings -> AI providers)")
                return [path, "-p", "--input-format", "stream-json", "--output-format", "stream-json",
                        "--verbose", "--tools", "", "--no-session-persistence",
                        "--model", MODEL, "--system-prompt", SYSTEM]
            _hot = HotClaude(argv, lambda: cli_tools.cli_env(settings, ai_providers.CLAUDE_CODE),
                             lambda: _scratch(settings))
        return _hot


def shutdown() -> None:
    if _hot is not None:
        _hot.shutdown()


@router.post("/gear/identify")
async def gear_identify(request: Request):
    settings = request.app.state.settings
    if not token_ok(settings, request.headers.get("x-gear-token", "")):
        return JSONResponse({"ok": False, "err": "bad gear token"}, status_code=401)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = None
    image = body.get("image") if isinstance(body, dict) else None
    if not isinstance(image, str) or not image or len(image) > MAX_IMAGE_B64:
        return JSONResponse({"ok": False, "err": "a JPEG image (base64, under 2 MB) is required"}, status_code=400)
    image = re.sub(r"^data:image/\w+;base64,", "", image)
    cats = [str(c)[:40] for c in (body.get("categories") or []) if str(c).strip()][:40]
    text = "New photo." + (" Categories in use: " + ", ".join(cats) + "." if cats else "")
    content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image}},
               {"type": "text", "text": text}]
    from starlette.concurrency import run_in_threadpool
    try:
        reply = await run_in_threadpool(hot_for(settings).ask, content)
        return {"ok": True, "suggestion": parse_suggestion(reply)}
    except GearError as e:
        return JSONResponse({"ok": False, "err": str(e)}, status_code=e.status)
    except OSError as e:
        return JSONResponse({"ok": False, "err": f"could not run Claude Code ({type(e).__name__})"}, status_code=502)


if __name__ == "__main__":  # pragma: no cover - operator helper
    import sys
    if "--token" in sys.argv:
        print(token_for(os.environ.get("DASH_SESSION_SECRET", "")))
