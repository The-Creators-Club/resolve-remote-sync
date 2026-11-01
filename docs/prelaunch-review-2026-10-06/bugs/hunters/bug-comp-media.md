# Pre-launch bug hunt - bug-comp-media (2026-10-06)

Lens: companion media/jobs. HEAD 08b40eb plus the uncommitted working tree, read as it stands.

What I covered: `jobs_runner.py` and `jobs_media.py` end to end, `job_paths.py`, `proc_tree.py`, `canon.py`, `broll_fetch.py`, `broll_upload.py`, `sidecar_tools.py`. In `broll_ingest.py` I traced run/claim, manifest matching, crunch, the proxy encode and verify, stills and frames, the upload plan, enqueue/resend, `_pump_uploads`, stage-live, mirror, finish, lease and heartbeat, cancel, prepare/upload_slot/note_picked and staging retention. In `music_ingest.py` I read the overrides (manifest match, crunch, upload plan, enqueue). From `music_clap_sidecar.py` I read the transcode and decode, and from `music_worker.py` connect, import and place. In `proxy_gen.py` I read `_run_ffmpeg`, `_verify`, `_publish`, `_still_needed` and `sweep_stale_partials`. I read the `ffmpeg_tools.py` resolution and encoder detection, plus the headers and outlines of `broll_standins.py`, `bpg.py`, `broll_vlm_sidecar.py` and `proxy_history.py`.

I checked against the 2026-09-24 hunt (bug-comp-media-1..8, bug-comp-broll-1..6) and KNOWN_BUGS. Nothing below repeats one of those.

Probe: `UploadQueue` re-enqueue after done, in the scratchpad, using the runner seam. Output: `uploaded() while re-upload in flight still lists: ['A/clip.mov']`.

### bug-comp-media-1 - Quitting the tray during a whisper job often leaves the whisper worker running on the GPU

- Severity: medium
- Confidence: CONFIRMED (code read; it is a timing race)
- Where: companion/src/ccsync_companion/jobs_runner.py:962-967 (`stop` joins for 5 s), :1314-1347 (`_run_child` loop); app.py:11518-11522
- What: `JobRunner.stop()` sets `_stop` and joins the loop thread for 5 s. The whisper loop notices `_stop` only after each `proc.wait(timeout=5.0)` slice. When a heartbeat is due it makes that HTTP call first, which can take up to 20 s, and only then checks `_stop`. So the time from stop to `_terminate()` is anywhere from 0 to about 25 s, and the join gives up after 5. The child runs in its own process group (`proc_tree.spawn_kwargs`), so it does not die with the companion on Windows or on POSIX.
- Scenario: An editor quits the tray (or a self-upgrade restarts it) halfway through a 20-minute whisper job. The join times out, teardown continues and the process exits. `pipeline.py` and the worker it spawned keep going: they hold VRAM and write transcripts into the vault. The restarted companion knows nothing about them, reports the machine idle, and can claim the next whisper job onto the same card. The first job's lease expires after 300 s and it is handed to another machine, so two writers end up on one episode's sidecars. This is exactly the harm comp-music-ytdl-jobs-1 fixed for cancel and halt, reached through shutdown instead.
- Recommendation: Make `stop()` reach the child. Either keep the live Popen on the runner and have `stop()` call `proc_tree.kill_tree` on it, or have `stop()` set the wake and give the loop a stop-aware wait (an Event wait of 0.5 s instead of `proc.wait(5)`). Check `_stop` before the heartbeat. Join for at least the kill_tree budget.
- Known: no (comp-music-ytdl-jobs-1 covered cancel and halt only).

### bug-comp-media-2 - A 409 from /uploaded is re-posted before the re-upload has started, so the retry budget is gone in seconds and the item fails while its files are still going up

- Severity: medium
- Confidence: CONFIRMED (probe of UploadQueue plus the `_pump_uploads` trace)
- Where: companion/src/ccsync_companion/broll_ingest.py:3083-3084, 3134-3135, 3150-3167; broll_upload.py:294-309 (`enqueue` dedupes only against active and queued jobs), :409-413 (`uploaded()` returns the whole `_done` ledger)
- What: On a 409 (the server could not stat some files), `_pump_uploads` calls `_enqueue_uploads`, which queues the rels again. The old DONE entries for those rels stay in `queue._done`, and `uploaded()` keeps listing them. The next pump therefore computes `missing = []` straight away and posts `/uploaded` again before the re-upload has done anything. `_drain` calls `_pump_uploads` after every crunched item as well as on each 15 s tick, so `MAX_UPLOAD_ATTEMPTS` (3) can be spent in seconds.
- Scenario: The server cannot see a clip's original after the first upload; the file was trashed, or a mount was briefly stale. The pump re-queues a 40 GB re-upload. Over the next one or two pumps the same body is posted, gets 409 each time, and `_fail_item` ends the clip while rclone is still pushing the original. The original then lands on the NAS with no live row to own it, which is the orphan comp-broll-music-3 set out to prevent. The clip shows as failed even though its retry was going to succeed. Music items share this pump.
- Recommendation: When re-declaring after a 409, drop the done entries for those rels (a `forget_done(rels)` next to `retry()`), or record per item which upload generation landed. Only re-post once the re-queued jobs have finished. Separately, re-send only the rels the server named in `detail.missing`, not the whole plan.
- Known: no

### bug-comp-media-3 - Music: two picked `.ogg` files with the same name transcode to one shared `out/<stem>.mp3`, so one library track can be uploaded with the other's audio

- Severity: medium
- Confidence: CONFIRMED (code read end to end)
- Where: companion/src/ccsync_companion/music_clap_sidecar.py:777 (`dest = dest_dir / (src.stem + ".mp3")`); broll_ingest.py:2455-2463 (`_out_dir` is `<staging>/out` for the whole batch), :1597-1607 (picked items keep their original path and stem); music_ingest.py:342-366, 610-670
- What: Uploaded tracks are staged as `<local_id>.ogg`, so their stems are unique. Picked tracks (`source: "path"`, which the music page offers through `miMakeItem(..., 'path', f.path)`) keep their real names. Every `.ogg` is transcoded into the same batch-wide `out` directory and named only by its stem. The upload queue is asynchronous, so the next item's transcode can run while the previous item's mp3 is still queued or uploading.
- Scenario: An editor picks a folder holding `Disc 1/Theme.ogg` and `Disc 2/Theme.ogg`, or two albums that both have `Intro.ogg`. Track 1 is transcoded to `out/Theme.mp3`, embedded, given its `dest_name` and queued for upload. Track 2's transcode then writes over `out/Theme.mp3` with `ffmpeg -y`. Depending on timing, track 1's upload either sends track 2's audio or reads a file being rewritten. The lsjson size check and the server's stat both pass. The library row for track 1 now plays track 2, while its embedding, waveform and hash are track 1's. Nothing notices; search returns the wrong audio. Any later re-send of track 1 (resend or 409) uploads track 2's bytes as well.
- Recommendation: Name the transcode output by the item's uid (or local_id), as b-roll names its outputs by `video_id`, for example `out/<item uid>.mp3`. Or give each item its own subdirectory.
- Known: no (bug-comp-broll-1's music half fixed the manifest matching, not the output naming)

### bug-comp-media-4 - The peaks recipe buffers the whole decode in the tray process and then makes two int32 copies of it

- Severity: low
- Confidence: CONFIRMED (arithmetic from the code)
- Where: companion/src/ccsync_companion/jobs_media.py:636-718 (`_read_pcm` collects every chunk and then `b"".join`s them), :335-351 (`peaks_bytes`: `astype("int32")` plus `np.abs`)
- What: The PCM is 16 kB per second of source. A 3-hour Zoom interview is 173 MB of chunks, joined into a second 173 MB buffer, then turned into a 345 MB int32 array and another 345 MB from abs. That is roughly 0.9-1 GB transient inside the companion that also runs sync, and about 2 GB for a 6-hour recording. A MemoryError comes back as a retryable failure, so the job tours the fleet.
- Scenario: The fleet takes a peaks job for a long multicam audio file on an 8 GB laptop. The tray's memory spikes; in the worst case the process is killed or the job fails on every machine it reaches before it pins.
- Recommendation: Bin while streaming. Feed each block from the drain thread through a running per-bin max, carrying the remainder across blocks, so memory stays O(bins). Or widen to int32 one block at a time.
- Known: no

## Not reported (checked and found sound, or already recorded)

- `job_paths.resolve` / `safe_stem`: absolute paths, climbing, NUL characters and Windows-only characters are all handled as bug-comp-media-3/-8 left them.
- The sidecar ffmpeg/deno installs are sha256-pinned and the zip member is read by name only; the broll-vlm runtime and weights are sha-pinned with an https host allow-list.
- `broll_fetch` cap, terminal-state reaping and spawn-failure cleanup are correct.
- Stand-ins are never placed on a wired rig (`broll_server._is_wired`); that is outside this territory, but it was the obvious data-loss question.
- Concurrent frame extraction (`_make_frames` at width 2) publishes and then clears children over one another, so `_kill_child` can miss a one-frame ffmpeg at stop. The orphan lives for seconds; not worth a finding.
