# Joins aimed at whole-product

## Checked

- J1 | F1
- J2 | fine
- J3 | F2
- J4 | F3
- J5 | fine
- J6 | F2, F4
- J7 | F7
- J8 | F4, F5, F6
- J9 | fine
- J10 | fine
- J11 | F8
- J12 | F9
- J13 | F10, F11
- J14 | F12, F13
- J15 | F14

## Findings

### F1: The assistant's conversations are kept for good while it is off, or deleted after the keeping period
- Kind: contradiction
- From: accounts-privacy-legal / How long the product keeps each kind of record
- Here: The assistant / One switch turns the assistant off for the whole site; A conversation with the assistant is kept per cut list
- From says: "Records of conversations with the assistant | 30 days, or the period the site sets" and "When the assistant is off: nothing new is recorded, and what was recorded is still deleted on time."
- Here says: "Switching it off deletes nothing: connected assistants, keys, conversations and the house style are kept, and switching it on again brings everything back as it was." and "When the assistant is off: no conversation is offered and none is lost."
- Settled by: ACC-050 (a situation, weaker): "Every stored transcript and assistant record is deleted after a site-set period"
- Fix: whole-product should say that conversations, like every assistant record, are still deleted after the site's keeping period while the assistant is off, and that a cut list's conversation lasts at most that period.

### F2: Section summaries and the montage builder always use the fastest strength, or follow the edit chat's chosen strength
- Kind: contradiction
- From: cards-editor-4 / Which strength of assistant each feature of the editor uses, and what it costs
- Here: The assistant / A person picks how strong an assistant answers, where offered
- From says: "The montage builder and section summaries use the same choice, so no assistant feature of the editor runs at a strength the person cannot see and change."
- Here says: "Summaries, the montage builder and search inside one transcript always use the fastest."
- Settled by: decisions page 27, 27.2, answered 2026-11-24 with the recommendation: "A: every assistant feature in the editor (shortening, montage builder, summaries) uses the strength chosen in the chat panel; search keeps its own."
- Fix: whole-product should say summaries and the montage builder follow the edit chat's chosen strength (only search inside one transcript stays on the fastest).

### F3: The transcript search's conversation is kept per cut list, or per episode and goes cold after an hour
- Kind: contradiction
- From: cards-editor-3 / The search sheet has pickers for which transcripts, how many results, which strength of assistant, and a fresh start (and the same piece's conversation rules)
- Here: The assistant / A conversation with the assistant is kept per cut list
- From says: "One conversation per episode, chosen transcripts, strength and kind, shared by every browser working on that episode. It stays warm while it has answered at least once, the transcripts have not changed, and it was last used under an hour ago, also across a restart of the server."
- Here says: "A feature that talks with the assistant (the edit chat, transcript search) keeps one conversation per cut list" and "A conversation with no cut list open lasts until the server restarts."
- Settled by: OWNER_REQUIREMENTS section 4: "In the Timeline Cards editor, everything a person sees and touches ... Where this specification marks a passage `Exact`, it is to be built as written."
- Fix: whole-product should drop transcript search from the per-cut-list rule and point to Timeline Cards' transcript search for how its conversations are kept (per episode, scope, strength and kind, cold after an hour).

### F4: Routine assistant work has a cost cap of its own besides the one daily budget
- Kind: differs
- From: cards-editor-4 / Which strength of assistant each feature of the editor uses, and what it costs
- Here: The assistant / What the assistant costs is shown before it runs, and a site can cap it
- From says: "Each counts against the site's one daily budget for the assistant ... No feature of the editor has an allowance of its own."
- Here says: "Routine work over a whole project or archive (describing clips, lining up a whole episode) stays within a cost the site sets, and says so when it would go over."
- Settled by: decisions page 3, 3.6, answered 2026-11-24: "one daily budget in money, with the expected cost shown before each task."
- Fix: whole-product should say routine work over a project or archive counts against the one daily budget, not a separate "cost the site sets".

### F5: When the day's budget is spent, new runs are refused, or footage-in's work waits for the next day
- Kind: contradiction
- From: cards-footage-in / Footage-in works most urgent first, within the site's daily budget
- Here: The assistant / What the assistant costs is shown before it runs, and a site can cap it
- From says: "Footage-in never fails for lack of budget: when the day's budget is spent, that work waits ... and the work carries on by itself when the new day's budget opens."
- Here says: "Once the day's budget is spent, new runs are refused and anyone waiting is told at once: \"today's assistant budget of $X is spent; try again tomorrow, or ask an admin to raise it\"."
- Settled by: decisions page 31, 31.3, answered 2026-11-24: "No share ... it may spend the whole day's budget, then waits for the next day."
- Fix: whole-product should say that runs a person starts are refused with the budget sentence, while work running on its own waits and carries on when the next day's budget opens.

### F6: With the assistant off, footage-in shows a message naming the assistant
- Kind: contradiction
- From: cards-footage-in / Footage-in works most urgent first, within the site's daily budget
- Here: The assistant / One switch turns the assistant off for the whole site
- From says: "When the assistant is off or unavailable, lining up stands still with \"Assistant is not available on this server (<why>)\""
- Here says: "no assistant control is left on any screen: no button, panel, picker, setting, chip or message about it"
- Settled by: OWNER_REQUIREMENTS section 2: "One site-wide switch turns the assistant off. Everything else still works, and no assistant control is left on any screen."
- Fix: cards-footage-in should keep that sentence for an assistant that is on but unavailable, and for "off" use its own other passage (the English and word links are left for a person and each interview says which, with no mention of the assistant).

### F7: When the site's switches cannot be read, the editor shows every tool, but the product's rule is that optional features count as off
- Kind: contradiction
- From: cards-editor-5 / The editor shows only the tools the site has switched on
- Here: The rebuild itself / A change to the site's settings reaches every computer without a restart
- From says: "If the server cannot be asked, nothing is taken off."
- Here says: "When the copy cannot be read, every optional feature counts as off and every switch on what a computer reports counts as on, the safe side in each case"
- Settled by: the owner must say: when the Timeline Cards editor cannot learn the site's switches, should it show the assistant and Resolve tools or hide them until it knows?
- Fix: whichever he chooses, both pieces should state the same side, with whole-product saying whether its rule covers the editor in a browser as well as the app on each computer.

### F8: The Footage Sorter's Ask and footage-in's English and first sort are missing from the list of features that use the assistant
- Kind: missing
- From: footage-sorter-and-camera-cards-3 / The assistant searches on a person's behalf and shows every search it ran
- Here: The assistant / A site may connect more than one kind of assistant and pin one; A feature that needs the assistant says plainly when it cannot be used
- From says: "Asked a question in ordinary words, the assistant runs searches of the archive for the person and answers with results."
- Here says: "for each feature that uses the assistant (YouTube search and relevance, Timeline Cards' search by meaning, summaries and edit chat, the server's own check-up), who answers it and why" (nothing on the Footage Sorter's Ask, footage-in's translation, line-up and first sort, or the board)
- Settled by: the owner must say: can the Footage Sorter's Ask and footage-in's translation and first sort be answered by any kind of assistant the site connects, or only by the kind Timeline Cards' features were made for?
- Fix: whole-product should add these features to the assistant settings' per-feature list, to the "No assistant is connected." sentence and to the list of features only one kind can do, per his answer.

### F9: Music's failure line tells an admin to tell their admin
- Kind: contradiction
- From: music / A failed search or browse says why, and a late answer never replaces a newer one
- Here: Wording / Every message is a plain sentence that says what is known and what to do
- From says: "Try again, and if it keeps happening tell your admin what this line says."
- Here says: "Nobody is told to ask themselves: an admin is never told \"ask your admin\"."
- Settled by: ALL-043 (a situation, weaker): "nobody is told to ask themselves"
- Fix: music should end the line differently for an admin (for example pointing at the overview's list of problems or support), keeping "tell your admin" for others.

### F10: The switch for the parts is one setting under two names
- Kind: differs
- From: server-install-and-running-1 / A part switched on but missing something it needs says so
- Here: The rebuild itself / An admin switches each part on and off for the whole site
- From says: "Setting: Which parts are on. Does: switches each optional part on or off for the site; see The whole product."
- Here says: "Setting: Switchable parts. Does: switches each of the six parts ... on or off for everyone."
- Settled by: OWNER_REQUIREMENTS section 1: "One way to do each thing: ... one place a setting comes from"
- Fix: server-install-and-running-1 should drop its own Setting line and point to whole-product's "Switchable parts".

### F11: A part that is on but cannot work is taken out of the menu, or shown saying it has nothing to serve
- Kind: contradiction
- From: server-install-and-running-1 / A part switched on but missing something it needs says so
- Here: Could not check, refusals and nothing silent / A part that is missing or broken never stops anything else
- From says: "Timeline Cards on with no place for its data: it says it has nothing to serve"
- Here says: "A part that started but cannot work (for example, it cannot write where it keeps its records) is taken out of the menu rather than shown broken, and an admin sees why on the list of problems and beside its switch in settings."
- Settled by: OWNER_REQUIREMENTS section 2: "Editors never meet a dead tab or a greyed control."
- Fix: server-install-and-running-1 should say such a part is out of the menu and the admin is told on the problems list and beside its switch, not that the part itself says it has nothing to serve.

### F12: "No assistant connected" is worded three different ways
- Kind: contradiction
- From: youtube / The assistant behind search is the one the site has set up, and every failure is explained
- Here: The assistant / A feature that needs the assistant says plainly when it cannot be used; An admin tests each assistant and sees its state
- From says: "\"this site has no working Assistant. An admin must set one up in settings. Until then no job can generate search terms.\"" and "\"Assistant is not enabled for this site\""
- Here says: "no assistant connected: \"no assistant has a working key\", with where an admin connects one" and the state "switched off for this site"
- Settled by: ALL-044 (a situation, weaker): "one event is worded the same everywhere it appears"
- Fix: whole-product should give the one sentence for "no assistant connected" and for "not allowed on this site", and youtube should use those sentences.

### F13: YouTube's re-check of the assistant spends a paid call, but finding out a state never costs one
- Kind: contradiction
- From: youtube / The assistant behind search is the one the site has set up, and every failure is explained
- Here: The assistant / An admin tests each assistant and sees its state; A feature that needs the assistant says plainly when it cannot be used
- From says: "re-checked on its own at least every five minutes until it passes. Only the assistant the admin chose is ever checked, so no paid call goes to one that will not be used."
- Here says: "Finding out a state never costs a call to the assistant." and "worked out once, without a call that costs anything"
- Settled by: YTD-100 and YTD-102 (situations, weaker): the re-check every five minutes, and no paid call to an assistant that will not be used; neither needs the check to be a paid call
- Fix: youtube should say its five-minute re-check costs no call (only Test and real searches do), matching whole-product.

### F14: Every fetched program is pinned to a version, but YouTube's downloader moves to its newest build by itself
- Kind: contradiction
- From: youtube / Downloading keeps working as YouTube changes, with nothing for an editor or admin to do
- Here: Requests, logs and outside programs / Nothing runs on a computer that its person or the vendor did not put there
- From says: "each moves to the newest build within a day, checked as genuine before it is used, never going backwards"
- Here says: "Every program the product fetches from outside is pinned to a version and to its publisher's own checksum" and "programs a person chose to add, by pressing a button that names what will be fetched"
- Settled by: YTD-093 (ruling): "The server and every computer move to the newest verified daily build within a day, in the background without delaying startup, never downgrading, and report their version."
- Fix: whole-product should except programs that keep themselves current (YouTube's downloader, and its own subscription assistant updates): those take the newest build verified against the publisher's checksum, never older, without a button.
