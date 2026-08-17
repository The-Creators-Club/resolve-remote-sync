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
   no redirects followed, 10s timeout, 1 MiB cap — §5).
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

## 3. `tools/publish_feed.py` — building a feed directory (never uploading)

Run **on the release rig**, next to the offline key, exactly like
`tools/sign_release.py` and `tools/publish_package.py`. It never touches a
network: it reads/writes a local directory and imports `sign_release` for
the actual per-record signing (no second signer implementation).

```powershell
python tools\publish_feed.py --artifact companion\dist\ccsync-companion.exe `
    --kind companion --platform windows --version 0.8.0 --min-version 0.7.12 `
    --signed-binary --notes "fixes the lane B breaker false-positive" `
    --feed-dir .\feed --base-url https://releases.ccsync.app/v1

python tools\publish_feed.py --manifest companion\dist\ccsync-release.json `
    --feed-dir .\feed --base-url https://releases.ccsync.app/v1

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
- **Never uploads.** Getting the directory onto whatever actually serves
  `<base-url>` is one of:

  ```powershell
  # A public "ccsync-releases" GitHub repo, release assets as the CDN:
  gh release upload stable-v1 .\feed\channel.json .\feed\channel.json.sig `
      .\feed\windows\*.exe .\feed\macos\* --clobber -R ccsync/ccsync-releases

  # Any S3-compatible bucket behind a CDN:
  rclone sync .\feed remote:ccsync-releases --checksum
  ```

  Either is "any static file host" — nothing about the format requires a
  particular one, and no server-side code runs at `<base-url>` at all.

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
The admin page (`Admin → Users`, `[ AVAILABLE FROM THE VENDOR ]` section
under Published Packages) is the same underlying functions
(`release_feed.py`) driven from htmx partials instead — "Check now" from a
script and "Check now" from the browser behave identically.

### The dashboard image line

The container image itself **cannot self-update**: there is no Docker
socket mounted (deliberately — `docs/ZERO_TOUCH_PLAN.md` §5, "no Docker
socket, no self-recreate"). The feed's `dashboard_image` field only lets the
admin page say *"image 1.2.3 available (running 0.9.0) — update in your NAS
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
  fully controls it: fetch is capped, redirect-refusing, https-only, and
  nothing is acted on until it verifies.
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

## 6. What this does NOT do

- It does not make the dashboard update its own container image (§4).
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
