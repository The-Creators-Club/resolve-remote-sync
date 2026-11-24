# Sealed notes: browser-features

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 5 notes.

### CE1-134: An installed offline worker keeps serving its old page over moved addresses.
- Why: An installed worker controls every address under its scope, so after the page moved it served the old page; a scope of "/" claimed the whole site.
- Must: When pages move, the old worker is switched off for everyone without losing unsent edits, and no worker claims more than its own section.
- Tool: Browser offline storage and installed offline workers
- Where it bit: Timeline Cards: the editor

### CE2-103: Browser storage belongs to an address, port included.
- Why: Offline storage is kept per page origin and can be evicted, so changing the server address or the app's local port strands every downloaded copy.
- Must: A released app's local address and port never change, and changing the server address keeps every downloaded copy and queued edit available.
- Tool: Browser offline storage and installed offline workers
- Where it bit: Timeline Cards: the editor

### CE2-104: Browser caches belong to the whole site, not to one page.
- Why: Deleting "all caches" to clear one stale offline page also removed another app's offline page and media an editor had saved for offline work.
- Must: Clearing a page's offline copy deletes only that page's own files, never another page's or saved media.
- Tool: Browser offline storage and installed offline workers
- Where it bit: Timeline Cards: the editor

### CE3-S01: A waveform drawn one rectangle per pixel column costs 198 ms a frame.
- Why: About 3,400 sub-shapes per path loaded the browser's graphics process; one outline per clip took 5.6 ms, and evicting cached images mid-frame forced reallocations.
- Must: Each clip's waveform is drawn as one outline, cached image sizes are capped, and no image being drawn this frame is evicted.
- Tool: browser 2D canvas
- Where it bit: Timeline Cards: the editor

### CE3-S03: The first visit after a release saved nothing for offline use.
- Why: Re-registering the page's offline cache handler at the same address does not check for a new one, and the page's own check raced the new one taking control.
- Must: After a release, one online open is enough for the editor to work offline again.
- Tool: browser service workers
- Where it bit: Timeline Cards: the editor
