# Answers against lessons: releases-and-updates

## Lessons

### APP-068: amend
- Answer: page 10, 10.2 (recommendation accepted, "accept all the recommendations"): "A: one rule: the second failed start or crash within ten minutes of the new version's first start puts the previous one back (one failure is forgiven, for antivirus holding the file)." Also page 8, 8.11 (accepted): "A, because one rule says one thing to the editor and admin"
- Lesson says: "After two failed starts of a new build, the app restores the previous build by itself"
- Field: must
- New words: A second failed start or crash within ten minutes of a new build's first start restores the previous build by itself, and syncing resumes with no one touching the machine.
- Because: he chose one rule for going back, counting crashes as well as failed starts and bounded to ten minutes from the new version's first start.

### REL-048: amend
- Answer: page 10, 10.2 (recommendation accepted): "A: one rule: the second failed start or crash within ten minutes of the new version's first start puts the previous one back"; "with A, a version that crashes twice is replaced after the second crash instead of the third."
- Lesson says: "three crashing starts within 10 minutes restore it"
- Field: must
- New words: The previous build stays until the new one proves healthy; a second failed start or crash within 10 minutes restores it, never below the signed minimum, telling the editor.
- Because: he chose going back on the second failure within ten minutes, not the third.

### REL-020: amend
- Answer: page 10, 10.3 (recommendation accepted): "A: one publish; the vendor's studio is simply the first site reading the vendor's list, with its own trial on one computer; customers are offered it after 24 hours on the studio and a second person's approval."
- Lesson says: "One command builds, publishes and offers a release to every computer"
- Field: must
- New words: One command builds and publishes a release, refusing before anything moves if a check fails.
- Because: his ruling of one command stands, but by his later answer a published release is not offered to every computer at once: the studio tries it first and customers wait 24 hours and a second person's approval (earlier ruling quoted in the lesson's Why: "there used to be one command which did all of this ... rebuild, pushed it to dashboard, pushed to tray utility").

### REL-072: amend
- Answer: page 10, 10.3 (recommendation accepted): "customers are offered it after 24 hours on the studio and a second person's approval." ("with A, the vendor needs a second person to approve every customer release")
- Lesson says: "refused until that same build ran 24 hours on the studio."
- Field: must
- New words: A customer site updates only to the exact build named for it, refused until that same build ran 24 hours on the studio and a second person approved it.
- Because: his earlier ruling ("customers pinned by digest, with vendor soak") gains a second person's approval by his later answer on the same path to customers.

### REL-044: amend
- Answer: page 10, 10.9 (recommendation accepted; option A in the trace, releases-and-updates-Q8): "A: \"try first\": new versions arrive by themselves, held back, and wait for the admin to try one on a computer and make it current."
- Lesson says: "every signed-in computer is offered a newly published update within minutes."
- Field: must
- New words: Pressing update responds visibly at once, and every signed-in computer is offered a newly current update within minutes.
- Because: a newly published version is held back on a site until an admin tries it and makes it current, so the offer follows becoming current, not publishing.

### REL-036: amend
- Answer: page 10, 10.3 (recommendation accepted): "A: one publish; the vendor's studio is simply the first site reading the vendor's list"; and OWNER_REQUIREMENTS section 1: "One way to do each thing: ... one way to publish a new version."
- Lesson says: "an unsigned build needs its version typed"
- Field: must
- New words: Every way of making a build current passes the same checks, and a refusal says why and leaves current alone.
- Because: with versions reaching a site only through the vendor's signed list, no unsigned build can be held, so the clause has nothing to test.
- Doubt: rests on reading "one publish" as leaving no way for an unsigned build onto a site; settled if no site may hold a build that did not come through the vendor's signed list.

### REL-038: amend
- Answer: page 10, 10.3 (recommendation accepted): "A: one publish; the vendor's studio is simply the first site reading the vendor's list ... because it is one way to publish, the studio tests exactly what customers receive"; option C, "keep the studio's own direct release beside the customer one", not chosen.
- Lesson says: "and only truly modified builds are marked so" (and in Why: "builds served here before those offered by the vendor")
- Field: must
- New words: Each product and platform shows its newest build first, older ones only in a rollback picker, and one place updates everything.
- Because: with the studio's own direct release gone, every build a site holds is the unmodified one from the vendor's list, so neither a modified mark nor a "served here" group remains.
- Doubt: this is a ruling about the builds list, and his later answer is about the publishing path, not the list; settled by whether any build other than the vendor's published one can appear on a site's list.

### REL-065: amend
- Answer: OWNER_REQUIREMENTS section 1, "The language": "The app on an editor's computer and the server are written in Rust: one native program on each, light, quick to start, with one version number." Page 30, 30.14 (accepted): "One installed program instead of several".
- Lesson says: "A change to one part (editor, b-roll, music, downloader) is tested and shipped without retesting or redeploying the unrelated parts."
- Field: must
- New words: (none proposed until settled)
- Because: "one native program ... with one version number" on the server may mean a part's change ships as a new server version, which would clash with shipping a part without redeploying the rest.
- Doubt: OWNER_REQUIREMENTS section 2 keeps his words that each part "can be maintained, updated, enabled and disabled individually", "a self contained separately versioned folder per module", which agree with the lesson; settled by whether a part's change reaches a site without a new version of the whole server program. If it does, the lesson stands unchanged.

## Read

- lessons read: 81
- decision questions read: 76 (page 10: 13, page 8: 19, page 3: 10, page 30: 14, page 31: 4, and pages 1 and 2 of DECISIONS.md: 16)
