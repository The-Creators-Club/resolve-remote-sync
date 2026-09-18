# CR-293 - the refresh that was remembered on a flap, and the .mp4 refusal that was not the archive's - FIXED in repo 2026-09-18 (mediums wave, companion-resolve)

Two confirmed mediums in `proxy_relink.py` + `resolve_bridge.py`, both about
phase 3's editing-proxy/stand-in machinery answering a question it was never
asked.

### CR-293A (comp-resolve-2) - a forced refresh in which ReplaceClip RAISED is remembered for ever as settled - FIXED (resolve_bridge.py, proxy_relink.py)

`replace_clip` answered `ok: False` only when `raised == max(1, tries)`, so a
burst in which one or two of the three `ReplaceClip` calls raised (Resolve
mid-render, a script-server flap) and the surviving call did not move the
geometry returned `{"ok": True, "changed": False}`. `apply_relinks` treats
`changed is False` as a permanent verdict and calls `note_geometry_verdict`,
whose only expiry is the proxy file's `(mtime, size)` - which for a file whose
original has already arrived never changes again. Phase 3's one mechanism was
therefore disarmed for that clip for the life of the process, silently. The
fix is the verifier's cheaper half: the forced arm now returns
`retryable: True` when `raised > 0` (still `ok: True`, so the clip does not
fall into `failures` / `REASON_NO_ANSWER` and the RES-3 channel reports
nothing new), and `apply_relinks` skips `note_geometry_verdict` on that flag
and logs "asking again next pass". The `changed is True` branch, which
deliberately notes a verdict under the pre-call `stored_frames`, is untouched.
Three tests: the consumer does not remember a flap, a CLEAN no-change refresh
is still remembered (CR-284R must not be lost), and the producer - the real
`replace_clip` driven with a stub item whose first two `ReplaceClip` calls
raise - says `retryable`.

### CR-293B (comp-resolve-3) - the `.mp4` refusal was not scoped to the b-roll archive - FIXED (proxy_relink.py)

`plan_relinks` refused a `Proxy/<stem>.mp4` offer on "the file exists and is
not a ledgered stand-in" with no `_under_archive` test, although every comment
on the rule says "in the archive that file is the browser PREVIEW". Outside
the archive a `.mp4` proxy is a perfectly good one: `GENERATED_EXT` became
`.mov` only at R14 (2026-08-19) and `proxy_scan.py` states in capitals that
existing `.mp4` proxies stay valid and are never re-made, so every pre-R14
project proxy in the fleet was silently never attached - no op AND no `notes`
entry, so the RES-3 "why is my proxy not attached" channel, the tray line and
the log all said nothing. `_under_archive` is now hoisted into a local (it was
already computed six lines above for the refresh gate) and the refusal is
gated on it; when the rule does fire, a `notes` entry carries the new
`REASON_ARCHIVE_PREVIEW`, so an archive refusal is explainable instead of
invisible. The insert side (`resolve_bridge._attach_adjacent_proxy`) was left
alone on the verifier's narrowing: its only caller is the b-roll insert, so it
is archive-scoped by construction. Two tests: a project clip's legacy `.mp4`
is planned again, and an archive preview is still refused and now says why.

### Verification
- comp-resolve-2: `test_a_refresh_in_which_resolve_raised_is_not_remembered_for_ever`, `test_a_clean_refresh_that_did_not_move_is_still_remembered`, `test_replace_clip_says_a_partly_raised_refresh_is_retryable` - all three red with the two hunks reverted in place, green after.
- comp-resolve-3: `test_a_legacy_project_mp4_proxy_is_still_attached` red with the `under_archive` gate removed, green after; `test_an_archive_preview_is_still_refused_and_now_says_so` guards the half that stays.
- Re-run green together with `test_proxy_relink.py`, `test_proxy_relink_standins.py`, `test_bug_hunt_2026_09_18_companion_media.py`, `test_bug_hunt_2026_09_18b_companion_media.py` (116 passed), plus `test_resolve_bridge.py` + `test_watcher.py` (188) and `test_no_em_dash.py` (103).

### Not fixed
- Nothing from this group's list. `watcher.py` needed no change.

### OWED TO ANOTHER GROUP
- None. Both halves of each fix are inside this group's files.
- Worth knowing for whoever owns the tray/popup copy later: `REASON_ARCHIVE_PREVIEW` is a new editor-visible string in `proxy_relink.py`, surfaced through `plan_relinks`' `notes` and whatever the caller does with them. No other file needs a change for it.

### Deploy order
- Companion-only, no wire change. Any dashboard, old or new, is unaffected.

### Owner decisions
- None needed.
