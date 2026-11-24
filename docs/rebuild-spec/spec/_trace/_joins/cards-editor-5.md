# Joins aimed at cards-editor-5

## Checked

- J1 | F1
- J2 | fine
- J3 | fine
- J4 | fine
- J5 | fine
- J6 | F2
- J7 | F3, F4
- J8 | F5, F6
- J9 | F7
- J10 | fine
- J11 | fine

## Findings

### F1: A real sign-out deleting the episode list kept on the device is said only by accounts; the editor piece keeps that list for offline use and never says it goes
- Kind: missing
- From: accounts-privacy-legal / Signing out, and signing out everywhere
- Here: nowhere (the nearest is "Timeline Cards installs on a phone as its own app that opens on the episode list")
- From says: "A real sign-out (not an ended sign-in) also deletes the list of Timeline Cards episodes saved on that device."
- Here says: "with no network, shows the last episode list it had within about 8 seconds, marks the cut lists saved on the phone, and opens them;"
- Settled by: the owner must say: when a person signs out of the dashboard on a phone or computer, is the episode list Timeline Cards kept there for offline use deleted from that device?
- Fix: cards-editor-5 adds to the phone app behaviour that a real sign-out (not an expired sign-in) deletes the saved episode list on that device, so the offline promise reads "after the last sign-in"; accounts stays as it is.

### F2: The "episode picker's third part" listing transcripts does not exist here; this piece calls it "the episode's browser" and gives it no columns
- Kind: differs
- From: cards-editor-3 / Any transcript of the episode can be opened from the episode picker on its own
- Here: The episode's browser lists every transcript and cut list, and several can be chosen at once
- From says: "The picker's third part lists every interview and clip transcript of the episode with person, clip, colour and whether it is already loaded. ... The picker itself is described in Timeline Cards: the editor, Opening episodes and keeping the editor running."
- Here says: "Inside the editor, the episode's browser lists every transcript and every cut list of the episode, can be filtered and searched, and lets a person choose several at once"
- Settled by: CE1-012 (ruling): "the browser lists every transcript and cut list in the episode, filterable, searchable and multi-selectable." (it names the browser; who shows person, clip, colour and loaded is not settled by it)
- Fix: cards-editor-3 calls it "the episode's browser" (this piece's own name; "episode picker" here means the Timeline Cards page) and drops "third part"; cards-editor-5 adds that each transcript row shows its person, clip, colour and whether it is already loaded.

### F3: The episode list here has no "was last in N min ago" line, which cards-editor-4 says the list shows
- Kind: missing
- From: cards-editor-4 / Every signed-in person sees who is working in which episode
- Here: The Timeline Cards page lists every episode in its folders, most recently opened first
- From says: ""<who> is in it now" (within the last minute), "<who> was last in N min ago", or "<who> opened it <how long ago>""
- Here says: "when it was opened: "you opened it <ago>" (marked as the person's own), "<name> opened it <ago>", "somebody opened it <ago>" or "never opened"; who is in it now;"
- Settled by: the owner must say: on the episode list, does an episode someone left a few minutes ago read "<who> was last in N min ago", and for how long after they leave?
- Fix: cards-editor-5 gives the full presence wording on each episode ("<who> is in it now" within the last minute, then "<who> was last in N min ago", then the "opened it" lines) and cards-editor-4 points here instead of repeating it.

### F4: Closing an episode, with its confirmation, is described as an act on the episode list, but the episode list here offers no Close
- Kind: missing
- From: cards-editor-4 / Every signed-in person sees who is working in which episode
- Here: The Timeline Cards page lists every episode in its folders, most recently opened first (each episode offers only "Open"); Opening an episode goes into the editor at the cut list last left there ("Closing an episode frees everything it used")
- From says: "Closing an episode asks first, naming who was last in it and when: "Close <episode>? <who> was last in N min ago. Anything an offline browser has not sent yet stays in that browser until it reconnects." ... Ways in: the dashboard's list of episodes."
- Here says: "changed <when>", written like "3 Sep 2026"; and "Open"."
- Settled by: the owner must say: can a person close an open episode from the Timeline Cards page, and who may do it?
- Fix: if yes, cards-editor-5 adds a Close on each open episode of the list with that confirmation and who may press it; if no, cards-editor-4 drops the sentence.

### F5: Send to Resolve is a red button in the header (and a row of the header's More) here, but sending is an action on the cut with no top-bar button there
- Kind: contradiction
- From: cards-to-resolve-and-exports / The Resolve and exports dialog (and "Where the dialog and the script downloads are reached", beside it)
- Here: The header shows the brand, where you are, search, undo, redo and Send to Resolve; A More menu offers each card's less common actions, and the header's
- From says: "Sending is an action on the cut, not a button in the top bar: the cut's own actions hold "Send to Resolve", which opens the Send tab with a fresh dry run."
- Here says: "**Send to Resolve** (desk only): a red primary "Send to Resolve" when a cut list is open and sending is available" and "Header extras: "Redo", "Send to Resolve" (or a quiet row with the reason ...)"
- Settled by: CRX-065 (ruling): "A cut offers one action that sends it to a new Resolve timeline: name it, see dry-run counts, confirm; the top bar holds no such button."
- Fix: cards-editor-5 removes Send to Resolve, its "Sending" state and its "Resolve: not connected" label from the header, its compaction steps and the header More extras, and says where the cut's own "Send to Resolve" action sits (desk and phone); cards-to-resolve-and-exports stays.

### F6: Where the exports are reached: here they appear only in place of Send when Resolve help is off; there an Export toolbar button is always present
- Kind: differs
- From: cards-to-resolve-and-exports / The Resolve and exports dialog (and "Where the dialog and the script downloads are reached")
- Here: The header shows the brand, where you are, search, undo, redo and Send to Resolve; With the help for the editing program switched off, the editor never mentions it and offers the exports
- From says: "Toolbar button "Export" (download icon, tooltip "Resolve and exports: export, import, send, follow")" and, with the help off, "the Export button's tooltip reads "Exports: export, import""
- Here says: "When the help for the editing program is off: no Send to Resolve button, label or tip is drawn; the header offers the exports in its place" and "Where Send to Resolve stands, the editor offers the exports instead"
- Settled by: OWNER_REQUIREMENTS.md section 2: "With it off, nothing in the product mentions that program, and the b-roll archive, music and Timeline Cards offer exports instead of sending to it." (says exports are offered, not where); with CRX-065 removing the header Send, the owner must say only if the Export button is not to be always present: is the Export button in the editor's top bar whether or not the help for the editing program is on?
- Fix: cards-editor-5 names the one "Export" toolbar button as always present (its tooltip changing when the help is off) instead of "the exports in its place", so a builder does not make a second, help-off-only export control.

### F7: The refusal sentence "this request came from another site" for Timeline Cards is not in the editor's pieces
- Kind: missing
- From: dashboard-2 / A change that did not come from the dashboard's own page is refused
- Here: nowhere (the only nearby rule is "An edit is refused only for a real reason, and never in silence": "a plain sentence saying why")
- From says: "and in Timeline Cards with "this request came from another site". The cure is to reload the page."
- Here says: nothing
- Settled by: the owner must say: when Timeline Cards refuses a change because the page it came from is not the dashboard's own, what sentence does the person see, and is it the same sentence the rest of the dashboard shows?
- Fix: cards-editor-5 (under "An open editor page carries on through a server restart" or "An edit is refused only for a real reason") adds the refusal and its sentence, or dashboard-2 drops the separate Timeline Cards sentence and uses its own everywhere.
