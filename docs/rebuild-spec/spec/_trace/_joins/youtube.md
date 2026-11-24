# Joins aimed at youtube

## Checked

- J1 | fine
- J2 | F7, F8
- J3 | fine
- J4 | F1, F2, F3
- J5 | F4
- J6 | F5, F6
- J7 | F1

## Findings

### F1: the site switch for getting past YouTube's blocking is a different thing, under a different name and heading, in youtube
- Kind: differs
- From: dashboard-2 / Every setting of the site (also whole-product / An admin switches each part on and off for the whole site)
- Here: Signing in to YouTube / A site decides whether signed-in YouTube sessions may be used on editors' computers (nothing under "How YouTube throttles and refuses")
- From says: "Setting: YouTube's extra measures against being blocked. Does: lets downloads take extra steps to get past YouTube refusing them" and whole-product: "getting round YouTube's blocking (see YouTube downloads: How YouTube throttles and refuses)"
- Here says: "Getting past YouTube's own blocks with a signed-in YouTube session on editors' computers is a site switch of its own" with "Setting: Signed-in YouTube downloads on editors' computers", while "Every computer that downloads, and the server, meet this demand" (proof of a real player) unswitched, and the health line shows "whether what gets the server past YouTube's blocks is working, unreachable, failed to set up, or off" with no switch for it
- Settled by: decisions page-07 7.4 answered A (keep the second switch, "because those measures touch YouTube's terms, which is a choice the studio should make knowingly"), with YTD-103 (ruling: "anti-blocking is a separate opt-in"); the owner must say: does the one anti-blocking switch cover only signed-in downloads on editors' computers, or every extra step the server and the computers take to get past YouTube's blocks?
- Fix: youtube names one setting with one name and states exactly which measures it gates (including the server's, which its health line can show "off"), and dashboard-2 and whole-product use that name and point to the heading where youtube describes it.

### F2: dashboard-2's list of every site setting leaves out youtube's other site settings
- Kind: contradiction
- From: dashboard-2 / Every setting of the site
- Here: Signing in to YouTube / An admin can give the server a signed-in YouTube session; Keeping the downloader working / An optional periodic test checks that YouTube still serves a known video
- From says: "Each setting below is one thing an admin can change for the whole site."
- Here says: "Setting: The server's YouTube session. ... Applies to: the site." and "Setting: Periodic YouTube test. ... Applies to: the site."
- Settled by: OWNER_REQUIREMENTS section 5: "The specification lists every setting by what it does, with no arrangement."
- Fix: dashboard-2 either lists these two site settings (and the switch of F1 under its settled name) or says that a part's own site settings are listed in that part's piece.

### F3: the YouTube downloads switch is written out in both pieces, with different search words
- Kind: said twice
- From: dashboard-2 / Every setting of the site
- Here: Keeping the downloader working / A site switches YouTube downloads on and off while the server runs
- From says: "Setting: YouTube downloads. ... Search words: YouTube, downloads, videos, part, switch."
- Here says: "Setting: YouTube downloads. ... Search words: youtube, downloads, part, switch, enable."
- Settled by: OWNER_REQUIREMENTS section 1: "One way to do each thing: ... one place a setting comes from"
- Fix: one piece (youtube) holds the setting line and dashboard-2 points to it, or both carry the same search words.

### F4: the server update's refusal counts "running" YouTube downloads, but youtube says a restart interrupts different jobs from those
- Kind: contradiction
- From: releases-and-updates / An admin updates the server with one button
- Here: Jobs on the page: queue, retry, cancel / A server restart never loses a job; One job, one computer / When the computer doing a download goes away
- From says: "N YouTube download(s) are running: an update restarts the server for about ten seconds and interrupts them. ... Downloads waiting for review do not count."
- Here says: "a job caught while writing terms, searching, looking up details or filtering is put back in the queue and run again from the start (its terms and results are thrown away). A job caught downloading carries on" and "A network outage, or the server being unreachable, for up to about a minute does not lose the job"
- Settled by: the owner must say: should the one-button server update warn about YouTube searches in progress (which a restart throws back to the start) and leave out jobs downloading on an editor's own computer (which a ten-second restart does not touch)?
- Fix: releases-and-updates says which job states it counts and what the restart does to each, in youtube's terms; youtube's restart section stays as it is.

### F5: the repair of an undecodable YouTube original is a proxy swap done on its own here, an "edit-ready copy" offered before a render there
- Kind: differs
- From: resolve-on-the-editors-computer / The editor is warned when the open timeline uses VP9 originals
- Here: Files Resolve can decode / Clips already in the studio that Resolve cannot decode are found and fixed; Every clip lands as a single MP4 file
- From says: "each VP9 original is swapped for an edit-ready copy with the same frame count, which takes seconds per clip when such a copy exists (as it does for a YouTube download made ready to edit)"
- Here says: "a proxy of it exists with exactly the same number of frames, the original is set aside and the proxy takes its place" (On its own) and "the converted clip takes the clip's name and the download is removed"
- Settled by: YTD-042 (ruling: "An undecodable original is replaced by its proxy only when the frame counts match") and RSV-116 (ruling: "A pre-render repair swaps in an edit-ready copy with the same frame count"), both from the owner's "just copy the proxy out into the main folder"
- Fix: resolve-on-the-editors-computer calls the copy the clip's proxy with matching frames and drops "as it does for a YouTube download made ready to edit" (a converted download keeps no second copy), and youtube says its proxy swap is the same repair as that window's offer, or points to it.

### F6: youtube says Resolve stops renders on VP9 and AV1 clips; resolve warns only about VP9 and says AV1 renders fine
- Kind: contradiction
- From: resolve-on-the-editors-computer / The editor is warned when the open timeline uses VP9 originals
- Here: Files Resolve can decode / Before Resolve renders, the editor is told which clips would stop the render
- From says: "If any is VP9, a window titled "CC Sync: VP9 media in this timeline" says"
- Here says: "Fact about Resolve 21: it stops a render on some VP9 and AV1 clips from YouTube. ... See Timeline Cards: the hand-over to Resolve, and exports: Renders from Resolve."
- Settled by: the owner must say: before a render, should the editor be told about AV1 clips as well as VP9 ones? (lessons disagree, neither a ruling: YTD-039 says some AV1 clips stop a render, RSV-115 says "AV1 and HEVC render fine")
- Fix: youtube and resolve-on-the-editors-computer name the same codecs, and youtube's pointer also names Resolve on the editor's computer: The editor is warned when the open timeline uses VP9 originals.

### F7: youtube's GET IT FROM THE NAS does not say what happens when the computer is already fetching as many clips as it will
- Kind: missing
- From: broll / A clip not on this computer yet is fetched first, with progress, and then placed
- Here: Reaching the editor and Resolve / An editor can open a downloaded clip's folder, or fetch it from the NAS
- From says: "A computer downloads at most two clips at once for an editor who is waiting. A third reads "not sent yet: ..." ... never as an error and never as success" and "the same one-file fetch serves ... a downloaded YouTube original brought to the editor's computer"
- Here says: "Otherwise: "the download finished but the file is not there - try again", the reason it failed (for example the drive is not connected), or "the download failed"."
- Settled by: OWNER_REQUIREMENTS section 1: "One way to do each thing"
- Fix: youtube says that GET IT FROM THE NAS shares the two-at-once limit and shows a waiting state (not a failure) when the computer is busy, pointing to broll's fetch for the rule.

### F8: youtube still tells the requesting editor to fetch server-downloaded clips by hand, against its own rule that they arrive by themselves
- Kind: contradiction
- From: broll / A clip not on this computer yet is fetched first, with progress, and then placed ("a downloaded YouTube original brought to the editor's computer")
- Here: Where a download runs, and saying so / The page always says where each job ran and why (and The owner of a computer can keep it out of YouTube downloads; An editor can open a downloaded clip's folder) against Reaching the editor and Resolve / Downloaded clips reach the computer of the editor who asked
- From says: "the same one-file fetch serves ... a downloaded YouTube original brought to the editor's computer"
- Here says: "the server downloads them, and YouTube originals only sync upwards, so the editor fetches one from the download history when they want it on their computer" against "The clips of a job reach the computer of the editor who asked for them on their own, wherever they were downloaded, when that computer syncs the project. Any other editor fetches a clip in one click from the history."
- Settled by: decisions page-18 18.4 answered B: "the clips of a job reach the computer of the editor who asked by themselves, when that computer syncs the project; others fetch by hand"
- Fix: youtube rewrites the server-hand-over sentence, the "on this computer" switch message and the GET IT FROM THE NAS explanation to say the requester's clips arrive by themselves when their computer syncs the project and only other editors fetch by hand (sync-1's "never comes down to anyone else's" needs the same exception).
