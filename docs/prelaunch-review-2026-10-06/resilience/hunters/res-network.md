# Pre-launch resilience review - lens res-network (network loss and partitions)

Date 2026-10-06, HEAD 08b40eb plus the uncommitted working tree. Read-only.

**Covered:** the companion's network clients end to end: reporter (`reporter.py`: payload
budget, timeouts, failure streak, tray surfacing), `transport.py` (cleartext guard, DNS
classification), `selection.py` (plan cache, project-roots TTL, unreachable handling),
`site.py` (manifest cache and refresh loop), `identity.py`, `upgrade.py` (download, REL-8
attempt ledger) and the auto/pushed update gates in `app.py`, `jobs_runner.py` (claim,
heartbeat, result) against the dashboard's `db.heartbeat_job` / `finish_job` /
`expire_leases`, `ytdl_executor.py` call retry, `sync/lane_guard.py` (check_remote on a
failed listing, fleet halt), `sync/rclone_lane.py` (transport flags, partial suffix,
stall watchdog, `down_route`), `sync/server_locate.py`, `broll_fetch.py`,
`broll_server.py` threading, `jobs_media.py` partials, Syncthing admin timeouts and the
NAS-side `syncthing_client.py` options; dashboard `alerts.py` kind registry,
heartbeat/dead-man, delivery budget, `release_feed.py` timeouts, `tailscale_local.py`.
One probe in the scratchpad: urllib POST of a 6 MB body to a server reading steadily at
~200 KB/s with `timeout=5` fails at 5.0 s (the socket timeout bounds the WHOLE sendall,
not each chunk).

**Already solid (not reported):** every urllib call has a timeout; no redirects followed;
plan, site manifest and project roots are cached with honest "cache"/"unreachable"
labels; a failed NAS listing never trips the lane B breaker; rclone has `--timeout`,
`--contimeout`, partial suffixes and a stall watchdog; ytdl fleet calls retry transport
failures inside the lease; jobs heartbeats treat transport failure as a blip; alert
delivery has a cycle budget and requeues undelivered rows; the tray says "cannot reach the
server" and how long since the dashboard accepted a report.

**Not covered:** live behaviour on real lossy links (nothing touched the network), the
Timeline Cards agent tunnel (off everywhere), the ytdl server side (dormant in the vendor
build), macOS-specific SMB hard-mount behaviour.

### res-network-1 - A dashboard outage longer than the 5-minute job lease kills every running fleet job, and a result posted during an outage is never retried
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** companion/src/ccsync_companion/jobs_runner.py:815-868 (`_heartbeat`), :886-923 (`_post_result`), :1269-1366 (`_run_child`); dashboard/src/ccsync_dashboard/db.py:12153-12176 (`heartbeat_job`), :12179-12204 (`finish_job`), :12285-12330 (`expire_leases`), db.py:11607 (`JOB_LEASE_SECONDS = 300`)
- **What:** `heartbeat_job` refuses to extend a lease whose `lease_expires_at` has passed, even when nobody else has claimed the job (`AND lease_expires_at > ?`). The companion keeps working through transport failures (correct), but the first heartbeat that gets through after more than 300 s of outage answers 410 and `_run_child` terminates the child. Separately, `_post_result` makes ONE attempt; a transport failure is logged and dropped ("a lost result costs one retry"), although `finish_job` would accept a late result. `ytdl_executor` already retries transport failures inside the lease; the jobs runner does not.
- **Scenario:** The NAS reboots for an update, the dashboard container is restarting after an image pull, or a laptop's tailnet drops for 6 minutes. A whisper pass 40 minutes into an hour-long interview transcription is killed on reconnect, `expire_leases` counts an attempt and puts a cooldown on the machine that did the work, and the job starts again from zero elsewhere. A job that finished while the dashboard was down has its result discarded, so the same GPU work runs again. Several outages during a long queue can spend whisper's retry budget, and whisper is never pinned, so the job ends `abandoned`.
- **Recommendation:** In `heartbeat_job`, extend an expired lease when the row is still held by the same (editor, machine) and has not been re-queued: the CAS on `claimed_by`/`claimed_machine`/state already proves nobody else holds it. Give `_post_result` a bounded retry, or keep a small on-disk outbox of unsent results that is flushed on the next successful report. `finish_job` already accepts late results.
- **Known:** new (comp-ytdl-jobs-1 / CR-31 fixed the transport-blip half only)

### res-network-2 - Transient network failures spend REL-8's permanent per-version upgrade budget, and an admin's UPDATE NOW cannot override it
- **Severity:** medium
- **Confidence:** CONFIRMED
- **Where:** companion/src/ccsync_companion/upgrade.py:125-141, 371-463, 1704-1859 (`download_and_verify`); companion/src/ccsync_companion/app.py:7077-7108 (`_upgrade_attempt_blocked`), 7167-7184 (`_note_upgrade_failure`), 8382-8425 (`_maybe_auto_update`), 8500-8540 (pushed update)
- **What:** Every exception in the streamed download, including a connection reset, a TLS drop or a dashboard restart mid-transfer, is filed as `ERROR_DOWNLOAD` and counts toward `MAX_UPGRADE_ATTEMPTS = 8`, the same budget as an AV quarantine. The download cannot resume (no Range request): a drop at 95 % starts again from byte 0. When the cap is reached, the auto-update and pushed-update paths both return silently on "given up". A fresh admin push (new `requested_at`) is also blocked, because the cap is keyed on the version, not on the request. Only a newer published version, or the editor clicking Update in the tray, moves the machine on.
- **Scenario:** A remote editor on hotel Wi-Fi or a tethered phone gets a security fix through auto_update. Eight drops of a ~100 MB download over about 37 hours (10 min, 1 h, then 6 h back-offs) exhaust the budget. The admin sees `[ FAILED x8 ]` and presses UPDATE NOW, which does nothing. The machine stays on the vulnerable build until the vendor ships another version or a non-technical editor finds the tray item.
- **Recommendation:** Don't count transport-class failures (URLError, timeouts, resets, 5xx) toward the permanent cap: give them their own back-off with no give-up, or reset the counter when a report succeeds after the failure. Let a pushed update with a new `requested_at` clear the given-up state once (not the crash-looped state). Add Range resume for a `.partial` download whose length and sha are known.
- **Known:** REL-8 (FIXED, intended for AV/sha failures; this is its network side effect, new)

### res-network-3 - An idle machine on a slow uplink can never deliver its heavy report: the 30 s timeout bounds the whole upload, so the machine goes dark on the fleet grid
- **Severity:** medium
- **Confidence:** CONFIRMED (timeout semantics probed); PLAUSIBLE (real payload sizes on real links not measured)
- **Where:** companion/src/ccsync_companion/reporter.py:107-120 (7 MiB budget), 417-443 (`default_http_post`, no compression), 535-541 (`report_timeout_full` 30 s), 1523-1571 (`_report_loop` / `_run_cycle`); manifest.py:36 (2000 entries per list per project)
- **What:** urllib's `timeout` bounds the total `sendall` of the request body (probe: steady ~200 KB/s, 6 MB body, timeout=5, fails at 5.0 s). Heavy reports are sent uncompressed, with a 30 s ceiling and a 7 MiB budget, so they need about 1.9 Mbit/s of sustained upload at the budget size. An idle machine sends ONLY heavy ticks (`light` is true only on active ticks), and `_fit_payload` sheds by size, never after a timeout. A heavy body that cannot cross the link in 30 s therefore fails on every tick, and the reply that carries every command (halt, pushed update, file moves, machine settings, job offers) never arrives. During a big lane A upload (rclone has no `--bwlimit` anywhere), the 5 s light tick also has to share an uplink that rclone is saturating.
- **Scenario:** An editor with three selected projects (per-file manifests of up to 2000 originals plus 2000 proxies each, plus the Resolve bin tree) works from home on a 1 Mbit/s ADSL upload or a rural 4G hotspot. Every idle heavy report times out. The fleet grid shows the machine stale, then red, then `machine_silent` after 24 h. The tray says "the dashboard has not accepted a report", and the editor's admin cannot push a fix because the reply channel is the report.
- **Recommendation:** gzip report bodies (`Content-Encoding: gzip`; JSON path lists compress about 10x) and have the dashboard accept them. Scale the heavy timeout with body size, or after a heavy timeout fall back to a light tick so the core status and the command reply still flow. Consider an optional lane A `--bwlimit` / upload share for home uplinks.
- **Known:** new (B6 fixed the 8 MiB size limit, not time)

### res-network-4 - Nothing on the server notices that the server itself fell off the tailnet; a fleet-wide disconnect surfaces only as per-machine `machine_silent` after 24 h
- **Severity:** medium
- **Confidence:** CONFIRMED (absence)
- **Where:** dashboard/src/ccsync_dashboard/alerts.py:100-104 (`SILENT_SECONDS = 24 h`), 3931-3932 and the ALERT_KINDS registry (no tailnet/self-reachability kind); dashboard/src/ccsync_dashboard/tailscale_local.py (read-only status client used only by setup); alerts.py:880-915 (heartbeat is opt-in and off unless a sink is set)
- **What:** Tailscale (Serve) is the only publish path for every customer, but the alert registry has no check on the NAS's own tailnet state (BackendState, key expiry, Serve config) and no correlated "most recently-active computers went silent at the same moment" rule. `tailscale_local.status()` can already read `BackendState` and `Self.KeyExpiry` but feeds only the setup wizard. The dead-man heartbeat is opt-in.
- **Scenario:** The NAS's Tailscale node key expires (180-day default for a user-authenticated node), or the Tailscale app stops after a TrueNAS update. Every remote editor loses the dashboard and all three lanes at once. The dashboard, still up on the LAN with internet for SMTP, raises nothing for 24 hours, then one `machine_silent` per machine. Nothing warned that the key was about to expire. At a customer site the vendor cannot reach, the first signal is editors complaining.
- **Recommendation:** Add an alert kind fed by `tailscale_local` (state not Running, key expiry within 14 days, Serve config missing) wherever the socket is present, and a correlated fleet-silence check (for example, at least 50 % of the machines that reported in the last day silent for 30 min or more gives ONE alert naming the server's network). Turn the daily heartbeat on by default whenever a sink is configured.
- **Known:** new

### res-network-5 - `remote_down` (second lane B route, e.g. a Cloudflare tunnel) has no failover to the primary route
- **Severity:** low
- **Confidence:** CONFIRMED
- **Where:** companion/src/ccsync_companion/sync/rclone_lane.py:839-881 (`down_route`); broll_fetch.py:268-297
- **What:** With `remote_down` set, `down_route` falls back to `remote` only when the route is REFUSED by config validation. When the configured route is merely unreachable (tunnel down, third-party account suspended, WebDAV origin dead), every lane B pass and every on-demand b-roll fetch fails, although the tailnet route to the same NAS would work.
- **Scenario:** A customer adopts the documented `remote_down` knob for a faster download path. The tunnel provider has an outage, or the tunnel's token is rotated. Proxy downloads and Send-to-Resolve fetches stop for every machine using it until someone edits config.toml by hand.
- **Recommendation:** After N consecutive transport-class failures on `VIA_REMOTE_DOWN`, run the pass on the primary route (same scope, same breaker) and report `route: fallback` so the dashboard can say so. Or document `remote_down` as unsupported for customers until failover exists.
- **Known:** new (cf-lane-b trial)

### res-network-6 - A laptop configured with an http LAN-address dashboard keeps sending its fleet credential in cleartext on whatever network it joins
- **Severity:** low
- **Confidence:** CONFIRMED (by design)
- **Where:** companion/src/ccsync_companion/transport.py:1-30, 204-260 (`_classify_name_by_dns`, `classify`); docs/EDITOR_SETUP.md:234-235 (`http://<tailnet-ip>:8480` as the documented form)
- **What:** A private or CGNAT literal, or a name that resolves to anything private (including a captive portal's DNS hijack to 10.x or 192.168.x), is `http_local`, so `X-CCSync-Token`, the identity token and any sign-in password go out in cleartext every report interval. The guard never asks whether the address is still the studio's (for example, a 100.64/10 target while Tailscale is down).
- **Scenario:** A laptop set to `http://192.168.0.10:8480` (studio LAN) is taken to a cafe or a client's office whose LAN is also 192.168.0.0/24. Or a `http://nas:8480` name is hijacked by a hotel portal's DNS to 10.0.0.1. Every minute it POSTs the per-editor fleet token to whatever answers there.
- **Recommendation:** Ship https by default for new customers (Tailscale Serve already provides certificates), and move "require https" from deferred to on by default for new sites. Short of that: skip sending credentials to a 100.64/10 target while no Tailscale interface is up, and to a name whose resolved address class changed since the last successful report.
- **Known:** LG-4 / CR-339 (deferred "require https", plan section 6) - still open

### res-network-7 - Editor-side Syncthing runs on upstream defaults: auto-upgrade every 12 h and crash reporting are on, uncontrolled at customer sites
- **Severity:** low
- **Confidence:** PLAUSIBLE
- **Where:** installer/windows_bootstrap.ps1:333, 1945-2028; installer/macos_bootstrap.sh:1848-1877, 2026; no `urAccepted` / `autoUpgradeIntervalH` / `crashReportingEnabled` / `STNOUPGRADE` anywhere in companion/src, installer or server
- **What:** The installers download the official Syncthing release from GitHub and start it with `serve --no-browser` only. Official binaries upgrade themselves on a 12 h cycle within a major version, and they send crash reports to the Syncthing project by default. Relays and global discovery are on, which PRIVACY.md discloses. Self-upgrade and crash reporting are not disclosed (the PRIVACY row covers only discovery and relays), and lane C's engine version is not pinned.
- **Scenario:** A Syncthing point release changes REST behaviour or folder-state semantics that `syncthing_admin.py` / `syncthing_lane.py` rely on, and every editor machine on every customer site takes it within 12 hours, outside the release pipeline. Or a crash report leaves a customer site that was told only the listed endpoints are contacted.
- **Recommendation:** Set `STNOUPGRADE=1` (or `autoUpgradeIntervalH=0`) and `crashReportingEnabled=false` through the companion's Syncthing admin on start, ship Syncthing upgrades through the vendor channel, and add the endpoint to PRIVACY.md if any part stays on.
- **Known:** PRIVACY.md row covers discovery/relays only; auto-upgrade and crash reporting new
