# Decision list, page 6: The dashboard, part 1

Stays behind: never shown to the session that rebuilds the product.

17 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 6.1 Should a person's computers beyond the twenty most recently heard from silently lose their details?

- **Today:** after every report, only a person's 20 most recently heard-from computers keep their latest details; an older one loses them silently and, if it still has ticks, shows as lost.
- **Options:** A: no limit; a computer leaves only when forgotten, and the lost and two-week rules handle silent ones. B: keep the limit of 20, and tell the admin when it drops one.
- **Recommended:** A, fewer rules, and nothing vanishes without a person choosing it.
- **What you would notice:** none for any studio with fewer than 20 computers per person.
- (dashboard-1-Q12)

### 6.2 Should diagnostics and finished transfers each be kept by age alone?

- **Today:** diagnostics are kept both to the newest 5 per computer and to 30 days; finished transfers both to the newest 300 per computer and to 7 days.
- **Options:** A: age only: diagnostics 30 days, finished transfers 7 days. B: keep both limits on each.
- **Recommended:** A, one limit each, and the age is the one a person can plan around.
- **What you would notice:** a computer that sends many diagnostics in a month keeps all of them.
- (dashboard-1-Q13)

### 6.3 Should a file that finished arriving at the server always name the computer that sent it?

- **Today:** a file that finishes arriving on the NAS is credited to an editor only when exactly one editor's computer receives that project; otherwise to nobody.
- **Options:** A: every finished upload is recorded once, credited to the computer that sent it, and to nobody only when that truly cannot be known. B: keep crediting only when one computer takes the project.
- **Recommended:** A, the history should say who sent each file, and a file should not be listed twice.
- **What you would notice:** the history names who uploaded what on shared projects.
- (dashboard-1-Q14)

### 6.4 How often should a running computer be heard from?

- **Today:** descriptions disagree: one says every computer is heard from about every 30 seconds, another about once a minute (never more often than every 30 seconds), and while files move every 5 seconds; the admin is told a request will arrive "usually within 30 s".
- **Options:** A: about every 30 seconds, and every few seconds while files are moving. B: about once a minute, and every few seconds while files are moving.
- **Recommended:** A, so that "usually within 30 s" is true and an asleep computer goes amber on time.
- **What you would notice:** with B, requests to a computer take up to a minute to arrive.
- (dashboard-1-Q17)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 6.5 | From which places can a project be ticked and unticked? | a project can be ticked or unticked from six places: the project list, the project's own page, the sync queue on the overview, the sync queue on a person's own page, each computer on a person's own page, and the admin's plan grid. All follow the same rules. | A, because the Projects page is where you asked for ticking to live and the grid is the one place an admin sees a whole computer's plan; the rest repeat them. (dashboard-1-Q1) |
| 6.6 | Should what is moving right now be shown on the Overview as well as on the Transfers page? | a short scrolling list of moving files sits on the overview, and the full list is on the transfers view; the "safe to close" sentence appears in three places. | A, one list of moving files and one readout that leads to it. (dashboard-1-Q2) |
| 6.7 | Should every problem, alert and check live in one list on the Overview, instead of being repeated in a health summary and in each source's own list? | the problems the server found and the diagnostics computers sent are shown both on the overview and in a separate health summary; the summary also repeats the alerts, the always-true facts and the protection lines, which each have their own full list too (protection a third time in the recovery guide). | A, because your lesson asks for one ranked list and repeating it in three places is three things to keep in step. (dashboard-1-Q3) |
| 6.8 | Where should the studio-wide stop be found? | it is shown or reachable in five places: a banner on every page, a banner over the computers list, the stop control itself, a shortcut on the overview, and a line in a person's list of settings. | A, one place to press and one way to be told. (dashboard-1-Q4) |
| 6.9 | Should the project list appear only on the Projects page? | the same list of projects appears on the overview and again beside every project's page. | A, the Overview carries the summary and the Projects page the list. (dashboard-1-Q5) |
| 6.10 | Should there be one way to make an existing folder a project? | "Use this folder" makes an existing folder a project and changes nothing inside it; creating a project while choosing to use an existing folder of that name does the same but also adds the standard subfolders. Only creating is recorded in the history. | A, one act per job, and every act in the history. (dashboard-1-Q6) |
| 6.11 | From where can an admin forget a computer? | from the list of lost computers and from the list of every computer, with two different questions. | A, one act and one question, reachable wherever the admin meets the computer. (dashboard-1-Q7) |
| 6.12 | Should "Ask this computer why" be offered on a person's page as well as in the computer's details? | an admin can ask from a computer's details on the computers list and from each computer on a person's own page. | A, since a person's page leads to each computer's details anyway. (dashboard-1-Q8) |
| 6.13 | Should the sync queue offer a picker of projects not yet ticked? | the product still works out which projects a person has not ticked, for a picker that once sat in the queue panel, but nothing shows it. | A, it repeats the Projects page. (dashboard-1-Q9) |
| 6.14 | When the NAS seems to have lost many projects at once, should an admin be able to take them off the lists anyway? | if one look at the NAS would take out more than a quarter of the projects, nothing is taken out and a banner stays until a later look agrees. A way to take them out anyway exists but nothing can reach it. | A, because after a real reorganisation of the NAS the banner would otherwise never go away, and "there must always be a manual override". (dashboard-1-Q10) |
| 6.15 | Should every request aimed at one computer behave the same way: wait up to 14 days, follow a rename, never go to a clone? | requests waiting for one computer (a pushed update, a resume of downloading, a diagnostics ask, a file move, a Resolve undo, a settings change, a cancel) each expire differently (14 days, never, 7 days) and only some follow a renamed computer. | A, one way of telling a computer something. (dashboard-1-Q11) |
| 6.16 | Should every reader see the same help documents everywhere, with nothing extra for admins on the vendor's own copy? | on the vendor's development copy, admins see every internal document in the help reader; on a studio's server everyone sees the same set. This is the only tool for the builders in this piece. | A, the builders make their own tools. (dashboard-1-Q15) |
| 6.17 | Should a computer's diagnostics keep reaching the admin in all three ways? | diagnostics reach the admin when the editor presses the button in the app, automatically when a kind of syncing falls into an error, and when an admin asks the computer why. | A, because each serves someone the others do not (the editor who notices first, the admin who notices later, and nobody noticing at all). (dashboard-1-Q16) |

## Your answers

ANSWERED 2026-11-24. After answering pages 2 and 3 and most of page 4 one
by one, he said of everything still waiting: "accept all the
recommendations." So every question on this page is answered with its
recommendation.
