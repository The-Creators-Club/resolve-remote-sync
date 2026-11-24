# Joins aimed at music

## Checked

- J1 | F1, F2
- J2 | F3, F4
- J3 | fine
- J4 | F5
- J5 | F6, F7, F8
- J6 | fine
- J7 | F9, F10

## Findings

### F1: The one-file fetch waits differently when the computer is busy: broll caps it at two and gives up after 15 minutes, music waits for one other download with no limit
- Kind: contradiction
- From: broll / A clip not on this computer yet is fetched first, with progress, and then placed
- Here: Sending to Resolve / A track the editor's computer does not have yet is fetched from the NAS when sent
- From says: "A computer downloads at most two clips at once for an editor who is waiting. A third reads \"not sent yet: ...\" ... after 15 minutes it gives up with \"This computer has been busy with other downloads for a while. Try again when they have finished.\""
- Here says: "it reads the app's own message or \"waiting for this computer’s other download to finish, then sending…\", and carries on when that is done."
- Settled by: BRO-113 (kind situation, weaker): "\"Busy\" is a wait starting \"not sent yet\", never success in any open page version; the page retries at the suggested pace for 15 minutes, and queued work starts when a slot frees."
- Fix: music should say the music page waits on the same shared fetch with its two-at-once limit and gives up after 15 minutes with broll's sentence (worded for a track), instead of waiting without limit for a single other download.

### F2: The same one-file fetch is described in full in both pieces, and they already differ on what an editor with a folder of their own is told
- Kind: said twice
- From: broll / A clip not on this computer yet is fetched first, with progress, and then placed
- Here: Sending to Resolve / A track the editor's computer does not have yet is fetched from the NAS when sent
- From says: "an editor who points the archive at a folder of their own is told \"nothing was fetched: the archive on this computer is in a folder of your own, which CC Sync does not fill\" with \"file not found at <path> - is the share mounted?\""
- Here says: "A computer set to sync nothing, or whose music folder was set to another place by hand, does not fetch: there, and when the file is still not there after copying, the answer is \"file not found at <path> - is the share mounted?\"."
- Settled by: OWNER_REQUIREMENTS.md section 1: "One way to do each thing"
- Fix: music should keep only its own page wording (the "track isn’t on this computer yet" and "syncing the track" lines) and point to broll's one-file fetch for who fetches, the limits and every refusal, including the "folder of your own" sentence.

### F3: Broll's one free-space floor covers dropped music, but music says a drop is never refused for space
- Kind: contradiction
- From: broll / A drop holds at most 2,000 clips and is taken only if it fits
- Here: Adding tracks to the library / Dropping audio anywhere on the music page adds it to the library
- From says: "Setting: Keep this much space free. Does: the one floor of free space on this computer that nothing CC Sync writes there (dropped b-roll and music, proxies, downloads) ever eats into."
- Here says: "A drop is never refused for lack of free space on the person's own computer."
- Settled by: MUS-008, withdrawn in knowledge-base/_cross/TAKEN_OUT.txt (weaker, not a ruling): "a free-space minimum for a drop existed because drops were staged on the person's computer; the specification refuses no drop for space"
- Fix: broll should drop "dropped ... music" from the floor setting's text, since music writes nothing of a drop to the person's computer.

### F4: Broll's staging clean-up counts music drops held on the computer, but music never says a drop keeps files on the computer
- Kind: missing
- From: broll / Dropped files are cleaned away a week after they are no longer needed
- Here: nowhere
- From says: "When the b-roll archive is off: the button and the line count music drops only."
- Here says: nothing (music reads a dropped file where the person has it: "A dropped file that has gone from the person's computer before it was taken in fails with \"the source file is no longer on this computer ...\"")
- Settled by: MUS-008, withdrawn in knowledge-base/_cross/TAKEN_OUT.txt (weaker, not a ruling): "drops were staged on the person's computer; the specification refuses no drop for space"
- Fix: broll should make "CLEAR FINISHED STAGING" and its line about b-roll drops only, and say that with the b-roll archive off there is no staging button or line.

### F5: The music progress window on the editor's computer is described in full both here and in the editor app
- Kind: said twice
- From: editor-app / Long background work has a progress window the editor can close and reopen
- Here: Imports across computers / An editor sees music analysis on their computer while it is doing it
- From says: "PAUSE, RESUME, START NOW and CANCEL, each enabled only when it can act ... when the work finishes (every item done or failed) it closes itself 4 seconds later."
- Here says: "It opens once when work starts (and stays closed if the editor closes it), and shows the download headline ... Its buttons are Cancel, Pause or Resume, and Start now (only while waiting for the editor to be away or for Resolve to close)."
- Settled by: OWNER_REQUIREMENTS.md section 1: "One way to do each thing"
- Fix: music should keep only the window's music wording (heading "INDEXING MUSIC", its second line, the music notices) and point to editor-app for how the window opens, closes, updates and which buttons it has.

### F6: Music pauses its analysis the moment the person comes back; shared work finishes what it is running
- Kind: contradiction
- From: fleet-jobs / The kinds of shared work and what each needs (read with "Work already running is finished when the person comes back")
- Here: Adding tracks to the library / A person chooses whether their drop is analysed now or while they are away
- From says: "When someone starts using the keyboard or mouse, or opens Resolve, the computer takes no new shared work, but finishes the piece it is running. A long piece of work is never killed because its person came back."
- Here says: "pausing the moment they come back (they lose at most the step in progress)"; also "Indexing music… D of T (stops when you're back)" and "The memory it takes is given back as soon as the person returns to the computer."
- Settled by: JOB-003 (kind situation, weaker): "no new job starts while someone is present, and a long job already running is not killed when they return."
- Fix: music should say that when the person comes back the track in progress is finished and no further track is started, instead of pausing at once and losing the step in progress.

### F7: A track whose analysis fails is tried twice in fleet-jobs, never retried in music
- Kind: contradiction
- From: fleet-jobs / The kinds of shared work and what each needs (read with "A computer takes shared work only while nobody is using it")
- Here: Adding tracks to the library / A track that cannot be read or analysed fails with a plain reason
- From says: "A clip or track whose analysis fails is tried twice in all, then left as failed until a person asks again"
- Here says: "A failed track shows as failed with its reason and is not retried on its own." and "Nothing retries these on their own: fix the file and drop it again."
- Settled by: the owner must say: when a music track cannot be analysed, does the product try it once more by itself before showing it as failed, or show it as failed at once?
- Fix: whichever he chooses, both pieces should say the same number of tries for a music track.

### F8: Music fixes "away" at 5 minutes with Resolve closed; fleet-jobs makes both the computer's own settings
- Kind: contradiction
- From: fleet-jobs / The kinds of shared work and what each needs (read with "A computer takes shared work only while nobody is using it")
- Here: Adding tracks to the library / A person chooses whether their drop is analysed now or while they are away
- From says: "Setting: Quiet time before shared work. ... Default: 5 minutes." and "Setting: Hold shared work back while Resolve is open. ... Default: on."
- Here says: "\"Only when idle\" means only while they have been away from keyboard and mouse for at least 5 minutes and Resolve is closed"
- Settled by: OWNER_REQUIREMENTS.md section 1: "one place a setting comes from"
- Fix: music should say "Only when idle" waits for the computer's quiet time and its Resolve hold-back as set in Work shared out across the computers, rather than a fixed 5 minutes and Resolve always closed.

### F9: A placed track a frame out is re-laid once by the Resolve promise, but music takes it out and reports failure
- Kind: contradiction
- From: resolve-on-the-editors-computer / What Resolve does with multicams, timelines and frame rates
- Here: Sending to Resolve / A placed track lands at the playhead in the timeline that is open, or not at all
- From says: "Every clip the product places in Resolve is read back and laid again once if it is a frame out."
- Here says: "If the track did not land exactly at the playhead it is taken out again: \"placement failed on A<n> at frame X - something already occupies that span, or the track is locked\"."
- Settled by: RSV-109 (kind given, weaker): "Every clip placed in Resolve by script is read back and re-laid once if it is off by a frame."
- Fix: music should say a track that lands one frame out is laid again once, and only a track still not at the playhead after that is taken out with the "placement failed" sentence.

### F10: Music measures a track's length in its own frame count; Resolve counts an audio clip's frames in the clip's own rate, which must be converted
- Kind: contradiction
- From: resolve-on-the-editors-computer / What Resolve does with multicams, timelines and frame rates
- Here: Sending to Resolve / A placed track lands at the playhead in the timeline that is open, or not at all
- From says: "Placing audio-only clips converts frames using the clip's own rate, and the timeline's length is checked afterwards."
- Here says: "The track's length is its frame count, else its duration at the timeline's frame rate, else one second." (and an insert moves later clips "by exactly the track's length")
- Settled by: RSV-112 (kind given, weaker): "Placing audio-only clips into a timeline converts frames using the clip's own rate and checks the timeline's length afterwards."
- Fix: music should say the track's length on the timeline is its frame count converted from the clip's own rate to the timeline's, so a ripple insert moves later clips by the track's true length on that timeline.
