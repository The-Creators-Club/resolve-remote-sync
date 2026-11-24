# Work shared out across the computers

The product needs heavy work done: transcribing speech, making small preview copies of clips, pulling the sound out of clips, drawing waveforms, analysing b-roll and music, copying camera cards and drives, and reading what is on a drive. Every such piece of work is done on one of the studio's computers that is able and free, and this is the one place that decides which. Each editor decides whether their computer takes part, which kinds of work it takes, and can lend it for a while even when they are at it. An admin sees every piece of work that is waiting, running and finished, can start one now on a chosen computer, cancel it or try it again, and always gets an honest answer, in words, to "why is this not running". This is always available and cannot be switched off; a kind of work that belongs to a part that is switched off is not shown anywhere, not even as a tick box.

## When a computer counts as free and able

### A computer takes shared work only while nobody is using it

A computer is given a piece of shared work only after nobody has touched its keyboard or mouse for long enough for that kind of work:

| Kind of work | Nobody at the keyboard or mouse for |
|---|---|
| Transcribing speech, preview copies, analysing b-roll or music | the computer's quiet time, 5 minutes unless changed. A clip or track whose analysis fails is tried twice in all, then left as failed until a person asks again |
| Pulling the sound out of a clip, drawing a waveform | 1 minute |
| Copying a camera card, copying a drive, reading a drive | no wait: a person started it by plugging something in |

A computer also takes no new shared work while Resolve is open on it, and never while Resolve is rendering, whether or not anyone is at the keyboard.

How long nobody has been at a computer is always told correctly, however long the computer has been switched on. Whenever it cannot be told, or the answer cannot be read, every part of the product treats someone as being at the computer.

- On its own: whether a computer is free, from how long its keyboard and mouse have been left alone and whether Resolve is open or rendering.
- By hand: the person at the computer can lend it now, which skips the wait (see "The person at a computer can lend it to shared work for a while"); an admin can start a piece of work now (see "An admin can start waiting work now, on a chosen computer"); and the computer's quiet time and the hold-back for Resolve are settings of the computer.
- Setting: Quiet time before shared work. Does: how long nobody must have used this computer before it takes heavy shared work; 0 means it never waits, which is how a computer nobody sits at is set, and its wait is then shown as "no wait". Default: 5 minutes. Who: the computer's own person, on the computer. Applies to: a computer. Search words: idle, quiet time, away, wait, fleet.
- Setting: Hold shared work back while Resolve is open. Does: when on, this computer takes no new shared work while Resolve is open on it. Default: on. Who: the computer's own person, on the computer. Applies to: a computer. Search words: Resolve open, editing, hold back, fleet work.
- Windows and macOS: on Windows only the person's own session counts, so another user signed in to the computer or a remote session does not make it busy. On macOS the time since the last input is read from the system. On any other system it can never be told, so work that waits for quiet never runs there.

### Work already running is finished when the person comes back

When someone starts using the keyboard or mouse, or opens Resolve, the computer takes no new shared work, but finishes the piece it is running. A long piece of work is never killed because its person came back.

### The person at a computer can lend it to shared work for a while

From the app on their own computer, the person at it can lend the computer to shared work now, for a set time. The menu item reads "Take fleet jobs now (N min)", where N is the computer's lending period. While it is lent the item reads "Taking fleet jobs until HH:MM (click to stop)" with a tick ("Taking fleet jobs now (click to stop)" when the end time cannot be read). Turning it on says "Taking fleet jobs for the next N minutes, even while you work."; turning it off, or the time running out by itself, says "Back to taking fleet jobs only while you are away."

Until the end time the computer takes any kind of work it can do without waiting for quiet and even with Resolve open, and it becomes first choice for transcribing, preview copies, sound and waveforms. It does not lift the rest after a failure, nor any other reason a computer is passed over. An end time that cannot be read, or has passed, counts as not lent. Work taken while lent records "You lent this computer to the fleet, so it took this job while you are here." The dashboard shows a lent computer as "volunteering until <time>", in the viewer's local time.

The item is present only while this computer takes shared work.

- Who: the person at the computer.
- Ways in: from the app on that computer only. Nothing on the dashboard lends a computer.
- Setting: Lending period. Does: how long one click of "Take fleet jobs now" lends this computer: "LEND THIS COMPUTER FOR N minutes AT A TIME (click for M)" steps through 15, 30, 60 and 120 minutes, saying "One click of 'Take fleet jobs now' will lend this computer for M minutes." Default: 30 minutes. Who: the computer's own person, on the computer. Applies to: a computer. Search words: lend, volunteer, take jobs now, fleet.

### A computer's own heavy work comes first

A computer's own heavy work for its own editor (making proxies for it, see Proxies and file moves: Making proxies on editors' computers) comes before shared work. While it is busy with its own heavy work, it takes no shared work and says "This computer is busy with your own work, so it is not taking fleet work." with what that work is; when it cannot be checked whether it is busy, it counts as busy. Being busy with its own work never counts against the computer: it is not rested as if work had failed.

All work on one computer's graphics card takes turns: shared work never starts on a graphics card that the computer's own work is using.

Only one progress window for the computer's own heavy work is open at a time: opening another closes the first. A set-up problem with the computer's own proxy making does not stop shared work.

### A computer says in one sentence whether it is taking shared work and why not

The computer's state is one sentence, shown in its menu and its settings window and on the dashboard. The first of these that applies is the one shown:

1. "Fleet jobs are switched off on this computer."
2. "This computer is not connected to the studio's server, so it cannot be given work."
3. "Your admin has stopped syncing for the whole fleet, so this computer is not taking work of any kind." (also when the stop cannot be checked)
4. "This computer is running a fleet job." ("Your admin asked this computer to run a fleet job now." when the admin started it now.)
5. "This computer is not set up for any of the kinds of work the fleet queues." followed by "It is set to take only: <kinds>." or a sentence naming what it lacks for the kinds that are queued.
6. "This computer is busy with your own work, so it is not taking fleet work." with what that work is, or that it could not be checked.
7. "Somebody is at this computer, so it is not taking fleet work. It waits for <N minutes> of quiet." (also when it cannot be told)
8. "Resolve is open here, so this computer is not taking fleet work." (also when that cannot be checked)
9. "This computer is ready for fleet work."

Sentences 7 and 8 are skipped while the computer is lent and for work an admin started now; nothing skips sentences 1 to 6. A computer that is free and simply has nothing to do counts as taking work. The sentence describes only the present check, never a reason left over from an earlier one. On the dashboard the same state reads "Taking fleet work", "Taking fleet work while nobody is using it", "Not taking work: switched off on this computer", "Not taking work: <reason>", or "Not taking work: not heard from" for a computer that has gone quiet.

- Ways in: the app's menu and settings window on the computer, the computer's own row on the dashboard, and the per-computer view.

### The reasons a computer is passed over for a piece of work

For each piece of work, every computer is either able to take it or passed over for one reason. The first of these that applies is the reason given for that computer:

1. As many of that kind as the studio allows at once are already running ("<N> <kind> job(s) are already running, which is this fleet's limit (<limit>); it starts as soon as one finishes").
2. The work is meant for another computer ("this job is for <computer> only").
3. The computer lacks something the work needs (see "Work that needs something a computer lacks says exactly what is missing").
4. "syncing is stopped by your admin for the whole fleet".
5. "this computer has not been heard from since <time> (<N min / N h / N days> ago), so it cannot take anything until it is switched on": after 15 minutes of silence. A time that cannot be read is not treated as silence.
6. "syncing is stopped on this computer".
7. "this computer has an update waiting to apply". An update that cannot reach that computer does not hold work back: the computer stays able for every kind it can do, and the admin is shown why it was not updated.
8. "this computer's proxy download stopped itself, so it is not in a state anyone should add work to" (see Sync: Safety stops).
9. "this computer is already holding job #<number> (<kind>)".
10. "this computer has not said what it can do".
11. "fleet jobs are switched off on this computer".
12. "this computer takes only <kinds> jobs, not <kind>".
13. "this computer is busy with its own work" (naming the work).
14. "this computer is resting until <time> (<why, by default 'a job failed here'>)".
15. Somebody is at the computer: "somebody is at this computer (idle <N> s, <kind> needs <M> s)", "this computer cannot say how long it has been idle, which counts as somebody being at it", or "this computer's idle answer is unreadable".
16. Another computer is better placed, and the minute it is given first has not run out (see "The best-placed able computer is asked first").

Only computers heard from in the last 15 minutes are ever offered work or counted as able; a computer that has gone quiet is named as the reason a piece of work waits.

### Work that needs something a computer lacks says exactly what is missing

When a computer cannot do a piece of work, the reason names exactly what is missing:

- a shared folder it cannot reach right now: "this computer has no <folder> it can reach right now";
- a thing it has or has not got: "<thing> is not available on this computer";
- an amount: "<thing> is <value>, the job needs at least <amount>" (for example the graphics card's memory);
- anything else: "<thing> is <value>, the job needs <value>".

When a computer is missing a tool because fetching that tool keeps failing on it, the reason adds "the <tool> install on this computer is failing (<N> tries): <cause>" (the count only when above 1).

#### Lessons

- Met: JOB-001, JOB-002, JOB-003, JOB-004, JOB-005, JOB-006.

## What a computer can honestly offer

### The kinds of shared work and what each needs

| Kind of work | Shown to people as | Asked for by | What the computer needs |
|---|---|---|---|
| Transcribing speech | Transcribe audio (uses the graphics card) | Timeline Cards | a graphics card with at least the memory the work states (6 GB unless the work says otherwise), the transcription set-up, and the episodes folder |
| Small preview copy of a clip | Make small preview copies of video | Timeline Cards | the video tools, and the folders the clip and its copy are in |
| Pulling the sound out of a clip | Pull the audio out of video | Timeline Cards | the video tools, and the folders the clip and its sound are in |
| Drawing a clip's waveform | Draw audio waveforms | Timeline Cards | the video tools, and the folders the clip and its waveform are in |
| Analysing b-roll clips | Analyse b-roll | the b-roll archive | what the b-roll archive says the analysis needs |
| Analysing music | Analyse music | music | what music says the analysis needs |
| Copying a camera or recorder card | Copy camera cards | the Footage Sorter | the card plugged into this computer |
| Copying a drive | Copy drives | the Footage Sorter | the drive plugged into this computer |
| Reading what is on a drive | Read drives | the Footage Sorter | the drive plugged into this computer |

A kind exists only while the part that asks for it is switched on. What the analysis of b-roll and of music needs, and what a person is shown about it, is in The b-roll archive: Describing and indexing clips, and in Music: Adding tracks to the library. What a card copy and a drive copy do is in The Footage Sorter and camera cards: Copying a card.

- When Timeline Cards is off: the four Timeline Cards kinds do not exist, and no computer shows a tick for them.
- When the b-roll archive is off: there is no b-roll analysis.
- When music is off: there is no music analysis.
- When camera cards with the Footage Sorter is off: there are no card copies, drive copies or drive reads.

### A computer offers only work it has checked it can do right now

A computer is offered a kind of work only when it really can do it at that moment:

- it offers a kind only after checking that the very tools that kind uses start on it;
- it offers work only on folders it can read right now: a drive that has been unplugged is absent, and work on it goes to a computer that has it;
- it offers transcription only when it has a graphics card with enough memory and the transcription set-up;
- it offers card and drive work only while the Footage Sorter is on and a card or drive is plugged in, and it reads one drive at a time.

Nothing a computer says about itself is ever misread as "cannot": something the server does not recognise is never taken to mean the computer is unable. A computer that has never said what it can do is offered no work that needs anything, and is shown as "this computer has not said what it can do". Work of a kind the app on a computer cannot do is handed straight back, as not worth trying again on that computer.

### A computer fetches the tools a kind of work needs by itself

Where a kind of work needs tools that the computer does not have (the video tools, the transcription set-up), the computer fetches them itself the first time it could take that kind, and nobody has to install or point to anything. Until they are in place, the computer does not offer that kind. When fetching a tool has failed twice in a row on a computer, the admin is shown which tool, on which computer, and why: as an alert, and in the answer to "why is this not running" for any work that needed it.

- On its own: fetching the tools a kind needs.
- By hand: an editor who does not want the tools on their computer unticks that kind of work.

### An editor decides whether their computer takes shared work and which kinds

In the app's settings window on their own computer, an editor can set:

- "Let the fleet use this computer", on by default. Turning it on says "This computer will take work for the fleet again."; turning it off says "This computer will stop taking work for the fleet." Beneath it: "Fleet work runs only while you are away from this computer."
- One on/off row per kind of work, each named as in the table above, all on by default. Turning one off or on says "This computer will <no longer do this | now do this> for the fleet: <kind>." Turning off the last one is refused: "That is the last kind of work this computer takes. Untick 'Let the fleet use this computer' instead."
- The lending period (see "The person at a computer can lend it to shared work for a while").

This is how an editor keeps a laptop out of one kind of work without leaving shared work altogether. With every kind ticked, the computer also takes any kind of work added later. Each change takes effect at once.

- Who: the computer's own person, on the computer. The computer's owner or an admin can ask for the same two settings from the dashboard (next behaviour).
- Ways in: the app's settings window on the computer, and the computer's settings asked from the dashboard.
- Setting: Let the fleet use this computer. Does: whether this computer takes any shared work at all. Default: on. Who: the computer's own person on the computer, or its owner or an admin by asking from the dashboard. Applies to: a computer. Search words: fleet work, shared work, lend computer, take jobs, laptop.
- Setting: Kinds of work this computer takes. Does: one tick per kind of work. An unticked kind is never given to this computer, and with every kind ticked, kinds added later are taken too. Default: every kind. Who: the computer's own person on the computer, or its owner or an admin by asking from the dashboard. Applies to: a computer. Search words: kinds of work, transcribe, preview copies, waveforms, fleet kinds.

### An admin or the computer's owner can ask a computer from the dashboard to change its shared-work settings

From the dashboard, the person a computer belongs to, or an admin, can ask that computer to change exactly two things: whether the fleet may use it, and which kinds of work it takes. Whether a computer is wired or remote can never be asked for from the dashboard.

What the dashboard shows for the computer: whether it is taking work now (and why not), what it is running, which kinds it takes ("every kind" or "not reported"), how long it waits before it starts, and its graphics card. Then "Let the fleet use this computer" and one tick per kind ("every kind" ticks them all, and the kind ticks are unavailable while fleet use is off), each sent as soon as it is changed, asking only for what changed. The ticks show what the computer WILL do: a waiting ask if there is one, otherwise what the computer is doing. Beneath them: "Asked of <computer> the next time it is in touch. Fleet work only runs while nobody is using the computer." and "To lend it now, or stop the job it is running, use the app on that computer."

Refusals:

- not the computer's owner or an admin: "Only the person this computer belongs to, or an admin, can change it."
- an unknown computer: "<person> has no computer called <computer>."
- anything other than the two settings: "Only these can be changed from here: whether the fleet may use the computer, and which kinds of work it takes."
- unticking the last kind, refused before anything is sent: "That is the last kind of work this computer takes. Untick Let the fleet use this computer instead."
- a kind of work that does not exist.
- a computer never heard from: "<computer> has not been heard from yet." (the controls are replaced by this sentence)
- a computer that must update first: "<computer> must update CC Sync before this can be changed from here. Update it, or change it in its own settings window." (the controls are replaced by this sentence)
- nothing would change: "Nothing to ask: it already works that way."

One ask per computer waits at a time. A new change while one waits is folded into it, the newer value winning for each setting. A waiting ask can be withdrawn ("Withdrawn. Nothing is asked of it now." or "There was nothing waiting to withdraw."). An ask is applied once, however often it reaches the computer, and an answer to an older ask changes nothing. The state shown under the computer:

- "Asked <ago>. <computer> gets it the next time it is in touch."
- "Sent to <computer> <ago>. Waiting for its answer."
- "<computer> could not save it yet and will try again: <detail>" (it tries again after 5 minutes)
- "In effect." (for 10 minutes after the answer, then nothing)
- "<computer> refused: <detail>"
- "<computer> was not in touch for 14 days, so the request was dropped."
- nothing, when withdrawn or when there is none.

When the ask is applied, the editor at that computer is told once: "<Who> asked this computer to stop taking fleet work / take fleet work again / take every kind of fleet work / take only these kinds of fleet work: <kinds>." ("Your administrator" when no name is given, and a name is cut to 64 characters.) Every step is recorded in the dashboard's history of who did what.

- Who: the computer's owner, or an admin.
- Ways in: the computer's own page on the dashboard, the per-computer view, and a person's own account page for their computers; the same two settings on the computer itself (previous behaviour).

### Each computer's shared-work state on the dashboard

For each computer, the dashboard shows:

- its state sentence (see "A computer says in one sentence whether it is taking shared work and why not");
- how long nobody has used it: "<n> s with nobody using it" under a minute, "<n> min with nobody using it", "no wait" for a computer that never waits, or "not reported";
- the work running now: "<kind> on <file>, <n>%" (the file and the percentage only when known);
- "volunteering until <time>" while its person has lent it;
- its graphics card's name and memory, when known.

- Who: an admin for every computer, and each person for their own computers.
- Ways in: the per-computer view, each computer's own page, and a person's own account page for their computers.

### What an admin can learn about what a computer is able to do

For every computer, an admin can see what it has for shared work: whether it has a graphics card and its name and memory, whether it has a hardware video encoder, whether the video tools run, whether transcription is ready and if not why (not fetched yet, missing, or incomplete), how many processors it has and how loaded it is, which of the studio's shared folders it can reach right now, whether the Footage Sorter's card and drive work is on there, whether shared work is on, its quiet time, the kinds it takes, how long nobody has used it ("cannot tell" when unknown), whether Resolve is open and which project, until when it is lent, and its state sentence. These facts are never more than a minute old while the computer is in touch. When it is not, the last known facts are kept and shown with their age. No credentials or paths are shown.

- Who: an admin.
- Name and search words: what a computer can do. Search words: graphics card, encoder, capabilities, transcription ready, computer abilities.

#### Lessons

- Met: JOB-007, JOB-008, JOB-009, JOB-010, JOB-011.

## Choosing who runs what

### Each piece of work is done by exactly one computer

Every piece of heavy work a part asks for is done by exactly one computer. Two computers never both do the same piece, not even for a moment, and no piece is ever lost: a piece asked for survives the page that asked for it closing, any computer restarting, the server restarting and the network dropping. A computer that is free and able starts on waiting work within about 20 seconds; nobody has to press anything.

### Waiting work is taken in a fair order

Waiting work is taken oldest first, except that sound and waveforms go ahead of preview copies, so an editor can listen to a clip before they can watch it. Work an admin started now goes first. A long backlog of one kind never hides another kind, and a piece that some computer can do is offered however many pieces that nobody can do are waiting ahead of it. A computer narrows what it takes by its own settings, but is never given a piece it was not able for at that moment.

### The best-placed able computer is asked first

Among the computers able to do a piece of work, the best placed is asked first. They are ranked by, in order:

1. how well suited each is to the kind:
   - transcribing: a computer its person has lent now, then a graphics card with room for the work plus 1 GB to spare, then any graphics card;
   - preview copies: a computer lent now, then a hardware video encoder;
   - sound and waveforms: a computer lent now, then a computer set as wired to the server, which reads footage fastest;
   - card copies, drive copies and drive reads: no preference (the card or drive is in one computer);
2. holding less shared work right now;
3. being less loaded (a computer that cannot say how loaded it is counts as not loaded, never as a penalty);
4. having been left alone longer.

Names never break a tie. For the first minute after a piece of work is asked for, only the best-ranked computers (all of them, when tied) may take it; after that every able computer may. Work an admin started now and work meant for one computer do not wait that minute, and when no computer is able the minute counts as over.

- On its own: which able computer is asked first, from the ranking above.
- By hand: an admin can start the work now on a chosen computer (see "An admin can start waiting work now, on a chosen computer"), and a person can lend their computer so that it is first choice.

### Work can be meant for one named computer

A piece of work can name the one computer that should do it. Every other computer is passed over with "this job is for <computer> only", and the named computer is asked at once, with no minute given to a better-placed one. Work meant for one computer stays meant for it even while that computer is away.

### An admin can start waiting work now, on a chosen computer

On the work page, an admin can start any waiting piece of work now, on any able computer or on one computer picked from the list. Work started now skips three waits only: the rest after a failure on that computer, the wait for nobody to be at the computer (it is taken even with someone at it or Resolve open), and the minute given to the best-placed computer. It still waits while syncing is stopped for the whole fleet or on that computer, while an update waits to apply there, while that computer's proxy download has stopped itself, while the computer is already doing shared work or its own heavy work, while shared work is off on it, and while that kind is unticked on it. Only that piece is taken. It records "Your admin asked this computer to run this job now, without waiting for you to step away." The Footage Sorter starts its card and drive copies this way, because a person is waiting at the card.

- Who: an admin.
- Ways in: the work page.

### Choosing a computer is a pick from the studio's known computers

Wherever a person chooses which computer does a piece of work (an admin starting work now, an editor choosing which computer makes a clip's proxy from its preview, see Proxies and file moves: Making proxies on editors' computers), the choice is a pick from the studio's known computers, and the work is sent at once. A name is typed only when no computer is known. For each computer the pick shows whose it is, its name, whether it is in touch (computers heard from recently first, then by name), when it was last heard from, whether it takes shared work and which kinds ("every kind" when none are named), what it has (graphics card and memory, hardware encoder, video tools, transcription, processors, shared folders), how long nobody has used it ("cannot tell" when unknown), whether it can do this piece and why not, and the work it is doing now. No credentials or paths are shown.

- Who: anyone allowed to ask for the work.

### Work tied to one computer's Resolve is never shared

Placing a cut into Resolve, and any editing inside Resolve, is never shared work: it is done only on the computer where that Resolve runs, by the person at it. See Timeline Cards: the hand-over to Resolve, and exports: Which computer is driving Resolve.

### Media for Timeline Cards is made by the studio's computers first, and by the server when none can

When Timeline Cards needs a clip's sound, preview copy or waveform, the piece is offered to the studio's computers first. While it is being made the clip shows "making"; when the file is there, it is ready. The server makes the file itself when:

- the answer to "why is this not running" says no computer will ever be able to (none able, the named computer unknown, none heard from), or
- the computers have used up their tries on it, for any reason other than the clip having no sound or no picture, which are final.

While the hold-up is only passing (computers busy, the limit reached, waiting for quiet, a computer resting), Timeline Cards keeps waiting. Work the server takes over is never handed back to the computers; it resumes after the server restarts, and if it fails on the server too it is given up with the error. The server never makes a file a computer is already making, and if a computer's copy arrives while the server is also making one, the server's is thrown away. Work is shared out only for files in the studio's shared folders; anything else is made by the server. Transcription is never taken over by the server: it needs a graphics card. The server takes over a piece only when it can start it now; otherwise the piece is given up and shown as given up.

The explanation of such a piece reads "the computers could not finish this, so the server is making it; it never goes back to the computers".


#### Lessons

- Met: JOB-012, JOB-013, JOB-014.

## Load on the NAS and the computers

### A computer does one piece of shared work at a time

A computer is never given a second piece of shared work while it is doing one. The one exception is reading a drive, which is light: a computer may read one drive beside one other piece of work, but never two drives at once; a second drive read is left waiting for later. Media for one clip is never made twice at once: however many people open the same clip, there is at most one piece of work making each file.

On Windows, shared work runs with no window and at low priority, so it does not slow the person at the computer.

- Windows and macOS: on Windows, shared work runs hidden and at low priority.

### Only so many of each kind of work run across the studio at once

Across the whole studio, at most this many pieces of each kind run at once:

| Kind | At most at once |
|---|---|
| Transcribing speech | 2 |
| Copying a drive | 2 |
| Every other kind | 4 |

The limit holds at every moment, even when several computers ask in the same instant. A piece held back by the limit is explained as "<N> <kind> job(s) are already running, which is this fleet's limit (<limit>); it starts as soon as one finishes", and starts as soon as one finishes. Work the server has taken over does not count towards the limit.

- Setting: How many of each kind run at once. Does: the studio-wide limit for each kind of shared work. A value below 1 counts as 1. Default: 2 for transcribing and for drive copies, 4 for every other kind. Who: an admin. Applies to: the site. Search words: limit, at once, concurrent, fleet cap, how many jobs.

### The server makes no media while a card is being copied to the NAS

While a camera or recorder card is being copied to the NAS, the server makes no preview copies, sound or waveforms itself: the work waits until the copy is done, so the copy is not slowed. See The Footage Sorter and camera cards: Drives, speed and interruptions.

#### Lessons

- Met: JOB-015, JOB-016.

## Progress

### Progress is shown as it goes, never as a made-up zero

While a piece of work runs, its progress is shown as a real percentage when it is known and as "running" when it is not, never as a made-up 0%. Progress moves at least every 30 seconds while work runs; a long transcription shows its progress as it goes (also whenever it has moved by 1%). A transcription counts the files to do, which one is under way and how far through it; a preview copy, sound or waveform counts how far through the clip it is; card and drive copies add how many files and bytes are done.

### The work page shows what is waiting and running, and why any of it is not moving

The work page is for admins. It keeps itself up to date without reloading. It opens with "Work the fleet does for itself: transcriptions, preview copies, sound and waveforms, analysis, card and drive copies." and "A piece of work goes to a computer that can do it. What this page is for is a queue that is not moving, and why. That answer is under each row, per computer, in words."

- A summary: "<N> waiting, <N> running[, <N> made on the server][, <N> given up in the last <N> h]", and "The oldest has waited <time>."
- Per kind: "<kind> <running>/<limit>", with "full: the next one waits for a free slot" at the limit.
- Whether the server can take over work the computers could not finish, and if not, why not.
- Open work (up to 100 rows): number, kind, "now" (every able computer asked at once) or "for <computer>" (only that one), state (waiting, running, being made on the server, each explained), "(stopping)" while a cancel is under way, which computer has it (or "nobody"), progress ("-" when unknown, because unknown is not zero), age, and "cancel" and "start now".
- Under each row: the one-line answer to "why is this not running", "(<N> attempts: <start of the last error>)", and per computer "yes" or "no", "<person>/<computer>: <reason>".
- Empty: "Nothing is waiting or running." with how many were given up recently.

For each piece of work the page can open what is known about it: its kind, when and by whom it was asked for, the files it works on (as a shared folder and the path inside it, never a drive letter), what a computer needs to take it, its state, the person and computer doing it, its last sign of life, its attempts, its last error, its result, its progress, whether it was started now, the computer it is meant for, and when and by whom it was cancelled. The per-computer view shows, for each computer doing work, its kind, state, last sign of life, percentage and file.

- Who: admins.
- Ways in: the work page.
- Name and search words: shared work. Search words: jobs, queue, fleet work, transcriptions waiting, why not running.

### The editor sees what their computer is doing for the studio, and its last ten jobs

In the app's settings window, the editor sees "Taking fleet work" or "Not taking work: <reason>". While a piece runs: "Running a fleet job for the team: <kind> on <file> (started <age>)", why it was taken while someone was there (lent, or an admin started it now), and "STOP THIS JOB". Below, the computer's last 10 finished pieces, kept across restarts: "<kind> on <file>: <finished | failed | stopped>, <age> (<error, up to 300 characters>)". The app's menu shows the current piece too. When a transcription finishes, the editor is told "Finished a transcription job for the fleet (<N> s)."

- Who: the person at the computer.
- Ways in: the app's settings window and menu on the computer.

#### Lessons

- Met: JOB-017.

## Stopping and cancelling

### An admin cancels a piece of work

An admin can cancel any piece of work that has not finished. The question is "Stop job #N? It is stopped where it runs and not tried again."

- A waiting piece ends at once: "job #N is over", recorded as cancelled by that admin.
- A running piece shows "stopping" until the computer (or the server) confirms the work has really ended: "job #N will stop on <computer>'s next contact; it is not tried again anywhere", or "job #N will stop shortly: it is being made on the server". The admin's cancel always reaches that computer. A piece is never marked finished while its work is still running.
- If the computer goes away instead of confirming, the piece ends as cancelled once it has been silent for as long as any lost work is (see "A computer gone quiet does not keep its work"), with "cancelled: <person>/<computer> went quiet without confirming".
- A piece already finished: "job #N has already finished". No such piece: "there is no job #N".

A cancelled piece never runs again anywhere, the cancel reports the state the piece actually ended in, and the counts of waiting work include only work that can still be given out.

- Who: an admin.
- Ways in: the work page.

### The editor stops the job running on their own computer

The person at a computer can stop the shared work it is running with "STOP THIS JOB" in the app's settings window. It answers at once: "Stopping the fleet job. It goes back to the queue for another computer." ("There is no fleet job running now." when there is none, and "CC Sync could not stop that job." with where to look when it fails.) Stopping also ends a lending. The piece is not counted as a failure and this computer is not rested for it. Once stopped on that computer it stays stopped, whatever the server says next.

- Who: the person at the computer.
- Ways in: the app's settings window and menu on the computer.

### A stop ends everything the work started and leaves nothing half-made

Whenever a running piece of work is cancelled, stopped, or ended by the app quitting, everything it started is ended within seconds and the graphics card and any half-made files are freed. It is asked to stop first; if it has not ended within about 10 seconds it is forced, with a further 5 seconds allowed. It reports stopped only once everything it started has ended. A half-made result is removed; a result already finished is kept. A running piece always obeys a cancel, a studio-wide stop and its time limit, even when the clip it reads has stopped delivering data.

### A studio-wide stop or the app closing puts running work back to waiting

When an admin stops syncing for the whole fleet (see The dashboard: Stopping and resuming the fleet), or the app on a computer quits, the work running there stops and goes back to waiting, to be done when a computer can; it is not counted as a failure of that computer. While the fleet is stopped, no computer takes any shared work.

### Only the computer doing a piece of work can end it or change it

Once a piece of work has moved to another computer, nothing the first computer does or says afterwards touches it, its progress or its results. A finished result from a computer that was slow to report is still accepted, as long as no other computer has taken the work meanwhile.

#### Lessons

- Met: JOB-018, JOB-019, JOB-020, JOB-021, JOB-022, JOB-023, JOB-024.

## Outages and withdrawn access

### A short loss of the server or the network does not cost a running job

A piece of work keeps running through a brief loss of the server or the network, and its result is handed in once the server can be reached again. It stops only when it is cancelled, when it has gone to another computer, or when the computer's access is withdrawn. While the server cannot be reached, a computer takes no new work.

### A computer gone quiet does not keep its work

When a computer doing a piece of work goes quiet (switched off, asleep, unplugged from the network) for 5 minutes, the work goes back to waiting and is taken by the next able computer. The piece's history shows "<person>/<computer> went quiet at <time>, so the work was given to another computer". Losing work this way uses up one of its tries, and the computer that went quiet is rested before it is given more ("job #N (<kind>) was lost here").

### A computer whose access is refused says so and takes no work

When the server refuses a computer's access (its person suspended, disabled or removed, see Accounts, privacy and the legal paperwork: Suspending, disabling and removing a person), the computer stops the work it is running at once, takes no new work, and shows that it is not taking work, adding "This computer's fleet work is not being accepted right now: ask the studio to check this account." A piece it had already finished can still be handed in. The next time the server accepts it, the message clears by itself.

#### Lessons

- Met: JOB-025, JOB-026, JOB-027.

## Failures, retries and the queue

### Work that fails is tried again on another computer, a set number of times

Each piece of work moves from waiting, to running on one computer, to one of three endings: done, failed, or given up. When it fails:

- A failure that is about the work itself (the clip has no sound, no picture or no samples, or the file is not in the studio's folders at all) ends it at once as failed, with that reason in plain words, and it is not tried again: "this job failed and will not be tried again: <reason>".
- A failure of the computer (a tool that would not start, a folder it could not reach, a time limit run out, the computer going quiet) sends it back to waiting, to be tried on another computer, until its tries are used up.
- When its tries are used up it is given up: "given up after <N> attempt(s): <last error, or 'no error recorded'>", unless the server takes it over (see "Media for Timeline Cards is made by the studio's computers first, and by the server when none can").

| Kind | Tries |
|---|---|
| Transcribing speech | 3 |
| Preview copies | 3 |
| Sound, waveforms, card copies, drive copies, drive reads | 2 |

### A computer where work just failed rests before it is given more

After a piece of work fails on a computer (not when it is cancelled or stopped by its person), that computer is given no more shared work for 2 minutes, shown as "this computer is resting until <time> (job #N (<kind>) failed here: <first 120 characters of the error>)". A piece finished successfully there ends the rest. This keeps a computer with a broken tool from failing every piece in turn.

- Setting: Rest after a failure. Does: how long a computer is passed over after a piece of shared work failed on it; 0 means no rest. Default: 2 minutes. Who: an admin. Applies to: the site. Search words: rest, cool down, after failure, retry wait.

### Every piece of work has one answer to "why is this not running"

Every piece of work has one overall answer, in words:

- being done: "<person>/<computer> is doing this job (started <time>)";
- being made on the server: "the computers could not finish this, so the server is making it; it never goes back to the computers";
- done: "this job is done"; given up and failed: as in "Work that fails is tried again on another computer, a set number of times";
- at the limit: the sentence in "Only so many of each kind of work run across the studio at once";
- some computer can take it: "<N> computer(s) can take this job; one will start it shortly";
- no computer has ever been in touch: "no computer has ever been in touch with this server";
- meant for one computer never heard from: "this job is for <computer> only, and no computer of that name has ever been in touch"; meant for one that cannot take it now: "this job is for <computer> only, and it cannot take it: <why>";
- otherwise: "no computer can take this job right now: <why>", naming the reason of the computer nearest to taking it, for example "somebody is at it", "it cannot do this kind of work", "it has not been heard from in the last 15 minutes", "it is busy with its own work"; when that reason is a missing tool whose fetching keeps failing, it adds ". On <person>/<computer>, <cause>".

Beside the sentence, the answer says whether the hold-up will pass by itself ("the fleet will get to it": computers busy, the limit, waiting for quiet, a computer resting, a named computer away) or not (no computer able, the named computer unknown, no computer in touch), and the two always point at the same cause. It also says how many computers could ever do it, and how many of that kind are running against the limit.


### For waiting work an admin sees why each computer is or is not taking it

For a piece of work still waiting there is one line for every computer ever heard from. A computer passed over shows its reason (see "The reasons a computer is passed over for a piece of work"). An able computer shows either "this computer can take it, and is first choice", or "this computer can take it (choice <n> of <m>, <why it lost>, <when>)". Why it lost names the first thing it lost on: "the first choice has <somebody at it who lent it now | a hardware video encoder | a graphics card with room for this work | a graphics card | a wired connection to the server> and this computer has not", or "the first choice is better placed for this kind of work", "is doing less work right now", "is less loaded", "has been left alone longer". When is "it may take it now too" or "it may take it in <N> s if nobody ahead of it has by then".

- Who: an admin.
- Ways in: the work page.

### Admins are warned when work waits and nobody can take it

An admin is warned, "work is waiting and nobody is taking it", when the oldest waiting piece has waited 6 hours or more and the reason will not pass by itself: no computer can do it, every able computer has that kind switched off, syncing is stopped for the whole fleet, or every able computer has gone quiet. Passing reasons (all busy, waiting for quiet, the limit, a computer resting) never raise it. See The dashboard: Problems the server finds, and Alerts by mail.

### Admins are warned when work was given up

An admin is warned, "the fleet gave up on some work", when any piece was given up in the last 24 hours, as one warning for all of them. A serious warning, "the server has stopped making work it took over", is raised when work the server took over has shown no sign of life for over an hour.

### Finished work can be looked back on and tried again

On the work page, "show finished" lists every piece that ended in the last 24 hours (the period can be changed): number, kind, ending ("done", "failed", "given up" or "cancelled"), what it worked on (with "(retry of #N)" for a new attempt), which computer last had it, when, its attempts, and its full last error. Empty: "Nothing has finished in the last <N> hours." A failed or given-up piece has "try again": "Queue job #N again? It goes back on as a new job.", then "job #N is on the queue again as #M. The old one is left as it was." The new piece has the same kind, files, needs, start-now and named computer, and the admin is shown which computers can do it. Refusals: "job #N is <state> and has not finished, so there is nothing to try again yet. Cancel it first."; "job #M is already a new attempt at job #N and it is still on the queue." Trying again never queues a second copy of a piece already waiting or running, however many times it is pressed. Finished work is kept for 30 days; waiting work is never forgotten.

- Who: an admin.
- Ways in: the work page.

#### Lessons

- Met: JOB-028, JOB-029, JOB-030, JOB-031, JOB-032, JOB-033, JOB-034, JOB-035.

## Results that are complete and current

### A result appears only when it is complete and current

For every kind of work that makes a file:

- A file counts as already made only if it is newer than its source and made in the current form and settings; the same check is made before the work starts and again before the result is kept. One already made is reused and the work finishes as "nothing to do, it was already made".
- A result appears under its final name only once it is complete and the whole source has been read; a result made from part of the source is never kept, and the work fails so it can be tried again.
- When two computers make the same file, the first finished copy wins and the other is thrown away; a newer finished copy is never overwritten.
- A stopped or failed piece leaves nothing usable behind.
- A piece is judged on whether its real result is complete: a tool's side messages never fail it, and a real error keeps its own message.
- Results are named as the editor knows the clip.
- Sound and waveforms give up after 30 minutes and preview copies after 60, and can be tried again on another computer.

When a piece finishes, the admin sees how long it took, how much faster than real time it ran, and the files it made.

### Work names its files inside the studio's shared folders

A piece of work names its files as a shared folder (the studio's project tree, the Timeline Cards episodes, the media folder, the footage) and a path inside it, never as a full path, so the same piece can be done on any computer, wherever that computer keeps those folders. A computer that does not have the folder, or cannot reach it right now, is passed over ("this computer has no <folder> it can reach right now"), and the piece may be done elsewhere. A path that climbs out of its folder, a full path, an empty path, or one with unprintable characters fails the piece with a sentence saying so.

A piece that makes a file must say where it goes: nothing guesses a place in somebody's episodes. Its name defaults to the source's own name. A name that no computer can write (empty, a dot name, or holding a "/" or a control character) is refused when the work is asked for, with "the output name is not a plain file name: it cannot be a dot name or hold a '/' or a control character". A name only Windows cannot write (holding a ":" or a "\") is never given to a Windows computer, and is made on a Mac or by the server.

- Windows and macOS: a file name holding ":" or "\" is made only on a Mac or by the server.

### A computer transcribes an episode's folder

A transcription names a folder in the Timeline Cards episodes and its episode, and can ask for speakers to be told apart. A folder with nothing left to transcribe finishes at once at 100%. When done, the transcripts made are listed. What the transcripts hold is in Timeline Cards: footage in, ready to cut: The transcript and its English.

### A small preview copy of a clip is made for Timeline Cards

A preview copy is at most 480 lines tall, never enlarged, with a fresh picture every second so it can be jumped about in quickly, and stereo sound. A computer whose graphics card can encode video uses it; others encode on the processor. A clip with no picture fails as "no video track" and is not tried again.

### A clip's sound is made for Timeline Cards

If a clip's sound can be played by a browser as it is, it is copied without change, and kept only when its length is within 0.05 seconds of the clip's; otherwise it is converted to compact mono sound of speech quality. A clip with no sound fails as "no audio track" and is not tried again.

### A clip's waveform is made for Timeline Cards

A waveform holds 200 points a second, and is made with little memory even for very long recordings. One made at a different number of points is made again. A clip with no sound, or no samples, fails as "no audio track" and is not tried again.

#### Lessons

- Met: JOB-036, JOB-037, JOB-038, JOB-039.
