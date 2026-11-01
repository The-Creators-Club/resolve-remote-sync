# CC Sync: supported platforms

**Version 0.1 (draft), 2026-10-07** (CR-377; COM-M52, COM-M39, owner decisions
of 2026-10-07). The beta terms (`legal/BETA_AGREEMENT.md` section 4) quote the platform list themselves, because this page is not published to customers; keep the two in step.
"Supported" means we test it and will help with it. Anything not listed is
unsupported, and may work. Rows marked **UNVERIFIED** are what the code
targets, not what has been run on that platform.

## Editor machines

| Platform | Supported | Notes |
|---|---|---|
| Windows | **Windows 10 22H2 and Windows 11, x64** | Windows 10 reached end of life in October 2025, so it receives security updates only with extended security updates; we support 22H2 only because editors are still on it. Unless the machine is enrolled, treat it as a risk. ARM Windows is not supported |
| macOS | **Apple silicon (arm64) only** | `tools/release_macos.sh` builds and checks an arm64 binary (an unsigned arm64 binary is killed on launch, so the build is ad-hoc signed). Intel Macs are not supported. **Minimum macOS: not pinned.** The build sets no deployment target (`LSMinimumSystemVersion` is absent) and uses a floating `macos-latest` CI runner, so the floor is whatever that runner's Python targets. **OPEN for the owner:** name a minimum, then pin it in the build. The macOS wizard and companion lag Windows by one release and the macOS first-run has not been run on a clean Mac (MACOS_FIRST_RUN) |
| Linux | Not supported | |
| Machine management | **Unmanaged machines only** | No MDM and no endpoint-protection policy that blocks unsigned software. The beta builds are **unsigned** (no Authenticode, no Apple Developer ID): see `legal/BETA_AGREEMENT.md` section 4. A written SmartScreen and System Settings click-through guide is **owed** (launch-shape decision, GL-30 doc half); none exists in `INSTALL.md` yet |
| Browser | A current Chrome, Edge, Safari or Firefox | For the dashboard and the b-roll, music and Cards pages |

## DaVinci Resolve

- **DaVinci Resolve Studio** (paid) is required. The free edition does not
  expose the scripting API the companion uses (`EDITOR_SETUP.md`); the wizard
  and the companion should say so, and a machine on Resolve Free is
  unsupported.
- **Resolve 20 Studio is the version the code was written and checked
  against** (`resolve_prefs.py` reads its preference keys off a live Resolve
  20). Earlier majors (18, 19) and later ones are **UNVERIFIED**: no
  version or edition check exists in the code yet (COM-M52), so an
  unsupported build is not refused, it may simply misbehave. External
  scripting must be set to Local or Network in Resolve's preferences.
- Resolve's script server and the launch-order rule (CR-68) mean the
  companion waits for Resolve to be ready; that is expected, not a fault.

## Server (the NAS)

| Platform | Supported |
|---|---|
| **TrueNAS SCALE 25.x** (25.10 is what the studio runs and what the REST and SSH install path was written against), and **26** | Supported from launch (CR-365, owner decision 2026-10-07): 25.04 and later talk JSON-RPC over the websocket, which is the only API on 26 (REST was removed); 24.10 and older fall back to REST and are not a supported version. The JSON-RPC path is written from the published middleware API and tested against an in-process peer: the first run on a real 26 box is still owed, and a 26 key needs its account named (`DASH_NAS_API_KEY_USER`) |
| **Synology DSM 7.2.1** (tested on a DS423+, 7.2.1-69057 Update 6) | DSM 7.2 and later are the documented floor (`SERVER-SYNOLOGY.md`); DSM 7.2.1 is the only version actually tested. The install admin must be in `administrators` with 2FA off |
| Other NAS or a plain Linux box | Not supported |

One NAS per site. It holds the tree, the dashboard container and Syncthing.

## Network: Tailscale

- Tailscale on the NAS and on every editor machine is part of the product's
  perimeter, and **Tailscale Serve is the only supported way to publish the
  dashboard** with TLS.
- **Business use needs a paid Tailscale plan.** Tailscale's free Personal plan
  is for non-commercial use; a studio needs Standard (or higher) per user. That
  cost is the customer's and belongs in any quote (COM-M39). The older note
  in `APPLIANCE_INSTALL.md` that the free tier is enough is wrong for a
  business.
- Tailscale Funnel (used for public client share links) is a capped beta
  service; treat it as best effort and do not depend on it for delivery.

## Base rig

An operator's Windows 10 22H2 or 11 x64 machine with Python 3.11+ and git, for
the install and release scripts (`INSTALL.md`).

## What this page does not promise

During the free beta none of the above carries a service level
(`legal/BETA_AGREEMENT.md`). The page is the list we test against and will
try to keep true.
