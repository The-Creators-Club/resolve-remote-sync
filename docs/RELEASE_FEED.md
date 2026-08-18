# RELEASE_FEED.md — the vendor release feed ("we publish once, every dashboard pulls")

Written 2026-08-17, `docs/ZERO_TOUCH_PLAN.md` WP E. Read
[`RELEASE.md`](RELEASE.md) first, specifically **"The release signing key"**
— this document extends that trust model, it does not replace it.

## 1. Why this exists

Every fleet's dashboard already trusts one thing without question: a
[signed package record](RELEASE.md#the-release-signing-key) whose Ed25519
signature verifies against a baked/configured public key. Until this
existed, the only way a record reached a dashboard was a human with the
offline release key PUTting bytes into *that specific dashboard*
(`tools/publish_package.py`, `installer/build_editor_package.ps1 -Publish`).
For one customer that is fine. For N customers that is N passwords and N
manual ships every time we fix something.

The release feed is a second, unattended way for a signed record to reach a
dashboard: we publish a small signed JSON document once, to a plain static
file host, and every customer's dashboard pulls it on its own schedule (or
on an admin's "Check now" click) and offers to publish anything it does not
already have. **Nothing about what a companion or a dashboard verifies
changes.** The feed is a second *deliverer* of records that already have to
pass the exact same signature check a human PUT does.

## 2. The channel format (schema v1)

A feed is two files at a stable URL prefix (call it `<base>`):

```
<base>/channel.json          the manifest — plain JSON, world-readable
<base>/channel.json.sig      a DETACHED signature over it, base64 Ed25519
```

### 2.1 `channel.json`

```json
{
  "schema": 1,
  "generated_at": "2026-08-17T18:00:00Z",
  "channel": "stable",
  "pubkey_id": "301d677acf210156",
  "dashboard_image": {"tag": "1.2.3", "digest": "sha256:9f2c...ab12"},
  "packages": [
    {
      "kind": "companion",
      "platform": "windows",
      "version": "0.8.0",
      "filename": "ccsync-companion-0.8.0.exe",
      "sha256": "…64 hex…",
      "size_bytes": 41943040,
      "min_version": "0.7.12",
      "published_at": "2026-08-17T17:55:00Z",
      "signed_binary": true,
      "signature": "…base64, 64 bytes…",
      "pubkey_id": "301d677acf210156",
      "url": "https://releases.ccsync.app/v1/windows/ccsync-companion-0.8.0.exe",
      "notes": "fixes the lane B breaker false-positive"
    }
  ]
}
```

- `schema` — always `1` today. A future incompatible shape bumps it; a
  dashboard that does not understand a `schema` value ignores the channel
  entirely (fail closed, same as an unverifiable signature).
- `channel` — a name (`"stable"` today), not consulted for anything except
  display; kept for a future beta/stable split.
- `pubkey_id` — informational: which key signed the channel wrapper. Trust
  is never decided by this field — see §2.3.
- `dashboard_image` — `tag`/`digest` of the current vendor dashboard image.
  Advisory only: nothing here can pull or apply an update to the container
  (§4). It exists so the admin page can say "an update is available" and
  name the one click that applies it in the NAS's own UI.
- `packages` — a list of **package records in EXACTLY the shape
  `tools/sign_release.py` already produces** (`RECORD_FIELDS` in
  `companion/src/ccsync_companion/release_pubkey.py` /
  `dashboard/src/ccsync_dashboard/release_trust.py`): `kind`, `platform`,
  `version`, `filename`, `sha256`, `size_bytes`, `min_version`,
  `published_at`, `signed_binary` — plus three fields that are NOT part of
  the signed record: `signature`, `pubkey_id` (whose key signed *this
  record* — may differ from the channel's own `pubkey_id` during a
  rotation), `url` (the absolute https download URL — deliberately
  unsigned, same reasoning as the dashboard's own `url` field: see
  `release_pubkey.py`'s docstring, "WHAT IS NOT SIGNED"), and `notes` (a
  short, unsigned, purely cosmetic description).

### 2.1a The `dashboard` record (schema v1, added 2026-08-18)

`ZERO_TOUCH_PLAN.md` WP K. The same channel also carries the **dashboard's own
code**, as a record of kind `dashboard`, platform `linux`:

```json
{
  "kind": "dashboard",
  "platform": "linux",
  "version": "0.5.1",
  "filename": "ccsync-dashboard-0.5.1.tar.gz",
  "sha256": "…64 hex…",
  "size_bytes": 982575,
  "min_version": "0.0.0",
  "published_at": "2026-08-18T17:55:00Z",
  "signed_binary": false,
  "runtime_id": "…64 hex…",
  "signature": "…base64, 64 bytes…",
  "pubkey_id": "301d677acf210156",
  "url": "https://github.com/OWNER/REPO/releases/download/TAG/ccsync-dashboard-0.5.1.tar.gz",
  "notes": "fixes the transfers page's 30s poll"
}
```

Two things are different about it, and only two:

- **A tenth SIGNED field, `runtime_id`.** Every other record signs nine
  fields; a `dashboard` record signs ten. It is inside the signature because
  it is what decides whether an update may be applied at all — an unsigned
  one would let anyone able to serve the feed relabel a bundle as compatible
  with a runtime it was never built for. The extra field is **scoped to the
  kind** (`release_pubkey.KIND_EXTRA_FIELDS` / `release_trust.record_fields`,
  two copies as always), so every `companion`/`onboard` record canonicalises
  byte for byte as it always did: no `v2` prefix, no overlap release, and no
  companion in the field notices anything.
- **It is APPLIED, never PUBLISHED.** A `dashboard` record must never reach
  `companion_packages` — a row there would offer the dashboard's tarball to
  an editor's companion as an upgrade. `release_feed._valid_records` verifies
  it exactly like any other record, and then `package_records()` /
  `dashboard_records()` split the two: the packages table, the `[ PUBLISH ]`
  buttons and the `stage`/`current` auto-publish policy only ever see the
  first list, and `POST /api/v1/admin/feed/publish {kind: "dashboard"}` is a
  400 naming the route that does apply it. The second list is
  `dashboard_update.py`'s (`docs/DOCKER.md`, "Code root selection").

**The two-tier rule.** The image is the runtime; the bundle is the code. A
record whose `runtime_id` equals the running image's `/venv/.runtime-id` is a
**code update**: one button, ~10 s offline, no NAS involved. A record whose
`runtime_id` differs brought a dependency, and the container has no Docker
socket and never will — so it is a **runtime update**: the page names the one
click in the NAS's own UI (`Apps > ccsync > Update` /
`Container Manager > Project ccsync > Build`) and offers no button. Concretely,
a change to `dashboard/deploy/requirements.lock` or to the Dockerfile's
`ARG BASE_IMAGE` line makes the next release a runtime update; anything else
is a code update. The id is `sha256` over exactly those two inputs —
`dashboard/src/ccsync_dashboard/runtime_id.py` is the one implementation, and
both `tools/build_dashboard_bundle.py` and the Dockerfile call it.

**Threat model line.** A `dashboard` record is the only thing in this system
that turns a signed artefact into code the dashboard *executes as itself*, so
it is verified three times, twice more than a companion package: at fetch
(`_valid_records`), at apply (the tarball's sha256 against the signed record,
plus the extracted manifest against that record), and **at every subsequent
boot** — `dashboard/deploy/select_code_root.py` re-checks the record's
signature before the container will run a byte of the installed tree, using
the image's own verifier and the image's own baked keys, never anything from
the data volume. Whoever holds the offline release key can therefore run code
inside a customer's dashboard container — which was already true of every
companion on every editor machine, and is exactly why that key is offline. The
container still cannot reach Docker, the NAS host, or root.

There is no length ceiling on `packages` written down here on purpose — a
real feed carries a handful of records (2 platforms × 2 kinds, occasionally
an old version kept for rollback); `dashboard/src/ccsync_dashboard/
release_feed.py`'s fetch caps the WHOLE document at 1 MiB, which is orders
of magnitude more than any real channel needs.

### 2.2 `channel.json.sig`

Base64 of a 64-byte Ed25519 signature, over:

```
b"ccsync-channel-v1\n" + json.dumps(channel_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
```

where `channel_dict` is the parsed `channel.json` document **exactly as
served** (no `signature` field of its own — the signature is always
detached). The domain-separation prefix (`ccsync-channel-v1\n`) exists so
this signature can never be replayed as a signature over anything else the
same key might be asked to sign — the exact same reasoning as
`release_pubkey.RECORD_PREFIX` for individual package records, just a
second, distinct prefix for a second, distinct kind of document.

Signed by the **same offline release key** as everything in `RELEASE.md`
("The release signing key") — there is only ever one release key for a
vendor, never a separate "feed key". `tools/publish_feed.py` and
`dashboard/src/ccsync_dashboard/release_feed.py` each carry their own copy
of the canonicalisation function (`canonical_channel_bytes`), the same
duplication-on-purpose pattern as `release_pubkey.py`/`release_trust.py`:
two deployment units, neither may import the other, and a comment in both
files says so.

### 2.3 Verification, end to end

1. The dashboard fetches `channel.json` and `channel.json.sig` (https only,
   at most 5 https redirects followed, 10s timeout, 1 MiB cap — §5, and
   §3.1 for why a redirect is followed at all).
2. It verifies the **channel-level** signature against
   `settings.release_pubkeys` (`DASH_RELEASE_PUBKEYS`) — the SAME list the
   PUT route already verifies every publish against. A channel whose
   signature does not verify against a configured key is discarded whole:
   `last_error` is set, nothing is cached as "available", and nothing is
   ever surfaced to an admin. **This is the whole point of the feed: the
   host serving it is never trusted, only the signature is.**
3. Independently, it verifies **each package record's own signature**
   (`release_trust.verify_record`) — belt and braces on top of step 2, in
   case a compromised or buggy feed host could otherwise splice an
   unsigned or mis-signed record into an otherwise-genuinely-signed
   channel wrapper. A record that fails this check is silently dropped
   from `available` (logged, not surfaced) while the rest of the channel
   is still usable.
4. **Publishing** (manual click or an auto-policy) downloads the artefact
   from the record's `url`, hashes it, and checks the hash against the
   record's `sha256`. It then calls the SAME
   `package_store.store_verified_package` the PUT route calls, which
   re-verifies `release_trust.verify_record` a *third* time — this time
   against the record the dashboard is about to write to
   `companion_packages`. Nothing reaches that table without passing this
   check, regardless of which of the two doors (PUT, or the feed) it came
   through.

A compromised or malicious feed host can, at absolute worst: serve nothing
(the dashboard just never sees an update — no different from not checking),
serve a stale channel forever (visible as `last_channel_generated_at` never
advancing), or serve garbage that fails every check above and is logged and
discarded. **It can never make a dashboard install a binary the offline
release key did not sign.**

## 3. `tools/publish_feed.py` — building, signing and publishing a feed

Run **on the release rig**, next to the offline key, exactly like
`tools/sign_release.py` and `tools/publish_package.py`. It reads/writes a
local directory and imports `sign_release` for the actual per-record signing
(no second signer implementation).

Signing is always local and always first. Uploading is a separate, explicit
opt-in (`--github-upload`, 2026-08-18): regenerating a feed directory to look
at it must never publish to the world as a side effect. **The offline release
key is never sent anywhere** — GitHub receives signed bytes, never the thing
that signed them.

```powershell
python tools\publish_feed.py --artifact companion\dist\ccsync-companion.exe `
    --kind companion --platform windows --version 0.8.0 --min-version 0.7.12 `
    --signed-binary --notes "fixes the lane B breaker false-positive" `
    --feed-dir .\feed --base-url https://releases.ccsync.app/v1

python tools\publish_feed.py --manifest companion\dist\ccsync-release.json `
    --feed-dir .\feed --base-url https://releases.ccsync.app/v1

python tools\build_dashboard_bundle.py --out .\dist
python tools\publish_feed.py --artifact .\dist\ccsync-dashboard-0.5.1.tar.gz `
    --kind dashboard --platform linux --version 0.5.1 `
    --feed-dir .\feed --github-repo OWNER/REPO --github-upload

python tools\publish_feed.py --set-image 1.2.3@sha256:9f2c...ab12 --feed-dir .\feed

python tools\publish_feed.py --verify .\feed
```

What it does, per invocation:

- `--artifact` (or `--manifest`, which fills `version`/`platform`/`artifact`/
  `signed_binary` from a `ccsync-release.json` the way `publish_package.py`
  already does, and refuses a `git_dirty`/`tests_run: false` manifest unless
  `--allow-dirty`/`--allow-untested` — OPS-1 applies here too): signs the
  record (`tools/sign_release.py`, imported and called — never
  reimplemented), copies the artefact into `<feed-dir>/<platform>/<filename>`,
  and **replaces** any existing record with the same `(kind, platform,
  version)` in `channel.json` or appends a new one.
- `--kind dashboard` needs no `--runtime-id`: the tool reads it out of the
  bundle's own `manifest.json` and **refuses** a `--runtime-id` that
  disagrees with it. The value is signed, so a typo'd one is not a re-upload
  away from correct, it is a re-sign away — and every customer would meanwhile
  see a runtime update they cannot apply.
- `--set-image tag@digest`: updates `dashboard_image` (can be combined with
  `--artifact` in one run, or run alone to bump only the image line).
- Either action rewrites `channel.json` and re-signs `channel.json.sig`,
  then **re-verifies its own output offline** before printing success — the
  same discipline `sign_release.py` uses (a signature that does not verify
  locally must never leave the rig).
- `--verify <dir>`: offline-checks an existing feed directory — the channel
  signature, every record's signature, and (when the artefact is still
  present locally) that its bytes actually hash to what the record claims.
  Verifies against the SAME baked `RELEASE_PUBKEYS` a real companion/
  dashboard trusts, so `--verify` failing here means a real deployment would
  refuse it too.
- `--github-repo OWNER/REPO --github-upload`: uploads `channel.json`, its
  `.sig` and every artefact to a GitHub release via `gh` (`--clobber`,
  creating the release if absent), after signing and after asserting that
  every signed record URL matches the asset it is about to become. Before
  2026-08-18 the tool refused to upload at all and printed the `gh release
  upload` / `rclone sync` one-liners for a human to run; publishing a release
  is now one command. See §3.1.
- **Any static file host still works.** Nothing in the format requires GitHub
  and no server-side code runs at `<base-url>` at all — an S3-compatible
  bucket behind a CDN is `rclone sync .\feed remote:ccsync-releases
  --checksum` and a `--base-url` naming it. That is the escape hatch for the
  day this moves off GitHub.

### 3.1 GitHub Releases as the host (and its 302)

GitHub Releases is the host we chose. Its URLs have exactly one shape:

```
https://github.com/OWNER/REPO/releases/download/TAG/FILE
```

and `DASH_RELEASE_FEED_URL` is that prefix + `/channel.json`. Give
`publish_feed.py` `--github-repo OWNER/REPO` (with `--github-tag`) rather than
a hand-typed `--base-url`: the URL is baked into the *signed* channel, so one
that disagrees with where the bytes actually land is a channel nobody can fix
without the offline key. A release's assets live in one flat namespace per tag
— there are no directories — so `channel.json`, `channel.json.sig` and every
artefact are siblings under `TAG`, and filenames must be unique across
platforms (they already are: the version and platform are in them).

**Every one of those URLs answers `302`**, with a `Location` on a short-lived
signed `https://release-assets.githubusercontent.com/...` URL (measured
2026-08-18). It is not optional and not a misconfiguration — it is how GitHub
serves assets. Until 2026-08-18 `release_feed.py` refused all 3xx outright, so
a GitHub-hosted feed failed on its very first fetch; it now follows **at most
5 redirects, every hop `https://`**, and refuses a `Location:` on any other
scheme as the downgrade attack it would be. See §5 for why that is safe here
and nowhere else in this codebase.

The tag is stable and re-uploaded to (`gh release upload … --clobber`), so
`<base>` never changes under a deployed dashboard. A private repo will NOT
work: the fetch deliberately sends no credential (§5), so the assets must be
world-readable.

## 4. Dashboard configuration

Three environment variables (`docs/CONFIG.md` §2.3a has the full reference
row):

| Var | Default | Meaning |
|---|---|---|
| `DASH_RELEASE_FEED_URL` | `""` | the absolute URL of `channel.json`. **Empty = the feed is entirely off** — no background thread, no network call, ever. Must be `https://` |
| `DASH_RELEASE_FEED_POLICY` | `manual` | `manual` \| `stage` \| `current` — see below. An unrecognised value falls back to `manual` with a boot warning, never upward |
| `DASH_RELEASE_FEED_INTERVAL` | `86400` | seconds between background checks (floored at 60s) |

Policy, editable at runtime from the admin page or `POST
/api/v1/admin/feed/policy` without a redeploy (persisted in the `feed_state`
table, migration v19 — a runtime override always wins over the env default
so an admin's choice survives until they change it again, but reverts to
the env default if the override is cleared):

- **manual** (default) — nothing is ever auto-published. "Check now" and
  the per-record "Publish" / "Publish + make current" buttons on the admin
  page (or the matching JSON routes) are the only way a feed record ever
  becomes a `companion_packages` row.
- **stage** — every newly-verified record this dashboard does not already
  have is auto-published, but never made current — an admin still flips
  `[ MAKE CURRENT ]` by hand.
- **current** — auto-published **and** made current: full hands-off. An
  admin who wants zero-touch updates end to end sets this once.

### Routes

```
GET  /api/v1/admin/feed             {configured, last_checked_at, last_error,
                                      available: [record, ...], image: {...}}
POST /api/v1/admin/feed/check       force a fetch now
POST /api/v1/admin/feed/publish     {kind, platform, version, make_current}
POST /api/v1/admin/feed/policy      {policy}
```

All four require an admin session, exactly like `/api/v1/admin/packages`.
The admin page (`Settings → Packages`, i.e. `/admin/packages`, the
`[ AVAILABLE FROM THE VENDOR ]` section under Published Packages; it was the
bottom of the Users page until 2026-08-18) is the same underlying functions
(`release_feed.py`) driven from htmx partials instead — "Check now" from a
script and "Check now" from the browser behave identically.

### The dashboard's own update routes

```
GET  /api/v1/admin/dashboard-update          the status view (below)
GET  /api/v1/admin/dashboard-update/status   the same body, polled 1/s while applying
POST /api/v1/admin/dashboard-update/apply    {version, force}
POST /api/v1/admin/dashboard-update/rollback {to_version, restore_db}
```

Admin session + CSRF, same as everything else that changes what runs. The
status body carries `code_updates` and `runtime_updates` separately (the
two-tier rule, §2.1a), the running/image versions and source, the in-progress
step, the last error, and the database backups taken before each update.
`docs/API.md` §5 has the field list; `docs/DOCKER.md` has what happens on
disk.

### The dashboard image line

The container image itself **cannot self-update**: there is no Docker
socket mounted (deliberately — `docs/ZERO_TOUCH_PLAN.md` §5, "no Docker
socket, no self-recreate"). Since 2026-08-18 its **code** can, over this same
feed (§2.1a) — but the image, i.e. Python and the pinned dependency closure,
still changes only in the NAS's own UI. The feed's `dashboard_image` field
lets the admin page say *"image 1.2.3 available (running 0.9.0) — update in your NAS
UI: <the exact click>"*, where the hint depends on the site manifest's
`nas_kind`:

- `synology` → "Container Manager → Project ccsync → Build"
- `truenas` → "Apps → ccsync → Update"
- anything else → a generic pointer at the NAS's own app/container manager

A floating minor tag in the compose file (`ccsync:1`) is what makes that one
click sufficient — see the plan's §3.4.

## 5. Threat model

- **CI never holds the release key.** The key lives offline on the release
  rig (`RELEASE.md`), full stop. `tools/publish_feed.py` runs there, next
  to it, exactly like `sign_release.py`. A hosted CI runner that builds
  companion/onboard artefacts (`.github/workflows/release-*.yml`) uploads
  them as a build artifact; a human downloads them and runs
  `publish_feed.py` by hand, same shape as `docs/RELEASE.md`'s "no-Mac
  path" already documents for `publish_package.py`.
- **The dashboard trusts only the keys it was shipped with**
  (`DASH_RELEASE_PUBKEYS`), not whatever a feed host happens to serve.
  There is no "pin the feed's key on first fetch" trust-on-first-use step
  anywhere in this design — TOFU is exactly the weakness a signed channel
  exists to avoid.
- **The feed host is UNTRUSTED.** It is a CDN, a bucket, a GitHub Releases
  page — no server-side logic, no authentication, nothing secret ever
  stored there. Its only two jobs are "serve these bytes" and "don't serve
  stale bytes forever" (the latter is not even security-critical: a stale
  channel just means no update is offered, not a wrong one). Every
  consumer treats it exactly as it would treat a network attacker who
  fully controls it: fetch is capped, https-only, and nothing is acted on
  until it verifies.
- **Redirects are followed here, and ONLY here** (2026-08-18). `docs/
  GOTCHAS.md` §12's rule is that no dashboard call follows a 3xx, because on
  an *authenticated* call the session cookie / `X-CCSync-Token` /
  `X-CCSync-Identity` would ride along to whatever host the `Location` names.
  These two fetches (`channel.json`/`.sig` and the artefact) are the single
  carve-out, and only because both halves of the justification hold: they
  send **no credential at all** — no cookie, no Authorization, no token, and
  nothing in `release_feed.py` may ever add one — and **every byte they
  return is content-verified** by §2.3 before it is believed. A redirect can
  point the fetch at a different host; it cannot make that host's bytes
  verify against the offline release key, so the redirect target inherits
  exactly the trust the feed host had, which is none. The follow is bounded
  at **5 hops**, and **every hop must be `https://`** — a `Location:` on
  `http://` (or any other scheme) is refused, never fetched, because a
  downgrade is the one thing a network attacker on the path could actually
  use. This carve-out does not extend to any authenticated call anywhere
  else; `dashboard/tests/test_release_feed.py`'s redirect section pins each
  of these rules.
- **Compromise of the feed host** lets an attacker: withhold updates,
  replay an old (but still validly signed, and still floor-checked via
  `min_version`) channel, or serve garbage that is discarded. It does NOT
  let them get an unsigned or relabelled binary installed anywhere — the
  three-layer verify in §2.3 sits between the feed and
  `companion_packages` regardless of entry point.
- **Compromise of a customer's dashboard** (the scenario `RELEASE.md`
  already covers for the PUT route) is unchanged by the feed's existence:
  the feed is a second *source* of signed records, not a second *kind* of
  trust. A compromised dashboard with `stage`/`current` policy can
  auto-publish/auto-current any record the vendor has genuinely signed and
  fed — which is exactly what the customer configured it to do — but it
  still cannot conjure a record the offline key never signed.
- **Air-gapped customers** (no outbound network to the feed host at all)
  are unaffected: `DASH_RELEASE_FEED_URL` stays empty, and the existing PUT
  route (`tools/publish_package.py`, or the admin page's manual upload) is
  the only path, exactly as it is today. The plan calls this out as a WP E
  follow-up ("air-gapped bundle upload") — not yet built; today's answer is
  "use the PUT route".

## 6. Artefacts that are not packages: the CLAP audio model

*Added 2026-08-18, `docs/MUSIC_INGEST_PLAN.md` step 3.* The feed carries one
more kind of thing now, and it deliberately does **not** ride in `packages`:

```json
"artefacts": [
  {
    "kind": "music-clap-audio",
    "version": "1",
    "filename": "music-clap-audio-1.onnx",
    "sha256": "…64 hex…",
    "size_bytes": 279978254,
    "url": "https://github.com/OWNER/REPO/releases/download/TAG/music-clap-audio-1.onnx"
  },
  { "kind": "music-clap-audio", "version": "1",
    "filename": "music-clap-audio-1.params.json", "…": "…" }
]
```

**Why a separate list.** A package record is something a DASHBOARD installs:
it is per-platform, it is signed individually by `sign_release.py`, and
`package_store.store_verified_package` re-verifies that signature before it
reaches `companion_packages`. The CLAP audio tower is none of those things. It
is one platform-independent file that a **companion** downloads and checks
against a sha256 **baked into the binary it is already running**
(`music/indexer/music_models.py`, vendored into the companion as
`music_clap/music_models.py` with a parity gate). Squeezing it into `packages`
would mean inventing a `kind` that nothing may install, a `platform` it does
not have, and a per-record signature no consumer reads.

**What secures it.** The whole channel document is signed
(`canonical_channel_bytes` covers every key, `artefacts` included), so nobody
can add, move or re-point one without the offline release key. The consumer
then verifies the bytes against its own baked digest, which is a stronger
check than a feed signature anyway: a compromised feed host can serve nothing,
or serve something every companion refuses.

**Compatibility.** `release_feed.py` reads `schema` and `packages` and ignores
every other key, so a dashboard on an older image is unaffected — no
migration, no schema bump, and it simply does not see the list.

Publishing, on the release rig, next to the offline key:

```powershell
python tools\publish_feed.py `
    --asset music\web\data\audio_encoder\music-clap-audio-1.onnx `
    --asset music\web\data\audio_encoder\music-clap-audio-1.params.json `
    --asset-kind music-clap-audio --asset-version 1 `
    --feed-dir .\feed --github-repo OWNER/REPO --github-upload
```

- Both files, always: a companion needs the ONNX **and** its params JSON, and
  the params are what drive the numpy mel front end.
- The `--asset-version` is `music_models.MODELS["clap-audio"]["version"]`, and
  it is in the FILENAME so two exports can sit on the feed at once. That is
  the whole migration story: publish the new one, ship a companion that pins
  it, and drop the old file when no build in the field expects it any more.
- **The sha256 the tool prints must match the catalogue in the build you are
  shipping.** They are produced by the same export (`export_audio_encoder.py
  --print-catalogue` writes the block), and if they disagree, every companion
  deletes the download and retries for ever. `--verify` re-checks the bytes on
  disk against the channel before anything is uploaded.
- An artefact whose `url` does not match where the upload will land is refused
  before a byte moves, exactly as a package record is: the URL is inside the
  signed document, so it is not a re-upload away from correct, it is a re-sign
  away.

## 7. What this does NOT do

- It does not make the dashboard update its own container image (§4). Its
  own CODE, yes (§2.1a); the image, no, and that is a decision, not a gap.
- It does not add a second signing key or a second trust anchor —
  `DASH_RELEASE_PUBKEYS` is the only list either the PUT route or the feed
  ever checks against.
- It does not change anything about how a *companion* verifies an update —
  `upgrade.py`/`release_pubkey.py` on the editor side are completely
  unaware the feed exists; they see the same `companion_packages` row
  either way.
- It does not run without `DASH_RELEASE_FEED_URL` set — an existing
  deployment that never sets it gets no new thread, no new network call,
  no new UI beyond one line saying how to turn it on.
