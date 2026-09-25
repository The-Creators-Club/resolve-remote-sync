# Verifier med-07 (2026-09-25)

Judged against HEAD (63d4290) with `git show HEAD:<path>`. Probes ran in the
session scratchpad against HEAD copies of the modules; nothing in the repo was
edited except this file.

## bug-dash-ops-1 - CONFIRMED (medium)

`_in_sent` (triage_mail.py:578) runs `SEARCH HEADER Message-ID "<mid>"`, which
RFC 3501 defines as a substring match, and `handle_message` (:499) turns a hit
into `ok = True` whenever the sender equals `alerts_smtp_user`, with no regard
for an explicit `dkim=fail`/`dmarc=fail` in the topmost header. A forged
message with a Message-ID fragment such as `mail.gmail.com` matches any Sent
message. Even an exact match would be weak: every recipient of the owner's mail
knows real Message-IDs from his Sent folder. The CCT token (48 h, sent only to
`alerts_smtp_to`) still bounds it, and the feature is off in the vendor build,
so medium, not high.

Evidence: read `_in_sent`, `handle_message`, `poll` at HEAD. No ledger entry
covers it; the override arrived in 19dc9cf/9ee90d0.

## bug-dash-ops-2 - CONFIRMED (medium)

`auth._resolve_session` accepts a cookie signed with any
`session_secrets_previous` secret (DASH-2), but `YtdlGate._identified_scope`
(ytdl.py:171) calls `auth.read_session_cookie(self._secret, cookie)` with no
`previous=`, and the gate is built with only `settings.session_secret` (:555).
After a rotation the request gets past login_gate but no identity header is
added, so ytdlweb returns its own 401 until the editor signs in again. The same
code is in broll.py and music.py `_identified_scope`. This is a gap in DASH-2
rather than a duplicate of it.

Evidence: read auth.py `_read_token_any`, `read_session_cookie`,
`_resolve_session`, `previous_session_secrets`, plus the three gates.

## bug-dash-ops-4 - CONFIRMED (medium)

The key pattern's `\b` before the key cannot match after `_`, so
`TRUENAS_PW=`, `DASH_SESSION_SECRET=` and `SYNCTHING_API_KEY:` get through.
A quote between the key and `:` also defeats the pattern. `notices.error_detail`
(notices.py:1328) runs exception text through this redactor, so a miss can
reach the home page and DB backups as well as crash files.

Evidence: I exec'd HEAD's `_REDACTIONS` + `redact`. `'DASH_SESSION_SECRET=abcdef123'`,
`'TRUENAS_PW=hunter2'`, `'SYNCTHING_API_KEY: zzzz'`, `"{'password': 'hunter2'}"`
and `'{"api_key": "k123"}'` came back unchanged, while `'token=abc'` became
`'token=<redacted>'`.

## bug-broll-1 - CONFIRMED (medium)

The panel sends the STORED `item.video_id` (clientfolders.js remove/note).
`remove_item`/`set_note` match `video_id = ? OR (share, rel_path) = _identity_of(current index, ?)`,
which mixes two id spaces. After a renumber, the stored id of X is the current id
of Z, so one click deletes both items. MEDIA-23's comment assumes the panel sends
the current id, which it does not.

Evidence: probe using the HEAD `app.client_folders` module and the broll/web
venv. The items were X (stored 5) and Z (stored 9), and the index was
renumbered to Z=5, X=12. `remove_item(c, 1, 5, idx)` returned True and the
folder was left empty (`[]`).

## bug-broll-2 - CONFIRMED (medium)

`HttpBackend.write_index_result` and `record_moved` post the local shadow's
`video_id`, even though the module docstring says the two id spaces are
independent and `upsert_video` throws away the remote id. `routes_ingest.ingest_index`
looks up `body.video_id` directly in the canonical DB, then deletes and replaces
segments, themes and flags on whatever clip holds that number. This mode is
dormant on the base rig (co-located sqlite), but `db.mode: api` is a supported,
documented config (INDEXERS.md, dashboard_site.py), and the corruption it causes
is silent. So medium stands.

Evidence: read http_backend.py, cli.py `_storage`, routes_ingest.py
`/index`. Related to the 2026-08-21 hunt's HttpBackend `error`-field finding
(a different defect).

## bug-broll-3 - CONFIRMED (medium)

The mechanism holds end to end in the code:
- `ingest_batches.claim` mints `videos` rows with AUTOINCREMENT on the live DB (max B+1...).
- The base rig mints its own B+1... on its copy.
- The stills are `posters|sprites/{id}.jpg` in one directory, served by id (routes_media.py, routes_share.py).
- `build_archive` copies base-rig stills by id over a differing file, stashing the old one.
- `broll_drain` re-inserts drained videos "never with their old id".

A grep of server/ and broll/ turns up no step that renames stills. I did not
reproduce it end to end because that needs a publish. Every link was read at
HEAD, which moves the hunter's PLAUSIBLE to confirmed.

Evidence: read ingest_batches.py:140-160, :800-830; routes_media.py;
build_archive.py:100-130, :590-610; server/broll_drain.py:220-260; `git grep
-i poster|sprite` over server/ and the drain.

## bug-music-ytdl-3 - DOWNGRADE (low)

The mechanism is real. `write_item_result` writes the `tracks` row before the
companion uploads, and the next item's `allocate_name` calls `share_root_ready`.
In a library whose only row is the unlanded item 1, both sample ends miss, so
it answers "not mounted" (503 `share_not_ready`, retryable). If the root dir
does not exist yet, `library_has_tracks` is now true and gives the same refusal.
The case is narrow, though. It happens only on the first drop into an empty
library, and only if item 1's upload has not landed by the time item 2's
embedding finishes, which normally takes seconds to minutes of CPU.
The companion retries with backoff for about 20 minutes, and the first
successful check is cached. It fails permanently only with uploads paused or a
very slow first upload.

Evidence: read config.share_root_ready (HEAD :478-560), ingest_batches
`write_item_result`/`allocate_name`, and companion music_ingest.py (per item:
embed -> `_post_result` -> `_enqueue_uploads`, uploads async).

## bug-music-ytdl-4 - CONFIRMED (medium)

`release(state='cancelled')` moves every item not in
(live, duplicate, skipped, cancelled, queued_for_base_rig) to `cancelled`. That
includes `indexed`/`uploading` items whose `tracks` row already exists. The
companion's `cancel()` stops the upload queue before it releases, so those files
never land. `cancelled` is in ITEM_TERMINAL, `retry_failed` moves only `failed`,
and the only `DELETE FROM tracks` is `db.prune_missing`, a manual base-rig
`--prune`. The rows stay searchable, their audio returns 404, and they count in
rescoring. The release docstring promises these rows stay `indexed` and can be
fixed, and the code contradicts it. The same path runs from
`expire_stale_leases` for a cancel whose companion died. No existing ledger entry
covers it: CR-286E and CR-304A are about the cancel wedge, not orphan rows.

Evidence: read ingest_batches.py release (:1231-1262), expire_stale_leases
(:659-700), retry_failed docstring, ITEM_TERMINAL; companion broll_ingest.py
`cancel()` (:1326-1345); `git grep "DELETE FROM tracks"` over music/web.

## Duplicates

None within this group, and none duplicates a filed high.
