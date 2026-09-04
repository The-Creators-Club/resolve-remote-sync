"""CC Sync fleet dashboard."""

# 0.5.0 (2026-08-17): the commercial-readiness pass -- server-side revocable
# sessions + CSRF + boot-time secret floor + OIDC (CR-8), signed upgrade
# channel + DASH_RELEASE_PUBKEYS (CR-6), per-editor report tokens and scoped
# fleet reads (CR-18), sync_guard alarms + fleet halt (CR-11), [features]
# switches and brand keys on the site manifest (CR-2, CR-16), scoped NAS API
# key (CR-9), schema v14-v16. Deploy notes: KNOWN_BUGS.md CR-8 (everyone is
# signed out once; weak secrets refuse to boot).
# 0.6.0 (2026-08-18): ingest and self-update. The fleet grid and the report
# endpoint learned b-roll and music ingest (`ReportIn.broll_ingest` /
# `music_ingest`, the two chips, `commands.*_ingest`, schema v20-v21) and the
# same pass fixed pydantic silently dropping the `proxy_coverage` and
# `youtube_import` sections it had been sent for weeks; the site manifest
# gained `indexer.model_tier`, `release_feed_base` and `brand_logo`; an AI
# Providers settings page backs a five-deep provider chain the ytdl app asks
# per call; and WP K (docs/ZERO_TOUCH_PLAN.md) lets this container update its
# OWN code over the signed feed -- a `dashboard` package record, a bundle
# staged, verified and swapped with a DB backup and a rollback, `runtime_id`
# and the `code` object on /api/v1/health. Deploy notes: KNOWN_BUGS.md WPK-1
# (the image must ship templates/ and static/) and WPK-2 (the first OTA needs
# DASH_RELEASE_FEED_URL set and one manual redeploy).
# 0.7.23 (2026-08-30): force, target and volunteer (§10 of
# docs/TIMELINE-CARDS-INTO-CCSYNC.md). Three levers over a scheduler that
# could only ever say "wait": `force` on a job skips the idle floor, the
# per-machine cooldown and the rank grace everywhere it is offered,
# `target_machine` sends it to one named computer, and `volunteer_until` --
# set by the person AT a machine, from their tray -- opens that machine's
# idle gate while they work. Schema v46, `commands.jobs.forced` on the report
# reply, `ids` on the claim. Pairs with companion 0.9.61.
VERSION = "0.7.36"
