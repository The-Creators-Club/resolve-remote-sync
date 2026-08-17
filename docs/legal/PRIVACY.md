<!-- DRAFT FOR COUNSEL — NOT LEGAL ADVICE. Written 2026-08-17 for
     docs/COMMERCIAL_READINESS.md item 3, which found that the repo had no
     privacy policy and no telemetry disclosure of any kind.
     Every factual statement here was verified against the code on 2026-08-17
     and is cited. It is an engineer's description shaped into the form of a
     privacy policy so a lawyer has something concrete to redline; it has NOT
     been reviewed by a qualified legal professional and it is NOT publishable
     as-is.
     TODO(legal): replace "Cablewrap Creative" with the registered legal
     entity name, its company number and registered address. The placeholder
     was inferred from the operator's email domain and
     is almost certainly NOT the correct contracting entity — confirm before
     use.
     TODO(legal): decide whether this document is (a) a vendor privacy notice,
     (b) a template the customer adapts into their own staff-facing notice, or
     (c) both, split into two files. It is currently written as (c) collapsed
     into one, which is why it addresses "the Customer" throughout. -->

# CC Sync — privacy policy

**Draft of 2026-08-17. DRAFT FOR COUNSEL — not legal advice.**

CC Sync ("the Software") is supplied by **Cablewrap Creative** ("the
Licensor", "we") and is defined in `docs/legal/EULA.md`. This document
describes what personal data the Software processes, where it lives, what
leaves the Customer's network and to whom.

Read it together with **`docs/legal/TELEMETRY.md`**, which is the exact,
field-by-field inventory of what the companion reports. This document explains
the consequences; that one holds the facts.

## 1. The short version

- **CC Sync is self-hosted.** The dashboard, the databases, the media and the
  sync all live on hardware the Customer owns and operates. **No telemetry,
  usage data, crash report, licence check or analytics is sent to the Licensor.
  There is no vendor endpoint. We have not built one.** (VERIFIED: the only
  outbound HTTP the companion performs on its own is to `dashboard_url` —
  `reporter.py`, `identity.py`, `upgrade.py` — plus the pinned tool downloads
  in §5.)
- **The Customer is the data controller** for everything the Software
  collects about their staff. See §3.
- **The Software monitors employees.** It records, per named person, which
  Resolve project they have open, the video files on their workstation's
  disk, their media-pool bin structure and their transfer throughput — as
  often as every 5 seconds. See §4 and `docs/legal/TELEMETRY.md`.
- Some optional features send data to third parties **using the Customer's own
  accounts and API keys**: Anthropic, YouTube, Hugging Face, Tailscale, the
  Syncthing relay and discovery network. See §5.

## 2. What data the Software processes

**Personal data (identifies a person).**

- Editor usernames — the same account name as on the Customer's NAS
  (`api.api_report`, key of nearly every table).
- Workstation hostnames (`platform.node()`, `reporter.py:_build_payload`).
- Sign-in credentials at the moment of sign-in: the editor's NAS username and
  password are POSTed to the Customer's own dashboard, which verifies them
  against the NAS over SMB and **stores neither** (`identity.py`,
  `auth.verify_credentials`, `auth._verify_smb`).
- Identity tokens and report tokens held on the workstation in
  `~/.ccsync/identity.json`, written owner-only (`identity.save_identity`).
- Activity data: what each named person is working on, when, and how fast —
  see §4.

**Content data (may contain personal data about third parties).**

- File and folder names, sizes and paths across the project tree.
- The video, audio and project files themselves, moved between the NAS and
  workstations by the sync lanes.
- Derived indexes: b-roll clip descriptions and transcripts in `broll.db`,
  music tags and embeddings in `music.db`. Transcripts of recorded speech are
  personal data about whoever is speaking.

**Not processed.** No screenshots, keystrokes, clipboard, webcam, browsing
history or window titles other than the Resolve project name. No special
category data is collected by design — though it can obviously appear inside
the footage the Customer chooses to store.

## 3. Roles: who is the controller

**The Customer is the controller.** They own the NAS, they run the dashboard,
they choose the admins (`DASH_ADMIN_USERS`), and they decide who is monitored
and why. Every database this product creates sits on their hardware.

**The Licensor is not a processor for ordinary operation**, because ordinary
operation involves no transfer of anything to us. There is no vendor telemetry
endpoint and no phone-home.

**The Licensor may become a processor during support**, and only then: if the
Customer sends us a log bundle, a database copy, or grants remote access to
diagnose a problem, we process the personal data it contains, on their
instructions, for that purpose. That is a limited, event-driven processing
relationship.

**TODO(legal):** a short data-processing agreement (GDPR Art. 28) covering
support access — purpose limitation, confidentiality, sub-processors,
deletion at the end of the engagement, breach notification. It should be an
annex to the EULA, not a separate negotiation. **This does not exist today.**

**TODO(operator):** a written support-data policy — where log bundles are
stored, for how long, who may open them, and that they are deleted when the
ticket closes.

## 4. Where the data lives

| Where | What | Notes |
|---|---|---|
| The Customer's NAS: `/data/dashboard.db` | All fleet telemetry — lane status, machine state, the open Resolve project, per-file disk manifests, media-pool bin trees, transfer history | Retention per table in `docs/legal/TELEMETRY.md` (14/30 days after a machine stops reporting; sticky project mappings and `known_editors` never expire) |
| The Customer's NAS: the project tree | The footage, projects and assets themselves | The canonical copy |
| The Customer's NAS: `broll.db`, `music.db` | Derived search indexes, including transcripts | No retention policy is implemented; these are treated as assets, not logs |
| Each workstation: `~/.ccsync/` | `config.toml`, `identity.json` (tokens, owner-only), `eula_accepted.json`, `companion.log` (rotated), `syncthing.log`, `state/` | VERIFIED by listing the directory on the base rig, 2026-08-17 |
| The Customer's NAS: `${DASH_CRASH_DIR:-<db dir>/crashes}` | Dashboard crash reports (stack traces, which can contain paths and usernames), owner-only, capped at `MAX_CRASH_FILES` | `crash_report.py`. Local only unless the Customer opts in to a sender — see §5 |
| Each workstation: the P: tree | The slice of the project tree that editor syncs | |

Nothing in this table is on Licensor infrastructure.

## 5. What leaves the Customer's network, and to whom

Everything in this section is either optional, customer-configured, or an
unavoidable part of a feature the Customer switched on. **None of it goes to
the Licensor.**

| Recipient | What is sent | When | Verification |
|---|---|---|---|
| **Anthropic** (`api.anthropic.com`) | **b-roll indexing:** contact-sheet frames of the Customer's own footage, base64-encoded, plus any transcript text, as prompt content. **YouTube search:** the topic an editor typed, and the titles/channels/durations of candidate videos. | Only when the b-roll indexer is run (base rig) or the `/ytdl` search is used | `broll/indexer/broll_index/claude_client.py:image_block,build_message_content`; `ytdl/web/ytdlweb/claude_cli.py`. **Both** use the `anthropic` SDK with a **Customer-supplied `ANTHROPIC_API_KEY`** as of 2026-08-17 (`dashboard/deploy/requirements.txt`, `anthropic>=0.69`) — the calls are billed to, and logged under, the Customer's own Anthropic account |
| **YouTube / Google** | Search and download requests, and — if the Customer supplies one — an **exported `cookies.txt` holding a Google account's session**, which authenticates those requests as that account | Only when the `/ytdl` feature is used | `ytdl/web/ytdlweb/config.py:43-46` (`YTDL_COOKIES_FILE`), `vendor/downloader.py:203-205`. See `docs/COMMERCIAL_READINESS.md` item 2 for the separate legal analysis of this feature |
| **Hugging Face** | Model downloads only (no Customer data) | Base rig indexing only. **The NAS container never does this** — `fastembed` is deliberately excluded from `dashboard/deploy/requirements.txt`, which says so and gives the reason. VERIFIED | `dashboard/deploy/requirements.txt` (b-roll section); `music/web/musicweb/text_encoder.py` runs a precomputed local artefact instead |
| **Syncthing global discovery + public relay pool** | Lane C: device IDs, IP addresses, and — when a direct connection cannot be made — **the encrypted file stream itself, routed through third-party relay servers**. Relays see ciphertext, device IDs, addresses and volumes; they cannot read file contents | Whenever lane C runs | VERIFIED: devices are added with `addresses: ["dynamic"]` and `relaysEnabled`/`globalAnnounceEnabled` are left at their `true` defaults (`server/accept_device.py:184`, `sync/syncthing_admin.py:561`, `app.py:3532-3533`). This is why `transport_health` reports relayed-vs-direct at all |
| **Tailscale** | If the Customer uses Tailscale (the decided remote-access path): device names, users, IPs and connection metadata reach Tailscale's coordination service. Content is end-to-end encrypted between nodes | Whenever the tailnet is used | `docs/SERVER-SYNOLOGY.md`. The Customer's own Tailscale account and contract |
| **GitHub, downloads.rclone.org, johnvansickle.com** | Nothing but the download request itself — no Customer data | At install, and when the companion refreshes yt-dlp/ffmpeg/deno | `installer/windows_bootstrap.ps1`, `installer/macos_bootstrap.sh`, `companion/src/ccsync_companion/sidecar_tools.py`, `ytdlp_manager.py` |
| **Sentry (or another error-tracking service), if the Customer opts in** | Dashboard crash reports — stack traces, which can contain file paths and usernames | Only if the Customer sets `DASH_SENTRY_DSN` **and** installs `sentry_sdk`, which `dashboard/deploy/requirements.txt` deliberately does not | `dashboard/src/ccsync_dashboard/crash_report.py:18-30`. **Off by default and off in the shipped image**: crash files are written locally, owner-only, under `${DASH_CRASH_DIR:-<db dir>/crashes}` and sent nowhere. If the Customer turns this on, the DSN and the account are theirs |
| **The Licensor** | **Nothing.** | — | No vendor endpoint exists |

**TODO(operator):** two of these deserve a decision in writing before rollout,
because they surprise people:

1. Lane C's **public relay fallback** means a Customer's (encrypted) footage
   can transit servers operated by strangers. Syncthing can be configured with
   `relaysEnabled: false` and `globalAnnounceEnabled: false` for a
   closed/on-premises deployment; the Software does not do this today.
2. The **b-roll indexer sends frames of the Customer's footage to Anthropic**.
   That is fine and expected for stock/b-roll, and potentially not fine for a
   client's embargoed material. It must be stated in the sales conversation
   and covered by the Customer's own agreement with Anthropic.

## 6. Lawful basis, and the employee-monitoring warning

**This is the part that matters most, and it is the Customer's obligation, not
ours.**

`docs/legal/TELEMETRY.md` sets out exactly what is collected. In summary the
Software continuously records, per named employee: the project they have open,
their working pattern over time, the contents of their local disk, the
structure of their own bins, and their connection throughput.

That is **systematic monitoring of workers' activity**. Before deploying:

- **Pick a lawful basis and document it.** Legitimate interests (Art. 6(1)(f))
  is the realistic one, with a documented balancing test. **Employee consent is
  not a sound basis** — it is rarely freely given in an employment relationship
  (EDPB Guidelines 05/2020; WP29 Opinion 2/2017).
- **Run a DPIA** (Art. 35). Systematic employee monitoring is on essentially
  every supervisory authority's mandatory-DPIA list.
- **Consult the works council where one exists.** In Germany, a system
  *capable* of monitoring performance or behaviour requires the works council's
  agreement before rollout (BetrVG §87(1) No. 6) — regardless of whether anyone
  intends to use it that way. Comparable duties exist in Austria, the
  Netherlands, France and the Nordics.
- **Tell the staff** (Arts. 13–14). The field table in
  `docs/legal/TELEMETRY.md` is written so it can be handed to them directly.
- **Write down the purpose limitation**: diagnosing sync problems, not
  performance management. Every dashboard admin can see the whole fleet grid,
  so this must be a rule people know about, not an assumption.

**Data minimisation (Art. 5(1)(c)) is currently constrained by the Software.**
There is no configuration switch that disables reporting of the open Resolve
project name, the local file manifest, or the media-pool bin tree while
leaving sync working. The only "off" is to blank `dashboard_url`, which
disables managed sync and upgrades too. Three opt-out switches are TODO'd in
`docs/legal/TELEMETRY.md` and should be treated as a prerequisite for sale
into any jurisdiction with strong workplace-privacy rules.

## 7. Retention

Enforced by `db.prune`, run hourly by the collector (`collector.py:1212`,
`DASH_INTERVAL_PRUNE` = 3600 s):

| Data | Retained |
|---|---|
| Lane status (current and history) | 30 days |
| Machine state — including the last reported Resolve project | 30 days |
| Per-file local media manifests, media-pool bin trees, media rollups | 14 days |
| Transfer history | 7 days |
| Live transfer rows | 120 seconds |
| Resolve-project → tree-project mappings; the list of known editors | **Indefinitely** |
| The footage, the b-roll index, the music index | Indefinitely — they are the Customer's assets |

**Two caveats, stated plainly because they are easy to misread:**

1. The clocks measure **time since the last report**, not time since
   collection. For a person who works every day, the *current* picture is held
   **indefinitely**; the 14- and 30-day figures describe how long a record
   survives after that person's machine goes quiet.
2. `db.prune` is reachable **only** from the collector loop. A deployment
   whose collector thread has stopped expires nothing, and nothing alarms on
   that today.

## 8. Data-subject rights

The Customer, as controller, must answer requests from their own staff. What
the Software gives them today:

- **Access / portability (Arts. 15, 20)** — the data is in one SQLite file,
  `/data/dashboard.db`, and every relevant table is keyed by
  `editor_username`. A `SELECT` per table produces the extract. **There is no
  export button. TODO(engineering).**
- **Erasure (Art. 17)** — a `DELETE` per table, same key. **There is no purge
  action, and no admin UI for it. TODO(engineering).** Note that erasure is
  partly self-executing: stop reporting, and the rows age out within 14–30
  days — except `project_roots` and `known_editors`, which never do.
- **Rectification (Art. 16)** — usernames come from the NAS; correct them
  there.
- **Objection (Art. 21)** — realistically means excluding that person's
  machine from reporting (blank `dashboard_url`), which also removes managed
  sync and upgrades for them. See the minimisation note in §6.

Requests should go to the Customer's own contact, not to the Licensor. If a
request reaches us we will refer it to the Customer.

## 9. Sub-processors

The Licensor engages **no sub-processor** in the ordinary operation of the
Software, because we receive no Customer data.

The recipients in §5 are **the Customer's own** suppliers, under the
Customer's own accounts and agreements: Anthropic, Google/YouTube, Tailscale,
and the Syncthing project's discovery/relay infrastructure. The Customer
should list them in their own record of processing.

**TODO(legal):** if a hosted or managed-service offering is ever sold, this
section is wrong and the whole controller/processor analysis in §3 must be
redone.

## 10. Security

Verified facts, good and bad, so counsel is not surprised later:

- Passwords are never stored by the dashboard; sign-in is verified against the
  NAS over SMB (`auth._verify_smb`) and a signed, expiring identity token is
  issued instead (`identity.py`).
- Reports are authenticated twice — a fleet report token plus a
  dashboard-signed identity token that must match the claimed username, or the
  report is rejected 401 (`api.api_report`).
- Tokens on disk are written owner-only (`identity.save_identity`,
  `secretfile.harden`).
- Non-admin editors can see only their own data (`auth.Scope`).
- **The dashboard is reachable over plain HTTP in the current deployment**
  (`dashboard_url = "http://192.168.0.10:8480"`, verified on the base rig
  2026-08-17), and the sign-in POST carrying the editor's NAS password uses
  that same channel. It is confined to the LAN or an encrypted tailnet, and
  the decided publish path is Tailscale Serve (HTTPS) — but nothing in the
  Software refuses a cleartext URL. **TODO(engineering).**
- **Companion builds are unsigned and the upgrade channel is not
  authenticated** — see `docs/COMMERCIAL_READINESS.md` item 4. That is a
  security issue with privacy consequences (an attacker who can push a build
  can do anything on every editor's machine) and it is tracked there.

## 11. Contact

**TODO(legal/operator):** a security and privacy contact address, and a
decision on whether a DPO is required (Art. 37 — likely not for the Licensor,
possibly for the Customer). Until this is filled in, this document cannot be
issued.

- Privacy / data-protection enquiries: `TODO(legal)`
- Security vulnerability reports: `TODO(legal)` — and see
  `docs/COMMERCIAL_READINESS.md` for the disclosure-policy item.
- Registered entity and address: `TODO(legal)` — "Cablewrap Creative" is a
  placeholder inferred from the operator's email domain and is probably not
  the correct contracting entity.

## 12. Changes

**TODO(legal):** a version marker and change policy, mirroring the
`EULA-VERSION` mechanism in `docs/legal/EULA.md`. Unlike the EULA, a privacy
notice change does not need re-acceptance — but it does need to be
communicated, and a customer needs to be able to tell which version they were
given.
