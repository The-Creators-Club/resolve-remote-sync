"""The macOS publish scripts must survive a password with control bytes in it.

KNOWN_BUGS item 10, hit live 2026-08-04: `tools/release_macos.sh` and
`tools/build_onboard_macos.sh` shared a `json_escape()` that escaped backslash
and double quote only, and assembled the login body with `printf`. A password
carrying any byte < 0x20 therefore produced INVALID JSON and the dashboard
answered `422 json_invalid / "Invalid control character at 31"` -- which reads
as "wrong password" and is not. The usual source is a bracketed paste: zsh
wraps pasted text in ESC[200~ ... ESC[201~ and `read -r -s` captures the
escapes along with the password.

The fix has three layers and this file tests all three: strip the paste
wrappers, REFUSE anything still carrying a non-printable byte (stripping alone
would turn the 422 into a misleading 401), and harden `json_escape()` so the
JSON is valid whatever it is handed.

Like tests/test_rclone_stanza_rewrite.py these run the real functions out of
the real scripts, under the real `od`/`awk`/`sed` of whatever machine they run
on -- which is the only way a GNU-vs-BSD difference is visible at all (MAC-9).
The two scripts are copy-shared twins, so the first test greps the two copies
against each other the way server/tests/test_cross_component.py does with the
.stignore builders.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TOOLS = REPO_ROOT / "tools"
RELEASE_SH = TOOLS / "release_macos.sh"
ONBOARD_SH = TOOLS / "build_onboard_macos.sh"
SENTINEL_BEGIN = "# ---CCSYNC-PASSWORD-HYGIENE-BEGIN---"
SENTINEL_END = "# ---CCSYNC-PASSWORD-HYGIENE-END---"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None
    or shutil.which("awk") is None
    or shutil.which("od") is None,
    reason="needs bash, awk and od (the point of the test is the local ones)",
)

ESC = "\x1b"
PASTE_OPEN = ESC + "[200~"
PASTE_CLOSE = ESC + "[201~"

# The stubs the extracted block expects from its host script.
PRELUDE = """\
set -u
fail() { echo "FAILED: $1" >&2; exit 1; }
ADMIN_USER="owen"
DASHBOARD_URL="http://dashboard.invalid:8480"
"""


def _extract_block(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    begins = [i for i, line in enumerate(lines) if line.strip() == SENTINEL_BEGIN]
    ends = [i for i, line in enumerate(lines) if line.strip() == SENTINEL_END]
    assert len(begins) == 1 and len(ends) == 1, (
        f"{path} must contain exactly one {SENTINEL_BEGIN}/{SENTINEL_END} pair"
    )
    assert begins[0] < ends[0]
    return "\n".join(lines[begins[0]:ends[0] + 1]) + "\n"


def _run(tmp_path: Path, body: str, stdin: str = "", argv=()) -> subprocess.CompletedProcess:
    """Run `body` with the shared block in scope. The value under test arrives
    on stdin, never in argv: a Windows dev box cannot pass an ESC or a newline
    through a command line intact.

    Bytes in, bytes out, decoded here -- subprocess's text mode would translate
    the "\\n" of a test password into "\\r\\n" on Windows and the test would be
    measuring its own harness."""
    script = tmp_path / "harness.sh"
    script.write_text(
        PRELUDE + _extract_block(RELEASE_SH) + "\n" + body,
        encoding="utf-8",
        newline="\n",
    )
    raw = subprocess.run(
        ["bash", str(script), *argv],
        input=stdin.encode("utf-8"), capture_output=True, timeout=60,
    )
    return subprocess.CompletedProcess(
        raw.args, raw.returncode,
        raw.stdout.decode("utf-8", "replace"),
        raw.stderr.decode("utf-8", "replace"),
    )


# -- the two copies are one copy --------------------------------------------


def test_both_publish_scripts_carry_the_same_block_byte_for_byte():
    """They are copy-shared: release_macos.sh publishes the companion binary
    and build_onboard_macos.sh the wizard, and both log in to the same
    dashboard with the same password read the same way. A fix applied to one
    is a fix missing from the other."""
    assert _extract_block(RELEASE_SH) == _extract_block(ONBOARD_SH), (
        "tools/release_macos.sh and tools/build_onboard_macos.sh have drifted "
        f"between {SENTINEL_BEGIN} and {SENTINEL_END} -- they are copy-shared; "
        "make the change to both."
    )


def test_neither_script_still_carries_the_two_rule_escape():
    """The exact line that shipped the bug: backslash and quote only."""
    old = """json_escape() { printf '%s' "$1" | sed -e 's/\\\\/\\\\\\\\/g' -e 's/"/\\\\"/g'; }"""
    for path in (RELEASE_SH, ONBOARD_SH):
        assert old not in path.read_text(encoding="utf-8"), f"{path} still escapes only \\ and \""


def test_neither_script_reads_the_password_without_the_hygiene_wrapper():
    """A second `read -r -s DASH_PASSWORD` outside read_dashboard_password
    would be a password that skipped stripping and validation."""
    for path in (RELEASE_SH, ONBOARD_SH):
        text = path.read_text(encoding="utf-8")
        assert text.count("read -r -s DASH_PASSWORD") == 1, path
        assert "read_dashboard_password\n" in text, f"{path} never calls read_dashboard_password"


# -- json_escape: the output is always valid JSON ---------------------------

ESCAPE_BODY = 'value="$(cat)"\njson_escape "$value"\n'


def _escape(tmp_path: Path, value: str) -> str:
    result = _run(tmp_path, ESCAPE_BODY, stdin=value)
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.mark.parametrize(
    "value",
    [
        "correct horse battery staple",
        'quote " and backslash \\ and both \\"',
        "tab\there",
        "line\nbreak",
        "carriage\rreturn",
        "esc" + ESC + "ape",
        "bell\a and backspace\b and formfeed\f",
        "\x01\x02\x03\x1f\x7f",
        "unicode: paßwort éè 你好",
        "/slash/ and ~tilde~ and $dollar and `tick`",
        PASTE_OPEN + "pasted" + PASTE_CLOSE,
    ],
)
def test_escaped_values_parse_as_json_and_round_trip(tmp_path, value):
    """The whole point: whatever goes in, the login body is valid JSON and the
    server sees the bytes that were typed."""
    escaped = _escape(tmp_path, value)
    body = '{"username":"owen","password":"' + escaped + '"}'
    parsed = json.loads(body)
    assert parsed["password"] == value


def test_the_json_body_is_parseable_by_python_json_load(tmp_path):
    """Same check the bug report asks for, driven end to end through the
    shell: build the real login body and pipe it into python -c json.load."""
    value = "es" + ESC + "c\tand\nnewline \\ \" done"
    body_script = (
        'value="$(cat)"\n'
        """printf '{"username":"%s","password":"%s"}' """
        '"$(json_escape "$ADMIN_USER")" "$(json_escape "$value")"\n'
    )
    result = _run(tmp_path, body_script, stdin=value)
    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout)
    assert parsed == {"username": "owen", "password": value}


def test_control_characters_become_escapes_not_raw_bytes(tmp_path):
    escaped = _escape(tmp_path, "a\nb\tc" + ESC + "d\x7fe")
    assert "\n" not in escaped and "\t" not in escaped and ESC not in escaped
    assert "\\n" in escaped and "\\t" in escaped
    assert "\\u001b" in escaped and "\\u007f" in escaped


def test_a_utf8_password_is_not_re_encoded(tmp_path):
    """LC_ALL=C means awk emits the bytes it was handed; a re-encoding here
    would send a different password than the editor typed."""
    escaped = _escape(tmp_path, "paßwort")
    assert escaped == "paßwort"


def test_the_empty_string_escapes_to_nothing(tmp_path):
    assert _escape(tmp_path, "") == ""


# -- the release manifest, the other thing json_escape writes ---------------


def _extract_write_manifest() -> str:
    lines = RELEASE_SH.read_text(encoding="utf-8").splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("write_manifest() {")]
    assert len(starts) == 1, "release_macos.sh must define write_manifest() exactly once"
    # The body is a `cat <<JSON` heredoc whose own closing brace sits at column
    # 0, so the function ends at the first "}" AFTER the heredoc terminator.
    heredoc_end = next(i for i, line in enumerate(lines) if i > starts[0] and line == "JSON")
    end = next(i for i, line in enumerate(lines) if i > heredoc_end and line == "}")
    return "\n".join(lines[starts[0]:end + 1]) + "\n"


def test_the_release_manifest_is_valid_json_even_with_hostile_values(tmp_path):
    """dist/ccsync-release.json is read by check_deploy_drift.ps1 and by
    build_onboard_macos.sh's staleness guard. Every string in it goes through
    the same json_escape, so hardening it covers them too."""
    body = (
        'VERSION="0.5.0"\n'
        'VERSION_STAMP="0.5.0+dirty"\n'
        'ARTIFACT_ARCH="arm64"\n'
        'SHA="deadbeef"\n'
        "SIZE_BYTES=123\n"
        'BUILT_AT="2026-08-05T00:00:00Z"\n'
        'ARTIFACT_MTIME="2026-08-05T00:00:00Z"\n'
        'GIT_COMMIT="abc1234"\n'
        'GIT_DESCRIBE="$(cat)"\n'
        "GIT_DIRTY=true\n"
        "TESTS_RUN=false\n"
        # signed_binary joined the manifest with the signed upgrade channel
        # (COMMERCIAL_READINESS.md item 4, 2026-08-17); release_macos.sh runs
        # under `set -u`, so an absent one is an unbound-variable abort here.
        "SIGNED_BINARY=false\n"
        'BUILT_BY="owen@mac"\n'
        + _extract_write_manifest()
        + "write_manifest\n"
    )
    hostile = 'v0.5.0-2-g\\"branch\ttab' + ESC + "esc"
    result = _run(tmp_path, body, stdin=hostile)
    assert result.returncode == 0, result.stderr
    manifest = json.loads(result.stdout)
    assert manifest["git_describe"] == hostile
    assert manifest["version_stamp"] == "0.5.0+dirty"
    assert manifest["size_bytes"] == 123


# -- strip_bracketed_paste --------------------------------------------------

STRIP_BODY = 'value="$(cat)"\nprintf "[%s]" "$(strip_bracketed_paste "$value")"\n'


def _strip(tmp_path: Path, value: str) -> str:
    result = _run(tmp_path, STRIP_BODY, stdin=value)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("[") and result.stdout.endswith("]")
    return result.stdout[1:-1]


def test_the_paste_wrappers_are_stripped_from_both_ends(tmp_path):
    assert _strip(tmp_path, PASTE_OPEN + "hunter2" + PASTE_CLOSE) == "hunter2"


def test_a_wrapper_is_stripped_wherever_it_appears(tmp_path):
    """Pasting into a partly-typed line puts the wrapper in the middle."""
    assert _strip(tmp_path, "hun" + PASTE_OPEN + "ter" + PASTE_CLOSE + "2") == "hunter2"


def test_a_clean_password_is_returned_unchanged(tmp_path):
    for value in ("hunter2", "p@ss w0rd!", "back\\slash", 'qu"ote', "paßwort"):
        assert _strip(tmp_path, value) == value


def test_stripping_does_not_eat_other_escapes(tmp_path):
    """Only the two bracketed-paste wrappers go; anything else must survive to
    be REJECTED by name, not silently deleted."""
    assert _strip(tmp_path, "a" + ESC + "[201b") == "a" + ESC + "[201b"


# -- reject_non_printable ---------------------------------------------------

REJECT_BODY = 'value="$(cat)"\nreject_non_printable "$1" "$value"\necho ACCEPTED\n'


def _reject(tmp_path: Path, value: str, label: str = "password"):
    return _run(tmp_path, REJECT_BODY, stdin=value, argv=(label,))


def test_a_clean_password_is_accepted(tmp_path):
    for value in ("hunter2", "p@ss w0rd!", 'back\\slash and "quote"', "paßwort"):
        result = _reject(tmp_path, value)
        assert result.returncode == 0, result.stderr
        assert "ACCEPTED" in result.stdout


@pytest.mark.parametrize(
    "value,expected",
    [
        (ESC + "abc", "byte 0x1b at position 1"),
        ("ab" + ESC + "cd", "byte 0x1b at position 3"),
        ("ab\ncd", "byte 0x0a at position 3"),
        ("abc\t", "byte 0x09 at position 4"),
        ("ab\x7f", "byte 0x7f at position 3"),
        ("paßw\x01", "byte 0x01 at position 6"),  # position is in BYTES
    ],
)
def test_a_control_byte_is_refused_by_name_and_position(tmp_path, value, expected):
    result = _reject(tmp_path, value)
    assert result.returncode == 1
    assert "ACCEPTED" not in result.stdout
    assert f"the password contains a non-printable character ({expected})" in result.stderr
    assert "retype it rather than pasting" in result.stderr


def test_the_label_names_which_value_is_wrong(tmp_path):
    result = _reject(tmp_path, "al" + ESC + "ex", label="username")
    assert result.returncode == 1
    assert "the username contains a non-printable character (byte 0x1b at position 3)" in result.stderr


def test_the_first_offending_byte_is_the_one_reported(tmp_path):
    result = _reject(tmp_path, "a\x1bb\x02c")
    assert "byte 0x1b at position 2" in result.stderr


# -- read_dashboard_password: the three layers together ---------------------

READ_BODY = 'read_dashboard_password\nprintf "PASSWORD=[%s]" "$DASH_PASSWORD"\n'


def test_a_bracketed_paste_is_stripped_then_accepted(tmp_path):
    """The reported case: the editor pastes a correct password and the script
    used to send it wrapped in escapes."""
    result = _run(tmp_path, READ_BODY, stdin=PASTE_OPEN + "hunter2" + PASTE_CLOSE + "\n")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASSWORD=[hunter2]"
    assert "dashboard password for owen@http://dashboard.invalid:8480" in result.stderr


def test_a_typed_password_is_untouched(tmp_path):
    result = _run(tmp_path, READ_BODY, stdin="hunter2\n")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "PASSWORD=[hunter2]"


def test_a_password_with_a_leftover_control_byte_refuses_to_publish(tmp_path):
    """Stripping alone would send this and earn a 401 that reads as "wrong
    password" -- the same lie in a different colour."""
    result = _run(tmp_path, READ_BODY, stdin="hun" + ESC + "ter2\n")
    assert result.returncode == 1
    assert "PASSWORD=" not in result.stdout
    assert "the password contains a non-printable character (byte 0x1b at position 4)" in result.stderr


def test_a_paste_wrapper_with_nothing_in_it_is_named(tmp_path):
    result = _run(tmp_path, READ_BODY, stdin=PASTE_OPEN + PASTE_CLOSE + "\n")
    assert result.returncode == 1
    assert "no password was entered" in result.stderr
    assert "paste wrapper" in result.stderr


def test_the_username_is_checked_before_the_prompt(tmp_path):
    """It rides in the same JSON object, and it comes from argv where a paste
    can put the same bytes."""
    body = 'ADMIN_USER="al\x1bex"\n' + READ_BODY
    result = _run(tmp_path, body, stdin="hunter2\n")
    assert result.returncode == 1
    assert "the username contains a non-printable character (byte 0x1b at position 3)" in result.stderr
    assert "dashboard password for" not in result.stderr
