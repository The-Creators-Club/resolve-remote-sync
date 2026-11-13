# The whole product: what real use taught

91 lessons. Each is one rule the product can be tested against: what a person saw (the heading), why it happened, and what the product must do. Kinds: *given* is a fact about something the studio has whatever is built; *ruling* is the owner's decision; *situation* is something the product must survive.

## Could not check, refusals and nothing silent

### ALL-052: The owner: "no clips match" appeared while the page was still loading.
- Why: The owner: "there is no 'loading' - it just says no clips match your current filter"; the empty message appeared before any data arrived.
- Must: Until data arrives the page says it is loading; a failed load says so with a retry; "nothing found" appears only after a real answer.
- Kind: ruling

### ALL-090: The owner: "A computer having nothing ticked is FINE."
- Why: The owner: "I've already made this clear in the past. A computer having nothing ticked is FINE"; it kept appearing as blocked, amber or an open issue.
- Must: A computer with no projects ticked shows as normal on every surface: no error, warning, blocked reason, red or amber state, alert or notice; real faults keep theirs.
- Kind: ruling

### BRD-035: One action's several refusals stacked identical red notices.
- Why: Each refused change raised its own red 8-second notice, so a single turn stacked several identical ones on screen.
- Must: Several refusals from one action show as one summary with a count, the details kept where they can be read.
- Kind: situation

### ALL-050: "Could not check" was shown as fine, zero or cleared.
- Why: A crashed scan read "fully covered", a closed Resolve showed zero problems, a failed check mailed "cleared", and a release gate passed an empty error list.
- Must: Anything not checked shows "not checked" or "cannot tell", never OK, zero or passed; earlier problems stay open, and any gate meeting it refuses.
- Kind: situation

### ALL-051: "Could not read" was acted on as "nothing there".
- Why: An unplugged drive, unmapped share or one failed NAS listing erased records, zeroed counts, excluded a project for good, or labelled stale data live.
- Must: An unreadable source is never empty: records survive, counts keep their last value marked stale, the safe side is taken, and the next good read recovers.
- Kind: situation

### ALL-053: An optional feature a site lacks showed broken parts or a permanent "not checked".
- Why: Sites without an optional feature saw a "not checked" line about it forever, teaching people to ignore that line where it matters.
- Must: When a feature is not enabled or present, its controls, chips, banners and checks are hidden and the rest of the page is unchanged.
- Kind: situation

### ALL-054: Whole features failed for weeks with no sign anywhere.
- Why: Shared LUTs, proxy attaching and computer-run jobs failed silently; a missing language part made search literal-only from day one; a feature hid behind an undiscoverable drag.
- Must: Every feature shows somewhere a person looks whether it works, a missing part is named where its feature is used, and nothing needs a hidden gesture.
- Kind: situation

### ALL-055: Every assistant failure read as one vague refusal.
- Why: The assistant being slow to start, signed out or not installed all showed the same refusal, while settings claimed a working sign-in.
- Must: When the assistant cannot be used, every affected feature says which (slow to start, signed out, not installed), and settings never claims a working sign-in.
- Kind: situation

### ALL-056: A refusal hid its reason behind a generic line.
- Why: Refusals read "this page has stopped updating", network errors posed as answers, errors vanished in 5 seconds, and computed reasons stayed in logs.
- Must: Every refusal or failure shows its real reason to the person it affects, names a network failure as one, and stays on screen until read.
- Kind: situation

### ALL-057: A button that quietly does nothing reads as broken.
- Why: A panel toggle did nothing until data existed, and a loudness toggle did nothing silently when no levels were loaded.
- Must: Every button visibly acts or says why it cannot; a panel toggle always opens its panel, empty if need be, saying how to start.
- Kind: situation

### ALL-058: Actions reported success when nothing changed or parts had failed.
- Why: A copy said "finished" after listing failures, a setting was saved where it was never read, and a download was marked done after part failed.
- Must: Success shows only once the change is confirmed; partial failure is never plain success, progress counts only successes, and nothing a retry needs is deleted.
- Kind: situation

### ALL-059: A rehearsal told people things had changed.
- Why: A rehearsal uninstall said removal failed and to delete by hand, and rehearsals showed "Copying 0 B of 800 GB".
- Must: A rehearsal says "checking" or "would", never claims or demands a change, and counts exactly what the real run would do.
- Kind: situation

### ALL-060: Long work showed nothing, and clicks went unacknowledged.
- Why: Setup ran 30 minutes with a blank window, sign-in froze 15 seconds, a two-minute button gave no feedback, and indexing printed nothing for six hours.
- Must: Every click is acknowledged at once, and any action over a second shows that it started and then its progress.
- Kind: situation

### ALL-061: A question window opened out of sight, so a run seemed to do nothing.
- Why: The owner: "run it again there is no popup", then "there was actually a popup I just had to dismiss it on the previous runs".
- Must: Any window waiting for a person's answer comes to the front and stays on top until answered.
- Kind: situation

## The rebuild itself

### ALL-001: The owner: "the keyword is elegance", the fewest moving parts every time.
- Why: The owner set one guiding principle: "the keyword is elegance. We go for the most elegant option with the least moving parts every time".
- Must: Any part whose removal leaves every required behaviour intact is removed; elegance never removes a feature, a ruling or a lesson.
- Kind: ruling

### ALL-002: The owner: nothing about how the old product was built reaches the rebuild.
- Why: The owner: "NOTHING about how this product was actually built should make it into the rebuild document, only what it achieves", since old tools and counts bias a new design.
- Must: The rebuild brief names no old tool, internal name or count of parts; a reader of it cannot tell how the original was built.
- Kind: ruling

### ALL-003: The owner: one clean rebuild of the whole thing, footage sorter included.
- Why: The owner wants "a completely clean rebuild of the whole thing", "without having any bias as to how the original architecture was built"; "This rebuild should include footage sorter, too."
- Must: Sync, dashboard, Timeline Cards and the footage sorter are specified and built together from what people do, never from the old design.
- Kind: ruling

### ALL-004: The owner: every component is a module that can be switched on and off.
- Why: The owner wants "every individual component to be a module" that "slots into the dashboard, so each one can be maintained, updated, enabled and disabled individually".
- Must: Each module is enabled or disabled on its own without affecting others; switching one off hides it and stops its work but deletes nothing.
- Kind: ruling

### ALL-005: The owner: one repository, one self-contained, separately versioned folder per module.
- Why: The owner chose "one repository with a self contained separately versioned folder per module" over separate codebases.
- Must: One repository holds the core and every module; each module's folder carries all its own parts and its own version number.
- Kind: ruling

### ALL-006: The owner: most features stay, but every overlap is put to him.
- Why: The owner: "most of these I would want to keep", but "Six places to tick a project is an example of something that could be removed. The questions should still be asked."
- Must: Each capability is built once; whether a duplicate way into it survives is the owner's decision, made one overlap at a time, never assumed.
- Kind: ruling

### ALL-007: Every feature ships, from one build, switched on per studio.
- Why: The owner ruled "Keep every feature and get it ready", and that parts one customer lacks are switched off by a setting, never forked into another build.
- Must: One build serves every studio with every feature working; a feature a studio lacks is dormant by setting, and client share links check the studio holds the rights.
- Kind: ruling

### ALL-008: The supported platforms are one fixed, published list.
- Why: Nothing said what the product runs on; the owner's list is Windows 10 22H2 or 11 x64, Apple silicon Macs, Resolve Studio 20, TrueNAS 25 or 26, Synology DSM 7.2.1.
- Must: The supported-platform list is published, and every install check agrees with it exactly.
- Kind: ruling

### ALL-009: A feature switched off kept its work running on the server.
- Why: Switching the YouTube downloader off left its download work still running on the server.
- Must: Within a minute of a feature being switched off, none of its work is still running anywhere.
- Kind: situation

## The look

### ALL-010: iOS zooms the whole page when a form field's text is under 16 px.
- Why: On an iPhone, focusing an input whose text is smaller than 16 px zooms the whole page.
- Must: Every form field on a phone uses at least 16 px text.
- Kind: given

### ALL-011: With Windows animation effects off, every page is in reduced-motion mode.
- Why: Chrome on Windows reads the system "animation effects" switch; with it off, every page is told to reduce motion, so animations a page relies on never run.
- Must: Everything works with reduced motion on, showing final states at once, and nothing waits for an animation that reduced motion skips.
- Kind: given

### ALL-012: Resolve's dark clip colours vanish on a dark card.
- Why: Clip colours are Resolve's own sixteen; Navy measures only 2.59:1 against a dark card, so the swatch needs a ring to be seen.
- Must: Clip colours are never changed, and every one of Resolve's sixteen stays at least 3:1 visible against whatever it sits on.
- Kind: given

### ALL-013: One raw control character in a page script killed the whole page.
- Why: Browsers turn a raw NUL inside an inline script into a replacement character, so code that passed every non-browser check failed to compile and the page died.
- Must: Page scripts carry no raw control characters other than tab, CR and LF, and every page change is run in a real browser before release.
- Kind: given

### ALL-014: A phone installing a web app fetches its manifest and icon without signing in.
- Why: When a phone installs a web app it fetches the manifest and icon with no sign-in cookie, so a redirect to sign-in breaks installing.
- Must: Every installable page's manifest, icon and offline script load without sign-in, while the pages and data behind them still require it.
- Kind: given

### ALL-015: The owner: "The whole product takes the timeline cards editor's look".
- Why: The owner: "I really like the way the timeline cards rebuild looks"; a sorter restyled to an older look got "this UI does not look like the timeline cards redesign at all".
- Must: Every surface (dashboard, searches, downloader, sorter, the editor's computer app) uses the editor's colours, type, panels, buttons and status line; no older look survives.
- Kind: ruling

### ALL-016: The owner: one look only, with no switch to another.
- Why: Several looks were offered; the owner: "retire the rest, they shouldn't even be options" and "we don't need to maintain the switch to the old UI".
- Must: The product has one look, with no setting, saved preference, old link or page that shows another.
- Kind: ruling

### ALL-017: Green means backed up and nothing else; each colour has one job.
- Why: Assigned clips were green, colliding with "backed up"; the owner wanted the product's red, "red instead of orange", as the highlight.
- Must: Green only for synced or backed up; cyan for selection, focus and go; gold for suggestions and warnings; red for brand, the one primary action and danger.
- Kind: ruling

### ALL-018: Text contrast: names 7:1, all other readable text 4.5:1 on every ground.
- Why: Faded secondary text at 40 % measured 3.0:1, and the red accent read 4.11:1 on control backgrounds until they were darkened.
- Must: Names and secondary text reach 7:1 and other readable text 4.5:1 on every background, faded text measured as drawn, disabled text excepted, checked automatically.
- Kind: ruling

### ALL-019: The owner: no control keeps the browser's default look.
- Why: Text fields, checkboxes, scrollbars and sliders showed the browser's light defaults on the dark theme, and the top bar broke labels in half at 1920 x 1080.
- Must: Every field, checkbox, list, scrollbar and slider wears the product's look on every page, and navigation wraps only between whole items.
- Kind: ruling

### ALL-020: The owner: no bracket buttons; every action is a real labelled button.
- Why: The owner: "I don't like the bracket buttons, make them more usable."
- Must: Each action is a labelled button with at least a 44 px touch target and a separate key hint; an icon-only button has a spoken name and a tooltip.
- Kind: ruling

### ALL-021: The owner: nothing on a page jumps when switching, loading or opening panels.
- Why: Pages moved sideways between pages with and without a scrollbar, between tabs and on all or none; opening a panel moved every card and text reflowed on hover.
- Must: Switching pages or tabs, loading, hovering or opening a panel never moves content already on screen; only an idle box may shrink to its content.
- Kind: ruling

### ALL-022: The owner: every window folds, and every unclear control explains itself on screen.
- Why: The owner: "Every window should be expandable/collapsible" and "Give everything tooltips that need it"; top-bar tooltips opened above their buttons, off the screen.
- Must: Every window collapses and expands, every unclear control explains itself on hover, focus or touch, and every tooltip lies wholly on screen.
- Kind: ruling

### ALL-023: The owner: nothing is cramped, unexplained or hidden behind a sideways scroll.
- Why: The owner: "what do these dots mean? This UI looks terrible, compressed, and you have to scroll to the right"; some pages had no phone layout or needed hover.
- Must: Every figure has a visible legend, every page fits a 390 px phone with no sideways scroll or hover, and every window keeps its buttons reachable.
- Kind: ruling

### ALL-024: Fonts ship with the product; Chinese names use a Chinese-capable face.
- Why: Fonts came from an outside font service; the large Chinese face is too big to ship, so system Chinese fonts draw Chinese names.
- Must: No page loads fonts or other assets from the internet, and Chinese folder and clip names always render in a Chinese-capable face.
- Kind: ruling

### ALL-025: The owner: "our brand on every customer's build is what I want".
- Why: An upgrade swapped the maker's mark for a neutral one; the owner: "that's half the point", the product is sold like Resolve with its maker's mark.
- Must: The maker's current mark, in red, is on every window, popup, installer, taskbar and tab by default; a studio may choose another, and upgrades never change that choice.
- Kind: ruling

### ALL-026: The owner: every app reached from the dashboard has a way back to it.
- Why: The dashboard linked to the footage sorter, but the sorter had no way back, on desktop or phone.
- Must: Every app reached from the dashboard shows a link back to the dashboard on every page, on phone and desktop.
- Kind: ruling

### ALL-027: Android's Back button left the page instead of returning to the list.
- Why: A phone layout shows one view at a time; without a history step, Android's Back leaves the page instead of returning to the main list.
- Must: On a phone, leaving the main list for another view adds one history step, so Back returns to the list.
- Kind: situation

### ALL-028: Small screen faults: undersized buttons, clipped placeholders, mislabelled searches.
- Why: Phone buttons were 40 x 44 px, a search placeholder read "Search the car" at 1440 px, an empty panel took a quarter of a phone screen.
- Must: Every touch target is at least 44 x 44 px, no label is clipped at 1440 px, empty panels take no room, and every label says what it does.
- Kind: situation

### ALL-029: Faint text and invisible keyboard focus made screens hard to use.
- Why: Buttons showed no keyboard focus, some borders measured under 2:1, and dialogs ignored Enter and Escape.
- Must: Every control shows keyboard focus, borders are visible, and every dialog answers Enter and Escape.
- Kind: situation

### ALL-031: Screen readers heard symbol names and never the question being confirmed.
- Why: Buttons read "black right-pointing triangle dismiss", headings "slash slash your computers", and a delete confirmation was only "are you sure, dialog, Cancel".
- Must: Screen readers hear names without decorative symbols or underscores, repeated controls name their subject, and every confirmation announces its full question.
- Kind: situation

See also, filed under another capability:

- DSH-125 (The dashboard): The only button that closes an error was red text on a red banner.

## Wording

### ALL-032: The owner: no long dashes in anything a person reads.
- Why: The owner: "remove em dashes from visible text"; a spaced double hyphen stood in for one, and text the page composes in the browser went unchecked.
- Must: No visible text, browser-composed messages included, has a long dash or " -- "; use a hyphen with spaces, a colon or two sentences; an empty cell shows a hyphen.
- Kind: ruling

### ALL-033: The owner: the product names roles, never a person.
- Why: Messages named the owner personally; he: "change it to admin - it reads kind of patronising."
- Must: No text a person reads names a specific person; people are referred to by role, such as "your admin".
- Kind: ruling

### ALL-034: One word for each idea and each action, everywhere a person reads.
- Why: A sync plan, a computer and "not syncing" each had several names; sending a cut to Resolve was "build", "conform" and "make" in different places.
- Must: Approved words only (computer, ticked, sync plan, paused, stopped by your admin, stopped itself, upload, proxy download, folder sync); an action keeps one name, in sentence case.
- Kind: ruling

### ALL-035: Counts read "3 file(s)" instead of real plurals.
- Why: The owner retired the "(s)" shorthand, but it kept shipping in tray, dialog and page messages.
- Must: Every count a person reads uses the correct singular or plural word ("1 clip", "3 clips") with an agreeing verb.
- Kind: ruling

### ALL-036: The owner: no customer's name, drive letter or example in what ships.
- Why: Defaults named the first studio's shoot and archive folder, its drive letter, its NAS brand, its episode, its search language and real people in sample data.
- Must: A fresh site shows no name, folder, drive letter, language default or example taken from another studio; every such value comes from the site's own settings.
- Kind: ruling

### ALL-037: The owner: no assistant or product name in a generated document's title.
- Why: Every generated plan and draft was titled with the assistant's name in brackets; the owner said to stop adding it "to the title of all these documents".
- Must: Documents the product or its assistant creates are named by episode and version only.
- Kind: ruling

### ALL-038: The product's own name was spelled two ways.
- Why: The product's name was spelled one way in the default and another in about 60 sentences editors read.
- Must: The product's name is spelled one way in every sentence a person reads.
- Kind: situation

### ALL-039: Browser tabs showed the product's name, not the studio's.
- Why: Page titles were fixed text while the header showed the studio's own name; the search pages' titles load before the name is known.
- Must: Every browser tab title, search and download pages included, carries the studio's own name from site settings.
- Kind: situation

### ALL-040: Parts of the product ignored the site's drive letter and folder names.
- Why: Installers, messages and sync steps assumed the default drive letter, projects folder, login port and account ids, so another studio's install mapped wrong drives and broke silently.
- Must: Every part reads drive letter, tree, projects and proxy folder names, NAS login port and account ids from the same site settings, or refuses a value it cannot honour.
- Kind: situation

### ALL-041: Screens showed internal codes, ids and raw errors instead of sentences.
- Why: Pages showed raw states like "no-model", project ids, model ids, raw database text, transfer-tool output, and once "[object Object]" for a structured refusal.
- Must: Every state, refusal and error is a plain sentence naming cause and next step; raw values sit one click away, and tests check the rendered text.
- Kind: situation

### ALL-042: Raw error text with local paths left an editor's computer.
- Why: Error strings, which can carry an editor's local paths, were forwarded to the server and shown in settings and on a landing page.
- Must: No raw error text or local path leaves an editor's computer; the server receives and shows a plain sentence.
- Kind: situation

### ALL-043: The admin was told "ask your admin", and counts had the wrong scope.
- Why: A notice put a computer-wide 1,046 missing proxies under a project holding 438; one sentence covered three situations; only the first failing folder was named.
- Must: Counts state their scope, each distinct problem gets its own true sentence, several show a count, and nobody is told to ask themselves.
- Kind: situation

### ALL-044: Messages claimed causes the product could not see.
- Why: A missing folder marker was blamed on a move, a move notice claimed Resolve was relinked when it was not, and one drive state had three names.
- Must: Every message states only what the product actually knows, and one event is worded the same everywhere it appears.
- Kind: situation

### ALL-045: Messages sent people to buttons and pages that were not there.
- Why: Messages and the customer guide named gone menu items, absent pages, a button hidden in that state, another screen's button, vendor-only tools and one NAS brand.
- Must: Every direction, message or guide line names a place and label that exist and are visible then; a release fails when one does not.
- Kind: situation

### ALL-046: "Contact support" never said who or where support is.
- Why: A dozen messages told people to contact support, but no screen, mail or window named a contact.
- Must: Every "contact support" line, mail, help page and setup finish names a real support contact, which a reseller or site can replace.
- Kind: situation

### ALL-047: Plain help for the product's words was not reachable from the product.
- Why: The how-it-works guide existed only outside the product; no screen in any part linked to help.
- Must: From every place a product term appears a person reaches plain help on it; if help is absent, the page says "Help is not installed".
- Kind: situation

### ALL-048: Times read "releases itself 0s ago" and "since never".
- Why: Future times went through "time ago" wording that clamps to zero, sentences printed "never" for an unknown time, and panels showed raw timestamps.
- Must: Times read in plain words and the right tense ("releases in 23 h"), and every sentence reads correctly whether its time is known or not.
- Kind: situation

### ALL-049: A long message reached the dashboard cut off mid-word.
- Why: Messages over 255 characters were cut at the limit, losing the name of the conflicting program at the end.
- Must: Messages put the useful fact first and are shortened on purpose, never by a limit that lands mid-word.
- Kind: situation

## Safety in what the product does

### ALL-062: The owner: "we don't want this script to be able to delete ANYTHING".
- Why: The owner ordered a review stating "we don't want this script to be able to delete ANYTHING".
- Must: No automatic action deletes an original or a file on the server; anything removed locally is a person's explicit choice or recoverable for a period.
- Kind: ruling

### ALL-063: The owner: opening a tool never starts its work.
- Why: The owner: tools "should not auto run on launch, they should all be adjusted so that they just launch and then there is a run button".
- Must: Opening any tool that changes a project or files shows it idle; nothing is processed until the person presses its run button.
- Kind: ruling

### ALL-064: One click stopped syncing, signed people out or stopped the fleet.
- Why: Stopping the fleet, wiping a plan, revoking sign-ins, signing out every session including your own and switching a computer to wired all acted at once.
- Must: Any action that stops syncing, deletes, revokes, signs out or affects every computer asks first stating the consequence, and looks unlike harmless controls.
- Kind: situation

### ALL-065: A safety rule fixed in one place stayed missing where the same action happens elsewhere.
- Why: Free-space checks, mass-deletion brakes, name normalising and user cut-off each guarded one of several paths doing the same action.
- Must: Every path that performs a kind of action obeys every safety rule for that action, each one tested.
- Kind: situation

### ALL-066: One bad item stopped a whole batch.
- Why: A row naming an unknown share, or "429" in a file name mistaken for a rate-limit reply, aborted the batch and left it stuck.
- Must: One bad item in a batch is recorded and skipped, and the rest of the batch carries on.
- Kind: situation

### ALL-067: Fixes meant editing files or redeploying, which a non-technical owner cannot do.
- Why: Only one editor setting had a control, and fifteen admin messages said "edit a variable and redeploy".
- Must: Every setting an editor or admin may need is a control in the product, and no message tells anyone to edit files or redeploy.
- Kind: situation

### ALL-068: A setting of zero meaning "none" was taken literally and broke the feature.
- Why: Port 0 bound a random port nothing could reach, and a session lifetime of 0 signed every user out on the next page, silently.
- Must: A zero or negative port or lifetime is refused or replaced by the default, and the replacement is reported naming the setting.
- Kind: situation

### ALL-069: An interrupted settings write reset a computer to defaults.
- Why: Settings, secret and marker files were rewritten in place; an interruption left them half-written and read as defaults, a present key or a permanent refusal.
- Must: Every file holding settings, secrets or identity is replaced whole or not at all, and a damaged one is detected, never read as valid.
- Kind: situation

## Windows, text and names

### ALL-070: Windows tools often save text with an invisible byte-order mark.
- Why: A settings file saved with a byte-order mark was read as empty or broken by a strict reader, silently losing all its settings.
- Must: Every settings file is accepted with or without a byte-order mark, and the product never writes one.
- Kind: given

### ALL-071: A Windows console on a Western code page fails on Chinese or accented text.
- Why: Printing "Šimalčík" or a Chinese line raised "'charmap' codec can't encode character"; a run dying mid-apply left Resolve half-changed.
- Must: Logging or printing Chinese, accented or any non-Western text never stops a run, on any Windows console.
- Kind: given

### ALL-072: Windows passes text to and from other programs in a legacy code page.
- Why: Child programs' input and output default to cp1252 (cp950 on Traditional Chinese), so a Chinese term crashed a call and a non-Latin name faked a failed health check.
- Must: All text exchanged with other programs is UTF-8 explicitly, unreadable bytes replaced, and a decoding failure is reported, never taken as an empty result.
- Kind: given

### ALL-073: Windows may spell its temporary folder as an old 8.3 short path.
- Why: On some Windows machines the temporary-folder path is a short 8.3 name, so a text comparison with full long names never matches.
- Must: Every comparison of Windows paths treats the short and long spellings of one path as the same path.
- Kind: given

### ALL-074: Windows caps a command line at 32,767 characters.
- Why: Long text passed as a command argument fails on Windows, at 8,191 characters through a batch file.
- Must: Large text is never passed to another program as a command argument on Windows.
- Kind: given

### ALL-075: Explorer ignores its select switch when the switch arrives inside quotes.
- Why: "Open in Explorer" opened Documents for every clip whose path had a space, because the quoted select switch was silently ignored.
- Must: Reveal in Explorer opens the right folder with the clip selected for paths with spaces, brackets and non-Latin letters, checked against the window that opened.
- Kind: given

### ALL-076: Windows timestamps repeat, and clocks step backwards.
- Why: Windows time moves in 15.6 ms ticks, so events often share a stamp; network time corrections and waking from sleep step the clock back.
- Must: No identity comes from a timestamp, and a time window such as a restart limit counts a stamp in the future as recent.
- Kind: given

### YTD-092: A backslash path shown to a Mac editor is a wrong path.
- Why: On a Mac a backslash is legal inside a file name, and a page served from the NAS cannot know an editor's drive letter or system.
- Must: Pages served from the NAS show a file's path relative to the project tree, with forward slashes and no drive letter, saying "under your sync drive".
- Kind: given

### ALL-077: The owner: every Windows file picker is the full Explorer dialog.
- Why: The owner: "make sure it is the proper explorer file picker not the limited one without an address bar in the top".
- Must: Every file or folder picker on Windows is the full system dialog with an address bar a path can be typed or pasted into.
- Kind: ruling

### ALL-078: Names written only in Chinese or other non-Latin scripts broke features.
- Why: A shared folder named only in Chinese made every settings read fail, and a non-Latin computer name could not travel in a request's identity.
- Must: Computers, folders, projects and network peers named in any script work everywhere the name travels.
- Kind: situation

### ALL-079: A folder named "Luts Local" was treated as inside "Luts".
- Why: Folder containment compared text prefixes, so a sibling whose name began with the library's name counted as inside it.
- Must: "Is this inside that folder" compares whole folder names, so "Luts Local" is never inside "Luts".
- Kind: situation

### ALL-080: Names containing ".." could reach outside the studio tree.
- Why: Project paths, template folder names and downloaded file names containing ".." or "." created folders or records outside the tree.
- Must: Any folder or file name typed or received is refused if it would resolve outside the studio tree or to the folder itself.
- Kind: situation

### ALL-081: One file dated far in the future blanked every row after it.
- Why: A camera with no clock set writes absurd file dates, and one bad date broke the whole list from that row on.
- Must: A file or folder with an impossible date shows a plain placeholder date and never hides or breaks any other row.
- Kind: situation

### ALL-082: Today's date was refused as "in the future" before 8 a.m. in Taiwan.
- Why: Dates were checked against universal time, so in a UTC+8 studio "today" was still tomorrow until 08:00.
- Must: Every date a person enters or reads is interpreted in the studio's own time zone.
- Kind: situation

## Requests, logs and outside programs

### ALL-083: Oversized or malformed requests crashed the server or the editor's app.
- Why: Write paths read unlimited bodies, trusted stated lengths, and crashed on wrong types or odd characters; the sender saw a server error and resent forever.
- Must: Every request has a size cap, and malformed input gets a clear refusal the sender treats as final, never a crash or a retryable server error.
- Kind: situation

### ALL-084: Editors' computers hammered the server once it answered immediately.
- Why: A repeating request relied on the server holding each reply 25 seconds; when it answered at once, every computer looped continuously.
- Must: Every repeating request from an editor's computer keeps its own minimum interval and backs off whatever the server answers, and idle waiting never ties up the server.
- Kind: situation

### ALL-085: Logs grew without limit on the server and lost evidence fast on editors.
- Why: Server logs had no cap on an appliance nobody watches, while a 20 MB editor log rotated its evidence away in under half an hour.
- Must: Logs are capped on every machine yet keep at least a day of history, and a rotation leaves a note that older lines were dropped.
- Kind: situation

### ALL-086: The same unchanged problem was logged every pass, burying everything else.
- Why: Repeating warnings ran to 1,350 lines a day in a 5 MB log, and an unreachable server would log once a second per clip.
- Must: A repeating condition is logged when it starts or changes and quietly in between, so a day of it costs a handful of lines.
- Kind: situation

### ALL-087: Outside programs were installed as "latest" without verification.
- Why: Installers fetched unpinned, unchecked programs, one lacking a publisher checksum, and one download host outage stopped every build.
- Must: Every downloaded outside program is pinned by version and checksum and verified before unpacking; no checksum means refusal; a byte-identical second source is allowed.
- Kind: situation

## The assistant

### ALL-088: The owner: assistant work must cost cents, not dollars, per run.
- Why: The owner: one sort "cost 60 cents to run haha, not reasonable"; archive indexing "absolutely hammers my usage" and pay-per-call would be "insanely expensive".
- Must: Each assistant task shows its expected cost before running, and routine runs over a project or archive stay within a cost the owner sets.
- Kind: ruling

### ALL-089: Customer builds use only the studio's own paid assistant key.
- Why: Customers have no personal subscription sign-in, consumer terms forbid reselling one, and the owner ruled nothing of the assistant is bundled.
- Must: In a customer build every assistant call uses the site's own paid key, no setting enables subscription sign-in, nothing is bundled, and keys never show in full.
- Kind: ruling
