# The studio flavour: how the studio keeps Claude Code and Codex

GL-31 / CR-374, 2026-10-07 (owner decision "GL-45 AI billing", docs/PRELAUNCH_REVIEW_2026-10-06.md).

One codebase, one image. The Claude Code and Codex CLI providers, the SET UP
wizard and its subscription sign-in relay, the CLI auto-update and the
CLI-only server triage agent all run on a PERSONAL subscription. A customer's
service may not do that (COM-H1), so the **vendor build hard-disables all of
it**; the studio's own dashboard keeps it.

## What "hard" means

`ccsync_dashboard/build_flavor.py` is asked by `site_store.feature_enabled`
BEFORE any database row or `DASH_SITE_*` value. On a locked build:

- `[features] ai_cli_providers` and `ai_cli_auto_update` read OFF, whatever a
  Settings checkbox, a stored `features.ai_cli_providers = 1` row, an
  imported site.toml or an accepted notice says. `GET /api/v1/site` publishes
  them as false.
- the provider list has no CLI rows, no CLI switch and no subscription notice
  (the page hides them; `GET /api/v1/admin/ai-providers` answers
  `cli_build_locked: true`);
- the wizard's install and sign-in routes answer 409 "not available in this
  build";
- the Settings Features panel does not render the two CLI checkboxes at all
  (server-side), so a Save can never post `features.ai_cli_auto_update` and
  overwrite a stored studio value;
- the server triage agent SHIPS (owner table GL-48) through ONE compliant
  door: an unmodified Claude Code the admin installed on the host (typed path
  under AI providers, or on PATH; the wizard that would fetch it is locked),
  run ONLY on the site's Anthropic API key (Console billing). The run's
  environment drops the wizard HOME and any stored setup-token. With no API
  key or no binary the gate says exactly which is missing and the run mails
  the fallback. Whether this counts as a "CLI provider" is an OWNER QUESTION
  (CR-374 ledger, deferred); the code half is done and one line
  (`triage.cli_gate`) closes it if the answer is no;
- the AI provider chain only ever selects an API provider (Claude API, OpenAI,
  DeepSeek), so Timeline Cards and the YouTube downloader bill an API key.

## How the studio keeps them

The switch is NOT a site setting. It is one process environment variable,
`DASH_STUDIO_CLI_PROVIDERS=1`, that exists only in the deploy. The deploy
script writes it from the studio's OWN `site.toml`:

```toml
[studio]
allow_cli_providers = true
```

`server/install_dashboard_app.py` projects that into the container
environment. Absent (the vendor default, and what every customer's site.toml
and the appliance compose file carry) the build is locked. Nothing in the
database, the manifest, the Settings page or any API can set it.

## Deploy order for the studio (do this BEFORE the first deploy of CR-374)

**The first CR-374 delivery to the studio MUST be a full
`server/install_dashboard_app.py` redeploy (`tools\ship.cmd`), never an
over-the-air code bundle and never an app-manager image swap.** Both keep the
container's OLD environment, so the new code boots without the variable and
the studio comes up LOCKED. (The OTA preflight that would catch this is the
RUNNING, older code's, which cannot know.) If it happens anyway: nothing
stored is rewritten (the Settings page no longer posts the CLI rows while
locked, and the boot log says "LOCKED vendor build but ... stored"); add the
`[studio]` block, redeploy with the install script, and everything returns.

1. Add the `[studio]` block above to the studio's site.toml.
2. Deploy the dashboard as usual (`tools\ship.cmd`). The container now carries
   `DASH_STUDIO_CLI_PROVIDERS=1`, and the studio's existing
   `features.ai_cli_providers` and `ai_cli_auto_update` rows keep working,
   with the studio's existing CLI install and sign-in untouched.
3. If step 1 is skipped, the studio's CLI providers and triage go dark on that
   deploy (they fall back to an API key, and triage mails a "needs Claude
   Code" fallback). Nothing is deleted; adding the block and redeploying
   brings them back.

A customer who edits their own container environment can defeat the lock. That
is accepted: the lock decides what we ship and default, and the beta terms say
the same thing. It is not a licence check.

## Round 2 additions (2026-10-07)

- A stored CLI pin (`ai_provider_preference` = claude_code or codex) is read
  as auto on a locked build, and a CLI pin is refused (422) there, so a
  stranded studio's Cards and YouTube AI still use an API key.
- A stranded studio is announced as the notice `cli_lock_stranded` (home
  page, PROBLEMS THE SERVER FOUND), not only a boot log line.
- Settings > AI providers shows, on a locked build, one path box for the
  server check's own Claude Code. No wizard, no sign-in. The server check's
  run uses its own writable HOME (`<data>/tools/claude-code/api-home`) and
  only `ANTHROPIC_API_KEY`.
- Export site.toml writes the raw stored `ai_cli_*` flags, so an export from
  a stranded studio imports intact into the corrected deploy.
