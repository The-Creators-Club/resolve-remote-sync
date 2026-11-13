# Sealed notes: tailscale

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 6 notes.

### BRO-S15: The public link relay strips the URL path before forwarding.
- Why: The relay removes its mount path when forwarding, so its target must carry the client-folder prefix itself.
- Must: The public client-folder link serves its page and media under its prefix, tested from outside the studio network.
- Tool: Tailscale Funnel
- Where it bit: The b-roll archive

### APP-S05: A secure server address on port 8443 was turned into plain http.
- Why: The private-network service used to publish the dashboard serves secure connections on 8443 and on every port of its own names.
- Must: Without a typed scheme, that service's names and port 8443 are tried as secure.
- Tool: Tailscale Serve and Funnel
- Where it bit: The app on each editor's computer

### SRT-S14: A public link relay is too slow for hundreds of gigabytes.
- Why: Links published past the private network go through a relayed, bandwidth-limited service: fine for a few files, slow for hundreds of GB.
- Must: A link shows both its team-network address (full speed) and its public one, and large outside deliveries are flagged as slow.
- Tool: Tailscale Funnel
- Where it bit: The Footage Sorter and camera cards

### SRV-S01: The private-network tool's packaged start-up gives up and keeps minting login links.
- Why: Started without a key, the stock start-up gives up after 60 s and crash-loops, minting a fresh login link each cycle; publishing fails before login completes.
- Must: A first sign-in to the private network on the NAS shows one stable login link until completed from setup, and publishing is set only afterwards.
- Tool: Tailscale container image (containerboot, LocalAPI, Serve)
- Where it bit: The server: installing it and keeping it running

### SRV-S02: An empty private-network member answers "nothing published" with a null body.
- Why: Asking for publish settings returns success with a null body, and writing them is accepted even when the network's secure certificates are switched off.
- Must: Read a null answer as "nothing published", and refuse to publish, naming the admin page to fix, while the network's certificates are off.
- Tool: Tailscale (Serve and its local API)
- Where it bit: The server: installing it and keeping it running

### SRV-S03: The server's private-network sign-in expires after 180 days by default.
- Why: Expiry, or a NAS update that stops the network service, silences the whole fleet at once.
- Must: The server watches its own network connection, warns 14 days before expiry, and raises one alert when most computers go silent together.
- Tool: Tailscale
- Where it bit: The server: installing it and keeping it running
