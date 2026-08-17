# PRODUCT_REPO.md — the customer-facing repo, and how it is made

This repo is not the repo a customer gets. It is the **private engineering
archive**: 152 commits of reasoning, `KNOWN_BUGS.md`, three dated bug-hunt
ledgers, a commercial audit that doubles as an attack map, and one deployment's
addresses in a few hundred places. All of that is worth keeping and none of it
is worth handing over.

The **product repo** is what a customer, a contractor or an auditor sees: one
squashed commit, a neutral author, no tenant identity. It is produced from this
one, by one command, and it is thrown away and rebuilt rather than maintained.

```powershell
.\tools\make_product_repo.ps1 -Destination E:\Projects\ccsync-product -WhatIf
```

Background: [`COMMERCIAL_READINESS.md`](COMMERCIAL_READINESS.md) item 10
(*"start the product repo from a squashed commit and keep this one as the
private engineering archive"*), 2026-08-17.

---

## Why two repos

| | This repo | The product repo |
|---|---|---|
| History | 152 commits, kept forever | 1 commit, regenerated |
| Author metadata | a real contributor, a machine-derived email | `CC Sync <engineering@example.invalid>` |
| `KNOWN_BUGS.md`, bug-hunt archives | yes — the point of the archive | withheld |
| The commercial audit | yes | withheld |
| One-machine runbooks and session logs | yes | withheld |
| Client catalogue data | git-ignored under `private/` | cannot be reached (untracked) |
| Who reads it | us | customers, contractors, counsel, auditors |

**The rewrite is for IDENTITY, not for keys.** A full-history scan of both
branches on 2026-08-17 found **no key, token, password, private key, `.env` or
cookie jar ever committed** (COMMERCIAL_READINESS.md section B). There is
nothing to rotate and nothing to purge from old objects. What *is* in the
history is:

- a contributor's real name and machine-derived email in 8 commits' author
  fields,
- a named editor's account, hostname and machine dossier,
- one customer's project catalogue and archive filenames,
- this deployment's NAS addresses, pool name, tailnet and brand.

That is why a **squashed export is both sufficient and necessary**. Sufficient:
there is no secret hiding in commit #14 that a fresh init would preserve.
Necessary: rewriting 152 commits with `filter-branch` would buy nothing extra
and would break every commit id cited across the docs that *do* ship.

---

## The recipe

`-WhatIf` first, always. It runs the read-only half — every refusal and the
full tenant-marker table — and creates nothing.

```powershell
# 1. rehearse
.\tools\make_product_repo.ps1 -Destination E:\Projects\ccsync-product -WhatIf

# 2. for real, from a tag (a tag, not HEAD: the product repo's single commit
#    records no provenance otherwise)
.\tools\make_product_repo.ps1 -Destination E:\Projects\ccsync-product -SourceRef v1.0.0
```

Exit codes: `0` clean, `2` refused before anything moved, `1` the export ran
but a verification check failed (the tree is on disk; **do not publish it**).

| Flag | Use |
|---|---|
| `-Destination <path>` | required; refused if non-empty unless `-Force`, and refused if it is inside this repo |
| `-SourceRef <ref>` | default `HEAD`; a tag is the honest choice |
| `-AuthorName` / `-AuthorEmail` | default `CC Sync` / `engineering@example.invalid` (RFC 2606 `.invalid` — undeliverable by construction) |
| `-CommitMessage` | subject of the one commit |
| `-AllowTenantMarkers` | rehearse the export while items 10/11 are still landing. **Not a ship flag** — the verification table still fails and the exit code is still non-zero |
| `-Force` | empty a non-empty destination first |
| `-WhatIf` | native `SupportsShouldProcess`; prints the plan, writes nothing |

### What it actually does

1. **Preflight** — refuses on a dirty tree, an unresolvable `-SourceRef`, a
   destination inside (or containing) this repo, or a missing LICENSE/NOTICE.
   All refusals are collected and printed together; one run tells you
   everything you have to fix.
2. **Marker scan** — `git grep` for each tenant marker *against the ref, with
   the exclusion pathspecs applied*, so the measurement is of the tree that
   would be produced, and is still read-only.
3. **Export** — `git archive <ref>` to a tar, expanded with `tar`.
4. **Prune** — deletes the tracked-but-not-shippable files listed below.
5. **Commit** — `git init -b main`, `git add -A`, one commit with the neutral
   identity forced on **both** the author and the committer trailer.
6. **Verify** — the eight-row pass/fail table, re-derived from the destination
   repo rather than from the plan that built it.

### Two things that are load-bearing

**`git archive` takes only tracked files.** That is what makes the untracked
material unreachable rather than merely excluded: `site.toml`, `private/`, the
five `.venv` directories, `dist/`, `build/`, `.cache/` and `.pytest_cache/`
cannot leak through this path even if somebody deletes the `.gitignore`. The
per-tenant files that *are* tracked are the explicit list below — a much
shorter and much more auditable problem.

**A tar file, not a pipe.** `git archive … | tar -x` is the POSIX idiom and it
corrupts the archive under Windows PowerShell: the pipeline carries .NET
strings, not bytes. And the two tars on this machine disagree about a Windows
path — Windows' own `C:\Windows\System32\tar.exe` (bsdtar) *rejects*
`--force-local`, while Git for Windows' GNU tar 1.35 *requires* it or it reads
`-f C:\…` as `host:path` and tries to open an rmt connection (`tar: Cannot
connect to C: resolve failed`). The script reads `tar --version` and decides;
do not hardcode either.

---

## What is withheld, and why

Every entry is withheld for **identity or internal-only content**. Nothing is
withheld because it contains a secret; there are none. The list lives in
`$TenantFiles` / `$TenantGlobs` at the top of `tools/make_product_repo.ps1`
with the same reasons inline — edit it there, not here, and a listed path that
no longer exists is reported rather than silently skipped.

| Path | Why it does not ship |
|---|---|
| `KNOWN_BUGS.md` | the private defect ledger: NAS addresses and a running list of unfixed defects including "no TLS anywhere". The editor identity in it was scrubbed on 2026-08-17 (item 10 section B); the live defect list is why it still does not ship. Raw material for a customer-facing security whitepaper *later* |
| `docs/COMMERCIAL_READINESS.md` | the audit itself — 2 critical and 5 high findings with `file:line`, plus the packaging strategy. An attack map and a business document in one |
| `docs/macos-onboarding-handoff.md` | one editor's full machine dossier: account, tailnet IP, "SSH is open", home paths |
| `docs/synology-spikes-2026-08-17.md` | 1,316 lines of measurements against one live box (`192.168.0.104`, `100.65.15.123`, tailnet name, share layout) |
| `docs/bug-hunt-*.md` | the three dated hunt archives, 2,384 lines. Every entry is a defect with a reproduction — a customer reads it as a list of live holes, an attacker as a map |
| `docs/macos-first-run-*.md` | dated session logs from one Mac, naming its account and tailnet address |
| `installer/MACOS_FIRST_RUN.md` | the script for our one supervised Mac session; a one-machine runbook, superseded the moment it ran |
| `docs/SYNOLOGY_PORT_PLAN.md` | internal work-package plan, carrying its own status and written to the audit's numbering |
| `broll/HANDOFF.md` | a dated session handoff — and the source of the **unsafe** plain `copy` over the live WAL-mode `broll.db` that item 8 exists to replace. Shipping it would ship the bad recipe |
| `broll/OVERNIGHT.md` | one-rig operating instructions: a literal `C:\Users\alex` python path and the customer's `config.queue.yaml` |
| `CLAUDE.md` | the engineering-repo agent briefing: names the base rig, this fleet and this repo's private conventions, and its own title carries the brand. **Item 13 owes a customer-facing `ARCHITECTURE.md` and install guide in its place** — do not ship this as a substitute |
| `broll/indexer/config.queue.yaml`, `config.ff2.yaml`, `duplicates_report.md`, `broll/eval/queries_*.yaml` | one customer's catalogue: 25 named projects, episode titles, camera bodies, ~450 real archive filenames, and eval queries written against them. Moved to the git-ignored `private/` on 2026-08-17; still listed because they exist in older refs |
| `docs/PRODUCT_REPO.md`, `tools/make_product_repo.ps1` | this document and this script. Both name every marker in full, so both must be excluded or the scan would fail on its own definition — and both are archive documents by construction |

After the prune the script prints an **advisory** (never a failure) listing
surviving documents that still reference a withheld one. A dangling
cross-reference is the visible edge of this list; the fix is usually a sentence
in the surviving doc.

---

## The tenant markers

`$TenantMarkers` in the script. Matched as fixed strings; the three account
names are matched with `-w` (word) or `alex` also matches *Alexander*.

Counts below are `git grep -c` against `HEAD` **with the exclusion list already
applied** — i.e. what would survive into a product repo built today
(2026-08-17, branch `commercial-readiness`, mid-sprint).

| Marker | Hits | What it is |
|---|---|---|
| `Creators_Club` | 543 | tree root name, SMB share, prefix of every derived Syncthing folder id |
| `alex` (word) | 417 | the operator's account; the default admin user in 8 files |
| `/mnt/tank` | 157 | the TrueNAS pool mountpoint literal, 17 compose mounts deep |
| `ruskin` (word) | 155 | a named editor |
| `creators_club` | 62 | the b-roll collection slug and the forced `creators_club_sftp` rclone remote |
| `TheCreatorsPool` | 62 | the ZFS pool name; `drive_swap.py` derives the editor UNC from it |
| `Creators Club` | 59 | brand copy — "your Creators Club drive" in the tray, the topbar, four `index.html` files |
| `leso` (word) | 54 | a named editor's macOS account — in **production** source, not only fixtures |
| `192.168.0.102` | 36 | production NAS LAN IP |
| `creatorsclub` | 34 | `com.creatorsclub.*` bundle ids, launchd labels, plists |
| `100.71.216.3` | 33 | production NAS tailnet IP |
| `Cablewrap` | 15 | the operating company's name |
| `C:\Users\alex` | 12 | dev-machine paths as **dataclass defaults** in both indexers |
| `100.65.15.123` | 7 | the Synology port target's tailnet IP |
| `192.168.0.104` | 5 | the Synology port target's LAN IP — someone else's live box |
| `tail26290e` | 3 | the tailnet name; one hit leaks the whole network's identity |
| `DESKTOP-LQQ41TC` | 1 | an editor's hostname |
| **total** | **1,655** | |

**The counts above predate the 2026-08-17 identity sweep** (item 10 section B).
The four person/machine markers -- the two editor account names, the editor
hostname and the external-disk label -- are now **0** everywhere outside this
document and `$TenantMarkers` itself; the fixtures that used them read
`editor1`/`editor2`/`EDITOR-PC-02`/`EDITOR2-PC`/`EXT-DISK`. They stay in the
marker list as defence in depth: an old ref, a revert or a new file can
reintroduce one, and the scan is what catches that.

The fix for these is **items 10 and 11** — the site manifest, blanked identity
defaults, neutralised fixtures, drive letter and tree shape as data — not more
exclusions. Excluding a source file to make the scan green would ship a product
that cannot build.

**`truenas_admin` is deliberately not a marker.** It is TrueNAS SCALE's own
stock administrator account, the name every box ships with; `site.example.toml`
documents it as such and `docs/SERVER.md` has to be able to write `ssh
truenas_admin@<your-nas>`. Scanning for it fires 37 times on correct, generic
product documentation, and a check that cries wolf 37 times teaches the
operator to reach for `-AllowTenantMarkers`. What is actually tenant about
`ssh truenas_admin@192.168.0.102` is the address — already a marker.

---

## Verifying by hand

The script prints these as a pass/fail table and exits non-zero on any FAIL.
Re-run them yourself against the destination; each should produce the output in
the right-hand column.

```powershell
$P = "E:\Projects\ccsync-product"
```

| # | Command | Expected |
|---|---|---|
| V1 | `git -C $P rev-list --count HEAD` | `1` |
| V2 | `git -C $P log --format='%an <%ae>\|%cn <%ce>'` | exactly one line, `CC Sync <engineering@example.invalid>\|CC Sync <engineering@example.invalid>` — **both halves**, on every commit |
| V3 | `git -C $P grep -nIF -e "Creators_Club"` (and each other marker; `-w` for `alex`/`leso`/`ruskin`) | no output, exit 1 |
| V4 | `git -C $P ls-files \| Select-String 'site\.toml\|\.db$\|identity\.json\|cookies\.txt\|\.pem$\|\.key$\|^private/'` | only `server/tests/fixtures/site.toml` (see below) |
| V5 | `git -C $P ls-files \| Select-String 'KNOWN_BUGS\|bug-hunt\|MACOS_FIRST_RUN\|HANDOFF\|OVERNIGHT\|COMMERCIAL_READINESS'` | no output |
| V6 | `(Get-ChildItem $P -Recurse -File -Force \| Where-Object { $_.FullName -notlike "*\.git\*" }).Count` vs `(git -C $P ls-files).Count` | equal — if the exported `.gitignore` matched a tracked file, `git add -A` would have dropped it silently |
| V7 | for each `*.sh`: `[IO.File]::ReadAllBytes($f) -contains 13` | `False` — **byte-scan, do not grep**: MSYS grep strips CR before matching and will call a CRLF file clean (a CRLF `run.sh` took the dashboard down on 2026-07-26) |
| V8 | `git -C $P ls-files \| Select-String '^(LICENSE\|NOTICE)$'` | both present |

**V4's one allowed exception** is `server/tests/fixtures/site.toml`: `server/`'s
conftest points `$CCSYNC_SITE` at that fixture before anything imports
`common`, so a product repo without it has a whole suite that fails on a fresh
clone. Its contents are invented, and the root `.gitignore` already negates it.

---

## What is still owed before the product repo can ship

The script **refuses** on the first two. They are operator and counsel
decisions and it will not choose for you.

1. **LICENSE** — the repo has none. Without a licence the recipient has no
   right to use the code, which is worse than any licence you might pick. The
   choice is constrained by known facts (COMMERCIAL_READINESS.md item 3):
   `pystray` is **LGPLv3** and is frozen into the single-file companion exe
   (and `tray.py` copies its Win32 internals, which strengthens the
   derivative-work reading), and the installer SFTP-pushes a **GPLv3** static
   ffmpeg onto the customer's NAS — conveying, with no source offer.
2. **NOTICE** — the third-party licence inventory. Start it with
   `pip-licenses` per component, then add by hand everything that does not come
   from pip: ffmpeg, rclone, Syncthing, Tailscale, yt-dlp, the Resolve
   scripting API, htmx, PyInstaller, CLAP/MiniLM/Whisper weights. Item 3's
   table E is the working list; four of its rows are marked *"stated from
   knowledge, not the repo — confirm before quoting"*.
3. **A green marker scan**, which depends on **items 10 and 11 landing first**
   — 1,655 hits today. Until then `-AllowTenantMarkers` rehearses the export
   and still exits non-zero.
4. **A replacement for the withheld docs.** `CLAUDE.md` and `KNOWN_BUGS.md` are
   the two files a newcomer would reach for, and neither ships. Item 13 owes a
   generic install guide, an architecture overview and an API reference; until
   they exist the product repo is a codebase without a front door.

Not gates on the export itself, but gates on *selling* what it produces: items
1–4 of the audit (the Claude subscription path, the YouTube stack, the
licensing posture, code signing).

---

## Re-export policy

Every run is a **fresh squash**. The product repo's single commit has no
ancestry in common with the previous run's, so a downstream clone cannot
`git pull` an update — it can only be replaced. Decide this before anyone
forks it, not after.

**Recommended policy — publish it as a snapshot, not a branch:**

- Re-export **only at a tagged release**, from the tag (`-SourceRef v1.2.0`),
  never from a moving `HEAD`.
- In the destination, after the export: `git tag v1.2.0` and push it as a
  **new, unrelated** history — force-push to a `main` that nobody is expected
  to have based work on, and say so in the product repo's own README.
- Treat customer or contractor changes as **patches sent back to this repo**,
  never as commits in the product repo. There is no merge path back: the
  product repo has no history to merge against, and the next export would
  discard them.
- If a customer needs a real fork with a real history, that is a different
  decision — it means giving up the squash, and it must be made once, in
  writing, with counsel.

---

## Do not run this against a dirty tree, and not during a ship

The script refuses on a dirty working tree and there is deliberately **no
`-AllowDirty`**, unlike `tools\ship.cmd`. A hotfix has to reach the fleet
today; a product repo never does. The refusal is about reproducibility, not
safety: `git archive <ref>` reads the commit and is unaffected by uncommitted
work, so an export from a dirty tree would silently *not* contain what the
operator is looking at — and mid-de-tenanting-sprint, "the repo was mid-edit"
is the likeliest explanation for a surprising marker count.

**Never run it during a ship.** `tools\ship.cmd` builds, publishes and installs
across this repo, `companion/dist` and the NAS; an export taken while that is
in flight names a version that was never published. Ship first, verify with
`tools\check_deploy_drift.ps1`, tag, then export from the tag.

The script never writes to this repo. Its only commands aimed here are
`rev-parse`, `status`, `ls-tree`, `grep` and `archive` — all read-only — and it
says so in its own header, so a reviewer does not have to take this file's word
for it.
