r"""The requester's own machine as the YouTube download executor (plan §7).

docs/YTDL_LOCAL_DOWNLOAD.md is the design; this is its companion half. The
short version, from the 2026-08-13/14 incident: bulk anonymous downloads out of
the NAS's one datacentre IP is exactly YouTube's bot-check profile (five clips
failed outright on 2026-08-13, and the fleet had already been cut off at 112
metadata calls on 2026-08-11), while an editor fetching their own reviewed
selections from a residential IP is not -- and the requester's clips then land
on the requester's disk with no sync hop to wait for.

The flow, all of it started by ONE job id arriving on the loopback (§2):

    SPA -> POST 127.0.0.1:8899/ytdl/download {job_id}
        -> claim        (fleet token; the server flips download_mode=local)
        -> manifest     (what to fetch, where it goes, under which contract)
        -> yt-dlp per clip, status posted per clip, heartbeat every 30 s
        -> the last clip hands the job back; the server sweeps what failed

Rules that are not negotiable here:

  - **THE BROWSER CONTRIBUTES A JOB ID AND NOTHING ELSE** (§8). Paths, URLs,
    quality and the naming template all arrive from the server under the fleet
    token. This is /music/send's principle ("never trust the page with paths")
    extended to never trusting it with the work order either.
  - **ANY 410 IS THE END OF THE JOB, QUIETLY.** routes_fleet answers 410 to
    every way a lease can be over -- it expired and the server reclaimed the
    job, another editor holds it, the job finished. The companion's answer to
    all of them is identical: stop, delete its own partials, say nothing to
    the editor. Reclaim is one-way (§3): no retry, no ping-pong, no error UI.
  - **NAMING IS A CONTRACT** (§5). The outtmpl, the sidecar and the
    quality-fallback rung come from the vendored `ytdl_common`, which is
    byte-identical to the server's copy. Divergence is silent data skew in one
    canonical tree -- two spellings of the same clip, found months later.
  - **NEVER RAISE INTO THE TRAY.** Everything here runs on a daemon thread and
    swallows its own failures: a machine that cannot download locally is a
    machine that downloads the way the whole fleet did before this existed.

Scope cut, deliberate and documented (see SCOPE_QUALITIES): only 480p/720p/
1080p are executed locally. Since CR-79 (2026-08-25) a clip that lands here
is ffprobed and, when it is not H.264/AAC/CFR, converted ON THIS MACHINE with
the vendored downloader's own ffmpeg command and swap-in rule
(ensure_edit_ready -> `_ensure_edit_ready`), so the naming objection the
0.8.0 cut rested on is gone: the converted file takes the ORIGINAL name, and
`.editready` was only ever the locked-file fallback. The rungs above 1080p
stay server-side for a different reason now, a CPU one (SCOPE_QUALITIES).

Added 2026-08-14 (companion 0.8.0).

2026-08-26, CR-80 and docs/YTDL_RESILIENCE_PLAN.md WP2/WP3/WP4: a clip is
downloaded ANONYMOUSLY first and the editor's cookie jar is spent only on the
one failure it answers (a bot check), because an unconditional jar is what
made one flagged Google account fatal to every download this machine could
make; no player client is pinned any more, because a pinned client is a
pinned bug waiting to happen; and N identical failures in a row end this
machine's turn instead of grinding through the rest of the job.
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Optional

from . import canon
from . import config as config_mod
from . import ffmpeg_tools
from . import machine as machine_mod
from . import resolve_bridge
from . import root_guard
from . import ui_copy
from . import upgrade as upgrade_mod
from . import sidecar_tools
from . import ytdl_attestation
from . import ytdl_common
from . import ytdl_cookies
from . import ytdlp_manager
from .sync.repath import normalized_safe_rel

log = logging.getLogger("ccsync.ytdl")

# The dashboard's fleet API for this feature. One prefix, so a deployment that
# moved the ytdl mount is one edit.
API_PREFIX = "/ytdl/api"

# What this executor will run itself. Until CR-79 (2026-08-25) the reason
# given for stopping at 1080p was a NAMING one -- "the server's converted
# deliverable is `<stem>.editready.mp4`, which the CLI cannot reproduce" --
# and that was a misreading of vendor/downloader._swap_in: the converted file
# REPLACES the download under its original name, and `.editready` survives
# only when Windows holds the original open. This executor now runs the same
# probe-and-convert (`_ensure_edit_ready`), so nothing here is unreproducible
# any more. What still keeps 1440p/2160p/`best`/`audio` on the server is
# cost: YouTube serves nothing above 1080p as AVC, so every one of those is a
# guaranteed full libx264 re-encode of a 4K VP9/AV1 stream on an editor's
# laptop, minutes to hours at 100% CPU while they edit. Widening this tuple
# is the whole change if the owner wants it; the machinery is in place.
SCOPE_QUALITIES = ("480p", "720p", "1080p")

# yt-dlp's own in-flight litter, matched as a SUFFIX. Worker parity
# (worker._SWEEPABLE / _sweepable, YTDL-17): `'.part' in name` also matched a
# video whose TITLE contains ".part", and `.editready` is deliberately absent
# because it is a deliverable, not a leftover.
SWEEPABLE_SUFFIXES = (".part", ".ytdl", ".temp")

# The file yt-dlp has FINISHED writing but has not merged yet, matched on the
# STEM. COMP-BROLL-3 (2026-08-14): every rung this executor runs is a
# `bestvideo+bestaudio` selector, so yt-dlp renames `... [id].f137.mp4.part` to
# `... [id].f137.mp4` the moment that stream completes and KEEPS it (for
# resume) if anything after it fails. Nothing on the machine deleted it: it is
# not a suffix above, `landed_file` correctly refuses to read it as the clip,
# and it matches lane A's `+ *.mp4` include and no stignore line -- so a laptop
# lid closed at clip 7 put a 1.4 GB video-only orphan on the NAS and on every
# editor with that project ticked, permanently. `.temp` is the same file half a
# second later (FFmpegMergerPP writes `... [id].temp.mp4`).
#
# A deliverable can never match: the outtmpl ends every finished name in
# `[id].<ext>`, so its stem ends in `[id]`, and both callers are id-scoped to
# that segment anyway.
#
# `.editready` joined them in YT-6 (2026-08-28). It could not before: it was
# also _swap_in's fallback DELIVERABLE, so sweeping it deleted the only copy
# of the clip (YTDL-17). The deliverable is `converted_name` now, whose stem
# still ends in `[id]`, which frees the `.editready` name to mean what it
# always looked like it meant -- ffmpeg's half-written output. A truncated one
# from a killed container or a closed lid was otherwise never swept, never
# disowned, and still matched lane A's `+ *.mp4`.
#
# `.original` is deliberately NOT here: it is a whole real download that
# swap_in could not delete because Resolve had it open, and the id-scoped
# retry (clear_aside_originals) is what tries again. An age-based folder sweep
# deleting footage is not a thing this module does.
_INTERMEDIATE_STEM_RE = re.compile(r"\.(f\d+|temp|editready)$")

# What a failed attempt's leftovers are RENAMED to, rather than deleted --
# worker.DISOWNED_SUFFIX and _disown_output, verbatim rule (YTDL-3,
# 2026-08-11). A half-converted original is still footage somebody may want and
# the disk cost should be visible, but under its real name it carries the
# `[id]` the disk-scan dedupe reads: every later search would call the clip
# "already in the fleet" and point the editor at a file they cannot open. The
# suffix also takes it out of lane A's video-extension include, so a disowned
# corpse stays on the machine that made it.
DISOWNED_SUFFIX = ".failed"

# The OTHER half of the naming contract (§5: "the outtmpl, the sidecar,
# EMBEDDED TAGS, ..."), which the 0.8.0 argv simply did not have -- COMP-BROLL-2
# (2026-08-14). vendor/downloader.py:137-155 embeds these on the NAS with a
# MetadataParser pre_process pass plus FFmpegMetadata, and its module header
# calls them "three redundant metadata channels" the downstream DaVinci Resolve
# credits script reads; without them a clip fetched by an editor and the same
# clip fetched by the NAS have IDENTICAL NAMES and different insides, which is
# exactly the silent skew §5 exists to prevent.
#
# Spelled as CLI equivalents because this side drives the standalone binary
# (§6): `--parse-metadata FROM:TO` IS MetadataParserPP.Actions.INTERPRET, and
# its default WHEN is pre_process -- the same pass, so FFmpegMetadata picks the
# tags up. The list is not in ytdl_common because it cannot drift: its source
# (`downloader._credits_action`, in a file vendored VERBATIM from
# yt-credit-downloader and never edited) is frozen, and tests/test_ytdl_executor
# pins this spelling against it.
CREDITS_METADATA_ARGS = (
    "--parse-metadata", "%(channel,uploader)s:%(meta_channel)s",
    "--parse-metadata", "%(webpage_url)s:%(meta_video_url)s",
    "--parse-metadata", "%(channel_url,uploader_url)s:%(meta_channel_url)s",
    "--parse-metadata", "%(uploader,channel)s:%(meta_uploader)s",
    # The two standard tags the same pass writes: channel -> artist,
    # url -> comment.
    "--parse-metadata", "%(channel,uploader)s:%(artist)s",
    "--parse-metadata", "%(webpage_url)s:%(meta_comment)s",
    # `--embed-metadata` is {'key': 'FFmpegMetadata', 'add_metadata': True}.
    # `--embed-chapters` is not redundant: FFmpegMetadataPP's own default for
    # add_chapters is True, so the server's one-key dict embeds chapters and
    # the CLI (which defaults that flag OFF) would not. With both flags, yt-dlp
    # 2026.08.04 builds {'key': 'FFmpegMetadata', 'add_chapters': True,
    # 'add_metadata': True, 'add_infojson': 'if_exists'} -- byte for byte the
    # postprocessor the NAS gets (measured 2026-08-14).
    "--embed-metadata",
    "--embed-chapters",
)

# Where yt-dlp's `--write-info-json` output goes. COMP-BROLL-1 (2026-08-14):
# it used to go where the video goes, which is a Syncthing SENDRECEIVE folder
# whose stignore ignores video extensions, `.part` and `.ytdl` but deliberately
# NOT `.json` (sidecars and manifest.json are meant to travel). yt-dlp writes it
# at extraction time, i.e. minutes before the media finishes, so every one of a
# 40-clip job's ~120 KB info jsons was indexed and fanned out to the NAS and to
# every other editor -- and since the 2026-08-11 delete-protection retrofit set
# ignoreDelete=true on editor folders, the executor deleting them afterwards
# never propagated. Permanent, undeletable litter, byte for byte the failure
# R15 fix 3 closed for `.part` files.
#
# Beside the sidecar manager's tools dir rather than inside it (that one holds
# binaries it owns), with the system temp dir as the fallback.
INFO_JSON_DIR_NAME = "ytdl-info"

# Where a clip may legitimately come from. Matched after `www.`/`m.` are
# stripped and by EQUALITY, routes_api._YT_HOSTS's rule: `youtube.com.evil.net`
# and `notyoutube.com` both have to fail, which a substring test does not do.
# googlevideo.com is YouTube's media CDN and is matched as a SUFFIX because its
# hosts are per-datacentre (`rr3---sn-abc.googlevideo.com`).
YOUTUBE_HOSTS = frozenset({
    "youtube.com", "music.youtube.com", "youtube-nocookie.com", "youtu.be",
})
YOUTUBE_HOST_SUFFIXES = (".googlevideo.com",)

# The YouTube player client an editor's machine asks as. UNPINNED since
# 2026-08-26 (CR-80, docs/YTDL_RESILIENCE_PLAN.md WP2): empty means send no
# --extractor-args at all, i.e. yt-dlp's own default client set.
#
# It was `web_safari` from CR-39 (2026-08-19) until then, because that was the
# one client an editor's machine could use without a GVS PO-token provider.
# Six weeks later it returns NO USABLE FORMATS at all, with or without
# cookies, on both the yt-dlp the fleet is running and the current one --
# measured on the base rig against the deployed companion's own binary.
# build_argv carries both tables.
#
# The rule those two measurements draw, and the reason this is now empty
# rather than a different client: A PINNED PLAYER CLIENT IS A PINNED BUG
# WAITING TO HAPPEN. Which client works is YouTube's to change and they change
# it every few weeks; yt-dlp's maintainers track that weekly and we do not, so
# every pin we carry is a pin we have taken on the job of keeping current, and
# CR-39 -> CR-80 is what that costs when we forget. `ytdl_player_client` stays
# as an OVERRIDE for the day a specific client is known-good and the default
# is not (_player_client) -- a lever that is not a release.
DEFAULT_PLAYER_CLIENT = ""

# ------------------------------------------------ anonymous first (WP3)
#
# Two failures with OPPOSITE remedies, which is why they are two classifiers
# and two messages rather than one "download failed" (plan WP3/WP4,
# 2026-08-26). The bot check says THIS MACHINE'S IP NEEDS AN ACCOUNT and its
# answer is to try the editor's jar; the account flag says THIS ACCOUNT IS
# REFUSED and its answer is to drop the jar. Spelled to match the server's
# worker._bot_checked / _account_flagged, because a clip that fails on an
# editor's machine is retried on the NAS and the two must read it the same way.
#
# Both apostrophes in the bot check, because yt-dlp passes YouTube's own text
# through and it has arrived either way -- the curly one as an escape so this
# file stays pure ASCII. Deliberately NOT the bare "sign in to confirm":
# "Sign in to confirm your age" is one age-gated video, not a challenged IP.
_BOT_CHECK_MARKERS = ("confirm you're not a bot",
                      "confirm you’re not a bot")
_ACCOUNT_FLAG_MARKERS = ("the page needs to be reloaded",)

# What the clip row says when NEITHER path can fetch it. Editor-facing: they
# cannot fix either half themselves, so it says what is happening and what it
# means rather than naming a knob (the server's BOTH_PATHS_NOTE names
# YTDL_COOKIES_FILE because an admin reads that one).
BOTH_BLOCKED_ERROR = (
    "both download paths are blocked on this machine: YouTube is asking the "
    "anonymous one to confirm it is not a bot, and it is refusing the "
    "signed-in session as well. Export a fresh cookies.txt from a different "
    "signed-in YouTube session, or let the server download this job.")

# The note that rides on the clip row when the FALLBACK is what landed it.
# The ordinary anonymous path is deliberately noteless: it is the default, and
# a note on every row is a note nobody reads.
COOKIES_PATH_NOTE = ("downloaded with the signed-in YouTube session "
                     "(the anonymous attempt was bot-checked)")

# How many consecutive clip failures with the SAME normalised signature end
# this machine's turn instead of grinding on (plan WP6, 2026-08-26). CR-80's
# job 28 discovered the same wall 29 times. 0 disables it; `config.toml`
# `ytdl_max_identical_failures` is the per-machine override, and it is not in
# config.DEFAULTS for the same reason `ytdl_player_client` is not: a knob for
# the machine that hits a false positive, not a setting to explain to every
# editor.
DEFAULT_MAX_IDENTICAL_FAILURES = 3

# The two failure signatures that mean "the binary, not the video" (plan WP4:
# five in a row is a client that no longer works). On this side the answer is
# not a note but an ACTION -- ask the sidecar manager to re-check the floor and
# update -- because CR-80's fleet half was exactly a yt-dlp too old to work
# and a floor it already satisfied.
_UPDATE_WORTH_TRYING = ("requested format is not available", "http error 403")

# HTTP to the dashboard. Short: every one of these calls is a small JSON
# round trip on the tailnet, and a wedged one must not outlive the lease it is
# there to hold (180 s).
HTTP_TIMEOUT_SECONDS = 15.0

# How long a fleet call keeps retrying a TRANSPORT failure before it gives up
# (CR-31, 2026-08-19). The dashboard container restarted mid-job -- a three
# second outage -- and the clip-status POST that landed in it raised
# ConnectionRefused, which propagated out of _download_all, out of run(), and
# ended the whole local download at clip 2 of 22. The lease then expired and
# the server reclaimed the job, so the remaining 20 clips downloaded onto the
# NAS, where lane B does not bring YouTube originals down: the editor lost
# their footage to a blip they never saw.
#
# Sized against the lease, not against patience. The server's lease is 180 s
# and the heartbeat thread renews it every 30 s, so the worst case is a lease
# that is already 30 s old when the retry starts: 30 + this budget + one final
# HTTP_TIMEOUT_SECONDS has to stay comfortably under 180. It is a budget on
# ELAPSED time rather than an attempt count for exactly that reason -- six
# attempts that each time out at 15 s is 90 s of wall clock, not six seconds.
#
# TRANSPORT failures only. An HTTP status is an ANSWER (default_request's rule)
# and 410 is the end of the job: retrying either of those is how a reclaim
# becomes a ping-pong.
CALL_RETRY_BUDGET_SECONDS = 60.0
CALL_RETRY_FIRST_BACKOFF = 2.0
CALL_RETRY_MAX_BACKOFF = 15.0

# One clip's whole yt-dlp run, merge included. Generous for an editor on a
# hotel link and a 1080p feature-length clip; bounded because an unbounded
# wait would hold the job's lease -- and therefore the server's fallback --
# forever. A timeout is reported as an ordinary clip failure, so the
# second-chance sweep picks it up (§2 step 7).
CLIP_TIMEOUT_SECONDS = 2 * 3600.0

# Fallbacks for what the server normally tells us. Both are config on the
# server (YTDL_LEASE_SECONDS / YTDL_HEARTBEAT_SECONDS, shipped as 180/30) and
# arrive in the claim response; these only cover a server that answered
# without them.
DEFAULT_HEARTBEAT_SECONDS = 30.0
DEFAULT_PAUSE_SECONDS = 3.0

# The free-space floor, checked BEFORE the claim (§7: "decline the claim,
# don't die at clip 40" -- the 0.7.x upgrade lesson). MIN_FREE_BYTES_MARGIN is
# imported rather than re-typed for the reason ytdlp_manager imports it: two
# copies of a number meaning "don't be the thing that fills an editor's disk"
# would drift. NOMINAL_JOB_BYTES is a FLOOR and not a forecast -- a reviewed
# selection is routinely 20-40 clips and a few GB, and nothing tells us the
# sizes up front, so this refuses on a disk that is already in trouble rather
# than pretending to predict the job.
MIN_FREE_BYTES_MARGIN = upgrade_mod.MIN_FREE_BYTES_MARGIN
NOMINAL_JOB_BYTES = 5 * 1024 * 1024 * 1024

# capabilities() reasons. Small, closed and editor-readable: the SPA shows
# nothing (it just falls back to the server path), but this is what the
# companion log says when an editor asks why their machine is not downloading.
REASON_DISABLED = ("the YouTube downloader is off for this site, or switched "
                   "off in config")
REASON_NO_DASHBOARD = "this machine has no dashboard URL or token configured"
REASON_NO_EDITOR = "nobody is signed in on this machine"
# H5 (2026-08-17): the fleet routes verify a SIGNED identity, so a machine
# with a name but no live token cannot claim anything. Distinct from
# REASON_NO_EDITOR because the fix is different -- that one is "sign in", this
# one is "sign in AGAIN" (a 30-day token that has run out).
REASON_NO_IDENTITY = ("this machine has no valid sign-in token -- sign in "
                      "again from the tray")
# COMMERCIAL_READINESS.md item 2 (2026-08-17). The editor has not accepted the
# rights/ToS attestation ON THIS MACHINE. Server-side acceptance is recorded
# per user and gates the browser; this is the per-machine half, because "this
# computer downloads other people's video" is a fact about the machine and
# whoever owns it.
# CYT-4 (sweep 2026-09-04): this one is read IN THE BROWSER, in its own
# louder toast, by an editor who then right-clicks the tray and finds no
# YouTube item at all - it moved into the Settings window on 2026-08-27.
REASON_NOT_ATTESTED = ("the YouTube terms have not been accepted on this "
                       f"computer: {ui_copy.YOUTUBE_TERMS}")
# COMP-BROLL-5 (2026-08-14). ffmpeg is an OPTIONAL dependency on this fleet
# (ffmpeg_tools.ffmpeg_available says so, and proxy_generation_enabled is
# tri-state for the same reason), but EVERY rung this executor runs is a
# `bestvideo+bestaudio` merge selector -- yt-dlp refuses those outright with no
# merger. Without this check a machine with no ffmpeg claimed the job, failed
# 100% of its clips, burned the editor's IP on the metadata calls anyway and
# left a history of red rows, which is the opposite of §6's promise that
# "editors never see a broken local downloader -- they see the old behaviour".
REASON_NO_FFMPEG = ("ffmpeg is not installed on this machine, so downloaded "
                    "video and audio cannot be merged")
# comp-ytdl-1 (2026-08-21). Every lane, the youtube importer, the proxy
# generator and the on-demand b-roll fetch ask the root guard before they
# write; this executor, which creates its own destination directories, never
# did. On macOS an absent /Volumes/<Name> is not an error: mkdir CREATES it on
# the boot volume, GBs land on the internal disk, and the next replug mounts
# the real drive at "/Volumes/<Name> 1" -- the ROOT_MISPLACED outage
# root_guard.py opens by describing. Same gap COMMERCIAL_READINESS item 5
# closed for broll_fetch.fetch_refusal.
REASON_TREE_ABSENT = ("this machine's tree isn't mounted right now, so there "
                      "is nowhere to download into")


class LeaseLost(Exception):
    """The server answered 410: this job is no longer ours to download.

    Its own exception because every caller does the same thing with it and
    nothing else: stop. See the module docstring's second rule.
    """


# ---------------------------------------------------------------------------
# http
# ---------------------------------------------------------------------------


def default_request(method: str, url: str, body: Optional[dict],
                    headers: dict, timeout: float) -> tuple[int, Any]:
    """One fleet API call -> (status_code, parsed_json_or_None).

    An HTTP error status is an ANSWER here, not an exception: 410 means "the
    lease is gone" and 409 means "somebody else has it", and both are ordinary
    outcomes this executor branches on. urllib raises HTTPError for them, so it
    is caught and unwrapped -- a caller that had to know urllib's shape would
    be a caller that stubs it wrong in tests.

    A transport failure (no route, DNS, timeout, a body that is not JSON) still
    raises: those are not answers, and the claim path treats them as "no
    capability today", exactly like a refused claim.
    """
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        # No redirects: `headers` carries the fleet token, and urlopen follows
        # 3xx while stripping only Authorization -- a custom header rides along
        # to whatever host the Location names. Same rule as reporter.py's
        # default_http_post (COMMERCIAL_READINESS.md item 15, 2026-08-17); a
        # 3xx now surfaces as the HTTPError this function already unwraps.
        with upgrade_mod.build_no_redirect_opener().open(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        try:
            raw = exc.read()
        except Exception:
            raw = b""
        status = exc.code
    try:
        return status, (json.loads(raw.decode("utf-8")) if raw else None)
    except (json.JSONDecodeError, UnicodeDecodeError):
        # A proxy's HTML error page, or a dashboard that fell over mid-answer.
        # The STATUS is what every caller acts on, so it survives.
        return status, None


# (method, url, body, headers, timeout) -> (status, parsed). The one seam the
# tests stub, deliberately the same shape as default_request above.
RequestFn = Callable[[str, str, Optional[dict], dict, float], tuple[int, Any]]
# (argv, timeout, on_spawn) -> object with .returncode/.stdout/.stderr.
# default_run also takes an optional `on_line` keyword (each stdout line as it
# arrives); _call_run only passes it to a runner whose signature admits it, so
# the three-argument fakes the suite has always used keep working.
RunFn = Callable[[list, float, Optional[Callable[[Any], None]]], Any]


def default_run(argv: list, timeout: float,
                on_spawn: Optional[Callable[[Any], None]] = None,
                on_line: Optional[Callable[[str], None]] = None) -> Any:
    """Run yt-dlp, captured, windowless, with a sanitized env and a kill handle.

    Popen rather than subprocess.run for ONE reason: `on_spawn` hands the live
    process to the caller so a lost lease can kill a download in flight
    (subprocess.run gives nothing to kill until it returns, and a 40-clip job
    would keep fetching for an hour after the server took it back).

    stdout is read LINE BY LINE on a helper thread and each line handed to
    `on_line` as it arrives (2026-08-25): that is how the tray's "Downloading
    YouTube clip 3/12 (4.2 MB/s)" line gets its numbers, from the progress
    template build_argv asks yt-dlp to print. The lines are still collected
    into .stdout afterwards, so nothing that read the CompletedProcess
    changes. stderr stays a plain pipe read by communicate(); a callback that
    raises is swallowed -- a tray line must never kill a download.

    Everything else is ytdlp_manager._default_run's construction, for its
    reasons: resolve_bridge.sanitized_child_env() because PYTHONHOME/
    PYTHON3HOME are pinned process-wide at OUR _MEIPASS (AUDIT_2 CORE-M6) and
    yt-dlp.exe is itself a frozen Python; CREATE_NO_WINDOW because this is a
    windowed build and an unflagged spawn flashes a console on the editor's
    desktop; stdin closed because a yt-dlp that decided to prompt would
    otherwise block until the timeout.
    """
    proc = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        encoding="utf-8",
        errors="replace",
        creationflags=ytdlp_manager._win_creationflags(),
        env=resolve_bridge.sanitized_child_env(),
    )
    if on_spawn is not None:
        on_spawn(proc)
    lines: list = []

    def _pump() -> None:
        try:
            for line in proc.stdout:
                lines.append(line)
                if on_line is not None:
                    try:
                        on_line(line.rstrip("\r\n"))
                    except Exception:
                        pass
        except Exception:
            pass

    pump = threading.Thread(target=_pump, name="ytdl-stdout", daemon=True)
    pump.start()
    try:
        # communicate() reads stderr; stdout is the pump's (a stream handed
        # to communicate as well would be read twice and lose lines).
        proc.stdout, stdout_stream = None, proc.stdout
        try:
            _out, err = proc.communicate(timeout=timeout)
        finally:
            proc.stdout = stdout_stream
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:
            pass
        proc.stdout, stdout_stream = None, proc.stdout
        try:
            _out, err = proc.communicate()
        finally:
            proc.stdout = stdout_stream
        pump.join(timeout=5)
        raise
    pump.join(timeout=5)
    return subprocess.CompletedProcess(argv, proc.returncode, "".join(lines), err)


def _call_run(run: Any, argv: list, timeout: float, on_spawn: Any,
              on_line: Any) -> Any:
    """Invoke a RunFn, passing `on_line` only to a runner that takes it.

    The seam predates the progress line and every fake in the suite (and any
    operator's replacement) is `(argv, timeout, on_spawn)`. A runner without
    the keyword simply produces no progress -- the tray line then reads
    "Downloading YouTube clip 3/12" with no rate, which is true.
    """
    if on_line is not None:
        try:
            params = inspect.signature(run).parameters
            takes = ("on_line" in params or any(
                p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()))
        except (TypeError, ValueError):
            takes = False
        if takes:
            return run(argv, timeout, on_spawn, on_line=on_line)
    return run(argv, timeout, on_spawn)


# ---------------------------------------------------------------------------
# what this machine can say about itself
# ---------------------------------------------------------------------------


class Deps:
    """Everything the executor needs from the running companion, injectable.

    Built once by app.py and handed to the 8899 listener (broll_server holds it
    on the server object, the way it already holds ccsync_cfg). The `ytdlp` and
    `editor_fn`/`selection_fn` seams matter live and not only in tests:

      - `ytdlp` is THE YtDlpManager the tray already runs. Its status() is a
        lock-guarded, zero-I/O read of the last daily check, which is what
        makes GET /ytdl/capabilities answer inside the SPA's 1 s probe budget
        (running `yt-dlp --version` inline costs seconds on a cold PyInstaller
        binary behind an AV scanner -- ytdlp_manager.VERSION_TIMEOUT_SECONDS
        allows fifteen);
      - `editor_fn` is app.editor_identity, not cfg["editor_name"]: a lease
        needs the VERIFIED holder, and reporting under a config-file name the
        dashboard does not know would take a lease nobody can trace;
      - `selection_fn` returns this machine's synced projects, which is what
        the manifest's project_label is validated against (§7).

    Absent seams degrade to "no capability", never to a guess.
    """

    def __init__(
        self,
        cfg: dict[str, Any],
        ytdlp: Optional[Any] = None,
        editor_fn: Optional[Callable[[], Optional[str]]] = None,
        selection_fn: Optional[Callable[[], Optional[list]]] = None,
        request_fn: Optional[RequestFn] = None,
        run_fn: Optional[RunFn] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
        identity_token_fn: Optional[Callable[[], Optional[str]]] = None,
        root_present_fn: Optional[Callable[[], bool]] = None,
        root_probe_fn: Optional[Callable[[str], str]] = None,
    ) -> None:
        self.cfg = cfg or {}
        self.ytdlp = ytdlp
        self._editor_fn = editor_fn
        self._selection_fn = selection_fn
        self._identity_token_fn = identity_token_fn
        # comp-ytdl-1 (2026-08-21). Two seams, because the two callers have
        # different budgets: `root_present_fn` is app.root_is_present, a
        # zero-I/O read of the guard's cached verdict, which is all
        # capabilities() (1 s probe budget, no subprocesses) may use;
        # `root_probe_fn` is the full root_guard.probe_root, run once off the
        # fast path before a job creates any directory. Absent seams mean "no
        # new information" and pass, exactly as ROOT_UNKNOWN does.
        self._root_present_fn = root_present_fn
        self._root_probe_fn = root_probe_fn
        self.request = request_fn or default_request
        self.run = run_fn or default_run
        self.sleep = sleep_fn or time.sleep

    # -- config-derived, zero-I/O ----------------------------------------
    @property
    def dashboard_url(self) -> str:
        return str(self.cfg.get("dashboard_url", "") or "").strip().rstrip("/")

    @property
    def token(self) -> str:
        """The shared fleet token, read from cfg PER CALL.

        reporter.post_once's rule and its reason: /api/v1/verify hands the
        current report token back at sign-in and IdentityManager republishes it
        into this same dict, so a rotated (or mistyped) config.toml
        `dashboard_token` stops 403-ing the moment the editor signs in.
        """
        return str(self.cfg.get("dashboard_token", "") or "").strip()

    def tree_is_absent(self) -> bool:
        """True only when the tree is KNOWN to be gone. "Can't tell" is
        False -- a probe that has not answered must never be the reason an
        editor cannot download (root_guard's contract). Never raises."""
        try:
            present_fn = self._root_present_fn
            if present_fn is not None and not present_fn():
                return True
        except Exception:
            log.debug("ytdl: the root-presence check failed", exc_info=True)
        return False

    def tree_is_misplaced(self) -> bool:
        """The full probe, for the paths that are about to WRITE. Costs a
        stat (and on a misplaced macOS volume, one cached diskutil), so it is
        never on the capabilities path. Never raises."""
        probe = self._root_probe_fn or root_guard.probe_root
        try:
            root = str(self.cfg.get("local_root", "") or "").strip()
            if not root:
                return False
            return probe(root) in (root_guard.ROOT_ABSENT, root_guard.ROOT_MISPLACED)
        except Exception:
            log.debug("ytdl: the root probe failed", exc_info=True)
            return False

    def editor(self) -> str:
        """The verified editor name, or "" when nobody is signed in.

        "" is a REFUSAL, not a fallback: routes_fleet.claim answers 400 to an
        empty editor because a lease needs a holder.
        """
        if self._editor_fn is not None:
            try:
                return str(self._editor_fn() or "").strip()
            except Exception:
                log.debug("ytdl: editor_fn failed", exc_info=True)
                return ""
        return str(self.cfg.get("editor_name", "") or "").strip()

    def identity_token(self) -> str:
        """The dashboard-signed identity token, or "" when not signed in.

        The fleet routes VERIFY this since 2026-08-17 (H5): the shared report
        token proves "a fleet machine", and this proves WHICH editor's. Without
        it every claim, heartbeat, manifest and status post is a 403, so ""
        means no capability -- the same answer, and the same fallback, as an
        editor who is not signed in at all.

        Read per call, like `token`: IdentityManager replaces it on sign-in and
        clears it on sign-out, and a cached copy would keep a signed-out
        machine claiming jobs until the tray restarted.
        """
        if self._identity_token_fn is not None:
            try:
                return str(self._identity_token_fn() or "").strip()
            except Exception:
                log.debug("ytdl: identity_token_fn failed", exc_info=True)
                return ""
        return ""

    def selection_labels(self) -> Optional[set]:
        """This machine's synced project labels, or None when unknowable.

        None and empty are different answers and callers must treat them so:
        empty is "this editor syncs nothing" (refuse), None is "we could not
        ask" (also refuse, but for a reason worth logging differently). Both
        fail closed -- the cost is a job the server downloads instead.
        """
        if self._selection_fn is None:
            return None
        try:
            items = self._selection_fn()
        except Exception:
            log.debug("ytdl: selection_fn failed", exc_info=True)
            return None
        if items is None:
            return None
        labels = set()
        for item in items or []:
            if not isinstance(item, dict):
                continue
            for key in ("rel_path", "label"):
                value = normalize_label(item.get(key))
                if value:
                    labels.add(value)
        return labels

    def ytdlp_status(self) -> dict:
        """The sidecar's last check. Never runs the binary (see the class
        docstring's 1 s probe budget)."""
        if self.ytdlp is None:
            return {"ok": False, "version": None,
                    "message": "the yt-dlp sidecar manager is not running"}
        try:
            return dict(self.ytdlp.status() or {})
        except Exception:
            log.debug("ytdl: ytdlp status read failed", exc_info=True)
            return {"ok": False, "version": None,
                    "message": "the yt-dlp sidecar could not be read"}

    def ytdlp_binary(self) -> Path:
        return ytdlp_manager.binary_path(self.cfg)

    @property
    def is_base_rig(self) -> bool:
        return str(self.cfg.get("mode", "editor") or "").strip().lower() == "base"


def normalize_label(value: Any) -> str:
    """A project label folded to one comparable spelling.

    The dashboard's selection and the ytdl job row hold the SAME string (the
    folder label that is the year/series/project rel path -- dashboard
    api._selection_view pins `rel_path` to it), but they travel through
    different hands: one has been through a config file and a JSON cache, the
    other through a search form. Case and separators are folded so
    `2026/FF5/Show` and `2026\\FF5\\show` are the one project they obviously
    are; nothing else is touched.
    """
    if not isinstance(value, str):
        return ""
    return value.replace("\\", "/").strip().strip("/").casefold()


def _label_parts(value: Any) -> list:
    """A project label split into path segments, in its ORIGINAL spelling.

    normalize_label's casefolded twin is for COMPARING labels; this is for
    walking the disk with one (comp-ytdl-5, 2026-08-21)."""
    if not isinstance(value, str):
        return []
    return [p for p in value.replace("\\", "/").strip().strip("/").split("/") if p]


def free_bytes_at(path: Any) -> Optional[int]:
    """Free bytes on the volume holding `path`, or None if unknowable.

    Walks UP to the first existing ancestor: the destination folder of a
    first-ever download does not exist yet, and disk_usage on a missing path
    raises rather than answering for the volume it would live on.
    """
    try:
        p = Path(str(path))
    except Exception:
        return None
    for candidate in (p, *p.parents):
        try:
            if candidate.exists():
                return int(shutil.disk_usage(str(candidate)).free)
        except Exception:
            continue
    return None


def projects_root(cfg: dict[str, Any]) -> Optional[str]:
    """`<local_root>/Projects` on THIS machine, or None.

    local_root and not the canonical `P:\\` prefix, for broll_server
    .default_broll_mount's reason: this string is handed to the filesystem, and
    on a Mac there is no drive namespace to resolve `P:\\` against.
    """
    try:
        root = config_mod.resolved_local_root(cfg or {})
    except Exception:
        return None
    if not str((cfg or {}).get("local_root") or "").strip():
        return None
    return str(Path(root, "Projects"))


def destination_for(cfg: dict[str, Any], project_rel_path: Any) -> Optional[str]:
    """The manifest's `project_rel_path` -> the folder to download into here.

    THROUGH PATH CANON (§7), not by joining onto local_root directly. The
    manifest speaks the canonical tree -- `<label>/Youtube/<term>` under the
    fleet's one Projects root -- because only the companion knows where that
    root is on the machine it is running on. So the path is built canonically
    (`P:\\Projects\\...`, in the PREFIX's spelling, backslashes on a Mac too)
    and then translated to this host's spelling. On the base rig
    canonical_prefix IS local_root and the translation is the identity, which
    is exactly why the base rig is the pilot machine: its "local" download
    writes straight onto the NAS.

    None when the rel path is not a contained relative path.
    normalized_safe_rel is the fleet's one answer to that question (the same
    helper selection.py validates dashboard rel_paths with) -- a second set of
    traversal rules is how a traversal gets served.
    """
    rel = normalized_safe_rel(project_rel_path)
    if rel is None:
        return None
    parts = [p for p in rel.replace("\\", "/").split("/") if p and p != "."]
    if not parts:
        return None
    local_root = str((cfg or {}).get("local_root", "") or "").strip()
    if not local_root:
        return None
    prefix = str((cfg or {}).get("canonical_prefix", "") or "").strip()
    if not prefix:
        # A machine with no canonical prefix configured (legacy / unmanaged):
        # there is no canon to translate through, and its local tree IS the
        # only spelling it has.
        return os.path.join(local_root, "Projects", *parts)
    sep = canon.plat_for(prefix).sep
    canonical = prefix.rstrip("\\/") + sep + sep.join(["Projects", *parts])
    return canon.canonical_to_local(canonical, local_root, prefix)


def url_is_youtube(url: Any) -> bool:
    """Is this a URL we are willing to hand to yt-dlp? Never raises.

    The manifest arrives token-authed from our own dashboard, so this is a
    defence against a SERVER bug (or a compromised row) rather than against the
    browser -- which contributes nothing but a job id. Cheap, and the failure
    it prevents is "the editor's machine fetched something arbitrary off the
    internet on the fleet's say-so".
    """
    try:
        parsed = urllib.parse.urlparse(str(url or ""))
    except Exception:
        return False
    if parsed.scheme.lower() not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    for stripped in ("www.", "m."):
        if host.startswith(stripped):
            host = host[len(stripped):]
    if host in YOUTUBE_HOSTS:
        return True
    return any(host.endswith(suffix) for suffix in YOUTUBE_HOST_SUFFIXES)


def machine_mode(cfg: Any) -> str:
    """"base" or "editor" for THIS computer -- app.effective_mode's rule,
    without needing the app object.

    Kept in step with `CcsyncApp.effective_mode` deliberately: config's own
    `mode` and nothing else since 2026-08-27, because the role belongs to the
    computer and not to whoever is signed in (CR-88). Anything that is not
    exactly "base" is an editor machine, which is the safe direction -- a
    machine wrongly called wired would be offered destinations it does not
    sync."""
    try:
        return "base" if str((cfg or {}).get("mode", "") or "").strip().lower() == "base" else "editor"
    except Exception:  # noqa: BLE001 - a cfg that is not a mapping is an editor
        return "editor"


def capabilities(deps: Deps) -> dict:
    """What GET /ytdl/capabilities answers. 200 always; `ok` carries the verdict.

    MUST BE FAST -- the SPA's probe aborts at 1 s and any failure sends the job
    down the server path with no UI noise (§2 step 2). So nothing here runs a
    subprocess or makes a request: the yt-dlp version is the sidecar manager's
    CACHED daily result (ytdlp_manager.status(), a lock-guarded read that does
    no I/O by design), the ffmpeg question is answered by the proxy generator's
    _resolve_binary (a which()/exists() pair, never a `-version` spawn), and the
    only other syscall is one disk_usage.

    `ok: false` is a complete answer, not an error: it means this machine
    downloads the way every machine did before 0.8.0.
    """
    status = deps.ytdlp_status()
    result = {
        "ok": False,
        "reason": None,
        # CYT-7: an advisory that does NOT refuse the job (see below). Always
        # present so the SPA can read one shape.
        "warning": None,
        "editor": deps.editor(),
        "ytdlp_version": status.get("version"),
        "template_version": ytdl_common.TEMPLATE_VERSION,
        "sidecar_version": ytdl_common.SIDECAR_VERSION,
        # COMP-BROLL-10 (2026-08-14): the rungs this machine will actually run.
        # The SPA knows the job's quality when it decides whether to dispatch,
        # so a probe that says "480p/720p/1080p" lets it not dispatch a 2160p
        # job at all -- today it dispatches every job, the companion claims it,
        # reads the manifest, finds a rung only the server can name and hands
        # it back by letting the lease expire, and the job sits still for up to
        # 180 s. An SPA that ignores the field behaves exactly as it does now.
        "scope_qualities": list(SCOPE_QUALITIES),
        "free_bytes": free_bytes_at(projects_root(deps.cfg) or Path.home()),
        # WHICH COMPUTER IS ASKING (CR-72 follow-up, 2026-08-31). The ytdl
        # picker's widening rule is per MACHINE -- ticked_projects/_wired take
        # a hostname -- but the browser had no way to learn one: a page served
        # from the NAS knows the person, never the computer they are sitting
        # at. So a mixed account's wired machine kept being handed the picker
        # its REMOTE machine's sync plan justifies, which is the "I can still
        # only select /animals as a destination on the base rig" report.
        #
        # `platform.node()` and not machine_id: the hostname is the key
        # `machine_state`, `selections` and every lane report are already
        # filed under (machine.py's own docstring says so), and the server
        # side matches on exactly that string. Both fields are free -- no
        # syscall, no I/O -- which is what keeps this inside the SPA's 1 s
        # probe budget.
        "machine": platform.node(),
        # "base" (wired) or "editor" (remote), read the way app.effective_mode
        # reads it: THIS COMPUTER's own config, never the person's role
        # (CR-88). Diagnostic here -- the server re-derives wiredness from
        # machine_state rather than trusting a client that says "base".
        "mode": machine_mode(deps.cfg),
    }
    # youtube_enabled, not local_downloads_enabled: the site's own
    # `youtube_download` flag comes first (2026-08-17). A site that never
    # turned the downloader on has no /ytdl mount either, so this is belt and
    # braces -- and the braces matter, because a companion pointed at a
    # dashboard mid-rollback must not be the one component still downloading.
    if not ytdlp_manager.youtube_enabled(deps.cfg):
        result["reason"] = REASON_DISABLED
        return result
    if not deps.dashboard_url or not deps.token:
        result["reason"] = REASON_NO_DASHBOARD
        return result
    if not result["editor"]:
        result["reason"] = REASON_NO_EDITOR
        return result
    if not deps.identity_token():
        result["reason"] = REASON_NO_IDENTITY
        return result
    if not ytdl_attestation.accepted(result["editor"]):
        result["reason"] = REASON_NOT_ATTESTED
        return result
    if not status.get("ok"):
        result["reason"] = str(status.get("message") or "yt-dlp is not ready on this machine")
        return result
    # CYT-7 (usability sweep 2026-09-03): a yt-dlp past its shelf life that
    # could not update itself is published with ok=True -- it can still very
    # probably download -- so it passed the test above and reached no human at
    # all. It is a WARNING and never a refusal: blocking the download would
    # send the job to the server for a binary that mostly still works.
    if str(status.get("action") or "") == ytdlp_manager.ACTION_STALE:
        result["warning"] = str(status.get("message") or "") or None
    if not _ffmpeg_location(deps.cfg):
        # The SAME call build_argv makes, so a capability that said yes is a
        # capability whose `--ffmpeg-location` will be there (COMP-BROLL-5).
        result["reason"] = REASON_NO_FFMPEG
        return result
    if deps.tree_is_absent():
        # LAST, and off the guard's cached verdict rather than a fresh probe:
        # this answer has a 1 s budget (comp-ytdl-1, 2026-08-21). Note that
        # free_bytes above cannot catch this -- free_bytes_at walks up to the
        # first EXISTING ancestor, so with /Volumes/T7 unplugged it reports
        # the boot volume's free space and passes.
        result["reason"] = REASON_TREE_ABSENT
        return result
    result["ok"] = True
    return result


# ---------------------------------------------------------------------------
# the fleet API client
# ---------------------------------------------------------------------------


def _this_machine_id() -> str:
    """This computer's id for the claim body, "" when there is none.

    Never raises and never blocks the claim: the id is a KEY the server may
    scope the lease by (data-model-7), not a credential and not a requirement.
    Deliberately UNCACHED here, unlike reporter.py's per-instance cache: a
    claim happens once per job, machine.json is one small local file, and a
    module-level cache would outlive the tray's own re-read of an id an editor
    replaced by hand.
    """
    try:
        return str(machine_mod.machine_id() or "")
    except Exception:
        log.debug("ytdl: this machine has no id to claim with", exc_info=True)
        return ""


class FleetClient:
    """routes_fleet, from the other end. Token-authed, browser-free.

    Every method raises LeaseLost on 410 -- that is the whole error model above
    the claim, because the server answers 410 to every way a lease can end and
    the companion's response to all of them is to stop (§3).
    """

    def __init__(self, deps: Deps, editor: str,
                 timeout: float = HTTP_TIMEOUT_SECONDS,
                 should_stop: Optional[Callable[[], bool]] = None,
                 sleep: Optional[Callable[[float], None]] = None,
                 clock: Optional[Callable[[], float]] = None) -> None:
        self.deps = deps
        self.editor = editor
        self.timeout = timeout
        # The job's own stop predicate, so a retry loop does not sit out its
        # budget after the tray has been told to quit or the lease is known
        # lost. Defaulting to "never stop" keeps every existing caller (and
        # every test that builds a bare client) working unchanged.
        self.should_stop = should_stop or (lambda: False)
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic

    def _url(self, suffix: str) -> str:
        return f"{self.deps.dashboard_url}{API_PREFIX}{suffix}"

    def _headers(self) -> dict:
        # X-CCSync-Identity carries the dashboard-SIGNED identity token, not
        # the editor's name (H5, 2026-08-17). It used to be the bare name, and
        # routes_fleet said so out loud -- "a MISTAKE-PREVENTER, not an
        # authorisation boundary" -- which meant the shared fleet token, held
        # by every machine, was the only thing between a companion and another
        # editor's job. The server now verifies the signature before it
        # believes the name; this is the same token reporter.py and
        # selection.py already send on every call they make.
        return {
            "Content-Type": "application/json",
            "X-CCSync-Token": self.deps.token,
            "X-CCSync-Identity": self.deps.identity_token(),
        }

    def _call(self, method: str, suffix: str, body: Optional[dict] = None):
        """One fleet call, retrying a TRANSPORT failure inside the lease.

        The retry exists because of CR-31: `deps.request` raises for "no route,
        DNS, timeout, a body that is not JSON", and every one of those used to
        end the job -- the exception left _call, left _download_all, and
        run()'s catch-all logged "job N failed" and stopped with 20 of 22 clips
        undownloaded. A dashboard restart is three seconds; the lease is 180.
        Nothing about that is a reason to hand the job back.

        What is NOT retried, and must never be: a status code. 410 is the end
        of the job (the module's second rule) and every other code is an answer
        the caller branches on. Only the raised transport failure gets another
        go, and only until CALL_RETRY_BUDGET_SECONDS is spent -- after which
        the exception propagates exactly as it did before, because a dashboard
        that has been unreachable for a minute has already let the lease lapse
        and the server is downloading what we did not.
        """
        deadline = self._clock() + CALL_RETRY_BUDGET_SECONDS
        backoff = CALL_RETRY_FIRST_BACKOFF
        attempt = 0
        while True:
            attempt += 1
            try:
                status, parsed = self.deps.request(
                    method, self._url(suffix), body, self._headers(),
                    self.timeout)
            except Exception as exc:
                # No budget left, or the job is over anyway: raise, and let the
                # caller do what it has always done with an unreachable server.
                if self.should_stop() or self._clock() >= deadline:
                    raise
                # Logged at WARNING on the first go and DEBUG after: an outage
                # long enough to matter should be one line in the log an editor
                # can be asked for, not a stream of them.
                log.log(logging.WARNING if attempt == 1 else logging.DEBUG,
                        "ytdl: %s %s failed (%s) -- retrying for up to %.0fs",
                        method, suffix, exc, CALL_RETRY_BUDGET_SECONDS)
                self._sleep(min(backoff, max(0.0, deadline - self._clock())))
                backoff = min(backoff * 2, CALL_RETRY_MAX_BACKOFF)
                if self.should_stop():
                    raise
                continue
            if attempt > 1:
                log.info("ytdl: %s %s succeeded on attempt %s", method, suffix,
                         attempt)
            if status == 410:
                raise LeaseLost(_detail_of(parsed) or "this job is no longer yours")
            return status, parsed

    def claim(self, job_id: int, ytdlp_version: Optional[str],
              free_bytes: Optional[int]) -> Optional[dict]:
        """Take the lease, or None.

        None for EVERY refusal there is -- 403 (yt-dlp older than the fleet
        minimum), 409 (somebody else holds it), 410 (not claimable: finished,
        pinned to the server, or a naming-contract skew), a 500, an unreachable
        dashboard. They are one outcome to this side: the server worker
        downloads exactly as it does today, which is the whole rollback story
        (§10), and none of them is an error the editor should see.
        """
        body = {
            "editor": self.editor,
            "ytdlp_version": ytdlp_version or "",
            "template_version": ytdl_common.TEMPLATE_VERSION,
            # COMP-BROLL-6 (2026-08-14): the sidecar half of the §5 handshake
            # was advertised by the server (the manifest and the client config
            # both carry it) and compared by nobody, so a server that grew a
            # ninth SIDECAR_FIELD would have taken 8-field sidecars from every
            # 0.8.0 companion without a word. The two numbers are separate
            # precisely because they fail differently (ytdl_common:56-60).
            "sidecar_version": ytdl_common.SIDECAR_VERSION,
            # COMP-BROLL-10 (2026-08-14): what this executor will actually run.
            # The server holds the job's quality at claim time, so declaring
            # the scope here is what lets it answer 410 immediately instead of
            # granting a lease it must then wait out -- three minutes of a
            # 2160p job sitting still, per job, for nothing. A server that does
            # not read the field behaves exactly as it does today: the manifest
            # check below still hands the job back.
            "scope_qualities": list(SCOPE_QUALITIES),
            "free_bytes": free_bytes,
            # data-model-7 (CR-66, CR-67): the download lease is keyed on the
            # editor NAME, so one account's two computers are one lease holder
            # -- the second machine's claim is refused as "somebody else holds
            # it" and its editor watches the server download a job their own
            # machine was ready to take (docs/MULTI_MACHINE_PLAN.md: a plan
            # belongs to a COMPUTER). This is the same id reporter.py already
            # sends, minted once into ~/.ccsync/machine.json and surviving a
            # rename. "" when the file cannot be read or written, which is what
            # a server keying per (editor, machine_id) must treat exactly as
            # today's person-wide lease; the server half tolerates its absence
            # either way.
            "machine_id": _this_machine_id(),
        }
        try:
            status, parsed = self.deps.request(
                "POST", self._url(f"/jobs/{job_id}/claim"), body,
                self._headers(), self.timeout)
        except Exception as exc:
            log.info("ytdl: job %s could not be claimed (%s) -- the server "
                     "downloads it", job_id, exc)
            return None
        if status == 200 and isinstance(parsed, dict):
            return parsed
        log.info("ytdl: job %s was not given to this machine (HTTP %s: %s) -- "
                 "the server downloads it", job_id, status,
                 _detail_of(parsed) or "no detail")
        if status == 403:
            _warn_on_a_version_floor_we_rank_differently(parsed, ytdlp_version)
        return None

    def heartbeat(self, job_id: int) -> None:
        self._call("POST", f"/jobs/{job_id}/heartbeat", {"editor": self.editor})

    def manifest(self, job_id: int) -> Optional[dict]:
        status, parsed = self._call("GET", f"/jobs/{job_id}/download-manifest")
        if status != 200 or not isinstance(parsed, dict):
            log.warning("ytdl: job %s did not answer a manifest (HTTP %s)",
                        job_id, status)
            return None
        return parsed

    def clip_status(self, job_id: int, video_id: str, state: str,
                    error: Optional[str] = None, note: Optional[str] = None,
                    filepath_rel: Optional[str] = None,
                    title: Optional[str] = None,
                    channel: Optional[str] = None) -> None:
        """Mirror one clip's outcome into the job rows.

        Failures other than 410 are logged and swallowed: the download itself
        already happened (or already failed), and dying on a lost status post
        would abandon the rest of the job over a blip. The server's
        second-chance sweep is what makes that safe -- a clip whose `done`
        never landed is simply retried once server-side (§2 step 7).

        `title`/`channel` are OMITTED rather than sent as null when we do not
        know them (YTDL-WEB-8, 2026-08-14): routes_fleet falls back to the
        existing row for each, exactly as the NAS worker's `res.get('channel')
        or v['channel']` does, and a pasted-link job's row -- which has no
        channel until a download reports one -- must not be overwritten with a
        None by the executor that could not read an info json.
        """
        body = {"state": state, "error": error, "note": note,
                "filepath_rel": filepath_rel}
        if title:
            body["title"] = title
        if channel:
            body["channel"] = channel
        status, parsed = self._call(
            "POST", f"/jobs/{job_id}/clips/{urllib.parse.quote(str(video_id), safe='')}"
                    "/status", body)
        if status != 200:
            log.warning("ytdl: job %s clip %s: the dashboard refused the %r "
                        "status (HTTP %s: %s)", job_id, video_id, state, status,
                        _detail_of(parsed) or "no detail")


def _detail_of(parsed: Any) -> str:
    """FastAPI's error body -> one readable line. Never raises."""
    try:
        detail = parsed.get("detail") if isinstance(parsed, dict) else None
        if isinstance(detail, dict):
            return str(detail.get("detail") or detail)
        return str(detail or "")
    except Exception:
        return ""


def _detail_dict(parsed: Any) -> dict:
    """routes_fleet's structured `detail` payload, or {}. Never raises."""
    try:
        detail = parsed.get("detail") if isinstance(parsed, dict) else None
        return detail if isinstance(detail, dict) else {}
    except Exception:
        return {}


def _warn_on_a_version_floor_we_rank_differently(parsed: Any,
                                                 ours: Optional[str]) -> None:
    """Say so when the server calls our yt-dlp stale and we call it current.

    COMP-BROLL-9 (2026-08-14). The two sides rank the same two strings with
    different rules: this one parses them into tuples of ints
    (ytdlp_manager.version_is_older -> upgrade.parse_version), the dashboard
    compares the raw strings, which is exact for yt-dlp's own zero-padded
    YYYY.MM.DD output and NOT for the free-text `YTDL_MIN_YTDLP_VERSION` an
    operator types. One unpadded floor ('2026.8.5') therefore 403s every claim
    from every machine in the fleet while every companion concludes it has
    nothing to update -- local downloads silently dead everywhere, and the only
    log line anywhere says the yt-dlp is old.

    The ranking here is the correct one and is deliberately NOT bent to match;
    what this adds is the sentence that names the cause, because the failure is
    a config typo on the NAS and nothing on this side can fix it.
    """
    detail = _detail_dict(parsed)
    if str(detail.get("reason") or "") != "ytdlp_version":
        return
    floor = str(detail.get("min_ytdlp_version") or "").strip()
    if not floor or not ours:
        return
    if ytdlp_manager.version_is_older(ours, floor):
        return          # ordinary staleness; the sidecar updates itself
    log.warning(
        "ytdl: the dashboard refused this machine's yt-dlp %s as older than "
        "its minimum %r, but %s is not older than %r by version order. The "
        "fleet minimum is probably not zero-padded (YTDL_MIN_YTDLP_VERSION on "
        "the dashboard); until it is, every machine's downloads run on the "
        "server.", ours, floor, ours, floor)


# ---------------------------------------------------------------------------
# files on disk
# ---------------------------------------------------------------------------


def is_sweepable(name: str) -> bool:
    """yt-dlp's own litter for one clip -- in flight OR finished-but-unmerged.

    The suffix half is worker._sweepable, verbatim rule. The stem half is
    COMP-BROLL-3's addition (see _INTERMEDIATE_STEM_RE): a `... [id].f137.mp4`
    that yt-dlp finished and kept for resume is not "in flight" by any suffix
    test, and it was the one thing here that nothing on the machine ever
    deleted. The server worker's _sweepable should grow the same rule -- until
    it does, this side simply cleans up more thoroughly than that one.
    """
    path = Path(str(name))
    if path.suffix in SWEEPABLE_SUFFIXES or path.suffix.startswith(".part-Frag"):
        return True
    return bool(_INTERMEDIATE_STEM_RE.search(path.stem))


def id_bearing_files(outdir: Any, video_id: str) -> set:
    """{name} of everything in outdir carrying `[video_id]`.

    Substring, never a glob: a video id may contain any of `[]-_` and one bad
    escape silently matches nothing (worker._id_bearing_files).
    """
    try:
        return {p.name for p in Path(str(outdir)).iterdir()
                if p.is_file() and f"[{video_id}]" in p.name}
    except OSError:
        return set()


def landed_file(outdir: Any, video_id: str) -> Optional[str]:
    """The FINISHED file this clip left in `outdir`, or None.

    The `[id]`-at-the-end-of-the-stem anchor (worker._landed_file, and
    ytsearch._ID_RE's rule, YTDL-27) is what keeps `... [id].info.json` and
    `... [id].credits.json` from being read as the clip itself: their stems end
    in `.info` / `.credits`, not in `[id]`. A DISOWNED corpse is skipped for
    worker._landed_file's other reason: a previous attempt's leftover is not
    this attempt's output.
    """
    for name in sorted(id_bearing_files(outdir, video_id)):
        if is_sweepable(name) or name.endswith(DISOWNED_SUFFIX):
            continue
        if Path(name).stem.endswith(f"[{video_id}]"):
            return name
    return None


def clear_partials(outdir: Any, video_id: str) -> None:
    """Delete THIS clip's own in-progress leftovers. Never fatal.

    ID-SCOPED, never a glob of the folder (worker._clear_partials): the term
    folder is shared with every other clip of the search, and a `.part` in
    there may belong to a download that is still running -- another editor's,
    even, since both executors write into one canonical tree.

    SAQBbd1Rxmo (2026-08-13) is why it happens at all: a give-up left a 10 MB
    `... [id].f137.mp4.part` behind forever, and yt-dlp RESUMES a .part, so
    every later attempt started from the poisoned bytes and died the same way.
    """
    for name in id_bearing_files(outdir, video_id):
        if not is_sweepable(name):
            continue
        try:
            (Path(str(outdir)) / name).unlink()
        except OSError as exc:
            log.warning("ytdl: could not remove %s in %s (%s); a later retry "
                        "may resume from it", name, outdir, exc)


def clear_aside_originals(outdir: Any, video_id: str) -> tuple[int, int]:
    """Retry the delete swap_in could not do. -> (deleted, bytes still there).

    YT-6 (2026-08-28): when Resolve holds the pre-conversion original open,
    swap_in renames it `... [id].original.<ext>` instead of deleting it, and
    before this NOTHING ever removed it. It is a full second copy of the clip,
    it matches lane A's `+ *.mp4`, and one term folder collected one per
    converted download forever.

    ID-SCOPED and only on the way IN to a fresh attempt at the same clip, for
    clear_partials' reason: the folder is shared with every other clip of the
    search and with the other executor. Resolve is normally no longer holding
    the file by then (a later session, a closed project), so this is the
    natural moment. What it cannot delete it REPORTS, in bytes, so the note on
    the clip row can say how much is reclaimable rather than the space being
    invisible; nothing here forces a delete, because the editor may have that
    file open in a timeline this second.
    """
    deleted, remaining = 0, 0
    for name in id_bearing_files(outdir, video_id):
        if not Path(name).stem.endswith(ORIGINAL_SUFFIX):
            continue
        path = Path(str(outdir)) / name
        size = _size_of(path)
        try:
            path.unlink()
        except OSError as exc:
            remaining += size
            log.info("ytdl: %s is still in use (%s); %s bytes stay reclaimable",
                     path, exc, size)
            continue
        deleted += 1
        log.info("ytdl: reclaimed %s bytes from %s (the original this clip's "
                 "conversion could not replace last time)", size, path)
    return deleted, remaining


def disown_output(outdir: Any, video_id: str, before: set) -> None:
    """Rename what a FAILED attempt landed so nothing downstream reads it.

    worker._disown_output's rule (YTDL-3, 2026-08-11), which this executor was
    missing entirely: a download that got as far as a real file and then died
    left `... [id].mp4` in the term folder -- unledgered, half-written, and
    carrying the `[id]` the disk-scan dedupe anchors on, so every later search
    called the clip "already in the fleet" and pointed the editor at a file
    they cannot open. On THIS side it is worse than on the NAS's, because lane
    A would then carry the corpse up to the NAS and lane B fan it out; the
    `.failed` suffix takes it out of that include list too.

    Only files that were NOT there before this attempt are touched, and yt-dlp's
    own resume state is left to clear_partials. Never fatal.
    """
    for name in id_bearing_files(outdir, video_id) - set(before or ()):
        if is_sweepable(name) or name.endswith(DISOWNED_SUFFIX):
            continue
        path = Path(str(outdir)) / name
        try:
            path.rename(path.with_name(name + DISOWNED_SUFFIX))
        except OSError as exc:
            log.warning("ytdl: could not disown %s (%s); it may block "
                        "re-downloading %s until it is removed by hand",
                        path, exc, video_id)


# ---------------------------------------------------------------------------
# edit-ready: probe the landed clip, convert it here if Resolve could not
# decode it (CR-79, 2026-08-25)
# ---------------------------------------------------------------------------
#
# Everything in this section is vendor/downloader.py's ensure_edit_ready,
# probe_streams, _same_rate, _color_args and _swap_in, split into pure pieces
# so each can be run through this executor's seams (deps.run, the kill handle,
# the tray's progress mirror) and pinned against the vendored original by
# server/tests/test_cross_component.py. The DECISION (which codecs are fine,
# what counts as VFR, what a failed probe means) and the ffmpeg command must
# stay byte-for-byte the server's: a clip converted here and the same clip
# converted on the NAS have to be the same file, or §5's "two spellings of one
# clip" comes back as two ENCODINGS of one clip.
#
# Why it exists: measured 2026-08-25, `player_client=web_safari` (CR-39)
# serves muxed HLS only, so all three AVC-constrained alternatives in
# ytdl_common.format_selector are unsatisfiable and yt-dlp takes the last,
# codec-unconstrained `best[height<=1080]`. That is H.264/AAC today because
# YouTube's HLS ladder is all AVC -- but nothing on this side checked, while
# the server ffprobes every clip. The day YouTube puts VP9 into that ladder,
# a local download would land undecodable and silent.

EDIT_SAFE_VCODECS = frozenset({"h264"})
EDIT_SAFE_ACODECS = frozenset({"aac"})

# _swap_in's two names. `.editready` is the converted file while ffmpeg
# writes it and the DELIVERABLE only when the original cannot be replaced or
# even renamed (Windows, clip open in Resolve); `.original` is where a locked
# original is moved aside so the converted file can take its name.
EDITREADY_SUFFIX = ".editready"
ORIGINAL_SUFFIX = ".original"

# YT-6 (resilience sweep 2026-08-28): the FALLBACK deliverable's name, and the
# reason it is not `.editready` any more. Every finished download's stem ends
# in `[id]` -- that anchoring is what the dedupe scan (ytsearch._ID_RE), the
# server's _landed_file and youtube_import._is_clip_name all read to tell a
# clip from its litter. `<stem>.editready.mp4` broke it: the file was the
# deliverable, so nothing could sweep it, and its stem ended in `.editready`,
# so nothing recognised it as the clip either. The editor got two clips per
# download (the importer filed both) and a truncated `.editready` from a
# container kill was never swept, never disowned, and still matched lane A's
# `+ *.mp4`. Putting the marker BEFORE the id bracket keeps both properties:
# the stem still ends `[id]`, and the name still says what happened.
CONVERTED_SUFFIX = ".converted"

# The trailing `[id]` of a yt-dlp outtmpl name. Non-greedy head so a title
# that itself contains brackets keeps them: only the LAST bracket group is the
# id (the same anchoring rule as the dedupe scan).
_ID_TAIL_RE = re.compile(r"^(?P<head>.*?)(?P<id>\s*\[[^\[\]]*\])$")

# ffprobe reads headers; ffmpeg re-encodes a whole clip. The conversion budget
# is above CLIP_TIMEOUT_SECONDS because libx264 at crf 18 on a laptop runs
# below real time on 1080p, and a two-hour clip is a legitimate download.
# Bounded at all for the lease's reason: the heartbeat thread keeps renewing
# while this runs, so an ffmpeg that hung would hold the job forever.
PROBE_TIMEOUT_SECONDS = 120.0
CONVERT_TIMEOUT_SECONDS = 3 * 3600.0


def probe_argv(ffprobe: str, path: Any) -> list:
    """probe_streams's command line, verbatim."""
    return [str(ffprobe), "-v", "error", "-print_format", "json",
            "-show_streams", str(path)]


def parse_probe(proc: Any) -> dict:
    """probe_streams's reading of ffprobe's answer.

    YTDL-22 (2026-08-11): a failure is `{"_probe_error": why}`, never `{}` --
    an empty dict reads as "no video stream, nothing to fix", which is how a
    container with no ffprobe once delivered every VP9 download unconverted.
    """
    rc = getattr(proc, "returncode", 1)
    if rc != 0:
        err = str(getattr(proc, "stderr", "") or "").strip()[-300:]
        return {"_probe_error": err or f"ffprobe exited {rc}"}
    try:
        return json.loads(str(getattr(proc, "stdout", "") or "") or "{}")
    except ValueError as exc:
        return {"_probe_error": f"unparseable ffprobe output: {exc}"}


def _same_rate(a: Any, b: Any, tol: float = 0.01) -> bool:
    """Are ffprobe's two frame-rate fields the same rate? (vendored verbatim)

    YTDL-23 (2026-08-11): compared as numbers, not as the raw strings ffprobe
    prints. `24000/1001` vs `24/1` and `30000/1001` vs `2997/100` are the same
    rate written differently; string-comparing them read as VFR and triggered
    a full libx264 re-encode. An unreadable or absent rate counts as "same".
    """
    try:
        fa, fb = Fraction(str(a)), Fraction(str(b))
    except (TypeError, ValueError, ZeroDivisionError):
        return True
    if fa == fb:
        return True
    if fa <= 0 or fb <= 0:
        return True
    return abs(float(fa) - float(fb)) <= tol * max(float(fa), float(fb))


def _color_args(v: dict) -> list:
    """Carry the source's colour tags across a re-encode. (vendored verbatim)"""
    args: list = []
    for flag, key in (("-color_primaries", "color_primaries"),
                      ("-color_trc", "color_transfer"),
                      ("-colorspace", "color_space")):
        val = v.get(key)
        if val and val != "unknown":
            args += [flag, val]
    if v.get("color_range") in ("tv", "pc"):
        args += ["-color_range", v["color_range"]]
    return args


def edit_ready_plan(probe: dict) -> dict:
    """ensure_edit_ready's decision for edit_codec="h264", as data.

    -> {"convert": bool, "need_v": bool, "need_a": bool, "probe_failed": bool,
        "vcodec": str|None, "acodec": str|None, "video": dict}

    An audio-only file (a video stream absent from a probe that WORKED) needs
    nothing. A probe that failed converts both streams on suspicion -- the
    vendored rule -- and `_ensure_edit_ready` is where a failed conversion of
    a suspicion is forgiven.
    """
    probe = probe if isinstance(probe, dict) else {}
    probe_failed = bool(probe.get("_probe_error"))
    streams = probe.get("streams") or []
    video = next((s for s in streams if isinstance(s, dict)
                  and s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if isinstance(s, dict)
                  and s.get("codec_type") == "audio"), None)
    plan = {"convert": False, "need_v": False, "need_a": False,
            "probe_failed": probe_failed, "vcodec": None, "acodec": None,
            "video": video or {}}
    if video is None and not probe_failed:
        return plan
    vcodec = video.get("codec_name") if video else None
    acodec = audio.get("codec_name") if audio else None
    vfr = bool(video) and not _same_rate(video.get("avg_frame_rate"),
                                         video.get("r_frame_rate"))
    need_v = probe_failed or vcodec not in EDIT_SAFE_VCODECS or vfr
    need_a = probe_failed or (audio is not None and acodec not in EDIT_SAFE_ACODECS)
    plan.update(convert=bool(need_v or need_a), need_v=bool(need_v),
                need_a=bool(need_a), vcodec=vcodec, acodec=acodec)
    return plan


def edit_ready_argv(ffmpeg: str, src: Any, tmp: Any, plan: dict) -> list:
    """ensure_edit_ready's ffmpeg command for the h264 policy, verbatim.

    Streams that are already fine are COPIED (`-c:v copy` / `-c:a copy`), so a
    VP9-with-AAC download pays for the video only; `-map_metadata 0` and
    `+use_metadata_tags` carry the embedded credits across.
    """
    video = plan.get("video") or {}
    vargs = (["-c:v", "libx264", "-preset", "medium", "-crf", "18",
              "-profile:v", "high", "-pix_fmt", "yuv420p", "-fps_mode", "cfr"]
             + _color_args(video)) if plan.get("need_v") else ["-c:v", "copy"]
    aargs = ["-c:a", "aac", "-b:a", "320k"] if plan.get("need_a") else ["-c:a", "copy"]
    muxargs = ["-movflags", "+use_metadata_tags+faststart"]
    return ([str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
             "-i", str(src), "-map", "0:v:0", "-map", "0:a:0?"]
            + vargs + aargs + ["-map_metadata", "0"] + muxargs + [str(tmp)])


def editready_name(name: str) -> str:
    """`<stem>.editready.mp4` for a landed `<stem>.<ext>` (ensure_edit_ready's
    `tmp`; the h264 policy's out_ext is always .mp4)."""
    return str(Path(name).with_suffix("")) + EDITREADY_SUFFIX + ".mp4"


def converted_name(final: str) -> str:
    """`<title>.converted [id].mp4` for a deliverable `<title> [id].mp4`.

    The marker goes BEFORE the id bracket so the stem still ends in `[id]`
    (YT-6, 2026-08-28) -- see CONVERTED_SUFFIX. A name with no bracket group
    at all is not something this executor wrote, so it gets the marker on the
    end and is at least distinguishable; nothing downstream could have
    recognised it as a clip either way.
    """
    path = Path(final)
    stem, ext = path.stem, path.suffix
    match = _ID_TAIL_RE.match(stem)
    if match:
        return match.group("head") + CONVERTED_SUFFIX + match.group("id") + ext
    return stem + CONVERTED_SUFFIX + ext


def swap_in(tmp: Path, final: Path, original: Path) -> tuple[str, Optional[str]]:
    """_swap_in, verbatim in effect: -> (name delivered, note or None).

    Windows refuses to overwrite or delete a file another process holds open
    -- a clip already in an open Resolve project fails os.replace() with
    "Access is denied". A plain rename of the locked file IS allowed, so the
    original is moved aside to `.original` instead of deleted; and if even
    that fails, the converted file is delivered under `converted_name` rather
    than the work being thrown away. The note is what on_status said, and it
    rides the clip row (_download_one merges it into `note`) because an odd
    name in a term folder with no explanation anywhere is how COMP-BROLL-4 and
    YT-6 both got misread.
    """
    same = os.path.abspath(str(final)) == os.path.abspath(str(original))
    try:
        if not same:
            os.remove(original)
        os.replace(tmp, final)
        return final.name, None
    except OSError:
        pass
    aside = Path(str(original.with_suffix("")) + ORIGINAL_SUFFIX + original.suffix)
    try:
        os.replace(original, aside)
        os.replace(tmp, final)
    except OSError:
        pass
    else:
        # The size is deliberately NOT in this note: the file is reported as
        # reclaimable on the next attempt at the same clip (YT-6), when the
        # id-scoped retry has actually tried to delete it and failed. Saying
        # "N bytes to reclaim" here would be saying it about a file we have not
        # yet asked to remove.
        return final.name, f"original was in use, kept as {aside.name}"
    # Neither the original's name nor its place could be taken. Deliver the
    # converted file under a name whose stem still ends in `[id]`, so the
    # importer and the dedupe scan can both read it as the clip.
    keep = final.with_name(converted_name(final.name))
    try:
        os.replace(tmp, keep)
    except OSError:
        return tmp.name, (f"converted, but could not replace {original.name}: "
                          f"saved as {tmp.name}")
    return keep.name, (f"converted, but {original.name} was in use: "
                       f"saved as {keep.name}")


def _size_of(path: Any) -> int:
    """A file's size, or 0 for anything that cannot be stat'd."""
    try:
        return int(Path(path).stat().st_size)
    except (OSError, ValueError):
        return 0


def _reclaimable_bytes(size: int) -> str:
    """A byte count for a clip note (YT-6).

    The space a locked-aside original is holding is REPORTED rather than
    silently reclaimed: it is a real download, the editor may have it open in
    Resolve this second, and a sentence saying how much is there is what lets
    a human choose. No em dashes and no locale (the note reaches an editor).
    """
    size = int(size or 0)
    if size >= 1024 ** 3:
        return f"{size / 1024 ** 3:.1f} GB"
    if size >= 1024 ** 2:
        return f"{size / 1024 ** 2:.0f} MB"
    return f"{size} bytes"


def _configured_ffmpeg(cfg: dict[str, Any]) -> str:
    return str((cfg or {}).get("ffmpeg_path",
                               config_mod.DEFAULTS.get("ffmpeg_path", "ffmpeg")) or "")


def _ffprobe_binary(cfg: dict[str, Any]) -> Optional[str]:
    """This machine's ffprobe, or None when there is none to run.

    ffmpeg_tools.ffprobe_for answers the SIBLING of the resolved ffmpeg and
    falls back to the bare name; the bare name is only worth anything when
    PATH has it. None -- rather than the vendored "convert on suspicion" -- is
    the one deliberate deviation from ensure_edit_ready, because on this side
    the cost of that suspicion is a needless full re-encode of EVERY clip on
    an editor's laptop, not a container CPU. The sidecar installs ffprobe
    beside ffmpeg (sidecar_tools.TOOLS), so None is a machine somebody set up
    by hand, and it is logged as such.
    """
    try:
        candidate = ffmpeg_tools.ffprobe_for(_configured_ffmpeg(cfg))
    except Exception:
        return None
    if os.path.isabs(candidate) and os.path.exists(candidate):
        return candidate
    return shutil.which(candidate)


def _ffmpeg_binary(cfg: dict[str, Any]) -> Optional[str]:
    try:
        return ffmpeg_tools._resolve_binary(_configured_ffmpeg(cfg))
    except Exception:
        return None


def info_scratch_dir() -> Optional[Path]:
    """Where `--write-info-json` may write, OUTSIDE the canonical tree.

    COMP-BROLL-1's destination (see INFO_JSON_DIR_NAME for what writing it
    beside the footage cost). None when neither candidate can be created, which
    the caller answers by not asking yt-dlp for an info json at all: a clip with
    no credits sidecar is a smaller problem than permanent fleet-wide litter,
    and write_sidecar already handles "there was no info json" as an ordinary
    outcome.
    """
    candidates = []
    try:
        candidates.append(ytdlp_manager.tools_dir().parent / INFO_JSON_DIR_NAME)
    except Exception:
        log.debug("ytdl: could not derive the tools dir", exc_info=True)
    try:
        candidates.append(Path(tempfile.gettempdir()) / ("ccsync-" + INFO_JSON_DIR_NAME))
    except Exception:
        log.debug("ytdl: could not derive a temp dir", exc_info=True)
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except OSError as exc:
            log.debug("ytdl: %s is not usable for info json (%s)", candidate, exc)
    log.warning("ytdl: nowhere outside the project tree to put yt-dlp's info "
                "json -- downloading without one, so these clips get no "
                "credits sidecar")
    return None


def info_json_template(scratch: Any) -> str:
    """The `-o infojson:` template. `%(id)s` and nothing else from the clip.

    Deliberately NOT the outtmpl: this file never travels, so it needs no
    uploader/title (which is also what keeps it clear of Windows' 260-character
    limit, COMP-BROLL-8's neighbour). yt-dlp forces the extension to
    `info.json` for this output type, so the result is `<scratch>/<id>.info.json`
    -- a name this side can predict without parsing yt-dlp's output. Measured
    against yt-dlp 2026.08.04 on 2026-08-14: `-o infojson:<abs path>` is
    honoured even though the default `-o` is absolute (`--paths` is NOT, which
    is why this is spelled as a second output template and not as `-P`).
    """
    return "infojson:" + os.path.join(str(scratch), "%(id)s.%(ext)s")


def scratch_info_json(scratch: Any, video_id: str) -> Optional[Path]:
    """The redirected info json for one clip, or None if it is not there."""
    if not scratch or not video_id:
        return None
    candidate = Path(str(scratch)) / f"{video_id}.info.json"
    try:
        return candidate if candidate.is_file() else None
    except OSError:
        return None


def info_json_for(outdir: Any, video_id: str, video_name: Optional[str]) -> Optional[Path]:
    """The `--write-info-json` file for this clip IN THE TREE, or None.

    yt-dlp writes it as `<name-without-extension>.info.json`, so the video's
    own name answers it directly; the id scan is the fallback for the case
    where the video is not where we expected but its metadata is.

    Since COMP-BROLL-1 this is the fallback path only -- the info json is
    redirected out of the tree (info_json_template) and normally found by
    scratch_info_json. It stays because a yt-dlp that ignored the per-type
    output template would otherwise silently lose every sidecar, and because
    the sidecar has to be written from wherever the info json actually is.
    """
    directory = Path(str(outdir))
    if video_name:
        candidate = directory / (Path(video_name).stem + ".info.json")
        if candidate.exists():
            return candidate
    for name in sorted(id_bearing_files(directory, video_id)):
        if name.endswith(".info.json"):
            return directory / name
    return None


def write_sidecar(video_path: Path,
                  info_path: Optional[Path]) -> tuple[Optional[str], Optional[dict]]:
    """`<video>.credits.json` from yt-dlp's info json, then delete the info json.

    -> (sidecar path or None, the parsed info dict or None). The dict is handed
    back rather than discarded because the clip's `done` post carries the title
    and channel into the ledger (YTDL-WEB-8, 2026-08-14): a pasted-link job's
    row has no channel at all until a download reports one, and this is the
    only place on this side that ever knows it. The two halves are deliberately
    INDEPENDENT -- a parsed dict whose sidecar could not be written is still
    the right answer for the status post (COMP-BROLL-8's other half).

    The sidecar is the contract (ytdl_common.credits_sidecar/sidecar_path); the
    info json is 40-200 KB of yt-dlp internals per clip and is NOT -- the
    downstream Resolve credits script reads the sidecar, and the NAS worker
    produces no info json at all (downloader.build_opts sets no writeinfojson;
    it reads the info dict in-process). Deleting it is housekeeping in the
    scratch dir it now lives in, not the fleet-wide hazard it was before
    COMP-BROLL-1 moved it out of the tree.

    ONLY ON SUCCESS, though (COMP-BROLL-8, 2026-08-14): the unlink used to run
    whatever happened above it, so an unreadable info json or a failed sidecar
    write -- a full disk, a share that dropped, a name over Windows' 260
    characters -- destroyed the one artifact the credits could have been
    rebuilt from, for a clip that is then reported `done` and never revisited.
    A leftover info json is recoverable; a deleted one is not.

    Never raises: a clip that landed is a clip that landed, sidecar or not.
    """
    if info_path is None:
        log.info("ytdl: no info json beside %s -- no credits sidecar written",
                 video_path.name)
        return None, None
    try:
        info = json.loads(info_path.read_text(encoding="utf-8"))
    except Exception:
        log.warning("ytdl: could not read %s -- no credits sidecar written",
                    info_path.name, exc_info=True)
        info = None
    if not isinstance(info, dict):
        info = None
    target = None
    if info is not None:
        target = ytdl_common.sidecar_path(str(video_path))
        try:
            # `indent=2, ensure_ascii=False`, matching downloader._write_sidecar
            # exactly: §5 says BYTE-identical artifacts, and ensure_ascii
            # defaults to True -- so without it every CJK or accented title
            # would be \u-escaped here and literal on the NAS. Same file, two
            # encodings, one canonical tree.
            #
            # newline="\n" for the other half of the same rule: text mode
            # translates "\n" to os.linesep, so a Windows editor would write
            # CRLF into a file the Linux container writes LF into -- two byte
            # streams for one artifact, and on the base rig (whose local_root
            # IS the NAS share) both spellings would land in the same folder.
            # The repo learned this once already, from a CRLF run.sh that took
            # the dashboard down (.gitattributes, CLAUDE.md).
            Path(target).write_text(
                json.dumps(ytdl_common.credits_sidecar(info), indent=2,
                           ensure_ascii=False),
                encoding="utf-8", newline="\n")
        except OSError:
            log.warning("ytdl: could not write the credits sidecar for %s -- "
                        "keeping %s so it can be rebuilt from",
                        video_path.name, info_path.name, exc_info=True)
            target = None
    if target is None:
        return None, info
    try:
        info_path.unlink()
    except OSError:
        log.debug("ytdl: could not remove %s", info_path, exc_info=True)
    return target, info


# ---------------------------------------------------------------------------
# the job
# ---------------------------------------------------------------------------


class DownloadJob:
    """One claimed job, executed on this machine. One at a time (see start()).

    Threads: the caller's daemon thread runs run(); a second daemon thread
    heartbeats the lease while it does. The heartbeat thread is the only thing
    that can cut a download short, and it does so for exactly one reason -- a
    410, i.e. the server has taken the job back.
    """

    def __init__(self, job_id: int, deps: Deps) -> None:
        self.job_id = int(job_id)
        self.deps = deps
        self.client: Optional[FleetClient] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()          # tray shutdown
        self._lease_lost = threading.Event()    # a 410, anywhere
        self._proc: Optional[Any] = None
        self._current: Optional[tuple] = None   # (outdir, video_id) in flight
        # Resolved once per job, when there is work: yt-dlp's info json goes
        # here and NEVER into the project tree (COMP-BROLL-1). None = this
        # machine has nowhere to put one, so none is asked for.
        self.info_dir: Optional[Path] = None
        self.running = True
        self.total = 0
        self.done = 0
        self.failed = 0
        self.clip: Optional[str] = None
        # The clip in flight, from yt-dlp's own progress line (2026-08-25):
        # bytes so far, the total it expects (or estimates), and its rate in
        # bytes/s. None = not known yet, or between clips (merging, the pause).
        self.bytes_done: Optional[int] = None
        self.bytes_total: Optional[int] = None
        self.speed_bps: Optional[float] = None
        # "downloading" while yt-dlp runs, "converting" while ffmpeg does
        # (CR-79): the tray must not read a ten-minute re-encode as a stalled
        # download. None between clips and before the first.
        self.phase: Optional[str] = None
        # Which path the NEXT clip is tried on first (plan WP3, 2026-08-26).
        # Anonymous, always, at the start of a job: the jar is the fallback,
        # and a flip that does not survive the job is the safe direction.
        self._cookies_first = False
        # The breaker (plan WP6): the last clip failure's normalised signature
        # and how many in a row have carried it.
        self._last_signature: Optional[str] = None
        self._identical_failures = 0
        # ONE yt-dlp update poke per job, not per clip.
        self._update_poked = False

    # -- progress mirror --------------------------------------------------
    def snapshot(self) -> dict:
        """What GET /ytdl/progress answers, and what the tray line is built
        from. The SERVER rows remain the truth (§7) -- this exists so the SPA
        can show something in the first seconds, before the first status post
        has made the round trip, and so the tray can say how fast."""
        with self._lock:
            return {"job_id": self.job_id, "running": self.running,
                    "clip": self.clip, "done": self.done,
                    "failed": self.failed, "total": self.total,
                    "bytes_done": self.bytes_done,
                    "bytes_total": self.bytes_total,
                    "speed_bps": self.speed_bps,
                    "phase": self.phase}

    def _on_ytdlp_line(self, line: str) -> None:
        """One line of yt-dlp's stdout. Only the progress template's lines
        matter (PROGRESS_PREFIX); everything else is yt-dlp talking to itself.
        Never raises: default_run swallows anyway, but a parse error here must
        not even cost the one update."""
        parsed = parse_progress_line(line)
        if parsed is not None:
            self._set(**parsed)

    def _set(self, **fields) -> None:
        with self._lock:
            for key, value in fields.items():
                setattr(self, key, value)

    # -- lease ------------------------------------------------------------
    def _register_proc(self, proc: Any) -> None:
        with self._lock:
            self._proc = proc
        if self._lease_lost.is_set() or self._stop.is_set():
            # The lease went away between the decision to spawn and the spawn
            # itself. Kill it here rather than let a download run on for an
            # hour on a job the server has already taken back.
            self._kill_proc()

    def _kill_proc(self) -> None:
        with self._lock:
            proc = self._proc
        if proc is None:
            return
        try:
            proc.kill()
        except Exception:
            log.debug("ytdl: could not kill yt-dlp", exc_info=True)

    def lose_lease(self, why: str) -> None:
        """A 410 arrived. Stop everything, quietly (module docstring, rule 2)."""
        if self._lease_lost.is_set():
            return
        self._lease_lost.set()
        log.info("ytdl: job %s is no longer ours (%s) -- stopping; the server "
                 "downloads what is missing", self.job_id, why)
        self._kill_proc()

    def stop(self) -> None:
        """Tray shutdown. Same shape as broll_fetch.stop_all's cancel: killing
        mid-download is safe, because the litter it leaves is id-scoped and the
        next executor -- ours or the server's -- clears it."""
        self._stop.set()
        self._kill_proc()

    def _should_stop(self) -> bool:
        return self._lease_lost.is_set() or self._stop.is_set()

    def _heartbeat_loop(self, interval: float) -> None:
        while not self._stop.wait(interval):
            if self._lease_lost.is_set():
                return
            try:
                self.client.heartbeat(self.job_id)
            except LeaseLost as exc:
                self.lose_lease(str(exc))
                return
            except Exception as exc:
                # A blip, not a verdict: the lease is 180 s and this runs every
                # 30 s, so six failures in a row are needed before it matters --
                # and when it does, the next call answers 410 and we stop then.
                log.debug("ytdl: heartbeat for job %s failed (%s)", self.job_id, exc)

    # -- the run ----------------------------------------------------------
    def run(self) -> None:
        """Thread target. Never raises, never leaves the module guard held."""
        try:
            self._run()
        except LeaseLost as exc:
            self.lose_lease(str(exc))
            self._cleanup_current()
        except Exception:
            log.exception("ytdl: job %s failed", self.job_id)
        finally:
            self._set(running=False, clip=None)
            _release(self)

    def _run(self) -> None:
        cap = capabilities(self.deps)
        if not cap["ok"]:
            log.info("ytdl: job %s not started -- %s", self.job_id, cap["reason"])
            return

        # BEFORE the claim (§7, the 0.7.x free-space lesson). The claim body
        # wants the number anyway, so this costs nothing extra.
        free = cap["free_bytes"]
        needed = MIN_FREE_BYTES_MARGIN + NOMINAL_JOB_BYTES
        if free is not None and free < needed:
            log.warning(
                "ytdl: %.1f GB free on this machine but a download job needs "
                "about %.1f GB -- not claiming job %s. The server downloads it.",
                free / 1_000_000_000, needed / 1_000_000_000, self.job_id)
            return

        editor = cap["editor"]
        # should_stop is the job's own predicate: _call's retry (CR-31) must
        # not sit out a 60 s budget after the tray has asked us to quit or the
        # heartbeat has already learned the lease is gone.
        # The sleep is the stop Event's wait, not time.sleep: a tray shutdown
        # during a backoff should be felt at once rather than up to
        # CALL_RETRY_MAX_BACKOFF later.
        self.client = FleetClient(self.deps, editor,
                                  should_stop=self._should_stop,
                                  sleep=self._stop.wait)
        lease = self.client.claim(self.job_id, cap["ytdlp_version"], free)
        if lease is None:
            return

        heartbeat = _positive_number(lease.get("heartbeat_seconds"),
                                     DEFAULT_HEARTBEAT_SECONDS)
        thread = threading.Thread(target=self._heartbeat_loop, args=(heartbeat,),
                                  name=f"ccsync-ytdl-hb-{self.job_id}", daemon=True)
        thread.start()
        try:
            self._download_all()
        finally:
            # Stops the heartbeat WITHOUT ending the lease: there is no
            # "release" call in routes_fleet, and there does not need to be --
            # the server reclaims on expiry (<=lease_seconds, shipped as 180 s)
            # and then downloads only what is missing (§3). That is the exit
            # path for every early return below, and it is cheap and honest:
            # three minutes of a job sitting still, versus a second endpoint
            # whose failure mode is a job nobody owns.
            self._stop.set()

    def _download_all(self) -> None:
        manifest = self.client.manifest(self.job_id)
        if not manifest:
            return

        # Belt to the claim's braces: routes_fleet.claim already refuses a
        # template skew (410), so reaching here means the server changed its
        # mind mid-job or a proxy served a stale answer. Either way, downloading
        # under a template we do not share is the one thing §5 forbids.
        template = manifest.get("template_version")
        if template != ytdl_common.TEMPLATE_VERSION:
            log.warning("ytdl: job %s speaks naming template %s, this build "
                        "speaks %s -- handing it back", self.job_id, template,
                        ytdl_common.TEMPLATE_VERSION)
            return

        # The other half of the same handshake (COMP-BROLL-6). Checked here as
        # well as in the claim because the two numbers fail differently: a
        # template skew duplicates clips, a sidecar skew feeds the Resolve
        # credits script a shape it does not read -- and the second is invisible
        # in the tree, so nothing else would ever notice it.
        sidecar = manifest.get("sidecar_version")
        if sidecar != ytdl_common.SIDECAR_VERSION:
            log.warning("ytdl: job %s wants credits sidecar version %s, this "
                        "build writes %s -- handing it back", self.job_id,
                        sidecar, ytdl_common.SIDECAR_VERSION)
            return

        quality = str(manifest.get("quality") or "").strip()
        if quality not in SCOPE_QUALITIES:
            # The SPA does not know the quality when it dispatches (it sends a
            # job id and nothing else, §8), so this cannot be declined before
            # the claim. Nothing is posted and nothing is downloaded; the lease
            # simply expires and the server picks the job up as if no companion
            # had ever answered. See SCOPE_QUALITIES for why these rungs are
            # not ours to run.
            log.info("ytdl: job %s is a %s job, which only the server can name "
                     "correctly -- letting the lease expire", self.job_id,
                     quality or "(no quality)")
            return

        label = manifest.get("project_label")
        if not self._label_is_ours(label):
            return

        outdir = destination_for(self.deps.cfg, manifest.get("project_rel_path"))
        if not outdir:
            log.warning("ytdl: job %s named a destination this machine cannot "
                        "resolve (%r) -- downloading nothing", self.job_id,
                        manifest.get("project_rel_path"))
            return
        # RE-CHECKED HERE, with the full probe (comp-ytdl-1, 2026-08-21):
        # capabilities() answered when the SPA asked, the claim and the
        # manifest are two round trips later, and the mkdir below is the line
        # that would create a fake /Volumes/<Name> on a Mac's boot disk. The
        # job is not failed, it is left alone -- the lease expires and the
        # server downloads it, which is what every other refusal on this path
        # does.
        if self.deps.tree_is_misplaced():
            log.warning("ytdl: job %s -- this machine's tree is not mounted, so "
                        "nothing is being downloaded into %s (the server will)",
                        self.job_id, outdir)
            return
        try:
            Path(outdir).mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("ytdl: could not create %s (%s) -- downloading nothing",
                        outdir, exc)
            return

        clips = [c for c in (manifest.get("clips") or []) if isinstance(c, dict)]
        pause = _positive_number(manifest.get("download_pause_seconds"),
                                 DEFAULT_PAUSE_SECONDS)
        self.info_dir = info_scratch_dir()
        self._set(total=len(clips))
        log.info("ytdl: job %s -- %d clip(s) at %s into %s", self.job_id,
                 len(clips), quality, outdir)

        for index, clip in enumerate(clips):
            if self._should_stop():
                self._cleanup_current()
                return
            wall = self._breaker_reason()
            if wall is not None:
                # Handed back the way every other refusal on this path is
                # (§2 step 7, and the "no release endpoint" rule): stop
                # posting, let the heartbeat stop and the lease expire, and
                # the server reclaims the job and downloads what is missing.
                # The clips already reported `failed` are re-queued by its
                # second-chance sweep exactly as they would have been.
                log.warning("ytdl: job %s -- %d clips in a row failed the same "
                            "way (%s), so this machine is stopping at clip %d "
                            "of %d and handing the rest back to the server",
                            self.job_id, self._identical_failures, wall,
                            index + 1, len(clips))
                return
            if index:
                # Residential pacing, server-provided (§7): the NAS's 3 s is a
                # bot-check defence for ONE static IP, and an editor's own line
                # can afford to be gentler or brisker as the server decides.
                self.deps.sleep(pause)
                if self._should_stop():
                    self._cleanup_current()
                    return
            self._download_one(clip, outdir, quality)

    def _label_is_ours(self, label: Any) -> bool:
        """Does this machine sync the project the manifest names? (§7)

        THE POINT IS THE DISK, not authorisation: the token already proved the
        caller is our dashboard. A server bug that pointed an editor's machine
        at a project it does not sync would write gigabytes into a folder
        nothing on that machine watches, uploads or ever cleans up -- and on
        the base rig, straight into the canonical tree under a label nobody
        chose.

        The base rig is the documented exception and not a hole: its local_root
        IS the NAS share, so it "syncs" every project by definition and has no
        selection to check against. The directory-exists test replaces it,
        which still refuses a label that names nothing real.
        """
        wanted = normalize_label(label)
        if not wanted:
            log.warning("ytdl: job %s named no project label -- downloading "
                        "nothing", self.job_id)
            return False
        if self.deps.is_base_rig:
            root = projects_root(self.deps.cfg)
            # The label's OWN spelling, not the casefolded comparison form
            # (comp-ytdl-5, 2026-08-21): `wanted` exists to compare against
            # the selection labels, and stat-ing it turned "2026/FF5/Energy
            # Transition" into "2026/ff5/energy transition" -- the same
            # directory on NTFS and default APFS, and no directory at all on a
            # case-sensitive volume (case-sensitive APFS, a Mac SMB mount of a
            # case-sensitive ZFS dataset). There the job was refused, the
            # lease expired, and nothing was ever downloaded on that rig. This
            # is the spelling destination_for writes with.
            parts = [p for p in _label_parts(label) if p]
            here = Path(root).joinpath(*parts) if root and parts else None
            if here is not None and here.is_dir():
                return True
            log.warning("ytdl: job %s names project %r, which is not in this "
                        "base rig's tree -- downloading nothing", self.job_id,
                        label)
            return False
        labels = self.deps.selection_labels()
        if labels is None:
            log.warning("ytdl: job %s names project %r and this machine cannot "
                        "confirm what it syncs -- downloading nothing (the "
                        "server will)", self.job_id, label)
            return False
        if wanted in labels:
            return True
        log.warning("ytdl: job %s names project %r, which this machine does not "
                    "sync -- downloading nothing", self.job_id, label)
        return False

    # -- one clip ---------------------------------------------------------
    def _download_one(self, clip: dict, outdir: str, quality: str) -> None:
        video_id = str(clip.get("video_id") or "").strip()
        url = clip.get("url")
        if not video_id:
            log.warning("ytdl: job %s has a clip with no video id -- skipping it",
                        self.job_id)
            return
        # The previous clip's numbers must not sit under this clip's name
        # for the seconds before its first progress line.
        self._set(clip=video_id, bytes_done=None, bytes_total=None,
                  speed_bps=None, phase="downloading")
        if not url_is_youtube(url):
            # Recorded as a failure rather than silently skipped: the row has to
            # say something, and the server's second-chance sweep is what gets
            # the editor their clip if the URL is fine and this check is wrong.
            log.warning("ytdl: job %s clip %s: refusing a non-YouTube URL (%r)",
                        self.job_id, video_id, url)
            self.client.clip_status(self.job_id, video_id, "failed",
                                    error="the download URL was not a YouTube "
                                          "URL, so this machine refused it")
            self._set(failed=self.failed + 1)
            return

        # Marked in flight BEFORE the first post, not after: if the `downloading`
        # post is the call that answers 410, this clip is still the one whose
        # litter has to be cleaned on the way out.
        self._current = (outdir, video_id)
        # What was already there, for disown_output: a corpse this attempt did
        # not create belongs to whoever did (worker._record_failure's `before`).
        before = id_bearing_files(outdir, video_id)
        # YT-6 (2026-08-28): the delete a previous conversion could not do,
        # retried now that Resolve has probably let go of the file. Before the
        # download, so `before` already reflects it and the space is free for
        # the bytes about to arrive.
        _reclaimed, still_held = clear_aside_originals(outdir, video_id)
        self.client.clip_status(self.job_id, video_id, "downloading")

        ok, note, error = self._run_ytdlp_with_fallback(url, outdir, quality, video_id)
        if self._should_stop():
            # A lost lease (or a tray shutdown) killed the child. Nothing is
            # posted -- the job is not ours to report on any more -- and this
            # clip's own litter goes with it.
            self._cleanup_current()
            return

        if not ok:
            self._fail_clip(outdir, video_id, before, error)
            return

        name = landed_file(outdir, video_id)
        if not name:
            # yt-dlp exited 0 and left nothing whose stem ends in [id]. Reported
            # as a failure for YTDL-15's reason, applied on this side: a `done`
            # with no file writes a ledger row that says "the fleet already has
            # this" and points at nothing, and the ledger never cascades.
            self._fail_clip(outdir, video_id, before,
                            "yt-dlp reported success but left no output file")
            return

        # Resolve has to be able to decode it (CR-79). Same probe, same
        # decision, same ffmpeg command as the server's ensure_edit_ready,
        # run here instead of handing the clip back.
        name, conv_note, conv_error = self._ensure_edit_ready(outdir, name, video_id)
        if self._should_stop():
            self._cleanup_current()
            return
        if conv_error:
            self._fail_clip(outdir, video_id, before, conv_error)
            return
        if conv_note:
            note = f"{note}; {conv_note}" if note else conv_note
        if still_held:
            # Reported, never quietly reclaimed (YT-6): the aside file is a
            # whole download and the editor may have it open in a timeline.
            held = (f"an earlier copy of this clip is still in use "
                    f"({_reclaimable_bytes(still_held)} reclaimable)")
            note = f"{note}; {held}" if note else held

        video_path = Path(outdir) / name
        # The scratch copy first (COMP-BROLL-1); the in-tree one is the fallback
        # for a yt-dlp that ignored the per-type output template.
        info_path = (scratch_info_json(self.info_dir, video_id)
                     or info_json_for(outdir, video_id, name))
        _sidecar, info = write_sidecar(video_path, info_path)
        # The ledger's title and channel, from the one dict on this machine
        # that knows them (YTDL-WEB-8). Read through credits_sidecar rather
        # than off the info dict directly so the `channel or uploader` fallback
        # is the SAME one the sidecar and the NAS worker use -- a clip must not
        # be credited to one name in its sidecar and another in the ledger.
        credits = ytdl_common.credits_sidecar(info) if info else {}
        self.client.clip_status(self.job_id, video_id, "done",
                                filepath_rel=name, note=note,
                                title=credits.get("title"),
                                channel=credits.get("channel"))
        self._set(done=self.done + 1)
        self._current = None
        # A clip that landed is proof the wall is not there any more, so the
        # breaker counts CONSECUTIVE failures and this is where the count dies.
        self._last_signature = None
        self._identical_failures = 0

    def _ensure_edit_ready(self, outdir: str, name: str,
                           video_id: str) -> tuple[str, Optional[str], Optional[str]]:
        """-> (name delivered, note or None, error or None).

        ensure_edit_ready, on this machine, through this executor's seams:
        deps.run for both subprocesses (windowless, sanitized env), the kill
        handle so a lost lease ends a re-encode the way it ends a download,
        and `phase` on the progress mirror so the tray says "Converting".

        The three outcomes are the vendored ones. Fine as downloaded, or
        converted and swapped in: the name (and a note when the swap had to
        improvise). Conversion failed after the probe SAID it was needed: an
        error, which _download_one turns into a failed clip -- the download
        is still there and _fail_clip disowns it, so the server's sweep
        starts over. Conversion failed after the probe merely FAILED: kept as
        downloaded with a note, because losing the video over a guess is
        worse than delivering it (YTDL-22).
        """
        src = Path(outdir) / name
        ffprobe = _ffprobe_binary(self.deps.cfg)
        if not ffprobe:
            log.warning("ytdl: job %s clip %s: no ffprobe beside this machine's "
                        "ffmpeg, so the clip is delivered as downloaded and "
                        "unchecked (the sidecar normally installs one)",
                        self.job_id, video_id)
            return name, None, None
        try:
            proc = _call_run(self.deps.run, probe_argv(ffprobe, src),
                             PROBE_TIMEOUT_SECONDS, self._register_proc, None)
            probe = parse_probe(proc)
        except subprocess.TimeoutExpired:
            probe = {"_probe_error": "ffprobe did not answer in time"}
        except Exception as exc:  # noqa: BLE001
            probe = {"_probe_error": f"{type(exc).__name__}: {exc}"}
        finally:
            with self._lock:
                self._proc = None
        if self._should_stop():
            return name, None, None
        plan = edit_ready_plan(probe)
        if not plan["convert"]:
            return name, None, None

        ffmpeg = _ffmpeg_binary(self.deps.cfg)
        was = (plan["vcodec"] or "unprobeable") + (f"/{plan['acodec']}" if plan["acodec"] else "")
        if not ffmpeg:
            # capabilities() refused the job without ffmpeg, so this is a
            # binary that vanished mid-job. The vendored FileNotFoundError
            # branch: keep what we have.
            log.warning("ytdl: job %s clip %s needs converting (was %s) but "
                        "ffmpeg is gone; kept as downloaded", self.job_id, video_id, was)
            return name, "could not convert (no ffmpeg); kept as downloaded", None
        tmp = Path(outdir) / editready_name(name)
        self._set(phase="converting", bytes_done=None, bytes_total=None, speed_bps=None)
        log.info("ytdl: job %s clip %s: converting to H.264 (was %s)",
                 self.job_id, video_id, was)
        argv = edit_ready_argv(ffmpeg, src, tmp, plan)
        rc, stderr = 1, ""
        try:
            proc = _call_run(self.deps.run, argv, CONVERT_TIMEOUT_SECONDS,
                             self._register_proc, None)
            rc = int(getattr(proc, "returncode", 1) or 0)
            stderr = str(getattr(proc, "stderr", "") or "")
        except subprocess.TimeoutExpired:
            stderr = (f"ffmpeg did not finish within "
                      f"{CONVERT_TIMEOUT_SECONDS / 3600:.0f}h and was killed")
        except Exception as exc:  # noqa: BLE001
            stderr = f"ffmpeg could not be run: {exc}"
        finally:
            with self._lock:
                self._proc = None
            self._set(phase="downloading")
        if self._should_stop() or rc != 0 or not tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
            if self._should_stop():
                return name, None, None
            if plan["probe_failed"]:
                return name, ("could not probe the codecs and the safety "
                              "conversion failed; kept as downloaded"), None
            return name, None, ("Edit-ready conversion failed: "
                                + stderr.strip()[-500:])
        final = Path(outdir) / (str(Path(name).with_suffix("")) + ".mp4")
        delivered, note = swap_in(tmp, final, src)
        return delivered, note, None

    def _fail_clip(self, outdir: str, video_id: str, before: set,
                   error: str) -> None:
        """This clip is over. Disown what it landed, delete what it half-landed.

        worker._record_failure's order and its reason: ANY final failure can
        leave a `.part` behind (SAQBbd1Rxmo, 2026-08-13), and a clip that has
        finished failing has no resume state worth keeping -- the server's
        second-chance sweep starts it over from nothing (§2 step 7).

        LOGGED since CR-39 (2026-08-19). It was not, and that is most of why
        CR-39 took a morning of studio time to find: every local download was
        failing on a 403 three seconds in, this function reported it to the
        server and reset the row, and the companion log went from "job 53 -- 1
        clip(s)" straight to the next job with nothing in between. The editor
        saw the badge flash "downloading on your machine" and settle back on
        "the server", and there was no line anywhere on their machine saying
        why. A clip failure is ordinary -- the server retries it -- but
        ordinary is not the same as invisible.
        """
        log.warning("ytdl: job %s clip %s failed on this machine (%s) -- the "
                    "server will retry it", self.job_id, video_id,
                    str(error or "no error text")[:300])
        disown_output(outdir, video_id, before)
        clear_partials(outdir, video_id)
        self._drop_scratch_info(video_id)
        self.client.clip_status(self.job_id, video_id, "failed", error=error)
        self._set(failed=self.failed + 1)
        self._current = None
        self._note_failure(error)

    def _note_failure(self, error: Any) -> None:
        """Count this failure against the breaker; poke the updater if the
        signature says the BINARY, not the video, is what is wrong."""
        sig = failure_signature(error)
        if sig and sig == self._last_signature:
            self._identical_failures += 1
        else:
            self._last_signature = sig
            self._identical_failures = 1
        self._maybe_poke_ytdlp(error)

    def _breaker_reason(self) -> Optional[str]:
        """The signature this machine has hit N times in a row, or None.

        Plan WP6, 2026-08-26, and it is _bot_checked's rule generalised: A
        FAILURE THAT WILL REPEAT IDENTICALLY FOR EVERY REMAINING CLIP MUST
        STOP THE RUN, NOT THE CLIP. CR-80's job 28 discovered one wall 29
        times, each with yt-dlp's full retry budget behind it -- 29 chances to
        make YouTube angrier, for no information.
        """
        limit = max_identical_failures(self.deps.cfg)
        if limit and self._identical_failures >= limit:
            return self._last_signature or "the same failure"
        return None

    def _maybe_poke_ytdlp(self, error: Any) -> None:
        """Ask the sidecar manager to re-check yt-dlp, ONCE per job.

        Only for the two signatures that mean the binary rather than the video
        (_UPDATE_WORTH_TRYING). CR-80's fleet half was exactly this: every
        companion sat on a yt-dlp that could not download anything, reporting
        "2026.07.04 is current" nightly, because the floor it compared against
        was the one that shipped with it. ensure() re-reads the dashboard's
        floor, so the fix reaches a machine at its next failure instead of at
        its next daily check. Absent seam (no manager, an older one with no
        ensure) is simply no poke -- never a failed job.
        """
        if self._update_poked:
            return
        low = str(error or "").lower()
        if not any(marker in low for marker in _UPDATE_WORTH_TRYING):
            return
        ensure = getattr(getattr(self.deps, "ytdlp", None), "ensure", None)
        if not callable(ensure):
            return
        self._update_poked = True
        log.info("ytdl: job %s: that failure is what an out-of-date yt-dlp "
                 "looks like; asking the sidecar to re-check", self.job_id)
        try:
            result = dict(ensure() or {})
        except Exception:  # noqa: BLE001 -- a clip failure must not become a crash
            log.debug("ytdl: the yt-dlp re-check failed", exc_info=True)
            return
        log.info("ytdl: yt-dlp re-check: %s", result.get("message") or result.get("action"))

    def _drop_scratch_info(self, video_id: str) -> None:
        """Bin the redirected info json for a clip that will not get a sidecar.

        Housekeeping only -- it is outside the tree (COMP-BROLL-1), so nothing
        depends on it going. The one copy deliberately left behind is the one
        write_sidecar could not write a sidecar from (COMP-BROLL-8).
        """
        path = scratch_info_json(self.info_dir, video_id)
        if path is None:
            return
        try:
            path.unlink()
        except OSError:
            log.debug("ytdl: could not remove %s", path, exc_info=True)

    def _run_ytdlp_with_fallback(self, url: Any, outdir: str, quality: str,
                                 video_id: str) -> tuple[bool, Optional[str], Optional[str]]:
        """-> (ok, note, error). ONE rung down on a truncated stream, never two.

        The signature and the ladder are ytdl_common's, shared with the NAS
        worker, so both executors make the SAME call from the same evidence --
        or the fleet ends up with one clip at 1080p on the NAS and the same clip
        at 720p on an editor's machine, or a failure on one side and a silent
        downgrade on the other (SAQBbd1Rxmo, 2026-08-13).

        Matched as TEXT, on the binary's stderr: there is no DownloadError class
        on a CLI boundary -- ytdl_common.stream_truncated's docstring anticipates
        exactly this case -- so the class test it makes for the worker is
        replaced by "the process failed", and BOTH markers are still required.
        The byte-count phrase alone is the ordinary short read yt-dlp retries
        out of by itself; "giving up after" is what says the retry budget is
        spent and the FORMAT, rather than the moment, is the problem. Nothing
        else may cost an editor 360 lines of resolution nobody asked to lose.
        """
        ok, stderr, note, error = self._run_ytdlp_paths(url, outdir, quality, video_id)
        if ok:
            return True, note, None
        if self._should_stop():
            return False, None, None
        lower = (ytdl_common.lower_quality(quality, ytdl_common.QUALITY_HEIGHTS)
                 if _looks_truncated(stderr) else None)
        if lower is None or lower not in SCOPE_QUALITIES:
            return False, None, error or _error_tail(stderr)
        log.warning("ytdl: job %s: %s came back truncated at %s; retrying at %s",
                    self.job_id, video_id, quality, lower)
        # The .part IS the truncated bytes and yt-dlp resumes a .part, so the
        # retry has to start from nothing or it inherits the corpse.
        clear_partials(outdir, video_id)
        ok, stderr2, note2, error2 = self._run_ytdlp_paths(url, outdir, lower, video_id)
        if ok:
            truncated = ytdl_common.TRUNCATED_NOTE.format(q=quality, lower=lower)
            return True, (f"{truncated}; {note2}" if note2 else truncated), None
        return False, None, error2 or _error_tail(stderr2)

    def _run_ytdlp_paths(self, url: Any, outdir: str, quality: str,
                         video_id: str) -> tuple[bool, str, Optional[str], Optional[str]]:
        """One clip, ANONYMOUSLY FIRST, the cookie jar as the fallback.
        -> (ok, stderr of the last attempt, note, error).

        THE INVERSION (plan WP3, 2026-08-26). Until then every argv carried
        `--cookies` whenever a jar resolved, which is what made one flagged
        Google account fatal to everything this machine could download
        (CR-80): there was no path that did not carry the jar, so there was
        nothing to fall back to and nothing anywhere said why. Anonymous is
        the normal case and needs no account at all; the jar is the escape
        hatch, and it is spent only on the ONE failure it answers.

        Exactly one fallback attempt, and only on a classified failure:

          anonymous -> bot check    -> retry with the jar (if there is one)
          cookies   -> account flag -> retry anonymously
          both refused              -> BOTH_BLOCKED_ERROR, which names both

        The preference is STICKY per executor and starts anonymous: a job of
        forty clips must not re-discover the bot check forty times, and a
        machine that restarts starts anonymous again -- the safe direction,
        because an unnecessary anonymous attempt costs one extraction and an
        unnecessary cookies attempt spends the credential.

        Cost, honestly: one extra failed extraction per clip on a genuinely
        bot-checked line, before the flip. Seconds.
        """
        jar = _cookies_file(self.deps.cfg)
        first = jar if (self._cookies_first and jar) else None
        ok, stderr = self._run_ytdlp(url, outdir, quality, first)
        if ok:
            return True, "", self._landed_note(video_id, first), None
        if self._should_stop():
            return False, stderr, None, None

        if first is None:
            if not jar or not _bot_checked(stderr):
                return False, stderr, None, None
            log.info("ytdl: job %s clip %s: YouTube bot-checked the anonymous "
                     "download; retrying once with the signed-in session",
                     self.job_id, video_id)
            ok, stderr2 = self._run_ytdlp(url, outdir, quality, jar)
            if ok:
                self._prefer_cookies(True, "an anonymous download was bot-checked "
                                           "and the signed-in session worked")
                return True, "", self._landed_note(video_id, jar), None
            if _account_flagged(stderr2):
                return False, stderr2, None, BOTH_BLOCKED_ERROR
            return False, stderr2, None, None

        if not _account_flagged(stderr):
            return False, stderr, None, None
        log.info("ytdl: job %s clip %s: YouTube is refusing the signed-in "
                 "session; retrying once anonymously", self.job_id, video_id)
        ok, stderr2 = self._run_ytdlp(url, outdir, quality, None)
        if ok:
            self._prefer_cookies(False, "YouTube is refusing the signed-in "
                                        "session and anonymous downloads work")
            return True, "", self._landed_note(video_id, None), None
        if _bot_checked(stderr2):
            return False, stderr2, None, BOTH_BLOCKED_ERROR
        return False, stderr2, None, None

    def _landed_note(self, video_id: str, cookies: Optional[str]) -> Optional[str]:
        """Log which path landed the clip, and return the row's note for it.

        Logged for every clip (CR-39's lesson: a download path that is never
        named is a download path nobody can diagnose), noted on the row only
        for the fallback -- see COOKIES_PATH_NOTE.
        """
        log.info("ytdl: job %s clip %s: downloaded %s", self.job_id, video_id,
                 "with the signed-in YouTube session" if cookies else "anonymously")
        return COOKIES_PATH_NOTE if cookies else None

    def _prefer_cookies(self, cookies_first: bool, why: str) -> None:
        """Flip which path the NEXT clip tries first. Logs on the flip only:
        once per job is an operational signal, once per clip is noise."""
        if self._cookies_first == cookies_first:
            return
        self._cookies_first = cookies_first
        log.info("ytdl: job %s: downloading %s from now on (%s)", self.job_id,
                 "with the signed-in YouTube session" if cookies_first
                 else "anonymously", why)

    def _run_ytdlp(self, url: Any, outdir: str, quality: str,
                   cookies: Optional[str] = None) -> tuple[bool, str]:
        argv = self.build_argv(url, outdir, quality, cookies)
        try:
            proc = _call_run(self.deps.run, argv, CLIP_TIMEOUT_SECONDS,
                             self._register_proc, self._on_ytdlp_line)
        except subprocess.TimeoutExpired:
            return False, (f"yt-dlp did not finish within "
                           f"{CLIP_TIMEOUT_SECONDS / 3600:.0f}h and was killed")
        except Exception as exc:
            return False, f"yt-dlp could not be run: {exc}"
        finally:
            with self._lock:
                self._proc = None
        # THE PATH THIS ATTEMPT ACTUALLY RAN ON, not "is a jar configured"
        # (plan WP3, 2026-08-26). With the inversion, a machine with a perfectly
        # good jar makes anonymous attempts all day, and reading the config here
        # would credit an anonymous bot check to the editor's sign-in and light
        # the tray warning for a session nothing had touched.
        cookies_used = bool(cookies)
        if getattr(proc, "returncode", 1) == 0:
            # A cookied download that worked is proof the session is alive;
            # clear a stale mark so the tray warning goes away by itself once
            # things are fine again (2026-08-17).
            #
            # CYT-5 (usability sweep 2026-09-04): the clear used to be gated on
            # `self._cookie_health_stale` as well -- a PER-JOB memo, False in
            # every new DownloadJob -- so the record could only be cleared
            # inside the same job that wrote it. Every later successful cookied
            # download took this early return without calling mark_ok, and the
            # tray asked for a fresh sign-in forever, which is the exact
            # opposite of the comment above. The FILE is the authority now (one
            # small read, and only on the rare cookied path); the memo stays on
            # the write side below, where its job is one mark_stale per job
            # rather than forty.
            if cookies_used:
                self._cookie_health_stale = False
                if ytdl_cookies.recorded_status() == ytdl_cookies.STATUS_STALE:
                    ytdl_cookies.mark_ok(
                        "a download succeeded with the signed-in session")
            return True, ""
        stderr = str(getattr(proc, "stderr", "") or "")
        # The one thing worth reading out of a failure BEYOND the clip row:
        # yt-dlp telling us the editor's YouTube session is dead (rotated,
        # signed out, or -- since CR-80 -- flagged by YouTube). Recorded once,
        # not per clip; the tray warns from the record. The reason is written
        # in the editor's words (ytdl_cookies.stale_reason), because "yt-dlp:
        # the page needs to be reloaded" is the string that cost CR-80 a day.
        sig = ytdl_cookies.classify_failure(stderr, cookies_used)
        if sig and not self._cookie_health_stale:
            self._cookie_health_stale = True
            ytdl_cookies.mark_stale(ytdl_cookies.stale_reason(sig))
        return False, stderr

    # Per-executor memo so a batch of 40 age-gated clips writes the status
    # file once, not 40 times. Not authoritative -- the file is.
    _cookie_health_stale = False

    def build_argv(self, url: Any, outdir: str, quality: str,
                   cookies: Optional[str] = None) -> list:
        """The yt-dlp command line. The NAMING half of it is the contract.

        `cookies` is the jar to send, or None for an ANONYMOUS run (the
        default since plan WP3, 2026-08-26): which path a clip is tried on is
        _run_ytdlp_paths's decision, not this function's.

        `-f`, the outtmpl and the mp4 container are ytdl_common's and the
        server's build_opts', spelled the same way on purpose: same rung, same
        request to YouTube, same filename out. `prefer_avc=True` because the
        edit codec is h264 -- which is also why the rungs above 1080p are not
        run here at all (SCOPE_QUALITIES).

        The embedded credits tags are the same contract's other half
        (CREDITS_METADATA_ARGS, COMP-BROLL-2): the NAS embeds them, so a clip
        fetched here must too, or one folder holds two shapes of the same clip
        and only ffprobe can tell.

        --no-playlist because a URL that turned out to name a playlist must not
        become forty unasked-for downloads on an editor's disk; --write-info-json
        because the credits sidecar is built from it -- redirected OUT of the
        project tree, because that folder syncs fleet-wide and a delete in it
        does not (COMP-BROLL-1); --ffmpeg-location because the merge needs it
        and the proxy generator already knows where it is (§6: no new binary
        management). The flag is conditional only for a caller who bypassed
        capabilities(), which refuses the job when ffmpeg does not resolve.
        """
        argv = [
            str(self.deps.ytdlp_binary()),
            "-f", ytdl_common.format_selector(quality, prefer_avc=True),
            "--merge-output-format", "mp4",
            "-o", ytdl_common.outtmpl(outdir),
            "--no-playlist",
            # --no-mtime: the finished file keeps TODAY as its mtime instead of
            # the media response's Last-Modified, which for YouTube is usually
            # the upload date (YT-3, resilience sweep 2026-08-28). Lane A's only
            # stability gate on this tree is `--min-age 120s`, so a file stamped
            # 2019 was eligible the instant it appeared: the pre-conversion VP9
            # original could go up under the final name, and lane A is
            # `copy --ignore-existing`, whose rule is that the first version of
            # a name to reach the NAS is the only one that ever will. That is
            # CR-79's undecodable clip arriving through the sync lane. With this
            # flag --min-age is a real gate again.
            "--no-mtime",
            # Progress as ONE machine-readable line per update, on stdout,
            # where default_run's pump reads it (2026-08-25, the owner: the
            # tray should say "Downloading: x/x (xx MB/s)"). --newline because
            # yt-dlp's default progress is a carriage-return-rewritten bar
            # that never reaches a pipe as lines; the template because its
            # human bar is not something to parse. Replaced --no-progress,
            # which is why the tray said nothing about a download for a year.
            "--progress", "--newline",
            "--progress-template", PROGRESS_TEMPLATE,
            # Fragments in flight (CR-74's fix, applied here 2026-08-25).
            # web_safari serves HLS, and HLS fragments fetched one at a time
            # run at whatever pace YouTube gives ONE connection: 3-4 MiB/s on
            # a long clip against 53 MiB/s with six in flight, measured on the
            # server. The editor's download walked the same ladder the same
            # way and read as "the youtube downloads are going very slowly".
            "-N", str(fragment_jobs(self.deps.cfg)),
        ]
        argv += list(CREDITS_METADATA_ARGS)
        if self.info_dir is not None:
            argv += ["--write-info-json", "-o", info_json_template(self.info_dir)]
        ffmpeg_dir = _ffmpeg_location(self.deps.cfg)
        if ffmpeg_dir:
            argv += ["--ffmpeg-location", ffmpeg_dir]
        # A JavaScript runtime, when the sidecar installed one (COMP-YTDL,
        # 2026-08-16). yt-dlp enables only deno by default and the official
        # yt-dlp.exe bundles none, so WITHOUT this an anonymous download still
        # works (yt-dlp's deprecated no-runtime path) but the moment cookies
        # are supplied every format vanishes -- the signed-in web client makes
        # yt-dlp solve a JS challenge it cannot without a runtime. `deno:<path>`
        # because the binary is deliberately off PATH (the rclone_path
        # precedent); the server's downloader.py enables both deno and node,
        # but only deno is installed here.
        deno = sidecar_tools.managed_deno()
        if deno:
            argv += ["--js-runtimes", f"deno:{deno}"]
        # THE PLAYER CLIENT, and it has now been the difference between this
        # feature working and not in BOTH directions. Two measurements, six
        # weeks apart, on the same machine class.
        #
        # CR-39 (2026-08-19), which pinned `web_safari`. yt-dlp's default
        # client set handed back format URLs bound to a GVS PO token, and an
        # editor's machine has no provider for one -- the NAS does, the bgutil
        # sidecar (downloader.pot_opts, ytdl/web/DEPLOY.md), which is why the
        # server never hit this and the requester always did. Same clip, same
        # binary, same minute, on a live editor machine:
        #
        #     default (android_vr)  ERROR: unable to download video data:
        #                           HTTP Error 403: Forbidden
        #     ios                   "requires a GVS PO Token which was not
        #                           provided ... may yield HTTP Error 403"
        #     tv                    "The page needs to be reloaded"
        #     web                   works, but falls to format 18 -- 360p
        #     web_safari            works, 17.3 MB, full quality, exit 0
        #
        # CR-80 (2026-08-26), which killed it. `web_safari` serves muxed HLS,
        # and YouTube has SABR-forced those https formats away: it returns no
        # usable formats at all now, on either yt-dlp, with or without the
        # editor's cookies. Measured on the base rig against the deployed
        # companion's own yt-dlp (2026.07.04) and its own jar:
        #
        #     web_safari, anonymous                 no usable formats
        #     web_safari, with cookies              no usable formats
        #     default client, with cookies          "The page needs to be
        #                                            reloaded."
        #     default client, anonymous             formats, then HTTP 403
        #     2026.8.19, default, anonymous         WORKS
        #
        # So: yt-dlp's own default set, on the current yt-dlp, downloads
        # anonymously from a residential IP with no PO-token provider at all.
        # A pinned client is a pinned bug waiting to happen (see
        # DEFAULT_PLAYER_CLIENT) -- the pin that was correct in August was a
        # guaranteed failure by the end of the month, and the yt-dlp floor
        # (ytdlp_manager) is the half of this that has to stay current.
        #
        # Config-overridable because this is YouTube's to change, and the day
        # it does an operator needs a lever that is not a release. Empty
        # string means "send nothing", which is now also the default.
        client = _player_client(self.deps.cfg)
        if client:
            argv += ["--extractor-args", f"youtube:player_client={client}"]
        # The signed-in cookies.txt, when the CALLER chose the cookies path.
        #
        # A PARAMETER since 2026-08-26 (plan WP3), and it used to be
        # `_cookies_file(self.deps.cfg)` resolved right here, unconditionally.
        # That is what made one flagged Google account fatal to every download
        # this machine could make (CR-80): there was no argv that did not carry
        # the jar, so there was nothing to fall back to. The jar is the escape
        # hatch it was always described as -- what answers a bot check -- not
        # the default. _run_ytdlp_paths decides; this only spells it.
        if cookies:
            argv += ["--cookies", str(cookies)]
        argv.append(str(url))
        return argv

    def _cleanup_current(self) -> None:
        """Delete the in-flight clip's own litter. Id-scoped, never fatal."""
        current = self._current
        self._current = None
        if current is None:
            return
        outdir, video_id = current
        clear_partials(outdir, video_id)
        self._drop_scratch_info(video_id)


# The progress line yt-dlp prints, once per update, with `--newline`. A
# prefix nothing else on stdout starts with, then tab-separated fields; a
# field yt-dlp does not know is "NA". total_bytes is exact once the server
# said Content-Length, total_bytes_estimate is yt-dlp's guess for HLS -- the
# tray takes the first that is a number.
PROGRESS_PREFIX = "CCSYNC-PROGRESS"
PROGRESS_TEMPLATE = ("download:" + PROGRESS_PREFIX
                     + "\t%(progress.downloaded_bytes)s"
                     "\t%(progress.total_bytes)s"
                     "\t%(progress.total_bytes_estimate)s"
                     "\t%(progress.speed)s")

# Fragments in flight, bounded like the server's fragment_jobs (CR-74): 1 is
# the old sequential fetch, and the ceiling keeps one editor's download from
# looking like bulk automation to YouTube.
DEFAULT_FRAGMENT_JOBS = 6
MAX_FRAGMENT_JOBS = 16


def fragment_jobs(cfg: dict[str, Any]) -> int:
    """`ytdl_fragment_jobs` from config.toml, bounded 1..16, default 6.
    Never raises: a junk value is the default, not a refused download."""
    try:
        n = int((cfg or {}).get("ytdl_fragment_jobs",
                                config_mod.DEFAULTS.get("ytdl_fragment_jobs",
                                                        DEFAULT_FRAGMENT_JOBS)))
    except (TypeError, ValueError):
        n = DEFAULT_FRAGMENT_JOBS
    if n < 1:
        n = 1
    return min(n, MAX_FRAGMENT_JOBS)


def _num(text: Any) -> Optional[float]:
    try:
        v = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    return v if v == v and v >= 0 else None      # NaN and negatives are "NA"


def parse_progress_line(line: Any) -> Optional[dict]:
    """A PROGRESS_TEMPLATE line -> {bytes_done, bytes_total, speed_bps}, or
    None for any other line (or a malformed one). Pure; never raises.

    bytes_total is the exact total when yt-dlp has one, else its estimate,
    else None. speed_bps None = yt-dlp printed NA (the first update, or a
    stalled fragment): the tray then shows the count without a rate rather
    than "0.0 MB/s", which would read as stuck.
    """
    text = str(line or "").strip()
    if not text.startswith(PROGRESS_PREFIX):
        return None
    fields = text.split("\t")
    # The first field must BE the prefix, not merely start with it: a line
    # that happens to share the opening characters is not a progress line.
    if len(fields) < 5 or fields[0] != PROGRESS_PREFIX:
        return None
    done = _num(fields[1])
    total = _num(fields[2])
    if total is None:
        total = _num(fields[3])
    speed = _num(fields[4])
    return {"bytes_done": int(done) if done is not None else None,
            "bytes_total": int(total) if total is not None else None,
            "speed_bps": speed}


def _bot_checked(stderr: Any) -> bool:
    """Is this yt-dlp stderr a bot check? (worker._bot_checked's twin.)

    What the ANONYMOUS path says when YouTube wants an account, and the ONE
    failure the cookie jar is an answer to -- so it is what decides whether a
    clip is retried with it (plan WP3, 2026-08-26).
    """
    low = str(stderr or "").lower()
    return any(marker in low for marker in _BOT_CHECK_MARKERS)


def _account_flagged(stderr: Any) -> bool:
    """Is this the flagged-session message (CR-80, 2026-08-26)?

    The cookies path's own failure mode. The session still authenticates --
    this is YouTube refusing to serve video to it -- so the answer is to stop
    sending it, not to sign in again, and nothing on this machine can fix it.
    """
    low = str(stderr or "").lower()
    return any(marker in low for marker in _ACCOUNT_FLAG_MARKERS)


# An 11-char YouTube id is the one part of a per-clip error guaranteed to
# differ between clips; paths and byte counts are the other two.
_SIG_VIDEO_ID = re.compile(r"\b[0-9A-Za-z_-]{11}\b")
_SIG_PATH = re.compile(r"[A-Za-z]?:?[\\/][^\s'\"]+")
_SIG_DIGITS = re.compile(r"\d+")


def failure_signature(error: Any) -> str:
    """A key that is EQUAL for "the same failure on a different clip".

    worker._failure_signature's rule and its regexes, so the two executors
    count the same wall the same way. Signature-based rather than
    classifier-based on purpose: the point is "this is the same thing again",
    and a classifier only decides what the message says.
    """
    text = _SIG_VIDEO_ID.sub(" ", str(error or ""))
    text = _SIG_PATH.sub(" ", text)
    text = _SIG_DIGITS.sub("", text.lower())
    return " ".join(text.split())[:120]


def max_identical_failures(cfg: dict[str, Any]) -> int:
    """How many identical clip failures in a row end this machine's turn.

    `ytdl_max_identical_failures` in config.toml, else
    $CCSYNC_YTDL_MAX_IDENTICAL_FAILURES, else 3. 0 (or a negative) disables the
    breaker entirely. Never raises: junk is the default, not a refused job.
    """
    raw = (cfg or {}).get("ytdl_max_identical_failures", None)
    if raw is None:
        raw = os.environ.get("CCSYNC_YTDL_MAX_IDENTICAL_FAILURES")
    if raw is None or str(raw).strip() == "":
        return DEFAULT_MAX_IDENTICAL_FAILURES
    try:
        n = int(str(raw).strip())
    except (TypeError, ValueError):
        return DEFAULT_MAX_IDENTICAL_FAILURES
    return max(n, 0)


def _looks_truncated(stderr: Any) -> bool:
    low = str(stderr or "").lower()
    return all(marker in low for marker in ytdl_common.TRUNCATION_MARKERS)


def _error_tail(stderr: Any, limit: int = 400) -> str:
    """The last few lines of yt-dlp's stderr, for the clip row.

    The TAIL and not the head: yt-dlp's first lines are warnings about the
    extractor and its last are what actually went wrong. Trimmed because
    routes_fleet stores 500 characters and a wall of text in a job row helps
    nobody read it.
    """
    text = " ".join(str(stderr or "").split())
    if not text:
        return "the download failed and yt-dlp said nothing"
    return text[-limit:]


def _ffmpeg_location(cfg: dict[str, Any]) -> Optional[str]:
    """The directory holding this machine's ffmpeg, or None. Never raises."""
    try:
        configured = str((cfg or {}).get("ffmpeg_path",
                                         config_mod.DEFAULTS.get("ffmpeg_path", "ffmpeg")) or "")
        resolved = ffmpeg_tools._resolve_binary(configured)
        return os.path.dirname(resolved) if resolved else None
    except Exception:
        return None


def _cookies_file(cfg: dict[str, Any]) -> Optional[str]:
    """The signed-in cookies file to send, or None. Never raises.

    ytdl_cookies.resolve is the seam: the `ytdl_cookies_file` config key if
    set and present, else the tray-written `~/.ccsync/youtube-cookies.txt`,
    else None. A configured-but-absent path is None rather than an error --
    yt-dlp aborts the whole run on a missing --cookies file, and an anonymous
    attempt (which may still succeed, or fall back to the server) beats
    refusing to try."""
    try:
        return ytdl_cookies.resolve(cfg)
    except Exception:
        return None


def _player_client(cfg: dict[str, Any]) -> str:
    """Which YouTube player client yt-dlp should ask as. Never raises.

    See build_argv for the measurements. `ytdl_player_client` in config.toml
    overrides it; an explicit empty string means "send no --extractor-args at
    all", which is yt-dlp's own default set and the behaviour before CR-39.
    """
    try:
        value = cfg.get("ytdl_player_client", None)
    except Exception:
        return DEFAULT_PLAYER_CLIENT
    if value is None:
        return DEFAULT_PLAYER_CLIENT
    return str(value).strip()


def _positive_number(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return number if number > 0 else fallback


# ---------------------------------------------------------------------------
# the module guard: ONE job at a time
# ---------------------------------------------------------------------------
#
# Module level and not per-server, because the thing being protected is the
# MACHINE: two jobs downloading at once would compete for the same line, and
# two claims from one editor is exactly the "two browser tabs" case the lease
# is designed around (§11). The 409 below is the local half of that.

_GUARD = threading.Lock()
_CURRENT: Optional[DownloadJob] = None
_LAST: Optional[dict] = None


def _release(job: DownloadJob) -> None:
    global _CURRENT, _LAST
    with _GUARD:
        if _CURRENT is job:
            _CURRENT = None
        _LAST = job.snapshot()


def current_job() -> Optional[DownloadJob]:
    with _GUARD:
        return _CURRENT


def start(job_id: Any, deps: Deps) -> tuple[int, dict]:
    """POST /ytdl/download's logic. -> (http_status, json_body).

    202 the moment the thread is spawned: the SPA is waiting on this response
    and the job takes minutes, so nothing about the download may happen on the
    request thread. 409 when this machine is already running one, 503 when the
    capability is gone since the probe (an editor who switched the config off,
    a signed-out tray, a yt-dlp that broke this morning).
    """
    global _CURRENT
    job_id = _job_id_or_none(job_id)
    if job_id is None:
        return 400, {"ok": False, "message": "job_id must be a positive integer"}

    # The running job is checked BEFORE the capability, and the order is the
    # answer's usefulness: a machine with a download in flight is a machine
    # that was capable when it started one, and "you are already downloading
    # job 7" is what the second tab needs to hear. Capability can only have
    # gone away underneath it (a sign-out, a config edit), and saying so here
    # would send the SPA down the server path for a job this machine is
    # already, visibly, working.
    with _GUARD:
        if _CURRENT is not None and _CURRENT.running:
            return 409, {"ok": False, "job_id": _CURRENT.job_id,
                         "message": f"this machine is already downloading job "
                                    f"{_CURRENT.job_id}"}

    cap = capabilities(deps)
    if not cap["ok"]:
        return 503, {"ok": False, "message": cap["reason"], "job_id": job_id}

    with _GUARD:
        if _CURRENT is not None and _CURRENT.running:
            # Re-checked under the lock the claim is taken with: capabilities()
            # does a syscall, and two tabs a millisecond apart both passing the
            # check above is exactly the race the lease exists for.
            return 409, {"ok": False, "job_id": _CURRENT.job_id,
                         "message": f"this machine is already downloading job "
                                    f"{_CURRENT.job_id}"}
        job = DownloadJob(job_id, deps)
        _CURRENT = job

    thread = threading.Thread(target=job.run, name=f"ccsync-ytdl-{job_id}",
                              daemon=True)
    try:
        thread.start()
    except Exception:
        log.exception("ytdl: could not start the download thread for job %s", job_id)
        _release(job)
        return 503, {"ok": False, "job_id": job_id,
                     "message": "the download thread could not be started"}
    return 202, {"ok": True, "job_id": job_id, "state": "started"}


def progress(job_id: Any = None) -> dict:
    """GET /ytdl/progress's body. Small on purpose -- the server rows are the
    truth (§7) and this is a first-seconds mirror, not a second ledger."""
    wanted = _job_id_or_none(job_id)
    job = current_job()
    if job is not None and (wanted is None or job.job_id == wanted):
        return job.snapshot()
    with _GUARD:
        last = dict(_LAST) if _LAST else None
    if last is not None and (wanted is None or last.get("job_id") == wanted):
        return last
    return {"job_id": wanted, "running": False, "clip": None,
            "done": 0, "failed": 0, "total": 0,
            "bytes_done": None, "bytes_total": None, "speed_bps": None}


def stop_all() -> None:
    """Tray shutdown. Kills a download in flight; never raises.

    Called from broll_server.stop for broll_fetch.stop_all's reason: a yt-dlp
    still writing into the project tree after the tray exits is an orphan
    nothing supervises. What it leaves is an id-scoped `.part`, which is
    stignored on the editor side (2026-08-14) and which the next attempt --
    ours or the server's -- clears before it downloads.
    """
    job = current_job()
    if job is None:
        return
    try:
        job.stop()
    except Exception:
        log.debug("ytdl: stopping the running job failed", exc_info=True)


def _job_id_or_none(value: Any) -> Optional[int]:
    """A job id off the wire, or None. THE ONLY THING READ FROM THE BODY (§8).

    bools are refused explicitly: `isinstance(True, int)` is True in Python, so
    a JSON `true` would otherwise become job 1. Strings are refused too -- the
    SPA sends the id it read from the job row, which is a number.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value > 0 else None
