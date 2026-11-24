# Decision list, page 16: The b-roll archive

Stays behind: never shown to the session that rebuilds the product.

28 questions. Each has what exists today, the options, my recommendation and what you would notice. The specification is already written to the recommendation (or, where I recommend cutting something, still holds it, ready to delete). **Reply with the numbers you disagree with; anything you do not mention is taken as the recommendation.**

## Choices

### 16.1 Should new b-roll be described on whichever of the studio's computers is able and free, starting with the computer it was dropped from?

- **Today:** dropped clips are always previewed and described on the computer of the person who dropped them, as you ruled; a computer without a big enough graphics card cannot take the drop at all and the editor is told to "take over from another computer" by hand. Your requirements for this build say heavy work is shared across the studio's computers.
- **Options:** A: the dropper's own computer does the work, always (your earlier ruling). B: the work is done on a computer of the studio's that is able and free, the dropper's own first when it can, otherwise another, with progress shown on the page, on the computer doing it and on the dashboard.
- **Recommended:** B, because it is the same one rule every other kind of heavy work follows and a laptop without a graphics card can still drop footage.
- **What you would notice:** with B an editor on a small laptop drops footage and it gets described anyway, somewhere else in the studio; with A they must carry it to a bigger computer.
- (broll-Q1)

### 16.2 Should the paid option of having the assistant describe b-roll clips stay, now that describing on the studio's own graphics cards is judged good enough?

- **Today:** clips can be described for free on a graphics card, or by the assistant over the internet, paid per clip, with model choice, a key, a cost report and a forecast.
- **Options:** A: keep both, the studio's own graphics cards by default. B: describe only on the studio's own graphics cards and remove the paid option.
- **Recommended:** B, because you judged the free describing good enough and it removes keys, billing, limits and a cost report.
- **What you would notice:** with B nobody can spend money on describing and a studio without any graphics card cannot describe b-roll (search by speech still works).
- (broll-Q2)

### 16.3 How should a clip's subject category be decided?

- **Today:** three things exist: the assistant can propose a category list for a person to approve, hand-written keyword rules decide each clip's category, and the describing also suggests a category that is shown but decides nothing. One part of the product matches categories by meaning, another by shared words; nobody could tell which is in use.
- **Options:** A: the studio's category list with the words that point to each category decides, as written; no proposal by the assistant and no suggestion shown. B: keep all three. C: let the describing choose from the studio's list by meaning, in any language, with the list's words only as a fallback.
- **Recommended:** A, because one rule a person can read and edit decides, and a categorised clip never moves anyway.
- **What you would notice:** with A an admin edits the list and its words and nothing else proposes categories; with C clips in other languages may file better without new words.
- (broll-Q3)

### 16.4 Before a computer downloads the several gigabytes describing needs, should someone be asked?

- **Today:** the computer starts the download by itself and shows a notification; the person dropping clips is asked only when they run a drop from the page.
- **Options:** A: the person running a drop is asked, as written; work picked up as shared work downloads with a notification only. B: nothing ever downloads without someone saying yes on the page.
- **Recommended:** A, because the person who starts the work is asked and shared work must not wait for a click.
- **What you would notice:** with B an editor's computer can sit idle with clips waiting until someone confirms.
- (broll-Q4)

### 16.5 Should camera raw (Blackmagic RAW, RED, Canon Cinema RAW Light) be accepted into the b-roll archive?

- **Today:** dropped footage refuses raw, because it cannot be decoded without Resolve; another list of accepted kinds includes raw; a heavy raw original sent to Resolve arrives as its preview only; own shoots in raw enter as their proxies.
- **Options:** A: refuse raw in a drop, as written; raw shoots enter the archive as their own proxies. B: accept raw, which needs a way to decode it outside Resolve.
- **Recommended:** A, because raw shoots already enter as their high-quality proxies and nothing new is needed.
- **What you would notice:** with B an editor could drop a card of raw clips straight in.
- (broll-Q5)

### 16.6 Should one "keep this much free" setting on each computer cover everything the product writes there?

- **Today:** several floors guard the same drive: proxies made (20 GB and 5%), b-roll drops (20 GB), downloads (20 GB), and music drops a second, smaller floor of 2 GB; free space is also checked at four moments with different rules, so a computer can say it can take a drop and then refuse it.
- **Options:** A: one floor per computer, checked by one rule (what is about to be written, plus the floor) every time. B: keep a floor per kind of work.
- **Recommended:** A, because one number is easier to understand and a computer can no longer say yes and then no.
- **What you would notice:** an editor sets one number on their computer instead of several.
- (broll-Q6)

### 16.7 Should one "only when I am away" choice cover all background work on a computer?

- **Today:** making proxies, b-roll describing and shared work each have their own "wait for 5 minutes of quiet" and their own "hold back while Resolve is open", and proxies do not hold back while Resolve is open while the other two do.
- **Options:** A: one quiet time and one Resolve hold-back per computer, the ones shared work already has, used by describing too. B: keep a setting per kind of work.
- **Recommended:** A, because a person thinks of "my computer while I am away", not of three separate waits.
- **What you would notice:** one setting to change instead of three.
- (broll-Q7)

### 16.8 Should search keep its three ways (words, words plus related meaning, meaning only) and the fuzzy tick, or be one search that does the right thing?

- **Today:** Hybrid, Keyword and Semantic, plus a fuzzy tick and a what-to-search choice; Hybrid already contains Keyword, and meaning search may not even run on the studio's server.
- **Options:** A: keep all three ways and the fuzzy tick, as written. B: one search: word matches first, up to 5 related clips by meaning after them, misspellings forgiven when the words find little; keep only the what-to-search choice.
- **Recommended:** B, because it gives the same results with two fewer controls.
- **What you would notice:** with B there is no way to search by meaning alone or to turn forgiving off.
- (broll-Q8)

### 16.9 Should the way of searching, what to search and the hidden flags be kept in a shared or reloaded search?

- **Today:** they are lost on reload and are not in a link someone shares, while the words, folder and open clip are.
- **Options:** A: keep them in the address too. B: leave them out, as written.
- **Recommended:** A, because a shared link should show the same results to the person it is sent to.
- **What you would notice:** with A a shared link opens exactly the same search.
- (broll-Q10)

### 16.10 Should every signed-in editor be able to change, revoke and delete every client folder, whoever made it?

- **Today:** yes; who made a folder is shown but grants nothing.
- **Options:** A: keep that. B: only the maker or an admin may change, revoke or delete.
- **Recommended:** A, because folders are the studio's, and a link must be revocable by whoever is around when a client should lose it.
- **What you would notice:** with B an editor could not withdraw a colleague's link.
- (broll-Q14)

### 16.11 When the app on the editor's computer cannot be reached, where should the message send them to get it?

- **Today:** the message ends "Downloads are in Settings.", which points at nothing on that page.
- **Options:** A: a link to the page where an editor installs the app on their computer. B: no pointer.
- **Recommended:** A.
- **What you would notice:** an editor without the app is taken straight to it.
- (broll-Q15)

### 16.12 Should a running drop's "done" count count only clips that were indexed?

- **Today:** "<done> of <n> indexed" also counts failed, duplicate, cancelled and skipped clips.
- **Options:** A: "done" counts only clips indexed, and the line shows failed, duplicate and skipped beside it. B: keep it.
- **Recommended:** A, because "indexed" should mean indexed.
- **What you would notice:** the numbers on the line add up the way they read.
- (broll-Q16)

### 16.13 When a clip's file is gone from the archive, should it drop out of search on its own?

- **Today:** a file deleted stays in search until someone removes it by hand.
- **Options:** A: hidden from search while its file is gone and back when it returns, never while the archive cannot be read at all; nothing forgotten. B: stays until removed by hand.
- **Recommended:** A, because a result that cannot be played or sent is worse than none.
- **What you would notice:** no dead results.
- (broll-Q20)

### 16.14 Should an editor be warned that a render made on their computer while a clip is a stand-in renders the low-resolution preview?

- **Today:** only a log says so.
- **Options:** A: the editor's app says it, beside its count of clips cut on stand-ins, and before a render if it can tell. B: say nothing.
- **Recommended:** A, because a 1080p preview in a 6K render is a delivery mistake.
- **What you would notice:** an editor knows before delivering.
- (broll-Q21)

### 16.15 Should fetching a missing clip when sending to Resolve be its own choice, rather than switched off by pointing the archive at another folder?

- **Today:** an editor who points the archive at a folder of their own silently switches off fetching missing clips.
- **Options:** A: fetching follows where the archive is on that computer, as written, and the message says why nothing was fetched. B: fetching is a separate on/off setting on the computer.
- **Recommended:** A with the reason said, because a folder of one's own is a copy the product does not keep in step, and one setting fewer.
- **What you would notice:** with B an editor could have clips fetched into a folder of their own.
- (broll-Q22)

### 16.16 Should the computer's file chooser for b-roll close by itself after five minutes on a Mac too?

- **Today:** on Windows a chooser left open for 5 minutes is closed as if cancelled; on macOS it stays on screen and whatever is then chosen is thrown away.
- **Options:** A: closes on both. B: stays open on both and the page keeps waiting.
- **Recommended:** A, because a choice that is silently thrown away is the worst outcome.
- **What you would notice:** on a Mac the chooser goes away instead of losing a choice.
- (broll-Q28)

## Tidy-ups

One thing that can be done from several places, the same job existing twice, things switched off for everyone, things nobody can reach, and tools only the builders use.

| # | Question | Today | Recommended |
|---|---|---|---|
| 16.17 | Should the subject be chosen from the folder tree only, or also from a separate category list beside the search box? | the place being browsed is set from the folder tree, from a category list that repeats the tree's Downloads half, and from the folders and category in an open clip's path, each clearing the others. | B, because the list repeats the tree exactly. (broll-Q9) |
| 16.18 | Should the state of the app on this computer be shown in one place on the b-roll page, and is the list of collection descriptions wanted? | whether the app on this computer is reachable is checked in two places, the collections panel and the add-footage panel; the collections panel's list of descriptions is information only. | B, because the status matters only when adding footage or sending, and a send already says when the app cannot be reached. (broll-Q11) |
| 16.19 | Should a drop's failures be tried again from one place? | three ways: "retry" per row and "retry all failed" for files that did not reach the computer, and "try the N failed again" for a finished drop. | B, because a person sees a failed clip either way and should not need to know which step it failed in. (broll-Q12) |
| 16.20 | Should speech in dropped footage be transcribed? | "Transcribe speech" is shown when adding footage but is always disabled ("not available yet"), and the server refuses it, while footage reaching the archive another way is transcribed. | A, because search by what is said is the quickest way to find a clip and works before describing finishes. (broll-Q13) |
| 16.21 | May the builders' tools for b-roll go from the product? | the archive can be run on its own with no sign-in at all; there is a search-quality check against a private set of test searches (through the real search or straight on the index); a way to measure a candidate describer against existing descriptions; and a blind judging page for scoring describers. | A, because no editor or client uses them. (broll-Q17) |
| 16.22 | Should transcription always follow a collection's "no transcription" setting and its longest-clip cap? | one way of transcribing honours them; the bulk transcription that actually runs ignores both. | A, because a setting that is ignored is worse than none. (broll-Q18) |
| 16.23 | Should an admin be able to have the archive's previews checked and remade where one will not play? | three one-off repairs exist for previews made under earlier rules (not playable in a browser, timecode wrong, hover strip layout missing); a timecode correction is then undone by the next archive build. | B, because previews are made right and checked before they count, and the archive carried over is repaired once in the carry-over. (broll-Q19) |
| 16.24 | Should each problem reach an admin exactly once, in one wording? | every serious standing problem the server finds is also mailed, and several also have a mailed alert of their own, so the same problem arrives twice in different words: refused sharing changes, refused project removals, the server's syncing not answering, the unreadable b-roll archive, fields the dashboard cannot store, broken facts, failing background work. | A. (broll-Q23) |
| 16.25 | May the fallback that takes the studio's own project folder as its own footage, for a site that never set the list, go? | a site whose settings never mention own footage gets one studio's own project folder as its own footage; a blank list and a missing one behave differently. | A. (broll-Q24) |
| 16.26 | From which places should a b-roll drop be paused, resumed, started now and cancelled? | from the drop on the b-roll page, from the app on the computer doing the work, and from the dashboard. | A, because an admin needs to stop a drop on someone else's computer and the person at the computer needs it without a browser. (broll-Q25) |
| 16.27 | Should one fetch of a single missing file serve b-roll clips, music tracks and downloaded YouTube originals alike? | sending a b-roll clip, sending a music track and bringing a downloaded YouTube original to the editor's computer all fetch one file from the NAS the same way. | A. (broll-Q26) |
| 16.28 | Where is the b-roll describing quality chosen? | an admin's site setting, the indexing computer's own setting, a per-computer override, and a choice per run or per drop. | A, because a computer that cannot hold a level is never given it anyway. (broll-Q27) |

## Your answers

ANSWERED 2026-11-24. After answering pages 2 and 3 and most of page 4 one
by one, he said of everything still waiting: "accept all the
recommendations." So every question on this page is answered with its
recommendation.
