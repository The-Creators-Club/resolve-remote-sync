# Answers against lessons: server-install-and-running

## Lessons

### SRV-014: amend
- Answer: page 11, 11.2 (all recommendations accepted, 2026-11-24): "A: offer it on both, and on Synology tell the admin plainly the step to take in DSM." And 11.3: "A: accept steps by hand on Synology, never say \"created\" unless confirmed, and keep the protection lines at \"cannot verify\"." Earlier ruling quoted in the lesson: "make it run on synology also".
- Lesson says: "Installing and running every server feature works the same on a Synology and on a TrueNAS, from the same release."
- Field: must
- New words: Every server feature installs and runs on a Synology and a TrueNAS from the same release; what a Synology cannot do from outside, the admin is told to do on it.
- Because: he accepted that per-project privacy and snapshot schedules on a Synology are steps the admin takes by hand in DSM, so "works the same" no longer holds there.
- Doubt: "works the same" may have meant the same result for the person, which 12.1 ("one result on both ... with each NAS's own facts stated") keeps; if so the lesson stands. Settled by asking whether a step by hand in DSM counts as "the same".

### SRV-015: amend
- Answer: page 11, 11.2: "on Synology tell the admin plainly the step to take in DSM" ("with A a Synology admin who wants private projects must do one step per project in DSM"); 11.3: "accept steps by hand on Synology". Earlier ruling quoted in the lesson: the admin should "do nothing except install".
- Lesson says: "with no commands, builds, signing keys or manual steps on the customer's side."
- Field: must
- New words: A new studio is set up from a browser wizard after those installs, with no commands, builds or signing keys; steps by hand only where a Synology allows nothing else.
- Because: his later answers accept steps by hand in DSM on a Synology for private projects and snapshots, which the lesson's "no manual steps" forbids outright.
- Doubt: the steps are optional (private projects, snapshots) rather than part of setting the studio up; if "set up" means only the required tasks, the lesson stands. Settled by whether optional protections count as set-up.

### SRV-079: amend
- Answer: page 11, 11.16 (accepted): "an admin can record a date by hand, and a successful one-file rehearsal also records it; both turn the same line green. A, because each covers a restore the other cannot."
- Lesson says: "a test restore counts only when the bytes match."
- Field: must
- New words: The owner restores from any snapshot in the dashboard into a separate folder, overwriting nothing; a test restore counts when its bytes match or an admin records its date.
- Because: he kept the admin's typed date as a second way to record that a restore was tried, so a byte match is not the only thing that counts.
- Doubt: the lesson may speak only of the dashboard's own rehearsal, beside which the typed date is a separate record; if so it stands. Settled by whether "counts" means the protection line turning green.

## Read

- lessons read: 126
- decision questions read: 116 (pages 1, 2, 3, 9, 11, 12, 30, 31 in full, and pages 5, 7, 10 for lessons touching alerts, releases and the private network)

Left alone because they turn on a point not settled:
- whether a new computer waits for an admin's approval: SRV-123
- whether footage may travel through a service outside the studio's private network: SRV-010, SRV-016
