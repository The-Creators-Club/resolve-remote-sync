# ops-server - server/ operator scripts (except install_dashboard_app.py) and bench/
Files read (approximate coverage): server/common.py (SSH/SFTP/REST/RPC transport, host-key pinning, snapshot_before, cli - about 60%), server/publish_db.py (all), server/broll_drain.py (all), server/check_health.py (all), server/setup_tree.py (build_remote_script + main), server/setup_editor_account.py (all), server/setup_syncthing_folder.py (main, marker read), server/backends/truenas.py (restart/container_exec, set_tree_acl, snapshots, home perms), server/backends/synology.py (root_cmd/PATH_EXPORT, container_exec, snapshots), server/truenas_rpc.py (pooling/REST-only cache), install_dashboard_app.py helpers that publish_db calls (build_db_swap_script, run_ssh_guarded, make_staging_dir, prune_orphaned_staging) read only to trace publish_db; bench/ README, runners/_rclone_common.py, CI wiring; docs/SERVER.md (grep), docs/BACKUP_RESTORE.md sections 1, 6, 8; dashboard provision.py folder config (parity check only).
Probes run:
- check_health.py against an unreachable NAS (scratch site.toml, TRUENAS_HOST=127.0.0.1, CCSYNC_SSH_PORT=59999 with nothing listening, fake pinned key, HOME/known_hosts/snapshot log redirected to scratch): traceback out of check_tailscale, exit 1, checks 2b-7 never ran.
- publish_db local half on a scratch copy of the real b-roll index (E:\broll-queue\broll.db, 501 MB, 25,578 videos / 62,160 segments / 91,821 embeddings): sqlite backup 1.96 s, quick_check + counts 2.10 s, user_version 1 ms.
- zlib level 1 on 8 x 8 MB samples of the same file: 0.615 ratio, 1.18 s per 64 MB (compression is not worth adding - see "already good").
- Read paramiko 3.x channel.py in the dashboard venv: DEFAULT_WINDOW_SIZE = 2 MiB, window replenished only by recv/recv_stderr (_check_add_window).

## Findings

### ops-server-1 - Pre-op snapshots (`ccsync-pre-*`) never expire, so nothing deleted after one is ever freed
- Category: disk-growth
- Severity: medium
- Confidence: CONFIRMED
- Where: server/common.py:2406 (snapshot_before), server/backends/truenas.py:955-989 (snapshot/snapshot_now), server/backends/synology.py:1241-1271, server/setup_tree.py:288, server/setup_snapshots.py (no prune), docs/BACKUP_RESTORE.md:116
- What: every setup_tree run takes a ZFS snapshot of the whole tree dataset, and every deploy one of the apps dataset (install_dashboard_app.py:6634), named `ccsync-pre-<label>-<ts>`. No code anywhere in the repo destroys a `ccsync-pre-*` snapshot (grep of server/, dashboard/src, companion/src, tools/ for `zfs destroy`, `pool.snapshot.delete`, `ccsync-pre`: only the creator). The runbook's retention column says "until the pool prunes them by hand"; ZFS prunes nothing by itself. A snapshot pins every block deleted or rewritten after it, so the oldest setup_tree pre-op snapshot holds every project, proxy and render deleted from the tree since that day.
- Cost / failure scenario: setup_tree runs once per new project (about 100 projects today, 500 at commercial scale); a deploy runs several times a week. Deleting a finished 1-2 TB project after delivery frees zero bytes while any older pre-op snapshot exists, and the hourly/daily floor (24 h / 30 d) gives no hint, because the space is charged to an unnamed manual snapshot. On the apps dataset each deploy's snapshot pins the `app.old.<ts>` tree and the music artefacts (up to 1.4 GB) the NEXT deploy prunes, plus the `/data/backups` rotation (8 GB cap) and dashboard.db churn: estimated several GB per month at today's deploy rate, unbounded over the product's life. Pool full is the outcome the scheduled retention exists to prevent.
- Evidence: code read above; BACKUP_RESTORE.md table row "pre-op ... until the pool prunes them by hand"; KNOWN_BUGS.md:10233 and :30084 name live pre-op snapshots on `tank` and `tank/TheCreatorsPool`. On DSM the description is the bare label (`setup_tree`, `deploy`), not the `ccsync-pre-` name TrueNAS uses (synology.py:1263 passes `desc=label`; truenas delegates to snapshot_now with the prefixed name), so the two backends have drifted and a DSM pre-op snapshot cannot even be identified for pruning.
- Ledger: new (related to PL-RES-109 (open), which is about the SCHEDULED snapshots pinning churn; those at least expire)
- Suggested change: give pre-op snapshots a retention: in snapshot_before, in the SAME ssh call as the `zfs snapshot`, destroy `<dataset>@ccsync-pre-*` older than 30 days (the daily floor's horizon), never the newest one per label, never one with a `ccsync:keep` user property; or add the same sweep as a step of setup_snapshots.py --apply. On DSM pass the `ccsync-pre-<label>-<ts>` name as the description (make synology.snapshot() delegate to snapshot_now() like truenas does). Must not break: "a point-in-time behind every recursive op" - 30 days is longer than any of the documented "someone notices" windows except the index publish, which has its own `.prev`.
- Effort / risk: S effort; low risk (only destroys snapshots this code created and named, past the documented floor)

### ops-server-2 - check_health.py dies with a traceback when the NAS is unreachable, skipping every later check
- Category: resilience
- Severity: medium
- Confidence: CONFIRMED
- Where: server/check_health.py:612-621 (main), :246-250 (check_tailscale), :399-404 (check_tree), :465 and :493 (check_editor_accounts); same class in server/setup_tree.py:291 and server/write_marker.py:82/:182
- What: check_tailscale calls backend().tailscale_status_json -> container_exec -> run_ssh with no guard, check_tree calls run_ssh with no guard, and check_editor_accounts calls truenas_api, which raises requests.ConnectionError on an RPC transport error. cli() catches only EnvError and NotImplementedError. The script's own rule (line 364: "A health CHECK must not crash on the thing it is checking") is applied to the Syncthing and dashboard checks only.
- Cost / failure scenario: the moment an operator runs the health check is when something is down. NAS sshd unreachable -> traceback after check 1; the local tailnet-path check (2b), Syncthing (3/4), the SFTP-transport check and the dashboard check (7) never run, and the exit code is 1 (Python's uncaught-exception code), which by the documented contract ("exit code = number of failed checks") reads as "one check failed". Same for setup_tree.py: a dropped channel after the snapshot is taken prints a traceback and no snapshot verdict line.
- Evidence: probe - scratch site.toml, TRUENAS_HOST=127.0.0.1, CCSYNC_SSH_PORT=59999 (nothing listening), pinned throwaway key: output is the postgres skip line then `paramiko.ssh_exception.NoValidConnectionsError: [Errno None] Unable to connect to port 59999 on 127.0.0.1` raised from check_health.py:613 -> truenas.py:151 -> common.py:1542; process exit 1.
- Ledger: new
- Suggested change: in main(), run each check through a small wrapper that turns any exception into `report(False, "<check>: could not run (<ExcType>: <msg>)")` and carries on; use run_ssh_guarded (or catch) in setup_tree.py/write_marker.py so a dropped channel ends in a FAILED line plus snapshot_verdict(). Must not change the PASS/FAIL contract or the exit code meaning.
- Effort / risk: S effort; low risk

### ops-server-3 - publish_db on Synology runs the swap without the DSM PATH, so `docker exec` and `synoacltool` are not found and every publish is refused
- Category: bug
- Severity: medium
- Confidence: CONFIRMED (by code read; not run on a DSM box)
- Where: server/publish_db.py:946-947 (swap), :675-676 (rollback); server/backends/synology.py:63-72 (PATH_EXPORT), :178-186 (root_cmd)
- What: the Synology backend's own comment says docker (/usr/local/bin) and the syno CLIs (/usr/syno/bin) are "none of which are on sudo's PATH on a stock DSM box", which is why every other privileged DSM command goes through backend.root_cmd (PATH_EXPORT + sudo /bin/sh -c). publish_db builds `'echo "$SUDO_PW" | sudo -S sh -c ' + swap` itself. The swap's integrity step (quick_check_snippet) runs `docker exec <ctr> python3 ...`, then falls back to a host python3, which the same module says DSM does not have. The acl line `synoacltool -copy` fails the same way (non-fatal, NOTE only).
- Cost / failure scenario: `publish_db.py --which broll --apply` on a Synology site: upload and drain succeed, then the swap exits 11 ("PRAGMA quick_check on the staged broll.db did not answer ok") every time - safe (live index untouched) but the b-roll index can never be published on DSM. The operator's only way through is `--no-integrity-check`, which also leaves the new file without its ACL copied (synoacltool still not found), i.e. possibly unwritable by the container (ingest pushes fail) or world-writable under DSM's `internal-sftp -u 000`.
- Evidence: publish_db.py:947 and :676 vs synology.py:185-186; read_live_counts/take_drain/apply_drain DO work on DSM because they go through backend.container_exec -> _root -> root_cmd (synology.py:372-374), so the failure is confined to the two hand-built sudo lines. No server test runs the swap through a Synology backend (grep of server/tests for publish_db + synology: only install_identity and staging_parent are covered).
- Ledger: new
- Suggested change: wrap both scripts with the backend's privileged form when it has one: `cmd = backend.root_cmd(swap) if hasattr(backend, "root_cmd") else 'echo "$SUDO_PW" | sudo -S sh -c ' + shell_quote(swap)`. TrueNAS output stays byte-identical. Add a test that renders the Synology swap and asserts PATH_EXPORT precedes `docker exec`.
- Effort / risk: S effort; low risk

### ops-server-4 - The Syncthing API key and GUI password are taken on the command line, and the runbook tells operators to type them there
- Category: security
- Severity: medium
- Confidence: CONFIRMED
- Where: server/setup_syncthing_folder.py:331, server/accept_device.py:119, server/check_health.py:587, server/secure_syncthing_gui.py:174-177 (`--api-key`, `--password`); docs/SERVER.md:579, :669, :733 (`--api-key <syncthing-api-key>`); check_health.py:5 docstring
- What: the repo's own rule is that secrets never go on a command line (ccsync CLAUDE.md on TRUENAS_PW; SEC-2 moved the sudo password to stdin; sftp_put_text keeps the .env out of argv), and tools/load_secrets.ps1 already supplies SYNCTHING_API_KEY from DPAPI. These four scripts still accept the key (and the GUI password) as argv, and the operator runbook's three copy-paste lines put it there.
- Cost / failure scenario: every onboarding (accept_device, once per editor machine) and every hand-provisioned project writes the key into PowerShell's PSReadLine history (`%APPDATA%\Microsoft\Windows\PowerShell\PSReadLine\ConsoleHost_history.txt`, plaintext, kept indefinitely) and into the process list for the run. The key is full control of the NAS Syncthing: share any project folder to any device id, i.e. the whole tree. At commercial scale it is one leaked file per customer admin workstation.
- Evidence: the four argparse lines and three SERVER.md lines above; docs/SECRETS.md lists SYNCTHING_API_KEY as a load_secrets-managed secret.
- Ledger: new
- Suggested change: change the runbook lines to rely on the environment (`. .\tools\load_secrets.ps1` first); keep `--api-key` working for compatibility but print a one-line warning when it is used, and make `secure_syncthing_gui --password` read from getpass/env instead of argv (it already generates one when absent). Must not break the env-var fallback every script already has.
- Effort / risk: S effort; low risk

### ops-server-5 - One full SSH connect + password auth per remote command: 7 handshakes for a b-roll publish, 3 for a new project, one of them redundant
- Category: perf
- Severity: low
- Confidence: CONFIRMED (count); cost estimated
- Where: server/common.py:1593-1609 (run_ssh opens and closes a paramiko client per call), :1631 (sftp_put_text), server/publish_db.py:827, :864, :876, :888-889, :914, :946, :962; server/setup_tree.py:288-291 (via truenas.py:933 and :979)
- What: run_ssh builds a new SSHClient (TCP connect, key exchange, host-key check, password auth) for every command. `publish_db --which broll --apply` on TrueNAS makes 7 separate connections (live counts, mktemp, SFTP upload, `wc -c`, drain export, swap, drain apply; 8 on DSM with the staging prepare); setup_tree makes 3 (df dataset probe, zfs snapshot, the script). The `wc -c` round trip (publish_db.py:888) re-checks a size the swap script checks again on the `.new` copy one step later (install_dashboard_app.py:4257-4260, same `exit 8` message class).
- Cost / failure scenario: estimated 0.3-0.6 s per handshake on the LAN and 1-2 s over a DERP-relayed tailnet (an admin away from the studio): about 2-4 s per publish locally, up to ~14 s relayed, out of a run whose local half measured 4 s. Each password auth also lands in the NAS auth log. Small, but it is the per-run fixed cost of every script in the package and it grows with every step added.
- Evidence: call sites above; the TrueNAS REST/RPC half already solved the same problem with a pooled, reused session (truenas_rpc.py:543-612, "a fresh login per poll ... TrueNAS rate-limits").
- Ledger: new
- Suggested change: cache one connected client per (host, port, user) in common.py for the life of the process (closed atexit), with run_ssh reopening once if the transport is not active; keep the password-on-stdin per command and the host-key policy exactly as is. Drop the separate `wc -c` call in publish_db (the swap's own check covers it) or fold it into the drain call.
- Effort / risk: S-M effort; low risk (tests patch run_ssh, not ssh_client)

### ops-server-6 - run_ssh reads stdout to EOF before touching stderr: more than 2 MiB of stderr wedges the call until the inactivity timeout
- Category: bug
- Severity: low
- Confidence: PLAUSIBLE
- Where: server/common.py:1604-1606
- What: `out = stdout.read()` then `err = stderr.read()`. paramiko's flow-control window (2 MiB, DEFAULT_WINDOW_SIZE = 64 * 2**15) is shared by both streams and only replenished when data is read (Channel._check_add_window from recv/recv_stderr). If the remote writes more than 2 MiB to stderr before closing stdout, the remote blocks on write, stdout never reaches EOF, and the read sits until the channel's inactivity timeout (120 s default), then raises socket.timeout.
- Cost / failure scenario: setup_tree's `chown -R` (truenas.py:836) and the publish swap's `cp -a` print one stderr line (~100-150 bytes) per failing file; a re-run of setup_tree over an existing 20k+ file project on a dataset that refuses ownership changes (the aclmode=restricted case the same code already anticipates for chmod) emits several MB, so the run hangs for 120 s and then tracebacks (setup_tree uses unguarded run_ssh) instead of reporting what failed. Rare at today's scale, likelier with larger trees.
- Evidence: paramiko 3.x source in the dashboard venv (common.py:232, channel.py:701/:749/:1274); call order in run_ssh.
- Ledger: new
- Suggested change: drain both streams concurrently (a small loop on channel.recv_ready()/recv_stderr_ready(), or read stderr on a helper thread), keeping the (rc, out, err) contract; or cap remote stderr at source for the recursive steps (`2> >(tail -c 64k >&2)` is bash-only, so prefer the client-side fix).
- Effort / risk: S effort; low risk

### ops-server-7 - The 500 MB b-roll index is staged in /tmp on TrueNAS, the place the deploy moved its big artefacts away from
- Category: resilience
- Severity: low
- Confidence: PLAUSIBLE
- Where: server/publish_db.py:593-609 (staging_parent returns "/tmp" on every non-DSM backend), :864-865
- What: install_dashboard_app.make_staging_dir's own docstring (OPS-8) says /tmp on the NAS "may be RAM-backed" and stages the 1.4 GB music artefacts under `<apps root>/staging` instead. publish_db stages broll.db, now 501 MB (measured; 25,578 videos, 5x the brief's working figure), in /tmp on TrueNAS, and leaves it there on every failure path by design until a later deploy's prune_orphaned_staging (>= 2 h old) removes it.
- Cost / failure scenario: one publish puts 0.5 GB in /tmp for the length of the run; two failed retries in an afternoon hold 1-1.5 GB there until the next deploy. If /tmp is tmpfs or a small boot-pool, that is RAM or boot-pool space taken from the middleware; at commercial archive sizes (20k+ clips, ~2 GB index) a single publish can ENOSPC /tmp.
- Evidence: publish_db.py:608-609; install_dashboard_app.py:5244-5247 and 5272-5276 (OPS-8 text); measured index size. Whether /tmp is RAM-backed on the studio's TrueNAS was not checked (no NAS access).
- Ledger: related to OPS-8 / SERVER-5 (fixed for the deploy, not applied to publish_db on TrueNAS)
- Suggested change: use `<apps root>/staging` on TrueNAS too (staging_parent's DSM branch already builds it and prune_orphaned_staging already sweeps it); the `ccsync-*-upload.*` glob already matches publish_db's slug.
- Effort / risk: S effort; low risk

### ops-server-8 - bench/ no longer measures the lanes the companion ships, yet is installed and tested on every CI run
- Category: streamline
- Severity: low
- Confidence: CONFIRMED
- Where: bench/ccbench/runners/_rclone_common.py:121-127; .github/workflows/ci.yml:206-214
- What: the harness's rclone flag set is `--transfers`, `--multi-thread-streams`, `--sftp-chunk-size`. The shipped lanes now also depend on `--sftp-concurrency` (CR-364: the DSM 64Ki/16 rule that decides whether a >514 MiB proxy arrives whole), and lane B's WebDAV/remote_down route with pinned `--multi-thread-cutoff` (rclone_lane.py:689-711); bench can sweep neither, and it imports nothing from the companion, so nothing makes it notice. Last code change 2026-09-18; it has not been used to choose a setting since the August transport decisions (estimated, no results committed).
- Cost / failure scenario: every CI run builds bench/.venv from its lock and runs its 14 test files (estimated 30-60 s of runner time per push) for a tool whose answers would not reproduce the CR-364 failure or evaluate the WebDAV route. A benchmark that silently omits the decisive knob is worse than none when someone next uses it to "prove" a chunk size.
- Evidence: the flag builder above vs companion rclone_lane.py:427-428, :643-645, :706-711; CI steps above.
- Ledger: new
- Suggested change: either add `sftp_concurrency` (and a remote/WebDAV endpoint kind) to the param matrix, or move bench/ to `legacy\` per the tree's retire-not-delete rule and drop its two CI steps and its row in run_all_tests.ps1 / CLAUDE.md. Keep check_health's deliberately duplicated peer_path rule (it is the live copy).
- Effort / risk: S effort (retire) or M (align); low risk

## What is already good
- Secrets on the SSH channel: the sudo password goes on stdin (SUDO_PW_PREAMBLE), the Synology .env goes by SFTP, never argv; TrueNAS REST/RPC prefers a scoped API key, and the JSON-RPC session is pooled and reused (truenas_rpc.py) so job polling does not log in every 2 s.
- publish_db's local half is cheap and correct: sqlite backup + quick_check + counts of the real 501 MB index in about 4 s; the rename-based swap leaves the live path without an index only between two `mv`s. Transport compression is NOT worth adding: zlib-1 saves only 38% at ~55 MB/s of CPU, slower than the LAN it would save.
- broll_drain's merge is keyed on the UNIQUE (share, rel_path) index, runs in one IMMEDIATE transaction and is idempotent; leave it.
- setup_tree sends ONE generated script down ONE session and chowns only the project subtree (not the tree), with the snapshot taken once per run (no duplicate snapshots in one run found in this territory).
- .stignore and folder-config parity between server/ and dashboard/ is pinned by server/tests/test_cross_component.py; the copies have not drifted.

## Coverage note
Not read in depth: install_syncthing_app.py, secure_syncthing_gui.py beyond its argv, create_api_key.py, write_marker.py beyond its run_ssh calls, accept_device.py beyond argv, most of synology.py's account/ACL half and truenas.py's app-install half, common.py's site/slug/path helpers. bench/ was judged on its flag set and CI cost, not run. Nothing was run against a NAS or DSM; findings 3 and 7 rest on the repo's own statements about DSM's PATH and /tmp.

## OUT OF TERRITORY
- server/install_dashboard_app.py:6634: each deploy's pre-recreate snapshot is one of the never-pruned `ccsync-pre-*` of ops-server-1; and its music.db swap on Synology should be checked for the same missing PATH_EXPORT as ops-server-3.
- dashboard/src/ccsync_dashboard/dashboard_update.py:1671, api.py:3844, recovery.py:500: the dashboard takes its own pre-op snapshots (`dashboard-update-*`, `file-move-undo-*`, `restore-*`); check whether anything prunes those.
