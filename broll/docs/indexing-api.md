# Indexing against the Anthropic API — keys, cost, and knobs

*Written 2026-08-17 for COMMERCIAL_READINESS.md item 1. Updated 2026-08-18:
this is now the **optional** `indexer.backend: anthropic` path — a new
install defaults to `indexer.backend: local` (Qwen3-VL via a vendored
llama.cpp, zero marginal cost, needs a GPU — see `broll/docs/indexing-local.md`
and `broll/docs/local-indexing-options-2026-08-17.md`). Choose `anthropic`
per site for a studio that wants the better first impression this document
describes, or has no GPU to spare for indexing. An existing config.yaml that
already has an `anthropic:` section keeps using it unchanged either way.*

The `describe` stage (dispatched by `pipeline.stage_describe`; this document
covers only the `anthropic` branch of it — `indexing-local.md` covers `local`)
is the only part of the indexer that costs money, and only on this backend.
Until 2026-08-17 it shelled out to the `claude -p` CLI signed in to one
person's Claude Code subscription. That could not ship to a customer: it needs
a claude.ai login on the indexing machine, its session limits are per-person
rather than per-org, and the Consumer Terms do not cover reselling it. The
stage now calls the Messages API through the official `anthropic` SDK with
the customer's own key.

Nothing else about the stage changed: same prompt, same JSON contract, same
per-window merge, same `usage.jsonl`, same "an account-wide failure stops the run
and leaves the queue resumable" behaviour.

## Giving the indexer a key

The key is **never** written into `config.yaml`. That file is copied between
machines, pasted into support threads, and committed to this repo; a key in it is
a key that leaks. The loader rejects `anthropic.api_key` outright.

Two supported ways, in the order the client checks them:

1. **Environment variable** (default `ANTHROPIC_API_KEY`; rename it with
   `anthropic.api_key_env`).
2. **Keyfile** — `anthropic.api_key_file: "C:/ProgramData/ccsync/anthropic.key"`.
   First non-blank, non-`#` line is the key, so the file can be annotated with
   who issued it and when it was rotated.

With neither, the run stops before its first call with
`authentication_error: no Anthropic API key…`. That is deliberate: a missing key
fails every video identically, so it must stop once rather than mark thousands of
clips `error`. `broll-index run` and `parallel_claude.py` both print the resolved
source in their banner (`auth: Anthropic API key from $ANTHROPIC_API_KEY …`).

## Model and price

`model:` in config (and `--model`) takes a short alias or an exact API model id;
an unrecognised value is passed through so a config can pin one the alias table
has not caught up with.

| Alias    | Model id             | USD / Mtok in | USD / Mtok out |
|----------|----------------------|---------------|----------------|
| `haiku`  | `claude-haiku-4-5`   | 1.00          | 5.00           |
| `sonnet` | `claude-sonnet-5`    | 3.00          | 15.00          |
| `opus`   | `claude-opus-5`      | 5.00          | 25.00          |
| `fable`  | `claude-fable-5`     | 10.00         | 50.00          |

The archive to date was indexed on `haiku`, which was judged good enough for
this job on the first real corpus (see `indexing-findings.md` — synonym
expansion works, segment boundaries track real cuts, quality flags are
plausible). `sonnet` is the default for a new install because a customer's first
impression of search quality is worth more than the difference in unit price;
drop to `haiku` for a bulk backfill.

## How many calls a clip costs

The arithmetic, all of it visible in `broll_index/pipeline.py`'s `stage_describe` (the anthropic branch):

```
frames        = scene cuts, plus filler so no gap exceeds sampling.max_gap_s
sheets        = ceil(frames / 9)                    # 3x3 contact sheets
sheets        = cap_sheets(sheets, max_sheets_per_video)
calls         = ceil(sheets / (frames_per_call / 9))   # default 4 sheets/call
```

So with the defaults (`frames_per_call: 36`) **one call covers 4 sheets = 36
frames**, and the measured average across the real archive is **~2 calls per
clip** — one for a short cutaway, many for a long clip with lots of cuts. The
long tail is what hurts: 9% of videos consumed 36% of all calls before
`max_sheets_per_video` existed. Each call re-pays both its image cost and its
per-segment output cost, so capping the sheets on long clips is the single
biggest lever on total spend.

Per call, roughly:

- **input** — the prompt template (~3k tokens) plus the images. A contact sheet
  is billed at about `width x height / 750` tokens, so 4 sheets dominate.
- **output** — the JSON contract, ~500–2,000 tokens depending on how many
  segments the window yields.

`usage.jsonl` in `data_root` records the real token counts for every call, plus
an **estimated** `total_cost_usd` computed locally from the table above (the API
returns tokens, not dollars). That file is how a full-archive run is forecast
before it is started:

```powershell
python - <<'PY'
import json, pathlib
rows = [json.loads(l) for l in pathlib.Path("E:/broll-queue/usage.jsonl").read_text().splitlines()]
print(len(rows), "calls", round(sum(r.get("total_cost_usd", 0) for r in rows), 2), "USD est")
PY
```

## Config knobs (`anthropic:` in config.yaml)

| Key | Default | What it changes |
|---|---|---|
| `api_key_env` | `ANTHROPIC_API_KEY` | Which environment variable holds the key |
| `api_key_file` | *(unset)* | File to read the key from when the env var is absent |
| `max_tokens` | `8000` | Output ceiling per call. Too low truncates the JSON (logged, then the one retry); too high is free — you are billed for what is produced |
| `timeout_s` | `600` | Per-request timeout |
| `max_retries` | `5` | Retries per call, on 429 / 5xx / overloaded only |
| `retry_base_delay_s` | `2` | Exponential backoff base, jittered, overridden by the server's `retry-after` |
| `retry_max_delay_s` | `60` | Backoff ceiling |
| `max_concurrency` | `4` | API calls in flight, enforced inside the client |
| `thinking` | `disabled` | `adaptive` buys reasoning tokens on **every** call. Describing a contact sheet is extraction, not reasoning — leave it off unless an archive's descriptions justify paying for it across tens of thousands of calls |

`sampling.max_sheets_per_video` and `sampling.frames_per_call` are the other two
cost knobs and live in their own section; see `config.example.yaml`.

## Concurrency and rate limits

The stage is latency-bound, not usage-bound: measured at ~84 s per call, serial,
it managed 20 videos/hour — over 100 h for a 2,000-clip queue — while the machine
sat idle. `parallel_claude.py --workers N` runs N clips at once (a thread pool
since 2026-08-17; the SDK client is thread-safe and pools connections) and sets
the client's own in-flight ceiling to the same N, so a wider fan-out cannot put
more requests on the wire than the account can serve.

Raising `--workers` cannot raise the organisation's rate limit, only reach it
sooner. Past that the run goes bursty — index, wait out the limit, resume — and
the limit sets the pace. That is expected, not an error:

- **429 / 529 / 5xx** are retried per call with jittered backoff, honouring the
  server's `retry-after`. Past `max_retries` the failure is reported as
  account-wide, `parallel_claude.py` cancels the queued work, and every clip
  keeps its `proxied` status so the next run picks it up exactly where it
  stopped. `run_queue.py` waits out the reset and resumes on its own.
- **401 / 403 / credit exhausted** are not retried — they will not fix
  themselves — and stop the run the same way, with the queue intact.
- **A refusal, or unparseable JSON**, is that clip's problem: one retry, then the
  clip is marked `error` and the queue carries on.

## Operator TODO for a customer install

1. Issue an API key for the customer's own Anthropic organisation.
2. Put it in the environment (`ANTHROPIC_API_KEY`) or in a keyfile referenced by
   `anthropic.api_key_file`, readable only by the indexing account.
3. Set a spend limit on that key in the Anthropic Console, and forecast the
   archive from `usage.jsonl` on a sample share before starting a full run.
