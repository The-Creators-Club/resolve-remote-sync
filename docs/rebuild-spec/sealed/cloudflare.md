# Sealed notes: cloudflare

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 4 notes.

### BRO-S14: Client downloads through the tunnel crawled at about 3 MB/s.
- Why: The tunnel's default transport gave about 3 MB/s, its alternative about 18 MB/s, while a direct address reached the line's 39 MB/s.
- Must: Large client transfers get a measured direct path rather than an untested tunnel.
- Tool: Cloudflare Tunnel (cloudflared, QUIC transport)
- Where it bit: The b-roll archive

### SRT-S10: A hosted database's shared daily limits ran out and took other sites down.
- Why: 100,000 writes and 5 million reads a day per account; one change list read 26 million rows and a one-off repair 442 million, failing every site on the account.
- Must: The copy record lives where no daily quota can stop it, and every job's reads scale with what it changes, are bounded, watched and stopped when far over.
- Tool: Cloudflare D1 (free plan, limits shared per account)
- Where it bit: The Footage Sorter and camera cards

### SRV-S22: One bulk import used up a hosted database's daily allowance for every app.
- Why: The free tier shares 100,000 row writes and 5 million reads a day across all databases; one import or full-scan update used it until midnight UTC.
- Must: Estimate rows written and read before any bulk job, send only changes, and test query plans on data of real size.
- Tool: Cloudflare D1
- Where it bit: The server: installing it and keeping it running

### SYN-S33: A free tunnel service may carry video only with caching turned off.
- Why: The service's terms were read as allowing video when caching is bypassed; that is a reading, not written permission, and throttling must be watched.
- Must: A route through a third-party tunnel runs uncached, on its own account, with its rate checked daily for throttling.
- Tool: Cloudflare Tunnel
- Where it bit: Sync
