# bug-broll - pre-launch bug hunt, b-roll web app, indexer, publish drain

Lens `bug-broll`, 2026-10-06, HEAD 08b40eb plus the uncommitted working tree.

**What I read:** every file in `broll/web/app/`: routes_share, client_folders, routes_client_folders, main, media, routes_media, routes_ingest, routes_batches, routes_fleet, fleet_auth, identity, ingest_batches, archive_names, routes_api, config. I also read the cache halves of semantic.py and fuzzy.py.

On the static side I read the HTML-injection sinks in share.js, app.js, clientfolders.js and ingest.js, plus `cfShareUrl`. In the indexer I read `storage/http_backend.py` and the stills and copy logic in `build_archive.py`. Following the calls out of my territory, I read `server/broll_drain.py` (export and apply), the drain/swap sequence in `server/publish_db.py`, the BrollGate and login_gate carve-outs in the dashboard, and the rclone `copyto` argv in the companion's `broll_upload.py`.

**Probes I ran:** small scripts with the broll/web venv against the real modules, each on a temporary `BROLL_DATA_ROOT`:

- `p_upsert.py`: a partial `/api/ingest/video` upsert.
- `p_case.py`: archive-name allocation across shoot names and folder names that differ only in case or Unicode normalisation.
- `p_release.py`: `release('done')` while items are still unfinished.
- `p_perf.py`: the cost of the public media membership check after ids are renumbered.
- A Node one-liner for the URL host setter.

**What I did not cover:** search.py beyond its imports, and the remaining indexer modules (local_vlm, local_runtime, parallel_*, run_queue, sorter, taxonomy). I only checked broll/eval for tracked secrets and media (the bundle is not tracked). I did not run any test suite.

**Already in the ledger:** the 2026-09-24 broll findings bug-broll-1, -2 and -4 are fixed in the tree. bug-broll-3 (preview stills keyed by id) is still open as an owner decision and is re-reported below as bug-broll-6.

---

### bug-broll-1 - The archive-name allocator compares folders by exact bytes: two shoot names that differ only in case, or a folder name typed on a Mac versus on Windows, get the same file name, and the second upload overwrites the first clip's proxy and original

- Severity: high
- Confidence: CONFIRMED for the allocation (probed). PLAUSIBLE for the overwrite, which depends on the archive dataset being case-insensitive or normalising Unicode.
- Where: `broll/web/app/ingest_batches.py:275-317` (`_taken_names`), `:320-337` (`_allocate`), `:257-268` (`archive_dir_for`); `broll/web/app/routes_batches.py:66-86` (`_validated_share`); `companion/src/ccsync_companion/broll_upload.py:159-195` (`rclone copyto` overwrites a file that differs).
- What: there are two places a name can count as taken:
  - **Published archive paths.** These are read with a case-insensitive `LIKE`, but then kept only when `str(parent) == archive_dir`. That comparison is exact on bytes.
  - **Rows claimed in the same share.** These are filtered with `share = ?`, which is also exact.

  `UNIQUE(share, rel_path)` is exact too. So `Taiwan Shoot` and `taiwan shoot` are two separate shares whose archive folders differ only by case. And within one share, a folder name typed in NFC (Windows) and the same name in NFD (from a Mac listdir) are two separate folders. Neither case sees the other's names. `claim_key` lowercases the stem but never the folder, and nothing normalises Unicode (the CR-90 class of bug).
- Scenario: the probe gave this output.

  ```
  Taiwan Shoot -> Creators_Club/Taiwan Shoot/Day1/Proxy/C0001.mp4 | Creators_Club/Taiwan Shoot/Day1/C0001.MP4
  taiwan shoot -> Creators_Club/taiwan shoot/Day1/Proxy/C0001.mp4 | Creators_Club/taiwan shoot/Day1/C0001.MP4
  NFC -> Creators_Club/Interviews/Šimalč\xedk/Proxy/C0001.mp4
  NFD -> Creators_Club/Interviews/Šimalčík/Proxy/C0001.mp4
  ```

  Camera clip names restart on every card (C0001, A001_C001), so a second session for the same shoot with different capitalisation is the ordinary way this happens. On an SMB-style dataset (case-insensitive and/or normalising), both claims resolve to one file on disk:
  1. The second companion's `rclone copyto` replaces the first clip's preview and its ORIGINAL.
  2. `mark_uploaded` checks the second clip's size and puts it live.
  3. The first clip's row still points at the same path, so it now plays the second clip's footage.
  4. The first original is gone. Nothing stashes it, unlike build_archive's trash.

  The same blindness applies to a base-rig share with `archive_name` set ("MOFA Disaster") when an editor types "mofa disaster". On a case-sensitive dataset the result is two folders that Windows/SMB editors cannot tell apart.
- Recommendation:
  - Compare archive folders with a case-folded, NFC-normalised key in both `_taken_names` sources: casefold plus NFC on `archive_dir` and on the `str(parent)` test, and a share match that ignores case and normalisation.
  - Normalise `share` and `rel_dir` to NFC on the way in (create and precheck).
  - Make `_validated_share` refuse, or map onto, an existing share or archive folder that differs only in case or normalisation.
  - Defence in depth: make the companion's upload refuse to overwrite a destination it did not create (for example `--ignore-existing` on the original), or have `mark_uploaded` refuse a path another `videos` row already owns.
- Known: new. This is the CR-90 class applied to ingest naming.

### bug-broll-2 - A partial `/api/ingest/video` upsert wipes the clip's hash, size, duration, dimensions, codec, shot date and inbox flag

- Severity: medium
- Confidence: CONFIRMED (probed with the real app and TestClient)
- Where: `broll/web/app/routes_ingest.py:68-108` (the `ON CONFLICT ... DO UPDATE` uses `hash = excluded.hash`, `size_bytes = excluded.size_bytes`, ... and `in_inbox = excluded.in_inbox`); caller `broll/indexer/broll_index/storage/http_backend.py:129-140` (`update_video` posts only the changed fields); `broll/indexer/broll_index/pipeline.py:109,176,208` (for example `update_video(id, status="proxied", **geometry)`) and `set_error`.
- What: `VideoIn` defaults every field to None (and `in_inbox` to False). The upsert COALESCEs only some columns: category, error, the sprite geometry, frames/start_tc/bitrate, archive paths. The rest are overwritten with whatever arrived. `HttpBackend.update_video` sends only `{share, rel_path, **fields}`, so every stage update after the probe nulls the probe data on the server.
- Scenario: the probe posted a full probed row, then `{"status":"proxied","sprite_cell_w":160}`. The result:

  ```
  {'hash': None, 'size_bytes': None, 'duration_s': None, 'width': None, 'height': None, 'codec': None, 'in_inbox': 0, 'status': 'proxied', 'sprite_cell_w': 160}
  ```

  This happens to every clip any `db.mode: api` indexer touches: a customer whose indexer is not co-located with the NAS. The consequences:
  - Duration, resolution and codec filters and the detail panel go blank.
  - The precheck duplicate test (by `hash`) never matches.
  - The client-folder hash identity stays blank.
  - `edit_weight` answers "cannot tell".
  - `in_inbox` resets to 0, so the sorter loses track of inbox clips.

  Every `set_error` does the same.
- Recommendation: COALESCE every column on conflict, as the comment for `error` already argues. Treat `in_inbox` as nullable (`bool | None`) and COALESCE it too. Add a test that posts a partial update after a full one.
- Known: new. The 2026-09-24 bug-broll-2 fixed the id half of http_backend, not this.

### bug-broll-3 - Publishing the b-roll index while a dashboard ingest batch is running silently loses that batch's writes and re-numbers its clips under the running companion; publish_db does not refuse

- Severity: medium
- Confidence: CONFIRMED by reading the sequence end to end. Not run against a live publish.
- Where: `server/publish_db.py:898-981` (drain taken, then swap, then apply; `open_batches` is only printed); `server/broll_drain.py` EXPORT (a snapshot of `ingest_items`/`videos` at time T) and APPLY (`INSERT OR REPLACE` of the T-snapshot over the published file; drained videos re-inserted at `cur.lastrowid`); `broll/web/app/ingest_batches.py:1174-1345` (`mark_uploaded`), `:1069-1145` (`write_item_result`); `docs/INDEXERS.md:315-319` ("Pause ingest first if you can").
- What: the drain is a snapshot. Anything the live app writes between the export and the rename lands in the file that is about to be renamed away: checkpoints, `/result`, `/uploaded`, release. Between the rename and the apply, the new file has no rows for the batch, so fleet calls answer 404. The apply then restores the stale snapshot with `INSERT OR REPLACE`. It also re-mints every drained video id, while the companion still holds the old ids from its claim manifest and uploads `posters|sprites/<old id>.jpg`. Nothing enforces "pause ingest first": `open_batches > 0` is printed and the publish goes ahead.
- Scenario: a 300-clip idle-mode batch runs overnight and the operator publishes in the morning.
  1. A clip whose `/uploaded` landed in the window is restored as `uploading`, with `videos.status = 'ingesting'`.
  2. The companion already counts it live and moves on, then releases `done` (see bug-broll-4). The clip's media is in the archive, but it is invisible to search and browse for ever.
  3. A `/result` in the window is lost, so the later `/uploaded` gets 409 `no_result` and the item fails.
  4. Every clip of the batch gets a new id, so its uploaded poster and sprite sit under a number that now belongs to nothing, or to another clip (bug-broll-6).
- Recommendation: make publish_db refuse while `open_batches > 0` (claimed or running with a live lease), or add an explicit `--allow-running-ingest`. Better, have it set a site-wide ingest hold that the claim, heartbeat and per-item routes answer with a retryable status. Take the drain under that hold and clear it after the apply. Print the open batches by machine and editor in the refusal.
- Known: partly documented as an operator caution in docs/INDEXERS.md ("a batch that starts between the drain and the rename"). The in-flight-writes loss and the id re-mint under a live companion are not recorded.

### bug-broll-4 - `release('done')` while items are unfinished ends the batch as `done`, leaves invisible `ingesting` rows holding names, and nothing can retry them

- Severity: medium
- Confidence: CONFIRMED (probed)
- Where: `broll/web/app/ingest_batches.py:1350-1398` (`release`: `final` is downgraded only for `n_failed`/`n_proxies_live`), `:584-651` (`retry_failed` moves only `failed`/`proxies_live`).
- What: the server trusts the companion's "done". Items still at `pending`, `describing`, `indexed` or `uploading` do not make the batch `done_with_errors`. Their `videos` rows stay `ingesting`, which is invisible and reserves the name, and there is no way back.
- Scenario: probe output for a 2-item batch, one item at `uploading` and one at `pending`, released as done:

  ```
  {'state': 'done', 'n_items': 2, 'n_done': 0, ...}
  ['uploading', 'pending'] ['ingesting', 'ingesting']
  retry_failed -> retried 0
  ```

  The panel says "finished" and the footage never appears. Any divergence between the companion's local ledger and the server produces this shape: the publish window in bug-broll-3, a swallowed 400 or 409 on a checkpoint, or an older companion.
- Recommendation: in `release(state="done")`, treat every item not in `ITEM_FINISHED` as a failure. Mark it `failed` with a reason such as "the computer finished without this clip", so that `done_with_errors` and `retry_failed` both reach it. Log the mismatch.
- Known: new.

### bug-broll-5 - A client link built against a public base with no explicit port keeps the dashboard's own port, so the link is dead for the client

- Severity: medium
- Confidence: CONFIRMED (the URL-setter behaviour was probed in Node, and the code path was read)
- Where: `broll/web/static/clientfolders.js:54-62` (`cfShareUrl`: `local.protocol = pub.protocol; local.host = pub.host`).
- What: the WHATWG `URL.host` setter leaves the existing port alone when the new value carries none. A public base such as `https://share.studio.com` or `https://nas.tailXXXX.ts.net` (Funnel on 443, or any reverse proxy or Cloudflare tunnel on the default port) therefore inherits the port of the URL the editor is browsing the dashboard on.
- Scenario: the editor browses `http://truenas:8090/broll/` and the public base is `https://nas.tail1234.ts.net`. The copied link is `https://nas.tail1234.ts.net:8090/broll/share/<token>/`, which no Funnel or proxy answers. The client gets a connection error, and the editor sees nothing wrong because their own copy test is done from inside the tailnet. The documented `:8443` setup works only because it names a port explicitly.
- Recommendation: build the URL from the public origin and the path, `new URL(local.pathname, cf.publicBase)`, or set `local.port = pub.port` explicitly. Pin it with a test for a base with no port.
- Known: new.

### bug-broll-6 - Preview stills are keyed by `videos.id` in one shared folder, while the base rig, fleet ingest and the publish drain each mint ids independently (still open)

- Severity: medium
- Confidence: CONFIRMED (re-read at this HEAD: there is no `FLEET_ID_BASE`, and the drain renames no stills)
- Where: `broll/web/app/ingest_batches.py:149-161` (`ItemFiles.poster/sprite`), `:822-831` (claim mints ids); `broll/web/app/routes_media.py:50-59` and `routes_share.py` (posters and sprites served by id); `broll/indexer/build_archive.py:116-129` and `:590-606` (copies base-rig `posters/<id>.jpg` over a file that differs); `server/broll_drain.py` APPLY (re-inserts "never with their old id").
- What and scenario: as recorded on 2026-09-24. Dashboard-ingested clips and base-rig clips both take ids B+1 and up. build_archive replaces the fleet clips' stills with base-rig ones. After a publish, the drained clips are re-numbered and their stills are not renamed. The search grid and public client links then show another clip's thumbnail and a scrub sprite that does not match the clip, or no preview at all. A client-facing link showing the wrong footage is a launch-visible defect.
- Recommendation: the owner's pending choice from `docs/bug-hunt-2026-09-24/ledger2/owner-decision.md`. Option (A), a disjoint fleet id range kept by the drain plus a one-off rename for legacy clips, is server-side only.
- Known: bug-broll-3 (2026-09-24), DEFERRED for the owner in KNOWN_BUGS, OPEN.

### bug-broll-7 - The public media gate falls back to re-resolving the whole folder on every thumbnail after any renumber, and never heals; one share page costs seconds of dashboard CPU

- Severity: medium
- Confidence: CONFIRMED (probed: 8.4 ms per media request for a 500-clip folder after a renumber)
- Where: `broll/web/app/routes_share.py:93-109` (`_member_id`); `broll/web/app/client_folders.py:795-818` (`member_video_id` checks only the STORED id), `:972-977` (`public_video_ids` = full `resolve_items`), `:855-868` (`_refresh_item_path` heals `rel_path`, never `video_id`).
- What: the fast path matches only while the stored `video_id` is still the current id. Every publish re-numbers dashboard-ingested clips (the drain), so every media request for those items runs `resolve_items` over the whole folder: 2-3 queries per item, plus a write per hash-resolved item. Nothing ever rewrites the stored id, so the folder never returns to the fast path.
- Scenario: a 500-clip folder of ingested clips after one publish. The page fetches 500 posters at about 8.4 ms each, roughly 4 s of CPU per page view. Hover-scrub sprites and preview Range requests add more. This runs on the dashboard's single process, behind an unauthenticated URL published to the internet by Funnel. A few clients, or one scraper looping the poster URL, stall the fleet status page, which CLAUDE.md ranks above every feature.
- Recommendation: when `resolve_items` resolves an item to a different current id, rewrite the stored `video_id` (best effort, like `_refresh_item_path`, respecting `UNIQUE(folder_id, video_id)`). Or cache `public_video_ids` per (folder, search_generation). Consider a per-token request budget on the public door.
- Known: new.

### bug-broll-8 - A shoot name equal to an indexer share is accepted: it re-files that share's collection, and every later publish drain treats the base rig's rows for that share as dashboard-only

- Severity: low
- Confidence: CONFIRMED by reading
- Where: `broll/web/app/ingest_batches.py:838-845` (claim: `INSERT INTO share_roots ... ON CONFLICT(share) DO UPDATE SET collection = excluded.collection`); `broll/web/app/routes_batches.py:66-86,107-109` (no check against existing indexer shares; `collection` from the body is not validated against the two known slugs); `server/broll_drain.py` EXPORT (`ids` includes `videos WHERE share IN (SELECT share FROM ingest_batches)`).
- What: an editor who types an existing indexer share key as the shoot name (for example `ff4` for more FF4 footage) causes three effects:
  1. The share's `collection` is overwritten. A Downloads share flips to "Our Footage" and its subject tree disappears.
  2. From then on the drain exports EVERY base-rig row of that share as "exists only on the NAS". A row the base rig has since deleted (rebase) or renamed (`/moved`) is not in the new file's (share, rel_path) map, so the apply re-inserts it. Deleted clips come back, and moved clips appear twice in search, after every publish.
  3. The base rig's build_archive allocates names against its own DB, which lacks the fleet rows. It replaces the fleet clips' files (into the trash) and leaves their rows pointing at base-rig footage.

  A `collection` value posted to the API that is neither slug is stored as-is.
- Recommendation: refuse a shoot name that matches (ignoring case and normalisation) an existing share with `ingest:` absent from `share_roots.root`, or ask the editor to confirm. Validate `collection` with `config.normalise_collection`. In the drain, select ids by `ingest_items.video_id` only, or by `share_roots.root LIKE 'ingest:%'`, not by share name.
- Known: new.

### bug-broll-9 - The expired or revoked share page shows the curator's LOGIN username to anyone holding the old link

- Severity: low
- Confidence: CONFIRMED by reading
- Where: `broll/web/app/client_folders.py:549-570` (`gone_contact_sentence` uses `created_by`), `broll/web/app/routes_share.py:111-138` (`_gone_page`).
- What: `created_by` is the dashboard login name stamped by the gate, not the display name the account page now offers (`account_api.display_names_for`). The page tells an outside party "Please ask alex at ...". That is half of a dashboard credential, served on a Funnel-published page. It is also the wrong label for a studio that set display names.
- Recommendation: show only `contact`, or a display name passed in by the mount. Never the login name.
- Known: new. It came in with UX-19 (2026-08-28).

### bug-broll-10 - `record_view` on the public folder route is not guarded against a locked ledger, so a client can get a 500

- Severity: low
- Confidence: CONFIRMED by reading
- Where: `broll/web/app/routes_share.py:162-164`, `broll/web/app/client_folders.py:980-984`.
- What: `_refresh_item_path` was made best-effort because "a client viewing a link must never see a 500 because the ledger happened to be locked". `record_view` is the same write on the same request and is unguarded. With the default 5 s sqlite timeout, an editor's write or the v1->v2 backfill (an IMMEDIATE lock, described as "seconds wide") turns the client's page load into a 500. The page then shows the "could not load just now" text.
- Recommendation: wrap `record_view` in `try/except sqlite3.Error` and log at debug level. A lost view count is the right failure.
- Known: new.
