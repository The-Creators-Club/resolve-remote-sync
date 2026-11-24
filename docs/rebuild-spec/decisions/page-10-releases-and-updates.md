# Decision list, page 10: Releases and updates

Stays behind: never shown to the session that rebuilds the product.

13 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 10.1 The owner requires one app with one version on an editor's computer. Should the separate Timeline Cards apps for Windows and Android, with their own update check, stay?

- **Today:** Timeline Cards has its own Windows app and its own Android app, each checking the server for its own newer version, beside the CC Sync app on the same Windows computer.
- **Options:** A: keep the Android app for phones (a phone is not an editor's computer), and fold the Windows Timeline Cards app into the one app on the editor's computer, updated with it. B: keep both separate apps as they are. C: drop both and rely on the dashboard installed as an app.
- **Recommended:** A, because it meets "one app with one version" on the computer and keeps the phone app whose offline use he relies on.
- **What you would notice:** with A, a Windows editor has one app to update instead of two. With C, the phone keeps working through the browser's installed page but loses the Android app's own updates.
- (releases-and-updates-Q3)

### 10.2 When a new version of the app keeps failing, how soon should the computer put the previous one back?

- **Today:** one rule puts the previous version back after two failed starts of a new version, another after three crashing starts within ten minutes.
- **Options:** A: one rule: the second failed start or crash within ten minutes of the new version's first start puts the previous one back (one failure is forgiven, for antivirus holding the file). B: three crashing starts within ten minutes.
- **Recommended:** A, one rule that goes back sooner, so an editor waits less on a broken version.
- **What you would notice:** with A, a version that crashes twice is replaced after the second crash instead of the third.
- (releases-and-updates-Q4)

### 10.3 One way to publish: the vendor's studio takes every version first, and customers get it only after it has run there for a day and a second person has approved. Is that right?

- **Today:** there are two release paths: the studio's own release, straight into the studio's server and made current at once, and a customer release through the vendor's list after a 24-hour studio trial and a second person's approval, plus three more ways to publish to the list.
- **Options:** A: one publish; the vendor's studio is simply the first site reading the vendor's list, with its own trial on one computer; customers are offered it after 24 hours on the studio and a second person's approval. B: as A, without the second person's approval. C: keep the studio's own direct release beside the customer one.
- **Recommended:** A, because it is one way to publish, the studio tests exactly what customers receive, and his 24-hour rule is built in.
- **What you would notice:** with A, the vendor needs a second person to approve every customer release. With B he can release to customers alone.
- (releases-and-updates-Q7)

### 10.4 Which warnings about versions not reaching the computers should stay?

- **Today:** about fifteen separate alerts and checks each describe part of "did the new version reach every computer", some mailed, some shown as standing problems, some both, with the "no update check" one appearing at 48 hours in one place and 7 days in another.
- **Options:** A: keep them as one list of problems, each shown once and mailed once, as written. B: keep only "an update will not install", "a computer is refusing every update", "a recalled version is still running" and "this server cannot check for updates", and rely on the versions page for the rest.
- **Recommended:** A, because each one names a different thing an admin must do, and showing each once removes the duplication.
- **What you would notice:** with B, an admin sees fewer alerts and must look at the versions page to notice slow uptake or a trial failing.
- (releases-and-updates-Q11)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 10.5 | Should the editor's "install this update" stay in both the app's menu and its settings window? | an offered update can be installed from a menu item and from a button in the app's settings window. Both open the same confirmation. | A, because it is one action reached from the two places an editor looks, with one confirmation behind both. (releases-and-updates-Q1) |
| 10.6 | Which ways of putting a new version on an editor's computer stay? | a new version reaches a computer by the editor's click, by an admin's push, by the studio's unattended updates, by a hand-run upgrade on Windows, and by running the installer again. | A, because the hand-run upgrade does what the app's own update and a rerun of the installer already do, with a second set of rules. (releases-and-updates-Q2) |
| 10.7 | Should downloading an update follow the same rule for plain, unencrypted connections as everything else the app sends to the server? | the update download refuses a plain connection to a name that only resolves on the studio's network, while the computer's regular check-ins to the same address go through. | A, because the download is checked against the vendor's signature anyway, and two rules mean a computer that checks in but can never update. (releases-and-updates-Q5) |
| 10.8 | Should choosing which version the computers run be one act, with "going back" simply choosing an earlier version? | an admin can make a version current from a held version, from a "roll back to" choice, from the vendor's list, and can separately roll every computer on one version back to another (which may also change the current version), each with a forced variant. | A, because every route ends in the same thing, and the computers all follow the current version anyway. (releases-and-updates-Q6) |
| 10.9 | When a site starts, how much of the vendor's offer should it take by itself? | a new site takes nothing by itself ("manual"), and has no vendor list set at all unless the installer chose it. | A, because a site where nobody clicks still receives fixes and nothing reaches the computers unapproved. (releases-and-updates-Q8) |
| 10.10 | Should a studio be able to let its computers install newer versions with nobody clicking, and should that be on from the start? | the setting exists and is off in every studio. | A, because a studio that wants it has it, and nobody is surprised by an unasked restart. (releases-and-updates-Q9) |
| 10.11 | How long should a page wait for the server to come back after it restarts, before saying so? | after a server update the page gives up after 3 minutes and says so; after a set-up step it waits with no stated limit. | A, one rule, and a person is never left wondering. (releases-and-updates-Q10) |
| 10.12 | Where should an admin be able to push an update to one computer? | "update now" is on the list of computers that are behind, a held-back version has "push to one computer", the per-computer view has it, and a person's account page has it for admins. | A, because the account page is about the person, not about which version their computers run. (releases-and-updates-Q12) |
| 10.13 | The builders' own tools here (a self-test mode that prints whether every part of the built app loads, and a record of which working copy of Timeline Cards and the Footage Sorter was installed on the server) are left out of the specification. Agree they go? | both exist for the people building the product. | A, because what they protect is written as a promise (every version is started and passes its own check before it is signed, and the server shows each part's version). (releases-and-updates-Q13) |

## Your answers

ANSWERED 2026-11-24. After answering pages 2 and 3 and most of page 4 one
by one, he said of everything still waiting: "accept all the
recommendations." So every question on this page is answered with its
recommendation.
