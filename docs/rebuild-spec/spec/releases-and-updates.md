# Releases and updates

This is how a new version of CC Sync reaches the server and every editor's computer, and how everyone can tell which version runs where. The vendor publishes a version once, signed with a key only the vendor holds, and it reaches every kind of computer the product supports. A studio's admin decides how much of what the vendor offers the studio takes by itself, tries a new version on one computer before every computer is offered it, sees which computer runs which version, pushes or holds an update, and rolls back. An editor is offered an update in the app on their computer, installs it with one confirmation, and is never left with a broken app or interrupted work. Nothing here can be switched off: every site, whatever parts it has switched on, takes its versions this way.

## Installing an update on an editor's computer

### An editor installs an offered version with one confirmation

When the app offers a different version (see "The app shows the offer and says whether it is an update, a rollback or a switch"), the editor chooses it and is asked to confirm. The window's title carries the studio's brand.

| The offered version is | Heading | Question | Button |
|---|---|---|---|
| newer | ► UPDATE CC SYNC | "Update to v<version>? CC Sync will restart itself." | UPDATE |
| older | ► ROLL BACK CC SYNC | "Roll back to v<version>? That is OLDER than the v<current> on this computer. You would LOSE whatever v<current> fixed. CC Sync will restart itself." | ROLL BACK |
| not comparable | ► SWITCH CC SYNC | "Switch to v<version>? You are running v<current>. CC Sync will restart itself." | SWITCH |

- The release notes follow under "What is new in v<version>:", up to 1,200 characters, cleaned of control characters and runs of spaces.
- If anything is syncing: "A sync is currently running. It will resume automatically after the restart."
- Buttons CANCEL and the action. Enter confirms. Closing the window cancels.
- If the window cannot be opened, nothing is installed: "Couldn't open the update window, so nothing was changed. Restart CC Sync and try again."
- With no offer, choosing it does nothing.
- Only the installed app updates itself. A copy run by the people building the product says so and does nothing.
- Only one install runs at a time. A second click while one runs does nothing.
- Who: the editor at their own computer.
- Ways in: the app's menu, and the same button in the app's settings window.

### An update waits until it will harm no work in progress

An update, however it was started (the editor's click, an admin's push, or an unattended update), never interrupts work it would harm.

- While a window of the app is open: "Can't update while a CC Sync window is open. Close it and try again."
- While media is being copied in: "Can't update while media is being copied in. Let it finish, then try again."
- Uploads, downloads and shared heavy work in progress either reach a point where they can stop safely, or resume after the restart exactly where they stopped. An upload that has run for hours is never thrown away by an update.
- An update started by the editor shows these refusals at once. An update started by an admin's push or by unattended updating shows them once, the first time, and then waits quietly: it tries again by itself about 90 seconds later while work is open, and about 10 minutes later after a failed download. It stops trying once the computer runs that version or a newer one, or the offer is withdrawn.
- On its own: an unattended or pushed update holds back while work would be harmed, from the open windows, copies in progress and transfers on this computer.

### Installing replaces the app and keeps the previous version until the new one has proved healthy

Once nothing would be harmed, the editor sees "Installing v<version>…". The app downloads the version, checks it, puts it in place of the running app and restarts.

- The new version is started and given up to 30 seconds to say it has started. If it exits first, everything is put back and the previous version keeps running. If it is running but silent at 30 seconds, the previous one stands down anyway.
- After an update exactly one copy of the app is running, however long the previous copy takes to stop in the middle of a transfer. Success is reported only when the new version is still running a few seconds after it started. Otherwise the editor is told "Update failed. You're still on v<current>, nothing is broken." with how to get help (copy the diagnostics for the admin from the app's settings window), and the version still running is named.
- If the program cannot be replaced (for example antivirus holds the file), the update fails, says what holds the file, and is never counted as installed.
- If putting the previous version back itself fails, the app's log names where the previous version is so a person can restore it by hand.
- The previous version is kept until the new one has had a check-in accepted by the server and has been running 10 minutes, or has been running an hour when the server cannot be reached. If the app stops sooner it is kept to the next start.
- The server is told why an attempt failed, in one of these words: the download failed, the contents did not match, no space, refused, the swap failed, the new version would not start, or it kept crashing and was rolled back.
- Windows and macOS: on macOS the new program is written to a new file and renamed over the previous one, never copied over it in place (see "Facts about macOS").

### The editor is told when an update has completed

The first start on a new version, other than a first-ever install, tells the editor that the update to v<version> has completed.

- If the computer cannot keep its record of starts and versions, the app warns the editor and names where it could not write, and the server is told how many writes failed. That is never treated as "nothing is known" about crashes.

### An update is downloaded only from the studio's own server, whole, and only when there is room

- The download comes from the same address as the server the computer checks in with. Anything else is refused. A redirect is refused and nothing is re-sent.
- The connection follows the same rule as every other call the app makes to the server: secure, or plain to an address that is on the studio's own network.
- At least 200 MB plus the version's size must be free on the computer, or the attempt fails as "no space".
- A download larger than its stated size (or 300 MiB when no size is given) is abandoned. One whose contents do not match the vendor's signed record is thrown away.

### A failed update is tried again less and less often and then given up on

- After a failed attempt at a version, the next unattended attempt waits at least 10 minutes, then 1 hour, then 6 hours between each. This is remembered across restarts.
- After 8 failures at the same version, the computer stops trying it by itself, whether from unattended updating or an admin's push. The app's menu and the server say so, with the reason. The editor can still choose it from the menu.
- A different version starts the count again. Reaching the version clears it.
- An offer the computer will not install (for example one below its floor, see "Every version sets a floor no computer goes below") waits on the same curve, does not count as a failure, and the refusal and its reason are told to the server.
- A version this computer went back from because it kept crashing is never installed unattended again (see "A new version that keeps crashing puts the previous one back by itself").
- An admin's push waits at most 14 days (see "An admin pushes a version to one computer").

### An update cut off halfway still leaves an app that starts

If an update is interrupted at any point (the computer loses power, the app is killed), the computer is left with a program that starts at sign-in. When the app's program is missing and the previous version is still there, the previous version is put back so there is something to start, with no person renaming files. Recovery never overwrites an app that is present. With nothing at all to start, nothing is relaunched, and the editor sees that the app is not running.

### Anyone signed in can download the app and the installer

A person signed in to the dashboard, or a computer with the studio's credentials, may download any version the studio holds, or ask for "current" (in any letter case) to get the current version of that kind for that operating system. This is how a new editor gets the installer.

- Neither signed in nor a computer with credentials: told to sign in.
- A computer whose person's account is removed, suspended or disabled: refused with the account's sentence (see Accounts, privacy and the legal paperwork: How a computer proves who it belongs to).
- Nothing current: "no current <platform> <kind> is published".
- An unknown version: refused as unknown.
- The file is missing on the server: "the file for that version is missing on the server".
- The download carries its checksum, version and signature details, so a first install that cannot check a signature itself can still check the file is whole and refuse a source that is not signed.
- The file name the person downloads is made from the kind, operating system and version.
- Who: anyone signed in, and every computer of the studio.

### The Timeline Cards app on an Android phone updates itself from the server

On a computer, Timeline Cards opens from the one app on that computer and updates with it: there is no separate Timeline Cards program to install or update there. On an Android phone, Timeline Cards is an installed app of its own, carrying the product's mark, and it checks the studio's server for a newer version and installs it. The check needs the editor to be signed in. With no version of the app on the server, the app is told "no app builds have been published". Only the version listed as the newest can be downloaded. Anything else is "no such app build", and a listed version whose file is missing is "that build is listed but missing". Nothing about the check is kept by the device's browser between checks.

Section **UPDATES**: "New versions of this app are published on the server. Checking needs the server, and you signed in." **Check for update** then: "this is the newest version (<v>)" or "version <v> is available (this is <current>)" with **Install <v>**. Installing: "installing <v>: confirm on the screen Android shows". Errors: "set the server first", "you are working offline: go back online to check for an update", "this server has no app builds published", "sign in first", "the server answered <code>", "this build cannot install updates", "the download did not match its checksum: try again", "the server stopped answering" (after 30 s), plus two messages for a broken list of published builds.

{{33-107}}

An update published without a checksum is refused ("this update carries no checksum, so it was not installed: publish it again"), and a download that does not match its checksum is deleted. The checksum proves the download arrived whole. The update is installed only when it also carries the vendor's signature (see "Nothing is installed that the vendor did not sign"), and Android itself replaces the app only when it is signed with the app's own key (see "Facts about Android").

- Exact: yes
- When Timeline Cards is off: the app's updates are not offered and the check answers that no app builds have been published.
- Phone and desk: on a computer Timeline Cards updates with the one app. On an Android phone the person confirms on Android's own screen, and first allows the app to install apps.

#### Lessons

- Met: APP-067, APP-068, APP-069, REL-046, REL-047, REL-048, REL-049, REL-050, REL-051, REL-052, REL-053, REL-054.

## Facts about Windows, macOS and the NAS that bite an update

### Facts about Windows

- A program without a valid code signature meets the SmartScreen warning on every fresh install and may be quarantined by antivirus. So every Windows program a person runs, the installer and first-run set-up included, ships code-signed, and the signature carries a timestamp so it outlives the certificate. A version whose Windows program is not code-signed is marked so wherever it is listed, and making it the one every computer is offered needs a deliberate confirmation.
- Antivirus can hold a newly installed program. An update that cannot replace the program fails and says what holds the file (see "Installing replaces the app and keeps the previous version until the new one has proved healthy").
- A stock Windows install refuses to run script files directly. Nothing a person is told to run requires them to change Windows' script policy first.
- Each Windows program carries its file details: the product name CC Sync, the vendor's legal entity as company and copyright holder, a description, and its version.

### Facts about macOS

- A new Mac program copied over the previous file is killed at launch. Every install or update on macOS writes the new program to a new file and renames it over the previous one.
- An update must keep the app's permissions on the Mac (its access to the disk) and its ability to start at sign-in. A launch macOS refuses is shown to someone, never silent.
- An app without a Developer ID signature meets Gatekeeper's "cannot be opened because the developer cannot be verified". On Apple silicon an app with no signature at all is killed at launch, so such a version is never published. A signed version that is not notarised is warned about at release. The Mac app and installer are signed throughout: a nested unsigned or altered part, or packing that broke the signature, stops the release ("Do NOT publish it").
- A Mac version that does not run natively on Apple silicon is warned about at release.
- A Mac installer handed over by hand (USB stick, AirDrop, a copy) arrives quarantined and needs System Settings > Privacy & Security > "Open Anyway".

### Facts about the NAS and the share

- A file someone has open over the share cannot be replaced. Anything that must replace a file on the share fails loudly and names the file.
- A script written with Windows line endings fails on a Mac and on the NAS, and can take the server down with it. No version is released while any file meant to run on macOS or on the NAS has Windows line endings or lacks permission to run.
- Some server updates need the server's installation renewed in the NAS's own app manager (see "Some server updates need the installation renewed on the NAS"). When the vendor names an exact installation to use, the admin must edit the server's project in the app manager and paste the exact references given: pressing Update or Build alone fetches the installation it was fixed to again. On Synology this is the app manager's Project, then Edit. On TrueNAS it is Apps, then Edit. Otherwise it is the NAS's own app manager. When no exact installation is named, the admin presses Build (Synology) or Update (TrueNAS) in the app manager.

### Facts about Android

Android replaces an installed app in place, keeping its offline data, only when the update is signed with the same key as the installed one. The first version made creates that key (valid 100 years), and the vendor is told it must be backed up: losing it means the app can never be updated in place again, only removed and installed afresh.

#### Lessons

- Met: REL-001, REL-002, REL-003, REL-004, REL-005, REL-006, REL-007.

## Version numbers

### Every version is three plain numbers and means one set of bytes

- A version of the app on the editor's computer, of the installer and of the server is exactly three numbers separated by dots ("version must look like 1.2.3"). Anything else is refused when it is published.
- The installer states one version, the same on Windows and on macOS.
- One version always means one set of bytes, everywhere. Publishing the identical bytes again changes nothing ("already published at this version, with these exact bytes"). Publishing different bytes under a version already published is refused ("bump the version"). A server version once released is never rebuilt. The studio tests exactly what customers receive.
- Versions are compared number by number, by one rule everywhere: a later number in any part is newer, so 1.10 is newer than 1.9. A version that is not made of numbers and dots counts as older than every real version.
- A version made from unfinished, unsaved work carries a mark after its number. For finishing an admin's push it counts as its number, but it never counts as newer than the clean version of the same number.
- A minimum version or floor that does not read as a version is refused when it is set, never stored to refuse every computer later.

### During the beta every version stays below 1.0.0

Every version released during the beta is a pre-release version, below 1.0.0. Nothing raises it to 1.0.0 without the owner's explicit decision to launch the paid release.

### An admin sees exactly which version the server runs

The server shows an admin, and its health information carries, the version it runs, the version its installation on the NAS holds where the two differ, and an identifier of the exact build it was made from. When the build cannot be identified (for example it was made from unfinished work) the identifier is shown as unknown, never guessed.

- Who: an admin.

#### Lessons

- Met: REL-010, REL-008, REL-009, YTD-096.

## Signing and trust

### Nothing is installed that the vendor did not sign

Every version the product hands to a computer, and every server update, carries the vendor's signature over what it is: its kind (the app on the editor's computer, the installer, the Timeline Cards app, a server update), its operating system, its version, its file name, its fingerprint, its size, its floor (see "Every version sets a floor no computer goes below"), when it was published, whether the program carries the operating system's code signature, and, where they apply, the processor it is for and the oldest server it works with. The signature is made on the vendor's release computer. The server can check a signature but can never make one.

Every app the product installs checks each offer when it arrives, before it is shown, and refuses it when:

- it is not signed with one of the vendor's keys built into the version the computer is running, whatever address it came from;
- it is a version of something other than this app (an installer offered as an update, for example);
- it is for another operating system;
- it claims to need a newer version than itself (a malformed record, which changes nothing);
- it is below this computer's floor.

A refused offer is never shown to the editor. The server is told the refused version, the reason and when, until the computer runs that version or the server stops offering it.

The server likewise accepts a version only when it is signed by a key the server holds. A signature refusal says what was wrong: not readable, the wrong length, or "no vendor key held here verifies this record". Two versions that cannot be compared are treated as a refusal, never as fine. With no key held, every check fails and the server says so.

- Who: nobody can override this. There is no way to make an unsigned version reach an editor's computer.

### The vendor's signing key is kept offline and protected

The key that signs every version is a private key on the vendor's release computer. It never leaves that computer and is never used by any automatic build: versions may be built anywhere, but they are signed only there, after the version has been checked there.

The vendor can:

- create a key, never overwriting an existing one by accident ("overwriting it orphans every version the fleet was ever offered"). A forced replacement keeps the previous key aside;
- protect it with a passphrase of at least 12 characters, typed twice. The protected copy is checked before the unprotected one is destroyed. Signing asks for the passphrase every time;
- see its public half and a short identifier, and every key a change of key in progress involves;
- check that it unlocks;
- back it up to a file or print it, which records when and where. The vendor is then asked to confirm on the dashboard "I have backed it up".

An unprotected key prints a warning every time it is used. A wrong passphrase or an altered file: "cannot unlock: wrong passphrase, or the key file was altered". A damaged key is restored from either backup. After creating a key the vendor is told to protect it and back it up now, with two offline copies and the passphrase written down elsewhere. Every release reminds the vendor while a backup is missing. A written plan says what to do if the key is stolen.

- Who: the vendor.

### Changing the signing key never strands a computer

A computer trusts only the keys built into the version it already runs. So:

- a version carrying no trusted key would refuse every update for ever, and is refused at release;
- a version is refused at release when the key that will sign it is not among the keys built into it ("every editor would refuse the version you are about to publish");
- changing the key takes an overlap: first a version that trusts both the previous and the new key, signed with the previous key, and only once that version is on every computer does the new key sign. Publishing a version signed by a key the current version does not trust is refused, with this explained.

Several vendor keys may be trusted at once for this overlap, each shown by its short identifier.

- Who: the vendor.

### Every site trusts the vendor's key out of the box

A studio's server holds the vendor's public key from the moment it is installed, so it accepts the vendor's versions with nothing for the studio to do. A key the site deliberately supplies wins over the vendor's.

- The set-up and settings show "Signing key for updates": "The key this server checks every CC Sync version against." It reads "the vendor's signing key is in place: this server only accepts versions the vendor signed", or "N signing key(s) held" (the key itself is never shown).
- With none: "no signing key: this server refuses every version until it holds the vendor's public signing key, so your editors' computers can never be updated from here. Do not make a key of your own: paste the vendor's in the box and save. Skipping means updates wait until you do."
- A pasted value that is not a key is refused: "it should be 44 characters of letters and digits ending in =". It is refused when it is pasted and when the server is installed, before anything on the NAS changes, with the reason: the server would otherwise ignore it and refuse every vendor version and every update.
- A customer is warned never to make a key of their own: a key of their own refuses every vendor version and cuts the site off from the vendor's updates.
- Only the vendor is ever asked to back up the signing key. A site whose key is the vendor's is never asked, and the server can tell whether every key it holds is the vendor's.
- Setting: Signing key for updates. Does: the key every version the server accepts must be signed with. Default: the vendor's public key. Who: an admin. Applies to: the site. Search words: signing key, release key, trust, vendor key, updates.

### Setting up a Mac checks the app it downloads

A Mac being set up by hand fetches the app from the studio's server, using the computer's key: the current Mac version by default, or a named one. It is not installed when the download fails (a wrong key, no route to the server, or no Mac version published), when the server served it without the vendor's signature, or when its fingerprint does not match the one stated, with "Tell the admin: either the published version is corrupt or something is rewriting the download." With no key, an app already on the Mac is left as it is and not checked for updates. With no app at all, a boxed warning says "THE SYNC APP IS NOT INSTALLED ON THIS MAC" and what will not work: no syncing in either direction, no checking in, no project picking.

- Windows and macOS: the Windows installer carries the app inside it and copies it in. The Mac's hand-run set-up downloads it.

### A server update is checked and tried before it replaces anything

A server update is downloaded only over a secure connection, is at most 256 MiB, must arrive within ten minutes, and must match exactly what the vendor signed. Anything else is refused with the reason. Its contents are checked file by file against what the vendor listed, and anything unsafe or unlisted refuses the whole update. The new version is then started against copies of the studio's data, within ten minutes, and must bring them up to date without error. If it cannot, the update is refused with the failed checks named and "Nothing was swapped". Only then does the server switch to it. A server version that can no longer be verified as signed by the vendor is never started.

### The server believes only a release list the vendor signed, and refuses an earlier one played back

- The vendor's list of versions, and every version in it, must carry a valid vendor signature.
- The list is fetched only over secure connections at every hop (a redirect to an insecure address is refused), sends no credential of any kind, and is limited in size.
- A list older than the newest one the server has ever accepted is refused as "a possible replay of an earlier list", and nothing changes. A list's date never goes backwards: when the vendor publishes, a wrong clock on the vendor's computer is caught and named.
- Versions without a valid signature, versions that claim a minimum above their own, and versions the vendor has recalled are dropped.
- Versions the list describes in a form this server cannot use are reported: the check still succeeds, but it reads "N record(s) in the list are not offered here: ... The vendor has to publish them again." (up to five named).
- A list held at an address with a query string still finds its signature. When the signature cannot be found, the error explains why and names the address tried.
- Records stay readable and verifiable by every version of the app still checking in. New details added to a record never make an earlier app refuse it. The one line of release notes shown in an offer is outside the signature, so changing it never changes what a computer verifies.

#### Lessons

- Met: REL-011, REL-012, REL-013, REL-014, REL-015, REL-016, REL-017, REL-018, REL-019.

## Making and publishing a release

### The vendor publishes a version once and it reaches every kind of computer

There is one way to publish a new version. The vendor starts it with one command at the vendor's release computer, naming the version. It covers every kind of computer the product supports: the app on the editor's computer for Windows and for macOS (on both kinds of Mac processor), the installer that sets up a new computer for each, the Timeline Cards app for Android phones, the server's update when the server changed, and any large file a part needs once (such as what music search needs to understand a description of a track).

What the vendor gets:

- Everything is checked before anything moves (see "A release is refused before anything moves when something is wrong").
- Each program is built, started once in exactly the form it ships in, and must pass its own self-test within three minutes before it is signed. A version that fails at any step is never published, and every version published contains exactly what was built for it.
- Everything is signed on the vendor's release computer, after it is checked there, and checked again straight after signing.
- The app carries the same version number on every operating system. A release whose platforms disagree is refused.
- The installer for each operating system always sets up the app version that is current for that operating system. When a release carries both, they become current together, and only once both have arrived whole.
- The version goes to the vendor's own studio first, as it goes to any site, and reaches customer sites only after it has run there (see "Customer sites are offered a version only after it has run a day at the vendor's studio").
- A release can carry one line of what changed, shown to the editor in the offer (see "The app shows the offer and says whether it is an update, a rollback or a switch").
- Each line the release prints is labelled as coming from the release. A failure is printed in red with its reason, a warning in yellow. The release ends with one line per operating system at the vendor's studio: "N of M computers on <version>", how many are behind and how many are refusing it. It ends saying plainly whether it fully succeeded, was refused or failed (and nothing past that point happened), or was published but is held back.
- A release that stopped part way can be run again: it completes what is missing without redoing or changing anything already published, and says how far the last run got. Running it again after the version has changed is a new release, not a completion.
- A trial run checks everything and changes nothing.
- Who: the vendor.

### The vendor sees before publishing whether a release makes syncing slower

Before a version is published, the same measurements of how fast footage travels that chose the way footage moves are run again with the new version: camera originals going up, proxies and originals coming down, and many small project files kept in step, between the studio's server and real editors' computers on the studio's own network, on a home connection in the same country and in other countries, on Windows and on macOS. The vendor is shown the results beside those of the version before, for each kind of transfer and each computer, with every one that got slower marked. A release that makes syncing slower is caught before it ships: the vendor sees it before anything is published, and publishing it anyway is a deliberate, named choice.

- Who: the vendor.

### A release is refused before anything moves when something is wrong

Every refusal a release can meet is checked before its first long or irreversible step, each with a sentence saying what to do:

- the signing key's passphrase is wrong (asked once, with hidden typing, before anything moves);
- the version, for any of its kinds, is already published with different bytes ("bump the version");
- the version is not above every version already published for that kind, unless the vendor deliberately names it as a rollback;
- an automated check failed on exactly this change, or did not run (a skipped check is not a pass), on Windows or on macOS;
- the version is made from unfinished, unsaved work, unless the vendor deliberately overrides. Such a version is marked as made from unfinished work wherever it is listed, is held back at the vendor's studio unless the vendor overrides a second, separate time to make it current there, and never reaches a customer site. A Mac installer built from it warns "do not hand this installer to an editor";
- no code-signing identity is set up for Windows or macOS, unless the vendor deliberately accepts an unsigned version, which is then marked and printed in a boxed "UNSIGNED VERSION" warning about the operating systems' warnings;
- a file meant to run on macOS or the NAS has Windows line endings or lacks permission to run;
- an operating system or processor is named that no computer asks for;
- the signing key is not among the keys built into the version, or the floor is above the version (see "Changing the signing key never strands a computer" and "Every version sets a floor no computer goes below").

A note, never a refusal, reminds the vendor when the signing key has no recorded backup. Each override is a deliberate, named choice.

- Who: the vendor.

### A version reaches a site whole or not at all

The same rules apply however a version arrives at a site: brought by an admin's button, or taken by the site by itself from the vendor's list.

- Refused when its floor is above its own version: every computer that saw the offer would raise its floor above the version and then refuse it. Nothing is published, and the vendor must sign it again with a floor at or below its version.
- Refused when the signature does not cover exactly what arrived: "signature REJECTED (<detail>): nothing was published. The signature must cover this exact record."
- The same version with the same contents: "already held at this version, with these exact bytes." With different contents: "<kind> <version> for <platform> is already held on this server, from different bytes. Nothing on disk was replaced. The vendor has to publish this under a new version number." Both short fingerprints are shown.
- Larger than 200 MiB, or taking more than ten minutes, or not over a secure connection: refused. Empty, or not matching its checksum: "the download was corrupted, and nothing was published".
- Short of space: the server's data disk must have three times the version's size plus 256 MiB free: "not enough free space on the server's data disk: N MiB free, this version needs about M MiB. Older versions are cleared when a new one arrives (the current one and the two newest others are kept): free some space and try again." When free space cannot be measured there is no refusal.
- A transfer cut off midway leaves nothing behind. Two arriving at once cannot spoil each other. A version becomes visible only once all its files are present and match.
- When a version arrives, older versions of the same kind and operating system are cleared, keeping the current one and the two newest others. A cleared version goes to the server's trash for 30 days, like a deletion (see "An admin deletes a version that is not current").
- Every arrival is recorded among admin actions, naming the admin who brought it, or "the vendor's list" when the site took it by itself.

When the vendor publishes to the vendor's list:

- a live list that does not verify is refused ("either the list was tampered with, or it was signed by a key this copy does not know"). A list that cannot be read is refused, never assumed empty. Only a list that does not exist yet is a first publish;
- publishing merges into the live list and never drops a version already published, except one deliberately recalled. Anything that would drop one is refused, naming it;
- a recalled version can never be published again;
- an interrupted publish leaves either the previous list or the complete new one, and running it again completes it.

### The server keeps a record of every version it holds

For each version the server keeps: its kind (the app, the installer, the Timeline Cards app, the server), version, operating system, processor, file name, fingerprint, size, when and by whom it was signed, its signature and which key signed it, its floor, whether the program carries the operating system's code signature, whether it is held back or current, since when, when it was made current, whether it was ever current, the server version it needs, the change it was built from and whether that was finished work, when and why it was recalled, and a one-line note of what changed.

- One record per kind, operating system and version. A new version always arrives held back.
- The note is folded to one line, cut to 300 characters, and is not covered by the signature.
- Only the change it was built from can be corrected afterwards. Nothing signed can be. A "made from unfinished work" mark that the vendor's list later says is finished is cleared, never set.

#### Lessons

- Met: REL-020, REL-021, REL-022, REL-023, REL-024, REL-025, REL-026, REL-027, REL-028, REL-029, REL-030, REL-031, REL-032.

## Trying a build on one computer first

### A new version is held back until one computer has run it for the trial time

However a version arrives, it is held back: kept on the server, offered to nobody. A held-back version of the app may become current only once at least one computer has run it for the trial time, 30 minutes by default, with no crash and without going back.

- The server notes the time each computer first checks in on a version. For a version and operating system, it looks at every computer checking in on exactly that version: how long it has run it, its crash count, when its newest crash was written, and whether it went back.
- A computer's crashes count as "none" when it has none recorded or its newest crash was written before it started this version, "some" otherwise, and "unknown" when either cannot be read. Only real crashes after the version started there count. A deliberate restart or a stop for an update never counts. Every "unknown" counts against passing.
- A refusal reads "<version> has not finished its trial yet: <reason> Make it current anyway by confirming the override.", where the reason is one of:
  - "no computer has run <version> yet. Push it to one computer first, leave it for N min, then make it current."
  - "R of the M computers on <version> had to go back off it because it kept crashing."
  - "M computers on <version> have reported C crash(es), and K of those computers have crashed since <version> started running there."
  - "C crash(es) are on record on the M computers on <version> and nothing says when they were written, so they cannot be told apart from this version's."
  - "no computer on <version> has reported its crash count, so nothing here says the version stays up."
  - "M computers have been on <version> for T min, the trial is N min.", with "The C crash(es) on record there were all written before <version> started running, so none of them are its." when that is so.
- The admin overrides only by typing the exact version into the confirmation box. Without it: "to override the trial, type the version number (<version>) into the confirmation box. Nothing changed."
- No trial is needed for a version that has been current before (going back), for a site's very first version, and, when the site acts by itself, for a version older than the current one (a vendor withdrawal). The installer has no trial.
- When a version is asked to become current as it arrives and that is refused, it is still kept, held back, with "kept and HELD BACK: push it to one computer, let it run, then MAKE CURRENT. <reason>".
- On its own: whether a version has passed its trial, from the check-ins of the computers running it.
- By hand: the admin sees the trial's state on the version (see "An admin tries a held-back version on one computer") and can override by typing the version.
- Setting: Trial time for a new version. Does: how long at least one computer must run a new version of the app without crashing before every computer can be offered it. 0 turns the trial off. Default: 30 minutes. Who: an admin. Applies to: the site. Search words: trial, soak, new version, test first, staged.

### An admin tries a held-back version on one computer

Each held-back version of the app that is not recalled shows its trial: "on trial: N computer(s) on <version> for N min, N crashes (none since <version> started there / N computer(s) crashed since <version> started there), N went back (trial N min)".

- "push to one computer" picks a computer of that operating system ("<person>/<computer> (<version>)") and asks it to take exactly this version on its next check-in. The version is offered to that computer alone until it runs it or the push is withdrawn. Refusals: "pick a computer to push this version to", "no <platform> app version <version> is held here", "no computer '<computer>' for '<person>'".
- "make current" is refused until one computer has run it for the trial time, and the refusal says so beside the version.
- "make current anyway" appears only while the trial time is not met, and needs the version typed in.
- Who: an admin.

### An admin makes a version current

For the app, current means the version every computer of that operating system is offered. For the installer, it means what a new editor downloads. There is exactly one current version per kind and operating system: making one current puts the previous one back to held, sets "made current at" to now (making a version current again restarts that clock), and marks it as having been current.

Every way of making a version current passes the same checks, in this order, and a refusal says why and leaves the current version as it was:

- no such version: refused;
- recalled by the vendor: "<kind> <version> was RECALLED by the vendor[: reason]. It cannot be made current. Move the computers back to a version that was not recalled." No override;
- needs a newer server (or its need cannot be read): "<kind> <version> needs server <x> and this server is <y>. Update the server first, then make this version current." No override;
- a version that was current before passes (it is a rollback);
- the trial, for the app only (see "A new version is held back until one computer has run it for the trial time").

Every button shows that it is busy and is disabled the moment it is pressed. A refusal appears where the admin clicked. Every change of current version, by an admin or by the site itself, is recorded among admin actions, with whether it was overridden.

- Who: an admin.
- Ways in: from a held-back version in the list of versions, from the choice of an earlier version to go back to, and from the list of what the vendor offers.

#### Lessons

- Met: REL-037, REL-038, REL-033, REL-034, REL-035, REL-036, REL-039.

## Offering an update to a computer

### Each computer is offered the version it should run, or told why not

A computer is offered a version when it has said which operating system and processor it runs and which version of the app, and that version differs from the one to offer. "Differs", not "is older": an earlier version an admin made current is offered exactly like an update. The version offered is the current one for its operating system, except that a computer with a pushed version waiting is offered that version, even when it is held back. Every computer checking in is offered a newly current version on its next check-in, within minutes.

The offer is held back, and the computer is given the reason instead, when:

- the version was recalled: "that version was recalled by the vendor";
- the version needs a newer server: "that version needs a newer server than this one";
- the version and the computer name different processors, unless the version is made for both kinds of Mac processor: "that version was made for a different processor than this computer";
- no version exists for the computer's operating system and processor. The server shows "No <platform>/<processor> version published: N computer(s) report that processor and the current version is for a different one, so they are offered nothing rather than a program that cannot run."
- the computer has not said which operating system it runs: it is shown as unknown and offered nothing.

A computer is offered an older version only after an admin chose to go back to it. The server says when its current version is older than versions computers run.

When a new version is waiting but needs a newer server than this one, it is never offered to the computers, and the admin sees the problem: "A new CC Sync version for <platform> (<version>) is waiting but cannot be handed to the computers here: it needs server <x> and this server is <y>. Until the server is updated, every computer stays on the version it has." The next step reads "update the server from the vendor. The new version is offered to the computers straight after." It clears by itself once that is no longer so. Whether the computers are up to date is measured against what the vendor offers, never only against what this server holds.

- On its own: which version each computer is offered, from its operating system, processor and version, the site's current version and any push waiting.
- By hand: the admin makes a version current, pushes one to a computer, or moves the computers back.

### The server and the computers never work together at versions that do not match

Each version of the app names the oldest server it works with, inside its signature, and is never offered to a computer whose server is older (see "Each computer is offered the version it should run, or told why not"). The vendor's release refuses a version that needs a newer server than any server version the vendor offers. When the server is newer or older than something a computer sends, both keep working: a computer learns the server's version from every answer it gets and sends only what that server understands, and a part the server cannot read never costs the rest of what the computer sent. When the computers send something this server is too old to read, the admin is told plainly to update the server (see "The server tells an admin when versions are not reaching computers"). When an editor's computer must update before something will work, the editor is told so in those words.

### The app shows the offer and says whether it is an update, a rollback or a switch

The app shows an offer only on an installed copy, and only while the server offers a version different from the one running.

| The offered version is | Menu item | Notification when it is first offered |
|---|---|---|
| newer | "Update available → v<X> (install)" | "Update available → v<X>. Use the menu to install" |
| older | "Roll back to v<X> (older version, install)" | "Roll back to v<X> offered. That is OLDER than the v<running> you are running. Only install it if your admin asked you to." |
| not comparable (a version that is not plain dotted numbers) | "Switch to v<X> (install)" | "Switch to v<X>. Use the menu to install" |

- When the version carries a line of what changed, the menu item is followed by " - <the first line>" cut to 48 characters, and the notification by "What's new: <the first line>" cut to 90 characters. The line is extra spaces collapsed and cut to 300 characters. It is advice only: it is never part of what the computer verifies.
- An older version is never called an update.
- A version this computer went back from because it kept crashing is not announced, but the menu still offers it, so the editor can choose it deliberately.
- The offer disappears when the server stops offering it. Signing in at the app also brings an offer.
- Pressing the menu item responds visibly at once.
- Ways in: the menu, and the same button in the app's settings window.

### A studio can let its computers take newer versions without anyone clicking

With this setting on, a NEWER offered version installs by itself on every computer of the studio. An older version is never taken unattended: it stays in the menu for the editor. The computer keeps trying while that version is offered, under the same rules and waits as any update (see "A failed update is tried again less and less often and then given up on"), and stops when the offer is withdrawn or replaced or the setting is turned off. A refusal's notice shows only on the first try. When the site's settings cannot be read, the setting counts as off.

- On its own: with the setting on, each computer installs a newer offered version once nothing would be harmed.
- By hand: an admin turns it on or off. An editor can still choose any offered version from the menu.
- Setting: Update editors' computers by themselves. Does: lets each editor's computer install a newer offered version with nobody clicking. Default: off. Who: an admin. Applies to: the site. Search words: automatic updates, auto update, unattended, install updates.

#### Lessons

- Met: REL-040, REL-041, REL-042, REL-043, REL-044, REL-045.

## Pushing updates and seeing who has what

### An admin pushes a version to one computer

An admin asks one computer to install a version, naming it (up to 32 characters) or, with none named, the current version for that computer's operating system. A held-back version may be pushed: it is then offered to that one computer alone, as its trial.

- Refusals:
  - an unknown computer: "no computer '<computer>' for '<person>'";
  - no version named and nothing current: "no current version of the app is published for that computer's operating system";
  - the named version is not held for that operating system: "<version> is not held on this server for <platform>";
  - the version this computer kept crashing on and went back from: "<computer> kept crashing on <version> and went back, so it will not install that version again, not even from UPDATE NOW. Publish a fixed version and it is offered as usual." (A version with an unfinished-work mark counts as the same version.)
- Before a second click, the admin sees what is already waiting for that computer: an update and when it was asked for, and any other request waiting for it.
- The admin is told whether a request was already waiting, whether the version is held back (", as an offer of a held-back version to this computer alone"), and when it will apply: "on that computer's next check-in, usually within 30 s. It was last heard from <N s | N minutes | N hours | N days> ago". When it was last heard from 24 hours or more ago: "when that computer next checks in. It was last heard from ..., so this may sit for a while". With nothing on record: "when that computer next checks in. Nothing on record says when it last did". A long-silent computer gets this warning, never a refusal.
- The computer installs it on its next check-in, only if the signed offer it holds is exactly that version, the version is not below its floor, and replacing the app would not interrupt work in progress. The editor is told "Your administrator is updating CC Sync to v<X>." The same waits and refusals apply as for the editor's own click, retried quietly. A new request for the same version is tried at once. A version already running is not installed again.
- If the computer cannot be offered the pushed version, it is not sent. The computer is given the reason ("the update you were sent cannot be installed on this computer"), and the admin sees "cannot be sent": "This computer is not being offered that version: <why>. It still takes shared work. Withdraw the push or publish a version it can take." The push stays waiting and is sent as soon as the version can be offered.
- While a push waits for that answer, the computer is given no new shared heavy work, because it is about to change version (see Work shared out across the computers: Choosing who runs what).
- A push is finished once the computer checks in on that version or a later one. A push back to an earlier version is finished only when the computer checks in on exactly that version. A push never shows success while nothing was delivered: until it is finished it stays visibly waiting.
- A push unanswered for 14 days expires, recorded as done by the system with "not taken within 14 days". When the computer goes back from a version because it kept crashing, a push for that version is withdrawn, recorded as done by the system with "kept crashing and went back".
- The admin can withdraw a waiting push at any time ("Withdraw the request. The computer keeps what it runs."). It always succeeds, even when nothing was waiting, and ends the one-computer offer of a held-back version.
- Every push and withdrawal is recorded among admin actions: who asked, when, the version, and which version the computer was on, so an update can be told from a rollback.
- Every version of the app, the very first one a computer ever installs included, obeys a pushed update.
- Who: an admin.
- Ways in: from the list of computers that are behind on the versions page, from a held-back version ("push to one computer"), and from the per-computer view.

### The versions page shows every version the site holds

The versions page is the one place an admin sees and changes which versions the site holds and offers. It reads afresh every 30 seconds, and every action redraws the whole list.

- At the top, what the server hands out right now: "app: what every computer updates itself to. installer: what a new editor downloads." One version per kind and operating system, with "N computer(s) on it".
- Versions are grouped by kind (the app on the editor's computer, the server, the installer, the Timeline Cards app) and operating system (Windows, macOS, then others). Empty groups are left out. Each group shows its current version and its newest version first. Older held-back versions are folded away ("Kept so you can put the computers back on one of them. A version taken from the vendor waits here, held back and on trial, until somebody makes it current."), and offered in the choice of a version to go back to. Empty: "Nothing held: every version here is the current one for its platform."
- For each version: its version, when and by whom it arrived, its size and a short fingerprint (the whole one on pointing), and these labels where they apply:
  - "current", or "held back" (kept here, not handed out) and since when;
  - the processor it is for;
  - "made from unfinished work" (only where it truly was), otherwise the change it was built from;
  - "recalled", with the vendor's reason;
  - "update the server first": "Needs server <v>, this server is <v>.";
  - "file missing";
  - "no code signature": the program carries no operating-system code signature, so Windows or macOS will warn on install;
  - its floor;
  - the line of what changed;
  - whether it was ever current (making it current again is a rollback);
  - its trial, for a held-back app (see "An admin tries a held-back version on one computer");
  - how many computers last checked in on it. For installers this is always "cannot tell", because no computer says which installer set it up.
- The server's data disk: "data disk: <free> free of <total>", or when under 2 GiB "<size> free on the server's data disk. A new version is refused below a safety floor, and a full disk stops every write the server makes. Older versions are cleared when a new one arrives, and backups and earlier server versions are cleared on each server update.", or "Could not measure free space on the server's data disk."
- Nothing served yet: "Nothing is being served yet: the vendor's versions are in the vendor's list below. Press "Check now" there to fetch them." With no vendor list set up, it says to take a version from the vendor.
- The trial time in force, and the server's own version.
- Who: an admin.
- Name and search words: Versions and updates. Search words: updates, versions, builds, release, rollout, packages.

### The versions page shows who runs which version

For each operating system with a current version of the app:

- "N of M on <version>", when it was made current (empty means "cannot tell"), how many are behind, how many went back after crashing, the total failed attempts, and "N refusing" (each computer and its reason on pointing). A computer refusing the offer also counts as behind.
- Behind means strictly older than the current version for the computer's own operating system. A computer on a newer version, even newer than the vendor's, is shown as ahead and raises no alarm. One that reports no version is shown as "unknown version". One running a version the vendor recalled shows the vendor's reason.
- Each computer behind: the person, the computer, its version, when it last checked in, and whichever of these applies:
  - "asked for <v>" (a push waiting), or "cannot be sent" with why;
  - "went back from <v>" ("Do not make that version current."), shown until the computer runs that version or a later one;
  - "failed xN": its last attempt to update, with the version, the number of attempts, the last error and when. The error "kept crashing" always means the new version kept crashing and the computer went back, never that a download failed;
  - "refusing <v>": "This computer refuses the current version: <reason>. Pushing it again will not change that." A refusing computer shows the refusal and its reason until it runs that version or the offer is withdrawn, so it is never mistaken for one that has not checked in, and an offer held back by the server is told apart from no update at all;
  - "Not offered to this computer: it kept crashing on <v> and went back, and it will not install that version again by itself. A newer version is offered as usual.";
  - otherwise "update now" (see "An admin pushes a version to one computer"), and "cancel" for a waiting push.
- Every computer checking in, grouped by operating system, to pick one to push to.
- Every processor computers report that the current version does not cover, with how many computers.
- When every computer is current: "All reporting computers are on the current version."
- A count the server cannot read is "cannot tell", never "all on the current version", and operating systems with computers but no current version are counted too.

How the site stands against the vendor, in one place:

- "this server <version>" with the vendor's newest server version (marked when newer) and whether the server is behind, or "vendor: not checked"; when the vendor was last checked; the last reason the server did not update itself.
- For each operating system: "<platform> computers are offered <current or 'nothing'>, published <ago>", the vendor's newest, whether the computers are behind the vendor, and one line per version computers actually run, "N on <version> (current), published <ago>", including versions this server never held.
- "No version of the app is current here yet, so nothing has been offered to anybody."
- Each disagreement as a sentence: "A newer CC Sync version for <platform> (<v>) is on offer and the computers here are being offered <current>. Update the server first: it is <D> and the vendor is offering <DV>."; "The vendor is offering <v> for <platform> and the computers here are being offered <current>."; "<n> of <total> <platform> computers are on <current>."; "This server is <D> and the vendor is offering <DV>." Otherwise: "Everything here agrees: this server, the vendor's versions and the computers checking in."
- A blank means not checked, never up to date.

Each computer tells the server, with every check-in, how its updates are going: the version it failed to install, how many attempts, the last failure and when, the version it went back from after crashing, how many times this version has started, any offer it refused and why, and how many record writes failed. All are zero when nothing went wrong.

- Who: an admin.

### The server tells an admin when versions are not reaching computers

Each of these is shown as a problem the server found and mailed as an alert (see The dashboard: Problems the server finds), with the fix in words.

| Problem | How serious | When | Fix shown |
|---|---|---|---|
| an update will not install | serious | a computer has failed 8 or more times at the same update | install by hand once the cause is fixed. When the last failure shows the new version crashing again and again and going back: do not install that version by hand, send the diagnostics, and publish a newer version |
| a computer is refusing every update | serious | within the last 24 hours a computer refused an offered version because its signature was bad, it was below that computer's floor, or it was offered over a plain connection from a public address. Older refusals are ignored | publish a version it will accept, or install by hand |
| a new version is not being taken | warning | a version was made current 48 hours or more ago and a computer that checked in since is still on an older one. Not raised when the time it was made current is unknown | push it, or ask the editor to install it |
| a computer is several versions behind | warning | 3 or more versions (not recalled, held here or offered by the vendor) are newer than the computer's | computers already on or ahead of the current version, or on an operating system with no current version, are grouped as "the <platform> computers", with a sentence explaining that "Update now" cannot help them |
| a computer cannot be updated from here | serious | a computer runs a version too old to take a pushed update | update it by hand |
| a trial version is failing | warning | a version on trial, not older than the current one, has crashed on or been gone back from on at least one computer since it started running there | do not make it current, send the diagnostics |
| a computer went back from an update | warning | a computer put the previous version back because the new one kept crashing | publish a fixed version |
| a recalled version is still running | serious | a computer runs a version the vendor recalled | move the computers off it |
| one platform's version is behind another's | warning | with two or more operating systems each having a current version, one was made current 7 days or more after the other's, or, if either time is unknown, trails by more than 2 versions | make an already-held newer version current, or ask the vendor |
| a held version can strand computers | serious | a current version needs a floor above its own ("a computer that accepts it can never install anything again"), or a floor below the highest already held for its kind, or a version on the shelf (not recalled) needs a newer server ("it needs server X and this server is Y, so it can never be handed to the computers from here"), or an operating system's current version is not the vendor's newest (not held here, held but not current, or older). Not checked with no vendor list or before the vendor's offer was read | update the server, or make the vendor's newest current |
| the server is not running the update applied to it | serious | the server started on its installation's version while its record says a newer update was applied | see the server's update history |
| computers send things this server is too old to read | warning | computers send details this server cannot store. Shown with the list of details | update this server ("Update now") |
| this server cannot check for updates | warning | the vendor's list was last read 7 days or more ago, never, or the last read failed. Cleared when no vendor list is set up | "Check now" |
| updates cannot install on this NAS | warning | every version the vendor offers needs a newer server installation than this one | renew the installation on the NAS (see "Some server updates need the installation renewed on the NAS") |

- Who: an admin sees these.

#### Lessons

- Met: REL-055, REL-056, REL-058, REL-059.

## Rolling back and withdrawing a build

### A new version that keeps crashing puts the previous one back by itself

One failed start of a new version is allowed (antivirus holding the files, for example). When a new version fails to start, or crashes, a second time within 10 minutes of its first start, the app puts the previous version back and starts it, before anything else starts, and syncing resumes with nobody touching the computer. A start that lost to a copy already running, or that was the hand-over during an update, does not count. A start that finishes and stays up resets the count.

- It cannot go back when no previous copy is kept, when the previous version is unknown, or when the previous version is below the computer's floor. Then the app carries on, says why in the start-up log, and the server is told, so a person can step in. None of this can stop the app from starting when it would otherwise start.
- About three seconds after the start on the previous version, the editor is told: "The last update kept crashing, so CC Sync went back to v<version>."
- The crashing version is marked on this computer: neither an unattended update nor an admin's push installs it again, and a newer version is tried as usual. The mark clears only when the computer runs that version, because the editor chose it deliberately. The server is told which version the computer went back from until a check-in is accepted.
- On its own: going back, decided from the new version's failed starts and crashes in its first 10 minutes.
- By hand: the editor sees what happened and can choose the version again from the menu. The admin sees "went back from <v>".

### An admin moves the computers back to an earlier version

Going back is choosing an earlier version to be current. "go back to…" lists only earlier held versions of the same kind and operating system that could be made current: not recalled, not waiting on a newer server, file present, and for the app either current before or past its trial.

- It asks, for the app: "Move <platform> back to the version you chose? Every <platform> computer on a newer version is asked to install it on its next check-in. It was current before, so there is no trial time." For the installer: "It is what new editors download from now on."
- Before the admin confirms, they are shown which computers run something newer than the chosen version other than the version being left, since they will be moved down too.
- Every computer on a newer version is then asked to install the chosen one, as a push, and the page shows each one moving until its check-in confirms it. The version gone back from is not offered again unless an admin chooses it.
- Refusals: nothing to go back to; the version the computers already run ("<v> is what those computers are already running."); a version recalled too ("<v> was recalled too. Pick a version that was not.").
- For a recalled version still running somewhere: "recalled <kind> <version> <platform> was withdrawn by the vendor: <reason>. N computer(s) still running it.", with "move them onto" a choice of versions that are not recalled (the current one chosen first). Confirming asks every computer on the recalled version to take the chosen one, and makes the chosen one current if the recalled one still is.
- Recorded among admin actions, with which computers were asked.
- Who: an admin.

### Every version sets a floor no computer goes below

Each signed version names a floor: the oldest version a computer may ever be taken back to. A computer raises its own floor when it sees an offer with a higher one, the floor only ever rises, and the computer never installs anything below it. A refused offer never changes any computer's floor. Going below the floor is a deliberate step taken by hand at the computer itself. The floor normally trails the current version by one release, kept per kind and operating system. A release that fixes something a downgrade would bring back raises the floor.

Refused when the version is signed, when it arrives at a site, and on every computer:

- no floor at all ("any older signed version could then be made current by a list played back, or by someone who took over an admin's session"), unless the vendor deliberately allows it;
- a floor above the version's own (the version would refuse itself and every corrected copy);
- a floor lower than one already published for that kind and operating system;
- for the app and the installer, a floor above the version offered to computers.

Going back to an earlier version above the floor is how a rollback works.

### The vendor recalls a version

The vendor can withdraw a version from every site, with a reason. The reason is required ("every customer server shows it beside the withdrawn version"). Recalling takes the version off the vendor's list and out of being current, and names the version to go back to: when it was current and nothing else is named current in the same act, the recall is refused unless the vendor deliberately leaves nothing current, and the vendor is told to name the newest version below the withdrawn one.

At each site, at its next check of the vendor's list and under every setting, manual included:

- the recalled version stops being offered to the computers. Its record and file stay on the site, marked recalled with when and why;
- it can never be made current again, and publishing it again is refused;
- the computers running it are flagged, and the admin is offered to move them onto another version (see "An admin moves the computers back to an earlier version"). Where the site follows the vendor, the vendor's chosen replacement becomes current and the computers are moved back, recorded in the admin history as done by the vendor's list;
- the vendor's list view shows every recall, with reason and time, whether or not this site ever held that version.

Making an earlier version current again on the vendor's list only changes which version is named current: nothing is rebuilt or signed again. It is refused for a recalled version, for a version the list does not carry (listing what it does carry), and for one signed by a key the current version does not trust.

- Who: the vendor.

### An admin deletes a version that is not current

- It asks "Delete <kind> <v> for <platform>? It goes to the trash on this server for 30 days. After that it is gone, and putting the computers back on it means asking the vendor for it again."
- The current version cannot be deleted: "cannot delete the current version. Make another version current first."
- The file goes to the server's trash and is kept 30 days from the deletion, then deleted for good. A file already missing is not an error. If it cannot be moved to the trash: "could not move <file> to the trash (...). Nothing was deleted: the version and its file are still here." A failed delete changes nothing.
- A deleted version cannot be restored from the dashboard.
- Recorded among admin actions with where the file went.
- Who: an admin.

### A server version that will not start properly is undone by itself

After a new server version starts, the server waits about 45 seconds and then checks for up to another 45 seconds that it answers as that version. A version that does not, or that has not got that far within ten minutes of starting (a start that hangs is caught too), is restarted. After two failed starts in a row the server goes back by itself to the previous version and records why ("<version> failed to reach a healthy start N times", or that it was refused N times and why). A healthy start clears the count.

- The admin sees "Went back automatically: <reason>" in the server's update view, and that version is marked so the server never takes it again by itself.
- The server never goes back to a version that cannot understand the studio's data as it now stands. It stays on the new version, keeps its admin pages answering, and records "This server did not go back automatically: starting <version> would fail on every start. Restore the backup taken before this update and go back from the dashboard, or update to a newer version." When it cannot tell whether the previous version understands the data, it still goes back.
- On its own: going back, from the new version's failed starts.
- By hand: the admin sees why and can go back, forward, or restore a backup from the dashboard (see "An admin moves the server back to an earlier version").

### An admin moves the server back to an earlier version

An admin can take the server back to the previous version, or to an earlier one the server still holds, and the server restarts. "go back to…" offers them ("Offline about ten seconds. Its data is backed up and stays as it is. Asks first.").

- It asks "Move this server back to <version>? It will be offline for about ten seconds while it restarts. The data is backed up first and stays as it is: it is not taken back to an earlier copy." The button stays disabled until a version is chosen.
- The admin may tick "also restore the data from <backup>" ("no backup on record" when there is none). The question then says that everything recorded since that backup is discarded, the computers' check-ins since then included.
- When the studio's data is newer than the earlier version understands, the move is refused unless the admin restores the backup named in the message alongside it, or explicitly accepts the risk. The question says to tick the restore box "or this will be refused". When it cannot be known whether the earlier version understands the data, the move is allowed, the data stays, and the answer says it is unknown.
- A backup can only be restored together with going back. A backup that does not exist or holds nothing in use is refused.
- Refused while an update is running, when the server holds no earlier version ("this server is already running the version it was installed with"), and when the named version is not held.
- A version gone back from is marked "gone back from by <admin>" and is never taken again by itself, until an admin updates to it by hand.
- The 10 newest backups are listed: when, name, from which version, what they hold, size.
- Who: an admin.

#### Lessons

- Met: REL-060, REL-061, REL-062, REL-063.

## The server updating itself

### An admin sees which server updates are on offer

The server's update view shows the version running and what it came from, and lists, newest first, with size, publish date and notes:

- updates the server can take with one button ("update now": "It is offline for about ten seconds. Its data is backed up first. Asks first.");
- updates that need the server's installation renewed in the NAS's own app manager, with the exact steps (see "Some server updates need the installation renewed on the NAS");
- earlier versions the server can go back to.

A version equal to the one running is not listed. With nothing newer: "No update is available for this server." The same view shows the progress or the last outcome of an update, any automatic going back and its reason, the backups taken before updates (name, when, by which version, what they hold, total size), the free space on the server's data disk (or that it cannot be measured), how many times the version on trial has failed to start, and what going back to the previous version would mean for the studio's data: safe, unknown, or that a backup must be restored with it. If the update state cannot be read: "could not read the update state: <error>".

- Who: an admin.
- Name and search words: Server updates. Search words: update server, dashboard version, upgrade, roll back server.

### An admin updates the server with one button

Every server update the vendor offers is applied from the dashboard with one button. The NAS's own app manager is needed only when the installation itself must be renewed. The admin is asked "Update this server to <version>? It will be offline for about ten seconds while it restarts. The data is backed up first." The update starts at once and the server restarts by itself for about ten seconds when it lands.

Refused, with the reason in words, when:

- the version named is not a plain dotted version number;
- another update is already running ("Wait for it to finish or fail"), including when two admins press at the same moment: one update runs and the other is told, and the page keeps following the one running;
- that version is already running;
- the version is older than the one running ("To go back, use go back to… instead");
- the update needs the installation renewed in the NAS's app manager instead;
- YouTube downloads are in progress: "N YouTube download(s) are running: an update restarts the server for about ten seconds and interrupts them. Wait, or apply again with force." Downloads waiting for review do not count. The admin can override with force;
- the data disk is short of space: it needs at least four times the update's size plus twice the size of the studio's live data, plus 256 MiB. A disk whose free space cannot be measured is not refused;
- the server cannot write where updates go.

An admin's own update to a version also lifts any "never take by itself" mark on that version.

- Who: an admin.
- When YouTube downloads is off: no download can be interrupted, so that refusal never appears.

### The admin watches each step of a server update

Progress is refreshed every second and shows, in order: queued ("starting the update"), downloading, checking, trying the new version against copies of the studio's data, backing up, switching over, restarting ("restarting: the server is offline for about ten seconds"), then done; or failed with the reason. A refusal shows "Not applied: <reason>". Opening the page while an update runs picks up its progress.

- The page reloads by itself once the new version answers. After 3 minutes without an answer it says "the server has not come back yet. It may still be restarting: reload this page in a minute, or check the server's logs." and keeps watching, reloading by itself if it answers later.
- An update cut off by the server or the NAS restarting is shown afterwards as failed, "interrupted by a restart at step S", and updating and going back work again from the page at once.
- Nothing temporary from an update is left on the disk, whatever happens.
- With a full or read-only data disk, the update's state still answers, and an update already applied still restarts into the new version.

### Some server updates need the installation renewed on the NAS

A few updates change what the server's installation on the NAS itself carries, and cannot be applied from the dashboard. For these, the update view, the versions page, a banner on the overview and the alert mail all give the same instruction, for this kind of NAS (see "Facts about the NAS and the share"). The banner appears when every server update on offer needs this (up to five versions named), "every server version on offer (<versions>) needs the server's installation renewed, so no update can be applied from the dashboard", with how to do it on this kind of NAS, and goes away by itself when that is no longer so.

When the server is installed, the person is told whether later updates will apply from the dashboard, and the updates view says "installation update" for a version that needs renewing instead of offering a button. A server whose installation is renewed to a version at or above an update it had taken runs the renewed version at its next start, and says so in the update view ("<version> is not newer than the installation's own <version>: the installation carries it"). It does not do this when the renewed installation would not understand the studio's data as it now stands: it records the refusal instead.

- Who: an admin.

### A site that follows the vendor updates its server by itself

When the site takes the vendor's versions as current (see "An admin chooses how much of the vendor's offer the site takes by itself"), the server takes the server version the vendor offers after each check, in the same way as the admin's button but never interrupting YouTube downloads. When it starts: "taking server <version> now: this server restarts for about ten seconds when it lands." When it does not, its health view shows one sentence why ("server <version> was not applied: <reason>"):

- an update is already running;
- the newer version is not the one the vendor offers ("Update now" takes it by hand);
- it needs the installation renewed (with how);
- it already failed here and "will not be retried by itself";
- an admin went back from it;
- it was taken before, would not start, and was undone;
- it has not finished its trial: the vendor must have published it at least the trial time ago (30 minutes by default, none when the trial is off), and a version with no readable publish date is never taken while a trial is set.

- On its own: taking the vendor's server version, from the site's choice and the trial.
- By hand: the admin updates or goes back from the server's update view, and the site's choice can be changed at any time.

### The server never runs on data newer than it understands

If the server is put back to a version older than its own records, it refuses to start and says the records were written by a newer server than this one, gives both record versions, and tells the admin to install the matching or a newer server. An update of the records that was interrupted halfway carries on from where it stopped at the next start.

### Each part of the server is updated without touching the others

A new version may change one part (the b-roll archive, music, YouTube downloads, Timeline Cards, the Footage Sorter) without changing the others, and a part is tested and shipped on its own. Updating a part never touches another part's records. The server shows the version of each part, and which version of Timeline Cards and of the Footage Sorter it runs. The app on the editor's computer is always one app with one version, updated as a whole.

### Every server version released has proved it starts from empty

Before a server version is released, it has been started from nothing with fresh secrets, answered its health check with the right version, and shown its set-up page. A server update carries the server's program and the help pages customers read; an update that would leave the help pages missing, or the server with no program, is refused. Every file in it carries a checksum and the whole can be verified ("VERIFY OK" or "VERIFY FAILED"). Released server versions are signed so anyone can verify them, and each customer site is fixed to the exact server versions released.

#### Lessons

- Met: REL-064, REL-065, REL-066, REL-067, REL-068, REL-069, REL-070, REL-071.

## Customer sites and the vendor's release feed

### Every site takes the vendor's versions from one signed list

The vendor publishes one signed list that every site reads: the server's versions, the app and the installer for each operating system, the Timeline Cards app, and the large files parts need once, with which version of each is current, the exact server installation sites should run, and every recall. A site checks the whole list's signature, and each version's, against the keys it trusts (see "The server believes only a release list the vendor signed, and refuses an earlier one played back").

- Every site, the vendor's own studio included, takes its versions this way, so every customer receives the app, the installer for each operating system and the server's updates through the same list. With no installer held, the page new editors download from tells the customer to take one from the vendor.
- A site trusts the vendor's key and reads the vendor's list out of the box. The list's address is one the vendor owns and can move elsewhere without touching any installed site.
- Every download a site makes, large files included, comes from the site's own source of versions, and never follows a redirect from a secure address to an insecure one. A large file a part needs carries a checksum the app compares with the one it already holds.
- Setting: Where the site takes the vendor's versions from. Does: the address of the vendor's list. Empty means the site is never offered any version. Default: the vendor's own address. Who: an admin. Applies to: the site. Search words: release feed, vendor, update source, updates address.

### An admin chooses how much of the vendor's offer the site takes by itself

"Nothing here reaches your computers until it is held on this server and made current." The admin chooses one of three:

| Choice | What happens |
|---|---|
| by hand | nothing is taken by itself. Only an admin's button brings a version in |
| try first | the version the vendor offers for each kind and operating system is downloaded and held back, offered to no computer until an admin makes it current |
| follow the vendor | the same, and it is made current, subject to the trial. The server also updates itself (see "A site that follows the vendor updates its server by itself") |

- The version the vendor offers is the one the vendor names as current, or, with none named, the highest version.
- Changing the choice asks first, and cancelling puts the previous choice back. Choosing "follow the vendor" asks: "Take new versions automatically AND make them current? Every editor's computer will take each new version from the vendor without anyone approving it first. Choose 'try first' if you want to test a version before the computers get it." Any other choice applies at once.
- Anything else is refused as not one of the three.
- On its own: with "try first" or "follow the vendor", the site takes each new version after its daily check.
- By hand: an admin brings any one version in, makes any held version current, or changes the choice at any time.
- Setting: How the site takes the vendor's new versions. Does: whether new versions from the vendor wait for an admin, arrive held back for trying, or are offered to every computer by themselves. Default: try first. Who: an admin. Applies to: the site. Search words: vendor updates, auto publish, release policy, follow vendor, staged.

### The server checks the vendor's list every day, and an admin can check now

The first check runs about ten seconds after the server starts, then once a day. An admin can press "Check now" at any time, and is shown what was taken or made current by that check, what the vendor recalled, and which versions need a newer server; a failure reads "check failed: <error>". Versions the server would not take: "This server would not take <list> from the vendor. Nothing was taken. Ask the vendor: it is the release record that is being refused, not the download."

- The view shows whether a list is set up and where, the choice in force, "last checked <ago>" (or "never"), how often it checks, "next in about <time>" or, after a failure, "next retry in about <time>", and "last check failed" with the error on pointing.
- Kept: when the list was last checked (success or failure), the last error, when the list itself was made, how many verified versions it carried, and what it offers per operating system. An empty offer means unknown, never "nothing offered".
- Stale means never checked, or no successful check for more than 7 days. Then the overview shows a banner: "No successful update check for N days. Last checked <ago>: <error>. This site is not receiving fixes, which looks the same as no fixes having been published." With no list set up it says so and is never called stale.
- With no list set up there are no checks and nothing reaches out to the internet. "Check now" and taking a version from the vendor answer that no vendor list is set up.
- Setting: How often the server checks the vendor. Does: the time between checks of the vendor's list. Never under a minute. Default: once a day. Who: an admin. Applies to: the site. Search words: update check, check interval, vendor check, how often.

### An admin brings one version from the vendor onto the site by hand

The vendor's list shows each version it offers, with its notes and when it was published:

- "current here";
- "held back, not current", with "make current" and "make current anyway" as for any held-back version;
- "same version, different bytes", with both short fingerprints: "ask the vendor for a new version number. Nothing was replaced.";
- "recalled": "It is not offered here under any choice.";
- otherwise "take" (download it, held back) and "take and make current" ("The trial time still applies.").

"<list> are offered by the vendor. Press "Check now" to take them." or "Nothing new: this server already holds everything the vendor offers." A newer server version shows that it is available, what is running, and how to apply it.

Taking a version is refused when no list is set up, when it is a server update ("server updates are applied, not taken"), when it is already held (or the same version from different bytes: "The vendor has to publish this version under a new version number."), when the download is not secure, does not match, fails, or is over 200 MiB or ten minutes, or when the disk is short of space (see "A version reaches a site whole or not at all"). The record names the admin as the one who brought it.

The set-up shows "Software for editors": "Take the current version of the app for Windows and macOS." It reads "windows <version> current, macos <version> current"; a warning when only one operating system has a current version ("<platform>: none held"); to do when neither does, pointing to taking one from the vendor; failed when the server cannot read its versions. Its "CHECK NOW" checks the vendor now under the site's choice and adds "taken from the vendor: <versions>", "the vendor has nothing this server does not already hold", or a warning that the check failed.

- Who: an admin.
- Ways in: the vendor's list on the versions page, and the "Software for editors" step of the set-up.

### A server can be installed with no vendor list

A site may be installed with the vendor's list switched off. The person installing is warned that the server then makes no call to the vendor and its updates screen offers no update: it is a valid way to run, and they are told to set the list if updating itself is what they want.

- Who: whoever installs the server.

### Customer sites are offered a version only after it has run a day at the vendor's studio

A version reaches customer sites only as the exact version the vendor names for them, and only after:

- it was made from finished work the vendor has accepted into the product, and every automated check passed on exactly that change, the server's own included ("nothing has tested this server" is a refusal, not a pass);
- its server version is not older than the newest the vendor offers ("that is going back, not a release");
- every piece of it exists for every operating system;
- its version label belongs to no other change ("a released label is never moved");
- the vendor's own studio has run exactly this version for 24 hours. The first time the vendor tries, the clock starts and the release is refused, "run again in 24 h". Later tries say how many hours remain. A different version, or one whose origin cannot be told, on the studio is refused;
- a second person at the vendor has approved it.

Then the server version is released, then the apps and installers. If the apps fail, the vendor is told the server half is already out and how to send the rest. A fresh customer installation is fixed to the exact server version released. When it is done, the vendor is told when customers get it: sites that follow the vendor take it at their next check (daily, and about ten seconds after their server restarts), subject to their own trial; sites that try first hold it back for their admin; sites that take versions by hand need their admin to check and take it. A ready-to-run recall line is printed for every version published.

- Who: the vendor.

### The vendor is told every day when the list for customers falls behind

A daily check reads the signed list and reports it stale when no server version is current, when the current server is more than 3 versions behind the newest the vendor has made (a different first or second number always counts as far behind), when the current server names no exact installation, when a current app needs a newer server than the current server, or when the list is more than 45 days old while a newer server exists. A list that cannot be read or does not verify is "NOT CHECKED", never fresh, and counts as a failure.

- Who: the vendor.

#### Lessons

- Met: REL-072, REL-073, REL-075, REL-076, REL-077, REL-078, REL-079.

