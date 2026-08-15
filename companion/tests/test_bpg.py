"""BPG is started only when nothing else is encoding, and never stopped.

Every test here runs against injected collaborators: the real ones start
DaVinci Resolve.
"""
import pytest

from ccsync_companion import bpg


@pytest.fixture(autouse=True)
def _clean_probe_cache():
    """The CIM probe's cache is process-global (MED-9), so one test's answer
    must not become the next one's -- the same rule the ffmpeg_tools and
    resolve_bridge caches are reset under."""
    bpg._reset_probe_cache()
    yield
    bpg._reset_probe_cache()


class FakeChild:
    def __init__(self, alive=True):
        self._alive = alive

    def poll(self):
        return None if self._alive else 0


_DEFAULT = object()


def make_launcher(cfg=None, *, running=False, spawn=None, clock=None,
                 command=_DEFAULT, ensure=None, press=None):
    spawned = []

    def default_spawn(cmd):
        spawned.append(cmd)
        return FakeChild()

    launcher = bpg.BpgLauncher(
        cfg or {},
        generation_enabled=True,
        clock=clock or (lambda: 1000.0),
        spawn=spawn or default_spawn,
        running_fn=lambda: running,
        command=["Resolve.exe", "-pg"] if command is _DEFAULT else command,
        ensure_fn=ensure if ensure is not None else (
            lambda dirs, path="", create_dir=False: {"ok": True}),
        press_start_fn=press if press is not None else (lambda: "pressed"),
        # Synchronous: the real one is a daemon thread that waits three
        # minutes for a window, which a test must never race.
        run_async=lambda fn: fn(),
    )
    return launcher, spawned


READY = dict(queue_empty=True, needs_resolve=6, user_away=True)


def test_it_launches_when_the_ffmpeg_queue_is_empty_and_nobody_is_here():
    launcher, spawned = make_launcher()
    assert launcher.maybe_launch(**READY) is None
    assert spawned == [["Resolve.exe", "-pg"]]


def test_it_waits_for_the_ffmpeg_queue_to_drain():
    """The sequencing this exists for: BPG is the same GPU as the ffmpeg
    encoder, so the two must never run together."""
    launcher, spawned = make_launcher()
    assert launcher.maybe_launch(**{**READY, "queue_empty": False}) == (
        "ffmpeg still has clips queued")
    assert spawned == []


def test_it_waits_for_the_user_to_leave():
    launcher, spawned = make_launcher()
    assert launcher.maybe_launch(**{**READY, "user_away": False}) == (
        "user is at the keyboard")
    assert spawned == []


def test_nothing_to_do_starts_nothing():
    launcher, spawned = make_launcher()
    assert launcher.maybe_launch(**{**READY, "needs_resolve": 0}) == "nothing needs BPG"
    assert spawned == []


def test_it_does_not_start_a_second_one():
    launcher, spawned = make_launcher(running=True)
    assert launcher.maybe_launch(**READY) == "already running"
    assert spawned == []


def test_a_child_we_started_counts_as_running_without_a_process_probe():
    """The probe shells out to PowerShell; the child we hold a handle to needs
    no probe at all, and a BPG mid-encode must not be launched over."""
    launcher, spawned = make_launcher()
    launcher.maybe_launch(**READY)
    assert len(spawned) == 1
    assert launcher.maybe_launch(**READY) == "already running"
    assert len(spawned) == 1


def test_a_dead_child_is_not_relaunched_until_the_cooldown_passes():
    """If BPG exits immediately -- no licence, a dialog, a moved install -- a
    tick-rate relaunch would start Resolve every 15 seconds."""
    now = {"t": 1000.0}
    launcher, spawned = make_launcher(
        spawn=lambda cmd: FakeChild(alive=False), clock=lambda: now["t"])
    assert launcher.maybe_launch(**READY) is None
    assert launcher.maybe_launch(**READY) == "launched too recently"
    now["t"] += bpg.RELAUNCH_COOLDOWN_SECONDS + 1
    assert launcher.maybe_launch(**READY) is None


def test_a_spawn_that_raises_is_not_fatal_and_still_backs_off():
    def boom(cmd):
        raise OSError("no such file")

    launcher, _ = make_launcher(spawn=boom)
    assert launcher.maybe_launch(**READY) == "launch failed"
    assert launcher.maybe_launch(**READY) == "launched too recently"


def test_no_installation_means_disabled_not_broken(tmp_path):
    """command=None is "go and look", so this points bpg_path at a file that
    does not exist -- the same answer a machine with no Resolve gives, without
    depending on whether THIS machine happens to have one installed."""
    launcher, spawned = make_launcher(
        cfg={"bpg_path": str(tmp_path / "nope.exe")}, command=None)
    assert launcher.command is None
    assert launcher.enabled is False
    assert launcher.maybe_launch(**READY) == "disabled"
    assert spawned == []


@pytest.mark.parametrize("explicit,expected", [(True, True), (False, False)])
def test_an_explicit_flag_beats_the_derivation(explicit, expected):
    launcher = bpg.BpgLauncher(
        {"bpg_enabled": explicit}, generation_enabled=False,
        clock=lambda: 0.0, spawn=lambda cmd: FakeChild(),
        running_fn=lambda: False, command=["Resolve.exe", "-pg"],
    )
    assert launcher.enabled is expected


def test_it_derives_off_where_this_machine_does_not_generate():
    """Same rule as proxy_gen_enabled: an editor whose lane B would sweep a
    generated proxy has no business making them with BPG either."""
    launcher = bpg.BpgLauncher(
        {}, generation_enabled=False, clock=lambda: 0.0,
        command=["Resolve.exe", "-pg"],
    )
    assert launcher.enabled is False


# -- telling BPG apart from the editor ---------------------------------------

def test_bpg_is_recognised_by_its_flag_not_its_image_name():
    """They are the SAME binary: the Start-menu shortcut is Resolve.exe -pg.
    tasklist cannot answer this question, which is why it is not used."""
    editor = ['"C:\\Program Files\\Blackmagic Design\\DaVinci Resolve\\Resolve.exe"']
    generator = [editor[0] + " -pg"]
    assert bpg.is_bpg_running(lambda: editor) is False
    assert bpg.is_bpg_running(lambda: generator) is True
    assert bpg.is_bpg_running(lambda: editor + generator) is True


@pytest.mark.parametrize("unknown", [None, []])
def test_an_unreadable_process_list_does_not_block_a_launch(unknown):
    """Reported as "not running": a wrong launch costs a focused window, a
    wrong "already running" costs the BRAW gap never closing."""
    assert bpg.is_bpg_running(lambda: unknown) is False


# -- what the gate is allowed to COST (MED-8/MED-9, 2026-08-11) ---------------

def test_the_idle_probe_may_be_a_callable_and_is_asked_last():
    """Every Mac editor forked ioreg every 15 s for this value, on a platform
    where BPG does not exist -- the caller evaluated it eagerly and the
    launcher discards it on its first line. A callable is asked only once the
    cheap conditions have passed."""
    asked = {"n": 0}

    def _away():
        asked["n"] += 1
        return True

    launcher, spawned = make_launcher()
    assert launcher.maybe_launch(queue_empty=True, needs_resolve=0,
                                 user_away=_away) == "nothing needs BPG"
    assert asked["n"] == 0

    assert launcher.maybe_launch(queue_empty=True, needs_resolve=6,
                                 user_away=_away) is None
    assert asked["n"] == 1
    assert spawned == [["Resolve.exe", "-pg"]]


def test_the_process_probe_is_not_run_inside_the_cooldown():
    """It is a PowerShell spawn, and inside the cooldown its answer cannot
    change the outcome."""
    probes = {"n": 0}

    def _running():
        probes["n"] += 1
        return False

    launcher = bpg.BpgLauncher(
        {}, generation_enabled=True, clock=lambda: 1000.0,
        spawn=lambda cmd: FakeChild(alive=False), running_fn=_running,
        command=["Resolve.exe", "-pg"],
    )
    assert launcher.maybe_launch(**READY) is None
    assert probes["n"] == 1
    assert launcher.maybe_launch(**READY) == "launched too recently"
    assert probes["n"] == 1


def test_the_command_line_read_is_ttl_cached(monkeypatch):
    """The gate asks on every 15 s tick for as long as a BRAW gap exists, and
    the launcher's cheap short-circuit only covers a BPG we started
    ourselves -- an editor who opened it from the Start menu paid a
    PowerShell per tick."""
    runs = {"n": 0}

    class _Out:
        returncode = 0
        stdout = "Resolve.exe -pg\n"

    monkeypatch.setattr(bpg.platform, "system", lambda: "Windows")
    monkeypatch.setattr(bpg.subprocess, "run",
                        lambda *a, **kw: (runs.__setitem__("n", runs["n"] + 1), _Out())[1])

    assert bpg._cim_command_lines() == ["Resolve.exe -pg"]
    assert bpg._cim_command_lines() == ["Resolve.exe -pg"]
    assert runs["n"] == 1

    bpg._reset_probe_cache()
    assert bpg._cim_command_lines() == ["Resolve.exe -pg"]
    assert runs["n"] == 2


def test_a_failed_read_is_cached_too(monkeypatch):
    """"Cannot tell" means the same as "not running" to every caller, so
    re-spawning PowerShell to be told nothing again is pure cost."""
    runs = {"n": 0}

    def _boom(*a, **kw):
        runs["n"] += 1
        raise OSError("powershell is not on PATH")

    monkeypatch.setattr(bpg.platform, "system", lambda: "Windows")
    monkeypatch.setattr(bpg.subprocess, "run", _boom)

    assert bpg._cim_command_lines() is None
    assert bpg._cim_command_lines() is None
    assert runs["n"] == 1


def test_a_launch_forgets_the_cached_process_list(monkeypatch):
    """The cache is a cost saver, not a state: a BPG we just started must not
    be masked by a read taken before it existed."""
    monkeypatch.setattr(bpg.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        bpg.subprocess, "run",
        lambda *a, **kw: type("O", (), {"returncode": 0, "stdout": ""})(),
    )
    assert bpg._cim_command_lines() == []
    assert bpg._probe_cache is not None

    launcher, spawned = make_launcher()
    assert launcher.maybe_launch(**READY) is None
    assert spawned
    assert bpg._probe_cache is None


# -- the watch list: an empty one is a silent no-op (2026-08-13) -------------

RUSKIN = r"P:\Projects\2026\CCT\Creator Profiles\Season 1\B-roll\Editor Added\ruskin"


def write_ini(tmp_path, value=bpg.INVALID_MARKER, extra="codecType=1\n"):
    ini = tmp_path / "ProxyGeneratorSettings.ini"
    ini.write_text(f"[General]\nwatchFolderList={value}\n{extra}", encoding="utf-8")
    return ini


@pytest.mark.parametrize("value,expected", [
    (bpg.INVALID_MARKER, []),
    ("", []),
    (r"P:\\Projects", [r"P:\Projects"]),
    (r"P:\\Projects, W:\\Temp Transfer", [r"P:\Projects", r"W:\Temp Transfer"]),
    (r'"C:\\a,b", D:\\c', [r"C:\a,b", r"D:\c"]),
])
def test_the_qt_list_is_read_the_way_qt_writes_it(value, expected):
    """@Invalid() is what the base rig's list had decayed to, and reading it as
    a path would have been worse than reading it as nothing."""
    assert bpg.parse_watch_folders(value) == expected


def test_a_folder_is_added_to_an_empty_list(tmp_path):
    ini = write_ini(tmp_path)
    result = bpg.ensure_watch_folders([RUSKIN], path=str(ini))
    assert result["ok"] is True and result["added"] == [RUSKIN]
    text = ini.read_text(encoding="utf-8")
    assert bpg.parse_watch_folders(
        text.splitlines()[1].split("=", 1)[1]) == [RUSKIN]
    # Everything else in the file is the user's and survives untouched.
    assert "codecType=1" in text


def test_an_existing_entry_is_kept_verbatim(tmp_path):
    """The value text is carried over as text, never re-serialised: a parse we
    get subtly wrong must cost a redundant entry, never the user's list."""
    ini = write_ini(tmp_path, value=r"W:\\Temp Transfer")
    assert bpg.ensure_watch_folders([RUSKIN], path=str(ini))["ok"] is True
    value = ini.read_text(encoding="utf-8").splitlines()[1].split("=", 1)[1]
    assert value.startswith(r"W:\\Temp Transfer, ")
    assert bpg.parse_watch_folders(value) == [r"W:\Temp Transfer", RUSKIN]


def test_an_ancestor_already_covers_it(tmp_path):
    """Watch folders are recursive: an editor watching P:\\Projects needs
    nothing added, and adding it would grow their list every launch."""
    ini = write_ini(tmp_path, value=r"P:\\Projects")
    before = ini.read_text(encoding="utf-8")
    result = bpg.ensure_watch_folders([RUSKIN], path=str(ini))
    assert result["ok"] is True and result["added"] == []
    assert ini.read_text(encoding="utf-8") == before


def test_the_original_settings_are_backed_up_once(tmp_path):
    ini = write_ini(tmp_path)
    original = ini.read_text(encoding="utf-8")
    bpg.ensure_watch_folders([RUSKIN], path=str(ini))
    backup = tmp_path / ("ProxyGeneratorSettings.ini" + bpg.BACKUP_SUFFIX)
    assert backup.read_text(encoding="utf-8") == original

    bpg.ensure_watch_folders([r"P:\Projects\2026\Other"], path=str(ini))
    # Still the FIRST state: the point is that what the user had is
    # recoverable, not what the last write replaced.
    assert backup.read_text(encoding="utf-8") == original


def test_a_settings_file_that_does_not_exist_yet_is_created(tmp_path):
    """BPG that has never been opened has no settings file."""
    ini = tmp_path / "ProxyGeneratorSettings.ini"
    assert bpg.ensure_watch_folders([RUSKIN], path=str(ini))["ok"] is True
    assert RUSKIN in bpg.parse_watch_folders(
        ini.read_text(encoding="utf-8").splitlines()[1].split("=", 1)[1])


def test_a_machine_with_no_bpg_profile_collects_no_stray_config(tmp_path):
    ini = tmp_path / "nowhere" / "ProxyGeneratorSettings.ini"
    result = bpg.ensure_watch_folders([RUSKIN], path=str(ini))
    assert result["ok"] is False
    assert result["reason"] == "no BPG settings directory"
    assert not ini.parent.exists()


def test_the_settings_directory_is_created_for_a_machine_that_has_resolve(tmp_path):
    """COMP-MEDIA-6: the Preferences directory is created by BPG's first RUN,
    not by the Resolve installer -- so refusing to make it meant the
    precondition for launching BPG was that BPG had already been launched, and
    the whole R14 feature was inert on every machine that needs it. The
    launcher passes create_dir because find_bpg_command has already proved
    there is a proxy generator here."""
    ini = tmp_path / "nowhere" / "ProxyGeneratorSettings.ini"

    result = bpg.ensure_watch_folders([RUSKIN], path=str(ini), create_dir=True)

    assert result["ok"] is True
    assert result["added"] == [RUSKIN]
    assert RUSKIN in bpg.parse_watch_folders(
        ini.read_text(encoding="utf-8").splitlines()[1].split("=", 1)[1])


def test_the_launcher_asks_for_the_directory_to_be_created(tmp_path):
    seen = {}

    def ensure(dirs, path="", create_dir=False):
        seen["create_dir"] = create_dir
        return {"ok": True}

    launcher, spawned = make_launcher(ensure=ensure)
    assert launcher.maybe_launch(**READY, watch_dirs=[RUSKIN]) is None
    assert seen["create_dir"] is True, (
        "maybe_launch already returned on `no proxy generator installed` -- "
        "reaching here means Resolve.exe is there (COMP-MEDIA-6)"
    )


def test_a_settings_directory_that_cannot_be_created_is_still_not_fatal(tmp_path):
    """An unwritable %APPDATA% is a reason not to launch, never a crash."""
    blocker = tmp_path / "nowhere"
    blocker.write_text("I am a file, not a directory", encoding="utf-8")
    ini = blocker / "ProxyGeneratorSettings.ini"

    result = bpg.ensure_watch_folders([RUSKIN], path=str(ini), create_dir=True)

    assert result["ok"] is False
    assert result["reason"] == "settings file could not be written"


def test_the_list_is_not_grown_without_limit(tmp_path):
    ini = write_ini(tmp_path)
    wanted = [rf"P:\Projects\2026\P{n}" for n in range(bpg.MAX_ADDED_PER_LAUNCH + 5)]
    result = bpg.ensure_watch_folders(wanted, path=str(ini))
    assert result["ok"] is True
    assert len(result["added"]) == bpg.MAX_ADDED_PER_LAUNCH


def test_nothing_wanted_writes_nothing(tmp_path):
    ini = write_ini(tmp_path)
    before = ini.read_text(encoding="utf-8")
    assert bpg.ensure_watch_folders([], path=str(ini))["ok"] is True
    assert ini.read_text(encoding="utf-8") == before


# -- the spawn itself ---------------------------------------------------------

def test_the_launch_strips_the_pinned_python_home_from_resolve(monkeypatch):
    """COMP-MEDIA-3: PYTHONHOME/PYTHON3HOME are pinned process-wide at OUR
    _MEIPASS in a frozen build and the bootloader deletes that directory when
    the tray exits -- and this child is Resolve.exe, which locates and
    LoadLibrary()s its Python by exactly those two variables. Every other
    spawn in the package already sanitizes; this one did not."""
    monkeypatch.setenv("PYTHONHOME", "C:/mei-12345")
    monkeypatch.setenv("PYTHON3HOME", "C:/mei-12345")
    monkeypatch.setenv("APPDATA", "C:/Users/ed/AppData/Roaming")
    seen = {}

    def _popen(command, **kwargs):
        seen["command"] = command
        seen.update(kwargs)
        return FakeChild()

    monkeypatch.setattr(bpg.subprocess, "Popen", _popen)
    bpg._spawn_detached(["Resolve.exe", "-pg"])

    assert "PYTHONHOME" not in seen["env"]
    assert "PYTHON3HOME" not in seen["env"]
    # A sanitized env, not an empty one: Resolve needs APPDATA to find its
    # own settings, and everything else the editor's session carries.
    assert seen["env"]["APPDATA"] == "C:/Users/ed/AppData/Roaming"


def test_the_process_probe_and_the_start_press_sanitize_too(monkeypatch):
    monkeypatch.setenv("PYTHONHOME", "C:/mei-12345")
    monkeypatch.setattr(bpg.platform, "system", lambda: "Windows")
    seen: list[dict] = []

    class _Out:
        returncode = 0
        stdout = "pressed"
        stderr = ""

    def _run(argv, **kwargs):
        seen.append(kwargs)
        return _Out()

    monkeypatch.setattr(bpg.subprocess, "run", _run)
    bpg._cim_command_lines()
    bpg.press_start(wait_seconds=1, run_fn=_run)

    assert len(seen) == 2
    assert all("PYTHONHOME" not in kwargs["env"] for kwargs in seen)


# -- the launcher's half of it -----------------------------------------------

def test_the_watch_folders_are_set_before_anything_is_started(tmp_path):
    seen = {}

    def ensure(dirs, path="", create_dir=False):
        seen["dirs"] = list(dirs)
        seen["create_dir"] = create_dir
        return {"ok": True}

    launcher, spawned = make_launcher(ensure=ensure)
    assert launcher.maybe_launch(**READY, watch_dirs=[RUSKIN]) is None
    assert seen["dirs"] == [RUSKIN]
    assert spawned == [["Resolve.exe", "-pg"]]


def test_a_generator_that_would_watch_nothing_is_not_started(tmp_path):
    """The 2026-08-13 failure exactly: launching regardless meant a window
    opening three times a day for months while the gap never moved."""
    launcher, spawned = make_launcher(
        ensure=lambda dirs, path="", create_dir=False: {"ok": False, "reason": "boom"})
    assert launcher.maybe_launch(**READY, watch_dirs=[RUSKIN]) == (
        "watch folders could not be set")
    assert spawned == []
    # No cooldown was burnt: this cost a file read, so the next tick may retry.
    assert launcher._last_launch_at is None


def test_an_ensure_that_raises_is_not_fatal():
    def boom(dirs, path="", create_dir=False):
        raise OSError("read-only settings")

    launcher, spawned = make_launcher(ensure=boom)
    assert launcher.maybe_launch(**READY, watch_dirs=[RUSKIN]) == (
        "watch folders could not be set")
    assert spawned == []


def test_managing_the_watch_list_can_be_turned_off():
    """Writing a file the editor owns is an intrusion, and the opt-out must
    not also stop the launch."""
    called = {"n": 0}

    def ensure(dirs, path="", create_dir=False):
        called["n"] += 1
        return {"ok": True}

    launcher, spawned = make_launcher(
        cfg={"bpg_manage_watch_folders": False}, ensure=ensure)
    assert launcher.maybe_launch(**READY, watch_dirs=[RUSKIN]) is None
    assert called["n"] == 0
    assert spawned


# -- the Start button: BPG does not start itself (2026-08-13) ----------------

def test_start_is_pressed_after_a_launch():
    presses = []
    launcher, spawned = make_launcher(press=lambda: presses.append("x") or "pressed")
    assert launcher.maybe_launch(**READY, watch_dirs=[RUSKIN]) is None
    assert len(presses) == 1


def test_a_bpg_somebody_else_left_idle_is_poked_too():
    """Clips waiting, generator up, nothing encoding is the same dead end
    whoever opened the window."""
    presses = []
    launcher, spawned = make_launcher(
        running=True, press=lambda: presses.append("x") or "pressed")
    assert launcher.maybe_launch(**READY) == "already running"
    assert len(presses) == 1
    assert spawned == []


def test_the_poke_is_rate_limited():
    """It is a PowerShell spawn on a 15 s tick -- the cost MED-9 was about."""
    now = {"t": 1000.0}
    presses = []
    launcher, _ = make_launcher(
        running=True, clock=lambda: now["t"],
        press=lambda: presses.append("x") or "already-running")
    launcher.maybe_launch(**READY)
    launcher.maybe_launch(**READY)
    assert len(presses) == 1
    now["t"] += bpg.START_POKE_COOLDOWN_SECONDS + 1
    launcher.maybe_launch(**READY)
    assert len(presses) == 2


def test_autostart_can_be_turned_off():
    presses = []
    launcher, spawned = make_launcher(
        cfg={"bpg_autostart": False}, press=lambda: presses.append("x") or "pressed")
    assert launcher.maybe_launch(**READY, watch_dirs=[RUSKIN]) is None
    assert presses == []
    assert spawned


def test_a_press_that_raises_does_not_break_the_launch():
    def boom():
        raise RuntimeError("no UI automation here")

    launcher, spawned = make_launcher(press=boom)
    # The spawn already happened; the press is the convenience on top of it.
    assert launcher.maybe_launch(**READY, watch_dirs=[RUSKIN]) is None
    assert spawned


@pytest.mark.parametrize("stdout,expected", [
    ("pressed\n", "pressed"),
    ("already-running\n", "already-running"),
    ("no-window\n", "no-window"),
    ("", "failed"),
])
def test_the_start_press_reports_what_the_window_said(monkeypatch, stdout, expected):
    monkeypatch.setattr(bpg.platform, "system", lambda: "Windows")
    out = type("O", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()
    assert bpg.press_start(wait_seconds=1, run_fn=lambda *a, **kw: out) == expected


def test_the_start_press_is_windows_only(monkeypatch):
    monkeypatch.setattr(bpg.platform, "system", lambda: "Darwin")

    def boom(*a, **kw):
        raise AssertionError("no PowerShell on a Mac")

    assert bpg.press_start(run_fn=boom) == "not-windows"


def test_a_configured_path_that_does_not_exist_is_no_command(tmp_path):
    assert bpg.find_bpg_command(str(tmp_path / "nope.exe")) is None


def test_a_configured_path_is_launched_with_the_pg_flag(tmp_path):
    exe = tmp_path / "Resolve.exe"
    exe.write_text("", encoding="utf-8")
    assert bpg.find_bpg_command(str(exe)) == [str(exe), "-pg"]
