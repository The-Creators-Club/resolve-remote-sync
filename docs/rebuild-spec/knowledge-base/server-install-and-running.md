# The server: installing it and keeping it running: what real use taught

126 lessons. Each is one rule the product can be tested against: what a person saw (the heading), why it happened, and what the product must do. Kinds: *given* is a fact about something the studio has whatever is built; *ruling* is the owner's decision; *situation* is something the product must survive.

## Installing on a NAS

### SRV-001: A fresh NAS downloaded from some hosts at about 28 kB/s.
- Why: The studio NAS took about 25 minutes for a 42 MB file a workstation fetched in 24 s, overrunning a 10-minute install step.
- Must: Installing never depends on the NAS downloading large files; they can be fetched elsewhere, checksum-verified and pushed over the LAN, a failed checksum leaving nothing.
- Kind: given

### SRV-002: TrueNAS 26 drops the management interface older TrueNAS versions answer.
- Why: TrueNAS 26 removes its older request-response web interface and keeps only its live-connection one; 25.04 and 25.10 answer both.
- Must: Installing and managing works on TrueNAS 25 and 26 with no setting, and a NAS version the product cannot drive is refused with a named reason.
- Kind: given

### SRV-003: TrueNAS accepted an app install that failed later, and install said success.
- Why: On TrueNAS a successful answer to "create this app" only means the job was accepted; it can still fail, for example when its address no longer exists.
- Must: Installation reports success only when the NAS's install job finished successfully and the app is actually running.
- Kind: given

### SRV-004: On TrueNAS 25.10 a filtered app query returned nothing for an installed app.
- Why: A re-run of the install then tried to create the app again and advised deleting the healthy one.
- Must: The product never concludes a NAS app is absent from a filtered query alone, and never advises deleting a running app.
- Kind: given

### SRV-005: The health check called the editors group empty on a healthy TrueNAS.
- Why: TrueNAS user records list group membership by the group's internal database id, not its unix group number, so comparing unix numbers never matches.
- Must: Group membership checks on TrueNAS pass on a correctly set-up NAS and fail only when a member is really missing.
- Kind: given

### SRV-006: A TrueNAS API key was refused when presented as the admin.
- Why: On TrueNAS 25.04 and later an API key belongs to one account and acts with that account's rights, so sign-in must name that account.
- Must: The server signs in to the NAS as the key's own account, and a refused sign-in names the account that was presented.
- Kind: given

### SRV-007: Synology and TrueNAS number users differently, so a fixed account number fails.
- Why: Synology numbers local users from 1026 and TrueNAS gives 3000 to its first, so the server ran as a nonexistent user and could write nothing.
- Must: Install uses the real NAS account the server runs as, and every start warns, naming account and owner, when that account does not own its data folder.
- Kind: given

### SRV-010: Synology caps transfer chunks at 64 KiB and breaks on permission changes in shares.
- Why: Synology's file-transfer server limits chunks to 64 KiB, and changing permissions under a shared folder breaks its sharing rules.
- Must: On a Synology, transfers respect the NAS's own limits and nothing changes permissions inside a shared folder.
- Kind: given

### SRV-011: Windows could create files on the NAS share but not list or read them.
- Why: Windows' built-in network-file client checks a file's "other" permission bits itself; with them at none, reads and listings fail "Access is denied" whatever the NAS allows.
- Must: Setup verifies that an editor's computer can list, read, write and delete in the shared tree, and names which of the four failed.
- Kind: given

### SRV-012: Resolve collaborators were shown an internal server address and could not connect.
- Why: Resolve collaboration takes each editor's address as the project server sees it; behind address translation every editor registered the server's internal gateway.
- Must: The shared project server sees each editor's real, mutually reachable address, on the LAN and the private network alike.
- Kind: given

### SRV-013: Resolve's project database server ships with a well-known superuser password.
- Why: A site set up with that default password accepted database connections from every network and sat outside every backup.
- Must: Any Resolve project database the product sets up gets a random password, accepts only the studio's LAN and private network, and is backed up.
- Kind: given

### SRV-014: The owner: the server runs on whichever NAS the studio owns.
- Why: The product ran only on TrueNAS; the owner asked to "make it run on synology also".
- Must: Installing and running every server feature works the same on a Synology and on a TrueNAS, from the same release.
- Kind: ruling

### SRV-015: The owner: a customer installs two things, then a browser wizard does the rest.
- Why: The admin should "do nothing except install" the private network and the server; "Only us as the issuers of the product should ever be building anything."
- Must: A new studio is set up from a browser wizard after those installs, with no commands, builds, signing keys or manual steps on the customer's side.
- Kind: ruling

### SRV-016: The owner: the dashboard is reached only over the studio's private network.
- Why: The owner ruled the private network "should be the only option also for future customers"; the login is the dashboard's only gate.
- Must: A new site starts with every secure default on and serves the dashboard only over https on the private network, no public port or relay, except deliberately public links.
- Kind: ruling

### SRV-017: The owner: a customer shows setup their folder layout instead of adopting ours.
- Why: The project-folder layout was partly fixed in the product; the owner wants setup pointed at sample projects to infer a template.
- Must: Setup derives the project layout from one or more sample project folders, and no folder name of this studio is required anywhere.
- Kind: ruling

### SRV-018: The owner: the drive letter editors see the tree on is set on the server.
- Why: The tree's drive letter is site data, defaulting to P:, so a second studio never needs a different installer.
- Must: The drive letter is set once on the server, defaults to P:, and every installer and editor app reads it from there.
- Kind: ruling

### SRV-019: A new customer following the install guide reached a server nobody could sign in to.
- Why: The default sign-in needed a NAS address never asked for, the first-admin page redirected to sign-in, and a required storage check could never pass.
- Must: A fresh install done as documented reaches first-admin creation in the browser, sign-in, working folder sync and private reachability, and every required setup check can pass.
- Kind: situation

### SRV-020: Nobody but its makers had ever installed the product on a clean NAS.
- Why: No clean install through to editors' computers, first sync, first update and first rollback had been done by an outsider.
- Must: On a clean NAS, following only the published guide, a newcomer reaches first sync, first update and first rollback on one Windows and one Mac editor.
- Kind: situation

### SRV-021: The admin could see setup problems but had no way to fix them.
- Why: Setup detected missing values but offered no field, and advice said to edit server files the next update overwrites: "A finding the operator cannot clear is worse than no finding."
- Must: Every value setup checks can be entered in setup itself, and every finding's next action is doable from the product's pages, never by editing files or redeploying.
- Kind: situation

### SRV-022: Setup said Done with no alerts, no signing key and no snapshots.
- Why: What a new studio most needs and is least likely to do unprompted was optional and unmentioned in setup.
- Must: Setup is not done until alert destination, release signing key and NAS snapshots are each set or knowingly skipped; a skip never turns a protection line green.
- Kind: situation

### SRV-023: Setup stuck on a required step nobody could complete, then passed it wrongly.
- Why: A build missing its licence document left a required step amber for ever; a fix then counted it accepted even after an unaccepted licence arrived.
- Must: Setup never requires a step the admin cannot complete, and the licence counts as accepted only when someone accepted the licence now present.
- Kind: situation

### SRV-024: One missing guide stopped the licence agreement from being installed.
- Why: A deploy shipped no documents at all when any one was absent, so setup told editors no licence agreement was included.
- Must: A deploy ships the documents present, names the missing ones, and refuses only when the licence agreement itself is missing.
- Kind: situation

### SRV-025: Folders the install created on the NAS locked out editors and the sync.
- Why: A fresh install left the shared assets folder and its parents owned by the NAS administrator, with fixed user and group numbers instead of the site's.
- Must: Every folder the product creates, parents included, has the site's owner, group and permissions, writable by the server's services and by editors over the share.
- Kind: situation

### SRV-026: A fresh install's sync service restart-looped because it could not write its folders.
- Why: The folders handed to the server's services belonged to the administrator account, not the account the services run as.
- Must: On a fresh install every server service starts once and stays up, and every folder it writes exists and is writable by the account it runs as.
- Kind: situation

### SRV-027: Re-running the install with the build already running tore the app down.
- Why: An install aimed at the running build deleted and re-created the app, interrupting everyone for nothing.
- Must: Re-running the install with the build already running leaves the running server untouched.
- Kind: situation

### SRV-028: On a fresh install, server parts disagreed on shared secrets, so no editor connected.
- Why: Each server part generated or read a shared secret under its own name on first boot, so one part was refused by another for ever.
- Must: After the first boot of a fresh install every server part holds the same shared secrets, and editors connect without manual repair.
- Kind: situation

### SRV-029: Remote editors could have been given the NAS's LAN address.
- Why: A NAS reachable on the studio LAN and privately from outside has no single address; the LAN one fails for remote editors.
- Must: Each editor's computer is set up with an address it can actually reach, never assumed to be the LAN address.
- Kind: situation

### SRV-030: Setup said the dashboard was published while only the server could reach it.
- Why: The private-network step turned green because the server's own network link was up, though nothing made the dashboard reachable from other computers.
- Must: The publishing step turns green only when the dashboard answers over the private network at a valid secure address.
- Kind: situation

### SRV-031: A file-ownership warning advised running the server as root.
- Why: The expected owner was read off a data folder created as root, so the warning blamed the configured id and recommended root.
- Must: A setup warning says where its number came from and recommends the matching fix, and never advises running the server as root.
- Kind: situation

### SRV-032: Setting only the user half of the file-owner pair misfiled files days later.
- Why: A user id set without its group id was honoured by one part and ignored by another, so files landed under different owners and an editor's sync failed.
- Must: The server's file-owner user and group are set together or not at all, and a half-set pair is warned about at start.
- Kind: situation

### SRV-034: Changing the tree's drive letter after computers joined would break every path.
- Why: Editors' computers and their Resolve links point at the drive letter and tree name, so a later change breaks them all.
- Must: The drive letter and tree name are fixed once any computer has joined, and are shown read-only.
- Kind: situation

### SRV-035: A helper program fetched for the admin was installed without its publisher's checksum.
- Why: When a release published no checksum, the downloaded bytes served as their own proof while the page claimed they were verified.
- Must: A third-party program is installed only when the publisher's checksum matches; otherwise the admin is refused and offered to point at a copy they installed.
- Kind: situation

See also, filed under another capability:

- ALL-080 (The whole product): Names containing ".." could reach outside the studio tree.

## Settings and secrets

### SRV-036: A placeholder, a blank secret or another start path left the server open.
- Why: A shipped placeholder token worked as a credential, a blank one opened a write path to every session, and one start path ran with sign-in off.
- Must: However started, the server generates a missing secret or refuses to start; a blank, placeholder or weak secret is refused, and no value ever means "open".
- Kind: situation

### SRV-037: A secret saved badly or not at all signed everyone out at the next restart.
- Why: A secret that could not be stored, or was left empty by a full disk or a kill mid-write, was replaced at restart, refusing every computer and browser.
- Must: Secrets are written whole or not at all; one that cannot be stored, or is empty or partial at start, stops the server with a plain reason.
- Kind: situation

### SRV-038: A quoted secret in the settings made every computer's sign-in fail.
- Why: A hand-edited secret with quotes or a trailing space passed the length check but matched nothing.
- Must: At start the server names any secret wrapped in quotes or carrying surrounding spaces, never showing its value.
- Kind: situation

### SRV-039: The customer's own NAS password was refused or altered because of its characters.
- Why: The install refused "$" and mangled "#", quotes and spaces, though a customer's password is theirs and may hold any character.
- Must: A credential the customer owns is stored and read back exactly, whatever its characters; refusals apply only to secrets the product generates.
- Kind: situation

### SRV-040: A setting value the server could not use booted cleanly, then broke sign-in.
- Why: A capitalised sign-in method was read differently in two places, refusing every password; a session lifetime of 0 expired every session at the next request.
- Must: Settings are normalised once at start, and an unknown or unusable value refuses the start, naming the value and the allowed ones.
- Kind: situation

### SRV-041: Settings the operator changed did nothing, or reverted at an update.
- Why: Site settings edited after first boot were ignored, a saved folder choice lived in the replaceable server image, and a redeploy reset secrets and admins to defaults.
- Must: Every setting takes effect when changed or the dashboard says why not, and updates and reinstalls keep every setting, secret and saved choice, showing any change first.
- Kind: situation

## Updates, restarts and rollbacks

### SRV-042: The owner: updating the server must not take the dashboard away.
- Why: The owner: "investigate a new way of deploying the dashboard without taking it down ... The gap is over a minute and it causes problems".
- Must: A server update keeps the dashboard and open editor pages answering throughout, with no gap a person or an editor's app can notice.
- Kind: ruling

### SRV-043: The dashboard was down at boot, waiting on downloads from the internet.
- Why: Boot waited on a tool refresh for 146 seconds, up to 20 minutes on retries, and with no internet the dashboard crash-looped.
- Must: The dashboard serves within seconds of starting with no internet access; any refresh runs beside it and applies at a later start.
- Kind: situation

### SRV-044: A server update that answered every page with an error was kept.
- Why: A boot counted as healthy after a fixed delay, or when the process answered, though the build lacked its page templates and stylesheets.
- Must: An update counts as healthy only when it answers with its own version and serves a real page and stylesheet within about 150 seconds; otherwise it is rolled back.
- Kind: situation

### SRV-045: A server update that crashed on boot was reverted, then reapplied for ever.
- Why: The failed update was reverted and re-applied ten seconds later, endlessly.
- Must: A failed server update is reverted and never reapplied automatically.
- Kind: situation

### SRV-046: A server update that died partway left the dashboard on unknown code.
- Why: A dropped connection or full disk after the switch-over ended the update silently; a later update's clean-up then deleted the copy the dashboard ran from.
- Must: A failed update restarts on a known version and names it, and no later update removes anything the running dashboard still uses.
- Kind: situation

### SRV-047: A full or read-only data disk left an update swapped in but never restarted.
- Why: The update's status notes could not be written to the failed disk, and that failure skipped the restart while the records named the new version.
- Must: An update or rollback on a full or read-only disk either restarts into the new code or stops before swapping, and says plainly which.
- Kind: situation

### SRV-048: A power cut during an update blocked every later update and rollback.
- Why: The "update in progress" mark survived the power loss and still looked current after restart, so every later update was refused until files on the NAS were edited.
- Must: An update interrupted by power loss or a restart shows as failed at its step on the next start, and can be retried or rolled back from the dashboard.
- Kind: situation

### SRV-049: Re-applying the server version already running erased the rollback target.
- Why: After a restart that did not happen or a fallback boot, re-applying the same version blanked the previous one, so rollback went to much older code.
- Must: Re-applying a version keeps the existing rollback target unchanged.
- Kind: situation

### SRV-050: A rollback ran old code against data a newer version had changed.
- Why: A manual rollback kept today's newer-layout data, and an automatic revert counted refused boots as failures and could pick a build older than the data.
- Must: No rollback reaches a build that cannot open the current data unless the admin restores the named backup or accepts the risk; only real failed boots count.
- Kind: situation

### SRV-051: A search index published by a newer server was unreadable by an older one.
- Why: A new index format would break any older server version the server was rolled back to.
- Must: An index is never published to a server that cannot read it, and a server rolled back past an index format still boots with that search marked off.
- Kind: situation

### SRV-052: Rolling back a search index installed a side file instead of the index.
- Why: The recovery picked the newest saved file by name, a journal side file of the old index, installed it and printed "rolled back".
- Must: An index rollback restores only a complete index and checks that it opens before reporting success.
- Kind: situation

### SRV-053: Updating one part on the server downgraded or switched off another.
- Why: Redeploying the cutting editor shipped an older footage sorter, turning it off; an update put back an older downloader, and its start-time add-on failed silently.
- Must: Updating one part never removes, disables or downgrades another, and a part installed at start that fails retries and raises a visible warning.
- Kind: situation

### SRV-054: A broken optional part took the whole dashboard down.
- Why: Adding a new search part left the dashboard unreachable during a deploy, and one unguarded failure could stop the dashboard booting.
- Must: No failure in an optional part ever stops the dashboard starting or serving; that part is shown unavailable with its reason.
- Kind: situation

### SRV-055: A server update would restart under an editor's running download.
- Why: A server update restarts the dashboard for about ten seconds, which kills an editor's YouTube download job running at that moment.
- Must: A server update waits until running download jobs finish, retrying by itself, and is never forced past a running job.
- Kind: situation

### SRV-056: A page's restart button would have restarted the whole studio's server.
- Why: The embedded editor's restart re-ran its own process, which was the shared server, and whole media files were held in memory to send.
- Must: No page action can restart the shared server, and media is streamed with backpressure, never assembled whole in memory.
- Kind: situation

### SRV-057: A restart during a long tool download lost all trace of it.
- Why: A restart or out-of-memory kill during a 313 MB install left the page saying "not installed" and a partial file on disk for ever.
- Must: An install interrupted by a restart shows as interrupted with a try-again button, and partial downloads older than a day are removed.
- Kind: situation

### SRV-058: A stale update record kept a "not running the update" alarm firing.
- Why: An update applied weeks earlier and superseded by newer full installs was silenced only on exact version equality, so it kept alarming.
- Must: An update record not newer than the running server is retired silently; the alarm sounds only when a newer update is not running.
- Kind: situation

### SRV-059: The assistant read as unavailable after every server restart until someone clicked Test.
- Why: Whether the assistant was signed in was remembered only in memory, so each restart forgot it though the sign-in was still saved.
- Must: After a restart a saved sign-in reads as signed in without a manual test, while a sign-in that just failed or was signed out still wins.
- Kind: situation

### SRV-060: Nothing recorded which code a deploy shipped, so nothing could check it.
- Why: A deploy copied code without recording its origin or contents, so a hand-edited copy on the NAS could not be detected.
- Must: Every deploy records what it shipped with per-file checksums, and the server shows "not checked" rather than a verdict when that record is missing.
- Kind: situation

### SRV-061: A missing server database would start fresh and reopen first-admin setup.
- Why: A missing database was recreated empty with first-admin setup open again, data upgrades took no backup, and a forgotten admin password had no way back.
- Must: A missing or damaged database stops the server with a clear message, every data upgrade backs up first, and a locked-out admin has a documented recovery.
- Kind: situation

## Shares that go away, and checks that cannot run

### SRV-062: A NAS share that drops leaves an empty folder where it was mounted.
- Why: An unmounted share, or a volume mounted after the server starts, reads as an existing empty folder, and free space is then measured on the wrong disk.
- Must: A share is judged present only by something that exists on the real share, never by its mount folder existing or listing.
- Kind: given

### SRV-063: A vanished share read as healthy, and writes landed on the bare mount point.
- Why: The server created a project folder on the empty mount point, judged the tree present, and downloaded into storage lost at the next restart.
- Must: Before writing, the server confirms the share by a known item, creates nothing first, shows the section unavailable within one check cycle, and refuses in plain words.
- Kind: situation

### SRV-064: An empty-looking listing made the dashboard record every project as gone.
- Why: An unmounted volume read as empty and a sync helper answering zero folders looked like every project deleted, and both wiped the records.
- Must: A listing that takes a project from many files to none, or the fleet from many projects to none, is refused and reported, never acted on.
- Kind: situation

### SRV-065: Unable to look, the server acted as if nothing was there.
- Why: A refused listing read as "no project marker" or "no backup to roll back to", a refused probe skipped a safety snapshot, and a failed setup step reported success.
- Must: Every check tells present, absent and could-not-check apart; could-not-check names its reason and stops the action, never reading as nothing there or done.
- Kind: situation

### SRV-066: A site served a frozen copy after its share moved to another NAS.
- Why: Moving the share did not move the services reading the old path, which kept serving the orphaned copy without an error.
- Must: When the tree moves, every service reading it is moved or stops with an error; none silently serves the old copy.
- Kind: situation

### SRV-067: A hung NAS share or service froze the background cycle and the health page.
- Why: A hung export blocks inside the operating system, and one slow NAS service stretched a status cycle to 20 minutes, holding ticks and showing editors offline.
- Must: Status and health pages answer within seconds while a share or service hangs, and every background cycle has a time budget and says when it was partial.
- Kind: situation

### SRV-068: A file any editor can write made the server store and process thousands of entries.
- Why: A folder-list file on the share held 10,000 entries against a stated limit of 32; 20,000 entries took 23 seconds of every status cycle.
- Must: Anything editors can write or a link can name is size-limited before processing, so stored data and work stay bounded and background checks never stall.
- Kind: situation

## Snapshots, restoring and the server's disk

### SRV-069: TrueNAS snapshots datasets, not plain folders.
- Why: A folder at the pool root reports the pool as its dataset, TrueNAS will not schedule snapshots on a plain folder, and a recursive pool schedule covers the whole NAS.
- Must: The product's data lives in its own dataset, a pool name is accepted as a dataset answer, and snapshots are never scheduled on a whole pool.
- Kind: given

### SRV-070: TrueNAS refuses a daily snapshot task whose name pattern lacks the hour.
- Why: A task named by year, month and day failed with "%H must be present", so the hourly task existed and the daily silently did not.
- Must: Every snapshot task's name pattern carries hour and minute, and after creating tasks the product confirms each one really exists.
- Kind: given

### SRV-071: A Synology NAS offers no way to read its snapshot schedule.
- Why: Synology's DSM has no interface for reading snapshot schedules, unlike TrueNAS, so "are snapshots configured" cannot be answered there.
- Must: On a Synology the backup check says it cannot see snapshot schedules, asks the owner to confirm on the NAS, and checks recent backups instead.
- Kind: given

### SRV-072: NAS snapshots keep deleted footage on the pool until they expire.
- Why: Unchanged snapshots cost almost nothing, but deleted footage stays for the whole retention; on TrueNAS two schedules sharing a name pattern prune each other's snapshots.
- Must: Media snapshots are kept weeks, not months, each schedule has its own name pattern, and the server warns before snapshot space fills the pool.
- Kind: given

### SRV-073: A NAS mounts each snapshot folder only when it is first opened.
- Why: A server app started earlier sees an empty snapshot folder, and the recovery page blamed a renamed project.
- Must: The recovery page sees every snapshot, including ones never opened since the server started, and explains an empty snapshot folder as not visible.
- Kind: given

### SRV-074: Restoring files on TrueNAS and Synology needs opposite ownership steps.
- Why: After copying files back, resetting ownership is required on TrueNAS but wipes the share's permissions on Synology, and rolling a dataset back destroys every later snapshot.
- Must: Recovery commands are produced only for a NAS platform and dataset the product has verified; otherwise none are given and the missing fact is named.
- Kind: given

### SRV-075: Missing protections, like no snapshot schedule, showed as all green.
- Why: The NAS had no snapshot task and the pre-update snapshot failed silently every time; absence raises no error, so nothing reported it.
- Must: A protection shows green only on positive evidence, otherwise "missing" or "not checked", with a home-page warning; the weekly report lists every protection.
- Kind: situation

### SRV-076: The server's own data had no snapshot behind it under a green install.
- Why: The data sat in a plain folder no schedule covered, scheduling was refused with advice about the wrong setting, and recovery said "there are no snapshots".
- Must: Install checks a working schedule covers the server's data, names the remedy when not, and recovery says snapshots were never set up rather than none exist.
- Kind: situation

### SRV-077: Server-changing tools never said which NAS they were about to change.
- Why: Destructive and recursive privileged changes ran on whichever NAS the configuration pointed to, printing no host and asking nothing.
- Must: Every server-changing action first names the NAS and site; destructive ones need the NAS's name typed, and with no person at a terminal they refuse.
- Kind: situation

### SRV-078: Server changes ran with no snapshot behind them and nobody knew.
- Why: A failed pre-change snapshot was one warning in a long log, and no record of snapshot attempts was kept.
- Must: Every server-changing run ends by saying whether a snapshot was taken and why not, and every attempt is recorded permanently.
- Kind: situation

### SRV-079: Restoring lost files needed a root shell and expert judgement.
- Why: Every restore meant choosing datasets and snapshots by hand and could overwrite the live project; the owner is not technical.
- Must: The owner restores from any snapshot in the dashboard into a separate folder, overwriting nothing; a test restore counts only when the bytes match.
- Kind: situation

### SRV-080: Files restored from a snapshot were synced out to every editor.
- Why: The restore folder was created inside the live project, and hidden folders still sync to every computer with the project ticked.
- Must: Files restored from a snapshot reach editors' computers only when an admin moves them into place.
- Kind: situation

### SRV-081: A restore that stopped at 50,000 files would have looked complete.
- Why: The restore's file walk stopped at its limit and the restore ignored that, so a large project would be half restored.
- Must: A restore that cannot cover the whole tree is refused, naming the limit and offering another route; it never restores part and reports done.
- Kind: situation

### SRV-082: A restore preview counted files it never looked at as missing.
- Why: A snapshot comparison stopped at a file limit and showed "18,402 files missing, 4.1 TB", mostly present, then refused the restore.
- Must: A comparison that stopped early shows no counts and says it could not count; it never shows invented numbers or zeros.
- Kind: situation

### SRV-083: Camera originals deleted over the NAS file share had no way back.
- Why: Any editor signed in to the NAS's file share could delete camera originals, with no recycle bin.
- Must: An original deleted through the file share can be restored by an admin for a stated period, and editors cannot delete originals by default.
- Kind: situation

### SRV-084: Old builds, backups and histories grew without limit on the server's disk.
- Why: Builds, a database backup per update (4.2 GB kept), every server version, never-expiring safety snapshots and 75 MB cut-list histories piled up beside the live database.
- Must: Every snapshot, backup, build and history the product keeps expires by a stated age or count, and the data disk's use is shown.
- Kind: situation

### SRV-085: Writes onto the server did not check free space first.
- Why: Only the manual upload checked space; update downloads and a 313 MB tool install could fill the volume holding the database while health read green.
- Must: Every large write checks for twice its size free before a byte moves, a refusal shows on a page, and low space is reported as a fault.
- Kind: situation

### SRV-086: Nothing warned before the NAS filled or when backups missed something.
- Why: NAS free space was never measured, Resolve's project database sat outside backups, and nothing said no offsite copy existed.
- Must: The dashboard warns before NAS free space runs low and says when there is no offsite copy or Resolve's project database is not backed up.
- Kind: situation

### SRV-087: Each failed retry of a large publish left another 900 MB on the NAS.
- Why: A failed publish of search data left its partial copy, nothing removed it, and every retry added another.
- Must: Leftovers from a failed upload to the NAS are removed by the next attempt and never accumulate across retries.
- Kind: situation

### SRV-088: A 1.4 GB publish that dropped near the end started again from zero.
- Why: The search data went to the NAS as one upload that could not resume, over a link where brief drops are routine.
- Must: An interrupted large publish to the NAS resumes from the files already delivered, each verified by its content.
- Kind: situation

## Off-site backup

### SRV-089: Cold archive storage is cheap to keep and slow and costly to restore.
- Why: For 53 TB of originals, deep cold archive costs about $1/TB a month, but restores take 12-48 h, cost about $90/TB and carry a 180-day minimum.
- Must: Any off-site plan for originals states monthly cost, first-upload time on the studio uplink (about 3 weeks at 30 MB/s), restore time and restore cost.
- Kind: given

### SRV-090: One long-distance upload stream reaches about 7 MB/s; eight reach 23-30.
- Why: Taiwan to Europe at 213 ms round trip: upload 7.3 MB/s single, 23-30 MB/s with 8 streams; download 6.6 and 19.5; 100 GB restores in about 1.5 h.
- Must: Long-distance uploads and restores use parallel streams, and a restore estimate is shown before it starts.
- Kind: given

### SRV-091: The NAS's single long-distance streams jump from 0.3 to 17 MB/s with BBR.
- Why: Taiwan to the US, one stream ran 0.3 MB/s on the default congestion control; the BBR setting survived a reboot, a rate cap set beside it did not.
- Must: The NAS uses congestion control fit for long, lossy links, and any network tuning the product depends on is re-checked after every NAS reboot.
- Kind: given

### SRV-092: The owner: the cheapest off-site copy that can rebuild a client render.
- Why: The NAS held the only copy of every timeline, proxy and interview audio; the owner wanted "the cheapest way", and "the backup should include the resolve project. 1080p proxies."
- Must: Nightly, the NAS itself copies 1080p proxies, audio, stills, graphics, project files and every Resolve project off site, with no PC needing to be on.
- Kind: ruling

### SRV-093: The owner: off-site backup is ticked per project on the dashboard.
- Why: About 2.9 TB of proxies and small files against 57.5 TB of originals; the plan was a per-project tick, on by default.
- Must: Each project can be ticked for off-site backup; an unticked one shows when its copy expires, and a ticked one with no upload in 3 days raises an alert.
- Kind: ruling

### SRV-094: A file deleted on the NAS stays restorable from the off-site copy for a while.
- Why: Deletions are never mirrored at once: kept versions run 24 hourly, 30 daily, 12 weekly and 24 monthly, with contents and names encrypted from the host.
- Must: A deleted or changed file can be restored off site for the stated retention, the page shows that policy, and the host can read no names or contents.
- Kind: ruling

### SRV-095: Off-site upload must not starve editors' sync on the studio uplink.
- Why: The uplink is about 39 MB/s, shared with editors' sync and downloads; the backup is capped at 12 MB/s by day and 30 MB/s overnight.
- Must: Off-site backup runs under a lower bandwidth cap during working hours than overnight, so editors' transfers keep most of the uplink by day.
- Kind: situation

### SRV-096: The off-site copy could not be read without a key kept only on the NAS.
- Why: Losing the NAS would also lose the means to decrypt the off-site copy.
- Must: The off-site backup's key is held somewhere other than the NAS, and the product warns until the owner confirms it is stored safely.
- Kind: situation

### SRV-097: Restoring from the off-site copy had never been tried.
- Why: Recovery means restoring the project library, relinking the timeline to the downloaded proxies as main media and rendering at 1080p.
- Must: A small project is restored and rendered from the off-site copy on a laptop as a rehearsal, and a sample of the backup is verified monthly.
- Kind: situation

## Health checks and alerts

### SRV-098: An e-mail's authentication header can be added by any server along the way.
- Why: A forged reply could carry a passing authentication header, and a substring search for a message id matched unrelated mail in the Sent folder.
- Must: A mailed reply acts only if the studio's own receiving server vouched for it and its reference matches exactly.
- Kind: given

### SRV-099: The owner: the server finds and explains its own problems.
- Why: He asked to "include as many alerts as possible, make the server as self-diagnosing as possible. Any errors should be flagged, the diagnosis should be as clear as possible."
- Must: Every problem the server can detect reaches a person on the home page and by message, with a plain diagnosis and the next action.
- Kind: ruling

### SRV-101: The owner: the server checks itself twice a day and he approves fixes by reply.
- Why: The owner wanted an assistant to examine alerts and health twice daily, e-mail suggested fixes, and "reply to the email and get it to carry out its suggestions".
- Must: A reply acts only from an authorised, authenticated sender with an unexpired reference, and can only trigger actions the dashboard already offers as buttons.
- Kind: ruling

### SRV-102: Nobody was told anything, and nothing said nobody would be.
- Why: The default alert destination was none, and a destination silent for months looked healthy, so every check reported into an empty room.
- Must: With no alert destination, or none delivered in 30 days, the home and protection pages say "nobody is being told"; an unreadable record shows "cannot verify".
- Kind: situation

### SRV-103: Silence from the server cannot tell "all is well" from "server is down".
- Why: Every alert is sent by the thing being watched, so a server that is off sends exactly as much as a healthy one.
- Must: An optional daily "all quiet" message, counting computers and problems, lets the owner notice when messages stop.
- Kind: situation

### SRV-104: Problems open before alerts were set up were never sent.
- Why: Problems found while no destination existed were recorded as already raised, so configuring mail later sent nothing about them.
- Must: When an alert destination is first set, everything currently open is sent at the next check, and the save says so.
- Kind: situation

### SRV-105: A mail server that hung stalled every check and restarted the server each round.
- Why: Sending alerts had no time limit, so an unanswering mail server or web hook outlasted the server's own stuck-check and triggered a restart.
- Must: Delivering alerts finishes within a fixed budget (two minutes a round), overrunning it is reported as a problem, and a slow mail server never stalls or restarts the server.
- Kind: situation

### SRV-106: Alert mail was sent without checking the mail server's certificate.
- Why: The encrypted mail connection accepted any certificate and any host name.
- Must: Alert mail verifies the mail server's certificate and host name by default, a mismatch names the host, and only an explicit admin setting turns it off.
- Kind: situation

### SRV-107: A part not set up on this server was reported as broken and mailed daily.
- Why: A new server with folder sync deliberately not configured reported the sync service down and alerted every day.
- Must: A part this site has not set up shows as "not set up", never as down, and raises no alert.
- Kind: situation

### SRV-108: The "background work stopped" alarm was always on, or never could be.
- Why: Liveness was judged against three minutes though a server without folder sync cycles every ten, and only after a successful cycle, so a failing checker still read fresh.
- Must: Background work is judged alive by when it last started a cycle, against the rhythm this server runs; a stopped one alarms within about 20 minutes, a brand-new one reads "cannot tell".
- Kind: situation

### SRV-109: A dead background worker left the server reporting healthy for hours.
- Why: The status worker could die at start on a locked database and never restart, while the health check only tested that a page answered.
- Must: A background worker that dies is restarted, and the server's health check fails while the data it shows is stale.
- Kind: situation

### SRV-110: The server reported the folder sync reachable when it was not.
- Why: Health counted background rounds that never touch the folder sync as proof it was reachable.
- Must: Health claims a service is reachable only from a round that actually talked to it.
- Kind: situation

### SRV-111: Restarting a background worker could leave two of it running.
- Why: A stop that timed out forgot the still-running worker, and the restart started a second beside it on the same queue.
- Must: Restarting a background worker never results in two; while the old one is still busy, the restart refuses and says so.
- Kind: situation

### SRV-112: The server's own crash reports were written and never read.
- Why: Crash reports went into a folder nothing showed, so only someone with a shell on the NAS could know the server had crashed.
- Must: Crashes since the server last started appear as a problem on the dashboard, and an admin can download the recent reports there.
- Kind: situation

### SRV-113: The server lost its own network link and nobody heard for a day.
- Why: Nothing watched the server's private-network connection, so an expired sign-in produced one vague mail per computer a day later.
- Must: The server alerts once, within minutes, when its own network link is down or its sign-in nears expiry, and when many computers fall silent together.
- Kind: situation

### SRV-114: A sync drive left out overnight wrote the same warning thousands of times.
- Why: Each owed file move was re-sent and re-answered every 30 seconds per machine, and every answer was logged.
- Must: A repeated identical answer is logged once, and again only when its state or detail changes, including across a server restart.
- Kind: situation

### SRV-115: Reporting that the server's store was busy froze the whole dashboard.
- Why: The busy report wrote to the busy store itself, and a once-a-minute sign-in touch blocked up to 20 seconds and refused valid sessions.
- Must: When the store is busy, reporting it adds no write and stalls no request, and a valid session is never refused because a background write waited.
- Kind: situation

### SRV-116: A busy server made reports wait seconds, and its warning blamed the editors' computers.
- Why: With the CPU busy, each report held the database write lock up to 17.6 seconds; the warning blamed the reporting computer and advised unticking projects.
- Must: Reports finish in about a tenth of a second under load, and a slow-write warning measures the lock holder and never blames an editor's computer.
- Kind: situation

### SRV-117: Server memory grew without limit as long clips arrived at once.
- Why: Each waveform held a whole decoded clip (307 MB for 64 minutes) with no limit on parallel clips, and the server process grew to about 2.6 GB.
- Must: Opening an episode of many two-hour interviews with no waveforms yet keeps server memory under a fixed ceiling, and no single feature can exhaust it.
- Kind: situation

See also, filed under another capability:

- DSH-097 (The dashboard): Alert mail comes as one digest, not one mail per alert.

## Connections and credentials

### SRV-118: A NAS ships with a self-signed certificate.
- Why: Checking the NAS's certificate against the system's trusted authorities always fails, which tempts people to switch checking off.
- Must: The NAS certificate seen at first connection is trusted, a changed one is refused, and turning certificate checking off is never offered.
- Kind: given

### SRV-119: The setup computer sent the NAS admin password to whatever host answered.
- Why: Admin connections accepted any NAS host key, the server held the NAS admin password, and every editor had a full shell on the NAS.
- Must: Admin connections pin the NAS host key and refuse a change, the server holds only a scoped NAS key, and editors' NAS accounts transfer files only.
- Kind: situation

### SRV-120: Following a redirect replays a password or key to wherever it points.
- Why: A 307 or 308 redirect resends the body unchanged, and custom key headers usually follow; only the standard authorisation header is dropped across hosts.
- Must: No request carrying a password, key or session follows a redirect; a redirect is refused with its status and target named, and nothing is sent on.
- Kind: situation

### SRV-121: A dropped NAS connection must not make a change happen twice.
- Why: Retrying after a dropped connection is safe for reads, but a change already sent may have been carried out.
- Must: After a dropped connection the server retries reads and unsent requests once, and never re-sends a change that may already have landed.
- Kind: situation

### SRV-122: Installing a sign-in key on the NAS failed but reported success.
- Why: The key install reported only its last step's result, so a failed write during rotation printed "installed" while the revoked key stayed.
- Must: Every setup step that changes the NAS stops on the first failure and reads its result back before reporting success.
- Kind: situation

### SRV-123: Adding a person's second computer locked their first out of the NAS.
- Why: Giving the second computer its access replaced what the account already held instead of adding to it.
- Must: Adding a person's second computer keeps every access their other computers already have on the NAS, and one that could not be given is tried again.
- Kind: situation

### SRV-124: A helper's admin page on the server was open to the network with no login.
- Why: Anyone on the private network or LAN could share any project folder to their own device, and a first guard replaced a password the admin had set.
- Must: No admin page the server runs is reachable without a login, and a login the admin already set is kept, never replaced.
- Kind: situation

## NAS speed, load and clock

### SRV-125: Camera card offloads to the NAS ran far below card, network and disk speeds.
- Why: New writes landed on the disks' slow inner tracks in a pool reported half full, and the switch shipped with flow control off, dropping packets.
- Must: Transfer estimates to the NAS use measured throughput, expecting speed to fall with pool fill and concurrent work, never the nominal link speed.
- Kind: given

### SRV-126: Blackmagic Disk Speed Test showed the NAS writing at only 119 MB/s.
- Why: The test writes through the cache, forcing slow committed writes; a normal buffered copy to the same share ran at 758 MB/s.
- Must: Any NAS speed figure the product shows or tests against comes from buffered large-file writes and reads, never write-through or cached reads.
- Kind: given

### SRV-127: One copy inside the NAS made every share slow to list from that computer.
- Why: A NAS-to-NAS copy saturated the disks, and the NAS serves each PC's file sharing through one process, so all its listings queued behind it.
- Must: Big copies between NAS folders are paced so a person's folder browsing on any share never waits more than a few seconds.
- Kind: given

### SRV-128: A NAS pool about 90% full made every read and listing crawl.
- Why: At 90% full (7.8 TB free of 76) listings took over a minute and short audio encodes 150-336 s instead of under one, with the CPU idle.
- Must: The product warns before the NAS pool passes about 80% full, and names fullness as the cause when reads slow down.
- Kind: given

### SRV-129: A NAS can declare one time zone while its clock and schedules run another.
- Why: The NAS's zone file said UTC while its clock and scheduler ran on Taipei time, and the server app had no zone, so a 04:00 job would run eight hours off.
- Must: Every scheduled scan, snapshot and upload fires at the studio's wall-clock time, shown to the owner and checked against the NAS's actual clock, not its zone file.
- Kind: given

### SRV-130: A client pulling 2 TB made the NAS's web pages time out.
- Why: Big sequential reads collapse the NAS's small-file speed; a 10-second index scan took 390 seconds and pages returned gateway errors.
- Must: Pages stay responsive while large downloads or verifications run, and nothing rescans many files because of one missed page.
- Kind: situation
