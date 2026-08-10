# Overnight indexing run

One command. It finishes any remaining local work first (no API usage), then
indexes, then builds search vectors.

```powershell
Start-Process -FilePath "C:\Users\alex\AppData\Local\Programs\Python\Python312\python.exe" `
  -ArgumentList "-u","run_queue.py","--config","config.queue.yaml","--model","haiku","--api-workers","12" `
  -WorkingDirectory "E:\Projects\broll-platform\indexer" `
  -RedirectStandardOutput "E:\broll-queue\claude.log" `
  -RedirectStandardError "E:\broll-queue\claude.err" -WindowStyle Hidden
```

Leave it running; come back in the morning.

**Start it detached, as above — not in the foreground.** Three runs on 2026-07-22
were launched inside a terminal/agent session and every one of them was killed
when that session ended, one of them seconds after it started. Fourteen hours
produced nothing. `Start-Process` outlives the shell that launched it.

`--api-workers` is the throughput knob: that many `claude -p` calls run at once.
Serial (`1`) measured a flat 20 videos/hour — over 100 h for a 2,000-video
queue — while the machine sat at 12% CPU with 97 GB of RAM free, because the
stage waits on one round-trip at a time. Raising it cannot raise the account's
usage ceiling, only reach it sooner; past that point the run goes bursty
(index, wait out the limit, resume) and the ceiling sets the pace.

## What it does, in order

1. **Local phase** — probe, transcript ingest, proxy encode, contact sheets, in
   4 parallel workers. **No API usage.** Skipped instantly for anything already
   done, so it costs nothing if the local run already finished.
2. **Index phase** — the only stage that spends usage.
3. **Embed phase** — semantic vectors. Local and free.

Running the whole thing as one command matters: `--stages claude` alone would
index only the videos that happened to be ready and then stop, silently
leaving the rest unindexed.

## Ending a run at a set time

`--deadline 2026-07-31T16:00:00` (local time) ends a run cleanly at a wall
clock time. Past it the API stage starts no new video; the ones already in
flight finish and commit, then the local embed stage runs and the process
exits. Videos never started keep their `proxied` status and cost nothing, so
the next run picks them up.

Use this rather than killing the run. A kill wastes every call in flight — one
per `--api-workers`, so 24 of them at 24 workers — and `--max-hours` cannot do
the job: it is only checked *between* stage invocations, and the API stage
runs the whole queue in a single invocation.

## Session limits are expected, not errors

On a 429 it waits 15 minutes and resumes. The queue is left untouched — nothing
is marked failed and no work is repeated. Fully resumable: if the machine
reboots or you stop it, run the same command again and it picks up exactly
where it stopped.

## Check progress at any time

```powershell
python -c "import sqlite3;c=sqlite3.connect(r'file:E:/broll-queue/broll.db?mode=ro',uri=True);print(dict(c.execute('SELECT status, COUNT(1) FROM videos GROUP BY status').fetchall()))"
```

Or read the tail of `E:\broll-queue\claude.log` — the stage streams a line per
video now. It used to buffer everything until the stage exited, so a run that
stalled after its first hour was indistinguishable from a healthy one for the
next eight, and the database was the only way to tell them apart.

`indexed` is the count that matters. `skipped` (2,100) is the editor proxy
folders, deliberately excluded.

## Measure the result in the morning

```powershell
cd E:\Projects\broll-platform
.\web\.venv\Scripts\python.exe eval\run_eval_api.py E:\broll-queue\broll.db --queries eval\queries_archive.yaml
```

Before indexing this scored **recall 19/20, guards 4/5**, with the one miss
being `aerial drone shot of coastline` — a purely visual query. That miss
turning into a hit is the clearest measure of what the run added.

## If Windows reboots mid-run

Active hours are 9am–1am, so updates can restart the machine between 1am and
9am — exactly when this runs. Nothing is lost (progress is committed per
video), but the run stops. Either pause updates for a week
(Settings → Windows Update → Pause updates), or just re-run the command.

## Search while it runs

`http://127.0.0.1:8420/` already serves the archive. Speech search works now
(English, Chinese in both scripts, and cross-lingual). The visual layer fills
in as the run progresses.
