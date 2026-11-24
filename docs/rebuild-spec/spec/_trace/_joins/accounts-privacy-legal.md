# Joins aimed at accounts-privacy-legal

## Checked

- J1 | fine
- J2 | fine
- J3 | F4, F5
- J4 | F2, F3
- J5 | fine
- J6 | fine
- J7 | F1
- J8 | fine
- J9 | fine
- J10 | F8, F9
- J11 | fine
- J12 | F6, F7
- J13 | F1
- J14 | F1
- J15 | fine
- J16 | F16
- J17 | F16, F17
- J18 | fine
- J19 | F1
- J20 | fine
- J21 | F10
- J22 | F2, F11, F12, F13
- J23 | fine
- J24 | fine
- J25 | F13
- J26 | F14
- J27 | F15
- J28 | fine
- J29 | fine
- J30 | F18
- J31 | F19
- J32 | fine

## Findings

### F1: Other pieces still name a "disabled" person as a third state; this piece has only suspended and removed
- Kind: contradiction
- From: editor-app / The editor signs in with the username and password their admin gave them (also dashboard-1 / A computer that cannot sign in is still shown, and admins are told; fleet-jobs / A computer whose access is refused says so and takes no work; releases-and-updates / Anyone signed in can download the app and the installer)
- Here: Suspending, disabling and removing a person
- From says: "the person is removed, suspended or disabled | the sentence for that case"
- Here says: "Suspending and removing a person each take effect at the very next request, everywhere" (the refusal table has sentences only for "the person was removed" and "the person is suspended"; the heading alone still says "disabling")
- Settled by: page-09 9.4, answered with the recommendation: "B: three: suspend (...), "a device was lost" (...), and remove; disable folded into suspend."
- Fix: editor-app, dashboard-1, fleet-jobs and releases-and-updates drop "disabled" (suspended or removed only), and this piece renames its heading to "Suspending and removing a person".

### F2: A new computer waits for an admin's approval in other pieces; here signing in is all it takes
- Kind: contradiction
- From: dashboard-1 / An admin sees every person and computer in one place (also server-install-and-running-1 / Editor accounts on the NAS are made and managed by the dashboard)
- Here: A computer becomes a person's when they sign in on it
- From says: "computers waiting to be approved, each with a suggested owner and name when that computer has already said who it is (see "A new computer is approved under its owner")"; server-install-and-running-1: "if it cannot be written that is an error and the computer's approval stays pending"
- Here says: "Nothing else is needed: no code passed to an admin, no approval, nothing pasted." (yet "Only the people the admin has let in" says a name joins the list when an admin "approves the person's computer")
- Settled by: the owner must say: when an editor signs in on a new computer, does it start syncing at once, or does it wait until an admin approves it?
- Fix: if signing in is enough, dashboard-1 drops "A new computer is approved under its owner" and the waiting list, server-install-and-running-1 drops "approval stays pending", and this piece drops "approves the person's computer"; otherwise this piece describes the approval step.

### F3: The admin's page of people has two names
- Kind: differs
- From: dashboard-1 / An admin sees every person and computer in one place
- Here: An admin manages the studio's people from one list
- From says: "Name and search words: People and computers."
- Here says: "Name and search words: People."
- Settled by: the owner must say: is the admin's list of people and their computers one page, and is it called "People" or "People and computers"?
- Fix: one piece describes the page and gives its name, and the other points at it by that same name.

### F4: Per-project access is a site's choice in dashboard-1; here every project is always members-only
- Kind: contradiction
- From: dashboard-1 / Anyone signed in can create a project
- Here: Each project is reachable only by its members
- From says: "On sites that control access per project, the new folder is open only to that project's group"
- Here says: "Each project's folder on the NAS can be opened, changed or deleted only by its members"
- Settled by: page-09 9.7, answered with the recommendation: "A: per-project access only."
- Fix: dashboard-1 drops "On sites that control access per project" (here and on archiving), and server-install-and-running-1 drops its "Who may see each project" setting.

### F5: dashboard-1 gives a project's creator access; this piece's list of ways to become a member does not include creating it
- Kind: contradiction
- From: dashboard-1 / Anyone signed in can create a project
- Here: Each project is reachable only by its members
- From says: "and the creator is given access"
- Here says: "A person is a member of a project when they have ticked it on any of their computers (full or upload only) and it is not archived, or when an admin has given them access."
- Settled by: the owner must say: does the person who creates a new project get into its folder straight away, before they tick it?
- Fix: if yes, this piece adds "or when they created it (never by creating one that already exists)" to the ways to become a member; if no, dashboard-1 drops "the creator is given access".

### F6: editor-app signs out a person's 17th computer; here adding a computer never takes anything away
- Kind: contradiction
- From: editor-app / The editor signs in with the username and password their admin gave them
- Here: A computer becomes a person's when they sign in on it
- From says: "a person may have at most 16 computers signed in, the least recently used one beyond that being signed out"
- Here says: "adding a computer never takes anything away from the person's other computers" and "A computer's sign-in never ends on a timer. It ends only when an admin withdraws it, when the person's access is stopped or removed, or when the person signs out on that computer"
- Settled by: ACC-010 (ruling): "A computer's sign-in ends only when an admin revokes it or the person's access is removed"
- Fix: editor-app drops the 16-computer limit and the signing out of the least recently used one.

### F7: The app's sign-in refusals use other sentences, reveal unknown names, and give no wait in minutes
- Kind: contradiction
- From: editor-app / The editor signs in with the username and password their admin gave them
- Here: What a refused sign-in says; Wrong passwords make the next try wait
- From says: "\"invalid username or password\"", "\"'<name>' is not an account on this dashboard - ask an admin to create it\"", "\"too many sign-in attempts - try again shortly\"", "\"sign-in is not available on this server right now - try again shortly\""
- Here says: "one sentence for all, "sign-in refused - check your username and password, then try again". It never says which half was wrong." and "Too many sign-in attempts. Try again in N minutes." and "login not configured on the server", with "The same limits apply to signing in on the dashboard, signing in from the app on an editor's computer"
- Settled by: ACC-031 (situation, weaker) for the wait: "A lockout always answers with a wait capped at one hour, stated in whole minutes, identical for unknown and real names"; for the rest the owner must say: may the app on an editor's computer tell a person that the name they typed is not an account here, when the dashboard's sign-in page never does?
- Fix: editor-app uses this piece's sentences (or this piece states that the app's sign-in has its own sentences and which names it may reveal), and the too-many-attempts line states the wait in minutes.

### F8: Closing the licence window: editor-app keeps offering it; here closing declines and stops the offer
- Kind: contradiction
- From: editor-app / Nothing syncs until the licence is accepted, and the app asks within a minute
- Here: A computer accepts the licence before it first syncs; The licence window
- From says: "offers it again until it has been answered, counts closing it as unanswered"
- Here says: "Declining or closing the window stops the automatic offer" and "closing the window declines"
- Settled by: the owner must say: when an editor closes the licence window without pressing either button, does the app keep offering it every minute, or stop until they open it from the menu?
- Fix: the piece that loses changes its sentence on closing the window to match.

### F9: editor-app stops sync until the current licence is accepted; here a new version asks without stopping sync
- Kind: contradiction
- From: editor-app / Nothing syncs until the licence is accepted, and the app asks within a minute
- Here: A new licence version asks everyone again without stopping their sync
- From says: "Nothing syncs on a computer until someone there has accepted the current licence"
- Here says: "The computer keeps syncing while it waits, and shows "waiting for the licence to be accepted" as its state"
- Settled by: ACC-055 (situation, weaker): "A licence change asks each editor at once without stopping their sync"
- Fix: editor-app says nothing syncs until a licence has been accepted for the first time, and a newer version is asked for without stopping sync (pointing here).

### F10: The server set-up's licence task: different state wording and a different answer to who may accept
- Kind: contradiction
- From: server-install-and-running-1 / Set-up task: the licence
- Here: The server's set-up asks the admin to accept the licence
- From says: "Accepted, the task shows "accepted (<who and when>)"", "\"(no licence agreement is included in this build)\" and cannot be accepted", "Who: anyone before the first account exists; then an admin."
- Here says: "\"accepted v<version>\" (done)", "\"no licence agreement is included in this build, so nothing has been accepted\" (a warning ...)", "Who: an admin."
- Settled by: ACC-057 (situation, weaker) for who: "once the text exists it is incomplete until an admin accepts"; for the wording the owner must say: once the licence is accepted at the server's set-up, does the task show the version accepted, or who accepted it and when?
- Fix: one piece holds the task in full (states, wording, who) and the other points at it; both currently describe it in full.

### F11: The longest sign-in name is 31 characters here and 32 in server-install-and-running-1
- Kind: contradiction
- From: server-install-and-running-1 / Editor accounts on the NAS are made and managed by the dashboard
- Here: A sign-in name has one shape, and a name accepted anywhere works everywhere
- From says: "A username starts with a lowercase letter, followed by up to 31 lowercase letters, digits, dots, underscores or hyphens."
- Here says: "is 1 to 31 characters long" and "(at most 31 characters)"
- Settled by: the owner must say: is the longest sign-in name 31 characters or 32?
- Fix: server-install-and-running-1 says "1 to 31 characters in all" (or this piece moves to 32, sentence included), so both give one length.

### F12: Editors' NAS access is a setting in both pieces, with different defaults and owners, though the owner chose one fixed result
- Kind: contradiction
- From: server-install-and-running-1 / Editor accounts on the NAS are made and managed by the dashboard
- Here: A studio can keep editors to file transfers only on the NAS
- From says: "Setting: What editors may do on the NAS. ... Default: only transfer files. Who: an admin."
- Here says: "Setting: Editors transfer files only. ... Default: off. Who: the person installing the server."
- Settled by: page-12 12.1, answered with the recommendation: "A: one result on both (file transfer only, by key only, confined to the tree, dashboard only on the NAS itself and the private network)"
- Fix: both pieces drop the setting; editors are always transfer-only on the NAS, and this piece drops the conversion report and its refusal.

### F13: The NAS login's password is the person's own password here, a random one nobody is told in server-install
- Kind: contradiction
- From: server-install-and-running-1 / Editor accounts on the NAS are made and managed by the dashboard (also server-install-and-running-2 / Each editor gets their own account on the NAS)
- Here: Every person has one account, and a studio may put its single sign-on in front
- From says: "A new account gets the full name (default the username), the editors' group, a random password nobody is told"; server-install-and-running-2: "a random password the editor never needs to know"
- Here says: "the product keeps each person's NAS login in step with their account, with the same name and the same password, so a person never has a second password to remember"
- Settled by: page-09 9.1, answered with the recommendation: "B: one account per person that the product keeps, whose password it keeps in step with the person's NAS login where the studio uses the shared folders"
- Fix: both server-install pieces say the NAS login carries the person's own account password where the studio uses the shared folders (and is changed with it), not a random one.

### F14: Removing a person deletes their NAS login here; server-install-and-running-2 only cuts their computers off and locks the login if asked
- Kind: contradiction
- From: server-install-and-running-2 / When an editor leaves their computers lose the NAS
- Here: An admin removes a person from the whole product
- From says: "When an editor is removed or suspended, or one of their computers is forgotten, that computer can no longer reach the NAS ... When the admin asks for the account to be locked as well, TrueNAS locks the account and Synology expires it at once."
- Here says: "their account, and their login on the NAS where the studio's NAS holds one, and their access to the shared folders and network drive"
- Settled by: the owner must say: when an admin removes a person, is their login on the NAS deleted with everything else, or kept and only locked when the admin asks?
- Fix: the losing piece changes; if deleted, server-install-and-running-2 says removal deletes the NAS login (lock applying to suspension only) and states what happens to the home folder.

### F15: server-install-and-running-2 points at "the server's secret store", which this piece never describes
- Kind: missing
- From: server-install-and-running-2 / The server holds a limited key for a TrueNAS and never its administrator password
- Here: nowhere ("How secrets and keys are kept" covers editors' computers, passwords shown once, encryption in transit and logs only)
- From says: "The product writes it down nowhere but the server's secret store."
- Here says: nothing
- Settled by: the owner must say: once the server has been given a secret (a NAS key, a mail password, an assistant key), can anyone ever see it again, or can it only be replaced?
- Fix: this piece adds a behaviour under "How secrets and keys are kept" saying where the server keeps the secrets it is given and who may read or replace them, so the pointer lands.

### F16: Computers report their drives to the Footage Sorter, but this piece's full list of what a computer reports leaves drives out
- Kind: missing
- From: footage-sorter-and-camera-cards-1 / Every drive is known by its identity, and the product knows which computer it is plugged into (also footage-sorter-and-camera-cards-2 / Drives are known by their own identity and noticed when plugged in)
- Here: What a computer tells the server; Four kinds of reporting can be switched off, by a computer or for the whole studio
- From says: "Each watching computer tells the studio's record about every card reader and fixed drive plugged into it: its identity, label, file system, size, free space, whether it is removable or fixed, whether it is the system drive, and its drive letter"
- Here says: nothing about drives, while "its list of what computers report matches exactly what they send"
- Settled by: ACC-050 (situation, weaker): "the published report list matches what is actually sent"
- Fix: this piece adds drive reporting (only while the Footage Sorter is on) to "What a computer tells the server" and lists the per-computer drive switch beside the four kinds.

### F17: An admin can set a computer's drive-reporting switch; here the server never sets a computer's own reporting choice
- Kind: contradiction
- From: footage-sorter-and-camera-cards-2 / Drives are known by their own identity and noticed when plugged in
- Here: Four kinds of reporting can be switched off, by a computer or for the whole studio; An editor chooses what their computer reports
- From says: "Setting: Tell the studio about this computer's drives. ... Who: an admin, or the person whose computer it is. Applies to: a computer."
- Here says: "The server can never switch a computer's own choices" and "Who: the editor at that computer, and only there."
- Settled by: the owner must say: may an admin turn a computer's drive reporting off or on from the dashboard, or is that only the editor's choice at that computer, like the other reporting switches?
- Fix: if only the editor, footage-sorter-and-camera-cards-2 changes "Who" to the editor at that computer; if an admin too, this piece states that drive reporting is the one per-computer report an admin may set.

### F18: sync-2 ties a computer to a person on a brand-new dashboard by its name alone; here nobody is assumed in while the studio has no editors
- Kind: contradiction
- From: sync-2 / A computer belongs to a person only once it is tied to a known editor
- Here: Only the people the admin has let in can open the product
- From says: "(on a brand-new dashboard that knows no editors yet, any computer named like a sign-in name counts)"
- Here says: "Being let in is never assumed: not while the studio has no editors yet" and "A report from a computer never adds a name to the list."
- Settled by: ACC-001 (situation, weaker): "The admin decides which accounts may open the product, and every sign-in route, single sign-on included, refuses any account outside that set."
- Fix: sync-2 drops the brand-new-dashboard exception, so a computer belongs to a person only once it is tied to someone the admin has let in.

### F19: whole-product has a computer report every kind when its settings copy is unreadable; here a computer can never turn back on what the studio switched off
- Kind: contradiction
- From: whole-product / A change to the site's settings reaches every computer without a restart
- Here: Four kinds of reporting can be switched off, by a computer or for the whole studio; An admin switches a kind of reporting off for the whole studio
- From says: "When the copy cannot be read, every optional feature counts as off and every switch on what a computer reports counts as on, the safe side in each case"
- Here says: "a computer can never switch back on what the studio switched off" and "if the server cannot read the stored choice it keeps the last one applied rather than quietly reporting again"
- Settled by: the owner must say: when an editor's computer cannot read its copy of the studio's settings, does it go on sending kinds of information the studio switched off (the server throwing them away on arrival), or hold them back until it can read the settings again?
- Fix: whole-product and this piece state the same answer; if held back, whole-product says an unreadable copy counts every reporting switch as off.
