# Trace of server-install-and-running-2

## Coverage

- 14-023 | The admin sees how safely each computer reaches the dashboard
- 15-055 | Admins are warned when the server's private-network link is down, about to expire or not publishing the dashboard
- 15-056 | Admins are warned when most computers go quiet at once
- 16-056 | Nothing carrying a password, key or session follows a redirect
- 16-058 | Every admin page the product runs needs a login
- 16-062 | The product makes sure it is talking to the studio's own NAS
- 17-028 | The server knows a visitor's real address
- 17-068 | The admin sees how safely each computer reaches the dashboard
- 17-077 | The server joins the private network and publishes the dashboard there with https
- 17-078 | The dashboard is put back on the private network on its own if it goes missing
- 17-079 | The admin connects the server to the NAS once in the set-up wizard
- 18-038 | The dashboard is reached only through the studio's private network
- 18-039 | Editors on the NAS can only transfer files, by key, inside the studio's tree ; Each editor gets their own account on the NAS
- 18-043 | The server joins the private network and publishes the dashboard there with https
- 20-103 | The admin sees how safely each computer reaches the dashboard
- 21-003 | The server holds a limited key for a TrueNAS and never its administrator password
- 21-004 | On a Synology the server holds the password of an account made for it
- 21-006 | Every admin page the product runs needs a login
- 21a-011 | The dashboard is reached only through the studio's private network
- 21a-012 | Editors on the NAS can only transfer files, by key, inside the studio's tree
- 21a-013 | The server works as an account of its own on the NAS
- 21a-015 | Each editor gets their own account on the NAS
- 21a-016 | Each editor gets their own account on the NAS
- 21a-017 | Each editor gets their own account on the NAS
- 21a-018 | Editors on the NAS can only transfer files, by key, inside the studio's tree
- 21a-019 | Editors on the NAS can only transfer files, by key, inside the studio's tree
- 21a-020 | The admin can bring existing editor accounts on the NAS into the product
- 21a-021 | When an editor leaves their computers lose the NAS
- 21a-022 | Editors on the NAS can only transfer files, by key, inside the studio's tree
- 21a-023 | An editor's key sign-in needs their home folder kept to themselves
- 21a-024 | On a Synology the file-transfer service must be on and allowed to editors
- 21c-001 | The server works as an account of its own on the NAS
- 21c-016 | The product makes sure it is talking to the studio's own NAS
- 21c-018 | The server holds a limited key for a TrueNAS and never its administrator password
- 21d-008 | The product makes sure it is talking to the studio's own NAS
- 21d-009 | The product makes sure it is talking to the studio's own NAS
- 21d-010 | What the product says when a TrueNAS refuses or a connection drops
- 21d-011 | A Synology must run DSM 7 with every service the product needs
- 21d-017 | The product makes sure it is talking to the studio's own NAS
- 21-030 | Transfers with a Synology stay within what DSM can serve
- 21b-003 | Installing gets the media tools the server needs

## Questions for the owner

### server-install-and-running-2-Q1: Locking every admin page behind a login happens on its own. Should the set-up wizard also have a button that does it?
- Kind: several ways in
- Today: the server checks and locks the folder-syncing helper's admin page on its own, and the set-up wizard runs the same check and action again; a separate hand-run step locks it too, and installing an editor's computer locks that computer's copy.
- Options: A: on its own only; the wizard just shows the outcome. B: on its own, plus a button in the wizard.
- Recommend: A, because a check that runs on its own and is shown needs no second way to start it.
- Changes for a person: with A an admin sees the state but has nothing to press; with B there is a button that does what already happened.
- Text assumes: A for the action, with the wizard showing the outcome (the "Ways in" line lists both until he answers)
- Items: 16-058, 21-006

### server-install-and-running-2-Q2: TrueNAS and Synology lock editors down in different ways. Is it right that the text states one result on both and the differences only as facts about each NAS?
- Kind: differs
- Today: on TrueNAS the product adds sign-in rules and asks the NAS to switch off password sign-in (which TrueNAS refuses for accounts with Windows file sharing); on Synology it adds nothing because DSM already limits editors, but must turn the file-transfer service on and check application-privilege rules; home-folder permissions are set differently and only TrueNAS logs a refusal; TrueNAS lets a site give editors a full shell, Synology never does; TrueNAS demands both dashboard addresses, Synology makes them optional and refuses every-address.
- Options: A: one result on both (file transfer only, by key only, confined to the tree, dashboard only on the NAS itself and the private network), with each NAS's own facts stated. B: keep each NAS's own options (a shell on TrueNAS, address choices that differ).
- Recommend: A, since the editor and admin get the same thing on either NAS and the differences are only what each system needs.
- Changes for a person: with A a TrueNAS site can no longer give editors a shell on the NAS, and nobody types dashboard addresses.
- Text assumes: A
- Items: 21a-011, 21a-018, 21a-019, 21a-022, 21a-023, 21a-024

### server-install-and-running-2-Q3: On the very first connection to the NAS, should its identity be trusted on its own (and its fingerprint shown), or must the admin confirm it first?
- Kind: differs
- Today: the set-up wizard trusts the first certificate seen when the fingerprint box is left blank; the hand-run install refuses a NAS it has never seen unless the person explicitly allows "trust once"; the record of trusted NAS identities is private to the installing person on macOS and Linux but not on Windows; checking can be turned off (the studio does).
- Options: A: first connection during set-up trusts and records it, shows the fingerprint, a change is refused forever; the record is readable only by admins on every system; checking cannot be turned off. B: the admin must tick "trust once" before the first connection.
- Recommend: A, because set-up is already a deliberate act by the admin and a second confirmation adds a step that protects nothing more.
- Changes for a person: with A the admin presses nothing extra; with B they confirm the fingerprint once. Either way the studio can no longer turn the check off.
- Text assumes: A
- Items: 16-062, 17-079, 21d-008, 21d-009, 21d-017, 21c-016

### server-install-and-running-2-Q4: Should the product make the server's own NAS account on TrueNAS too, as it does on Synology?
- Kind: differs
- Today: on TrueNAS the account must be made by hand when the storage pool is built and the product refuses to make it; on Synology the product makes it.
- Options: A: the product makes it when missing on both kinds. B: by hand on TrueNAS, by the product on Synology.
- Recommend: A, one way on both, and one less thing for the person installing to do.
- Changes for a person: with A a new TrueNAS site has no account to make by hand.
- Text assumes: A
- Items: 21a-013

### server-install-and-running-2-Q5: When the server's account numbers on a TrueNAS do not match the site's settings, should the install stop until they do?
- Kind: other
- Today: the differences are named and the fix given; whether the install then stops or goes on is not known.
- Options: A: stop until they match. B: report and go on.
- Recommend: A, because a server writing the studio's tree as the wrong owner can lock editors out of footage.
- Changes for a person: with A a mismatched site cannot finish installing until the numbers are set.
- Text assumes: A
- Items: 21c-001

### server-install-and-running-2-Q6: Is bringing a studio's existing editor accounts on the NAS into the product still wanted?
- Kind: unreachable
- Today: the install can list the editors' accounts on TrueNAS; on Synology the listing always fails in a real run. It is used only when moving older accounts over.
- Options: A: keep it as a one-time carry-over that works on both kinds. B: cut it; existing accounts are matched as each person is added.
- Recommend: A, since the owner requires that the studio's people and computers carry over, and this is how existing NAS accounts are matched.
- Changes for a person: with B the admin re-adds each editor and the product takes over their existing NAS account then.
- Text assumes: A
- Items: 21a-020

## Readers' questions and unsettled points

- 15-Q6 | with dashboard-1
- 18-Q6 | answered: owner's requirements (the private network is the only way in, so publishing the dashboard there with https must work)
- 21-Q2 | answered: SRV-124 (a login the admin already set is kept, never replaced)
- 21a-Q3 | server-install-and-running-2-Q6
- 21a-Q4 | answered: SRV-119 (editors' NAS accounts transfer files only)
- 21b-Q3 | with accounts-privacy-legal
- 21c-Q5 | with accounts-privacy-legal
- 21d-Q4 | answered: SRV-118 (turning certificate checking off is never offered)
- U-16-9 | behind the glass
- U-17-3 | settled: the one such rule a person needs is Synology's limit of 64 KiB pieces and 16 at a time, which the product keeps to on its own
- U-17-7 | settled: the text names no service and speaks of the studio's private network as something the studio has
- U-21-1 | behind the glass
- U-21-3 | behind the glass
- U-21-4 | behind the glass
- U-21a-1 | behind the glass
- U-21a-2 | behind the glass
- U-21b-1 | behind the glass
- U-21b-2 | behind the glass
- U-21c-1 | server-install-and-running-2-Q5
- U-21c-2 | behind the glass
- U-21c-5 | settled: the identity seen at first connection is recorded and shown (SRV-118)
- U-21c-6 | settled: owner's requirements; the dashboard answers only on the NAS itself and on its private-network publication
- U-21d-2 | settled: the DSM 7 check refuses, listing each missing service, before anything is touched
- U-21d-4 | settled: every refusal from TrueNAS is shown in plain words
- U-21d-5 | behind the glass

## Still unsettled

- server-install-and-running-2-U2 | whether DSM lets an account that is not an administrator manage users, groups and snapshots, so whether the server's Synology account can be less than an administrator | the text asks for an account made for the server alone, never the person's own administrator sign-in, and does not promise it is not an administrator | 21-004, 21c-018

## Conflicts between an item and a lesson

- SRV-118 | 16-062, 21d-009, 21c-016 | the items let a site turn checking of the NAS's certificate off; the lesson says turning it off is never offered. Wrote the lesson.
- SRV-119 | 21-003, 21c-018 | the items let a studio opt out and store the TrueNAS administrator password; the lesson says the server holds only a scoped key. Wrote the lesson (the opt-out question is with accounts-privacy-legal).
- SRV-119 | 21a-016, 21a-019 | TrueNAS lets a site give editors a full shell; the lesson says editors' NAS accounts transfer files only. Wrote the lesson.
- SRV-123 | 21a-016, 21a-017 | the items say a computer's key replaces any key already there; the lesson says approving a key keeps every key already on the NAS. Wrote the lesson.
- SRV-124 | 21-006, 16-058 | the person's own lock step replaces an existing login, and a site can turn the automatic lock off; the lesson says no admin page is reachable without a login and an existing login is kept. Wrote the lesson, with no switch to turn it off.
- owner's requirements | 18-038, 21a-011 | the items have the dashboard answer on the studio's network address too, with addresses typed in on TrueNAS; the owner made the private network the only way in. Wrote the owner's requirement.

## New in this text

- Every admin page the product runs needs a login | the outcome of the check is shown to the admin and a failed or unknown result is a problem the server found; today it is only written to the server's log (nothing silent)
- The server knows a visitor's real address | the admin is told when something passes along addresses the server does not believe; today only the log hears of it
- The admin connects the server to the NAS once in the set-up wizard | the credential is never shown back and is shown masked
- Transfers with a Synology stay within what DSM can serve | nothing for the admin to set or fix; today the transfer settings are refused at install and fail the health check, and proxies fetched under wrong settings must be fetched again by hand
- Copy times to the NAS are estimated from measured speed | written from SRV-125
- Any NAS speed the product shows is measured with large ordinary files | written from SRV-126
- Big copies inside the NAS never make browsing wait | written from SRV-127
- The admin is warned before the NAS's storage gets too full | written from SRV-128
- Schedules run on the studio's own clock | written from SRV-129, including the warning when the NAS's clock is wrong and the studio time zone setting
- Pages stay quick while big downloads and checks run | written from SRV-130
- Each editor gets their own account on the NAS | a key that could not be written stays offered to the admin (SRV-123); every change is read back (SRV-122)
- The server works as an account of its own on the NAS | the product makes the account on TrueNAS too (Q4)

## Parts of items left out

- 17-028 | the installer's setting naming which front ends are believed: with the private network the only way in, the product knows its own front end
- 18-039 | that a key cannot be checked while the dashboard is down and the connection is refused: how editors' keys are looked up
- 21-006 | the report-only mode of the hand-run lock step, the login saved to a file on the person's computer, restricting the listening address, and telling a wrong access key from a wrong address: tools and insides of one helper
- 21-004 | "never in the description of the app itself": kept as "never in the description of the app as DSM shows it"
- 21-003 | "the lines to paste for the install": the key is entered where the set-up asks for it
- 21c-016 | the description of the server written for pasting by hand, and the rehearsal showing the fingerprint: how the server is handed its settings
- 21c-018 | the old opt-out that lets the server hold the TrueNAS administrator password (with accounts-privacy-legal; SRV-119)
- 21d-008 | the record kept on the installing computer and moving it elsewhere for a session, the pin "for the session": the installing computer's own arrangement
- 21d-017 | the generated library password for the editing program and the snapshot record: kept by other parts; the installing computer's folder is an arrangement
- 21-030 | the transfer settings refused at install, the health check that fails, and re-fetching proxies over 514 MiB: the promise is that the limit is kept on its own
- 21b-003 | the measured speed of the usual source (about 28 kB/s) is kept only as "slowly, about 25 minutes", which the person is told
- 15-055 | "the fix gives the command": written as "the step"
- 17-077 | the by-hand commands in each to-do state: written as "the step to fix it"

## Joins with other capabilities

- broll / Client folders and links | The dashboard is reached only through the studio's private network | the one link reachable from outside the private network
- dashboard / Problems the server finds | Admins are warned when the server's private-network link is down, about to expire or not publishing the dashboard | where serious problems are shown and alerted
- dashboard / Problems the server finds | Admins are warned when most computers go quiet at once | the same; the silent-computer ladder is with dashboard-1
- editor-app / Signing in, the computer's identity and the licence | The admin sees how safely each computer reaches the dashboard | the app refuses plain http to a public address
- accounts-privacy-legal / Passwords, sessions and failed sign-ins | The server knows a visitor's real address | the failed sign-in limit counts by visitor address
- accounts-privacy-legal / How a computer proves who it belongs to | Each editor gets their own account on the NAS | approving a computer adds its key
- accounts-privacy-legal / Suspending, disabling and removing a person | When an editor leaves their computers lose the NAS | removing or suspending a person
- accounts-privacy-legal / How secrets and keys are kept | The server holds a limited key for a TrueNAS and never its administrator password | the server's secret store
- server-install-and-running / Snapshots, restoring and the server's disk | Schedules run on the studio's own clock | scheduled snapshots fire at studio time

## Settled from the present product

- server-install-and-running-2-U1 | nothing checks the NAS's clock at present; the text takes the amount used for a computer's clock
