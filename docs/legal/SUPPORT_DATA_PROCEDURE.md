<!-- DRAFT FOR COUNSEL. Written 2026-10-07 (CR-377, COM-M4, COM-H12, GL-34).
     One page: how the Licensor's support handles what a customer sends.
     The customer-facing counterpart is the DPA (docs/legal/DPA.md). -->

# CC Sync: support data procedure

**Version 0.1 (draft), 2026-10-07.** Applies to support during the free open
beta (`docs/legal/BETA_AGREEMENT.md`). Support is best effort.

**Principle.** CC Sync is self-hosted and sends no Customer data to the Licensor
on its own (a vendor-build dashboard's check of the Licensor's release feed
carries none; see `PRIVACY.md` section 5). Support sees only what the
Customer chooses to send, and only for the problem at hand.

| Question | Answer |
|---|---|
| **What may support ask for** | A diagnostics bundle (the button in the companion, or Health in the dashboard: versions, settings, lane states, recent crash summaries, the last 40 log lines, no tokens), the companion log, `syncthing.log`, a screenshot of the error, and the exact steps. Nothing else by default. Support does **not** ask for the dashboard database, the footage, passwords, tokens, API keys or cookies, and tells the customer to redact them if they appear |
| **How it is sent** | By email to the support mailbox (support@thecreatorsclub.co, a separate mailbox from the privacy and security contact), from an address the Customer chooses. No upload site, no chat tool. A customer may redact or trim a bundle first |
| **Where it is kept** | In the support mailbox (Google Workspace, listed as a sub-processor in `DPA.md`) and, if it must be unpacked, in one folder per request on an encrypted disk of a named support person. Never in a shared drive, a ticket tool, a public repo or an issue tracker. Findings that go into the repo (a bug entry) are written without names, paths or hostnames from the customer |
| **Deletion period** | **30 days after the request (ticket) is closed** (owner decision, 2026-10-07), including the mailbox's trash and local copies. A customer may ask for earlier deletion at any time. The only thing kept afterwards is a note of the request that contains no customer material |
| **Who may access** | The named people working the request, which during the beta is the owner and anyone he names in writing for it. No contractor or reseller sees it without the Customer being told first |
| **Remote sessions** | Only at the Customer's invitation, time-limited, started and ended by the Customer, who can end it at any moment. Support states beforehand what it will look at, changes nothing without saying so, never opens footage or personal files, never takes files away, and writes down the start and end time. Credentials are never shared; a session uses the Customer's own tailnet or a screen-share the Customer controls, never a permanent back door |
| **Breach** | The Customer is told without undue delay and within 48 hours (`DPA.md` section 2.6) |

## AI tools never read support data

**Decided by the owner, 2026-10-07: no.** No customer support material is
pasted into, uploaded to or read by an AI tool, including this repository's
own AI tooling. If that ever changes, it is a further sub-processor under
`DPA.md`: change `DPA.md` Annex III, `PRIVACY.md` section 9 and this page
together, and tell customers first.

## Other open points

1. Who may be "named" during the beta (deletion is 30 days after the ticket closes, decided).
2. Whether a support mailbox shared by more than one person needs an access
   log.
