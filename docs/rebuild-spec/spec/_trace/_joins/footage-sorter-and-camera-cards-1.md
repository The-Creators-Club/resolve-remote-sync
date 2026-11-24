# Joins aimed at footage-sorter-and-camera-cards-1

## Checked

- J1 | F1, F2, F3
- J2 | F4
- J3 | F5, F6
- J4 | fine
- J5 | fine
- J6 | F7, F8, F9, F10, F11, F12, F13
- J7 | F14, F15

## Findings

### F1: Shared-work rules hold card copies back; this piece says a card copy starts at once and several run side by side
- Kind: contradiction
- From: fleet-jobs / A computer does one piece of shared work at a time
- Here: Copying a card / There is one card copy, and it starts at once on the computer the card is in
- From says: "A computer is never given a second piece of shared work while it is doing one."
- Here says: "It starts at once, whether or not someone is using that computer, with no wait for the computer to be free." and "Copies from different cards to different places run at the same time."
- Settled by: SRT-053 (ruling): "A card or drive copy asked for from any browser starts right away on the computer holding the card, whether or not someone is using it."; SRT-071 (given) for several cards at once
- Fix: fleet-jobs should exempt card copies, drive copies and drive reads from the one-piece-per-computer rule, the studio-wide "at most at once" limits (4 card copies, 2 drive copies) and the holds its "start now" keeps (syncing stopped, update waiting, already doing shared work), or say they are not shared work at all.

### F2: An editor can untick "Copy camera cards", "Copy drives" or "Read drives", or switch fleet use off, and card copies stop; this piece has no such switch
- Kind: contradiction
- From: fleet-jobs / An editor decides whether their computer takes shared work and which kinds
- Here: nowhere (the per-computer switches here are "Watch for cards and drives on this computer" and "Field backup on this computer")
- From says: "An unticked kind is never given to this computer"
- Here says: "Who: anyone signed in, and the editor at the computer the card is in, even with no network."
- Settled by: SRT-053 (ruling): "A card or drive copy asked for from any browser starts right away on the computer holding the card"; OWNER_REQUIREMENTS: "One way to do each thing: one way of telling a computer something, one place a setting comes from"
- Fix: fleet-jobs should take the three Footage Sorter kinds out of the per-computer kind ticks and out of "Let the fleet use this computer", leaving part 1's two switches as the only per-computer controls over card work.

### F3: Card copies are started through the admin-only "start now"; here anyone signed in starts one and it is recorded as theirs
- Kind: contradiction
- From: fleet-jobs / An admin can start waiting work now, on a chosen computer
- Here: Copying a card / There is one card copy, and it starts at once on the computer the card is in
- From says: "It records "Your admin asked this computer to run this job now, without waiting for you to step away." The Footage Sorter starts its card and drive copies this way, because a person is waiting at the card."
- Here says: "It is recorded as started by the person who started it." and "Who: anyone signed in, and the editor at the computer the card is in, even with no network."
- Settled by: decision 19.5, answered 2026-11-24 with the recommendation: "A, a card copy only adds and never overwrites, while drive copies reach any drive in the studio." (card copies open to anyone signed in)
- Fix: fleet-jobs should drop the sentence routing card and drive copies through an admin's "start now" and its message, and say a card copy is started by whoever asked (anyone signed in, or the editor offline in field backup).

### F4: Fleet-jobs points here for "the server makes no media while a card is copied to the NAS", and this piece says nothing about it
- Kind: missing
- From: fleet-jobs / The server makes no media while a card is being copied to the NAS
- Here: nowhere (Drives, speed and interruptions has no such rule)
- From says: "the work waits until the copy is done, so the copy is not slowed. See The Footage Sorter and camera cards: Drives, speed and interruptions."
- Here says: nothing
- Settled by: JOB-002 (given, weaker than a ruling): "Proxy making that reads from the NAS does not run, or yields, while a camera-card offload to the NAS is in progress."
- Fix: either fleet-jobs drops the pointer (its own text is complete), or part 1's "Card copies are as fast as a dedicated card-copying program" gains one line that media-making on the NAS waits while a card copy to the NAS runs, pointing back to fleet-jobs.

### F5: The field backup page names a "check by the copier" as one way copies are verified; this piece has one quick check by default and a full check when asked
- Kind: contradiction
- From: footage-sorter-and-camera-cards-2 / A laptop in the field knows what is safe without reaching the studio
- Here: Checking a copy / What makes a copy count as checked
- From says: "how copies are verified, on hovering: a check by the copier after every file, or "every file read back in full and compared";"
- Here says: "The check is quick by default: the same size, identical first and last 1 MiB, and, for camera video, the clip's index"
- Settled by: SRT-064 (ruling): "Every copy is checked by size, identical first and last 1 MiB and the movie index; a full read-back runs only when asked, and the check says it is quick."; decision 19.1 (only the product's own copying, no outside copier)
- Fix: part 2 should change the hover text to the quick check (size, first and last MiB, the clip's index) or "every byte" when a full check was asked for that copy.

### F6: On a laptop a NAS copy counts wherever it is by name, size and time; here it must also have been checked against the card's file
- Kind: contradiction
- From: footage-sorter-and-camera-cards-2 / A laptop in the field knows what is safe without reaching the studio
- Here: Backed up and safe to format / Which copies count, and when a file is backed up
- From says: "a copy on the NAS counts wherever it is, since footage there is moved into project folders."
- Here says: "when a copy matching its name, size and recorded time is anywhere on the NAS and has been checked against the card's file, unless that copy is recorded as coming from another card."
- Settled by: SRT-041 (situation, weaker than a ruling): "A copy proves a card file safe only when it is tied to that card; two cards' look-alike files never vouch for each other."
- Fix: part 2 should say a NAS copy counts wherever it is only once it is tied to this card (checked against this card's file, never recorded from another card), as part 1 does.

### F7: Part 3 has its own Studio time zone setting, a fixed offset with no summer time and a different default
- Kind: contradiction
- From: footage-sorter-and-camera-cards-3 / The Sorter's settings
- Here: Clocks and file dates / The studio has one time zone, used for every time that carries none of its own
- From says: "as a fixed offset with no daylight saving. Default: the site's own time zone, set when the part is switched on."
- Here says: "A zone that is named (rather than a fixed offset) follows its own summer time." and "Default: UTC+8."
- Settled by: decision 19.4, answered 2026-11-24 with the recommendation: "A: one named studio time zone that everything follows."
- Fix: part 3 should drop its own Studio time zone setting and point to part 1's, and part 1 should reconcile its "UTC+8" default with its own line that the NAS's zone is used when none has been set.

### F8: Part 3 brings camera proxies with every card copy by default; here they come only when "Back up proxies too" is ticked, unticked by default
- Kind: contradiction
- From: footage-sorter-and-camera-cards-3 / The Sorter's settings
- Here: Copying a card / Camera proxies come off a card only when asked
- From says: "Setting: Bring the camera's proxies with a card copy. Does: whether a card copy also copies the proxies the camera wrote, into a folder named "proxy" beside the footage. Default: on."
- Here says: "A copy offers "Back up proxies too", unticked by default."
- Settled by: SRT-050 (ruling): "The copy offers "Back up proxies too", unticked by default, and proxies and their descriptive files are copied only when it is ticked at Copy."
- Fix: part 3 should remove the site setting and point to part 1's per-copy tick (and part 1's Proxy folder inside the dated folder).

### F9: Part 3 has a setting that lets an unverified card copy count as done; here a copy with an unchecked file is never Done
- Kind: contradiction
- From: footage-sorter-and-camera-cards-3 / The Sorter's settings
- Here: Checking a copy / How a card copy ends, and what the person is told
- From says: "Setting: Count an unverified card copy as done. Does: whether a card copy that could not be checked may still count as finished. Default: off."
- Here says: "A copy with any unchecked file is never Done."
- Settled by: decision 19.1, answered 2026-11-24 with the recommendation: "no "copied but nobody checked it" outcome."
- Fix: part 3 should remove the setting.

### F10: Part 3 lets a card copy skip a file whose name is taken; here the card's file is always written beside it
- Kind: contradiction
- From: footage-sorter-and-camera-cards-3 / The Sorter's settings
- Here: Copying a card / The Sorter decides clip by clip whether a card clip needs copying
- From says: "keep both (the incoming one is renamed) or skip the incoming file. Default: keep both."
- Here says: "left exactly as it is; the card's file is written beside it"
- Settled by: decision 19.15, answered 2026-11-24 with the recommendation: "A: always write beside ("name (2)"), never overwrite, never skip a same-size different file."
- Fix: part 3 should remove the "Same name, different file" setting.

### F11: Part 3 says a card copy does not start without 256 MB left free; here only that place is refused and the others carry on
- Kind: contradiction
- From: footage-sorter-and-camera-cards-3 / The Sorter's settings
- Here: Drives, speed and interruptions / Room and path length are checked before anything moves
- From says: "A card copy does not start unless it leaves at least 256 MB free on the drive it copies to."
- Here says: "If what needs copying there, plus 256 MiB kept spare, is more than its free space, that place is refused before anything moves" and "The other places carry on."
- Settled by: the owner must say: when one of several places a card is being copied to has too little room, does the copy still go ahead to the other places?
- Fix: part 3 should drop its sentence and point to part 1's rule (per place, 256 MiB spare), unless the owner rules otherwise.

### F12: Part 3 fetches "the crew's list of cards" every 15 minutes; here the card-use page is part of the Sorter and nothing is fetched
- Kind: contradiction
- From: footage-sorter-and-camera-cards-3 / The Sorter's settings
- Here: Backed up and safe to format / The crew record which cards they used on which day
- From says: "the crew's list of cards every 15 minutes."
- Here says: "On their phones, during a shoot, the crew record which of the studio's camera cards they used on which day, on a card-use page that installs to the home screen on iOS and Android and opens as an app."
- Settled by: decision 19.12, answered 2026-11-24 with the recommendation: "A: the card-use page is part of the Footage Sorter (installs on phones, works offline, no access key, no fetching)."
- Fix: part 3 should drop the 15-minute read of the crew's list of cards.

### F13: Part 3 says only an admin changes the Sorter's settings; here several per-computer card settings are the editor's for their own computer
- Kind: contradiction
- From: footage-sorter-and-camera-cards-3 / The Sorter's settings
- Here: Copying a card / An editor adds and removes folders as places to copy to (also the settings "Watch for cards and drives on this computer", "Field backup on this computer", "Field backup folder", "Rest field drives during long copies")
- From says: "Every setting of the Sorter is on the Sorter's settings, besides the folders above, and only an admin changes them, except card names."
- Here says: "Setting: Places to copy cards to on this computer. Does: the folders on this computer offered as places a card can be copied to. Default: none. Who: the editor for their own computer, and an admin."
- Settled by: decision 19.18, answered 2026-11-24 with the recommendation: one list of folders "whether added on the page or in the computer's settings" (the page being the editor's field backup); decision 19.17 (a per-computer switch to leave a computer out of card watching)
- Fix: part 3 should say only the site-wide Sorter settings are admin-only, and that the per-computer settings in part 1 are also changed by the editor for their own computer.

### F14: Part 3 says cards show "as they happen" with a 2-second reconnect; here a visible page checks every 5 seconds and a card appears within about 10
- Kind: differs
- From: footage-sorter-and-camera-cards-3 / New footage appears on its own once it has finished arriving
- Here: Recognising cards and drives / Every card put in a reader appears within seconds, with no click; The person is told when a card arrives, is ready, fails, is removed, and when its copy ends
- From says: "Cards arriving in a reader, leaving it, and copying show in every open Sorter page as they happen; if the page loses its connection it is back within about 2 seconds."
- Here says: "appears in the Footage Sorter within about 10 seconds" and "While a Sorter page is visible it checks the list of cards about every 5 seconds"
- Settled by: SRT-060 (ruling) for copy progress: "refreshed every few seconds while visible, never in a hidden tab"; for arrival, the owner must say: how soon after a card goes in must every open Sorter page show it?
- Fix: part 3 should replace "as they happen" and the reconnect figure with a pointer to part 1's timings for cards.

### F15: Part 3 always shows the card the app opened the Sorter for; here a tab already showing another card keeps it and offers Go
- Kind: contradiction
- From: footage-sorter-and-camera-cards-3 / New footage appears on its own once it has finished arriving
- Here: Recognising cards and drives / When a card goes in, the Footage Sorter comes up on it
- From says: "A card that the app on the editor's computer opens the Sorter for is shown straight away in that page, in the card's own view."
- Here says: "If that tab is already showing another card's view, that view stays, and "Card <drive> detected" with Go is shown instead."
- Settled by: the owner must say: when a new card goes in while the Sorter is already showing another card, should the page switch to the new card or stay and offer Go?
- Fix: part 3 should add part 1's exception (or point to it), unless the owner rules that the page always switches.
