# Resilience sweep brief (shared by every agent)

Repo: E:\Projects\resolve-remote-sync (read CLAUDE.md first; SPEC.md is the architecture; KNOWN_BUGS.md is the 4800-line defect ledger; docs/ has the operational docs, esp. GOTCHAS.md, SYNC_SAFETY.md, RESOLVE_EDIT_SAFETY.md, HOW_IT_WORKS.md).

What this system is: a DaVinci Resolve editing fleet. A TrueNAS server holds the canonical project tree; each editor's Windows/Mac machine runs a tray "companion" that syncs slices of it (lane A rclone up, lane B rclone down, lane C Syncthing), watches/fixes Resolve projects, and takes OTA upgrades from a FastAPI "dashboard" running in a container on the NAS. The owner is NON-TECHNICAL. Editors are video editors, not IT people. Admins are the owner. Anything that loses footage, silently stops syncing, or requires a "restart everything in order" dance is the worst class of failure. "The dashboard is what tells everyone whether their footage is syncing" outranks every feature.

YOUR JOB: sweep your assigned area and propose ways to make it MORE RESILIENT. Three lenses, all three required:
  1. PITFALLS in the code as written: places where a plausible real-world condition (disk full, sleep/wake, VPN drop, clock skew, NAS reboot, half-written file, a path with odd characters, two instances running, a stale build in the field, a schema older than the code, a partial deploy, an exception in a thread, a timeout that never fires...) leads to silent failure, wrong state, data loss, or a stuck state only a human can clear.
  2. USER ERROR the system does not cope with: what can an editor/admin/owner plausibly do wrong at each touchpoint (tray, popups, settings window, dashboard pages, installer, wizard, NAS shell, drive letters, renaming/moving/deleting things by hand in Explorer/Finder, ticking the wrong thing, running two of something, ignoring a dialog, unplugging, killing the process, editing a config file by hand, pasting a wrong URL/token, typos...) and what happens today vs. what SHOULD happen (refuse, warn, auto-correct, undo, quarantine, degrade gracefully).
  3. CREATIVE SAFEGUARDS that make the whole thing operate better: invariants that could be self-checked continuously, dry-run/preview modes, "are you sure" with consequences spelled out, undo journals, quarantine-instead-of-delete, canaries, self-tests at boot, heartbeats with expiry, watchdogs, idempotency keys, staged rollouts, automatic rollback, drift detectors, "explain why I'm not syncing" diagnostics, redundancy for single points of failure, rate limits, budgets, health scores, and anything else you can think of. Be creative but concrete: each idea must be tied to a real mechanism in THIS codebase.

RULES:
- Read the actual code. Cite file:line for every finding. Do not guess at behaviour you did not verify in the source.
- Before proposing a safeguard, CHECK whether it already exists (grep the code, KNOWN_BUGS.md and docs/). Many guards already exist here (lane B breaker, sync halt, undo journal, root_guard, shutdown_guard, script_server, loopback_guard, EULA gate, signed upgrade channel, ZFS snapshot-before-privileged...). If a guard exists but has a hole, say precisely what the hole is. Re-proposing an existing guard wholesale is a wasted finding.
- KNOWN_BUGS.md lists many items as FIXED/OPEN; do not re-report an OPEN item unless you add a genuinely new angle (say which CR/ID it relates to).
- DO NOT modify any file in the repo. Read-only. You write ONE output file: the path given in your task.
- Keep the output file to at most ~300 lines. Quality over quantity: 12-25 strong findings beats 60 weak ones. Rank them.

OUTPUT FORMAT (markdown, exactly this shape so it can be merged):

# <Area name>

## Summary
3-6 sentences: the area's overall resilience posture, the biggest risk you found, the best cheap win.

## Findings
For each, ranked most valuable first:

### <AREA-CODE>-<n>: <one-line title>
- **Lens:** pitfall | user-error | safeguard
- **Where:** `path:line` (one or more)
- **Scenario:** a concrete, plausible sequence of events (who does what, what the machine/network is doing)
- **Today:** what the code actually does then (verified), and the consequence
- **Proposed:** the safeguard/behaviour change, concretely (what refuses/warns/records/retries; what the user sees; where state lives so it survives a restart)
- **Effort:** S / M / L   **Severity:** low / med / high / critical   **Confidence:** low / med / high
- **Related:** existing guards, docs, KNOWN_BUGS ids if any

## Cross-cutting notes
Anything you noticed outside your area worth handing to another agent, briefly.

Finish your reply to the orchestrator with ONLY: the output path, the count of findings, and your top 3 in one line each.
