#!/usr/bin/env python3
r"""Fail when the customer channel trails main.

    python tools/check_feed_freshness.py [--max-behind 3] [--max-age-days 45]

GL-24 / COM-H8 (CR-371, 2026-10-07). The customer channel sat a month behind
the studio (feed dashboard 0.7.44 while main was 0.7.73) and nothing said so:
shipping to the studio never moves it, and no check compared the two. This
reads the PUBLISHED channel (the one customers read, signature verified with
the keys baked into this tree) and exits non-zero when:

  * the channel's current dashboard trails the dashboard VERSION in this tree
    by more than --max-behind releases (same major.minor: the patch distance;
    a different major.minor always counts as far behind);
  * a current companion/onboard record names a requires_dashboard newer than
    the channel's current dashboard (customers would stage it and never offer
    it, SYS-2);
  * there is a current dashboard but no `dashboard_image` digest in the signed
    channel (customers are pinned BY DIGEST, GL-50: no digest, nothing to pin);
  * the channel was last generated more than --max-age-days ago while main has
    moved on (a stale feed behind a quiet repo is not an alarm).

Exit codes: 0 fresh, 1 stale, 3 NOT CHECKED (the feed could not be read or
verified): an unverified check is never OK. Stdlib only; reuses publish_feed's
fetch and signature check so there is one reader of the feed.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO_ROOT / "companion" / "src"))

FEED_REPO = "The-Creators-Club/ccsync-releases"
EXIT_OK, EXIT_STALE, EXIT_UNCHECKED = 0, 1, 3


def version_tuple(text: str) -> tuple:
    parts = []
    for chunk in str(text or "").replace("+", ".").split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def tree_dashboard_version(root: Path = REPO_ROOT) -> str:
    text = (root / "dashboard" / "src" / "ccsync_dashboard" / "__init__.py").read_text(
        encoding="utf-8")
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else ""


def versions_behind(published: str, main: str) -> int:
    """How many releases `published` trails `main`: the patch distance within
    one major.minor, 10_000 across one (a minor bump is always 'far')."""
    a, b = version_tuple(published), version_tuple(main)
    if not a:
        return 10_000
    if a[:2] != b[:2]:
        return 10_000 if a < b else 0
    return max(0, (b[2] if len(b) > 2 else 0) - (a[2] if len(a) > 2 else 0))


def judge(channel: dict, main_version: str, *, max_behind: int, max_age_days: int,
          now: datetime | None = None) -> list[str]:
    """The list of failures (empty = fresh). Pure, so the tests drive it."""
    problems: list[str] = []
    current = channel.get("current") or {}
    dash = str(current.get("dashboard/linux") or "")
    if not dash:
        problems.append("the channel has no current dashboard/linux at all: customers get no "
                        "dashboard from it")
    else:
        behind = versions_behind(dash, main_version)
        if behind > max_behind:
            shown = "a different minor release" if behind >= 10_000 else f"{behind} releases"
            problems.append(f"the channel's dashboard is {dash} but main is {main_version} "
                            f"({shown} behind, limit {max_behind}): run tools/release_customers.py")
        image = channel.get("dashboard_image") or {}
        if not str(image.get("digest") or "").startswith("sha256:"):
            problems.append("the channel names no dashboard_image digest, so a customer has "
                            "nothing to pin (GL-50): release_customers.py sets it with the bundle")
    for key, version in sorted(current.items()):
        kind = key.split("/", 1)[0]
        if kind not in ("companion", "onboard") or not dash:
            continue
        for rec in channel.get("packages", []):
            if (f"{rec.get('kind')}/{rec.get('platform')}", rec.get("version")) == (key, version):
                need = str(rec.get("requires_dashboard") or "")
                if need and version_tuple(need) > version_tuple(dash):
                    problems.append(f"{key} {version} needs dashboard {need}, newer than the "
                                    f"channel's {dash}: customers would never be offered it")
    stamp = str(channel.get("generated_at") or "")
    try:
        generated = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
    except ValueError:
        generated = None
    if generated is not None and dash and versions_behind(dash, main_version) > 0:
        age = ((now or datetime.now(timezone.utc)) - generated).days
        if age > max_age_days:
            problems.append(f"the channel was last generated {age} days ago ({stamp}) and main "
                            f"has moved on ({dash} -> {main_version})")
    return problems


def _run(argv):
    p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.returncode, p.stdout, p.stderr


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=FEED_REPO)
    ap.add_argument("--max-behind", type=int, default=3)
    ap.add_argument("--max-age-days", type=int, default=45)
    args = ap.parse_args(argv)

    import publish_feed  # noqa: E402 - needs the sys.path above
    with tempfile.TemporaryDirectory(prefix="ccsync-freshness-") as tmp:
        channel, signature, status = publish_feed.fetch_published_channel(
            args.repo, publish_feed.DEFAULT_GITHUB_TAG, runner=_run, dest=Path(tmp),
            out=sys.stdout)
        if status != "ok" or channel is None:
            print(f"[feed-freshness] NOT CHECKED: could not read the published channel "
                  f"({status})", file=sys.stderr)
            return EXIT_UNCHECKED
        ok, detail = publish_feed.verify_channel_signature(
            channel, signature, publish_feed.release_pubkey.RELEASE_PUBKEYS)
        if not ok:
            print(f"[feed-freshness] NOT CHECKED: the channel does not verify ({detail})",
                  file=sys.stderr)
            return EXIT_UNCHECKED
    main_version = tree_dashboard_version()
    problems = judge(channel, main_version, max_behind=args.max_behind,
                     max_age_days=args.max_age_days)
    if problems:
        print(f"[feed-freshness] STALE (main dashboard {main_version}):", file=sys.stderr)
        for line in problems:
            print("  - " + line, file=sys.stderr)
        return EXIT_STALE
    print(f"[feed-freshness] fresh: channel dashboard "
          f"{(channel.get('current') or {}).get('dashboard/linux')} vs main {main_version}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
