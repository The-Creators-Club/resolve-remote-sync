# Sealed notes: openssh-on-alpine-linux

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 1 notes.

### SRV-S10: An account created the default way refused key sign-in.
- Why: On the small Linux base used, an account created with the default locked password field is refused even for key-only sign-in.
- Must: Every file-transfer account created for an editor signs in with its key the first time it is tried.
- Tool: OpenSSH on Alpine Linux (useradd shadow field "!")
- Where it bit: The server: installing it and keeping it running
