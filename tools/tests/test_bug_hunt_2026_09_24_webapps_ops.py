"""The 2026-09-24 hunt, tools/ half (webapps-ops group).

logic-release-1: the documented key rotation signed the "overlap" release
with the NEW key (`new --force` puts it at the path every signer reads), and
the REL-7 refusal then told the operator to pass the override. These tests
EXECUTE the runbook's own commands (read out of docs/RELEASE.md, so an edit
to the doc is an edit to the test) against a tmp key and a tmp feed, and pin
that the refusal names the key that has to sign instead of the override.
Nothing here touches the real key, the real release_pubkey.py or the network.
"""
from __future__ import annotations

import base64
import json
import re
import shlex
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parent.parent
REPO = TOOLS.parent
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(REPO / "companion" / "src"))

import publish_feed as pf  # noqa: E402
import release_key as release_key_mod  # noqa: E402
from ccsync_companion import ed25519, release_pubkey  # noqa: E402

BASE_URL = "https://releases.example.test/v1"
RELEASE_MD = REPO / "docs" / "RELEASE.md"
NEXT_KEY_IN_DOC = r"$env:USERPROFILE\.ccsync-release\release-next.key"


def _key_id(path: Path) -> str:
    secret = release_key_mod.read_secret(path)
    return release_pubkey.pubkey_id(
        base64.b64encode(ed25519.public_key(secret)).decode("ascii"))


def _rotation_section() -> str:
    text = RELEASE_MD.read_text(encoding="utf-8")
    start = text.index("### Rotating")
    return text[start:text.index("### ", start + 5)]


def _documented_key_commands() -> list[list[str]]:
    """Every `python tools\\release_key.py ...` line of the rotation's step 1,
    as argv for release_key.main."""
    out = []
    for line in _rotation_section().splitlines():
        line = line.strip()
        if line.startswith("python tools\\release_key.py"):
            rest = line[len("python tools\\release_key.py"):]
            out.append(shlex.split(rest.replace("\\", "/"), posix=True))
    return out


def _publish(feed_dir, artifact, version, *extra):
    return pf.main(["--artifact", str(artifact), "--platform", "windows",
                    "--version", version, "--min-version", "0.0.0",
                    "--feed-dir", str(feed_dir), "--base-url", BASE_URL,
                    "--make-current", *extra])


def _record(feed_dir, version):
    channel = json.loads((feed_dir / pf.CHANNEL_FILENAME).read_text())
    return [p for p in channel["packages"] if p["version"] == version][0]


@pytest.fixture
def rig(tmp_path, monkeypatch):
    """The release rig: release.key (the OLD key) at the signing path, a tmp
    copy of the companion's baked list, and v0.9.54 current on the feed."""
    ring = tmp_path / ".ccsync-release"
    ring.mkdir()
    old = ring / "release.key"
    monkeypatch.setenv("CCSYNC_RELEASE_KEY", str(old))
    assert release_key_mod.main(["new"]) == 0
    baked = tmp_path / "release_pubkey.py"
    shutil.copy(REPO / "companion" / "src" / "ccsync_companion" / "release_pubkey.py", baked)
    assert release_key_mod.main(["bake", "--target", str(baked)]) == 0
    feed = tmp_path / "feed"
    art = tmp_path / "a.exe"
    art.write_bytes(b"MZ" + b"a" * 4000)
    assert _publish(feed, art, "0.9.54", "--baked-pubkey-ids", _key_id(old)) == pf.EXIT_OK
    return {"tmp": tmp_path, "ring": ring, "old": old, "baked": baked, "feed": feed}


def _baked_ids(baked: Path) -> list[str]:
    text = baked.read_text(encoding="utf-8")
    return [release_pubkey.pubkey_id(k) for k in re.findall(r'"([A-Za-z0-9+/=]{40,})"', text)]


# ---------------------------------------------------------------- logic-release-1

def test_the_documented_rotation_ships_the_overlap_without_an_override(rig, capsys):
    """Step 1 run exactly as written: the overlap build is signed by the OLD
    key and publishes with no --allow-key-rotation, then step 3's switch
    signs the next one with the new key, again with no override."""
    commands = _documented_key_commands()
    assert commands, "the rotation section lists no release_key.py commands"
    next_key = rig["ring"] / "release-next.key"
    old_id = _key_id(rig["old"])
    for argv in commands:
        argv = [str(next_key) if a == NEXT_KEY_IN_DOC.replace("\\", "/") else a
                for a in argv]
        assert "--force" not in argv, f"the rotation must not overwrite the signing key: {argv}"
        if "backup" in argv:
            argv = argv[:argv.index("--to")] + ["--to", str(rig["tmp"] / "offline.key")]
        if "bake" in argv:
            argv = argv + ["--target", str(rig["baked"])]
        assert release_key_mod.main(argv) == 0, argv
    assert next_key.exists(), "step 1 did not create the side key"
    assert _key_id(rig["old"]) == old_id, "step 1 replaced the signing key"
    new_id = _key_id(next_key)
    ids = _baked_ids(rig["baked"])
    assert set(ids) == {old_id, new_id}, ids

    overlap = rig["tmp"] / "b.exe"
    overlap.write_bytes(b"MZ" + b"b" * 4000)
    assert _publish(rig["feed"], overlap, "0.9.55",
                    "--baked-pubkey-ids", ",".join(ids)) == pf.EXIT_OK, \
        capsys.readouterr().err
    assert _record(rig["feed"], "0.9.55")["pubkey_id"] == old_id

    # Step 3: the switch, once the fleet runs the overlap build.
    rig["old"].replace(rig["ring"] / "release.key.superseded")
    next_key.replace(rig["old"])
    after = rig["tmp"] / "c.exe"
    after.write_bytes(b"MZ" + b"c" * 4000)
    assert _publish(rig["feed"], after, "0.9.56",
                    "--baked-pubkey-ids", ",".join(ids)) == pf.EXIT_OK, \
        capsys.readouterr().err
    assert _record(rig["feed"], "0.9.56")["pubkey_id"] == new_id


def test_an_overlap_signed_by_the_new_key_is_refused_toward_the_old_key(rig, capsys):
    """HEAD's step 1 (`new --force` + `bake --add`): the refusal used to end
    "Pass --allow-key-rotation if this is that deliberate step", which the
    operator shipping what they believe is the overlap build then does."""
    old_id = _key_id(rig["old"])
    assert release_key_mod.main(["new", "--force"]) == 0
    assert "THE NEW KEY NOW SIGNS EVERYTHING" in capsys.readouterr().out
    new_id = _key_id(rig["old"])
    assert release_key_mod.main(["bake", "--add", "--target", str(rig["baked"])]) == 0
    capsys.readouterr()

    art = rig["tmp"] / "b.exe"
    art.write_bytes(b"MZ" + b"b" * 4000)
    rc = _publish(rig["feed"], art, "0.9.55", "--baked-pubkey-ids", f"{new_id},{old_id}")
    assert rc == pf.EXIT_USAGE
    err = capsys.readouterr().err
    assert "WILL REFUSE THIS BUILD" in err
    assert "SIGNED WITH THE OLD KEY" in err and old_id in err, err
    assert "if this is that deliberate step" not in err, err


def test_a_build_that_does_not_bake_the_old_key_is_sent_to_the_procedure(
        rig, capsys, monkeypatch):
    other = rig["tmp"] / "other.key"
    assert release_key_mod.main(["--path", str(other), "new"]) == 0
    capsys.readouterr()
    monkeypatch.setenv("CCSYNC_RELEASE_KEY", str(other))
    art = rig["tmp"] / "b.exe"
    art.write_bytes(b"MZ" + b"b" * 4000)
    rc = _publish(rig["feed"], art, "0.9.55", "--baked-pubkey-ids", _key_id(other))
    assert rc == pf.EXIT_USAGE
    err = capsys.readouterr().err
    assert "Rotating" in err and "signed with the OLD" in err, err
    assert "does not perform a rotation" in err, err


def test_the_runbook_no_longer_starts_a_rotation_with_new_force():
    section = _rotation_section()
    assert "1. `python tools\\release_key.py new --force`" not in section
    assert "release-next.key new" in section
    assert "signed by the OLD key" in section


# ------------------------------------------ logic-release-1, review round

SHIP_PS1 = TOOLS / "ship.ps1"


def _step3() -> str:
    section = _rotation_section()
    return section[section.index("\n3. "):section.index("`release_key.py new --force` is NOT")]


BUILD_PKG_PS1 = REPO / "installer" / "build_editor_package.ps1"
POWERSHELL = shutil.which("powershell") or shutil.which("pwsh")
needs_powershell = pytest.mark.skipif(
    POWERSHELL is None, reason="no PowerShell on this host")

# Round 2 review (C), 2026-09-25: the step-3 test used to model the ps1 as one
# Python equality on a record it wrote itself, so it pinned doc strings and
# would not have noticed the ps1's comparison changing. This runs the ps1's
# OWN Get-PubkeyId + Test-SigningKeyTheFleetTrusts, cut out of the file, with
# only the network call and the two console helpers stubbed.
_PS1_RUNNER = r"""
param([string]$Funcs, [string]$View, [string]$Pub, [switch]$Override)
function Write-Step { param([string]$m) Write-Output "[pkg] $m" }
function Write-Warn2 { param([string]$m) Write-Output "[pkg] WARNING: $m" }
$script:ViewPath = $View
function Invoke-RestMethod { param($Method, $Uri, $WebSession)
    return (Get-Content -Raw -LiteralPath $script:ViewPath | ConvertFrom-Json) }
$AllowKeyRotation = [bool]$Override
. $Funcs
$id = Get-PubkeyId -Base64 $Pub
Write-Output "signing-id $id"
Test-SigningKeyTheFleetTrusts -Url "https://dash.example.test" -Session $null -SigningId $id
Write-Output "check-returned"
exit 0
"""


def _ps1_key_check(tmp: Path, record: dict, signing_key: Path, *, override=False):
    text = BUILD_PKG_PS1.read_text(encoding="utf-8")
    start = text.index("function Get-PubkeyId")
    funcs = text[start:text.index("\nif ($Publish -and", start)]
    assert "function Test-SigningKeyTheFleetTrusts" in funcs
    (tmp / "funcs.ps1").write_text(funcs, encoding="utf-8")
    (tmp / "runner.ps1").write_text(_PS1_RUNNER, encoding="utf-8")
    view = {"packages": [{"platform": "windows", "kind": "companion", "is_current": True,
                          "version": record["version"], "pubkey_id": record["pubkey_id"]}]}
    (tmp / "view.json").write_text(json.dumps(view), encoding="utf-8")
    pub = base64.b64encode(
        ed25519.public_key(release_key_mod.read_secret(signing_key))).decode("ascii")
    args = [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
            str(tmp / "runner.ps1"), "-Funcs", str(tmp / "funcs.ps1"),
            "-View", str(tmp / "view.json"), "-Pub", pub]
    if override:
        args.append("-Override")
    proc = subprocess.run(args, capture_output=True, text=True, timeout=180)
    return proc.returncode, proc.stdout + proc.stderr


@needs_powershell
def test_step3_says_pathway_a_needs_the_override_once_and_when(rig, capsys):
    """Review finding 1: build_editor_package.ps1 compares this rig's key with
    the key that SIGNED the current build (the dashboard keeps no baked
    list). After the switch the current build is the overlap build, signed by
    the OLD key, so pathway A's first new-key build IS refused. The runbook
    used to promise "REL-7 passes again without an override" there. This runs
    the ps1's own check on the real records and pins that the doc says what
    that check does."""
    old_id = _key_id(rig["old"])
    next_key = rig["ring"] / "release-next.key"
    assert release_key_mod.main(["--path", str(next_key), "new"]) == 0
    new_id = _key_id(next_key)
    # Step 1: the overlap release, signed by the OLD key, over 0.9.54 (old).
    code, out = _ps1_key_check(rig["tmp"], _record(rig["feed"], "0.9.54"), rig["old"])
    assert code == 0 and "check-returned" in out and "also signed" in out, out
    assert f"signing-id {old_id}" in out, out  # the ps1's id is pubkey_id
    art = rig["tmp"] / "b.exe"
    art.write_bytes(b"MZ" + b"b" * 4000)
    assert _publish(rig["feed"], art, "0.9.55",
                    "--baked-pubkey-ids", f"{old_id},{new_id}") == pf.EXIT_OK
    capsys.readouterr()
    overlap = _record(rig["feed"], "0.9.55")
    # Step 3, pathway A: the first new-key build meets the overlap record.
    code, out = _ps1_key_check(rig["tmp"], overlap, next_key)
    assert code == 1 and "check-returned" not in out, out
    assert "WILL REFUSE THIS BUILD" in out and f"signed with {old_id}" in out, out
    assert "Nothing was built." in out
    # ...and passes only with the override, which the doc says is this build's.
    code, out = _ps1_key_check(rig["tmp"], overlap, next_key, override=True)
    assert code == 0 and "check-returned" in out and "-AllowKeyRotation" in out, out

    step3 = _step3()
    assert "passes\n   again without an override" not in step3
    assert "without an override" not in step3.split("**Pathway A**")[1]
    assert "**Pathway A**" in step3 and "-AllowKeyRotation" in step3
    assert "IS refused" in step3
    assert "release.key.superseded pubkey" in step3
    # the general paragraph no longer says a correct rotation never trips it
    assert "a correct rotation never trips the check" not in _rotation_section()
    ship = SHIP_PS1.read_text(encoding="utf-8")
    help_text = ship[ship.index(".PARAMETER AllowKeyRotation"):ship.index(".EXAMPLE")]
    assert "does NOT perform a key" in help_text and "Rotating" in help_text


def test_new_force_on_the_signing_path_does_not_then_say_bake(rig, capsys):
    """Review finding 3: the warning was followed by "Next: ... bake" with no
    --add, i.e. the stranding step, as the next instruction."""
    assert release_key_mod.main(["new", "--force"]) == 0
    out = capsys.readouterr().out
    assert "THE NEW KEY NOW SIGNS EVERYTHING" in out
    assert "Next: python tools/release_key.py bake" not in out, out


def test_a_first_key_still_gets_the_bake_prompt(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CCSYNC_RELEASE_KEY", str(tmp_path / "release.key"))
    assert release_key_mod.main(["new"]) == 0
    assert "Next: python tools/release_key.py bake" in capsys.readouterr().out


def test_backing_up_the_side_key_keeps_the_signing_keys_record(rig, capsys):
    """Review finding 4: backup.json was one file per DIRECTORY, so step 1's
    side-key backup rewrote the signing key's record with the side key's
    id."""
    assert release_key_mod.main(["backup", "--to", str(rig["tmp"] / "old.copy")]) == 0
    old_id = _key_id(rig["old"])
    rec_old = release_key_mod.backup_record_path(rig["old"])
    assert rec_old == rig["ring"] / "backup.json"
    assert json.loads(rec_old.read_text())["pubkey_id"] == old_id

    next_key = rig["ring"] / "release-next.key"
    assert release_key_mod.main(["--path", str(next_key), "new"]) == 0
    assert release_key_mod.main(["--path", str(next_key), "backup",
                                 "--to", str(rig["tmp"] / "next.copy")]) == 0
    capsys.readouterr()
    assert json.loads(rec_old.read_text())["pubkey_id"] == old_id
    rec_next = release_key_mod.backup_record_path(next_key)
    assert rec_next != rec_old
    assert json.loads(rec_next.read_text())["pubkey_id"] == _key_id(next_key)
    # The doc's step 3 moves the records with the keys.
    assert "`release-next.key.backup.json` to `backup.json`" in _step3()


# ------------------------------------ logic-release-1, round 2 review (2026-09-25)

LOAD_SECRETS = TOOLS / "load_secrets.ps1"


def _trusted(capsys) -> list[str]:
    capsys.readouterr()
    assert release_key_mod.main(["trusted", "--quiet"]) == 0
    line = capsys.readouterr().out.strip()
    return [release_pubkey.pubkey_id(k) for k in line.split(",") if k]


def test_the_trust_list_holds_both_keys_for_the_whole_rotation(rig, capsys):
    """Review (A): load_secrets.ps1 derived DASH_RELEASE_PUBKEYS from
    release.key alone and ship.cmd writes it into the container, so each ship
    in the window redeployed the studio dashboard trusting one key - after
    the switch, not the old key the current build, the vendor channel and the
    OTA code trees are signed by. HEAD has no `trusted` (argparse exits 2)."""
    old_id = _key_id(rig["old"])
    assert _trusted(capsys) == [old_id]
    next_key = rig["ring"] / "release-next.key"
    assert release_key_mod.main(["--path", str(next_key), "new"]) == 0
    new_id = _key_id(next_key)
    assert _trusted(capsys) == [old_id, new_id]          # steps 1-2
    rig["old"].replace(rig["ring"] / "release.key.superseded")
    next_key.replace(rig["old"])
    assert _trusted(capsys) == [new_id, old_id]          # step 3 onward
    offline = rig["tmp"] / "offline"
    offline.mkdir()
    (rig["ring"] / "release.key.superseded").replace(offline / "release.key.superseded")
    assert _trusted(capsys) == [new_id]                  # step 4


def test_an_unreadable_rotation_key_refuses_rather_than_trusting_one(rig, capsys):
    (rig["ring"] / "release-next.key").write_text("not a key\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        release_key_mod.main(["trusted", "--quiet"])
    assert "release-next.key" in str(exc.value)


@needs_powershell
def test_load_secrets_exports_the_whole_trust_list(rig, tmp_path, capsys):
    """Runs load_secrets.ps1's own DASH_RELEASE_PUBKEYS block (cut out of the
    file, $PSScriptRoot pointed at tools/) against a ring holding a side key:
    the value ship.cmd deploys into the container must carry both keys."""
    next_key = rig["ring"] / "release-next.key"
    assert release_key_mod.main(["--path", str(next_key), "new"]) == 0
    capsys.readouterr()
    text = LOAD_SECRETS.read_text(encoding="utf-8")
    block = text[text.index("$keyFile = Join-Path"):text.index("\nif ($loaded.Count -eq 0)")]
    block = block.replace("$PSScriptRoot", "'" + str(TOOLS) + "'")
    runner = ("function Write-Warn2 { param([string]$m) Write-Output \"WARN $m\" }\n"
              "$loaded = @()\n" + block +
              "\nWrite-Output \"KEYS=$env:DASH_RELEASE_PUBKEYS\"\n"
              "Write-Output \"LOADED=$($loaded -join ';')\"\n")
    (tmp_path / "runner.ps1").write_text(runner, encoding="utf-8")
    env = dict(os.environ)
    env["USERPROFILE"] = str(rig["tmp"])
    env["CCSYNC_RELEASE_KEY"] = str(rig["old"])
    env.pop("DASH_RELEASE_PUBKEYS", None)
    # `python` in the block must be one that can run release_key.py.
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
    proc = subprocess.run([POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass",
                           "-File", str(tmp_path / "runner.ps1")],
                          capture_output=True, text=True, timeout=180, env=env)
    out = proc.stdout + proc.stderr
    keys = [ln for ln in out.splitlines() if ln.startswith("KEYS=")][0][5:].split(",")
    assert [release_pubkey.pubkey_id(k) for k in keys if k] == \
        [_key_id(rig["old"]), _key_id(next_key)], out
    assert "2 keys: a key rotation is under way" in out, out


def test_the_runbook_covers_the_trust_list_and_the_mac_key():
    """Review (A) and (B), tied to the code they describe."""
    section = _rotation_section()
    step2 = section[section.index("\n2. "):section.index("\n3. ")]
    assert "load_secrets.ps1" in step2 and "release_key.py trusted" in step2
    assert "never hand-set" in step2
    assert "release_key.py') trusted --quiet" in LOAD_SECRETS.read_text(encoding="utf-8")
    step3 = _step3()
    mac = step3[step3.index("**The Mac signs too"):]
    assert "release_macos.sh" in mac and "build_onboard_macos.sh" in mac
    assert "~/.ccsync-release/release.key" in mac and "NEW" in mac
    for script in ("release_macos.sh", "build_onboard_macos.sh"):
        assert "~/.ccsync-release/release.key" in (TOOLS / script).read_text(encoding="utf-8")
    step4 = section[section.index("\n4. **Drop the old key**"):]
    assert "move `release.key.superseded`" in step4
