# The server: installing it and keeping it running

## Installing on a NAS

### SRV-001: A fresh NAS downloaded from some hosts at about 28 kB/s.
- What was going on: The studio NAS took about 25 minutes for a 42 MB file a workstation fetched in 24 s, overrunning a 10-minute install step.
- What the product must do: Installing never depends on the NAS downloading large files; they can be fetched elsewhere, checksum-verified and pushed over the LAN, a failed checksum leaving nothing.
- Kind: 1a
- From: C01-073, M05-073

### SRV-002: TrueNAS 26 drops the management interface older TrueNAS versions answer.
- What was going on: TrueNAS 26 removes its older request-response web interface and keeps only its live-connection one; 25.04 and 25.10 answer both.
- What the product must do: Installing and managing works on TrueNAS 25 and 26 with no setting, and a NAS version the product cannot drive is refused with a named reason.
- Kind: 1a
- State: fixed, never shipped
- From: H07-119, L11-011, H08-010

### SRV-003: TrueNAS accepted an app install that failed later, and install said success.
- What was going on: On TrueNAS a successful answer to "create this app" only means the job was accepted; it can still fail, for example when its address no longer exists.
- What the product must do: Installation reports success only when the NAS's install job finished successfully and the app is actually running.
- Kind: 1a
- From: H02-003

### SRV-004: On TrueNAS 25.10 a filtered app query returned nothing for an installed app.
- What was going on: A re-run of the install then tried to create the app again and advised deleting the healthy one.
- What the product must do: The product never concludes a NAS app is absent from a filtered query alone, and never advises deleting a running app.
- Kind: 1a
- From: H04-060

### SRV-005: The health check called the editors group empty on a healthy TrueNAS.
- What was going on: TrueNAS user records list group membership by the group's internal database id, not its unix group number, so comparing unix numbers never matches.
- What the product must do: Group membership checks on TrueNAS pass on a correctly set-up NAS and fail only when a member is really missing.
- Kind: 1a
- From: H02-004

### SRV-006: A TrueNAS API key was refused when presented as the admin.
- What was going on: On TrueNAS 25.04 and later an API key belongs to one account and acts with that account's rights, so sign-in must name that account.
- What the product must do: The server signs in to the NAS as the key's own account, and a refused sign-in names the account that was presented.
- Kind: 1a
- State: fixed, never shipped
- From: L11-012

### SRV-007: Synology and TrueNAS number users differently, so a fixed account number fails.
- What was going on: Synology numbers local users from 1026 and TrueNAS gives 3000 to its first, so the server ran as a nonexistent user and could write nothing.
- What the product must do: Install uses the real NAS account the server runs as, and every start warns, naming account and owner, when that account does not own its data folder.
- Kind: 1a
- State: fixed, never shipped
- From: L11-008, L06-060, H07-117

### SRV-008: On Synology the file-transfer login cannot reach system folders, even as admin.
- What was going on: Synology confines its secure file-transfer login to shared folders, so a file staged in the system temporary folder can never be sent.
- What the product must do: Every file copied onto a Synology is staged inside a shared folder the transfer login can see.
- Kind: 1a
- From: H03-036, L01-006

### SRV-009: Synology's admin command-line tools are not found under sudo in a remote session.
- What was going on: On DSM 7.2 the share, user, ACL and app tools live in system folders missing from sudo's search path in a remote session.
- What the product must do: Install steps on a Synology call these tools by full path or set the path first.
- Kind: 1a
- From: M02-105

### SRV-010: Synology caps transfer chunks at 64 KiB and breaks on permission changes in shares.
- What was going on: Synology's file-transfer server limits chunks to 64 KiB, and changing permissions under a shared folder breaks its sharing rules.
- What the product must do: On a Synology, transfers respect the NAS's own limits and nothing changes permissions inside a shared folder.
- Kind: 1a
- From: C01-105

### SRV-011: Windows could create files on the NAS share but not list or read them.
- What was going on: Windows' built-in network-file client checks a file's "other" permission bits itself; with them at none, reads and listings fail "Access is denied" whatever the NAS allows.
- What the product must do: Setup verifies that an editor's computer can list, read, write and delete in the shared tree, and names which of the four failed.
- Kind: 1a
- From: M06-009

### SRV-012: Resolve collaborators were shown an internal server address and could not connect.
- What was going on: Resolve collaboration takes each editor's address as the project server sees it; behind address translation every editor registered the server's internal gateway.
- What the product must do: The shared project server sees each editor's real, mutually reachable address, on the LAN and the private network alike.
- Kind: 1a
- From: M05-050

### SRV-013: Resolve's project database server ships with a well-known superuser password.
- What was going on: A site set up with that default password accepted database connections from every network and sat outside every backup.
- What the product must do: Any Resolve project database the product sets up gets a random password, accepts only the studio's LAN and private network, and is backed up.
- Kind: 1a
- State: fixed, never shipped
- From: H07-121, L11-025

### SRV-014: The owner: the server runs on whichever NAS the studio owns.
- What was going on: The product ran only on TrueNAS; the owner asked to "make it run on synology also".
- What the product must do: Installing and running every server feature works the same on a Synology and on a TrueNAS, from the same release.
- Kind: 2
- From: P06-005

### SRV-015: The owner: a customer installs two things, then a browser wizard does the rest.
- What was going on: The admin should "do nothing except install" the private network and the server; "Only us as the issuers of the product should ever be building anything."
- What the product must do: A new studio is set up from a browser wizard after those installs, with no commands, builds, signing keys or manual steps on the customer's side.
- Kind: 2
- State: fixed, never shipped
- From: P06-006, M03-021

### SRV-016: The owner: the dashboard is reached only over the studio's private network.
- What was going on: The owner ruled the private network "should be the only option also for future customers"; the login is the dashboard's only gate.
- What the product must do: A new site starts with every secure default on and serves the dashboard only over https on the private network, no public port or relay, except deliberately public links.
- Kind: 2
- From: P06-007, M02-086, C01-107, H08-012

### SRV-017: The owner: a customer shows setup their folder layout instead of adopting ours.
- What was going on: The project-folder layout was partly fixed in the product; the owner wants setup pointed at sample projects to infer a template.
- What the product must do: Setup derives the project layout from one or more sample project folders, and no folder name of this studio is required anywhere.
- Kind: 2
- State: still open
- From: P07-012

### SRV-018: The owner: the drive letter editors see the tree on is set on the server.
- What was going on: The tree's drive letter is site data, defaulting to P:, so a second studio never needs a different installer.
- What the product must do: The drive letter is set once on the server, defaults to P:, and every installer and editor app reads it from there.
- Kind: 2
- From: M01-073

### SRV-019: A new customer following the install guide reached a server nobody could sign in to.
- What was going on: The default sign-in needed a NAS address never asked for, the first-admin page redirected to sign-in, and a required storage check could never pass.
- What the product must do: A fresh install done as documented reaches first-admin creation in the browser, sign-in, working folder sync and private reachability, and every required setup check can pass.
- Kind: 3
- From: H07-114, M02-092, L10-092, L01-074

### SRV-020: Nobody but its makers had ever installed the product on a clean NAS.
- What was going on: No clean install through to editors' computers, first sync, first update and first rollback had been done by an outsider.
- What the product must do: On a clean NAS, following only the published guide, a newcomer reaches first sync, first update and first rollback on one Windows and one Mac editor.
- Kind: 3
- State: outcome not found
- From: H08-017

### SRV-021: The admin could see setup problems but had no way to fix them.
- What was going on: Setup detected missing values but offered no field, and advice said to edit server files the next update overwrites: "A finding the operator cannot clear is worse than no finding."
- What the product must do: Every value setup checks can be entered in setup itself, and every finding's next action is doable from the product's pages, never by editing files or redeploying.
- Kind: 3
- State: fixed, never shipped
- From: L11-004, L04-030

### SRV-022: Setup said Done with no alerts, no signing key and no snapshots.
- What was going on: What a new studio most needs and is least likely to do unprompted was optional and unmentioned in setup.
- What the product must do: Setup is not done until alert destination, release signing key and NAS snapshots are each set or knowingly skipped; a skip never turns a protection line green.
- Kind: 3
- From: L04-081

### SRV-023: Setup stuck on a required step nobody could complete, then passed it wrongly.
- What was going on: A build missing its licence document left a required step amber for ever; a fix then counted it accepted even after an unaccepted licence arrived.
- What the product must do: Setup never requires a step the admin cannot complete, and the licence counts as accepted only when someone accepted the licence now present.
- Kind: 3
- From: L06-040, H05-069

### SRV-024: One missing guide stopped the licence agreement from being installed.
- What was going on: A deploy shipped no documents at all when any one was absent, so setup told editors no licence agreement was included.
- What the product must do: A deploy ships the documents present, names the missing ones, and refuses only when the licence agreement itself is missing.
- Kind: 3
- From: L09-053

### SRV-025: Folders the install created on the NAS locked out editors and the sync.
- What was going on: A fresh install left the shared assets folder and its parents owned by the NAS administrator, with fixed user and group numbers instead of the site's.
- What the product must do: Every folder the product creates, parents included, has the site's owner, group and permissions, writable by the server's services and by editors over the share.
- Kind: 3
- From: H04-049, H03-034, L01-007

### SRV-026: A fresh install's sync service restart-looped because it could not write its folders.
- What was going on: The folders handed to the server's services belonged to the administrator account, not the account the services run as.
- What the product must do: On a fresh install every server service starts once and stays up, and every folder it writes exists and is writable by the account it runs as.
- Kind: 3
- State: fixed, never shipped
- From: L11-003

### SRV-027: Re-running the install with the build already running tore the app down.
- What was going on: An install aimed at the running build deleted and re-created the app, interrupting everyone for nothing.
- What the product must do: Re-running the install with the build already running leaves the running server untouched.
- Kind: 3
- State: fixed, never shipped
- From: L11-076

### SRV-028: On a fresh install, server parts disagreed on shared secrets, so no editor connected.
- What was going on: Each server part generated or read a shared secret under its own name on first boot, so one part was refused by another for ever.
- What the product must do: After the first boot of a fresh install every server part holds the same shared secrets, and editors connect without manual repair.
- Kind: 3
- From: H03-027

### SRV-029: Remote editors could have been given the NAS's LAN address.
- What was going on: A NAS reachable on the studio LAN and privately from outside has no single address; the LAN one fails for remote editors.
- What the product must do: Each editor's computer is set up with an address it can actually reach, never assumed to be the LAN address.
- Kind: 3
- From: C01-106

### SRV-030: Setup said the dashboard was published while only the server could reach it.
- What was going on: The private-network step turned green because the server's own network link was up, though nothing made the dashboard reachable from other computers.
- What the product must do: The publishing step turns green only when the dashboard answers over the private network at a valid secure address.
- Kind: 3
- State: fixed, never shipped
- From: L11-001

### SRV-031: A file-ownership warning advised running the server as root.
- What was going on: The expected owner was read off a data folder created as root, so the warning blamed the configured id and recommended root.
- What the product must do: A setup warning says where its number came from and recommends the matching fix, and never advises running the server as root.
- Kind: 3
- From: L07-042

### SRV-032: Setting only the user half of the file-owner pair misfiled files days later.
- What was going on: A user id set without its group id was honoured by one part and ignored by another, so files landed under different owners and an editor's sync failed.
- What the product must do: The server's file-owner user and group are set together or not at all, and a half-set pair is warned about at start.
- Kind: 3
- From: L07-041

### SRV-033: Folder names from configuration could climb out of the project tree.
- What was going on: Template folder names from one configuration source kept ".." segments, and new projects created those folders as given.
- What the product must do: Every folder name, from any configuration source, is checked so it can never point outside the project tree.
- Kind: 3
- From: H05-068

### SRV-034: Changing the tree's drive letter after computers joined would break every path.
- What was going on: Editors' computers and their Resolve links point at the drive letter and tree name, so a later change breaks them all.
- What the product must do: The drive letter and tree name are fixed once any computer has joined, and are shown read-only.
- Kind: 3
- State: fixed, never shipped
- From: L11-029

### SRV-035: A helper program fetched for the admin was installed without its publisher's checksum.
- What was going on: When a release published no checksum, the downloaded bytes served as their own proof while the page claimed they were verified.
- What the product must do: A third-party program is installed only when the publisher's checksum matches; otherwise the admin is refused and offered to point at a copy they installed.
- Kind: 3
- From: H04-016

## Settings and secrets

### SRV-036: A placeholder, a blank secret or another start path left the server open.
- What was going on: A shipped placeholder token worked as a credential, a blank one opened a write path to every session, and one start path ran with sign-in off.
- What the product must do: However started, the server generates a missing secret or refuses to start; a blank, placeholder or weak secret is refused, and no value ever means "open".
- Kind: 3
- From: H04-019, H03-025

### SRV-037: A secret saved badly or not at all signed everyone out at the next restart.
- What was going on: A secret that could not be stored, or was left empty by a full disk or a kill mid-write, was replaced at restart, refusing every computer and browser.
- What the product must do: Secrets are written whole or not at all; one that cannot be stored, or is empty or partial at start, stops the server with a plain reason.
- Kind: 3
- From: L04-066, L09-010, H06-056

### SRV-038: A quoted secret in the settings made every computer's sign-in fail.
- What was going on: A hand-edited secret with quotes or a trailing space passed the length check but matched nothing.
- What the product must do: At start the server names any secret wrapped in quotes or carrying surrounding spaces, never showing its value.
- Kind: 3
- From: L02-068

### SRV-039: The customer's own NAS password was refused or altered because of its characters.
- What was going on: The install refused "$" and mangled "#", quotes and spaces, though a customer's password is theirs and may hold any character.
- What the product must do: A credential the customer owns is stored and read back exactly, whatever its characters; refusals apply only to secrets the product generates.
- Kind: 3
- From: L04-006

### SRV-040: A setting value the server could not use booted cleanly, then broke sign-in.
- What was going on: A capitalised sign-in method was read differently in two places, refusing every password; a session lifetime of 0 expired every session at the next request.
- What the product must do: Settings are normalised once at start, and an unknown or unusable value refuses the start, naming the value and the allowed ones.
- Kind: 3
- From: L03-089, H05-070

### SRV-041: Settings the operator changed did nothing, or reverted at an update.
- What was going on: Site settings edited after first boot were ignored, a saved folder choice lived in the replaceable server image, and a redeploy reset secrets and admins to defaults.
- What the product must do: Every setting takes effect when changed or the dashboard says why not, and updates and reinstalls keep every setting, secret and saved choice, showing any change first.
- Kind: 3
- State: outcome not found
- From: H08-033, G01-037, D04-066

## Updates, restarts and rollbacks

### SRV-042: The owner: updating the server must not take the dashboard away.
- What was going on: The owner: "investigate a new way of deploying the dashboard without taking it down ... The gap is over a minute and it causes problems".
- What the product must do: A server update keeps the dashboard and open editor pages answering throughout, with no gap a person or an editor's app can notice.
- Kind: 2
- State: outcome not found
- From: P13-027, P11-022

### SRV-043: The dashboard was down at boot, waiting on downloads from the internet.
- What was going on: Boot waited on a tool refresh for 146 seconds, up to 20 minutes on retries, and with no internet the dashboard crash-looped.
- What the product must do: The dashboard serves within seconds of starting with no internet access; any refresh runs beside it and applies at a later start.
- Kind: 3
- From: C04-028, H04-052

### SRV-044: A server update that answered every page with an error was kept.
- What was going on: A boot counted as healthy after a fixed delay, or when the process answered, though the build lacked its page templates and stylesheets.
- What the product must do: An update counts as healthy only when it answers with its own version and serves a real page and stylesheet within about 150 seconds; otherwise it is rolled back.
- Kind: 3
- From: L02-058, L01-003

### SRV-045: A server update that crashed on boot was reverted, then reapplied for ever.
- What was going on: The failed update was reverted and re-applied ten seconds later, endlessly.
- What the product must do: A failed server update is reverted and never reapplied automatically.
- Kind: 3
- State: fixed, never shipped
- From: H07-024

### SRV-046: A server update that died partway left the dashboard on unknown code.
- What was going on: A dropped connection or full disk after the switch-over ended the update silently; a later update's clean-up then deleted the copy the dashboard ran from.
- What the product must do: A failed update restarts on a known version and names it, and no later update removes anything the running dashboard still uses.
- Kind: 3
- From: H02-002, H01-024

### SRV-047: A full or read-only data disk left an update swapped in but never restarted.
- What was going on: The update's status notes could not be written to the failed disk, and that failure skipped the restart while the records named the new version.
- What the product must do: An update or rollback on a full or read-only disk either restarts into the new code or stops before swapping, and says plainly which.
- Kind: 3
- From: L10-012, L09-019, H06-055

### SRV-048: A power cut during an update blocked every later update and rollback.
- What was going on: The "update in progress" mark survived the power loss and still looked current after restart, so every later update was refused until files on the NAS were edited.
- What the product must do: An update interrupted by power loss or a restart shows as failed at its step on the next start, and can be retried or rolled back from the dashboard.
- Kind: 3
- From: L02-059, H03-033

### SRV-049: Re-applying the server version already running erased the rollback target.
- What was going on: After a restart that did not happen or a fallback boot, re-applying the same version blanked the previous one, so rollback went to much older code.
- What the product must do: Re-applying a version keeps the existing rollback target unchanged.
- Kind: 3
- From: L09-022

### SRV-050: A rollback ran old code against data a newer version had changed.
- What was going on: A manual rollback kept today's newer-layout data, and an automatic revert counted refused boots as failures and could pick a build older than the data.
- What the product must do: No rollback reaches a build that cannot open the current data unless the admin restores the named backup or accepts the risk; only real failed boots count.
- Kind: 3
- From: H05-074, L02-060

### SRV-051: A search index published by a newer server was unreadable by an older one.
- What was going on: A new index format would break any older server version the server was rolled back to.
- What the product must do: An index is never published to a server that cannot read it, and a server rolled back past an index format still boots with that search marked off.
- Kind: 3
- From: H06-050

### SRV-052: Rolling back a search index installed a side file instead of the index.
- What was going on: The recovery picked the newest saved file by name, a journal side file of the old index, installed it and printed "rolled back".
- What the product must do: An index rollback restores only a complete index and checks that it opens before reporting success.
- Kind: 3
- From: H06-051

### SRV-053: Updating one part on the server downgraded or switched off another.
- What was going on: Redeploying the cutting editor shipped an older footage sorter, turning it off; an update put back an older downloader, and its start-time add-on failed silently.
- What the product must do: Updating one part never removes, disables or downgrades another, and a part installed at start that fails retries and raises a visible warning.
- Kind: 3
- From: P17-028, M03-006

### SRV-054: A broken optional part took the whole dashboard down.
- What was going on: Adding a new search part left the dashboard unreachable during a deploy, and one unguarded failure could stop the dashboard booting.
- What the product must do: No failure in an optional part ever stops the dashboard starting or serving; that part is shown unavailable with its reason.
- Kind: 3
- State: outcome not found
- From: H05-103, P03-039

### SRV-055: A server update would restart under an editor's running download.
- What was going on: A server update restarts the dashboard for about ten seconds, which kills an editor's YouTube download job running at that moment.
- What the product must do: A server update waits until running download jobs finish, retrying by itself, and is never forced past a running job.
- Kind: 3
- From: M02-020

### SRV-056: A page's restart button would have restarted the whole studio's server.
- What was going on: The embedded editor's restart re-ran its own process, which was the shared server, and whole media files were held in memory to send.
- What the product must do: No page action can restart the shared server, and media is streamed with backpressure, never assembled whole in memory.
- Kind: 3
- From: G01-051

### SRV-057: A restart during a long tool download lost all trace of it.
- What was going on: A restart or out-of-memory kill during a 313 MB install left the page saying "not installed" and a partial file on disk for ever.
- What the product must do: An install interrupted by a restart shows as interrupted with a try-again button, and partial downloads older than a day are removed.
- Kind: 3
- From: L05-014

### SRV-058: A stale update record kept a "not running the update" alarm firing.
- What was going on: An update applied weeks earlier and superseded by newer full installs was silenced only on exact version equality, so it kept alarming.
- What the product must do: An update record not newer than the running server is retired silently; the alarm sounds only when a newer update is not running.
- Kind: 3
- From: M01-069, L08-034

### SRV-059: The assistant read as unavailable after every server restart until someone clicked Test.
- What was going on: Whether the assistant was signed in was remembered only in memory, so each restart forgot it though the sign-in was still saved.
- What the product must do: After a restart a saved sign-in reads as signed in without a manual test, while a sign-in that just failed or was signed out still wins.
- Kind: 3
- From: L05-040

### SRV-060: Nothing recorded which code a deploy shipped, so nothing could check it.
- What was going on: A deploy copied code without recording its origin or contents, so a hand-edited copy on the NAS could not be detected.
- What the product must do: Every deploy records what it shipped with per-file checksums, and the server shows "not checked" rather than a verdict when that record is missing.
- Kind: 3
- State: still open
- From: L04-076

### SRV-061: A missing server database would start fresh and reopen first-admin setup.
- What was going on: A missing database was recreated empty with first-admin setup open again, data upgrades took no backup, and a forgotten admin password had no way back.
- What the product must do: A missing or damaged database stops the server with a clear message, every data upgrade backs up first, and a locked-out admin has a documented recovery.
- Kind: 3
- State: outcome not found
- From: H08-028

## Shares that go away, and checks that cannot run

### SRV-062: A NAS share that drops leaves an empty folder where it was mounted.
- What was going on: An unmounted share, or a volume mounted after the server starts, reads as an existing empty folder, and free space is then measured on the wrong disk.
- What the product must do: A share is judged present only by something that exists on the real share, never by its mount folder existing or listing.
- Kind: 1a
- From: H05-066, L02-026

### SRV-063: A vanished share read as healthy, and writes landed on the bare mount point.
- What was going on: The server created a project folder on the empty mount point, judged the tree present, and downloaded into storage lost at the next restart.
- What the product must do: Before writing, the server confirms the share by a known item, creates nothing first, shows the section unavailable within one check cycle, and refuses in plain words.
- Kind: 3
- From: L10-006, H06-030, L07-038

### SRV-064: An empty-looking listing made the dashboard record every project as gone.
- What was going on: An unmounted volume read as empty and a sync helper answering zero folders looked like every project deleted, and both wiped the records.
- What the product must do: A listing that takes a project from many files to none, or the fleet from many projects to none, is refused and reported, never acted on.
- Kind: 3
- From: H07-034

### SRV-065: Unable to look, the server acted as if nothing was there.
- What was going on: A refused listing read as "no project marker" or "no backup to roll back to", a refused probe skipped a safety snapshot, and a failed setup step reported success.
- What the product must do: Every check tells present, absent and could-not-check apart; could-not-check names its reason and stops the action, never reading as nothing there or done.
- Kind: 3
- From: H02-005, H03-026

### SRV-066: A site served a frozen copy after its share moved to another NAS.
- What was going on: Moving the share did not move the services reading the old path, which kept serving the orphaned copy without an error.
- What the product must do: When the tree moves, every service reading it is moved or stops with an error; none silently serves the old copy.
- Kind: 3
- From: M05-072

### SRV-067: A hung NAS share or service froze the background cycle and the health page.
- What was going on: A hung export blocks inside the operating system, and one slow NAS service stretched a status cycle to 20 minutes, holding ticks and showing editors offline.
- What the product must do: Status and health pages answer within seconds while a share or service hangs, and every background cycle has a time budget and says when it was partial.
- Kind: 3
- From: H04-043, L07-033

### SRV-068: A file any editor can write made the server store and process thousands of entries.
- What was going on: A folder-list file on the share held 10,000 entries against a stated limit of 32; 20,000 entries took 23 seconds of every status cycle.
- What the product must do: Anything editors can write or a link can name is size-limited before processing, so stored data and work stay bounded and background checks never stall.
- Kind: 3
- From: H05-064, L07-049

## Snapshots, restoring and the server's disk

### SRV-069: TrueNAS snapshots datasets, not plain folders.
- What was going on: A folder at the pool root reports the pool as its dataset, TrueNAS will not schedule snapshots on a plain folder, and a recursive pool schedule covers the whole NAS.
- What the product must do: The product's data lives in its own dataset, a pool name is accepted as a dataset answer, and snapshots are never scheduled on a whole pool.
- Kind: 1a
- From: L01-005, L03-021, C03-020

### SRV-070: TrueNAS refuses a daily snapshot task whose name pattern lacks the hour.
- What was going on: A task named by year, month and day failed with "%H must be present", so the hourly task existed and the daily silently did not.
- What the product must do: Every snapshot task's name pattern carries hour and minute, and after creating tasks the product confirms each one really exists.
- Kind: 1a
- From: L05-002

### SRV-071: A Synology NAS offers no way to read its snapshot schedule.
- What was going on: Synology's DSM has no interface for reading snapshot schedules, unlike TrueNAS, so "are snapshots configured" cannot be answered there.
- What the product must do: On a Synology the backup check says it cannot see snapshot schedules, asks the owner to confirm on the NAS, and checks recent backups instead.
- Kind: 1a
- From: C02-045

### SRV-072: NAS snapshots keep deleted footage on the pool until they expire.
- What was going on: Unchanged snapshots cost almost nothing, but deleted footage stays for the whole retention; on TrueNAS two schedules sharing a name pattern prune each other's snapshots.
- What the product must do: Media snapshots are kept weeks, not months, each schedule has its own name pattern, and the server warns before snapshot space fills the pool.
- Kind: 1a
- From: H07-019, M06-010

### SRV-073: A NAS mounts each snapshot folder only when it is first opened.
- What was going on: A server app started earlier sees an empty snapshot folder, and the recovery page blamed a renamed project.
- What the product must do: The recovery page sees every snapshot, including ones never opened since the server started, and explains an empty snapshot folder as not visible.
- Kind: 1a
- State: still open
- From: L06-075

### SRV-074: Restoring files on TrueNAS and Synology needs opposite ownership steps.
- What was going on: After copying files back, resetting ownership is required on TrueNAS but wipes the share's permissions on Synology, and rolling a dataset back destroys every later snapshot.
- What the product must do: Recovery commands are produced only for a NAS platform and dataset the product has verified; otherwise none are given and the missing fact is named.
- Kind: 1a
- From: L03-025

### SRV-075: Missing protections, like no snapshot schedule, showed as all green.
- What was going on: The NAS had no snapshot task and the pre-update snapshot failed silently every time; absence raises no error, so nothing reported it.
- What the product must do: A protection shows green only on positive evidence, otherwise "missing" or "not checked", with a home-page warning; the weekly report lists every protection.
- Kind: 3
- From: H07-050, L03-020, C03-018, L01-004, H04-004

### SRV-076: The server's own data had no snapshot behind it under a green install.
- What was going on: The data sat in a plain folder no schedule covered, scheduling was refused with advice about the wrong setting, and recovery said "there are no snapshots".
- What the product must do: Install checks a working schedule covers the server's data, names the remedy when not, and recovery says snapshots were never set up rather than none exist.
- Kind: 3
- From: L05-001, H03-037

### SRV-077: Server-changing tools never said which NAS they were about to change.
- What was going on: Destructive and recursive privileged changes ran on whichever NAS the configuration pointed to, printing no host and asking nothing.
- What the product must do: Every server-changing action first names the NAS and site; destructive ones need the NAS's name typed, and with no person at a terminal they refuse.
- Kind: 3
- From: L02-037, H07-052

### SRV-078: Server changes ran with no snapshot behind them and nobody knew.
- What was going on: A failed pre-change snapshot was one warning in a long log, and no record of snapshot attempts was kept.
- What the product must do: Every server-changing run ends by saying whether a snapshot was taken and why not, and every attempt is recorded permanently.
- Kind: 3
- From: L02-038

### SRV-079: Restoring lost files needed a root shell and expert judgement.
- What was going on: Every restore meant choosing datasets and snapshots by hand and could overwrite the live project; the owner is not technical.
- What the product must do: The owner restores from any snapshot in the dashboard into a separate folder, overwriting nothing; a test restore counts only when the bytes match.
- Kind: 3
- From: H07-051, L03-024

### SRV-080: Files restored from a snapshot were synced out to every editor.
- What was going on: The restore folder was created inside the live project, and hidden folders still sync to every computer with the project ticked.
- What the product must do: Files restored from a snapshot reach editors' computers only when an admin moves them into place.
- Kind: 3
- From: H06-104

### SRV-081: A restore that stopped at 50,000 files would have looked complete.
- What was going on: The restore's file walk stopped at its limit and the restore ignored that, so a large project would be half restored.
- What the product must do: A restore that cannot cover the whole tree is refused, naming the limit and offering another route; it never restores part and reports done.
- Kind: 3
- From: L06-051, H05-062

### SRV-082: A restore preview counted files it never looked at as missing.
- What was going on: A snapshot comparison stopped at a file limit and showed "18,402 files missing, 4.1 TB", mostly present, then refused the restore.
- What the product must do: A comparison that stopped early shows no counts and says it could not count; it never shows invented numbers or zeros.
- Kind: 3
- From: L07-034

### SRV-083: Camera originals deleted over the NAS file share had no way back.
- What was going on: Any editor signed in to the NAS's file share could delete camera originals, with no recycle bin.
- What the product must do: An original deleted through the file share can be restored by an admin for a stated period, and editors cannot delete originals by default.
- Kind: 3
- State: outcome not found
- From: H08-025

### SRV-084: Old builds, backups and histories grew without limit on the server's disk.
- What was going on: Builds, a database backup per update (4.2 GB kept), every server version, never-expiring safety snapshots and 75 MB cut-list histories piled up beside the live database.
- What the product must do: Every snapshot, backup, build and history the product keeps expires by a stated age or count, and the data disk's use is shown.
- Kind: 3
- State: still open
- From: L02-062, H08-078

### SRV-085: Writes onto the server did not check free space first.
- What was going on: Only the manual upload checked space; update downloads and a 313 MB tool install could fill the volume holding the database while health read green.
- What the product must do: Every large write checks for twice its size free before a byte moves, a refusal shows on a page, and low space is reported as a fault.
- Kind: 3
- From: L05-013, H07-020

### SRV-086: Nothing warned before the NAS filled or when backups missed something.
- What was going on: NAS free space was never measured, Resolve's project database sat outside backups, and nothing said no offsite copy existed.
- What the product must do: The dashboard warns before NAS free space runs low and says when there is no offsite copy or Resolve's project database is not backed up.
- Kind: 3
- State: outcome not found
- From: H08-029

### SRV-087: Each failed retry of a large publish left another 900 MB on the NAS.
- What was going on: A failed publish of search data left its partial copy, nothing removed it, and every retry added another.
- What the product must do: Leftovers from a failed upload to the NAS are removed by the next attempt and never accumulate across retries.
- Kind: 3
- From: H02-006

### SRV-088: A 1.4 GB publish that dropped near the end started again from zero.
- What was going on: The search data went to the NAS as one upload that could not resume, over a link where brief drops are routine.
- What the product must do: An interrupted large publish to the NAS resumes from the files already delivered, each verified by its content.
- Kind: 3
- State: still open
- From: H02-007

## Off-site backup

### SRV-089: Cold archive storage is cheap to keep and slow and costly to restore.
- What was going on: For 53 TB of originals, deep cold archive costs about $1/TB a month, but restores take 12-48 h, cost about $90/TB and carry a 180-day minimum.
- What the product must do: Any off-site plan for originals states monthly cost, first-upload time on the studio uplink (about 3 weeks at 30 MB/s), restore time and restore cost.
- Kind: 1a
- State: still open
- From: D07-109

### SRV-090: One long-distance upload stream reaches about 7 MB/s; eight reach 23-30.
- What was going on: Taiwan to Europe at 213 ms round trip: upload 7.3 MB/s single, 23-30 MB/s with 8 streams; download 6.6 and 19.5; 100 GB restores in about 1.5 h.
- What the product must do: Long-distance uploads and restores use parallel streams, and a restore estimate is shown before it starts.
- Kind: 1a
- From: D07-100, M04-096

### SRV-091: The NAS's single long-distance streams jump from 0.3 to 17 MB/s with BBR.
- What was going on: Taiwan to the US, one stream ran 0.3 MB/s on the default congestion control; the BBR setting survived a reboot, a rate cap set beside it did not.
- What the product must do: The NAS uses congestion control fit for long, lossy links, and any network tuning the product depends on is re-checked after every NAS reboot.
- Kind: 1a
- State: still open
- From: D07-101

### SRV-092: The owner: the cheapest off-site copy that can rebuild a client render.
- What was going on: The NAS held the only copy of every timeline, proxy and interview audio; the owner wanted "the cheapest way", and "the backup should include the resolve project. 1080p proxies."
- What the product must do: Nightly, the NAS itself copies 1080p proxies, audio, stills, graphics, project files and every Resolve project off site, with no PC needing to be on.
- Kind: 2
- From: D07-097, D07-096

### SRV-093: The owner: off-site backup is ticked per project on the dashboard.
- What was going on: About 2.9 TB of proxies and small files against 57.5 TB of originals; the plan was a per-project tick, on by default.
- What the product must do: Each project can be ticked for off-site backup; an unticked one shows when its copy expires, and a ticked one with no upload in 3 days raises an alert.
- Kind: 2
- State: still open
- From: P16-051, D07-108

### SRV-094: A file deleted on the NAS stays restorable from the off-site copy for a while.
- What was going on: Deletions are never mirrored at once: kept versions run 24 hourly, 30 daily, 12 weekly and 24 monthly, with contents and names encrypted from the host.
- What the product must do: A deleted or changed file can be restored off site for the stated retention, the page shows that policy, and the host can read no names or contents.
- Kind: 2
- From: D07-103

### SRV-095: Off-site upload must not starve editors' sync on the studio uplink.
- What was going on: The uplink is about 39 MB/s, shared with editors' sync and downloads; the backup is capped at 12 MB/s by day and 30 MB/s overnight.
- What the product must do: Off-site backup runs under a lower bandwidth cap during working hours than overnight, so editors' transfers keep most of the uplink by day.
- Kind: 3
- From: D07-102

### SRV-096: The off-site copy could not be read without a key kept only on the NAS.
- What was going on: Losing the NAS would also lose the means to decrypt the off-site copy.
- What the product must do: The off-site backup's key is held somewhere other than the NAS, and the product warns until the owner confirms it is stored safely.
- Kind: 3
- State: still open
- From: D07-105

### SRV-097: Restoring from the off-site copy had never been tried.
- What was going on: Recovery means restoring the project library, relinking the timeline to the downloaded proxies as main media and rendering at 1080p.
- What the product must do: A small project is restored and rendered from the off-site copy on a laptop as a rehearsal, and a sample of the backup is verified monthly.
- Kind: 3
- State: still open
- From: D07-106

## Health checks and alerts

### SRV-098: An e-mail's authentication header can be added by any server along the way.
- What was going on: A forged reply could carry a passing authentication header, and a substring search for a message id matched unrelated mail in the Sent folder.
- What the product must do: A mailed reply acts only if the studio's own receiving server vouched for it and its reference matches exactly.
- Kind: 1a
- From: H06-077

### SRV-099: The owner: the server finds and explains its own problems.
- What was going on: He asked to "include as many alerts as possible, make the server as self-diagnosing as possible. Any errors should be flagged, the diagnosis should be as clear as possible."
- What the product must do: Every problem the server can detect reaches a person on the home page and by message, with a plain diagnosis and the next action.
- Kind: 2
- From: P08-007

### SRV-100: The owner: setting up alert mail sent eleven separate e-mails at once.
- What was going on: The owner: "I'm getting spammed with emails now". Each open finding was mailed on its own.
- What the product must do: A person gets at most one alert e-mail per check cycle, a digest listing every new, cleared and still-open finding.
- Kind: 2
- From: C03-062

### SRV-101: The owner: the server checks itself twice a day and he approves fixes by reply.
- What was going on: The owner wanted an assistant to examine alerts and health twice daily, e-mail suggested fixes, and "reply to the email and get it to carry out its suggestions".
- What the product must do: A reply acts only from an authorised, authenticated sender with an unexpired reference, and can only trigger actions the dashboard already offers as buttons.
- Kind: 2
- From: P12-011

### SRV-102: Nobody was told anything, and nothing said nobody would be.
- What was going on: The default alert destination was none, and a destination silent for months looked healthy, so every check reported into an empty room.
- What the product must do: With no alert destination, or none delivered in 30 days, the home and protection pages say "nobody is being told"; an unreadable record shows "cannot verify".
- Kind: 3
- From: L04-061

### SRV-103: Silence from the server cannot tell "all is well" from "server is down".
- What was going on: Every alert is sent by the thing being watched, so a server that is off sends exactly as much as a healthy one.
- What the product must do: An optional daily "all quiet" message, counting computers and problems, lets the owner notice when messages stop.
- Kind: 3
- From: L04-062

### SRV-104: Problems open before alerts were set up were never sent.
- What was going on: Problems found while no destination existed were recorded as already raised, so configuring mail later sent nothing about them.
- What the product must do: When an alert destination is first set, everything currently open is sent at the next check, and the save says so.
- Kind: 3
- From: L04-063

### SRV-105: A mail server that hung stalled every check and restarted the server each round.
- What was going on: Sending alerts had no time limit, so an unanswering mail server or web hook outlasted the server's own stuck-check and triggered a restart.
- What the product must do: Delivering alerts finishes within a fixed budget (two minutes a round), overrunning it is reported as a problem, and a slow mail server never stalls or restarts the server.
- Kind: 3
- From: H07-038, L04-060

### SRV-106: Alert mail was sent without checking the mail server's certificate.
- What was going on: The encrypted mail connection accepted any certificate and any host name.
- What the product must do: Alert mail verifies the mail server's certificate and host name by default, a mismatch names the host, and only an explicit admin setting turns it off.
- Kind: 3
- From: L03-091

### SRV-107: A part not set up on this server was reported as broken and mailed daily.
- What was going on: A new server with folder sync deliberately not configured reported the sync service down and alerted every day.
- What the product must do: A part this site has not set up shows as "not set up", never as down, and raises no alert.
- Kind: 3
- From: H05-065, L06-045

### SRV-108: The "background work stopped" alarm was always on, or never could be.
- What was going on: Liveness was judged against three minutes though a server without folder sync cycles every ten, and only after a successful cycle, so a failing checker still read fresh.
- What the product must do: Background work is judged alive by when it last started a cycle, against the rhythm this server runs; a stopped one alarms within about 20 minutes, a brand-new one reads "cannot tell".
- Kind: 3
- From: L07-031, L06-044

### SRV-109: A dead background worker left the server reporting healthy for hours.
- What was going on: The status worker could die at start on a locked database and never restart, while the health check only tested that a page answered.
- What the product must do: A background worker that dies is restarted, and the server's health check fails while the data it shows is stale.
- Kind: 3
- From: H01-030

### SRV-110: The server reported the folder sync reachable when it was not.
- What was going on: Health counted background rounds that never touch the folder sync as proof it was reachable.
- What the product must do: Health claims a service is reachable only from a round that actually talked to it.
- Kind: 3
- From: L04-074

### SRV-111: Restarting a background worker could leave two of it running.
- What was going on: A stop that timed out forgot the still-running worker, and the restart started a second beside it on the same queue.
- What the product must do: Restarting a background worker never results in two; while the old one is still busy, the restart refuses and says so.
- Kind: 3
- From: L07-054

### SRV-112: The server's own crash reports were written and never read.
- What was going on: Crash reports went into a folder nothing showed, so only someone with a shell on the NAS could know the server had crashed.
- What the product must do: Crashes since the server last started appear as a problem on the dashboard, and an admin can download the recent reports there.
- Kind: 3
- From: L04-080

### SRV-113: The server lost its own network link and nobody heard for a day.
- What was going on: Nothing watched the server's private-network connection, so an expired sign-in produced one vague mail per computer a day later.
- What the product must do: The server alerts once, within minutes, when its own network link is down or its sign-in nears expiry, and when many computers fall silent together.
- Kind: 3
- State: fixed, never shipped
- From: L11-006

### SRV-114: A sync drive left out overnight wrote the same warning thousands of times.
- What was going on: Each owed file move was re-sent and re-answered every 30 seconds per machine, and every answer was logged.
- What the product must do: A repeated identical answer is logged once, and again only when its state or detail changes, including across a server restart.
- Kind: 3
- From: L07-029

### SRV-115: Reporting that the server's store was busy froze the whole dashboard.
- What was going on: The busy report wrote to the busy store itself, and a once-a-minute sign-in touch blocked up to 20 seconds and refused valid sessions.
- What the product must do: When the store is busy, reporting it adds no write and stalls no request, and a valid session is never refused because a background write waited.
- Kind: 3
- From: H06-023

### SRV-116: A busy server made reports wait seconds, and its warning blamed the editors' computers.
- What was going on: With the CPU busy, each report held the database write lock up to 17.6 seconds; the warning blamed the reporting computer and advised unticking projects.
- What the product must do: Reports finish in about a tenth of a second under load, and a slow-write warning measures the lock holder and never blames an editor's computer.
- Kind: 3
- From: P12-065

### SRV-117: Server memory grew without limit as long clips arrived at once.
- What was going on: Each waveform held a whole decoded clip (307 MB for 64 minutes) with no limit on parallel clips, and the server process grew to about 2.6 GB.
- What the product must do: Opening an episode of many two-hour interviews with no waveforms yet keeps server memory under a fixed ceiling, and no single feature can exhaust it.
- Kind: 3
- State: fixed, never shipped
- From: H08-052

## Connections and credentials

### SRV-118: A NAS ships with a self-signed certificate.
- What was going on: Checking the NAS's certificate against the system's trusted authorities always fails, which tempts people to switch checking off.
- What the product must do: The NAS certificate seen at first connection is trusted, a changed one is refused, and turning certificate checking off is never offered.
- Kind: 1a
- State: fixed, never shipped
- From: L11-024

### SRV-119: The setup computer sent the NAS admin password to whatever host answered.
- What was going on: Admin connections accepted any NAS host key, the server held the NAS admin password, and every editor had a full shell on the NAS.
- What the product must do: Admin connections pin the NAS host key and refuse a change, the server holds only a scoped NAS key, and editors' NAS accounts transfer files only.
- Kind: 3
- From: L01-027

### SRV-120: Following a redirect replays a password or key to wherever it points.
- What was going on: A 307 or 308 redirect resends the body unchanged, and custom key headers usually follow; only the standard authorisation header is dropped across hosts.
- What the product must do: No request carrying a password, key or session follows a redirect; a redirect is refused with its status and target named, and nothing is sent on.
- Kind: 3
- From: L06-036, H05-002, M01-079

### SRV-121: A dropped NAS connection must not make a change happen twice.
- What was going on: Retrying after a dropped connection is safe for reads, but a change already sent may have been carried out.
- What the product must do: After a dropped connection the server retries reads and unsent requests once, and never re-sends a change that may already have landed.
- Kind: 3
- State: fixed, never shipped
- From: L11-013

### SRV-122: Installing a sign-in key on the NAS failed but reported success.
- What was going on: The key install reported only its last step's result, so a failed write during rotation printed "installed" while the revoked key stayed.
- What the product must do: Every setup step that changes the NAS stops on the first failure and reads its result back before reporting success.
- Kind: 3
- From: H04-084, L04-007

### SRV-123: Approving a person's second computer locked their first out of the NAS.
- What was going on: Writing an approved key replaced the account's key list instead of adding to it.
- What the product must do: Approving a key keeps every key already on the NAS, so each computer keeps its access, and a key that could not be written stays offered.
- Kind: 3
- From: H07-107, H06-059

### SRV-124: A helper's admin page on the server was open to the network with no login.
- What was going on: Anyone on the private network or LAN could share any project folder to their own device, and a first guard replaced a password the admin had set.
- What the product must do: No admin page the server runs is reachable without a login, and a login the admin already set is kept, never replaced.
- Kind: 3
- State: fixed, never shipped
- From: H07-116, L11-005

## NAS speed, load and clock

### SRV-125: Camera card offloads to the NAS ran far below card, network and disk speeds.
- What was going on: New writes landed on the disks' slow inner tracks in a pool reported half full, and the switch shipped with flow control off, dropping packets.
- What the product must do: Transfer estimates to the NAS use measured throughput, expecting speed to fall with pool fill and concurrent work, never the nominal link speed.
- Kind: 1a
- From: P10-038

### SRV-126: Blackmagic Disk Speed Test showed the NAS writing at only 119 MB/s.
- What was going on: The test writes through the cache, forcing slow committed writes; a normal buffered copy to the same share ran at 758 MB/s.
- What the product must do: Any NAS speed figure the product shows or tests against comes from buffered large-file writes and reads, never write-through or cached reads.
- Kind: 1a
- From: M06-008

### SRV-127: One copy inside the NAS made every share slow to list from that computer.
- What was going on: A NAS-to-NAS copy saturated the disks, and the NAS serves each PC's file sharing through one process, so all its listings queued behind it.
- What the product must do: Big copies between NAS folders are paced so a person's folder browsing on any share never waits more than a few seconds.
- Kind: 1a
- From: P15-016

### SRV-128: A NAS pool about 90% full made every read and listing crawl.
- What was going on: At 90% full (7.8 TB free of 76) listings took over a minute and short audio encodes 150-336 s instead of under one, with the CPU idle.
- What the product must do: The product warns before the NAS pool passes about 80% full, and names fullness as the cause when reads slow down.
- Kind: 1a
- State: outcome not found
- From: P15-014

### SRV-129: A NAS can declare one time zone while its clock and schedules run another.
- What was going on: The NAS's zone file said UTC while its clock and scheduler ran on Taipei time, and the server app had no zone, so a 04:00 job would run eight hours off.
- What the product must do: Every scheduled scan, snapshot and upload fires at the studio's wall-clock time, shown to the owner and checked against the NAS's actual clock, not its zone file.
- Kind: 1a
- From: D07-073, P17-022, M04-074

### SRV-130: A client pulling 2 TB made the NAS's web pages time out.
- What was going on: Big sequential reads collapse the NAS's small-file speed; a 10-second index scan took 390 seconds and pages returned gateway errors.
- What the product must do: Pages stay responsive while large downloads or verifications run, and nothing rescans many files because of one missed page.
- Kind: 3
- From: M05-086

## Sealed

### SRV-S01: The private-network tool's packaged start-up gives up and keeps minting login links.
- What was going on: Started without a key, the stock start-up gives up after 60 s and crash-loops, minting a fresh login link each cycle; publishing fails before login completes.
- What the product must do: A first sign-in to the private network on the NAS shows one stable login link until completed from setup, and publishing is set only afterwards.
- Kind: 1b
- Tool: Tailscale container image (containerboot, LocalAPI, Serve)
- State: fixed, never shipped
- From: C02-002, M03-022

### SRV-S02: An empty private-network member answers "nothing published" with a null body.
- What was going on: Asking for publish settings returns success with a null body, and writing them is accepted even when the network's secure certificates are switched off.
- What the product must do: Read a null answer as "nothing published", and refuse to publish, naming the admin page to fix, while the network's certificates are off.
- Kind: 1b
- Tool: Tailscale (Serve and its local API)
- State: fixed, never shipped
- From: L11-002

### SRV-S03: The server's private-network sign-in expires after 180 days by default.
- What was going on: Expiry, or a NAS update that stops the network service, silences the whole fleet at once.
- What the product must do: The server watches its own network connection, warns 14 days before expiry, and raises one alert when most computers go silent together.
- Kind: 1b
- Tool: Tailscale
- State: fixed, never shipped
- From: H07-120

### SRV-S04: A missing mount source is silently created as an empty administrator-owned folder.
- What was going on: The runtime creates a missing mount source owned by root, which the server's own user cannot write, and the server then fails on permissions.
- What the product must do: Install creates every mounted folder with the server user's ownership before first start, and the server refuses to start on one it cannot write.
- Kind: 1b
- Tool: Docker bind mounts
- From: L01-082, H04-050

### SRV-S05: Restarting the service that owns a shared network strands its neighbours.
- What was going on: When services share one service's network, restarting that owner leaves the others with no network until they restart too.
- What the product must do: After the network-owning service restarts, every service sharing its network is reachable again without a person stepping in.
- Kind: 1b
- Tool: Docker network_mode: service:
- State: outcome not found
- From: C02-003

### SRV-S06: A failed health status does not restart the program.
- What was going on: Restart-on-failure acts only when the process exits; an "unhealthy" status is informational unless something else acts on it.
- What the product must do: The dashboard detects and recovers its own dead background work in process, and its health does not fail just because the NAS sync service is down.
- Kind: 1b
- Tool: Docker restart policies and healthchecks
- From: H04-044

### SRV-S07: Snapshots mounted on demand do not reach a program behind a default mount.
- What was going on: A default mount does not pass on mounts made later under it, so snapshots the NAS mounts on first access stay empty for the server app.
- What the product must do: The snapshot folder is mounted with propagation from the host and setup prints the host-side check, or snapshots are read another way.
- Kind: 1b
- Tool: Docker bind mount of a ZFS .zfs/snapshot directory (slave propagation)
- From: L06-076, H05-088

### SRV-S08: The packaged install's settings file alters passwords with "$" or " #".
- What was going on: The parser interpolates "$", treats " #" as a comment and strips quotes and edge spaces, so the customer's own password was changed.
- What the product must do: The customer's own NAS password works whatever its characters, or the install refuses it naming the exact character.
- Kind: 1b
- Tool: Docker Compose .env files
- From: H04-083

### SRV-S09: A Synology NAS runs an older app engine lacking newer file syntax.
- What was going on: The app manager on a Synology carried an older engine that rejects the optional env-file syntax newer guides use.
- What the product must do: Install files work on the oldest app manager the supported NAS models ship, checked on that version.
- Kind: 1b
- Tool: Docker Compose 2.20.1 on Synology (compose-go v1.16.0)
- From: C02-005

### SRV-S10: An account created the default way refused key sign-in.
- What was going on: On the small Linux base used, an account created with the default locked password field is refused even for key-only sign-in.
- What the product must do: Every file-transfer account created for an editor signs in with its key the first time it is tried.
- Kind: 1b
- Tool: OpenSSH on Alpine Linux (useradd shadow field "!")
- From: C02-004

### SRV-S11: A new database password was announced but the existing database kept the old one.
- What was going on: The packaged database reads its password only when it first creates an empty data folder, so later changes are silently ignored.
- What the product must do: Changing the password on an existing database actually changes it, or the server refuses to start and says so.
- Kind: 1b
- Tool: PostgreSQL container image (POSTGRES_PASSWORD)
- State: fixed, never shipped
- From: L11-026

### SRV-S12: Row-by-row inserts held the write lock for seconds beside a busy thread.
- What was going on: Each row hands back the interpreter lock; a 3,800-row replace took 0.08 s quiet, 28 s beside one busy thread, 181 s beside two.
- What the product must do: Bulk writes go in as one statement, so the write lock is held under a second whatever else the process is doing.
- Kind: 1b
- Tool: Python sqlite3 module (executemany under the GIL)
- From: C04-024, L10-071, P12-066

### SRV-S13: Picking the newest saved database copy by name chose a journal file.
- What was going on: The database keeps files ending -wal and -shm beside each copy, so choosing the newest previous copy by name picked one of those.
- What the product must do: A rollback picks only whole database copies and refuses journal files.
- Kind: 1b
- Tool: SQLite
- From: L10-046

### SRV-S14: The HTTP library re-sends custom key headers and form bodies across redirects.
- What was going on: On a cross-host redirect the library drops only the standard authorisation header; a form body and any custom key header go to the new host.
- What the product must do: Every request carrying a credential in a body or custom header turns redirect-following off explicitly and refuses any redirect response.
- Kind: 1b
- Tool: Python requests and urllib urlopen
- From: L06-037

### SRV-S15: Upgrading a mail connection to encryption checked neither host nor certificate.
- What was going on: Upgrading the connection without an explicit context verifies neither the host name nor the certificate.
- What the product must do: Alert mail verifies the mail server's certificate and host name, with only an explicit admin opt-out for a self-signed relay.
- Kind: 1b
- Tool: Python smtplib starttls()
- From: H04-086

### SRV-S16: The owner's own e-mailed reply was never read, then refused.
- What was going on: Mail the studio account sends to its own plus-address arrives already marked read and carries no authentication results, because it never leaves the provider.
- What the product must do: Replies are read whatever their read state, handled exactly once, and a self-sent reply is accepted when the same message sits in that account's Sent folder.
- Kind: 1b
- Tool: Gmail / Google Workspace mailbox read over IMAP
- From: P12-012, C04-001

### SRV-S17: Deleting the replaced assistant version broke calls still running.
- What was going on: The command-line assistant re-launches itself by its own file path, so deleting the old version broke calls in flight, which can last 15 minutes.
- What the product must do: An update keeps the previous version on disk for at least an hour after switching, then removes it.
- Kind: 1b
- Tool: Claude Code CLI
- From: L10-028

### SRV-S18: The assistant's command-line tool took 50 seconds to start on a busy NAS.
- What was going on: A cold version check took 50 s against a 10 s limit, and an expired sign-in left a credential file without a refresh token that still looked present.
- What the product must do: Allow at least 90 s for a cold start, keep the last good answer on a timeout, and treat a credential with no refresh token as signed out.
- Kind: 1b
- Tool: Claude Code CLI
- From: C04-022

### SRV-S19: The NAS's catalog sync app makes its own key and stores settings outside snapshots.
- What was going on: On TrueNAS the catalog app generates its own access key and keeps device pairings and shares in an app volume no dataset snapshot covers.
- What the product must do: Setup reads the sync tool's key from the app instead of asking the owner to invent one, and the backup page lists its settings as not covered.
- Kind: 1b
- Tool: Syncthing (TrueNAS catalog app)
- From: L05-003

### SRV-S20: The cloud storage box accepts only about 1.5 new files a second.
- What was going on: The box took about 1.5 new files a second per account at any parallelism; packed, 2,000 tiny files took 21 s instead of 20 minutes.
- What the product must do: Many small files reach that storage packed into large objects, so a backup of 90,000 small files finishes in minutes.
- Kind: 1b
- Tool: Hetzner Storage Box (packing via restic)
- From: D07-099, M04-097

### SRV-S21: Cloud storage prices for about 3.4 TB of proxies and project files.
- What was going on: A 5 TB storage box cost 13 euros a month and another store about $20; one store bills deletions for 90 days, so unticking projects costs money.
- What the product must do: Cloud backup cost is checked against data size and deletion rules; a store billing early deletion is unsuitable when projects are often dropped.
- Kind: 1b
- Tool: Hetzner Storage Box, Backblaze B2, Wasabi
- From: D07-098

### SRV-S22: One bulk import used up a hosted database's daily allowance for every app.
- What was going on: The free tier shares 100,000 row writes and 5 million reads a day across all databases; one import or full-scan update used it until midnight UTC.
- What the product must do: Estimate rows written and read before any bulk job, send only changes, and test query plans on data of real size.
- Kind: 1b
- Tool: Cloudflare D1
- From: M04-098

## Removed
