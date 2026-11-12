# B-roll: the clip indexing pipeline and the search evaluation tools

Terms used throughout:

- **Indexer**: the operator-run command-line program (`broll-index`, plus a set of standalone scripts) that walks folders of video files, analyses each clip and writes the b-roll search database.
- **Share**: a named folder of source footage configured in the indexer's `config.yaml` (for example a YouTube-download archive, or one project's own shoot). Every clip row in the database is stored under a share name plus a path relative to that share's root.
- **Clip / video row**: one source video file known to the database.
- **Proxy / preview**: the small H.264 MP4 copy of a clip the indexer makes for browser playback (and, in later phases, for Resolve to link as a proxy).
- **Contact sheet**: a single JPEG tiling up to 9 stills from a clip in a 3x3 grid, each with its timestamp burned in, which is what gets sent to a vision model.
- **Segment**: one described shot within a clip (start/end seconds, description, objects, setting, on-screen text, camera details), produced by the vision model.
- **Backend**: which vision model describes clips: `local` (Qwen3-VL run on the operator's GPU through a downloaded llama.cpp server) or `anthropic` (Claude through the Anthropic Messages API, paid per call).
- **Data root**: the folder (`data_root`) where the indexer writes proxies, posters, sprites, contact sheets, transcripts and logs.

## Configuration file (`config.yaml`) and environment variables

(source: indexer/broll_index/config.py, indexer/config.example.yaml)

- The config file path is given with `--config` on every `broll-index` command; default `config.yaml` in the current folder. It is YAML; an empty file is treated as empty settings.
- Every refusal about a missing required setting names the key and the environment variable that would supply it.
- **`data_root`** (required; environment variable `BROLL_DATA_ROOT` wins over the file). Missing: refused with "data_root is required (or set BROLL_DATA_ROOT). It is where frames, proxies, posters, sprites and transcripts are written - tens of GB, so it is never guessed."
- **`db.mode`**: `sqlite` (default; the indexer writes the search database file directly) or `api` (the indexer posts results to the web app's ingest API over HTTP). Any other value: refused "unknown db.mode".
  - `db.path` (env `BROLL_DB_PATH` wins): required when mode is `sqlite`; refused by name if absent.
  - `db.url` (env `BROLL_DB_URL` wins): required when mode is `api`; refused by name if absent.
  - `db.token` (env `BROLL_DB_TOKEN` wins): the bearer token sent to the ingest API. No default (empty).
  - In `api` mode the indexer also keeps a local bookkeeping database at `<data_root>/indexer_local_state.db` (see "Ingest API storage mode").
- **`model`**: the Claude model alias used by the `anthropic` backend when no `--model` is given. Default `sonnet`.
- **`taxonomy_model`**: the Claude model used by `taxonomy propose`. Default `sonnet`.
- **`shares`**: a map of share name to either a bare root path string, or an object with:
  - `root` (required): the folder on this machine.
  - `description`: free text, default empty.
  - `source`: `originals` (default; the downloaded or camera file is the archive copy, and an editor's `Proxy` folder beside it is skipped as a redundant encode) or `proxies` (the shoot's own `Proxy` `.mov` files are what is archived and indexed, and the camera originals are not indexed). Any other value is refused: "share X: source must be one of originals, proxies".
  - `max_duration_s`: clips longer than this many seconds are not indexed (see the probe stage). Default: no cap.
  - `exclude`: a list of folder patterns, relative to the share root, never walked. Patterns are shell-style wildcards matched against each folder's forward-slash relative path; `*` crosses folder separators, so `*/AE` also matches `Nuclear/B-roll/AE`. A matching folder prunes its whole subtree. A bare string instead of a list is refused: "exclude must be a list, not a string". Leading and trailing slashes are stripped.
  - `index` (default true): false means every local stage still runs (probe, proxy, poster, sprite, transcript) but no contact sheets are built and no vision model is ever called for this share; its clips rest in status `organised`.
  - `transcribe` (default true): false means speech transcription never runs for this share.
  - `archive_name`: the folder name the share's clips get on the NAS archive when it should differ from the share key; empty means use the key. Changing it after a copy moves nothing (the next archive build copies everything again under the new name).
- **`anthropic`** section (used only by the `anthropic` backend and by `taxonomy propose`):
  - Setting `anthropic.api_key`, `anthropic.key` or `anthropic.token` in the file is refused: "anthropic.<key> must not be set in config.yaml - the API key belongs in the environment ... or in a file named by anthropic.api_key_file".
  - `api_key_env`: name of the environment variable holding the key. Default `ANTHROPIC_API_KEY`.
  - `api_key_file`: path of a file holding the key. Default none.
  - `max_tokens`: default 8000 output tokens per call.
  - `timeout_s`: default 600 seconds per call.
  - `max_retries`: default 5 (retries on rate limit / overload / server errors only).
  - `retry_base_delay_s`: default 2.0; `retry_max_delay_s`: default 60.0.
  - `max_concurrency`: default 4 API calls in flight at once.
  - `thinking`: `disabled` (default) or `adaptive`; anything else refused.
- **`sampling`** section (how stills are chosen for contact sheets):
  - `scene_threshold`: default 0.3 (ffmpeg scene-change score above which a frame is a cut).
  - `max_gap_s`: default 4.0 seconds; no two sampled stills are further apart than this.
  - `frames_per_call`: default 36 stills per Claude call (so 4 contact sheets per call).
  - `max_sheets_per_video`: default 0 (no cap). When positive, a long clip's contact sheets are evenly thinned to this many before sending to Claude, so the whole duration is still covered.
- **`whisper`** section (local speech transcription):
  - `enabled`: default true.
  - `python` (env `CCSYNC_WHISPER_PYTHON` wins): the Python executable of a separate faster-whisper environment. No default.
  - `script` (env `CCSYNC_WHISPER_SCRIPT` wins): the transcription helper script. No default.
  - `model`: default `large-v3-turbo`.
  - `model_dir` (env `CCSYNC_WHISPER_MODEL_DIR` wins): where whisper models are cached; empty means the helper's own default.
  - `language`: default none (auto-detect); set to force a language such as `zh`.
  - `max_gap_s`: default 1.0; `max_duration_s`: default 30.0 (how transcript cues are merged, see "Transcription").
  - When `transcribe` is asked for by name and `python` or `script` is unset, refused: "whisper.python and whisper.script is not set. Transcription shells out to a faster-whisper environment: build one with broll/indexer/tools/make_whisper_env.ps1 (or .sh) and set the keys in config.yaml, or export CCSYNC_WHISPER_PYTHON / CCSYNC_WHISPER_SCRIPT. See docs/INDEXERS.md." If set but not a file: "whisper.python points at <path>, which is not a file".
- **`embedding`** section (semantic search vectors):
  - `enabled`: default true.
  - `model`: default `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.
  - `batch_size`: default 64.
  - `cache_dir` (env `BROLL_MODEL_CACHE`, then `FASTEMBED_CACHE_PATH`, win): where the embedding model weights are kept; empty means the library default.
- **`indexer`** section (which vision backend):
  - `backend`: `local` or `anthropic`; anything else refused. Default: if the file has no `indexer.backend` but does have an `anthropic:` section, `anthropic`; otherwise `local`.
  - `model_tier`: `good` (Qwen3-VL 4B, 8 GB VRAM) or `best` (Qwen3-VL 8B, 12 GB VRAM); anything else refused. Default `good`. Whether it was written explicitly is remembered (decides whether the dashboard is asked, see "Model tier resolution").
  - `local_cache_dir` (env `BROLL_LOCAL_CACHE_DIR` wins): where the llama.cpp runtime and model weights are downloaded. Empty means a per-OS default (see "Local model runtime").
  - `llama_server_path` (env `BROLL_LLAMA_SERVER_PATH` wins): use an already-installed `llama-server` instead of downloading one.
  - `dashboard_url` (env `BROLL_DASHBOARD_URL` wins): where to ask the dashboard for the site's model tier.
  - `frames_per_call`: default 9 stills per local model call.
  - `gpu_layers`: default 99 (llama.cpp `-ngl`, offload all layers).
  - `merge_similar_segments`: default true; merges adjacent near-identical shots the local model over-splits.

## The `broll-index` command line

(source: indexer/broll_index/cli.py)

- Global flag `--config <path>` (default `config.yaml`). A subcommand is required.
- **`scan --share <name> --root <folder> [--inbox <subfolder>] [--rehash]`**: walks the folder and adds or updates clip rows (see "Scanning"). The share's `source` mode and `exclude` patterns come from the config, never from a flag; an unknown share is scanned as `originals` with no excludes. Prints "scan: upserted N video(s) from <root> (share=<name>[, source=proxies][, K exclude pattern(s)])".
  - `--rehash`: re-read every known file's head and tail instead of trusting its stored hash when the size has not changed.
- **`run [--model haiku|sonnet|fable] [--limit N] [--stages <list>] [--tier good|best]`**: drains the work queue through the stages (see "The indexing pipeline"). `--stages` is a comma-separated subset of `probe,proxy,frames,transcribe,claude,embed`; default all. `--limit` stops after N clips. `--tier` applies only to the local backend and overrides every other tier source for this run. Before running it prints either "backend: local - <tier label> (<VRAM note>)" or the Anthropic auth description (see "Claude API calls"). Ends with "run: processed N video(s)".
- **`models pull [--tier good|best] [--force]`**: downloads the pinned llama.cpp runtime and one tier's model weights into the local cache (see "Local model runtime"). Safe to re-run: a file already present with the right checksum is not fetched again. Refuses (exit 2) an unknown tier, or a tier the detected GPU is too small for unless `--force`. Prints the runtime, weights and vision-projector file paths.
- **`doctor`**: prints a diagnostic report for the local backend: configured backend; detected GPU name and memory ("unified memory" on Apple Silicon, "VRAM" elsewhere) or "GPU: none detected"; recommended tier or "none - search-only, or backend: anthropic"; the resolved tier; the cache folder; whether `llama-server` is present ("NOT downloaded yet - run `broll-index models pull`") and the version it reports; whether the weights and projector files are present; and the dashboard manifest URL or "(none configured or derivable from db.url)".
- **`transcribe [--limit N]`**: shorthand for `run --stages transcribe`. If whisper is enabled but not configured it refuses with the whisper message above (exit 2). Note: because the pipeline only ingests existing `.srt` files in this stage (see "Transcription"), this command never runs whisper itself.
- **`taxonomy propose [--out <file>]`**: asks Claude to cluster the indexed themes into categories and writes a Markdown proposal (default `taxonomy_proposal.md`).
- **`taxonomy apply <taxonomy_file>`**: loads an approved category file into the database; prints "taxonomy apply: loaded N categories into the DB".
- **`taxonomy assign <rules_file> [--dry-run] [--reassign]`**: gives each indexed clip one category from keyword rules; prints totals and a per-category table (clips filed versus clips matching). `--reassign` also re-files clips that already have a category (help text warns it moves files in the shared archive and breaks stored archive paths).
- **`origins [--verify] [--dry-run]`**: records where each clip's true original file lives; `--verify` checks each path on disk now.
- **`sort [--dry-run]`**: moves indexed clips from the inbox folder into their category folder; prints each move "moved: A -> B" (or "would move").
- **`migrate`**: applies pending schema migrations to the configured SQLite database and prints a report. Refused (exit 2) when `db.mode` is `api`: "migrate requires db.mode 'sqlite' - the ingest API owns its own database's schema...".
- **`rebase --to-share <name> --root <folder> [--apply] [--prune-duplicates] [--out <file>] [--verbose]`**: re-points the index at a new storage folder by matching content hashes. Dry run unless `--apply`. `--apply` with `db.mode: api` is refused (exit 2). Writes a report (default `rebase_report.md`) and prints the summary (or full report with `--verbose`); a dry run ends "rebase: DRY RUN - nothing written. Re-run with --apply to commit."
- **`duplicates [--verify/--no-verify] [--apply] [--out <file>] [--verbose]`**: finds clips that already exist elsewhere in the index. `--verify` is on by default. With `--no-verify` it prints a four-line warning starting "!!! WARNING: --no-verify skips whole-file hash confirmation." and stating a false match "can PERMANENTLY LOSE FOOTAGE". The report path defaults to a git-ignored private folder (see "Site data paths") and its parent folder is created. Dry run unless `--apply`.
- **`export-manifest --out <file> [--format list|robocopy|rsync]`**: writes the list of files to copy to the NAS (every clip except confirmed duplicates). Clips in a share not in the config are skipped with "export-manifest: N video(s) skipped - unknown share (not in config)" on stderr.

## The indexing pipeline (`broll-index run`)

(source: indexer/broll_index/pipeline.py)

- **Stage order**: probe, proxy, frames, transcribe, claude (the vision description, whichever backend), embed. Only requested stages run.
- **Clip statuses** used by the pipeline: `discovered` (found by scan), `probed`, `proxied`, `indexed` (described), `organised` (resting: share opted out of description), `skipped` (parked, with a reason in the error text), `error` (with a message), plus `sorted` and `excluded` set elsewhere.
- **Which clips are worked on**: rows with status `discovered`, `probed`, `proxied` or `organised`. When `transcribe` or `embed` is among the requested stages, `indexed`, `sorted` and `skipped` rows are also included, so an archive indexed before those stages existed can still pick them up. Rows marked as confirmed duplicates of another row are never returned.
- **Prerequisites**: probe needs `discovered`; proxy needs `probed`; frames and claude need `proxied`. Transcribe and embed run whatever the status.
- Before any work, every run records where each share's footage lives (see "Share root reporting"), best effort.
- **Reopening opted-out clips**: a clip at `organised` whose share is now `index: true` is put back to `proxied` before its stages run, so it gets contact sheets and a description.
- **Probe stage**: reads duration, frame rate, width, height, codec, shot date (first 10 characters of the `creation_time` tag), frame count, start timecode and bitrate (see "Media tools").
  - No video stream: status `skipped`, error "audio-only (no video stream) - transcript indexed, no visuals". Its speech can still be transcribed.
  - Video stream but no duration: status `skipped`, error "no duration in the container - nothing here can be sampled; remux it and re-scan".
  - Longer than the share's `max_duration_s`: status `skipped`, error "longer than <cap>s cap (<duration>s) - not indexed". Such a clip still belongs in the copy manifest.
  - Otherwise status `probed`.
- **Proxy stage**: writes `<data_root>/proxies/<id>.mp4` (see "Media tools" for the encode), then a sprite sheet `<data_root>/sprites/<id>.jpg` and a poster `<data_root>/posters/<id>.jpg`, both cut from the proxy (or from the original if the proxy is missing or empty). Stores the sprite's measured geometry on the row and sets `proxied`.
- **Frames stage** (contact sheets):
  - Skipped if `<data_root>/sheets/<id>/_complete` already exists.
  - Works from the local proxy if it exists and is non-empty, else the original.
  - Finds scene-change timestamps, fills gaps so no two samples are more than `max_gap_s` apart (and a sample sits at or near 0 and near the end), extracts one still per timestamp into `sheets/<id>/frames/frame_NNNN.jpg`, and tiles them 9 per sheet into `sheet_0001.jpg`, `sheet_0002.jpg`, ...
  - No stills could be extracted: fails the clip with "frames failed: no frames could be extracted - unreadable or truncated media".
  - Writes `sheets/<id>/frames.json` (the timestamps actually sampled and the sheet paths) then the `_complete` marker.
- **Share with `index: false`**: at the frames or claude stage the clip is set to `organised` (logged "organised after the proxy; no contact sheets, no model call") and the frames and claude stages are skipped; transcribe and embed still run.
- **Share with `transcribe: false`**: the transcribe stage is skipped for its clips.
- **Over-length clips** (`skipped` with a codec and a duration) are never transcribed; audio-only `skipped` clips are.
- **Transcribe stage inside `run`** only ingests an `.srt` that already exists under `<data_root>/transcripts/<id>/` (written by the batch transcription script); if none exists it does nothing. See "Transcription".
- **Claude (describe) stage**: see "Vision description: Anthropic backend" and "Vision description: local backend".
  - Anthropic: needs `sheets/<id>/frames.json`, else fails "no contact sheets found - run the 'frames' stage first". Sheets are capped by `max_sheets_per_video`, grouped `frames_per_call / 9` sheets per call (minimum 1), each call gets the prompt plus the current category list, and all windows' results are merged and written as one index result (themes, quality flags, category hint, segments, model name). Status becomes `indexed`.
  - Every model call appends one line to `<data_root>/usage.jsonl` (clip id, relative path, duration, model, number of sheets or frames, and the token usage). Failure to write is ignored.
- **Embed stage**: see "Search enrichment".
- **Error handling**:
  - A probe, proxy or frames failure sets the clip to `error` with "<stage> failed: <message>" and stops that clip.
  - A transcribe or embed failure is logged and never errors the clip.
  - A clip whose share is not in the config is set to `error`: "unknown share '<name>' (not in config)".
  - A claude-stage failure whose message looks account-wide (out of credit, bad key, rate limit, and for the local backend a dead or refused model server) aborts the whole run, leaves that clip's status untouched, and logs either "rate limit reached after N video(s) this run[; resets <hint>]. The queue is untouched - re-run to pick up where it stopped." or "aborting run after N video(s): <message>. The queue is unchanged - fix the cause and re-run to resume." Any other claude-stage failure sets the clip to `error`.
- The run returns the number of clips attempted.

## Media tools: probing, proxies, sprites, posters, stills, contact sheets

(source: indexer/broll_index/ffmpeg_tools.py)

- Requires `ffmpeg` and `ffprobe` on the PATH. All tool output is read as UTF-8 with bad bytes replaced (so CJK file names do not crash a run on a non-UTF-8 Windows locale).
- **Unreadable files**: ffprobe failure raises "ffprobe failed on <name>: <first 200 chars of error>" plus " - file is truncated or incompletely downloaded" when the error says the moov atom is missing, or " - file is not valid media" for invalid data.
- **Probe values**: duration from the container, else the video stream; frame rate from the average rate, else the base rate; bitrate from the video stream, else the container; frame count is the container's claimed count only if it is within max(1 frame, 1%) of duration x frame rate (otherwise left unknown); start timecode as the file prints it (container tag first, then a timecode track, then any stream tag).
- **Drop-frame timecode rule**: for a proxy, a colon-separated timecode at 29.97 or 59.94 fps is rewritten with a semicolon before the frame field (drop-frame) unless the file has a QuickTime timecode track (`tmcd`), whose colon is a genuine non-drop timecode. A timecode already containing `;`, or at another rate, is kept.
- **NVIDIA encoder detection**: checks once per process whether ffmpeg lists `h264_nvenc`.
- **Proxy encode**:
  - Height 1080 (never upscaled; height forced even), H.264. With NVIDIA: `h264_nvenc`, preset p5, variable bitrate, constant quality 25. Without: `libx264`, preset medium, CRF 23.
  - Keyframe every second of frames (GOP = rounded frame rate) when the rate is known.
  - Always 8-bit 4:2:0 (`yuv420p`), so 10-bit camera sources play in a browser.
  - The source's timecode is carried over (with the drop-frame rule above).
  - AAC audio at 128 kbps; `faststart` for streaming.
  - If the NVIDIA encode fails outright it is redone with libx264. A libx264 failure raises "ffmpeg libx264 exited N: <first 300 chars of error>".
  - **Verification** (on by default): the proxy is decoded end to end and fails on any decode error; its video packet count must exactly equal the source's (counted only if the proxy count is known; the source count is remembered per file version, up to 512 files, and a failed count is not remembered); its duration must be at least 97% of the source's. On failure after an NVIDIA encode, it is re-encoded with libx264 and checked again; still bad raises "proxy unusable after libx264 fallback (<reason>)" where the reason is "N decode errors", "X frames of the source's Y" or "truncated: Xs of Ys".
- **Sprite sheet** (hover-scrub strip): one frame every 2 seconds, 240 px wide cells, 10 columns, JPEG quality 4. At most 240 cells: a longer clip's interval is stretched to fit. The written sheet is measured and the stored geometry is columns, cell count, interval, and cell width and height (unknown if measurement fails).
- **Poster**: one frame at 10% of the duration, 640 px wide, JPEG.
- **Scene detection**: ffmpeg `select` on scene score above the threshold; timestamps de-duplicated and sorted.
- **Still extraction**: one JPEG per timestamp, at most 960 px wide (never upscaled), seeking accurately; timestamps are clamped to 0.05 s before the end. A seek that produces nothing is silently dropped rather than failing.
- **Contact sheets**: up to 9 stills per sheet in a 3x3 grid, cells 384 px wide with height from the clip's aspect ratio (16:9 if unknown), each with its HH:MM:SS timestamp burned in at the bottom-left (white 18 pt text on a half-transparent black box). Font: Arial on Windows and macOS, DejaVu Sans Bold on Linux, or ffmpeg's default if none found. A single still makes a one-cell sheet.

## Vision description: Anthropic (Claude API) backend

(source: indexer/broll_index/claude_client.py, indexer/broll_index/contract.py, indexer/broll_index/prompts/index_clip_v6.md)

- Selected when `indexer.backend` is `anthropic`. Each call sends the window's contact sheets as base64 images (JPEG, PNG, WebP or GIF accepted; any other file type fails "unsupported contact-sheet image type"), images first, then the prompt text.
- **Model names** (`--model` or `model:`): `haiku` = `claude-haiku-4-5`, `sonnet` = `claude-sonnet-5`, `opus` = `claude-opus-5`, `fable` = `claude-fable-5`. Any other text is sent to the API unchanged, so an exact model id can be pinned. (The `run --model` flag only accepts `haiku`, `sonnet`, `fable`; `opus` is reachable only through `model:` in the config.)
- **API key**: from the environment variable named by `api_key_env` (default `ANTHROPIC_API_KEY`), else the first non-blank, non-`#` line of `api_key_file`. Errors (all treated as account-wide, so the run stops with the queue intact):
  - unreadable key file: "authentication_error: cannot read anthropic.api_key_file <path>: <reason>";
  - key file with no key: "authentication_error: anthropic.api_key_file <path> contains no key";
  - no key at all: "authentication_error: no Anthropic API key. Set <VAR> in the environment, or set anthropic.api_key_file in config.yaml to a file holding one. The key itself must never be written into config.yaml."
  - SDK missing: "the `anthropic` SDK is not installed - `pip install anthropic`".
- **Run banner**: "auth: Anthropic API key from $ANTHROPIC_API_KEY - billing this organisation's API credit", or "...from anthropic.api_key_file (<path>)...", or "auth: NO API KEY - <message>".
- **Thinking**: `adaptive` sends adaptive thinking. `disabled` sends thinking off, except for `claude-fable-5` and `claude-mythos-5`, which always think, where the setting is left out of the request.
- **Concurrency ceiling**: at most `max_concurrency` (default 4) calls in flight across the whole process; the parallel runner can set it.
- **Retries** (the SDK's own retries are turned off): HTTP 408, 409, 425, 429, 500, 502, 503, 504, 529 and connection/timeout errors are retried up to `max_retries` times. The wait is the server's `retry-after` if sent (capped at `retry_max_delay_s`), else base x 2^attempt capped at the max, with random jitter of 50 to 100%. Each retry logs "claude: API error N: ... - retry k/n in Xs". After the last retry it fails with "... (gave up after N retries)", which counts as account-wide. Any other API error fails at once with "API error <status>: <type>: <message>".
- **Response handling**:
  - A model refusal (stop reason `refusal`) fails only that clip: "claude declined this clip (stop_reason=refusal)".
  - Hitting `max_tokens` logs a warning ("the JSON is probably truncated; raise anthropic.max_tokens if this repeats").
  - Code fences around the JSON are removed; if the text is not valid JSON, the first complete JSON object in it is used and anything after it ignored.
  - Invalid output gets exactly one fresh call; a second failure fails the clip with "claude returned invalid JSON after one retry: <reason>".
- **Cost estimate**: each call's cost is estimated locally (never billed figures) from per-million-token prices: Haiku 4.5 $1 in / $5 out, Sonnet 5 $3 / $15, Opus 5 $5 / $25, Fable 5 $10 / $50; cache writes count 1.25x input, cache reads 0.1x. Unknown models are estimated at $0. The estimate goes into `usage.jsonl` with token counts and call duration.
- **Account-wide failure classification** (stop the run, do not mark the clip): message contains "credit balance is too low", "insufficient credit", "authentication_error", "invalid api key", "permission_error", "account is not authorized"; or a rate-limit sign ("session limit", "rate_limit_error", "rate limit", "usage limit", "quota exceeded", "too many requests", "overloaded", or 429 in the shapes "error 429", "status 429", "HTTP 429", "429 too many requests"; a bare "429" elsewhere, such as in a file name, does not count); or a 400 invalid-request error mentioning "thinking" or "max_tokens" (a config mistake every call would repeat).
- **Reset-time hint**: a limit message containing "resets <time>" is parsed; the wait is the time until that local clock time (tomorrow if already passed) plus 60 seconds, unless that is more than 6 hours away, in which case the hint is ignored. (Used by the queue runner.)
- **Prompt (version 6)**: the prompt names each attached sheet by file name in order, states that burned-in timecodes are absolute from the clip start, and demands strictly visible facts (with worked examples about brake lights, tunnel lamps, congestion), one segment per distinct shot ("when in doubt, split"), terse noun-phrase descriptions of about 8 to 20 words, an `objects` list with synonyms and broader terms, `setting`, `motion`, verbatim `onscreen_text` in the original script joined with " | " and an English `onscreen_text_en`, proper nouns folded into objects in both scripts, clip-level `themes`, one `category_hint` slug from the current category list (or null; "(no taxonomy defined yet)" when there are no categories), and `quality_flags` from a fixed list. Output must be strict JSON.
- **Output contract and repair** (applies to both backends):
  - Required top-level keys: `themes`, `category_hint`, `quality_flags`, `segments`; themes, flags and segments must be lists. Missing ones fail the window.
  - Quality flags outside `shaky`, `soft_focus`, `overexposed`, `underexposed`, `noisy`, `rolling_shutter` are silently dropped.
  - Each segment must have `t_start`, `t_end`, `description`, `objects`, `setting`, `motion`. A segment whose start or end is null or not a number is dropped (warning logged); if every segment is dropped the window fails "all N segment(s) had a null or non-numeric t_start/t_end". Null text fields become empty; a non-list `objects` becomes empty.
  - On-screen text given as a list is joined with " | "; missing becomes empty.
  - "No visual content" labels are normalised to exactly `newsreader`, `title card`, `black frame`, `colour bars`, `station ident`, with aliases (news reader, news anchor, anchor, presenter, talking head to newsreader; color bars, test pattern to colour bars; titles, title cards to title card; blank frame to black frame; channel ident, ident to station ident).
  - Windows are merged: themes and flags are unioned in first-seen order, segments concatenated, the first non-empty category hint wins.

## Vision description: local (Qwen3-VL) backend

(source: indexer/broll_index/local_vlm.py, indexer/broll_index/compact_format.py, indexer/broll_index/prompts/index_clip_v7_compact.md)

- Selected when `indexer.backend` is `local` (the default for a new config). Uses the individual stills from the frames stage (not the contact sheets), read back from `frames.json`; a still whose file is missing is skipped. No stills: the clip fails "no usable frames found - run the 'frames' stage first"; no `frames.json`: "no frames metadata found at <path> - run the 'frames' stage first".
- **First use downloads**: unless `llama_server_path` is set, the pinned llama.cpp runtime is downloaded and unpacked if missing; the tier's weights and vision-projector files are downloaded if missing or wrong (silently, no progress lines). See "Local model runtime".
- **Model server**: starts `llama-server` on a free local port (127.0.0.1 only) with 16,384-token context, `gpu_layers` layers on the GPU, one request slot, no warm-up, minimum 1,024 image tokens per image. Its output is appended to `<data_root>/local_vlm_server.log` with a timestamped command line per start. On Windows it is started in its own process group with no console window (so Ctrl-C in the indexer does not reach it and no black window flashes when run inside the companion).
  - Waits up to 1,200 seconds for `/health` to answer, checking every second. Exits early: "llama-server exited early with code N; see <log>". Never healthy: the server is terminated (killed after 20 s) and "llama-server did not become healthy within 1200s; see <log>".
  - One server per (binary, weights, projector, GPU layers, context) is kept running for the life of the process and reused across clips; a reused server is health-checked (3 s, then one 15 s retry) and replaced if dead. All servers are stopped when the process exits.
- **Per call**: stills are split into windows of about `frames_per_call` (default 9) each, sized evenly so there is no tiny last window. Each call sends the fixed instructions, then a line like `F1=00:00:00 F2=00:00:04 ...`, then each still labelled "F<n> (<timecode>):", then "Answer now: the S lines, then the T line." Sampling temperature 0.1, repeat penalty 1.15, at most 150 output tokens per still, prompt caching on, 900-second timeout.
  - A grammar constrains the answer to between 1 and N lines of the form `S F<a>[-F<b>] | <description> | <objects> | <on-screen text or -> // <English or ->` followed by exactly one `T <themes>` line; frame ids only F1 to Fn; description at most 220 characters, objects 300, each text 300, themes 160.
  - A network failure raises "llama-server call failed: <reason>" (account-wide if it says connection refused).
- **Parsing**: tolerant of stray lines (logged as "tolerated parse issue(s)"), bullets, lowercase, and bare numbers instead of F ids. Objects split on semicolons (also full-width) or, failing that, commas, de-duplicated case-insensitively. "-", "none", "n/a", "null", "no text" and similar mean empty. Segment start and end times are taken from the frame table (the model's own times are never used); `setting` and `motion` are left empty. No S lines at all: retried once, then the clip fails "local vlm returned unparseable output after one retry: ...".
- **Quality flags from pixels** (instead of the model): every still is measured (480 px greyscale). `overexposed` if at least 30% of stills have mean brightness above 200 or at least 25% clipped-white pixels; `underexposed` if at least 30% of non-black stills have mean below 45 (a still with mean under 12 and over 95% dark pixels counts as black, not underexposed); `soft_focus` if the median sharpness score of non-black stills is below 20. A still that cannot be read is skipped.
- **Category by nearest match** (instead of the model): the clip's themes, descriptions and objects are compared with each category's label and description, using the same multilingual embedding model as search (if installed) or a simple word-weighting fallback; the best match is used if its score is at least 0.15, otherwise no category. Only the slug is stored.
- **Merging over-split shots** (`merge_similar_segments`, default on): adjacent segments whose object lists overlap by at least 60% and whose descriptions are at least 75% similar are joined (earliest start, latest end, union of objects, differing on-screen texts joined with " | "). Logged "merged N over-segmented pair(s)".
- The stored model name is `local:qwen3-vl-4b-q4_k_m` or `local:qwen3-vl-8b-q4_k_m`. Each call logs to `usage.jsonl` with cost 0, the tier, and encode/decode times.
- **Account-wide local failures** (stop the run, clip untouched): messages containing "not healthy", "did not become healthy", "exited early", "connection refused", "econnrefused", "failed to start".
- The local backend still requires the frames stage, which also builds contact sheets that this backend never reads, and `sampling.max_sheets_per_video` has no effect on it.

## Local model runtime and model tiers

(source: indexer/broll_index/local_models.py, indexer/broll_index/local_runtime.py, indexer/broll_index/dashboard_site.py)

- **Tiers**:
  - `good`: label "Good", "Qwen3-VL 4B", note "Qwen3-VL 4B: needs an NVIDIA GPU with 8 GB VRAM (or Apple Silicon with 16 GB); ~20 s per clip on an RTX 3080". Weights 2.5 GB plus projector 0.84 GB from Hugging Face (`Qwen/Qwen3-VL-4B-Instruct-GGUF`, pinned revision, Q4_K_M).
  - `best`: label "Best", "Qwen3-VL 8B", note "Qwen3-VL 8B: needs 12 GB VRAM (or Apple Silicon with 24 GB); a little sharper on on-screen text and vocabulary, ~2x slower". Weights 5.0 GB plus projector 1.16 GB.
  - An unknown tier: "unknown model tier X - expected one of good, best".
- **Runtime** (llama.cpp release b10470, pinned):
  - Windows: CUDA 12.4 x64 build (251 MB) plus a separate CUDA runtime archive (391 MB), both unpacked into one folder.
  - macOS: Metal arm64 build (11 MB).
  - Linux: Vulkan x64 build (33 MB), labelled "not benchmarked, no CUDA build in this release".
  - Any other operating system: "unsupported platform for the local backend".
  - If the unpacked folder does not contain `llama-server`: "extracted <label> but llama-server is not where expected ... the release asset's internal layout may have changed". On macOS and Linux the binary is made executable. Once the binary exists it is never re-checked.
- **Cache layout** (default folder: Windows `%LOCALAPPDATA%\ccsync\indexer`, macOS `~/Library/Application Support/ccsync/indexer`, Linux `~/.cache/ccsync/indexer`): `downloads/` (archives), `runtime/llamacpp-b10470-<platform>/`, `models/<tier>/`.
- **Verified downloads**:
  - Every file is checked against a pinned SHA-256. A file already present with the right hash is never fetched again (works offline). A present file with the wrong hash is deleted and fetched again ("failed re-verification, re-downloading").
  - Downloads go to `<file>.part`; a hash mismatch at the end deletes it and fails: "sha256 mismatch downloading <url>: expected X, got Y. Refusing to use this file. Re-run to retry the download."
  - When the server supports byte ranges and the file is at least 16 MB, it is fetched over several parallel connections (default 6; environment variable `CCSYNC_DOWNLOAD_STREAMS`, clamped 1 to 16, a non-number is warned about and ignored), in slices of at least 8 MB. A `<file>.part.json` record of each slice's progress is saved about every 2 seconds, so a killed download resumes slice by slice. A record that does not match the partial file causes both to be deleted and a fresh start.
  - A connection that moves less than 256 KB in 20 seconds (or sends nothing for 20 s) is dropped and reopened; more than 5 stalls in a row fails the slice. Each slice gets 3 attempts with backoff 0.5 s doubling to at most 4 s; later attempts go back to the original URL rather than the redirected one. A server that stops honouring ranges mid-download fails: "<url> stopped honouring Range mid-download (HTTP N)". A failed download keeps its partial for the next run.
  - Without range support, or with one stream, it downloads in one stream, resuming a partial file from its end when possible.
  - Progress goes to stderr as "  <file>: X/Y MB (P%)" at most 4 times a second, with banner lines "fetching <file> (<size>) from <url>", unless a host application supplies its own progress callback (then nothing is printed). The current download speed (averaged over 5 s) is published for a host application to show.
- **GPU detection**: on Apple Silicon Macs, total unified memory (from `sysctl hw.memsize`); elsewhere, the first NVIDIA GPU's name and memory from `nvidia-smi` (10-second timeout). Failure means "no GPU". AMD and Intel GPUs are never detected, even though the Linux runtime could use them.
- **Recommended tier**: `best` if memory is at least 12 GB (24 GB on Apple Silicon), `good` if at least 8 GB (16 GB), otherwise none.
- **Fit check** (only `models pull`; `run` never checks): no GPU: "no GPU detected (<detail>). The local backend needs an NVIDIA GPU (or Apple Silicon); use backend: anthropic, or add --force to try anyway". Too small: "Best needs 12 GB VRAM; this machine reports 10 GB - choose Good or add --force" (for Good: "... - add --force").
- **`llama-server` version** for `doctor`: first line of `--version`, else of `--help`, 10-second timeout each, or unknown.
- **Model tier resolution** (for `run`, `models pull`, `doctor`): the `--tier` flag; else `indexer.model_tier` if written in the config; else the dashboard's site manifest; else `good`.
  - The dashboard address is `indexer.dashboard_url` if set; else, when `db.mode` is `api`, `db.url` with a trailing `/broll/api` or `/api` removed; else none.
  - It requests `GET <dashboard>/api/v1/site` (no credentials, 5-second timeout) and reads `indexer.model_tier`; any failure, non-JSON body, missing key or unknown value means "not set" and is only logged.

## Scanning a share (`broll-index scan`)

(source: indexer/broll_index/scanner.py, indexer/broll_index/hashing.py)

- Walks the share root recursively. Video files are those ending (any case) in `.mov`, `.mp4`, `.mxf`, `.braw`, `.avi`, `.mkv`, `.m4v`. Everything else is ignored.
- Skipped while walking: any file or folder whose name starts with `.`; on Windows also anything with the hidden or system attribute; the data root and everything under it; folders matching the share's `exclude` patterns (matched case-insensitively, whole subtree pruned).
- **Content fingerprint**: a fast hash (xxHash64) of the first 8 MiB, the last 8 MiB and the file size. A file already in the database with the same size keeps its stored fingerprint without being read again, unless `--rehash` is given.
- **Initial status of a newly seen file** (never changed on later scans of a known file):
  - Share `source: originals`: a file inside a folder named `proxy`, `proxies`, `optimized`, `optimised`, `transcode`, `transcodes`, `transcoded`, `lowres` or `low_res` (any depth, any case) is `skipped` (recorded and still copied to the archive, but never indexed); everything else is `discovered`.
  - Share `source: proxies`: a file inside such a folder is `discovered` (it is the archive copy); every other file (the camera original) is `excluded` (recorded only: never indexed and never copied).
- **Inbox flag**: with `--inbox <subfolder>`, files under that subfolder are flagged as in the inbox (used by `sort`); others are flagged as not in the inbox, on every scan.
- A rescan updates only the fingerprint, size and inbox flag of known rows; it never resets their status.
- A scan never removes rows: widening `exclude` leaves already-recorded rows in place (they must be deleted by hand), and a file deleted from disk keeps its row.
- **Whole-file hash** (used by `duplicates`): xxHash64 of the entire file read in 8 MiB chunks.

## Index storage: direct database mode and ingest API mode

(source: indexer/broll_index/storage/base.py, storage/sqlite_backend.py, storage/http_backend.py, storage/__init__.py)

- **Direct mode (`db.mode: sqlite`)**:
  - Opens (creating the parent folder if needed) the SQLite file at `db.path` with foreign keys on. A brand-new, empty database is initialised from `broll/schema.sql` (which sets the latest schema version). An existing older database is not upgraded automatically: that needs `broll-index migrate`.
  - Writing a clip's description replaces all of its segments, themes and quality flags, deletes the vector embeddings of its old segments, sets status `indexed`, records the time and the model name, and stores the category hint. Objects are stored as one comma-separated string.
  - Writing a transcript replaces all of its transcript cues and records the transcription time and language; it never changes the clip's status.
  - Every write that changes searchable text or vectors (description, transcript, keyword normalisation, embeddings, row deletion) also increments a "search generation" counter in the database's `meta` table in the same transaction, which tells the web app's search caches to reload. A database older than migration 010 makes these writes fail (the fix is `migrate`).
  - Deleting a clip removes its segments, themes and quality flags too.
  - Recording a sort move changes the relative path, clears the inbox flag and sets status `sorted`.
  - Loading categories inserts new ones and updates the label and description of existing slugs; it never deletes categories.
  - Share root reporting writes the `share_roots` table directly (insert or update, never delete).
- **Ingest API mode (`db.mode: api`)**:
  - Every request carries the header `X-Ingest-Token: <db.token>`.
  - All reads (which clips are waiting, which are sortable, themes, segments) come from a local copy kept at `<data_root>/indexer_local_state.db`, which mirrors every write. Categories are the exception: they are fetched with `GET <db.url>/categories`.
  - Adding or updating a clip: written locally, then `POST <db.url>/ingest/video` with share, relative path and the changed fields (30-second timeout). The id the server returns is remembered locally (in a table mapping local id to server id) because the two id spaces differ.
  - Writing a description: written locally, then `POST <db.url>/ingest/index` with the server id (0 if unknown), the share and relative path, themes, flags, category hint and segments (60-second timeout).
  - Recording a sort move: `POST <db.url>/ingest/moved` with the clip's reference taken before the rename and `new_rel_path` (30-second timeout).
  - Share root reporting: `POST <db.url>/ingest/shares` (30-second timeout).
  - Any HTTP error status aborts the operation with the HTTP error.
  - **Not supported over the API** (written to the local copy only, then an error is raised):
    - transcripts: "writing transcripts is not supported over the ingest API - run the 'transcribe' stage against the co-located sqlite backend instead...";
    - keyword normalisation and embeddings: "writing search_norm is not supported over the ingest API..." / "writing embeddings is not supported...";
    - category loading: "SPEC.md's ingest contract has no endpoint for writing `categories`; `taxonomy apply` only updated the indexer's local shadow db, NOT the web app's canonical database...";
    - deleting clips: "deleting videos is not supported over the ingest API - run rebase against the co-located sqlite backend instead".
  - Because the transcribe and embed stages swallow their own errors, in API mode they log a warning per clip and the server never receives transcripts, keyword normalisation or embeddings; the local copy records the transcript as done, so it is not retried.

## Share root reporting

(source: indexer/broll_index/share_push.py)

- At the start of every `run` (and the parallel runners that call it), the list of configured shares (name, root folder, `source` mode, description, whether indexed) is written to the database's share-roots record, so the web app can later resolve where each clip's original lives.
- Best effort: if it fails, a warning is logged ("could not push share roots (...); the origin manifest may not be able to resolve originals at conform time") and the run continues. Shares are never removed from the record.

## Transcription (speech to text)

(source: indexer/broll_index/transcribe.py, indexer/broll_index/transcript_quality.py, indexer/broll_index/pipeline.py)

- Runs an external faster-whisper helper (`whisper.python` running `whisper.script`) with arguments `<source> -o <out_dir> -m <model> [-l <language>]`, 2-hour timeout. When `whisper.model_dir` is set, the helper is given `HF_HOME`, `HUGGINGFACE_HUB_CACHE` (`<model_dir>/hub`) and `CCSYNC_WHISPER_MODEL_DIR` in its environment. Output goes to `<data_root>/transcripts/<id>/<source name>.srt` (or the newest `.srt` in that folder if the name differs).
  - Helper failure: "whisper exited N: <first 400 chars>"; no output: "whisper produced no .srt in <folder>".
- **Inside `broll-index run`** the stage never runs whisper: it only reads an existing `.srt` (written by the batch transcription script) and does nothing if there is none. Running whisper from the pipeline itself happens only in code paths that do not pass the "ingest only" switch (none in the CLI).
- Skipped when: the clip already has a transcription time recorded; `whisper.enabled` is false; the share has `transcribe: false`; the clip was parked as over the duration cap; or (when whisper would run) the helper paths are unset or not files.
- **Subtitle parsing**: tolerant of a byte-order mark, Windows line endings and a missing final newline; blocks without a timestamp line or without text are dropped.
- **Cue merging**: adjacent cues are joined while the pause between them is at most `max_gap_s` (1.0 s) and the joined passage spans at most `max_duration_s` (30 s).
- **Hallucination filter**:
  - Any merged passage containing a known whisper artefact is dropped: "字幕志愿者", "字幕志願者", "字幕由", "请不吝点赞", "請不吝點贊", "订阅", "訂閱", "打赏", "打賞", "转载请注明", "轉載請註明", "明镜与点点栏目", "amara.org", "subtitles by", "subtitled by", "thanks for watching", "thank you for watching", "please subscribe" (Latin text compared case-insensitively).
  - The remaining transcript is rejected whole if: empty ("empty transcript (no speech detected)"); one line makes up 60% or more of 3 or more lines ("repetition loop: ..."); fewer than 12 characters in total ("too little content"); or the clip is longer than 2 minutes and the transcript averages fewer than 8 characters per minute ("implausibly sparse ... likely noise, not speech").
  - A rejected transcript is stored as "attempted, no cues" so the clip is not transcribed again; the reason is logged.
- Any failure in this stage is logged as a warning and never errors the clip.

## Search enrichment: keyword normalisation and semantic vectors (`embed` stage)

(source: indexer/broll_index/pipeline.py, indexer/broll_index/normalize.py, indexer/broll_index/embed.py)

- Runs for every clip in the work list whatever its status; skipped entirely when `embedding.enabled` is false. Failures are logged and never error the clip.
- **Searchable text** of a segment is its description, objects, setting, on-screen text and English on-screen text joined with spaces; of a transcript cue, its text.
- **Keyword normalisation** (only for rows that do not have it yet): text with no Chinese characters is stored unchanged. Text with Chinese characters becomes the original plus its Traditional (Taiwan) and Simplified conversions, each split into words, de-duplicated and space-joined, so two-character words and either script can be found by keyword search. Needs the optional `jieba` and `opencc` packages; without both, the raw text is stored and a warning is logged once ("search_norm will fall back to raw text"). Written once per clip in one batch, even if the embedding half cannot run.
- **Semantic vectors**: every segment and cue with non-empty text that has no vector yet, or whose vector was made with a different model than `embedding.model`, is embedded with the multilingual MiniLM model (384 numbers, normalised) in batches of `batch_size`. Changing the model in the config therefore re-embeds everything on the next pass. Needs the optional `fastembed` package; without it the stage logs "skipped embedding (fastembed not installed)" (and once: "fastembed is not installed - semantic embeddings are disabled (pip install fastembed to enable this stage)"). The model is downloaded on first use into `embedding.cache_dir`.

## Duplicate detection (`broll-index duplicates`)

(source: indexer/broll_index/duplicates.py)

- Groups all clips sharing the same fast fingerprint (ignoring clips with no fingerprint or already marked as a duplicate).
- **With verification (default)**: each candidate's whole file is hashed (a hash already stored on the row is reused). Only clips whose whole-file hashes match are duplicates. A candidate whose file cannot be found (unknown share, or file gone) is listed as missing and never marked. A candidate that matched the fast fingerprint but not the whole-file hash is listed as a confirmed-distinct collision and never marked.
- **Without verification** (`--no-verify`): the fast fingerprint groups are marked directly.
- **Which copy is kept** (the canonical): highest status in the order sorted > indexed > proxied > probed > discovered > error (others rank as error), then most segments, then lowest id.
- With `--apply`, every other copy gets `duplicate_of` = the canonical id (and its whole-file hash); canonicals get their whole-file hash stored. Duplicate rows are never deleted; they are excluded from the work queue, from the copy manifest and (on the web side) from search. Re-running is safe: marked rows drop out of the candidate pool.
- **Report** (Markdown, written to `--out`): a summary line "N duplicate(s) to mark, N canonical copy/copies kept, N partial-hash collision(s) confirmed distinct (NOT marked), N file(s) missing (not marked) - verification ON" (or "OFF (--no-verify: unconfirmed, risk of data loss)"), a bold warning block when unverified, then sections "Marked duplicate", "Canonical copies kept", "Partial-hash collisions confirmed DISTINCT (NOT marked duplicate)", "Missing source files (NOT marked duplicate)", each listing "[id] share:path".

## Copy manifest (`broll-index export-manifest`)

(source: indexer/broll_index/manifest.py)

- Lists every clip to copy to the NAS: all rows except confirmed duplicates and `excluded` camera originals (both counted as "bytes saved"). Clips in a share not in the config are skipped and counted. File existence is not checked. Clips with any other status (including `skipped`, `error`, `organised`) are included.
- Summary: "N file(s) to copy, N duplicate(s) skipped, N byte(s) saved".
- **Formats**:
  - `list`: one absolute source path per line.
  - `robocopy`: a Windows batch file that refuses to run unless `DEST` is set ("Set DEST to the destination root first, e.g. set DEST=Z:\broll-consolidated"), then one `robocopy "<source folder>" "%DEST%\<share>\<sub folder>" "<file>" ... /R:2 /W:5` line per source folder.
  - `rsync`: one `<share>/<relative path>` per line, for `rsync --files-from`.
  - An unknown format is refused (the CLI only offers the three).

## Schema migration (`broll-index migrate`)

(source: indexer/broll_index/migrate.py)

- Brings an existing SQLite database up to schema version 13, one step at a time: 1 to 2 on-screen text, 2 to 3 transcripts, 3 to 4 hybrid search, 4 to 5 duplicates, 5 to 6 share roots, 6 to 7 archive path, 7 to 8 original path, 8 to 9 sprite geometry, 9 to 10 search generation, 10 to 11 ingest batches, 11 to 12 geometry, 12 to 13 live proxies (see "Database schema").
- Migration scripts are read from `broll/migrations/` first, else the copy bundled inside the indexer package; missing from both: "migration file X not found at repo root (...) or bundled fallback (...)".
- Each step runs in one transaction; a failure rolls that step back: "migration X failed, rolled back: <error>". A step that does not advance the version: "X ran but left user_version at N - it is missing a trailing `PRAGMA user_version = N+1;`". A version with no registered step: "no migration registered to advance user_version N -> N+1".
- Already current: "migrate: database already at user_version N, nothing to do". Empty database: "migrate: database has no schema yet (user_version 0) - this isn't an existing database to upgrade in place. Run any broll-index command against it (e.g. `scan`) to initialize it fresh at the latest schema instead of `migrate`." Success: "migrate: applied <files> (now at user_version 13)".

## Recording where originals live (`broll-index origins`)

(source: indexer/broll_index/origins.py)

- For every clip that is not an `excluded` camera original and whose share is in the config:
  - if an `excluded` row exists in the same share, same folder (ignoring any `proxy` folder level, case-insensitive) and same file name stem (case-insensitive), the original is that row's file (a `proxies` share's camera original);
  - otherwise the clip's own file is its original.
- Writes `original_path` (share root + relative path) and `original_size_bytes` on each clip. Matching uses the database rows only, never the disk, so it works with drives unplugged.
- `--verify`: also checks each path exists right now and stamps `original_verified_at` only on those that do; a missing one is counted, never recorded as gone.
- `--dry-run`: computes and reports without writing.
- Output: "origins: recorded N original path(s) of M row(s); K unresolved" and, with verify, "verified on disk: N   not found right now: M".

## Re-pointing the index at a new folder (`broll-index rebase`)

(source: indexer/broll_index/rebase.py)

- Walks the new root (same rules as scan, without excludes) and computes the fast fingerprint of every video file there.
- For each fingerprint already in the index: the best-indexed row (status rank as in duplicates, then most segments) is pointed at the new share and the alphabetically first matching new path ("rematched", or "already correct" if it already points there); every other row with that fingerprint is "superseded". Extra copies on the new root and files not in the index are listed. Rows with no fingerprint or no match are "not found on the new root" and left untouched.
- `--apply` updates share and relative path of rematched rows; with `--prune-duplicates` it also deletes superseded rows (and their segments, themes, flags). Without `--apply` nothing is written.
- Report (Markdown): "# Rebase report - target share: <share>", a summary "N rematched, N already correct, N duplicate row(s) superseded, N indexed video(s) not found on the new root, N file(s) on the new root not in the index", then sections for rematched ("[id] old -> new"), already correct (count only), "Superseded duplicates (NOT deleted - review these)", "Not found on the new root (left untouched)", "On the new root but not in the index" ("Run `scan` + `run` on the new root to index these.").

## Categories (`broll-index taxonomy propose | apply | assign`)

(source: indexer/broll_index/taxonomy.py, indexer/taxonomy.rules.yaml)

- **propose**: collects every theme in the database with its count, sends one text-only request to Claude (`taxonomy_model`) asking for a two-level slug hierarchy with labels and descriptions, written as Markdown ending in a YAML block, and writes the reply to `--out`. Refused with "no themes indexed yet; run `broll-index run` first" when there are no themes. Uses the Anthropic API whatever `indexer.backend` says.
- **apply**: reads a YAML file that is either a list of categories or `{categories: [...]}`; each must have `slug` and `label` ("taxonomy entry missing keys ..."); anything else: "taxonomy.yaml must be a list of categories, or {categories: [...]}". Inserts or updates them.
- **assign** (rule-based filing, one category per clip):
  - Reads the rules file: `categories` (each with `slug`, `label`, `description`, and `match` patterns), optional `fallback_categories`, optional `default_category`, optional `descriptors` (returned but unused).
  - A pattern ending in `*` matches words starting with it; any other pattern matches a whole word; case-insensitive. A category with no patterns is never chosen by theme matching.
  - Considers clips with status `indexed` that have themes. Clips that already have a category keep it unless `--reassign`.
  - Step 1 measures each category's breadth (how many clips match it at all).
  - Step 2 picks, per clip, the category matching the most of its themes, ties going to the narrower (less broad) category, then slug order.
  - Interviewee rule: if the rules define the category `people/interviewee-broll` and the clip's path is inside a person's folder within a folder named `interview`, `interviews`, `interviewee` or `interviewees` (at least one level below it), the clip goes there when its themes mention interview/talking head/testimony/conversation/speaking, or when no subject matched.
  - Step 3: clips matching nothing are scored against the fallback categories only (same tie-break); still nothing: the default category if one is configured, otherwise left uncategorised.
  - Unless `--dry-run`, writes the chosen category on each clip and loads all categories (subjects, fallbacks, default) into the database.
  - Output: "taxonomy assign: assigned N of M video(s) across K categories (F via the fallback tier, P by the interviewee path prior); X left where they already were; U matched no rule" (or "would assign"), then a table of slug, clips filed, and "(matches N)".
- **The shipped rules file** (`taxonomy.rules.yaml`): see "Bundled config files".

## Sorting inbox clips into category folders (`broll-index sort`)

(source: indexer/broll_index/sorter.py)

- Picks clips that are in the inbox, have a category, and have status `indexed`.
- Destination is `<share root>/<category>/<file name>`; if taken, `_2`, `_3`, ... is added before the extension.
- Same drive (Windows: same drive letter; elsewhere: same device): a rename. Different drive: copy (keeping timestamps), compare sizes, delete the source; a size mismatch deletes the copy and fails "size mismatch copying A -> B, aborting move".
- After a move the clip's path is updated, the inbox flag cleared and status set to `sorted`. Failures set the clip to `error` with "sort failed: <reason>"; an unknown share: "sort failed: unknown share '<name>'". `--dry-run` only lists moves.

## Site data paths

(source: indexer/broll_index/site_data.py)

- Default locations for site-specific files are under a git-ignored `private/` folder at the repository root, resolved from the code's own location rather than the current folder: the queue config `private/broll/indexer/config.queue.yaml` and the duplicates report `private/broll/indexer/duplicates_report.md`. Nothing requires them to exist; a missing file fails naming the full path.

## Record of in-place repairs

(source: indexer/broll_index/inplace_fixes.py)

- A file at the archive root, `.ccsync-inplace-fixes.json`, records archive files that were deliberately rewritten in place (for example a re-encoded 10-bit preview), keyed by forward-slash path relative to the archive root, with a quick fingerprint (SHA-256 of size, first 1 MiB and last 1 MiB), size, time, which tool did it and a note. Written atomically.
- A file counts as "already fixed" only while its current quick fingerprint still equals the recorded one.
- Before any file in the archive is overwritten, it is moved to `<archive root>/.ccsync-replaced/<UTC timestamp>/<relative path>` (with a numeric suffix if that already exists). This trash is never cleaned automatically. If the move fails, the overwrite must not happen.
- Read and record failures are silent (a missing or corrupt record means "nothing is known-fixed").

## Standalone indexer scripts: shared conventions

(source: indexer/*.py, indexer/broll_index/site_data.py)

- Each script under `broll/indexer/` (other than the `broll-index` command) takes `--config`, defaulting to `private/broll/indexer/config.queue.yaml` at the repository root. Most read `db.path` directly, so they only work against a direct SQLite database (`db.mode: sqlite`); several read the YAML themselves rather than through the config loader, so the environment-variable overrides and required-key refusals do not apply to them (`batch_transcribe.py`, `embed_transcripts.py`, `find_broken_sources.py`, `normalize_search.py`, `run_queue.py`).
- They are run by hand from `broll/indexer` (or by the watchdog). None has a user interface beyond printed progress.

## Unattended queue runner (`run_queue.py`)

(source: indexer/run_queue.py)

- Flags: `--config`, `--model` (default `haiku`), `--stages <list>` (override; runs exactly those stages through the serial CLI), `--max-hours N`, `--workers N` (default 4, local phase), `--api-workers N` (default 4, concurrent model calls; 1 means serial), `--deadline <local ISO time>` (no new clip is started after it).
- Logs "queue start - {status counts}".
- **Default plan** (no `--stages`): runs `parallel_local.py` with `--workers` (logs its exit code and counts), then the `claude` stage (through `parallel_claude.py` when `--api-workers` > 1, else the serial `broll-index run --stages claude`), then the `embed` stage through the serial CLI.
- Child output is streamed live and also captured. After each child: "[stages] rc=N remaining A -> B | <last line>", where "remaining" counts clips at discovered, probed or proxied (not duplicates).
- **On a child failure**:
  - If the child's own abort line ("claude stage aborted: ...", or a FatalRunError traceback line) says rate limit: sleeps until the reset time named in the message (plus 60 s, at most 6 hours away), else 15 minutes, logging "rate limited - resets X, sleeping N min, queue untouched" or "rate limited - no usable reset time..., waiting 15 min". If 6 hours of such waiting pass without the queue moving, stops: "waited N h on rate limits without placing a single video; stopping rather than sleeping on." Progress resets the counter.
  - Otherwise, if the queue moved, retries ("failed but progressed; retrying"); if not, stops with the last 800 characters of output.
- `--max-hours` is checked only between child runs; when reached: "max-hours reached; stopping cleanly".
- Ends with "queue complete - {counts}".

## Parallel local stages (`parallel_local.py`)

(source: indexer/parallel_local.py)

- Flags: `--config`, `--workers` (default 6, separate processes).
- Works on clips at discovered, probed, proxied or organised (not duplicates), in id order. Per clip: reopens an `organised` clip if its share is indexable again; sets "unknown share '<name>'" error for a share not in the config; ingests an existing `.srt` if the clip has none recorded and the share allows transcription (before probing, and without the over-length check the serial pipeline applies); then runs probe, proxy and frames as the status allows. For a share with `index: false`, stops before frames and sets `organised`. A stage failure sets "<stage> failed: <reason>".
- Prints "N videos through local stages, W workers", progress every 25 clips or on any error ("[i/N] rate/min eta Xh ok=.. err=.. last=id:status"), and a final summary.

## Parallel model stage (`parallel_claude.py`)

(source: indexer/parallel_claude.py)

- Flags: `--config`, `--model` (default `haiku`), `--workers` (default 4; also becomes the API client's in-flight ceiling), `--limit N`, `--share <name>` (repeatable; restrict to those shares), `--deadline <local ISO time>`, `--after-id N` (only clips with a higher id, so a second run can be started alongside a running one without overlap).
- Prints the Anthropic auth banner, then works on clips at `proxied` (not duplicates), excluding shares with `index: false`, in id order.
- An unknown `--share` name: prints "unknown share(s): X" and "known: ..." and exits 2.
- Each worker re-reads the clip and skips it if no longer `proxied`. Results are classified ok, skip, error (read back from the database row, so a clip the pipeline marked `error` is counted as an error), crash, deadline.
- After the deadline no new clip starts ("DEADLINE reached - starting no new videos; those in flight will finish"); unstarted clips stay `proxied`.
- An account-wide failure cancels all unstarted clips: "ACCOUNT-WIDE FAILURE - stopping. <reason>", "cancelled N queued videos; queue untouched and resumable", and at the end "claude stage aborted: <reason>" with exit code 1.
- Progress every 5 results, on every success and on crashes; final "done N, errors N, skipped N, not-started N in X min".
- With the local backend configured, this script drives the local model through the same path (despite its name and the Anthropic banner).

## Watchdog (`watchdog.ps1`, Windows only)

(source: indexer/watchdog.ps1)

- Meant to be run by a scheduled task. Parameters: `-DryRun` (do everything except launch), `-Force` (skip the "already running" check), `-Python <path>` (else `BROLL_PYTHON`, else `python.exe` on PATH; none: logs "FAIL - no python: ..." and exits 1).
- Log file: `E:\broll-queue\watchdog.log` (fixed path). Database: `E:\broll-queue\broll.db` (fixed path).
- If a `python.exe` process whose command line contains `run_queue.py` exists: logs "ok - run_queue alive (PID ...)" and exits.
- Asks `run_queue.remaining()` for the remaining count; 0: logs "queue complete - nothing to restart" and exits. Unreadable: logs "could not read remaining count (...) - restarting anyway".
- Otherwise starts, hidden, `python -u run_queue.py --model haiku --api-workers 12` in the script's own folder, with output to `E:\broll-queue\claude-<timestamp>.log` and `.err`, and logs "RESTARTED from <folder> - N videos remaining, log claude-<stamp>.log". Dry run logs "DRY-RUN - would restart, N videos remaining".
- Any error: logs "watchdog error: ..." and exits 1.

## Batch transcription (`batch_transcribe.py`)

(source: indexer/batch_transcribe.py)

- Flags: `--config`, `--model` (default `large-v3-turbo`), `--compute-type` (default `float16`), `--limit N`.
- Loads faster-whisper once on the CUDA GPU (no CPU option, no language option, ignores the config's `whisper` section) and transcribes, shortest first, every clip that: is not a duplicate; has no transcription recorded; has no `.srt` yet in its transcript folder; and is neither `discovered` nor `skipped`, except audio-only `skipped` clips (no codec, with a duration), which are included. It does not honour a share's `transcribe: false`.
- On Windows it adds the pip-installed NVIDIA cuBLAS/cuDNN/NVRTC DLL folders to the DLL search path and PATH.
- A file not found: "[i/N] MISSING <path>". A file with no audio stream gets an empty `.srt` (counted done, never retried). Transcription uses voice-activity filtering and beam size 5; a failure is retried once after 1 s, then "[i/N] FAILED <name>: <reason>".
- Writes `<data_root>/transcripts/<id>/<source name>.srt`. Prints the count and hours of audio up front, the model load time, progress every 10 clips or for any clip taking over 30 s, and a final "done N, failed N in X min (Nx realtime)". The pipeline's transcribe stage later ingests these files.

## Embedding transcripts in bulk (`embed_transcripts.py`)

(source: indexer/embed_transcripts.py)

- Flags: `--config`, `--batch` (default 256).
- Finds every non-empty transcript cue without a vector for the configured `embedding.model` (default MiniLM), embeds them in batches, inserts or replaces the vectors, increments the search generation and commits per batch. Waits up to 120 s on a locked database. Prints "N transcript cues need embedding (<model>)", running progress and a final count. Requires `fastembed` (fails otherwise). Ignores `embedding.enabled` and `cache_dir`.

## Keyword normalisation in bulk (`normalize_search.py`)

(source: indexer/normalize_search.py)

- Flags: `--config`, `--batch` (default 500).
- Switches the database to WAL journal mode, waits up to 60 s on locks, then fills the normalised keyword text for every transcript cue and segment that has none (same rules as the embed stage), committing and incrementing the search generation per batch. Prints per-table counts, progress and a total.

## Unreadable source finder (`find_broken_sources.py`)

(source: indexer/find_broken_sources.py)

- Flags: `--config`, `--workers` (default 8), `--out` (default `broken_sources.md` in the current folder).
- Checks every non-duplicate clip's source with ffprobe in parallel; a file not on disk is "MISSING from disk"; an unreadable one reports the first error line (120 characters). Prints each problem as found and progress every 500.
- Writes a Markdown report: "# Unreadable source files", "N of M source files cannot be read as media. These are damaged in the archive itself - re-download or re-copy them.", then one section per share listing "`path` (size MB) - reason".

## Building the shared archive tree (`build_archive.py`)

(source: indexer/build_archive.py)

- Flags: `--config`, `--dest <archive root>` (required), `--apply` (otherwise plan only), `--limit N`. Needs a direct SQLite database.
- **Which clips**: status `indexed`, `proxied` or `organised`, plus audio-only `skipped` clips, excluding duplicates. A `proxied` clip from a non-own-shoot share with no category yet is held back until described (so it is not filed under the uncategorised folder first).
- **Own-shoot shares** are those with `source: proxies`. Their clips go under `Creators_Club/<archive_name or share>/<the source's folders, minus any Proxy level>/`. All other clips go under `Downloads/<category>/`, or `Downloads/_uncategorised/` without a category.
- **File names**: the source file's name stem, with Windows-forbidden characters (`< > : " / \ | ? *` and control characters) replaced by `_`, trailing dots and spaces removed, cut to 90 characters, `untitled` if empty. Folder parts are cleaned the same way.
- **Two media slots per clip**:
  - Top slot `<folder>/<name>.<ext>`: for own-shoot shares, the shoot's own proxy file copied as is; otherwise the recorded original (if the file exists) or else the generated preview. A clip with neither is counted "NO proxy yet".
  - Preview slot `<folder>/Proxy/<name>.mp4`: the generated preview (`<data_root>/proxies/<id>.mp4`); for an audio-only clip with no preview, the top-slot file.
- **Stills**: `<dest>/posters/<id>.jpg` and `<dest>/sprites/<id>.jpg` copied from the data root; a missing one is counted.
- **Name collisions**: a clip that already has an archive path keeps that name forever. New clips take the plain name if no clip (published or planned) holds it in that folder (compared case-insensitively, extension ignored), else `<name>_2`, `_3`, ... Collisions are never judged from what is on disk.
- **Plan output**: "eligible videos", "files to place (N GB)", media count, posters and sprites counts with "(N clip(s) have none -- 'no preview' on the site)", "NO proxy yet".
- With `--apply`, the preview path of every planned clip (relative to the archive root) is written to the clip's `archive_path` before copying.
- **Deciding what to copy**: a destination recorded in the archive's in-place repair record and still matching it is left alone ("repaired in place: N (left alone - see .ccsync-inplace-fixes.json)"). Otherwise a file is copied when the destination is missing, differs in size, or (same size, modification times more than 2 s apart) differs in its quick fingerprint; unreadable means copy. Prints "to copy now", "already present".
- Without `--apply`: prints the first 12 planned paths and "re-run with --apply to copy". Nothing to copy: "nothing to do".
- **Copying**: to `<dest>.part` first (preserving timestamps), then any existing destination is moved to the archive trash ("replacing <name> (old copy kept at <path>)") and the copy renamed into place. A failure prints "FAILED <name>: <reason>" and continues. Progress every 25 files with GB, MB/s and ETA; final "copied N file(s), X GB in Y min".
- Never deletes anything at the destination and never touches source footage. Changing a share's `archive_name`, or a clip's category, leaves the old copies in place.

## Repairing 10-bit previews (`fix_10bit_proxies.py`)

(source: indexer/fix_10bit_proxies.py)

- Flags: `--root` (default `P:\Assets\B-roll Archive`), `--apply` (otherwise report only), `--workers` (default 2), `--limit N`.
- Reads `<root>/broll.db` and resolves each clip's preview as `<root>/<archive_path>`, or `<root>/proxies/<id>.mp4` when there is no archive path; existing files only. Probes them 8 at a time.
- A preview is "browser-hostile" when its first video stream is not H.264, or its pixel format contains "10".
- Report: "browser-hostile previews: N", "probe errors: N" (first 10 listed), and refusals: any hostile file not inside a folder named `Proxy` or `proxies` (any case) is listed as "REFUSED (not inside a Proxy/ folder - these are originals, not previews)". Dry run shows up to 10 examples and "dry run - re-run with --apply to re-encode these."
- With `--apply`: each eligible preview is re-encoded with the standard proxy encode (from the single same-named file one folder up if exactly one exists, else from the preview itself) into `.fix~<name>` and swapped into place, then recorded in the in-place repair record. Progress every 50; "done: N fixed, N failed"; exit code 1 if any failed.
- Note: the standard encode is now 1080p, so this also changes resolution of the repaired preview.

## Repairing preview timecode (`fix_proxy_timecode.py`)

(source: indexer/fix_proxy_timecode.py)

- Flags: `--root` (default `P:\Assets\B-roll Archive`), `--apply`, `--limit N`. Uses 4 workers.
- Same preview list as above. For each preview inside a folder named exactly `Proxy`, finds the single same-named file one folder up; reads its timecode and the drop-frame rule; verdicts: `fix` (preview's timecode differs from the wanted one), `ok`, `no-source`, `source-no-tc`. Prints "needs timecode: N" and tallies; dry run shows 5 examples and "dry run - re-run with --apply to remux these."
- With `--apply`: rewrites the container only (no re-encode) with the wanted timecode into `.fix~<name>`, then checks the written timecode equals the wanted one ("remux dropped the timecode" / "remux wrote X, not Y (the container normalised it)"), then swaps it in (one retry after 2 s if the file is locked). 600-second timeout per file. Progress every 200; exit 1 if any failed.
- Unlike the 10-bit repair, these fixes are not recorded in the in-place repair record, so a later `build_archive.py --apply` sees a size difference and copies the generated preview back over them (keeping the repaired file in the trash).

## Rebuilding sprite sheets (`regen_sprites.py`)

(source: indexer/regen_sprites.py)

- Flags: `--data-root <folder>` (required; must contain `broll.db`, else "regen_sprites: no broll.db under X" and exit 1), `--workers` (default 8), `--limit N`, `--dry-run`, `--force` (rebuild even clips whose geometry is recorded).
- First runs the schema migration on that database and prints its report.
- Rebuilds the sprite sheet from the local preview (`proxies/<id>.mp4`) for every clip with a duration and no recorded sprite geometry (or all, with `--force`), writing the measured geometry per clip. Clips without a local preview are skipped and counted. Progress every 250; final counts of rebuilt, failed and still unrecorded; exit 1 if any failed. Touches nothing outside the data root.

## Encoding missing own-shoot proxies (`tools/make_own_proxies.py`)

(source: indexer/tools/make_own_proxies.py)

- Flags: `--root <tree>` (required; missing folder: "make_own_proxies: --root does not exist" exit 2), `--preset ff2|disinfo|wct` (a built-in exclude list for three specific customer project trees), `--exclude <pattern>` (repeatable), `--max-duration` (default 300 s; 0 = no cap), `--workers` (default 2), `--apply` (otherwise dry run), `--limit N`, `--ledger <file>` (default `broll/indexer/proxy-prepass-<preset or folder name>.jsonl`, appended to).
- Walks the tree, skipping folders that look like proxy folders, names starting with `@` or `.`, and excluded patterns (a `*/X` pattern also matches a top-level `X`). Candidates are files ending in `.mp4 .mov .mxf .mts .m4v .mkv .avi .m2ts` (not `._` files) with no non-empty `Proxy/<stem>.(mov|mp4|mxf|mts)` beside them.
- Per clip: probe (failure: `probe-failed`), no duration (`no-duration`), no picture (`no-video-stream`), longer than the cap (`over-cap`), dry run (`would-encode`). Otherwise encodes `<dir>/Proxy/<stem>.mp4` using the companion's own editor-proxy encode settings (imported from the companion package), carrying the source timecode with the drop-frame rule, writing to `.mp4.partial` first.
- Verification as for the indexer's proxy (decode errors, exact frame count, at least 97% duration). A bad NVIDIA result is redone on the CPU encoder once (`nvenc_retry` noted). Still bad: `bad-output`; encoder error: `encode-failed`; success: `ok` with the byte size.
- Every result is appended as one JSON line to the ledger. Prints the candidate count, encoder ("h264/hevc NVENC" or "libx265 (CPU)"), mode, progress every 25 with GB written and per-status counts, and a summary.
- Never reads, moves or deletes source files.

## Back-catalogue run script (`tools/run_backcatalogue.sh`)

(source: indexer/tools/run_backcatalogue.sh)

- A fixed sequence for three specific customer projects with hardcoded drive paths (`Q:/FF2` and two `R:/Project Backups/...` trees) and the private queue config: encode missing proxies for each (5 workers), delete leftover `.mp4.partial` files, scan the three shares (`ff2`, `disinfo`, `wct`), run `parallel_local.py` with 8 workers, run the describe stage, run the embed stage, then print per-share status counts from `E:/broll-queue/broll.db`. Logs to `run_backcatalogue.log` with timestamps.

## Usage cost report (`tools/cost_report.py`)

(source: indexer/tools/cost_report.py)

- `python tools/cost_report.py <data_root> [--archive-hours H]`. Reads `<data_root>/usage.jsonl` (missing: "no usage log at <path> - run the claude stage with instrumentation first").
- Per model: number of calls, distinct clips, minutes of footage, minutes of model time, input / cache-creation / cache-read / output tokens, the share of input that is per-call overhead, estimated cost, cost per clip-minute and clip-hour, speed relative to real time, and with `--archive-hours` a cost and model-time forecast for an archive of that size; overhead tokens per call.

## Whisper sidecar environment (`tools/make_whisper_env.ps1`, `tools/make_whisper_env.sh`, `tools/whisper_transcribe.py`)

(source: indexer/tools/make_whisper_env.ps1, indexer/tools/make_whisper_env.sh, indexer/tools/whisper_transcribe.py)

- **Builder** (PowerShell on Windows, bash on Linux/macOS): creates a separate Python virtual environment (default `broll/indexer/.whisper-env`; `-Path`/`--path` to change) with pinned `faster-whisper==1.1.1` and `ctranslate2==4.5.0`, plus (unless `-Cpu`/`--cpu`) `nvidia-cublas-cu12==12.4.5.8` and `nvidia-cudnn-cu12==9.1.0.70`. Refuses an existing folder without `-Force`/`--force` ("already exists. Re-run with -Force to rebuild it."). Interpreter: `-Python`/`--python`, else `python.exe` on PATH (Windows; none: "no python.exe found") or `$PYTHON`/`python3`. Verifies the packages import, then prints the `whisper.python` and `whisper.script` values to put in `config.yaml`, mentioning the ~1.6 GB first-run model download and `whisper.model_dir`. The bash version rejects unknown arguments (exit 2) and prints help with `-h`.
- **Helper** (`whisper_transcribe.py <media> -o <dir> [-m model] [-l lang] [--device auto|cuda|cpu] [--compute-type T]`): device default from `CCSYNC_WHISPER_DEVICE` (else `auto`: GPU if one is visible, else CPU); compute type from `CCSYNC_WHISPER_COMPUTE_TYPE` (else `float16`, switched to `int8` on CPU). Missing input: "no such file" exit 2. No audio stream (or ffprobe absent counts as having audio): writes an empty `.srt`. faster-whisper missing: explains how to build the environment, exit 3. Transcribes with voice-activity filtering and beam size 5, writes `<dir>/<stem>.srt` and prints its path. Adds the NVIDIA DLL folders on Windows.

## Overnight run report (`broll/morning_report.py`)

(source: morning_report.py)

- No flags. Reads the fixed database `E:\broll-queue\broll.db` and data folder `E:\broll-queue`.
- Prints: coverage (indexed + sorted out of all non-skipped clips, with a per-status table); segment count and how many have on-screen text; transcript cue and embedding counts; counts of the canonical no-visual labels; model call count, payload versus overhead tokens and output tokens from `usage.jsonl`; error count with the first 10 erroring clips; free space on drive `E:`; then a fixed "baseline before indexing: recall 19/20, guards 4/5" header and runs the API search evaluation (`eval/run_eval_api.py`) with the web app's Windows virtual environment against the private archive query set `private/broll/eval/queries_archive.yaml`.

## Database schema (fresh install and migrations)

(source: schema.sql, migrations/*.sql, indexer/broll_index/migrations/*.sql)

- `schema.sql` creates a fresh database directly at version 13 in WAL journal mode. The `migrations/` scripts upgrade an older one step by step; the copies bundled inside the indexer package are identical except for a comment.
- **Clip table (`videos`)**: share, relative path (unique together), fast fingerprint, size, duration, frame rate, width, height, codec, shot date, approved category, model's category hint, inbox flag, status (default `discovered`; no constraint on the value), error text, description time, model, transcription time and language, whole-file hash, `duplicate_of`, archive path, original path / size / last-verified time, sprite geometry (cell width, cell height, columns, cells, interval), frame count, start timecode, bitrate.
- **Segments** (one per described shot): start, end, description, objects, setting, motion, on-screen text, English on-screen text, normalised keyword text. Kept in two full-text indexes automatically: one word-based with English stemming (description, objects, setting, English on-screen text, normalised text) and one character-trigram based for substring matching of Chinese (on-screen text, objects, normalised text).
- **Transcript cues**: start, end, text, normalised text; same two full-text indexes.
- **Embeddings**: one vector per segment or cue, with model name and dimension.
- **Themes** (free-text tags per clip), **quality flags** (restricted to the six allowed words), **categories** (slug, label, description).
- **Share roots**: share, root folder, source mode (`originals`/`proxies`), description, indexed flag, update time, and a `collection` override written only by dashboard ingest.
- **Meta**: key/value, seeded with `search_generation = 0`.
- **Ingest batches and items** (used by the dashboard's drag-and-drop ingest and the companion, not by this indexer): batch owner, machine, companion version, share, collection (default `owned`), settings, state (`queued`, `claimed`, `running`, `done`, `done_with_errors`, `cancelled`, `failed`), counters, current item, lease expiry, heartbeat, cancel request, upload pause, error and timestamps; items with order, original name, sub-folder, size, fingerprint, media facts, source (`upload`/`path`), clip id, duplicate-of, archive folder and name, state (`pending`, `duplicate`, `proxying`, `framing`, `describing`, `indexed`, `uploading`, `proxies_live`, `live`, `failed`, `cancelled`, `skipped`), stage percent, error, attempts, original-uploaded flag.
- **Migration notes visible to an operator**: 002 leaves existing segments with empty on-screen text (the describe stage must be re-run to fill it); 002 and 004 rebuild the full-text indexes; 013 rebuilds the ingest items table to allow `proxies_live`.

## Bundled config files

(source: indexer/config.example.yaml, indexer/taxonomy.rules.yaml, indexer/pyproject.toml)

- **`config.example.yaml`**: a template to copy to `config.yaml` with one share (`broll` at `Y:/broll`), `data_root: D:/broll-data`, SQLite at `D:/broll-data/broll.db` (API URL and token shown for the other mode), `indexer.backend: local` with frames per call 9, GPU layers 99 and segment merging on, `model: sonnet`, `taxonomy_model: sonnet`, the Anthropic block, sampling (0.3 / 4.0 / 36), whisper pointing at `.whisper-env/Scripts/python.exe` and `tools/whisper_transcribe.py` (relative paths), and embedding. Because it contains an `anthropic:` section and an explicit `indexer.backend: local`, a config copied from it runs the local backend.
- **`taxonomy.rules.yaml`** (the rules for `taxonomy assign`): 33 subject categories with match patterns across energy (nuclear, renewables, power & grid), environment (waste & recycling, pollution & climate, conservation & wildlife, coastal erosion), economy (industry & manufacturing, work & wages, retail & commerce, agriculture & fishing, cost of living & housing, finance & markets), society (government & politics, protest & activism, policing & crime, education, health & welfare, transport & road safety, indigenous affairs, gender & LGBT), culture (heritage & religion, food & drink, performance & music, digital & social media, animation & anime, media & broadcasting), leisure (esports & gaming, travel & tourism, sport & outdoors, animals & pets), security (military & defence, emergency & disaster), plus `people/interviewee-broll` with no patterns (only reachable through the interviewee folder rule). Five fallback categories (`general/news-broadcast`, `general/interviews`, `general/archival`, `general/public-life`, `general/places`) and the default `general/unsorted` ("Unsorted"). A `descriptors` block (format, place, look) that the indexer reads and returns but does not use.
- **Package definition**: the package `broll-indexer` 0.1.0 needs Python 3.12 or newer and installs the `broll-index` command. Required libraries: `anthropic`, `xxhash`, `pyyaml`, `requests`, `jieba`, `opencc-python-reimplemented`. Optional extras: `embeddings` (`fastembed`), `transcribe` (`faster-whisper` 1.1.1 and `ctranslate2` 4.5.0 in-process), `dev` (`pytest`). The prompts and bundled migrations ship inside the package. numpy is imported unconditionally by the embedding module, which the pipeline (and so the `broll-index` command) loads at start-up, yet numpy is neither declared nor in `requirements.lock`; the local backend's pixel quality flags also need Pillow, likewise undeclared. Both arrive only through the optional `fastembed` extra, if at all.

## Data files in `broll/indexer` (not code)

(source: as named; what reads or writes each, per the code)

- `proxy-prepass-disinfo.jsonl`, `proxy-prepass-ff2.jsonl`, `proxy-prepass-ff2-w5.jsonl`, `proxy-prepass-wct.jsonl`: result ledgers appended by `tools/make_own_proxies.py` (one JSON record per clip: source, status, duration, destination, bytes, error detail). Nothing reads them back.
- `run_backcatalogue.log`: the log written by `tools/run_backcatalogue.sh`.
- `rebase_report.md`: the default output of `broll-index rebase`.
- `requirements.lock`: pinned, hashed dependency list for installs and CI; not read by the code.
- `.pytest_cache/`: test-runner cache (not part of the product).

## Search evaluation: keyword-only scorer (`eval/run_eval.py`)

(source: eval/run_eval.py)

- `python eval/run_eval.py <db> [<db> ...] [--queries <yaml>]`. Default query set: `private/broll/eval/queries_ff2.yaml` at the repository root (site-specific, git-ignored).
- A query file is YAML with a `queries` list; each entry has `q` (the query text), and either `expect_any` (a list of substrings, any of which must appear in a matching clip's relative path) or `expect_none: true` (a "precision guard": the query must return nothing), plus optional `tags`.
- Runs each query straight against the database's full-text tables (no web app): every term is quoted and the terms are joined with AND; quoted phrases stay together. Searches visual segments and transcripts, in both the word index and the trigram index; trigram tables are skipped when any term is shorter than 3 characters; tables missing in older schemas are skipped; a query the database rejects counts as no hits.
- Report per database: schema version, indexed clip and segment counts, recall "hit/total (P%)", "precision guards: clean/total clean", recall per tag, then each miss ("MISS 'q' (N hits, none expected-matching)") and each guard failure ("LEAK 'q' returned N hits (expected none)").
- With two or more databases: a comparison listing each query whose outcome differs, with HIT/MISS per database.
- Exit code 1 if any guard fails in any database.

## Search evaluation: through the real search API (`eval/run_eval_api.py`)

(source: eval/run_eval_api.py)

- `python eval/run_eval_api.py <db> [--queries <yaml>] [--mode hybrid|keyword|semantic] [--no-fuzzy]`. Same query file format and default.
- Loads the b-roll web app in-process (needs the web app's dependencies) with `BROLL_DATA_ROOT` set to the database's folder, so the web app actually searches `<that folder>/broll.db` whatever file name was given; the counts printed come from the given file.
- Calls `GET /api/search?q=...&mode=<mode>&fuzzy=<true|false>&limit=50` for each query and matches expectations against `share/relative path` of the returned clips. A non-200 answer is recorded as an error.
- Report: database name, mode, fuzzy flag, schema version, clip and embedding counts, recall, guards, recall per tag, and misses ("MISS"/"LEAK ... (N videos returned)"). Exit 1 if any guard fails.

## Local vision-model evaluation harness (`eval/local_vlm/`)

(source: eval/local_vlm/common.py, select_clips.py, make_bundle.py, run_eval.py, format.py, prompt_v7_compact.md, config.base-rig.json, config.mac.json)

- **Purpose**: measure how well a locally-run Qwen3-VL model describes clips compared with the existing Claude Haiku descriptions (treated as a reference, not truth), on about 100 clips, across three "arms": A (individual stills, 9 per call, compact line format, grammar-constrained), B (same without grammar), C (old path: contact sheets, the version 6 JSON prompt, 4 sheets per call, at most 24 sheets per clip, temperature 0).
- **Defaults**: database `BROLL_DB_PATH` or `E:\broll-queue\broll.db`; data root `BROLL_DATA_ROOT` or `E:\broll-queue`. Sampling for A/B: temperature 0.1, repeat penalty 1.15; 150 output tokens per still.
- `format.py` and `prompt_v7_compact.md` are the evaluation's own copies of the indexer's compact format module and prompt; the code is identical except that the indexer's copy can pass an embedding cache folder.
- **Clip selection** (`select_clips.py [--db] [--data-root] [--per-stratum 25] [--max-frames 45] [--min-frames 2] [--seed 20260817] [--out clips.json]`): reads the database read-only; considers non-duplicate clips at `indexed` or `sorted` with a model and at least one segment, whose `sheets/<id>/` folder is complete and every listed still exists. Drops clips with more than 45 or fewer than 2 stills. Shuffles with the seed, then picks up to 25 per stratum in order: `text` (baseline has on-screen text), `multishot` (5+ segments), `simple` (at most 2 segments), `random`. Writes `clips.json` with the stills (index, time, timecode, relative path), sheet paths, the baseline segments/themes/flags/category/model, the category list and selection statistics. Missing database: "DB not found: <path> (set --db or BROLL_DB_PATH)". Prints counts and a still-count histogram.
- **Portable bundle** (`make_bundle.py [--clips] [--out bundle] [--zip bundle.zip] [--no-sheets] [--no-zip]`): deletes and recreates `bundle/`, copies the selected stills (and contact sheets unless `--no-sheets`) into `bundle/sheets/<id>/...`, writes `bundle/clips.json` with a relative frames root, and zips the bundle (fast deflate) unless `--no-zip`.
- **Runner** (`run_eval.py --arm A|B|C`):
  - Flags: `--clips`, `--results-dir` (default `results`), `--config <host json>`, `--llama-server`, `--model`, `--mmproj`, `--model-label`, `--port` (default 8931), `--ctx` (default 16384), `--image-min-tokens` (default 1024; 0 disables), `--server-arg` (repeatable), `--server-url` (attach to a running server; refused if unhealthy), `--load-timeout` (1200 s), `--call-timeout` (900 s), `--clip-time-cap` seconds (skip a clip's remaining windows once exceeded; recorded `partial`), `--frames-per-call` (9), `--sheets-per-call` (4), `--no-grammar`, `--limit N`, `--ids ...`, `--retry-errors`, `--temperature`, `--repeat-penalty`, `--category auto|fastembed|tfidf|none`.
  - Host config files: `config.base-rig.json` (Windows RTX 3080 with absolute paths to a llama-server and the 4B Q4 model in one user's profile) and `config.mac.json` (Apple M4 Max, server in `~/.cache/ccsync-eval`). Missing config file: "host config not found". Missing binary/model/projector: "missing --X" or "X not found".
  - Starts its own llama-server (log `results/llama-server.<arm>.log`; Windows: own process group), waits for health every 2 s, stops it at exit or on Ctrl-C/termination.
  - Resumable: clips already in `results/<arm>.jsonl` are skipped (`--retry-errors` re-runs those recorded as `error`).
  - Per clip it records one JSON line: status (`ok`, `partial`, `invalid`, `partial_invalid`, `error`), window count, valid windows, wall time, tokens, encode/decode times, peak memory (Windows: GPU memory used minus the level before the server started; macOS: the server's resident memory), the merged result (for A/B also pixel quality flags, per-still statistics and nearest-match category with score and method), and every call's raw text and timings. Lines are written and flushed to disk immediately.
  - Writes `results/<arm>.meta.json` (arm, host, runtime, model, context, sampler, timings, peak memory).
  - Prints a progress line per clip with status, calls, segments, seconds, tokens, decode speed, memory and ETA.
- **Scorer** (`score.py [--results-dir results] [--clips] [--recategorize] [--category auto|fastembed|tfidf]`): finds `clips.json` beside or above the results folder if not given. For every arm present, scores each clip against the Haiku baseline:
  - segment F1 (greedy one-to-one match at time-overlap of at least 0.5, each interval padded by the median still gap, at most 4 s), precision, recall, count ratio;
  - frame coverage; object-set Jaccard; head-noun recall over objects and over all text (simple singularisation and a stop-word list);
  - on-screen text exact match, similarity, character recall and detection (on clips whose baseline has text), and a false-positive rate where the baseline had none;
  - category agreement with the baseline hint and the approved category, whether the slug is in the taxonomy; theme Jaccard and soft overlap; quality-flag Jaccard;
  - an "agreement" score (mean of segment F1, head recall, OCR similarity if applicable, category agreement if applicable; 0 for invalid clips).
  - Aggregates overall, on the clips common to all arms (when they differ), and per stratum; lists the 20 clips with lowest agreement for arm A with a side-by-side segment table and frame folder.
  - Writes `report.md` and `summary.json` into the results folder. `--recategorize` re-assigns arm A/B categories on this machine. No results: "no <arm>.jsonl in <dir>".
- **Cross-run comparison** (`compare.py <run dirs or summary.json files> [--out results/compare.md] [--labels ...]`): one table of run metadata and, per arm, a metric table side by side, plus arm A per-stratum segment F1 / head recall / OCR similarity.
- **Mac model picker** (`mac_models.py list | pick --model 8b|30b|32b --budget-gb N [--ctx 16384] [--prefer q8|q4] [--force]`): a catalogue of Qwen3-VL 8B, 30B-A3B and 32B quantisations (official Qwen and unsloth repositories) with sizes; picks the best quantisation whose weights + projector + context memory + 2.5 GB overhead fit the budget, trying 8k context if 16k does not fit. `--force` returns the smallest at 8k marked over-budget instead of failing ("no X quant fits a N GB budget"). Prints JSON.
- **Mac launcher** (`run_mac.sh --bundle <zip|dir> [--models 8b,30b,32b] [--limit N] [--q4|--q8] [--cache DIR] [--results DIR] [--clip-time-cap-32b SEC (900)] [--skip-arms-bc]`, macOS bash 3.2): refuses anything but Apple Silicon macOS. Writes a pid file, unpacks the bundle into `bundle-mac/`, finds llama-server (env `LLAMA_SERVER`, PATH, cache, `brew install llama.cpp`, else downloads release b10470 and clears the quarantine attribute), installs Pillow for the user if missing, computes the Metal memory budget (wired limit, else 3/4 of RAM above 34 GB or 2/3 below, minus 0.5 GB), then per model: picks a quantisation, downloads model and projector from Hugging Face with resumable curl (progress in `download.log`), prefetches the other models in the background, runs arm A (8B also arms B and C on 25), kills stray servers, scores each, and finally compares all runs. Writes `pick.json` per model and a `DONE` marker.
- **Windows overnight launcher** (`run_overnight.ps1 [-Limit N] [-ClipsC 25] [-MinFreeMB 6000] [-MaxWaitHours 8] [-SkipWait] [-Foreground] [-Python] [-Config config.base-rig.json] [-ResultsDir results]`): relaunches itself hidden as a worker (refuses if a live worker's lock exists: "already running"). The worker waits, checking every 60 s for up to 8 hours, until the GPU has at least 6,000 MB free and DaVinci Resolve is not running (logging "waiting for Resolve to close" or "waiting for GPU memory"; gives up with exit 3). Then runs arms A and B, arm C on 25 clips, and the scorer, logging everything to `results/run.log`; kills any leftover llama-server, writes `results/DONE`, removes the lock.
- **Status** (`status.ps1 [-Tail 20] [-ResultsDir results]` and `status_mac.sh [results dir]`): whether the worker/launcher is alive (or a stale lock / DONE marker), llama-server state, GPU or system memory, whether Resolve is running (Windows), per-arm clip counts and fully-ok counts, report times, the last download line (Mac) and the tail of the run log.

## Human blind judging tool (`eval/local_vlm/judge/`)

(source: eval/local_vlm/judge/build_judge.py, serve.py, summarise_verdicts.py)

- **Builder** (`build_judge.py [--clips bundle/clips.json] [--source LABEL=PATH ...] [--order disagreement|random|id] [--seed 20260817] [--limit N] [--summary results/summary.json] [--out judge.html]`): writes one self-contained offline HTML page. Default sources: `haiku` (the baseline inside clips.json), `local-4b` (`results/A.jsonl` if present) and every `results-mac/<model>/A.jsonl`. `--source` replaces the defaults; a missing file is refused; a value without `=` is refused. Default order puts the 20 most-disagreeing clips (from summary.json, or scraped from report.md) first, then the rest shuffled with the seed. Missing clips file: "clips file not found ... run make_bundle.py ... first". Reports how many referenced frame images are missing ("WARNING: N frame(s) will show broken images").
- **The judge page** (`judge.html`, opened from disk; title "local-VLM b-roll eval - judge"):
  - Top bar: "JUDGE", progress "n/N", clip share/path, stratum and duration, a hint "<-/-> clip · click column then 1-5 to score", buttons "Export verdicts.json", "Import", "Summary".
  - Filmstrip of the clip's stills (96x54 thumbnails with timecodes). Clicking a still shows it larger and pins it: every segment (in every column) covering that time (with 2 s slack) is highlighted; clicking the same still again unpins.
  - One column per source, labelled A, B, C... in a per-clip random order chosen and remembered by this browser (blind). Each column lists segments (time range, description, objects, on-screen text with English), themes, quality flags and category. Hovering a segment highlights the stills it covers; clicking pins it (click again to unpin); clicking anywhere else clears a pin. Clicking a column focuses it.
  - Under each column: accuracy buttons 1 to 5 (click the active one again to clear), a "best" radio choice, and flags "hallucinated", "missed the shot", "OCR wrong", "over-segmented". Any vote on a clip reveals the real source names in the column headers.
  - Keyboard: Right/Left arrow move to the next/previous clip; keys 1 to 5 score the focused column. Ignored while typing in a text box.
  - A notes box per clip, saved on every keystroke.
  - Everything (votes, notes, shuffle, current position) is stored in the browser's local storage under the prefix `brolljudge_v1_`, and the page reopens at the last clip.
  - Export downloads `verdicts.json` (every clip with any vote: per-source score and flags, best, note, revealed, time). Import reads such a file and overwrites those clips' votes (marked revealed, with a fresh shuffle), alerting "imported N verdict(s)" or "not valid JSON".
  - Summary panel: per source, mean score, number scored, "best" picks and flag counts, over the clips judged so far.
- **Local server** (`serve.py [--port 8000] [--no-browser]`): serves the whole `local_vlm` folder on 127.0.0.1 only and opens `http://127.0.0.1:<port>/judge/judge.html`, for browsers that will not load the page's images from disk.
- **Verdict summary** (`summarise_verdicts.py [--verdicts judge/verdicts.json] [--out judge/verdicts.md]`): writes a Markdown report of per-source mean score, count, best picks and flag counts, the same per stratum, all notes, and for each source that has a scorer `summary.json`, the Pearson and Spearman correlation between the human score and the scorer's agreement value. Missing input: "not found: ... (Export from judge.html first, or pass --verdicts)".

## Prototype scripts kept beside the docs (`broll/docs/prototypes/local-vlm/`)

(source: docs/prototypes/local-vlm/run_local_vlm.py, run_llamacpp.py)

- `run_local_vlm.py --ids <ids> [--device auto|cpu|cuda] [--max-sheets 3] [--max-new-tokens 900] [--out local_vlm_results.json]`: loads Qwen3-VL-4B (environment `VLM_MODEL` to change) through the `transformers` library (GPU only if more than 9 GB is free), runs the version 6 prompt on the first sheets of each given clip from the hardcoded `E:/broll-queue` data and database, validates with the indexer's parser, and writes a JSON results file. Hardcoded repository path `E:/Projects/Editing/ccsync`. Needs torch, transformers and Pillow, none of which the indexer declares.
- `run_llamacpp.py --ids <ids> [--max-sheets 3] [--schema] [--ngl 0] [--threads N] [--out results_llamacpp.json]`: the same through a Windows `llama-server.exe` in a folder beside the script (`LLAMA_DIR`, default `llamacpp`) on port 8931, with the 4B GGUF found in the Hugging Face cache (`HF_HOME`), optionally constraining output to a JSON schema of the contract. Windows-only as written.
- `claude_baseline.json`, `results_llamacpp_cuda.json`, `results_llamacpp_cuda_schema.json`, `results_transformers_cpu.json`, `results_transformers_cuda.json`: result files from those prototype runs (the latter four are the scripts' output format); nothing in the code reads them. Which code wrote `claude_baseline.json` could not be determined.

## Evaluation data files (not code)

(source: as named; readers and writers per the code)

- `eval/local_vlm/clips.json`: the selected clip list with baseline descriptions; written by `select_clips.py`; read by `run_eval.py`, `score.py`, `make_bundle.py`, `status.ps1` (clip count) and, through the bundle copy, `build_judge.py`.
- `eval/local_vlm/bundle/` (`clips.json` with a relative frames root, plus about 2,000 still and contact-sheet JPEGs under `sheets/<id>/`): written by `make_bundle.py`; read by `run_mac.sh`, `build_judge.py` and the judge page's images. `bundle.zip` is the same zipped, written by `make_bundle.py`, read by `run_mac.sh`.
- `eval/local_vlm/results/A.jsonl`, `B.jsonl`, `C.jsonl` (one record per clip per arm) and `A.meta.json`, `B.meta.json`, `C.meta.json`: written by `run_eval.py`; read by `score.py`, `build_judge.py`, `status.ps1`.
- `eval/local_vlm/results/llama-server.A.log` etc.: the model server's output, written by `run_eval.py`. `run.log` and `DONE`: written by `run_overnight.ps1`; read by `status.ps1`.
- `eval/local_vlm/results/report.md` and `summary.json`: written by `score.py`; `summary.json` read by `compare.py`, `build_judge.py` (disagreement order) and `summarise_verdicts.py`.
- `eval/local_vlm/results-mac/<model>/A.jsonl` and `A.meta.json` (two models present: 30B-A3B Q5_K_M and 8B Q8_0): written by `run_eval.py` under `run_mac.sh`; read by `score.py` and `build_judge.py`.
- `eval/local_vlm/judge/judge.html`: generated by `build_judge.py` (contains the page code shown above plus the embedded evaluation data); git-ignored.
- The `.gitignore` files keep results, bundles, logs, judge page and verdict exports out of version control.

## Looks redundant or overlapping

- Three ways to run transcription: whisper from the pipeline (code present but never reached from any command, since every caller passes "ingest only"), the per-file sidecar helper `tools/whisper_transcribe.py` (only reached by that unreachable path), and `batch_transcribe.py` (the one that actually produces transcripts). `broll-index transcribe` refuses when the sidecar is not configured even though it only ingests files the batch script wrote.
- Two runners for the local stages (`broll-index run` serially, `parallel_local.py` in parallel) and two for the model stage (`broll-index run --stages claude`, `parallel_claude.py`), plus `run_queue.py` orchestrating them and `watchdog.ps1` restarting `run_queue.py`. The parallel and serial paths re-implement the same rules (organised reopening, index:false, transcribe ingest) separately and differ in details (the over-length transcription check exists only in the serial path).
- Keyword normalisation and embedding exist both as the `embed` pipeline stage and as two standalone bulk scripts (`normalize_search.py`, `embed_transcripts.py`) that write the same columns and tables.
- `fix_10bit_proxies.py` and `fix_proxy_timecode.py` repair previews already in the archive for problems the current encoder no longer creates; `regen_sprites.py` repairs sprite geometry for sheets built before it was recorded. All three are one-off migrations kept as tools.
- `duplicates` (marks copies, never deletes) and `rebase --prune-duplicates` (deletes superseded rows) both decide "which copy is canonical" with the same ranking implemented twice.
- The compact format and prompt exist twice (indexer `compact_format.py` + `prompts/index_clip_v7_compact.md`, and `eval/local_vlm/format.py` + `prompt_v7_compact.md`), and are also vendored into the companion. The llama-server start/health/window code exists in both `local_vlm.py` and `eval/local_vlm/run_eval.py`.
- Migrations are stored twice (repository `migrations/` and a bundled copy in the package), and `schema.sql` restates the end result of all of them.
- Five unused prompt versions (`index_clip.md`, `_v2` to `_v5`) ship in the package; only v6 (Anthropic) and v7 compact (local) are loaded.
- The local backend runs the frames stage, which builds contact sheets it never reads (only the Anthropic backend uses sheets).
- Proxies are made by three producers with separate settings: the indexer's 1080p H.264 browser preview, `tools/make_own_proxies.py` (borrowing the companion's HEVC editor-proxy settings), and the companion itself; the frame-count rule is shared but the encodes are not.
- `morning_report.py`, `tools/cost_report.py` and `parallel_claude.py`'s summary each compute call/token totals from `usage.jsonl` or the database in their own way.
- `taxonomy propose` (Claude clusters themes into a proposal) and `taxonomy assign` with the hand-written `taxonomy.rules.yaml` are two separate approaches to categories; the local backend adds a third (nearest-match category hint), and the Anthropic backend a fourth (model's category hint). Only `assign` sets the clip's actual category.
- `run_eval.py` (keyword tables) and `run_eval_api.py` (real search) score the same query sets two ways; `morning_report.py` wraps the second.

## Claims the code does not back

- `transcribe.py` module docstring: transcription "runs over everything unconditionally". In the pipeline it only ingests existing `.srt` files, never runs whisper, and skips shares with `transcribe: false` and over-length clips.
- `pipeline.py` module docstring and the CLI help for `transcribe` describe it as local faster-whisper transcription; inside `run` it is ingest-only.
- `run_queue.py` docstring lists "2. transcribe - GPU-local and free; do it early" as a stage it runs; its default plan never runs transcription (the `LOCAL_STAGES` list naming it is unused), and `parallel_local.py` only ingests existing `.srt` files.
- `config.example.yaml` says CJK keyword normalisation "is always applied by the `embed` stage and has no separate toggle"; with `embedding.enabled: false` the embed stage returns before normalising anything.
- `build_archive.py` module docstring shows the layout `<dest>/Downloads/<category>/<original name>.mp4`; the code puts the best media at that level and the preview in a `Proxy/` subfolder, and for downloads the top file is the original in its own extension. Its `dest_rel` docstring and `preview_source` docstring call the preview "540p"; the encoder now makes 1080p.
- `build_sprite` docstring refers to "the 540p proxy step"; proxies are 1080p. `fix_10bit_proxies.py` docstring says a second-generation encode "is invisible at 540p"; its re-encode is now 1080p.
- `watchdog.ps1` comment says it runs non-elevated because "the claude CLI's credentials are user-scoped"; the indexer no longer uses the Claude CLI (it uses an API key).
- `summarise_verdicts.py` docstring says it reads `--clips` for a sanity id check; there is no `--clips` option and no such check.
- `run_eval_api.py` usage line implies the given database file is scored; the web app always reads `broll.db` in that file's folder.
- `local_vlm.load_frame_list` docstring says still files are numbered by their position in the requested timestamp list while `frames.json` holds only produced timestamps, and assumes the two line up; if a still in the middle of a clip failed to extract, every later still is paired with the next still's timestamp (only a trailing failure is harmless).
- `claude_client.call_claude_with_retry` docstring says usage is empty "if the CLI gave no envelope"; there is no CLI any more.
- `pyproject.toml` describes `fastembed` as the only optional heavy dependency and says the embedding module "degrades to a logged no-op without it"; the module imports numpy unconditionally, numpy is not declared, and the pipeline cannot be imported without it.

## Could not determine

- Whether numpy and Pillow are present on real indexing machines (they are not declared; without numpy the `broll-index` command cannot start).
- What the web app's ingest endpoints (`/ingest/video`, `/ingest/index`, `/ingest/moved`, `/ingest/shares`, `/categories`) do with the fields the indexer sends (for example `status`, `error`, sprite geometry), and whether `/ingest/index` resolves by share and path as the indexer's comments say: that is the web section's code.
- What the dashboard's `GET /api/v1/site` returns for `indexer.model_tier`, and when (dashboard section).
- The `GET /api/search` parameters' exact semantics (`mode`, `fuzzy`) used by `run_eval_api.py` (web section).
- How often mid-clip still extraction fails in practice (which decides how often the local backend mislabels timestamps).
- Which script produced `docs/prototypes/local-vlm/claude_baseline.json`.
- The contents of the private query sets (`private/broll/eval/queries_*.yaml`) and the private queue config, which are outside the repository.
- Whether anything still runs `taxonomy propose`; nothing in the tree calls it.
- Whether `index: false` shares are still used anywhere (`build_archive.py`'s comments say MOFA was switched to indexed).
