# Entries that may be one lesson filed twice: batch 1 of 2 (107 groups)

## Group 1

### ACC-007 [accounts-privacy-legal / Who may sign in]: An admin grants a person access with one button.
- What was going on: The owner: "add the button for admins to grant access".
- What the product must do: An admin can grant a person access from a single button on the dashboard, with no other step.
- Kind: 2
- State: outcome not found

### APP-029 [editor-app / Security warnings, permissions and certificates]: A Mac app loses Full Disk Access after every update.
- What was going on: macOS ties privacy grants to the exact build of an app signed without a stable developer identity, so each update loses access to the sync drive.
- What the product must do: Mac builds carry a stable developer identity; the app checks Full Disk Access at every start and tells the editor exactly how to grant it.
- Kind: 1a
- State: outcome not found

### REL-002 [releases-and-updates / Facts about Windows, macOS and the NAS that bite an update]: On a Mac, the app lost its disk permission after an update, or never started.
- What was going on: macOS ties grants such as Full Disk Access to the code signature; an ad-hoc-signed app loses them on update, and a refused launch is silent.
- What the product must do: An update on macOS keeps the app's permissions and its ability to start, and a refused launch is visible to someone.
- Kind: 1a
- State: still open

## Group 2

### ACC-008 [accounts-privacy-legal / Who may sign in]: The editor page refuses anyone not signed in, even on the private network.
- What was going on: Other editors' computers share the studio's private network, so the owner ruled the page must refuse anyone without the key from the start.
- What the product must do: The editor page answers nothing to a device that has not signed in, even on the studio's private network.
- Kind: 2

### SRV-124 [server-install-and-running / Connections and credentials]: A helper's admin page on the server was open to the network with no login.
- What was going on: Anyone on the private network or LAN could share any project folder to their own device, and a first guard replaced a password the admin had set.
- What the product must do: No admin page the server runs is reachable without a login, and a login the admin already set is kept, never replaced.
- Kind: 3
- State: fixed, never shipped

## Group 3

### ACC-009 [accounts-privacy-legal / Who may sign in]: One online sign-in every 100 days, everything else works offline.
- What was going on: The owner wants one online sign-in every 100 days, warned about while online as it nears the end, with all other work possible offline.
- What the product must do: Sign-ins last 100 days, show when they end, warn within 14 days, renew in place, and an expiry never deletes anything saved on the device.
- Kind: 2

### CE2-109 [cards-editor / Working offline]: The cut editor works fully offline, with 100-day sign-ins.
- What was going on: Owner: "you only need to be online once every 100 days to log in ... it should warn you while online if the login is about to expire".
- What the product must do: Sign-ins last 100 days, a warning shows from 14 days before expiry while online, and an expired sign-in never stops offline editing or deletes downloads.
- Kind: 2

## Group 4

### ACC-010 [accounts-privacy-legal / How a computer proves who it belongs to]: A computer's sign-in never expires on a timer.
- What was going on: A computer's sign-in lapsed at 30 days overnight, stopping reports and transfers for two days; the owner: "get rid of expiring login", "not needed".
- What the product must do: A computer's sign-in ends only when an admin revokes it or the person's access is removed; browser sessions may still expire.
- Kind: 2

### APP-123 [editor-app / Signing in, the computer's identity and the licence]: An editor app's sign-in must never expire on its own.
- What was going on: Sign-in lapsed after 30 days; sync and reporting stopped silently on unattended machines (an editor lost two days, a render machine a weekend), with one night-time balloon.
- What the product must do: A healthy computer never loses its sign-in by time alone; if it is ever refused, the editor and dashboard are told and the editor reminded hourly.
- Kind: 2

## Group 5

### ACC-026 [accounts-privacy-legal / Passwords, sessions and failed sign-ins]: Every person has one page for themselves, their computers and settings.
- What was going on: The owner asked for a page where any user, admin or not, sees themselves and their computers, sets their name, password and every setting open to them.
- What the product must do: Every signed-in person can change their own name, password and personal settings and see their computers from one page; the name is a label, never an identity.
- Kind: 2

### DSH-007 [dashboard / Overview, menus and finding things]: An admin can open any person and see what they have and lack.
- What was going on: The owner asked for a per-person drill-down and "a full overview of all the projects being synced, who has what".
- What the product must do: An admin opening any person sees each project they ticked, per computer: what has synced, what has not, and what is missing.
- Kind: 2
- State: outcome not found

## Group 6

### ACC-032 [accounts-privacy-legal / Passwords, sessions and failed sign-ins]: The offline page was stored on devices with the user's identity.
- What was going on: The cached offline fallback page was drawn with the signed-in user's name, admin menu and form protection value, then stored on the device.
- What the product must do: Any page stored for offline use carries no user identity, admin control or security value.
- Kind: 3

### DSH-137 [dashboard / Phones and the installed app]: The installed dashboard could show a stored copy as live, with the last user's name.
- What was going on: A cached page served offline would claim footage was syncing during a halt, and the saved offline page kept the old user, admin menu and form token.
- What the product must do: Offline, the installed app shows an "offline" page carrying no user, role or form token; status, data and sign-in pages are never served from a stored copy.
- Kind: 3

## Group 7

### ACC-033 [accounts-privacy-legal / What each person may see and reach]: A browser sends the origin "null" from contexts that are not this site.
- What was going on: A request with origin "null" comes from a sandboxed or opaque context, yet it was treated like a request with no origin and allowed.
- What the product must do: A request whose origin is "null" is treated as coming from another site.
- Kind: 1a

### DSH-138 [dashboard / Security of pages]: Browsers send "Origin: null" from places that are not this site.
- What was going on: Sandboxed frames, data and blob documents and some redirect chains send "Origin: null", and it was let through like a missing origin.
- What the product must do: On anything that changes data or drives Resolve, "Origin: null" without a matching referrer is refused; only a truly absent origin may pass.
- Kind: 1a

## Group 8

### ACC-035 [accounts-privacy-legal / What each person may see and reach]: Any signed-in editor could read internal documents through the help pages.
- What was going on: Help served the whole internal document tree, including defect records, secrets notes and pages naming people, machines and NAS addresses, to every editor at every customer.
- What the product must do: Only guides written for customers and legal documents ship; help lists and opens only what the reader's role may see.
- Kind: 3

### ACC-038 [accounts-privacy-legal / What each person may see and reach]: The public client page also served the internal app's code to anyone.
- What was going on: The internet-facing client preview page shared a file folder with the internal pages, so anyone could download the internal app and its request map.
- What the product must do: The internet-facing client page serves only the files its viewer needs and refuses any internal page or script.
- Kind: 3
- Move to: broll

### BRO-133 [broll / Client folders and links]: The public client page exposed the whole internal app's files.
- What was going on: The public share address served every static file of the internal b-roll app, not just the viewer's.
- What the product must do: The public share serves only the viewer's own files and answers anything else as not found.
- Kind: 3

### DSH-141 [dashboard / Security of pages]: The help viewer served every internal document to anyone signed in.
- What was going on: Every document in the source tree, the bug ledger included, was browsable by customers.
- What the product must do: The help viewer serves only documents published for that reader's audience, refuses any path outside its folder, and keeps links between documents working.
- Kind: 3

## Group 9

### ACC-039 [accounts-privacy-legal / What each person may see and reach]: Any website in an editor's browser could drive programs on that computer.
- What was going on: The local helper and the editor's local server answered any web page or rebinding host name, accepting paths with ".." or Mac volume paths.
- What the product must do: Anything listening on an editor's computer answers only the product's own pages, refuses other sites and paths outside its folders, and logs each refusal.
- Kind: 3

### CE2-178 [cards-editor / Working offline]: A helper server on the editor's own machine answers only its own app.
- What was going on: The app's local server writes and deletes files on disk, so any website or rebound host name reaching it could touch the projects folder.
- What the product must do: The local server refuses any other Host or another site's Origin, and every path it touches resolves inside its own project folder.
- Kind: 3

## Group 10

### ACC-046 [accounts-privacy-legal / What the product records about a person]: Customer data never reaches the vendor in normal running.
- What was going on: The owner ruled no vendor telemetry: data stays on site, support data is shared case by case, never read by AI tools, and deleted 30 days after its ticket closes.
- What the product must do: Nothing leaves the site for the vendor unless an admin sends a support bundle; no AI tool reads it; it is deleted 30 days after its ticket closes.
- Kind: 2

### REL-072 [releases-and-updates / Customer sites and the vendor's release feed]: Customers get one exact build after it ran on the studio first.
- What was going on: Customers followed a moving label, so whatever was published last reached them untested; the owner ruled "customers pinned by digest, with vendor soak".
- What the product must do: A customer site updates only to the exact build named for it, refused until that same build ran 24 hours on the studio.
- Kind: 2
- State: fixed, never shipped

### ALL-007 [whole-product / The rebuild itself]: Every feature ships, from one build, switched on per studio.
- What was going on: The owner ruled "Keep every feature and get it ready", and that parts one customer lacks are switched off by a setting, never forked into another build.
- What the product must do: One build serves every studio with every feature working; a feature a studio lacks is dormant by setting, and client share links check the studio holds the rights.
- Kind: 2

## Group 11

### ACC-064 [accounts-privacy-legal / Third-party licences and what customers receive]: No customer receives the product's source code.
- What was going on: The owner decided no customer gets source; a customer copy of the code could not be built and leaked internal documents.
- What the product must do: Customers install from a package they are given; nothing in the customer path hands out source code or internal documents.
- Kind: 2

### REL-074 [releases-and-updates / Customer sites and the vendor's release feed]: No customer ever receives the product's source code.
- What was going on: The owner ruled that no customer gets source.
- What the product must do: No customer download, install or update contains the product's readable source, and no customer-facing step fetches it.
- Kind: 2

## Group 12

### ACC-066 [accounts-privacy-legal / Third-party licences and what customers receive]: Customer builds use the site's own paid assistant account, never a consumer subscription.
- What was going on: Consumer subscription terms do not allow use in a sold product; the owner keeps his subscription sign-in for the studio only.
- What the product must do: In a customer build the subscription sign-in is absent and cannot be turned on; the site's own business key works for every assistant feature.
- Kind: 2

### ALL-089 [whole-product / The assistant]: Customer builds use only the studio's own paid assistant key.
- What was going on: Customers have no personal subscription sign-in, consumer terms forbid reselling one, and the owner ruled nothing of the assistant is bundled.
- What the product must do: In a customer build every assistant call uses the site's own paid key, no setting enables subscription sign-in, nothing is bundled, and keys never show in full.
- Kind: 2
- State: fixed, never shipped

## Group 13

### ACC-072 [accounts-privacy-legal / How secrets and keys are kept]: A helper reading outside text was handed every server credential.
- What was going on: An assistant run over untrusted YouTube titles and descriptions inherited every secret in the server's environment.
- What the product must do: Any helper program run over outside text receives only an allow-listed set of settings, never a fleet, storage or signing credential.
- Kind: 3

### YTD-098 [youtube / The assistant behind search]: The assistant was handed every server secret while reading YouTube text.
- What was going on: The assistant ran with the server's whole environment, including fleet, login and NAS credentials.
- What the product must do: The assistant receives only the inputs its task needs, never the server's secrets.
- Kind: 3

## Group 14

### ACC-073 [accounts-privacy-legal / How secrets and keys are kept]: A redirect could resend a credential to another address.
- What was going on: Calls carrying credentials followed redirects, and the usual client strips only the standard authorization header, so a 307 resent the secret elsewhere.
- What the product must do: A credentialed call never follows a redirect and its refusal names the target; only an uncredentialed, signature-verified download may follow https redirects.
- Kind: 3

### SRV-120 [server-install-and-running / Connections and credentials]: Following a redirect replays a password or key to wherever it points.
- What was going on: A 307 or 308 redirect resends the body unchanged, and custom key headers usually follow; only the standard authorisation header is dropped across hosts.
- What the product must do: No request carrying a password, key or session follows a redirect; a redirect is refused with its status and target named, and nothing is sent on.
- Kind: 3

## Group 15

### ACC-075 [accounts-privacy-legal / How secrets and keys are kept]: Connections carrying footage or passwords did not check who answered.
- What was going on: File transfers accepted any NAS host key, server calls to the NAS skipped certificate checks, and alert mail sent its password unverified.
- What the product must do: Every connection carrying footage or a credential verifies the far end's identity, and a changed identity is refused.
- Kind: 3
- State: still open

### SRV-106 [server-install-and-running / Health checks and alerts]: Alert mail was sent without checking the mail server's certificate.
- What was going on: The encrypted mail connection accepted any certificate and any host name.
- What the product must do: Alert mail verifies the mail server's certificate and host name by default, a mismatch names the host, and only an explicit admin setting turns it off.
- Kind: 3

### SRV-119 [server-install-and-running / Connections and credentials]: The setup computer sent the NAS admin password to whatever host answered.
- What was going on: Admin connections accepted any NAS host key, the server held the NAS admin password, and every editor had a full shell on the NAS.
- What the product must do: Admin connections pin the NAS host key and refuse a change, the server holds only a scoped NAS key, and editors' NAS accounts transfer files only.
- Kind: 3

## Group 16

### BRO-003 [broll / Givens: browsers, cameras, files and Resolve]: Resolve refused every 29.97 preview after a camera's timecode was rewritten.
- What was going on: A colon in a file's timecode track is genuine non-drop-frame; Sony's own metadata colon is read as drop-frame; only files with no timecode track need guessing.
- What the product must do: Timecode from a file's timecode track is kept as written; only a file with none gets its drop-frame form decided from its frame rate.
- Kind: 1a

### PRX-004 [proxies-and-file-moves / What Resolve accepts as a proxy]: Sony footage at 29.97 or 59.94 got proxies Resolve refused on drop-frame form.
- What was going on: Sony metadata prints drop-frame timecode in colon (non-drop) form; same digits in the two forms are different frames, and a rewrite can silently flip a file's drop-frame flag.
- What the product must do: A proxy's timecode names the same frame in the same drop-frame form Resolve reads from the original, verified on the value and form written and by Resolve accepting it.
- Kind: 1a
- Check: Should Sony colon timecode at 29.97 and 59.94 always be written drop-frame, or only when Resolve reads the original as drop-frame?

## Group 17

### BRO-009 [broll / Givens: browsers, cameras, files and Resolve]: The page said the local app was not running when Chrome had blocked it.
- What was going on: Chrome's local-network permission can block a plain-http page from calling the app on this computer, and that looks identical to nothing listening.
- What the product must do: A page that cannot reach the local app never claims it is not running; it names both possibilities and offers a one-click self-test.
- Kind: 1a

### APP-107 [editor-app / Telling the editor what is wrong]: The browser said the app was not running when it was.
- What was going on: Chrome's local network permission can stop an http web page reaching an app on the same computer, which looks identical to the app being closed.
- What the product must do: When a page cannot reach the local app it says it could not reach it and offers a self-test, never asserting the app is not running.
- Kind: 1a

## Group 18

### BRO-010 [broll / Givens: browsers, cameras, files and Resolve]: A clip uploaded from a Mac was treated as having no original.
- What was going on: macOS spells accented and Chinese names decomposed; compared byte for byte with the NAS spelling, originals and proxies went unfound and editors pulled the heavy original instead.
- What the product must do: Name matching treats the Mac and NAS spellings of one name as equal, while every file is opened by the exact spelling on disk.
- Kind: 1a

### PRX-085 [proxies-and-file-moves / Names: letter case and Unicode]: Moved clips with accented names never relinked on a Mac.
- What was going on: macOS and Resolve on a Mac spell accented names decomposed, the NAS and Windows composed, so raw comparisons matched nothing and one project appeared twice.
- What the product must do: Every comparison of file or project names treats both Unicode spellings as equal, while disk operations use the exact bytes on disk.
- Kind: 1a

### SYN-066 [sync / Names]: A Mac spells accented file names differently, so held files looked missing forever.
- What was going on: macOS returns names decomposed (NFD), Windows and the NAS composed (NFC); 12 accented files showed owed for a day, and moves read as deletions. Chinese names have no decomposed form.
- What the product must do: Every comparison of a path from a Mac with one from elsewhere treats both spellings as equal, while files are opened, renamed or deleted by their exact bytes.
- Kind: 1a

### ALL-073 [whole-product / Windows, text and names]: Windows may spell its temporary folder as an old 8.3 short path.
- What was going on: On some Windows machines the temporary-folder path is a short 8.3 name, so a text comparison with full long names never matches.
- What the product must do: Every comparison of Windows paths treats the short and long spellings of one path as the same path.
- Kind: 1a

### YTD-072 [youtube / Choosing the destination and checking space]: A project with an accented name was reported missing.
- What was going on: The name came from a Mac, which spells accents decomposed; the NAS spells them composed, so an exact check missed a folder that existed.
- What the product must do: Every check that a project folder exists matches names regardless of accent spelling, and never blames a missing share when the folder is there.
- Kind: 3

## Group 19

### BRO-011 [broll / Givens: browsers, cameras, files and Resolve]: Changing a folder name's capitals made the whole folder be indexed again.
- What was going on: Windows drives and NAS shares treat "Youtube" and "YouTube" as one folder, but an exclusion rule compared letter case exactly.
- What the product must do: Path comparisons on these drives and shares ignore letter case, so a capitals-only rename changes nothing.
- Kind: 1a

### BRO-012 [broll / Givens: browsers, cameras, files and Resolve]: Two archive names differing only in case land in one folder.
- What was going on: Windows and macOS treat file names that differ only in letter case as the same name.
- What the product must do: Archive names are compared without case, and a new name matching an existing one apart from case is refused or renamed.
- Kind: 1a
- State: outcome not found

### PRX-086 [proxies-and-file-moves / Names: letter case and Unicode]: A Mac did not recognise its own moved file spelled with other capitals.
- What was going on: Windows and Mac volumes ignore letter case by default, though a Mac volume can be case-sensitive; Linux and the NAS always distinguish case.
- What the product must do: Path comparisons follow the real volume's case rule, and file operations use the path's own spelling.
- Kind: 1a

### SYN-065 [sync / Names]: The NAS and some Mac volumes treat letter case as different names.
- What was going on: "youtube" and "Youtube" can both exist on the NAS, while Windows ignores case; looking a project up by a lower-cased spelling found nothing on a case-sensitive volume.
- What the product must do: Names may be compared ignoring case, but a folder is looked up and opened by its exact spelling on disk.
- Kind: 1a

## Group 20

### BRO-074 [broll / The clip player]: Pressing Enter on a focused button could append a clip to the live timeline.
- What was going on: The clip view captured Enter and Space for its own shortcut, even on focused buttons and in drawers open over it.
- What the product must do: Keyboard shortcuts never override a focused button or field, and nothing reaches Resolve without the editor meaning to send it.
- Kind: 3

### APP-100 [editor-app / Windows, dialogs and notifications]: Pressing Enter on a focused Cancel button ran the window's main action.
- What was going on: The app's buttons took no keyboard focus, so Enter always triggered the window's default.
- What the product must do: Every button can be reached by keyboard and shows focus, and Enter acts on the focused button.
- Kind: 3

## Group 21

### BRO-079 [broll / Previews made for the archive]: An editing proxy a few frames short failed the whole clip.
- What was going on: Resolve refuses proxies even 1 to 18 frames short, but a failed optional editing proxy also discarded the preview, stills and original upload.
- What the product must do: An editing proxy failing its exact frame check is dropped with a stated reason, and the clip still goes live with its preview.
- Kind: 3

### PRX-010 [proxies-and-file-moves / What Resolve accepts as a proxy]: "Sync stuck" was really Resolve refusing proxies a few frames short.
- What was going on: Every file had synced, but 7 proxies were 1 to 18 frames short and another covered 1,238 of 3,741 seconds, so Resolve would not link them.
- What the product must do: A proxy whose frame count differs from its original is named to the editor and on the dashboard as a proxy fault, not a sync stall, and remade.
- Kind: 3
- State: outcome not found

## Group 22

### BRO-081 [broll / Previews made for the archive]: Copying 85 GB of previews to the NAS over 10GbE took far longer than minutes.
- What was going on: The owner expected about 85 GB over a 10 gigabit link to take a few minutes; many small preview files ran much longer.
- What the product must do: A bulk copy to the NAS shows progress and speed, and moves many small files at close to the link's capacity.
- Kind: 3
- State: outcome not found

### SRT-077 [footage-sorter-and-camera-cards / Drives, speed and interruptions]: A long copy to the NAS ran unsteadily, then stopped moving unnoticed.
- What was going on: The owner: a trip's copy "has stopped moving", ran "much slower than this link should allow" on 10 Gb, and a card copy's speed was "so unstable".
- What the product must do: A long copy runs steadily near the link's capacity, shows live speed, says when it stops moving, and shows where any slowdown comes from.
- Kind: 3
- State: outcome not found

## Group 23

### BRO-088 [broll / Bringing new footage in]: An upload the server refused for good stayed "uploading" for ever.
- What was going on: Only two server answers were handled; every other refusal, permanent ones included, was re-sent silently with no attempt count.
- What the product must do: Every upload answer is classed as done, retry later with a limit, or failed for good with the server's own sentence, shown to the editor and retryable.
- Kind: 3

### YTD-074 [youtube / Choosing the destination and checking space]: Pasted links skipped the space check, and the refusal named a hidden button.
- What was going on: Pasted-link jobs and server fallbacks got no free-space check, so a full NAS filled clip by clip, and the "no room" message named a retry button hidden in that state.
- What the product must do: Every way a download starts, on any computer, checks space before fetching and refuses once, in one sentence naming a button on screen, leaving clips retryable.
- Kind: 3

## Group 24

### BRO-097 [broll / Bringing new footage in]: "Try the failed clips again" said "12 clips queued" while nothing ran.
- What was going on: The retry named items and the staged drop wrongly, so the editor's computer answered zero retried or failed every clip in seconds with the files still staged.
- What the product must do: A retry reruns failed clips from the files this computer staged, refuses with a reason if it cannot tell which drop, and says running only once a computer took it.
- Kind: 3

### MUS-018 [music / Imports across computers]: A thirty-second NAS blip failed every track of an album drop for good.
- What was going on: The library's "try again later" answers (share not mounted, two tracks racing for one name) were treated as final, retried back to back, with no retry button.
- What the product must do: A retry-later answer is retried with pauses for about twenty minutes before failing with the library's words, and a failed track can be retried from the page.
- Kind: 3

## Group 25

### BRO-098 [broll / Bringing new footage in]: Retrying failed items took a batch from the computer still working on it.
- What was going on: Retry reset a running batch to queued, so the working computer was cut off and the editor's second computer could claim the same clips.
- What the product must do: A retry is refused while a computer still holds the batch, naming that computer; an abandoned batch can still be retried.
- Kind: 3

### MUS-022 [music / Imports across computers]: Another computer's retry or late cancel took an import from the computer running it.
- What was going on: Retry reset a batch still held by a working computer, letting a second one index the same tracks, and a stale computer's cancel deleted a track mid-upload.
- What the product must do: Only the computer holding an import can cancel or release it, retry is refused while another holds it, naming it, and an abandoned import stays retryable.
- Kind: 3

## Group 26

### BRO-106 [broll / Sending a clip to Resolve]: Send to Resolve on a remote computer failed with "file not found".
- What was going on: Remote editors do not hold the archive or music library; the owner: sync it down to the matching path under the local tree.
- What the product must do: Sending a clip or track the computer lacks fetches just it to the matching local path with visible progress, then imports it, b-roll into an archive bin.
- Kind: 2

### MUS-050 [music / Sending to Resolve]: Sending a track to Resolve failed when the track was not on the computer.
- What was going on: The music library is not synced to editors, so sending a track gave "file not found" instead of fetching it.
- What the product must do: Sending a track not yet on the computer fetches it first, showing progress, then places it in Resolve.
- Kind: 3

## Group 27

### BRO-111 [broll / Sending a clip to Resolve]: Send to Resolve offers both append and place on top.
- What was going on: Sending could only append; the owner asked for "both 'append' and 'place on top'".
- What the product must do: The person chooses between appending the clip at the timeline's end and placing it on a track above, at the playhead.
- Kind: 2
- State: outcome not found

### CRX-016 [cards-to-resolve-and-exports / Placing, deleting and linking clips in Resolve]: With no track named, Resolve's append follows the destination-track buttons.
- What was going on: With V1's destination toggle off nothing lands and no error comes back, a rollback done the same way restores nothing, and some audio-only positions place nothing.
- What the product must do: Every placement names its track and media type and counts only after its track and start are read back; missing picture or sound is reported by track.
- Kind: 1a

### CRX-017 [cards-to-resolve-and-exports / Placing, deleting and linking clips in Resolve]: Appending to a missing track reports success; a chosen track gets no linked audio.
- What was going on: An append at a track index that does not exist returns an item and places nothing; an append to a chosen track places picture without linked sound.
- What the product must do: A cut placed on an upper track lands on a track that exists, with picture and sound both placed and linked, as a hand edit would.
- Kind: 1a

### RSV-110 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: Resolve's append can report success while placing nothing.
- What was going on: Appending without naming a track follows the timeline's destination-track buttons; with the video destination off nothing lands, no error returns, and a returned item proves nothing.
- What the product must do: After adding a clip to a timeline, the product confirms it is there at the expected start, without pinning it to one media type and losing its sound.
- Kind: 1a

## Group 28

### BRO-119 [broll / Previews standing in for originals]: A drive unplugged for one check erased the record of stand-ins.
- What was going on: A pulled sync drive, unmapped share or NAS reboot made every file unreadable at once, and the cleanup read that as deletion.
- What the product must do: A cleanup that cannot see the folder tree does nothing, and an unreadable file is never treated as deleted.
- Kind: 3

### ALL-051 [whole-product / Could not check, refusals and nothing silent]: "Could not read" was acted on as "nothing there".
- What was going on: An unplugged drive, unmapped share or one failed NAS listing erased records, zeroed counts, excluded a project for good, or labelled stale data live.
- What the product must do: An unreadable source is never empty: records survive, counts keep their last value marked stale, the safe side is taken, and the next good read recovers.
- Kind: 3

## Group 29

### BRO-127 [broll / Client folders and links]: A distant client had to download terabytes without joining the private network.
- What was going on: The owner: "several terabytes for a client to download it once", 500 Mbps at both ends, "I don't want them to have to join our [private network]."
- What the product must do: A client link downloads chosen folders read-only and resumable straight from the NAS near line speed, needing no client software or private-network access.
- Kind: 2

### APP-021 [editor-app / Installing and setting up]: A new editor could not download the installer before joining the private network.
- What was going on: The installer was served only behind the private network it existed to join, and setup asked for the address it had just come from.
- What the product must do: A new editor downloads the installer without being on the private network, and setup never asks for a value it already has.
- Kind: 3
- State: outcome not found

## Group 30

### BRO-136 [broll / Replacing the search index]: Publishing a rebuilt search index deleted the clips added since.
- What was going on: Clips and tracks added by editors exist only in the live index; swapping in a rebuilt copy dropped them and the import queue, a size check passed it, and success was reported.
- What the product must do: Replacing a search index keeps every item and queue entry added since the rebuild began, or refuses before anything changes, and a failed merge is reported naming the recovery.
- Kind: 3

### MUS-031 [music / Keeping the library's data whole]: Publishing a fresh music index wiped tracks the live library had queued.
- What was going on: Tracks added on the live library were overwritten when a copy worked on elsewhere was copied or published back over it.
- What the product must do: Results worked on elsewhere merge in track by track, only where the file is unchanged, and never discard tracks the live library gained meanwhile; otherwise the publish refuses.
- Kind: 3

## Group 31

### BRO-137 [broll / Replacing the search index]: A published index the running server could not read switched search off.
- What was going on: An index in a newer format disabled b-roll search; an older one under a newer server made every import fail until restart.
- What the product must do: Publishing an index whose format version differs from the running server's is refused in either direction, naming what to do first.
- Kind: 3

### SRV-051 [server-install-and-running / Updates, restarts and rollbacks]: A search index published by a newer server was unreadable by an older one.
- What was going on: A new index format would break any older server version the server was rolled back to.
- What the product must do: An index is never published to a server that cannot read it, and a server rolled back past an index format still boots with that search marked off.
- Kind: 3

## Group 32

### BRD-018 [cards-board / Working the board by hand]: Set-aside cards are grouped under the theme they would have belonged to.
- What was going on: The owner: weak material goes in "a staged -- category which is named after the MOST RELEVANT category"; a group named "Staged-- China actually scared" belongs to that theme.
- What the product must do: Each set-aside card sits in a set-aside group named after its most relevant theme, and arrives on the cutting editor's shelf under that name.
- Kind: 2

### CE1-058 [cards-editor / Notes and the staged shelf]: Staged cards can be filed into categories the editor names.
- What was going on: The owner: "right click > add to category > select existing categories or add a new one", with a strip filtering the shelf; a planning board's groups come across.
- What the product must do: Categories keep document order, never alphabetical; a card sits in one; deleting a category returns its cards to the plain shelf; a board made into a cut brings its groups.
- Kind: 2

## Group 33

### BRD-045 [cards-board / Montages]: A montage draws only on downloaded news and archive footage.
- What was going on: The owner: "Montages are always and ONLY downloaded material - newsreaders, coverage, etc."; an early montage was to use reporters' voiceover and residents' soundbites.
- What the product must do: A montage's pool holds only downloaded news and archive clips, never the film's own interviews or their transcripts.
- Kind: 2
- Check: Are studio anchors' link lines still excluded? An early montage ruling excluded them, later rulings favour newsreader delivery.

### CFI-110 [cards-footage-in / Montages]: A montage uses only downloaded material, never the studio's own interviews.
- What was going on: The owner's rule: a montage is news, coverage or archive the product downloaded, with credits, never the studio's interview material.
- What the product must do: Building a montage refuses interview footage and any clip without a credit record.
- Kind: 2
- Move to: cards-editor

## Group 34

### BRD-049 [cards-board / Montages]: A montage's assistant conversation continues instead of starting over.
- What was going on: Each describe, revise or search re-sent the whole material as a fresh request, costing minutes and losing context: "I don't want it to reset context every time".
- What the product must do: Requests about one montage continue one remembered conversation, and a lost conversation is reported, not silently restarted.
- Kind: 2

### CE2-090 [cards-editor / Shortening and the assistant]: The assistant keeps one warm conversation while the owner works.
- What was going on: The owner: "does the session stay active ... so the cached content remains cached? I don't want it to reset context every time"; search covers one or all transcripts.
- What the product must do: Follow-ups on one cut or montage share one conversation, a reload or second browser joins it, and a forced restart says so on screen and re-sends the material.
- Kind: 2

## Group 35

### CE1-002 [cards-editor / Chinese text and matching]: A Chinese search finds the same words in Simplified, Traditional or pinyin.
- What was going on: The owner: "the simp>trad agnostic search which we used to have disappeared"; the matching was missing on one install and search silently went literal.
- What the product must do: Transcript search matches Simplified, Traditional and pinyin on every install, and if that matching is unavailable the page says so instead of quietly matching less.
- Kind: 2

### SRT-174 [footage-sorter-and-camera-cards / Archive search]: An English search must find Chinese names, and the reverse.
- What was going on: Folders, people and events mix Traditional Chinese and English: "typhoon" should find 颱風災後, 台灣 match 台湾, "zhang" find 張; two-character words like 颱風 are common.
- What the product must do: Name searches match across Traditional and Simplified, English, Chinese and pinyin, any two-character query finds every name containing it, and corrected translations are kept.
- Kind: 2
- State: still open

## Group 36

### CE1-003 [cards-editor / Chinese text and matching]: An edit failed because the selection was Simplified and the timed words Traditional.
- What was going on: A transcript export was in Simplified characters while the timed words had been converted to Traditional, so the edit "did not go through".
- What the product must do: Any matching of Mandarin text against timed words treats the Simplified and Traditional forms of a character as equal.
- Kind: 3

### CFI-069 [cards-footage-in / Chinese script]: Mandarin text reads as Taiwan writes it, in Traditional characters with 台.
- What was going on: The owner: "we want 滑鼠/影片"; the house style is Taiwan phrasing and 台灣 with 台, while speech-to-text emits Simplified and standard conversion turns 台 into 臺.
- What the product must do: Every Mandarin transcript, word, cue and card is Traditional with Taiwan phrasing and 台, identically in search; text in another language is never converted.
- Kind: 2

## Group 37

### CE1-004 [cards-editor / Search and the transcript panel]: Search hits show the paragraph itself, never the assistant's retyped copy.
- What was going on: Answers repeated each passage plus its neighbours, about 8,000 characters and 139 s a turn; the owner: "the result itself is enough"; one-person searches read every transcript.
- What the product must do: The assistant returns only paragraph references and reasons; the page shows each matched paragraph from the transcript, 5 to 50 hits as chosen; a one-person search reads only theirs.
- Kind: 2

### CE2-092 [cards-editor / Shortening and the assistant]: Shortening used a massive amount of assistant capacity.
- What was going on: Each of about 50 calls per pass carried six transcripts and the whole cut, about 180,000 tokens; a one-person search read 322,000 characters for a 97,000-character transcript.
- What the product must do: Each call carries only what that step needs, so a one-section or one-person request costs in proportion to that material, and each pass logs its cost.
- Kind: 2

## Group 38

### CE1-014 [cards-editor / The English a cut shows]: A clip running over an interviewer's question showed no English at all.
- What was going on: Interview questions exist only in the timed speech, not in any transcript paragraph; the owner: "it should not refuse to show interview questions".
- What the product must do: Words no paragraph holds show as a gap in the original language, and the rest of the clip still shows its English, marked approximate.
- Kind: 3

### CFI-074 [cards-footage-in / The transcript and its English]: A transcript reads as meaning-based paragraphs with questions marked and full English.
- What was going on: The owner wants paragraphs by meaning, the interviewer's question as a heading, each paragraph translated "NATURALLY and COMPLETELY", and a reference per paragraph.
- What the product must do: Each paragraph carries the question it answers, its verbatim original, its full natural English, and a reference that survives edits and renames.
- Kind: 2

## Group 39

### CE1-015 [cards-editor / The English a cut shows]: A re-cut card showed its paragraph's whole English, which read as clips shifted.
- What was going on: Split, trimmed or extended cards kept the parent paragraph's English or English matched by text; the owner read the wrong line as clips "shifted by seconds".
- What the product must do: A cut's English line translates exactly its own span, shows the original words until that exists, and adds nothing under speech already in English.
- Kind: 3

### CE3-065 [cards-editor / The English a cut shows]: A cut shows the transcript's own English for exactly the words it plays.
- What was going on: The owner: "The high quality english already exists so why doesn't it just load it in", and "you adjust a clip and it just pulls out the relevant translation section".
- What the product must do: Every cut and set-aside card, whole or trimmed, shows the transcript's own English for exactly the words it plays, never the whole paragraph's.
- Kind: 2

## Group 40

### CE1-022 [cards-editor / House style and the assistant]: The film reads as one conversation between people who never met.
- What was going on: The owner: people answering each other "'accidentally' is a core part of my style ... one large conversation"; suspense by withholding, partial sentences when tenser, splices highlighted.
- What the product must do: Assisted ordering and cutting see cards in cut order and choose each as a reply to the one before; the house style is the owner's to edit per series.
- Kind: 2

### CE3-062 [cards-editor / Shortening and the edit chat]: The assistant must never work from an outdated copy of the transcripts.
- What was going on: A conversation kept the transcripts and house style it opened with, so a paragraph that had since moved named the wrong words.
- What the product must do: When transcripts or the house style change, the next request works from the new ones and says which of the two changed.
- Kind: 3

## Group 41

### CE1-037 [cards-editor / Editing: selecting, deleting, inserting]: A deleted cut moves to the staged shelf under the section it came from.
- What was going on: The owner: "when you delete it moves the clip into the staged section for the section you're currently in ... it disappears from the lane and cards but goes to staged".
- What the product must do: A deleted cut leaves the cards and lane and appears on the staged shelf, labelled with its section, keeping its words, English, colour and note, ready to put back.
- Kind: 2

### CFI-081 [cards-footage-in / The transcript and its English]: Staged cards must show English like cut cards do.
- What was going on: The owner: "the staged section shows English translations too".
- What the product must do: Every card, staged or cut, shows the English for its words.
- Kind: 2

### CRX-088 [cards-to-resolve-and-exports / Exports]: The text export holds each card in its spoken language only.
- What was going on: The owner asked for the cards as plain text and as a Markdown document with no English for Mandarin cards.
- What the product must do: The cards export as plain text and as Markdown in timeline order, each card in its spoken language only, without translations.
- Kind: 2

## Group 42

### CE1-041 [cards-editor / Editing: selecting, deleting, inserting]: Next and previous edit stopped short of or past the cut point after a gap.
- What was going on: Cut points were counted without gaps while the playhead counted them, so every jump after one 50-frame gap was 50 frames off.
- What the product must do: Next and previous edit land exactly on the cut point, before and after gaps, in both directions, at 25 and 29.97 fps.
- Kind: 3

### CRX-005 [cards-to-resolve-and-exports / Frames, frame rates and timecode]: Mixed-rate clips land in Resolve at a length Resolve decides.
- What was going on: Resolve was seen rate-conforming a 24 fps clip into 29.97, laying off-rate source frames one to one (a gap after each), and sizing cuts so they overwrote each other.
- What the product must do: Each cut starts at the previous item's read-back end, with no gaps or overlaps, and its placed length matches the clip's real rate within 0.04 seconds.
- Kind: 1a
- State: still open
- Check: Does Resolve rate-conform mixed-rate clips or lay them frame for frame, and does a project setting decide which?

## Group 43

### CE1-046 [cards-editor / Editing: selecting, deleting, inserting]: A clip name with square brackets broke the cut list.
- What was going on: Downloaded YouTube clips carry their video id in square brackets, and a line break in a speaker name was read back as a new cut.
- What the product must do: Any punctuation or line break in a name or reference survives save and reload unchanged, and no supplied text can create, remove or change a cut.
- Kind: 3

### YTD-049 [youtube / File names and what a file carries]: Square brackets in a file name read as wildcards in Windows' scripting shell.
- What was going on: Downloaded files carry the YouTube id in [ ], and Windows' own scripting shell treats [ ] in a path as wildcards, so an existence test on such a name answers false.
- What the product must do: Names containing [ ] are found, copied and checked as literal names everywhere.
- Kind: 1a

## Group 44

### CE1-049 [cards-editor / Editing: selecting, deleting, inserting]: A file dropped into a browser page gives its name and size, never its path.
- What was going on: Browsers hand a page only a dropped file's name and size, so a clip dragged in must be found among the episode's files.
- What the product must do: Dropped media is found by name and size inside the episode, and the page says which files were not found or still lack a transcript or proxy.
- Kind: 1a

### CFI-100 [cards-footage-in / Footage files and files made from them]: A file dropped on a web page gives its name and bytes, never its path.
- What was going on: Browsers hand a dropped file's name, size and contents to the page but not its place on disk, and uploading multi-gigabyte video through a page is impractical.
- What the product must do: Dropped media is found on the NAS by name and size; if it is not there, the person is told to put it there and drop it again.
- Kind: 1a

## Group 45

### CE1-066 [cards-editor / The cut list, undo and saving]: One cut list saved from two places at once can lose one side's change.
- What was going on: The browser editor and a laptop app edited the same cut list; both merged this time, but nothing stopped two writers overwriting each other.
- What the product must do: When one cut list is saved from two places at once, both changes are kept or the second is refused, with the conflict shown to both people.
- Kind: 3
- State: still open

### CE3-076 [cards-editor / Working offline and on several devices]: Two writers of the same file erased each other's work.
- What was going on: Two machines each saved a shared file whole, wiping the other's additions; the cut file can also be edited by hand.
- What the product must do: Shared files are merged on save, and a write that finds the file changed underneath it refuses rather than overwrites.
- Kind: 3

## Group 46

### CE1-068 [cards-editor / Edit speed and answering the editor]: Every edit must feel instant, a split included.
- What was going on: Edits waited for a slow confirmation and greyed the list: over 2 s, then 500-600 ms per edit from the phone; a split alone waited a 300-700 ms round trip.
- What the product must do: On a 433-cut project every edit, split included, is drawn within about 100 ms and saved behind it, greying nothing; a refusal takes it back with the reason; selection survives undo.
- Kind: 2

### CE2-134 [cards-editor / Several people and devices]: An edit took 709 ms to confirm though applied in 37 ms.
- What was going on: Owner wanted edits to "feel instant"; over a 100 ms one-way remote path, two full requests on fresh connections cost 637 of the 709 ms.
- What the product must do: An edit is confirmed by the answer to the edit itself, in one round trip, without refetching the whole cut.
- Kind: 3
- State: outcome not found

## Group 47

### CE1-085 [cards-editor / Playback and audio]: Audio fades drawn on the lane must be heard as drawn.
- What was going on: The owner ruled fades audio only and linear in gain, then: "make audio fades in the lane actually play, not just be visual".
- What the product must do: The lane and scrubbing play each fade as drawn at every rate, overlapping ends multiplied, with no click; there are no video fades; the transcript player never fades.
- Kind: 2

### CE1-086 [cards-editor / Playback and audio]: Fade handles on cuts reach Resolve as real audio fades.
- What was going on: The owner asked for Resolve-style fade handles on cuts and ruled them audio only.
- What the product must do: A cut's audio fade handles arrive in Resolve as real audio fades, and no video fade is ever written.
- Kind: 2
- Move to: cards-to-resolve-and-exports

### CRX-041 [cards-to-resolve-and-exports / Undo, markers, titles, fades and properties]: Fade handles are audio only, heard in the browser and exact in Resolve.
- What was going on: The owner: "timeline cards only needs audio fades, not video fades", conforming "to resolve accurately", and fades must "actually play, not just be visual".
- What the product must do: Cuts carry audio fade-in and fade-out handles that play as drawn in the browser and arrive in Resolve at the same lengths; the picture is never faded.
- Kind: 2

## Group 48

### CE1-096 [cards-editor / Lane clicks and keys]: In Chrome on Windows a lone Alt press hands the keyboard to Chrome's menu.
- What was going on: After Alt was pressed and released alone, as after Alt plus wheel, click or drag, the next Space opened Chrome's three-dot menu instead of playing.
- What the product must do: Space always plays or stops, straight after any Alt gesture, and never activates a browser menu or a focused button.
- Kind: 1a

### CE2-001 [cards-editor / The lane: clicking, trimming and dragging]: The lane must handle like Resolve's own timeline.
- What was going on: The owner asked for Alt plus wheel to zoom "to match resolve", centred waveforms, the playhead following a ripple trim, and no momentum when panning.
- What the product must do: The lane uses the editor's own Resolve keyboard preset (Resolve's defaults otherwise), Alt+wheel zooms, ripple trims carry the playhead, waveforms sit centred, and panning stops with the mouse.
- Kind: 2

## Group 49

### CE1-106 [cards-editor / Game controller]: The controller's landing marker shows only while the left stick is held in.
- What was going on: The owner: "make it so the chevron marker only appears when you press down L3 also, it's distracting".
- What the product must do: The centre landing marker appears only while the left stick is pressed, can be aimed by panning, and the head lands there on release.
- Kind: 2

### CE3-088 [cards-editor / Phone and game controller]: Controller zoom keeps the view's centre; holding L3 aims a playhead jump.
- What was going on: The owner wanted zoom not tied to the playhead, a jump to "whatever I'm looking at", and the marker shown only while L3 is held: "it's distracting".
- What the product must do: Controller zoom keeps the view's centre; holding L3 shows the centre marker, panning moves it, release moves the playhead there; nothing shows otherwise.
- Kind: 2

## Group 50

### CE1-110 [cards-editor / Game controller]: The controller drives the transcript like the timeline.
- What was going on: The owner: "move the playhead with right stick, then hold lt and move right stick to make selection", then a button inserts after the selected card.
- What the product must do: The pad acts on the focused pane; in the transcript the right stick steps word by word, LT plus stick selects, and LT plus X inserts after the selected card.
- Kind: 2
- State: fixed, never shipped

### CE2-163 [cards-editor / Phones, installing and the controller]: The controller drives the transcript with the lane's own buttons.
- What was going on: Owner: "keep the transcript controls as similar as possible to the lane controls so I dont have to memorise a new set of mappings".
- What the product must do: Every button does the same job on the transcript as on the lane, applied to text, a right-stick playhead included, and one button switches lane and transcript.
- Kind: 2

## Group 51

### CE1-119 [cards-editor / Panels and layout]: On desktop the transcript opens beside the cards, never over them.
- What was going on: The owner preferred the page "split when you open" the transcript, not a panel floating over the cards; on a phone the panel is a full-screen pane.
- What the product must do: On desktop an opened side panel sits beside the cards, which reflow, and never covers them; on a phone it takes the screen and has its own close.
- Kind: 2

### CE2-075 [cards-editor / Search and the transcript panel]: Double-clicking a card opens its transcript beside the cards.
- What was going on: The owner wanted the card's transcript in a right-hand panel pushing the cards left, together filling the screen, searchable and switchable.
- What the product must do: Double-clicking a card opens its full transcript at that passage beside the cards; it can be searched, closed, and switched to any episode transcript.
- Kind: 2

## Group 52

### CE1-131 [cards-editor / Opening episodes, restarts and Resolve]: After every server restart the assistant showed as unavailable.
- What was going on: The assistant's sign-in state lived only in memory, and the reason showed only in a hover tooltip, which a phone cannot show.
- What the product must do: A signed-in assistant shows available straight after a restart, and any reason a feature is unavailable is printed on screen, never only in a tooltip.
- Kind: 3

### SRV-059 [server-install-and-running / Updates, restarts and rollbacks]: The assistant read as unavailable after every server restart until someone clicked Test.
- What was going on: Whether the assistant was signed in was remembered only in memory, so each restart forgot it though the sign-in was still saved.
- What the product must do: After a restart a saved sign-in reads as signed in without a manual test, while a sign-in that just failed or was signed out still wins.
- Kind: 3

## Group 53

### CE1-134 [cards-editor / Offline and several devices]: An installed offline worker keeps serving its old page over moved addresses.
- What was going on: An installed worker controls every address under its scope, so after the page moved it served the old page; a scope of "/" claimed the whole site.
- What the product must do: When pages move, the old worker is switched off for everyone without losing unsent edits, and no worker claims more than its own section.
- Kind: 1a

### CE1-135 [cards-editor / Offline and several devices]: An installable editor under a sub-path claimed every page of the site.
- What was going on: Served under a sub-path of the dashboard, the editor declared the site root as its installed-app scope, handing every dashboard page to it.
- What the product must do: An editor installed from a sub-path claims only that sub-path, and every link it makes works under any prefix.
- Kind: 3

### CE2-138 [cards-editor / Phones, installing and the controller]: An installed app under a sub-path takes over the whole site.
- What was going on: An installed home-screen app whose scope is the site root claims every address on the host, including the dashboard it sits inside.
- What the product must do: An installed editor's scope and start address are its own folder, whether served at the root or under a sub-path.
- Kind: 1a

## Group 54

### CE1-139 [cards-editor / Offline and several devices]: One slow reply flipped the page onto an offline copy hundreds of revisions old.
- What was going on: The owner: "the lane and the order keep jumping around"; one slow poll switched to a copy at revision 231 while the live cut was at 507.
- What the product must do: Only a measured, repeated outage switches to offline; the copy follows every live state; an older revision never replaces a newer one; the screen says live or offline.
- Kind: 3

### CE2-116 [cards-editor / Working offline]: One slow answer switched the page to an old offline copy.
- What was going on: Any timed-out call, even a meaning search that honestly takes a minute, declared the server dead and swapped in a stale copy for 20 s, so edits looked reverted.
- What the product must do: Only a failed short reachability check switches to offline; long requests carry no deadline; the screen never shows an older state; a live or offline marker stays visible.
- Kind: 3

## Group 55

### CE2-002 [cards-editor / The lane: clicking, trimming and dragging]: The lane plays the whole cut and edits exactly like the cards.
- What was going on: The owner asked for a resizable strip under the cards, with waveforms and each clip's words wrapped inside, for listening through and editing.
- What the product must do: The lane plays every cut in order, wraps clip words with an ellipsis when cut off, can be resized, and any edit made there matches the same edit made on the cards.
- Kind: 2

### CE3-002 [cards-editor / The lane: how clips look and read]: Lane clip text wraps Chinese by character but never splits an English word.
- What was going on: The owner: "frequentl / y" must not happen; Chinese wraps per character, and waveforms fill the clip's height behind the text.
- What the product must do: No Latin word is broken across lines in a lane clip; an overlong one ends in an ellipsis; Chinese wraps per character.
- Kind: 2

## Group 56

### CE2-007 [cards-editor / The lane: clicking, trimming and dragging]: Dragging a clip edge outward must lengthen it and show the words added.
- What was going on: The owner: "I still can't drag a clip out"; an outward drag was refused, and extending showed nothing of "what words you're adding to the edit".
- What the product must do: Dragging an edge outward extends it from its source, showing live the new extent and words; it is refused only when the source has nothing left, with the reason.
- Kind: 2

### CE3-005 [cards-editor / The lane: how clips look and read]: Dragging a clip's edge shows the trimmed-off words faded.
- What was going on: The owner chose faded handle text so that extending a clip is "drag until the sentence ends".
- What the product must do: While dragging or hovering near a clip edge, the words beyond the edge show faded.
- Kind: 2

## Group 57

### CE2-040 [cards-editor / Colours]: Some of Resolve's clip colours are nearly invisible on a dark card.
- What was going on: Resolve's sixteen clip colours are fixed; Navy is nearly black and measures 2.35:1 against a dark card, invisible as a waveform on a dark row.
- What the product must do: Every Resolve clip colour, drawn on a dark surface, stays recognisable at 3:1 or better without altering the colour itself.
- Kind: 1a

### ALL-012 [whole-product / The look]: Resolve's dark clip colours vanish on a dark card.
- What was going on: Clip colours are Resolve's own sixteen; Navy measures only 2.59:1 against a dark card, so the swatch needs a ring to be seen.
- What the product must do: Clip colours are never changed, and every one of Resolve's sixteen stays at least 3:1 visible against whatever it sits on.
- Kind: 1a

## Group 58

### CE2-045 [cards-editor / Playback and audio]: A browser given a video file to play sound decodes the video too.
- What was going on: Chrome decodes the video track to reach the audio, contending for the decoder other tabs use, so the lane froze and YouTube stuttered; it also sends date-form range checks.
- What the product must do: The browser is only ever handed audio-only files for sound, and partial-file requests work with every validator form browsers send.
- Kind: 1a

### CE3-037 [cards-editor / Playback and audio]: Chrome resumes a partly played file with a dated range request.
- What was going on: Chrome resumes a partly played file by asking for a byte range conditioned on a date, not a tag; a server ignoring that form sent the whole file and playback froze.
- What the product must do: Audio the browser has partly played resumes instantly, whichever form of resume request the browser sends.
- Kind: 1a

## Group 59

### CE2-046 [cards-editor / Playback and audio]: Chrome puts an idle sound output to sleep, and Bluetooth adds delay.
- What was going on: After silence Chrome parks the output, so sound came half a second late; Bluetooth adds 150-250 ms, and muted video ran 0.1 s ahead.
- What the product must do: The playhead moves the instant Play is pressed after any seek, eases into sync with what is heard within half a second, and picture waits for the sound.
- Kind: 1a

### CE3-038 [cards-editor / Playback and audio]: Chrome lets an idle audio device sleep, so the first Play waits.
- What was going on: Chrome puts an idle audio output to sleep, and Play then waits for the device to wake.
- What the product must do: The first Play after a pause sounds without a wake-up delay.
- Kind: 1a

## Group 60

### CE2-060 [cards-editor / Playback and audio]: Resolve's scripting cannot set a clip's volume.
- What was going on: Per-cut gain set in the editor has no way into Resolve through scripting, because no clip-volume setter exists.
- What the product must do: Every send to Resolve states how many cuts' gains did not reach it, and names them.
- Kind: 1a

### CRX-038 [cards-to-resolve-and-exports / Undo, markers, titles, fades and properties]: Resolve's scripting cannot set fades, keyframes, transitions or clip volume.
- What was going on: Item properties cover only a static opacity, so one cut's 22 audio fades and its manual gains, and levelling heard in the preview, never reached Resolve.
- What the product must do: Every send and export carries fades, gain and levelling where it can, and names each one it dropped, with a count in words.
- Kind: 1a
- State: fixed, never shipped

### CRX-042 [cards-to-resolve-and-exports / Undo, markers, titles, fades and properties]: A per-cut gain was asked for but never reached Resolve.
- What was going on: The owner asked for per-cut gain; how Resolve stores a clip's volume was never confirmed, so a guessed level could put an unseen level into a timeline.
- What the product must do: A cut's gain reaches Resolve at the level set, proven by reading back a known level; until then every send says gain was not carried.
- Kind: 2
- State: still open

## Group 61

### CE2-065 [cards-editor / Media the browser gets]: New clips must be playable without waiting for someone to ask.
- What was going on: Small playback copies were made only when a clip was first played, so a fresh batch stayed unplayable for minutes and offline offered 2.9 GB of full recordings.
- What the product must do: Every clip's small playback copy is made automatically when it lands or the project opens, before anyone plays or downloads it.
- Kind: 2

### CFI-104 [cards-footage-in / Footage files and files made from them]: Most interviews had no small listening copy or waveform ready.
- What was going on: These were made only when a page asked, so a new project had them for just 2 interviews, and working offline offered 2.9 GB of full WAVs.
- What the product must do: Every clip's small listening copy and waveform are made as soon as its sound is final, before anyone opens the editor.
- Kind: 3

## Group 62

### CE2-076 [cards-editor / Search and the transcript panel]: The transcript list showed 4 of an episode's 40 transcripts.
- What was going on: The list held only transcripts the cards had already used, so after a start most were missing.
- What the product must do: The transcript list shows every transcript in the episode, whether opened before or not.
- Kind: 3

### CFI-099 [cards-footage-in / Running on its own, with a hand on every decision]: The editor found no transcripts in an episode's folder.
- What was going on: Pointed at one episode's folder, the editor read no transcripts at all, with no reason given.
- What the product must do: Opening an episode lists every transcript in it, or says which files it rejected and why.
- Kind: 3
- State: outcome not found

## Group 63

### CE2-079 [cards-editor / Search and the transcript panel]: Every transcript paragraph must have timing, or the panel goes dead.
- What was going on: Paragraphs were placed by exact text match against separately timed words; 80-90% missed, so click-to-play and the playhead silently stopped.
- What the product must do: When bringing the studio's existing transcripts in once, every paragraph gets timing, approximate where no exact match exists, so nothing is dropped silently.
- Kind: 3

### CFI-106 [cards-footage-in / Bringing the studio's existing transcripts in once]: Existing transcript paragraphs went dead when timed from a second transcription.
- What was going on: A second transcription of the same audio differs by a character or two per paragraph; 80 to 90% got no timing, and a one-character-off 31-character paragraph scored 0.732.
- What the product must do: On import, every paragraph of any length, hand-corrected ones included, gets timing even when its words differ slightly from the timed words, with honest confidence.
- Kind: 3

## Group 64

### CE2-086 [cards-editor / The English a cut shows]: A clip's English must cover exactly its words.
- What was going on: A clip ending at "president Lai" showed English running past it, another dropped "slaughter" though 殺戮 was in it, and 186 of 237 re-ordered clips showed none.
- What the product must do: Every clip shows the transcript's own English for exactly the words between its edges, for the whole episode, with no button needed.
- Kind: 2

### CFI-096 [cards-footage-in / Running on its own, with a hand on every decision]: A second speech-to-text pass rewrote clip words, so their English vanished.
- What was going on: Re-timing interviews with a fresh transcription brought different characters and words (他 heard as 它), and re-cutting 707 clips from it broke their English.
- What the product must do: New word timings only move a clip's edges; its words stay in the transcript's own wording and characters.
- Kind: 3

## Group 65

### CE2-124 [cards-editor / Working offline]: Unsent offline edits save themselves to a file, without nagging.
- What was going on: The only copy lived in browser storage; owner: "local copies should save to a directory automatically"; "Downloads on laptop is fine"; the first version prompted every minute.
- What the product must do: Unsent edits save within seconds, at most once a minute and always including the last, to one silently overwritten file, restorable without duplicating edits.
- Kind: 2

### CE3-069 [cards-editor / Working offline and on several devices]: The offline rescue copy asked to save a growing file every minute.
- What was going on: While offline, the browser opened a save prompt once a minute, each time a new file of 1 to 1.7 MB.
- What the product must do: The rescue copy of unsent edits interrupts at most once per ten minutes and, where the browser allows, quietly overwrites one file chosen once.
- Kind: 3

## Group 66

### CE2-131 [cards-editor / Several people and devices]: An editor working offline could be thrown out of their episode.
- What was going on: Presence was measured by server requests, so after 15 quiet minutes an offline editor looked gone, while an always-on computer kept its editor "in" for ever.
- What the product must do: Presence follows a person actually working, offline or on a sleeping phone; unsent work keeps an episode occupied; a closer is told who was last in and when.
- Kind: 3
- State: still open

### CRX-084 [cards-to-resolve-and-exports / Which computer is driving Resolve]: An editor's two computers could not work in two episodes at once.
- What was going on: Requests followed the person's last request on any device, so Resolve requests and their answers landed in different episodes and applied edits were reported lost.
- What the product must do: Each computer follows the episode open on that computer, and a request and its answer always reach the same episode.
- Kind: 3

## Group 67

### CE2-137 [cards-editor / Phones, installing and the controller]: A phone fetches an app's install files without the sign-in.
- What was going on: Chrome fetches a web app's manifest and icons without cookies; behind the login they redirected, so Install made a shortcut with an address bar.
- What the product must do: Install files and icons for every installable page load without sign-in, reveal nothing private, and the installed page opens full screen.
- Kind: 1a

### ALL-014 [whole-product / The look]: A phone installing a web app fetches its manifest and icon without signing in.
- What was going on: When a phone installs a web app it fetches the manifest and icon with no sign-in cookie, so a redirect to sign-in breaks installing.
- What the product must do: Every installable page's manifest, icon and offline script load without sign-in, while the pages and data behind them still require it.
- Kind: 1a

## Group 68

### CE2-145 [cards-editor / Phones, installing and the controller]: On Android a long press fires the same event as a right-click.
- What was going on: A long press meant to open a transcript or move a clip opened the right-click colour picker under the finger.
- What the product must do: Every touch gesture has exactly one meaning in each phone view, and nothing that means right-click is reachable by a long press.
- Kind: 1a

### CE3-087 [cards-editor / Phone and game controller]: Android's back gesture means "back to the cards" from every full-screen view.
- What was going on: Phone views had four different ways out.
- What the product must do: Back from any full-screen phone view returns to the cards without piling up history, and back from the cards leaves the page.
- Kind: 3

### ALL-027 [whole-product / The look]: Android's Back button left the page instead of returning to the list.
- What was going on: A phone layout shows one view at a time; without a history step, Android's Back leaves the page instead of returning to the main list.
- What the product must do: On a phone, leaving the main list for another view adds one history step, so Back returns to the list.
- Kind: 3

## Group 69

### CE2-149 [cards-editor / Phones, installing and the controller]: The editor apps update themselves from inside the app.
- What was going on: The owner: "make the app installable inside the app, without needing to get pushed over adb", on Windows and Android.
- What the product must do: Each app checks, downloads, verifies and installs its own update from its settings, keeping its settings and offline copies.
- Kind: 2

### DSH-134 [dashboard / Phones and the installed app]: Phone install and offline use need https and fail silently without it.
- What was going on: Offline workers, "Add to Home screen" and Android's app wrapper all need a secure address and do nothing without one; Android installs only from https.
- What the product must do: The dashboard is reachable on https wherever phones use it, every "open dashboard" link follows the site's published address, and a check names any failing install step.
- Kind: 1a

### SRT-063 [footage-sorter-and-camera-cards / Copying a card]: The card recorder page installs as an app on phones.
- What was going on: The owner: "make the card recorder also installable on ios and android".
- What the product must do: The card recorder installs to the home screen on iOS and Android and opens as an app.
- Kind: 2
- State: outcome not found

## Group 70

### CE2-S06 [cards-editor / Sealed]: The desktop wrapper's window ran at 20 frames a second.
- What was going on: The packaged desktop window spent about 49 ms presenting each frame, while the same page in a browser app window held 144.
- What the product must do: Measure frame rate in the window the editor actually uses, and ship whichever window kind meets the performance goal.
- Kind: 1b
- Tool: Electron

### APP-S15 [editor-app / Sealed]: The desktop app's own window ran the editor at 20 fps; the browser ran 144.
- What was going on: The same page ran 144 fps in Chrome but about 20 in the app shell's window, each frame stalling about 49 ms on hand-off to Windows; driver settings did not cure it.
- What the product must do: The desktop app shows the editor at the same frame rate as the plain browser on the same computer.
- Kind: 1b
- Tool: Electron

## Group 71

### CE3-092 [cards-editor / The page: header, warnings and redrawing]: The desktop editor is one whole window, like Resolve.
- What was going on: The owner: "like it's one whole window, somewhat like resolve": no system title bar, the header is the drag area.
- What the product must do: The desktop editor shows as one window whose header doubles as its title bar, with the window buttons in the editor's colours.
- Kind: 2
- State: fixed, never shipped

### APP-095 [editor-app / Windows, dialogs and notifications]: The desktop app is one dark window with no white title bar, like Resolve.
- What was going on: Owner: "make the windows header bar for the exe fit with the overall style, like it's one whole window, somewhat like resolve, without the white bar at the top".
- What the product must do: The desktop app's title bar is drawn in the product's own look, with no plain system bar above it.
- Kind: 2
- State: fixed, never shipped

## Group 72

### CE3-099 [cards-editor / The page: header, warnings and redrawing]: Inside the dashboard there was no way back from the editor.
- What was going on: When the editor ran within the dashboard, nothing on its page led back.
- What the product must do: The editor, when part of the dashboard, always shows a one-click way back to it.
- Kind: 3

### ALL-026 [whole-product / The look]: The owner: every app reached from the dashboard has a way back to it.
- What was going on: The dashboard linked to the footage sorter, but the sorter had no way back, on desktop or phone.
- What the product must do: Every app reached from the dashboard shows a link back to the dashboard on every page, on phone and desktop.
- Kind: 2

## Group 73

### CE3-100 [cards-editor / The page: header, warnings and redrawing]: One raw control character in page code kills the whole page in browsers.
- What was going on: A raw NUL byte in an inline script passes checks outside a browser, but the browser's HTML parser turns it into U+FFFD and the page's script dies at load.
- What the product must do: Page sources are checked for raw control characters, and the editor is tested loaded in a real Chrome and Safari before release.
- Kind: 1a

### ALL-013 [whole-product / The look]: One raw control character in a page script killed the whole page.
- What was going on: Browsers turn a raw NUL inside an inline script into a replacement character, so code that passed every non-browser check failed to compile and the page died.
- What the product must do: Page scripts carry no raw control characters other than tab, CR and LF, and every page change is run in a real browser before release.
- Kind: 1a

## Group 74

### CFI-013 [cards-footage-in / Frame rates]: Blackmagic cameras record true 30.000 or 24.000 fps; Sony records 29.97 or 23.976.
- What was going on: The Pyxis records true 24.000 beside an FX3 at 23.976; Resolve retimes a 30.000 clip onto 29.97 by time, so frames sit up to half a frame off.
- What the product must do: Mixed-rate angles are reported on arrival and stay in sync without drift, and a one-frame mismatch from a true-rate file is not called a broken build.
- Kind: 1a

### CRX-008 [cards-to-resolve-and-exports / Frames, frame rates and timecode]: A multicam's timecode restarts at 01:00:00:00 and its angles map frame for frame.
- What was going on: Building a multicam resets its timecode, and angles map frame for frame, even a true 24.000 angle in a 23.976 multicam, so matching by source timecode landed minutes off.
- What the product must do: Cuts are mapped onto a multicam frame for frame from each angle's own start, never by matching source timecode.
- Kind: 1a

### RSV-106 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: A multicam's angles map frame for frame from their starts, not by timecode.
- What was going on: Building a multicam resets its timecode to 01:00:00:00, and angles map frame for frame, even a true 24.000 angle in a 23.976 multicam, so timecode conform landed minutes off.
- What the product must do: Moving cuts between a camera clip and its multicam maps frames one to one from the angle's start, never by source timecode or real time.
- Kind: 1a

## Group 75

### CFI-014 [cards-footage-in / Frame rates]: Mixed frame rates and misread drop-frame timecode drift a multicam out of sync.
- What was going on: True 30 treated as 29.97 drifts 1.8 frames a minute; 29.97 drop-frame timecode read as non-drop drifts about 50 frames in 25 minutes.
- What the product must do: Every clip's frame rate is handled exactly, drop-frame timecode is decoded as drop-frame, and a mixed-rate shoot states what drift it costs.
- Kind: 1a

### CFI-018 [cards-footage-in / Facts about Resolve: rates, multicams, timecode]: Resolve clips keep the frame rate the project had when they were imported.
- What was going on: WAVs imported into a 24 fps project stay 24; positions counted in 29.97 timeline frames put 11 of 16 interviews 0.4 to 25 s out and stretched a timeline 401 s.
- What the product must do: Every position sent to Resolve is computed in that clip's own rate, and each build is read back in seconds and fails loudly beyond one frame.
- Kind: 1a

### CFI-019 [cards-footage-in / Facts about Resolve: rates, multicams, timecode]: Resolve refuses a scripted timeline rate, and a new project defaults to 24 fps.
- What was going on: Scripting refuses to set a timeline's own rate, and a project's rate can change only while it holds no timelines.
- What the product must do: Before any timeline is built, the project's rate is checked against the cameras and set while empty, or the build refuses with the reason.
- Kind: 1a

### CRX-012 [cards-to-resolve-and-exports / Frames, frame rates and timecode]: Interviews mix frame rates, such as 29.97 clips on a 25 fps timeline.
- What was going on: Clip and timeline rates often differ; a cut's source span is its timeline duration times clip rate over timeline rate, never one to one.
- What the product must do: Every source span is computed at the clip's own rate, and a mixed-rate build matches hand-computed frames exactly.
- Kind: 3

### RSV-111 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: Resolve projects start at 24 fps or at the first raw clip's rate.
- What was going on: New projects were 24 fps, or 30 after the first Blackmagic raw import; scripting refuses a timeline's own rate, and the project rate changes only while there are no timelines.
- What the product must do: Before anything is imported or built, the project's rate is checked against the footage (29.97 drop-frame here) and the person is stopped if it cannot be set.
- Kind: 1a

### RSV-112 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: Resolve counts an audio-only clip's frames in that clip's own rate.
- What was going on: Resolve gave recorder WAVs 24 fps; asking for 48,508 frames on a 29.97 timeline placed 60,574, making an angle timeline 401 s too long.
- What the product must do: Placing audio-only clips into a timeline converts frames using the clip's own rate and checks the timeline's length afterwards.
- Kind: 1a

## Group 76

### CFI-016 [cards-footage-in / Frame rates]: New material with no stated frame rate defaults to 29.97 drop-frame.
- What was going on: Every studio interview and timeline measured 29.97 drop-frame, and the owner set it as the default.
- What the product must do: Timelines and clips with no stated rate default to 29.97 drop-frame, and a rate a file states is always kept.
- Kind: 2

### CRX-010 [cards-to-resolve-and-exports / Frames, frame rates and timecode]: A sent timeline is butt-joined at a chosen rate, 29.97 drop-frame by default.
- What was going on: The owner rejected built timelines at the wrong rate and with gaps: "Default frame rate going forward should be 29.97"; all 74 studio timelines were 29.97 drop-frame.
- What the product must do: A send offers a rate (default 29.97 drop-frame), butt-joins cuts and first imports any clip the Resolve project lacks; a file stating another rate keeps it.
- Kind: 2
- Check: The same ruling asked for marker-free timelines, yet later rulings place section and gap-note markers: are markers wanted?

## Group 77

### CFI-022 [cards-footage-in / Facts about Resolve: rates, multicams, timecode]: Resolve's scripting cannot reach multicam angles or set a transcription language.
- What was going on: Scripting exposes no multicam angles, and setting the transcription language returns false for every value, so auto-detect picked English for Mandarin interviews.
- What the product must do: Nothing that prepares footage depends on these calls, and anything Resolve cannot do is done another way or reported, never silently skipped.
- Kind: 1a

### RSV-103 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: Resolve's scripting reports no file path and no angles for multicam clips.
- What was going on: A multicam answers "" for its file path and scripting shows nothing of its angles; on a 904-item multicam timeline scripting found 0-3 paths in 4-14 s, against 44 angle files really used.
- What the product must do: Every multicam and compound clip's source files are found from its angles, and a timeline of multicams never reads as having no media.
- Kind: 1a

## Group 78

### CFI-027 [cards-footage-in / Grouping clips and building the multicam]: A folder can hold someone else's interview, and one recording two interviews.
- What was going on: One person's folder held another's whole interview, a tape held a husband's then his wife's interview, and one interview came in two sessions three hours apart.
- What the product must do: Grouping shows who introduces themselves and when, and a person can move a file to another interviewee, split a recording at a time, or join sessions.
- Kind: 3

### SRT-144 [footage-sorter-and-camera-cards / Placing sound recordings]: Speakers who introduce their organisation, or say their name late, went unidentified.
- What was going on: An interviewee opening "大家好，我們是婦女新知基金會" was skipped, names came many minutes in, and a recording was credited to someone merely mentioned.
- What the product must do: Attribution uses the whole recording, handles "we are" introductions, never credits a name only mentioned, marks guesses, and reports recordings it cannot attribute.
- Kind: 3

## Group 79

### CFI-038 [cards-footage-in / Grouping clips and building the multicam]: Each interviewee's multicam wears that interviewee's colour from the plan.
- What was going on: The owner colours each interviewee's cards in the plan and wants their multicam clips in Resolve to carry the same colour from the start.
- What the product must do: Every interviewee's multicam clip shows that interviewee's plan colour in Resolve from the moment it is made.
- Kind: 2

### CRX-072 [cards-to-resolve-and-exports / Sending a cut to Resolve]: Clip colours set in the cards did not reach Resolve.
- What was going on: The owner wants clip colours set in the cards carried into the built timeline; on a montage they did not arrive.
- What the product must do: A colour set on a cut in the cards appears on that clip in the timeline Resolve receives.
- Kind: 3
- State: outcome not found

### CRX-096 [cards-to-resolve-and-exports / Titles and compound clips]: Compound clips should carry the name and colour of what they hold.
- What was going on: Resolve names new compound clips "Compound Clip 1, 2..."; the owner wants each named after its clip and coloured like that interviewee's multicam.
- What the product must do: A compound clip the product creates is named after the clip it wraps and takes the clip colour of the related interviewee's multicam.
- Kind: 2
- State: outcome not found
- Move to: resolve-on-the-editors-computer

## Group 80

### CFI-039 [cards-footage-in / Grouping clips and building the multicam]: Resolve's "Brown" clip colour is never used; "Chocolate" is the brown.
- What was going on: The owner ruled that the mustard-ochre "Brown" is never assigned to anything; the chocolate brown is fine.
- What the product must do: No colour the product assigns in Resolve or on cards is ever Resolve's "Brown".
- Kind: 2
- Move to: cards-to-resolve-and-exports

### RSV-125 [resolve-on-the-editors-computer / Bins, clip sorting and imports]: Resolve's clip colour names mislead, and the owner bans "Brown".
- What was going on: Resolve's "Brown" renders mustard ochre, which the owner never wants; "Chocolate" is the brown, "Pink" is pale and "Violet" is hot pink.
- What the product must do: No clip colour the product assigns or offers is "Brown", and colour pickers show swatches, not Resolve's names alone.
- Kind: 2

## Group 81

### CFI-101 [cards-footage-in / Footage files and files made from them]: A NAS share limits a file name to 255 bytes, not characters.
- What was going on: A Chinese character is 3 bytes, so a 244-byte news title plus a working suffix hit 256 and the audio was never made, though its waveform showed.
- What the product must do: Every name made from a title or source name fits 255 UTF-8 bytes, cut on a character boundary keeping the start, a hash and the id.
- Kind: 1a

### CFI-102 [cards-footage-in / Footage files and files made from them]: Windows refuses command lines longer than about 32,000 characters.
- What was going on: A folder of news clips with long CJK titles exceeded the 32,767-character limit (error 206) before any work began.
- What the product must do: Processing any number of long-named files on Windows never fails on command-line length, and partial batch results survive a crash.
- Kind: 1a

### ALL-074 [whole-product / Windows, text and names]: Windows caps a command line at 32,767 characters.
- What was going on: Long text passed as a command argument fails on Windows, at 8,191 characters through a batch file.
- What the product must do: Large text is never passed to another program as a command argument on Windows.
- Kind: 1a

### YTD-047 [youtube / File names and what a file carries]: Long Chinese titles overflow the 255-byte file name limit.
- What was going on: Windows and NAS file systems cap a name at 255 bytes and a Chinese character takes three, so long titles failed with "Invalid argument"; Windows also caps a command line near 32K characters.
- What the product must do: Every name the product writes, temporary ones included, is capped at 200 UTF-8 bytes keeping the video id, and long file lists never go on a command line.
- Kind: 1a

## Group 82

### CFI-103 [cards-footage-in / Footage files and files made from them]: A made file newer than its source can still be out of date.
- What was going on: A waveform made at an old rate was newer than its source, so "newer means done" kept the stale file forever.
- What the product must do: Whether a made file is current is judged by its content or format, not by its date alone.
- Kind: 3

### JOB-037 [fleet-jobs / Results that are complete and current]: A stale waveform newer than its footage was never remade.
- What was going on: A waveform in an old format is still newer than its source, so "newer than the source" refused every remake and discarded fresh ones.
- What the product must do: A derived file counts as made only if newer than its source and in the current format and settings, asked the same way before work and before publishing.
- Kind: 3

## Group 83

### CFI-105 [cards-footage-in / Footage files and files made from them]: Drawing a waveform held a whole decoded clip in memory.
- What was going on: Long interview clips decode to gigabytes of audio, and every waveform job kept the whole decode in memory at once.
- What the product must do: Waveforms for clips of any length are made in bounded memory, and several at once cannot exhaust the machine.
- Kind: 3
- State: fixed, never shipped

### SRV-117 [server-install-and-running / Health checks and alerts]: Server memory grew without limit as long clips arrived at once.
- What was going on: Each waveform held a whole decoded clip (307 MB for 64 minutes) with no limit on parallel clips, and the server process grew to about 2.6 GB.
- What the product must do: Opening an episode of many two-hour interviews with no waveforms yet keeps server memory under a fixed ceiling, and no single feature can exhaust it.
- Kind: 3
- State: fixed, never shipped

## Group 84

### CFI-S16 [cards-footage-in / Sealed]: The cloud speech-to-text writes Mandarin in Simplified characters.
- What was going on: Its Mandarin output is Simplified, so comparing it with the studio's Traditional text fails without conversion.
- What the product must do: Its transcripts are converted to Traditional before they are compared or shown.
- Kind: 1b
- Tool: Soniox

### SRT-S15 [footage-sorter-and-camera-cards / Sealed]: The paid speech-to-text writes Taiwanese Chinese in Simplified characters.
- What was going on: The paid service returned Simplified Chinese for Taiwanese speech, while the local engine and the studio's transcripts were Traditional.
- What the product must do: Output from the paid service is converted to the studio's script before it is stored, shown or compared.
- Kind: 1b
- Tool: Soniox

## Group 85

### CFI-S30 [cards-footage-in / Sealed]: An encoder picks its output format from the file name's extension.
- What was going on: A temporary name with an unknown extension fails or writes the wrong format.
- What the product must do: Every temporary output names its format explicitly, so the finished file is identical whatever it was called while being written.
- Kind: 1b
- Tool: ffmpeg (muxer chosen from output extension)

### JOB-S02 [fleet-jobs / Sealed]: A temporary output name broke the encoder.
- What was going on: The tool picks the format from the extension, so "name.m4a.partial" fails; .m4a, .mp4 and .ogg map to the formats ipod, mp4 and ogg.
- What the product must do: Any output written under a temporary name states its format explicitly, and the result is byte-identical to the normal command.
- Kind: 1b
- Tool: ffmpeg

### PRX-S02 [proxies-and-file-moves / Sealed]: An overnight run of 1,040 proxies produced none.
- What was going on: The encoder picks its output format from the file extension, and a temporary ".partial" name gave it none, so all 6,290 attempts failed at start.
- What the product must do: Every encode names its output format explicitly whatever the temporary file is called, and a failure records the encoder's first error lines.
- Kind: 1b
- Tool: ffmpeg

## Group 86

### CRX-002 [cards-to-resolve-and-exports / Frames, frame rates and timecode]: Resolve's scripted append sometimes places a clip one frame early.
- What was going on: Appending a clip through Resolve's scripting occasionally lands it one frame before the requested position.
- What the product must do: After every scripted placement the position is read back and corrected if it is off.
- Kind: 1a

### RSV-109 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: Resolve places scripted clips a frame early and reports odd source times.
- What was going on: An append asked for frame 1238 landed at 1237; the source start counts from the file's start timecode; and Resolve reported an empty frame count for one WAV.
- What the product must do: Every clip placed in Resolve by script is read back and re-laid once if it is off by a frame.
- Kind: 1a

## Group 87

### CRX-004 [cards-to-resolve-and-exports / Frames, frame rates and timecode]: Resolve's count of linked picture-sound pairs changed between sessions.
- What was going on: Reading the same timeline in different sessions gave 490, 242 and 238 linked pairs.
- What the product must do: Pairing a cut's picture with its sound never rests on one session's count of linked items.
- Kind: 1a

### RSV-114 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: Resolve's count of linked clips changes between sessions on identical timelines.
- What was going on: The same timeline, with byte-identical stored data, showed 490 of 490 clips linked, then 242, then 238.
- What the product must do: Resolve's scripted link count is never taken as proof that picture and sound are paired.
- Kind: 1a

## Group 88

### CRX-027 [cards-to-resolve-and-exports / Placing, deleting and linking clips in Resolve]: Exporting and re-importing a Resolve timeline damages multicam edits.
- What was going on: An FCP7 XML round trip unlinked half the pairs and lost every multicam angle, the subtitles and the grades; a .drt round trip left 304 one-way links and duplicated all 9 multicams.
- What the product must do: A multicam or graded timeline is never rebuilt by export and re-import, and any repaired timeline keeps every track, angle, link, colour, marker, subtitle and grade.
- Kind: 1a

### RSV-108 [resolve-on-the-editors-computer / Multicams, frame rates and timelines]: Rebuilding a damaged multicam timeline by export and reimport fails both ways.
- What was going on: An XML round trip lost multicam angles, subtitles and half the links; Resolve's own timeline export kept the bad links and imported duplicate angle timelines into the bin.
- What the product must do: A damaged multicam timeline is repaired inside Resolve (duplicate it and relink each pair), never by an export and import round trip, leaving no stray angle timelines.
- Kind: 1a

## Group 89

### CRX-047 [cards-to-resolve-and-exports / Talking to Resolve: restarts, dialogs and speed]: Every Resolve call returns nothing while a dialog box is open.
- What was going on: While a modal dialog is up (a message box, a transcription progress window, "Audio Output: Remote Audio not found"), scripting calls return nothing at once; only closing it helps.
- What the product must do: A call that returns nothing is treated as a possible blocking dialog and named to the editor, and an editor's own transcription is never cancelled.
- Kind: 1a
- State: outcome not found

### RSV-011 [resolve-on-the-editors-computer / Connecting to Resolve's scripting: launch, stalls and death]: Any open Resolve dialog makes its scripting answer nothing, for every program.
- What was going on: An "Audio Output: device not found" box (speaker unplugged, or "Remote Audio" after Remote Desktop) appears on project load; until clicked, calls return nothing and queued renders sit at Ready.
- What the product must do: Empty answers mean "Resolve cannot answer now", never missing data; nothing is written meanwhile, the person is told to check Resolve for an open box, and renders are confirmed started.
- Kind: 1a

### RSV-015 [resolve-on-the-editors-computer / Connecting to Resolve's scripting: launch, stalls and death]: Resolve's scripting goes dead while the Remote Desktop session is disconnected.
- What was going on: With the Windows session disconnected, load, save and page calls return nothing; one such Resolve stopped responding and crashed about 30 minutes later.
- What the product must do: A disconnected desktop session on the Resolve computer is detected and the person told to reconnect, instead of attempting Resolve work.
- Kind: 1a

## Group 90

### CRX-052 [cards-to-resolve-and-exports / Talking to Resolve: restarts, dialogs and speed]: Resolve never re-reads an open timeline whose stored data changes.
- What was going on: Changes written to the library for an open timeline are not seen until the project is closed and reopened.
- What the product must do: Any change made to a timeline outside Resolve closes it first and reopens it after, with the editor's work saved beforehand.
- Kind: 1a

### RSV-048 [resolve-on-the-editors-computer / Project libraries and projects]: Resolve can be open while refusing scripting, and its last save stays readable.
- What was going on: With scripting refusing, the timeline and transcripts as of Resolve's last save were still in the project library, so work could continue.
- What the product must do: With Resolve closed or refusing scripting, the editor still shows the timeline as of Resolve's last save and says plainly it is not live.
- Kind: 1a

## Group 91

### CRX-055 [cards-to-resolve-and-exports / Talking to Resolve: restarts, dialogs and speed]: Only one program may drive Resolve on a computer.
- What was going on: A second program driving Resolve on the same computer risks scripting for the whole session, and each failed start left another hidden connection running.
- What the product must do: Never more than one connection to Resolve per computer: a second is refused (an unreadable process list counts as one running), and a failed start leaves nothing running.
- Kind: 3

### RSV-026 [resolve-on-the-editors-computer / Connecting to Resolve's scripting: launch, stalls and death]: Two programs on one computer talking to Resolve endanger its scripting.
- What was going on: A second Resolve client on the same computer risks scripting for the whole session and queues behind or ahead of the first for Resolve's one-at-a-time answers.
- What the product must do: One program per computer talks to Resolve, holding it only during calls, never while computing; another found running is named and left alone, and "cannot tell" counts as running.
- Kind: 3

## Group 92

### CRX-058 [cards-to-resolve-and-exports / Sending a cut to Resolve]: Resolve files a new timeline in whatever bin the editor last clicked.
- What was going on: Resolve's scripted create-timeline puts the timeline in the currently selected media pool bin, wherever the editor happened to click last.
- What the product must do: The editor can choose the bin a built timeline goes into, the editor's selected bin is restored afterwards, and an unknown bin is refused before building.
- Kind: 1a

### RSV-120 [resolve-on-the-editors-computer / Bins, clip sorting and imports]: Resolve's scripted import files clips into whichever bin is currently selected.
- What was going on: Aiming background imports meant switching the current bin and back every 20-60 s, overwriting a bin the editor had just clicked.
- What the product must do: Background imports into Resolve never change which bin the editor has selected, even when the editor clicks mid-import.
- Kind: 1a

## Group 93

### DSH-003 [dashboard / Overview, menus and finding things]: A Projects page lists every project to open, manage, tick and untick.
- What was going on: The owner asked for "a new 'projects' page where you can see all the projects, click into them to manage them, tick them, untick them".
- What the product must do: One page lists all projects; opening one offers every action on that project, including ticking and unticking it for sync.
- Kind: 2
- State: still open

### DSH-035 [dashboard / Ticking and unticking]: Ticking for a person changed all their computers without saying so.
- What was going on: A person-level tick pulled a project to every computer they own, and unticking on one computer could remove it from the others.
- What the product must do: A tick or untick changes only the chosen computer; one covering several computers names each and asks first; a plan change can be undone exactly within an hour.
- Kind: 3

### DSH-061 [dashboard / Transfers and the queue]: The queue lists only ticked work waiting behind live transfers.
- What was going on: 737 files, 44 GB, from projects nobody had ticked showed as queued; the owner wants "files which are queued on the current sync job, but aren't yet syncing".
- What the product must do: The queue lists, per person and project, files from ticked projects waiting behind running transfers; unticking removes a project from every queue and "behind" mark at once.
- Kind: 2

### DSH-110 [dashboard / Settings and setup]: Undoing a settings change emptied lists instead of restoring them.
- What was going on: Undo restored blank instead of the default for settings never set, and its confirm quoted an older change then reverted the newest.
- What the product must do: Undoing a settings change restores exactly the earlier effective values, and its confirm names the change it will actually undo.
- Kind: 3

### RSV-143 [resolve-on-the-editors-computer / Fixing media: copying in, rehearsals and undo]: One fix needed several undos, and a repeat undo claimed success.
- What was going on: A long fix was recorded as several changes, one change had no record at all, and undoing one already undone reported success again.
- What the product must do: Each press is undone by one undo restoring the exact earlier state or saying it cannot, a repeat says it is already undone, and relinks re-check each clip's path just before.
- Kind: 3
- State: outcome not found

### SYN-003 [sync / What syncs where]: Nothing syncs until a project is ticked, and ticked projects go one at a time.
- What was going on: Everything was syncing at once; the owner wanted editors to tick or untick projects, nothing moving until ticked, and projects synced one after another.
- What the product must do: Nothing syncs to a computer until a project is ticked for it; unticking stops it; several ticked projects sync one at a time, in order.
- Kind: 2

### SYN-019 [sync / A plan belongs to a computer]: Changing one computer's plan changed the person's other computers too.
- What was going on: "Remove from this computer" sent a person-wide removal, an empty untick was widened to the whole person, and a computer's first own tick replaced every project it had inherited.
- What the product must do: Ticking, unticking or removing a project for one computer changes only that project on that computer; if nothing was removed it says so instead of widening.
- Kind: 3

## Group 94

### DSH-010 [dashboard / Overview, menus and finding things]: Builds on offer are listed currently served first, then the vendor's.
- What was going on: The owner: "the top should just be 'currently served' and then underneath it 'available from the vendor'", grouped by kind then platform.
- What the product must do: Where builds are listed, currently served ones come first, then the vendor's offer, then other held versions folded away, each grouped by kind then platform.
- Kind: 2

### REL-038 [releases-and-updates / Trying a build on one computer first]: The builds list must show the newest first and hide old versions.
- What was going on: Owner: newest at the top, "we should never show all the previous versions", builds served here before those offered by the vendor, by product then platform.
- What the product must do: Each product and platform shows its newest build first, older ones only in a rollback picker, one place updates everything, and only truly modified builds are marked so.
- Kind: 2
- State: outcome not found

## Group 95

### DSH-012 [dashboard / Each computer's state]: A computer with no projects ticked is fine, never an error.
- What was going on: The owner: "A computer having nothing ticked is FINE", repeated after quiet ones were still drawn amber or red or counted as expected to sync.
- What the product must do: A computer with nothing ticked leads with a neutral line and is never an error, warning, alert, blocked state, open issue or expected syncer, even when quiet.
- Kind: 2

### ALL-090 [whole-product / Could not check, refusals and nothing silent]: The owner: "A computer having nothing ticked is FINE."
- What was going on: The owner: "I've already made this clear in the past. A computer having nothing ticked is FINE"; it kept appearing as blocked, amber or an open issue.
- What the product must do: A computer with no projects ticked shows as normal on every surface: no error, warning, blocked reason, red or amber state, alert or notice; real faults keep theirs.
- Kind: 2

## Group 96

### DSH-014 [dashboard / Each computer's state]: A computer that syncs nothing by design was shown "sync engine down" for 28 days.
- What was going on: A wired computer works straight on the NAS and syncs nothing, yet its headline and chip judged it like an editing computer.
- What the product must do: A computer whose role syncs nothing never shows a sync fault, chip, headline or alert about syncing; an editor's computer still does.
- Kind: 3

### APP-080 [editor-app / The tray or menu-bar icon and its menu]: A wired computer that syncs nothing must show green unless something is wrong.
- What was going on: The owner's computer works straight off the NAS with sync off by design, yet showed amber and "sync engine not running" as a blocking problem for two days.
- What the product must do: A computer configured to sync nothing shows the healthy colour and never reports the missing sync as a problem; owner: "green unless there is an error".
- Kind: 2

### SYN-024 [sync / Wired or remote]: A computer wired to the NAS works straight off it and syncs nothing.
- What was going on: Owner: the studio base machine "does not need to pull proxies" and "doesn't need to sync anything locally at all"; it sat forever in a queue it could never clear.
- What the product must do: A wired computer downloads nothing, copies no project locally, never appears in the sync queue, shows healthy, and still reports what its Resolve sees.
- Kind: 2

## Group 97

### DSH-016 [dashboard / Each computer's state]: A computer that stopped reporting kept its green dot for a week.
- What was going on: A caught-up computer that went quiet was never "behind", so its last transfer states stayed frozen green.
- What the product must do: A computer with no report for 15 minutes shows amber, after 6 hours red, as not heard from with when it last reported, whatever it last said.
- Kind: 3

### SYN-086 [sync / Stuck, slow and fair transfers]: An upload sat "syncing" for hours with nothing moving, starving downloads.
- What was going on: A transfer stuck on a sleeping external drive or a local read moved zero bytes for over two hours, looked identical to a working one, and held every download behind it.
- What the product must do: Bytes moved, not time, decide: a transfer with no progress for 15 minutes is stopped and shown red with "no progress for N minutes"; one still moving is never stopped or alerted on.
- Kind: 3

## Group 98

### DSH-031 [dashboard / Each computer's state]: "Safe to close" was worked out for the person, not the computer it named.
- What was going on: It counted uploads from all of a person's computers but said "this computer", and left out projects still preparing.
- What the product must do: "Safe to close" names the computers that still owe uploads, and is never shown while any project is still preparing.
- Kind: 3

### SYN-099 [sync / Uploads that cannot resume, shutdown and sleep]: "Am I safe to close my laptop?" had no answer, then named the wrong computer.
- What was going on: Footage not yet uploaded sits on one disk only; the answer was worked out for the person but worded "this computer", so the wrong machine was told to stay on.
- What the product must do: The editor sees one line saying whether it is safe to close, naming the computer or computers that still owe uploads, and none rather than a guess.
- Kind: 3

## Group 99

### DSH-039 [dashboard / Ticking and unticking]: After a tick nothing showed for up to a minute.
- What was going on: Then the transfers view claimed nothing was happening while gigabytes flowed.
- What the product must do: Within seconds of a tick the project shows as getting ready, and as transferring as soon as any byte moves.
- Kind: 3

### SYN-110 [sync / Saying truthfully what the sync is doing]: After a tick, nothing happened for a minute, then pages said nothing moved.
- What was going on: A tick waited out a 60-second cycle, a just-ticked project was missing from views, and its setup showed as an error while 2.9 GB flowed.
- What the product must do: A tick takes effect within about 5 seconds, shows "getting ready" until data flows, and progress counts proxies and synced files by bytes.
- Kind: 3

## Group 100

### DSH-048 [dashboard / Projects]: Projects are linked only on an exact name, never on a guess.
- What was going on: "Event 1 Videos" matched "Creator Profiles Season 1" on the digit; a name sharing two words was linked for good; the owner: "the matcher should be updated".
- What the product must do: A project is linked automatically only on an exact name match with one project; any partial match asks a person, and no guess is stored unconfirmed.
- Kind: 2
- State: fixed, never shipped

### RSV-053 [resolve-on-the-editors-computer / Knowing which project is open]: A Resolve project is linked to a project folder only on an exact name match.
- What was going on: Linking on a partial name overlap was silent and permanent; the owner: auto-linking into a non-matching project "is not useful behaviour".
- What the product must do: A Resolve project links automatically only when its name exactly matches one project folder's name; anything else, or an unreadable tree, asks the editor.
- Kind: 2
- State: fixed, never shipped

## Group 101

### DSH-049 [dashboard / Projects]: Orphaned proxies raise one warning per folder, not one per proxy.
- What was going on: A folder moved by hand on the NAS left 56 orphaned proxies, one warning each, two visible at a time; the owner: "one warning per folder ... not one warning per proxy".
- What the product must do: Orphaned proxies raise one warning per proxy folder, naming the first few clips and counting the rest.
- Kind: 2

### PRX-046 [proxies-and-file-moves / Pairing proxies with their originals]: Proxies left behind after their originals moved raised a warning per file.
- What was going on: When originals moved, the old Proxy folder kept 56 orphaned proxies (6.7 GB), each raising its own warning.
- What the product must do: Leftover proxies whose originals moved are reported once per folder, with the originals' new location when it can be found.
- Kind: 3

## Group 102

### DSH-050 [dashboard / Projects]: A new project said the server had 0 originals.
- What was going on: New projects waited up to 45 minutes for their turn to be counted, and "not yet counted" was drawn as zero, which reads as empty.
- What the product must do: A new project is counted within a minute, and until then every surface says "counting", never zero.
- Kind: 3

### PRX-039 [proxies-and-file-moves / Making proxies on editors' computers]: A new project said "0 originals" for up to 45 minutes.
- What was going on: New projects were counted in a slow rotation, so views showed 0 originals, an empty picker, and "43/0" beside people.
- What the product must do: A new project is counted within about a minute, and until then every view says "counting", never 0.
- Kind: 3
- State: fixed, never shipped

## Group 103

### DSH-052 [dashboard / Projects]: Clips in a folder borrowed from another project were missing from its totals.
- What was going on: Borrowed files were counted only under the project that owns the folder.
- What the product must do: A project's media figures include files in folders it borrows, labelled as borrowed.
- Kind: 3
- State: still open

### SYN-011 [sync / What syncs where]: A borrowed folder never came down when its owning project was ticked upload-only.
- What was going on: A borrowed folder counted as covered whenever its owning project was ticked in any mode, but upload-only brings nothing down, and the editor was told to ask an admin.
- What the product must do: A computer syncing a project fully gets every folder it borrows, whatever mode the owning project is ticked in.
- Kind: 3

## Group 104

### DSH-055 [dashboard / Projects]: Leftovers of a failed download sat as owed uploads forever.
- What was going on: Half-finished download part files, 31.7 GB, were counted as uploads due, though the sync never sends such files.
- What the product must do: Files the sync deliberately never sends are never counted as owed, queued or behind.
- Kind: 3

### SYN-115 [sync / What is owed]: Leftovers of a dead YouTube download sat as owed uploads for ever.
- What was going on: Temporary parts, 31.7 GB, left by a crashed download were counted as originals to upload, though uploads deliberately skip such files.
- What the product must do: Anything uploads deliberately skip is never counted as owed, judged by the same rules on both ends.
- Kind: 3

## Group 105

### DSH-060 [dashboard / Projects]: A ".." in the folder template created folders outside the project.
- What was going on: One source of the new-project folder template did not filter "..", so every new project wrote folders outside its own directory.
- What the product must do: Folder names from every source of the project template are stripped of ".." and leading separators before any folder is created.
- Kind: 3

### SRV-033 [server-install-and-running / Installing on a NAS]: Folder names from configuration could climb out of the project tree.
- What was going on: Template folder names from one configuration source kept ".." segments, and new projects created those folders as given.
- What the product must do: Every folder name, from any configuration source, is checked so it can never point outside the project tree.
- Kind: 3

### ALL-080 [whole-product / Windows, text and names]: Names containing ".." could reach outside the studio tree.
- What was going on: Project paths, template folder names and downloaded file names containing ".." or "." created folders or records outside the tree.
- What the product must do: Any folder or file name typed or received is refused if it would resolve outside the studio tree or to the folder itself.
- Kind: 3

## Group 106

### DSH-071 [dashboard / People and computers]: A renamed computer lost its plan or its outstanding commands.
- What was going on: Commands were filed under the computer's name, and a rename onto an existing name deleted that computer's plan.
- What the product must do: A renamed computer keeps its plan, history and outstanding commands; clones never get each other's commands; a rename onto another's name changes neither plan and warns.
- Kind: 3

### PRX-068 [proxies-and-file-moves / Moves that reach every computer]: Pending moves for a renamed or forgotten computer were never delivered or closed.
- What was going on: Commands stayed filed under a computer's old name; answers after a rename updated nothing, and a forgotten computer warned forever while its copy re-uploaded.
- What the product must do: Pending commands follow a computer through a rename, both delivery and answer, and are deleted with a computer the admin forgets.
- Kind: 3

### SYN-134 [sync / Facts about the NAS and the operating systems]: On macOS a rename silently replaces a file already at the destination.
- What was going on: Windows refuses to rename onto an existing file, but macOS replaces it silently, so a restore that "never overwrites" lost a fresh copy on Macs.
- What the product must do: Restoring or moving a file never overwrites an existing file on any platform, including one that appears during the move; a clash is refused and named.
- Kind: 1a

## Group 107

### DSH-076 [dashboard / Reports from computers]: Computers re-sent unchanged file lists every minute.
- What was going on: Each computer re-sent thousands of file names every 60 seconds though they changed every 2 to 5 minutes, and the server rewrote every row.
- What the product must do: Large file lists are sent and stored only when they change, with an occasional full resend so the server converges after a restart.
- Kind: 3

### SYN-117 [sync / Load on the NAS when nothing changes]: Every computer re-sent its unchanged file lists every few minutes.
- What was going on: About 510 MB a day per computer was re-sent and rewritten unchanged, about 47 GB of server writes a day at 20 computers.
- What the product must do: A report about unchanged projects sends and stores almost nothing, idle computers back off, and an over-size report drops only enough detail.
- Kind: 3
- State: still open

