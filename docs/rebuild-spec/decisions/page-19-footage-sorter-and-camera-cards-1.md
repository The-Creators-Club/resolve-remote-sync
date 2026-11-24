# Decision list, page 19: The Footage Sorter and camera cards, part 1

Stays behind: never shown to the session that rebuilds the product.

26 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 19.1 Should card copies only ever use the product's own copying, never a separately installed copy program on Windows?

- **Today:** on a Windows computer with a particular third-party copy program installed, card files are handed to it. A stopped copy can then leave a short file under its real name, a setting lets it copy with its own check switched off, and an installer step exists only to set that program up.
- **Options:** A: only the product's own copying, which always checks and never leaves a short file under a real name. B: keep handing copies to the outside program when it is installed.
- **Recommended:** A, it is one way of copying with one set of promises, and the safer one.
- **What you would notice:** nothing to install or set up for card copies; no "copied but nobody checked it" outcome.
- (footage-sorter-and-camera-cards-1-Q2)

### 19.2 Should cloud-storage drives be left out everywhere, including as places to copy a card to?

- **Today:** the studio's record never hears of cloud-storage drives (Google Drive, OneDrive, Dropbox and the like), but field backup offers them as places to copy a card to, where a copy could count toward "safe to format".
- **Options:** A: never seen, never offered, never counted. B: offered as places to copy to, counted. C: offered but never counted.
- **Recommended:** A, a cloud folder on a laptop is not a second physical copy until it has uploaded, so it must never make a card look safe.
- **What you would notice:** a cloud folder no longer appears in the list of places to copy to.
- (footage-sorter-and-camera-cards-1-Q4)

### 19.3 Should closing a card keep its clips' assignments, so bringing it back loses no work?

- **Today:** closing a card clears every assignment of its clips, and bringing it back returns them unassigned; a card that was pulled out keeps them.
- **Options:** A: closing keeps assignments, like pulling. B: closing clears them.
- **Recommended:** A, closing is "take it off my list", and quietly undoing sorting work is a surprise.
- **What you would notice:** a card shown again comes back as it was.
- (footage-sorter-and-camera-cards-1-Q11)

### 19.4 Should the studio have one time zone setting that everything follows, calendar matching included?

- **Today:** the studio's offset is a setting (default +8 hours), but calendar matching always reads zone-less event times at +8; the nightly work follows a second, named zone setting.
- **Options:** A: one named studio time zone that everything follows. B: keep the fixed offset and the separate nightly zone.
- **Recommended:** A, one setting, and a named zone handles summer time for a studio somewhere else.
- **What you would notice:** one setting instead of two; a customer outside +8 gets correct calendar matching.
- (footage-sorter-and-camera-cards-1-Q14)

### 19.5 Card copies can be started by anyone signed in, drive-to-drive copies only by an admin. Is that the split wanted?

- **Today:** card copies, audits and move plans are open to anyone signed in; drive copies and carrying out a move are admin only.
- **Options:** A: keep the split. B: drive copies open to anyone signed in too. C: card copies admin only.
- **Recommended:** A, a card copy only adds and never overwrites, while drive copies reach any drive in the studio.
- **What you would notice:** none with A.
- (footage-sorter-and-camera-cards-1-Q15)

### 19.6 May anyone signed in ask for the card record and the calendar to be fetched again, or only an admin?

- **Today:** anyone who can reach the Sorter may ask for a fresh card-tracker or calendar fetch, though other changes need an admin.
- **Options:** A: anyone signed in, since it changes nothing. B: admin only.
- **Recommended:** A, a refresh changes no data.
- **What you would notice:** none with A.
- (footage-sorter-and-camera-cards-1-Q16)

### 19.7 Should there be one way of placing sound recordings, combining every clue, and should it be the same as the lining-up by sound in Timeline Cards?

- **Today:** two tools propose where a sound recording belongs: one inside the Sorter (identical copies, the studio's interview transcripts, names heard, introductions, the calendar) and a separate one (recorder clocks, matching sound to the cameras, paid transcripts). Timeline Cards lines up angles by sound a third time.
- **Options:** A: one placement that combines all their clues, sharing its lining-up by sound with Timeline Cards. B: keep the two tools. C: one tool in the Sorter, separate from Timeline Cards.
- **Recommended:** A, one job done once, with every clue.
- **What you would notice:** one answer for where a recording belongs, and one place to correct it.
- (footage-sorter-and-camera-cards-1-Q17)

### 19.8 Should only 32-bit WAVs count as field recordings?

- **Today:** only 32-bit recordings count, because every recorder the studio uses writes 32-bit float; a new recorder writing 24-bit would be treated as not field sound.
- **Options:** A: keep the rule, but say why ("not 32-bit") and let a person mark a file as a field recording. B: count a WAV from a recognised recorder at any bit depth.
- **Recommended:** A, it is right for every recorder the studio owns, and with the reason shown and the override a new recorder is never silently lost.
- **What you would notice:** with B, a 24-bit recorder's files are placed like any other without being marked by hand.
- (footage-sorter-and-camera-cards-1-Q18)

### 19.9 Should automatic backup states survive a restart of the server?

- **Today:** each drive's automatic backup state (copying, done, away, error) is forgotten when the server restarts.
- **Options:** A: kept across restarts. B: forgotten.
- **Recommended:** A, a page that forgets what it did tells an admin nothing after an update.
- **What you would notice:** the last state of each drive is still shown after a restart.
- (footage-sorter-and-camera-cards-1-Q19)

### 19.10 Should wording specific to this studio come from site settings?

- **Today:** some names are this studio's own: the field-drive label pattern, the crew card tracker site and its wording, the off-site backup's provider, the production sheet named after one series, a drive letter in hints.
- **Options:** A: every such name from a site setting, with plain defaults. B: keep them written in.
- **Recommended:** A, a second studio must not see this one's names.
- **What you would notice:** nothing for this studio; another studio sets its own.
- (footage-sorter-and-camera-cards-1-Q20)

### 19.11 When a finished card cannot be marked backed up, should the person be told why on the card?

- **Today:** when its serial is not named or some clips have no copy, the card stays marked used and the reason goes only into the server's log.
- **Options:** A: say so on the card, with the reason and what to do. B: keep it in the log.
- **Recommended:** A, nothing about whether footage is safe should be silent.
- **What you would notice:** a card that stays "used" says why.
- (footage-sorter-and-camera-cards-1-Q22)

### 19.12 Should the crew's record of which cards they used on which day be part of the Footage Sorter, a phone page of its own, rather than a separate site the Sorter reads?

- **Today:** the crew record card use on the studio's own card-tracking site; the Sorter fetches it every 15 minutes with an access key, keeps a copy for offline use, and tells the site back "backed up" or "used". Your rulings ask that the card recorder page installs as an app on phones, shows English and Traditional Chinese, always accepts a new day's use, and is strict about "backed up".
- **Options:** A: the card-use page is part of the Footage Sorter (installs on phones, works offline, no access key, no fetching). B: keep the separate site and have the Sorter read it.
- **Recommended:** A, one place holds the cards and their use, so nothing has to be fetched, kept in step or keyed.
- **What you would notice:** the crew open the card-use page from the studio's own address; there is no tracker key to set up.
- (footage-sorter-and-camera-cards-1-Q23)

### 19.13 Should imaging a damaged card be offered on macOS as well as Windows?

- **Today:** taking a raw image of a whole card is offered on Windows only; whether it is offered on macOS is not known.
- **Options:** A: on both. B: Windows only, with macOS told to image the card elsewhere.
- **Recommended:** A, a Mac in the field is exactly where a damaged card is found.
- **What you would notice:** a Mac editor can image a card before formatting it.
- (footage-sorter-and-camera-cards-1-Q24)

### 19.14 Should the check that a drive really is the studio's NAS run on macOS too?

- **Today:** on Windows a drive letter is accepted as the NAS only if it carries the NAS's mark or points at the NAS's network path; on macOS it is accepted without a check.
- **Options:** A: the same check on both. B: check on Windows only.
- **Recommended:** A, a copy to the wrong place must never count as "at home" on either.
- **What you would notice:** a Mac with the wrong volume chosen is told so instead of copying there.
- (footage-sorter-and-camera-cards-1-Q25)

### 19.15 When a different file already has the name a card's file would land under, should the card's file be written beside it under a new name, or left uncopied and reported?

- **Today:** field backup leaves the card's file uncopied and reports a conflict; the Sorter writes it beside under a new name, or skips it, by a setting; one account also skips a different clip of the same size as if it were there.
- **Options:** A: always write beside ("name (2)"), never overwrite, never skip a same-size different file. B: leave it uncopied and report it. C: keep the setting.
- **Recommended:** A, the card's footage then always gets a copy, and nothing already there is touched.
- **What you would notice:** conflicts no longer leave a clip without a copy; there are occasional "name (2)" files.
- (footage-sorter-and-camera-cards-1-Q26)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 19.16 | Should there be one card copy, with the older A-CAM / B-CAM copy and its separate fallback gone? | a card can be copied four ways. Field backup on the editor's computer copies to every ticked drive at once, offline, and lands NAS copies in a "FieldBackup" folder. The Sorter's card copy reviews first and copies into the sorted folders or staging. A quick "stage this card now" skips the review and two of its refusals. And an older copy, started by a separate Windows card watcher whenever the Sorter cannot be reached (switched on by default though meant only as a stop-gap), copies Sony and Blackmagic cards into A-CAM and B-CAM transfer folders with its own windows and folder layout, no review, no record of copies and no damage check; it calls a copy "done" where the Sorter would say "done, unverified". | A, one copy that works offline already covers what the fallback was for, with every check the fallback skips. (footage-sorter-and-camera-cards-1-Q1) |
| 19.17 | Should a computer watch for cards whenever the Footage Sorter is on, with a per-computer switch to leave one out? | one account has card reporting off on every computer unless switched on for it; another has it on by default per computer, switchable off by the computer's owner. | A, cards just appear, and a laptop that should not report can still be left out. (footage-sorter-and-camera-cards-1-Q3) |
| 19.18 | Should the folders a computer offers as places to copy to be one list, whether added on the page or in the computer's settings, with Remove really removing? | folders come from the page and from the computer's own settings; those from the settings show a Remove button that does nothing visible. | A, one list and a button that does what it says. (footage-sorter-and-camera-cards-1-Q5) |
| 19.19 | A drive's kind (studio drive, laptop, client drive) can be set on the card-copy page and in the studio's list of drives. Keep both? | field backup lets the editor set a drive's kind on that computer; the studio's list of drives lets an admin set it too; the page's choice beats the record's. | A, the person with the drive in hand is the one who knows, and one value means no disagreement. (footage-sorter-and-camera-cards-1-Q6) |
| 19.20 | A card's serial can be named from the card's own view and from the list of serials nobody has named. Keep both? | both exist and do the same thing. | A, the card's view serves the card in hand and the list catches up cards already copied and gone. (footage-sorter-and-camera-cards-1-Q7) |
| 19.21 | A card copy's progress shows on the card's row, its banner, its details and in the list of everything copying. Keep all four? | all four show the same progress, plus field backup's own copy list. | A, progress where the card is and one place for everything at once. (footage-sorter-and-camera-cards-1-Q8) |
| 19.22 | Same-name clips are flagged on each clip, in the checks for missing footage, and when moving clips. Keep all three? | all three flag them (the move dialog's flag is written in part 2). | B, they answer different moments (browsing, auditing a card, moving) and none can lose footage. (footage-sorter-and-camera-cards-1-Q9) |
| 19.23 | Duplicates are left out of every move plan, and a separate admin tool also sets proven duplicates aside into a quarantine. Keep both? | both exist; the move plans skip duplicates already in place, and the tool moves proven ones aside. | A, the quarantine is the only way duplicates ever stop taking space, and it never deletes. (footage-sorter-and-camera-cards-1-Q10) |
| 19.24 | Should a person be able to point the Sorter at a folder or a card image and have it read as a card, and can the dead controls around it go? | reading a card again only redisplays it, linking a folder or detecting a card from the server is always refused, and a live card stream never carries anything; one form of the Sorter does accept a mounted card image in place of a drive. | A, recovering from a card image is exactly when the same checks are wanted. (footage-sorter-and-camera-cards-1-Q12) |
| 19.25 | Should every clip have one backup verdict, from the record of every copy? | a clip's "backed up" comes from the record of every copy (with look-alike matching) and separately from a match against what the sorted folders hold now; a clip's details show two lists of copies that can disagree. | A, two answers to "is it safe" is the one thing this part must never give. (footage-sorter-and-camera-cards-1-Q13) |
| 19.26 | Which layout of time folders is the studio's: one folder per day and camera named with its time range, or a day folder holding time-range folders? | the Sorter files staged footage in one folder per day and camera named with its time range; the older copy makes a day folder holding time-range folders. | A, one level fewer, and it is what the Sorter's moves already follow. (footage-sorter-and-camera-cards-1-Q21) |

## Your answers

Not yet answered.
