# The server: installing it and keeping it running, part 2 of 2

This part covers how the studio's computers and people reach the server, the credentials the server holds for the NAS and how they are kept, how editors' own access to the NAS is made and locked down, and what an admin is told about the NAS's speed, load and clock.

## Connections and credentials

### The dashboard is reached only through the studio's private network

The studio's private network is the one way in to the dashboard, for this studio and for every customer: from inside the studio and from away alike, an editor's computer, an admin's browser and a phone all reach the dashboard through it. A private network of this kind joins the studio's own computers and phones wherever they are, so no editor needs a VPN of their own and nothing about the dashboard is open to the internet. The one exception is the link an editor hands to a client for a client folder (see The b-roll archive: Client folders and links).

On the NAS the dashboard answers only on the NAS itself and on its publication on the private network, never on every address the NAS has. There is no address for the person installing to choose or type for this: the server's place on the private network comes from signing it in (see "The server joins the private network and publishes the dashboard there with https").

Facts about the NAS that make this the simplest arrangement:

- On a Synology, DSM's own web server holds the usual web ports, so nothing else can take every address on them. Asking for every address on a Synology is refused, telling the person to keep the dashboard on the NAS itself and publish it on the private network.
- A NAS's own file sharing for Windows and macOS (the studio's mapped drive) stays on the studio's own network as the NAS provides it. That is the NAS's service, not the dashboard.

- Who: anyone signed in, from a computer or phone joined to the studio's private network.
- Name and search words: private network access. Search words: remote access, VPN, reach the dashboard, from home, network.

### The server joins the private network and publishes the dashboard there with https

The set-up wizard carries an optional task, "Connect to your private network", with the button "SIGN IN OR PUBLISH" and a CHECK. It signs the server in to the studio's private network and publishes the dashboard there over https.

What the task shows:

| State | Shown as |
|---|---|
| The server is not signed in to the private network | to do: the server is not signed in yet, with the link to open to add it to the network, or, when there is no link yet, a note to press the button |
| Signed in and published with https | ok: "signed in as <name>, published at <address>" |
| The dashboard's address is already an address on the private network | ok |
| Signed in, but the server's key on the network expires within 14 days | warning: "... its key expires in N day(s). When it does every editor loses the server at once.", with the steps in the network's own admin console to turn key expiry off for this server. A later expiry date is shown as a note. |
| Signed in but not published | to do, saying which of these holds, each with the step to fix it: https certificates are off for the network; the publishing settings could not be read; nothing publishes the dashboard on the network, so no editor can reach it (it answers on the NAS itself only) |

What the button does:

- When the server is signed in, it publishes the dashboard with https on the private network. If the dashboard had no address yet, the published address becomes the dashboard's address.
- When the server is not signed in, it fetches a sign-in link, waiting up to about 5 seconds, and says "open <link> and sign in, then press CHECK on this task". It never reports success by itself: only CHECK does.

Refusals, each in plain words with the next step:

- the network service did not answer, or is not running;
- https certificates are off for the network: where in the network's admin console to turn them on, then press this again, "so no editor could connect";
- the publishing settings could not be read;
- publishing is not turned on for the network: follow the link in the message once;
- the server has no name on the network yet.

- Who: an admin.
- Ways in: the set-up wizard.
- Name and search words: connect to your private network. Search words: private network, publish, https, sign in server, remote.

### The dashboard is put back on the private network on its own if it goes missing

- On its own: about once a minute, a server signed in to the private network checks that the dashboard is still published there, and publishes it again if it is not. A publication that exists, including one an admin made by hand, is never overwritten.
- By hand: the last repair (when, whether it worked, and why not) is shown on the private-network task in the set-up wizard and in the alert below, and the admin can publish by hand from the same task.

### Admins are warned when the server's private-network link is down, about to expire or not publishing the dashboard

Three serious problems, each shown among the problems the server found and sent as alerts (see The dashboard: Problems the server finds):

| Problem | When |
|---|---|
| "this server's private network connection is down" | the server's connection to the private network is not running |
| "this server's private network key is about to expire" | its key on the network expires within 14 days, or already has |
| "the dashboard is not published on the private network" | the connection runs but nothing publishes the dashboard on it. The text includes what the last automatic repair said, and the fix gives the step that publishes it again. |

An answer from the network that cannot be read, or a connection that did not answer, makes the check "not checked", never a clear.

### Admins are warned when most computers go quiet at once

A serious problem, "most computers went quiet at the same time", points the admin at the server and its network rather than at the editors one by one.

It is raised when, among the computers that reported within the last 24 hours (at least 2 of them), the largest group that went silent within the same 10 minutes, each silent for between 30 minutes and 24 hours, is at least half of them and at least 2, and either:

- the server's own private-network connection is unhealthy, or
- at least 2, and at least half, of that group were in the middle of a transfer when they last reported.

The wording says which of the two applied. The fix tells the admin to check the NAS and its private-network connection.

### The admin sees how safely each computer reaches the dashboard

For each computer, the server notes how its reports arrive: over https; over plain http inside the studio's own network (the studio's network, the private network or the NAS itself); or over plain http across the public internet. Only a change is recorded. When the server cannot tell, or a name cannot be looked up within a second, the computer counts as inside the studio's own network.

Beside the site settings, an admin sees, for information only:

- "<n> computer(s) reach(es) this dashboard over plain http on your network or private network. Serving it over https is recommended."
- "<n> ... over plain http from the internet: see the alerts on the home page."

Nothing is shown when there are none. A computer reaching the dashboard over plain http from the internet is also an alert. The app on an editor's computer itself refuses to send anything to the dashboard over plain http at a public address (see The app on each editor's computer: Signing in, the computer's identity and the licence).

- Who: an admin.

### The server knows a visitor's real address

The address of a person visiting the dashboard is what the limit on failed sign-ins counts by, and what a person's account page shows (see Accounts, privacy and the legal paperwork: Passwords, sessions and failed sign-ins). The server takes a visitor's address, and whether the visit was over https, only from the NAS itself and from its own publication on the private network. An address passed along by anything else is ignored, and everyone coming through it counts as one visitor; the admin is told once, as a problem the server found, which way in passed an address it does not believe.

### Nothing carrying a password, key or session follows a redirect

When an address the server was given (the NAS's management address, its file sharing, or anything else it sends a password, key or session to) answers by sending it somewhere else, the server sends nothing on. The admin is told the address redirected, with the answer's code and where it pointed, that nothing was sent, and to set the address that really answers. A reply that is not what was expected is reported as an error in words; it never breaks the page or the server.

### Every admin page the product runs needs a login

No admin web page that the server, or anything the product installs on the NAS or on an editor's computer, runs is ever reachable without a login: anyone who can reach an unlocked admin page is its administrator.

- On its own: within a few minutes of starting, and then every hour (retried about every two minutes until it can be read), the server checks each such page's sign-in settings.
  - Settings that cannot be read: nothing is changed, and the state is "unknown", never "unprotected".
  - A login set and open access off: left alone.
  - A login set but open access on: only open access is switched off. The login the admin set is kept, never replaced.
  - No login: the product sets one (the existing user name, or a default one) with a password of 28 random letters and digits, keeps it in the server's secret store, and switches open access off.
  - Everything that already used the page keeps working.
  - When the change needs a restart of what serves the page to take hold, the admin is told to restart it, and where.
  The same check runs when an editor's computer is installed, and an install never stops because of it.
- By hand: the outcome (protected, secured, failed, unknown) is shown to the admin on the set-up wizard's health of the server, and a failed or unknown result is a problem the server found. The admin can see the login the product set, once, when they ask for it; it is never shown again or written anywhere a person could read it.
- Ways in: on its own, and from the set-up wizard.
- Pending: server-install-and-running-2-Q1

### The admin connects the server to the NAS once in the set-up wizard

The set-up wizard's optional task "Connect to your NAS" is described as a one-time admin credential for snapshots and the editors' accounts on the NAS. It carries a form:

- the kind of NAS: TrueNAS or Synology;
- the NAS's address: a name or IP address with an optional port, "with no http:// in front";
- for TrueNAS, an access key and the account it was made for; for Synology, the account and password (see "On a Synology the server holds the password of an account made for it");
- the NAS's certificate fingerprint: blank remembers the first certificate seen and refuses a different one later; a fingerprint pins it; "1" checks it against the usual certificate authorities. There is no way to turn checking off.

Refusals:

- a TrueNAS given a password: "a TrueNAS NAS is connected with an API key, never the admin password...";
- a key without its account;
- a NAS account that is also a dashboard admin: "Make a separate sign-in for the dashboard admin, so a stolen dashboard login is not the key to the whole NAS."

The task's check asks the NAS within 3 seconds and says "<kind> <version> at <name> answered", with a support note when the TrueNAS version is outside the supported range, or failed with the NAS's refusal in one line of at most 100 characters. With nothing stored, it asks for the details.

The credential entered is never shown back, never written to a log, a page or a file a person could read, and is shown masked wherever its presence is reported.

- Who: an admin.
- Ways in: the set-up wizard.
- Name and search words: connect to your NAS. Search words: NAS connection, TrueNAS key, Synology account, NAS address, certificate.
- Setting: the NAS's kind, address and credential. Does: tells the server which NAS holds the studio's tree and how to manage editors' accounts and snapshots on it. Default: none, entered at set-up. Who: an admin. Applies to: the site. Search words: NAS address, NAS key, NAS password, TrueNAS, Synology.

### The server holds a limited key for a TrueNAS and never its administrator password

On TrueNAS the server never holds the NAS administrator's password. It holds an access key made for a named account of its own that can do only what the server needs: manage editors' accounts and set permissions.

- The person setting up creates that dedicated account and its rights themselves in TrueNAS; the product does not. The product then makes the key for it.
- Before the key is made, the person is always told the risk that remains: even the dedicated account can reset any account's password and keys and change permissions anywhere. The key's worth is that the administrator password is not on the server, that it can be revoked by its name, and that its account can be watched. They are shown exactly which actions the key allows.
- Making the key act as the administrator itself is refused unless the person deliberately asks for it, and then they are warned that the key has administrator-equivalent rights.
- The key is shown once ("TrueNAS stores it hashed and will not show it again"), with where to enter it and a reminder of where to revoke it. The product writes it down nowhere but the server's secret store.
- The key is labelled by name in TrueNAS. Each new key gets a new name, so the old one can be deleted by name.
- If TrueNAS refuses every way of making the key, the person is told not to guess and to read TrueNAS's own documentation. If a key was made but its value did not come back, they are told to delete it in TrueNAS and try again.
- Asking for such a key on a Synology is refused, explaining that DSM has no access keys.
- Installing or updating the server on TrueNAS without such a key is refused, giving the step that makes one. With a key, the install says that the administrator password is not stored.

Facts about TrueNAS that the person meets here: a key belongs to the account it was made for, and TrueNAS revokes a key that is sent to it over a connection it does not treat as secure.

- Who: an admin.

### On a Synology the server holds the password of an account made for it

DSM has no access keys of its own, so on a Synology the server holds the password of an account named for it. At every install the person is told that this should be an account made for the server alone, never their own administrator sign-in. Every secret the server needs on a Synology is kept where only the NAS's administrator can read it, never in the description of the app as DSM shows it; a preview of the install names the secrets without their values.

- Who: an admin.
- Pending: server-install-and-running-2-U2

### The product makes sure it is talking to the studio's own NAS

Every connection the product makes to the NAS that carries a password, a key or an account change first checks that the NAS is the studio's NAS. A NAS ships with a certificate it made itself, which no certificate authority vouches for, so the product recognises the NAS by its own identity:

- On its own: the first time the server reaches the NAS during set-up, the NAS's identity is recorded and the person is shown its fingerprint, told that later connections are checked against it and that a change will be refused, and given the fingerprint to compare with the one the NAS shows on its own screen. If the NAS cannot be reached to record it, the server meanwhile accepts only a certificate the usual authorities vouch for (so a NAS's own certificate fails) and tries again after a minute.
- On its own: an identity that has CHANGED from the recorded or pinned one is refused, showing the expected and offered fingerprints, where the expected one came from, how to update it, and "Nothing was sent". It is never trusted again on its own. A NAS that presents no identity, or a record that cannot be read, is refused the same way.
- By hand: an admin can instead pin the NAS's identity by its fingerprint (letter case, colons and spaces ignored), have it checked against the usual certificate authorities (for a NAS with a certificate from one), or give the studio's own certificate authority. A fingerprint written wrongly is refused with an example of the right form, never taken as "no check". To accept a NAS whose certificate was deliberately replaced, an admin removes the recorded identity; nothing does this automatically. Turning the check off is never offered.

The identity the server trusts is also what editors' computers check the NAS by. The record of trusted identities can be read only by admins.

- Who: an admin.
- Setting: the NAS's identity. Does: decides which NAS the product will send passwords, keys and account changes to. Default: the identity seen at first connection, recorded. Who: an admin. Applies to: the site. Search words: NAS certificate, fingerprint, NAS identity, trust NAS.
- Pending: server-install-and-running-2-Q3

### What the product says when a TrueNAS refuses or a connection drops

Facts about TrueNAS and what the person is told:

- TrueNAS refuses unencrypted connections to its management interface unless they come from the NAS itself, and revokes an access key sent over a connection it does not treat as secure. The product therefore never sends a key that way.
- When TrueNAS refuses the key, the person is told so, reminded that a key sent over a connection TrueNAS does not treat as secure is revoked by it, and told which account the key was presented as and how to name the right one (a key belongs to the account it was made for).
- A refused password says "the NAS refused the username or password".
- After a dropped connection, the product retries a read, or a request that was never sent, once. A change that may already have reached the NAS is never sent a second time.
- Waiting for TrueNAS to finish a piece of work gives up after 2 minutes and says it did not finish.

### A Synology must run DSM 7 with every service the product needs

Before signing in, the product checks that the Synology offers each service it needs (sign-in, users, groups, group members, application permissions, file transfer, shared folders and their permissions, and shared-folder snapshots) at the version it needs. If any is missing or at another version, it refuses, listing each one, because a half-installed NAS is worse than one never touched. A NAS that refuses the check itself is told it does not look like DSM 7. The password is never put in a web address.

Synology's answers are shown in plain words:

- the session has no privilege: almost always a session from an older sign-in;
- the session expired: the product signs in again once, and a second expiry is reported;
- invalid account or password; the account may not sign in to DSM;
- a two-factor code is needed;
- the Snapshot Replication package is not installed;
- no such user; the user already exists; the password fails this DSM's password policy;
- no such group; the group already exists; bad or missing values;
- anything else: "DSM error" and its number.

A rehearsal of the install shows each step it would take, with every password shown as redacted.

### The server works as an account of its own on the NAS

The server writes the studio's tree as one account of its own on the NAS, which owns the editors' share (by default named "broll", user number 3000, group number 3001, in the group "editors"). It is not an editor.

- On both kinds, the product makes the account if it is missing (it cannot sign in interactively, and its password is random and never kept) and reports its number, or says it already exists.
- On TrueNAS, the server works with the user and group numbers in the site's settings. Before installing, the product reads the account's and the editors' group's real numbers on the NAS. Each difference is named ("is user N on this NAS but the server would run as M", likewise for the group), with the instruction to set those numbers in the site's settings, and the install stops until they match. When the numbers cannot be read, the person is warned that the install goes ahead unchecked. A rehearsal skips the check.
- On Synology, the product refuses an account numbered outside 1024 to 169999, because Synology's own accounts start at 1024 and its package accounts at 170000. If the site names the shared folder holding the tree, the account is given its own read-write access to it; if that fails, the person is told and the install goes on.
- If the account is in the editors' group it is taken out, and the person is told if it is still listed there afterwards.

- Setting: the server's account numbers on the NAS. Does: the user and group the server writes the studio's tree as. Default: user 3000, group 3001. Who: an admin. Applies to: the site. Search words: NAS user, uid, gid, owner, permissions.
- Pending: server-install-and-running-2-Q4
- Pending: server-install-and-running-2-Q5

### Each editor gets their own account on the NAS

Each editor gets an account on the NAS, in the editors' group, with a home folder, a random password the editor never needs to know, and the keys their computers reach the NAS with. Files an editor writes can be changed by the other editors. The account appears within about 30 seconds of the editor being added. Accounts are never deleted by this.

- Each of an editor's computers that is approved (see Accounts, privacy and the legal paperwork: How a computer proves who it belongs to) has its key added beside the keys already there, so every computer keeps its access. A key that could not be written stays offered to the admin, with the reason.
- Every step that changes the NAS stops at the first failure and reads its result back before reporting success: the key is read back after it is written, and group membership after it is set.
- Running the set-up again for an existing editor re-adds them to the editors' group.
- On TrueNAS, the account is also enabled for Windows file sharing.
- On Synology:
  - Refused before anything is created or changed: Synology's built-in account names (admin, guest, anonymous, root, system, http, in any letter case); names starting "sc-", which look like Synology package accounts; an existing account numbered outside 1024 to 169999; and an existing account not in the editors' group, which the product will not take over (the person is told to add it to the group on the NAS first or pick another name).
  - If Synology says the name exists but does not list it as an ordinary account, the person is told it is probably a package account and to pick another name.
  - The random password meets Synology's rule of mixed case and a digit. It never expires, no e-mail is sent, and the editor may change it.
  - The home folder must exist: if Synology's "User Home" service is off, the step is refused and the person is told to turn it on (Control Panel, User & Group, Advanced) and run it again.

Facts about Synology accounts: every account's main group is the NAS's "users" group, so the editors' group is an extra one; account names match regardless of letter case; an account counts as locked when it has expired; and asking Synology for an existing account by name can answer that it is missing, so the product finds accounts by listing them. A failure to look an account up stops the step with the NAS's reason.

- On its own: the account is made and kept up when an admin adds an editor or approves a computer.

### Editors on the NAS can only transfer files, by key, inside the studio's tree

An editor's account on the NAS can only transfer files. It cannot sign in to a shell, it accepts no password for transfers (only a key from one of the editor's approved computers), and it starts in the studio's tree and cannot leave it. If the dashboard cannot be reached, nobody's access changes.

How each kind of NAS gets there:

- On TrueNAS, the product adds rules for the editors' group to the NAS's sign-in service: file transfer only, no password sign-in, no forwarding or tunnels, no terminal. The administrator's own settings in that service are kept, and an unchanged rule set is reported as unchanged. These rules do not confine editors to one folder: what they can reach is governed by the folders' permissions. The product also asks TrueNAS to switch off password sign-in for each editor's account; TrueNAS refuses this for accounts that use Windows file sharing, and that refusal is expected and reported as such.
- On Synology, nothing is added: only Synology's administrators can sign in interactively, so editors never can, and Synology has no switch for password sign-in (the password is used only for Windows file sharing and the dashboard's sign-in). The person is told to keep Synology's file-transfer service on and its terminal access restricted (Control Panel, Terminal and SNMP).
- Synology shows a file-transfer connection its shared folders as the top level, without the volume they live on, and nothing outside them (the system's temporary folder cannot be reached). On TrueNAS a path on the NAS is the same path over a file-transfer connection.

### An editor's key sign-in needs their home folder kept to themselves

Both kinds of NAS refuse key sign-in when the editor's home folder (or, on Synology, the hidden folder and file holding the key) can be written by anyone but the editor, or is not owned by them. The product sets these permissions and then checks them, warning the admin when the NAS will still refuse.

- On TrueNAS the home folder is made the editor's alone, with any extra access rules removed. The NAS's sign-in log records such a refusal.
- On Synology the home folder itself must never have its permissions changed by hand, because that deletes Synology's access rules on it; only the hidden key folder (editor only) and the key file (editor read and write only) are set. Synology logs nothing for this refusal: the editor only sees "Authentication failed". The admin is told to repair the key folder directly and the home folder by having Synology re-apply inherited access, never by changing its mode.

### On a Synology the file-transfer service must be on and allowed to editors

With Synology's file-transfer service off, an editor's key sign-in succeeds and the connection is then closed, with nothing in any log. The product turns the service on (on port 22 unless the site says otherwise) and says so, or reports it already on with its port. Synology grants file transfer to everyone by default, but an "application privilege" rule can deny it: a rule denying it to everyone or to the editors' group stops the install, telling the person to remove it on Synology's Application Privileges screen. Rules for single accounts or other groups are not checked. If the rules cannot be read, the person is told to check that screen by hand, and the install goes on. On TrueNAS there is nothing to turn on.

- Setting: the Synology file-transfer port. Does: the port editors' computers reach the NAS's file transfer on. Default: 22. Who: an admin. Applies to: the site. Search words: SFTP port, file transfer, Synology, port 22.

### When an editor leaves their computers lose the NAS

When an editor is removed or suspended, or one of their computers is forgotten, that computer's key is removed from the NAS so it can no longer reach it. When the admin asks for the account to be locked as well, TrueNAS locks the account and Synology expires it at once. On Synology, if the key was removed but the account could not be expired, the admin is told exactly that.

- Who: an admin.

### The admin can bring existing editor accounts on the NAS into the product

When a studio already has editor accounts on its NAS, the product lists every account in the editors' group so they can be brought in once, each matched to a person. On Synology, a group that does not exist yet answers that there are no editor accounts yet.

- Who: an admin.
- Pending: server-install-and-running-2-Q6

#### Lessons

- Met: SRV-118, SRV-119, SRV-120, SRV-121, SRV-122, SRV-123, SRV-124.

## NAS speed, load and clock

### Transfers with a Synology stay within what DSM can serve

A fact about Synology: DSM's own secure file-transfer server cannot serve transfers that use large pieces or many at once. Every transfer between an editor's computer and a Synology stays within 64 KiB pieces and 16 at a time. Nobody sets this: the product keeps to it on a Synology on its own, and nothing transferred with a Synology ever comes down damaged because of it.

### Installing gets the media tools the server needs

The server needs a media converter to read and make video. When installing needs to download it, the person is shown the download and its progress. The usual source serves a NAS slowly (about 25 minutes for this download), so the NAS is given up to 30 minutes before the step gives up. The person installing can instead have their own computer fetch it (up to 5 minutes) and send it over the studio's network, where it is unpacked on the NAS (up to 5 minutes).

- When the NAS's own download fails, the person is told the source is slow and offered the other way.
- When the installing computer cannot fetch it, the person is told to retry, to point at a copy already on their computer, or to let the NAS download it.

- Who: an admin.

### Copy times to the NAS are estimated from measured speed

Every estimate of how long a copy to or from the NAS will take comes from the speed the NAS has really been delivering for that kind of work, and expects the speed to fall as the NAS's storage fills and as other work runs on it. It is never worked out from the nominal speed of the network link or the disks.

### Any NAS speed the product shows is measured with large ordinary files

Any figure the product shows or tests against for the NAS's speed comes from writing and reading large files the ordinary way, as footage is written and read. It never comes from writes that bypass the NAS's buffering or from reads the NAS answers out of its memory.

### Big copies inside the NAS never make browsing wait

A large copy from one folder on the NAS to another is paced so that a person browsing any share on the NAS, from any computer, never waits more than a few seconds for a folder to list.

### The admin is warned before the NAS's storage gets too full

A NAS whose storage is nearly full slows every read and every folder listing. The admin is warned before the NAS's storage passes about 80% full, as a problem the server found and an alert. When reads or listings from the NAS slow down and the storage is that full, the warning names fullness as the cause.

- Who: an admin.

### Schedules run on the studio's own clock

A NAS can declare one time zone while its clock and schedules run on another. Every scheduled scan, snapshot and upload fires at the studio's wall-clock time. The dashboard shows the admin the studio's time zone and the time the NAS's clock actually reads, checked against true time rather than the zone the NAS declares. When the NAS's clock is wrong, the admin is told, as a problem the server found, with the NAS's time, the true time and the step to correct it on the NAS.

- Who: an admin.
- Setting: the studio's time zone. Does: the wall-clock time every scheduled scan, snapshot, upload and report is set in and shown in. Default: asked at set-up. Who: an admin. Applies to: the site. Search words: time zone, clock, schedule, studio time.
- Pending: server-install-and-running-2-U1

### Pages stay quick while big downloads and checks run

The dashboard's pages, the client links and every page of the product keep answering promptly while large downloads (a client fetching terabytes) or long checks run. A page that once failed to load never makes the product rescan many files to make up for it.

#### Lessons

- Met: SRV-125, SRV-126, SRV-127, SRV-128, SRV-129, SRV-130.
