# ccbench -- sync-transport benchmark harness

Picks the fastest transfer engine per Creators Club sync lane (see
`../SPEC.md` §"Architecture") for editors syncing with the TrueNAS box, and
verifies whether the Tailscale path is direct or DERP-relayed before
trusting any transfer number. Target to beat: Blackmagic Cloud's observed
~60 mb/s.

Three lanes, per SPEC.md:

| Lane | Content | Direction |
|---|---|---|
| A | video originals | editor -> NAS (up) |
| B | proxies | NAS -> editor (down) |
| C | everything else (audio/GFX/AE/subs/stills) | bidirectional |

Engines benchmarked: `rclone` (SFTP backend), `rclone` (SMB backend), raw
`robocopy` (Windows SMB baseline), `syncthing` (event-driven, lane C
candidate), and `iperf3` (raw network ceiling + Tailscale path check).

## Setup

```powershell
cd bench
python -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
```

No third-party runtime dependencies -- Python 3.12's stdlib `tomllib` reads
the config, `argparse`/`subprocess`/`urllib` handle the rest. `pytest` is
only needed for the test suite.

## Quick start: does the harness itself work here?

```powershell
.venv\Scripts\ccbench selftest
```

Runs a miniature matrix entirely on this machine with no network calls: a
tiny synthetic dataset, `robocopy` against a local directory (Windows),
`rclone` local<->local if `rclone` is on PATH, an ephemeral `syncthing` pair
on loopback if the binary is present, and a local `iperf3` client/server pair
if `iperf3` is present. Anything missing shows up as a one-line "skipped:
reason" row instead of failing. Add `--workspace DIR --keep` to inspect the
generated data/results/report afterwards instead of using a throwaway temp
dir.

## Real benchmark run against the NAS

1. **Generate datasets** (once; reuse across repeated `run`s):
   ```powershell
   .venv\Scripts\ccbench dataset --out data\large --profile large   # 3 x 4 GiB, incompressible, .braw/.mov
   .venv\Scripts\ccbench dataset --out data\small --profile small   # 400 files, 50 KiB-20 MiB, nested 3 deep
   ```
   Both are deterministic for a given `--seed` (default 1337) and write a
   `manifest.json` (path/size/sha256 per file) alongside the data, used later
   for post-transfer verification.

2. **Fill in `bench.toml`** (copy `bench.toml.example`): NAS Tailscale
   host/user/key for the SFTP lane, host/share/user for the SMB lane (put the
   password in an env var, referenced by name via `password_env` -- never in
   the file), the UNC path for the raw robocopy baseline, and the iperf3
   host. See the comments in `bench.toml.example` for every field.

3. **Check the network path first** -- a DERP-relayed Tailscale connection
   will cap throughput well below 60 mb/s regardless of which transport you
   pick, so check this before spending time on the transport matrix:
   ```powershell
   .venv\Scripts\ccbench tailscale-check --peer <nas-tailnet-hostname-or-ip>
   ```
   This only queries the local `tailscaled` daemon's cached peer state (no
   packets sent to the peer) and prints a loud warning if the path is
   relayed instead of direct. **Direct is decided by `CurAddr` being
   non-empty**, not by `Relay` being empty: tailscaled reports a peer's home
   DERP region in `Relay` even when the connection is a direct UDP path, so
   the region name is shown as supplementary detail only.

4. **Run the matrix**:
   ```powershell
   .venv\Scripts\ccbench run --config bench.toml
   ```
   Runs every engine x lane x param-sweep x repeat combination sequentially,
   printing progress, and appends each result as one JSON line to
   `results/results.jsonl` (append-only). Re-running the same command is
   *resumable* -- combos that already produced a **measurement** are skipped,
   and combos that were skipped (missing binary, unsupported direction) or
   failed (timeout, short transfer, runner crash) are **retried**: install the
   missing syncthing, re-run, and the lane-C cells actually get measured.
   `--rerun` re-runs even the good ones. Use `--engines rclone_sftp,syncthing`
   or `--lanes A,B` to scope a run. The iperf3 sweep belongs to the synthetic
   lane `net`, so `--lanes A,B` skips it and `--lanes net` runs only it.
   Remote scratch cleanup still happens at the end of a fully-resumed run,
   even when every combo was already recorded.

   **Re-measuring after you change something** (a NAS tuning change, a new
   NIC): the file is append-only, so `--rerun` puts the new numbers in the same
   median as the old ones -- 2 repeats at 380 MB/s plus 2 at 760 report as
   ~570 MB/s, `n 4/4`. Either point `--results` at a fresh file, or use
   `ccbench report --since` below. The report flags any combo whose repeats
   span more than a few hours, so a blend is visible either way.

5. **Read the report**:
   ```powershell
   .venv\Scripts\ccbench report --results results\results.jsonl --out results\report.md
   ```
   Produces a markdown table per lane (**median** MB/s across repeats, with
   min/max/n, how the bytes were counted, how verification was done, and a
   loopback flag), a "recommended per-lane config" section with the exact
   `rclone`/`robocopy` flags (or "use Syncthing as-is" for lane C), and a
   "did we beat Resolve Cloud" section comparing the winning MB/s against
   the ~60 mb/s baseline read both as Mbps and as MB/s (the unit Blackmagic
   quotes is ambiguous, so both are shown).

   `--since 24h` (or `7d`, or an ISO date like `2026-08-14`) cuts the history
   at a known event so a median cannot span it; the window is printed in the
   report itself. Rows whose repeats span more than a few hours are marked
   `BLENDED` in the Notes column and in the winner's caveats, and a row whose
   clock is coarse relative to what it timed (the syncthing pair polls rather
   than brackets, so both ends of its interval land on a poll) says so as
   instrument error instead of leaving it to look like variance.

## Nothing here deletes anything outside a `_bench` path

Every `rclone purge` / `rmtree` this harness performs goes through
`ccbench/guard.py`, which refuses any target whose path has no `_bench`
component. A `remote_path`/`unc_path`/`work_dir` edited down to
`Creators_Club` therefore fails the run loudly instead of purging real project
media. The single override is explicit:
`ccbench run --allow-destructive-endpoint` (or
`[general] allow_destructive_endpoint = true`), and the run prints a warning
when it is on.

## How the numbers are kept honest

- **Bytes are what the tool says it moved**, not the dataset manifest total:
  rclone's own `stats.bytes` (via `--use-json-log`), robocopy's `Bytes :`
  summary, the size of what actually landed for syncthing. If that can't be
  parsed the manifest total is substituted and the row's `bytes_source` says
  `manifest-fallback`. A run that moved 0 bytes -- **or materially less than
  the dataset holds** -- is recorded as a **failure**, because timing a
  transfer into a destination that was already (partly) warm measures nothing.
  A partial row is the dangerous one: it looks fast *and* passes the
  presence+size verification of whatever did land.
- **The download destination is emptied before every timed "down" run**
  (guarded), so a warm destination can't make rclone/robocopy skip everything.
  `rmtree` can leave files behind without complaining, so the result is
  checked and the run fails if anything survived. Likewise a pre-clean
  (`rclone purge`) that timed out fails the run instead of being assumed to
  have worked.
- **Syncthing completion needs the index, not just an idle folder.** An empty
  folder that has just been added is idle with `needBytes == 0` before it has
  heard from the peer; the runner waits (untimed) for the pair to connect and
  requires `globalBytes` to have reached what was seeded before it believes a
  zero.
- **Credentials never reach `results.jsonl` or the report.** rclone's SMB
  connection string carries `pass=<obscured>`, and `rclone obscure` is
  reversible with `rclone reveal` -- so every path that could echo a remote
  spec onto a result row (guard refusals, cleanup failures, rclone's own
  stderr) goes through `guard.redact()` first.
- **The untimed "seed" copy that populates the remote for a "down" run fails
  the run** on a non-zero exit or a timeout, instead of being swallowed.
- **Remote cleanup happens once, after the whole matrix**, never between two
  timed runs -- purging several GB on the NAS warms its ARC for whatever runs
  next.
- **MB/s is decimal** (bytes / 1e6 / s) everywhere, so 60 Mbps is exactly
  7.5 MB/s.
- **The report shows the median of the repeats**, with min/max as columns;
  best-of-N rewards whichever repeat got the luckiest cache.
- **The lane comes from `bench.toml`** and is carried on every result row; it
  is never re-derived from a dataset name.
- **A runner crash fails one cell**, recorded as an `ok=false` row with the
  traceback tail; the rest of the matrix still runs.

## How verification works

- **Downloads**: 3 randomly chosen files (seeded, so the same 3 files are
  checked across an A/B comparison) are re-hashed at the destination and
  compared to the manifest's size + sha256 (`verify_method =
  spot-check-sha256`).
- **Uploads**: the destination is listed back (`rclone lsjson -R`, or a
  directory walk for robocopy) and every manifest file must be present with
  the right size (`remote-size-listing`). If the listing itself is
  unavailable the row is marked `verified=no` with
  `verify_method=exit-code-only` -- an exit code alone is never reported as
  verification.

A run that "succeeds" per the tool's own exit code but fails verification is
marked `verified=no`, and the report only picks a verified winner when one
exists.

## Loopback rows are not comparable

The syncthing runner benchmarks two ephemeral instances on 127.0.0.1, and the
`local_test_dir` selftest escape hatch makes rclone/robocopy copy disk-to-disk
on this machine. Every such row carries `loopback=true`, is shown as
`YES -- not comparable` in the report's Loopback column, and can only become a
lane winner if no real-network row exists for that lane (in which case the
recommendation says so in bold).

## Runner notes / known limitations

- **rclone** runners use an on-the-fly connection string
  (`:sftp,host=...,user=...,key_file=...:path` /
  `:smb,host=...,user=...,pass=...:share/path`) so editors don't need a
  pre-provisioned `rclone.conf`.
- `--sftp-chunk-size` is configured in **KiB** (`sftp_chunk_size_kib`). SFTP's
  maximum total packet is 256 KiB, so 255 is the largest usable value and the
  one that matters on a high-RTT link; rclone's default is 32 KiB. The old
  megabyte key (`sftp_chunk_size_mb`) is rejected with an error rather than
  silently reinterpreted.
- `--multi-thread-streams` is swept in **both** directions for `rclone_smb`
  (the SMB backend can multi-thread uploads) and for "down" on `rclone_sftp`.
  It is pinned to an explicit `0` only for SFTP "up", where the backend cannot
  use it at all -- and that appears in the recorded params, so it is never a
  silent zero.
- For "down" runs, the runner first does an untimed "seed" copy to make sure
  the remote side actually has the dataset (idempotent -- rclone/robocopy
  skip files that are already present and unchanged) and **fails the run if
  that seed errors or times out**, then empties the local destination and
  times only the download. For "up" runs, the remote destination is
  pre-cleaned (untimed) before each timed run so a repeat can't look
  artificially fast because the data was already there.
- `keep_remote_data = false` (default) cleans up the NAS-side (or ephemeral
  syncthing) test data **once, after the whole matrix**; set `true` in
  `bench.toml` to leave it for manual inspection.
- **syncthing** runner measures one direction at a time: it seeds one side and
  times the other receiving it. `direction = "bidirectional"` is therefore
  **rejected** (a skipped row saying so) rather than measured one-way under a
  two-way label -- use `direction = "both"`, which produces separate `up` and
  `down` rows.
- **syncthing 1.x and 2.x are both supported, by detection.** v2 reorganised
  the CLI (the daemon needs the `serve` subcommand, `generate` lost
  `--no-default-folder`, `--device-id` became a `device-id` subcommand, and
  config/database are two directories). The runner probes
  `syncthing --version` once per binary, caches the major, and picks the
  matching command shape; an unrecognised major is a **skipped** row with a
  clear message rather than a guess, because a daemon started with flags it
  silently reinterprets would produce a row that looks measured. Only process
  spawning and config generation differ -- the REST endpoints the measurement
  depends on are identical on both. On v2 the runner passes an explicit
  `--data` inside its temp workspace, so a bench run never writes into the
  machine's real syncthing database.
- **syncthing** runner spins up two ephemeral instances on loopback
  (temp config dirs, random high ports, relays/discovery/NAT disabled, one
  shared folder) and polls `/rest/db/status` for completion. This is fully
  self-contained by design (matches the selftest requirement) -- to actually
  benchmark a real editor<->NAS Syncthing pair over Tailscale later, the
  same device-pairing/REST logic would just need the loopback addresses
  swapped for real reachable ones. Until then **every syncthing row is
  `loopback=true` and is not comparable** with the rclone/robocopy rows.
- **iperf3** direction "down" uses `-R` (server sends). The `sum_received`
  field of iperf3's own JSON output is used for goodput (bytes/seconds), so
  the reported MB/s is what the receiver actually got, not the sender's
  attempted rate.
- If a binary (`rclone`/`robocopy`/`syncthing`/`iperf3`) isn't found, its
  runner returns a `skipped` result with a one-line reason instead of
  raising -- the matrix always completes and the report just shows those
  rows as skipped.

## Layout

```
bench/
  ccbench/
    cli.py            argparse entry point (ccbench dataset|run|report|selftest|tailscale-check)
    dataset.py         synthetic dataset generator (large/small/both profiles) + manifest.json
    config.py          bench.toml loader (stdlib tomllib, path resolution)
    guard.py           scratch-path guard: no purge/rmtree outside a "_bench" path
    matrix.py           orchestrates the engine x lane x param x repeat matrix, resumable JSONL
    report.py           results.jsonl -> markdown report + per-lane recommendation
    result.py           RunResult dataclass + JSONL append/read/resume helpers
    selftest.py          local-only end-to-end acceptance test
    runners/
      base.py            shared helpers (which(), spot_check, subprocess wrapper, ...)
      _rclone_common.py  shared rclone plumbing (param matrix, transfer, cleanup)
      rclone_sftp.py
      rclone_smb.py
      robocopy_smb.py    Windows-only, raw SMB baseline
      syncthing.py       ephemeral loopback pair
      iperf3.py           network ceiling + tailscale direct/DERP check
  tests/                 pytest suite (dataset determinism/incompressibility, resume logic,
                          report rendering, param-matrix expansion, runner integration)
  bench.toml.example     annotated example config
  data/, results/, work/ generated at runtime (not committed data itself, just the dirs)
```
