# Accounts, privacy and the legal paperwork: what real use taught

70 lessons. Each is one rule the product can be tested against: what a person saw (the heading), why it happened, and what the product must do. Kinds: *given* is a fact about something the studio has whatever is built; *ruling* is the owner's decision; *situation* is something the product must survive.

## Who may sign in

### ACC-007: An admin grants a person access with one button.
- Why: The owner: "add the button for admins to grant access".
- Must: An admin can grant a person access from a single button on the dashboard, with no other step.
- Kind: ruling

### ACC-008: The editor page refuses anyone not signed in, even on the private network.
- Why: Other editors' computers share the studio's private network, so the owner ruled the page must refuse anyone without the key from the start.
- Must: The editor page answers nothing to a device that has not signed in, even on the studio's private network.
- Kind: ruling

### ACC-009: One online sign-in every 100 days, everything else works offline.
- Why: The owner wants one online sign-in every 100 days, warned about while online as it nears the end, with all other work possible offline.
- Must: Sign-ins last 100 days, show when they end, warn within 14 days, renew in place, and an expiry never deletes anything saved on the device.
- Kind: ruling

### ACC-001: Accounts outside the editing team could sign in and browse everything.
- Why: Sign-in checked the NAS password, or the identity provider, but not whether the account belonged to the studio, so bookkeeper, guest or directory accounts got in.
- Must: The admin decides which accounts may open the product, and every sign-in route, single sign-on included, refuses any account outside that set.
- Kind: situation

### ACC-002: An outside sign-in could take over another person's account by name.
- Why: Accounts from an outside sign-in service were matched by a username the person could edit there, so a stranger could become an existing editor.
- Must: An outside sign-in maps to an account only through an identifier the person cannot change at the sign-in service, never by name.
- Kind: situation

### ACC-004: A name the sign-in accepted quietly failed in some sections.
- Why: Names with spaces, accents or over 64 characters became sessions, but ticks, computer joins and music import refused them while naming the wrong cause.
- Must: Any name accepted at sign-in works the same in every section; a name the product cannot use is refused at sign-in, saying the shape required.
- Kind: situation

### ACC-005: A fresh install had no way to create its first admin in a browser.
- Why: With local accounts and none created yet, the setup page sent visitors to a sign-in nobody could pass.
- Must: On a fresh install with no accounts the setup page creates the first admin in a browser, and closes once any account exists.
- Kind: situation

## How a computer proves who it belongs to

### ACC-010: A computer's sign-in never expires on a timer.
- Why: A computer's sign-in lapsed at 30 days overnight, stopping reports and transfers for two days; the owner: "get rid of expiring login", "not needed".
- Must: A computer's sign-in ends only when an admin revokes it or the person's access is removed; browser sessions may still expire.
- Kind: ruling

### ACC-011: One credential shared by every computer could not be revoked for one.
- Why: Every computer used one shared secret, so a leaked or stolen copy opened the whole fleet and cutting off one machine cut off all.
- Must: Each computer holds its own credential bound to one person, revocable alone; a site-wide shared credential is off unless the admin turns it on.
- Kind: situation

### ACC-012: Per-person credentials silently switched features off.
- Why: Sign-in still handed out a retired shared credential while music, b-roll and YouTube accepted only it, so per-person credentials broke them silently.
- Must: Every part of the product accepts exactly the credentials the main sign-in accepts, through one check, and a retired credential is never issued or accepted.
- Kind: situation

### ACC-013: A computer's credential for one editor could act as another editor.
- Why: Music accepted whatever identity a computer stated beside a credential tied to a different editor, so it could claim and fail another editor's batches.
- Must: In every feature a credential tied to one person acts only as that person; a mismatched stated identity is refused.
- Kind: situation

### ACC-014: Two computers with the same name keep signing each other out.
- Why: One person's computers can share a hostname, such as two identical Macs, so a credential keyed on the hostname replaced the other's.
- Must: A computer's identity never depends on its hostname; two same-named computers keep separate, working credentials.
- Kind: situation

### ACC-015: Changing the server's secret signed every computer out.
- Why: Computer sign-ins rested on one server secret; during a change only reports accepted the old one, and a lost secret refused every computer, which looked like machines switched off.
- Must: A secret change keeps every existing sign-in working on every request in every part, refused computers are named with the fix, and an unsaved secret stops startup.
- Kind: situation

### ACC-016: Revoking a credential never said which computers would stop.
- Why: One credential can be used by several of an editor's computers, and revoking it answered only "ok".
- Must: The credential list shows which computers use each one, and revoking names them and says they will stop reporting.
- Kind: situation

### ACC-017: A browse-only account could sign a computer in to the fleet.
- Why: With local accounts only, the membership check was skipped, so an account made for browsing b-roll could get computer credentials.
- Must: Only an active, unsuspended account with an editing role can sign a computer in; other accounts are refused.
- Kind: situation

## Suspending, disabling and removing a person

### ACC-025: Deleting a person or forgetting a computer left their traces behind.
- Why: Erasing history meant hand-editing live records; a deleted person's name stayed in logs, alerts and records; a forgotten computer's diagnostics stayed stored.
- Must: Erase removes past records; deleting a person replaces their and their computers' names everywhere with a stable anonymous stand-in; forgetting a computer removes everything about it.
- Kind: ruling

### ACC-018: Disabling or deleting a person left their browsers and computers working.
- Why: Disabling changed one flag: open sessions kept working for days and the person's computers kept reporting, syncing and holding shares under credentials nobody could revoke.
- Must: Disabling, deleting or suspending a person ends their sessions, shares and every computer's access at the next request, all or nothing, and the confirm states this.
- Kind: situation

### ACC-019: A deleted person came back when their computer reported.
- Why: Deleting a person erased the only record saying they were barred, so their computer's next report or registration re-created them.
- Must: No report or registration ever re-creates a deleted person.
- Kind: situation

### ACC-020: An admin could disable the last admin and lock everyone out.
- Why: Delete refused removing yourself or the last admin, but disable had no such guard, leaving no account able to administer.
- Must: Disabling or deleting your own account, or the last enabled admin, is refused with a message.
- Kind: situation

### ACC-021: The only way to stop a person was to delete them.
- Why: Where accounts live on the NAS, the only stop control deleted the account, every computer and its sync plan.
- Must: Suspend stops a person's computers and unshares their folders while keeping their plan; resume restores exactly that, and the suspended state shows everywhere.
- Kind: situation

### ACC-022: A suspended freelancer's laptop kept working everywhere except one check.
- Why: Suspension was checked only on the status report, so the laptop still read plans, took updates, claimed jobs, pushed b-roll, music and downloads, and wrote into shared storage.
- Must: A suspended person is refused at every door that reads or writes, by one shared notion of suspended, while an admin can still read their plan.
- Kind: situation

### ACC-023: A briefly busy server undid an admin's suspensions and archives.
- Why: A read that failed was answered as "nobody suspended, nothing archived", so a sharing pass re-shared every suspended or archived folder.
- Must: A failed read is never taken as an empty answer; a sharing pass that cannot read suspensions or archives changes nothing and lets no suspended person through.
- Kind: situation

### ACC-024: A new account reusing a deleted person's name inherited their access.
- Why: Project grants and records were kept by sign-in name after deletion, so a new person with that name picked them up.
- Must: A new account with a deleted person's name starts with none of their projects or rights, and keeps rights given to it directly.
- Kind: situation

## Passwords, sessions and failed sign-ins

### ACC-026: Every person has one page for themselves, their computers and settings.
- Why: The owner asked for a page where any user, admin or not, sees themselves and their computers, sets their name, password and every setting open to them.
- Must: Every signed-in person can change their own name, password and personal settings and see their computers from one page; the name is a label, never an identity.
- Kind: ruling

### ACC-027: A password reset left the account's other browsers signed in.
- Why: Changing or resetting a password kept every existing session alive.
- Must: A password change or admin reset signs out every other session of that account, keeping only the actor's own, and nothing typed is logged or echoed.
- Kind: situation

### ACC-028: A one-time password vanished in a panel that refreshed itself.
- Why: A new password and computer credential were shown in panels re-fetched every 30 to 60 seconds, styled as an error with a warning triangle.
- Must: A one-time secret is shown once, outside any auto-refreshing area, styled as a result not an error, with a copy button.
- Kind: situation

### ACC-029: Five wrong passwords from anyone locked the whole studio out.
- Why: Behind the NAS's own published front server every request arrived from one internal address, so the per-address failure limit was shared by every editor and computer.
- Must: One person's failed sign-ins never lock out other people, and the sessions page shows each person's real address.
- Kind: situation

### ACC-030: One valid sign-in reset the guessing limit for every name from that address.
- Why: A successful sign-in cleared the per-address failure count, so someone with one account could keep guessing others' passwords.
- Must: A successful sign-in clears only that account's failure count; the per-address count expires on its own time.
- Kind: situation

### ACC-031: A locked-out editor could not tell how long to wait, and the wait broke.
- Why: Lockouts of 1 to 60 minutes went unsaid, retrying extended them, and after about 1,024 failures the doubling wait overflowed into server errors.
- Must: A lockout always answers with a wait capped at one hour, stated in whole minutes, identical for unknown and real names.
- Kind: situation

See also, filed under another capability:

- DSH-137 (The dashboard): The installed dashboard could show a stored copy as live, with the last user's name.

## What each person may see and reach

### ACC-034: The leftmost forwarded-for address is whatever the client wrote.
- Why: Behind a trusted front server the client's address was read from the left end of the forwarded list, which the client controls.
- Must: A client's address is taken only from entries the studio's own front server added.
- Kind: given

### ACC-035: Any signed-in editor could read internal documents through the help pages.
- Why: Help served the whole internal document tree, including defect records, secrets notes and pages naming people, machines and NAS addresses, to every editor at every customer.
- Must: Only guides written for customers and legal documents ship; help lists and opens only what the reader's role may see.
- Kind: situation

### ACC-036: An editor could see other editors' computers and their missing files.
- Why: Fleet views answered everything to any session, and refusing another's batch as "forbidden" confirmed it existed.
- Must: An editor sees only their own computers in detail and others as counts; another person's computer or batch answers exactly as one that does not exist.
- Kind: situation

### ACC-037: The open health check exposed project names.
- Why: The health address answers without sign-in, and its full answer carried project names, labels and error text.
- Must: Anything answered without sign-in reveals only whether the server is up and its version.
- Kind: situation

### ACC-039: Any website in an editor's browser could drive programs on that computer.
- Why: The local helper and the editor's local server answered any web page or rebinding host name, accepting paths with ".." or Mac volume paths.
- Must: Anything listening on an editor's computer answers only the product's own pages, refuses other sites and paths outside its folders, and logs each refusal.
- Kind: situation

### ACC-040: A blocked address was reached by spelling it with a doubled slash.
- Why: Blocks matched the address as typed, while the server collapsed "//" and dot segments and ran the blocked action; add-on pages each decided access differently.
- Must: Every block applies to the address as the server will act on it, and every page behind the sign-in refuses on any doubt.
- Kind: situation

### ACC-041: Upload routes were open whenever no protection was set.
- Why: A missing upload secret meant "open", and a search section run without the dashboard's sign-in had no protection at all.
- Must: Every writing route refuses when its protection is not configured, and each upload is capped in files and bytes.
- Kind: situation

### ACC-042: A configuration value made a section trust a forged identity.
- Why: One value made a section believe an identity header and skip its own check, behind any front server that did not strip that header.
- Must: An identity passed between parts is trusted only when the product itself added it inside the same server, never because of a configuration value.
- Kind: situation

### ACC-043: Pages sent no browser security headers and some admin actions skipped origin checks.
- Why: No page, the public client viewer included, sent a content policy; release actions skipped request-forgery checks; admins had no second factor.
- Must: Every page sends browser security headers, every changing action checks its origin, and admins can use a second factor.
- Kind: situation

### ACC-044: Any editor could reach and delete any project on the NAS.
- Why: Every project folder was shared with every editor, and "creating" a project that already existed handed the caller access to it.
- Must: Each project folder is limited to its members, admins manage members from the project, and re-creating an existing project grants nothing.
- Kind: situation

### ACC-045: The server held NAS-admin power by default.
- Why: The server kept a root-equivalent NAS credential, the dashboard admin was the NAS admin, NAS identities went unverified, and any editor could delete any project.
- Must: By default the server holds no NAS-admin-equivalent credential, verifies the NAS it talks to, and editors delete only projects granted to them.
- Kind: situation

See also, filed under another capability:

- DSH-138 (The dashboard): Browsers send "Origin: null" from places that are not this site.
- BRO-133 (The b-roll archive): The public client page exposed the whole internal app's files.

## What the product records about a person

### ACC-046: Customer data never reaches the vendor in normal running.
- Why: The owner ruled no vendor telemetry: data stays on site, support data is shared case by case, never read by AI tools, and deleted 30 days after its ticket closes.
- Must: Nothing leaves the site for the vendor unless an admin sends a support bundle; no AI tool reads it; it is deleted 30 days after its ticket closes.
- Kind: ruling

### ACC-047: Each category of reporting can be switched off.
- Why: The app reported the open Resolve project, file lists, the project tree, bins and idle time with no off switch, though the licence terms promise one.
- Must: Each category can be withheld per computer or per site; sync still runs, and the server drops withheld fields on arrival and deletes what it held.
- Kind: ruling

### ACC-049: A person can download everything the dashboard holds about them.
- Why: The legal terms promise a copy of a person's data on request, and there was no way to produce one.
- Must: One file covers every store, secrets excluded, lists what is left out, goes only to that person or an admin, and is rate-limited and logged.
- Kind: ruling

### ACC-048: Switching reporting off must withhold the report, not the work.
- Why: The checks behind withheld categories also recover Resolve and count conflicts, identifiers leaked project names, and older apps ignore the switches.
- Must: Withheld categories still run, read as withheld rather than empty or zero, and the server strips them on arrival from any app version.
- Kind: situation

### ACC-050: Transcripts kept for the assistant had no retention limit.
- Why: Transcripts stayed in the assistant's stores indefinitely, and the published list of what each computer reports no longer matched what it sent.
- Must: Every stored transcript and assistant record is deleted after a site-set period, and the published report list matches what is actually sent.
- Kind: situation

### ACC-051: The privacy policy said "no phone-home" while the server checked for releases.
- Why: Customer servers asked the vendor for new releases, but the policy denied any outbound contact or third parties.
- Must: The privacy policy lists every automatic outbound request and outside service, what it carries, and how to turn it off.
- Kind: situation

### ACC-052: Only names are taken from the planning sheet, never contact details.
- Why: The interviewee roster comes from a sheet that also holds phone numbers and addresses.
- Must: The product copies only the episode and names from the planning sheet and never stores contact details.
- Kind: situation

## The licence a person accepts

### ACC-053: Admins see which licence version each computer accepted.
- Why: The legal terms rely on knowing each computer's accepted licence version, and nothing showed it.
- Must: Each computer shows "Licence version accepted", "Older licence accepted" or "Not reported"; "not accepted" is never guessed from silence.
- Kind: ruling

### ACC-054: A licence accepted for the owner's own team records who did it.
- Why: The owner allowed recording acceptance remotely for his own team, never for customers' editors, if the record says truthfully who accepted for whom.
- Must: A remotely recorded acceptance names who accepted, on whose behalf, and by what method.
- Kind: ruling

### ACC-059: A legal document stays out of the product until counsel clears it.
- Why: The owner ruled that draft legal documents (beta agreement, data processing terms, support data procedure) are not published until counsel clears each.
- Must: A legal document not yet cleared by counsel is never shown, linked or offered for acceptance inside the product.
- Kind: ruling

### ACC-055: A new licence version stopped sync until each editor clicked accept.
- Why: After an unattended update, computers waited for acceptance and nothing uploaded overnight.
- Must: A licence change asks each editor at once without stopping their sync, and a computer still waiting shows that as its state.
- Kind: situation

### ACC-056: A stray keypress must never accept the licence.
- Why: A dialog where Return presses the default button could record an agreement the person never read.
- Must: The licence is accepted only by a deliberate click on Accept; no key press accepts it.
- Kind: situation

### ACC-057: A build without the licence text ticked the licence step done.
- Why: Setup showed an empty box and marked the step done, then treated "no licence" as settled, so a licence arriving in a later update was never accepted.
- Must: Missing licence text records nothing and shows a warning; setup re-checks every time, and once the text exists it is incomplete until an admin accepts.
- Kind: situation

### ACC-058: The licence dialog showed raw draft text with internal notes.
- Why: The licence was displayed as raw marked-up source, including an internal "draft for counsel" comment and long dashes.
- Must: Legal text shown to people is properly rendered, holds no internal notes, and follows the product's wording rules.
- Kind: situation

## Third-party licences and what customers receive

### ACC-060: Copyleft components reached customers in breach of their licences.
- Why: A lesser-GPL library was sealed into the app and a GPL encoder was pushed onto the NAS with no source offer.
- Must: The build fails on any disallowed licence, and any copyleft tool a customer needs is fetched by their own machine from its publisher.
- Kind: ruling

### ACC-063: Every shipped program carries the licence texts it owes.
- Why: Programs handed to editors and customers bundled other people's code without including those licences' texts.
- Must: Every shipped program carries its owed licence texts, viewable from its help, the setup wizard's last page and the dashboard's help.
- Kind: ruling

### ACC-064: No customer receives the product's source code.
- Why: The owner decided no customer gets source; a customer copy of the code could not be built and leaked internal documents.
- Must: Customers install from a package they are given; nothing in the customer path hands out source code or internal documents.
- Kind: ruling

### ACC-065: One flat price per site, enforced by contract.
- Why: The owner ruled a flat price per site whatever the computer count, with no seat or expiry checks, and downloads no longer public.
- Must: No seat count or expiry check ever stops a site working, and downloading the product requires a credential issued to that site.
- Kind: ruling

### ACC-061: A copyleft part of an off-by-default feature reached every customer.
- Why: A GPL YouTube helper sat in every server install and a codec reached every editor machine, though the feature is off unless enabled.
- Must: Copyleft software serving an optional feature reaches a customer's machines only after that customer turns the feature on.
- Kind: situation

### ACC-062: A shipped copyleft library had no licence notice.
- Why: Notices were generated from developer setups, not from what customers receive, an allow-list claimed the notice existed, and no release step checked it.
- Must: Notices list exactly the components and versions customers receive, are checked every release, a release missing one fails, and an unknown licence is never assumed permissive.
- Kind: situation

See also, filed under another capability:

- ALL-089 (The whole product): Customer builds use only the studio's own paid assistant key.

## How secrets and keys are kept

### ACC-067: On Windows a file-mode change does not make a file private.
- Why: A mode change only toggles read-only; inherited profile access lists decide readers, and changing them in two steps can lock out the owner.
- Must: Credential files are owner-only on every platform, set through the platform's own access controls in a single step.
- Kind: given

### ACC-068: On Windows any process can read another program's command line.
- Why: Credentials passed as command-line arguments were readable by any non-admin process, and one was printed in an example shipped to editors.
- Must: No secret is passed on a command line or printed in shipped examples; secrets travel by standard input, environment or protected file.
- Kind: given

### ACC-069: A stored sign-in was readable by others while being written.
- Why: A saved YouTube sign-in and its browser profile were written with default permissions and tightened later, or never, leaving a live Google session readable.
- Must: A stored sign-in is private from creation, before any byte is written, on Windows and macOS, and removed when no longer needed.
- Kind: situation

### ACC-070: Passwords appeared in logs, notifications and crash reports.
- Why: A timed-out drive connection printed its command with the password, and redaction missed secrets written as NAME=value, NAME: value or quoted.
- Must: No password or secret, in any common spelling, appears in a log, notification, crash report, diagnostics copy or error message.
- Kind: situation

### ACC-071: A client preview link's secret was written into error records and mailed.
- Why: Server errors were recorded under the full web address, so a failing client link stored its secret, showed it on the home page, mailed and backed it up.
- Must: Error records, alerts and logs never hold a secret carried in a web address, and are grouped by page kind so they cannot grow without end.
- Kind: situation

### ACC-072: A helper reading outside text was handed every server credential.
- Why: An assistant run over untrusted YouTube titles and descriptions inherited every secret in the server's environment.
- Must: Any helper program run over outside text receives only an allow-listed set of settings, never a fleet, storage or signing credential.
- Kind: situation

### ACC-073: A redirect could resend a credential to another address.
- Why: Calls carrying credentials followed redirects, and the usual client strips only the standard authorization header, so a 307 resent the secret elsewhere.
- Must: A credentialed call never follows a redirect and its refusal names the target; only an uncredentialed, signature-verified download may follow https redirects.
- Kind: situation

### ACC-074: The app would send its credential over plain http to a public address.
- Why: Nothing checked whether a plain-http dashboard address was public, a raw IPv6 address read as a local name, and a wrong refusal silences a studio.
- Must: Plain http is refused before sending only when every resolved address is public, passes with a note otherwise, and is re-judged within 30 seconds of a network change.
- Kind: situation

### ACC-075: Connections carrying footage or passwords did not check who answered.
- Why: File transfers accepted any NAS host key, server calls to the NAS skipped certificate checks, and alert mail sent its password unverified.
- Must: Every connection carrying footage or a credential verifies the far end's identity, and a changed identity is refused.
- Kind: situation

### ACC-076: The mail password could be sent unencrypted.
- Why: With encryption switched off for alert mail, the server still signed in to the mail server, sending the stored password in clear.
- Must: No password is sent over an unencrypted connection; such a mail setting is refused at save and at send.
- Kind: situation
