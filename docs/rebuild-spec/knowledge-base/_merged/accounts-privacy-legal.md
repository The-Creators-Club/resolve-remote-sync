# People, sign-in, privacy and the licence

## Who may sign in

### ACC-001: Accounts outside the editing team could sign in and browse everything.
- What was going on: Sign-in checked the NAS password, or the identity provider, but not whether the account belonged to the studio, so bookkeeper, guest or directory accounts got in.
- What the product must do: The admin decides which accounts may open the product, and every sign-in route, single sign-on included, refuses any account outside that set.
- Kind: 3
- State: still open
- From: L11-022, H04-015

### ACC-002: An outside sign-in could take over another person's account by name.
- What was going on: Accounts from an outside sign-in service were matched by a username the person could edit there, so a stranger could become an existing editor.
- What the product must do: An outside sign-in maps to an account only through an identifier the person cannot change at the sign-in service, never by name.
- Kind: 3
- State: outcome not found
- From: H08-037

### ACC-003: On a single-sign-on site, a NAS password still let someone in.
- What was going on: One sign-in route accepted a NAS password where the site requires its identity provider, its second factor and its allowed groups.
- What the product must do: Where single sign-on is required, every way in refuses a password and goes through the identity provider.
- Kind: 3
- State: fixed, never shipped
- From: L11-019, H07-123

### ACC-004: A name the sign-in accepted quietly failed in some sections.
- What was going on: Names with spaces, accents or over 64 characters became sessions, but ticks, computer joins and music import refused them while naming the wrong cause.
- What the product must do: Any name accepted at sign-in works the same in every section; a name the product cannot use is refused at sign-in, saying the shape required.
- Kind: 3
- From: L07-043, L09-021

### ACC-005: A fresh install had no way to create its first admin in a browser.
- What was going on: With local accounts and none created yet, the setup page sent visitors to a sign-in nobody could pass.
- What the product must do: On a fresh install with no accounts the setup page creates the first admin in a browser, and closes once any account exists.
- Kind: 3
- From: H03-029

### ACC-006: Creating an account needed a key that only exists after the account does.
- What was going on: The new-account form demanded the computer key that only the editor's setup wizard generates, after the account exists.
- What the product must do: An account can be created without the key; setup submits it for one-click admin approval, and a missing key is shown with what it blocks.
- Kind: 3
- From: L04-167

### ACC-007: An admin grants a person access with one button.
- What was going on: The owner: "add the button for admins to grant access".
- What the product must do: An admin can grant a person access from a single button on the dashboard, with no other step.
- Kind: 2
- State: outcome not found
- From: P14-011

### ACC-008: The editor page refuses anyone not signed in, even on the private network.
- What was going on: Other editors' computers share the studio's private network, so the owner ruled the page must refuse anyone without the key from the start.
- What the product must do: The editor page answers nothing to a device that has not signed in, even on the studio's private network.
- Kind: 2
- From: D06-026

### ACC-009: One online sign-in every 100 days, everything else works offline.
- What was going on: The owner wants one online sign-in every 100 days, warned about while online as it nears the end, with all other work possible offline.
- What the product must do: Sign-ins last 100 days, show when they end, warn within 14 days, renew in place, and an expiry never deletes anything saved on the device.
- Kind: 2
- From: C04-032

## How a computer proves who it belongs to

### ACC-010: A computer's sign-in never expires on a timer.
- What was going on: A computer's sign-in lapsed at 30 days overnight, stopping reports and transfers for two days; the owner: "get rid of expiring login", "not needed".
- What the product must do: A computer's sign-in ends only when an admin revokes it or the person's access is removed; browser sessions may still expire.
- Kind: 2
- From: C03-003, L03-034

### ACC-011: One credential shared by every computer could not be revoked for one.
- What was going on: Every computer used one shared secret, so a leaked or stolen copy opened the whole fleet and cutting off one machine cut off all.
- What the product must do: Each computer holds its own credential bound to one person, revocable alone; a site-wide shared credential is off unless the admin turns it on.
- Kind: 3
- State: fixed, never shipped
- From: L11-020, G01-043, M02-094

### ACC-012: Per-person credentials silently switched features off.
- What was going on: Sign-in still handed out a retired shared credential while music, b-roll and YouTube accepted only it, so per-person credentials broke them silently.
- What the product must do: Every part of the product accepts exactly the credentials the main sign-in accepts, through one check, and a retired credential is never issued or accepted.
- Kind: 3
- From: L01-049, H03-021

### ACC-013: A computer's credential for one editor could act as another editor.
- What was going on: Music accepted whatever identity a computer stated beside a credential tied to a different editor, so it could claim and fail another editor's batches.
- What the product must do: In every feature a credential tied to one person acts only as that person; a mismatched stated identity is refused.
- Kind: 3
- From: L06-074, H05-098

### ACC-014: Two computers with the same name keep signing each other out.
- What was going on: One person's computers can share a hostname, such as two identical Macs, so a credential keyed on the hostname replaced the other's.
- What the product must do: A computer's identity never depends on its hostname; two same-named computers keep separate, working credentials.
- Kind: 3
- State: still open
- From: L11-021

### ACC-015: Changing the server's secret signed every computer out.
- What was going on: Computer sign-ins rested on one server secret; during a change only reports accepted the old one, and a lost secret refused every computer, which looked like machines switched off.
- What the product must do: A secret change keeps every existing sign-in working on every request in every part, refused computers are named with the fix, and an unsaved secret stops startup.
- Kind: 3
- From: L03-087, H04-012, H06-057, H07-041, L02-063

### ACC-016: Revoking a credential never said which computers would stop.
- What was going on: One credential can be used by several of an editor's computers, and revoking it answered only "ok".
- What the product must do: The credential list shows which computers use each one, and revoking names them and says they will stop reporting.
- Kind: 3
- From: L04-149

### ACC-017: A browse-only account could sign a computer in to the fleet.
- What was going on: With local accounts only, the membership check was skipped, so an account made for browsing b-roll could get computer credentials.
- What the product must do: Only an active, unsuspended account with an editing role can sign a computer in; other accounts are refused.
- Kind: 3
- From: L04-165

## Suspending, disabling and removing a person

### ACC-018: Disabling or deleting a person left their browsers and computers working.
- What was going on: Disabling changed one flag: open sessions kept working for days and the person's computers kept reporting, syncing and holding shares under credentials nobody could revoke.
- What the product must do: Disabling, deleting or suspending a person ends their sessions, shares and every computer's access at the next request, all or nothing, and the confirm states this.
- Kind: 3
- State: fixed, never shipped
- From: H04-010, H03-022, C02-071, L04-162, H07-040, L01-026

### ACC-019: A deleted person came back when their computer reported.
- What was going on: Deleting a person erased the only record saying they were barred, so their computer's next report or registration re-created them.
- What the product must do: No report or registration ever re-creates a deleted person.
- Kind: 3
- State: fixed, never shipped
- From: L11-018

### ACC-020: An admin could disable the last admin and lock everyone out.
- What was going on: Delete refused removing yourself or the last admin, but disable had no such guard, leaving no account able to administer.
- What the product must do: Disabling or deleting your own account, or the last enabled admin, is refused with a message.
- Kind: 3
- From: H03-030

### ACC-021: The only way to stop a person was to delete them.
- What was going on: Where accounts live on the NAS, the only stop control deleted the account, every computer and its sync plan.
- What the product must do: Suspend stops a person's computers and unshares their folders while keeping their plan; resume restores exactly that, and the suspended state shows everywhere.
- Kind: 3
- From: L04-163

### ACC-022: A suspended freelancer's laptop kept working everywhere except one check.
- What was going on: Suspension was checked only on the status report, so the laptop still read plans, took updates, claimed jobs, pushed b-roll, music and downloads, and wrote into shared storage.
- What the product must do: A suspended person is refused at every door that reads or writes, by one shared notion of suspended, while an admin can still read their plan.
- Kind: 3
- From: L06-029, H05-061, L08-006, L07-026

### ACC-023: A briefly busy server undid an admin's suspensions and archives.
- What was going on: A read that failed was answered as "nobody suspended, nothing archived", so a sharing pass re-shared every suspended or archived folder.
- What the product must do: A failed read is never taken as an empty answer; a sharing pass that cannot read suspensions or archives changes nothing and lets no suspended person through.
- Kind: 3
- From: L06-042

### ACC-024: A new account reusing a deleted person's name inherited their access.
- What was going on: Project grants and records were kept by sign-in name after deletion, so a new person with that name picked them up.
- What the product must do: A new account with a deleted person's name starts with none of their projects or rights, and keeps rights given to it directly.
- Kind: 3
- State: fixed, never shipped
- From: L11-028

### ACC-025: Deleting a person or forgetting a computer left their traces behind.
- What was going on: Erasing history meant hand-editing live records; a deleted person's name stayed in logs, alerts and records; a forgotten computer's diagnostics stayed stored.
- What the product must do: Erase removes past records; deleting a person replaces their and their computers' names everywhere with a stable anonymous stand-in; forgetting a computer removes everything about it.
- Kind: 2
- From: L10-057, H07-109

## Passwords, sessions and failed sign-ins

### ACC-026: Every person has one page for themselves, their computers and settings.
- What was going on: The owner asked for a page where any user, admin or not, sees themselves and their computers, sets their name, password and every setting open to them.
- What the product must do: Every signed-in person can change their own name, password and personal settings and see their computers from one page; the name is a label, never an identity.
- Kind: 2
- From: P12-030

### ACC-027: A password reset left the account's other browsers signed in.
- What was going on: Changing or resetting a password kept every existing session alive.
- What the product must do: A password change or admin reset signs out every other session of that account, keeping only the actor's own, and nothing typed is logged or echoed.
- Kind: 3
- From: C04-050, H06-058, H07-108

### ACC-028: A one-time password vanished in a panel that refreshed itself.
- What was going on: A new password and computer credential were shown in panels re-fetched every 30 to 60 seconds, styled as an error with a warning triangle.
- What the product must do: A one-time secret is shown once, outside any auto-refreshing area, styled as a result not an error, with a copy button.
- Kind: 3
- From: L04-056

### ACC-029: Five wrong passwords from anyone locked the whole studio out.
- What was going on: Behind the NAS's own published front server every request arrived from one internal address, so the per-address failure limit was shared by every editor and computer.
- What the product must do: One person's failed sign-ins never lock out other people, and the sessions page shows each person's real address.
- Kind: 3
- From: H04-013

### ACC-030: One valid sign-in reset the guessing limit for every name from that address.
- What was going on: A successful sign-in cleared the per-address failure count, so someone with one account could keep guessing others' passwords.
- What the product must do: A successful sign-in clears only that account's failure count; the per-address count expires on its own time.
- Kind: 3
- From: H03-023

### ACC-031: A locked-out editor could not tell how long to wait, and the wait broke.
- What was going on: Lockouts of 1 to 60 minutes went unsaid, retrying extended them, and after about 1,024 failures the doubling wait overflowed into server errors.
- What the product must do: A lockout always answers with a wait capped at one hour, stated in whole minutes, identical for unknown and real names.
- Kind: 3
- From: L07-040, L04-146

### ACC-032: The offline page was stored on devices with the user's identity.
- What was going on: The cached offline fallback page was drawn with the signed-in user's name, admin menu and form protection value, then stored on the device.
- What the product must do: Any page stored for offline use carries no user identity, admin control or security value.
- Kind: 3
- From: L03-094

## What each person may see and reach

### ACC-033: A browser sends the origin "null" from contexts that are not this site.
- What was going on: A request with origin "null" comes from a sandboxed or opaque context, yet it was treated like a request with no origin and allowed.
- What the product must do: A request whose origin is "null" is treated as coming from another site.
- Kind: 1a
- From: H05-067

### ACC-034: The leftmost forwarded-for address is whatever the client wrote.
- What was going on: Behind a trusted front server the client's address was read from the left end of the forwarded list, which the client controls.
- What the product must do: A client's address is taken only from entries the studio's own front server added.
- Kind: 1a
- From: H06-076

### ACC-035: Any signed-in editor could read internal documents through the help pages.
- What was going on: Help served the whole internal document tree, including defect records, secrets notes and pages naming people, machines and NAS addresses, to every editor at every customer.
- What the product must do: Only guides written for customers and legal documents ship; help lists and opens only what the reader's role may see.
- Kind: 3
- From: L06-056, H05-001, C03-068, M01-078

### ACC-036: An editor could see other editors' computers and their missing files.
- What was going on: Fleet views answered everything to any session, and refusing another's batch as "forbidden" confirmed it existed.
- What the product must do: An editor sees only their own computers in detail and others as counts; another person's computer or batch answers exactly as one that does not exist.
- Kind: 3
- From: G01-047, C02-019

### ACC-037: The open health check exposed project names.
- What was going on: The health address answers without sign-in, and its full answer carried project names, labels and error text.
- What the product must do: Anything answered without sign-in reveals only whether the server is up and its version.
- Kind: 3
- From: G01-038

### ACC-038: The public client page also served the internal app's code to anyone.
- What was going on: The internet-facing client preview page shared a file folder with the internal pages, so anyone could download the internal app and its request map.
- What the product must do: The internet-facing client page serves only the files its viewer needs and refuses any internal page or script.
- Kind: 3
- From: H03-043
- Move to: broll

### ACC-039: Any website in an editor's browser could drive programs on that computer.
- What was going on: The local helper and the editor's local server answered any web page or rebinding host name, accepting paths with ".." or Mac volume paths.
- What the product must do: Anything listening on an editor's computer answers only the product's own pages, refuses other sites and paths outside its folders, and logs each refusal.
- Kind: 3
- From: M01-064, D05-087, L01-025

### ACC-040: A blocked address was reached by spelling it with a doubled slash.
- What was going on: Blocks matched the address as typed, while the server collapsed "//" and dot segments and ran the blocked action; add-on pages each decided access differently.
- What the product must do: Every block applies to the address as the server will act on it, and every page behind the sign-in refuses on any doubt.
- Kind: 3
- From: H06-075, H07-111

### ACC-041: Upload routes were open whenever no protection was set.
- What was going on: A missing upload secret meant "open", and a search section run without the dashboard's sign-in had no protection at all.
- What the product must do: Every writing route refuses when its protection is not configured, and each upload is capped in files and bytes.
- Kind: 3
- From: G01-046

### ACC-042: A configuration value made a section trust a forged identity.
- What was going on: One value made a section believe an identity header and skip its own check, behind any front server that did not strip that header.
- What the product must do: An identity passed between parts is trusted only when the product itself added it inside the same server, never because of a configuration value.
- Kind: 3
- From: L07-067

### ACC-043: Pages sent no browser security headers and some admin actions skipped origin checks.
- What was going on: No page, the public client viewer included, sent a content policy; release actions skipped request-forgery checks; admins had no second factor.
- What the product must do: Every page sends browser security headers, every changing action checks its origin, and admins can use a second factor.
- Kind: 3
- State: still open
- From: H07-136

### ACC-044: Any editor could reach and delete any project on the NAS.
- What was going on: Every project folder was shared with every editor, and "creating" a project that already existed handed the caller access to it.
- What the product must do: Each project folder is limited to its members, admins manage members from the project, and re-creating an existing project grants nothing.
- Kind: 3
- State: fixed, never shipped
- From: L11-027

### ACC-045: The server held NAS-admin power by default.
- What was going on: The server kept a root-equivalent NAS credential, the dashboard admin was the NAS admin, NAS identities went unverified, and any editor could delete any project.
- What the product must do: By default the server holds no NAS-admin-equivalent credential, verifies the NAS it talks to, and editors delete only projects granted to them.
- Kind: 3
- State: fixed, never shipped
- From: H07-122

## What the product records about a person

### ACC-046: Customer data never reaches the vendor in normal running.
- What was going on: The owner ruled no vendor telemetry: data stays on site, support data is shared case by case, never read by AI tools, and deleted 30 days after its ticket closes.
- What the product must do: Nothing leaves the site for the vendor unless an admin sends a support bundle; no AI tool reads it; it is deleted 30 days after its ticket closes.
- Kind: 2
- From: M02-087, H08-008, L11-056

### ACC-047: Each category of reporting can be switched off.
- What was going on: The app reported the open Resolve project, file lists, the project tree, bins and idle time with no off switch, though the licence terms promise one.
- What the product must do: Each category can be withheld per computer or per site; sync still runs, and the server drops withheld fields on arrival and deletes what it held.
- Kind: 2
- From: L01-021, C04-049, L10-055

### ACC-048: Switching reporting off must withhold the report, not the work.
- What was going on: The checks behind withheld categories also recover Resolve and count conflicts, identifiers leaked project names, and older apps ignore the switches.
- What the product must do: Withheld categories still run, read as withheld rather than empty or zero, and the server strips them on arrival from any app version.
- Kind: 3
- From: G01-048

### ACC-049: A person can download everything the dashboard holds about them.
- What was going on: The legal terms promise a copy of a person's data on request, and there was no way to produce one.
- What the product must do: One file covers every store, secrets excluded, lists what is left out, goes only to that person or an admin, and is rate-limited and logged.
- Kind: 2
- From: L10-056

### ACC-050: Transcripts kept for the assistant had no retention limit.
- What was going on: Transcripts stayed in the assistant's stores indefinitely, and the published list of what each computer reports no longer matched what it sent.
- What the product must do: Every stored transcript and assistant record is deleted after a site-set period, and the published report list matches what is actually sent.
- Kind: 3
- State: outcome not found
- From: H08-045

### ACC-051: The privacy policy said "no phone-home" while the server checked for releases.
- What was going on: Customer servers asked the vendor for new releases, but the policy denied any outbound contact or third parties.
- What the product must do: The privacy policy lists every automatic outbound request and outside service, what it carries, and how to turn it off.
- Kind: 3
- State: fixed, never shipped
- From: L11-057

### ACC-052: Only names are taken from the planning sheet, never contact details.
- What was going on: The interviewee roster comes from a sheet that also holds phone numbers and addresses.
- What the product must do: The product copies only the episode and names from the planning sheet and never stores contact details.
- Kind: 3
- From: C06-100

## The licence a person accepts

### ACC-053: Admins see which licence version each computer accepted.
- What was going on: The legal terms rely on knowing each computer's accepted licence version, and nothing showed it.
- What the product must do: Each computer shows "Licence version accepted", "Older licence accepted" or "Not reported"; "not accepted" is never guessed from silence.
- Kind: 2
- From: L10-059

### ACC-054: A licence accepted for the owner's own team records who did it.
- What was going on: The owner allowed recording acceptance remotely for his own team, never for customers' editors, if the record says truthfully who accepted for whom.
- What the product must do: A remotely recorded acceptance names who accepted, on whose behalf, and by what method.
- Kind: 2
- From: M01-076

### ACC-055: A new licence version stopped sync until each editor clicked accept.
- What was going on: After an unattended update, computers waited for acceptance and nothing uploaded overnight.
- What the product must do: A licence change asks each editor at once without stopping their sync, and a computer still waiting shows that as its state.
- Kind: 3
- State: still open
- From: P12-053, H07-130

### ACC-056: A stray keypress must never accept the licence.
- What was going on: A dialog where Return presses the default button could record an agreement the person never read.
- What the product must do: The licence is accepted only by a deliberate click on Accept; no key press accepts it.
- Kind: 3
- From: C02-021

### ACC-057: A build without the licence text ticked the licence step done.
- What was going on: Setup showed an empty box and marked the step done, then treated "no licence" as settled, so a licence arriving in a later update was never accepted.
- What the product must do: Missing licence text records nothing and shows a warning; setup re-checks every time, and once the text exists it is incomplete until an admin accepts.
- Kind: 3
- From: L05-012, L07-039

### ACC-058: The licence dialog showed raw draft text with internal notes.
- What was going on: The licence was displayed as raw marked-up source, including an internal "draft for counsel" comment and long dashes.
- What the product must do: Legal text shown to people is properly rendered, holds no internal notes, and follows the product's wording rules.
- Kind: 3
- From: H06-092

### ACC-059: A legal document stays out of the product until counsel clears it.
- What was going on: The owner ruled that draft legal documents (beta agreement, data processing terms, support data procedure) are not published until counsel clears each.
- What the product must do: A legal document not yet cleared by counsel is never shown, linked or offered for acceptance inside the product.
- Kind: 2
- From: H08-009

## Third-party licences and what customers receive

### ACC-060: Copyleft components reached customers in breach of their licences.
- What was going on: A lesser-GPL library was sealed into the app and a GPL encoder was pushed onto the NAS with no source offer.
- What the product must do: The build fails on any disallowed licence, and any copyleft tool a customer needs is fetched by their own machine from its publisher.
- Kind: 2
- From: L01-018

### ACC-061: A copyleft part of an off-by-default feature reached every customer.
- What was going on: A GPL YouTube helper sat in every server install and a codec reached every editor machine, though the feature is off unless enabled.
- What the product must do: Copyleft software serving an optional feature reaches a customer's machines only after that customer turns the feature on.
- Kind: 3
- From: C02-009

### ACC-062: A shipped copyleft library had no licence notice.
- What was going on: Notices were generated from developer setups, not from what customers receive, an allow-list claimed the notice existed, and no release step checked it.
- What the product must do: Notices list exactly the components and versions customers receive, are checked every release, a release missing one fails, and an unknown licence is never assumed permissive.
- Kind: 3
- From: H06-079, L09-043

### ACC-063: Every shipped program carries the licence texts it owes.
- What was going on: Programs handed to editors and customers bundled other people's code without including those licences' texts.
- What the product must do: Every shipped program carries its owed licence texts, viewable from its help, the setup wizard's last page and the dashboard's help.
- Kind: 2
- From: L10-060

### ACC-064: No customer receives the product's source code.
- What was going on: The owner decided no customer gets source; a customer copy of the code could not be built and leaked internal documents.
- What the product must do: Customers install from a package they are given; nothing in the customer path hands out source code or internal documents.
- Kind: 2
- From: L11-054

### ACC-065: One flat price per site, enforced by contract.
- What was going on: The owner ruled a flat price per site whatever the computer count, with no seat or expiry checks, and downloads no longer public.
- What the product must do: No seat count or expiry check ever stops a site working, and downloading the product requires a credential issued to that site.
- Kind: 2
- From: H08-001

### ACC-066: Customer builds use the site's own paid assistant account, never a consumer subscription.
- What was going on: Consumer subscription terms do not allow use in a sold product; the owner keeps his subscription sign-in for the studio only.
- What the product must do: In a customer build the subscription sign-in is absent and cannot be turned on; the site's own business key works for every assistant feature.
- Kind: 2
- From: H08-002, H07-126

## How secrets and keys are kept

### ACC-067: On Windows a file-mode change does not make a file private.
- What was going on: A mode change only toggles read-only; inherited profile access lists decide readers, and changing them in two steps can lock out the owner.
- What the product must do: Credential files are owner-only on every platform, set through the platform's own access controls in a single step.
- Kind: 1a
- From: G01-044

### ACC-068: On Windows any process can read another program's command line.
- What was going on: Credentials passed as command-line arguments were readable by any non-admin process, and one was printed in an example shipped to editors.
- What the product must do: No secret is passed on a command line or printed in shipped examples; secrets travel by standard input, environment or protected file.
- Kind: 1a
- From: H04-020

### ACC-069: A stored sign-in was readable by others while being written.
- What was going on: A saved YouTube sign-in and its browser profile were written with default permissions and tightened later, or never, leaving a live Google session readable.
- What the product must do: A stored sign-in is private from creation, before any byte is written, on Windows and macOS, and removed when no longer needed.
- Kind: 3
- From: L08-073, H06-080

### ACC-070: Passwords appeared in logs, notifications and crash reports.
- What was going on: A timed-out drive connection printed its command with the password, and redaction missed secrets written as NAME=value, NAME: value or quoted.
- What the product must do: No password or secret, in any common spelling, appears in a log, notification, crash report, diagnostics copy or error message.
- Kind: 3
- From: H01-009, H06-078

### ACC-071: A client preview link's secret was written into error records and mailed.
- What was going on: Server errors were recorded under the full web address, so a failing client link stored its secret, showed it on the home page, mailed and backed it up.
- What the product must do: Error records, alerts and logs never hold a secret carried in a web address, and are grouped by page kind so they cannot grow without end.
- Kind: 3
- From: H05-063, L06-046

### ACC-072: A helper reading outside text was handed every server credential.
- What was going on: An assistant run over untrusted YouTube titles and descriptions inherited every secret in the server's environment.
- What the product must do: Any helper program run over outside text receives only an allow-listed set of settings, never a fleet, storage or signing credential.
- Kind: 3
- From: L02-032

### ACC-073: A redirect could resend a credential to another address.
- What was going on: Calls carrying credentials followed redirects, and the usual client strips only the standard authorization header, so a 307 resent the secret elsewhere.
- What the product must do: A credentialed call never follows a redirect and its refusal names the target; only an uncredentialed, signature-verified download may follow https redirects.
- Kind: 3
- From: L03-090, G01-045

### ACC-074: The app would send its credential over plain http to a public address.
- What was going on: Nothing checked whether a plain-http dashboard address was public, a raw IPv6 address read as a local name, and a wrong refusal silences a studio.
- What the product must do: Plain http is refused before sending only when every resolved address is public, passes with a note otherwise, and is re-judged within 30 seconds of a network change.
- Kind: 3
- From: G01-049, L10-058

### ACC-075: Connections carrying footage or passwords did not check who answered.
- What was going on: File transfers accepted any NAS host key, server calls to the NAS skipped certificate checks, and alert mail sent its password unverified.
- What the product must do: Every connection carrying footage or a credential verifies the far end's identity, and a changed identity is refused.
- Kind: 3
- State: still open
- From: H04-014

### ACC-076: The mail password could be sent unencrypted.
- What was going on: With encryption switched off for alert mail, the server still signed in to the mail server, sending the stored password in clear.
- What the product must do: No password is sent over an unencrypted connection; such a mail setting is refused at save and at send.
- Kind: 3
- State: outcome not found
- From: H05-097

## Sealed

### ACC-S01: A single-file program cannot carry a lesser-GPL library.
- What was going on: A single-file build unpacks libraries to a new temporary folder each launch, so recipients cannot replace a lesser-GPL library as that licence requires.
- What the product must do: Lesser-GPL libraries ship as separate replaceable files with their full licence text and how to replace them, never inside a single-file build.
- Kind: 1b
- Tool: PyInstaller one-file builds with LGPL libraries (pystray, psycopg2)
- State: fixed, never shipped
- From: L03-039, L11-053

## Removed
