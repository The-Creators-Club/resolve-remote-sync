"""First-boot secrets bootstrap (ZERO_TOUCH_PLAN.md WP D / §3.2, 2026-08-17).

Today every secret this container needs (`DASH_SESSION_SECRET`,
`DASH_REPORT_TOKEN`, `BROLL_INGEST_TOKEN`, `SYNCTHING_API_KEY`,
`CCSYNC_INTERNAL_TOKEN`) is compose env, generated once by
`server/install_dashboard_app.py`'s `openssl rand` and baked into a 0600
`.env` on the NAS host -- which is exactly the "only we build anything, no
customer shell" bar this plan is judged against (§1) breaking: an appliance
customer has no shell to run `openssl` in and no `.env` to edit.

`ensure_secrets()` is the fix: for each of the five, if the environment
already carries it, LEAVE IT ALONE (env always wins -- rotating one by
setting the env var stays possible, exactly as it is today); otherwise load
a previously-generated value from `<data>/secrets/<lowercase name>`, or
generate one with `secrets.token_urlsafe(32)` and persist it there 0600, so a
container restart (routine -- `docker restart`, a host reboot) does not mint
a fresh admin cookie signing key and silently sign every editor out.

It is called from `create_app` **only when the caller did not pass an
explicit `Settings`** -- i.e. only on the `run()` path a real container
takes. Every test in this suite constructs `Settings(...)` directly, so this
module never touches a filesystem during the suite, and a deployment that
already sets all five in its compose env (every deployment today) sees no
behaviour change at all in those five values: the function reads them, finds
them all present, and writes nothing for them. What it does do,
unconditionally, is refresh the two env_file targets for agent A's sidecars
(SPEC WP A: `ccsync-sftp` and the bundled Syncthing) -- those files must
always reflect the CURRENT value of the two secrets those sidecars need,
whether that value came from the environment or from here, because the
sidecar has no other way to learn a rotated key.

Never logs a value -- only which of {env, file, generated} each one came
from.

ONE OF THE FIVE IS NOT LIKE THE OTHERS (DASH-2, resilience sweep 2026-08-28).
"Rotating one by setting the env var stays possible" is true of all five and
CHEAP for four of them. `DASH_SESSION_SECRET` also signs every companion's
machine-identity token, which never expires (CR-86), so changing it 401s the
whole fleet's reports at once until each editor signs in again at their tray.
Rotate it with the old value in `DASH_SESSION_SECRET_PREVIOUS` (accept-only,
comma-separated) and drop that once the fleet page's drain count reaches
zero -- docs/SECRETS.md, "Rotating DASH_SESSION_SECRET".
"""
from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path
from typing import Mapping, MutableMapping

log = logging.getLogger("ccsync.dashboard.secrets_boot")

# Order matters only for the log line; every one is independent.
SECRET_ENV_VARS = (
    "DASH_SESSION_SECRET",
    "DASH_REPORT_TOKEN",
    "BROLL_INGEST_TOKEN",
    "SYNCTHING_API_KEY",
    "CCSYNC_INTERNAL_TOKEN",
)


def _secrets_dir(env: Mapping[str, str]) -> Path:
    """<data dir>/secrets -- data dir is DASH_DB_PATH's parent, default
    /data (settings.py's own default, duplicated here because this runs
    BEFORE Settings exists -- that is the whole point of "before
    Settings.from_env" in the work package: the bootstrap has to know where
    /data is without asking the dataclass it is about to build)."""
    db_path = env.get("DASH_DB_PATH", "/data/dashboard.db")
    return Path(db_path).parent / "secrets"


def _write_secret_file(path: Path, value: str) -> None:
    """0600, POSIX; on Windows (dev only -- the shipped image is Linux) the
    mode argument to os.open is accepted but not enforced, which is a no-op
    rather than a failure -- there is no admin-facing dev workflow on
    Windows that reads this file back, only tests, and tests never call this
    function with a value worth protecting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # best-effort on platforms without POSIX modes


def write_secret_file(path: Path, value: str) -> None:
    """The public name for the 0600 write above (2026-08-18).

    `ai_providers.py` stores the customer's AI keys under the same
    `<data>/secrets/` tree and must use the same hardening -- one
    implementation, so a future fix to it (an ACL on Windows, a fsync, a
    umask) reaches every secret this container writes rather than four of the
    five.
    """
    _write_secret_file(path, value)


def _read_secret_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# The two secrets a SIDECAR also holds, and the `KEY=VALUE` env_file each one
# reads: {env var: (filename, key inside it)}.
#
# dash-admin-2 (2026-08-21): compose.appliance.yaml's `secrets-init` service
# generates these two into `syncthing.env` / `internal.env` BEFORE this
# container starts (the sidecars have no secret generator of their own and
# compose reads an env_file at container start, so somebody has to write them
# first). This module used to look only at `<data>/secrets/<lower env name>`,
# find nothing, GENERATE a second value, and then overwrite `syncthing.env`
# with it -- so Syncthing answered 403 until its container was restarted, and
# the sftp sidecar (which is NOT restarted, and whose token is only read at
# its own startup) presented a token the dashboard had never heard of: every
# `AuthorizedKeysCommand` call 401'd and no editor could authenticate at all.
# Adopting whatever the sidecar file already holds is what makes the three
# parties agree on first boot; the plain file is written too, so the name
# every other reader uses exists from then on.
SIDECAR_ENV_FILES = {
    "SYNCTHING_API_KEY": ("syncthing.env", "STGUIAPIKEY"),
    "CCSYNC_INTERNAL_TOKEN": ("internal.env", "CCSYNC_INTERNAL_TOKEN"),
}


def _read_env_file_value(path: Path, key: str) -> str:
    """One `KEY=VALUE` out of a compose env_file. Tolerant of blank lines,
    comments and `export ` prefixes; never raises."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        name, sep, value = line.partition("=")
        if sep and name.strip() == key:
            return value.strip().strip('"').strip("'")
    return ""


def ensure_secrets(
    env: MutableMapping[str, str] | None = None,
    names: tuple[str, ...] = SECRET_ENV_VARS,
    data_dir: Path | None = None,
) -> dict[str, str]:
    """Fill in `env` (default `os.environ`) for every blank secret in
    `names`, from `<data>/secrets/<lowercase name>` or freshly generated.

    `data_dir` is the DATA directory (its `secrets/` subdirectory is what is
    actually read/written) -- overrides deriving it from
    `env["DASH_DB_PATH"]`'s parent, for a caller that already knows the real
    one from a live `Settings` object (e.g. `setup_engine`'s `secrets`
    task) rather than from the environment, which may not agree with it (a
    hand-built `Settings(db_path=...)`, as every test in this suite
    constructs, never touches the real environment). Without this, such a
    caller would derive `/data` from a default that has nothing to do with
    where THIS process's data actually lives -- and, worse, write real
    files there since `env` defaults to the real `os.environ` (measured
    2026-08-17: an "E:/data/secrets" this exact mismatch created on a dev
    machine, cleaned up by hand).

    Returns {name: "env" | "file" | "generated"} for the boot log -- never
    the values. Never raises: a `/data` that cannot be created or written
    (e.g. this process does not own it yet) leaves the affected variable
    unset, exactly as it is today when nobody has run the secret-generation
    step -- create_app's existing boot-time refusal (auth.check_boot_secrets)
    is what stops the dashboard from serving on a missing session secret, not
    this function.
    """
    env = os.environ if env is None else env
    secrets_dir = (data_dir / "secrets") if data_dir is not None else _secrets_dir(env)
    provenance: dict[str, str] = {}
    for name in names:
        if env.get(name, "").strip():
            provenance[name] = "env"
            continue
        path = secrets_dir / name.lower()
        existing = _read_secret_file(path)
        if existing:
            env[name] = existing
            provenance[name] = "file"
            continue
        # A sidecar's env_file, if one already carries this secret
        # (dash-admin-2, 2026-08-21 -- see SIDECAR_ENV_FILES). Adopted, never
        # regenerated: the sidecar that wrote it is already running with it.
        sidecar = SIDECAR_ENV_FILES.get(name)
        if sidecar is not None:
            adopted = _read_env_file_value(secrets_dir / sidecar[0], sidecar[1])
            if adopted:
                env[name] = adopted
                provenance[name] = "sidecar-file"
                try:
                    _write_secret_file(path, adopted)
                except OSError as exc:                              # noqa: BLE001
                    log.warning("could not mirror %s from %s to %s (%s)",
                                name, sidecar[0], path, exc)
                continue
        value = secrets.token_urlsafe(32)
        try:
            _write_secret_file(path, value)
        except OSError as exc:  # noqa: BLE001
            log.warning("could not persist a generated secret for %s to %s (%s); "
                        "it will be regenerated on the next boot unless the "
                        "environment sets it", name, path, exc)
        env[name] = value
        provenance[name] = "generated"
    if provenance:
        log.info("secrets bootstrap: %s", ", ".join(
            f"{name}={source}" for name, source in provenance.items()))
    _write_sidecar_env_files(env, secrets_dir)
    return provenance


def _write_sidecar_env_files(env: Mapping[str, str], secrets_dir: Path) -> None:
    """`syncthing.env` (`STGUIAPIKEY=`) and `internal.env`
    (`CCSYNC_INTERNAL_TOKEN=`, `APP_UID=`, `APP_GID=`) -- the `env_file:`
    targets agent A's compose
    (WP A/C) points the `syncthing` and `sftp` sidecar services at, because
    neither of them reads `DASH_*` variables and neither has its own secret
    generator. Rewritten every boot so a secret rotated by setting the env
    var (env always wins, see ensure_secrets) reaches the sidecars too --
    they only ever read these files at their OWN startup, so a rotation
    still needs `docker compose up -d syncthing sftp`, but at least the file
    they would read is never stale.

    Best-effort: a write failure here must never stop the dashboard itself
    from booting (see ensure_secrets' docstring) -- it degrades to "the
    sidecars keep whatever they last had," which is the same failure mode as
    every other file this module cannot write.
    """
    syncthing_key = env.get("SYNCTHING_API_KEY", "")
    internal_token = env.get("CCSYNC_INTERNAL_TOKEN", "")
    # APP_UID/APP_GID: the uid/gid THIS container runs as, so the sftp
    # sidecar (which owns the /tree mount, SPEC.md §3.1) writes files with
    # the same ownership the dashboard and Syncthing already use. Read from
    # the environment (compose sets these for every service from one place)
    # rather than os.getuid() -- a rootless container's os.getuid() is
    # already remapped, and the value that matters here is the one written
    # into the OTHER services' compose entries, not this process's kernel
    # view of itself.
    app_uid = env.get("APP_UID", "")
    app_gid = env.get("APP_GID", "")
    try:
        if syncthing_key:
            _write_secret_file(secrets_dir / "syncthing.env",
                               f"STGUIAPIKEY={syncthing_key}\n")
        if internal_token:
            lines = [f"CCSYNC_INTERNAL_TOKEN={internal_token}\n"]
            if app_uid:
                lines.append(f"APP_UID={app_uid}\n")
            if app_gid:
                lines.append(f"APP_GID={app_gid}\n")
            # `internal.env`, which is the file compose.appliance.yaml's sftp
            # service actually env_files -- NOT `sftp.env`, which this
            # function wrote until 2026-08-21 and which nothing has ever read
            # (dash-admin-2). A stale copy of a live secret with no reader is
            # not worth keeping around, so an old one is removed.
            _write_secret_file(secrets_dir / "internal.env", "".join(lines))
            (secrets_dir / "sftp.env").unlink(missing_ok=True)
    except OSError as exc:  # noqa: BLE001
        log.warning("could not write sidecar env_file targets under %s (%s)",
                    secrets_dir, exc)
