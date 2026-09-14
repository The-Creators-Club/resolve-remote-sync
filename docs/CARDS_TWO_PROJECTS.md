# Two people, two projects: a landing page and an engine each

**Status: PHASE 1 (with 1a and 1b) BUILT 2026-09-14, in the dashboard only.**
Section 11 is what was built, what was left out, and what has not been run
against a real engine. Phase 2 is untouched and still a plan.

Originally written 2026-09-14 after Alex asked
"right now is it possible for two users signed into different accounts to
work on two different cards projects at the same time", and then chose the
shape: *"at the landing page you just select a project and then go in to
start editing it"*.

**Revision 2, same day**, after a review against both checkouts. Nine
things in revision 1 were wrong or missing and every one of them is in here
now; section 8 lists them, because a plan that quietly corrects itself
teaches nobody anything.

Companion reading: `TIMELINE-CARDS-INTO-CCSYNC.md` section 3.2 (how the page
came to be mounted at all), `CARDS_DEPLOY.md` (how the snapshot deploy ships
the other repo's checkout).

---

## 1. The answer today, and exactly where it is decided

**No.** Two logins can both be on `/cards`, but they are looking through
one engine at one file.

* `dashboard/src/ccsync_dashboard/cards.py:379` builds ONE
  `ProjectAgentEngine` and keeps it on `app.state.cards_engine`. The mount,
  the WSGI shim and the 24 a2wsgi workers all front that single object.
* `multicam_pipeline/cards/project_engine.py:591` `open_project()` switches
  `self.path` **in place**. Its docstring is explicit that this is a shared
  act: *"A switch is a thing an editor waits for - the answer IS 'the cards
  are B's now'."* It is server state; no session, no user, no key.
* `library_engine.py:536` `set_root()` is the same story one level up: an
  episode-root switch is queued and waited for, and it is the engine's root,
  which means it is everyone's root (CR-101 is the bug from when the answer
  came back before the switch had landed).
* `cards.py:267` `CardsGate` is deliberately thin and mints no identity
  header, unlike `BrollGate` and `MusicGate`.

What *does* work today, and must keep working: **two people in the SAME
project**. The handler compares `body["version"]` against the engine's
(`handler.py:1096, 1120, 1222, 1247, 1294`), `project_engine.py:1816`
`_order_check` refuses an edit whose `base` order is no longer the live one,
and `busy` / `pending` apply one edit at a time. Two browsers - or a laptop
and a phone - already edit one cut list safely, and the multi-window support
(`17-windows.js`) was built on exactly that.

So the gap is narrow and specific: **different projects at the same time.**

---

## 2. What an engine actually is (this decides the whole cost)

`ProjectAgentEngine(ProjectEngine, AgentLink)` is ~7,400 lines:

| Layer | Scope | What it holds |
|---|---|---|
| `LibraryEngine` (4,518 lines) | **the episode ROOT** | the clip resolutions, the transcripts and token caches, the peaks/proxy/audio state, the library sweep thread, the ffmpeg worker, the translation and search runs |
| `ProjectEngine` (2,872 lines) | **the open FILE** | `_flat` / `_alts`, the uid maps, the marks, the card cache, the redo stack, the published state |
| `AgentLink` (`agent.py`) | **the wire to a machine** | the `/agent/*` protocol only. *"Nothing in this class imports fusionscript, which is the whole point - this is what runs in a container on the NAS"* (`agent.py:40`) |

That third row matters and revision 1 got it wrong: **there is no Resolve in
the container.** The bridge is in the companion (`timeline_cards_role.py`,
`timeline_cards_bridge.CardsBridge`), and CR-68's one-client rule is enforced
*there, per machine* (`timeline_cards_role.py:346, 372`). Two editors on two
machines are two Resolves, legitimately, and always were. See Phase 1a.

`_forget_file()` (`project_engine.py:559`) documents the root/file split:
switching files throws away the file half and keeps the root half, *"the
clip resolutions and every per-clip cache stay: they are the episode's"*.

Two consequences:

1. **An engine per ROOT is natural.** Two engines on two episodes share
   little and step on almost nothing (section 5 lists the almost).
2. **An engine per FILE within one root is not**, today: two engines on the
   same root keep two copies of that episode's library, sweep the same vault
   twice, and - the part revision 1 missed - both hold and rewrite the same
   per-root JSON stores. That is phase 2, and it is bigger than a refactor of
   one class.

---

## 3. The shape

```
/cards                    the LANDING page: which episode, which cut file.
                          Served by the mount itself - no engine needed to
                          draw it, so it answers even when every engine is
                          busy or absent.
/cards/p/<slug>/          the page as it is today, byte for byte, with one
                          engine behind it.
/cards/p/<slug>/api/...   every existing route, unchanged.
```

**THE URL IS THE KEY, NOT THE SESSION.** Revision 1 had the session carry
`cards_key`, which quietly forbids the everyday pair the same plan named:
one account, laptop and phone, two projects. The session may only *remember*
the last slug, so `/cards` can offer "carry on with Reproductive Rights -
Ordered V7" above the list.

**The slug is dashboard-minted, with a registry behind it.** Roots are
`X:\Vault\2026\FF5\Civil Defence`-shaped: spaces, CJK, and a Mac's NFD
against everyone else's NFC (CR-90). A path in a URL is a bug waiting for a
Mac; the slug is an opaque id in a small table, and the table is keyed
through the same normaliser `db.media_rel_key` uses.

The page's own URLs are document-relative on purpose - pinned for the
sibling mounts by `broll/web/tests/test_mounted_prefix.py` and
`music/web/tests/test_mounted_prefix.py` - so a deeper prefix costs the page
nothing and `tests/test_page_golden.py` does not move.

**No identity header.** Revision 1 had `CardsGate` start minting one the way
`BrollGate` does. It should not: "who is where" is dashboard state (session
to slug, last poll time), the sub-app reads no header today, and
`broll.py`'s strip-then-mint exists for a sub-app that *acts* on one.

---

## 4. Phase 1 - an engine per EPISODE, a landing page, a small pool

Two people in two different episodes. On this fleet that is the common case
by a wide margin (Reproductive Rights and Framing Formosa, say).

* `cards.py` grows an engine **pool**: `{slug: engine}`, built lazily on
  first entry, capped (`DASH_CARDS_ENGINES`, default **2**).
* **NO EVICTION IN PHASE 1.** The third entrant is refused with a sentence
  ("two episodes are open: Reproductive Rights (Alex, active 2 min ago) and
  Framing Formosa (Ruskin, 40 min ago) - ask one of them to leave, or an
  admin can drop an idle one"), and an admin action drops one deliberately.
  This is not timidity, it is section 6: **`stop()` does not stop anything
  today** (`project_agent.py:685` sets `self._stop = True`; the only reader
  anywhere is `project_engine.py:1632`, while `_lib_worker` at
  `agent.py:998`, the tokens worker at `agent.py:623` and the translator
  thread at `translate.py:314` are all `while True`). LRU eviction would leak
  a sweep thread and a translator per evicted engine. Eviction arrives when a
  real `stop()` does.
* `/cards` landing page: the episodes under the vault, each with its cut
  files, who is in it, and what it is doing (loaded / loading / failed / not
  open). One template in the dashboard; **no engine required to render it**.
* **Each engine gets its own `data_dir`** (`<data>/cards/<slug>/`). Today
  every engine would share `<data>/cards` (`cards.py:207`), which holds
  `cards_mirror.json`, `cards_pick.json`, `cards_lane_keys.json`
  (`agent.py:74-77`), `library_backups`, the EN-index cache
  (`library_engine.py:872`) and `cards_ui.json`. `project_pick.doc_save`
  (`project_pick.py:425`) is read-merge-write through a fixed `path + ".tmp"`
  with no cross-process lock: two engines calling `remember()` at once
  truncate each other.
* **The `cards_ui.json` boot root goes.** `build_engine` reads "the" root out
  of it at startup (`cards.py:212-221`) - meaningless with a pool, and
  actively wrong once a slug names the root.
* **`POST /api/root` is blocked at the gate.** It is a live route inside the
  page (`handler.py:1509`, calling `engine.set_root()`), and one click on the
  drawer's root menu would move engine A onto root B - which may already have
  an engine - making the pool key a lie. It becomes a redirect to the other
  slug's URL, which is what the click means now. `GET /api/roots`
  (`handler.py:398`) stays: the landing page wants that list.
* **The pinned executor takes a provider, not an engine.** `app.py:711`
  binds `PinnedExecutor(settings, app.state.cards_engine)` at boot and asks
  `available()` there; with a lazily built pool there is no engine at boot,
  so there is no executor, and every media job that spends its fleet retries
  goes `abandoned` - a silent regression of the port plan's phase 4. It must
  take a callable that answers "an engine, if there is one", and
  `available()` must be asked when a job needs it. (A job's `root` is a
  container mount - `vault` / `media` / `tree`, `cards_exec.py:297` - not an
  episode root, and `fleet_execute` takes absolute paths, so any engine's
  worker can run any pinned job. Revision 1 had this backwards.)

### Phase 1a - Resolve belongs to the account, not to the server

**The rule (Alex, 2026-09-14): a signed-in user may drive only the
companions signed in to their own account.** Alex's page drives Alex's
Creator-1 and Razer; Ruskin's page drives Ruskin's machine and nothing else.
Nobody "holds" Resolve fleet-wide, so nobody hands it over and the second
person is never blocked by the first. Revision 1's single-holder lock and
its [ TAKE RESOLVE ] button are both gone: they were solving a problem that
only existed because section 2's table put Resolve in the container.

It is not new machinery - it is the identity the tunnel already verifies:

* `cards_tunnel.py` overwrites the agent's self-asserted
  `socket.gethostname()` with the identity it verified and names the agent
  `editor/MACHINE`: *"THE VERIFIED IDENTITY IS THE AGENT'S NAME ... the
  verified name, never `body.editor`"*. That editor half comes from the
  dashboard's **own signed identity token** via `api._require_fleet_caller` -
  *"the only name allowed to decide anything"*.
* So: a state push routes to the engine **that editor is in**, and a page's
  live seam only sees agents whose editor half is the session's user.
  `cards_tunnel.py:115 local_engine()` reads the single
  `app.state.cards_engine` today and `agent.py:348` is last-push-wins
  (`self.agent_name = body.get("name") or self.agent_name`) - both become
  per-engine, which is the actual work in this section.

What it means concretely:

* An agent that is not yours **does not appear** on your page - not greyed,
  not refused on click. A conform button that always says no is worse than
  one that is not there. The landing page may say "Ruskin is live on his own
  machine" as information, with nothing to press.
* **No admin override**, deliberately. Driving another editor's Resolve is a
  synthetic keystroke into a timeline you cannot see, which is section 4.2 of
  the port plan's objection to scheduling `conform`. If it is ever wanted it
  is a separate explicit act with an audit line.
* **CR-68 binds per MACHINE**, in the companion. One person with one editing
  machine is live in at most one project at a time, and the refusal names
  *their own other project* rather than another person. An editor with two
  machines can be live in two projects at once.
* **Hardening that ships with it:** four machines still authenticate with the
  shared fleet report token (the dashboard says so at boot: *"0 use
  per-editor tokens"*). The binding rests on the signed identity token and
  holds either way, but per-editor `cce1.` tokens are what make a stolen
  companion credential useless for one editor's machines. Mint them on
  Admin > Users, then set `DASH_SHARED_REPORT_TOKEN_ENABLED=0`.

### Phase 1b - the phone, which is where this breaks first

Not optional, not later: an installed Cards app on a phone meets this before
any desktop does.

* **`/cards/sw.js` must become a kill switch.** The installed worker's scope
  is `/cards/`, which covers the new project URLs, and every navigation in
  scope goes through `shellAnswer` (`sw.js:383-395`) - so a phone whose
  network verdict is "down" gets the *old flat page* over the new URLs. The
  mount serves an unregister-and-claim worker at the old path, and the real
  worker registers at the project scope.
* **The login-gate exemptions must become patterns.** They are exact paths
  today: `app.py:114` `/cards/manifest.webmanifest`, `/cards/icon.svg`,
  `app.py:125` `/cards/sw.js`, pinned by `test_pwa.py:277-294`. Under the
  project prefix the manifest fetch - made without the cookie - 303s to
  `/login`, Chrome calls the page not installable, and the worker's periodic
  update fetch installs the login page as its own script. That is CR-100 and
  its 2026-09-04 sibling, exactly, and the comment at `app.py:118` already
  explains why.
* **The expired-session JSON-401 list too** (`app.py:1250`): it is the
  prefixes `/cards/api/`, `/cards/audio`, `/cards/video`, `/cards/peaks`.
  Under the new prefix an expired session hands an `audio` element a login
  *document*, which the page reads as "this clip has no audio".

### Phase 2 - two cut files of the SAME episode

Bigger than revision 1 said. It is not only `LibraryEngine` by composition:
every per-root store two engines would hold and rewrite whole comes with it -
`timeline_notes.json`, `cards_bins.json`, the PlanStore and PlaceStore
(`library_engine.py:378-381`, `stores.py:112-126`: atomic per writer,
last-writer-wins across two), `card_translations.json` /
`gt_translations.json` (`translate.py:66`), and the per-(root, scope)
transcript-search session (`transcript_search.py:447-463`), where two engines
resuming one Claude session id is the `_in_use` refusal `chat_edit.py:238`
already knows about. Only the per-file sidecars are safe. This deserves its
own plan; phase 1 makes it optional rather than urgent.

---

## 5. What it costs, honestly

* **Memory is a measurement, not a guess.** Before building: one engine on
  Reproductive Rights (572 cards, 11 multicams) and one on Framing Formosa
  (16), RSS after load, after a sweep, and with the ffmpeg worker running.
  The cap follows from that number. The dashboard - which is what tells the
  fleet whether their footage is syncing - wins every argument with this
  feature.
* **Two sweeps, two ffmpeg workers**, on different files but the same CPU.
  The heavy work is meant to go to the fleet (the jobs path) precisely so it
  does not run here.
* **Process-wide, one per process, not one per engine**: `project_pick.py:203`
  `_CANVAS_CACHE` is a ONE-entry cache and `:215` `_CANVAS_WORK` a single
  lock for every canvas, so two people prewarming canvases in two episodes
  serialise on a ~7 s conversion and evict each other. Performance, not
  correctness, and worth knowing before someone reports it as a hang.
* **Diagnostics assume one engine**: `mount_status.record_root("cards", ...)`
  (`cards.py:402`), `health_block`'s single `engine.root` (`cards.py:429`),
  and the `cards_tree_matches_source` invariant (`test_invariants.py:893`).
  Cosmetic, but they will say the wrong thing.

### The alternative we are not taking, and why

**A process per project**: run the standalone `server.py` on a loopback port
per project and proxy it, reusing the tunnel's own `_forward`
(`cards_tunnel.py:201`). Eviction becomes `kill`, every module-level global
and the thread leak disappear, and phase 2 comes free. We are not taking it
because it re-creates the two things section 3.2 of the port plan removed:
media Range/206 responses proxied through Starlette instead of served
in-process, and `CARDS_TOKEN` back on the wire. If phase 2 ever looks
unavoidable, this is the option to re-price against it rather than the
composition refactor.

## 6. Prerequisites, in the order they have to happen

1. **A real `stop()`** in the Cards repo - `_lib_worker`, the tokens worker
   and the translator thread all reading `_stop`, and `stop()` joining them -
   OR no eviction in phase 1 (which is what is planned, so this becomes the
   price of eviction later, not of shipping).
2. **Per-engine `data_dir`**, and `cards_ui.json`'s boot root removed.
3. **The slug registry**, normalised (CR-90).
4. **The executor by provider** (`app.py:711`).
5. **Gate and 401 lists as patterns**, plus the kill-switch worker.
6. **`POST /api/root` blocked** at the gate.

## 7. What this does NOT change

* Two people in one project: unchanged, still safe, still the normal way to
  work together.
* Conform on one machine: still one Resolve client (CR-68, in the companion).
  `conform` and `resolve-edit` must never become schedulable (port plan
  section 4.2). Two people conforming at once is two machines, each its
  owner's own.
* `POST /cards/api/restart` stays refused at the gate.
* The mount stays tri-state and never fatal: a broken pool must not stop the
  dashboard booting.
* The deploy: still the snapshot of the other repo plus the dashboard image.

## 8. What the review changed (revision 1 to 2)

1. `AgentLink` is the wire, not the Resolve bridge; there is no Resolve in
   the container, so the single-holder rule and [ TAKE RESOLVE ] were
   answering a bug that does not exist. (Alex's account rule replaced them
   independently, and is now the whole of Phase 1a.)
2. `cards_exec` does NOT know episode roots; the real problem is the
   executor being bound to an engine at boot.
3. `stop_engine` does not stop the threads - so no eviction in phase 1.
4. The URL, not the session, is the routing key.
5. The slug needs minting and a registry; a path is not a key.
6. `POST /api/root` inside the page defeats the pool.
7. One shared `data_dir`, and the `cards_ui.json` boot root.
8. The phone breaks first: service-worker scope, the manifest 303, the
   JSON-401 prefixes. Now its own phase, not a sentence.
9. The identity header is unnecessary; phase 2 undersells the shared
   per-root stores.

## 9. The tests that move

Dashboard (`dashboard/tests`):

* `test_cards_mount.py:500-571` - every mounted-route test assumes the flat
  `/cards/api/...`. Rewrite under the prefix, and add: the cap refusal,
  `/api/root` blocked, `/api/restart` and the agent prefix still blocked, the
  bare project URL redirect, and the landing page rendering with NO engine.
* `test_cards_mount.py:649` stops a FAKE engine with a `.stopped` flag, which
  is why nobody noticed `stop()` does nothing. A test against the real
  checkout asserting the thread count returns to baseline fails today - write
  it with the real `stop()` in section 6.1.
* `test_pwa.py:277-294` and `test_invariants.py:868-873` pin the exact open
  paths: change to patterns, and add "the prefixed `sw.js` /
  `manifest.webmanifest` / `icon.svg` are never redirected to login" and
  "`/cards/sw.js` is the kill switch".
* The expired-session JSON-401 test for `/cards/api/` - prefixed variants.
* `test_jobs_pinning.py:154-173` constructs `PinnedExecutor(settings,
  engine)`: it takes a provider now, and "available once the first engine
  exists, not decided at boot" is a new check.
* `test_cards_tunnel.py` - a push routes to that editor's engine; a push
  with no engine for that editor answers a sentence.
* New: two engines, two data dirs, `remember()` on both, nothing lost; the
  slug registry round-trips a CJK root.

Cards repo (`tests/`):

* `test_root_switch.py` pins `POST /api/root` landing - still true
  standalone; the block is pinned on the dashboard side.
* `test_project_agent.py` / `test_root_switch.py` build engines with
  `data_dir=tmp` - add two-engines-two-dirs isolation of pick / mirror /
  lane keys.
* New: `stop()` joins the library thread, the tokens thread and the
  translator.
* `test_multi_window.js` and `test_offline_page.js` fake `location` as
  `/cards/`: add a nested-scope variant and "an outer-scope worker
  unregisters itself".
* `test_page_golden.py`: unchanged.

## 10. The decisions left for Alex

1. **Phase 1 (with 1a and 1b) only, or 1 then 2?** Phase 1 is "two episodes
   at once" and is a few days *with* section 6. Phase 2 is "two cut files of
   one episode" and is a refactor of the other repo's core.
2. **How many engines?** 2 unless the memory measurement says 3.
3. Resolve: **decided** - your own account's companions, nobody else's.
4. Landing page: should it show that another editor is live on their own
   machine (information, nothing to press), or show nothing? The plan
   assumes the first.

---

## 11. What was built (2026-09-14)

Phase 1, 1a and 1b, **entirely in the ccsync repo**: the other repo needed no
change at all, and that is a finding rather than a saving. The page registers
its service worker document-relative (`navigator.serviceWorker.register('sw.js')`
in `15-offline.js`) and its manifest is relative too, so under
`/cards/p/<slug>/` both already land in the right scope. Only the OLD worker
at `/cards/` had to be dealt with, and that is a dashboard route.

### The pieces

| File | What it does |
|---|---|
| `dashboard/src/ccsync_dashboard/cards_pool.py` | NEW. The slug (`root_key` -> NFC + case-fold + separators, then a sha256 prefix with a readable label), the vault scan (`episodes()`), and `EnginePool`: `{slug: Entry}`, a cap, a background builder thread per episode, `note_visit` / `engine_for` for phase 1a, `drop` and `stop_all`. |
| `cards_landing.py` | NEW. `/cards/` (the landing page), `/cards/state.json`, `POST /cards/open`, `POST /cards/close` (admin), and the three flat PWA surfaces -- with `/cards/sw.js` now a KILL SWITCH. |
| `templates/cards_landing.html` | NEW. The episode list with its four states, who is in each (information, nothing to press), the cap refusal, and a self-refresh only while something is opening. |
| `cards.py` | `build_engine` takes `root` and `data_dir`; `data_dir_for(settings, slug)` is `<data>/cards/<slug>`; the `cards_ui.json` boot root is GONE; `CardsDispatch` routes `/cards/p/<slug>/...`; `/api/root` joins `/api/restart` in `BLOCKED_PATHS`; `stop_engine` drains the pool; `engine_provider(app)`; the health line is one row per episode. |
| `cards_tunnel.py` | `local_engine(request, editor)` and `_routed`: a push goes to the engine that editor is in, and an editor in no episode gets a sentence (an empty answer on the long poll, which is what "no edit for you" already looks like). |
| `cards_exec.py` | `PinnedExecutor` takes an engine OR a callable that answers with one, asked per call; `start()` no longer refuses to start when there is no engine yet; the seam is bound once per job. |
| `app.py` | `_open_path()` = the literal set plus ONE pattern for `/cards/p/<slug>/{sw.js,manifest.webmanifest,icon.svg}`; the JSON-401 list gains `_cards_json_re` for the four prefixes under a slug; the executor is built from `cards.engine_provider(app)`. |
| `settings.py` | `cards_engines` / `DASH_CARDS_ENGINES`, default 2. |

### The decisions, as taken

* **Slug**: a hash of the normalised root with a readable label
  (`civil-defence-9f2a1c04`), no registry table. Stable across restarts and
  machines, so an installed phone app keeps working, and CR-90 is handled at
  the point of minting.
* **Cap 2**, refusal not eviction, admin close on the landing page. The
  memory measurement in §5 has NOT been taken - two is the default until it
  is, and the refusal is what keeps that honest.
* **Resolve is the account's**: the routing half of 1a is built. See below
  for the half that is not.
* **The landing page names who is live**, with nothing to press.

### What was deliberately left out

* **Per-viewer agent filtering inside the page.** 1a routes each editor's
  pushes to their own episode's engine, which is what stops a sweep landing
  in somebody else's timeline. But two editors in the SAME episode still
  share one engine, and `agent.py:348` is last-push-wins, so the second
  agent's name overwrites the first on that page. Making the page show each
  viewer only their own agent is a change in the other repo (the engine holds
  one agent, not a map), and it belongs with phase 2's per-root work.
* **A real `stop()`.** Unchanged upstream, so `drop()` frees the SEAT and not
  the threads, and says so in its own docstring. Eviction still waits on it.
* **Phase 2** (two cut files of one episode): untouched.

### What has not been proved

Everything here ran against the fake checkout in `dashboard/tests`. **No real
`ProjectAgentEngine` has been built twice in one process**, which is where
the per-root stores of §4's phase 2 list would bite if any of them turn out
to be process-global rather than per-engine (`project_pick._CANVAS_CACHE` and
`_CANVAS_WORK` are known to be, and that is performance, not correctness).
The first live run should be two episodes on FF5lab, watching RSS, before
anybody edits a real cut on it.

### Tests

`dashboard/tests/test_cards_pool.py` is new (30 tests: the slug's NFC/NFD and
CJK cases, the cap sentence, a failed episode holding no seat, per-engine
data dirs, the landing page with no engine, `/api/root` blocked, the kill
switch, the open-path pattern refusing to widen, and the two races the build
found in itself - a gate cached by slug serving a reopened episode's dead
engine, and an episode closed while its builder thread still held it).
`test_cards_mount.py` was rewritten onto the prefix and gained the two phase
1a routing tests. Both suites pass, and so does the rest of the dashboard
suite.
