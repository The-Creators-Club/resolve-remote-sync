"""The music half of the dashboard deploy: does a deploy actually SHIP /music?

The dashboard has mounted the music app at /music in code for a while, and the
installer had never heard of music -- so every deploy produced a container
whose mount reported `absent` behind a green healthcheck. That failure is
invisible from the outside, which is why the checks here are about the
INSTALLER and the COMPOSE FILE rather than about the app.

Everything is offline: the shell-level tests run the generated remote scripts
under a stub `sudo` in a temp directory (the same harness test_safety.py uses),
and the install-path test points the installer at a temp "host root" with a
fake NAS behind it, so the real one is never touched.

Run with:
    cd E:\\Projects\\resolve-remote-sync\\server
    python -m pytest tests -q
"""
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402
import install_dashboard_app as ida  # noqa: E402

from test_safety import run_remote_script  # noqa: E402

BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(BASH is None, reason="a POSIX shell is required")

REPO = Path(__file__).resolve().parents[2]
COMPOSE_YAML = REPO / "dashboard" / "deploy" / "compose.yaml"
RUN_SH = REPO / "dashboard" / "deploy" / "run.sh"

# The three container paths the music app is assembled from, and the one thing
# that has to be true of each of them.
MUSIC_MOUNTS = {
    "/music-app": "ro",       # code: never writable by the process running it
    "/music-data": "rw",      # music.db + staging/: the app writes both
    "/music-encoder": "ro",   # exported CLAP text tower
    "/music-proxies": "ro",   # 128k preview mp3s
    "/music-share": "rw",     # the library: queued ingest lands files in it
    "/opt/ffmpeg": "ro",      # static ffmpeg/ffprobe
}


def _service() -> dict:
    return ida.compose_config(
        8480, "/mnt/tank/apps/ccsync-dashboard", "http://gui:8384", "k", "t",
        "s", "truenas_admin", "h", "u", "pw",
    )["services"]["dashboard"]


# --------------------------------------------------------------------------
# The container's environment: MUSIC_-prefixed, because it is SHARED
# --------------------------------------------------------------------------

def test_music_env_is_prefixed_and_points_at_the_mounts():
    """musicweb honours bare DATA_ROOT/MUSIC_ROOT as fallbacks, and this
    container's environment is shared with the dashboard and with the b-roll
    mount (which namespaces everything BROLL_*). Setting the generic names here
    is a collision waiting to happen, so the prefixed ones are set instead."""
    env = _service()["environment"]
    assert env["MUSIC_DATA_ROOT"] == "/music-data"
    assert env["MUSIC_SHARE_ROOT"] == "/music-share"
    assert env["MUSIC_PROXIES_DIR"] == "/music-proxies"
    assert env["MUSIC_TEXT_ENCODER_DIR"] == "/music-encoder"
    for generic in ("DATA_ROOT", "MUSIC_ROOT", "PROXIES_DIR"):
        assert generic not in env, f"{generic} is unprefixed in a shared environment"


def test_there_is_no_music_enable_flag_or_ingest_token():
    """Deliberate asymmetry with b-roll, and the reason is in DEPLOY.md: b-roll
    needs a flag because it has a credential the dashboard refuses to start
    without. Nothing under /music is exempt from login_gate, so the session is
    the credential and shipping the tree is the switch. A flag here would be a
    second, silent way to lose the feature."""
    env = _service()["environment"]
    assert "DASH_MUSIC_ENABLED" not in env
    assert "MUSIC_INGEST_TOKEN" not in env


def test_ffmpeg_is_not_wired_through_the_env_vars_musicweb_trusts():
    """musicweb._tool() returns $FFMPEG/$FFPROBE WITHOUT checking that the path
    exists, and only falls back to shutil.which() when they are unset. Setting
    them to /opt/ffmpeg/* would make _require_ffmpeg pass on a host where the
    provisioning step was skipped, turning a clean 503 into a
    FileNotFoundError partway through an upload. PATH is the honest wiring."""
    env = _service()["environment"]
    assert "FFMPEG" not in env and "FFPROBE" not in env
    # ffmpeg stays FIRST on PATH: /opt/claude and /opt/deno joined the line for
    # the ytdl mount, and neither may displace the pinned ffmpeg build.
    assert ('export PATH="/opt/ffmpeg:/opt/claude:/opt/deno:$PATH"'
            in RUN_SH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# The mounts themselves
# --------------------------------------------------------------------------

def test_every_music_mount_exists_with_the_right_mode():
    volumes = _service()["volumes"]
    for container_path, mode in MUSIC_MOUNTS.items():
        matches = [v for v in volumes if f":{container_path}:" in v]
        assert len(matches) == 1, f"{container_path} is mounted {len(matches)} times"
        assert matches[0].endswith(f":{mode}"), (
            f"{container_path} must be {mode}: {matches[0]}"
        )


def test_the_data_root_is_writable_and_the_code_root_is_not():
    """The two failures this splits apart. A read-only /music-data is the
    DEGRADED state -- sqlite answers "unable to open database file" on every
    request -- and a writable /music-app is remote code execution in a
    container holding TRUENAS_PW, exactly as it would be for /app."""
    volumes = _service()["volumes"]
    assert any(v.endswith("/music-web:/music-app:ro") for v in volumes)
    assert any(v.endswith("/music-data:/music-data:rw") for v in volumes)


def test_the_music_share_is_the_library_not_a_private_copy():
    """Same rule as the b-roll archive: one set of media serves the search UI
    and the editors' timelines. A private copy under the app root would mean
    9.5 GB twice, and the ingested track would never appear on P:."""
    volumes = _service()["volumes"]
    assert f"{ida.DEFAULT_MUSIC_LIBRARY_ROOT}:/music-share:rw" in volumes
    assert ida.DEFAULT_MUSIC_LIBRARY_ROOT.startswith(common.DEFAULT_CC_ROOT + "/Assets")
    assert not any("music-share:/music-share" in v for v in volumes), (
        "the music data mount is the shared library, not <host-root>/music-share"
    )


def test_compose_yaml_carries_the_same_music_mounts():
    """test_safety.py already asserts the whole volume list matches; this says
    which lines matter, so a drift failure names the feature that broke."""
    text = COMPOSE_YAML.read_text(encoding="utf-8")
    vol_block = text.split("\n    volumes:", 1)[1].split("\n    restart:", 1)[0]
    yaml_vols = [line.strip().lstrip("- ").strip().strip('"').strip("'")
                 for line in vol_block.splitlines()
                 if line.strip().startswith("- ")]
    for container_path, mode in MUSIC_MOUNTS.items():
        assert f"{container_path}:{mode}" in [":".join(v.split(":")[-2:])
                                              for v in yaml_vols], (
            f"compose.yaml has no {container_path}:{mode} mount"
        )


# --------------------------------------------------------------------------
# run.sh -- all three app roots on PYTHONPATH
# --------------------------------------------------------------------------

def test_pythonpath_carries_every_app_root():
    """/music-app on PYTHONPATH is the entire difference between a mounted
    music UI and one that reports `absent` with a single WARNING in the log --
    and /ytdl-app is the same statement about the YouTube downloader."""
    text = RUN_SH.read_text(encoding="utf-8")
    m = re.search(r"^export PYTHONPATH=(\S+)$", text, re.M)
    assert m, "run.sh no longer exports a single-line PYTHONPATH"
    roots = m.group(1).split(":")
    assert roots == ["/app/src", "/broll-app", "/music-app", "/ytdl-app"], roots


def test_pythonpath_entries_are_all_actually_mounted():
    """A path entry pointing at a volume nobody mounts is free, but a MOUNT
    nobody puts on the path is the bug this whole change exists to fix."""
    text = RUN_SH.read_text(encoding="utf-8")
    roots = re.search(r"^export PYTHONPATH=(\S+)$", text, re.M).group(1).split(":")
    mounted = {v.split(":")[-2] for v in _service()["volumes"]}
    for root in roots:
        if root == "/app/src":          # inside the /app mount
            continue
        assert root in mounted, f"{root} is on PYTHONPATH but nothing mounts it"


# --------------------------------------------------------------------------
# What the code push contains -- and, above all, what it does not
# --------------------------------------------------------------------------

def test_the_code_push_excludes_the_14gb_of_data():
    """data/ rides its own switch (--music-data). In the code tree it would be
    1.4 GB of model artefact and preview mp3s on EVERY dashboard deploy, over
    paramiko's SFTP, to land in a read-only mount the app cannot write."""
    src = ida.music_web_source()
    if not (src / "musicweb" / "main.py").is_file():
        pytest.skip(f"no musicweb/main.py under {src}")
    rels = [rel for _p, rel in ida.iter_local_files(src, ida.MUSIC_EXCLUDE_DIRS)]
    assert rels, "the music code push is empty"
    assert "musicweb/main.py" in rels
    assert "schema.sql" in rels
    assert not [r for r in rels if r.startswith("data/")], "data/ is in the code push"
    assert not [r for r in rels if r.startswith("tests/")]
    assert not [r for r in rels if ".venv" in r or "__pycache__" in r]
    _count, size = ida.local_manifest(src, ida.MUSIC_EXCLUDE_DIRS)
    assert size < 20 * 1024 * 1024, f"the music code push is {size} bytes"


def test_the_data_components_are_the_three_things_that_ship_separately():
    assert ida.MUSIC_DATA_COMPONENTS == ("db", "encoder", "proxies")
    paths = ida.music_component_paths("/mnt/tank/apps/ccsync-dashboard")
    assert paths["db"].endswith("/music-data/music.db")
    assert paths["encoder"].endswith("/music-encoder")
    assert paths["proxies"].endswith("/music-proxies")


@pytest.mark.parametrize("raw,expected", [
    ("auto", set()),
    ("none", set()),
    ("", set()),
    ("all", {"db", "encoder", "proxies"}),
    ("db", {"db"}),
    ("db,proxies", {"db", "proxies"}),
    (" ENCODER ", {"encoder"}),
])
def test_parse_music_data_push(raw, expected):
    forced, err = ida.parse_music_data_push(raw)
    assert (forced, err) == (expected, "")


def test_parse_music_data_push_rejects_nonsense():
    forced, err = ida.parse_music_data_push("db,waveforms")
    assert forced == set()
    assert "waveforms" in err and "db" in err


def test_auto_ships_only_what_the_nas_lacks(monkeypatch):
    """The whole point of the split: the first install is the 1.4 GB one and a
    routine dashboard deploy pushes nothing."""
    monkeypatch.setattr(ida, "music_components_present",
                        lambda root, dry_run: {"db": True, "encoder": True,
                                               "proxies": False})
    assert ida.music_components_to_push("/r", "auto", set(), False) == ["proxies"]

    monkeypatch.setattr(ida, "music_components_present",
                        lambda root, dry_run: dict.fromkeys(ida.MUSIC_DATA_COMPONENTS,
                                                            True))
    assert ida.music_components_to_push("/r", "auto", set(), False) == []


def test_forced_components_ship_even_when_present(monkeypatch):
    """--music-data all is how a re-index is published; if "already there"
    could veto it, there would be no way to update the index at all."""
    monkeypatch.setattr(ida, "music_components_present",
                        lambda root, dry_run: dict.fromkeys(ida.MUSIC_DATA_COMPONENTS,
                                                            True))
    assert ida.music_components_to_push("/r", "all", {"db", "encoder", "proxies"},
                                        False) == ["db", "encoder", "proxies"]
    assert ida.music_components_to_push("/r", "db", {"db"}, False) == ["db"]


def test_none_ships_nothing_and_asks_the_nas_nothing(monkeypatch):
    monkeypatch.setattr(
        ida, "music_components_present",
        lambda *a, **k: pytest.fail("--music-data none must not probe the NAS"))
    assert ida.music_components_to_push("/r", "none", set(), False) == []


def test_an_empty_component_dir_on_the_nas_counts_as_missing(monkeypatch):
    """Step 1 creates music-encoder/ and music-proxies/ empty. If "auto" read
    those as present, the artefacts would never ship at all and /music/api/
    search would 500 forever."""
    sent = {}

    def fake_run_ssh(cmd, dry_run=False, timeout=120):
        sent["cmd"] = cmd
        return 0, "db yes\nencoder no\nproxies no\n", ""

    monkeypatch.setattr(ida, "run_ssh", fake_run_ssh)
    present = ida.music_components_present("/mnt/tank/apps/ccsync-dashboard", False)
    assert present == {"db": True, "encoder": False, "proxies": False}
    assert "ls -A" in sent["cmd"], "an existing but EMPTY directory must not count"


def test_an_unreachable_probe_reports_everything_missing(monkeypatch):
    """Better to re-push than to conclude "already there" from a failed
    check and deploy a music UI with no index."""
    monkeypatch.setattr(ida, "run_ssh", lambda *a, **k: (255, "", "no route to host"))
    assert ida.music_components_present("/r", False) == {
        "db": False, "encoder": False, "proxies": False}


# --------------------------------------------------------------------------
# The index swap -- install_tree's guarantees, for a file the container writes
# --------------------------------------------------------------------------

def _seed_db(tmp_path, body=b"NEW INDEX\n"):
    """(data_root, staging, expected_bytes) with a live index already in place."""
    data_root = tmp_path / "root" / "music-data"
    data_root.mkdir(parents=True)
    (data_root / "music.db").write_bytes(b"OLD INDEX\n")
    (data_root / "music.db-wal").write_bytes(b"OLD WAL\n")
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "music.db").write_bytes(body)
    return data_root, staging, len(body)


@needs_bash
def test_db_swap_installs_and_keeps_the_previous_index(tmp_path):
    data_root, staging, size = _seed_db(tmp_path)
    old = str(data_root / "music.db.old.20260810120000")
    script = ida.build_db_swap_script(str(data_root), str(staging),
                                      str(data_root / "music.db"), old, size)
    proc = run_remote_script(script, tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert (data_root / "music.db").read_bytes() == b"NEW INDEX\n"
    # the previous index is preserved, not deleted (standing no-deletion rule)
    assert Path(old).read_bytes() == b"OLD INDEX\n"
    assert not staging.exists()
    assert not (data_root / "music.db.new").exists()


@needs_bash
def test_db_swap_moves_the_wal_aside_with_the_database_it_belongs_to(tmp_path):
    """music.db is in WAL mode (write/read version 2 in its header). A stale
    -wal left beside a freshly replaced database is how a working index
    becomes a corrupt one -- and it must be MOVED, not deleted, because it is
    the only copy of whatever those transactions were."""
    data_root, staging, size = _seed_db(tmp_path)
    old = str(data_root / "music.db.old.20260810120000")
    script = ida.build_db_swap_script(str(data_root), str(staging),
                                      str(data_root / "music.db"), old, size)
    proc = run_remote_script(script, tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert not (data_root / "music.db-wal").exists(), "a stale WAL survived the swap"
    assert Path(old + "-wal").read_bytes() == b"OLD WAL\n"


@needs_bash
def test_db_swap_leaves_the_live_index_alone_when_the_copy_is_short(tmp_path):
    data_root, staging, size = _seed_db(tmp_path)
    (staging / "music.db").write_bytes(b"trunc")      # right file, wrong bytes
    old = str(data_root / "music.db.old.20260810120000")
    script = ida.build_db_swap_script(str(data_root), str(staging),
                                      str(data_root / "music.db"), old, size)
    proc = run_remote_script(script, tmp_path)

    assert proc.returncode == 8
    assert "incomplete" in proc.stderr
    assert (data_root / "music.db").read_bytes() == b"OLD INDEX\n"
    assert (data_root / "music.db-wal").read_bytes() == b"OLD WAL\n"
    assert not Path(old).exists()


@needs_bash
def test_db_swap_rolls_back_when_the_swap_in_fails(tmp_path):
    data_root, staging, size = _seed_db(tmp_path)
    old = str(data_root / "music.db.old.20260810120000")
    script = ida.build_db_swap_script(str(data_root), str(staging),
                                      str(data_root / "music.db"), old, size)
    live = ida.shell_quote(str(data_root / "music.db"))
    candidate = ida.shell_quote(str(data_root / "music.db.new"))
    # delete the verified candidate in the instant between the two renames
    sabotage = script.replace(f"mv {live} ", f"rm -f {candidate}; mv {live} ", 1)
    proc = run_remote_script(sabotage, tmp_path)

    assert proc.returncode == 9
    assert "previous index restored" in proc.stderr
    assert (data_root / "music.db").read_bytes() == b"OLD INDEX\n"


def test_db_ownership_is_the_container_not_root():
    """install_tree chowns root:root and strips group write, which is correct
    for code and would make every queued ingest fail to write its `pending`
    row into the index."""
    script = ida.build_db_swap_script("/r/music-data", "/tmp/s",
                                      "/r/music-data/music.db", "/r/old", 10)
    assert "chown 3000:3000" in script
    assert "chown -R root:root" not in script
    assert "chmod 660" in script


# --------------------------------------------------------------------------
# ffmpeg -- provisioned, because nothing here builds an image
# --------------------------------------------------------------------------

@pytest.mark.parametrize("script", [
    ida.build_ffmpeg_install_script(
        "/mnt/tank/apps/ccsync-dashboard/ffmpeg",
        ida.DEFAULT_FFMPEG_URL, ida.DEFAULT_FFMPEG_SHA256),
    ida.build_ffmpeg_unpack_script(
        "/mnt/tank/apps/ccsync-dashboard/ffmpeg", "/tmp/s/ffmpeg.tar.xz",
        "/tmp/s", ida.DEFAULT_FFMPEG_SHA256),
], ids=["remote-download", "lan-push"])
def test_ffmpeg_script_is_idempotent_pinned_and_self_checking(script):
    """Both provisioning paths -- the NAS downloading it and this machine
    pushing it over the LAN -- get the same guarantees. The checksum is not
    decoration in either: remotely it is the internet being verified, locally it
    is a 42 MB SFTP."""
    # already installed -> does nothing (a redeploy must not re-download 42 MB)
    assert "already provisioned" in script and "exit 0" in script
    # checksum before unpacking
    assert ida.DEFAULT_FFMPEG_SHA256 in script and "sha256sum -c" in script
    assert script.index("sha256sum -c") < script.index("tar -xJf")
    # and the candidate is EXECUTED before it is moved into place
    assert "-version" in script
    assert script.index("-version") < script.index("mv ")
    assert "does not run on this host" in script


@needs_bash
def test_a_corrupted_transfer_installs_nothing(tmp_path):
    """The failure the LAN push introduces that the download did not: SFTP wrote
    something other than what was sent. A bare `printf | sha256sum -c` under
    `set -e` would report the pipeline's LAST command, so this asserts on the
    explicit `if !` and its exit code."""
    staging, target = tmp_path / "staging", tmp_path / "ffmpeg"
    staging.mkdir()
    (staging / "ffmpeg.tar.xz").write_bytes(b"half a tarball")
    script = ida.build_ffmpeg_unpack_script(
        str(target), str(staging / "ffmpeg.tar.xz"), str(staging),
        ida.DEFAULT_FFMPEG_SHA256)
    proc = run_remote_script(script, tmp_path)

    assert proc.returncode == 7
    assert "transfer was corrupted" in proc.stderr
    assert not target.exists()


def test_the_lan_push_cleans_up_its_staging():
    """42 MB per deploy, in /tmp on a NAS. install_tree's staging is removed by
    its swap script for the same reason."""
    script = ida.build_ffmpeg_unpack_script("/r/ffmpeg", "/tmp/s/ffmpeg.tar.xz",
                                            "/tmp/s", "d" * 64)
    assert "rm -rf '/tmp/s'" in script
    assert script.index("rm -rf '/tmp/s'") > script.index("mv '/r/ffmpeg'/ffmpeg.new")


def test_the_pinned_ffmpeg_url_is_versioned_not_rolling():
    """johnvansickle's ffmpeg-release-amd64-static.tar.xz is a rolling pointer:
    its bytes change under a pinned hash the day a new release lands, and the
    install then fails the checksum for a reason that looks like tampering."""
    assert "ffmpeg-release-amd64-static" not in ida.DEFAULT_FFMPEG_URL
    assert re.search(r"ffmpeg-\d+\.\d+(\.\d+)?-amd64-static\.tar\.xz$",
                     ida.DEFAULT_FFMPEG_URL)
    assert len(ida.DEFAULT_FFMPEG_SHA256) == 64


def test_an_overridden_url_drops_the_pinned_hash(monkeypatch, capsys):
    """The hash belongs to the URL. Checking the pinned one against somebody
    else's mirror fails confusingly; not checking it is the honest behaviour,
    and it is said out loud."""
    cmds: list = []
    monkeypatch.setenv("MUSIC_FFMPEG_URL", "https://mirror.invalid/ffmpeg.tar.xz")
    transcript = _dry_run(monkeypatch, capsys, cmds, extra_argv=["--ffmpeg-fetch",
                                                                "remote"])
    assert "will NOT be checksummed" in transcript
    ffmpeg_cmd = next(c for c in cmds if "mirror.invalid" in c)
    assert ida.DEFAULT_FFMPEG_SHA256 not in ffmpeg_cmd
    assert "sha256sum" not in ffmpeg_cmd


def test_the_default_is_to_fetch_here_and_push_over_the_lan(monkeypatch, capsys):
    """The first deploy of this app died here: the step runs BEFORE any tree
    ships, the NAS pulls johnvansickle at ~28 kB/s, and 42 MB does not fit in
    run_ssh's 600s timeout. Nothing had landed -- but nothing could land."""
    cmds: list = []
    transcript = _dry_run(monkeypatch, capsys, cmds)
    assert "push it to the NAS over the LAN" in transcript
    assert not any(ida.DEFAULT_FFMPEG_URL in c for c in cmds), (
        "the NAS must not be the one downloading it by default")
    unpack = next(c for c in cmds if "tar -xJf" in c)
    assert "ccsync-ffmpeg-upload" in unpack and "curl" not in unpack


def test_an_already_provisioned_host_is_not_re_fetched(monkeypatch, capsys):
    """The remote scripts are idempotent on their own, which was enough when the
    NAS did the downloading. It is not enough now: without this probe a routine
    redeploy fetches and pushes 42 MB to be told "already provisioned"."""
    monkeypatch.setattr(ida, "run_ssh", lambda *a, **k: (0, "yes\n", ""))
    calls: list = []
    monkeypatch.setattr(ida, "fetch_ffmpeg_tarball",
                        lambda *a: calls.append(a) or (None, "should not run"))
    ida.provision_ffmpeg("/mnt/tank/apps/ccsync-dashboard", "local", dry_run=False)

    assert calls == []
    assert "already provisioned" in capsys.readouterr().out


def test_no_ffmpeg_skips_the_step_entirely(monkeypatch, capsys):
    cmds: list = []
    _dry_run(monkeypatch, capsys, cmds, extra_argv=["--no-ffmpeg"])
    assert not any("ffmpeg.tar.xz" in c for c in cmds)


# -- the local fetch. Offline: the network is stubbed or asserted unused. -----

class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("the network was used")
    monkeypatch.setattr(ida.urllib.request, "urlopen", refuse)


def test_a_supplied_tarball_is_still_checked_against_the_pin(monkeypatch, tmp_path):
    """MUSIC_FFMPEG_FILE is the escape hatch for a host that cannot download --
    not an escape hatch from the checksum."""
    _no_network(monkeypatch)
    tarball = tmp_path / "ffmpeg.tar.xz"
    tarball.write_bytes(b"not the pinned build")
    monkeypatch.setenv("MUSIC_FFMPEG_FILE", str(tarball))

    path, err = ida.fetch_ffmpeg_tarball(ida.DEFAULT_FFMPEG_URL,
                                         ida.DEFAULT_FFMPEG_SHA256)
    assert path is None and "does not match the pinned sha256" in err

    path, err = ida.fetch_ffmpeg_tarball(ida.DEFAULT_FFMPEG_URL,
                                         ida.sha256_file(tarball))
    assert path == tarball and err == ""


def test_the_cache_saves_the_second_deploy_a_download(monkeypatch, tmp_path):
    _no_network(monkeypatch)
    monkeypatch.setenv("MUSIC_FFMPEG_CACHE", str(tmp_path))
    cached = ida.ffmpeg_cache_path(ida.DEFAULT_FFMPEG_URL)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(b"pretend tarball")

    path, err = ida.fetch_ffmpeg_tarball(ida.DEFAULT_FFMPEG_URL,
                                         ida.sha256_file(cached))
    assert path == cached and err == ""


def test_a_cached_tarball_that_fails_the_pin_is_re_downloaded(monkeypatch, tmp_path):
    """A cache whose only job is to skip a download must never be the reason a
    wrong build gets installed."""
    monkeypatch.setenv("MUSIC_FFMPEG_CACHE", str(tmp_path))
    cached = ida.ffmpeg_cache_path(ida.DEFAULT_FFMPEG_URL)
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(b"stale bytes from an older pin")
    good = b"the real tarball"
    monkeypatch.setattr(ida.urllib.request, "urlopen",
                        lambda *a, **k: _FakeResponse(good))

    path, err = ida.fetch_ffmpeg_tarball(ida.DEFAULT_FFMPEG_URL,
                                         hashlib.sha256(good).hexdigest())
    assert err == "" and path.read_bytes() == good


def test_a_download_that_fails_the_pin_is_not_left_in_the_cache(monkeypatch, tmp_path):
    """Otherwise one truncated transfer poisons every later deploy, with an
    error that reads like tampering."""
    monkeypatch.setenv("MUSIC_FFMPEG_CACHE", str(tmp_path))
    monkeypatch.setattr(ida.urllib.request, "urlopen",
                        lambda *a, **k: _FakeResponse(b"half a tarball"))

    path, err = ida.fetch_ffmpeg_tarball(ida.DEFAULT_FFMPEG_URL,
                                         ida.DEFAULT_FFMPEG_SHA256)
    assert path is None and "does not match the pinned sha256" in err
    assert list(tmp_path.rglob("*.part")) == []
    assert not ida.ffmpeg_cache_path(ida.DEFAULT_FFMPEG_URL).exists()


def test_two_urls_never_share_a_cache_entry(tmp_path, monkeypatch):
    """Every static-ffmpeg mirror names its tarball the same thing."""
    monkeypatch.setenv("MUSIC_FFMPEG_CACHE", str(tmp_path))
    a = ida.ffmpeg_cache_path("https://a.invalid/ffmpeg-amd64-static.tar.xz")
    b = ida.ffmpeg_cache_path("https://b.invalid/ffmpeg-amd64-static.tar.xz")
    assert a != b
    assert a.name.endswith("ffmpeg-amd64-static.tar.xz")


def test_a_failed_local_fetch_is_a_note_not_a_failed_deploy(monkeypatch, capsys):
    """The whole point of the step being non-fatal: /music's ingest answers 503
    with a readable message, and the other 19 files still ship."""
    monkeypatch.setattr(ida, "run_ssh", lambda *a, **k: (0, "no\n", ""))
    monkeypatch.setattr(ida, "fetch_ffmpeg_tarball",
                        lambda *a: (None, "URLError: unreachable"))
    ida.provision_ffmpeg("/mnt/tank/apps/ccsync-dashboard", "local", dry_run=False)

    err = capsys.readouterr().err
    assert "ffmpeg was NOT provisioned" in err and "URLError" in err
    assert "MUSIC_FFMPEG_FILE" in err and "--ffmpeg-fetch remote" in err


# --------------------------------------------------------------------------
# The install as a whole, against a temp host root and a fake NAS
# --------------------------------------------------------------------------

def _dry_run(monkeypatch, capsys, cmds, extra_argv=()):
    """Run a --dry-run install, recording every command. Returns the transcript."""
    def record(cmd, dry_run=False, timeout=120):
        cmds.append(cmd)
        return 0, "", ""

    for name, value in (("SYNCTHING_API_KEY", "k"), ("DASH_REPORT_TOKEN", "t"),
                        ("DASH_SESSION_SECRET", "s"), ("TRUENAS_PW", "pw"),
                        ("BROLL_INGEST_TOKEN", "ingestTOKENsentinel4b7d1e9a03c6")):
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(ida, "run_ssh", record)
    monkeypatch.setattr(sys, "argv", ["install_dashboard_app.py", "--dry-run",
                                      *extra_argv])
    assert ida.main() == 0
    captured = capsys.readouterr()
    return "\n".join([captured.out, captured.err, *cmds])


def test_a_deploy_ships_the_music_tree_and_prepares_every_host_dir(monkeypatch, capsys):
    cmds: list = []
    transcript = _dry_run(monkeypatch, capsys, cmds)

    dirs_cmd = next(c for c in cmds if "music-data" in c and "mkdir -p" in c)
    for name in ("music-web", "music-data", "music-encoder", "music-proxies",
                 "ffmpeg"):
        assert name in dirs_cmd, f"{name} is never created on the host"
    # the code dirs keep /app's posture; only the data root is container-owned.
    # (The command is single-quoted for `sudo -S sh -c`, so match on the shape
    # rather than on a quoted path.)
    assert "chown 3000:3000" in dirs_cmd
    assert "3000:3001" not in dirs_cmd, "the editors group must not own music-data"
    assert dirs_cmd.count("chmod 755") >= 1 and "chmod 770" in dirs_cmd
    # the tree itself is actually pushed
    assert "ccsync-musicweb-upload" in transcript
    assert "/music-web.new" in transcript and "/music-web.old." in transcript


def test_the_music_library_root_is_prepared_like_projects(monkeypatch, capsys):
    """Left to Docker the bind source is auto-created root:root 0755, the
    container (3000:3001) cannot write into it, and every queued ingest fails.
    2770 setgid broll:editors, NOT 770 group-3000 -- editors browse this
    library over SMB as P:\\Assets\\Music."""
    cmds: list = []
    _dry_run(monkeypatch, capsys, cmds)

    lib = next(c for c in cmds if ida.DEFAULT_MUSIC_LIBRARY_ROOT in c)
    assert "chown 3000:3001" in lib and "chmod 2770" in lib
    assert "chmod 770 " not in lib


def test_a_missing_music_tree_warns_and_deploys_anyway(monkeypatch, capsys, tmp_path):
    """The deliberate asymmetry with b-roll. Nothing on the command line
    asserted the operator wanted music, so a checkout without it must not fail
    the deploy of the thing that tells everyone whether their footage is
    syncing."""
    cmds: list = []
    monkeypatch.setenv("MUSIC_WEB_SRC", str(tmp_path / "nowhere"))
    transcript = _dry_run(monkeypatch, capsys, cmds)

    assert "NOTE" in transcript and "no music app at" in transcript
    assert "absent" in transcript
    assert not any("musicweb-upload" in c for c in cmds)
    # ...and nothing music-shaped was pushed, including the library prep
    assert not any(ida.DEFAULT_MUSIC_LIBRARY_ROOT in c for c in cmds)


def test_music_data_none_pushes_no_data_but_still_ships_the_code(monkeypatch, capsys):
    cmds: list = []
    transcript = _dry_run(monkeypatch, capsys, cmds,
                          extra_argv=["--music-data", "none"])

    assert "ccsync-musicweb-upload" in transcript
    for slug in ("ccsync-musicdb-upload", "ccsync-musicencoder-upload",
                 "ccsync-musicproxies-upload"):
        assert slug not in transcript, f"{slug} ran under --music-data none"


def test_a_bad_music_data_value_is_refused_before_anything_is_touched(monkeypatch,
                                                                     capsys):
    def boom(*a, **k):
        raise AssertionError("a rejected --music-data must not touch the NAS")

    monkeypatch.setattr(ida, "run_ssh", boom)
    monkeypatch.setattr(sys, "argv", ["install_dashboard_app.py", "--dry-run",
                                      "--music-data", "everything"])
    assert ida.main() == 1
    assert "unknown --music-data component" in capsys.readouterr().err


def test_the_dry_run_says_how_big_the_push_is(monkeypatch, capsys):
    """1.4 GB over paramiko's SFTP is a decision, not a detail. The operator
    sees the size before it starts."""
    src = ida.music_data_source()
    if not src.is_dir():
        pytest.skip(f"no music data under {src}")
    cmds: list = []
    transcript = _dry_run(monkeypatch, capsys, cmds)
    assert "music data to ship" in transcript
    assert re.search(r"total", transcript)
    assert re.search(r"\d+(\.\d+)? (MB|GB)", transcript)


@needs_bash
def test_the_install_lands_where_compose_expects_it(tmp_path):
    """End to end against a TEMP host root and a stub sudo -- no NAS involved.

    Proves the thing that was actually broken: after an install, the paths the
    compose file bind-mounts at /music-app, /music-data, /music-encoder and
    /music-proxies exist on the host and hold the right files.
    """
    root = tmp_path / "mnt" / "apps" / "ccsync-dashboard"
    root.mkdir(parents=True)

    # a miniature music/web + data/, standing in for the real 1.4 GB
    src = tmp_path / "src"
    (src / "musicweb").mkdir(parents=True)
    (src / "musicweb" / "main.py").write_text("app = 1\n", encoding="utf-8")
    (src / "schema.sql").write_text("-- schema\n", encoding="utf-8")
    data = src / "data"
    (data / "text_encoder").mkdir(parents=True)
    (data / "text_encoder" / "text_encoder.onnx").write_text("ONNX\n", encoding="utf-8")
    (data / "proxies").mkdir()
    (data / "proxies" / "1.mp3").write_text("MP3\n", encoding="utf-8")
    (data / "music.db").write_text("SQLite index\n", encoding="utf-8")

    # the code tree, and the two read-only artefact trees
    for target, source in (("music-web", src),
                           ("music-encoder", data / "text_encoder"),
                           ("music-proxies", data / "proxies")):
        excludes = ida.MUSIC_EXCLUDE_DIRS
        count, size = ida.local_manifest(source, excludes)
        staging = tmp_path / f"staging-{target}"
        # ignore_patterns(*MUSIC_EXCLUDE_DIRS) is what makes the code staging
        # dir data/-free, exactly as iter_local_files does for the real upload.
        shutil.copytree(source, staging,
                        ignore=shutil.ignore_patterns(*excludes))
        script = ida.build_swap_script(
            str(root), str(staging), f"{root / (target + '.new')}",
            f"{root / (target + '.old.20260810120000')}", count, size,
            target_dir=str(root / target))
        proc = run_remote_script(script, tmp_path)
        assert proc.returncode == 0, f"{target}: {proc.stderr}"

    # ...and the index, which goes to the writable data root
    db_staging = tmp_path / "staging-db"
    db_staging.mkdir()
    shutil.copy(data / "music.db", db_staging / "music.db")
    db_script = ida.build_db_swap_script(
        str(root / "music-data"), str(db_staging),
        str(root / "music-data" / "music.db"),
        str(root / "music-data" / "music.db.old.20260810120000"),
        (data / "music.db").stat().st_size)
    proc = run_remote_script(db_script, tmp_path)
    assert proc.returncode == 0, proc.stderr

    # Every host path the compose file names now exists and holds what the app
    # imports/opens. host_root -> container_path, read straight off compose.
    for volume in _service()["volumes"]:
        host_path, container_path = volume.split(":")[0], volume.split(":")[1]
        if container_path not in ("/music-app", "/music-data", "/music-encoder",
                                  "/music-proxies"):
            continue
        landed = root / Path(host_path).name
        assert landed.is_dir(), f"{container_path} would mount an absent {landed}"

    assert (root / "music-web" / "musicweb" / "main.py").read_text() == "app = 1\n"
    assert (root / "music-web" / "schema.sql").is_file()
    assert not (root / "music-web" / "data").exists(), "the 1.4 GB rode along"
    assert (root / "music-data" / "music.db").read_text() == "SQLite index\n"
    assert (root / "music-encoder" / "text_encoder.onnx").is_file()
    assert (root / "music-proxies" / "1.mp3").is_file()


@needs_bash
def test_the_installed_tree_is_readable_by_the_container_uid(tmp_path):
    """The mounts are :ro and the container runs as 3000:3001, so every file
    has to be world-readable -- a 0600 model artefact is a mount that exists
    and cannot be opened, which the app reports as a fallback to full CLAP
    (and a 500 on /music/api/search).

    The script-shape half of this runs everywhere; the half that reads real
    mode bits back off the filesystem only runs on a POSIX one.
    """
    root = tmp_path / "root"
    root.mkdir()
    staging = tmp_path / "staging"
    staging.mkdir()
    secret = staging / "text_encoder.onnx"
    secret.write_text("ONNX\n", encoding="utf-8")
    secret.chmod(0o600)
    count, size = ida.local_manifest(staging, ida.MUSIC_EXCLUDE_DIRS)
    script = ida.build_swap_script(
        str(root), str(staging), str(root / "music-encoder.new"),
        str(root / "music-encoder.old.20260810120000"), count, size,
        target_dir=str(root / "music-encoder"))
    assert "chmod -R u+rwX,go+rX,go-w" in script
    proc = run_remote_script(script, tmp_path)

    assert proc.returncode == 0, proc.stderr
    assert (root / "music-encoder" / "text_encoder.onnx").is_file()
    if os.name == "nt":
        pytest.skip("POSIX modes are not meaningful on this filesystem "
                    "-- the chmod in the script above is asserted instead")
    mode = (root / "music-encoder" / "text_encoder.onnx").stat().st_mode
    assert mode & 0o044, "the shipped artefact is not world-readable"
    assert not mode & 0o022, "the shipped artefact is group/other writable"


def test_the_installer_never_ships_the_indexer():
    """music/indexer needs a GPU, ffmpeg and a local mount of the library. Only
    two routes touch it and both degrade cleanly; shipping it would put a
    torch-importing tree on the NAS for nothing."""
    src = ida.music_web_source()
    if not (src / "musicweb" / "main.py").is_file():
        pytest.skip(f"no musicweb/main.py under {src}")
    rels = [rel for _p, rel in ida.iter_local_files(src, ida.MUSIC_EXCLUDE_DIRS)]
    assert not [r for r in rels if r.startswith("indexer/")]
    assert "MUSIC_INDEXER_DIR" not in _service()["environment"]
