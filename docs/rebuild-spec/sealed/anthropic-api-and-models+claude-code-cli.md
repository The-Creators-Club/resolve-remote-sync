# Sealed notes: anthropic-api-and-models+claude-code-cli

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names every one of these tools. 2 notes.

### BRO-S06: An exhausted API key silently overrode the signed-in subscription.
- Why: Wherever the key variable is set, the command line uses it instead of the signed-in account, without saying so.
- Must: Each assistant call uses the account the admin chose and records which account it used.
- Tool: Claude Code CLI (ANTHROPIC_API_KEY overrides login)
- Where it bit: The b-roll archive

### ALL-S01: A spawned assistant command line billed the wrong account.
- Why: Started by a server or from another assistant session, the command line prefers inherited key and session variables over its own sign-in, failing with "credit balance too low".
- Must: Every background assistant call runs on the account the product is configured with, never one inherited from whatever launched it.
- Tool: Claude Code CLI (`claude -p`; scrub inherited ANTHROPIC_* and CLAUDECODE variables)
- Where it bit: The whole product
