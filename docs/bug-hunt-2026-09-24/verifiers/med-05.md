# Verifier med-05 (2026-09-25)

Judged against HEAD (`git archive HEAD` into the session scratchpad; probes ran
with the dashboard venv against that HEAD copy, never the working tree).

## bug-dash-db-1 - CONFIRMED (medium)
`queued_jobs` is `ORDER BY priority DESC, id ASC LIMIT 200`, and both
`jobs.offers_for_machine` (jobs.py:931) and `db.claim_next_job` (db.py:10534)
walk only that window. Nothing ages a queued job out, a never-claimed job never
spends its retry budget, and whisper never pins, so 200 unrunnable (or
capped) jobs at the head starve everything behind them indefinitely.
Evidence: probe with 200 `whisper` jobs requiring `gpu_vram_gb: 6` then one
`peaks`: `len(queued_jobs)==200`, peaks id absent, `claim_next_job(...,
allowed_ids=[peaks])` -> None, `offers_for_machine(...)["offered"]` -> [].
Not a duplicate of anything in this group.

## bug-dash-db-2 - CONFIRMED (medium)
The companion lists at most 2,000 proxies per project (manifest.py
`MAX_PER_FILE_ENTRIES`, sets `truncated`), and `fetch_sync_backlog`'s `down`
spec counts every NAS proxy with no `editor_media` row, so every proxy past the
2,000th is a permanent phantom download. The only hedge is
`manifest_truncated`, which transfers.html:78 renders as "totals may
undercount" - the wrong direction for `down`. CR-314 fixed the combined-cap
case in `replace_editor_media` only; a single kind over 2,000 is untouched.
Evidence: read of db.py 9662-9766, 9284-9316, manifest.py 211-226,
api.py:590 (the backlog feeds the transfers/queue view unfiltered).

## bug-dash-api-1 - CONFIRMED (medium)
`approve_pending_ssh_key` in NAS mode calls
`nas.create_or_update_editor(username, key_text, None)`; TrueNAS PUTs
`sshpubkey` to the single new key and Synology writes `authorized_keys` via
`printf > tmp; mv -f`, so both REPLACE. The approve button in
admin_users.html has no `hx-confirm` and no warning (unlike the manual
[ UPDATE SSH KEY ] form, which confirms "Replace ...'s SSH key?"). The
wizard's `_offer_ssh_key` offers each computer's own key, so approving an
editor's second computer locks the first out of SFTP (lanes A and B).
Recoverable, not data loss, so medium stands.

## bug-dash-api-2 - CONFIRMED (medium)
`_move_proxy_siblings` targets `dest.parent/"Proxy"/candidate.name`, i.e.
the old proxy name, although `FileMoveIn.to_path` may rename (undo depends on
that). Probe on HEAD: same-folder rename A001.mov -> Renamed.mov returned
`(0, ['A001.mov (something is already at the destination)'])` with the proxy
unmoved (move stored PARTIAL, HTTP 207 with a false reason); a rename into
another folder moved the proxy as `B/Proxy/A001.mov`, which no longer pairs
with `Other.mov`. The companion's `rename_proxy_siblings_case_only` renames to
`dest.stem`, so the case-only case also diverges between NAS and machine.

## bug-dash-diag-1 - CONFIRMED (medium)
`protection.run_cycle` builds the `missing` keep-list only from lines BROKEN
this pass; a line that falls to NOT_CHECKED (tasks() is None at
protection.py:328/415) closes its MISSING notice, and `_protection_findings`
drops it from `protection_missing`, so `alerts.deliver` records and mails a
recovery. `invariants.run_cycle` carries exactly this guard (`stored_broken`,
invariants.py:1284-1353, dash-collector-2); protection has none. Every NAS
blip flaps the snapshot/backup line: "cleared" mail, then a fresh "new" error.

## bug-dash-diag-2 - DOWNGRADE (low)
The mechanism holds: `checked_kinds` is built from `ALERT_KINDS`, and
`CHECK_FAILED` is outside it (alerts.py:3686), so a `check_failed` subject is
never offered for recovery and `_is_open` stays True for ever. But the impact
is smaller than stated: the dashboard's open counts come from the LIVE scan
(`alerts.open_counts(findings)`, api.py:1553/10310, ui.py:1813), not the
ledger, so nothing shows it as open; and a later failure is still mailed
(check_failed is SEV_ERROR, which re-sends daily while open). What is lost is
the "recovered" message and the digest's label ("repeat ... 49 days" instead
of new). A misleading label, no hidden problem: low.

## bug-dash-diag-3 - CONFIRMED (medium)
`restore_missing` creates `live/.restored-<ts>` INSIDE the live project folder
(recovery.py:424), which is the Syncthing folder root. The leading dot only
hides it from provision's own walks (recovery.py:88-95 says so); Syncthing
syncs dot-directories, and `build_stignore_lines` (provision.py:156) ignores
only video extensions, partials, ytdl fragments and Proxy. So every restored
non-video file (audio, .drp, stills, subtitles, and the copied
`.ccsync-project` marker) is pushed to every full-tick machine. Read only; not
reproduced against a live Syncthing, but nothing in the path filters it.
