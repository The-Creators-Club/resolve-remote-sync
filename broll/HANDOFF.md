# Session handoff — 2026-08-02

What changed, why, and what is still open. Written at the end of a long session;
the reasoning matters more than the diff, because several decisions reversed
earlier ones on measured evidence.

---

## 1. The archive is the centre of the design now

Everything an editor touches lives in one tree on the NAS:

```
P:\Assets\B-roll Archive\                    (= /mnt/tank/TheCreatorsPool/Creators_Club/Assets/B-roll Archive)
  broll.db                                   the search index the dashboard serves
  posters\  sprites\                         browse thumbnails
  Downloads\<group>\<subject>\
      <name>.mp4                             BEST MEDIA — what Resolve imports and renders from
      Proxy\<name>.mp4                       540p preview — what the browser plays, what syncs cheap
  Creators_Club\<share>\<Day N>\<camera>\
      <name>.mov                             the shoot's own HEVC editor proxy
      Proxy\<name>.mp4                       540p preview
```

**One rule, both collections: best media in the folder, preview in `Proxy/`.**

For Downloads the top file is the real original. For Creators_Club it is the
shoot's own editor proxy, which Resolve treats *as* the original. The point is
that every clip is ONLINE and renderable, with no per-collection special case.

Why `Proxy/` specifically — this is load-bearing, not tidiness:

- cc_sync **lane B** (`build_filter_rules_down`) syncs exactly `**/Proxy/**`, so
  previews fan out to editors through machinery that already exists.
- **lane A** (`build_filter_rules_up`) *excludes* it, so an editor can never
  upload archive media back over the top.
- Resolve and `proxy_relink.expected_proxy_paths` both look for a proxy at
  `<parent>/Proxy/<stem>`, so **the proxy auto-attaches at import** with no
  scripting at all (verified live, see §4).

Current contents: **2,093 originals (279.7 GB) + 2,093 previews (54.7 GB)**.
MOFA is being added now.

### Requirement this imposes on sync (task #17)

The archive **must** land at `<local_root>\Assets\B-roll Archive\` on each
editor's machine. `P:` resolves to `local_root`, so `Assets/` beside `Projects/`
is in-tree by construction and `classify_path` returns `OK`/`MISSING`. Put it
anywhere else and **every archive clip classifies `OUT_OF_TREE` and pops the
fixer dialog on every scan**. Verified by direct test, not assumed.

---

## 2. Deployed and working

The b-roll UI is **mounted in-process in the cc_sync dashboard at `/broll`**
(`dashboard/src/ccsync_dashboard/broll.py`), behind `DASH_BROLL_ENABLED`.
Confirmed working remotely over Tailscale from alex_laptop.

Three things about the mount that are easy to break:

- **Auth is inherited.** Starlette middleware wraps mounts, so `login_gate`
  already covers `/broll/*`. The b-roll app must never grow auth of its own.
  `/broll/api/*` and `/broll/media/*` return **401 JSON**, not a 303 — `fetch()`
  and `<video>` cannot follow an HTML redirect.
- **The sub-app's lifespan does NOT run.** Starlette only runs the outermost
  app's. `broll._init_broll_storage()` replicates it; without it the first
  request hits a database that was never created.
- **`BROLL_INGEST_TOKEN` is mandatory.** The b-roll app treats an unset token as
  dev mode and allows ingest with *no* credential — harmless standalone, an
  unauthenticated write path on the fleet's origin once mounted. The dashboard
  refuses to open the ingest carve-out unless it is set, so blank means
  unreachable rather than open.

`DATA_ROOT` is the archive itself, so one set of media serves both the search UI
and editors' timelines.

---

## 3. Decisions that reversed on evidence

Each of these started as the opposite and changed because something was measured.

| Believed | Measured | Now |
|---|---|---|
| Re-encode MOFA's proxies for the archive | They are 1080p HEVC Main 10; our pipeline emitted 540p H.264 — a worse second generation | Copy the `.mov` **verbatim** |
| Generate 1080p editing proxies for the 402 downloads lacking one | Originals are **279 GB**; editor proxies for the same clips are **614 GB**. These are YouTube files — a "proxy" is *bigger than its source* | Put the **originals** in the archive. `build_editing_proxies.py` is dead; delete it |
| MOFA too expensive to index (`index: false`) | Clips average 8–15 s / 4–5 scenes → **1 contact sheet = 1 model call each**; frames stage runs at 33× realtime | Indexed like any other share |
| Whisper gives MOFA free speech search | It is cutaways with incidental crew chatter | `transcribe: false` — the cues are *noise in the index*, worse than nothing |

The `max_sheets_per_video` cap (commit `0d984dc`) is a **long-clip** problem —
9% of the YouTube archive consuming 36% of calls. MOFA is the opposite shape and
needs no cap.

---

## 4. Verified against live Resolve

Tested in a throwaway project on Resolve Studio 21.0.1 (archive untouched):

- The adjacent `Proxy/` file **auto-attaches at import** — no `LinkProxyMedia`.
- `LinkProxyMedia` **succeeds even with the original absent** (validates against
  project metadata, not the file).
- Proxy attachment **survives close/reopen**; timeline in/outs intact.
- **You cannot render while the original is offline.** Deliver hard-fails with
  "Full resolution media not found" — no Prefer Proxies override, no scriptable
  switch. *This is why the top slot is always populated.*
- **`MediaPool.RelinkClips` works** (used nowhere in either repo before): folder
  + name matched, flips clips online, **keeps the proxy attached**. That is the
  conform gesture for task #19.
- Deleting a file Resolve has open leaves **stale state** — `Online Status` lies
  until reopen, and rendering in that window **wedged the render pipeline** until
  `StopRendering()`.

---

## 5. Stability guarantees now enforced in code

- **Categories never move.** `taxonomy assign` only fills `category IS NULL`;
  a filed clip keeps its category even if better rules would move it, because
  the category is in its archive path and timelines point at it. `--reassign`
  is the supervised escape hatch and says so.
- **Archive paths are deterministic.** `dedupe()` resolves collisions against
  names claimed *within the run*, never against disk — checking disk made the
  second build rename all 2,093 clips to `_2`.
- **`index: false` is reversible.** `reopen_if_now_indexable()` returns
  `organised` clips to `proxied` when the flag flips; without it they were
  stranded, invisible to every runner while looking finished.

---

## 6. Bugs found and fixed this session

- **CRLF took the dashboard down.** `pathlib.write_text` converted `run.sh` to
  CRLF; `sh` rejected `set -eu\r` and the container crash-looped. *Always write
  deploy files with `newline="\n"`.* Diagnosed far too slowly — `docker logs`
  first, not `curl` polling.
- **Present-but-null segment fields.** Validation checked keys were *present*,
  not that they held a value, so `{"t_end": null}` passed and died at the INSERT
  on a NOT NULL column — discarding a clip's whole index after its calls were
  paid for. 5 clips requeued.
- **`objects` is a list, not a string.** A coercion fix nearly wiped every object
  keyword; caught by tests.
- **Uncategorised bucket counted wrong.** `category IS NULL` also matches every
  *not yet indexed* clip — the folder promised 163 and delivered 1,414.
- **546 wasted API calls.** `run_queue.py` polled blindly every 15 min; each
  retry fired ~26 concurrent calls that all 429'd. Now sleeps until the reset
  time the error itself names.

---

## 7. State right now

```
indexed  2093     discovered 646    proxied 190
excluded  558     skipped   2103    probed   3    error 5
```

**RUNNING:** MOFA local pass (`parallel_local.py --workers 4`, pid was 24116,
log `E:\broll-queue\mofa-local-20260802-165536.log`). ~688 eligible; expect
**554** MOFA clips to reach `proxied` (4 are over the 5-minute cap and are
dropped at probe, the cheapest possible place).

Tests: **434 indexer · 136 web · 311 dashboard · 50 companion.**

### Must run after the MOFA pass, or the clips stay invisible to editors

1. `build_archive.py --config config.queue.yaml --dest "P:/Assets/B-roll Archive" --apply`
2. `broll-index origins --verify`
3. `broll-index taxonomy assign taxonomy.rules.yaml`
4. the `embed` stage
5. `copy E:\broll-queue\broll.db "P:\Assets\B-roll Archive\broll.db"`

Then the API stage: **554 MOFA (1 call each) + 130 outstanding YouTube**, via
`indexer\watchdog.ps1 -Force`. Note the watchdog scheduled task is **Disabled**.

---

## 8. Open, with task numbers

- **#17** sync the archive to editors — must land at `<local_root>\Assets\…`
  (§1). Decide whole-tree vs sparse: 334 GB will not go down a residential link.
- **#18** loopback insert server in the cc_sync tray. Much smaller than planned:
  look up `archive_path`, canonicalise, import, append. No delivery, no copy, no
  cleanup. Must ride `_API_LOCK` — two processes driving `fusionscript.dll`
  crashed with `0xc0000005`.
- **#19** conform tool — relink to true originals via `RelinkClips`.
  `videos.original_path` now records where every original lives (5,040 rows,
  verified). MOFA proxies pair to the right camera by (directory, stem), not
  stem alone — 0 mispairings across 558.
- **#23** 4 clips whose preview and original stems diverged (dedupe ran
  independently for the two files, which have different extensions). Low
  urgency; only Resolve auto-attach is affected.
- **#15/#21** largely obsolete — the archive-root design removed the manifest
  and settled the tiering. Read before acting on them.
- **#5** 130 YouTube videos still unindexed.
