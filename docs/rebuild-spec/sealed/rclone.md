# Sealed notes: rclone

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 18 notes.

### SYN-S14: A filter for folders at any depth missed the folder at a project's top.
- Why: The tool's any-depth folder pattern requires at least one parent folder, so a Proxy folder at the project root did not match.
- Must: Proxy folders at every depth, the project root included, follow the proxy rules.
- Tool: rclone filter patterns (**/Proxy/**)
- Where it bit: Sync

### SYN-S15: The transfer tool's filters match raw bytes, and the first matching rule wins.
- Why: A composed-spelling exclude missed a Mac's decomposed file, and an include listed earlier overrode a later exclude.
- Must: Every exclude is given in both Unicode spellings, placed before any include, and a folder exclude also covers everything inside it.
- Tool: rclone (filter rules)
- Where it bit: Sync

### SYN-S16: Folder names with [brackets] in a transfer filter excluded files nobody asked to skip.
- Why: The tool's filter rules read brackets as a pattern, and the studio's tree really contains bracketed names.
- Must: Any real name passed into a filter rule is escaped so it matches only itself.
- Tool: rclone filter rules
- Where it bit: Sync

### SYN-S18: A slow computer clock silently stopped every proxy download.
- Why: The tool ages remote files against the local clock, so with a slow clock every NAS file looks future-dated, is skipped, and the run still exits successfully.
- Must: A minimum-age rule on remote files is not trusted while the local clock is off, and such a run is reported as blocked by the clock.
- Tool: rclone (--min-age)
- Where it bit: Sync

### SYN-S19: Mirroring with a minimum-age filter bins files freshly rewritten on the source.
- Why: The age filter applies to each side separately, so a recently rewritten NAS file is hidden and the editor's older copy is treated as deleted and moved to backup.
- Must: No age filter is combined with mirroring deletions in a way that hides a rewritten source file.
- Tool: rclone (sync with --min-age and --backup-dir)
- Where it bit: Sync

### SYN-S20: Files moved to the local bin appeared in transfer history as downloads.
- Why: Moving a file into the backup folder logs two records, a move then a move-into-backup, and counting the first made it look transferred.
- Must: History and counts show a file moved to the local bin as removed, never as downloaded, and count it once.
- Tool: rclone JSON log with --backup-dir ("Moved (server-side)" then "Moved into backup dir")
- Where it bit: Sync

### SYN-S21: The transfer tool reported success on a proxy the NAS had cut short.
- Why: With 255 KiB chunks and 64 parallel requests against a server lacking the transfer-limits extension, the tool finished with success on a truncated file.
- Must: Use 64 KiB chunks and 16 parallel requests or fewer against such servers, and check the finished size independently of the tool's success.
- Tool: rclone (SFTP backend, chunk size and concurrency)
- Where it bit: Sync

### SYN-S22: The transfer tool's checksums over secure file transfer need a shell on the NAS.
- Why: It computes checksums by running hash commands on the NAS, which a file-transfer-only account cannot do.
- Must: Transfers verify integrity without running commands on the NAS before editor accounts are restricted to file transfer only.
- Tool: rclone (over SFTP)
- Where it bit: Sync

### SYN-S23: An interrupted upload to the NAS restarts every file from zero.
- Why: The tool cannot resume uploads over secure file transfer; ending it by an app update, a sleep or a timeout throws away hours of a big file.
- Must: An in-flight upload is never ended for routine reasons or for being slow; an app update waits for it or leaves it running.
- Tool: rclone over SFTP
- Where it bit: Sync

### SYN-S24: The transfer tool's own timeouts do not cover a stuck local read.
- Why: Its network timeout covers remote traffic only, and its maximum-duration limit is never checked during a blocked local read.
- Must: Every transfer run is watched from outside for byte progress.
- Tool: rclone (--timeout, --max-duration)
- Where it bit: Sync

### SYN-S25: A time-limited transfer run waits alone on its last big file.
- Why: Past a soft time limit it starts nothing new and waits for files in flight; one stream used a quarter of the line, and two runs share temporary names.
- Must: Never end a run mid-file, never transfer one file in two runs at once, and keep the computer awake while a file is in flight.
- Tool: rclone over SFTP (--max-duration soft limit)
- Where it bit: Sync

### SYN-S26: Editors' transfers failed with "key mismatch" on every new site.
- Why: The NAS offers several host key types, the tool prefers ECDSA, and only the ed25519 key had been recorded.
- Must: Record the NAS host key with its key type and tell the tool to use exactly that type.
- Tool: rclone (SFTP host key checking)
- Where it bit: Sync

### SYN-S27: Leaving out the parallel-streams setting does not mean zero streams.
- Why: The tool defaults to 4 parallel streams per file, so a recommendation that omitted a winning value of 0 selected the slower setting.
- Must: Any recommended or applied transfer setting states every value explicitly, including zero.
- Tool: rclone (--multi-thread-streams)
- Where it bit: Sync

### SYN-S28: The transfer tool's "obscured" passwords can be read back.
- Why: Its stored passwords are only obscured, revealed by a single command, and could land in benchmark output.
- Must: Stored transfer passwords are treated as plain secrets and never written to logs, reports or results.
- Tool: rclone (obscure / reveal)
- Where it bit: Sync

### SYN-S29: The transfer tool logs retries as errors even when the run succeeds.
- Why: Retried operations are written at error level; only the exit code says whether the run failed.
- Must: A transfer run is judged failed only by the tool's final result, never by error-level lines in its output.
- Tool: rclone
- Where it bit: Sync

### SYN-S30: The transfer tool reads a minimum size of "1" as 1 KiB, not one byte.
- Why: Measured: a bare "1" as the minimum file size means 1 KiB; "1B" is needed to skip only empty files.
- Must: A minimum-size filter meant to skip empty files still lets one-byte and small files sync.
- Tool: rclone (--min-size)
- Where it bit: Sync

### SYN-S31: Each transfer run opens its own NAS login pool and lists the whole folder.
- Why: Pools are not shared between runs, so a run set to 16 connections can log in 16 times per project per pass plus a full recursive listing.
- Must: Size connection counts for checks that find nothing, not for big uploads, and do not start a run when nothing local has changed.
- Tool: rclone (sftp-connections, checkers, per-run connection pool)
- Where it bit: Sync

### SYN-S32: The transfer tool leaves part-files beside the real file in the destination.
- Why: By default an interrupted transfer leaves a file named with a random token and a ".partial" ending in the destination folder, which nothing removes.
- Must: Every filter for the synced folders excludes these part-files, and orphans are found and reported.
- Tool: rclone
- Where it bit: Sync
