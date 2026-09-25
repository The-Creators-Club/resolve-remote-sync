# Ledger, wave 2, group "owner" (owner decisions, no code files)

The "owner" group owns no files. It collects items other builders found that
need the owner's (or counsel's) decision rather than a builder's edit. Nothing
below was changed in the tree; each item says what decision is needed.

## Owed round

### ui-comp-windows-3 (from c-app) - EULA.md text is still a counsel draft
- Status: DEFERRED (owner / counsel decision)
- Verified as: `grep -a` on 2026-09-25. The three copies
  (`companion/src/ccsync_companion/assets/EULA.md`, `onboarding/assets/EULA.md`,
  `docs/legal/EULA.md`) are identical in the lines that matter: line 19 (VISIBLE,
  survives c-app's `_licence_display_text` comment strip) reads
  "Version 1.0 - draft of 2026-08-17. DRAFT FOR COUNSEL."; line 21 names
  **Cablewrap Creative** as licensor (a retired brand, memory: owner email is
  thecreatorsclub.co since 2026-09-04); line 185 leaves
  "[TODO(legal): jurisdiction]" as governing law; line 196 carries
  "TODO(legal): registered entity name, company number". c-app fixed the
  display half (the HTML counsel comment, markup and em dashes no longer
  reach the dialog).
- Why not done by a builder: the words of a licence are counsel's and the
  owner's (CLAUDE.md: `docs/legal/` is DRAFT FOR COUNSEL). A builder
  inventing a licensor entity or a jurisdiction would put an unreviewed legal
  claim in front of every editor. Also, changing the text and bumping
  `EULA-VERSION` pushes every editor in every fleet back through the licence
  gate (and 0.9.x refuses to sync until they accept), so the edit should be
  made once, with the final text.
- Decision needed from the owner: (1) the registered legal entity that
  licenses the software (replaces "Cablewrap Creative" at lines 21 and 196,
  and in `docs/legal/PRIVACY.md`); (2) the governing-law jurisdiction
  (line 185); (3) whether the document is final, so the "DRAFT FOR COUNSEL"
  line 19 and the header comment go. Once decided: edit `docs/legal/EULA.md`,
  copy it byte-identical to the two asset copies, bump `<!-- EULA-VERSION: -->`
  to 1.1 (or 2.0), and ship companion + onboarding together.
- Fix: none. Regression test: none (no code change). Tests run: none.
- Skew / deploy order: when the text changes, companion and onboarding ship
  together; the version bump re-prompts every editor.
- OWED: none to a builder; owner/counsel decision as above.

### logic-resolve-3 (from c-resolve) - Resolve factory LUT copies already in P:\Assets\Luts
- Status: DEFERRED (owner decision; a destructive act on a shared folder)
- Verified as: c-resolve's ledger (listing of 2026-09-25): the library holds
  Resolve's whole factory set (ACES, Arri, Astrodesign, Blackmagic Design, DCI,
  DJI, Film Looks, HDR *, Olympus, Panasonic, RED, Samsung, Sony, VFX IO and
  the loose Canon/Cintel/Invert/Sony .ilut/.olut files), so every editor's LUT
  browser shows each twice. c-resolve's code fix (`luts.py`
  `RESOLVE_FACTORY_LUT_NAMES`) stops NEW factory copies being offered; it does
  not remove the ones already copied. I did not re-list the share (brief
  rule 9: do not touch the NAS).
- Why not done by a builder: `P:\Assets\Luts` is Syncthing-shared to every
  editor. A deletion propagates to the whole fleet, and a LUT a grade already
  references by its library path (rather than Resolve's factory path) would go
  missing in that project. Only the owner can say whether any timeline uses
  the library copies.
- Decision needed from the owner: remove the factory folders/files from
  `P:\Assets\Luts` or keep them. If remove: take a snapshot first (CLAUDE.md
  "snapshot before anything privileged and recursive"), MOVE them to a dated
  folder outside the shared tree rather than delete, and have editors restart
  Resolve (the LUT index is cached at launch). The list of names to move is
  `luts.RESOLVE_FACTORY_LUT_NAMES`.
- Fix: none. Regression test: none. Tests run: none.
- Skew / deploy order: none (data, not code); best done after companion with
  the luts.py fix is on the fleet, so nobody's Share LUTs re-offers them.
- OWED: none to a builder; owner decision as above.
