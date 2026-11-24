# Music: what real use taught

46 lessons. Each is one rule the product can be tested against: what a person saw (the heading), why it happened, and what the product must do. Kinds: *given* is a fact about something the studio has whatever is built; *ruling* is the owner's decision; *situation* is something the product must survive.

## What the owner wants

### MUS-001: Music is dropped in, indexed on its own, and sent to Resolve three ways.
- Why: The owner asked for drag-and-drop music ingest with automatic analysis, .ogg files converted to mp3, and three ways to send a track to Resolve.
- Must: A dropped music file is indexed with no further step, .ogg becomes mp3, and a track can be imported to a bin, inserted, or placed on the track below.
- Kind: ruling

### MUS-002: A track added from an editor's computer lacked tempo, key and loudness.
- Why: The owner asked that tracks analysed on an editor's computer match the library's original quality; those tracks had no tempo, key or loudness, and a differently computed tempo is worse than blank.
- Must: Every library track gets the same analysis, including tempo, key and loudness measured the same way, wherever it was added.
- Kind: ruling

### MUS-003: "Similar tracks" returned only tracks from the same stock library.
- Why: The owner wants a track's file name ignored for tags, genre and mood; similar-track results came back from one stock library only.
- Must: Search and "similar" rank by sound, tags, genre and mood; a file name never affects results, and similar results are not dominated by one source library.
- Kind: ruling

## Which files are music

### MUS-004: Raw .aac tracks showed wrong durations, one off by 7 minutes.
- Why: Raw .aac files store no duration, so quick readings estimate from bitrate and size; 85 of 89 were wrong, defeating duplicate checks by duration.
- Must: Durations of raw .aac files come from decoding the audio, never from an estimate.
- Kind: given

### MUS-005: Interview and field recordings swamped the music scan.
- Why: Of 2,384 audio files on the NAS, 397 were music; the rest were recorder and multitrack takes, wireless-mic files, voiceover, stings under 30 s and files over 15 minutes.
- Must: Music ingest excludes recorder takes, voiceover, stings under 30 s and recordings over 15 minutes, and keeps stems apart from tagging.
- Kind: situation

### MUS-006: Tracks named only by a library number were merged as duplicates.
- Why: Stock-music downloads are often named by a numeric id alone, so stripping numbers to compare names collapsed them; one track also comes as both preview and master.
- Must: Numeric-id names stay distinct when deduplicating, and of true duplicates the best format (wav, flac, aac, mp3, ogg) with the readable name is kept.
- Kind: situation

### MUS-007: Music tracks over two hours got a false length and heavy memory use.
- Why: Decoding held about three times the track's raw audio in memory, and anything over two hours was recorded as exactly 7,200 seconds.
- Must: Music of any length is indexed with its true duration and bounded memory use.
- Kind: situation

## Adding tracks to the library

### MUS-009: Music dropped while the NAS share was unmounted was answered "queued" and lost.
- Why: An unmounted share is an empty folder on the server's own disk; uploads landed there, hidden once the share mounted back, including for seconds after a NAS reboot.
- Must: Every write into the library confirms at that moment that the share is mounted and is the library; otherwise the upload is refused with the reason.
- Kind: situation

### MUS-010: A mounted, full music library was reported missing and closed all ingest.
- Why: Presence was judged by whether sampled indexed files existed; old tidied files, and new records whose audio had not yet arrived, made a mounted library look absent.
- Must: The library is judged present by the share itself, so removed files or an import in progress never make a mounted library refuse new music.
- Kind: situation

### MUS-011: A new upload took over an existing or promised track's name.
- Why: Names were checked against disk only, ignoring tracks already listed and names promised to uploads still in flight, so later items overwrote earlier ones.
- Must: A library name is never given to two items, counting every import not yet landed, and the name shown before importing equals the name given.
- Kind: situation

### MUS-012: A track that failed local analysis stayed only on the editor's computer.
- Why: Library names are issued after analysis, so a track that could not be analysed locally had no name and uploading under its own could overwrite another editor's file.
- Must: A track that cannot be analysed locally is still uploaded and queued under a library-issued name; nothing reaches the library under a name the library did not issue.
- Kind: situation

### MUS-013: Choosing a free file name spun forever when the library could not be checked.
- Why: Every "is this name taken" check answered taken on any error, so a share the server could list but not enter made every candidate taken.
- Must: "Could not tell" is a retryable error, picking a name gives up after a fixed number of candidates, and the page says the library cannot be checked.
- Kind: situation

### MUS-015: Nothing searchable may be missing its audio.
- Why: Tracks were listed before their audio uploaded, so a cancelled batch left them searchable but silent.
- Must: A track appears in search only once its audio is in the library, and a cancelled batch removes or finishes every track it started.
- Kind: situation

### MUS-016: A failed track stayed "pending" for ever and blocked its corrected re-drop.
- Why: Analysis failures never reached the live library, so the track looked pending and a good re-drop was refused as a duplicate.
- Must: A track that fails analysis shows as failed in the library with its reason, stops being retried, and does not block a corrected re-drop.
- Kind: situation

### MUS-017: The library did not show new tracks until a reload.
- Why: When an ingest finished, the list, counts and header stayed unchanged, and a blank waveform on a new track looked broken.
- Must: When an ingest finishes the library refreshes once, newest first, and a track with no waveform yet says why and that seeking still works.
- Kind: situation

## Imports across computers

### MUS-018: A thirty-second NAS blip failed every track of an album drop for good.
- Why: The library's "try again later" answers (share not mounted, two tracks racing for one name) were treated as final, retried back to back, with no retry button.
- Must: A retry-later answer is retried with pauses for about twenty minutes before failing with the library's words, and a failed track can be retried from the page.
- Kind: situation

### MUS-019: A track that recovered once was failed for good by the next brief outage.
- Why: The count of failed sends was never reset after one succeeded, so a track that recovered on try 5 had one try left for its next blip.
- Must: Every retry budget resets after a success, so a later outage gets the full number of tries.
- Kind: situation

### MUS-020: A track that was saved got an error reply and was failed for good.
- Why: A busy library made a follow-up bookkeeping read fail, turning a successful save into an error the sending computer treats as final.
- Must: A track whose save succeeded is answered as a success even when a follow-up bookkeeping read fails.
- Kind: situation

### MUS-023: Cancelling a batch nobody was working on hung on "cancelling" for ever.
- Why: The cancel waited for a confirmation from a computer that never held the batch, or whose hold had lapsed, leaving it shown as live with no button to end it.
- Must: Cancelling work no computer holds, or whose holder has lapsed, ends it at once; no state exists that neither cleanup nor any button can leave.
- Kind: situation

### MUS-024: A finished batch read "11 of 12 tracks" for ever.
- Why: Tracks ending as "queued for later analysis" or waiting for another computer counted as neither done nor failed, and clean-up deleted files they still needed.
- Must: Every ending state counts towards the total, waiting tracks are named, and no clean-up removes a file a waiting track still needs.
- Kind: situation

### MUS-025: After a page reload, staged or retried music could not be sent by any button.
- Why: Only the page remembered the batch, so after a reload send, cancel, retry and take-over were refused, and the fallback advice started a different import.
- Must: After a page reload, staged work can still be sent, cancelled, retried or taken over from the page, and no fallback advice starts a different import.
- Kind: situation

### MUS-027: An open music tab kept starting work on the editor's computer.
- Why: An open music tab made the editor's app start a fresh worker every 30 seconds, Resolve running or not, about 14 GB of temporary writes an hour.
- Must: A browser tab left open for an hour causes no repeated process starts and no growing disk writes on the editor's computer.
- Kind: situation

### MUS-028: An analyser already downloaded was treated as missing until a restart.
- Why: Pressing Run did nothing because an analyser already on disk was read as absent for the whole session.
- Must: An analyser already on disk is found without restarting anything.
- Kind: situation

### MUS-029: The music analyser refused to download from the studio's own update server.
- Why: Allowed download hosts were fixed to one public host, so a site publishing updates elsewhere had music analysis refused, with a sentence blaming correct settings.
- Must: The product's own components download from wherever the site's update feed lives, over https (plain http only on the same computer), checked against a pinned fingerprint.
- Kind: situation

### MUS-030: An analyser that failed its check still loaded, replacing the good one.
- Why: The new analyser was written into place before it was checked, and anything complete-looking was loaded without asking whether it had passed.
- Must: An analyser or index that fails verification never replaces the working one, and none is loaded without a recorded passed check.
- Kind: situation

## Keeping the library's data whole

### MUS-033: A newly published library was not what search answered from.
- Why: Search kept answering from the previous library after a publish or new tracks, until someone restarted the dashboard.
- Must: After a library is published or tracks are added, browse and search answer from the new data within a minute, without a restart.
- Kind: situation

### MUS-034: A 200-track album drop re-scored the whole library 200 times.
- Why: Each added track re-scored all tracks and rebuilt the search, about 1.7 million writes for one album.
- Must: Library-wide recomputes after ingest are batched, at most once a minute and once at the end of a drop.
- Kind: situation

### MUS-035: A track added while the library was being re-scored stayed untagged.
- Why: A library-wide re-score cleared the "needs re-scoring" mark at its end, wiping the mark a track added during the pass had set.
- Must: A track added at any moment ends up with tags and moods and is found by every filter.
- Kind: situation

### MUS-036: A failed re-tagging wiped every tag in the library.
- Why: Re-scoring deleted all tags first and wrote new ones at the end; a failure in between left the deletion pending, and the next unrelated save committed it.
- Must: A failed recompute leaves the previous tags exactly as they were, and the library says when its tags are behind.
- Kind: situation

### MUS-037: A renamed track stayed in search and failed only at send to Resolve.
- Why: Renaming a library file added a new entry but never removed the old; about a third of the library has numeric names, so renaming is routine.
- Must: A track whose file was renamed or deleted on the NAS leaves search at the next indexing, so every result can be sent to Resolve.
- Kind: situation

### MUS-038: A track's preview played a deleted track's audio.
- Why: Previews were chosen by a track number that a new track could inherit from a deleted one, while waveform, tags and Resolve got the new file.
- Must: A track's preview always plays that track's own audio; a preview made for different audio is never served.
- Kind: situation

### MUS-040: A library was marked upgraded although its upgrade never ran.
- Why: Re-stamping the version on every open moved a live 376-track index past an upgrade that then never ran; a missing part showed the feature as absent.
- Must: An upgrade counts as done only when the data has the new shape, and a broken feature shows as degraded, never as absent.
- Kind: situation

## Searching and filtering

### MUS-041: Filters stayed lit but were ignored, or threw away the typed search.
- Why: Mood, axis and tempo filters were dropped from description searches while shown on, and changing a filter reloaded the whole library while the box kept the query.
- Must: Every filter shown as on applies to browsing and description search alike, and changing a filter narrows the current search instead of discarding it.
- Kind: situation

### MUS-042: A tempo filter silently hid every track whose tempo was unknown.
- Why: Tracks with no measured tempo or length were excluded by any tempo or length filter without saying so.
- Must: A filter never silently hides tracks whose value is unknown; it says how many are hidden and offers to include them.
- Kind: situation

### MUS-043: A broken search looked like "nothing matches".
- Why: Failed searches (analyser not loaded, session expired, busy library) showed the empty result with advice to loosen the description.
- Must: A failed search says so with the reason and Try again, an expired session says to reload and sign in, and "nothing matches" appears only for a real empty answer.
- Kind: situation

### MUS-044: An empty "similar tracks" result advised rewording a description nobody typed.
- Why: One empty-state sentence served every kind of music search, and a filter matching nothing said the library was empty.
- Must: Each kind of search or lookup has its own empty-result sentence, and an empty filtered result says which filter removed everything.
- Kind: situation

### MUS-045: One failed panel blanked the whole music page.
- Why: If one statistics or filter request failed at load, the whole page showed a raw status line instead of the library.
- Must: One failed part of a page shows its own error while the rest of the page works.
- Kind: situation

## Listening in the browser

### MUS-046: Audio players probing with a header-only request before seeking were refused.
- Why: Browser players first ask only for headers (HEAD) to learn the length and range support, and the audio address answered "method not allowed".
- Must: Every audio and video address answers HEAD with the same headers as GET, including range answers, and sends no body.
- Kind: given

### MUS-047: Audio players asking for a file's last bytes were sent its first bytes.
- Why: Players ask for "the last N bytes" to read tags and duration at a file's end; sending the start gives wrong durations or no seeking.
- Must: Media serving answers "last N bytes" requests correctly, and answers an unreadable or reversed range with the whole file.
- Kind: given

### MUS-048: Preview audio kept playing with no way to stop it.
- Why: A new search cleared the list while a preview played, leaving no controls, and pause and seek did nothing until the waveform finished loading.
- Must: Playing audio always has a visible stop, and play, pause and seek work from the moment the player opens.
- Kind: situation

### MUS-049: A half-synced track's waveform request failed with a raw server error.
- Why: A truncated or undecodable file made the waveform fail with a raw error, on a request made for every track clicked.
- Must: A track that cannot be decoded answers with a named "could not be read" reason, the log names the track and file, and the page keeps working.
- Kind: situation

## Sending to Resolve

### MUS-051: The reveal button silently did nothing on every editor's computer.
- Why: The button opened a file window on the NAS serving the page, not on the editor's computer, and the failure was thrown away.
- Must: Every action on an editor's files or Resolve runs on that editor's own computer, and a button that fails tells the person why.
- Kind: situation

### MUS-052: Inserting music at the playhead cut into a clip spanning that point.
- Why: The insert shifted or removed timeline content before finding that a clip straddled the insert point, so the cue overlapped, lost its tail, or cut the clip.
- Must: Inserting music refuses, before changing anything, when a clip straddles the insert point.
- Kind: situation

See also, filed under another capability:

- BRO-106 (The b-roll archive): Send to Resolve on a remote computer failed with "file not found".

## Keeping files safe

### MUS-053: A file uploaded from a Windows browser can carry backslash path tricks.
- Why: A Windows browser can send an upload name like "..\..\evil.wav"; a server that splits names only on "/" keeps the traversal shape.
- Must: Every uploaded file name is cut to its last part on both "/" and "\" before use, so no upload can name a path outside its folder.
- Kind: given

### MUS-054: A file name containing "&" could run a command when "reveal in folder" was clicked.
- Why: The Windows command shell treats "&" as a command separator, and passing a path through it let a name run a command.
- Must: File names are never interpreted by a shell; a name like "rock&roll.mp3" opens the right folder and runs nothing.
- Kind: situation

### MUS-055: A file request from a web page could follow a link outside the library.
- Why: On a Mac whose music share was found by scanning mounted volumes, the containment check was skipped, so a symbolic link out of the volume was followed.
- Must: A file request from any web page resolves links and refuses anything outside the shared library, however the library was found.
- Kind: situation
