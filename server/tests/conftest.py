"""Point every test at the fixture site manifest, before anything imports it.

server/common.py reads site.toml AT IMPORT TIME -- it has to, because the
values are argparse defaults and a parser bakes its defaults in when it is
built. So the choice of site has to be made before the first `import common`,
which for pytest means here: conftest.py is imported before any test module.

Without this the suite would run against a blank site (every identity value
""), which is the un-configured state the scripts refuse in -- correct
behaviour, useless for testing a deploy. The fixture carries placeholder
values because a deploy test needs a host, a pool and a tree that look like
one; the refuse-when-unset contract has its own test, which reloads common
with the environment cleared (test_site_manifest.py). Added 2026-08-17 with
WP0 of docs/SYNOLOGY_PORT_PLAN.md.
"""
import os
from pathlib import Path

FIXTURE_SITE = Path(__file__).resolve().parent / "fixtures" / "site.toml"

# The search order is flag, then ENV VAR, then the manifest -- so a shell that
# exports the operator's own NAS (the base rig's does: TRUENAS_HOST, and
# tools/load_secrets.ps1 exports more) SHADOWS the fixture, and the byte-for-
# byte compose goldens then render that shell's host instead of the fixture's.
# That went unnoticed for as long as the fixture carried this fleet's real
# address and the two happened to agree; the 2026-08-17 identity sweep
# (COMMERCIAL_READINESS.md item 10) made them differ, and the goldens then
# failed on the base rig only. Clear the identity overrides here, before
# common is imported. A test that WANTS one sets it with monkeypatch.setenv,
# which is unaffected.
#
# DASH_TRUSTED_PROXIES joined the list 2026-08-21 (CR-67 seam 5): it reaches
# the compose TEMPLATE now, and trusted_proxies_for reads the deploying
# shell's value first by design -- so an operator who exported one would
# render it into the byte-for-byte goldens.
for _shadowing in ("TRUENAS_HOST", "SYNO_HOST", "TRUENAS_USER", "SYNO_USER",
                   "DASH_TRUSTED_PROXIES",
                   # CR-362 / GL-02 (2026-10-07): the Synology/image compose
                   # files now render the deploying shell's release key and
                   # vendor switch. load_secrets.ps1 exports the key on the
                   # base rig and INSTALL.md Step 6 exports the switch, so
                   # either would leak into the byte-for-byte goldens.
                   "DASH_RELEASE_PUBKEYS", "DASH_VENDOR_DEFAULTS"):
    os.environ.pop(_shadowing, None)

# GL-18/GL-19 (CR-368, 2026-10-07): the operator toolchain now records NAS host
# keys, NAS certificate pins and a generated Postgres password under ~/.ccsync.
# A suite must neither read the base rig's real ones (a recorded key would
# flow into the byte-for-byte goldens) nor write into them.
import tempfile as _tempfile  # noqa: E402

_STATE = Path(_tempfile.mkdtemp(prefix="ccsync-tests-state-"))
os.environ["CCSYNC_KNOWN_HOSTS"] = str(_STATE / "known_hosts")
os.environ["CCSYNC_KNOWN_CERTS"] = str(_STATE / "known_certs.json")
os.environ["CCSYNC_PG_PASSWORD_FILE"] = str(_STATE / "pg_password")
for _shadowing in ("CCSYNC_SSH_HOSTKEY", "PG_PASSWORD", "TRUENAS_VERIFY_SSL",
                   "SYNO_VERIFY_SSL", "TRUENAS_API_KEY"):
    os.environ.pop(_shadowing, None)

# setdefault, not a bare assignment: running the suite against another site's
# manifest (CCSYNC_SITE=... pytest) is a legitimate thing to want.
os.environ.setdefault("CCSYNC_SITE", str(FIXTURE_SITE))

# OPS-9 (resilience sweep 2026-08-28): snapshot_before now APPENDS a durable
# record, and its default path is the operator's own
# ~/.ccsync/snapshot_log.jsonl. A suite that runs several dozen snapshot calls
# must not write rows into the live ledger of the machine it is running on, so
# every test gets a throwaway path unless it sets its own.
import tempfile  # noqa: E402

os.environ.setdefault(
    "CCSYNC_SNAPSHOT_LOG",
    str(Path(tempfile.gettempdir()) / "ccsync-tests-snapshot_log.jsonl"))


# OPS-1 (resilience sweep 2026-08-28): every restart now probes
# /api/v1/health from inside the container and the deploy FAILS when it does
# not answer as this checkout's VERSION. That probe retries for
# HEALTH_PROBE_SECONDS, and the suite's fake `run_ssh` answers every command
# with an empty string -- which is exactly the wedged-container shape, so an
# unstubbed probe would make every whole-deploy test sit out the full budget
# and then fail. The probe is therefore HEALTHY BY DEFAULT here, and the
# tests that are about it (test_deploy_resilience.py) replace this stub with
# their own.
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _health_probe_answers_healthy(monkeypatch):
    import sys  # noqa: PLC0415

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        import install_dashboard_app as ida  # noqa: PLC0415 - after CCSYNC_SITE is set
    except Exception:
        # A test module that never touches the deploy script (the compose
        # goldens, the site-manifest reloads) has nothing to stub.
        return

    monkeypatch.setattr(
        ida, "probe_dashboard_health",
        lambda port, expected, dry_run, budget=0: (
            True, {"ok": True, "version": expected or ida.repo_dashboard_version()},
            "stubbed by conftest"),
        raising=False)


# NO TEST HERE LEAVES THIS MACHINE (audit tests-ci-2, 2026-11-11). The deploy
# script's real-run tests stub run_ssh, the tree installs and the provisioning
# steps, and their helper's docstring says "nothing here opens a socket". It
# did: the TrueNAS version note calls the real API client against the
# manifest's `[nas] host` with TRUENAS_PW="pw", so the first real-run test of
# each process tried a TLS connection to a private address on whatever network
# the suite was run from (a login attempt with a junk password on a studio
# LAN; a 30 s timeout on CI). One unstubbed call is easy to add again, so the
# guard is here rather than in that one helper: a connect to anything but this
# machine fails at once, with a message that names the fix. A test that
# stands up its own server on 127.0.0.1 is unaffected.
import socket as _socket  # noqa: E402

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}


def _is_local(address) -> bool:
    if not isinstance(address, tuple) or not address:
        return True                       # AF_UNIX and friends: a path, not a network
    host = str(address[0] or "").strip().lower()
    return host in _LOCAL_HOSTS or host.startswith("127.")


class _NoNetwork(OSError):
    pass


def _refuse(address):
    raise _NoNetwork(
        f"a server test tried to open a connection to {address!r}. No test may leave this "
        "machine: stub the call that reaches the NAS (see server/tests/conftest.py).")


@pytest.fixture(autouse=True)
def _no_connections_off_this_machine(monkeypatch):
    real_create, real_connect, real_connect_ex = (
        _socket.create_connection, _socket.socket.connect, _socket.socket.connect_ex)

    def create_connection(address, *args, **kwargs):
        if not _is_local(address):
            _refuse(address)
        return real_create(address, *args, **kwargs)

    def connect(self, address):
        if not _is_local(address):
            _refuse(address)
        return real_connect(self, address)

    def connect_ex(self, address):
        if not _is_local(address):
            _refuse(address)
        return real_connect_ex(self, address)

    monkeypatch.setattr(_socket, "create_connection", create_connection)
    monkeypatch.setattr(_socket.socket, "connect", connect)
    monkeypatch.setattr(_socket.socket, "connect_ex", connect_ex)
    yield
