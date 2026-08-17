# Deploying `web/`

The b-roll UI is served **from inside the cc_sync dashboard**, mounted in-process
at `/broll`. Editors reach it on the same host, port and login as everything
else — there is no second service to find or sign in to.

The standalone container described further down still works and is the dev loop,
but it is **not** how this is deployed. Do not run it on the NAS alongside the
mount: it would be an unauthenticated twin of the same database.

## How the mount works

`dashboard/src/ccsync_dashboard/broll.py` imports `app.main:app` and mounts it.
Three things make that safe and are easy to break:

- **Auth comes from the dashboard.** Starlette middleware wraps mounted apps, so
  `login_gate` already covers `/broll/*`. The b-roll app must never grow auth of
  its own. `/broll/api/*` and `/broll/media/*` answer **401 JSON** rather than a
  303 to the login page, because `fetch()` and `<video>` cannot follow an HTML
  redirect.
- **The sub-app's lifespan does NOT run.** Starlette only runs the outermost
  app's. `broll._init_storage()` replicates it (data dirs + `ensure_schema`);
  without it the first request hits a database that was never created.
- **`BROLL_INGEST_TOKEN` is mandatory.** Unset, the three `/api/ingest/*`
  endpoints answer **503** and log why — there is no "dev mode" open branch any
  more (deleted 2026-08-17, COMMERCIAL_READINESS.md item 15; it was an
  unauthenticated write path on the fleet's origin the moment anything
  proxied or mounted this app). The dashboard additionally refuses to open its
  ingest carve-out without the token. Set it on the server *and* in the
  indexer config, or nothing can push.

## Deploying it

Everything is in `dashboard/deploy/compose.yaml` and the matching block in
`server/install_dashboard_app.py` — **keep those two in step**, they describe the
same container and drift only ever shows up in production.

| | |
|---|---|
| `/broll-app` | the `web/` tree, read-only, on `PYTHONPATH` via `run.sh` |
| `/broll-data` | `BROLL_DATA_ROOT`: `broll.db`, `proxies/`, `posters/`, `sprites/`, `sheets/` |
| `DASH_BROLL_ENABLED` | `1` to mount; anything else and the volumes are unused |
| `BROLL_CREATORS_SHARES` | shares holding our own footage (browse under `Creators_Club`) |

`numpy` and `rapidfuzz` are in `deploy/requirements.txt`. **`fastembed` is not**:
it is optional (`app/semantic.py` degrades to keyword-only) and downloads a
~100 MB model from Hugging Face on first use — a container-egress decision to
make deliberately.

Worth knowing for later: if B-roll insert delivery is built, put `/broll-data`
and the `Projects` tree on **one ZFS dataset**. ZFS cannot hardlink across
datasets even within a pool, so a split forces a full copy per delivered clip.

The indexer pushes to `http://<nas>:8480/broll/api` with `X-Ingest-Token`.

---

# Standalone container (dev / LAN escape hatch)

Not the deployment. Kept because it is the dev loop and a fallback.

## Build

From the `web/` directory (this is the Docker build context):

```
docker build -t broll-web .
```

The image only bakes in `web/`'s own copies of `schema.sql` and
`migrations/` (`web/schema.sql`, `web/migrations/`, kept in sync with the
repo-root copies, the single source of truth -- see `app/db.py` for the
resolution order and the loud failure if both a schema/migration and its
bundled fallback are missing). It does not need the rest of the repo.

## Run

```
docker run -d \
  --name broll-web \
  -p 8420:8420 \
  -v /volume1/broll-data:/data \
  -e BROLL_SHARES="broll:Main b-roll archive" \
  -e BROLL_INGEST_TOKEN="<shared secret, matches indexer config>" \
  broll-web
```

- `-v /volume1/broll-data:/data` -- mount the TrueNAS dataset holding
  `broll.db`, `proxies/`, `sprites/`, `posters/`, `sheets/` at `DATA_ROOT`
  (container env `BROLL_DATA_ROOT` defaults to `/data`, matching this mount).
- `BROLL_SHARES` -- semicolon-separated `share:description` pairs, drives
  `/api/shares` (used by the frontend's Settings panel). Purely descriptive;
  actual share->local-path mounting happens in the indexer/companion
  configs, not here.
- `BROLL_INGEST_TOKEN` -- the three `/api/ingest/*` endpoints require a
  matching `X-Ingest-Token` header (used by a remote indexer). REQUIRED: unset,
  those endpoints answer 503, including for a co-located indexer and including
  in a bare dev checkout. Generate one with `openssl rand -hex 24`.
- Port `8420` is the app's fixed port (see `Dockerfile`/`CMD`).

On first start, the container applies `schema.sql` to `/data/broll.db`
(`PRAGMA user_version` 0 -> current) and creates the `proxies/`, `sprites/`,
`posters/`, `sheets/` subdirectories if missing. An existing database is
stepped forward through every migration between its version and current
(v1 -> v2 -> v3 -> v4) in one startup, each in its own transaction.
Subsequent restarts are a no-op migration check; a database newer than this
image's schema version fails loudly at startup instead of running against
it.

## Semantic search (optional)

`numpy`/`rapidfuzz` (semantic matrix math, fuzzy typo correction) are
regular dependencies and always installed. `fastembed` (the ONNX embedding
encoder used to turn a query into a vector) is an optional extra --
`app/semantic.py` degrades to keyword-only search if it isn't installed or
no `embeddings` rows exist yet, so it is not required for the app to run.
To enable it, install the `semantic` extra (`pip install -e .[semantic]`
instead of `pip install -e .` in the Dockerfile) -- note the first semantic
query then downloads the embedding model from Hugging Face (~100 MB),
so the container needs outbound internet access at least once.

## Tailscale

Per SPEC.md, v1 has no auth (Tailscale-only deployment) -- do not expose
port 8420 to the public internet. Bind it to the Tailscale interface / rely
on TrueNAS + Tailscale ACLs for access control.

## Reverse proxy note

If fronting with a reverse proxy later, make sure it passes `Range` request
headers through unmodified and doesn't buffer the whole response body --
`/media/proxy/{id}.mp4` depends on real 206 Partial Content passthrough for
in-browser seeking.
