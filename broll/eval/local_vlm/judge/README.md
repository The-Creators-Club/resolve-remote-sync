# Human judge for the local-VLM b-roll eval

`score.py` (one level up) scores every local-VLM run's segments/objects/OCR/
themes/category against the Haiku baseline in `clips.json` and writes
`report.md` + `summary.json`. That's the automatic half. This directory is
the other half: a page for a **human** to actually read the frames and the
segments side by side, blind, and say which one is right — the thing
`score.py`'s "agreement with Haiku" number cannot tell you, because Haiku
itself is a reference, not ground truth (it was wrong on clip 13454; see
`score.py`'s docstring).

## Quick start

```powershell
cd broll\eval\local_vlm\judge
python build_judge.py          # writes judge.html next to this file
start judge.html                # or: double-click it in Explorer
```

That's it for Chrome/Edge — `judge.html` is fully self-contained (inline
CSS/JS, no CDN) and its `<img>` tags point at `../bundle/...` with a plain
relative path, which both browsers load fine straight off `file://`
(verified 2026-08-18 with a headless Chromium run via Playwright — filmstrip
thumbnails rendered, 0 of 1756 referenced frames missing). If you're on
Firefox, or a machine whose policy disables `file://` image loading, run the
fallback instead:

```powershell
python serve.py                 # binds 127.0.0.1 only; opens a browser tab for you
```

`build_judge.py`'s default `--clips` is `../bundle/clips.json`, **not** the
top-level `clips.json` — only the bundle has a small, relative
`frames_root`, which is what lets the generated page's image paths be
relative instead of an absolute `E:\broll-queue\...` that only exists on the
base rig. If `../bundle/` doesn't exist yet, build it first:

```powershell
cd ..
python make_bundle.py
cd judge
python build_judge.py
```

## What you're looking at

- **Top bar:** progress (`k/100`), the clip's share/path/stratum/duration,
  Export/Import, and a Summary toggle.
- **Filmstrip:** every frame the models actually saw, in order, with its
  timecode. Click a thumbnail to enlarge it and to highlight every segment
  (in every column) whose `[t_start, t_end]` covers that frame's time.
- **Columns, one per source, labelled A/B/C/…:** each lists that source's
  segments (time range, description, objects, on-screen text + its English),
  then themes/quality flags/category at the bottom. Hover or click a segment
  to highlight the filmstrip frames inside its time range; click again (or
  click empty space) to unpin.
- **The column headers are blind.** You see "A", "B", "C" — not which VLM (or
  Haiku) produced that column — until you cast a vote for that clip (a
  score, a best pick, or a flag). The moment you do, every column's header
  reveals its true source for that clip, so you can learn from the answer
  without having been biased by it while scoring. The order is re-shuffled
  independently per clip and stored in your browser (`localStorage`), so
  reloading mid-session doesn't relabel anything.

  This blinding is a **voting-bias control, not a security boundary** —
  `judge.html`'s embedded data plainly contains the true source name for
  every column of every clip (open the page source and it's right there in
  the JSON). It stops *you* from anchoring on "oh, that's the 4B model, it's
  probably worse" before you've actually read the segments; it does not stop
  a determined look at devtools.

## Voting

- **Accuracy 1–5** per column: click a number, or click the column first
  (or press it) to focus it, then press `1`–`5` on the keyboard.
- **Best**: one radio per clip, across all columns (including Haiku — if you
  think Haiku's baseline itself was the most accurate read of the shot,
  say so).
- **Flags** per column: `hallucinated`, `missed the shot`, `OCR wrong`,
  `over-segmented`.
- **Note**: one free-text box per clip, saved as you type.

Everything is written to `localStorage` immediately — close the tab, reopen
`judge.html` later (even after rebuilding it, as long as the clip ids are
the same), and your progress and votes are still there. Navigate with
`←`/`→`.

**Export** downloads `verdicts.json` — clip id, TRUE source name (never the
blind letter) per column's score/flags, the best pick, the note, and a
timestamp. **Import** restores a `verdicts.json` into `localStorage` (marked
already-revealed, since you only get an export after voting).

A **Summary** panel (top-right toggle) shows, live, per-source mean score,
times picked best and flag counts — over whatever you've judged so far in
this browser.

## Turning votes into a report

```powershell
python summarise_verdicts.py --verdicts path\to\verdicts.json
```

Writes `verdicts.md`: per-source mean/wins/flags overall and by stratum, any
notes you left, and — the actual point of this tool — how well `score.py`'s
automatic per-clip `agreement` number tracked what you actually scored
(Pearson/Spearman correlation), for every source that has already been
scored with `score.py --results-dir ...` (a `summary.json` sitting next to
its `A.jsonl`). A source without one shows "not scored yet" instead of a
number — `summarise_verdicts.py` never runs `score.py` for you (this tool
only reads results, never writes into a results directory).

## Adding a new source (e.g. the 32B lands)

Nothing to edit. Drop its `results-mac/<model>/A.jsonl` (+ `A.meta.json` if
you have it, for a nicer revealed label) where the others live, then:

```powershell
python build_judge.py
```

`build_judge.py`'s default source list is `haiku` (from the bundle's
`clips.json`), `local-4b` (`../results/A.jsonl`), plus every
`../results-mac/*/A.jsonl` it finds — so a new directory is picked up
automatically. Any clip you'd already voted on keeps its old votes; the new
source just shows up as an additional blind column (existing per-clip
letter shuffles get the new key appended, not reshuffled, so already-cast
votes for the OTHER columns on that clip stay attached to the right source).

To pin the source list by hand instead (e.g. to compare only two of them):

```powershell
python build_judge.py --source haiku=baseline --source local-4b=..\results\A.jsonl
```

`baseline` is a literal sentinel value, not a path — it means "pull segments
straight out of `clips.json`'s `baseline` field for every clip", which is
the only way to see Haiku's read of the shot at all (arm A/B/C's `A.jsonl`
files never contain it).

## Ordering and `--limit`

- `--order disagreement` (default): the 20 clips `../results/summary.json`
  flagged as furthest from Haiku (arm A) come first — the ones most worth a
  human's time — then the rest in a seeded shuffle, so a `--limit 20` run
  covers exactly the disagreement list and a `--limit 100` run (the default)
  still covers everything.
- `--order random`: all 100 clips shuffled (same fixed seed by default, so
  reruns without `--seed` reproduce the same order).
- `--order id`: plain ascending clip id — useful for a methodical pass, or
  for comparing notes with someone else who also used `--order id`.

`--limit N` judges only the first N of that order — handy for a first pass
before committing to all 100.

## Known limitations

- **Blind is UI-only**, not tamper-proof (see above).
- The per-clip letter shuffle is regenerated by each browser independently.
  Two people judging the same `judge.html` will NOT see the same letter for
  the same source on the same clip — by design (nobody should be able to
  infer "A is always the 4B model" from a pattern), but it does mean you
  can't say "I liked column B on clip 12443" to a colleague and have it mean
  anything; use the clip id and, after reveal, the true source name.
- `--order disagreement`'s "20 largest disagreements" comes from
  `../results/summary.json`, i.e. is always computed from the **local-4b**
  (arm A, base rig) run specifically — it's a fixed, reasonable set of
  hard/interesting clips, not a live recomputation across every source you
  hand this script.
- `summarise_verdicts.py`'s automatic-vs-human correlation is only as good
  as how many clips you've actually scored for that source — Pearson/
  Spearman on a handful of points is noisy; the table reports `n` for
  exactly this reason.
