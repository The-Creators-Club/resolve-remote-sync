# Decision list, page 11: The server: installing it and keeping it running, part 1

Stays behind: never shown to the session that rebuilds the product.

21 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 11.1 Should the server still run on a TrueNAS older than 25.04?

- **Today:** an older TrueNAS works through its older management interface, with a note that it is not supported.
- **Options:** A: refuse a TrueNAS older than 25.04 with the reason and "upgrade to 25.04 or later". B: keep it working with a note.
- **Recommended:** A, because supporting an interface that later TrueNAS versions removed is a part kept only for old boxes.
- **What you would notice:** with A a studio on an old TrueNAS must upgrade the NAS first.
- (server-install-and-running-1-Q5)

### 11.2 Should per-project privacy be offered on Synology, where it needs a step by hand in DSM?

- **Today:** on TrueNAS each project can have its own group and is protected against other editors deleting it; on Synology the share-wide editors' rule still lets every editor in until someone breaks inheritance by hand in File Station, and project folders are not protected against deletion.
- **Options:** A: offer it on both, and on Synology tell the admin plainly the step to take in DSM. B: offer it on TrueNAS only. C: refuse Synology sites that want private projects.
- **Recommended:** A, because Synology gives no way to do it from outside and saying so is the fewest parts.
- **What you would notice:** with A a Synology admin who wants private projects must do one step per project in DSM.
- (server-install-and-running-1-Q6)

### 11.3 Is it acceptable that on Synology regular snapshots may need steps by hand?

- **Today:** on TrueNAS the server makes and confirms the snapshot schedules; on Synology it needs DSM's Snapshot Replication package, falls back to steps by hand, and always reports "created".
- **Options:** A: accept steps by hand on Synology, never say "created" unless confirmed, and keep the protection lines at "cannot verify". B: refuse to finish set-up on a Synology until snapshots are confirmed.
- **Recommended:** A, because Synology's schedules cannot be read from outside, so B could never be satisfied.
- **What you would notice:** with A a Synology admin follows the steps and the protection list keeps saying it cannot verify.
- (server-install-and-running-1-Q7)

### 11.4 Should every piece of extra software the parts need follow the version the product approves?

- **Today:** the Timeline Cards editor's software is replaced when the approved version changes; the media converter and the YouTube helper stay at whatever version was first installed.
- **Options:** A: every one follows the approved version. B: keep the difference.
- **Recommended:** A, one rule for all.
- **What you would notice:** with A a fix in the media converter reaches the studio with the next release.
- (server-install-and-running-1-Q8)

### 11.5 Should a risky change across the whole tree stop when no snapshot could be taken first?

- **Today:** the snapshot is best effort: if it cannot be taken the person is warned and the change goes on, unless a strict mode was asked for.
- **Options:** A: stop, unless the admin accepts in words that the change has nothing behind it. B: warn and go on.
- **Recommended:** A, because footage is at stake and the admin can still choose to go on.
- **What you would notice:** with A an admin on a NAS without snapshots must confirm once per such change.
- (server-install-and-running-1-Q12)

### 11.6 Should every action that changes the NAS show its preview first?

- **Today:** some actions preview by default and need a confirmation, others act at once, with no clear rule.
- **Options:** A: every action can be previewed; those that sweep a whole tree or cannot be undone always show the preview first and ask for the NAS's name; the rest act at once. B: every action previews first and asks.
- **Recommended:** A, a clear rule without slowing everyday actions.
- **What you would notice:** with A everyday changes need one click; sweeping ones always show what they will do.
- (server-install-and-running-1-Q14)

### 11.7 Is the off-site backup part of the server that is always there, rather than part of the Footage Sorter?

- **Today:** the off-site backup is shown and scheduled from the Footage Sorter's pages, while the NAS runs it on its own.
- **Options:** A: part of the always-on server, shown in the dashboard; only the record of every copy needs the Footage Sorter. B: part of the Footage Sorter, gone when it is off.
- **Recommended:** A, because protecting the studio's work does not depend on camera cards.
- **What you would notice:** with B a studio without the Footage Sorter has no off-site backup.
- (server-install-and-running-1-Q16)

### 11.8 Should a signed-in person keep getting the fuller health summary from "is the dashboard up?"

- **Today:** anyone gets healthy or not and the version; a signed-in person or a computer also gets a large summary that repeats what the overview shows admins.
- **Options:** A: cut the summary; the short answer stays and the overview shows the rest. B: keep it.
- **Recommended:** A, because the overview already shows it.
- **What you would notice:** none for an admin; nobody reads the summary elsewhere.
- (server-install-and-running-1-Q17)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 11.9 | Should the set-up task list be one page that an admin lands on until set-up is finished and finds in settings afterwards? | the same task list appears as the first-run wizard and again among the admin's settings. | A, because it is one page reached two ways, not two things. (server-install-and-running-1-Q1) |
| 11.10 | Should set-up check that a Synology's secure file transfer service is switched on? | the server can ask DSM whether the service is on, but nothing shows or uses the answer. | A, because without the service no editor can transfer anything, and the check is one question. (server-install-and-running-1-Q2) |
| 11.11 | Should the server check, on a Synology, that the tree's folders keep their access rules? | a check exists that tells a folder's Synology access rules are intact, gone, or missing the editors' rule, with the repair; nothing runs it. | A, because a folder that loses its rules makes new files writable by everyone and nothing else would say so. (server-install-and-running-1-Q3) |
| 11.12 | Should there be one health check of the whole server side, shown in the dashboard? | the server is checked from the admin's own computer by one tool and again, differently, at the end of every install or update. | A, one check in one place with the fewest parts. (server-install-and-running-1-Q4) |
| 11.13 | Should the software for signed-in YouTube downloads be fetched only with YouTube's anti-blocking measures switched on? | it is installed only when the anti-blocking part of YouTube downloads is on, which is off for every studio by default. | A, because the text then has one rule: a part gets what it needs when it is on. (server-install-and-running-1-Q9) |
| 11.14 | Should the switches that are off for every studio by default stay (YouTube's anti-blocking measures, automatic updates of editors' apps)? | both exist, are off unless a studio turns them on, and the install only notes them. | A for automatic updates (a studio may want it); the anti-blocking measures follow the YouTube piece's decision. (server-install-and-running-1-Q10) |
| 11.15 | Can the server's own spare copy of the syncing, off unless started on purpose, go? | the server can run a second copy of its syncing for the whole tree, switched off unless someone starts it. | A, because nobody uses it and the server's syncing is already there. (server-install-and-running-1-Q11) |
| 11.16 | Should "a restore was tried" be recordable both by an admin's typed date and by the server's own restore rehearsal? | an admin can record a date by hand, and a successful one-file rehearsal also records it; both turn the same line green. | A, because each covers a restore the other cannot. (server-install-and-running-1-Q13) |
| 11.17 | At what point should an admin be warned that the server's disk is running out? | one check warns under 10 percent free, another under 2 GB free, in different words. | A, because a small disk and a large one each need one of the two. (server-install-and-running-1-Q15) |
| 11.18 | Should the two facts that can never be checked be made checkable? | "deleted-file keeping agrees between the server and the editors' computers" and "each part on the server is the version that was shipped" always show as not checked. | A, because both protect footage or a correct server and a line that is never checked teaches people to ignore it. (server-install-and-running-1-Q18) |
| 11.19 | Can sending crashes to the vendor, and keeping a server log file, go? | both are off unless set when the server is installed; sending crashes is not even complete. | A, because the download already gets the reports to support. (server-install-and-running-1-Q19) |
| 11.20 | Should the server's twice-daily check run on the assistant the site has set up, with no assistant program installed on the server? | the check runs only on an assistant program installed and signed in on the server, which is off in the vendor's build and missing from some builds; otherwise an admin types where a copy is. | A, fewest parts and one assistant for the whole product. (server-install-and-running-1-Q20) |
| 11.21 | Can the tools for the product's builders go: the testing switch that turns off the server's security, a helper that deletes test accounts on a Synology, and a one-off command that runs the gathering jobs once? | a switch lets the server start with weak or lost secrets and accept computers with no credential (announced loudly, with a problem shown when it is on); a helper deletes test accounts; a command runs the main jobs once and prints the results. | A. (server-install-and-running-1-Q21) |

## Your answers

Not yet answered.
