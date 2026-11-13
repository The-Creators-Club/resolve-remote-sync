# Sealed notes: docker

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 5 notes.

### SRV-S04: A missing mount source is silently created as an empty administrator-owned folder.
- Why: The runtime creates a missing mount source owned by root, which the server's own user cannot write, and the server then fails on permissions.
- Must: Install creates every mounted folder with the server user's ownership before first start, and the server refuses to start on one it cannot write.
- Tool: Docker bind mounts
- Where it bit: The server: installing it and keeping it running

### SRV-S05: Restarting the service that owns a shared network strands its neighbours.
- Why: When services share one service's network, restarting that owner leaves the others with no network until they restart too.
- Must: After the network-owning service restarts, every service sharing its network is reachable again without a person stepping in.
- Tool: Docker network_mode: service:
- Where it bit: The server: installing it and keeping it running

### SRV-S06: A failed health status does not restart the program.
- Why: Restart-on-failure acts only when the process exits; an "unhealthy" status is informational unless something else acts on it.
- Must: The dashboard detects and recovers its own dead background work in process, and its health does not fail just because the NAS sync service is down.
- Tool: Docker restart policies and healthchecks
- Where it bit: The server: installing it and keeping it running

### SRV-S08: The packaged install's settings file alters passwords with "$" or " #".
- Why: The parser interpolates "$", treats " #" as a comment and strips quotes and edge spaces, so the customer's own password was changed.
- Must: The customer's own NAS password works whatever its characters, or the install refuses it naming the exact character.
- Tool: Docker Compose .env files
- Where it bit: The server: installing it and keeping it running

### SRV-S09: A Synology NAS runs an older app engine lacking newer file syntax.
- Why: The app manager on a Synology carried an older engine that rejects the optional env-file syntax newer guides use.
- Must: Install files work on the oldest app manager the supported NAS models ship, checked on that version.
- Tool: Docker Compose 2.20.1 on Synology (compose-go v1.16.0)
- Where it bit: The server: installing it and keeping it running
