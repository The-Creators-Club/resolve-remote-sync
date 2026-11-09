"""Serve the Footage Sorter from inside the dashboard, at /sorter.

footage-sorter's docs/DASHBOARD-MODULE-PLAN.md. Mounted the way /cards is
(cards.py): the code is ANOTHER REPO'S CHECKOUT (`footage_sorter`, shipped to
`<apps>/sorter-web` and mounted /sorter-app:ro by install_dashboard_app.py),
appended to sys.path here, in-process, behind login_gate, tri-state, and
never fatal. An editor gets one URL and one login.

What it needs that nothing else here mounts: the footage POOL, one mount of
the whole dataset (`/pool`), so that Temp Transfer -> Projects is a rename
on one filesystem. Two bind mounts of the same dataset would make every move
fail with EXDEV. Plus its own writable state (`/sorter-data`).

THE GATE (SorterGate) does three things:

1. Re-stamps WHO is asking. Any inbound X-Sorter-User / X-Sorter-Admin is
   STRIPPED, and the real ones are set from the session login_gate already
   resolved. The sorter trusts those headers for two decisions with
   consequences: who may execute a move (admins only), and whose name goes
   into the manifest's ops journal. YtdlGate's rule, for its reason.
2. Answers `/sorter/api/whoami` itself: the user, whether they are an admin,
   and the session's CSRF token. The page sends that token on every write,
   so /sorter is an ordinary session route with full CSRF protection, not an
   exemption.
3. Holds a request until the engine has loaded. It loads in a thread at
   boot; reading 55 MB of clips and catalog takes a few seconds, and the
   dashboard must not wait for it.

MOVES INSIDE PROJECTS go through api.move_project_files (``_inside_mover``):
a clip moved on the server alone would be re-uploaded to its old folder by
every editor's lane A (docs/FILE_MOVES.md). Moves INTO Projects from Temp
Transfer are plain renames by the sorter: no editor holds Temp Transfer.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request

from . import mount_status
from .settings import Settings

log = logging.getLogger("ccsync.dashboard.sorter")

MOUNT_PATH = "/sorter"
MOUNTED = "mounted"
ABSENT = "absent"
DISABLED = "disabled"

USER_HEADER = b"x-sorter-user"
ADMIN_HEADER = b"x-sorter-admin"
LOAD_WAIT_S = 120.0


def checkout_src(settings: Settings | None) -> str:
    """DASH_SORTER_SRC (the deployment's), or SORTER_SRC (dev and tests, and taken as consent)."""
    configured = str(getattr(settings, "sorter_src", "") or "").strip()
    return configured or os.environ.get("SORTER_SRC", "").strip()


def enabled(settings: Settings | None) -> bool:
    return bool(getattr(settings, "sorter_enabled", False)) or bool(os.environ.get("SORTER_SRC", "").strip())


def host_settings(settings: Settings) -> dict:
    """DASH_SORTER_SETTINGS: what the CONTAINER knows (roots under /pool, ffmpeg, the legacy id table)."""
    raw = str(getattr(settings, "sorter_settings", "") or "").strip()
    if not raw:
        return {}
    try:
        val = json.loads(raw)
    except ValueError as e:
        raise ValueError(f"DASH_SORTER_SETTINGS is not JSON ({e})") from e
    if not isinstance(val, dict):
        raise ValueError("DASH_SORTER_SETTINGS must be a JSON object")
    return val


def _add_to_path(src: str) -> None:
    """APPENDED, never prepended (cards.py's rule): a configured PYTHONPATH keeps winning."""
    if src and src not in sys.path:
        sys.path.append(src)


# ------------------------------------------------------------------ identity

def _identity(scope: dict, settings: Settings) -> tuple[str | None, bool, str]:
    """(user, admin, csrf) by login_gate's own answer for this request."""
    from starlette.requests import Request

    from . import auth
    try:
        req = Request(scope)
        user = auth.get_session_user(req)
    except Exception:  # noqa: BLE001 - fail closed: nobody
        return None, False, ""
    if not user:
        return None, False, ""
    try:
        admin = bool(auth.is_admin(settings, user))
    except Exception:  # noqa: BLE001 - fail closed: not an admin
        admin = False
    try:
        csrf = auth.csrf_token(req)
    except Exception:  # noqa: BLE001
        csrf = ""
    return user, admin, csrf


def _latin1(s: str) -> bytes | None:
    try:
        return s.encode("latin-1")
    except UnicodeEncodeError:
        return None


async def _json(send: Callable, status: int, body: dict) -> None:
    payload = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode()),
                            (b"cache-control", b"no-store")]})
    await send({"type": "http.response.body", "body": payload})


class SorterGate:
    """Identity in, whoami answered, and the engine waited for (see the module docstring)."""

    def __init__(self, holder: "_Holder", settings: Settings) -> None:
        self.holder = holder
        self.settings = settings

    def _sub(self, scope: dict) -> str:
        path = scope.get("path", "")
        root = scope.get("root_path", "")
        if root and path.startswith(root):
            return path[len(root):] or "/"
        if path.startswith(MOUNT_PATH):
            return path[len(MOUNT_PATH):] or "/"
        return path

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            app = self.holder.app
            if app is not None:
                await app(scope, receive, send)
            return
        sub = self._sub(scope)
        if scope.get("path", "") == MOUNT_PATH:
            # the page's URLs are document-relative: at /sorter they would resolve against /, not /sorter/
            await send({"type": "http.response.start", "status": 307,
                        "headers": [(b"location", (MOUNT_PATH + "/").encode()), (b"content-length", b"0")]})
            await send({"type": "http.response.body", "body": b""})
            return
        user, admin, csrf = _identity(scope, self.settings)
        if sub.rstrip("/") == "/api/whoami":
            await _json(send, 200, {"user": user, "admin": admin, "csrf": csrf})
            return
        if self.holder.app is None:
            # Waits on an event-loop Event, never a thread: a held request must not use one of anyio's 40
            # shared worker threads, or a page opening during the load would starve the dashboard's sync routes.
            ready = await self.holder.wait_async(LOAD_WAIT_S)
            if not ready or self.holder.app is None:
                if self.holder.error:      # the boot may have recorded "mounted" after the load failed: say it again
                    mount_status.record("sorter", ABSENT, self.holder.error)
                await _json(send, 503, {"error": self.holder.error or "the footage sorter is still loading: try again in a moment"})
                return
        headers = [(k, v) for k, v in scope.get("headers", ()) if k.lower() not in (USER_HEADER, ADMIN_HEADER)]
        if user:
            enc = _latin1(user)
            if enc is not None:
                headers.append((USER_HEADER, enc))
                headers.append((ADMIN_HEADER, b"1" if admin else b"0"))
            else:
                log.warning("sorter identity header not minted for %r: not latin-1", user)
        scope = dict(scope, headers=headers)
        await self.holder.app(scope, receive, send)


class _Holder:
    def __init__(self) -> None:
        self.app: Any = None
        self.engine: Any = None
        self.error: str | None = None
        self.ready = threading.Event()
        self.stopped = False                      # stop_sorter ran: a load still in flight must not start anything
        self.lock = threading.Lock()
        self._waiters: list[tuple[Any, Any]] = []   # (loop, asyncio.Event) of the requests being held

    def finish(self) -> None:
        """The load is over (loaded or failed): release every held request. Callable from any thread."""
        with self.lock:
            self.ready.set()
            waiters, self._waiters = self._waiters, []
        for loop, ev in waiters:
            try:
                loop.call_soon_threadsafe(ev.set)
            except RuntimeError:      # that loop is closed; nobody is waiting on it
                pass

    async def wait_async(self, timeout: float) -> bool:
        import asyncio
        with self.lock:
            if self.ready.is_set():
                return True
            ev = asyncio.Event()
            self._waiters.append((asyncio.get_running_loop(), ev))
        try:
            await asyncio.wait_for(ev.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            with self.lock:
                self._waiters = [w for w in self._waiters if w[1] is not ev]


# ------------------------------------------------------------------ moves inside Projects

def _inside_mover(settings: Settings, dest_root: str) -> Callable[[str, str, str], dict]:
    """A move whose source is inside Projects, through the dashboard's own file move (its companions follow)."""
    from fastapi import HTTPException

    from . import api, db

    def move(src: str, dst: str, user: str) -> dict:
        rel_src = os.path.relpath(src, dest_root).replace(os.sep, "/")
        rel_dst = os.path.relpath(dst, dest_root).replace(os.sep, "/")
        conn = db.connect(settings.db_path)
        try:
            rows = conn.execute("SELECT slug, label FROM projects WHERE active=1").fetchall()

            def owner(rel: str) -> tuple[str, str]:
                best = None
                for r in rows:
                    label = str(r["label"]).strip("/")
                    if rel == label or rel.startswith(label + "/"):
                        if best is None or len(label) > len(best[1]):
                            best = (str(r["slug"]), label)
                if best is None:
                    raise RuntimeError(f"{rel} is in no CC Sync project, so no editor's copy can follow it")
                return best
            from_slug, from_label = owner(rel_src)
            to_slug, to_label = owner(rel_dst)
            body = api.FileMoveIn(path=rel_src[len(from_label) + 1:], to_slug=to_slug,
                                  to_path=rel_dst[len(to_label) + 1:])
            try:
                return api.move_project_files(settings, conn, from_slug, body, user or "sorter")
            except HTTPException as e:
                raise RuntimeError(str(e.detail)) from None
        finally:
            conn.close()
    return move


# ------------------------------------------------------------------ card ingest (the companion's)
#
# footage-sorter docs/DASHBOARD-MODULE-PLAN.md, "Card ingest through the
# companion: the protocol". A card is in a reader on a PC; only that PC's
# companion can read it, and only the sorter knows where its clips go. So:
#
#   POST /sorter/agent/cards   the companion's full set of cards, on the fleet
#                              credential (cards_tunnel's posture: no session,
#                              no CSRF, the VERIFIED editor, never the body's)
#   card-ingest fleet job      queued by the sorter when someone presses Copy,
#                              FORCED (a person is standing at that card) and
#                              TARGETED at "<editor>/<machine>" that reported it
#
# The sorter reads the finished job's receipt back through `_job_hooks`.

MAX_CARDS_REPORT_BYTES = 8 * 1024 * 1024
MAX_CARDS_PER_REPORT = 16
agent_router = APIRouter(prefix="/sorter/agent")


@agent_router.post("/cards")
def sorter_agent_cards(payload: dict[str, Any], request: Request) -> dict:
    from . import api, db
    conn = db.connect(request.app.state.settings.db_path)
    try:
        editor = api._require_fleet_caller(request, conn)
    finally:
        conn.close()
    engine = getattr(request.app.state, "sorter_engine", None)
    if engine is None:
        # 503, which the companion reads as "this site has no sorter (yet)" and backs off
        raise HTTPException(503, "the Footage Sorter is not running on this dashboard")
    machine = str((payload or {}).get("machine") or "").strip()[:128]
    cards = (payload or {}).get("cards")
    if not machine or not isinstance(cards, list):
        raise HTTPException(422, "expected {machine, cards: [...]}")
    if len(cards) > MAX_CARDS_PER_REPORT:
        raise HTTPException(413, f"at most {MAX_CARDS_PER_REPORT} cards in one report")
    try:
        return engine.ingest.report(editor, machine, cards)
    except ValueError as e:
        raise HTTPException(413, str(e)) from None


# The two calls a companion makes for a claimed card-ingest job. The copy list
# and the receipt travel here, not in the job row: db._job_json caps a row's
# JSON at 16 KB and replaces anything bigger with {}, and one card's list is
# hundreds of files. Only the editor whose machine CLAIMED the job may read the
# list or file the receipt (the verified identity, never the body's).
AGENT_PATH_RE = (r"^/sorter/agent/(cards|volumes|ingest/\d+(/(receipt|progress))?"
                 r"|ledger/(scan/\d+(/(chunk|finish|progress))?|copies|mirror))$")

COPY_JOB_KINDS = ("card-ingest", "drive-copy")
SCAN_JOB_KINDS = ("ledger-scan",)


def _claimed_job(request: Request, job_id: int, barred: str = "allow",
                 kinds: tuple[str, ...] = COPY_JOB_KINDS) -> tuple[Any, str]:
    from . import api, db
    conn = db.connect(request.app.state.settings.db_path)
    try:
        editor = api._require_fleet_caller(request, conn, barred=barred)
        job = db.get_job(conn, int(job_id))
    finally:
        conn.close()
    if not job or job.get("kind") not in kinds:
        raise HTTPException(404, "no such scan job" if kinds == SCAN_JOB_KINDS else "no such card copy job")
    if str(job.get("claimed_by") or "").lower() != editor.lower():
        raise HTTPException(409, "this job is not claimed by you")
    engine = getattr(request.app.state, "sorter_engine", None)
    if engine is None:
        raise HTTPException(503, "the Footage Sorter is not running on this dashboard")
    return engine, editor


@agent_router.get("/ingest/{job_id}")
def sorter_agent_ingest_manifest(job_id: int, request: Request) -> dict:
    # "gone": a suspended account's companion reads the 410 as "this job is not yours, stop"; the receipt
    # door stays "allow", it only retires work already claimed
    engine, _editor = _claimed_job(request, job_id, barred="gone")
    try:
        return engine.ingest.manifest_for(job_id)
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    except ValueError as e:
        raise HTTPException(409, str(e)) from None


@agent_router.post("/ingest/{job_id}/receipt")
def sorter_agent_ingest_receipt(job_id: int, payload: dict[str, Any], request: Request) -> dict:
    engine, editor = _claimed_job(request, job_id)
    try:
        out = engine.ingest.receipt(job_id, payload)
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    log.info("sorter: job #%s receipt from %s: %s", job_id, editor, out)
    return out


@agent_router.post("/ingest/{job_id}/progress")
def sorter_agent_ingest_progress(job_id: int, payload: dict[str, Any], request: Request) -> dict:
    """Live progress while the companion copies (about every 2 s). Same door as the receipt: only the editor
    whose machine claimed the job. It is stored for the browser and touches nothing else."""
    engine, _editor = _claimed_job(request, job_id)
    try:
        return engine.ingest.progress(job_id, payload)
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


# ------------------------------------------------------------------ the ledger (the companion's half)
#
# footage-sorter docs/LEDGER-BROWSER-DESIGN.md. The NAS holds the ledger; a
# companion tells it which volumes this machine can see, walks the roots of a
# drive on request (a `ledger-scan` fleet job), and files each verified copy it
# makes. All of these are the card routes' door: fleet token + signed identity,
# no session, no CSRF (app.py's regexes), and a job-bound call is the CLAIMANT's.
# The logic is the sorter's (`engine.ledger`); these routes only authenticate,
# bound the body, and translate its ValueError / LookupError into 422 / 404.

MAX_VOLUMES_REPORT_BYTES = 1 * 1024 * 1024
MAX_VOLUMES_PER_REPORT = 64
MAX_LEDGER_COPIES_BYTES = 4 * 1024 * 1024
MAX_LEDGER_COPIES_PER_POST = 5000
# A scan chunk is 5,000 rows of [path, size, mtimeMs]: about 1 MB of JSON, 150 KB gzipped.
# The wire cap is the COMPRESSED size (app.py's body gate); the decompressed cap is ours,
# and is what stops a few KB of zeros from becoming a gigabyte (a gzip bomb).
MAX_LEDGER_CHUNK_BYTES = 4 * 1024 * 1024
# 5,000 rows of [path, size, mtimeMs] is ~0.6 MB; 10,000 long paths ~3 MB. A bigger cap only buys a
# hostile body more heap (json.loads of dense `{},` costs ~25x its size), so it is not bigger.
MAX_LEDGER_CHUNK_DECOMPRESSED = 3 * 1024 * 1024
MAX_LEDGER_CHUNK_ROWS = 10000          # the ledger's own cap (5,000 is what a companion sends)
LEDGER_CHUNK_PATH_RE = r"^/sorter/agent/ledger/scan/\d+/chunk$"


def _ledger(request: Request) -> Any:
    engine = getattr(request.app.state, "sorter_engine", None)
    ledger = getattr(engine, "ledger", None) if engine is not None else None
    if ledger is None:
        raise HTTPException(503, "the Footage Sorter's ledger is not running on this dashboard")
    return ledger


def _fleet_editor(request: Request, barred: str = "allow") -> str:
    from . import api, db
    conn = db.connect(request.app.state.settings.db_path)
    try:
        return api._require_fleet_caller(request, conn, barred=barred)
    finally:
        conn.close()


def _ledger_call(fn: Callable[..., Any], *args: Any, **kw: Any) -> Any:
    """Run an engine.ledger method; its errors are the caller's, not a 500.

    LookupError (no such scan) is 404; `LedgerGone` (the scan is finished or abandoned: stop) is 409,
    like the card list's "already finished"; any other ValueError is a bad request, 422. LedgerGone
    subclasses ValueError and lives in the sorter's repo, so it is told by name."""
    try:
        return fn(*args, **kw)
    except LookupError as e:
        raise HTTPException(404, str(e)) from None
    except ValueError as e:
        if any(c.__name__ == "LedgerGone" for c in type(e).__mro__):
            raise HTTPException(409, str(e)) from None
        raise HTTPException(422, str(e)) from None


def _serial_only(copies: list) -> list:
    """A fleet caller names a volume by its SERIAL and nothing else: an `id` would let any companion
    file copies onto `nas:thecreatorspool` or `cloud:hetzner`, and a `kind` would let it decide what
    counts as a backup. The ledger ignores both from a fleet caller; they are dropped here as well,
    so it is true however the ledger is configured."""
    out = []
    for c in copies:
        if isinstance(c, dict) and isinstance(c.get("volume"), dict):
            c = {**c, "volume": {k: v for k, v in c["volume"].items() if k not in ("id", "kind")}}
        out.append(c)
    return out


def _takes_attempt(fn: Callable[..., Any]) -> bool:
    import inspect
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return "attempt" in params or any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def decode_chunk_body(raw: bytes, encoding: str) -> dict:
    """A scan chunk's body -> its JSON object. gzip (`Content-Encoding: gzip`) or plain, both bounded.

    The decompressed size is capped as it is produced (zlib's max_length), so a bomb is refused at the
    cap, not after it has been inflated. HTTPException 400 (not gzip / not JSON), 413 (too large)."""
    import zlib
    enc = (encoding or "").strip().lower()
    if enc in ("gzip", "x-gzip"):
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            data = d.decompress(raw, MAX_LEDGER_CHUNK_DECOMPRESSED + 1)
        except zlib.error:
            raise HTTPException(400, "the chunk is not valid gzip") from None
        if len(data) > MAX_LEDGER_CHUNK_DECOMPRESSED:
            raise HTTPException(413, f"a chunk may be at most {MAX_LEDGER_CHUNK_DECOMPRESSED // (1024 * 1024)} MB decompressed")
        if not d.eof:
            raise HTTPException(400, "the chunk's gzip stream is truncated")
    elif enc in ("", "identity"):
        data = raw
        if len(data) > MAX_LEDGER_CHUNK_DECOMPRESSED:
            raise HTTPException(413, "the chunk is too large")
    else:
        raise HTTPException(415, f"unsupported Content-Encoding {enc!r}")
    try:
        body = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise HTTPException(400, "the chunk is not JSON") from None
    if not isinstance(body, dict):
        raise HTTPException(422, "expected {rows: [...], seq}")
    return body


@agent_router.post("/volumes")
def sorter_agent_volumes(payload: dict[str, Any], request: Request) -> dict:
    """This machine's volumes (drives, cards, the fixed D:), on change and every five minutes.
    Answers {scan: [{volumeId, roots, jobId}]}: what the ledger wants scanned now."""
    editor = _fleet_editor(request)
    ledger = _ledger(request)
    machine = str((payload or {}).get("machine") or "").strip()[:128]
    volumes = (payload or {}).get("volumes")
    if not machine or not isinstance(volumes, list):
        raise HTTPException(422, "expected {machine, volumes: [...], digest}")
    if len(volumes) > MAX_VOLUMES_PER_REPORT:
        raise HTTPException(413, f"at most {MAX_VOLUMES_PER_REPORT} volumes in one report")
    return _ledger_call(ledger.report_volumes, editor, machine, volumes, str((payload or {}).get("digest") or "")[:128])


@agent_router.get("/ledger/scan/{job_id}")
def sorter_agent_scan_manifest(job_id: int, request: Request) -> dict:
    # "gone" like the card list: a suspended account's companion reads 410 as "stop"
    _claimed_job(request, job_id, barred="gone", kinds=SCAN_JOB_KINDS)
    return _ledger_call(_ledger(request).scan_manifest, job_id)


@agent_router.post("/ledger/scan/{job_id}/chunk")
async def sorter_agent_scan_chunk(job_id: int, request: Request) -> dict:
    from starlette.concurrency import run_in_threadpool
    raw = await request.body()
    encoding = request.headers.get("content-encoding", "")

    def work() -> dict:
        _claimed_job(request, job_id, kinds=SCAN_JOB_KINDS)          # before a byte of it is inflated
        body = decode_chunk_body(raw, encoding)
        rows = body.get("rows")
        seq = body.get("seq")
        if not isinstance(rows, list) or isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
            raise HTTPException(422, "expected {rows: [...], seq: n}")
        if len(rows) > MAX_LEDGER_CHUNK_ROWS:
            raise HTTPException(413, f"at most {MAX_LEDGER_CHUNK_ROWS} rows in one chunk")
        ledger = _ledger(request)
        # the scan attempt this chunk belongs to (the manifest hands it out; a reclaimed job gets a
        # new one, so a stale companion's chunks are refused): handed on when the ledger takes one
        attempt = body.get("attempt")
        if attempt is not None and _takes_attempt(ledger.scan_chunk):
            return _ledger_call(ledger.scan_chunk, job_id, seq, rows, attempt=attempt)
        return _ledger_call(ledger.scan_chunk, job_id, seq, rows)

    return await run_in_threadpool(work)


@agent_router.post("/ledger/scan/{job_id}/finish")
def sorter_agent_scan_finish(job_id: int, payload: dict[str, Any], request: Request) -> dict:
    _claimed_job(request, job_id, kinds=SCAN_JOB_KINDS)
    return _ledger_call(_ledger(request).scan_finish, job_id, payload or {})


@agent_router.post("/ledger/scan/{job_id}/progress")
def sorter_agent_scan_progress(job_id: int, payload: dict[str, Any], request: Request) -> dict:
    _claimed_job(request, job_id, kinds=SCAN_JOB_KINDS)
    return _ledger_call(_ledger(request).scan_progress, job_id, payload or {})


@agent_router.post("/ledger/copies")
def sorter_agent_ledger_copies(payload: dict[str, Any], request: Request) -> dict:
    """Verified copies a companion made (a field copy's outbox, a drive copy). Idempotent on
    volume + path + size + mtime, so a re-sent outbox is harmless. Answers {accepted, duplicates}."""
    editor = _fleet_editor(request)
    ledger = _ledger(request)
    copies = (payload or {}).get("copies")
    if not isinstance(copies, list):
        raise HTTPException(422, "expected {copies: [...]}")
    if len(copies) > MAX_LEDGER_COPIES_PER_POST:
        raise HTTPException(413, f"at most {MAX_LEDGER_COPIES_PER_POST} copies in one post")
    machine = str((payload or {}).get("machine") or "").strip()[:128]
    return _ledger_call(ledger.record_copies, machine, _serial_only(copies), editor=editor)


@agent_router.get("/ledger/mirror")
def sorter_agent_ledger_mirror(request: Request, volumes: str = "", since: str = "", limit: int = 5000) -> dict:
    """The ledger's copies for these volume ids, changed since the cursor ("seq:id", as the last answer
    gave it), for the field page. Answers {cols, rows, cursor, more, volumes}; while `more`, ask again."""
    _fleet_editor(request, barred="gone")
    ids = [v.strip() for v in volumes.split(",") if v.strip()][:MAX_VOLUMES_PER_REPORT]
    return _ledger_call(_ledger(request).mirror, ids, since.strip()[:64] or 0, max(1, min(int(limit), 20000)))


def _job_hooks(settings: Settings, engine: Any) -> None:
    """Plug the dashboard's fleet job queue into the sorter's ingest service."""
    from . import db

    def submit_job(kind: str, inputs: dict, requires: dict, target_machine: str, user: str, editor: str = "") -> int:
        # the session's own editor, passed by the sorter: two editors may both have a machine called LAPTOP
        target = f"{editor}/{target_machine}" if editor else target_machine
        conn = db.connect(settings.db_path)
        try:
            job_id = db.create_job(conn, kind, inputs, requires, created_by=f"sorter:{user or 'unknown'}",
                                   priority=5, forced=True, target_machine=target)
            conn.commit()
        finally:
            conn.close()
        log.info("sorter: job #%s (%s, %d files) queued for %s by %s", job_id, kind, len(inputs.get("copies") or []), target, user)
        return job_id

    def job_status(job_id: int) -> dict | None:
        conn = db.connect(settings.db_path)
        try:
            j = db.get_job(conn, int(job_id))
        finally:
            conn.close()
        if not j:
            return {"state": "abandoned", "error": "the job is gone from the queue"}
        return {"state": j.get("state"), "progress": j.get("progress"), "result": j.get("result"),
                "error": j.get("last_error") or None}

    def cancel_job(job_id: int) -> None:
        conn = db.connect(settings.db_path)
        try:
            db.request_job_cancel(conn, int(job_id), "sorter")
            conn.commit()
        finally:
            conn.close()

    engine.ingest.submit_job, engine.ingest.job_status, engine.ingest.cancel_job = submit_job, job_status, cancel_job


# ------------------------------------------------------------------ mount

def mount_sorter(app: FastAPI, settings: Settings) -> tuple[str, str]:
    """Mount the sorter at /sorter. -> (status, detail). NEVER RAISES."""
    app.state.sorter_engine = None
    if not enabled(settings):
        return DISABLED, "DASH_SORTER_ENABLED is not 1"
    src = checkout_src(settings)
    if not src:
        return DISABLED, "no footage-sorter checkout is configured (DASH_SORTER_SRC)"
    if not Path(src).is_dir():
        log.warning("Footage Sorter NOT mounted: %s is not a directory", src)
        return ABSENT, f"the configured checkout is not there ({src})"
    data_dir = str(getattr(settings, "sorter_data", "") or "").strip()
    if not data_dir:
        return DISABLED, "no data folder is configured (DASH_SORTER_DATA)"
    try:
        hs = host_settings(settings)
    except ValueError as e:
        return ABSENT, str(e)
    # Where the dashboard is, for the OAuth callback Google redirects the browser to (the engine's
    # default would be its own loopback). An explicit publicUrl in DASH_SORTER_SETTINGS wins.
    public_url = str(getattr(settings, "site_dashboard_url", "") or "").strip().rstrip("/")
    if public_url and not str(hs.get("publicUrl") or "").strip():
        hs = dict(hs, publicUrl=public_url)
    for key in ("destRoot",):
        root = hs.get(key)
        if root and not Path(root).is_dir():
            log.warning("Footage Sorter NOT mounted: %s %s is not mounted", key, root)
            return ABSENT, f"the pool is not mounted here ({key} {root})"
    try:
        _add_to_path(src)
        config = importlib.import_module("footage_sorter.config")
        engine_mod = importlib.import_module("footage_sorter.engine")
        web = importlib.import_module("footage_sorter.web")
    except Exception as e:  # noqa: BLE001 - see the docstring
        log.warning("Footage Sorter not mounted (%s: %s); the dashboard continues without it", type(e).__name__, e)
        return ABSENT, f"the checkout did not import ({type(e).__name__}: {e})"

    holder = _Holder()
    cache_dir = str(getattr(settings, "sorter_cache", "") or "").strip() or os.path.join(data_dir, "cache")
    public = os.path.join(src, "public")

    def load() -> None:
        try:
            paths = config.Paths(data_dir, cache_dir, public)
            engine = engine_mod.SorterEngine(
                paths, hs, roots_locked=True,
                inside_mover=_inside_mover(settings, hs.get("destRoot") or "") if hs.get("destRoot") else None)
            engine.load()
            _job_hooks(settings, engine)
            with holder.lock:
                if holder.stopped:        # the app shut down while we were loading: start nothing
                    log.info("Footage Sorter load finished after shutdown; engine not started")
                    return
                engine.start()
                holder.engine = engine
                app.state.sorter_engine = engine
            holder.app = web.create_app(engine, trust_identity_headers=True)
            log.info("Footage Sorter loaded: %d clips, data %s", len(engine.clips), data_dir)
        except Exception as e:  # noqa: BLE001 - the page says so; the dashboard carries on
            holder.error = f"the footage sorter could not load its data ({type(e).__name__}: {e})"
            log.exception("Footage Sorter failed to load")
            # the mount was reported before the load ran: take it back, so the nav link hides
            # and the status page says why
            app.state.sorter_mounted = False
            app.state.sorter_status, app.state.sorter_detail = ABSENT, holder.error
            mount_status.record("sorter", ABSENT, holder.error)
        finally:
            holder.finish()

    threading.Thread(target=load, name="sorter-load", daemon=True).start()
    app.state.sorter_holder = holder
    if hs.get("destRoot"):
        mount_status.record_root("sorter", str(hs["destRoot"]))
    app.mount(MOUNT_PATH, SorterGate(holder, settings))
    log.info("Footage Sorter mounted at %s (from %s, data %s)", MOUNT_PATH, src, data_dir)
    return MOUNTED, f"serving {hs.get('destRoot') or data_dir}"


def stop_sorter(app: FastAPI) -> None:
    """Let the engine's threads go at app shutdown. Never raises."""
    holder = getattr(app.state, "sorter_holder", None)
    if holder is not None:
        with holder.lock:         # a load in flight sees this before it starts the engine
            holder.stopped = True
    engine = getattr(app.state, "sorter_engine", None)
    if engine is not None:
        try:
            engine.stop()
        except Exception:  # noqa: BLE001
            log.exception("the Footage Sorter engine did not stop cleanly")
    app.state.sorter_engine = None
