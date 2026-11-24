# Trace of whole-product

## Coverage

- 14-006 | A refused change is shown beside the control that asked for it
- 15-012 | A check that cannot run is itself a problem an admin sees ; Anything the product has not checked reads "not checked", never fine
- 15-077 | A check that cannot run is itself a problem an admin sees
- 17-007 | What the server notices at start-up is shown to an admin, never only written down
- 17-016 | An unexpected error says so plainly and the admin is told
- 19-023 | A part that is missing or broken never stops anything else
- 20-087 | Anything the product has not checked reads "not checked", never fine
- 20-112 | Anything the product has not checked reads "not checked", never fine
- 34-008 | Work done on request always ends with an answer or a sentence
- 04-093 | left out: for the builders only
- 13-080 | An admin switches each part on and off for the whole site ; A site may instead connect an assistant through a subscription signed in on the server
- 01-039 | A change to the site's settings reaches every computer without a restart
- 09-073 | A change to the site's settings reaches every computer without a restart
- 14-015 | Every screen works by keyboard, by touch and with the system's accessibility settings ; Nothing on a screen jumps ; Every screen fits a phone ; Every screen has one look and no way to another
- 25-047 | Every window and section folds away and stays folded ; Every control and status mark explains itself ; Every question before an action looks and behaves the same
- 33-112 | The maker's mark is on every window, and a studio may choose its own
- 04-087 | Counts, sizes, times and lengths of time read the same everywhere ; One word for each idea and each action, everywhere ; The product speaks in the studio's name ; Every message is a plain sentence that says what is known and what to do
- 13-008 | Counts, sizes, times and lengths of time read the same everywhere
- 13-009 | Every "contact support" line names a real contact
- 14-008 | Every control and status mark explains itself
- 14-014 | Copy buttons say whether the copy worked
- 40-091 | Messages name the assistant one way, and nothing it makes carries a product's name
- 09-074 | The product speaks in the studio's name
- 07-010 | Only the studio's own dashboard can make the app on an editor's computer act
- 07-011 | A page can name only files inside the studio's libraries
- 07-014 | left out: for the builders only
- 09-037 | Nothing that carries a sign-in crosses the public internet unencrypted
- 13-005 | Every question before an action looks and behaves the same
- 14-010 | Every question before an action looks and behaves the same
- 04-092 | A studio can put its own logo on every icon and window
- 13-001 | Every browser tab carries the studio's name and the page's name
- 17-010 | Every browser tab carries the studio's name and the page's name
- 27-031 | A studio can put its own logo on every icon and window
- 12-027 | left out: for the builders only
- 14-001 | Pages need nothing from the internet
- 13-085 | A site may connect more than one kind of assistant and pin one ; A site may instead connect an assistant through a subscription signed in on the server
- 14-024 | A site may connect more than one kind of assistant and pin one ; An admin tests each assistant and sees its state
- 14-025 | A site connects the assistant with its own paid key
- 14-026 | A site may instead connect an assistant through a subscription signed in on the server
- 14-027 | A feature that needs the assistant says plainly when it cannot be used
- 15-088 | An admin is told when the site's assistant stops working ; A site may instead connect an assistant through a subscription signed in on the server
- 17-052 | A site may instead connect an assistant through a subscription signed in on the server
- 18-029 | A site may connect more than one kind of assistant and pin one ; A feature that needs the assistant says plainly when it cannot be used
- 18-030 | A site may instead connect an assistant through a subscription signed in on the server
- 18-031 | A site connects the assistant with its own paid key ; No secret is ever shown, recorded or sent where a person could read it
- 18-032 | An admin tests each assistant and sees its state ; A site may instead connect an assistant through a subscription signed in on the server
- 18-033 | A site may instead connect an assistant through a subscription signed in on the server
- 18-034 | A site may instead connect an assistant through a subscription signed in on the server
- 18-035 | A site may instead connect an assistant through a subscription signed in on the server
- 18-036 | The studio's website can ask the assistant to name a piece of gear from a photo
- 19-049 | A feature that needs the assistant says plainly when it cannot be used
- 19-050 | A person picks how strong an assistant answers, where offered
- 34-009 | A run of the assistant is limited and always ends with a sentence ; What the assistant costs is shown before it runs, and a site can cap it
- 34-010 | A conversation with the assistant is kept per cut list
- 34-011 | left out: for the builders only
- 34-012 | Work waiting for the assistant goes in order of who is waiting ; What the assistant costs is shown before it runs, and a site can cap it
- 40-001 | A person picks how strong an assistant answers, where offered
- 40-002 | A person picks how strong an assistant answers, where offered
- 40-003 | A conversation with the assistant is kept per cut list
- 40-004 | A feature that needs the assistant says plainly when it cannot be used
- 40-005 | A conversation with the assistant is kept per cut list

## Questions for the owner

### whole-product-Q1: Can the tools that exist only for the people building the product go?
- Kind: dev only
- Today: four things exist only for building and testing: a switch that swaps the tray icon for another way of drawing it and logs every window that closes; a setting that lets any page served from the editor's own computer drive the app; a way for the server, run in its insecure development mode, to accept check-ins with no credentials; and a stand-in assistant for tests that never touches the network.
- Options: A: leave all four out of the specification; the new build makes its own tools. B: keep them as described.
- Recommend: A, since nobody using the product meets any of them, and the one with a promise inside it (tests can never reach the real assistant) is a matter for the builders.
- Changes for a person: nothing for an editor or an admin either way.
- Text assumes: left out
- Items: 04-093, 07-014, 12-027, 34-011
- Covers: 04-Q9, 07-Q7, 12-Q5
- Answered by the owner 2026-11-24: A, the builders' tools go; nothing of them is in the text.

### whole-product-Q2: Should what the server notices when it starts be shown to admins on the list of problems?
- Kind: other
- Today: when it starts the server notices some things that will stop people working (a person listed as an admin with no account, NAS details missing so editors cannot sign in) and only writes them to its own log, which nobody reads.
- Options: A: raise each on the overview's list of problems, with what to do. B: keep them in the log only.
- Recommend: A, since the rule everywhere else is that nothing fails silently and these break sign-in.
- Changes for a person: with A an admin sees, on the overview, that editors cannot sign in and why, instead of hearing it from an editor.
- Text assumes: A
- Items: 17-007
- Covers: 17-Q13
- Answered by the owner 2026-11-24: A, what the server notices at start goes on the overview's list of problems.

### whole-product-Q3: Should every "are you sure" question be the same dialog, with the same buttons?
- Kind: differs
- Today: most questions appear in the product's own dialog titled "are you sure" with Cancel focused and "Yes, do it"; a few (signing out everywhere) use the browser's own plain box with OK and Cancel; music's questions say Cancel and "Go ahead".
- Options: A: one dialog of the product's own everywhere, titled "Are you sure?", Cancel focused, "Yes, do it". B: keep the mix.
- Recommend: A, one way to ask is fewer parts and a person always knows which button is safe.
- Changes for a person: signing out everywhere and music's questions look and read like every other question.
- Text assumes: A
- Items: 13-005, 14-010, 25-047
- Covers: 14-Q6
- Answered by the owner 2026-11-24: A, one "Are you sure?" dialog everywhere, Cancel focused, "Yes, do it".

### whole-product-Q4: Should one computer be able to carry a different logo from the rest of the studio?
- Kind: several ways in
- Today: a logo can be set for the whole studio, and also given to one computer, where it wins over the studio's.
- Options: A: the studio's logo only. B: keep the per-computer logo as well.
- Recommend: A, since one place a setting comes from is the owner's rule and nobody has needed a different logo on one machine.
- Changes for a person: with A an admin sets the logo once and every computer shows it; nobody can give one computer its own.
- Text assumes: A
- Items: 04-092
- Covers: 04-Q10
- Answered by the owner 2026-11-24: A, one logo for the whole studio; no per-computer logo.

### whole-product-Q5: Should the installed Timeline Cards app keep its own icon (rows with a red playhead), or carry the product's mark like every other window?
- Kind: differs
- Today: every icon of the product comes from one brand mark, except the installed Timeline Cards app, whose icon is rows on a dark rounded square with a red playhead. Your ruling puts the maker's mark on every window, popup, installer, taskbar entry and tab.
- Options: A: the installed Timeline Cards app uses the product's mark like everything else. B: it keeps its own rows-and-playhead icon.
- Recommend: A, since your ruling asks for one mark everywhere and a studio's own logo should reach this icon too.
- Changes for a person: with A the Timeline Cards app on a phone or computer shows the same mark as the rest of the product (or the studio's logo).
- Text assumes: A
- Items: 33-112
- Answered by the owner 2026-11-24: A, the installed Timeline Cards app carries the product's mark (or the studio's logo).

### whole-product-Q6: Should a site be able to connect several kinds of assistant, in an order with a pin, or just one?
- Kind: either-or
- Today: an admin can set up several assistant services, tried in a fixed order unless one is pinned; but Timeline Cards' assistant features work with only one kind, so any other kind leaves them refused, and some kinds answer only YouTube search.
- Options: A: keep several kinds, the order and the pin. B: one kind of assistant only, the one every feature works with, connected with one key.
- Recommend: A, since it keeps the studio free to choose and change the assistant's maker, as the product is kept free of any one editing program; B is the fewer-parts choice if you are content to tie every feature to one maker.
- Changes for a person: with B an admin pastes one key and everything works; with A an admin can mix kinds but may find Timeline Cards refusing.
- Text assumes: A
- Items: 13-085, 14-024, 14-025, 14-026, 14-027, 18-029
- Covers: 14-Q2
- Answered by the owner 2026-11-24: A, several kinds of assistant, in an order, with a pin.

### whole-product-Q7: Should a site be able to run the assistant through a personal subscription signed in on the server, or with a paid key only?
- Kind: dormant
- Today: besides a paid key, an admin can fetch the assistant maker's own program onto the server and sign it in with a personal subscription, after accepting a notice that this may breach the subscription's terms; the server can keep that program up to date once a day. It is off on every new site, and the build sent to customers locks it off whatever is stored. Your rulings say every studio gets the same one build, and that customer builds use only the site's own paid key with no setting that enables subscription sign-in.
- Options: A: cut it; every site connects the assistant with a paid key. B: keep it, off until an admin accepts the notice, in every site's build.
- Recommend: A, since one build serves every studio and your ruling forbids it for customers, so keeping it would mean a second build or breaking the ruling; it also removes a wizard, a sign-in, an updater and three warnings.
- Changes for a person: with A your own studio moves its assistant from your subscription to a paid key; nothing changes for a customer.
- Text assumes: B
- Items: 13-080, 13-085, 14-026, 15-088, 17-052, 18-030, 18-032, 18-033, 18-034, 18-035
- Covers: 13-Q11, 18-Q5
- Answered by the owner 2026-11-24: B, the subscription way stays in the product for every site, in the one build, off by default on every new site until an admin turns it on; the paid key stays the default way. His own studio uses it.

### whole-product-Q8: Should naming gear from a photo for the studio's website follow the site's assistant choice and the switch that turns the assistant off?
- Kind: differs
- Today: the studio's public website can send the server a photo of gear and get a packing-list entry back; unlike every other use of the assistant, it always uses the subscription program and ignores the admin's choice, the pin and the site's switches.
- Options: A: it follows the site's choice, pin and switch like everything else. B: it keeps its own fixed way. C: cut it from the product; it serves the website, not editing.
- Recommend: A, one way to reach the assistant; C if the website can call an assistant itself.
- Changes for a person: with A, switching the assistant off also stops gear naming; with C the website's gear page loses the photo button.
- Text assumes: A
- Items: 18-036
- Covers: 18-Q4
- Answered by the owner 2026-11-24: A, gear naming follows the site's assistant choice, its pin and its off switch.

### whole-product-Q9: Two limits on assistant spending stack: a spend per hour and a number of calls per day. Keep one, both, or neither?
- Kind: either-or
- Today: the person running the server can set a dollar limit per rolling hour and, separately, a count of assistant calls per day; both are off by default and both apply on top of each other. Your ruling also asks that routine runs stay within a cost you set.
- Options: A: one limit, money per day, shown in settings, with the expected cost shown before each task. B: keep both as they are. C: neither, the key's own limit on the maker's side is enough.
- Recommend: A, one limit in the unit you think in (money) covers both and matches your cents-not-dollars ruling.
- Changes for a person: with A an admin sets one daily budget; with B two.
- Text assumes: A
- Items: 34-009, 34-012
- Answered by the owner 2026-11-24: A, one daily budget in money, with the expected cost shown before each task.

### whole-product-Q10: If the subscription way stays, where is it switched on: the tick box under the list, the notice in the set-up, the site's settings, or all three?
- Kind: several ways in
- Today: the site-wide switch allowing subscription programs can be set from a tick box under the list of assistants, by accepting the notice inside the set-up steps, and from the site settings form.
- Options: A: only by accepting the notice in the set-up (and switched off from the same place). B: keep all three.
- Recommend: A, since accepting the notice is the one act that should turn it on, and one place is the owner's rule.
- Changes for a person: with A an admin always reads the notice before it is on.
- Text assumes: A
- Items: 14-024, 14-026
- Answered by the owner 2026-11-24: A, switched on in one place only, by accepting the notice inside the set-up.

## Readers' questions and unsettled points

- 04-Q9 | whole-product-Q1
- 04-Q10 | whole-product-Q4
- 07-Q7 | whole-product-Q1
- 09-Q8 | with releases-and-updates
- 09-Q11 | with releases-and-updates
- 12-Q5 | whole-product-Q1
- 13-Q11 | whole-product-Q7
- 14-Q2 | whole-product-Q6
- 14-Q4 | with server-install-and-running-1
- 14-Q6 | whole-product-Q3
- 17-Q10 | with dashboard-2
- 17-Q13 | whole-product-Q2
- 18-Q4 | whole-product-Q8
- 18-Q5 | whole-product-Q7
- 19-Q4 | answered: ALL-009 and the owner's requirements (switching a part hides it and stops its work); every part switches on and off live, within a minute, written under "An admin switches each part on and off for the whole site"
- 34-Q5 | whole-product-Q9
- 40-Q9 | with cards-editor-3
- 40-Q10 | with cards-editor-4
- U-07-4 | not a question: what "end of timeline" and "at the playhead" do inside Resolve belongs to the send-to-Resolve behaviours of the b-roll archive and music, outside this piece
- U-09-1 | settled: the site's settings are fetched while the app runs, about every 15 minutes, so a change reaches a computer without reinstalling
- U-09-2 | settled: one rule for every call that carries a sign-in, shared work and Footage Sorter copies included
- U-09-6 | behind the glass
- U-13-10 | behind the glass
- U-14-7 | settled: every page carries the same question dialog and the same explanations, written as a rule under "Every question before an action looks and behaves the same" and "Every control and status mark explains itself"
- U-14-8 | behind the glass
- U-18-1 | settled: accepting the notice in the set-up switches the subscription way on for the site; where else it may be switched is whole-product-Q10
- U-18-2 | settled: such notes are shown to admins as problems on the overview, written under "An admin is told when the site's assistant stops working"
- U-19-8 | settled: the Sorter's pages and the Timeline Cards app's updates are written in their own pieces
- U-25-3 | behind the glass
- U-25-4 | behind the glass
- U-34-4 | behind the glass
- U-40-2 | answered: the owner's requirements (one board and one editor), so nothing is served in a second form

## Still unsettled


## Conflicts between an item and a lesson

- ALL-009 | 01-039 | the item says a part switched on or off reaches each computer within about 15 minutes; the lesson asks that within a minute none of a switched-off part's work is still running anywhere. Wrote: a part switched on or off takes effect everywhere within a minute; other site settings within about 15 minutes.
- ALL-087 | 14-026 | the item says that where the publisher gives no checksum the install goes ahead and the received file's checksum is recorded; the lesson and 18-033 say no checksum means refusal. Wrote the refusal.
- ALL-089 | 13-080, 13-085, 14-026, 18-030, 18-033, 18-034, 18-035, 17-052 | the ruling says a customer's build has no setting that enables subscription sign-in; the owner's answer of 2026-11-24 is later: the subscription way stays for every site, off by default, switched on by accepting the notice in the set-up (whole-product-Q7). Wrote his answer; the paid key stays the default way.
- ALL-007 | 17-052 | the ruling says one build serves every studio; the owner's answer of 2026-11-24 is later and keeps that: one build, with the subscription way present for every site and switched off until an admin turns it on. No locked second build is written.
- ALL-025 | 33-112 | the item gives the installed Timeline Cards app an icon of its own; the ruling puts the maker's mark on every window and taskbar entry. Wrote the ruling, confirmed by the owner 2026-11-24 (whole-product-Q5).
- ALL-048 | 13-008 | the item reads a missing time as "never", which produced "since never"; wrote that a missing time reads as words that fit the sentence.
- ALL-088 | 40-001 | the item shows prices only in the strength picker's notes; the ruling asks that every assistant task shows its expected cost before running. Wrote the ruling.

## New in this text

- Every feature shows somewhere whether it works | written from ALL-053, ALL-054 and ALL-055; no item showed it as a general rule.
- A computer with nothing ticked is normal | written from ALL-090.
- A page says it is loading until it has an answer | written from ALL-052.
- Every refusal and failure shows its real reason and stays until read | written from ALL-056 and BRD-035.
- Every button acts or says why it cannot | written from ALL-057 and ALL-060.
- Success is shown only when it is true | written from ALL-058.
- A rehearsal only says what would happen | written from ALL-059.
- A window waiting for an answer comes to the front | written from ALL-061.
- An admin switches each part on and off for the whole site | each part shows its own version number beside its switch (ALL-005); switching a part off stops its work within a minute (ALL-009).
- The computers and systems the product supports are one published list | written from ALL-008.
- Each action is a labelled button | written from ALL-020 and ALL-028.
- Each colour means one thing on every screen | written from ALL-012, ALL-017 and ALL-018, as meanings only; the values are in the look book.
- Every screen has one look and no way to another | written from ALL-015, ALL-016 and ALL-019.
- Typefaces come with the product, and Chinese names show in a typeface that has them | written from ALL-024.
- Every app reached from the dashboard leads back to it | written from ALL-026.
- A phone can install a page as an app without signing in first | written from ALL-014.
- Every message is a plain sentence that says what is known and what to do | written from ALL-041 to ALL-045 and ALL-049.
- Nothing removes footage on its own | written from ALL-062.
- Opening a tool never starts its work | written from ALL-063.
- Every way of doing something keeps the same safety rules | written from ALL-065.
- One bad item never stops the rest | written from ALL-066.
- Every setting is a control in the product | written from ALL-067 and ALL-068.
- An interrupted save never loses a computer's settings | written from ALL-069.
- Names in any script work everywhere | written from ALL-070 to ALL-072, ALL-074 and ALL-078.
- A folder is the same folder however it is spelled | written from ALL-073 and ALL-079.
- Names that would reach outside the studio's tree are refused | written from ALL-080.
- Showing a clip in the file manager selects it | written from ALL-075.
- Every file picker on Windows is the full system dialog | written from ALL-077.
- Paths shown on a web page are written for every computer | written from YTD-092.
- Dates are the studio's dates | written from ALL-076, ALL-081 and ALL-082.
- An admin can always find out what happened and when | written from ALL-085 and ALL-086.
- No secret is ever shown, recorded or sent where a person could read it | the masking of 18-031 written as a rule for every secret.
- Nothing runs on a computer that its person or the vendor did not put there | written from ALL-087.
- A request the server cannot accept gets a plain refusal, never a crash | written from ALL-083.
- Editors' computers never wear the server down | written from ALL-084.
- One switch turns the assistant off for the whole site | the owner's requirement; no item described the switch itself.
- What the assistant costs is shown before it runs, and a site can cap it | expected cost shown before each task, routine runs within a cost the site sets (ALL-088), and one daily budget in money in place of the hourly spend limit and the daily count of calls (whole-product-Q9).
- An admin is told when the site's assistant stops working | widened from 15-088 to any connected assistant.
- The studio's website can ask the assistant to name a piece of gear from a photo | follows the site's choice and switch (recommendation of whole-product-Q8).
- On every screen the assistant is called Assistant | the owner's decision (requirements, 2026-11-24): "Assistant" on every screen, never a maker's or model's name; admins tell connections apart by place and kind; strengths named by what they do, with their price.
- How footage travels is chosen from real measurements | points to the owner's requirement that the way footage travels is chosen by measurement with near and far-off computers, re-run before each release.
- An admin switches each part on and off for the whole site | the new-site default (every part off except the help for the editing program) restated from the owner's requirements, with "a studio that only wants syncing sees nothing else".
- A feature that needs the assistant says plainly when it cannot be used | the refusal for a kind that cannot do Timeline Cards' features no longer names the assistant it was made for.
- A person picks how strong an assistant answers, where offered | each strength always shows its price, or "price not known yet" for a newer version, instead of dropping it.

## Parts of items left out

- 15-077 | "roll back from the published packages" reworded as going back to the version before; how is in Releases and updates.
- 17-007 | computers still reporting on the old shared credential, retired sign-in secrets still honoured, and a stored setting the locked build ignores: arrangements of the present build's credentials and builds.
- 17-016 | "except the old Timeline Cards page": there is one editor.
- 34-008 | the word "helper" for the server's inner parts: an inside.
- 01-039 | retrying every 2 minutes after a failed fetch, and set-up values that take effect only at the next start: arrangements.
- 09-073 | "nobody is told" when the site cannot be reached: the computer's own connection state is shown elsewhere (The app on each editor's computer).
- 13-080 | the YouTube anti-automation switch and automatic updates are written in their own pieces (YouTube downloads, Releases and updates).
- 14-015 | "the pages are always dark": how the look looks is the look book's.
- 13-001 | colouring a phone's status bar: the look book's.
- 27-031 | a builders' check that reports icons that no longer match the mark.
- 13-008 | the text progress bar of ten or sixteen blocks: how it looks; a time with no zone read as universal time: an inside.
- 04-087 | durations "<1 min", "~2h 5m" and time left "Nh MMm" reconciled into one form.
- 07-010 | "the CC Sync companion" in the refusal is the build's own name for the app, reworded; a change of address made on the computer itself needing a restart: an arrangement.
- 07-011 | "no mount configured for share" reworded: it names an inside.
- 09-037 | the update download allowing plain http only by the shape of the address: one rule written (question with releases-and-updates).
- 13-005 | the browser's own confirm box for signing out everywhere (whole-product-Q3).
- 14-024 | "All five providers are set up.": the number of kinds is the build's; the server's own check (14-028) is described in The dashboard.
- 14-026 | the hint naming the command to sign in on the server itself: a terminal step nobody should need (ALL-067).
- 18-032 | "run <login command> on this host": as above.
- 18-034 | "Signing in from the page needs the server's usual operating system; elsewhere run the program's own login": a terminal step.
- 17-052 | the vendor's locked build and the studio's own build: one build serves every studio (ALL-007).
- 18-036 | a code derived from the server's own secret: how it is made is behind the glass; "the first after an hour's quiet is slower": a running time.
- 19-049 | "translate" in the refusal: the editor has no translate controls (owner's requirements).
- 19-050 | naming an exact dated model pins it: model names are behind the glass; remembering what each family name meant: an inside.
- 34-009 | the hourly spend limit, replaced by one daily budget in money (whole-product-Q9)
- 34-012 | the daily count of calls, replaced by one daily budget in money (whole-product-Q9)
- 33-112 | the rows-and-playhead icon, replaced by the product's mark (whole-product-Q5)
- 34-009 | at most 4 runs at once and 32 waiting: the size of the build's own pipe.
- 40-001 | the dollar prices per million units of text for each strength: the maker's prices, not the product's.
- 40-002 | checking for newer versions every 6 hours, 10 minutes after a failure: an arrangement.
- 40-005 | conversations kept in the episode folder, and held by the provider for one server only: where they are kept is behind the glass; the promise (survives reloads and restarts, a lost one is re-opened once and said so) is written.
- 34-010 | conversations kept on the server and never in the episode's folders: where they are kept is behind the glass.

- 04-092 | a logo of one computer's own, winning over the studio's: cut by the owner 2026-11-24 (whole-product-Q4)
- 14-024 | the tick box under the list and the site settings form as places to allow subscription programs: cut by the owner 2026-11-24 (whole-product-Q10)

## Joins with other capabilities

- The dashboard / Problems the server finds | An unexpected error says so plainly and the admin is told | the list of problems on the overview, one row per kind of error and page.
- The dashboard / Settings and setup | A site may connect more than one kind of assistant and pin one | where the assistant settings live, and the setting "Which assistant to use".
- The dashboard / Pages that refresh and answer clicks | A refused change is shown beside the control that asked for it | the "stopped updating" warning and answers beside the pressed control.
- The dashboard / Security of pages | Nothing that carries a sign-in crosses the public internet unencrypted | the warning when a computer connects unencrypted over the public internet.
- The dashboard / Phones and the installed app | A phone can install a page as an app without signing in first | what is reachable signed out for installing.
- The app on each editor's computer / Settings, records and background work | Only the studio's own dashboard can make the app on an editor's computer act | where the dashboard address and the extra address are set on a computer.
- YouTube downloads / Signing in to YouTube | An admin switches each part on and off for the whole site | the site switch "YouTube's extra measures against being blocked".
- Releases and updates / Pushing updates and seeing who has what | An admin switches each part on and off for the whole site | automatic updates switched on for the site.
- Accounts, privacy and the legal paperwork / What the product records about a person | A change to the site's settings reaches every computer without a restart | the switches on what computers report.
- The server: installing it and keeping it running / NAS speed, load and clock | Dates are the studio's dates | the studio's time zone ("Schedules run on the studio's own clock").
- Timeline Cards: the editor / Shortening, the edit chat and the assistant | A conversation with the assistant is kept per cut list | the edit chat and transcript search that hold conversations.
- Timeline Cards: the editor / Search and the transcript panel | A person picks how strong an assistant answers, where offered | the strength picker on the search panel.
- The dashboard / Settings and setup | A site may instead connect an assistant through a subscription signed in on the server | dashboard-2 writes the guided setup as notice, download, sign-in and test; the owner kept it (2026-11-24), off by default and switched on only by accepting the notice in the set-up; dashboard-2 should match.

## Joins settled

- accounts-privacy-legal F19 | changed: A change to the site's settings reaches every computer without a restart | an unreadable copy now counts every switchable kind of reporting as withheld (not on); syncing and the checks behind it keep running
- cards-editor-3 F2 | changed: A person picks how strong an assistant answers, where offered | summaries, the montage builder and shortening use the edit chat's chosen strength; a one-person search is a scope of the search panel at its chosen strength
- cards-editor-4 F10 | changed: A conversation with the assistant is kept per cut list | the edit chat also starts afresh when the house style changed or after more than an hour cold, pointing to cards-editor-4
- dashboard-1 F10 | changed: A part that is missing or broken never stops anything else | a switched-on part that cannot work keeps its menu place and opens a "not working right now, why, admins told" page; also on the problems list and the overview's state of the parts
- dashboard-2 F8 | changed: Dates are the studio's dates | points to server-install-and-running-2 "Schedules run on the studio's own clock" for the one studio time zone
- dashboard-2 F12 | no change here: dashboard-2 changes; this piece already says a refused click gets the note above its control
- editor-app F27 | changed: Only the studio's own dashboard can make the app on an editor's computer act | another allowed address is added by an admin for the site; the editor keeps only correcting their own computer's dashboard address
- server-install-and-running-1 F10 | changed: Dates are the studio's dates | same pointer as dashboard-2 F8, no longer to server-install-and-running-1's Settings and secrets
- whole-product F1 | changed: One switch turns the assistant off for the whole site ; A conversation with the assistant is kept per cut list | the keeping period still runs while the assistant is off; a cut list's conversation lasts at most that period
- whole-product F3 | changed: A conversation with the assistant is kept per cut list | transcript search dropped from the per-cut-list rule (and the "no cut list open" sentence with it), pointing to cards-editor-3's search sheet
- whole-product F4 | changed: What the assistant costs is shown before it runs, and a site can cap it | routine work counts against the one daily budget, no allowance of its own
- whole-product F5 | changed: What the assistant costs is shown before it runs, and a site can cap it | a run a person starts is refused with the budget sentence; work running on its own waits for the next day's budget
- whole-product F6 | no change here: cards-footage-in changes; this piece already says no assistant message is left with it off
- whole-product F7 | changed: A change to the site's settings reaches every computer without a restart | the safe-side rule covers the Timeline Cards editor in a browser as well as the app; cards-editor-5 changes its own sentence
- whole-product F8 | changed: A site may connect more than one kind of assistant and pin one ; A feature that needs the assistant says plainly when it cannot be used | the Footage Sorter's Ask, footage-in's translation, line-up and first sort and the board's assistant added to the per-feature list and the "No assistant is connected." sentence; footage-in and the board, as Timeline Cards features, join the made-for-one-kind list, the Sorter's Ask works with any kind (my call: no piece states it)
- whole-product F9 | no change here: music changes; this piece already says nobody is told to ask themselves
- whole-product F10 | no change here: the name here is already "Switchable parts"; server-install-and-running-1 drops its own line
- whole-product F12 | no change here: this piece already holds "no assistant has a working key" with where an admin connects one; youtube changes
- whole-product F13 | no change here: this piece already says finding out a state costs no call; youtube changes
- whole-product F14 | changed: Nothing runs on a computer that its person or the vendor did not put there | YouTube's downloader and a kept-up-to-date subscription assistant program take the newest checksum-verified build, never older, without a button
- youtube F1 | changed: An admin switches each part on and off for the whole site | the switch is named "YouTube's extra measures against being blocked" and points to youtube's "A site decides whether YouTube's extra measures against being blocked are used"
