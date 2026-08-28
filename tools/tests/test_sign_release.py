r"""Unit tests for the release-signing tools (COMMERCIAL_READINESS.md item 4,
2026-08-17).

Run them with the dashboard venv, from this directory's parent:

    cd tools
    ..\dashboard\.venv\Scripts\python.exe -m pytest tests -q

They never touch the operator's real key: every test points
CCSYNC_RELEASE_KEY at a tmp_path file.
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(REPO / "companion" / "src"))

import release_key as release_key_mod  # noqa: E402
import sign_release  # noqa: E402
from ccsync_companion import ed25519, release_pubkey  # noqa: E402


@pytest.fixture
def key(tmp_path, monkeypatch):
    path = tmp_path / "release.key"
    monkeypatch.setenv("CCSYNC_RELEASE_KEY", str(path))
    assert release_key_mod.main(["new"]) == 0
    return path


@pytest.fixture
def artifact(tmp_path):
    path = tmp_path / "ccsync-companion.exe"
    path.write_bytes(b"MZ" + b"pretend-exe" * 100)
    return path


def _run(argv):
    """sign_release.main, returning the parsed JSON it printed."""
    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert sign_release.main(argv) == 0
    return json.loads(buf.getvalue())


def test_new_writes_a_32_byte_seed_and_refuses_to_clobber(tmp_path, monkeypatch, capsys):
    path = tmp_path / "release.key"
    monkeypatch.setenv("CCSYNC_RELEASE_KEY", str(path))
    assert release_key_mod.main(["new"]) == 0
    seed = release_key_mod.read_secret(path)
    assert len(seed) == 32

    # A second `new` must NOT silently orphan every build the fleet was
    # offered -- losing the key is unrecoverable without reinstalling.
    assert release_key_mod.main(["new"]) == 1
    assert release_key_mod.read_secret(path) == seed
    assert "NOT overwriting" in capsys.readouterr().out


def test_new_force_keeps_the_superseded_key(tmp_path, monkeypatch):
    path = tmp_path / "release.key"
    monkeypatch.setenv("CCSYNC_RELEASE_KEY", str(path))
    release_key_mod.main(["new"])
    first = release_key_mod.read_secret(path)
    release_key_mod.main(["new", "--force"])
    assert release_key_mod.read_secret(path) != first
    assert release_key_mod.read_secret(path.with_suffix(".key.superseded")) == first


def test_a_missing_key_says_how_to_make_one(tmp_path):
    with pytest.raises(SystemExit) as exc:
        release_key_mod.read_secret(tmp_path / "nope.key")
    assert "release_key.py new" in str(exc.value)


def test_bake_rewrites_the_trusted_list(tmp_path, key):
    target = tmp_path / "release_pubkey.py"
    target.write_text(
        'RELEASE_PUBKEYS: tuple[str, ...] = (\n    "OLDKEY" + "x" * 40,\n)\n',
        encoding="utf-8",
    )
    assert release_key_mod.main(["bake", "--target", str(target)]) == 0
    pub = base64.b64encode(
        ed25519.public_key(release_key_mod.read_secret(key))
    ).decode("ascii")
    assert f'"{pub}"' in target.read_text(encoding="utf-8")
    assert "OLDKEY" not in target.read_text(encoding="utf-8")


def test_bake_add_keeps_the_old_key_for_a_rotation(tmp_path, key):
    target = tmp_path / "release_pubkey.py"
    old = base64.b64encode(ed25519.public_key(bytes(range(32)))).decode("ascii")
    target.write_text(
        f'RELEASE_PUBKEYS: tuple[str, ...] = (\n    "{old}",\n)\n', encoding="utf-8"
    )
    assert release_key_mod.main(["bake", "--add", "--target", str(target)]) == 0
    text = target.read_text(encoding="utf-8")
    assert old in text
    pub = base64.b64encode(
        ed25519.public_key(release_key_mod.read_secret(key))
    ).decode("ascii")
    assert pub in text


def test_the_repo_bakes_the_key_the_signer_uses():
    """The companion in this tree must trust whatever tools/sign_release.py
    would sign with -- otherwise every editor refuses the next ship, and
    nothing before the fleet notices says so."""
    default = release_key_mod.key_path()
    if not default.exists():
        pytest.skip("no release key on this machine (tools/release_key.py new)")
    pub = base64.b64encode(
        ed25519.public_key(release_key_mod.read_secret(default))
    ).decode("ascii")
    assert pub in release_pubkey.RELEASE_PUBKEYS, (
        "companion/src/ccsync_companion/release_pubkey.py does not trust the key "
        "at " + str(default) + " -- run: python tools/release_key.py bake"
    )


def test_a_signed_record_verifies_and_names_the_file_the_server_will_choose(key, artifact):
    out = _run(["--artifact", str(artifact), "--kind", "companion",
                "--platform", "windows", "--version", "0.7.12",
                "--min-version", "0.7.12"])
    assert out["filename"] == "ccsync-companion-0.7.12.exe"
    assert out["size_bytes"] == artifact.stat().st_size
    ok, detail = release_pubkey.verify_record(
        out, out["signature"],
        pubkeys=[base64.b64encode(
            ed25519.public_key(release_key_mod.read_secret(key))).decode("ascii")],
    )
    assert ok and detail == out["pubkey_id"]


@pytest.mark.parametrize("kind, platform, expected", [
    ("companion", "windows", "ccsync-companion-1.0.0.exe"),
    ("companion", "macos", "ccsync-companion-1.0.0"),
    ("onboard", "windows", "ccsync-onboard-1.0.0.exe"),
])
def test_the_filename_rule_matches_the_dashboards(kind, platform, expected):
    assert sign_release.package_filename(kind, platform, "1.0.0") == expected


def test_a_zip_macos_onboard_is_named_zip_and_a_script_sh():
    assert sign_release.package_filename(
        "onboard", "macos", "1.0.0", head=b"PK\x03\x04") == "ccsync-onboard-1.0.0.zip"
    assert sign_release.package_filename(
        "onboard", "macos", "1.0.0", head=b"#!/b") == "ccsync-onboard-1.0.0.sh"


def test_the_query_suffix_url_encodes_base64(key, artifact):
    """A raw `+` in a signature becomes a SPACE in a query string, and the
    publish then fails with an opaque 400 halfway through a ship."""
    out = _run(["--artifact", str(artifact), "--kind", "companion",
                "--platform", "windows", "--version", "0.7.12"])
    assert "+" not in out["query"].split("&signature=")[1].split("&")[0]
    assert out["query"].startswith("&signature=")
    assert "&min_version=0.0.0" in out["query"]


def test_signing_a_different_file_changes_the_signature(key, artifact, tmp_path):
    a = _run(["--artifact", str(artifact), "--kind", "companion",
              "--platform", "windows", "--version", "0.7.12",
              "--published-at", "2026-08-17T00:00:00Z"])
    other = tmp_path / "other.exe"
    other.write_bytes(b"MZ-something-else")
    b = _run(["--artifact", str(other), "--kind", "companion",
              "--platform", "windows", "--version", "0.7.12",
              "--published-at", "2026-08-17T00:00:00Z"])
    assert a["signature"] != b["signature"]


def test_an_empty_artifact_is_refused(key, tmp_path):
    empty = tmp_path / "empty.exe"
    empty.write_bytes(b"")
    with pytest.raises(SystemExit):
        sign_release.main(["--artifact", str(empty), "--kind", "companion",
                           "--platform", "windows", "--version", "0.7.12"])


def test_an_unrankable_min_version_is_refused(key, artifact):
    with pytest.raises(SystemExit):
        sign_release.main(["--artifact", str(artifact), "--kind", "companion",
                           "--platform", "windows", "--version", "0.7.12",
                           "--min-version", "nightly"])


def test_signed_binary_is_part_of_the_record(key, artifact):
    plain = _run(["--artifact", str(artifact), "--kind", "companion",
                  "--platform", "windows", "--version", "0.7.12",
                  "--published-at", "2026-08-17T00:00:00Z"])
    signed = _run(["--artifact", str(artifact), "--kind", "companion",
                   "--platform", "windows", "--version", "0.7.12",
                   "--published-at", "2026-08-17T00:00:00Z", "--signed-binary"])
    assert plain["signed_binary"] is False and signed["signed_binary"] is True
    assert plain["signature"] != signed["signature"]


def test_the_cli_runs_as_a_script(key, artifact):
    """The build scripts shell out to it -- an import-time break must not be
    something only the test suite's sys.path hides."""
    proc = subprocess.run(
        [sys.executable, str(TOOLS / "sign_release.py"),
         "--artifact", str(artifact), "--kind", "companion",
         "--platform", "windows", "--version", "0.7.12"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["filename"] == "ccsync-companion-0.7.12.exe"


class TestTheFloorMayNotExceedTheBuild:
    """CR-52 / CR-67 item 3 (2026-08-21). `--min-version 0.9.54` for a 0.9.44
    build signs perfectly and is then refused by every machine that sees it:
    the companion raises its monotonic floor on RECEIPT, so the offer, every
    earlier build and the corrected republish all fall below it. The dashboard
    (release_trust.min_version_exceeds_version) and the companion
    (upgrade._min_version_above_own) both refuse such a record now. The
    signing rig is the cheapest place of the three, because here it is a
    retype rather than a visit to every editor's machine."""

    def test_a_floor_above_the_version_is_refused(self, key, artifact):
        with pytest.raises(SystemExit) as excinfo:
            sign_release.main([
                "--artifact", str(artifact), "--kind", "companion",
                "--platform", "windows", "--version", "0.9.44",
                "--min-version", "0.9.54"])
        message = str(excinfo.value)
        assert "0.9.54" in message and "0.9.44" in message
        assert "CR-52" in message

    def test_the_refusal_happens_before_the_key_is_touched(self, tmp_path, artifact, monkeypatch):
        """No key file at all: the check must still fire, which is what makes
        it usable on a rig where the key lives somewhere else."""
        monkeypatch.setenv("CCSYNC_RELEASE_KEY", str(tmp_path / "absent.key"))
        with pytest.raises(SystemExit) as excinfo:
            sign_release.main([
                "--artifact", str(artifact), "--kind", "companion",
                "--platform", "windows", "--version", "0.9.44",
                "--min-version", "0.9.54"])
        assert "ABOVE" in str(excinfo.value)

    def test_a_floor_equal_to_the_version_is_the_normal_case(self, key, artifact):
        record = _run(["--artifact", str(artifact), "--kind", "companion",
                       "--platform", "windows", "--version", "0.9.44",
                       "--min-version", "0.9.44"])
        assert record["min_version"] == "0.9.44"

    def test_two_digit_minors_compare_as_numbers(self, key, artifact):
        """After 0.9.9 comes 0.10.0 (owner's rule 2026-08-18). A string
        compare would refuse this good record and accept the bad one below."""
        record = _run(["--artifact", str(artifact), "--kind", "companion",
                       "--platform", "windows", "--version", "0.10.0",
                       "--min-version", "0.9.44"])
        assert record["version"] == "0.10.0"
        with pytest.raises(SystemExit):
            sign_release.main(["--artifact", str(artifact), "--kind", "companion",
                               "--platform", "windows", "--version", "0.9.9",
                               "--min-version", "0.10.0"])

    def test_an_unrankable_version_is_left_to_the_other_checks(self, key, artifact):
        """A `+dirty` version cannot be ranked, so this check says nothing
        about it: `valid_min_version` on the dashboard owns "is this a version
        at all", and two refusals for one fault would name the wrong one."""
        assert sign_release.min_version_exceeds_version("0.9.44+dirty", "0.9.54") is False
        assert sign_release.min_version_exceeds_version("0.9.44", "") is False

    def test_the_comparison_matches_the_dashboards(self):
        """The rule is written out in three places that cannot import each
        other (tools, the container, the frozen companion). Pin them together
        on the cases that matter, so a change in one shows up as a failure
        rather than as a record one side accepts and another refuses."""
        cases = [
            ("0.9.44", "0.9.54", True),
            ("0.9.44", "0.9.44", False),
            ("0.9.44", "0.9.40", False),
            ("0.10.0", "0.9.99", False),
            ("0.9.9", "0.10.0", True),
            ("0.9.44+dirty", "0.9.54", False),
            ("0.9.44", "nightly", False),
            ("", "0.9.1", False),
        ]
        for version, min_version, expected in cases:
            assert sign_release.min_version_exceeds_version(version, min_version) is expected, (
                version, min_version)
        try:
            sys.path.insert(0, str(REPO / "dashboard" / "src"))
            from ccsync_dashboard import release_trust  # noqa: PLC0415
        except Exception:  # pragma: no cover - the dashboard tree may be absent
            pytest.skip("dashboard source not importable from here")
        for version, min_version, expected in cases:
            assert release_trust.min_version_exceeds_version(version, min_version) is expected, (
                version, min_version)


# --- REL-4 / REL-16 / REL-13 (resilience sweep 2026-08-28) ------------------
#
# Three facts the record could not carry: the dashboard version a companion
# needs ("deploy the dashboard before the companions", stated in four docs and
# checked in no code), the architecture it was built for (an Intel Mac was
# offered CI's arm64 binary), and which commit it came from.


def _pub_of(key_path) -> str:
    return base64.b64encode(
        ed25519.public_key(release_key_mod.read_secret(key_path))).decode("ascii")


def _optional(kind):
    return getattr(release_pubkey, "OPTIONAL_KIND_EXTRA_FIELDS", {}).get(kind, ())


def test_an_optional_extra_is_omitted_when_blank(key, artifact):
    """Blank must read as ABSENT: a record with arch="" canonicalises
    differently from one published before the field existed, and every one of
    those has to keep verifying."""
    out = _run(["--artifact", str(artifact), "--kind", "companion",
                "--platform", "windows", "--version", "0.9.55"])
    assert "arch" not in out
    assert "requires_dashboard" not in out
    ok, detail = release_pubkey.verify_record(out, out["signature"],
                                              pubkeys=[_pub_of(key)])
    assert ok, detail


@pytest.mark.skipif(not _optional("companion"),
                    reason="this build's record carries no optional companion extras")
def test_the_declared_values_are_inside_the_signature(key, artifact):
    out = _run(["--artifact", str(artifact), "--kind", "companion",
                "--platform", "windows", "--version", "0.9.55",
                "--emit-kind-extras", "--requires-dashboard", "0.7.17", "--arch", "x86_64"])
    assert out["requires_dashboard"] == "0.7.17"
    assert out["arch"] == "x86_64"
    ok, detail = release_pubkey.verify_record(out, out["signature"],
                                              pubkeys=[_pub_of(key)])
    assert ok, detail
    # Tampering with either one breaks the signature, which is the whole point
    # of signing them rather than sending them beside the record.
    tampered = dict(out)
    tampered["requires_dashboard"] = "0.0.1"
    ok, _ = release_pubkey.verify_record(tampered, out["signature"],
                                         pubkeys=[_pub_of(key)])
    assert not ok


@pytest.mark.skipif(not _optional("companion"),
                    reason="this build's record carries no optional companion extras")
def test_the_signed_extras_ride_in_the_query_the_caller_puts_on_the_put(key, artifact):
    out = _run(["--artifact", str(artifact), "--kind", "companion",
                "--platform", "windows", "--version", "0.9.55",
                "--emit-kind-extras", "--requires-dashboard", "0.7.17", "--arch", "arm64",
                "--git-sha", "c245f50", "--git-dirty", "1"])
    assert "requires_dashboard=0.7.17" in out["query"]
    assert "arch=arm64" in out["query"]
    assert "git_sha=c245f50" in out["query"]
    assert "git_dirty=1" in out["query"]


def test_a_requires_dashboard_nothing_signs_is_refused(key, artifact, monkeypatch):
    """Dropping it silently leaves an ordering rule that exists only in the
    operator's head."""
    monkeypatch.setattr(release_pubkey, "OPTIONAL_KIND_EXTRA_FIELDS", {}, raising=False)
    with pytest.raises(SystemExit) as exc:
        sign_release.main(["--artifact", str(artifact), "--kind", "companion",
                           "--platform", "windows", "--version", "0.9.55",
                           "--emit-kind-extras", "--requires-dashboard", "0.7.17"])
    assert "does not cover" in str(exc.value)


def test_an_arch_nothing_signs_degrades_to_offer_it_to_everyone(key, artifact, monkeypatch, capsys):
    """The opposite direction on purpose: an absent arch means what it has
    always meant, and refusing would make the build unpublishable."""
    monkeypatch.setattr(release_pubkey, "OPTIONAL_KIND_EXTRA_FIELDS", {}, raising=False)
    assert sign_release.main(["--artifact", str(artifact), "--kind", "companion",
                              "--platform", "windows", "--version", "0.9.55",
                              "--emit-kind-extras", "--arch", "arm64"]) == 0
    assert "offered to every machine on that platform" in capsys.readouterr().err


def test_a_requires_dashboard_that_cannot_be_ranked_is_refused(key, artifact):
    with pytest.raises(SystemExit) as exc:
        sign_release.main(["--artifact", str(artifact), "--kind", "companion",
                           "--platform", "windows", "--version", "0.9.55",
                           "--emit-kind-extras", "--requires-dashboard", "0.7.17-rc1"])
    assert "dotted-numeric" in str(exc.value)


def test_the_extras_are_dropped_loudly_unless_emission_is_opted_in(key, artifact, capsys):
    """OVERLAP CONSTRAINT (2026-08-28): a record carrying requires_dashboard
    or arch is refused by every companion older than 0.9.55, with no OTA
    recovery, so signing them in is opt-in (--emit-kind-extras). Without
    the flag both are dropped and stderr says why."""
    out = _run(["--artifact", str(artifact), "--kind", "companion",
                "--platform", "windows", "--version", "0.9.55",
                "--requires-dashboard", "0.7.17", "--arch", "x86_64"])
    err = capsys.readouterr().err
    assert "--emit-kind-extras" in err
    assert not out.get("requires_dashboard")
    assert not out.get("arch")
    ok, detail = release_pubkey.verify_record(out, out["signature"],
                                              pubkeys=[_pub_of(key)])
    assert ok, detail
