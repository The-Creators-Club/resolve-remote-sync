"""Which AI the YouTube downloader uses, and where its credentials live.

Added 2026-08-18. Until today the answer was one environment variable
(`ANTHROPIC_API_KEY`) set by `install_dashboard_app.py` into the container's
compose env -- which is the "an appliance customer has no shell" problem
`ZERO_TOUCH_PLAN.md` exists to remove, one variable at a time. An admin can
now type keys on Settings, and the ytdl app asks THIS module, on every call,
which backend to use.

**The chain, in order: `claude_code > anthropic_api > codex > openai_api >
deepseek_api`.** First AVAILABLE wins -- a CLI is available when it is
installed AND signed in, an API when a key is present. An admin can pin one
instead (`ai_provider_preference`), and a pin that is not available is a
REFUSAL rather than a quiet fall-through to the next: somebody who pinned
DeepSeek did not consent to their Anthropic key being spent instead.

**Why CLI providers exist here at all, and why that is not a walk-back of
`COMMERCIAL_READINESS.md` item 1.** That finding named three ToS problems:
service use of a CONSUMER plan, seat sharing, and REDISTRIBUTING the Claude
Code binary to customer hardware. The third one is ours and stays fixed:
nothing in this repo BUNDLES either CLI -- not in the image
(`docs/DOCKER.md`), not in a package record, not in a release artefact, and
there is no `claude-bin` volume or installer step for one. Since 2026-08-18
`cli_tools.py` can FETCH one at the admin's click, from the publisher's own
distribution and checked against the publisher's own checksum, into the
customer's own data volume: that is the customer installing the publisher's
build on their own host with one button instead of a shell, which is what the
owner asked for when he read "no `claude` on this container's PATH. Install it
on the dashboard host" and said it was too complex for most users. A CLI
provider is still an ADAPTER, and the first two ToS problems are still the
customer's own decision, made knowingly: the whole CLI half is behind the site
feature flag `[features] ai_cli_providers`, which ships OFF in the vendor
build, the wizard opens on a notice saying whose subscription is about to be
spent, and API keys stay the vendor default and the documented path.

**No secret ever leaves this module in a readable form except to the ytdl
app.** Keys are files under `<data>/secrets/ai/<name>`, 0600, written through
`secrets_boot.write_secret_file` (the same hardening the five boot secrets
get). They are NEVER in `GET /api/v1/site` -- that route is open to anyone
who can reach the dashboard and is documented as carrying nothing secret --
never in a log line, and never in an API response: the routes below publish a
MASK (`sk-…abcd`) and a source, nothing else. The environment still wins when
it is set, so a deployment that already passes `ANTHROPIC_API_KEY` through
compose keeps working exactly as it did, and the page says "set by the
deployment" rather than offering to overwrite something it cannot.
"""
from __future__ import annotations

import logging
import os
import shlex
import shutil
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from . import auth, cli_tools, secrets_boot
from .api import get_conn

log = logging.getLogger("ccsync.dashboard.ai_providers")

router = APIRouter(prefix="/api/v1")

CLAUDE_CODE = "claude_code"
ANTHROPIC_API = "anthropic_api"
CODEX = "codex"
OPENAI_API = "openai_api"
DEEPSEEK_API = "deepseek_api"

# THE CHAIN. This tuple is the priority order and the display order both --
# the Settings page numbers the rows from it, so the page can never show an
# order the resolver does not use. `ytdlweb.ai_backend.PROVIDER_ORDER` states
# the same list for the case where the ytdl app runs with no dashboard in
# reach; this one is the one that decides.
PROVIDER_ORDER = (CLAUDE_CODE, ANTHROPIC_API, CODEX, OPENAI_API, DEEPSEEK_API)


@dataclass(frozen=True)
class ProviderSpec:
    """One backend: how it is credentialed, and how it is checked."""

    name: str
    label: str
    kind: str                  # "cli" | "api"
    # api: the env var that also sets this key (and WINS over a stored file),
    # and the file under <data>/secrets/ai/.
    env_var: str = ""
    secret_file: str = ""
    # cli: the executable to look for on PATH, the site_settings key holding
    # an explicit path, the command an admin must run ON THE HOST to sign in,
    # and the argv used for the login probe (see _cli_argv).
    binary: str = ""
    path_setting: str = ""
    login_command: str = ""
    probe_args_env: str = ""
    default_probe_args: str = ""


PROVIDERS: dict[str, ProviderSpec] = {
    CLAUDE_CODE: ProviderSpec(
        name=CLAUDE_CODE, label="Claude Code", kind="cli",
        binary="claude", path_setting="ai_claude_code_path",
        # Verified against Claude Code 2.1.234 (2026-08-18). It used to say
        # "claude   (then /login)", which is the in-session slash command and
        # needs a terminal somebody is sitting at; this one is the direct
        # subcommand, and it is what the wizard drives under a pty.
        login_command="claude auth login",
        # Same env var the ytdl app reads (they share one container
        # environment), so one correction fixes both the probe and the real
        # call rather than leaving them disagreeing about how to invoke a CLI
        # neither of us ships.
        probe_args_env="YTDL_CLAUDE_CODE_ARGS",
        default_probe_args="-p --output-format text --disallowed-tools *",
    ),
    ANTHROPIC_API: ProviderSpec(
        name=ANTHROPIC_API, label="Claude API", kind="api",
        env_var="ANTHROPIC_API_KEY", secret_file="anthropic_api_key",
    ),
    CODEX: ProviderSpec(
        name=CODEX, label="Codex", kind="cli",
        binary="codex", path_setting="ai_codex_path",
        login_command="codex login",
        probe_args_env="YTDL_CODEX_ARGS",
        default_probe_args="exec --sandbox read-only -",
    ),
    OPENAI_API: ProviderSpec(
        name=OPENAI_API, label="OpenAI API", kind="api",
        env_var="OPENAI_API_KEY", secret_file="openai_api_key",
    ),
    DEEPSEEK_API: ProviderSpec(
        name=DEEPSEEK_API, label="DeepSeek API", kind="api",
        env_var="DEEPSEEK_API_KEY", secret_file="deepseek_api_key",
    ),
}

API_PROVIDERS = tuple(n for n in PROVIDER_ORDER if PROVIDERS[n].kind == "api")
CLI_PROVIDERS = tuple(n for n in PROVIDER_ORDER if PROVIDERS[n].kind == "cli")

# The `site_settings` rows this module owns. They live in the same table as
# the manifest but are deliberately NOT `site_store.KEYS`: nothing outside
# this container ever reads them, so they must never appear in
# `GET /api/v1/site`, in the site.toml export, or in the manifest an installer
# consumes. `site_store.resolved_manifest` ignores unknown rows, which is what
# makes sharing the table safe.
PREFERENCE_KEY = "ai_provider_preference"
SETTING_KEYS = (PREFERENCE_KEY, "ai_claude_code_path", "ai_codex_path")

# "auto" plus every provider name. Stored as text; validated on the way in.
AUTO = "auto"

# What the Settings page says, and what the ToS note has to keep saying. Kept
# here rather than in the template so the API answer and the page cannot drift
# -- an admin who drives this from curl deserves the same warning.
CLI_TOS_NOTE = (
    "Claude Code and Codex are signed in with a personal Claude or ChatGPT "
    "subscription. Using a personal subscription to power a service may "
    "breach its terms: that is your decision, not ours. Neither CLI is "
    "shipped, bundled or updated by CC Sync. SET UP downloads the publisher's "
    "own build, from the publisher's own servers, at your click, and checks it "
    "against the publisher's own checksum. The API keys above are the "
    "supported path."
)

# Status vocabulary. The chip on the Settings page and the `status` field of
# the API answer are the same six strings.
ST_AVAILABLE = "available"
ST_NOT_CONFIGURED = "not_configured"
ST_NOT_INSTALLED = "not_installed"
ST_NOT_SIGNED_IN = "not_signed_in"
ST_DISABLED = "disabled_by_site"
ST_UNKNOWN = "unknown"

STATUS_LABELS = {
    ST_AVAILABLE: "available",
    ST_NOT_CONFIGURED: "not configured",
    ST_NOT_INSTALLED: "not installed",
    ST_NOT_SIGNED_IN: "not signed in",
    ST_DISABLED: "disabled by site",
    ST_UNKNOWN: "unknown",
}

# Longest key we will store. Generous -- these are ~100 characters today and a
# gateway token can be longer -- and bounded, because this writes a file.
MAX_KEY_CHARS = 512


class ProviderError(ValueError):
    """A refused write (bad provider name, unusable key). The message is
    shown to the admin verbatim and never contains the key."""


# --------------------------------------------------------------- key storage

def keys_dir(settings: Any) -> Path:
    """`<data>/secrets/ai`. Under the SAME directory the boot secrets use, so
    a deployment only has one place to back up, one to lock down, and one to
    keep off a database dump (a DB backup must never be a working
    credential -- db.py SCHEMA_V15's rule, applied to somebody's paid API
    key)."""
    return Path(settings.db_path).parent / "secrets" / "ai"


def _key_path(settings: Any, name: str) -> Path:
    return keys_dir(settings) / PROVIDERS[name].secret_file


def spec(name: str) -> ProviderSpec:
    try:
        return PROVIDERS[name]
    except KeyError:
        raise ProviderError(f"{name!r} is not a known AI provider") from None


def read_key(settings: Any, name: str, env: Mapping[str, str] | None = None) -> tuple[str, str]:
    """(value, source) where source is "env" | "file" | "".

    ENV WINS, always. Rotating a key by setting the container variable stays
    possible exactly as it is today, and a deployment whose compose already
    carries `ANTHROPIC_API_KEY` sees no behaviour change at all from this
    module existing -- the page tells the admin the value is "set by the
    deployment" instead of pretending a Set button would take effect.
    """
    provider = spec(name)
    if provider.kind != "api":
        return "", ""
    env = os.environ if env is None else env
    from_env = (env.get(provider.env_var, "") or "").strip()
    if from_env:
        return from_env, "env"
    try:
        stored = _key_path(settings, name).read_text(encoding="utf-8").strip()
    except OSError:
        stored = ""
    return (stored, "file") if stored else ("", "")


def validate_key(raw: str) -> str:
    """The key as it will be stored, or raise. Never echoes the value back in
    an error message -- a refusal that quotes the key puts it in the browser's
    console, the server log and anyone's screenshot."""
    value = str(raw or "").strip()
    if not value:
        raise ProviderError("the key is blank")
    if len(value) > MAX_KEY_CHARS:
        raise ProviderError(f"that key is longer than {MAX_KEY_CHARS} characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ProviderError("the key contains control characters -- paste it again")
    if any(ch.isspace() for ch in value):
        # Catches the two common paste accidents ("Bearer sk-..." and a
        # trailing line from a wrapped terminal) at the moment they happen,
        # rather than as an unexplained 401 on the next search job.
        raise ProviderError("the key contains a space -- paste the key alone, "
                            "with no 'Bearer' prefix")
    return value


def set_key(settings: Any, name: str, raw: str) -> str:
    """Store a key 0600 and return its MASK. Raises ProviderError."""
    provider = spec(name)
    if provider.kind != "api":
        raise ProviderError(f"{provider.label} does not take an API key -- it is a CLI")
    value = validate_key(raw)
    path = _key_path(settings, name)
    try:
        secrets_boot.write_secret_file(path, value)
    except OSError as exc:
        raise ProviderError(
            f"could not write the key to {path.parent} ({exc.strerror or exc}). "
            f"That directory must be writable by the container's uid."
        ) from None
    # The name of the provider, never the key, and never at a level that ends
    # up in a support bundle by accident.
    log.info("AI provider key stored for %s", name)
    return mask(value)


def clear_key(settings: Any, name: str) -> bool:
    """Delete a stored key. -> whether there was one. An env-set key cannot be
    cleared from here (it is the deployment's, not the page's) and saying so
    is the route's job."""
    spec(name)
    path = _key_path(settings, name)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise ProviderError(f"could not remove the stored key ({exc.strerror or exc})")
    log.info("AI provider key cleared for %s", name)
    return True


def mask(value: str) -> str:
    """`sk-…abcd`: enough to tell two keys apart, not enough to use one.

    A short value is masked ENTIRELY rather than mostly -- a 6-character
    string with its last 4 shown is nearly the whole secret.
    """
    value = str(value or "")
    if not value:
        return ""
    if len(value) < 12:
        return "…"
    return f"{value[:3]}…{value[-4:]}"


# ------------------------------------------------------- site_settings rows

def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    """One row, or the default.

    A MISSING TABLE IS A DEFAULT, not an error: this is read from the ytdl
    worker thread (`make_lookup`), which can run against a database whose
    migrations have not been applied yet -- a fresh volume, a container
    mid-boot -- and the honest answer there is "this site has not said", not a
    traceback in the middle of somebody's job.
    """
    stored = row_value(conn, key)
    return (stored if stored is not None else default) or default


_TABLE = "site_settings"


def row_value(conn: sqlite3.Connection, key: str) -> str | None:
    """The raw stored value, or None when there is no row at all.

    The distinction matters for the feature flag: a row of "0" is an admin
    who turned CLI providers OFF, and must beat `DASH_SITE_AI_CLI_PROVIDERS=1`
    in the container's environment -- exactly the precedence site_store gives
    every other manifest key ("the DB row if one EXISTS"). Collapsing "0" into
    "unset" would make the Settings checkbox unable to switch the feature off
    on a deployment whose env once turned it on.
    """
    try:
        row = conn.execute(f"SELECT value FROM {_TABLE} WHERE key = ?", (key,)).fetchone()
    except sqlite3.OperationalError:
        return None
    return None if row is None else str(row["value"])


def set_setting(conn: sqlite3.Connection, key: str, value: str, updated_by: str) -> None:
    """Upsert one of SETTING_KEYS. Its own writer rather than
    `site_store.set_many` because these rows are NOT manifest fields: that
    function validates against `site_store.KEYS` and would (correctly) refuse
    them, and adding them there would publish them in the manifest export."""
    if key not in SETTING_KEYS:
        raise ProviderError(f"{key!r} is not an AI-provider setting")
    from . import db as dbmod

    conn.execute(
        "INSERT INTO site_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
        "updated_at=excluded.updated_at, updated_by=excluded.updated_by",
        (key, value, dbmod.utcnow_iso(), updated_by),
    )


def preference(conn: sqlite3.Connection) -> str:
    """The admin's pin, or "auto". An unrecognised stored value reads as
    "auto" rather than as a pin nothing can satisfy."""
    value = (get_setting(conn, PREFERENCE_KEY, AUTO) or AUTO).strip()
    return value if value in PROVIDER_ORDER else AUTO


def set_preference(conn: sqlite3.Connection, value: str, updated_by: str) -> str:
    value = (value or "").strip() or AUTO
    if value != AUTO and value not in PROVIDER_ORDER:
        raise ProviderError(
            f"{value!r} is not 'auto' or one of: {', '.join(PROVIDER_ORDER)}")
    set_setting(conn, PREFERENCE_KEY, value, updated_by)
    return value


def cli_enabled(conn: sqlite3.Connection, settings: Any) -> bool:
    """Whether this site turned `[features] ai_cli_providers` on.

    FAILS CLOSED and reads the same DB-row-then-environment precedence every
    other site feature does (`site_store`): the row when there is one, else
    `DASH_SITE_AI_CLI_PROVIDERS`. Off is the vendor build's shape.

    Delegates to `site_store.feature_enabled` since 2026-08-21
    (product-surface-1): this function's precedence WAS the intended one and
    the /ytdl mount's env-only read was not, so the rule moved to the one
    predicate every feature gate now calls rather than staying a second
    implementation of it here.
    """
    from . import site_store

    return site_store.feature_enabled(conn, settings, "ai_cli_providers")


def cli_path(conn: sqlite3.Connection, name: str, settings: Any = None) -> str:
    """The executable for a CLI provider, in the order the page implies.

    1. The path an admin TYPED. It is the override, so it wins even when the
       wizard has installed something: an admin who points at a binary is
       telling us about their host, and being second-guessed by a download is
       exactly the surprise this whole page exists to avoid.
    2. The one the SET UP wizard installed under `<data>/tools`, at the
       customer's click, from the publisher (2026-08-18, `cli_tools.py`).
    3. Whatever is on PATH, which is how a customer who installed it in the
       container themselves has always been found.

    `settings` is optional so a caller that only has a connection (an older
    test, a probe with nothing to install into) still gets 1 and 3.
    """
    provider = spec(name)
    configured = get_setting(conn, provider.path_setting, "").strip()
    if configured:
        return configured if Path(configured).is_file() else ""
    installed = cli_tools.cli_binary(settings, name) if settings is not None else ""
    if installed:
        return installed
    return shutil.which(provider.binary) or ""


# --------------------------------------------------------------- CLI probing
# Two questions, two costs. "Is it installed" is `--version` (fast, and the
# answer changes only when somebody installs something). "Is it signed in" is
# a real one-token call, because a logged-out CLI is installed and version-able
# and useless -- exactly the failure this page exists to show BEFORE an editor
# submits a twenty-minute job.
#
# Cached, per provider, with a TTL: the chain re-resolves on EVERY ytdl AI
# call, and a subprocess per call would be a fork bomb on a busy job. The
# Test button forces a fresh probe, which is what an admin who has just run
# the login command needs.

PROBE_TTL_SECONDS = 600.0
VERSION_TIMEOUT = 10.0
LOGIN_PROBE_TIMEOUT = 60.0
# One token of answer, and no data: the probe must not be able to leak
# anything if the CLI is misconfigured, and it must be the cheapest call the
# provider bills.
PROBE_PROMPT = "Reply with the two characters: ok"

_probe_cache: dict[str, dict] = {}
_probe_lock = threading.Lock()


def _cached_probe(name: str) -> dict | None:
    with _probe_lock:
        entry = _probe_cache.get(name)
        if entry and (time.monotonic() - entry["at"]) < PROBE_TTL_SECONDS:
            return dict(entry["value"])
    return None


def _store_probe(name: str, value: dict) -> None:
    with _probe_lock:
        _probe_cache[name] = {"at": time.monotonic(), "value": dict(value)}


def reset_probe_cache() -> None:
    """Forget every cached CLI answer (tests, and any write that could change
    one -- a new path setting, the feature flag being turned on)."""
    with _probe_lock:
        _probe_cache.clear()


def _cli_argv(name: str, path: str) -> list[str]:
    provider = spec(name)
    raw = os.environ.get(provider.probe_args_env, "") or provider.default_probe_args
    return [path] + shlex.split(raw)


def _probe_env(settings: Any = None, name: str = "") -> dict:
    """The environment a probe runs in: this container's, MINUS the API keys,
    PLUS the wizard's `$HOME` and token when there is one.

    A CLI provider is chosen because the customer wants their SUBSCRIPTION
    used. Claude Code prefers `ANTHROPIC_API_KEY` when it finds one, so a
    probe that inherited it would answer "signed in" about a key rather than
    about the login -- and would bill the wrong account to say so.

    ONE helper since 2026-08-18 (`cli_tools.cli_env`): the probe, the Test
    button and the real ytdl call must agree about which `$HOME` the CLI reads
    its credentials from, or the chip on this page is about a different
    account than the one a job spends.
    """
    return cli_tools.cli_env(settings, name)


def _run(argv: list[str], stdin: str | None, timeout: float, env: dict | None = None):
    """One subprocess. argv, never a shell; the customer's binary, never ours."""
    return subprocess.run(                                  # noqa: S603
        argv, input=stdin, capture_output=True, text=True, timeout=timeout,
        env=_probe_env() if env is None else env,
    )


def probe_cli(conn: sqlite3.Connection, name: str, *, force: bool = False,
              settings: Any = None) -> dict:
    """{installed, signed_in, path, version, detail} for one CLI provider.

    Blocking (two subprocesses at worst) -- call it off the event loop.
    Never raises: every failure is a state this dict can describe, because
    the Settings page has to render SOMETHING for a CLI that is halfway
    installed, and a 500 tells an admin nothing they can act on.
    """
    if not force:
        cached = _cached_probe(name)
        if cached is not None:
            return cached
    provider = spec(name)
    path = cli_path(conn, name, settings)
    if not path and settings is None:
        # A settings-less caller cannot see the wizard's install, so its "not
        # installed" is an answer about ITS view, not about the container.
        # Never let that view into the shared cache, where the Settings page
        # and the ytdl lookup (both of which do pass settings) would read it
        # as the truth (2026-08-18).
        return {"installed": False, "signed_in": False, "path": "", "version": "",
                "detail": f"not installed: no `{provider.binary}` on this container's PATH."}
    env = _probe_env(settings, name)
    result = {"installed": False, "signed_in": False, "path": path,
              "version": "", "detail": ""}
    if not path:
        # The old text told an admin to open a shell on the dashboard host.
        # The owner's answer to that, 2026-08-18, was "this is too complex for
        # most users" -- so it names the button that does it for them, and
        # keeps the manual path as the second sentence for the deployments
        # that already work that way.
        result["detail"] = (
            f"not installed: no `{provider.binary}` on this container's PATH. "
            f"Click SET UP to install it from the publisher, or set the full "
            f"path of a copy you installed yourself.")
        _store_probe(name, result)
        return result
    try:
        proc = _run([path, "--version"], None, VERSION_TIMEOUT, env)
    except (OSError, subprocess.SubprocessError) as exc:
        result["detail"] = f"could not run {path}: {type(exc).__name__}"
        _store_probe(name, result)
        return result
    if proc.returncode != 0:
        result["detail"] = (proc.stderr or proc.stdout or "").strip()[:200]
        _store_probe(name, result)
        return result
    result["installed"] = True
    first_line = ((proc.stdout or "").strip().splitlines() or [""])[0]
    result["version"] = first_line[:120]

    try:
        probe = _run(_cli_argv(name, path), PROBE_PROMPT, LOGIN_PROBE_TIMEOUT, env)
    except subprocess.TimeoutExpired:
        result["detail"] = (f"{provider.label} did not answer a one-token probe "
                            f"within {LOGIN_PROBE_TIMEOUT:.0f}s")
        _store_probe(name, result)
        return result
    except (OSError, subprocess.SubprocessError) as exc:
        result["detail"] = f"could not run {path}: {type(exc).__name__}"
        _store_probe(name, result)
        return result
    if probe.returncode == 0 and (probe.stdout or "").strip():
        result["signed_in"] = True
    else:
        detail = (probe.stderr or probe.stdout or "").strip()[:200]
        result["detail"] = detail or "the CLI answered nothing"
        # The login is an interactive OAuth in a browser. Until 2026-08-18
        # this page could only print the command for an admin to run on the
        # host; the wizard (`cli_tools.py`) now drives it through a pty and
        # relays the URL and the code, so the command stays here as the manual
        # fallback rather than as the only answer.
        result["login_command"] = provider.login_command
    _store_probe(name, result)
    return result


# ------------------------------------------------------------- the resolver

@dataclass(frozen=True)
class ProviderChoice:
    """What the ytdl app will use. `name` is "" when nothing is available --
    a state the Settings page shows and the ytdl app reports as
    `claude_auth:`, never a silent fallback to something nobody chose."""

    name: str
    label: str
    reason: str
    pinned: bool = False

    @property
    def ok(self) -> bool:
        return bool(self.name)


def resolve_provider(availability: Mapping[str, bool], preference: str = AUTO) -> ProviderChoice:
    """The chain, as a pure function of "what is available" + "what is pinned".

    Kept free of settings, connections and subprocesses ON PURPOSE: this is
    the rule the whole feature turns on, and it is worth being able to test
    all 32 availability combinations in a table without a filesystem
    (tests/test_ai_providers.py does exactly that).

    A PIN THAT IS NOT AVAILABLE IS A REFUSAL. Falling through to the next
    provider would spend a key the admin did not choose, on a service they may
    have deliberately pinned away from (a data-residency answer, a spend cap,
    a contract). Loud and stopped beats quiet and wrong.
    """
    pref = (preference or AUTO).strip() or AUTO
    if pref != AUTO:
        if pref not in PROVIDER_ORDER:
            return ProviderChoice("", "", f"{pref!r} is not a known AI provider", True)
        if availability.get(pref):
            return ProviderChoice(pref, PROVIDERS[pref].label,
                                  "pinned by an admin", True)
        return ProviderChoice(
            "", "",
            f"{PROVIDERS[pref].label} is pinned but not available. Nothing else "
            f"will be used in its place -- clear the pin to fall back to the "
            f"chain.", True)
    for name in PROVIDER_ORDER:
        if availability.get(name):
            higher = [PROVIDERS[n].label for n in PROVIDER_ORDER
                      if n == name or availability.get(n)]
            reason = ("first available in the chain"
                      if len(higher) == 1 else
                      "first available in the chain (ahead of "
                      + ", ".join(l for l in higher if l != PROVIDERS[name].label) + ")")
            return ProviderChoice(name, PROVIDERS[name].label, reason)
    return ProviderChoice("", "", "no provider has a working credential")


def provider_states(
    conn: sqlite3.Connection, settings: Any, *, probe: bool = True,
    force: bool = False, only: Sequence[str] | None = None,
) -> list[dict]:
    """One row per provider, in chain order, for the API and the page.

    `probe=False` is for a caller that must not spend a subprocess (or a
    token) -- it reports a CLI as `unknown` rather than guessing, which the
    page renders as "test it".

    `only` narrows the rows to those providers, keeping each one's real chain
    RANK. It exists for `resolved()` (ytdl-web-5, 2026-08-21): probing a CLI
    is a real billed/subscription call, and the resolver has no business
    spending one on a provider the admin has pinned away from.
    """
    allow_cli = cli_enabled(conn, settings)
    rows: list[dict] = []
    for rank, name in enumerate(PROVIDER_ORDER, start=1):
        if only is not None and name not in only:
            continue
        provider = PROVIDERS[name]
        row = {
            "name": name,
            "label": provider.label,
            "kind": provider.kind,
            "rank": rank,
            "status": ST_NOT_CONFIGURED,
            "available": False,
            "detail": "",
        }
        if provider.kind == "api":
            value, source = read_key(settings, name)
            row.update({
                "env_var": provider.env_var,
                "key_present": bool(value),
                "key_source": source,
                # A MASK. The value itself never leaves this process except
                # towards the ytdl app.
                "masked": mask(value),
                "editable": source != "env",
                "detail": ("set by the deployment (%s in the container's "
                           "environment); the value here cannot change it"
                           % provider.env_var) if source == "env" else "",
            })
            row["available"] = bool(value)
            row["status"] = ST_AVAILABLE if value else ST_NOT_CONFIGURED
        else:
            row.update({
                "path_setting": provider.path_setting,
                "path": "",
                "version": "",
                "login_command": provider.login_command,
                "configured_path": get_setting(conn, provider.path_setting, ""),
                "installable": False,
                "install_detail": "",
                "installed_by_wizard": False,
                "installed_version": "",
                "signin_state": "idle",
                "signed_in_account": "",
            })
            if allow_cli:
                # The wizard's view of this tool, and it costs no subprocess:
                # two small file reads and an in-memory session. The page needs
                # it on the ROW (not only inside the stepper) to draw the chip
                # and to choose between [ SET UP ] and the buttons that replace
                # it. Only for an ENABLED site, so an off one touches nothing.
                wizard = cli_tools.setup_snapshot(conn, settings, name)
                row.update({
                    "installable": wizard["supported"],
                    "install_detail": wizard["unsupported_detail"],
                    "installed_by_wizard": wizard["install"]["installed"],
                    "installed_version": wizard["install"]["installed_version"],
                    "signin_state": wizard["signin"]["state"],
                    "signed_in_account": wizard["signin"].get("account", ""),
                })
            if not allow_cli:
                # NOT PROBED, not just hidden: an off site must not run
                # somebody's agent binary to find out whether it would have
                # worked.
                row["status"] = ST_DISABLED
                # Names the control on THIS page, not the config key: the
                # owner read "[features] ai_cli_providers" and went looking
                # for a features page that does not exist (2026-08-18).
                row["detail"] = ("CLI providers are off for this site. Tick "
                                 "'Allow CLI providers (Claude Code, Codex)' "
                                 "below to enable them")
            elif not probe:
                row["status"] = ST_UNKNOWN
            else:
                probed = probe_cli(conn, name, force=force, settings=settings)
                row["path"] = probed["path"]
                row["version"] = probed["version"]
                row["detail"] = probed["detail"]
                if not probed["installed"]:
                    row["status"] = ST_NOT_INSTALLED
                elif not probed["signed_in"]:
                    row["status"] = ST_NOT_SIGNED_IN
                else:
                    row["status"] = ST_AVAILABLE
                    row["available"] = True
        row["status_label"] = STATUS_LABELS[row["status"]]
        rows.append(row)
    return rows


def availability(rows: list[dict]) -> dict[str, bool]:
    return {row["name"]: bool(row["available"]) for row in rows}


def resolved(conn: sqlite3.Connection, settings: Any, *, probe: bool = True) -> ProviderChoice:
    """Which provider an AI call will use.

    THE PIN IS READ FIRST (ytdl-web-5, 2026-08-21). This used to build the
    whole table before `resolve_provider` ever looked at the preference, so a
    site with `ai_cli_providers` on and an API provider pinned spent a real
    one-token Claude Code / Codex call -- the very subscription the admin
    pinned away from -- every time the 600 s probe cache expired, and blocked
    the ytdl worker for up to 70 s inside a job to learn an availability it
    then ignored. With a pin there is exactly one provider whose availability
    can change the answer, so exactly one is probed; `resolve_provider` still
    REFUSES a pin that is not available rather than falling through the chain.

    With no pin this is unchanged: the ordered probe, whose reason string
    names what it chose over what.
    """
    pref = preference(conn)
    if pref != AUTO:
        rows = provider_states(conn, settings, probe=probe, only=(pref,))
        return resolve_provider(availability(rows), pref)
    rows = provider_states(conn, settings, probe=probe)
    return resolve_provider(availability(rows), pref)


# ------------------------------------------------- what the ytdl app is told

def lookup_payload(conn: sqlite3.Connection, settings: Any) -> dict:
    """The mapping `ytdlweb.ai_backend.current_provider()` consumes.

    THIS IS THE ONE PLACE A KEY CROSSES OUT OF THIS MODULE, and it goes to a
    sub-app in this same process (dashboard/ytdl.py mounts it), never over a
    socket. Called per AI call, so a key entered on Settings works on the next
    job and a cleared one stops working just as fast.
    """
    choice = resolved(conn, settings)
    if not choice.ok:
        return {"provider": "", "detail": choice.reason}
    payload: dict[str, Any] = {"provider": choice.name, "detail": choice.reason,
                               "cli_enabled": cli_enabled(conn, settings)}
    provider = PROVIDERS[choice.name]
    if provider.kind == "api":
        payload["api_key"] = read_key(settings, choice.name)[0]
    else:
        payload["cli_path"] = cli_path(conn, choice.name, settings)
        # The OVERLAY, not the whole environment: the ytdl app runs in this
        # same process and builds its base from the same os.environ, so this
        # carries only what this module knows and it does not (the wizard's
        # $HOME, and the OAuth token when the setup-token strategy is what
        # signed the CLI in). Without it the job would run against a different
        # $HOME than the probe on the Settings page and be told to log in.
        payload["cli_env"] = cli_tools.cli_env_overlay(settings, choice.name)
    return payload


def make_lookup(settings: Any):
    """A zero-argument callable the ytdl mount installs. Opens (and closes) its
    own connection per call: it is invoked from the ytdl WORKER THREAD, which
    has no request and therefore no `Depends(get_conn)` connection, and a
    long-lived connection shared with that thread is how a "database is
    locked" appears under a job."""
    from . import db as dbmod

    def lookup() -> dict:
        conn = dbmod.connect(settings.db_path)
        try:
            return lookup_payload(conn, settings)
        finally:
            conn.close()

    return lookup


# ------------------------------------------------------------------- routes
# Admin-only, exactly like every other /api/v1/admin/* route; CSRF comes from
# app.csrf_gate, which covers these paths with no exemption. A key is only
# ever in a JSON BODY -- never a query string, which lands in access logs,
# browser history and any proxy in between.

def _require_admin(request: Request) -> str:
    settings = request.app.state.settings
    user = auth.get_session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="log in first")
    if not auth.is_admin(settings, user):
        raise HTTPException(status_code=403, detail="admins only")
    return user


def _known(name: str) -> ProviderSpec:
    if name not in PROVIDERS:
        raise HTTPException(status_code=404, detail=f"unknown AI provider {name!r}")
    return PROVIDERS[name]


def _snapshot(conn: sqlite3.Connection, settings: Any, *, probe: bool = True,
              force: bool = False) -> dict:
    rows = provider_states(conn, settings, probe=probe, force=force)
    choice = resolve_provider(availability(rows), preference(conn))
    return {
        "providers": rows,
        "order": list(PROVIDER_ORDER),
        "preference": preference(conn),
        "cli_enabled": cli_enabled(conn, settings),
        "cli_tos_note": CLI_TOS_NOTE,
        "resolved": {"name": choice.name, "label": choice.label,
                     "reason": choice.reason, "pinned": choice.pinned},
    }


@router.get("/admin/ai-providers")
async def api_ai_providers(
    request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    """Every provider's status, the pin, and the RESOLVED choice (a name,
    never a credential)."""
    _require_admin(request)
    settings = request.app.state.settings
    # Off the event loop: a CLI probe is two subprocesses, and this is the
    # one route that may run them.
    return await run_in_threadpool(_snapshot, conn, settings)


class KeyIn(BaseModel):
    # In the BODY, never the path or a query. Capped well under the route's
    # 4 MiB default so a paste accident is a 422 and not a file write.
    key: str = Field(max_length=MAX_KEY_CHARS * 4)


@router.put("/admin/ai-providers/{name}/key")
async def api_set_ai_key(
    name: str, payload: KeyIn, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    admin = _require_admin(request)
    provider = _known(name)
    settings = request.app.state.settings
    if provider.kind != "api":
        raise HTTPException(status_code=400,
                            detail=f"{provider.label} is a CLI -- it has no API key. "
                                   f"Sign it in on the dashboard host instead.")
    if read_key(settings, name)[1] == "env":
        raise HTTPException(
            status_code=409,
            detail=(f"{provider.env_var} is set in this container's environment "
                    f"and always wins. Change it there (or unset it) -- a key "
                    f"saved here would never be used."))
    try:
        set_key(settings, name, payload.key)
    except ProviderError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # The provider, never the key.
    log.info("admin %r set the %s key", admin, name)
    return await run_in_threadpool(_snapshot, conn, settings)


@router.delete("/admin/ai-providers/{name}/key")
async def api_clear_ai_key(
    name: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    admin = _require_admin(request)
    provider = _known(name)
    settings = request.app.state.settings
    if provider.kind != "api":
        raise HTTPException(status_code=400,
                            detail=f"{provider.label} is a CLI -- it has no API key")
    try:
        clear_key(settings, name)
    except ProviderError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    log.info("admin %r cleared the %s key", admin, name)
    return await run_in_threadpool(_snapshot, conn, settings)


@router.post("/admin/ai-providers/{name}/test")
async def api_test_ai_provider(
    name: str, request: Request, conn: sqlite3.Connection = Depends(get_conn)
) -> dict:
    """One tiny live call. -> {ok, detail} -- never the key, never a token
    count, never the model's answer beyond "it answered"."""
    _require_admin(request)
    _known(name)
    settings = request.app.state.settings
    result = await run_in_threadpool(test_provider, conn, settings, name)
    return result


class PathIn(BaseModel):
    # A filesystem path on the dashboard host, not a URL and not a command
    # line -- it is exec'd as argv[0], never through a shell.
    path: str = Field(default="", max_length=1024)


@router.put("/admin/ai-providers/{name}/path")
async def api_set_ai_cli_path(
    name: str, payload: PathIn, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    """Where the CUSTOMER installed their CLI, when it is not on PATH.

    Blank clears it (back to the wizard's install, else `shutil.which`). A
    TYPED PATH STILL WINS over anything the wizard installed (`cli_path`): an
    admin who points at a binary is telling us about their host, and being
    silently overridden by a download is the surprise this page exists to
    avoid. An admin who types a path to something that is not there gets
    "not installed", never a download -- fetching happens only at the SET UP
    button, from the publisher, with a checksum (`cli_tools.py`).
    """
    admin = _require_admin(request)
    provider = _known(name)
    settings = request.app.state.settings
    if provider.kind != "cli":
        raise HTTPException(status_code=400,
                            detail=f"{provider.label} is an API provider -- it has "
                                   f"no executable path")
    value = str(payload.path or "").strip()
    if any(ord(ch) < 32 for ch in value):
        raise HTTPException(status_code=422, detail="that path contains control characters")
    set_setting(conn, provider.path_setting, value, updated_by=admin)
    conn.commit()
    # The answer must reflect the NEW path, not a probe of the old one.
    reset_probe_cache()
    log.info("admin %r set the %s path to %r", admin, name, value)
    return await run_in_threadpool(_snapshot, conn, settings)


class PreferenceIn(BaseModel):
    preference: str = Field(default=AUTO, max_length=64)


@router.put("/admin/ai-providers/preference")
async def api_set_ai_preference(
    payload: PreferenceIn, request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
) -> dict:
    admin = _require_admin(request)
    settings = request.app.state.settings
    try:
        value = set_preference(conn, payload.preference, updated_by=admin)
    except ProviderError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    conn.commit()
    log.info("admin %r set the AI provider preference to %r", admin, value)
    return await run_in_threadpool(_snapshot, conn, settings)


# ------------------------------------------------------------- the Test call

def test_provider(conn: sqlite3.Connection, settings: Any, name: str) -> dict:
    """Prove a credential works, as cheaply as the provider allows.

    API providers: a MODEL LIST (Anthropic, OpenAI) or a one-token completion
    (DeepSeek, which has no list endpoint worth the round trip). A key-shape
    check would answer the wrong question -- "the key is set and does not
    work" is the failure this button exists for.

    CLI providers: the same probe the page's status chip uses, forced.

    Never raises, and never returns anything derived from the key: {ok,
    detail} where detail is our words plus the service's own message.
    """
    provider = spec(name)
    if provider.kind == "cli":
        if not cli_enabled(conn, settings):
            return {"ok": False, "detail": "CLI providers are off for this site "
                                           "([features] ai_cli_providers)"}
        # WITH settings: without them the probe cannot see the wizard's own
        # install under <data>/tools, answers "not installed", and -- because
        # a forced probe is cached -- flips the status row to the same wrong
        # answer, sending the downloader back to the next provider in the
        # chain. Owner hit exactly that a minute after a successful sign-in
        # (2026-08-18).
        probed = probe_cli(conn, name, force=True, settings=settings)
        if probed["signed_in"]:
            return {"ok": True, "detail": f"{provider.label} answered "
                                          f"({probed['version'] or probed['path']})"}
        if not probed["installed"]:
            return {"ok": False, "detail": probed["detail"] or
                    f"no `{provider.binary}` on this host"}
        return {"ok": False,
                "detail": (f"installed but not signed in. Click SET UP and finish "
                           f"the sign-in step, or run `{provider.login_command}` on "
                           f"this host. [{probed['detail']}]")}

    key, source = read_key(settings, name)
    if not key:
        return {"ok": False, "detail": f"no key is configured for {provider.label}"}
    try:
        detail = _live_api_check(name, key)
    except Exception as exc:  # noqa: BLE001 - a Test button must never 500
        return {"ok": False, "detail": f"{type(exc).__name__}: {str(exc)[:200]}"}
    if detail is None:
        return {"ok": True,
                "detail": f"{provider.label} accepted the key"
                          + (" (set by the deployment)" if source == "env" else "")}
    return {"ok": False, "detail": detail}


# Where each API provider is checked, and with what. urllib rather than an SDK
# for the two OpenAI-compatible ones -- no new dependency for one GET (the
# same call the ytdl app makes with plain urllib; see ai_backend.py).
_TEST_TIMEOUT = 20.0


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A credential must never be replayed to a Location somebody else chose
    (docs/GOTCHAS.md §12's no-redirect rule, applied to the one call in this
    module that carries a customer's API key)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _live_api_check(name: str, key: str) -> str | None:
    """None when the key works, else a one-line reason. Never logs the key."""
    if name == ANTHROPIC_API:
        url = (os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/")
               or "https://api.anthropic.com") + "/v1/models?limit=1"
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    elif name == OPENAI_API:
        url = (os.environ.get("OPENAI_BASE_URL", "").rstrip("/")
               or "https://api.openai.com/v1") + "/models"
        headers = {"Authorization": f"Bearer {key}"}
    else:
        url = (os.environ.get("DEEPSEEK_BASE_URL", "").rstrip("/")
               or "https://api.deepseek.com") + "/models"
        headers = {"Authorization": f"Bearer {key}"}

    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        # No redirect handler installed: a credential must not be replayed to
        # a Location we did not choose (docs/GOTCHAS.md §12).
        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(request, timeout=_TEST_TIMEOUT) as resp:
            resp.read(4096)
        return None
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001
            body = ""
        if exc.code in (401, 403):
            return f"the key was refused (HTTP {exc.code}). {body}"
        return f"HTTP {exc.code} from the provider. {body}"
    except (TimeoutError, OSError) as exc:
        return (f"could not reach the provider from this container "
                f"({type(exc).__name__}: {str(exc)[:160]})")
