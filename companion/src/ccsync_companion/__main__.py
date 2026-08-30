"""Allows `python -m ccsync_companion` to start the app."""

import sys

# Same branch as launcher.py: the supervisor re-entry must not import the app.
if "--supervise" in sys.argv[1:]:
    from .supervisor import main as _supervise

    sys.exit(_supervise(sys.argv[1:]))

from .app import run  # noqa: E402

if __name__ == "__main__":
    run()
