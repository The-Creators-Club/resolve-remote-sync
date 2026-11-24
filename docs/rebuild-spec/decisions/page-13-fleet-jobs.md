# Decision list, page 13: Work shared out across the computers

Stays behind: never shown to the session that rebuilds the product.

12 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 13.1 When an editor presses "stop this job" on their own computer, should the work be cancelled for good, or go back to the queue for another computer?

- **Today:** the editor's settings window says "Stopping the fleet job. It goes back to the queue for another computer.", but the stop is actually treated like an admin's cancel: the work is ended and never tried again anywhere, so the transcript or preview it was making never arrives.
- **Options:** A: the work goes back to the queue for another computer, and the editor's computer is not blamed or rested for it. B: the work is cancelled for good, as an admin's cancel.
- **Recommended:** A, because the editor only wants their computer back, the work is still needed, and it is what the screen already promises.
- **What you would notice:** with A, a stopped transcription is still finished elsewhere; with B, someone must notice and queue it again.
- (fleet-jobs-Q1)

### 13.2 Should a change to whether a computer takes shared work, and which kinds, take effect at once instead of at the next start of the app?

- **Today:** whether changed on the computer or asked from the dashboard, the change is saved and waits for the app to restart; nothing restarts it, so a red line says it takes effect "when CCSync next starts", and the dashboard shows "saved, takes effect the next time CCSync starts there".
- **Options:** A: every change takes effect at once. B: changes wait for the next start, as now.
- **Recommended:** A, because there is nothing a person gains from the wait and it removes a whole set of "waiting for a restart" states.
- **What you would notice:** with A, unticking a kind stops new work of that kind straight away (running work is still finished).
- (fleet-jobs-Q2)

### 13.3 Should lending a computer to shared work also be possible from the dashboard?

- **Today:** only the person at the computer can lend it, from the app; the dashboard shows "volunteering until <time>" but has no control. An admin can start a waiting piece now on a chosen computer instead.
- **Options:** A: lending stays at the computer only. B: the owner or an admin can also lend or end a lending from the dashboard.
- **Recommended:** A, because lending means "I am here, use it anyway", which only the person at the computer can say, and an admin's "start now on this computer" already covers the admin's need.
- **What you would notice:** with B, a computer could be lent while its person is at it without their saying so.
- (fleet-jobs-Q10)

### 13.4 Should every able computer fetch the tools a kind of work needs by itself, including the transcription set-up?

- **Today:** the video tools are fetched by the computer itself (and an admin sees when that keeps failing), but transcription works only once the transcription set-up has been installed and pointed to by hand on each computer.
- **Options:** A: a computer fetches every tool it needs by itself, the transcription set-up included, and an editor who does not want it unticks that kind. B: transcription stays set up by hand.
- **Recommended:** A, because nothing outside the product should be needed, and a computer with a good graphics card otherwise sits out of transcription until someone remembers to set it up.
- **What you would notice:** with A, a computer with a suitable graphics card starts taking transcription without anyone doing anything, after a one-off download.
- (fleet-jobs-Q12)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 13.5 | When no computer can make a clip's preview copy, sound or waveform for Timeline Cards, or the computers keep failing at it, should the server make it itself? | the server is meant to finish these three kinds when the computers used up their tries, and Timeline Cards makes the file itself when no computer will ever be able to. With the new editor on, the server has nothing to make them with, so such work is just given up. Transcription is never taken over (the server has no graphics card). | A, because an editor opening a clip on a studio with no free computer still gets to hear and see it, and the NAS is spared until the computers have had their chance. (fleet-jobs-Q3) |
| 13.6 | Work can skip the wait for nobody to be at a computer three ways. Keep all three? | an admin marking work "now"; the person at the computer lending it until a time; and a computer set as wired to the server being exempt from the wait altogether. | A, because the exemption guesses that a wired computer has nobody at it, while a quiet time of 0 says it plainly for the computers that really are nobody's desk. (fleet-jobs-Q4) |
| 13.7 | Should an admin be able to queue a piece of work by hand, and if so from where? | an admin can queue a transcription, preview copy, sound or waveform by hand from a command line, with a priority, "now" and a named computer; the dashboard cannot do it. A kind that does not exist, or a computer that does not exist, is accepted without a warning. Every part that needs work (Timeline Cards, the Footage Sorter) already asks for it by itself. | A, because no person's task needs it once every part asks for its work by itself, and the priority number goes with it. (fleet-jobs-Q5) |
| 13.8 | Cancelling a piece of work can be done from the dashboard and from a command line. Keep both? | an admin can cancel from the work page or from a command line. | A, one way to do each thing. (fleet-jobs-Q6) |
| 13.9 | Trying finished work again can be done from the dashboard and from a command line. Keep both? | "try again" is on the work page and on a command line. | A, one way to do each thing. (fleet-jobs-Q7) |
| 13.10 | Seeing the work waiting and running, and why a piece is not running, can be done from the dashboard and from a command line (which can also follow one piece live). Keep both? | the work page shows the queue and per-computer reasons; a command line lists, explains and follows work line by line. | A, one way to do each thing, and the page already updates by itself. (fleet-jobs-Q8) |
| 13.11 | Whether a computer takes shared work, and which kinds, can be set on the computer itself and asked for from the dashboard. Keep both? | the editor sets it in the app's settings window; the owner or an admin can ask for the same two settings from the dashboard, and the computer applies the ask. | A, because an admin cannot reach an editor's computer and an editor may only have the app open, so each needs a way in, and both change the same one setting. (fleet-jobs-Q9) |
| 13.12 | For waiting work, which reason should be shown as THE reason it is not running? | the one-line answer names the commonest reason across all computers, while the "will this pass by itself" verdict is taken from the most hopeful computer, so the two can point at different causes. | A, because the computer nearest to taking it is the one whose hold-up decides when the work starts, and the sentence and verdict then always agree. (fleet-jobs-Q11) |

## Your answers

Not yet answered.
