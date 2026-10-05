"""The server's yt-dlp, kept on the NIGHTLY channel (CR-361, 2026-10-05).

Owner decision 2026-10-05: "accept any yt-dlp build, daily etc, to get the
latest". YouTube's anti-bot changes now land faster than yt-dlp cuts stable
releases -- stable sat at 2026.08.19 for seven weeks while the nightly reached
2026.09.27.232945 -- and the container's yt-dlp only ever moved when somebody
raised the pin in requirements.lock and shipped an image. CR-80 and CR-83 were
both that shape. So this keeps a nightly beside the pinned copy and lets it
SHADOW the pinned one:

    /data/ytdlp-nightly/
        versions/<yt-dlp version>/yt_dlp/...   pip --target, one per build
        current                                 the active version dir's NAME
        install.json                            what the last attempt did

run.sh reads `current` (in plain sh: no python on that path) and appends the
RESOLVED `versions/<name>` directory to PYTHONPATH. Every PYTHONPATH entry sits
ahead of /venv's site-packages on sys.path, so `import yt_dlp` finds the
nightly first and the image's pinned yt-dlp is only the fallback: no nightly
installed, the switch off, or every install failed.

UNPINNED BY DESIGN, and that is a deliberate exception to this repo's
hash-pinned-lock rule (COMMERCIAL_READINESS.md item 13). The whole point is
"whatever yt-dlp published last night", which a hash in a lock cannot express.
What replaces the pin: PyPI over TLS (pip verifies each file against the
index's own sha256), --no-deps (only yt-dlp itself moves; every library it
can use stays the image's pinned one), an import of the staged copy in a
child process before anything points at it, and a refusal to activate a build
that ranks BELOW the image's own. `YTDL_YTDLP_NIGHTLY=0` puts a deployment
back on the pinned copy alone.

RESTART SEMANTICS -- honest version. The dashboard is ONE long-lived process
(uvicorn workers=1) and yt-dlp is imported into it once; Python does not
re-import a package because its files changed, and yt-dlp still imports some
submodules lazily, so swapping files under a live import would mix two
versions in one process. Nothing here ever does that: each build gets its own
directory, the running process keeps importing from the one it started with
(which pruning never deletes), and a refresh only moves the `current` pointer.
A refreshed nightly therefore takes effect at the NEXT PROCESS START -- a
container restart, an image update, or an over-the-air code update's exit-75
re-exec (run.sh re-reads the pointer on every pass of that loop). It does not
restart the dashboard to apply itself: the dashboard is what tells everyone
whether their footage is syncing, and a daily self-restart is a decision for
the owner, not a side effect of a downloader. /api/health says when a newer
build is waiting (`yt_dlp_nightly.pending_restart`).

stdlib only, and runnable as `python -m ytdlweb.ytdlp_nightly install` with
nothing but /ytdl-app on the path: run.sh calls it before the app exists.
Never raises out of refresh(); never fatal to a boot.
"""
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

log = logging.getLogger(__name__)

# run.sh exports the root it used. Unset means "no run.sh that knows this
# layout booted this process" (a dev server, the test suite, an image older
# than CR-361), and then nothing here runs: staging a build that no PYTHONPATH
# will ever point at is a daily download for nothing.
ROOT_ENV = 'YTDL_YTDLP_NIGHTLY_ROOT'
DEFAULT_ROOT = '/data/ytdlp-nightly'
# '0' switches the whole thing off, at boot and in the daily refresh alike,
# for a deployment that wants exactly the image's pinned yt-dlp.
SWITCH_ENV = 'YTDL_YTDLP_NIGHTLY'

VERSIONS_DIR = 'versions'
CURRENT_NAME = 'current'
MARKER_NAME = 'install.json'
STAGING_PREFIX = '.staging-'

PACKAGE = 'yt-dlp'
# --pre is what makes it the nightly: yt-dlp publishes every nightly to PyPI
# as `<date>.<HHMMSS>.dev0` (2026.9.27.232945.dev0 on 2026-10-05, the same
# build as the GitHub nightly 2026.09.27.232945, verified that day), and
# without --pre pip only ever sees the stable 2026.8.19. --target, because in
# image mode /venv is a read-only image layer (CR-84); --no-deps, because only
# yt-dlp is meant to move. A short --timeout/--retries: pip's defaults can
# hold a boot for minutes on a PyPI that is not answering, and this step has
# its own retry loop.
PIP_ARGS = ('install', '--quiet', '--disable-pip-version-check',
            '--no-cache-dir', '--pre', '--upgrade', '--no-deps',
            '--timeout', '20', '--retries', '1')
PIP_TIMEOUT_SECONDS = 300
VERIFY_TIMEOUT_SECONDS = 120

# A successful check this recent is not repeated: a container restarted three
# times in an hour (an OTA, a crash loop) must not ask PyPI three times.
MIN_INTERVAL_SECONDS = 20 * 3600
# How often the in-process thread wakes. Shorter than a day on purpose: the
# MIN_INTERVAL above keeps a SUCCESSFUL check to about once a day, and a
# failed one is retried within six hours instead of tomorrow.
REFRESH_WAKE_SECONDS = 6 * 3600
# The first wake after the process starts. run.sh has just run the boot
# install, so this one is normally a no-op behind MIN_INTERVAL; it exists for
# a boot whose install failed (CR-73: no DNS in the container's first
# seconds) and for a site that turned the downloader on after boot.
REFRESH_FIRST_WAKE_SECONDS = 15 * 60
# The boot install's retry delays, CR-73's: the only failure ever seen in the
# field for the plugin install was the network not being up yet.
BOOT_RETRY_DELAYS = (5, 15, 30)

_VERSION_RE = re.compile(r'^\d{4}\.\d{1,2}\.\d{1,2}(\.\d+)*$')
_NAME_RE = re.compile(r'^[0-9][0-9.]*$')

# Run in a child, with the staged directory first on sys.path: proves the
# staged copy imports on THIS interpreter, that it is the copy being imported
# (not the image's), and what version it really is. Building a YoutubeDL
# loads the extractor table, which is where a broken build would show.
_VERIFY = (
    'import os, sys\n'
    'staged = os.path.realpath(sys.argv[1])\n'
    'sys.path.insert(0, staged)\n'
    'import yt_dlp, yt_dlp.version\n'
    'where = os.path.realpath(yt_dlp.__file__)\n'
    'if not where.startswith(staged + os.sep):\n'
    '    raise SystemExit("imported %s, not the staged copy" % where)\n'
    'yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True})\n'
    'print(yt_dlp.version.__version__)\n'
)
_BASE_VERSION = 'import yt_dlp.version; print(yt_dlp.version.__version__)'


# ---------------------------------------------------------------- helpers

def enabled():
    """Is the nightly switched on for this process? (run.sh-managed + not 0)"""
    if (os.environ.get(SWITCH_ENV) or '1').strip() == '0':
        return False
    return bool((os.environ.get(ROOT_ENV) or '').strip())


def root():
    return (os.environ.get(ROOT_ENV) or '').strip() or DEFAULT_ROOT


def version_rank(version):
    """'2026.09.27.232945' -> (2026, 9, 27, 232945); None for anything else.

    config.version_rank's rule, repeated rather than imported because run.sh
    runs this module before the app (and its config) exist. A nightly's
    fourth part makes it rank after the stable of the same day."""
    text = str(version or '').strip()
    if not _VERSION_RE.match(text):
        return None
    return tuple(int(p) for p in text.split('.'))


def _now():
    return time.time()


def _iso(stamp):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(stamp))


def read_current(root_dir=None):
    """The active version directory's name, or '' when there is none usable.

    Same rule as run.sh's: a plain name (digits and dots, nothing that could
    walk out of versions/) whose directory really holds yt_dlp/version.py."""
    base = root_dir or root()
    try:
        with open(os.path.join(base, CURRENT_NAME), encoding='utf-8') as fh:
            name = fh.read().strip()
    except OSError:
        return ''
    if not _NAME_RE.match(name):
        return ''
    if not os.path.isfile(os.path.join(base, VERSIONS_DIR, name, 'yt_dlp', 'version.py')):
        return ''
    return name


def read_marker(root_dir=None):
    """install.json as a dict, or {} when absent or unreadable."""
    try:
        with open(os.path.join(root_dir or root(), MARKER_NAME), encoding='utf-8-sig') as fh:
            data = json.load(fh)
    except Exception:  # noqa: BLE001 - a marker is evidence, never a failure
        return {}
    return data if isinstance(data, dict) else {}


def _atomic_write(path, text):
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _write_marker(base, payload):
    try:
        _atomic_write(os.path.join(base, MARKER_NAME), json.dumps(payload))
    except OSError as exc:
        # A marker we cannot write is a diagnostic lost, never a boot stopped
        # (run.sh's write_unblock_marker, same rule).
        log.warning('yt-dlp nightly: could not write %s (%s)', MARKER_NAME, exc)


def _child_env(base):
    """This process's environment minus every PYTHONPATH entry inside the
    nightly root, so neither pip nor the base-version probe sees a nightly."""
    env = dict(os.environ)
    real_base = os.path.realpath(base)
    entries = [p for p in (env.get('PYTHONPATH') or '').split(os.pathsep)
               if p and not os.path.realpath(p).startswith(real_base)]
    if entries:
        env['PYTHONPATH'] = os.pathsep.join(entries)
    else:
        env.pop('PYTHONPATH', None)
    return env


def _default_run(argv, timeout, env):
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                          env=env, stdin=subprocess.DEVNULL)


def _last_words(proc_or_exc):
    """The useful tail of a failure, for the marker (CR-84: pip's own words,
    not our guess about them)."""
    if isinstance(proc_or_exc, BaseException):
        return f'{type(proc_or_exc).__name__}: {proc_or_exc}'[:4000]
    text = ((getattr(proc_or_exc, 'stderr', '') or '') + '\n'
            + (getattr(proc_or_exc, 'stdout', '') or '')).strip()
    return text[-4000:] or f'exit {getattr(proc_or_exc, "returncode", "?")}'


def in_use_dir(base=None):
    """The versions/<name> directory THIS process imported yt-dlp from, or ''.

    Read from sys.modules only -- never imports yt_dlp itself, because an
    import here would pin whatever is on the path at that moment."""
    module = sys.modules.get('yt_dlp')
    where = getattr(module, '__file__', None) if module is not None else None
    if not where:
        return ''
    versions = os.path.realpath(os.path.join(base or root(), VERSIONS_DIR))
    path = os.path.realpath(where)
    if not path.startswith(versions + os.sep):
        return ''
    return path[len(versions) + 1:].split(os.sep, 1)[0]


def _prune(base, keep):
    """Delete version dirs not in `keep`, and any staging dir left by a
    refresh that was killed. Never the one a running process imports from:
    the caller puts it in `keep`."""
    versions = os.path.join(base, VERSIONS_DIR)
    try:
        names = os.listdir(versions)
    except OSError:
        names = []
    for name in names:
        if name in keep:
            continue
        shutil.rmtree(os.path.join(versions, name), ignore_errors=True)
    try:
        for name in os.listdir(base):
            if name.startswith(STAGING_PREFIX):
                shutil.rmtree(os.path.join(base, name), ignore_errors=True)
    except OSError:
        pass


# ---------------------------------------------------------------- the work

def refresh(base=None, *, min_interval=MIN_INTERVAL_SECONDS, keep=(),
            run=None, now=None):
    """Install the newest yt-dlp nightly into a fresh directory and point
    `current` at it. -> the marker dict it wrote. Never raises.

    `keep` names version dirs that must survive pruning (the one a live
    process imports from). `run(argv, timeout, env)` and `now()` are seams.
    """
    base = base or root()
    run = run or _default_run
    clock = now or _now
    started = clock()
    previous = read_current(base)
    marker = read_marker(base)

    if previous and min_interval > 0:
        try:
            since = started - float(marker.get('checked_at'))
        except (TypeError, ValueError):
            since = None
        if (since is not None and 0 <= since < min_interval and marker.get('ok')
                and marker.get('version') == previous):
            log.info('yt-dlp nightly: %s checked %.1f h ago, not asking again yet',
                     previous, since / 3600)
            return dict(marker, note=f'checked {since / 3600:.0f} h ago, not asked again yet')

    def done(ok, version, error='', note=''):
        payload = {
            'ok': bool(ok),
            'at': _iso(clock()),
            # Only a SUCCESSFUL check moves checked_at, so a failed one is
            # retried on the next wake instead of after MIN_INTERVAL.
            'checked_at': clock() if ok else marker.get('checked_at'),
            'version': version or previous or '',
            'previous': previous or '',
            'base_version': base_version,
            'error': (error or '')[:4000],
            'note': note,
            'source': 'pypi --pre',
        }
        _write_marker(base, payload)
        return payload

    base_version = ''
    try:
        os.makedirs(os.path.join(base, VERSIONS_DIR), exist_ok=True)
        env = _child_env(base)
        probe = run([sys.executable, '-c', _BASE_VERSION], VERIFY_TIMEOUT_SECONDS, env)
        if getattr(probe, 'returncode', 1) == 0:
            lines = (getattr(probe, 'stdout', '') or '').strip().splitlines()
            base_version = lines[-1].strip() if lines else ''
        staging = tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=base)
    except Exception as exc:  # noqa: BLE001
        return done(False, '', _last_words(exc))

    try:
        try:
            proc = run([sys.executable, '-m', 'pip', *PIP_ARGS, '--target', staging,
                        PACKAGE], PIP_TIMEOUT_SECONDS, env)
        except Exception as exc:  # noqa: BLE001 - a timeout included
            return done(False, '', _last_words(exc))
        if getattr(proc, 'returncode', 1) != 0:
            return done(False, '', _last_words(proc))
        try:
            check = run([sys.executable, '-c', _VERIFY, staging],
                        VERIFY_TIMEOUT_SECONDS, env)
        except Exception as exc:  # noqa: BLE001
            return done(False, '', 'the staged yt-dlp did not import: ' + _last_words(exc))
        lines = (getattr(check, 'stdout', '') or '').strip().splitlines()
        staged = lines[-1].strip() if lines else ''
        if getattr(check, 'returncode', 1) != 0 or version_rank(staged) is None:
            return done(False, '', 'the staged yt-dlp did not import: ' + _last_words(check))
        if base_version and version_rank(base_version) is not None \
                and version_rank(staged) < version_rank(base_version):
            # PyPI handed us something OLDER than the image already carries.
            # Shadowing a newer pinned copy with it would be a downgrade
            # nobody asked for; keep whatever is active and say so.
            return done(False, '', f'PyPI offered yt-dlp {staged}, older than the '
                                   f'image\'s own {base_version}; not using it')
        if staged == previous:
            return done(True, staged, note='already the newest nightly')
        dest = os.path.join(base, VERSIONS_DIR, staged)
        if os.path.isdir(dest):
            # The same build was installed before (and may be what a live
            # process imports from): reuse it, never write over it.
            shutil.rmtree(staging, ignore_errors=True)
        else:
            os.replace(staging, dest)
        _atomic_write(os.path.join(base, CURRENT_NAME), staged + '\n')
        log.info('yt-dlp nightly: %s staged as current (was %s); it applies '
                 'at the next dashboard process start', staged, previous or 'none')
        return done(True, staged, note=f'updated from {previous}' if previous else 'installed')
    except Exception as exc:  # noqa: BLE001
        return done(False, '', _last_words(exc))
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        try:
            _prune(base, {read_current(base), previous, *keep} - {''})
        except Exception:  # noqa: BLE001
            log.debug('yt-dlp nightly: prune failed', exc_info=True)


def boot_install(base=None, *, run=None, now=None, sleep=time.sleep,
                 delays=BOOT_RETRY_DELAYS, min_interval=MIN_INTERVAL_SECONDS):
    """run.sh's step: refresh() with CR-73's retries. -> the last marker."""
    marker = {}
    for attempt, delay in enumerate((*delays, None), start=1):
        marker = refresh(base, min_interval=min_interval, run=run, now=now)
        marker['attempts'] = attempt
        _write_marker(base or root(), marker)
        if marker.get('ok') or delay is None:
            break
        print(f'run.sh: yt-dlp nightly install failed -- retrying in {delay}s',
              file=sys.stderr)
        sleep(delay)
    return marker


# ------------------------------------------------------- the daily refresh

_thread = None
_thread_lock = threading.Lock()


def _loop():
    wait = REFRESH_FIRST_WAKE_SECONDS
    while True:
        time.sleep(wait)
        wait = REFRESH_WAKE_SECONDS
        if not enabled():
            continue
        try:
            in_use = in_use_dir()
            marker = refresh(keep=(in_use,) if in_use else ())
            if not marker.get('ok'):
                log.warning('yt-dlp nightly refresh failed (the running copy '
                            'is unchanged): %s', marker.get('error'))
        except Exception:  # noqa: BLE001 - this thread must outlive anything
            log.exception('yt-dlp nightly refresh failed')


def ensure_refresher_started():
    """Start the daily refresh thread once. -> whether one is running.

    Only under a run.sh that manages the nightly (ROOT_ENV set) and with the
    switch on. Called from worker.ensure_started, so `YTDL_WORKER=0` (every
    test suite) keeps it off too."""
    global _thread
    if not enabled():
        return False
    with _thread_lock:
        if _thread is not None and _thread.is_alive():
            return True
        _thread = threading.Thread(target=_loop, name='ytdl-ytdlp-nightly',
                                   daemon=True)
        _thread.start()
    return True


# ------------------------------------------------------------- health

def health_state(running_version):
    """`yt_dlp_nightly` for /api/health. `running_version` is the version
    actually imported in this process (routes_api._yt_dlp_version).

    state: 'off' (switched off, or no run.sh that manages it -- the image's
    pinned copy is what runs), 'unknown' (on, but no marker yet: NOT CHECKED,
    never OK), 'ok', or 'failed'. `pending_restart` is True when a newer build
    is installed than the one this process imported."""
    out = {'state': 'off', 'installed': '', 'running': running_version or '',
           'pending_restart': False, 'at': '', 'error': '', 'note': ''}
    if not enabled():
        return out
    marker = read_marker()
    out['installed'] = read_current()
    if not marker:
        out['state'] = 'unknown'
    else:
        out['state'] = 'ok' if marker.get('ok') else 'failed'
        out['at'] = str(marker.get('at') or '')
        out['error'] = str(marker.get('error') or '')
        out['note'] = str(marker.get('note') or '')
    installed, running = version_rank(out['installed']), version_rank(running_version)
    out['pending_restart'] = bool(installed and running and installed > running)
    return out


# ------------------------------------------------------------- CLI

def main(argv=None):
    """`python -m ytdlweb.ytdlp_nightly install [--root R]` (run.sh's boot step).

    Always exits 0: a failed nightly install is recorded in the marker and
    the image's pinned yt-dlp keeps working; it must never stop a boot."""
    args = list(sys.argv[1:] if argv is None else argv)
    base = None
    if '--root' in args:
        i = args.index('--root')
        base = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
    command = args[0] if args else ''
    if base:
        os.environ[ROOT_ENV] = base
    if command == 'install':
        if (os.environ.get(SWITCH_ENV) or '1').strip() == '0':
            return 0
        marker = boot_install(base)
        if marker.get('ok'):
            print(f'run.sh: yt-dlp nightly {marker.get("version")} '
                  f'({marker.get("note") or "ok"})')
        else:
            print('run.sh: WARNING: yt-dlp nightly install FAILED; /ytdl runs on the '
                  f'image\'s pinned yt-dlp {marker.get("base_version") or ""}. It said:',
                  file=sys.stderr)
            print(marker.get('error') or '', file=sys.stderr)
        return 0
    print('usage: python -m ytdlweb.ytdlp_nightly install [--root DIR]', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
