# Releases and updates: what real use taught

81 lessons. Each is one rule the product can be tested against: what a person saw (the heading), why it happened, and what the product must do. Kinds: *given* is a fact about something the studio has whatever is built; *ruling* is the owner's decision; *situation* is something the product must survive.

## Installing an update on an editor's computer

### APP-067: After an update the app was gone until someone restarted it by hand.
- Why: The new version started while the old one still held the run-once lock and quit, and "update complete" was reported without checking the new app stayed up.
- Must: After an update exactly one copy runs; success is reported only if the new app is still running seconds later, and otherwise the old one keeps running.
- Kind: situation

### APP-068: A new build that died on start was never rolled back.
- Why: Deaths before the app finished starting were not counted as failed starts, so sync stopped until someone restored the old build by hand on each machine.
- Must: A second failed start or crash within ten minutes of a new build's first start restores the previous build by itself, and syncing resumes with no one touching the machine.
- Kind: situation

### APP-069: An update interrupted mid-swap left the computer with no app at all.
- Why: A power cut, reboot or antivirus quarantine between moving the old program aside and placing the new one left nothing to start.
- Must: An interrupted self-update restores a runnable app without a person, and recovery never overwrites an app that is present.
- Kind: situation

### REL-046: An update failed but reported success, leaving the old build running for days.
- Why: The install step failed yet exited cleanly, relaunched the old build, and the release reported complete.
- Must: An update is reported done only once the new version is confirmed running; otherwise it says it failed and names the version still running.
- Kind: situation

### REL-047: After a one-click update no app was running at all.
- Why: The new copy started while the old one still held the one-copy-only lock, waited a fixed 20 seconds, gave up, and the old copy exited too.
- Must: After an update exactly one app is running, however long the old copy takes to stop mid-transfer, and a new copy dying on start rolls back.
- Kind: situation

### REL-048: An update that crashed minutes after starting left the editor with no app.
- Why: The previous build was deleted a minute after updating, and a macOS login item never restarts a crashed app.
- Must: The previous build stays until the new one proves healthy; a second failed start or crash within 10 minutes restores it, never below the signed minimum, telling the editor.
- Kind: situation

### REL-049: A computer reinstalled the crashing build it had just rolled back from.
- Why: The next offer or push handed back the same build, and an admin's own rollback of the server was overridden every ten seconds the same way.
- Must: A build undone on a computer or server is never installed there again automatically, only a newer one, and an admin's push of it is refused in words.
- Kind: situation

### REL-050: An update killed midway left nothing to start at sign-in.
- Why: For a moment during a self-update no program exists at the expected path, and a kill then leaves nothing to start.
- Must: An update interrupted at any point leaves a program that starts at sign-in, recovered without a person renaming files.
- Kind: situation

### REL-051: Crash-loop protection went silent when the app could not write its records.
- Why: With the home folder full or locked by antivirus, the app could not record its starts, so a crashing build was never reverted.
- Must: When the app cannot record a start it warns naming where, and never treats that as "nothing known" about crashes.
- Kind: situation

### REL-052: Installing an update threw away an upload that had run for hours.
- Why: Pushed and unattended updates restarted the app without waiting, so a large upload started again from zero and jobs were killed.
- Must: An update waits for uploads, fetches and jobs to reach a safe point, or they resume where they stopped, unless a person chooses otherwise.
- Kind: situation

### REL-053: An unattended update gave up for good because a window was open.
- Why: An update refused once for an open window, a copy in progress or a failed download was never retried.
- Must: A deferred update retries by itself (about 90 s after an open window, 10 min after a failed download), tells the editor once, and retires once reached or passed.
- Kind: situation

### REL-054: A computer that could not install an update retried every ten minutes for ever.
- Why: Antivirus quarantine, a corrupted download or a full disk failed every attempt, refetching 20 MB each time while the push showed pending.
- Must: Failed attempts back off from 10 minutes to 1 hour to 6 hours and stop after 8 with the reason shown; a push expires after 14 days.
- Kind: situation

## Facts about Windows, macOS and the NAS that bite an update

### REL-001: A new Mac program copied over the old file was killed at launch.
- Why: macOS caches a program's code signature per file, so overwriting a signed program in place fails the check ("Invalid Page") and the system kills it at start.
- Must: Every install or update on macOS writes the new program to a new file and renames it over the old one, never overwriting in place.
- Kind: given

### REL-002: On a Mac, the app lost its disk permission after an update, or never started.
- Why: macOS ties grants such as Full Disk Access to the code signature; an ad-hoc-signed app loses them on update, and a refused launch is silent.
- Must: An update on macOS keeps the app's permissions and its ability to start, and a refused launch is visible to someone.
- Kind: given

### REL-003: Windows antivirus held the installed program, and the update still said complete.
- Why: Windows antivirus can hold an installed program file for over ten seconds, so replacing it fails and the old version starts again.
- Must: An update that cannot replace the program reports failure, says what holds the file, and is never counted as installed.
- Kind: given

### REL-004: A file someone has open over the share cannot be replaced.
- Why: An editor running the installer straight off the NAS share kept it open, so publishing a new one failed, yet the release said it was complete.
- Must: When publishing cannot replace a file on the share, the release fails loudly and names the file.
- Kind: given

### REL-005: A script written on Windows failed on the Mac and took the NAS dashboard down.
- Why: Windows line endings make shell scripts fail on macOS and the NAS ("Illegal option -", "bad interpreter"), many text tools hide them, and Windows drops the executable mark.
- Must: Every script that runs on a Mac or the NAS is checked byte by byte for Windows line endings and executable permission before any package is assembled.
- Kind: given

### REL-006: A stock Windows install refuses to run script files directly.
- Why: Running a script by name failed with "running scripts is disabled on this system", for release steps and an install script alike.
- Must: Nothing a person is told to run requires them to change Windows' script policy first.
- Kind: given

### REL-007: Windows warns every editor who installs an unsigned program.
- Why: Without a paid code-signing certificate every fresh Windows install shows a SmartScreen warning, and the setup program a new editor runs first was never set up for signing.
- Must: Every Windows program a person runs, first-run installer included, ships code-signed, and a release states which of its files are unsigned.
- Kind: given

## Version numbers

### REL-010: The beta keeps a pre-release version number until the paid release.
- Why: The owner ruled the launch is a free open beta with only minor version bumps; the first whole-number version is his statement for the paid launch.
- Must: Every beta build carries a pre-release version number, and nothing raises it to the first whole-number version without the owner's explicit launch decision.
- Kind: ruling

### REL-008: Version 1.10 was ranked below 1.9.
- Why: Comparing versions as text puts 1.10 below 1.9 and 1.9.9 above 1.9.65, which stops prompts or refuses valid updates.
- Must: Every version comparison compares each dotted part as a number.
- Kind: situation

### REL-009: A computer on a build with a version suffix never finished a pushed update.
- Why: A version with a suffix marking local changes did not parse as a number, so a push to a computer already on it was resent every report for ever.
- Must: A suffixed build counts as its numeric version for completing a push, but never as newer than the clean build of that version.
- Kind: situation

### YTD-096: A version floor written "2026.8.5" refused every computer in the studio.
- Why: One side compared versions as text and the other as numbers, so the server refused everyone while each computer believed itself current.
- Must: Versions are compared numerically by one rule everywhere, and a floor that does not parse is refused when it is set.
- Kind: situation

## Signing and trust

### REL-011: The release signing key never leaves the owner's offline machine.
- Why: The owner ruled builds may be made in the cloud but signed only on his machine, since a leaked key reaches code every editor's computer runs at logon.
- Must: Builds may be produced anywhere, but signing happens only on the offline machine holding the key, after verifying the build there.
- Kind: ruling

### REL-012: The key the whole fleet trusts sat unprotected, with no backup.
- Why: The owner ruled the key is a passphrase-protected file with two offline backups in different places for the beta, and a hardware token before the paid release.
- Must: Signing asks for the passphrase every time, the key restores from either backup, missing backups are reminded each release, and a written plan exists for a stolen key.
- Kind: ruling

### REL-013: A signing-key change would have stranded every computer on its current build.
- Why: Each computer trusts only the keys inside the build it already runs, so a build signed only with a new key is refused everywhere.
- Must: A key change first ships a build signed by the old key that trusts both; publishing a build no installed computer trusts is impossible.
- Kind: situation

### REL-014: Anyone posing as the dashboard could install any program on every computer.
- Why: An update and its checksum arrived in one unauthenticated reply, and one desktop app installed whatever program sat in a shared folder beside a hash.
- Must: Every app the product installs refuses any update whose signature does not verify against a key built into it, whatever the update's source.
- Kind: situation

### REL-015: The app installed a genuine signed installer over itself as an update.
- Why: Updates were accepted on signature alone, so a signed installer replaced the app and launched at every logon.
- Must: An update is installed only if its signed record names this app and this platform.
- Kind: situation

### REL-016: A replayed old signed build could roll a computer back past safety fixes.
- Why: Every signed release carried a minimum version of zero, so any genuine old build could be installed again.
- Must: A release that fixes something a downgrade would bring back raises the minimum version, and computers refuse anything below it.
- Kind: situation

### REL-017: One typo in a minimum version could freeze every computer's updates.
- Why: A record whose minimum version exceeded its own version raised each computer's floor on mere receipt, refusing that build, its corrected republish and any rollback.
- Must: Such a release is refused at signing, publishing and on every computer, and a refused offer never changes any computer's floor.
- Kind: situation

### REL-018: An old or wrongly dated release list could lock computers out.
- Why: Nothing checked a release list was fresh, so an old one could be replayed; once checked, a list stamped hours ahead by a fast clock blocked every later one.
- Must: Computers refuse a release list older than one already seen, and list dates never go backwards because a publisher's wrong clock is caught and named.
- Kind: situation

### REL-019: New fields in an update record made older apps refuse every update for ever.
- Why: Older builds fail the whole signature on fields they do not know, refuse silently, and need a reinstall at each desk.
- Must: Update records stay verifiable by every build still reporting in; release notes, shown as one line in the offer, never change what older builds verify.
- Kind: situation

## Making and publishing a release

### REL-020: A release should be one short command.
- Why: The owner, facing several manual steps: "there used to be one command which did all of this ... rebuild, pushed it to dashboard, pushed to tray utility".
- Must: One command builds and publishes a release, refusing before anything moves if a check fails.
- Kind: ruling

### REL-021: A release failed twenty minutes in, or halfway, for something known at the start.
- Why: An unsigned build or a byte mismatch was refused only after deploys, tests and packaging, sometimes after the release was already tagged and approved.
- Must: Every refusal a release can meet is checked before its first long or irreversible step.
- Kind: situation

### REL-022: One version number meant two different programs.
- Why: Two builds of one commit differ in bytes, and republishing a version with new bytes swapped the served file under its checksum, so computers failed to update.
- Must: A version always means one set of bytes everywhere; republishing identical bytes changes nothing, different bytes are refused as a conflict, and the studio tests exactly what customers receive.
- Kind: situation

### REL-023: An untested build from any branch could reach customers.
- Why: Publishing took the newest green build regardless of branch or version, one route skipped the tests entirely, and the customer channel lagged the studio by weeks.
- Must: Only an unmodified main-line build above every published version, whose full tests actually ran and passed, reaches customers, and a check fails when the customer channel trails.
- Kind: situation

### REL-024: A packaged build was never started before it shipped.
- Why: A build can pass every test from source and still fail to start once packaged.
- Must: Every release build is started once in its packaged form and passes a self-test before it is signed or published.
- Kind: situation

### REL-025: A failed installer build was published under the new version carrying the old app.
- Why: When building the installer failed, the previous build was uploaded under the new number, and the channel then refused that number for the real build.
- Must: A build that fails at any step is never published, and every published version contains exactly the code built for it.
- Kind: situation

### REL-026: A new editor was handed the previous app by the installer.
- Why: The installer bundled an app built earlier, and the app and installer were published in separate steps that an interruption left on different versions.
- Must: The installer always installs the current app build, and the two become current together only after both uploads succeed.
- Kind: situation

### REL-027: Retried uploads of one release published a file failing its own checksum.
- Why: Two uploads of one version shared a staging file, so one deleted the other's or both interleaved into a file matching neither checksum.
- Must: Concurrent or retried uploads never share staging files, and a published file always matches its recorded checksum.
- Kind: situation

### REL-028: An interrupted publish listed a release whose files were missing.
- Why: The list went up before the files, a killed publish left a listing with no file, and re-applying the running version erased the rollback target.
- Must: A release becomes visible only once all its files download, an interrupted publish leaves the old or complete new release, and re-applying keeps the rollback target.
- Kind: situation

### REL-029: Publishing from a fresh machine would erase every other release.
- Why: The release list was rebuilt from the publisher's local copy and uploaded, validly signed, over the live one.
- Must: Publishing merges into the live list read from where customers read it, and refuses any upload that drops an existing release unless told to.
- Kind: situation

### REL-030: A published build reached no computer because its platform was misspelled.
- Why: Computers pick updates by exact platform name, so a build listed as "Windows" or "darwin" was valid, published and silently dropped.
- Must: Publishing refuses before signing any platform name computers do not ask for, and a published build that cannot be offered is reported naming its version.
- Kind: situation

### REL-031: A release safety check passed a fleet it could not read.
- Why: An empty list, the server's answer on any error, read as "no stragglers", and platforms with computers but no published build were not counted.
- Must: An unreadable or empty fleet is a refusal, and computers are counted per platform, including platforms with no build.
- Kind: situation

### REL-032: The Mac build lagged the Windows build for weeks unnoticed.
- Why: Mac builds can only be made on a Mac, and the reminder was one line at the end of a release.
- Must: When one platform's current build is over 7 days older than another's, the dashboard warns with the steps to catch it up.
- Kind: situation

## Trying a build on one computer first

### REL-037: Make Current gave no feedback, so it was clicked repeatedly.
- Why: The owner: "there is a long delay before it happens, and no visual feedback ... I had to click it multiple times"; refusals appeared elsewhere and automatic promotions went unrecorded.
- Must: Every action button shows busy and disables at once, a refusal appears where clicked, and every promotion, manual or automatic, is recorded.
- Kind: ruling

### REL-038: The builds list must show the newest first and hide old versions.
- Why: Owner: newest at the top, "we should never show all the previous versions", builds served here before those offered by the vendor, by product then platform.
- Must: Each product and platform shows its newest build first, older ones only in a rollback picker, one place updates everything, and only truly modified builds are marked so.
- Kind: ruling

### REL-033: A new build reached every computer at once, with no trial.
- Why: Making a build current handed it to the whole fleet within one report, and the trial guarded only some of the ways a build became current.
- Must: Every route leaves a new build staged, never offered automatically, until one computer runs it 30 minutes crash-free; only rollbacks, first builds and withdrawals skip this.
- Kind: situation

### REL-034: A trial build was blamed for crashes written by older builds.
- Why: The crash count was a lifetime total, so weeks-old crashes held a new build back, and test kills and deliberate restarts were counted as its crashes.
- Must: Only real crashes after the build started on that computer count; deliberate restarts never do, and when it cannot be told the build is not passed and says so.
- Kind: situation

### REL-035: An admin's push of a staged build to one computer was ignored.
- Why: Computers were offered only the current build, so a push naming a staged build was refused, making "try it on one computer" impossible.
- Must: Pushing a staged build to one computer offers it to that computer alone until it runs it or the push is withdrawn.
- Kind: situation

### REL-036: A build was made current that no computer would take.
- Why: Rollback and other routes skipped checks for signature, trial, order and server version, so the page said current while every computer refused it.
- Must: Every way of making a build current passes the same checks; an unsigned build needs its version typed, and a refusal says why and leaves current alone.
- Kind: situation

### REL-039: Deleting an old build removed it at once instead of keeping it.
- Why: Moving a file keeps its modified time, so a build published over 30 days ago was purged in one click, and a failed delete dropped the entry but kept the file.
- Must: A deleted build stays recoverable for 30 days counted from deletion, and a failed delete changes nothing.
- Kind: situation

## Offering an update to a computer

### REL-040: The app offered an "update" that was really an older version.
- Why: Any build differing from the running one is offered so a rollback travels like an update, but every offer was labelled "update".
- Must: An offer says "Update" only when newer, "Roll back to X (older)" when older, and "Switch to X" when versions cannot be ranked.
- Kind: situation

### REL-041: Every editor was offered "Roll back" for six weeks.
- Why: Computers pushed past the published current build ran newer builds, and the studio kept re-applying the vendor's older current, so each app offered the older one.
- Must: A computer is offered an older build only after an admin chose a rollback, and the dashboard says when its current build is older than computers run.
- Kind: situation

### REL-042: An Intel Mac was offered an Apple silicon build it could never run.
- Why: Builds were matched by operating system only, from some offer paths, so the Mac downloaded, failed to start and rolled back for ever.
- Must: Every offer, from every path, matches the computer's operating system and processor, and when no build exists for it the computer and dashboard say so.
- Kind: situation

### REL-043: Editor builds reached computers before the server they needed.
- Why: "Server first" lived only in documents and was broken seven times; a server too old for a build hid the refusal and showed everyone current.
- Must: Each build states the minimum server it needs; a server never offers one it is too old for and shows what to do, measuring "up to date" against the vendor.
- Kind: situation

### REL-044: Pressing update did nothing, and other computers never got the offer.
- Why: A click gave no response for minutes, and other signed-in computers were never offered a newly published update.
- Must: Pressing update responds visibly at once, and every signed-in computer is offered a newly current update within minutes.
- Kind: situation

### REL-045: A laptop on an early build could never receive a pushed update.
- Why: Builds older than remote updating never read the request, so one computer ran a build ten versions old until updated by hand.
- Must: The very first build any editor installs obeys a pushed update, and the dashboard marks any computer too old to be pushed to.
- Kind: situation

## Pushing updates and seeing who has what

### REL-055: A computer refusing every update looked like one that had not reported.
- Why: Refusals (bad signature, below the floor, insecure address) were forgotten on first read or when the server withheld an offer, so the dashboard showed "pending" for ever.
- Must: A refusing computer shows the refusal and reason until it runs that build or the offer is withdrawn; a withheld offer is told apart from no update.
- Kind: situation

### REL-056: "Update now" said done and delivered nothing, or stayed pending for ever.
- Why: A push cleared on "at or past" the version, which a downgrade always is, while an upgrade push cleared only on an exact match.
- Must: An upgrade push clears at that version or newer; a push to an older build installs it or stays visibly pending, never showing success with nothing delivered.
- Kind: situation

### REL-058: Fixes were tested against code the computer was not running.
- Why: Source, installed app, installer, server and channel drift apart, and a release ended on a prediction, so a fleet that stopped updating was silent for months.
- Must: Every computer and the server show their running build beside the newest; each platform shows who is behind, and one behind 48 hours after reporting is flagged.
- Kind: situation

### REL-059: A computer on a newer build was called "behind".
- Why: Counting anything not on current as behind flags a trial computer or a Mac whose build simply comes later, and an unknown rollout start invents a stall.
- Must: Behind means strictly older for the computer's own platform; being ahead, even of the vendor, is no alarm, and an app on a cached plan says so.
- Kind: situation

See also, filed under another capability:

- JOB-006 (Work shared out across the computers): A computer that could not take a pushed update silently dropped out of jobs.

## Rolling back and withdrawing a build

### REL-060: "Roll the fleet back" showed success and delivered nothing.
- Why: Computers accepting only newer offers ignored the older build, and recovery was otherwise possible only after a vendor recall, one computer at a time.
- Must: An admin can roll any kind back at any time; every computer installs it, confirmed by their reports, and the rolled-off build is not offered again unasked.
- Kind: situation

### REL-061: A rollback downgraded computers that were never on the bad build.
- Why: Re-pointing current also offered the older build to computers on hotfixes or individually pushed newer builds.
- Must: Before a rollback, the admin is shown which computers run something newer than the target other than the build being rolled off.
- Kind: situation

### REL-062: A withdrawn build kept being offered and stayed installed.
- Why: Withdrawal was ignored under some update policies, offers followed list order not version, and withdrawing current could leave nothing current or be undone by a later publish.
- Must: One current build per kind and platform; a signed withdrawal reaches every computer under every policy, names a replacement, cannot be undone by publishing, and moves computers back.
- Kind: situation

### REL-063: Rolling the server back made newer apps' reports rejected for ever.
- Why: One unknown word or mistyped field made a server reject a whole report every 30 seconds, and an app kept sending new words after a server rollback.
- Must: An app re-learns the server's version from every reply and sends new words only to servers that accept them; an unreadable field never costs the rest.
- Kind: situation

## The server updating itself

### REL-064: The owner: updates reach the fleet and the server from one admin click.
- Why: Owner: "make the dashboard self-update over the air, with the NAS UI click kept only for runtime changes", and push to computers without their editors clicking.
- Must: An admin installs a release on the server and every computer from the dashboard; only newer builds are offered as updates, and the NAS screen is for runtime changes only.
- Kind: ruling

### REL-065: Each part of the dashboard should update on its own.
- Why: Owner: "can we split all the different modules of the dashboard out so they can be updated separately ... only changes that affect certain modules".
- Must: A change to one part (editor, b-roll, music, downloader) is tested and shipped without retesting or redeploying the unrelated parts.
- Kind: ruling

### REL-066: A server update that could not serve pages was never undone.
- Why: Only a crash on start counted, an update that never started was skipped uncounted, and a refusal for a missing setting counted as a failed boot.
- Must: An update that started but does not pass its health check within ten minutes is reverted with its real reason shown; a refusal names its cause instead.
- Kind: situation

### REL-067: An automatic revert could roll back to code that cannot open the database.
- Why: The failed version had already upgraded the database, so the older code refused to start on every boot.
- Must: A revert never picks code older than the database; it keeps the new code and says why, and when it cannot tell, it still reverts.
- Kind: situation

### REL-068: A server killed mid-update refused every later update and rollback.
- Why: Power loss or a kill during the restart left "update in progress" recorded, and only a shell could clear it.
- Must: An "in progress" left by a dead process becomes "failed, interrupted" on start, and update and rollback work again from the page.
- Kind: situation

### REL-069: On a full data disk an applied update never started and status failed.
- Why: Reading the update status also wrote a correction, and on a full or read-only disk that failure stopped the restart.
- Must: With a full or read-only data disk, update status still answers and an applied update still restarts into the new code.
- Kind: situation

### REL-070: A stale server froze every app update where nobody clicks.
- Why: App updates need a minimum server version, and the server was the one part with no unattended update.
- Must: On a site set to follow the vendor, the server updates itself after the waiting period, rolls back if it will not start, and never retries a failed build unattended.
- Kind: situation

### REL-071: Update checks failed silently for weeks.
- Why: Blocked outbound access or a moved release feed made every daily check fail, shown on one admin page only, so it looked like nothing was released.
- Must: With no successful update check for 7 days the home page shows a banner, and a site never checked counts as stale.
- Kind: situation

## Customer sites and the vendor's release feed

### REL-072: Customers get one exact build after it ran on the studio first.
- Why: Customers followed a moving label, so whatever was published last reached them untested; the owner ruled "customers pinned by digest, with vendor soak".
- Must: A customer site updates only to the exact build named for it, refused until that same build ran 24 hours on the studio and a second person approved it.
- Kind: ruling

### REL-073: A customer on a fixed server build was given update steps that changed nothing.
- Why: The banner said to press the NAS app's update button, which fetches the same fixed build again.
- Must: Every update notice for a server fixed to one build names the exact new build and the steps that actually change it.
- Kind: situation

### REL-075: Customers were told to make their own signing key, cutting off vendor updates.
- Why: A customer following the guide would reject every vendor build, and every customer server nagged to back up a key it never holds.
- Must: Customer installs trust the vendor's key and feed out of the box, a malformed key is refused at install, and only the vendor sees key-backup prompts.
- Kind: situation

### REL-076: Customers fed by the vendor had no installer to onboard editors.
- Why: The installer was published only from the studio's own machine, so a customer's installer page was empty.
- Must: Every customer receives the editor installer for each platform through the same channel as the app, and an empty installer page speaks to the customer.
- Kind: situation

### REL-077: The update address written into every install can never move.
- Why: Every install records where it fetches updates, so an address the vendor does not control breaks every site when it moves.
- Must: Every install fetches updates from a vendor-owned address that can be redirected without touching any installed site.
- Kind: situation

### REL-078: A customer site could never download the music model.
- Why: The allowed download source was fixed to the vendor's host, and a secure source could redirect to an insecure one.
- Must: Every download follows the site's own release source, and never follows a redirect from a secure address to an insecure one.
- Kind: situation

### REL-079: A release feed address with a query string quietly delivered no builds.
- Why: The signature address was made by appending to the whole address, so a pre-signed or token address pointed at a file that does not exist.
- Must: A feed address with a query string finds its signature, and a feed that keeps failing is shown to the admin with the real address tried.
- Kind: situation

See also, filed under another capability:

- ACC-064 (Accounts, privacy and the legal paperwork): No customer receives the product's source code.
