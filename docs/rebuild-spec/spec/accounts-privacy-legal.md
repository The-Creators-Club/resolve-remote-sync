# Accounts, privacy and the legal paperwork

This is who may use the product and what each person may do and see: signing in to the dashboard and on an editor's computer, how a computer is tied to the person it belongs to, stopping and removing a person, passwords and sign-ins, what the product records about people and their computers and the say each person and each studio has over it, the licence a person accepts, the third-party licences a customer receives, and how secrets are kept. Every person meets it: an editor signing in on a phone or a computer, an admin adding and removing people, and the owner deciding what the studio's computers may report. It is part of the core and cannot be switched off. Every switchable part (the b-roll archive, music, YouTube downloads, Timeline Cards, the Footage Sorter) sits behind the same sign-in, knows who is asking in the same way, and refuses the same people.

## Who may sign in

### The studio chooses how people sign in

The person installing the server chooses one of three ways for people to sign in, and the choice holds for the whole site:

| Way | What a person signs in with | Where the password is changed |
|---|---|---|
| NAS accounts (the default) | their account on the studio's NAS and its password; the same password opens the shared folders | on their account page, which changes it on the NAS |
| The studio's single sign-on | their organisation's account, through the organisation's own sign-in service | at the organisation, never here |
| Accounts the product keeps | an account and password kept by the product alone | on their account page |

Whatever the choice, every person has one sign-in name, the same one on the dashboard, on their computers and in every part, and an account is either an admin or an editor.

- Setting: How people sign in. Does: chooses whether people sign in with their NAS account, the studio's single sign-on, or accounts the product keeps itself. Default: NAS accounts. Who: the person installing the server. Applies to: the site. Search words: sign-in method, single sign-on, SSO, NAS account, local accounts.
- Pending: accounts-privacy-legal-Q1

### Only the people the admin has let in can open the product

The admin decides which accounts may open the product, and every way in refuses any account outside that set: the dashboard's sign-in page, single sign-on, the app on an editor's computer, and every switchable part. An account existing on the NAS or at the organisation's sign-in service is not enough by itself: a person is in only once an admin has added them, approved them, or let in a group they belong to (see "Signing in through the studio's single sign-on"). Being let in is never assumed: not while the studio has no editors yet, and not when the product cannot read who it knows (then the sign-in is refused with "cannot confirm your account right now: try again shortly").

The product keeps a list of the studio's people. A name joins it when an admin creates the account, approves the person's computer, or gives them access to a project, and the list keeps when and how each name joined. Names are compared ignoring capitals, and anything that is not a valid sign-in name is ignored. A report from a computer never adds a name to the list.

- Who: an admin decides.

### A sign-in name has one shape, and a name accepted anywhere works everywhere

A sign-in name starts with a lower-case letter, holds only lower-case letters, digits, ".", "_" and "-", and is 1 to 31 characters long. Typed names are trimmed and turned to lower case, and the person is told when capitals were turned to lower case. A name that does not fit is refused where it is first given (creating an account, the first sign-in through single sign-on) with the shape required: "username must start with a letter and contain only lowercase letters, digits, '.', '_', '-' (at most 31 characters)". A name the sign-in accepted works the same in every part of the product, on the NAS and on every computer; no part refuses a name the sign-in accepted, and no part treats such a person as not signed in.

A person who wants to be shown in another script or with spaces and capitals sets a display name (see "A person chooses the name others see").

### The sign-in page

The sign-in page shows the studio's name and a sign-in box: "Use the username and password your admin gave you.", "Your admin creates this account for you. If you do not have one yet, ask them before installing.", a username box (no automatic capitals or spell check), a password box and "Sign in". An empty name or password is refused. After signing in the person goes to the page they were trying to reach, with its query, but only if that page is on this same site; anything else sends them to the overview. A person already signed in who opens the sign-in page is sent straight on, unless they asked to sign in afresh, in which case the form shows with the line "Sign in again to keep this phone or computer working offline for another 100 days." A refusal shows a "refused" state and the message (see "What a refused sign-in says").

A program other than a browser (a script an admin writes) can sign in the same way, under the same rules and limits, and then act as that person.

- Name and search words: Sign in. Search words: sign in, log in, username, password, sign-in page.

### Signing in through the studio's single sign-on

With single sign-on, the sign-in page offers "Sign in with SSO" and no password form. The button sends the person to the studio's sign-in service and back to the page they wanted (only a page on this dashboard; anything else returns to the overview). The round trip must finish within 10 minutes. Every way in, the app on an editor's computer included, goes through the sign-in service; a password is refused.

The first time a person arrives from the sign-in service, the account is tied to that service's permanent identifier for them, one the person cannot change at the service. Every later sign-in finds the account by that identifier, never by the name the service gives, so nobody can take over another person's account by renaming themselves at the service. The name the service gives must fit the shape of a sign-in name once lower-cased; a name with "@", "/" or a backslash, or any other name that does not fit, is refused with the shape required.

A person arriving from the service is let in only when they belong to one of the groups the site allows, or, when no groups are set, when an admin has already added them. Otherwise: "this account is not a member of the group allowed to use this dashboard - ask your admin" or "this account is not part of this fleet - ask your admin to add it".

On the way back the person can be told:

- "this sign-in expired or did not start here: try again";
- "bad sign-in state: try again";
- "the identity provider refused this sign-in" (the service's own reason is not shown);
- "no authorization code in the callback";
- "the identity provider's answer could not be verified", or a short reason when the service pointed the sign-in somewhere else;
- that the account name the service gave is not usable here, with the shape required;
- "this account was removed from the dashboard - ask your admin";
- when the service cannot be reached: "the identity provider is unreachable".

When single sign-on is chosen but not fully set up, both steps answer with the first thing missing. The service's answer must be signed so that only the service could have signed it, and the dashboard's own secret for the service is never sent anywhere the service did not name.

- Setting: Single sign-on service. Does: the address of the organisation's sign-in service (https only, plain http only on the same machine), the dashboard's registration and secret with it, which details are asked for (default the person's name, profile and e-mail), which detail is the account name (default the person's preferred user name), which detail lists groups and which groups are allowed (none means the person must already be added), and the address the service returns to (default worked out from the visit). Default: not set. Who: the person installing the server. Applies to: the site. Search words: single sign-on, SSO, identity provider, groups, organisation account.
- Pending: accounts-privacy-legal-Q2

### An admin's emergency password door under single sign-on

So that a broken sign-in service cannot lock the studio out, the sign-in page also carries "Single sign-on is configured for this dashboard. Admin sign-in if the identity provider is down." "Admin sign-in" shows the password form under an "admin sign-in" divider. Only the admins named at install may sign in there; their password is checked as on a NAS-account site. Anyone else is refused with the ordinary refusal, and it counts as a failed sign-in. When the service cannot be reached, its refusal adds "An admin can sign in at" with a link to this door. The account page tells an admin about this door.

- Who: the admins named at install only.
- Pending: accounts-privacy-legal-Q2

### The sign-in service's admin mark

A site may name a detail and values by which the organisation's sign-in service marks someone as an admin. Such a person gets past the membership check and nothing more; only the admin list and an account's admin role make anyone an admin in the product. The server's set-up says so when such a mark is configured.

- Setting: Sign-in service admin mark. Does: which detail and values from the sign-in service let a person past the membership check. Default: not set. Who: the person installing the server. Applies to: the site. Search words: SSO admin, admin claim, admin group, identity provider.
- Pending: accounts-privacy-legal-Q3

### The admins are named at install, and are never the NAS's own administrator

An admin is anyone named in the admin list given at install (or in the server's set-up), on every sign-in method; where the product keeps its own accounts, an account with the admin role that is not disabled is an admin too. Installing is refused when no admin is named ("name an editor account, not the NAS administrator") and when the list names the NAS's own administrator account, ignoring capitals ("use a separate account"). Names are comma-separated; spaces and blanks are dropped. A person's account page shows where their admin power comes from: the admin list, or their account's role.

- Who: the person installing the server.
- Setting: Admins. Does: the people who are admins on every sign-in method. Default: none; at least one is required. Who: the person installing the server, and the server's set-up. Applies to: the site. Search words: admins, administrators, admin list, who is admin.
- Pending: accounts-privacy-legal-Q10

### A fresh install creates its first admin in a browser

On a fresh install with no accounts, the server's set-up page lets the person installing it create the first admin in a browser. It closes as soon as any account exists, and is never offered again.

### An admin adds a person in one step

An admin adds a person with one action and nothing else: a sign-in name (the shape above), optionally a full name, optionally a password, and, where the product keeps its own accounts, a role (admin or editor, default editor). Nothing the person's computer will need has to be supplied by the admin: the person signs in on each of their computers and that computer is theirs (see "A computer becomes a person's when they sign in on it").

A password, when given, must be at least 12 characters. A blank password makes a random one, shown once to the admin and never again (see "A new password or computer sign-in is shown once, to copy"); where people sign in with their NAS account, a blank password instead leaves the account with a password nobody knows, unusable until an admin sets one.

Refusals: a name that does not fit the shape; "role must be one of ('admin', 'editor')"; "password must be at least 12 characters"; "'<name>' already exists"; and, where people sign in with their NAS account, the NAS being unreachable or refusing, with what it said. Where the NAS creates the account it can take up to two minutes, and the page says so: "This can take up to two minutes while the NAS creates the account. Leave the page open." while showing "creating the account on the NAS...". Warnings from the NAS are shown: "<name>: created with warnings (<list>)". Without the NAS's own password the people page says "This dashboard has no NAS password, so editor accounts cannot be created here. Set it on Settings, Setup (Connect to your NAS)." and offers no creating.

An account made on the NAS is set up there with everything the person needs to sync and to open the network drive, and checked afterwards; any gap is listed for the admin. Creating an existing person's account again repairs it in place.

- Who: an admin.
- Ways in: the people settings.

### An admin manages the studio's people from one list

One list shows every person: "N accounts" or "No editor accounts yet." Each person shows the sign-in name; "shown as" (their display name); role; status (active, suspended, disabled); their computers; and the actions: set a password, suspend or resume, disable or enable (where the product keeps its own accounts), download their data, erase their history, and remove. A person the studio knows by a computer, a plan or a report but who has no account is listed too ("Known to the fleet (a device, a plan or a report), but no account here."), with remove, download data and erase history. When the account list cannot be read: "The account list is unavailable: <error>", with whatever did answer. The list refreshes by itself every 30 seconds, and every action answers with a notice or an error line.

Where people sign in with their NAS account, the list also shows whether the person's account may open the shared folders, and whether the NAS has it locked.

- Who: an admin. Anyone else is told "admins only".
- Name and search words: People. Search words: people, users, accounts, editors, team.

### A studio can keep editors to file transfers only on the NAS

A studio can choose that editors' NAS accounts may only transfer files and never log in to the NAS itself. New accounts then get no login, and the NAS is set so that editors may only transfer files, with no password login; the admin is told whether that was set, was already right, or must be added by hand. Existing editors can be converted: first a report listing every editor and marking who would change, then, once confirmed, each account is converted and reported, ending "All editors are transfer-only." Converting is refused until the studio has chosen transfer-only ("set that first").

- Setting: Editors transfer files only. Does: editors' NAS accounts may move files for syncing but never log in to the NAS. Default: off. Who: the person installing the server. Applies to: the site. Search words: transfer only, no login, NAS login, file transfer.

### A person chooses the name others see

A person can set a display name that other people see instead of their sign-in name. It is only a label shown on screen: records of who did what, sign-ins, sync plans and everything else always use the sign-in name. A person sets or clears their own; an admin can set or clear anyone's.

The name is tidied before saving: the ends are trimmed, every run of spaces, tabs or line breaks becomes one space, and accented letters are stored in one composed spelling. Unchanged text changes nothing. Refusals, with exactly these sentences:

- only spaces: "A name cannot be empty. To go back to your sign-in name, clear the box and save."
- longer than 64 characters: "A name can be at most 64 characters."
- any control, invisible (for example zero-width or right-to-left override), private-use or unassigned character: "A name cannot contain invisible or control characters."
- equal, ignoring capitals and accent spelling, to another person's sign-in name or display name (anyone the studio knows, any account, any admin): "Someone else already goes by that name. Pick another."

A person may use their own sign-in name in any capitals. Two people can never claim the same name at the same moment. Success: "Saved. Other people now see <name>." Clearing the box: "Cleared. Other people now see your sign-in name." For an admin setting another's: "<username> is now shown as <name>." or "<username> is shown by their sign-in name again."; an unknown person: "There is no account called <username>."; a non-admin trying it for someone else is refused. A refused name keeps what was typed. Every change is recorded with the name before and after. A change shows on every page within 30 seconds, and where display names cannot be read, sign-in names are shown.

- Who: the person for themselves, an admin for anyone.
- Ways in: the person's own account page, the people list.

#### Lessons

- Met: ACC-001, ACC-002, ACC-003, ACC-004, ACC-005, ACC-007, ACC-008, ACC-009.
- Tied to an arrangement: ACC-006 (the promise is in "An admin adds a person in one step").

## How a computer proves who it belongs to

### A computer becomes a person's when they sign in on it

An editor's computer belongs to the person who signed in on it from the app (see The app on each editor's computer: Signing in, the computer's identity and the licence). Signing in gives that computer its own sign-in, bound to that one person and labelled with the computer's name. Nothing else is needed: no code passed to an admin, no approval, nothing pasted. One person may have several computers, each with its own sign-in, and adding a computer never takes anything away from the person's other computers.

Only an account that is active, not suspended, not removed and has the editor or admin role can sign a computer in; any other account is refused with the sentence for its case.

A computer's sign-in never ends on a timer. It ends only when an admin withdraws it, when the person's access is stopped or removed, or when the person signs out on that computer (which forgets who was signed in there). A computer's identity never depends on its name: two computers with the same name keep separate, working sign-ins, and renaming a computer changes nothing.

A computer's sign-in and a browser's sign-in can never stand in for each other.

- Who: an editor, on their own computer.

### A computer's sign-in reaches only that computer's own work, as its own person

The app on an editor's computer uses its own sign-in, never a browser's, for everything it does for itself: reporting, reading its sync plan, unticking its own project, moving files to and from the server, downloading updates, reading (never setting) a studio-wide stop, taking and reporting on shared work (proxies, transcription, YouTube jobs, b-roll and music imports, the Footage Sorter's card reports), Timeline Cards' hand-over to Resolve, and finding files. Every part of the product accepts exactly the computer sign-ins the dashboard accepts, by one and the same check, so no part quietly stops working for a computer the dashboard accepts. A sign-in that has been withdrawn is never issued again and never accepted.

In every part, a computer's sign-in acts only as its own person: a computer that states a different person from the one its sign-in belongs to is refused, saying so ("this sign-in belongs to a different editor"). A missing or wrong sign-in is refused before anything the computer sent is read. Nothing a computer's sign-in reaches can be reached by a browser without signing in, and nothing a computer sends can make the server fail.

Only computers of people who are active and have the editor or admin role can move files to and from the server; a disabled, suspended, removed or unknown person's computer is refused.

### A refused computer is told why, and the admin sees it

Each refusal tells the computer, and through it the editor, why:

| Case | What the computer is told |
|---|---|
| no sign-in on the computer | a sign-in is required: use "Sign in" in the app's menu |
| its sign-in was withdrawn by an admin | it was revoked: sign in again from the app |
| its sign-in cannot be checked any more | it is invalid or expired: sign in again from the app |
| its sign-in belongs to a different person | refused, saying so |
| the person was removed | "this account was removed from the dashboard. Ask your admin to add it again if that was a mistake" |
| the person is suspended | "this account is suspended on the dashboard. Ask your admin to press RESUME: your sync plan is untouched and comes straight back" |
| the person's account is disabled | "this account has been disabled on the dashboard. Ask your admin to turn it back on: nothing will sync until they do" |

On the editor's computer a withdrawn sign-in reads "this computer's sign-in was revoked: sign in again from the CC Sync tray".

Each refusal marks the computer on the dashboard with "report refused at <time>" and a plain reason of at most 200 characters, such as "no computer sign-in was sent", "its computer sign-in was revoked by an admin", "its computer sign-in belongs to a different editor", "this account has been disabled", "this account is suspended" or "this account was removed". Only computers the studio already knows are marked. Nothing else from a refused report is kept. The mark clears on the next accepted report.

### An admin sees every computer sign-in and can withdraw one

The admin's list shows each person's computer sign-ins: the person, the computer, a label of up to 64 characters, when it was made, who made it, and when it was last used. It refreshes by itself every minute. Withdrawn sign-ins are left out unless asked for; the list is ordered by person and then newest.

Withdrawing a sign-in is never refused because it is in use. The admin is first asked "Revoke <name>'s sign-in on <computer>? That computer stops reporting and syncing until <name> signs in on it again.", and is then told exactly who stops: "Revoked. <A | A and B | A, B and N more> was using this sign-in and will stop reporting within a minute." or "Revoked. No computer's last report used this sign-in, so nothing should stop reporting." Withdrawing one already withdrawn does nothing: "that sign-in was already revoked (or never existed)". A withdrawn sign-in is kept on the list, marked revoked with when and by whom, and forgotten 180 days after it was withdrawn; a live one is never forgotten. Where it is not known which computers use a sign-in, the list says "cannot tell", never "none".

- Who: an admin.
- Name and search words: Computer sign-ins. Search words: computer sign-in, revoke, device access, credentials, lost laptop.

### An admin ends every computer sign-in a person holds, at once

For a laptop that was lost or taken, an admin can end every computer sign-in a person holds. Every sign-in made for that person's computers before that moment stops working at once and for good: their computers are refused at their next report, and the app asks the editor to sign in again, which works at once on a computer they still have. A computer signed in afterwards is not affected. A later change of the server's clock can never bring an ended sign-in back. Nothing is deleted and no plan changes. It is recorded in the history.

- Who: an admin.
- Pending: accounts-privacy-legal-Q6

### An admin issues a computer sign-in by hand

An admin can make a computer sign-in for a person by hand (the sign-in name rules apply, with a label of up to 64 characters). It is shown once only (see "A new password or computer sign-in is shown once, to copy"), with "Send it to whoever set up <name>'s computer: it goes into the app's settings, and the app has to be restarted before it takes effect." The server keeps only enough to check it, so it can never be shown again. The editor can paste it into set-up on that computer, or leave it for later: set-up then finishes NOT READY, with a warning that the dashboard will refuse every report from this computer until it is in. A pasted value with spaces before or after is refused ("remove the space"), and anything not shaped like a computer sign-in is refused ("that is not a computer sign-in"). A sign-in already on the computer is never cleared by set-up.

- Who: an admin makes it, the editor pastes it.
- Pending: accounts-privacy-legal-Q5

### A site may let computers report without a sign-in of their own

A site can allow computers to report with one sign-in shared by the whole studio, beside each person's own. Off by default. While it is allowed, a computer using it must still carry its signed-in person's identity, and the admin's list of computer sign-ins shows how many computers still use it, named as person/computer: "N computer(s) still report with the SHARED studio-wide sign-in: <names>. Once this is empty, it is safe to switch the shared sign-in off." or "All N reporting computer(s) use their own sign-ins. The shared sign-in is no longer used by anything: it is safe to switch it off."

- Setting: Shared studio-wide computer sign-in. Does: lets computers report with one sign-in shared by the whole studio as well as their own. Default: off. Who: the person installing the server. Applies to: the site. Search words: shared sign-in, studio key, shared credential, shared key.
- Pending: accounts-privacy-legal-Q4

### Changing the server's own secrets signs nobody out

When the server's own signing secret is changed, every existing computer sign-in and browser sign-in keeps working, on every request, in every part, until the admin chooses to retire the previous secret. The dashboard shows how many computers still sign in under the previous secret and names them as person/computer, with the time each last did (up to the newest 200), so the admin knows when retiring it is safe. Once it is retired, each of those editors signs in again with one "Sign in..." click in the app. Seven days after a change, if computers still use the previous secret, admins are warned: "computers are still on the old sign-in key". A computer refused for this reason is named with the fix: sign in again from the app.

- Who: an admin.

#### Lessons

- Met: ACC-010, ACC-011, ACC-012, ACC-013, ACC-014, ACC-015, ACC-016, ACC-017.

## Suspending, disabling and removing a person

### Stopping a person takes effect everywhere at once

Suspending, disabling and removing a person each take effect at the very next request, everywhere, all or nothing: every browser sign-in of theirs ends, every computer of theirs is refused wherever it reaches the server (reporting, signing in, reading its plan, moving files, shared work, and the b-roll archive, music, YouTube downloads, the Footage Sorter and Timeline Cards), and the server stops sharing projects with their computers within a minute. Every part asks the same one question, "may this person act?", so no door is left open. A request from such a person's computer to a switchable part (sending a clip from the b-roll archive, downloading a YouTube video on the editor's own computer) is answered as if no sign-in was given. The confirmation an admin answers states all of this before anything happens.

The product never takes an answer it could not read as "this person is fine". While it cannot tell whether a person is suspended, disabled or removed, it changes nothing: it shares nothing new with that person, unshares nothing that was already shared, and lets no suspended or removed person through; their computer is told "cannot confirm your account right now: try again shortly".

The admin's view of computers and the alert for refused reports show the short reason: "this account has been disabled", "this account is suspended" or "this account was removed".

### An admin suspends a person and resumes them with nothing lost

Suspending works whatever the sign-in method, for anyone the studio has. The admin is asked "Pause syncing for <name>? Their browsers are signed out, their computers are turned away and their projects are unshared. Their sync plan is kept and "Resume" puts it back." An optional reason of up to 255 characters is shown on the person's row and in the history, and is never sent to their computer. The notice reads "<name> is suspended. Their computers are being turned away and their projects will be unshared within a minute. The sync plan is untouched: RESUME puts it all back."

While suspended, the person cannot sign in anywhere and their computers are refused with the suspended sentence. Their ticks are untouched, and an admin can still read their plan. The suspended state shows on every page that shows the person. Resuming brings back exactly what was ticked: "<name> is back. Their projects are shared again on the next cycle, exactly as they were." Suspend and resume are recorded with when, by whom and why.

Refusals: "not a valid username"; "you cannot suspend the account you are signed in as - sign in as another admin to suspend this one"; "'<name>' is not an editor this dashboard knows"; resuming someone who is not suspended.

- Who: an admin.
- Ways in: the people list.
- Pending: accounts-privacy-legal-Q7

### An admin disables an account and turns it back on

Where the product keeps its own accounts, an admin can disable one. The admin is asked "Stop <name> signing in? Their browsers are signed out and their computers are turned away. Their computers keep their projects until you untick them." A disabled account cannot sign in anywhere and is not an admin; every browser sign-in of the person ends and every computer sign-in of theirs is withdrawn, so their computers stop reporting. From outside, a disabled or unknown account looks the same as a wrong password. Turning it back on restores only the password: the person signs in again on their browsers and computers. The admin is told how much was ended, and both acts are recorded in the history. Where the product keeps its own accounts and at least one exists, a name with no account at all is treated as disabled.

- Who: an admin.
- Pending: accounts-privacy-legal-Q6

### An admin can never stop their own account or the last admin

Disabling, suspending or removing the account you are signed in as is refused: "you cannot disable the account you are signed in as - sign in as another admin to disable this one" (and the same in "suspend" and "delete" wording). Disabling or removing the last enabled admin is refused: "this is the last enabled admin account - create another admin before disabling it" (and the same in "delete" wording).

### An admin removes a person from the whole product

Removing a person takes away everything that let them in and everything about them, in one act:

- their account, on the NAS too where people sign in with NAS accounts, and their access to the shared folders and network drive;
- every computer of theirs, which stops receiving anything, with each computer's plan and records; the files on their computers stay where they are;
- every browser sign-in and computer sign-in, ended and deleted;
- their history, their diagnostics, their sharing connections and completion records, their profile and display name, their place in the studio's list of people, and their membership of every project;
- their unfinished YouTube downloads, stopped and cancelled, with the search terms of their jobs deleted.

What must stay as evidence (the history of what was done, alerts, problems, YouTube download history, the client folders they made) stays, with their name and their computers' names replaced by a stand-in (see "A removed person becomes the same stand-in name everywhere"). Free text typed into a client folder (contact, description, notes) is not changed, and client links keep working.

The admin is asked "Delete <name>: their account, their computers and their sync plans? "Suspend" only pauses them." and told what was removed. If something the removal needs cannot be reached (the NAS, or the sharing of projects with computers), nothing is removed and the admin is told what could not be reached, so nothing was deleted, and to try again once it is up. Refusals: "not a valid username"; yourself and the last admin (above); "'<name>' is not an account or an editor this dashboard knows". A name the studio knows only through a computer or a plan, with no account anywhere, can be removed the same way.

The history records the removal under the stand-in name, with counts of what went.

- Who: an admin.
- Ways in: the people list.

### A removed person becomes the same stand-in name everywhere

A removed person becomes "deleted-user-" and each of their computers "deleted-machine-", each followed by 10 characters made from the name and a secret the site makes once and never changes, so one person always becomes the same stand-in and nobody can work the name back out. The replacement is made everywhere the name stands, at once, including the b-roll and music records, YouTube records and client folders:

- fields saying who did something, and entries of the history made by or about the person;
- subjects that name the person or one of their computers;
- free text (alert details, problem descriptions and advice, history details) on entries tied to the person, whole names only and with exact capitals, so "alice-b", "alice.smith" and "Send a test email" survive removing "alice" or "test";
- the computers holding or chosen for shared work.

A computer name someone else also uses is never rewritten. Where a renamed problem collides with an existing one, the newer is kept. The removal is refused when no stand-in name can be made.

### No report ever brings a removed person back

Removing a person leaves a lasting mark. A computer that keeps reporting under the removed name, or signs in with it, is refused and never re-creates the person; neither does any sign-in through the NAS or the organisation's sign-in service, even where the account still exists there (a removed person whose NAS password still works is refused with the ordinary sign-in refusal). Only an admin lifts the mark, by creating the account again or adding the person again. Sign-ins made before the removal stay dead after the person is added again.

### A new account with a removed person's name starts with nothing of theirs

A person added under a name that once belonged to a removed person starts with none of the removed person's projects, access, ticks or rights. It keeps whatever is given to the new account directly.

#### Lessons

- Met: ACC-018, ACC-019, ACC-020, ACC-021, ACC-022, ACC-023, ACC-024, ACC-025.

## Passwords, sessions and failed sign-ins

### What a refused sign-in says

A sign-in is checked in this order, and the first that applies is what the person is told:

1. The server has no sign-in set up: "login not configured on the server".
2. The site is set to secure connections only and the page was reached over plain http: the page says "this dashboard is configured for https only but you reached it over http. Use the https URL." and the form "use the https URL". This does not count as a failed sign-in.
3. Too many recent failures for this name or from this address: "Too many sign-in attempts. Try again in a minute." or "... in N minutes." (see "Wrong passwords make the next try wait"). Made-up names are held back exactly like real ones.
4. Too many sign-ins being checked at once: "the server is busy checking sign-ins. Try again in a moment." This does not count as a failure.
5. A wrong password, an unknown name, a disabled account, or a person who was removed (even if their NAS password still works): one sentence for all, "sign-in refused - check your username and password, then try again". It never says which half was wrong. Every such failure counts.

Oversized or malformed sign-in requests are refused. A sign-in name is at most 31 characters (above) and a password at most 1024.

A successful sign-in clears that name's failures, ends whatever sign-in that browser had before, starts a new one the server can end later, and says who is signed in and whether they are an admin. Anyone can ask who is signed in and whether they are an admin.

### Wrong passwords make the next try wait

Failures are counted per sign-in name (5 allowed) and per network address (40 allowed) within an hour. Reaching either limit makes the next try wait 1 minute, doubling with each further failure (1, 2, 4, 8 minutes ...) up to 1 hour; the longer of the two waits applies. A failure older than an hour stops counting. The person is told the wait in whole minutes, rounded up: "Too many sign-in attempts. Try again in a minute." or "Too many sign-in attempts. Try again in N minutes.", never more than 60. Made-up names are held back exactly like real ones, so the wait never reveals which names exist.

One person's failures never lock out anyone else: the per-address limit is high enough for a studio sharing one address, and a successful sign-in clears only that name's count, never the address's, which ages out by itself. The counts survive a restart of the server. The same limits apply to signing in on the dashboard, signing in from the app on an editor's computer, and the current password on the change-password form. Every failure is recorded with the name and the address, never the password.

### A browser sign-in lasts 100 days, and warns two weeks before it ends

A browser stays signed in for 100 days from the moment it signed in, used or not, so a phone used offline for weeks stays signed in. There is no "never ends". Every page knows when its sign-in ends.

Once 14 days or less are left, a note appears at the top of each page, without blocking anything: "Your sign-in expires in <N days | less than a day>. Sign in again now so this phone/computer keeps working offline for another 100 days." "Sign in again" renews the sign-in in place while it is still live and returns to the same page; "Not now" hides the note until the next calendar day. The note shows only while the device is online, and checks the real end with the server, since a saved page may carry an earlier one. The sign-in page itself shows no note.

When the sign-in has ended the person is told "Your sign-in has expired. Sign in again." An ended sign-in never deletes anything saved on the device.

- Phone and desk: the same on both; the note matters most on a phone used offline.

### A visitor who is not signed in is sent to sign in and brought back

Opening any page without a sign-in goes to the sign-in page and, after signing in, back to the page asked for, with its query. A part of a page refreshing itself after the sign-in has ended sends the whole browser to the sign-in page, and afterwards back to the page that part belongs to. In the b-roll archive and the other switchable parts, the next action after a sign-in ends shows "Session expired, signing in again..." and does the same. A request for data with no sign-in is answered "Your sign-in has expired. Sign in again."

### Signing out, and signing out everywhere

Signing out ends this browser's sign-in on the server at once and lands on the sign-in page. A real sign-out (not an ended sign-in) also deletes the list of Timeline Cards episodes saved on that device. Signing out everywhere ends every sign-in of this person on every browser and device. Neither touches the person's computers' own sign-ins.

- Who: anyone signed in, for themselves.
- Ways in: the header's sign out and sign out everywhere, the person's own account page.
- Pending: accounts-privacy-legal-Q9

### A person sees every browser signed in as them and signs out the others

The person's account page lists every browser signed in as them ("Every browser signed in as <name> (N now)..."), refreshed by itself every 30 seconds: its network address (the person's real address, taken only from what the studio's own front server recorded), the browser as a short description such as "Chrome, Windows" ("Unknown browser" when nothing is recognised; the product's own app and command-line tools named as such), when it signed in, and when it was last seen (to within about a minute), with "this browser" marked. "Use these if a computer or a phone was lost."

- "Sign out" on another browser asks "Sign out <browser>? Whoever is using it has to sign in again." and answers "Signed that browser out." Refusals: "That is not a browser on this list.", "That browser is already signed out.", "Two browsers match that; use sign out the others instead.", and for this browser "That is this browser. Use Sign out instead."
- "Sign out the others" asks "Sign <name> out of the other N browser(s)? This one stays signed in." and answers "Signed out <n> other browser(s). This one stays signed in." or "No other browser was signed in."; with no other: "Only this browser is signed in."
- "Sign out everywhere".

Another person's sign-in can never be touched from here. Each sign-out is recorded. Ended sign-ins disappear 7 days after they ended.

- Who: anyone signed in, for themselves.
- Pending: accounts-privacy-legal-Q9

### An admin sees every browser signed in across the studio and signs a person out

An admin sees every live browser sign-in in the studio, up to 200 at a time, refreshed every 30 seconds: "Revoking signs that account out everywhere within a second. The computer's own sign-in is separate and is not affected." Each shows the name ("(you)" for the admin), when it signed in, when last seen, the address and browser, and "revoke all", which asks "Sign <name> out of every browser? They will need to sign in again. Their computer's own sync is not affected." and answers "revoked N session(s) for <name>". On the admin's own row it reads "sign me out everywhere". With nobody signed in: "Nobody is signed in through a browser right now." Refused with "username required" for an empty name.

- Who: an admin.
- Name and search words: Signed-in browsers. Search words: sessions, signed in, sign out, browsers, devices.
- Pending: accounts-privacy-legal-Q9

### The one rule for a new password

A new password is at least 12 characters, and that is the only rule. It applies wherever a password is set (creating an account, an admin setting one, a person changing their own) and is checked with the same words on the page as typed and on the server: "password must be at least 12 characters". A password set before is never checked against it.

### A person changes their own password

On their own account page a person changes their password. With single sign-on: "You sign in with your organisation's account, so there is no password here to change. Change it where your organisation looks after its accounts.", with the note that changing it there does not sign them out here. Otherwise the page says what it changes (a NAS account: the password for the dashboard and the shared folders; an account the product keeps: only this sign-in), "it leaves alone: Syncing.", "afterwards: Every other browser signed in as <name> is signed out at once; this one stays signed in.", and "forgotten it?" (an admin can set one).

The form asks for the current password, the new one ("at least N characters: that is the only rule"), and the new one again, with "show what I typed" for all three. Under the new password a count reads "0 of <min> characters", "<n> of <min> characters: <k> more to go" or "<n> characters: long enough"; under the repeat, "type it again", "the two match" or "the two do not match yet". "Fill in all three boxes, then press Change password. Nothing changes until the server says so." Then "Change password".

Checks, in this order, with nothing changed on any refusal and what was typed kept in the boxes:

1. A sign-in method the product cannot change passwords for: "This dashboard does not know how to change passwords for its sign-in method. Ask your admin. Nothing changed."
2. "The two new passwords are not the same. Nothing changed."
3. "The new password needs at least <n> characters. Nothing changed."
4. "The new password is the same as the current one. Nothing changed."
5. Too many wrong tries: the same wait as the sign-in page, which wrong current passwords here count towards.
6. An admin named in the admin list with no account the product keeps: "<user> is not an account this dashboard keeps a password for. Ask another admin, or change it where that account lives."
7. The current password is checked as at sign-in: "The server is busy checking other sign-ins. Try again in a minute. Nothing changed." or "That is not your current password, so nothing changed. Several wrong tries in a row make this form wait, like the sign-in page."; a right one clears the wrong-try count.
8. Where people sign in with their NAS account: "This dashboard holds no server credential, so it cannot change server passwords. Ask your admin."; "Could not reach the server, so nothing changed. Try again in a minute."; "The server does not let this dashboard change the password of <user>. Change it in the NAS's own settings, or ask your admin."; "The server refused the change, so nothing changed. Try again, or ask your admin." The NAS's own error text is never shown.

Anything over 1024 characters: "A password must be text of at most 1024 characters. Nothing changed." A typed password is never shown back, logged or echoed.

On success this browser gets a fresh sign-in and every other browser signed in as the person is signed out; their computers' sign-ins are not affected. The page reloads and reads "changed", "Password changed." and one of "Signed out N other browser(s); this one stays signed in.", "No other browser was signed in; this one stays signed in." or, when that cannot be told, "Your other browsers may still be signed in: check signed-in browsers below, or use Sign out everywhere."; for a NAS account also "Use the new one for the shared folders too." The change is recorded with how the person signs in and how many other sign-ins existed, never the password or its length.

- Who: anyone signed in, for themselves.

### An admin sets a person's password

An admin sets a new password for a person: "Set a new password for <name>? Their old one stops working now." (on a NAS account, "It is their NAS login too.": the dashboard, the shared folders and syncing all stop accepting the old one). An empty box: "password required". The one rule for a new password applies; where people sign in with their NAS account, the NAS refuses system accounts and anyone who is not one of the studio's editors. On success every browser sign-in of that person ends, except the admin's own current one when they set their own, and the admin is told: "Password set for <name>. Tell them the new password: it is not shown here again." or "Password set for <name>, and signed out N session(s) of theirs. Tell them the new password: it is not shown here again." The reset is recorded in the history with how it was done and nothing about the password. Refused for a name that is not an account ("'<name>' is not a local account").

- Who: an admin.
- Ways in: the people list.

### An account can be marked to change its password at its next sign-in

When an admin sets a password, the account can be marked so that the person must choose a new password the next time they sign in, before they reach any page.

- Who: an admin.
- Pending: accounts-privacy-legal-Q8

### Signing in over plain http on a site set to secure connections only

A site can be set so that browser sign-ins work only over a secure (https) connection. By default a sign-in is marked secure exactly when the visit came over https; it can be forced on or off. Forced on, signing in over plain http is refused (see "What a refused sign-in says"), and that is not counted as a failed sign-in.

- Setting: Secure connections only. Does: refuses browser sign-in over plain http. Default: follows how each visit arrived. Who: the person installing the server. Applies to: the site. Search words: https only, secure, encrypted, http.

### Timeline Cards run by itself asks for its own password

When the Timeline Cards editor is run on its own, apart from the dashboard, and is reachable from other computers, it will not start without a password of at least 8 characters ("set a password (8 or more characters) and the editor will ask for it"). Reachable only from its own computer, it still asks for one when the person running it sets one.

The sign-in page: title "Log in - Timeline Cards", the Timeline Cards mark and "TIMELINE CARDS", heading "Log in", the text "This editor is open to the network, so it asks for its password.", one "Password" field (focused, the browser may fill it), and a "Log in" button, disabled while sending. A wrong password shows "That is not the password." under the form and selects the field; any other failure shows the server's sentence, or "The login failed."; no answer shows "The server did not answer.". It works without scripts too. The page cannot be shown inside another page. After signing in the person lands on the page they first asked for (anything odd becomes the start page); visiting the sign-in page while signed in goes straight there. Any page asked for without a sign-in goes to the sign-in page; anything else is refused "log in first".

A sign-in lasts 30 days by default (at least 1 day), renewed on a page load once less than half is left. Restarting the editor keeps everyone signed in; changing the password signs everyone out; signing out ends that browser's sign-in. Wrong passwords: from one address the first 5 failures are free, then each further failure waits 2, 4, 8 ... seconds, at most 5 minutes, cleared only by a successful sign-in; from one network 20 free failures, and across the whole editor 100, then the same doubling, forgotten 10 minutes after their last failure. While a wait applies: "Too many wrong passwords. Try again in N s.".

- Pending: accounts-privacy-legal-Q11

#### Lessons

- Met: ACC-026, ACC-027, ACC-028, ACC-029, ACC-030, ACC-031.

## What each person may see and reach

### Everything needs a sign-in except a short list of open doors

Every page and every piece of data needs a signed-in person, except:

- the sign-in page, signing in and out, and asking "who am I";
- the server's set-up page while no admin exists yet (see "A fresh install creates its first admin in a browser");
- the server's health answer, which says only whether the server is up and its version, nothing else;
- the studio's public description that installers and the app on editors' computers read (studio name, drive letter, addresses, which parts are on);
- what a phone needs to install the dashboard or Timeline Cards as an app (icons, the app's description, the offline page), read only;
- a client folder link in the b-roll archive and a shared folder link in the Footage Sorter, where the link itself is the credential;
- the doors an editor's computer uses with its own sign-in (see "A computer's sign-in reaches only that computer's own work, as its own person"), which still check that sign-in.

There are no public pages describing how to drive the server. Every rule about what is open or closed applies to the address as the server will act on it, however it was spelled (a doubled slash, odd capitals or encoded characters reach no page a plain spelling would not), and when in doubt a page behind the sign-in refuses.

### Admin-only actions refuse everyone else, and a change must come from the product's own pages

An action reserved for admins refuses a signed-in non-admin with "admins only" and someone not signed in with "log in first". A change made from a signed-in browser is accepted only when it comes from the product's own pages, so another website open in the same browser can never act in a person's name. Every page tells the browser to refuse being shown inside another site and to load nothing from places the product does not name. Every way to change or upload anything refuses when its protection is not set up, and every upload is capped in number of files and size.

### Who is an admin, and what an admin sees

An admin is anyone in the admin list (see "The admins are named at install, and are never the NAS's own administrator"), and, where the product keeps its own accounts, any account with the admin role that is not disabled. Nothing else makes anyone an admin. An admin sees the whole studio and can look at any page as one named editor sees it. A person may change an editor's settings if it is themselves or they are an admin.

An admin can turn on a second step at sign-in for their own account, a six-digit code from an authenticator app on their phone, asked for after the password. Once on, their sign-in on any browser needs the code.

- Setting: Second step at sign-in. Does: asks this admin for a code from an authenticator app after the password. Default: off. Who: the admin for their own account. Applies to: a person. Search words: two-factor, 2FA, authenticator, second factor, code.

### An editor sees their own computers in full and everyone else only as counts

The project list, each project's page, transfers, who holds which media, and the view of each computer are all narrowed to the person looking. An editor sees their own computers' rows; for the rest of the studio they see only totals with no names (computers in total, how many are fine, how many are unhealthy, how many are out of date) and a count of rows hidden from them. Lists of computers whose downloads stopped themselves, that are halted, lost, or whose reports are refused show only their own. The studio-wide stop is shown to everyone in full. An editor does not see the server's own health, warnings about the release feed, or the progress of a change of the server's secrets.

Asking for something one may not see answers exactly as if it did not exist: an unknown project is answered "unknown project '<name>'"; asking for the missing files of a computer that is not in the project, or that belongs to another person when the asker is not an admin, is answered "device not in project", so an editor cannot even learn that another person's computer or batch exists.

- Who: every signed-in person, narrowed to what they may see.

### Each project is reachable only by its members

Each project's folder on the NAS can be opened, changed or deleted only by its members, and folders above a project are protected so that nobody can remove or rename what is not theirs. A person is a member of a project when they have ticked it on any of their computers (full or upload only) and it is not archived, or when an admin has given them access. Giving access is the way in for a person whose computers only work straight off the server and so tick nothing. Membership follows ticks and grants within a minute. A membership added by hand on the NAS is never removed by the product. Creating a project that already exists grants nothing to anyone. An editor can delete only a project they are a member of.

On each project's page an admin sees "given access by an admin" (each person, marked "(also ticks it)" where they tick it too, with "Remove", which asks "Remove <name>'s access to this project? Nothing on disk is deleted."; empty: "Nobody yet. People who tick this project get in by the tick.") and "in by their tick" (everyone who ticks it). A person choice and "Give access" ("choose a person first" when none). Results: "access given", "<name> can now open this project. The server applies it within a minute." and "access removed", "<name> no longer has access through this list. Someone who ticks the project still gets in by the tick." Giving access to a name the studio does not know is refused ("unknown editor '<name>'"). Every change is recorded in the history.

- Who: an admin.
- Ways in: the project's own page.

### A studio can let every editor open every project

A site can choose that every editor reaches every project. Each project's access list then reads "Every editor can open every project on this server (project access is set to shared). People you add here are remembered, and take effect if the server is switched to per-project access."

- Setting: Every editor opens every project. Does: lets every editor reach every project instead of only the projects they are members of. Default: off. Who: an admin. Applies to: the site. Search words: project access, shared access, per-project, permissions.
- Pending: accounts-privacy-legal-Q12

### Every switchable part sits behind the same sign-in and knows who is asking

The b-roll archive, music, YouTube downloads, the Footage Sorter and Timeline Cards are reachable only through the dashboard's sign-in. Each is told, by the product itself and only from inside the server, who is signed in and whether they are an admin; nobody can pass themselves off as someone else, and a sign-in the server has ended is never honoured. No setting can make a part trust an identity it was handed from outside.

### Timeline Cards and the Footage Sorter are reached only through the dashboard

The Timeline Cards editor and the Footage Sorter answer nothing to a device that has not signed in to the dashboard, even on the studio's private network. A request that does not come through the dashboard is refused "this editor is reached through its dashboard". The editor knows the signed-in person's name from the dashboard.

- Pending: accounts-privacy-legal-Q11

### The Footage Sorter on a single computer, without a sign-in

The Footage Sorter can also run as a program on one Windows computer, reachable only from that same computer, where anyone using that computer can do everything in it: no sign-in, no roles.

- Pending: accounts-privacy-legal-Q13

### Anything listening on an editor's computer answers only the product's own pages

Anything of the product's that listens on an editor's computer (the app receiving clips and tracks sent from the product's pages, Timeline Cards' link to Resolve) answers only the product's own pages and the dashboard the computer belongs to. A change, a data request, a live connection, or a sound or picture that a page on another website tries to load is refused ("requests from another site are not accepted"). It answers only to its own computer's names and plain numeric addresses (and to extra names the person running it lists, none by default); anything else is refused "this server does not answer to that host name", so an outside website cannot pose as it. It never opens a path outside its own folders. Each refusal is written to the computer's log.

### Every person has one page about themselves

Every signed-in person has an account page that is always about them; no address can make it show someone else. Not signed in: "Sign in first." It reads "signed in as <name> · admin/editor · server password / local account / single sign-on · N computer(s), N wired to the server". Admins also read "This page is about you only. To change someone else's password, sign them out, or look after their computers, use the people settings."

It holds, in one place:

- their display name, with the name box (see "A person chooses the name others see": up to 64 characters, the sign-in name as placeholder, "Clear the box and save to go back to it.", "Save");
- their sign-in name: "cannot be changed: it is the key every computer, plan and file uses";
- their role (admin, and whether from the admin list or their account's role; or editor);
- how they sign in ("your account on the server", "a local account kept by this dashboard", "your organisation's single sign-on") and facts about their password, with "Change your password" where it can be changed here;
- "active" or "suspended by an admin";
- each of their computers, remote and wired listed apart, including computers no longer heard from. For each: Windows or Mac, wired or remote, its app version and whether it is up to date ("up to date" when it matches the current one or no current one is known), when it last reported, whether it is live, why it is in its state, the licence it accepted, which kinds of reporting it withholds, its sync plan (each project, full or upload only), its share of heavy work, the settings it last reported and any change waiting for it. Each computer's part refreshes by itself, and disappears if the computer stops being the person's;
- the site's facts: the drive letter the project tree appears as (P: by default), whether automatic updates are on, whether YouTube downloads are on, and whether the studio's syncing is stopped;
- the browsers signed in as them (see "A person sees every browser signed in as them and signs out the others");
- "your data" with "Download" (see "A person downloads everything the product holds about them").

A script signed in as the person can fetch the same information.

- Who: anyone signed in, for themselves.
- Name and search words: My account. Search words: account, profile, my computers, password, display name, my data.

### A person or an admin asks one of the person's computers to change its settings

From the account page, a person (or an admin, for anyone) can ask one of the person's computers to change whether it takes shared heavy work and which kinds (see Work shared out across the computers). Whether a computer is wired or remote can never be asked for from the dashboard; it is set only on the computer. The page offers only settings that computer can take. The request waits until the computer next checks in, and is shown as waiting until the computer answers "applied" or "refused"; a request not answered within 14 days expires, and says so. Each computer shows how long it volunteers, how often it reminds about an unplugged sync drive, its YouTube status (downloads on, sign-in enabled, terms accepted, signed in), which of its settings wait for the app to restart, and its answer to the last request. When the computer cannot say whether a restart is waiting, the page says it cannot tell.

- Who: the person for their own computers, an admin for anyone's.
- Pending: accounts-privacy-legal-Q14

### Help shows each person only what their role may see

The product's help holds only guides written for its customers and its legal documents. It lists and opens only what the role of the person looking may see: an editor never reaches an admin's guide, and nobody reaches anything written for the people who build the product.

#### Lessons

- Met: ACC-034, ACC-035, ACC-036, ACC-037, ACC-039, ACC-040, ACC-041, ACC-042, ACC-043, ACC-044, ACC-045.

## What the product records about a person

### What a computer tells the server

Every computer tells the server, whatever its switches:

- who is signed in on it, the computer's name and its permanent identity, the app's version, the operating system and the kind of processor;
- for each direction of syncing: its state, how much is waiting and moving, the last error, when it last synced, the project it is on, bytes done and total, speed, time left and the files moving now, and the files finished since it last reported;
- the queue of ticked projects and the one being synced, whether it syncs or works straight off the server, the state of its connection to the server;
- which originals have no proxy, safety stops, its trash size, any studio-wide stop it holds, Resolve's health;
- its answers to file moves and undo requests the server sent, what it can do, its shared-work settings and whether they wait for a restart, a b-roll or music batch in progress, the state of importing YouTube clips, how its reports and updates are going, how many crash reports it holds;
- the licence it accepted (version, when, and a fingerprint of the exact text);
- which kinds of reporting it withholds.

Unless withheld (below), it also tells the server the open Resolve project, which media files are on its disk per project, the Resolve bin structure, the undo records it holds, and how long since its keyboard or mouse was last used. What the dashboard shows of a computer's media and bins is never more than about 10 minutes behind while the computer is on. Sync status is always sent in full, however much else a computer holds.

### Four kinds of reporting can be switched off, by a computer or for the whole studio

Four kinds of information about a person's work can be switched off, each on one computer (all on by default) and for the whole studio (all on by default). A kind is reported only when both the computer and the studio allow it. The kinds, and what switching each off costs:

| Kind | What it covers | What is lost when off |
|---|---|---|
| The name of the open Resolve project | the open project wherever it appears, the projects with clips only on that computer, the project named on each undo record, project names in answers to undo requests | also switches off the bin structure; the dashboard does not offer to set up a new project for it; the editor cannot be the first to tie a Resolve project to a folder (an admin can); projects are not tied automatically from this computer |
| The list of media files on this computer | the list itself, and the names of missing clips, refused clips, files in sync conflicts, stray and moved project folders and example skipped files (counts remain) | every file move in every active project is sent to this computer; what it holds and its upload progress show as not reported |
| The Resolve bin structure | the bin structure | nothing else; also off whenever the project name is off, because bins are organised by project |
| How long since the keyboard or mouse was used | the idle time itself | the computer counts as someone being at it, so background work that waits for an idle computer is not offered to it |

Switching a kind off withholds the report, never the work: syncing, relinking, checks and everything else still run, and the editor's own undo from the app works whatever is withheld. Undo records are still listed, with project names shown as "<project>" or "(detail withheld: this computer does not report project names)", so an admin can still ask for an undo.

Never withheld, because syncing or the person's own action needs them: names of files being and recently transferred, the result of a file move the dashboard ordered, a project name the editor types or sends when setting up a project, and, only if the Timeline Cards hand-over is on for this computer, the project and timeline it is driving.

The server can never switch a computer's own choices, and a computer can never switch back on what the studio switched off.

### An editor chooses what their computer reports

On the editor's computer, the app's settings carry "PRIVACY: what this computer tells the dashboard. Sync is not affected." and four on/off rows: "The name of the open Resolve project", "The list of media files on this computer", "The Resolve bin structure", "How long since the keyboard or mouse was used". Flipping one takes effect from the very next report: "This computer will report <item> again from its next report." or "This computer will stop reporting <item>. The dashboard forgets what it held on the next report. Sync is not affected." If the choice cannot be saved: "Couldn't save that - see the log." A kind the studio switched off shows off with "(Turned off for everyone by your administrator)" and cannot be changed here; the bins show off with "(Off while the project name is off)" whenever the project name is off. A greyed row keeps this computer's own answer underneath.

Set-up offers the same choice as one of its steps: choose what this computer tells the dashboard; sync works the same whichever you pick; you can change these later in the app's settings for this computer; switching one off also deletes what the dashboard already holds about it. Four tick boxes, each with a grey line saying what is lost when off (the table above), start from this computer's own earlier choices (all on for a new computer). A grey footer lists what is still sent because syncing or the editor's own action needs it.

- Who: the editor at that computer, and only there.
- Ways in: the app's settings, set-up.
- Setting: Report the open Resolve project. Does: lets this computer tell the dashboard the name of the open Resolve project. Default: on. Who: the editor at that computer. Applies to: a computer. Search words: privacy, Resolve project, report, project name.
- Setting: Report the media files on this computer. Does: lets this computer tell the dashboard which media files it holds. Default: on. Who: the editor at that computer. Applies to: a computer. Search words: privacy, file list, media, report.
- Setting: Report the Resolve bin structure. Does: lets this computer tell the dashboard its Resolve bins. Default: on. Who: the editor at that computer. Applies to: a computer. Search words: privacy, bins, Resolve, report.
- Setting: Report keyboard and mouse idle time. Does: lets this computer tell the dashboard how long since it was last used. Default: on. Who: the editor at that computer. Applies to: a computer. Search words: privacy, idle, keyboard, mouse, presence.

### An admin switches a kind of reporting off for the whole studio

An admin can switch each of the four kinds off for every computer: "Switching one off stops every computer sending it, deletes what the dashboard already holds about it for every computer, and does not affect sync. A computer can also switch these off for itself (its app settings, privacy); it cannot switch back on what the site has switched off." Each switch shows its cost (the table above). Each is exactly on or off; blank is refused.

Before anything switches a kind off, whether a save, bringing settings in from a file, or undoing a settings change, the admin is asked: "Stop every computer reporting: <names>? What this dashboard holds about it/them is deleted for every computer now, for good. Sync is not affected.", with "Stop reporting". Turning one back on is not asked. The studio's choice holds across restarts of the server, and if the server cannot read the stored choice it keeps the last one applied rather than quietly reporting again.

- Who: an admin.
- Setting: Studio reports the open Resolve project. Does: lets every computer report the open Resolve project's name; off also stops the bin structure. Default: on. Who: an admin. Applies to: the site. Search words: privacy, Resolve project, reporting, studio-wide.
- Setting: Studio reports media files on computers. Does: lets every computer report which media files it holds. Default: on. Who: an admin. Applies to: the site. Search words: privacy, file list, media, reporting.
- Setting: Studio reports Resolve bins. Does: lets every computer report its Resolve bins. Default: on. Who: an admin. Applies to: the site. Search words: privacy, bins, Resolve, reporting.
- Setting: Studio reports idle time. Does: lets every computer report how long since it was last used. Default: on. Who: an admin. Applies to: the site. Search words: privacy, idle time, presence, reporting.

### What is withheld is removed on arrival, and what was held is deleted

The server removes every withheld kind from every incoming report, whatever version of the app sent it, before anything is kept. A report that cannot be cleaned is refused rather than kept with withheld information in it. A computer that does not repeat its choice in a report keeps its last stated choice, and each computer's choice is recorded.

When a computer starts withholding a kind, everything the dashboard held of that kind for that computer is deleted: for the Resolve project, the open project, Resolve health details and the list of unopened projects, and the project names on its undo records; for the file list, its file lists and totals, and its missing and refused clip paths; for the bins, its bin listings; for idle time, its idle time. Newly withholding the project name, the file list or the bins also deletes that computer's stored diagnostics. When the studio switches a kind off, it is deleted for every computer at once, and every stored diagnostics report that could contain it is deleted. Switching a kind back on brings nothing back.

### Withheld information reads as not reported, never as a fault

Everywhere, a withheld kind reads as "not reported", never as zero, none or empty. For each kind a computer does not send, the computer shows a grey chip "NOT REPORTED BY THIS COMPUTER" with the kind ("OPEN RESOLVE PROJECT", "FILE LIST", "RESOLVE BINS", "IDLE TIME"); pointing at it says the computer's own privacy switch or the studio's is off, and "Sync is not affected, and nothing here is a fault." It never changes any colour, headline, note or alert. Problems that depend on a withheld kind (footage on one computer only, project folders outside the tree, a moved project folder) are not raised for that computer, and one already open is closed without a message.

### Diagnostics hide what a computer withholds

When the computer or the studio withholds the Resolve project, the file list or the bins, the diagnostics a computer produces replace every known project name with "<project>" and every path in the studio's folders with "<root>/<file>", and end with a note naming what was withheld. If hiding fails, the whole description is replaced by a one-line notice that it was withheld.

### A person downloads everything the product holds about them

A person downloads everything the product holds about them from their account page, always their own; nothing can change whose. An admin can download anyone's, including a person the studio knows only by a computer, a plan or a report. Each download is started only by a deliberate press, never by opening a link.

The download is one readable data file named for the person and the date, holding when it was made, the product's version, whose data it is, every record naming the person, and a "not included" list. It covers every store of every part:

- their computers and their current state, their ticks (including ones made for them), preferences, sync state and transfers, file lists, bin listings, file moves and Resolve undos sent to their computers, settings requests, requests for originals, their sharing connections, safety findings naming them;
- their identity: their place in the studio's list of people, suspensions, display name, account (password left out), computer sign-ins (secrets left out);
- their history: sync history, finished transfers, completion history, missing-file lists, diagnostics;
- evidence: history entries by or about them, alerts, problems, shared work, projects they archived, builds they published, site settings they changed (values left out);
- their browser sign-ins (when, last used, address, browser) and their failed sign-ins;
- their YouTube jobs, search terms, clips their computer fetched (for another person's job, only the facts of the fetching), download history credited to them, and their acceptances of the YouTube notice;
- client folders they made and clips they added to them;
- b-roll and music indexing batches they started or cancelled.

Something is about a person when it carries their name (ignoring capitals), or names a computer only they use; a computer name someone else also uses does not count. Sign-in secrets, password fingerprints and client-link secrets are never included (a client link's secret is the link itself). "Not included" always lists, in plain words: files on the person's own computers; files on the NAS and the server's records of what each computer holds; the text of the server's mailed check reports (kept 60 days); Timeline Cards' working records (kept per episode); failed sign-ins counted by network address; snapshots of the server's storage. A sentence is added for each store that could not be read ("<what>: not available on this dashboard, so it could not be read.", "<what>: could not be read just now.").

Refusals: a non-admin asking for someone else: "Only an admin can do this for another person."; an impossible name: "That is not a user name this dashboard can hold."; nobody known by that name: "This dashboard holds nothing about <username>."; one already being made: "An export of <username>'s data is already being made. Try again when it has finished."; more than 5 in an hour, counted apart for the person's own and for admins': "<username>'s data has been exported <n> times in the last hour. Try again later."; larger than 50 MB: for an admin "The export of <username>'s data is larger than 50 MB, so it was not made. Erase their history first, or ask for a copy by other means.", for the person "Your data is larger than 50 MB, so the file was not made. Ask an admin for a copy by other means." A refusal from a page is a short page with the sentence and "Go back". Every download is recorded with counts only, never the data.

- Who: anyone signed in, for themselves; an admin for anyone.
- Ways in: the person's own account page, the people list.
- Pending: accounts-privacy-legal-Q15

### An admin erases a person's past history

An admin can erase a person's past history while keeping the person: "Erase the history of <name>? Their account and what their computers report now stay." It removes the past records about them (sync and transfer history, completion history, missing-file lists, stored diagnostics), their ended browser sign-ins (live ones stay), their failed-sign-in count unless it is holding sign-in back right now, and their finished YouTube jobs with their search terms and results. It never removes their current state, their identity or evidence, the studio's YouTube download history (which stops the same video being downloaded twice), their acceptances of the YouTube notice, anything still running, or anyone else's records. It works whether or not YouTube downloads are switched on. A store that cannot be reached is skipped and named, and the rest still runs: "Erased <n> past record(s) about <username>. Their account and their computers' current state are unchanged.", adding " Some stores could not be reached; press it again later." when anything was skipped. Refusals as for the download. The erasure is recorded with counts per kind of record and what was skipped.

- Who: an admin.

### How long the product keeps each kind of record

About once an hour the server forgets what is past its keeping time:

| Record | Kept |
|---|---|
| Completion history | thinned to one point per hour after 48 hours, deleted after 30 days |
| Finished transfers | 7 days, and only the newest 300 per computer |
| Sync history | 30 days |
| A computer's sync state and its latest report details | until 30 days of silence |
| Missing-file lists | until not refreshed for 7 days |
| A computer's file lists and bin listings | until not refreshed for 14 days |
| Diagnostics | 30 days, and only the newest 5 per computer |
| History of who did what | 180 days |
| Withdrawn computer sign-ins | 180 days after withdrawal; live ones for good |
| Ended browser sign-ins | 7 days after they ended, or once past the 100-day limit |
| Log of alert mail | 120 days |
| Problems | 120 days after both closing and last being seen; open ones for good |
| Mailed check reports | 60 days |
| Updates pushed to a computer and settings requests | expire after 14 days unanswered (recorded) |
| Finished shared work | 30 days after its last change; waiting work for good |
| Records of conversations with the assistant | the period the site sets |

Never forgotten by age: projects (only made inactive), the computers and their plans (only by forgetting a computer or removing its person), the studio's list of people, display names, file moves and each computer's outcome, published builds, site settings, set-up progress, open problems.

- Setting: Keep assistant records for. Does: how long every stored record of a conversation with the assistant is kept before it is deleted. Default: not settled. Who: an admin. Applies to: the site. Search words: retention, assistant, transcripts, keep, delete after.
- When the assistant is off: nothing new is recorded, and what was recorded is still deleted on time.
- Pending: accounts-privacy-legal-U1

### Nothing leaves the studio for the vendor

In normal running nothing about the studio, its people or its footage leaves the site for the vendor. The server's crash reports are written on the server only and sent nowhere. The one way anything reaches the vendor is a support bundle an admin chooses to send; no assistant or other automatic tool reads it, and the vendor deletes it 30 days after the support ticket closes.

The product's privacy notice lists every request the product makes on its own to anywhere outside the studio and every outside service it uses, what each carries, and how to turn it off, and its list of what computers report matches exactly what they send.

### Only names are taken from a planning sheet

Where the product reads the studio's planning sheet for an episode, it copies only the episode and the people's names, never contact details.

#### Lessons

- Met: ACC-046, ACC-047, ACC-048, ACC-049, ACC-050, ACC-051, ACC-052.

## The licence a person accepts

### A computer accepts the licence before it first syncs

The licence an editor accepts travels inside the app, with its version. Before a computer syncs for the first time, someone at it must accept the current licence. Set-up shows it before anything is installed, and that is usually where it is accepted: the text read-only and scrollable, its version at the foot, and an introduction saying that accepting records the agreement on this computer and continues, and that declining closes set-up with nothing changed. The page is skipped when the computer has already accepted this version or a newer one (versions compared number by number), and is never skipped when the licence or its version cannot be found in the installer; then the page says so and tells the editor to ask the admin for a copy before continuing.

If set-up did not record an acceptance, the app offers the licence by itself about 3 seconds after it starts, and again every minute until the window has actually been shown once (waiting while another of the app's windows is open, or while the desktop is not ready). Until it is accepted nothing syncs; everything else in the app still runs. The menu carries "► Accept the licence agreement to start syncing…" and the app's settings window shows a red line "⚠ <the reason>. Nothing syncs until it is accepted." with "READ AND ACCEPT THE LICENCE". The reason is one of "The CC Sync licence agreement has not been accepted on this computer." or "The licence acceptance record on this computer is unreadable.", each followed by where to read and accept it. Declining or closing the window stops the automatic offer and says "NOT SYNCING: the licence agreement was not accepted. Tray > Accept the licence agreement."; the menu and the settings window open it again any number of times while there is something to accept.

Accepting records on the computer which version was accepted, when, by whom, and a fingerprint of the exact text, and starts syncing at once (subject to everything else): "Licence accepted, syncing is starting." If the acceptance cannot be saved: "Couldn't save your acceptance. Check disk space and try again." A build missing its licence text says "NOT SYNCING: this build is missing its licence document." with how to get help, and does not keep asking. If checking the licence fails with an error, the licence counts as accepted.

- Who: anyone at the computer.
- Ways in: set-up, opened by itself, the app's menu, the app's settings window.
- Pending: accounts-privacy-legal-Q16

### The licence window

The window is headed "► licence agreement" and reads "This computer is NOT SYNCING until someone here accepts the CC Sync licence agreement (version <V>). Read it below. Accepting records your agreement on this computer only, and syncing starts straight away." Below it is the whole licence in a scrolling, read-only box, properly laid out as text a person reads: headings stand out, no authoring notes or markup, links shown as "text (address)", and no long dashes. The text recorded as accepted is the licence exactly as issued. The buttons are DECLINE and ACCEPT. The licence is accepted only by a deliberate click on ACCEPT: ACCEPT is not focused, no key press accepts it, Enter does nothing, closing the window declines, and if the window cannot be shown the answer is decline.

### A new licence version asks everyone again without stopping their sync

When a new version of the licence arrives with an update, every computer is asked to accept it at once, by the same window, menu line and settings line, reading "The CC Sync licence agreement has been updated (version <new>; this computer accepted <old>)." The computer keeps syncing while it waits, and shows "waiting for the licence to be accepted" as its state in the app and on the dashboard. If the app is not running when the update is installed by hand, set-up opens on the licence page instead (not on a computer that works straight off the server, and not when asked not to; then only a warning), and a package with no set-up tells the editor to get the current installer from the dashboard. A package with no licence version never asks again.

- Who: anyone at the computer.

### The dashboard shows which licence each computer accepted

Each computer tells the dashboard which licence version it accepted, when, by whom, and a fingerprint of the exact text (each up to 128 characters). A report that does not mention it leaves the record as it was. Compared with the version the dashboard hands out, each computer shows green "Licence X accepted" when the same, amber "Older licence accepted" when different, and grey "Not reported" when nothing is recorded; when the dashboard has no licence of its own it is shown without colour. Nothing recorded means "Not reported", never "not accepted". It shows on the studio's overview of computers and on the person's own account page.

An acceptance recorded for a computer by someone not sitting at it (an admin accepting for the owner's own team) names who accepted, on whose behalf, and by what means.

### The server's set-up asks the admin to accept the licence

The server's set-up carries a required task "Welcome, EULA": "Read and accept the license agreement." It shows the licence text and a box to tick. Its states: "accepted v<version>" (done); "awaiting acceptance of v<version>" (to do), so a new version needs a new acceptance; "no licence agreement is included in this build, so nothing has been accepted" (a warning, which records nothing and counts as satisfied only while the build truly has no licence, re-checked every time the task is looked at); "could not read EULA: ..." (failed). Once a licence is in the build, the task is to do until an admin accepts it, found without restarting the server.

- Who: an admin.

### A legal document reaches people only once counsel has cleared it

No legal document (the licence, the privacy notice, terms for a part) is shown, linked or offered for acceptance anywhere in the product until counsel has cleared it. Legal text shown to people is properly laid out and follows the product's wording rules.

#### Lessons

- Met: ACC-053, ACC-054, ACC-055, ACC-056, ACC-057, ACC-058, ACC-059.

## Third-party licences and what customers receive

### Every program carries the licence texts it owes, and anyone can read them

Every program the product gives a customer (the app on an editor's computer for Windows and for macOS, its installers, the server, and any optional add-on) carries inside it the licence text of every component in it, including what it is built on, and no program is made without them. A person can read them from the app's help, from the last page of set-up, and from the dashboard's help. A customer also receives a third-party notices document: issued by the vendor, stating that CC Sync is proprietary under its own licence and that each component's own licence prevails for that component, listing the licences that need attention, the components in each part of the product with their versions, and the outside programs set-up fetches, with their versions and checksums. It lists exactly what customers receive, version for version.

### Nothing under a disallowed licence reaches a customer

No release goes out if anything a customer would receive is under a copyleft licence (GPL, LGPL, AGPL, SSPL) or an unknown licence, unless it has a recorded exception with a reason that applies to that program. An unknown licence is never assumed to be permissive. A release is also refused if a program holds anything not on its approved list, any file nobody accounts for, or any component whose licence text is missing. Copyleft software a customer needs (such as the media converter on the NAS) is fetched by the customer's own machine from its publisher, never handed over by the vendor or by the installer's computer. Copyleft software that only serves an optional part reaches a customer's machines only after that customer turns the part on.

### A component the user may swap can be swapped

A component whose licence gives the user the right to replace it is shipped as separate, replaceable files, and a copy the user puts in the app's settings folder is used instead.

### What a customer receives, and what never

A customer installs from a package they are given. Nothing in the customer's path hands out the product's source code or the vendor's internal documents. Each site pays one flat price, held by contract: no seat count and no expiry check ever stops a site working. Downloading the product needs a credential issued to that site.

#### Lessons

- Met: ACC-060, ACC-061, ACC-062, ACC-063, ACC-064, ACC-065.

## How secrets and keys are kept

### Credentials on an editor's computer are private to that person

On every editor's computer, every file holding a credential (the app's settings with the computer's sign-in, the computer's identity, anything that lets the product's own pages talk to the app, the editor's YouTube sign-in) is private to the person who owns it from the moment it is created, before anything is written into it: on Windows only the signed-in user can read and write it, on macOS only the owner. It is set through the system's own access controls in one step, and a stored sign-in is removed when it is no longer needed. This never stops the app; if it cannot be done, the editor and the admin are told.

### A new password or computer sign-in is shown once, to copy

A new password or computer sign-in an admin creates appears in a box that is never folded or refreshed away, styled as a result and not an error: "new password/credential for <name>", "shown once", the value, and "copy" (which turns to "copied"), with "Copy it now. It is shown once, and the panels on this page refresh by themselves." For a password: "Give it to <name> and have them change it after they sign in. Nothing here can show it again: the next one has to be a new password." For a computer sign-in: what to do with it (see "An admin issues a computer sign-in by hand").

### A credential never crosses the internet unencrypted

No password, sign-in or footage is ever sent unencrypted to a public internet address. The app on an editor's computer refuses before sending when every address its dashboard's name leads to is public, lets plain http through with a note when the address is on the studio's own or private network, and judges again within 30 seconds of the computer's network changing. Every connection carrying footage or a credential checks the identity of the far end, and an identity that has changed is refused, never trusted again by itself. A call carrying a credential never follows a redirect, and its refusal names where it was being sent; only a download that carries no credential and whose contents are checked against a signature afterwards may follow redirects, and only over https. A mail setting that would send its password unencrypted is refused when saved and when sending.

Admins are told, as a serious problem, "a computer reaches this dashboard unencrypted over the internet", when a computer's last report arrived unencrypted from a public internet address. Unencrypted over the studio's own or private network is never raised. It repeats daily only while that computer has reported in the last 24 hours, and otherwise is said once. The fix offered: serve the dashboard encrypted on the private network, set the encrypted address in the app, update CC Sync, or forget that computer.

### No secret appears where people or logs can read it

No password or secret, in any common spelling, appears in a log, a notification, a crash report, a copy of diagnostics, an alert, a mail or an error message. A secret carried in a web address (such as a client link) is never written into error records, alerts or logs, and those records are grouped by kind of page so they cannot grow without end. No secret is passed on a command line or printed in shipped examples. Any helper the product runs over outside text (a web page, a downloaded file, a reply) receives only the settings it needs, never a credential for the studio's computers, the NAS or signing.

#### Lessons

- Met: ACC-067, ACC-068, ACC-069, ACC-070, ACC-071, ACC-072, ACC-073, ACC-074, ACC-075, ACC-076.

