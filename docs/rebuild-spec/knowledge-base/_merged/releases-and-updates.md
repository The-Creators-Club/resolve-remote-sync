# Releases and updates

## Facts about Windows, macOS and the NAS that bite an update

### REL-001: A new Mac program copied over the old file was killed at launch.
- What was going on: macOS caches a program's code signature per file, so overwriting a signed program in place fails the check ("Invalid Page") and the system kills it at start.
- What the product must do: Every install or update on macOS writes the new program to a new file and renames it over the old one, never overwriting in place.
- Kind: 1a
- From: P12-052, L10-067, G01-021, M02-010

### REL-002: On a Mac, the app lost its disk permission after an update, or never started.
- What was going on: macOS ties grants such as Full Disk Access to the code signature; an ad-hoc-signed app loses them on update, and a refused launch is silent.
- What the product must do: An update on macOS keeps the app's permissions and its ability to start, and a refused launch is visible to someone.
- Kind: 1a
- State: still open
- From: C01-056

### REL-003: Windows antivirus held the installed program, and the update still said complete.
- What was going on: Windows antivirus can hold an installed program file for over ten seconds, so replacing it fails and the old version starts again.
- What the product must do: An update that cannot replace the program reports failure, says what holds the file, and is never counted as installed.
- Kind: 1a
- From: H01-025

### REL-004: A file someone has open over the share cannot be replaced.
- What was going on: An editor running the installer straight off the NAS share kept it open, so publishing a new one failed, yet the release said it was complete.
- What the product must do: When publishing cannot replace a file on the share, the release fails loudly and names the file.
- Kind: 1a
- From: H04-061

### REL-005: A script written on Windows failed on the Mac and took the NAS dashboard down.
- What was going on: Windows line endings make shell scripts fail on macOS and the NAS ("Illegal option -", "bad interpreter"), many text tools hide them, and Windows drops the executable mark.
- What the product must do: Every script that runs on a Mac or the NAS is checked byte by byte for Windows line endings and executable permission before any package is assembled.
- Kind: 1a
- From: H02-026, G01-022, C01-021

### REL-006: A stock Windows install refuses to run script files directly.
- What was going on: Running a script by name failed with "running scripts is disabled on this system", for release steps and an install script alike.
- What the product must do: Nothing a person is told to run requires them to change Windows' script policy first.
- Kind: 1a
- From: P05-041

### REL-007: Windows warns every editor who installs an unsigned program.
- What was going on: Without a paid code-signing certificate every fresh Windows install shows a SmartScreen warning, and the setup program a new editor runs first was never set up for signing.
- What the product must do: Every Windows program a person runs, first-run installer included, ships code-signed, and a release states which of its files are unsigned.
- Kind: 1a
- State: still open
- From: P06-034, H03-038

## Version numbers

### REL-008: Version 1.10 was ranked below 1.9.
- What was going on: Comparing versions as text puts 1.10 below 1.9 and 1.9.9 above 1.9.65, which stops prompts or refuses valid updates.
- What the product must do: Every version comparison compares each dotted part as a number.
- Kind: 3
- From: M02-079, C02-022, L04-029

### REL-009: A computer on a build with a version suffix never finished a pushed update.
- What was going on: A version with a suffix marking local changes did not parse as a number, so a push to a computer already on it was resent every report for ever.
- What the product must do: A suffixed build counts as its numeric version for completing a push, but never as newer than the clean build of that version.
- Kind: 3
- From: L06-010, H05-012

### REL-010: The beta keeps a pre-release version number until the paid release.
- What was going on: The owner ruled the launch is a free open beta with only minor version bumps; the first whole-number version is his statement for the paid launch.
- What the product must do: Every beta build carries a pre-release version number, and nothing raises it to the first whole-number version without the owner's explicit launch decision.
- Kind: 2
- From: H08-005, M01-067

## Signing and trust

### REL-011: The release signing key never leaves the owner's offline machine.
- What was going on: The owner ruled builds may be made in the cloud but signed only on his machine, since a leaked key reaches code every editor's computer runs at logon.
- What the product must do: Builds may be produced anywhere, but signing happens only on the offline machine holding the key, after verifying the build there.
- Kind: 2
- From: C02-060, M02-081

### REL-012: The key the whole fleet trusts sat unprotected, with no backup.
- What was going on: The owner ruled the key is a passphrase-protected file with two offline backups in different places for the beta, and a hardware token before the paid release.
- What the product must do: Signing asks for the passphrase every time, the key restores from either backup, missing backups are reminded each release, and a written plan exists for a stolen key.
- Kind: 2
- State: fixed, never shipped
- From: H07-028, L11-059, H08-015, L05-017

### REL-013: A signing-key change would have stranded every computer on its current build.
- What was going on: Each computer trusts only the keys inside the build it already runs, so a build signed only with a new key is refused everywhere.
- What the product must do: A key change first ships a build signed by the old key that trusts both; publishing a build no installed computer trusts is impossible.
- Kind: 3
- From: L02-064, L10-047, H06-052

### REL-014: Anyone posing as the dashboard could install any program on every computer.
- What was going on: An update and its checksum arrived in one unauthenticated reply, and one desktop app installed whatever program sat in a shared folder beside a hash.
- What the product must do: Every app the product installs refuses any update whose signature does not verify against a key built into it, whatever the update's source.
- Kind: 3
- State: still open
- From: L01-022, H08-054

### REL-015: The app installed a genuine signed installer over itself as an update.
- What was going on: Updates were accepted on signature alone, so a signed installer replaced the app and launched at every logon.
- What the product must do: An update is installed only if its signed record names this app and this platform.
- Kind: 3
- From: L03-082, H04-028

### REL-016: A replayed old signed build could roll a computer back past safety fixes.
- What was going on: Every signed release carried a minimum version of zero, so any genuine old build could be installed again.
- What the product must do: A release that fixes something a downgrade would bring back raises the minimum version, and computers refuse anything below it.
- Kind: 3
- From: H04-026

### REL-017: One typo in a minimum version could freeze every computer's updates.
- What was going on: A record whose minimum version exceeded its own version raised each computer's floor on mere receipt, refusing that build, its corrected republish and any rollback.
- What the product must do: Such a release is refused at signing, publishing and on every computer, and a refused offer never changes any computer's floor.
- Kind: 3
- From: H03-010

### REL-018: An old or wrongly dated release list could lock computers out.
- What was going on: Nothing checked a release list was fresh, so an old one could be replayed; once checked, a list stamped hours ahead by a fast clock blocked every later one.
- What the product must do: Computers refuse a release list older than one already seen, and list dates never go backwards because a publisher's wrong clock is caught and named.
- Kind: 3
- State: fixed, never shipped
- From: H07-029, L11-039

### REL-019: New fields in an update record made older apps refuse every update for ever.
- What was going on: Older builds fail the whole signature on fields they do not know, refuse silently, and need a reinstall at each desk.
- What the product must do: Update records stay verifiable by every build still reporting in; release notes, shown as one line in the offer, never change what older builds verify.
- Kind: 3
- From: M02-076, L05-011, L06-034, L04-124

## Making and publishing a release

### REL-020: A release should be one short command.
- What was going on: The owner, facing several manual steps: "there used to be one command which did all of this ... rebuild, pushed it to dashboard, pushed to tray utility".
- What the product must do: One command builds, publishes and offers a release to every computer, refusing before anything moves if a check fails.
- Kind: 2
- From: P03-023

### REL-021: A release failed twenty minutes in, or halfway, for something known at the start.
- What was going on: An unsigned build or a byte mismatch was refused only after deploys, tests and packaging, sometimes after the release was already tagged and approved.
- What the product must do: Every refusal a release can meet is checked before its first long or irreversible step.
- Kind: 3
- State: fixed, never shipped
- From: M02-082, L11-040

### REL-022: One version number meant two different programs.
- What was going on: Two builds of one commit differ in bytes, and republishing a version with new bytes swapped the served file under its checksum, so computers failed to update.
- What the product must do: A version always means one set of bytes everywhere; republishing identical bytes changes nothing, different bytes are refused as a conflict, and the studio tests exactly what customers receive.
- Kind: 3
- State: outcome not found
- From: H04-024, H08-014, L09-014

### REL-023: An untested build from any branch could reach customers.
- What was going on: Publishing took the newest green build regardless of branch or version, one route skipped the tests entirely, and the customer channel lagged the studio by weeks.
- What the product must do: Only an unmodified main-line build above every published version, whose full tests actually ran and passed, reaches customers, and a check fails when the customer channel trails.
- Kind: 3
- State: fixed, never shipped
- From: H04-025, L11-037, H07-030

### REL-024: A packaged build was never started before it shipped.
- What was going on: A build can pass every test from source and still fail to start once packaged.
- What the product must do: Every release build is started once in its packaged form and passes a self-test before it is signed or published.
- Kind: 3
- State: fixed, never shipped
- From: L11-033

### REL-025: A failed installer build was published under the new version carrying the old app.
- What was going on: When building the installer failed, the previous build was uploaded under the new number, and the channel then refused that number for the real build.
- What the product must do: A build that fails at any step is never published, and every published version contains exactly the code built for it.
- Kind: 3
- From: H02-023

### REL-026: A new editor was handed the previous app by the installer.
- What was going on: The installer bundled an app built earlier, and the app and installer were published in separate steps that an interruption left on different versions.
- What the product must do: The installer always installs the current app build, and the two become current together only after both uploads succeed.
- Kind: 3
- From: G01-041, L02-065

### REL-027: Retried uploads of one release published a file failing its own checksum.
- What was going on: Two uploads of one version shared a staging file, so one deleted the other's or both interleaved into a file matching neither checksum.
- What the product must do: Concurrent or retried uploads never share staging files, and a published file always matches its recorded checksum.
- Kind: 3
- From: H01-068

### REL-028: An interrupted publish listed a release whose files were missing.
- What was going on: The list went up before the files, a killed publish left a listing with no file, and re-applying the running version erased the rollback target.
- What the product must do: A release becomes visible only once all its files download, an interrupted publish leaves the old or complete new release, and re-applying keeps the rollback target.
- Kind: 3
- From: H06-054, H05-100

### REL-029: Publishing from a fresh machine would erase every other release.
- What was going on: The release list was rebuilt from the publisher's local copy and uploaded, validly signed, over the live one.
- What the product must do: Publishing merges into the live list read from where customers read it, and refuses any upload that drops an existing release unless told to.
- Kind: 3
- From: H04-022

### REL-030: A published build reached no computer because its platform was misspelled.
- What was going on: Computers pick updates by exact platform name, so a build listed as "Windows" or "darwin" was valid, published and silently dropped.
- What the product must do: Publishing refuses before signing any platform name computers do not ask for, and a published build that cannot be offered is reported naming its version.
- Kind: 3
- From: L08-008, L07-057

### REL-031: A release safety check passed a fleet it could not read.
- What was going on: An empty list, the server's answer on any error, read as "no stragglers", and platforms with computers but no published build were not counted.
- What the product must do: An unreadable or empty fleet is a refusal, and computers are counted per platform, including platforms with no build.
- Kind: 3
- From: L06-033

### REL-032: The Mac build lagged the Windows build for weeks unnoticed.
- What was going on: Mac builds can only be made on a Mac, and the reminder was one line at the end of a release.
- What the product must do: When one platform's current build is over 7 days older than another's, the dashboard warns with the steps to catch it up.
- Kind: 3
- From: L04-090

## Trying a build on one computer first

### REL-033: A new build reached every computer at once, with no trial.
- What was going on: Making a build current handed it to the whole fleet within one report, and the trial guarded only some of the ways a build became current.
- What the product must do: Every route leaves a new build staged, never offered automatically, until one computer runs it 30 minutes crash-free; only rollbacks, first builds and withdrawals skip this.
- Kind: 3
- From: L02-055, H07-022, C03-013, L05-010, H06-053

### REL-034: A trial build was blamed for crashes written by older builds.
- What was going on: The crash count was a lifetime total, so weeks-old crashes held a new build back, and test kills and deliberate restarts were counted as its crashes.
- What the product must do: Only real crashes after the build started on that computer count; deliberate restarts never do, and when it cannot be told the build is not passed and says so.
- Kind: 3
- State: still open
- From: L05-030, P12-063

### REL-035: An admin's push of a staged build to one computer was ignored.
- What was going on: Computers were offered only the current build, so a push naming a staged build was refused, making "try it on one computer" impossible.
- What the product must do: Pushing a staged build to one computer offers it to that computer alone until it runs it or the push is withdrawn.
- Kind: 3
- From: M02-078, L05-029

### REL-036: A build was made current that no computer would take.
- What was going on: Rollback and other routes skipped checks for signature, trial, order and server version, so the page said current while every computer refused it.
- What the product must do: Every way of making a build current passes the same checks; an unsigned build needs its version typed, and a refusal says why and leaves current alone.
- Kind: 3
- From: L07-024, H05-011, L03-092, H04-029

### REL-037: Make Current gave no feedback, so it was clicked repeatedly.
- What was going on: The owner: "there is a long delay before it happens, and no visual feedback ... I had to click it multiple times"; refusals appeared elsewhere and automatic promotions went unrecorded.
- What the product must do: Every action button shows busy and disables at once, a refusal appears where clicked, and every promotion, manual or automatic, is recorded.
- Kind: 2
- From: P12-025, L10-054

### REL-038: The builds list must show the newest first and hide old versions.
- What was going on: Owner: newest at the top, "we should never show all the previous versions", builds served here before those offered by the vendor, by product then platform.
- What the product must do: Each product and platform shows its newest build first, older ones only in a rollback picker, one place updates everything, and only truly modified builds are marked so.
- Kind: 2
- State: outcome not found
- From: P12-026, P10-064

### REL-039: Deleting an old build removed it at once instead of keeping it.
- What was going on: Moving a file keeps its modified time, so a build published over 30 days ago was purged in one click, and a failed delete dropped the entry but kept the file.
- What the product must do: A deleted build stays recoverable for 30 days counted from deletion, and a failed delete changes nothing.
- Kind: 3
- From: L02-072, H05-058, L06-027

## Offering an update to a computer

### REL-040: The app offered an "update" that was really an older version.
- What was going on: Any build differing from the running one is offered so a rollback travels like an update, but every offer was labelled "update".
- What the product must do: An offer says "Update" only when newer, "Roll back to X (older)" when older, and "Switch to X" when versions cannot be ranked.
- Kind: 3
- From: C01-017, P02-049, G01-039

### REL-041: Every editor was offered "Roll back" for six weeks.
- What was going on: Computers pushed past the published current build ran newer builds, and the studio kept re-applying the vendor's older current, so each app offered the older one.
- What the product must do: A computer is offered an older build only after an admin chose a rollback, and the dashboard says when its current build is older than computers run.
- Kind: 3
- From: P16-050, M02-077

### REL-042: An Intel Mac was offered an Apple silicon build it could never run.
- What was going on: Builds were matched by operating system only, from some offer paths, so the Mac downloaded, failed to start and rolled back for ever.
- What the product must do: Every offer, from every path, matches the computer's operating system and processor, and when no build exists for it the computer and dashboard say so.
- Kind: 3
- From: H07-027, L02-054, H06-103

### REL-043: Editor builds reached computers before the server they needed.
- What was going on: "Server first" lived only in documents and was broken seven times; a server too old for a build hid the refusal and showed everyone current.
- What the product must do: Each build states the minimum server it needs; a server never offers one it is too old for and shows what to do, measuring "up to date" against the vendor.
- Kind: 3
- From: L02-057, H07-026, L04-065

### REL-044: Pressing update did nothing, and other computers never got the offer.
- What was going on: A click gave no response for minutes, and other signed-in computers were never offered a newly published update.
- What the product must do: Pressing update responds visibly at once, and every signed-in computer is offered a newly published update within minutes.
- Kind: 3
- From: P02-047

### REL-045: A laptop on an early build could never receive a pushed update.
- What was going on: Builds older than remote updating never read the request, so one computer ran a build ten versions old until updated by hand.
- What the product must do: The very first build any editor installs obeys a pushed update, and the dashboard marks any computer too old to be pushed to.
- Kind: 3
- From: P08-003, M02-015

## Installing an update on an editor's computer

### REL-046: An update failed but reported success, leaving the old build running for days.
- What was going on: The install step failed yet exited cleanly, relaunched the old build, and the release reported complete.
- What the product must do: An update is reported done only once the new version is confirmed running; otherwise it says it failed and names the version still running.
- Kind: 3
- From: P04-033, L03-065

### REL-047: After a one-click update no app was running at all.
- What was going on: The new copy started while the old one still held the one-copy-only lock, waited a fixed 20 seconds, gave up, and the old copy exited too.
- What the product must do: After an update exactly one app is running, however long the old copy takes to stop mid-transfer, and a new copy dying on start rolls back.
- Kind: 3
- From: L03-066, C01-098, H03-008

### REL-048: An update that crashed minutes after starting left the editor with no app.
- What was going on: The previous build was deleted a minute after updating, and a macOS login item never restarts a crashed app.
- What the product must do: The previous build is kept until the new one proves healthy, and three crashing starts within 10 minutes restore it, never below the signed minimum, and tell the editor.
- Kind: 3
- From: C03-014, L02-052, H07-023, H08-020

### REL-049: A computer reinstalled the crashing build it had just rolled back from.
- What was going on: The next offer or push handed back the same build, and an admin's own rollback of the server was overridden every ten seconds the same way.
- What the product must do: A build undone on a computer or server is never installed there again automatically, only a newer one, and an admin's push of it is refused in words.
- Kind: 3
- State: fixed, never shipped
- From: L10-042, H06-048, C04-009, L11-030

### REL-050: An update killed midway left nothing to start at sign-in.
- What was going on: For a moment during a self-update no program exists at the expected path, and a kill then leaves nothing to start.
- What the product must do: An update interrupted at any point leaves a program that starts at sign-in, recovered without a person renaming files.
- Kind: 3
- State: outcome not found
- From: H05-094

### REL-051: Crash-loop protection went silent when the app could not write its records.
- What was going on: With the home folder full or locked by antivirus, the app could not record its starts, so a crashing build was never reverted.
- What the product must do: When the app cannot record a start it warns naming where, and never treats that as "nothing known" about crashes.
- Kind: 3
- From: L06-016

### REL-052: Installing an update threw away an upload that had run for hours.
- What was going on: Pushed and unattended updates restarted the app without waiting, so a large upload started again from zero and jobs were killed.
- What the product must do: An update waits for uploads, fetches and jobs to reach a safe point, or they resume where they stopped, unless a person chooses otherwise.
- Kind: 3
- State: still open
- From: M02-013, H07-131

### REL-053: An unattended update gave up for good because a window was open.
- What was going on: An update refused once for an open window, a copy in progress or a failed download was never retried.
- What the product must do: A deferred update retries by itself (about 90 s after an open window, 10 min after a failed download), tells the editor once, and retires once reached or passed.
- Kind: 3
- From: L01-023, H03-011

### REL-054: A computer that could not install an update retried every ten minutes for ever.
- What was going on: Antivirus quarantine, a corrupted download or a full disk failed every attempt, refetching 20 MB each time while the push showed pending.
- What the product must do: Failed attempts back off from 10 minutes to 1 hour to 6 hours and stop after 8 with the reason shown; a push expires after 14 days.
- Kind: 3
- From: L02-053

## Pushing updates and seeing who has what

### REL-055: A computer refusing every update looked like one that had not reported.
- What was going on: Refusals (bad signature, below the floor, insecure address) were forgotten on first read or when the server withheld an offer, so the dashboard showed "pending" for ever.
- What the product must do: A refusing computer shows the refusal and reason until it runs that build or the offer is withdrawn; a withheld offer is told apart from no update.
- Kind: 3
- State: fixed, never shipped
- From: L04-082, L07-017, L06-008, H05-013, L08-082

### REL-056: "Update now" said done and delivered nothing, or stayed pending for ever.
- What was going on: A push cleared on "at or past" the version, which a downgrade always is, while an upgrade push cleared only on an exact match.
- What the product must do: An upgrade push clears at that version or newer; a push to an older build installs it or stays visibly pending, never showing success with nothing delivered.
- Kind: 3
- From: H03-024, L07-047

### REL-057: A push the computer could not take kept it out of fleet jobs.
- What was going on: A push of a build withheld from that computer (wrong processor, withdrawn) stayed "waiting" for 14 days and the computer was treated as mid-update.
- What the product must do: A push that cannot be delivered says so beside the computer with the reason, and the computer keeps taking jobs.
- Kind: 3
- From: L10-020

### REL-058: Fixes were tested against code the computer was not running.
- What was going on: Source, installed app, installer, server and channel drift apart, and a release ended on a prediction, so a fleet that stopped updating was silent for months.
- What the product must do: Every computer and the server show their running build beside the newest; each platform shows who is behind, and one behind 48 hours after reporting is flagged.
- Kind: 3
- From: G01-042, L04-088

### REL-059: A computer on a newer build was called "behind".
- What was going on: Counting anything not on current as behind flags a trial computer or a Mac whose build simply comes later, and an unknown rollout start invents a stall.
- What the product must do: Behind means strictly older for the computer's own platform; being ahead, even of the vendor, is no alarm, and an app on a cached plan says so.
- Kind: 3
- From: L04-089, G01-040

## Rolling back and withdrawing a build

### REL-060: "Roll the fleet back" showed success and delivered nothing.
- What was going on: Computers accepting only newer offers ignored the older build, and recovery was otherwise possible only after a vendor recall, one computer at a time.
- What the product must do: An admin can roll any kind back at any time; every computer installs it, confirmed by their reports, and the rolled-off build is not offered again unasked.
- Kind: 3
- From: H05-010, L06-009, M01-080, L04-145

### REL-061: A rollback downgraded computers that were never on the bad build.
- What was going on: Re-pointing current also offered the older build to computers on hotfixes or individually pushed newer builds.
- What the product must do: Before a rollback, the admin is shown which computers run something newer than the target other than the build being rolled off.
- Kind: 3
- From: L07-025

### REL-062: A withdrawn build kept being offered and stayed installed.
- What was going on: Withdrawal was ignored under some update policies, offers followed list order not version, and withdrawing current could leave nothing current or be undone by a later publish.
- What the product must do: One current build per kind and platform; a signed withdrawal reaches every computer under every policy, names a replacement, cannot be undone by publishing, and moves computers back.
- Kind: 3
- From: L02-056, H07-025, H04-023

### REL-063: Rolling the server back made newer apps' reports rejected for ever.
- What was going on: One unknown word or mistyped field made a server reject a whole report every 30 seconds, and an app kept sending new words after a server rollback.
- What the product must do: An app re-learns the server's version from every reply and sends new words only to servers that accept them; an unreadable field never costs the rest.
- Kind: 3
- From: H06-049, L08-031, L09-031, H05-034, C03-069

## The server updating itself

### REL-064: The owner: updates reach the fleet and the server from one admin click.
- What was going on: Owner: "make the dashboard self-update over the air, with the NAS UI click kept only for runtime changes", and push to computers without their editors clicking.
- What the product must do: An admin installs a release on the server and every computer from the dashboard; only newer builds are offered as updates, and the NAS screen is for runtime changes only.
- Kind: 2
- From: P06-033, C02-039

### REL-065: Each part of the dashboard should update on its own.
- What was going on: Owner: "can we split all the different modules of the dashboard out so they can be updated separately ... only changes that affect certain modules".
- What the product must do: A change to one part (editor, b-roll, music, downloader) is tested and shipped without retesting or redeploying the unrelated parts.
- Kind: 2
- State: still open
- From: P14-007

### REL-066: A server update that could not serve pages was never undone.
- What was going on: Only a crash on start counted, an update that never started was skipped uncounted, and a refusal for a missing setting counted as a failed boot.
- What the product must do: An update that started but does not pass its health check within ten minutes is reverted with its real reason shown; a refusal names its cause instead.
- Kind: 3
- State: fixed, never shipped
- From: L11-031, L07-036, L06-062

### REL-067: An automatic revert could roll back to code that cannot open the database.
- What was going on: The failed version had already upgraded the database, so the older code refused to start on every boot.
- What the product must do: A revert never picks code older than the database; it keeps the new code and says why, and when it cannot tell, it still reverts.
- Kind: 3
- From: L07-037

### REL-068: A server killed mid-update refused every later update and rollback.
- What was going on: Power loss or a kill during the restart left "update in progress" recorded, and only a shell could clear it.
- What the product must do: An "in progress" left by a dead process becomes "failed, interrupted" on start, and update and rollback work again from the page.
- Kind: 3
- From: H05-075, L06-054, L01-024

### REL-069: On a full data disk an applied update never started and status failed.
- What was going on: Reading the update status also wrote a correction, and on a full or read-only disk that failure stopped the restart.
- What the product must do: With a full or read-only data disk, update status still answers and an applied update still restarts into the new code.
- Kind: 3
- From: L07-058

### REL-070: A stale server froze every app update where nobody clicks.
- What was going on: App updates need a minimum server version, and the server was the one part with no unattended update.
- What the product must do: On a site set to follow the vendor, the server updates itself after the waiting period, rolls back if it will not start, and never retries a failed build unattended.
- Kind: 3
- From: L05-016

### REL-071: Update checks failed silently for weeks.
- What was going on: Blocked outbound access or a moved release feed made every daily check fail, shown on one admin page only, so it looked like nothing was released.
- What the product must do: With no successful update check for 7 days the home page shows a banner, and a site never checked counts as stale.
- Kind: 3
- From: L02-061

## Customer sites and the vendor's release feed

### REL-072: Customers get one exact build after it ran on the studio first.
- What was going on: Customers followed a moving label, so whatever was published last reached them untested; the owner ruled "customers pinned by digest, with vendor soak".
- What the product must do: A customer site updates only to the exact build named for it, refused until that same build ran 24 hours on the studio.
- Kind: 2
- State: fixed, never shipped
- From: H08-013, L11-036

### REL-073: A customer on a fixed server build was given update steps that changed nothing.
- What was going on: The banner said to press the NAS app's update button, which fetches the same fixed build again.
- What the product must do: Every update notice for a server fixed to one build names the exact new build and the steps that actually change it.
- Kind: 3
- State: fixed, never shipped
- From: L11-041

### REL-074: No customer ever receives the product's source code.
- What was going on: The owner ruled that no customer gets source.
- What the product must do: No customer download, install or update contains the product's readable source, and no customer-facing step fetches it.
- Kind: 2
- From: H08-004

### REL-075: Customers were told to make their own signing key, cutting off vendor updates.
- What was going on: A customer following the guide would reject every vendor build, and every customer server nagged to back up a key it never holds.
- What the product must do: Customer installs trust the vendor's key and feed out of the box, a malformed key is refused at install, and only the vendor sees key-backup prompts.
- Kind: 3
- From: L10-093, H07-115

### REL-076: Customers fed by the vendor had no installer to onboard editors.
- What was going on: The installer was published only from the studio's own machine, so a customer's installer page was empty.
- What the product must do: Every customer receives the editor installer for each platform through the same channel as the app, and an empty installer page speaks to the customer.
- Kind: 3
- From: H04-027

### REL-077: The update address written into every install can never move.
- What was going on: Every install records where it fetches updates, so an address the vendor does not control breaks every site when it moves.
- What the product must do: Every install fetches updates from a vendor-owned address that can be redirected without touching any installed site.
- Kind: 3
- State: outcome not found
- From: H08-016

### REL-078: A customer site could never download the music model.
- What was going on: The allowed download source was fixed to the vendor's host, and a secure source could redirect to an insecure one.
- What the product must do: Every download follows the site's own release source, and never follows a redirect from a secure address to an insecure one.
- Kind: 3
- From: H06-122

### REL-079: A release feed address with a query string quietly delivered no builds.
- What was going on: The signature address was made by appending to the whole address, so a pre-signed or token address pointed at a file that does not exist.
- What the product must do: A feed address with a query string finds its signature, and a feed that keeps failing is shown to the admin with the real address tried.
- Kind: 3
- From: L06-055, H05-076

## Sealed

### REL-S01: Install and release scripts died on harmless error-stream text.
- What was going on: With stop-on-error, a native command's redirected error output becomes fatal, and a script with no explicit exit returns the last command's code.
- What the product must do: Scripts judge each external command by its exit code only and always exit with their own explicit status.
- Kind: 1b
- Tool: Windows PowerShell 5.1
- From: C01-008

### REL-S02: An interrupted release upload was skipped as already published, for ever.
- What was going on: An interrupted upload keeps its name and size but stays unfinished, so skipping by name and size never re-sent it.
- What the product must do: A release file counts as published only when the host says it finished and its checksum matches; any doubt uploads it again.
- Kind: 1b
- Tool: GitHub Releases
- From: L09-055

### REL-S03: A failed re-upload left the update feed without its index file.
- What was going on: Replacing a release file deletes the old one before uploading, so two server errors left the feed without its index for about a minute.
- What the product must do: After every publish the feed's file list is checked, and a missing index is restored before success is reported.
- Kind: 1b
- Tool: GitHub Releases (gh release upload --clobber)
- From: M02-080

### REL-S04: Hosted release files redirect to another host and cannot sit in folders.
- What was going on: A download answers with a redirect to a different host, and a release's files are one flat list whose names cannot contain a slash.
- What the product must do: Downloads follow secure redirects with no credentials sent and verify every file, and published file names are unique without folders.
- Kind: 1b
- Tool: GitHub Releases
- From: C02-028

### REL-S05: A pre-signed feed link could not reach its signature file.
- What was going on: A pre-signed link is valid for one exact file, so changing its name to reach the signature file is refused and builds stopped arriving.
- What the product must do: The signature file's address can be set apart from the feed's, and when it cannot be fetched the admin page names the likely cause.
- Kind: 1b
- Tool: pre-signed object-storage links (S3 SigV4) for the release feed
- From: L07-045

### REL-S06: Build signing was silently skipped while believed on.
- What was going on: A step's own variables are invisible to that step's run condition, so the certificate step was always skipped and builds shipped unsigned.
- What the product must do: Each build states whether it was signed, and a build expected to be signed that is not is refused for publishing.
- Kind: 1b
- Tool: GitHub Actions (a step's own env is not visible to its own `if`)
- From: H03-039

### REL-S07: The build service reported a run green when its test job was skipped.
- What was going on: A skipped job does not fail its run, and a protected release environment that does not exist yet is created automatically with no reviewer.
- What the product must do: Release checks confirm the test job ran and passed on the commit, and that the release environment exists with a required reviewer.
- Kind: 1b
- Tool: GitHub Actions (skipped jobs, auto-created environments)
- From: L11-038

### REL-S08: Building the Android app wrapper failed with unhelpful errors.
- What was going on: The builder demands a file from a retired Android SDK package, and the resource linker rejects a package name part starting with an underscore.
- What the product must do: The Android app builds from a clean machine in one step, with a package name every Android tool accepts.
- Kind: 1b
- Tool: Bubblewrap (TWA builder) and aapt2
- From: C03-041

## Removed

