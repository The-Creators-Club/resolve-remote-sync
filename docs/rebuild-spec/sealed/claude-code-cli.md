# Sealed notes: claude-code-cli

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 12 notes.

### BRO-S05: The assistant's command line reported failures on normal output and exited successfully.
- Why: Its errors appear on standard output rather than the error stream, and the exit code can still be zero.
- Must: Each assistant call is judged by the content it returned, never by its exit code alone.
- Tool: Claude Code CLI
- Where it bit: The b-roll archive

### CE1-S01: The command-line assistant answers with its default model unless told.
- Why: Without an explicit model on each call, the command-line assistant uses its default, and the answers look plausible.
- Must: Every call names the model the feature asked for.
- Tool: Claude Code CLI (--model)
- Where it bit: Timeline Cards: the editor

### CE1-S02: A conversation id is spent even when its first turn fails.
- Why: After any attempt with an id, even a failed one, later turns get "Session ID ... is already in use"; an unknown id answers "No conversation found".
- Must: "Already in use" or "not found" means the conversation is lost; a fresh id opens a new one with a visible note, and "new conversation" always starts one.
- Tool: Claude Code CLI sessions (--session-id / --resume)
- Where it bit: Timeline Cards: the editor

### CE1-S03: One assistant conversation cannot take two turns at once.
- Why: Sending several sections in parallel on one conversation failed with "Session ID ... is already in use".
- Must: Turns on one conversation run one after another, even when the page sends several at once.
- Tool: Claude Code CLI
- Where it bit: Timeline Cards: the editor

### CE2-S05: Saved conversations resume only on the same machine and folder.
- Why: A conversation id resumes only with the same machine, home and working folder; unknown ids fail "No conversation found", reused ones "already in use"; rebuilds wipe them.
- Must: The tool always starts from the same folder, and a conversation that cannot resume is restarted with its material re-sent, never answered without it.
- Tool: Claude Code CLI sessions (--session-id / --resume)
- Where it bit: Timeline Cards: the editor

### CE3-S02: An older assistant command-line tool refuses a newer model's exact name.
- Why: The installed tool rejects a model id newer than its catalogue with "update required", but resolves family aliases itself; it can report an error with a zero exit code.
- Must: Models are asked for by family alias unless pinned, the tool keeps itself updated, a zero-exit error counts as failure, and a refusal names the outdated tool.
- Tool: Claude Code CLI (model ids versus aliases, self-update)
- Where it bit: Timeline Cards: the editor

### DSH-S02: The assistant tool said "signed in" about a different account than the one billed.
- Why: With an API key in its environment the tool answers about the key and bills it; its sign-in command is "auth login"; its Linux build is 313 MiB.
- Must: A sign-in check reports the same account the real work will use, and nothing billable runs under an account other than the one shown.
- Tool: Claude Code CLI 2.1.x (auth login, setup-token, HOME)
- Where it bit: The dashboard

### DSH-S03: An assistant tool was larger than an assumed 300 MiB download cap.
- Why: The tool is 313 MiB and its publisher's manifest lists exact size and checksum; the other vendor's Linux tool ships only as a static build with a checksum list.
- Must: Download size limits and file names come from the publisher's manifest, and sign-in flows are tried on the real host before use.
- Tool: Claude Code and Codex command-line tools
- Where it bit: The dashboard

### SRV-S17: Deleting the replaced assistant version broke calls still running.
- Why: The command-line assistant re-launches itself by its own file path, so deleting the old version broke calls in flight, which can last 15 minutes.
- Must: An update keeps the previous version on disk for at least an hour after switching, then removes it.
- Tool: Claude Code CLI
- Where it bit: The server: installing it and keeping it running

### SRV-S18: The assistant's command-line tool took 50 seconds to start on a busy NAS.
- Why: A cold version check took 50 s against a 10 s limit, and an expired sign-in left a credential file without a refresh token that still looked present.
- Must: Allow at least 90 s for a cold start, keep the last good answer on a timeout, and treat a credential with no refresh token as signed out.
- Tool: Claude Code CLI
- Where it bit: The server: installing it and keeping it running

### ALL-S02: Each assistant command-line run spent most of its time starting unrelated plug-ins.
- Why: Every run booted all configured tool connections with long timeouts, 48-84 s per chunk against about 25 s without them; multi-turn file loops added overhead.
- Must: A 50-segment batch of assistant work finishes in under 30 s on a busy editing machine.
- Tool: Claude Code CLI (`--strict-mcp-config`, inline single-turn prompts, three chunks in parallel)
- Where it bit: The whole product

### YTD-S11: A dead assistant sign-in leaves its credential file with zero expiry.
- Why: When its session cannot refresh, the command-line assistant rewrites its credential file with expiry 0 and no refresh token, and the file still exists.
- Must: "No refresh token and already expired" counts as signed out, reading only those two facts and never any secret value.
- Tool: Claude Code CLI
- Where it bit: YouTube downloads
