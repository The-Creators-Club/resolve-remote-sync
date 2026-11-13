# Sealed notes: anthropic-api-and-models+local-vision-model

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names every one of these tools. 2 notes.

### BRO-S09: Descriptions from separate frames beat a mosaic; model size barely mattered.
- Why: In a 100-clip owner-judged test, every local model size beat the hosted model's mosaic-based index; separate frames and a compact constrained answer were the lever.
- Must: Clip descriptions are written from several separate frames, and the describing method is chosen by a human judging the studio's own footage.
- Tool: Qwen3-VL (local), Claude Haiku (hosted)
- Where it bit: The b-roll archive

### BRO-S10: Every vision model tested called a gun "a tool with a laser pointer".
- Why: Safety tuning in every model tried, hosted included, softened weapons into harmless objects, so a search for "gun" missed them.
- Must: The comparison set includes weapons and look-alikes, known misnamings are recorded per model, and a weapons search finds such footage despite softened wording.
- Tool: Qwen3-VL (all sizes), Claude Haiku image description
- Where it bit: The b-roll archive
