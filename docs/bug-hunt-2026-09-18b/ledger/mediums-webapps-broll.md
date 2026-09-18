# CR-302 - the b-roll web app's mediums (2026-09-18b wave) - FIXED in repo 2026-09-18 (broll/web)

### CR-302A (broll-1) - broll-3's NFC fix covers the ORIGINAL but not the editing proxy beside it - FIXED (broll/web/app/routes_api.py)

Today's broll-3 fix made `insert_target_detail`'s TOP-SLOT sibling search
normalisation-insensitive (NFC on both sides of the compare, the entry's own
bytes kept in the answer), and left the editing proxy two lines below built as
`preview.parent / (preview.stem + ".mov")` from the DB's NFC string and
`is_file()`-d. On the container a `.mov` whose name is spelled NFD on the NAS
(CR-90, a Mac's rclone upload) was therefore invisible while the original
beside it was found, which is worse than missing both:
`broll_server.derive_insert_paths` reads a null `edit_proxy_rel` either as
"the original is light enough to edit with" (a null-bitrate row, i.e. every
pre-2026-09-17 row, so the editor downloads the camera master the tier exists
to avoid) or as a stand-in with `upgrade_rel = None`, a ledgered stand-in
nothing will ever upgrade. The fix discovers the editing proxy the same way
the top slot is discovered: one `os.listdir` of the `Proxy/` folder, match
`NFC(splitext(e)[0]) == want` and `splitext(e)[1].lower() == EDIT_PROXY_EXT`,
and `edit_proxy_rel` carries the entry's own bytes because the companion
OPENS that path (CLAUDE.md's CR-90 rule: never normalise a path something
opens). Two things came with the rewrite: broll-4's guard survives as a
normalised comparison against the preview's own name (a `.mov` preview is
still not its own editing proxy, and its spelling on disk need not match the
row's), and proxy-tiers-3's rule extends to the new call - a listing that
RAISED sets `known = False` rather than answering "there is no editing
proxy". Ambiguity (two candidates differing only by normalisation) degrades
to None with a log line, exactly as the top slot does.

The wire is unchanged: the same keys with the same meanings, so no deploy
ordering is implied. Tests:
`broll/web/tests/test_bug_hunt_2026_09_18b_webapps_broll.py` -
an NFD editing proxy beside an NFC preview is found and returned in its disk
bytes, a `.mov` preview is still not its own editing proxy, and an unreadable
`Proxy/` answers `known: false`.

### CR-302B (proxy-tiers-3, owed in by companion-broll) - a server that could not LOOK must not send a 0.9.74 companion a stand-in plan - FIXED (broll/web/app/routes_api.py)

`_insert_object` answered `original_is_edit_weight` from the row on every
path, including the `known: false` outage path. `known` is read by companion
0.9.75 and later only; every build in the field today reads
`original_is_edit_weight` alone, so a heavy clip during an outage came back as
`false` and the companion planned a stand-in and wrote a ledger row that
outlives the outage for ever. On the `known is False` path the field is now
FORCED to `True` - the only value in this object that is not the truth - which
forces PLAN_FETCH_ORIGINAL on 0.9.65..0.9.74, i.e. fetch the file the editor
asked for, which is the route 0.9.75 takes from `known` anyway (it returns
before the weight is consulted). It is scoped to that path deliberately: a
`true` on the healthy path would suppress every stand-in the tier exists to
make, so the healthy arm keeps `_is_edit_weight(video)` byte for byte.
`edit_proxy_rel` is already null there, so nothing else changes. Two new cells
in `tests/test_bug_hunt_2026_09_18b_webapps_broll.py` pin both arms with a
HEAVY row (2160p, 200 Mb/s, h264), because the existing known=false cell in
`test_insert_target.py` is a 3 Mb/s clip that is edit-weight either way.

### CR-302C (music-1's twin, owed in by the music group) - a cancel delivered to a LIVE lease wedged the batch - FIXED (`broll/web/app/ingest_batches.py`)

`cancel()` set `lease_expires_at = NULL` in the same UPDATE that asked for the
stop, while leaving `state = 'running'`. That is outside
`expire_stale_leases`'s predicate (`lease_expires_at IS NOT NULL`) for ever, so
a companion killed before its next heartbeat (crash, Stop-Process, power cut,
its own upgrade) left a row no sweep could reach, no claim could take
(`_leaseholder_or_410` 410s on `cancel_requested` first) and whose every
`dest_name` stayed reserved, so each later drop of the same clip was allocated
a `(2)` name. The lease is now left alone - the YTDL-WEB-1 property it was
nulled for (the next fleet call 410s even if a heartbeat lands first) is
already delivered by `cancel_requested` - and `expire_stale_leases` finalises a
`cancel_requested = 1` batch whose lease ran out with `release(conn, batch,
state='cancelled')` before the requeue UPDATE, returning `cur.rowcount +
len(stopped)`: handing a cancelled batch back to `queued` would leave it asking
to be claimed while every claim is refused. Three new cells plus one existing
cell updated (`test_fleet_ingest.py`'s cancelled-release test asserted the
nulled lease; its real property, that the release is accepted, holds either
way and is unchanged).

### CR-302D (music-3's twin, owed in by the music group) - the retry and take-over notices reported a browser error as the companion's answer - FIXED (`broll/web/static/ingest.js`)

`ingestRetryFailedBatch` and `ingestTakeOver` printed `e.message` as the reason
this computer did not pick the clips up. The two commonest dispatch failures
are not refusals in words at all: no tray at all (a rejected fetch, message
"Failed to fetch", no status) and a companion too old for `/broll/ingest/*`
(404, the app's own generic "the CC Sync tray returned HTTP 404"). Both read as
something the companion said, and on the retry path the only sentence that says
what to DO - open this page on the computer that has the clips and press take
over - was unreachable. `ingestSpokeARefusal(e)` (a 409, or a body carrying
`reason`/`message`) now decides whether the companion really answered;
otherwise `ingestDispatchHint(e)` names it (`ING_TOO_OLD` on a 404, "The CC
Sync tray on this computer did not answer." otherwise) and the actionable
fallback stays. `ING_TOO_OLD` was hoisted out of the capabilities probe, which
already said exactly that sentence. Four node-driven tests drive the real
thrown shapes through both functions.

### Verification
- CR-302C: three new cells in `tests/test_bug_hunt_2026_09_18b_webapps_broll.py`; the lease-survives-the-cancel and sweep-finalises cells FAIL on the pre-fix source (checked with only those hunks reverted) and pass after, and the uncancelled-lease cell passes both ways, which is what pins that the sweep's own job is untouched.
- CR-302D: four node-driven cells in the same file; the no-tray, too-old and take-over cells FAIL pre-fix and pass after, and the real-409 cell passes both ways (the 2026-09-11b wording must survive). `node --check` on `ingest.js`.
- Re-run all of it: `cd broll/web; .venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_18b_webapps_broll.py tests/test_fleet_ingest.py tests/test_insert_target.py tests/test_bug_hunt_2026_09_18_webapps_tools.py tests/test_no_em_dashes.py tests/test_one_vocabulary.py tests/test_ingest_ui.py -q` - 179 passed.
- proxy-tiers-3 (CR-302B): the heavy-outage cell FAILS on the source with only this hunk reverted (`original_is_edit_weight` False) and passes after; the healthy heavy cell passes both ways, which is what pins the scoping.
- broll-1: `broll\web\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_18b_webapps_broll.py tests/test_bug_hunt_2026_09_18_webapps_tools.py tests/test_insert_target.py tests/test_no_em_dashes.py -q` from `broll/web` - 38 passed. On the source with only this hunk reverted, the NFD-editing-proxy cell and the unreadable-`Proxy/` cell FAIL (the broll-4 guard cell passes both ways by design: it pins that the guard survived the rewrite). `py_compile` clean on both files.

### Not fixed
- Nothing: broll-1 was this group's only confirmed medium. The downgraded-to-low broll-2 was not started (the box).

### OWED TO ANOTHER GROUP
- None outstanding. Three OWED items came IN and all three landed: companion-broll's forced `original_is_edit_weight` as CR-302B, and the music group's two twins as CR-302C (`ingest_batches.py`) and CR-302D (`static/ingest.js`). Nothing is owed OUT. The change is inside `broll/web/app/routes_api.py`; the companion side (`broll_server.derive_insert_paths`) needs no change, it simply starts receiving the non-null `edit_proxy_rel` it always expected.

### Deploy order
- Dashboard (which mounts `broll/web`) FIRST, as the companion-broll group's ledger says; no companion change is required by this group and no wire key changes shape. CR-302B is precisely what makes that order safe for the 0.9.65..0.9.74 builds in the field. A companion one release older or newer reads the same keys, and a dashboard rollback returns the pre-fix behaviour without stranding anything on either side.

### Note on scope
- CR-302C changes what an editor sees for one row shape: a cancelled batch whose companion never answered now ends as `cancelled` rather than reappearing as `queued`. That is the point of the fix, and `_leaseholder_or_410` already 410s such a batch, so no companion of any vintage can observe a difference.

### Owner decisions
- None needed.
