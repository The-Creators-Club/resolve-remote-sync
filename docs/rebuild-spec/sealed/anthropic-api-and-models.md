# Sealed notes: anthropic-api-and-models

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 10 notes.

### BRO-S01: The describer narrated an emergency from brake lights.
- Why: When a shot shows little, the describer narrates events; lamps on a tunnel gantry became "emergency lights", topping searches for "emergency vehicle".
- Must: Descriptions state only what the frames show, and shots with nothing to describe get fixed labels such as newsreader, title card, black frame or colour bars.
- Tool: Claude as the clip describer
- Where it bit: The b-roll archive

### BRO-S02: Describing cost came from images and output, not the large fixed prompt.
- Why: Spend was output 56%, frame images 38%, the cached fixed prompt 6%; the longest 9% of videos made 36% of all calls.
- Must: Frames sent per video are capped and spread across the whole clip, so a 1.8-hour clip costs a bounded number of calls.
- Tool: Anthropic API pricing (cache reads billed at 0.1x)
- Where it bit: The b-roll archive

### BRO-S03: Fixed instructions after the images never hit the cache, and answers were cut off.
- Why: Instructions after images missed the prompt cache, an output limit below a third of past answers truncated them (two paid calls, then failure), and conversations kept every earlier photo.
- Must: Repeated fixed text is cached, no answer is cut off by the output limit, and a long session's input does not grow with every earlier image.
- Tool: Anthropic Messages API (prompt caching, output token limit, Batch API at half price)
- Where it bit: The b-roll archive

### BRO-S04: One model rejected "thinking disabled" and failed every clip.
- Why: The newest model always thinks and rejects an explicit "off", while omitting the setting on other models turns on billed thinking.
- Must: The thinking setting is chosen per model, so no request is rejected and no unrequested thinking is billed.
- Tool: Anthropic Messages API, Claude Fable 5 (thinking omitted or adaptive, never explicitly disabled)
- Where it bit: The b-roll archive

### CE2-S01: Only the marked prefix of a prompt is cached.
- Why: With the corpus in four messages and only the first marked, 79% of the text was billed in full each turn, and a "warm" search took 139 s.
- Must: Long multi-part prompts are marked so the whole stored prefix is cached, and every call records tokens read from and written to the cache.
- Tool: Anthropic Messages API prompt caching (cache_control breakpoints)
- Where it bit: Timeline Cards: the editor

### CE2-S02: The prompt cache lasts five minutes unless an hour is asked for.
- Why: An editor who searches, watches and searches again pays full price to re-read every transcript after five minutes.
- Must: Conversations meant to stay warm ask for the one-hour cache, and keep the cache length they were opened with.
- Tool: Anthropic Messages API prompt caching
- Where it bit: Timeline Cards: the editor

### CE2-S04: An hour of speech is about 15,000 to 20,000 tokens of prose.
- Why: Mandarin is about one token per character and English one per four; both land near 15-20k per hour, so a 10-hour corpus is about 180k.
- Must: The model is given sentence-level text, never per-word timing, so a 10-hour corpus fits in one request.
- Tool: Claude models
- Where it bit: Timeline Cards: the editor

### CFI-S20: Given an approved translation as context, the model copies it instead of translating.
- Why: Asked to translate adjacent cuts with the paragraph's approved English as context, it returned that English verbatim, dealt out across the cuts in order.
- Must: Context given to the translator is limited to each cut's own time slice, and answers matching context verbatim outside it are rejected.
- Tool: Claude Haiku as the caption translator
- Where it bit: Timeline Cards: footage in, ready to cut

### CFI-S23: The cheaper assistant model links words as well as the dearer one.
- Why: On 20 paragraphs both gave 20 of 20 valid answers; the larger merged phrases like "these black bears" and cost about twice as much per episode.
- Must: Word links run on the cheapest model that passes the answer check, chosen by measured cost and a Chinese reader's judgement.
- Tool: Claude Haiku 5.5 versus Sonnet 5.5
- Where it bit: Timeline Cards: footage in, ready to cut

### CFI-S24: Linking a long paragraph can take minutes and arrive reordered.
- Why: Long paragraphs took minutes and 392 calls timed out at 180 s; phrases came back in Mandarin order around English asides.
- Must: Linking allows minutes per call, retries unanswered calls, and accepts phrases listed out of order as long as none overlap.
- Tool: Claude Haiku 5.5
- Where it bit: Timeline Cards: footage in, ready to cut
