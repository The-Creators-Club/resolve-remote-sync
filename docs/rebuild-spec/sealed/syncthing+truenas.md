# Sealed notes: syncthing+truenas

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names every one of these tools. 2 notes.

### SRV-S19: The NAS's catalog sync app makes its own key and stores settings outside snapshots.
- Why: On TrueNAS the catalog app generates its own access key and keeps device pairings and shares in an app volume no dataset snapshot covers.
- Must: Setup reads the sync tool's key from the app instead of asking the owner to invent one, and the backup page lists its settings as not covered.
- Tool: Syncthing (TrueNAS catalog app)
- Where it bit: The server: installing it and keeping it running

### SYN-S01: The folder sync tool stalls on a restricted-permission NAS share.
- Why: On a NAS dataset in restricted ACL mode the tool's per-folder permission changes failed and transfers sat in temporary files.
- Must: The tool is told to ignore permissions on the NAS side, and transfers complete there.
- Tool: Syncthing (ignorePerms on a TrueNAS restricted-ACL dataset)
- Where it bit: Sync
