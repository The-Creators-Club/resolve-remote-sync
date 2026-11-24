# Music

Music is the studio's library of tracks for scoring films: a person drops audio in, the product takes it into the library and analyses every track on its own, and anyone signed in can find music by describing the sound they want, browse and filter the library, listen in the browser, and send a track straight into the editing program on their own computer. Editors use it while cutting; an admin also sees everyone's drops. Music is one of the six parts a site switches on and off. When it is off, nobody but an admin sees it, and only in settings, where it is listed with its switch: there is no music page, no music entry in the menu bar or in search, no music lines or buttons in the app on an editor's computer, and no computer analyses or downloads anything for music. Switching it off never deletes a track, a tag or a drop, and switching it back on brings everything back as it was.

## What the owner wants

### A site switches music on and off

Music is one part a site can switch on and off by itself. When it is switched off, its work stops everywhere: drops still being taken in or analysed stop where they are and keep their place, no computer starts analysing music or downloading what music analysis needs, and the app on each editor's computer drops every music line, button and notice. Every action music offers on an editor's computer, opening a track's folder included, follows the same switch. Nothing is deleted: the library's files, every track's description, tags, waveform and listening copy, and every drop with its tracks stay as they are, and switching music back on carries on from there.

- Who: an admin.
- Setting: Music. Does: shows or hides the music library for everyone and starts or stops all music work. Default: off. Who: an admin. Applies to: the site. Search words: music, library, tracks, soundtrack, part, switch.
- When the help for the editing program is off: music stays usable, and every place that would send a track to the editing program offers to save the track's file instead.

### The music page is a page of the dashboard

The music page is part of the dashboard and carries the dashboard's own menu bar. If the menu bar cannot be fetched, a plain header with the product name and a link back to the overview is shown instead, so the page always has a way home. Every music page and every answer it asks for is behind the dashboard's sign-in. If the page fails while starting, the list area reads "Loading the page failed: …" with the reason. A part of the page that fails shows its own error in its own place and the rest of the page keeps working. A music page left open for hours causes no growing work or disk writes on the computer it is open on.

- Who: anyone signed in.
- Name and search words: Music. Search words: music, tracks, library, soundtrack, score, songs.
- Phone and desk: below about 900 pixels wide the header no longer stays at the top, the filters stack above the results and the list of dropped tracks takes the full width. Below about 600 pixels, text fields use a text size large enough that a phone does not zoom in when one is tapped. On touch screens every control is at least 44 pixels to tap.

#### Lessons

- Met: MUS-001, MUS-002, MUS-003.

## Which files are music

### The library takes audio files, and editors see it as one flat folder

The library takes audio in WAV, MP3, FLAC, AAC, M4A, OGG, AIFF (either spelling of its ending) and Opus form. Anything else is refused as "not an audio file (<ending>)", or left out of a drop. A file with no playable sound, or a sound of zero length, is refused ("no decodable audio stream"). OGG files are converted to high-quality MP3 when they are added.

In their file browser and in the editing program, editors see the library as one flat folder, the Music folder under Assets in the studio's shared tree, with every track directly in it.

A track's length is always measured by decoding its sound, never taken from what the file claims or estimated, so raw AAC files and tracks of any length, two hours and longer included, show their true length.

### Recordings that are not music stay out of the library

When the product looks over a whole folder of mixed audio, recorder takes, voiceover, stings shorter than 30 seconds and recordings longer than 15 minutes are left out, and anything inside a folder named "_stems" is kept apart from tagging, so interviews and field recordings never swamp the music. A track a person drops in by hand is always taken, whatever its length.

### Tracks named only by a number stay apart from each other

When the product decides whether two files are the same track, names that are only a library number are compared as numbers and stay distinct, so a stock library's numbered tracks are never merged. Of true duplicates arriving together, the copy in the best form is kept (in order: WAV, FLAC, AAC, MP3, OGG), carrying the more readable name.

#### Lessons

- Met: MUS-004, MUS-005, MUS-006, MUS-007.

## Adding tracks to the library

### Dropping audio anywhere on the music page adds it to the library

Dragging files over the music page covers it with "Drop audio to add it to the library" and "It is analysed on its own and becomes searchable. .ogg is converted to mp3." A person can also press "Add music" and pick files ("Choose files…") or a whole folder ("Choose a folder…"); cancelling the picker does nothing and says nothing. A dropped or picked folder is searched all the way down, keeping only audio files. Once dropped, a track needs no further step: it is taken into the library and analysed on its own.

Limits a person plans around:

- at most 500 tracks in one drop: "A drop holds at most 500 tracks. Let this one finish first." or "Only the first N tracks were taken: a drop holds 500.";
- at most 537 MB a file: "that track is N MB and the library takes at most 537 MB per file".

A drop with nothing usable reads "Nothing there this app can index: music takes .wav, .mp3, .flac, .aac, .m4a, .ogg and similar." A drop with files that are not audio leaves them out and says "<n> of these are not audio files", naming up to 20. A drop is never refused for lack of free space on the person's own computer.

- Who: anyone signed in. No separate key is needed.
- Ways in: dropping files anywhere on the music page, and "Add music" with its file and folder pickers.

### A person chooses whether their drop is analysed now or while they are away

When dropping, a person chooses "Only when idle" (the default) or "Foreground". The choice says when the person's own computer may give its time to this drop: "Only when idle" means only while nobody has been at that computer's keyboard or mouse for the computer's quiet time (5 minutes unless changed) and, while its hold-back for Resolve is on (as it is unless changed), Resolve is closed, as for all shared work. When the person comes back, the track under way is finished and saved, and no further track starts until the computer is free again. "Foreground" is the start now that shared work offers: the drop is analysed at once, while they work, within the share of a working computer's capacity the site allows such work. The quiet time, the hold-back for Resolve, start now and the share, with their settings, are in Work shared out across the computers: When a computer counts as free and able, "A computer takes shared work only while nobody is using it". When the computer cannot tell whether the person is away it counts them as present, and when it cannot tell whether Resolve is open it counts it as open. A summary reads "<n> track(s), <size> - will run now" or "- will run when you're away", or "nothing selected". The analysis is done on a computer of the studio's that is able and free (see Work shared out across the computers: Choosing who runs what); this choice only governs the person's own computer.

### Each dropped track shows its state until it is in the library

The drop's tracks appear in a list at once. Each row has a tick box (a track can be unticked until its work starts), the track's name, and a line with its size, its length, "will be saved as <name>" when it will be renamed, or "already in the library as <name or track #id>". The head reads "<k> of <n> track(s) selected". Duplicates are found before anything is added: a duplicate is unticked the first time it is found.

| Of | States, as shown |
|---|---|
| A drop | "waiting", "working", "all done", "finished, some tracks failed", "cancelled", "failed" |
| A track | "waiting", "converting", "uploading", "analysing", "in the library", "waiting to be analysed", "already in the library", "failed", "cancelled", "skipped" |

An unknown state is shown as it came. A line for the drop reads "N of M done · L in the library · F failed · D duplicate", with what is happening now (the current file and step, "downloading the music analysis N%", or waiting for the person to step away), and up to 200 lines "<state> · <name> - <error>". Every ending state counts towards the total, so a finished drop always adds up. A track in the library reads "✓ name - m:ss, NNN bpm"; a failed one "✕ name - <error>". The list follows progress within a couple of seconds. Nothing is ever shown as working when nothing is working on it.

A track's sound is in the library, safe and playable, as soon as it has arrived. It appears in search once it has been analysed, with no further step. While it waits, the list reads "Waiting to be analysed: N track(s). They are in the library already and become searchable once analysed." with up to 20 names, and says plainly when no computer of the studio's can analyse music at the moment, and why. Tracks that could not be analysed are listed as "N could not be analysed. Nothing retries these on their own: fix the file and drop it again." with up to 20 lines "✕ name - reason". Both lines are hidden when they are zero.

### A person pauses, resumes, starts now or cancels their drop

"Pause", "Resume" and "Start now" act on the drop at once and are confirmed in a short notice. "Start now" switches a drop waiting for the person to step away to working at once. "cancel…" asks "Stop this drop? Tracks already in the library stay there; the rest are dropped. Your own files are not touched." and reads "Cancel requested: it stops within about 30 seconds." Cancelling always ends the drop: tracks already in the library stay, and every other track the drop started is taken out again, never left half there (except while the library looks unmounted, when nothing is removed). No state exists that no button and no clean-up can end. When the drop ends, its heading becomes "Last drop" and every control is disabled.

- Who: the person who dropped it, or an admin.
- Ways in: the music page, and the app on the editor's computer while that computer is working on the drop.

### When a drop finishes the library refreshes and shows the newest tracks first

When a drop being watched finishes, a notice reads "Ingest <state words>: the library below is refreshed, newest first." The page refreshes its totals, tags and sliders once and switches the sort to newest, and the finished tracks leave the drop list.

### The same track is not added twice

A track is refused as "already in the library as <name> (same track)" when its name, once simplified (letter case, a stock-library prefix and copy markers like "(2)" ignored, only letters and digits compared), matches a track already in the library or on its way in, and the two lengths are within 2 seconds of each other. This catches the same track encoded again. A track is refused as "already in the library as <name>" when its bytes are identical to a track already there or on its way in. The library's own copy is always the one kept.

- On its own: a duplicate is unticked in the drop list before anything is added.
- By hand: a person can tick it again; the library still refuses an identical or same-length same-name track with the words above.

### Each track gets its name in the library before it is added

The name a person is shown before a track is added ("will be saved as <name>") is the name it gets, and no name is ever given to two tracks, counting every track still on its way in. A name is cleaned: any folder part is dropped (on both "/" and "\"), characters Windows forbids are replaced by an underscore, and an empty name becomes "untitled". If the name is taken, in either Unicode spelling, it becomes "name (2)", "name (3)" and so on, up to about a thousand, and is then refused. Every track is readable by every editor over the network.

When the library is briefly busy or unavailable, the track waits and tries again with growing pauses for about twenty minutes, showing "the library is not ready yet: <detail>", and nothing already done for it is done again. When the library cannot even be checked, that counts as "not ready", never as a refusal, and the page says the library cannot be checked. Every such allowance starts afresh after a success, so a later outage gets the full time again. Any other refusal, or a track whose time ran out, reads "the library would not take this track: <detail>", and the track can be tried again from the page. A track that was saved is reported as saved, even when a follow-up check fails.

### Every track is described the same way wherever it was added

Every track in the library carries the same description, measured the same way however it was added:

- its length, measured from the sound itself;
- its tempo in BPM to one decimal, always between 60 and 190, judged from the first six minutes, or none when it cannot be judged;
- its musical key, such as "A minor" (major or minor), with a confidence;
- its loudness: integrated LUFS for anything longer than half a second, and its peak level;
- a waveform overview of 900 points, scaled to the track's own loudest moment;
- its tags in five categories and its four feels (see "The tags and feels a track can carry");
- what it sounds like, both as a whole and in up to twelve 10-second stretches spread across it (leaving out the first and last 2 %), for search and for similar tracks. A track of 10 seconds or less is judged whole.

A track that cannot be analysed is skipped and the rest carry on. Tempo, key and loudness are shown on each track's row in the list.

### The tags and feels a track can carry

Tags are chosen from fixed lists. Each track keeps its top 3 genres, 4 moods, 4 instruments, 3 use cases and 3 textures, each with a score and its rank against the rest of the library as a percentile.

| Category | Labels |
|---|---|
| Genre | orchestral, ambient, electronic, synthwave, hip hop, rock, post-rock, folk acoustic, jazz, classical, east asian, world folk, lo-fi, pop, trailer epic, choral, experimental, blues soul |
| Mood | tense, ominous, dark, uplifting, hopeful, triumphant, melancholy, nostalgic, peaceful, mysterious, urgent, playful, romantic, aggressive, contemplative, eerie, grand, lonely, determined |
| Instrument | piano, strings, solo cello, acoustic guitar, electric guitar, synth, drums, percussion, brass, woodwind, choir, electronic beat, bass, east asian str, mallets, organ, harp |
| Use case | interview bed, montage, opening titles, tension build, emotional payoff, action, underscore, credits, reveal, timelapse |
| Texture | sparse, dense, lo-fi tape, clean, gritty, pulsing, drone, glitchy |

Four feels are kept for every track, each ranked as a percentile across the library: arousal (energetic against calm), valence (happy against sad), tension (anxious against relaxed) and organic (acoustic against electronic).

Scores are judged against the whole library, so a track's tags and ranks can shift as the library grows. A track plainly named for its sound, such as "Solo Piano", carries the matching tag.

### OGG tracks enter the library as 320 kbps MP3

An Ogg Vorbis file is converted to MP3 at 320 kbps, keeping its details such as title and artist, before it is analysed. The conversion gives up after 15 minutes, and fails when the result has no sound ("transcode produced a file with no audio"). Every other kind of audio enters the library as it is.

### A track that cannot be read or analysed fails with a plain reason

A dropped track that cannot be done ends as failed, with one of these reasons:

- "the source file is not on this computer any more";
- "this file has no audio track that could be read";
- "this file could not be read (<error>)";
- "this file could not be converted to mp3: <error>";
- "this track could not be analysed: <reason>";
- "this file could not be decoded (<error>)";
- "the music analysis gave an unusable result for this file";
- "stopped", when the person stops the drop.

Reading a file gives up after 2 minutes and analysing it after 15 minutes. A failed track shows as failed with its reason and is not retried on its own. It never blocks the same track, corrected, from being dropped again.

#### Lessons

- Met: MUS-009, MUS-010, MUS-011, MUS-012, MUS-013, MUS-015, MUS-016, MUS-017.

## Imports across computers

### A drop survives the page closing, a restart and the network dropping

A drop is never lost and never done twice. Closing the page, reloading it, the person's computer or the app on it restarting, or the network dropping for a while leaves every track where it was: when the page is opened again it shows the person's unfinished drops, and each can still be paused, resumed, cancelled or have its failed tracks tried again. A track whose work was cut off is done again from the start of that step. A dropped file that has gone from the person's computer before it was taken in fails with "the source file is no longer on this computer (the drive was unplugged, or it was moved)".

### A person sees their own drops, and an admin sees everyone's

The list of drops has "Mine" and, for an admin only, "Everyone"; anyone else asking for everyone's is refused "only an admin can see everyone's drops". It shows the newest first, at most 200, and keeps itself up to date. Each drop shows its state, the person (in Everyone), its age ("just now", "N min ago", "N h ago", "yesterday", "N days ago", with the full time in the hint), the run choice, its counts, "cancelling" and any error. "tracks" and "hide tracks" show or hide up to 200 track lines. With none: "no drops yet". Another person's drop is invisible to anyone but an admin, answering as if it did not exist ("no such drop").

"try the failed tracks again" (finished drops with failures) puts the failed tracks back, keeping their names: "Nothing in that drop had failed." or "N track(s) back in the queue." It is refused while the drop is still being worked on: "This drop is still being worked on. Stop it first, then try the failed tracks again."

- Who: anyone signed in sees and acts on their own drops; an admin sees everyone's and may cancel any.

### An editor sees music analysis on their computer while it is doing it

While the editor's own computer is analysing music, the app on it shows one line in its menu, in tracks, and the buttons that act on the drop are in its settings window while a drop exists: pause, resume, index now, show the progress and cancel. The line's wording, the music failure line included, and the buttons' labels are in The app on each editor's computer: Telling the editor what is wrong, "The menu carries a line for each piece of work under way".

What each button answers:

- Index now: "Analysing music now. It keeps going while you work."
- Pause: "Music indexing paused. Nothing already indexed is lost."
- Resume: "Music indexing will carry on from where it stopped."
- Cancel asks "STOP INDEXING THIS MUSIC": "<done> of <total> tracks are already in the library and they stay there. The rest will not be indexed. The tracks themselves are not deleted." with "STOP INDEXING", then "Music indexing stopped."

The progress window "INDEXING MUSIC" has the second line "Your tracks are being analysed on this computer. Closing this window does not stop it." When it opens by itself, how it is opened again, what it shows, its buttons and when it closes are in The app on each editor's computer: Windows, dialogs and notifications, "Long background work has a progress window the editor can close and reopen". Signing out on the computer stops new work at once.

Whether this computer takes part in music analysis at all is its own choice, set with its settings for sharing heavy work (see Work shared out across the computers: When a computer counts as free and able).

- Who: the editor at their own computer.

### Music analysis needs a one-off download of about 280 MB on a computer that does it

A computer that analyses music for the first time downloads what it needs: about 280 MB, once. Music analysis needs no graphics card. The download comes from wherever the site's updates come from, only over a secure connection (a plain connection only to the same computer), only from places the product trusts, and is checked against a fingerprint the product carries. What fails the check is never used and never replaces a copy that works. A copy already on the computer is found without restarting anything. The download needs its own size plus about 200 MB free on the disk; a disk whose free space cannot be measured does not refuse.

When the person sitting at that computer started the work there with "Foreground", they are asked first: "The music analysis isn't on this computer yet. Running this drop downloads it first (about <size>). Continue?" with Cancel (the default) and "Go ahead". A tray notice appears when the download starts. A progress window names "the music analysis" with percent, rate and time left, and "The music analysis is ready. Indexing starts now." appears when it is done. A stopped download resumes where it left off: "the download was stopped - it will resume where it left off". Refusals and failures:

- "refusing to download the music analysis: <host> is not one of the places this product is allowed to fetch from";
- "Not enough disk space for the music analysis: needs about X GB free at <folder>, has Y GB. Free some space and try again";
- "the music analysis download did not pass its check - the file was deleted and will be fetched again";
- "the music analysis could not be downloaded: <error>";
- "the music analysis could not be loaded on this computer (<error>)".


### An editor is told plainly when their computer must update before music works

When the app on an editor's computer must be updated before it can analyse music or open a track's folder, the editor is told so in one plain sentence, with the update offered: "Your CC Sync app needs the update it offers before it can do this. Take the update, then reload this page." Every track is described the same way, so a computer that would describe tracks differently from the rest of the library takes no music work until it is updated.

### Analysing music keeps the computer it runs on usable

Music analysis uses a graphics card when the computer offers one. While someone is using the computer, analysis uses no more than the share of that computer's capacity it allows shared work (see Work shared out across the computers: When a computer counts as free and able, "A computer takes shared work only while nobody is using it"). The memory it takes is given back as soon as the work stops. It never holds back the making of proxies on that computer. While a computer is analysing music, or downloading what it needs, it is kept from sleeping, and a shutdown is met with a warning (see The app on each editor's computer: Starting, staying running and crashing, "A computer doing heavy work stays awake and warns before shutting down").

#### Lessons

- Met: MUS-018, MUS-019, MUS-020, MUS-023, MUS-024, MUS-025, MUS-027, MUS-028, MUS-029, MUS-030.

## Keeping the library's data whole

### Tags across the library catch up as tracks arrive

Because tags and feels are judged against the whole library, adding tracks refreshes every track's tags and feels. When tracks arrive in quick succession this happens at most about once a minute, and once more when a drop ends, so a 200-track album is not re-scored 200 times. In between, the page shows "tags catching up". A track added at any moment, even while the library is being re-scored, ends up with its tags and feels and is found by every filter. A refresh that fails leaves the previous tags exactly as they were and keeps "tags catching up" showing.

### What people add is never lost, and every change shows within a minute

A track a person added, and everything known about it, is never lost or rolled back by any later update of the library, its analysis or the product. After tracks are added or the library changes, browsing and search answer from the new data within a minute, with nothing restarted and nothing for anyone to do.

### When music cannot work, it says so

When music cannot work (for example its data cannot be read by this version of the product), music is shown as not working with the reason wherever the state of each part is shown, and its link is not offered as working. A music feature that cannot run is shown as not working with its reason, never as switched off or absent.

#### Lessons

- Met: MUS-033, MUS-034, MUS-035, MUS-036, MUS-037, MUS-038, MUS-040.

## Searching and filtering

### A person finds music by describing the sound they want in their own words

The music page has one search box, hinted "describe the vibe… tense driving synth pulse, warm nostalgic piano, hopeful build for a montage". Enter or the search button runs the search; Enter is the only key shortcut on the page. An empty box shows the library instead (browsing). A choice beside the box sets how a track is matched:

- "any moment" (the default): a track is scored by its best single 10-second stretch, from up to twelve stretches spread evenly across it, ignoring the very start and end;
- "whole track": scored by the track as a whole.

Changing that choice runs the search again only when the box has text. A search returns at most 60 tracks, best match first, ranked by how they sound, their tags, genre and mood; a file's name never affects the results. Each carries a match figure from 0 to 100 that is relative to this result set only: the best hit shows 100, the weakest 0, and a single hit 0. Filters that are on apply to search exactly as to browsing, narrowing the 60 tracks chosen, so a filter can only thin the results. A very long description is cut short: only its first several hundred words count. A plain description of a track's sound finds it within the first ten results.

### Eight example descriptions run a search with one click

Under the search box are eight ready-made searches, each of which runs at once: "tense driving synth pulse", "warm nostalgic piano", "hopeful build for a montage payoff", "sparse ominous drone under an interview", "triumphant orchestral finale", "playful quirky plucked strings", "traditional east asian strings", "gritty industrial percussion".

### One clear control resets the whole search

"clear" empties the search box, deselects any tag, sets every feel slider to "off", unticks "Include tracks with no BPM or length", empties the tempo and length boxes, and lists the whole library again.

### The page shows the size of the library and whether its tags are up to date

A line reads "<n> tracks · <h>h · <GB> GB" (hours to one decimal, gigabytes to two), with " · tags catching up" added while the library's tags are behind recently added tracks. If the totals cannot be fetched it reads "library totals did not load", with the reason in the hint, and the rest of the page keeps working.

### A person can filter by feel, one feel at a time

There is one slider per feel, in this order with these labels: "arousal: calm → intense", "valence: dark → bright", "tension: resolved → tense", "organic: electronic → acoustic". Any further feel the library has is added after these, labelled "low → high". Each slider has "off" in the middle and can be moved towards either end, in steps of 5 percentiles. Moved towards the high end it reads "<high word>: top N%" (for example "intense: top 20%") and keeps only the tracks ranked in the top N% of the library on that feel; moved towards the low end it reads "<low word>: top N%" (for example "calm: top 20%") and keeps only the tracks ranked in the bottom N%, so a person can ask for the calmest, darkest, most resolved or most electronic tracks as easily as for the most intense. Above the sliders: "One at a time: moving a slider clears the others." Releasing a slider sets the others to off and runs the current search again, or the browse list if the box is empty.

### A person can filter by tempo and by length

Boxes for lowest and highest BPM (0 to 300) and for shortest and longest length in seconds are committed together by "apply", which runs the current search or browse again. An empty box, or 0, means no limit on that side.

### Tracks with no tempo or length yet are never hidden silently

When some tracks have no BPM or no length yet, a tick box "Include tracks with no BPM or length" appears with "<n> tracks have no BPM or length yet" (n is the larger of the two counts); otherwise the line reads "every track has a BPM and a length". Ticked, a tempo or length filter also keeps tracks whose value is missing. When a filter hides tracks only because their value is missing, the results say "<n> track(s) have/has no <bpm|length> and are/is not shown" with an "include them" button (hint "Show tracks that have not been analysed yet") that ticks the box and runs the search again.

### A person can filter by a tag: genre, mood, instrument, use case or texture

Each tag category (genre, mood, instrument, use case, texture, then any other in alphabetical order) lists its labels with how many tracks carry each, most common first. Clicking a label selects it, one at a time across all categories, and narrows what is shown to tracks carrying that tag: the typed description stays and the search runs again with the tag, or with an empty box the library is browsed by that tag. Clicking the selected label again deselects it. Clicking a tag shown on a track row does the same as clicking that label in its list.

- Ways in: the tag lists beside the results, and the tags on each track row.

### The library list can be sorted, but search results keep their match order

Sort choices: file name (the default), newest (most recently added first), BPM, length. Sorting applies to browsing only. While search or similar results are shown, the sort control is disabled with the note "search results are in order of match" and the hint "Search results are ordered by how well they match. Clear the search to sort the library." With a tag selected and the sort left at file name, tracks are ordered by how strongly they carry that tag. Browsing shows at most 500 tracks.

### The results are headed by what is shown and how many tracks

A headline plus "<n> track(s)". Headlines: "All tracks"; a summary of the filters that are on, joined by " · " ("<category>: <label>", "<feel word>: top N%", "<min>-<max> bpm", "<min>-<max> s"); "“<query>” · any moment" or "“<query>” · whole track"; "Similar to <file name>"; "Just added"; "Searching…"; "Finding similar…"; and the failure headlines.

### Empty results say what to try

Each kind of search has its own sentence when nothing comes back:

- a description search: "Nothing matches. Try a looser description or clear the filters.";
- browsing with filters: "No tracks match these filters. Clear one and try again.", followed by the filters that are on, and, when one filter alone removed everything, that filter named;
- an empty library: "The library is empty. Drop some music in to get started.";
- similar tracks: "Nothing in the library sounds like this one yet."

"Nothing matches" appears only for a real empty answer, never for a failure.

### A failed search or browse says why, and a late answer never replaces a newer one

When the session has expired: "<what> failed: your session expired. Reload the page to sign in again." Otherwise: "<what> failed: the server answered <status> (or the network reason). Try again, and if it keeps happening tell your admin what this line says." For an admin the line does not end by sending them to an admin: it points them instead to the overview's list of problems and to the site's support contact. Only the answer to the person's latest request is shown: a slow search that comes back after a later filter change is dropped.

### Each track in the list shows what it is and offers play, similar and send

Each row has a play button; the file name; its length (m:ss), BPM (rounded, when known), key (when known) and loudness in LUFS (when known); its leading tags (top genre, top two moods, top instrument, top use case), each with a hint "<category> · score <s> · <pct>th percentile"; a match figure (search and similar only); a "similar" button; and a "→ Resolve" button, which opens the player under the row without starting playback. The play button opens the player under the row and starts playing; pressing it again on the open track pauses and resumes. Changing the list closes any open player and stops the sound.

- When the help for the editing program is off: the row has no "→ Resolve" button; the player it would open offers to save the track's file instead.

### A person can list the tracks that sound most like a given track

"similar" replaces the list with the 25 nearest-sounding tracks, leaving out the track itself, each with a match figure. Similar tracks are ranked by sound, tags, genre and mood, and are never dominated by the stock library the track came from: what tracks of one source library share only because they come from that library is discounted, for any source with at least 8 tracks in the library. A file's name never affects the results.

- Ways in: the track's row, and its open player.

#### Lessons

- Met: MUS-041, MUS-042, MUS-043, MUS-044, MUS-045.

## Listening in the browser

### A person plays a track in the browser with a waveform to click on

One player is open at a time, under its track's row. It shows the track's waveform with the played part marked, kept in step while playing and when the window is resized; clicking the waveform jumps to that point. It has a play/pause button, which is always there while sound plays, and a readout "m:ss / m:ss". Play, pause and seeking work from the moment the player opens. When the track ends the button returns to play. Captions under the waveform:

- no waveform yet: "No waveform yet: this track has not been analysed yet. Seeking still works.";
- connection lost: "The waveform could not be loaded: this page lost the server.";
- another failure: "The waveform could not be loaded (the server answered N).";
- a track whose sound cannot be decoded, such as one only half copied: "The waveform could not be loaded: this track could not be read."

A track that cannot be read never breaks the page.

### Listening uses a lighter listening copy where one exists, and starts and seeks at once

Each track can have a listening copy at about 128 kbps; the original is played where there is none. No listening copy is made for a track whose original is already at or below about 134 kbps, whatever its form. A listening copy keeps only the sound (cover art dropped), mixes surround down to stereo, keeps mono as mono and keeps the sample rate. A copy more than 3% shorter than its original is refused as cut short, and a copy older than its original is made again. A track's listening copy always plays that track's own sound: a copy made from other audio is never played. Playback can start anywhere in the track without the whole file downloading first, and seeking works in every browser and player, including players that ask for only the end of a file or ask about a file before fetching it. Taking a track out of the library takes its listening copy with it.

- On its own: listening copies are made for new and changed tracks without anyone asking.

#### Lessons

- Met: MUS-046, MUS-047, MUS-048, MUS-049.

## Sending to Resolve

### The page names a track by its place in the library, and each computer finds it in its own copy

The music page never sends a full path. It names a track by the library and its place inside it. On an editor's computer the music library is the Music folder under Assets in the shared tree, unless a setting on that computer names another folder. A place that leads outside the library (a full path, a drive letter, a network path, a step up, or a link pointing outside) is refused. With no library folder on the computer, the page is told so.

- Setting: Music folder on this computer. Does: where this computer finds the music library, when it is not the Music folder under Assets in the shared tree. Default: the Music folder under Assets in the shared tree. Who: an admin, or the editor for their own computer. Applies to: a computer. Search words: music folder, library location, path, this computer.

### An editor sends a track to Resolve on their own computer in one of three ways

Resolve can only be driven on the computer it runs on, so the open player's three buttons talk to the app on the person's own computer:

| Button | Hint | What happens | Note when done |
|---|---|---|---|
| "import to bin" | "Import into the Music bin in the media pool. Nothing is placed on a timeline." | The track is imported only. | "imported to the Music bin" or "already in the media pool (Music)", with the clip name |
| "place underneath" | "Place at the playhead on the first free audio track from A2 down. Nothing moves." | The track goes, sound only, at the playhead on the lowest audio track from A2 upward that is empty for the track's whole length from the playhead (A1 is kept for dialogue and sync sound). If none is free, a new stereo track is added ("could not add an audio track" if that fails). Nothing else moves. Needs an open timeline: "no timeline is open". | "placed on A<n> at the playhead - nothing moved", or the same with "(new track)" |
| "insert at playhead" | "Ripple insert on A2: clips at or after the playhead on that track shift later. Refuses if that track is linked to video." | The track goes at the playhead on A2 (added as a stereo track if missing), and every clip at or after the playhead on that track moves later by exactly the track's length. Needs an open timeline. | "inserted at the playhead on A<n>, <k> clip(s) rippled later" |

While the exchange runs, every player button is disabled and the status reads "talking to Resolve…". It ends with the app's note or "done" (shown as good), or its error or "failed" (shown as bad). If the app answered but refused: "the CC Sync app answered but refused the request (HTTP N)", pointing the person to the app's copy-diagnostics-for-your-admin action, which has the reason. If it could not be reached: "couldn’t reach the CC Sync app: it is not running, or the browser blocked local connections", followed by the app's local status address to open in a tab, and the advice that if that address answers that all is well, the browser is to blame, not the app (see The app on each editor's computer: Settings, records and background work, "The product's pages reach Resolve on the editor's computer through the app, and only the studio's pages may").

- Who: the editor at their own computer.
- When the help for the editing program is off: the three buttons are not there; the player offers to save the track's file instead.

### Every sent track goes into a Music bin once, and is online on every computer

If any clip anywhere in the media pool already points at the track (under this computer's spelling of the path or the shared spelling), that clip is used again. Otherwise the track is imported into a bin named Music (found anywhere in the bin tree by its name, or made at the top of the media pool) and, where it can be, pointed at the shared spelling so it is online on other computers too. If Resolve refuses: "Resolve refused to import <name>".

### An insert that would break the timeline is refused before anything changes

An insert is refused, with nothing touched, when:

- the playhead is inside a clip on that track: "the playhead is inside a clip on A<n> (frame X to Y), so it cannot be rippled whole. Move the playhead to a cut, or razor the clip there first, or use 'place underneath'.";
- a clip that would move has no media of its own (a compound, Fusion or generator clip): "A<n> holds a clip with no media pool source (compound, fusion or generator) at frame X - it cannot be safely re-appended. Use 'place underneath'.";
- a clip that would move is linked to picture: "A<n> is linked to video at frame X - rippling it alone would desync sync sound. Use 'place underneath'."

If it fails after clips were moved, whatever was placed is taken out and the moved clips are put back where they were: "insert failed; rolled back <restored>/<total> clip(s) on A<n>". Clips put back are placed fresh, so settings made on them in the timeline are lost.

### A placed track lands at the playhead in the timeline that is open, or not at all

If the editor switched timelines while the track was being placed: "the current timeline changed - nothing was placed". A placed track is read back, and one that landed a frame out is laid again once; only a track still not exactly at the playhead after that is taken out again: "placement failed on A<n> at frame X - something already occupies that span, or the track is locked". The playhead is read from the timeline's current timecode (drop-frame timecode understood), or the timeline's start if that cannot be read. The track's length on the timeline is its frame count converted from the track's own frame rate to the timeline's, else its duration at the timeline's frame rate, else one second, so an insert moves later clips by the track's true length on that timeline.

### A track the editor's computer does not have yet is fetched from the NAS when sent

Music is not synced to editors' computers. When a track sent to Resolve is not on the computer, that one file is first copied down from the library on the NAS, and the send carries on by itself once it is there. The page reads "track isn’t on this computer yet: syncing it down, then sending…", then "syncing the track to this computer: N%" (without a figure when unknown), until it is there. Which computers fetch, how many files a computer fetches at once, the wait while it is busy with other downloads and when that wait gives up, and every refusal and failure, each worded for a track, are those of the one fetch of a single missing file (see The b-roll archive: Sending a clip to Resolve, "A clip not on this computer yet is fetched first, with progress, and then placed").

### When Resolve is not ready for a track, the page is told why

- Resolve is not running or still starting: "could not reach DaVinci Resolve (<reason>). Is it running, with Preferences > System > General > External scripting = Local?" The app checks that Resolve is ready without connecting to it, so it never breaks Resolve's start-up.
- No project open: "no project is open in Resolve (the Project Manager window counts as no project)".
- Resolve took longer than 90 seconds: "Resolve did not respond within 90s. It is usually busy, showing a dialog, or on the Project Manager window." The request is abandoned after 90 seconds, so a Resolve that hangs never freezes the app on the editor's computer.
- The app could not do the work at all: "could not start the Resolve work: <error>", or the reason it gave.

The connection to Resolve continues in Resolve on the editor's computer: Connecting to Resolve's scripting: launch, stalls and death.

### The page shows whether the editor's Resolve is reachable and what is open in it

A status marker reads "Resolve · off" when the editor's own computer cannot reach Resolve, or "Resolve · <timeline name, else project name, else 'connected'>" when it can, with the hint "project X · timeline Y". It shows good or bad at a glance. With a timeline open, the page also learns its frame rate, its number of audio tracks and its current timecode; when Resolve cannot answer, it learns the reasons above. It is asked of the editor's own computer when the page opens, after every send, about every 30 seconds while the tab is in view (not while hidden), and at once when the tab comes back into view. Many open music pages never slow Resolve down.

- When the help for the editing program is off: there is no Resolve marker.

### An editor opens the folder holding a track on their own computer

"reveal" in the open player asks the app on the person's own computer to open the track's folder, and reads "opening the folder…" until it answers:

- the track is there: the file manager opens with it selected, "Showing <name> in <folder>";
- the track is missing but its folder is there: the folder opens, "<name> is not there - opened <folder> instead";
- neither: "<path> is not on this computer - is the share mounted?";
- the file manager cannot be opened: "could not open the file manager - see the CC Sync app's log".

Otherwise it ends with the app's message or "opened". An application or disk image is shown, never opened. A file name is never read as a command: a name like "rock&roll.mp3" opens the right folder and runs nothing. A button that fails always says why.

- Windows and macOS: Windows opens Explorer and macOS opens Finder. On any other system the person is told the path instead.

#### Lessons

- Met: MUS-051, MUS-052.

## Keeping files safe

### Nothing is written to the library when its share is not there

Every write into the library first confirms, at that moment, that the library's share is mounted and is the library. The library is judged present by the share itself, never by which tracks can be seen in it, so tracks removed by hand or a drop in progress never make a mounted library refuse new music. When the share is not there, the drop is refused with nothing written: "the music library is not mounted here (nothing at <path>). Nothing is written until it is back." When the library cannot be checked at all, the person is told the library cannot be checked, and the track waits and tries again. On a brand-new library the folder is made.

### Tracks whose files have gone leave the library, but never on a share that looks unmounted

The library is looked over on its own: new and changed files are analysed, and tracks whose files were renamed or deleted on the NAS leave search with their listening copies, so every track in search can be sent to Resolve. Nothing is removed when no files were found at all ("a share that is not mounted, not an empty library. Nothing pruned."), or when more than 5 tracks and more than a fifth of the library would go. Up to 20 removed names are listed.

- On its own: which tracks have gone, from the files present in the library's folder.
- By hand: when a removal was held back because it was too large, an admin sees the tracks that would go and can confirm the removal.

### A file name can never reach outside the library or run anything

Every dropped file name is cut to its last part on both "/" and "\" before use, so no drop can name a place outside the library folder. A file asked for by any web page is followed through any link and refused when it lies outside the library, however the library was found. File names are never interpreted as commands anywhere.

#### Lessons

- Met: MUS-053, MUS-054, MUS-055.
