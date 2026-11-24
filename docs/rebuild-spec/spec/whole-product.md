# The whole product

These are the rules that hold on every screen and in every part of CC Sync: the dashboard's pages, the b-roll archive, music, YouTube downloads, Timeline Cards, the Footage Sorter and the app on each editor's computer. They say how the product tells people what it knows and what it does not, how it refuses, how it words things, how it keeps people and footage safe, how it handles names and text, what it promises about its records and the programs it runs, and how the assistant is connected, chosen, paid for and switched off. Every other piece of the specification leans on these rules and does not repeat them; a tester can check each one on any screen. None of it can be switched off: it is part of the core.

## Could not check, refusals and nothing silent

### Anything the product has not checked reads "not checked", never fine

Whenever the product could not find something out, it says so in those words or as "cannot tell". It never shows such a thing as OK, as zero, as passed or as cleared. In particular:

- A problem that was open before a check failed stays open; a check that did not run never declares anything cleared.
- Something the product could not read is never treated as empty. Records survive, counts keep their last value marked as old with the time they were last true, the product takes the side that keeps footage and people safe, and the next good read puts everything right.
- When the records the product keeps about people (suspensions, archived people, keys waiting to be used, withdrawn sign-ins, personal data) are momentarily busy or failing, the answer is an error, never "nobody" or "nothing". So a busy moment can never share a suspended person's folders again or bring back a sign-in that was withdrawn.
- Any step that is waiting on something the product could not check refuses rather than going ahead.
- Every kind of problem the server watches for notes the time each time it is looked for, whether or not anything is found. A kind not looked for within 36 hours, or whose time cannot be read, shows as "not checked". A problem closing itself does not count as having been checked.

### A check that cannot run is itself a problem an admin sees

When one of the server's own checks cannot run, that is a serious problem of its own, named after the check: "The check for '<what>' could not run, so this server does not know whether that is all right. Treat it as unchecked, not as fine." When a check stops with an error part way: "The server's own check '<name>' stopped with an error (<what went wrong>), so whatever it watches is not being watched right now. Its last findings are left as they were." The fix offered is to send the server's diagnostics to the site's support contact, and, if it began just after an update, to go back to the version before. When the server cannot even read its own state, one problem stands for the whole set of checks: "This server could not read its own state to check whether anything is wrong, so nothing below has been checked."

Each such problem clears the next time its check runs cleanly, and only then.

- Who: admins see these on the overview's list of problems.

### What the server notices at start-up is shown to an admin, never only written down

Anything the server notices when it starts that will stop someone working, or that an admin should act on, is raised on the overview's list of problems with what to do, not only kept in a record nobody reads. For example: a person named as an admin who has no account, or details of the NAS missing so that editors cannot sign in and an admin cannot manage people ("The dashboard still runs").

- Who: admins see these.

### An unexpected error says so plainly and the admin is told

When something goes wrong that the product did not expect, the person sees "internal error", with nothing from the error itself, and the error is recorded on the overview's list of problems for admins, one row per kind of error on each page (see The dashboard: Problems the server finds). When the server is momentarily too busy to answer, the person is told "the server is busy; try again", the page tries again on its own after 30 seconds, and admins see a separate "server busy" warning. Every switchable part answers and records its unexpected errors the same way.

### A part that is missing or broken never stops anything else

The b-roll archive, music, YouTube downloads, Timeline Cards and the Footage Sorter each come up on their own. If one is not set up, is incomplete, or fails to start, the dashboard, syncing and every other part still start and work. A part that started but cannot work (for example, it cannot write where it keeps its records) is taken out of the menu rather than shown broken, and an admin sees why on the list of problems and beside its switch in settings.

### Every feature shows somewhere whether it works

A feature that has stopped working says so where a person who uses it looks: on the feature itself and on the overview. A missing piece a feature needs (a graphics card, a sign-in, a program, a connection) is named where the feature is used, with what to do. Nothing needs a hidden gesture to find out whether it works. When the assistant cannot be used, every feature that needs it says which reason applies (slow to start, signed out, not connected), and the assistant's settings never claim a connection works that does not (see "A feature that needs the assistant says plainly when it cannot be used"). A feature that is not switched on, or that a site does not have, shows nothing: its controls, marks, banners and checks are hidden and the rest of the page is unchanged; it never shows broken parts or a permanent "not checked".

### A computer with nothing ticked is normal

A computer with no projects ticked shows as normal on every surface: no error, warning, blocked reason, warning colour, alert or notice. Real faults on that computer keep theirs.

### A page says it is loading until it has an answer

Until its data arrives a page or panel says it is loading. A load that failed says so, with its reason and a way to try again. "Nothing found", "no clips match", an empty list or a zero appears only after a real answer that is empty.

### Every refusal and failure shows its real reason and stays until read

Whenever the product refuses something or something fails, the person it affects is shown the real reason in a plain sentence, never a generic line in its place. A failure to reach the server or the network is named as that. The message stays on screen until the person has had a chance to read it; it is not a flash that vanishes. When one action is refused several times over (for example several files in one drop), the person sees one summary with a count, and each reason can still be read.

### A refused change is shown beside the control that asked for it

When the server refuses a change a person asked for with a button, form or switch (other than because their sign-in has ended), the page is not marked as out of date. A short note appears directly above the control that was used and is scrolled into view:

- when this account may not do it: "Not allowed: <the server's reason>", or "Not allowed: this account cannot do that." when no reason was given;
- otherwise: "Refused: <the server's reason>", or "Refused: the server answered <status> and gave no reason."

A tick box that had been flipped goes back to what the server still holds. Using the same control again removes the old note first.

When a press redraws a panel that carries an error or an outcome (for example a test mail that went out or failed), that message is moved to directly above the control that was pressed and scrolled to the middle of the screen; an error wins over an outcome. When several forms on a page do the same kind of thing, the message goes beside the one actually used. For a form taller than half the screen, the message goes above its last button instead. Timed refreshes never move a message; only a person's press does.

### Every button acts or says why it cannot

Every click or tap is acknowledged at once. Any action that takes more than a second shows that it has started and then how far along it is. A button never quietly does nothing: it acts, or says why it cannot. A control that opens a panel always opens it, empty if need be, saying how to start.

### Success is shown only when it is true

An action reports success only once the change is confirmed. When part of it failed, the person is told what failed and what succeeded; partial failure is never shown as plain success. Progress counts only what succeeded. Nothing a retry would need is removed before the work is done.

### A rehearsal only says what would happen

Wherever a person can try something out first (a rehearsal, a dry run, a preview of a change), the product says "checking" or "would", never claims that anything changed and never asks the person to make a change. What it reports is exactly what the real run would do, counted the same way.

### A window waiting for an answer comes to the front

Any window or dialog that needs a person's answer before work can go on comes to the front and stays on top until it is answered, so a run never seems to have done nothing because its question opened out of sight.

- Windows and macOS: holds for the app on the editor's computer on both.

### Work done on request always ends with an answer or a sentence

Work the server does when a person asks for it (outside the assistant, which has its own rules under "The assistant") always ends in a result or a plain sentence naming the part of the product that could not do it, never a hang:

- no answer in time: it gives up after 2 minutes, unless a part has said its work may take longer, and says "<part> did not answer "<request>" within N s";
- too much at once: "<part> is busy with other requests; try again in a moment";
- it failed: "<part> stopped part way; ask again and it will be started afresh";
- it keeps failing: "<part> keeps stopping; it will be tried again in a few seconds";
- something the part needs is not on the server: the sentence names what is missing and says the part cannot run until it is there;
- the person cancelled: "stopped";
- the server is shutting down: "the server is shutting down".

Progress is shown to the person while the work runs. One part's long work never holds up another part's quick requests.

#### Lessons

- Met: ALL-052, ALL-090, BRD-035, ALL-050, ALL-051, ALL-053, ALL-054, ALL-055, ALL-056, ALL-057, ALL-058, ALL-059, ALL-060, ALL-061.

## The rebuild itself

### An admin switches each part on and off for the whole site

Every studio runs the same product, with every part in it. A part a studio does not use is simply switched off; there is never a separate edition with parts missing. In settings an admin sees every switchable part listed with its switch and its own version number, and switches each one on or off by itself, without touching any other.

On a new site, the help for the editing program is on and the other five switchable parts are off until an admin switches them on. Switching a part off hides it from everyone but an admin and stops its work everywhere, on the server and on every editor's computer, within a minute; nothing it holds is deleted, and switching it on again brings it back as it was. Switching a part on makes it appear for everyone within a minute, with no restart of the server or of any computer.

Some features inside a part are also switched on for the whole site rather than per person, and are described where they belong: getting round YouTube's blocking (see YouTube downloads: How YouTube throttles and refuses) and computers taking new versions without anyone clicking (see Releases and updates: Pushing updates and seeing who has what). Each is off on a new site.

- Who: an admin.
- Setting: Switchable parts. Does: switches each of the six parts (the b-roll archive, music, YouTube downloads, Timeline Cards, the Footage Sorter with camera cards, the help for the editing program) on or off for everyone. Default: the help for the editing program on, the other five off. Who: an admin. Applies to: the site. Search words: parts, modules, switch on, enable, disable, features.
- Name and search words: Parts. Search words: parts, modules, features, switch on, versions.

### A change to the site's settings reaches every computer without a restart

Every computer of the studio works from the site's settings: the studio's name and brand, the name its drive is given in sentences, which parts are switched on, and the switches on what computers report. A change an admin makes reaches every running computer within about 15 minutes, and a part switched on or off within a minute, with no restart. A computer that is off takes the change as soon as it next reaches the server.

Each computer keeps the last copy of the site's settings it was given (from its installation onwards) and works from that copy whenever the server cannot be reached, so it starts and syncs offline. When the copy cannot be read, every optional feature counts as off and every switch on what a computer reports counts as on, the safe side in each case, until a good copy arrives (see Accounts, privacy and the legal paperwork: What the product records about a person).

- On its own: each computer picks up the site's settings without anyone asking, and keeps working from its last copy when the server cannot be reached.

### The computers and systems the product supports are one published list

There is one published list of the operating systems, their versions and the kinds of NAS the product supports. Every installer and every set-up check agrees with that list exactly: what the list includes installs, and what it leaves out is refused with the list named.

#### Lessons

- Met: ALL-001, ALL-002, ALL-003, ALL-004, ALL-005, ALL-006, ALL-007, ALL-008, ALL-009.

## The look

### Every screen has one look and no way to another

Every surface wears the one look the owner's requirements set (the Timeline Cards editor's): the dashboard's pages, the b-roll archive, music, YouTube downloads, the Footage Sorter, the app on the editor's computer and every window it opens. There is no setting, saved preference, old link or page that shows any other look. No control keeps the browser's or the operating system's default appearance: every field, tick box, list, drop-down, scroll bar and slider wears the product's look on every page, the browser's own drop-downs and scroll bars included. Where a row of navigation does not fit, it wraps only between whole items, never in the middle of one.

### Each action is a labelled button

Every action is a real button with a label that says what it does, in sentence case, with any keyboard shortcut shown as a separate hint beside it. A button that carries only an icon has a name screen readers speak and an explanation on hover, focus and touch. No label is clipped at a width of 1440 pixels, and every label says what it does (a search box says what it searches).

### Each colour means one thing on every screen

The look book gives each colour one job, and no screen uses a colour for anything else. In particular the colour that means synced or backed up is used for nothing else, so a person can trust it at a glance; selection, focus and "go" share one colour; suggestions and warnings share one; and the brand, the one main action on a screen, and danger share one.

Text is always readable against what it sits on: names and secondary text reach a contrast of at least 7 to 1, and all other readable text at least 4.5 to 1, on every background, with faded text measured as it is drawn. Only disabled text is exempt. This is checked automatically before every release.

The sixteen clip colours of the editing program are shown exactly as the program shows them, never changed, and each stays visible against whatever it sits on, at a contrast of at least 3 to 1.

### Every screen works by keyboard, by touch and with the system's accessibility settings

- Every focused control shows a clear focus outline, and every border can be seen.
- Every dialog answers Enter and Escape.
- Nothing blinks or pulses for ever: a warning light, an episode loading and a tick box saving blink a few times and stop.
- With the operating system's reduce-motion setting on (on Windows this is also the case whenever animation effects are switched off), every animation and transition is off, final states show at once, and nothing waits for an animation that is not shown.
- With Windows high contrast on, every mark whose meaning would otherwise be carried by colour alone gets a border, and the current page is outlined and underlined.
- On a touch screen every button, tab, tick box, field and list row is at least 44 by 44 pixels.
- Screen readers hear names without decorative symbols or underscores; controls repeated in a list name what they act on ("Untick Project A", not just "Untick"); and every confirmation announces its whole question.

No release reaches a studio with a page that has not been opened and used in a real browser.

### Nothing on a screen jumps

Switching pages or tabs, loading, hovering or opening a panel never moves anything already on screen. Places where an answer will appear keep their room before it arrives, and a button keeps its width while its label changes to a busy word during a request. Only an idle box may shrink to fit what it holds. A panel with nothing in it takes no room.

### Every screen fits a phone

Every page fits a phone 390 pixels wide with no sideways scroll and nothing that needs hovering to reach. On a phone, text is never smaller than 12 pixels, every text box uses text of at least 16 pixels so the phone does not zoom in on it, long names wrap rather than widening the page, and wide tables and code scroll inside themselves. Every window keeps its buttons within reach whatever its size. Every figure has a legend a person can see.

On a phone, leaving a main list for another view adds one step to the browser's history, so the phone's Back button returns to the list rather than leaving the page.

- Phone and desk: text sizes, touch targets and Back behave as above on a phone; the same pages are used at a desk.

### Every window and section folds away and stays folded

Every window collapses and expands. Sections of a page can be folded away, and stay folded the next time that page is opened in the same browser. Every unclear control explains itself on hover, on keyboard focus and on touch (see "Every control and status mark explains itself"), and every explanation lies wholly on screen.

### Typefaces come with the product, and Chinese names show in a typeface that has them

Every typeface, icon and script a page uses comes from the studio's own server; nothing is fetched from the internet. Chinese folder, clip and person names always show in a typeface that can draw them.

### The maker's mark is on every window, and a studio may choose its own

By default the maker's current mark, in the brand colour, is on every window, popup, installer, taskbar entry, tray or menu-bar icon and browser tab. A studio may choose another (see "A studio can put its own logo on every icon and window"), and no update ever changes that choice.

The installed Timeline Cards app, on a computer or on an Android phone, carries the same mark (or the studio's own logo), with square and round versions for Android's launcher.


### Every app reached from the dashboard leads back to it

Every page of every part reached from the dashboard (the b-roll archive, music, YouTube downloads, Timeline Cards, the Footage Sorter, the help) shows a way back to the dashboard on every page, on a phone and at a desk.

### A phone can install a page as an app without signing in first

Where a page can be installed on a phone as an app, everything the phone fetches to install it (its description, its icon, and what lets it open offline) is reachable without signing in, while the pages and every piece of data behind them still need a sign-in (see The dashboard: Phones and the installed app).

#### Lessons

- Met: ALL-010, ALL-011, ALL-012, ALL-013, ALL-014, ALL-015, ALL-016, ALL-017, ALL-018, ALL-019, ALL-020, ALL-021, ALL-022, ALL-023, ALL-024, ALL-025, ALL-026, ALL-027, ALL-028, ALL-029, ALL-031.

## Wording

### Counts, sizes, times and lengths of time read the same everywhere

Every part of the product, on every screen and in every notification, writes these the same way:

| What | How it reads |
|---|---|
| A count | the right singular or plural with a verb that agrees: "1 clip is waiting", "3 clips are waiting"; never "clip(s)" |
| A size | B, KB, MB, GB, TB in steps of 1024, with one decimal above bytes: "512 B", "1.5 KB", "3.2 GB" |
| How long ago | "Ns ago" under a minute, then "Nm ago", "Nh ago", "Nd ago" |
| A time to come | in the future tense: "releases in 23 h", "in 5m" |
| A length of time or time left | "45s", "12m", "2h 05m", "3d 4h"; an estimate carries "~" ("~12m"), and an estimate under a minute reads "<1m" |
| Nothing to show | a hyphen, "-" |
| Progress whose total is not known | shown as not known, never as zero or as a full bar |

Every sentence that carries a time reads correctly whether the time is known or not: a time that does not exist reads as words that fit the sentence ("never synced", "not yet checked"), never as "since never" or "0s ago". A time that cannot be read is shown as it was written. Dates and times are shown and understood in the studio's own time zone (see "Dates are the studio's dates").

No text a person reads has a long dash or " -- ".

### One word for each idea and each action, everywhere

Each idea has one word, and each action one name, everywhere a person reads, in sentence case. The approved words include: computer, ticked, sync plan, paused, stopped by your admin, stopped itself, upload, proxy download, originals download, folder sync, express upload. The words for the kinds of movement are the same in the app on the editor's computer as on the dashboard. The product's own name is spelled one way in every sentence.

### The product speaks in the studio's name

Every value that differs between studios comes from the site's own settings: the studio's name and short name, the product name, the logo, the support contact, the drive letter, the names of the shared tree, the projects folder and the proxy folders, the language defaults, and the details for reaching the NAS. A new site shows no name, folder, drive letter, language default or example taken from another studio. A part that cannot honour a value the site has set refuses it and says so; it never quietly uses its own.

So, on an editor's computer:

- notification and dialog titles read "<studio short name>: <what it is about>", using the product name when the studio has no short name;
- the product name is the site's own, and "CC Sync" when the site has set none;
- messages say "the <studio short name> server" (or "the server") and "your <studio name> drive" (or "your studio drive");
- the logo is the site's when it has given one, otherwise the maker's mark.

In a browser, every tab title carries the studio's own name, the pages of the b-roll archive, music, YouTube downloads and the Footage Sorter included (see "Every browser tab carries the studio's name and the page's name").

A change to any of these reaches every computer with the rest of the site's settings (see "A change to the site's settings reaches every computer without a restart").

No text a person reads names a particular person of the studio or of the vendor: people are referred to by their role ("your admin"), except where a page shows who did something or who a computer belongs to.

### Every "contact support" line names a real contact

Wherever the product tells a person to send something to support or to contact support (a problem's fix, a mail, a help page, the end of setting something up), it names a real contact: the site's support contact, or the vendor's when the site has set none. A reseller or a site can put its own in place of the vendor's.

### Every message is a plain sentence that says what is known and what to do

- Every state, refusal and error a person reads is a plain sentence that names the cause and the next step. Internal codes, ids and raw error text are never the message; where they help, they sit one click away.
- A message states only what the product actually knows; it never claims a cause it cannot see. One event is worded the same wherever it appears.
- Every count says what it counts over ("3 of this computer's projects", "12 files across the studio"). Each distinct problem gets its own true sentence; several of the same show as one with a count.
- Nobody is told to ask themselves: an admin is never told "ask your admin".
- Every direction ("press Retry", "open Settings, then Sync") names a place and a label that exist and can be seen at that moment. A release in which a message points at something that is not there is not shipped.
- A message puts the useful fact first. When it must be shortened, it is shortened on purpose at a word, never cut by a length limit in the middle of a word.
- No raw error text and no path on an editor's own disk leaves that computer: what the server receives and shows is a plain sentence.

### Every control and status mark explains itself

Every control and every status mark (a chip, a tag, a light) carries a short explanation, which screen readers are also given.

- With a mouse, hovering shows it after a quarter of a second, beside the thing it explains and kept wholly on screen; the pointer may move onto it.
- With a keyboard, explained marks can be reached with Tab. Focusing a mark shows its explanation at once; focusing a button shows it after nearly a second, so tabbing along a row of buttons does not cover the next one. Escape or scrolling hides it, and it follows its control while the page scrolls.
- On a touch screen, every control with an explanation has a small "?" beside it that opens an explanation sheet with the control's name and text; tapping a status mark itself, or anything else that is not a control, also opens it. Enter or Space opens it from the keyboard. Tapping the sheet, tapping elsewhere or Escape closes it.

Wherever a word of the product's own appears (a state, a kind of transfer, a part's name), a person can reach plain help on it from there. When the help is not on the server, the page says "Help is not installed" in its place.

### Copy buttons say whether the copy worked

Wherever a value is meant to be copied (a one-time password, a computer's fresh sign-in key, a checksum, a device id), a Copy button copies it. The button then reads "Copied" for 2 seconds. If copying is not possible but the value can be selected, it is left selected and the button reads "Selected: press Ctrl+C" (the same words on a Mac); otherwise it reads "Could not copy". Copying works whether the page was reached by a secure address or not.

### Messages name the assistant one way, and nothing it makes carries a product's name

Every message that mentions the assistant names it the way the product shows it on screen, the same everywhere, and no message names a program the person never meets. Documents the product or the assistant creates (a cut list, an export, a script, a report) are named by episode and version only, never with the assistant's name or a product name in the title.

#### Lessons

- Met: ALL-032, ALL-033, ALL-034, ALL-035, ALL-036, ALL-037, ALL-038, ALL-039, ALL-040, ALL-041, ALL-042, ALL-043, ALL-044, ALL-045, ALL-046, ALL-047, ALL-048, ALL-049.

## Safety in what the product does

### Only the studio's own dashboard can make the app on an editor's computer act

Pages of the dashboard ask the app on the editor's own computer to do things there (send a clip or a track to the editing program, show a file in the file manager, report whether the editing program is open). The app answers only two kinds of caller: programs run on that same computer by its own user, and web pages served from the studio's dashboard address, as set on that computer or as the server last announced it, whether reached by its plain or its secure form. A page from any other site, a page that does not say where it comes from, or a request that pretends to come from a different address is refused. Asking whether the app is there and working needs no page; anything that changes something needs the dashboard's page or a program run by the computer's own user.

Every refusal reads "this request was refused by the CC Sync app on this computer", followed by the advice to open the app's log, or to copy the app's diagnostics and send them to the admin; the reason itself is in the log.

If the dashboard address known to the computer is not the address editors actually browse to, every send to the editing program is refused this way. An admin or the editor puts it right by correcting the address, or by adding the other address the dashboard is reached by (see The app on each editor's computer: Settings, records and background work). When the server announces a new address, every app follows it within about 30 seconds, without a restart.

- Who: refusals reach whoever pressed the button; the address is set by an admin or the editor at that computer.

### A page can name only files inside the studio's libraries

Every file a page asks the app on an editor's computer about is named as one of the studio's libraries (the b-roll archive, music, the projects, YouTube downloads) plus a place inside it, never as a place on the disk. A name that climbs out of its library, starts from the top of a disk or a drive letter, or follows a link out of the library is refused, with the reason. When a library has no place on this computer, the answer is "this computer has no place set for the <library> library". Showing a file in the file manager never opens an application, an installer package or anything else the system would run instead of showing.

- Windows and macOS: on a Mac, an application or installer package is shown in its folder, never opened.

### Nothing that carries a sign-in crosses the public internet unencrypted

Every call from an editor's computer to the server that carries a sign-in (reports, signing in, the site's settings, what the computer syncs, shared work, Footage Sorter copies, downloading an update) follows one rule:

- It is refused before anything is sent when the server's address is plain http and every address the name leads to is on the public internet. The error reads "not sent: <host> is plain http on the public internet; use the dashboard's https address".
- Plain http is allowed to the computer itself and within the studio's own network: private addresses, the studio's private remote-access network, a one-word name, names ending in the studio network's own or local endings, test names, a name that does not resolve, and any name that leads to at least one private address. A number written without dots is read as the address it stands for, so it cannot pass as a local name.
- A secure address is always checked against the certificates the computer trusts, and nothing turns that check off.
- When the server's address answers by sending the call somewhere else, the call counts as failed and is not followed, so a sign-in is never carried anywhere but the server.

On the server's side, the dashboard warns an admin when a computer reaches it unencrypted over the public internet (see The dashboard: Security of pages).

### Every question before an action looks and behaves the same

Any action that stops syncing, deletes, withdraws access, signs anyone out, or affects every computer asks first, and its button looks unlike harmless controls. Every such question, everywhere in the product, appears in the same dialog of the product's own:

- titled "Are you sure?", with the full question stating what will happen;
- a "Cancel" button, which has the focus, so Enter or Escape alone never confirms, and "Yes, do it";
- Cancel or Escape sends nothing and puts back any tick box that had already flipped;
- while the question is open the page does not refresh;
- if the control was redrawn while the question was open, it is found again and the action is sent once; if it can no longer be found, the dialog says "This changed while you were reading; nothing was sent." with only a close button.

Screen readers hear the whole question. The questions on the editor's computer follow the same rules in its own windows.


### Nothing removes footage on its own

No action the product takes on its own deletes an original or any file on the server. Anything removed from an editor's own computer is either that person's explicit choice, asked for with a question that names it, or can be got back for a time.

### Opening a tool never starts its work

Opening any tool, page or window that can change a project or files shows it idle. Nothing is processed until a person presses its button to run it, drops files onto it, or has set it to run on its own (as footage dropped into Timeline Cards processes itself).

### Every way of doing something keeps the same safety rules

Where one kind of action can be done from more than one place (removing, moving, unticking, stopping), every place obeys every safety rule of that action: the same question, the same refusals, the same protection of footage. Each rule is tested in each place before a release.

### One bad item never stops the rest

When work runs over many items (files, clips, tracks, computers), one item that cannot be done is recorded with its reason and skipped, and the rest carry on. The person sees how many were done and which were not, and why.

### Every setting is a control in the product

Every setting an editor or an admin may need is a control in the product. No message tells anyone to edit a file, type a command, or reinstall the server. A value of zero or less for something that must be positive (a port, a length of time) is refused when typed, or, where it arrives from elsewhere, replaced by the default, and the person is told which setting was replaced and with what.

### An interrupted save never loses a computer's settings

Every save of settings, secrets or a computer's identity either completes whole or leaves the previous version in place, so a crash, a power cut or a full disk in the middle of a save never resets a computer to its defaults or forgets who it is. A damaged settings record is recognised as damaged and reported, never read as valid.

#### Lessons

- Met: ALL-062, ALL-063, ALL-064, ALL-065, ALL-066, ALL-067, ALL-068, ALL-069.

## Windows, text and names

### A studio can put its own logo on every icon and window

Every icon of the product comes from one mark: the tray or menu-bar icon, the icons of the installed programs and their windows, the dashboard's browser-tab icons, the phone home-screen icons (including ones a phone may crop to a circle or a rounded square), and the icons of the b-roll archive and the other parts. At small sizes the mark is drawn stronger so thin strokes stay visible. By default it is the maker's mark.

A studio can give its own logo, which every computer of the studio shows, without anyone reinstalling. There is one logo for the whole studio; no computer carries a different one. The logo must be white on a transparent background; a coloured logo comes out as a solid shape in the colour of the state it shows. The tray icon and every window's icon change together. On Windows, notifications are headed with the site's product name ("CC Sync" when none is set) and the mark.

- Who: an admin.

### Every browser tab carries the studio's name and the page's name

Every page's browser tab reads the studio's short name in capitals, a colon, and the page's name: "STUDIO: SYNC STATUS". When the studio has no short name, the first that is set of these is used: its full name, the product name the site has set, then "CC Sync". This holds for every part's pages too. The dashboard's own title reads "<studio's name> - <product name> Dashboard", or "CC Sync Dashboard" when no studio name is set. Every page carries the product's icon for a browser tab and for a phone's home screen.

### Names in any script work everywhere

Computers, people, folders, projects, clips and other studios' computers named in any script (Chinese, accented Latin, Cyrillic, anything else) work everywhere the name travels: in the tree, in every list, in search, in messages, in what is shown on another computer, and in what is handed to the editing program. In particular:

- writing a record of what happened or showing a message that holds such a name never stops a piece of work, whatever language the computer's own system is set to;
- text exchanged with other programs is read as the standard encoding that holds every script, characters that cannot be read are replaced rather than dropped, and text that cannot be read at all is reported, never taken as empty;
- a settings file the product reads is accepted with or without the invisible mark some Windows programs put at its start, and the product never writes that mark;
- long text (a whole transcript, a long list of files) handed to another program on the same computer is never cut short or refused because of its length.

### A folder is the same folder however it is spelled

Two spellings of the same place are treated as the same place, including a short form of a Windows folder name and its long form. "Is this inside that folder" compares whole folder names, so "Luts Local" is never inside "Luts".

### Names that would reach outside the studio's tree are refused

Any folder or file name typed by a person or received from anywhere is refused, with the reason, when it would end up outside the studio's tree or would be the folder itself ("..", a name starting from the top of a disk, a drive letter, a link that leads out).

### Showing a clip in the file manager selects it

"Show in Explorer" (or in Finder on a Mac) opens the folder that holds the clip with the clip selected, also for names with spaces, brackets and non-Latin letters. That the right folder opened with the right clip selected is checked against the window that actually opened.

- Windows and macOS: Explorer on Windows, Finder on a Mac.

### Every file picker on Windows is the full system dialog

Every place where a person picks a file or folder on Windows opens the full system dialog, with an address bar into which a path can be typed or pasted.

- Windows and macOS: on a Mac the system's own picker is used.

### Paths shown on a web page are written for every computer

A page served from the server shows a file's place relative to the studio's tree, with forward slashes and no drive letter, saying it is "under your sync drive", so the same line is right for an editor on Windows and on a Mac.

### Dates are the studio's dates

Every date and time a person enters or reads is understood in the studio's own time zone, so the date a person sees is the studio's date at any hour (see The server: installing it and keeping it running: Settings and secrets). A file or folder with a date that cannot be true (for example far in the future) shows a plain placeholder date and never hides or breaks any other row. Nothing is told apart by its time alone, and where a limit counts recent events (for example how many restarts in an hour), a time in the future counts as recent.

#### Lessons

- Met: ALL-070, ALL-071, ALL-072, ALL-073, ALL-074, ALL-075, ALL-076, YTD-092, ALL-077, ALL-078, ALL-079, ALL-080, ALL-081, ALL-082.

## Requests, logs and outside programs

### Pages need nothing from the internet

Every typeface, script and icon any page uses is served by the studio's own server. A studio whose network has no internet access still sees complete, correctly drawn pages, and no page reaches out to anyone else while a person reads it. Only features whose whole job is outside (YouTube downloads, the assistant) need the internet, and they say so when it cannot be reached.

### An admin can always find out what happened and when

The server and every editor's computer keep a record of what they did and what went wrong, with the time of each entry. An admin can always read it: the server's from the dashboard, and each computer's from the app on that computer or as diagnostics the editor sends. Each record is kept to a size limit on every machine, yet always holds at least the last day. When older entries are dropped to keep within the limit, the record says that older entries were dropped and from when.

A condition that repeats is recorded when it starts, when it changes and when it ends, and is quiet in between, so a whole day of the same condition costs a handful of lines and never buries anything else.

- Who: an admin.

### No secret is ever shown, recorded or sent where a person could read it

No password, key, sign-in code or token is ever shown in full after it has been entered, written into any record of what happened, put in a web address, published in the site's settings, or included in a message, a mail, a problem's text or diagnostics. Where a page must show that a key is there, it shows only its first 3 and its last 4 characters around an ellipsis ("abc…wxyz"), and only an ellipsis for a short key. A secret shown once, by design (a one-time password, a computer's fresh sign-in key), is shown once with a Copy button and never again. When the product quotes another program's words (an error, a sign-in message), anything that looks like a secret is removed first. A refused secret is never quoted back.

### Nothing runs on a computer that its person or the vendor did not put there

The product only ever runs what the vendor ships in it, and programs a person chose to add, by pressing a button that names what will be fetched and from where. Every program the product fetches from outside is pinned to a version and to its publisher's own checksum, and is checked before it is unpacked or run. When the publisher gives no checksum, the program is refused and nothing is installed. The same program, byte for byte, may come from a second place. A failed or refused fetch leaves whatever was there before still working.

### A request the server cannot accept gets a plain refusal, never a crash

Every request to the server, and to the app on an editor's computer, has a size limit. A request that is too large or badly formed gets a clear refusal, which the computer that sent it treats as final rather than trying again; it never crashes the server or the app, and never comes back as an error that invites a retry.

### Editors' computers never wear the server down

Each kind of regular contact from an editor's computer keeps its own least interval between tries and backs off when the server is slow or refuses, whatever the server answers, so a server that answers at once is never hammered. A computer waiting for something to happen never ties the server up while it waits.

#### Lessons

- Met: ALL-083, ALL-084, ALL-085, ALL-086, ALL-087.

## The assistant

### One switch turns the assistant off for the whole site

An admin can switch the assistant off for the whole site. With it off, nothing in the product calls an assistant, and no assistant control is left on any screen: no button, panel, picker, setting, chip or message about it, on the dashboard, in any part, or on an editor's computer. Everything else keeps working. Each part says what it does instead where the assistant would have helped (see the parts' own pieces). Switching it off deletes nothing: connected assistants, keys, conversations and the house style are kept, and switching it on again brings everything back as it was. The change reaches every screen within a minute.

- Who: an admin.
- Setting: The assistant. Does: switches every use of the assistant on or off for the whole site; off removes every assistant control from every screen. Default: on (nothing is answered until an assistant is connected). Who: an admin. Applies to: the site. Search words: assistant, AI, switch off, disable assistant, AI off.
- Name and search words: The assistant. Search words: assistant, AI, key, connect, provider.
- When the assistant is off: the rest of this section is not shown to anyone, admins included, except the switch itself.

### A site connects the assistant with its own paid key

The assistant is never shipped with the product. The usual way for a site to connect one is a key it has bought from the assistant's maker, paid per use; a site may instead switch on a subscription signed in on the server (see "A site may instead connect an assistant through a subscription signed in on the server"). Every assistant call the site makes is charged to the site's own key or subscription, so what the assistant costs is the site's own, and any spending limit on the maker's side is set there.

An admin adds a key in three guided steps, "get a key", "paste it", "test":

1. **Get a key.** The maker's own instructions, a link to the maker's site that opens in a new tab, what is needed, what it costs, what a key looks like, and a note that any spending limit is set on the maker's side.
2. **Paste it.** A hidden key box and "Save key". Before anything is sent the key is refused, without being quoted, when it is blank ("the key is blank"), over 512 characters, holds control characters ("paste it again"), or holds a space ("the key contains a space: paste the key alone, with no 'Bearer' prefix"). Once saved: "Stored as <masked key>." The step says that the key is kept on the server, readable only by the product, and never shown again except masked. Next is offered only after a save.
3. **Test.** "Test key" makes one real call and shows OK or FAILED with how many seconds it took, then where this assistant sits in the site's order and whether it now answers ("It answers from now on" or "<other assistant> still answers first"), and, when it cannot do some features (see "A feature that needs the assistant says plainly when it cannot be used"), which ones.

Back, Cancel ("Closes this without going further. Anything already saved stays saved.") and Next or Finish are always offered, and what was typed survives the page redrawing. A stored key can be replaced (straight to step 2) or removed, after the question "Remove the stored <name> key from this server? Features that use it will move to the next connected assistant, or stop if there is none."

A key given when the server was installed always wins over one entered here. It is shown as "set when the server was installed" and cannot be changed, saved over or removed from the page ("a key saved here would never be used").

- Who: an admin.
- When the assistant is off: not shown.

### A site may connect more than one kind of assistant and pin one

A site may connect several kinds of assistant. They sit in a fixed order of preference, shown to the admin in that order. Unless an admin pins one, every feature uses the first in the order that is ready (a key entered and accepted, or a subscription program installed and signed in), and the reason given names the ones it was chosen ahead of. An admin can pin one ("auto: first available in the order" or the pinned one). A pinned assistant that is not ready is a refusal, never a quiet fallback: "<name> is pinned but not available. Nothing else will be used in its place: clear the pin to fall back to the order." A pin that cannot be set puts the choice back and says "could not pin: <reason>".

The assistant settings show:

- at the top, "pinned to <name>", "pinned, not available" or "auto: first available";
- the connected assistants, "<n> of <total> set up · in order", each with its place in the order, its name, its state, its last test, its key masked and whether it was set when the server was installed or entered here, and what it is used for, standing by for, or not used for and why;
- for each feature that uses the assistant (YouTube search and relevance, Timeline Cards' search by meaning, summaries and edit chat, the server's own check-up), who answers it and why, or that nothing does and why;
- "+ add new", listing the kinds not yet connected ("<n> more you can set up: <names>", or "All are set up."), each with what it is and what it needs;
- per assistant: Test, Pin as preferred or Unpin, Replace key, Remove.

With none connected: "No assistant is connected.", saying that the YouTube downloader cannot search, Timeline Cards' assistant features do not work, the server's check-up mails a plain summary, and that adding a key takes a minute. A failure to read the settings says "could not read the assistant settings: <reason>". Some kinds of assistant can answer only some features (for example only YouTube search); the help says which.

- Who: an admin.
- Ways in: the assistant settings (see The dashboard: Settings and setup).
- When the assistant is off: not shown.

### An admin tests each assistant and sees its state

Each connected assistant shows one state, each with an explanation: available, not configured, not signed in, switched off for this site, or unknown. A state can be up to ten minutes old; one not freshly checked is marked "(not re-checked since <time>)". Finding out a state never costs a call to the assistant.

Test makes one real call, which answers within 20 seconds, and reads "testing…", then "test ok, <s>s" or "test failed, <s>s" with the reason: "<name> accepted the key", "no key is configured", "the key was refused", another refusal from the maker in words, or that the maker could not be reached from the server.

- Who: an admin.
- When the assistant is off: not shown.

### A site may instead connect an assistant through a subscription signed in on the server

A site may connect an assistant by a personal subscription instead of a key: the maker's own program is fetched to the server and signed in with the subscription. This way is off for every site until an admin switches it on by accepting a notice. While it is off such programs are never run, their rows say only that the site has not allowed them, and pinning one is refused.

The notice, titled "This uses YOUR subscription, on a shared server", says that every use by every person (every YouTube search by every editor, every Timeline Cards question) is spent on the signed-in account; that using a personal subscription to power a shared service may breach its terms, and that this is the site's decision, not the vendor's; that CC Sync ships nothing and fetches the maker's own program from the maker's own servers only when the admin presses Install, checked against the maker's own checksum; and that a key is the supported way. The admin ticks "I understand this uses my own subscription for a shared server" before Next is offered.

The set-up has four steps, starting at the first one not finished: allow, install, sign in, test.

- **Install** (or Update, or Try again): "From <maker>, checked against its published checksum before anything runs. It goes into this server's data folder and nowhere else." Progress reads "<step>: <MiB> of <MiB> (<n>%)". It ends "installed: <version>", "interrupted: <reason>" or an error. Before anything is fetched it is refused, saying why, when the server's system, processor or variant of the system is not one the program supports, when the server cannot write where it keeps the program, or when there is too little space. A program whose maker publishes no checksum or size for it is refused: "the publisher published no checksum, so this install cannot be verified and was not done." Every failure says "Nothing was installed" and leaves any earlier version working; an install cut off by a restart says so and invites a fresh start. One install runs at a time. An admin who installed a copy themselves can type its full path ("blank = search the usual places"), and that copy then always wins.
- **Sign in**: a choice of account type where the maker offers one (subscription or pay per use), a button that opens the maker's own sign-in page in a new tab, a short code to type there, and a box to paste back the code that page gives (refused when blank, "that code is blank", over 512 characters or holding control characters; never stored or shown). It shows "waiting for the sign-in to finish (<n>s left)" with a Cancel button, and gives up after 5 minutes ("the sign-in was not finished within 5 minutes and was stopped"). One sign-in runs at a time. Success is confirmed by asking the program, then shows "Signed in as <account>" with the e-mail masked to the first and last letter of the name and the domain, plus plan and organisation where known, and a Sign out button. A sign-in survives the server restarting; one that has expired and cannot renew itself says "Sign in again".
- **Test and finish**: the version, whether it is signed in, Test, and its place in the order. Checking that such a program is signed in makes one tiny real request, charged to the subscription. Its test answers "answered (<version>)", "not installed: press Set up to install it from the maker, or give the full path of a copy you installed yourself", or "installed but not signed in: press Set up and finish the sign-in step".

Afterwards each such program offers: Sign out (or "Finish setting up: sign in"), Update (only for a copy installed here), "Use my own copy" or "Change its path", and Remove (only for a copy installed here, refused while it is installing: "Remove <name> and its sign-in from this server? Features that use it will move to the next connected assistant, or stop if there is none."). The way is switched on in one place only, by accepting the notice in the set-up, and an admin switches it off again from the same set-up; switching it off closes any set-up that is open and stops every such program being run, deleting nothing.

When the site allows it and an admin turns it on, the server keeps a copy it installed up to date by itself: about five minutes after starting, then at most once a day, it installs only a strictly newer version, with the same checks as an install by hand, never while another install runs, and never for a copy at a typed path. When such an update fails, admins see a warning naming the installed and newest versions and the reason: "Timeline Cards keeps working on the version it has, but a newer assistant may be refused until it is updated." The fix is to update it from the assistant settings.

The program never sees the server's other secrets or keys.

- Who: an admin.
- Setting: Subscription assistants. Does: allows the site to connect an assistant through a personal subscription signed in on the server. Default: off. Who: an admin, by accepting the notice in the set-up. Applies to: the site. Search words: subscription, sign in, assistant program, personal plan.
- Setting: Keep subscription assistants up to date. Does: lets the server install a newer version of a program it installed, once a day. Default: off. Who: an admin. Applies to: the site. Search words: update assistant, automatic update, program version.
- When the assistant is off: not shown.

### An admin is told when the site's assistant stops working

When the assistant the site relies on can no longer be used (a key refused, a program signed out or no longer runnable, a pinned assistant gone), admins see a problem on the overview naming which assistant, what is wrong, what is affected, and what to do. It clears by itself once the assistant works again or the setting that relies on it is removed.

- Who: admins.
- When the assistant is off: no such problem is raised.

### What the assistant costs is shown before it runs, and a site can cap it

Every assistant task a person starts shows what it is expected to cost before it runs. Routine work over a whole project or archive (describing clips, lining up a whole episode) stays within a cost the site sets, and says so when it would go over.

A site can also cap what the assistant spends in a day, in money. Once the day's budget is spent, new runs are refused and anyone waiting is told at once: "today's assistant budget of $X is spent; try again tomorrow, or ask an admin to raise it". Raising the budget lets waiting work carry on at once. The assistant settings show what has been spent so far that day against the budget. The day is the studio's own day.

- Setting: Assistant budget per day. Does: the most the site's assistant may spend in a day before new runs are refused. Default: no limit. Who: an admin. Applies to: the site. Search words: budget, spend limit, assistant cost, daily cap, AI cost.
- When the assistant is off: not shown.

### A run of the assistant is limited and always ends with a sentence

- When too many runs are waiting: "the assistant is busy with other requests; try again in a moment"; a run that waited too long is told it "did not get a turn within N s".
- A run is stopped after 15 minutes ("did not answer within N s, so the run was stopped"), when it writes far more than an answer, or when it takes more steps than its task allows.
- A run asked for a particular kind of answer that does not give one is told so in words.
- A cancelled run says "stopped", and stopping a run stops everything it started.
- The answer appears on the page as it is written.

The assistant is given no power to change files, run commands or browse, except where a feature needs one particular power for its job, and then only that one.

### Work waiting for the assistant goes in order of who is waiting

Work for the assistant is done most urgent first: what a person is waiting for, then what is on a screen, then background work, and oldest first within each. Work a person waits for is never dropped; when no more can be accepted, the person is told "too much work is queued already; try again in a moment". A person who leaves withdraws their own request. When the assistant or something it needs cannot be reached, waiting people are told at once, and the work is tried again a minute later. A piece the answer left out is asked once more on its own, then fails "it was left out of the answer". Waiting work survives the server restarting and carries on; people waiting when it stops are told "the server is stopping".

### A feature that needs the assistant says plainly when it cannot be used

Whether the assistant can be used is worked out once, without a call that costs anything, and shown on the page; checking never stops the page from updating. Every button that needs the assistant is then dimmed, with a one-sentence reason on hover, focus or tap:

- no assistant connected: "no assistant has a working key", with where an admin connects one;
- the connected assistant cannot do this feature: Timeline Cards' search by meaning, section summaries, montage conversations and edit chat work only with the kind of assistant they were made for, so with another kind they say "this site's assistant is <name>, and Timeline Cards' search by meaning and summaries need <the assistant they were made for>", telling the admin to connect it or pin it in the assistant settings; the YouTube downloader works with any kind;
- not yet checked on this server: the admin should test it in the assistant settings;
- slow to start: "the server is busy starting the assistant: try again in a minute";
- signed out: "an admin must sign it in again".

When a request fails, the person is told in words, never with a crash: the assistant could not be asked, it failed (with its own words, any secret removed), it answered with something that was not a result, it refused a key, it no longer offers what was asked for, it did not answer in time, or "the assistant refused, and said why in no words at all". The name of the assistant that answered is remembered and shown. When cards are selected in the editor, the selection travels with the question.

- When the assistant is off: none of these buttons are shown.

### A person picks how strong an assistant answers, where offered

Where Timeline Cards lets a person choose (the transcript search panel and the edit chat), three strengths are offered: "fastest", "stronger" and "most capable", each with a short note that also carries its price to the site where the price is known. Each panel says which is its default: transcript search defaults to the fastest, the edit chat to the most capable. Summaries, the montage builder and search inside one transcript always use the fastest.

When the maker offers a newer version of one of the three strengths, the choice moves to it by itself, never to anything older than the version the product came with; its label then shows the new version, and its note drops the price when no price is known for it. Looking for newer versions never makes a person wait; until an answer comes, or when it fails, the last known versions stay. A request naming a strength the product does not recognise gets that feature's default; nothing is ever refused for a bad choice.

- When the assistant is off: no picker is shown.

### A conversation with the assistant is kept per cut list

A feature that talks with the assistant (the edit chat, transcript search) keeps one conversation per cut list, so later questions build on earlier ones without the assistant reading everything again. It is saved after every finished turn and survives the page reloading and the server restarting; a cut list brought back from its history keeps its conversation. A conversation with no cut list open lasts until the server restarts.

A new conversation starts when the transcripts it was given change, when the person presses "new conversation" or "start over", and when they switch strength: each strength holds its own conversation, and switching opens that strength's, which first reads the material again, slowly and at that strength's price. When a strength moves to a newer version, the open conversation carries on.

When the assistant no longer knows a conversation (for example on a server set up afresh), the feature opens a new one once, reading the material again, and says so on its status line; it never retries silently. A remembered conversation that is missing or damaged simply starts a new one at the next turn.

- When the assistant is off: no conversation is offered and none is lost.

### The studio's website can ask the assistant to name a piece of gear from a photo

The studio's own public website can send the server a photo of a piece of gear (under about 2 MB) with the studio's list of gear categories (up to 40), and gets back a suggested packing-list entry: name, category, weight in grams of one item, quantity (1 to 99), a one-line note, and how sure it is (high, medium or low). The website must send the site's gear code, which an admin copies from the dashboard and which changes whenever the server's own secret is renewed; a wrong code is refused. It uses the site's assistant as chosen and pinned, and is refused while the assistant is off. Errors say that no assistant is connected, that it stopped, that it gave no usable answer, or that it did not answer within 120 seconds. Photos are handled one at a time.

- Who: the studio's website, holding the gear code.
- When the assistant is off: every request is refused, saying the assistant is off for this site.

#### Lessons

- Met: ALL-088, ALL-089.
