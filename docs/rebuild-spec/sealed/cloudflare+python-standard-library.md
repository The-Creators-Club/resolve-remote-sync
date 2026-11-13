# Sealed notes: cloudflare+python-standard-library

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names every one of these tools. 1 notes.

### SRT-S11: The studio's website blocked the server's requests by their default client name.
- Why: The card tracker on the studio's public site answered 403 to the NAS, because its protection blocks a generic library client name.
- Must: Requests to the studio's own sites carry a named client identity and are tested against the live site, not only locally.
- Tool: Cloudflare in front of the card tracker; Python urllib's default User-Agent
- Where it bit: The Footage Sorter and camera cards
