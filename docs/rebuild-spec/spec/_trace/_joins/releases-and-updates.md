# Joins aimed at releases-and-updates

## Checked

- J1 | fine
- J2 | F1
- J3 | fine
- J4 | fine
- J5 | F2
- J6 | F3, F4
- J7 | F5, F6
- J8 | F7
- J9 | fine
- J10 | F8, F9
- J11 | F10, F11, F12
- J12 | fine
- J13 | fine
- J14 | fine
- J15 | F13, F14
- J16 | fine
- J17 | fine
- J18 | fine

## Findings

### F1: Downloading the product from the vendor needs a site credential in one piece and sends no credential at all in the other
- Kind: contradiction
- From: accounts-privacy-legal / What a customer receives, and what never
- Here: Signing and trust / The server believes only a release list the vendor signed, and refuses an earlier one played back; Customer sites and the vendor's release feed / Every site takes the vendor's versions from one signed list
- From says: "Downloading the product needs a credential issued to that site."
- Here says: "The list is fetched only over secure connections at every hop (a redirect to an insecure address is refused), sends no credential of any kind, and is limited in size." (and nowhere is a credential issued to a site, or asked for when a site takes a version from the vendor)
- Settled by: ACC-065 (ruling): "downloading the product requires a credential issued to that site."
- Fix: releases-and-updates says that every version a site takes from the vendor is downloaded with the credential issued to that site, how a site gets it, and what the admin sees when it is missing or refused (and, since a call carrying a credential follows no redirect, that those downloads follow none).

### F2: Where the vendor's offer sits among the versions a site holds, and which held versions are folded away
- Kind: contradiction
- From: dashboard-1 / Builds on offer are listed in a fixed order
- Here: Pushing updates and seeing who has what / The versions page shows every version the site holds
- From says: "the ones being served to the studio's computers come first, then what the vendor offers, then any other versions the server holds, folded away."
- Here says: "Each group shows its current version and its newest version first. Older held-back versions are folded away" and, for the vendor's offer, "the vendor's versions are in the vendor's list below."
- Settled by: REL-038 (ruling): "Each product and platform shows its newest build first, older ones only in a rollback picker, ... builds served here before those offered by the vendor, by product then platform."
- Fix: dashboard-1 says the newest held version of each kind and platform is shown with its group (only older ones folded), and both pieces state the same order of the served versions, the held versions and the vendor's offer.

### F3: A vendor list that was never checked is stale in one piece and never called stale in the other
- Kind: contradiction
- From: dashboard-1 / Fleet-wide trouble is shown above the computers
- Here: Customer sites and the vendor's release feed / The server checks the vendor's list every day, and an admin can check now
- From says: "\"stale\" when it has been read before and the last check is older than the stale limit (a feed never yet checked is not called stale)"
- Here says: "Stale means never checked, or no successful check for more than 7 days."
- Settled by: REL-071 (situation, weaker): "With no successful update check for 7 days the home page shows a banner, and a site never checked counts as stale."
- Fix: dashboard-1 drops "a feed never yet checked is not called stale" and names the limit as 7 days without a successful check.

### F4: The vendor list's trouble is shown in two places with two different texts
- Kind: differs
- From: dashboard-1 / Fleet-wide trouble is shown above the computers
- Here: Customer sites and the vendor's release feed / The server checks the vendor's list every day, and an admin can check now
- From says: "when the vendor's release feed cannot be read, when it was last checked, how many days ago, the last error, \"stale\" ..." (above the list of computers)
- Here says: "Then the overview shows a banner: \"No successful update check for N days. Last checked <ago>: <error>. This site is not receiving fixes, which looks the same as no fixes having been published.\""
- Settled by: decisions page 10, 10.4, answered 2026-11-24 with its recommendation: "keep them as one list of problems, each shown once and mailed once, as written."
- Fix: dashboard-1 points to the one overview banner of releases-and-updates instead of describing its own feed line above the computers, or releases-and-updates names that place as the banner's only home.

### F5: The reply action pushes the "newest" build and refuses when the computer runs it; the push itself sends the current version and has no such refusal
- Kind: contradiction
- From: dashboard-2 / What a reply to the server check can carry out
- Here: Pushing updates and seeing who has what / An admin pushes a version to one computer
- From says: "Push the newest app build to a computer (\"asked <who> to update to X on its next report\") | no such computer, no newest build for its platform, or it already runs it"
- Here says: "naming it (up to 32 characters) or, with none named, the current version for that computer's operating system" and "A version already running is not installed again."
- Settled by: dashboard-2's own rule "Each action does exactly what the matching control on the dashboard does", and REL-064 (ruling): "only newer builds are offered as updates" does not make a held-back newest build the push target.
- Fix: dashboard-2 says the reply pushes the current version for that computer's operating system, with the push's own refusals ("no current version of the app is published for that computer's operating system", the went-back-from refusal), and either both pieces refuse a push of the version already running or neither does.

### F6: Withdrawing a push is refused when nothing waits in one piece and always succeeds in the other
- Kind: contradiction
- From: dashboard-2 / What a reply to the server check can carry out
- Here: Pushing updates and seeing who has what / An admin pushes a version to one computer
- From says: "Withdraw a pushed update for a computer | no such computer, or no update waiting"
- Here says: "The admin can withdraw a waiting push at any time (\"Withdraw the request. The computer keeps what it runs.\"). It always succeeds, even when nothing was waiting"
- Settled by: the owner must say: when an admin withdraws an update for a computer that has nothing waiting, is that told as a refusal or quietly accepted?
- Fix: whichever piece loses changes to the other's answer, so the reply action and the dashboard button do the same.

### F7: The setting for unattended updates has two names
- Kind: differs
- From: dashboard-2 / Every setting of the site
- Here: Offering an update to a computer / A studio can let its computers take newer versions without anyone clicking
- From says: "Setting: Updates with nobody clicking. Does: every editor's computer installs any newer build offered to it without anyone pressing anything (never an older one)."
- Here says: "Setting: Update editors' computers by themselves. Does: lets each editor's computer install a newer offered version with nobody clicking."
- Settled by: OWNER_REQUIREMENTS section 5: "Every page, part and setting therefore has a plain name and a few search words in this specification."
- Fix: dashboard-2 uses the name and search words given in releases-and-updates (or points to it instead of repeating the setting).

### F8: The editor's message after going back from a crashing update is a different sentence
- Kind: contradiction
- From: editor-app / A version that cannot stay up is replaced by the version before
- Here: Rolling back and withdrawing a build / A new version that keeps crashing puts the previous one back by itself
- From says: "\"⚠ The vX update kept crashing, so CC Sync went back to the previous version. Your admin has been told\""
- Here says: "\"The last update kept crashing, so CC Sync went back to v<version>.\""
- Settled by: the owner must say: when the app goes back from a crashing update, does the editor's message name the version that crashed or the version now running, and does it say the admin has been told?
- Fix: one piece carries the sentence and the other points to it.

### F9: With no earlier version to go back to, the app is left down in one piece and carries on in the other
- Kind: contradiction
- From: editor-app / A version that cannot stay up is replaced by the version before
- Here: Rolling back and withdrawing a build / A new version that keeps crashing puts the previous one back by itself
- From says: "If there is no earlier version to go back to, the app is left down and the admin is told that a person must step in."
- Here says: "Then the app carries on, says why in the start-up log, and the server is told, so a person can step in. None of this can stop the app from starting when it would otherwise start."
- Settled by: decisions page 8, 8.11, answered 2026-11-24 with its recommendation: "one rule says one thing to the editor and admin, and it keeps the ruled three-an-hour relaunch for ordinary crashes."
- Fix: releases-and-updates says that with nothing to go back to the crashing version is relaunched no more than three times an hour and then left down, with the admin told a person must step in, and editor-app says the same in those terms.

### F10: A download link an admin hands a new editor works without signing in; this piece tells anyone not signed in to sign in
- Kind: contradiction
- From: editor-app / An editor gets the installer for a new computer, or to repair one
- Here: Installing an update on an editor's computer / Anyone signed in can download the app and the installer
- From says: "an admin can hand them the installer as a file or as a download link that works from anywhere without signing in."
- Here says: "Neither signed in nor a computer with credentials: told to sign in." and "Who: anyone signed in, and every computer of the studio."
- Settled by: decisions page 8, 8.12, answered 2026-11-24 with its recommendation: "the link an admin hands over is the only other way in a new editor needs, since they cannot sign in yet."
- Fix: releases-and-updates adds the admin-handed installer link as a way to download without signing in (who can make it, what it reaches, and what happens when it is used), and leaves "told to sign in" for every other request.

### F11: The sentences for "nothing published" and "file missing" differ for the same installer download
- Kind: contradiction
- From: editor-app / An editor gets the installer for a new computer, or to repair one
- Here: Installing an update on an editor's computer / Anyone signed in can download the app and the installer
- From says: "\"No <platform> installer has been published for this studio yet, so there is nothing to download. Ask whoever set this dashboard up for the installer.\"" and "\"installer file is missing on the server: re-publish it\""
- Here says: "Nothing current: \"no current <platform> <kind> is published\"." and "\"the file for that version is missing on the server\""
- Settled by: the owner must say: when a person follows an installer download and nothing is published, or its file is gone, which sentence do they read?
- Fix: one piece carries the sentences for a person following the installer link and the other points to them.

### F12: Admins are told to "publish" or "re-publish" an installer, but a site only takes versions from the vendor
- Kind: contradiction
- From: editor-app / An editor gets the installer for a new computer, or to repair one
- Here: Customer sites and the vendor's release feed / Every site takes the vendor's versions from one signed list
- From says: "with a line telling admins how to publish one (see Releases and updates: Making and publishing a release)" and "re-publish it"
- Here says: "There is one way to publish a new version. The vendor starts it" and "With no installer held, the page new editors download from tells the customer to take one from the vendor."
- Settled by: decisions page 10, 10.3, answered 2026-11-24 with its recommendation: "one publish; the vendor's studio is simply the first site reading the vendor's list".
- Fix: editor-app tells the admin to take the installer from the vendor (pointing to "An admin brings one version from the vendor onto the site by hand") instead of publishing or re-publishing it.

### F13: A server update keeps the dashboard answering with no gap in one piece and takes it offline for about ten seconds in the other
- Kind: contradiction
- From: server-install-and-running-1 / Updating the server never takes the dashboard away
- Here: The server updating itself / An admin updates the server with one button (also An admin sees which server updates are on offer, The admin watches each step of a server update, An admin moves the server back to an earlier version)
- From says: "A server update keeps the dashboard and every open editor's page answering throughout, with no gap a person or an editor's app can notice."
- Here says: "\"Update this server to <version>? It will be offline for about ten seconds while it restarts. The data is backed up first.\"" and "restarting (\"restarting: the server is offline for about ten seconds\")"
- Settled by: SRV-042 (ruling): "A server update keeps the dashboard and open editor pages answering throughout, with no gap a person or an editor's app can notice."
- Fix: releases-and-updates drops every "offline for about ten seconds" from server updates and its steps (and says whether going back keeps the same promise), so no message tells an admin the dashboard goes away.

### F14: A server update is never forced past a running download in one piece and can be forced by the admin in the other
- Kind: contradiction
- From: server-install-and-running-1 / Updating the server never takes the dashboard away
- Here: The server updating itself / An admin updates the server with one button
- From says: "An update waits until running download jobs have finished, trying again by itself, and is never forced past a running job."
- Here says: "\"N YouTube download(s) are running: an update restarts the server for about ten seconds and interrupts them. Wait, or apply again with force.\" ... The admin can override with force"
- Settled by: SRV-055 (situation, weaker): "A server update waits until running download jobs finish, retrying by itself, and is never forced past a running job."
- Fix: releases-and-updates makes the admin's button wait for running downloads and apply by itself once they finish, with no force override, or, if the owner wants the override, server-install-and-running-1 drops "never forced".
