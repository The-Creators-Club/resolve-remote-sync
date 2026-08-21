# Client folders — curated b-roll with a link a client can open

*Built 2026-08-18. Owner's ask: "curate folders of b-roll and get an external
link to send to clients who might want to licence it; they preview the folder
the way an editor peruses b-roll."*

A **client folder** is a hand-picked set of archive clips with a title, a
description, a contact line and a **link**. Whoever has the link, and nobody
else, sees a page that works like the b-roll archive does for an editor:
thumbnails that scrub on hover, a preview player, and "what is in this clip".
No login, no account, no companion. Previews only (the 540p proxy), never an
original.

Contents: [1. Using it](#1-using-it) · [2. What the client sees](#2-what-the-client-sees-and-what-they-never-see)
· [3. Making the link reach outside the tailnet](#3-making-the-link-reach-outside-the-tailnet-tailscale-funnel)
· [4. Security posture](#4-security-posture) · [5. Data and backup](#5-data-and-backup)
· [6. Limits and what is not built](#6-limits-and-what-is-deliberately-not-built) · [7. Files](#7-files)

---

## 1. Using it

Everything is on the b-roll page (`/broll`), signed in as any editor.

**Make a folder, add clips.**

- Hover any thumbnail in the grid: a **+** appears in its top-right corner.
  Click it and tick the folder(s) the clip belongs in, or `+ new folder…` to
  make one on the spot. The same popover is on the detail view's
  **+ client folder** button.
- The **☰ Client folders** button in the header (left of the settings gear)
  opens the panel: every folder, its status chip (`live` / `revoked` /
  `expired`), clip count, who made it and how often the link has been opened.
- Open a folder to edit its **title**, **description** and **contact** (the
  client sees all three; an email address becomes a "mailto" link with the
  folder named in the subject), set an **expiry** (never / 7 / 30 / 90 days),
  **reorder** clips (▲▼), give each clip a **caption** the client sees under
  the thumbnail, or **remove** one (✕).

**Send the link.** The panel shows the folder's link with **Copy** and
**open**. Paste it into an email. Until an admin has set the public link base
(§3), the panel warns that the link only works for people already on the
tailnet, i.e. only for you.

**Take it back.** **Revoke link** kills it at once (the page and every
thumbnail on it answer "not available", even to a browser that already has it
open); **Reactivate** brings the same link back; **New link** issues a fresh
one and kills the old (for a link that was forwarded on). **Delete folder**
removes the folder and its link for good. Every editor sees and can edit every
folder: a client folder is the studio's, and "the one we sent to Acme" has to
be findable by whoever is at the desk.

Nothing about the archive changes when you do any of this. A folder is a list
of references; the clips stay where they are.

## 2. What the client sees, and what they never see

The link opens `…/broll/share/<token>/`: the studio's name (site manifest
`org_name`), the folder's title, description and contact line, and a grid of
clips. Each card is the poster frame, the duration, and the caption (or the
clip's name). Hovering scrubs the sprite sheet exactly as it does for an
editor. Clicking plays the 540p preview with the browser's own controls, and
lists the clip's visual segments with timecodes ("harbour wide, slow push in
· exterior, golden hour"), each clickable to seek. Left/right arrows step
through the folder, Esc returns to the grid; a clip has its own URL
(`#v=<id>`) so a client can point at "this one".

What the public routes will **not** answer, by construction
(`broll/web/app/client_folders.py: PUBLIC_VIDEO_COLUMNS` is the allow-list;
`routes_share.py` has no `SELECT *`):

- any file path, share name or archive layout (`rel_path`, `archive_path`,
  `original_path`, `share`). The only path fragment a client sees is the
  clip's basename without extension, i.e. what the shot was named;
- the transcript, themes or quality flags: editors' search tools, not a
  buyer's preview;
- any clip that is not in *this* folder: media routes check membership on
  every request, so `…/media/proxy/<other id>.mp4` is a 404;
- the existence of any other folder, or whether a dead token was revoked,
  expired or never existed: one 404 for all three, and an HTML "not
  available" page rather than a JSON error on the two page routes;
- an original. Ever. The proxy is served with `controlslist="nodownload"`
  (a deterrent, not a lock: previews are meant to be watched);
- a search-engine listing or a Referer: every response carries
  `X-Robots-Tag: noindex, nofollow, noarchive` and
  `Referrer-Policy: no-referrer`.

The viewer counts an opening of the folder (`view_count`, `last_viewed_at`),
which the panel shows as "opened 3 times, last …". Nothing finer, and nothing
about who.

## 3. Making the link reach outside the tailnet (Tailscale Funnel)

**The tension, stated plainly.** On 2026-08-17 the product decision was that
Tailscale Serve is the *only* way the dashboard is published, for us and for
customers: no reverse proxy, no DDNS, no public exposure, because the login
page is the dashboard's only gate and the Syncthing GUI beside it is admin
over every fleet folder. A client is not on the tailnet, so a client link
needs a public door. The recommendation is **Tailscale Funnel on a separate
port, scoped to exactly one path prefix, `/broll/share`**. That keeps the
decision intact in every way that mattered:

- still Tailscale, still HTTPS with a certificate Tailscale manages, still
  nothing opened on the router and no DDNS;
- the login page, `/api`, `/broll` proper, `/music`, `/ytdl`, Syncthing:
  **not** on the funnel. Funnel publishes everything a port serves, so the
  share prefix gets its *own* port (Funnel allows 443, 8443 and 10000; 443 is
  the tailnet-only Serve of the whole dashboard and stays that way);
- what *is* on the funnel is a set of read-only routes that reveal nothing
  without a 128-bit token, and nothing but that folder's previews with one.

The rejected alternatives, so nobody re-litigates them: a DSM reverse-proxy
rule or router port-forward (the door the 08-17 decision closed; also no
certificate story); a "public dashboard" bind (publishes the login page);
mailing the client an export (loses the browse-and-scrub experience the owner
asked for, and is a copy of the previews we cannot revoke).

### 3.1 Prerequisites (one-time, in the Tailscale admin console)

1. **HTTPS certificates enabled** on the tailnet (DNS → "Enable HTTPS"). Same
   click Serve needed; `docs/SERVER-SYNOLOGY.md` "Access" describes the
   "Serve is not enabled on your tailnet" first-run message.
2. **Funnel allowed for the NAS** in the tailnet policy file. Funnel is off by
   default and is enabled per-node through a node attribute; add to the ACL:

   ```jsonc
   "nodeAttrs": [
     { "target": ["autogroup:member"], "attr": ["funnel"] }
   ]
   ```

   (or target the NAS by tag/name instead of `autogroup:member` to be
   narrower). Until this exists, `tailscale funnel` refuses with a message
   naming the attribute and a link to the admin console. That message is a
   normal first-run state, not a failure.

### 3.2 Turn it on

The target is the dashboard's HTTP listener as seen from wherever tailscaled
runs, **with the prefix repeated on the target**. `--set-path /broll/share`
mounts the proxy at that prefix and Tailscale STRIPS the mount path before
forwarding (measured 2026-08-18 on Tailscale 1.98.9: with a bare
`http://host:8480` target the dashboard received `/assets/share.css`, and its
login redirect said so: `next=%2Fassets%2Fshare.css`); a target of
`http://host:8480/broll/share` puts it back, and the dashboard then sees
`/broll/share/assets/share.css` exactly as it must. Everything the viewer
needs lives under that prefix by design (§7), so nothing else has to be
published.

**Synology (Tailscale is a DSM package; the dashboard binds 127.0.0.1:8480):**

```sh
TS=/var/packages/Tailscale/target/bin/tailscale
sudo $TS funnel --bg --yes --https=8443 --set-path /broll/share http://127.0.0.1:8480/broll/share
sudo $TS serve status        # expect: https://<nas>.<tailnet>.ts.net:8443 (Funnel on) |-- /broll/share proxy http://127.0.0.1:8480/broll/share
```

**TrueNAS (Tailscale is an app in a container on the host network; the
dashboard binds the tailnet IP from `[net] bind_tailnet`, not loopback):**

```sh
# over SSH on the NAS; the container is named `tailscale`
sudo docker exec tailscale tailscale funnel --bg --yes --https=8443 --set-path /broll/share http://<tailnet-ip>:8480/broll/share
sudo docker exec tailscale tailscale serve status
```

`tailscale funnel` takes the SAME arguments as `tailscale serve` and turns
Funnel on for that mount in one go; there is no separate `funnel … on` step
(that form fails on 1.98 with `non-localhost target "http://on" must include
a scheme`). To go tailnet-only again: `tailscale funnel --https=8443 off`
leaves the mount, `serve --https=8443 --set-path /broll/share off` removes it.

**`tailscale funnel …` BLOCKS until the tailnet allows Funnel for this
node.** With no `funnel` node attribute it prints

```
Funnel is not enabled on your tailnet.
To enable, visit:
         https://login.tailscale.com/f/funnel?node=<id>
```

and then waits, polling, until someone with admin rights on the tailnet
clicks that link (or edits the policy file, §3.1); the moment they do, it
completes on its own. Run it under `nohup … &` if you are not going to keep
the shell open, or just re-run it after the click.

If the Tailscale app is not on the host network, `127.0.0.1` inside the
container is not the NAS; use the address the dashboard actually binds
(`site.toml [net] bind_tailnet`, the same one `dashboard_url` names).

**Verify, from a machine that is NOT on the tailnet** (a phone on mobile
data is the honest test):

```sh
curl -sSI https://<nas>.<tailnet>.ts.net:8443/broll/share/assets/share.css | head -1   # HTTP/2 200
curl -sSI https://<nas>.<tailnet>.ts.net:8443/login | head -1                          # 404: NOT published
curl -sSI https://<nas>.<tailnet>.ts.net:8443/broll/share/nope/ | head -1              # 404 (the "not available" page)
```

Only the first should be a 200. If `share.css` is a 404 or a login redirect
whose `next=` starts with `/assets/…`, the mount prefix was stripped and not
put back: the target must end in `/broll/share` (above).

**Then set the public link base**, once: open the Client folders panel as an
admin and put `https://<nas>.<tailnet>.ts.net:8443` (scheme, host, port; no
path) in **Public link base** → Save. Every folder's link is minted against it
from then on, and the panel's "tailnet only" warning goes away. The value is
site data (stored beside the folders, §5), not code or an env var: nothing to
redeploy, and a customer's is theirs.

**Turn it off** with `tailscale funnel --https=8443 off` (the serve mount can
stay; it is tailnet-only without the funnel) and clear the public base.

**Done for this fleet on 2026-08-19:** `truenas.tail26290e.ts.net:8443`, the
`funnel` attribute granted by the owner through the console link, the folder
JSON fetched from outside the tailnet (200) and `/login` on that port 404.

### 3.3 What Funnel costs

Funnel traffic is relayed through Tailscale's ingress servers (TLS terminates
on the NAS; the relay sees only the encrypted stream). Tailscale documents it
as bandwidth-limited and not for heavy serving. For what this is (a client
scrubbing thumbnails and watching a few 540p previews) it is fine; it is not
a delivery channel for masters, and it was never meant to be one. If a
customer's clients are numerous or far away, the answer is a proper CDN'd
front for the share prefix, not a wider Funnel, and that is a separate piece
of work.

## 4. Security posture

- **The token is the credential.** `secrets.token_urlsafe(16)`: 22 URL-safe
  characters, 128 bits, unguessable, minted server-side. It is stored in the
  clear (`client_folders.token`) so the panel can show the link again; a copy
  of `client_shares.db` is therefore a copy of every live link, which is also
  true of the browser history of everyone who ever clicked one. Revoke and
  rotate exist for exactly that. The database is on the NAS, behind the
  dashboard, behind the tailnet.
- **Every public request re-checks.** `routes_share._live_folder` (token
  valid, not revoked, not expired) and `_member_id` (this clip is in this
  folder) run per request, so a link that dies while a page is open stops
  serving on the next thumbnail, not the next visit.
- **The dashboard opens one prefix.** `app.login_gate` lets `/broll/share/`
  through with no session; `BrollGate` still strips any inbound
  `X-CCSync-User`, so an anonymous request is anonymous inside the sub-app.
  `/broll/api/client-folders` (the curation API) stays behind the session and
  needs the gate's identity stamp; the public base URL is admin-only.
- **Read-only on the funnel side.** Nothing under `/share/` accepts a body.
  The one write a stranger triggers is `view_count += 1`.
- **Rate limiting: none.** 2^128 makes enumeration a non-problem; a
  determined pest hammering one live token is a Funnel-bandwidth problem, and
  revoke is one click.
- **Not gated by a `[features]` flag.** The routes exist on every deployment;
  they are inert without a token, and useless outside the tailnet without
  Funnel, which the operator turns on by hand (§3). A flag would only add a
  redeploy between "the owner wants this" and "the owner has this".

## 5. Data and backup

Folders live in **`client_shares.db`**, a separate SQLite file beside
`broll.db` in the b-roll data root (`<tree_name>/Assets/B-roll Archive/` on
the NAS, `BROLL_DATA_ROOT` in the container). Not new tables in `broll.db`,
on purpose: `broll.db` is the search *index*, which the base rig builds and
pushes over the live copy with `server/publish_db.py` (rename-swap), and a
customer's client folders must survive every index publish. Clips are stored
by `videos.id` **and** by `(share, rel_path)`, so an archive re-indexed with
new ids re-resolves its folders by name at read time (`resolve_items`); a clip
that has left the index shows in the panel as "no longer in the archive
index" and is simply not shown to the client.

Schema: `client_folders`, `client_folder_items`, `client_share_settings`
(one key today, `public_base_url`); `PRAGMA user_version = 1`;
`client_folders.ensure_schema` creates it and refuses a newer version. The
container creates the file itself on first use (WAL mode, like `broll.db`);
on DSM that means it inherits the share's ACL like any new file there
(`docs/synology-spikes-2026-08-17.md` spike 1: never chown/chmod inside the
tree share).

Backup: it is on the **tree** dataset, so `server/setup_snapshots.py`'s
schedule already covers it and `docs/BACKUP_RESTORE.md` §4a restores it like
any other file (with or without its `-wal`/`-shm`, never one without the
other). `publish_db.py` does not touch it and must not learn to.

## 6. Limits, and what is deliberately not built

- **No watermark.** Previews go out as they are indexed (540p, the same
  proxy an editor scrubs). A burned-in watermark would mean a second proxy per
  clip in the archive tree; if licensing traffic grows, that is the next
  thing, and it belongs in the indexer's proxy step, not here.
- **No download button, no originals.** The client asks; the studio delivers
  through whatever it delivers masters through today.
- **No per-client password.** The link is the credential; a password on top
  would be a second secret to send in the same email. Expiry and revoke are
  the controls.
- **No branding beyond the org name.** The page is the fleet's own theme
  (dark, mono, red hairlines) with the site's `org_name`; the brand logo the
  dashboard carries is not on it yet.
- **View counts are per page-open, anonymous.** No per-clip analytics.
- **Folders hold at most 500 clips.** A thousand-clip "folder" is the
  archive, and the page would take a while to draw.
- **URLs carry the port** (`:8443`). Cosmetic; a nicer hostname in front is a
  DNS CNAME + certificate question for later, and it must not become a
  reverse proxy that re-opens the 08-17 decision.

## 7. Files

| File | What |
|---|---|
| `broll/web/app/client_folders.py` | the ledger: `client_shares.db` schema, tokens, CRUD, membership, `resolve_items`, settings |
| `broll/web/app/routes_client_folders.py` | the editor's API, `/api/client-folders` (session identity via the gate's `X-CCSync-User`; public base admin-only) |
| `broll/web/app/routes_share.py` | the public door, `/share/{token}/…` (page, `api/folder`, `api/videos/{id}`, `media/{proxy,sprite,poster}`), all read-only, token-checked per request |
| `broll/web/app/main.py` | includes both routers; mounts a VIEWER-ONLY copy of the static tree at `/share/assets` so the viewer needs nothing outside `/broll/share`. `ShareAssets` serves the `SHARE_ASSETS` allow-list (`style.css`, `share.css`, `share.js`, `sprite.js`, the two favicons, `brand_mark.png`) and 404s everything else exactly as a missing file would, because that directory also holds the editors' SPA -- `app.js`, `ingest.js`, `clientfolders.js`, `index.html` -- and `/broll/share` is the one prefix an operator publishes past the tailnet with a Funnel (broll-3, 2026-08-21). Adding a file to the viewer means adding it to that list |
| `broll/web/static/clientfolders.js` | the panel, the card **+** and its popover (a third classic script; `cf*` names only) |
| `broll/web/static/sprite.js` | the sprite-sheet geometry, extracted from `app.js` so the viewer scrubs with the same arithmetic |
| `broll/web/static/share.html`, `share.js`, `share.css`, `share_gone.html` | the viewer, and the "not available" page |
| `dashboard/src/ccsync_dashboard/app.py` | `login_gate` opens `/broll/share/` |
| `dashboard/src/ccsync_dashboard/broll.py` | `_init_broll_storage` also creates `client_shares.db` (best-effort: a b-roll tree from before the feature still mounts) |
| `broll/web/tests/test_client_folders.py`, `dashboard/tests/test_broll_mount.py` | what §2 and §4 promise, pinned |
