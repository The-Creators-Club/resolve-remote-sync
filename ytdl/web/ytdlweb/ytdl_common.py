"""What BOTH download executors must agree on, byte for byte.

From companion 0.8.0 a clip may be fetched by the NAS worker OR by the
requester's own machine (docs/YTDL_LOCAL_DOWNLOAD.md). The two must produce
IDENTICAL artifacts for the same video -- the same filename out of the same
outtmpl, the same `.credits.json` sidecar, the same quality-fallback rung --
because the tree they both write into is one canonical tree that syncs
fleet-wide. Divergence here is silent data skew across the fleet, the exact
class of bug the path-canon work (R12) exists to prevent, and it would surface
as "the same clip is in the project twice under two names" months later.

**THIS FILE IS VENDORED INTO THE COMPANION** (plan §5, phase 2), the way the
installer's parity files are, so:

  - it imports NOTHING from `ytdlweb` and nothing outside the stdlib. The
    companion has no ytdlweb, no FastAPI and no yt-dlp *library* (it drives the
    standalone yt-dlp binary -- plan §6), so an import of either half of this
    app would make the vendored copy unusable;
  - `lower_quality()` takes the quality table as an ARGUMENT rather than
    importing `vendor.downloader`. One table still exists per tree (the format
    string the retry downloads with is built from it), and passing it in is
    what keeps this module importable on the other side of the fleet;
  - `TEMPLATE_VERSION` / `SIDECAR_VERSION` are the handshake. The download
    manifest carries them; a companion whose vendored copy disagrees declines
    the claim and the job stays server-side (plan §5). **Bump them whenever
    anything below changes shape**, or the fleet grows two spellings of the
    same clip and nothing notices.
"""
import os
from pathlib import Path

# The naming contract's version. Bump on ANY change to OUTTMPL (or to what the
# name is built from): a manifest whose template_version an executor does not
# recognise is refused, which degrades to server-side execution -- never to a
# second filename for the same clip.
TEMPLATE_VERSION = 1

# The sidecar contract's version, bumped on any change to the field set below.
# Separate from TEMPLATE_VERSION because they fail differently: a template skew
# duplicates clips, a sidecar skew feeds the Resolve credits script a shape it
# does not read.
SIDECAR_VERSION = 1

# THE filename every downloaded clip carries, on either executor. `.60B`/`.140B`
# truncate to BYTES rather than characters -- NFS and SMB cap a name at 255
# bytes and a CJK title is 3 bytes a character. `[%(id)s]` last and immediately
# before the extension is load-bearing twice over: the disk half of the dedupe
# reads the id back out of the stem (ytsearch._ID_RE is anchored there), and
# the corpse cleanup scopes itself to that `[id]` segment.
OUTTMPL = '%(uploader).60B - %(title).140B [%(id)s].%(ext)s'


def outtmpl(outdir):
    """The absolute yt-dlp `outtmpl` for a destination folder.

    os.path.join, so the separator is the executing machine's: the NAS worker
    writes /projects/..., an editor's companion writes P:\\Projects\\... -- the
    NAME is what has to match, not the path that leads to it.
    """
    return os.path.join(str(outdir), OUTTMPL)


# What `<video>.credits.json` is called, next to the clip. The suffix replaces
# the video's extension rather than being appended to it, so the sidecar's stem
# does NOT end in `[id]` -- which is precisely why the disk-scan dedupe (whose
# id regex is anchored to the end of the stem) never mistakes a sidecar for the
# clip it describes.
SIDECAR_SUFFIX = '.credits.json'

# The fields of the sidecar, in order. The downstream DaVinci Resolve credits
# script reads them, so this list is a published interface and not an internal
# detail -- and it is EIGHT fields, not the nine the plan's prose says
# (docs/YTDL_LOCAL_DOWNLOAD.md §5, written from memory). The count is settled
# here by the code that actually writes them today: vendor/downloader.py's
# _write_sidecar, which is vendored verbatim from yt-credit-downloader and must
# not be edited. tests/test_ytdl_common.py pins the two against each other, so
# a ninth field can only arrive in both at once.
SIDECAR_FIELDS = ('channel', 'channel_url', 'uploader', 'video_url', 'title',
                  'video_id', 'upload_date', 'duration')


def credits_sidecar(info):
    """A yt-dlp info dict -> the `.credits.json` payload, both executors alike.

    The fallbacks are the ones downloader._write_sidecar has always used
    (channel falling back to uploader, channel_url to uploader_url): a clip
    fetched by an editor and a clip fetched by the NAS must not disagree about
    who made it because one of them read a different key.
    """
    info = info or {}
    return {
        'channel': info.get('channel') or info.get('uploader'),
        'channel_url': info.get('channel_url') or info.get('uploader_url'),
        'uploader': info.get('uploader'),
        'video_url': info.get('webpage_url'),
        'title': info.get('title'),
        'video_id': info.get('id'),
        'upload_date': info.get('upload_date'),
        'duration': info.get('duration'),
    }


def sidecar_path(filepath):
    """Where the sidecar for `filepath` goes. Same rule on both executors."""
    return str(Path(filepath).with_suffix('')) + SIDECAR_SUFFIX


# ------------------------------------------------------- the quality ladder
# COPIED from vendor/downloader.py (2026-08-14, phase 2), not imported and not
# moved. Three constraints meet here and only a copy satisfies all of them:
#
#   - vendor/downloader.py is vendored VERBATIM from yt-credit-downloader and
#     must not be edited, so the definitions cannot move out of it;
#   - this module is vendored into the companion and imports nothing but the
#     stdlib (see the module docstring) -- an import of `vendor.downloader`
#     would make the companion's copy unimportable;
#   - the companion drives the standalone yt-dlp BINARY (plan §6), so it needs
#     the `-f` string itself, spelled exactly as the NAS worker spells it, or
#     the two executors ask YouTube for different streams for the same rung.
#
# tests/test_ytdl_common.py pins both against downloader's originals for every
# rung x prefer_avc, so a change there that is not copied here fails the suite
# rather than reaching the fleet.

QUALITY_HEIGHTS = {
    "best": None, "2160p": 2160, "1440p": 1440,
    "1080p": 1080, "720p": 720, "480p": 480,
}


def format_selector(quality: str, prefer_avc: bool = True) -> str:
    """Build a yt-dlp format string for a UI quality choice.

    With `prefer_avc`, AVC video + AAC audio are tried first so the merged file
    needs no re-encode at all. YouTube only serves AVC up to 1080p, so anything
    above that asks for the best stream there is and gets converted afterwards.

    YTDL-4 (2026-08-11): the AVC alternatives are prepended ONLY at <=1080p.
    yt-dlp takes the first *satisfiable* alternative, and
    `[height<=2160][vcodec^=avc1]` is satisfied by the 1080p AVC stream nearly
    every video has -- so 1440p/2160p/best used to download 1080p, report
    success, and never reach ensure_edit_ready at all. Silent quality loss with
    no error anywhere.
    """
    if quality == "audio":
        return "bestaudio[acodec^=mp4a]/bestaudio/best" if prefer_avc else "bestaudio/best"

    h = QUALITY_HEIGHTS.get(quality)
    hf = f"[height<={h}]" if h else ""
    generic = f"bestvideo{hf}+bestaudio/best{hf}"
    if not prefer_avc or h is None or h > 1080:
        return generic
    return (f"bestvideo{hf}[vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
            f"bestvideo{hf}[vcodec^=avc1]+bestaudio/{generic}")


# --------------------------------------------------- a truncated DASH stream
# Moved here from worker.py (2026-08-14) unchanged: the local executor has to
# make the SAME call on the same signature, or a clip that the NAS would have
# delivered at 720p comes back as a failure on an editor's machine (and vice
# versa, which is worse -- a silent downgrade the server would not have made).

# SAQBbd1Rxmo (2026-08-13, "Cruz Yanez - Aerial View Rio Grande LNG Project"):
# YouTube served ONE of that video's formats truncated. Every attempt at f137
# (1080p avc) died with "Got error: 8 bytes read, 10288457 more expected. Giving
# up after 10 retries" -- reproduced from TWO IPs (the NAS worker and the base
# rig), including from a fresh start with no .part to resume, while f136 (720p)
# plus audio came down fine from both minutes later. The clip was not dead, the
# RUNG was; nothing tried another one, so the editor got nothing at all.
#
# BOTH markers are required, and only on a yt-dlp DownloadError. The byte-count
# phrase on its own is the ordinary short read yt-dlp retries out of by itself;
# "giving up after" is what says the retry budget is SPENT and the format,
# rather than the moment, is the problem. Nothing else may downgrade quality --
# a bot check, a throttle or a dead network are moments, and they keep the
# failure they have always had rather than silently costing the editor 360 lines
# of resolution nobody asked to lose.
TRUNCATION_MARKERS = ('more expected', 'giving up after')

# What a fallback from `best` asks for. NOT 2160p: `best` is the UNCAPPED
# selector, so a cap above the source's own height re-selects the identical
# stream YouTube just served short, while the 1080p rung asks for AVC/AAC
# (format_selector's prefer_avc branch) and is therefore a genuinely different
# format for any source -- YouTube's best is VP9 or AV1.
BEST_FALLBACK_QUALITY = '1080p'

TRUNCATED_NOTE = '{q} stream truncated by YouTube, fell back to {lower}'


def stream_truncated(exc):
    """Did yt-dlp give up on ONE format that keeps arriving short?

    The class is matched BY NAME rather than with an isinstance: yt_dlp is
    imported lazily inside vendor/downloader.py precisely so this app -- and
    this suite -- runs in a venv without it, and an import here would undo that
    (vendor/__init__.py). The companion has no yt_dlp module at all (it shells
    out to the standalone binary, plan §6) and matches the same words in the
    binary's stderr, which is the other reason this stays a name/text test.
    """
    if not any(k.__name__ == 'DownloadError' for k in type(exc).__mro__):
        return False
    low = str(exc or '').lower()
    return all(m in low for m in TRUNCATION_MARKERS)


def lower_quality(quality, heights):
    """The rung below `quality`, or None when there is nothing below it.

    `heights` is downloader.QUALITY_HEIGHTS -- passed in rather than imported so
    the companion's vendored copy of this file needs no vendored downloader (see
    the module docstring). It is read rather than re-written as a second table
    here for the same reason it always was: the format string the retry actually
    downloads with is built from that one dict. 'audio' is not a rung on this
    ladder and has nothing below it.
    """
    if quality not in heights:
        return None
    h = heights[quality]
    if h is None:
        return BEST_FALLBACK_QUALITY
    below = [q for q, height in heights.items()
             if height is not None and height < h]
    return max(below, key=lambda q: heights[q]) if below else None
