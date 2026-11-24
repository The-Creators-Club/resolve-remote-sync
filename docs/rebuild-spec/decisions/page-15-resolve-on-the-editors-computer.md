# Decision list, page 15: Resolve on the editor's computer

Stays behind: never shown to the session that rebuilds the product.

12 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 15.1 How should the editor be told about clips that point at a path only another editor's computer has?

- **Today:** from the open timeline the editor gets one notification per clip, naming the clip and the start of its path; from the media pool sweep they get one notification per sweep, naming the first clip and a count, with "details in the log". The words differ.
- **Options:** A: one notice per batch found, naming the first clip and how many others, each path told about once while the app runs, with the full list in the app's diagnostics. B: one notification per clip, as from the timeline.
- **Recommended:** A, because a project imported from another computer can hold hundreds such clips and one problem should raise one notice.
- **What you would notice:** with A, an editor sees one notice for a whole batch, not one per clip.
- (resolve-on-the-editors-computer-Q2)

### 15.2 Should there be one tool for getting scattered media into the tree, instead of FIX ALL and "Copy this project's media in" side by side?

- **Today:** FIX ALL copies the clips the window lists (from the open timeline, or from a whole-project scan) and relinks them; "Copy this project's media in" copies every scattered clip in the project's media pool, relinks the same way, first shows what the server will then receive and send down, then waits while the originals upload and the proxies come down. The reminder about projects not open tells editors to press FIX ALL.
- **Options:** A: one tool: FIX ALL, filled either from the open timeline or from "Scan whole project", with the size and room line; uploading and bringing proxies down are left to syncing, which does them anyway. B: keep both tools.
- **Recommended:** A, because both copy and relink in exactly the same way, and the second adds only a wait for syncing that syncing does on its own.
- **What you would notice:** with A, an editor bringing in an old project presses "Scan whole project" then FIX ALL, and watches the upload in the app's transfers rather than in the copy window; the preview of what the server would delete goes with it (syncing's own safety stops still protect the editor's files).
- (resolve-on-the-editors-computer-Q4)

### 15.3 The product saves a backup copy of a Resolve project before changing it, but its own undo never uses the copy. Keep making it, and should a person be able to restore it through the product?

- **Today:** at most every 15 minutes per project, before changing clips, the project is saved and exported as a backup kept 60 days; nothing in the product restores it.
- **Options:** A: keep making it (a lesson requires it), and leave restoring to Resolve's own project manager, with the app's diagnostics saying where the copies are. B: keep making it and add a restore button in the product. C: stop making it.
- **Recommended:** A, because Resolve already imports such a copy, and a restore button would be a second undo beside the real one.
- **What you would notice:** with A, a person restoring a project by hand opens Resolve's project manager and imports the dated copy.
- (resolve-on-the-editors-computer-Q7)

### 15.4 The VP9 warning says the timeline "plays fine now only because Resolve is using the H.264 proxies" even when no proxy exists or is attached. Should that sentence fit the case?

- **Today:** the sentence is shown for every VP9 warning.
- **Options:** A: show the sentence only when the affected clips are playing from proxies, and leave it out otherwise. B: keep it on every warning.
- **Recommended:** A, because a warning that says something untrue teaches editors to ignore it.
- **What you would notice:** with A, an editor whose VP9 clips have no proxy does not read that they play fine.
- (resolve-on-the-editors-computer-Q9)

### 15.5 When an editor's request for originals made from Resolve's menu is dropped, should they be told?

- **Today:** a request from Resolve's Scripts menu that is not answered within an hour, or that cannot be read, is dropped and nobody is told; a failure of the quick upload of new clips is not shown either.
- **Options:** A: the editor gets a notification that the request was dropped, and why. B: dropped in silence, as now.
- **Recommended:** A, because an editor who asked for originals and gets nothing otherwise waits for footage that is never coming.
- **What you would notice:** with A, an editor sees "could not be sent" and can ask again.
- (resolve-on-the-editors-computer-Q10)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 15.6 | Clips stored outside the shared tree are found in several ways. Which stay? | five: the open timeline is read every few seconds, the whole media pool is read every two minutes, the editor can press "Scan whole project", "Copy this project's media in" reads the media pool, and the projects not open are checked every 30 minutes. | A, because the scan by hand already covers every bin, and a timed sweep of the media pool makes Resolve stutter for the editor. (resolve-on-the-editors-computer-Q1) |
| 15.7 | Undoing a change the product made in Resolve can be done by the editor and by an admin, from two places on the dashboard. Keep all of them? | the editor presses "Undo last fix" (always the newest change, in the project open now; a second button in the same settings window does the same); an admin can undo any listed change for a computer from the per-computer view and again from the dashboard's recovery guide for the Resolve problem, waiting until that project is open. | A, because the editor and the admin need different things (the newest change here, against any change on a computer far away), but the admin needs only one page to do it from. (resolve-on-the-editors-computer-Q3) |
| 15.8 | Should FIX ALL's rehearsal mode stay? | a rehearsal that checks every clip and copies nothing exists, off by default; it can be switched on only by editing the app's settings file, and when on only the log says so, though a red line and a "TURN REHEARSAL OFF" button do appear. | A, because no editor's task needs a rehearsal: FIX ALL never touches the original, shows size and room first, can be cancelled, and can be undone. (resolve-on-the-editors-computer-Q5) |
| 15.9 | When an admin's undo is waiting on an editor's computer, should the admin see the real reason it waits? | when Resolve stops answering, or no timeline is open, the admin is told "there is no project open in Resolve on this computer", which is not what happened. A finer "parked until the project is open" state exists but is never sent. | A, because one waiting state with a true reason tells the admin everything the parked state would. (resolve-on-the-editors-computer-Q6) |
| 15.10 | A count of seconds until the next automatic change is allowed exists but is shown nowhere. Keep it? | the product can tell how many seconds remain before its limit allows the next change it would make on its own, but no screen shows it. | A, because an editor has nothing to do with the number; the set-up problem itself is what they act on. (resolve-on-the-editors-computer-Q8) |
| 15.11 | Sharing an editor's own LUTs with the team can be started from the app's menu and from its settings window. Keep both? | the menu shows "N LUT(s) only on this computer: share with the team" while there are any, and the settings window has the same action. | A, because the offer appears exactly when it is useful, and one way to do each thing. (resolve-on-the-editors-computer-Q11) |
| 15.12 | Where each Resolve project's files go can be read and set from several places. Which stay? | it is read on the overview, on a person's own account page (one per computer) and in the list of Resolve projects and their folders; it is set in that list by an admin, and first set when a project is set up from the app's question about an untied Resolve project. | A, because the per-computer view is where a person looks for what one computer is doing, and the list is the one place to change it. (resolve-on-the-editors-computer-Q12) |

## Your answers

Not yet answered.
