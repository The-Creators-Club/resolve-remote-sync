# Answers against lessons: proxies-and-file-moves

## Lessons

### PRX-030: amend
- Answer: page 16, question 16.7 (all recommendations accepted): "A: one quiet time and one Resolve hold-back per computer, the ones shared work already has, used by describing too." With page 13, question 13.6 (accepted): "a quiet time of 0 says it plainly for the computers that really are nobody's desk."
- Lesson says: "Proxy making starts after 5 minutes without input"
- Field: must
- New words: Proxy making starts after the computer's quiet time without input (5 minutes unless changed), treats unknown idleness as busy, stops within seconds of input and discards its partial file.
- Because: proxy making no longer has its own fixed 5-minute wait. It uses the computer's one quiet time, which is 5 minutes by default and is set to 0 on a computer nobody sits at.

### PRX-031: amend
- Answer: page 16, question 16.7 (accepted), whose Today reads "proxies do not hold back while Resolve is open while the other two do", answered "A: one quiet time and one Resolve hold-back per computer, the ones shared work already has". The shared-work hold-back it adopts is on by default and takes no new work while Resolve is open.
- Lesson says: "dropping to one whenever Resolve is open or rendering, even on a forced run; each computer can override"
- Field: must
- New words: An idle computer encodes several proxies in parallel; while Resolve is open or rendering it starts none, even on a forced run, unless the computer's Resolve hold-back is off.
- Because: proxy making takes over the computer's one Resolve hold-back, which by default holds work back entirely while Resolve is open, instead of dropping to one encode at a time.
- Doubt: the answer does not say whether a computer with its hold-back off still drops to one encode while Resolve is open. It also does not say whether rendering holds work back even with the hold-back off, which is what shared work does ("never while Resolve is rendering"). Both are settled by how the shared-work hold-back is written for proxies.

### PRX-032: amend
- Answer: page 4, question 4.14 (answered one by one, as recommended): "A: one floor per computer (20 GB by default) decides when downloads pause and restart, when recovery copies are dropped, and every \"has stopped\" verdict and alert". With page 16, question 16.6 (accepted), whose Today names "proxies made (20 GB and 5%)", answered "A: one floor per computer, checked by one rule (what is about to be written, plus the floor) every time."
- Lesson says: "Proxy making keeps at least 20 GB or 5 percent free"
- Field: must
- New words: Proxy making keeps the computer's one free-space floor clear beyond what it writes, waits for two equal size-and-time samples, and never encodes proxy-folder, partial or its own files.
- Because: proxy making no longer has its own floor of 20 GB or 5 percent. It uses the computer's single free-space floor, checked against what is about to be written.

### PRX-063: amend
- Answer: page 6, question 6.15 (accepted): "A, one way of telling a computer something". The recorded option is "A: one rule for every request: it waits until carried out or 14 days, follows a rename, and is never delivered to another computer claiming the same identity", and it changes this for a person: "a resume or a file move that never reaches a computer now lapses after 14 days and says so, instead of waiting for ever."
- Lesson says: "A move waits for each computer however long it is offline or its drive is away; expiry measures only silence, on the server's clock."
- Field: must
- New words: A move waits for each computer while it is offline or its drive is away, lapsing only after 14 days, on the server's clock, and a lapsed move says so.
- Because: a file move now follows the one rule for every request to a computer, which lapses at 14 days and says so, instead of waiting however long.
- Doubt: the answer does not say whether the 14 days count from sending or from the computer's last contact, so it is unclear whether "expiry measures only silence" survives. A computer answering "waiting for the sync drive" would keep a move alive only under the second reading. The dashboard piece's wording for requests to one computer settles it.

### PRX-098: amend
- Answer: page 6, question 6.10 (accepted), recorded as "A: one way: \"Use this folder\" never changes anything inside; creating only ever makes a new folder and, when the name exists, points to \"Use this folder\"". It changes this for a person: "using an existing folder never adds subfolders; anyone wanting them adds them by hand."
- Lesson says: "Creating or adopting a project adds missing template folders"
- Field: must
- New words: Creating a project lays down the studio's template folders; using an existing folder adds none; neither ever moves, renames or overwrites a folder or file already there.
- Because: the owner's later answer is that making an existing folder a project changes nothing inside it, so template folders come only with a newly created project.

### PRX-098: amend
- Answer: page 6, question 6.10, as above.
- Lesson says: "including on folders already holding interviewee footage"
- Field: why
- New words: The owner wanted the standard folders laid down at project start; an existing folder holding interviewee footage, made a project, is left exactly as it is.
- Because: his earlier wish for template folders on existing folders is the part that 6.10 reversed.

## Read

- lessons read: 97
- decision questions read: 103 (page 14: 3; page 4: 21; page 13: 12; page 3: 10; page 30: 14; page 31: 4; page 15: 12; page 16: 16.5 to 16.7; page 6: 6.10 to 6.17; DECISIONS pages 1 and 2: 16)
