# Verifier med-13 (2026-09-25): logic-cards-1, logic-cards-2, logic-cards-3

Judged against HEAD (`git show HEAD:...`). Probe: HEAD's `cards_pool.py` and
`cards_landing._close_prompt` / `_last_in_phrase` copied to the scratchpad and
driven from the dashboard venv with a fake build callable (no repo file, no
live process touched). No prior KNOWN_BUGS or earlier-hunt entry for any of
the three (`grep -a` for `may_close`, `note_agent`, `_where`).

## logic-cards-1 - CONFIRMED (medium)

The mechanism holds exactly. `may_close` (HEAD cards_pool.py:459-463) returns
"" for any editor who appears in `occupants`, including when somebody else is
listed too; probe: occupants `['alex', 'ruskin']`, `may_close(slug, "ruskin",
False) == ''`. The confirm is built from `Entry.last_in()`, the most recent
stamp, which is the presser: the probe prints "Close Framing Formosa? ruskin is
in it now. ..." with alex (in it 2 min earlier) never named. This contradicts
stated intent in two places at HEAD: the `cards_close` docstring ("an admin is
still the only person who can" take an episode from whoever is in it) and the
landing template's Who-column comment ("another person being live here is
something to know, never something to take"). The `may_close` docstring's
"an episode they are themselves an occupant of" reads as written for the
solo case; test_cards_pool.py:557-562 never tests two occupants. Medium is
right: a non-admin can drop an engine a colleague is actively editing in,
after a confirm that hides the colleague, but the cut file is on disk and the
offline-browser buffer survives, so no data loss.

## logic-cards-2 - CONFIRMED (medium)

`local_engine` (HEAD cards_tunnel.py:143-157) calls `pool.note_agent(editor)`
on every agent call that routes to an engine, and `note_agent` stamps
`seen[editor]` on the slug in `_where[editor]`, which only `drop()` /
`stop_all()` clear. The companion role long-polls `/agent/pending` for as
long as the tray runs (timeline_cards_role.py `_loop` / `call`), regardless
of whether any page is open. Probe: an entry whose only page stamp was 3 h
old read `occupants == []` and closable by ruskin; after one
`note_agent("bob")` it read `['bob']` and `may_close(..., "ruskin", False)`
refused. So for any editor with the Cards role on, the 15-minute idle release,
the cap refusal's "nobody in the last 15 min" branch and the Who column never
lapse while their companion is up. The security-1 intent was to protect an
OFFLINE editor, and an agent poll cannot tell that apart from an editor who
left hours ago; this is a real side effect of that fix, returning the
"only an admin can free the seat" state security-2 set out to end. Medium
matches security-2's own rating; the practical reach is limited to machines
with `cards_agent` on (the base rig at least, since CR-226).

## logic-cards-3 - DOWNGRADE (low), largely a duplicate of bug-dash-cards-jobs-2

Every mechanism is real: `_where` is one slot per editor (HEAD
cards_pool.py:285, :324-357), so all of one editor's agents (Creator-1 and
Razer) route to one engine, which contradicts CARDS_TWO_PROJECTS.md 1a ("An
editor with two machines can be live in two projects at once"); and
`cards_open` calls `note_visit` on a still-LOADING entry (cards_landing.py:224),
so `engine_for` answers None for the whole build (probe: `engine_for("alex")`
was the ready engine, then None with B `loading`). But the harmful half is the
same root cause, and largely the same scenario, as wave 1's
bug-dash-cards-jobs-2 (per-editor `_where` overwritten by every served
request): in the hunter's own scenario Alex's laptop page on Repro Rights
keeps polling through the mount, and each of those requests calls
`note_visit` and flips `_where` back within seconds, so the "detached for the
whole build" window only lasts that long when no page of his is open, in which
case following the last episode opened is the design's own rule. Fixing
jobs-2 by routing on (editor, machine) removes the two-machine half too. What
is left that jobs-2 does not cover is the landing copy ("One episode at a time
per person" is neither enforced nor true, and the page never says Resolve
follows the last episode opened) and the `/cards/open` stamp on a LOADING
entry, both low.
