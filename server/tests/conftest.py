"""Point every test at the fixture site manifest, before anything imports it.

server/common.py reads site.toml AT IMPORT TIME -- it has to, because the
values are argparse defaults and a parser bakes its defaults in when it is
built. So the choice of site has to be made before the first `import common`,
which for pytest means here: conftest.py is imported before any test module.

Without this the suite would run against a blank site (every identity value
""), which is the un-configured state the scripts refuse in -- correct
behaviour, useless for testing a deploy. The fixture carries this fleet's real
values because a deploy test needs a host, a pool and a tree that look like
one; the refuse-when-unset contract has its own test, which reloads common
with the environment cleared (test_site_manifest.py). Added 2026-08-17 with
WP0 of docs/SYNOLOGY_PORT_PLAN.md.
"""
import os
from pathlib import Path

FIXTURE_SITE = Path(__file__).resolve().parent / "fixtures" / "site.toml"

# setdefault, not a bare assignment: running the suite against another site's
# manifest (CCSYNC_SITE=... pytest) is a legitimate thing to want.
os.environ.setdefault("CCSYNC_SITE", str(FIXTURE_SITE))
