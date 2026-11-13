# Sealed notes: postgresql-container-image

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 1 notes.

### SRV-S11: A new database password was announced but the existing database kept the old one.
- Why: The packaged database reads its password only when it first creates an empty data folder, so later changes are silently ignored.
- Must: Changing the password on an existing database actually changes it, or the server refuses to start and says so.
- Tool: PostgreSQL container image (POSTGRES_PASSWORD)
- Where it bit: The server: installing it and keeping it running
