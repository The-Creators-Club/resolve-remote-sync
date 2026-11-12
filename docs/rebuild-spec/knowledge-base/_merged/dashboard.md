# The dashboard

## Overview, menus and finding things

### DSH-001: The home page is an Overview, not the sync page.
- What was going on: The owner found the old menus confusing and ruled "Sync should not be the homepage any more, there should be an 'overview' page".
- What the product must do: Home shows problems, health, a sync summary, each module's status, the version, and quick links to commonly used settings.
- Kind: 2
- State: still open
- From: P19-008

### DSH-002: A Sync menu holds Projects, Transfers and a per-computer view.
- What was going on: The owner wants Projects and Transfers "in a dropdown menu if you roll over 'sync'", with a per-computer view third.
- What the product must do: Sync opens a menu, on hover with a mouse and on tap on touch, offering Projects, Transfers and a per-computer view, each its own page.
- Kind: 2
- State: still open
- From: P19-009

### DSH-003: A Projects page lists every project to open, manage, tick and untick.
- What was going on: The owner asked for "a new 'projects' page where you can see all the projects, click into them to manage them, tick them, untick them".
- What the product must do: One page lists all projects; opening one offers every action on that project, including ticking and unticking it for sync.
- Kind: 2
- State: still open
- From: P19-010

### DSH-004: Settings are grouped by what they do and have their own search.
- What was going on: The owner: "the old settings menu and the menu layout is somehwat confusing"; he wants "UX cleanliness" and a search covering settings only.
- What the product must do: Settings are grouped by purpose, and a search inside Settings finds and opens any setting by name, returning settings only.
- Kind: 2
- State: still open
- From: P19-011

### DSH-005: A search in the menu bar opens any module, setting, project, computer or person.
- What was going on: The owner asked for "a general search in the menu bar", then added "yes the general search should find projects computers and people".
- What the product must do: Typing a name in the menu-bar search finds and opens any module, setting, project, computer or person.
- Kind: 2
- State: still open
- From: P19-012

### DSH-006: Many problems must not swamp the overview.
- What was going on: The owner: many errors must not "visually ruin" the overview, and "I don't like the issues being these card boxes".
- What the product must do: Problems occupy a fixed-size area that scrolls when full, and every scrollbar in the product has the product's own style.
- Kind: 2
- From: P12-029

### DSH-007: An admin can open any person and see what they have and lack.
- What was going on: The owner asked for a per-person drill-down and "a full overview of all the projects being synced, who has what".
- What the product must do: An admin opening any person sees each project they ticked, per computer: what has synced, what has not, and what is missing.
- Kind: 2
- State: outcome not found
- From: P12-035

### DSH-008: The other tools open as pages of the dashboard, with a way back.
- What was going on: The owner wanted b-roll and music to look like the dashboard, carry its header and a way back, and be listed after the dashboard's own pages.
- What the product must do: Every tool opens with the dashboard's header and navigation, is listed after the dashboard's own sections, and returns to the dashboard in one click.
- Kind: 2
- From: P04-023

### DSH-009: The installer link downloads the right build for the visitor's computer.
- What was going on: The owner asked that clicking the installer link download the Windows or Mac installer matching the computer doing the browsing.
- What the product must do: Clicking the installer link downloads the installer for the visitor's operating system at once, with the other one still offered.
- Kind: 2
- From: P06-039

### DSH-010: Builds on offer are listed currently served first, then the vendor's.
- What was going on: The owner: "the top should just be 'currently served' and then underneath it 'available from the vendor'", grouped by kind then platform.
- What the product must do: Where builds are listed, currently served ones come first, then the vendor's offer, then other held versions folded away, each grouped by kind then platform.
- Kind: 2
- From: L08-020

## Each computer's state

### DSH-011: Phones have no hover, so help shown only on hover is unreachable.
- What was going on: Chips, fields and states explained themselves only on mouse hover, clipped at 40 characters, on the page most opened on phones.
- What the product must do: Every explanation of a chip, field or state can be read in full by tap, mouse and keyboard, and no internal reason code is ever shown.
- Kind: 1a
- From: L04-139, H07-099

### DSH-012: A computer with no projects ticked is fine, never an error.
- What was going on: The owner: "A computer having nothing ticked is FINE", repeated after quiet ones were still drawn amber or red or counted as expected to sync.
- What the product must do: A computer with nothing ticked leads with a neutral line and is never an error, warning, alert, blocked state, open issue or expected syncer, even when quiet.
- Kind: 2
- From: P10-008, P11-049, L04-034, H07-058, L10-051, C04-012

### DSH-013: Each computer row shows one headline, with nothing overlapping.
- What was going on: The owner: "very visually cluttered, clean it up" and "text disorderly, overlaying things"; one row repeated a sentence three times and an empty box was "way too big".
- What the product must do: Each computer shows one headline (named fault, out of date, transfer error, nothing ticked, then syncing or idle), its transfer states, details folded, nothing overlapping, boxes sized to content.
- Kind: 2
- From: L08-022, P10-066, P12-044, L10-063

### DSH-014: A computer that syncs nothing by design was shown "sync engine down" for 28 days.
- What was going on: A wired computer works straight on the NAS and syncs nothing, yet its headline and chip judged it like an editing computer.
- What the product must do: A computer whose role syncs nothing never shows a sync fault, chip, headline or alert about syncing; an editor's computer still does.
- Kind: 3
- From: M02-022, C04-015, L10-062, P12-043

### DSH-015: Checks raised alarms about states chosen on purpose.
- What was going on: Alarms fired on a computer that syncs nothing by design, a sharing plan with no differences, a superseded build's failed test, and features switched off.
- What the product must do: A check never alarms on a state chosen on purpose, a feature the site switched off, a plan with nothing to change, or a build already superseded.
- Kind: 3
- From: L04-028, H06-106

### DSH-016: A computer that stopped reporting kept its green dot for a week.
- What was going on: A caught-up computer that went quiet was never "behind", so its last transfer states stayed frozen green.
- What the product must do: A computer with no report for 15 minutes shows amber, after 6 hours red, as not heard from with when it last reported, whatever it last said.
- Kind: 3
- From: L02-023, H07-003

### DSH-017: A laptop that was simply asleep was shown red "upload has stopped".
- What was going on: Every silent computer turned red at 15 minutes, though laptops sleep for hours.
- What the product must do: A quiet computer reads as asleep or not reporting, never as a sync fault, unless it was known to be mid-transfer when it went quiet.
- Kind: 3
- From: H06-016

### DSH-018: A computer red for three hours was reported by no alert.
- What was going on: A check that stayed quiet on purpose about computers with a personal project open also marked them reported, so the last-resort alert skipped them.
- What the product must do: A computer whose sync is red for hours is always reported by some alert, even when other checks deliberately say nothing about it.
- Kind: 3
- From: L07-030

### DSH-019: A computer refusing to sync looked idle with nothing to do.
- What was going on: Signed out, wrong clock, drive absent, disk full, stopped, licence not accepted, nothing shared and offline were each known, yet showed as "idle, 0 queued".
- What the product must do: Each computer shows one plain sentence saying why it is not syncing, the first true cause in a fixed order; "idle" only when working with nothing to move.
- Kind: 3
- From: L01-020, C02-059, H07-016

### DSH-020: A computer whose person was signed out stopped syncing without a word.
- What was going on: A Mac with nobody signed in sent no reports and ignored a queued update for days; elsewhere an expired sign-in silently stopped a computer.
- What the product must do: A computer's sign-in never expires on its own, and a computer with nobody signed in shows "nobody signed in".
- Kind: 3
- From: M02-016

### DSH-021: A computer that could not prove who it is vanished like a switched-off one.
- What was going on: A revoked or unverifiable computer sent nothing the server accepted, so it simply stopped appearing.
- What the product must do: A computer that cannot prove who it is still appears as "cannot sign in", with the reason.
- Kind: 3
- From: H07-043

### DSH-022: A computer read "idle, nothing owed" while a failed upload sat folded away.
- What was going on: Warnings were moved behind a collapsed details control that carried no count, and the headline never asked what was still owed.
- What the product must do: A headline is never calmer than its details; every folded-away warning is counted on the folded control, and "nothing owed" is said only after checking.
- Kind: 3
- From: H06-015, L09-012

### DSH-023: A full editor drive showed as a red dot with no reason.
- What was going on: Free disk space appeared nowhere, and a retired computer's year-old low-disk reading stayed an alarm for ever.
- What the product must do: Each computer's free space shows amber under 10% or 50 GB, red under 5% or 20 GB; never reported or over 48 hours old gives no verdict.
- Kind: 3
- From: L02-048, L04-078

### DSH-024: The dashboard said downloads stopped themselves with 145 GB free.
- What was going on: It read its own under-5% colour on a 4 TB drive as a stop, though the editor app stops only below an absolute 20 GB.
- What the product must do: Why a computer stopped is told only from the reason it reported, at its own threshold; a low-space colour is a warning, never a stop.
- Kind: 3
- From: P10-062, M01-068, L08-033, C03-012

### DSH-025: A computer with a wrong clock vanished or looked signed out.
- What was going on: Ordering and pruning used times the computer supplied, and a far-off clock made a fresh sign-in look expired.
- What the product must do: Freshness, ordering and pruning use the server's own receive time, and an expiry caused by a wrong clock names the clock, not the sign-in.
- Kind: 3
- From: L02-021

### DSH-026: A wrong clock on the NAS must not turn every computer red.
- What was going on: With the server's clock wrong, every computer's last report looked stale, so the whole fleet showed as failing.
- What the product must do: A wrong server clock is reported as itself and never marks healthy computers as stale.
- Kind: 3
- State: outcome not found
- From: H08-031

### DSH-027: An upload stall that healed stayed red for 13 days.
- What was going on: The editor app kept re-sending an old stall record, and the dashboard trusted it though uploads had completed every day since.
- What the product must do: A stall shows only while current: a completed pass in that direction since it began clears it, while a stall with no way to tell stays shown.
- Kind: 3
- From: P12-006, L10-032

### DSH-028: A computer could show "indexing" forever after its work finished.
- What was going on: When finished work is signalled only by the report going quiet about it, a remembered "busy" never clears.
- What the product must do: A computer's busy indicator clears on the first report after its work ends.
- Kind: 3
- From: C02-014

### DSH-029: A page about one computer showed another computer's open project.
- What was going on: It read the person's most recently reporting computer, so a MacBook's page named the project open on the same editor's iMac.
- What the product must do: A page about one computer shows only that computer's facts, and the choice survives refresh; only a page about the person shows their newest computer's.
- Kind: 3
- From: L07-052, L06-028, H05-059

### DSH-030: A count for one project was shown as if it were the whole computer's.
- What was going on: A per-project count was kept per computer, so one project's zero overwrote another's four and admins searched the wrong project.
- What the product must do: Every figure names the project or folder it covers, and one scope's figure never overwrites another's.
- Kind: 3
- From: L09-028

### DSH-031: "Safe to close" was worked out for the person, not the computer it named.
- What was going on: It counted uploads from all of a person's computers but said "this computer", and left out projects still preparing.
- What the product must do: "Safe to close" names the computers that still owe uploads, and is never shown while any project is still preparing.
- Kind: 3
- From: H05-060

### DSH-032: Summary counts contradicted the rows right below them.
- What was going on: "Moving 0 B, nothing ticked anywhere" sat beside 15 files transferring, and a filtered view's counts switched to the whole fleet.
- What the product must do: Every summary count agrees with the rows it summarises, for the same view, and updates when they change.
- Kind: 3
- From: H07-094

## Ticking and unticking

### DSH-033: Choosing what a computer syncs starts from a person, then a computer.
- What was going on: The owner: showing every user at once "would be very unwieldy" in a big company; "it just shows the picker so you can select someone".
- What the product must do: Where an admin sets what a computer syncs, nothing is listed until a person and a computer are chosen, preselected when the site has only one.
- Kind: 2
- State: outcome not found
- From: P10-065, L08-021, P12-033

### DSH-034: A tick that could not be added could not be removed either.
- What was going on: The owner: "animals is ticked but I cannot untick it. They're all greyed out." Refusing new ticks on a wired computer disabled its old tick too.
- What the product must do: An existing tick can always be removed wherever shown; only unticked boxes are locked, with the reason, and a leftover forbidden tick is never reported as an error.
- Kind: 3
- From: C03-053, L01-054, P09-011, H05-071

### DSH-035: Ticking for a person changed all their computers without saying so.
- What was going on: A person-level tick pulled a project to every computer they own, and unticking on one computer could remove it from the others.
- What the product must do: A tick or untick changes only the chosen computer; one covering several computers names each and asks first; a plan change can be undone exactly within an hour.
- Kind: 3
- From: L02-030, H06-126

### DSH-036: A confirmed "this removes the project" re-ticked it instead.
- What was going on: Tick controls only said "flip", so a control drawn before another view changed the plan did the opposite.
- What the product must do: Every tick or untick carries what the person intends, a stale control never does the opposite, and cancelling restores what the screen showed.
- Kind: 3
- From: H07-093

### DSH-037: Ticks flipped on screen but saved nothing, with no error.
- What was going on: A broken page script left checkboxes flipping visually with no request made, unnoticed across ten releases.
- What the product must do: A control that fails to save tells the person so; a change never looks saved when it was not.
- Kind: 3
- From: H04-068, L03-093

### DSH-038: Ticking every project for a new editor tried to put 4 TB on 500 GB.
- What was going on: Ticking checked nothing about size, though each project's proxy size and each computer's free space were known.
- What the product must do: Ticking warns when a project's proxies exceed the computer's free space, naming both figures, and asks before saving; it never refuses.
- Kind: 3
- From: L02-049

### DSH-039: After a tick nothing showed for up to a minute.
- What was going on: Then the transfers view claimed nothing was happening while gigabytes flowed.
- What the product must do: Within seconds of a tick the project shows as getting ready, and as transferring as soon as any byte moves.
- Kind: 3
- From: P02-036

### DSH-040: One click wiped a computer's whole plan with no confirmation.
- What was going on: Clearing a plan, copying one plan over another, revoking a key, setting a password and disabling an account each acted on one click.
- What the product must do: Destructive actions ask first, naming what changes on both sides; copying an empty plan is refused, and a plan copy can be undone.
- Kind: 3
- From: L04-058

### DSH-041: Nobody could tell who unticked a project, or when.
- What was going on: Plan changes, halts, pushed updates, file moves, deletions, publishes and settings overwrote state with no history, with several admins on one dashboard.
- What the product must do: Every change to plans, people, computers, releases or settings is kept in an append-only history of who, what and when, for 180 days, filterable.
- Kind: 3
- From: L02-029, H07-015

## Projects

### DSH-042: Every new project appears for every editor automatically.
- What was going on: A project an editor tried to sync never appeared; the owner wants every new project available to every editor with no admin step.
- What the product must do: A project created on the server or set up from Resolve appears, tickable, for every editor within minutes, with nobody granting access.
- Kind: 2
- From: P02-010

### DSH-043: Project status shows each person's total progress, not one route's share.
- What was going on: Status read "0/1 files, 128b" while hundreds of proxies were local; the owner: show "what percentage of proxies they have, along with all other media".
- What the product must do: Each person's project status is total bytes held of what they should have, proxies and other media, excluding originals that live only on the server.
- Kind: 2
- From: P02-037

### DSH-044: For each project and person, show what is held, missing and moving.
- What was going on: The owner wanted files held and missing, offline in Resolve, proxy-only as normal for remote editors, and above all live speeds and times left.
- What the product must do: Per project and person: files present, missing, offline in Resolve, and every running transfer with speed, files remaining and time left.
- Kind: 2
- From: P02-011

### DSH-045: Project lists nest by folder and start collapsed.
- What was going on: The owner wanted every computer in a project's view, each person's media foldable, and the project list nested by year and series with short names.
- What the product must do: A project's view lists every computer, media folded per person; the project list nests by folder with short names, collapsed except the open project's path, across refreshes.
- Kind: 2
- From: P02-038, C01-029

### DSH-046: Choosing a project's server folder is a real folder browser.
- What was going on: The picker offered only a prefilled list, and linking an existing folder forced a new subfolder: "this is pointless behaviour".
- What the product must do: Setting a project's folder lets a person browse the real server tree and link any existing folder as it is, or create a new one anywhere.
- Kind: 2
- From: P02-005

### DSH-047: A project's server folder, once set, changes only when an admin changes it.
- What was going on: The owner: the folder "should be stored, and fixed, only changed if an admin changes it manually", with the detected value visible.
- What the product must do: Each project's detected folder is shown; once set, only an admin changes it and nothing automatic rewrites it.
- Kind: 2
- From: P02-006

### DSH-048: Projects are linked only on an exact name, never on a guess.
- What was going on: "Event 1 Videos" matched "Creator Profiles Season 1" on the digit; a name sharing two words was linked for good; the owner: "the matcher should be updated".
- What the product must do: A project is linked automatically only on an exact name match with one project; any partial match asks a person, and no guess is stored unconfirmed.
- Kind: 2
- State: fixed, never shipped
- From: P02-007, P14-039

### DSH-049: Orphaned proxies raise one warning per folder, not one per proxy.
- What was going on: A folder moved by hand on the NAS left 56 orphaned proxies, one warning each, two visible at a time; the owner: "one warning per folder ... not one warning per proxy".
- What the product must do: Orphaned proxies raise one warning per proxy folder, naming the first few clips and counting the rest.
- Kind: 2
- From: P10-003, L08-018

### DSH-050: A new project said the server had 0 originals.
- What was going on: New projects waited up to 45 minutes for their turn to be counted, and "not yet counted" was drawn as zero, which reads as empty.
- What the product must do: A new project is counted within a minute, and until then every surface says "counting", never zero.
- Kind: 3
- From: M04-107, C04-043

### DSH-051: New footage took hours to show as on the server.
- What was going on: Checking a few projects per cycle, unchanged ones included, took 3.1 hours to show new footage, and 15.6 hours at 500 projects.
- What the product must do: A file that reached the server shows as on the server within five minutes, at 500 projects as at 5.
- Kind: 3
- State: still open
- From: H08-061

### DSH-052: Clips in a folder borrowed from another project were missing from its totals.
- What was going on: Borrowed files were counted only under the project that owns the folder.
- What the product must do: A project's media figures include files in folders it borrows, labelled as borrowed.
- Kind: 3
- State: still open
- From: L01-087

### DSH-053: A computer's file counts showed files it could not have.
- What was going on: An editor showed 195 of 283 proxies for a project never synced, and one computer showed different counts under two accounts.
- What the product must do: A computer's file counts come only from files found on that computer, and one computer reports under one identity.
- Kind: 3
- State: outcome not found
- From: P02-057

### DSH-054: Finished proxy downloads looked owed because a file list was capped.
- What was going on: A computer's file list was capped at one total, filled by originals first, so up to 523 proxies past the cap looked missing.
- What the product must do: What a computer holds is never cut short so that files look owed; any limit applies per kind and is shown as truncated.
- Kind: 3
- From: P12-008

### DSH-055: Leftovers of a failed download sat as owed uploads forever.
- What was going on: Half-finished download part files, 31.7 GB, were counted as uploads due, though the sync never sends such files.
- What the product must do: Files the sync deliberately never sends are never counted as owed, queued or behind.
- Kind: 3
- From: P12-009

### DSH-056: A folder holding other projects could be made a project, then never synced.
- What was going on: A project mark on a parent folder hid the projects beneath it from the nesting check, so linking succeeded but it never synced.
- What the product must do: A folder that contains a project, or sits inside one, can never be made a project, and the refusal names the nested project.
- Kind: 3
- From: H01-067

### DSH-057: A mistyped project could never be removed from the lists.
- What was going on: Any editor may create a project, deliberately, but nothing removed one; deleting the folder by hand was the only cure.
- What the product must do: An admin can archive a project, removing it from every list without deleting anything; the archive survives rescans, and creating says who can undo it.
- Kind: 3
- From: L04-164

### DSH-058: Creating a project over an archived one said "ok" but left it hidden.
- What was going on: A project created or adopted under an archived project's name succeeded on paper while staying archived and invisible.
- What the product must do: Creating or adopting a project under an archived project's name is refused, saying it is archived, until it is un-archived.
- Kind: 3
- From: H06-116, H07-110

### DSH-059: A project name with an apostrophe broke the confirmations.
- What was going on: Names people type contain apostrophes, quotes and Chinese; pasted into a confirm dialog's code, a quote ended it and a crafted name became script.
- What the product must do: Every action and confirmation works for any name a person can type, shows it exactly, and never runs any of it as code.
- Kind: 3
- From: L10-048, C04-008, H06-060

### DSH-060: A ".." in the folder template created folders outside the project.
- What was going on: One source of the new-project folder template did not filter "..", so every new project wrote folders outside its own directory.
- What the product must do: Folder names from every source of the project template are stripped of ".." and leading separators before any folder is created.
- Kind: 3
- From: L06-039

## Transfers and the queue

### DSH-061: The queue lists only ticked work waiting behind live transfers.
- What was going on: 737 files, 44 GB, from projects nobody had ticked showed as queued; the owner wants "files which are queued on the current sync job, but aren't yet syncing".
- What the product must do: The queue lists, per person and project, files from ticked projects waiting behind running transfers; unticking removes a project from every queue and "behind" mark at once.
- Kind: 2
- From: P02-035, C01-028

### DSH-062: A 400 MB upload appeared nowhere and looked stuck.
- What was going on: Uploads to the NAS showed in no view, and a file finishing between 60-second polls reached neither live transfers nor history.
- What the product must do: Every transfer in either direction shows live while running, progress updates within seconds, and every finished file lands in history.
- Kind: 3
- From: P02-034, C01-032

### DSH-063: A backlog stuck behind an unplugged drive looked like it was draining.
- What was going on: 52 originals, 23.5 GB, sat queued for days as an ordinary upload while the computer had reported its sync drive absent.
- What the product must do: A queued backlog its computer reports it cannot move shows "on hold", the computer's own reason, and since when.
- Kind: 3
- From: P12-007, L10-030

### DSH-064: A long clip name pushed progress and speed off the screen.
- What was going on: Long unbroken names, often Chinese with no spaces, set the table's width and hid the columns the table exists for.
- What the product must do: File names wrap anywhere and show whole on hover or tap; progress, speed and time left stay visible at 390, 1100 and 1600 pixels wide.
- Kind: 3
- From: P12-010, L10-031

## People and computers

### DSH-065: Accounts the product uses for itself appeared as editors.
- What was going on: The owner: "what are these users - this is bad UX for an end user"; the server's own account showed as an editor with a missing key.
- What the product must do: Only real people appear in any list of people; the product's own accounts never do, and get their access without joining the editors' group.
- Kind: 3
- From: C01-108, P06-008

### DSH-066: Approving a second computer seemed to ask for a new username.
- What was going on: Typing the computer's name into the approval box created an editor with no plan, which unshared that computer from every project.
- What the product must do: Approving a computer means choosing its existing owner, prefilled from what it reported; a new person only by explicit choice; one person may own many computers.
- Kind: 3
- From: C03-009, L03-027, P08-005

### DSH-067: A departed editor's computer kept receiving projects.
- What was going on: Nothing could delete a person or a computer, and removing someone by hand left their device on every project share.
- What the product must do: Deleting a person removes accounts, devices, shares and sessions, all or nothing; removing one computer says plainly it is not a revocation while the person remains.
- Kind: 3
- From: L03-050

### DSH-068: A dead or departed computer vanished while still holding projects.
- What was going on: Its status expired after 30 days, or a computer limit deleted the oldest record, while its plan and shares stayed active.
- What the product must do: A computer unseen 7 days is listed as lost with the projects it holds; one holding ticks or shares is forgotten only by an admin, never automatically.
- Kind: 3
- From: L02-024, L04-166

### DSH-069: A retired laptop mailed the owner the same alarm every day.
- What was going on: A computer silent three weeks raised the same daily error 21 times, nothing said it could be removed, and the owner learned to ignore alerts.
- What the product must do: A computer silent 14 days is reported once more, then stands as one "forgotten?" notice offering to forget it, until it reports or is forgotten.
- Kind: 3
- From: H07-143, L04-064

### DSH-070: Two computers cloned from one disk fought over one identity.
- What was going on: A copied disk carries the same identity and sync device, so each report took the other's record and plan, and sharing never settled.
- What the product must do: Two computers claiming one identity both stay visible and flagged, with how to reset the newer; a rename counts only once the old name is silent five minutes.
- Kind: 3
- From: L03-022, H07-042, C03-019, L02-069

### DSH-071: A renamed computer lost its plan or its outstanding commands.
- What was going on: Commands were filed under the computer's name, and a rename onto an existing name deleted that computer's plan.
- What the product must do: A renamed computer keeps its plan, history and outstanding commands; clones never get each other's commands; a rename onto another's name changes neither plan and warns.
- Kind: 3
- From: H06-010, L01-066

### DSH-072: An admin could not get diagnostics without the editor's help.
- What was going on: Diagnostics went only to the broken computer's clipboard, relying on a non-technical editor to send them.
- What the product must do: An admin can ask any reporting computer for its diagnostics and receive them with no editor action; one whose transfers fail sends them itself, at most hourly.
- Kind: 3
- From: L02-051, H07-017

### DSH-073: Pushing to a laptop shut in a bag looked like a live push.
- What was going on: Update, resume and ask-why answered "ok" for a computer last heard from nine days ago, and the queued row never moved.
- What the product must do: A command to a computer says when it will apply and when the computer was last heard from, warning if long ago, without refusing.
- Kind: 3
- From: L04-148

## Reports from computers

### DSH-074: Report fields the server did not know were silently thrown away.
- What was going on: Nine Resolve health fields, such as "Resolve wedged 40 s", and later whole sections were sent on every report and dropped unseen for weeks, three times over.
- What the product must do: Every field a computer reports is stored and shown or named loudly as unknown; a section no longer sent clears the old one; never sent shows nothing.
- Kind: 3
- From: L06-032, H05-032, L04-035, L02-022, C02-015, L01-008

### DSH-075: One bad field got a computer's whole report refused, cutting it off.
- What was going on: A number where text was expected, over-long error text, over 64 projects or over 8 MB refused every report, and the reply is the computer's only channel for stops and updates.
- What the product must do: A report is never refused whole: a wrong, unknown or oversized part is trimmed or dropped and named, the rest kept, its commands delivered, the computer still listed.
- Kind: 3
- From: H07-008, H06-117, M02-075, H05-033, L07-016, H04-053, C01-047

### DSH-076: Computers re-sent unchanged file lists every minute.
- What was going on: Each computer re-sent thousands of file names every 60 seconds though they changed every 2 to 5 minutes, and the server rewrote every row.
- What the product must do: Large file lists are sent and stored only when they change, with an occasional full resend so the server converges after a restart.
- Kind: 3
- From: H04-039

### DSH-077: A momentary empty listing made the server treat projects as deleted.
- What was going on: The NAS sync service restarted empty or a volume was not mounted yet, so projects were deactivated and their inventory wiped; the later refusal never reached the owner.
- What the product must do: A pass that would deactivate over a quarter of projects or drop over 90% of a project's files is refused, keeps the old data, and stays on the home page until resolved.
- Kind: 3
- From: L02-025, L03-023

### DSH-078: Facts the system relied on broke silently and were found by accident.
- What was going on: A tick never shared to its computer, a project folder renamed on the NAS, a cloned disk and an impossible update floor were each checked only when written.
- What the product must do: Every cycle compares plans with actual sharing both ways and names each broken fact, and any device awaiting approval over 24 hours, with consequence and fix; it never repairs.
- Kind: 3
- From: L03-018, L02-070

## Problems the server finds

### DSH-079: The server diagnoses itself as far as it can.
- What was going on: The owner: "make the server as self-diagnosing as possible. Any errors should be flagged, the diagnosis should be as clear as possible"; refusals had reached only a log.
- What the product must do: Every problem the server finds shows on the home page with a plain next step, and comes back if dismissed while still true.
- Kind: 2
- From: L02-066

### DSH-080: Problems that have gone away leave without anyone clicking dismiss.
- What was going on: The owner: "if they are resolved they should go away without needing dismiss to be clicked"; one-off errors and outdated warnings stayed open for weeks.
- What the product must do: Every problem has a rule that closes it (cause gone, a later success, or 24 quiet hours for one-off errors), and warnings about unknown data are re-judged after a server update.
- Kind: 2
- From: L10-022, P12-019, C04-002, L08-019

### DSH-081: Every fix a page suggests can be done from where the person is.
- What was going on: The owner: "Make this a click-through wizard, this is too complex for most users"; messages said "edit a setting and redeploy", named internal keys, guessed causes or named hidden pages.
- What the product must do: Every problem names its real cause, or "cannot tell", and a fix that is a button, a link that goes there, or "ask whoever installed this server", never a command.
- Kind: 2
- From: L05-009, C02-043, P06-028, L04-077, L11-052

### DSH-082: The footage-outside-the-tree warning must name the project.
- What was going on: The owner: "this warning should say which project. the project might be an editor's personal project which they don't want to sync."
- What the product must do: The warning names the project; a project tied to no synced project raises nothing; when the open project is unknown it says "could not check", never "fine".
- Kind: 2
- From: L05-071

### DSH-083: A check that could not run looked the same as one that passed.
- What was going on: Checks that crashed, could not reach the NAS, could not see their evidence or were never evaluated showed as fine, and some closed findings with "no action needed".
- What the product must do: Every check reads OK, broken, not checked (with the reason) or failed to run, each visibly different, and only a real verdict opens or closes a problem.
- Kind: 3
- From: H06-014, L03-019, L09-020

### DSH-084: A network check that could not read the network mailed "cleared".
- What was going on: Checks of the server's own network sent an all-clear when the network state could not be read at all.
- What the product must do: A check that cannot read its evidence reports "could not check", never "cleared" or OK, and sends no all-clear mail.
- Kind: 3
- State: fixed, never shipped
- From: L11-007

### DSH-085: A check failing now still showed OK because it once passed.
- What was going on: Any check evaluated once ever showed OK, including one now failing every cycle or no longer running at all.
- What the product must do: A check shows OK only if its latest run passed recently; one failing shows failed, and one not run recently shows not checked.
- Kind: 3
- State: fixed, never shipped
- From: H08-030

### DSH-086: The owner was mailed "cleared" about problems nobody had fixed.
- What was going on: Anything absent from a scan counted as recovered: another project opened, a cap of 20 or 40 per kind, a recency window, a check with no verdict.
- What the product must do: A problem closes only when a complete check found it gone; capped, filtered, skipped or unchecked subjects stay open and mail nothing; a display limit never limits what is known.
- Kind: 3
- From: L06-048, H05-004, L08-017, L07-032

### DSH-087: A background pass that refused or skipped its work counted as success.
- What was going on: A safety brake froze all project unticks for days while health showed fine, and its only trace was a log line lost on restart.
- What the product must do: A background pass that refuses or skips work shows as incomplete with its reason on the home page and in alerts, until a clean pass clears it.
- Kind: 3
- From: L02-028

### DSH-088: A scheduled server task could stop running while the home page looked fine.
- What was going on: A task that last ran fine then stopped showed nothing amiss, while a fresh install's first check ran 10 minutes in and a 3-minute rule flagged it stopped.
- What the product must do: A task past its usual interval shows overdue and raises an alert; a fresh install running on schedule is never flagged, but work dead at start is, within minutes.
- Kind: 3
- From: L10-061, L09-030

### DSH-089: Everything wrong was spread across separate places.
- What was going on: Notices, alerts, broken cross-checks and missing protections each lived apart, each half-answering "is my fleet all right".
- What the product must do: Everything the server knows is wrong appears in one list ranked error, warning, then not checked, with each source's words and links; one broken source never blanks it.
- Kind: 3
- From: H07-089, L04-160

### DSH-090: An optional feature that failed simply vanished from the menu.
- What was going on: B-roll or music search failing to start lost its link with no reason shown, and a feature whose NAS share dropped at night stayed advertised as working.
- What the product must do: A feature that is on but unavailable shows broken with its reason; one whose data disappears shows degraded within one check; unreadable status reads "not checked".
- Kind: 3
- From: L06-052, H07-144, L04-079, H04-051

### DSH-091: Cleared notices were kept for ever.
- What was going on: Notices had no retention, so cleared rows about computers long gone piled up; any cleanup also had to spare open problems however old.
- What the product must do: Cleared notices are deleted after 120 days; an open notice is never removed by any cleanup, however old.
- Kind: 3
- From: L06-047

### DSH-092: A server error notice pointed at a log a server update had deleted.
- What was going on: The notice held only the error's type and "see the server log", but the log does not survive a server update.
- What the product must do: A server-error notice carries its own error type, message and innermost few code locations, bounded in size, with every key or token masked.
- Kind: 3
- From: L08-015

### DSH-093: A slowness warning blamed the wrong cause.
- What was going on: A slow but harmless NAS scan was reported as holding the data store, and slow-write timing counted queue waits and advised editors to untick.
- What the product must do: A slowness problem measures only how long the lock was held, names the real holder, never advises an editor to untick, and clears once a later check passes.
- Kind: 3
- From: L09-011, L10-072

### DSH-094: Alerts counted deliberate restarts as crashes.
- What was going on: Intentional restarts and a test abort counted as crashes, and an alert fired when the studio ran a newer server than the vendor offered.
- What the product must do: Alerts never count a deliberate restart as a crash, and never flag running a newer release than the vendor offers.
- Kind: 3
- State: still open
- From: M01-070

### DSH-095: "I have backed it up" was recorded, but its line stayed red.
- What was going on: The line showed the last check, run every 15 minutes, while the click only updated stored data.
- What the product must do: Acknowledging a problem updates the line it acknowledges, and the warnings it raised, immediately.
- Kind: 3
- From: P10-067, L08-024

### DSH-096: Error records from two features merged, naming a page that does not exist.
- What was going on: Errors inside b-roll and music were filed under an inner address both share, not the address a person actually used.
- What the product must do: Every error record names the full address that failed, keeps features apart, and never stores the secret part of a client share link.
- Kind: 3
- From: L10-009

## Alerts by mail

### DSH-097: Alert mail comes as one digest, not one mail per alert.
- What was going on: Turning mail alerts on sent eleven messages in one minute, and every unfixed error mailed again daily; the owner: "I'm getting spammed with emails now."
- What the product must do: One message per check: new problems worst first, unfixed ones one line each with days open, recoveries included; the first message says it is a catch-up.
- Kind: 2
- From: L05-028, M02-073

### DSH-098: The admin chooses which kinds of alert are mailed.
- What was going on: The owner: "I want to be able to select which types of email alerts the admin gets. What types of warnings, etc."
- What the product must do: Each alert kind can be switched on or off for mail by an admin, and a switched-off kind still shows on the dashboard.
- Kind: 2
- State: outcome not found
- From: P13-028

### DSH-099: Problems reached nobody unless the owner happened to look.
- What was going on: An editor's sync was dead 18 hours before anyone noticed; alerts had nowhere to go by default and said nothing about it.
- What the product must do: Detected problems reach a named person within an hour, unasked, repeated daily while true, with recovery notes and a weekly report; no destination is a fault until set or skipped.
- Kind: 3
- From: M02-074, H07-001, L02-067

### DSH-100: Alert delivery showed as working before anything was ever sent.
- What was going on: A weekly report "generated, not sent" with no mail set up counted as proof, so a mistyped mail server read green for a week.
- What the product must do: Alert delivery shows as working only after a real message reached a recipient through that same channel.
- Kind: 3
- From: L06-049, H05-005

### DSH-101: A half-hour mail outage lost the week's report.
- What was going on: A failed send counted its slot as done, and three tries ten minutes apart could not outlast a relay down from 07:55 to 08:40.
- What the product must do: A report, heartbeat or alert whose send fails is retried with a widening gap (about 10 minutes, 1 hour, 6 hours) and delivered late, never dropped.
- Kind: 3
- From: L07-035, L06-050, H05-006

### DSH-102: A failed alert and a failed editor install reached nobody.
- What was going on: An alert that failed to send was never retried or shown, and an editor's failed install was invisible to the admin.
- What the product must do: An alert that cannot be sent shows as undelivered until it goes, and an editor's failed install appears on the dashboard.
- Kind: 3
- State: outcome not found
- From: H08-032

## Settings and setup

### DSH-103: AI providers are tried in the owner's order unless one is pinned.
- What was going on: The owner asked for one place to enter keys or sign in to each provider, with features using "the first which is available".
- What the product must do: Each AI feature uses the first available provider in the owner's order unless an admin pins one; a pinned one unavailable is refused, never replaced; the one in use is shown.
- Kind: 2
- From: P06-025, C02-034

### DSH-104: Connecting an AI provider is a short click-through setup.
- What was going on: Connecting meant installing a program on the server by hand, "too complex for most users", and listing every provider at once was "visually confusing".
- What the product must do: Only active providers are listed, plus "add new": a picker, then a guided setup (notice, verified install, browser sign-in with code, test), with the manual path still offered.
- Kind: 2
- State: outcome not found
- From: L01-052, P06-026, P12-032

### DSH-105: The setup checklist showed placeholders and a step that could never pass.
- What was going on: The owner photographed "TODO waiting on: admin" and "not implemented", and a required step waited on a check that could never pass on that site.
- What the product must do: The setup checklist never shows placeholder text; every item is a real check naming its next action, and no required step depends on an unanswerable check.
- Kind: 2
- From: C02-044

### DSH-106: Settings saved on the dashboard were ignored by the server itself.
- What was going on: Brand, project folder templates, shared folders, NAS kind and a feature switch reached computers while the server kept its install-time values.
- What the product must do: A saved setting takes effect everywhere, server included, within seconds and without restart, from one source; core features never depend on an optional feature's switch.
- Kind: 3
- Check: One same-day source says this was still open; does any setting still need a restart, or have a second source?
- From: L01-071, H04-047, H03-028

### DSH-107: The owner could not change the dashboard address in settings.
- What was going on: The owner: "it won't let me change the dashboard url"; the field locked once any value had ever been stored, though nothing supplied one.
- What the product must do: A setting is locked only while a live source supplies it now; a doubtful check leaves it editable, and a differing value elsewhere is shown beside it.
- Kind: 3
- From: C03-055, L03-079, P09-013

### DSH-108: A computer's own setting was greyed out with no hint where to change it.
- What was going on: Wired versus remote is each computer's own setting, but the dashboard greyed its boxes without saying so.
- What the product must do: Wherever a computer's own setting is shown read-only, visible text says where to change it on that computer.
- Kind: 3
- From: L04-142

### DSH-109: Importing a settings file overwrote everything with no preview or undo.
- What was going on: Pasting an older or another site's settings replaced every value, the project drive letter and tree name included, with no record of the old ones.
- What the product must do: A settings import shows what will change and asks first, and keeps the replaced values so the change can be undone.
- Kind: 3
- From: L02-073

### DSH-110: Undoing a settings change emptied lists instead of restoring them.
- What was going on: Undo restored blank instead of the default for settings never set, and its confirm quoted an older change then reverted the newest.
- What the product must do: Undoing a settings change restores exactly the earlier effective values, and its confirm names the change it will actually undo.
- Kind: 3
- From: H06-105

### DSH-111: After a successful sign-in, the test and other features still said failed.
- What was going on: The setup dialog collapsed whenever the page refreshed its list, and the test and the downloader kept a stale "failed" after sign-in.
- What the product must do: A setup dialog survives page refreshes, and a successful sign-in is seen at once by its test and every feature using it.
- Kind: 3
- From: P06-027

### DSH-112: A customer could not see whether their server and apps were current.
- What was going on: Only the vendor could compare versions; a customer had no view of their versions against the newest offered.
- What the product must do: An admin sees server and app versions against the newest offered and how many computers run each; an offer not checked reads "not checked", never "up to date".
- Kind: 3
- From: L05-015

### DSH-113: An admin's setup button answered only "internal error".
- What was going on: The free-space check before installing a helper could itself crash, and the button had no last-resort answer.
- What the product must do: A failing admin button names what failed, that nothing was half-installed, and the fallback; a check that cannot finish is a refusal, never a yes.
- Kind: 3
- From: L08-016

## Pages that refresh and answer clicks

### DSH-114: A browser scrolls to a section link only once, while the page loads.
- What was going on: Parts that arrive a moment later are never scrolled to, so the link lands at the top, and a repeat press of the same link did nothing.
- What the product must do: A link to a section scrolls there once it arrives, every time it is pressed, without fighting a reader who has already scrolled.
- Kind: 1a
- From: L04-043, H07-102

### DSH-115: Returning to a page reopens it where the person left it.
- What was going on: Each page change reloaded a long page at the top; the owner: "it should remember your position from the last time".
- What the product must do: Returning to a page restores its scroll and open sections after late parts load, unless the link names a section; positions expire after 8 hours.
- Kind: 2
- From: L05-023

### DSH-116: The answer to a click appeared far from the button pressed.
- What was going on: Answers were drawn at the top of long pages or on another row, or lost when parts refreshing every 15 seconds took their slot.
- What the product must do: An action's answer appears in view beside the control pressed, or on the page if it is gone, replacing earlier answers, even while other parts refresh.
- Kind: 3
- From: H05-073, L06-061, H06-083, L04-140, H07-092

### DSH-117: Long-running buttons showed nothing for up to two minutes.
- What was going on: Create, publish and check-now gave no sign of working, so people clicked again and started a second multi-megabyte download.
- What the product must do: Every control that can take over a second shows it is working and disables itself until the answer arrives.
- Kind: 3
- From: L04-057

### DSH-118: Self-refreshing pages wiped what an admin was typing.
- What was going on: Parts redrawn every 10 to 60 seconds cleared typed text, closed open lists, pickers and toggles, and erased one-time passwords before they were copied.
- What the product must do: A refresh never discards typed input, an open list, picker, sheet or toggle, an action's pending answer, or a one-time secret; every secret has a copy button.
- Kind: 3
- From: H06-082, H07-090, L04-087

### DSH-119: The dashboard said "updated 4s ago" while unreachable for an hour.
- What was going on: Failed refreshes were not reported, and the freshness stamp was drawn once per page load.
- What the product must do: Every page shows when its data last updated successfully and says plainly when updates are failing.
- Kind: 3
- From: L04-055, H07-091

### DSH-120: An expired session pasted the sign-in page into the page's own panels.
- What was going on: Self-refreshing parts inserted the sign-in page every few seconds, and a 12-hour-old tab's first click said "login required", reading as a permissions fault.
- What the product must do: When a session expires, the next refresh or action takes the person to sign in and back to the page, and a batch of clicks stops at the first failure.
- Kind: 3
- From: H01-069, L04-147

### DSH-121: A program calling with an expired sign-in got the sign-in page.
- What was going on: Programs and audio players handed a sign-in page fail with cryptic messages on every poll and never learn the session expired.
- What the product must do: A request that is not a page, without a valid sign-in, gets a clear machine-readable "signed out" answer, never the sign-in page.
- Kind: 3
- From: C03-036

### DSH-122: One busy or failed source turned a whole page into an error.
- What was going on: A brief NAS hiccup blanked a whole panel, computers awaiting approval included, and a busy data store could have shown "nobody suspended" as fact.
- What the product must do: A failed source spoils only its own part, which says "could not read this right now" with its last known state and time; the rest renders, no empty answer stated.
- Kind: 3
- From: H02-001, L07-028

### DSH-123: One stored time without a time zone broke a page for days.
- What was going on: A single sign-in record carried a time with no zone, and formatting "how long ago" crashed every render of the page.
- What the product must do: A badly formed stored value spoils at most its own cell, and a stored time with no zone is read as UTC.
- Kind: 3
- From: L03-028, C03-005

### DSH-124: A dashboard open on a phone in a pocket kept polling the server.
- What was going on: Hidden tabs kept refreshing every two seconds, slowing the server for the whole studio.
- What the product must do: A hidden page polls nothing, refreshes once when shown again, and polls more slowly on touch devices.
- Kind: 3
- From: C03-044

### DSH-125: The only button that closes an error was red text on a red banner.
- What was going on: Error banners are red and buttons were drawn red, so dismiss was clickable but unreadable on every error.
- What the product must do: Every button and link on any banner is legible against that banner's own colour.
- Kind: 3
- From: L10-021

## Speed under load

### DSH-126: The home page grew slow as the fleet grew.
- What was going on: It ran 1,170 data store queries per load, 2.8 s with 20 computers; each open tab rebuilt it 12 times a minute, about 6 s at 50 editors.
- What the product must do: The home page loads within a second for 20 computers and stays fast at 50 editors and 400 projects; a refresh with nothing changed costs little.
- Kind: 3
- State: still open
- From: H07-104, H08-059

### DSH-127: One slow save froze the dashboard for everyone.
- What was going on: Saves waited up to 5 s (3.07 s measured) while every request queued, and a report rewriting 6,000 rows made 12 clicks fail in 27 minutes.
- What the product must do: While one write waits, every other page and report is answered within a second; "busy" answers at once, background writes wait their turn, and the slow writer is recorded.
- Kind: 3
- State: still open
- From: H08-060, L08-075, M03-065, L04-031

### DSH-128: One admin's long action froze the dashboard for ten minutes.
- What was going on: A publish download of up to 600 s, a music upload of 55 MB files, and editor recalculation at 97% of a core for 4 s ran where every page waited.
- What the product must do: No admin action, upload, search or feature work delays other pages or computers' reports by more than a second; long work runs aside and shows progress.
- Kind: 3
- From: H07-039, L04-059, H02-020, C06-052

### DSH-129: Each edit in the editor recomputed the whole cut.
- What was going on: Recomputing every card's words after each edit took 4 s at 97% of a core.
- What the product must do: Work done per edit scales with the edit, not with the whole cut.
- Kind: 3
- From: C06-052
- Move to: cards-editor

## Phones and the installed app

### DSH-130: A phone zooms the page when a text field under 16 px is tapped.
- What was going on: Phone browsers zoom in on focusing a small input and do not zoom back out, leaving the page sideways.
- What the product must do: Every input on a phone-sized screen has text of at least 16 px.
- Kind: 1a
- From: C03-042

### DSH-131: Chrome's phone emulation hides sideways overflow from width checks.
- What was going on: Under mobile emulation the layout viewport grows to the content, so page width equals window width and overflowing pages pass.
- What the product must do: Phone-width checks compare page width with the visible viewport, not the layout viewport.
- Kind: 1a
- From: H07-097

### DSH-132: An installed phone web app keeps old files until its background script changes.
- What was going on: Cached files are served first and never rechecked, so a redeploy with the same version left stale styles even on hard reload.
- What the product must do: After any redeploy, version changed or not, installed phone pages paint from cache but fetch fresh copies, so the next visit uses them.
- Kind: 1a
- From: H05-072, L06-059

### DSH-133: A browser may stop a page's background worker mid cache refresh.
- What was going on: Unless the worker is told to wait for its background refresh, the browser can stop it first, so a fix never arrives.
- What the product must do: A fix republished without a version change reaches every browser within two visits, slow mobile connections included.
- Kind: 1a
- From: L07-050

### DSH-134: Phone install and offline use need https and fail silently without it.
- What was going on: Offline workers, "Add to Home screen" and Android's app wrapper all need a secure address and do nothing without one; Android installs only from https.
- What the product must do: The dashboard is reachable on https wherever phones use it, every "open dashboard" link follows the site's published address, and a check names any failing install step.
- Kind: 1a
- From: C03-039, M03-049

### DSH-135: On a phone every page scrolled sideways and controls were tiny.
- What was going on: Pages built for 1280 px overflowed by up to 1500 px at 390 px, one went black, and the checkbox that starts a real sync was 13 px.
- What the product must do: At phone and tablet widths no page scrolls sideways or hides content, tables become labelled rows, touch targets are at least 44 px, text at least 12 px.
- Kind: 3
- From: C03-043, H07-096

### DSH-136: On a phone the projects to tick were 10,000 pixels down the page.
- What was going on: The phone shortcut for ticking landed where the project list came last, and the "tick a project" hint did not link to it.
- What the product must do: On a phone, ticking a project is one tap from every place that asks the person to tick one.
- Kind: 3
- From: H07-098

### DSH-137: The installed dashboard could show a stored copy as live, with the last user's name.
- What was going on: A cached page served offline would claim footage was syncing during a halt, and the saved offline page kept the old user, admin menu and form token.
- What the product must do: Offline, the installed app shows an "offline" page carrying no user, role or form token; status, data and sign-in pages are never served from a stored copy.
- Kind: 3
- From: C03-045, H04-021

## Security of pages

### DSH-138: Browsers send "Origin: null" from places that are not this site.
- What was going on: Sandboxed frames, data and blob documents and some redirect chains send "Origin: null", and it was let through like a missing origin.
- What the product must do: On anything that changes data or drives Resolve, "Origin: null" without a matching referrer is refused; only a truly absent origin may pass.
- Kind: 1a
- From: L06-038

### DSH-139: An endless upload with no sign-in could crash the dashboard.
- What was going on: The size limit trusted the declared length, and the body was read before the credential was checked, so a streamed endless body exhausted memory.
- What the product must do: Credentials are checked before any body is read, and reading stops at a hard size limit whatever length is declared.
- Kind: 3
- From: H04-018

### DSH-140: A sign-in exemption outlived the page it was made for.
- What was going on: A deleted page's exemption stayed, so anything later added at that address would be open to anyone.
- What the product must do: An exemption from sign-in goes with the page it exists for; nothing beyond the named pages is reachable without signing in.
- Kind: 3
- From: L07-044

### DSH-141: The help viewer served every internal document to anyone signed in.
- What was going on: Every document in the source tree, the bug ledger included, was browsable by customers.
- What the product must do: The help viewer serves only documents published for that reader's audience, refuses any path outside its folder, and keeps links between documents working.
- Kind: 3
- From: L05-022

### DSH-142: An error page showed data store host, user and server paths to any user.
- What was going on: A project that failed to open printed the raw internal error, connection details and server folder paths included, to every signed-in browser.
- What the product must do: Pages show only the kind of error and that the server log has the detail, never raw internal error text, admins included.
- Kind: 3
- Check: Should the problem notice for a server error still carry its message and code locations (DSH-092), given pages never show raw error text?
- From: L09-023

## Stopping and resuming the fleet

### DSH-143: An admin can resume a computer's stopped downloads from the dashboard.
- What was going on: The admin had checked the NAS and knew the trip was harmless, but only the editor at that computer could clear it; the owner asked for a remote resume.
- What the product must do: An admin can resume a stopped computer's downloads from the dashboard, and the resume applies only to the stop in force when pressed.
- Kind: 2
- From: P07-011

### DSH-144: A fleet-wide halt stayed on until somebody remembered it.
- What was going on: Stopping all syncing was one unconfirmed click with no reason, never expired, and showed only where it was set.
- What the product must do: A fleet halt needs a reason and confirmation, shows on every page for everyone, ends after 24 hours unless extended, and keeps a history.
- Kind: 3
- From: L02-071

## Sealed

### DSH-S01: Android hid the address bar only for a verified site.
- What was going on: An Android web-app wrapper hides the bar only if the site publishes a statement naming the app and its signing key fingerprint; otherwise it silently falls back.
- What the product must do: The site publishes that statement, allows two signing keys during a hand-over, and a check reports whether it verifies.
- Kind: 1b
- Tool: Android Trusted Web Activity (Digital Asset Links)
- From: C03-040

### DSH-S02: The assistant tool said "signed in" about a different account than the one billed.
- What was going on: With an API key in its environment the tool answers about the key and bills it; its sign-in command is "auth login"; its Linux build is 313 MiB.
- What the product must do: A sign-in check reports the same account the real work will use, and nothing billable runs under an account other than the one shown.
- Kind: 1b
- Tool: Claude Code CLI 2.1.x (auth login, setup-token, HOME)
- From: C02-035

### DSH-S03: An assistant tool was larger than an assumed 300 MiB download cap.
- What was going on: The tool is 313 MiB and its publisher's manifest lists exact size and checksum; the other vendor's Linux tool ships only as a static build with a checksum list.
- What the product must do: Download size limits and file names come from the publisher's manifest, and sign-in flows are tried on the real host before use.
- Kind: 1b
- Tool: Claude Code and Codex command-line tools
- From: L01-053

### DSH-S04: An error banner sent with another page update stayed out of view.
- What was going on: When one reply updates both the page and an error strip elsewhere, the update event fires once per element, and the first used up the scroll target.
- What the product must do: Any error banner a reply puts on the page is scrolled into view with its button, however many parts that reply updates.
- Kind: 1b
- Tool: htmx out-of-band swaps
- From: L07-051

### DSH-S05: The NAS sync engine answered normally with zero folders after a failed load.
- What was going on: Restarted with a default or unloadable configuration, it answers success with a valid device id and an empty folder list.
- What the product must do: A folder list that suddenly empties is treated as a broken sync engine, never as every project removed.
- Kind: 1b
- Tool: Syncthing (REST config after a failed config load)
- From: L02-027

## Removed

- C02-048 | no longer applies: about where the old dashboard's menu put updates and admin pages, which is being redrawn
- P06-037 | no longer applies: the old menu and gear layout is being redrawn
- C02-049 | superseded by DSH-001
- P06-038 | superseded by DSH-001
- P06-035 | no longer applies: the bracket-label button style is gone

