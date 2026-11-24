# Decision list, page 18: YouTube downloads

Stays behind: never shown to the session that rebuilds the product.

21 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 18.1 When an admin gives the server a signed-in YouTube session, should searches use it only after YouTube bot-checks them, as downloads do?

- **Today:** searches and detail lookups always use the server's session when one is given; downloads use it only after a bot check. Every search therefore exposes the account to being flagged by YouTube, after which it breaks everything.
- **Options:** A: one rule: the session is used only after a bot check, for searches and downloads alike. B: searches always use it, downloads only after a bot check.
- **Recommended:** A, one rule, and the account is used as little as possible so it lasts.
- **What you would notice:** with A, a search may first be bot-checked and then retried signed in; the account is flagged less often.
- (youtube-Q3)

### 18.2 When a job is cancelled mid-clip, should the clip in flight be stopped at once and thrown away, or finished first?

- **Today:** the page says "it stops after the video in flight", but the clip in flight is in fact stopped within about two seconds and thrown away; one lesson asks for stopping within seconds, another for stopping after the clip in flight on an editor's computer.
- **Options:** A: stop within about two seconds everywhere, remove the half-made clip, leave it waiting so RETRY can fetch it, and say "cancelling: stopping the clip in flight". B: finish the clip in flight, then stop.
- **Recommended:** A, a cancel that takes effect at once is what a person expects, and a long clip could otherwise run for an hour after cancel.
- **What you would notice:** the wording matches what happens.
- (youtube-Q8)

### 18.3 Which projects can a person download into?

- **Today:** the list offers the projects the editor syncs on any of their computers, but every active project when the download runs on the server or a wired computer; since downloads run on the server by default, anyone can download into any active project while the refusal speaks of "projects you sync".
- **Options:** A: every active project, whoever asks and wherever it runs; the editor's own computer simply does not take a job for a project it does not hold. B: only projects the person syncs on some computer.
- **Recommended:** A, one rule that never changes with where the download runs, and the picker and every later step can never disagree.
- **What you would notice:** with A, an editor with nothing ticked can still download into a project; no "tick it first" refusals.
- (youtube-Q11)

### 18.4 Clips downloaded on the server, or on another editor's computer, never reach the editor who asked for them unless they fetch each one by hand. Should they?

- **Today:** YouTube originals only sync upwards, like all original footage; the editor sees "not on this computer" and a fetch button per clip.
- **Options:** A: as today, fetched one clip at a time by hand. B: the clips of a job reach the computer of the editor who asked by themselves, when that computer syncs the project; others fetch by hand. C: downloaded clips reach every computer syncing the project, like other footage coming down.
- **Recommended:** B, the person who asked for the footage expects to find it on their computer, without filling everyone else's disks.
- **What you would notice:** with B, the requesting editor finds the clips in their folder and in Resolve without pressing anything.
- (youtube-Q12)

### 18.5 Filing downloaded clips into Resolve has its own on-off switch per computer and keeps running when the YouTube part is off. Should it follow the YouTube part?

- **Today:** the filing is not tied to the site's YouTube switch.
- **Options:** A: it follows the YouTube part (and the help for the editing program), keeping its own per-computer switch. B: it stays independent.
- **Recommended:** A, switching a part off stops its work everywhere, and clips already downloaded are still in their folders.
- **What you would notice:** with A, a site that switches YouTube off no longer has clips filed into Resolve.
- (youtube-Q13)

### 18.6 A clip the editor removed from Resolve's media pool comes back the next time the app starts, because the file is still in the folder. Should a removed clip stay removed?

- **Today:** nothing is remembered across restarts, so a removed clip is filed again.
- **Options:** A: a clip the editor removed stays removed while its file stays in the folder. B: it is filed again after each restart.
- **Recommended:** A, an editor's own act is never undone by the product.
- **What you would notice:** with A, removing a clip from the media pool is final until the editor imports it again.
- (youtube-Q14)

### 18.7 The download history shows everyone who downloaded what, to every signed-in person. Is that wanted?

- **Today:** the history and the "already in" marks are shared by everyone, with the name of who downloaded each clip.
- **Options:** A: keep it shared, with names. B: shared, without names except to an admin. C: each person sees only their own.
- **Recommended:** A, the shared record is what stops the studio downloading a video twice, and it carries the rights statement each person signed.
- **What you would notice:** none with A.
- (youtube-Q18)

### 18.8 You ruled that each person accepts the YouTube rights statement on each computer, in the app, as well as on the page. Should one acceptance on the page also count for the computer the page is open on?

- **Today:** an editor accepts the notice on the page (per wording) and again in the app on each computer before that computer downloads for them; without the second, their downloads quietly run on the server.
- **Options:** A: as ruled, two acceptances. B: one acceptance on the page, recorded with the person, the wording and the computer it was given on, counting for that computer too.
- **Recommended:** B, one statement read once does the same job with one step fewer, and the record still says who and on which computer.
- **What you would notice:** with B, an editor accepts once per wording per computer, on the page.
- (youtube-Q20)

### 18.9 Should an editor still be able to point their computer at their own copy of the downloading tool, or turn its daily self-updating off?

- **Today:** a per-computer setting names a downloading tool the editor manages (the app then never updates it), and setting the age limit to 0 also stops the computer updating it.
- **Options:** A: neither: the product keeps downloading working by itself, and never replaces video tools the editor installed for their own use. B: keep both settings.
- **Recommended:** A, every such setting is a way for one computer to fall behind YouTube's changes unnoticed.
- **What you would notice:** with A, nothing to set; an editor who managed their own copy keeps it for their own use, untouched.
- (youtube-Q21)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 18.10 | One item is a tool for the people building the product (making the one-click YouTube sign-in use a particular browser, with a one-line diagnosis of which browser would be used). Can it go? | whoever builds the product can name a browser for the one-click sign-in to try first, and ask which browser would be used. | A, it is for the builders and no editor or admin meets it. (youtube-Q1) |
| 18.11 | An editor can give their computer a signed-in YouTube session three ways: the one-click sign-in in a browser window, choosing an exported cookies file, or naming a cookies file in the computer's settings. Which stay? | all three exist; the cookies file is also what the app falls back to when no suitable browser is installed. | A, one click is the ruled way and the chooser is the only way on a computer without Edge, Chrome, Brave or Chromium; the third is the same thing again. (youtube-Q2) |
| 18.12 | Should there still be a site switch that turns downloading on editors' own computers off altogether? | downloading on editors' computers is off for every site unless switched on, so in practice every download runs on the server, even when YouTube is blocking the server and would serve the editor. | A, YouTube blocking the studio's address is exactly when an editor's own connection is needed, and the per-computer choice already covers anyone who does not want it. (youtube-Q4) |
| 18.13 | You ruled an "on this computer" switch on the YouTube page, on by default. Each computer also has its own setting keeping it out of downloads. Should they be one setting, shown in both places? | the page switch is remembered per browser; the computer's own setting is separate, and either one sends the job to the server. | A, one value, two places to see it, and the editor never has to choose because it starts on. (youtube-Q5) |
| 18.14 | A download on an editor's own computer can be stopped from four places: the app's menu, the app's status, the page's STOP, and the page's DOWNLOAD ON THE SERVER INSTEAD. Which stay? | all four stop the computer's download and let the server finish the rest; they differ only in where the button is and whether the page waits for the next contact. | A, the two page buttons do the same thing and so do the two app ones. (youtube-Q6) |
| 18.15 | A job can be cancelled from five places on the page (the progress panel, the job's downloads, the review's CANCEL SEARCH, the Queue list and the "Waiting for you" list), and only the review asks first. Keep them all, and which should ask? | five cancel buttons; only discarding a search at review asks for confirmation. | A, a cancel where the job is seen, and a question only where something unseen is lost. (youtube-Q7) |
| 18.16 | Failed clips can be retried with RETRY N FAILED on the job, or by pressing DOWNLOAD again on a finished job's review. Keep both? | both queue the failed and waiting clips again, with the same refusals. | A, DOWNLOAD on a finished review has to stay for picking more clips, and a retry button where the failures are shown costs nothing. (youtube-Q9) |
| 18.17 | A downloaded clip's folder can be opened (or the clip fetched from the NAS) from the download history and from a finished clip's row in a job. Keep both? | both do the same thing. | A, each list is where an editor looks for the clip at that moment. (youtube-Q10) |
| 18.18 | The periodic test of a known public video is off by default. Keep it? | an admin can switch on a test, at most every five minutes, that tries a known video the way a real download would; it is off and hidden by default. One of the admin alerts relies on it. | A, when nobody downloads for days it is the only way to learn of a block before an editor needs a clip, and it fetches a real video so a pass means downloading works. (youtube-Q15) |
| 18.19 | 480p, the "last hour" upload window, a number of results per term and skipping the term review can be asked for but are never offered on the page. Offer them or drop them? | only something calling the server directly can use them. | A, nobody has missed them, and 480p still exists as the step down after a truncated 720p stream. (youtube-Q16) |
| 18.20 | A second conversion target, an intra-frame editing format with uncompressed sound, exists but nothing can choose it. Can it go? | every clip is converted to H.264. | A, H.264 with AAC is what Resolve decodes everywhere, and a second target is a second set of rules. (youtube-Q17) |
| 18.21 | The page still carries handling for "a previous search is still open", which the queue makes impossible. Can it go? | the refusal and its confirmation are never shown, because new jobs always queue. | A, it can never be met. (youtube-Q19) |

## Your answers

Not yet answered.
