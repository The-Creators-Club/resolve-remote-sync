# YouTube downloads

## Searching and reviewing results

### YTD-001: YouTube's search has no free date range, only five fixed upload windows.
- What was going on: YouTube's search filter offers only five fixed upload-date windows, which cannot say "2019", and its search-page results carry no upload date.
- What the product must do: A date range an editor sets is applied after the search, removes every result outside it, and is shown on every view of the job.
- Kind: 1a
- From: C02-077

### YTD-002: An archive channel's uploads are barely reachable through YouTube search.
- What was going on: Whole archive channels, one holding 34,000 newsreels, are barely reachable by search; listing the channel's uploads and filtering titles, or date-stamped queries, found them.
- What the product must do: Footage search can list every upload of a named channel and filter it by title.
- Kind: 1a
- State: outcome not found
- From: M03-079

### YTD-003: Some news uploads carry a sign-language signer burned into the picture.
- What was going on: Taiwan's public broadcaster posts sign-language versions of bulletins with the same audio and a signer inset in frame; the same story usually exists without it.
- What the product must do: A downloaded news clip with a burned-in signer is flagged, pointing to a plain version of the same story where one exists.
- Kind: 1a
- From: M04-043

### YTD-004: One topic becomes English and Taiwanese Chinese searches, reviewed before download.
- What was going on: The owner wanted one typed topic expanded into related English and Traditional Chinese (Taiwan) searches, each Chinese term with an English gloss, listed for review and downloaded together.
- What the product must do: One topic yields English and Chinese searches and one review list with relevant results ticked, downloading into the chosen project in a subfolder named after the topic.
- Kind: 2
- From: C01-080, P04-035

### YTD-005: The search terms are shown, ticked, before searching, and searches queue.
- What was going on: The owner: "show a list of the search terms it is going to use (for chinese ones, it should show a translation in brackets)... there should also be a queue."
- What the product must do: Every term is listed ticked, Chinese ones with a bracketed English translation, with tick all and untick all; further searches queue behind the running one.
- Kind: 2
- From: C03-052, P09-007

### YTD-006: A search can be English only, Chinese only, or the exact term, with dates.
- What was going on: Every search expanded into both languages; the owner asked for "'only english', 'only chinese' or 'single search term only'" and "a date selector".
- What the product must do: Each search picks both languages (the default), one, or the typed term only, plus an optional upload-date range; the scope is remembered per browser, the dates never.
- Kind: 2
- From: L03-049, M03-012, P07-021

### YTD-007: A search is either for visuals or for a news montage, chosen per search.
- What was going on: The owner: "If you're downloading for montages, you ideally just want news clips with lots of relevant audio"; footage searches and reporting searches judge different things.
- What the product must do: Each search is for pictures or for on-topic speech, with its own preset filters, shown on the job and never changed afterwards; the page explains each filter group.
- Kind: 2
- From: P06-048, C02-054

### YTD-008: A visuals search favours shots of the subject, adjustable with checkboxes.
- What was going on: The owner: "if we search 'presidential palace' we're looking for visuals of presidential palace", then "make it a series of check boxes so the user can decide and tweak it".
- What the product must do: By default establishing shots, aerials, walk-throughs and raw footage beat panels, commentary and reactions; "shots of" boxes only seek, "also keep" boxes drop when unticked; all or none means no bias.
- Kind: 2
- From: P05-004, C01-086

### YTD-009: A search for a named show returned aerials of its setting, not the show.
- What was going on: Expanding "bojack horseman" into shot queries about its setting returned Hollywood-sign aerials instead of the show itself.
- What the product must do: An editor can search exactly the typed term with no expansion, and any expansion of a named title stays about that title.
- Kind: 2
- State: still open
- Check: Is an expansion of a named title now kept about the title, or is the exact-term scope the whole answer?
- From: M02-100, P06-049

### YTD-010: Videos longer than half an hour are skipped.
- What was going on: The owner ruled the downloader "should skip videos over half an hour long".
- What the product must do: Search results longer than 30 minutes are left out of downloads.
- Kind: 2
- State: outcome not found
- From: P05-030

### YTD-011: A video the studio already had was downloaded again.
- What was going on: The owner required duplicates to be flagged and refused; one download path skipped the last check before fetching and moved the clip's history record to the new project.
- What the product must do: A video the studio has is marked duplicate in review, refused if picked, and checked again on any computer just before fetching, recording a duplicate instead.
- Kind: 2
- From: P04-036, H01-064

### YTD-012: A chosen maximum of 100 candidates still looked up 327 videos.
- What was going on: The person picks how many candidates a search looks up, with a safe default, and the chosen limit was ignored.
- What the product must do: The chosen maximum (default 100) caps how many videos are looked up, and a value outside the offered choices is refused, never silently changed.
- Kind: 3
- From: P05-005

### YTD-013: Results with unknown upload dates passed a date range unchecked.
- What was going on: Search-page results carry no upload date, so they cannot be checked against the range a person chose.
- What the product must do: Such a result stays visible but arrives unticked, with a note that its date is unknown and was not checked against the range.
- Kind: 3
- From: L10-088

### YTD-014: All 300 results arrived marked relevant, and nothing said they were unfiltered.
- What was going on: With no assistant available to judge relevance, every candidate arrived marked relevant under a generic hint.
- What the product must do: When the assistant could not filter results, the page says the list is unfiltered and how to fix it.
- Kind: 3
- From: L04-126

### YTD-015: Clicking a clip's title to watch it changed what would be downloaded.
- What was going on: A click on the title link also ticked or unticked the clip and saved the change at once.
- What the product must do: Previewing a clip never changes its download selection; only the tick control does.
- Kind: 3
- From: H06-095

### YTD-016: Unticking clips mid-download changed nothing; a new scope kept the old ticks.
- What was going on: The download held its to-do list for the whole job, and choosing "relevant" did not untick rows an earlier "all" pass had ticked.
- What the product must do: Unticking a clip during a download stops it being fetched, and choosing a selection scope replaces the previous selection.
- Kind: 3
- State: outcome not found
- From: M03-014

### YTD-017: After the first clip, the download button greyed out for good.
- What was going on: The button allowed downloading only before any clip of the search was fetched.
- What the product must do: An editor can download further clips from a finished search without searching again.
- Kind: 3
- From: P06-056, L01-064

### YTD-018: A pasted link downloads into the project's YouTube folder and joins a history.
- What was going on: The owner wanted a link box that behaves like search; a link has no search term, so it files at the root of the project's YouTube folder.
- What the product must do: A pasted link downloads into the chosen project's YouTube folder, imports into Resolve, and joins a history showing thumbnail and title that opens its folder on click.
- Kind: 2
- From: P05-006

### YTD-019: Pasted links can be sent into a subfolder the person types.
- What was going on: The owner: "there should be a way to manually input the name of the folder/bin you want links you are downloading to go into".
- What the product must do: A folder box beside the paste box names a safe subfolder under the chosen project, remembered per browser; blank keeps the default.
- Kind: 2
- From: P09-010, L01-090

## How YouTube throttles and refuses

### YTD-020: About a hundred quick lookups from one address got it blocked for hours.
- What was going on: About 24 searches in two seconds, or 112 rapid per-video lookups, from one address tripped YouTube's bot check for hours; a home connection fetching its own picks was not blocked.
- What the product must do: Searches and per-video lookups share one pace (at most 80 a minute, about 2 s between searches), and details a search already returned are reused, never fetched again.
- Kind: 1a
- From: P05-003, C01-083, H01-066

### YTD-021: YouTube can bot-check a whole address: search works, video details are refused.
- What was going on: From a flagged address search answers, but every video's details say "Sign in to confirm you're not a bot", signed in or not; a VPN on the same network fails; another address works.
- What the product must do: A refused details lookup ends only that pass: results reach review on search-page data, failing only if no clip has a length, and downloads run from another address.
- Kind: 1a
- From: P14-003, M03-004, P13-025, C04-026, L10-086, L10-087

### YTD-022: YouTube bot-checks anonymous downloads while search keeps working.
- What was going on: YouTube can refuse anonymous bulk downloads as a bot check while search and video details still answer.
- What the product must do: A bot-check refusal is reported as one, never as a missing video or a network fault.
- Kind: 1a
- From: M06-003

### YTD-023: Without a proof-of-origin token, YouTube refuses media or serves only slow streams.
- What was going on: YouTube binds most media links to a proof-of-origin token; without one, fetches get 403 or crawl near 1.8 MiB/s, some ending "downloaded file is empty"; enforcement tightened within one day.
- What the product must do: Every computer that downloads passes the token check, a missing token helper raises an alert, and every failure is logged with YouTube's own error text.
- Kind: 1a
- From: P07-018, M03-002

### YTD-024: Long videos crawl at 3-4 MiB/s on one connection; six at once reach 53.
- What was going on: YouTube paces each connection on long videos and often withholds direct formats, leaving segmented streams; a 36-minute clip ran 3-4 MiB/s one segment at a time, 53 MiB/s six at once.
- What the product must do: Downloads fall back to segmented streams when direct formats are refused and fetch about six pieces at once, sustaining well over 10 MiB/s on a fast line.
- Kind: 1a
- From: P07-019, M03-003, L03-048

### YTD-025: Old uploads refuse direct downloads but allow streamed ones.
- What was going on: Uploads from about 2008-2012 answer 403 on every direct format while their streamed formats download fine; 38 of 113 picks failed this way.
- What the product must do: A download refused with 403 on direct formats is retried on streamed formats before it is reported failed.
- Kind: 1a
- From: C06-049

### YTD-026: One quality of a clip can arrive truncated every time while another works.
- What was going on: One clip's 1080p stream died at about 10 MB on every attempt from two different networks, while 720p downloaded fine.
- What the product must do: A truncated download retries once a quality lower and records it; a transient refusal never lowers quality, and a final failure removes its partial files.
- Kind: 1a
- From: P05-014, L03-069

### YTD-027: YouTube can list a clip's formats and then refuse its bytes.
- What was going on: Format discovery can succeed and the download itself then fail with HTTP 403, so a simulated fetch proves nothing.
- What the product must do: A download health check reports working only after one real download through the same path real jobs use.
- Kind: 1a
- From: L03-045

### YTD-028: A live-stream link never finishes downloading.
- What was going on: A live stream records until it ends, so its download never finished and blocked every download queued behind it.
- What the product must do: A live-stream link is refused or stopped at a set time limit, no download holds the downloader past a limit, and cancel stops one in progress within seconds.
- Kind: 1a
- State: fixed, never shipped
- From: L11-075, H08-056

### YTD-029: A multi-part video on another site arrived as its first part only.
- What was going on: Bilibili splits long videos into parts (分P), so a 67-minute video came down as its 3-minute opening; Bilibili also drops connections, and Vimeo now requires sign-in.
- What the product must do: A multi-part video downloads every part, each named from its own details, and the parts together count as the video when checking what is on disk.
- Kind: 1a
- From: C06-050, M03-080

### YTD-030: A job ground through 29 clips that all failed the same way.
- What was going on: One identical failure was retried per clip with the full retry budget, and no computer reported why.
- What the product must do: Three consecutive identical failures stop the run with the likely cause in plain words and report it to the dashboard, leaving the rest pending; a retry re-queues only failed clips.
- Kind: 3
- From: C02-082, L03-044, P07-025

### YTD-031: One clip's timeout aborted a whole batch and lost its credits.
- What was going on: A single download over its time limit stopped the batch before any credit record was written.
- What the product must do: One clip's failure or timeout fails that clip only; the batch carries on and every finished clip keeps its credits.
- Kind: 3
- From: C06-051

### YTD-032: A download sat at full CPU, wrote nothing, and never ended.
- What was going on: A download missing a helper it needs can hang with no output for over 100 s, where a healthy one finishes in 6.4 s.
- What the product must do: A download that writes no bytes within a set time is stopped and reported with a reason.
- Kind: 3
- From: M02-007

## Signing in to YouTube

### YTD-033: An editor's everyday browser cannot lend its YouTube sign-in.
- What was going on: Chrome on Windows encrypts its cookies from other programs, a daily-use profile rotates them within days, a partial export reads as signed out, and YouTube has no automation sign-in.
- What the product must do: The YouTube sign-in lives apart from the editor's daily browser, is checked for a real session before acceptance, is readable only by that user, and going stale is reported.
- Kind: 1a
- From: L03-054, C01-085, M03-019

### YTD-034: YouTube can flag a signed-in account so every download fails.
- What was going on: A flagged account still lists its feed and authenticates, but every download fails "The page needs to be reloaded", while anonymous fetching of the same clips reaches 1080p.
- What the product must do: Downloads go anonymous first, use sign-in only after a bot check, fall back to anonymous when the account is refused, report which happened, and never urge renewing a refused session.
- Kind: 1a
- From: P07-024, L03-040, M03-001

### YTD-035: Signing in to YouTube is one click, with a warning when it lapses.
- What was going on: The owner asked that an editor click once, sign in on Google's own page, see a signed-in page close after 2 s, and be warned when the sign-in stops working.
- What the product must do: Sign-in opens Google's page, detects success itself and closes after 2 s; the tray shows signed-in within seconds and warns when the session dies.
- Kind: 2
- From: P06-009, P06-010

### YTD-036: Downloads on an editor's computer are signed in and fetch age-restricted videos.
- What was going on: Age-restricted videos failed for a remote editor; the owner: local downloads "can get age gated videos".
- What the product must do: An editor signs in to YouTube once from the app, their downloads then fetch age-restricted videos, and an incomplete or expired sign-in is reported.
- Kind: 2
- From: P05-010

## Files Resolve can decode

### YTD-037: Resolve shows YouTube's VP9, AV1 and Opus downloads as Media Offline.
- What was going on: Resolve fails to decode the VP9 ("Failed to decode the video frame"), AV1 and Opus files YouTube commonly serves, though the files are sound; about 1,495 studio files were affected.
- What the product must do: No downloaded clip reaches any editor's Resolve in VP9, AV1 or Opus.
- Kind: 1a
- From: M02-060, P05-037

### YTD-038: Opus audio makes a clip flicker between online and offline in a timeline.
- What was going on: YouTube files carrying Opus audio flickered offline in a Resolve timeline; the owner asked that it be prevented and the affected clips re-encoded.
- What the product must do: Clips already downloaded with Opus audio are found and re-encoded to AAC, and no new download lands with Opus.
- Kind: 1a
- State: outcome not found
- From: P09-019

### YTD-039: Resolve 21 stops a render on some VP9 and AV1 YouTube clips.
- What was going on: Resolve 21 stops a render with "Error decoding full resolution media" on VP9 and some AV1 clips that other tools decode without trouble.
- What the product must do: Before a render, a timeline's sources are checked for such codecs and the editor is told which clips will fail.
- Kind: 1a
- From: M04-063

### YTD-040: A typical editor's computer has no command-line video tools.
- What was going on: Editors' computers usually have no command-line encoder or media probe, so downloading there refused itself and the server did everything unnoticed.
- What the product must do: The product brings its own verified media tools to editors' computers and never replaces ones the editor installed.
- Kind: 1a
- From: L03-051

### YTD-041: Every download lands as H.264 with AAC at a constant standard frame rate.
- What was going on: The owner: clips "are meant to be automatically converted to a correct format", on the computer that downloaded them, "no need to send back to the server"; one download route skipped it.
- What the product must do: Every clip, by any route on any computer, is checked and if needed converted to H.264 with AAC at a constant standard frame rate under its own name, the tray saying "converting".
- Kind: 2
- From: P13-023, C06-066, L03-046, M03-008, P07-023, C02-078

### YTD-042: An undecodable download is fixed by copying its proxy, if frames match.
- What was going on: The owner: "just copy the proxy out into the main folder instead of re-encoding each one individually"; a 48-minute re-encode was too slow before a deadline.
- What the product must do: An undecodable original is replaced by its proxy only when the frame counts match, keeping the original aside; otherwise it is re-encoded.
- Kind: 2
- From: M04-064

### YTD-043: Camera originals match the "needs converting" test but must never be converted.
- What was going on: Sony FX3 files (H.264 with PCM audio) fail the format test used for downloads, yet they are camera originals.
- What the product must do: Conversion applies only to downloaded clips, never to camera originals.
- Kind: 3
- From: M02-061

### YTD-044: A clip still converting was uploaded and imported in its unplayable form.
- What was going on: During a two- to ten-minute conversion the original sat under the final name, so it was uploaded (uploads never overwrite) and imported, and an interruption left it there for good.
- What the product must do: Nothing sits under a clip's final name until conversion succeeds; the source waits under a name everything ignores, and an interrupted conversion leaves nothing under that name.
- Kind: 3
- From: L10-044, H06-029, H07-035, L02-010

### YTD-045: Scratch files written inside a synced project spread and could never be deleted.
- What was going on: Download scratch files written into a synced project folder spread before deletion, and since deletions are not passed on, they stayed on every computer.
- What the product must do: No temporary file is ever created inside a synced folder; work happens outside it and only finished files move in.
- Kind: 3
- From: H01-057

### YTD-046: Converted downloads left a second, broken copy in Resolve and on the NAS.
- What was going on: Intermediate and pre-conversion files carried video extensions, so they were imported as extra clips, and Resolve held the original open so it could not be deleted.
- What the product must do: Only the finished clip is imported or shared, and leftovers that cannot be deleted yet are retried later and reported with their size.
- Kind: 3
- From: L02-033

## File names and what a file carries

### YTD-047: Long Chinese titles overflow the 255-byte file name limit.
- What was going on: Windows and NAS file systems cap a name at 255 bytes and a Chinese character takes three, so long titles failed with "Invalid argument"; Windows also caps a command line near 32K characters.
- What the product must do: Every name the product writes, temporary ones included, is capped at 200 UTF-8 bytes keeping the video id, and long file lists never go on a command line.
- Kind: 1a
- From: M02-062, M03-015, M06-002

### YTD-048: Titles carry characters Windows forbids, and their full-width look-alikes.
- What was going on: Video titles contain characters Windows forbids and full-width look-alikes (？ ： ｜); a name changed by one character no longer matches its Resolve clip.
- What the product must do: A title becomes a name legal on Windows, macOS and the NAS once, at the source, and that name is carried byte for byte everywhere.
- Kind: 1a
- From: G01-012

### YTD-049: Square brackets in a file name read as wildcards in Windows' scripting shell.
- What was going on: Downloaded files carry the YouTube id in [ ], and Windows' own scripting shell treats [ ] in a path as wildcards, so an existence test on such a name answers false.
- What the product must do: Names containing [ ] are found, copied and checked as literal names everywhere.
- Kind: 1a
- From: M05-034

### YTD-050: A downloaded video carries its channel name and link inside the file.
- What was going on: The owner wanted the channel name and video address stored in each file's metadata, to drive credits in Resolve later.
- What the product must do: Every downloaded video's own metadata holds its channel name and source link, readable after the file is moved or renamed, on Windows and macOS.
- Kind: 2
- From: P01-034

### YTD-051: The same clip came out differently depending on which computer fetched it.
- What was going on: Downloads on editors' computers lacked embedded credits and the uploader's name, and a release could ship different naming rules to the server and a Mac.
- What the product must do: A clip has identical name, embedded credits, credits file and history record whichever computer fetched it, and a mismatched credits format refuses the job.
- Kind: 3
- From: H01-059, H02-025

## Where a download runs, and saying so

### YTD-052: The same clip must download the same way on an editor's computer and the server.
- What was going on: A clip hung on an editor's computer but downloaded on the server; the owner: "why don't we just make the process of downloading the exact same between server and local".
- What the product must do: The same clip with the same settings downloads with the same result on an editor's computer and on the server.
- Kind: 2
- From: P06-059

### YTD-053: Downloading on this computer is a switch, on by default, and fallbacks say why.
- What was going on: Five failures over five days all looked like "the feature doesn't work" because fallbacks to the server were silent; the owner: "we need a switch for download locally and an error and some feedback".
- What the product must do: An "on this computer" switch defaults on, a stale page reads it as on, and every download ending on the server names its reason once and what it means for the clip.
- Kind: 2
- From: P06-054, L01-058, C02-063

### YTD-054: Every job silently went to the server because a busy app answered slowly.
- What was going on: Mid-sync the editor's app took 3.9 s to answer a 1 s check, the server started before any claim, and pasted links were never offered: 45 of 45 jobs ran there.
- What the product must do: Every download is offered to the requester's computer, which answers within 1 s even mid-sync; slow answers are retried, refusals fall back at once, and the server waits 4 s.
- Kind: 3
- From: L01-056, P06-053, L01-055, M03-010, C02-057

### YTD-055: Downloads meant for editors' computers silently ran on the server for two days.
- What was going on: Editors' computers lacked a needed tool and the server lacked a setting, so every job fell back to the server, which worked, so nobody noticed.
- What the product must do: Each download records and shows which computer ran it, and health shows each computer's downloader version and last real download, so a fallback is never invisible.
- Kind: 3
- From: C01-091, P05-011, L03-043

### YTD-056: An editor's computer stopped downloading its own clips, and nobody knew why.
- What was going on: The owner asked twice why a remote editor's app was not downloading YouTube clips on his own computer; no cause was recorded.
- What the product must do: When a computer that should download a clip does not, the dashboard states that computer's reason.
- Kind: 3
- State: outcome not found
- From: P12-055

### YTD-057: A download handed back to the server gave no reason, or a bare error code.
- What was going on: A computer handing a job back (wrong project, no space, missing tree and more) recorded why, but the page never said, and once painted "declined the job (HTTP 503)".
- What the product must do: Whenever a job moves to the server, the page says why in a plain sentence and that the server will finish it, never a bare HTTP code.
- Kind: 3
- From: H06-123, L04-120, L08-003

### YTD-058: A retried job stayed stuck on the server for good.
- What was going on: A retry inherited the finished run's "taken back by the server" state, so it never ran on the editor's computer again and kept hitting the address YouTube had blocked.
- What the product must do: Pressing download again on a finished job starts a fresh run that may go to the editor's computer, unless that computer had abandoned the job.
- Kind: 3
- From: L01-057, H01-063

### YTD-059: A server second chance on a blocked address failed the whole job.
- What was going on: While YouTube blocked the server, its second-chance download of clips an editor's computer missed failed the job outright, though the editor already had the other clips.
- What the product must do: When the server is blocked on a second chance, the remaining clips are marked failed with "retry from your own computer" and the job ends done.
- Kind: 3
- From: L10-089

### YTD-060: Computers took download jobs they could not finish.
- What was going on: A computer without the tool that merges video and audio accepted jobs and failed every clip, and computers claimed qualities they could not handle, leaving jobs idle three minutes.
- What the product must do: A computer takes a download job only if it can complete it (tools, quality, project); otherwise the job starts elsewhere at once.
- Kind: 3
- From: H01-060

### YTD-061: A job made for the server's wider project choice was taken by an editor's computer.
- What was going on: A server download may target any active project; a page could mark a job for the server, then let its own computer take it into a project it does not sync.
- What the product must do: A job created to run on the server can never be taken by an editor's computer.
- Kind: 3
- From: L06-065

### YTD-062: A failed tool install turned off downloading on that computer for a day.
- What was going on: After a failed install or update of the download tools the next try was 24 hours away, so one network blip at start sent that computer's downloads to the server.
- What the product must do: A failed install or update retries within minutes with backoff, and the editor can see why downloading on their computer is off.
- Kind: 3
- From: H06-101

## One job, one computer

### YTD-063: Any editor's computer may finish another editor's lapsed download.
- What was going on: A review limited lapsed jobs to their creator's computers; the owner: "I want the old behaviour back", because the editors share one archive.
- What the product must do: Once a job's hold has expired, any signed-in editor's running computer may take it over and finish it.
- Kind: 2
- From: P11-050, L09-054, M03-007, H05-101, H06-091

### YTD-064: Two computers, even one person's laptop and desktop, downloaded the same job.
- What was going on: A hold was checked by person, or only when claimed, so a laptop waking after its hold expired kept renewing and reporting beside the desktop that took over.
- What the product must do: Each job is held by exactly one computer, every call names the calling computer, holding is checked at every step, and a computer that lost a job is told to stop and stops.
- Kind: 3
- From: H01-065, H04-037, L07-023, H05-086, L06-015

### YTD-065: A three-second dashboard restart ended a 22-clip download at clip 2.
- What was going on: The editor's computer treated one refused connection during a brief restart as the end of the job, and the server then fetched clips the editor could not get.
- What the product must do: A job survives the server being unreachable for up to 60 s, while a clear error answer such as "job over" still stops it.
- Kind: 3
- From: L01-059, M02-101, C02-062

### YTD-066: A status report sent twice showed "23 of 22".
- What was going on: A clip's done or failed report was re-sent when its reply was lost after the server had processed it, and each copy bumped the job's counters.
- What the product must do: A repeated status report is counted once; totals never exceed the clip count or keep a phantom failure.
- Kind: 3
- From: H03-018

## Choosing the destination and checking space

### YTD-067: A wired editor could choose no project as a download destination.
- What was going on: Destinations were the person's ticked projects, and a wired computer never ticks one; the page knew the person, not which of their computers was asking.
- What the product must do: Destinations depend on the computer that will download: the server or a wired computer may target any active project, a remote computer only projects it syncs.
- Kind: 3
- From: C02-076, P07-017, P09-009, L01-089, C03-054

### YTD-068: The project picker offered projects the next step refused.
- What was going on: The picker used a wider rule than creating, downloading and retrying the job, and the page never sent which computer was asking.
- What the product must do: A job remembers where and on which computer it was accepted, and every later step accepts any project the picker offered.
- Kind: 3
- From: H04-069, L04-005

### YTD-069: An editor with two computers saw every project twice.
- What was going on: Plans are kept per computer, and the picker listed one entry per computer.
- What the product must do: A person's project list shows each project once, however many computers they own.
- Kind: 3
- From: H03-049

### YTD-070: The page keeps the project the person last picked.
- What was going on: The picker reset to the first project on every load, so 16 searches meant for one project were filed under another.
- What the product must do: The last chosen project is remembered per browser, restored if it still exists, and never changed except by the person.
- Kind: 2
- From: P05-013, L03-068, C01-103

### YTD-071: Downloads landed in a different project from the one selected.
- What was going on: An editor picked one project on the page, yet his clips kept landing in the first project in the list.
- What the product must do: A download lands in the project selected when download was pressed, and the job shows that project.
- Kind: 3
- State: outcome not found
- From: P06-057

### YTD-072: A project with an accented name was reported missing.
- What was going on: The name came from a Mac, which spells accents decomposed; the NAS spells them composed, so an exact check missed a folder that existed.
- What the product must do: Every check that a project folder exists matches names regardless of accent spelling, and never blames a missing share when the folder is there.
- Kind: 3
- From: L08-004

### YTD-073: Forty long clips can need 15 to 40 GB, and nothing checked.
- What was going on: 40 clips of 12 minutes at 1080p take 15-40 GB; pasted links carry no length, so 40 links into 6 GB passed a flat 2 GB guess.
- What the product must do: Show an estimate and free space, estimating about three minutes per link of unknown length, refuse below twice the estimate, and proceed when space cannot be read.
- Kind: 3
- From: L04-128, L10-019

### YTD-074: Pasted links skipped the space check, and the refusal named a hidden button.
- What was going on: Pasted-link jobs and server fallbacks got no free-space check, so a full NAS filled clip by clip, and the "no room" message named a retry button hidden in that state.
- What the product must do: Every way a download starts, on any computer, checks space before fetching and refuses once, in one sentence naming a button on screen, leaving clips retryable.
- Kind: 3
- From: L09-047, H06-031, L08-002

### YTD-075: Space was measured on the wrong disk, and freeing space changed nothing.
- What was going on: Downloads to an editor's disk were refused for lack of space on the NAS, and a refusal was kept a minute, so freeing 300 GB did nothing.
- What the product must do: Free space is measured on the disk that will be written, by the computer writing it, afresh each time download is pressed.
- Kind: 3
- From: H05-085, L06-064, L08-001

### YTD-076: A lost NAS share was reported as "the disk is full".
- What was going on: A dropped share leaves its empty folder on the server's own small disk, so space reads that disk and downloads "succeed" there, then vanish and block re-downloading.
- What the product must do: Before writing into a NAS folder the share is confirmed present; if not, the refusal says the share is missing, never that the disk is full.
- Kind: 3
- From: L09-046, L06-063

## Jobs on the page: queue, retry, cancel

### YTD-077: Leaving the page and coming back made twelve pasted links seem lost.
- What was going on: The downloads ran fine, but the reopened page showed nothing, so the owner thought his links were "eaten".
- What the product must do: Every load of the page shows the running job, the queue behind it and recently finished jobs, whatever the address says.
- Kind: 3
- From: L03-078, P09-012

### YTD-078: A reload showed last week's parked search instead of the running download.
- What was going on: After a reload the page attached to the oldest unfinished job, a week-old search awaiting review, and the downloading job appeared nowhere.
- What the product must do: The page shows the running job first, then the newest parked one, and lists every parked search with resume and cancel.
- Kind: 3
- From: L04-127

### YTD-079: A search nobody downloaded from blocked every later search.
- What was going on: A search left at review counted as the editor's active job, so new searches did nothing, and cancel claimed "stops after the video in flight" with nothing in flight.
- What the product must do: A search left at review never silently blocks a new one: it is shown, can be discarded in one obvious click, and every cancel message matches the job's real phase.
- Kind: 3
- From: C01-087, P05-008, P06-050, C02-058, L01-065, M03-011, P07-020

### YTD-080: A queued job showed "0 ahead" behind another editor's long job.
- What was going on: The server downloads one job at a time for the whole studio, but the position counted only the editor's own jobs.
- What the product must do: A queued job shows how many studio-wide jobs are ahead and whether the downloader is running, on creation and after a reload.
- Kind: 3
- From: L04-125

### YTD-081: The queue looked stuck while jobs waited for their creators' review.
- What was going on: All four open jobs were waiting at review steps only the person who created them can do, and nothing showed that.
- What the product must do: A job waiting for a person's review shows as waiting for that named person, never as stuck.
- Kind: 3
- State: still open
- From: P10-068

### YTD-082: A job that failed before its first clip offered no retry.
- What was going on: The failure message said to press retry, but the button appeared only once clip details had loaded, which never happens for such a job or after a reload.
- What the product must do: Any job with clips still owed shows retry, including after a reload and when it failed before the first clip.
- Kind: 3
- From: L10-018

### YTD-083: Cancel did nothing while a download ran on an editor's computer.
- What was going on: Cancel, and "download on the server instead", took effect only after the editor's computer finished, so every clip landed under a "cancelling" message.
- What the product must do: Cancel stops a download on an editor's computer after the clip in flight, and a hand-back button appears only when it will take effect.
- Kind: 3
- From: H01-062

## Progress

### YTD-084: The tray says "Downloading x/x (xx MB/s)" while it fetches.
- What was going on: Downloads on the editor's computer were invisible in the tray and felt slow; the owner asked for "Downloading: x/x (xx mb/s)".
- What the product must do: While downloading, the tray reads like "Downloading YouTube clip 3/12 (4.2 MB/s, 38%)", live, dropping what is unknown, and says "converting" during a re-encode.
- Kind: 2
- From: P07-022, C02-066, L03-047, M03-013

### YTD-085: A one-video download sat at 0%, and a job countdown ran backwards.
- What was going on: Progress counted only finished videos, a job-wide average jumped backwards because clips differ tenfold in length, and a forty-minute local download showed only "downloading".
- What the product must do: Page and tray show clip N of M plus the in-flight clip's thumbnail, percent, speed and time left; unknown is blank, never zero; a local download can be stopped there.
- Kind: 3
- From: P05-007, C01-088, L04-098, L04-119

## Reaching the editor and Resolve

### YTD-086: Downloaded originals go up from the computer that fetched them, never down to others.
- What was going on: Other editors' YouTube originals cost one editor 58 GB on his first sync.
- What the product must do: Downloaded originals upload from the downloading computer but never sync down to other computers; their small proxies still come down.
- Kind: 2
- From: C01-089

### YTD-087: A clip downloaded on the server never reached the editor who asked.
- What was going on: Originals only travel up to the NAS, so every server fallback left the clip where the requesting editor could not get it.
- What the product must do: Any clip in a person's download history that is missing from their computer can be fetched from the NAS in one click.
- Kind: 3
- From: L01-060, P06-055, M02-102

### YTD-088: An editor imported 540p previews because the originals never reached him.
- What was going on: Only the previews of downloaded clips reached a remote editor, so he imported those into the shared project; the owner called it "clearly incorrect behaviour".
- What the product must do: Resolve always receives a downloaded clip's full original, never its preview, on every computer.
- Kind: 3
- From: P05-016

### YTD-089: Downloaded clips land in Resolve in a bin named after their topic.
- What was going on: The owner wanted downloads imported automatically into the open project's YouTube bin, inside a bin named after the search topic.
- What the product must do: Once on an editor's computer, clips appear under the YouTube bin in a bin named after the topic, each clip once.
- Kind: 2
- From: P04-037

### YTD-090: Downloaded clips never reached Resolve, and nobody knew.
- What was going on: Clips landed in the project but the import stopped (no matching project, Resolve closed, drive absent), visible on neither side.
- What the product must do: Clips waiting for Resolve, and an import that gave up, show with the reason on the editor's computer and on the dashboard.
- Kind: 3
- From: L04-144

### YTD-091: "Show in folder" opened Documents for every clip.
- What was going on: Windows Explorer's select-a-file option works only in one exact quoting form; quoting the whole option opens a default folder instead.
- What the product must do: "Show in folder" opens the containing folder with the file selected, for any path, verified by the folder that actually opened.
- Kind: 1a
- From: C01-090

### YTD-092: A backslash path shown to a Mac editor is a wrong path.
- What was going on: On a Mac a backslash is legal inside a file name, and a page served from the NAS cannot know an editor's drive letter or system.
- What the product must do: Pages served from the NAS show a file's path relative to the project tree, with forward slashes and no drive letter, saying "under your sync drive".
- Kind: 1a
- Move to: whole-product
- From: L04-045

## Keeping the downloader working

### YTD-093: The downloader takes its newest daily build everywhere, without a product release.
- What was going on: YouTube changes break downloaders within days while stable releases lag weeks; the owner: "accept any ... build, daily etc, to get the latest", "without having to do a full new build".
- What the product must do: The server and every computer move to the newest verified daily build within a day, in the background without delaying startup, never downgrading, and report their version.
- Kind: 2
- From: L10-090, P12-021, L02-031, M03-005

### YTD-094: A downloader too old to work was noted only in a log.
- What was going on: YouTube changes often break downloaders within weeks; one 43 days old that could not update itself was logged once a day.
- What the product must do: A downloader that cannot update, or lags a known newer build, is shown to the editor and as an admin warning before downloads start failing.
- Kind: 3
- From: L04-083

### YTD-095: A wiped download helper still read "installed" and green.
- What was going on: Install was judged by a stamp kept apart from the files, so a wiped helper read healthy while downloads crawled near 1.8 MiB/s or landed empty.
- What the product must do: A component reads installed only when its files are confirmed on disk; missing files reinstall, and an unverified check reads "not checked", never OK.
- Kind: 3
- From: L06-058

### YTD-096: A version floor written "2026.8.5" refused every computer in the studio.
- What was going on: One side compared versions as text and the other as numbers, so the server refused everyone while each computer believed itself current.
- What the product must do: Versions are compared numerically by one rule everywhere, and a floor that does not parse is refused when it is set.
- Kind: 3
- Move to: releases-and-updates
- From: H01-061

## The assistant behind search

### YTD-097: Text from YouTube can carry instructions aimed at the assistant.
- What was going on: Titles and descriptions the relevance check reads are written by strangers and can carry instructions.
- What the product must do: Anything taken from the web reaches the assistant fenced as material to judge, never as instructions, whichever service is used.
- Kind: 3
- From: C02-036, L01-017

### YTD-098: The assistant was handed every server secret while reading YouTube text.
- What was going on: The assistant ran with the server's whole environment, including fleet, login and NAS credentials.
- What the product must do: The assistant receives only the inputs its task needs, never the server's secrets.
- Kind: 3
- From: H07-046

### YTD-099: Searches failed "no AI provider" while Settings said the assistant was signed in.
- What was going on: The assistant's sign-in had expired and could not refresh; Settings judged it by a file existing, and the job dropped the assistant's own reason.
- What the product must do: A sign-in that has expired and cannot refresh shows "Sign in again" everywhere, and a failed job carries the assistant's own reason, never "no provider".
- Kind: 3
- From: L10-074, P13-010

### YTD-100: The assistant read "missing" for days after one failed check at startup.
- What was going on: A NAS often starts before its internet is up; the assistant check ran once, failed, and nothing re-checked until someone searched anyway.
- What the product must do: A failing availability check for an outside service repeats on its own at least every five minutes until it passes.
- Kind: 3
- From: H03-050, L01-072

### YTD-101: A health light that could only move one way lied for weeks.
- What was going on: YouTube sign-in health could only worsen and the assistant's could only turn green, so a revoked key stayed green while every search failed.
- What the product must do: Every health status moves both ways from live results, and a week without use reads "unused", not failed.
- Kind: 3
- From: L04-054

### YTD-102: Checking assistants spent paid calls on a provider the admin had ruled out.
- What was going on: Every ten minutes of activity each enabled assistant was tested with a real paid call, up to 70 s, before the admin's chosen one was read.
- What the product must do: With an assistant chosen by the admin, only that one is checked; no paid call goes to a provider that will not be used.
- Kind: 3
- From: H03-051

## Rights and terms

### YTD-103: The downloader is off until each person and computer accepts a rights statement.
- What was going on: The downloader and its anti-blocking parts were installed and on everywhere, with no rights acceptance recorded.
- What the product must do: The downloader is off by default, each person and computer records a versioned rights acceptance first, anti-blocking is a separate opt-in, and unreadable settings mean off.
- Kind: 2
- From: L01-016

### YTD-104: A punctuation-only edit to the rights notice must not force re-agreement.
- What was going on: Changing the notice's version sends every editor in every studio back through the dialog.
- What the product must do: Editors are asked to agree again only when the words agreed to change, never for punctuation alone.
- Kind: 2
- From: L06-067

### YTD-105: A download refused for unaccepted terms says "Please first accept download terms".
- What was going on: A download started on the dashboard was silently refused when the editor's computer had not accepted the terms.
- What the product must do: The page tells the person to accept the download terms in the editor's app first, where the item reads "Accept YouTube Terms".
- Kind: 2
- From: P06-011

## Sealed

### YTD-S01: The downloader stamps finished files with YouTube's upload date.
- What was going on: By default it sets a file's modified time from the server's Last-Modified header, usually the upload date, so a file written seconds ago looks years old.
- What the product must do: Downloaded files keep their real write time, so any rule that waits for a file to settle treats a just-written file as new.
- Kind: 1b
- Tool: yt-dlp (default mtime; --no-mtime / updatetime False)
- From: L02-011

### YTD-S02: With no paths set, the downloader writes scratch files in the working folder.
- What was going on: Given no paths, it writes format-test files in the current folder, which on the server was the read-only root, so downloads died "permission denied".
- What the product must do: The downloader always runs with a writable scratch location the product owns, and a failed clip records the full error.
- Kind: 1b
- Tool: yt-dlp (paths home/temp defaults)
- From: C02-061, L01-061, P06-051

### YTD-S03: Single-stream pieces look exactly like finished videos.
- What was going on: Fetching video and audio apart, it names a piece "Title [id].f137.mp4", stops changing it before merging, and keeps it if anything fails.
- What the product must do: Files with ".f" plus digits before the extension are never imported into Resolve, synced or left behind; only the merged file counts.
- Kind: 1b
- Tool: yt-dlp
- From: H01-058

### YTD-S04: The downloader rewrites the cookie file it is given on every run.
- What was going on: An emptied cookie file fills with anonymous visitor cookies that hold no login, and an operator's original export gets overwritten.
- What the product must do: A cookie file counts as a sign-in only if it holds a real login cookie, and the operator's original export is kept separately.
- Kind: 1b
- Tool: yt-dlp (cookies.txt jar handling)
- From: L03-042, C02-081

### YTD-S05: Signed-in downloads found no formats at all.
- What was going on: With a cookie file the downloader also needs a proof-of-origin token and a JavaScript runtime; anonymous downloads reached 1080p without them, signed-in ones found nothing.
- What the product must do: Signed-in downloads run only where every piece YouTube demands is present, and a missing piece is reported rather than looking like an empty video.
- Kind: 1b
- Tool: yt-dlp (cookies, PO token provider, deno JS runtime)
- From: C01-084, P05-009, L03-055

### YTD-S06: Without its script runtime the downloader hangs or every format vanishes.
- What was going on: Lacking its runtime it falls back to a slow built-in interpreter (97 s, no output, against 6.4 s) or fails "format not available", which reads as YouTube flakiness.
- What the product must do: The runtime is checked however the app was started, a missing one shows as a banner, and failures it causes name it instead of advising an update.
- Kind: 1b
- Tool: yt-dlp (needs deno or node on PATH; lost it when started from a Windows scheduled task's stripped environment)
- From: L04-129, P06-058

### YTD-S07: A pinned YouTube player client stops working within weeks.
- What was going on: The default client needed a token editors lacked; another worked at full quality, then failed as enforcement tightened; naming several let it pick a token-bound 403 format.
- What the product must do: The downloader uses its own default client, and which client it imitates can be changed without a product release.
- Kind: 1b
- Tool: yt-dlp player_client (android_vr, ios, tv, web, web_safari) and GVS PO tokens
- From: C02-064, L01-062, P06-052, M03-020, L03-041

### YTD-S08: Only the downloader's newest nightly keeps up with YouTube.
- What was going on: Mid-stream 403s at 40-70% were fixed only by a pre-release; plain self-update never leaves stable, and installing a nightly from the package index took 146 s.
- What the product must do: Update explicitly to the nightly channel in the background, keep the last working copy to fall back on, and show when a newer build awaits a restart.
- Kind: 1b
- Tool: yt-dlp (nightly channel, self-update, package index)
- From: P14-004, C04-027, M06-004, H07-132, L10-091

### YTD-S09: Judging the downloader stale by age alone raised false alarms.
- What was going on: Its makers can go five weeks or more without a stable release, so a 21-day age rule called three computers out of date on the newest release.
- What the product must do: "Out of date" is shown only when a newer version is known to exist, never by age alone.
- Kind: 1b
- Tool: yt-dlp
- From: L10-038, P12-020

### YTD-S10: Segmented downloads need parallel fetching and a working token helper.
- What was going on: Without the token helper add-on only throttled segmented formats remain, and fetched one segment at a time they crawl; its failed install was only in a log.
- What the product must do: Fetch about six segments in parallel, retry a failed helper install, and record and show its install result, unknown reading "not checked".
- Kind: 1b
- Tool: yt-dlp HLS (concurrent_fragment_downloads) and the bgutil PO-token provider plugin
- From: L01-063, C02-065, L04-085

### YTD-S11: A dead assistant sign-in leaves its credential file with zero expiry.
- What was going on: When its session cannot refresh, the command-line assistant rewrites its credential file with expiry 0 and no refresh token, and the file still exists.
- What the product must do: "No refresh token and already expired" counts as signed out, reading only those two facts and never any secret value.
- Kind: 1b
- Tool: Claude Code CLI
- From: L10-075

## Removed

