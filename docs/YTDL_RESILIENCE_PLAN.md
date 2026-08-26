# YouTube downloading: resilience plan

**Status: NOTHING IN THIS DOCUMENT IS BUILT.** It is the write-up of the
projected change after CR-80 (2026-08-26), plus the other ways the YouTube
downloader can be made harder to break. The CR-80 incident itself, and the
live fix applied to the NAS that day, are in `KNOWN_BUGS.md`; the deployment
facts are in `ytdl/web/DEPLOY.md`. This document is about what to do next.

Read `docs/YTDL_LOCAL_DOWNLOAD.md` first if you have not: the requester-first
design (an editor's own machine downloads, the NAS is the fallback) is assumed
throughout.

---

## 1. What CR-80 actually taught us

On 2026-08-26 every server-side download failed with
`ERROR: [youtube] <id>: The page needs to be reloaded.` Two independent things
had gone wrong, and either one alone still breaks downloading:

1. **YouTube flagged the signed-in account** whose `cookies.txt` the NAS uses.
   Not expired - the cookies still authenticated fine (the subscriptions feed
   listed normally). YouTube downgrades the `tv` client
   (`tv_downgraded ... playability status: UNPLAYABLE`) and SABR-forces
   `web_safari`'s https formats away, so **every** `player_client` comes back
   with storyboards and no media. Measured against seven clients.
2. **yt-dlp 2026.07.04 had no anonymous path left.** Without cookies the only
   client still producing URLs was `android_vr`, and its media fetch 403'd.
   2026.8.19 adds the `visionos` client, which still gets real https URLs.

| yt-dlp | cookies | result |
|---|---|---|
| 2026.07.04 | yes | "The page needs to be reloaded." |
| 2026.07.04 | no | formats found, then HTTP 403 |
| 2026.8.19 | yes | "The page needs to be reloaded." |
| **2026.8.19** | **no** | **1080p, ~20 MiB/s** |

Three lessons, and they are what the rest of this plan is built on:

- **Cookies are not a safety net, they are a second failure mode.** The
  2026-08-11 measurement that made them mandatory has inverted. A signed-in
  session is one more thing that can be revoked, silently, mid-job.
- **A pinned `player_client` is a pinned bug waiting to happen.** CR-39 pinned
  `web_safari` because it was the one that worked in August. It is dead now.
- **Health that reports configuration is not health.** `/ytdl/api/health`
  returned `cookies: true` throughout, which means "a path is set", not "the
  session works". It was green while nothing could download.

## 2. The unreported half: the editors' machines are broken the same way

Found while writing this doc, on the base rig, against the deployed companion's
own yt-dlp (`%LOCALAPPDATA%\ccsync\tools\yt-dlp.exe`, **2026.07.04**) and its
own cookie jar (`~/.ccsync/youtube-cookies.txt`):

| companion config | result |
|---|---|
| `web_safari` (its pinned default), anonymous | no usable formats |
| `web_safari`, with its cookies | no usable formats |
| default client, with its cookies | "The page needs to be reloaded." |
| default client, anonymous | formats found, then **HTTP 403** |
| **2026.8.19, default client, anonymous** | **works** |

So the local downloader is dead in every combination it can currently be in,
on a residential IP, and has been since roughly the same time as the server.
`YTDL_LOCAL_DOWNLOAD=1` is on fleet-wide, so a job an editor's machine claims
fails; job 28 only reached the NAS because its `download_mode` was `server`.

**Two things kept this invisible:**

- `ytdlp_manager` self-updates the companion's yt-dlp only when it is below
  `YTDL_MIN_YTDLP_VERSION`, which the dashboard serves from
  `config.DEFAULT_MIN_YTDLP_VERSION = '2026.07.04'` and which is **not set** in
  the live container's environment. So every companion in the fleet looks at
  2026.07.04, concludes "current", and stays on the one version that cannot
  download. The base rig's log says exactly that, nightly:
  `ytdlp: yt-dlp 2026.07.04 is current`.
- `ytdl_cookies.STALE_SIGNATURES` - the companion's cookie-health classifier -
  does not contain "the page needs to be reloaded", so a flagged session never
  gets marked stale and the tray never says anything.

**This is the most urgent item in this document and it is not covered by the
NAS fix.** WP1 and WP2 below are what close it.

## 3. The failure surface, as it stands

Where a YouTube download can fail, and what the system currently does about it:

| failure | detected? | what the editor sees |
|---|---|---|
| IP bot-checked ("not a bot") | **yes** - `worker._bot_checked`, fails the phase fast with an actionable note | a message naming the fix |
| account flagged ("page needs to be reloaded") | **no** | N identical opaque per-clip errors |
| SABR squeeze on the pinned client | **no** | "Requested format is not available" per clip |
| GVS 403 on the media fetch | **no** | "HTTP Error 403" per clip |
| yt-dlp too old to work at all | **no** | whichever of the above lands |
| PO-token sidecar unreachable | partially - CR-73 hardened the install, but a boot failure is only a log line | slow or empty downloads |
| stream truncated | **yes** - one rung down is retried (`_download_video`) | a downgrade note on the row |
| no JS runtime | **yes** - `/api/health` `js_runtime` | health pip |

The pattern is clear: the *one* failure mode anyone thought to classify
(`_bot_checked`) is handled well - fail the phase immediately, say what the
admin must do. Every newer failure mode falls through to "burn the retry
budget, record an opaque string on 29 rows, end `done` with 29 failures". The
work below is mostly about extending the treatment `_bot_checked` already
gets to the failures YouTube has invented since.

---

## 4. The projected change

Ordered by value-per-effort. WP1-WP3 are the ones I would do; WP4-WP7 are
worth doing and can wait; WP8 is deliberately listed as *not* recommended.

### WP1 - stop shipping a dead yt-dlp (both halves)

The single highest-value change, and the only one that fixes the fleet today.

- Raise `config.DEFAULT_MIN_YTDLP_VERSION` to `2026.8.19` so every companion
  self-updates on its next check. (Already done in the repo for the *server's*
  own copy: the floors in `ytdl/web/pyproject.toml` and
  `dashboard/pyproject.toml` and both `requirements.lock` files. The companion
  floor is a different knob and is **not** done.)
- Set `YTDL_MIN_YTDLP_VERSION` in the live container so the fleet moves before
  the next dashboard build, rather than after it.
- Add the running yt-dlp version to `/ytdl/api/health` (`_yt_dlp_state()`
  currently answers only `ok`/`missing` from an import), and show it in the
  admin view. "Which yt-dlp is the server on" took a `docker exec` to answer
  during CR-80.
- **Residual worth writing down**: `/venv` belongs to the image, so a dashboard
  image update reinstalls whatever the lock says. The lock is the durable fix;
  the live `pip install` is not.

### WP2 - unpin `player_client`, on both executors

`ytdl_executor.DEFAULT_PLAYER_CLIENT = "web_safari"` was correct in August and
is a guaranteed failure now. yt-dlp's own default client list is maintained by
people who track this weekly; we are not going to beat them from here, and
every time we pin we inherit the job of keeping the pin current.

- Drop the pin and let yt-dlp choose, keeping the setting as an *override* for
  when a specific client is known-good and the default is not.
- The vendored server downloader (`ytdl/web/ytdlweb/vendor/downloader.py`)
  never pinned one - it already relies on the default. Keep it that way.
- Note the constraint this creates: the two executors must agree on quality
  (`ytdl_common`), so a client difference that changes the format ladder shows
  up as one clip at 1080p on the NAS and 720p on a laptop. That is the
  2026-08-13 incident's shape and is why the pin existed at all. The answer is
  the shared quality rule, which is already there, not a shared client pin.

### WP3 - anonymous first, cookies as the fallback (the inversion)

Today the cookie jar is unconditional: `worker._download_video` passes
`cookies_file=config.COOKIES_FILE or None` on every call. That is what made a
flagged account fatal to everything.

Invert it:

1. Try the download **anonymously**.
2. Only if that comes back with a bot check (`worker._bot_checked`, which
   already exists and is already the right classifier) retry **once** with the
   cookie jar.
3. Record which path produced the file, and surface it.

This restores cookies to the escape hatch `DEPLOY.md` originally described,
gets the system through both of the last two incidents unaided (2026-08-11 the
fallback fires and saves you; 2026-08-26 the fallback never fires and you never
notice), and needs no accounts at all in the normal case.

Same change on the companion side, where `_cookies_file(self.deps.cfg)` is
likewise unconditional.

**Cost to be honest about**: one extra failed extraction per clip on a
genuinely bot-checked IP, before the fallback fires. Cheap - extraction is a
few seconds and the bot check is phase-fatal today anyway.

### WP4 - classify the failures YouTube has invented since

Extend the two classifiers that already exist rather than inventing a third
mechanism.

- Add "the page needs to be reloaded" to a new **account-flagged** class,
  distinct from the bot check: the bot check says *this IP needs an account*,
  the flag says *this account is refused*. They have opposite remedies, so they
  must not share a message.
  - Server: a sibling of `BotCheckError` that fails the phase fast with a note
    saying the signed-in session is being refused and downloads are continuing
    anonymously (or, if anonymous is also dead, that both paths are blocked).
  - Companion: add the phrase to `ytdl_cookies.STALE_SIGNATURES` so the
    existing `mark_stale` / tray-status machinery lights up. This is a
    one-line change with a test and it should go in regardless of the rest.
- Add a **SABR / no-usable-formats** class for "Requested format is not
  available" arriving on *every* clip in a row. One clip is an oddity; five in
  a row is a client that no longer works, and the message should say to check
  for a yt-dlp update rather than blaming the videos.
- Adopt the rule `_bot_checked` established: **a failure that will repeat
  identically for every remaining clip must stop the phase, not the clip.** 29
  rows each burning `retries: 10` is 29 chances to make YouTube angrier, for
  no information.

### WP5 - make health mean something

`cookies: bool(config.COOKIES_FILE)` is a configuration echo. Replace the
whole pip with an *evidence* model, cheap enough to hit on every page load:

- Cache the outcome of the last real download attempt per path (anonymous /
  cookies), the way `claude_cli.health()` already caches its verdict instead of
  probing per request. The pattern and the reasoning are already in the health
  endpoint's docstring; reuse them.
- Report `yt_dlp_version`, `pot_provider` (whether bgutil actually answered,
  not whether a URL is configured - CR-73 sat undetected for days behind a
  configured-but-unreachable sidecar), and `last_download` with its verdict.
- An optional **canary**: one tiny public clip, extracted (not downloaded) on a
  schedule, recording which path worked. That is the check that would have
  caught both CR-73 and CR-80 before an editor did. Keep it cheap and keep it
  off the request path.

### WP6 - do not let one job discover the same wall 29 times

- **Circuit-break the download phase** on a repeated identical failure, the way
  `sync/lane_guard.py` breaks lane B: after N consecutive failures with the
  same signature, park the job with a reason a human can act on rather than
  grinding through the rest. Lane B's rule that a latch must be on disk and
  cleared by a person, never in-memory, applies here too.
- **Preserve the retry**: the CR-80 recovery was one `POST
  /ytdl/api/jobs/28/download`, which re-queued exactly the 29 failed rows
  (YTDL-16's "`done` is accepted as well as `ready_for_review`"). That is a
  genuinely good piece of design and it is what made the recovery a one-liner.
  Anything added here must keep it working.
- Consider a **retry button in the UI** for a finished job with failures. The
  endpoint exists and behaves; today the only way to reach it on a `done` job
  is the download button, which is not obviously a retry.

### WP7 - operational hygiene

- **Pin the PO-token sidecar's reachability into health** (folded into WP5) and
  keep run.sh's retry ladder from CR-73.
- **Document the two-way test as the first diagnostic.** Every future
  "downloads are failing" starts with: run the same clip in the container with
  and without `--cookies`, on the current yt-dlp and on the latest. Which one
  works has flipped once and will flip again. This is in `DEPLOY.md`'s
  reversal block now; it belongs in the runbook too.
- **Stop treating the cookie jar as durable state.** yt-dlp rewrites
  `cookies.txt` in place on every run, so the operator's export is overwritten
  by whatever the session became. Keep the pristine export beside it
  (`cookies.txt.orig`) so restoring is a copy, not a re-export.

### WP8 - a pool of accounts to rotate through: NOT recommended

Raised by the owner on 2026-08-26 and worth recording with its reasoning,
because it is the intuitive answer and it is the wrong shape here.

- **It optimises the wrong path.** The system worked *better* with no account
  at all. A pool adds more of the thing that failed, to protect a path we did
  not need.
- **Every account is a consumable, not a fixture.** Bulk automated downloading
  through a signed-in account is exactly what Google flags; a pool is a supply
  of accounts to burn through, each needing creation, warming, and a cookie
  re-export when it expires.
- **Every jar is a live credential** sitting in the data directory. One is
  already a thing we handle carefully; ten is a credential-management problem
  in a product we ship to customers.
- **It makes the legal position worse.** `COMMERCIAL_READINESS.md` item 2
  already has the anti-anti-automation posture parked for legal review.
  "The product farms Google accounts" is materially harder to defend than
  "the product supports an optional operator-supplied cookie file".
- **Auto-rotation cannot be done reliably.** Deciding "this account is
  flagged" is guesswork, and guessing wrong burns the spare on the same job
  that burned the first.

If a second jar is genuinely wanted, the honest version is a **manual** second
slot (`YTDL_COOKIES_FILE_ALT`) an admin points at a spare export and switches
to deliberately - not a rotation the system manages on its own.

---

## 5. Suggested order

1. **WP1 + the one-line WP4 companion signature.** Fixes the live fleet
   outage in section 2. Small, and nothing else works until yt-dlp is current.
2. **WP2.** Removes the pin that will otherwise break again on YouTube's next
   client squeeze.
3. **WP3.** The structural fix: cookies stop being able to take everything
   down.
4. **WP4 proper, then WP5.** Turn silent walls into messages, then into a
   health signal that would have caught them first.
5. **WP6, WP7.** Containment and runbook.

WP1-WP3 are each small and independently shippable. Note the ordering
constraint the fleet always has: **the dashboard deploys before the
companions**, and a companion change reaches editors only through a published
build.

## 6. Verification recipe

Whatever is built, this is the test that decides whether it works. Run it in
the live container and on one editor machine, against the same clip:

```sh
# in the dashboard container
for CK in "" "--cookies /ytdl-data/cookies.txt"; do
  /venv/bin/python -m yt_dlp --simulate --no-warnings $CK \
    --extractor-args "youtubepot-bgutilhttp:base_url=$YTDL_POT_BASE_URL" \
    -f "bv*[height<=1080]+ba/b[height<=1080]" \
    -O "%(format_id)s h=%(height)s" "https://www.youtube.com/watch?v=<id>"
done
```

A simulate is not enough on its own - CR-80's anonymous path *extracted*
happily on 2026.07.04 and then 403'd on the bytes. Always finish with one real
download, and prefer the production path
(`ytdlweb.vendor.downloader.download(..., ffmpeg_location=config.FFMPEG_DIR)`)
over a hand-built argv, which is how the CR-80 fix was confirmed.

## 7. Open decisions for the owner

- **WP8**: is the account pool dropped on the reasoning above, or do you want
  the manual second-slot version?
- **WP5's canary**: a scheduled extraction of one public clip is the difference
  between finding this yourself and an editor finding it. It is a small, real
  amount of automated traffic to YouTube on a fixed cadence. Worth it?
- **WP3's default**: after the inversion, should the NAS keep a cookie jar
  configured at all, or should the vendor default be "no jar, and an admin adds
  one if their IP ever gets challenged"? The latter is cleaner for customers
  and means one less credential in a deployment nobody is watching.
