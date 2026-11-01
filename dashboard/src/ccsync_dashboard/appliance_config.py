"""Settings an appliance admin enters in the wizard instead of editing
container environment (CR-363, GL-07, 2026-10-07; PRAC-6).

THE PROBLEM. Six wizard tasks (`admin`, `syncthing`, `nas_connect`,
`release_key`, `software`, `secrets`) could only be fixed by "set DASH_X in
the container's environment, then redeploy". compose.appliance.yaml says
"NONE OF IT SHOULD BE EDITED" and APPLIANCE_INSTALL.md never explains how
anyone would, so two REQUIRED steps (Admin, Sync engine) were a wall for a
customer who installs this themselves, and the other four were a support
ticket each.

THE SHAPE OF THE FIX. A small JSON file, `<data>/secrets/appliance_config.json`
(0600, the directory every other generated credential lives in), holding values
for an ALLOW-LISTED set of the same environment variables. `apply_overlay()`
copies them into the process environment at boot, BEFORE `Settings.from_env()`
reads it, and ONLY for a variable the real environment leaves blank. So:

* a deployment that sets the variable in compose (the studio, every TrueNAS
  install) is untouched: the environment always wins, exactly as it does for
  `secrets_boot.ensure_secrets`;
* the wizard's forms write this file and restart the process (exit 75, which
  run.sh and `restart: unless-stopped` both act on), because `Settings` is a
  frozen dataclass built once and "read them live" would mean a second source
  of truth for every reader;
* nothing here is a new way to set anything an env var could not already set.

Secrets (an API key, a password) are stored here and never echoed: a form
shows "set" or "not set", and leaving a secret field blank keeps what is
stored. The file is never logged, never in an API response and never in a
support bundle.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping
from urllib.parse import urlsplit

log = logging.getLogger("ccsync.dashboard.appliance_config")

FILENAME = "appliance_config.json"


class ConfigError(ValueError):
    """A refusal written for the admin who typed the value."""


@dataclass(frozen=True)
class Field:
    env: str
    label: str
    hint: str = ""
    secret: bool = False
    # Rendered as a select when set.
    choices: tuple[str, ...] = ()
    placeholder: str = ""


# ----------------------------------------------------------------- validators

_NAME = re.compile(r"^[A-Za-z0-9._@\\-]{1,64}$")
_HOST = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.\-]{0,251}[A-Za-z0-9])?(:\d{1,5})?$")


def _csv_names(value: str) -> str:
    names = [n.strip() for n in value.replace(";", ",").split(",") if n.strip()]
    if not names:
        raise ConfigError("enter at least one account name")
    for name in names:
        if not _NAME.match(name):
            raise ConfigError(f"{name!r} is not a plain account name (letters, digits, . _ - only)")
    return ",".join(names)


def _url(value: str, *, https_only: bool = False) -> str:
    parts = urlsplit(value)
    if parts.scheme not in (("https",) if https_only else ("http", "https")) or not parts.netloc:
        raise ConfigError("enter a full web address starting with "
                          + ("https://" if https_only else "http:// or https://"))
    if parts.username or parts.password:
        raise ConfigError("the address must not contain a username or password")
    return value.rstrip("/")


def _host(value: str) -> str:
    if not _HOST.match(value):
        raise ConfigError("enter the NAS's name or IP address, with no http:// in front")
    return value


def _pubkeys(value: str) -> str:
    from .settings import _looks_like_ed25519_pubkey

    keys = [k for k in value.replace(",", " ").split() if k]
    if not keys:
        raise ConfigError("paste the update signing key")
    for key in keys:
        if not _looks_like_ed25519_pubkey(key):
            raise ConfigError("that is not an update signing key (it should be 44 characters "
                              "of letters and digits ending in =)")
    return " ".join(keys)


def _cert_pin(value: str) -> str:
    """The NAS certificate pin: `sha256:` + 64 hex, or `1` (verify against the
    system CA bundle, for a NAS with a real certificate). There is deliberately
    no way to turn verification OFF from the wizard (CR-368 follow-up,
    2026-10-07); blank means record the certificate on the first connect."""
    from .nas import tls_pin

    if value.strip() == "1":
        return "1"
    try:
        digest = tls_pin.parse_pin(value)
    except ValueError as exc:
        raise ConfigError(str(exc)) from None
    if not digest:
        raise ConfigError("enter sha256: followed by the certificate's 64-digit fingerprint, "
                          "or leave this blank to record it on the first connection")
    return tls_pin.PREFIX + digest


def _secret(value: str) -> str:
    if len(value) > 400 or any(ord(c) < 32 for c in value):
        raise ConfigError("that value is too long or contains control characters")
    return value


_VALIDATORS: dict[str, Callable[[str], str]] = {
    "DASH_ADMIN_USERS": _csv_names,
    "SYNCTHING_GUI_URL": _url,
    "DASH_NAS_HOST": _host,
    "DASH_NAS_USER": lambda v: _NAME.match(v) and v or _raise("that is not a plain account name"),
    "DASH_NAS_API_KEY": _secret,
    "DASH_NAS_API_KEY_USER": lambda v: _NAME.match(v) and v or _raise(
        "that is not a plain account name"),
    "DASH_NAS_PW": _secret,
    "DASH_NAS_VERIFY_SSL": _cert_pin,
    "DASH_NAS_KIND": lambda v: v if v in ("truenas", "synology") else _raise(
        "choose truenas or synology"),
    "DASH_RELEASE_PUBKEYS": _pubkeys,
    "DASH_RELEASE_FEED_URL": lambda v: _url(v, https_only=True),
}


def _raise(message: str) -> str:
    raise ConfigError(message)


# What each wizard task may store. The allow-list is the whole security story:
# a variable that is not named here cannot be written, whatever a request says.
FORMS: dict[str, tuple[Field, ...]] = {
    "admin": (
        Field("DASH_ADMIN_USERS", "admin account name",
              "The sign-in account that may administer this dashboard. It must NOT be "
              "the NAS's own admin account. Several can be given, separated by commas.",
              placeholder="alex"),
    ),
    "syncthing": (
        Field("SYNCTHING_GUI_URL", "sync engine address",
              "Where this dashboard reaches the sync engine. The bundled one is "
              "http://tailscale:8384.", placeholder="http://tailscale:8384"),
    ),
    "nas_connect": (
        Field("DASH_NAS_KIND", "NAS type", choices=("truenas", "synology")),
        Field("DASH_NAS_HOST", "NAS address", "The NAS's name or IP address.",
              placeholder="nas.local"),
        Field("DASH_NAS_USER", "NAS admin account",
              "Synology only. TrueNAS uses the key below.", placeholder="admin"),
        Field("DASH_NAS_API_KEY", "NAS API key",
              "TrueNAS only: a key made for this dashboard, never the admin password.",
              secret=True),
        # CR-365 (2026-10-07): the JSON-RPC login names the account the key was
        # made for, which is not the admin. REQUIRED with a TrueNAS key (round 2,
        # 2026-10-07): TrueNAS 26 has only auth.login_ex, which needs the name.
        Field("DASH_NAS_API_KEY_USER", "NAS API key account",
              "TrueNAS only: the account the key above was made for (the name given "
              "to create_api_key.py --username, or the account that owns the key "
              "if you made it by hand). Required with a TrueNAS key.",
              placeholder="ccsync-svc"),
        Field("DASH_NAS_PW", "NAS admin password", "Synology only.", secret=True),
        Field("DASH_NAS_VERIFY_SSL", "NAS certificate fingerprint",
              "Optional. Leave blank and the NAS's certificate is recorded the first "
              "time this dashboard connects (it is logged, and a different one is "
              "refused afterwards). Or enter sha256: and the 64-digit fingerprint to "
              "pin it yourself.", placeholder="sha256:"),
    ),
    "release_key": (
        Field("DASH_RELEASE_PUBKEYS", "update signing key",
              "The vendor's public key. Builds signed by anything else are refused."),
    ),
    "software": (
        Field("DASH_RELEASE_FEED_URL", "vendor update feed",
              "The https address the vendor publishes builds at.",
              placeholder="https://"),
    ),
}

# The names an operator (not a customer) would use, for a fold-out.
OPERATOR_NOTES: dict[str, str] = {
    task: ", ".join(f.env for f in fields) for task, fields in FORMS.items()
}

ALLOWED: frozenset[str] = frozenset(f.env for fields in FORMS.values() for f in fields)
SECRET_ENVS: frozenset[str] = frozenset(
    f.env for fields in FORMS.values() for f in fields if f.secret)

_write_lock = threading.Lock()


# -------------------------------------------------------------------- storage

def _data_dir(env: Mapping[str, str] | None = None, data_dir: Path | None = None) -> Path:
    if data_dir is not None:
        return Path(data_dir)
    env = os.environ if env is None else env
    return Path(env.get("DASH_DB_PATH", "/data/dashboard.db")).parent


def config_path(env: Mapping[str, str] | None = None, data_dir: Path | None = None) -> Path:
    return _data_dir(env, data_dir) / "secrets" / FILENAME


def load(env: Mapping[str, str] | None = None, data_dir: Path | None = None) -> dict[str, str]:
    """Stored values, allow-listed. A missing or damaged file is `{}`."""
    try:
        raw = json.loads(config_path(env, data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {k: str(v) for k, v in raw.items() if k in ALLOWED and str(v).strip()}


def apply_overlay(env: MutableMapping[str, str] | None = None,
                  data_dir: Path | None = None) -> list[str]:
    """Copy stored values into `env` (default `os.environ`) where it has none.
    Returns the NAMES applied, for the boot log. Never raises, never logs a
    value."""
    target = os.environ if env is None else env
    applied: list[str] = []
    try:
        stored = load(target, data_dir)
    except Exception:                                                  # noqa: BLE001
        log.warning("could not read the stored wizard settings", exc_info=True)
        return applied
    for key, value in stored.items():
        if not str(target.get(key, "")).strip():
            target[key] = value
            applied.append(key)
    if applied:
        log.info("wizard settings applied: %s", ", ".join(sorted(applied)))
    return applied


def view(task_id: str, env: Mapping[str, str] | None = None,
         data_dir: Path | None = None) -> list[dict[str, Any]]:
    """What a form needs to draw itself, with no secret in it: a secret field
    reports only whether something is stored."""
    try:
        stored = load(env, data_dir)
    except Exception:                                                  # noqa: BLE001
        stored = {}
    source = os.environ if env is None else env
    out = []
    for f in FORMS.get(task_id, ()):
        have = bool(stored.get(f.env)) or bool(str(source.get(f.env, "")).strip())
        out.append({
            "env": f.env, "label": f.label, "hint": f.hint, "secret": f.secret,
            "choices": list(f.choices), "placeholder": f.placeholder,
            "set": have,
            # A non-secret value may be shown back, so an admin can correct it.
            "value": "" if f.secret else stored.get(f.env, ""),
        })
    return out


def _effective(key: str, stored: Mapping[str, str], env: Mapping[str, str] | None) -> str:
    source = os.environ if env is None else env
    return (str(source.get(key, "")).strip() or stored.get(key, "")).strip()


def _cross_checks(task_id: str, values: Mapping[str, Any],
                  env: Mapping[str, str] | None, data_dir: Path | None) -> None:
    """Refusals that depend on two settings at once (GL-18, CR-368 follow-up,
    2026-10-07). The base-rig deploy enforces these in install_dashboard_app;
    a self-installing customer never runs it, so the wizard does:

    * the dashboard's admin is not the NAS's admin account (a dashboard login
      would otherwise be the NAS's root-equivalent credential);
    * a TrueNAS site gives an API key, never the admin password."""
    stored = load(env, data_dir)

    def pick(key: str) -> str:
        if key in values and str(values[key] or "").strip():
            return str(values[key]).strip()
        if key == "DASH_NAS_API_KEY_USER" and key in values:
            # A blank PLAIN field is "clear it" in save(), so the post-save
            # value is blank (or the environment's), never the stored one
            # (CR-365 round 2, GL-11, 2026-10-07).
            source = os.environ if env is None else env
            return str(source.get(key, "")).strip()
        return _effective(key, stored, env)

    if task_id in ("admin", "nas_connect"):
        nas_user = pick("DASH_NAS_USER").lower()
        admins = {n.strip().lower() for n in pick("DASH_ADMIN_USERS").split(",") if n.strip()}
        if nas_user and nas_user in admins:
            raise ConfigError(
                "the dashboard's admin account must not be the NAS's own admin account "
                f"({nas_user!r}). Make a separate sign-in for the dashboard admin, so a "
                "stolen dashboard login is not the key to the whole NAS.")
    if task_id == "nas_connect":
        kind = pick("DASH_NAS_KIND") or "truenas"
        if kind == "truenas" and str(values.get("DASH_NAS_PW") or "").strip():
            raise ConfigError(
                "a TrueNAS NAS is connected with an API key, never the admin password: "
                "leave the password blank and enter the key made for this dashboard.")
        if (kind == "truenas" and pick("DASH_NAS_API_KEY")
                and not pick("DASH_NAS_API_KEY_USER")):
            raise ConfigError(
                "a TrueNAS API key needs the name of the account it was made for "
                "(NAS API key account): TrueNAS 26 logs a key in by that name and "
                "refuses it without. It is the --username given to create_api_key.py.")


def save(task_id: str, values: Mapping[str, Any], env: Mapping[str, str] | None = None,
         data_dir: Path | None = None) -> list[str]:
    """Validate and store one task's form. Returns the names written.

    Only this task's own fields are accepted. A blank SECRET keeps the stored
    value (the form never shows it back, so blank means "unchanged"); a blank
    plain field clears it. Raises ConfigError, whose text is for the admin.
    """
    fields = {f.env: f for f in FORMS.get(task_id, ())}
    if not fields:
        raise ConfigError("this step has nothing to fill in here")
    unknown = sorted(k for k in values if k not in fields)
    if unknown:
        raise ConfigError(f"not a setting of this step: {', '.join(unknown)}")
    clean: dict[str, str] = {}
    clear: list[str] = []
    _cross_checks(task_id, values, env, data_dir)
    for key, raw in values.items():
        text = str(raw if raw is not None else "").strip()
        if not text:
            if not fields[key].secret:
                clear.append(key)
            continue
        try:
            clean[key] = _VALIDATORS[key](text)
        except ConfigError as exc:
            raise ConfigError(f"{fields[key].label}: {exc}") from None
    if not clean and not clear:
        raise ConfigError("nothing to save")
    from .secrets_boot import write_secret_file

    with _write_lock:
        stored = load(env, data_dir)
        stored.update(clean)
        for key in clear:
            stored.pop(key, None)
        path = config_path(env, data_dir)
        try:
            write_secret_file(path, json.dumps(stored, sort_keys=True) + "\n")
        except OSError as exc:
            raise ConfigError(f"could not store the setting ({exc.strerror or exc})") from None
    return sorted(set(clean) | set(clear))


# -------------------------------------------------------------------- restart

RESTART_DELAY_SECONDS = 1.5


def schedule_restart(settings: Any, delay: float = RESTART_DELAY_SECONDS) -> None:
    """Restart this process shortly, so the HTTP response that asked for it
    still gets home. Exit 75 is what `deploy/run.sh` and the container's
    restart policy both act on (dashboard_update.request_restart). A seam: the
    suite replaces this, because a test that signals its own process is a test
    that kills itself."""
    from . import dashboard_update

    timer = threading.Timer(delay, dashboard_update.request_restart, args=(settings,))
    timer.daemon = True
    timer.start()
