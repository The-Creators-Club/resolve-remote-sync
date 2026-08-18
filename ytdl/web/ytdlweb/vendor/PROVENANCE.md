# Provenance of `ytdl/web/ytdlweb/vendor/`

**Status: a written licence grant is OWED for this directory.** Nothing here
carries one today. This file records what was verified, what was not, and
exactly what the grant has to say. Written 2026-08-17 for
`docs/COMMERCIAL_READINESS.md` item 2 (the YouTube feature's legal wrapper);
it is an engineering record, not legal advice.

## What is in here

| File | Origin |
|---|---|
| `downloader.py` | Vendored from `yt-credit-downloader/downloader.py`, 2026-08-11, "as close to verbatim as the container allows" — the container edits are marked `# [vendor]` at the code site (two of them, plus a third on 2026-08-18 that reworded two `on_status()` strings off an em dash for house style). |
| `ytsearch.py` | Derived from the same project's `batch_dl.py`: its search half, with the argparse/print layer removed. |
| `__init__.py` | Written for this repo; describes the two edits above. |

## What was verified (2026-08-17)

- **The upstream exists and is in hand.** `E:\Projects\Utilities\yt-credit-downloader`,
  a working checkout on the base rig. Its git remote is
  `https://github.com/The-Creators-Club/Utilities.git`; HEAD at the time of
  writing is `c58a3f37dfd708b382a278084f616ea7f0a9a62a` (2026-08-11), authored
  by **Alex** — the same person and the same organisation (The Creators Club)
  that owns this repository.
- **There is no licence file, licence header, or copyright notice anywhere in
  that project.** No `LICENSE`, no `COPYING`, no `SPDX-License-Identifier`, and
  the `README.md` says nothing about licensing, copyright or authorship. There
  is therefore **no licence to reproduce here** — which is why this file is
  `PROVENANCE.md` and not `LICENSE`.
- **Default copyright applies.** Absent an express grant, the code is
  "all rights reserved" by its author. Today that is harmless because author,
  vendor and only customer are the same party. It stops being harmless the
  moment this software is licensed to someone else, because the grant to that
  customer would be made by a party with nothing in writing behind it.
- **Third-party code inside these files:** none identified. The heavy lifting
  is `yt-dlp` (imported, never vendored — see `__init__.py` for why the import
  is lazy) and `ffmpeg` (invoked as a subprocess). Both are separate
  dependencies with their own terms; neither is redistributed from this
  directory. `yt-dlp` is pinned in `dashboard/deploy/requirements.txt` and is
  installed by pip at deploy time, not shipped in this tree.

## What the written grant has to contain

Whoever signs it needs to be the author of the upstream project (or hold its
copyright by assignment). One page is enough, and it must state:

1. **Who grants.** The copyright holder of `yt-credit-downloader`, by name.
2. **What is granted.** Specifically `downloader.py` and `batch_dl.py` as of
   commit `c58a3f37dfd708b382a278084f616ea7f0a9a62a` — and any later revision
   this repo re-vendors — together with derivative works of them (this
   directory is one).
3. **To whom.** The entity that ships CC Sync, by name, **and its customers**:
   a grant that stops at the vendor does not cover the copies that go out with
   every deployment.
4. **Which rights.** Copy, modify, and redistribute in source and object form,
   including as part of a commercial product, sublicensable to end customers.
5. **For how long, and can it be revoked.** Perpetual and irrevocable, or the
   product has a dependency that can be switched off after it has shipped.
6. **Warranty and liability.** Whatever the parties agree — but say something,
   because silence here is what a dispute is later argued out of.
7. **Attribution, if any is required.** If the author wants a credit line,
   name where it goes (this file, or a NOTICE shipped with the product).

The simplest resolution, given the author and the vendor are currently the same
party, is to **add a permissive licence (MIT or Apache-2.0) to the upstream
repository and re-vendor**, then replace this file with the copied licence
text. That is a five-minute change today and a negotiation later.

## Operator note

Nothing in this directory is exercised unless a site has enabled the YouTube
downloader (`site.toml` `[features] youtube_download`, off by default — see
`docs/legal/YOUTUBE_FEATURE_NOTICE.md`). A deployment with the feature off does
not import it.
