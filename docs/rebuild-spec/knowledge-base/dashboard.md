# The dashboard: what real use taught

139 lessons. Each is one rule the product can be tested against: what a person saw (the heading), why it happened, and what the product must do. Kinds: *given* is a fact about something the studio has whatever is built; *ruling* is the owner's decision; *situation* is something the product must survive.

## Overview, menus and finding things

### DSH-001: The home page is an Overview, not the sync page.
- Why: The owner found the old menus confusing and ruled "Sync should not be the homepage any more, there should be an 'overview' page".
- Must: Home shows problems, health, a sync summary, each module's status, the version, and quick links to commonly used settings.
- Kind: ruling

### DSH-002: A Sync menu holds Projects, Transfers and a per-computer view.
- Why: The owner wants Projects and Transfers "in a dropdown menu if you roll over 'sync'", with a per-computer view third.
- Must: Sync opens a menu, on hover with a mouse and on tap on touch, offering Projects, Transfers and a per-computer view, each its own page.
- Kind: ruling

### DSH-003: A Projects page lists every project to open, manage, tick and untick.
- Why: The owner asked for "a new 'projects' page where you can see all the projects, click into them to manage them, tick them, untick them".
- Must: One page lists all projects; opening one offers every action on that project, including ticking and unticking it for sync.
- Kind: ruling

### DSH-004: Settings are grouped by what they do and have their own search.
- Why: The owner: "the old settings menu and the menu layout is somehwat confusing"; he wants "UX cleanliness" and a search covering settings only.
- Must: Settings are grouped by purpose, and a search inside Settings finds and opens any setting by name, returning settings only.
- Kind: ruling

### DSH-005: A search in the menu bar opens any module, setting, project, computer or person.
- Why: The owner asked for "a general search in the menu bar", then added "yes the general search should find projects computers and people".
- Must: Typing a name in the menu-bar search finds and opens any module, setting, project, computer or person.
- Kind: ruling

### DSH-006: Many problems must not swamp the overview.
- Why: The owner: many errors must not "visually ruin" the overview, and "I don't like the issues being these card boxes".
- Must: Problems occupy a fixed-size area that scrolls when full, and every scrollbar in the product has the product's own style.
- Kind: ruling

### DSH-007: An admin can open any person and see what they have and lack.
- Why: The owner asked for a per-person drill-down and "a full overview of all the projects being synced, who has what".
- Must: An admin opening any person sees each project they ticked, per computer: what has synced, what has not, and what is missing.
- Kind: ruling

### DSH-008: The other tools open as pages of the dashboard, with a way back.
- Why: The owner wanted b-roll and music to look like the dashboard, carry its header and a way back, and be listed after the dashboard's own pages.
- Must: Every tool opens with the dashboard's header and navigation, is listed after the dashboard's own sections, and returns to the dashboard in one click.
- Kind: ruling

### DSH-009: The installer link downloads the right build for the visitor's computer.
- Why: The owner asked that clicking the installer link download the Windows or Mac installer matching the computer doing the browsing.
- Must: Clicking the installer link downloads the installer for the visitor's operating system at once, with the other one still offered.
- Kind: ruling

### DSH-010: Builds on offer are listed currently served first, then the vendor's.
- Why: The owner: "the top should just be 'currently served' and then underneath it 'available from the vendor'", grouped by kind then platform.
- Must: Where builds are listed, currently served ones come first, then the vendor's offer, then other held versions folded away, each grouped by kind then platform.
- Kind: ruling

## Each computer's state

### DSH-011: Phones have no hover, so help shown only on hover is unreachable.
- Why: Chips, fields and states explained themselves only on mouse hover, clipped at 40 characters, on the page most opened on phones.
- Must: Every explanation of a chip, field or state can be read in full by tap, mouse and keyboard, and no internal reason code is ever shown.
- Kind: given

### DSH-012: A computer with no projects ticked is fine, never an error.
- Why: The owner: "A computer having nothing ticked is FINE", repeated after quiet ones were still drawn amber or red or counted as expected to sync.
- Must: A computer with nothing ticked leads with a neutral line and is never an error, warning, alert, blocked state, open issue or expected syncer, even when quiet.
- Kind: ruling

### DSH-013: Each computer row shows one headline, with nothing overlapping.
- Why: The owner: "very visually cluttered, clean it up" and "text disorderly, overlaying things"; one row repeated a sentence three times and an empty box was "way too big".
- Must: Each computer shows one headline (named fault, out of date, transfer error, nothing ticked, then syncing or idle), its transfer states, details folded, nothing overlapping, boxes sized to content.
- Kind: ruling

### DSH-014: A computer that syncs nothing by design was shown "sync engine down" for 28 days.
- Why: A wired computer works straight on the NAS and syncs nothing, yet its headline and chip judged it like an editing computer.
- Must: A computer whose role syncs nothing never shows a sync fault, chip, headline or alert about syncing; an editor's computer still does.
- Kind: situation

### DSH-015: Checks raised alarms about states chosen on purpose.
- Why: Alarms fired on a computer that syncs nothing by design, a sharing plan with no differences, a superseded build's failed test, and features switched off.
- Must: A check never alarms on a state chosen on purpose, a feature the site switched off, a plan with nothing to change, or a build already superseded.
- Kind: situation

### DSH-016: A computer that stopped reporting kept its green dot for a week.
- Why: A caught-up computer that went quiet was never "behind", so its last transfer states stayed frozen green.
- Must: A computer with no report for 15 minutes shows amber, after 6 hours red, as not heard from with when it last reported, whatever it last said.
- Kind: situation

### DSH-017: A laptop that was simply asleep was shown red "upload has stopped".
- Why: Every silent computer turned red at 15 minutes, though laptops sleep for hours.
- Must: A quiet computer reads as asleep or not reporting, never as a sync fault, unless it was known to be mid-transfer when it went quiet.
- Kind: situation

### DSH-018: A computer red for three hours was reported by no alert.
- Why: A check that stayed quiet on purpose about computers with a personal project open also marked them reported, so the last-resort alert skipped them.
- Must: A computer whose sync is red for hours is always reported by some alert, even when other checks deliberately say nothing about it.
- Kind: situation

### DSH-019: A computer refusing to sync looked idle with nothing to do.
- Why: Signed out, wrong clock, drive absent, disk full, stopped, licence not accepted, nothing shared and offline were each known, yet showed as "idle, 0 queued".
- Must: Each computer shows one plain sentence saying why it is not syncing, the first true cause in a fixed order; "idle" only when working with nothing to move.
- Kind: situation

### DSH-020: A computer whose person was signed out stopped syncing without a word.
- Why: A Mac with nobody signed in sent no reports and ignored a queued update for days; elsewhere an expired sign-in silently stopped a computer.
- Must: A computer's sign-in never expires on its own, and a computer with nobody signed in shows "nobody signed in".
- Kind: situation

### DSH-021: A computer that could not prove who it is vanished like a switched-off one.
- Why: A revoked or unverifiable computer sent nothing the server accepted, so it simply stopped appearing.
- Must: A computer that cannot prove who it is still appears as "cannot sign in", with the reason.
- Kind: situation

### DSH-022: A computer read "idle, nothing owed" while a failed upload sat folded away.
- Why: Warnings were moved behind a collapsed details control that carried no count, and the headline never asked what was still owed.
- Must: A headline is never calmer than its details; every folded-away warning is counted on the folded control, and "nothing owed" is said only after checking.
- Kind: situation

### DSH-023: A full editor drive showed as a red dot with no reason.
- Why: Free disk space appeared nowhere, and a retired computer's year-old low-disk reading stayed an alarm for ever.
- Must: Each computer's free space shows amber under 10% or 50 GB, red under 5% or 20 GB; never reported or over 48 hours old gives no verdict.
- Kind: situation

### DSH-024: The dashboard said downloads stopped themselves with 145 GB free.
- Why: It read its own under-5% colour on a 4 TB drive as a stop, though the editor app stops only below an absolute 20 GB.
- Must: Why a computer stopped is told only from the reason it reported, at its own threshold; a low-space colour is a warning, never a stop.
- Kind: situation

### DSH-025: A computer with a wrong clock vanished or looked signed out.
- Why: Ordering and pruning used times the computer supplied, and a far-off clock made a fresh sign-in look expired.
- Must: Freshness, ordering and pruning use the server's own receive time, and an expiry caused by a wrong clock names the clock, not the sign-in.
- Kind: situation

### DSH-026: A wrong clock on the NAS must not turn every computer red.
- Why: With the server's clock wrong, every computer's last report looked stale, so the whole fleet showed as failing.
- Must: A wrong server clock is reported as itself and never marks healthy computers as stale.
- Kind: situation

### DSH-027: An upload stall that healed stayed red for 13 days.
- Why: The editor app kept re-sending an old stall record, and the dashboard trusted it though uploads had completed every day since.
- Must: A stall shows only while current: a completed pass in that direction since it began clears it, while a stall with no way to tell stays shown.
- Kind: situation

### DSH-028: A computer could show "indexing" forever after its work finished.
- Why: When finished work is signalled only by the report going quiet about it, a remembered "busy" never clears.
- Must: A computer's busy indicator clears on the first report after its work ends.
- Kind: situation

### DSH-029: A page about one computer showed another computer's open project.
- Why: It read the person's most recently reporting computer, so a MacBook's page named the project open on the same editor's iMac.
- Must: A page about one computer shows only that computer's facts, and the choice survives refresh; only a page about the person shows their newest computer's.
- Kind: situation

### DSH-030: A count for one project was shown as if it were the whole computer's.
- Why: A per-project count was kept per computer, so one project's zero overwrote another's four and admins searched the wrong project.
- Must: Every figure names the project or folder it covers, and one scope's figure never overwrites another's.
- Kind: situation

### DSH-031: "Safe to close" was worked out for the person, not the computer it named.
- Why: It counted uploads from all of a person's computers but said "this computer", and left out projects still preparing.
- Must: "Safe to close" names the computers that still owe uploads, and is never shown while any project is still preparing.
- Kind: situation

### DSH-032: Summary counts contradicted the rows right below them.
- Why: "Moving 0 B, nothing ticked anywhere" sat beside 15 files transferring, and a filtered view's counts switched to the whole fleet.
- Must: Every summary count agrees with the rows it summarises, for the same view, and updates when they change.
- Kind: situation

## Ticking and unticking

### DSH-033: Choosing what a computer syncs starts from a person, then a computer.
- Why: The owner: showing every user at once "would be very unwieldy" in a big company; "it just shows the picker so you can select someone".
- Must: Where an admin sets what a computer syncs, nothing is listed until a person and a computer are chosen, preselected when the site has only one.
- Kind: ruling

### DSH-034: A tick that could not be added could not be removed either.
- Why: The owner: "animals is ticked but I cannot untick it. They're all greyed out." Refusing new ticks on a wired computer disabled its old tick too.
- Must: An existing tick can always be removed wherever shown; only unticked boxes are locked, with the reason, and a leftover forbidden tick is never reported as an error.
- Kind: situation

### DSH-035: Ticking for a person changed all their computers without saying so.
- Why: A person-level tick pulled a project to every computer they own, and unticking on one computer could remove it from the others.
- Must: A tick or untick changes only the chosen computer; one covering several computers names each and asks first; a plan change can be undone exactly within an hour.
- Kind: situation

### DSH-036: A confirmed "this removes the project" re-ticked it instead.
- Why: Tick controls only said "flip", so a control drawn before another view changed the plan did the opposite.
- Must: Every tick or untick carries what the person intends, a stale control never does the opposite, and cancelling restores what the screen showed.
- Kind: situation

### DSH-037: Ticks flipped on screen but saved nothing, with no error.
- Why: A broken page script left checkboxes flipping visually with no request made, unnoticed across ten releases.
- Must: A control that fails to save tells the person so; a change never looks saved when it was not.
- Kind: situation

### DSH-038: Ticking every project for a new editor tried to put 4 TB on 500 GB.
- Why: Ticking checked nothing about size, though each project's proxy size and each computer's free space were known.
- Must: Ticking warns when a project's proxies exceed the computer's free space, naming both figures, and asks before saving; it never refuses.
- Kind: situation

### DSH-040: One click wiped a computer's whole plan with no confirmation.
- Why: Clearing a plan, copying one plan over another, revoking a key, setting a password and disabling an account each acted on one click.
- Must: Destructive actions ask first, naming what changes on both sides; copying an empty plan is refused, and a plan copy can be undone.
- Kind: situation

### DSH-041: Nobody could tell who unticked a project, or when.
- Why: Plan changes, halts, pushed updates, file moves, deletions, publishes and settings overwrote state with no history, with several admins on one dashboard.
- Must: Every change to plans, people, computers, releases or settings is kept in an append-only history of who, what and when, for 180 days, filterable.
- Kind: situation

See also, filed under another capability:

- SYN-110 (Sync): After a tick, nothing happened for a minute, then pages said nothing moved.

## Projects

### DSH-042: Every new project appears for every editor automatically.
- Why: A project an editor tried to sync never appeared; the owner wants every new project available to every editor with no admin step.
- Must: A project created on the server or set up from Resolve appears, tickable, for every editor within minutes, with nobody granting access.
- Kind: ruling

### DSH-043: Project status shows each person's total progress, not one route's share.
- Why: Status read "0/1 files, 128b" while hundreds of proxies were local; the owner: show "what percentage of proxies they have, along with all other media".
- Must: Each person's project status is total bytes held of what they should have, proxies and other media, excluding originals that live only on the server.
- Kind: ruling

### DSH-044: For each project and person, show what is held, missing and moving.
- Why: The owner wanted files held and missing, offline in Resolve, proxy-only as normal for remote editors, and above all live speeds and times left.
- Must: Per project and person: files present, missing, offline in Resolve, and every running transfer with speed, files remaining and time left.
- Kind: ruling

### DSH-045: Project lists nest by folder and start collapsed.
- Why: The owner wanted every computer in a project's view, each person's media foldable, and the project list nested by year and series with short names.
- Must: A project's view lists every computer, media folded per person; the project list nests by folder with short names, collapsed except the open project's path, across refreshes.
- Kind: ruling

### DSH-046: Choosing a project's server folder is a real folder browser.
- Why: The picker offered only a prefilled list, and linking an existing folder forced a new subfolder: "this is pointless behaviour".
- Must: Setting a project's folder lets a person browse the real server tree and link any existing folder as it is, or create a new one anywhere.
- Kind: ruling

### DSH-047: A project's server folder, once set, changes only when an admin changes it.
- Why: The owner: the folder "should be stored, and fixed, only changed if an admin changes it manually", with the detected value visible.
- Must: Each project's detected folder is shown; once set, only an admin changes it and nothing automatic rewrites it.
- Kind: ruling

### DSH-048: Projects are linked only on an exact name, never on a guess.
- Why: "Event 1 Videos" matched "Creator Profiles Season 1" on the digit; a name sharing two words was linked for good; the owner: "the matcher should be updated".
- Must: A project is linked automatically only on an exact name match with one project; any partial match asks a person, and no guess is stored unconfirmed.
- Kind: ruling

### DSH-049: Orphaned proxies raise one warning per folder, not one per proxy.
- Why: A folder moved by hand on the NAS left 56 orphaned proxies, one warning each, two visible at a time; the owner: "one warning per folder ... not one warning per proxy".
- Must: Orphaned proxies raise one warning per proxy folder, naming the first few clips and counting the rest.
- Kind: ruling

### DSH-051: New footage took hours to show as on the server.
- Why: Checking a few projects per cycle, unchanged ones included, took 3.1 hours to show new footage, and 15.6 hours at 500 projects.
- Must: A file that reached the server shows as on the server within five minutes, at 500 projects as at 5.
- Kind: situation

### DSH-052: Clips in a folder borrowed from another project were missing from its totals.
- Why: Borrowed files were counted only under the project that owns the folder.
- Must: A project's media figures include files in folders it borrows, labelled as borrowed.
- Kind: situation

### DSH-053: A computer's file counts showed files it could not have.
- Why: An editor showed 195 of 283 proxies for a project never synced, and one computer showed different counts under two accounts.
- Must: A computer's file counts come only from files found on that computer, and one computer reports under one identity.
- Kind: situation

### DSH-054: Finished proxy downloads looked owed because a file list was capped.
- Why: A computer's file list was capped at one total, filled by originals first, so up to 523 proxies past the cap looked missing.
- Must: What a computer holds is never cut short so that files look owed; any limit applies per kind and is shown as truncated.
- Kind: situation

### DSH-055: Leftovers of a failed download sat as owed uploads forever.
- Why: Half-finished download part files, 31.7 GB, were counted as uploads due, though the sync never sends such files.
- Must: Files the sync deliberately never sends are never counted as owed, queued or behind.
- Kind: situation

### DSH-056: A folder holding other projects could be made a project, then never synced.
- Why: A project mark on a parent folder hid the projects beneath it from the nesting check, so linking succeeded but it never synced.
- Must: A folder that contains a project, or sits inside one, can never be made a project, and the refusal names the nested project.
- Kind: situation

### DSH-057: A mistyped project could never be removed from the lists.
- Why: Any editor may create a project, deliberately, but nothing removed one; deleting the folder by hand was the only cure.
- Must: An admin can archive a project, removing it from every list without deleting anything; the archive survives rescans, and creating says who can undo it.
- Kind: situation

### DSH-058: Creating a project over an archived one said "ok" but left it hidden.
- Why: A project created or adopted under an archived project's name succeeded on paper while staying archived and invisible.
- Must: Creating or adopting a project under an archived project's name is refused, saying it is archived, until it is un-archived.
- Kind: situation

### DSH-059: A project name with an apostrophe broke the confirmations.
- Why: Names people type contain apostrophes, quotes and Chinese; pasted into a confirm dialog's code, a quote ended it and a crafted name became script.
- Must: Every action and confirmation works for any name a person can type, shows it exactly, and never runs any of it as code.
- Kind: situation

### DSH-060: A ".." in the folder template created folders outside the project.
- Why: One source of the new-project folder template did not filter "..", so every new project wrote folders outside its own directory.
- Must: Folder names from every source of the project template are stripped of ".." and leading separators before any folder is created.
- Kind: situation

See also, filed under another capability:

- PRX-039 (Proxies and file moves): A new project said "0 originals" for up to 45 minutes.

## Transfers and the queue

### DSH-061: The queue lists only ticked work waiting behind live transfers.
- Why: 737 files, 44 GB, from projects nobody had ticked showed as queued; the owner wants "files which are queued on the current sync job, but aren't yet syncing".
- Must: The queue lists, per person and project, files from ticked projects waiting behind running transfers; unticking removes a project from every queue and "behind" mark at once.
- Kind: ruling

### DSH-062: A 400 MB upload appeared nowhere and looked stuck.
- Why: Uploads to the NAS showed in no view, and a file finishing between 60-second polls reached neither live transfers nor history.
- Must: Every transfer in either direction shows live while running, progress updates within seconds, and every finished file lands in history.
- Kind: situation

### DSH-063: A backlog stuck behind an unplugged drive looked like it was draining.
- Why: 52 originals, 23.5 GB, sat queued for days as an ordinary upload while the computer had reported its sync drive absent.
- Must: A queued backlog its computer reports it cannot move shows "on hold", the computer's own reason, and since when.
- Kind: situation

### DSH-064: A long clip name pushed progress and speed off the screen.
- Why: Long unbroken names, often Chinese with no spaces, set the table's width and hid the columns the table exists for.
- Must: File names wrap anywhere and show whole on hover or tap; progress, speed and time left stay visible at 390, 1100 and 1600 pixels wide.
- Kind: situation

## People and computers

### DSH-065: Accounts the product uses for itself appeared as editors.
- Why: The owner: "what are these users - this is bad UX for an end user"; the server's own account showed as an editor with a missing key.
- Must: Only real people appear in any list of people; the product's own accounts never do, and get their access without joining the editors' group.
- Kind: situation

### DSH-066: Approving a second computer seemed to ask for a new username.
- Why: Typing the computer's name into the approval box created an editor with no plan, which unshared that computer from every project.
- Must: Approving a computer means choosing its existing owner, prefilled from what it reported; a new person only by explicit choice; one person may own many computers.
- Kind: situation

### DSH-067: A departed editor's computer kept receiving projects.
- Why: Nothing could delete a person or a computer, and removing someone by hand left their device on every project share.
- Must: Deleting a person removes accounts, devices, shares and sessions, all or nothing; removing one computer says plainly it is not a revocation while the person remains.
- Kind: situation

### DSH-068: A dead or departed computer vanished while still holding projects.
- Why: Its status expired after 30 days, or a computer limit deleted the oldest record, while its plan and shares stayed active.
- Must: A computer unseen 7 days is listed as lost with the projects it holds; one holding ticks or shares is forgotten only by an admin, never automatically.
- Kind: situation

### DSH-069: A retired laptop mailed the owner the same alarm every day.
- Why: A computer silent three weeks raised the same daily error 21 times, nothing said it could be removed, and the owner learned to ignore alerts.
- Must: A computer silent 14 days is reported once more, then stands as one "forgotten?" notice offering to forget it, until it reports or is forgotten.
- Kind: situation

### DSH-070: Two computers cloned from one disk fought over one identity.
- Why: A copied disk carries the same identity and sync device, so each report took the other's record and plan, and sharing never settled.
- Must: Two computers claiming one identity both stay visible and flagged, with how to reset the newer; a rename counts only once the old name is silent five minutes.
- Kind: situation

### DSH-071: A renamed computer lost its plan or its outstanding commands.
- Why: Commands were filed under the computer's name, and a rename onto an existing name deleted that computer's plan.
- Must: A renamed computer keeps its plan, history and outstanding commands; clones never get each other's commands; a rename onto another's name changes neither plan and warns.
- Kind: situation

### DSH-072: An admin could not get diagnostics without the editor's help.
- Why: Diagnostics went only to the broken computer's clipboard, relying on a non-technical editor to send them.
- Must: An admin can ask any reporting computer for its diagnostics and receive them with no editor action; one whose transfers fail sends them itself, at most hourly.
- Kind: situation

### DSH-073: Pushing to a laptop shut in a bag looked like a live push.
- Why: Update, resume and ask-why answered "ok" for a computer last heard from nine days ago, and the queued row never moved.
- Must: A command to a computer says when it will apply and when the computer was last heard from, warning if long ago, without refusing.
- Kind: situation

## Reports from computers

### DSH-074: Report fields the server did not know were silently thrown away.
- Why: Nine Resolve health fields, such as "Resolve wedged 40 s", and later whole sections were sent on every report and dropped unseen for weeks, three times over.
- Must: Every field a computer reports is stored and shown or named loudly as unknown; a section no longer sent clears the old one; never sent shows nothing.
- Kind: situation

### DSH-075: One bad field got a computer's whole report refused, cutting it off.
- Why: A number where text was expected, over-long error text, over 64 projects or over 8 MB refused every report, and the reply is the computer's only channel for stops and updates.
- Must: A report is never refused whole: a wrong, unknown or oversized part is trimmed or dropped and named, the rest kept, its commands delivered, the computer still listed.
- Kind: situation

### DSH-076: Computers re-sent unchanged file lists every minute.
- Why: Each computer re-sent thousands of file names every 60 seconds though they changed every 2 to 5 minutes, and the server rewrote every row.
- Must: Large file lists are sent and stored only when they change, with an occasional full resend so the server converges after a restart.
- Kind: situation

### DSH-077: A momentary empty listing made the server treat projects as deleted.
- Why: The NAS sync service restarted empty or a volume was not mounted yet, so projects were deactivated and their inventory wiped; the later refusal never reached the owner.
- Must: A pass that would deactivate over a quarter of projects or drop over 90% of a project's files is refused, keeps the old data, and stays on the home page until resolved.
- Kind: situation

### DSH-078: Facts the system relied on broke silently and were found by accident.
- Why: A tick never shared to its computer, a project folder renamed on the NAS, a cloned disk and an impossible update floor were each checked only when written.
- Must: Every cycle compares plans with actual sharing both ways and names each broken fact, and any device awaiting approval over 24 hours, with consequence and fix; it never repairs.
- Kind: situation

## Problems the server finds

### DSH-079: The server diagnoses itself as far as it can.
- Why: The owner: "make the server as self-diagnosing as possible. Any errors should be flagged, the diagnosis should be as clear as possible"; refusals had reached only a log.
- Must: Every problem the server finds shows on the home page with a plain next step, and comes back if dismissed while still true.
- Kind: ruling

### DSH-080: Problems that have gone away leave without anyone clicking dismiss.
- Why: The owner: "if they are resolved they should go away without needing dismiss to be clicked"; one-off errors and outdated warnings stayed open for weeks.
- Must: Every problem has a rule that closes it (cause gone, a later success, or 24 quiet hours for one-off errors), and warnings about unknown data are re-judged after a server update.
- Kind: ruling

### DSH-081: Every fix a page suggests can be done from where the person is.
- Why: The owner: "Make this a click-through wizard, this is too complex for most users"; messages said "edit a setting and redeploy", named internal keys, guessed causes or named hidden pages.
- Must: Every problem names its real cause, or "cannot tell", and a fix that is a button, a link that goes there, or "ask whoever installed this server", never a command.
- Kind: ruling

### DSH-082: The footage-outside-the-tree warning must name the project.
- Why: The owner: "this warning should say which project. the project might be an editor's personal project which they don't want to sync."
- Must: The warning names the project; a project tied to no synced project raises nothing; when the open project is unknown it says "could not check", never "fine".
- Kind: ruling

### DSH-083: A check that could not run looked the same as one that passed.
- Why: Checks that crashed, could not reach the NAS, could not see their evidence or were never evaluated showed as fine, and some closed findings with "no action needed".
- Must: Every check reads OK, broken, not checked (with the reason) or failed to run, each visibly different, and only a real verdict opens or closes a problem.
- Kind: situation

### DSH-084: A network check that could not read the network mailed "cleared".
- Why: Checks of the server's own network sent an all-clear when the network state could not be read at all.
- Must: A check that cannot read its evidence reports "could not check", never "cleared" or OK, and sends no all-clear mail.
- Kind: situation

### DSH-085: A check failing now still showed OK because it once passed.
- Why: Any check evaluated once ever showed OK, including one now failing every cycle or no longer running at all.
- Must: A check shows OK only if its latest run passed recently; one failing shows failed, and one not run recently shows not checked.
- Kind: situation

### DSH-086: The owner was mailed "cleared" about problems nobody had fixed.
- Why: Anything absent from a scan counted as recovered: another project opened, a cap of 20 or 40 per kind, a recency window, a check with no verdict.
- Must: A problem closes only when a complete check found it gone; capped, filtered, skipped or unchecked subjects stay open and mail nothing; a display limit never limits what is known.
- Kind: situation

### DSH-087: A background pass that refused or skipped its work counted as success.
- Why: A safety brake froze all project unticks for days while health showed fine, and its only trace was a log line lost on restart.
- Must: A background pass that refuses or skips work shows as incomplete with its reason on the home page and in alerts, until a clean pass clears it.
- Kind: situation

### DSH-088: A scheduled server task could stop running while the home page looked fine.
- Why: A task that last ran fine then stopped showed nothing amiss, while a fresh install's first check ran 10 minutes in and a 3-minute rule flagged it stopped.
- Must: A task past its usual interval shows overdue and raises an alert; a fresh install running on schedule is never flagged, but work dead at start is, within minutes.
- Kind: situation

### DSH-089: Everything wrong was spread across separate places.
- Why: Notices, alerts, broken cross-checks and missing protections each lived apart, each half-answering "is my fleet all right".
- Must: Everything the server knows is wrong appears in one list ranked error, warning, then not checked, with each source's words and links; one broken source never blanks it.
- Kind: situation

### DSH-090: An optional feature that failed simply vanished from the menu.
- Why: B-roll or music search failing to start lost its link with no reason shown, and a feature whose NAS share dropped at night stayed advertised as working.
- Must: A feature that is on but unavailable shows broken with its reason; one whose data disappears shows degraded within one check; unreadable status reads "not checked".
- Kind: situation

### DSH-091: Cleared notices were kept for ever.
- Why: Notices had no retention, so cleared rows about computers long gone piled up; any cleanup also had to spare open problems however old.
- Must: Cleared notices are deleted after 120 days; an open notice is never removed by any cleanup, however old.
- Kind: situation

### DSH-092: A server error notice pointed at a log a server update had deleted.
- Why: The notice held only the error's type and "see the server log", but the log does not survive a server update.
- Must: A server-error notice carries its own error type, message and innermost few code locations, bounded in size, with every key or token masked.
- Kind: situation

### DSH-093: A slowness warning blamed the wrong cause.
- Why: A slow but harmless NAS scan was reported as holding the data store, and slow-write timing counted queue waits and advised editors to untick.
- Must: A slowness problem measures only how long the lock was held, names the real holder, never advises an editor to untick, and clears once a later check passes.
- Kind: situation

### DSH-094: Alerts counted deliberate restarts as crashes.
- Why: Intentional restarts and a test abort counted as crashes, and an alert fired when the studio ran a newer server than the vendor offered.
- Must: Alerts never count a deliberate restart as a crash, and never flag running a newer release than the vendor offers.
- Kind: situation

### DSH-095: "I have backed it up" was recorded, but its line stayed red.
- Why: The line showed the last check, run every 15 minutes, while the click only updated stored data.
- Must: Acknowledging a problem updates the line it acknowledges, and the warnings it raised, immediately.
- Kind: situation

### DSH-096: Error records from two features merged, naming a page that does not exist.
- Why: Errors inside b-roll and music were filed under an inner address both share, not the address a person actually used.
- Must: Every error record names the full address that failed, keeps features apart, and never stores the secret part of a client share link.
- Kind: situation

## Alerts by mail

### DSH-097: Alert mail comes as one digest, not one mail per alert.
- Why: Turning mail alerts on sent eleven messages in one minute, and every unfixed error mailed again daily; the owner: "I'm getting spammed with emails now."
- Must: One message per check: new problems worst first, unfixed ones one line each with days open, recoveries included; the first message says it is a catch-up.
- Kind: ruling

### DSH-098: The admin chooses which kinds of alert are mailed.
- Why: The owner: "I want to be able to select which types of email alerts the admin gets. What types of warnings, etc."
- Must: Each alert kind can be switched on or off for mail by an admin, and a switched-off kind still shows on the dashboard.
- Kind: ruling

### DSH-099: Problems reached nobody unless the owner happened to look.
- Why: An editor's sync was dead 18 hours before anyone noticed; alerts had nowhere to go by default and said nothing about it.
- Must: Detected problems reach a named person within an hour, unasked, repeated daily while true, with recovery notes and a weekly report; no destination is a fault until set or skipped.
- Kind: situation

### DSH-100: Alert delivery showed as working before anything was ever sent.
- Why: A weekly report "generated, not sent" with no mail set up counted as proof, so a mistyped mail server read green for a week.
- Must: Alert delivery shows as working only after a real message reached a recipient through that same channel.
- Kind: situation

### DSH-101: A half-hour mail outage lost the week's report.
- Why: A failed send counted its slot as done, and three tries ten minutes apart could not outlast a relay down from 07:55 to 08:40.
- Must: A report, heartbeat or alert whose send fails is retried with a widening gap (about 10 minutes, 1 hour, 6 hours) and delivered late, never dropped.
- Kind: situation

### DSH-102: A failed alert and a failed editor install reached nobody.
- Why: An alert that failed to send was never retried or shown, and an editor's failed install was invisible to the admin.
- Must: An alert that cannot be sent shows as undelivered until it goes, and an editor's failed install appears on the dashboard.
- Kind: situation

## Settings and setup

### DSH-103: AI providers are tried in the owner's order unless one is pinned.
- Why: The owner asked for one place to enter keys or sign in to each provider, with features using "the first which is available".
- Must: Each AI feature uses the first available provider in the owner's order unless an admin pins one; a pinned one unavailable is refused, never replaced; the one in use is shown.
- Kind: ruling

### DSH-104: Connecting an AI provider is a short click-through setup.
- Why: Connecting meant installing a program on the server by hand, "too complex for most users", and listing every provider at once was "visually confusing".
- Must: Only active providers are listed, plus "add new": a picker, then a guided setup (notice, verified install, browser sign-in with code, test), with the manual path still offered.
- Kind: ruling

### DSH-105: The setup checklist showed placeholders and a step that could never pass.
- Why: The owner photographed "TODO waiting on: admin" and "not implemented", and a required step waited on a check that could never pass on that site.
- Must: The setup checklist never shows placeholder text; every item is a real check naming its next action, and no required step depends on an unanswerable check.
- Kind: ruling

### DSH-106: Settings saved on the dashboard were ignored by the server itself.
- Why: Brand, project folder templates, shared folders, NAS kind and a feature switch reached computers while the server kept its install-time values.
- Must: A saved setting takes effect everywhere, server included, within seconds and without restart, from one source; core features never depend on an optional feature's switch.
- Kind: situation

### DSH-107: The owner could not change the dashboard address in settings.
- Why: The owner: "it won't let me change the dashboard url"; the field locked once any value had ever been stored, though nothing supplied one.
- Must: A setting is locked only while a live source supplies it now; a doubtful check leaves it editable, and a differing value elsewhere is shown beside it.
- Kind: situation

### DSH-108: A computer's own setting was greyed out with no hint where to change it.
- Why: Wired versus remote is each computer's own setting, but the dashboard greyed its boxes without saying so.
- Must: Wherever a computer's own setting is shown read-only, visible text says where to change it on that computer.
- Kind: situation

### DSH-109: Importing a settings file overwrote everything with no preview or undo.
- Why: Pasting an older or another site's settings replaced every value, the project drive letter and tree name included, with no record of the old ones.
- Must: A settings import shows what will change and asks first, and keeps the replaced values so the change can be undone.
- Kind: situation

### DSH-110: Undoing a settings change emptied lists instead of restoring them.
- Why: Undo restored blank instead of the default for settings never set, and its confirm quoted an older change then reverted the newest.
- Must: Undoing a settings change restores exactly the earlier effective values, and its confirm names the change it will actually undo.
- Kind: situation

### DSH-111: After a successful sign-in, the test and other features still said failed.
- Why: The setup dialog collapsed whenever the page refreshed its list, and the test and the downloader kept a stale "failed" after sign-in.
- Must: A setup dialog survives page refreshes, and a successful sign-in is seen at once by its test and every feature using it.
- Kind: situation

### DSH-112: A customer could not see whether their server and apps were current.
- Why: Only the vendor could compare versions; a customer had no view of their versions against the newest offered.
- Must: An admin sees server and app versions against the newest offered and how many computers run each; an offer not checked reads "not checked", never "up to date".
- Kind: situation

### DSH-113: An admin's setup button answered only "internal error".
- Why: The free-space check before installing a helper could itself crash, and the button had no last-resort answer.
- Must: A failing admin button names what failed, that nothing was half-installed, and the fallback; a check that cannot finish is a refusal, never a yes.
- Kind: situation

## Pages that refresh and answer clicks

### DSH-114: A browser scrolls to a section link only once, while the page loads.
- Why: Parts that arrive a moment later are never scrolled to, so the link lands at the top, and a repeat press of the same link did nothing.
- Must: A link to a section scrolls there once it arrives, every time it is pressed, without fighting a reader who has already scrolled.
- Kind: given

### DSH-115: Returning to a page reopens it where the person left it.
- Why: Each page change reloaded a long page at the top; the owner: "it should remember your position from the last time".
- Must: Returning to a page restores its scroll and open sections after late parts load, unless the link names a section; positions expire after 8 hours.
- Kind: ruling

### DSH-116: The answer to a click appeared far from the button pressed.
- Why: Answers were drawn at the top of long pages or on another row, or lost when parts refreshing every 15 seconds took their slot.
- Must: An action's answer appears in view beside the control pressed, or on the page if it is gone, replacing earlier answers, even while other parts refresh.
- Kind: situation

### DSH-117: Long-running buttons showed nothing for up to two minutes.
- Why: Create, publish and check-now gave no sign of working, so people clicked again and started a second multi-megabyte download.
- Must: Every control that can take over a second shows it is working and disables itself until the answer arrives.
- Kind: situation

### DSH-118: Self-refreshing pages wiped what an admin was typing.
- Why: Parts redrawn every 10 to 60 seconds cleared typed text, closed open lists, pickers and toggles, and erased one-time passwords before they were copied.
- Must: A refresh never discards typed input, an open list, picker, sheet or toggle, an action's pending answer, or a one-time secret; every secret has a copy button.
- Kind: situation

### DSH-119: The dashboard said "updated 4s ago" while unreachable for an hour.
- Why: Failed refreshes were not reported, and the freshness stamp was drawn once per page load.
- Must: Every page shows when its data last updated successfully and says plainly when updates are failing.
- Kind: situation

### DSH-120: An expired session pasted the sign-in page into the page's own panels.
- Why: Self-refreshing parts inserted the sign-in page every few seconds, and a 12-hour-old tab's first click said "login required", reading as a permissions fault.
- Must: When a session expires, the next refresh or action takes the person to sign in and back to the page, and a batch of clicks stops at the first failure.
- Kind: situation

### DSH-121: A program calling with an expired sign-in got the sign-in page.
- Why: Programs and audio players handed a sign-in page fail with cryptic messages on every poll and never learn the session expired.
- Must: A request that is not a page, without a valid sign-in, gets a clear machine-readable "signed out" answer, never the sign-in page.
- Kind: situation

### DSH-122: One busy or failed source turned a whole page into an error.
- Why: A brief NAS hiccup blanked a whole panel, computers awaiting approval included, and a busy data store could have shown "nobody suspended" as fact.
- Must: A failed source spoils only its own part, which says "could not read this right now" with its last known state and time; the rest renders, no empty answer stated.
- Kind: situation

### DSH-123: One stored time without a time zone broke a page for days.
- Why: A single sign-in record carried a time with no zone, and formatting "how long ago" crashed every render of the page.
- Must: A badly formed stored value spoils at most its own cell, and a stored time with no zone is read as UTC.
- Kind: situation

### DSH-124: A dashboard open on a phone in a pocket kept polling the server.
- Why: Hidden tabs kept refreshing every two seconds, slowing the server for the whole studio.
- Must: A hidden page polls nothing, refreshes once when shown again, and polls more slowly on touch devices.
- Kind: situation

### DSH-125: The only button that closes an error was red text on a red banner.
- Why: Error banners are red and buttons were drawn red, so dismiss was clickable but unreadable on every error.
- Must: Every button and link on any banner is legible against that banner's own colour.
- Kind: situation

## Speed under load

### DSH-126: The home page grew slow as the fleet grew.
- Why: It ran 1,170 data store queries per load, 2.8 s with 20 computers; each open tab rebuilt it 12 times a minute, about 6 s at 50 editors.
- Must: The home page loads within a second for 20 computers and stays fast at 50 editors and 400 projects; a refresh with nothing changed costs little.
- Kind: situation

### DSH-127: One slow save froze the dashboard for everyone.
- Why: Saves waited up to 5 s (3.07 s measured) while every request queued, and a report rewriting 6,000 rows made 12 clicks fail in 27 minutes.
- Must: While one write waits, every other page and report is answered within a second; "busy" answers at once, background writes wait their turn, and the slow writer is recorded.
- Kind: situation

### DSH-128: One admin's long action froze the dashboard for ten minutes.
- Why: A publish download of up to 600 s, a music upload of 55 MB files, and editor recalculation at 97% of a core for 4 s ran where every page waited.
- Must: No admin action, upload, search or feature work delays other pages or computers' reports by more than a second; long work runs aside and shows progress.
- Kind: situation

## Phones and the installed app

### DSH-131: Chrome's phone emulation hides sideways overflow from width checks.
- Why: Under mobile emulation the layout viewport grows to the content, so page width equals window width and overflowing pages pass.
- Must: Phone-width checks compare page width with the visible viewport, not the layout viewport.
- Kind: given

### DSH-132: An installed phone web app keeps old files until its background script changes.
- Why: Cached files are served first and never rechecked, so a redeploy with the same version left stale styles even on hard reload.
- Must: After any redeploy, version changed or not, installed phone pages paint from cache but fetch fresh copies, so the next visit uses them.
- Kind: given

### DSH-133: A browser may stop a page's background worker mid cache refresh.
- Why: Unless the worker is told to wait for its background refresh, the browser can stop it first, so a fix never arrives.
- Must: A fix republished without a version change reaches every browser within two visits, slow mobile connections included.
- Kind: given

### DSH-134: Phone install and offline use need https and fail silently without it.
- Why: Offline workers, "Add to Home screen" and Android's app wrapper all need a secure address and do nothing without one; Android installs only from https.
- Must: The dashboard is reachable on https wherever phones use it, every "open dashboard" link follows the site's published address, and a check names any failing install step.
- Kind: given

### DSH-135: On a phone every page scrolled sideways and controls were tiny.
- Why: Pages built for 1280 px overflowed by up to 1500 px at 390 px, one went black, and the checkbox that starts a real sync was 13 px.
- Must: At phone and tablet widths no page scrolls sideways or hides content, tables become labelled rows, touch targets are at least 44 px, text at least 12 px.
- Kind: situation

### DSH-136: On a phone the projects to tick were 10,000 pixels down the page.
- Why: The phone shortcut for ticking landed where the project list came last, and the "tick a project" hint did not link to it.
- Must: On a phone, ticking a project is one tap from every place that asks the person to tick one.
- Kind: situation

### DSH-137: The installed dashboard could show a stored copy as live, with the last user's name.
- Why: A cached page served offline would claim footage was syncing during a halt, and the saved offline page kept the old user, admin menu and form token.
- Must: Offline, the installed app shows an "offline" page carrying no user, role or form token; status, data and sign-in pages are never served from a stored copy.
- Kind: situation

See also, filed under another capability:

- ALL-010 (The whole product): iOS zooms the whole page when a form field's text is under 16 px.

## Security of pages

### DSH-138: Browsers send "Origin: null" from places that are not this site.
- Why: Sandboxed frames, data and blob documents and some redirect chains send "Origin: null", and it was let through like a missing origin.
- Must: On anything that changes data or drives Resolve, "Origin: null" without a matching referrer is refused; only a truly absent origin may pass.
- Kind: given

### DSH-139: An endless upload with no sign-in could crash the dashboard.
- Why: The size limit trusted the declared length, and the body was read before the credential was checked, so a streamed endless body exhausted memory.
- Must: Credentials are checked before any body is read, and reading stops at a hard size limit whatever length is declared.
- Kind: situation

### DSH-140: A sign-in exemption outlived the page it was made for.
- Why: A deleted page's exemption stayed, so anything later added at that address would be open to anyone.
- Must: An exemption from sign-in goes with the page it exists for; nothing beyond the named pages is reachable without signing in.
- Kind: situation

### DSH-141: The help viewer served every internal document to anyone signed in.
- Why: Every document in the source tree, the bug ledger included, was browsable by customers.
- Must: The help viewer serves only documents published for that reader's audience, refuses any path outside its folder, and keeps links between documents working.
- Kind: situation

### DSH-142: An error page showed data store host, user and server paths to any user.
- Why: A project that failed to open printed the raw internal error, connection details and server folder paths included, to every signed-in browser.
- Must: Pages show only the kind of error and where the detail is kept; only the admin's problem notice carries the error's message, with secrets masked and its size limited.
- Kind: situation

## Stopping and resuming the fleet

### DSH-144: A fleet-wide halt stayed on until somebody remembered it.
- Why: Stopping all syncing was one unconfirmed click with no reason, never expired, and showed only where it was set.
- Must: A fleet halt needs a reason and confirmation, shows on every page for everyone, ends after 24 hours unless extended, and keeps a history.
- Kind: situation

See also, filed under another capability:

- SYN-045 (Sync): Only the editor at the keyboard could clear a tripped safety stop.
