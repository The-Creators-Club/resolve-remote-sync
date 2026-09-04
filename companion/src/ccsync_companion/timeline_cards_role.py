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

A FROZEN COMPANION MAY NOT BE ABLE TO IMPORT IT, and that is an import
failure with a sentence, not a crash. The shipped companion is a PyInstaller
one-file build carrying only its own dependencies; the cards engine pulls in
whatever MulticamPipeline's checkout needs. If those are missing, `start()`
refuses with "the Timeline Cards engine at <path> could not be imported
(ModuleNotFoundError: ...)" and the tray app carries on. THE FIRST TIME THIS
ROLE IS SWITCHED ON, TRY IT FROM A SOURCE RUN OF THE COMPANION FIRST -- the
answer to a missing dependency is a decision (bundle it, or run the companion
from source on that one machine), not a hotfix.

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
from datetime import datetime, timezone
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
# How often the standalone-agent probe is re-run while the role is refusing.
# It shells out, so not per tick.
PROBE_CACHE_SECONDS = 60.0

# WHAT THE FLEET GRID GOES GREEN ON (RES-6, sweep 2026-09-04). Until this
# sweep `report_block()["connected"]` was `bool(self._threads)`, and nothing
# ever cleared that list: a loop that raised, a loop that returned and a
# machine that had been answered HTTP 401 for hours all rendered exactly like
# a healthy one. These five words are the whole vocabulary, and only the first
# is green.
HEALTH_RUNNING = "running"
HEALTH_STOPPED = "stopped"
HEALTH_REFUSED = "refused"
HEALTH_CREDENTIAL_REFUSED = "credential_refused"
HEALTH_UNREACHABLE = "unreachable"
# TWO LONG POLLS. The pull loop's poll returns at AGENT_WAIT_SECONDS at the
# latest and the push loop posts state at least as often, so a role that has
# said nothing for two of them is a role that is not talking, whatever its
# threads think they are doing.
STALE_AFTER_SECONDS = 2 * AGENT_WAIT_SECONDS
# A start is not a poll: the loops need a moment to make their first call, and
# a chip that goes amber for the first three seconds of every companion
# restart is a chip nobody believes.
GRACE_SECONDS = 30.0
# The sentence an editor gets for a revoked or rotated fleet token. It names
# the ONE thing that fixes it, which is not "wait".
CREDENTIAL_ADVICE = ("the fleet credential is refused: sign in again from the "
                     "tray")


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


def engine_class(engine_mod: Any) -> Any:
    """The engine class this checkout exports, or None.

    Both spellings are accepted on purpose: §7c is written against
    `SyncEngine`, and the checkout that exists today calls it `ResolveEngine`
    (bug-hunt-2026-09-03 comp-resolve-3). One expression, so `check_contract`
    and `_start` can never disagree about which class was validated -- they
    did, and the second half died as an AttributeError inside start()'s
    catch-all, which is the outcome the contract version exists to prevent.
    """
    return getattr(engine_mod, "SyncEngine", None) or getattr(
        engine_mod, "ResolveEngine", None)


def check_contract(engine_mod: Any) -> Any:
    """Does this engine take a bridge? (§7c.) Returns the class it validated.

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
    engine_cls = engine_class(engine_mod)
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
    return engine_cls


# ------------------------------------------------------- the standalone agent

# `reorder_web.py --agent` and `python -m multicam_pipeline ... --agent`, plus
# the PC's own `reorder_web.py 8800`, which is the other half of the same rule.
_AGENT_MARKERS = ("reorder_web.py", "multicam_pipeline")

# The one answer that is neither a sighting nor a clearance. A CONSTANT since
# RES-7, because `refusal()` gives it its own sentence: rendering "Found: this
# machine's processes could not be listed" read as if something had been seen.
PROBE_UNREADABLE = "this machine's processes could not be listed"


def describe_process(line: str) -> str:
    """A process line -> "python.exe (pid 4312): ...reorder_web.py --agent".

    RES-7: the refusal used to name a command line and nothing else, so
    "stop it" meant "find it yourself". Both probe shapes are handled -- the
    tab-separated one `running_command_lines` emits now, and the bare command
    line an older caller or a test passes -- because a probe this module does
    not own may still be wired in (`processes_fn`).
    """
    raw = str(line or "").strip()
    if not raw:
        return ""
    pid = name = ""
    command = raw
    if "\t" in raw:
        pid, _, rest = raw.partition("\t")
        name, _, command = rest.partition("\t")
    else:
        first, _, rest = raw.partition(" ")
        if first.isdigit() and rest.strip():
            pid = first
            name, _, command = rest.strip().partition(" ")
    pid = pid.strip()
    name = Path(name.strip()).name if name.strip() else ""
    command = command.strip() or raw
    if pid.isdigit() and name:
        return f"{name} (pid {pid}): {command}"[:300]
    return raw[:300]


def running_command_lines() -> Optional[list[str]]:
    """Every process command line on this machine, or None if we cannot tell.

    None is NOT "there is nothing running" -- see the fail-closed rule in
    `standalone_agent()`. Windows needs CIM for the command line (tasklist
    does not carry one); macOS has `ps -Ao command`.

    EACH LINE CARRIES `pid<TAB>name<TAB>command line` since the 2026-09-04
    sweep (RES-7): "stop it and restart the companion" is not advice anybody
    can act on when the thing to stop is named only by a command line three
    screens wide. `standalone_agent()` matches on substrings, so a line in the
    old bare-command-line shape still works and the old refusal still reads.
    """
    system = platform.system()
    try:
        if system == "Windows":
            out = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "Get-CimInstance Win32_Process | ForEach-Object "
                 "{ \"$($_.ProcessId)`t$($_.Name)`t$($_.CommandLine)\" }"],
                capture_output=True, text=True, timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        elif system == "Darwin":
            out = subprocess.run(["ps", "-Ao", "pid=,comm=,command="],
                                 capture_output=True, text=True, timeout=30)
        else:
            return None
    except Exception:
        log.debug("cards: could not list processes", exc_info=True)
        return None
    if out.returncode != 0:
        # bug-hunt-2026-09-03 comp-resolve-6: a listing that failed part way
        # through (a CIM query interrupted, an access error mid-enumeration)
        # still carries lines, and a truncated list read as authoritative is
        # how a running standalone agent goes unseen -- two Resolve clients on
        # one machine, the exact CR-68 outcome this gate exists to prevent.
        # Non-zero means "cannot tell", whatever came out on stdout.
        log.debug("cards: the process listing exited %s -- treating it as "
                  "unreadable", out.returncode)
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
        return PROBE_UNREADABLE
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
        # THE EVIDENCE report_block() JUDGES ON (RES-6). `_last_poll_at` is
        # any successful tunnel call, not only a `state` push: the pull loop
        # long-polls `pending` and a role whose push loop alone had died would
        # otherwise look silent. `_last_http_status` is the last answer the
        # dashboard actually gave, which is how a 401 stops being
        # indistinguishable from a network that is down.
        self._last_poll_at: Optional[float] = None
        self._last_http_status: Optional[int] = None
        self._last_error = ""
        # What killed a loop, in its own words, so `stopped` can say why.
        self._loop_error = ""
        # The re-evaluation thread (RES-7). It exists only on machines with
        # `cards_agent` on: a companion with the role off must not shell out
        # for a process listing every minute for ever.
        self._stop_ev = threading.Event()
        self._supervisor: Optional[threading.Thread] = None
        self._logged_detail = ""

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
        None.

        RE-ASKED EVERY PROBE_CACHE_SECONDS WHILE THE ROLE IS DOWN (RES-7,
        sweep 2026-09-04), not once at start. Every one of these refusals is
        a condition that CLEARS: somebody signs in, somebody closes the
        standalone agent, a fleet halt expires (24 h by design). Deciding
        them once per process meant the sentence "sign in from the tray" told
        an editor to do the one thing that would not help, because only a
        restart started the role.
        """
        if not self.enabled:
            return (STATE_DISABLED,
                    "cards_agent is not set in ~/.ccsync/config.toml")
        if not self.dashboard_url or not self._token:
            return (STATE_NO_DASHBOARD,
                    "this companion has no dashboard to long-poll. Sign in "
                    "from the tray and this computer will pick the page up "
                    "on its own within a minute")
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
        if found == PROBE_UNREADABLE:
            # NOT A SIGHTING. The old sentence rendered this as "Found: this
            # machine's processes could not be listed", which reads like
            # something was seen and sent people looking for it (RES-7).
            return (STATE_STANDALONE_AGENT,
                    "another Timeline Cards process may be running here and "
                    "this machine's processes could not be listed, so the "
                    "companion is not starting the role (CR-68)")
        if found:
            return (STATE_STANDALONE_AGENT,
                    "a Timeline Cards process is already talking to Resolve on "
                    "this machine, so the companion will not be a second one "
                    "(CR-68). Close the standalone Timeline Cards agent window "
                    "and this computer will pick the page up on its own within "
                    "a minute. Found: " + describe_process(found))
        return None

    # -- start / stop ----------------------------------------------------
    def start(self) -> bool:
        """-> did it start. Never raises.

        A False here is no longer final (RES-7): on a machine with the role
        switched on, the watchdog keeps asking, so a companion that started
        before sign-in or beside a standalone agent comes up by itself once
        the condition clears.
        """
        started = False
        try:
            started = self._start_guarded()
        finally:
            if self.enabled:
                self._ensure_supervisor()
        return started

    def _start_guarded(self) -> bool:
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
            # ONCE PER SENTENCE, not once per attempt: the watchdog re-asks
            # every PROBE_CACHE_SECONDS now (RES-7), and a refusal that never
            # changes must not be a line a minute in companion.log for weeks.
            if detail != self._logged_detail:
                self._logged_detail = detail
                # INFO for the ordinary off states, WARNING for the one that
                # means somebody has to do something.
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
        engine_cls = engine_class(engine_mod)
        if engine_cls is None:
            # bug-hunt-2026-09-03 comp-resolve-3: a bare getattr("SyncEngine")
            # here contradicted check_contract, which accepts either spelling,
            # so a checkout exporting only ResolveEngine passed the contract
            # test and then died as an AttributeError in start()'s catch-all
            # with a sentence that names nothing.
            raise CardsRoleError(
                "this Timeline Cards checkout has no SyncEngine/ResolveEngine",
                STATE_NO_ENGINE)
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
        letting a thread die into silence and the page go quiet for ever.

        SAYING SO NOW MEANS SAYING SO IN THE REPORT (RES-6): until this sweep
        the only trace was a log line on the machine, and `report_block()`
        went on calling itself connected because `_threads` was still a list
        of two dead threads."""
        try:
            target()
        except Exception as exc:                                # noqa: BLE001
            log.exception("cards: the %s loop stopped", which)
            self._note_loop_end(f"the {which} loop stopped: "
                                f"{type(exc).__name__}: {exc}")
        else:
            log.warning("cards: the %s loop returned -- the page will not "
                        "update until the companion restarts", which)
            self._note_loop_end(f"the {which} loop returned")

    def _note_loop_end(self, detail: str) -> None:
        with self._lock:
            # The FIRST death is the interesting one: the second loop usually
            # dies of the same cause a moment later, and overwriting would
            # leave the report naming the symptom rather than the cause.
            if not self._loop_error:
                self._loop_error = detail[:300]

    # -- the watchdog (RES-7) ---------------------------------------------
    def _ensure_supervisor(self) -> None:
        if self._supervisor is not None and self._supervisor.is_alive():
            return
        self._stop_ev.clear()
        self._supervisor = threading.Thread(target=self._supervise,
                                            name="ccsync-cards-watch",
                                            daemon=True)
        self._supervisor.start()

    def _supervise(self) -> None:
        """Re-ask the refusal while the role is down, for ever.

        The cadence is PROBE_CACHE_SECONDS because the only expensive question
        in `refusal()` is the process probe and that is what its cache is
        sized for -- read per iteration so a test can shorten it.
        """
        while not self._stop_ev.wait(float(PROBE_CACHE_SECONDS)):
            self.supervise_now()

    def supervise_now(self) -> bool:
        """One re-evaluation. -> is the role running now. Never raises.

        A HALT DOES NOT STOP A ROLE THAT IS UP, deliberately, and RES-7's
        proposal to make it does not survive `_halted`'s own rule: the edits
        are synthetic keystroke sequences and one stopped half way through is
        a timeline nobody asked for. A halt still refuses a START, and it now
        stops LATCHING the role off for the life of the process once it
        expires, which was the actual defect.
        """
        try:
            with self._lock:
                if self._threads:
                    return True
            return self._start_guarded()
        except Exception:                                       # noqa: BLE001
            log.debug("cards: the watchdog stumbled", exc_info=True)
            return False

    def stop(self) -> None:
        """Let go of Resolve. The loops are daemon threads inside a blocking
        long poll, so this does not join them: what it does is stop this
        object claiming to be the agent, and the process is going away."""
        # The watchdog goes with it: a stop() that left it running would
        # start the role again a minute into the shutdown (RES-7).
        self._stop_ev.set()
        self._supervisor = None
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
        try:
            status, parsed = request(method, url, body, self._headers(),
                                     float(timeout))
        except Exception as exc:                                # noqa: BLE001
            # A TRANSPORT FAILURE IS EVIDENCE TOO (RES-6). The engine's loops
            # swallow it and back off, which is right for them and is exactly
            # why this side has to keep the last one: "the dashboard has been
            # unreachable for an hour" is otherwise invisible everywhere.
            self._note_call(None, f"{type(exc).__name__}: {exc}")
            raise
        if status != 200:
            detail = ""
            if isinstance(parsed, dict):
                detail = str(parsed.get("detail") or "")
            message = (f"the dashboard answered HTTP {status} for {suffix}"
                       + (f": {detail}" if detail else ""))
            self._note_call(int(status), message)
            raise CardsTunnelError(message)
        self._note_call(200, "")
        self._note_traffic(suffix, body, parsed)
        return parsed if isinstance(parsed, dict) else {}

    def _note_call(self, status: Optional[int], error: str) -> None:
        """What the dashboard last said, and when it last said 200.

        `_last_poll_at` moves on ANY successful call and not only on a `state`
        push: the pull loop's long poll is the one that runs even when nothing
        is happening in Resolve, so a role judged on `state` alone would look
        silent on a quiet afternoon (RES-6).
        """
        with self._lock:
            self._last_http_status = status
            self._last_error = str(error or "")[:300]
            if status == 200:
                self._last_poll_at = time.time()

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

    def health(self) -> tuple[str, str]:
        """(one of the five HEALTH_* words, a sentence) -- RES-6.

        The order is the order of severity, and every branch is a DIFFERENT
        problem with the same old symptom: a thread that has died, a
        credential that has been refused, a dashboard that cannot be reached,
        and a machine that was never going to serve the page at all.
        """
        with self._lock:
            gate_state, gate_detail = self._state, self._detail
            threads = list(self._threads)
            since, polled = self._since, self._last_poll_at
            status, error, loop_error = (self._last_http_status,
                                         self._last_error, self._loop_error)
        if not threads:
            return HEALTH_REFUSED, gate_detail
        alive = [t for t in threads if t.is_alive()]
        if loop_error or not alive:
            return HEALTH_STOPPED, (
                loop_error or "the push and pull loops are no longer running")
        if status in (401, 403):
            return HEALTH_CREDENTIAL_REFUSED, CREDENTIAL_ADVICE
        if polled is None and error:
            # A call that FAILED is evidence, and the start grace below is
            # only ever cover for silence: a role whose every call so far has
            # been refused is not "still starting".
            return HEALTH_UNREACHABLE, error
        fresh = polled if polled is not None else since
        age = time.time() - float(fresh or 0.0)
        # A start counts for GRACE_SECONDS and no longer: after that the only
        # thing that keeps this green is the dashboard answering.
        limit = STALE_AFTER_SECONDS if polled is not None else GRACE_SECONDS
        if fresh is None or age > limit:
            return HEALTH_UNREACHABLE, (
                error or "the dashboard has not answered this computer's "
                         "Timeline Cards loops")
        if gate_state != STATE_RUNNING:
            return HEALTH_STOPPED, gate_detail
        return HEALTH_RUNNING, gate_detail

    def status(self) -> dict[str, Any]:
        """Zero-I/O snapshot for the log and the diagnostics bundle."""
        health, health_detail = self.health()
        with self._lock:
            state, detail = self._state, self._detail
            running = bool(self._threads)
            since, seen = self._since, self._seen
            polled, http = self._last_poll_at, self._last_http_status
            timeline, project = self._timeline, self._project
            engine = self._engine
        answer: dict[str, Any] = {
            "state": state, "detail": detail, "running": running,
            "since": since, "last_state_at": seen,
            "health": health, "health_detail": health_detail,
            "last_poll_at": polled, "last_http_status": http,
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

        `connected` is about THIS machine's role, not about the cards server.
        Since RES-6 (sweep 2026-09-04) it is a JUDGEMENT and not a list
        length: green means the loops are alive AND the dashboard answered
        one of them within two long polls. A dead loop, a 401 and a dashboard
        that has gone quiet used to be indistinguishable from a healthy
        machine here, and the fleet grid is where somebody would have looked.

        `state` is now one of the five HEALTH_* words and `detail` is the
        sentence that goes with it; the refusal vocabulary moved to
        `gate_state`, which is still what tells "nobody turned it on" from "a
        standalone agent is still running there".
        """
        status = self.status()
        return {
            "connected": status["health"] == HEALTH_RUNNING,
            "state": status["health"],
            "detail": status["health_detail"],
            "gate_state": status["state"],
            "last_poll_at": _iso(status["last_poll_at"]),
            "last_http_status": status["last_http_status"],
            "timeline": status["timeline"],
            "version": status["version"],
            "since": status["since"] and round(status["since"], 3),
        }


def _iso(when: Optional[float]) -> Optional[str]:
    """An epoch second -> UTC ISO-8601, or None. The report is JSON and the
    reader is a page on another machine, so a float here would be a number
    somebody has to convert with the wrong timezone."""
    if not when:
        return None
    try:
        return datetime.fromtimestamp(float(when), timezone.utc).replace(
            microsecond=0).isoformat()
    except Exception:
        return None


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
