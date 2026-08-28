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
                   "DASH_TRUSTED_PROXIES"):
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
