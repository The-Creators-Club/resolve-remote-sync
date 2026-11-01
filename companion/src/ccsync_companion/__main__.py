"""Allows `python -m ccsync_companion` to start the app."""

import sys

# Same branch as launcher.py: the supervisor re-entry must not import the app.
if "--supervise" in sys.argv[1:]:
    from .supervisor import main as _supervise

    sys.exit(_supervise(sys.argv[1:]))

if "--self-test" in sys.argv[1:]:
    from .startguard import self_test as _self_test

    sys.exit(_self_test(sys.argv[1:]))

from . import startguard as _startguard  # noqa: E402

# GL-22 (CR-370): see launcher.py.
if _startguard.begin(sys.argv[1:]) == "reverted":
    sys.exit(0)

from .app import run  # noqa: E402

if __name__ == "__main__":
    run()
