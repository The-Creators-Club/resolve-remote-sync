# Dashboard: every page, panel and control

Terms used throughout:

- **Dashboard**: the web server on the NAS that the editors' computers report to and people sign in to with a browser.
- **Companion**: the CC Sync program on each editor computer. Its **tray** is its icon menu.
- **Computer** / **machine**: one editor computer that has reported. A person can own several.
- **Admin**: a signed-in user the dashboard treats as an administrator. **Editor**: any other signed-in user.
- **Tick** / **untick**: put a project into, or take it out of, a computer's **sync plan** (the list of projects that sync to that computer). A tick has a **mode**: `full` (normal) or `upload only` (the computer only sends its video originals up; nothing comes down).
- **Partial**: an HTML fragment fetched by the page itself (with the htmx library) and swapped into a window, either on a timer ("polled") or when a button is pressed.
- **Window**: a framed panel on a page with a title bar and a fold (collapse) button.
- **Tag** / **chip**: a small labelled square with a lowercase word showing a state. Most carry an explanation in a tooltip; on a touch screen tapping it opens the hint sheet (below).
- **Lanes** (the three ways a computer syncs), shown in plain words on every page: lane A = "upload" (video originals up to the server), lane B = "proxy download" (small edit copies down), lane C = "folder sync" (Syncthing keeps project folders the same everywhere). An unknown lane name is shown as itself.

## Shared page frame (every page)

(source: shell.html, partials/topbar.html, partials/stamp.html, partials/halt_line.html, partials/hint_sheet.html, partials/settings_nav.html, ui.py `_render`, ui_chrome.py)

- **One look only.** Every page uses the "CC Terminal" look. Every htmx request a page makes carries a header `X-CC-UI: terminal` plus the CSRF (cross-site request forgery) token; per the template comment, a request without that header is told to reload the page before the route runs (the gate itself is in app.py, not in this part).
- **Browser tab title** on every page is the studio short name in capitals, followed by the page name (for example "STUDIO: SYNC STATUS"). The studio name falls back through: site `org_short`, site `org_name`, site `product_name`, the server's product-name setting, then "CC Sync".
- **Page icon, home-screen icon and phone status-bar colour** (`#070403`) are set on every page; the page links the web app manifest (except the Cards landing, which links its own).
- **Sign-in expiry banner**: every signed-in page carries when the sign-in ends (Unix seconds); a script (cc.js, not in this part) draws a banner as the end nears. Empty on the sign-in page.
- **Collapsed-section memory across refreshes**: when a window body is swapped by a poll, every foldable section marked with a key keeps its open or closed state, and any open pop-up sheet inside the swapped area is reopened at the same scroll position.
- **Deep-link scroll**: if the address has a `#anchor` and that element only arrives with a later fragment, the page scrolls to it once it appears (once per page load).
- **The one confirm dialog**: every action that asks "are you sure" uses one modal dialog titled "are you sure", with the question text, a focused **Cancel** button and a **Yes, do it** button. (The two sign-out-everywhere buttons use the browser's own confirm box instead.)
- **Toast slot**: one status line at the bottom for short messages (filled by scripts outside this part).
- **Hint sheet ("what this means")**: tapping a tag, a status light or any element with a tip opens a sheet showing the label and its explanation, with "tap anywhere to close" at the foot.
- **Fleet stop line** (signed-in users only): loaded on page load and re-read every 60 seconds while the tab is visible, from `GET /partials/halt-line` (any signed-in user; 401 "sign in first" otherwise).
  - While the fleet stop is on: red line, tag **stopped** (tip "Every computer has stopped syncing because an admin stopped the fleet."), "Syncing is stopped on every computer (N hours so far, M computers in the fleet).", the reason the admin typed, "Set by <who> <time ago>; it releases itself <in Xh Ym> unless somebody keeps it on." Admins also get a **Start syncing again** link to Users, fleet stop panel. "M computers" counts every registered computer, including switched-off ones. Hours are whole hours since it was set.
  - After the stop has expired: amber line, tag **expired**, "The fleet-wide stop has expired and syncing has started again everywhere.", "It was set for: <reason>", "Set by <who> <ago>, expired <ago>." Admins get **Take this notice down** (link to Users, fleet stop panel).
  - Nothing is shown while the fleet is syncing normally.
  - The "releases itself" time reads "any moment now" under one minute, then "in Nm", "in Nh Nm", "in Nd Nh".
- **Time wording** used everywhere: "never" for no time; under a minute "Ns ago", then "Nm ago", "Nh ago", "Nd ago". A stamp with no time zone is read as UTC. An unreadable stamp is shown as typed.
- **Size wording**: B, KB, MB, GB, TB in steps of 1024, one decimal above bytes; "-" for none.
- **Time-left wording**: "Ns", "Nm", "Nh MMm", "Nd Nh"; "-" for none.
- **Text progress bar**: ten (or sixteen) block characters, filled in proportion; question marks when the amount is unknown.
- **Support address**: any problem's "fix" sentence that says "send us" or "to support" has the site's `support_contact` (vendor default unless the site overrides it) put into it.
- **Display names**: wherever a person is named, their chosen display name is shown if they have one, otherwise their sign-in name. Only on signed-in pages.

### The header bar ("HUD")

- **Brand link** (logo plus the studio name), top left, goes to `/` (sync status).
- **Main navigation** (signed-in only), each item marked when it is the current page:
  - **sync** (`/`), always.
  - **b-roll** (`/broll/`) only when the b-roll module mounted fully; **music** (`/music/`) only when the music module mounted fully; **youtube** (`/ytdl/`) only when the YouTube downloader mounted fully; **cards** (`/cards/`) only when Timeline Cards mounted fully; **sorter** (`/sorter/`) only when the Footage Sorter mounted. A module that failed or is degraded gets no link.
  - **transfers** (`/transfers`), always.
  - **settings**, admins only, goes to the Health page (`/admin/health`). It is lit on every Settings page except Transfers.
  - **more** button (shown at medium widths, 601 to 900 px) opens the "more" sheet; music and youtube fold into it at that width.
- **Problem count** (admins only, on full pages; absent at zero): red light, "N problem(s)", links to `/go/notices` (the Health page's notices). The number is the count of open problems the server found with severity "error". Title: "the server has found problems it cannot fix by itself".
- **Alert count** (admins only, absent at zero): "N alert(s)" (errors plus warnings from the last alert scan's stored counts), red light if any error, amber otherwise; links to `/admin/health`. Hidden on small screens.
- **Freshness stamp** (signed-in): "updated <time ago>", the server's own clock at the moment it last answered, re-read every 30 seconds while the tab is visible from `GET /partials/stamp`. If the server cannot reach Syncthing it adds an amber light and **stale** (": syncthing unreachable, data may be stale" on wide screens; tip "Syncthing is unreachable: the data on this page may be stale."). On a phone only the stale warning is shown, never the time. If the collector status cannot be read, Syncthing is assumed reachable (no false alarm).
- **User name** (links to `/account`), with "@admin" for admins; hidden on small screens.
- **menu** button opens the account menu: "signed in as <name> (admin)", **your account** (`/account`), **help** (`/help`), **installer** (`/download`, the click is the download), a "session" heading, **sign out** (plain form POST `/logout`), **sign out everywhere** (plain form POST `/logout-everywhere`, browser confirm "Sign yourself out of every browser, including this one? You will need to sign in again to finish what you are doing.").
- **sign in** link when not signed in.
- **Phone dock** (bottom bar on phones, signed-in only): sync, b-roll (if mounted), cards (if mounted), sorter (if mounted), transfers, more.
- **"more" sheet**: problem count, alert count, music, youtube, settings (admins), installer, help, "<name> (admin): your account", sign out, sign out everywhere (same confirm), an install slot that a script fills with an INSTALL button when the browser offers to install the app, and **close**.
- **`GET /partials/topbar?current=<page>`** (signed-in pages; the mounted b-roll, music and YouTube apps fetch it): the same header as a fragment, with the freshness stamp and, for admins, the problem and alert counts. An unknown `current` lights nothing.

### The Settings strip

- Shown on every Settings page. Three labelled groups, each a row of links:
  - **Run the fleet**: site (`/admin/settings`), users (`/admin/users`), sync plans (`/admin/assignments`), transfers (`/transfers`, visible to editors too), packages (`/admin/packages`), jobs (`/admin/jobs`), history (`/admin/audit`), setup (`/setup`).
  - **Is it healthy**: health (`/admin/health`), invariants (`/admin/invariants`), protection (`/admin/protection`), alerts (`/admin/alerts`).
  - **When it breaks**: recovery (`/admin/recovery`), help (`/help`, visible to editors too).
- An editor sees only the non-admin entries (transfers, help); a group with nothing visible is not drawn. The current page is marked. On a phone the strip scrolls sideways.

### Panel short links

- **`GET /go/<panel>`** (redirect, 303): notices to `/admin/health#server-notices`; collector to `/admin/health#fleet-collector`; diagnostics to `/admin/health#fleet-diagnostics`; admin-fleet-halt to `/admin/users#admin-fleet-halt`; ai-providers to `/admin/settings#ai-providers`; restore to `/admin/recovery#restore`; dashboard-update to `/admin/packages#dashboard-update`. Any other name: 404 "no such panel".

### Static files and the installable app

(source: static_files.py, ui_assets.py, ui.py)

- **Static file links carry a content fingerprint** (`/static/<file>?h=<first 10 hex characters of the file's sha256>`), so a redeploy of the same version still changes the address. A file the build does not have gets a plain address.
- **Caching rules for `/static/`**: an address whose fingerprint matches the file's current content is cached for one year as unchangeable; an address with any other fingerprint is never stored; anything under `/static/fonts/` is cached for a year; everything else must be re-checked every time. Only successful (200) and not-modified (304) answers get these rules.
- `.woff2` fonts are served as `font/woff2`.
- **`GET /manifest.webmanifest`** (open without sign-in, per a comment): the app manifest file with its `name` and `short_name` replaced by the site's product name. If that fails, the file is served as is; if the file is missing, 404 "no manifest on this server".
- **`GET /sw.js`** (open without sign-in, per a comment): the service worker script, with the dashboard version and the list of fingerprinted style sheets, shared scripts (pwa.js, htmx.min.js, htmx_errors.js, tab_memory.js) and fonts to store for offline use written into it. Served with permission to control the whole site and "no-cache". 404 "no service worker on this server" if absent.
- **`GET /offline`** (open without sign-in, per a comment): the page shown when the phone or computer cannot reach the dashboard. It is drawn as if nobody were signed in (no header, no name, no token). Content: the studio name, an **offline** window, "This device cannot reach the dashboard right now. Nothing here is live: check the network, then try again.", and **Try again**, which reloads the address that failed (from `/offline` itself it goes to `/`).

## Sign in and sign out

(source: ui.py `/login`, `/logout`, `/logout-everywhere`; login.html)

- **`GET /login`** (anyone):
  - `next=` names where to go after signing in. Only a same-site path starting with a single `/` is kept; anything else (an external address, `//host`, `/\host`) becomes `/`.
  - A signed-in visitor is sent straight to `next` (303), unless `renew=1` is given, which shows the form anyway so they can start a fresh sign-in.
  - If the server is configured for https only (cookie marked secure) and the page was reached over plain http: error 400 "this dashboard is configured for https only (DASH_COOKIE_SECURE=1) but you reached it over http. Use the https URL."
  - `signed_out=1` (where a real sign-out lands): the page deletes the Timeline Cards front door's saved episode list (`cards-landing` browser cache) on this device. An expired sign-in does not do this.
- **The sign-in page** (no header bar): the studio name in capitals, a **sign in** window.
  - If the dashboard uses single sign-on (`auth_method = oidc`): a **Sign in with SSO** button (goes to the SSO login path with `next`). The password form is then hidden and replaced by "Single sign-on is configured for this dashboard. Admin sign-in if the identity provider is down.", where **Admin sign-in** opens `/login?local=1`. With `local=1` the password form appears under an "admin sign-in" divider.
  - Otherwise the password form: "Use the username and password your admin gave you.", "Your admin creates this account for you. If you do not have one yet, ask them before installing.", fields **username** (no auto-capitalisation, no spell check) and **password**, button **Sign in**.
  - With `renew=1`: extra line "Sign in again to keep this phone or computer working offline for another 100 days."
  - A refusal shows a red **refused** tag and the message.
- **`POST /login`** (anyone):
  - Refuses a body over 8 KB with 413 "request body too large" (checked from the declared length and the real length). More than 16 form fields or an unreadable body: 400 "malformed form body".
  - Username is trimmed and lower-cased.
  - Messages, in order of checking:
    - No session secret configured: "login not configured on the server (DASH_SESSION_SECRET unset)".
    - Https-only server reached over http: "this dashboard is configured for https only (DASH_COOKIE_SECURE=1): use the https URL".
    - Too many recent failures for this username or address: a message naming the wait (wording from auth.py, not in this part). Unknown usernames are throttled the same as real ones.
    - Single sign-on configured and the user is not an admin: the generic refusal (admins only may use the password form then).
    - Credential check busy (too many checks at once): "the server is busy checking sign-ins. Try again in a moment." (does not count as a failure).
    - Wrong password, unknown user, or a deleted person (a deleted person's NAS password still works, but the dashboard refuses): the single generic message "sign-in refused - check your username and password, then try again". Every failure is recorded toward the throttle.
  - On success: failures are cleared, a new session cookie and server-side session row are created, and the browser's previous session (if any) is revoked (recorded as "renewed" or "replaced").
  - **First-run steering**: an admin who signed in without asking for a specific page lands on `/setup` instead of `/` while any required setup step is still outstanding. Never for an editor. If the database cannot be read, the normal landing is used.
- **`POST /logout`**: ends this session (deletes the server-side row too) and goes to `/login?signed_out=1`.
- **`POST /logout-everywhere`**: signed-in only (401 "not logged in"); revokes every session of this user on every device, deletes the cookie, goes to `/login?signed_out=1`.

## Installer download

(source: ui.py `/installer`, `/download`, `/download/{platform}`; installer.html)

- **`GET /download`** (signed-in): reads the browser's User-Agent. "Mac OS" or "Macintosh" sends you (303) to `/download/macos`; "Windows" to `/download/windows`. Anything else (Linux, a trimmed browser string) shows the platform chooser page instead of guessing.
- **`GET /download/windows`** and **`/download/macos`** (signed-in): sends the current published **onboard** package (the full clean-install and repair wizard, not the bare companion) for that platform, as a download named with its stored, versioned file name, with headers `X-CCSync-SHA256` and `X-CCSync-Version`.
  - Any other platform: 404 "unknown platform: use /download/windows or /download/macos".
  - Nothing published: 404 plain text "No <platform> installer has been published for this fleet yet, so there is nothing to download. Ask whoever set this dashboard up for the installer." plus "Admins: publish one with `tools/publish_latest.py --kind onboard --platform <platform>` (or upload it on Settings > Packages)."
  - Published but the file is gone from disk: 404 "installer file is missing on the server: re-publish it".
- **`GET /installer`** (signed-in): the chooser page, "INSTALLER", "for a new editor computer, or to repair one".
  - Lead text: "The full clean-install and repair package for a new editor computer. Save it to that computer's own disk: running it off the shared drive locks the file for everyone, and the setup wizard refuses it."
  - Phone-only note: "On a phone: this package cannot be run here. Download it and send it to the editor's own computer, Windows or macOS, and run it there."
  - One window each for **windows** and **macos**. The one matching this browser is marked "this computer".
    - If published: version, size, "published <ago>", sha256 (first 16 characters, full value in tooltip), **Download for Windows** / **Download for macOS**.
    - Windows note: the beta is not code-signed; expect "Windows protected your PC" (SmartScreen); steps: run, More info, Run anyway; if no Run anyway, Properties, tick Unblock, OK, run again; Smart App Control must be turned off first.
    - macOS note: not notarised; steps: open once and click Done, System Settings, Privacy & Security, Open Anyway with the Mac password, open again and click Open; may repeat after a companion update.
    - If nothing is published: "Nothing published for this platform yet." (not an error).

## Home page: SYNC STATUS (`/`)

(source: ui.py `page_fleet`, `partial_fleet`, `safe_to_close`, `CHIP_HELP`; ui_home.py; fleet.html; partials/home_macros.html, fleet_grid.html, projects_tree.html, home_problems.html, home_transfers.html, home_queue.html, home_fix_root.html, computer_answer.html, plan_changes.html)

- **Who**: any signed-in user. An editor sees their own computers plus summary counts; an admin sees the whole fleet. An admin can add `?as=<editor>` to look at and tick for another person; for an editor `?as=` is ignored. `?machine=<name>` narrows the sync queue and the fix-root line to one of that person's computers; a name the person does not own is ignored (the person's view is shown).
- **Page head**: "> SYNC STATUS", "N computer(s) · N project(s)".
  - Admins: **Stop the fleet** link (goes to `/go/admin-fleet-halt`, the switch on Users). Tip: "Opens the fleet stop on Users: it pauses syncing on every computer at once until you start it again. Nothing is deleted, and the pause ends by itself after 24 hours."
- **Syncthing unreachable line** (when the server cannot reach Syncthing at first paint): amber **stale** tag, "The server cannot reach Syncthing. The numbers below may be old. Nothing is lost: every computer keeps syncing.", **What to do** link to `/admin/recovery`.

### Left column: ticking_for and projects

- **ticking_for window**: a small form that decides whose plan, and which computer's, the tree ticks.
  - Admins with other known editors: **editor** drop-down, "<me> (me)" plus every other known editor; changing it reloads the page with `?as=` (and clears the computer choice).
  - When the chosen person has more than one computer: **computer** drop-down, "every computer" plus each computer; changing it reloads with `?machine=`. Tip: "A sync plan belongs to a computer, not a person. Every computer ticks or unticks all of them at once."
  - Exactly one computer: plain line "computer: <name>".
  - A **Go** button only when scripts are off.
  - When acting for someone else: warning "acting as <name>: a tick here starts a real sync on their computer".
- **projects window**:
  - A find box ("find a project", shortcut key `/` shown) that filters the tree as you type (the filtering script is cc/home.js, not in this part); "No project matches." when nothing matches.
  - The tree body re-reads every 30 seconds while visible and whenever any tick or untick on the page answers (`GET /partials/projects-tree?current=&machine=&as=`, signed-in only, 401 "sign in first").
  - Count line: "N of M ticked for <computer or person>".
  - Projects are grouped into foldable year and show folders (each with its project count); a folder holding the current project starts open.
  - Each project row: a checkbox (only when there is a person to tick for) and the project name linking to `/project/<slug>` (keeping `?as=`).
    - Checkbox tooltip: wired person or computer: "<name> is wired to the server: it works directly off the NAS and syncs nothing. Change it on that computer: tray, Settings, This computer." (checkbox disabled, but existing ticks stay visible). One computer picked: "Tick to sync <project> to <computer> only. Untick to stop it there." No computer picked: "Tick to sync <project> to every computer <person> uses. Per-computer plans: pick a computer above, or Settings, Sync plans."
    - The checkbox always sends the state it means (`mode=on` when unticked, `mode=off` when ticked), so a stale row can never do the opposite.
    - Confirm on untick for the whole person: "This removes <project> from <person>'s N computer(s) (<names>). Their copies stay on disk; nothing new comes down and proxy sync stops for it."
    - Confirm on untick for one computer: "This removes <project> from <computer>. Its copies stay on disk; nothing new comes down and proxy sync stops for it there."
    - Confirm on ticking the project whose page you are on, when the API has a capacity warning for it: "<capacity sentence> Sync it there anyway?" (sentence built outside this part).
    - Tags: **upload only** (links to the glossary entry "Upload only"); **link** (red) when a shared-folder link on the project needs attention; a number with a down-arrow when N computers are still catching up.
  - Empty tree: "No projects yet: they appear after the server's first look at the tree."

### Readouts (four boxes)

- Drawn on first paint and refreshed whenever the computers window re-reads (sent alongside it, only when that answer carries the projects view).
- **online**: "N / M", where M is computers with at least one project ticked (a wired computer, or one with nothing ticked, is left out) and N is those not silent. Foot: "<computer> not heard from[, and N more]" (amber) when any is silent; "every computer with a project ticked has reported" (green); "no computer has a project ticked" (plain). A computer with nothing ticked never makes this amber.
- **moving**: total bytes still owed (files moving now plus queued uploads and downloads, from the transfers view). Foot: "N project(s) catching up", or "N file(s) moving now", or "nothing waiting".
- **problems** (admins only): the number of open "error" problems the server found (the same count as the header). Foot: "N warning(s)" if any warnings; "listed below with what to do" if only errors; "nothing needs you" (green) if none.
- **in sync**: "N / M", M = projects ticked anywhere (by this person for an editor; by anyone for an admin), N = those not behind and not "getting ready". Foot "all caught up", "N still catching up", or "no project is ticked anywhere".
- If the transfers and ticks cannot be read, "moving" and "in sync" fall back to the projects view's own figures.

### problems.log window (admins only)

- Loads on page load and every 60 seconds while visible (`GET /partials/home-problems`, admin only). Title-bar link **health** to `/admin/health`.
- Each open problem the server found: severity tag (**error** / **warn** / **info**), subject, the name of the check that found it, when last seen (first seen in tooltip), the diagnosis text, the fix text (with support address), a link button whose label and address come from the problem kind (default "take me there"), and **dismiss**.
  - Dismiss confirm: "Dismiss this? It is only hidden. If the server finds the same problem again it comes straight back, so dismissing it is not a fix." (`POST /partials/notices/{id}/dismiss?view=home-problems`, admin only). If it was already gone: "that notice is already gone. Reload the page."
- No problems: "All clear. N of M checks ran and found nothing wrong.", plus an amber tag "N never ran" when some registered checks have never run.
- Fold-out **what the server checks** (N checks): every registered check with **found** (it is in the list above), **ok** (ran recently, found nothing), or **not checked** (registered but never run, or its last run is no longer recent: the tooltip names the date it last ran). Only recent evidence counts as OK.

### computers window

- Re-reads every 15 seconds while visible (`GET /partials/fleet`, keeping `?as=`; signed-in, scoped like the page). Bar meta: "N computer(s) · collector <ago>" (the newest finish time of the collector's check cycles). Bar link **what the words mean** to the Help glossary.
- **Banners at the top of the window** (inside the polled area):
  - Fleet stop on: **stopped**, "Syncing is stopped on every computer: an admin stopped the whole fleet." with reason and "set by <who> <ago>".
  - Proxy download safety breaker tripped on some computers: **stopped**, "Proxy download stopped on N computer(s): <editor/machine list>. Check the server, then press "Resume" on that computer's row (or have each editor use the tray's "Resume proxy download")."
  - Computers paused by their own user: **paused**, "Syncing is paused on N computer(s), by whoever is sitting at it/them: <list>."
  - Report sections the dashboard is discarding: **ignored**, "N report section(s) ignored: <names>. Companions are computing and sending this and the dashboard is throwing it away. Last seen <ago> from <machines>."
  - Share removals refused by the safety limit: **refused**, "N share removal(s) refused: shares are frozen. No untick is being applied on N folder(s), N computer(s). Approve the pending devices (Settings, then Users), then this clears itself on the next cycle. If these removals are what you meant (limit N), apply them here, or have an admin raise the per-computer allowance so the limit grows with the fleet (Settings, Sharing safety)." Admins get **Apply these N removal(s)** unless the list was cut short (`POST /partials/admin/enforce/approve-removals`, admin only; the count travels from the banner; tip says the approval is "Good for one hour" and points to the list under problems; a refusal shows as a red banner).
  - Project deactivation refused: **refused**, "<message>. The project list is being kept exactly as it was. Check Syncthing on the server: a config it cannot load answers with zero folders."
  - Computers whose reports are being refused: **refused**, "N computer(s) is/are being refused: <list>. They are reporting and the dashboard is turning them away (<reason>). Have each editor click "Sign in..." on that computer's tray."
  - Computers still signed with a retired key: **old key**, "N computer(s) still on a retired signing key. They are accepted because DASH_SESSION_SECRET_PREVIOUS still carries the old key: <machines>. Each one clears when its editor signs in again at the tray. Remove that variable once this reaches zero."
  - Update checks failing: **no updates**, "No successful update check for N days. last checked <ago> - <error>. This site is not receiving fixes, which looks the same as no fixes having been published."
  - Every dashboard update on offer needs a new container image: **new image**, "Every dashboard build on offer needs a new container image. <versions> bring dependencies this container does not have, so no update can be applied from this dashboard. To apply it: <NAS-specific hint>."
- **Editor scope line**: "Showing your computers. N other computer(s) in the fleet: N unhealthy, N on an old build."
- **Column heads**: computer, sync (tip explains up / down / share), issues, version, last report.
- **One row per computer**:
  - Status light and a one-line headline (text and colour from the health module, not in this part; a computer with nothing ticked stays muted however long it is quiet).
  - Computer name, the person's display name (and sign-in name if different).
  - Three lane lines (upload, proxy download, folder sync), each with a mini meter and its state word, ", stalled" when the lane's reason says "no progress"; tooltip "<lane>: <state> - <reason or last error>". Lane colours are capped by the row's headline level (a muted row never shows a red or amber lane; a busy green lane is drawn as busy).
  - **Issues** (errors first, then warnings; "nothing wrong" when none). Each tag carries its explanation:
    - **proxy download stopped itself** (breaker): "<reason>, stopped <ago>. Upload and folder sync are still running; nothing was deleted."
    - **stopped by your admin** (fleet stop) or **syncing paused on this computer** (local pause), with the reason.
    - **sync engine down <ago>[, N restarts failed]** (not on wired computers): "the Syncthing engine on this computer has been down since <time>; N automatic restart attempt(s) have failed; automatic restarts are switched off or suppressed on this computer, so nothing is trying. Last error: ..."
    - **clock <amount> ahead/behind**: "this computer's clock is <amount> ahead of/behind the server's. Proxy download uses a minimum file age, so a clock this far out can make it transfer nothing at all while reporting no error. Fix the clock on that computer (enable automatic time)."
    - **stalled: <lane>[, killed]**: "<lane> on this computer made no progress for N second(s) and was killed / and was reported without being killed, <ago>. A local drive that stops answering reads exactly like this." Only while the stall is current.
    - **being refused: sign in on its tray**: "the last report from this computer was refused <ago>: <reason>. Nothing below is current. The editor has to click Sign in... on this computer's tray."
    - **update kept crashing**: "this computer installed <version>, kept crashing on it and was rolled back, last <ago>. It will not take that build again on its own. Do not install it by hand: publish a newer build."
    - **update failed xN**: "this computer has tried to install <version> N time(s) and failed, last <ago>: <error>. Antivirus quarantine, a proxy mangling the download and a full disk all look like this."
    - **recalled build**: the recall reason (or "no reason given").
    - **unverified**: "this companion has not signed in with verified credentials".
    - **suspended**: "an admin paused this person on Settings, Users. Their computers are being turned away and their projects are unshared. Their sync plan is kept: Resume puts it all back."
    - **reverted from <version>**: "this computer installed <v>, could not start it, and put itself back on <running>. That build should not be made current for the fleet."
    - **unfiltered folders: N**: "N Syncthing folder(s) on this computer have no ignore filter written: <names>. Without it, folder sync carries camera originals both ways."
    - **conflicts: N**: "N Syncthing sync-conflict file(s) in this computer's tree. Two people saved one project file; nothing was lost, but somebody's edit is sitting in a renamed copy."
    - **N clips outside the tree**: "the project open on this computer references N clip(s) from outside the sync tree[, N of them under the wrong drive letter]. They will never upload, so the timeline opens with red media on every other computer. Scanned <ago>."
    - **N project(s) with clips only here**: "N clip(s) exist only on this computer, outside the sync tree, in Resolve projects it does not have open: '<first three names>'[ and N more]. They will never upload until the editor opens each project and presses FIX ALL. Checked <ago>."
    - **N stray project dirs**: "N project folder(s) on this computer's disk are not in the sync tree, holding <size>. Nothing in them is on the server or visible to anybody else."
    - **project folder moved**: "N project folder(s) on this computer are not where the tree expects. Syncing for those projects looks busy and moves nothing. Move it back, or use "Move on the server and on every computer" on the project page."
    - **won't upload: N**: "N file(s) exist on the NAS under the same name at a different size (counted under <subfolder>). Upload never overwrites a file already on the server, so this computer's newer versions will never go up." (The "counted under" part only when the companion named the folder it scanned.)
    - **relayed: N**: "N Syncthing peer(s) connected via a RELAY, not directly: folder sync on this computer is limited to relay speed (1-5 MB/s), not the link. Checked <ago>."
    - **orphans: N**: "<size> of orphaned rclone .partial files left on the NAS by an interrupted upload. Never deleted automatically; remove them by hand to reclaim the space."
    - **express upload failed** (with the last error), or else **express dropped: N** ("N file(s) dropped by the express upload's batch cap: they still go up on the next periodic pass.").
    - **crashes: N**: "N background task(s) on this computer have crashed and written a report (newest: ...). The tray stays up and syncing looks normal, so ask the editor to open <companion diagnostics location> in the companion and send it to you."
    - **youtube clips waiting for resolve: N**: "N YouTube clip(s) downloaded to this computer are waiting to go into Resolve (<reason>). They are on the disk; nothing is lost. Reported <ago>." Or **youtube import gave up**: "this computer gave up filing N downloaded YouTube clip(s) into Resolve: <reason>. They stay on the disk under Youtube/ and are retried when its companion restarts. Reported <ago>." (only when its state is not ok or idle).
    - **N need proxies**: "N clip(s) on this computer have no proxy yet, so nobody else on the fleet can see that footage (proxy generator: <state>); N queued to encode."
    - **disk N%** (amber or red, only when the disk status is not green): "this computer's sync drive has <free> free of <total>; its system drive has <free> free. Measured <ago>. Proxy download fills a drive file by file. When the drive drops below its floor, proxy download stops and .ccsync-trash is emptied oldest first. On CC Sync newer than 0.9.78 it is emptied until the drive has twice the floor free, which starts proxy download again. On 0.9.78 or older it stops emptying at the floor, so proxy download starts again only once somebody frees space up to twice the floor, or presses "Resume" in that computer's tray. Either way, a proxy download the safety breaker has stopped waits for somebody to resume it, from that computer's tray or by an admin with "Resume" on this row."
    - **trash: <size>** (only above 5,000,000,000 bytes): "N recoverable file(s) in this computer's .ccsync-trash. Pruned automatically after 14 days."
    - **ingest staging <size>**: "<size> of footage is in this computer's drop folder and has not been filed into a project yet. It is on one disk."
    - **vram** (the b-roll indexing warning text) and **music model** (the music indexing warning text).
    - **version unknown** ("this companion has never reported its version: it predates the upgrade channel") or **out of date** ("<platform>: running <v>, current is <v>").
  - **Work in progress** (after the issues):
    - **indexing b-roll: done/total** (amber if a warning, else highlighted), tooltip: batch id (8 characters), clip, state and gate, model tier, percent of this clip, failed count, reported ago.
    - **indexing music: done/total**, the same for music tracks.
    - **<job label>: N%** or "job N", linking to `/admin/jobs`, tooltip with job number, kind, state, file and last heartbeat.
    - **volunteering until <time>**: "somebody at <machine> clicked 'take fleet jobs now', so this computer is offered work while they use it - until <time> UTC, or until they click it off. Nothing else is bypassed: a stop, an update or a proxy download that stopped itself still refuse."
    - Timeline Cards role tag, by its reported state: **cards[: <timeline>][ v<version>]** (running, green): "this computer is serving the Timeline Cards page from its own Resolve - <timeline> <detail> - last talked <ago>"; **cards stopped** (red): "the Timeline Cards role on this computer has STOPPED: the page will not update until its companion is restarted."; **cards refused** (amber): "...refused to start."; **cards signed out** (red, adds "(HTTP <status>)"): "...is being refused by the dashboard (its credential is wrong or expired), so the page it serves is stale."; **cards offline** (amber): "...cannot reach the dashboard, so the page it serves is stale." A connected role with no state reads as running. A state outside these five shows nothing.
  - **Version** column: the running companion version ("?" if unknown), plus "current <v>" when out of date.
  - **Last report** column: time since the last report.
  - **details** fold-out (stays open across refreshes), with "· N note(s)" beside it when the health module counted notes (the list in its tooltip):
    - storage: "disk N% used, <free> free".
    - transport: "direct: N" (tooltip "N Syncthing peer(s) connected directly. Checked <ago>.").
    - resolve (only when this computer has sent the detail; absent for an older companion, never shown as zero): connected / not connected / not checked; project open; "wedged N s in <call>" in red; "proxies attached N, failed N (why)"; "proxy queue capped at N"; low-space note; "stills: <status> (<instruction>)" when stills are not OK; fold-outs listing missing clips (label depends on the companion version) and clips "refused: the path is not the canonical one".
    - reporting: one muted tag per category this computer does not send: "not reported by this computer: <label>", explained as a privacy switch on the computer (tray, Settings, THIS COMPUTER, PRIVACY) or the site (Settings, Site, TELEMETRY), never a fault.
    - this computer: "GPU NG, nvenc" and "whisper" when reported (whisper tip: "this computer has the whisper venv and the pipeline checkout the transcription jobs need").
    - version: "<platform>, running <v>, current is <v>".
    - licence: the accepted licence status text (green, amber or dim), with accepted time and the first 12 characters of its sha256 in the tooltip.
  - **Admin keys inside details**:
    - **Resume** (only when the proxy download breaker is tripped and no resume is waiting): asks that computer to start proxy download again on its next report (`POST /partials/admin/machines/resume-lane-b`, admin only). Once asked it shows **resume asked** ("waiting for <machine> to report in and pick this up"). If the computer is no longer in the fleet: "That computer is no longer in the fleet, so nothing was resumed. Reload the page."
    - **Ask this computer why**: asks the computer to upload its own diagnostics on its next report (`POST /partials/admin/machines/ask-why`, admin only; with `?view=none` it answers empty). Once asked: **asked why** ("waiting for <machine> to report in and send its diagnostics"). An unknown computer is silently ignored (the row stays as it was).
    - **Read the answer** (only when a diagnostics bundle exists): loads that computer's bundles into the what_computers_said window.
- **No computers**: "No computer has reported yet. Each companion is given this dashboard's address when it is installed: if one is running and is not here, ask that editor to open <diagnostics location> and send you what it copies."
- **lost computers** fold-out (open by default): computers with no report for over a week, "Each one still holds its sync plan, and is still shared the projects in it." Table: status light, editor, computer (Syncthing device id in tooltip), platform, still planned ("N project(s): names" or "nothing"), last report. Admins get **Forget** with confirm "Forget the computer <m> (<editor>)? Its sync plan, its status rows and its Syncthing device go, so it stops being sent projects. Files already on it stay there. If its companion is still installed and signed in, it will register itself again on its next report." (`POST /partials/admin/machines/forget-lost`, admin only; a refusal leaves the row in place silently).
- **projects** fold-out: "N, N catching up", one line per project with a status light, a link to its page, "N editor(s), N behind, <size> queued" or "all synced".

### what_computers_said window (admins only)

- Starts with "Press "Read the answer" on a computer's row to read what it sent." Filled by `GET /partials/computer-answer?editor=&machine=` (admin only): with a computer named, its last five diagnostics bundles; with none, the newest bundle per computer.
- If the server has its own crash reports: "This server has N saved crash report(s) of its own." with **download crash reports** and "then send them to <support address>".
- **`GET /admin/diagnostics/crash-reports.zip`** (admin only): the server's own crash reports as one zip named `ccsync-crash-reports.zip`, built in memory, with a header giving the file count.
- Each bundle is a fold-out (first one open): editor, computer, a trigger tag (**lane error**: "a sync job failed, so this computer sent its own diagnostics"; **admin request**: "an admin asked this computer why"; **button**: "the editor used Copy diagnostics in the companion"; anything else its own name with underscores as spaces), when it arrived and the computer's own time if different, and the full text.
- When narrowed: "Showing <name> only." with **every computer**.
- None: "No computer has uploaded diagnostics yet. Press "Ask this computer why" in a computer's details, or have the editor open <location> in the companion. Companions older than the build that added this cannot send any."

### transfers window

- A fixed-height scrolling window (about 35% of the screen height) re-read every 2 seconds while visible (`GET /partials/home-transfers`, signed-in only, keeping `?as=`). Bar link **all transfers** to `/transfers`. Only what is moving now.
- **Safe-to-close line** (always drawn for an editor, never for an admin's fleet-wide view; amber when not safe). Built from the transfers view, for the signed-in person only (it never knows which computer the browser is on, so it names computers):
  - Some computer cannot list all of its originals and nothing is known to be owed: "Cannot tell yet: <computer> (<project>) holds more video originals than it can list to the dashboard, so some may not have uploaded. Leave it running and check its tray." If every such computer simply withholds its file list: "Cannot tell yet: <computer> does not report its file list to the dashboard, so the dashboard cannot tell whether everything uploaded. Check its tray." Never "safe".
  - No uploads owed, some downloads: "Safe to close: nothing of yours is waiting to go to the server. 1 file is still coming down and carries on where it left off next time." (or "N files are still coming down and carry on where they left off next time.").
  - Nothing at all: "Safe to close: nothing is transferring."
  - Uploads owed: "Not yet: N file(s) still uploading from <computers> (<size>), about <time>. Leave that computer running." / "Leave those computers running." / "Leave it running." (when some upload has no computer name). Adds "There may be more: <computer> holds more video originals than it can list to the dashboard." when applicable. The time is bytes owed divided by the current total upload speed (only when the speed is over 1 byte per second).
- Each moving file: up or down arrow, name, (admins) editor / computer, "folder sync" for a whole-project Syncthing row, meter and percent, speed per second, time left.
- Nothing moving: "Nothing is moving right now."

### plan_changes window (admins only)

- Loads on page load and every 60 seconds (`GET /partials/plan-changes`, admin only). Bar link **history** to `/admin/audit`.
- Every tick and untick in the last hour: when, who (display name), **ticked** / **unticked**, project (folder name; slug in tooltip), editor, where ("every computer (N)" for a person-level change, else the computer or "unassigned"), and **Undo** or "put back".
- **Undo** (`POST /partials/plan-changes/{audit_id}/undo`, admin only) restores exactly the placements that existed before the change (same computers, same modes), removing any it added. Confirm when the undo would take the project off computers: "This removes <project> from <editor>'s N computer(s) (<names>). Their copies stay on disk; nothing new comes down and proxy sync stops for it." The undo is itself recorded in the history and the collector is nudged. Results: "put <project> back for <editor>" or "removed <project> again for <editor>". Refusals: "that is not a plan change this page can undo"; "that record does not name a project and an editor, so it cannot be undone"; older than the undo window: "that change is more than an hour old, so it is no longer offered as an undo. Tick or untick it yourself if that is what you want."
- Empty: "No tick or untick in the last hour. Older changes are in the history."

### sync_queue window (when there is a person to show)

- Re-reads every 10 seconds while visible and after any tick on the page (`GET /partials/home-queue?as=&machine=`, signed-in; 401 "not logged in").
- Safe-to-close line (as above), then "For <person>[ on <computer>]: one project at a time, top to bottom."
- Table: position, status light, project name with tags **syncing now** (the one being worked on), **upload only** (glossary link), **gone** ("This project no longer exists on the server."), and "shares <subfolder> from <other project>" lines; synced (meter and percent, "upload only", or "no data yet"); left ("N files, <size>, <speed>/s, about <time> left", "synced", or "-"); **Untick**.
  - Untick removes the project from every computer of that person (`mode=off`, so a stale button never ticks). Confirm: "This removes <project> from <person>'s N computer(s) (<names>). Their copies stay on disk; nothing new comes down and proxy sync stops for it." Tip: "Stop syncing this project to <person>'s computers. Nothing already there is deleted."
- Empty: "Nothing ticked, so nothing syncs to this computer. Tick a project in the projects list." (link to the projects window). Never shown as a warning.
- **fix destination root** section: where the companion's "Fix all" puts files for the project open in Resolve on one computer.
  - When the person has more than one computer: buttons **last to report** and one per computer (plain links that reload the page with `?machine=`, keeping `?as=`).
  - "open in Resolve[ on <computer>]: <Resolve project>, files go into <folder> (set by an admin / matched by itself, then kept; admins change it in the project's project roots window)".
  - No match: tag **no match**, "no project in the tree matched; an admin can map it in a project's project roots window".
  - Nothing reported: "no Resolve project reported yet".

### Tick and untick route (shared by every page)

- **`POST /partials/selection/{editor}/{slug}/toggle`** with optional `machine`, `mode`, `view`, `slug_page`, `queue_machine`:
  - Allowed for the editor themself or an admin; otherwise 403 (401 when not signed in) "not allowed".
  - `machine` must be one of that editor's computers, else 404 "<editor> has no computer named '<m>'". No `machine` means the person: every computer they use.
  - `mode` absent: plain toggle. `mode=off`: remove only (no-op if not ticked). `mode=on`: add only, in full mode, never changing the mode of an existing tick (no-op if ticked). `mode=full` or `mode=upload_only`: sets that mode, ticking if needed, never unticks.
  - Ticking an inactive or unknown project: 404 "unknown project '<slug>'".
  - Every computer of the person is wired: 409 "every computer on this account is wired to the server: they work directly off the NAS and sync nothing, so projects cannot be ticked for them".
  - The named computer is wired: 409 "<m> is wired to the server: it works directly off the NAS and syncs nothing, so projects cannot be ticked for it". A person-level tick skips wired computers on its own.
  - Every non-no-op change is recorded in the history with the before and after placements, and the collector is nudged at once so sharing changes start without waiting for the next enforce cycle.
  - Answer depends on `view`: `tree` (the projects tree), `home-queue` (the sync queue; `queue_machine` keeps the window about one computer), `person-queue` (the account page's queue, which also tells every computer window on the account page to refresh), `none` (empty answer), `project` (the project detail window). Any other or none: an empty answer. Every answer tells the page's other plan windows to re-read.

## Project page (`/project/<slug>`)

(source: ui.py `page_project`, `partial_project`, `partial_bins`, `partial_missing`, `_partial_project_link_edit`, `partial_project_move*`, `_project_access_answer`, `_project_originals_answer`, `partial_project_roots*`; project.html; partials/project_detail.html, bins.html, missing_files.html, project_access.html, project_originals.html, project_roots.html, project_roots_browse.html)

- **Who**: any signed-in user. Unknown slug: 404 "unknown project '<slug>'". Supports `?as=` like the home page.
- **Head**: "> <project name>", the project's server path, "folder id <slug>" (tip: the name Syncthing uses for the shared folder), **Sync status** link back to `/` (keeping `?as=`).
- **Left column**: the same ticking_for and projects windows as the home page, with this project highlighted and its group opened.
- **The detail area** re-reads every 10 seconds while visible and after any tick on the page (`GET /partials/project/<slug>`, signed-in). Every button in it answers into the same area.

### Warnings at the top of the detail area

- Project folder gone from the server: **folder removed**, "This project's folder is no longer on the server."
- Server-side Syncthing folder in error or stopped: **sync folder <state>**, "<error, or 'this folder is not syncing on the server'>. The completion figures below are stale until this is fixed."
- Server file count failing: **server count not updated**, "<error>. The server figures below are the last good ones, from before this started. checked <ago>".
- Each held sharing change (enforce note): "Sharing change held: <note> (<ago>)".

### sync_plan window

- Bar meta "N editor(s)".
- **selected by**: every editor with the project ticked on at least one computer, each with **upload only** or **upload only on one computer** (mixed modes) tags linking to the glossary; "nobody, so it is not syncing to any editor" if none.
- **state**: **needs attention** (red), **catching up** (amber), **in sync** (green), or **not synced anywhere**.
- Buttons for the viewer (or the `?as=` person), with "acting as <name>: these keys change their sync plan, not yours." when acting for someone else:
  - Main key: **Tick for me** / **Tick for <name>**; or **Tick for all of my/<name>'s computers (N)** when not ticked and they have several computers; or **Untick for me/<name>** when ticked. It sends `mode=on` or `mode=off`. Untick confirm names every computer ("This removes <project> from <name>'s N computer(s) (<list>). Their copies stay on disk; nothing new comes down and proxy sync stops for it."). Tick confirm, when a capacity warning exists: "<warning> Sync it there anyway?"
  - When the person's tick is upload only: **Switch to full sync** (tip "Download this project's proxies and shared files as well: the normal sync."), confirm "This syncs <project> in full on every one of <name>'s N computers (<list>), including any that do not have it ticked yet: its proxies and shared files come down on each. [capacity warning] Switch to full sync?"
  - Otherwise: **Upload only for me/<name>** (when not ticked) or **Switch to upload only** (when ticked, with confirm "This sets <project> to upload only on every one of <list>: nothing more comes down on any of them, and a computer that has a full sync of it now stops downloading. Their copies stay on disk. Switch to upload only?"). Tip: "For footage you already have on this computer: send the video originals to the server and download nothing (no proxies, no shared project files)."
  - When not ticked and the person has several computers: "or one computer at a time:" with one button per computer that ticks it on that computer only.

### computers window (per project)

- Bar meta "N computer(s) share it", link **what the words mean**.
- Table per computer: status light; editor display name with **wired** (report-only base computer) and **unmapped** ("This computer's sync identity is not named after an editor. Approve it on Settings, then Users.") tags and "online"/"offline"; synced percent with meter (proxies and shared project files only); has "N / M files"; missing "N files, <size>"; media "N/M orig, N/M proxy" (against the server's counts); lane tags "<lane>: <state>" ("no reports" if none); last seen (the report time for wired or connected computers, otherwise the last connection time). Wired computers show "-" for synced, has and missing.
- **Missing files** button (when files are missing and the computer has a Syncthing device) opens an inline list under the row that survives the 10-second refresh: `GET /partials/project/<slug>/missing/<device_id>` (signed-in; 404 "device not in project: <id>" when the device is not in the project or belongs to a person this viewer may not see). Shows "missing on <name>, refreshed <ago>", each file and its size, "and N more (the list stops at M)" when cut short, or "Nothing listed yet. The collector refreshes these lists every minute for computers that are behind."
- No computers: "No editor computer shares this folder yet. Approve the computer on Settings, then Users: sharing follows by itself on the next cycle."

### shared_folders window (shown when the project has links, or when signed in)

- Bar meta "N in, N out".
- **shares from**: each folder shared into this project from another, with **ok** or its status tag (red), the subfolder, "from <lender project>" link, detail text, and **Unshare** (`POST /partials/project/<slug>/links/remove`; "nothing on disk is deleted").
- **shared into**: each subfolder of this project shared into another project, with a link to it.
- Form: a path box ("a folder from another project, e.g. 2026/Show/Episode/Interviews/...") and **Share a folder into this project** (`POST /partials/project/<slug>/links`). Empty path: "type or paste the folder to share (e.g. 2026/FF5/Elections/Interviewees/...)". Other refusals come from the API's link rules (not in this part) and appear as a red banner.

### move_files window (admins only)

- Bar meta "N move(s)".
- Form: **move** (a file or folder in this project, e.g. "B-roll/A001_0512.braw"), **to project** (drop-down of every active project, this one selected), **into folder** (blank for the project root), **Move on the server and on every computer**. Browser confirm: "Move '<path>' from <project> to <dest>[/<folder>] on the server, and tell N computer(s) to move their copy and relink Resolve? Proxies move with it. You can put it back with Undo while every computer has either applied it or is still waiting for it." No confirm when the path is empty.
  - `POST /partials/project/<slug>/move` (who may move is decided by the API, not in this part). Empty path: "type the file or folder to move, e.g. B-roll/A001_0512.braw".
  - Success: **moved**, "<from> is now <to> on the server (N proxy file(s) with it); N computer(s) told to follow."
  - Partial success: **moved, some proxies stayed**, "<from> is now <to> on the server, but these proxy files did not move: <list>. Move them by hand or run the move again once whatever is holding them has let go."
- **moves awaiting computers**: every computer that has not applied a finished move: **not applied: this computer may upload the old path again** (expired; with **Ask that computer again**, `POST /partials/project/<slug>/moves/<id>/reissue`, refusal "that computer has already answered this move"), **waiting N days** (2 days or more), or **waiting**; editor, computer, the path, "asked <ago>", ", this computer is still trying (N attempts)", last error.
- **moves**: each move with one state tag: **unfinished on the server** (with "This move was interrupted part-way through on the server. Nothing has been sent to any computer. Check both paths on the server; the dashboard re-checks them every cycle and finishes it by itself once only one of them exists."), **put back**, **N blocked**, **N failed**, **N not applied**, **waiting for N**, or **done**; plus **some proxies stayed** for a partial move; from and to paths, "by <who> <ago>", ", putting move N back" for an undo; any state detail; and **Undo this move** when it can be undone (`POST /partials/project/<slug>/moves/<id>/undo`, confirm "Move <to> back to <from> on the server, and tell every computer that holds it to move its copy back and relink Resolve? Proxies go back with it."). Under each move, one line per computer: "not applied, this computer may upload the old path again", "still trying here (N attempts)", "told, not done yet", "waiting for its next report", "blocked here after N attempts", "put in the trash on this computer: it does not sync the destination project", "moved[, Resolve not repointed yet]", or "failed", with detail.

### media_presence window

- Re-reads on load and every 5 seconds while visible (`GET /partials/project/<slug>/bins`, signed-in, scoped: an editor sees their own computers). Link **what the words mean**.
- Head line: "the server has N originals and N proxy files", or, before the server has ever counted the project, **counting** "the server is counting this project's files. A new project is counted within a minute or two." (never shown as zero).
- Per computer (fold-out): status light, editor, computer, mode, **proxy only** tag, "originals N/M, proxies N/M" (or "holds N originals and N proxies, server count pending"), **N offline in Resolve** tag.
  - Per Resolve bin (fold-out): bin path or "(root)", "N/M present" (amber when not all present), and each clip with a light (uploading, online, offline) and a **proxy** tag for proxy clips. "(clip list shortened)" when cut.
  - "No Resolve bin data. Open this project in Resolve on that computer to fill it in."
- Nothing reported: "No computer has reported what it holds for this project yet."

### project_access window (admins only)

- Loaded once (not polled) from `GET /partials/project/<slug>/access` (admin only; 404 for an unknown project, per the API helper).
- When the site gives every editor every project: "Every editor can open every project on this server (project access is set to shared). People you add here are remembered, and take effect if the server is switched to per-project access."
- **given access by an admin**: each person (display name), "(also ticks it)", and **Remove** (confirm "Remove <name>'s access to this project? Nothing on disk is deleted."). Empty: "Nobody yet. People who tick this project get in by the tick."
- **in by their tick**: everyone who ticks it.
- Form: **person** drop-down (every known editor not already granted) and **Give access**. `POST /partials/project/<slug>/access` (admin only; sign-in errors are real 401/403s). "choose a person first" when none chosen. Results: **access given** "<name> can now open this project. The server applies it within a minute." / **access removed** "<name> no longer has access through this list. Someone who ticks the project still gets in by the tick."

### originals_on_request window (signed-in)

- Loaded once and redrawn only by its own buttons: `GET /partials/project/<slug>/originals[?target=<editor>::<machine>&dir=<folder>]` (signed-in, 401 "sign in first"; 404 for an inactive or unknown project).
- Explanation: "Camera originals brought down to one computer, beside its proxies. A folder also brings what is uploaded into it later. Stopping keeps the files already down."
- **Every pick for this project is listed for every viewer**: person, computer, **folder**/**file** tag and path (who chose it, from Resolve or the dashboard, and when, in the tooltip), size on the server, and "on that computer": "cannot tell" (the computer withholds its file list, or has not reported this project), "nothing on the server yet", or "[at least ]N of M in" ("at least" when the computer's list was capped). **Stop** only for picks the viewer may change (their own computers, or any for an admin), confirm "Stop bringing <path> to <computer>? The files already there stay."
- Empty: "No originals chosen for this project. Proxies come down as usual."
- **bring originals to a computer**: a **computer** drop-down of computers with this project ticked in full mode that the viewer may manage; a computer whose companion is older than the required minimum version is listed but disabled ("- needs companion <min>"), with a line "<computer> runs companion <v> / has not said which companion it runs: it ignores originals picks until it is updated to <min> or later." **Browse originals** opens the browser.
  - No eligible computers: "None of the/your computers has this project ticked for full sync, so there is nowhere to bring originals to."
  - Refusals when browsing: "You cannot choose originals for that computer here: it does not have this project ticked for full sync, or it is not one of yours." and "<computer> runs companion <v>, and only <min> or later brings originals down: an older one ignores the picks. Update it first."
- **The browser**: "Originals of <project>[/<folder>] on the server, for <computer>.", **Up a folder**, then a table of subfolders (click to open; file count and size under it; **Bring this folder** with confirm "Bring the N originals in <folder> (<size>) to <computer>, and anything uploaded into it later?") and files (size; **Bring this file**), **chosen** where already picked. Lists come from the server's last walk of the project. At most 400 files are listed per folder, then "and N more files here. Bring the folder to get them all." Before the first walk: "The server is still counting this project's files. They appear here within a minute or two: press Browse originals again." Otherwise empty: "The server has no originals here yet."
  - When the Footage Sorter is mounted: each file also shows a 96 by 54 thumbnail made from its proxy, which opens the proxy playing in a new tab; with no proxy the picture is replaced by "no proxy yet".
- `POST /partials/project/<slug>/originals` (`action` add or remove, `editor`, `machine`, `rel`, `is_dir`, `dir`): only for the viewer's own computers unless admin (403 "you can only choose originals for your own computers (admins excepted)"). Missing fields: "choose a computer and a file or folder first". Over-long path: "that path is too long to be a file in this project". Other refusals from the API appear as a banner. Results: **asked for** "<path> comes down to <computer> on its next pass. Everything chosen there for this project is <size>." / **stopped** "<path> no longer comes down to <computer>. Files already there stay."

### project_roots window (signed-in)

- Which Resolve project files into which tree folder when the companion's "Fix all" runs. "Resolve project, then where "Fix all" puts its files. The first match is kept; only admins change these." Re-reads every 30 seconds while visible (`GET /partials/project-roots`, signed-in); paused while a folder picker is open (per a comment; the pause is in a script outside this part).
- Table: Resolve project, files into (folder), source ("admin (<who>)" or how it was matched). Resolve projects seen but not mapped: **no match**, "seen, not mapped".
- Admins only:
  - A drop-down of active projects plus "remove (match again)" (or "pick a project") and **Set** (`POST /partials/project-roots`): sets the mapping to a project, or removes it so it is matched again.
  - **Browse**: a folder picker of the whole Projects tree (`GET /partials/project-roots/browse?resolve_project=&rel=`, admin only, 403/401 "admins only: destination roots are fixed once set"). Breadcrumb buttons from **Projects**; **Files go into Projects/<folder>** for the folder you are in; each subfolder with **project** and **same name** tags and **Pick**. "no folders here" when empty.
  - `POST /partials/project-roots` refusals: not admin 403/401 "admins only: destination roots are fixed once set"; no Resolve project named 422 "resolve_project required"; a picked folder outside the Projects tree 422 (message from the API); a folder that is not there 404 "no such folder under Projects/: '<rel>'"; an unknown project 404 "unknown project '<slug>'". A picked folder that is a registered project is stored as that project. Any folder under Projects works even if it is not a registered project.
- Empty: "Nothing yet. These appear when a companion reports an open Resolve project."

## Project setup page (`/project-setup?resolve_project=<name>`)

(source: ui.py `page_project_setup`, `_setup_context`, `_browse_context`, `partial_project_setup_*`; project_setup.html; partials/project_setup_panel.html)

- **Who**: any signed-in user (it is where the companion's NEW PROJECT flow sends an editor; that link is outside this part). With no Resolve project name: redirect to `/`.
- **Head**: "> PROJECT SETUP", "Resolve project: <name>".
- **One window, "project setup"**, whose body is replaced by every browse, link and create:
  - **Already set up** (the Resolve project already has a mapping, matched case-insensitively): resolve project, "files into <folder> (<source>-set by <who>)", and "Mappings are fixed once set. As an admin you can change it in the project roots window on the project's page." (admin) or "Ask your admin if this looks wrong." (editor).
  - **Cannot show folders** (the Projects tree is not mounted in the dashboard): "The server's Projects tree is not mounted on this dashboard, so it cannot show you the folders. Ask whoever installed this server: it is a container setting, not something this page can change."
  - **Pick the folder for this project**: "Browse the server's Projects tree. If the project's folder is already there, pick it with Use this folder. Nothing inside it is changed. Only create a new folder when there is not one yet; new folders get the standard subfolders (<the site's template folder list>)."
    - Breadcrumbs starting at **Projects**.
    - "You are in Projects/<folder>" with **Use this folder** when the current folder may be picked (it is not inside a different project); otherwise "Open a year, then a show, to find the folder." (at the top) or "You are inside a project: go up a level to pick a folder."
    - Folder list (hidden folders skipped, sorted case-insensitively): **same name** tag when the folder's name matches the Resolve project; **project** tag for folders that are already projects (these do not open, since projects cannot nest); other folders open on click; each row has **Use this folder** or **Link this project**. "empty folder" when none. One unreadable folder does not hide the others. A listing error shows as **not shown** with the message ("could not list the folder: ...").
    - Inside a project: "This folder is already a project. Use Use this folder above to point "<name>" at it." or "You are inside an existing project, and projects cannot nest. Go up to pick or create."
    - Otherwise **or create a new project folder here** (in Projects/<folder>): "Only for a folder that does not exist yet. A name that is already listed above would nest a second folder inside it, so pick it with Use this folder instead.", a name box and **Create & link**. Note: "Anyone signed in can create a project, and it appears for everyone: in the tick lists, on SYNC PLANS and in the queue. Who made it is recorded in HISTORY. Only an admin can take one back off those lists, with Archive on SYNC PLANS, and even that keeps the folder and the files."
  - **Done**: **ok**, "Projects/<folder> is set up on the server[ and "<name>" now files into it].", "Sync (its Syncthing folder) is set up automatically within about 5 minutes. You can close this page."
  - **Not done** (red): the error, and when the typed name already exists as a folder, a **Use Projects/<folder>** button that links that folder instead.
- **`GET /partials/project-setup/browse?rel=&resolve_project=`** (signed-in, 401 "not signed in").
- **`POST /partials/project-setup/link`** (`resolve_project`, `rel`): "not signed in"; "pick a folder to link"; a Resolve project that is already mapped can only be re-pointed by an admin ("this Resolve project is already mapped: ask an admin to change it"). Claims the folder as a project (writes a marker and a project row) and maps the Resolve project. Other refusals from the API appear as the error.
- **`POST /partials/project-setup/create`** (`resolve_project`, `parent_rel`, `name`): "not signed in"; a folder of that name exists (offers it, see above); other refusals from the API. Creates the folder with the template subfolders, maps it, and records "project.create" in the history with who did it.

## Transfers page (`/transfers`)

(source: ui.py `page_transfers`, `partial_transfers`, `safe_to_close`; transfers.html; partials/transfers.html)

- **Who**: any signed-in user. An editor sees "your files, on every computer you use"; an admin sees "every editor". Shows the Settings strip (editors see only transfers and help in it).
- Re-read every 2 seconds while the tab is visible (`GET /partials/transfers`, signed-in, scoped the same way). Only the inner lists are replaced, so folds, open rows and scroll positions survive.
- **Safe-to-close note** (editors only; see the home page for the sentences): green **safe** ("Safe: nothing of yours is going up, so you can shut down or unplug.") or amber **not yet** ("Not yet: closing or unplugging now would leave footage on one disk. Leave it running until this says safe.").
- **live window**: meta "N moving · <total fleet speed>/s total". Table: (admin) editor and computer, direction arrow (up: "from the computer to the server"; down: "from the server to the computer"), file name (with a **folder sync** tag for a whole-project Syncthing row: "The sync engine reports the whole project here, not single files."), progress meter and percent, speed, time left. Empty: "Nothing is transferring right now."
- **queued window**: meta "N file(s) · <size> waiting", or "not counted yet" when rows exist but none could be counted.
  - Lead: "N file(s) waiting behind the transfers above, from the last disk lists the computers reported. May lag a few minutes." / "Nothing counted yet, but the rows below are not finished: see each one." / "Everything that should be somewhere is there."
  - One fold-out per (person, computer, project, lane): (admin) editor, computer, project name, then one of:
    - **getting ready** ("Getting ready: the project was just ticked, and the computer and server are setting it up. Nothing needs doing."), with "Just ticked as upload only. Waiting for this computer's first file list, then its video originals start uploading (nothing is downloaded)." or "Just ticked. Sharing and first file lists are being set up; syncing starts within a minute or two."
    - An upload row whose count is unknown: **cannot tell** ("The dashboard cannot tell whether this computer still owes uploads."), "This computer's file list was capped: it holds more video originals than it can list to the dashboard, so the dashboard cannot tell whether it still owes uploads. Leave it running and check its tray." (the last sentence only when not on hold).
    - Otherwise: direction arrow, "N file(s) · <size>", a kind tag (**upload**, **proxy download** or **folder sync**, each explained).
    - **on hold** (red) with the reason sentence and "(since <ago>)" when something on the computer is holding the transfer.
  - Inside: each file name and size; "... and N more" when the list was cut; "This computer has more video originals than it can list to the dashboard, so the upload count may be low." (uploads, capped); "This computer's proxy list was capped, so the count is worked out from its totals and no file names are shown." (downloads, capped, no names); "no file names reported".
- **history window** ("kept 7 days"): "Recently completed files: what the companions report, plus files arriving at the server." Each: (admin) editor, direction, file, completed ago. Empty: "Nothing completed recently."

## Settings, Users (`/admin/users`)

(source: ui.py `page_admin_users` and every `/partials/admin/users/*`, `/partials/admin/sessions*`, `/partials/admin/report-tokens*`, `/partials/admin/fleet-halt`, `/partials/admin/machines/forget`; admin_users.html; partials/admin_users.html, admin_suspend_button.html, minted_secret.html, admin_sessions.html, admin_report_tokens.html, fleet_halt.html)

- **Who**: admins only. Every page and partial in this section answers 403 "admins only" to a signed-in editor and 401 "admins only" to an anonymous request.
- **Head**: "> USERS", "Create editor accounts, approve new computers and keys, set known passwords." Quick links **stop syncing everywhere** (jumps to the stop window) and **create an account** (jumps to the create form).
- **One-time secret box** at the top (never folded, never refreshed away): shows a newly generated password or report token: "new password/token for <name>", "shown once", the value, a **copy** button (label changes to "copied"), "Copy it now. It is shown once, and the panels on this page refresh by themselves."
  - Password: "Give it to <name> and have them change it after they sign in. Nothing here can show it again: the next one has to be a new password."
  - Token: "Send it to whoever set up <name>'s computer: it goes into the companion's own settings file, and the companion has to be restarted (tray, then Restart CCSync) before it takes effect. It outranks the shared token and survives every tray sign-in."
- **The users area** re-reads every 30 seconds while visible (`GET /partials/admin/users`). Every form in it answers with the whole area, with a red error line or a green notice at its top.
- **Data-subject buttons** on every person row (local accounts, NAS accounts, editors without an account):
  - **export data**: a plain form to `POST /api/v1/admin/users/<name>/export` (route outside this part) that downloads one JSON file with everything the dashboard holds about the person (computers' records, history, sessions, requests, audit entries; passwords and keys left out); the download is audited (per the tooltip).
  - **erase history**: `POST /partials/admin/users/erase-history` (route outside this part), confirm "Erase the history of <name>? Their account and what their computers report now stay." Tooltip: removes past sync and transfer history, completion and missing-file records, stored diagnostics, expired sessions, past failed sign-ins and finished YouTube requests.

### When the dashboard keeps its own accounts (`auth_method = local`)

- **local_accounts window** ("N accounts" or "none yet"): username; **shown as** (a display-name box, up to 64 characters, placeholder the username, **save**, posts to `/partials/admin/users/display-name`, outside this part; clearing it shows the sign-in name again); role; status (**disabled**, **active**, **suspended**); ssh keys (fingerprint and label, each with **revoke** and confirm "Revoke this SSH key for <name>? Their SFTP stops now."; "none"; and an **add** box for a new key); **set** password (confirm "Set a new password for <name>? Their old one stops working now."); **disable** / **enable**; **suspend** / **resume**; export data; erase history; **delete**.
  - Disable confirm: "Stop <name> signing in? Their computers keep their projects until you untick them." Tooltip: a disabled account cannot sign into the dashboard or SFTP, its sessions and report tokens are revoked, and its computers are turned away when they report; enable undoes it.
  - Delete confirm: "Delete <name>, their computers and their sync plans? "Disable" only stops logins."
  - Empty: "No local accounts yet."
- **create_local_account window**: username, role (editor or admin), optional SSH public key, optional password ("Blank generates a one-time password that is shown once, at the top of this page."), **create** (shows "creating the account..." while waiting).

### When accounts live on the NAS (any other `auth_method`)

- If no NAS password is configured: "This dashboard has no NAS password, so editor accounts cannot be created here. Set it on Settings, Setup (Connect to your NAS), or set DASH_NAS_PW in the container." (with a link to `/setup#nas_connect`). The device and account windows are then not shown.
- If the NAS or Syncthing could not be reached: a red note with the error, then whatever half answered.
- **devices_awaiting_approval window** (meta "N waiting", "none pending" or "unavailable" while Syncthing is not answering, never "none" then):
  - Each Syncthing device asking to join: device id, status (**pending**, or **unmapped** for one that joined under a name that is not a person), computer name, and an owner form: a username box (suggesting known editors; pre-filled with what the companion reported, marked **reported**), a **create new editor** checkbox, **approve**.
  - Foot: "Pick the person who owns this computer, never the computer's own name. One editor can own several computers, so a second computer takes the SAME username as their first. A row marked reported was filled in from what that computer's companion already told the dashboard."
  - Empty: "No device is waiting. A new computer appears here when its Syncthing asks to join."
  - `POST /partials/admin/users/approve`: refusals "SYNCTHING_GUI_URL is not configured", "username must be a valid TrueNAS-style username", a malformed device id (shape-checked and upper-cased first; message from the API), an unknown username without **create new editor** (message from the API), and any Syncthing error. On success the person is recorded as a known editor.
- **editor_accounts window** ("N on the NAS"; "The account list is unavailable: <error>" when the NAS does not answer):
  - Username; **shown as** box and **save** (as above); uid; ssh key (**set** or **no ssh key** with "upload and proxy download will not run until a key is added", plus a key box with **add ssh key** / **update ssh key**; replacing confirm "Replace <name>'s SSH key? Their upload and proxy download stop until it is in use."); smb **on**/**off**; locked (**locked**, **suspended**, or "-"); **set** password (confirm "Set a new password for <name>? It is their NAS login too."; tooltip: the dashboard, SMB and SFTP all stop working with the old one); suspend/resume; export data; erase history; **delete** (confirm "Delete <name>: their NAS account, their computers and their sync plans?").
  - Empty: "No editor accounts yet."
- **create_new_editor_account window**: username, optional full name, optional SSH public key ("Leave this blank if they have not installed yet: their installer sends the key up on first sign-in and you approve it on this page. Upload and proxy download do not run until a key is on the account."), optional known password ("otherwise randomized and unusable for dashboard login"), **create** (shows "creating the account on the NAS..."), "This can take up to two minutes: the NAS creates the account, its group and its home directory. Leave the page open."

### Create, password, disable, suspend, delete: what the server does

- **`POST /partials/admin/users/create`** (also used by the "add/update ssh key" box on an existing NAS account):
  - Local accounts: creates the account with the chosen role; a blank password generates a random one (15 random bytes, URL-safe) shown once in the secret box; an SSH key, if given, is added. Errors come from the local account store. The person is recorded as a known editor.
  - NAS accounts, refusals in order: no NAS password ("This dashboard has no NAS password, so editor accounts cannot be created here. Set it on Settings, Setup (Connect to your NAS), or set DASH_NAS_PW in the container."); bad username ("username must start with a letter and contain only lowercase letters, digits, '.', '_', '-'"); text that is not an SSH public key ("does not look like an OpenSSH public key"); a blank key for an EXISTING account (refused, because it would erase the key in use; message from the API); a password that is too short (message from the password rule). Then the account is created or updated on the NAS (can take about two minutes), the password set if given, and the person recorded as a known editor. If a password was set on an existing account, all of that person's browser sessions are signed out: "Password set for <name>, and signed out N session(s) of theirs." NAS warnings: "<name>: created with warnings (<list>)".
- **`POST /partials/admin/users/password`**:
  - Local: "password required"; store errors; on success the reset is written to the history and every session of that person is signed out. Notice: "Password set for <name>. Tell them the new password: it is not shown here again." or "Password set for <name>, and signed out N session(s) of theirs. Tell them the new password: it is not shown here again."
  - NAS: "DASH_NAS_PW is not configured on the dashboard"; bad username (same wording as create); "password required"; too short (minimum length applies to new passwords only; existing short ones keep working); NAS errors. Same history entry and sign-out as local.
- **`POST /partials/admin/users/disable`** (`disabled` 1 or 0): only with local accounts ("this action is only available with DASH_AUTH_METHOD=local"). Refusals from the account store (for example the last enabled admin, or yourself). Disabling also revokes that person's sessions and report tokens ("account disabled").
- **`POST /partials/admin/users/suspend`** (`suspended` 1 or 0, optional `reason` up to 255 characters): works for any account type. Suspend confirm: "Pause syncing for <name>? Their sync plan is kept and "Resume" puts it back."
  - Refusals: "not a valid username"; "you cannot suspend the account you are signed in as - sign in as another admin to suspend this one"; "<name> is not an editor this dashboard knows".
  - Suspend notice: "<name> is suspended. Their computers are being turned away and their projects will be unshared within a minute. The sync plan is untouched: RESUME puts it all back." Resume notice: "<name> is back. Their projects are shared again on the next cycle, exactly as they were." Both are recorded in the history.
- **`POST /partials/admin/users/delete`**: deletes the person everywhere (account, keys, sessions, report tokens, all their computers' plans, status rows and Syncthing devices; files on their computers stay). Refusals and failures from the shared delete rule appear as the error; partial success: "deleted <name>: <warnings>".
- **`POST /partials/admin/users/keys/add`** and **`/keys/remove`**: local accounts only ("this action is only available with DASH_AUTH_METHOD=local"). Remove takes effect at once.

### ssh_keys_awaiting_approval window (only when an editor's installer has offered a key)

- "Sent up by an editor's installer. Their upload and proxy download cannot authenticate until one is approved." Each: editor, fingerprint (full key in tooltip), the computer it came from, when sent, **approve** and **dismiss**.
- **`POST /partials/admin/users/keys/approve`**: installs the key on the account (refusals from the shared rule); notice "SSH key added for <name>. Their upload and proxy download can authenticate now."
- **`POST /partials/admin/users/keys/dismiss`**: confirm "Throw away this key for <name>? Their computer can offer it again." Removes the offer only and records it in the history.

### computers window

- "Every computer that has reported in. Remove forgets it: its sync plan, its status rows and its Syncthing device." Table: editor, computer (Syncthing device id in tooltip), platform, mode (editor or base), running version, plan ("N project(s)"), last report, **remove**.
- **remove** confirm: "Forget <computer>? It stops receiving projects. A running companion re-registers." (`POST /partials/admin/machines/forget`; refusals from the shared rule appear as the error). Tooltip: uninstall the companion first, or delete the user, if it should stay gone.
- Empty: "No computer has reported in yet."

### editors_without_an_account window (only when there are any)

- "Known to the fleet (a device, a plan or a report), but no account here." Each name with **delete** (confirm "Delete <name> from the fleet, with their computers and sync plans?") and the export / erase buttons.

### signed_in_browsers window

- Loads on page load and every 30 seconds (`GET /partials/admin/sessions`). "Revoking signs that account out everywhere within a second. The companion's own identity token is separate and is not affected."
- Table of every live browser session: username ("(you)" for yourself), signed in, last seen, from (address and browser), and **revoke all** (confirm "Sign <name> out of every browser? They will need to sign in again. Their computer's own sync is not affected.") or, on your own rows, **sign me out everywhere** (confirm "Sign yourself out of every browser, including this one? You will need to sign in again to finish what you are doing.").
- Empty: "Nobody is signed in through a browser right now."
- **`POST /partials/admin/sessions/revoke`**: "username required"; "sessions are not being recorded on this deployment"; otherwise "revoked N session(s) for <name>" (shown in the error slot).

### report_tokens window

- Loads on page load and every 60 seconds (`GET /partials/admin/report-tokens`). "One credential per editor, revocable on its own. It replaces the single shared fleet token every companion used to hold."
- If some computers still report with the shared fleet token: "N computer(s) still report with the SHARED fleet token: <names>. Once this is empty, ask whoever installed this server to switch the shared token off: it is a container setting, not something this page can change." Otherwise, when every reporting computer uses its own token: "All N reporting computer(s) use per-editor tokens. The shared token is no longer used by anything: it is safe for whoever installed this server to switch it off."
- Table: editor, label, created, last used, **revoke** (confirm "Revoke <name>'s report token? Their companion stops reporting and stops syncing until you issue a new token and they enter it. The old token cannot be shown again."; refusal "that token was already revoked (or never existed)"). Empty: "no per-editor tokens yet".
- **mint a token**: editor username, optional label, **mint** (`POST /partials/admin/report-tokens/create`; bad username refused with the standard wording). The token appears once in the secret box at the top of the page.

### stop_syncing_everywhere window (the fleet stop)

- Loads on page load and every 60 seconds (`GET /partials/admin/fleet-halt`). "Stops uploads, proxy downloads and shared project files on every editor's computer. Nothing is deleted; it is fully reversible. A computer that is off right now takes the stop the moment it reports again."
- **When stopped**: "Syncing is stopped on every computer", the reason, "set by <who> <ago> (N hours so far, N computers in the fleet)", "releases itself <in ...> unless you keep it stopped (kept on N times)". "Each companion picks this up on its next report (within a minute) and shows the reason in its tray. Editors cannot start syncing again themselves; only this button can." Buttons **start syncing again** and **keep it stopped** (confirm "Keep every computer in the fleet stopped for another day? Nobody's uploads, proxy downloads or shared project files move until you start them again here."). Keeping it on moves only the expiry, one day from now, and keeps the original reason and start time.
- **When not stopped**: a reason box ("why (shown in every editor's tray)") and **stop all syncing**, confirm "Stop syncing on EVERY computer in the fleet? Uploads, proxy downloads and shared project files stop everywhere until you start them again here. Nothing is deleted. Work done while it is stopped will not reach anyone until you start them again." The stop releases itself after a day (24 hours, per the tooltips).
- **After an expired stop**: "The last stop EXPIRED and syncing started again everywhere <ago>. It was set by <who> <ago>: <reason>." and **ok, it can stay off**, which takes the notice down everywhere without changing any computer.
- **`POST /partials/admin/fleet-halt`** refusals: a reason under 3 characters when starting a stop: "say why: every editor's tray will show this"; **ok, it can stay off** pressed after someone set a NEW stop: "a new stop was set since this page loaded, so nothing was changed. Use "Start syncing again" if you mean to end it."; a stale **keep it stopped** after the stop already expired, and other store refusals: the store's message.
- **previous stops** fold-out: when, what (**stopped**, **kept on**, or other), who, why.

## Settings, Sync plans (`/admin/assignments`)

(source: admin_assignments.html; ui.py `partial_admin_archive_project`. The page route is in assignments.py and the checkbox behaviour in static/cc/assignments.js, both outside this part: what follows is what the template draws.)

- **Who**: admins (the Settings strip lists it as admin-only; the route's own gate is outside this part).
- **Head**: "> SYNC PLANS", "N person/people · N computer(s) · N project(s)".
- **Lead text**: explains that a plan belongs to a computer, not a person; that "every computer" shows them side by side; that every box is the same write as the Sync status checkboxes ("there is one list, not two"); and that the small **up** box beside a tick makes it upload only. Links to the glossary entry "Upload only" and the glossary.
- **whose_plan window** (meta "the choice is in the address, so a link lands here too"): a plain form with **person** ("choose a person..." plus every known person) and **computer** ("choose a computer...", "every computer" when the person has more than one, then each computer; disabled until a person is chosen; the computer list is filled in the browser from a person-to-computers map in the page), and **show**. Nothing is listed until both are chosen.
- **plan window** (meta "N projects x N computer(s)", or "nobody chosen"):
  - No known editors: "No known editors yet: one appears here once they sign in, tick a project of their own, or their companion reports."
  - Not chosen yet: "Choose a person above, then one of their computers, then show. Nothing is listed until then: a company with many editors has a grid too wide to read, and a plan belongs to one computer anyway."
  - Person has no computer: "This person has no computer to show a plan for yet." No projects: "No active projects yet."
  - A **filter projects** box ("Filtering unticks nothing").
  - **Grid**: one column per computer, one row per active project.
    - Column head: computer name with a presence light for the person, the person's name, "<size> free" (last reported free space on the sync drive), and either "wired: set on that computer" for a wired computer (with explanation) or the column tools: **all** (tick every project; "Asks first if the proxies would not fit. Press again while it runs to stop after the change in flight."), **none** (untick every project), and when the person has other computers a **copy from...** drop-down ("Give this computer the same projects as another of <person>'s. Asks first, and names anything it would stop syncing.").
    - Row head: project name; proxy size on the server ("not measured" when unknown, meaning a tick cannot warn about space); **archive** button with browser confirm "Archive <project>? N editor(s) sync it now, and it stops being sent to their computers. Nothing is deleted: the folder and the files stay on the server, and UNARCHIVE puts it back."
    - Each cell: a tick checkbox ("sync "<project>" to <computer>") and a small **up** (upload only) checkbox. On a wired column an unticked cell is disabled ("...is wired to the NAS: it works directly off the tree, so a new sync cannot be ticked here. Change it on that computer: tray, Settings, This computer.") and a ticked one stays untickable ("...syncs nothing: untick to clear this stale sync."); the up box is disabled on wired columns.
    - Legend: ticked = "synced: the project comes down and goes up"; up = "upload only: originals go up, nothing comes down"; empty = "not on this computer".
  - Results of the cell writes appear in a live message area below the grid (filled by the script).
- If the archived list cannot be read: "The archived list could not be read right now, so it is not shown. Nothing was archived or restored by this, and the projects above are unaffected."
- **archived_projects window** (when any): "Off every tick list and the queue. Nothing was deleted: the folders and the files are still on the server." Each: project, "archived <ago> by <who>, still ticked for N editor(s)", **unarchive** ("The ticks it had are still there, so it starts syncing again on the next cycle.").
- **`POST /partials/admin/projects/archive`** (admin only; plain form with the CSRF field): `archived=1` archives (records "project.archive" in the history with the editors who tick it), `archived=0` unarchives (records "project.unarchive"). Nothing is deleted; shares are removed on the next enforce cycle. Then redirects (303) back to `/admin/assignments` with the same person and computer chosen. An empty slug does nothing but redirect.

## Settings, Site (`/admin/settings`)

(source: ui.py `page_admin_settings`, `_live_auto_derived_values`, `_auto_derived_env_hints`, `partial_admin_enforce_allowance`; admin_settings.html; partials/android_settings.html. The save, import, undo, AI provider and Android routes, and the tab script static/cc/site_settings.js, are outside this part.)

- **Who**: admins only (403/401 "admins only").
- **Head**: "> SITE SETTINGS", "Who this deployment is: names, tree, NAS and sync settings every editor's companion reads. Changes apply on save, no redeploy needed."
- **Six tabs** (display only; switching tabs is done by the page script): **studio and tree**, **features**, **ai providers**, **export and history**, **sharing safety**, **android**. Only the first two share one form and one Save.
- **Each text field** shows its label (with a plain-words tooltip on jargon labels such as SMB UNC, SFTP, Rclone, Syncthing), the stored value, and a hint. Special cases:
  - **Locked / auto-derived**: the box is read-only and labelled "auto-derived: <where it comes from>" only when a live value is available right now:
    - Dashboard URL: when the bundled Tailscale helper reports it is running and signed in with a name ("the bundled Tailscale sidecar is signed in as <name>").
    - NAS Syncthing ID: when this site's Syncthing answers its status call within 2 seconds ("this site's Syncthing reports device id <first 7 characters>...").
    - SFTP host: never (no live source exists).
    - Tree name, Drive letter and Remote root: labelled "locked" and read-only once any computer has registered ("read-only now that computers have registered; every installer and companion builds its paths from it").
  - **Environment hint**: when a deployment environment variable `DASH_SITE_<KEY>` holds a different value from the saved one, a line "env DASH_SITE_<KEY>=<value> (not applied: the value above is what is live; edit it, or import a site.toml, to change it)". Never applied automatically.
  - **Support contact** shows the raw stored value (blank when unset) with the vendor default as a grey placeholder.
  - Dashboard URL also carries a warning: "This must be exactly the address editors type in their browser, or Send to Resolve stops working."
- **studio and tree tab**:
  - **your_studio** ("header, login page, every tray"): Org name, Short name, Support contact, Product name, Tray logo (a bare file name picks a mark the companion ships; anything with a slash is a path on the editor's computer; must be white on transparent).
  - **the_tree** ("server and every editor's disk"): Tree name, Drive letter, Remote root, SMB UNC, Dashboard URL.
  - **how_editors_connect** (marked **advanced**), folded by default: "show the seven connection fields. Set up once when the server was installed. A wrong value here stops syncing for everybody.": SFTP host, SFTP port, SFTP chunk size (hint: on a Synology server use 64Ki), SFTP concurrency, SFTP shell type, Rclone remote, NAS Syncthing ID. If the stored transfer setting is unsafe for this server: "The saved transfer setting is not safe for this server: <problem>. Editors already get the safe values shown below. Save this form to store them."
  - **nas_and_folders**: NAS kind (a drop-down of the supported kinds only), Template folders (comma-separated; the folders every new project is created with), Shared asset folders (comma-separated paths inside the tree every editor gets, such as the LUT library).
  - **Save** ("saving" while busy) with a result line.
- **features tab**:
  - **features** ("published to every companion"): YouTube downloader; YouTube anti-automation bypass; Automatic companion updates ("editors' computers take a newer published build without anyone clicking"; "A computer never goes backwards and never updates in the middle of a popup."); and, only when the build is not locked against command-line AI tools: AI CLI providers (shown, disabled, "set on AI providers, where accepting the notice turns it on") and Keep Claude Code up to date ("once a day, this server installs the publisher's newer Claude Code (checked against the publisher's checksum)").
  - **telemetry** ("what every computer reports"; only when the build has it): "Switching one off stops every computer sending it, deletes what the dashboard already holds about it for every computer, and does not affect sync. A computer can also switch these off for itself (its tray: Settings, THIS COMPUTER, PRIVACY); it cannot switch back on what the site has switched off." Four switches, each with its cost:
    - Open Resolve project name (off also stops the bin structure; no NEW PROJECT prompt; an editor cannot be first to map a Resolve project; no automatic mapping from that computer).
    - Files on each computer's disk (off: every file move in every active project is sent to that computer, and its holdings and upload progress show as not reported).
    - Resolve bin structure.
    - Time since the last keyboard or mouse input (off: that computer is not offered jobs that wait for an idle computer).
    - The page script asks before a save that switches one off (per the template comment).
  - A transport line filled by the script (how many computers report over which kind of connection).
  - **b-roll_indexing_model**: **Good** (Qwen3-VL 4B: 8 GB VRAM NVIDIA, or Apple Silicon 16 GB; about 20 s per clip on an RTX 3080) or **Best** (Qwen3-VL 8B: 12 GB VRAM, or Apple Silicon 24 GB; about 2x slower). "The indexer on your wired computer reads this choice from the dashboard; it can be overridden per computer in the indexer's config."
  - **Save**.
- **ai providers tab** (drawn by the script from the AI providers API): "Which AI answers the things on this server that ask one. When nothing is pinned, the first available provider in the order is used..." A **who_answers** window (which provider answers the YouTube downloader and others; a **prefer** drop-down, "auto: first available in the order"; "A pinned provider that is not available is a refusal, not a fallback: nothing else is used in its place."), a **your_ai_providers** list with "add new", and a "CLI tools (Claude Code, Codex):" **OFF/ON** switch ("It spends a personal subscription: read the notice under add new first.").
- **export and history tab**:
  - **export_import** (site.toml): **Export site.toml** (downloads `/api/v1/admin/site/export`; "No password or AI key is in it."), a paste box and **Import** ("Reads the pasted text, shows you every setting it would change and asks first. Nothing changes until you say yes.").
  - **change_history**: "The last few times a save or an import changed these settings. Undo puts back the values from just before the most recent one." and **Undo last change** (asks first).
  - Import and undo ask through the page's own "are you sure" dialog (**Cancel** / **Yes**).
- **sharing safety tab**: **sharing_safety** ("the stop on mass unsharing"): "The server stops and asks when one pass would take more shares away than this limit, because that is what a broken snapshot looks like. Removals an admin caused on purpose (an archived project, a suspended person, an unticked project) never count. The limit is at least the server's flat floor; set a number here to let it grow with the fleet: this many removals for every computer. 0 keeps the flat floor." Field **Removals per computer** (0 to 100) and **Save**.
  - **`POST /partials/admin/enforce/allowance`** (admin only): not a whole number in range: 422 "Enter a whole number from 0 to 100." Saved: "Saved. The flat limit applies." (0) or "Saved. Up to N share removal(s) per computer in one pass before the safety stop." The collector is nudged.
- **android tab** (`/.well-known/assetlinks.json`): "The app wrapper's proof that this site owns it. Without it the installed app opens with a browser URL bar across the top and nothing says why." Fields **Package name** (blank turns the app off and the site serves an empty statement) and **SHA-256 cert fingerprints** (one per line; 32 colon-separated hex pairs; keep the old key while handing over to a new one). **Save** posts to `/api/v1/setup/android`; **Check** posts to `/api/v1/setup/android/check` (both outside this part) and shows either **serving** "<path> carries N statement for <package> with N fingerprint(s)" with the list, or **empty** "<path> answers []. An app installed against this origin will open with a URL bar until both a package name and a fingerprint are saved above." Then either Google's checker address ("Google decides, not this page...") or "Set Dashboard URL on the studio and tree tab to this site's https address before you build the app...".

## Settings, Packages (`/admin/packages`)

(source: ui.py `page_admin_packages`, `_packages_and_feed`, `_vendor_rows`, `_kind_platform_groups`, every `/partials/admin/packages/*`, `/partials/admin/feed/*`, `/partials/admin/machines/update*`, `partial_admin_dashboard_update`; ui_packages.py; admin_packages.html; partials/admin_packages.html, admin_dashboard_update.html)

- **Who**: admins only.
- **Head**: "> PACKAGES", "The builds this server hands to the fleet, the ones the vendor offers, the computers that are behind, and this dashboard's own code."
- The packages area re-reads every 30 seconds while visible (`GET /partials/admin/packages`). Every button in it answers with the whole area. A refusal is drawn on the row that was clicked (and at the top only if that row is no longer on the page).
- **Grouping**: every list is grouped by kind (companion, dashboard, onboard, then any other alphabetically) and platform (windows, macos, linux, then others), with a group with nothing in it left out. Inside a group, newest version first (numeric comparison; a version with anything non-numeric sorts last).
- **Build tags** on a row: **+dirty, <commit>** (built from uncommitted code) or the commit id; **current**; **staged** (a companion build held here and not handed out); the processor (**arch**); **recalled** (with reason); **update the dashboard first** ("Needs dashboard <v>; this dashboard is <v>."); **file missing**; **unsigned** ("Published without a release signature: companions that check signatures will refuse this build." plus "Publish the signed build from the vendor list instead." when a vendor feed is configured, else "Republish it through tools\ship.cmd instead."); **no code sig** (record signed, program has no Authenticode or Developer ID signature).
- Each row: version, published ago and by whom, size (sha256 first 12 characters; full in tooltip).

### currently_served window ("one build per kind and platform")

- "What this server hands out right now. companion: what the fleet updates itself to. onboard: the full installer served by the Installer page."
- **Data volume line**: "Could not measure free space on <path>." when unmeasurable; red "<size> free on the data volume (<path>). Publishing is refused below a safety floor, and a full volume stops every write this dashboard makes. Old builds are pruned on publish; database backups and old code trees are pruned on each dashboard update." when under 2 GiB (2,147,483,648 bytes); otherwise "data volume: <free> free of <total> <path>".
- Each served build: "N computer(s) on it" (when known), and a **roll back to...** drop-down plus **roll back** listing only older held builds of the same kind and platform that a plain make-current would accept: not recalled, not blocked on the dashboard version, signed, file present, and for a companion either previously current or past its soak. Confirm: "Roll <kind> for <platform> back to the build you chose? Every <platform> computer on a newer build is offered it on its next report. It was current before, so there is no soak." (companion) or "It is what this server hands out from now on." (other kinds).
- Nothing served: "Nothing is being served yet: your supplier's builds are in the From the vendor window below. Press "Check now" there to fetch them." (feed configured) or "Nothing is being served yet: publish a build below, or from your wired computer with tools\ship.cmd".
- **Recalled builds still running somewhere**: "recalled <kind> <version> <platform> was withdrawn by the vendor: <reason>. N computer(s) is/are still running it." With computers on it: "roll them onto" a drop-down of non-recalled builds of that kind and platform (current preselected) and **roll the fleet back** (`POST /partials/admin/packages/roll-fleet-back`): every computer on the recalled build is asked to take the chosen one; if the dashboard is still handing out the rolled-off build, the current pointer is moved too where allowed. If that move was refused: "The computers were asked to roll back, but this dashboard is still handing out the build you rolled off: <reason>". Other refusals from the shared rule appear as the error.
- **Processor gaps**: "No <platform>/<arch> build published: N computer(s) report(s) that processor and the current build is for a different one, so they are offered nothing rather than a program that cannot run."

### rollout window ("did it reach the fleet", when there is data)

- Per platform: "N of M on <version>" with **N refusing** (each computer and reason in the tooltip), behind ("<editor> on <computer> <version>, <ago>" list, or "none"), reverts, failed attempts, current since.

### Held (non-current) build rows (in "other versions held")

- **Canary line** (companions with soak data, not recalled): "canary: N computer(s) on <v> for N min, N crashes (none since <v> started there / N computer(s) crashed since <v> started there), N rolled back (soak N min)".
  - **push to one computer**: a drop-down of computers of that platform ("<editor>/<machine> (<version>)") and the button (`POST /partials/admin/packages/push-one`): asks that one computer to take this exact build on its next report. Refusals: "pick a computer to push this build to"; "no published <platform> companion package <v>"; "no computer '<m>' for '<editor>'". Recorded in the history.
- **make current** (not on recalled builds): "Refused until one computer has run it for the soak time; the refusal says so here."
- **make current anyway** (only when the soak is not yet satisfied or the build is unsigned): type the version into the box to confirm. For an unsigned build an extra confirm: "This build has no release signature. Companions verify signatures, so making it current stops EVERY computer in the fleet from updating, silently. <instead words> Make it current anyway?"
- **`POST /partials/admin/packages/current`** (`kind`, `platform`, `version`, optional `force`, `confirm`, `row_version`): the same refusal rule as the JSON route (soak gate, signature, recall, dashboard version, file, typed confirmation; wording outside this part); "no published <platform> <kind> package <v>" if the row is gone. Success is recorded in the history with whether it was forced.
- **delete** (`POST /partials/admin/packages/delete`), confirm "Delete <kind> <v> for <platform>? It goes to the trash on this server for 30 days. After that it is gone, and putting the fleet back on it means rebuilding and republishing." Refusals: "no published <platform> <kind> package <v>"; "cannot delete the current version; make another version current first"; a failure to move the file to the trash (its message). The file goes to the packages trash folder for 30 days; recorded in the history.

### from_the_vendor window ("what your supplier publishes")

- "Nothing here reaches your fleet until it is published onto this server and made current."
- Not configured: "Not configured, so this server is not being offered new builds. Ask whoever installed this server to point it at your supplier's release channel: it is a container setting, not something this page can change."
- Configured: feed address; "last checked <ago>" (or "never"), "checks every N h" (or the shorter interval), "next in about <time>" / "next retry in about <time>" (after a failure), and **last check failed** (error in tooltip). The interval is the configured feed interval (default one day) but never below the poller's minimum.
- **policy** drop-down (asks before changing, via a script outside this part; the drop-down is put back on cancel): **manual: "Check now" and publish only**, **stage: auto-publish, not current**, **current: auto-publish and make current**. `POST /partials/admin/feed/policy`; an invalid value shows its error.
- **check now** (`POST /partials/admin/feed/check`; "DASH_RELEASE_FEED_URL is not configured"; "feed check failed: <error>"). Builds the check refused: "refused This dashboard would not take <list> from the feed. Nothing was published. Ask whoever publishes these builds: it is the release record that is being refused, not the download."
- Each vendor build with its state:
  - **current here**: "this server already hands this build to its fleet".
  - **staged, not current** (already downloaded): **make current**, and **make current anyway** (typed version) when the soak gate holds it or it is unsigned (with the unsigned confirm).
  - **same version, different bytes**: "this server holds this version from a different build; ask the vendor for a new version number".
  - **recalled**: "the vendor recalled this build; it cannot be made current".
  - Available (not on this server): **publish** (downloads it, staged) and **publish and make current** ("The soak gate still applies."). `POST /partials/admin/feed/publish` downloads in the background of the request (up to the feed's own fetch timeout); "DASH_RELEASE_FEED_URL is not configured" or the package store's refusal.
  - Notes and published time per build. A "dirty" flag sent as the text "0" is correctly read as clean.
- If the classified list is empty but the feed lists available builds: "<list> are offered by the vendor. Press "Check now" to publish them." Otherwise: "Nothing new: the fleet's packages already cover everything the vendor feed offers."
- **same version, different bytes** notes: "<kind> <v> <platform>: published here as <sha>, the vendor feed now offers <sha>. Nothing was replaced. Ask the vendor to publish it under a new version number."
- **recalled by the vendor** notes: "<kind> <v> <platform>: <reason>. It is not offered here under any policy."
- A newer container image: "Image <tag> available (running <v>). To apply it: <hint>".

### other_versions_held window ("N build(s)")

- Folded: "show the N build(s) held here. Kept so you can put the fleet back on one of them: republishing an older build is how a rollback works here, and a build pulled from the vendor feed waits here as a staged canary until somebody makes it current." Rows as described above. Empty: "Nothing held: every published build is the current one for its platform."

### out_of_date_computers window ("N behind")

- Table: editor, computer, running version (amber), **reverted from <v>** ("Do not make that build current."), **refusing <v>** (reason and when in tooltip), last report, and an update cell:
  - Already asked: **asked for <v>**; **cannot be sent** with "This computer is not being offered that build: <why>. It still takes jobs. Withdraw the push or publish a build it can take."; **kept crashing, rolled back** or **failed xN**; and **cancel** (`POST /partials/admin/machines/update/cancel`; "Withdraw the request. The computer keeps what it runs.").
  - Refusing the current build: "This computer refuses the current build: <reason>. Pushing it again will not change that."
  - Fled the current build: "Not offered to this computer: it kept crashing on <v> and rolled itself back, and it will not install that build again. A newer build is offered as usual."
  - Otherwise **update now** (`POST /partials/admin/machines/update`): asks that computer to take the current build for its platform on its next report. Refusals: "no computer '<m>' for '<editor>'"; "no current companion package is published for that computer's platform"; the fled-build refusal (wording outside this part). With `?view=none` (used by the account page) it answers empty.
- Empty: "All reporting computers are on the current version."
- Foot: with a feed: "New builds come from your supplier's release channel: the From the vendor window lists them, and "Check now" fetches any the next scheduled check has not. Each computer's tray then offers the update. (A site that builds its own companion publishes with tools\ship.cmd from its wired computer.)" Without: "Publish new builds from your wired computer with one command: tools\ship.cmd. It runs the gates, the test suites, the build, the publish and the soak-gated flip. See docs/RELEASE.md. Each computer's tray then offers the update."

### this_dashboard window ("its own code")

- Loaded once (never polled) from `GET /partials/admin/dashboard-update` (admin only); its buttons are driven by static/cc/dashboard_update.js (outside this part), which talks to the dashboard-update JSON routes (outside this part).
- If the status cannot be read: "could not read the code update state: <error>" with defaults.
- Shows: running version; code from (image, or an update applied on top); image carries; runtime id (first 12 characters).
- Notes: "Reverted automatically: <reason>"; "This dashboard did not roll itself back automatically: <reason>"; "<v> was applied here and has been retired: <reason, or 'this image carries it'>."
- Not an image-mode deployment: "This deployment updates from your wired computer, not over the air: its code is read straight off the server rather than from an installed package. Ask whoever installed this server to move it onto the update channel if you want to update from this page."
- Image mode:
  - Progress line: "working: <step>, <message>" while in progress, or **last update failed** with the error.
  - Code updates for this runtime: version, size, published, notes, **update now** ("It is offline for about ten seconds; the databases are backed up first. Asks first."). None: "No code update is available for this runtime."
  - **older bundles on the feed**: **roll back to...** drop-down and **roll back** (disabled until chosen; "Offline about ten seconds; the databases are backed up and stay as they are. Asks first.").
  - Each update that needs a new container image: **runtime update** "dashboard <v> needs a new container image: it brings dependencies this container does not have. To apply it: <hint>".
  - Installed tree: "installed tree <v>, applied <ago>", a drop-down with one option (the tree before, or "the image's own build") and **roll back** ("The databases stay as they are unless you tick the box below. Asks first.").
  - **also restore the databases from <backup>** checkbox (disabled with "no backup on record"). If the database schema is newer than what the target build knows: "This database is on schema vN and the build you would go back to knows vM. Restore the backup alongside it, or the rollback is refused. Restoring also takes today's reports back to that moment." If the target's schema is unknown: "...The rollback is allowed and the database stays where it is."
  - **database backups** (taken before each update, under /data/backups): up to 10 newest, with when, name, from version, databases, size.

## Settings, Jobs (`/admin/jobs`)

(source: ui.py `page_admin_jobs`, `_jobs_context`, `partial_admin_jobs`, `partial_admin_retry_job`, `partial_admin_cancel_job`; admin_jobs.html; partials/admin_jobs.html)

- **Who**: admins only.
- **Head**: "> FLEET JOBS", "Work the fleet does for itself: transcriptions, 480p proxies, audio extractions and waveform peaks." Lead: "A job is offered to every computer that can do it and claimed by the first one to ask, so nothing here is assigned to anybody. What this page is for is the opposite case: a queue that is not moving, and why. That answer is under each row, per computer, in words."
- The whole area re-reads every 15 seconds while visible (`GET /partials/admin/jobs[?finished=1]`); the "show finished" choice is kept in the refresh address.
- **the_queue window**: meta "N queued, N running[, N pinned here][, N abandoned in the last N h]". One box per job kind: "<label> running/cap" (marked full when at the cap: "the next one waits for a free slot"); cap is the most the whole fleet may run at once. **pin: this server** when this dashboard can run media jobs the fleet gave up on, else **no pinning here** (reason in tooltip: "A job whose retry budget runs out is abandoned..."). "The oldest has waited <time>."
- **jobs window** (open jobs, up to 100): job number, kind label with **now** (forced: every capable computer asked at once) and **for <computer>** (only that computer is offered it), state tag (**running**, **queued**, **pinned**, **claimed**, each explained) and "(cancelling)", where (person/computer or "nobody"), progress percent (or "-": unknown is not zero), age, **cancel** (confirm "Stop job #N? It is killed where it runs and not retried.").
  - Under each row: the scheduler's one-line answer why, "(N attempts: <first 120 characters of the last error>)", and one line per computer: **yes**/**no**, "<editor>/<computer>: <reason>", **sidecar failed** tag.
  - Empty: "Nothing is queued or running." plus "N job(s) were abandoned in the last N h."
  - **show finished** / **hide finished** toggle.
- **finished_in_the_last_N_hours window** (only when shown): job, kind, state (**done** green, otherwise red; **gave up** for abandoned), what ("<root>:<path>", "(retry of #N)"), last held by, when, why it ended (full last error and attempts), **try again** for failed or abandoned jobs (confirm "Queue job #N again? It goes back on as a new job."). Empty: "Nothing has finished in the last N hours."
- **`POST /partials/admin/jobs/{id}/retry`**: queues the same inputs under a new number and leaves the old row alone: "job #N is on the queue again as #M. The old one is left as it was." Refusal: the store's sentence, or "there is no job #N".
- **`POST /partials/admin/jobs/{id}/cancel`**: "job #N has already finished" if over; otherwise "job #N is over" (queued job removed), "job #N will stop when this server's own worker next checks it: it is running here, not on any computer" (pinned), or "job #N will stop on its next report - the computer running it is the only thing that can end it" (held by a computer).

## Settings, History (`/admin/audit`)

(source: ui.py `page_admin_audit`, `partial_admin_audit`; admin_audit.html; partials/admin_audit.html)

- **Who**: admins only. Not refreshed automatically.
- **Head**: "> HISTORY", "What changed in this fleet, and who changed it." Lead lists what writes a line (ticks and unticks, fleet stop and start, proxy download resumed, user deleted, computer forgotten, build published or made current, update pushed, file moved, site settings saved, Syncthing device approved) and "Nothing edits or removes a line except the retention pass."
- **what_changed window** (meta "kept for N days", the history retention): a filter box ("filter by project, editor, computer, version or action") with **filter** and, when filtering, **clear**. The filter matches the subject (`GET /partials/admin/audit?q=`). Up to 200 newest lines: when (exact time in tooltip), who (display name; sign-in name in tooltip), action, subject, detail (the recorded JSON as written).
- Empty: "Nothing in the timeline matches "<q>"." or "Nothing has been recorded yet. Every tick, stop, deletion and publish from here on lands in this list."

## Settings, Alerts (`/admin/alerts`)

(source: ui.py `page_admin_alerts`, `_alerts_context`, `_triage_status`, `/partials/admin/alerts/*`, `/admin/alerts/preview`, `/admin/alerts/triage/{id}`; admin_alerts.html; partials/admin_alerts.html. The checks themselves, sending and the server check live in alerts.py and triage.py, outside this part.)

- **Who**: admins only. Not refreshed automatically. Opening the page runs the alert scan once to list what is open.
- **Head**: "> ALERTS", "checked against N things every M minutes" (M = the alert interval, default 600 seconds, shown in whole minutes, at least 1).
  - **Preview this week's report** opens `GET /admin/alerts/preview` in a new tab: plain text "Subject: <subject>" and the body of this week's report, built from what is open now. Nothing is sent.
  - **Send a test** (`POST /partials/admin/alerts/test`): sends "This is a test of the CC Sync alert channel. Nothing is wrong." through the saved channel, never de-duplicated. Answers "test sent to <address or 'the configured sink'>." or "the test could not be sent: <detail>".
- Lead: "What this server checks about itself and the fleet, what it found, and where it sends it... This is the same information, pushed, plus a report every Monday morning."
- **currently_open window**: meta "N problem(s), N to look at" or "nothing open". Each finding: severity tag (**error** / **warn**), title, subject, diagnosis, detail, fix (with support address). Empty: "Nothing is wrong that this server can see. All N checks ran and found nothing."
- **where alerts go**: "Off by default. Nothing here ever leaves this NAS unless you set a channel. One save checks every field below together, and refuses the whole form on one bad field."
  - **channel window**: **Send alerts by** radio buttons for each available channel: **none** ("Nothing leaves this NAS. Problems still show on the Health page."), **mail (smtp)**, **webhook**. **Time zone** (an IANA name such as Europe/London; blank shows UTC; "The weekly report goes out at 08:00 on Monday in this zone."). **Weekly report** on (Monday 08:00) / off. **Daily "still here" message** on (one a day) / off ("If these stop arriving, the server itself is down."). **How many messages**: whatever suits the channel / one message per check / one message per problem (a webhook gets one POST per finding).
  - **server_check window** (meta on/off): "Claude Code reads everything this server knows is open, stuck or failing and mails you what needs a person, at these hours in the time zone set under channel. It only reads; a reply to its email can carry out the actions it offers." Fields: **Server check** on/off (needs Claude Code set up on Site, AI providers); **At these hours** (0 to 23, comma-separated, at most four; placeholder "6,18"); **Reply address** ("The only mail the server ever reads"; blank means the email cannot be replied to); **IMAP host** (blank works it out from the SMTP host; read with the SMTP user and password).
    - Status lines: "Server check is on/off.", "It cannot run its analysis: <why>. Each check will mail a plain summary instead.", "Replies are not being read (they need a reply address and mail as the channel).", "A check has been running since <time>.", "last check <time>, <status>[, the email did not go out]." with **read its report** (opens `GET /admin/alerts/triage/<id>`: the report text as mailed, 404 "no such server check"), or "No check has run yet.", "replies last read <ago>: <detail>". If its state cannot be read: "The server check's state could not be read: <error>".
    - **Run now** (`POST /partials/admin/alerts/triage/run`): starts a check whatever the schedule, one at a time; "Server check started. The report arrives by mail in a few minutes." (recorded in the history) or "the server check did not start: <why>".
  - **mail window**: SMTP host, SMTP port (usually 587 with STARTTLS, or 465), SMTP user, From, To (comma-separated), STARTTLS on/off, Verify the mail server's certificate on / off ("When on, a certificate that does not match the host is a refusal, never a silent fallback.").
    - **SMTP password**: when it comes from the deployment's environment: "in use: <mask>" and "This password comes from the deployment's own environment, so it cannot be changed here: change it where this server is deployed." Otherwise a password box (placeholder "stored: <mask>" or "not set"), **Set password** and **Clear** (`POST /partials/admin/alerts/password`). Results: "password stored.", "password cleared.", "there was no stored password.", or the store's error; if the environment password is in use anyway, adds "The deployment's environment password is still the one in use, and it wins over the one stored here: change it where this server is deployed." The password is kept in its own file on the server and never shown.
  - **webhook window**: Webhook URL (https only; body is {subject, text} as JSON; a stored URL is shown masked).
  - **Save** (`POST /partials/admin/alerts/save`; only the known setting keys are kept; field cap is the number of keys plus 4). Answers "saved." or, when a channel was just switched on from none, "Saved. The next check will send everything that is currently open." Refusals: the settings validator's message. Saving also starts the reply reader at once if replies were switched on. Recorded in the history.
- **sent.log window**: "Newest first, grouped by the message each one went out in. A failed send is kept..." Up to 200 rows: when, kind (including heartbeat, weekly, test), subject, to, result (**sent** or the refusal reason). A message carrying several findings has a header "<ago>: one message, N findings". Empty: "Nothing has been sent yet."
- **checks window** (meta "N checks, N found, N sent as alerts"): "So that silence is provably checked, not unchecked. Tick the kinds you want to be told about. An unticked kind is still checked every M minutes and still shows on this page and in the weekly report; it just sends no message. A check added in a later update starts ticked." Kinds grouped under headings, each with **found** or its severity word (**problem** / **to look at**) and a checkbox.
  - **Save**, **All**, **Problems only**, **None** (`POST /partials/admin/alerts/kinds`; a preset wins over the ticks; field cap is the number of kinds plus 6; an unknown kind is refused "not an alert kind: <list>"). Answers "saved. N of M kinds are sent as alerts." plus "The rest are still checked and still shown on this page and in the weekly report." when some are off. Recorded in the history.

## Settings, Health (`/admin/health`)

(source: ui.py `page_admin_health`, `_health_rows`, `_health_context`, `_notices_context`; ui_health.py; admin_health.html; partials/health_notices.html, health_collector.html, health_diagnostics.html)

- **Who**: admins only. This is where **settings** in the header lands. Not refreshed automatically. Opening it runs the alert scan once.
- **Head**: "> HEALTH", "N open across notices, alerts, invariants and protection" or "nothing open, every check answered", "Support: <support contact>". Band tags: **N needs attention** (errors), **N worth a look** (warnings), **N not checked**, or **nothing open**.
- Lead: "Everything this server currently has open, worst first... Nothing here changes anything." Note: "Not checked is not OK. It means this server cannot answer that one, and the reason is beside it."
- **what_is_running window** (link **packages**; meta "vendor channel last checked <ago>" or "the vendor channel has never been checked here"):
  - "this dashboard <version>" with **vendor: <newest>** (amber when the vendor has a newer one) or **vendor: not checked**.
  - Per platform: "<platform> computers are offered <current or 'nothing'>, published <ago>", **vendor: <newest>** (amber if behind), and one line per running build: "N on <version> (current), published <ago>".
  - "No computer build is current here yet, so nothing has been offered to anybody." when none.
  - Each disagreement (from the package store) as an amber note, or "Everything here agrees: this server, the vendor's channel and the computers reporting in."
  - A dashboard-update note when given. If the box cannot be built it is simply left out.
- **Four tabs**: **open findings (N)**, **problems the server found**, **collector**, **what computers said**. The last three load their contents once when the page opens.
- **open findings tab (open.log)**: one ranked list from four sources: the server's open problems ("PROBLEM THE SERVER FOUND"), the alert scan ("ALERT"), the invariants that are not OK ("INVARIANT"), and the protection lines that are not OK ("PROTECTION"). Order: errors, then warnings, then not checked; within a band, source in that order, then title and subject. Invariants or protection lines that are not checked or could not run go in "not checked". Each row: band tag (**needs attention** / **worth a look** / **not checked**), title, source, subject, diagnosis, fix (with support address), a link from the problem kind (brackets stripped from the label), and a link to the source page (**notices** jumps to the notices tab).
  - A source that fails to answer becomes one **not checked** row: "Could not read <source>", "<error type>: <first 160 characters>", "This page could not ask this source, so nothing it would report is shown here. That is not checked, not OK.", "Open "<page>" for its own list. If that page fails too, the dashboard log names the error." So the all-clear line can never show while a source is down.
  - Empty: "Nothing is open. Every check this server runs answered, and none of them found a problem."
  - After a dismiss on the notices tab, this list, the tab count, the bar meta and the head totals re-read themselves.
  - Footer links to the four detail pages.
- **problems the server found tab** (`GET /partials/health-notices`, admin only): "Things this server refused to do, and what to do about them. Each one comes back by itself if it is still true after you dismiss it." or "Nothing. N of M checks ran and found nothing wrong." with "N never ran". Each problem: severity, subject, check name, "last seen <ago>", body, fix, kind link, **dismiss** (same confirm as the home page; `POST /partials/health-notices/{id}/dismiss`, admin only; "that notice is already gone. Reload the page."), "first seen <ago>". The **what the server checks** fold-out as on the home page.
- **collector tab** (`GET /partials/health-collector`, admin only; "read only"):
  - "Retention last ran <ago>" (or "never on this database").
  - When stale: **stale** "The last collector cycle finished too long ago: everything below is the last thing it managed to do, not the state now."
  - Table of the background cycles (provision, config, enforce, inventory, connections, completion, remoteneed, prune, invariants, alerts, each explained in its tooltip): status light, last run, and "what it did not do": **failed** with the note ("no reason recorded"), **overdue** ("has not run again on time"), **incomplete** with the note, or "nothing". Empty: "no collector cycle has finished yet".
  - **pending share changes**: each held change "Sharing change held: <note> (<ago>)"; "No enforce cycle has run yet."; "Nothing pending: every folder's shares matched the plan as of <ago>."; or "What the enforce cycle would apply, as of <ago>: N share(s) to add, N to remove. Read only, nothing on this page changes a share." with a table of folder, **+ <first 7 characters of device id>** and **- <id>** tags; "showing the first 100 folders" when cut.
- **what computers said tab** (`GET /partials/health-diagnostics?editor=&machine=`, admin only): the same bundle list and crash-report download as the home page's window, "Showing <computer> only." with **every computer**, and "No computer has uploaded diagnostics yet. Use ask this computer why on a computer row on the home page, or have the editor open <location> in the companion. Companions older than the build that added this cannot send any."

## Settings, Invariants (`/admin/invariants`)

(source: ui.py `page_admin_invariants`; admin_invariants.html; partials/invariant_checks.html)

- **Who**: admins only. Read only; no buttons; not refreshed.
- **Head**: "> INVARIANTS" (tip: "An invariant is something that must always be true for sync to work..."), "re-checked every N minutes" (default 900 seconds), "N broken, N could not run, N not checked, N ok".
- Lead: facts the system relies on, re-checked on a timer; "Nothing on this page changes anything." Note: "Not checked is not OK."
- **invariants window** ("N checks"): each numbered check with **ok**, **broken** (red or amber by severity), **could not run**, or **not checked**; title; when it last ran ("never"); and for broken or failed ones the consequence, the fix (with support address); detail and each affected subject always. Empty: "No invariant pass has run yet."

## Settings, Protection (`/admin/protection`)

(source: ui.py `page_admin_protection`, `partial_admin_protection_ack`; admin_protection.html; partials/protection.html)

- **Who**: admins only. Not refreshed.
- **Head**: "> PROTECTION", "N of M confirmed, N missing, N this server cannot check, last looked at <ago>" (or "no pass has run yet").
- Lead: "What stands between this fleet and losing something, and what does not... Nothing is assumed to be there." Note: "Cannot verify is not protected... On a Synology the snapshot lines stay that way for good: DSM keeps its schedules somewhere no other program can read."
- **what_is_protected window**: each line **protected**, **missing**, **could not run**, or **cannot verify**, with title, and for anything not OK its consequence and fix; detail and subjects.
- **what_only_you_can_confirm window**: "This server cannot see a key on your workstation or a restore you did by hand. Record it here and the lines above turn green." Two date forms, each showing "last recorded <date> by <who>" or "never recorded":
  - "The release signing key is backed up, on" with **I have backed it up**. Not shown on a site that holds no private key (vendor build).
  - "A restore from a backup was tried, on" with **Record a restore**.
  - `POST /partials/admin/protection/ack` (`key`, `date`, admin only): records the date under the admin's name, writes it to the history, and re-checks that line at once. "recorded <date>." Refusals (an unreadable or future date, an unknown key) show the store's message.

## Settings, Recovery: GET SOMETHING BACK (`/admin/recovery`)

(source: ui.py `page_admin_recovery`, `_recovery_context`, `_resolve_undo_view`, `/partials/admin/recovery/*`; admin_recovery.html; partials/recovery.html. The plan, the snapshot list, the preview, the restore and the drill are in recovery.py, outside this part.)

- **Who**: admins only. Not refreshed. Asks the NAS on every render.
- **Head**: "> GET SOMETHING BACK", "nothing on this page overwrites anything". Lead explains that where the server can do the recovery itself it says so, and otherwise prints exact commands for this server with its real names; a restore copies into a new folder and never replaces anything.
- **protected_right_now window**: "N confirmed, N missing, N this server cannot check." with **the full list** (to Protection), and every line that is not OK (**missing**, **could not run**, **cannot verify**). All OK: "Everything this server checks is in place."
- **what_this_server_knows window**: each fact about the NAS, **confirmed** or **not confirmed** (with why and fix). None: "This server could not gather anything about this NAS just now."
- **what_went_wrong window** (the wizard): one link per problem (question and detail), each opening `/admin/recovery?problem=<key>#wizard`. The answer pane: "what to do", the question, and each step tagged **this server can do this** (with a **go** link to the page that does it), **on the NAS, as an administrator** (with the exact commands), or **not printed** ("this server is not sure of the names these commands need, so it will not guess"). Nothing picked: "Pick what went wrong, and what to do appears here."
  - **For the Resolve problem only: undo a clip-path change.** "Every time CC Sync changes where Resolve looks for clips, that computer writes the change down and tells this server. Undoing one puts those clip paths back on that computer, the same as "Undo last fix" in its tray's Settings. It happens when the computer next reports, and only while that project is open in its Resolve." Per computer that reported such changes or was asked: a table of when, project, clips changed, and **Undo this change** (confirm "Put back the N clip path(s) CC Sync changed in <project> on <computer>?") or **undo asked** when an unanswered ask exists (checked against every open ask, not only the five shown); then up to five recent asks: "<ago> <who> asked to undo <project>: <state sentence>". None: "No computer has told this server about a clip-path change it could undo. On the computer itself, "Undo last fix" is in the RESOLVE section of its tray's Settings."
  - `POST /partials/admin/recovery/resolve-undo` (`editor`, `machine`, `journal`, admin only; same rule as the JSON route, which 404s a change the computer has not reported and audits the ask): "Asked <computer> to put those clip paths back. It happens when that computer next reports, and only while that project is open in its Resolve; the answer shows in its list below."
- **put_files_back window** (anchor `#restore`):
  - When snapshots can be read: "Pick a project and a snapshot. Whatever is missing is copied into a new folder called .restored-<date> at the top of the Projects folder on the server, under the project's own name. It is not sent to any editor's computer..." Drop-downs **project** and **snapshot**, **See what is missing** (`POST /partials/admin/recovery/preview`, read only).
  - Preview: "<project> in <snapshot>: N file(s) missing from the server now, N that are there but different, N the same." ("This project is too large to list in full: the counts above stopped early." when cut), or **cannot say** when the folder could not be walked in one go (no zeros shown). A note, the missing file list ("+ <path>", "... and N more").
  - When anything is missing or different: checkbox **also bring back the ones that are there but different** (pre-ticked when only changed files exist) and **Restore into a new folder** (`POST /partials/admin/recovery/restore`), confirm "Copy N missing file(s)[, and the N different one(s) if the box is ticked,] into a new folder? Nothing there now changes." (or the changed-only wording). Result: "copied N file(s) into <where>. Nothing that was already there was touched." and "Restored N file(s) into <where>, at the top of the Projects folder on the server. A name that starts with a dot may be hidden in Explorer or Finder until hidden items are shown." plus "N could not be copied: <list>". Refusals from the recovery module appear as the error.
  - When snapshots cannot be read: "This server cannot read this NAS's snapshots, so it cannot put anything back by itself. <why>".
- **rehearse_a_restore window**: "Copies one real file out of the newest snapshot into a scratch folder, checks it came back exactly, deletes it again, and records the date on the protection page." **Rehearse a restore now** (`POST /partials/admin/recovery/drill`): "rehearsed a restore from <snapshot>: <detail>." or "the rehearsal FAILED: <detail>." The last five drills: **worked** / **failed**, when, snapshot, detail.
- **what_has_been_put_back window** (when any): up to ten restores: when, who, N files, snapshot, where.

## Setup wizard (`/setup`)

(source: ui.py `page_setup`; setup.html. Every control is driven by static/cc/setup.js against setup_routes.py, both outside this part: what follows is what the page draws.)

- **Who**: admins. A signed-in editor is redirected to `/`. With nobody signed in, the page opens only while the first-run window is open (decided in setup_routes); otherwise it redirects to `/login?next=/setup`. The Settings strip shows only for a signed-in visitor.
- **Head**: "> SETUP", "First-run wizard: every step here can be re-run later from Settings."
- **Step strip** (links): 1. Welcome, EULA; 2. Admin account; 3. Your studio; 4. Who should we tell?; 5. Checklist. Each step window carries a status tag (starts "checking").
- An error slot for errors with no step behind them.
- **1. welcome_eula**: the licence text, "I have read and accept this agreement." checkbox, **accept** (disabled until ticked; "Accepting is recorded with the agreement's version."), a status line.
- **2. create_your_admin_account**: filled by the script (the account form, or why there is none).
- **3. your_studio**: org name, short name (falls back to org name), tree name ("the top folder"), drive letter ("on Windows", placeholder P:\), template folders (comma-separated), **save** and a status line. Prefilled from the site settings when signed in (per the template comment).
- **4. who_should_we_tell**: "This server checks dozens of things about your fleet every few minutes. It needs somewhere to send what it finds. With nobody to tell, the first anyone hears of a stopped sync is an editor asking." Email address, or a webhook URL, a checkbox ticked by default "Also send one short "still here" message a day. If they stop arriving, this server is down.", **save**, **send a test**. "Email is sent through the mail server on Settings, then Alerts. If you have not set one up yet, save the address here and finish there."
- **checklist**: "Every step is re-runnable; optional ones may be skipped." Table of step, status, detail and an action column (filled by the script). "Stuck, or something here looks wrong? Send it to <support contact>."

## Help (`/help` and `/help/<document>`)

(source: ui.py `page_help`, `page_help_document`, `_help_response`; help.html. Finding, checking and rendering documents is help.py, outside this part.)

- **Who**: signed-in users. An editor gets the customer-facing document set; an admin gets every document this server carries (the choice is made in help.py from the admin flag).
- An unknown document still renders the page (with the document list) but answers with status 404.
- **Head**: "> HELP", the current document name (default HOW_IT_WORKS.md) or "not available on this server", and "Need a person? Contact <support contact>". Admins also see the Settings strip.
- **documents window** (count of documents): grouped links, each with title, file name and an optional note; the current one marked.
- On the main guide only: "How this system works, in plain English... The glossary is what every word on the other pages links back to." (link to `#glossary`).
- **contents window** ("N sections"): links built from the document's headings.
- **document window**: the rendered document (escaped before it is marked up). Glossary terms are anchors `#term-<slug>` that other pages link to (the glossary link `GLOSSARY_HREF` and per-term links built by `term_href`).
- If no help is available: the reason as a note.

## Your account (`/account`)

(source: account.html; partials/account_you.html, account_password.html, account_sessions.html, account_sync_keys.html, account_computer.html, account_jobs.html, account_result.html, person_queue.html, person_fix_root.html, ev_macros.html; ui_everyday.py. The page route and its other partial routes are in account_ui.py, outside this part.)

- **Who**: any signed-in user; always about the signed-in person (no `?as=`).
- **Head**: "> YOUR ACCOUNT" (admin tag for admins), "signed in as <name> · admin/editor · server password / local account / single sign-on · N computer(s), N wired to the server", and **Change your password** (jumps to the password window) when the password can be changed here.
- After a password change (`?changed=password&others=N`): **changed** "Password changed." plus "Signed out N other browser(s); this one stays signed in." / "No other browser was signed in; this one stays signed in." / "Your other browsers may still be signed in: check signed-in browsers below, or use Sign out everywhere."; with server (NAS) accounts also "Use the new one for the shared folders too."
- Admins: "This page is about you only. To change someone else's password, sign them out, or look after their computers, use Settings, Users." with a link.
- **you window** (never refreshed):
  - The shown name and "signed in as <name>". A **Name** form (up to 64 characters; placeholder the sign-in name; "Clear the box and save to go back to it."; **Save**; posts to `/partials/account/display-name`, outside this part) with a result line; a refused name keeps what was typed.
  - sign-in name ("cannot be changed: it is the key every computer, plan and file uses"); role (admin with where that comes from: "on the server's admin list" or "an admin in this dashboard's accounts"; or editor); signs in with ("your account on the server", "a local account kept by this dashboard", "your organisation's single sign-on") and a link "change your password" / "about your password"; account **active** or **suspended by an admin**; **sync keys** (loaded after paint from `/partials/account/sync-keys`: each key **approved** or **waiting for your admin**, fingerprint, the computer it came from; "a key is installed on the server; this server cannot show which one"; an unreadable note; "none yet" or "none, and none needed: a computer wired to the server syncs nothing"; "Your computers upload and download with these, not with your password..."); **your data** with **Download** (plain form to `POST /api/v1/me/export`, outside this part; downloads one JSON file about you and is audited).
- **change your password window** (never refreshed):
  - Single sign-on: "You sign in with your organisation's account, so there is no password on this dashboard to change." with where to change it, the sign-in host if known, a note that changing it elsewhere does not sign you out here, "No password here. Your organisation looks after it." and, for admins, the emergency **Admin sign-in** explanation.
  - Otherwise: what it changes (server accounts: the NAS password used for the dashboard and the shared folders; local accounts: only this dashboard sign-in), "it leaves alone: Syncing.", "afterwards: Every other browser signed in as <name> is signed out at once; this one stays signed in.", "forgotten it?" (another admin or your admin can set one), and for admins "someone else's" (Settings, Users).
  - Form: **current password**, **new password** ("at least N characters: that is the only rule", with a live "0 of N characters" counter), **new password again** (live match hint "type it again"), **show what I typed**, **Change password** (posts to `/partials/account/password`, outside this part). Refusals land in a fixed result slot, keeping the typed text; success reloads the account page. Idle text: "Fill in all three boxes, then press Change password. Nothing changes until the server says so."
- **your computers** (remote) and **your wired computers** sections, one window per computer, each refreshed every 30 seconds and after any of its own buttons or a queue untick:
  - Bar: computer name with **not heard from** (lost), **online**, or **not reporting**.
  - role (wired "works off the server share; syncs nothing" or remote "syncs projects to its own drive"), sync drive (the share mapped as the drive letter, for wired), CCSync version with **up to date** or **out of date: <current>**, system, licence line, **not reported** tags for withheld report categories, last report, and "now" (the computer's current why-sentence).
  - Out of date: admins get **Update now** (`POST /partials/admin/machines/update?view=none`); editors read "update it from its tray: Settings, HELP, Update to <v>. Your admin can also push it."
  - Remote only: "projects on this computer N ticked", each project with **full** or **upload only**, and **Sync fully** (asks the capacity question if any) / **Upload only**, and **Untick** (confirm "This removes <project> from <computer>. Its copies stay on disk; nothing new comes down and proxy sync stops for it."). All use the tick route with this computer and `view=none`. "Nothing is ticked for this computer." when empty. An add row: a project drop-down with **Tick** and **Upload only** (driven by cc/account.js, which asks the capacity question before a full tick).
  - **fleet jobs**: now (whether it is taking work, and why not), running, takes (kinds or "every kind" or "not reported"), starts after (idle time), graphics. When the computer can be asked: **Let the fleet use this computer** checkbox and one checkbox per job kind (disabled when fleet use is off), each saved on change (`/partials/account/machines/settings`, outside this part); unticking the last kind is refused in the page ("That is the last kind of work this computer takes. Untick Let the fleet use this computer instead."). "Asked of <computer> on its next report, and it takes effect when CCSync next starts there. Fleet work only runs while nobody is using the computer." A status line and **Withdraw** while a request is pending. Otherwise the reason it cannot be asked. "lend it now, or stop the job it is running: tray, Take fleet jobs now and Settings, FLEET JOBS".
  - **what it reported**: name, value (or "not reported") and where it is changed, per reported setting.
  - Foot: "Remote or wired, pause, stop all syncing, YouTube sign-in: <computer>'s tray, Settings." Admins, unless the computer is lost: **Ask this computer why** (`POST /partials/admin/machines/ask-why?view=none`).
  - No remote computers: "No remote computers have reported in as <name>. Install CCSync on a computer and sign in to it as <name>: it appears here after its first report." with **Get the installer**. No wired: "No computers wired to the server. A computer becomes one from its tray: Settings, THIS COMPUTER, Wired to the server, then a restart of CCSync."
- **sync queue window** (only with remote computers): loads and re-reads every 10 seconds (`GET /partials/person-queue`, signed-in, 401 "not logged in"; always the signed-in person). Safe-to-close note, the queue table as on the home page with **Untick** (person-wide, `view=person-queue`; the answer also refreshes every computer window), "Nothing ticked, so nothing syncs to your computers. Tick a project under each computer above, or in the projects list on the sync status page.", and one **fix destination root** block per remote computer: "open in Resolve on <computer>: <project> files into <folder> (admin-set / auto-matched, fixed; admins change it in the project's roots window)", or **no match**, or "no Resolve project reported yet".
- **your settings window**: a table of every setting the person has, its value now, and where it changes, in four groups: kept by this dashboard (Name; what each computer syncs, "N projects, N upload only"; Password; Signed-in browsers); each computer's own, asked from here (Let the fleet use this computer; Kinds of fleet work); each computer's own, changed from its tray (Remote or wired; Lend this computer to the fleet now; Drive reminder; YouTube terms and sign-in, only when the YouTube downloader is on for the site; Update CCSync; Sign this computer in or out); set for everyone (Drive letter; Automatic updates; YouTube downloads; Fleet stopped), with links to Settings for admins and "your admin" for editors.
- **signed-in browsers window** (loads and re-reads every 30 seconds from `/partials/account/sessions`, outside this part): "Every browser signed in as <name> (N now)...", each with address, browser (**this browser** tag), signed in, last seen, and **Sign out** for every other browser (confirm "Sign out <browser>? Whoever is using it has to sign in again."); **Sign out the others** (confirm "Sign <name> out of the other N browser(s)? This one stays signed in.") or "Only this browser is signed in."; **Sign out everywhere** (plain form to `/logout-everywhere`, browser confirm); "Use these if a computer or a phone was lost."

## Timeline Cards landing (`/cards/`)

(source: cards_landing.html. The route, the episode data and the open/close routes are in cards_landing.py and cards.py; the page script is static/cards_landing.js; all outside this part. What follows is what the template draws. The page also works with no script: folders are fold-outs and every button is a real form.)

- **Who**: signed-in users (it extends the shared frame). It links the Cards app's own web manifest instead of the dashboard's. When the old Cards page is not retired, it also loads the offline helper that registers the Cards service worker and marks cut lists downloaded on this device.
- **Head**: "> TIMELINE CARDS" and either (retired) "N in the vault", or "up to N episodes at once on this server · N open now · N in the vault". **Carry on with <episode>** when there is a last episode (retired: always; otherwise only if it is open).
- Lead: retired: "Open goes into the episode's newest cut list. Another cut list is one tap away inside the editor." Otherwise: "Your Resolve follows the last episode you went into. Two people in the same episode is fine: the cut list takes one edit at a time and both browsers see the same cards."
- Notes: **not opened** with a refusal sentence; a "want" note when the page was sent for a particular episode ("<name> is open." / "Opening <name>. This page takes you into it as soon as it is ready." / "<name> is not open. An episode closes when the dashboard restarts or somebody closes it. Open it again here.", with that episode's actions); "Opening <names>. This reads the episode off the vault: it takes a moment, and this page updates itself when it is ready." (without scripts the page reloads every 3 seconds while anything is opening).
- No episodes: "No episodes under the vault yet. An episode is a folder with an Interviewees or Clips folder in it."
- **find_an_episode window**: a search box ("search episodes, shows, years", shortcut `/`, **clear**); order chips **last opened** (default), **date**, **largest**, **A - Z**; year chips **all** and one per year; view chips **folders** (default) and **list**.
- **your_recent window** ("the last N you went into"; only episodes you opened yourself): tiles with name, path or show, badge and when opened; a tile opens the episode (a link when ready or retired, otherwise an open form; disabled while opening).
- **episodes window** ("N episodes", **unfold all**, **fold all**): year and show folders (top level and "hot" folders open by default) with episode count and total size; each episode row:
  - Icon by state, the name (a link when ready or retired), badge **ready** ("Open on the server, so going in is instant."), **opening**, or **failed**.
  - Meta: when opened ("never opened"; yours marked), size ("sizing" while counting; "+" when partial), "changed <when>", "in <path>".
  - The failure detail, an opening note, "in it now: <names>" or who was last in.
  - Actions: retired: **Open** (a link into the newest cut list). Otherwise: **Open** (link) when ready; "opening" spinner while loading; else an **Open** / **Try again** form posting to `/cards/open` (tip "Up to N can be open at once."); and **close** (posting to `/cards/close`, browser confirm with a server-built prompt) when the viewer may close it.
  - "Nothing matches." with **Show everything**.
- Foot (not retired): "An episode stays open behind you once it is open, so switching back is instant. You can close your own episode, or one nobody has been in for a while; closing one somebody else is in is for an admin."

## Files of this part (all read in full)

(source: the files below)

- dashboard/src/ccsync_dashboard/ui.py (lines 1 to 5442), ui_home.py, ui_health.py, ui_everyday.py, ui_chrome.py, ui_packages.py, ui_assets.py, static_files.py.
- Every template in dashboard/templates/ and dashboard/templates/partials/ (74 files), each represented in a section above.

## Looks redundant or overlapping

- **Two live-transfers views**: the home page's transfers window (moving files only, `/partials/home-transfers`) and the Transfers page (`/partials/transfers`), both polled every 2 seconds, both carrying the safe-to-close sentence. The account page's sync queue carries it a third time.
- **Three sync-queue renderings**: the home sync_queue window, the account page's person queue, and the project page's sync_plan window, each with its own untick, plus a fourth tick/untick surface in the account page's per-computer windows, a fifth in the projects tree, and a sixth in Sync plans. All go to one route, but each answer re-draws a different window, so the page needs a "plan changed" event to keep the others honest.
- **Two "fix destination root" read-outs** (home_fix_root and person_fix_root) plus the project_roots window that edits it.
- **Notices shown twice**: problems.log on the home page and the "problems the server found" tab on Health, with two dismiss routes (`/partials/notices/{id}/dismiss` and `/partials/health-notices/{id}/dismiss`) and two copies of the "what the server checks" list.
- **Diagnostics bundles shown twice**: home what_computers_said (`/partials/computer-answer`) and the Health tab (`/partials/health-diagnostics`), with near-identical templates and the crash-zip link in both.
- **Health page aggregates four pages** (notices, alerts, invariants, protection) that each still exist with their own full list; Recovery repeats the protection lines again.
- **Fleet stop shown in four places**: the every-page halt line, the home computers-window banner, the Users stop window, and the home "Stop the fleet" link; the account page's settings table names it a fifth time.
- **Forget a computer**: two routes doing the same thing (`/partials/admin/machines/forget` from Users and `/partials/admin/machines/forget-lost` from the home page).
- **Ask this computer why / update now**: each reachable from two pages (home row and account computer window; Packages and account), with `view=none` variants.
- **Make current**: three ways on Packages (the rollback drop-down on a served row, a held row's make current, the vendor row's make current) plus "make current anyway" twice.
- **SSH key entry** for a NAS account reuses the whole create-account route; local accounts have separate add/remove key routes.
- **Report tokens vs shared fleet token**: two credential systems shown side by side, with a panel whose only job is to say when the old one can be switched off.
- **Session revocation in three places**: header "sign out everywhere", Users "signed_in_browsers", account "signed-in browsers".
- **Three window/bar macro copies**: home_macros.win, ev_macros.win, and per-template `bar()` macros in admin_users, admin_jobs, admin_packages, admin_settings, admin_assignments, setup and recovery.
- **Two date-of-acknowledgement mechanisms for restores**: the Protection "Record a restore" form and the Recovery "Rehearse a restore now" button (which records the date itself).
- **The installer chooser** (`/installer`) and `/download` (which shows the same chooser for an unknown browser).

## Claims the code does not back

- The fleet-stop tooltips on the home page say "the pause ends by itself after 24 hours" and the Users window says "releases itself after a day"; the expiry length is set in db.py, not in this part, so the 24-hour figure is not confirmed here.
- The partials/home_macros.html header comment says it "is reachable only when `home` is on" and ev_macros says "only when `everyday` is on": there is no longer any group switch; the terminal look is the only look.
- shell.html comment: a request without `X-CC-UI` "is told to reload"; the gate is in app.py (not in this part) and was not verified here.
- partials/admin_jobs.html bar for the queue says "Each kind shows how many are running out of the most the whole fleet may run at once"; the caps come from jobs.py and were not verified here.
- fleet_grid.html (CHIP_HELP "trash") says files are "Pruned automatically after 14 days": that is a companion behaviour, not checked in this part.
- The Site page hint for SFTP chunk size says "On a Synology server use 64Ki": advice only; nothing on the page enforces it.
- Project roots: the template says the 30-second refresh is held while a folder picker is open (`data-poll-hold`); that behaviour is in static/htmx_errors.js, not verified here.
- The Users "signed_in_browsers" text says revoking takes effect "within a second"; no timing is set in this part.
- The project_access route comment says it 404s an unknown project through `_access_project_or_404`; confirmed only as a call, its behaviour is in api.py.

## Could not determine

- The exact refusal wording and conditions of every rule that lives in api.py, auth.py, db.py, alerts.py, recovery.py, release_feed.py, package_store.py, local_users.py and the NAS backends (make-current gate, soak, delete-user, forget-machine, move, link, access, originals, password length, throttle wait, enforce approval window): only the routes that call them are in this part.
- Which routes are open without sign-in: comments name `/login`, `/manifest.webmanifest`, `/sw.js`, `/offline` and (conditionally) `/setup`; the gate list is in app.py.
- Who may open `/admin/assignments` and `/account`, and what the account partial routes (`/partials/account/*`, `/partials/admin/users/display-name`, `/partials/admin/users/erase-history`) refuse: those routes are in account_ui.py, subject_data_api.py and assignments.py.
- Everything the page scripts do (assignments grid writes and confirms, site settings tabs, save, import, undo, AI providers, dashboard update, setup steps, Cards landing sort and search, account add-project row, project tree filter, window folding memory, confirm dialog wiring): the scripts are in dashboard/static, covered by another section.
- The fleet-stop expiry length, the plan-undo window (the message says one hour), the history retention days and the jobs finished window: constants in db.py.
- The health headline text and colour for each computer row (health.fleet_headline) and the "notes" count behind a row's details.
- The minimum companion version for originals on request (`db.ORIGINALS_MIN_COMPANION`).
- Whether the `/admin/alerts` page's per-render alert scan is expensive enough to matter (it runs the full scan on every page open and every alerts form answer).
