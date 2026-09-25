# ui-music-ytdl-web - Wave 3 UI hunt of the music search/player UI and the YouTube downloader UI (music/web/static, ytdl/web/static)
Files read (approximate coverage): music/web/static/index.html (all), app.js (all), ingest.js (all), style.css (all); ytdl/web/static/index.html (all), style.css (~85%), app.js (~45%: helpers, health, projects, attach/poll, review grid, runSearch/runUrls/startDownload, recent, history, reveal, attestation, init). Prior hunters' music.md / ytdl-web.md titles for 09-03, 09-11, 09-11b, 09-18, 09-18b checked for duplicates.
Tests/probes run: copied each app's static tree to the scratchpad, stubbed `fetch` with canned API answers, and rendered the real index.html + style.css + app.js in headless Edge (screenshots + a DOM measuring script) at phone and desktop widths. Em-dash grep over both static trees (only hit: an HTML comment, exempt). No repo file other than this report was written.

## Findings

### ui-music-ytdl-web-1 - The YouTube page has no phone layout: its search row is 365 px wider than the screen
- Severity: medium
- Confidence: CONFIRMED
- Where: ytdl/web/static/style.css:391 (`.search-bar`, no wrap) and the whole file (no `@media` rule anywhere); markup ytdl/web/static/index.html:81-119
- What: `.search-bar` is a non-wrapping flex row holding `#q`, `#project` (up to 320 px), `#quality`, the "on this computer" switch, `#period` and `#maxcand`. None of those can shrink below their content, and the stylesheet has no media query at all (music has two at 900 px), so on a narrow screen the row just runs off the right edge. The shot-type row, the SEARCH IN scope row and the review grid get pulled wider with it.
- Failure scenario: an editor opens /ytdl/ on a phone. Headless Edge measures `scrollWidth=847` against a viewport of 482 (the narrowest it would render). The quality picker, the switch, the date filter, the candidate cap and GET LINKS all sit past the right edge, so the page scrolls sideways. The screenshot also shows "Raw / uncut / no commen..." and "[ MY TER..." cut off, and review cards wider than the screen.
- Evidence: scratchpad render. Measured bounding boxes: `#quality L412-480`, `#locallabel L488-602`, `#period L610-711`, `#maxcand L719-847` against a 482 px client width.
- Ledger: new
- Suggested fix: let `.search-bar` wrap (`flex-wrap: wrap`) and add a `@media (max-width: 600px)` block that stacks the pickers and gives `#q` / `#urls` the full width, as music's 900 px block does for its rail.

### ui-music-ytdl-web-2 - Clicking a clip's title to watch it on YouTube also ticks or unticks it for download
- Severity: medium
- Confidence: CONFIRMED
- Where: ytdl/web/static/app.js:2011-2023 (`card()`)
- What: the title is an `<a target="_blank">` inside the card, and the card's `onclick` toggles selection. The checkbox calls `stopPropagation`, but the link does not. So a click on the title opens YouTube and also bubbles up to the card, which posts `select`.
- Failure scenario: an editor reviewing 74 clips clicks each promising title to preview it in a new tab. Every preview flips that clip's selection. Clips they wanted come back unticked (`DOWNLOAD N` drops), and the ones they previewed and rejected by clicking the box get re-ticked. The only sign is the checkbox in a tab they have just left.
- Evidence: code read. `a.href = v.url; a.target = '_blank'` with no handler of its own, and `n.onclick = () => { if (!v.duplicate) toggle(v, !v.selected); }`.
- Ledger: new
- Suggested fix: `a.onclick = e => e.stopPropagation();`.

### ui-music-ytdl-web-3 - The rights-attestation lock on SEARCH / GET LINKS is undone by the project loader and by every submit
- Severity: medium
- Confidence: CONFIRMED
- Where: ytdl/web/static/app.js:3098-3108 (`setAttested`), 752-753 (`loadProjects`), 2222 and 2293 (`finally` in runSearch/runUrls)
- What: `init` awaits `loadAttestation()`, which disables `#go` / `#golinks` for an editor who has not accepted. `loadProjects()` runs next and sets both back to `disabled = false` whenever any project exists. The reverse happens too: accepting re-enables them even when `loadProjects` had disabled them for "no projects ticked". The `finally` blocks re-enable them after every submit. On top of that, `setAttested(true)` restores `el.dataset.title || el.title`, but `dataset.title` is never set. So after accepting, the tooltip still says "Accept the download terms at the top of this page first", and GET LINKS loses its own tooltip until a reload.
- Failure scenario: a new editor has not accepted yet and sees the notice with SEARCH lit. They type a topic and press it, and the server refuses with a 403 toast, even though the page's own gate was supposed to prevent that. An editor with no projects ticked who accepts gets SEARCH enabled over "you are not syncing any project".
- Evidence: code read of the init order (loadAttestation, then loadHealth, then probe, then loadProjects) and of the three unconditional writes.
- Ledger: new
- Suggested fix: compute `disabled` in one place from `!state.attested || !state.hasProjects || state.submitting`, and save the original title in `data-title` at init.

### ui-music-ytdl-web-4 - The music player pane is a fixed 150 px box that cuts off its own buttons and messages
- Severity: medium
- Confidence: CONFIRMED
- Where: music/web/static/style.css:752 (`.pane.open { height: 150px }`, `.pane { overflow: hidden }`); content built in music/web/static/app.js:206-281
- What: the height animation uses a fixed height, and the comment assumes the content "is fixed anyway". It is not. The five action buttons wrap on narrow screens, and two more lines can appear under the waveform: the no-waveform caption (every fleet-ingested track) and the Resolve status/error line (up to about 200 characters). Anything past 150 px is clipped with no scroll.
- Failure scenario: rendered with a fleet track (peaks 404) after pressing "import to bin" with no tray running, the inner content is 161 px at a 1246 px desktop width and 237 px on the phone layout. On desktop the error line that explains why Resolve did not answer is cut off. On a phone the `reveal` / `similar` buttons and the whole message are hidden.
- Evidence: scratchpad render, measuring `.paneinner.scrollHeight` against the 150 px pane.
- Ledger: new
- Suggested fix: animate `max-height` (for example 0 to 400 px) or `grid-template-rows: 0fr` to `1fr` instead of a fixed height, or set the height from `inner.scrollHeight` after each message change.

### ui-music-ytdl-web-5 - Changing any rail filter, the sort, or pressing "[ include them ]" silently throws away the typed search while the box still shows it
- Severity: medium
- Confidence: CONFIRMED
- Where: music/web/static/app.js:694-700 (axis `onchange`), 906 (sort), 910-913 (include-unknown), 927-931 (apply range), 623 (the `[ include them ]` button that `noteUnknownHidden` adds after a SEARCH)
- What: MUSIC-4 made the rail's filters travel with a text search (`filterFields()` goes into `api/search`). But every rail control, once changed, calls `loadTracks()`, the browse route, and never `runSearch`. `#q` keeps the description (only `selectFacet` clears it). `runSearch` itself draws the `[ include them ]` button, and clicking it replaces the search results with an unranked browse list.
- Failure scenario: an editor searches "tense driving synth pulse", sees "3 tracks have no BPM ... [ include them ]" and clicks it. They get the whole library sorted by filename, with no match scores, under a headline of "All tracks", while the search box still reads "tense driving synth pulse". The same happens after setting BPM 90-130 and pressing apply. It reads as "the search is broken".
- Evidence: code read. There is no `$('#q').value` check on any of these paths.
- Ledger: related to MUSIC-4 (2026-09-04, fixed in the other direction only)
- Suggested fix: route these handlers through one `refresh()` that calls `runSearch($('#q').value)` when the box is non-empty and `loadTracks()` otherwise. Also hide the sort control, or state that it does not apply, while a search is showing.

### ui-music-ytdl-web-6 - A length filter that matches nothing says "The library is empty"
- Severity: low
- Confidence: CONFIRMED
- Where: music/web/static/app.js:547-564 (`loadTracks` headline `bits`)
- What: the headline and the empty-state choice are built from facet, axis and BPM only. `dur_min` / `dur_max` (and include-unknown) never go into `bits`. So a length-only filter reports "All tracks", and when it matches nothing it picks the no-filters sentence.
- Failure scenario: Secs min 900, apply. The result head reads "All tracks 0 tracks" and the list says "The library is empty. Drop some music in to get started." on a 397-track library.
- Evidence: code read.
- Ledger: new
- Suggested fix: push a `${min||0}-${max||'∞'} s` bit for `state.dur`, the same as BPM.

### ui-music-ytdl-web-7 - One failed stats or facets call at load kills the whole music page, with a raw status line
- Severity: low
- Confidence: CONFIRMED
- Where: music/web/static/app.js:873-946 (`init`)
- What: `init` awaits `api/stats` and `api/facets` before it wires SEARCH, clear, ADD MUSIC, sort, the dropzone and the first `loadTracks`. If either one throws (an expired session 401, a locked DB 500, a restart blip), the catch writes `Failed to load: api/stats -> 401` into the list. Nothing is wired, and the `failureText()` wording written for exactly this (MUSIC-2) is not used.
- Failure scenario: an editor returns to a tab after the session expired and reloads. They get a dead page whose only text is `Failed to load: api/stats -> 401`: SEARCH and ADD MUSIC do nothing, and nothing says "sign in again".
- Evidence: code read.
- Ledger: related to MUSIC-2
- Suggested fix: wire the handlers first, treat stats and facets as best-effort (as `refreshLibrary` already does), and render the failure through `failureText('Loading the library', e)`.

### ui-music-ytdl-web-8 - Music's sticky header is taller than the `--header-h` the filter rail parks under, and on a phone it takes a third of the screen
- Severity: low
- Confidence: CONFIRMED (measured with the fallback topbar; the injected dashboard topbar is at least as tall)
- Where: music/web/static/style.css:32 (`--header-h: 134px`), 400-414 (`.filter-rail` sticky at `top: var(--header-h)`), 138 (`#app-header` sticky)
- What: the rail's offset is a constant, but the header's height depends on how its rows wrap. It measured 150 px at 1246 px wide, so while scrolling the top 16 px of the rail (padding and the FEEL heading) sit under the header. Below 900 px the header stays sticky and grows to 263 px: search, buttons, the Resolve chip, stats and eight example prompts all wrap.
- Failure scenario: on a 390x844 phone, roughly a third of the screen is a frozen header and the track list scrolls in the rest. On desktop the "Feel" heading is half hidden once the page scrolls.
- Evidence: scratchpad render, `#app-header` getBoundingClientRect height 150 px (1246 wide) and 263 px (482 wide).
- Ledger: new
- Suggested fix: make `#app-header` `position: static` inside the 900 px media query, and set `--header-h` from JS (a ResizeObserver on `#app-header`) or drop the sticky rail offset.

### ui-music-ytdl-web-9 - After a music batch finishes, the panel still says "Running" and offers Run again on the same staged tracks
- Severity: low
- Confidence: CONFIRMED
- Where: music/web/static/ingest.js:994-1054 (`miRenderLive`), 910-921 (`miRenderSummary`), 928 (`miRun` never clears `mi.items`)
- What: when the server reports a terminal state, `mi.running` goes false. The `#mi-live` section (heading "Running") stays up with all controls disabled, because `mi.batchUid` is never cleared. The staged track list is never cleared either and is still ticked, so the Run button re-enables over tracks that are already in the library.
- Failure scenario: an editor's 20-track batch reaches "all done". The panel shows a "Running" heading over "all done", and below it the same 20 tracks with an active Run button. Pressing it mints a second batch of the same files (the server may only then flag them duplicate), and the editor cannot tell whether the first run counted.
- Evidence: code read. The only path that empties `mi.items` is the clear button.
- Ledger: new
- Suggested fix: on the transition to terminal (`miNoteBatchState`), clear the staged items (or mark them "done") and retitle the live section, for example "Last batch".

### ui-music-ytdl-web-10 - YouTube's Recent searches list prints the raw phase enum that the progress strip translates
- Severity: low
- Confidence: CONFIRMED
- Where: ytdl/web/static/app.js:2791 (`el('span', 'ph', j.phase)`) vs `PHASE_LABEL` at 32-44
- What: the progress strip shows "pick the search terms" / "ready for review" / "asking claude for search terms". The Recent searches row for the same job shows `terms_review`, `ready_for_review` or `generating_terms`. These are two vocabularies for one state on one screen, and the underscored one is the database's.
- Failure scenario: the Recent row reads `2026-09-23 09:10 ready_for_review ...` directly under a strip saying "READY FOR REVIEW", and a parked `terms_review` job reads as an internal error code.
- Evidence: code read and the scratchpad render (visible in the idle screenshot).
- Ledger: new
- Suggested fix: `PHASE_LABEL[j.phase] || j.phase`.

## Coverage note
ytdl app.js was read at about 45%. Not read closely: renderProgress / renderDownloads / renderRetry, the term review, the queue/waiting panels, the local-download dispatch and progress lines, and runFetch. Their visible states (a downloading job, a failed job with RETRY, a queued job) were not rendered, because the stub only covered the idle and ready_for_review shapes. The real `/partials/topbar` was not injected (the fallback header was used), so the header heights above are a lower bound. Keyboard/ARIA was looked at only in passing: the ytdl review cards and the music track rows are click-only divs whose checkbox or buttons are the keyboard route, which works. The music ingest panel does not move focus into itself on open, which is minor.

## OUT OF TERRITORY
- none
