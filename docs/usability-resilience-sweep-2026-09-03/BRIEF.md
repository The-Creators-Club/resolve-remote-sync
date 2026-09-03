# Usability + resilience sweep brief, 2026-09-03 (shared by every agent)

Repo: E:\Projects\resolve-remote-sync at `097f5a3` (main). Read `CLAUDE.md` first
(it is long and it is the map). `SPEC.md` is the architecture; `KNOWN_BUGS.md` is
the 10,000-line defect ledger (entries CR-1..CR-101 are the recent ones);
`docs/` has the operational docs, esp. `GOTCHAS.md`, `SYNC_SAFETY.md`,
`RESOLVE_EDIT_SAFETY.md`, `HOW_IT_WORKS.md`, `SELF_DIAGNOSIS.md`.

**A sweep like this already ran on 2026-08-28**: `docs/RESILIENCE_SWEEP_2026-08-28.md`
is its synthesis and `docs/resilience-sweep-2026-08-28/<AREA>.md` are its raw
reports (201 findings). Waves 1-4 of that sweep were BUILT (notices, alerts,
invariants, protection, recovery, self-diagnosis). READ THE REPORT FOR YOUR
AREA BEFORE YOU START and do not re-report its findings: either the finding is
built (say nothing), or it is still open (mention it in one line under
"Still open from 08-28", no re-analysis), or you have a genuinely new angle.
Your value is what that sweep did NOT find, and the whole usability lens, which
it did not have.

What this system is: a DaVinci Resolve editing fleet. A TrueNAS (or Synology)
server holds the canonical project tree; each editor's Windows/Mac machine runs
a tray "companion" that syncs slices of it (lane A rclone up, lane B rclone
down, lane C Syncthing), watches/fixes Resolve projects, generates proxies, runs
fleet jobs, and takes OTA upgrades from a FastAPI "dashboard" in a container on
the NAS. The dashboard also mounts the b-roll search, music search, YouTube
download and Timeline Cards apps. The owner is NON-TECHNICAL. Editors are video
editors, not IT people. Admins are the owner. The product is being readied for a
second customer (see `docs/COMMERCIAL_READINESS.md`, `docs/ZERO_TOUCH_PLAN.md`).

YOUR JOB: sweep your assigned area with TWO lenses, both required:

1. USABILITY. Put yourself in the seat of the person who touches this surface
   (editor at the tray / popup / settings window / browser; admin on the
   dashboard; owner installing a customer; a developer shipping). For every
   touchpoint ask: Is it discoverable? Does the copy say what happened AND what
   to do next? Is there feedback while something long runs? Are there too many
   steps, or a step that could be automatic? Can it be undone? Is the same
   thing named the same way everywhere (tray vs dashboard vs docs)? Does an
   error name the cause or just the symptom? Are defaults right? What does a
   first-time user get wrong? What does the expert user do fifty times a day
   that could be one click? Is anything only reachable by editing a file or
   running a script that an editor/admin plausibly needs? Are dangerous
   actions and harmless ones visually distinct? What state is invisible that
   the person needs to see? Read the actual template / tray / popup / CLI
   strings; quote the copy you would change and write the copy you would ship.
   Follow the repo's own copy rules: NO EM DASHES in user-visible text, the
   `[ BUTTON ]` bracket style, brand strings from the site manifest, never a
   customer's name in code.

2. RESILIENCE (new angles only, see above). Plausible real-world conditions
   (disk full, sleep/wake, VPN drop, clock skew, NAS reboot, half-written file,
   odd characters in a path, two instances, a stale build in the field, a schema
   older than the code, a partial deploy, an exception in a thread, a timeout
   that never fires, a slow machine, a huge project, a laptop on hotel wifi...)
   that lead to silent failure, wrong state, data loss, or a stuck state only a
   human can clear. User mistakes the system does not cope with. Safeguards
   tied to a concrete mechanism in this codebase (invariants, dry-run, undo,
   quarantine, canaries, heartbeats with expiry, watchdogs, idempotency,
   staged rollout, drift detectors, "explain why" diagnostics, rate limits).
   Include things that are technically guarded but where the guard's OUTPUT is
   unusable (a log line nobody reads, a notice with no next action, a state
   file with no UI).

RULES:
- Read the actual code. Cite `file:line` for every finding. Do not guess at
  behaviour you did not verify in the source. Quote real strings.
- Before proposing anything, CHECK whether it already exists (grep the code,
  `KNOWN_BUGS.md`, `docs/`, the 08-28 report for your area). If a guard or a UI
  exists but has a hole, say precisely what the hole is.
- DO NOT modify any file in the repo. Read-only. You write ONE output file: the
  path given in your task. Nothing else. Do not run the test suites.
- Keep the output file to at most ~350 lines. Quality over quantity: 15-30
  strong findings beats 60 weak ones. Rank them.
- A usability finding must be as concrete as a bug: who, where (the exact
  screen/menu/route), what they see today (quoted), what they should see.

OUTPUT FORMAT (markdown, exactly this shape so it can be merged):

# <Area name>

## Summary
3-6 sentences: the area's usability posture, its resilience posture, the
biggest risk, the best cheap win.

## Findings
For each, ranked most valuable first:

### <AREA-CODE>-<n>: <one-line title>
- **Lens:** usability | resilience | both
- **Who:** editor | admin | owner | developer
- **Where:** `path:line` (one or more), plus the screen/menu/route if a UI
- **Today:** what the person sees / what the code does (verified, quoted)
- **Proposed:** the change, concretely: the copy, the control, the check, the
  state file, what refuses/warns/records/retries, what the user sees
- **Effort:** S / M / L   **Value:** low / med / high / critical   **Confidence:** low / med / high
- **Related:** existing guards, docs, KNOWN_BUGS ids, 08-28 finding ids if any

## Still open from 08-28
One line each: id, title, "not built" or "partly built (what is missing)".
Skip this section if nothing applies.

## Cross-cutting notes
Anything you noticed outside your area worth handing to another agent, briefly.

Finish your reply to the orchestrator with ONLY: the output path, the count of
findings (usability / resilience), and your top 3 in one line each.
