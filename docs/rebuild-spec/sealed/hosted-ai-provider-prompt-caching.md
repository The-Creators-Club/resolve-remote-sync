# Sealed notes: hosted-ai-provider-prompt-caching

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 1 notes.

### CE2-S03: A prompt cache belongs to one model.
- Why: Resuming a conversation on another model re-reads the whole cached corpus at that model's price while reporting itself warm.
- Must: Switching models starts a separate conversation, while the visible history of what was done to the cut is shared across models.
- Tool: hosted AI provider prompt caching
- Where it bit: Timeline Cards: the editor
