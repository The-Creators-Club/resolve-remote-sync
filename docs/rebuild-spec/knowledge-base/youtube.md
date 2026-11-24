# YouTube downloads: what real use taught

96 lessons. Each is one rule the product can be tested against: what a person saw (the heading), why it happened, and what the product must do. Kinds: *given* is a fact about something the studio has whatever is built; *ruling* is the owner's decision; *situation* is something the product must survive.

## Searching and reviewing results

### YTD-001: YouTube's search has no free date range, only five fixed upload windows.
- Why: YouTube's search filter offers only five fixed upload-date windows, which cannot say "2019", and its search-page results carry no upload date.
- Must: A date range an editor sets is applied after the search, removes every result outside it, and is shown on every view of the job.
- Kind: given

### YTD-002: An archive channel's uploads are barely reachable through YouTube search.
- Why: Whole archive channels, one holding 34,000 newsreels, are barely reachable by search; listing the channel's uploads and filtering titles, or date-stamped queries, found them.
- Must: Footage search can list every upload of a named channel and filter it by title.
- Kind: given

### YTD-003: Some news uploads carry a sign-language signer burned into the picture.
- Why: Taiwan's public broadcaster posts sign-language versions of bulletins with the same audio and a signer inset in frame; the same story usually exists without it.
- Must: A downloaded news clip with a burned-in signer is flagged, pointing to a plain version of the same story where one exists.
- Kind: given

### YTD-004: One topic becomes English and Taiwanese Chinese searches, reviewed before download.
- Why: The owner wanted one typed topic expanded into related English and Traditional Chinese (Taiwan) searches, each Chinese term with an English gloss, listed for review and downloaded together.
- Must: One topic yields English and Chinese searches and one review list with relevant results ticked, downloading into the chosen project in a subfolder named after the topic.
- Kind: ruling

### YTD-005: The search terms are shown, ticked, before searching, and searches queue.
- Why: The owner: "show a list of the search terms it is going to use (for chinese ones, it should show a translation in brackets)... there should also be a queue."
- Must: Every term is listed ticked, Chinese ones with a bracketed English translation, with tick all and untick all; further searches queue behind the running one.
- Kind: ruling

### YTD-006: A search can be English only, Chinese only, or the exact term, with dates.
- Why: Every search expanded into both languages; the owner asked for "'only english', 'only chinese' or 'single search term only'" and "a date selector".
- Must: Each search picks both languages (the default), one, or the typed term only, plus an optional upload-date range; the scope is remembered per browser, the dates never.
- Kind: ruling

### YTD-007: A search is either for visuals or for a news montage, chosen per search.
- Why: The owner: "If you're downloading for montages, you ideally just want news clips with lots of relevant audio"; footage searches and reporting searches judge different things.
- Must: Each search is for pictures or for on-topic speech, with its own preset filters, shown on the job and never changed afterwards; the page explains each filter group.
- Kind: ruling

### YTD-008: A visuals search favours shots of the subject, adjustable with checkboxes.
- Why: The owner: "if we search 'presidential palace' we're looking for visuals of presidential palace", then "make it a series of check boxes so the user can decide and tweak it".
- Must: By default establishing shots, aerials, walk-throughs and raw footage beat panels, commentary and reactions; "shots of" boxes only seek, "also keep" boxes drop when unticked; all or none means no bias.
- Kind: ruling

### YTD-009: A search for a named show returned aerials of its setting, not the show.
- Why: Expanding "bojack horseman" into shot queries about its setting returned Hollywood-sign aerials instead of the show itself.
- Must: An editor can search exactly the typed term with no expansion, and any expansion of a named title stays about that title.
- Kind: ruling

### YTD-010: Videos longer than half an hour are skipped.
- Why: The owner ruled the downloader "should skip videos over half an hour long".
- Must: Search results longer than 30 minutes are left out of downloads.
- Kind: ruling

### YTD-011: A video the studio already had was downloaded again.
- Why: The owner required duplicates to be flagged and refused; one download path skipped the last check before fetching and moved the clip's history record to the new project.
- Must: A video the studio has is marked duplicate in review, refused if picked, and checked again on any computer just before fetching, recording a duplicate instead.
- Kind: ruling

### YTD-018: A pasted link downloads into the project's YouTube folder and joins a history.
- Why: The owner wanted a link box that behaves like search; a link has no search term, so it files at the root of the project's YouTube folder.
- Must: A pasted link downloads into the chosen project's YouTube folder, imports into Resolve, and joins a history showing thumbnail and title that opens its folder on click.
- Kind: ruling

### YTD-019: Pasted links can be sent into a subfolder the person types.
- Why: The owner: "there should be a way to manually input the name of the folder/bin you want links you are downloading to go into".
- Must: A folder box beside the paste box names a safe subfolder under the chosen project, remembered per browser; blank keeps the default.
- Kind: ruling

### YTD-012: A chosen maximum of 100 candidates still looked up 327 videos.
- Why: The person picks how many candidates a search looks up, with a safe default, and the chosen limit was ignored.
- Must: The chosen maximum (default 100) caps how many videos are looked up, and a value outside the offered choices is refused, never silently changed.
- Kind: situation

### YTD-013: Results with unknown upload dates passed a date range unchecked.
- Why: Search-page results carry no upload date, so they cannot be checked against the range a person chose.
- Must: Such a result stays visible but arrives unticked, with a note that its date is unknown and was not checked against the range.
- Kind: situation

### YTD-014: All 300 results arrived marked relevant, and nothing said they were unfiltered.
- Why: With no assistant available to judge relevance, every candidate arrived marked relevant under a generic hint.
- Must: When the assistant could not filter results, the page says the list is unfiltered and how to fix it.
- Kind: situation

### YTD-015: Clicking a clip's title to watch it changed what would be downloaded.
- Why: A click on the title link also ticked or unticked the clip and saved the change at once.
- Must: Previewing a clip never changes its download selection; only the tick control does.
- Kind: situation

### YTD-016: Unticking clips mid-download changed nothing; a new scope kept the old ticks.
- Why: The download held its to-do list for the whole job, and choosing "relevant" did not untick rows an earlier "all" pass had ticked.
- Must: Unticking a clip during a download stops it being fetched, and choosing a selection scope replaces the previous selection.
- Kind: situation

### YTD-017: After the first clip, the download button greyed out for good.
- Why: The button allowed downloading only before any clip of the search was fetched.
- Must: An editor can download further clips from a finished search without searching again.
- Kind: situation

## How YouTube throttles and refuses

### YTD-020: About a hundred quick lookups from one address got it blocked for hours.
- Why: About 24 searches in two seconds, or 112 rapid per-video lookups, from one address tripped YouTube's bot check for hours; a home connection fetching its own picks was not blocked.
- Must: Searches and per-video lookups share one pace (at most 80 a minute, about 2 s between searches), and details a search already returned are reused, never fetched again.
- Kind: given

### YTD-021: YouTube can bot-check a whole address: search works, video details are refused.
- Why: From a flagged address search answers, but every video's details say "Sign in to confirm you're not a bot", signed in or not; a VPN on the same network fails; another address works.
- Must: A refused details lookup ends only that pass: results reach review on search-page data, failing only if no clip has a length, and downloads run from another address.
- Kind: given

### YTD-022: YouTube bot-checks anonymous downloads while search keeps working.
- Why: YouTube can refuse anonymous bulk downloads as a bot check while search and video details still answer.
- Must: A bot-check refusal is reported as one, never as a missing video or a network fault.
- Kind: given

### YTD-023: Without a proof-of-origin token, YouTube refuses media or serves only slow streams.
- Why: YouTube binds most media links to a proof-of-origin token; without one, fetches get 403 or crawl near 1.8 MiB/s, some ending "downloaded file is empty"; enforcement tightened within one day.
- Must: Every computer that downloads passes the token check, a missing token helper raises an alert, and every failure is logged with YouTube's own error text.
- Kind: given

### YTD-024: Long videos crawl at 3-4 MiB/s on one connection; six at once reach 53.
- Why: YouTube paces each connection on long videos and often withholds direct formats, leaving segmented streams; a 36-minute clip ran 3-4 MiB/s one segment at a time, 53 MiB/s six at once.
- Must: Downloads fall back to segmented streams when direct formats are refused and fetch about six pieces at once, sustaining well over 10 MiB/s on a fast line.
- Kind: given

### YTD-025: Old uploads refuse direct downloads but allow streamed ones.
- Why: Uploads from about 2008-2012 answer 403 on every direct format while their streamed formats download fine; 38 of 113 picks failed this way.
- Must: A download refused with 403 on direct formats is retried on streamed formats before it is reported failed.
- Kind: given

### YTD-026: One quality of a clip can arrive truncated every time while another works.
- Why: One clip's 1080p stream died at about 10 MB on every attempt from two different networks, while 720p downloaded fine.
- Must: A truncated download retries once a quality lower and records it; a transient refusal never lowers quality, and a final failure removes its partial files.
- Kind: given

### YTD-027: YouTube can list a clip's formats and then refuse its bytes.
- Why: Format discovery can succeed and the download itself then fail with HTTP 403, so a simulated fetch proves nothing.
- Must: A download health check reports working only after one real download through the same path real jobs use.
- Kind: given

### YTD-028: A live-stream link never finishes downloading.
- Why: A live stream records until it ends, so its download never finished and blocked every download queued behind it.
- Must: A live-stream link is refused or stopped at a set time limit, no download holds the downloader past a limit, and cancel stops one in progress within seconds.
- Kind: given

### YTD-029: A multi-part video on another site arrived as its first part only.
- Why: Bilibili splits long videos into parts (分P), so a 67-minute video came down as its 3-minute opening; Bilibili also drops connections, and Vimeo now requires sign-in.
- Must: A multi-part video downloads every part, each named from its own details, and the parts together count as the video when checking what is on disk.
- Kind: given

### YTD-030: A job ground through 29 clips that all failed the same way.
- Why: One identical failure was retried per clip with the full retry budget, and no computer reported why.
- Must: Three consecutive identical failures stop the run with the likely cause in plain words and report it to the dashboard, leaving the rest pending; a retry re-queues only failed clips.
- Kind: situation

### YTD-031: One clip's timeout aborted a whole batch and lost its credits.
- Why: A single download over its time limit stopped the batch before any credit record was written.
- Must: One clip's failure or timeout fails that clip only; the batch carries on and every finished clip keeps its credits.
- Kind: situation

### YTD-032: A download sat at full CPU, wrote nothing, and never ended.
- Why: A download missing a helper it needs can hang with no output for over 100 s, where a healthy one finishes in 6.4 s.
- Must: A download that writes no bytes within a set time is stopped and reported with a reason.
- Kind: situation

## Signing in to YouTube

### YTD-033: An editor's everyday browser cannot lend its YouTube sign-in.
- Why: Chrome on Windows encrypts its cookies from other programs, a daily-use profile rotates them within days, a partial export reads as signed out, and YouTube has no automation sign-in.
- Must: The YouTube sign-in lives apart from the editor's daily browser, is checked for a real session before acceptance, is readable only by that user, and going stale is reported.
- Kind: given

### YTD-034: YouTube can flag a signed-in account so every download fails.
- Why: A flagged account still lists its feed and authenticates, but every download fails "The page needs to be reloaded", while anonymous fetching of the same clips reaches 1080p.
- Must: Downloads go anonymous first, use sign-in only after a bot check, fall back to anonymous when the account is refused, report which happened, and never urge renewing a refused session.
- Kind: given

### YTD-035: Signing in to YouTube is one click, with a warning when it lapses.
- Why: The owner asked that an editor click once, sign in on Google's own page, see a signed-in page close after 2 s, and be warned when the sign-in stops working.
- Must: Sign-in opens Google's page, detects success itself and closes after 2 s; the tray shows signed-in within seconds and warns when the session dies.
- Kind: ruling

### YTD-036: Downloads on an editor's computer are signed in and fetch age-restricted videos.
- Why: Age-restricted videos failed for a remote editor; the owner: local downloads "can get age gated videos".
- Must: An editor signs in to YouTube once from the app, their downloads then fetch age-restricted videos, and an incomplete or expired sign-in is reported.
- Kind: ruling

## Files Resolve can decode

### YTD-037: Resolve shows YouTube's VP9 and Opus downloads as Media Offline.
- Why: Resolve fails to decode the VP9 ("Failed to decode the video frame") and Opus files YouTube commonly serves, though the files are sound; AV1 rendered fine when tested; about 1,495 studio files were affected.
- Must: No downloaded clip reaches an editor's Resolve in anything but H.264 picture with AAC sound: VP9 fails to decode and Opus sound drops offline.
- Kind: given

### YTD-038: Opus audio makes a clip flicker between online and offline in a timeline.
- Why: YouTube files carrying Opus audio flickered offline in a Resolve timeline; the owner asked that it be prevented and the affected clips re-encoded.
- Must: Clips already downloaded with Opus audio are found and re-encoded to AAC, and no new download lands with Opus.
- Kind: given

### YTD-039: Resolve 21 stops a render on some VP9 and AV1 YouTube clips.
- Why: Resolve 21 stops a render with "Error decoding full resolution media" on VP9 and some AV1 clips that other tools decode without trouble.
- Must: Before a render, a timeline's sources are checked for such codecs and the editor is told which clips will fail.
- Kind: given

### YTD-040: A typical editor's computer has no command-line video tools.
- Why: Editors' computers usually have no command-line encoder or media probe, so downloading there refused itself and the server did everything unnoticed.
- Must: The product brings its own verified media tools to editors' computers and never replaces ones the editor installed.
- Kind: given

### YTD-041: Every download lands as H.264 with AAC at a constant standard frame rate.
- Why: The owner: clips "are meant to be automatically converted to a correct format", on the computer that downloaded them, "no need to send back to the server"; one download route skipped it.
- Must: Every clip, by any route on any computer, is checked and if needed converted to H.264 with AAC at a constant standard frame rate under its own name, the tray saying "converting".
- Kind: ruling

### YTD-042: An undecodable download is fixed by copying its proxy, if frames match.
- Why: The owner: "just copy the proxy out into the main folder instead of re-encoding each one individually"; a 48-minute re-encode was too slow before a deadline.
- Must: An undecodable original is replaced by its proxy only when the frame counts match, keeping the original aside; otherwise it is re-encoded.
- Kind: ruling

### YTD-043: Camera originals match the "needs converting" test but must never be converted.
- Why: Sony FX3 files (H.264 with PCM audio) fail the format test used for downloads, yet they are camera originals.
- Must: Conversion applies only to downloaded clips, never to camera originals.
- Kind: situation

### YTD-044: A clip still converting was uploaded and imported in its unplayable form.
- Why: During a two- to ten-minute conversion the original sat under the final name, so it was uploaded (uploads never overwrite) and imported, and an interruption left it there for good.
- Must: Nothing sits under a clip's final name until conversion succeeds; the source waits under a name everything ignores, and an interrupted conversion leaves nothing under that name.
- Kind: situation

### YTD-045: Scratch files written inside a synced project spread and could never be deleted.
- Why: Download scratch files written into a synced project folder spread before deletion, and since deletions are not passed on, they stayed on every computer.
- Must: No temporary file is ever created inside a synced folder; work happens outside it and only finished files move in.
- Kind: situation

### YTD-046: Converted downloads left a second, broken copy in Resolve and on the NAS.
- Why: Intermediate and pre-conversion files carried video extensions, so they were imported as extra clips, and Resolve held the original open so it could not be deleted.
- Must: Only the finished clip is imported or shared, and leftovers that cannot be deleted yet are retried later and reported with their size.
- Kind: situation

## File names and what a file carries

### YTD-047: Long Chinese titles overflow the 255-byte file name limit.
- Why: Windows and NAS file systems cap a name at 255 bytes and a Chinese character takes three, so long titles failed with "Invalid argument"; Windows also caps a command line near 32K characters.
- Must: Every name the product writes, temporary ones included, is capped at 200 UTF-8 bytes keeping the video id, and long file lists never go on a command line.
- Kind: given

### YTD-048: Titles carry characters Windows forbids, and their full-width look-alikes.
- Why: Video titles contain characters Windows forbids and full-width look-alikes (？ ： ｜); a name changed by one character no longer matches its Resolve clip.
- Must: A title becomes a name legal on Windows, macOS and the NAS once, at the source, and that name is carried byte for byte everywhere.
- Kind: given

### YTD-049: Square brackets in a file name read as wildcards in Windows' scripting shell.
- Why: Downloaded files carry the YouTube id in [ ], and Windows' own scripting shell treats [ ] in a path as wildcards, so an existence test on such a name answers false.
- Must: Names containing [ ] are found, copied and checked as literal names everywhere.
- Kind: given

### YTD-050: A downloaded video carries its channel name and link inside the file.
- Why: The owner wanted the channel name and video address stored in each file's metadata, to drive credits in Resolve later.
- Must: Every downloaded video's own metadata holds its channel name and source link, readable after the file is moved or renamed, on Windows and macOS.
- Kind: ruling

### YTD-051: The same clip came out differently depending on which computer fetched it.
- Why: Downloads on editors' computers lacked embedded credits and the uploader's name, and a release could ship different naming rules to the server and a Mac.
- Must: A clip has identical name, embedded credits, credits file and history record whichever computer fetched it, and a mismatched credits format refuses the job.
- Kind: situation

## Where a download runs, and saying so

### YTD-052: The same clip must download the same way on an editor's computer and the server.
- Why: A clip hung on an editor's computer but downloaded on the server; the owner: "why don't we just make the process of downloading the exact same between server and local".
- Must: The same clip with the same settings downloads with the same result on an editor's computer and on the server.
- Kind: ruling

### YTD-053: Downloading on this computer is a switch, on by default, and fallbacks say why.
- Why: Five failures over five days all looked like "the feature doesn't work" because fallbacks to the server were silent; the owner: "we need a switch for download locally and an error and some feedback".
- Must: An "on this computer" switch defaults on, a stale page reads it as on, and every download ending on the server names its reason once and what it means for the clip.
- Kind: ruling

### YTD-055: Downloads meant for editors' computers silently ran on the server for two days.
- Why: Editors' computers lacked a needed tool and the server lacked a setting, so every job fell back to the server, which worked, so nobody noticed.
- Must: Each download records and shows which computer ran it, and health shows each computer's downloader version and last real download, so a fallback is never invisible.
- Kind: situation

### YTD-056: An editor's computer stopped downloading its own clips, and nobody knew why.
- Why: The owner asked twice why a remote editor's app was not downloading YouTube clips on his own computer; no cause was recorded.
- Must: When a computer that should download a clip does not, the dashboard states that computer's reason.
- Kind: situation

### YTD-057: A download handed back to the server gave no reason, or a bare error code.
- Why: A computer handing a job back (wrong project, no space, missing tree and more) recorded why, but the page never said, and once painted "declined the job (HTTP 503)".
- Must: Whenever a job moves to the server, the page says why in a plain sentence and that the server will finish it, never a bare HTTP code.
- Kind: situation

### YTD-058: A retried job stayed stuck on the server for good.
- Why: A retry inherited the finished run's "taken back by the server" state, so it never ran on the editor's computer again and kept hitting the address YouTube had blocked.
- Must: Pressing download again on a finished job starts a fresh run that may go to the editor's computer, unless that computer had abandoned the job.
- Kind: situation

### YTD-059: A server second chance on a blocked address failed the whole job.
- Why: While YouTube blocked the server, its second-chance download of clips an editor's computer missed failed the job outright, though the editor already had the other clips.
- Must: When the server is blocked on a second chance, the remaining clips are marked failed with "retry from your own computer" and the job ends done.
- Kind: situation

### YTD-060: Computers took download jobs they could not finish.
- Why: A computer without the tool that merges video and audio accepted jobs and failed every clip, and computers claimed qualities they could not handle, leaving jobs idle three minutes.
- Must: A computer takes a download job only if it can complete it (tools, quality, project); otherwise the job starts elsewhere at once.
- Kind: situation

### YTD-062: A failed tool install turned off downloading on that computer for a day.
- Why: After a failed install or update of the download tools the next try was 24 hours away, so one network blip at start sent that computer's downloads to the server.
- Must: A failed install or update retries within minutes with backoff, and the editor can see why downloading on their computer is off.
- Kind: situation

## One job, one computer

### YTD-063: Any editor's computer may finish another editor's lapsed download.
- Why: A review limited lapsed jobs to their creator's computers; the owner: "I want the old behaviour back", because the editors share one archive.
- Must: Once a job's hold has expired, any signed-in editor's running computer may take it over and finish it.
- Kind: ruling

### YTD-065: A three-second dashboard restart ended a 22-clip download at clip 2.
- Why: The editor's computer treated one refused connection during a brief restart as the end of the job, and the server then fetched clips the editor could not get.
- Must: A job survives the server being unreachable for up to 60 s, while a clear error answer such as "job over" still stops it.
- Kind: situation

### YTD-066: A status report sent twice showed "23 of 22".
- Why: A clip's done or failed report was re-sent when its reply was lost after the server had processed it, and each copy bumped the job's counters.
- Must: A repeated status report is counted once; totals never exceed the clip count or keep a phantom failure.
- Kind: situation

## Choosing the destination and checking space

### YTD-070: The page keeps the project the person last picked.
- Why: The picker reset to the first project on every load, so 16 searches meant for one project were filed under another.
- Must: The last chosen project is remembered per browser, restored if it still exists, and never changed except by the person.
- Kind: ruling

### YTD-067: A wired editor could choose no project as a download destination.
- Why: Destinations were the person's ticked projects, and a wired computer never ticks one; the page knew the person, not which of their computers was asking.
- Must: Destinations are every active project, whoever asks and wherever the download runs; a computer never takes a job for a project it does not hold.
- Kind: situation

### YTD-068: The project picker offered projects the next step refused.
- Why: The picker used a wider rule than creating, downloading and retrying the job, and the page never sent which computer was asking.
- Must: A job remembers where and on which computer it was accepted, and every later step accepts any project the picker offered.
- Kind: situation

### YTD-069: An editor with two computers saw every project twice.
- Why: Plans are kept per computer, and the picker listed one entry per computer.
- Must: A person's project list shows each project once, however many computers they own.
- Kind: situation

### YTD-071: Downloads landed in a different project from the one selected.
- Why: An editor picked one project on the page, yet his clips kept landing in the first project in the list.
- Must: A download lands in the project selected when download was pressed, and the job shows that project.
- Kind: situation

### YTD-072: A project with an accented name was reported missing.
- Why: The name came from a Mac, which spells accents decomposed; the NAS spells them composed, so an exact check missed a folder that existed.
- Must: Every check that a project folder exists matches names regardless of accent spelling, and never blames a missing share when the folder is there.
- Kind: situation

### YTD-073: Forty long clips can need 15 to 40 GB, and nothing checked.
- Why: 40 clips of 12 minutes at 1080p take 15-40 GB; pasted links carry no length, so 40 links into 6 GB passed a flat 2 GB guess.
- Must: Show an estimate and free space, estimating about three minutes per link of unknown length, refuse below twice the estimate, and proceed when space cannot be read.
- Kind: situation

### YTD-074: Pasted links skipped the space check, and the refusal named a hidden button.
- Why: Pasted-link jobs and server fallbacks got no free-space check, so a full NAS filled clip by clip, and the "no room" message named a retry button hidden in that state.
- Must: Every way a download starts, on any computer, checks space before fetching and refuses once, in one sentence naming a button on screen, leaving clips retryable.
- Kind: situation

### YTD-075: Space was measured on the wrong disk, and freeing space changed nothing.
- Why: Downloads to an editor's disk were refused for lack of space on the NAS, and a refusal was kept a minute, so freeing 300 GB did nothing.
- Must: Free space is measured on the disk that will be written, by the computer writing it, afresh each time download is pressed.
- Kind: situation

### YTD-076: A lost NAS share was reported as "the disk is full".
- Why: A dropped share leaves its empty folder on the server's own small disk, so space reads that disk and downloads "succeed" there, then vanish and block re-downloading.
- Must: Before writing into a NAS folder the share is confirmed present; if not, the refusal says the share is missing, never that the disk is full.
- Kind: situation

## Jobs on the page: queue, retry, cancel

### YTD-077: Leaving the page and coming back made twelve pasted links seem lost.
- Why: The downloads ran fine, but the reopened page showed nothing, so the owner thought his links were "eaten".
- Must: Every load of the page shows the running job, the queue behind it and recently finished jobs, whatever the address says.
- Kind: situation

### YTD-078: A reload showed last week's parked search instead of the running download.
- Why: After a reload the page attached to the oldest unfinished job, a week-old search awaiting review, and the downloading job appeared nowhere.
- Must: The page shows the running job first, then the newest parked one, and lists every parked search with resume and cancel.
- Kind: situation

### YTD-079: A search nobody downloaded from blocked every later search.
- Why: A search left at review counted as the editor's active job, so new searches did nothing, and cancel claimed "stops after the video in flight" with nothing in flight.
- Must: A search left at review never silently blocks a new one: it is shown, can be discarded in one obvious click, and every cancel message matches the job's real phase.
- Kind: situation

### YTD-080: A queued job showed "0 ahead" behind another editor's long job.
- Why: The server downloads one job at a time for the whole studio, but the position counted only the editor's own jobs.
- Must: A queued job shows how many studio-wide jobs are ahead and whether the downloader is running, on creation and after a reload.
- Kind: situation

### YTD-081: The queue looked stuck while jobs waited for their creators' review.
- Why: All four open jobs were waiting at review steps only the person who created them can do, and nothing showed that.
- Must: A job waiting for a person's review shows as waiting for that named person, never as stuck.
- Kind: situation

### YTD-082: A job that failed before its first clip offered no retry.
- Why: The failure message said to press retry, but the button appeared only once clip details had loaded, which never happens for such a job or after a reload.
- Must: Any job with clips still owed shows retry, including after a reload and when it failed before the first clip.
- Kind: situation

### YTD-083: Cancel did nothing while a download ran on an editor's computer.
- Why: Cancel, and "download on the server instead", took effect only after the editor's computer finished, so every clip landed under a "cancelling" message.
- Must: Cancel stops a download on an editor's computer within about two seconds, leaving the clip in flight for retry; a hand-back button appears only when it takes effect.
- Kind: situation

## Progress

### YTD-084: The tray says "Downloading x/x (xx MB/s)" while it fetches.
- Why: Downloads on the editor's computer were invisible in the tray and felt slow; the owner asked for "Downloading: x/x (xx mb/s)".
- Must: While downloading, the tray reads like "Downloading YouTube clip 3/12 (4.2 MB/s, 38%)", live, dropping what is unknown, and says "converting" during a re-encode.
- Kind: ruling

### YTD-085: A one-video download sat at 0%, and a job countdown ran backwards.
- Why: Progress counted only finished videos, a job-wide average jumped backwards because clips differ tenfold in length, and a forty-minute local download showed only "downloading".
- Must: Page and tray show clip N of M plus the in-flight clip's thumbnail, percent, speed and time left; unknown is blank, never zero; a local download can be stopped there.
- Kind: situation

## Reaching the editor and Resolve

### YTD-089: Downloaded clips land in Resolve in a bin named after their topic.
- Why: The owner wanted downloads imported automatically into the open project's YouTube bin, inside a bin named after the search topic.
- Must: Once on an editor's computer, clips appear under the YouTube bin in a bin named after the topic, each clip once.
- Kind: ruling

### YTD-087: A clip downloaded on the server never reached the editor who asked.
- Why: Originals only travel up to the NAS, so every server fallback left the clip where the requesting editor could not get it.
- Must: A job's clips reach the asking editor's computer by themselves when it syncs the project; any other history clip missing there can be fetched from the NAS in one click.
- Kind: situation

### YTD-088: An editor imported 540p previews because the originals never reached him.
- Why: Only the previews of downloaded clips reached a remote editor, so he imported those into the shared project; the owner called it "clearly incorrect behaviour".
- Must: Resolve always receives a downloaded clip's full original, never its preview, on every computer.
- Kind: situation

### YTD-090: Downloaded clips never reached Resolve, and nobody knew.
- Why: Clips landed in the project but the import stopped (no matching project, Resolve closed, drive absent), visible on neither side.
- Must: Clips waiting for Resolve, and an import that gave up, show with the reason on the editor's computer and on the dashboard.
- Kind: situation

See also, filed under another capability:

- ALL-075 (The whole product): Explorer ignores its select switch when the switch arrives inside quotes.
- SYN-009 (Sync): YouTube originals go up, and come down only to the editor who asked.

## Keeping the downloader working

### YTD-093: The downloader takes its newest daily build everywhere, without a product release.
- Why: YouTube changes break downloaders within days while stable releases lag weeks; the owner: "accept any ... build, daily etc, to get the latest", "without having to do a full new build".
- Must: The server and every computer move to the newest verified daily build within a day, in the background without delaying startup, never downgrading, and report their version.
- Kind: ruling

### YTD-094: A downloader too old to work was noted only in a log.
- Why: YouTube changes often break downloaders within weeks; one 43 days old that could not update itself was logged once a day.
- Must: A downloader that cannot update, or lags a known newer build, is shown to the editor and as an admin warning before downloads start failing.
- Kind: situation

### YTD-095: A wiped download helper still read "installed" and green.
- Why: Install was judged by a stamp kept apart from the files, so a wiped helper read healthy while downloads crawled near 1.8 MiB/s or landed empty.
- Must: A component reads installed only when its files are confirmed on disk; missing files reinstall, and an unverified check reads "not checked", never OK.
- Kind: situation

## The assistant behind search

### YTD-097: Text from YouTube can carry instructions aimed at the assistant.
- Why: Titles and descriptions the relevance check reads are written by strangers and can carry instructions.
- Must: Anything taken from the web reaches the assistant fenced as material to judge, never as instructions, whichever service is used.
- Kind: situation

### YTD-099: Searches failed "no AI provider" while Settings said the assistant was signed in.
- Why: The assistant's sign-in had expired and could not refresh; Settings judged it by a file existing, and the job dropped the assistant's own reason.
- Must: A sign-in that has expired and cannot refresh shows "Sign in again" everywhere, and a failed job carries the assistant's own reason, never "no provider".
- Kind: situation

### YTD-100: The assistant read "missing" for days after one failed check at startup.
- Why: A NAS often starts before its internet is up; the assistant check ran once, failed, and nothing re-checked until someone searched anyway.
- Must: A failing availability check for an outside service repeats on its own at least every five minutes until it passes.
- Kind: situation

### YTD-101: A health light that could only move one way lied for weeks.
- Why: YouTube sign-in health could only worsen and the assistant's could only turn green, so a revoked key stayed green while every search failed.
- Must: Every health status moves both ways from live results, and a week without use reads "unused", not failed.
- Kind: situation

### YTD-102: Checking assistants spent paid calls on a provider the admin had ruled out.
- Why: Every ten minutes of activity each enabled assistant was tested with a real paid call, up to 70 s, before the admin's chosen one was read.
- Must: With an assistant chosen by the admin, only that one is checked; no paid call goes to a provider that will not be used.
- Kind: situation

See also, filed under another capability:

- ACC-072 (Accounts, privacy and the legal paperwork): A helper reading outside text was handed every server credential.

## Rights and terms

### YTD-103: The downloader is off until each person and computer accepts a rights statement.
- Why: The downloader and its anti-blocking parts were installed and on everywhere, with no rights acceptance recorded.
- Must: The downloader is off by default, each person and computer records a versioned rights acceptance first, anti-blocking is a separate opt-in, and unreadable settings mean off.
- Kind: ruling

### YTD-104: A punctuation-only edit to the rights notice must not force re-agreement.
- Why: Changing the notice's version sends every editor in every studio back through the dialog.
- Must: Editors are asked to agree again only when the words agreed to change, never for punctuation alone.
- Kind: ruling
