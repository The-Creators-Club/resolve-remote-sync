"""CC Sync fleet dashboard."""

# 0.5.0 (2026-08-17): the commercial-readiness pass -- server-side revocable
# sessions + CSRF + boot-time secret floor + OIDC (CR-8), signed upgrade
# channel + DASH_RELEASE_PUBKEYS (CR-6), per-editor report tokens and scoped
# fleet reads (CR-18), sync_guard alarms + fleet halt (CR-11), [features]
# switches and brand keys on the site manifest (CR-2, CR-16), scoped NAS API
# key (CR-9), schema v14-v16. Deploy notes: KNOWN_BUGS.md CR-8 (everyone is
# signed out once; weak secrets refuse to boot).
VERSION = "0.5.0"
