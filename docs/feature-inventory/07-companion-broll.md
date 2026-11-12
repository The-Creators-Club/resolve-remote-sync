# Companion: the b-roll send-to-Resolve server, b-roll ingest and local clip indexing

Terms used throughout:

- **Loopback server**: the small web server the companion (the tray app on each editor's computer) runs on `127.0.0.1`, port 8899 by default. Only programs on the same computer can reach it. Web pages served by the dashboard (the fleet web app on the NAS) call it from the editor's own browser.
- **Share** and **rel path**: a clip is never named by an absolute path on the wire. A request names a share (a short name such as `broll`, `music`, `projects`) and a forward-slash path relative to that share. The companion translates the pair into a path on this computer.
- **Mount table**: the map from share name to the folder where that share lives on this computer.
- **Preview**: the small 1080p (or 540p) H.264 `.mp4` copy of an archive clip kept in a `Proxy/` folder beside the original.
- **Editing proxy**: a higher-quality `.mov` copy, made only for originals judged too heavy to edit with.
- **Stand-in**: the preview's bytes saved on this computer under the original's own file name and path, so Resolve's clip points at the canonical original path while the editor actually cuts with the preview. The companion keeps a ledger (a record file) of every stand-in it placed.
- **Ingest**: dropping or picking new clips (or music tracks) on the dashboard's page so that THIS computer processes them (hashing, previews, AI description) and uploads them to the archive.
- **Batch**: one ingest job registered on the dashboard; a computer "claims" it with a time-limited lease.
- **Sidecar**: a separately downloaded helper program (here: the local AI model runtime, `llama-server`) that the companion fetches and runs.
- **Base rig / wired**: a computer whose project tree is the NAS share itself (config `mode = "base"`, or `local_root` equal to the canonical prefix such as `P:\`). **Remote**: an editor computer holding a synced copy.

## The loopback server: starting, stopping, port, config files
(source: broll_server.py)

- **On/off switch**: config key `broll_server_enabled` (default `true`). When false the server does not start; log line "broll: Send-to-Resolve server disabled by config".
- **Port**: config key `broll_server_port` (default `8899`). Any value that is not an integer from 1 to 65535 (including `0`) falls back to 8899 with a warning. A typo here never counts as a config problem that stops sync.
- **Bind address**: always `127.0.0.1`. Not configurable.
- **Port reuse**: on macOS and Linux the server sets "reuse address" (skip the TIME_WAIT delay); on Windows it does not, so a second program already listening on 8899 makes the bind fail instead of silently sharing traffic.
- **Bind failure**: the server is simply absent; nothing else in the companion is affected. The warning names the usual cause: "the OLD standalone BRoll Companion still running (it is retired and its only job was this port): quit it from its own tray icon and remove it from startup, then restart this companion." The error text is kept and can be read back (`last_bind_error`) for the tray and the fleet report; it is cleared on a successful bind. A repeat of the same error text (the app retries the bind with backoff) logs at debug level only; a different error logs again at warning level.
- **Startup log line** names the b-roll mounts, the music mounts, the YouTube-downloader mounts and the allowed browser origins, or "NONE -- dashboard_url is blank, so no web page can drive this companion".
- **Each request is handled on its own thread**; worker threads die with the process.
- **Any unexpected error inside a request** answers HTTP 500 `{"ok": false, "message": "the companion failed to handle that request -- see its log"}` and logs the traceback. A request never goes unanswered.
- **Request logging** goes to the companion log at debug level only.
- **Server identity header**: `CCSyncCompanion/<companion version>`.
- **Stopping** (when the tray exits): in this order, (1) every on-demand archive download (rclone) is killed, (2) any YouTube download this machine is running is stopped, (3) the b-roll and music ingest orchestrators are stopped, (4) the listener is shut down and the port released. Never raises.
- **File `~/.broll-companion.json`** (the share-to-folder map, inherited from the retired standalone companion):
  - Created with defaults on first start if missing: `{"server_url": "http://127.0.0.1:8000", "mounts": {}}`.
  - `server_url`: read into the config but used by nothing in this part (documented as "not required").
  - `mounts`: share name to local folder. A non-object `mounts` becomes empty. Malformed JSON, an unreadable file or bad encoding falls back to defaults with a warning; it never stops the companion.
  - Read once at server start: editing it needs a companion restart.
- **File `~/.broll-companion.README.txt`**: written once if missing, explaining the fields above in plain words (the `broll` share needs no entry and defaults to `<local_root>/Assets/B-roll Archive`; an explicit `broll` entry switches off automatic downloading of missing clips; `music` defaults to `<local_root>/Assets/Music`; `projects` defaults to `<local_root>/Projects`; on macOS a share with no entry is probed at `/Volumes/<share>`, `-1`, `-2`; restart the companion after editing).
- **Default `broll` mount**: `<local_root>/Assets/B-roll Archive`, derived from `local_root` in `~/.ccsync/config.toml`. Used only when the JSON file has no non-blank `broll` entry. No default when `local_root` is blank. Existence of the folder is not checked.
- **Music and YouTube-downloader mount tables** are built at the same moment from the same JSON file by other modules (outside this section) and served under separate keys so a `broll` entry never leaks into them.

## Who may call the loopback server
(source: loopback_guard.py, broll_server.py)

- **Host header check (anti DNS-rebinding)**, applied to every request before anything else: the Host must be `127.0.0.1`, `localhost` or `::1` (bracketed form accepted) with the server's own port (a Host with no port is accepted only if the server port is 80). A missing or empty Host is accepted. Any other Host: 403 with the generic refusal.
- **Origin check**, applied to every request that carries an `Origin` header: the origin must exactly match (case-insensitive, no prefix/suffix matching; the literal `null` is refused) one of:
  - `dashboard_url` from `~/.ccsync/config.toml`, in both its `http://` and `https://` forms (same host and port; any user-info stripped);
  - `dashboard_url` from the cached site manifest (`~/.ccsync/state/site.json`), both schemes;
  - each entry of config key `loopback_extra_origins` (list; no default; escape hatch for a dashboard reached by a different name), both schemes;
  - DEV ONLY: when config key `loopback_dev_origins = true` (default false), any `http(s)://127.0.0.1|localhost|[::1]` origin on any port.
  - A refused origin gets 403 and no CORS headers. The log line names the refused origin, the list held, and says to set `dashboard_url` or `loopback_extra_origins` in `~/.ccsync/config.toml`.
- **Allow-list refresh**: rebuilt from config plus the cached site manifest at most every 30 seconds, so a re-provisioned dashboard address self-heals within a session. A rebuild failure keeps the last good list. The config half still needs a restart (the config dict is the one handed in at start).
- **Requests without an Origin** (curl, a browser tab opened directly on `/status`): GET requests are answered; POST and PUT need the loopback token.
- **Loopback token**: a random 32-byte URL-safe string written to `~/.ccsync/loopback-token` at every server start (a new token each session). Written to a temp file, permissions tightened (0600 on macOS/Linux, owner-only ACL on Windows), then renamed into place. A caller sends it as header `X-CCSync-Loopback`; compared in constant time against the file, re-read per request. If the file cannot be written the browser routes still work and local non-browser callers have no way in (warning logged).
- **POST and PUT authorisation**: an allowed Origin OR a valid token; otherwise 403.
- **POST content type**: must be `application/json` (parameters after `;` ignored); otherwise 415. (This forces browsers to send a permission preflight.)
- **Refusal body** (all 403/415 refusals): `{"ok": false, "message": ..., "error": ...}` both set to "this request was refused by the CC Sync companion - open Tray > Settings > OPEN LOG for the reason, or send Tray > Settings > HELP > COPY DIAGNOSTICS FOR YOUR ADMIN to your admin". The reason is only in the log.
- **CORS response headers** (only for an allowed Origin): `Access-Control-Allow-Origin: <that origin>`, `Access-Control-Allow-Headers: Content-Type, X-CCSync-Loopback, X-CCSync-Ingest`, `Access-Control-Allow-Methods: GET, POST, PUT, OPTIONS`, `Access-Control-Allow-Private-Network: true`. `Vary: Origin` is sent on every response.
- **OPTIONS (preflight)**: allowed origin gets 204 with the CORS headers; a preflight with no Origin gets 403.
- **Request body limits (POST)**: `Content-Length` must be a non-negative integer (else 400 "invalid Content-Length"); over 256 KB gives 413 "body too large (max 262144 bytes)". A body that is not valid JSON, or JSON that is not an object, gives 400 "invalid JSON body". An empty body counts as `{}`.
- **Unread body draining**: on any refusal of a POST or PUT, up to 1 MB of the remaining body is read and discarded first so the client sees the refusal instead of a connection reset.
- **Share name rules** (every route that takes a share): one path segment, 1 to 64 characters, no leading/trailing spaces, not starting with `.`, no `\`, `/`, `:` or control characters. Otherwise the request is a 400 ("invalid share name ...").
- **Rel path rules**: must be a string, non-empty, not absolute (no leading `/`, no drive letter like `C:`), no `..` component, no component ending in `:`. Backslashes are treated as separators; empty and `.` components are dropped. After joining, the result must still resolve (symlinks followed) inside the share folder ("rel_path escapes the share root"). All are 400s.
- **macOS share discovery**: for a share with no mount-table entry (or a blank one), the companion looks for `/Volumes/<share>`, `/Volumes/<share>-1`, `/Volumes/<share>-2` and uses the first that is a folder and resolves inside `/Volumes`. Windows and Linux do no probing.
- **A blank mount entry counts as absent**; a share with no mount answers "no mount configured for share '<share>'" (HTTP 200, `ok: false`); a non-string mount answers "the mount configured for share '<share>' is not a path".
- **Bundle protection helper** (used by other route groups' "reveal in file manager"): a path whose last component ends in `.app`, `.bundle`, `.framework`, `.kext`, `.plugin`, `.prefpane`, `.qlgenerator`, `.saver`, `.service`, `.workflow`, `.xpc`, `.appex`, `.pkg`, `.dmg` or `.mpkg` is recognised as something a file manager must never be pointed at.

## Route inventory of the loopback server
(source: broll_server.py)

Every route below is subject to the Host/Origin/token/content-type rules above. Unknown paths answer 404 `{"ok": false, "message": "not found: <path>"}` for GET, POST and PUT.

- `GET /status`: b-roll self-test. No token needed. Answers 200 `{ok: true, resolve_connected, mounts, version, loopback: {bound: true, port}, standins_owed}`. Details in "Send to Resolve (b-roll)".
- `POST /insert`: put a b-roll clip range into the editor's open Resolve timeline. Details below.
- `GET /music/status`, `POST /music/send`, `POST /music/reveal`: the music library's "Send to Resolve" and "show in folder". The dispatch is here; what they do lives in `music_server.py` (outside this section). Bodies are `{share, rel_path, ...}`; errors use the `error` key; a non-object JSON body gives 400 "invalid JSON body".
- `POST /ytdl/reveal`, `POST /ytdl/fetch`: the YouTube downloader page's "show in folder" and "pull this original to my computer". Behaviour lives in `ytdl_server.py` (outside this section); errors use the `message` key.
- `GET /ytdl/capabilities`: always 200; whether this computer can run YouTube downloads itself (`ytdl_executor.py`, outside this section). With no executor wiring it answers "cannot".
- `GET /ytdl/progress[?job_id=N]`: `{"jobs": [...]}` for what this computer is downloading; filtered to one job when `job_id` is an integer; an unparseable id is ignored (no 400).
- `POST /ytdl/download`: body `{job_id}` only; starts the local download of a job the dashboard defined (destination, URLs, quality all come from the server). Behaviour in `ytdl_executor.py`.
- `POST /ytdl/cancel`: body `{job_id}` or `{all: true}`. Stops downloads this computer started. Always 200: `{ok: true, stopped: N, message}` with message "Stopped. The server will download the clips this computer did not finish." or "There was no download running on this computer." (Not listed in the module's own header comment.)
- `GET|POST|PUT /broll/ingest/...` and `/music/ingest/...`: nine routes per kind (capabilities, pick, prepare, upload, progress, thumb, run, control, retry). Details in "Ingest routes on the loopback server".

## Send to Resolve (b-roll)
(source: broll_server.py)

- **`GET /status`**:
  - `resolve_connected`: whether DaVinci Resolve answered a scripting probe. The probe runs in a separate child process with a 20-second timeout (a stuck Resolve gets the child killed and reads as "no"), and results are cached and shared so many requests do not spawn many children.
  - `mounts`: the b-roll mount table in effect.
  - `version`: the companion version.
  - `loopback`: `{bound: true, port}` so a page can tell this companion apart from something else on the port.
  - `standins_owed`: list of `{local_path, rel_path, why}` for every stand-in whose editing-proxy download has permanently given up (so the editor knows they are cutting on the preview, not the editing proxy).
- **`POST /insert` body**: `share`, `rel_path`, `in_frame`, `out_frame`, `mode` (default `"append"`), optional `insert` object (advisory facts from the dashboard about the clip's files, see below).
- **Insert modes**: `append` (to the end of the timeline) and `playhead` (at the playhead). Any other mode: 200 `ok: false` "unknown insert mode '<mode>' -- this companion may need an update".
- **Frame checks**: `in_frame` and `out_frame` must both be integers, else 400 "in_frame and out_frame must be integers". `out_frame <= in_frame` gives 200 `ok: false` "out point must be after in point".
- **Path checks**: bad share or rel path gives 400 with the reason; no mount gives 200 `ok: false` with the reason.
- **The `insert` advisory object** (all fields optional; anything malformed is ignored field by field, it can never make an insert fail): `preview_rel`, `edit_proxy_rel`, `original_rel`, `original_is_edit_weight` (true/false/null), `geometry` (`width`, `height`, `fps`, `frames`, `start_tc`), `known` (false means the server could not list the archive folder), `original_pending` (true means the original exists but is still uploading). Every rel path in it goes through the same traversal rules; a bad one is ignored.
  - Without the object, preview and editing-proxy paths are guessed from the naming convention: `Proxy/<stem>.mp4` (preview) and `Proxy/<stem>.mov` (editing proxy) beside the original. If the named rel path is itself inside a `Proxy/` folder, it is treated as the preview and the editing proxy is `<same folder>/<stem>.mov`.
  - An explicit `null` for `preview_rel` or `edit_proxy_rel` means "there is none"; an absent key means "use the convention".
  - An explicit `null` for `original_rel` (when at least one tier field was accepted) means "the archive has no original for this clip".
  - `known: false` overrides everything: the object is treated as not judged, the original is assumed present, and the weight is reset to unknown.
  - An editing proxy path equal to the preview path is discarded.
- **Decision table** (which of four routes the insert takes):
  1. The file at the original's path is on disk: import it. If that file is a ledgered stand-in, it is still imported and a background editing-proxy upgrade may be (re)started; otherwise nothing downloads.
  2. File absent and this computer is wired (base mode, or `local_root` equals `canonical_prefix`): fetch the original (in practice the base-rig refusal below applies).
  3. File absent and the server said `known: false`: fetch the original.
  4. File absent and there is no original (explicit null, or the named rel path is the preview itself): "preview only", download the preview to its own path and import that.
  5. File absent and the original is light enough to edit (`original_is_edit_weight` true, or unknown without a dashboard-supplied editing proxy), or no preview is known: download the original.
  6. File absent, heavy, and the original's extension is not `.mov`, `.mp4` or `.m4v` (including camera-raw `.braw`, `.r3d`, `.crm`, and `.mxf`, `.avi`, `.mkv`, or no extension): "preview only".
  7. File absent, heavy, `.mov`/`.mp4`/`.m4v` original: stand-in, i.e. download the preview's bytes to the original's path and name, and owe an editing-proxy upgrade.
  - "Heavy" means `original_is_edit_weight` is false, or it is unknown while the dashboard supplied an editing-proxy path.
- **On-demand download of a missing clip** (only when all hold): the share is `broll`; the computer is not in base mode; the `broll` mount in effect is the derived default (an explicit entry in `~/.broll-companion.json` switches this off). Otherwise the answer is 200 `ok: false` "file not found at <path> - is the share mounted?".
  - Further refusals come from the fetch rules (see "On-demand archive downloads").
  - While downloading: 200 `{ok: false, state: "downloading", message: "syncing the clip to this computer: N%" (or "syncing the clip to this computer…" with no percent), progress}`. The page re-sends the same request about every 1.5 s to read progress; the request that finds the file in place carries on to the import.
  - When this computer's download slot is taken by another clip: 200 `{ok: true, state: "busy", retry_after: 1.5, message: "not sent yet: this computer is already downloading as much as it will at once. This one starts as soon as a slot is free"}`.
  - On failure: 200 `ok: false` "couldn't sync the clip from the NAS: <reason>".
  - A stand-in download writes a ledger "intent" row before the download starts (so a closed tab cannot leave an unrecorded stand-in) and removes that row if the download is refused as busy, fails, raises, or the file vanishes. When the bytes land, the row is rewritten with the real size and "upgrade pending" (if an editing proxy is known).
  - A download that finished between polls is noticed on the next poll, and a stand-in row is settled then.
- **The import itself** runs in a separate child process (same as `/status`) calling Resolve's media import and timeline insert with the path, in/out frames and mode. A child that does not answer is killed. The answer is the worker's `{ok, message}`; a non-dict answer becomes the generic Resolve scripting error message; a failure without a message uses its `error` text or "the Resolve worker failed".
- **After a successful insert of a stand-in** that owes an editing proxy: the background upgrade is started (and its retry budget reset, since an editor asked).

## Background editing-proxy upgrade for stand-ins
(source: broll_server.py)

- **What it does**: downloads the clip's editing proxy (`.mov`) from the NAS on a separate low-priority download lane, then asks Resolve (in a child process) to link it as the clip's proxy media, leaving the clip's file path on the original.
- **Triggers**: a successful insert of a stand-in; and the companion's relink cycle (every 120 s, called from elsewhere), which resumes every ledger row still "pending".
- **One upgrade per stand-in path at a time** in this process; a second request for the same path is ignored.
- **Polling**: checks every 2 s; gives up after 1 hour total ("the editing proxy did not finish downloading").
- **States written to the ledger**: `pending`, `done`, `failed` (with a reason). A path that fails the share/rel checks is `failed`. A download failure is `failed` (log says "the clip keeps the preview"). A file present but Resolve did not link it (Resolve closed, wrong project) stays `pending` and counts one spent attempt; past the ledger's attempt ceiling the 120 s cycle stops retrying until the editor sends that clip again.
- **A row already `done`** is never re-run.
- **Same 120 s cycle also settles intent rows**: for each stand-in intent row, it checks whether the file landed (reads the video header with this computer's ffmpeg, config `ffmpeg_path`, default `ffmpeg`), whether a real original arrived instead (row retired), or nothing ever landed (row retired). No Resolve call.

## Ingest routes on the loopback server
(source: broll_server.py)

Two route groups with identical shapes: `/broll/ingest/...` (video clips for the b-roll archive) and `/music/ingest/...` (tracks for the music library). The path prefix alone decides which orchestrator, staging folder and server prefix are used. If the companion has no orchestrator for that kind, routes answer 503 "<b-roll|music> indexing is not running on this computer" (capabilities answers 200 with a reason instead).

- **`GET /<kind>/ingest/capabilities`**: always 200; `ok` true only if `reasons` is empty. Does no slow work (one free-space check; GPU, model cache and encoder list come from cached snapshots; rclone presence from a PATH lookup).
  - b-roll answer: `ok`, `reasons`, `version`, `ffmpeg` (found), `nvenc` (true/false, or null when encoders have not been probed yet), `rclone`, `gpu` {`present`, `vram_gb`, `detail`, `apple_silicon`}, `tiers` {`good`, `best`: each `fits`, `reason`, `cached`, `vram_gb` (Apple unified-memory figure on Apple Silicon), `download_bytes` (0 if cached, else weights plus vision projector size), `label`}, `recommended_tier`, `runtime_cached`, `staging` {`dir`, `free_bytes`, `floor_bytes`}, `busy` {`batch_uid`, `state`}, `signed_in`, `run_modes` (`idle`, `foreground`).
  - b-roll reasons (exact strings): the "good" tier's reason or "this computer's GPU cannot run the b-roll indexing model" when neither tier fits; "ffmpeg is not installed on this computer yet: it is fetched the first time a batch runs"; "rclone is not installed on this computer, so indexed clips could not be uploaded to the NAS"; "this computer has no synced tree, so there is nowhere to stage the clips"; "only X GB free where the clips would be staged (the floor is Y GB)"; "this computer is already indexing a b-roll batch"; "nobody is signed in on this computer"; "b-roll indexing is switched off on this computer".
  - Note: a missing ffmpeg makes `ok` false even though the reason says ffmpeg will be fetched at batch time.
  - music answer: `ok`, `reasons`, `version`, `kind: "music"`, `ffmpeg`, `rclone`, `clap` {cached, download_bytes, version, runtime, providers, feed, dim} (CLAP is the audio embedding model, about 280 MB, runs on CPU; no GPU gate), `audio_exts`, `transcode_exts`, `max_file_bytes` (512 MiB), `max_items`, `staging`, `busy`, `signed_in`, `run_modes`. Reasons: the CLAP module's refusal text if any; the ffmpeg sentence; "rclone is not installed on this computer, so indexed tracks could not be uploaded to the library"; "...nowhere to stage the tracks"; "only X GB free where the tracks would be staged (the floor is Y GB)"; "this computer is already indexing a music batch"; "nobody is signed in on this computer"; "music indexing is switched off on this computer".
- **Staging free-space floor**: config key `broll_ingest_free_space_floor_gb` (default 20 GB) and `music_ingest_free_space_floor_gb` (default from the music kind, see "Ingest kinds"). Negative values count as 0.
- **Staging folder**: b-roll `<local_root>/Assets/B-roll Archive/.ingest`, overridable by config key `broll_ingest_staging_dir` (meant for the base rig, whose tree is the NAS). None (no ingest possible) when no `local_root`.
- **`POST /<kind>/ingest/pick`**: body `{kind: "files" | "folder"}` (default "files"; anything else 400 "kind must be 'files' or 'folder'"). Opens the operating system's native file or folder picker on this computer (timeout 300 s). Folder picks are walked for allowed extensions (b-roll: `.mp4 .mov .m4v .mxf .mts .m2ts .avi .mkv .webm`; music: the music kind's audio list). Answers `{ok: true, files: [...]}` with real local paths; `{ok: false, message: "cancelled"}` when nothing was picked; the picker's own "busy" message when another CC Sync window is open; "the file picker could not be opened on this computer" on any other failure. The returned paths are recorded as the only local paths a later `prepare` may name ("index in place" with no copy).
- **`POST /<kind>/ingest/prepare`**: body handed to the orchestrator (see "B-roll ingest: preparing a drop").
- **`PUT /<kind>/ingest/upload/{staging_id}/{local_id}`**: streams one dropped file's bytes into staging.
  - Path pattern: staging id 1 to 64 of `A-Za-z0-9_-`; local id 1 to 80 of `A-Za-z0-9_.-` (URL-decoded). Other paths 404.
  - Content type must be `application/octet-stream` (else 415), AND the request must carry header `X-CCSync-Ingest` (any non-empty value) or the loopback token (else 403).
  - The orchestrator must recognise the slot (else its own status and message). The destination must resolve inside the staging root (else 403).
  - Music only: a declared size over 512 MiB is refused with 413 "that track is N MB and the library takes at most 537 MB per file".
  - Free space: if free space minus the declared size would fall under the floor, 507 "not enough space to stage this clip: it needs X GB and only Y GB is free (the floor is Z GB) -- free some space and drop it again".
  - Byte limit: declared size plus the larger of 1% or 64 KB; with no declared size, 256 KB. Missing Content-Length: 411 "this upload needs a Content-Length"; invalid: 400; declared over limit: 413 "this file is bigger than the N bytes the companion was told to expect"; sending more than declared: 413 "this upload sent more than it declared -- nothing was kept"; client hung up: 400 "the upload stopped before the whole file arrived"; disk error: 507 "the companion could not write the clip to its staging folder -- <reason>" or "...could not finish writing the clip into staging".
  - Written as `<name>.partial` in 1 MB chunks and renamed into place only when complete; partial files are deleted on every failure.
  - On success the orchestrator records the byte count and its answer is returned.
- **`GET /<kind>/ingest/progress[?staging_id=]`**: the orchestrator's progress snapshot.
- **`GET /<kind>/ingest/thumb?staging_id=&local_id=`**: one JPEG thumbnail of a staged item, `Cache-Control: no-store`; or the orchestrator's error JSON.
- **`POST /<kind>/ingest/run`**: body `{batch_uid, staging_id, run_mode}`; `run_mode` is `idle` or `foreground`; a body with no `run_mode` but `start_now: true` means `foreground`. Nothing else in the body is read; the work order comes from the server.
- **`POST /<kind>/ingest/control`**: body `{action}` handed to the orchestrator (pause/resume/cancel etc., see below).
- **`POST /<kind>/ingest/retry`**: body `{items: [local ids]}` re-arms failed uploads of this drop. If the body also carries `batch_uid` (and the re-arm succeeded), the companion immediately claims and runs that batch again (`run_mode`/`start_now` as for run) and adds `retried` to the answer.

## On-demand archive downloads (one clip or one track)
(source: broll_fetch.py)

- **Purpose**: pull exactly one file from the NAS to the place a full sync would have put it, when an editor sends a clip or track to Resolve that is not on this computer. Three NAS folders can be the source: `Assets/B-roll Archive` (b-roll clips and their previews/editing proxies), `Assets/Music` (music tracks, used by the music route group), `Projects` (YouTube originals the server downloaded, used by the YouTube downloader's fetch route).
- **Transfer**: one `rclone copyto <remote>:<remote_root>/<folder>/<rel_path> <local destination>` per file, using the companion's download route settings (a separate download remote, `remote_down`, when configured, otherwise `remote` + `remote_root`), the same tuning flags and transport flags as the sync lanes, JSON logs, progress stats every 1 s. rclone writes `<name>.partial` and renames when complete, so a killed download never leaves a truncated file under the real name.
- **Joining**: downloads are keyed by destination path; a repeat click or a progress poll for the same destination joins the running download instead of starting another.
- **Concurrency caps**: at most 2 foreground downloads at once (clips an editor is waiting for); at most 1 background download at once (stand-in editing proxies). The lanes are counted separately so a background download never makes a foreground click wait. At the cap nothing is queued or recorded: the answer is `busy` with `retry_after: 1.5` and the busy message above, and the caller must ask again.
- **States**: `downloading` (with progress: `bytes`, `total_bytes`, `speed_bps`, `eta_seconds`, and `percent` 0 to 100 when a total is known), `busy`, `done`, `failed` (with message). A finished (done or failed) download is forgotten when read; after `failed` the next request starts again from scratch; after `done` the caller re-checks the disk. A caller that finds the file already in place also clears the finished record.
- **Refusals before starting** (editor-facing text shown in the web page's toast):
  - no `remote` in config: "this computer's sync config names no rclone remote, so the clip can't be fetched from the NAS (remote= in ~/.ccsync/config.toml)";
  - no `remote_root`: "this computer's sync config has no remote_root, so the clip can't be fetched from the NAS (remote_root= in ~/.ccsync/config.toml)";
  - rclone not usable: "can't fetch the clip from the NAS -- <detail>";
  - no `local_root`: "this computer's sync config has no local_root, so there is nowhere to put the file (local_root= in ~/.ccsync/config.toml)";
  - destination outside this computer's tree: "that file is outside this computer's tree -- nothing was downloaded";
  - tree folder absent or mounted in the wrong place (for example an unplugged external drive or an unmounted macOS volume): "this computer's tree isn't mounted right now, so nothing can be downloaded into it -- reconnect the drive and try again". A tree check that could not decide lets the download proceed.
  - a download thread that could not be started: "this computer could not start the download (<error>)".
- **Failure messages**: "could not start rclone: <error>"; the last error line rclone logged (ignoring its generic "fatal error received" notice); "rclone exited with code N"; "the download finished but <path> is still missing"; "cancelled -- the companion shut down".
- **On Windows** rclone is started without a console window (the lane's creation flags).
- **Shutdown** kills every running download.

## Stand-in ledger (remembering which archive files are really previews)
(source: broll_standins.py)

- **File**: `<companion log folder>/state/broll_standins.json` (normally `~/.ccsync/state/broll_standins.json`). Format `{"version": 1, "standins": {<normalised path>: entry}}`. Written atomically (temp file named with the process id, then renamed). Re-read whenever its modification time or size changes, so another process's write is picked up.
- **Entry fields**: `local_path` (exact path as on disk), `share`, `rel_path`, `original_rel`, `preview_rel`, `edit_proxy_rel`, `geometry` (the original's width/height/fps/frames/start timecode as the dashboard sent it), `placed_at`, `placed_at_iso`, `size` (the stand-in's size in bytes, or null), `pending_fetch` (true while the row is only an intent written before the download), `upgrade` (`pending`/`done`/`failed`/null), `upgrade_note`, `upgrade_attempts`.
- **Path matching**: paths are compared after Unicode NFC normalisation (macOS file names arrive decomposed), case folding and separator folding; the stored path keeps the exact bytes.
- **Every new stand-in logs a warning**: "<path> now holds the PREVIEW's bytes, not the original. Resolve will read its geometry from that file, and a render on this computer would render it".
- **"Is this a stand-in?"**: yes if there is an entry and its file has the recorded size (or the size was never known, or the file is absent). A different size means the real original has replaced it, so it is no longer a stand-in.
- **"Is this stale?"**: an entry exists and the file on disk now has a different size. Used by the relink pass (elsewhere) to know the Resolve clip still carries the stand-in's geometry.
- **Settling intent rows** (every 120 s from the relink cycle):
  - if a file has appeared: its header is read with ffmpeg. Width/height different from the original's geometry means the stand-in landed (row gets its size). Same geometry means the real original arrived (row removed, log "the real original arrived at <path>, so the stand-in entry goes"), except when the original is no taller than the preview height (1080) with even sides, where only a codec other than H.264 proves it is the original. When the header cannot decide, the download record decides: done means stand-in, failed means remove, unknown (for example after a restart) leaves the row pending.
  - if no file after 6 hours: the row is removed ("no file ever arrived at <path> -- the download did not happen"), but only if the archive folder itself exists right now.
- **Pruning**: rows whose file is gone and that are older than 30 days are dropped when the ledger is loaded, but only if the archive folder exists right now (an unplugged drive never wipes the ledger). Log "forgot N entr(ies) whose file has been gone for over 30 days".
- **Upgrade attempt ceiling**: 8. A row pending with 8 or more spent attempts is no longer retried by the cycle and is reported as "given up" (alongside `failed` rows) in `GET /status`'s `standins_owed`. An editor's new insert of that clip resets the count.
- **Fleet report**: the companion's report to the dashboard (built elsewhere) carries `standins_placed`: `{rels: [archive-relative paths of every original this computer has ever stood in for, stale or not, de-duplicated, NFC], checked_at}`, at most 200 entries. An empty list is sent as a positive "none here".
- **"Is this path inside the b-roll archive?"**: true for paths under `<local_root>/Assets/B-roll Archive` or `<canonical_prefix>/Assets/B-roll Archive` (judged in that root's own spelling). The Resolve watcher (elsewhere) uses this to exclude archive clips from its "missing media" count, because an offline original in the archive is normal on a remote computer.
- **Corrupt file**: treated as empty with one warning per corruption ("A clip inserted as a stand-in before now will look like the real original to this companion"). A failed write is logged and the in-memory state is rolled back; nothing in the ledger ever raises to its caller.

## Ingest kinds: what differs between b-roll and music ingest
(source: ingest_kinds.py)

- **Two kinds exist**: `broll` and `music`. An unknown kind name falls back to b-roll.
- **b-roll kind**: label "b-roll"; dashboard (server) route prefix `/broll/api/fleet/ingest`; loopback prefix `/broll/ingest`; local state file `broll_ingest.json`; config key prefix `broll_ingest_`; progress window title "INDEXING B-ROLL"; counts in "clip"s; accepts `.mp4 .mov .m4v .mxf .mts .m2ts .avi .mkv .webm` (camera raw `.braw`, `.r3d`, `.crm` deliberately not accepted, because ffmpeg cannot decode them); a running batch makes this computer's proxy generator stand aside, showing "indexing b-roll first"; uses a model tier; fleet report section `broll_ingest`; at most 2,000 items per prepare; default staging free-space floor 20 GB.
- **music kind**: label "music"; server prefix `/music/api/fleet/ingest`; loopback prefix `/music/ingest`; state file `music_ingest.json`; config prefix `music_ingest_`; window title "INDEXING MUSIC"; counts in "track"s; accepts `.wav .mp3 .flac .aac .m4a .ogg .aiff .aif .opus`; `.ogg` is transcoded on this computer before upload; never stands proxy generation aside; no model tier; report section `music_ingest`; at most 500 items per prepare; default free-space floor 2 GB; an item is finished when `live`, `duplicate`, `cancelled`, `skipped` or `queued_for_base_rig` (the last means this computer could not compute the audio embedding and left the work for the base rig).
- **Per-kind config keys** are all `<prefix>_<suffix>`, for example `broll_ingest_idle_seconds` and `music_ingest_idle_seconds`.
- **Staging folder per kind**: config key `<prefix>_staging_dir` overrides; otherwise b-roll stages in `<local_root>/Assets/B-roll Archive/.ingest` and music in `<music library folder>/.ingest` (by default `<local_root>/Assets/Music/.ingest`). No `local_root` means no staging and no ingest.
- **Upload URL per item**: `<loopback prefix>/upload/<staging_id>/<local_id>`.

## B-roll (and music) ingest on this computer: overall flow
(source: broll_ingest.py)

The same orchestrator serves both kinds; music overrides only the per-item work (in `music_ingest.py`, outside this section). Everything below applies to both kinds unless it says b-roll.

- **The flow as an editor sees it**: (1) on the dashboard's b-roll page the editor drops files (or presses "choose from this computer", which opens the native picker); (2) the page asks this computer to `prepare` staging slots; (3) dropped files are streamed into staging, picked files are indexed where they are; (4) each staged file is probed and hashed so the page can ask the server about duplicates; (5) the page creates a batch on the server and tells this computer to `run` it; (6) this computer claims the batch, makes previews, editing proxies, stills and frames, describes every clip with a local AI model, posts the description, uploads everything to the NAS archive with rclone, and the server flips each clip live.
- **Feature switch**: config key `broll_ingest_enabled` (default true; `music_ingest_enabled` for music). Off means the worker never starts, the gate reads "disabled", and `run` answers 503 "<b-roll|music> indexing is switched off on this computer".
- **State file**: `<companion state folder>/broll_ingest.json` (music: `music_ingest.json`). Holds the current batch with every item's stage and outputs, every staging drop, the remembered picker folders, the paused, forced and upload-paused flags, the current warning and a timestamp. Rewritten atomically (compact JSON) at every checkpoint, roughly a dozen times per clip.
- **Resume after a restart**: the saved batch is reloaded; any unfinished item whose source file is gone is failed with "the source file is no longer on this computer (the drive was unplugged, or it was moved)"; the batch is marked to be re-claimed on the next tick. An unreadable state file means starting clean (log only).
- **Worker cadence**: one pass ("tick") every 15 seconds, or immediately when woken by an action. A failing tick is logged and the next one runs.
- **Each tick, in order**: re-claim a resumed batch if needed; evaluate the gate; if the model is missing and there is work, download it; open the progress window once per batch when work starts; crunch items while the gate stays open; stop the local model server whenever not running (gives the GPU memory back at once); pump uploads; finish the batch if nothing is outstanding; run the staging retention sweep.

## Ingest gate (when this computer is allowed to crunch)
(source: broll_ingest.py)

Checked in this order; the first that applies is the state shown:

- `disabled`: `broll_ingest_enabled` is false.
- `drive-absent`: `local_root` is not configured or not a folder right now (a check that errors counts as present). Window note "waiting: the sync drive is not connected".
- `paused`: paused from the tray or the page, or the companion-wide pause. Note "paused".
- `misconfigured`: the companion's blocked check says the sync config is broken. Note "waiting: this computer's sync config needs fixing".
- `no-ffmpeg`: ffmpeg not available at `ffmpeg_path` (default `ffmpeg`). Note "waiting for ffmpeg to be installed".
- `no-model` / `tier-unfit`: the batch's model tier (default "good") is not downloaded (`no-model`, note "fetching the local indexing model") or this GPU cannot run it (`tier-unfit`; a tier that does not fit is reported as unfit even if the weights are missing, so nothing is downloaded for it). On first entering `tier-unfit` the reason is shown as a warning.
- `nothing-to-do`: no batch, or every item finished or failed twice.
- `user-active` (idle run mode only): the person has not been away from keyboard and mouse for at least `broll_ingest_idle_seconds` (default: the value of `proxy_gen_idle_seconds`, itself default 300 s). An idle reading that cannot be taken counts as "not away". Note "waiting until you're away from the keyboard".
- `resolve-open` (idle run mode only, and only when `broll_ingest_skip_while_resolve` is true, the default): DaVinci Resolve is running (a check that errors counts as running). Note "waiting: DaVinci Resolve is open".
- `running`.
- **Run modes**: `idle` (only crunch while the editor is away and Resolve is closed) and `foreground` (crunch now). "Start now" from the tray or page forces foreground until the batch ends or is paused.
- **The gate is re-checked between every stage of every clip**, so an editor returning costs at most the stage in progress.
- **Indexing beats proxy generation** (b-roll only): while a b-roll batch is running or downloading its model, this computer's proxy generator (elsewhere) stands aside and shows "indexing b-roll first". Music never blocks it.
- **Sleep prevention and shutdown text**: while running or downloading the model, the companion's shutdown and keep-awake guard is given "still indexing <b-roll|music> (N <clip|track>(s) left)" or "still downloading the <kind> indexing model".

## Preparing a drop (staging)
(source: broll_ingest.py)

- **`prepare` body**: `{items: [{local_id, name, size, source: "upload" or "path", path (for source "path"), rel_dir}]}`.
- **Whole-request refusals**: no items: 400 "no clips were offered"; more than the kind's limit (2,000 b-roll, 500 music): 413 "that is N clips; 2000 is the most one batch can hold"; no staging folder: 503 "this computer has no synced tree, so there is nowhere to stage the clips"; not enough room for the floor plus the total size of all "upload" items: 507 with the space message below; staging folder cannot be created: 507 "the companion could not create its staging folder -- <reason>".
- **Per-item refusals** (the rest of the drop still stages): extension not accepted: "<.ext> is not a video this machine can index" (music: "an audio file this machine can index"); for picked paths: "no path was given for that clip", "that file is not on this computer", "that file could not be read", "that is not a video this machine can index", or "that file was not chosen on this computer: use the "choose from this computer" picker and pick it again" (the path is not inside a folder the native picker returned; an empty list refuses everything).
- **Remembered picker folders**: up to 32 most recent folders, saved in the state file so a restart between picking and preparing still works. For a folder pick the folder the editor chose is remembered, not each sub-folder.
- **Staging layout**: a new folder `<staging root>/<16 hex characters>/` with an `out/` sub-folder; each uploaded item is saved as `<local_id><ext>`. Local ids are cleaned to letters, digits, `-`, `_`, `.`, at most 64 characters (default `item<N>`); `rel_dir` is cleaned of `.` and `..` and capped at 255 characters; a missing name becomes `clip<N>`.
- **Answer**: 202 `{ok: true, staging_id, items: [{local_id, accepted, reason or upload_url}]}`.
- **Background probing**: after prepare, a background thread probes (ffprobe) and hashes every picked-in-place file. Uploaded files are probed and hashed as soon as their upload completes. Staged item states: `waiting`, `ready`, `failed` (with "the file is not there" or "this file could not be read (<error>)"). A hash failure alone does not fail the item.
- **Upload slot rules**: unknown staging id or item: 404 "no such upload slot -- prepare first"; a picked-in-place item: 409 "that clip is being indexed where it already is, not uploaded"; already fully uploaded: 409 `{already: true, message: "that clip is already staged"}` (the page treats this as success, so a reconnecting page never re-sends a big file).
- **Upload completion answer**: `{ok, size, hash, probe, state, error}`.
- **Retry of failed staged files** (`/retry`): body `{staging_id?, items?: [local ids]}`. No items means every failed item in that drop; no staging id means every drop. A malformed staging id: 400 "that is not a staging id". Failed items go back to `waiting`, their leftover `.partial` upload file is deleted, picked-in-place items are re-probed. Answer `{ok: true, retried: N}`; retrying something not failed is a harmless no-op.
- **Thumbnail** (`/thumb`): returns the JPEG made for that staged item, only if it is inside that staging folder (else 403 "refused"); 404 "no such clip" or "no preview for that clip yet".
- **Progress** (`/progress`, polled about every 1.5 s by the page): `{failed_items, staging: {id, items: [{local_id, state, name, size, hash, probe, rel_dir, error}]}, batch: {uid, state, gate, forced, paused, upload_paused, done, failed, total, queued_for_base_rig, queued_names, failed_items, warning, eta_seconds, current: {name, stage, percent}, upload: {...}, model: {tier, ready, percent, rate_bytes_per_s, eta_seconds, note}}}`. No disk access.

## Running a batch (claim, lease, heartbeat)
(source: broll_ingest.py)

- **`run` refusals**: batch id not 32 lowercase hex characters: 400 "that is not a batch id"; this computer already holds a different batch: 409 "this computer is already indexing another batch"; indexing disabled: 503; no `dashboard_url` or `dashboard_token`: 503 "this computer has no dashboard URL or token configured"; nobody signed in (no identity token): 503 "nobody is signed in on this computer"; staging id given but unknown: 409 "those clips are no longer staged on this computer - drop them again"; dashboard unreachable: 503 "this computer could not reach the dashboard to claim the batch"; claim refused: the server's message, with status 403, 409 or 410 passed through (other statuses become 503), default text "the dashboard would not hand over this batch"; tier does not fit this GPU: 503 with the reason and `reason: "tier_unfit"` (the batch is not released, so another of the editor's computers can take it after the lease expires); claim names no staging id while this computer is holding a staging drop with those same files: 409 `reason: "staging_id_missing"` "this computer has those clips staged, but the request did not say which drop: reload the page and try again".
- **The claim** (`POST <dashboard>/broll/api/fleet/ingest/batches/<uid>/claim`, music `/music/api/fleet/ingest/...`): sends machine name, companion version, tier and the full capabilities answer. Receives the work order: settings (tier, run mode, `upload_originals`), share, archive folder on the NAS (`archive_remote_rel`, fallback `Assets/B-roll Archive`), category list (taxonomy), heartbeat interval, the server-side upload-paused flag, and each item's id, video id, original name, sub-folder, size, hash, archive folder and file stem, final archive path, duplicate status and state. The browser's choice of run mode overrides the stored one for this computer.
- **Matching manifest rows to staged files** (each staged file used at most once, rows and files taken in their original order): by content hash first; then name + sub-folder + size; then name + sub-folder; then name + size in any folder; then name alone. A file whose known hash differs from the row's known hash is never paired. Unmatched rows have no source file (they fail with "the source file is not on this computer any more"). Music uses its own simpler matcher.
- **Answer**: 202 `{ok: true, batch_uid, state: "claimed" or "waiting-for-model", run_mode, tier}`.
- **Every server call** carries `X-CCSync-Token` (shared fleet token), `X-CCSync-Identity` (the signed-in editor's token) and `X-CCSync-Machine` (this computer's name); a name with non-Latin-1 characters is sent percent-encoded in `X-CCSync-Machine-Pct` instead. Redirects are never followed. Timeout 20 s.
- **Heartbeat**: every 30 s (or the server's `heartbeat_seconds`). The reply can say `cancel_requested` (the batch is cancelled locally, "cancelled from the dashboard") or change `upload_paused` (uploads pause or resume to match). A network failure is ignored until the next beat.
- **Lease lost** (any HTTP 410 from the server, or 403/409/410 on a re-claim): the batch is dropped quietly; running ffmpeg, uploads and the model server are stopped; staged files are kept; the retention clock starts.
- **Re-claim after restart**: on the first tick after a resume the claim is re-sent (the server treats it as idempotent for the same machine). Unreachable dashboard: tried again next tick. Settings, taxonomy, heartbeat interval, archive folder and upload-paused flag are merged from the reply; items already uploading are re-queued for upload.
- **Dashboard cancel through the report reply**: the companion's regular report reply can carry `commands.broll_ingest.cancel: [batch uids]` (music: `commands.music_ingest`); a matching batch is cancelled with reason "cancelled from the dashboard".
- **Report to the dashboard** (section `broll_ingest` of the companion's regular report; music has its own section): empty when there is no batch and no warning; otherwise `active, batch_uid, state, gate, done, failed, total, clip` (first 255 characters), `percent` (0 to 100), `tier, run_mode, uploading, upload_paused, model_download_percent, warning` (255 characters), `at`.
- **Staging report** (`ingest_staging` in the report): bytes, number of drops, oldest timestamp, and bytes split into finished, never-run and held.

## Per-clip processing (b-roll)
(source: broll_ingest.py)

Each clip goes through these stages, saved after each so a restart resumes where it stopped. Item stages shared with the server: `pending, proxying, framing, describing, indexed, uploading, live, failed, duplicate, cancelled, skipped`. Every stage change is posted to the server (`.../items/<uid>/status` with `stage_percent`, attempts, hash, probe); a failed post is ignored (the next one carries the newer stage).

- **Attempts**: each clip may be tried at most 2 times; after that it is left failed. An unexpected error fails the clip with "this clip could not be indexed: <error>" and moves on.
- **Source check**: a missing source fails with "the source file is not on this computer any more".
- **Probe and hash** (if not done yet).
- **1. Browser preview** (`<video id>.mp4`, 1080p H.264; progress 10%): encoded to `.partial`, NVENC (NVIDIA hardware encoder) first if the ffmpeg build has `h264_nvenc`, then one CPU retry. Accepted only if it decodes to at least 97% of the source's duration AND has exactly the source's frame count (when both counts are known). Otherwise the clip fails with "the proxy did not decode -- this clip was skipped" or "the proxy has N frames, the original has M - Resolve would refuse it". Encode time limit: the largest of the media timeout (900 s), the proxy generator's stuck floor, and the clip duration times the proxy generator's stuck factor (fallbacks 1800 s and 60x if those cannot be read).
- **2. Editing proxy** (`<video id>.mov`; progress 25%): skipped, with the reason recorded, when the original is camera raw (`.braw`, `.r3d`, `.crm`, or codec braw/r3d/redcode/crm: "needs Resolve") or already light enough to edit with ("original is edit-weight"; an unknown bitrate counts as heavy, so it is made). Otherwise encoded with the same recipe the companion's project proxy generator uses, carrying the source timecode, through the same NVENC-then-CPU and verification loop. If it cannot be made the clip continues without it (reason "the editing proxy could not be encoded" or the frame-count sentence); it does not fail the clip.
- **3. Stills** (progress 40%), made from the preview: a poster (`.poster.jpg`), a sprite sheet (`.sprite.jpg`, a grid of small frames for hover-scrubbing; the cell size is measured from the finished image when Pillow is available), and a thumbnail (`.thumb.jpg`) if the item has none yet. Failure of a still is not fatal.
- **4. Frames** (stage `framing`, 55% to 65%): scene detection on the preview, gaps filled, then one JPEG per timestamp into `<staging>/sheets/<video id>/frames/frame_NNNN.jpg` plus `frames.json`. Up to `broll_ingest_max_concurrent_ffmpeg` (default 2, clamped to 1 to 8) frame extractions run in parallel. If stopped midway no `frames.json` is written, so the clip is redone.
- **5. Describe** (stage `describing`, 70%): the local vision model server is started for the batch's tier and the clip's frames are described (see "Local clip description"). Failure: "the local model could not describe this clip (<error>) -- see <model server log path>", or the sidecar's own error.
- **6. Post the result** to the server (`.../items/<uid>/result`): segments, themes, quality flags, category hint, model name, and from the probe duration, fps, width, height, codec, shot date, plus sprite cell width, cell height, columns, cell count and interval. A refusal fails the clip with "the archive would not take this clip's description: <detail>" and the next attempt re-describes. On success the stage is `indexed`.
- **7. Upload** (stage `uploading`, 90%): see below.
- **Timing**: each completed clip's duration feeds the remaining-time estimate.

## Uploading results and taking clips live
(source: broll_ingest.py)

- **What is uploaded per clip** (remote paths relative to the archive): `posters/<video id>.jpg`, `sprites/<video id>.jpg`, `<archive dir>/Proxy/<stem>.mp4` (preview), `<archive dir>/Proxy/<stem>.mov` (editing proxy, if made), and `<archive dir>/<final name>` (the original, only when the batch setting `upload_originals` is true, the default).
- **Before queuing**, every file is checked; if the original (or everything) is missing, the clip fails with "the files for this clip are not on this computer any more, so it could not be uploaded". The original is queued first so a failure cannot leave stills orphaned; the queue itself sends in its own order (see "Upload queue").
- **Early live**: as soon as every file except the original has landed, the server is told (`.../uploaded` with `original_uploaded: false`) so the clip goes live on its proxies while a large original is still uploading. A refusal of that early post is ignored.
- **Final report** when everything has landed: `.../items/<uid>/uploaded` with each file's path and size, `original_uploaded`, and the editing-proxy path if one was made. Outcomes:
  - 200: the clip is `live`; the companion moves its own preview and editing proxy into its local archive copy (`<local_root>/Assets/B-roll Archive/<dir>/Proxy/`) so sending that clip to Resolve on this computer needs no download (skipped if a file is already there).
  - 409 with a `missing` list: the item is re-queued for upload; after 3 attempts the clip fails with "the archive never saw these files: <up to 3 names>".
  - other 4xx: the clip fails at once with the server's message or "the archive refused this clip (HTTP N)".
  - 5xx and anything else: retried, up to 3 attempts, then "the archive would not take this clip (HTTP N)".
- **An rclone failure** on one file: that file alone is re-sent, up to 3 attempts, then the clip fails with rclone's error.
- **A file the queue has lost track of** for 3 consecutive pumps fails the clip: "the upload of N file(s) never started on this computer". An item in `uploading` with nothing declared fails: "this computer has no files left to upload for this clip".
- **A clip already live whose original then fails**: it stays live (it is usable), the failure is logged as a warning ("... is live with its proxies, but its original never reached the archive ... its original has to be uploaded again"), and its staging drop is held so the only copy is not deleted. When a later retry uploads the original, the hold is released.
- **Batch end**: when nothing is outstanding the batch is released to the server as `done` (or `failed` if every clip failed) with `{done, failed, total}` and, if any live clips are missing their original, `originals_failed` and up to 10 `originals_owed` names (warning logged). The upload queue, model server and batch are put down and the retention clock starts.

## Ingest controls, notifications and the progress window
(source: broll_ingest.py)

- **Control actions** (page `/control` and tray, same effect): `pause` (also clears "start now"), `resume`, `start_now` (force foreground, unpause), `cancel`, `pause_upload`, `resume_upload`. Unknown action: 400 "unknown action '<x>'". Answer `{ok: true, state: <gate>, batch: <uid>}`.
- **Cancel**: stops ffmpeg (terminate, then kill after 5 s), uploads and the model server; releases the batch to the server as `cancelled` with the reason ("cancelled on this computer" or "cancelled from the dashboard"); staged files are kept for the retention window.
- **Tray balloons** (title from the site's notification title for the kind):
  - each new warning, once (for example the tier-unfit reason);
  - before a model download: "Downloading the Good b-roll indexing model (3.9 GB). Right-click the tray icon to see progress." (tier name and size vary);
  - after it: "The b-roll indexing model is ready. Indexing starts now."
- **Progress window** (shared work window): opened once per batch when work starts (closing it is respected). Title "INDEXING B-ROLL" or "INDEXING MUSIC". Shows: a headline while the model downloads ("Downloading <name>: 61% at 38 MB/s, about 1 min left"; time phrases "almost done", "about N sec left", "about N min left", "about Hh Mm left"); the current clip and stage with its percent; done, total and failed counts in clips or tracks; a remaining-time estimate; a note (the warning, or the gate note listed above; for music, "Waiting for the computer that is wired to the server: N tracks still on this computer." when items are queued for the base rig). Buttons: Cancel, Pause or Resume, and Start now (only while waiting for the editor to be away or for Resolve to close). Shown as finished when done + failed + queued equals total.
- **Status for the tray** includes up to 20 failed clip names with their reasons and up to 20 names queued for the base rig.

## Staging retention and disk space
(source: broll_ingest.py)

- **Retention**: finished drops are deleted after 7 days by default, counted from when their batch ended. Config key as actually read: `broll_ingest_ingest_staging_retention_days` (music: `music_ingest_ingest_staging_retention_days`); 0 means delete as soon as the batch ends. Swept every tick.
- **Never-run drops** (staged but no batch ever ended) are also deleted by the sweep once both their staging time and the newest file inside are older than the retention period.
- **Never deleted**: the drop of the batch currently running; drops holding files for the base rig or holding an original the archive lacks (logged "kept N staged file(s) the base rig still has to finish").
- **CLEAR FINISHED STAGING** (a button in the tray's Settings window, elsewhere): runs the sweep with age 0; it removes finished drops only, never never-run or held ones, and reports how many were kept back.
- **A folder that cannot be deleted** (for example a file still open on Windows) is retried next tick.
- **Not-enough-space message** (prepare): "Not enough space where the clips would be staged (<folder>): X GB free, and this drop needs Y GB on top of the Z GB floor" (or ", and Z GB is the floor"), followed by one of: ". N GB of that drive is finished b-roll staging: open Settings from the tray icon and use CLEAR FINISHED STAGING"; ". N GB of that drive is b-roll staging that was never indexed: open the b-roll page and index or re-drop it, and it is cleared automatically after 7 days"; ". Free some space and it will continue"; and, if any, ". N GB more is b-roll staging kept on this computer because the archive does not have those files yet; it is released once they reach it". An unmeasurable disk is never a refusal.
- **Free-space floor in the orchestrator**: `broll_ingest_free_space_floor_gb` or `music_ingest_free_space_floor_gb`, default 20 GB here for both kinds.

## Ingest media recipes (what ffmpeg produces for each clip)
(source: broll_ingest_media.py)

- **Content fingerprint** (used by the server to spot duplicates): xxh64 of the first 8 MiB, then the last 8 MiB (only if the file is larger than 8 MiB), then the file size written as a decimal string. Must match the base-rig indexer exactly.
- **Probe**: one ffprobe giving duration, fps, width, height, codec, bitrate, timecode (drop-frame normalised) and shot date.
- **Preview** (`.mp4`): the companion's shared 1080p H.264 browser-preview recipe, given the source timecode and frame rate (one keyframe per second).
- **Editing proxy** (`.mov`): the companion's shared project-proxy recipe (HEVC Main-10, 1080p, about 7 Mbps, AAC 192k), written in a QuickTime container, with the source timecode.
- **Frame count check**: counts real video frames in source and result; an unknown count on either side skips the check.
- **Sprite sheet**: one frame every 2 s, 240 px wide cells, 10 columns, at most 240 cells (a longer clip gets a wider interval: duration / 240). JPEG quality 4.
- **Poster**: one frame taken 10% into the clip, 640 px wide, JPEG.
- **Thumbnail**: same as the poster at 160 px wide (for the drop-zone grid when the browser cannot decode the file itself, for example 10-bit footage or MXF).
- **Scene detection**: scene-change threshold 0.3; every reported timestamp is used, de-duplicated and sorted. A clip with no cuts still gets frames.
- **Gap filling**: a first sample at 0 s if the first cut is later than 4 s; no gap between samples longer than 4 s (evenly spaced fillers inserted, including up to the end); timestamps rounded to milliseconds.
- **Frame extraction**: one JPEG per timestamp, accurate seek, scaled to at most 960 px wide, clamped to 0.05 s before the end. Files are named by their position in the requested list (`frame_0004.jpg`), so a frame that failed leaves a gap instead of shifting later frames. `frames.json` holds `{"timestamps": [...], "sheets": []}`.
- **Running ffmpeg**: the configured `ffmpeg_path` (resolved to the companion's own downloaded copy when needed), no console window on Windows, error output always read. Default time limit 900 s per run (stills, sprites, scene detection, frames); encodes get the longer limit described above. A timeout ("ffmpeg timed out after N s -- unreachable drive, or a file still being written") or a binary that cannot be started ("ffmpeg could not be run (<path>): <error>") counts as that step failing. A timed-out scene detection therefore falls back to evenly spaced samples every 4 s.
- **Stopping**: the running ffmpeg is published so cancel and shutdown can terminate it.

## Upload queue (ingest results to the NAS)
(source: broll_upload.py)

- **One upload at a time**, per batch, so ingest uploads never compete with the sync lanes with more than one transfer.
- **Order**: poster, sprite, preview, editing proxy, original, then music audio; ties broken by remote path. (A clip becomes visible on the dashboard after its stills land, playable after its preview, and its original goes last.)
- **Destination**: `<remote>:<remote_root>/Assets/B-roll Archive/<path>` for b-roll (the archive folder named by the server's claim is not used for b-roll uploads; music queues are given `Assets/Music`). Always the main `remote`, never the separate download route.
- **Command**: `rclone copyto <local file> <destination>` with the upload tuning flags and transport flags from the sync lane settings, JSON logs, stats every 1 s. rclone writes `.partial` on the far side and renames, so the server never sees a truncated file under the real name. No console window on Windows.
- **Duplicate enqueue** of the same remote path while queued or uploading joins the existing job.
- **Pause** (from tray, page or the server's upload-paused flag) stops starting new uploads; the file in flight is allowed to finish (an interrupted SFTP upload restarts from zero). **Resume** restarts the queue.
- **NAS not reachable** (no remote, no remote_root, or no rclone, same texts as the on-demand download): the job goes back to the front of the queue, the reason is kept on the job, and the queue waits 5 s; this never counts as a failed attempt. Log "broll upload: waiting -- <reason>".
- **Verification after each upload**: `rclone lsjson` on the uploaded file (2-minute limit). Listing fails: "the upload finished but <path> is not on the NAS (<first 120 characters of rclone's error>)". Size differs: "<path> arrived at N bytes, not M -- it will be sent again". An unreadable size or a verification that cannot run counts as success (the server checks again).
- **Upload failure texts**: "could not start rclone: <error>", rclone's last error line, "rclone exited with code N", "cancelled", "the upload failed (<error>)" for an unexpected internal error.
- **Stop** (cancel, lease lost, batch finished, shutdown): kills the running rclone, marks every queued job failed with "cancelled", and the queue can never run again (a new batch gets a new queue).
- **Progress** (shown in the page and tray): queued count, done count, failed count, paused flag, and the active file's kind, path, bytes, total, speed, ETA and percent.

## Local AI model: tiers, hardware checks, download
(source: broll_vlm_sidecar.py, broll_vlm/local_models.py, broll_vlm/local_runtime.py)

- **Two model tiers** (Qwen3-VL vision-language model, Q4_K_M quantisation, run by the open-source `llama-server` from llama.cpp release b10470):
  - **Good** ("Qwen3-VL 4B"): needs an NVIDIA GPU with 8 GB VRAM, or Apple Silicon with 16 GB unified memory. Note text: "Qwen3-VL 4B: needs an NVIDIA GPU with 8 GB VRAM (or Apple Silicon with 16 GB); ~20 s per clip on an RTX 3080". Weights 2,497,281,664 bytes plus vision projector 836,180,256 bytes. Recorded on the clip as `local:qwen3-vl-4b-q4_k_m`. Default tier.
  - **Best** ("Qwen3-VL 8B"): needs 12 GB VRAM, or Apple Silicon with 24 GB. Note "Qwen3-VL 8B: needs 12 GB VRAM (or Apple Silicon with 24 GB); a little sharper on on-screen text and vocabulary, ~2× slower". Weights 5,027,784,800 bytes plus projector 1,159,029,824 bytes. Recorded as `local:qwen3-vl-8b-q4_k_m`.
  - Every file is pinned to an exact Hugging Face repository revision and sha256 digest.
- **Runtime per platform**: Windows: CUDA 12.4 x64 build (250.8 MB archive) plus a separate CUDA runtime archive (391.4 MB). macOS: Apple Silicon (arm64) Metal build (11.1 MB). Linux: Vulkan x64 build (33.3 MB; noted as not benchmarked). Any other platform: "no llama.cpp b10470 build pinned for platform ..." (no indexing).
- **Cache folder**: `<companion tools folder>/broll-vlm` (Windows `%LOCALAPPDATA%\ccsync\tools\broll-vlm`; macOS `~/Library/Application Support/ccsync/tools/broll-vlm`), holding `downloads/` (archives, kept after extraction), `runtime/llamacpp-b10470-<platform>/` and `models/<tier>/`.
- **GPU detection**: on Apple Silicon Macs, total memory from `sysctl hw.memsize`; everywhere else, `nvidia-smi` (first GPU's name and memory). No `nvidia-smi` or no NVIDIA GPU means "no GPU" (so AMD/Intel GPUs on Windows or Linux, and Intel Macs, cannot index). Probe runs without a console window, is cached for 10 minutes, and never fails loudly.
- **Fit check and its exact refusals** (shown in the page, tray balloon and tray line):
  - no GPU: "Can't index b-roll: no usable GPU on this computer (<detail>). Indexing needs an NVIDIA GPU or Apple Silicon";
  - too small for Best: "Can't index b-roll: Best needs 12 GB VRAM, this GPU has 8 GB - choose Good" (Apple: "unified memory", "this Mac has");
  - too small for Good: "Can't index b-roll: Good needs 8 GB VRAM, this GPU has N GB - indexing needs a bigger GPU: this batch can run on another computer";
  - unknown tier: "Can't index b-roll: unknown model tier ..."
- **Recommended tier**: Best if memory reaches Best's floor, else Good if it reaches Good's, else none.
- **Never runs on the CPU**: with no fitting GPU the model server is refused.
- **"Downloaded" check**: both model files present at their exact pinned size (not re-hashed each time); runtime present when the extracted `llama-server` exists.
- **Cached status**: the readiness snapshot (runtime ready, each tier ready, GPU, current download, last error) is held in memory and only re-read from disk by an explicit refresh; a successful download triggers one.
- **Download order and refusals** (run by the ingest tick when the batch's tier is missing):
  1. the tier must fit this GPU (else that refusal; nothing downloaded);
  2. free space at the cache folder must cover both model files, twice each runtime archive (archive plus extracted copy) and a 200 MiB margin; else "Not enough disk space for the Good model: needs about X GB free at <folder>, has Y GB - free some space and try again" (an unmeasurable disk is not a refusal);
  3. every URL must be https and on the allowed hosts: `github.com`, `objects.githubusercontent.com`, `huggingface.co`, `cdn-lfs.huggingface.co`, `cdn-lfs-us-1.huggingface.co`, `cdn-lfs-eu-1.huggingface.co`, or matching `cdn-lfs*.huggingface.co`; else "refusing to download the b-roll model: <host> is not one of the hosts this build is allowed to fetch from";
  4. runtime archives downloaded and extracted (made executable on macOS/Linux), then the weights and projector.
- **Download mechanics**: a file already present with the right sha256 is not downloaded again. Otherwise up to 6 parallel ranged connections (environment variable `CCSYNC_DOWNLOAD_STREAMS`, 1 to 16; a non-number gives a warning and 6; files under 16 MiB use one stream; slices at least 8 MiB). A connection moving under 256 KB in 20 s is dropped and reopened (at most 5 stalls per slice); each slice gets 3 attempts with backoff 0.5 s doubling to 4 s. Partial files (`.part`) and a slice-progress record (`.part.json`) survive interruptions and are resumed. Progress (name, bytes, total, percent, rate over the last 5 s, time left) is published about 4 times a second for the progress window.
- **Verification**: the finished file's sha256 must match the pin; on mismatch the partial is deleted and the ingest says "the model download's checksum did not match. The file was deleted and will be fetched again" (both model files of the tier are deleted).
- **Other download outcomes**: stopped by shutdown: "the download was stopped - it will resume where it left off"; any other failure: "the b-roll model could not be downloaded: <error>"; success: "<Good|Best> is ready".
- **Runtime layout error**: "extracted <build> but llama-server is not where expected (<path>) - the release asset's internal layout may have changed".

## Local model server
(source: broll_vlm_sidecar.py, broll_vlm/local_vlm.py)

- **Start refusals** (each fails the current clip): the fit refusals above; "the b-roll indexing runtime is not installed on this computer yet"; "the <Good|Best> model is not downloaded on this computer yet".
- **Command**: `llama-server -m <weights> --mmproj <projector> --host 127.0.0.1 --port <free port> -c 16384 -ngl 99 -np 1 --no-warmup --image-min-tokens 1024`, listening on a random free loopback port. On Windows it gets its own process group and no console window.
- **Log**: appended to `~/.ccsync/state/broll_vlm_server.log` (llama-server's own output, with a timestamped command line per start). If the folder cannot be created the server starts without a log.
- **Readiness**: polls `GET /health` every second for up to 20 minutes; exits early: "llama-server exited early with code N; see <log>"; never healthy: "llama-server did not become healthy within 1200s; see <log>" (the process is then stopped).
- **Reuse**: one server per (binary, weights, projector, GPU layers, context) is kept warm for the whole batch. A warm server that fails a 3 s health check gets one 15 s retry before being replaced (the old one is stopped first).
- **Stopping**: terminate, wait 20 s, then kill. The ingest stops every server whenever it is not actively crunching (the editor came back, batch over, cancel, shutdown) so the GPU memory is returned immediately. Servers are also stopped when the companion process exits.

## Local clip description (what the model is asked and what is stored)
(source: broll_vlm/local_vlm.py, broll_vlm/compact_format.py, broll_vlm/contract.py, broll_vlm/prompts/index_clip_v7_compact.md, broll_ingest.py)

- **Input**: the extracted frames listed in `frames.json` (missing frame files are skipped; none at all: "no usable frames found - run the 'frames' stage first"), each with its timecode `HH:MM:SS`.
- **Windows**: frames are split into near-equal groups of at most 8 per model call (no tiny last group). One HTTP call per group to the local server's chat completions endpoint.
- **Each call contains**: the fixed instructions (below), the frame table line `F1=00:00:00 F2=00:00:04 ...`, then for each frame a label `F<n> (<timecode>):` and the JPEG image, then "Answer now: the S lines, then the T line." Settings: temperature 0.1, repeat penalty 1.15, at most 150 output tokens per frame, prompt caching on, 15-minute timeout per call.
- **Output grammar enforced on the model**: 1 to N shot lines (N = frames in the call) then exactly one theme line, then the answer must end. Frame ids limited to F1..Fn. Description at most 220 characters, objects at most 300, each on-screen text field at most 300, themes at most 160. A text field is either a single `-` or text not starting with a dash or space. The characters `|`, line breaks and `→` cannot appear inside a field.
- **What the instructions ask the model to produce** (prompt file `index_clip_v7_compact.md`, sent verbatim):
  - Overall rule: describe only what is visible; no narration, no inferred events or causes, no story across frames; hedge briefly ("possibly melons") or describe appearance rather than guess. Examples given: red vehicle lights are brake lights unless a light bar or livery is visible; slow traffic is congestion, not an accident.
  - **One shot line per distinct shot**: a run of consecutive frames of the same place, subject and camera setup; split whenever the picture changes; "when in doubt, split"; never more lines than frames; never reuse a frame.
  - **Line format**: `S <frames> | <description> | <objects> | <onscreen text or -> // <English of the text or ->`.
  - `<frames>`: one frame id or a range (`F1`, `F3-F5`), only ids from the frame list.
  - `<description>`: a terse comma-separated list of nouns and noun phrases, 8 to 20 words, no sentences, no "footage showing"; keep colour, time of day, camera position and counts as attributes. For shots with no searchable picture, exactly one canonical label as the whole description: `newsreader` (studio anchor at a desk), `title card`, `black frame`, `colour bars`, `station ident`.
  - `<objects>`: semicolon-separated nouns for everything visible, most specific first, including the plain broader term (example: `frigate;warship;navy ship`); proper nouns read from on-screen text (people, places, organisations) added in both original script and English.
  - `<onscreen text>`: burned-in text verbatim in its original script (Chinese, Japanese, Korean never romanised): chyrons, lower-thirds, channel names, dates, signage, banners, vehicle markings, name plates; several pieces joined with " | "; stop at illegible text; ignore camera timecode or frame counters; `-` if none. Still transcribed on newsreader and title shots.
  - `// <English>`: a short English rendering of the on-screen text, or `-`. Nothing may follow it on the line.
  - **Theme line**: `T <theme;theme;...>`, 2 to 6 short tags summarising the whole group of frames.
  - No JSON, timecodes, headings, numbering, blank lines or commentary. A worked three-shot example is included.
- **Parsing** (tolerant): accepts variants such as a leading `-`/`*`, `S1:`, `Themes:`, bare numbers for frame ids (clamped into range), `;` or full-width `；` separators (else commas), and none-words (`-`, the em-dash and en-dash characters, `none`, `n/a`, `null`, `no text`, empty quotes, `(none)`) as empty. Objects and themes are de-duplicated case-insensitively. Everything after the third `|` is the text field (text may itself contain ` | `); the English part is after the last `//`. Unrecognised lines are logged as tolerated problems. No shot lines at all is a failure; the call is retried once, then the clip fails with "local vlm returned unparseable output after one retry: ...".
- **Segment times come from the frame table**, never from the model: a shot's start is its first frame's time and its end is its last frame's time. `setting` and `motion` are always empty for this backend.
- **Validation**: every segment needs a numeric start and end; untimed segments are dropped (all dropped is a failure). Missing text fields become empty; on-screen text given as a list is joined with " | ". Descriptions are normalised to the canonical no-picture labels, including aliases (news reader, news anchor, anchor, presenter, talking head to `newsreader`; color bars, test pattern to `colour bars`; titles, title cards to `title card`; blank frame to `black frame`; channel ident, ident to `station ident`).
- **Merging the groups**: themes and quality flags united in order, segments concatenated.
- **Quality flags from pixels** (computed on all frames, scaled to 480 px grey): `overexposed` when at least 30% of frames have mean brightness over 200 or at least 25% clipped-white pixels; `underexposed` when at least 30% of non-black frames have mean under 45 (a black frame is mean under 12 with over 95% dark pixels); `soft_focus` when the median sharpness measure of non-black frames is under 20. Allowed flag vocabulary: `shaky`, `soft_focus`, `overexposed`, `underexposed`, `noisy`, `rolling_shutter` (anything else is dropped).
- **Category**: chosen in code, not by the model, from the category list the server sent with the claim: the category whose label and description are most similar to the clip's themes, descriptions and objects. Uses a multilingual sentence-embedding model if the `fastembed` library is importable, otherwise word/CJK-character TF-IDF similarity. Below a similarity of 0.15 no category is set.
- **Over-segmentation merge** (on): adjacent segments (by start time) are merged when their object sets overlap at least 60% (Jaccard) and their descriptions are at least 75% similar; the merged segment keeps the earlier start, later end, the union of objects and both on-screen texts joined with " | " when different.
- **Result handed to the server**: segments (start, end, description, objects, empty setting and motion, on-screen text, English text), themes, quality flags, category, and model name `local:<model label>`.

## Code present but not used by the companion (vendored indexer leftovers)
(source: broll_vlm/local_runtime.py, broll_vlm/local_vlm.py)

- DORMANT: printing download progress and "fetching ..." banners to the console (the companion always passes a progress callback, which silences them).
- DORMANT: `refuse_if_tier_unfit` (the indexer CLI's "Best needs 12 GB VRAM; this machine reports 10 GB - choose Good or add --force" check, with a `--force` override); the companion uses its own fit check.
- DORMANT: `llama_server_version` (`--version`/`--help` banner read for the indexer's `doctor` command).
- DORMANT: `default_cache_dir` (the indexer's own cache path, `%LOCALAPPDATA%\ccsync\indexer` and equivalents); the companion uses its tools folder.
- DORMANT: inside the describe step, the path that downloads the runtime and model and starts its own server with a log at `<staging>/local_vlm_server.log`; the companion always hands it an already-running server's address, so this path never runs.
- DORMANT: per-call usage logging hook (`log_usage`); the companion passes none.
- DORMANT: `is_fatal_local_error` classification of server failures; nothing in the companion reads it.

## Looks redundant or overlapping

- Two capability answers (`build_ingest_capabilities` and `build_music_ingest_capabilities`) repeat the same ffmpeg, rclone, staging, busy, signed-in and switched-off checks with different nouns.
- Two different default staging floors for music: the capability route and the upload route use 2 GB, while the orchestrator's own `prepare` space check uses 20 GB unless `music_ingest_free_space_floor_gb` is set.
- `/<kind>/ingest/retry` does two unrelated things depending on whether the body carries `batch_uid` (re-arm failed uploads in staging, or re-run a server-side batch).
- `run_mode` and its legacy alias `start_now: true` are both accepted on `/run` and `/retry`.
- Ingest status is assembled three times for three readers: the page's `/progress`, the tray's status, and the dashboard report section, each with its own field subset.
- Download state is tracked in two places that have to be reconciled: the on-demand download registry (popped on read) and the stand-in ledger's intent rows (settled later by header probing and by `reap_finished`/`settle_landed`).
- The on-demand fetch prerequisite messages (no remote, no remote_root, no rclone) re-check what the sync config validator already checks; the upload queue reuses the same messages.
- Thumbnails for the drop grid are made twice: by the browser where it can, and by the companion for every clip during stills.
- Free-space checks exist in four places with different rules: capability route (floor only), `prepare` (floor plus whole drop), PUT (floor plus that file), model download (files, double archives, 200 MiB margin).
- `server_url` in `~/.broll-companion.json` is written by default and documented but never read by anything in this part.
- The `standins_owed` list in `GET /status` and the "given up" upgrade state duplicate information the tray is expected to show separately (not built in this part).
- The vendored describe step can download and start its own model server, duplicating the sidecar's download and server management (unused here, see above).
- The loopback server carries five route groups on one port (b-roll insert, music, YouTube downloader, b-roll ingest, music ingest) with two different error-key conventions (`message` for b-roll, YouTube and ingest; `error` for music).

## Claims the code does not back

- The module header of `broll_server.py` lists the routes it serves but omits `POST /ytdl/cancel`, which the code serves.
- `broll_ingest.py` says the retention period is overridable as `<kind>_ingest_staging_retention_days`; the key actually read is `broll_ingest_ingest_staging_retention_days` (and `music_ingest_ingest_staging_retention_days`), because the kind's prefix already ends in `_ingest`.
- `build_ingest_capabilities` says the GPU and model-cache facts come from a snapshot "refreshed on the ingest tick"; no ingest tick calls the sidecar's refresh. The snapshot is only updated by a GPU probe made elsewhere or by a completed model download, so after a companion restart `cached` and `runtime_cached` read false (and the GPU may read "not probed yet", making the tiers unfit) until something probes or a batch downloads.
- `_remote_rel` says the server decides where a kind's uploads go (`archive_remote_rel`); for b-roll the value is stored but the upload queue always uses `Assets/B-roll Archive`. Only music reads it.
- `ingest_kinds.py` says music's 2 GB default floor applies "when the site has set no `<prefix>_free_space_floor_gb`"; the orchestrator's own floor ignores the kind default and uses 20 GB.
- `_fetchable_from_nas` says the on-demand download never runs "on a base rig, whose local_root IS the NAS share", but it only checks `mode == "base"`. A computer whose `local_root` equals the canonical prefix while its mode is not `base` is treated as wired by the insert plan and can still start an rclone download onto its own tree.
- `broll_upload.py` describes the uploaded preview as a "540p proxy"; the ingest makes and uploads the 1080p preview (`broll_ingest_media.py` and `broll_ingest.py` say 1080p).
- `broll_vlm_sidecar.fits` documents the refusal with an em dash before "choose Good"; the code writes a spaced hyphen.
- The capability reason "ffmpeg is not installed on this computer yet: it is fetched the first time a batch runs" is not backed by anything in this part: the ingest gate only waits in `no-ffmpeg`; whatever fetches ffmpeg lives elsewhere.
- `broll_vlm_sidecar.py` promises "never a surprise 3.9 GB download"; the companion side starts the model download on its own as soon as a claimed batch needs it, with only a tray balloon. Any consent step would be on the web page, outside this part.

## Could not determine

- What `/music/*`, `/ytdl/*` actually do: their behaviour lives in `music_server.py`, `ytdl_server.py` and `ytdl_executor.py`, outside this part. Only the dispatch, body checks and error keys are listed here.
- The music per-track ingest pipeline (probe, transcode, peaks, CLAP embedding, base-rig fallback, its own manifest matcher and upload body) lives in `music_ingest.py` and `music_clap_sidecar.py`, outside this part.
- How the Resolve child process performs the insert, the `/status` Resolve probe and the proxy link (`music_worker.py`, `resolve_bridge.py`), including what "append" and "playhead" do precisely in Resolve.
- Who calls `resume_pending_upgrades` (described in comments as the 120 s relink cycle), `placed_report`, `staging_report`, `prune_staging(0)` (CLEAR FINISHED STAGING) and `note_report_response`, and the tray windows and menu lines that show ingest status: all outside this part.
- The exact preview height (`ffmpeg_tools.PROXY_HEIGHT`; 1080 is the fallback in this part), the "edit-weight" rule (`ffmpeg_tools.is_edit_weight`) and the exact encode arguments, which live in `ffmpeg_tools.py`.
- The proxy generator's stuck floor and factor that set the encode time limit (read from `proxy_gen.py`).
- Whether the frozen companion bundles `fastembed` (category by embeddings) or always uses the TF-IDF fallback.
- The native picker's own behaviour (walk depth, the 2,000-file cap mentioned in a comment, the "busy" message text), which lives in `popup.py`.
- Whether anything outside the files read (other than `capabilities.py`'s GPU probe) refreshes the model readiness snapshot at startup; only `app.py` was searched.
