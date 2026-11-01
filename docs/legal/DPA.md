<!-- DRAFT FOR COUNSEL. Written 2026-10-07 (CR-377, COM-M4). A template: the
     bracketed items are filled per Customer. Facts in Annex I and II are
     drawn from docs/legal/TELEMETRY.md and docs/legal/PRIVACY.md as at
     2026-10-07; re-read both after any change to what the Software reports
     or to the support procedure. -->

<!-- DPA-VERSION: 0.1 -->

# CC Sync: data processing agreement (GDPR Art. 28)

**Version 0.1 (draft), 2026-10-07.**

Between **[Customer legal name and address]** ("the Controller") and
**Cablewrap Creative Ltd.**, No. 111, Minquan Road, Zhuwei Village, Tamsui
District, New Taipei City 251, Taiwan (R.O.C.) ("the Processor").

## 1. When this agreement applies

CC Sync is self-hosted. In normal operation the Processor receives **no**
personal data, runs no server holding the Controller's data and is **not** a
processor (`docs/legal/PRIVACY.md` section 3).

The Processor is a processor **only** when the Controller sends it, or gives it
access to, material containing personal data in order to obtain support: a
diagnostics bundle, a log, a database copy or a screenshot sent to the support
mailbox, or a remote session on a Controller's machine. This agreement covers
exactly that and nothing else. If the Controller never does so, nothing under
it happens.

## 2. Processing terms (Art. 28(3))

1. The Processor processes the personal data **only on the Controller's
   documented instructions**, which are: use it to diagnose and resolve the
   support request it was sent for. Sending the material is the instruction.
   The Processor tells the Controller if it believes an instruction infringes
   data-protection law.
2. Persons authorised to process it are bound by confidentiality, and access
   is limited to those working on the request
   (`docs/legal/SUPPORT_DATA_PROCEDURE.md`).
3. **Security** (Art. 32): the measures in Annex II.
4. **Sub-processors**: only those in Annex III. The Processor gives the
   Controller at least 30 days' notice of a new one, by email; the Controller
   may object on reasonable data-protection grounds, and if the parties cannot
   agree the Controller may stop sending support material. The Processor
   imposes the same obligations on a sub-processor and remains liable for it.
5. **Assistance**: the Processor helps the Controller, by appropriate measures
   and at no charge during the beta, to answer data-subject requests and to
   meet Arts. 32 to 36 so far as the Processor holds the data. Because the
   Processor holds only support material, a request is normally answered by
   deleting or returning that material.
6. **Breach**: the Processor notifies the Controller without undue delay, and
   in any case within 48 hours of becoming aware, of a personal-data breach
   affecting the Controller's data, with what it knows.
7. **Deletion or return**: at the end of the support request, and in any case
   by the period in `docs/legal/SUPPORT_DATA_PROCEDURE.md` (30 days after the
   ticket closes), the Processor deletes the material, including from the
   mailbox's trash, or returns it on request.
8. **Audit**: the Processor makes available the information needed to show
   compliance and allows an audit by the Controller or its auditor on 30 days'
   notice, no more than once a year unless a breach requires it, during
   business hours and subject to confidentiality. [Counsel: the Processor is a
   small company; an information-request route may be preferred to on-site
   audit.]

## 3. International transfers

The Processor is in Taiwan, which has **no EU or UK adequacy decision**
(owner and counsel to confirm the current position before signature). Where
the Controller is subject to the GDPR or UK GDPR, the transfer of support
material to the Processor is a restricted transfer, and the parties agree:

- **EU:** the Standard Contractual Clauses (Commission Implementing Decision
  (EU) 2021/914), **Module Two (controller to processor)**, are incorporated.
  Clause 7 docking: [included]. Clause 9(a): option 2 (general written
  authorisation, 30 days). Clause 11 optional redress: [not included].
  Clause 17: law of **[Member State, Ireland suggested]**. Clause 18: courts
  of **[same Member State]**. Annex I.A (parties), I.B (description of
  transfer) and I.C (competent supervisory authority, **[to complete]**) are
  Annex I below; SCC Annex II is Annex II below; SCC Annex III is Annex III
  below.
- **UK:** the **UK International Data Transfer Addendum** to the EU SCCs
  issued by the ICO (version B1.0), or alternatively the UK IDTA, **[select
  one]**. **[Placeholder: Tables 1 to 4 of the Addendum (parties, selected
  SCCs, appendix information, which party may end the Addendum on an ICO
  change), completed from this agreement.]**
- **Taiwan transfer note.** Taiwan's Personal Data Protection Act restricts
  transfers OUT of Taiwan by the Processor, not a Controller's sending material
  in. The Processor passes support material on only to the sub-processors in
  Annex III, whose servers may be outside Taiwan. **[Counsel: confirm the PDPA
  treatment, and whether a Taiwan Controller needs anything further.]**

If the SCCs and this agreement conflict, the SCCs prevail.

## 4. Liability, term, law

**[Counsel.]** Suggested: liability follows the EULA and the beta terms
(`docs/legal/BETA_AGREEMENT.md`), except that nothing limits a liability that
cannot lawfully be limited. Term: until all support material is deleted.
Governing law: as the EULA, except where the SCCs require otherwise.

---

## Annex I: description of the processing

**A. Parties.** As above. Controller's contact: **[ ]**. Processor's contact:
contact@thecreatorsclub.co. The Processor has appointed no data protection
officer and no EU or UK representative **[counsel: Art. 27 representative
question]**.

**B. Description of the transfer and processing.**

| Item | Description |
|---|---|
| Data subjects | The Controller's editors, administrators and other staff who use CC Sync, and any person named in the file names, project names, logs or footage in the material sent |
| Categories of personal data | Those the Software records (field by field in `docs/legal/TELEMETRY.md`): editor username and display name; computer hostname; the DaVinci Resolve project open and when; seconds since last keyboard or mouse input (never the input itself); file names and paths, which can contain project, client and user names; sync lane state, errors and transfer throughput; media-pool bin structure and clip paths; IP addresses and tailnet device names in logs; dashboard audit entries; free text a person types into a support request |
| Sensitive data | None intended. The Software does not collect special-category data; footage or a screenshot in a bundle could incidentally show some. The Controller should not send such material |
| Frequency | One-off, per support request |
| Nature and purpose | Reading, storing, analysing and replying, to diagnose and fix a fault in CC Sync. No other purpose, no profiling, no use to train a model (`docs/legal/SUPPORT_DATA_PROCEDURE.md`) |
| Retention | Until the request closes plus the deletion period in `SUPPORT_DATA_PROCEDURE.md`, then deleted |
| Transfers to sub-processors | As Annex III |

**C. Competent supervisory authority.** **[The authority of the Controller's
EU Member State; for the UK, the ICO.]**

## Annex II: technical and organisational measures

Drawn from `docs/legal/PRIVACY.md` section 10 and
`docs/legal/SUPPORT_DATA_PROCEDURE.md`. The Software's own measures protect the
Controller's deployment; this annex covers the Processor's handling of support
material.

- Support material is received only at the support mailbox, under a Google
  Workspace account with two-step verification, and is not forwarded to
  personal accounts or chat tools.
- Access is limited to named people working on the request. Remote sessions
  happen only when the Controller starts them and can end them, are logged,
  and use the Controller's own tailnet or a screen-share the Controller
  controls.
- Material is encrypted at rest by the provider, and on an encrypted disk where
  saved locally, in one folder per request, and is deleted at the end of the
  period.
- The Software removes the companion's own token from a diagnostics bundle
  before sending it (`TELEMETRY.md`, "diagnostics bundles").
- Breach handling: section 2.6.
- Updates to the Software are signed (Ed25519) with a release key the Processor holds as a
  passphrase-protected key file with offline backups (a hardware token is
  planned before the paid release), and verified by the Software against the
  public keys built into it before they are applied.
- Processor staff are bound by confidentiality. **[Owner/counsel: add any
  certification or policy actually held; none is claimed here.]**

## Annex III: sub-processors

| Sub-processor | Purpose | Data | Location | Safeguard |
|---|---|---|---|---|
| **Google Workspace** (Google Ireland Limited for EEA and UK customers, otherwise Google LLC) | The support mailbox (support@thecreatorsclub.co): receives, stores and delivers support material | Whatever the Controller emails | Google data centres, including the US | Google's Cloud Data Processing Addendum, with SCCs and the EU-US Data Privacy Framework where applicable |
| **GitHub, Inc.** (Microsoft) | The release feed, a static file host for update downloads. Receives **no** support material and no Controller data; the requesting dashboard's IP address is visible to it. Listed for completeness, not as a processor of support material | The requester's IP address | US | GitHub's data protection terms |

The Processor does not use any AI service or AI tool to read support material
(logs, diagnostics bundles, screenshots or mail), and commits not to
(`docs/legal/SUPPORT_DATA_PROCEDURE.md`). Should that ever change, this annex
is updated and the Controller notified under section 2.4 **before** any support
material is sent to such a service.

Anything else support touches (a remote-session or screen-share tool the
Controller itself chooses, or a tailnet the Controller owns) is the
Controller's own supplier and not the Processor's sub-processor, unless the
Processor supplies the account.
