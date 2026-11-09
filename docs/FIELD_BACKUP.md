# Field backup page (companion)

2026-11-09 - part D of the footage-sorter ledger browser
(`footage-sorter/docs/LEDGER-BROWSER-DESIGN.md`, "The companion" item 4).

Tray "Field backup..." opens `http://127.0.0.1:8898/field`, served by the companion itself
(`field_server.py`; port `field_server_port`, off with `field_server_enabled = false`). Page, script
and style come from `assets/field/` and reference nothing outside, so it works with no network.

## Modules
- `field_mode.py` rules: what is tracked, kinds, the card verdict, folder naming, quick verify, the
  small state files.
- `field_copy.py` the engine: planning, one lane per physical drive, refusals, failures.
- `field_service.py` cards, destinations, verdicts, the outbox and mirror legs.
- `field_server.py` loopback HTTP, guarded like the b-roll server (Host, Origin, token, JSON).

## Rules worth knowing
- **Safe to format** = every masters/audio file on the card has one copy at home (a `nas` volume) or
  two on different counting volumes (`ours`, `laptop`, `nas`). Client drives, cards, and drives with
  no kind never count. A result resting on laptop copies alone is flagged. A person sets a drive's
  kind on the page when the ledger and the label (CIB_D<n> = ours, WD-<n> = client) do not say.
- **Layout**: `<destination>/FieldBackup/<day> <card label or serial>/<the card's own tree>` on a
  drive and the NAS pool; straight under the folder for a configured laptop folder. The day is the
  newest file's, so running the card again later lands in the same folder.
- **Copying** goes through `card_copy.CardJob` (TeraCopy on Windows, Python elsewhere): never
  overwrites, resumes a short copy of the same file, reports a different file as a conflict. Files
  already there (same size, mtime within 2.5 s, or on that drive under another path per the mirror
  and confirmed on disk) are quick-verified (size, first/last MiB, moov) and recorded `quick`.
  Copier-verified copies are recorded `full`.
- **Lanes**: destinations on one physical disk (Windows: storage device number) share a lane.
- **Failures**: a destination without room (needs + 256 MB) is refused before it starts; a drive
  that fills or is pulled mid-copy stops only its lane, keeping and recording what landed whole.
- **Ledger**: verified copies go to the outbox (`tool: field`) and, when the dashboard answers, to
  the ledger, followed by a mirror pull. Until the mirror catches up, copies made here count from
  `field-local-copies.jsonl`. NAS-pool copies are not outboxed (the server's pool scan records them).

## After the adversarial review (2026-11-10): what "safe to format" will not believe
- A copy that failed TeraCopy's verify is renamed `<name>.failed` (the ledger skips it). "Already
  there" is trusted on a quick check only when a verified record exists for that exact volume and
  path; otherwise the file is compared in full. A TeraCopy copy its own verify did not reach is
  recorded only after a full compare.
- Copies are counted by physical disk (two partitions, or a folder that is a junction onto a field
  drive, are one). A folder on a card or USB stick is never "the laptop".
- Every original judges the card (stills, 360, HEIF, raws, video, audio) except sidecars (XML, THM,
  LRV, ...). Untracked originals are known from this laptop's own copies only.
- A copy on an attached drive is stat'ed (size and time) before it counts; a deleted one is dropped.
- A copy found by name, size and time must be THIS card's: local rows keep the card serial and path,
  other rows must end with the card-relative path (a top-level file must sit in the card's folder).
- Two cards with one label and day: the second lands in `<day> <label> <serial>` (a `.ccsync-card`
  marker file says whose folder it is).
- A mapped letter is the NAS pool only with a `.ccsync-pool` marker or a UNC target (config
  `field_pool_unc`); a letter that changes hands, or a pulled card, stops the lane.
- `teracopy.launch` counts a launch as registered only when the new history database lists the
  job's files and destination; an empty database or another lane's is not it; a job that never
  registers is launched again (twice at most); a cold TeraCopy (no History folder) is waited for.

## Not verified live
Real TeraCopy with several lanes at once (it is a single-instance app; jobs are matched by
destination in its history database) was not exercised: tests use a fake TeraCopy.
