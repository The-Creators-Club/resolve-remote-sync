# Sealed notes: htmx

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 1 notes.

### DSH-S04: An error banner sent with another page update stayed out of view.
- Why: When one reply updates both the page and an error strip elsewhere, the update event fires once per element, and the first used up the scroll target.
- Must: Any error banner a reply puts on the page is scrolled into view with its button, however many parts that reply updates.
- Tool: htmx out-of-band swaps
- Where it bit: The dashboard
