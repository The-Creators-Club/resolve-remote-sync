# Decision list, page 9: Accounts, privacy and the legal paperwork

Stays behind: never shown to the session that rebuilds the product.

18 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 9.1 Should a studio keep the choice of three ways for people to sign in (their NAS account, the organisation's single sign-on, or accounts the product keeps itself)?

- **Today:** the person installing the server picks one of three. What an admin can do differs between them: disabling an account and adding keys by hand exist only where the product keeps its own accounts; with NAS accounts the same password also opens the shared folders; with single sign-on there is no password here at all.
- **Options:** A: keep all three, with every action working the same for each. B: one account per person that the product keeps, whose password it keeps in step with the person's NAS login where the studio uses the shared folders, with single sign-on as an option a site can put in front of it. C: NAS accounts and single sign-on only.
- **Recommended:** B, because a person then has one account and one password everywhere, every admin action works the same, and the studio's NAS still opens with the same password.
- **What you would notice:** with B an admin manages one kind of account and sees the same actions for everyone; an editor notices nothing except that disable and suspend no longer depend on the sign-in method. With A nothing changes.
- (accounts-privacy-legal-Q1)

### 9.2 Under single sign-on, should the admins keep an emergency password door for when the sign-in service is down?

- **Today:** under single sign-on the sign-in page hides a password form behind "Admin sign-in"; only the admins named at install may use it. A lesson from real use says that where single sign-on is required, every way in must refuse a password, because a NAS password once let someone in on a single-sign-on site.
- **Options:** A: no password anywhere under single sign-on, as the lesson asks; a broken sign-in service then locks everyone out until it is back. B: keep the door for the admins named at install only, every other way in going through the service.
- **Recommended:** B, because a studio locked out of its own server by an outside service is worse than one guarded door that only the named admins can use and that counts every failure.
- **What you would notice:** with A an admin cannot reach the dashboard while the organisation's sign-in service is down; with B they can, by password.
- (accounts-privacy-legal-Q2)

### 9.3 Should the organisation's sign-in service be able to make someone an admin, or should its "admin" mark go?

- **Today:** a site can name a detail by which the sign-in service marks admins, but such a person only gets past the membership check and is not an admin anywhere in the product.
- **Options:** A: drop the mark; groups decide who gets in and the admin list decides who is an admin. B: let the mark make someone an admin. C: keep it as it is.
- **Recommended:** A, because a mark that looks like admin power and grants none is a trap, and the allowed groups already do the letting in.
- **What you would notice:** with A the setting disappears and nothing else changes for anyone; with B people the organisation marks become admins here.
- (accounts-privacy-legal-Q3)

### 9.4 Which ways of stopping a person should an admin have?

- **Today:** six different acts each stop a different mix of browsers, computers and sharing: disable (only where the product keeps its own accounts), suspend, sign them out of browsers, withdraw all their computers' sign-ins, withdraw one computer sign-in, and remove.
- **Options:** A: keep all six. B: three: suspend (everything stops, plan kept, resume restores it), "a device was lost" (end one computer's sign-in, or all of a person's computer and browser sign-ins, while the person stays in good standing), and remove; disable folded into suspend.
- **Recommended:** B, because each of the three answers a different real situation (pause someone, lose a laptop, someone leaves), and disable and suspend cannot be told apart from outside.
- **What you would notice:** with B an admin sees three plain choices on a person instead of six; a disabled account becomes a suspended one.
- (accounts-privacy-legal-Q6)

### 9.5 Should an admin be able to suspend any person, even one whose computer has never synced anything?

- **Today:** a person can be suspended only once the server has seen them as an editor (a tick, a report, an approved computer); an account that was made but never used cannot be suspended in advance.
- **Options:** A: any of the studio's people can be suspended. B: only people the server has seen at work.
- **Recommended:** A, because an admin who wants to stop someone should never be told to wait until that person has started.
- **What you would notice:** with A suspend is offered on every person in the list.
- (accounts-privacy-legal-Q7)

### 9.6 Can a site still choose to make the NAS's own administrator account the dashboard's admin?

- **Today:** installing refuses an admin list that names the NAS administrator, but a site can switch that refusal off, and a related choice lets the server hold the NAS administrator's password.
- **Options:** A: the refusal always holds. B: keep the opt-out.
- **Recommended:** A, because an admin of the product never needs the NAS's own top account, and holding it puts the whole NAS one stolen password away.
- **What you would notice:** with A a site that uses the NAS administrator as its admin must name a separate account once.
- (accounts-privacy-legal-Q10)

### 9.7 Should a studio still be able to let every editor open every project, instead of only the projects they are members of?

- **Today:** a site chooses between per-project access (each project's folder reachable only by its members) and shared access (every editor reaches every project). A lesson from real use requires each project folder to be limited to its members.
- **Options:** A: per-project access only. B: keep shared access as a site setting, off by default.
- **Recommended:** A, because the lesson asks for it and members follow ticks and grants on their own, so there is nothing for a studio to look after.
- **What you would notice:** with A an editor reaches only projects they tick or were given; nobody loses a project they work on.
- (accounts-privacy-legal-Q12)

### 9.8 Should every setting on an editor's computer take effect at once, without restarting the app?

- **Today:** some settings take effect only after the app restarts (wired or remote, the shared-work settings), others at once (privacy, rehearsal of fixes). The dashboard shows which settings wait for a restart.
- **Options:** A: every setting takes effect at once. B: keep as it is.
- **Recommended:** A, because a setting that silently waits for a restart is a setting the editor thinks is on when it is not.
- **What you would notice:** with A the "waiting for a restart" line disappears from the account page and the app.
- (accounts-privacy-legal-Q14)

### 9.9 Several things the server refuses or skips are written only to its log, where nobody sees them. Should every one of them be shown to an admin?

- **Today:** a computer whose sharing waits for approval on the NAS, a computer named like an unknown person, a project folder move the server refused to follow, a missing identity mark it refused to rewrite, a shared library in the wrong place, and per-project access doing nothing on Synology are written only to the server's log.
- **Options:** A: each becomes a problem shown to admins with its fix. B: leave them in the log.
- **Recommended:** A, because a refusal nobody sees looks exactly like everything working.
- **What you would notice:** with A admins see a few more problems, each with what to do.
- (accounts-privacy-legal-Q17)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 9.10 | Should a computer ever be allowed to report with one sign-in shared by the whole studio, or must every computer have its own? | each computer normally has its own sign-in tied to its person. A site can also allow one studio-wide credential that identifies nobody (off on new installations), and an admin is shown how many computers still use it and when it is safe to switch it off. A computer can also hold a credential set in its own settings beside the person's. | A, because a credential that identifies nobody cannot be withdrawn for one computer, and every computer already gets its own when its editor signs in. (accounts-privacy-legal-Q4) |
| 9.11 | Should an admin also be able to make a computer's sign-in by hand for the editor to paste in, or is the editor signing in on the computer the only way? | a computer gets its own sign-in when the editor signs in from the app; an admin can also issue one by hand, shown once, which the editor pastes into set-up or the app's settings, and some sites require that paste on top of the password sign-in. | A, because one sign-in already gives the computer everything it needs, and a second way means a secret travelling between people by hand. (accounts-privacy-legal-Q5) |
| 9.12 | Should an account marked "must change password" make the person change it at their next sign-in, or should the mark go? | setting a password can mark the account as having to change it, but nothing ever asks the person to. | B, because the one-time password an admin sets already tells the person to change it, and they can do that from their own page; a forced step adds a page nobody asked for. (accounts-privacy-legal-Q8) |
| 9.13 | Signing browsers out is offered from the header (sign out, sign out everywhere), from a person's own list of browsers, and from an admin's list of every browser in the studio. Keep all three? | all three exist and do overlapping things. | B, because each place then does a different thing: leave this browser, look after my own, look after someone else's. (accounts-privacy-legal-Q9) |
| 9.14 | Should Timeline Cards exist only inside the dashboard, behind its sign-in, or also run on its own with its own password? | Timeline Cards can be reached through the dashboard (the only form the studio uses), run on its own with its own password page and slow-down, or served on its own on the NAS with a per-device key or with no sign-in at all, through which anyone who reaches it can drive Resolve. The owner has ruled that the editor page answers nothing to a device that has not signed in. | A, because one door is the one that can be kept safe, and the studio uses no other. (accounts-privacy-legal-Q11) |
| 9.15 | Does the Footage Sorter still need to run as a program on one Windows computer with no sign-in, or only inside the dashboard? | the Sorter exists both as a program on one Windows computer, where anyone at that computer can do everything, and inside the dashboard behind its sign-in. | A, because one door with one notion of who is asking is simpler and safer, and the owner's requirements put every part behind the dashboard. (accounts-privacy-legal-Q13) |
| 9.16 | A person downloads their own data from their account page, and an admin downloads anyone's from the people list. Keep both? | both exist; download and erase are also offered on the people list for people known only by a computer. | A, because they are for different people (a person's own right to their data, and an admin answering for someone else), and the owner's ruling says a person can download what is held about them. (accounts-privacy-legal-Q15) |
| 9.17 | The licence can be opened by itself, from the app's menu and from the app's settings window. Keep all three? | the app opens it by itself after starting, the menu has "Accept the licence agreement to start syncing…", and the settings window has "READ AND ACCEPT THE LICENCE". | A, because each is where an editor who is not syncing will look, and none can do anything else. (accounts-privacy-legal-Q16) |
| 9.18 | Two things in these items are tools for the people building and releasing the product. Can they go from the specification? | a computer can read its plan with no sign-in when the server has no sign-in secret set (only on a builder's test server), and the owner's release secrets are kept encrypted on his own computer and loaded into one window when he publishes. | A, because no person using the product meets either. (accounts-privacy-legal-Q18) |

## Your answers

ANSWERED 2026-11-24. After answering pages 2 and 3 and most of page 4 one
by one, he said of everything still waiting: "accept all the
recommendations." So every question on this page is answered with its
recommendation.
