# The pipeline before the editor: from recorded interview to transcript, translation and word timing

Terms used throughout:

- **Episode root**: one folder in the notes vault for one shoot, for example `X:\Vault\2026\FF5\Energy Transition`. It must contain a folder named `Interviewees`, which holds one subfolder per interviewee (the **interviewee folder**). A `Script Docs` folder beside `Interviewees` holds episode-level files.
- **Notes vault**: the folder tree the studio keeps its transcripts and canvases in (it is opened in Obsidian, but nothing in this part needs Obsidian running; every stage reads and writes plain files).
- **Multicam**: a DaVinci Resolve media-pool clip of type "Multicam" that groups one interview's camera angles and sound. Its name is normally `<Person> Multicam`; the **stem** is that name with a trailing "Multicam" removed.
- **Pool name**: the clip's exact name in Resolve's media pool. Every word-timing file is named after it, and later readers find it only by that name.
- **Project library**: the database Resolve keeps its projects in (PostgreSQL on a server, or a local SQLite "Disk" library). Several stages read it directly, with no Resolve program running.
- **Whisper**: the faster-whisper speech-to-text engine, run locally on this machine's graphics card (GPU), falling back to the processor (CPU).
- **Word sidecar**: a `<clip>_words.json` file holding one entry per spoken word with its start and end time. This is what Timeline Cards times a cut with.
- **`^ref` / block ref**: a line `^xxxx` (4 to 10 lowercase letters or digits) under a paragraph in a transcript `.md`, giving that paragraph a permanent address.
- **OpenCC pass**: converting Simplified Chinese (which whisper writes) to Traditional Taiwanese Chinese, phrase by phrase (`s2twp`), then replacing every `臺` with the house-style `台`.

## The one command line: `pipeline.py` (source: pipeline.py)

- Run as `py -3.12 pipeline.py <command> [args]`. With no argument, or `-h`, `--help` or `help`, it prints its own description followed by every command, grouped under four headings, with a one-line description each; exit status 0.
- Each command runs one module exactly as `python -m <module>` would: same arguments, same `--help`, same exit status. It adds the repo folder to the module search path first, so it works from any current folder.
- Hyphens and underscores in a command name are interchangeable (`build_canvas` equals `build-canvas`).
- An unknown command prints `pipeline.py: no such command: <name>` and the full command list to the error stream; exit status 2.
- A command may carry fixed arguments of its own: `update-project` is `diff-project` with `--update` added in front of the user's arguments.
- The two web servers are not commands here: `pipeline_web.py` (the stage page, port 8799) and `reorder_web.py` (Timeline Cards, port 8800, another section).
- The full command list, in the order printed:
  - Heading "transcripts":
    - `multicam-transcripts`: "stage 1 - export Resolve's own transcription as .md + .srt". Described below.
    - `resolve-multicam-whisper`: "stage 2 - render each multicam's audio and whisper it". Described below.
    - `preview-video`: "a small 480p mp4 beside each interview WAV, in sync with it (ffmpeg, no Resolve)". Described below.
    - `fold-mono`: "one-sided stereo WAVs -> true mono (stage 2 does this itself)". Described below.
    - `whisper-transcripts`: "stage 1b - adopt stage 2's whisper as the transcript (.md + .srt)". Described below.
    - `check-multicam-transcripts`: "stage 3 - which multicams are still truncated". Described below.
    - `check-transcript-coverage`: "stage 4 - Resolve vs whisper, interval by interval". Described below.
    - `finalize-transcript`: "stage 5 - add a unique ^block ref to every block". Described below.
    - `extract-paragraphs`: "stage 6 - transcripts -> the paragraphs .jsonl pool". Described below.
    - `assist-links`: "last stage - phrase alignment + word links for Timeline Cards (Claude)". Described below (it forwards to another section's code).
    - `first-question`: "where the crew asks the interviewee to introduce themselves". Described below.
    - `resplit-draft`: "re-split a prepped draft into blocks". Described below.
    - `search-transcripts`: "list / grep / show / render for the search skills". Described below.
    - `transcribe`: "montage builder phase 1 - whisper a folder of clips into a corpus". Described below.
    - `translate-corpus`: "English above the Mandarin for every corpus transcript (local qwen)". Described below.
    - `refresh-cuts`: "repair cut lists' clip names + rates from the corpus sidecars". Another section's code (`cards`).
    - `repair-words`: "repair word sidecars whose tokens were converted one at a time". Described below.
  - Heading "canvas" (all another section's code): `build-canvas` (stage 9, the deterministic canvas build), `add-to-canvas` (add a later interview to a canvas already in use), `regroup-canvas` (carve a new theme out of a canvas in use), `reorder-canvas` (slide whole groups along the row), `resequence-canvas` (write a re-sequenced copy from a card-level plan), `story-flow-extract` (flatten an ordered canvas and pool for the story-flow read), `interviewee-colors` (one colour per interviewee, on the canvas and in Resolve), `canvas-timeline` (stage 10, an ordered canvas becomes a Resolve timeline), `canvas-to-cutlist` (an ordered canvas becomes a `.cut.md` cut list, no Resolve), `make-lite-audio` (the small Opus copy of every interview's WAV), `recolour-sections` (default colour rotation for a cut list's sections), `conform-project` (a `.cut.md` becomes a Resolve timeline, dry run unless `--apply`), `diff-project` (how a `.cut.md` and its timeline differ), `update-project` (rewrite the `.cut.md` from that timeline, dry unless `--apply`).
  - Heading "resolve" (another section's code): `resolve-ui` (drive Resolve's user interface for what the scripting interface will not do), `multicam-ui` (make a multicam clip from a bin), `sync-angles` (audio-sync a multicam's angles), `build-angle-timelines` (one timeline per angle from the clips on disk), `interview-angles` (plan and build one interview's angle timelines, audio-synced), `zoom-into-angles` (put the Zoom recorder on audio track 1 of existing angle timelines), `resync-angles` (slip each angle's picture onto its audio track 1, in place), `wait-for-selection` (watch for the stage 8 selection file).
  - Heading "library" (another section's code): `library-reader` (read a timeline out of the project library, no Resolve), `library-writer` (write a conformed timeline into the library), `library-edits` (move, trim, split, delete, insert in place).

## Top-level launcher scripts (source: check_transcript_coverage.py, extract_paragraphs.py, finalize_transcript.py, search_transcripts.py)

- Four scripts in the repo root exist only so that Claude "skills" stored outside the repo (canvas-sorter, project-search, transcript-search) can keep running them by absolute path. Each one adds the repo folder to the module search path and runs the matching module under `multicam_pipeline.transcripts`, with the same arguments, help and exit status. None has behaviour of its own.
  - `check_transcript_coverage.py` runs the stage 4 coverage check.
  - `extract_paragraphs.py` runs stage 6.
  - `finalize_transcript.py` runs stage 5.
  - `search_transcripts.py` runs the search helper.

## The stage page: `pipeline_web.py` (source: pipeline_web.py)

### Starting it

- Command: `pipeline_web.py [port] [--no-browser]`. Port defaults to 8799.
- Listens on 127.0.0.1 only (this machine). There is no sign-in and no access check of any kind: anything on this machine can call every route.
- Prints `Transcript Pipeline -> http://127.0.0.1:<port>/` and, unless `--no-browser`, opens the page in the default browser 0.6 seconds after start.
- At start it checks that nine stage modules can be found and prints `WARNING: missing backend module: <name>` for each one that cannot; it starts anyway.
- It needs the shared theme file `webtheme.py` from the sibling `Editing\Launcher` folder (it puts that folder first on the search path, so the Launcher copy is the one used, not the identical copy in this repo). It also imports the interviewee-colours module (another section) at start; if either is missing the server does not start.
- Every stage it runs is a child Python process (`python -m <module>`, working folder = the repo), with output captured into a job log. No console window flashes on Windows.

### Where every path comes from

- The person types an episode root. Everything else is derived from it:
  - The folder must exist, else `not a directory: <path>`.
  - It must contain `Interviewees`; if the person typed the `Interviewees` folder itself, its parent is taken as the root. Otherwise `no 'Interviewees' folder inside <path>`.
  - Surrounding spaces and double quotes on the typed path are removed.
- **Several episodes from one shoot**: if `<root>\Script Docs\episodes.json` exists, it lists episode names (either a bare list or `{"episodes": [...]}`); each episode then gets its own paragraph pool, proposal, assignments and canvas off the shared transcripts. A broken file gives `bad <path>: <reason>`; an empty list or a non-text entry gives `<path> must hold a non-empty list of episode names`. With no file, the episode is named after the root folder.
- An unknown or blank episode name silently falls back to the first episode.
- Derived paths (all outside the episode root except the canvas):
  - Shoot-wide paragraph pool: `E:\Projects\Editing\Transcripts\canvas-theme-picker\work\<root folder name>_paragraphs.jsonl` (the folder is located relative to this repo: two levels up, then `Transcripts\canvas-theme-picker`).
  - This episode's paragraph pool: `...\work\<episode>_paragraphs.jsonl`.
  - Category proposal: `...\canvas-theme-picker\proposals\<episode>.json`.
  - Category assignments: `...\work\<episode>_assignments.json`.
  - Canvas: `<root>\Script Docs\<episode> Canvas (Claude).canvas`.

### The page itself (route `/`)

- Title "Transcript Pipeline". Dark theme with a blue accent (from `webtheme.py`).
- **Top panel**:
  - A text box, placeholder `Project root, e.g. X:\Vault\2026\FF5\Energy Transition`.
  - **Scan** button: reads the folder and draws everything below. Remembers the typed root in the browser's local storage (`tp_root`) and, per root, the last episode (`tp_ep_<root>`). On an error, shows the error in red in place of the path list.
  - **Check Resolve** button: appends "checking Resolve…" under the paths, then either `Resolve: <error>` in red or `Resolve <project> · bin <bin name> · <n> multicams`.
  - A path list: "Episode" (a dropdown when the root has several episodes, with "`<n>` episodes share these transcripts"; plain text otherwise), "Interviewees" (folder path) and "Canvas" (canvas path). Choosing another episode in the dropdown rescans for it.
  - A people list, one line per interviewee folder (folders named `archive`, `script docs` or `_archive`, in any letter case, are skipped): a colour swatch (the interviewee's assigned colour, with a tooltip `<hex> — Resolve <clip colour>`, or a dashed empty swatch with tooltip "no colour assigned yet"), the name, then three pills that turn green when true: `srt` (a Resolve `.srt` other than a `.whisper.srt` is in the folder), `whisper` (a `.whisper.srt` is there), `prepped` followed by the number of `^ref` blocks (a `.md` in the folder carries at least one `^ref` line).
- On load, the page fetches the model list; if a root was remembered it scans it at once; it also starts watching the job (so a run started earlier shows up).
- **Stage list** (shown after a scan). Each row has a round marker (its number, or a green tick when the row counts as done), a title, a description, a bold status, and a **Run** button. Rows that use Claude also have a model dropdown. Rows, in order:
  1. **Export Resolve transcripts**: ".md + .srt per interviewee, straight from the project database". Status `<n> of <m> have an .srt`. Done when every interviewee has one (and there is at least one).
  - (unnumbered, marked with a palette icon) **Multicam colours**: "give each multicam the colour its interviewee's cards get on the canvas — runs automatically at the start of Reference". Status `<n> assigned` or `none yet`; done when any colour is assigned. Two buttons: **Dry run** and **Set**. (The colour logic is another section's code.)
  2. **Reference audio + whisper**: "render each multicam, transcribe locally as a second opinion". Status `<n> of <m> have a reference` (counts interviewees with a `.whisper.srt`).
  3. **Preview video**: "a small 480p mp4 beside each WAV, cut from the camera file (ffmpeg, no Resolve) — made automatically after the audio render; this does only the missing ones". Status `<n> of <m> have a preview` (a file ending ` Preview.mp4`).
  4. **Word timings**: "whisper words (<clip>_words.json) for every interview WAV that has none - from the WAV on disk, no Resolve; runs at the start of Prep too". Status `<n> of <m> have word timings`.
  5. **Swap 24-bit audio in, re-transcribe in Resolve**: "MANUAL — drag each <clip>.wav onto its multicam audio Angle 1 (32-bit drops to Angle 2), Clear Transcription, Transcribe, swap back. Run to see which clips still need it." Status always "checks every multicam transcript against its full length"; never shown as done.
  6. **Verify coverage**: "diff the two - catches sections Resolve silently dropped". Status always "run after both of the above"; never shown as done.
  7. **Prep transcripts**: "paragraphs, question marking, translation, block refs". Status `<n> of <m> prepped`. Done when no interviewee has only raw `.md` files. Model dropdown, default Sonnet 5.
  8. **Extract paragraphs**: "deterministic - no model". Status `<n> paragraphs` (non-blank lines in this episode's pool) or "not extracted".
  9. **Propose categories**: "read everything, name up to 15 overarching containers". Status `<n> proposed, <k> selected` or "none yet". Model dropdown, default Fable 5.
  10. **Sort + build canvas**: "place every paragraph, then build the canvas with a script". Status "canvas built", "assignments ready" or "not run". Model dropdown, default Fable 5.
  11. **Language assist for Timeline Cards**: "phrase alignment + word links + gloss for every prepped transcript (Claude) — runs automatically after Prep; re-running only does what is new". Status `<n> clips aligned` (number of `.json` files in `<root>\Script Docs\Cuts\.tcards\@align`) or "not run".
  - **Rebuild canvas only** (marker ↻, shown only when the assignments file exists): "re-run the script over existing assignments — no model, seconds". Run button.
  - **Conform timeline (Resolve)** (marker 10, shown only when `Script Docs` holds at least one `.canvas` file): "cut a hand-ordered canvas into a timeline of multicam cuts — needs the episode's project open in Resolve", plus "— using conform.map.json" when `Script Docs\conform.map.json` exists. A dropdown of canvases (newest first, any name containing `.bak` excluded; the last choice per episode is remembered in local storage `tp_canvas_<episode>`), a **Dry run** button and a **Build** button. (Another section's code.)
- Model dropdowns offer four models: "Fable 5 (best judgment, slow/priciest)" (`claude-fable-5`), "Opus 4.8" (`claude-opus-4-8`), "Sonnet 5 (good default)" (`claude-sonnet-5`), "Haiku 4.5 (fast, rough)" (`claude-haiku-4-5-20251001`). Each dropdown remembers its choice in local storage (`tp_prep`, `tp_propose`, `tp_sort`).
- **Job panel** (appears once a job has run): the job label, a line `<status> · started <time> · <end time>`, a live progress bar with `<label> — <pct>%  <note>` when the running stage prints progress lines, and the job log (up to the last 800 lines, monospace, up to 320 px tall; it stays scrolled to the bottom if it was within 30 px of the bottom). While a job runs, the page asks for its state every 1.2 seconds; when it finishes, the page rescans the root.
- **Category selection area** (shown when the proposal file exists and has themes):
  - Heading "Categories", a counter `<ticked> / <target>` (target from the proposal's `target_count`, default 12), a **+ Custom category** button and a **Save & sort paragraphs** button, and the note "Tick what to keep, rename freely, add your own. Saving runs the sort with the Sort model below, then builds the canvas with a script."
  - One card per proposed theme: a tick in the corner, the name in an editable text box (pre-filled with any earlier rename), the description, and the evidence line. Clicking anywhere on the card except the text box toggles it on or off. Cards already in the proposal's `selected` list start ticked.
  - **+ Custom category** adds a ticked card named `Custom <n>` (first free number) with a dashed border, a description text area ("What belongs here? This is what paragraphs are matched against."), an × button that removes the card, and evidence "custom category"; it scrolls into view and its name is selected for typing.
  - **Save & sort paragraphs** sends the ticked cards (original name, new name or the original if blank, and for custom cards the description) with the Sort model.
- Errors from a Run, Set, Build or Save button appear in a browser alert box.
- The Export, Reference and Preview stages accept a dry-run flag on the server, but the page never sends one for them. `UNREACHABLE` from the page; only a hand-made request can ask for it.
- The server accepts a `bin` value for Colours, Reference and Swap check, but the page never sends one, so they always use the bin currently open in Resolve. The server also accepts `whisper_model` for Reference (default `large-v3`), which the page never sends.

### Routes

- `GET /` or `/index.html`: the page.
- `GET /api/models`: the four-model list as JSON.
- `GET /api/job`: the current job: `status` (`idle`, `running`, `done`, `error`), `stage`, `label`, `log`, `started`, `ended`, and `progress` (`label`, `pct`, `note`) while one is showing.
- `GET /api/resolve`: asks Resolve which project and bin are open. It first checks, from the machine's network table, that Resolve's scripting server is ready to accept a client; if not it answers `{"error": "DaVinci Resolve is not accepting scripting connections yet"}`. Otherwise it connects and answers `{project, bin, multicams: [names of multicam clips in the current bin]}`. Run in a child process with a 90-second limit; any failure answers `{"error": <first 200 characters>}`. Always status 200.
- `GET /api/scan?dir=<root>&ep=<episode>`: the derived paths plus per-interviewee state (`raw`, `prepped`, `blocks`, `srt`, `wav`, `whisper`, `preview`, `words`) and the counts the page shows, the list of canvases, whether `conform.map.json` exists, and each interviewee's colour. Any error answers 400 with `{"error": ...}`.
- `GET /api/proposal?dir=&ep=`: the proposal file's raw text. A missing file answers 400 with the error.
- `POST /api/run` with JSON `{root, episode, stage, model?, dry?, bin?, canvas?, whisper_model?}`: starts one stage as the single background job. Refusals: an unknown stage answers 400 `unknown stage '<x>'`; a job already running answers 409 `a run is already in progress`; a bad root answers 400. Answers `{"ok": true}` once started.
- `POST /api/select` with `{root, episode, selected: [...], model?}`: saves the category choice into the proposal file and, if a model was given, starts the Sort stage. Refuses an empty or non-list selection with `nothing selected` (400). A custom category not yet in the proposal is added to its themes with evidence "custom category (added by hand)"; an existing custom one gets its description updated. Writes `selected`, `selected_at` (local time), and, only if absent, `paragraphs_jsonl` and `output_canvas`. The file is written whole through a temporary file and swapped in. If another job is already running the sort is silently not started and the answer says `"sort_started": false`.
- Any other path answers 404 `not found`.

### The job runner

- Exactly one job at a time, held in memory; a restart of the server forgets it. There is no cancel button and no route that stops a job.
- A job ends `done` when its stage returns, or `error` with `ERROR: <message>` logged when it raises. A child process that exits non-zero raises `<what> failed (exit <n>)`.
- Child Python processes run unbuffered so the log is live. Any output line of the form `PROGRESS <label> <n>% <note>` becomes the progress bar instead of a log line.
- Claude runs are the `claude` command-line program, found through the `CLAUDE_BIN` environment variable or the PATH (a `.cmd` or `.bat` is run through `cmd /c`); if not found the job fails with `claude CLI not found on PATH (set CLAUDE_BIN)`. It is run headless with the prompt, the chosen model, streaming JSON output and `--dangerously-skip-permissions` (Claude may run any tool without asking), in the repo folder. The log shows Claude's text, each tool use as `  > <tool> - <description>`, and the final result after `- result -`.

### What each Run button does

- **Export**: runs stage 1 (`multicam-transcripts --out <Interviewees>`). Fails the job if it exits non-zero.
- **Multicam colours, Dry run / Set**: runs the interviewee-colours module on the root (with `--apply` for Set). Another section's code. Needs Resolve open.
- **Reference**: first runs the colours step for real (or as a dry run when the dry flag is set); if that fails it logs `WARNING: could not set the multicam colours -- carrying on with the render.` and continues. Then runs stage 2 (`resolve-multicam-whisper --out <Interviewees> --model large-v3 --delete-timelines`).
- **Preview video**: runs `preview-video <Interviewees>`. Exit 2 logs `preview video: some clips got no preview - see above; the rest are done` and is not an error.
- **Word timings**: runs `resolve-multicam-whisper --from-library --root <root>` (no Resolve). The project library address comes from the environment or `deploy\site.toml`, because the page passes none.
- **Swap check**: runs stage 3 (`check-multicam-transcripts --out <Interviewees>`). A non-zero exit is not an error; it adds the line `Swap the flagged clips, re-transcribe in Resolve, then run this again.`
- **Verify coverage**: for every interviewee folder (skipping archive and Script Docs folders), for every `<x>.whisper.srt`, looks for `<x>.srt`. Missing: logs `<name> no Resolve .srt to check`. Otherwise logs `=== <name> ===` and runs stage 4 on the pair; a non-zero exit counts as flagged. Ends with `checked <n> interview(s), <k> with missing sections` and, when any were flagged, `Re-transcribe those in Resolve before prepping, or the gaps become holes in the canvas.` Never fails the job.
- **Prep**: first runs Word timings (above); a failure there fails the whole Prep. Then lists interviewees that have a raw `.md` and no prepped one; if none, logs `every interviewee already has a prepped transcript.` and stops (Language assist does NOT run in that case). Otherwise logs `prepping: <names>` and runs Claude with the PREP prompt (see "The three Claude prompts"), then runs Language assist.
- **Extract**: creates the `work` folder if needed and runs stage 6 on the root, always writing the shoot-wide pool (`<root name>_paragraphs.jsonl`), never the per-episode one.
- **Propose**: if this episode's pool is missing: on a several-episode root it fails with `<episode pool name> is missing. On a merged root, extract writes the shared pool (<pool name>); split it into per-episode pools before proposing.` (nothing in this part splits it); otherwise it runs Extract first. Then creates the `proposals` folder and runs Claude with the PROPOSE prompt.
- **Sort**: runs Claude with the ASSIGN prompt, then Rebuild canvas.
- **Rebuild canvas**: fails with `no assignments file - run Sort first` when the assignments file is missing; otherwise creates `Script Docs` if needed and runs the canvas builder (another section) on the pool, the assignments and the canvas path.
- **Conform timeline**: refuses with `pick a canvas file first` or `canvas not found: <path>`; otherwise runs the canvas-to-timeline module (another section), adding `--apply` unless Dry run. Needs the episode's project open in Resolve.
- **Language assist**: runs `assist-links <root>`. Exit 2 logs `assist links: stopped at the Claude call budget - run Language assist again to carry on` and is not an error.

### The three Claude prompts (sent by the page)

- **PREP**: asks Claude to invoke the "canvas-sorter" skill's PREP phase for the named interviewees: turn each raw transcript `.md` into `<stem>_Transcript.md` with semantic paragraphs, `#` question marking, English and Mandarin paired verbatim, and block refs added with `finalize_transcript.py`; never alter the wording in any language; then stop. The skill itself lives outside this repo (`~/.claude/skills/canvas-sorter`), so what PREP actually produces is decided there, not here.
- **PROPOSE**: asks for the skill's PROPOSE phase: read the paragraph pool and write a theme proposal to the proposal path, at most 25 themes, two of which are always "Personal Stories" and "Ending"; themes are broad containers, but one that would hold 80 or more paragraphs must be split; do not assign paragraphs.
- **ASSIGN**: asks for the skill's ASSIGN phase: write `{"themes": [{"name", "role": "personal|body|ending", "keys": [...]}]}` to the assignments path; every paragraph in exactly one group; "Uncategorised" only for non-content, under 10%; interviewer questions go with their answer, directly above it; body themes in story order; keys copied verbatim; do not run the canvas builder.

## Stage 1: export Resolve's own transcription (source: multicam_transcripts.py)

- **What it does**: for every multicam clip in one media-pool bin, reads the transcription Resolve already made (Resolve's own speech-to-text, run by a person in Resolve beforehand) and writes, per interviewee, a plain transcript `<stem>.md` and a subtitle file `<clip name>.srt`.
- **Needs from outside**:
  - DaVinci Resolve open, with external scripting allowed, and the episode's project open. It refuses to connect while Resolve's scripting server is not ready (`DaVinci Resolve is not accepting scripting connections yet (closed or starting up)`), and `could not connect to DaVinci Resolve -- is it running with Preferences > System > General > External scripting = Local?` if the connection fails. `no project is open in Resolve` if none.
  - Read access to the project library: PostgreSQL (needs the `psycopg2` library; default user `postgres`, password `DaVinci`, port 5432, 20-second connect limit) or a local Disk library (found under `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Resolve Project Library\...\Users\<any>\Projects\<project name>\Project.db`, opened read-only; `could not locate Project.db for disk database ...` if not found). Any other library type: `unsupported project database type`.
  - The `zstandard` library (the transcription is stored compressed).
  - The multicams must already have been transcribed inside Resolve by a person.
  - No GPU, no Claude, no notes app.
- **Which library**: asks Resolve; when Resolve answers nothing (as Resolve 21 does), reads Resolve's own log files (`%APPDATA%\...\Support\logs\davinci_resolve.log.1` then `davinci_resolve.log`) for the last "Current project pointer changed to (<project>) from project library (<name> : <Network|Disk>)" line for this project, and the host from a "postgres project library <name> at <address>" line (default 127.0.0.1). `--db-name` / `--db-host` override both. With nothing found: `could not work out which project library this project lives in ... -- pass --db-name / --db-host`.
- **Which clips**: the bin named by `--bin` (searched anywhere in the media pool; `bin '<x>' not found in the media pool`), else the bin open in Resolve. Only clips whose type is Multicam. `--only <text>` (repeatable) keeps clips whose name contains any given text, ignoring case. None left: `no multicam clips in bin '<name>'`.
- **Where each clip goes**: into `<--out>\<folder>`, where the folder is, in order: a `--map CLIP=FOLDER` override (matched on the stem or the full clip name, ignoring case; a `--map` without `=` is refused `--map expects CLIP=FOLDER`); an existing subfolder whose name equals the stem ignoring case; the best fuzzy match among existing subfolders (name split into word parts; score = shared parts over the stem's parts, or 0.75 per part that contains or is contained in another when nothing is shared exactly; accepted at 0.5 or more), which handles "Brian" to "Brian Hioe" and "Huang Chi-wen" to "Chih-Wen Huang"; else a new folder named after the stem.
- **Default output root**: `X:\Vault\2026\FF5\Energy Transition\Interviewees` (one specific episode) when `--out` is not given.
- **The `.md`**: the transcript text exactly as Resolve holds it, including Resolve's own `(...)` pause markers and paragraph breaks, with leading spaces trimmed from each line. UTF-8.
- **The `.srt`**: cues built from Resolve's word tokens. A cue ends at a paragraph break, at sentence-ending punctuation (Latin or Chinese, with trailing quotes or brackets), or before it would pass the line budget: 60 characters, or 20 when the language is Chinese, Japanese, Korean or Cantonese (decided by Resolve's language tag, else by more than 30% wide characters in the first 400 tokens). `--max-chars` overrides. `(...)` pause markers are left out. A cue whose end is not after its start gets a 1 ms length. Times carry the project's start timecode (normally 1 hour), as Resolve's own subtitle exports do. Windows line endings.
- **Skips and failures**, one log line per clip (`<clip> <words> words <cues> cues lang=<x> <m:ss> -> <folder> [exact|fuzzy(0.83)|override|new folder]`):
  - A clip with no transcription in the database: `no transcription in the project database (clip status: <Resolve's status or "not transcribed">)`, counted as failed.
  - A database error for one clip: `FAILED: <reason>`, counted as failed.
  - Missing folder: created (`created folder <name>`), unless `--no-create-folders`, which skips it with `skip -- folder <name> does not exist (enable 'create missing folders')`.
  - An existing file is skipped (`skip (exists) <file>`) unless `--overwrite`; the run ends with `(tick Overwrite to replace existing files)` when anything was skipped.
  - `--dry-run`: lists `would create folder` / `would write <file> (<n> bytes)` and writes nothing.
  - `--no-md` / `--no-srt` write only the other file.
- Ends with `done: <n> written, <k> skipped, <f> failed` (or `dry run: ...`). Exit status 1 if any clip failed, else 0; any other error prints `error: <message>` and exits.
- It reads blobs whether or not Resolve's speaker detection was on (it recognises the transcription by its shape).
- It also offers two functions with no caller in this part: a bin lister (every bin holding multicams, with counts, and which bin is open) and a preview scan that reports what would be written per clip without touching disk. The module's description says they back a `transcripts_web.py` page; no such file is in this part.

## Stage 2: render each multicam's audio and transcribe it with whisper (source: resolve_multicam_whisper.py, whisper_worker.py, mono_fold.py)

### Two ways to run it

- **Render mode** (default): needs Resolve open with the project; renders a WAV for each multicam, then transcribes.
- **Library mode** (`--from-library`, or `--from-facts <file>`): needs NO Resolve. Transcribes WAVs already on disk, taking each clip's identity, frame rate and start timecode from the project library. This is what the stage page's Word timings button and the start of Prep run.

### Render mode, step by step

- Connects to Resolve (same readiness check as stage 1; refusals end the run: `DaVinci Resolve is not accepting scripting connections yet (closed or starting up)`, `could not connect to DaVinci Resolve -- is it running with external scripting enabled?`, `no project is open in Resolve`).
- Picks the bin (`--bin` anywhere in the pool, else the open bin; `bin '<x>' not found in the media pool`), keeps only Multicam clips, applies `--only` filters (repeatable, case-insensitive "name contains"). None: `no multicam clips in bin '<name>'`.
- Destination per clip: `--out` (default `X:\Vault\2026\FF5\Energy Transition\Interviewees`), then the same folder matching as stage 1 (exact stem, else fuzzy at 0.5 or more, crediting both exact and partial parts, else a new folder named after the stem). `--flat` puts every clip directly in `--out`.
- `--dry-run`: prints each clip with its duration and destination and stops.
- Sets the project's render settings to the "Audio Only" preset if it exists, and the WAV format; refuses with `render format 'wav' not available. have: ...` if the project has no WAV format.
- For each clip:
  - If `<destination>\<clip name>.wav` already exists and `--overwrite` is not given: no render; logs `audio exists, skipping render (TC <timecode>)` and still transcribes it.
  - Otherwise: clears any in/out marks on the clip (a mark would silently shorten the render), creates or reuses a timeline named `<clip name> [xscript]` from the clip (logs `FAILED to create a timeline` on failure), makes it current, clears its marks, creates the folder, sets render settings (target folder, file name = clip name, all frames, audio only; `FAILED to set render settings` on failure), adds a render job (`FAILED to queue a render job` on failure) and logs `queued TC <timecode> -> <folder> [<how>]`.
- The start timecode stamped on everything is: `--offset` if given; else the clip's own Start TC; else the timeline's start; else the project's timeline start setting; else `01:00:00:00`. The frame rate recorded is the clip's own FPS, else the project's timeline rate.
- `--no-render`: leaves the jobs queued, prints `<n> job(s) queued. Render them in the Deliver page, then re-run.` and stops.
- Otherwise starts rendering and waits, checking every 2 seconds, then prints each job's status. With nothing to render: `nothing new to render.`
- **One-ear fix** (unless `--no-mono-fold`): every planned WAV that has all its sound in one channel is rewritten as a true one-channel WAV (details under "fold-mono" below). In this path the stereo original is NOT kept. Logs `folded <n> one-sided render(s) to true mono`.
- **Preview videos** (unless `--no-preview`): runs the preview maker on every WAV (see "Preview video"), using the project name to choose among same-named clips. Any failure there is logged as `preview videos skipped: <reason>` and never stops the run.
- **Re-import** (unless `--no-import`): imports every planned WAV not already in the bin (compared by file path) into the multicam's bin, then logs `imported <n> render(s) into bin '<bin>'` or `renders already in bin '<bin>'`, and always the instruction `-> drag each onto its multicam's audio Angle 1 (original drops to Angle 2), then run Resolve's transcription on the multicams.`
- `--delete-timelines` (the stage page always passes it): deletes every timeline in the project whose name ends ` [xscript]`, including any made by earlier runs. Logs `removed <n> scratch timeline(s)`.
- `--no-whisper`: stops here.
- WAVs not on disk are reported `no audio on disk - render may have failed`; if none exist: `no rendered audio to transcribe`.
- Then the whisper pass (below), then a reminder to run the coverage check.

### Library mode

- `--from-library` requires `--root` (`--from-library needs --root <episode root>`) and a project library host and database name (`no project library: give --db-host and --db-name (or set CARDS_DB_HOST / CARDS_DB_NAME)`).
- Library address defaults: `CARDS_DB_HOST` and `CARDS_DB_NAME` from the environment; else `[db] host` and `name` in the repo's `deploy\site.toml`. `--db-project` limits it to one project when the library holds several.
- Walks `<root>\Interviewees` (or the root itself if it has no `Interviewees`): every `.wav` directly in that folder and directly in each subfolder not starting with `.`, nothing deeper. Sorted.
- Each WAV's file name (without `.wav`) must be a clip name in the library; if not it is reported `not a clip name in the library - skipped` and never guessed. For known ones, it takes the clip's id, frame rate and start in seconds from the library (another section's reader) and computes the start timecode.
- `--facts-out <file>` writes that plan as JSON (time made, library host and name, root, rows) and carries on; `--from-facts <file>` reads such a plan and transcribes from it with no library and no Resolve (`cannot read the facts plan ...`, `<file> carries no rows`). This lets one Python (with the database driver) plan and another (with the GPU whisper) transcribe.
- `--dry-run`: prints per WAV its clip, rate, timecode, id, the two output paths, and `SKIP (<why>)` or `transcribe (<why>)`, plus unknown WAVs, and `<n> to transcribe, <k> unknown`.
- WAVs missing on disk: `no audio on disk - skipped`. Nothing left: `no audio to transcribe`.
- Folds one-sided WAVs already on disk (unless `--no-mono-fold`), WITHOUT keeping the stereo original, logging `folded <n> one-sided wav(s) to true mono`.
- Then the whisper pass. No previews, no import, no Resolve.

### The whisper pass (both modes)

- Loads faster-whisper with `--model` (default `large-v3`). First puts the CUDA libraries installed as Python packages on the Windows library search path. Tries the GPU with `--compute-type` (default `float16`; `int8_float16` is the documented choice when the card is shared with Resolve), proves it with a two-second silent test decode, and on any failure prints `GPU unavailable (<reason>)` and `falling back to CPU - this will be much slower` and uses the CPU with `int8`. `--cpu` skips the GPU entirely. Prints `running on cuda/float16` (or similar).
- **Skip rule** per WAV: skipped only when its `<clip>.whisper.srt` exists AND (when word timing is wanted) its word sidecar exists, has words, and still matches the WAV: same size and modification time (within 0.01 s), or failing that the same quick fingerprint (SHA-1 of the size plus the first and last MiB). Logs `srt + words exist, skipping (<why>)`. When only the `.srt` exists, logs `srt exists, re-transcribing for word timing (<why>)`. `--overwrite` forces it.
- **Language**: with no `--lang`, the default is per-chunk detection:
  - The audio is split into speech chunks at pauses of 0.5 s or more, each chunk at most 20 s.
  - Each chunk of at least 1 s is language-detected; a detection under 60% confidence decides nothing. An undecided chunk takes the language of the chunk before it (or the first decided one at the start of the file).
  - Consecutive chunks of one language form a run; chunks less than 3 s apart form one stretch inside a run.
  - **Island rule**: a run with less than 3 s of speech whose language differs from all its neighbours is absorbed into the run before it (or after it, at the start), repeatedly; each surviving run records how many chunks it absorbed.
  - Each language is then transcribed in its own pass over only its own stretches, with timestamps kept absolute, and the passes are merged by start time.
  - If detection cannot run or decides nothing, it prints `per-chunk language detection did not run (<reason>) - one detection per 30 s window instead` and falls back to whisper's own per-30-second detection; if the installed faster-whisper is too old for that, it prints `this faster-whisper cannot detect the language per segment (1.1 or newer can) - one detection for the whole file`.
  - `--lang <code>` forces one language for the whole file, with no detection at all.
  - The clip's recorded language is the one with the most spoken seconds (ties go to the first-detected language).
- Beam size 5. Voice activity filtering on in the fallback path.
- **OpenCC pass**: applied to each segment detected as Mandarin, or whose text contains any Chinese character, to both the cue text and that segment's words. The words are converted as one joined phrase and then split back per word, so phrase-level replacements match the segment text. Default conversion `s2twp`; `--opencc <conversion>` changes it; `--no-opencc` turns it off; `--no-tai` keeps OpenCC's `臺`. If OpenCC cannot be loaded, prints `opencc s2twp unavailable (<reason>) - output stays as whisper wrote it`.
- **Progress**: prints `PROGRESS <clip> (<i>/<n>) <pct>% <done>/<total> min <cues> cues <lang> eta <m>m<ss>s` at most every 3 seconds (the stage page shows it as a bar), and a 100% line at the end.
- **Writes** beside the WAV:
  - `<clip>.whisper.srt`: one numbered cue per non-empty segment, times plus the clip's start timecode, UTF-8, plain line endings.
  - `<clip>_words.json` (unless `--no-words`): the word sidecar (format under "Word sidecar format"), with every word and segment time shifted by the clip's start timecode, and `start_tc_sec` and `start_tc` recording the shift. Writing it requires the montage-builder module, which in turn needs the sibling `Resolve\MontagePipeline` folder; if that cannot be imported it prints `no word sidecar: <reason>` and writes only the `.srt`.
- Per clip it logs `<n> word(s) -> <file>` and `<cues> cues <min> min speech lang=<lang> [opencc=<conversion>] <seconds>s`; a mixed-language clip shows each language with its minutes and the number of runs, for example `en (en 27.1 min, zh 1.4 min, 3 runs)`.
- Render mode ends with: `Now diff each against Resolve's own export:` and the coverage command.

### Command-line flags of stage 2 (full list)

- `--bin`, `--out`, `--flat`, `--only` (repeatable), `--model` (default `large-v3`), `--lang`, `--cpu`, `--compute-type` (default `float16`), `--offset`, `--no-render`, `--no-whisper`, `--no-words`, `--no-mono-fold`, `--no-preview`, `--no-import`, `--delete-timelines`, `--overwrite`, `--dry-run`, `--from-library`, `--root`, `--db-host`, `--db-name`, `--db-project`, `--facts-out`, `--from-facts`, `--opencc` (default `s2twp`), `--no-opencc`, `--no-tai`. Each is described above.

## The whisper worker for the montage corpus (source: whisper_worker.py)

- A separate program run by `transcribe` (below), never by a person directly. Usage: `whisper_worker.py --out <result.json> [--files-from <list>] [-m model] [-l language] [--device] [--compute-type] [--beam-size] [--no-vad] [--opencc] [--tai] [--batched N] FILE...`.
- It loads one model once, then transcribes every file in turn. Defaults: model `large-v3-turbo`, device `cuda`, compute type `float16`, beam size 5, voice filtering on (pauses of 0.5 s), no OpenCC unless asked, sequential (not batched). There is no automatic CPU fallback here.
- `--files-from` takes a text file with one path per line (used when the list would be too long for a Windows command line). No files at all: `no media files: give paths, or --files-from <list>`.
- Language detection: the same per-chunk method as stage 2 by default; the per-30-second fallback when detection fails or when `--batched N` is used (batched mode never uses per-chunk detection); `-l` forces one language.
- Mandarin conversion is per segment as in stage 2, but here only segments detected as exactly `zh` or containing a Chinese character are converted.
- Reports progress on its error stream as one JSON object per line: `load` (model, device, compute type, seconds), `start` (path), `progress` (path, seconds done, duration, at most every 5 s), `done` (path, duration, seconds, language, languages, multilingual, detection, runs, words, real-time factor), `failed` (path, first 400 characters of the error), `warn` (reason).
- Writes the full result to `--out` as JSON: the run settings and, per file, path, duration, majority language, its confidence, seconds per language, whether per-window detection was used, the language runs, how detection was decided (`chunks`, `window`, `forced`), seconds taken, and the segments with their words (start, end, text, confidence). A file that fails gets an `error` entry and the others carry on.
- Exit status 1 only when every file failed; otherwise 0.

## The montage corpus: `transcribe` (source: whisper_corpus.py)

- **What it does**: transcribes every media file in one or more folders (for example downloaded news clips for a montage) and writes, for each, under the episode root: `<root>\Clips\<stem>\<stem>_words.json` (word sidecar) and `<root>\Clips\<stem>\<stem>_Transcript.md` (readable transcript with `^ref` blocks).
- Usage: `pipeline.py transcribe --folder <dir> [--folder <dir>...] --root <episode root> [flags]`. Both are required.
- **Needs from outside**: no Resolve. A GPU is expected (device `cuda` by default, no automatic CPU fallback in the worker; `--device cpu` must be given). A separate Python environment for whisper at `C:\Users\alex\tools\whisper\.venv\Scripts\python.exe` is used when it exists, else the current Python (`--python` overrides). The sibling folder `Resolve\MontagePipeline` must exist: its transcript writer is what formats the `.md` (this module will not even start without it). ffprobe on the PATH is optional (only the frame rate in the `.md` depends on it, default used otherwise). For `--speakers`, a second Python environment with pyannote and a Hugging Face token. No Claude, no notes app.
- **Which files**: every file under each folder, recursively, with extension `.mp4 .mov .mkv .m4v .webm .wav .m4a .mp3 .flac`; skipping subfolders named `proxy`, `proxies`, `.history`, `transcripts`, `clips` (any case) or starting with `.`, and any file whose name contains `.editready`, `.original`, `.part`, `.temp`, `.failed` or `.ytdl`. A folder that does not exist stops the run: `error: not a folder: <path>`, exit 2.
- A second file with the same stem in one run is skipped: `[skip] <stem> -- a clip of that stem is already in this run`.
- **Skip rule**: the same size-and-time-then-fingerprint rule as stage 2, against the existing sidecar. `--force` re-transcribes.
- Prints `<n> media file(s), <k> already transcribed, <m> to do`. `--dry-run` lists `[dry ] <stem>` for each one to do and stops.
- Runs one worker process for all files (file list passed in a temporary file when the command would pass about 24,000 characters). Its results go to a temporary folder that is deleted at the end. Log lines: `[load] <model> on <device>/<type> in <s>s`, `[<i>/<n>] <file name>`, `<done>s / <total>s`, `lang=<x> (<mix>) <s>s audio in <s>s (<x>x realtime), <n> words`, `FAILED: <error>`, `note: <warning>`. If the worker wrote no result: `the whisper worker wrote no result (exit <n>)` with up to 8 lines of its other output.
- **Speakers** (`--speakers`): a second pass runs the speaker-separation worker (below) on every file that transcribed. Each word is given the speaker turn it overlaps most; a word overlapping no turn takes the nearest turn within 0.5 s, else no speaker. If the pass fails for any reason, logs `[diarize] NO SPEAKERS -- every word's speaker stays null` with the reason, records it in the sidecar's `speaker_error`, and keeps the transcription. Logs `speakers: <n> in <k> turn(s)` per file. Model `pyannote/speaker-diarization-3.1` unless `--diarize-model`. Python: `C:\Users\alex\tools\whisper\.venv-diarize\Scripts\python.exe` when present, else the whisper Python (`--diarize-python` overrides). Token from `HF_TOKEN`, `HUGGING_FACE_HUB_TOKEN`, or `[whisper] hf_token` in `deploy\site.toml`; passed only in the child's environment, never printed.
- **Per file written**:
  - The word sidecar (format below) with `fps` from ffprobe (default the pipeline's default rate) and no timecode shift.
  - The `.md`: frontmatter with clip, source path, video id, channel, title, URL and upload date (read from a downloader credits file through the montage module, or the id from the file name), start timecode blank, fps, language, number of speakers, words, paragraphs, duration, `timing: word`, sidecar file name, model, export date, `exported_by: whisper_corpus.py`, and a fingerprint of the word stream. Paragraphs break where speech pauses for the montage module's pause length (a `(...)` marker is inserted at such gaps). Speaker headings appear only with more than one speaker. A `.md` someone has edited by hand is not overwritten without `--force`: logs `[md  ] <stem>: hand-edited, left alone (--force to overwrite)`.
  - Logs `[ok  ] <stem>: <n> words, <k> speaker(s) -> <md name>`.
- Ends with `done: <n> transcribed, <f> failed, <k> skipped (<min> min audio in <min> min, <x>x realtime overall)`, the whisper (and speaker) speed, and each failure. Exit 1 if any failed, else 0.
- Flags: `--folder` (repeatable, required), `--root` (required), `--speakers`, `--diarize-model`, `-m/--model` (default `large-v3-turbo`), `-l/--language`, `--device` (default `cuda`), `--compute-type` (default `float16`), `--beam-size` (default 5), `--opencc` (default `s2twp`), `--no-s2tw` (no conversion), `--no-tai`, `--batched N` (default 0), `--no-batched`, `--no-vad`, `--force`, `--python`, `--diarize-python`, `--dry-run`.

### Word sidecar format (`<clip>_words.json`), as written by stage 2 and `transcribe`

- `version` 1; `clip` (the pool name or safe stem); `source` (media path); `source_sha1`, `source_size`, `source_mtime` (the fingerprint used by the skip rule); `duration`; `fps`; `timing: "word"`; `language` (majority by spoken seconds); `language_prob`; `languages` (seconds per language); `multilingual`; `detection` (`chunks`, `window` or `forced`); `language_runs`; `model`, `device`, `compute_type`, `vad`, `opencc` (what was actually applied, empty when nothing was converted), `batched`; `speakers` (labels used, empty without speaker separation), `speaker_source`, `speaker_error`; `made` (local time), `made_by: "whisper_corpus.py"`; `segments` (whisper's sentences: start, end, text, language); `words` (start, end, text, speaker). Interviews add `start_tc_sec` and `start_tc`.
- A segment that came back with no words becomes one word covering the whole segment, so its text is never lost.
- Written through a temporary file and swapped in.

## Speaker separation worker (source: diarize_worker.py)

- A separate program run by `transcribe --speakers`. Usage: `diarize_worker.py --out <turns.json> [--model <name>] [--device cuda] FILE...`.
- Needs: pyannote.audio in its Python, a Hugging Face read token in `HF_TOKEN` (or `HUGGING_FACE_HUB_TOKEN`), and that account having accepted the terms of both `pyannote/speaker-diarization-3.1` and `pyannote/segmentation-3.0`. Uses the GPU when torch sees one, else the CPU (`staying on the CPU (<reason>)`).
- Refusals, each written into the result as `error` with a `no_speakers` event and exit status 3: pyannote missing (the message gives the exact one-time install commands for `.venv-diarize`, torch for CUDA 12.4 and `pyannote.audio>=3.3`, and the token instructions); no token (`HF_TOKEN is not set, and <model> is a gated model.`); terms not accepted (`huggingface refused <model>: the model is gated and this account has not accepted its terms ... retrying will not help.`).
- Loads model checkpoints with torch's safe-loading check turned off, in this process only.
- Any file that is not `.wav`, `.flac` or `.ogg` is first decoded to a temporary 16 kHz mono WAV with ffmpeg (deleted when that file is done); with no ffmpeg it warns `no ffmpeg -- handing <file> to pyannote as it is`; a decode failure fails that file `could not decode <file> to WAV: <detail>`.
- Writes `{model, device, files: [{path, turns: [[start, end, label]...], seconds}]}`; progress events as the whisper worker's (`load`, `start`, `done` with turns and speakers, `failed`, `warn`). Exit 1 only when every file failed.

## fold-mono: one-sided stereo WAVs to true mono (source: mono_fold.py)

- **What it does**: an interview WAV whose sound is all in one channel of a stereo file plays in one ear in headphones; this rewrites it as a one-channel WAV.
- **Needs**: ffmpeg and ffprobe (on the PATH, else `~\tools\ffmpeg\bin\ffmpeg.exe` or `C:\ffmpeg\bin\ffmpeg.exe`, ffprobe beside it). No Resolve, no GPU, no Claude, no notes app.
- Usage: `pipeline.py fold-mono <wav or folder> [...] [--recurse] [--silence-db dBFS] [--dry-run] [--legacy FOLDER | --no-legacy] [--one-sided]`.
  - With no ffmpeg at all: `no ffmpeg on PATH - nothing can be measured` and stops.
  - A folder means its `.wav` files; with `--recurse`, every `.wav` in it and below, skipping any folder named `legacy`. A file named outright is always taken. A target with no WAV prints `<target> no .wav here`. No WAVs at all: exit 1.
  - Prints `<n> wav(s) to check`, then one line per WAV with the reason. Exit 0.
- **Decision** (default): measures each channel's peak level over the whole file. Folded only when exactly one channel peaks above the silence floor (default -30 dBFS, `--silence-db` changes it). Left alone, with the reason: already one channel, no audio, audio in more than one channel (with each channel's level), every channel silent, or `could not measure the channels`.
- **`--one-sided`**: does not test; folds to whichever channel is loudest by average (RMS) level. Meant for a recorder known to write one channel into a stereo file.
- **The rewrite**: a new one-channel WAV is written beside the original as `.<name>.mono.tmp.wav`, keeping the original's PCM sample format (24-bit if the source is not PCM), allowing files over 4 GB, copying metadata. It is checked to be one channel and the same length to the millisecond before it replaces the original; any failure leaves the original untouched (`fold FAILED, left as it was: <reason>`).
- **Keeping the original** (command line only): by default the stereo original is moved into a `legacy` folder beside it (`--legacy` names another folder; a name already there gets ` (2)`, ` (3)` ...). `--no-legacy` keeps nothing. If the move fails, nothing is folded. If the swap then fails, the original is moved back, or the message says where it is.
- `--dry-run`: `would fold to mono, original to legacy\: <reason>` and changes nothing.
- When stage 2 calls it automatically (render mode and library mode), the stereo original is never kept.
- Never folds dual mono (the same sound on both channels).

## Preview video beside each interview WAV (source: preview_video.py)

- **What it does**: for every interview WAV, makes `<same name> Preview.mp4` in the same folder: a small picture of the interview that lines up with the WAV from its first frame, so Timeline Cards can play picture beside the audio.
- **Needs from outside**: no Resolve (it never connects). Read access to the project library (`--db-host` / `--db-name`, defaults from `CARDS_DB_HOST` / `CARDS_DB_NAME` or `deploy\site.toml`); with none, every clip fails `no project library (--db-host / --db-name, CARDS_DB_HOST / CARDS_DB_NAME)`. ffmpeg and ffprobe on the PATH. The camera files (or, for Blackmagic RAW files, their `Proxy\<stem>.mp4` sibling, found by another section's code) must be reachable. An NVIDIA GPU is used for encoding if ffmpeg has it, else the CPU. No Claude, no notes app.
- Usage: `pipeline.py preview-video <episode root or Interviewees folder> [--overwrite] [--dry|--dry-run] [--only NAME] [--no-verify] [--trust-library] [--encoder auto|nvenc|x264] [--db-host] [--db-name] [--db-project]`.
- Which WAVs: the same walk as stage 2's library mode (the `Interviewees` folder and one level of subfolders), filtered by `--only` (case-insensitive, repeatable). None: `no WAVs under <root>` and exit 0.
- **Per WAV**:
  - An existing preview is skipped (`preview exists, skipped`) unless `--overwrite`.
  - The clip is looked up in the library by the WAV's file name: first in the named project (stage 2 passes the open project), else in every project; every same-named multicam that has picture is a candidate. None: `not a multicam in the project library`.
  - Picture source: angle 1 (the first video track). Every camera item on it is placed at its own position; where items overlap, the later one wins and the note says how much of the earlier shows. An item with no camera file shows black and is noted. An angle with no picture at all is passed over for the next (`angle 1 has no picture; angle <n> is used`). Compound clips inside an angle are opened, to a depth of 8; one that cannot be opened shows black (`... is a compound clip the library cannot open: black`). Still images (`.psd .png .jpg .jpeg .tif .tiff .gif .bmp .webp .exr .tga`) are skipped with a note. An item with a non-default time map (possibly a speed change) is noted and kept only if its sound check passes.
  - **Sound check before encoding** (not in dry run): for each camera item, at 6 points along it, a window of up to 15 s of the WAV is searched for in the camera file's sound within 25 s either side of where the library says it should be (analysed at 8 kHz). A match counts when its strength is at least 0.15. At least 3 points (and at least half of those that ran) must agree within two frames; the agreed offset then corrects the picture's start. Items too short to test (window under 4 s) borrow the offset of another item from the same file. An item that fails is dropped (whatever it covered shows through, and the check runs again, up to 4 times) with a reason such as `sound check failed: <good> of <ran> probes matched, peaks [...]`, plus `the file is only <x> s long but the item needs <y> s of it` or a time-map note when they apply. `--trust-library` keeps a failed item at the library's position, marked `UNVERIFIED, library offset used`. If nothing usable remains: `could not verify the sync against the wav (<reasons>)`, and no preview is made.
  - Logs each item `item <name> at <s> s, <s> s shown offset corrected <+s> s (<frames> frames, drift <s> s)` or `LEFT BLACK -- <reason> -- dropped; whatever it covered shows instead`, every note, and `black: <s> s of <total> s (longest item only: <s> s)`.
  - **Encode**: H.264, 480 pixels tall (width keeps the shape, even number), the multicam's frame rate, a keyframe at least every second, 650 kbit/s video (max 900), mono AAC 64 kbit/s at 48 kHz of the camera's own sound, fast-start layout, exactly as long as the WAV with black before and after the picture. Several items are laid over one black base, each letterboxed to the first file's shape, with their sounds mixed. GPU encoder (NVENC) first when available and `--encoder auto`, falling back to x264 (`<encoder> failed (<last error line>)`). Encoded to a local temporary folder, then copied beside the WAV as `<name> Preview.mp4.part` and renamed, so a half-written preview is never visible.
  - **Sound check after encoding** (unless `--no-verify`): the finished preview's sound is compared with the WAV at 5 points inside each item; logs `sync <item> <+ms> ms against the wav (spread <ms> ms, peaks [...])`, with `** OFF BY MORE THAN A FRAME **` when off by more than 1/30 s, or `no clear match`.
  - Result lines: `-> <path> (<MB> MB, <encoder>, <s> s)`, `preview exists, skipped`, `would make <path>` (dry run), or `NO PREVIEW: <reason>`.
- Never stops a calling run: every failure becomes a `NO PREVIEW` line.
- Ends with `preview video: <n> made, <n> exists, <n> failed ...`. Exit 2 if any failed or if fewer results came back than WAVs (which is what happens when no library is configured); else 0.

## Stage 1b: adopt whisper as the interview's transcript (source: whisper_transcripts.py)

- **What it does**: for interviews that already went through stage 2, replaces the Resolve-made raw transcript with whisper's, so the transcript text, the cues and the word timing all come from one transcription. It re-transcribes nothing.
- **Needs**: only the files stage 2 wrote. No Resolve, no project library, no GPU, no Claude, no notes app. Not on the stage page; command line only.
- Usage: `pipeline.py whisper-transcripts <Interviewees folder, or one interviewee's folder> [--only NAME] [--dry-run] [--force]`.
  - A path that is not a folder: `not a folder: <path>`, exit 2. A folder holding a `*_words.json` itself is treated as one interviewee; otherwise each subfolder is one. Nothing found: `nothing under <path>`, exit 1.
  - `--only` (repeatable) keeps clips whose name contains the text, ignoring case.
- **Per word sidecar** `<clip>_words.json` in an interviewee folder:
  - A sidecar with no segments and no words: FAILED `the sidecar holds no segments and no words`. With words but no segments: FAILED `the sidecar has no segments -- re-run stage 2 for this clip, or keep Resolve's text`.
  - Builds the raw transcript `<stem>.md` from whisper's segments, one line per segment, with a blank line wherever speech paused 1.2 s or more.
  - Skipped (`skip already whisper's`) when `<stem>.md` already holds exactly that text, unless `--force`.
  - `--dry-run`: `DRY`, writes nothing.
  - Otherwise: moves the existing `<stem>.md` to `<stem>.resolve.md` and `<clip>.srt` to `<clip>.resolve.srt`, but only the first time (when a `.resolve` copy already exists, the current file is simply overwritten); writes the new `<stem>.md`; copies `<clip>.whisper.srt` over `<clip>.srt`, or, if that is missing, builds a `.srt` from the word timings with stage 1's cue rules (FAILED `no cues to write` if there are none).
  - Never touches the prepped `<stem>_Transcript.md`; the person must re-run Prep and finalize for that interviewee to get a transcript built from whisper's text.
- Logs per folder, then per clip: `written <n> segments, cues from <the .whisper.srt | the word timing>, kept <backup>`, `skip`, `DRY` or `FAILED <reason>`. Ends with `<n> clip(s), <f> failed (dry run)`. Exit 1 if any failed.

## Stage 3: which multicams are still cut short in Resolve (source: check_multicam_transcripts.py)

- **Why it exists**: Resolve's own speech-to-text silently stops early on 32-bit float recordings carrying samples far above full scale. The 24-bit WAV from stage 2 does not have the problem, so the fix is a manual swap in Resolve. This stage reports which clips still need it and confirms the fix worked.
- **Needs**: Resolve open with the project (same readiness check and refusals as stage 1), the project library readable (same rules as stage 1, but with no command-line overrides for the library name or host), and ffprobe on the PATH to measure each WAV. No GPU, no Claude, no notes app.
- Usage: `pipeline.py check-multicam-transcripts --out <Interviewees> [--bin NAME] [--tolerance SECONDS]`. `--out` is required.
- Refusals: `no project is open in Resolve`, `bin '<x>' not found in the media pool`, `no multicam clips in bin '<name>'`.
- Prints a table, one row per multicam: clip length (frames over FPS, default 29.97), the length of its rendered `<clip>.wav` (looked for in the interviewee folder found by stage 2's folder matching), the end of Resolve's transcription (last word's end minus one hour), and a status:
  - `no render` when the WAV is missing; `render short <n>s` when the WAV is more than 1 s shorter than the clip;
  - `not transcribed` when Resolve holds no transcription; `TRANSCRIPT SHORT <n>s` when it ends more than the tolerance (default 10 s) before the clip does;
  - `ok` otherwise; a database error prints `DB error: <reason>` for that clip.
- All fine: `all <n> multicam(s) fully transcribed.`, exit 0.
- Otherwise: `<k> of <n> need attention:`, the names, and the instructions: drag `<clip>.wav` (already in the bin) onto that multicam's audio Angle 1, pushing the 32-bit original to Angle 2, run Resolve's Transcribe Audio and re-run the check; "Resolve keeps an existing transcription -- Clear Transcription first, or the re-run is a no-op that returns the same truncated result." Exit 1.

### The manual swap (between stage 2 and stage 4)

- Nothing in this part can do it: there is no scripting call for multicam angles. A person, in Resolve: drags each `<clip>.wav` onto its multicam's audio Angle 1 (the 32-bit original falls to Angle 2), clears the transcription, transcribes again, and (per the stage page's text) swaps back. Then re-runs stage 1 Export (to get the full-length Resolve text) and stage 3 to confirm.

## Stage 4: Resolve's transcript against whisper's, interval by interval (source: check_transcript_coverage.py)

- **What it does**: finds stretches where Resolve's subtitles have no cue. With a second source (whisper's subtitles, or the audio itself) it decides which of those stretches really had speech in them, that is, were dropped.
- **Needs**: nothing but files for the basic modes. ffprobe for `--media`. faster-whisper in the running Python for `--media` speech detection and for `--recover` (which loads `large-v3` on whatever device is available). No Resolve, no Claude, no notes app.
- Usage: `pipeline.py check-transcript-coverage --srt <file> [--media <audio>] [--reference-srt <file>] [--min-gap auto|SECONDS] [--min-speech SECONDS] [--lang zh|en] [--recover] [--offset TC] [--duration T] [--fps N]`.
- **Start time**: with no `--offset`, if the first cue starts at 59 minutes or later it assumes an hour-start timeline, subtracts one hour from every cue (and from the reference's cues) and says so (`note : first cue is at ~01:00:00 — assuming an hour-start timeline and subtracting 1h. pass --offset 0 if that is wrong.`). `--offset` takes a timecode with frames (at `--fps`, default 29.97), `HH:MM:SS.mmm`, or seconds.
- A file with no cues stops: `no subtitle cues parsed from <file> — is it really an SRT?`.
- Prints the cue count, span and total cue time.
- **Gap threshold**: `--min-gap auto` (default) is ten times the median gap between cues, never below 6 s; it prints the median and 95th percentile and the threshold chosen. A number sets it directly. A gap before the first cue that long counts too.
- **Reference length**: `--duration` (timecode or seconds) or the `--media` file's length through ffprobe (`ffprobe failed on <file>` stops it). If the last cue ends more than 1 s after the reference length it stops with an error explaining that the subtitles and the audio are not on the same timebase and how to render the matching audio from Resolve. A tail gap at least the threshold long is added. Prints the share of runtime covered. Without either it notes that the truncated-tail check (the most common failure) cannot run. With `--media`, a first cue landing more than 1 s before zero warns that the offset looks wrong.
- **Outcomes**:
  - No gaps: `OK: no gap of <n>s or more between cues.` plus the density chart; exit 0.
  - With `--reference-srt`: a reference running past the last cue by more than the threshold adds that tail (only when neither `--media` nor `--duration` was given). Each gap is "real" when the reference has at least `--min-speech` seconds (default 2) of cues inside it, else "genuine silence". No real gaps: `OK: the reference found no speech that the subtitles miss.`, exit 0. Otherwise `*** <n> SKIPPED SECTION(S): <time> of speech the reference caught and the subtitles didn't ***`, each with its span, the density chart, `Open the reference SRT at those timecodes to read what was lost.`, exit 1. This is the mode the stage page's Verify uses.
  - With neither reference nor media: lists every gap (`some may just be silence`), the chart, and advice to add `--media` and `--recover`; exit 1.
  - With `--media`: speech is detected in the audio (pauses of 0.5 s split speech); gaps with at least `--min-speech` seconds of speech are real; silent ones are listed as ignored (first four shown). None real: `OK: every gap is genuine silence. Nothing was skipped.`, exit 0. Otherwise `*** <n> SKIPPED SECTION(S): <time> of speech with no transcript ***` and the list; with `--recover` each window is transcribed in `--lang` (default `zh`) and printed as `[start -> end]` and the text (or `(nothing recognised)`), else a hint to re-run with `--recover`; exit 1.
- **Density chart**: one character per minute of runtime (a ramp from blank to `#`), 60 per row, then every run of full minutes under 35% covered, with its share. Printed in every outcome except the media mode.
- `--recover` has no effect in the reference mode.

## Stage 5: give every block a permanent `^ref` (source: finalize_transcript.py, blocklen.py)

- **What it does**: turns a prepped draft (paragraph blocks separated by blank lines: English line(s), then the original-language line; `# ` in front of interviewer-question lines) into the final transcript with a unique `^ref` line under every block.
- **Needs**: only the draft file. Normally run by Claude during Prep (the PREP prompt names it). No Resolve, no GPU, no notes app.
- Usage: `pipeline.py finalize-transcript <draft.md> <final.md> [--max-seconds N] [--allow-long]`. A wrong argument count prints the help and exits 1.
- **Refusals** (exit 1):
  - The final file already exists, whatever its content: `ERROR: <final> already exists - refusing to overwrite. Delete or rename it first if regeneration is intended.`
  - The draft has no blocks: `ERROR: draft has no paragraph blocks`.
  - Any block estimated longer than 60 s of speech (`--max-seconds` changes the limit; `--allow-long` turns the check off): `ERROR: <k> of <n> blocks are over <limit>s of tape - too long to cut with. Split them at the answer's own internal turns before finalizing (aim ~20s a block). Re-run with --allow-long to override.` and each offending block as `block <i>: <s>s <first 70 characters>`.
- **Length estimate**: lines starting `_Source:` or `^` are ignored and a leading `# ` is removed. If any line carries 10 or more wide (Chinese) characters, the estimate is the wide characters on those lines at 4.5 per second; otherwise the words on all lines at 2.5 per second.
- **Refs**: a block whose last line is already a `^ref` keeps it. Each new ref is 6 characters of lowercase letters and digits, derived from the block's text and position, unique within the file.
- Writes the blocks separated by blank lines and prints `Wrote <final>: <n> blocks (<k> new refs, <m> preserved)`.

## Re-split an over-long draft without changing its words (source: resplit_draft.py)

- **What it does**: breaks over-long blocks in a draft into several, at points a person (or Claude) names, and proves no character of text changed.
- **Needs**: only files. Not on the stage page.
- `pipeline.py resplit-draft <draft.md> --report [--max-seconds N]`: prints `<n> blocks median <s>s p90 <s>s max <s>s over <limit>s: <k>` and each block over the limit (default 60 s) with its number and first 80 characters.
- `pipeline.py resplit-draft <draft.md> <splits.json> [--dry-run] [--max-seconds N]`: applies splits. The JSON maps a 1-based block number to one of:
  - a list of anchors: the exact opening text of each new sub-block after the first;
  - `{"en": [...], "zh": [...]}`: anchors for the English line and the original-language line separately, for a two-line bilingual block; both must produce the same number of parts, and part i of each are paired;
  - a string: the full replacement text, blank-line separated.
- Refusals (each stops the run with `ERROR: ...` and writes nothing): block numbers out of range; an anchor not found, found twice, or at the very start of the block; a bilingual block that does not have exactly one English and one original line; a line or block that lost or gained any character other than whitespace; a split producing only one block; different part counts per language.
- Prints `<n> blocks -> <m> (<k> split)`, any blocks still over the limit, then either `(dry run, not written)` or `wrote <draft>` (the draft is rewritten in place).

## Stage 6: every `^ref` block becomes one line of the paragraph pool (source: extract_paragraphs.py)

- **What it does**: reads every interviewee's finished transcript and writes a JSON-lines file, one paragraph per line, which the category steps and the canvas build read.
- **Needs**: only files. Another section's card-height estimator is called for each paragraph. No Resolve, no GPU, no Claude, no notes app.
- Usage: `pipeline.py extract-paragraphs <episode root> <output .jsonl>`. A wrong argument count prints the help and exits 1. No `Interviewees` folder: `ERROR: <path> not found`, exit 1.
- For each interviewee subfolder (sorted by name, ignoring case; no folder is skipped by name here, unlike the stage page's scan):
  - The source is the `.md` with the most `^ref` blocks (a block counts only if it has at least one text line above its `^ref` line), provided it has at least 3. Each block becomes one paragraph whose text is `_Source: [[<vault-relative path>#^<ref>|<file stem> › ^<ref>]]_`, a blank line, then the block. The vault-relative path is everything after a folder named `vault` (any case), else the last five path parts.
  - Otherwise, an older `*(paragraphs).canvas` file in the folder: each text card becomes a paragraph, in top-to-bottom, left-to-right order, with no ref and the card's stored height (default 400).
  - Otherwise the summary says `NO TRANSCRIPT MD OR CANVAS - needs prep` and the folder contributes nothing.
- Each line: `key`, `interviewee` (folder name), `ref` (or null), `source` (file path), `height` (estimated card height), `question` (true when every non-empty line of the block starts with `#`), `text`.
- **Keys**: `p` plus 8 hexadecimal characters derived from `interviewee|ref` (or from the interviewee and position for the older canvas source), so editing one transcript does not change any other paragraph's key. Two different paragraphs with the same key stop the run: `ERROR: key collision on <key> -- ... Re-ref one of the blocks (finalize_transcript.py) and re-run.`
- Creates the output folder if needed, overwrites the output file, prints `Wrote <n> paragraphs -> <path>` and one summary line per interviewee.

## Language assist: phrase alignment and word links for Timeline Cards (source: assist_links.py)

- **What it does here**: a thin launcher. It runs the editor's own script `editor\scripts\assist-links.ts` (another section) over an episode with Node; that script is what calls Claude and writes the results into `<episode root>\Script Docs\Cuts\.tcards\` (`@align`, `@aids`), which Timeline Cards reads.
- Usage: `pipeline.py assist-links <episode root> [--dry] [--max-calls N]`; everything after the root is passed through to the script unchanged.
- Refusals (exit 1, message on the error stream): no root given, or the first argument starts with `-` (`usage: assist_links <episode folder> [--dry] [--max-calls N]`); no `Interviewees` folder (`no Interviewees folder in <root>`); no `node` on the PATH (`node is not on PATH (the editor's passes run on Node)`); the editor's packages not installed (`the editor's packages are not installed: run npm ci in <editor folder>`).
- Runs `node --import tsx scripts/assist-links.ts --episode <root> ...` in the repo's `editor` folder with the full environment, and returns its exit status: 0 done, 2 stopped at the Claude call budget (run again to carry on), 1 an error (as this file describes it; the script itself is not part of this section).
- **Needs**: Node and the editor's installed packages; whatever Claude access the editor script uses (not determinable from this part). No Resolve, no GPU.
- The stage page runs it automatically after Prep, and as its own Language assist row.

## Where the crew asks "introduce yourself": `first-question` (source: first_question.py)

- **What it does**: transcribes only the opening window of an interview recording and finds the moment the crew asks the interviewee to introduce themselves, which is where the multicam is meant to be trimmed to. Prints that time in a form to paste into Resolve.
- **Needs**: no Resolve (only the file). ffmpeg on the PATH. A GPU by default (`--device cuda`, no automatic CPU fallback). The whisper Python environment at `C:\Users\alex\tools\whisper\.venv\Scripts\python.exe` when present, else the current Python (`--python` overrides); it needs faster-whisper and numpy, and uses OpenCC if present. No Claude, no notes app. Not on the stage page.
- Usage: `pipeline.py first-question <audio or video file> [--start SECONDS] [--minutes 15] [-m large-v3] [-l/--lang/--language CODE] [--device cuda] [--compute-type float16] [--beam-size 5] [--python PATH] [--json FILE]`. A missing file raises an error. `--worker` is a hidden flag used only when it runs itself as the transcription child.
- **Transcription**: the child process decodes only the window from `--start` for `--minutes` (default the first 15 minutes) as 16 kHz mono, straight from the file without writing to disk, then transcribes it with per-chunk language detection (or the per-30-second fallback, or a forced language), and applies the house OpenCC pass (`s2twp` plus `台`) to Mandarin or Chinese-character segments. Its progress goes to the screen; word timings are not kept. If the child fails: `the whisper worker failed (exit <n>)` with its last output, or `the whisper worker wrote no JSON`. ffmpeg failing or decoding nothing is reported as the child's error.
- **Finding the moment**, three passes in order; within a pass the earliest segment wins:
  1. The question: a segment containing any of `自我介紹`, `介紹一下`, `介紹自己`, `介紹您自己`, `介紹你自己`, `先介紹`, `簡單介紹`, `請介紹` (each also in Simplified), or, ignoring case, `introduce yourself`, `introduce yourselves`, `tell us who you are`, `tell me who you are`, `who you are and what you do`, `your name and`, `start by introducing`. Text is also checked after an OpenCC Simplified-to-Traditional conversion when OpenCC is installed.
  2. A bare `介紹` (or `介绍`).
  3. The answer, only in segments starting within the first 10 minutes of the window: a segment that, after leading fillers and punctuation, begins `我是`, `我叫` or `大家好`, or matches "my name is", or "I'm / I am ... and I" within 100 characters.
- **The time reported**: the window start plus the segment's start, minus 0.75 s (1.5 s for an answer), never earlier than the window start.
- **Output**: `file`, `window <start> .. <end> (<n> segments, <language>, <detection>)`, `whisper <model> <type>, <s> s audio in <s> s (<x>x realtime), model load <s> s`, then either `FIRST QUESTION at <h:mm:ss.mmm> (<seconds> s, via <question|question-weak|answer>: <pattern>)`, the line, and two segments either side with the hit marked `>`; or `NOT FOUND - no intro question in this window. The segments are below; widen with --minutes or move with --start.` followed by up to 80 segments and `... <n> more`. `--json FILE` also writes the whole result (`wrote : <file>`). Exit 0 whether or not it was found.

## Search helper for the transcript-search skills (source: search_transcripts.py)

- **What it does**: the exact half of a Claude search over interview transcripts. Claude reads and judges; this finds the transcripts, prints blocks, and writes the results page with every quote copied from the file, refusing any reference that does not exist.
- **Needs**: only the prepped transcripts. Used by Claude skills stored outside the repo (`project-search`, `transcript-search`) through the top-level `search_transcripts.py`. No Resolve, no GPU, no notes app.
- **Which transcripts**: a target may be an episode root, its `Interviewees` folder, one interviewee folder (that person only), or a single transcript file (a file not named `*_Transcript.md` gets `WARNING: <name> is not a *_Transcript.md; searching it anyway`). The episode root is found by walking up to the first folder that has `Interviewees` (`ERROR: no Interviewees folder at or above <path>` if none). Per interviewee folder, the `*_Transcript.md` file; with several, the one with the most blocks (`(note) <name>: <n> transcripts, using <file>`); with none, `(skip) <name>: no *_Transcript.md`. None at all: `ERROR: no *_Transcript.md files under <path>`.
- `list <target>`: one line per transcript: interviewee, block count, size in bytes, path.
- `grep <target> <regex> [--context N]`: every block matching the regular expression (ignoring case), printed as `<name> ^<ref>:` and the block (marked `>>`) with N blocks either side; the total count goes to the error stream.
- `show <target> ^ref [^ref ...]`: each named block's exact text (the `^` is optional), or `^<ref>: NOT FOUND`.
- `render <target> --hits <hits.json> [--out <file.md>]`:
  - The hits file holds `query` (required: `ERROR: hits.json has no 'query'`), `summary`, and `hits`, each with `interviewee` (folder name; may be omitted for a single transcript), `refs` (or a single `ref`), `score` (3 on point, 2 relevant, 1 tangential; default 2) and `why`.
  - Every hit is checked before anything is written: unknown interviewee, no refs, a ref not in that transcript, or a score other than 1 to 3. Any problem prints `ERROR: hits.json rejected - fix these and re-run:` and the list, and exits 2 without writing. No hits at all: `WARNING: no hits; writing an empty results page`.
  - The page goes to `--out`, else `<episode root>\searches\<YYYY-MM-DD> [<interviewee> - ]<query, cleaned and cut to 90 characters>.md`, never overwriting (` (2)`, ` (3)`...). The `searches` folder is created if needed.
  - Page content: `# Search: <query>`; date, scope, hit counts by score; a Summary section if given; for several transcripts, a table of interviewees with hits and their best score, and `Nothing found for: <names>`; then per interviewee (best score first, then most hits) each hit as `### ★★☆ ^ref ^ref`, the reason in italics, the nearest interviewer question within the 4 blocks before it as `> **Q:** ...`, the blocks quoted, and `Source:` links in the vault's `[[path#^ref|stem › ^ref]]` form.
  - Prints `wrote <path> (<n> hits)`.

## Translate the montage corpus with a local model: `translate-corpus` (source: qwen_translate.py)

- **What it does**: for every montage-corpus transcript `<root>\Clips\<stem>\<stem>_Transcript.md`, puts an English line above each Mandarin block, translated by a local model through Ollama. Interview transcripts are not touched (only the `Clips` folder is read).
- **Needs**: an Ollama server (default `http://localhost:11434`) with the model (default `qwen2.5:7b-instruct`); no API key, no Claude, no Resolve, no notes app. It does not start Ollama.
- Usage: `pipeline.py translate-corpus --root <episode root> [--model NAME] [--url URL] [--limit N] [--dry-run]`. No `Clips` folder: `no Clips folder under <root>` on the error stream, exit 2.
- **Per file**: the frontmatter is kept as is. Each blank-line-separated block is read as heading lines (starting `#`), a `^ref` line, the line with the most Chinese characters (counted as Mandarin when at least 20% of it is Chinese), and the remaining lines joined as the English. An English part that contains any Chinese character is treated as missing and redone. Blocks with Mandarin and no English are translated; a file with none is left alone.
- **Translation**: one request per block, temperature 0.1, up to 180 s each, with a fixed instruction to translate Taiwanese Mandarin speech into fluent English for documentary subtitles, transliterating every name, and to reply with nothing but the translation. The answer is collapsed to one line. An answer containing any Chinese character is rejected and retried with a sterner instruction, and on the third try with one worked example (a reporter's sign-off); after three rejects the block fails (`FAILED (the model kept Chinese characters in the answer) -- the zh stays alone`). A network error also fails just that block.
- Each translated block logs `<seconds>s <first 70 characters>`. The rewritten block is: headings, English, Mandarin, `^ref`. When at least one block was translated, the whole file is rewritten through a temporary file, with every block re-emitted in that normalised shape and separated by single blank lines.
- `--dry-run` counts blocks that would be translated and writes nothing. `--limit N` stops after N files that had work.
- Logs `<n> transcript(s) under <Clips>`, `[<i>/<n>] <stem>: <k> block(s) translated[, <f> failed]` (or `to translate`), a file-level `FAILED (<reason>)`, and `done: <n> block(s) in <files> file(s), <failed> failed, <min> min`. Exit 0.

## Repair word sidecars converted one token at a time: `repair-words` (source: repair_words.py)

- **What it does**: older word sidecars had their Mandarin words converted to Traditional one character at a time, so phrase-level replacements in the segment text did not reach the words, and Timeline Cards could not find some paragraphs in the word stream. This re-converts each segment's words as one phrase, from the sidecar itself, with no transcription.
- **Needs**: OpenCC in the running Python; another section's translation-cache module (imported at start, so the command fails without it). No Resolve, no GPU, no Claude, no notes app.
- Usage: `pipeline.py repair-words (--root <folder> | --file <sidecar> ...) [--apply] [--no-backup] [--no-translations]`. Neither given: `nothing to do: give --root or --file`, exit 2. `--root` finds every `*_words.json` anywhere below it.
- **Dry by default**: prints what would change and writes nothing until `--apply`.
- **Per sidecar**:
  - Unreadable: `unreadable (<reason>)`.
  - It uses the conversion the sidecar records in `opencc`. A sidecar with no such field is assumed to have had `s2twp+tai`, but only if its segment text is unchanged by that conversion; otherwise `no opencc field and the segments do not look converted -- left alone`. An empty record: `no OpenCC pass recorded -- nothing was converted`. OpenCC failing to load prints its warning and the file is left alone.
  - Each word is assigned to the segment it overlaps most (a zero-length word to the segment it sits in); words in no segment are left exactly as they are. Each segment's words are joined, converted, and split back. Timings and all other fields are untouched.
  - No change: `already converted as phrases`. Otherwise `<n> token(s): <was>><now>, ...` (first 8 shown).
  - With `--apply`: a `<file>.bak` copy is made the first time only (not with `--no-backup`), and the file is replaced through a temporary file.
- Prints `[DRY RUN: ]<n> token(s) in <k> file(s) would be re-converted | re-converted`, and `re-run with --apply to write them` on a dry run with changes.
- **Translation caches** (only with `--root`, unless `--no-translations`): in `<root>\Script Docs\`, the files `card_translations.json` and `gt_translations.json` (written by Timeline Cards, another section) are keyed on the person and the exact Mandarin. For every entry whose Mandarin changes under the house conversion, it works out which interviewee (from `Script Docs\interviewee_colors.json`, plus "no interviewee") produced the key, and copies the entry under the new key, keeping the old one. Entries no name accounts for are counted, not guessed. Prints `<cache> <n> entr(ies) re-keyed[, <k> whose interviewee is unknown]`; writes only with `--apply`.

## Comparing Chinese regardless of script (source: zh_fold.py, zh_fold_table.py, tools/gen_zh_fold.py)

- **What it is**: a one-character-to-one-character table that maps Traditional Chinese characters (including Taiwan variant forms such as `臺`) to Simplified, so two texts can be compared as "the same words" whichever script each is in, without changing lengths or positions. It never rewrites any file.
- **Who uses it**: nothing in this part. Other sections call it (the canvas-to-timeline step, and Timeline Cards' text matching and transcript search).
- Offers: fold a text to Simplified (same length always); list every spelling of a character the table knows (itself, its Simplified form, every Traditional form that folds to it); and test whether two texts are the same after folding.
- If the table cannot be loaded, folding does nothing (texts compare exactly).
- **The table** (`zh_fold_table.py`, generated; I sampled its start and end rather than reading every character): 4,112 pairs, held as two long strings of keys and values. The file says it was generated on 2026-09-04.
- **The generator** (`tools/gen_zh_fold.py`, run by hand): reads OpenCC's `TSCharacters.txt` (first candidate, single characters only) and `TWVariantsRev.txt` (Taiwan variants folded on to the same target) from the fixed folder `C:\Users\alex\tools\whisper\.venv\Lib\site-packages\opencc\dictionary`, resolves chains for up to three rounds, drops identity pairs, and overwrites the fixed path `E:\Projects\Editing\Resolve\MulticamPipeline\multicam_pipeline\zh_fold_table.py`. Prints the pair count, a sample and four check characters. Both paths are hard-coded.

## Shared look for the stage page (source: webtheme.py)

- A block of page styling (dark background, blue accent, green, amber and red status colours, thin scrollbars, Segoe UI 14 px body text) that pages paste into their own style sheet. The stage page actually loads the identical copy in the sibling `Editing\Launcher` folder, not this one. No behaviour of its own.

## Shared helpers with no command of their own (source: paths.py, transcripts/__init__.py, blocklen.py)

- `paths.py` names the repo folder, so modules can find `deploy\site.toml` and the sibling `MontagePipeline` folder.
- `transcripts/__init__.py` only lists the modules; no behaviour.
- `blocklen.py` is the spoken-length estimate described under stage 5, used by finalize and re-split.

## The order of work, and what a person does by hand between stages (source: pipeline_web.py, the stage modules above)

- **Before stage 1, in Resolve, by hand**: build one multicam per interview (other sections' tools can help), put them in a bin, open that bin, and run Resolve's own Transcribe Audio on each multicam. Stage 1 exports whatever transcription Resolve holds; it cannot start one.
- **Before stage 1, on disk, by hand**: create the episode root with an `Interviewees` folder. Interviewee subfolders may be made in advance (stages 1 and 2 match clip names to them) or are created on demand. Optionally a `Script Docs\episodes.json` for a shoot that cuts into several episodes.
- **Stage 1 (Export)**: Resolve open. Writes `<stem>.md` and `<clip>.srt`.
- **Colours** (rides along with Reference): Resolve open (another section's code).
- **Stage 2 (Reference)**: Resolve open for the render; writes `<clip>.wav`, `<clip> Preview.mp4`, `<clip>.whisper.srt`, `<clip>_words.json`, re-imports the WAVs into the bin.
- **Stage 1b (optional, command line only)**: adopt whisper's text as the raw transcript, replacing stage 1's files (kept once as `.resolve.md` / `.resolve.srt`).
- **Stage 3 (Swap check)** and **the manual swap**: Resolve open; a person drags WAVs onto Angle 1, clears and re-runs Resolve's transcription, swaps back, re-runs Export, and re-runs the check until it says `all <n> multicam(s) fully transcribed.`
- **Stage 4 (Verify)**: files only. A person reads the report and, where sections were dropped, goes back to Resolve and re-transcribes before Prep ("or the gaps become holes in the canvas").
- **Prep** (Claude): word timings first (files plus the project library, GPU), then the canvas-sorter skill writes `<stem>_Transcript.md` with English and Mandarin paired, question marks and refs (stage 5 run by Claude), then Language assist (Node and Claude). If finalize refuses over-long blocks, someone (Claude, or a person with `resplit-draft`) splits them and finalize runs again.
- **Stage 6 (Extract)**: files only. On a several-episode root a person must split the shoot-wide pool into per-episode pools by hand before Propose; nothing here does it.
- **Propose** (Claude), then **Select on the page by hand** (tick, rename, add custom categories, Save), then **Sort** (Claude) and the scripted canvas build (another section).
- **Hand ordering of the canvas** in the notes app (another section), then **Conform timeline** in Resolve (another section).
- **Timeline Cards** then reads, from this part's output: the `<clip>_words.json` word timing, the `<stem>_Transcript.md` (paired English and Mandarin with refs), the `<clip> Preview.mp4`, the WAVs, and the Language assist results under `Script Docs\Cuts\.tcards\`.
- **The montage corpus is a separate track**: `transcribe` (whisper a folder of clips into `<root>\Clips\`), then `translate-corpus` (English above the Mandarin with a local model).

## What every stage needs from outside itself (source: all files of this part)

Each line answers: can it run with no editing program (Resolve) open and no notes app? and what else must exist?

- **Export (stage 1, `multicam-transcripts`)**: NEEDS Resolve open with the episode's project, external scripting allowed, and the multicam bin open (or `--bin`); the multicams already transcribed inside Resolve; read access to the project library (PostgreSQL with `psycopg2`, or the local Disk library) and `zstandard`. No GPU, no Claude, no notes app.
- **Multicam colours**: NEEDS Resolve open (another section's code; also writes `Script Docs\interviewee_colors.json`).
- **Reference, render mode (stage 2, `resolve-multicam-whisper`)**: NEEDS Resolve open with the project, the "Audio Only" render preset (or at least a WAV render format), and the bin. Then local only: faster-whisper with CUDA libraries in the running Python (GPU preferred, CPU fallback), OpenCC for Traditional Chinese (optional, warns without it), ffmpeg and ffprobe for the mono fold (optional, skipped without it), the project library and ffmpeg for previews (optional, skipped without them), and the sibling `MontagePipeline` folder for the word sidecar (without it only the `.srt` is written). No Claude, no notes app.
- **Word timings (stage 2, `--from-library`)**: NO Resolve. Needs the project library address (environment or `deploy\site.toml`) and `psycopg2`, the WAVs already rendered and named exactly as their pool clips, faster-whisper (GPU preferred), and the `MontagePipeline` folder for the sidecar. With `--facts-out` / `--from-facts` the library half and the whisper half can run in two different Pythons. No Claude, no notes app.
- **Preview video**: NO Resolve. Needs the project library (address as above), ffmpeg and ffprobe, the camera files (or their proxies) reachable, numpy (for the sound check, through another section's code). NVIDIA encoding used if present. No Claude, no notes app.
- **fold-mono**: NO Resolve. Needs ffmpeg and ffprobe only.
- **Stage 1b (`whisper-transcripts`)**: NO Resolve, no library, no GPU. Needs only stage 2's files.
- **Swap check (stage 3)**: NEEDS Resolve open with the project and the bin; the project library; ffprobe. The manual swap itself is done in Resolve by a person.
- **Verify coverage (stage 4)**: NO Resolve. Files only in the reference mode (what the page uses). `--media` needs ffprobe and faster-whisper; `--recover` needs faster-whisper with a model download or cache.
- **Prep**: NO Resolve (its first step is library-mode word timings: project library plus GPU whisper). Needs the `claude` command-line program installed and signed in (found through `CLAUDE_BIN` or the PATH), the "canvas-sorter" skill installed in the user's Claude configuration (outside this repo), and permission to let Claude run tools unattended. Then Language assist (below). No notes app needed to run, though the output is written in the notes vault's link format.
- **Finalize (stage 5)** and **resplit-draft**: files only.
- **Extract (stage 6)**: files only.
- **Propose, Sort**: NO Resolve. The `claude` program signed in, the canvas-sorter skill. Sort also runs the canvas build (another section).
- **Language assist (`assist-links`)**: NO Resolve. Needs Node on the PATH, the editor's packages installed (`npm ci` in the repo's `editor` folder), and whatever Claude access the editor's script uses (not visible in this part).
- **Conform timeline**: NEEDS Resolve open with the episode's project (another section's code).
- **`transcribe` (montage corpus)**: NO Resolve. Needs a CUDA GPU by default (no automatic CPU fallback), the whisper Python environment at `C:\Users\alex\tools\whisper\.venv` (or any Python with faster-whisper), the sibling `MontagePipeline` folder (required to start at all), optionally ffprobe; for `--speakers`, a second environment with pyannote, a Hugging Face token and accepted model terms.
- **`translate-corpus`**: NO Resolve. Needs Ollama running locally with the model pulled.
- **`first-question`**: NO Resolve. Needs ffmpeg, a CUDA GPU by default, faster-whisper and numpy (the whisper environment when present).
- **`repair-words`**: NO Resolve. Needs OpenCC and another section's `cards` package to be importable.
- **`search-transcripts`**: NO Resolve. Files only (used by Claude skills).
- **The stage page itself**: NO Resolve to open it; the `Editing\Launcher` folder must sit beside the repo's parent (for the theme) and the category files live in the fixed `Editing\Transcripts\canvas-theme-picker` folder. **Check Resolve** and the Resolve stages need Resolve.
- **Machine and path assumptions across this part**: Windows paths are hard-coded in several places: Resolve's scripting modules folder under `C:\ProgramData\Blackmagic Design\...`, Resolve's log and Disk library under `%APPDATA%`, the whisper environments under `C:\Users\alex\tools\whisper\`, ffmpeg fall-backs under `~\tools\ffmpeg\bin` and `C:\ffmpeg\bin`, the default output root `X:\Vault\2026\FF5\Energy Transition\Interviewees` (stages 1 and 2), and the OpenCC dictionary folder and output path of the table generator. The CUDA library-path set-up only acts on Windows. No macOS or Linux paths exist in this part; the Resolve readiness check is another section's code.

## Looks redundant or overlapping

- Two copies of the clip-name-to-interviewee-folder matcher, in stage 1 and stage 2, with slightly different fuzzy scoring (stage 2 adds exact and partial credit together; stage 1 uses partial credit only when no part matches exactly). In rare cases the same clip could land in different folders, and stage 3 and stage 4 then look in stage 2's choice.
- Two copies of the Resolve connection and readiness check (stage 1 raises an error, stage 2 exits) and of "find a bin anywhere in the pool".
- Two whisper transcription engines with the same language logic: stage 2 runs faster-whisper inside the current Python (`large-v3`, CPU fallback), while `transcribe` and `first-question` spawn a separate whisper environment (`large-v3-turbo` / `large-v3`, no CPU fallback). `first-question` reaches into the worker module by file path and replaces one of its internal functions.
- Three places decide "already done" for a WAV or clip: stage 2's skip rule, `transcribe`'s skip rule (shared code), and the stage page's per-interviewee pills (which only check that files exist).
- Stage 1's Resolve-text export and stage 1b's whisper-text adoption both write the same `<stem>.md` and `<clip>.srt`; and the coverage check (stage 4) and the swap check (stage 3) both exist only to compare Resolve's transcript with something else, which stage 1b makes unnecessary for new interviews.
- The stage page's "Word timings" row and the first step of Prep run the same command; Language assist runs both after Prep and as its own row.
- Spoken-length estimates for the 60 s block limit live in `blocklen` and are re-applied in both `finalize-transcript` and `resplit-draft --report`.
- The `transcribe` corpus path and the interview path both write word sidecars through one writer, but the `.md` they produce differs: `transcribe` writes a full transcript with frontmatter and refs, stage 1b writes a bare raw text.
- Two OpenCC passes: the house conversion (Simplified to Traditional, `s2twp` plus `台`) at transcription time, and the reverse one-character fold table (Traditional to Simplified) for comparison in other sections; `repair-words` exists only to fix files written before the first was corrected.
- `webtheme.py` exists twice (this repo and `Editing\Launcher`, byte-identical); the stage page loads the Launcher copy.
- `multicam_transcripts.py` keeps two functions (a bin lister and a scan preview) that no file in this part calls; its description names a `transcripts_web.py` page that is not in this part.
- Montage-corpus translation uses a local Ollama model (`translate-corpus`), while the interview translation is done by Claude during Prep, and Timeline Cards has its own translation caches (which `repair-words` re-keys): three translation routes.
- The four top-level forwarding scripts duplicate the `pipeline.py` commands of the same name.

## Claims the code does not back

- `pipeline_web.py`'s own description and the Propose row say "name up to 15 overarching categories"; the PROPOSE prompt actually sent to Claude says "AT MOST 25 themes".
- The Language assist row says it does "phrase alignment + word links + gloss"; this part only launches a Node script and cannot confirm what it does.
- The stage page's row numbering (1 to 11, then 10 again for Conform) does not match the stage numbers used by `pipeline.py` and the module descriptions (stage 3 swap check, stage 4 coverage, stage 5 finalize, stage 6 extract, stage 9 canvas, stage 10 timeline); `pipeline_web.py`'s own description numbers Prep as 5 and Extract as 6.
- `pipeline_web.py`'s description says Prep produces "paragraphed bilingual _Transcript.md"; the code only sends a prompt naming an external skill. What Prep produces is decided outside this repo.
- `finalize_transcript.py`'s description says it refuses to overwrite an existing final file "unless it was also generated draft-equal"; the code refuses whenever the file exists.
- `check_transcript_coverage.py`'s `--fps` help says "(default 25)"; the default is 29.97 (30000/1001).
- `whisper_corpus.py`'s `--opencc` help says "s2tw (the default -- Taiwan variants, 台灣), s2twp (variants plus Taiwan phrasing, 臺灣)"; the default is `s2twp`, and with the default `台` step both write `台灣`.
- `whisper_corpus.py` reports a clip whose `.md` was "unchanged" also as written (it counts in both lists); the final "transcribed" count includes them.
- `whisper_transcripts.py` says "It deletes nothing" and that a second run never overwrites the first backup: true for the backup, but on a second adoption (for example with `--force`) the current `<stem>.md` and `<clip>.srt` are overwritten with no new backup, so any hand edits made after the first adoption are lost.
- `mono_fold.py` says programmatic callers fold only "a WAV it rendered minutes ago" and therefore keep no original; stage 2's library mode also folds WAVs rendered at any earlier time, keeping no stereo original.
- `preview_video.py` says it works on every `<name> Multicam.wav`; it takes every `.wav` in the interviewee folders, whatever its name, and fails those that are not multicams in the library.
- `preview_video.py` says the result lines up "to within a frame"; the after-encode check only reports the offset and flags it when over 1/30 s; it does not stop or redo a preview that is off.
- `multicam_transcripts.py` says `scan()`, `export()` and `list_bins()` back a `transcripts_web.py` page; no such page is in this part, and the stage page runs the command line instead.
- `resolve_multicam_whisper.py` says a clip is skipped "only when BOTH files are there and the WAV still hashes to what the sidecar says"; with `--no-words` the `.srt` alone decides.
- `qwen_translate.py` says blocks that already carry a Latin line "are left alone"; when any block in the file is translated, every other block is re-emitted too, with several English lines joined into one and the order normalised to headings, English, Mandarin, ref.
- The `--delete-timelines` help says it removes "the timelines this script created"; it removes every timeline whose name ends ` [xscript]`, whoever made it.

## Could not determine

- What the "canvas-sorter" skill (PREP, PROPOSE, ASSIGN phases) actually does: it lives in the user's Claude configuration, outside this repo, and decides the shape of every `_Transcript.md`, including whether translation is done there.
- How `editor\scripts\assist-links.ts` reaches Claude (command-line sign-in or an API key), what its budget is, and exactly what it writes: another section's code.
- Whether the Python the stage page runs under (`sys.executable`) has both `psycopg2` and a working CUDA faster-whisper, which the Word timings and Prep stages need together in one process; the modules themselves say the whisper environment has no `psycopg2`.
- What the project-library reader (`LibraryTokens.facts`, `LibraryReader.multicam_angles` and friends), the interviewee-colours step, the canvas build, the canvas-to-timeline conform and the Resolve readiness check do in detail: other sections.
- Whether the `MontagePipeline` sibling folder exists on every machine that runs stage 2; without it stage 2 silently writes no word sidecar.
- The exact Simplified/Traditional pairs in `zh_fold_table.py`: only its start, end and count were read.
- Whether the four model identifiers on the stage page (`claude-fable-5`, `claude-opus-4-8`, `claude-sonnet-5`, `claude-haiku-4-5-20251001`) are still accepted by the installed `claude` program; they are a fixed list in the page.
