# Sealed notes: offsite-storage-providers+restic

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names every one of these tools. 1 notes.

### SRV-S20: The cloud storage box accepts only about 1.5 new files a second.
- Why: The box took about 1.5 new files a second per account at any parallelism; packed, 2,000 tiny files took 21 s instead of 20 minutes.
- Must: Many small files reach that storage packed into large objects, so a backup of 90,000 small files finishes in minutes.
- Tool: Hetzner Storage Box (packing via restic)
- Where it bit: The server: installing it and keeping it running
