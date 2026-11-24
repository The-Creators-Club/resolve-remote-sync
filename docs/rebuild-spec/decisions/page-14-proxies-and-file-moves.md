# Decision list, page 14: Proxies and file moves

Stays behind: never shown to the session that rebuilds the product.

3 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 14.1 When a clip has failed to become a proxy three times, or Resolve has refused a proxy, should that be remembered across a restart of the app?

- **Today:** a clip given up on after three failed attempts is tried again after any restart of the app, and a proxy Resolve refused is offered to Resolve again after a restart. So a broken clip is retried every time the computer restarts, and a refused proxy is offered again each time.
- **Options:** A: remember both for that version of the file across restarts; a changed file starts afresh, and "make the missing proxies now" retries every clip given up on at once. B: forget both whenever the app restarts, as today.
- **Recommended:** A, because a restart then changes nothing a person can see and the editor still has one button to retry everything.
- **What you would notice:** with A, a broken clip stops being retried after three tries until the file changes or the editor presses "make the missing proxies now"; with B, it is tried three more times after every restart.
- (proxies-and-file-moves-Q1)

### 14.2 On a Mac, should CC Sync find, open and start Blackmagic Proxy Generator for raw clips by itself, as it does on Windows?

- **Today:** on Windows the generator is found where Resolve installs it, opened for raw clips and started with its Start button pressed. On a Mac it is off until someone types in where the generator is, and even then the app leaves it idle for the editor to press Start.
- **Options:** A: the same on both: found where Resolve installs it, opened and started without the editor's help, with the "could not press Start" note when that fails. B: keep the Mac as it is: off until its location is given, and never started for the editor.
- **Recommended:** A, because raw clips on a Mac otherwise sit without proxies until someone notices, and one behaviour on both systems is simpler.
- **What you would notice:** with A, a Mac editor's raw clips get proxies while they are away, like a Windows editor's; with B, a Mac editor must set the location once and press Start each time.
- (proxies-and-file-moves-Q3)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 14.3 | Should the two rehearsal settings (make no proxies but list what would be made, and FIX ALL listing its copies and relinks without doing them) stay in the product? | both exist, are off, and can only be switched on by editing the computer's settings file by hand. They were made for the people building the product but ship to every computer. | A, because nobody running the studio uses them, and a setting nobody can reach is a moving part with no job. (proxies-and-file-moves-Q2) |

## Your answers

ANSWERED 2026-11-24. After answering pages 2 and 3 and most of page 4 one
by one, he said of everything still waiting: "accept all the
recommendations." So every question on this page is answered with its
recommendation.
