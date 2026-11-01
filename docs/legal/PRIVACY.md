<!-- Maintainers: every factual statement here is cited to the code, as it
     stood on 2026-09-25. Re-read the citations after any change to
     companion/src/ccsync_companion/reporter.py, the dashboard's
     /api/v1/report route, db.prune, or anything that adds an outbound call.
     A privacy policy that has drifted from the code is worse than none.
     ENG-GAP markers flag statements that describe a missing feature; update
     them when the feature ships. -->

# CC Sync: privacy policy

**Version 1.1, 2026-10-07.**

*Draft for counsel: the changes since 1.0 are the plain no-telemetry statement, the support-mailbox sub-processor, the pointer to `docs/legal/DPA.md` and the Transfers paragraph (CR-377, COM-M4).*

*The DPA, the beta agreement and the support-data procedure cited in this policy are drafts not yet released in the product; the Licensor provides them on request at support@thecreatorsclub.co until they are.*

CC Sync ("the Software") is supplied by **Cablewrap Creative Ltd.**, a
company registered in Taiwan (R.O.C.) ("the Licensor", "we"), and is defined
in `docs/legal/EULA.md`. This document describes what personal data the
Software processes, where it lives, what leaves the Customer's network and to
whom.

It serves two purposes. It is the Licensor's own privacy notice, and it is
the factual basis a Customer uses to write the notice it gives its own staff.
That is why it addresses "the Customer" throughout: the Customer, not the
Licensor, is the one operating the Software and deciding what it collects.

Read it together with **`docs/legal/TELEMETRY.md`**, which is the exact,
field-by-field inventory of what the companion reports. This document explains
the consequences; that one holds the facts.

## 1. The short version

- **CC Sync is self-hosted.** The dashboard, the databases, the media and the
  sync all live on hardware the Customer owns and operates. **No telemetry,
  usage data, crash report, licence check or analytics is sent to the
  Licensor. There is no vendor endpoint that receives Customer data.** The
  only outbound request the companion makes on its own is to the Customer's
  own `dashboard_url` (`reporter.py`, `identity.py`, `upgrade.py`), plus the
  tool downloads listed in section 5. The one automatic request a dashboard can
  make to a Licensor-controlled location is the release-feed check in
  section 5 (on by default in a vendor build, switchable off), which carries
  no Customer data.
- **In normal operation no Customer data leaves the Customer's network for
  the Licensor.** There is no vendor telemetry and no Licensor server that
  holds Customer data. The one automatic request to a Licensor-controlled
  location is a vendor-build dashboard's check of the Licensor's release feed
  (section 5), which carries no Customer data. The only way Customer data
  reaches the Licensor is that the Customer chooses to send it for support
  (section 3): it is emailed through Google Workspace, the support mailbox's
  provider (section 9), or seen in a remote session the Customer starts.
- **The Customer is the data controller** for everything the Software
  collects about its staff. See section 3.
- **The Software can be used to monitor employees.** It records, per named
  person, which Resolve project they have open, how long since their
  workstation last received keyboard or mouse input, the video files on their
  workstation's disk, their media-pool bin structure and their transfer
  throughput, as often as every 5 seconds. See section 6 and
  `docs/legal/TELEMETRY.md`.
- Some optional features send data to third parties **using the Customer's
  own accounts and API keys**: AI providers (Anthropic, OpenAI, DeepSeek),
  YouTube, Hugging Face, Tailscale, the Syncthing relay and discovery
  network, and the Customer's own mail or webhook provider. See section 5.

## 2. What data the Software processes

**Personal data (identifies a person).**

- Editor usernames: the same account name as on the Customer's NAS or
  identity provider (`api.api_report`, the key of nearly every table).
- Workstation hostnames (`platform.node()`, `reporter.py:_build_payload`) and
  a random per-machine identifier the companion creates
  (`~/.ccsync/machine.json`).
- Sign-in credentials at the moment of sign-in. With NAS (`smb`) or
  single-sign-on (`oidc`) authentication, the editor's password is POSTed to
  the Customer's own dashboard, verified against the NAS, and **not stored**
  (`auth.verify_credentials`, `auth._verify_smb`). With the dashboard's own
  accounts (`local`), the dashboard stores a salted scrypt hash of the
  password, never the password itself (`local_users.py`).
- Identity tokens and report tokens held on the workstation in
  `~/.ccsync/identity.json`, written owner-only (`identity.save_identity`).
- Activity data: what each named person is working on, when, whether they are
  at their keyboard, and how fast their connection is. See section 6.
- Diagnostics bundles: a text report of one workstation's sync state,
  including recent log lines, which name that person's paths and open
  project. See section 4.
- An audit log of administrative actions on the dashboard, naming the admin
  who took each one.

**Content data (may contain personal data about third parties).**

- File and folder names, sizes and paths across the project tree.
- The video, audio and project files themselves, moved between the NAS and
  workstations by the sync lanes.
- Derived indexes: b-roll clip descriptions and transcripts in `broll.db`,
  music tags and embeddings in `music.db`. Transcripts of recorded speech are
  personal data about whoever is speaking.

**Not processed.** No screenshots, keystrokes, clipboard, webcam, browsing
history or window titles other than the Resolve project name. The idle
measurement reads only the time of the last input event, never what the input
was (`companion/src/ccsync_companion/idle.py`). No special category data is
collected by design, though it can appear inside the footage the Customer
chooses to store.

## 3. Roles: who is the controller

**The Customer is the controller.** It owns the NAS, runs the dashboard,
chooses the admins, and decides who is monitored and why. Every database the
Software creates sits on its hardware.

**The Licensor is not a processor in ordinary operation**, because ordinary
operation involves no transfer of Customer data to us. There is no vendor
telemetry endpoint. (A vendor-build dashboard's release-feed check, section 5,
carries no Customer data.)

**The Licensor may become a processor during support**, and only then: if the
Customer sends us a diagnostics bundle, a log, a database copy, or grants
remote access to diagnose a problem, we process the personal data it
contains. When we do, we process it only on the Customer's instructions and
only to resolve that support request; we keep it confidential and limit it to
the people working on the request; we use only the sub-processors listed in
section 9; we delete it within the period stated in
`docs/legal/SUPPORT_DATA_PROCEDURE.md` and `docs/legal/DPA.md` (30
days after the request is closed, and earlier on the Customer's request); and we tell the Customer
without undue delay if a personal-data breach affects it. The terms are set
out as a data-processing agreement (GDPR Art. 28) in **`docs/legal/DPA.md`**,
which a Customer can sign by writing to the Licensor at the contact address in section 11. How
support handles what it receives is in
`docs/legal/SUPPORT_DATA_PROCEDURE.md`.

The Customer decides what it sends us, and is responsible for sending only
what the support request needs.

## 4. Where the data lives

| Where | What | Notes |
|---|---|---|
| The Customer's NAS: `/data/dashboard.db` | All fleet telemetry: lane status, machine state, the open Resolve project, idle time, per-file disk manifests, media-pool bin trees, transfer history | Retention per table in `docs/legal/TELEMETRY.md` (7 to 30 days after a machine stops reporting; the Resolve-project mappings and the list of known editors never expire) |
| The Customer's NAS: `/data/dashboard.db` | Diagnostics bundles: one workstation's sync state, recent crash summaries and its last 40 log lines. Sent when the editor presses the diagnostics button, when a lane fails, or when an admin asks that machine | The newest 5 per machine, and none older than 30 days (`db.DIAGNOSTICS_KEEP_PER_MACHINE`, `db.DIAGNOSTICS_MAX_AGE_DAYS`) |
| The Customer's NAS: `/data/dashboard.db` | The admin audit log; the server's alert and notice ledgers | 180 days for the audit log, 120 days for the alert log and cleared notices (`db.prune`) |
| The Customer's NAS: the YouTube downloader's database | YouTube downloader: rights attestations (who accepted, when, which wording) and the download ledger (who requested which video, which machine fetched it) | Only where the Customer enabled the feature. Not deleted automatically |
| The Customer's NAS: the project tree | The footage, projects and assets themselves | The canonical copy |
| The Customer's NAS: `broll.db`, `music.db`, `client_shares.db` | Derived search indexes, including transcripts; client share links | Not deleted automatically: these are the Customer's assets, not logs |
| Each workstation: `~/.ccsync/` | `config.toml`, `identity.json` (tokens, owner-only), `machine.json`, `eula_accepted.json`, `companion.log` (rotated), `syncthing.log`, `crashes/`, `state/` | |
| The Customer's NAS: `${DASH_CRASH_DIR:-<db dir>/crashes}` | Dashboard crash reports (stack traces, which can contain paths and usernames), owner-only, capped at `MAX_CRASH_FILES` | `crash_report.py`. Local only unless the Customer opts in to a sender (section 5) |
| Each workstation: the synced tree | The slice of the project tree that editor syncs | |

Nothing in this table is on Licensor infrastructure.

## 5. What leaves the Customer's network, and to whom

Everything in this section is either optional, configured by the Customer, or
an unavoidable part of a feature the Customer switched on. **None of it
carries Customer data to the Licensor.**

| Recipient | What is sent | When | Source |
|---|---|---|---|
| **AI providers** (Anthropic `api.anthropic.com`; OpenAI and DeepSeek where chosen) | **b-roll indexing with the API backend:** contact-sheet frames of the Customer's own footage, plus any transcript text. **YouTube search:** the topic an editor typed, and the titles, channels and durations of candidate videos. **Timeline Cards:** transcript text for translation, search and section summaries. **Server triage (optional):** a scrubbed report of the dashboard's open problems, including editor and machine names and error text | Only when the feature is used. The b-roll indexer's local backend (llama.cpp with Qwen3-VL) sends nothing | `broll/indexer/broll_index/claude_client.py`; `ytdl/web/ytdlweb/ai_backend.py`; `dashboard/src/ccsync_dashboard/ai_providers.py`, `cards_ai.py`, `triage.py`. Every call uses a **Customer-supplied API key**, or the Customer's own signed-in Claude Code or Codex CLI, and is billed to and logged under the Customer's own account |
| **YouTube / Google** | Search and download requests, and, if the Customer supplies one, a **browser session** that authenticates those requests as a Google account | Only when the `/ytdl` feature is enabled and used | `ytdl/web/ytdlweb/config.py` (`YTDL_COOKIES_FILE`), `vendor/downloader.py`. See `docs/legal/YOUTUBE_FEATURE_NOTICE.md` |
| **Hugging Face, GitHub** (model and runtime downloads) | Nothing but the download request itself | On a machine running the b-roll indexer or the local ingest backend. The dashboard container does not download models | `broll/indexer/broll_index/local_runtime.py`, `companion/src/ccsync_companion/broll_vlm_sidecar.py`; `music/web/musicweb/text_encoder.py` runs a precomputed local file instead |
| **Syncthing global discovery + public relay pool** | Lane C: device IDs, IP addresses, and, when a direct connection cannot be made, **the encrypted file stream itself, routed through third-party relay servers**. Relays see ciphertext, device IDs, addresses and volumes; they cannot read file contents | Whenever lane C runs | Devices are added with `addresses: ["dynamic"]`, and relays and global discovery are left at Syncthing's defaults (on) (`server/accept_device.py`, `sync/syncthing_admin.py`, `app.py:transport_health`) |
| **Tailscale** | If the Customer uses Tailscale for remote access: device names, users, IPs and connection metadata reach Tailscale's coordination service. Content is end-to-end encrypted between nodes. If the Customer publishes client share links with Tailscale Funnel, those pages are reachable from the public internet through Tailscale's servers | Whenever the tailnet is used | `docs/SERVER-SYNOLOGY.md`, `docs/CLIENT_FOLDERS.md`. The Customer's own Tailscale account |
| **The Customer's mail server or webhook** | Alert and weekly-report mail (machine names, editor names, what is wrong), and the triage report | Only if the Customer configures an alert sink (none by default) | `dashboard/src/ccsync_dashboard/alerts.py` |
| **GitHub, downloads.rclone.org, johnvansickle.com, downloads.claude.ai** | Nothing but the download request itself | At install, when the companion refreshes yt-dlp, ffmpeg or deno, and when an admin installs a CLI tool from the dashboard | `installer/windows_bootstrap.ps1`, `installer/macos_bootstrap.sh`, `companion/src/ccsync_companion/sidecar_tools.py`, `ytdlp_manager.py`, `dashboard/src/ccsync_dashboard/cli_tools.py` |
| **The Licensor's release feed** (a static file host, currently GitHub Releases) | A plain download request with no credential and no Customer data. The host, as with any web request, sees the dashboard's IP address | A vendor-build dashboard (the self-install appliance image) checks the Licensor's release feed by default: shortly after each start of the dashboard, then about once a day (or as the site configures it), and whenever an admin asks for a check. A site can turn it off by setting `DASH_RELEASE_FEED_URL` to empty; a site that sets its own `[releases] feed_url` uses that instead | `dashboard/src/ccsync_dashboard/release_feed.py`, `dashboard_update.py` |
| **Sentry (or another error-tracking service), if the Customer opts in** | Dashboard crash reports: stack traces, which can contain file paths and usernames | Only if the Customer sets `DASH_SENTRY_DSN` **and** installs `sentry_sdk`, which the shipped image does not include | `dashboard/src/ccsync_dashboard/crash_report.py`. Off by default. If the Customer turns it on, the account is theirs |
| **The Licensor** | **Nothing**, except what the Customer chooses to send us for support (section 3) | | No vendor endpoint exists |

Two of these deserve a written decision by the Customer before rollout,
because they surprise people:

1. **Syncthing's public relay fallback** means the Customer's encrypted
   footage can transit servers operated by third parties. CC Sync leaves
   Syncthing's relays and global discovery on. A Customer that wants a closed
   deployment can turn both off in Syncthing's settings on the NAS and on
   each workstation, accepting that lane C then stops wherever no direct
   connection exists.
2. **The b-roll indexer's API backend sends frames of the Customer's footage
   to the chosen AI provider.** That suits stock footage and b-roll, and may
   not suit a client's embargoed material. The local backend sends nothing.
   Which backend to use, and whether the Customer's agreement with the AI
   provider covers its material, is the Customer's decision.

## 6. Lawful basis, and the employee-monitoring warning

**This is the part that matters most, and it is the Customer's obligation, not
ours.**

`docs/legal/TELEMETRY.md` sets out exactly what is collected. In summary the
Software continuously records, per named employee: the project they have open,
whether they are at their keyboard, their working pattern over time, the
contents of their local disk, the structure of their own bins, and their
connection throughput.

That is **systematic monitoring of workers' activity**. Before deploying:

- **Pick a lawful basis and document it.** Legitimate interests (Art. 6(1)(f))
  is the realistic one, with a documented balancing test. **Employee consent is
  not a sound basis**: it is rarely freely given in an employment relationship
  (EDPB Guidelines 05/2020; WP29 Opinion 2/2017).
- **Run a DPIA** (Art. 35). Systematic employee monitoring is on essentially
  every supervisory authority's mandatory-DPIA list.
- **Consult the works council where one exists.** In Germany, a system
  *capable* of monitoring performance or behaviour requires the works council's
  agreement before rollout (BetrVG §87(1) No. 6), regardless of whether anyone
  intends to use it that way. Comparable duties exist in Austria, the
  Netherlands, France and the Nordics.
- **Tell the staff** (Arts. 13 and 14). The field table in
  `docs/legal/TELEMETRY.md` is written so it can be handed to them directly.
- **Write down the purpose limitation**: diagnosing sync problems and
  scheduling background work, not performance management. Every dashboard
  admin can see the whole fleet grid, so this must be a rule people know
  about, not an assumption.

**Data minimisation (Art. 5(1)(c)).** Four kinds of reporting can be
switched off without stopping sync, for one computer or for the whole site:
the name of the open Resolve project wherever it is reported, the list of
media files on the computer's disk and the file names in its Resolve and
conflict checks, the Resolve bin structure, and the time since the last
keyboard or mouse input. Switching one off also deletes what the dashboard
already held about it. `docs/legal/TELEMETRY.md`, "What can be turned off",
says how, what still goes to the dashboard, and what each switch costs.

## 7. Retention

Enforced by `db.prune`, run hourly by the dashboard's collector
(`collector.py`, `DASH_INTERVAL_PRUNE` = 3600 s):

| Data | Retained |
|---|---|
| Lane status (current and history) | 30 days |
| Machine state, including the last reported Resolve project and idle time | 30 days |
| Per-file local media manifests, media-pool bin trees, media rollups | 14 days |
| Transfer history | 7 days |
| Live transfer rows | 120 seconds |
| Diagnostics bundles | 30 days, and at most 5 per machine |
| Finished background jobs | 30 days |
| Admin audit log | 180 days |
| Alert log, cleared server notices | 120 days |
| Resolve-project to tree-project mappings; the list of known editors | **Indefinitely** |
| YouTube attestations and download ledger (where enabled) | **Indefinitely** |
| The footage, the b-roll index, the music index, client share links | Indefinitely: they are the Customer's assets |

**Two caveats, stated plainly because they are easy to misread:**

1. The clocks measure **time since the last report**, not time since
   collection. For a person who works every day, the *current* picture is held
   for as long as they keep working; the 14- and 30-day figures describe how
   long a record survives after that person's machine goes quiet.
2. `db.prune` runs only inside the dashboard's collector. The home page's
   collector panel shows when retention last ran, turns amber when it is
   overdue, and the dashboard raises an alert, on its home page and through
   the configured alert channel, when it fails or is overdue.

## 8. Data-subject rights

The Customer, as controller, answers requests from its own staff. What the
Software gives it today:

- **Access and portability (Arts. 15, 20).** An administrator can download
  everything the dashboard holds about a person as one JSON file (Settings,
  Users, Export data), and each person can download their own from their
  account page. The file lists what it does not include: files on the
  person's own computer and on the storage server, Syncthing's own database,
  the text of server triage reports, Timeline Cards working records (kept per
  episode, not per person), sign-in throttle records kept by network address,
  and server snapshots.
- **Erasure (Art. 17).** An administrator can erase a person's activity
  history while keeping their account (Settings, Users, Erase history). That
  removes their computers' past lane and transfer history, completion and
  missing-file records, stored diagnostics bundles, expired sign-in sessions,
  past failed sign-ins (an active sign-in lockout is kept), and the finished
  YouTube requests they made (what they searched for stays on the record of
  each clip downloaded and in the names of the folders the clips are stored
  in). It does not remove their computers' current state, which the
  computers report again on each report unless a reporting switch in section
  6 is off.

  Deleting a person on the Users page removes them from the whole product:
  their account (including their NAS account), every one of their computers'
  records, their Syncthing devices, their known-editor entry, their sessions,
  their history as above, and every credential that could act as them. The
  exception is their finished YouTube requests: a delete keeps them, under
  the stand-in described next, alongside the other YouTube jobs. Their list
  of search terms is removed, but the search text stays on the job and
  download records, and in the folder names, under the stand-in. Erase their
  history first to remove the finished requests themselves. Where
  the dashboard keeps a record of something done (the audit log, alerts and
  notices, background and YouTube jobs, file moves, YouTube downloads and
  rights attestations, and client-folder entries), the person's name and
  their computers' names are replaced by a fixed stand-in, except that an
  administrator's name stays on the audit entries for actions they took until
  those entries expire after 180 days.

  Not covered by either action: the b-roll and music indexes' record of which
  computer indexed a batch (replaced when the index is next published),
  Timeline Cards working records, server triage runs (deleted after 60 days),
  what the studio itself wrote in a client folder's contact details,
  description and notes, and snapshots of the dashboard's storage, which
  expire on their own schedule. Revoked credentials are deleted 180 days
  after revocation.
- **Rectification (Art. 16).** Usernames come from the NAS or the identity
  provider; correct them there.
- **Objection (Art. 21).** In practice this means excluding that person's
  workstation from reporting (a blank `dashboard_url`), which also removes
  managed sync and updates for them. See the data-minimisation note in
  section 6.

Requests should go to the Customer, not to the Licensor. If a request reaches
us, we will refer it to the Customer.

## 9. Sub-processors

The Licensor engages **no sub-processor** in the ordinary operation of the
Software, because we receive no Customer data.

**For support only**, when the Customer sends us a bundle, log or other
material, the Licensor uses **Google Workspace** (Google Ireland Limited for
customers in the EEA and UK, otherwise Google LLC), which provides the
support mailbox (support@thecreatorsclub.co) where that material arrives and is
kept until deletion. The full list, with purpose and location, is in
`docs/legal/DPA.md` Annex III. A Customer that does not want its support data
to pass through that mailbox can say so and arrange another route with us
before sending anything.

The recipients in section 5 are **the Customer's own** suppliers, under the
Customer's own accounts and agreements: its AI providers, Google/YouTube,
Tailscale, its mail or webhook provider, and the Syncthing project's discovery
and relay infrastructure. The Customer should list them in its own record of
processing.

The Licensor does not offer the Software as a hosted or managed service. This
policy describes self-hosted deployments only.

### Transfers

In normal operation the Licensor receives no personal data, so no
international transfer to or from the Licensor takes place. When the Customer
sends support material, it goes to a Licensor based in Taiwan (R.O.C.) through
Google's infrastructure. If the Customer is in the EEA or the UK, that is a
restricted transfer: Taiwan has no EU adequacy decision, so `docs/legal/DPA.md`
incorporates the EU Standard Contractual Clauses (Module 2, controller to
processor) and, for the UK, the ICO's Addendum or the IDTA. Support is
requested only for what the problem needs, and a Customer can redact a bundle
before sending it. The Customer's own transfers to its AI providers, Tailscale
and the other recipients in section 5 are governed by its own agreements with
them.

## 10. Security

- Passwords: with NAS or single-sign-on authentication the dashboard never
  stores a password; it verifies it against the NAS (`auth._verify_smb`) and
  issues a dashboard-signed identity token instead (`identity.py`). With the
  dashboard's own accounts it stores only a salted scrypt hash.
- Identity tokens do not expire on their own (since 2026-08-27). A report
  also needs the editor's report token, and disabling or deleting the
  account revokes that token and the person's dashboard sessions
  (`api._purge_user_credentials`), which is how an admin takes access away.
- Reports are authenticated twice: a report token (per editor, or a shared
  fleet token during migration) plus a dashboard-signed identity token that
  must match the claimed username, or the report is rejected
  (`api.api_report`).
- Tokens on disk are written owner-only (`identity.save_identity`,
  `secretfile.harden`).
- Non-admin editors can see only their own data (`auth.Scope`).
- Updates are signed: every build offered through the upgrade channel carries
  an Ed25519 signature from the Licensor's release key (a passphrase-protected key file held by the Licensor, with offline backups), and the
  companion and dashboard refuse a build that does not verify against the
  public keys already built into them. During the free beta the executables
  carry no operating-system code-signing certificate (no Authenticode, no
  Apple Developer ID); see `docs/legal/BETA_AGREEMENT.md` section 4.
- **Transport.** The companion refuses to send anything, including an
  editor's password, to a dashboard whose address is plain `http://` on the
  public internet, and says so on the tray. The setup wizard will not accept
  such an address. Over plain `http://` to an address on the studio's own
  network or tailnet it works, and shows a note in its Settings; tailnet
  traffic is encrypted underneath by WireGuard. The dashboard records how
  each computer reaches it, as far as it can tell, shows how many use plain
  http, and raises an alert if any computer reaches it over plain http from
  the public internet. Behind a proxy the dashboard is not configured to
  trust, a computer that reaches it over https is counted as plain http on a
  private network.
  The supported deployment serves the dashboard over HTTPS with Tailscale
  Serve.

Report security vulnerabilities to contact@thecreatorsclub.co.

## 11. Contact

**Cablewrap Creative Ltd.**, registered office: No. 111, Minquan Road, Zhuwei
Village, Tamsui District, New Taipei City 251, Taiwan (R.O.C.).

- Privacy and data-protection enquiries: contact@thecreatorsclub.co
- Security vulnerability reports: contact@thecreatorsclub.co

The Licensor has not appointed a data protection officer. Whether the Customer
needs one (GDPR Art. 37) is the Customer's own determination.

## 12. Changes

Each version of this policy carries a version number and date at the top.
When it changes, the new version ships with the Software in `docs/legal/`. A
changed privacy policy does not need to be accepted again, but a Customer can
always tell which version it was given from the copy shipped with its build.
