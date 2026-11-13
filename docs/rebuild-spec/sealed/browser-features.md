# Sealed notes: browser-features

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 2 notes.

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
