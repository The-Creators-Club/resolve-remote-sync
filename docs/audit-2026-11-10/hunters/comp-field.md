# comp-field - companion field backup, card copy, TeraCopy, ledger scan/outbox/mirror, card and volume detection
Files read (approximate coverage): companion/src/ccsync_companion/ field_mode.py (all), field_copy.py (all), field_service.py (all), field_server.py (all), card_copy.py (all), teracopy.py (all), ledger_scan.py (all), ledger_outbox.py (all), ledger_mirror.py (all), sorter_cards.py (all), sorter_volumes.py (all), wav_header.py (all), assets/field/field.js (poll loop only); dashboard/src/ccsync_dashboard/sorter.py (ledger agent routes, 380-610); footage-sorter footage_sorter/ledger.py (record_copies, _record_one, mirror, SQL_MIRROR), ledger_rules.py (ext lists). Not read: footage-sorter ledger_sources.py, cardtracker.py, ingest.py. docs/FIELD_BACKUP.md read in full.
Probes run (all files under scratchpad\comp-field\, companion venv):
- probe_verdict.py: one card verdict through LedgerView + LocalCopies + LedgerMirror + FieldStore, card of 500 / 2,000 files copied to two drives; with and without the mirror already holding those copies. Plus cProfile.
- probe_outbox.py: ledger_outbox append / pending / flush at 10k, 40k, 80k queued copies (send stubbed to 200).
- probe_listcard.py: sorter_cards.classify / list_card on a synthetic 20k-file removable "field drive", and one minute of SorterCards ticks while its free space moves.
- probe_unreadable.py: list_card with one card folder unreadable, then field_mode.card_verdict.
- is_judged over common camera original extensions (inline).
- `tasklist /FI "IMAGENAME eq TeraCopy.exe" /NH` timed (5 runs), TeraCopy History db count.

## Findings

### comp-field-1 - A card folder that cannot be read vanishes from the listing, and the card is then "Safe to format"
- Category: bug
- Severity: high
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/sorter_cards.py:404-424 (list_card), field_service.py:329, field_mode.py:307-378 (card_verdict)
- What: `list_card` swallows an OSError from `os.scandir` of a folder (debug log, `continue`) and from an entry's stat, so the files in an unreadable folder are simply absent from `files`. The field page judges the card on that list only, so a card whose second folder will not read (flaky reader, FAT damage, a folder the card is still settling) is judged on the folders that did read. Nothing in the result says the listing was partial. ledger_scan.py solved exactly this for drives (the `unreadable` list and `complete:false`); the card listing never got it.
- Cost / failure scenario: DJI card, DCIM/100MEDIA reads, DCIM/101MEDIA throws EIO. The three 100MEDIA files are at home -> page says "Safe to format: all 3 files are at home." The 101MEDIA footage has no copy anywhere and is formatted away. The copy run copies the same short list, so every lane also reports green.
- Evidence: probe_unreadable.py: os.scandir made to raise for 101MEDIA -> listed 3 of 6 files -> `verdict: safe safeToFormat=True | Safe to format: all 3 files are at home.`
- Ledger: new
- Suggested change: have list_card return `unreadable` (folders and entries it could not read) like LedgerScan; FieldService keeps it on the card and card_verdict refuses `safeToFormat` (state "incomplete", headline naming the folder) while it is non-empty, and the copy run reports it. The sorter's card report can carry it too. Must not make a readable card unsafe.
- Effort / risk: S effort; low risk

### comp-field-2 - "Safe to format" ignores originals whose extension is not on an allow-list (Nikon N-RAW .NEV and others)
- Category: bug
- Severity: high
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/field_mode.py:93-112 (ORIGINAL_EXTS, is_judged), 332-334, 363-365
- What: the verdict only waits for files whose extension is in MASTER_EXTS | AUDIO_EXTS | sorter MEDIA_EXTS | a short extra set; anything else is silently not judged (fail-open). Missing originals include .NEV (Nikon Z8/Z9 N-RAW video), .ARX (ARRIRAW HDE), .cine (Phantom), .CRW, .ERF, .RWL, .M2T, .MOD, .VOB. FieldCopier._record also drops them (`is_judged or is_recordable`), so they are never even recorded.
- Cost / failure scenario: a Nikon card with N-RAW video plus JPG/NEF stills: once the stills have two copies the page says "Safe to format", whatever happened to the .NEV clips. A card of N-RAW alone reads "Nothing on this card needs backing up (no footage, audio or photos on it)", which a person reads as "format it".
- Evidence: inline probe: is_judged('DCIM/100NZ9_1/DSC_0001.NEV') False, '.ARX' False, '.cine' False, '.CRW' False, '.ERF' False, '.M2T' False, '.MOD' False, '.VOB' False, '.RWL' False; card_verdict([[...NEV, 5 GB]]) -> state "empty", headline "Nothing on this card needs backing up".
- Ledger: new
- Suggested change: invert the rule: judge every file except a deny-list (sidecars XML/THM/LRV/BIM/PPN/SMI/SRT, thumbnails, proxies, system and temp files, `._` twins). An unknown file then makes the card unsafe, which is the safe direction; add .nev/.arx/.cine/.crw/.erf/.rwl/.m2t/.mod/.vob to the ledger's own rules separately so they can be counted.
- Effort / risk: S effort; low risk (more cards read "unsafe" until their unknown files are copied, which is the intent)

### comp-field-3 - The verdict rewrites field-local-copies.jsonl (with fsync) once per FILE after a sync: 28 s for a 2,000-file card
- Category: perf
- Severity: high
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/field_mode.py:737-751 (LedgerView._raw calls local.forget per lookup), 684-696 (forget rewrites the whole file + fsync), 656-657 (add filters the whole list per copy)
- What: every `copies(name,size,mtime)` lookup that finds a local row the mirror now also holds calls `LocalCopies.forget([that row])`, which rewrites the entire jsonl atomically with fsync. A verdict does one lookup per file, so the first verdict after a successful sync performs one full-file rewrite per covered file: O(files x rows) bytes and one fsync per file. It runs inside the page's GET /field/api/state request thread, and the verdict cache is only filled at the end, so each 4 s poll during it starts another verdict (ThreadingHTTPServer), which pile up behind the LocalCopies lock. `add()` is quadratic the same way (`rows[:] = [...]` per copy).
- Cost / failure scenario: runs once per card per sync that delivered its copies (after every run with the dashboard reachable, and the 5-minute auto-sync). 500 files -> 10.6 s, 2,000 files -> 28.0 s of page stall and fsync storm; at the 60,000-row cap each rewrite is ~18 MB, so a 2,000-file card would write ~36 GB (estimated, quadratic). add() of 4,000 rows into 4,000 took 0.3-0.4 s; into a 60k file per 2,000-file lane, an estimated 10+ s.
- Evidence: probe_verdict.py: `F=500 cover=True: verdict 10.60s`, `F=2000 cover=True: verdict 28.01s`, local rows 4000 -> 0 (one rewrite per file); without the mirror holding them the same verdict is 4.4 s (finding 4).
- Ledger: new
- Suggested change: collect the covered rows during the verdict and call forget() once at the end (or on the sync thread right after a pull, comparing the pulled rows with the local file in one pass); keep LocalCopies indexed by (name_lc, size) and by (volume_id, path) so add/matching/forget are O(1) per row.
- Effort / risk: S effort; low risk

### comp-field-4 - Every verdict reopens SQLite per file, re-reads field-state.json six times per file, and scans all local copies per file: 4.4 s per 2,000-file card, every 20 s while the page is open
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/ledger_mirror.py:172-181, 337-356 (where opens a connection, sets WAL, runs the whole CREATE schema, per call); field_mode.py:535-551 + 582-584 (FieldStore.get/kinds read and parse the file on every call), 256-271 (KindResolver.kind calls overrides() first), 672-682 (LocalCopies.matching is a linear scan); field_service.py:470-489 (stamp also reads kinds), 486/535 (mirror.status COUNT(*) twice per poll), 539 (outbox pending, see finding 6), 721-735 (_present stats every NAS row over SMB when the pool is mounted)
- What: per judged file the verdict makes 1 SQLite connect + PRAGMA + executescript(SCHEMA), ~6 FieldStore file reads + JSON parses (kind_of per copy row, again in the uncounted loop, and in the on_nas match), and a full scan of LocalCopies. At home with the pool mounted it also stats each NAS copy over SMB. The plan for each lane repeats the per-file lookup (`_already_on_volume`, `verified_record`).
- Cost / failure scenario: page polls every 4 s idle (1 s while copying); verdict TTL 20 s, also invalidated by every lane end, sync and kind change. 2,000-file card, 4,000 local rows: 4.4 s (profile: 1.8 s SQLite where incl. 1.25 s connect, 1.1 s LocalCopies scan, 0.67 s for 12,000 field-state.json reads). LocalCopies scan is linear: at 20k rows estimated ~6 s more. Two cards in readers double it. With the NAS mounted add an estimated 2-6 s of SMB stats per verdict.
- Evidence: probe_verdict.py `F=2000 cover=False: verdict 4.42s ... field-state.json reads=12000 sqlite connects=2000`; cProfile output in the probe run.
- Ledger: new
- Suggested change: one mirror connection per verdict (or one `WHERE (name_lc,size) IN (json_each)` query, the shape the sorter's SQL_MATCH already uses); run the schema once per process; snapshot kinds/guesses/info once per verdict; index LocalCopies; cache the pool `_present` answer per verdict. Must keep "a copy on an attached drive is stat'ed before it counts".
- Effort / risk: M effort; low risk

### comp-field-5 - Cards in fixed readers (CFexpress B, the 2026-11-10 fix) are reported to the sorter but cannot be copied by the companion or the field page
- Category: bug
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/card_copy.py:466 (_find_card: `self._volumes("removable", ...)`), 587 (_card_gone), field_service.py:314 (`not v.get("removable")` -> not a card), field_copy.py:454 (_card_present: "removable")
- What: commit 7ac37ed made sorter_cards list `local` volumes so a CFexpress B card on a FIXED disk (H: on creator-1, bmcc) reaches the sorter. card_copy, which runs the resulting card-ingest job, still looks for the serial among removable volumes only, so the job fails non-retryably with "card ... is not in a card reader on this computer, so nothing was copied". The field page drops fixed volumes from its card list and instead offers the CFexpress card as a "Copy to" destination (kind guessed "unknown").
- Cost / failure scenario: every ingest of a CFexpress B / Blackmagic SSD card through the sorter fails at once; in the field the card cannot be backed up from the page at all, and a person can tick it as a destination and write another card's footage onto a camera card.
- Evidence: code read; `git show --stat 7ac37ed` touched sorter_cards only; card_copy/field_service last changed in b229ee2/bfb15de.
- Ledger: related to the 2026-11-10 fixed-reader change (7ac37ed), new
- Suggested change: one predicate "is this volume a card" (sorter_cards.describe's rule: removable, or fixed with a camera layout) used by card_copy._find_card/_card_gone ("local" scope + serial), field_service._cards_from, field_copy._card_present; exclude such volumes from destinations. Keep the system disk excluded.
- Effort / risk: S effort; low risk

### comp-field-6 - The ledger outbox is quadratic to flush and is fully re-parsed on every field-page poll
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/ledger_outbox.py:262-280 (flush re-reads the whole file per 500-copy batch), 319-324 (_drop re-reads, json.dumps(sort_keys) every line, rewrites + fsync per batch), 229-231 (pending parses the whole file), 185-187 (append parses it to dedupe); field_service.py:539 (pending on every GET /field/api/state)
- What: each 500-row batch costs two full parses, a JSON re-serialisation of every line and a full-file rewrite with fsync, so a backlog of N copies costs O(N^2/500). `pending()` parses the whole file and is called by the page every 1-4 s and by OutboxFlusher every 60 s (twice per failed tick while offline; no backoff on transport errors).
- Cost / failure scenario: a week in the field at 3 drives x 2,000 files/day ~ 42k queued. Measured flush CPU+disk (network excluded): 10k 1.0 s, 40k 20.9 s, 80k 73.6 s; the 200k cap extrapolates to ~7-8 min and ~400 rewrites of up to ~57 MB (~11 GB written). pending() at 80k = 0.26 s per page poll, i.e. 26 % of a core while a copy runs.
- Evidence: probe_outbox.py output above.
- Ledger: new
- Suggested change: keep a sent-offset (or move the outbox to a small SQLite table): send batches from one read, drop all delivered lines in ONE rewrite at the end (or truncate by offset), cache the count by file size+mtime for pending(). Keep "nothing is deleted until a 200" and the rejected file.
- Effort / risk: S effort; low risk

### comp-field-7 - The mirror is keyed on the volumes plugged in right now: every card in or out re-pulls everything (NAS pool included) and deletes the away drives' copies
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/field_service.py:681-683 (ids = every attached volume incl. cards and the system disk, + the pool), ledger_mirror.py:244-268 (different set -> cursor "" and _forget_other_volumes), field_service.py:301-303 (_root_by_vid never cleared), field_mode.py:718-735 (_present)
- What: the pull's volume set is the current attachment set, so inserting or removing ANY volume (each new card) resets the cursor to zero and re-downloads every row of every volume including `nas:...`, and deletes all mirror rows of volumes not attached (a field drive that went into the bag). LocalCopies rows were already forgotten once the mirror had them (finding 3), so those copies stop counting. Separately `_root_by_vid` keeps an unplugged drive's old letter, so `_present` stats that letter and drops the away copy (or checks whatever drive took the letter). Both contradict field_mode's own rule "a copy on a drive that is away is believed".
- Cost / failure scenario: sync runs after every run and every 5 min with the page open. Pool rows in the ledger are masters/audio for ~100 projects (estimated 10^5-10^6 rows): each card insert = 20-200 pages of 5,000 rows over Tailscale plus upserts that also store the raw JSON (estimated tens to hundreds of MB, minutes). Functionally: card copied to CIB_D1 and CIB_D2, D1 unplugged, next card inserted, sync -> the first card drops to "one copy" and gets copied again (fail-safe, but the field workflow the page was built for).
- Evidence: code read (lines above); `same = meta volumes == want` else `cursor = ""` and `_forget_other_volumes(ids)`.
- Ledger: new
- Suggested change: pull for a persistent, growing set (volumes ever recorded here + ledger-known kinds + pool), one cursor per volume; never forget on unplug; drop `_root_by_vid` entries for volumes not in the latest scan so away means away. Keep "only live rows".
- Effort / risk: M effort; low risk

### comp-field-8 - The physical-disk key is cached by drive LETTER for the life of the process, so two partitions of one disk can count as two copies
- Category: bug
- Severity: medium
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/field_service.py:353-356 (_lane_key caches `physical_key(root)` by root path forever), 303 (_phys_by_vid from it), 402/420 (Destination.lane), 632 (`phys` persisted into LocalCopies rows), field_mode.py:297 (row phys wins)
- What: IOCTL_STORAGE_GET_DEVICE_NUMBER is asked once per letter per process lifetime. Letters and device numbers are reassigned as drives come and go, and the companion runs for weeks, so a letter's cached "disk:N" can belong to a disk that left. Two partitions of a newly plugged disk can then get different keys (one stale, one fresh) and count as two copies; the stale key is also written into the LocalCopies row and survives restarts for 30 days. Lanes are grouped by the same key, so two partitions of one disk may also be written in parallel.
- Cost / failure scenario: E: was disk:3 last week; today a two-partition SSD (disk:2) mounts as E: and F:, both set to "ours" -> E: keeps disk:3, F: gets disk:2 -> each file on both partitions = two counted copies -> "Safe to format" with one physical disk. Needs letter reuse with a different disk number, routine with rotating field drives.
- Evidence: code read; the docstring of file_verdict promises "two partitions of one disk ... never make two".
- Ledger: new (regression of the 2026-11-10 review's "copies are counted by physical disk")
- Suggested change: key the cache by volume serial + letter and drop it on each scan for volumes no longer present (or simply re-ask: the IOCTL is a single cheap call per volume per scan).
- Effort / risk: S effort; low risk

### comp-field-9 - A removable volume holding footage is fully re-listed (and re-posted) every 10 s whenever its free space moves
- Category: perf
- Severity: medium
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/sorter_cards.py:574-583 (sig includes `free`), 456 (describe -> list_card), 609-614 (digest change -> POST); field_service.py:320-322 (same sig, 30 s TTL)
- What: the "nothing moved" test includes free bytes, so any volume being written to is re-classified and, if it holds media within 4 levels, re-walked in full each tick, reading 4 KB of every .xml and every .wav header, and the whole listing is POSTed to /sorter/agent/cards because the file count/bytes changed. A removable field drive that holds a recorder or BMCC backup (`FieldBackup/<day card>/x.WAV` is media at depth 2) is a `generic` card by this rule, so it is re-listed every 10 s while the field page copies onto it, and every 300 s at idle (RELIST) with a 300 s resend.
- Cost / failure scenario: 20k-file drive: 0.8-1.2 s per list on a local NVMe (USB HDD slower, estimated several seconds and competing with the copy for the same disk), 6 re-lists per minute, 1.8 MB uncompressed report body each. The field page does the same at its 4 s poll (30 s TTL defeated by the moving sig).
- Evidence: probe_listcard.py: `list_card 0.80s, 20005 files, 2000 xml heads read; one report body 1.8 MB`, `one minute of SorterCards ticks while the drive is written to: 6 full re-lists, 5.1s`.
- Ledger: new
- Suggested change: leave `free` out of the relist signature (use root + capacity + the root folder's mtime, or a cheap top-level listing hash); skip volumes that are a running copy's destination (register them like ingest_busy); consider gzip for the cards POST as the scan chunks already do.
- Effort / risk: S effort; low risk

### comp-field-10 - The Python copier's "read back in full" verify reads the OS page cache, not the media
- Category: bug
- Severity: medium
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/card_copy.py:279-315 (copy_file writes, fsyncs, then verify_whole), 194-218 (verify_whole uses a plain buffered open)
- What: the partial is read back immediately after it is written; on Windows and macOS those pages are still in the file cache, so the "verify" hashes memory that was just written and cannot see a bad write to the card/drive (USB bridge corruption, a failing drive). fsync guarantees the write was issued, not that what reads back from the medium matches. The receipt still says `verified: true` and the field page records `full`.
- Cost / failure scenario: every copy by the Python copier (every Mac, every PC without TeraCopy, `card_copier = "python"`): a 4 GB clip on a 16 GB laptop is read back almost entirely from RAM. A silently corrupting USB enclosure produces copies recorded as fully verified, which count toward "safe to format".
- Evidence: code read; standard OS caching behaviour (no FILE_FLAG_NO_BUFFERING / F_NOCACHE / posix_fadvise DONTNEED anywhere in the module).
- Ledger: new
- Suggested change: verify with an uncached read: Windows CreateFile with FILE_FLAG_NO_BUFFERING (sector-aligned buffer), macOS fcntl F_NOCACHE, Linux posix_fadvise(DONTNEED) after fsync. Keep the single hash-while-copying pass.
- Effort / risk: M effort; medium risk (aligned I/O on Windows)

### comp-field-11 - TeraCopy's wait spawns `tasklist` every 5 s per lane for the whole copy
- Category: idle
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/teracopy.py:686 (wait_for_job calls `_is_running()` on every poll), 369-377 (default_is_running = subprocess tasklist)
- What: the process check is only needed when the history record is missing or stalled, but it runs on every 5 s poll even while the database says the job is running, in every lane.
- Cost / failure scenario: measured 186 ms wall per tasklist here. 3 lanes x 1 h copy = 2,160 process spawns (~6.7 min of process time) beside a copy on a laptop.
- Evidence: PowerShell Measure-Command over 5 runs: 186 ms each.
- Ledger: new
- Suggested change: call `_is_running()` only when state is missing/locked or `copied` without a verify seen; or enumerate processes via ctypes (CreateToolhelp32Snapshot) with no spawn.
- Effort / risk: S effort; low risk

### comp-field-12 - Every lane reads the whole card on its own; three destinations read the card three times at once
- Category: perf
- Severity: low
- Confidence: PLAUSIBLE
- Where: companion/src/ccsync_companion/field_copy.py:407-421 (one CardJob per lane group, all started together), card_copy.py:279-315
- What: the run starts one thread per physical drive, each with its own CardJob reading every source file; full compares of unverified "already there" files read the card again per lane. On the Python copier path a single reader could hash once and fan the same buffer out to N writers.
- Cost / failure scenario: 256 GB card, 3 drives: 768 GB read from the card instead of 256 GB, with three interleaved sequential streams on one SD/CFexpress reader (estimated 1.5-3x slower when the reader, not the drives, is the bottleneck). TeraCopy path is single-instance and cannot share a read, so this applies to Mac / no-TeraCopy machines.
- Evidence: code read; estimated.
- Ledger: new
- Suggested change: for the Python copier, a fan-out copy (one read + one hash, N `.partial` writers, each then verified) for lanes that start together; keep per-lane failure isolation by dropping a failed writer, not the read.
- Effort / risk: M effort; medium risk

### comp-field-13 - Proxy-by-name rule has drifted from the ledger's
- Category: streamline
- Severity: low
- Confidence: CONFIRMED
- Where: companion/src/ccsync_companion/field_mode.py:58 (`S03\.mp4$`) vs footage-sorter footage_sorter/ledger_rules.py:41 (`\dS\d{2}\.mp4$`); field_mode.py:63 (`_RULES = ledger_scan.Rules()`, the built-in copy, never the server's rules_doc)
- What: the field verdict decides "tracked" from the companion's built-in copy of the rules and a different proxy-name regex; the ledger calls C0001S01.MP4 a proxy, the field page a master, and a server-side rules change never reaches the field page.
- Cost / failure scenario: a card whose proxies the ledger does not track as masters is judged on them by the page (safe direction, extra "short" files); any future ext added server-side is missed by the page.
- Evidence: code read of both regexes.
- Ledger: new
- Suggested change: cache the server's `rules_doc()` with the mirror pull and build field_mode's Rules from it (fallback to the built-in copy), with one shared proxy regex.
- Effort / risk: S effort; low risk

## What is already good
- ledger_scan.walk: scandir with the cached DirEntry stat (no extra syscall per file on Windows), links not followed, bounded memory (one 5,000-row chunk), gzip chunks retried under the same seq, unreadable folders exempted rather than marked gone. Leave it alone; it is the model finding 1 should copy.
- Volume detection is ctypes (GetLogicalDrives / GetVolumeInformationW with SEM_FAILCRITICALERRORS), not a PowerShell/WMI spawn per poll; sorter_volumes debounces free-space posts (1 GiB or 1 %, 60 s).
- card_copy's Python copier hashes while copying in one pass with an 8 MiB reused buffer, writes `.partial`, publishes without clobbering, and never overwrites; resume builds a new partial instead of appending in place.
- teracopy.launch serialises stubs and confirms registration by file list + destination; history matching excludes pre-existing databases.

## Coverage note
Did not read footage-sorter ledger_sources.py, cardtracker.py, ingest.py, or the dashboard's sorter ingest routes beyond the ledger agent ones; did not check the server-side SQL_MIRROR index or the mirror endpoint's cost. Did not exercise real TeraCopy, real card readers or `list_volumes` on this machine (brief: no real drives). field.js reviewed only for its poll cadence.

## OUT OF TERRITORY
- footage-sorter footage_sorter/ledger.py:1290-1320: mirror() runs one LIMIT lim+1 query per volume and merges in Python; with 200 ids that is up to 1M rows fetched to return 5,000 - worth an EXPLAIN against the real copies indexes.
- companion wav_header.py / footage_sorter wav.py: RF64/BW64 recordings (>4 GB WAVs from Sound Devices/Zoom) return None, so long takes get no duration on either side.
