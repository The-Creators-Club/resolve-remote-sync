"""PyInstaller entry point.

The package's __main__.py can't be handed to PyInstaller directly — run as a
top-level script its relative imports have no parent package. This absolute-
import shim is what build.spec targets instead.
"""

import sys

# The relaunch-on-abort supervisor is this same exe re-entered with a flag
# (CR-93, 2026-08-30). Branched BEFORE the app import on purpose: the
# supervisor waits on one process handle for hours and must not carry the
# companion, its config, its logging or tkinter to do it.
if "--supervise" in sys.argv[1:]:
    from ccsync_companion.supervisor import main as _supervise

    sys.exit(_supervise(sys.argv[1:]))

# GL-22 (CR-370, 2026-10-07). `--self-test` imports the whole package and
# exits: a release step LAUNCHES the frozen exe with it (no pipeline ever
# did). Branched before the app import for the same reason as the supervisor:
# an import error in the app must surface as the self-test's FAILURE.
if "--self-test" in sys.argv[1:]:
    from ccsync_companion.startguard import self_test as _self_test

    sys.exit(_self_test(sys.argv[1:]))

# Also before the app import: record this start attempt, so a build that dies
# at import (never reaching CompanionApp.run) is still counted and two such
# deaths restore the predecessor. Light on imports and never raises.
from ccsync_companion import startguard as _startguard  # noqa: E402

if _startguard.begin(sys.argv[1:]) == "reverted":
    sys.exit(0)

from ccsync_companion.app import run  # noqa: E402 - see above

if __name__ == "__main__":
    run()
