# Sealed notes: pre-signed-object-storage-links

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 1 notes.

### REL-S05: A pre-signed feed link could not reach its signature file.
- Why: A pre-signed link is valid for one exact file, so changing its name to reach the signature file is refused and builds stopped arriving.
- Must: The signature file's address can be set apart from the feed's, and when it cannot be fetched the admin page names the likely cause.
- Tool: pre-signed object-storage links (S3 SigV4) for the release feed
- Where it bit: Releases and updates
