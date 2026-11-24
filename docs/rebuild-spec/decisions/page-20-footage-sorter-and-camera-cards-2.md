# Decision list, page 20: The Footage Sorter and camera cards, part 2

Stays behind: never shown to the session that rebuilds the product.

11 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 20.1 When a computer's drive reporting is switched off, should copies the product itself makes on that computer still reach the studio's record?

- **Today:** switching off a computer's drive reporting stops its field copies being sent in the background, but the field backup page still sends them whenever it syncs.
- **Options:** A: every verified copy the product makes always reaches the record; the switch only stops this computer's drives and their files being listed. B: the switch stops both, so copies made there stay on that computer.
- **Recommended:** A, because a copy the product made is the safety answer for a card, and one rule is simpler than a page that behaves differently from the background.
- **What you would notice:** with A an admin always sees field copies made on a laptop whose drive listing is off; with B those copies count only on that laptop.
- (footage-sorter-and-camera-cards-2-Q2)

### 20.2 Should calendar times and recorder times follow the studio's own time zone setting instead of a fixed UTC+8?

- **Today:** calendar event times are shown in a fixed UTC+8 with no daylight saving, and the recorder time zone for placing sound is fixed the same way, although the studio has a time zone setting.
- **Options:** A: both follow the studio's time zone setting (UTC+8 for this studio). B: keep the fixed UTC+8.
- **Recommended:** A, because one place a setting comes from, and a customer elsewhere would otherwise see every shoot at the wrong hour.
- **What you would notice:** nothing for this studio; a studio in another zone sees its own times.
- (footage-sorter-and-camera-cards-2-Q3)

### 20.3 Should the calendar export file stay as a way to feed shoots in when no calendar is connected?

- **Today:** events come from the connected Google calendar or, failing that, from an exported calendar archive someone downloaded; the archive never refreshes itself and only repeats daily and weekly events up to the end of 2026.
- **Options:** A: keep the export file as a fallback, reading every repeat. B: remove it; shoots come only from the connected calendar.
- **Recommended:** B, because one way in is enough and the connected calendar already keeps working offline from its last fetch.
- **What you would notice:** with B a studio must connect its calendar for suggestions; the "iCal export" state in the header goes.
- (footage-sorter-and-camera-cards-2-Q4)

### 20.4 Should the episodes, title rules and roster be managed by an admin inside the product, instead of files edited by hand on the server?

- **Today:** the rules and roster are files edited by hand on the server; they are picked up while it runs, and a rule that cannot be used is skipped without anyone being told.
- **Options:** A: an admin manages episodes, rules and the roster in the Sorter's settings, and a broken rule is shown as broken. B: keep hand-edited files on the server.
- **Recommended:** A, because every setting then has one place, and a customer's admin never needs to reach the server's files.
- **What you would notice:** with A an admin edits these in the browser and sees mistakes at once.
- (footage-sorter-and-camera-cards-2-Q5)

### 20.5 Should moving footage into its final folders be started only by an admin from the Sorter's page, with the rehearsal run by itself and its approval valid for one hour?

- **Today:** footage is moved two ways: a person runs a rehearsal and then the move by hand on the Windows computer, or an admin starts the moves on the server from the dashboard. The hand-run way refuses unless a clean rehearsal of the same plan is under 60 minutes old.
- **Options:** A: one way, from the Sorter's page: the rehearsal runs by itself when a plan is made, an admin approves by pressing Move, and the move is refused if the clean rehearsal is more than an hour old or the disk changed since. B: keep the hand-run way on the Windows computer as well.
- **Recommended:** A, because one path is fewer parts and the hour plus the re-check just before each item keeps footage as safe as the hand-run gate.
- **What you would notice:** with A nobody runs anything at a command line; an admin moves footage from the browser.
- (footage-sorter-and-camera-cards-2-Q8)

### 20.6 Should placing sound recordings use only the product's own transcription, with no paid outside speech-to-text service?

- **Today:** recordings still unplaced can have their first 10 minutes transcribed by a paid outside service, after the person sees the cost.
- **Options:** A: only the product's own transcription, run as heavy work on the studio's computers, with no keys or bills. B: keep the paid option alongside.
- **Recommended:** A, because the product already transcribes speech for every recording and a paid service adds a key, a bill and a cost forecast.
- **What you would notice:** with A nobody can spend money here; unplaced recordings are transcribed in full by the studio's own computers instead.
- (footage-sorter-and-camera-cards-2-Q10)

### 20.7 Should loose video clips be placed into shoots by sound and time in the same review as sound recordings?

- **Today:** placing loose video into shoots by matching its sound exists only as a separate command that prints counts, with no review.
- **Options:** A: fold it into the same proposals and review as sound recordings. B: drop it.
- **Recommended:** A, because it is the same matching and the same review, so it costs nothing extra and finds homes for undated clips.
- **What you would notice:** with A a loose clip gets a proposed shoot like a recording; with B it is assigned only by hand.
- (footage-sorter-and-camera-cards-2-Q11)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 20.8 | Should there be one record of where every copy is, recognising a recording by its camera's own id first and otherwise by name, size and time? | two records say whether footage is backed up. The Sorter's own record recognises a recording by the Sony camera's recording id, or by name, size and recording day. The studio-wide record of copies recognises a file by name, size and modified time within 3 seconds. A clip's details show a list from each, and they can disagree about "backed up". | A, because one record gives one answer to "is this backed up", and the camera's id is the surest identity where it exists. (footage-sorter-and-camera-cards-2-Q1) |
| 20.9 | Should building the roster from the planning sheet, planning every episode's folder skeleton, and planning every interviewee's folder be actions an admin runs from the Sorter's page? | building the roster from the planning spreadsheet and listing a season's empty folder layout exist inside the Sorter but nothing can start them; the same jobs (and planning a held folder for every interviewee) exist as tools an operator runs by hand from a command line. | A, because your ruling that every roster person appears as a greyed destination needs the interviewee folders made somehow, and the page is the one place to do it. (footage-sorter-and-camera-cards-2-Q6) |
| 20.10 | Which of the dozen ways to assign clips to a folder should stay? | dragging onto a folder, double-clicking a folder, the folder picker, a clip's own suggestion, Accept suggestions, the suggestions menu, the [ and ] keys, the clip menu's alternatives, "Use this instead" in the details, the audio worklist, and dropping files from the file manager onto a folder. | A, because each remaining way covers a different situation and the dropped ones repeat the suggestions menu or the picker. (footage-sorter-and-camera-cards-2-Q7) |
| 20.11 | Should sound recordings be reviewed in one place inside the Sorter, with the separate review page's timeline, listening, nudging and bulk approval folded in? | recordings are reviewed in two places: a view inside the Sorter (candidates, evidence, transcript) and a separate review page, opened only on the person's own computer with no sign-in, with a timeline against the cameras, listening, start nudging and bulk approval. | A, because one review gives one decision per recording and the separate page's sign-in gap goes. (footage-sorter-and-camera-cards-2-Q9) |

## Your answers

Not yet answered.
