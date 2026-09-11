## Fleet page, [ COMPANIONS ]: one row, one headline, 2026-09-11

Not a hunt finding: the owner read the page and said what was wrong with it.
Verbatim: "this whole section is also very visually cluttered, clean it up",
and, mid-build, about his own laptop: "also having no projects synced should
not be an error. Alex laptop just happens to have no synced projects, not an
error".

What a row was, in this order and all at once: a red sentence (on one machine
the SAME sentence nested three times), a line of lane chips, a `direct:1`
chip, breaker chips, `CRASHES: N`, a "Resolve: connected" line, a SECOND line
of a dozen chips (`GPU 10G`, `VRAM`, `TRASH: 7.9 GB`, `CARDS v2130`,
`CARDS REFUSED`, `YOUTUBE IMPORT GAVE UP`, `2 NEED PROXIES`, `68 CLIPS OUTSIDE
THE TREE`, `2 STRAY PROJECT DIRS`, `DISK 4%`) with `[ ASK THIS COMPUTER WHY ]`
and `[ READ THE ANSWER ]` in among them, an expander, a version and a last
report. Nine rows of that is a wall, and the page's whole job is "is anything
red".

### The nested sentence, and where it came from

The string the owner read was:

    Nothing to sync: no project is ticked for this computer (No projects are
    ticked for this computer (Nothing to sync yet: no projects are ticked for
    this computer))

Three layers, three authors, each wrapping the one below it in brackets:

1. `companion/sync/sequencer.py::_describe_no_selection` writes a whole
   sentence for the tray (SYNC-116, 2026-09-04): "Nothing to sync yet: no
   projects are ticked for this computer". It used to be a fragment.
2. `companion/app.py`'s `blocked` composer for `no_selection` still treats
   that as a fragment: `"No projects are ticked for this computer" + f"
   ({detail})"`. Layer 2 around layer 1.
3. `dashboard/health.py::_why_first` appends the companion's
   `blocked_detail` to the dashboard's own sentence. Its only guard was
   `detail.lower() not in sentence.lower()`, a SUBSTRING test, which cannot
   see a restatement in other words. Layer 3 around layer 2.

The fix is at layer 3, because that is the layer every companion in the field
reports into: a build from two months ago still sends the nested detail, and
this dashboard now renders one sentence out of it. `health._detail_clause` is
the whole rule: `_unnest` drops a trailing parenthetical that merely restates
its own head (repeatedly, so N layers collapse), and the detail is dropped
whole when it says nothing the sentence has not said. The comparison
(`_says_the_same`) is content words, de-pluralised, with a deliberately small
noise list, and it is SYMMETRIC: the repetition arrived in both directions. A
detail that ADDS something (a path, an errno, a count) still rides along, which
is what it is for.

`no_selection` additionally never takes a detail at all (`WHY_DETAIL_IS_ECHO`):
the plan lives on this server, so a companion's words about it can only ever
be this sentence again.

Layers 1 and 2 are left alone on purpose: changing them means a companion
release, and the dashboard has to be correct for the builds already out there
either way.

### Nothing ticked is not an error

`no_selection` joined `upload_only` in `health.WHY_INFORMATIONAL` and its
sentence is now "Nothing ticked for this computer" (it used to wear the "Nothing
to sync:" lead-in of the fault sentences around it). It renders muted, the row's
dot is unchanged (it was never derived from `why`), and it counts toward no
total. A base rig holding no tick was already exempt (CR-28) and still is.

### What a row is now

- **ONE headline** (`health.fleet_headline`, composed in `build_editors_view`
  after the version comparison, because "out of date" is one of the things it
  can be). Ranked: a named fault (halt, breaker, sync engine down, clock,
  root, refused sign-in ...) > out of date > a lane in error > nothing ticked
  or upload-only > "Syncing" / "Idle, nothing owed". `level` is red / amber /
  muted, and MUTED IS THE NORMAL ROW: both "nothing to chase" states share it,
  so a row that is not muted is the one the eye lands on. The template ranks
  nothing.
- **Three lane chips, fixed order, fixed width** (`health.lane_strip`):
  upload, proxy download, folder sync, always all three, a lane nobody
  reported drawn as "not reported" rather than dropped (dropping it would
  shift the two beside it). A healthy lane is `chip lane quiet` - muted, not
  green-boxed. `direct:N` is a muted detail beside them; `[ RELAYED: n ]` is
  still a chip, because that one is a fault.
- **Everything else behind `[ DETAILS ]`**, a collapsed `<details>` with a
  `data-key` so base.html keeps the choice across the 15 s poll, rendered as a
  two-column label/value list: PROBLEMS (chips, only for things that are
  wrong), STORAGE, RESOLVE (the wave-3 line and its two clip lists),
  THIS COMPUTER (GPU, nvenc, whisper - facts, so muted values and not chips),
  WORK (the b-roll/music batches, the job link, volunteering, the cards role).
  A collapsed row that hides a real problem says so: `health.detail_notes`
  counts them and the summary reads "4 notes", with each one named in its
  title.
- **The buttons in a column of their own**, right-aligned, one line:
  `[ RESUME ]`, `[ ASK THIS COMPUTER WHY ]`, `[ READ THE ANSWER ]` and their
  waiting-chips. Routes, `hx-target`, `hx-swap` and every form field are
  untouched; `[ UPDATE NOW ]` is not here (it lives on Settings, Packages).
- **Version**: the version plus `[ OUT OF DATE: x ]` only when it is, as
  before. Last report as before.

### Files

- `dashboard/src/ccsync_dashboard/health.py` - `_echo_words`,
  `_says_the_same`, `_unnest`, `_detail_clause`, `WHY_DETAIL_IS_ECHO`,
  `no_selection` in `WHY_INFORMATIONAL` and its new sentence, `lane_strip`,
  `_lane_fault`, `fleet_headline`, `detail_notes`
- `dashboard/src/ccsync_dashboard/api.py` - `build_editors_view` composes
  `lane_strip` and `headline` onto each row
- `dashboard/src/ccsync_dashboard/ui.py` - `_fleet_view` composes `notes`
  (it needs the Resolve detail attached one line above it)
- `dashboard/templates/partials/fleet_grid.html` - the COMPANIONS table
- `dashboard/static/style.css` - `.why-line.amber/.muted`, `.lane-strip`,
  `.chip.lane.quiet`, `.lane-detail`, `details.row-details`,
  `.row-detail-list`, `td.row-actions`, and the phone overrides for the last
  two inside the existing `table.stack` block

### Verification

From `dashboard` with `.venv\Scripts\python.exe -m pytest <file> -q`.

New: `tests/test_fleet_grid_declutter_2026_09_11.py` (11) - the owner's exact
triple-nested string collapses to one sentence; a self-nested detail is
un-nested and still appended once; a detail that adds evidence survives; the
headline priority (a tripped breaker beats out of date beats nothing ticked);
a lane in error is the headline when nothing outranks it; a quiet row says so
quietly; the three lanes are always the same three in the same order; a
healthy row carries no coloured chip at all; nothing ticked is muted, with no
red line, no coloured chip and no red dot; the clutter is behind one collapsed
expander with a note count; the buttons are a column.

Updated: `tests/test_health.py` (the lead-in list, and the informational set is
now two); `tests/test_bug_hunt_2026_09_11_dash_mounts_ui.py` (the Resolve line
is the RESOLVE row inside [ DETAILS ] now).

Run: `test_fleet_grid_declutter_2026_09_11.py`, `test_health.py`,
`test_bug_hunt_2026_09_11_dash_mounts_ui.py`,
`test_templates_wave3_2026_09_04.py`, `test_report_endpoint.py`,
`test_diagnostics.py`, `test_mobile_fleet.py`, `test_mobile_admin.py`,
`test_broll_ingest_report.py`, `test_music_ingest_report.py`,
`test_capabilities_report.py`, `test_cards_capability.py`, `test_packages.py`,
`test_release_channel.py`, `test_fleet_halt.py`, `test_multi_machine.py`,
`test_report_ingest_health.py`, `test_help_page.py`, `test_jobs_cancel.py`,
`test_sweep_2026_09_04_copy.py`, `test_sweep_2026_09_04_second_customer.py`,
`test_no_em_dash.py` - all green.

### Owner decisions

- The chips that were on the second line are all still rendered, inside
  [ DETAILS ], with their text, colour and `title` unchanged. Deleting any of
  them is a decision about what the fleet does not need to say, and this
  change is about where it is said.
- A capability (GPU, nvenc, whisper) is a muted value, not a chip: a chip on
  a fact is what the second line was. A live state (a batch, a job, the cards
  role, volunteering) keeps its chip and its colour, because those are
  states.
- The lane strip is fixed-width on a desktop and free-flowing on a phone:
  three 8.5 rem chips at 320 px would be the horizontal scroll MOBILE_PLAN.md
  M2 exists to prevent.

### Owed to another territory

- `companion/app.py`'s `no_selection` detail (layer 2 above) still composes
  "<its own sentence> (<the sequencer's sentence>)". The dashboard renders one
  sentence from it either way, and the TRAY may well read the same repetition
  somewhere. Worth a look in the companion's next pass; it is not fixed here,
  because a companion change is a release and this one must be correct for
  the builds already in the field.
- `[ UPDATE NOW ]` was not touched: it belongs to Settings, Packages, which
  another builder holds today.
