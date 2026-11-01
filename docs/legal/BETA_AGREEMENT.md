<!-- DRAFT FOR COUNSEL. Written 2026-10-07 (CR-377, owner decisions of
     2026-10-07: free open beta, unsigned builds, customer self-install).
     Maintainers: this is a SUPPLEMENT to docs/legal/EULA.md (version 1.1),
     not a change to it. Do NOT edit the EULA or its EULA-VERSION marker to
     carry beta terms: a bump sends every editor in every fleet back through
     acceptance. Where the two conflict, counsel to decide which prevails;
     the draft below says this agreement prevails for the beta only. -->

<!-- BETA-AGREEMENT-VERSION: 0.1 -->

# CC Sync: free open beta terms

**Version 0.1 (draft), 2026-10-07.**

These terms apply to a Customer that uses CC Sync during the free open beta,
in addition to the End User Licence Agreement (`docs/legal/EULA.md`, "the
EULA"). They are accepted by the Customer when it signs up for the beta, by email to the
support address, before the Customer installs the Software. The Software does
not yet present or record them (the installer and the first-run wizard show only
the EULA). Defined words have the meaning they have in the
EULA. **Cablewrap Creative Ltd.** ("the Licensor", "we") is a company
registered in Taiwan (R.O.C.).

## 1. What the beta is

The Software is pre-release. It is supplied free of charge, for evaluation and
real use at the Customer's own risk, while we find and fix problems. The
Licensor may change, remove or break a feature during the beta, including one
the Customer relies on.

## 2. As is, no uptime promise

The Software is supplied **as is and as available**. We give no promise of
availability, uptime, response time, or fitness for a particular purpose, to
the fullest extent the law allows. Nothing in these terms limits a liability
that cannot lawfully be limited.

**Keep your own backups.** The Software syncs and moves footage. The
Customer's tree must also exist somewhere the Software cannot delete it
(`docs/BACKUP_RESTORE.md`). The Customer, not the Licensor, is responsible for
the safety of its media.

## 3. A site may need to be set up again

A beta release may change how a site is stored or configured. The Customer
accepts that an update can require it to repeat the setup wizard, re-enter
settings, re-register computers or reinstall the dashboard container, and that
we may not provide an automatic migration for every beta build.

## 4. Unmanaged machines, unsigned builds

- **Supported machines are unmanaged ones** (no mobile-device management and
  no endpoint-protection policy that blocks unsigned software), on the
  platforms listed here: Windows 10 22H2 or Windows 11 (x64); macOS on
  Apple silicon; DaVinci Resolve Studio (version 20 is the one we have
  checked); a TrueNAS SCALE 25.x or 26 server or a Synology DSM 7.2.1 server;
  and a paid Tailscale plan for business use. We do not support the
  Software on a machine whose administrator controls what may run.
- **The beta builds are not code-signed.** They carry no Windows Authenticode
  certificate and no Apple Developer ID. Windows will show "Unknown
  publisher" and SmartScreen may need a click-through; macOS will need the
  Customer to allow the app in System Settings, and may ask again after an
  update. Updates inside the product are still verified by an Ed25519
  signature that the Software checks itself (`docs/legal/PRIVACY.md`
  section 10), which is not the same as operating-system signing. The
  Customer accepts this and decides for itself whether to run an unsigned
  build.

## 5. Support

Support during the beta is **best effort**, by email to support@thecreatorsclub.co, on business days, with no response or fix time. We may
ask for a diagnostics bundle or log. What we may ask for, how it is sent and
how long we keep it are in `docs/legal/SUPPORT_DATA_PROCEDURE.md`; where we
process personal data for support, `docs/legal/DPA.md` applies. We will not
join a remote session or read a bundle without the Customer's say-so.

## 6. Feedback

Feedback the Customer sends about the Software may be used by the Licensor to
improve it without payment or restriction. It does not include the Customer's
footage, projects or personal data.

## 7. Ending the beta, and ending these terms

- The Licensor may end the beta, end a Customer's participation, or move the
  Software to paid terms **on notice** (at least 30 days, unless a security,
  legal or abuse reason needs sooner), by email or in the dashboard.
- The Customer may stop at any time by uninstalling.
- Moving to paid terms is never automatic: continued use after the beta needs
  the Customer's acceptance of the then-current terms. Until then the Software
  keeps working as far as technically practical for a reasonable wind-down
  period, but we do not promise it.
- Sections 2, 5 (as to data handling) and 6 survive ending.

## 8. Relationship to the EULA

The EULA stays in force. **For the beta only**, where these terms and the EULA
differ, these terms apply. They do not change the EULA's text or version, and
they do not replace the Privacy policy (`docs/legal/PRIVACY.md`) or the
Telemetry disclosure (`docs/legal/TELEMETRY.md`).

## 9. Open points for counsel

1. Whether acceptance of these terms by email at beta sign-up, before install
   (the Software does not yet present or record it), binds the Customer, given
   the EULA's per-editor acceptance step (PRAC-40).
2. Governing law and forum for a free beta (the EULA's Taiwan courts clause
   may be unwelcome to consumers or small EU businesses).
3. Whether the "as is" wording is effective in the Customer's jurisdiction,
   and what a beta must say to a consumer rather than a business.
4. The wind-down wording in section 7.
