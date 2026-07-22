"""ccbench: sync-transport benchmark harness for Creators Club remote-editor sync.

Picks the fastest transfer engine per sync lane (video-up, proxy-down,
everything-else-bidirectional) for editors syncing with a TrueNAS box over
Tailscale, and verifies whether the Tailscale path is direct or DERP-relayed.
"""

__version__ = "0.1.0"
