"""Pure status-rollup logic. Precedence everywhere: red > amber > green.

An editor's dot answers "do I need to chase this person": red means broken or
stuck (lane error, offline while behind, or the data itself has gone stale),
amber means work in flight, green means fully synced and quiet.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from .db import age_seconds

GREEN = "green"
AMBER = "amber"
RED = "red"

_ORDER = {GREEN: 0, AMBER: 1, RED: 2}

OFFLINE_RED_SECONDS = 15 * 60
STALE_COMPLETION_SECONDS = 5 * 60
STALE_REPORT_SECONDS = 5 * 60

# UX-2 (resilience sweep 2026-08-28). There are three one-click ways for an
# editor to stop syncing for ever -- Settings -> WIRED TO THE SERVER (which
# writes sync_enabled=False), SIGN OUT (which stops the lanes AND the
# reporting, because editor_identity() then returns None) and Quit -- and an
# editor who was CAUGHT UP when they clicked has behind=False, so neither the
# offline branch nor the stale-completion branch below fires. The dot the
# owner scans stayed GREEN for a machine that had been dark for a week.
#
# So freshness is its own rule, independent of `behind`: a companion reports
# every 30 s, so 15 minutes of silence is already three times the staleness
# the lane chips redden at, and six hours is a machine nobody is going to
# notice any other way.
STALE_EDITOR_AMBER_SECONDS = 3 * STALE_REPORT_SECONDS
STALE_EDITOR_RED_SECONDS = 6 * 60 * 60


def worst(statuses: Iterable[str]) -> str:
    result = GREEN
    for s in statuses:
        if _ORDER.get(s, 0) > _ORDER[result]:
            result = s
    return result


def presence_status(mode: str, nas: Mapping[str, int], have: Mapping[str, int]) -> str:
    """Role-aware media-presence color for one editor on one project.

    Remote editors are *meant* to have proxies but not originals, so
    proxy-only is green; missing proxies (with proxies existing on the NAS)
    is amber. The base rig is meant to hold the originals, so missing
    originals is red. `nas` and `have` are {n_originals, n_proxies} counts.
    """
    nas_orig = nas.get("n_originals", 0)
    nas_prox = nas.get("n_proxies", 0)
    have_orig = have.get("n_originals", 0)
    have_prox = have.get("n_proxies", 0)
    if mode == "base":
        if nas_orig and have_orig < nas_orig:
            return RED           # the authoritative copy is incomplete
        return GREEN
    # editor: proxies are what matters; originals optional (proxy-only is fine)
    if nas_prox == 0:
        return GREEN             # nothing to pull yet
    if have_prox >= nas_prox:
        return GREEN
    if have_prox == 0:
        return AMBER             # not started
    return AMBER                 # partial


def is_proxy_only(have: Mapping[str, int]) -> bool:
    return have.get("n_originals", 0) == 0 and have.get("n_proxies", 0) > 0


def report_freshness(last_report_at: str | None, now: str) -> tuple[str, str | None]:
    """(colour, reason) for how long ago this machine's companion last reported.

    `last_report_at` None means "this device has no companion row at all",
    which is NOT an amber machine -- it is an unmapped Syncthing device, and
    the grid says so with its own `unmapped` flag. Anything else is measured:
    a timestamp that will not parse comes back AMBER with the reason naming
    it, never green (UX-2, resilience sweep 2026-08-28).
    """
    if last_report_at is None:
        return GREEN, None
    try:
        age = age_seconds(last_report_at, now)
    except (ValueError, TypeError):
        return AMBER, "the last report time on record cannot be read"
    if age >= STALE_EDITOR_RED_SECONDS:
        return RED, f"no report since {last_report_at}"
    if age >= STALE_EDITOR_AMBER_SECONDS:
        return AMBER, f"no report since {last_report_at}"
    return GREEN, None


def editor_status(
    *,
    completion: float | None,
    need_items: int | None,
    connected: bool,
    last_connected_at: str | None,
    completion_updated_at: str | None,
    syncthing_reachable: bool,
    lanes: Iterable[Mapping[str, Any]] = (),
    now: str,
    last_report_at: str | None = None,
) -> str:
    """Status of one editor device within one project.

    `lanes` are this editor's lane_report_current rows (any project -- lane
    A/B state is per-editor, not per-project).

    `last_report_at` is when that companion last reported at all. It is read
    INDEPENDENTLY of `behind` (UX-2): an editor who was caught up when they
    signed out, quit, or set the machine to WIRED TO THE SERVER is behind
    nothing and connected to nothing, and every other branch here says green.
    """
    lane_states = [l["state"] for l in lanes]
    if "error" in lane_states:
        return RED

    freshness, _reason = report_freshness(last_report_at, now)
    if freshness == RED:
        return RED

    behind = bool(need_items) or (completion is not None and completion < 100)
    if behind and not connected:
        if last_connected_at is None or age_seconds(last_connected_at, now) >= OFFLINE_RED_SECONDS:
            return RED
    if (
        syncthing_reachable
        and completion_updated_at is not None
        and age_seconds(completion_updated_at, now) >= STALE_COMPLETION_SECONDS
    ):
        return RED

    if behind or "syncing" in lane_states or freshness == AMBER:
        return AMBER
    return GREEN


def project_status(editor_statuses: Iterable[str]) -> str:
    return worst(editor_statuses)


def fleet_status(project_statuses: Iterable[str]) -> str:
    return worst(project_statuses)


def lane_chip_status(lane: Mapping[str, Any], now: str) -> str:
    """Dot color for a single reported lane, factoring in report freshness."""
    if lane["state"] == "error":
        return RED
    if age_seconds(lane["received_at"], now) >= STALE_REPORT_SECONDS * 3:
        return RED  # companion silent for 15+ minutes
    if lane["state"] == "syncing":
        return AMBER
    return GREEN


# --------------------------------------------------------------- SYS-1: stall
#
# SYS-1 (resilience sweep 2026-08-28). "No error" was rendered as green fleet
# wide: a lane in `syncing` was unconditionally AMBER for as long as it liked,
# so leso's MacBook sat at `state=syncing, transferring=1, last_error=NULL`
# for 2 h 20 m with nothing moving and lane B never getting its turn (CR-91b).
# The contract is one sentence: a state may not be green or amber without a
# monotonic progress token and the time it last changed.
#
# The clock is the SERVER's -- machine_state/lane_report_current record the
# received_at of the first report that carried the CURRENT token -- because
# the thread a companion-side watchdog would run on is precisely the one the
# fault wedges, and because a wrong clock on the machine must not be able to
# hide a stall (SYS-4).
LANE_STALL_FLOOR_SECONDS = 30 * 60
LANE_STALL_ROTATIONS = 3
# States in which nothing is expected to move, so there is nothing to stall.
# `paused` is a latch a human clears (the breaker, a disk floor) and carries
# its own chip; `error` is already red.
LANE_TERMINAL_STATES = frozenset({"idle", "error", "paused"})


def lane_stall(
    state: str,
    progress_token_since: str | None,
    now: str,
    rotation_seconds: float | None = None,
) -> float | None:
    """Seconds a non-terminal lane has gone without moving its token, or None.

    None is NO VERDICT, deliberately, in three cases: a terminal state, a
    companion too old to send a token at all (every machine in the field on
    the day this shipped), and a timestamp that will not parse. It is not
    "fine" -- report freshness and the lane's own state still answer for the
    row, and a machine that has stopped reporting reddens on that instead.
    What it must not do is turn an upgrade window into a red fleet.

    BYTES, not wall clock: the token changes whenever real work happened, so
    a genuinely slow 40 GB file over a thin uplink is not a stall.
    """
    if state in LANE_TERMINAL_STATES:
        return None
    if not progress_token_since:
        return None
    try:
        age = age_seconds(progress_token_since, now)
    except (ValueError, TypeError):
        return None
    limit = LANE_STALL_FLOOR_SECONDS
    if rotation_seconds:
        limit = max(LANE_STALL_ROTATIONS * float(rotation_seconds), limit)
    return age if age > limit else None


def lane_stall_detail(seconds: float) -> str:
    return f"syncing, no progress for {int(seconds // 60)} min"


def lane_chip(
    lane: Mapping[str, Any], now: str, rotation_seconds: float | None = None
) -> tuple[str, str | None]:
    """(colour, reason) for a single reported lane.

    Split out of lane_chip_status (which stays the colour-only view every
    older caller wants) so the stall can say WHY in one sentence: a red dot
    with no words is what CR-91b's two hours looked like on this page.
    """
    if lane["state"] == "error":
        return RED, lane.get("last_error") or None
    if age_seconds(lane["received_at"], now) >= STALE_REPORT_SECONDS * 3:
        return RED, "this companion has been silent for 15 minutes or more"
    stalled = lane_stall(
        lane["state"], lane.get("progress_token_since"), now, rotation_seconds)
    if stalled is not None:
        return RED, lane_stall_detail(stalled)
    if lane["state"] == "syncing":
        return AMBER, None
    return GREEN, None


def lane_chip_status(
    lane: Mapping[str, Any], now: str, rotation_seconds: float | None = None
) -> str:
    """Dot color for a single reported lane, factoring in report freshness."""
    return lane_chip(lane, now, rotation_seconds)[0]


# ----------------------------------------------------------- SYS-5 / UX-1: disk
#
# SYS-5 (resilience sweep 2026-08-28). Free space was invisible to the sync
# path and absent from the report, so a full drive showed as red dots with no
# cause and the owner's first question ("why?") had no answer on any page.
# Both a PERCENTAGE and an ABSOLUTE floor, because neither alone is right: 8 %
# of 8 TB is still 640 GB of headroom, and 60 GB free on a 500 GB laptop is
# one project away from unusable.
DISK_AMBER_PERCENT = 10.0
DISK_RED_PERCENT = 5.0
DISK_AMBER_FREE_BYTES = 50 * 1024 ** 3
DISK_RED_FREE_BYTES = 20 * 1024 ** 3


def disk_status(
    free_bytes: int | None, total_bytes: int | None
) -> tuple[str, float | None]:
    """(colour, percent free) for one machine's sync drive.

    GREEN with a None percentage is "this companion did not tell us", which
    the grid renders as no chip at all rather than as a reassurance: an older
    build sends no disk section, and inventing a green DISK chip for it would
    be the "could not check rendered as fine" mistake.
    """
    if free_bytes is None:
        return GREEN, None
    if not total_bytes:
        return GREEN, None
    percent = 100.0 * float(free_bytes) / float(total_bytes)
    if percent < DISK_RED_PERCENT or free_bytes < DISK_RED_FREE_BYTES:
        return RED, percent
    if percent < DISK_AMBER_PERCENT or free_bytes < DISK_AMBER_FREE_BYTES:
        return AMBER, percent
    return GREEN, percent


def _round_bytes(n: float) -> str:
    """Bytes as one figure a person reads out loud. ui.human_bytes' twin,
    duplicated on purpose: health.py is imported BY the view layer and must
    not import it back."""
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            break
        value /= 1024
    if unit == "GB" and value >= 1024:
        return f"{value / 1024:.1f} TB"
    return f"{value:.0f} {unit}"


# UX-1: warn once the tick is within this much of filling the drive, or once
# it is more than half of what is left. Below that the sentence is noise, and
# a confirm dialog nobody reads is worse than none.
CAPACITY_WARN_FRACTION = 0.5


def capacity_warning(
    project_label: str,
    proxy_bytes: int | None,
    machine: str,
    free_bytes: int | None,
) -> str | None:
    """UX-1: what ticking this project onto this computer costs, in one line.

    None when either figure is unknown (no NAS inventory yet, or a companion
    too old to report its disk) -- the tick still goes through. This REFUSES
    NOTHING by design: the owner may know something the dashboard does not
    (a drive about to be emptied, a project whose proxies are mostly stale).
    It just must never be silent about 4 TB onto a 500 GB laptop.
    """
    if not proxy_bytes or free_bytes is None:
        return None
    fits_with_room = (
        proxy_bytes + DISK_RED_FREE_BYTES <= free_bytes
        and proxy_bytes < free_bytes * CAPACITY_WARN_FRACTION
    )
    if fits_with_room:
        return None
    sentence = (f"{project_label} is {_round_bytes(proxy_bytes)} of proxies. "
                f"{machine} has {_round_bytes(free_bytes)} free.")
    if proxy_bytes > free_bytes:
        sentence += " That is more than will fit."
    return sentence


# ------------------------------------------------------------------ SYS-7
#
# "Why is my footage not syncing" had an answer on the machine and no route to
# the person asking (resilience sweep 2026-08-28). Every state below is
# already computed somewhere -- the breaker in lane_guard, the halt in a latch
# file, the root guard's answer, the plan in `selections`, the skew in v30's
# column, the disk in v32's -- and not one of them was ever composed into a
# sentence. The owner opened the fleet grid, which said amber, and then
# messaged the editor.
#
# ONE function, ordered by what actually goes wrong here, so the fleet grid,
# the editor's own home view and the diagnostics page all say the same thing.
# The order is the wire contract's `sync_guard.blocked.reason` order, first
# match wins, with `upload_only` inserted where SYS-7's tree puts it: after
# the plan questions and before the stall, because a machine that is MEANT to
# be idle must never be read as a machine that has stopped (CR-85).

WHY_ORDER: tuple[str, ...] = (
    "not_signed_in",
    "licence_pending",
    "clock_skew",
    "root_absent",
    "root_not_answering",
    "root_misplaced",
    "disk_full",
    "fleet_halt",
    "local_halt",
    "paused",
    "breaker_tripped",
    "no_selection",
    "folders_unfiltered",
    # Not a `blocked.reason` any companion sends: it is a PLAN fact the
    # dashboard owns (docs/UPLOAD_ONLY_TICK.md), and the only entry here that
    # is not a fault.
    "upload_only",
    "lane_stalled",
    "syncthing_down",
    "transport_offline",
)

# The reasons that are NOT red. why_not_syncing answers for them anyway:
# "nothing is coming down and that is correct" is exactly as much of an answer
# as a fault is, and leaving it out is what makes an admin chase an
# upload-only machine. The caller colours by membership here, never by the
# mere presence of a sentence.
WHY_INFORMATIONAL = frozenset({"upload_only"})

# One minute is already twice lane B's `--min-age 60s`, and a clock that far
# out makes the pass exclude every file on the NAS and exit 0 (SYS-4).
CLOCK_SKEW_WHY_SECONDS = 60.0

_LANE_WORDS = {
    "A": "upload",
    "lane_a_video_up": "upload",
    "B": "proxy download",
    "lane_b_proxy_down": "proxy download",
    "C": "folder sync",
    "lane_c_syncthing": "folder sync",
    "express": "express upload",
}


def _why_get(row: Mapping[str, Any], key: str) -> Any:
    """One lookup over a fleet-grid row and its nested `guard` block.

    build_editors_view puts the flattened machine_state columns under `guard`
    and the row-level facts (plan, mode, verified) at the top level; a caller
    holding a bare machine_state row has them all flat. Both are legitimate
    shapes here, so neither is assumed."""
    if key in row:
        return row.get(key)
    guard = row.get("guard")
    if isinstance(guard, Mapping):
        return guard.get(key)
    return None


def _duration_words(seconds: Any) -> str:
    """"47 minutes" / "3 hours". Plain words rather than the `eta` filter:
    this string ends up inside one sentence an editor reads, and that filter
    is built for a countdown."""
    try:
        total = int(abs(float(seconds)))
    except (TypeError, ValueError):
        return "an unknown time"
    if total < 90:
        return f"{total} second{'' if total == 1 else 's'}"
    minutes = total // 60
    if minutes < 90:
        return f"{minutes} minute{'' if minutes == 1 else 's'}"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} hour{'' if hours == 1 else 's'}"
    return f"{hours // 24} days"


def _lane_words(lane: Any) -> str:
    key = str(lane or "").strip()
    return _LANE_WORDS.get(key) or _LANE_WORDS.get(key.upper()) or "a sync lane"


def _why_sentence(code: str, row: Mapping[str, Any]) -> str:
    """The one plain sentence for `code`. No em dashes: an editor reads this."""
    if code == "not_signed_in":
        return "Not syncing: this computer is not signed in"
    if code == "licence_pending":
        return ("Not syncing: the licence agreement has not been accepted on this "
                "computer yet")
    if code == "clock_skew":
        skew = _why_get(row, "clock_skew_seconds")
        if skew is None:
            return ("Not syncing: this computer's clock is too far out from the "
                    "server, so proxy download transfers nothing")
        return (f"Not syncing: this computer's clock is {_duration_words(skew)} out "
                f"from the server, so proxy download transfers nothing")
    if code == "root_absent":
        return "Not syncing: the sync drive is not there on this computer"
    if code == "root_not_answering":
        return ("Not syncing: the sync drive is mapped but not answering, so nothing "
                "can be read or written")
    if code == "root_misplaced":
        return "Not syncing: the sync drive is pointing at the wrong place"
    if code == "disk_full":
        free = _why_get(row, "disk_root_free_bytes")
        return (f"Not downloading proxies: the drive has {_round_bytes(free)} free"
                if free is not None else
                "Not downloading proxies: the drive is out of space")
    if code == "fleet_halt":
        return "Not syncing: an admin has halted syncing for the whole fleet"
    if code == "local_halt":
        return "Not syncing: syncing has been stopped on this computer"
    if code == "paused":
        return "Not syncing: syncing is paused on this computer"
    if code == "breaker_tripped":
        return ("Not downloading proxies: proxy download stopped itself and needs a "
                "person to check the server")
    if code == "no_selection":
        return "Nothing to sync: no project is ticked for this computer"
    if code == "folders_unfiltered":
        count = _why_get(row, "folders_unfiltered")
        if count:
            return (f"Not syncing safely: {count} shared folder(s) on this computer "
                    f"have no ignore filter yet")
        return ("Not syncing safely: a shared folder on this computer has no ignore "
                "filter yet")
    if code == "upload_only":
        return "Nothing to download: this project is upload-only on this computer"
    if code == "lane_stalled":
        lane = _lane_words(_why_get(row, "stalled_lane"))
        seconds = _why_get(row, "stalled_seconds")
        if seconds is None:
            return f"Not syncing: {lane} is busy but nothing is moving"
        return (f"Not syncing: {lane} has been busy for {_duration_words(seconds)} "
                f"with nothing moving")
    if code == "syncthing_down":
        return "Not syncing: the sync engine on this computer is down"
    if code == "transport_offline":
        return "Not syncing: this computer cannot reach the server"
    # A reason a NEWER companion knows and this build does not. Named, not
    # swallowed: silence here would render as "fine", which is the whole
    # mistake SYS-7 exists to end.
    return ("Not syncing: this computer reported a reason this dashboard is too old "
            "to explain")


def why_not_syncing(
    row: Mapping[str, Any], now: str | None = None
) -> tuple[str, str] | None:
    """(reason_code, one sentence) for why this machine is not syncing, or None.

    PURE. `row` is a fleet-grid row from build_editors_view (or a bare
    machine_state row); every field is read defensively, because this has to
    answer correctly for a machine whose companion is three releases old and
    against a database whose newest columns have not landed yet.

    THE COMPANION'S OWN ANSWER WINS when the report carried one
    (`sync_guard.blocked`, SYNC-15): it can see the root guard's fourth
    answer, the licence park and its own transport, none of which reach a
    column here. This dashboard's derivation is the fallback, and it is
    deliberately a SUBSET -- a reason this side cannot evidence is not
    guessed at.

    None means "no reason found", which is NOT "syncing fine" and must never
    be rendered as a green claim; it is the absence of a sentence.
    """
    reported = str(_why_get(row, "blocked_reason") or "").strip()
    if reported:
        code = reported if reported in WHY_ORDER else "blocked"
        sentence = _why_sentence(code, row)
        detail = str(_why_get(row, "blocked_detail") or "").strip()
        # The companion's detail is APPENDED, never substituted: the sentence
        # is the product's words and the detail is the machine's (a path, an
        # errno, a folder name). A detail long enough to be a paragraph is a
        # diagnostics bundle's job, not a grid line.
        if detail and len(detail) <= 120 and detail.lower() not in sentence.lower():
            sentence = f"{sentence} ({detail})"
        return code, sentence

    if _why_get(row, "verified") is False:
        return "not_signed_in", _why_sentence("not_signed_in", row)

    skew = _why_get(row, "clock_skew_seconds")
    try:
        if skew is not None and abs(float(skew)) >= CLOCK_SKEW_WHY_SECONDS:
            return "clock_skew", _why_sentence("clock_skew", row)
    except (TypeError, ValueError):
        pass

    # The disk chip's own RED, not a second threshold to reconcile (SYS-5).
    if disk_status(_why_get(row, "disk_root_free_bytes"),
                   _why_get(row, "disk_root_total_bytes"))[0] == RED:
        return "disk_full", _why_sentence("disk_full", row)

    halt_active = bool(_why_get(row, "halt_active"))
    if bool(row.get("fleet_halt_active")) or (
            halt_active and str(_why_get(row, "halt_scope") or "") == "fleet"):
        return "fleet_halt", _why_sentence("fleet_halt", row)
    if halt_active:
        return "local_halt", _why_sentence("local_halt", row)

    if _why_get(row, "breaker_tripped"):
        return "breaker_tripped", _why_sentence("breaker_tripped", row)

    # A base rig holds no tick BY DESIGN (CR-28): it works directly off the
    # NAS tree, so "no project is ticked" is the correct state there, and
    # saying it in red is what put a permanent GETTING READY chip on this
    # page. `plan` absent (an older caller) skips both plan branches rather
    # than guessing at either.
    plan = row.get("plan") if isinstance(row.get("plan"), Mapping) else None
    is_base = str(_why_get(row, "mode") or "").strip().lower() == "base"
    if plan is not None and not is_base and not plan.get("count"):
        return "no_selection", _why_sentence("no_selection", row)

    if _why_get(row, "folders_unfiltered"):
        return "folders_unfiltered", _why_sentence("folders_unfiltered", row)

    if (plan is not None and not is_base
            and not plan.get("full") and plan.get("upload_only")):
        return "upload_only", _why_sentence("upload_only", row)

    # The stall, from either end: the companion's own detector (which killed
    # the pass) or this server's token watch (SYS-1's lane_stall, already on
    # the lane chips by the time this runs).
    if _why_get(row, "stalled_lane") or _why_get(row, "stalled_seconds"):
        return "lane_stalled", _why_sentence("lane_stalled", row)
    if now:
        for lane in row.get("lanes") or []:
            if not isinstance(lane, Mapping):
                continue
            stalled = lane_stall(str(lane.get("state") or ""),
                                 lane.get("progress_token_since"), now)
            if stalled is None:
                continue
            return "lane_stalled", (
                f"Not syncing: {_lane_words(lane.get('lane') or lane.get('label'))} "
                f"has been busy for {_duration_words(stalled)} with nothing moving")

    if _why_get(row, "supervisor_down_since"):
        return "syncthing_down", _why_sentence("syncthing_down", row)

    return None
