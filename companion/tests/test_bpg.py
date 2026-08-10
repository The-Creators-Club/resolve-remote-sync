"""BPG is started only when nothing else is encoding, and never stopped.

Every test here runs against injected collaborators: the real ones start
DaVinci Resolve.
"""
import pytest

from ccsync_companion import bpg


class FakeChild:
    def __init__(self, alive=True):
        self._alive = alive

    def poll(self):
        return None if self._alive else 0


_DEFAULT = object()


def make_launcher(cfg=None, *, running=False, spawn=None, clock=None,
                 command=_DEFAULT):
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


def test_a_configured_path_that_does_not_exist_is_no_command(tmp_path):
    assert bpg.find_bpg_command(str(tmp_path / "nope.exe")) is None


def test_a_configured_path_is_launched_with_the_pg_flag(tmp_path):
    exe = tmp_path / "Resolve.exe"
    exe.write_text("", encoding="utf-8")
    assert bpg.find_bpg_command(str(exe)) == [str(exe), "-pg"]
