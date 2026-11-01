"""What a VENDOR-BUILD dashboard (the appliance) trusts and pulls from by default.

CR-362 / GL-02, 2026-10-07. The appliance compose used to say its release key
was "generated on first boot" and carried no feed address, so a customer's
dashboard held no public key and no feed: it could never install an editor,
receive an update or a recall. These two values are the answer, baked into the
IMAGE so an image update can rotate them, and overridable from the environment.

THEY APPLY ONLY WHEN `DASH_VENDOR_DEFAULTS=1` (set by compose.appliance.yaml)
AND THE VARIABLE IS ABSENT. Two reasons, both load-bearing:

  * The studio's own site renders `DASH_RELEASE_FEED_URL` / `DASH_RELEASE_PUBKEYS`
    into its compose from site.toml, always present and possibly empty. Empty
    there is a decision ("this server has no feed"), and a default that
    replaced an empty value would change a live fleet through an upgrade.
  * Every test that builds `Settings.from_env({})` must stay free of a feed
    poller and its network calls.

STDLIB ONLY and no imports from this package: `deploy/select_code_root.py`
loads it at container boot, before the app is importable as a whole.

GL-47 (second operator): the feed address is ONE value, `VENDOR_FEED_URL`
below. The owner has not chosen the vendor-owned redirectable domain yet, so
the placeholder points at today's feed (the GitHub Releases asset the studio
publishes with tools/publish_latest.py). When the domain exists, change this
one constant and every appliance follows on its next image update. An operator
who needs another feed sets `DASH_RELEASE_FEED_URL` (and `DASH_RELEASE_PUBKEYS`).

THE PRIVATE HALF IS NOT HERE AND NEVER ON A CUSTOMER'S MACHINE. This is the
public half of the key tools/release_key.py minted; it must equal the key baked
into the companion (`release_pubkey.RELEASE_PUBKEYS`), a pin test holds the two
together. A rotation lists both for the overlap release (docs/RELEASE.md).
"""
from __future__ import annotations

# PLACEHOLDER for the vendor-owned, redirectable address (GL-47). Today it is
# the studio's GitHub Releases feed; see the module docstring.
VENDOR_FEED_URL = (
    "https://github.com/The-Creators-Club/ccsync-releases/releases/download/"
    "ccsync-releases-v1/channel.json"
)

# Base64 raw Ed25519 public keys of the vendor release key. Same value as
# companion/src/ccsync_companion/release_pubkey.py RELEASE_PUBKEYS.
VENDOR_RELEASE_PUBKEYS: tuple[str, ...] = (
    "GKNmk8MktRkGkrBv+ziF7O6ZNKCnjXfC9/TwDiYwKDY=",
)

ENV_SWITCH = "DASH_VENDOR_DEFAULTS"


def enabled(env) -> bool:
    """"1" and nothing else: a typo must leave the defaults OFF, because OFF
    is the shape every existing deployment already has."""
    return str(env.get(ENV_SWITCH, "")).strip() == "1"


def feed_url(env) -> str:
    """The configured feed URL: the variable when PRESENT (even empty), else
    the vendor feed when the switch is on, else ""."""
    if "DASH_RELEASE_FEED_URL" in env:
        return str(env.get("DASH_RELEASE_FEED_URL", "")).strip()
    return VENDOR_FEED_URL if enabled(env) else ""


def pubkeys_raw(env) -> str:
    """The raw DASH_RELEASE_PUBKEYS text with the same present-wins rule."""
    if "DASH_RELEASE_PUBKEYS" in env:
        return str(env.get("DASH_RELEASE_PUBKEYS", ""))
    return " ".join(VENDOR_RELEASE_PUBKEYS) if enabled(env) else ""


def holds_only_vendor_keys(keys) -> bool:
    """True when `keys` is non-empty and every one is the vendor's. That is
    the appliance's normal state, and it means the PRIVATE half is held by the
    vendor, not by this site (so there is nothing here to back up)."""
    keys = tuple(k for k in keys if k)
    return bool(keys) and all(k in VENDOR_RELEASE_PUBKEYS for k in keys)
