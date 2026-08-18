"""The AI CLI setup wizard: install, pointer flip, sign-in session, routes.

2026-08-18, `cli_tools.py`. Four properties this file exists to hold down:

* **Nothing is installed that the publisher did not sign for.** The sha256 in
  the publisher's manifest is checked BEFORE the pointer moves, a mismatch
  leaves nothing behind, and a version string that is not a version number
  never becomes a URL segment or a directory name.
* **The pointer flip is the only moment a version goes live**, so a failed or
  killed install cannot leave a half-written binary that the next probe would
  run.
* **The sign-in code and the OAuth token are never written down** -- not in a
  status, not in an error, not in a log line. What crosses is a URL out and a
  code back, which is the companion's YouTube sign-in shape.
* **Probe, Test and the real ytdl call share ONE environment helper.** A
  status chip about a different `$HOME` than the job uses is worse than no
  chip.

No test here opens a socket, runs a CLI or spawns a pty: `_fetch_bytes`,
`_fetch_json`, `release_feed.open_https_stream`, `_spawn_pty` and
`subprocess.run` are the seams, and every one of them is replaced.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
import threading
import time

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import ai_providers, auth, cli_tools
from ccsync_dashboard import db as dbmod
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "test-secret"
ADMIN = "owen"
EDITOR = "editor1"

ROUTE = "/api/v1/admin/ai-providers"


@pytest.fixture(autouse=True)
def _cold_module_state():
    """Every latch in this module is a process global (one install at a time,
    one sign-in at a time). One test's leftovers must not decide the next."""
    cli_tools._install_status.clear()
    cli_tools._install_running = ""
    cli_tools._signin = None
    cli_tools._signin_last.clear()
    ai_providers.reset_probe_cache()
    yield
    cli_tools.cancel_signin()
    cli_tools._install_status.clear()
    cli_tools._install_running = ""
    cli_tools._signin = None
    cli_tools._signin_last.clear()
    ai_providers.reset_probe_cache()


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                    admin_users=frozenset({ADMIN}))


@pytest.fixture
def env(tmp_path, monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(db_path=str(tmp_path / "ai.db"), session_secret=SECRET,
                        admin_users=frozenset({ADMIN}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "ai.db")
        yield client, conn, settings
        conn.close()


def as_user(client, user):
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, user))
    return client


def enable_cli(conn):
    conn.execute(
        "INSERT INTO site_settings (key, value, updated_at, updated_by) "
        "VALUES ('features.ai_cli_providers','1','now','test') "
        "ON CONFLICT(key) DO UPDATE SET value='1'")
    conn.commit()


# ------------------------------------------------------------ platform facts

@pytest.mark.parametrize("machine,expected", [
    ("x86_64", "linux-x64"), ("amd64", "linux-x64"),
    ("aarch64", "linux-arm64"), ("arm64", "linux-arm64"),
])
def test_the_platform_key_is_the_publishers_spelling(machine, expected, monkeypatch):
    monkeypatch.setattr(cli_tools, "_is_musl", lambda: False)
    assert cli_tools.platform_key(machine, "linux") == expected


def test_a_non_linux_dashboard_is_refused_by_name(monkeypatch):
    monkeypatch.setattr(cli_tools, "_is_musl", lambda: False)
    with pytest.raises(cli_tools.UnsupportedPlatform) as exc:
        cli_tools.platform_key("x86_64", "win32")
    # The dev machine. The refusal has to say WHICH thing it is refusing, or
    # it costs a support call.
    assert "win32" in str(exc.value)
    assert "type its path" in str(exc.value) or "path below" in str(exc.value)


def test_an_unknown_architecture_is_refused_by_name(monkeypatch):
    monkeypatch.setattr(cli_tools, "_is_musl", lambda: False)
    with pytest.raises(cli_tools.UnsupportedPlatform) as exc:
        cli_tools.platform_key("mips64", "linux")
    assert "mips64" in str(exc.value)


def test_a_musl_container_is_refused_rather_than_given_the_glibc_build(monkeypatch):
    monkeypatch.setattr(cli_tools, "_is_musl", lambda: True)
    with pytest.raises(cli_tools.UnsupportedPlatform) as exc:
        cli_tools.platform_key("x86_64", "linux")
    assert "musl" in str(exc.value)


def test_codex_takes_the_musl_triple_on_glibc_too(monkeypatch):
    """The publisher's own install.sh picks musl on EVERY Linux (read
    2026-08-18): the Linux builds are static, and there is no -gnu asset."""
    monkeypatch.setattr(cli_tools, "_is_musl", lambda: False)
    assert cli_tools.codex_target("x86_64", "linux") == "x86_64-unknown-linux-musl"
    assert cli_tools.codex_target("aarch64", "linux") == "aarch64-unknown-linux-musl"


# --------------------------------------------------------- manifest parsing

MANIFEST = {
    "version": "2.1.234",
    "platforms": {
        "linux-x64": {"binary": "claude", "size": 328358192,
                      "checksum": "3473601ea695d5bf769c5b202844d4cb4fbf723ae995450fcb6973204775c84a"},
        "darwin-arm64": {"binary": "claude", "size": 1, "checksum": "0" * 64},
    },
}


def test_the_manifest_yields_the_checksum_for_our_platform():
    entry = cli_tools.claude_platform_entry(MANIFEST, "linux-x64")
    assert entry["checksum"].startswith("3473601")
    assert entry["size"] == 328358192
    assert entry["binary"] == "claude"


def test_a_manifest_without_our_platform_names_the_ones_it_has():
    with pytest.raises(cli_tools.ToolError) as exc:
        cli_tools.claude_platform_entry(MANIFEST, "linux-arm64")
    assert "darwin-arm64" in str(exc.value) and "linux-x64" in str(exc.value)


@pytest.mark.parametrize("bad", [
    {"platforms": {"linux-x64": {"checksum": "nope"}}},
    {"platforms": {"linux-x64": {"checksum": "ab" * 31}}},
    {"platforms": {}},
    {"platforms": "not a map"},
    "not a manifest",
])
def test_an_unusable_manifest_is_a_refusal_not_a_download(bad):
    with pytest.raises(cli_tools.ToolError):
        cli_tools.claude_platform_entry(bad, "linux-x64")


@pytest.mark.parametrize("bad", [
    "latest", "2.1", "../../etc", "2.1.234/../..", "2.1.234 2", "",
    "v2.1.234", "2.1.234/claude", "2.1.234;rm -rf /",
])
def test_a_version_that_is_not_a_version_never_becomes_a_path(bad):
    """It is interpolated into a URL AND used as a directory name, so this is
    the one string in the module that could be a traversal."""
    with pytest.raises(cli_tools.ToolError):
        cli_tools.validate_version(bad)


def test_the_binary_url_is_the_publishers_shape():
    url = cli_tools.claude_binary_url("2.1.234", "linux-x64")
    assert url == ("https://downloads.claude.ai/claude-code-releases/"
                   "2.1.234/linux-x64/claude")
    assert url.startswith("https://")


def test_the_latest_endpoint_answer_is_validated(monkeypatch):
    assert cli_tools.latest_claude_version(lambda url: b"2.1.234\n") == "2.1.234"
    with pytest.raises(cli_tools.ToolError):
        cli_tools.latest_claude_version(lambda url: b"<html>maintenance</html>")


# ------------------------------------------------------------- codex parsing

CODEX_RELEASE = {
    "tag_name": "rust-v0.147.0",
    "assets": [
        {"name": "codex-package-x86_64-unknown-linux-musl.tar.gz",
         "browser_download_url": "https://github.com/openai/codex/releases/download/"
                                 "rust-v0.147.0/codex-package-x86_64-unknown-linux-musl.tar.gz"},
        {"name": "codex-package_SHA256SUMS",
         "browser_download_url": "https://github.com/openai/codex/releases/download/"
                                 "rust-v0.147.0/codex-package_SHA256SUMS"},
        {"name": "codex-x86_64-apple-darwin.dmg",
         "browser_download_url": "http://insecure.example/dmg"},
    ],
}


def test_the_codex_tag_becomes_a_plain_version():
    assert cli_tools.codex_version(CODEX_RELEASE) == "0.147.0"


def test_a_codex_asset_url_must_be_https():
    assert cli_tools.codex_asset(CODEX_RELEASE, "codex-package_SHA256SUMS")
    # http:// is not a URL this module will fetch, so it is not one it returns.
    assert cli_tools.codex_asset(CODEX_RELEASE, "codex-x86_64-apple-darwin.dmg") == ""
    assert cli_tools.codex_asset(CODEX_RELEASE, "nothing-like-this") == ""


def test_the_publishers_checksum_file_is_parsed_per_asset():
    text = ("bd758d53d56e41dc65e045f4589df79a038ed197a011adcb52a258e6ad64cfda  "
            "codex-package-x86_64-unknown-linux-musl.tar.gz\n"
            "9dbf1a83c46769d12355dc90b10fa61f51c28a97df37ccccf56fc6e4bab6b9eb  "
            "codex-app-server-package-x86_64-unknown-linux-musl.tar.gz\n")
    assert cli_tools.parse_sha256sums(
        text, "codex-package-x86_64-unknown-linux-musl.tar.gz").startswith("bd758d5")
    # An asset the file does not cover reads as "no checksum", which the UI
    # says out loud rather than pretending it verified something.
    assert cli_tools.parse_sha256sums(text, "codex-symbols.tar.gz") == ""


def make_tar(path, names):
    payload = b"#!/bin/true\n"
    with tarfile.open(path, "w:gz") as tar:
        for name in names:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(payload))
    return path


def test_the_codex_archive_is_unpacked_in_the_publishers_layout(tmp_path):
    archive = make_tar(tmp_path / "pkg.tar.gz", ["bin/codex", "codex-path/rg"])
    dest = tmp_path / "out"
    cli_tools._extract_codex_package(archive, dest)
    assert (dest / "bin" / "codex").is_file()
    assert (dest / "codex-path" / "rg").is_file()


def test_an_archive_with_a_traversal_member_is_walked_away_from(tmp_path):
    archive = make_tar(tmp_path / "evil.tar.gz", ["bin/codex", "../escaped"])
    dest = tmp_path / "out"
    with pytest.raises(cli_tools.ToolError) as exc:
        cli_tools._extract_codex_package(archive, dest)
    assert "nothing was installed" in str(exc.value)
    # Not beside the tree, and not a half-unpacked tree either: a package with
    # a `..` member is one to walk away from, not one to salvage.
    assert not (tmp_path / "escaped").exists()
    assert not dest.exists()


# ----------------------------------------------------- download + checksums

class FakeResponse:
    """Just enough of an http.client.HTTPResponse for the streaming reader."""

    def __init__(self, data: bytes, chunk: int = 9):
        self._data = data
        self._at = 0
        self._chunk = chunk

    def read(self, size=-1):
        end = self._at + (self._chunk if size in (-1, None) else min(size, self._chunk))
        out = self._data[self._at:end]
        self._at = end
        return out

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def close(self):
        pass


def serve(monkeypatch, data: bytes):
    seen = []

    def opener(url, *, timeout):
        seen.append(url)
        return FakeResponse(data)

    monkeypatch.setattr(cli_tools.release_feed, "open_https_stream", opener)
    return seen


def test_a_download_that_matches_the_publishers_sha_is_kept(tmp_path, monkeypatch):
    payload = b"pretend this is 313 MiB of claude"
    serve(monkeypatch, payload)
    dest = tmp_path / "claude.part"
    sha, size = cli_tools._download("https://x/claude", dest,
                                    cap=1 << 20,
                                    expected_sha=hashlib.sha256(payload).hexdigest(),
                                    expected_size=len(payload),
                                    progress=lambda got: None)
    assert dest.read_bytes() == payload
    assert size == len(payload) and sha == hashlib.sha256(payload).hexdigest()


def test_a_download_whose_sha_is_wrong_leaves_nothing_behind(tmp_path, monkeypatch):
    serve(monkeypatch, b"substituted bytes")
    dest = tmp_path / "claude.part"
    with pytest.raises(cli_tools.ToolError) as exc:
        cli_tools._download("https://x/claude", dest, cap=1 << 20,
                            expected_sha="ab" * 32, expected_size=0,
                            progress=lambda got: None)
    assert "sha256" in str(exc.value)
    assert "Nothing was installed" in str(exc.value)
    # THE HALF-WRITTEN FILE IS GONE. A partial binary that survived would be
    # one probe away from being executed.
    assert not dest.exists()


def test_a_download_whose_size_disagrees_with_the_manifest_is_refused(tmp_path, monkeypatch):
    payload = b"short"
    serve(monkeypatch, payload)
    dest = tmp_path / "claude.part"
    with pytest.raises(cli_tools.ToolError):
        cli_tools._download("https://x/claude", dest, cap=1 << 20,
                            expected_sha=hashlib.sha256(payload).hexdigest(),
                            expected_size=999, progress=lambda got: None)
    assert not dest.exists()


def test_a_runaway_response_is_capped(tmp_path, monkeypatch):
    serve(monkeypatch, b"x" * 5000)
    dest = tmp_path / "claude.part"
    with pytest.raises(cli_tools.ToolError) as exc:
        cli_tools._download("https://x/claude", dest, cap=100, expected_sha="",
                            expected_size=0, progress=lambda got: None)
    assert "exceeded" in str(exc.value)
    assert not dest.exists()


def test_progress_is_reported_while_it_streams(tmp_path, monkeypatch):
    serve(monkeypatch, b"y" * 90)
    seen = []
    cli_tools._download("https://x/claude", tmp_path / "p", cap=1 << 20,
                        expected_sha="", expected_size=0, progress=seen.append)
    assert seen and seen[-1] == 90 and len(seen) > 1


# --------------------------------------------------------- the pointer flip

def test_the_pointer_flip_is_what_makes_a_version_live(settings, tmp_path):
    name = cli_tools.CLAUDE_CODE
    assert cli_tools.installed_binary(settings, name) == ""
    version_dir = cli_tools.tool_root(settings, name) / "2.1.234"
    version_dir.mkdir(parents=True)
    (version_dir / "claude").write_text("#!/bin/true\n", encoding="utf-8")
    # Written but not pointed at: still "not installed".
    assert cli_tools.installed_binary(settings, name) == ""
    cli_tools._finish_install(settings, name, version="2.1.234", rel="claude",
                              sha="a" * 64, size=12, url="https://x/claude",
                              checksum_source="publisher_manifest")
    assert cli_tools.installed_binary(settings, name) == str(version_dir / "claude")
    state = cli_tools.read_state(settings, name)
    assert state["installed_version"] == "2.1.234"
    assert state["sha256"] == "a" * 64
    assert state["installed_at"]
    assert state["checksum_verified"] is True


def test_a_pointer_to_a_missing_binary_reads_as_not_installed(settings):
    name = cli_tools.CLAUDE_CODE
    cli_tools.pointer_path(settings, name).parent.mkdir(parents=True, exist_ok=True)
    cli_tools.pointer_path(settings, name).write_text("9.9.9/claude", encoding="utf-8")
    # Not a crash and not a false positive: the pointer is a FILE we read and
    # then check, which is the whole reason it is not a symlink.
    assert cli_tools.installed_binary(settings, name) == ""


def test_an_update_replaces_the_pointer_and_prunes_the_old_tree(settings):
    name = cli_tools.CLAUDE_CODE
    for version in ("2.1.234", "2.1.240"):
        d = cli_tools.tool_root(settings, name) / version
        d.mkdir(parents=True)
        (d / "claude").write_text("x", encoding="utf-8")
    cli_tools._finish_install(settings, name, version="2.1.240", rel="claude",
                              sha="b" * 64, size=1, url="https://x",
                              checksum_source="publisher_manifest")
    assert cli_tools.installed_binary(settings, name).endswith("2.1.240" + os.sep + "claude")
    # 330 MB per version on a NAS with tens of gigabytes free.
    assert not (cli_tools.tool_root(settings, name) / "2.1.234").exists()


def test_a_corrupt_state_file_is_not_a_500(settings):
    name = cli_tools.CLAUDE_CODE
    cli_tools.state_path(settings, name).parent.mkdir(parents=True, exist_ok=True)
    cli_tools.state_path(settings, name).write_text("{not json", encoding="utf-8")
    assert cli_tools.read_state(settings, name) == {}
    assert cli_tools.install_status(settings, name)["state"] == "idle"


def test_remove_takes_the_home_directory_with_it(settings):
    name = cli_tools.CLAUDE_CODE
    home = cli_tools.home_dir(settings, name)
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "creds.json").write_text("{}", encoding="utf-8")
    cli_tools.secrets_boot.write_secret_file(cli_tools.token_path(settings, name),
                                             "sk-ant-oat01-secret")
    cli_tools.remove_install(settings, name)
    assert not cli_tools.tool_root(settings, name).exists()
    # REMOVE means removed: a credential left behind would be inherited by the
    # next install without anybody signing in again.
    assert not cli_tools.token_path(settings, name).exists()
    assert cli_tools.read_token(settings, name) == ""


# --------------------------------------------------- the install-status machine

def install_ok(settings, name="claude_code"):
    """A stand-in for the real per-tool installer."""
    cli_tools._set_status(name, step="downloading", total=100, bytes=50)
    cli_tools._set_status(name, state="done", step="installed", version="1.2.3")


def test_the_status_walks_idle_running_done(settings, monkeypatch):
    name = cli_tools.CLAUDE_CODE
    gate = threading.Event()
    finished = threading.Event()

    def slow(settings_):
        cli_tools._set_status(name, step="downloading", total=100, bytes=25)
        gate.wait(5)
        cli_tools._set_status(name, state="done", step="installed", version="2.1.234")
        finished.set()

    monkeypatch.setattr(cli_tools, "_install_claude", slow)
    monkeypatch.setattr(cli_tools, "install_supported", lambda s: (True, ""))
    assert cli_tools.install_status(settings, name)["state"] == "idle"
    cli_tools.start_install(settings, name)
    for _ in range(50):
        if cli_tools.install_status(settings, name).get("bytes"):
            break
        time.sleep(0.02)
    running = cli_tools.install_status(settings, name)
    assert running["state"] == "running"
    assert running["percent"] == 25          # bytes/total, computed for the bar

    # A SECOND INSTALL IS REFUSED, not queued: two 330 MB downloads onto a NAS
    # that is also serving footage is never what anybody meant.
    with pytest.raises(cli_tools.ToolBusy):
        cli_tools.start_install(settings, name)
    gate.set()
    finished.wait(5)
    for _ in range(50):
        if cli_tools.install_status(settings, name)["state"] == "done":
            break
        time.sleep(0.02)
    assert cli_tools.install_status(settings, name)["state"] == "done"
    # And the latch is released, so the next click works.
    assert cli_tools._install_running == ""


def test_a_failing_install_becomes_an_error_status_not_a_dead_thread(settings, monkeypatch):
    name = cli_tools.CLAUDE_CODE

    def boom(settings_):
        raise cli_tools.ToolError("the publisher answered HTTP 503")

    monkeypatch.setattr(cli_tools, "_install_claude", boom)
    monkeypatch.setattr(cli_tools, "install_supported", lambda s: (True, ""))
    cli_tools.start_install(settings, name)
    for _ in range(100):
        if cli_tools.install_status(settings, name)["state"] == "error":
            break
        time.sleep(0.02)
    status = cli_tools.install_status(settings, name)
    assert status["state"] == "error"
    assert "503" in status["error"]
    assert cli_tools._install_running == ""


def test_an_unsupported_host_is_refused_before_a_thread_starts(settings, monkeypatch):
    monkeypatch.setattr(cli_tools, "install_supported",
                        lambda s: (False, "this dashboard is running on win32"))
    with pytest.raises(cli_tools.ToolError) as exc:
        cli_tools.start_install(settings, cli_tools.CLAUDE_CODE)
    assert "win32" in str(exc.value)
    assert cli_tools._install_running == ""


def test_a_status_call_creates_nothing_on_disk(settings):
    """Rendered on every Settings load, including for a site with the feature
    off. It must not make directories in somebody's data volume."""
    cli_tools.install_supported(settings)
    cli_tools.install_status(settings, cli_tools.CLAUDE_CODE)
    assert not cli_tools.tools_root(settings).exists()


# ------------------------------------------------------- the sign-in session

CLAUDE_OUTPUT = (
    "\x1b[2J\x1b[1;1H Claude Code\r\n"
    "Open this URL in your browser:\r\n"
    "\x1b[4mhttps://claude.ai/oauth/authorize?code=true&state=abc123\x1b[0m\r\n"
    "Paste code here if prompted > "
)


def session(tool=cli_tools.CLAUDE_CODE, expects_code=True):
    s = cli_tools.SignInSession(tool=tool)
    s._expects_code = expects_code
    return s


def test_the_url_is_lifted_out_of_ansi_decorated_output():
    s = session()
    s.feed(CLAUDE_OUTPUT)
    assert s.url == "https://claude.ai/oauth/authorize?code=true&state=abc123"
    assert s.state == "awaiting_code"
    # No escape sequence survives into anything the page renders.
    assert "\x1b" not in s.status()["url"]


def test_a_url_split_across_two_reads_is_still_found():
    s = session()
    s.feed("visit https://claude.ai/oauth/aut")
    # Half a URL is not a URL. There is no second chance at an authorisation
    # link, so nothing is published until the match is terminated.
    assert s.url == "" and s.state == "starting"
    s.feed("horize?state=xyz\r\nPaste code here > ")
    assert s.url.endswith("state=xyz")
    assert s.state == "awaiting_code"


def test_a_device_flow_waits_on_the_browser_and_shows_the_user_code():
    s = session(cli_tools.CODEX, expects_code=False)
    s.feed("Open https://auth.openai.com/device and enter ABCD-EFGH\r\n")
    assert s.state == "awaiting_browser"
    assert s.user_code == "ABCD-EFGH"


def test_a_device_flow_that_then_asks_for_a_paste_switches_to_awaiting_code():
    s = session(cli_tools.CODEX, expects_code=False)
    s.feed("Open https://auth.openai.com/device\r\n")
    assert s.state == "awaiting_browser"
    s.feed("Paste the authorization code here: ")
    assert s.state == "awaiting_code"


def test_the_code_is_written_to_the_pty_with_a_newline():
    s = session()
    s.feed(CLAUDE_OUTPUT)
    read_fd, write_fd = os.pipe()
    s._master = write_fd
    s.write_code("  the-one-time-code  ")
    os.close(write_fd)
    assert os.read(read_fd, 200) == b"the-one-time-code\n"
    os.close(read_fd)
    assert s.state == "verifying"


def test_the_code_is_not_in_the_status_or_the_transcript():
    s = session()
    s.feed(CLAUDE_OUTPUT)
    read_fd, write_fd = os.pipe()
    s._master = write_fd
    s.write_code("SECRET-CODE-1234")
    os.close(write_fd)
    os.close(read_fd)
    blob = json.dumps(s.status())
    assert "SECRET-CODE-1234" not in blob


@pytest.mark.parametrize("bad", ["", "   ", "x" * 2000, "code\x00with-nul"])
def test_a_malformed_code_is_refused_without_being_echoed(bad):
    s = session()
    s.feed(CLAUDE_OUTPUT)
    s._master = 1
    with pytest.raises(cli_tools.ToolError) as exc:
        s.write_code(bad)
    assert bad.strip() not in str(exc.value) or not bad.strip()


def test_a_code_submitted_before_a_url_is_refused():
    s = session()
    with pytest.raises(cli_tools.ToolError) as exc:
        s.write_code("1234")
    assert "not waiting for a code" in str(exc.value)


def test_a_long_lived_token_is_captured_and_scrubbed_from_the_transcript():
    s = session()
    s.feed("Your token:\r\nsk-ant-oat01-AAAABBBBCCCCDDDDEEEEFFFF\r\ndone\r\n")
    token = cli_tools._extract_token(s)
    assert token == "sk-ant-oat01-AAAABBBBCCCCDDDDEEEEFFFF"
    # THE TRANSCRIPT IS AN ERROR MESSAGE. The token must not survive in it,
    # because that string reaches the browser and the log.
    assert token not in s.tail()
    assert token not in json.dumps(s.status())


def test_redaction_covers_anything_token_shaped():
    assert "sk-ant-" in cli_tools._redact("sk-ant-oat01-AAAABBBBCCCCDDDD")
    assert "AAAABBBB" not in cli_tools._redact("sk-ant-oat01-AAAABBBBCCCCDDDD")


def test_an_email_is_masked_not_published():
    assert cli_tools.mask_email("alex@example.com") == "a…x@example.com"
    assert cli_tools.mask_email("jo@example.com") == "…@example.com"
    assert cli_tools.mask_email("") == ""


# ------------------------------------------------------- sign-in, end to end

class FakeProc:
    """A child that never exits until it is killed."""

    def __init__(self):
        self.returncode = None
        self._alive = True

    def poll(self):
        return None if self._alive else self.returncode

    def terminate(self):
        self._alive = False
        self.returncode = -15

    def kill(self):
        self.terminate()

    def wait(self, timeout=None):
        self._alive = False
        self.returncode = self.returncode if self.returncode is not None else -15
        return self.returncode


def test_only_one_sign_in_runs_at_a_time(settings, monkeypatch):
    monkeypatch.setattr(cli_tools, "_pty_available", lambda: True)
    monkeypatch.setattr(cli_tools, "cli_binary", lambda s, n: "/data/tools/claude")

    def stub(settings_, name, sess, binary):
        sess.state = "awaiting_code"
        sess.url = "https://claude.ai/oauth/authorize"

    monkeypatch.setattr(cli_tools, "_signin_worker", stub)
    first = cli_tools.start_signin(settings, cli_tools.CLAUDE_CODE)
    assert first["state"] == "awaiting_code"
    with pytest.raises(cli_tools.ToolBusy):
        cli_tools.start_signin(settings, cli_tools.CLAUDE_CODE)


def test_signing_in_a_cli_that_is_not_installed_is_a_refusal(settings, monkeypatch):
    monkeypatch.setattr(cli_tools, "_pty_available", lambda: True)
    with pytest.raises(cli_tools.ToolError) as exc:
        cli_tools.start_signin(settings, cli_tools.CLAUDE_CODE)
    assert "not installed" in str(exc.value)


def test_a_dashboard_without_a_pty_says_so_rather_than_pretending(settings, monkeypatch):
    monkeypatch.setattr(cli_tools, "cli_binary", lambda s, n: "/data/tools/claude")
    monkeypatch.setattr(cli_tools, "_pty_available", lambda: False)
    with pytest.raises(cli_tools.ToolError) as exc:
        cli_tools.start_signin(settings, cli_tools.CLAUDE_CODE)
    assert "Linux" in str(exc.value)


def test_a_sign_in_that_is_never_finished_is_killed(settings, monkeypatch):
    """Five minutes in the shipped build; a fifth of a second here. The child
    must not be left holding a pty forever because nobody opened the tab."""
    monkeypatch.setattr(cli_tools, "SIGNIN_TIMEOUT", 0.2)
    proc = FakeProc()
    read_fd, write_fd = os.pipe()
    monkeypatch.setattr(cli_tools, "_spawn_pty", lambda argv, env, cwd: (proc, write_fd))
    s = session()
    outcome, detail = cli_tools._run_strategy(
        settings, cli_tools.CLAUDE_CODE, s, "/data/tools/claude",
        cli_tools.SignInStrategy("auth-login", ["auth", "login"]))
    assert outcome == "failed" and "timed out" in detail
    assert proc.poll() is not None                 # terminated, not orphaned
    assert s.state == "failed" and "minutes" in s.detail
    os.close(read_fd)


def test_cancelling_kills_the_child_and_frees_the_slot(settings, monkeypatch):
    monkeypatch.setattr(cli_tools, "_pty_available", lambda: True)
    monkeypatch.setattr(cli_tools, "cli_binary", lambda s, n: "/data/tools/claude")
    proc = FakeProc()

    def stub(settings_, name, sess, binary):
        sess._proc = proc
        sess.state = "awaiting_code"

    monkeypatch.setattr(cli_tools, "_signin_worker", stub)
    cli_tools.start_signin(settings, cli_tools.CLAUDE_CODE)
    cli_tools.cancel_signin(cli_tools.CLAUDE_CODE)
    assert proc.poll() is not None
    assert cli_tools.signin_status(settings, cli_tools.CLAUDE_CODE)["state"] == "cancelled"
    # The slot is free again.
    cli_tools.start_signin(settings, cli_tools.CLAUDE_CODE)


def test_the_login_strategy_is_tried_before_setup_token(monkeypatch):
    monkeypatch.setattr(cli_tools, "_codex_supports_device_auth", lambda b: False)
    order = [s.key for s in cli_tools._strategies(cli_tools.CLAUDE_CODE,
                                                  "subscription", "/x/claude")]
    # setup-token prints a long-lived token we then have to HOLD; the login
    # flow does not. First one that works, and login is asked first.
    assert order == ["auth-login", "setup-token"]


def test_the_console_mode_passes_the_publishers_flag():
    strategies = cli_tools._strategies(cli_tools.CLAUDE_CODE, "console", "/x/claude")
    assert strategies[0].argv_tail == ["auth", "login", "--console"]


def test_codex_device_auth_is_detected_from_the_binary_not_assumed(monkeypatch):
    calls = []

    class Proc:
        returncode = 0
        stdout = "Usage: codex login [--device-auth]"
        stderr = ""

    monkeypatch.setattr(cli_tools.subprocess, "run",
                        lambda argv, **kw: calls.append(argv) or Proc())
    assert cli_tools._codex_supports_device_auth("/x/codex") is True
    assert calls[0][1:] == ["login", "--help"]

    class Old:
        returncode = 0
        stdout = "Usage: codex login"
        stderr = ""

    monkeypatch.setattr(cli_tools.subprocess, "run", lambda argv, **kw: Old())
    assert cli_tools._codex_supports_device_auth("/x/codex") is False


def test_auth_status_parses_the_publishers_json(settings, monkeypatch):
    monkeypatch.setattr(cli_tools, "cli_binary", lambda s, n: "/x/claude")

    class Proc:
        returncode = 0
        stdout = json.dumps({"loggedIn": True, "authMethod": "claude.ai",
                             "email": "alex@example.com", "orgName": "Studio",
                             "subscriptionType": "max"})
        stderr = ""

    monkeypatch.setattr(cli_tools.subprocess, "run", lambda argv, **kw: Proc())
    answer = cli_tools.auth_status(settings, cli_tools.CLAUDE_CODE)
    assert answer["logged_in"] is True
    assert answer["account"] == "a…x@example.com"          # masked, always
    assert answer["method"] == "claude.ai"


def test_auth_status_that_will_not_parse_reads_as_signed_out(settings, monkeypatch):
    monkeypatch.setattr(cli_tools, "cli_binary", lambda s, n: "/x/claude")

    class Proc:
        returncode = 1
        stdout = "Not logged in"
        stderr = ""

    monkeypatch.setattr(cli_tools.subprocess, "run", lambda argv, **kw: Proc())
    # Never "signed in" by accident: an unreadable answer is signed OUT.
    assert cli_tools.auth_status(settings, cli_tools.CLAUDE_CODE)["logged_in"] is False


# ------------------------------------------------------- the one env helper

def test_the_env_helper_strips_the_api_keys_and_sets_our_home(settings, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-be-inherited")
    monkeypatch.setenv("PATH", "/usr/bin")
    name = cli_tools.CLAUDE_CODE
    cli_tools.home_dir(settings, name).mkdir(parents=True)
    env = cli_tools.cli_env(settings, name)
    assert "ANTHROPIC_API_KEY" not in env
    assert env["HOME"] == str(cli_tools.home_dir(settings, name))
    assert env["PATH"] == "/usr/bin"              # the rest is inherited


def test_a_cli_the_customer_installed_themselves_keeps_its_own_home(settings, monkeypatch):
    """The pre-wizard deployment: `claude` on PATH, signed in on the host,
    working. Pointing it at an empty HOME would log it out to tidy a path."""
    monkeypatch.setenv("HOME", "/root")
    env = cli_tools.cli_env(settings, cli_tools.CLAUDE_CODE)
    assert env["HOME"] == "/root"
    assert cli_tools.cli_env_overlay(settings, cli_tools.CLAUDE_CODE) == {}


def test_the_oauth_token_is_passed_through_when_we_hold_one(settings):
    name = cli_tools.CLAUDE_CODE
    cli_tools.home_dir(settings, name).mkdir(parents=True)
    cli_tools.secrets_boot.write_secret_file(cli_tools.token_path(settings, name),
                                             "sk-ant-oat01-TOKEN")
    overlay = cli_tools.cli_env_overlay(settings, name)
    assert overlay[cli_tools.CLAUDE_TOKEN_VAR] == "sk-ant-oat01-TOKEN"


@pytest.fixture
def ytdl_env(tmp_path, monkeypatch):
    """A dashboard with the downloader mounted, which is what puts this
    repo's `ytdl/web` on sys.path -- the only way to compare the two halves of
    the env helper against each other for real rather than by description."""
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    settings = Settings(db_path=str(tmp_path / "y.db"), session_secret=SECRET,
                        admin_users=frozenset({ADMIN}),
                        site_feature_youtube_download=True)
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(tmp_path / "y.db")
        yield client, conn, settings
        conn.close()


def test_probe_test_and_the_ytdl_call_get_the_same_environment(ytdl_env, monkeypatch):
    """ONE helper, three callers. A probe that answered about a different
    $HOME than the job uses is worse than no probe."""
    _client, conn, settings = ytdl_env
    enable_cli(conn)
    name = cli_tools.CLAUDE_CODE
    cli_tools.home_dir(settings, name).mkdir(parents=True)
    monkeypatch.setattr(ai_providers.shutil, "which", lambda b: "/usr/bin/claude")
    seen = []
    monkeypatch.setattr(ai_providers, "_run",
                        lambda argv, stdin, timeout, env_=None, **kw:
                        seen.append(env_ or kw.get("env")) or _Ok())

    class _Ok:
        returncode = 0
        stdout = "ok"
        stderr = ""

    ai_providers.probe_cli(conn, name, force=True, settings=settings)
    probe_env = seen[0]
    assert probe_env["HOME"] == str(cli_tools.home_dir(settings, name))

    payload = ai_providers.lookup_payload(conn, settings)
    assert payload["provider"] == name
    # What crosses to the ytdl app is the OVERLAY, and applying it to the same
    # stripped base gives byte-for-byte what the probe ran with.
    ytdl_backend = pytest.importorskip("ytdlweb.ai_backend")
    provider = ytdl_backend.Provider(name, cli_path=payload["cli_path"],
                                     cli_enabled=True, cli_env=payload["cli_env"])
    assert ytdl_backend._cli_env(provider) == probe_env


def test_the_lookup_payload_never_carries_a_token_for_an_unsigned_in_tool(env):
    _client, conn, settings = env
    enable_cli(conn)
    payload = ai_providers.lookup_payload(conn, settings)
    assert "cli_env" not in payload or not payload.get("cli_env")


# ------------------------------------------------------------------- routes

WRITES = [
    ("post", ROUTE + "/claude_code/install", None),
    ("delete", ROUTE + "/claude_code/install", None),
    ("post", ROUTE + "/claude_code/signin", {"mode": "subscription"}),
    ("post", ROUTE + "/claude_code/signin/code", {"code": "1234"}),
    ("post", ROUTE + "/claude_code/signin/cancel", None),
    ("delete", ROUTE + "/claude_code/signin", None),
]
READS = [
    ("get", ROUTE + "/claude_code/setup"),
    ("get", ROUTE + "/claude_code/install-status"),
    ("get", ROUTE + "/claude_code/signin"),
]


@pytest.mark.parametrize("method,path,body", WRITES)
def test_every_write_route_refuses_an_anonymous_caller(env, method, path, body):
    client, _conn, _settings = env
    resp = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
    assert resp.status_code == 401


@pytest.mark.parametrize("method,path", READS)
def test_every_read_route_refuses_an_anonymous_caller(env, method, path):
    client, _conn, _settings = env
    assert getattr(client, method)(path).status_code == 401


@pytest.mark.parametrize("method,path,body", WRITES)
def test_every_write_route_refuses_a_non_admin(env, method, path, body):
    client, _conn, _settings = env
    as_user(client, EDITOR)
    resp = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
    assert resp.status_code == 403


def test_none_of_these_routes_are_csrf_exempt():
    from ccsync_dashboard import app as appmod

    for _method, path, _body in WRITES:
        assert path not in appmod._CSRF_EXEMPT_EXACT
        assert not path.startswith(appmod._CSRF_EXEMPT_PREFIXES)


def test_an_unknown_tool_is_a_404(env):
    client, _conn, _settings = env
    as_user(client, ADMIN)
    assert client.get(ROUTE + "/anthropic_api/setup").status_code == 404
    assert client.post(ROUTE + "/nonsense/install").status_code == 404


def test_installing_while_cli_providers_are_off_is_refused(env):
    client, _conn, _settings = env
    as_user(client, ADMIN)
    resp = client.post(ROUTE + "/claude_code/install")
    assert resp.status_code == 409
    # Names the step that fixes it, not the config key: the owner went looking
    # for a features page that does not exist (2026-08-18).
    assert "notice" in resp.json()["detail"]


def test_the_setup_route_carries_the_notice_and_the_state(env):
    client, conn, _settings = env
    enable_cli(conn)
    as_user(client, ADMIN)
    data = client.get(ROUTE + "/claude_code/setup").json()
    assert data["notice"]["title"] and data["notice"]["checkbox"]
    assert "subscription" in data["notice"]["text"]
    assert data["install"]["state"] == "idle"
    assert data["signin"]["state"] == "idle"
    assert data["signed_in"] is False
    assert data["publisher"].startswith("Anthropic")
    # Claude Code has two account types; Codex has none to choose.
    assert [m["value"] for m in data["modes"]] == ["subscription", "console"]


def test_the_setup_route_says_why_it_cannot_install_here(env, monkeypatch):
    client, conn, _settings = env
    enable_cli(conn)
    as_user(client, ADMIN)
    data = client.get(ROUTE + "/codex/setup").json()
    # On the dev machine (Windows) this is False with a sentence; in the
    # container it is True. Either way the two fields agree.
    assert data["supported"] is (data["unsupported_detail"] == "")


def test_the_install_status_route_answers_the_installed_record(env):
    client, conn, settings = env
    enable_cli(conn)
    as_user(client, ADMIN)
    version_dir = cli_tools.tool_root(settings, "claude_code") / "2.1.234"
    version_dir.mkdir(parents=True)
    (version_dir / "claude").write_text("x", encoding="utf-8")
    cli_tools._finish_install(settings, "claude_code", version="2.1.234", rel="claude",
                              sha="c" * 64, size=3, url="https://x",
                              checksum_source="publisher_manifest")
    data = client.get(ROUTE + "/claude_code/install-status").json()
    assert data["installed"] is True
    assert data["installed_version"] == "2.1.234"
    assert data["state"] == "done"
    assert data["checksum_source"] == "publisher_manifest"


def test_signing_in_before_installing_is_a_400_with_a_sentence(env):
    client, conn, _settings = env
    enable_cli(conn)
    as_user(client, ADMIN)
    resp = client.post(ROUTE + "/claude_code/signin", json={"mode": "subscription"})
    assert resp.status_code == 400
    assert "not installed" in resp.json()["detail"]


def test_a_code_with_no_session_is_a_400(env):
    client, conn, _settings = env
    enable_cli(conn)
    as_user(client, ADMIN)
    resp = client.post(ROUTE + "/claude_code/signin/code", json={"code": "1234"})
    assert resp.status_code == 400
    assert "no sign-in" in resp.json()["detail"]


def test_signing_out_deletes_the_token_even_with_no_binary(env):
    client, conn, settings = env
    enable_cli(conn)
    as_user(client, ADMIN)
    cli_tools.secrets_boot.write_secret_file(
        cli_tools.token_path(settings, "claude_code"), "sk-ant-oat01-TOKEN")
    resp = client.delete(ROUTE + "/claude_code/signin")
    assert resp.status_code == 200
    assert not cli_tools.token_path(settings, "claude_code").exists()
    assert "sk-ant-oat01-TOKEN" not in resp.text


def test_the_provider_row_carries_what_the_button_needs(env, monkeypatch):
    client, conn, settings = env
    enable_cli(conn)
    as_user(client, ADMIN)
    monkeypatch.setattr(ai_providers, "_run",
                        lambda argv, stdin, timeout, env_=None, **kw: None)
    monkeypatch.setattr(ai_providers.shutil, "which", lambda b: None)
    rows = {r["name"]: r for r in client.get(ROUTE).json()["providers"]}
    row = rows["claude_code"]
    assert row["installed_by_wizard"] is False
    assert row["signin_state"] == "idle"
    assert "installable" in row
    # The old copy told an admin to go and find a shell. The owner's answer to
    # that (2026-08-18) is the reason this feature exists.
    assert "SET UP" in row["detail"]


def test_a_disabled_site_still_touches_nothing(env, monkeypatch):
    client, _conn, settings = env
    as_user(client, ADMIN)
    ran = []
    monkeypatch.setattr(ai_providers, "_run", lambda *a, **kw: ran.append(a) or None)
    rows = {r["name"]: r for r in client.get(ROUTE).json()["providers"]}
    assert rows["claude_code"]["status"] == "disabled_by_site"
    assert ran == []
    assert not cli_tools.tools_root(settings).exists()


# ---------------------------------------------- the Test button sees the wizard

def test_the_test_route_sees_the_wizard_install_and_does_not_poison_the_cache(env, monkeypatch):
    """Owner, 2026-08-18, a minute after a successful sign-in: [ TEST ] said
    "not installed: no `claude` on this container's PATH", the row flipped
    to the same, and the downloader fell back to the next provider. The
    Test route probed WITHOUT settings, so it could not see
    <data>/tools/claude-code/current -- and a forced probe is cached, so its
    blind answer became everyone's answer."""
    from ccsync_dashboard import ai_providers, cli_tools

    client, conn, settings = env
    name = cli_tools.CLAUDE_CODE
    ai_providers.reset_probe_cache()
    version_dir = cli_tools.tool_root(settings, name) / "2.1.234"
    version_dir.mkdir(parents=True)
    (version_dir / "claude").write_text("#!/bin/true\n", encoding="utf-8")
    cli_tools._finish_install(settings, name, version="2.1.234", rel="claude",
                              sha="a" * 64, size=12, url="https://x/claude",
                              checksum_source="publisher_manifest")
    monkeypatch.setattr(ai_providers.shutil, "which", lambda *_a, **_k: None)

    calls = []

    class _Proc:
        def __init__(self, out):
            self.returncode = 0
            self.stdout = out
            self.stderr = ""

    def fake_run(argv, stdin, timeout, env=None):
        calls.append(list(argv))
        return _Proc("2.1.234 (Claude Code)\n" if "--version" in argv else "ok")

    monkeypatch.setattr(ai_providers, "_run", fake_run)
    monkeypatch.setattr(ai_providers, "cli_enabled", lambda *_a, **_k: True)

    result = ai_providers.test_provider(conn, settings, name)
    assert result["ok"], result
    assert calls and calls[0][0] == str(version_dir / "claude"), calls
    # and the shared cache now holds the truth, not a blind "not installed"
    cached = ai_providers.probe_cli(conn, name, settings=settings)
    assert cached["installed"] and cached["path"] == str(version_dir / "claude")


def test_a_settings_less_probe_never_writes_not_installed_into_the_cache(env, monkeypatch):
    from ccsync_dashboard import ai_providers, cli_tools

    client, conn, settings = env
    name = cli_tools.CLAUDE_CODE
    ai_providers.reset_probe_cache()
    monkeypatch.setattr(ai_providers.shutil, "which", lambda *_a, **_k: None)
    blind = ai_providers.probe_cli(conn, name, force=True)          # no settings
    assert not blind["installed"]
    assert ai_providers._cached_probe(name) is None, "a blind answer was cached"
