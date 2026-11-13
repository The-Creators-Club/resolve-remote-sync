# Sealed notes: docker+zfs

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names every one of these tools. 1 notes.

### SRV-S07: Snapshots mounted on demand do not reach a program behind a default mount.
- Why: A default mount does not pass on mounts made later under it, so snapshots the NAS mounts on first access stay empty for the server app.
- Must: The snapshot folder is mounted with propagation from the host and setup prints the host-side check, or snapshots are read another way.
- Tool: Docker bind mount of a ZFS .zfs/snapshot directory (slave propagation)
- Where it bit: The server: installing it and keeping it running
