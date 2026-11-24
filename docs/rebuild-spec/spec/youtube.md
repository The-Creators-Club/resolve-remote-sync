# YouTube downloads

YouTube downloads let an editor find footage on YouTube by describing a topic, review what was found, and have the chosen videos land in a project, ready to cut, with their credits written into each file; an editor can also paste links instead of searching. Editors use it while researching a film; an admin keeps it working and sees its health. YouTube is something the studio has to live with: it paces, blocks and changes its service without notice, and this part is shaped around what YouTube does. YouTube downloads is one of the six parts a site switches on and off, and it is off until a site switches it on. When it is off, nobody but an admin sees it, and only in settings, where it is listed with its switch: there is no YouTube page, no YouTube entry in the menu bar or in search, no YouTube controls, sign-in or terms in the app on an editor's computer, and no computer downloads, prepares to download, or opens or fetches a downloaded clip for this part. Switching it off never deletes anything: clips already downloaded stay in their projects as ordinary footage, and every job, acceptance and history entry is there again when it is switched back on.

## Searching and reviewing results

### Anyone signed in can use YouTube downloads, and each job belongs to the person who started it

YouTube downloads are reached only by a person signed in to the dashboard. A job is one search, or one batch of pasted links, and it belongs to the editor who started it: only they see it, review it, start, retry, reorder or cancel it. Asking for another editor's job gets the same answer as asking for one that does not exist ("no such job"), never "not allowed", so nobody learns that it exists.

The record of every clip ever downloaded, and who downloaded it, is shared: every editor sees all of it in the download history and in the "already in" marks on search results.

If the dashboard session expires while the page is open, the page says "your dashboard session has expired. Sign in to the dashboard again and reload this page. The job itself keeps running on the server." and stops refreshing; the job carries on.

- Who: anyone signed in.
- Name and search words: YouTube downloads. Search words: youtube, download, footage search, stock, clips, links.

### An editor starts a search with a topic, a project and a few choices

The controls for a search are: the topic (Enter starts the search), the project the clips go into, the quality, YouTube's own upload-date window, how many candidates to collect at most, the search mode, the shot types, the languages to search in, and an optional upload date range ("uploaded from" and "to", with a clear button when either is set). The search button disables itself while its request is in flight. With no project chosen the page says "pick a project first".

| Choice | What is offered | Refusals |
|---|---|---|
| Topic | required, at most 400 characters | "a search topic is required"; "a search topic must be 400 characters or fewer (that one is N)" |
| Quality | 1080p (the default), 720p, 1440p, 2160p, best | |
| YouTube's upload-date window | "any date", "today", "this week", "this month", "this year" | |
| Candidates at most | 50, 100 (the default), 200 or 400 | any other number is refused, never rounded |
| Upload date range | optional "from" and "to" | a date that is not a real calendar date: "must be a date like 2026-01-31", quoting what was typed; a start after its end: "the date range is reversed: "from" is after "to"" |
| Shot types | the nine boxes of the search mode | more than nine, or one the product does not know, is refused naming them |

YouTube's search has no free date range, only its five fixed upload windows. When a window is chosen, YouTube's own filter for that window is used. A date range the editor sets is applied after the search: it removes every result outside it, and it is shown on every view of the job. A new search always goes to the back of the editor's queue.

- Who: anyone signed in.

### The page remembers each editor's last choices in that browser

Remembered in the browser between visits: the search mode, the ticked shot types (separately for each mode), the languages to search in, the project, the candidate limit, the "on this computer" switch, and the folder typed for pasted links. The project is restored only if it is still offered (otherwise the first one offered is chosen) and is never changed except by the person. The upload date range is never remembered. Whether the review panel is folded is remembered, except that it opens itself when a search newly arrives at review.

### A search can list every upload of a named channel

An archive channel's uploads are barely reachable through YouTube's search. An editor can therefore name a channel instead of a topic, and the search lists every upload of that channel, which can then be narrowed by words in the title. The results go through the same review as any search.

- Who: anyone signed in.

### The editor reviews the search terms before searching

Before anything is searched, the editor sees the terms the assistant wrote and ticks the ones to use. The editor's own topic is always the first term, marked "what you typed", followed by the assistant's queries, up to 24 terms in all; repeats are ignored. Every term starts ticked. A Chinese query shows its English translation in brackets, and the typed topic gets one too when the assistant returned the same text.

The panel shows "N of M terms", TICK ALL, UNTICK ALL and SEARCH WITH THESE. SEARCH WITH THESE is disabled with nothing ticked, and is refused with "tick at least one search term: a search with none of them would find nothing". Ticks stay in the page until that button sends them; then searching starts. A job waiting here has no time limit and no default: it waits until the editor acts or cancels. Acting on a job that is no longer waiting for its terms is refused with "this job is <state>, not waiting for you to pick its search terms".

If the assistant fails while writing terms, the job fails with the matching message (see "The assistant behind search is the one the site has set up, and every failure is explained"); if it writes nothing usable, the job fails saying the reply contained no usable queries.

- Who: the editor who started the job.
- When the assistant is off: there is no term review. Only a search of exactly the typed topic is offered, and it starts searching at once.

### Each ticked term is searched on YouTube in turn until the candidate limit is reached

Each ticked term is searched once, about two seconds apart, collecting up to 15 results per term (a search of exactly the typed topic collects up to the whole candidate limit). Once the job holds the candidate limit (50, 100, 200 or 400 distinct videos), no new videos are added, though the remaining terms are still searched and the videos already held still note every term that found them. The chosen limit caps how many videos are looked up afterwards, too.

For each video the page keeps what YouTube's search page shows: title, channel, view count, thumbnail, duration (not for live or upcoming streams) and upload date when given. A term whose search fails counts as searched with no results and the job carries on. Each term records how many results it returned. A cancel is honoured between terms.

### Results that cannot be used are set aside with their reason and can be ticked back

Set-aside results stay on the job, unticked, with a note the editor can read, and the editor may tick them back.

| Why | Note shown |
|---|---|
| No duration (live, or none given) | "live or no duration" |
| Longer than 30 minutes | "over 30 minutes" |
| Upload date known and outside the editor's date range | "uploaded YYYY-MM-DD, outside A to B" (or "A onwards", "up to B") |
| Under a date range, upload date unknown | stays relevant but arrives unticked: "upload date unknown, so not checked against <range>: unticked until you look" |

An unknown date never sets a video aside. Videos longer than half an hour are left out of what a search downloads unless the editor ticks one back.

### A video the studio already has is marked with where it is and cannot be picked again

A result is marked "ALREADY IN <project>/<folder>" (an empty folder reads "Youtube"), dimmed and unticked, when the studio's record of downloads holds it (in any project) or a finished file carrying its YouTube id already sits anywhere in this project's YouTube folder. Unfinished and failed files do not count. Trying to tick one is refused with "already downloaded, so it cannot be selected" and where it is. Videos are recognised by YouTube's 11-character video id.

The same check is made again on whichever computer is about to fetch each clip, just before it does; a hit then marks the clip "already downloaded" instead of fetching it again.

### The review shows every found video as a card with counts, filters and what the download will cost

The review is shown when the search is ready for review (pasted links skip it). It holds:

- A row of term chips: "all terms (count)" and one per term, with its English gloss for a Chinese term and how many videos it shows with the filters as they stand. A chip's tip says whether the editor typed the term or the assistant wrote it, and how many of its results are set aside. Clicking a chip shows only that term's videos; clicking again clears it.
- A line naming the mode, languages, date range, shot types and candidate limit the search actually ran with.
- Counts: "R relevant · D already downloaded · F filtered out", with SHOW FILTERED OUT / HIDE FILTERED OUT when anything was set aside.
- SELECT ALL and SELECT NONE. Select all ticks the relevant videos, and the set-aside ones too while they are shown; it never ticks a video already downloaded or one that could not be looked up. Select none unticks everything. Choosing either replaces the selection before it.
- Each card: thumbnail, a tick box, the title, channel, duration, upload date, and the set-aside note or "unavailable". Clicking the card ticks or unticks it. Clicking the title opens the video on YouTube in a new tab and never changes the selection. Each tick is saved at once, in order, and undone with a message if saving fails.
- An empty grid says "all N filtered out: SHOW FILTERED OUT to see them" or "nothing found for this term".
- The header keeps "N clips · M selected" when the panel is folded.
- A footer: "N selected · Xh Ym of footage · roughly G GB · F GB free on the computer doing the download · into <project>/Youtube/<folder>".
- CANCEL SEARCH, only while the search waits for review, asks "Discard this search? Nothing from it was downloaded, and its results will be thrown away." and then clears the page ("search cancelled").
- DOWNLOAD N, enabled while the search waits for review or after it has finished, with at least one video ticked and the download terms accepted. An editor can come back to a finished search and download further clips from it without searching again.

Ticks stay live while the job downloads: unticking a clip that has not yet been fetched means it is not fetched.

- Who: the editor who started the job.
- Phone and desk: every count, tick and button works the same at phone width.

### An editor can paste YouTube links instead of searching

A links box (Ctrl or Cmd + Enter submits; Enter adds a line) and an optional folder box, then GET LINKS, which disables itself while its request is in flight. Pasted links are not looked up when pasted: a pasted job has no term review and no results review, and a clip's title is first known when it lands.

- Accepted, split on spaces, new lines and commas: a bare 11-character video id; a watch, short-link, Shorts, embed, live or old-style video link on YouTube, YouTube Music, YouTube's no-cookie domain or the short-link domain, with or without "www." or "m.", with or without "https://", with any tracking parameters. Playlist, channel, results and feed links are refused. A link to a video inside a playlist takes only that one video.
- Anything unreadable: "N of those are not YouTube video links: <first three>.... Paste watch/youtu.be/shorts links (or bare 11-character video ids), one per line."
- Nothing usable: "paste at least one YouTube link".
- At most 4000 characters ("that is N characters of links; paste at most 4000") and 50 distinct videos ("that is N links; 50 is the most one job may take. Split them into two."). A video pasted twice counts once.
- A video the studio already has is listed as skipped, "already in <project>/<folder>". If all of them are already held, nothing is started: "the fleet already has that video" (or "all of those videos"), with the list.
- The project and quality are checked as for a search, and so is the free space.
- With a folder typed, the clips go into Youtube/<folder> in the project; with none, loose in the project's Youtube folder. The folder box is remembered per browser; a blank one keeps the default. Pasted links take no search-only choices, and they are not limited by length.

A pasted clip, once landed, is filed into the editing program and joins the download history like any other.

- Who: anyone signed in.

### A news clip with a signer burned into the picture is flagged

Some news uploads carry a sign-language signer burned into the picture, which makes the footage hard to use. A downloaded news clip with a burned-in signer is flagged on its row and in the download history, pointing to a plain version of the same story where one was found.

#### Lessons

- Met: YTD-001, YTD-002, YTD-003, YTD-004, YTD-005, YTD-006, YTD-007, YTD-008, YTD-009, YTD-010, YTD-011, YTD-018, YTD-019, YTD-012, YTD-013, YTD-014, YTD-015, YTD-016, YTD-017.

## How YouTube throttles and refuses

### YouTube blocks an address that asks too much too fast, so every request is paced

About a hundred quick requests from one address are enough for YouTube to block that address for hours. Every request the studio makes to YouTube is therefore paced, and searches and detail lookups share one pace:

- searches about two seconds apart;
- detail lookups at most about 80 a minute;
- clips of a job downloaded one at a time, about three seconds apart, so the studio never looks to YouTube like a burst of traffic.

Details a search already returned are reused, never fetched again. Only single videos are ever downloaded, never a playlist; a clip with no video id is skipped. Each clip's file is dated with when it was downloaded, not YouTube's upload date. This pacing is what the page's standing line about deliberately paced downloads refers to.

### Each found video's details are looked up, and videos YouTube will not describe stay visible as unavailable

After searching, every video whose duration is not yet known has its full details fetched from YouTube at the pace above. Progress shows as "metadata i/n", and a cancel is honoured within a few videos. A video YouTube will not describe (unavailable, private or blocked in the studio's region) keeps its card, marked "unavailable", unticked and set aside. A detail YouTube returns empty is kept from the search page rather than blanked.

### When YouTube bot-checks a search, the search carries on from the search page where it can

YouTube can ask a whole address to prove it is not a bot ("confirm you're not a bot") while still answering searches from it, and it can do this to anonymous downloads while search keeps working. A refusal of this kind is always reported as a bot check, never as a missing video or a network fault.

- During the term searches: the job fails with the bot-check message (see "Downloads go out without a YouTube account first, and a signed-in session is used only after a bot check").
- While looking up details: no further lookups are made for that job; every video not yet looked up is described from the search page instead, and the job shows: "YouTube is limiting this server right now (it asked the server to prove it is not a bot), so the details on these results come from the search page instead of from each video: upload dates are missing and some durations may be too. Open a clip on YouTube before relying on its date." The job goes on to review. Only if no usable video on the job has any duration at all does the job fail with the bot-check message.

The download itself can still run from an address YouTube does serve (see "A download runs wherever YouTube will serve it").

### Downloads go out without a YouTube account first, and a signed-in session is used only after a bot check

Facts about YouTube: it sometimes refuses a download with a bot check, and it sometimes flags a signed-in account so that everything fetched with it fails with "the page needs to be reloaded". Once flagged, that session is the cause of failures, not their cure. So, wherever a download runs:

- Every download goes out first without a YouTube account.
- On a bot check, when a signed-in session is available where the download runs, the same clip is tried once with the session, and the clip shows that it is retrying signed in. If that works, the following clips of the job try the session first, and the clip is noted "downloaded with the signed-in YouTube session (the anonymous attempt was bot-checked)". Only a clip that landed through the signed-in session is noted.
- When the session is tried first and YouTube refuses the account, the clip is tried once without it; if that works, the job goes back to trying without the session first.
- Any other failure (the network, a refusal of the media itself, no usable format, a stream cut short) is never answered by switching between signed in and not.
- Each new job starts without the session again.

When a download cannot go on:

| Situation | The clip or job is told |
|---|---|
| Bot check on the server, and no signed-in session to fall back to | "YouTube is asking this server to sign in to confirm it is not a bot, so nothing can be searched or downloaded from it right now. Downloads run anonymously by default and there is no signed-in session to fall back to: an admin has to give the server a signed-in YouTube session exported from a browser." |
| Both ways refused on the server | "Both YouTube download paths are blocked, so nothing more can be fetched right now. Anonymous requests are being bot-checked and the signed-in session is being refused. An admin has to export a FRESH session from a different signed-in browser, and test the same clip both with and without it before trusting it." |
| Both ways refused on an editor's computer | "both download paths are blocked on this computer: YouTube is asking the anonymous one to confirm it is not a bot, and it is refusing the signed-in session as well. Export a fresh cookies file from a different signed-in YouTube session, or let the server download this job." |

A session file holding no actual sign-in counts as no session. In every case the clips not yet reached stay waiting, so RETRY picks them up later, and they may still be fetched from wherever YouTube does serve them. The outcome of the latest attempt each way (worked or failed, when, which video) is shown on the health line.

### YouTube demands proof that a request comes from a real player before it serves a video

Facts about YouTube, each of which a download must meet:

- Without proof that the request comes from a real player, YouTube refuses the media or serves only slow streams. Every computer that downloads, and the server, meet this demand. When one cannot, an admin is warned (see "Admins are warned when downloading on the server or a computer is not working"), and every failure keeps YouTube's own error text so it can be read.
- YouTube holds a single connection for a long video to a few MB/s. A long video still downloads at well over 10 MB/s on a fast line.
- YouTube refuses some older uploads in their direct form while serving them as streamed segments. A download refused that way is tried as streamed segments before it is reported failed.
- YouTube can list a clip's formats and then refuse its bytes, so nothing reports downloading as working until a real download has succeeded the way real jobs fetch.
- A video that arrives in several parts arrives whole: every part is downloaded, each named from its own details, and the parts together count as the video when checking what is already on disk.

### When YouTube cuts a stream short, the clip is tried once more one quality lower

YouTube sometimes ends a stream before all of it has arrived, and can do so again and again at one quality while another quality works. When that happens the partial files are deleted and the clip is tried once at the next step down: 2160p to 1440p, 1440p to 1080p, 1080p to 720p, 720p to 480p, best to 1080p; 480p has no step down and fails.

| When | The clip shows |
|---|---|
| Retrying | "<q> stream truncated; retrying at <lower>" |
| Landed at the lower quality | "<q> stream truncated by YouTube, fell back to <lower>" |
| Failed again | "<q> stream truncated by YouTube and the <lower> retry failed too: <error>" |

Nothing else ever lowers the quality: a passing refusal never does. A final failure removes its partial files.

### Live streams are refused, and a download that runs too long or stalls is stopped

- A live stream still running, or one not yet started, fails with "this is a live stream that has not finished, so it would record until it ends. Download it again once it is an ordinary video." A finished stream downloads normally.
- A clip's download, joining its picture and sound included, may take at most 2 hours: "the download took longer than 2 hours and was stopped".
- The conversion to an editable file is stopped after 3 hours: "the conversion to an editable file took longer than 3 hours and was stopped".
- A download that writes nothing for a set time is stopped, and the clip fails saying it stopped making progress.
- A download a person cancels stops within about two seconds.

One clip's failure or time limit fails that clip only: the job carries on with the next, and every clip that finished keeps its file and its credits.


#### Lessons

- Met: YTD-020, YTD-021, YTD-022, YTD-023, YTD-024, YTD-025, YTD-026, YTD-027, YTD-028, YTD-029, YTD-030, YTD-031, YTD-032.

## Signing in to YouTube

### A site decides whether signed-in YouTube sessions may be used on editors' computers

Getting past YouTube's own blocks with a signed-in YouTube session on editors' computers is a site switch of its own, separate from switching YouTube downloads on, and off until a site turns it on. While it is off:

- no signed-in session is ever used for a download on an editor's computer, even one saved there before;
- the sign-in controls are not offered in the app on the editor's computer;
- saving a session is refused with "signing in to YouTube for downloads is not enabled for this site. Ask your administrator";
- nothing extra is set up on editors' computers for it.

Turning it on also lets editors' computers answer YouTube's in-page challenges, which signed-in downloads need. If a computer cannot be made ready for that, signed-in downloads stay off on that computer and it says why. If a setting cannot be read, it counts as off.

- Setting: Signed-in YouTube downloads on editors' computers. Does: lets each editor sign in to YouTube from the app so their own downloads can fetch age-restricted and blocked videos. Default: off. Who: an admin. Applies to: the site. Search words: youtube sign in, age restricted, cookies, blocked, bot check.

### An editor signs in to YouTube with one click from the app

An editor signs in to YouTube once from the app on their computer; their downloads on that computer can then fetch age-restricted videos. The sign-in lives apart from the editor's everyday browser, since that browser cannot lend its YouTube sign-in.

The app opens a private browser window (1024 by 820) on Google's sign-in page, continuing to YouTube, with a sign-in profile of its own that is kept between sign-ins and with no first-run, default-browser, sync or translation prompts. It uses, in order, on Windows Microsoft Edge, Google Chrome, Brave; on macOS Google Chrome, Microsoft Edge, Brave, Chromium. Safari and Firefox are never used.

| Moment | The editor is told |
|---|---|
| Starting | "<browser> is opening. Sign in to YouTube in that window; it closes by itself when you're done. Close the window to cancel." |
| Waiting | "waiting for you to finish signing in", every 5 seconds, with the time spent and the time left; the app's menu shows the same line with its countdown |
| Signed in | "signed in, saving your session", then a page reading "Signed in to YouTube. Closing this window..." for 2 seconds |
| No suitable browser | "No Edge/Chrome found for the one-click sign-in: choose an exported cookies file instead", and the file chooser for a cookies file opens |
| The window never becomes reachable within 30 seconds | "<browser> started but its sign-in window never became reachable. Close any leftover windows and try again" |
| The window cannot be inspected | "the sign-in window opened but could not be inspected - try again" |
| The window crashes | "The sign-in window failed unexpectedly." with a pointer to using an exported cookies file instead |
| The editor closes it | "the browser was closed before the sign-in finished - nothing saved" |
| 10 minutes without finishing | "The sign-in did not finish in time. Nothing was saved: try again from the app's settings." |
| The browser cannot start | "couldn't start <browser> (<error>)" |
| No room for the sign-in profile | "couldn't create the sign-in profile folder (<error>)" |

The app detects success itself. Only the YouTube and Google sign-in is kept, marked as a live Google session not to be shared, and saved as for a cookies file (below). The browser window is always closed at the end. The app shows the editor as signed in within seconds.

The sign-in control reads "Sign in to YouTube (for downloads)…" when never signed in, "YouTube: signed in ✓ (sign in again…)" when working, and "Sign in to YouTube again (session expired)…" when stale or expired.

- Who: an editor, for their own computer.
- Ways in: the one-click sign-in, or a cookies file exported from a browser.
- When signed-in YouTube downloads on editors' computers is off: no sign-in control is shown.
- Windows and macOS: the browsers tried differ, as listed.

### An editor can instead give the app a cookies file exported from their browser

A button "Use an exported cookies file…" opens the system file chooser titled "Choose your exported YouTube cookies file", showing text files or all files. Cancelling does nothing. The file is checked before it is kept:

- it must be a cookies file in the common browser-export (Netscape) layout, otherwise "that is not a cookies file in Netscape format. Export it with a cookies-file browser extension, not Save As";
- it must hold at least two of YouTube's sign-in cookies, otherwise "those cookies are not from a signed-in YouTube session (no login cookies found). Sign in to YouTube in the browser first, then export";
- other failures: "couldn't read that file (<error>)", "couldn't save the cookies (<error>)".

On success it is stored so that only the computer's own user can read it, the session is marked working, and the editor reads "YouTube sign-in saved: your downloads can now reach age-restricted clips". If the chooser cannot open, the editor is told so. The chooser is refused while another of the app's windows is open.

- Who: an editor, for their own computer.

### The app judges the editor's YouTube sign-in from real downloads and warns once when it lapses

The state of the signed-in session on an editor's computer is judged from real downloads, checked in this order:

| State | When |
|---|---|
| none | no session saved, or the site does not allow signed-in downloads on editors' computers |
| refused | YouTube has flagged the account: a real download with it was refused with "the page needs to be reloaded". The reason shown is "YouTube is refusing your signed-in session (the page needs to be reloaded). Downloads are continuing without it." |
| stale | a real download with the session was refused with any of "cookies are no longer valid", "sign in to confirm you're not a bot", "sign in to confirm your age", "this video may be inappropriate for some users", "please sign in to view this video" or "login required"; the reason shown is YouTube's own phrase. A stale state more than 7 days old is marked as aged. It is recorded at most once per job. |
| expired | the sign-in in the saved session has run out ("the login cookies in the file have expired") |
| working | otherwise. A download that succeeds with a stale session puts it back to working ("a download succeeded with the signed-in session"). |

Each time the session moves into one of the lapsed states, the editor gets one notification (a restart may warn again), and the same warning shows in the app's settings:

- expired: "⚠ YouTube sign-in has expired: age-restricted clips will fall back to the server", with a pointer to signing in to YouTube again from the app's settings;
- refused: "⚠ YouTube is refusing your signed-in session: downloads are continuing without it". This warning never urges signing in again with the same account: a flagged account stays refused, and a fresh session from a different signed-in browser is what helps;
- unused: "YouTube sign-in has not been used since <date>. Sign in again if you need it";
- stale otherwise: "⚠ YouTube sign-in no longer works (Google rotated the session). Sign in again", with the same pointer.

- Who: an editor, for their own computer.

### An admin can give the server a signed-in YouTube session

An admin exports a signed-in YouTube session from a browser and gives it to the server. It counts as usable only if it actually holds a Google sign-in; an export holding only its header, or only anonymous cookies, is treated as no session and never used. When YouTube flags that account, it answers every request with "The page needs to be reloaded", and a fresh session from a different signed-in browser is needed.

The server uses the session only after YouTube bot-checks an attempt made without it, for searches, detail lookups and downloads alike, so the account is exposed to flagging as little as possible. The health line shows whether a session is given, and whether it is empty, anonymous or signed in.

- Who: an admin.
- Setting: The server's YouTube session. Does: gives the server a signed-in YouTube session to fall back on when YouTube bot-checks it. Default: none. Who: an admin. Applies to: the site. Search words: youtube session, cookies, server sign in, bot check.

#### Lessons

- Met: YTD-033, YTD-034, YTD-035, YTD-036.

## Files Resolve can decode

### The quality chosen is a ceiling

The qualities are best, 2160p, 1440p, 1080p and 720p. Quality is a ceiling: the clip comes at that height or the best below it. At 1080p and below, YouTube's H.264 picture with AAC sound is preferred (then H.264 with any sound, then any picture of that height or lower), so most clips need no conversion. At 1440p, 2160p and best, the best stream at or below that height is taken and converted afterwards. When "best" has to step down, the next step is 1080p. The same clip with the same choices comes out the same wherever it was downloaded.

### Every clip lands as a single MP4 file with H.264 picture and AAC sound at a constant frame rate

Facts about Resolve: it cannot decode YouTube's VP9 picture, and it shows clips with Opus sound as Media Offline, or flickering between online and offline in a timeline. So no downloaded clip reaches an editor's Resolve in anything but H.264 picture with AAC sound at a constant standard frame rate, by any route, on any computer.

Picture and sound are joined into one MP4 file. After a clip lands, what is inside it is read (giving up after 2 minutes). It is converted when:

- the picture is not H.264;
- the frame rate varies (the average and the nominal rate differ by more than 1 %);
- there is sound that is not AAC;
- or the file could not be read at all, in which case both picture and sound are converted to be safe.

A file with no picture (sound only) needs nothing. The result is H.264 at a quality indistinguishable from the download, high profile, 8-bit 4:2:0, at a constant frame rate, keeping its colour description; sound is AAC at 320 kbps. Whatever was already fine is copied untouched, the credits written into the file are kept, and the file starts playing without having to be read to the end.

While a clip converts, its row shows "converting to H.264 (was <video>/<audio>)", or "converting to H.264 on your computer" when the editor's own computer is doing it, and the app on that computer says "converting". Nothing sits under the clip's final name until its conversion has succeeded: the download waits under a name that the sync, Resolve and every other part of the product ignore, and an interrupted conversion leaves nothing under the final name. Stopping the job mid-conversion deletes the half-made result and leaves the unconverted download to be cleared later.

Converting is heavy work, done on a computer of the studio's that is able and free (see Work shared out across the computers: Choosing who runs what); the clip appears in its project only once it is ready.

Conversion applies only to downloaded clips, never to camera originals, even where a camera original would match the test above.

- On its own: whether a clip needs converting, decided from what is inside it.

### A clip Resolve holds open when its conversion finishes is still delivered

Fact about Windows: a file open in Resolve cannot be replaced. Each outcome is a note on the clip:

- the converted clip takes the clip's name and the download is removed;
- the name is held: the old file is kept beside it under an "original" name and the note says "original was in use, kept as <name>"; it is removed later once it is free (at the latest at the next attempt at that clip), and any size still held is reported then;
- even that fails: the converted clip is saved as "<title>.converted [<id>]" and the note says "converted, but <name> was in use: saved as <new name>";
- nothing can be put in place: the clip fails with "Edit-ready conversion failed: converted, but neither <name> nor its converted copy could be renamed into place";
- the old copy cannot be removed after a few tries over about two seconds: "the pre-conversion download could not be removed (<size>, kept as <name>); it syncs nowhere and can be deleted".

Only the finished clip is ever filed into Resolve or shared with other computers. A leftover that cannot be deleted yet is tried again later and reported with its size. Sizes in notes read "N.N GB", "N MB" or "N bytes".

- Windows and macOS: only on Windows can an open file block the swap.

### When conversion fails, the clip either fails with the reason or is kept as downloaded

| Why it failed | What happens |
|---|---|
| The file was read, needed converting, and the conversion failed | the clip fails: "Edit-ready conversion failed: <the last 500 characters of the error>" |
| The file could not be read, and the safety conversion failed | kept as downloaded, noted "could not probe the codecs and the safety conversion failed; kept as downloaded" |
| The computer lost the means to convert during the job | kept as downloaded, noted "could not convert (no video tool); kept as downloaded" |

### A download only ever cleans up after its own clip

On a failure, stop, cancel or loss of the job, and before a lower-quality retry, only the half-made files of the clip concerned are deleted; a folder is never swept. Nothing a download leaves behind is ever uploaded by the sync or filed into Resolve as a clip.

### Downloading needs nothing installed by the editor

A typical editor's computer has no tools for fetching or converting video. The product brings what it needs to every computer that downloads, checked as genuine before use, and never replaces or changes video tools the editor installed for themselves. The tools for converting video are kept on every computer whether or not YouTube downloads are on, because other parts need them too.

### Clips already in the studio that Resolve cannot decode are found and fixed

Clips already downloaded with Opus sound or a picture Resolve cannot decode are found in the projects' YouTube folders and re-encoded to H.264 with AAC under their own names, the same way as a new download.

When a downloaded clip on an editor's computer cannot be decoded and a proxy of it exists with exactly the same number of frames, the original is set aside and the proxy takes its place. When the frame counts differ, the clip is re-encoded instead.

- On its own: which clips cannot be decoded, found from what is inside them.

### Before Resolve renders, the editor is told which clips would stop the render

Fact about Resolve 21: it stops a render on some VP9 and AV1 clips from YouTube. Before a render, a timeline's sources are checked for such codecs, and the editor is told by name which clips will make it fail. See Timeline Cards: the hand-over to Resolve, and exports: Renders from Resolve.

#### Lessons

- Met: YTD-037, YTD-038, YTD-039, YTD-040, YTD-041, YTD-042, YTD-043, YTD-044, YTD-045, YTD-046.

## File names and what a file carries

### Every clip is named after its channel, title and YouTube id

A clip is named "<channel> - <title> [<video id>]" with its file type. The whole name is never more than 200 bytes, counting bytes rather than letters, so that long Chinese or other non-Latin titles fit the limits of Windows, macOS and the NAS: the channel is cut to 60 bytes, the title is cut to fit, nothing is cut in the middle of a character, and the video id is always kept. Every other name the product writes for a download, unfinished ones included, keeps to the same limit.

A title becomes a name legal on Windows, macOS and the NAS once, where the clip is made, and that name is carried byte for byte everywhere: characters Windows forbids and their full-width look-alikes are dealt with at that moment and never again. Names keep their square brackets, and every part of the product finds, copies and checks such a file by its literal name. The id in brackets is how a clip already in a folder is recognised.

Every computer that downloads names clips the same way, so one clip is never in the tree under two spellings. A computer that would name a clip differently does not download until it is updated (see Releases and updates: Offering an update to a computer).

### Every clip carries its credits inside it and in a record beside it

Written into the clip file itself: the channel (also as the artist), the video's address (also as the comment), the channel's address, the uploader, the chapters and YouTube's own details. They are readable after the file is moved or renamed, on Windows and on macOS.

Beside each clip is a small credits record, in this order: channel (or the uploader when there is no channel), channel address (or the uploader's address), uploader, video address, title, video id, upload date and duration. It is readable text that keeps non-Latin characters as they are. If the credits cannot be written at the time, what is needed to write them is kept so they can be made later; if it could not be gathered at all, the clip has no credits record.

A clip has the same name, the same credits inside it, the same credits record and the same history entry whichever computer fetched it.

### A search's clips go into a folder named after the topic, made safe for every computer

Clips land in <project>/Youtube/<folder>. For a search the folder is the topic; for pasted links it is the typed folder, or none. The name is made safe:

- characters Windows forbids and control characters become spaces, and runs of spaces become one;
- leading and trailing dots and spaces go;
- it is cut to about 80 bytes without splitting a character;
- a Windows reserved device name (CON, PRN, AUX, NUL, COM1 to COM9, LPT1 to LPT9) gets an underscore;
- an empty result becomes "search".

The text is stored in one Unicode form, so the same name typed on a Mac and on Windows is one folder. Nothing can name a place outside the projects.

### A record of each search is left in its folder

When a job's download finishes, its folder gets a record of the search: the topic, whether it was a search or pasted links, the mode, when and by whom, the project, the quality, every term (its text, language, translation, whether it was ticked, whether it was typed or written by the assistant, and how many results it gave) and every clip landed or skipped (id, link, title, channel, duration, upload date, where it is, and which terms found it). Running the same topic again replaces it. Pasted links with no folder get one record per job in the project's Youtube folder. A failure to write it never fails the job; a job stopped by YouTube's block writes none.

### Unfinished and failed files never pass for a finished clip

Unfinished work never appears in a project's folders: only finished clips move in. When a clip fails, nothing it produced is left where it could be taken for the clip, uploaded by the sync or filed into Resolve. Files and folders made by downloads can be renamed and deleted by every editor of the studio on the NAS.

#### Lessons

- Met: YTD-047, YTD-048, YTD-049, YTD-050, YTD-051.

## Where a download runs, and saying so

### A download runs wherever YouTube will serve it

Fact about YouTube: it can refuse or bot-check the studio's own address for hours at a time while still serving an editor's own connection, and an editor's own signed-in session can fetch age-restricted videos that the studio cannot. So a download runs wherever YouTube will serve it: on the server, or over the connection of the computer of the editor who asked for it. The product decides where, and the editor is not asked to choose. When YouTube refuses one place, the clips go to the other where it can take them; a clip is never lost because one place was refused.

Wherever it runs, the same clip with the same choices comes out the same: the same quality rules, the same conversion, the same name, the same credits, the same folder, and the same entry in the history. A download on an editor's computer runs under the editor signed in there.

- On its own: where each job runs, from where YouTube will serve it and whether the editor's own computer can take the job.
- By hand: the editor can keep their own computer out of downloads, or stop a download running on it, and the page always shows where a job ran.

### An editor's computer takes a download only when it can finish it there

A job runs on an editor's computer only when that computer can complete it. It cannot when, with the first reason that applies:

| Reason | Said |
|---|---|
| YouTube downloads are off for the site, or the computer is kept out of downloads | "the YouTube downloader is off for this site, or switched off in config" |
| The computer is not set up to reach the server | "this computer has no dashboard URL or token configured" |
| Nobody is signed in on the computer | "nobody is signed in on this computer" |
| The computer's sign-in is no longer accepted | "this computer has no valid sign-in token: sign in again from the tray" |
| The signed-in editor has not accepted the YouTube terms on this computer | "the YouTube terms have not been accepted on this computer: accept them at the top of the YouTube page on this computer" |
| The computer is not yet able to download or to join YouTube's separate picture and sound | the reason, or "the downloader is not ready on this computer" |
| The project drive is known to be absent | "this computer's project tree isn't mounted right now, so there is nowhere to download into" |
| The computer does not hold the project, or has too little free space | as in "Clips land in the right project folder on each computer, never in a made-up folder" and "Before downloading, the product checks there is room and refuses with numbers" |
| The computer must update before it can download | "This computer must be updated before it can download YouTube clips." |

When the computer cannot tell whether the drive is there, it does not refuse on that ground. A computer that is merely busy with sync still answers at once; a busy or slow answer never sends a job elsewhere unnoticed. The computer tells the page its free space on the drive that holds the projects, its name and the signed-in editor.

- Who: an editor, for their own computer.

### The page always says where each job ran and why

Each job records which computer ran it, and the page shows it: "downloading on your computer" or "downloading on the server", with who is downloading in the tip, the downloading computer's live line ("clip i/n · 38% at 4.2 MB/s · 2:10 left"), and the free space that computer reported.

Whenever a job runs on the server rather than the editor's own computer, or moves there, the page says why, once per distinct reason, in a plain sentence, never a bare error code, and adds what it means for the clips: the server downloads them, and YouTube originals only sync upwards, so the editor fetches one from the download history when they want it on their computer. The sentences:

- the computer could not take it: "This computer cannot download right now: <reason>. The server is downloading these clips.";
- the app on the computer is not answering: "Downloading on the server: the app on your computer is not answering", with a hint to check the app's status;
- the computer is busy with another job: "Downloading on the server: your computer is already downloading another job";
- the editor's acceptance is missing: "The dashboard has no record of you accepting the YouTube download terms, so this computer did not download. Read the notice at the top of this page and press Accept.";
- the server no longer accepts the computer's sign-in: "The dashboard does not accept this computer's sign-in, so it did not download.";
- the computer must update first: "This computer must be updated before it can download YouTube clips, so it did not download.";
- the computer stopped partway and gave the rest back: its reason, said once, at any time in the few minutes after the job moved to it.

The dashboard's per-computer view also states, for any computer that should have downloaded a clip and did not, that computer's reason (see The dashboard: Each computer's state).

### The owner of a computer can keep it out of YouTube downloads

A computer may be kept out of YouTube downloads. Kept out, it never downloads and prepares nothing for downloading, and it is reported as "local YouTube downloads are switched off in config"; jobs then run on the server. Showing a downloaded clip in its folder, and fetching a clip from the NAS to this computer, still work.

On the YouTube page, an "on this computer" switch shows and sets the same thing for the computer the page is open on. It is ticked by default, and a page that cannot read it treats it as ticked. Flipping it says "downloads will be offered to this computer first" or "downloads will run on the server. YouTube originals only sync upwards, so you can fetch one later from the download history." A job started while it is off runs on the server, and the page says so.

- Who: an editor, for their own computer.
- Ways in: the "on this computer" switch on the YouTube page, and the computer's own settings in the app.
- Setting: This computer downloads YouTube clips. Does: lets this computer run YouTube downloads over its own connection, or keeps it out so they run on the server. Default: on. Who: an editor, for their own computer. Applies to: a computer. Search words: youtube, download here, on this computer, local download.

### The YouTube controls on an editor's computer appear only where they can be used

The app on an editor's computer shows its YouTube controls (the progress and stop of a download) only when the site has YouTube downloads on and this computer is not kept out of them; the sign-in controls additionally need the site's switch for signed-in downloads on editors' computers. When it applies, they come with a warning that downloads on this computer may start failing, or that they are running on the server because this computer could not be made ready (see "An editor is warned when downloads on their computer may start failing").

When the part is off, or the app cannot tell whether it is on, the computer behaves as if it were off: it prepares nothing for downloading, answers any request to download with "the YouTube downloader is off for this site, or switched off in config", and answers a request to show or fetch a downloaded clip with "the YouTube downloader is not enabled for this site". Quitting the app stops any YouTube download it was running; the server finishes the clips.

### An editor can stop a download running on their own computer

While a YouTube download runs on the editor's computer, the editor can stop it from the app's menu ("► Stop the YouTube download") and from the YouTube page (STOP, shown only while this computer is downloading the job, so it appears only when it will take effect).

Stopping ends the download at once, including any joining or conversion under way, and deletes the half-made files of the clip in flight. The answer is "Stopped. The server will download the clips this computer did not finish." or, with nothing running, "There was no download running on this computer." The job shows as handed back with the reason "You stopped this download on this computer. The server will download the clips this computer did not finish." If stopping fails: "CC Sync could not stop the download. Copy the diagnostics for your admin from the app's help." The page's STOP also says when the app did not answer or refused.

- Who: the editor whose computer is downloading.
- Ways in: the app's menu, and STOP on the YouTube page.

#### Lessons

- Met: YTD-052, YTD-053, YTD-055, YTD-056, YTD-057, YTD-058, YTD-059, YTD-060, YTD-062.

## One job, one computer

### One job is downloaded by one computer at a time, exactly as the job says

What a computer downloads, where to and how is always decided by the job itself: the clips, their addresses, the quality, the destination folder and the naming. Nothing on the page can make a computer download something else or write somewhere else. A computer runs one YouTube job at a time; asking it for a second is answered "this computer is already downloading job N". Only one computer ever downloads a job at once, even two computers of the same editor; when another computer already has it, the page says "<who> is already downloading this job on <computer>". A computer that is told a job is no longer its own stops at once, deletes the half-made clip, and says nothing to the editor.

Pressing DOWNLOAD or RETRY again on a finished job starts a fresh run, which may go to the editor's own computer, unless that computer had given the job up.

### When the computer doing a download goes away, the rest of the job is finished elsewhere

If the computer downloading a job goes away (the laptop is closed, it loses its network, the app quits), it loses the job within about three minutes. The rest is then finished elsewhere: by the server, or by the running computer of any signed-in editor that can take it. Every clip whose finished file is already in the folder counts as done, credited to the editor who started the job, and only the rest is fetched.

A network outage, or the server being unreachable, for up to about a minute does not lose the job, while a clear answer that the job is over still stops it. If the server stops accepting the computer's sign-in mid-job: "The dashboard no longer accepts this computer's sign-in, so it stopped downloading. The server is downloading the rest of these clips." A computer that finds nothing left to fetch gives the job straight back, so it closes at once.

A status report that arrives twice is counted once: totals never exceed the number of clips and never keep a failure that did not happen.

- On its own: taking the job back from a computer that has gone silent.

### Clips that failed in one place are tried once more in the other

When an editor's computer finishes a job with failures, every clip that failed there is tried once more on the server, never more. If YouTube bot-checks the server on that second chance, the remaining clips are marked failed without further requests, each "YouTube is blocking the server right now (it asked the server to prove it is not a bot), so the server could not retry this clip. Press RETRY to fetch it from your own computer again.", and the job ends done with "Your computer downloaded the clips it could. The server could not retry the ones that failed there, because YouTube is blocking the server right now. Press RETRY to try them from your own computer again."

#### Lessons

- Met: YTD-063, YTD-065, YTD-066.

## Choosing the destination and checking space

### Clips can be downloaded into any active project, and the page keeps the one last picked

The project list offers every active project of the studio, each once, in the person's own order, whatever computer will do the download. The project chosen when download is pressed is where the clips land, and the job shows that project. Every later step accepts any project the picker offered; a project the picker offered is never refused further on. A project that has stopped being active since the search is refused: "<project> is no longer an active project, so nothing can be downloaded into it. Start a new search."

With no active projects, the picker says "there are no projects yet", and the search and paste buttons are disabled. If the list cannot be read: "no project list available" or "could not load projects".

The page remembers the project last picked, per browser, restores it if it still exists, and never changes it except when the person does.

Computers are named in messages by their current name, falling back to their identifier.


### Clips land in the right project folder on each computer, never in a made-up folder

The job names its project as a place inside the shared project tree; each computer puts it under its own copy of the tree, wherever that is on that computer. A destination that would lead outside the tree is refused. The project's name is compared ignoring letter case, either slash direction and accent spelling.

An editor's computer downloads only into a project it syncs; a computer set to sync nothing downloads only into a project whose folder already exists on it under the exact spelling. Right before writing, the computer checks again that the project drive is really connected (on macOS, that it is mounted in its right place), so a folder is never created on the computer's own disk in its stead. Otherwise the job goes to the server, and the page says which of these applied, each followed by "The server is downloading these clips.":

- "The download did not say which project it belongs to, so this computer handed it back."
- "This computer has no folder for <project>, so it handed the download back."
- "This computer could not check whether it syncs <project>, so it handed the download back."
- "This computer does not sync <project>, so it handed the download back."
- "This computer could not work out where these clips belong on its own disk, so it handed the job back."
- "This computer's project drive is not connected, so it handed the job back."
- "This computer could not create the folder these clips go in, so it handed the job back."

- Windows and macOS: on macOS the check is that the drive is mounted in its right place.

### Before downloading, the product checks there is room and refuses with numbers

Forty long clips can need 15 to 40 GB. Expected size per second of video:

| Quality | MB per second |
|---|---|
| 480p | 0.35 |
| 720p | 0.625 |
| 1080p | 1 |
| 1440p | 2 |
| 2160p and best | 4.4 |

With durations known, twice the estimate is needed. With none known (always for pasted links) the larger of 2 GB and three minutes per clip at that rate. The review's footer shows the estimate and the free space. Free space is measured on the disk that will be written, by the computer that will write it, afresh each time download is pressed; on the server it is otherwise re-measured at most once a minute, and always after a refusal. If free space cannot be measured, the download goes ahead.

The check is made at every way a download starts (pressing download or retry, pasting links) and once more on the computer about to write, just before it fetches. A refusal is said once, in one sentence naming a button on the screen, and leaves the clips ready to retry: "there is only X GB free where these clips go (<project>/Youtube/<folder>), and these N clips need about Y GB (or "this download needs room to work in"), so nothing was started. Free some space and press DOWNLOAD again." (GET LINKS for a paste; RETRY FAILED when found as the download begins). Under 10 GB the numbers show one decimal.

On an editor's computer, a job needs at least 5 GB free plus the room that computer always keeps free, as well as room for the estimate. With less, the job goes to the server: "This computer has X GB free and this download needs about Y GB, so the server is downloading it instead." (decimal GB, one decimal place).

### If the server has lost the footage share, downloads are refused with that diagnosis

Before writing into a folder on the NAS, the share is confirmed present. When the project's folder is absent, the projects folder itself is there, and nothing in it matches the project's name (matching regardless of letter case and accent spelling), the footage tree is declared gone: nothing is created, and the editor is told "the footage tree is not there: nothing at <projects folder> looks like <project>, so nothing was started. This is the server having lost the share, not a full disk. Tell whoever runs the dashboard, and press DOWNLOAD again once it is back." A job reaching its download this way fails with the same sentence. A missing share is never reported as a full disk, and a folder that is there is never reported missing.

#### Lessons

- Met: YTD-070, YTD-067, YTD-068, YTD-069, YTD-071, YTD-072, YTD-073, YTD-074, YTD-075, YTD-076.

## Jobs on the page: queue, retry, cancel

### Each editor can queue as many jobs as they like and reorder them

A new job always goes to the back of its editor's queue. Because YouTube blocks an address that fetches too much at once, the server runs one job at a time for the whole studio: jobs already under way first, then the next waiting job of an editor who has nothing running, in that editor's own order. A job waiting for its editor's review does not block that editor's next job, and a job being downloaded on an editor's own computer does not hold up the server.

- On starting a job with others ahead: "queued behind N jobs, M of them from other editors: it starts when they finish".
- A waiting job shows "waiting to start: you are next", or "N jobs ahead of it (M from other editors)", counting every job in the studio ahead of it, on creation and after a reload. When downloading on the server is not working, it shows "the downloader on the server is not running", and the page's banner also says that jobs will queue and never start.
- A Queue list shows the editor's waiting jobs numbered in run order, each with UP, DOWN (disabled at the ends) and CANCEL; a pasted job shows as "pasted links". Moving a job renumbers the whole queue. A job that has started cannot be moved ("this job is <state>, not waiting in the queue"). The list is hidden when empty.
- A "Waiting for you" list shows the editor's jobs parked at a term review or a results review, oldest first, each with RESUME (show it) and CANCEL. It is hidden when empty. The banner says "N searches are waiting for your review". A job waiting for a person's review shows as waiting for that person, never as stuck, and never silently blocks a new search.

- Who: the editor who owns the jobs.

### Pressing DOWNLOAD fetches every ticked video not already held

DOWNLOAD queues every ticked video that is not already held, could be looked up, and has not already landed. It is refused, in this order:

1. The download terms not accepted (see "Before anyone can cause a download, they accept a notice about their responsibilities").
2. The job is not at review, done or failed: "this job is <state>, not ready for review".
3. A failed job that never got as far as queueing clips: "this job failed before any clips were queued, so there is nothing to retry. Start a new search."
4. Reopening a finished job while the editor already has a job actually running: "you already have a job in progress", naming it. Jobs waiting at a review do not count.
5. The project is no longer active (see "Clips can be downloaded into any active project, and the page keeps the one last picked").
6. Not enough free space (see "Before downloading, the product checks there is room and refuses with numbers").
7. Nothing to fetch: "nothing is selected that has not already been downloaded".

On success the job moves to downloading and any earlier failure text is cleared.

### Clips that failed can be tried again with one button

Any job with clips still owed shows a retry: on a done or failed job with failed clips, a note and RETRY N FAILED (or RETRY N CLIPS when a failed job has clips still waiting but none failed), including after a reload and when the job failed before its first clip. The message is "re-queued the clips that failed". Only failed and waiting clips are queued again. It refuses for the same reasons as DOWNLOAD, shown as red messages. Pressing DOWNLOAD again on a finished job's review does the same.

- Who: the editor who owns the job.
- Ways in: the retry button on the job's downloads, and DOWNLOAD on a finished job's review.

### An editor can cancel a job at any point

A job waiting in the queue, waiting for its terms or waiting for review is cancelled outright. A job under way stops at the next opportunity: between terms, within a few detail lookups, between clips, or within about two seconds during a clip's download, wherever it runs. The clip in flight is stopped, its partial files are removed, it goes back to waiting (so RETRY can fetch it later), and the job ends cancelled. A job being downloaded on the editor's own computer is taken off that computer too. Cancelling a finished job does nothing ("already finished"). The page says "cancelled", or while a clip is downloading "cancelling: stopping the clip in flight". Every cancel message matches the job's real phase.

Cancel buttons appear wherever a job is shown: on the progress panel (hidden once finished), the job's downloads, the review (CANCEL SEARCH), and each row of the Queue and "Waiting for you" lists. Only where results nobody has downloaded would be thrown away (the review and the "Waiting for you" list) does it ask first: "Discard this search? Nothing from it was downloaded, and its results will be thrown away."

- Who: the editor who owns the job.
- Ways in: the progress panel, the job's downloads, the review's CANCEL SEARCH, the Queue list and the "Waiting for you" list.

### A run of identical failures stops the job and says what probably broke

When three clips in a row fail in the same way (the same error once video ids, file names and numbers are ignored), the job stops before the next clip, wherever it runs. A clip that lands in between starts the count again, and a refused live stream does not count. The clips not reached stay waiting, a retry queues only the failed and waiting clips again, and the dashboard is told. The job ends failed with a note naming the likely cause in plain words:

- no usable format each time: "N clips in a row came back with no usable format. That is what a YouTube client change looks like, not a problem with these videos: the means of downloading needs updating; then press RETRY to re-queue the failed clips.";
- the same, when what YouTube now demands before handing over any format is missing: says that this is missing and that an admin has to put it right;
- YouTube refusing the media itself: says the clips were refused when the media itself was fetched, and that an admin should check that what gets past YouTube's blocks is working and that the means of downloading is up to date, then press RETRY;
- anything else: "N clips in a row failed the same way: <error>. Fix the cause, then press RETRY to re-queue the failed clips."

On an editor's computer the stop reads "<N> clips in a row failed the same way on this computer (<the error, shortened>), so it stopped at clip <i> of <total> and handed the rest back. The server is downloading them."


### A clip that fails is reported with its reason

Each clip is shown as downloading, then done (with its file name, any notes, and the title and channel from YouTube) or failed with the reason: the last 400 characters of what the download said, or "the download failed and the downloader said nothing". A download that claims success but leaves no file fails with "the downloader reported success but left no output file". A failed clip is tried again elsewhere where that can help (see "Clips that failed in one place are tried once more in the other").

### A server restart never loses a job

When the server restarts, a job caught while writing terms, searching, looking up details or filtering is put back in the queue and run again from the start (its terms and results are thrown away). A job caught downloading carries on: the clip that was in flight goes back to waiting and resumes from where it stopped. Jobs waiting for a person keep waiting.

### The editor's recent jobs are listed and can be reopened

The last 15 jobs are listed, each with its time, its state in words, "topic → project" or "links → project/Youtube", mode, languages, date range, shot types and "max N". Clicking one shows that job. If the list cannot load it shows "failed to load: <message>".

### Opening the page takes the editor straight back to the job they were working on

Every load of the page shows the running job, the queue behind it and the recently finished jobs, whatever the page address says. The job shown first is the editor's running job if any, else their newest job waiting at a review, else the first job in their queue, else the job named in the page address, else none.

#### Lessons

- Met: YTD-077, YTD-078, YTD-079, YTD-080, YTD-081, YTD-082, YTD-083.

## Progress

### The job on screen shows its state, a bar and a running commentary

States shown: queued, asking Assistant for search terms, pick the search terms, searching youtube, fetching metadata, filtering + checking for duplicates, ready for review, downloading, done, failed, cancelled. A bar moves through a fixed share per state, and searching and fetching move within their share by their counts. The commentary line shows the mode, languages, date range, "N terms (x en / y zh)", "searched i/n", candidates found, "metadata i/n", the latest term and its result count, the queue position of a waiting job, and the failure text.

The page refreshes every 1.5 seconds, slowing to every 5 seconds after two minutes; a network blip is retried. The job being shown is kept in the page address, so a reload or a shared link returns to it. A job that has vanished is let go. "done" is used even when some clips failed; those show per clip.

### While downloading, the page lists every clip with its progress and outcome

The job's downloads show its state, "N/M downloaded", how many failed, and when done "N clips landed in <path>. Click a row to open the folder". One row per clip: thumbnail, title (or the video id until it is known), and the clip's state: percent and speed, merging, converting (with what it is converting from), "failed: <reason>", "already downloaded", "done: <note>", waiting or downloading. Clicking a finished clip's row opens its folder. A clip whose earlier copy is still held open by another program says "an earlier copy of this clip is still in use (N MB reclaimable)".

For the clip in flight, wherever it runs: percent done with one decimal, speed such as "4.2 MB/s" (decimal units; KB/s below 1 MB/s, B/s below 1 KB/s), and the time left on that clip (not on the whole job). Anything unknown is shown blank, never as zero.

### The app on the editor's computer shows the download it is running

While a job runs on an editor's computer, the app shows the job's title (the search's folder name, or the project), the clip in flight with its thumbnail, how many clips are done, failed and in total, the last file that landed, and a phase: "starting", "downloading" or "converting" while it runs; afterwards "cancelled" (the editor stopped it), "handed back" (with the reason) or "finished". The app's menu carries a live line from the same figures, such as "Downloading YouTube clip 3/12 (4.2 MB/s, 38%)", dropping whatever is unknown and saying "converting" during a re-encode. After the job ends, how it ended stays readable until the app restarts, so a page that looks afterwards still learns it. The download can be stopped from there.

- Who: the editor at that computer.

### The download history lists every clip the studio has downloaded

Newest first, 24 clips at a time, with OLDER for more and "showing N of M. Click a clip to open its folder"; the header counts all clips. Each row: thumbnail, title, "<project>/<folder> · channel · who downloaded it", and when. There is one entry per YouTube video, kept for ever and never shrinking; downloading the same video into another project moves its entry there. The editor credited is the one who started the job. Every signed-in person sees the whole history.

- Who: anyone signed in.

#### Lessons

- Met: YTD-084, YTD-085.

## Reaching the editor and Resolve

### Downloaded clips reach the computer of the editor who asked

YouTube originals, like all original footage, only sync upwards: a clip downloaded on one computer reaches the server, and does not spread to every editor's computer by itself (see Sync: What syncs where). The clips of a job reach the computer of the editor who asked for them on their own, wherever they were downloaded, when that computer syncs the project. Any other editor fetches a clip in one click from the history.


### An editor can open a downloaded clip's folder, or fetch it from the NAS

Clicking a clip in the download history, or a finished clip's row in a job's downloads, asks the app on the editor's computer to show it. The page names the clip by its place in the project tree, never by a full path; a place that leads outside the tree is refused.

- When the file is on this computer, the file manager opens with it selected: "Showing <name> in <folder>". An application or disk image is shown, never opened.
- When the file is not here but its folder is, the folder opens and the page offers GET IT FROM THE NAS: "<name> is not on this computer - opened <folder> instead. YouTube originals only sync up, so a clip another editor downloaded, or one the server downloaded, stays on the NAS until you ask for it." When neither is here, nothing opens and the same explanation is given.
- GET IT FROM THE NAS copies that one file down from the project's folder on the NAS, showing "getting <file> from the NAS - N%", then "<name> is on this computer" and opens the folder. Otherwise: "the download finished but the file is not there - try again", the reason it failed (for example the drive is not connected), or "the download failed". A clip already here: "<name> is on this computer".
- If the app cannot be reached, must be updated first, or fails, the page names the folder "Projects/<path>" under the editor's sync drive, with COPY PATH ("path copied", or "copy it from the line above").

Resolve always receives a downloaded clip's full original, never a preview of it, on every computer.

- Who: anyone signed in, on their own computer.
- Ways in: a row of the download history, and a finished clip's row in a job's downloads.
- Windows and macOS: Explorer opens on Windows and Finder on macOS. On any other system: "opening a folder is only supported on Windows and macOS. The file is at <path>". On Windows a path containing a double quote cannot be shown.

### Downloaded clips are filed into the open Resolve project's bins by themselves

Once clips are on an editor's computer, they appear in the Resolve project that is open, under the YouTube bin in a bin named after the topic, each clip once:

- clips in a search's folder go to the bin Master > Youtube > <search>; clips loose in the YouTube folder (from pasted links) go to Master > Youtube;
- the project's YouTube folder is the one the studio's record of projects names for that Resolve project (matched ignoring case); without one, the folder whose name shares the most words with the project's is taken, if it has a YouTube folder;
- only those two folder levels are looked at; a folder called Proxy (any case) and hidden folders are skipped;
- a clip counts when it is a video file (MP4, MOV, MKV, WebM or M4V), not hidden, and not an unfinished, temporary, converting or kept-original file; credits records are never filed;
- a clip is filed once it has stopped changing: at least 2 minutes old and unchanged since the last look;
- the app looks about once a minute, at once when the open project changes, and again straight away while there is more to file, up to 20 clips per bin at a time;
- a clip already in the media pool, under this computer's spelling or the shared spelling, is not filed again, and a file twice is imported once; filed clips are pointed at the path spelling every computer shares, so they are online on every computer;
- in bin names, slashes become "-", leading and trailing spaces and trailing dots are dropped, an empty name becomes "Untitled", and a bin already there matches even when its name was typed on a Mac with accented letters encoded differently;
- nothing is filed if the editor has switched to another project meanwhile ("project changed"); the bin the editor has selected is never changed; if Resolve will not move the new clips into their bin, they stay where they landed and nothing is deleted;
- a clip Resolve refuses is tried again, up to 3 times, then given up on until the app restarts;
- a clip the editor removes from the media pool is not filed again while its file stays in the folder.

See Resolve on the editor's computer: Bins, clip sorting and imports.

- On its own: filing each settled clip into its bin.
- By hand: the editor can switch the filing off for their computer, and a clip they remove stays removed.
- When the help for the editing program is off: nothing is filed and nothing about the editing program is shown; the clips are in their folders.

### The owner of a computer can switch the filing off

- Setting: Filing YouTube clips into Resolve. Does: files downloaded YouTube clips into the open Resolve project's bins by themselves. Default: on. Who: an editor, for their own computer. Applies to: a computer. Search words: youtube, resolve import, bins, filing.
- When YouTube downloads is off: the filing stops, and these settings are hidden.

### The editor and the dashboard are told what the filing is doing

States, checked in this order, with the sentence shown in the app on the editor's computer:

| State | Sentence |
|---|---|
| switched off | "Filing YouTube clips into Resolve is switched off on this computer." |
| sync drive absent | "The sync drive is not available, so downloaded clips cannot be filed into Resolve." |
| syncing paused | "Syncing is paused, so downloaded clips are waiting to go into Resolve." |
| Resolve closed (no project open, a project the app leaves alone, or Resolve not reachable) | "Resolve is closed, so downloaded clips are waiting to go into it." |
| no project folder | "This Resolve project has no folder on the server yet, so downloaded clips cannot be filed into it. Ask your admin." |
| waiting for clips to settle, filing, nothing to do | no sentence |

With clips waiting, the sentence starts "<N> downloaded clip(s) is/are waiting. ". With clips given up on: "<N> downloaded clip(s) could not be filed into Resolve. CC Sync tries them again the next time it starts." and " Last error: <error>", the error being "the import failed -- see the log", "the import returned nothing usable", Resolve's own message, "the import was refused", "Resolve refused N file(s)" or "could not create the bin". Also shown: how many clips are waiting, filed and failed since the app started, and when the last one was filed and into which bin. "Nothing" is shown when nothing is keeping clips from Resolve.

The dashboard's per-computer view shows the same for each computer: a state (for example fine, no matching project, Resolve closed, sync drive missing, paused), the reason, how many are waiting, and since when, clearing when the computer stops reporting it (see The dashboard: Each computer's state).

#### Lessons

- Met: YTD-089, YTD-087, YTD-088, YTD-090.

## Keeping the downloader working

### Downloading keeps working as YouTube changes, with nothing for an editor or admin to do

YouTube changes its service often, and deliberately, in ways that break downloading, so what works one week stops working within weeks. The product keeps its means of downloading current on the server and on every computer that downloads, by itself, without waiting for a new version of the product: each moves to the newest build within a day, checked as genuine before it is used, never going backwards, in the background without delaying the start of anything. A failed update leaves the previous working one in place and is tried again within minutes, then less often. When the first signs of a YouTube change appear in a download ("requested format is not available", "HTTP Error 403"), the computer looks for a newer means at once, at most once per job.

Each computer and the server report how current their means of downloading is, what was last done, and when it was checked; something reads as installed only when it is confirmed present, and a check that could not run reads "not checked", never as fine. An editor's computer that cannot be made able to download says why, and its downloads run on the server meanwhile.

When it cannot keep up, the page, the editor and an admin are told plainly before downloads start failing (see the warnings below).

- On its own: keeping the means of downloading current everywhere.

### An editor is warned when downloads on their computer may start failing

The app on the editor's computer warns:

- "⚠ YouTube downloads on this computer may start failing: the downloader is N days old and could not update itself" (or "is out of date"); the computer still downloads meanwhile;
- "⚠ YouTube downloads on this computer are running on the server: the downloader could not be installed here";
- when the computer's tools for converting video have failed to install twice or more in a row: "This computer cannot install its video tools, so it will not make proxies or take shared media work", followed by ": <cause>" when known.

The same warning goes to the YouTube page with the computer's answer.

### A site switches YouTube downloads on and off while the server runs

Switching YouTube downloads on or off in the site's settings takes effect on the server within 5 seconds, with no restart, and on every editor's computer within about 15 minutes, without restarting the app. Off: every YouTube page and address answers "Not Found", and the part's status says "this site has not enabled the YouTube downloader". Switched on while running: the next visit brings it up; if bringing it up fails, it is not tried again for a minute, and meanwhile the pages answer "Not Found". The YouTube entry appears in the menu only while the part is working.

- Setting: YouTube downloads. Does: shows or hides YouTube downloads for everyone and starts or stops all their work. Default: off. Who: an admin. Applies to: the site. Search words: youtube, downloads, part, switch, enable.

### A health line on the page shows whether searching and downloading can work right now

The page re-reads its health every two minutes. The main mark shows the assistant's state, adds a note when the server cannot download at all, and is green when both are fine, grey when not yet known and red otherwise. Further marks appear only when relevant:

- how current the server's means of downloading is: "the running downloader is N days old"; amber with "(Nd old)" once it is past 21 days and could not update itself, saying "YouTube breaks downloaders deliberately, so downloads on this server may start failing."; red when the server has none;
- something YouTube now requires before it serves a video, when missing;
- whether what gets the server past YouTube's blocks is working, unreachable, failed to set up, or off;
- the last download ("last download: anonymous", or failed, with a rough age such as "3 min ago", or "no downloads yet"), with the state of the server's signed-in session in its tip;
- the periodic test, when switched on.

Every health mark moves both ways from live results, and one unused for a week reads "unused", not failed.

Banner lines, each on its own: no assistant set up, assistant unreachable, assistant timed out, assistant failed (with the detail), downloading not possible on the server, a missing required part, the downloader not running ("jobs will queue and never start"), no projects, the job's own error with its matching instruction, searches waiting for review, and an expired session.

When the part is off, none of this is checked.

- Who: anyone signed in.
- When the assistant is off: the main mark shows only whether downloading works.

### Admins are warned when downloading on the server or a computer is not working

Alerts, only while YouTube downloads are on (see The dashboard: Alerts by mail):

| Level | Alert | When |
|---|---|---|
| warning | "a computer's YouTube downloader is old" | a computer says its means of downloading is out of date, unless it is in fact the newest there is |
| serious | "a computer has no working YouTube downloader" | |
| serious | "the YouTube downloader is not running" | downloading on the server is not working |
| warning | "YouTube downloads are failing" | the last real download failed and the server's own test download failed too |
| warning | "this server's YouTube downloader is old" | |
| warning | the server's means of getting past YouTube's bot checks cannot be reached, or failed to set itself up | not raised when none is set up or its state is unknown |

The dashboard's per-computer view shows each computer's YouTube state: whether it can download, how current its means of downloading is, its last message (up to 300 characters) and when it was checked, whether its video tools are installed (naming up to 4 that failed, the cause and how many tries in a row have failed), and its last real download.

### An optional periodic test checks that YouTube still serves a known video

When an admin switches it on, at most every five minutes the server fetches a known short public video at 1080p exactly as a real download would (without signing in first, and signed in only after a bot check and only with a real signed-in session), and shows the result on the health line: "canary ok", "canary failed" or "no run yet". Hidden when off.

- Setting: Periodic YouTube test. Does: tests at a set interval, of at least five minutes, that YouTube still serves a known video, so a block is noticed before an editor needs a download. Default: off. Who: an admin. Applies to: the site. Search words: youtube test, canary, health, check downloads.

#### Lessons

- Met: YTD-093, YTD-094, YTD-095.

## The assistant behind search

### Two search modes: footage of a subject, or news reporting

Each search is either VISUALS (the default) or NEWS MONTAGE, chosen per search, shown on the job and never changed afterwards. Switching mode brings back the shot types the editor last left ticked in that mode (the mode's preset the first time).

- VISUALS: the assistant writes queries that surface footage OF the topic (places, people, events, on-location footage, aerials, walk-throughs, ceremonies, press events, synonyms, names, related events), and keeps a result only if it is footage of the subject that can be cut into a timeline, not coverage about it. Narration in a language the editor cannot use does not matter. Preset: the six footage shot types.
- NEWS MONTAGE: queries surface reporting whose sound tells the story, naming people, places, organisations, events, outlets and programmes, and favouring news packages, bulletins, field reports, correspondent pieces, press conferences, briefings, statements and substantive interviews, with filing words in both languages (news, report, press conference, briefing, statement, interview, full speech, and their Taiwanese Chinese equivalents). Results are judged on their speech first and pictures second: clear speech beats prettier pictures, a fuller statement beats a 30-second summary, either language is accepted but a clip that stays in one language is preferred. Preset: the three coverage shot types.

Any expansion of a named title, such as a show or a film, stays about that title, never about its setting.

- When the assistant is off: no mode is offered.

### Nine shot-type boxes steer what the search looks for and keeps

Two groups, captioned "SHOTS OF IT = footage of the subject; ALSO KEEP = people talking about it", with a short explanation of each group on the page:

- Shots of it (ticked by default in visuals mode): Aerial / drone; Establishing / exteriors; Walk-through / POV / street; Timelapse; Ceremonies / events / protests; Raw / uncut / no commentary.
- Also keep (unticked by default in visuals mode): Interviews / talking heads; News reports; Commentary / analysis / reaction.

Each ticked type makes the assistant search with its phrasings, in English and Taiwanese Chinese, and keep results of that type. Each UNTICKED "also keep" type is actively avoided in searching and dropped in judging: interviews and talk or panel shows; studio segments, anchors, desk reads and pieces to camera (but a field report whose shots carry it is kept); commentary, analysis, explainers, reaction videos, podcasts and vlogs. An unticked footage type changes nothing.

With any footage type ticked in visuals mode, at least two thirds of the queries in each language carry one of the ticked phrasings, and compilations under heavy overlays are dropped. With Raw ticked, the longer, steadier, less-edited result is preferred.

Nothing ticked, or everything ticked, means no shot-type preference: the topic is searched broadly. The page says "nothing ticked: no bias, Assistant searches and filters on the topic alone" or the same for everything ticked.

Whatever is ticked, unrelated results, music, gaming, AI-generated videos and still-image slideshows are dropped; in news mode also silent, ambient or narration-free footage, music-only footage, talk about something else, and round-ups that only mention the subject. When it is unclear, a result is KEPT.

- When the assistant is off: the shot types are not offered.

### The editor chooses the languages to search in, or exactly what they typed

Four choices, each with a short note under it:

| Choice | What is searched |
|---|---|
| EN + ZH (the default) | 8 to 12 English queries and 8 to 12 Traditional Chinese queries as used in Taiwan (never Simplified, never mainland terms); every Chinese query carries an English gloss |
| ENGLISH ONLY | 16 to 24 English queries; results whose title and channel show another language are dropped, and those whose language cannot be told are kept |
| CHINESE ONLY | 16 to 24 Traditional Chinese queries (proper nouns may stay in English inside them), each with an English gloss; plainly other-language results are dropped |
| MY TERM ONLY | no queries are written; one search of exactly the typed text, with no expansion, collecting up to the whole candidate limit, with no term review. The results are still judged for relevance when the assistant is available. This search works when the assistant is unavailable or switched off. |

Queries are 2 to 6 words, without quotes or search operators. A query in a language the choice excludes is never searched. The editor's own topic counts as Chinese if it contains any Chinese character, else English.

- When the assistant is off: MY TERM ONLY is the only search, and no language choice is shown.

### The assistant judges every result and drops the ones that do not fit

The assistant sees each result's title (first 120 characters), channel (first 60) and duration, and keeps or drops it under the rules of the mode, shot types and languages chosen. A dropped result is unticked with the assistant's reason (about ten words at most, shown up to 80 characters) or "not relevant to the topic". A result the assistant did not mention stays relevant.

Anything taken from YouTube or typed by the editor reaches the assistant fenced as material to judge, never as instructions, whichever assistant is used.

If the assistant fails, the job does not fail: it shows "<assistant problem> the relevance filter could not run, so every result below is shown unfiltered" and the review goes ahead, so the editor knows the list is unfiltered and why.

- When the assistant is off: results are not judged; only the set-aside rules for length, dates and duplicates apply, and nothing on the page mentions a relevance filter.

### The assistant behind search is the one the site has set up, and every failure is explained

Each search uses the assistant the site has set up at that moment, so a key added, changed or removed in settings applies to the next search with no restart (see The whole product: The assistant). Failures, each with an instruction on the page:

- None set up: "this site has no working Assistant. An admin must set one up in settings. Until then no job can generate search terms." A MY TERM ONLY search still works.
- A key missing, rejected or not allowed, or an assistant whose sign-in has expired and cannot refresh: says so, names where an admin fixes it, and reads "Sign in again" wherever an expired sign-in shows.
- An assistant that needs a permission the site has not given: "Assistant is not enabled for this site".
- No answer in time (about three minutes): "did not answer within N s".
- Unreachable; declined the request; an unusable or empty reply (tried once more first).

A failed job carries the assistant's own reason, never a bare "no assistant". The page's health line carries the latest state, set by every real search and, while it is not well, re-checked on its own at least every five minutes until it passes. Only the assistant the admin chose is ever checked, so no paid call goes to one that will not be used. Keys never appear on the page.

- When the assistant is off: no assistant state, banner or control is shown, and searches are MY TERM ONLY.

#### Lessons

- Met: YTD-097, YTD-099, YTD-100, YTD-101, YTD-102.

## Rights and terms

### Before anyone can cause a download, they accept a notice about their responsibilities

The notice is titled "Before you download: your responsibilities" and sits above everything else on the page, in a scrollable box with an I ACCEPT button. It has four numbered statements:

1. you confirm you have the right to use the material (you own it, have a licence or permission, it is public domain or openly licensed, or an exception such as fair dealing or fair use applies);
2. you are responsible for complying with YouTube's terms of service and copyright law;
3. the product grants no rights in downloaded material and makes no representation that a download is lawful;
4. your username, the computer's name, the clip and the time are recorded and downloads are attributed to you.

It ends: "If you cannot make these statements about the material you are about to fetch, do not download it."

- Until the current wording is accepted, the search, paste and download buttons are disabled with the tip "Accept the download terms at the top of this page first"; pressing Enter in the topic box or Ctrl+Enter in the links box shows that sentence as a red message instead. The notice disappears once accepted.
- Accepting shows "Recorded. Thank you.", and with the page open on an editor's own computer, "Recorded. YouTube downloads can now run on this computer, for you." The time of the first acceptance of each wording is kept; pressing accept again changes nothing.
- The wording carries a version. A change to the words asks everyone again, keeping the old acceptances; a change of punctuation alone never does.
- If the wording changed while the page was open, accepting is refused with "the terms were updated while this page was open. Reload and read the new wording before accepting" and the page reloads itself.
- The acceptance is checked again at every act that causes a download: starting a search, pasting links, pressing download or retry (a review can sit for a week), and an editor's own computer taking a job. Refusal: "you have not accepted the YouTube download terms. Open the YouTube downloader and read the notice at the top of the page, then press Accept."
- If the record of acceptances cannot be read, everyone is treated as not having accepted, so downloads are refused rather than allowed. If the page cannot ask whether the notice was accepted, it leaves its buttons as they are and lets the refusal come when the person acts.

- Who: anyone signed in, for themselves.

### Each editor's acceptance counts for the computer it was given on

An acceptance is recorded with the person, the version of the wording, the time and the computer the page was open on, and it counts for that computer's own downloads as well: an editor accepts once per wording on each computer they use, on the YouTube page, and nowhere else. On a computer where this person has not yet accepted the current wording, the notice shows again at the top of the page.

The acceptance counts only for the same editor and the same words: a re-worded notice, another editor signing in on that computer, or a lost record all mean the terms must be accepted again before that computer downloads.

- Who: an editor, for themselves on each computer they use.

### Two standing lines about copyright and YouTube's limits are always on the page

Shown at the bottom of the page whether or not the notice is accepted:

- "Material downloaded here belongs to whoever made it. Clearing the rights for anything you cut into a deliverable is your responsibility, and this tool grants you none of them."
- "Downloads are paced deliberately and are not guaranteed to succeed. YouTube rate-limits, blocks and changes its service without notice; bulk or automated retrieval may breach its terms and may stop working at any time. Do not build a workflow that depends on this feature being fast, available, or complete."

### Only YouTube addresses are ever downloaded

A clip whose address is not a web address on YouTube (youtube.com, music.youtube.com, youtube-nocookie.com, youtu.be, or YouTube's video servers on googlevideo.com) is refused and reported failed: "the download URL was not a YouTube URL, so this computer refused it".

#### Lessons

- Met: YTD-103, YTD-104.
