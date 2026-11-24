# Joins aimed at server-install-and-running-1

## Checked

- J1 | F1, F2, F3, F4
- J2 | F5
- J3 | fine
- J4 | fine
- J5 | F6, F7
- J6 | F8, F9
- J7 | F10
- J8 | fine
- J9 | F11, F12
- J10 | fine
- J11 | F13
- J12 | F14, F15, F16
- J13 | F17
- J14 | fine
- J15 | F18
- J16 | fine
- J17 | F19
- J18 | F10

## Findings

### F1: The admins are named and checked at install there; here installing asks for two places only and set-up never refuses the NAS's own administrator
- Kind: contradiction
- From: accounts-privacy-legal / The admins are named at install, and are never the NAS's own administrator
- Here: Installing is one step on the NAS, and the rest happens in the browser; Set-up task: your admin account
- From says: "Installing is refused when no admin is named" ... "and when the list names the NAS's own administrator account, ignoring capitals (\"use a separate account\")"
- Here says: "Installing the server asks for two places only" and, in set-up, "the task carries a box for the names of the accounts that may administer the dashboard" (no refusal of the NAS administrator anywhere)
- Settled by: SRV-015 (ruling): "A new studio is set up from a browser wizard after those installs, with no commands, builds, signing keys or manual steps on the customer's side"; accounts-privacy-legal-Q10 "Answered by the owner 2026-11-24: A: the refusal always holds"
- Fix: accounts-privacy-legal should say the admins are named in the browser set-up (not at install), and this piece's "your admin account" task should refuse a list that is empty or names the NAS's own administrator account, with that piece's messages.

### F2: This piece still offers three ways to sign in and keeps the sign-in service's admin mark; the owner chose one account per person and dropped the mark
- Kind: contradiction
- From: accounts-privacy-legal / Every person has one account, and a studio may put its single sign-on in front
- Here: Set-up task: your admin account; A sign-in set-up that would lock everyone out is refused; Before any account exists anyone may start set-up, and after that only an admin
- From says: "Every person has one account, kept by the product: one sign-in name and one password for the dashboard, the app on their computers and every part."
- Here says: "a sign-in method that is not one of the three offered (the dashboard's own accounts, NAS accounts, single sign-on)" and "the identity provider's own admin mark is only noted at sign-in and makes nobody an admin"
- Settled by: accounts-privacy-legal-Q1 "Answered by the owner 2026-11-24: B: one account per person kept by the product, kept in step with the person's NAS login, with single sign-on optionally in front"; accounts-privacy-legal-Q3 "Answered by the owner 2026-11-24: A: the sign-in service's admin mark goes"
- Fix: this piece should drop sign-in by NAS account as a method (its admin task, its lock-out refusals, "when the studio signs in by NAS account") and the mention of the identity provider's admin mark, leaving the product's own accounts with single sign-on optionally in front.

### F3: An editor's NAS account gets a password nobody is told here; there it has the same password as the person's account
- Kind: contradiction
- From: accounts-privacy-legal / Every person has one account, and a studio may put its single sign-on in front
- Here: Editor accounts on the NAS are made and managed by the dashboard
- From says: "the product keeps each person's NAS login in step with their account, with the same name and the same password"
- Here says: "A new account gets the full name (default the username), the editors' group, a random password nobody is told"
- Settled by: accounts-privacy-legal-Q1 "Answered by the owner 2026-11-24: B: one account per person kept by the product, kept in step with the person's NAS login"
- Fix: this piece should say the editor's NAS account carries the person's own password and is changed with it, where the studio's people open the shared folders directly.

### F4: The longest sign-in name and the characters allowed differ
- Kind: contradiction
- From: accounts-privacy-legal / A sign-in name has one shape, and a name accepted anywhere works everywhere
- Here: Editor accounts on the NAS are made and managed by the dashboard; Set-up task: your admin account
- From says: "A sign-in name starts with a lower-case letter, holds only lower-case letters, digits, \".\", \"_\" and \"-\", and is 1 to 31 characters long."
- Here says: "A username starts with a lowercase letter, followed by up to 31 lowercase letters, digits, dots, underscores or hyphens." and "Each name is 1 to 64 letters, digits, \".\", \"_\", \"@\", \"\\\" or \"-\""
- Settled by: the owner must say: what is the longest sign-in name a person may have (31 or 32 characters)?; the admin names' "@" and "\" fall with F2 (no NAS-account or provider names any more).
- Fix: this piece should use the one shape accounts-privacy-legal gives (pointing to it) for both editors' NAS accounts and the admin names, with the length the owner names.

### F5: Changing the server's own sign-in secret is described there and does not exist here
- Kind: missing
- From: accounts-privacy-legal / Changing the server's own secrets signs nobody out
- Here: The server makes and keeps its own secrets; Secrets an admin enters are checked and never shown back
- From says: "When the server's own signing secret is changed, every existing computer sign-in and browser sign-in keeps working ... until the admin chooses to retire the previous secret."
- Here says: "Any that is missing is made at random on first start and kept on the server's own disk ... and the same value is used at every later start." (no way to change or retire one)
- Settled by: ACC-015 (kind situation, weaker): "A secret change keeps every existing sign-in working on every request in every part, refused computers are named with the fix, and an unsaved secret stops startup."
- Fix: this piece should say where an admin changes the server's sign-in secret (in settings, not by reinstalling) and point to accounts-privacy-legal for what happens to existing sign-ins.

### F6: Alert delivery counts as working under two different rules
- Kind: contradiction
- From: dashboard-2 / The dashboard says whether alerts are really reaching anyone
- Here: The protection list says what really stands between the studio and a loss (line "somebody is told when this server finds a problem"); Every problem the server finds reaches a person
- From says: "Alert delivery is shown as working only when a destination is set, something was delivered through it to someone in the last 30 days, and the most recent failure is older than the last success."
- Here says: "\"protected\" only when mail or a web address is set for alerts and something was actually delivered through it in the last 30 days"
- Settled by: the owner must say: when the last alert failed to go out but an earlier one went out within 30 days, is the studio shown as being told?
- Fix: both pieces should use one rule for "somebody is told", and the protection line here should point to dashboard-2's status line (or the other way round) instead of stating its own.

### F7: A deliberate choice to tell nobody ends the warning there; here a skip never turns the line green and the home page still says nobody is being told
- Kind: contradiction
- From: dashboard-2 / The dashboard says whether alerts are really reaching anyone
- Here: The Done step waits for the required tasks and three protections; The protection list says what really stands between the studio and a loss; Every problem the server finds reaches a person
- From says: "While no destination is set (and the admin has not chosen to tell nobody), a warning stands among the open problems"
- Here says: "A skip in set-up never turns a line green." and "With no alert destination set, or nothing delivered in 30 days, the home page and the protection list say \"nobody is being told\""
- Settled by: the owner must say: when an admin has chosen on purpose to tell nobody, does the home page still show that nobody is being told?
- Fix: this piece should say what the recorded "tell nobody" choice does to the protection line and the home page, in the same words as dashboard-2.

### F8: There, the person installing can unlock the tree's place; here no unlock exists and installing names two places only
- Kind: contradiction
- From: dashboard-2 / Where the tree sits is fixed once any computer has joined
- Here: The tree, the drive letter and the dashboard's address are set once and then locked
- From says: "only the person installing the server can unlock the change on purpose"
- Here says: "a change is refused, saying every computer's move must be planned first" (and "Installing the server asks only for its two places")
- Settled by: SRV-015 (ruling) rules out a step at install for it; whether the place can ever be changed the owner must say: once computers have joined, can an admin ever move the tree to a new drive letter or name, and if so from where?
- Fix: dashboard-2 should drop the installer's unlock; if the owner wants a deliberate change, this piece should describe it as a step in the dashboard.

### F9: The drive letter's rule and its refusal are written out in full in both pieces
- Kind: said twice
- From: dashboard-2 / Where the tree sits is fixed once any computer has joined
- Here: The tree, the drive letter and the dashboard's address are set once and then locked
- From says: "must look like \"P:\" or \"P:\\\" (the backslash is added) or be an absolute folder with no \"..\", and may not be blank"
- Here says: "The drive letter must look like \"P:\" or \"P:\\\" (the backslash is added) or an absolute folder with no \"..\", and may not be blank"
- Settled by: no disagreement yet; OWNER_REQUIREMENTS 1: "One way to do each thing: one way of telling a computer something, one place a setting comes from"
- Fix: dashboard-2 should keep only a pointer to this piece's passage for the drive letter's shape and lock.

### F10: The studio's time zone is leaned on as set here, but this piece never mentions it and set-up never asks for it
- Kind: missing
- From: footage-sorter-and-camera-cards-1 / Nightly work runs on the studio's clock; whole-product / Dates are the studio's dates
- Here: nowhere (not under Settings and secrets, not in the set-up tasks)
- From says: "When no studio time zone has been set, the NAS's own zone is used; when neither is known, the admin setting up the site is told that the nightly work will run on universal time." and "(see The server: installing it and keeping it running: Settings and secrets)"
- Here says: nothing
- Settled by: footage-sorter-and-camera-cards-1-Q14 "Answered by the owner 2026-11-24: A, one named studio time zone that everything follows"; server-install-and-running-2 holds the setting ("Default: asked at set-up")
- Fix: this piece's "your studio" set-up task should ask the studio's time zone and its settings list should point to server-install-and-running-2's "Schedules run on the studio's own clock"; whole-product and the Footage Sorter should point there, not to this piece's Settings and secrets or to "at install".

### F11: The nightly cloud backup is a setting in both pieces, under two names and with two defaults
- Kind: contradiction
- From: footage-sorter-and-camera-cards-2 / The NAS's footage goes to the cloud backup every night
- Here: The NAS copies the studio's work off site every night
- From says: "Setting: Nightly cloud backup of footage. ... Default: off until a cloud backup is set up."
- Here says: "Setting: Nightly off-site backup. Does: switches the nightly off-site copy on or off and sets its time. Default: on, at 04:15."
- Settled by: SRV-092 (ruling): "Nightly, the NAS itself copies 1080p proxies, audio, stills, graphics, project files and every Resolve project off site"
- Fix: footage-sorter-and-camera-cards-2 should drop its own setting and point to this piece's "Nightly off-site backup" (the record's page may show the same switch).

### F12: The Sorter's record is said to travel in the off-site copy, but the off-site copy here carries no such folder
- Kind: missing
- From: footage-sorter-and-camera-cards-2 / The record survives losing the NAS
- Here: The NAS copies the studio's work off site every night
- From says: "They go into the folder the NAS carries to the cloud backup when one is set up, else beside the record."
- Here says: "for every project ticked for off-site backup, its 1080p proxies, audio, stills, graphics and project files, plus every Resolve project"
- Settled by: the owner must say: when the NAS is lost, does the record of where every copy of the footage sits come back from the off-site copy?
- Fix: this piece should list the Sorter's daily record backup among what goes off site each night when the Footage Sorter is on.

### F13: Putting a folder move back takes a snapshot there; this piece's snapshot rule does not cover moves and, where it applies, refuses to go ahead without one
- Kind: missing
- From: proxies-and-file-moves / An admin puts a move back
- Here: A snapshot is taken before anything risky and sweeping
- From says: "Before putting back a folder move the server takes a snapshot of the NAS if it can, and goes ahead if it cannot."
- Here says: "Before an update, a reinstall, or any change of ownership that walks a whole folder tree, a snapshot of what is about to change is taken." ... "If no snapshot can be taken, the change does not go ahead"
- Settled by: the owner must say: if no snapshot can be taken, does putting a folder move back still go ahead without asking?
- Fix: this piece should name folder moves and their undo among the changes it snapshots and say which of its two rules (go ahead, or ask in words) they follow.

### F14: An update and going back leave the server offline about ten seconds there; here an update has no gap and no page restarts the server
- Kind: contradiction
- From: releases-and-updates / An admin moves the server back to an earlier version (and An admin updates the server with one button)
- Here: Updating the server never takes the dashboard away; Settings take effect without a restart, and no page restarts the server
- From says: "It will be offline for about ten seconds while it restarts."
- Here says: "A server update keeps the dashboard and every open editor's page answering throughout, with no gap a person or an editor's app can notice." and "No page of the product, the dashboard or any part, can restart the shared server."
- Settled by: SRV-042 (ruling): "A server update keeps the dashboard and open editor pages answering throughout, with no gap a person or an editor's app can notice."
- Fix: releases-and-updates should drop the ten seconds offline from updating and going back; this piece should say that updating and going back from the dashboard are the admin's deliberate acts and are not the page restart it forbids.

### F15: An update is refused during YouTube downloads and can be forced there; here it waits by itself and is never forced
- Kind: contradiction
- From: releases-and-updates / An admin updates the server with one button (read beside An admin moves the server back to an earlier version)
- Here: Updating the server never takes the dashboard away
- From says: "YouTube downloads are in progress: ... Wait, or apply again with force." ... "The admin can override with force"
- Here says: "An update waits until running download jobs have finished, trying again by itself, and is never forced past a running job."
- Settled by: SRV-055 (kind situation, weaker): "A server update waits until running download jobs finish, retrying by itself, and is never forced past a running job."
- Fix: releases-and-updates should drop the refusal and the force, and say the update waits for running downloads and goes ahead by itself.

### F16: Ten backups are listed there; at most eight are kept here
- Kind: contradiction
- From: releases-and-updates / An admin moves the server back to an earlier version
- Here: Before every update the studio's data is backed up
- From says: "The 10 newest backups are listed"
- Here says: "Backups are kept newest first, at most 3 per update, at most 8 in all and at most 8 GiB in all"
- Settled by: SRV-084 (kind situation, weaker) requires a stated count, which this piece gives; the owner must say only if he wants more than 8: how many backups taken before updates does the server keep?
- Fix: releases-and-updates should list every backup kept (at most 8) and point here for the keeping rule.

### F17: Updates that need the installation renewed, and what the person installing is told about them, are not in this piece
- Kind: missing
- From: releases-and-updates / Some server updates need the installation renewed on the NAS
- Here: Installing is one step on the NAS, and the rest happens in the browser (nothing on renewal anywhere)
- From says: "When the server is installed, the person is told whether later updates will apply from the dashboard"
- Here says: nothing
- Settled by: REL-064 (ruling): "An admin installs a release on the server and every computer from the dashboard; only newer builds are offered as updates, and the NAS screen is for runtime changes only."
- Fix: this piece's install passage should say what the person installing is told about later updates and how an installation is renewed from each kind of NAS's app screen, keeping every setting (pointing to releases-and-updates).

### F18: The shared Resolve library's nightly copies kept 30 days are not among what this piece keeps, which caps backups at 8
- Kind: contradiction
- From: resolve-on-the-editors-computer / Every shared Resolve project library is backed up every night
- Here: A shared Resolve project database on the NAS is set up safely; The server's own data space is watched
- From says: "Every Resolve project library the server holds is backed up nightly in that form, checked to be readable, and kept for 30 days."
- Here says: "backs it up with the server's data" and "Everything the server keeps expires by a stated age or count: ... backups (at most 8, 8 GiB)"
- Settled by: RSV-047 (kind given, weaker): "Every Resolve project library is backed up nightly, checked readable, kept 30 days, in a form Resolve's Project Manager can restore."
- Fix: this piece should say the library is copied nightly and kept 30 days, and list those copies separately in its "everything the server keeps" list.

### F19: A vendor-supplied appliance is mentioned there; here the server runs on exactly two kinds of NAS
- Kind: contradiction
- From: sync-2 / Downloads from a Synology NAS always arrive whole
- Here: The server runs on a TrueNAS or a Synology NAS
- From says: "(an appliance the vendor supplies does not have the fault)"
- Here says: "The server runs on exactly two kinds of NAS"
- Settled by: the owner must say: does the product run on a box the vendor supplies, besides a studio's own TrueNAS or Synology?
- Fix: if not, sync-2 should drop the parenthesis; if so, this piece should list the vendor's appliance as a third kind with its own facts.
