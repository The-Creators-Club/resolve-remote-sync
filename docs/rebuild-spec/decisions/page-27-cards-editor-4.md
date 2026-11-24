# Decision list, page 27: Timeline Cards: the editor, part 4

Stays behind: never shown to the session that rebuilds the product.

13 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 27.1 Shortening needs section headings, and a cut list without them is sent to the edit chat to "cut it down in words". Keep it that way, or should shortening also work on a cut list with no headings?

- **Today:** planning refuses a cut list with no titled sections and suggests the chat, which can also delete and trim cards.
- **Options:** A: keep it as it is: shortening works section by section, and the chat is the way to cut a cut list with no headings. B: shortening treats a cut list with no headings as one section.
- **Recommended:** A, because it needs nothing new and the refusal already says what to do.
- **What you would notice:** with B, a cut list with no headings could be shortened in the panel, but with no per-section plan to adjust.
- (cards-editor-4-Q2)

### 27.2 The montage builder and section summaries run at a fixed strength of assistant that nobody can choose. Should they follow the strength chosen in the edit chat, as shortening does?

- **Today:** the edit chat offers fastest, stronger and most capable; shortening is fixed to the stronger one though your ruling asks for it to use the chat's choice; the montage builder and summaries are fixed with no choice.
- **Options:** A: every assistant feature in the editor (shortening, montage builder, summaries) uses the strength chosen in the chat panel; search keeps its own. B: each keeps a fixed strength.
- **Recommended:** A, because it adds no new control and leaves no feature spending at a strength the person cannot see.
- **What you would notice:** with A, picking "fastest" in the chat makes a montage or a summary quicker and cheaper too.
- (cards-editor-4-Q4)

### 27.3 The edit chat shows the history of a cut list's chat from the studio's earlier Timeline Cards, read only, before the new messages. Is that worth carrying over?

- **Today:** the first time a cut list's chat opens, its earlier history is brought in once and shown under "Earlier messages, from the old Timeline Cards"; old proposals cannot be applied and the assistant is never told about them.
- **Options:** A: carry it over and show it read only, as now. B: leave it behind; a cut list's chat starts empty in the new build.
- **Recommended:** A, because you asked for what the studio has built up to be carried over, and it is one read-only section.
- **What you would notice:** with B, the reasons behind earlier edits are no longer readable in the chat.
- (cards-editor-4-Q5)

### 27.4 A cut list can be kept on a device from two places with different switches and wording. Should there be one panel, "On this device", holding everything?

- **Today:** an Offline page ("Download for offline", with Whole clips, Smaller audio and Include the video switches, the Work offline switch and "A copy of your edits") and a separate "On this device" panel ("Keep on this device", with Include video, the list of kept cut lists and the folder) both keep a cut list on the device, each in its own words.
- **Options:** A: one panel, "On this device", with the panel's words, taking in the Offline page's Whole clips and Smaller audio switches, the Work offline switch and the copy of edits. B: keep both.
- **Recommended:** A, because two places doing one job is the plainest case of a part that can go.
- **What you would notice:** with A the Offline page's labels ("Download for offline", "Download again", "Download the rest", "Other cut lists on this device") are gone and its buttons lead to the one panel.
- (cards-editor-4-Q6)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 27.5 | The tools made only for testing the editor (test pages with only shortening or only the chat, hidden per-browser switches, test hooks, the Windows app's test settings, the Android app's always-on inspection over USB): may they all go? | a test page carries the editor with only shortening, another with only the chat; a hidden per-browser choice forces where kept cut lists are stored (and another, in part 5, turns editor tools off on one device); the keep panel exposes test hooks; the Windows app can be pointed at another profile, downloads folder, server or projects folder for testing; the Android app can always be inspected from a computer over USB, which lets anyone holding the phone and a cable look inside the page. A builders' test proves the installed editor opens offline within set times. | A, because none of them is something a person uses, and inspection left on in the shipped app is an opening nobody needs. (cards-editor-4-Q1) |
| 27.6 | Shortening has two length sliders: one previews from the scores before any review and cannot be accepted, the other marks the suggestions during a review and can accept them. Keep both? | before a review, "Or drag to a length" with scores built previews on the lane which whole cards would go, and "Ask for the real cut" turns it into a plan; during a review, "At a length" marks the pending suggestions that would reach a length, with "Accept these". | A, because they already appear one at a time, and merging them would only change the label. (cards-editor-4-Q3) |
| 27.7 | Inside the apps, a second, quieter automatic keep of the open cut list's audio exists but never runs, because the automatic keep of the whole cut list does the job. May it go? | the apps keep the open cut list automatically (audio, waveforms, transcripts and English, switchable on the app's settings page); a separate audio-only keep, switchable only by a hidden setting, stands down wherever that is present. | A, because the whole-list keep already holds the audio. (cards-editor-4-Q7) |
| 27.8 | Should the Windows and Android apps open the editor from the dashboard's own address, with live editing between devices working inside the apps exactly as in a browser? | a prepared set-up for the apps to open the editor through the dashboard was never finished or shipped, and it is not known whether live editing between devices works inside the apps at all. | A, because the editor lives in the dashboard and an app that cannot edit live alongside a phone would be the one place where edits do not show within seconds. (cards-editor-4-Q8) |
| 27.9 | Should there be one "work offline" switch wherever the editor runs, instead of the editor's own and the app's own? | the editor has a work-offline switch and the apps have their own on their settings page; switching the app offline does not tell the editor, so the background top-ups do not know. | A, because two switches for one wish is how the top-ups came to run while the app was meant to be offline. (cards-editor-4-Q9) |
| 27.10 | On Android, "Open folder" says it worked but opens nothing. Should it open the folder, or not be offered on Android? | the button answers as if it opened the projects folder, and nothing happens. | A, because the folder is meant to be visible and the button is useful where it works. (cards-editor-4-Q10) |
| 27.11 | Something outside the editor can offer a set of edits for a person to preview and accept, but nothing in the product ever makes such an offer. Keep that door, or let it go? | the editor can list, preview, apply and dismiss offers that an outside caller puts in, kept for a day; every proposal the product itself makes (the chat, shortening, montage, search inserts, changes brought back from Resolve) already arrives through the ordinary proposal preview. | A, because the proposal preview already does the job for everything the product makes, and an unused door is a part to take away. (cards-editor-4-Q11) |
| 27.12 | A full-panel "You are offline. Keep editing." exists beside the offline toast but is never shown. May it go? | going offline shows a standing toast with Retry now and Hide; the full panel is never used. | A, because the toast already says the same and leaves the cards in view. (cards-editor-4-Q12) |
| 27.13 | The retired page shared up to 50 saved places per cut list across devices. Should places saved by hand be shared across devices in the new editor? | each device coming back to where it was and a new device starting at the latest place are your rulings and are written as decided; the retired page also kept up to 50 saved places per cut list that every device could go to. The retired page's shared staged draft with named saved drafts and its named bins, the other two parts of the same reader's question, are written up with the hand-over to Resolve and the transcript panel. | A, because the per-device place you ruled for already covers coming back to work, and markers and sections already mark places in the cut itself. (cards-editor-4-Q13) |

## Your answers

Not yet answered.
