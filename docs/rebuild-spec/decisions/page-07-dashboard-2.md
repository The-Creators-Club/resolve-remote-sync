# Decision list, page 7: The dashboard, part 2

Stays behind: never shown to the session that rebuilds the product.

11 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 7.1 Are all the scheduled messages wanted: a message after each check that finds something, the weekly report, the daily "still here", and the server check?

- **Today:** all four exist. The weekly report repeats what the per-check messages already said, plus builds, protection and what changed.
- **Options:** A: keep all four, each off or on by its own setting. B: drop the weekly report and rely on the per-check messages. C: drop the daily "still here".
- **Recommended:** A, because each answers a different question (what broke now, how the week went, is the server alive, what needs me), and each already has its own on or off setting.
- **What you would notice:** with B or C, one kind of mail stops arriving and its setting goes.
- (dashboard-2-Q2)

### 7.2 Should every change to the site's settings be recorded and undoable, and should the history show the old and new values?

- **Today:** a plain save is recorded only when it touches the tree's place or a reporting switch; imports always are. One view lists the last five changes with no values; another lists the last ten with before and after.
- **Options:** A: record every change of every kind, each undoable; the history names who, when, how and which settings, never the values. B: as A, and also show the old and new value of each setting that is not a secret.
- **Recommended:** A, because it keeps one history that can never leak a secret, and undo already puts back the exact earlier values without anyone reading them.
- **What you would notice:** with B an admin can read what each setting was before a change, not only which settings changed.
- (dashboard-2-Q6)

### 7.3 Should a studio be able to name its projects folder, rather than it always being called "Projects"?

- **Today:** the folder must be called "Projects"; the server refuses to start otherwise, and an imported settings file naming it otherwise is refused.
- **Options:** A: keep it always "Projects". B: let the studio name it, as a setting fixed once any computer has joined.
- **Recommended:** A, because no studio has asked and every computer, path and help page then agrees without one more setting.
- **What you would notice:** with B a new studio could call the folder something else at setup.
- (dashboard-2-Q7)

### 7.4 With YouTube downloads one part with its own switch, should its extra measures against being blocked keep a second switch of their own?

- **Today:** two switches: YouTube downloads, and the extra measures against YouTube blocking them, which only matter with downloads on.
- **Options:** A: keep the second switch. B: drop it; the YouTube part always does what it needs to download.
- **Recommended:** A, because those measures touch YouTube's terms, which is a choice the studio should make knowingly rather than one made for it.
- **What you would notice:** with B one switch fewer, and downloads take those measures whenever YouTube is on.
- (dashboard-2-Q8)

### 7.5 Is a separate Android app for the dashboard (with its own proof of ownership set in the settings) still wanted, or is the dashboard installed from the browser enough?

- **Today:** the dashboard installs from the browser as an app on any phone, and beside that a studio can have an Android app made, which needs its package name and signing fingerprints entered so it opens without an address bar.
- **Options:** A: keep the Android app and its settings. B: rely on the dashboard installed from the browser; drop the Android app, its two settings and its check.
- **Recommended:** B, because the installed dashboard already opens in its own window on every phone, and the Android app adds a build, a signing key and two settings for the same result.
- **What you would notice:** with B there is no studio Android app to install; people add the dashboard to their home screen from the browser.
- (dashboard-2-Q9)

### 7.6 Should the dashboard installed as an app carry the site's product name, rather than always "CC Sync"?

- **Today:** one view says the installed app always calls itself "CC Sync"; another says it carries the site's product name.
- **Options:** A: it carries the product name set for the site (CC Sync unless changed). B: always "CC Sync".
- **Recommended:** A, because every other place takes the name from the one setting, and a customer's people should see their own product name on their home screen.
- **What you would notice:** with A a site that renamed the product sees that name under the app's icon.
- (dashboard-2-Q10)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 7.7 | Should the assistant's scheduled server check stay, the one that mails a short list of what needs a person and carries out actions when the admin replies to its mail? | it is off unless an admin switches it on and has the assistant set up. When on, it reads everything open on the server up to four times a day, mails a short list with numbered actions, and a reply such as "do 1 and 3" carries them out after strict checks that the reply is genuine. | A, because it is the one place that turns many raw alerts into a short list a person can act on from a phone, and every action it offers is an existing button, so it adds no new way to change anything. (dashboard-2-Q1) |
| 7.8 | Should the weekly report carry a section on how much data each computer moved, which has never printed because the figure is not recorded? | the section exists on paper only; the figure is never recorded, so it never prints. | B, because the transfers page already shows what moves, and recording a weekly total for each computer adds a record nobody has asked to read. (dashboard-2-Q3) |
| 7.9 | Whether alerts really reach anyone is said in three places. Which should stay? | the alert channel's status line, a standing problem among the open problems while no destination is set, and one of the facts the server re-checks every quarter of an hour all say the same thing. | A, because an admin looks for problems among the open problems and looks for the channel's state beside its settings, and the third place says nothing new. (dashboard-2-Q4) |
| 7.10 | Should the alert destination be set both in a short step of the setup checklist and in the full alert settings? | the setup checklist has a short "who should we tell" form (one address and the daily message) and the full alert settings hold every field. | A, because a new site needs one address to start, and the short form writes the same single setting, so nothing is held twice. (dashboard-2-Q5) |
| 7.11 | When the server cannot read how project folders are syncing, should that be said on every page and again on the overview? | every page adds "the data on this page may be stale", and the overview also draws a longer line with a "What to do" link. | B, because one warning with its link says everything, wherever the person is. (dashboard-2-Q11) |

## Your answers

Not yet answered.
