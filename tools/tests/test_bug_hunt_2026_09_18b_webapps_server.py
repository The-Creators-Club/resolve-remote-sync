"""The 2026-09-18b hunt, mediums wave, webapps-server's tools half (CR-301).

server-tools-1 (release_macos.sh cancelled the caller's CCSYNC_REQUIRE_FFMPEG)
and server-tools-3 (gen_notices decoded pip-licenses by the console codec).

Stdlib only, like the rest of this suite; run with the dashboard venv.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import gen_notices                                     # noqa: E402

MAC = (ROOT / "tools" / "release_macos.sh").read_text(encoding="utf-8")


# ------------------------------------------------------------ server-tools-1

def _ffmpeg_block() -> str:
    """The lines that decide REQUIRE_FFMPEG, extracted by their surroundings
    rather than by the fixed text, so this runs against the unfixed script
    too."""
    block = MAC[MAC.index("# tests-1"):]
    block = block[:block.index('if [ "$DRY_RUN" = 1 ]')]
    # Comments only (both versions carry several, and a backtick inside one is
    # harmless to bash but not to a naive slice of the file).
    return "\n".join(line for line in block.splitlines()
                     if not line.strip().startswith("#"))


def _require_value(env_value, ffmpeg_present: bool) -> str:
    """Run the real block under bash with have_cmd stubbed, and report what
    CCSYNC_REQUIRE_FFMPEG the pytest line would carry."""
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("no bash on PATH: the text assertions below still hold")
    stub = "have_cmd() { return %d; }\n" % (0 if ffmpeg_present else 1)
    script = stub + _ffmpeg_block() + '\nprintf "[%s]" "$REQUIRE_FFMPEG"\n'
    env = {"PATH": "/usr/bin:/bin"}
    if env_value is not None:
        env["CCSYNC_REQUIRE_FFMPEG"] = env_value
    proc = subprocess.run([bash, "-c", script], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_the_caller_wins_when_ffmpeg_is_not_on_path():
    """CI sets CCSYNC_REQUIRE_FFMPEG=1 on the very step that runs this script,
    to turn a missing binary into a failed release. The script used to export
    the empty string over it and publish a build whose twenty media-job tests
    had silently skipped."""
    assert _require_value("1", ffmpeg_present=False) == "[1]"


def test_the_probe_still_fills_a_blank():
    assert _require_value(None, ffmpeg_present=True) == "[1]"
    assert _require_value(None, ffmpeg_present=False) == "[]"


def test_the_script_reads_the_inherited_value_at_all():
    assert "${CCSYNC_REQUIRE_FFMPEG:-}" in _ffmpeg_block()


def test_an_asked_for_but_absent_ffmpeg_is_said_out_loud():
    block = MAC[MAC.index("have_cmd ffmpeg"):]
    block = block[:block.index("companion tests passed")]
    assert "was set by the caller" in block
    # Still never a `fail` for the absence itself: the suite's own refusal is
    # what the caller asked for.
    assert 'fail "no ffmpeg' not in block


# ------------------------------------------------------------ server-tools-3

CJK_ROW = [{"Name": "somepkg", "Version": "1.0", "License": "MIT",
            "Author": "母子", "URL": "https://example.invalid"}]


class _FakePipe:
    """subprocess.run's decoding, faithfully: bytes on the wire, decoded by
    whatever `encoding=` the caller passed, or by the console codec when it
    passed none. cp1252 stands in for `locale.getpreferredencoding(False)` so
    the test means the same thing on every rig."""

    def __init__(self, payload: bytes):
        self.payload = payload

    def __call__(self, argv, **kw):
        encoding = kw.get("encoding") or "cp1252"
        errors = kw.get("errors") or "strict"
        out = self.payload.decode(encoding, errors)
        return subprocess.CompletedProcess(argv, 0, out, "")


def test_pip_licenses_output_is_decoded_as_utf8(monkeypatch):
    payload = json.dumps(CJK_ROW, ensure_ascii=False).encode("utf-8")
    monkeypatch.setattr(gen_notices.subprocess, "run", _FakePipe(payload))
    rows = gen_notices.run_piplicenses(Path("python"))
    assert rows[0]["Author"] == "母子"


def test_a_decode_failure_is_a_warning_not_a_traceback(monkeypatch):
    """UnicodeDecodeError is a ValueError and neither a RuntimeError nor a
    JSONDecodeError, so collect()'s except used to let it escape main() and
    the notices file could not be regenerated at all."""
    def boom(python):
        raise UnicodeDecodeError("charmap", b"\x8d", 0, 1, "undefined")

    monkeypatch.setattr(gen_notices, "run_piplicenses", boom)
    monkeypatch.setattr(gen_notices, "venv_python", lambda venv: Path(sys.executable))
    per_component, warnings = gen_notices.collect()
    assert per_component == {}
    assert warnings and any("pip-licenses failed" in w for w in warnings)


def test_no_tool_reads_a_subprocess_by_the_console_codec():
    """A hand-written list of files is how server-tools-3 survived the pass
    that fixed five other sites: scan instead."""
    offenders = []
    for path in sorted((ROOT / "tools").glob("*.py")):
        src = path.read_text(encoding="utf-8")
        for chunk in src.split("subprocess.run(")[1:]:
            call = chunk[:chunk.index(")")] if ")" in chunk else chunk
            if "text=True" in call and "encoding=" not in call:
                offenders.append(f"{path.name}: {call.strip()[:80]}")
    assert not offenders, offenders
