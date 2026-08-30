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

Items marked **(as planned; see MOBILE_PLAN.md §4 Mx)** are contracts the
matching work package is building as this is written, trued up after it
merges.

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

* Every page is usable at 390 px wide with one thumb, with no sideways
  scrolling of the page itself (as planned; see MOBILE_PLAN.md §4 M1, M2, M3).
* Tables that cannot be stacked scroll sideways **inside their own box** --
  the fleet grid and the assignments matrix are the two that do this. The
  page under them does not move.
* Controls are at least 44 px tall on a touch screen. On a mouse the pages
  are pixel-for-pixel what they were.
* The navigation drawer, the projects sidebar (a bottom sheet on a phone) and
  the settings strip are all reachable one-handed.
* The three side apps -- `/broll`, `/music`, `/ytdl` -- work but are not laid
  out for a phone yet. They are their own round (`MOBILE_PLAN.md` §7).
* The Timeline Cards page is a separate thing with its own phone layout and
  its own installable icon. Installing the dashboard does not change it, and
  the dashboard's service worker never touches `/cards/`.

## 3. Installing it

### Android, Chrome

1. Open the dashboard and sign in.
2. `⋮` -> **Add to Home screen** (it may say **Install app**).
3. Confirm. The icon lands on the home screen; opening it gives the
   dashboard with no browser chrome, in its own task.

If Chrome offers a plain shortcut instead of an install, the origin is not
https or the manifest is not being served -- run the checker (§6).

### iOS, Safari

1. Open the dashboard and sign in.
2. Share -> **Add to Home Screen** -> **Add**.
3. The icon opens the dashboard full screen with the status bar kept.

iOS has no install prompt and no `beforeinstallprompt`; the Share sheet is
the whole mechanism. Everything else works the same, except that Safari
evicts an unused site's storage after a few weeks, which for this app means
the offline page and cached styles get re-fetched -- nothing else is stored
on the phone.

### The Android app

A studio that wants a signed APK its editors install (own icon, no browser
chrome, no "add to home screen" instructions) builds a Trusted Web Activity
around this same install. The whole path -- build it, paste the fingerprint
into Settings, verify -- is `docs/ANDROID.md` (as planned; see
MOBILE_PLAN.md §4 M5). The one symptom to recognise: **an app that opens with
a URL bar has failed asset-link verification**, which is a settings problem,
not a build problem.

## 4. What polls, and when

The dashboard is a status board: pages refresh themselves rather than making
anyone pull down. On a phone that is a battery and a data question, so:

| what | how often |
|---|---|
| live transfers (on `/` and `/transfers`) | 2 s on a desktop, 10 s on a touch device |
| project bins | 5 s |
| the fleet grid, the jobs table | 15 s |
| the projects sidebar | 30 s |
| the fleet-halt banner | 60 s |

**Nothing polls while the page is hidden.** Switch apps, lock the phone, or
move to another tab and every one of those stops; coming back refreshes once,
immediately, and resumes (as planned; see MOBILE_PLAN.md §4 M1-M4). A phone
in a pocket costs the server nothing.

## 5. Offline

The installed app is not an offline app, and pretending otherwise would be
worse than saying so. It shows the fleet's live state, which by definition
comes from the server.

* With no network, opening the app gives **the dashboard's own offline page**
  -- the product's look, one sentence, a `[ RETRY ]` -- instead of the
  browser's dinosaur (as planned; see MOBILE_PLAN.md §4 M4).
* Styles, scripts and icons are served from the phone's cache, so that page
  appears instantly.
* Nothing else is cached. No page of fleet data, no API response, no partial
  and nothing from `/login` is ever stored on the phone: a cached fleet page
  would be a stale answer to "is anything red", which is the one question the
  board exists to answer, and a cached page from a signed-in session is a
  page the next person to pick up the phone should not see.
* Anything queued while offline is not queued: actions need the server. Do
  them again when the bars come back.

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
