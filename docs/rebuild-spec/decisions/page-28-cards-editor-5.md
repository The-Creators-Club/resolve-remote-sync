# Decision list, page 28: Timeline Cards: the editor, part 5

Stays behind: never shown to the session that rebuilds the product.

13 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 28.1 Should the Windows window for the editor come from the one app on the editor's computer, instead of being an app of its own?

- **Today:** a separate Windows app wraps the editor in a window of its own, with a menu: Episodes (home), App settings and status, Open the project folder, Open the app data folder, Quit, the edit menu, Reload, Force reload, zoom, full screen, developer tools, Back and Forward.
- **Options:** A: the one app on the editor's computer opens the editor in a window of its own with this menu, and updates with that app. B: a Windows app of its own for the editor, installed and updated separately. C: no Windows window at all: on a desk the editor is a browser tab.
- **Recommended:** A, because your requirements say an editor's computer runs one app with one version, and A keeps the whole-window editor without a second install.
- **What you would notice:** with A an editor installs nothing extra and finds the editor window in the app they already have; with B they install and update a second app; with C they always cut in a browser tab.
- (cards-editor-5-Q2)

### 28.2 Should single tools of the editor be switchable for a site, or should the editor's tools only follow Timeline Cards, the help for the editing program and the assistant switch?

- **Today:** the server can tell the editor that some of its tools are off, and they then do not appear, but nothing shows who sets this or where; a stand-alone run of the editor can switch each of its capabilities on or off when started.
- **Options:** A: no switch per tool; the editor's tools follow the site's switches you already decided (Timeline Cards on or off as one part, the help for the editing program, the assistant). B: an admin can also switch each tool of the editor (search, the edit chat, shortening, markers, gap notes, montage, video, the shelf and so on) off for the site.
- **Recommended:** A, because it is the fewest switches, and the switches you have decided already hide every tool that leans on something switched off.
- **What you would notice:** with A an admin has no per-tool list to manage; with B an admin could hide, say, the edit chat for everyone while keeping the assistant elsewhere.
- (cards-editor-5-Q3)

### 28.3 Should Follow and recorded places (record, next, drop, clear) work from the View sheet, as they do from their keys?

- **Today:** the View sheet has their buttons, but it is not certain anything supplies them there, in which case they are always disabled; the keys for following and for places work.
- **Options:** A: they work from the sheet as from the keys. B: keep Follow, drop recorded places everywhere. C: take both out of the sheet and keep only the keys.
- **Recommended:** A, because the keys already do it, and a phone without a keyboard reaches them only through the sheet.
- **What you would notice:** with C a phone user could not record or jump to places.
- (cards-editor-5-Q8)

### 28.4 "Copy a link to the selected cut" sat beside the Story Deck links, which are cut. Where should it live?

- **Today:** the button is next to links that go with Story Deck.
- **Options:** A: in a cut's More menu and the selection's. B: in the header's More menu.
- **Recommended:** A, because the link is about one cut and the cut's own menu is where a person looks.
- **What you would notice:** the button is found on the cut instead of in a Story Deck area.
- (cards-editor-5-Q9)

### 28.5 In the transcript, when Y has no find match to take, should it select the paragraph under the transcript's own playhead, or under the lane's playhead?

- **Today:** one description says the paragraph under the transcript's playhead; another, with the message "the block under the playhead - move with the D-pad, then LT + Y selects the run", says the paragraph under the lane's playhead.
- **Options:** A: the transcript's own playhead (the lane's playhead when the transcript has none). B: the lane's playhead.
- **Recommended:** A, because the controller acts on the place that has it, and the transcript has its own playhead for exactly that.
- **What you would notice:** with B, Y in the transcript jumps to whatever the lane is playing.
- (cards-editor-5-Q10)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 28.6 | The builders' own tools can go: a hook for automated tests, a hidden switch that turns editor tools off in one browser, and the Windows test app that cuts on a folder with no server, with its trial copy of every cut list. Agreed? | the running editor can be driven from the browser's developer console for tests; a hidden per-browser list can switch named editor tools off on that device, with no control; a "Timeline Cards Editor" test app for one Windows computer runs the editor on a chosen folder with no server and no sign-in, edits a private working copy of every cut list unless "write mode" is switched on, and has its own window, tray icon and menu; a stand-alone run of the editor copies every cut list to a private copy on first start and edits only that. | A, because every editor already reaches the cut lists through the dashboard, offline work covers being away from the server, and a second way to run the editor is a second product to keep working. (cards-editor-5-Q1) |
| 28.7 | The status line at the foot of the editor (mode, what is happening, the server's confirmed version "rev N") is hidden on every layout, so nobody sees it. Drop it, or show it? | it is written out in full but hidden on the desk and on both phone layouts; the header's sync pill, the toasts and the transport's Shortcuts button say the same things. | A, because what it says is already on screen elsewhere and nobody has relied on it. (cards-editor-5-Q4) |
| 28.8 | LT with D-pad Left or Right in the transcript can never reach a list of search results and always says so. Drop it, or give it a working meaning? | it is meant to step to the previous or next result of the open search, but whenever the search sheet is open the controller follows the results map instead, so in the transcript it always shows "There is no results list open: Ctrl+Shift+F searches every transcript" and rumbles. | A, because results are already walked with the D-pad in the sheet, and the hint never helped anyone. (cards-editor-5-Q5) |
| 28.9 | After an edge drag or a fade made with the controller, A was meant to play the join (1 s before the new edge to 1.5 s after). It never does. Should it? | A always plays from the head. | A, because one meaning for A is easier to trust from the sofa, and LT + A already plays a cut from its start. (cards-editor-5-Q6) |
| 28.10 | The View sheet's "All stacks" button always says the cut list has no stacks. Can it go? | it always answers "This cut list has no stacks", even though cards can be joined into stacks elsewhere in the editor. | A, because stacks are opened and closed on the cards themselves and nobody has missed a button that never worked. (cards-editor-5-Q7) |
| 28.11 | The retired page told a fault (a red banner) from a quiet "no timeline from Resolve" (an amber note). Does any of that belong in the rebuild? | only the retired page that showed Resolve's live timeline had it; the editor always shows its own cut list. | A, because you ruled that nothing about Resolve being away shows as a fault. (cards-editor-5-Q11) |
| 28.12 | Switching the editor to another episode by naming its folder only ever existed on the retired page. Can it go? | nothing in the editor asks for a switch by folder name; episodes are opened from the episode list and the Cut lists sheet. | A, because the episode list and the sheet already open every episode, without anyone typing a folder. (cards-editor-5-Q12) |
| 28.13 | The episode list offers the last episode twice: "Carry on with" (this browser) and the top of "your recent" (this person). Keep one record, or two? | "Carry on" names the last episode opened in this browser for 90 days; "your recent" lists the last 5 this person opened anywhere; the retired page also remembered one last episode for the whole server. | A, because one record cannot disagree with itself, and the big "Carry on" button stays where people expect it. (cards-editor-5-Q13) |

## Your answers

Not yet answered.
