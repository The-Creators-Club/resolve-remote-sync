# The server: installing it and keeping it running, part 1 of 2

The server is the part of CC Sync that lives on the studio's NAS: it holds the dashboard, keeps the studio's project tree in step with every editor's computer, and watches itself. A studio installs it on its own NAS without help and finishes setting it up in a browser; nobody types a command, builds anything or edits a file. This part covers what the NAS must be and offer, installing and the set-up in the browser, the settings and secrets an admin gives it, updates and going back, shares that go away, snapshots and restoring, the off-site backup, and the checks the server makes of itself and the alerts it sends. Syncing is core and never switched off, and the dashboard keeps telling everyone whether footage is syncing even while an optional part is broken or missing. The studio's network, remote access and the NAS's speed and clock are in part 2.

## Installing on a NAS

### The server runs on a TrueNAS or a Synology NAS

The server runs on exactly two kinds of NAS, both fully supported from the same release, with every feature working the same on both:

- **TrueNAS**, version 25.04 or later, TrueNAS 26 included, with no setting needed. A TrueNAS older than 25.04 is refused with the reason: "TrueNAS <version> predates 25.04, which this product does not run on. Upgrade to 25.04 or later." A TrueNAS newer than the versions this release was tested against draws a note to check the supported versions before upgrading the NAS; it is not refused. A version that cannot be read is said so.
- **Synology DSM 7.2 or later.** A DSM that does not offer the web interfaces the server needs (sign-in, users, groups, group membership, user homes, secure file transfer, shared folders) is refused with "this DSM does not offer what CC Sync needs to set up editors: set them up in DSM's Control Panel instead"; a box that does not answer the question at all is told "this does not look like a DSM 7 box".

The kind of NAS is chosen once (set-up offers the two; TrueNAS is the default). A blank or any other value is refused with "unknown NAS kind '<x>': allowed values: truenas, synology"; the server never guesses or falls back to TrueNAS. A step that one kind of NAS does not allow to be done from outside is refused with a message telling the admin what to do on the NAS's own screens instead.

Everything that needs to act on the NAS itself (editor accounts, access groups, snapshot checks, recovery commands, information about the NAS) works once the server has been given its way in to the NAS (see "Set-up task: Connect to your NAS"); until then those features say they are not set up, and everything else works.

The NAS's version and name are shown to the admin wherever the NAS reports them.

- Setting: Kind of NAS. Does: tells the server whether the studio's NAS is a TrueNAS or a Synology, which decides how it sets up accounts, folders and snapshots. Default: TrueNAS. Who: an admin. Applies to: the site. Search words: NAS kind, TrueNAS, Synology, DSM, storage.

### What a NAS must have before the server goes on it

Before installing, the studio needs:

- a NAS of one of the two kinds and versions above, with an app system the server can be installed through;
- a shared folder for the studio's tree (projects, the b-roll archive and the music library), shared to Windows and macOS computers as a network drive;
- a place for the server's own data, separate from the tree;
- on TrueNAS, both of these as storage areas of their own (TrueNAS calls them datasets), because TrueNAS snapshots storage areas, never plain folders, and a whole pool must never be put on a snapshot schedule (it would snapshot everything on it). A pool's name is accepted where a storage area is asked for;
- on Synology, the shared folder on a volume with copy-on-write storage (snapshots need it), and DSM's User Home service switched on;
- the NAS joined to the studio's private network, which is how the dashboard is reached (see The server: installing it and keeping it running: Connections and credentials).

Where the tree's shared folder does not yet exist on a Synology, set-up creates it: a top-level shared folder on a volume (so its name and path must agree; any other shape is refused, saying why), copy-on-write on, recycle bin off, compression off, not hidden, described as the product's tree. An existing shared folder is left alone and reported. The editors' group is given read and write access to it, which is read back and refused if Synology does not show it as writable; that access is what every folder and file below inherits. On TrueNAS the storage area and its Windows share are made on TrueNAS's own screens, and set-up says so and waits.

### Facts about TrueNAS and Synology the person setting up meets

| | TrueNAS | Synology (DSM) |
|---|---|---|
| What the server signs in to the NAS with | a limited access key for a dedicated account, never the admin password | a dedicated admin account's password; DSM has no access keys |
| Accounts that count as system accounts | numbered below 1000 | numbered below 1024 or from 170,000 up; built-in names admin, guest, anonymous, root, system, http; names starting "sc-" (package accounts) |
| Usernames | matched exactly | matched without regard to letter case |
| An editor's home folder | made by the server under the site's homes folder and made private | made by DSM; checked, never changed |
| Sign-in key for an editor's computer | stored on the account; a new key replaces the old | added beside the existing keys; DSM has no web interface for keys, so it is installed over the NAS's remote shell with administrator rights |
| Windows file sharing per account | a switch per account | not per account; always on |
| Deleting an editor's account | the home folder is left in place | DSM deletes the home folder with the account |
| Turning off password sign-in to the remote shell | refused by TrueNAS for an account with Windows file sharing; that is expected | managed by DSM |
| Folder permissions | owner, group, group-writable, new files take the folder's group | inherited access entries from the shared folder; changing a folder's mode or owner by hand strips its Synology access list (Synology calls this "Linux mode") and new files there then inherit nothing |
| Adding an account to a group | reliable | can report success while doing nothing, so membership is always read back |
| What a snapshot is of | a storage area on a pool; a folder that is not its own storage area is snapshotted through the one containing it | a whole shared folder |
| Snapshot names | chosen by whoever takes it: letters, digits and - _ . : only, starting with a letter or digit; a scheduled task's name pattern must carry the hour and minute or TrueNAS refuses a daily task | chosen by Synology from the clock; a label becomes the snapshot's description |
| Snapshot schedules | can be made and read from outside | need DSM's free Snapshot Replication package; schedules live where no other program can read them |
| Snapshots listed | oldest first, with space used | by time made, no space used, in no guaranteed order |
| Snapshot folders | a snapshot's folder is mounted only when it is first opened | the same |
| Secure file transfer from editors' computers | serves large transfer pieces | DSM's own server serves at most 64 KiB pieces, 16 at a time; it breaks on permission changes inside a shared folder |
| What the file-transfer sign-in can reach | any folder it is allowed | only inside shared folders, never system folders, even as admin |
| Admin command-line tools over the remote shell | found normally | not found under administrator rights in a remote session unless called by their full place |
| Installing an app from a pasted definition | takes it exactly as pasted: fills in no values and builds nothing | not applicable |
| An access key used over an unencrypted connection | TrueNAS revokes the key | not applicable |
| Its private-network connection runs as | one of TrueNAS's apps | a Synology package |

Transfers to and from editors on a Synology always stay within 64 KiB pieces and 16 at a time; the server never offers editors' computers anything larger, and nothing the server does changes permissions inside a Synology shared folder.

### Installing is one step on the NAS, and the rest happens in the browser

The person installing does two things on the NAS and nothing else by hand: joins the NAS to the studio's private network, and installs the server from the NAS's own app screen. Installing the server asks for two places only: the shared folder holding the studio's tree, and the place for the server's own data. The server refuses to start without either, naming the missing one. No secret is typed at install: the server makes its own on first start (see "The server makes and keeps its own secrets"). Everything else is entered in the set-up wizard in the browser.

What the person installing is told while the NAS installs it:

- that downloading the server can take a few minutes; the server is given up to 15 minutes to arrive, and the person is told when it has;
- if the download fails, the usual causes: the NAS has no route to the internet, or the version named does not exist; and that the server can instead be brought in from another computer on the studio's network, checked against its checksum (a fresh NAS has been seen downloading from some hosts at about 28 kB/s, so installing never depends on the NAS downloading large files quickly). A download that does not match its checksum leaves nothing installed;
- installing counts as done only when the NAS's own install has finished successfully AND the server is actually running and answering; a NAS that accepted an install which then failed is reported as a failure with the NAS's reason, never as success;
- if the server was told to answer on an address the NAS does not have, it fails with "cannot assign requested address", and the person is told to look at the app on the NAS's app screen.

On a fresh install every part of the server starts once and stays up, every folder it writes exists and is writable by the account it runs as, and every part of it holds the same shared secrets, so editors connect without any repair. A fresh install done as the published guide says reaches, in the browser, the making of the first admin, sign-in, working folder sync and reachability over the private network, and every required set-up check can pass. Following only the published guide, a newcomer on a clean NAS reaches first sync, first update and first rollback with one Windows and one Mac editor.

The server ships with the licence agreement, the third-party licence texts, the guide to how the product works and the guide to setting up an editor's computer. A guide that is missing from a build does not stop anything: the help says that guide is not installed. What set-up's licence task shows for a build with no licence agreement in it is in Accounts, privacy and the legal paperwork: The licence a person accepts, "The server's set-up asks the admin to accept the licence".

Installing again over a server that is already there and running leaves the running server untouched. Whether a server is already there is answered "installed", "not installed" or "could not tell" with the NAS's own reason; "could not tell" is never taken as "not installed", and the person is never advised to delete a server that may be running.

A first install ends by showing where to open the dashboard: its private address on the studio's private network.

What the person installing is told about later updates, and how an installation is renewed from each kind of NAS's app screen when an update needs it, keeping every setting, is in Releases and updates: The server updating itself, "Some server updates need the installation renewed on the NAS".

- Who: the person installing the server, on the NAS.

### What the server sets up on the NAS by itself

On first start, and again whenever it starts, the server makes sure of these, creating what is missing and never touching what is there:

- the folders of the studio's tree it relies on: the projects folder, the shared assets folder with the studio's shared libraries (by default the LUT library and the Resolve stills gallery), the b-roll archive with folders for its previews, and the music library. Every part's folders are created whether or not the part is switched on, so the server always starts. A failure to make the shared libraries is a note that the shared LUTs and stills may not appear; a failure to make the b-roll archive's or music library's folders makes that part unavailable with the reason, and the rest runs;
- the server's own private folders, readable only by the account the server runs as;
- the editors' group on the NAS ("editors" unless the site names another). An existing group is left alone and reported; a new one is created and reported with its number (on TrueNAS also enabled for Windows file sharing; on Synology numbered from 65536, and a group someone else created in the meantime is accepted). A failure to read or create it is reported with the NAS's reason;
- on a Synology, secure file transfer granted to the editors' group, where editors' transfers go through DSM's own file-transfer server. If that fails, the admin is warned that editors' transfers will fail with "channel closed".

Every folder the server creates, parent folders included, gets the site's owner, group and permissions, writable by the server and by editors over the share:

- **On TrueNAS** everything in the tree belongs to the editors' group, and each project's folder to that project's group, every folder makes new files inside it take the same group, and the folders above each project are protected so that one editor cannot delete another editor's project folder. If the storage area forbids those permission changes, the admin is told that the protection or the group inheritance is missing and why it was blocked; the ownership is still correct.
- **On Synology** permissions come only from Synology's inherited access rules and the server never changes a mode or an owner. Set-up checks the tree carries an inherited rule letting the editors' group read, write and delete; if it is missing, it first has Synology re-apply inheritance, then adds the rule itself, and reports which it did. A folder that has lost its Synology access rules is reported with the warning that new files there inherit nothing and land writable by everyone (Synology's file transfer creates files with no restriction), and the repair: re-apply Synology's inherited permissions to it, never change its mode, which deletes the Synology access list. On Synology the folders above each project are not protected against deletion by other editors.

The server acts on the NAS as a real NAS account and group, read from the NAS itself, never a fixed account number (the two kinds of NAS number accounts differently). The account and its group are always set together or not at all; a half-set pair is warned about at start. At every start, if that account does not own the server's data folder, the admin is warned, naming the account and the owner it found, where each came from, and the fix: give the folder to that account. No warning ever advises running the server with administrator rights.

### A part that needs extra software on the server gets it when switched on

Some switchable parts need extra software on the server: music and YouTube downloads need a media converter, the Timeline Cards editor needs software of its own to run, and signed-in YouTube downloads need a helper of their own. Each is fetched only when a part that needs it is switched on.

- Every such program is installed only when its checksum matches both the product's own record and the one its publisher lists. If the publisher's list cannot be reached, lists nothing for that download, or lists a different checksum, nothing is fetched and the admin is told which (a different one means the product's record is stale or the download site is not what it was). The admin may instead point at a copy they installed and vouch for themselves.
- A copy is checked again after it reaches the NAS, before it is unpacked; a mismatch is reported as a corrupted transfer and nothing is installed. A downloaded program is first run on the NAS to prove it works there; one that does not run is not installed, and the admin is told so.
- A program already there and working is left alone and reported as already there, before anything is downloaded. A failed check of whether it is there counts as "not there".
- A program that cannot be fetched, verified or installed never stops anything else. The part shows what will not work until it is there, with a "try again" button: music says adding tracks is not available; YouTube says signed-in downloads find no formats; the Timeline Cards editor says it cannot start.
- A fetch interrupted by a restart shows as interrupted, with "try again", on the next start; partial downloads older than a day are removed.

- Who: an admin.
- On its own: fetches what a switched-on part needs, from which parts are on.

### The set-up wizard walks the first admin through setting up the server

"First-run set-up: every step here can be re-run later from Settings." The set-up is a list of tasks. Each shows its title (with "(optional)" where so), a description, its state and a one-line detail with when it was last checked. States are "checking" (while being looked at), "to do", "done", "check this", "failed" and "skipped". The first unfinished task is highlighted. An error appears inside the task that failed and is scrolled to; older errors are cleared first.

Each task offers:

- "check": "Looks again at how this step stands. Changes nothing." One task cannot be checked twice at once;
- the task's own action where it has one;
- a form where the task needs values (fixed choices as drop-downs; secrets as described in "Secrets an admin enters are checked and never shown back"). A saved value takes effect at once;
- "skip" on an optional task ("skip, I understand" on one that holds back "Done"), which shows "skipped by admin" and stays skipped even when checked later, with "(you chose to skip this on <date>)" where an earlier skip no longer applies. A required task cannot be skipped ("<task> is required and cannot be skipped").

A check or action that breaks shows the task as failed, "internal error: <detail>", never an error page. The state of every task (its status, detail, time and whether it was skipped) is kept, so a server restarted mid-way resumes where the admin was. "Stuck, or something here looks wrong? Send it to <support contact>."

The tasks, in order: the licence; your admin account; your studio; storage check; syncing on the server; done (these are all required); then the optional ones: Connect to your private network, Connect to your NAS, protect your data, editors, software for editors, signing key for updates, who should we tell. (The server's own secrets need no task: the server makes them.) Every value set-up checks can be entered in set-up itself, and every finding's next action can be done from the product's pages, never by editing a file or reinstalling. Set-up never requires a task the admin cannot complete.

Until every required task is done, an admin who signs in without asking for a particular page lands on set-up instead of the overview, and the menu carries a set-up mark. Never an editor: an editor lands on the overview. If the server cannot tell whether set-up is finished, the normal landing is used. The same task list stays available to an admin in settings afterwards.

- Who: an admin; before any account exists, see the next behaviour.
- Ways in: the set-up page an admin lands on; the same list in settings.
- Name and search words: Set-up. Search words: setup, wizard, first run, checklist, getting started.

### Before any account exists anyone may start set-up, and after that only an admin

With no account yet, anyone who opens set-up may read the task list, read the licence, and create the first admin, which signs that browser in at once. Creating the first admin is refused when an admin already exists ("an admin account already exists"; two people submitting at once cannot both succeed), when the name given is the NAS's own administrator account, ignoring capitals ("use a separate account"), or with the account rule that failed. Any other task, accepting the licence included, answers "create the admin account first (step 2), then this step opens". Creating the first admin is recorded with the visitor's address.

Once any account exists, every part of set-up needs a signed-in admin ("log in first", "admins only"), and set-up never offers to create an account.

- Who: anyone, until the first account exists; then an admin.

### Set-up task: the licence

The first task on the list, and a required one: an admin reads and accepts the licence agreement. Its text, states and wording are in Accounts, privacy and the legal paperwork: The licence a person accepts, "The server's set-up asks the admin to accept the licence".

- Who: an admin.

### Set-up task: your admin account

"Create your admin account" (required): "A local account for you. No NAS credential is involved."

- A name and password form: "Makes the first admin account and signs you in with it." The task is done ("admin account: <names>") once any account exists, else "no admin account yet". The form is replaced by "an admin account already exists" or "could not check: <reason>" as the case is.
- The task also carries the list of the accounts that are always admins (see Accounts, privacy and the legal paperwork: Who may sign in, "The admins are named in set-up, and are never the NAS's own administrator"), several names separated by commas; the first admin's name starts it. A list that names nobody is refused ("name an editor account, not the NAS administrator"), and so is one that names the NAS's own administrator account, ignoring capitals ("use a separate account").
- Every name, in the form and in the list, has the one shape of a sign-in name (see Accounts, privacy and the legal paperwork: Who may sign in, "A sign-in name has one shape, and a name accepted anywhere works everywhere").

- Who: anyone before the first account exists; then an admin.

### Set-up task: your studio

"Your studio" (required): "Name, tree name, drive letter and the project layout." The form asks for the studio's name, a short name (defaulting to the studio's name), the name of the tree ("the top folder"), the drive letter editors see the tree on ("on Windows", for example P:\), the layout of a project, and the studio's time zone, which every schedule follows (see The server: installing it and keeping it running: NAS speed, load and clock, "Schedules run on the studio's own clock"). When signed in, the form is filled from the present settings, never over text being typed. Only changed, non-blank fields are saved: "nothing changed" or "saved". Done as "<studio name> / <tree name>" once all of these have values, otherwise "not set: <which>".

The project layout is learned from the studio's own projects: the admin points set-up at one or more sample project folders, and set-up takes from them where projects sit in the tree (how many folder levels, for example year, then series, then project) and which folders every new project starts with. No folder name of this product's is required anywhere; the admin can then edit what was learned. The values are the same settings described under "Settings and secrets".

- Who: an admin.

### Set-up task: the storage check

"Storage check" (required, button "Do it"): "Confirm the tree is writable and lay down the shared asset folders." The check reports the projects folder as not available to the server, as "not yet checked: click Do it", or as "writable; <free space> free". The action writes, reads back and removes a small test file in the projects folder, then creates any missing shared library folders, never changing who owns anything: "writable; <free> free; created N shared asset folder(s)". Failures:

- "could not write / read / delete a test file: <reason>"; for a permission refusal it names the account the server runs as and who owns the folder, and how to give the folder to that account;
- "writable, but could not create <folders> under <tree>: check who owns the shared folder";
- the projects folder is not available to the server at all, and what to point the server at;
- when the server cannot see the shared libraries beside the projects folder, that they live beside the projects on the NAS, outside what the server was given.

- Who: an admin.

### Set-up task: syncing on the server

"Syncing on the server" (required, button "Do it"): confirms that the server's own syncing is running and answering. The check (5 seconds at most) says it does not answer (failed), answers but has no identity yet (check this), or is done with the first 7 characters of its identity. Nothing that controls the server's syncing is reachable unprotected by anyone on the studio's network; if it ever is, the task shows "check this" and the action protects it. The action checks again, protects it if needed, and records the server's sync identity that editors' computers verify.

- Who: an admin.

### Set-up task: Connect to your private network

A new site starts with every secure default on and serves the dashboard only over a secure address on the studio's private network: no public port, no relay, except links deliberately made public (see The b-roll archive: Client folders and links). The optional task "Connect to your private network" publishes the dashboard there and checks it; its button, its states and when it turns done are in The server: installing it and keeping it running: Connections and credentials, "The server joins the private network and publishes the dashboard there with https". Every editor's computer is given an address it can actually reach, never assumed to be the address on the studio's own network.

- Who: an admin.

### Set-up task: editors

"Editors" (optional): "Add your first editor." Done as "N editor(s): <first five names>, and N more", counting every person the dashboard knows; otherwise "no editors yet", pointing to where people are added. Once the first editor's computer has joined, set-up checks that it can list, read, write and delete in the shared tree, and names which of the four failed.

- Who: an admin.

### The Done step waits for the required tasks and three protections

"Done" ("Everything required is configured.") stays to do, showing "waiting on: <task titles>", until every required task is done and each of three protections is either set or knowingly skipped: the signing key for updates, protecting the data (snapshots), and who should be told when something breaks. A skip lets Done turn green; it never turns the matching line on the protection list green (see "The protection list says what really stands between the studio and a loss").

- Who: an admin.

### Set-up task: Connect to your NAS

To manage editors' accounts, groups, permissions and snapshots, the server needs a way in to the NAS, entered in set-up's "Connect to your NAS" task and never shown back (the task's form is in The server: installing it and keeping it running: Connections and credentials, "The admin connects the server to the NAS once in the set-up wizard"):

- On TrueNAS, a limited access key for a dedicated account, and only that. The server signs in as the key's own account, and a refused sign-in names the account that was presented. TrueNAS revokes an access key that is ever used over an unencrypted connection, so the server never talks to the NAS unencrypted. Each request waits up to 30 seconds.
- On Synology, the password of a dedicated administrator account; a blank one is refused. The server signs in under a session of its own, so it never signs the admin's own browser out of DSM. What each sign-in failure and DSM error is said as, and the retry of an expired session, are in The server: installing it and keeping it running: Connections and credentials, "A Synology must run DSM 7 with every service the product needs". Each request waits up to 15 seconds.
- Every identity the NAS presents is checked before anything is sent to it (see The server: installing it and keeping it running: Connections and credentials, "The product makes sure it is talking to the studio's own NAS", and its setting "the NAS's identity").

The credential is stored exactly as entered, whatever characters it holds.

- Who: an admin.

### Editor accounts on the NAS are made and managed by the dashboard

The dashboard makes and looks after each editor's account on the NAS under the same rules on both kinds of NAS, and never touches an account it did not make. Every editor is in the studio's editors' group, created if missing.

- A username has the one shape of a sign-in name (see Accounts, privacy and the legal paperwork: Who may sign in, "A sign-in name has one shape, and a name accepted anywhere works everywhere"). A sign-in key is accepted when it starts with one of the standard key types.
- The dashboard can check the NAS answers (which also proves it may read users and groups), list editors, create or update an editor with their sign-in key and full name, set a password, and delete an editor.
- It refuses to change, set the password of or delete a system or built-in account ("<name> is a system account: refusing to modify it. Pick a different username." or "<name> is a DSM built-in account"), or any existing account not already in the editors' group ("<name> already exists on the NAS and is not in the editors' group: refusing to take over an account this dashboard did not create. Add it to the group by hand first, or pick a different username.").
- A new account gets the full name (default the username), the editors' group, the person's own account password where the studio uses the shared folders, changed whenever the person's password is (see Accounts, privacy and the legal paperwork: Who may sign in, "Every person has one account, and a studio may put its single sign-on in front"), the sign-in key, and Windows file sharing. An editor's NAS account only ever transfers files: it never has a login to the NAS itself. On TrueNAS its home folder is made under the site's homes folder and made private to the editor; if that cannot be confirmed within two minutes the admin is warned that file transfers may fail with a vague sign-in error. Password sign-in to the remote shell is switched off where the NAS allows it. On Synology the account has no expiry and no notification mail, and its home is made by DSM; if the home does not exist the admin is told "DSM's User Home service is off. Turn it on in Control Panel > User & Group > Advanced, then try again."
- After setting a key the result is checked and the admin warned of anything that did not take: the key, Windows file sharing or group membership; on Synology a home writable by others (the remote shell then refuses the key without saying why; repair by re-applying Synology's inherited permissions, never by changing the folder's mode), the key folder or key file with the wrong owner or permissions, or an interactive login shell (none is needed). On creation, a key that could not be installed is a warning and the account is kept.
- A second computer for the same editor adds its key beside the existing ones on Synology (reported "already there" when it is); if it cannot be written that is an error and the computer's approval stays pending. On TrueNAS updating an editor replaces the key.
- In the editor list on Synology, Windows file sharing always shows as on, an account whose expiry state is not normal shows as locked, and the key shows only as "(installed)" or empty.
- Deleting an editor on TrueNAS leaves their home folder in place, and the admin is told so; on Synology the admin is warned first that DSM deletes the home folder with the account.
- The editors' group is judged by its real members: a correctly set-up NAS passes, and the check fails only when a member is really missing.

- Who: an admin.
- Ways in: see Accounts, privacy and the legal paperwork: Who may sign in.
- Setting: Checking each editor's sign-in key on the NAS. Does: when on, the list of people looks up each editor's key on the NAS every time it is shown; off makes the list faster. Default: on. Who: an admin. Applies to: the site. Search words: sign-in key, editors list, NAS check, people page.
### A new project's folders are laid down on the NAS

An admin creates a project at the place in the tree the studio's layout gives (for example year, then series, then project), or at any depth; names with spaces are fine. The year, series and name may not be empty, contain a slash, start with a dot or contain "..", and are refused naming the bad part.

- Inside it the studio's standard folders are made, each reported as created or already there. Proxy folders are not made.
- Refused before anything is created, with "Nothing was created": the target is inside an existing project, or already contains a project two or more levels down (the one found is named).
- Ownership and permissions are re-applied over the whole new project for the editors' group (or the project's own group).
- Each project is open only to its own people. On TrueNAS the project gets its own group on the NAS, named from the project's identity and kept within the NAS's 32-character limit for group names (shortened, with a short code to keep it unique). On Synology the project's group is given access, but the admin is always told that the share-wide editors' rule still reaches that folder and still lets every editor in: they must break inheritance on that folder in Synology's File Station and remove the editors' entry, because Synology offers no way to do it from outside.

- Who: an admin.

### A project keeps a permanent identity

Each project carries a permanent identity, made from its name when the project is first created or adopted: lower case, every run of other characters turned into one hyphen, only a-z, 0-9 and hyphens; an empty result is refused. It is shown to the admin, and every record about the project (its ticks, Resolve links, history and media list) and the project's synced folder hang on it, so it survives the folder being renamed or moved.

- An existing folder can be given an identity (adopting it), and a moved project repaired.
- An identity is written only if the project has none; an existing identity is always kept. Writing the same identity again says "identity unchanged". A different one is not written over it: the admin is told the identity is permanent, what hangs on it, and that changing it must be done deliberately, with the suggestion to keep the old one.
- An identity record that cannot be read is never taken as "no identity", and nothing is written over it. A missing project folder is refused.

- Who: an admin.

### Every change to the NAS names the NAS first and asks before anything sweeping

Every action that changes the NAS first shows which NAS (its address and kind), which studio and which project tree it is about to work on. Every such action can be previewed first: the preview shows what it would do, changes nothing, and ends by saying nothing was changed and how to go ahead. Every refusal before a change says "Nothing was changed" in its own words.

Actions that sweep across a whole tree or cannot be undone (re-applying ownership across the whole tree, revoking an editor's access, creating a project's folders) additionally show the preview first and ask the admin to type the NAS's short name (the first part of its name, or the whole address when it is a number; letter case does not matter). A wrong answer stops with "Nothing was changed". A preview never asks.

- Who: an admin.

### A shared Resolve project database on the NAS is set up safely

Where the studio keeps a shared Resolve project database on the NAS, the server gives it a random password (never the well-known one Resolve's database ships with), lets it accept connections only from the studio's network and the private network, and copies it every night, keeping each copy 30 days (see Resolve on the editor's computer: Project libraries and projects, "Every shared Resolve project library is backed up every night"). Each editor's computer reaches it at an address it can really reach, so Resolve collaborators see each other's real addresses on the studio's network and the private network alike, never an address inside the server.

- When the help for the editing program is off: not offered.

### Set-up checks that the Synology's secure file transfer is switched on

On a Synology, set-up asks DSM whether its secure file transfer service is on, since editors' computers transfer files through it, and shows "check this" with where to switch it on in DSM when it is off.

- Pending: server-install-and-running-1-Q22


#### Lessons

- Met: SRV-001, SRV-002, SRV-003, SRV-004, SRV-005, SRV-006, SRV-007, SRV-010, SRV-011, SRV-012, SRV-013, SRV-014, SRV-015, SRV-016, SRV-017, SRV-018, SRV-019, SRV-020, SRV-021, SRV-022, SRV-023, SRV-024, SRV-025, SRV-026, SRV-027, SRV-028, SRV-029, SRV-030, SRV-031, SRV-032, SRV-034, SRV-035.

## Settings and secrets

### The server makes and keeps its own secrets

The server needs secret credentials of its own: one that keeps people and computers signed in, one the studio's computers report with, one that guards adding clips to the b-roll index, one that controls the server's own syncing, and one that lets the server's file-transfer service trust the server. Nobody types them. Any that is missing is made at random on first start and kept on the server's own disk, readable only by the server, and the same value is used at every later start. A secret is written whole or not at all: a failed save never destroys the good copy and never leaves an empty or partial one. Values are never shown or written anywhere a person reads.

However the server is started, a missing secret is made or the server refuses to start; no blank value ever means "open". If a freshly made secret could not be kept (an empty or partial copy counts as not kept), the server refuses to start rather than run with a secret that changes at every start, naming each one with what losing it would cost:

- every computer and every browser would be signed out the next time the server restarts;
- the studio's computers would stop being able to report;
- adding clips to the b-roll index would stop being accepted;
- the server would lose control of its own syncing;
- the file-transfer service would stop trusting the server.

It tells the admin to give the server's data folder to the account the server runs as (naming both).

An admin changes the secret that keeps people and computers signed in from settings, never by reinstalling; what then happens to existing sign-ins, and retiring the previous secret, are in Accounts, privacy and the legal paperwork: How a computer proves who it belongs to, "Changing the server's own secrets signs nobody out".

- On its own: makes every missing secret at first start, from which ones are not yet kept.
- By hand: an admin changes the sign-in secret from settings.

### Secrets an admin enters are checked and never shown back

The secrets an admin enters (the server's way in to the NAS, the mail server's password, the assistant's paid key, any secret the admin chooses to supply in place of one the server made) are entered in set-up or in settings and never shown back:

- A secret field shows only whether one is set ("set; leave blank to keep it"); leaving it blank keeps what is stored, while blanking a plain field clears it. A secret over 400 characters or holding control characters is refused.
- Every preview masks secrets: a set one shows as "set", an unset one as "unset".
- A secret the product generates for a person (a key, a password) is shown once, and that is said.
- A secret the admin supplies in place of one the server would make must be at least 24 characters long, have at least 8 different characters, and not be a common placeholder (such as changeme, change-me, replaceme, todo, tbd, secret, password, token, test, example, your-token-here, xxx, none, null; letter case ignored). The admin is told which rule failed: that it is not set; that it is the placeholder named (a value that is public); that it is only N characters and at least 24 are required; or that it has too little variety to be a random secret, and how to make a strong one. The same rule is applied at every start, so a weak value can never be running.
- A credential the customer owns (the NAS's password or access key, the mail server's password) is stored and read back exactly, whatever characters it holds; the strength rules apply only to secrets the product makes or stands in for.
- At start, the server names any secret that has spaces before or after it, or is wrapped in matching quotes, never showing its value: "Everything that uses it will be refused, on every computer at once." This is a serious problem on the home page.

Saving refusals: "this step has nothing to fill in here", "not a setting of this step: <name>", "nothing to save", "could not store the setting (<reason>)", and field errors prefixed with the field's label.

- Who: an admin.

### Adding clips to the b-roll index is always guarded

Adding clips to the b-roll index always needs the server's secret for it, even from a signed-in person. When none is set the server makes it itself (see "The server makes and keeps its own secrets"), so only a weak secret an admin supplied in its place leaves additions unguarded. The b-roll part then does not come up, and its status says that no usable secret is set, so adding to the index cannot be guarded; the admin can let the server make one or switch b-roll off. How the archive shows that it is not working is in The b-roll archive: Replacing the search index, "Search never stops because of an update"; adding clips is in The b-roll archive: Describing and indexing clips.

- When the b-roll archive is off: no such secret is needed and nothing is said.

### A sign-in set-up that would lock everyone out is refused

A sign-in set-up that would leave nobody able to sign in is refused when saved, with a message naming the problem, and the server likewise refuses to start on one:

- a sign-in method that is not one of the two offered (the product's own accounts, or those accounts with single sign-on in front): "Left as it is, every password would be refused";
- secure-only sign-in forced while the dashboard has no secure address;
- single sign-on chosen with the identity provider's address or the dashboard's registration with it missing, or a provider address that is not secure (plain is allowed only to the same machine).

Every setting is read and checked once at start; a value the server cannot use refuses the start, naming the value and the ones allowed.

- Who: an admin.

### The site's identity and layout reach every editor's computer and every page

Set once in the site's settings and handed to every editor's app, every installer and every page. Changes apply on save without reinstalling, and every editor's app reads them:

- the studio's name and a short name (blank: the full name, used in tight spots such as the tray's tooltip); a support contact (blank: the vendor's, shown as a hint); the product name (default "CC Sync"); and the tray logo (blank: the product's own mark; a mark shipped with the app, or a picture on the editor's computer, white on transparent). These show in the dashboard's header, on the sign-in page and in every tray. Every label that uses a technical word explains it on pointing;
- the tree's name, the drive letter editors see it on (default P:), where the tree lives on the NAS, and its Windows network path;
- where editors' computers transfer files to (the NAS and its port, default 22), and the NAS's key that their computers check;
- the layout of a project, the folders every new project starts with, and the shared libraries every editor gets;
- the b-roll archive's default collection and its label, and the folder holding the studio's own shoots;
- the release feed (blank: off) and how vendor releases are taken (see Releases and updates: Customer sites and the vendor's release feed);
- the server's own sync identity and the dashboard's address;
- the studio's time zone (see The server: installing it and keeping it running: NAS speed, load and clock, "Schedules run on the studio's own clock").

The site description that editors' computers and installers read is open before anyone signs in and never contains a secret, a person, a project, a list of paths or a key. Blank means "this site was not told". Beside the values above it gives what a computer needs to reach the server's files and to verify it is talking to the right server, the fixed list of video file kinds treated as originals (not configurable), the release feed's location (only when it is a secure address), the kind of NAS, the switches of the parts and features that are off unless the site turns them on, the site's four reporting switches (see Accounts, privacy and the legal paperwork: What the product records about a person), and the b-roll indexing quality: "good" (needs about 8 GB of graphics memory) or "best" (needs about 12 GB).

- Who: an admin sets them; everyone's app reads them.
- Setting: Studio name. Does: the studio's name in the dashboard's title, the sign-in page and every tray. Default: blank. Who: an admin. Applies to: the site. Search words: studio name, organisation, company, branding.
- Setting: Short name. Does: the studio's name where space is tight, such as the tray's tooltip. Default: the studio's name. Who: an admin. Applies to: the site. Search words: short name, abbreviation, tray name, branding.
- Setting: Support contact. Does: who editors and admins are told to contact when stuck. Default: the vendor's contact. Who: an admin. Applies to: the site. Search words: support, contact, help email, who to ask.
- Setting: Product name. Does: the name the product goes by on every screen. Default: CC Sync. Who: an admin. Applies to: the site. Search words: product name, branding, app name, rename.
- Setting: Tray logo. Does: the mark shown in every editor's tray or menu bar. Default: the product's own mark. Who: an admin. Applies to: the site. Search words: logo, tray icon, mark, branding.
- Name and search words: Studio settings. Search words: studio, branding, name, logo, identity.

### The tree, the drive letter and the dashboard's address are set once and then locked

An admin sets the tree's name, the drive letter editors' computers see it on (or, for a Mac-style tree, an absolute folder), where the tree lives on the NAS, the network address editors' computers map, and the dashboard's address ("This must be exactly the address editors type in their browser, or Send to Resolve stops working."). The drive letter must look like "P:" or "P:\" (the backslash is added) or an absolute folder with no "..", and may not be blank ("must be a Windows drive letter like 'P:\' or an absolute folder like '/mnt/tree'"). Every installer and every editor's app reads the drive letter from here.

Once any computer has joined, the tree's name, the drive letter and the tree's place on the NAS are shown read-only, marked "locked" ("every installer and app builds its paths from it"); a change is refused, saying every computer's move must be planned first. Saving the value a setting already has is not a change. The dashboard's address and the server's own sync identity are filled in and locked as "found by the server: <where from>" when the server can read them live.

The connection details editors' computers use are kept apart as advanced ("A wrong value here stops syncing for everybody.").

- Who: an admin.
- Setting: Tree name. Does: the name of the studio's top folder that every computer builds its paths from. Default: set at set-up. Who: an admin, until a computer joins. Applies to: the site. Search words: tree name, top folder, root folder, share name.
- Setting: Drive letter. Does: the drive letter (or Mac folder) editors' computers see the tree on. Default: P:. Who: an admin, until a computer joins. Applies to: the site. Search words: drive letter, P drive, mapped drive, network drive, mount.
- Setting: Dashboard address. Does: the address editors type to open the dashboard, which sending to Resolve depends on. Default: found by the server where it can read it. Who: an admin. Applies to: the site. Search words: dashboard address, URL, link, web address.

### The kind of NAS, the project layout and the shared libraries

An admin sets the kind of NAS (only the two supported kinds are offered), the layout of a project and the folders every new project starts with (learned from sample projects at set-up, editable as a comma-separated list), and the shared libraries every editor's computer gets (comma-separated folders in the tree, such as the LUT library). Each entry must be a folder under the tree, not an absolute one, with no drive letter and no ".." ("must stay under the tree: '..' is not allowed"). A shared library's name needs at least one letter or digit, and two names that would be confused for the same library are refused ("rename one of them"). A shared library is labelled by its folder's name unless the site gives a label.

- Who: an admin.
- Setting: Folders in every new project. Does: the folders laid down inside each new project. Default: learned from the sample projects shown at set-up. Who: an admin. Applies to: the site. Search words: project template, folders, new project, layout.
- Setting: Shared libraries. Does: folders in the tree every editor's computer gets, such as the LUT library and the Resolve stills gallery. Default: the LUT library and the Resolve stills gallery. Who: an admin. Applies to: the site. Search words: shared libraries, LUTs, stills, assets.

### Every setting is made in the dashboard and kept through every update

Every setting of the site is made in one place, the dashboard (in set-up or in settings), and takes effect when it is saved, or the dashboard says why it cannot. Installing the server asks only for its two places. An update or a reinstall keeps every setting, secret and saved choice; where one would change, it is shown first. The port the dashboard answers on, which the person installing gives on the NAS's app screen, is shown in the dashboard read-only, saying it is set on the NAS.

- Who: an admin.
- Setting: Port the dashboard answers on. Does: the port the dashboard listens on at the NAS's addresses. Default: 8480. Who: the person installing, on the NAS. Applies to: the site. Search words: port, 8480, address, listen.
- Setting: Syncing only over the private network. Does: when on, computers sync with each other and the server only over the studio's private network, and the server's private address is offered to computers first. Default: off. Who: an admin. Applies to: the site. Search words: private network only, sync route, LAN, remote sync.
- Pending: server-install-and-running-1-Q22

### The site's settings can be exported, imported and the last change undone

"Export" downloads the site's settings as a plain-text file ("No password or assistant key is in it."). "Import" takes pasted text (up to 65,536 characters), "shows you every setting it would change and asks first. Nothing changes until you say yes.", including which reporting categories it would switch off. An import goes through every check a save does; settings the dashboard does not hold are ignored; text with none it recognises is refused; text that cannot be read is refused with the reason. "The last few times a save or an import changed these settings. Undo puts back the values from just before the most recent one." with "Undo last change", which asks first.

- Who: an admin.
- Name and search words: Export and import settings. Search words: export, import, backup settings, undo, restore settings.

### A part switched on but missing something it needs says so

When a part is switched on but something it needs is not there, the dashboard says so to the admin, never as a refusal:

- YouTube downloads on with no assistant key: the YouTube page reports it has no working key until one is set;
- Timeline Cards on with no place for its data: it keeps its place in the menu, and opening it shows the page saying it is not working right now, that it has no place for its data, and that admins have been told (see The dashboard: Overview, menus and finding things, "Each part's state is shown on the Overview");
- the Footage Sorter on with no card pool; cloud-state or backup folders that are not full places on the NAS, or set without a pool; a cloud-state folder inside the pool (not used); no source or destination folders; any folder outside the pool (a move between disks would fail).

A new site starts with every one of the six switchable parts off (the b-roll archive, music, YouTube downloads, Timeline Cards, the Footage Sorter with camera cards) except the help for the editing program, which is on. The extra measures against YouTube's blocking are off (and can be on only when YouTube downloads are on), and automatic updates of editors' apps are off. YouTube downloads are always tried on the requesting editor's own computer first. Each part is switched on and off with the setting "Switchable parts" (see The whole product: The rebuild itself, "An admin switches each part on and off for the whole site").

- Who: an admin.

### Transfers to editors always stay within what the NAS can serve

The server never hands editors' computers a transfer setting the NAS's file service cannot serve (on a Synology, at most 64 KiB pieces, 16 at a time). If such a setting is ever found stored, editors are given the safe values at once, and the admin is told, as a serious problem, "the server settings can cut big downloads short": large proxy downloads (over about 514 MB) end early under it. The fix offered puts the safe values back, and any proxy larger than that which came down under the wrong setting is fetched again.

- On its own: gives editors' computers transfer settings the NAS can serve, from the kind of NAS.
- Pending: server-install-and-running-1-Q22

#### Lessons

- Met: SRV-036, SRV-037, SRV-038, SRV-039, SRV-040, SRV-041.

## Updates, restarts and rollbacks

### Updating the server never takes the dashboard away

A server update keeps the dashboard and every open editor's page answering throughout, with no gap a person or an editor's app can notice. The dashboard serves within seconds of starting, with or without internet access; anything it refreshes from outside runs beside it and applies at a later start. An update waits until running download jobs have finished, trying again by itself, and is never forced past a running job. Updating one part never removes, switches off or downgrades another. How a new version is offered and taken is in Releases and updates: The server updating itself.

- On its own: holds an update back while a download job is running, from the jobs running now.

### An update is kept only when the new version really serves

After every update the server checks that the new version answers as itself: healthy, giving its own version, and serving a real page and its stylesheet, within about 150 seconds (a slow NAS may stretch this to about three and a half minutes). On success the admin is told "the dashboard is serving" with its version. Otherwise the update counts as failed and is undone on its own: the failed version is set aside (never deleted), the version it replaced is put back and started, and the server is checked again. The admin is told why it failed (it answered as another version, could not be asked, or answered nothing readable), that nothing was deleted, and either that the server answers again ("this update is UNDONE, not finished") or that it still does not answer and the fault is not this update's, with where to look. A failed update is never applied again on its own. A new version of the editors' app is never offered while the server it depends on is failing its check.

- On its own: undoes an update that does not serve within its time, from the check after the update.
- By hand: the admin can try the update again, or go back further, from the dashboard.

### An update replaces the server whole or not at all

A new version is brought onto the NAS and checked complete (every file, by its content) before it replaces anything; the running server is not touched until then. What the admin is told:

- an empty update is refused, saying nothing would be installed;
- if the new version could not be brought in whole or does not match, the installed server is untouched;
- if putting the new version in place fails, the previous version is put back and the admin is told so;
- on success, the version installed and that the previous one is kept to go back to.

An interrupted transfer of a large update resumes from the files already delivered, each verified by its content, rather than starting again. Leftovers from a failed attempt are removed by the next attempt and never pile up across retries; the admin is told how much was reclaimed. On a full or read-only disk, an update or a going-back either restarts into the new code or stops before swapping anything, and says plainly which. An update interrupted by a power cut or a restart shows on the next start as failed at the step it reached, and can be tried again or undone from the dashboard. If an update fails after the new version is already in place, the server is restarted onto a known version, which is named, before the failure is reported; no later update ever removes anything the running server still uses.

### The version to go back to is always kept

After a successful update exactly one previous version is kept on the NAS, named with the date and time it was replaced; older ones are removed, except any the running server still uses, which are kept and the admin is told so. Applying the version that is already running changes nothing and keeps the existing version to go back to unchanged; the admin is told nothing would change.

- Who: an admin goes back, from the dashboard.

### Going back never reaches a version that cannot read the studio's data

Before every update the studio's data is backed up (see "Before every update the studio's data is backed up"). Going back never reaches a version that cannot open the studio's data as it now is, unless the admin restores the named backup taken before the update or accepts the risk in words. Only real failed starts count as a reason to go back on its own. A server that has gone back past the format of a search index still starts, with that search marked unavailable and why; an index is never given to a server that cannot read it, and going back on an index restores only a complete index and checks it opens before saying it is done. See The b-roll archive: Replacing the search index.

### Reinstalling never deletes what the server holds

Installing the server again over an existing one, even from scratch, never deletes the server's stored data (its records and everything else it keeps on the NAS). If the old installation cannot be taken down, the NAS's reason is reported and the reinstall stops. If the version would not change, a reinstall is only a restart and the admin is told so.

### The admin can see which version is running and whether it is what was shipped

The dashboard shows the version the server is running now, read from the running server itself; when it cannot be read, it says so, never a guess. Every update records what it shipped, file by file with checksums, and the dashboard shows whether the running server matches it; where there is no such record it shows "not checked", never a verdict. A record of an update that is not newer than the running server is retired silently; the alarm that an update is not running sounds only when a newer update has really not taken.

- Who: an admin.

### Settings take effect without a restart, and no page restarts the server

A setting saved in set-up or settings takes effect when it is saved; nobody has to restart the server for it. No page of the product, the dashboard or any part, can restart the shared server. Updating the server and going back to an earlier version from the dashboard are an admin's deliberate acts, not such a restart, and keep the dashboard answering throughout (see "Updating the server never takes the dashboard away"). Where the server must be restarted (for example after the NAS was repaired), the admin does it from the NAS's own app screen, and the server comes back by itself after a crash or a NAS restart unless someone stopped it.

### After a restart the server comes back as it was

After any restart, the server comes back exactly as it was: set-up resumes where the admin left it, work interrupted by the restart shows as interrupted with a way to try again, and a saved sign-in (to the assistant or anything else) reads as signed in without a manual test, while a sign-in that had just failed or been signed out still reads that way.

### Extra software the parts need follows the version the product approves

The extra software a part needs on the server counts as present only when it is exactly the version this release of the product approves. A different version is replaced with the approved one the next time it is fetched, and the previous one is kept beside it (one copy) until the new one works.


### Missing or damaged records stop the server with a clear message

If the server's own records are missing or damaged, the server does not start fresh (which would reopen first-admin set-up over a studio that has one): it stops with a plain message saying what is wrong and how to restore the records from a backup or a snapshot. Every change to the shape of the records is preceded by a backup. An admin who is locked out has a documented way back in.

#### Lessons

- Met: SRV-042, SRV-043, SRV-044, SRV-045, SRV-046, SRV-047, SRV-048, SRV-049, SRV-050, SRV-051, SRV-052, SRV-053, SRV-054, SRV-055, SRV-056, SRV-057, SRV-058, SRV-059, SRV-060, SRV-061.

## Shares that go away, and checks that cannot run

### A share that goes away is noticed and nothing is written to it

A NAS share that drops leaves an empty folder where it was. The server therefore judges a share present only by something known that exists on the real share, never by the folder it is reached through existing or listing. Before writing to a share, the server confirms it by that known item and creates nothing first; a share that has gone is shown unavailable within one round of checks, and anything that would write to it is refused in plain words. When the studio's tree moves to another share or NAS, everything that reads it follows or stops with an error; none goes on serving the old copy.

### A missing or empty project tree is reported once, and nothing is marked deleted

When the projects folder cannot be read (naming the system's error), is not there, or is there but completely empty, the admin is told, as one serious problem on the home page and by mail: "the project tree is missing: <the projects folder> <is not there at all | is there but completely empty | cannot be read: error>. This normally means the storage is not mounted. Nothing has been marked as deleted." It is not raised when no projects folder is set. While the tree is in that state nothing is marked deleted, and counting the files of projects is skipped with "skipped: the projects tree looks unmounted (0 entries)". It clears once the folder is readable and not empty; when fine, the health summary says how many top-level entries there are and how many are projects.

A listing that takes a project from many files to none, or the studio from many projects to none, is refused and reported, never acted on: the previous count is kept. A project whose folder is missing is recorded as missing on the NAS, and one with no video and no sign of being a synced folder as looking unmounted, never as empty.

### A switchable part whose data goes away becomes unavailable and comes back by itself

For each part a site can switch on (the b-roll archive, music, YouTube downloads, Timeline Cards, the Footage Sorter), the server knows whether it is working, unavailable, damaged or switched off, with a reason. A part that is switched on but did not start raises a warning: "The <part> page is not available on this server: <reason>. Editors will not see the link in the menu." A switched-off part raises nothing. Every few minutes the server checks that each available part's data is still there; if it has gone, the part becomes unavailable: "the folder it serves is not there any more (<folder>). Every request to that page will fail until it is back." When the data comes back, the part comes back by itself within seconds, with no restart; the change is shown on the part's state. A check that itself fails changes nothing. No failure of an optional part ever stops the dashboard starting or serving: the dashboard keeps telling everyone whether their footage is syncing.

- When a part is off: it raises nothing and is listed only in settings, with its switch.

### Every check tells present, absent and could-not-check apart

Every check the server makes ends in one of three answers: present, absent, or could not check. Could-not-check names its reason and stops whatever depended on it; it never reads as "nothing there" or "done". Work that needs something the site has not set up (the NAS's file sharing, the project tree) shows "not set up", never a success that did nothing and never "down", and raises no alert. A projects folder that is set but does not exist fails with "the projects folder does not exist" and its place. Keeping history tidy, the protection list and the alert checks run regardless.

### Background checks never hang the pages

The status and health pages answer within seconds while a share or a service on the NAS hangs. Every round of background work has a time budget and says when it was partial. Anything editors can write or a link can name is limited in size before the server processes it, so what is stored and the work it causes stay bounded and background checks never stall.

### The Synology tree's access rules are checked

On a Synology, the server checks that the tree's folders keep their Synology access rules and that a rule lets editors write there, and shows one of: could not read the folder's rules; its Synology rules are gone (it was changed by hand), with the repair; no rule lets editors write there, with the repair; or intact. TrueNAS has no equivalent.


#### Lessons

- Met: SRV-062, SRV-063, SRV-064, SRV-065, SRV-066, SRV-067, SRV-068.

## Snapshots, restoring and the server's disk

### The project tree and the server's records are snapshotted on a schedule

The server keeps point-in-time snapshots of two things on the NAS: the whole project tree, and the server's own records (the studio's projects, people, computers and what each computer syncs). Each covers everything beneath it.

- Hourly snapshots on the hour, kept 24 hours; daily snapshots at 03:10, kept 30 days. Snapshots are taken even when nothing changed. Media snapshots are kept weeks, not months, because a snapshot keeps deleted footage on the pool until it expires; the server warns before snapshot space fills the pool.
- On TrueNAS the server makes the schedules itself, for storage areas of their own only. A whole pool is refused (it would snapshot everything on it), and a folder that is only a plain folder in a pool is told it has no snapshot protection of its own and must first be made a storage area. Each schedule is created, corrected or left alone and reported as such, with how long it is kept; every schedule's name pattern carries the hour and minute, and after making them the server confirms each one really exists.
- On Synology, schedules need DSM's free Snapshot Replication package. Where the package is there and DSM accepts the schedule, the server uses the time of day and the number to keep. Otherwise the admin is given the steps: install Snapshot Replication, schedule the tree's shared folder every hour and every day, keep 24 hourly and 30 daily snapshots, do the same for the shared folder holding the server's data, and check that snapshots appear.
- Setting up shows what would be done first and changes nothing until the admin confirms. The report names the kind of NAS, the two places, and for each either "NO snapshots found: this has no point-in-time behind it" or how many there are and the newest with its time. A place that cannot be scheduled is named with the reason, followed by "Backups are NOT fully configured". Each schedule succeeds, fails, or needs a step the admin must take on the NAS; any failure or such step is listed and the report ends "Backups are NOT fully configured"; a clean report ends by asking the admin to check again within the hour that snapshots are appearing.
- The admin can also take an immediate snapshot of both places under a name they give.
- With no place known for the server's records, the admin is told the server's records then have no snapshot behind them.

- Who: an admin.
- Setting: How long hourly snapshots are kept. Does: how long each hourly snapshot of the tree and the server's records stays. Default: 24 hours. Who: an admin. Applies to: the site. Search words: snapshots, hourly, retention, keep.
- Setting: How long daily snapshots are kept. Does: how long each daily snapshot stays. Default: 30 days. Who: an admin. Applies to: the site. Search words: snapshots, daily, retention, keep.

### Set-up task: protect your data

"Protect your data" (optional): "Schedule NAS snapshots, or keep a backup of the server's records." Done when the NAS has a snapshot schedule covering the server's records and the tree ("N snapshot schedule(s) on the NAS", with the newest backup); also done, with a note that there is no snapshot schedule and why that matters, when only a backup of the server's records under 7 days old exists; otherwise to do, pointing to "The project tree and the server's records are snapshotted on a schedule". On Synology it says the NAS's snapshot schedules cannot be read, asks the admin to confirm them in DSM, and checks for recent backups instead. Any time the server starts or is updated while either place has no snapshot schedule, the admin is warned ("no snapshot behind this") with how to check again.

- Who: an admin.

### A snapshot is taken before anything risky and sweeping

Before an update, a reinstall, any change of ownership that walks a whole folder tree, or putting back a folder move, a snapshot of what is about to change is taken. On TrueNAS a folder that is not its own storage area is snapshotted through the one containing it, and the admin is told so; a folder not on a pool is refused. On Synology the whole shared folder is snapshotted; a place not inside a shared folder is refused. The snapshot is labelled with what it was for and when (on Synology the label becomes the snapshot's description). A snapshot that already exists under that name counts as taken.

If no snapshot can be taken, the change does not go ahead: the admin is told why, how to set up regular snapshots, and may go ahead anyway only by accepting in words that the change has nothing behind it. Putting back a folder move is the exception: it deletes nothing, so it takes a snapshot when it can and goes ahead when it cannot, without asking. Every such change ends by saying "this change had a snapshot behind it: yes", or "NO" with the reason, and every attempt (what for, the place, the time, the result) is kept in the history.

- Who: an admin.

### Before every update the studio's data is backed up

Just before switching versions, the studio's data (including the b-roll archive's and the music library's descriptions) is copied into a dated backup named for the update. A part that cannot be copied is skipped and the backup says so; it never stops the update. Where the NAS takes snapshots and the server has been given access, a snapshot named for the update and the time is also taken; otherwise the update notes that no snapshot was taken and why. Backups are kept newest first, at most 3 per update, at most 8 in all and at most 8 GiB in all; the newest is never deleted.

### The protection list says what really stands between the studio and a loss

"What stands between this studio and losing something, and what does not. Nothing is assumed to be there." About every 15 minutes the server checks nine lines, always all listed, in this order. Each is "protected", "missing", "cannot verify", or "could not run" (the check itself failed); "could not ask" is never shown as green, and "Cannot verify is not protected." A line no check has reached yet shows "cannot verify": "no protection check has run yet on this server". The list shows "N of M confirmed, N missing, N this server cannot check, last looked at <ago>" and every line that is not protected shows what it means and its repair.

| Line | When it is what |
|---|---|
| the project tree is on a snapshot schedule | Synology: always "cannot verify, confirm in DSM: this Synology's snapshot schedules are in the Snapshot Replication package, which this server has no way to read. Open DSM, Snapshot Replication, and check the schedule yourself." TrueNAS: "cannot verify" when the NAS could not be asked or the server does not know which storage area holds the tree; "missing" when no enabled snapshot schedule covers it (on it, or on a parent including everything below); otherwise "protected": "N enabled snapshot schedule(s) cover <area>". Repair: set up snapshots (see above). |
| the server's own records are on a snapshot schedule | The same rules for the storage area holding the server's records. Repair: make that place a storage area of its own and schedule snapshots of it. |
| a snapshot was actually taken in the last day | Synology: "cannot verify". TrueNAS: "cannot verify" when not asked; "missing" when no schedule is enabled ("N snapshot schedule(s), none enabled"; a disabled schedule counts as absent); "cannot verify" when no enabled schedule reports a last run; "missing" when the newest is over 25 hours old ("newest snapshot N h old, over the 25 h limit"); otherwise "protected". |
| this server only accepts CC Sync builds we signed | "missing" when no signing key is set; otherwise "protected", showing only how many keys, never the keys. |
| the release signing key has been backed up | "cannot verify" when no key is set; "protected" where every key is the vendor's ("the vendor holds the update signing key; there is nothing for you to back up"); "missing" when no admin has recorded a backup; otherwise "protected" with the date recorded. |
| somebody has actually restored from a backup this year | "missing" when no restore has been recorded or the last is over 365 days old; otherwise "protected". |
| files deleted on the server are kept for a year | "cannot verify" until the server has read the projects since it started, or when there are none; "missing" for each project whose deleted files are kept nowhere ("files deleted on the server for this project are not kept anywhere"); otherwise "protected" with the shortest keeping time in days. Repair: untick and re-tick the project. |
| deleted-file copies on editors' computers are within their limit (a warning, not an error) | From each computer's reported size of its kept deleted files: "cannot verify" when none has reported; "missing" for each computer over 50 GB; otherwise "protected", saying that the 14-day half of the rule is not checked. |
| somebody is told when this server finds a problem | "protected" only when alert delivery shows as working, by the one rule of The dashboard: Alerts by mail, "The dashboard says whether alerts are really reaching anyone"; otherwise "missing" ("nobody is told when something breaks here" when nothing is set), quoting how many checks the server makes; "cannot verify" when the delivery record cannot be read. When an admin has recorded the choice to tell nobody, the line stays "missing" and reads that nobody is told, by the admin's own choice. Repair: choose mail or a web address in the alert settings and press "Send a test". |

Every line that is "missing" is a serious problem on the home page, "a safety net is not there"; every line that cannot be verified, or whose check failed, is a warning, "a safety net this server cannot check". Neither is raised before the list has been worked out once, and the alert line raises neither while it is missing by the admin's recorded choice to tell nobody. A skip in set-up never turns a line green. The weekly report lists every line. See The dashboard: Problems the server finds.

- Who: an admin.
- Name and search words: Protection. Search words: protection, backups, snapshots, safety, what is protected.

### Deleted files on the server can be brought back for a year

A file deleted on the server, including a camera original deleted over the NAS's file share, is kept for a year for each project and can be brought back by an admin for that time. By default, editors cannot delete originals over the file share. See Sync: Deletions and removing a project.

### An admin records what only they can confirm

"This server cannot see a key on your workstation or a restore you did by hand. Record it here and the lines above turn green." Two records, each showing "last recorded <date> by <who>" or "never recorded":

- "The release signing key is backed up, on <date>" with "I have backed it up"; not shown where every signing key is the vendor's;
- "A restore from a backup was tried, on <date>" with "Record a restore".

The date is written year-month-day ("that is not a date this server can read. Use YYYY-MM-DD.") and may not be later than tomorrow ("that date is in the future."); blank means the day it is recorded. It is recorded under the admin's name, written to the history, and the line is checked again at once: "recorded <date>." A successful restore rehearsal (below) also records the restore date.

- Who: an admin.
- Ways in: the admin's own record; a successful restore rehearsal.

### The server rehearses a restore to prove the snapshots work

"Copies one real file out of the newest snapshot into a scratch folder, checks it came back exactly, deletes it again, and records the date on the protection list." From the newest snapshot (or one the admin names), the first file between 1 byte and 64 MB is copied to a scratch place, compared byte for byte, and the copy deleted; scratch left by an interrupted rehearsal is cleared first. "Rehearse a restore now" answers "rehearsed a restore from <snapshot>: restored one file out of this snapshot and it came back byte for byte." or "the rehearsal FAILED: the file that came back is NOT the file in the snapshot". Only a rehearsal whose bytes match records the restore date; a failed one records nothing there. The last five show "worked" or "failed", when, the snapshot and the detail; the last 20 are kept, and every rehearsal is in the audit trail. Refusals: no snapshots visible ("this server cannot rehearse a restore: <reason>"); the snapshot holds no project tree where expected; no file small enough ("under 64 MB"); a copy error.

- Who: an admin.

### The recovery guide walks an admin from what went wrong to what to do

The recovery guide answers even when the NAS is down, saying what it could not find out, and asks the NAS afresh each time it opens. "Nothing on this page overwrites anything." It shows the protection summary ("N confirmed, N missing, N this server cannot check." with every line not protected, or "Everything this server checks is in place.").

The admin picks what went wrong from five problems; nothing picked shows "Pick what went wrong, and what to do appears here." Each answer lists steps, each marked "this server can do this" (with "go" to where it is done), "on the NAS, as an administrator" (with the exact commands for this NAS, its real names filled in), or "not printed" ("this server is not sure of the names these commands need, so it will not guess"). A restore always copies into a new folder and never replaces anything.

1. "Something on the server was deleted, overwritten or changed by mistake" ("One project, one folder or one file. The usual one."): restore it here into a new folder beside the projects; look in the project's deleted-files folder first if it was recent; and, only when the server cannot read snapshots, the commands for restoring one file from a snapshot on the NAS and giving it the right owner.
2. "CC Sync changed clip paths in somebody's Resolve project and they are wrong": undo it from the dashboard (applied when that computer next reports with the project open), or "Undo last fix" in the app's settings on that computer; if the undo cannot help, the copy of the project saved on that computer before the change. See Resolve on the editor's computer: Fixing media: copying in, rehearsals and undo.
3. "This dashboard has lost projects, editors or their ticks": put back one of the server's own backups, and what that costs (ticks made since the backup must be redone); or the commands to restore the server's records from a NAS snapshot (stop the server, copy back, fix the owner, start it).
4. "The b-roll or music search is empty or wrong": go back to the previous search index (see The b-roll archive: Replacing the search index).
5. "Everything on the server is wrong since a particular moment" ("The last resort, and the only one here that destroys anything."): stop all syncing first; "This is the one that cannot be undone"; the commands to list the project tree's snapshots and roll it back to one; then put back anything the rollback undid (recreate lost projects through project set-up) and watch the first sync afterwards.

An unknown problem gives the single step "there is no recovery here for <name>".

- Who: an admin.
- Name and search words: Recovery guide. Search words: recovery, restore, disaster, lost files, rollback.
- When the help for the editing program is off: problem 2 is not offered.

### The recovery guide shows the facts it relies on and prints no command it cannot confirm

Each fact is shown with its value, whether it is confirmed, why not, and how to fix it: which kind of NAS this is (confirmed when the NAS answers and a kind is set); the storage area holding the project tree and the one holding the server's records (confirmed only when the NAS's own snapshot schedules name it or a parent including everything below; never on Synology); the storage pool the footage is on; where the server reads the project tree (confirmed when available); the snapshots the server can read ("N snapshot(s), newest <name>"); and the account the server runs as on the NAS. "This server could not gather anything about this NAS just now." when it could gather nothing. Restoring files needs opposite ownership steps on TrueNAS and on Synology, so a block of commands needing a fact that is not confirmed is replaced by "<title>: this server will not print these commands", naming each missing fact, why and its fix, and saying to do it by hand with someone who can check the NAS. Confirmed facts are filled into the commands. Gathering facts never breaks the page.

### The recovery page lists the NAS's snapshots or says exactly why it cannot

The server reads the project tree's snapshots read-only, and sees every snapshot, including ones never opened since the server started (a NAS mounts each snapshot's folder only when it is first opened). When it can read them they are listed newest first. Otherwise a reason is always given: the server was never given access to snapshots ("this server cannot read any snapshot", with how to give it read-only access); snapshots were never set up (said as that, not as "none exist"); the place cannot be read ("The snapshots may have been moved."); or there are none ("there are no snapshots yet. Either none has been taken yet, or they are kept somewhere else."). Not being able to see snapshots is never shown as "there are none" and never makes a project look missing.

- Who: an admin.

### Before restoring, an admin sees what is missing, changed and new

"Pick a project and a snapshot." "See what is missing" changes nothing. The snapshot's copy of the project folder (found by the project's present name) is compared file by file, by path and size, skipping hidden files, with the folder now:

- "<project> in <snapshot>: N file(s) missing from the server now, N that are there but different, N the same", with sizes, and files added since; up to 300 of each named ("+ <path>", "... and N more");
- when either side has more than 50,000 files, no counts at all: the folder holds more "than this server compares in one go. Restore the folder with the commands on the recovery page instead: a restore this large is a transfer, not a click." A comparison that stopped early never shows counts or zeros;
- otherwise "Nothing here is overwritten. Whatever you restore is copied into a new .restored folder at the top of the projects folder on the server, under the project's own name, and the files that are there now are left exactly as they are.";
- when this snapshot was already restored for this project, that is said first: "This snapshot was already restored on <date> UTC: N file(s) went into <where> on the server." (and how many times), that those copies are there and not in the project, so the same files still count as missing, and that restoring again makes another full copy;
- when snapshots cannot be read: "This server cannot read this NAS's snapshots, so it cannot put anything back by itself. <why>".

- Who: an admin.

### An admin restores a project's missing files into a new folder, never over the project

"Restore into a new folder" copies the files missing from the project, and, with "also bring back the ones that are there but different" ticked (ticked already when only changed files exist), the changed ones too, out of the snapshot into a new hidden folder at the top of the projects folder, named ".restored-<date and time>" and holding a folder with the project's name, at the same places inside. It asks first: "Copy N missing file(s)[, and the N different one(s),] into a new folder? Nothing there now changes."

- That folder is not a project and is not synced to any editor: restored files reach editors' computers only when an admin moves them into place. Nothing existing is overwritten, deleted or given a new owner; file dates are kept. There is no way to restore over the live project.
- A fresh snapshot is attempted first and the result reported (the restore goes ahead if it fails).
- A file that fails to copy is counted and named (the first 20) and the rest continue.
- Result: "Restored N file(s) into <where>, at the top of the projects folder on the server. A name that starts with a dot may be hidden in Explorer or Finder until hidden items are shown." plus "N could not be copied: <list>".
- The last ten restores are shown (when, who, how many files, snapshot, where); the last 20 are kept with size and failures, and each is in the audit trail.

Refusals, each saying nothing was changed:

- no such project ("there is no project called <name> on this server"); the project has no known folder; the project tree is not available to the server; no folder for the project now ("there is no folder for <name> on the server to restore into");
- the server cannot see snapshots; a snapshot name that is empty or contains a slash, backslash or dots ("<name> is not a snapshot name this server will accept"); no such snapshot ("there is no snapshot called <name> on this NAS"); the snapshot cannot be read; the snapshot has no folder for the project ("Either the project did not exist yet when it was taken, or its folder has been renamed since"); a path leading out of the project;
- more than 50,000 files on either side, or more than 20,000 files to copy: a restore that cannot cover the whole folder is refused, naming the limit and pointing to the commands on the recovery guide; it never restores part and reports done;
- nothing missing but files differing without the box ticked ("N file(s) are there with different contents. Tick 'also bring back the ones that are there but different'"); nothing to restore;
- the destination folder already exists ("A restore never writes into a folder that is already there: rename or delete it first."); the destination cannot be created.

- Who: an admin.

### Anything large written to the server's disk is refused first when there is no room

Every large write onto the server's data disk (a new version, extra software a part needs, any upload) first checks there is room: it is refused when free space is below twice what it needs plus 256 MiB (the 256 MiB floor applies even when the size is unknown), before a byte moves. The refusal shows on the page that asked: "not enough free space on the data volume: N MiB free, <what> needs about M MiB. Free some space and try again." A disk whose space cannot be measured is not refused, and that is said.

### The server's own data space is watched

The server watches free space on its own data disk and on the NAS's pools. A serious problem, "the server is running out of space", is raised and mailed when under 10 percent or under 2 GB is free, whichever comes first; the fix: remove old kept versions or backups the dashboard lists, or enlarge the volume. Free space that cannot be read is "could not check" ("That is not the same as knowing it is fine."). The NAS's pools are warned about before they fill, including when snapshot space is what is filling them. The dashboard shows how much of the data disk is used and by what. The home page also says when there is no off-site copy, and when a shared Resolve project database is not backed up.

Everything the server keeps expires by a stated age or count: snapshots (above), backups (at most 8, 8 GiB), the nightly copies of a shared Resolve project database (30 days, counted apart from those backups), kept versions (the running one and the one to go back to), crash reports (the newest 20), histories (the last 20 restores and rehearsals; the newest 2000 runs of background work), and its own log, kept to at most about 100 MB (the oldest dropped first), so nothing can fill the NAS.


#### Lessons

- Met: SRV-069, SRV-070, SRV-071, SRV-072, SRV-073, SRV-074, SRV-075, SRV-076, SRV-077, SRV-078, SRV-079, SRV-080, SRV-081, SRV-082, SRV-083, SRV-084, SRV-085, SRV-086, SRV-087, SRV-088.

## Off-site backup

### The NAS copies the studio's work off site every night

Every night the NAS itself copies off site what is needed to rebuild a client render: for every project ticked for off-site backup, its 1080p proxies, audio, stills, graphics and project files, plus every Resolve project (the editing program's database backups), and, when the Footage Sorter is on, its daily backup of the record of every copy (see The Footage Sorter and camera cards: The record of every copy, "The record survives losing the NAS"). No editor's computer needs to be on. The off-site copy is encrypted so that the storage host can read no file names and no contents.

- It runs each night at 04:15 by default; the time and on or off can be set; a missing or broken schedule means the defaults. Only one run at a time. A run that fails is not tried again that night. A run that finds nothing changed makes no new off-site snapshot.
- Upload speed is capped lower in working hours than overnight (12 MB/s from 08:00, 30 MB/s from 23:00), so editors' transfers keep most of the studio's uplink by day.
- A single long-distance upload stream reaches only about 7 MB/s, while eight together reach 23 to 30 MB/s, so uploads and restores use several streams at once. A NAS's single long-distance streams also depend on how its network is tuned for long, lossy links (seen to jump from 0.3 to 17 MB/s); the server checks that tuning after every NAS restart and warns when it is missing.
- An admin can ask for a run now, which starts within 10 minutes.
- After a good run, the full list of files in the new off-site snapshot is kept so it can be browsed. Daily logs of the runs are kept 60 days.

- Who: an admin.
- Setting: Nightly off-site backup. Does: switches the nightly off-site copy on or off and sets its time. Default: on, at 04:15. Who: an admin. Applies to: the site. Search words: off-site, cloud backup, nightly, backup time.

### An admin ticks which projects are backed up off site

Each project can be ticked for off-site backup on the dashboard. An unticked project shows when its off-site copy expires. A ticked project with no upload in 3 days raises an alert.

- Who: an admin.
- Setting: Off-site backup for this project. Does: whether this project's proxies, audio, stills, graphics and project files are copied off site each night. Default: off. Who: an admin. Applies to: a project. Search words: off-site, project backup, cloud, tick backup.

### The off-site backup's state, schedule and run now

When an off-site backup is set up, the dashboard shows:

- its state: "Running (<manual | nightly>) since <date time>", with live progress (percent done, bytes and files done and in all, speed over the last two minutes, time left, the current file, errors, time so far; fresh when updated in the last 30 seconds); or "Last run: <manual | nightly> · started <date time> · took <duration> · OK | FAIL · <text>"; or "No run recorded yet.";
- "last snapshot <ago>", "<n> files, <size> · <size> added last run" (new, changed and unchanged files), "off-site space <used> of <total> used", "<n> errors", "last error: <text>";
- how long copies are kept: "kept: <n> hourly, <n> daily, <n> weekly, <n> monthly";
- "Nightly backup is off." or "Next run: <date time>". The next run is none when off; the set time on the same day if it has not yet passed; "now" if it has passed and that day's run has not happened; otherwise the set time the next day. Whether a run has been asked for, and when.

An admin sets "Nightly at" (on or off, and a time) and saves (offered only when changed; unsaved edits survive the page refreshing): "Nightly cloud backup at <time>." or "Nightly cloud backup is off."; a bad time is refused ("the time must be HH:MM, 24 hours"); a failure "Could not save the schedule: <reason>". "Run now" (not offered while running, already asked for, or not set up): "Cloud backup requested. The NAS starts it within 10 minutes."; refused with "a cloud backup is running already" or "a run was already requested; the NAS starts it within 10 minutes". When the off-site backup is not set up, or its folder cannot be reached, the dashboard says so. Others see "Schedule: every night at <time>" or "off".

Within about two minutes of a run finishing, the files it holds are known to the record of every copy (see The Footage Sorter and camera cards: The record of every copy).

- Who: anyone signed in sees it; an admin sets the schedule and asks for a run.
- Name and search words: Off-site backup. Search words: off-site, cloud backup, backup status, nightly backup, run now.
- When the Footage Sorter and camera cards are off: the off-site backup runs and shows as above; only the record of every copy is not kept.

### Off-site copies are kept for a stated time, and deleted files stay restorable

Once a week (the first successful run on a Sunday) old off-site snapshots are thinned to keep 24 hourly, 30 daily, 12 weekly and 24 monthly. A file deleted or changed on the NAS is not removed off site at once: it stays restorable from older off-site snapshots for that long. The page states this keeping policy.

- Setting: How long off-site copies are kept. Does: how many hourly, daily, weekly and monthly off-site snapshots are kept. Default: 24 hourly, 30 daily, 12 weekly, 24 monthly. Who: an admin. Applies to: the site. Search words: off-site retention, keep backups, cloud retention, history.

### The off-site backup's key is kept away from the NAS

The off-site copy cannot be read without its key, so the key must also be kept somewhere other than the NAS. The dashboard shows a warning, and the protection list a line, until an admin confirms the key is stored safely elsewhere, recorded with who and when.

- Who: an admin.

### Restoring from the off-site copy is estimated and rehearsed

Before a restore from the off-site copy starts, the admin is shown how long it will take and what it will cost. Each month the server verifies a sample of the off-site copy against the files it came from, and shows the result. A rehearsal, restoring a small project from the off-site copy onto a laptop and rendering it, is recorded like a restore on the protection list.

Any plan to put the studio's camera originals off site states its monthly cost, the first upload's length on the studio's uplink (about 3 weeks at 30 MB/s), and the time and cost of a restore, because cold archive storage is cheap to keep and slow and costly to restore.

- Who: an admin.

#### Lessons

- Met: SRV-089, SRV-090, SRV-091, SRV-092, SRV-093, SRV-094, SRV-095, SRV-096, SRV-097.

## Health checks and alerts

### Anyone can ask whether the dashboard is up

The question "is the dashboard up?" always answers, even when unhealthy, so installers and set-up on an editor's computer can tell whether it is running. Anyone gets only healthy or not, and the version. The server counts as healthy only when its syncing answered in a round that actually talked to it (or the site has none) and its background work is alive and its picture of the studio is not stale; none of the optional parts can make it unhealthy.


- Who: anyone.

### The server answers only on the studio's networks and comes back by itself

The server answers only on the NAS itself and on its publication on the private network, never on every address; the default port is 8480. It comes back by itself after a crash or a NAS restart unless someone stopped it. The NAS's own app list shows whether it is healthy: the NAS asks about once a minute, allows it about two minutes to start, gives each answer about ten seconds, and shows it unhealthy after three failures in a row.

### The server re-checks the facts the product relies on every 15 minutes

"A fact here is something that must always be true for the product to be safe." About every 15 minutes the server re-checks a fixed list of such facts. It names problems and repairs nothing ("Nothing on this page changes anything."). Each fact is shown with when it was last checked ("never") in one of four states:

- "ok", with evidence (for example "34 full tick(s), all shared");
- "broken", by severity, naming up to 20 things it is broken for, each with a detail, its consequence and its fix (with the support contact);
- "not checked", with the reason ("Not checked is not OK.");
- "could not run", with the error (200 characters).

The page heads "re-checked every 15 minutes" and "N broken, N could not run, N not checked, N ok", or "No check has run yet." Every broken thing becomes a problem on the home page with the fact's severity: "<consequence> This server checks that <fact>, and right now it is not true: <detail>." with the fact's fix. Things beyond the 20 named stay open. A check that reaches no verdict keeps what was open. A check that fails is a serious problem: "The check for '<fact>' could not run, so this server does not know whether that is all right. Treat it as unchecked, not as fine.", cleared when it runs again. After each round the server's status says "N fact(s) broken; M check(s) could not run; K not checked here", and nothing when all is well.

Two facts are on the list and checked like the rest: that deleted-file keeping agrees between the server and the editors' computers, and that each part on the server is the version that was shipped.

- Who: an admin.
- Name and search words: Facts the product relies on. Search words: invariants, facts, checks, health, always true.

### The admin sees when each kind of background work last ran

Every kind of work the server does on its own records when it started and finished, whether it worked, and a note or error. A run that worked but did only part of what it should says so ("partial: N folder(s) left for the next round", "refused N share removal(s)", "kept N project count(s): the listing collapsed", "N move(s) found on the server", "N safety net(s) missing", or the number of open problems). The newest 2000 runs are kept.

The admin's health view, read only, shows for each kind its last run and what it did not do: "failed" (with a note, or "no reason recorded"), a warning when it worked with a note or is "overdue" ("has not run again on time"), "incomplete", or fine; "nothing has finished yet" before any run. Only work this site actually does can be overdue, and only after a success: overdue means not run for twice its usual interval (at least 3 minutes) plus about one full round. When the server's last look at the studio finished too long ago, it says that everything shown is the last thing it managed to do, not the state now. It also shows when old records were last cleared ("never"), active projects whose sharing has an error or is stopped, the 5 most recent sharing rounds that left a note, and the sharing changes the server would apply: "Nothing pending: every folder's shares matched the plan as of <ago>." or "What the server would apply, as of <ago>: N share(s) to add, N to remove. Read only, nothing on this page changes a share." with each project folder and the computers to add or remove (the first 100 folders). The NAS's sharing is shown reachable when work that needs it succeeded within the last 3 minutes.

One kind of work failing never stops the others: its half-done changes are thrown away and the rest carries on. A failed kind is tried again no sooner than normal, and after repeated failures waits longer each time, never more than five minutes between tries; one success puts it back to normal.

- Who: an admin.
- Name and search words: Server health. Search words: health, background work, jobs, overdue, status.

### Background work that stops is restarted and reported

The server watches, about every 30 seconds, that its background work is alive and moving. Background work is judged alive by when it last started a round, against the rhythm this server runs: stopped means nothing has started for twice the shortest normal gap between rounds, between 3 minutes and 2 hours (on a site without the server's own syncing, never less than 3 minutes), so a stopped one alarms within about 20 minutes at most; a brand-new server reads "cannot tell", and no runs at all is not shown as stopped.

- Work that died without being stopped on purpose is restarted, never into two at once: while the old one is still busy, the restart refuses and says so. Each restart is a warning on the home page: "The background work stopped and had to be restarted (N time(s) since this server last started). While it was down, nothing about the studio was being updated." with "If this keeps happening, restart the dashboard and send the server's crash reports to support."
- After three such restarts, on the fourth stop, or when it is alive but has made no progress for 15 minutes, the whole server restarts itself.
- While its data is stale, the server's health check fails.
- Work stopped on purpose at shut-down never counts as dead; at shut-down the server waits up to ten seconds for it.

The admin is told, as serious problems on the home page and by mail: "the server's background work has stopped"; "the server restarted its background work" (when it happens); "a server background job is failing", per kind of work whose last run failed, saying for how long ("The '<work>' work has been failing for about N hour(s): <meaning>. The server reported: <error, 200 characters>") and what it means for people, by effect:

| What is failing | What it means | Fix offered |
|---|---|---|
| setting up project folders for syncing | new and moved project folders are not being set up for syncing | look at the other problems (a stray project mark is the usual cause), otherwise restart the dashboard |
| reading the server's own syncing | the server cannot see its own syncing | restart the dashboard |
| sharing projects with computers | projects ticked or unticked on the dashboard are not reaching the editors' computers | untick and re-tick one project |
| refreshing the server's list of files | the server's own file list is not being refreshed | check the projects folder is there |
| clearing old history | old history is not being cleared on the privacy schedule | check free space |
| re-checking the facts | the facts the product relies on are not being re-checked | restart the dashboard |
| anything else | | "Restart the dashboard" |

Each clears when that work next succeeds. A warning, "a server background job is late", is raised when work that last succeeded has not finished within its expected time plus one alert interval; while the background work is stopped or that work is failing, an open "late" problem is held quiet.

- On its own: restarts background work that died, and restarts the whole server after repeated stops, from whether the work is alive and moving.

### The server says when it cannot write its own records

When failing work is failing because of the disk or the server's records (a disk error, a full or read-only disk, records locked, unopenable or damaged), a serious problem says so: "...Nothing this server records is safe while that is true." If the server cannot open its own records at all, it keeps trying every five seconds and shows that it cannot, on the home page and in the health answer. When the records are busy, saying so adds no write and stalls no request, and a valid session is never refused because a background write waited.

### Crashes are kept, shown and can be downloaded

Any crash in the server's work writes a crash report; a crash never stops the dashboard. The newest 20 reports are kept and older ones deleted; each is readable only by the server and names the time, the version, which part of the work crashed, the system, and the error in full, with passwords, keys, sign-in tokens and secrets in addresses removed first. Nothing is sent anywhere. A serious problem on the home page says "This server's own background tasks have crashed N time(s) since it started..." with the fix: press "Download crash reports" on the problem and attach the file; that download is the newest 20 reports in one archive. The problem closes itself once the newest crash is 24 hours old, and a new crash reopens it.

- Who: an admin.

### Each switchable part's state is shown with its reason

The server's status shows each switchable part as off, not there, partly working (hidden from editors' menus) or working, with a sentence, and notices within seconds when a part comes alive or breaks, without a restart. The sentences include: the part is not switched on for this site; the part is not installed on the server or did not start; the folder the part needs is not reachable; its data was written by a newer version than this server runs, so its page cannot open it; its data folder "could not be prepared: every request will fail until it is writable". A part this site has not set up shows "not set up", never "down", and raises no alert.

For the Timeline Cards editor the status shows: not started or stopped, missing something (with the first missing thing), starting, running, waiting to restart, or failing repeatedly (still retrying, slowly); how many times it has been restarted; and its last exit: "the editor stopped after <N>s; starting it again in <N>s." with the last three lines it wrote, or "the editor could not be started (<error>); trying again in <N>s". See Timeline Cards: the editor: Opening episodes and keeping the editor running.

- Who: an admin.

### The admin is told when the server's syncing is not answering

When the server cannot reach its own syncing, a serious problem says "the server's syncing is not answering"; it is mailed, clears when syncing answers again, and is left as it was when the server cannot tell. Not raised on a site that has no such syncing.

### Every problem the server finds reaches a person

Every problem the server can detect reaches a person on the home page and by message, with a plain diagnosis and the next action (see The dashboard: Problems the server finds, and Alerts by mail). Beyond that:

- Whether alerts are really reaching anyone is judged by one rule, shown on the alert channel's status line (see The dashboard: Alerts by mail, "The dashboard says whether alerts are really reaching anyone"). With no alert destination set, or nothing delivered in 30 days, the home page and the protection list say "nobody is being told"; a delivery record that cannot be read shows "cannot verify". When an admin has recorded the choice to tell nobody, the warning ends, but the home page and the protection list still read that nobody is told, by the admin's own choice, and never show it as green.
- When an alert destination is first set, everything open at that moment is sent at the next check, and the save says so.
- An optional daily "still here" message, counting computers and problems, lets the owner notice when messages stop.
- Delivering alerts finishes within two minutes a round; overrunning that is itself a problem, and a slow mail server never stalls or restarts the server.
- Alert mail checks the mail server's certificate and name by default; a mismatch names the host, and only an admin's explicit setting turns the check off (the setting "Verify the mail server's certificate", see The dashboard: Settings and setup, "Every setting of the site").
- The server alerts once, within minutes, when its own network link is down or its sign-in to the private network nears expiry, and when many computers fall silent together.
- A repeated identical answer is written to the log once, and again only when its state or detail changes, even across a restart.

### The server checks itself twice a day and the owner can approve a fix by reply

Twice a day the server has the assistant look over its own state, read only, and mails the admin a report of what it found, with a fallback summary or a note of failure when the assistant cannot run. A reply to that mail acts only when it comes from an address the site allows, the studio's own receiving mail server vouches for it, and it carries an unexpired reference that matches exactly; and it can only press a button the dashboard already offers. The admin's panel says whether this check can run, and if not, why: the assistant is not set up, or its sign-in has lapsed (then runs mail a plain summary until it is signed in again). The check runs on the assistant the way the site has set it up, usually a paid key, and its cost counts against the site's one daily budget for the assistant; when that budget is spent, the check mails the plain summary.

- Who: an admin.
- When the assistant is off: the check mails the plain summary only, and nothing can be approved by reply.

### One check of the whole server side, shown in the dashboard

One check covers everything the server needs and is shown in the dashboard: one pass or fail per part, plus warnings that never count as failures. It ends with "N of M checks passed" and, when there were warnings, a line saying nothing is broken but something is slow, with each listed. A check that cannot run is reported as failing, with the reason, and the rest still run. Each network check gives up after a few seconds (about 5 to 15). Computer names in other alphabets are shown as well as the screen can, never by stopping the check. What is checked:

- a shared Resolve project database on the NAS answers on the network (skipped, and said so, where the studio has none); this proves it is reachable, not that a sign-in works;
- the NAS is joined to the studio's private network, with its private addresses; each other computer on that network is listed as offline, reached directly, or relayed. A relayed computer is a warning: every byte to it passes through a relay, and the admin is told to check the network lets the direct path through in both directions;
- the path from the admin's own computer to the NAS is direct or relayed (a warning when relayed; skipped, and said so, when it cannot be read);
- the server's syncing answers, with the project folders it holds;
- the project tree's top folder exists (and on Synology that the editors' access to it is in place, or a warning when it cannot tell);
- the editors' group exists and has members, listing them ("exists but has no members yet" is a failure);
- on Synology, where editors' transfers go through DSM's own file-transfer server, that they stay within what it can serve;
- the dashboard answers healthy and sees its own syncing.

The state of the NAS's own connection to the private network is read on both kinds of NAS (on TrueNAS from its app, on Synology from its package).

- Who: an admin.
- Name and search words: Check everything. Search words: health check, doctor, diagnose, test server, verify.

### The server stays quick under load

Reports from editors' computers finish in about a tenth of a second under load; a warning about slow writes names what was really holding things up and never blames an editor's computer. Opening an episode of many two-hour interviews with no waveforms yet keeps the server's memory under a fixed ceiling, and no single feature can exhaust it. See The dashboard: Speed under load.

#### Lessons

- Met: SRV-098, SRV-099, SRV-101, SRV-102, SRV-103, SRV-104, SRV-105, SRV-106, SRV-107, SRV-108, SRV-109, SRV-110, SRV-111, SRV-112, SRV-113, SRV-114, SRV-115, SRV-116, SRV-117.
