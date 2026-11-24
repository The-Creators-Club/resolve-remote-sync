# Joins aimed at cards-editor-4

## Checked

- J1 | F7, F8
- J2 | F9
- J3 | F6
- J4 | fine
- J5 | F1, F2, F3, F4, F5
- J6 | F10

## Findings

### F1: This piece keeps a separate Windows Timeline Cards app with its own installer, while the owner folded it into the one app on the computer
- Kind: contradiction
- From: releases-and-updates / The Timeline Cards app on an Android phone updates itself from the server (also cards-editor-5 / The app on the editor's computer opens the editor in a window of its own)
- Here: The Windows app installs per person or runs portable, and runs once; Timeline Cards has its own apps for Windows and Android that show the editor from the studio's server; The Windows app's window, links, permissions and downloads
- From says: "On a computer, Timeline Cards opens from the one app on that computer and updates with it: there is no separate Timeline Cards program to install or update there." and (cards-editor-5) "from the app on the editor's computer ... and updates itself with the app, from its settings"
- Here says: "The Windows app comes as a one-click installer for the signed-in person of the computer and as a portable program, for 64-bit Windows. Only one copy runs: a second launch brings the existing window forward and restores it. If it cannot start because another program on the computer is in its way, it says so, asks for that program to be closed, and quits." and (33-098, Exact) "Closing the last window quits."
- Settled by: decisions page 10.1, answered 2026-11-24 with the recommendation: "A: keep the Android app for phones (a phone is not an editor's computer), and fold the Windows Timeline Cards app into the one app on the editor's computer, updated with it."; page 28.1: "A: the one app on the editor's computer opens the editor in a window of its own with this menu, and updates with that app."; OWNER_REQUIREMENTS 2: "An editor's computer runs one app with one version."
- Fix: cards-editor-4 drops the Windows installer, portable program, run-once and "another program is in its way" behaviour, says the Windows window is opened from the one app and updates with it (pointing to cards-editor-5), and replaces "Closing the last window quits" with closing only the editor window, leaving the Android app as the only Timeline Cards app of its own.

### F2: On a computer the editor window gets its own server-address setting here, but signs in to the one app's dashboard in cards-editor-5
- Kind: contradiction
- From: cards-editor-5 / The app on the editor's computer opens the editor in a window of its own
- Here: The app's settings page works with no network and sets the server address
- From says: "it signs in to the same dashboard, opens on the episode list, and updates itself with the app"
- Here says: "Setting: Address of the Timeline Cards page. Does: sets which studio server the app shows ... Applies to: a computer." and (33-088) "On first run the server address is the studio's own Timeline Cards address; it is changed on the device in the app's settings page."
- Settled by: OWNER_REQUIREMENTS 1: "One way to do each thing: one way of telling a computer something, one place a setting comes from"; decisions page 28.1 (A, the window comes from the one app).
- Fix: cards-editor-4 keeps the server-address field and setting for the Android app only and says that on a computer the editor window uses the dashboard address the one app already holds.

### F3: On a Mac this piece says the editor is a browser tab, cards-editor-5 gives the editor window a Mac menu bar
- Kind: contradiction
- From: cards-editor-5 / The app on the editor's computer opens the editor in a window of its own
- Here: The Windows app installs per person or runs portable, and runs once
- From says: "Windows and macOS: the menu's keys are given as on Windows; on a Mac, Cmd stands for Ctrl and the menu sits in the menu bar."
- Here says: "Windows and macOS: there is a Windows app; on a Mac the editor is used in a browser."
- Settled by: the owner must say: does an editor on a Mac open Timeline Cards in a window of the one app, as on Windows, or always in a browser? (OWNER_REQUIREMENTS 2, "An editor's computer runs one app with one version. Every optional part is in it", leans to the window; page 28.1 was asked about Windows only.)
- Fix: once answered, cards-editor-4 and cards-editor-5 say the same thing for a Mac; if the window, cards-editor-4 drops "on a Mac the editor is used in a browser".

### F4: The editor window "needs the dashboard to be reachable" there, but opens and edits offline here
- Kind: contradiction
- From: cards-editor-5 / The app on the editor's computer opens the editor in a window of its own
- Here: The apps notice within seconds that the server is gone and work offline; The editor opens with no network once it has been opened on that device
- From says: "It needs the studio's dashboard to be reachable, as the browser does."
- Here says: "Once the server is found to be down, the editor sees itself as offline at once and works from what the device keeps" and "it opens on that device with no network: from a bookmark, from the installed editor on a phone or computer"
- Settled by: lesson CE2-158 (kind situation, weaker): "Offline, the installed app shows the last episode list within about 8 s, marks cut lists saved on the device, and opens them."
- Fix: cards-editor-5 replaces "It needs the studio's dashboard to be reachable" with: it needs the dashboard for the first sign-in and the first visit, and after that opens and edits offline as described in cards-editor-4.

### F5: The computer's editor window is called "the Windows app" here and "the editor window" in cards-editor-5
- Kind: differs
- From: cards-editor-5 / The app on the editor's computer opens the editor in a window of its own (also releases-and-updates / The Timeline Cards app on an Android phone updates itself from the server)
- Here: Timeline Cards has its own apps for Windows and Android that show the editor from the studio's server; The panel says where things are kept and whether they will stay
- From says: "Name and search words: the editor window. Search words: editor window, desktop, window, menu, app."
- Here says: "Name and search words: the Timeline Cards app: Windows app, Android app, desktop app, phone app." and "shown as "The Windows app's project folder" / "The Android app's projects folder""
- Settled by: decisions page 28.1 (A: the window belongs to the one app); OWNER_REQUIREMENTS 5: "Every page, part and setting therefore has a plain name".
- Fix: cards-editor-4 names the computer side "the editor window" of the one app wherever it says "the Windows app" (headings, the storage label, the name and search words), keeping "the Timeline Cards app" for Android.

### F6: "All episodes" is refused offline because "the episode list needs the server", but this piece opens the episode list offline
- Kind: contradiction
- From: cards-editor-5 / The lists page shows the episode's cut lists, newest first, with what is open, last opened and kept on this device
- Here: The editor opens with no network once it has been opened on that device; The episode list shows which cut lists are kept on this device and opens them with no network
- From says: "While offline the link is refused with "You are offline: the episode list needs the server, so this cut list stays open""
- Here says: "With the server not answering at all, the episode list appears within about 3 seconds with its episodes listed" and "Offline, the list shows an "offline" warning ... Cut lists marked downloaded open from this device"
- Settled by: lesson CE2-158 (kind situation, weaker): "Offline, the installed app shows the last episode list within about 8 s, marks cut lists saved on the device, and opens them."
- Fix: cards-editor-5 lets "All episodes" open the device's saved episode list while offline (with its offline warning) instead of refusing, refusing only when that list was never saved on the device.

### F7: The studio's seven house-style rules are written out in full in both pieces
- Kind: said twice
- From: cards-board / The studio's house style, and an episode's own
- Here: The chat follows a house style of seven editorial rules, which an episode can replace with its own
- From says: "never any interviewer question; withhold, then reveal: the film raises one big question early ... make the cut feel like one conversation between people who were never in one room"
- Here says: "The built-in house style has seven rules: no interviewer questions ever; withhold, then reveal; part of a sentence can be the whole card; end sections on a cliffhanger; space revelations out; never invent tension ...; cut it as one conversation across speakers"
- Settled by: no disagreement yet; cards-board's "The owner's editorial rules" is the place cards-editor-4 itself sends the reader for where the style is written.
- Fix: cards-editor-4 replaces its list of the seven rules with a pointer to cards-board / The studio's house style, and an episode's own, keeping only what the chat does with the style.

### F8: The episode's own style notes are called "chat style note" and "shortening style note" here, "House style for an episode" and "Shortening rubric for an episode" on the board
- Kind: differs
- From: cards-board / The studio's house style, and an episode's own (and its neighbour The shortening rubric, and an episode's own)
- Here: An episode can carry its own description of what counts as fluff; The chat follows a house style of seven editorial rules, which an episode can replace with its own
- From says: "Setting: House style for an episode." and "Setting: Shortening rubric for an episode."
- Here says: "When the episode has its own shortening style note and it is not empty" and "An episode's own chat style note, when present and not empty, replaces these whole"
- Settled by: OWNER_REQUIREMENTS 5: "Every page, part and setting therefore has a plain name and a few search words in this specification."
- Fix: cards-editor-4 calls them by the board's setting names, "the episode's house style" and "the episode's shortening rubric".

### F9: The C key that opens the edit chat is missing from this piece's ways in and from its assistant-off list
- Kind: missing
- From: cards-editor-1 / Single keys open the help sheet, search, the edit chat, notes, places and Send to Resolve
- Here: An editor opens the edit chat from the toolbar or, on a phone, from the header; What remains of these features when the assistant is switched off
- From says: "C (lane and cards; in the transcript C belongs to the transcript): ask the assistant to change the cut list in your own words (the edit chat)." and "When the assistant is off: C opens nothing."
- Here says: "Ways in: the toolbar button on a desk, the header button and the edit view's top-bar button on a phone." and the assistant-off list names "Alt+H, Alt+B or Shift+B" and "Alt+M" but no C
- Settled by: OWNER_REQUIREMENTS 4: "In the Timeline Cards editor, everything a person sees and touches: every screen, panel, key ... These were shaped by months of his use." (28-017 is marked Exact)
- Fix: cards-editor-4 adds "the C key on the lane and the cards" to the edit chat's ways in and "C opens nothing" to its assistant-off list.

### F10: The whole-product rule says a conversation continues until three things renew it; the edit chat also starts afresh after an hour idle and when the house style changes
- Kind: contradiction
- From: whole-product / A conversation with the assistant is kept per cut list
- Here: The chat knows the whole episode's transcripts, the whole cut list and what the editor is pointing at
- From says: "A new conversation starts when the transcripts it was given change, when the person presses "new conversation" or "start over", and when they switch strength"
- Here says: "Warm for an hour after a completed turn; cold otherwise, or when the transcripts or house style changed." and "opened a new conversation: ... "the conversation had gone cold (over an hour), so the cut list was read again""
- Settled by: for the house style, cards-board / The studio's house style: "A change applies from the assistant's next answer on, in the editor's edit chat too"; for the hour, the owner must say: when an editor comes back to the edit chat after more than an hour, does the assistant carry on the same conversation or read the transcripts and the cut list again?
- Fix: whole-product adds a change of house style to its list of what starts a new conversation, and, as the owner answers, either adds an hour without a message to that list or cards-editor-4 drops the hour.
