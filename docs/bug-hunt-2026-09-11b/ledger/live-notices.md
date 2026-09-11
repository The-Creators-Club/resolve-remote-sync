## The live dashboard's open notices, 2026-09-11 (CR-266)

Not from the hunt reports: from the live dashboard's own PROBLEMS THE SERVER
FOUND panel, read on 2026-09-11. One row was a `server_error` from the Claude
Code SET UP wizard whose traceback no longer existed anywhere, because the
notice sent the reader to a log that a container recreate had already deleted:
that is one finding about the route that raised (CR-266a) and one about the
notice that could not describe it (CR-266b). Twenty more rows were
`invariant_broken` about a folder somebody had moved on the NAS two days
earlier, which the check could no longer see to re-raise and nothing was in a
position to close (CR-266c). The pattern behind all three is the same one the
hunt found everywhere: a diagnosis that describes evidence the deployment does
not keep.

### CR-266a (live notice, 2026-09-10T06:55Z) - the SET UP wizard's 500 became a sentence, and the check that could raise stopped raising - FIXED (`cli_tools.py`)

The live dashboard recorded exactly one `server_error` notice,
`/api/v1/admin/ai-providers/claude_code/install (TypeError)`, at
2026-09-10T06:55Z, when the admin clicked the Claude Code SET UP wizard. The
traceback is gone: in image mode `/data` survives a recreate and the
container's log does not (CR-266b covers that half, in `notices.py`). So this
entry is honest about what it found and what it fixed.

**The exact line was not identified, and this entry does not claim it was.**
Every shape the two publishers' APIs can answer with was driven through
`_install_claude` and `_install_codex` behind a stubbed
`release_feed.open_https_stream`: a `/latest` that is `null`, a manifest that
is `null` or a JSON list, `platforms: null`, a platform entry that is `null`,
a `checksum` that is a number, a `size` that is `null` / a string / a dict, a
`binary` that is `null` or a number, a release whose `assets` is `null`, an
asset whose `name` is a number, an asset dict that is `null`, a tag with no
version in it, and a `SHA256SUMS` body that is not text. Every one of them is
already a `ToolError` refusal, because `claude_platform_entry`,
`codex_release`, `codex_asset`, `codex_version` and `parse_sha256sums` coerce
with `str()` / guarded `int()` before they use anything. And they all run in
the install THREAD, whose `except Exception` turns any failure into a status
field: a publisher shape can therefore never be the 500 the notice recorded.
The request thread's own code (`install_supported`, the lock, `_write_inflight`,
`install_status`) was then driven through the real route with the admin-session
fixtures against a wrong-typed `state.json` / `install.json`, a missing data
directory and a polluted status dict, and none of those 500 either.

What WAS wrong, and is fixed:

1. `install_supported`'s docstring says "Never raises" and both its callers
   depend on it - the wizard's render, and `start_install` on the request
   thread of the route the notice named - but it caught `UnsupportedPlatform`
   only. `Path(settings.db_path)` on a settings object with no path, an
   `os.access` the kernel refuses, or a `dashboard_update.space_refusal`
   whose signature has drifted (a TypeError raised AT the call site, which
   that function's own broad try/except cannot see) all left the route as a
   bare 500. The room half moved into `_install_room` and the contract is now
   enforced: a check that cannot COMPLETE is a refusal naming the exception
   type, never an accidental yes, and it points at the "type its full path"
   fallback. This is a reproduced TypeError, not a hypothetical one.
2. The route had no last resort. Whatever raised on 2026-09-10, the admin got
   `{"detail": "internal error"}` from `app.py`'s generic handler, and there
   was nothing else to read. `POST` and `DELETE` on
   `/admin/ai-providers/{name}/install` now answer 503 with a sentence that
   names the tool as the page names it, names the exception TYPE, says nothing
   was left half-installed and names the fallback. The exception's own message
   never crosses (this module handles sign-in transcripts and download URLs).
   `DELETE` gets the same treatment because `record_server_error` keys on
   (path, exception class) and never carried the method, so the remove route -
   an `rmtree` of a 313 MB tree plus `cancel_signin`, in a threadpool, where
   an exception DOES reach the route - is as likely an origin as the POST.
   `ToolError` stays 400 and `ToolBusy` stays 409, and the `server_error`
   notice is still recorded (by the route now, best effort, because answering
   503 takes the request out of the handler that used to write it).
3. The install thread's own crash status read `TypeError while installing
   claude_code`: a Python class name and the tool's internal name, with
   nothing about whether anything was installed. It now names the tool's
   label, the STEP it died on (the one piece of a lost traceback the status
   still holds), that nothing was installed and what to do instead.

The checksum CONDITION (trust-model-7) is untouched and re-pinned by a test:
a Codex release that publishes no checksum for the asset is still refused and
nothing is installed unverified.

### CR-266b - a server error pointed at a log the container had thrown away - FIXED (notices.py, crash_report.py)

`notices.record_server_error` stored the exception's CLASS and nothing else,
deliberately: the message is the one string that could hold a path, a query or
a credential fragment, and the body said "the full error is in the server log
with this same path" instead. That sentence is not true of the deployment this
server actually runs. In image mode `/data` survives a container recreate and
the container's log does not, so the one fault the live dashboard recorded on
2026-09-10 ("/api/v1/admin/ai-providers/claude_code/install (TypeError)",
once, 06:55Z) has no surviving account of itself: no type beyond TypeError, no
message, no line. A notice that names a fault and then points at nothing is a
log line with better placement, which is the thing this whole module was
written to stop being.

The body now carries `notices.error_detail(exc)` after its own sentence: the
exception type, its message, and the innermost three frames as
`ccsync_dashboard/cli_tools.py:412: install_tool <- ...`, repo-relative so the
container's directory layout does not reach the home page. The mitigations are
the pair the omission was standing in for: every character goes through
`crash_report.redact` first, and the detail is bounded
(`SERVER_ERROR_DETAIL_CHARS = 1500`, with the message capped separately at 700
so a five-thousand-character `repr` cannot spend the budget and leave the
frames out). `crash_report._REDACTIONS` gained the three key shapes that turn
up BARE in an exception message with no `key=` in front of them to be
recognised: `sk-`/`sk-ant-`/`sk-proj-`, a `cce1.` fleet token, and a GitHub
`ghp_`/`gho_` token - all three reachable from exactly the route CR-266a is
about. The subject is untouched, because it is the `(kind, subject)` de-dup
key, and the occurrence count still reads back out of the previous body
because the detail is appended AFTER the counted sentence, never in front of
it. `error_detail` never raises: it is called from the 500 handler.

The daily digest already quotes notice bodies (`alerts._check_notices` ->
`notice_error` -> `_finding_body`), so the mail an owner reads at 07:00 now
holds the same three facts the panel does; that path is pinned by a test
rather than changed. `docs/SELF_DIAGNOSIS.md` section 3's description of the
kind was updated in the same change.

### CR-266c - twenty notices about a folder that had been moved rode the digest for ever - FIXED (invariants.py)

Twenty open `invariant_broken` notices, `proxy_pairs:
2026-creator-profiles-season-1/Interviewees/Interviews/Gold Card Meetup/Proxy/
<clip>.mp4`, first_seen 2026-09-09. The folder had been moved to
`Projects/2026/FF5/Talent Gap/Interviewees/Gold Card Meetup/`, where the
originals sit beside the Proxy folder: nothing is wrong on the NAS, and
nothing on the server could say so. `run_cycle` only ever names the subjects a
pass SAW, and a subject the check can no longer see is neither re-raised nor
cleared. Twenty is `db.INVARIANT_MAX_SUBJECTS` exactly, which is the other
half: while ANY pass of that invariant is capped - and a fleet with more than
twenty orphaned proxies caps every pass - the truncated-pass keep-list (CR-241,
made durable by CR-256d's `_TRUNCATED_CARRY` earlier in this same wave) holds
every subject the ledger ever remembered, so those rows stayed open for the
life of the container and rode the daily digest with it.

The fix is that the cap is a REPORTING cap, never a knowledge cap: a per-path
check walks the whole tree and then hands over the first twenty. `Outcome`
carries a new `found` - every broken subject NAME this pass saw, names only,
bounded at `MAX_FOUND_SUBJECTS = 2000`, pass-local and never stored - and
`invariants.broken()` fills it. A truncated pass that HAS a `found` set is
authoritative: the keep-list is exactly that set, so the twenty the cap could
not report stay open (CR-241's outcome, unchanged) and a subject that has
VANISHED from it is closed like any other cleared subject. An outcome that
cannot name its whole set (`Outcome(..., truncated=True)` built by hand, or a
set past the bound) falls back to `_TRUNCATED_CARRY` exactly as CR-256d left
it, and a pass that reached no verdict at all still clears nothing: NOT
CHECKED is not OK (bug-hunt-2026-09-03 dash-collector-2). Both directions are
pinned by their own test.

### Verification

CR-266a, in `dashboard/tests/test_bug_hunt_2026_09_11b_cr266a_cli_tools.py`
(15 passed), run with the dashboard venv:
- `tests/test_bug_hunt_2026_09_11b_cr266a_cli_tools.py::test_a_space_check_that_raises_is_a_refusal_not_a_traceback` -> fails at f1eeb42 (TypeError escapes), passes now
- `...::test_a_data_volume_with_no_path_is_a_refusal_not_a_traceback` -> fails at f1eeb42, passes now
- `...::test_the_install_route_refuses_instead_of_500ing_when_the_room_check_breaks` -> fails at f1eeb42 (the route raises TypeError, i.e. a 500), passes now as a 400 naming the cause
- `...::test_an_unforeseen_fault_is_a_503_with_a_sentence` -> fails at f1eeb42, passes now
- `...::test_a_failing_remove_on_the_same_path_answers_the_same_way` -> fails at f1eeb42, passes now
- `...::test_an_unforeseen_crash_in_the_worker_names_the_tool_and_the_step` -> fails at f1eeb42, passes now
- Guards, not regressions (they pass either way, and are here so the publisher-shape half and the checksum CONDITION stay that way): `test_a_refusal_is_still_a_400_and_a_busy_install_still_a_409`, the seven `test_a_wrong_typed_publisher_manifest_is_a_refusal_never_a_typeerror` cases, `test_a_codex_release_with_no_published_checksum_is_still_refused`
- `tests/test_cli_tools.py` (the module's own suite, same territory): 120 passed, unchanged

CR-266b and CR-266c, all in
`dashboard/tests/test_bug_hunt_2026_09_11b_cr266_live_notices.py`, run
with the dashboard venv. "fails before" for the CR-266c tests means against
the working tree WITH CR-256d and without this hunk (the carry is uncommitted,
so f1eeb42 alone cannot show the shape):
- `test_a_server_error_notice_carries_the_exception_and_its_frames` -> fails at f1eeb42, passes now
- `test_the_counter_still_reads_back_out_of_the_longer_body` -> pins the counted-sentence-first ordering
- `test_only_three_frames_and_a_bounded_body` -> fails at f1eeb42, passes now
- `test_a_secret_in_the_exception_message_is_masked` -> fails at f1eeb42, passes now
- `test_an_exception_with_no_traceback_is_still_described` -> fails at f1eeb42 (no such function), passes now
- `test_the_daily_digest_quotes_the_traceback_under_the_subject` -> fails at f1eeb42, passes now
- `test_a_subject_that_has_vanished_is_cleared_by_a_capped_pass` -> fails before (the notice stays open), passes now
- `test_a_pass_that_cannot_name_its_whole_set_clears_nothing` -> pins CR-256d's keep-list
- `test_a_check_that_could_not_run_clears_nothing_either` -> pins the NOT CHECKED rule
- `test_an_uncapped_pass_still_clears_what_it_did_not_find` -> pins the direction that already worked
- `test_the_found_set_is_names_only_and_bounded` -> fails before, passes now

11 passed in that file. Also green, unchanged: `test_alerts.py`,
`test_invariants.py`, `test_notices.py`, `test_notices_sweep_wave2.py`,
`test_crash_report.py`, `test_bug_hunt_2026_09_11_dash_collector_alerts.py`,
`test_bug_hunt_2026_09_11b_dash_collector_alerts.py` (256 passed).

### OWED TO ANOTHER TERRITORY
- CR-266a: none. `notices.record_server_error` is CALLED from `cli_tools.py`, never edited there, and the call is wrapped so a signature change cannot fail the request twice. No schema change, no wire change, no deploy ordering.
- dash-db: `dashboard/src/ccsync_dashboard/db.py`: `record_invariant_result`: take a `truncated: bool = False` and skip the "DELETE the subject rows this pass did not name" when it is set. Still owed from wave 1, and CR-266c narrows it rather than replacing it: with `found` in hand the carry is only reached by an outcome that cannot name its whole set, but a container restart still loses that carry. Dashboard-only, no deploy ordering.

### Owner decisions
- The refusals name the exception TYPE ("TypeError") in text an admin reads. That is jargon, and it is the same judgement CR-266b made for the notice body: it is the one word that makes two different faults on one button distinguishable when the log is gone. If the owner would rather not see it, it is one f-string in `_unexpected` and one in `install_supported`.
- A failed ROOM CHECK refuses the install rather than proceeding on the assumption there is room ("an unverified check is NOT CHECKED, never OK"). The cost is that a container where the check itself is broken cannot install a CLI from the page at all, and must use the typed-path fallback.
- Observed and NOT fixed (no TypeError, outside this item): `claude_platform_entry` accepts the manifest's `binary` verbatim, so a publisher answering `"binary": "../x"` would put `..` in the download URL segment. The bytes are still checked against the manifest's own sha256 and the local filename comes from `spec(name).rel_binary`, so nothing is written outside the version directory; it is a URL-shape hardening (the `validate_version` rule, applied to one more field) for whoever next owns this file.
- A `server_error` notice now stores the exception's MESSAGE, which the 2026-08-28 code deliberately refused to do (CR-266b). The alternative is to keep the refusal and write the detail to a file under `/data` instead, which survives a recreate and is not rendered on a page - it also puts the diagnosis back somewhere nobody opens, which is the failure this reverses. The mitigation is masking plus a bound; the HTTP 500 body is unchanged and still carries nothing derived from the exception.
- The bound is 1500 characters of detail, of which at most 700 is the message, and three frames (CR-266b). A longer body would be a crash dump in a table nothing prunes, and it is rendered inline on the home page.
- `MAX_FOUND_SUBJECTS = 2000` (CR-266c). Past that an invariant's pass carries no `found` set and behaves exactly as it did before this change: the carry keeps its notices open, and the stale ones among them need a pass that is not truncated to clear.
- The nas_media side of the live symptom is NOT touched. If the collector's `nas_media` rows for a hand-moved folder are what the check is still seeing, the notices are honest and the row pruning is the fix; this change is about the case where the subject has gone from the scan, which is what the panel showed. Worth one look at the live server after the deploy: the twenty should clear on the first pass of `proxy_pairs` that finds its whole set.
