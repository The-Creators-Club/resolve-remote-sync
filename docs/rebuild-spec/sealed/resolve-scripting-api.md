# Sealed notes: resolve-scripting-api

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 1 notes.

### RSV-S14: Importing into the current bin and then moving the clips aims without switching bins.
- Why: Moving newly imported clips avoids changing the selected bin; each scripting call returns a new folder object, so folders must be compared by unique id.
- Must: Import, then move the new clips to their bin comparing folders by unique id; a refused move leaves the clips in the project and logs where.
- Tool: Resolve scripting API (ImportMedia then MoveClips)
- Where it bit: Resolve on the editor's computer
