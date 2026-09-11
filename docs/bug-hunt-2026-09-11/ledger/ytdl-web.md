## The YouTube downloader service, 2026-09-11 (CR-244)

### CR-244 - a lost Projects mount read as "the disk is full", one editor's two computers could both download the same job, and a widened destination could be handed to a machine after all - FIXED 2026-09-11 (`ytdl/web`)

Seven findings from the 2026-09-11 hunt (`docs/bug-hunt-2026-09-11/hunters/ytdl-web.md`,
verdicts in `verifiers/ytdl-install.md`). No schema change: every fix is code,
comment or test, so a dashboard carrying this can be deployed under companions
of any age.

**ytdl-web-1 - the vanished mount that measured as a full disk.**
`free_bytes_at` walked up to the first ancestor `shutil.disk_usage` would
answer for and never asked whether the answering path was the destination's.
In the container `YTDL_PROJECTS_ROOT` is a bind mount, and a mount that has
gone away leaves its mount POINT behind on the container's own overlay
filesystem - so the probe succeeded, reported the overlay's two spare
gigabytes, and every `POST /api/jobs/{id}/download` came back "there is only
2.0 GB free where these clips go ... Free some space and press DOWNLOAD
again." The editor is sent to delete footage for a fault that is not theirs,
the actual one (no tree at all) is named nowhere, and the same refusal comes
back after they do. The `free is None` fail-open path written for exactly this
state was unreachable, because the case never raises. The verdict's correction
is load-bearing: comparing `st_dev` against `PROJECTS_ROOT` does NOT work,
since with the mount gone `PROJECTS_ROOT` is itself the leftover directory and
both sides match. The guard is now whether the destination's own PROJECT
FOLDER is there, and it is asked only on the way to a refusal
(`_refuse_if_the_tree_is_gone`): a download that fits is a download that fits,
and a folder this check cannot see is not a new way for one to be impossible.
A tree that is gone gets its own 409, `reason: tree_missing`, naming the mount
and saying in as many words that this is the server having lost the share and
not a full disk.

**ytdl-web-2 - "free some space and press DOWNLOAD again" did not work for a
minute.** The refusal's own instruction was the one action a 60 s cache
invalidated: an editor who deleted 300 GB got a byte-identical 409 quoting the
pre-deletion number, and the reasonable next conclusion is that DOWNLOAD is
broken. Refusals are no longer cached - `_forget_free_at` drops the entry
before the 409 is raised, from inside the module that owns the lock rather
than by reaching into the dict from the caller. Fixed in the same edit as
ytdl-web-1, as the verdict asked, because that fix changes what is cached.

**ytdl-web-3 - one editor's two computers could both download the same job.**
CR-66 narrowed the lease to `(editor, machine_id)` at the CLAIM door only;
`heartbeat`, `download-manifest` and `clip_status` all went through
`is_leaseholder(job, editor)`, which answers True for ANY of that editor's
computers. The docstring justified it with "the machine that could not claim
never gets a job id to post about", which does not cover the machine that DID
claim and then lost the lease by EXPIRY. Laptop A stalls past the lease,
desktop B claims it legitimately, A wakes up: A's heartbeat re-extended B's
lease, A's manifest was served, and A's per-clip `done` posts were recorded
against B's run with `download_host = claimed_by`. Two trees, two sets of
clips, lane A carrying both up - the outcome CR-66 exists to end - and neither
companion was ever told 410, so neither stopped. `machine_id` is now carried
on the heartbeat and clip-status bodies, as `?machine_id=` on the manifest GET
(a GET has no body) and as `X-CCSync-Machine` on all three, so whichever
spelling the companion build uses is understood. It is OPTIONAL everywhere:
absent is an older companion and keeps today's per-editor answer, which is
what lets this ship before the companion half. `db.is_leaseholder` takes the
machine, and `db.heartbeat_download` takes it into its WHERE as well, because
the route check and the compare-and-set are separate statements and the CAS is
the one that decides.

**ytdl-web-4 - the free-space gate measured the wrong computer.** The check
runs before any claim exists, so it always sized the NAS mount inside the
container. With `YTDL_LOCAL_DOWNLOAD` on, a job created local is normally
fetched onto the requesting editor's own disk and carried up by lane A later -
so a NAS at 9 GB free refused an editor with 4 TB free locally, naming a path
they cannot act on from the machine they are sitting at. The gate is now
skipped for a local job when the feature is on; the companion's own
free-space decision at claim time reads the disk that is actually written, and
the page already shows the estimate.

**ytdl-web-5 - three comments claimed an invariant the code has not held since
CR-96.** `NewJob.local` is client-supplied ON PURPOSE: CR-96 half 1 widens the
destination to every ACTIVE project whenever the download will run on the
server, because no machine's sync plan constrains a fetch no machine performs.
The module docstring, `schema.sql` and `migrations/013` all still said that a
client-supplied `local=false` "would let any editor write into any active
project, which is the one thing this check exists to stop" - so an owner
reading them would believe destinations were constrained when they are
deliberately not, for every editor, by default (the SPA posts `local:false`
whenever the flag is off, i.e. the whole shipped fleet). All three now say what
the widening is and is not. The real seam the verdict isolated is now closed at
the CLAIM door, not by deriving `local` server-side, which would break the case
CR-96 exists for: `db.claim_download`'s compare-and-set refuses a job whose
`created_local` is 0, and `routes_fleet.claim` answers 410 `created_widened`
with the reason the companion logs. The widening was granted on the promise
that no machine claims the job; a client could otherwise post `local:false` to
reach a project it does not sync and then hand the job id to its own companion
on 127.0.0.1:8899. Nothing an editor sees changes: a declined claim means the
server worker downloads the job exactly as it was created to.

**ytdl-web-6 - `_free_cache` had no ceiling.** One entry per destination is one
entry per SEARCH, in a uvicorn process meant to run for months, and nothing
ever removed one. The key is now the tree's filesystem: every destination lives
under `PROJECTS_ROOT`, so the root answers for all of them, and it is a pure
path comparison - no stat, which is what lets a cached answer come back while
the mount underneath is hanging.

**ytdl-web-7 - the " -- " cleanup reached one string out of seven.** YTWEB-7
reworded `worker.DEGRADED_NOTE` because the em-dash scan does not catch `--`,
and left six editor-facing strings spelling an em dash that way: the two "Tick
it on the dashboard first" refusals, the stale-attestation 409, the three AI
provider ops hints, and the rights notice the browser paints. All reworded with
a colon, a comma or two sentences, and the gap is now guarded:
`test_no_em_dash.py` gained a `' -- '` scan over the non-docstring literals of
the six modules whose strings reach a person, with log calls subtracted the way
docstrings are. The attestation's `TEXT_VERSION` is deliberately NOT bumped
(there is a comment saying so at the constant): the edit changed punctuation
and not one word of what is agreed to, and a bump sends every editor in every
fleet back through the dialog before they can download anything.

### Verification
- tests/test_bug_hunt_2026_09_11_ytdl_web.py::test_a_vanished_projects_mount_is_its_own_refusal_and_not_disk_full -> fails at 40f931a, passes now  (ytdl-web-1)
- tests/test_bug_hunt_2026_09_11_ytdl_web.py::test_a_real_tree_still_refuses_a_full_disk -> the control: passes at 40f931a and now  (ytdl-web-1)
- tests/test_bug_hunt_2026_09_11_ytdl_web.py::test_the_second_press_after_freeing_space_is_measured_fresh -> fails at 40f931a, passes now  (ytdl-web-2)
- tests/test_bug_hunt_2026_09_11_ytdl_web.py::test_a_heartbeat_from_a_machine_that_is_not_the_holder_is_410 -> fails at 40f931a, passes now  (ytdl-web-3)
- tests/test_bug_hunt_2026_09_11_ytdl_web.py::test_a_clip_status_from_the_wrong_machine_is_410 -> fails at 40f931a, passes now  (ytdl-web-3)
- tests/test_bug_hunt_2026_09_11_ytdl_web.py::test_the_manifest_is_refused_to_the_machine_that_is_not_the_holder -> fails at 40f931a, passes now  (ytdl-web-3)
- tests/test_bug_hunt_2026_09_11_ytdl_web.py::test_a_heartbeat_with_no_machine_id_is_the_older_companion -> the compatibility control: passes at 40f931a and now  (ytdl-web-3)
- tests/test_bug_hunt_2026_09_11_ytdl_web.py::test_a_holder_that_did_not_say_which_machine_is_not_evicted -> the compatibility control: passes at 40f931a and now  (ytdl-web-3)
- tests/test_bug_hunt_2026_09_11_ytdl_web.py::test_a_local_download_is_not_refused_by_the_servers_own_disk -> fails at 40f931a, passes now  (ytdl-web-4)
- tests/test_bug_hunt_2026_09_11_ytdl_web.py::test_a_job_created_under_the_widening_cannot_be_claimed -> fails at 40f931a, passes now  (ytdl-web-5)
- tests/test_bug_hunt_2026_09_11_ytdl_web.py::test_the_claim_door_is_the_one_that_refuses_it -> fails at 40f931a, passes now  (ytdl-web-5)
- tests/test_bug_hunt_2026_09_11_ytdl_web.py::test_the_free_space_cache_is_one_entry_per_filesystem -> fails at 40f931a, passes now  (ytdl-web-6)
- tests/test_no_em_dash.py::test_no_double_hyphen_in_editor_facing_strings -> fails at 40f931a on routes_api.py, ai_backend.py and attestation.py, passes now  (ytdl-web-7)

Run: `cd ytdl\web; ..\..\dashboard\.venv\Scripts\python.exe -m pytest tests/test_bug_hunt_2026_09_11_ytdl_web.py tests/test_no_em_dash.py tests/test_says_what_it_knows.py tests/test_local_download.py tests/test_attestation.py -q` -> 165 passed. The
"fails at 40f931a" half was measured against a `git archive HEAD` checkout of
`ytdl/web` in the scratchpad, with only the three test files copied in.
`tests/conftest.py` changed (see below), so `test_db.py`, `test_api.py`,
`test_dedupe.py`, `test_retry_failed.py` and `test_worker.py` were run too:
309 passed.

### OWED TO ANOTHER TERRITORY
- `companion/src/ccsync_companion/ytdl_executor.py`: the companion half of
  ytdl-web-3 - `machine_id` on the heartbeat body, on the clip-status body and
  as `?machine_id=` (or the `X-CCSync-Machine` header) on the manifest GET.
  The comp-ytdl-jobs builder owns it. Until it lands, the server behaves
  exactly as it does today: no field means per-editor, so nothing breaks and
  nothing is fixed either. DEPLOY ORDER: the dashboard first, always. A
  companion that sends the field to a dashboard that does not read it is
  ignored; a dashboard that reads it cannot be surprised by a companion that
  does not send it.
- `ytdl/web/tests/conftest.py` is shared ground inside this territory: its
  `clean_projects` fixture now re-creates the fixture PROJECT FOLDERS after
  wiping the tree, because since ytdl-web-1 an absent project folder means
  "the share is gone" and a root with no folders in it is not a tree.

### Owner decisions
- **The attestation's `TEXT_VERSION` was not bumped** for the punctuation-only
  rewording (ytdl-web-7). Bumping it is the module's own stated rule, and it
  would push every editor in every fleet back through the rights dialog for a
  colon. If you would rather keep the rule absolute, bump it to `2026-09-11.1`
  and delete the comment that explains the exemption.
- **ytdl-web-4 skips the server's disk gate for a local job rather than
  downgrading it to a warning the SPA shows.** The hunter's suggestion was a
  warning; a warning needs SPA work and a second wire field, and the number is
  already on the page via `sizeEstimate`. The cost of the smaller fix: a local
  job that NO companion claims falls back to the server worker with no
  free-space check ahead of it, and gets the per-clip errors that check was
  written to replace. Only reachable with `YTDL_LOCAL_DOWNLOAD` on, which the
  vendor build ships off.
- **A job created under the widening is now unclaimable** (ytdl-web-5). With
  the flag off this changes nothing, since no companion claims anything. With
  the flag on, an editor who unticks "on this machine" gets a server-side
  download, which is what unticking it means - but if you would rather the
  widening stayed a pure destination rule and machines could still claim,
  the refusal is one line in `db.claim_download`'s WHERE and one block in
  `routes_fleet.claim`.
