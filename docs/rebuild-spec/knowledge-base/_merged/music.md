# Music: finding a track and sending it to Resolve

## What the owner wants

### MUS-001: Music is dropped in, indexed on its own, and sent to Resolve three ways.
- What was going on: The owner asked for drag-and-drop music ingest with automatic analysis, .ogg files converted to mp3, and three ways to send a track to Resolve.
- What the product must do: A dropped music file is indexed with no further step, .ogg becomes mp3, and a track can be imported to a bin, inserted, or placed on the track below.
- Kind: 2
- From: P04-071

### MUS-002: A track added from an editor's computer lacked tempo, key and loudness.
- What was going on: The owner asked that tracks analysed on an editor's computer match the library's original quality; those tracks had no tempo, key or loudness, and a differently computed tempo is worse than blank.
- What the product must do: Every library track gets the same analysis, including tempo, key and loudness measured the same way, wherever it was added.
- Kind: 2
- State: still open
- From: P06-022, L01-012

### MUS-003: "Similar tracks" returned only tracks from the same stock library.
- What was going on: The owner wants a track's file name ignored for tags, genre and mood; similar-track results came back from one stock library only.
- What the product must do: Search and "similar" rank by sound, tags, genre and mood; a file name never affects results, and similar results are not dominated by one source library.
- Kind: 2
- State: outcome not found
- From: P04-072

## Which files are music

### MUS-004: Raw .aac tracks showed wrong durations, one off by 7 minutes.
- What was going on: Raw .aac files store no duration, so quick readings estimate from bitrate and size; 85 of 89 were wrong, defeating duplicate checks by duration.
- What the product must do: Durations of raw .aac files come from decoding the audio, never from an estimate.
- Kind: 1a
- From: M05-078

### MUS-005: Interview and field recordings swamped the music scan.
- What was going on: Of 2,384 audio files on the NAS, 397 were music; the rest were recorder and multitrack takes, wireless-mic files, voiceover, stings under 30 s and files over 15 minutes.
- What the product must do: Music ingest excludes recorder takes, voiceover, stings under 30 s and recordings over 15 minutes, and keeps stems apart from tagging.
- Kind: 3
- From: M05-074

### MUS-006: Tracks named only by a library number were merged as duplicates.
- What was going on: Stock-music downloads are often named by a numeric id alone, so stripping numbers to compare names collapsed them; one track also comes as both preview and master.
- What the product must do: Numeric-id names stay distinct when deduplicating, and of true duplicates the best format (wav, flac, aac, mp3, ogg) with the readable name is kept.
- Kind: 3
- From: M05-075

### MUS-007: Music tracks over two hours got a false length and heavy memory use.
- What was going on: Decoding held about three times the track's raw audio in memory, and anything over two hours was recorded as exactly 7,200 seconds.
- What the product must do: Music of any length is indexed with its true duration and bounded memory use.
- Kind: 3
- From: H06-111

## Adding tracks to the library

### MUS-008: A music drop on a laptop with 15 GB free was refused.
- What was going on: The 20 GB free-space minimum meant for b-roll was applied to music, whose largest file is about half a gigabyte.
- What the product must do: Each kind of drop has its own free-space minimum fitting its files (b-roll 20 GB, music 2 GB).
- Kind: 3
- From: L04-154

### MUS-009: Music dropped while the NAS share was unmounted was answered "queued" and lost.
- What was going on: An unmounted share is an empty folder on the server's own disk; uploads landed there, hidden once the share mounted back, including for seconds after a NAS reboot.
- What the product must do: Every write into the library confirms at that moment that the share is mounted and is the library; otherwise the upload is refused with the reason.
- Kind: 3
- From: L04-003, H04-078, L07-064

### MUS-010: A mounted, full music library was reported missing and closed all ingest.
- What was going on: Presence was judged by whether sampled indexed files existed; old tidied files, and new records whose audio had not yet arrived, made a mounted library look absent.
- What the product must do: The library is judged present by the share itself, so removed files or an import in progress never make a mounted library refuse new music.
- Kind: 3
- From: L07-065, H05-080, L06-071

### MUS-011: A new upload took over an existing or promised track's name.
- What was going on: Names were checked against disk only, ignoring tracks already listed and names promised to uploads still in flight, so later items overwrote earlier ones.
- What the product must do: A library name is never given to two items, counting every import not yet landed, and the name shown before importing equals the name given.
- Kind: 3
- From: H04-079, H07-106, H06-047, L09-051

### MUS-012: A track that failed local analysis stayed only on the editor's computer.
- What was going on: Library names are issued after analysis, so a track that could not be analysed locally had no name and uploading under its own could overwrite another editor's file.
- What the product must do: A track that cannot be analysed locally is still uploaded and queued under a library-issued name; nothing reaches the library under a name the library did not issue.
- Kind: 3
- State: still open
- From: L01-013

### MUS-013: Choosing a free file name spun forever when the library could not be checked.
- What was going on: Every "is this name taken" check answered taken on any error, so a share the server could list but not enter made every candidate taken.
- What the product must do: "Could not tell" is a retryable error, picking a name gives up after a fixed number of candidates, and the page says the library cannot be checked.
- Kind: 3
- From: L06-069, H05-008

### MUS-014: A music drop with no capable computer falls back, and says so.
- What was going on: When the editor's app is absent or too old, the drop falls back to uploading for later analysis on the studio's own machine.
- What the product must do: A music drop always lands somewhere, and the page tells the editor in words which path it took.
- Kind: 3
- From: C02-040

### MUS-015: Nothing searchable may be missing its audio.
- What was going on: Tracks were listed before their audio uploaded, so a cancelled batch left them searchable but silent.
- What the product must do: A track appears in search only once its audio is in the library, and a cancelled batch removes or finishes every track it started.
- Kind: 3
- From: H06-046

### MUS-016: A failed track stayed "pending" for ever and blocked its corrected re-drop.
- What was going on: Analysis failures never reached the live library, so the track looked pending and a good re-drop was refused as a duplicate.
- What the product must do: A track that fails analysis shows as failed in the library with its reason, stops being retried, and does not block a corrected re-drop.
- Kind: 3
- From: H03-044

### MUS-017: The library did not show new tracks until a reload.
- What was going on: When an ingest finished, the list, counts and header stayed unchanged, and a blank waveform on a new track looked broken.
- What the product must do: When an ingest finishes the library refreshes once, newest first, and a track with no waveform yet says why and that seeking still works.
- Kind: 3
- From: L04-134

## Imports across computers

### MUS-018: A thirty-second NAS blip failed every track of an album drop for good.
- What was going on: The library's "try again later" answers (share not mounted, two tracks racing for one name) were treated as final, retried back to back, with no retry button.
- What the product must do: A retry-later answer is retried with pauses for about twenty minutes before failing with the library's words, and a failed track can be retried from the page.
- Kind: 3
- From: L06-022, H05-081

### MUS-019: A track that recovered once was failed for good by the next brief outage.
- What was going on: The count of failed sends was never reset after one succeeded, so a track that recovered on try 5 had one try left for its next blip.
- What the product must do: Every retry budget resets after a success, so a later outage gets the full number of tries.
- Kind: 3
- From: L07-015

### MUS-020: A track that was saved got an error reply and was failed for good.
- What was going on: A busy library made a follow-up bookkeeping read fail, turning a successful save into an error the sending computer treats as final.
- What the product must do: A track whose save succeeded is answered as a success even when a follow-up bookkeeping read fails.
- Kind: 3
- From: L07-066

### MUS-021: A computer waiting out a retry reported idle and threw away its loaded analyser.
- What was going on: During a NAS blip, tracks waiting to retry made the computer report idle for up to five minutes while holding the batch, and the 4-12 GB analyser was rebuilt.
- What the product must do: A computer holding an import with tracks waiting to retry shows as working, keeps its analyser loaded, and never tells the editor it is idle.
- Kind: 3
- From: L07-014

### MUS-022: Another computer's retry or late cancel took an import from the computer running it.
- What was going on: Retry reset a batch still held by a working computer, letting a second one index the same tracks, and a stale computer's cancel deleted a track mid-upload.
- What the product must do: Only the computer holding an import can cancel or release it, retry is refused while another holds it, naming it, and an abandoned import stays retryable.
- Kind: 3
- From: L10-050, L07-062

### MUS-023: Cancelling a batch nobody was working on hung on "cancelling" for ever.
- What was going on: The cancel waited for a confirmation from a computer that never held the batch, or whose hold had lapsed, leaving it shown as live with no button to end it.
- What the product must do: Cancelling work no computer holds, or whose holder has lapsed, ends it at once; no state exists that neither cleanup nor any button can leave.
- Kind: 3
- From: C02-042, L09-040

### MUS-024: A finished batch read "11 of 12 tracks" for ever.
- What was going on: Tracks ending as "queued for later analysis" or waiting for another computer counted as neither done nor failed, and clean-up deleted files they still needed.
- What the product must do: Every ending state counts towards the total, waiting tracks are named, and no clean-up removes a file a waiting track still needs.
- Kind: 3
- From: L01-014, L04-121

### MUS-025: After a page reload, staged or retried music could not be sent by any button.
- What was going on: Only the page remembered the batch, so after a reload send, cancel, retry and take-over were refused, and the fallback advice started a different import.
- What the product must do: After a page reload, staged work can still be sent, cancelled, retried or taken over from the page, and no fallback advice starts a different import.
- Kind: 3
- From: L09-042, L07-063

### MUS-026: Every refusal from the editor's own app read "another of your computers is working".
- What was going on: The page ignored the reason the editor's app gave, including "reload the page and try again", and once said "queued" after a silent refusal.
- What the product must do: When the editor's app refuses, the page shows that app's own reason and action, and never reports success for work nothing picked up.
- Kind: 3
- From: L09-041

### MUS-027: An open music tab kept starting work on the editor's computer.
- What was going on: An open music tab made the editor's app start a fresh worker every 30 seconds, Resolve running or not, about 14 GB of temporary writes an hour.
- What the product must do: A browser tab left open for an hour causes no repeated process starts and no growing disk writes on the editor's computer.
- Kind: 3
- State: outcome not found
- From: H08-040

### MUS-028: An analyser already downloaded was treated as missing until a restart.
- What was going on: Pressing Run did nothing because an analyser already on disk was read as absent for the whole session.
- What the product must do: An analyser already on disk is found without restarting anything.
- Kind: 3
- From: P06-023

### MUS-029: The music analyser refused to download from the studio's own update server.
- What was going on: Allowed download hosts were fixed to one public host, so a site publishing updates elsewhere had music analysis refused, with a sentence blaming correct settings.
- What the product must do: The product's own components download from wherever the site's update feed lives, over https (plain http only on the same computer), checked against a pinned fingerprint.
- Kind: 3
- From: L08-071

### MUS-030: An analyser that failed its check still loaded, replacing the good one.
- What was going on: The new analyser was written into place before it was checked, and anything complete-looking was loaded without asking whether it had passed.
- What the product must do: An analyser or index that fails verification never replaces the working one, and none is loaded without a recorded passed check.
- Kind: 3
- From: H02-019

## Keeping the library's data whole

### MUS-031: Publishing a fresh music index wiped tracks the live library had queued.
- What was going on: Tracks added on the live library were overwritten when a copy worked on elsewhere was copied or published back over it.
- What the product must do: Results worked on elsewhere merge in track by track, only where the file is unchanged, and never discard tracks the live library gained meanwhile; otherwise the publish refuses.
- Kind: 3
- From: L01-031, H01-023

### MUS-032: Merging an older analysis bundle rolled the whole library's scores back.
- What was going on: Applying results computed earlier elsewhere replaced every track's scores wholesale, undoing newer re-scoring on the live library.
- What the product must do: Merging results never overwrites library-wide data newer than the results; stale parts are skipped with a reason, and a failing track is rolled back alone.
- Kind: 3
- From: L04-004, H04-080

### MUS-033: A newly published library was not what search answered from.
- What was going on: Search kept answering from the previous library after a publish or new tracks, until someone restarted the dashboard.
- What the product must do: After a library is published or tracks are added, browse and search answer from the new data within a minute, without a restart.
- Kind: 3
- From: H03-045

### MUS-034: A 200-track album drop re-scored the whole library 200 times.
- What was going on: Each added track re-scored all tracks and rebuilt the search, about 1.7 million writes for one album.
- What the product must do: Library-wide recomputes after ingest are batched, at most once a minute and once at the end of a drop.
- Kind: 3
- From: L04-069

### MUS-035: A track added while the library was being re-scored stayed untagged.
- What was going on: A library-wide re-score cleared the "needs re-scoring" mark at its end, wiping the mark a track added during the pass had set.
- What the product must do: A track added at any moment ends up with tags and moods and is found by every filter.
- Kind: 3
- From: H05-082, L06-070

### MUS-036: A failed re-tagging wiped every tag in the library.
- What was going on: Re-scoring deleted all tags first and wrote new ones at the end; a failure in between left the deletion pending, and the next unrelated save committed it.
- What the product must do: A failed recompute leaves the previous tags exactly as they were, and the library says when its tags are behind.
- Kind: 3
- From: L04-068, H07-037

### MUS-037: A renamed track stayed in search and failed only at send to Resolve.
- What was going on: Renaming a library file added a new entry but never removed the old; about a third of the library has numeric names, so renaming is routine.
- What the product must do: A track whose file was renamed or deleted on the NAS leaves search at the next indexing, so every result can be sent to Resolve.
- Kind: 3
- From: H02-021

### MUS-038: A track's preview played a deleted track's audio.
- What was going on: Previews were chosen by a track number that a new track could inherit from a deleted one, while waveform, tags and Resolve got the new file.
- What the product must do: A track's preview always plays that track's own audio; a preview made for different audio is never served.
- Kind: 3
- From: H03-046

### MUS-039: A library written by a newer version broke every request.
- What was going on: Publishing a music index from a newer build made every request fail while the menu still offered the page as working.
- What the product must do: Data written by a newer version is detected at start, the section is marked degraded with that reason, and its link is not offered as working.
- Kind: 3
- From: L04-084

### MUS-040: A library was marked upgraded although its upgrade never ran.
- What was going on: Re-stamping the version on every open moved a live 376-track index past an upgrade that then never ran; a missing part showed the feature as absent.
- What the product must do: An upgrade counts as done only when the data has the new shape, and a broken feature shows as degraded, never as absent.
- Kind: 3
- From: M05-079

## Searching and filtering

### MUS-041: Filters stayed lit but were ignored, or threw away the typed search.
- What was going on: Mood, axis and tempo filters were dropped from description searches while shown on, and changing a filter reloaded the whole library while the box kept the query.
- What the product must do: Every filter shown as on applies to browsing and description search alike, and changing a filter narrows the current search instead of discarding it.
- Kind: 3
- From: L04-131, H06-097

### MUS-042: A tempo filter silently hid every track whose tempo was unknown.
- What was going on: Tracks with no measured tempo or length were excluded by any tempo or length filter without saying so.
- What the product must do: A filter never silently hides tracks whose value is unknown; it says how many are hidden and offers to include them.
- Kind: 3
- From: L04-132

### MUS-043: A broken search looked like "nothing matches".
- What was going on: Failed searches (analyser not loaded, session expired, busy library) showed the empty result with advice to loosen the description.
- What the product must do: A failed search says so with the reason and Try again, an expired session says to reload and sign in, and "nothing matches" appears only for a real empty answer.
- Kind: 3
- From: L04-130

### MUS-044: An empty "similar tracks" result advised rewording a description nobody typed.
- What was going on: One empty-state sentence served every kind of music search, and a filter matching nothing said the library was empty.
- What the product must do: Each kind of search or lookup has its own empty-result sentence, and an empty filtered result says which filter removed everything.
- Kind: 3
- From: L04-046

### MUS-045: One failed panel blanked the whole music page.
- What was going on: If one statistics or filter request failed at load, the whole page showed a raw status line instead of the library.
- What the product must do: One failed part of a page shows its own error while the rest of the page works.
- Kind: 3
- From: H06-118

## Listening in the browser

### MUS-046: Audio players probing with a header-only request before seeking were refused.
- What was going on: Browser players first ask only for headers (HEAD) to learn the length and range support, and the audio address answered "method not allowed".
- What the product must do: Every audio and video address answers HEAD with the same headers as GET, including range answers, and sends no body.
- Kind: 1a
- From: L06-072, H05-083

### MUS-047: Audio players asking for a file's last bytes were sent its first bytes.
- What was going on: Players ask for "the last N bytes" to read tags and duration at a file's end; sending the start gives wrong durations or no seeking.
- What the product must do: Media serving answers "last N bytes" requests correctly, and answers an unreadable or reversed range with the whole file.
- Kind: 1a
- From: H01-021

### MUS-048: Preview audio kept playing with no way to stop it.
- What was going on: A new search cleared the list while a preview played, leaving no controls, and pause and seek did nothing until the waveform finished loading.
- What the product must do: Playing audio always has a visible stop, and play, pause and seek work from the moment the player opens.
- Kind: 3
- From: H01-035

### MUS-049: A half-synced track's waveform request failed with a raw server error.
- What was going on: A truncated or undecodable file made the waveform fail with a raw error, on a request made for every track clicked.
- What the product must do: A track that cannot be decoded answers with a named "could not be read" reason, the log names the track and file, and the page keeps working.
- Kind: 3
- From: L06-073, H05-084

## Sending to Resolve

### MUS-050: Sending a track to Resolve failed when the track was not on the computer.
- What was going on: The music library is not synced to editors, so sending a track gave "file not found" instead of fetching it.
- What the product must do: Sending a track not yet on the computer fetches it first, showing progress, then places it in Resolve.
- Kind: 3
- From: L03-056

### MUS-051: The reveal button silently did nothing on every editor's computer.
- What was going on: The button opened a file window on the NAS serving the page, not on the editor's computer, and the failure was thrown away.
- What the product must do: Every action on an editor's files or Resolve runs on that editor's own computer, and a button that fails tells the person why.
- Kind: 3
- From: H02-022

### MUS-052: Inserting music at the playhead cut into a clip spanning that point.
- What was going on: The insert shifted or removed timeline content before finding that a clip straddled the insert point, so the cue overlapped, lost its tail, or cut the clip.
- What the product must do: Inserting music refuses, before changing anything, when a clip straddles the insert point.
- Kind: 3
- From: H07-071, H06-042
- Check: should inserting a cue in the middle of an existing music bed succeed by making room, or always be refused as the later finding says?

## Keeping files safe

### MUS-053: A file uploaded from a Windows browser can carry backslash path tricks.
- What was going on: A Windows browser can send an upload name like "..\..\evil.wav"; a server that splits names only on "/" keeps the traversal shape.
- What the product must do: Every uploaded file name is cut to its last part on both "/" and "\" before use, so no upload can name a path outside its folder.
- Kind: 1a
- From: C02-001

### MUS-054: A file name containing "&" could run a command when "reveal in folder" was clicked.
- What was going on: The Windows command shell treats "&" as a command separator, and passing a path through it let a name run a command.
- What the product must do: File names are never interpreted by a shell; a name like "rock&roll.mp3" opens the right folder and runs nothing.
- Kind: 3
- From: H01-022

### MUS-055: A file request from a web page could follow a link outside the library.
- What was going on: On a Mac whose music share was found by scanning mounted volumes, the containment check was skipped, so a symbolic link out of the volume was followed.
- What the product must do: A file request from any web page resolves links and refuses anything outside the shared library, however the library was found.
- Kind: 3
- From: H01-038

## Sealed

### MUS-S01: Music tags computed on an editor's computer differed from the studio server's.
- What was going on: One variant of the analyser randomises its audio front end, so a slightly different spectrogram yields a plausible fingerprint of the wrong audio; the plain variant ran 93 ms per 10 s on CPU.
- What the product must do: A track analysed on any editor's computer gets the same fingerprint, tags and search results as if analysed on the studio server.
- Kind: 1b
- Tool: CLAP (laion/larger_clap_music_and_speech) audio tower exported to ONNX
- From: C02-033

### MUS-S02: Raw similarity scores from the audio analyser meant nothing in absolute terms.
- What was going on: Scores sit in a narrow band with correct ordering; the best 10-second window beat the track average (40% vs 20%); the analyser hears quietness poorly.
- What the product must do: Music filters use rank within the library, and quiet beds are found by an energy control rather than the word "quiet".
- Kind: 1b
- Tool: CLAP audio embeddings
- From: M05-077

### MUS-S03: Similar tracks came from one stock library, and removing that bias hurt text search.
- What was going on: The analyser hears codec, and one library was mostly lossless; applying the bias correction to typed queries halved top-10 accuracy, 40% to 20%.
- What the product must do: Similar-track results are not dominated by one source or codec, and the source-bias correction never applies to typed text queries.
- Kind: 1b
- Tool: CLAP audio-text embeddings with a source-bias projection
- From: M05-076, H01-037

### MUS-S04: After the library file was replaced, the running server kept serving the old one.
- What was going on: An open connection stays on the file it opened; replacing the file by rename leaves it reading the deleted old copy until reopened.
- What the product must do: After the search data is replaced on the NAS, the next search reads the new data without a server restart.
- Kind: 1b
- Tool: SQLite (a connection is bound to the file it opened, not to the path)
- From: H02-009

### MUS-S05: A rollback reported "restored" but silently lost recent changes.
- What was going on: Recent commits live in two side files beside the main file; moving the main file back without them discards every change since the last checkpoint.
- What the product must do: Any move, backup or rollback of the library carries its side files with it, and a rollback reported as "restored" loses no committed change.
- Kind: 1b
- Tool: SQLite in WAL mode (the -wal and -shm sidecar files)
- From: H02-008

### MUS-S06: A deleted highest record's number is handed to the next new record.
- What was going on: Without the auto-increment option, a new record gets one more than the current highest number, reusing a deleted top record's number.
- What the product must do: Nothing stored outside the library's records, such as a preview file, is keyed by a record number that can be reused.
- Kind: 1b
- Tool: SQLite (INTEGER PRIMARY KEY without AUTOINCREMENT reuses the top rowid)
- From: H03-047

## Removed
