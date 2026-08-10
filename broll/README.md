# broll-platform

> Folded into resolve-remote-sync as `broll/` on 2026-08-10. It was the
> standalone `E:\Projects\broll-platform` repo until then, and its pre-fold git
> history stays there. The fleet dashboard mounts `broll/web` in-process at
> `/broll` — see `dashboard/src/ccsync_dashboard/broll.py`.

Searchable b-roll library for Cablewrap Creative. Visual indexing via Claude Code,
web search UI with per-segment hits and in/out selection, one-click insert into
DaVinci Resolve Studio on each editor's machine over Tailscale.

See `SPEC.md` for architecture and contracts, `schema.sql` for the database.

Components: `indexer/` (Windows PC worker) · `web/` (search app, Docker on TrueNAS
when live). The third one, `companion/` (the editor-side agent "Send to Resolve"
talks to), was absorbed into the CC Sync companion on 2026-08-10 and deleted:
its server now lives at `companion/src/ccsync_companion/broll_server.py` in this
repo, inside the tray app editors already run. Nobody installs a second one, and
an old standalone BRoll Companion left running holds port 8899 against the new
one — quit it.

Cross-platform path consistency in shared Resolve projects: Windows editors all map the
share to the same drive letter; Mac editors rely on Resolve Path Mapping (Project Media
Locations) with Mapped Mount as fallback. Shared projects live on a Resolve Project
Server (Postgres, Docker on the NAS — `deploy/`).
