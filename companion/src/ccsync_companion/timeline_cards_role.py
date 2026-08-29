"""This machine's Resolve, serving the Timeline Cards page, from the tray app.

docs/TIMELINE-CARDS-INTO-CCSYNC.md phase 2 (2026-08-30). The standalone
`reorder_web.py --agent` becomes a thread here: same engine, same push/pull
loops, same edits -- a different connection and a different credential.

WHY IT MOVES AT ALL. `README.md` "On the NAS" already says "do not run this
PC's own reorder_web.py and the agent at the same time -- one Resolve client
at a time", and GOTCHAS §15 says one unguarded poller kills scripting for
every client on the machine for the rest of the Resolve session. The
companion is already a Resolve client on creator-1 and it is not going away,
so the agent cannot run BESIDE it. It has to be absorbed.

WHAT THIS FILE IS AND IS NOT. It is a shim: config, refusals, a thread, and
the credential swap. The engine is imported from the Timeline Cards checkout
(`jobs_mulcam_pipeline`), never copied -- decision 7.1, the same posture
`broll/web` and `music/web` already have. So a page fix over there stays a
`git pull` and not a fleet release, and the two suites stay where they are.

THE REFUSALS ARE THE FEATURE. Everything this can be wrong about ends with
two Resolve clients on one machine or an edit sent into the wrong timeline,
so every gate below fails towards NOT RUNNING and says why in a sentence the
diagnostics bundle carries:

  * `cards_agent` is off (the default, on every machine in the fleet);
  * no dashboard, no fleet token -- there is nothing to long-poll;
  * no MulticamPipeline checkout, or no vault root;
  * A STANDALONE AGENT IS ALREADY RUNNING HERE. Refuse, name it, and do NOT
    kill it: something a human started is something a human stops, and the
    old path keeps working until Alex flips the config (§6 "retire nothing
    yet"). Cannot tell counts as running -- a false refusal costs a page,
    a false start costs the scripting API;
  * the engine is older than the bridge contract (§7c). Named as a version,
    not discovered as an AttributeError in the middle of a conform.

THE HANDSHAKE HAS NEVER RUN LIVE. `release`/`reload` -- SaveProject,
CloseProject, LoadProject, SetCurrentTimeline -- are routed through the
bridge like any other edit, and TRUENAS-APP-PLAN.md §0 says twice that those
four calls have never been executed against a real project. Phase 2 does not
change that: run them on FF5lab from the CURRENT code first. Porting an
unexercised path and changing its host in the same week is the one thing §6
says not to do.
"""
from __future__ import annotations

import importlib
import inspect
import logging
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from . import timeline_cards_bridge

log = logging.getLogger("ccsync.cards")

# Why this machine is or is not serving the page, in the order _gate() asks.
STATE_DISABLED = "disabled"
STATE_NO_DASHBOARD = "no_dashboard"
STATE_HALTED = "halted"
STATE_NO_CHECKOUT = "no_checkout"
STATE_NO_VAULT = "no_vault"
STATE_STANDALONE_AGENT = "standalone_agent"
STATE_NO_ENGINE = "no_engine"
STATE_OLD_ENGINE = "old_engine"
STATE_RUNNING = "running"

# The engine's own long-poll ceiling (cards config AGENT_WAIT_S). The
# dashboard clamps to the same number.
AGENT_WAIT_SECONDS = 25.0
HTTP_TIMEOUT_SECONDS = 90.0
# How often the standalone-agent probe is re-run while the role is refusing.
# It shells out, so not per tick.
PROBE_CACHE_SECONDS = 60.0


class CardsRoleError(RuntimeError):
    """A refusal with a sentence in it. Never a traceback at the caller.

    It carries its own gate state: the caller must not have to guess which
    refusal this is by looking for a word in the message, which is how "no
    bridge contract at all" and "a contract from another version" became the
    same state during the build.
    """

    def __init__(self, message: str, state: str = STATE_NO_ENGINE) -> None:
        super().__init__(message)
        self.state = state


class CardsTunnelError(RuntimeError):
    """The dashboard answered something other than 200. The engine's loops
    treat every exception as "the network is down" and back off, which is the
    right response to all of these."""


# ----------------------------------------------------------------- the engine

def load_engine(checkout: str) -> Any:
    """-> (resolve_engine module, agent module) from `checkout`, or refuse.

    Imported, never copied (decision 7.1). The refusals name the path and the
    contract, because the two ways this fails on a real machine are "the
    checkout moved" and "the other repo has not landed §7c yet", and they
    need different people.
    """
    root = Path(str(checkout or "").strip())
    if not root.is_dir():
        raise CardsRoleError(
            f"no MulticamPipeline checkout at {root} "
            f"(set jobs_mulcam_pipeline in ~/.ccsync/config.toml)")
    if not (root / "multicam_pipeline" / "cards").is_dir():
        raise CardsRoleError(
            f"{root} is not a MulticamPipeline checkout "
            f"(no multicam_pipeline/cards in it)")
    path = str(root)
    if path not in sys.path:
        # Appended, never inserted at 0: this is somebody else's tree and it
        # must not be able to shadow a companion module by name.
        sys.path.append(path)
    try:
        engine_mod = importlib.import_module("multicam_pipeline.cards.resolve_engine")
        agent_mod = importlib.import_module("multicam_pipeline.cards.agent")
    except Exception as exc:                                   # noqa: BLE001
        raise CardsRoleError(
            f"the Timeline Cards engine at {root} could not be imported "
            f"({type(exc).__name__}: {exc})") from None
    check_contract(engine_mod)
    return engine_mod, agent_mod


def check_contract(engine_mod: Any) -> None:
    """Does this engine take a bridge? (§7c.)

    Two checks, because a version constant is a CLAIM: the constant says
    which contract the other repo thinks it implements, and the signature
    says whether it does. `REQUIRES_DASHBOARD` is the same idea between the
    companion and the dashboard, and it exists for the same reason -- the
    two halves ship on different days.
    """
    version = getattr(engine_mod, "BRIDGE_CONTRACT_VERSION", None)
    wanted = timeline_cards_bridge.CONTRACT_VERSION
    if version is None:
        raise CardsRoleError(
            "this Timeline Cards checkout has no bridge contract: its "
            "ResolveEngine still owns a Resolve connection of its own, which "
            "cannot run beside the companion's (CR-68). Update the checkout "
            "to one that defines BRIDGE_CONTRACT_VERSION = "
            f"{wanted} (docs/TIMELINE-CARDS-INTO-CCSYNC.md §7c)",
            STATE_NO_ENGINE)
    if int(version) != wanted:
        raise CardsRoleError(
            f"this Timeline Cards checkout implements bridge contract "
            f"{version} and this companion speaks {wanted} "
            f"(docs/TIMELINE-CARDS-INTO-CCSYNC.md §7c)", STATE_OLD_ENGINE)
    engine_cls = getattr(engine_mod, "SyncEngine", None) or getattr(
        engine_mod, "ResolveEngine", None)
    if engine_cls is None:
        raise CardsRoleError(
            "this Timeline Cards checkout has no SyncEngine/ResolveEngine")
    try:
        parameters = inspect.signature(engine_cls.__init__).parameters
    except (TypeError, ValueError):                            # pragma: no cover
        parameters = {}
    if "bridge" not in parameters:
        raise CardsRoleError(
            f"{engine_cls.__name__} says it speaks bridge contract {version} "
            f"but takes no `bridge` argument (§7c: SyncEngine(root, bridge=...))",
            STATE_OLD_ENGINE)


# ------------------------------------------------------- the standalone agent

# `reorder_web.py --agent` and `python -m multicam_pipeline ... --agent`, plus
# the PC's own `reorder_web.py 8800`, which is the other half of the same rule.
_AGENT_MARKERS = ("reorder_web.py", "multicam_pipeline")


def running_command_lines() -> Optional[list[str]]:
    """Every process command line on this machine, or None if we cannot tell.

    None is NOT "there is nothing running" -- see the fail-closed rule in
    `standalone_agent()`. Windows needs CIM for the command line (tasklist
    does not carry one); macOS has `ps -Ao command`.
    """
    system = platform.system()
    try:
        if system == "Windows":
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Get-CimInstance Win32_Process | "
                 "Select-Object -ExpandProperty CommandLine"],
                capture_output=True, text=True, timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        elif system == "Darwin":
            out = subprocess.run(["ps", "-Ao", "command"],
                                 capture_output=True, text=True, timeout=30)
        else:
            return None
    except Exception:
        log.debug("cards: could not list processes", exc_info=True)
        return None
    if out.returncode != 0 and not (out.stdout or "").strip():
        return None
    return [line.strip() for line in (out.stdout or "").splitlines() if line.strip()]


def standalone_agent(lines: Optional[list[str]]) -> Optional[str]:
    """The command line of a Timeline Cards process already talking to
    Resolve here, or None.

    FAILS CLOSED: `lines is None` (an unsupported platform, a probe that
    would not spawn) comes back as a refusal sentence, not as "nothing
    found". A false refusal costs the page until somebody looks; a false
    clearance costs the scripting API for the whole Resolve session, for
    every client on the machine, and the cure is closing Resolve.
    """
    if lines is None:
        return "this machine's processes could not be listed"
    for line in lines:
        low = line.lower()
        if not any(marker in low for marker in _AGENT_MARKERS):
            continue
        # The companion itself imports the package, so a match must look like
        # a SERVER or an AGENT, not like any process that mentions the path.
        if "--agent" in low or "reorder_web.py" in low:
            return line[:300]
    return None


# --------------------------------------------------------------- the tunnel

def make_tunnel_client(agent_mod: Any, role: "TimelineCardsRole", engine: Any) -> Any:
    """`AgentClient` with its ONE transport method replaced.

    Everything else about it -- push_loop, pull_loop, _apply_one, _result and
    the five-retry answer -- runs verbatim, which is the point: the loops
    that have driven Resolve from creator-1 for weeks are not rewritten here,
    they are re-pointed. `_req` is the only place they touch a socket.
    """

    class _TunnelClient(agent_mod.AgentClient):                 # type: ignore[misc]
        def _req(self, path, doc=None, timeout=30):
            return role.call(path, doc, timeout)

    # The token is empty ON PURPOSE and stays empty: the cards server's own
    # secret lives in the dashboard container and is attached there. Anything
    # this object puts in a body's `token` field is dropped by the tunnel.
    return _TunnelClient(role.dashboard_url, "", engine, role.machine)


# ------------------------------------------------------------------ the role

class TimelineCardsRole:
    """The thread, the gate and the credential. Never raises out of
    start()/stop()/status()."""

    def __init__(
        self,
        cfg: dict[str, Any],
        request_fn: Optional[Callable[..., tuple[int, Any]]] = None,
        identity_token_fn: Optional[Callable[[], Optional[str]]] = None,
        processes_fn: Optional[Callable[[], Optional[list[str]]]] = None,
        halted_fn: Optional[Callable[[], bool]] = None,
        engine_loader: Optional[Callable[[str], Any]] = None,
        bridge: Any = None,
        machine_name: str = "",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cfg = cfg or {}
        self._request = request_fn
        self._identity_token_fn = identity_token_fn
        self._processes_fn = processes_fn or running_command_lines
        self._halted_fn = halted_fn
        self._engine_loader = engine_loader or load_engine
        self._bridge = bridge
        self._machine_name = machine_name
        self._clock = clock

        self.enabled = bool(self.cfg.get("cards_agent", False))
        self._lock = threading.Lock()
        self._state = STATE_DISABLED
        self._detail = ""
        self._threads: list[threading.Thread] = []
        self._engine: Any = None
        self._client: Any = None
        self._probe: tuple[float, Optional[str]] = (0.0, None)
        self._probed = False
        self._since: Optional[float] = None
        self._seen: Optional[float] = None
        self._timeline = ""
        self._project = ""

    # -- config ---------------------------------------------------------
    @property
    def dashboard_url(self) -> str:
        return str(self.cfg.get("dashboard_url", "") or "").strip().rstrip("/")

    @property
    def _token(self) -> str:
        """Read PER CALL: IdentityManager republishes a rotated token into
        this same dict at sign-in (jobs_runner has the same property for the
        same reason)."""
        return str(self.cfg.get("dashboard_token", "") or "").strip()

    @property
    def machine(self) -> str:
        return self._machine_name or platform.node()

    @property
    def checkout(self) -> str:
        return str(self.cfg.get("jobs_mulcam_pipeline", "") or "").strip()

    @property
    def vault_root(self) -> str:
        """The vault this engine serves. `cards_vault_root` overrides, so a
        machine can transcode for the fleet out of one root and serve cards
        from another; `jobs_vault_root` is the usual answer."""
        return str(self.cfg.get("cards_vault_root")
                   or self.cfg.get("jobs_vault_root") or "").strip()

    # -- the gate -------------------------------------------------------
    def _standalone(self) -> Optional[str]:
        now = self._clock()
        stamp, answer = self._probe
        if self._probed and (now - stamp) < PROBE_CACHE_SECONDS:
            return answer
        try:
            answer = standalone_agent(self._processes_fn())
        except Exception:
            log.debug("cards: the standalone-agent probe failed", exc_info=True)
            answer = "this machine's processes could not be listed"
        self._probe = (now, answer)
        self._probed = True
        return answer

    def _halted(self) -> bool:
        """Fails CLOSED, like every other halt check here: "I could not tell
        whether everything is stopped" must not start a thing that drives
        Resolve.

        A halt refuses a START and does not interrupt a RUNNING role: the
        edits are synthetic keystroke sequences, and a sequence stopped
        half way through is a timeline nobody asked for. The companion's own
        shutdown is what lets go of Resolve.
        """
        if self._halted_fn is None:
            return False
        try:
            return bool(self._halted_fn())
        except Exception:
            log.debug("cards: the halt check failed", exc_info=True)
            return True

    def refusal(self) -> Optional[tuple[str, str]]:
        """(state, sentence) if this machine must not serve the page, else
        None. Called before the thread starts and never after: a role that
        is up stays up until stop()."""
        if not self.enabled:
            return (STATE_DISABLED,
                    "cards_agent is not set in ~/.ccsync/config.toml")
        if not self.dashboard_url or not self._token:
            return (STATE_NO_DASHBOARD,
                    "this companion has no dashboard to long-poll "
                    "(sign in from the tray)")
        if self._halted():
            return (STATE_HALTED,
                    "the fleet is halted, so this machine is not taking work "
                    "of any kind")
        if not self.checkout:
            return (STATE_NO_CHECKOUT,
                    "jobs_mulcam_pipeline is not set, so there is no Timeline "
                    "Cards engine to run")
        if not self.vault_root:
            return (STATE_NO_VAULT,
                    "jobs_vault_root is not set, so the engine has no vault "
                    "to read")
        found = self._standalone()
        if found:
            return (STATE_STANDALONE_AGENT,
                    "a Timeline Cards process is already talking to Resolve on "
                    "this machine, so the companion will not be a second one "
                    "(CR-68). Stop it and restart the companion. Found: "
                    + found)
        return None

    # -- start / stop ----------------------------------------------------
    def start(self) -> bool:
        """-> did it start. Never raises."""
        try:
            return self._start()
        except CardsRoleError as exc:
            self._set(getattr(exc, "state", STATE_NO_ENGINE), str(exc))
            log.warning("cards: not serving the page here: %s", exc)
            return False
        except Exception:
            log.exception("cards: the Timeline Cards role could not start")
            self._set(STATE_NO_ENGINE, "the role could not start (see the log)")
            return False

    def _start(self) -> bool:
        with self._lock:
            if self._threads:
                return True
        refused = self.refusal()
        if refused is not None:
            state, detail = refused
            self._set(state, detail)
            # INFO for the ordinary off states, WARNING for the one that means
            # somebody has to do something.
            if state == STATE_STANDALONE_AGENT:
                log.warning("cards: %s", detail)
            else:
                log.info("cards: not serving the page here: %s", detail)
            return False
        try:
            engine_mod, agent_mod = self._engine_loader(self.checkout)
        except CardsRoleError as exc:
            self._set(getattr(exc, "state", STATE_NO_ENGINE), str(exc))
            log.warning("cards: not serving the page here: %s", exc)
            return False
        bridge = self._bridge or timeline_cards_bridge.CardsBridge(self.cfg)
        self._bridge = bridge
        engine_cls = getattr(engine_mod, "SyncEngine")
        engine = engine_cls(self.vault_root, bridge=bridge)
        engine.start()
        client = make_tunnel_client(agent_mod, self, engine)
        with self._lock:
            self._engine = engine
            self._client = client
            self._since = time.time()
            self._threads = [
                threading.Thread(target=self._loop, args=(client.push_loop, "push"),
                                 name="ccsync-cards-push", daemon=True),
                threading.Thread(target=self._loop, args=(client.pull_loop, "pull"),
                                 name="ccsync-cards-pull", daemon=True),
            ]
            for thread in self._threads:
                thread.start()
        self._set(STATE_RUNNING, f"serving {self.vault_root} to {self.dashboard_url}")
        log.info("cards: serving the Timeline Cards page from this machine's "
                 "Resolve (%s -> %s)", self.vault_root, self.dashboard_url)
        return True

    def _loop(self, target: Callable[[], None], which: str) -> None:
        """AgentClient's loops never return; if one does, say so rather than
        letting a thread die into silence and the page go quiet for ever."""
        try:
            target()
        except Exception:
            log.exception("cards: the %s loop stopped", which)
        else:
            log.warning("cards: the %s loop returned -- the page will not "
                        "update until the companion restarts", which)

    def stop(self) -> None:
        """Let go of Resolve. The loops are daemon threads inside a blocking
        long poll, so this does not join them: what it does is stop this
        object claiming to be the agent, and the process is going away."""
        with self._lock:
            threads, self._threads = self._threads, []
            self._client = None
            self._engine = None
            self._since = None
        if threads:
            log.info("cards: no longer serving the page from this machine")
            self._set(STATE_DISABLED, "the companion is shutting down")

    # -- the credential swap ---------------------------------------------
    def _headers(self) -> dict[str, str]:
        identity = ""
        if self._identity_token_fn is not None:
            try:
                identity = str(self._identity_token_fn() or "")
            except Exception:
                log.debug("cards: identity_token_fn failed", exc_info=True)
        return {"Content-Type": "application/json",
                "X-CCSync-Token": self._token,
                "X-CCSync-Identity": identity}

    def call(self, path: str, doc: Optional[dict] = None, timeout: float = 30.0) -> Any:
        """One `/agent/*` call, re-pointed at the dashboard's tunnel.

        `AgentClient` builds paths like `/agent/pending?wait=25&token=...`.
        The token in that query is dropped: this companion holds no cards
        token, the dashboard attaches the real one, and a secret in a query
        string is a secret in somebody's access log.
        """
        raw, _, query = str(path).partition("?")
        suffix = raw.rsplit("/", 1)[-1]
        if suffix not in ("state", "pending", "result"):
            raise CardsTunnelError(f"no such agent route: {path}")
        url = f"{self.dashboard_url}/cards/agent/{suffix}"
        method = "GET" if suffix == "pending" else "POST"
        if suffix == "pending":
            wait = AGENT_WAIT_SECONDS
            for part in query.split("&"):
                key, _, value = part.partition("=")
                if key == "wait":
                    try:
                        wait = max(0.0, min(float(value), AGENT_WAIT_SECONDS))
                    except ValueError:
                        pass
            url += f"?wait={int(wait)}"
        body = None
        if doc is not None:
            body = {k: v for k, v in doc.items() if k != "token"}
        request = self._request
        if request is None:
            from .broll_ingest import default_request
            request = default_request
        status, parsed = request(method, url, body, self._headers(), float(timeout))
        if status != 200:
            detail = ""
            if isinstance(parsed, dict):
                detail = str(parsed.get("detail") or "")
            raise CardsTunnelError(
                f"the dashboard answered HTTP {status} for {suffix}"
                + (f": {detail}" if detail else ""))
        self._note_traffic(suffix, body, parsed)
        return parsed if isinstance(parsed, dict) else {}

    def _note_traffic(self, suffix: str, body: Optional[dict], answer: Any) -> None:
        """Keep just enough to answer "is this machine serving the page, and
        which timeline". The fleet grid's [ CARDS: E1 v5 ] is these three
        fields and nothing else."""
        if suffix != "state" or not isinstance(body, dict):
            return
        state = body.get("state")
        with self._lock:
            self._seen = time.time()
            if isinstance(state, dict):
                self._timeline = str(state.get("timeline") or "")
                self._project = str(state.get("project") or "")

    # -- what the report and the tray see ---------------------------------
    def _set(self, state: str, detail: str) -> None:
        with self._lock:
            self._state, self._detail = state, detail

    def status(self) -> dict[str, Any]:
        """Zero-I/O snapshot for the log and the diagnostics bundle."""
        with self._lock:
            state, detail = self._state, self._detail
            running = bool(self._threads)
            since, seen = self._since, self._seen
            timeline, project = self._timeline, self._project
            engine = self._engine
        answer: dict[str, Any] = {
            "state": state, "detail": detail, "running": running,
            "since": since, "last_state_at": seen,
            "timeline": timeline, "project": project,
        }
        try:
            answer["version"] = int(getattr(engine, "version", 0)) if engine else 0
        except Exception:
            answer["version"] = 0
        if self._bridge is not None:
            try:
                answer["lock"] = self._bridge.stats()
            except Exception:
                log.debug("cards: bridge stats failed", exc_info=True)
        return answer

    def report_block(self) -> dict[str, Any]:
        """`capabilities.cards_agent` -- what the fleet grid renders.

        `connected` is about THIS machine's role, not about the cards
        server: a companion that is holding Resolve open for the page says
        so, and one that refused says which refusal in `state`. Deliberately
        four small fields; the sentence lives in the diagnostics bundle.
        """
        status = self.status()
        return {
            "connected": bool(status["running"]),
            "state": status["state"],
            "timeline": status["timeline"],
            "version": status["version"],
            "since": status["since"] and round(status["since"], 3),
        }


def build(cfg: dict[str, Any], **kwargs: Any) -> Optional["TimelineCardsRole"]:
    """The role, or None on a machine that could not even construct one.

    Constructed on EVERY machine, including the ones with `cards_agent` off,
    so `status()` can answer "why is this machine not serving the page" from
    the diagnostics bundle rather than from silence.
    """
    try:
        return TimelineCardsRole(cfg, **kwargs)
    except Exception:
        log.exception("cards: could not build the Timeline Cards role")
        return None
