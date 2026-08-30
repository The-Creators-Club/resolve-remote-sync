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

from ccsync_companion.app import run  # noqa: E402 - see above

if __name__ == "__main__":
    run()
