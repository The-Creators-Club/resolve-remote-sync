#requires -Version 5.1
<#
.SYNOPSIS
    Build the CUSTOMER-FACING product repo out of this engineering repo:
    export a clean tree, drop the per-tenant files, and git init it with ONE
    squashed commit under a neutral identity. Read-only against THIS repo.

.DESCRIPTION
    Two repos, on purpose (docs/PRODUCT_REPO.md, docs/COMMERCIAL_READINESS.md
    item 10, 2026-08-17):

      THIS repo   the private engineering archive -- 152 commits of reasoning,
                  KNOWN_BUGS.md, the dated bug-hunt ledgers, the commercial
                  audit. It keeps its history and is never rewritten.
      PRODUCT     what a customer, a contractor or an auditor is handed. One
                  squashed commit, neutral author, no tenant identity.

    The rewrite is for IDENTITY, NOT FOR KEYS. A full-history scan of both
    branches on 2026-08-17 found no key, token, password, private key, .env or
    cookie jar ever committed (COMMERCIAL_READINESS.md section B). What IS in
    the history is a contributor's real name and machine-derived email in 8
    commits' author fields, a named editor's hostname and machine dossier, one
    customer's project catalogue, and this deployment's NAS addresses. None of
    that is a secret to rotate; all of it is somebody's identity to remove. So
    a squashed export is sufficient AND necessary -- filter-branch over 152
    commits would buy nothing extra and would break every commit id cited in
    the docs that survive.

    Five phases, in this order, because the expensive half must never start on
    a tree that is going to be refused:

      1  PREFLIGHT   read-only refusals: dirty tree, bad ref, destination
                     inside the source, missing LICENSE/NOTICE. Collected, not
                     short-circuited -- one run should tell you everything you
                     have to fix, not the first thing.
      2  SCAN        the tenant-marker grep, run against <SourceRef> with the
                     exclusion pathspecs applied, so it is still read-only and
                     still "before anything moves". Phase 5 re-runs the same
                     scan in the destination as proof.
      3  EXPORT      git archive, then prune the tracked-but-not-shippable files.
      4  COMMIT      git init, git add -A, one commit, neutral identity forced
                     on BOTH the author and the committer trailer.
      5  VERIFY      a pass/fail table. Any FAIL exits non-zero.

    git archive takes only TRACKED files. That is the load-bearing property of
    this script: untracked site.toml, private/, the five .venv directories,
    dist/, build/, .cache/ and .pytest_cache/ cannot leak through it even if
    somebody deletes the .gitignore. The per-tenant files that ARE tracked are
    a separate, explicit, commented list below.

    NOTHING here writes to the source repo: the only git commands aimed at it
    are rev-parse, status, ls-tree, grep and archive.

.PARAMETER Destination
    Directory to create the product repo in. Refused if it exists and is
    non-empty, unless -Force (which empties it first). Must NOT be inside the
    source repo -- a destination under the source would be picked up by the
    next git status here and, worse, would appear in its own next export.

.PARAMETER SourceRef
    What to export. Defaults to HEAD. Any committish works; a tag is the
    honest choice for a release (v1.0.0), because the product repo's single
    commit otherwise records no provenance at all.

.PARAMETER AuthorName
    Neutral author/committer name stamped on the one commit.

.PARAMETER AuthorEmail
    Neutral author/committer email. The default is under .invalid (RFC 2606)
    so it can never be delivered to and can never be mistaken for a real
    person's address. Both the author AND the committer fields are forced:
    --author alone leaves the committer trailer set from the running machine's
    git config, which is exactly the leak this script exists to prevent
    (user.email here is machine-derived).

.PARAMETER CommitMessage
    Subject of the squashed commit.

.PARAMETER AllowTenantMarkers
    Proceed even though the marker scan found hits. For rehearsing the export
    while items 10/11 are still landing -- NOT for shipping. The verification
    table still runs and still fails, so the exit code stays non-zero and no
    automation can mistake the result for a clean build.

.PARAMETER Force
    Empty a non-empty destination first.

.EXAMPLE
    .\tools\make_product_repo.ps1 -Destination E:\Projects\ccsync-product -WhatIf

    Always do this first. Runs phases 1-2 and prints the plan; creates nothing.

.EXAMPLE
    .\tools\make_product_repo.ps1 -Destination E:\Projects\ccsync-product -SourceRef v1.0.0
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $true)][string]$Destination,
    [string]$SourceRef = "HEAD",
    [string]$AuthorName = "CC Sync",
    [string]$AuthorEmail = "engineering@example.invalid",
    [string]$CommitMessage = "CC Sync -- initial product release",
    [switch]$AllowTenantMarkers,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Write-Head { param([string]$m) Write-Host ""; Write-Host "-- $m " -ForegroundColor Cyan }
function Write-Row { param([string]$k, [string]$v) Write-Host ("  {0,-32} {1}" -f $k, $v) }
function Write-Ok { param([string]$m) Write-Host "  PASS  $m" -ForegroundColor Green }
function Write-Fail { param([string]$m) Write-Host "  FAIL  $m" -ForegroundColor Red }
function Write-Note { param([string]$m) Write-Host "  ...   $m" -ForegroundColor DarkGray }
function Write-Warn { param([string]$m) Write-Host "  WARN  $m" -ForegroundColor Yellow }

# Native git, no stderr redirection. 2>&1 on a native command under
# $ErrorActionPreference = "Stop" wraps every stderr line in a NativeCommandError
# and can take the whole script down on a command that SUCCEEDED (Windows
# PowerShell 5.1). Exit codes are read from $LASTEXITCODE instead, explicitly,
# at every call site. The argument list is always a single [string[]] so that
# git's own -C / -c flags cannot be mistaken for this function's parameters.
$script:GitExit = 0
function Invoke-GitRaw {
    param([string[]]$GitArgs)
    $ErrorActionPreference = "Continue"
    $out = & git @GitArgs
    $script:GitExit = $LASTEXITCODE
    return $out
}

$RepoRoot = Split-Path -Parent $PSScriptRoot

# --------------------------------------------------------------------------
# The exclusion list: TRACKED files that must not reach a customer.
#
# Derived from git ls-files on 2026-08-17 and re-verified against <SourceRef>
# at run time -- a path listed here that no longer exists is REPORTED, not
# silently ignored, because a typo'd path is indistinguishable from a file
# that quietly came back under a new name.
#
# Everything here is withheld for IDENTITY or INTERNAL-ONLY CONTENT. Nothing
# is withheld because it contains a secret; there are none (section B).
# --------------------------------------------------------------------------
$TenantFiles = @(
    @{ Path = "KNOWN_BUGS.md"
       Why  = "the private defect ledger: NAS addresses and a running list of unfixed defects including 'no TLS anywhere' at line 642. The editor identity was scrubbed out of it on 2026-08-17 (COMMERCIAL_READINESS.md item 10 section B); the live defect list is what still keeps it back. Raw material for a customer-facing security whitepaper LATER -- not a file to hand over as it stands." },
    @{ Path = "docs/COMMERCIAL_READINESS.md"
       Why  = "the commercial audit itself: 2 critical and 5 high security findings with file:line, the licensing debt, and the packaging strategy. An attack map and a business document in one." },
    @{ Path = "docs/macos-onboarding-handoff.md"
       Why  = "one editor's full machine dossier -- account name, tailnet IP, 'SSH is open', home paths. Section B names this file." },
    @{ Path = "docs/synology-spikes-2026-08-17.md"
       Why  = "1,316 lines of measurements against ONE live box: 192.168.0.104, 100.65.15.123, the tailnet name, share layout. Internal engineering evidence for the port, not product documentation." },
    @{ Path = "installer/MACOS_FIRST_RUN.md"
       Why  = "the script for our one supervised Mac session -- a one-machine runbook, superseded the moment it ran." },
    @{ Path = "broll/HANDOFF.md"
       Why  = "a dated session handoff, and the source of the UNSAFE plain copy over the live WAL-mode broll.db that item 8 exists to replace. Shipping it would ship the bad recipe." },
    @{ Path = "broll/OVERNIGHT.md"
       Why  = "one-rig operating instructions: a literal C:\Users\alex python path and the customer's config.queue.yaml." },
    @{ Path = "docs/SYNOLOGY_PORT_PLAN.md"
       Why  = "internal work-package plan carrying its own status ('WP0-WP5 implemented') and written to COMMERCIAL_READINESS.md's numbering. A plan, not a product doc." },
    @{ Path = "CLAUDE.md"
       Why  = "the engineering-repo agent briefing: names the base rig, this fleet and this repo's private conventions, and its own title carries the brand. Item 13 owes a customer-facing ARCHITECTURE.md and install guide in its place -- do NOT ship this as a substitute." },
    @{ Path = "docs/PRODUCT_REPO.md"
       Why  = "the recipe for this export. It documents what is withheld and why, so it is an engineering-archive document by construction." },
    @{ Path = "tools/make_product_repo.ps1"
       Why  = "this script, for the same reason." }
)

# Globs, for families that keep growing. Matched against the ls-tree listing
# with -like, so they use forward slashes and are case-insensitive.
$TenantGlobs = @(
    @{ Glob = "docs/bug-hunt-*.md"
       Why  = "the dated bug-hunt archives (2026-08, -08-11, -08-14: 2,384 lines). Every entry is a defect with a file:line and a reproduction, most fixed, some deliberately deferred -- a customer reads that as a list of live holes and an attacker reads it as a map." },
    @{ Glob = "docs/macos-first-run-*.md"
       Why  = "dated session logs from one Mac, naming its account and its tailnet address." },
    @{ Glob = "broll/indexer/config.queue.yaml"
       Why  = "one customer's catalogue: 25 named projects, episode titles, camera bodies, sizes. Moved to the git-ignored private/ on 2026-08-17; listed here because it is still present in older refs." },
    @{ Glob = "broll/indexer/config.ff2.yaml"
       Why  = "the same catalogue for one production. Moved to private/ 2026-08-17." },
    @{ Glob = "broll/indexer/duplicates_report.md"
       Why  = "roughly 450 real archive filenames from the customer's footage. Moved to private/ 2026-08-17." },
    @{ Glob = "broll/eval/queries_*.yaml"
       Why  = "search eval sets written against that customer's footage; the queries name their productions. Moved to private/ 2026-08-17." }
)

# --------------------------------------------------------------------------
# Tenant markers. Text is matched as a FIXED string (git grep -F) -- the
# addresses contain dots and would otherwise be read as regexes. Word adds -w,
# which is what makes the three account names usable at all: without it "alex"
# also matches Alexander. IgnoreCase adds -i.
#
# DECISION on truenas_admin -- deliberately NOT a marker (2026-08-17).
# It is TrueNAS SCALE's own stock administrator account, the name every box
# ships with; site.example.toml documents it as such and docs/SERVER.md has to
# be able to write "ssh truenas_admin@<your-nas>". Scanning for it fires 37
# times on correct, generic product documentation, and a check that cries wolf
# 37 times teaches the operator to reach for -AllowTenantMarkers. What is
# actually tenant about "ssh truenas_admin@192.168.0.102" is the address --
# and that is already a marker below. Do not add it back.
# --------------------------------------------------------------------------
$TenantMarkers = @(
    @{ Text = "Creators_Club"; Why = "the tree root name, the SMB share name, and the prefix of every derived Syncthing folder id (608 hits at audit time; item 11)" },
    @{ Text = "creators_club"; Why = "the b-roll collection slug and the forced rclone remote name creators_club_sftp (onboarding/steps.py:1770). Same token, other case -- both rows are kept so each count means something on its own." },
    @{ Text = "Creators Club"; IgnoreCase = $true; Why = "brand copy: 'your Creators Club drive' in the tray, the topbar, four index.html files" },
    @{ Text = "creatorsclub"; IgnoreCase = $true; Why = "com.creatorsclub.* bundle ids, launchd labels and plists -- renaming these is a macOS re-install for every editor, so catch them here" },
    @{ Text = "Cablewrap"; IgnoreCase = $true; Why = "the operating company's name" },
    @{ Text = "100.71.216.3"; Why = "production NAS tailnet IP -- was a compiled-in default in companion/config.py, i.e. a second customer's companion phoning home to ours" },
    @{ Text = "192.168.0.102"; Why = "production NAS LAN IP" },
    @{ Text = "192.168.0.104"; Why = "the Synology port target's LAN IP -- someone else's live box, on their LAN" },
    @{ Text = "100.65.15.123"; Why = "the same Synology's tailnet IP" },
    @{ Text = "/mnt/tank"; Why = "the TrueNAS pool mountpoint literal -- the shape a hardcoded server path takes here, and 17 compose mounts deep (157 hits on 2026-08-17)" },
    @{ Text = "TheCreatorsPool"; Why = "the ZFS pool name; drive_swap.py derives the editor UNC from it structurally" },
    @{ Text = "C:\Users\alex"; IgnoreCase = $true; Why = "dev-machine paths as DATACLASS DEFAULTS in both indexers (item 11) -- not examples, but what runs when nobody overrides" },
    @{ Text = "leso"; Word = $true; IgnoreCase = $true; Why = "a named editor's macOS account. Scrubbed out of source, tests and docs on 2026-08-17 (item 10 section B) -- kept here because an old ref, a revert or a new file can reintroduce it" },
    @{ Text = "ruskin"; Word = $true; IgnoreCase = $true; Why = "a named editor, formerly across tests and the ledger; scrubbed 2026-08-17 (fixtures now say editor2), kept as defence in depth" },
    @{ Text = "alex"; Word = $true; IgnoreCase = $true; Why = "the operator's account: the default admin user in 8 files, plus several hundred incidental hits in docs and tests" },
    @{ Text = "DESKTOP-LQQ41TC"; IgnoreCase = $true; Why = "an editor's hostname; scrubbed 2026-08-17 (fixtures now say EDITOR-PC-02 / EDITOR2-PC)" },
    @{ Text = "SAMDISK"; IgnoreCase = $true; Why = "the volume label of one Mac editor's external disk -- it appears inside /Volumes/ paths, so it is identity even where no account name is; scrubbed 2026-08-17 (fixtures now say EXT-DISK)" },
    @{ Text = "tail26290e"; IgnoreCase = $true; Why = "the tailnet name -- it appears in every *.ts.net URL, so one hit leaks the whole network's identity" }
)

# Paths that must not exist in the product repo whatever the exclusion list
# says. This is the root .gitignore restated as an assertion: the ignore file
# is defence in depth, this is the proof it worked. private/ is untracked and
# therefore cannot be in a git archive at all -- assert it anyway, because
# "cannot happen" is how it happens.
$ForbiddenPatterns = @(
    "site.toml", "*.db", "*.db-wal", "*.db-shm", "identity.json",
    "cookies.txt", "youtube-cookies.txt", "*.pem", "*.key", "rclone.conf",
    ".env", "private/*"
)
# ...except the one deliberately-tracked site.toml: server/'s conftest points
# $CCSYNC_SITE at this fixture before anything imports common, so a product
# repo without it has a whole suite that fails on a fresh clone (the reason
# .gitignore already negates it). Its contents are invented.
$ForbiddenAllow = @(
    "server/tests/fixtures/site.toml"
)

Write-Host "=================================================================="
Write-Host " make product repo -- $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host " source: $RepoRoot @ $SourceRef"
Write-Host " dest:   $Destination"
Write-Host "=================================================================="

# --- 1. PREFLIGHT ----------------------------------------------------------

Write-Head "PREFLIGHT (read-only; reports every refusal, not just the first)"

$refusals = @()

$null = Invoke-GitRaw @("-C", $RepoRoot, "rev-parse", "--git-dir")
$isRepo = ($script:GitExit -eq 0)
if (-not $isRepo) {
    $refusals += "not a git repository: $RepoRoot -- git rev-parse --git-dir failed; run this from a checkout"
}

$resolvedRef = ""
if ($isRepo) {
    $resolvedRef = @(Invoke-GitRaw @("-C", $RepoRoot, "rev-parse", "--verify", "$SourceRef^{commit}")) | Select-Object -First 1
    if ($script:GitExit -ne 0 -or -not $resolvedRef) {
        $refusals += "-SourceRef '$SourceRef' does not resolve to a commit -- name a branch, tag or sha that exists"
        $resolvedRef = ""
    }
    else {
        Write-Row "source ref" "$SourceRef -> $resolvedRef"
    }
}

# A dirty tree is refused even though git archive <ref> reads the COMMIT and is
# therefore unaffected by it. The point is reproducibility: an export whose
# operator cannot say which tree it came from is not auditable, and during a
# de-tenanting sprint (fifteen agents in this working tree on 2026-08-17)
# "the repo was mid-edit" is the likeliest explanation for a surprising marker
# count. There is deliberately no -AllowDirty here, unlike tools/ship.cmd: a
# hotfix has to reach the fleet today, a product repo never does.
if ($isRepo) {
    $dirty = @(Invoke-GitRaw @("-C", $RepoRoot, "status", "--porcelain"))
    if ($dirty.Count -gt 0) {
        $refusals += "working tree is dirty ($($dirty.Count) paths) -- commit or stash first; git status --porcelain must be empty so the export is reproducible from a named ref"
    }
    else {
        Write-Ok "working tree is clean"
    }
}

# Destination containment, both directions. Compare canonical full paths with a
# trailing separator on each side, so E:\Projects\resolve-remote-sync-product is
# not mistaken for a child of E:\Projects\resolve-remote-sync.
$destFull = [System.IO.Path]::GetFullPath(
    [System.IO.Path]::Combine((Get-Location).ProviderPath, $Destination))
$srcFull = [System.IO.Path]::GetFullPath($RepoRoot)
$destCmp = $destFull.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
$srcCmp = $srcFull.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
if ($destCmp.StartsWith($srcCmp, [System.StringComparison]::OrdinalIgnoreCase)) {
    $refusals += "destination '$destFull' is inside the source repo -- put it beside the repo, e.g. $(Split-Path -Parent $srcFull)\ccsync-product"
}
if ($srcCmp.StartsWith($destCmp, [System.StringComparison]::OrdinalIgnoreCase)) {
    $refusals += "destination '$destFull' CONTAINS the source repo -- -Force would empty it"
}

$destExists = Test-Path -LiteralPath $destFull
$destNonEmpty = $false
if ($destExists) {
    $destNonEmpty = @(Get-ChildItem -LiteralPath $destFull -Force).Count -gt 0
}
if ($destNonEmpty -and -not $Force) {
    $refusals += "destination '$destFull' exists and is not empty -- delete it, choose another path, or pass -Force to empty it"
}

# LICENSE / NOTICE. The repo has NEITHER as of 2026-08-17 (verified: git
# ls-files matched no LICENSE, NOTICE or COPYING at the root), and this script
# will NOT invent one. Which licence, and what the NOTICE has to say, is an
# operator and counsel decision with constraints that are already known:
# pystray is LGPLv3 and is frozen into the single-file companion exe, and the
# installer SFTP-pushes a GPLv3 ffmpeg onto the customer's NAS with no source
# offer (COMMERCIAL_READINESS.md item 3). Shipping an unlicensed repo is worse
# than shipping none: with no licence, the recipient has no right to use it.
$licenseNames = @("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING")
$noticeNames = @("NOTICE", "NOTICE.md", "NOTICE.txt", "THIRD-PARTY-NOTICES.md")
$tracked = @()
if ($resolvedRef) {
    $tracked = @(Invoke-GitRaw @("-C", $RepoRoot, "ls-tree", "-r", "--name-only", $resolvedRef))
}
if ($tracked.Count -gt 0) {
    Write-Row "tracked files at ref" "$($tracked.Count)"
    $hasLicense = @($tracked | Where-Object { $licenseNames -contains $_ }).Count -gt 0
    $hasNotice = @($tracked | Where-Object { $noticeNames -contains $_ }).Count -gt 0
    if ($hasLicense) { Write-Ok "LICENSE present" }
    else {
        $refusals += "no LICENSE at the repo root in $SourceRef -- add a root file named LICENSE and commit it. Counsel decides WHICH: pystray is LGPLv3 and is frozen into companion/dist/ccsync-companion.exe, and the installer conveys a GPLv3 ffmpeg (COMMERCIAL_READINESS.md item 3). This script will not choose for you."
    }
    if ($hasNotice) { Write-Ok "NOTICE present" }
    else {
        $refusals += "no NOTICE at the repo root in $SourceRef -- add a root file named NOTICE listing every third-party component and its licence. Generate the starting point per component with pip-licenses, then add the non-pip ones by hand: ffmpeg, rclone, Syncthing, Tailscale, yt-dlp, the Resolve scripting API, htmx, PyInstaller (COMMERCIAL_READINESS.md item 3, table E)."
    }
}

# --- 2. TENANT-MARKER SCAN -------------------------------------------------
#
# Run against <SourceRef> with the exclusion pathspecs applied, so it measures
# exactly the tree phase 3 will produce -- and does it without writing a byte.
# Phase 5 re-runs the same scan in the destination as independent proof.

Write-Head "TENANT MARKERS (in $SourceRef, minus the exclusion list)"

# The exclusion list restated as pathspecs. :(exclude,glob) so that * does not
# cross a directory separator; the literal paths need no magic.
$excludeSpecs = @()
foreach ($t in $TenantFiles) { $excludeSpecs += ":(exclude)$($t.Path)" }
foreach ($g in $TenantGlobs) { $excludeSpecs += ":(exclude,glob)$($g.Glob)" }

$markerTotal = 0
if ($resolvedRef) {
    foreach ($m in $TenantMarkers) {
        $flags = @("-I", "-F", "-c")
        if ($m.Word) { $flags += "-w" }
        if ($m.IgnoreCase) { $flags += "-i" }
        $ga = @("-C", $RepoRoot, "grep") + $flags + @("-e", $m.Text, $resolvedRef, "--") + $excludeSpecs
        $lines = @(Invoke-GitRaw $ga)
        # git grep exits 1 for "no match" -- that is success here. Anything
        # above 1 is a real error and must not be read as a clean scan.
        if ($script:GitExit -gt 1) {
            $refusals += "git grep failed (exit $($script:GitExit)) scanning for '$($m.Text)' -- the marker scan cannot be trusted, so nothing is exported"
            break
        }
        $count = 0
        $files = 0
        foreach ($l in $lines) {
            $n = 0
            $tail = $l.Substring($l.LastIndexOf(':') + 1)
            if ([int]::TryParse($tail, [ref]$n)) { $count += $n; $files += 1 }
        }
        $markerTotal += $count
        $label = $m.Text
        if ($m.Word) { $label += " (word)" }
        if ($count -eq 0) { Write-Ok ("{0,-24} 0" -f $label) }
        else { Write-Fail ("{0,-24} {1} lines in {2} files" -f $label, $count, $files) }
    }
}

if ($markerTotal -gt 0) {
    Write-Note "each marker's reason is in the TenantMarkers array at the top of this script; the fix is COMMERCIAL_READINESS.md items 10 and 11 (site manifest, blanked defaults, neutralised fixtures), not more exclusions"
    if (-not $AllowTenantMarkers) {
        $refusals += "$markerTotal tenant-marker hits remain in $SourceRef -- land items 10/11, or withhold the file with a reason in the TenantFiles array, before exporting. -AllowTenantMarkers rehearses the export anyway; it does NOT make the result shippable."
    }
    else {
        Write-Warn "-AllowTenantMarkers: proceeding with $markerTotal hits. The verification table will still FAIL and this script will still exit non-zero."
    }
}

# --- refusal gate ----------------------------------------------------------

if ($refusals.Count -gt 0) {
    Write-Head "REFUSED -- nothing was created"
    foreach ($r in $refusals) { Write-Host "  * $r" -ForegroundColor Red }
    Write-Host ""
    Write-Host "  Fix all of the above and run again. Runbook: docs\PRODUCT_REPO.md"
    Write-Host ""
    # Under -WhatIf these are still real refusals: a rehearsal that reported
    # "would succeed" from a state that will not succeed is worse than no
    # rehearsal at all. The marker table above printed either way, which is the
    # part worth having mid-sprint.
    exit 2
}

# --- 3. EXPORT -------------------------------------------------------------

Write-Head "PLAN"

Write-Row "export" "git archive $SourceRef ($($tracked.Count) tracked files)"
Write-Row "prune (explicit paths)" "$($TenantFiles.Count)"
Write-Row "prune (globs)" "$($TenantGlobs.Count)"
Write-Row "commit as" "$AuthorName <$AuthorEmail>"
Write-Row "message" $CommitMessage

# Resolve the prune list against the ref NOW, so -WhatIf prints exactly what a
# real run would delete -- and so a stale entry is reported rather than
# silently skipped.
$toDelete = @()
foreach ($t in $TenantFiles) {
    if ($tracked -contains $t.Path) { $toDelete += $t.Path }
    else { Write-Warn "listed but not tracked at ${SourceRef}: $($t.Path) -- already removed upstream, or the path is stale; check the TenantFiles array" }
}
foreach ($g in $TenantGlobs) {
    $hit = @($tracked | Where-Object { $_ -like $g.Glob })
    if ($hit.Count -eq 0) {
        Write-Warn "glob matched nothing at ${SourceRef}: $($g.Glob) -- already removed upstream (the client catalogue moved to the git-ignored private/ on 2026-08-17), or the pattern is stale"
    }
    foreach ($h in $hit) { $toDelete += $h }
}
$toDelete = @($toDelete | Sort-Object -Unique)
Write-Host ""
foreach ($p in $toDelete) { Write-Host "  drop  $p" -ForegroundColor Yellow }

if ($WhatIfPreference) {
    Write-Head "-WhatIf"
    Write-Host "  Nothing was created. The plan above is what a real run would do."
    Write-Host "  Still owed before the result can ship: docs\PRODUCT_REPO.md, 'What is still owed'."
    Write-Host ""
    exit 0
}

Write-Head "EXPORT"

if ($destNonEmpty -and $Force) {
    if ($PSCmdlet.ShouldProcess($destFull, "empty (-Force)")) {
        Get-ChildItem -LiteralPath $destFull -Force | Remove-Item -Recurse -Force
        Write-Note "emptied $destFull"
    }
}
if (-not (Test-Path -LiteralPath $destFull)) {
    if ($PSCmdlet.ShouldProcess($destFull, "create directory")) {
        $null = New-Item -ItemType Directory -Path $destFull -Force
    }
}

# A tar file, not a pipe. "git archive ... | tar -x" is the POSIX idiom and it
# CORRUPTS the archive under Windows PowerShell: the pipeline carries .NET
# strings, not bytes, so the tar is re-encoded (and its line endings rewritten)
# on the way through. Write the tar to disk and expand it in a second step.
#
# TWO DIFFERENT TARS live on this machine and they disagree about a Windows
# path (both measured 2026-08-17):
#   C:\Windows\System32\tar.exe  bsdtar/libarchive -- what PowerShell resolves.
#                                Handles "-f C:\...\x.tar" fine and REJECTS
#                                --force-local ("Option --force-local is not
#                                supported", exit 1).
#   Git for Windows' GNU tar 1.35  -- what a Git Bash shell resolves. Reads
#                                "-f C:\..." as host:path and tries to open an
#                                rmt connection: "tar: Cannot connect to C:
#                                resolve failed". Needs --force-local.
# So the flag is decided from `tar --version`, not assumed. Passing it blindly
# breaks the PowerShell path; omitting it blindly breaks anyone who runs this
# from Git Bash (which is where server/'s suite already has to be run).
$tarPath = Join-Path ([System.IO.Path]::GetTempPath()) ("ccsync-product-{0}.tar" -f ([guid]::NewGuid().ToString("N")))
if ($PSCmdlet.ShouldProcess($destFull, "git archive $SourceRef and expand")) {
    $ErrorActionPreference = "Continue"
    $tarVersion = @(& tar --version) -join " "
    $tarProbe = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($tarProbe -ne 0) { throw "no usable tar on PATH -- Windows 10+ ships one at C:\Windows\System32\tar.exe and Git for Windows ships another" }
    $tarArgs = @("-xf", $tarPath, "-C", $destFull)
    if ($tarVersion -match "GNU tar") { $tarArgs = @("--force-local") + $tarArgs }
    Write-Row "tar" ($tarVersion.Trim() -split "\r?\n")[0]

    $null = Invoke-GitRaw @("-C", $RepoRoot, "archive", "--format=tar", "-o", $tarPath, $resolvedRef)
    if ($script:GitExit -ne 0) { throw "git archive failed (exit $($script:GitExit))" }
    Write-Row "archive" "$tarPath ($([int]((Get-Item -LiteralPath $tarPath).Length / 1KB)) KB)"

    $ErrorActionPreference = "Continue"
    & tar @tarArgs
    $tarExit = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    Remove-Item -LiteralPath $tarPath -Force
    if ($tarExit -ne 0) { throw "tar -xf failed (exit $tarExit) -- tar was '$tarVersion'" }
    Write-Ok "expanded $($tracked.Count) tracked files into $destFull"
    # git archive applies the .gitattributes eol rules -- verified 2026-08-17:
    # dashboard/deploy/run.sh comes out LF and tools/release.ps1 CRLF, exactly
    # as they are checked out here. The CRLF run.sh that crash-looped the
    # dashboard on 2026-07-26 cannot come back through this path; V7 below
    # proves that per export rather than trusting it.
}

Write-Head "PRUNE"
foreach ($p in $toDelete) {
    $full = Join-Path $destFull ($p -replace '/', '\')
    if (Test-Path -LiteralPath $full) {
        if ($PSCmdlet.ShouldProcess($full, "delete (per-tenant)")) {
            Remove-Item -LiteralPath $full -Force -Recurse
            Write-Host "  drop  $p" -ForegroundColor Yellow
        }
    }
}
# Directories the prune emptied. docs/ never empties today, but a future entry
# could take the last file in a directory with it, and an empty directory that
# git cannot represent would show up as an unexplained diff later.
Get-ChildItem -LiteralPath $destFull -Recurse -Directory |
    Sort-Object { $_.FullName.Length } -Descending |
    ForEach-Object {
        if (@(Get-ChildItem -LiteralPath $_.FullName -Force).Count -eq 0) {
            Remove-Item -LiteralPath $_.FullName -Force
            Write-Note "removed now-empty directory $($_.FullName.Substring($destFull.Length))"
        }
    }

# --- 4. SQUASHED COMMIT ----------------------------------------------------

Write-Head "COMMIT"

if ($PSCmdlet.ShouldProcess($destFull, "git init + one squashed commit")) {
    $null = Invoke-GitRaw @("-C", $destFull, "init", "-b", "main", "--quiet")
    if ($script:GitExit -ne 0) {
        # git init -b is git >= 2.28. On older git: init, then rename the unborn
        # branch by hand -- git branch -m needs a commit to exist, symbolic-ref
        # does not.
        $null = Invoke-GitRaw @("-C", $destFull, "init", "--quiet")
        if ($script:GitExit -ne 0) { throw "git init failed in $destFull" }
        $null = Invoke-GitRaw @("-C", $destFull, "symbolic-ref", "HEAD", "refs/heads/main")
        if ($script:GitExit -ne 0) { throw "could not set the initial branch to main" }
    }

    $null = Invoke-GitRaw @("-C", $destFull, "add", "-A")
    if ($script:GitExit -ne 0) { throw "git add -A failed in $destFull" }

    # BOTH identities, three ways, because each covers a different hole:
    #   --author=             the author trailer
    #   -c user.name/.email   the COMMITTER trailer -- what --author does not
    #                         set, and where this machine's git config would
    #                         otherwise write a real name and a machine-derived
    #                         email. That exact leak is already in 8 commits of
    #                         this repo's history (section B); it is the whole
    #                         reason the product repo is a fresh init.
    #   GIT_COMMITTER_*       belt and braces, in case a system-level config or
    #                         an include.path outranks -c
    # commit.gpgsign=false because a signature carries the signer's key id --
    # another identity -- and no customer can verify it anyway.
    $savedCN = $env:GIT_COMMITTER_NAME
    $savedCE = $env:GIT_COMMITTER_EMAIL
    $savedAN = $env:GIT_AUTHOR_NAME
    $savedAE = $env:GIT_AUTHOR_EMAIL
    try {
        $env:GIT_COMMITTER_NAME = $AuthorName
        $env:GIT_COMMITTER_EMAIL = $AuthorEmail
        $env:GIT_AUTHOR_NAME = $AuthorName
        $env:GIT_AUTHOR_EMAIL = $AuthorEmail
        $null = Invoke-GitRaw @(
            "-C", $destFull,
            "-c", "user.name=$AuthorName",
            "-c", "user.email=$AuthorEmail",
            "-c", "commit.gpgsign=false",
            "commit", "--author=$AuthorName <$AuthorEmail>", "--quiet", "-m", $CommitMessage)
        if ($script:GitExit -ne 0) { throw "git commit failed in $destFull (exit $($script:GitExit))" }
    }
    finally {
        $env:GIT_COMMITTER_NAME = $savedCN
        $env:GIT_COMMITTER_EMAIL = $savedCE
        $env:GIT_AUTHOR_NAME = $savedAN
        $env:GIT_AUTHOR_EMAIL = $savedAE
    }
    Write-Ok "committed"
}

# --- 5. VERIFY -------------------------------------------------------------
#
# Independent of everything above: these read the DESTINATION repo, not the
# plan that built it. Every row is a command a human can re-run by hand --
# docs\PRODUCT_REPO.md lists them.

Write-Head "VERIFY"

$checks = @()
function Add-Check {
    param([string]$Name, [bool]$Ok, [string]$Detail)
    $script:checks += @{ Name = $Name; Ok = $Ok; Detail = $Detail }
}

$log = @(Invoke-GitRaw @("-C", $destFull, "log", "--format=%an <%ae>|%cn <%ce>"))
$wanted = "$AuthorName <$AuthorEmail>|$AuthorName <$AuthorEmail>"
$badIdent = @($log | Where-Object { $_ -ne $wanted })
Add-Check "V1 exactly one commit" ($log.Count -eq 1) "$($log.Count) commit(s)"
Add-Check "V2 neutral author+committer" ($badIdent.Count -eq 0) "$($badIdent.Count) commit(s) carrying another identity"

$destFiles = @(Invoke-GitRaw @("-C", $destFull, "ls-files"))

$leftMarkers = 0
foreach ($m in $TenantMarkers) {
    $flags = @("-I", "-F", "-c")
    if ($m.Word) { $flags += "-w" }
    if ($m.IgnoreCase) { $flags += "-i" }
    $lines = @(Invoke-GitRaw (@("-C", $destFull, "grep") + $flags + @("-e", $m.Text)))
    if ($script:GitExit -gt 1) { $leftMarkers += 1; continue }
    foreach ($l in $lines) {
        $n = 0
        $tail = $l.Substring($l.LastIndexOf(':') + 1)
        if ([int]::TryParse($tail, [ref]$n)) { $leftMarkers += $n }
    }
}
Add-Check "V3 no tenant markers" ($leftMarkers -eq 0) "$leftMarkers hit(s) across $($TenantMarkers.Count) markers"

$forbidden = @()
foreach ($f in $destFiles) {
    if ($ForbiddenAllow -contains $f) { continue }
    $leaf = Split-Path -Leaf $f
    foreach ($pat in $ForbiddenPatterns) {
        if ($pat.EndsWith("/*")) {
            if ($f -like $pat) { $forbidden += $f }
        }
        elseif ($leaf -like $pat) { $forbidden += $f }
    }
}
$forbidden = @($forbidden | Sort-Object -Unique)
$forbiddenDetail = "site.toml / *.db / identity.json / cookies.txt / *.pem / *.key / private: none"
if ($forbidden.Count -gt 0) { $forbiddenDetail = ($forbidden -join ", ") }
Add-Check "V4 no secret-shaped paths" ($forbidden.Count -eq 0) $forbiddenDetail

$survivors = @($toDelete | Where-Object { $destFiles -contains $_ })
$survDetail = "$($toDelete.Count) path(s) dropped"
if ($survivors.Count -gt 0) { $survDetail = ($survivors -join ", ") }
Add-Check "V5 exclusion list applied" ($survivors.Count -eq 0) $survDetail

# A tracked file that the exported .gitignore happens to match would be
# SILENTLY dropped by git add -A: present on disk, absent from the repo.
# Verified 2026-08-17 that no tracked path matches the ignore list, so this
# should always be zero -- it is here because that ignore list keeps growing.
# The trailing separator is load-bearing: without it the prefix ".git" also
# matches .gitattributes and .gitignore, and this check then failed itself on
# its first real run (2026-08-17).
$gitDirPrefix = (Join-Path $destFull ".git") + [System.IO.Path]::DirectorySeparatorChar
$onDisk = @(Get-ChildItem -LiteralPath $destFull -Recurse -File -Force |
    Where-Object { -not $_.FullName.StartsWith($gitDirPrefix, [System.StringComparison]::OrdinalIgnoreCase) })
Add-Check "V6 nothing dropped by .gitignore" ($onDisk.Count -eq $destFiles.Count) "$($onDisk.Count) file(s) on disk, $($destFiles.Count) tracked"

# Byte-scan for CR. MSYS grep strips CR before matching and will report a file
# clean that is not (CLAUDE.md, 2026-08-10) -- so read the bytes.
$shellFiles = @($destFiles | Where-Object { $_ -like "*.sh" -or $_ -like "*.bash" })
$crShells = @()
foreach ($f in $shellFiles) {
    $bytes = [System.IO.File]::ReadAllBytes((Join-Path $destFull ($f -replace '/', '\')))
    if ($bytes -contains [byte]13) { $crShells += $f }
}
$crDetail = "$($shellFiles.Count) shell script(s), no CR byte"
if ($crShells.Count -gt 0) { $crDetail = ($crShells -join ", ") }
Add-Check "V7 shell scripts are LF" ($crShells.Count -eq 0) $crDetail

$destHasLicense = @($destFiles | Where-Object { $licenseNames -contains $_ }).Count -gt 0
$destHasNotice = @($destFiles | Where-Object { $noticeNames -contains $_ }).Count -gt 0
Add-Check "V8 LICENSE + NOTICE shipped" ($destHasLicense -and $destHasNotice) "LICENSE=$destHasLicense NOTICE=$destHasNotice"

foreach ($c in $checks) {
    if ($c.Ok) { Write-Ok ("{0,-30} {1}" -f $c.Name, $c.Detail) }
    else { Write-Fail ("{0,-30} {1}" -f $c.Name, $c.Detail) }
}

# Advisory, never a failure: a doc that survived and still points at one that
# did not. A dangling cross-reference is the visible edge of the exclusion
# list, and the fix is usually a sentence in the surviving doc, not a re-export.
$dangling = @()
foreach ($p in $toDelete) {
    $leaf = Split-Path -Leaf $p
    $refs = @(Invoke-GitRaw @("-C", $destFull, "grep", "-lIF", "-e", $leaf))
    if ($script:GitExit -le 1 -and $refs.Count -gt 0) { $dangling += "$leaf <- $($refs -join ', ')" }
}
if ($dangling.Count -gt 0) {
    Write-Host ""
    Write-Warn "dangling references to withheld files (advisory, not a failure):"
    foreach ($d in $dangling) { Write-Host "        $d" -ForegroundColor Yellow }
}

Write-Head "RESULT"

$failed = @($checks | Where-Object { -not $_.Ok })
Write-Row "product repo" $destFull
Write-Row "files" "$($destFiles.Count)"
Write-Host ""
if ($failed.Count -eq 0) {
    Write-Ok "all $($checks.Count) checks passed"
    Write-Host ""
    Write-Host "  The source repo was not modified. Runbook: docs\PRODUCT_REPO.md"
    Write-Host ""
    exit 0
}
Write-Fail "$($failed.Count) of $($checks.Count) checks FAILED -- do not publish this tree"
Write-Host ""
Write-Host "  The source repo was not modified. Runbook: docs\PRODUCT_REPO.md"
Write-Host ""
exit 1
