# Verifier med-08 (2026-09-25)

Judged against HEAD (`git show HEAD:<path>`). Findings: bug-ops-2, bug-ops-3,
bug-wire-1, bug-wire-2, bug-wire-3, logic-onboarding-2, logic-onboarding-3,
logic-onboarding-4.

## bug-ops-2 - DOWNGRADE (low)

The mechanism holds. In `tools/ship.ps1` at HEAD, `-Resume` sets
`$script:ResumeFrom` (:411), and then the "already published" probes for the
companion (:423-440) and the installer (:456-470) run unconditionally
(only `-DashboardOnly` skips them) and `exit 1` with "bump VERSION". After
journal step `publish` (the exit-3 soak refusal, :915-927) or `current`
(a failed local upgrade), both versions are published by definition, so
`-Resume` can never get past step 0 in exactly the states REL-15 wrote it for.
Low, not medium: this is release tooling at the operator's own terminal, the
same exit-3 message names the working path first ("click [ MAKE CURRENT ]
there"), nothing reaches the fleet in a wrong state, and the worst outcome of
following the bad advice is an unnecessary version bump.

Evidence: read HEAD ship.ps1 :245-300 (journal, `Test-StepDone`), :395-470,
:845-935; `api_download_package` (api.py:6674) serves any published version,
staged or current, so the probe does answer 200/206 for a staged build.

## bug-ops-3 - DOWNGRADE (low)

Real. `tools/publish_latest.py` (HEAD, end of `main`) prints
`publish_feed.py --retract --kind <kind> --platform <platform> --version <version> --reason "..." --github-upload`.
In `publish_feed.py`, `--retract` takes one `KIND/PLATFORM/VERSION` value
(:1010), so argparse consumes nothing and fails with "expected one argument";
and `--feed-dir` (:1076) and `--github-repo` (:1079-1080) are both required
for an upload and missing from the hint. Low, not medium: it is a placeholder
template in a hint that fails instantly and loudly, and the correct form is in
the module docstring (:56-57, the `--retract companion/windows/0.6.1 --feed-dir
... --github-repo ... --github-upload` example) and `--help`. It costs the
operator a minute at a bad moment; it cannot publish or retract the wrong thing.

Evidence: read both files at HEAD; the argparse shape is unambiguous (an import
probe from scratch failed on `release_key` path setup, not needed given the
definition).

## bug-wire-1 - CONFIRMED (medium)

Real on both sides. The companion's `_relink_pending_moves` (app.py:8374-8400)
clears its own ledger flag and queues a fresh `ok=True` answer with no
`relink_pending`. The dashboard's only writer, `db.mark_file_move_applied`
(db.py:6202-6252), matches `AND applied_at IS NULL` on both arms, and the
first `ok, relink_pending=True` answer already set `applied_at`, so the second
answer updates zero rows. The api.py:9514 comment even states "Terminal answers
cannot repeat". The row keeps `relink_pending=1` and the first detail for good,
and `partials/project_detail.html:250` renders it per computer as
"moved, Resolve not repointed yet (...)". Medium stands: a permanent false
status on the admin's project page for a relink that happened.

DUPLICATE: bug-comp-app-4 (filed low) is the same defect. Its "nothing renders
it" premise is wrong - the per-target template line above does - so this
entry's severity is the right one to keep.

Evidence: read db.py:6202-6300, api.py:9494-9535, app.py:8244-8270 and
8374-8400, and the template line at HEAD. KNOWN_BUGS RES-10 (~:6993-7023)
says the fresh answer exists "so the dashboard row updates"; nothing does.

## bug-wire-2 - CONFIRMED (medium)

Real. `broll/web/app/fleet_auth.py:173`, `music/web/musicweb/fleet_auth.py:169`
and `ytdl/web/ytdlweb/routes_fleet.py:267` verify `X-CCSync-Identity` with the
current `DASH_SESSION_SECRET` only (`config.get_session_secret()` reads that one
env var); `git grep SESSION_SECRET_PREVIOUS` finds nothing under broll/web,
music/web or ytdl/web. The dashboard's own report path uses
`auth.read_identity_token_ex` and accepts a retired key, logging that "that
editor has to sign in once at their tray" - i.e. nothing re-signs the token
automatically, so the drain window is as long as the slowest editor. BrollGate
strips only `x-ccsync-user`/admin headers, so the old identity header reaches
the sub-app and is refused 403. Medium: rotation is a rare, deliberate act, but
during it ingest/ytdl fail per machine while the fleet grid says accepted.

Related, not a duplicate: bug-dash-ops-2 is the same DASH-2 gap for browser
SESSION COOKIES in the gates (ytdl.py:171, broll.py:232, music.py:242); this
one is the companion identity token checked inside the sub-apps. One fix
(teach the sub-apps/gates the previous keys) could cover both.

Evidence: git grep at HEAD; read fleet_auth.py:150-200, api.py:9210-9280.

## bug-wire-3 - CONFIRMED (medium)

Real. `LaneReportIn` (api.py ~6832) declares raising `max_length` caps
(`last_error` 2000, `detail` 500, `current_project` 512) with no
`mode="before"` `_bound_to_field_caps` validator, and ReportIn's
`_truncate_report_sections` never touches `lanes`, so a long lane error 422s
the whole report (B6's shape). Probe from the dashboard venv (api.py is
unmodified vs HEAD): `LaneReportIn(name="lane_c", state="error",
last_error="x"*2001)` -> `REJECTED string_too_long`. Companion side:
`syncthing_lane.py` builds `last_error` as an unbounded `", ".join(errored)`
with each folder's Syncthing error text (:797, :834-841), and reporter.py
(:792-808) sends it verbatim; no `[:2000]` anywhere on lane fields. Reaching
2000 chars needs roughly 15+ folders erroring with long text at once (e.g.
"folder marker missing (this indicates potential data loss...)"), which is
plausible on a pulled drive or a mass marker loss - exactly when the admin
needs the machine visible. Medium stands (plausible trigger, fleet-grid dropout
and loss of halt/commands for that machine).

Evidence: read api.py 6812-6860, 7192-7265, 9075-9095 at HEAD;
`scratchpad/p_wire3.py`.

## logic-onboarding-2 - CONFIRMED (medium)

Real. `api_verify` returns `report_token: ""` and `report_token_kind: "editor"`
once `DASH_SHARED_REPORT_TOKEN_ENABLED=0`, and says "CR-18 stands: /verify never
mints a cce1 token". `git grep report_token_kind` at HEAD finds only the setter
(api.py:2216), a dashboard test and the old hunt doc: no consumer in the
companion or the wizard. Nothing in companion/src writes
`editor_report_token` except preserving an existing value (identity.py:119-134),
and the wizard has no field for one. The finish page's warnings branch is driven
by `install_warnings`, which nothing populates for this case, so the wizard says
DONE for a machine whose every report will 401. Medium: every new editor on a
site that followed the documented migration (API.md, CONFIG.md, GOTCHAS.md)
installs a machine that silently never appears.

Evidence: read api.py:2168-2230, identity.py:107-170, onboard.py:760-780 and
1325-1345 at HEAD.

## logic-onboarding-3 - DOWNGRADE (low)

The route is real: `installer/windows_upgrade.ps1` (:655-735) launches
onboard.exe whenever the acceptance record is missing, unreadable or older than
the packaged EULA (base rig and `-SkipWizard` excepted), while the relaunched
companion's startup path (app.py ~10995-11020) starts `_licence_watch`, which
offers the same licence on its own. Its `-SkipWizard` copy ("all three tray
lines read 'this machine isn't set up yet'") is also stale against CR-88. But
low, not medium: the wizard is the designed consent path and is documented
"Safe to re-run any time" - it merges config.toml, preserves the Syncthing
identity and SSH key (onboarding/README.md) - so the worst case is an editor
doing a redundant, disruptive-but-safe refresh or seeing two prompts. It only
fires on a hand-run package upgrade across an EULA-version bump, which is rare
(the fleet upgrades through the channel, which never runs this script).

Evidence: read windows_upgrade.ps1:655-735, app.py:6130-6150 and 10995-11020,
onboarding/README.md and onboard.py:405-430 at HEAD.

## logic-onboarding-4 - DOWNGRADE (low)

Real: onboard.py:417, :427, :740, windows_bootstrap.ps1:2463 and
macos_bootstrap.sh:2836 still say "TrueNAS username and password", while
`site.server_phrase()` (site.py ~422-436) exists precisely to remove that vendor
name from editor copy (SYNC-114/APP-10). It is false on a Synology or
`DASH_AUTH_METHOD=local` site. Low, not medium: it is copy only, it is true on
every site deployed today (the studio is TrueNAS with NAS-backed auth), and the
misdirection is recoverable by the admin in one sentence. It matters for the
commercial build and should ride the next copy pass.

Evidence: git grep TrueNAS at HEAD over the three files; read site.py
server_phrase.
