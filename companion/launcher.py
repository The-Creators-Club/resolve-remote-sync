"""PyInstaller entry point.

The package's __main__.py can't be handed to PyInstaller directly — run as a
top-level script its relative imports have no parent package. This absolute-
import shim is what build.spec targets instead.
"""

from ccsync_companion.app import run

if __name__ == "__main__":
    run()
