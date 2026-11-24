# Decision list, page 12: The server: installing it and keeping it running, part 2

Stays behind: never shown to the session that rebuilds the product.

6 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 12.1 TrueNAS and Synology lock editors down in different ways. Is it right that the text states one result on both and the differences only as facts about each NAS?

- **Today:** on TrueNAS the product adds sign-in rules and asks the NAS to switch off password sign-in (which TrueNAS refuses for accounts with Windows file sharing); on Synology it adds nothing because DSM already limits editors, but must turn the file-transfer service on and check application-privilege rules; home-folder permissions are set differently and only TrueNAS logs a refusal; TrueNAS lets a site give editors a full shell, Synology never does; TrueNAS demands both dashboard addresses, Synology makes them optional and refuses every-address.
- **Options:** A: one result on both (file transfer only, by key only, confined to the tree, dashboard only on the NAS itself and the private network), with each NAS's own facts stated. B: keep each NAS's own options (a shell on TrueNAS, address choices that differ).
- **Recommended:** A, since the editor and admin get the same thing on either NAS and the differences are only what each system needs.
- **What you would notice:** with A a TrueNAS site can no longer give editors a shell on the NAS, and nobody types dashboard addresses.
- (server-install-and-running-2-Q2)

### 12.2 On the very first connection to the NAS, should its identity be trusted on its own (and its fingerprint shown), or must the admin confirm it first?

- **Today:** the set-up wizard trusts the first certificate seen when the fingerprint box is left blank; the hand-run install refuses a NAS it has never seen unless the person explicitly allows "trust once"; the record of trusted NAS identities is private to the installing person on macOS and Linux but not on Windows; checking can be turned off (the studio does).
- **Options:** A: first connection during set-up trusts and records it, shows the fingerprint, a change is refused forever; the record is readable only by admins on every system; checking cannot be turned off. B: the admin must tick "trust once" before the first connection.
- **Recommended:** A, because set-up is already a deliberate act by the admin and a second confirmation adds a step that protects nothing more.
- **What you would notice:** with A the admin presses nothing extra; with B they confirm the fingerprint once. Either way the studio can no longer turn the check off.
- (server-install-and-running-2-Q3)

### 12.3 Should the product make the server's own NAS account on TrueNAS too, as it does on Synology?

- **Today:** on TrueNAS the account must be made by hand when the storage pool is built and the product refuses to make it; on Synology the product makes it.
- **Options:** A: the product makes it when missing on both kinds. B: by hand on TrueNAS, by the product on Synology.
- **Recommended:** A, one way on both, and one less thing for the person installing to do.
- **What you would notice:** with A a new TrueNAS site has no account to make by hand.
- (server-install-and-running-2-Q4)

### 12.4 When the server's account numbers on a TrueNAS do not match the site's settings, should the install stop until they do?

- **Today:** the differences are named and the fix given; whether the install then stops or goes on is not known.
- **Options:** A: stop until they match. B: report and go on.
- **Recommended:** A, because a server writing the studio's tree as the wrong owner can lock editors out of footage.
- **What you would notice:** with A a mismatched site cannot finish installing until the numbers are set.
- (server-install-and-running-2-Q5)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 12.5 | Locking every admin page behind a login happens on its own. Should the set-up wizard also have a button that does it? | the server checks and locks the folder-syncing helper's admin page on its own, and the set-up wizard runs the same check and action again; a separate hand-run step locks it too, and installing an editor's computer locks that computer's copy. | A, because a check that runs on its own and is shown needs no second way to start it. (server-install-and-running-2-Q1) |
| 12.6 | Is bringing a studio's existing editor accounts on the NAS into the product still wanted? | the install can list the editors' accounts on TrueNAS; on Synology the listing always fails in a real run. It is used only when moving older accounts over. | A, since the owner requires that the studio's people and computers carry over, and this is how existing NAS accounts are matched. (server-install-and-running-2-Q6) |

## Your answers

ANSWERED 2026-11-24. After answering pages 2 and 3 and most of page 4 one
by one, he said of everything still waiting: "accept all the
recommendations." So every question on this page is answered with its
recommendation.
