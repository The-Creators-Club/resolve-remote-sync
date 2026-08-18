# The YouTube downloader: what it is, and whose responsibility it is

> **DRAFT FOR COUNSEL — written by engineers, 2026-08-17.** Everything below
> describes what the software actually does and where the lines are drawn in
> code. None of it is legal advice, and none of it is a warranty that any
> particular download is lawful. A lawyer should review the wording here and in
> `ytdl/web/ytdlweb/attestation.py` (the notice editors accept) before this
> feature is offered to a customer.
>
> Written for `docs/COMMERCIAL_READINESS.md` items 2 and 3.

## The short version

CC Sync can download video from YouTube into a project's `Youtube/` folder, so
an editor can cut reference or archive material without leaving the tool.

**The feature is OFF in the software as shipped.** A customer turns it on for
their own deployment, and that act is the customer deciding that downloading
third-party YouTube material is something they are entitled to do — in their
jurisdiction, for their use, under their own agreement with YouTube. The vendor
does not make that decision for them, does not turn it on for them, and does
not ship the components whose only purpose is getting past YouTube's
anti-automation measures.

## What the vendor ships, and what it does not

| | In the default build | How a customer gets it |
|---|---|---|
| The downloader UI, search, review, download | **No** — not mounted, routes 404 | `site.toml` `[features] youtube_download = true` |
| `yt-dlp` (the downloader library) | Installed as a dependency, **unused** while the feature is off | — |
| PO-token provider sidecar (`bgutil-ytdlp-pot-provider`) | **No** — the compose service does not exist | `[features] youtube_unblock = true` |
| deno, the "n-challenge" JavaScript solver | **No** — not provisioned on the NAS, not installed by the companion | `[features] youtube_unblock = true` |
| Signing in to YouTube with browser cookies | **No** — the tray item is hidden, the endpoint refuses, cookie files on disk are ignored | `[features] youtube_unblock = true` |
| The Claude Code / Codex CLIs | **No, and not at any setting** — no copy of either one is contained in, or distributed with, any build of this software | `[features] ai_cli_providers = true` permits *using* one on the host: either one the customer installed themselves, or one the customer's admin fetched **from the publisher, at their own click**, through the SET UP wizard (below) |
| The rights/ToS attestation | Always. It cannot be switched off | — |

The three rows in the middle are what this document calls the **unblock
components**. They exist because YouTube actively resists automated retrieval:
a proof-of-origin token minter, a JavaScript runtime that answers a challenge
designed to be hard for non-browsers, and a mechanism for downloading as a
logged-in account. Whatever an individual customer's position on using them,
they are not something a vendor should install on a customer's behalf and
without being asked, so the software does not.

Nothing is *stripped* from the build. The code for all three stays in the
tree, dormant and labelled at each site, so that a customer who is entitled to
them turns them on with a configuration change and never a different binary.
That is deliberate: a build that silently differs from the one under test is
its own kind of hazard.

## What the customer is responsible for

Everything about the material. Specifically:

1. **Deciding whether they may download at all.** YouTube's Terms of Service
   restrict downloading content other than through features YouTube itself
   provides, or with the rights holder's permission. Whether a given retrieval
   is permitted is between the customer (and their editors) and YouTube.
2. **Clearing rights in anything they use.** A downloaded clip belongs to
   whoever made it. CC Sync grants no rights in any downloaded material, makes
   no representation that a download is lawful, and does not check.
3. **Turning the unblock components on, if they do.** Setting
   `youtube_unblock` is the customer asserting they may take the steps those
   components take.
4. **Telling their editors.** The software makes each editor accept the
   attestation (below), but the customer's own policy is what stands behind it.

## What the software does about it

Four things, all enforced in code rather than described in a manual:

- **Off by default, per site.** `site.toml` `[features] youtube_download`
  decides whether the dashboard mounts the downloader at all. Off, `/ytdl` and
  every fleet download route answer 404, the nav link is absent, and every
  editor's companion hides its YouTube menu items, refuses the loopback
  actions, and installs no downloader tooling. The switch is published to the
  fleet in `GET /api/v1/site` as `features.youtube_download`; a client that
  cannot read it, or reaches a server too old to send it, treats the feature as
  **off**.
- **A rights attestation, before the first download.** Every editor accepts a
  notice stating that they have the right to use the material, that complying
  with YouTube's Terms of Service and copyright law is their responsibility,
  and that CC Sync grants them no rights. It is recorded twice: **per user** in
  the dashboard's own database (username, wording version, digest of the exact
  text, timestamp) and **per machine** in the companion's state (the machine
  that fetches the video from its own address is a party to what happens).
  Downloads are refused until both are present — in the browser, on the fleet
  claim route, and in the companion's own capability check. Re-wording the
  notice bumps its version and re-prompts everyone.
- **A standing notice on the page.** The copyright line and the rate/volume
  disclaimer are shown on the downloader's pages permanently, not only at the
  one-time gate: "downloads are paced deliberately and are not guaranteed to
  succeed… do not build a workflow that depends on this feature being fast,
  available, or complete."
- **Attribution in the artefacts.** Every downloaded clip carries the uploading
  channel and the source URL in its container metadata and in a
  `.credits.json` sidecar beside it, and the fleet's ledger records which
  editor requested it and which machine fetched it.

## Turning it on (customer-configured)

In the customer's own `site.toml`:

```toml
[features]
youtube_download = true
# Only if this customer has decided they may:
youtube_unblock = false
```

then redeploy:

```
python server/install_dashboard_app.py            # reads site.toml
python server/install_dashboard_app.py --enable-youtube            # one-off, without editing the manifest
python server/install_dashboard_app.py --enable-youtube --enable-youtube-unblock
```

`--enable-youtube-unblock` on its own does nothing: the unblock components only
serve the downloader, and the deploy says so rather than provisioning them.

The downloader's two AI calls (search-term expansion and relevance filtering)
need an AI provider, which **the customer supplies**. The supported path is an
API key — Anthropic, OpenAI or DeepSeek — typed on the dashboard's **Settings →
AI providers** page or set in the container's environment
(`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`). It is billed to
their account, it is masked in `--dry-run` output and in every API response,
and on Synology it is written to the 0600 `.env` beside the compose file rather
than into it. Without one the downloader reports "no working AI provider
credential" and nothing else on the dashboard is affected.

### CLI providers: the customer's own subscription, and the customer's own CLI

Since 2026-08-18 the same Settings page can also point the two AI calls at
**Claude Code** or **Codex** — the command-line tools Anthropic and OpenAI
publish, driven by a personal Claude or ChatGPT subscription instead of a
metered API key.

**Neither tool is part of this product.** No copy of either one is contained
in, or distributed with, any build of CC Sync: not in the container image, not
in an installer, not in a release artefact, not in an update package. What CC
Sync contains is an *adapter*: if an executable called `claude` (or `codex`) is
present on the dashboard host, and it has been signed in there, the downloader
can invoke it in its non-interactive mode.

**Installed at the customer's click, from the publisher's own distribution,
not shipped by us.** Since 2026-08-18 the Settings page can also *fetch* one,
because requiring a shell on the server put the feature out of reach of the
customers it was meant for. When an administrator presses SET UP and accepts
the notice, the customer's own server downloads the tool **directly from the
publisher** — `downloads.claude.ai` for Claude Code, the `openai/codex` GitHub
releases for Codex — verifies it against the publisher's own published
checksum, and stores it in the customer's own data volume. The vendor is not
in that path: no copy is hosted, mirrored, cached, modified or redistributed by
CC Sync, no vendor credential is used to obtain it, and nothing is fetched
until an administrator asks for it. It is the same act as that administrator
running the publisher's install command on their own machine, with a button in
place of a terminal. Each tool remains governed by its own publisher's licence
and terms, between the customer and that publisher.

**The sign-in is the customer's, in the customer's browser.** CC Sync cannot
authenticate on anyone's behalf: the wizard runs the tool's own login command,
shows the administrator the authorisation URL it prints, and passes back the
one-time code they paste in. The credential the tool then writes is stored on
the customer's own server, under a directory only that server reads. The
vendor never sees it.

**It is off unless the customer turns it on.** `site.toml` `[features]
ai_cli_providers` (default `false`) is what makes the two rows appear at all;
while it is off they are not even probed — no process is executed, and nothing
can be downloaded. The Settings page carries this sentence above the switch:

> Using a personal Claude/ChatGPT subscription for a service may breach its
> terms — that is your decision.

and the wizard's first step, which an administrator must read and tick before
anything is fetched, says it at length:

> Claude Code and Codex are signed in with a personal Claude or ChatGPT
> subscription. Every YouTube search this dashboard runs, for every editor,
> will be spent on the account you are about to sign in. Using a personal
> subscription to power a service may breach its terms: that is your decision,
> not ours.
>
> CC Sync does not ship, bundle or update either tool. When you click INSTALL,
> this container downloads the publisher's own build, from the publisher's own
> servers, and checks it against the publisher's own checksum before it is
> used. Nothing is installed until you click.
>
> The supported alternative is an API key (Claude API, OpenAI, DeepSeek)
> entered on this page, billed to your own account, with no subscription terms
> in question.

Accepting that notice **is** what sets `ai_cli_providers`: the switch and the
statement of whose subscription is about to be spent are one decision, made in
one place, by a named administrator.

Which is the whole of the vendor's position. **Whether a personal subscription
may be used to power a service, and whether more than one person may benefit
from one seat, is between the customer and the provider of that subscription**;
CC Sync makes no representation that it is permitted, receives nothing from it,
and defaults to the metered API path in which every deployment pays for its own
usage under its own agreement.

This history matters and is recorded in `docs/COMMERCIAL_READINESS.md` item 1:
an earlier version of this feature shipped the 304 MB Claude Code binary onto
customer hardware and ran every deployment under one human's consumer account.
The redistribution was the vendor's to fix and is fixed — nothing is
distributed. What remains is a switch the customer may set for their own host,
their own binary and their own account, and a button that fetches that binary
from its publisher on their instruction.

**A note for counsel on that distinction.** The engineering position is that
"the vendor distributes a copy" and "the vendor's software fetches the
publisher's copy when a customer asks it to" are different acts, and that the
second is what a package manager, an IDE extension installer and the
publisher's own `install.sh` all do. It is drawn in code: no artefact of ours
contains either tool, no vendor-controlled host serves it, no vendor
credential obtains it, the request is unauthenticated and https-only, the
bytes are checked against the publisher's own checksum, and nothing happens
without an administrator's click. Whether that distinction holds under each
publisher's terms is a question for review (open item 5 below).

## Vendored code

`ytdl/web/ytdlweb/vendor/` carries a vendored copy of the `yt-credit-downloader`
utility. Its provenance, and the written licence grant that is owed for it, are
in `ytdl/web/ytdlweb/vendor/PROVENANCE.md`.

## Open items for counsel

1. Review the attestation wording (`ytdl/web/ytdlweb/attestation.py`
   `NOTICE_TEXT`, `COPYRIGHT_NOTICE`, `RATE_DISCLAIMER`) and the companion's
   copy of it (`companion/src/ccsync_companion/ytdl_attestation.py`). The two
   are pinned to the same version string by test; the companion's is trimmed
   for a plain dialog box.
2. Decide whether the EULA (`docs/legal/EULA.md`) needs a clause pointing at
   this document, and whether enabling `youtube_unblock` should require
   something more explicit than a configuration key.
3. Decide the retention period for the attestation records and for the
   download ledger (who downloaded what, when, from which machine). Neither is
   currently pruned.
4. Resolve the vendored-code grant in `PROVENANCE.md`.
5. **The SET UP wizard (2026-08-18).** Confirm that fetching Claude Code from
   `downloads.claude.ai`, and Codex from the `openai/codex` GitHub releases, at
   an administrator's click and into their own server, is not "distribution" by
   the vendor under either publisher's terms, and that the notice quoted above
   is sufficient disclosure of the subscription question at the moment it is
   asked. If either answer is no, the fix is small and known: remove the two
   install routes and go back to the customer typing the publisher's install
   command themselves. The adapter, the flag and the notice are unaffected.
