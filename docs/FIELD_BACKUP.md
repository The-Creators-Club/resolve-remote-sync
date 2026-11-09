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

## Not verified live
Real TeraCopy with several lanes at once (it is a single-instance app; jobs are matched by
destination in its history database) was not exercised: tests use a fake TeraCopy.
