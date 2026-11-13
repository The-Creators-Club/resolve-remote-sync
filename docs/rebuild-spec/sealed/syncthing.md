# Sealed notes: syncthing

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 12 notes.

### DSH-S05: The NAS sync engine answered normally with zero folders after a failed load.
- Why: Restarted with a default or unloadable configuration, it answers success with a valid device id and an empty folder list.
- Must: A folder list that suddenly empties is treated as a broken sync engine, never as every project removed.
- Tool: Syncthing (REST config after a failed config load)
- Where it bit: The dashboard

### SYN-S02: Sharing a folder with an unapproved device looks successful and silently does nothing.
- Why: The tool accepts a folder share naming a device it has not approved, replies OK and drops the device, so repeating the share every minute changes nothing.
- Must: A device is added to a share only after approval; one awaiting approval is shown as waiting, and no share to it is claimed or logged as made.
- Tool: Syncthing (a folder config naming an unconfigured device is accepted and the device stripped)
- Where it bit: Sync

### SYN-S03: A sync tool with its settings wiped comes back as a new device.
- Why: Started on an empty settings folder the tool regenerates its settings with a new device identity, but the app neither restarted it nor re-read the identity.
- Must: When the tool's settings are missing it is restarted to regenerate them, and its identity is re-read so shares follow the new one within one report.
- Tool: Syncthing
- Where it bit: Sync

### SYN-S04: A new computer's connection to the NAS dropped one second after connecting, forever.
- Why: Handshake then "reading length: EOF" after about 1 s means the other side does not list this device; a fresh configuration knows no devices.
- Must: Setup enrols the computer and the NAS in each other's device lists before the first connection, confirms it stays up, and names any second running copy.
- Tool: Syncthing
- Where it bit: Sync

### SYN-S05: The folder sync tool keeps "folder path missing" after a drive returns.
- Why: The tool rechecks a missing folder path only on its next scan; its folder marker's name is set per folder, was a file in old versions, and paths may begin with ~.
- Must: When a folder is in that error and its directory and marker exist again, a rescan is requested, at most every five minutes.
- Tool: Syncthing
- Where it bit: Sync

### SYN-S06: The folder sync tool reports "nothing needed" before it has heard from its peer.
- Why: A freshly added empty folder reads idle with zero bytes needed before it connects, which a benchmark recorded as a completed sync at zero seconds.
- Must: "Synced" is reported only after the peer is connected and has sent its file list.
- Tool: Syncthing
- Where it bit: Sync

### SYN-S07: The folder sync tool's web control page has no login by default.
- Why: The tool ships its control page without a password, on the NAS and on editors' computers alike.
- Must: Every control page the product runs requires a login or is unreachable from the network.
- Tool: Syncthing
- Where it bit: Sync

### SYN-S08: The folder sync tool's conflict copies are silent files with a fixed name pattern.
- Why: The tool renames the losing version "<name>.sync-conflict-<date>-<time>-<id>.<ext>" beside the file, for any file type, and reports nothing.
- Must: A scan of the synced tree finds files matching that pattern for every extension and reports the count and up to 20 paths.
- Tool: Syncthing (sync-conflict files)
- Where it bit: Sync

### SYN-S09: Un-ignoring one subfolder in the folder sync tool un-ignores everything under its parent.
- Why: In the tool's ignore rules an include naming a folder includes its whole subtree, and the tool descends into ignored folders when a deeper include could match.
- Must: Sharing one subfolder of a project delivers exactly that subfolder, and both sides then report complete.
- Tool: Syncthing v2 ignore patterns (.stignore negation)
- Where it bit: Sync

### SYN-S10: On Windows the folder sync tool reads backslash escapes as path separators.
- Why: Names with brackets or braces were escaped with backslashes, which the tool on Windows reads as separators, so a shared subtree stayed invisible while reading back confirmed.
- Must: Ignore patterns for such names are written in a form the tool reads the same on Windows and macOS, proven against the real tool before release.
- Tool: Syncthing ignore patterns
- Where it bit: Sync

### SYN-S11: Auto-accepted shared folders land flattened on editors' disks.
- Why: The tool's auto-accept turns a folder label containing slashes into one flat folder name instead of the nested project path.
- Must: Each shared project lands at its true nested path on the editor's disk.
- Tool: Syncthing (autoAcceptFolders)
- Where it bit: Sync

### SYN-S12: The folder sync tool upgrades itself and reports crashes to its makers.
- Why: The pinned version was replaced by the tool's own updater every 12 hours, and crash data left the studio.
- Must: Helper tools on editors' computers stay at the pinned version and send nothing to their makers.
- Tool: Syncthing (auto-upgrade, crash reporting)
- Where it bit: Sync
