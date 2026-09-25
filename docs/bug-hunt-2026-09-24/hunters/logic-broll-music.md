# logic-broll-music - b-roll and music journeys: client folders, stand-ins, ingest ledgers, music send (wave 2, logic + usability)
Files read (approximate coverage): broll/web/app/client_folders.py (all), routes_client_folders.py (all), routes_share.py (80-269), ingest_batches.py (40-1000), edit_weight.py; broll/web/static/clientfolders.js (grep of id/order/expiry/view paths); broll/indexer/broll_index/ffmpeg_tools.py (preview scale); companion broll_standins.py (290-840), broll_server.py (870-900, 1040-1320); music/web/musicweb/ingest_batches.py (1-128, 226-370, 556-780, 930-1270); companion music_server.py (398-531); KNOWN_BUGS CR-288B/2 and docs/bug-hunt-2026-09-18b ledger highs-companion-media.
Tests/probes run: one ad-hoc probe of client_folders.add_items/remove_item/resolve_items against a temp client_shares.db and an in-memory index, run from broll/web/.venv (script in the session scratchpad, nothing written in the repo).

## Findings

### logic-broll-music-1 - After an index rebuild, removing one clip from a client folder can delete a second clip, and adding a clip can be refused as "already in the folder"
- Severity: medium
- Confidence: CONFIRMED
- Where: broll/web/app/client_folders.py:675 (remove_item), :689 (set_note), :619-627 (add_items); broll/web/app/routes_client_folders.py:82-88 (list_folders contains tick); broll/web/app/routes_share.py:210-213 (public note lookup)
- What: every "is this item that clip" test matches `video_id = X OR (share, rel_path) = identity-of-X-in-the-CURRENT-index`. After publish_db.py renumbers `videos.id`, a stored item id can be the current id of a different clip. The panel sends the STORED id (clientfolders.js:414/438), `_identity_of` turns it into the path of whatever clip holds that number now, and the OR then matches a second, unrelated item. The same collision makes `add_items` answer `already` for a new clip whose current id equals another item's stale stored id, makes the search card show a false "in this folder" tick, and can hand the public detail panel another clip's caption.
- Failure scenario: a folder holds clip A (stored id 5) and clip B (stored id 9). A rebuild gives A id 7, B id 5 and a new clip C id 9. The editor adds C: `{'added': [], 'already': [9]}`, so C never reaches the client and no error appears. The editor then removes A in the panel (DELETE .../items/5): both A and B are deleted, and the client's live link loses B.
- Evidence: the probe prints `add c: {'added': [], 'already': [9]}`, `remove a -> True`, `panel after: []` (the folder had two clips and one was removed).
- Ledger: related to broll-4 (2026-08-21) and MEDIA-23 (2026-08-28); new. Those fixes added the OR, and the OR causes this.
- Suggested fix: when the index connection is available, match an item by its own identity first: resolve the id the panel sends to the stored ROW (`client_folder_items.id`, or `(folder_id, video_id)` only when the stored name still agrees with the index), and never OR a stale id with some other clip's name. In add_items, test "present" by (share, rel_path)/hash only and not by the bare stored video_id.

### logic-broll-music-2 - settle_intents calls a stand-in "the real original" for any heavy original that is 1080 lines or smaller
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/broll_standins.py:663-673 (`_what_landed`); broll/indexer/broll_index/ffmpeg_tools.py:568 (preview scale `min(1080, ih)`); broll/web/app/edit_weight.py (a heavy verdict does not need more than 1080 lines)
- What: an intent row is settled by comparing the probed width x height with the ORIGINAL's geometry, on the stated premise that "a stand-in is the preview's bytes and cannot match it". The preview is scaled to `min(1080, ih)` and never upscaled, so for a 1920x1080 original the preview is also 1920x1080. A 1080p original is heavy, and so gets a stand-in, whenever its bitrate is over 12 Mbps or its codec is not h264/hevc/prores (for example DNxHD, MJPEG, or 1080p H.264 at 50 Mbps). For those clips the geometries match, and `_what_landed` returns False ("the real original arrived").
- Failure scenario: an editor sends a 1080p 50 Mbps camera clip to Resolve and closes the tab while the page still says "syncing 40%". The fetch lands unobserved. On the next 120 s cycle settle_intents probes 1920x1080 = 1920x1080, logs "the real original arrived", and deletes the row. The preview's 1080p H.264 bytes now sit under the original's name with no ledger entry. The next insert imports them as the original, the relink pass never treats them as a stand-in, and a render on that machine renders the preview. This is the proxy-tiers-1 outcome that CR-288B/2 was meant to prevent.
- Evidence: read the scale filter (ffmpeg_tools.py:568, "Never upscale"), the edit-weight rule (height <= 1080 AND bitrate <= 12 Mbps AND a cheap codec), and plan_insert (broll_server.py:1050-1086), which places a stand-in whenever weight is False. The CR-288B/2 write-up and the 18b ledger only discuss the 6064x3424 case.
- Ledger: regression of CR-288B/2 (the settlement is wrong for a class of input it was meant to cover)
- Suggested fix: when the original's geometry equals the geometry the preview would have (height <= 1080), do not decide by geometry. Compare the codec or bitrate, or the frame count against `geometry.frames` (the preview is re-encoded, but `probe_video` reports codec and bitrate), or fall through to the job-state question and leave the row pending.

### logic-broll-music-3 - Cancelling a music batch mid-upload leaves tracks that stay searchable but have no audio and cannot be retried
- Severity: medium
- Confidence: CONFIRMED
- Where: music/web/musicweb/ingest_batches.py:1250-1255 (release on cancel), :930-1000 (write_item_result creates the `tracks` row before any upload), :556-590 (retry_failed moves only `failed`)
- What: a track row, with its embedding, windows and peaks, is written at `result` (item state `indexed`), and the audio is uploaded afterwards. `release(state='cancelled')` marks every item not in (live, duplicate, skipped, cancelled, queued_for_base_rig) as `cancelled`, so `indexed` and `uploading` items become terminal while their `tracks` rows stay. The release docstring says the opposite ("if its audio never landed it is `indexed` rather than `live` - visible in the ledger, fixable by re-uploading"), and retry_failed only moves `failed` items, so nothing brings these tracks back. The module's own guarantee ("A tracks row is only written when there is something real to write") no longer holds.
- Failure scenario: an editor drops 40 tracks, sees them indexing, and presses cancel while the uploads are running (or the lease sweep finalises a cancelled batch). Every track that was indexed but not yet uploaded stays in music search, facets, tag percentiles and the debias axes. Its audio route 404s and "send to Resolve" fails. Its name is held in `tracks`, so dropping the same file again gets `theme (2).mp3`. The panel shows the items as "cancelled", and only a base-rig `--prune` removes the rows.
- Evidence: code reading. `indexed` is written at write_item_result (line ~1012), the cancel UPDATE's exclusion list does not include it, and db.py:340 loads every track with an embedding into the search index without checking whether its file exists.
- Ledger: new (related to MUSIC-ING-2 / music-1 family, not the same defect)
- Suggested fix: on cancel, either keep `indexed`/`uploading` items out of the `cancelled` sweep (leave them `failed` with "audio never uploaded", which retry can reach), or delete the `tracks` row, its windows, peaks and proxy for any item whose audio never landed, and re-score, in the same transaction.

### logic-broll-music-4 - The editor's own "open" check of a client link is counted as the client opening it
- Severity: low
- Confidence: CONFIRMED
- Where: broll/web/app/routes_share.py:171-189 (`record_view` on every api/folder fetch); broll/web/static/clientfolders.js:285 (the panel's "open" link), :196 and :296-298 ("Opened N times, last <date>")
- What: view_count and last_viewed_at are incremented by every load of the public page, and the panel's own "open" button loads that page. The panel presents the counter as the answer to "has the client looked at it yet?", but it also counts the curator checking their own work, including every reload.
- Failure scenario: an editor builds a folder, clicks "open" to check it, and sends the link. The panel then reads "Opened 1 time, last today", and the editor believes the client has seen it when the client has not.
- Evidence: code reading. Both requests hit the same `share_folder` route, and nothing distinguishes a request carrying a dashboard session.
- Ledger: new
- Suggested fix: skip `record_view` when the request carries a valid dashboard session (the mount sits behind the gate, which can stamp the identity), or have the "open" button add a `?preview=1` that the route honours.

## Coverage note
Not reached: broll/web/app/search.py and semantic.py ranking logic, app.js/ingest.js flows beyond the client-folder panel, companion broll_ingest.py (3948 lines) and music_ingest.py, broll_upload/broll_fetch busy/retry loops, the indexer CLI (pipeline, sorter, share_push, rebase), the music drain/rescore, and the b-roll `proxies_live` retry path end to end (read only the server half: retry re-enters a published clip at `pending`, which re-runs the VLM description; the docstring says this is deliberate).

## OUT OF TERRITORY
- none
