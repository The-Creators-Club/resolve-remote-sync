# MOBILE.md -- the dashboard on a phone

Who this is for: the admin who sets it up, and the editor who uses it. The
plan and the reasoning behind every choice here are in `MOBILE_PLAN.md`; this
page is what to do.

The dashboard is one app. The phone gets the same pages the desktop gets,
laid out for a thumb, plus a web app manifest and a service worker so a phone
can install it as an icon, plus an optional Android APK (`docs/ANDROID.md`)
for studios that want a real app rather than a home-screen shortcut. There is
no separate mobile site and no separate URL: whatever an editor browses on a
laptop is what they browse on a phone.

Everything on this page has shipped. Where a detail is worth checking in the
code, the file is named.

---

## 1. Before anything: the origin must be https

A phone will not install a web app from `http://`, and the refusals are all
silent:

* `navigator.serviceWorker` does not exist on a plain-http origin, so the
  offline page and the caching never register at all.
* Chrome never shows "Add to Home screen" as an app install (it offers a
  plain bookmark instead, which opens in a browser tab with the address bar).
* A Trusted Web Activity refuses to verify, and the Android app opens with a
  URL bar across the top forever.

Nothing logs any of this. That is why `tools/check_mobile_origin.py` exists
(§6).

### The studio recipe (TrueNAS, today)

The NAS already terminates TLS inside its `tailscale` app container for the
Timeline Cards page (`https://truenas.tail26290e.ts.net/` -> :8800). The
dashboard is one more `serve` line in the same container. `:443` is taken by
that page and `:8443` by an unrelated Funnel, so the dashboard takes `:9443`:

```bash
sudo docker exec tailscale tailscale serve --bg --https=9443 http://192.168.0.102:8480
sudo docker exec tailscale tailscale serve status
```

The dashboard's origin is now `https://truenas.tail26290e.ts.net:9443/`.
Then, in `site.toml`:

```toml
[net]
dashboard_url = "https://truenas.tail26290e.ts.net:9443"
```

and redeploy (`python server/install_dashboard_app.py --mode bind`). The same
recipe, with the cookie-flag caveat spelled out, is in `docs/DOCKER.md`
("Serving the dashboard over https").

**Restart every companion after that change.** Each companion builds its
loopback CORS allow-list from `dashboard_url`
(`docs/COMMERCIAL_READINESS.md` item 156): until it is restarted with the new
value, Send-to-Resolve from the new origin is refused with a 403 and nothing
on the page says why. `loopback_extra_origins` is the per-machine escape
hatch for an editor who has to keep using both URLs for a while.

**Check the cookie flag.** `DASH_COOKIE_SECURE` defaults to `auto`: the
`Secure` attribute goes on the session cookie when the request looks https to
the app. Behind Serve the request the container receives is plain http with
`X-Forwarded-Proto: https` on it, and that header is believed **only from a
peer listed in `DASH_TRUSTED_PROXIES`** (default: loopback alone; the
TrueNAS deploy path builds `127.0.0.1,::1,172.16.0.0/12,<bind_tailnet>` for
you, which normally already covers a container-side Serve). If the
dashboard's log carries

```
X-Forwarded-For from <address>, which is not in DASH_TRUSTED_PROXIES (...)
```

then that address is the terminator, the flag is going out off, and it
belongs in `[net] trusted_proxies` beside the existing entries. Do not widen
the range to the whole studio LAN.

### The product switch (the appliance)

On the appliance stack (`dashboard/deploy/compose.appliance.yaml`) the same
answer is a file rather than a command:
`dashboard/deploy/tailscale/serve.json` says TLS on 443 proxying to
`http://dashboard:8480`, mounted read-only at `/config` in the `tailscale`
service. It is **off by default**: `TS_SERVE_CONFIG` comes from
`DASH_TAILSCALE_SERVE`, which is empty unless somebody sets it to
`/config/serve.json` (the switch carries the path and not a `1` because the
oldest compose this file targets has no `${VAR:+alternative}` form). Read
that service's comments before turning it on -- the appliance's `tailscale`
runs bare `tailscaled` rather than containerboot on purpose, and the
long-term shape is the dashboard POSTing that same JSON to
`/localapi/v0/serve-config` once the node is signed in
(`ZERO_TOUCH_PLAN.md` WP B).

---

## 2. What works in a phone browser

Open the dashboard's URL in Chrome (Android) or Safari (iOS) and sign in.
Everything is the same product: the console look, the `[ CHIP ]` idiom, the
same numbers.

* Below 600 px wide the pages lay themselves out for a thumb: one column,
  records that were table rows become labelled cards, and the page itself
  does not scroll sideways.
* Tables that would lose their meaning stacked scroll sideways **inside their
  own box** instead -- the fleet grid and the assignments matrix are the two
  that do this. The page under them stays put.
* Controls are at least 44 px on a touch screen. That is keyed to the pointer,
  not to the width, so a touch laptop gets the bigger hit boxes and a narrow
  desktop window does not: at a mouse the pages are what they were.
* The navigation drawer opens full height with the `[ X ]` where a thumb is.
  The projects sidebar becomes a `[ PROJECTS ]` handle pinned to the bottom of
  the screen; tapping it slides the tree up over the page. The settings strip
  scrolls sideways with the current page already in view.
* Text inputs are 16 px on a phone, because anything smaller makes both
  Android and iOS zoom the page in when the keyboard opens.
* The three side apps -- `/broll`, `/music`, `/ytdl` -- work but are not laid
  out for a phone yet. They are their own round (`MOBILE_PLAN.md` §7).
* The Timeline Cards page is a separate thing with its own phone layout and
  its own installable icon. Installing the dashboard does not change it, and
  the dashboard's service worker never touches `/cards/`.

## 3. Installing it

### Android, Chrome

1. Open the dashboard and sign in.
2. `⋮` -> **Add to Home screen** (it may say **Install app**). When Chrome
   decides the site is installable it also lights an `[ INSTALL ]` chip at
   the foot of the navigation drawer, which does the same thing.
3. Confirm. The icon lands on the home screen; opening it gives the
   dashboard with no browser chrome, in its own task.

The icon's label is the site's own product name -- the same one in the header
you signed in under -- so a studio that has renamed the product gets that
name on the phone.

If Chrome offers a plain shortcut instead of an install, and no `[ INSTALL ]`
chip appears, the origin is not https or the manifest is not being served:
run the checker (§6).

The Timeline Cards page (`/cards/`) is a second installable app with its own
manifest, `/cards/manifest.webmanifest`, and its own icon, `/cards/icon.svg`
(scope `.`, so the installed app owns `/cards/` only). Both are open at the
dashboard's login gate on purpose (CR-100, 2026-09-02): a browser fetches a
manifest without the session cookie, and behind the gate Chrome's Install
made a home-screen shortcut that opened with the URL bar. The checker in §6
does not cover that manifest; the test is Install from `/cards/` itself.

### iOS, Safari

1. Open the dashboard and sign in.
2. Share -> **Add to Home Screen** -> **Add**.
3. The icon opens the dashboard full screen with the status bar kept.

iOS has no install prompt, so there is no `[ INSTALL ]` chip there and the
Share sheet is the whole mechanism. Everything else works the same, except
that Safari evicts an unused site's storage after a few weeks, which for this
app means the offline page and the cached styles are fetched again. Nothing
else is stored on the phone anyway.

### The Android app

A studio that wants a signed APK its editors install (own icon, no browser
chrome, no "add to home screen" instructions) builds a Trusted Web Activity
around this same install. `docs/ANDROID.md` is the whole path: build it on CI
(`gh workflow run android.yml -f origin=<the https origin>`, which signs with
a throwaway debug key unless the release signing secrets are set, and says
which it did), then paste the package name and the SHA-256 fingerprint it
printed into **Settings -> ANDROID** and press `[ CHECK ]`. That is what
publishes the statement at `/.well-known/assetlinks.json` that Chrome fetches
from the phone.

The one symptom to recognise: **an app that opens with a URL bar has failed
asset-link verification**. It is nearly always the fingerprint or the origin
rather than the build, and `docs/ANDROID.md` opens with the four causes.

## 4. What polls, and when

The dashboard is a status board: pages refresh themselves rather than making
anyone pull down. On a phone that is a battery and a data question, so:

| what | on a desktop | on a phone or a tablet |
|---|---|---|
| live transfers (on `/` and `/transfers`) | 2 s | 10 s |
| project bins | 5 s | 15 s |
| the fleet grid, the jobs table | 15 s | 15 s |
| the projects sidebar | 30 s | 30 s |
| the fleet-halt banner | 60 s | 60 s |

The two fast ones are slowed for a coarse pointer rather than for a narrow
screen, so a tablet gets it too and a small desktop window does not.

**Nothing polls while the page is hidden.** Switch apps, lock the phone or
move to another tab and every poll stops, including a request already in
flight. Coming back refreshes each of them once, immediately, and then
resumes at the cadence above -- so the page an editor returns to is current,
and a phone in a pocket costs the server nothing.

## 5. Offline

The installed app is not an offline app, and pretending otherwise would be
worse than saying so. It shows the fleet's live state, which by definition
comes from the server.

* Pages come from the network first, always. The cache is never asked for one
  while there is a connection, so nothing on the phone can give a stale
  answer to "is anything red".
* When a page genuinely cannot be reached, the app paints **the dashboard's
  own offline page**: the product's look, one sentence, a `[ RETRY ]`,
  instead of the browser's dinosaur. It deliberately says nothing about the
  fleet -- it is a cached page, so anything it claimed would be old.
* Styles, scripts and icons do come from the cache, which is why that page
  appears instantly and why the app opens fast on a poor connection.
* Nothing else is stored, ever. Live data (`/api/`), the fragments that carry
  it (`/partials/`), the three side apps, Timeline Cards and both ends of a
  session (`/login`, `/logout`) are handed to the network untouched: a cached
  page from a signed-in session is a page the next person to pick up the
  phone should not see.
* Actions need the server, so nothing queues up while offline. Do them again
  when the bars come back.
* An update arrives by itself: every release changes the worker, the phone
  picks it up on the next launch, and the previous cache is deleted.

## 6. The checker

Run this from any machine that can reach the origin, after the TLS change and
before handing anyone a phone:

```
python tools/check_mobile_origin.py https://truenas.tail26290e.ts.net:9443
python tools/check_mobile_origin.py <url> --json      # for a script
```

Stdlib only, so it runs anywhere python does -- the NAS, a laptop, CI. Seven
lines, in the order a browser cares about, and it **stops at the first FAIL**
because everything after the first failure is a consequence of it. Exit code
1 if anything failed.

| line | what a FAIL means |
|---|---|
| `https` | the URL is not https. Nothing else can work. §1. |
| `certificate` | the TLS handshake was refused, or nothing answered. A phone shows an interstitial here and a TWA will not open at all. |
| `manifest` | `/manifest.webmanifest` is not reachable **signed out**, is not JSON, or has no `start_url`/`icons`. "not JSON" almost always means it redirected to the login page. |
| `service worker` | `/sw.js` is missing its `Service-Worker-Allowed` header, so it cannot control the whole site. |
| `asset links` | `/.well-known/assetlinks.json` is unreachable. An Android app from this origin would open with a URL bar. An **empty** statement list is fine: it means no Android package is configured yet. |
| `health` | `/api/v1/health` has no `version`. Whatever is answering on this origin, it is not the dashboard -- usually a wrong port. |
| `cookie secure` | the login page set a session cookie without `Secure` on an https origin: the trusted-proxy case in §1. `SKIP` here means the login page set no cookie at all, so there was nothing to judge; sign in on the phone and look at the cookie in devtools. |

## 7. Not here

Push notifications (alerts still go to email and webhooks), an iOS app, a
Play Store listing, and phone layouts for the three side apps. All of them
are `MOBILE_PLAN.md` §7.

One more thing worth knowing if you change a page: the sweep in
`docs/mobile/SWEEP.md` drives headless Chrome over every page at 390 px and
768 px and fails on a page that scrolls sideways or a control too small to
hit. It is how the layouts above are kept true.
