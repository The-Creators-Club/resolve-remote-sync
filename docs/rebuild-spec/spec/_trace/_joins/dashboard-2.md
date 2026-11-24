# Joins aimed at dashboard-2

## Checked

- J1 | F1
- J2 | F2, F3
- J3 | fine
- J4 | F4
- J5 | F5
- J6 | fine
- J7 | F6
- J8 | F4
- J9 | fine
- J10 | F7, F8
- J11 | fine
- J12 | fine
- J13 | fine
- J14 | fine
- J15 | F9, F10
- J16 | F11
- J17 | fine
- J18 | fine
- J19 | F12
- J20 | fine
- J21 | fine
- J22 | fine
- J23 | fine

## Findings

### F1: A settings save that switches a kind of reporting off asks first in one piece and is never asked about in the other
- Kind: missing
- From: accounts-privacy-legal / An admin switches a kind of reporting off for the whole studio
- Here: Saving settings checks every field first and one bad field changes nothing
- From says: "Before anything switches a kind off, whether a save, bringing settings in from a file, or undoing a settings change, the admin is asked: "Stop every computer reporting: <names>? ...", with "Stop reporting"."
- Here says: "Each save says "saving...", then "saved at HH:MM:SS" by the person's own clock, or "could not save: <reason>"" (import and undo name the reporting they would switch off; a plain save asks nothing)
- Settled by: the owner must say: when an admin saves settings that switch off a kind of reporting from computers, is the admin asked to confirm before it is saved, as on import and undo?
- Fix: dashboard-2's save section should say that a save switching a kind of reporting off first asks the question accounts-privacy-legal gives (pointing there for the wording), and its import and undo should name the same question and "Stop reporting" button.

### F2: The problem for a computer reaching the dashboard unencrypted over the internet is serious in one piece and a warning in the other
- Kind: contradiction
- From: accounts-privacy-legal / A credential never crosses the internet unencrypted
- Here: The dashboard warns when a computer reaches it unencrypted over the public internet
- From says: "Admins are told, as a serious problem, "a computer reaches this dashboard unencrypted over the internet""
- Here says: "It raises a warning only for an unencrypted connection over the public internet."
- Settled by: the owner must say: is a computer reaching the dashboard unencrypted over the public internet a serious problem (repeated daily while it lasts) or a warning (said once)?
- Fix: dashboard-2 should either say "a serious problem" or, better, keep only the recording of how each computer connects and point to accounts-privacy-legal for the problem, its severity, repetition and fix.

### F3: Alert mail may be sent unencrypted here, while the other piece refuses any mail setting that sends the password unencrypted
- Kind: contradiction
- From: accounts-privacy-legal / A credential never crosses the internet unencrypted
- Here: An admin chooses who is told when the server finds a problem; Every setting of the site (Secure mail connection)
- From says: "A mail setting that would send its password unencrypted is refused when saved and when sending."
- Here says: "The connection is encrypted unless the admin turns that off" and "Setting: Secure mail connection. Does: encrypts the connection to the mail server; off sends unencrypted."
- Settled by: ACC-076 (kind situation, weaker): "No password is sent over an unencrypted connection; such a mail setting is refused at save and at send."
- Fix: dashboard-2 should say that turning the secure mail connection off while a mail sign-in is set is refused when saved and when sending, with the refusal's wording.

### F4: What a studio-wide stop stops: here only syncing, elsewhere shared work and Timeline Cards' Resolve too
- Kind: missing
- From: fleet-jobs / A studio-wide stop or the app closing puts running work back to waiting; cards-to-resolve-and-exports / A computer says what stops its Resolve taking part
- Here: An admin stops syncing on every computer at once, with a reason
- From says: "While the fleet is stopped, no computer takes any shared work." and "syncing is stopped by your admin, so this computer is not taking work of any kind"
- Here says: "Stops uploads, proxy downloads and shared project files on every editor's computer." and the confirmation "Uploads, proxy downloads and shared project files stop everywhere until you start them again here."
- Settled by: JOB-022 (kind situation, weaker): "A running job always obeys cancel, a studio-wide stop and its time limit"; SYN-053 (kind situation, weaker): "A studio-wide stop halts every transfer on every folder, including libraries and first-time acceptance"
- Fix: dashboard-2's stop explanation and confirmation should also say that shared work running anywhere goes back to waiting and none is taken, shared libraries stop too, and no computer starts taking part in Timeline Cards while it lasts, so the admin is told the whole effect.

### F5: The Overview says a stop ends after 24 hours; here the admin can choose any length up to 30 days
- Kind: contradiction
- From: dashboard-1 / The Overview is the home page
- Here: An admin stops syncing on every computer at once, with a reason
- From says: "Nothing is deleted, and the pause ends by itself after 24 hours."
- Here says: "The stop lasts 24 hours unless the admin chooses another length, from any time above zero up to 720 hours (30 days), and then ends by itself."
- Settled by: the owner must say: when an admin stops syncing everywhere, may they choose how long the stop lasts (up to 30 days), or does it always end after 24 hours unless kept on? (DSH-144, kind situation, says only "ends after 24 hours unless extended")
- Fix: if a length can be chosen, dashboard-1's shortcut text should say "ends by itself after 24 hours unless you choose another length"; if not, dashboard-2 should drop the chosen length.

### F6: The settings search says the settings' groups are given here, but this piece deliberately gives no groups
- Kind: contradiction
- From: dashboard-1 / The settings search finds settings only
- Here: Every setting of the site
- From says: "Settings are listed in groups by what they do; the groups are in the second part of the dashboard's specification."
- Here says: "Each setting below is one thing an admin can change for the whole site." (a flat list, no groups)
- Settled by: OWNER_REQUIREMENTS section 5: "The specification lists every setting by what it does, with no arrangement. The builder proposes the menu and the grouping of settings from that list, and the owner approves the map before any page is built."
- Fix: dashboard-1 should say the groups are the ones the builder proposes and the owner approves, not that they are in dashboard-2.

### F7: The daily mail about footage not at home is unknown to the mail settings: who gets it, its sender, the list of what was sent and retrying
- Kind: missing
- From: footage-sorter-and-camera-cards-1 / A report and a daily mail say what footage is not at home
- Here: Alerts by mail (An admin sees every message that was sent; A message that cannot be sent is tried again)
- From says: "Every day at 08:00 studio time the report is mailed to the owner, from "Backups"" and "When mail is not set up, the overview says that these reminders cannot be sent"
- Here says: nothing (recipients are only "Alert recipients"; the sent list's kinds are "an alert, a clearance, the daily "still here", the weekly report, a test, the server check"; retries name the same messages)
- Settled by: the owner must say: does the daily mail about footage not at home go to the alert recipients through the alert mail settings, and does it appear in the list of what was sent and get tried again like every other message?
- Fix: dashboard-2 should name this mail among the messages it sends, lists and retries, and say who receives it; footage-sorter-and-camera-cards-1 should say "the alert recipients" (or whoever the owner names) instead of "the owner".

### F8: The studio's time zone defaults to universal time here, to UTC+8 or the NAS's zone in the Footage Sorter, though the owner wants one zone
- Kind: contradiction
- From: footage-sorter-and-camera-cards-1 / A report and a daily mail say what footage is not at home (and The studio has one time zone, used for every time that carries none of its own)
- Here: Every setting of the site (Time zone)
- From says: "When no studio time zone has been set, the NAS's own zone is used" and "Setting: Studio time zone. ... Default: UTC+8."
- Here says: "Setting: Time zone. Does: the time zone the weekly report, the daily "still here" message and the server check keep to. Default: blank, which is universal time."
- Settled by: footage-sorter-and-camera-cards-1-Q14 "Answered by the owner 2026-11-24: A, one named studio time zone that everything follows"; its default the owner must say: when no studio time zone has been set, which clock does everything follow?
- Fix: dashboard-2's Time zone entry should be the one studio time zone that every scheduled thing and every zone-less time follows, with the one default the owner names, and the Footage Sorter's entries should point to it instead of defining their own.

### F9: "Nobody is being told" after 30 days without a delivery, and "cannot verify", are absent here
- Kind: contradiction
- From: server-install-and-running-1 / Every problem the server finds reaches a person
- Here: The dashboard says whether alerts are really reaching anyone
- From says: "With no alert destination set, or nothing delivered in 30 days, the home page and the protection list say "nobody is being told"; a delivery record that cannot be read shows "cannot verify"."
- Here says: "While no destination is set (and the admin has not chosen to tell nobody), a warning stands among the open problems: "Nobody is being told when this server finds a problem..."" (30 days without delivery shows only "nothing has been delivered through the e-mail channel since YYYY-MM-DD" on the channel's status line; an unreadable record is not mentioned)
- Settled by: SRV-102 (kind situation, weaker): "With no alert destination, or none delivered in 30 days, the home and protection pages say "nobody is being told"; an unreadable record shows "cannot verify"."; whether the admin's deliberate choice to tell nobody ends it the owner must say: when an admin has chosen on purpose to tell nobody, does the home page still say nobody is being told?
- Fix: dashboard-2 should raise the standing "nobody is being told" problem also when nothing was delivered in 30 days and say "cannot verify" when the delivery record cannot be read; server-install-and-running-1 should say what the deliberate "tell nobody" choice does to it.

### F10: The mail certificate check is one setting under two names, defined in both pieces
- Kind: differs
- From: server-install-and-running-1 / Every problem the server finds reaches a person
- Here: Every setting of the site (Verify the mail server's certificate)
- From says: "Setting: Checking the mail server's certificate. Does: whether alert mail refuses a mail server whose certificate or name does not match. Default: on."
- Here says: "Setting: Verify the mail server's certificate. Does: refuses to send when the mail server's certificate does not match it; off only for a studio's own internal mail server with its own certificate. Default: on."
- Settled by: OWNER_REQUIREMENTS section 5: "Every page, part and setting therefore has a plain name and a few search words in this specification." (one setting, one name)
- Fix: server-install-and-running-1 should drop its setting entry and point to dashboard-2's "Verify the mail server's certificate".

### F11: A computer's report is answered within a second here, in about a tenth of a second in the other piece
- Kind: differs
- From: server-install-and-running-1 / The server stays quick under load
- Here: One slow action never holds up anyone else
- From says: "Reports from editors' computers finish in about a tenth of a second under load"
- Here says: "While one change is being written, every other page and every computer's report is still answered within a second."
- Settled by: SRV-116 (kind situation, weaker): "Reports finish in about a tenth of a second under load"
- Fix: dashboard-2 should give the tenth of a second for computers' reports (keeping a second for pages), or point to server-install-and-running-1 for the reports' bound.

### F12: A refused click shows "this page has stopped updating" here, but a note above the control with the page not marked out of date elsewhere
- Kind: contradiction
- From: whole-product / A refused change is shown beside the control that asked for it
- Here: Every page says how fresh it is and says plainly when it has stopped updating
- From says: "When the server refuses a change a person asked for with a button, form or switch (other than because their sign-in has ended), the page is not marked as out of date. A short note appears directly above the control ... "Not allowed: <the server's reason>""
- Here says: "When a page's exchanges with the server start failing, a warning held at the bottom of the page reads "THIS PAGE HAS STOPPED UPDATING ..." ... refused to this account: "The server refused this to your account (403)[: <server's reason>]. Reload the page; if you were signed out, sign in again."; any other error: "The server answered <status>. Reload the page to try again.""
- Settled by: ALL-056 (kind situation, weaker): "Refusals read "this page has stopped updating"" was the fault; "Every refusal or failure shows its real reason to the person it affects"
- Fix: dashboard-2 should say the stopped-updating warning comes only from the page's own refreshes failing, and that a refused click gets the note above its control as whole-product describes.
