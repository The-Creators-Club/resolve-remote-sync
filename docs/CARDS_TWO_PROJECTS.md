# Two people, two projects: a landing page and an engine each

**Status: PLAN, nothing built.** Written 2026-09-14 after Alex asked
"right now is it possible for two users signed into different accounts to
work on two different cards projects at the same time", and then chose the
shape: *"at the landing page you just select a project and then go in to
start editing it"*.

Companion reading: `TIMELINE-CARDS-INTO-CCSYNC.md` (how the page came to be
mounted in the dashboard at all - this plan changes §3.2's "one engine" into
"a pool", and nothing else about that contract), `CARDS_DEPLOY.md` (how the
snapshot deploy ships the other repo's checkout).

---

## 1. The answer today, and exactly where it is decided

**No.** Two logins can both be on `/cards`, but they are looking through
one engine at one file.

* `dashboard/src/ccsync_dashboard/cards.py:379` builds ONE
  `ProjectAgentEngine` and keeps it on `app.state.cards_engine`. The mount,
  the WSGI shim and the 24 a2wsgi workers all front that single object.
* `multicam_pipeline/cards/project_engine.py:592` `open_project()` switches
  `self.path` **in place**. Its docstring is explicit that this is a shared
  act: *"A switch is a thing an editor waits for - the answer IS 'the cards
  are B's now'."* It is server state; no session, no user, no key.
* `library_engine.py:536` `set_root()` is the same story one level up: an
  episode-root switch is queued and waited for, and it is the engine's root,
  which means it is everyone's root (CR-101 is the bug from when the answer
  came back before the switch had landed).
* `cards.py:267` `CardsGate` is deliberately thin and **mints no identity
  header**, unlike `BrollGate` and `MusicGate`: *"Timeline Cards has no
  per-editor state ... When that changes it changes with a schema, not with
  a header the sub-app trusts because we sent it."* This plan is that change,
  and it takes the note at its word.

What *does* work today, and must keep working: **two people in the SAME
project**. Every edit posts `version` + `base`, `_order_check` refuses a
stale one, and one edit is applied at a time (`busy` / `pending`). Two
browsers - or a laptop and a phone - already edit one cut list safely, and
the multi-window support (`17-windows.js`) was built on exactly that.

So the gap is narrow and specific: **different projects at the same time.**

---

## 2. What an engine actually is (this decides the whole cost)

`ProjectAgentEngine(ProjectEngine, AgentLink)` is ~7,400 lines of two
inherited layers, and the split between them is not where you would want it:

| Layer | Scope | What it holds |
|---|---|---|
| `LibraryEngine` (4,518 lines) | **the episode ROOT** | the clip resolutions, the transcripts and token caches, the peaks/proxy/audio state, the library sweep thread, the ffmpeg worker, the translation and search runs |
| `ProjectEngine` (2,872 lines) | **the open FILE** | `_flat` / `_alts`, the uid maps, the marks, the card cache, the redo stack, the published state |
| `AgentLink` | **the machine** | the Resolve bridge, the conform, the live timeline |

`_forget_file()` is the honest documentation of the split: switching files
throws away the file half and keeps the root half, *"the clip resolutions
and every per-clip cache stay: they are the episode's"*.

Two consequences, and they are the plan:

1. **An engine per ROOT is cheap and natural.** Two engines on two episodes
   share nothing and step on nothing.
2. **An engine per FILE within one root is not**, today: two engines on the
   same root would keep two copies of that episode's library, sweep the same
   vault twice and re-read the same transcripts. Nothing would break (the
   media writers are `.partial` + atomic rename, first writer wins - rule 2),
   but it is double the memory and double the disk churn for one episode.
   Making that cheap means splitting `LibraryEngine` out of the inheritance
   chain and sharing it by composition, which is a real refactor of the other
   repo's core.

Hence the phasing in §4.

---

## 3. The shape Alex asked for

```
/cards                    the LANDING page: which episode, which cut file.
                          Served by the mount itself - no engine needed to
                          draw it, so it answers even when every engine is
                          busy or absent.
/cards/p/<key>/           the page as it is today, byte for byte, with one
                          engine behind it. <key> is the episode root (phase
                          1) and later (root, file) (phase 2).
/cards/p/<key>/api/...    every existing route, unchanged.
```

The page's own URLs are **document-relative on purpose** and there is a test
pinning that for the other two mounts (`broll/web/tests/test_mounted_prefix.py`,
`music/web/tests/test_mounted_prefix.py`); Timeline Cards is the same - it
already runs under `/cards` having been written for `/`. So a deeper prefix
costs nothing in the page, and `tests/test_page_golden.py` does not move.

**Going in is one click next time.** The session remembers the last key
(dashboard session, not localStorage - it is about the account, not the
browser), so `/cards` can offer "carry on with Reproductive Rights - Ordered
V7" above the list.

**The landing page says who is where.** "2 people here" beside a project is
the feature that stops the surprise, and it needs identity - which is where
`CardsGate` starts stamping the session the way `BrollGate` does (mint the
header, and strip any inbound copy of it first; `broll.py` §3 is the model
and the reason).

---

## 4. Phases

### Phase 1 - an engine per EPISODE, a landing page, a pool

Two people in two different episodes. On this fleet that is the common
case by a wide margin (Reproductive Rights and Framing Formosa, say).

* `cards.py` grows an engine **pool**: `{root_key: engine}`, built lazily on
  first entry, capped (`DASH_CARDS_ENGINES`, default **2**), evicted
  least-recently-used and after an idle timeout, each one stopped through the
  existing `stop_engine` path so its threads go with it.
* The cap is a refusal with a sentence, never a silent swap: *"two episodes
  are open and both are in use - ask Alex to leave one, or raise
  DASH_CARDS_ENGINES"*. A pool that quietly evicts the engine someone is
  editing is worse than a pool of one.
* `/cards` landing page: the roots under the vault, each with its cut files,
  who is in it, and what it is doing (loaded / loading / failed). One extra
  template in the dashboard; no engine required to render it.
* The session carries `cards_key`; `CardsGate` resolves it to the engine and
  routes. A request for a key with no engine and no room gets the refusal
  above, not a 500.
* **You drive your own Resolve, and only your own** (Alex, 2026-09-14:
  "users can only use companions which are also signed in to their own
  account"). See Phase 1a below: this replaces the global "who holds Resolve" lock,
  and it is both safer and simpler.
* `cards_exec.py` (the pinned-media executor) targets the engine that owns
  the root the job names, which it already knows - the job's paths are (root
  name, relative path) pairs by design (§4 of the port plan).

### Phase 1a - Resolve belongs to the account, not to the server

**The rule: a signed-in user may drive only the companions signed in to
their own account.** Alex's page drives Alex's Creator-1 and Razer;
Ruskin's page drives Ruskin's machine and nothing else. Nobody "holds"
Resolve fleet-wide, so nobody has to hand it over, and the second person is
never blocked by the first.

This is not new machinery - it is using the identity the tunnel already
verifies:

* `cards_tunnel.py` already overwrites the agent's self-asserted
  `socket.gethostname()` with the identity it verified, and names the agent
  `editor/MACHINE`: *"THE VERIFIED IDENTITY IS THE AGENT'S NAME ... the
  verified name, never `body.editor`"*. The editor half is already
  trustworthy: `api._require_fleet_caller` takes it from **the dashboard's
  own signed identity token**, not from the report token - *"the only name
  allowed to decide anything"*.
* So an engine's live seam filters agents by that editor half against the
  session's user. What changes is a comparison and a scope, not a protocol.

What it means concretely:

* An agent whose editor is not you **does not appear** on your page - not
  greyed, not refused on click. A conform button that exists and always says
  no is a worse answer than one that is not there. The landing page may say
  "Ruskin is live on his own machine" as information, with nothing to press.
* **No admin override**, deliberately. An admin driving another editor's
  Resolve is a synthetic keystroke into a timeline they cannot see, which is
  the same objection §4.2 of the port plan makes to scheduling `conform` on
  another machine. If that is ever wanted it is a separate, explicit act
  with its own audit line, not a property of being an admin.
* **CR-68 still binds per machine**: one scriptapp client per machine. So one
  person with one editing machine is live in at most ONE project at a time -
  a second project they open is file-only, and says so naming their own other
  project rather than another person. That refusal is now about their own
  machine, which is a sentence that can actually be acted on.
* An editor with two machines (Alex: Creator-1 and Razer) can be live in two
  projects at once, one per machine. The engine pool makes that possible;
  this rule makes it legible.
* **Hardening that goes with it, not a blocker:** four machines still
  authenticate with the SHARED fleet report token (the dashboard says so at
  boot: *"0 use per-editor tokens"*). The identity binding above rests on the
  signed identity token and holds either way, but per-editor `cce1.` tokens
  are what make a stolen companion credential useless for one editor's
  machines. Mint them on Admin > Users and set
  `DASH_SHARED_REPORT_TOKEN_ENABLED=0` before this ships, so "your own
  account" means one thing at both ends.

### Phase 2 - two cut files of the SAME episode

Needs `LibraryEngine` by composition: one library per root, shared by N file
views. That is the other repo's core, it is where the Resolve bridge and the
media workers live, and it deserves its own plan rather than a paragraph in
this one. Phase 1 makes it optional rather than urgent.

---

## 5. What it costs, honestly

* **Memory is a measurement, not a guess.** Before any of this is built,
  measure one engine on Reproductive Rights (572 cards, 11 multicams) and on
  Framing Formosa (the 16-multicam one): RSS after load, after a sweep, and
  with the ffmpeg worker running. The cap and the default follow from that
  number. The container's limit is the constraint, and the dashboard - which
  is what tells the fleet whether their footage is syncing - has to win every
  argument with this feature.
* **Two sweeps, two ffmpeg workers.** Different roots, so different files,
  but the same CPU. The sweep is already throttled; the worker is one job at
  a time per engine, so the honest statement is "two engines can use two
  cores of the NAS", and the fleet job path exists precisely so heavy work
  does not run here.
* **The offline copy** (`15-offline.js`, the service worker) caches by URL.
  Per-project prefixes mean per-project offline copies, which is correct -
  but the SW's scope and its cache keys need a pass, and a stale copy of the
  old flat `/cards/` URL must not shadow the new one.
* **Every existing Cards test** runs the page at `/`; the suites that assert
  a URL shape (`test_page_golden.py`, `test_multi_window.js`,
  `test_offline_page.js`) need a prefix-aware pass, the way b-roll's mounted
  prefix test was written.
* **The deploy is unchanged**: still the snapshot of the other repo plus the
  dashboard image (`CARDS_DEPLOY.md`).

## 6. What this does NOT change

* Two people in one project: unchanged, still safe, still the normal way to
  work together.
* The agent/Resolve seam: still one machine, one client, one Resolve
  (CR-68). Nothing here makes conform concurrent ON ONE MACHINE, and §4.2 of
  the port plan still stands - `conform` and `resolve-edit` must never become
  schedulable. Two people conforming at once is two machines, each its
  owner's own (Phase 1a).
* `POST /cards/api/restart` stays refused at the gate.
* The mount stays tri-state and never fatal: a broken pool must not stop the
  dashboard booting.

## 7. The decision Alex has to make before this is built

1. **Phase 1 only, or phase 1 + 2?** Phase 1 is "two episodes at once" and is
   a few days. Phase 2 is "two cut files of one episode" and is a refactor of
   the other repo's core.
2. **How many engines?** 2 is the honest default for one NAS container. 3 if
   the memory measurement says so.
3. ~~Who gets Resolve?~~ **Decided 2026-09-14**: nobody "gets" it. You
   drive the companions signed in to your own account and no others (Phase 1a).
   The remaining sub-question, if you want it: should an editor's page show
   that someone ELSE is live on their own machine (information, nothing to
   press), or show nothing at all? The plan assumes the first.
