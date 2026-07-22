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
   relayed instead of direct.

4. **Run the matrix**:
   ```powershell
   .venv\Scripts\ccbench run --config bench.toml
   ```
   Runs every engine x lane x param-sweep x repeat combination sequentially,
   printing progress, and appends each result as one JSON line to
   `results/results.jsonl` (append-only). Re-running the same command is
   *resumable* -- combos already recorded are skipped; pass `--rerun` to
   force everything to run again. Use `--engines rclone_sftp,syncthing` or
   `--lanes A,B` to scope a run.

5. **Read the report**:
   ```powershell
   .venv\Scripts\ccbench report --results results\results.jsonl --out results\report.md
   ```
   Produces a markdown table per lane (best-of-repeats MB/s + verified
   flag), a "recommended per-lane config" section with the exact
   `rclone`/`robocopy` flags (or "use Syncthing as-is" for lane C), and a
   "did we beat Resolve Cloud" section comparing the winning MB/s against
   the ~60 mb/s baseline read both as Mbps and as MB/s (the unit Blackmagic
   quotes is ambiguous, so both are shown).

## How verification works

After a successful transfer, 3 randomly chosen files (seeded, so the same
3 files are checked across an A/B comparison) are re-hashed at the
destination and compared to the manifest's size + sha256. The `verified`
column in the report reflects this; a run that "succeeds" per the tool's own
exit code but fails the spot check is marked `verified=no` so it doesn't
quietly win a recommendation.

## Runner notes / known limitations

- **rclone** runners use an on-the-fly connection string
  (`:sftp,host=...,user=...,key_file=...:path` /
  `:smb,host=...,user=...,pass=...:share/path`) so editors don't need a
  pre-provisioned `rclone.conf`.
- `--multi-thread-streams` is dropped to `0` for "up" transfers -- it only
  helps rclone when it's the one writing the local destination file (a
  "down" transfer), and some backends don't support the parallel
  seek-writes at all; this is handled by direction, not by probing the
  backend at runtime.
- For "down" runs, the runner first does an untimed "seed" copy to make sure
  the remote side actually has the dataset (idempotent -- rclone/robocopy
  skip files that are already present and unchanged), then times only the
  download. For "up" runs, the remote destination is pre-cleaned (untimed)
  before each timed run so a repeat can't look artificially fast because the
  data was already there from the previous repeat.
- `keep_remote_data = false` (default) cleans up the NAS-side (or ephemeral
  syncthing) test data after each run; set `true` in `bench.toml` to leave
  it for manual inspection.
- **syncthing** runner spins up two ephemeral instances on loopback
  (temp config dirs, random high ports, relays/discovery/NAT disabled, one
  shared folder) and polls `/rest/db/status` for completion. This is fully
  self-contained by design (matches the selftest requirement) -- to actually
  benchmark a real editor<->NAS Syncthing pair over Tailscale later, the
  same device-pairing/REST logic would just need the loopback addresses
  swapped for real reachable ones.
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
