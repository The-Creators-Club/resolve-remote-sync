# Sealed notes: github

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 5 notes.

### REL-S02: An interrupted release upload was skipped as already published, for ever.
- Why: An interrupted upload keeps its name and size but stays unfinished, so skipping by name and size never re-sent it.
- Must: A release file counts as published only when the host says it finished and its checksum matches; any doubt uploads it again.
- Tool: GitHub Releases
- Where it bit: Releases and updates

### REL-S03: A failed re-upload left the update feed without its index file.
- Why: Replacing a release file deletes the old one before uploading, so two server errors left the feed without its index for about a minute.
- Must: After every publish the feed's file list is checked, and a missing index is restored before success is reported.
- Tool: GitHub Releases (gh release upload --clobber)
- Where it bit: Releases and updates

### REL-S04: Hosted release files redirect to another host and cannot sit in folders.
- Why: A download answers with a redirect to a different host, and a release's files are one flat list whose names cannot contain a slash.
- Must: Downloads follow secure redirects with no credentials sent and verify every file, and published file names are unique without folders.
- Tool: GitHub Releases
- Where it bit: Releases and updates

### REL-S06: Build signing was silently skipped while believed on.
- Why: A step's own variables are invisible to that step's run condition, so the certificate step was always skipped and builds shipped unsigned.
- Must: Each build states whether it was signed, and a build expected to be signed that is not is refused for publishing.
- Tool: GitHub Actions (a step's own env is not visible to its own `if`)
- Where it bit: Releases and updates

### REL-S07: The build service reported a run green when its test job was skipped.
- Why: A skipped job does not fail its run, and a protected release environment that does not exist yet is created automatically with no reviewer.
- Must: Release checks confirm the test job ran and passed on the commit, and that the release environment exists with a required reviewer.
- Tool: GitHub Actions (skipped jobs, auto-created environments)
- Where it bit: Releases and updates
