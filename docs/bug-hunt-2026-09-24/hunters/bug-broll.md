# bug-broll - broll/web/app (search API, share routes, client folders, ingest + fleet ingest) and broll/indexer (pipeline, storage backends, build_archive)
Files read (approximate coverage): broll/web/app/{routes_share, client_folders (all), routes_client_folders, main, media, routes_media, fleet_auth, identity, routes_fleet, routes_batches, routes_ingest, ingest_batches (claim/lease/transitions/result/upload/release/retry), routes_api (insert object, detail, search route), schemas (ingest models), semantic + fuzzy (cache keys only), config (paths)}.py; broll/web/static/clientfolders.js (the id each call sends); broll/indexer/broll_index/{storage/http_backend, storage/sqlite_backend (head), pipeline (_process_video, run_pipeline), config (data_root)}.py; broll/indexer/build_archive.py (stills + copy loop); following calls: server/broll_drain.py (apply program), companion broll_ingest.py (cancel/_maybe_finish).
Tests/probes run: three ad-hoc snippets from broll/web/.venv against the real `app.client_folders` module and the real FastAPI app (TestClient, temp BROLL_DATA_ROOT): (1) remove after an index renumber, (2) add after an index renumber, (3) /api/search with FTS-hostile q/mode/path/shoot/category values (no 500s found).

## Findings

### bug-broll-1 - client-folder item matching ORs a STALE stored id with the current name, so remove/note hit the wrong clip and add refuses a new one
- Severity: medium
- Confidence: CONFIRMED
- Where: broll/web/app/client_folders.py:675-698 (remove_item, set_note), :605-627 (add_items), broll/web/app/routes_share.py:210-213 (public note lookup), broll/web/app/routes_client_folders.py:85-88 (the "contains" tick); caller side broll/web/static/clientfolders.js:414,438 (sends `item.video_id`, the STORED id) and :569 (sends `video.id`, the CURRENT id)
- What: every matcher is `video_id = ? OR (share, rel_path) = identity_of(?)`, where one number is used both as a stored-ledger id and as a current-index id. After a publish renumbers `videos.id` those are different id spaces: `_identity_of(index, stored_id)` resolves the stored id to whatever clip now holds that number, and `video_id = current_id` matches whichever item was stored under that number. MEDIA-23's comment says the panel sends the current id; it sends the stored one.
- Failure scenario: folder holds X (stored id 5) and Z (stored id 9). An index publish renumbers: Z is now 5, X is 12. The editor clicks remove on X in the panel (sends 5) -> `_identity_of(5)` = Z -> DELETE matches X by id AND Z by name: both clips vanish from the client's live link. Probe output: `before [{5,'X.mp4'},{9,'Z.mp4'}]` -> `after []`. Same shape writes one note onto two clips (set_note) and shows the wrong clip's caption on the public detail panel (routes_share note query, fetchone of two matches). Inverse: the clip Y that inherited id 5 cannot be added to a folder whose stale item is stored as 5 - probe: `add_items([5])` -> `{'added': [], 'already': [5]}`, public page still shows only X; the card popover also ticks that folder as already holding Y.
- Evidence: scratchpad probes p1.py / p2.py (real module, two in-memory DBs, only mutation = the renumber); read of clientfolders.js call sites.
- Ledger: new (regression of the MEDIA-23 fix's premise; related to broll-4 2026-08-21)
- Suggested fix: match an item by its IDENTITY only: resolve the incoming id to a current (share, rel_path) and match on that (plus hash), and have the panel send the item's row id (client_folder_items.id) for remove/note instead of any video id; in add_items test presence by name/hash, never by stale stored ids.

### bug-broll-2 - HttpBackend posts the LOCAL shadow id to /api/ingest/index and /api/ingest/moved, writing descriptions onto (and renaming) a different clip
- Severity: medium
- Confidence: CONFIRMED
- Where: broll/indexer/broll_index/storage/http_backend.py:101-130 and :184-191 (server side broll/web/app/routes_ingest.py:168-294)
- What: the module docstring says the remote id returned by /ingest/video is "intentionally not assumed to equal the local id; they're independent id spaces", and upsert_video discards it. But write_index_result sends `"video_id": video_id` (the local shadow's id, which is what pipeline reads from videos_by_status) and record_moved does the same. The server looks that number up in the canonical broll.db, where it names some other clip.
- Failure scenario: an indexer run with `db.mode: api` against a web app whose archive already holds 15,000 clips. Its local shadow numbers the first new clip 1. /ingest/index replaces the segments, themes, flags and category_hint of canonical clip 1 (a different, already-indexed clip) with the new clip's description and sets it `indexed`, while the new clip stays `discovered` with no segments; the sorter's record_moved then renames canonical clip 1's rel_path (or 409s on a collision). Silent corruption of search results; nothing errors.
- Evidence: read of http_backend.py (payload built from the local id), pipeline.py _process_video (ids come from storage.videos_by_status -> local shadow), routes_ingest.py (looks up body.video_id directly). tests/test_http_backend.py only asserts URLs, not ids. Dormant on the base rig today (co-located sqlite + publish_db), live the moment any site uses api mode.
- Ledger: new
- Suggested fix: keep a local->remote id map (store the id /ingest/video returns in the shadow row) and send the remote id; or key /ingest/index and /ingest/moved by (share, rel_path) instead of id.

### bug-broll-3 - posters/sprites are keyed by videos.id in ONE shared folder while the base rig and the live dashboard mint ids independently, and the publish drain re-mints ingested clips' ids without moving their stills
- Severity: medium
- Confidence: PLAUSIBLE
- Where: broll/web/app/ingest_batches.py:157-158 (ItemFiles.poster/sprite = `posters|sprites/{video_id}.jpg`), broll/web/app/routes_media.py:50-59 and routes_share.py:250-269 (served by id), broll/indexer/build_archive.py:125-129 + :596-606 (copies base-rig `posters/{id}.jpg` over a differing file at the same name); server/broll_drain.py:236-252 (re-inserts drained videos "never with their old id")
- What: fleet ingest claims mint ids above the live max (B+1...), the base rig's next index mints ITS new clips at B+1... too, and both write `<archive>/posters/<id>.jpg` / `sprites/<id>.jpg`. build_archive replaces a differing file at that name (stashing the other). At publish the drain re-mints every dashboard-ingested clip under a new id, but no step renames its stills.
- Failure scenario: 20 clips ingested from the dashboard (ids 15001-15020), then the base rig indexes 30 new clips (its 15001-15030) and runs build_archive: the fleet clips' posters/sprites are replaced by base-rig ones, so the live search grid and any client share link show another clip's thumbnail and a scrub sprite whose geometry does not match the row. After publish + drain, the fleet clips come back as 15031-15050: their stills are looked up at ids that are missing or belong to nothing, so they show no preview, permanently (the originals sit in the archive trash under the old names).
- Evidence: read of the four sites above; the drain's own comment ("never with their old id: an id is a per-database rowid"); grep finds no rename of posters/sprites anywhere in server/ or broll/. Not reproduced end to end (needs a publish).
- Ledger: new (related to BROLL-1 2026-09-04 drain)
- Suggested fix: key stills by something both databases agree on (hash or share+rel_path digest), or have the drain rename `posters|sprites/<old>.jpg` to the new id and make claim mint ids in a range the base rig never uses.

### bug-broll-4 - a CANCELLED release is accepted from any of the editor's machines, with no leaseholder check, and deletes the live holder's in-flight rows
- Severity: low
- Confidence: PLAUSIBLE
- Where: broll/web/app/routes_fleet.py:255-261 (and ingest_batches.release :1376-1388)
- What: for `state == "cancelled"` the route checks only `batch.editor == editor`, never `X-CCSync-Machine` against `batch.machine` or the lease. release() then marks every non-kept item cancelled and deletes all `ingesting` video rows.
- Failure scenario: machine A slept holding a batch, its lease expired and machine B (same editor) took it over and is uploading. The editor clicks cancel in A's still-stale local companion (broll_ingest.cancel -> release(uid, "cancelled")): the server cancels B's batch and deletes the rows B is mid-upload into; B's next POST 410s and its uploaded files are left in the archive with no row.
- Evidence: read of routes_fleet.release and companion broll_ingest.py:1325-1337 (cancel posts release unconditionally with the uid it remembers).
- Ledger: new
- Suggested fix: when a machine header is present and differs from `batch.machine` while the lease is live, answer 410 other_machine instead of releasing.

## Coverage note
Did not read search.py/semantic.py/fuzzy.py bodies beyond cache keys, local_runtime.py, local_vlm.py, claude_client.py, parallel_*.py, run_queue.py, taxonomy/duplicates/rebase, or the share viewer JS beyond the id each call sends. The broll/web and indexer suites were not run.

## OUT OF TERRITORY
- server/broll_drain.py:236-252: re-mints drained video ids but never renames `posters|sprites/<old id>.jpg` (the server half of bug-broll-3).
- companion/src/ccsync_companion/broll_ingest.py:1337: cancel() releases "cancelled" for a batch this machine may no longer hold (the client half of bug-broll-4).
