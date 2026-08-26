"""The download canary: one tiny public clip, extracted on a schedule.

docs/YTDL_RESILIENCE_PLAN.md WP5 (2026-08-26). Both of the last two outages
(CR-73's unreachable PO-token sidecar, CR-80's flagged cookie jar) were found
by an EDITOR, days in, because nothing here ever asked YouTube a question of
its own: `/api/health` reported configuration, and configuration was fine
throughout. This thread asks the question -- can this container still resolve
a video, anonymously, and if not can it with the cookie jar -- and files the
answer in ytdl_evidence, which is what health reports.

Three properties, all of them load-bearing:

  - EXTRACT ONLY. `simulate`/`skip_download`: no bytes, no disk, no ffmpeg. A
    simulate is admittedly not proof (CR-80's anonymous path extracted happily
    on 2026.07.04 and then 403'd on the media fetch), but it catches every
    failure that happens before the bytes, which is where both incidents were.
  - OFF BY DEFAULT, and off in this suite. See config.CANARY_INTERVAL_SECONDS
    for the reasoning: this is real automated traffic to YouTube on a fixed
    cadence, from the IP that got bot-checked in 2026-08-11, and it is the
    owner's decision to turn on (plan section 7).
  - NEVER FATAL. Nothing here may raise into the caller, take down a request,
    or delay startup: a diagnostic that can break the thing it diagnoses is
    worse than no diagnostic.
"""
import logging
import os
import tempfile
import threading

from ytdlweb import config, ytdl_evidence
from ytdlweb.vendor import downloader

log = logging.getLogger(__name__)

SOURCE = 'canary'

# The same ceiling a default job asks for, so the canary walks the same format
# ladder a real download does. A canary that resolved a format nobody wants
# would go green on the day 1080p stopped being reachable.
QUALITY = '1080p'

_thread = None
_thread_lock = threading.Lock()
# Woken to run a tick now rather than at the next interval. Nothing sets it
# today; it exists so the loop's wait is interruptible rather than a bare
# sleep, which is what makes a shutdown or a future "test now" button cheap.
_wake = threading.Event()


def enabled():
    """Is the canary configured to run at all? Read by /api/health."""
    return bool(config.CANARY_INTERVAL_SECONDS)


def _video_id(url):
    """The `v=` id, for the evidence row. Best effort; '' is fine."""
    try:
        from urllib.parse import parse_qs, urlparse

        return (parse_qs(urlparse(str(url)).query).get('v') or [''])[0][:32]
    except Exception:  # noqa: BLE001
        return ''


def _extract(url, cookies_file=None):
    """One extract-only yt-dlp pass. Raises whatever yt-dlp raises.

    THE TEST SEAM: the suite replaces this whole function, so nothing in
    tests/ ever reaches the network or needs yt-dlp installed. Options come
    from downloader.build_opts rather than a second dict here on purpose -- the
    PO-token provider, the cache dir, the JS runtimes and the format selector
    are exactly the ones a real download uses, and a canary built from a copy
    would drift into testing a configuration nobody runs.
    """
    import yt_dlp  # lazy, like every other yt-dlp use in this app

    # A temp dir it will never write into: build_opts wants an outdir for the
    # output template and yt-dlp's scratch path (CR-33), and with simulate on
    # neither is ever used.
    with tempfile.TemporaryDirectory(prefix='ytdl-canary-') as tmp:
        opts = downloader.build_opts(
            tmp, QUALITY,
            ffmpeg_location=config.FFMPEG_DIR or None,
            cookies_file=cookies_file or None)
        opts.update({
            'simulate': True,
            'skip_download': True,
            # Nothing to post-process when there is no file; the metadata
            # parser would also import ffmpeg's postprocessor for nothing.
            'postprocessors': [],
            'quiet': True,
            'no_warnings': True,
            'noprogress': True,
        })
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)


def _bot_checked(text):
    """worker._bot_checked, imported LAZILY.

    Lazy because worker imports the database, the phase machine and half the
    app; this module is also imported by routes_api for `enabled()`, and a
    diagnostic must not widen anybody's import graph. One classifier, not two:
    the markers live in worker.py and adding a copy here is how the two
    versions of "is this a bot check" drift apart (plan WP4).
    """
    try:
        from ytdlweb import worker

        return bool(worker._bot_checked(text))
    except Exception:  # noqa: BLE001
        return False


def tick():
    """One canary round: anonymous, then cookies only if bot-checked.

    The same order WP3 puts the real downloads in, deliberately: a canary that
    tried the cookie jar first would go green on a path the downloads no longer
    take. The cookies path is attempted ONLY on a bot check and ONLY when the
    jar actually holds a cookie -- CR-80 parked the NAS's flagged jar as its
    two Netscape header lines, and re-testing an empty file every five minutes
    would record a permanent, meaningless failure.

    Never raises.
    """
    url = config.CANARY_URL
    vid = _video_id(url)
    try:
        _extract(url, None)
    except Exception as exc:  # noqa: BLE001
        ytdl_evidence.record(ytdl_evidence.PATH_ANONYMOUS, False, error=exc,
                             video_id=vid, source=SOURCE)
        log.warning('ytdl canary: anonymous extraction failed (%s: %s)',
                    type(exc).__name__, exc)
        if not _bot_checked(exc):
            return
        if ytdl_evidence.cookie_jar_state(config.COOKIES_FILE) != ytdl_evidence.JAR_PRESENT:
            return
        try:
            _extract(url, config.COOKIES_FILE)
        except Exception as exc2:  # noqa: BLE001
            ytdl_evidence.record(ytdl_evidence.PATH_COOKIES, False, error=exc2,
                                 video_id=vid, source=SOURCE)
            log.warning('ytdl canary: BOTH paths are blocked (cookies: %s: %s)',
                        type(exc2).__name__, exc2)
        else:
            ytdl_evidence.record(ytdl_evidence.PATH_COOKIES, True,
                                 video_id=vid, source=SOURCE)
        return
    ytdl_evidence.record(ytdl_evidence.PATH_ANONYMOUS, True, video_id=vid,
                         source=SOURCE)


def _run():
    """The loop. Sleeps FIRST, then ticks."""
    interval = config.CANARY_INTERVAL_SECONDS
    log.info('ytdl canary every %ss against %s', interval, config.CANARY_URL)
    while True:
        # Sleeps before the first tick on purpose: a container restart must not
        # be a way to make an extra request to YouTube (the dashboard restarts
        # for image updates and compose edits, none of which are about
        # YouTube), and the bgutil sidecar's boot-time install is the thing
        # CR-73 showed can still be in flight seconds after this app is up.
        _wake.wait(timeout=interval)
        _wake.clear()
        try:
            tick()
        except Exception as exc:  # noqa: BLE001 - a diagnostic may never die
            log.warning('ytdl canary tick failed (%s: %s)',
                        type(exc).__name__, exc)


def ensure_started():
    """Start the canary if it is configured. -> is there one running.

    Idempotent, and called from BOTH the standalone lifespan and the
    dashboard's mount, for the same reason worker.ensure_started() is:
    Starlette does not run a mounted sub-app's lifespan.

    `YTDL_WORKER=0` disables it too. That switch means "this process must not
    spawn the ytdl background threads" -- it is what keeps both test suites
    (and the dashboard's fake ytdlweb) from starting anything -- and a second
    thread that ignored it would be a suite making live YouTube requests.
    """
    if os.environ.get('YTDL_WORKER') == '0':
        return False
    if not config.CANARY_INTERVAL_SECONDS:
        # Not a warning: off is the shipped default (plan section 7).
        log.debug('ytdl canary disabled (YTDL_CANARY_INTERVAL_SECONDS unset)')
        return False
    global _thread
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return True
        _thread = threading.Thread(target=_run, name='ytdl-canary', daemon=True)
        _thread.start()
    return True


def is_alive():
    return bool(_thread is not None and _thread.is_alive())
