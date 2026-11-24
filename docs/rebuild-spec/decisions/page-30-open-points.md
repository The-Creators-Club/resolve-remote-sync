# Decision list, page 30: what only you can answer

Stays behind: never shown to the session that rebuilds the product.

Written by hand, 2026-11-24. These came from three places: points the
writers of the specification could not settle and the present code could
not answer either; places where the code turned out to differ from what the
specification assumed; and three questions that have been waiting since the
plan was made. **Reply with the numbers you disagree with; anything you do
not mention is taken as the recommendation.** Where I give a figure of my
own as a suggestion, it is marked as mine.

## Choices

### 30.1 Which parts are switched on for a brand-new site?

- **Today:** a new site starts with the b-roll archive and music on, and YouTube downloads, Timeline Cards and the Footage Sorter off. The pieces of the specification disagree with each other here (the music piece says music starts off, the server piece says on), because this was never decided.
- **Options:** A: every optional part starts off, except the help for the editing program, which you already decided starts on. B: as today.
- **Recommended:** A. It is one rule, and it is what you said on page 1: a customer who only wants syncing sees none of them.
- **What you would notice:** nothing in your own studio, where what is switched on is carried over. A new customer's dashboard starts with syncing only, and an admin switches on what they bought.

### 30.2 Is making proxies switched on by default on every computer?

- **Today:** by default a computer makes proxies only if it works straight off the NAS and brings no proxies down. On an ordinary editing computer it is off until someone switches it on.
- **Options:** A: on by default on every computer, under the usual rules (only while nobody is at the keyboard, giving way to Resolve, never filling the drive). B: as today.
- **Recommended:** A. A clip with no proxy cannot be seen by anyone else in the team, and the computer holding a new original is often the only one that can make its proxy until the original has finished uploading. The specification is written to A.
- **What you would notice:** with A, footage an editor shoots and drops on their own computer gets its proxies made there while they are away from it, with nothing to switch on.

### 30.3 Who may change a computer's own sync settings?

- **Today:** six settings of one computer can only be changed by editing a file on that computer: the warning at shutdown, keeping the computer awake while files move, how big the recovery folder may grow, the limits that make downloads stop themselves, how much free space is kept on the sync drive, and how long each project syncs before the next has its go.
- **Options:** A: the editor changes them in the app's settings for their own computer, and an admin can change them for any computer from the dashboard; except the limits that protect footage (the download safety limits), which only an admin may change. B: an admin only, for all six. C: the editor only.
- **Recommended:** A. It matches every other per-computer setting, and keeps the one that protects footage out of reach of a hurried click.
- **What you would notice:** these six appear in the app's settings and on each computer's page of the dashboard, and no file ever needs editing.

### 30.4 How long are records of conversations with the assistant kept?

- **Today:** for ever. Nothing deletes them and there is no setting.
- **Options:** A: 30 days by default, as a site setting. B: 180 days, the same as the history of who did what. C: kept until someone deletes them.
- **Recommended:** A (the figure is my suggestion). The privacy paperwork is easier to stand behind when little is kept, and a site can lengthen it.
- **What you would notice:** an assistant conversation older than the period can no longer be reopened.

### 30.5 Which recordings does the music library keep out?

- **Today:** nothing is kept out except folders named "_stems". Two of the lessons from real use pull apart: one says recorder takes, voiceover, stings under 30 seconds and recordings over 15 minutes stay out of the library (interview and field recordings once swamped it); the other says music of any length, two hours and more, is indexed properly.
- **Options:** A: those are left out only when the product looks over a whole folder of mixed audio; a track a person drops in by hand is always taken, whatever its length. B: nothing is ever left out. C: they are always left out, dropped by hand or not.
- **Recommended:** A. It meets both lessons. The specification is written to A.
- **What you would notice:** with A, pointing the library at a folder full of interview audio does not fill it with interviews, and a long ambient track you drop in yourself is still taken.

### 30.6 On the board, which key sets a card aside?

- **Today:** there is no board in the product yet. You once asked that pressing 0 should stage cards; that was never built.
- **Options:** A: the same key and gesture the editor uses to move a cut to the shelf, since you ruled that the board uses the editor's keys wherever the same act exists. B: 0, as you asked then.
- **Recommended:** A, so nothing is learned twice.
- **What you would notice:** the key you already use in the editor does the same on the board.

### 30.7 Do the ten reading aids stay?

- **Today:** the editor has ten aids for cutting speech in a language you do not read (the word-by-word gloss, grammar and name marks, romanisation and others), each with its own switch, a settings panel and a daily allowance of assistant calls. The writer could not tell from its sources whether you use them.
- **Options:** A: all ten stay, as they are. B: you name the ones you use and the rest go.
- **Recommended:** A unless you tell me which you never use: they are written as live.
- **What you would notice:** nothing with A.

### 30.8 Does the faint strike through filler words stay?

- **Today:** one of the reading aids strikes faintly through filler words. You once said of hesitation marks "lets ditch all this", and the writer could not tell whether that covered this one.
- **Options:** A: it stays as one of the aids, off unless switched on. B: it goes.
- **Recommended:** A, since it is off unless you switch it on.
- **What you would notice:** with B the switch is gone.

### 30.9 Does the product ever place name titles in Resolve?

- **Today:** it never has. The only titles it places are the notes on gaps. Two of your rulings say where name titles sit on the timeline and how they survive a hand-over, which reads as if the product places them.
- **Options:** A: no. The rulings describe how name titles you add yourself in Resolve must be treated (left where they are, never moved or lost by a later hand-over). B: yes, the product places a name title for each speaker, which is new work.
- **Recommended:** A.
- **What you would notice:** with A, name titles you make in Resolve are respected and nothing new appears.

### 30.10 A render or export ends at the first long stretch of empty timeline: how long is long?

- **Today:** not built. Your ruling asks that a timeline's real end be found by the first long stretch of empty timeline ("a gap of minutes"), so that stray clips parked far to the right are not rendered.
- **Options:** A: one minute by default, shown and settable by hand each time. B: five minutes.
- **Recommended:** A (the figure is my suggestion).
- **What you would notice:** a render stops where the film stops, and you are shown where that is before it starts.

### 30.11 Bridging the pause between two captions: up to what length?

- **Today:** not built. Your ruling asks that a short pause between two captions be bridged, so a caption holds on screen instead of flickering off.
- **Options:** A: pauses under one second are bridged, as a setting. B: you name the length.
- **Recommended:** A (the figure is my suggestion).
- **What you would notice:** captions no longer blink off for a fraction of a second between lines.

### 30.12 What is the assistant called on screen?

- **Today:** the editor's buttons and messages name it ("Ask Claude", and model names in the strength picker). The specification has "[the assistant]" in every such place, waiting for this answer.
- **Options:** A: one neutral name everywhere ("Assistant"), with strengths described by what they do (fastest, stronger, most capable, with the price). B: the name of whichever assistant the site has connected. C: the name it carries today.
- **Recommended:** A. A site may connect a different kind of assistant, and a neutral name is never wrong.
- **What you would notice:** "Ask Assistant" where it says "Ask Claude" now.

### 30.13 Does the page a client opens from a link take the product's one look?

- **Today:** the public page a client sees has a look of its own, different from the dashboard and from the editor.
- **Options:** A: it takes the Timeline Cards editor's look, like everything else. B: it keeps a look of its own, deliberately different.
- **Recommended:** A, since you ruled one look everywhere and have not said the client page is an exception.
- **What you would notice:** clients see the same style your editors do, with your studio's name and mark.

### 30.14 Is "built in Rust" a requirement the rebuild is given?

- **Today:** you asked whether it could be built in Rust, and I said it fits the app on the editor's computer and the server (one native program, safer, lighter, faster to start), while browser pages, the link to Resolve and the analysis of footage stay in their own languages. Everything else about how it is built is left to the rebuild session under your guiding principle.
- **Options:** A: yes, state it: Rust for the app on the editor's computer and for the server. B: say nothing and let the rebuild session choose by the guiding principle.
- **Recommended:** A. It is your wish for the new build, not a description of the old one, so it does not bias the rebuild toward what exists.
- **What you would notice:** nothing on screen. One installed program instead of several, and less memory used.

## For your information: no answer needed

- **Three safety stops your lessons ask for were never built**: stopping a card copy that makes no progress, stopping a download that writes nothing, and telling an admin when the NAS's own clock is wrong. The specification requires all three. No time was ever ruled for the first two, so the rebuild chooses one and shows it; for the NAS's clock it uses the amount already used for a computer's clock (shown from one minute out).
- **The reminder every few days about footage resting only on a laptop**, which you ruled, does not exist either: today laptop-only footage heads the daily mail. The specification keeps your ruling.
- **Two questions on page 9 cover the stand-alone forms**: whether anyone still uses the Footage Sorter as a program on its own on one Windows computer, and Timeline Cards served on its own on the NAS (neither has a sign-in). The specification has one Sorter and one Timeline Cards, both inside the dashboard.
- **Whether stacks come back in the editor** is on page 24. The editor you use has none; they existed only before it.

## To be tried before the pack is handed over (mine to do, with your Resolve and the Synology)

- Eight of Resolve's clip colour names (Purple, Apricot, Beige, Lime, Navy, Olive, Orange, Yellow) and the order of its marker colours were never checked against a real Resolve.
- Reading a saved Resolve project was only ever looked at for one version of Resolve.
- Whether the entries the product adds to Resolve's Scripts menu appear and read In and Out marks correctly was never tried in the build the inventory describes (the grading-frames release moved them; check the present build).
- Whether a Synology account that is not an administrator can manage users, groups and snapshots, so whether the server's account there can be less than an administrator.

## Your answers

ANSWERED 2026-11-24. After answering pages 2 and 3 and most of page 4 one
by one, he said of everything still waiting: "accept all the
recommendations." So every question on this page is answered with its
recommendation. Where a figure was marked as my own suggestion (30 days for
assistant records, one minute of empty timeline, pauses under one second
between captions), it is now his.
