# Dashboard: fleet jobs, and how it hosts Timeline Cards, b-roll, music, the YouTube downloader and the footage sorter

Terms used throughout:

- **Job**: a unit of media work the dashboard hands to one of the editors' computers (a "machine"). A machine is identified by the pair (editor account, machine name).
- **Companion**: the tray app on each editor computer. It reports to the dashboard on a timer; the reply to each report can carry job offers.
- **Offer**: a list of job ids put on a machine's report reply. The machine then has to claim one; the claim succeeds for exactly one machine (compare-and-set).
- **Capabilities**: the facts a companion reports about itself (ffmpeg present, GPU, VRAM, NVIDIA encoder, idle seconds, load, mounts, allowed job kinds, jobs switched on or off, a "volunteer until" time, a "local work" gate).
- **Base machine**: a machine whose own mode is `base` (wired to the server, nobody sits at it).
- **Engine**: one running copy of the Timeline Cards back end, bound to one episode folder.

## Job kinds, limits and idle floors (source: jobs.py, constants read from db.py)

- Seven job kinds are known: `whisper`, `proxy-480p`, `audio-extract`, `peaks`, `card-ingest`, `drive-copy`, `ledger-scan`.
  - A job of any other kind can sit in the queue but is never offered to anyone (refusal `kind_unknown`), and its explanation says: "this dashboard does not know the job kind '<kind>', so no computer will ever be offered it".
- Fleet-wide cap on how many of a kind may be held (claimed or running) at once:
  - `whisper` 2, `proxy-480p` 4, `audio-extract` 4, `peaks` 4, `card-ingest` 4, `drive-copy` 2, `ledger-scan` 4; any other kind 4.
  - Overridable per kind by the deployment setting `jobs_max_running` (environment `DASH_JOBS_MAX_RUNNING`); a value that is not a number falls back to 4; a value below 1 is treated as 1.
  - The cap is counted once per report and incremented as offers are made in the same reply, so one reply can never push a kind past its cap.
- Idle floor (seconds of no keyboard or mouse before a machine may be given the kind):
  - `whisper` 300, `proxy-480p` 300, `audio-extract` 60, `peaks` 60, `card-ingest` 0, `drive-copy` 0, `ledger-scan` 0; any other kind 300.
- Default hard requirements, filled in only when the submitter gave none, for the three media kinds (`proxy-480p`, `audio-extract`, `peaks`):
  - needs `ffmpeg` and `ffprobe`;
  - needs a mount for each of the job's `root` and `out_root` names (lower-cased, de-duplicated), when given.
  - `whisper` and every other kind get no default requirements (the submitter states them, for example a VRAM floor).
- Output-name check at submit time for the three media kinds: an `out_stem` (output file name stem) is refused if, after trimming, it is `.` or `..`, contains `/`, or contains a control character (code below 32, or 127). Message: "out_stem '<value>' is not a plain file name: it cannot be a dot name or hold a '/' or a control character, on any computer". A blank or missing stem is accepted (the source's own name is used). `:` and `\` are deliberately allowed.

## Who gets offered a job: the per-machine refusals, in the order asked (source: jobs.py)

Every report from a machine produces at most 8 offered job ids (the queue is walked in queue order). For each queued job, the first matching refusal below is recorded and the job is skipped for that machine:

- **Unknown kind** (`kind_unknown`).
- **Fleet cap reached** for the kind (`fleet_cap`).
- **Addressed to another machine** (`not_the_target`, "this job is for <target> only"): a job can name a target machine. The match is case-insensitive; a target written `editor/machine` must match both halves; a bare name matches the machine name of any editor.
- **Missing capability** (`capability`): the job's hard requirements are not met by the machine's capabilities.
- Then the machine policy (the same list is used by the explanation page), first true answer wins:
  1. Fleet-wide halt active: "syncing is stopped by your admin for the whole fleet" (`fleet_halt`).
  2. Machine has not reported for more than 15 minutes (only checked in the whole-fleet read, never for the machine that is reporting or claiming right now): "this computer has not reported since <time> (<N min / N h / N days> ago), so it cannot claim anything until it is switched on" (`not_reporting`). An unreadable timestamp is not treated as silent.
  3. Machine halt: "syncing is stopped on this computer" (`machine_halt`).
  4. A pushed update is waiting for that machine and the dashboard has not marked it as withheld (undeliverable): "this computer has an update waiting to apply" (`upgrading`). An update marked withheld does not block jobs.
  5. Proxy-download circuit breaker tripped: "this computer's proxy download stopped itself, so it is not in a state anyone should add work to" (`lane_b_breaker`).
  6. Already holding a job: "this computer is already holding job #<id> (<kind>)" (`already_holds_a_job`). Exception: a held `ledger-scan` does not count against other kinds, and for a `ledger-scan` only another held `ledger-scan` counts. So a machine can hold one ledger scan plus one other job.
  7. No capabilities ever reported: "this computer has not reported what it can do (a companion older than the job runner)" (`no_capabilities_reported`).
  8. Jobs switched off on the machine (`jobs_enabled` false; default true): "fleet jobs are switched off on this computer (jobs_enabled)" (`jobs_disabled`).
  9. The machine's own kind allow-list excludes the kind: "this computer's config allows only <kinds> jobs, not <kind>" (`kind_not_allowed`). An empty list allows every kind.
  10. The machine is busy with its own media work (`local_work`): either its reported gate says `local_work` (the text shown is the gate's detail, or "busy with its own media work"), or the stored flags say "busy indexing b-roll" or "busy indexing music". Message "this computer is <what>". An unrecognised gate reason is ignored, never a refusal.
  11. Cooling down after a failed job (skipped for a forced job): "this computer is cooling down until <time> (<reason, default 'a job failed here'>)" (`cooling_down`).
  12. Idle floor (skipped for a base machine, for a forced job, and for a machine whose person is volunteering):
      - idle unknown: "this computer cannot say how long it has been idle, which counts as somebody being at it";
      - idle below the floor: "somebody is at this computer (idle <N>s, <kind> needs <floor>s)";
      - idle unreadable: "this computer's idle answer is unreadable". All are `not_idle`.
- **Not the preferred machine yet** (`another_machine_is_preferred`): see ranking below.
- A **forced** job (the admin said "now") skips only the cooldown, the idle floor and the ranking wait. It does not skip halts, a waiting update, the breaker, a held job, jobs switched off, or the allow-list.
- The reply carries `offered` (job ids), `forced` (the subset submitted as forced, so the companion can bypass its own "user active" gate) and, internally, `refused` (id to reason).

## Volunteering (source: jobs.py)

- A machine is "volunteering" when its capabilities carry a `volunteer_until` time later than now (set by the person at the machine from their tray; nothing on the dashboard can set it).
- An unreadable or expired time counts as not volunteering; times with no zone are read as UTC.
- Volunteering lifts the idle floor for every kind, and is the top ranking signal for the four media kinds. It does not lift the cooldown or any other refusal.

## Ranking, and the 60-second preference window (source: jobs.py)

- Every machine that passes capability, target and policy is ranked, bigger is better, by (in order):
  1. Preference: the sum of the weights of the signals it has, per kind:
     - `whisper`: volunteering (3), GPU with room for the job's VRAM floor plus 1.0 GB headroom (2; with no floor stated, any GPU that reports its VRAM qualifies), any GPU (1).
     - `proxy-480p`: volunteering (2), NVIDIA encoder (1).
     - `audio-extract` and `peaks`: volunteering (2), machine in `base` mode (1).
     - `card-ingest`, `drive-copy`, `ledger-scan`: no signals.
  2. Fewer jobs currently held.
  3. Lower reported load (a machine reporting no load, as on Windows, counts as 0, not as a penalty).
  4. Longer idle.
- No tie-breaking on names.
- For the first 60 seconds after a job is created, it is offered only to the machine(s) with the best rank; ties are all offered together and the claim decides. After 60 seconds every able machine is offered it.
- Forced jobs and targeted jobs have no preference window: offered at once.
- If no machine is able, or a job's timestamps are unreadable, the window counts as already over.

## "Why is this job not running": the job explanation (source: jobs.py; served by the route `GET /api/v1/jobs/<id>/why`, which lives outside this part)

- Returns nothing for an unknown job id.
- For a job that is held, pinned or finished, returns no machine list, `schedulable` false, and a summary:
  - held (claimed or running): "<editor>/<machine> is holding this job (lease until <time>)", code `held`;
  - pinned: "the fleet could not finish this, so it is pinned to the dashboard's own worker; it never goes back to the fleet", code `pinned`;
    - plus ". It is waiting: no Timeline Cards episode is open on the dashboard, and it runs as soon as somebody opens one" when the pinned worker last found no open episode;
    - replaced by "the fleet could not finish this, and it was pinned to the dashboard's own worker, but <reason>. Nothing will run it here: cancel it and queue it again" when the old Timeline Cards page is retired (see the pinned worker section);
  - done: "this job is done"; abandoned: "given up after <N> attempt(s): <last error or 'no error recorded'>"; failed: "this job failed and will not be retried: <last error>". All three code `finished`.
- For a queued job: one line for every machine that has ever reported:
  - refused lines carry the reason code and sentence; a capability refusal adds, when the machine's ffmpeg/ffprobe/deno installer has reported a failure for a tool this job needs and the tool is missing: "the <tools> install on this computer is failing (<N> tries): <cause>" (the try count only when above 1);
  - able lines carry rank, the four rank numbers, which signals it has, and a sentence: "this computer can take it, and is first choice", or "this computer can take it (choice <n> of <m>; <why it lost>; <offer clause>)".
    - why it lost names the first rank component lost: "the first choice has <signal words> and this computer has not", or "the first choice is better placed for this kind of work / is holding less work right now / is less loaded / has been idle longer". Signal words: "somebody at it who said to take fleet jobs now", "an NVIDIA encoder", "a GPU with room for this model", "a GPU", "is wired to the server, next to the media".
    - offer clause: "it is being offered the job now too", or "it is offered the job too in <N>s if nobody ahead of it has taken it by then".
- Job-level answer: `schedulable` (true only when at least one machine is able, the kind is known and the fleet cap is not reached), `reason_code`, `transient`, `capable` (machines that could ever run it, ignoring desk presence and excluding capability, no-capabilities, kind-not-allowed, jobs-disabled and not-the-target refusals), `running`, `cap`, `summary`.
  - Unknown kind: code `kind_unknown`.
  - Cap reached: "<N> <kind> job(s) are already running, which is this fleet's limit (<cap>); it starts as soon as one finishes", code `fleet_cap`.
  - Some machine able: "<N> computer(s) can take this job; it is waiting to be claimed on their next report", code empty.
  - No machine ever reported: "no computer has ever reported to this dashboard", code `no_machine_reported`.
  - Otherwise the worst (most hopeful) code across machines wins, in this order: `all_busy` (upgrading, breaker, holding a job, local work, not preferred), `fleet_cap`, `cooling_down`, `idle_wait` (not idle), `halted` (fleet or machine halt), `kind_not_allowed` (allow-list or jobs disabled), `kind_unknown`, `machines_not_reporting`, else `no_capable_machine`.
  - Targeted job: only the target's lines count. No machine of that name ever reported: code `target_unknown`, summary "this job is for <target> only, and no computer of that name has ever reported to this dashboard". The target's refusal is waitable: code `target_away`; otherwise its own code passes through. Summary "this job is for <target> only, and it cannot take it: <why>".
  - Untargeted blocked summary names the commonest refusal: "no computer can take this job right now: <count> of <total> <words>", with words such as "have somebody sitting at them", "cannot do this kind of work", "have not reported in the last 15 min", "are busy with their own media work"; for capability, adds ". On <editor>/<machine>, <installer failure cause>" when one is known.
  - Transient codes (a waiting client should keep waiting): `all_busy`, `fleet_cap`, `idle_wait`, `cooling_down`, `held`, `pinned`, `target_away`. Everything else (including `target_unknown`, `no_capable_machine`, `machines_not_reporting`) tells Timeline Cards to make the file itself.
- Whether a job whose retries are spent becomes `pinned` or `abandoned` depends on whether a pinned executor exists and says it is available; default is no executor, so `abandoned`.

## Timeline Cards: the two states (source: cards.py, cards_landing.py, cards_edit.py)

- There are two Timeline Cards pages: the **old page** (the Timeline Cards Python page, one episode at a time under `/cards/p/<slug>/`) and the **new editor** (a Node server, served under `/cards/edit/`).
- **The old page is retired** when the new editor is switched on (see the new editor section for what "switched on" means) AND `DASH_CARDS_OLD_PAGE` is not `1`. This single decision is used by the episode picker, the episode dispatcher, the pinned-job worker and the health line. If the check itself fails, the old page is treated as not retired.
- State A, **editor off** (the default, vendor build): `/cards` is the episode picker plus the old page per episode, with engines opened on demand (described below).
- State B, **editor on, `DASH_CARDS_OLD_PAGE` unset**: the picker still lists episodes, but every Open is a link to `/cards/go/<slug>` which sends the browser into the new editor; no engine is ever opened; old episode URLs redirect to the editor; the picker's offline service worker is replaced by one that deletes itself; pinned media jobs can no longer run (see the pinned worker section).
- State C, **editor on, `DASH_CARDS_OLD_PAGE=1`**: rollback. The old page behaves as in state A, and the new editor also runs beside it.

## Timeline Cards: mounting and settings (source: cards.py; environment names from settings.py)

- Mounted at `/cards`, behind the dashboard login. Never stops the dashboard from starting; every failure becomes a status with a sentence, reported in the health output:
  - `disabled`, "DASH_CARDS_ENABLED is not 1", when not enabled;
  - `disabled`, "no Timeline Cards checkout is configured (DASH_CARDS_SRC)";
  - `absent`, "the configured checkout is not there (<path>)" when the checkout folder is missing (logged as a warning);
  - `disabled`, "no vault is mounted here (DASH_CARDS_VAULT_ROOT)";
  - `absent`, "the vault root is not mounted (<path>)" (logged as a warning);
  - `absent`, "the checkout did not import (<error>)";
  - `absent`, "a2wsgi is not installed (<error>)";
  - `mounted`, "serving <vault>".
- Settings (all environment variables):
  - `DASH_CARDS_ENABLED`: only the exact value `1` enables it; default off. DEV ONLY: setting `CARDS_SRC` in the environment to a checkout path also counts as enabled and supplies the checkout path.
  - `DASH_CARDS_SRC`: the Timeline Cards checkout folder (falls back to `CARDS_SRC`). It is appended to the import path, never placed before configured paths.
  - `DASH_CARDS_VAULT_ROOT`: the vault folder episodes are found under (falls back to `CARDS_VAULT_ROOT`).
  - `DASH_CARDS_ROOT`: fallback episode root for an engine built without one (in practice every engine gets its episode from the picker).
  - `DASH_CARDS_ENGINES`: how many episodes may be open at once, default 2, minimum 1.
  - `DASH_CARDS_PROJECT`: a cut file the engine opens at start, default none.
  - `DASH_CARDS_TOKEN`: the Timeline Cards server token; handed to each engine and used by the agent tunnel; never sent to editor machines.
  - `DASH_CARDS_SERVER_URL`: the address of a separate Timeline Cards server for the agent tunnel (see the tunnel section).
  - `DASH_CARDS_DB_HOST`, `DASH_CARDS_DB_NAME`: the Resolve project database the engine may reach; `DASH_CARDS_DB_WRITE_ALLOW`: comma-separated list of what it may write; `DASH_CARDS_DB_BACKUPS`: a backup folder. All blank by default and passed through unchanged.
  - `DASH_CARDS_MEDIA_MAP`: path translation pairs, written `P:\=/media/;X:\=/vault/`. Pairs split on `;`, each on the first `=`; empty halves and pairs with no `=` are skipped; trailing slashes are trimmed from the right side only.
  - `DASH_CARDS_OLD_PAGE`: `1` brings the old page back while the new editor is on; default off.
- The old page's own shared-secret browser key is switched off: the dashboard login is the only gate.
- Each engine keeps its state in `<dashboard data folder>/cards/<slug>/`, created on demand. If that cannot be created the engine runs with no state folder.
  - When files from before per-episode folders (`cards_mirror.json`, `cards_pick.json`, `cards_lane_keys.json`, `cards_ui.json`, `library_backups`) still sit in `<data>/cards/`, a warning is logged once per episode naming both folders. They are not moved, adopted or deleted.
- The Claude runner (see the Timeline Cards AI section) is handed to every engine. The checkout's model picker is given the dashboard's list of available model ids so "sonnet", "opus", "fable" follow the newest model; if the checkout is too old for that, a warning says it "will use its own model table".
- Also registered with the mount: the picker routes (below) and a router for the installed apps' own updates at `/cards/app/` (that router lives outside this part).
- The vault root is recorded so the dashboard's periodic mount checker re-probes it.
- Each episode's old page is served through a pool of 24 request workers; a media stream stops when its browser has gone.
- At dashboard shutdown every open engine is stopped.

## Timeline Cards: episodes and slugs (source: cards_pool.py)

- An **episode** is any folder that contains an `Interviewees` or `Clips` subfolder.
- The vault is searched up to 4 levels deep; a folder that is an episode is not searched further; folders starting with `.` are skipped; unreadable folders are skipped silently. The vault itself counts if it is an episode. Each episode has a name (folder name), a show (parent folder name) and a folder modified time. The list is sorted by show then name, case-insensitive.
- **Slug**: the episode's id in the URL. Made from the path normalised to Unicode NFC, backslashes turned to `/`, trailing slash removed, case folded; then the first 8 hex characters of its SHA-256, prefixed with a readable label from the folder name (letters a-z and digits only, other runs become `-`, at most 32 characters). A name with no Latin letters gets the bare 8-character code. Stable across restarts and machines.
- A path segment is accepted as a slug only if it is 1 to 48 characters of `a-z`, `0-9` and `-`.

## Timeline Cards (states A and C): opening, closing and seats (source: cards_pool.py, cards_landing.py)

- Episode states: `loading` ("opening this episode"), `ready` ("serving <root>"), `failed`.
- Open is idempotent: an episode already loading or ready comes back as it is.
- **Seat cap**: at most `DASH_CARDS_ENGINES` (default 2) episodes loading or ready. A third open is refused with: "<cap> episodes are already open: <name> (<occupants or 'nobody in the last 15 min'>) and ... . Ask whoever is in one to press "Close" beside it here, or close an idle one yourself. An admin can close any of them." Nothing is evicted automatically.
- Opening runs in the background; the page shows the state.
- A failed open shows "this episode did not open (<error type>). The dashboard log has the detail." (the error's text is only in the log).
- A failed episode can be opened again, but not within 20 seconds of failing: "<name> did not open a moment ago. Wait <N> s and press "Open" again."
- An episode still loading after 10 minutes is marked failed (checked whenever anything reads the pool): "the vault did not answer for 10 min, so this episode did not open. Press "Open" to try again." If the slow build then finishes and a seat is free, it is published anyway; if every seat was taken meanwhile it is stopped and the detail reads "this episode opened too late: every seat was taken by then. Press "Open" to try again."
- An episode closed while still opening is stopped as soon as its build finishes.
- **Occupants**: an editor counts as "in" an episode for 15 minutes after their last served request there (any request through the episode, plus agent work, see the tunnel). This only affects wording and who may close; it holds no seat.
- **Who may close an episode**: an admin, always; anyone else only if nobody is in it or they are the only person in it. Refusal: "somebody else is in that episode. Ask them to close it, or an admin can." A failed entry can be closed by anyone.
- Closing frees the seat, stops the engine, and forgets which editors and pending agent edits pointed there. The code states that closing does not free all of the engine's memory (some of its background work keeps running).
- **Where an editor's Resolve agent goes**: each editor is attached to one episode. Navigating to an episode's page (a GET for HTML of the page itself) moves them there; other requests (polls, media) move them only if the episode they were attached to has had no page request from them for 120 seconds. Opening an episode from the picker does not move them until it is ready.

## Timeline Cards (states A and C): the old episode page at /cards/p/<slug>/ (source: cards.py)

- Every request under `/cards/` that is not one of the picker's own routes goes to the episode dispatcher:
  - Anything starting `/cards/agent/` (that is not one of the three tunnel routes): 404 `{"error": "the agent protocol is served by the dashboard at /cards/agent/{state,pending,result}"}`.
  - A flat address from before per-episode pages (`/cards/api/...` and so on) or a malformed slug: a page navigation is redirected to `/cards/`; anything else gets 404 "Timeline Cards is one page per episode now: this address has moved under /cards/p/<episode>/" with a `landing` link.
  - `/cards/p/<slug>` without the trailing slash: redirected to `/cards/p/<slug>/`.
  - Episode not open: a page navigation is redirected to `/cards/?want=<slug>`; anything else gets 409 "this episode is <state or 'not open'>: the Timeline Cards page is where it opens".
  - Episode open: forwarded to that episode's old page, all of its own routes unchanged.
  - A page navigation also records the visit for "last opened", moves the person's agent to this episode, and sets the carry-on cookie on a successful answer.
- Two of the old page's own routes are blocked (also when written with a trailing slash, doubled slashes, or `.`/`..` segments). They answer 200 with an `error` the page shows:
  - `/api/restart`: "this Timeline Cards is part of the dashboard and cannot restart itself: redeploy the dashboard to pick up page changes". Any attempt by the page to shut down its server is refused and logged as an error.
  - `/api/root` (switching the engine to another folder): "this Timeline Cards has one engine per episode. Go back to the Timeline Cards page to open another episode, and this one stays open behind you".
- No identity headers are added: every signed-in person edits the same episode document.
- A navigation is recognised by `Sec-Fetch-Mode: navigate`, or failing that an `Accept` containing `text/html`, and only for GET or HEAD. Redirects are 303.

## Timeline Cards (state B): old episode URLs once retired (source: cards.py)

- `/cards/p/<slug>/sw.js` (GET or HEAD): a service worker that installs at once and unregisters itself. It deletes no cache and no on-device data, so unsent edits survive a rollback.
- A page navigation to any `/cards/p/<slug>/...`: redirected to `/cards/go/<slug>` (into the editor).
- Any other request: 410 `{"error": "The old Timeline Cards page is retired. Open the episode from the Timeline Cards page.", "landing": "/cards/"}`.
- No engine is built and no visit is recorded. The pool exists but stays empty.

## Timeline Cards: the episode picker page (source: cards_landing.py, cards_catalog.py)

- `GET /cards`: redirects (303) to `/cards/`.
- `GET /cards/` (signed in): the picker page.
  - Lists every episode found in the vault (the scan is reused for 30 seconds), as a folder tree with folder counts (levels every episode shares are dropped, but at least one level is kept), plus "recent": up to 5 episodes this person opened, newest first, and the list of years for filtering. Folders holding something open or something the reader has opened are drawn unfolded.
  - Each row shows: folder path, year (a `19xx`/`20xx` folder above it, else the year of its modified date), a phrase "you opened it <ago>" / "<name, 'you' or 'somebody'> opened it <ago>" / "never opened", size, a "partial" flag when the size walk was cut short, and the last modified date ("3 Sep 2026"). Ago phrases: "just now" (under 90 s), "<N> min ago", "<N> h ago", "<N> d ago" (under 60 days), "<N> mo ago". Sizes: B and KB with no decimals, MB/GB/TB with one.
  - Display names are used in phrases; a display name spelt "you", "somebody", "nobody" or "someone" falls back to the sign-in name.
  - "Carry on with ...": the episode named in the `ccsync_cards_last` cookie (90 days, HTTP-only, SameSite lax, Secure when the site's cookie rule says so). The cookie is set when a person opens an episode, enters its page, or goes through `/cards/go/`.
  - `?refused=<sentence>` shows a refusal; `?want=<slug>` marks the episode being waited for (ignored in state B).
  - States A/C extras per row: state, detail, who is in it now (display names), "<who> is in it now" (under a minute) or "<who> was last in <N> min ago", "opening for <N> min; it gives up at 10 min" (only after a minute), and a Close button when the reader may close it, with the confirm "Close <name>? <who was last in, other than the reader>. Anything an offline browser has not sent yet stays in that browser until it reconnects." The page shows how many of the cap are open. Episodes open but no longer found in the vault are still listed so they can be closed.
  - State B: rows have no state, no occupants, no close button; each Open links to `/cards/go/<slug>`.
  - If reading the catalogue fails, the page still draws without those fields.
- **Last opened** record: `<data>/cards/landing_opened.json`, holding who last opened each episode and, per person, when they last opened each one (at most 200 episodes per person, newest kept). Written when a person enters an episode page, presses Open, or goes through `/cards/go/`; at most once per person per episode per 60 seconds. A missing or corrupt file reads as empty.
- **Episode sizes**: `<data>/cards/landing_sizes.json`. One background walker sizes episodes one at a time, oldest answer first, each re-sized after 12 hours. It counts bytes, files and newest modification time, does not follow links, stops after 400,000 entries and marks the result partial; an unreadable subfolder also marks it partial. If the episode folder itself cannot be read, the last good number is kept. The walker is started whenever the picker is drawn and something is missing or older than 12 hours.
- `GET /cards/state.json`: the same data as JSON, polled while an episode opens: episodes, cap, open count, ready slugs, the signed-in user. In state B: cap 0, open 0, nothing ready.
- `POST /cards/open` (form field `slug`): always a 303 redirect.
  - State B: to `/cards/go/<slug>`.
  - Not mounted: `/cards/?refused=Timeline Cards is not mounted`.
  - Slug not in the vault: `/cards/?refused=that episode is not in the vault`.
  - Cap or retry-floor refusal: `/cards/?refused=<sentence>`.
  - Success: starts the open, records the visit and "last opened", sets the carry-on cookie, redirects to `/cards/?want=<slug>`.
  - Cross-site protection is by Origin header (the dashboard's general rule for `/cards/`, outside this part).
- `POST /cards/close` (form field `slug`): state B or not mounted redirects to `/cards/`; a refused close redirects to `/cards/?refused=<sentence>`; otherwise the episode is closed (logged with who closed it) and redirects to `/cards/`.
- `GET /cards/go/<slug>`:
  - bad slug or slug not in the vault: redirect to `/cards/?refused=that episode is not in the vault`;
  - states A/C: redirect to `/cards/?want=<slug>`;
  - state B: records "last opened", sets the carry-on cookie, and redirects to the new editor at that episode's newest cut list, or the editor's own sheet when the episode has none (see the editor section).
- `GET /cards/icon.svg`: the checkout's icon if it has one, otherwise a built-in dark square with a red and a white card.
- App manifest, `GET /cards/manifest.webmanifest` and `GET /cards/p/<slug>/manifest.webmanifest` (reachable without signing in; any slug-shaped value accepted, others 404 `{"error":"not found"}`): the installed phone app "Timeline Cards" / "Cards", standalone, colours `#0b0b0b`, with the checkout's own manifest fields merged in when it imports, then forced to id, start address and scope `/cards/` and the icon above (as "any" and "maskable"). Installing from an episode page therefore installs the one app that opens on the picker.

## Timeline Cards: the picker's offline service worker (source: cards_landing.py)

- `GET /cards/sw.js` serves one of two scripts, with the dashboard version inside so each release reinstalls it, and `no-cache`.
- States A and C, the **offline front door**:
  - Navigations to `/cards/` and to `/cards/p/...` (the latter only when that episode has no worker of its own on the device): network with an 8-second deadline. If the browser says it is offline, the request fails or times out, or the server answers 500 or above, the saved picker is served instead, marked with a `cards-offline` tag carrying when it was saved (which turns the page into an offline picker).
  - If no picker was ever saved: a page "The server cannot be reached" / "The episode list has not been saved on this phone yet. Open the app once with a connection and it will be." then "Episodes this phone can open offline:" listing every episode whose own offline copy is on the device, and a "Try again" link.
  - A successful picker load (HTML, not a redirect, no `want` or `refused` in the address) is saved. A redirect to the login page is neither saved nor deletes the saved copy.
  - Assets (`/static/...`, `/favicon.ico`, `/cards/icon.svg`, `/cards/manifest.webmanifest`): saved copy first, refreshed in the background; if not saved, network, falling back to a saved copy ignoring the query string.
  - Accepts a message from the page asking it to save the page and a list of same-origin assets (because the first visit happens before the worker controls the page), and answers "saved".
  - Everything else, including `state.json` and all API calls, passes through. It never deletes any episode's own caches.
  - The saved picker is deleted by the login page after a real sign-out (outside this part), not when a sign-in expires.
- State B, the **retired front door**: a script that deletes the saved picker cache and unregisters itself. It does not touch any episode's own caches.

## Timeline Cards: health output (source: cards.py)

- The dashboard health response (`GET /api/v1/health`, route outside this part) carries a Timeline Cards block: status and detail; `old_page` = `retired` or `serving`; an `editor` sub-block (see the editor section); the cap; one line per open episode (slug, root, state, whether a Resolve agent is attached now, who the last agent was, occupants); the first ready episode's root; whether any agent is attached; and the Claude status (see the AI section) when any engine exists.
- "Agent attached" uses the engine's own recent-contact test when it has one; otherwise whether an agent ever attached.

## Timeline Cards: the new editor at /cards/edit/ (source: cards_edit.py)

- **Switch**: `DASH_CARDS_EDITOR=1` (exact value; default off, off in the vendor build). Off: nothing is registered, nothing is started, health says `disabled`, "DASH_CARDS_EDITOR is not 1".
- **Important**: "switched on" for the purpose of retiring the old page means only this setting. The old page is retired even when the editor cannot actually start (no Node, no bundle, no vault); people are then sent to an editor that answers "Timeline Cards is not running".
- On: the routes always exist, even when a prerequisite is missing, so a visitor sees what is missing. Status at boot: `mounted`, "proxying /cards/edit/ to a child process", or `absent` with the first missing prerequisite, or `absent`, "it could not be set up (<error>)".
- **Prerequisites**, checked in this order, first failure is the shown reason:
  - "no Timeline Cards checkout is configured (DASH_CARDS_SRC)";
  - "the Timeline Cards checkout is not there (<path>)";
  - "the editor bundle is not in the Cards checkout (<checkout>/editor/dist-server/host.mjs). Deploy a Cards commit that carries editor/dist-server/host.mjs";
  - "no vault is mounted here (DASH_CARDS_VAULT_ROOT)";
  - "the vault root is not mounted (<path>)";
  - Node runtime: `DASH_NODE` if set (a bare name is looked up on the PATH; a path must be a file, otherwise "DASH_NODE is set to <value> and that is not a file", with no fallback); else `/opt/node/bin/node`; else `node` on the PATH; else "no Node runtime here: the host's node directory is not provisioned (it is mounted at /opt/node) and there is no node on PATH. The deploy provisions it when [timeline_cards] editor is on";
  - the editor's data folder `<dashboard data folder>/cards-edit/` with subfolders `work`, `media`, `video`, `translate`, `search`, `home` must be creatable: "the editor's data directory cannot be made (<path>: <error>)".
  - A missing prerequisite is re-checked every 30 seconds while the dashboard runs (so provisioning Node or deploying a Cards commit later starts it without a restart); each new reason is logged once as a warning.
- **The child process**: started when the dashboard starts (not when the app object is built), as `<node> <checkout>/editor/dist-server/host.mjs --write`, working folder `<data>/cards-edit/`. `--write` means it edits the live vault, the same files the old page edits.
  - Port: `DASH_CARDS_EDITOR_PORT` if non-zero, otherwise a free loopback port chosen fresh on each start. Listens on 127.0.0.1 only.
  - A random secret is made once per dashboard process (kept across child restarts, memory only).
  - Environment: an allow-listed set only (the same environment the Claude Code command-line tool would get on this dashboard, or failing that just `PATH`, `HOME`, `LANG`, `TZ`, `TMPDIR`, `SYSTEMROOT`, `TEMP`, `TMP`); none of the dashboard's passwords or tokens. Plus: `TC_VAULT` (vault), `TC_HOST` 127.0.0.1, `TC_PORT`, `TC_MOUNT_BASE` `/cards/edit`, `TC_MOUNT_HOME` `/cards/`, `TC_PROXY_SECRET`, `TC_WORK`, `TC_MEDIA_CACHE`, `TC_VIDEO_CACHE`, `TC_TRANSLATE_CACHE`, `TC_SEARCH_DATA` (the subfolders above), `TC_PYTHON` (the dashboard's own Python), `PYTHONPATH` (the checkout), `PYTHONDONTWRITEBYTECODE=1`, `TC_STATIC` (`<checkout>/editor/dist` when present), `TC_CLAUDE_BIN` (the installed Claude Code binary when there is one), `HOME` defaulting to `<data>/cards-edit/home`. Node's folder is put first on the PATH.
  - Every line the child prints goes to the dashboard log prefixed `editor:`; the last 40 lines are kept, and the last 3 appear in the status after an exit.
- **Supervisor states**: `idle` ("not started" / "stopped"), `absent` (a prerequisite is missing), `starting` ("starting on 127.0.0.1:<port>"), `running` ("serving on 127.0.0.1:<port>"), `backoff`, `failed` (crash loop, still retrying, slowly).
  - Counts as running only when the port answers, the child is still alive 0.5 seconds later, and the port still answers.
  - A child that never opens its port within 120 seconds is killed ("it never opened its port; killing it").
  - After an exit: "the editor exited (exit <code> after <N>s); starting it again in <N>s. Last output: <...>". If it could not even be launched: "the editor could not be started (<error>); trying again in <N>s".
  - Restart delay: 1 s doubling per consecutive quick failure, capped at 60 s; after 5 consecutive quick failures the state is `failed` and the cap becomes 300 s. A child that lived 60 seconds or more resets the failure count.
  - Health reports state, detail, port, process id, restart count and last exit; `status` is `mounted` when running, otherwise `absent`.
- **Shutdown**: when the dashboard stops, the child is sent a terminate signal and given 15 seconds (the editor saves every open cut list on that signal), then killed.
- **Opening an episode in the editor** (used by `/cards/go/<slug>`): the newest `*.cut.md` (not starting with `.`) in `<episode>/Script Docs/Cuts/` by modified time, looked up at most once per 30 seconds per episode, becomes `/cards/edit/?key=<episode path relative to the vault>/Script Docs/Cuts/<file>`. No cut list, an episode outside the vault, or the vault itself gives bare `/cards/edit/`.
- **Routes** (all methods GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS):
  - `/cards/edit`: 308 redirect to `/cards/edit/`, keeping the query.
  - `/cards/edit/<anything>`: requires a signed-in session (otherwise 401 `{"detail":"login required"}`; the general login gate normally answers first). Forwarded to the child with the body streamed and the answer streamed back unchanged (status, all headers except hop-by-hop, `Date` and `Server`; range and partial responses pass through; compressed bodies pass as sent). Connect timeout 5 s, no read timeout, write timeout 120 s, at most 200 connections. Redirects from the child are passed back, not followed.
    - For a GET whose browser has gone away, the upstream request is closed at once.
    - Editor not running or unreachable: 503 with `Retry-After: 5`, `no-store`. A page navigation gets a small HTML page: heading "Timeline Cards is starting" (state starting or idle, and the page refreshes itself every 4 seconds) or "Timeline Cards is not running", the reason, "Your cut lists are untouched.", and a link "Back to the Timeline Cards page". A fetch gets JSON `{"detail": "<heading>: <reason>", "state": ...}`.
    - Any other failure to get an answer: 502 `{"detail":"the editor did not answer"}`.
  - Headers sent to the child: removed are hop-by-hop headers and any header named by `Connection`, every `X-TC-*` header the browser sent, `Authorization`, `Host`, all `X-Forwarded-*` and `Forwarded`, and the dashboard's own cookies `ccsync_session` and `ccsync_cards_last` (other cookies pass). Added: `Host: 127.0.0.1:<port>`, `X-Forwarded-Host` (the browser's host), `X-Forwarded-Proto`, `X-Forwarded-For` (client address), `X-TC-Proxy-Secret`, `X-TC-User` (the signed-in name with control characters removed, at most 120 characters, percent-encoded if not plain ASCII). A browser `Origin` equal to the page's own host (http or https) is rewritten to `http://127.0.0.1:<port>`; any other Origin is passed unchanged so the editor refuses it.
  - WebSocket at `/cards/edit/<anything>` (the editor's live `/sync` channel): checked here because the login gate never sees WebSockets. No session, or an Origin that is not the page's own host: closed with code 1008. Editor not running: 1013. The child refusing or not answering within 10 seconds: 1011 (logged). Otherwise relayed both ways, text and binary, no size limit, no compression, the browser's subprotocols passed and the child's choice returned; when either side closes, both close (a missing close code becomes 1000; abnormal or invalid codes become 1011).

## Timeline Cards: the Resolve agent tunnel (source: cards_tunnel.py)

- Purpose: an editor's companion, which drives that editor's DaVinci Resolve for Timeline Cards (the "agent"), talks to Timeline Cards through the dashboard using its ordinary fleet credential. The Timeline Cards server token never reaches an editor's machine.
- Three routes. Each requires a valid fleet caller (fleet token and verified editor identity, checked by a shared helper outside this part); they are not behind the browser session.
  - `POST /cards/agent/state`: the agent's swept timeline, or a playhead-only ping.
  - `GET /cards/agent/pending?wait=<seconds>`: long poll for the next edit to apply in Resolve. `wait` defaults to 25 and is clamped to 0..25.
  - `POST /cards/agent/result`: how that edit went.
- In every body, a `token` field is dropped, and any `token` key in the answer is removed.
- **The agent's display name** is rebuilt from the verified identity: `editor/MACHINE` from the declared `machine` field (characters kept: letters, digits, `-`, `_`, `.`, space); if no machine was declared, the last `/`-part of the body's own `name` is used as the machine half marked `~` (for example `alex/~CREATOR-1`), unless it equals the editor name; else the editor alone. At most 96 characters. The `machine` field is then removed.
- **Which engine gets the call** (when the old page is mounted with its pool):
  - `state` and `pending` go to the engine of the episode this editor is attached to (see "where an editor's Resolve agent goes"). `result` goes first to the engine that handed out that edit id, otherwise the same way.
  - Editor in no episode: answered with HTTP 200 `{"error": "<editor or 'this machine'> is not in a Timeline Cards episode on this dashboard: open one at /cards/ and this agent attaches to it", "attached": false}`. For `pending`, the dashboard first holds the request for the requested wait (checking every 0.5 s whether an episode has appeared; if one does, it continues with the time left), then answers `{"note": <that sentence>, "attached": false}`.
  - In state B (old page retired) the pool exists but is always empty, so every agent call gets this "not in a Timeline Cards episode" answer.
  - An engine error is answered 200 `{"error": "<message>"}` (logged as a warning), never a 500.
  - A pending answer that cannot be turned into JSON is handed back to the engine's queue before the request fails.
  - An edit handed out is remembered (per editor, the last one) so its result reaches the same engine.
- **Seats**: a state push that carries a timeline, a ping whose playhead differs from the engine's current one, and every result count as the editor being "in" that episode (keeps them an occupant even when their browser is offline). Idle pings and long polls do not.
- **Forwarding to a separate Timeline Cards server** (only when the dashboard has no Timeline Cards pool, that is the old page is not mounted at all):
  - Needs `DASH_CARDS_SERVER_URL` (trailing `/` trimmed) and `DASH_CARDS_TOKEN`. Missing URL: 503 "no Timeline Cards server is configured here (set DASH_CARDS_SERVER_URL on the dashboard)", or, when the Timeline Cards mount is not running, "Timeline Cards is not running on this dashboard: <mount reason>. No separate Timeline Cards server is configured either (DASH_CARDS_SERVER_URL on the dashboard)." Missing token: 503 "no Timeline Cards token is configured here (set DASH_CARDS_TOKEN on the dashboard)".
  - Sends the token as header `X-Cards-Token`, never follows redirects. Timeouts: 90 s for state and result, wait plus 20 s for pending.
  - Upstream 401/403: 502 "the Timeline Cards server refused this dashboard's token (check DASH_CARDS_TOKEN against the server's CARDS_TOKEN)". Other HTTP error: 502 "the Timeline Cards server answered HTTP <code>". Unreachable: 502 "could not reach the Timeline Cards server at <url> (<error type>)". Non-JSON: 502 "the Timeline Cards server did not answer with JSON". All logged as warnings.

## Pinned jobs: the dashboard's own worker for media jobs the fleet gave up on (source: cards_exec.py, jobs.py)

- A **pinned** job is a media job (`proxy-480p`, `audio-extract`, `peaks`; which kinds may pin is a list kept outside this part; the code states `whisper` never pins) whose fleet retry budget is spent, handed to the dashboard's own worker instead of being abandoned. A pin is one-way: nothing here ever puts it back in the fleet queue; a failure here makes it `abandoned`.
- Whether a job can pin depends on whether the worker is "available": there must be an open old-page Timeline Cards engine whose checkout offers the media seam. Otherwise the job is abandoned instead.
- The worker runs only when Timeline Cards is mounted; it checks for pinned work every 10 seconds (minimum 2). With no engine it does nothing that pass and records that it is waiting for one (shown in the job explanation).
- **State B (old page retired)**: the worker is made with no engine source, is never available, and every media job that spends its retries is abandoned. A job pinned before the retirement is explained as "Nothing will run it here: cancel it and queue it again", and the worker's reason reads "the old Timeline Cards page is retired, so this dashboard opens no engine to run a pinned job on".
- Other reasons it gives for not running: "no episode is open yet, so there is no Timeline Cards engine to hand a pinned job to"; "Timeline Cards is not mounted in this dashboard"; "the mounted Timeline Cards checkout has no fleet_execute() (plan section 7f)".
- **Per job**: claims the pinned row (so two passes cannot both take it), resolves its paths, hands it to the engine's single media queue, records progress as it goes, and ends it `done` (result marked with the dashboard as executor, output files listed relative to the output root, with the root named) or `abandoned` with the error.
  - Cancellation: the engine is asked to stop when the job's cancel flag is set (error text is the shared "cancelled" message) or when the dashboard is shutting down ("this dashboard is shutting down").
  - Log lines: "pinned job #<id>: <kind> of <source> -> <out dir> (nothing in the fleet would finish it)", "pinned job #<id>: done, <N> file(s)", "pinned job #<id> (<kind>) failed here too: <error>".
- **Paths**: a job names (root name, relative path) pairs, never absolute paths. This dashboard's root names:
  - `vault`: `DASH_CARDS_ROOT`, else `DASH_CARDS_VAULT_ROOT`;
  - `tree`: the dashboard's projects folder;
  - anything in `DASH_JOBS_ROOTS` (`vault=/vault,media=/media`), which overrides the above. `media` has no fallback.
  - Inputs: `root` (default `media`) plus `rel_path` is the source; `out_root` (default the source root) plus `out_rel` is the output folder (required: "a media job must name the directory its output goes in (out_root + out_rel)"); `out_stem` is the output name (default the source file's name without extension).
  - Refusals (the job is abandoned with the sentence): unknown root, "this container has no '<name>' root configured, so it cannot place this job's paths (DASH_JOBS_ROOTS)"; any `..` part, "'<path>' leaves its root"; an output name that is blank, a dot name, contains `/` or a control character, "the output name '<stem>' is not a plain file name (no slashes, control characters or dot names), so this job cannot be written here or anywhere". `:` and `\` are allowed.
- Stopping: waits up to 5 seconds for a pass to end; if it does not, it refuses to start a second worker later.

## Timeline Cards (old page): how its routes are carried (source: cards_wsgi.py)

- Every one of the old page's own routes is served unchanged under `/cards/p/<slug>/`, including byte-range media, with responses streamed (not buffered), and a slow browser slows the producer rather than filling memory.
- Duplicate `Date` and `Server` headers and connection-level headers from the page are dropped.
- A page route that crashes answers 500 `{"error": "the Timeline Cards handler raised; see the dashboard log"}` (logged), unless the browser had already gone, in which case nothing is logged as an error. A route that answers nothing gets 502 `{"error": "the Timeline Cards handler answered nothing"}`. A response head larger than 64 KiB with no end is an error.
- For GET and HEAD, when the browser disconnects, the page's next write fails as if the socket had closed, so an abandoned media stream (for example after a video seek) stops at once.

## Timeline Cards (old page): the Claude features (source: cards_ai.py)

- The old page's three Claude features (exact translations to English, semantic search over the transcripts, section summaries) plus its montage conversations and the "ask Claude" edit chat run through the dashboard's AI-provider chain (configured on Settings -> AI providers, outside this part). The new editor does not use this; it is handed the Claude Code binary directly (see the editor section).
- **Claude only**: if the site's chosen provider is not the Anthropic API key or the Claude Code command-line tool, every call fails with "this site's AI provider is <label>, and Timeline Cards' translate, semantic search and summaries are written for Claude. Set an ANTHROPIC_API_KEY (Settings -> AI providers), or pin Claude." No provider at all: the chain's own reason, or "no provider has a working credential". A failure resolving: "the dashboard could not resolve an AI provider (<error>)".
- The model name always comes from the page; nothing here keeps a model list.
- Failures are returned to the page as a sentence, never as a crash.
- **Status** (shown as the page's dimmed-button tooltip and in the health output; never makes a test call): ok, or "this site's AI provider is <label>, not Claude", or, when Claude Code is installed but has never been tested in this process, "Claude Code has not been checked on this server yet. Open Settings -> AI providers and click TEST beside it (or set an ANTHROPIC_API_KEY there).". Also reports how long the cached corpus lives (`1h` or `5m`).
- **Anthropic API path**: needs the site's key ("no ANTHROPIC_API_KEY is set for this site (Settings -> AI providers)"; "the `anthropic` SDK is not installed in this container (<error>)"). Up to 16,000 output tokens, low effort, default timeout 900 seconds. Each call logs model, seconds, input, cache read, cache write and output tokens. Error sentences: "the site's ANTHROPIC_API_KEY was refused for model <model>: <...>", "this API does not know the model <model>: <...>", "Claude did not answer in time", or "<error type>: <...>".
- **Claude Code path**: the binary is the admin-typed path, then the one the setup wizard installed, then the PATH; none: "Claude Code is the site's provider but this container has no such executable". Runs with flags from `YTDL_CLAUDE_CODE_ARGS` (default `-p --output-format json`), the prompt on standard input, its working folder `<data>/cards/` (never the vault), the Claude Code environment of the setup wizard. Errors: "Claude Code did not answer within <N>s", "could not run Claude Code (<error>)", "Claude Code exited <code>: <detail>", "Claude Code reported an error: <detail>".
  - Model names: a family name (`claude-sonnet-N[-M]`, `claude-opus-...`, `claude-fable-...`) is passed as the bare alias (`sonnet`, `opus`, `fable`) so the newest is used; a dated snapshot name is passed exactly; a family name older than the one the alias was last seen to resolve to is passed exactly (treated as a deliberate pin). An empty model means the tool's default.
  - What each alias actually resolved to is learned from the reply and recorded in `model_aliases.json` in the Claude Code tool folder (written only when it changes; a backwards move is logged as a warning). With no API key, this record is what the old page's model picker is offered as the list of available models; with a key, the list comes from the Anthropic models listing (30-second timeout).
- **JSON answers**: when the page wants a JSON file, the prompt gains a line asking for the JSON object alone; the reply's JSON is parsed and written to the file (a file the tool wrote itself wins). Errors: "the model returned no JSON: <last 300 characters>", "the model returned unparsable JSON: <...>", "the model's answer could not be written to <path> (<error>)". The model is never given file tools by this side.
- **Selected cards**: when the page sends the cards selected now (and staged cards on the shelf), a block headed `SELECTED CARDS` ... `END SELECTED CARDS` is added to the instruction part of the prompt (not the cached part): numbered in selection order, each with its id, label, person, timecode, text (each up to 120 characters) and section, group, lane (up to 80); beyond 40 rows the rest are listed by id only. Not added if the prompt already contains the header.
- **Montage conversations**: a conversation is kept per session id in `<data>/cards_sessions/<id>.json` (id reduced to letters, digits, `_`, `-`, at most 80 characters). Turn 0 opens (replacing any old one); a later turn whose id is not stored answers `session_lost` once, and the page decides whether to resend the corpus. On the Claude Code path the tool keeps its own conversation (`--session-id` then `--resume`), and its "no conversation found" / "not found" / "does not exist" / "no such session" / "already in use" messages also become `session_lost`.
  - The prompt is split at the last line reading exactly `---INSTRUCTIONS---`: the part before is the corpus (cached), after is the instruction.
  - Caching: the corpus is cached for 1 hour if the installed SDK supports it (otherwise 5 minutes, with a warning logged); a conversation keeps the cache time it was opened with. Each request marks the first corpus part, the last corpus part and the current turn for caching.
  - History kept: all leading corpus turns plus the most recent turns, 40 turns in all, cut in whole question-answer pairs. A conversation that cannot be saved is logged, and its next turn will be `session_lost`.

## Footage Sorter: mounting at /sorter (source: sorter.py)

- The Footage Sorter (another repo's app) is served in the dashboard at `/sorter`, behind the login. Never stops the dashboard from starting.
- Settings:
  - `DASH_SORTER_ENABLED`: exact `1` enables; default off. DEV ONLY: `SORTER_SRC` in the environment also enables it and supplies the checkout.
  - `DASH_SORTER_SRC`: the checkout folder (appended to the import path).
  - `DASH_SORTER_DATA`: its writable state folder (required).
  - `DASH_SORTER_CACHE`: thumbnails and filmstrips, default `<data>/cache`.
  - `DASH_SORTER_SETTINGS`: a JSON object of what the container knows (roots under the pool, ffmpeg, a legacy id table and so on); passed to the sorter. If it names `destRoot`, that folder must exist. If it has no `publicUrl`, the dashboard's own configured URL is added (used for the sorter's Google sign-in callback).
- Boot statuses: `disabled` "DASH_SORTER_ENABLED is not 1"; `disabled` "no footage-sorter checkout is configured (DASH_SORTER_SRC)"; `absent` "the configured checkout is not there (<path>)"; `disabled` "no data folder is configured (DASH_SORTER_DATA)"; `absent` "DASH_SORTER_SETTINGS is not JSON (<error>)" or "DASH_SORTER_SETTINGS must be a JSON object"; `absent` "the pool is not mounted here (destRoot <path>)"; `absent` "the checkout did not import (<error>)"; `mounted` "serving <destRoot or data folder>".
- The sorter's data loads in the background after boot. If the load fails, the status becomes `absent` "the footage sorter could not load its data (<error>)", the nav link is hidden, and the status page says why. When loaded, the log says "Footage Sorter loaded: <N> clips, data <folder>". Folders the sorter may use are locked to the configured roots.
- `destRoot` is registered with the dashboard's periodic mount checker.
- On shutdown the sorter is stopped; a load still in progress when the dashboard stops never starts the sorter.

## Footage Sorter: the gate in front of the page (source: sorter.py)

- `/sorter` (exactly): 307 redirect to `/sorter/`.
- `/sorter/api/whoami`: answered by the dashboard: `{user, admin, csrf}` from the session (nobody / not admin / empty token on any failure). The page sends that CSRF token on writes, so `/sorter` has normal CSRF protection.
- Any other request while the sorter is still loading is held up to 120 seconds; then 503 `{"error": "<load failure sentence>"}` or "the footage sorter is still loading: try again in a moment" (no-store).
- Identity: any incoming `X-Sorter-User` and `X-Sorter-Admin` headers are removed and replaced with the signed-in user and `1`/`0` for admin (the sorter uses these to decide who may execute a move, admins only, and whose name goes in its journal). A user name that cannot be written in Latin-1 gets no identity header (logged as a warning).
- WebSocket and other non-HTTP traffic passes straight to the sorter when loaded.
- **Moves inside Projects**: when the sorter moves a clip whose source is inside the Projects tree, the move goes through the dashboard's own "move on the server and on every machine" file move, so editors' copies follow. The source and destination must each lie inside an active CC Sync project (the longest matching project folder wins); otherwise the move fails with "<path> is in no CC Sync project, so no editor's copy can follow it". A refusal from the file move is passed back as the error. Moves into Projects from elsewhere (for example Temp Transfer) are plain renames by the sorter.

## Footage Sorter: camera-card ingest, drive copies and the drive ledger through the companions (source: sorter.py, jobs.py)

- All routes below are under `/sorter/agent/`, called by companions with the fleet credential (no session, no CSRF; the editor is the verified identity, never a body field). If the sorter is not loaded: 503 "the Footage Sorter is not running on this dashboard" (ledger routes: "the Footage Sorter's ledger is not running on this dashboard"); a companion backs off on 503.
- `POST /sorter/agent/cards`: this machine's full list of camera cards in its readers. Body `{machine, cards: [...]}`; machine trimmed to 128 characters. Refusals: 422 "expected {machine, cards: [...]}", 413 "at most 16 cards in one report", 413 with the sorter's own reason. Body size limit 8 MB (enforced by the dashboard's general body gate).
- **Queuing a copy**: when a person presses Copy in the sorter, the dashboard queues a `card-ingest` (or `drive-copy`) fleet job: priority 5, forced (no idle wait, no cooldown, no 60-second preference), targeted at `<signed-in editor>/<machine>` (or the bare machine name when the sorter gives no editor), created by `sorter:<user>`. Logged "sorter: job #<id> (<kind>, <N> files) queued for <target> by <user>".
  - Status shown back to the sorter: the job's state, progress, result and last error; a job missing from the queue reads as `abandoned`, "the job is gone from the queue".
  - Cancel from the sorter requests the job's cancel (as `sorter`).
- Routes bound to a claimed job (the job must exist and be of the right kind, else 404 "no such card copy job" / "no such scan job"; it must be claimed by the calling editor, else 409 "this job is not claimed by you"):
  - `GET /sorter/agent/ingest/<job id>`: the list of files to copy (kept out of the job row because job rows are capped at 16 KB). A suspended account gets 410. 404 / 409 with the sorter's reason.
  - `POST /sorter/agent/ingest/<job id>/receipt`: the finished copy's receipt. 404 / 422 with the sorter's reason. Logged.
  - `POST /sorter/agent/ingest/<job id>/progress`: live copy progress (about every 2 seconds), stored for the browser.
- **The drive ledger** (the sorter's record of which drives hold which copies):
  - `POST /sorter/agent/volumes`: the machine's volumes (drives, cards, fixed disks), sent on change and every five minutes. Body `{machine, volumes, digest}` (digest up to 128 characters). Refusals: 422 "expected {machine, volumes: [...], digest}", 413 "at most 64 volumes in one report"; body limit 1 MB. Answers which volumes the ledger wants scanned now, each with a `ledger-scan` job id.
  - `GET /sorter/agent/ledger/scan/<job id>`: what to scan (suspended account: 410).
  - `POST /sorter/agent/ledger/scan/<job id>/chunk`: one batch of `[path, size, mtime]` rows, plain or gzip (`Content-Encoding: gzip` / `x-gzip`). Wire limit 4 MB; decompressed limit 3 MB, checked while inflating. Refusals: 400 "the chunk is not valid gzip", "the chunk's gzip stream is truncated", "the chunk is not JSON"; 413 "a chunk may be at most 3 MB decompressed" or "the chunk is too large"; 415 "unsupported Content-Encoding '<x>'"; 422 "expected {rows: [...], seq}" / "expected {rows: [...], seq: n}"; 413 "at most 10000 rows in one chunk". The claim is checked before inflating. An `attempt` number is passed on when the ledger supports it (a reclaimed job's stale chunks are refused).
  - `POST /sorter/agent/ledger/scan/<job id>/finish` and `.../progress`.
  - `POST /sorter/agent/ledger/copies`: verified copies a companion made (idempotent on volume + path + size + modified time). Body `{machine, copies}`; at most 5000 copies (413), body limit 4 MB; 422 "expected {copies: [...]}". A volume may be named only by its serial: any `id` or `kind` the companion sends on a volume is removed. Answers accepted and duplicate counts.
  - `GET /sorter/agent/ledger/mirror?volumes=<ids>&since=<cursor>&limit=<n>`: the ledger's copies for up to 64 volume ids changed since the cursor (cursor up to 64 characters), `limit` clamped to 1..20000, default 5000; answers rows, the next cursor and whether there is more. Suspended account: 410.
  - Ledger errors: "not found" style errors are 404, "this scan is finished or abandoned" is 409, other bad input 422.
- Scheduling of these kinds (jobs.py): `card-ingest`, `drive-copy`, `ledger-scan` have an idle floor of 0 and no ranking signals; a machine may hold a `ledger-scan` alongside one other job, but only one `ledger-scan` at a time.

## B-roll search: mounting at /broll (source: broll.py; setting names from settings.py)

- The b-roll search app (this repo's `broll/web`, another agent's part) is served in the dashboard at `/broll`, behind the login, in-process (so video byte-range answers are served directly). Never stops the dashboard from starting. The decision to mount at all is taken outside this file (setting `DASH_BROLL_ENABLED`, exact `1`, default off).
- **Ingest token** `BROLL_INGEST_TOKEN` (required for the mount): refused when not set ("is not set"), a known placeholder (`replace_me`, `changeme`, `todo`, `secret`, `password`, `token`, `test`, `example`, `your-token-here`, `xxx`, `none`, `null` and spelling variants: "is the placeholder '<x>' (a value that is in the public repo)"), shorter than 24 characters ("is only <N> characters; at least 24 are required"), or with fewer than 8 distinct characters ("has too little variety to be a random secret"). The dashboard refuses to start with such a token when b-roll is enabled (that check is outside this file); this file refuses to mount: `absent`, "no usable BROLL_INGEST_TOKEN is configured, so the b-roll ingest write path cannot be guarded".
- Boot statuses: `absent`, "the b-roll checkout did not import (<error>)"; `degraded` (mounted but hidden from the nav, every request will fail): "the b-roll database was written by a newer version of the b-roll app than this server runs, so no /broll page can open it (<error>)" or "the b-roll data root could not be prepared (<error>); every /broll request will fail until it is writable by this container's uid"; `mounted`, "serving /broll".
- DEV ONLY: when the b-roll app is not on the import path, the in-repo `broll/web` is used if present, with a log line saying so.
- At mount the dashboard does what the b-roll app's own start-up would do: creates its data root and the `proxies`, `sprites`, `posters`, `sheets` folders, applies its database schema, and (best effort) the client-folders database schema. A client-folders failure does not degrade the mount.
- The data root is registered with the periodic mount checker, using the `proxies` folder as the witness that the share is really there.
- The b-roll app is told it may trust the dashboard's fleet stamp (below). If its version cannot, a log line says that an editor holding a per-editor token "cannot run a drop until it is redeployed".

## B-roll search: the gate in front of the app (source: broll.py)

- `/broll/docs`, `/broll/docs/oauth2-redirect`, `/broll/redoc`, `/broll/openapi.json`: 404 `{"detail":"Not Found"}` (no API explorer).
- `/broll/api/ingest/...` (the indexer's write path): requires header `X-Ingest-Token` equal to the ingest token (compared as bytes, constant time), always, even for a signed-in editor; otherwise 401 `{"detail":"missing or invalid X-Ingest-Token"}` and a logged warning.
- On every request:
  - Any incoming `X-CCSync-User`, `X-CCSync-Admin`, `X-CCSync-Fleet-Auth` headers are removed; identity headers of a suspended or barred account are also stripped (a shared helper outside this part).
  - `X-CCSync-User` is set to the signed-in user (as the login gate resolved it, honouring previous session secrets after a rotation and server-side revocation); `X-CCSync-Admin: 1` is added for an admin. A name that cannot be written in Latin-1 gets no header (logged), so the b-roll app answers 401 for that person.
  - **Fleet stamp**: when the request carries a companion's `X-CCSync-Token`, the dashboard checks it (shared fleet token or a per-editor token) and adds `X-CCSync-Fleet-Auth: shared` or `editor:<name>`. No stamp when the token does not verify, the database cannot be read, the editor's account is suspended or barred (logged "b-roll fleet stamp withheld for '<editor>': <reason>"; an unreadable account state does not block), or the name is not Latin-1.
- Session lookups and the Range-streamed media pass through unbuffered.

## Music search: mounting at /music (source: music.py)

- The music search app (this repo's `music/web`, package `musicweb`, another agent's part) is served at `/music`, behind the login, in-process (audio byte-range answers served directly). Never stops the dashboard from starting. Whether it is mounted at all is decided outside this file.
- No ingest token is needed or checked here (unlike b-roll).
- At mount, the music app is told that it sits behind the dashboard login, so its drag-and-drop ingest accepts the session as the credential. If its version cannot be told, a warning says "its ingest route will refuse unless MUSIC_INGEST_TOKEN is set".
- At mount the music data folder is created and the database opened and its schema applied (as a probe).
- Boot statuses: `absent`, "the music checkout did not import (<error>)"; `degraded` (mounted, hidden from the nav): "the music database was written by a newer version of the music app than this server runs, so no /music page can open it (<error>)" or "the music data root could not be prepared (<error>); every /music request will fail until DATA_ROOT is writable by this container's uid"; `mounted`, "serving /music".
- DEV ONLY: the in-repo `music/web` is used when the package is not on the import path, with a log line.
- The data folder is registered with the periodic mount checker, with the database file as the witness.
- Gate on every request: `/music/docs`, `/music/docs/oauth2-redirect`, `/music/redoc`, `/music/openapi.json` answer 404 `{"detail":"Not Found"}`; identity headers `X-CCSync-User` / `X-CCSync-Admin` and the fleet stamp `X-CCSync-Fleet-Auth` are stripped and re-minted exactly as for b-roll (same rules for suspended accounts, Latin-1 names, previous session secrets). There is no token refusal: a companion token that does not verify is simply not stamped.

## YouTube downloader: the site switch and mounting at /ytdl (source: ytdl.py)

- The YouTube downloader app (this repo's `ytdl/web`, package `ytdlweb`, another agent's part) is served at `/ytdl`, behind the login, in-process. Never stops the dashboard from starting.
- **Site switch** `youtube_download` (off in the vendor build): read from the site settings row first (what Settings writes), then from `DASH_SITE_YOUTUBE_DOWNLOAD` in the environment; if the row cannot be read, the environment decides (logged as a warning). The answer is reused for 5 seconds, so ticking or unticking it on Settings takes effect within 5 seconds with no restart.
- **Switch off at boot**: nothing of the downloader is loaded. Status `disabled`, "this site has not enabled the YouTube downloader ([features] youtube_download)". Every path under `/ytdl` answers 404 `{"detail":"Not Found"}`; a WebSocket is closed with code 1000.
- **Switch turned on later**: the next request loads the downloader inline (import, storage set-up, worker start) and serves it; logged "ytdl UI loaded on demand: this site enabled the YouTube downloader while the dashboard was running". A failed load is not retried for 60 seconds; meanwhile requests get 404.
- **Switch turned off later**: requests answer 404 again and the status goes back to `disabled` (the loaded code stays in memory).
- Each change of state is written to the app state (nav link shown only when `mounted`) and to the dashboard's mount-status record used by alerts.
- **Switch on at boot**: loads at once. Statuses: `absent`, "the ytdl checkout did not import (<error>)" (then nothing is mounted at `/ytdl` at all and a later switch change cannot load it; a redeploy is needed); `degraded` (served, hidden from the nav), "the ytdl data root could not be prepared (<error>); every /ytdl request will fail until YTDL_DATA_ROOT is writable by this container's uid"; `mounted`, "serving /ytdl".
- DEV ONLY: the in-repo `ytdl/web` is used when the package is not on the import path, with a log line.
- At load the dashboard does the downloader's start-up: creates its data folder (`YTDL_DATA_ROOT`, default `./data`), applies its database schema, starts its single download worker (which first recovers jobs left mid-way by a restart), and starts its download canary if the downloader has one (the canary does nothing unless `YTDL_CANARY_INTERVAL_SECONDS` is set; it ships unset). The data folder is registered with the mount checker, with `ytdl.db` as the witness.
- The downloader's two AI calls are given the dashboard's provider chain (re-read per call, so keys changed on Settings apply at once). If that cannot be installed, a warning says it will fall back to `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` from the environment.
- The downloader is told it may trust the fleet stamp; an older version logs that an editor with a per-editor token "cannot download locally until it is redeployed".

## YouTube downloader: the gate in front of the app (source: ytdl.py)

- `/ytdl/docs`, `/ytdl/docs/oauth2-redirect`, `/ytdl/redoc`, `/ytdl/openapi.json`: 404 `{"detail":"Not Found"}`.
- Every request: incoming `X-CCSync-User` and `X-CCSync-Fleet-Auth` are removed; barred identities are stripped; `X-CCSync-User` is set to the signed-in user (same resolution rules as b-roll; Latin-1 only, else no header and a logged warning). No admin header is added here (unlike b-roll and music). The downloader uses the user to decide which projects a download may go into and whose jobs may be read.
- Fleet stamp as for b-roll: `shared` or `editor:<name>`, withheld for a suspended or barred account ("ytdl fleet stamp withheld for '<editor>': <reason>"), an unreadable token, an unopenable database, or a non-Latin-1 name.
- **Health for alerts**: when `/ytdl` is mounted or degraded, the dashboard's self-checks can read the downloader's own health (yt-dlp age, PO-token provider, cookies, last download, canary, Claude, worker alive, plugin install) without a network probe; nothing when the downloader is not loaded.

## YouTube downloader: one person's records (export, erase, delete) (source: ytdl.py)

- Used by the dashboard's account-privacy features (callers outside this part). Works whether or not the site switch is on, and never creates the downloader's database.
- **Export**: everything `ytdl.db` holds about a user, table by table; empty when the database does not exist or the installed downloader is too old to support it.
- **Erase history**: deletes the user's finished YouTube jobs with their search terms and videos; keeps the de-duplication ledger, attestations and anything still running. Returns counts per table.
- **Delete a person**: releases their live job leases, cancels their unfinished jobs, and replaces their name (and their computer names) with the dashboard's stand-in name, in one transaction; then nudges the download worker if anything was released or stopped. Returns `ok` with the stand-in and counts, or `absent` when there is no store. Refuses when no stand-in can be made: "no stand-in name for the deleted person: the dashboard database was not found" or "the stand-in name for the deleted person could not be made (<error>)".
- Errors raised to the caller: "the YouTube downloader's records could not be opened (<error>)" (including a database at a newer schema), "... could not be read", "the YouTube downloader's history could not be erased", "the YouTube downloader's records could not be updated".

## Looks redundant or overlapping

- Two Timeline Cards pages exist side by side: the old page (engine pool, episode picker open/close/seat cap, occupancy, Resolve agent tunnel routing, offline picker worker, pinned-job worker, Claude runner, WSGI shim) and the new editor (Node child process plus proxy). Once the editor flag is on, the old page and everything that exists only to serve it (pool, open/close, seat sentences, tunnel routing to engines, pinned-job execution, `cards_ai`, `cards_wsgi`, the offline front door) is dormant unless `DASH_CARDS_OLD_PAGE=1`.
- The agent tunnel has two back ends: the in-process engine and forwarding to a separate Timeline Cards server (`DASH_CARDS_SERVER_URL`), used only when the old page is not mounted at all.
- Three kill-switch service workers plus one real one for Timeline Cards: `/cards/sw.js` front door, `/cards/sw.js` retired version, `/cards/p/<slug>/sw.js` retired version.
- Three recency records for Timeline Cards: the carry-on cookie, the "last opened" JSON file, and in-memory occupants/last-in.
- The b-roll, music and YouTube gates are three near-copies of the same identity-stamping and fleet-stamp code (session lookup, strip-then-append, suspended-account check, Latin-1 rule, docs blocking, path readings); `ytdl.py` carries its own copies of `_header_value` and `_session_cookie` that `broll.py` also has.
- `_wants_html` and `sub_paths` exist in several of these files with the same logic.
- The output-name ("stem") rule is written twice here (`jobs.out_stem_problem` at submit time and `cards_exec._plain_stem` at run time) and a third time in the companion.
- `parse_media_map` and `has_transcripts` are copies of functions in the Timeline Cards repo.
- Two ways past the idle floor (forced jobs, volunteering) plus the base-machine exemption.
- The job explanation answers twice: a `reason_code` (worst answer wins) and a `summary` (commonest refusal), which can name different causes.
- `app.state.cards_engine` (single-engine era) is still read alongside the pool in health, tunnel and pinned-worker lookup; nothing in this part ever sets it to an engine.
- B-roll ingest-token placeholder and strength checks duplicate the dashboard's boot-time secret check (outside this part).

## Claims the code does not back

- `jobs.py` module docstring: "rank -- priority, then age". The ranking in this file never reads priority or age; it ranks by preference signals, held jobs, load and idle. (Queue order comes from `db.queued_jobs`, outside this part.)
- `cards.old_page_retired` docstring: "True when the new editor is on". It is true when the editor's setting is on, whether or not the editor can actually start; with Node or the bundle missing, the old page is still retired and people are sent to an editor that answers "Timeline Cards is not running".
- `cards.py` module docstring says the handler's `self.server` "refuses" to shut down; the stand-in object only logs an error (the real protection is the blocked `/api/restart` route).
- `cards_landing.py`: "re-walking three levels of it every two seconds"; the scan walks four levels.
- `cards_landing.py` CARDS_SW comment: "this worker deletes nothing but its own saved page"; the front-door worker deletes nothing at all (deletion is done by the login page or by the retired worker).
- `cards_exec.py` docstring: "`whisper` never pins". Nothing in this file refuses a whisper job; that rule lives in a list outside this part and could not be checked.
- `cards_ai.py` docstring heading "FIVE DECISIONS" is followed by seven numbered decisions.
- `cards_ai.py` decision 1 names the Claude models by version; the code keeps no model list at all and passes whatever the page sends.

## Could not determine

- The job HTTP routes (`GET /api/v1/jobs/<id>/why`, cancel, submit, claim, report-reply offers) are defined outside this part; how cancel works for queued, held and pinned jobs, when a job's retry budget is spent, and which kinds may pin (`JOB_PINNABLE_KINDS`) are not in these files.
- Queue order of `db.queued_jobs` (priority, age) and how `forced`, `priority` and `target_machine` are stored.
- How `DASH_JOBS_ROOTS` and `DASH_JOBS_MAX_RUNNING` strings are parsed (settings code outside this part).
- Whether the b-roll and music mounts are switched by settings, and the dashboard's start-up refusal for a weak `BROLL_INGEST_TOKEN` (both in `app.py`).
- The login-gate and CSRF carve-outs for `/cards/agent/*`, `/sorter/agent/*`, the manifest paths and `/cards/` (in `app.py`), and the body-size gate's behaviour on the sorter limits beyond the byte numbers named here.
- The routes of `/cards/app/` (`cards_app.py`, not in this part).
- What the old page does with `DASH_CARDS_DB_HOST`, `DASH_CARDS_DB_NAME`, `DASH_CARDS_DB_WRITE_ALLOW`, `DASH_CARDS_DB_BACKUPS`, `DASH_CARDS_PROJECT` (passed straight to the other repo's engine).
- Whether the deployed Timeline Cards checkout offers the media seam (`fleet_execute`), so whether pinning can ever happen in state A.
- What the sorter's own routes and pages do (`footage_sorter`, another repo).
- Whether omitting the admin header on `/ytdl` is deliberate or an oversight.

