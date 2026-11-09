"""Deploying the Footage Sorter (/sorter) -- Timeline Cards' deploy, pinned.

footage-sorter's docs/DASHBOARD-MODULE-PLAN.md, phase 3 (2026-11-09). The
sorter's code is ANOTHER REPO'S, shipped as an export of one commit to
<host-root>/sorter-web, so the properties worth pinning are the same ones
test_cards_snapshot.py pins for Cards, plus the three that are the sorter's
own:

  * only `footage_sorter/` and `public/` ship (the repo also holds a Node
    server, live data and caches, node_modules, a cloud worker...);
  * the settings JSON survives the trip through a single-quoted YAML scalar;
  * the pool is ONE bind of the whole dataset.

Everything runs against a throwaway git repository in tmp_path -- no NAS, no
network, and the real footage-sorter checkout is never read.

Run with:
    cd E:\\Projects\\Editing\\ccsync\\server
    ..\\dashboard\\.venv\\Scripts\\python.exe -m pytest tests/test_sorter_deploy.py -q
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import install_dashboard_app as ida  # noqa: E402

GIT = shutil.which("git")
needs_git = pytest.mark.skipif(GIT is None, reason="git is required")

IMAGE_TEMPLATE = ida.LOCAL_DASHBOARD_DIR / "deploy" / "compose.image.yaml"
HOST_ROOT = "/mnt/tank/apps/ccsync-dashboard"

# This studio's [footage_sorter], as the container sees it.
STUDIO = {
    "SITE_SORTER_ENABLED": True,
    "SITE_SORTER_POOL_HOST": "/mnt/tank/TheCreatorsPool",
    "SITE_SORTER_SOURCE_ROOTS": ["/pool/Temp Transfer"],
    "SITE_SORTER_DEST_ROOT": "/pool/Creators_Club/Projects",
    "SITE_SORTER_LEGACY_ID_ROOTS": {"/pool/Temp Transfer": "W:\\Temp Transfer",
                                    "/pool/Creators_Club": "P:\\"},
    "SITE_SORTER_VAULT_ROOT": "/vault/Vault/2026/FF5",
    "SITE_SORTER_POOL_GID": "",
}
STUDIO_JSON = (
    '{"sourceRoots":["/pool/Temp Transfer"],'
    '"destRoot":"/pool/Creators_Club/Projects",'
    '"stagingRoot":"/pool/Temp Transfer",'
    '"ffmpegDir":"/opt/ffmpeg",'
    '"legacyIdRoots":{"/pool/Temp Transfer":"W:\\\\Temp Transfer",'
    '"/pool/Creators_Club":"P:\\\\"},'
    '"vaultRoot":"/vault/Vault/2026/FF5"}'
)


@pytest.fixture
def studio(monkeypatch):
    for name, value in STUDIO.items():
        monkeypatch.setattr(ida, name, value)
    return STUDIO


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("SORTER_SRC", "SORTER_COMMIT", "CCSYNC_SORTER_RECORD"):
        monkeypatch.delenv(name, raising=False)


def git(repo, *args):
    proc = subprocess.run([GIT, *args], cwd=str(repo), capture_output=True, text=True)
    assert proc.returncode == 0, f"git {args} failed: {proc.stderr}"
    return proc.stdout.strip()


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_repo(tmp_path):
    """A repo shaped like footage-sorter: the checkout IS the repo root, trunk
    is `master`, and next to the two directories that ship sit all the things
    that must not -- TRACKED ones included, to prove the exclusion is an
    allow-list and not a reliance on .gitignore."""
    repo = tmp_path / "footage-sorter"
    repo.mkdir()
    git(tmp_path, "init", str(repo))
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/master")

    write(repo / "README.md", "before the module\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "before the Python port")
    before = git(repo, "rev-parse", "HEAD")

    write(repo / "footage_sorter" / "__init__.py", "")
    write(repo / "footage_sorter" / "web.py", "COMMITTED\n")
    write(repo / "public" / "index.html", "<html>committed</html>\n")
    for rel in ("server.js", "package.json", "mover.ps1", "lib/clipkey.js",
                "data/clips.json", "cache/thumbs/a.jpg", "node_modules/x/index.js",
                "test/t.js", "tests/py/test_x.py", "tools/t.py", "docs/PLAN.md",
                "cloud/ledger/src/index.js", "ingest/tray/main.js"):
        write(repo / rel, f"{rel}\n")
    write(repo / ".gitignore", "__pycache__/\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "the sorter module")
    head = git(repo, "rev-parse", "HEAD")

    # The working copy an operator actually has open.
    write(repo / "footage_sorter" / "web.py", "HALF FINISHED\n")
    write(repo / "footage_sorter" / "newmod.py", "untracked\n")
    write(repo / "footage_sorter" / "__pycache__" / "web.cpython-312.pyc", "ignored\n")
    write(repo / "lib" / "untracked.js", "not shipped anyway\n")
    return repo, before, head


def tops(tree):
    return {p.name for p in Path(tree).iterdir()}


# ---------------------------------------------------------------- the snapshot

@needs_git
def test_the_snapshot_ships_the_two_directories_and_nothing_else(tmp_path):
    repo, _before, head = make_repo(tmp_path)

    tree, info, err = ida.export_sorter_snapshot(repo, "master", dest_parent=tmp_path)
    assert err == ""
    # EXACTLY these three: the repo also holds a Node server, live data and
    # caches, node_modules, tests, tools, docs, a cloud worker and the ingest
    # tools, all of them tracked in this fixture.
    assert tops(tree) == {"footage_sorter", "public", ida.CARDS_MARKER_NAME}
    assert (tree / "footage_sorter" / "web.py").read_text(encoding="utf-8") == "COMMITTED\n"
    assert (tree / "public" / "index.html").is_file()
    # the commit, not the working copy
    assert not (tree / "footage_sorter" / "newmod.py").exists()
    assert not (tree / "footage_sorter" / "__pycache__").exists()
    assert not (tree / ".git").exists()
    assert info["commit"] == head
    assert info["subtree"] == ""


@needs_git
def test_the_marker_names_the_sorter_and_the_commit(tmp_path):
    repo, _before, head = make_repo(tmp_path)
    tree, info, err = ida.export_sorter_snapshot(repo, "master", dest_parent=tmp_path)
    assert err == ""
    raw = (tree / ida.CARDS_MARKER_NAME).read_text(encoding="utf-8")
    assert raw.startswith("# Footage Sorter, shipped by")
    parsed = ida.read_cards_marker(tree / ida.CARDS_MARKER_NAME)
    assert parsed["commit"] == head and parsed["ref"] == "master"
    assert parsed["subject"] == "the sorter module"


@needs_git
def test_sorter_commit_pins_another_commit(tmp_path, monkeypatch):
    """--sorter-commit: a commit that PREDATES the module has nothing to ship
    and is refused by name; one that has it is exported as it was."""
    repo, before, head = make_repo(tmp_path)
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "later work")
    write(repo / "footage_sorter" / "web.py", "LATER\n")
    git(repo, "commit", "-am", "even later")
    monkeypatch.setattr(ida, "SITE_SORTER_SRC", str(repo))

    args = argparse.Namespace(sorter_commit=head, sorter_src_dir="")
    tree, info, err = ida.resolve_sorter_tree(args)
    assert err == "" and info["commit"] == head
    assert (tree / "footage_sorter" / "web.py").read_text(encoding="utf-8") == "COMMITTED\n"

    # the default is the trunk: master, which is the only branch there
    tree, info, err = ida.resolve_sorter_tree(
        argparse.Namespace(sorter_commit="", sorter_src_dir=""))
    assert err == "" and info["ref"] == ida.SORTER_DEFAULT_REF == "master"
    assert (tree / "footage_sorter" / "web.py").read_text(encoding="utf-8") == "LATER\n"

    # a commit before the module has no footage_sorter/ or public/: EMPTY, refused
    tree, info, err = ida.resolve_sorter_tree(
        argparse.Namespace(sorter_commit=before, sorter_src_dir=""))
    assert tree is None and info is None and "EMPTY" in err and "/sorter" in err

    tree, info, err = ida.resolve_sorter_tree(
        argparse.Namespace(sorter_commit="no-such-branch", sorter_src_dir=""))
    assert tree is None and info is None
    # worded for the sorter: its flag, its name, never Cards'
    assert "no-such-branch" in err and "--sorter-commit" in err
    assert "Footage Sorter" in err and "cards" not in err.lower()


@needs_git
def test_an_explicit_directory_ships_its_two_directories_as_they_stand(tmp_path, monkeypatch):
    """SORTER_SRC / --sorter-src-dir keep Cards' meaning -- the working copy,
    uncommitted edits included -- for the two directories that ship. They do
    NOT ship the checkout root: that holds node_modules/, data/ and cache/."""
    repo, _before, _head = make_repo(tmp_path)
    monkeypatch.setattr(ida, "SITE_SORTER_SRC", str(repo))

    for how in ("env", "flag"):
        monkeypatch.delenv("SORTER_SRC", raising=False)
        args = argparse.Namespace(sorter_commit="", sorter_src_dir="")
        if how == "env":
            monkeypatch.setenv("SORTER_SRC", str(repo))
        else:
            args.sorter_src_dir = str(repo)
        tree, info, err = ida.resolve_sorter_tree(args)
        assert err == "" and info is None, how
        assert tops(tree) == {"footage_sorter", "public"}, how
        assert (tree / "footage_sorter" / "web.py").read_text(encoding="utf-8") == "HALF FINISHED\n"
        assert (tree / "footage_sorter" / "newmod.py").exists()
        assert not (tree / "footage_sorter" / "__pycache__").exists()


def test_a_src_that_is_not_a_checkout_ships_as_a_directory(tmp_path, monkeypatch, capsys):
    plain = tmp_path / "sorter-copy"
    write(plain / "footage_sorter" / "web.py", "x\n")
    write(plain / "public" / "index.html", "x\n")
    write(plain / "node_modules" / "big" / "x.js", "x\n")
    monkeypatch.setattr(ida, "SITE_SORTER_SRC", str(plain))
    monkeypatch.setattr(ida, "cards_repo_for",
                        lambda src, *a, **k: (None, "", f"{src} is not inside a git repository."))

    tree, info, err = ida.resolve_sorter_tree(
        argparse.Namespace(sorter_commit="", sorter_src_dir=""))
    assert err == "" and info is None
    assert tops(tree) == {"footage_sorter", "public"}
    assert "footage-sorter repository" in capsys.readouterr().err


def test_no_named_src_is_no_sorter_and_no_complaint(monkeypatch):
    monkeypatch.setattr(ida, "SITE_SORTER_SRC", "")
    assert ida.resolve_sorter_tree(
        argparse.Namespace(sorter_commit="", sorter_src_dir="")) == (None, None, "")


@needs_git
def test_the_dirty_note_is_about_the_directories_that_ship(tmp_path, capsys):
    """The repo is full of untracked files that never ship (lib/untracked.js
    here); the NOTE that "these are NOT in this deploy" must list only the
    ones that would have been."""
    repo, _before, _head = make_repo(tmp_path)
    _tree, _info, err = ida.export_sorter_snapshot(repo, "master", dest_parent=tmp_path)
    assert err == ""
    stderr = capsys.readouterr().err
    assert "newmod.py" in stderr and "web.py" in stderr
    assert "untracked.js" not in stderr


@needs_git
def test_the_deploy_record_is_kept_apart_from_cards(tmp_path, monkeypatch):
    repo, _before, head = make_repo(tmp_path)
    record = tmp_path / "state" / "sorter_deployed.json"
    monkeypatch.setenv("CCSYNC_SORTER_RECORD", str(record))
    monkeypatch.setenv("CCSYNC_CARDS_RECORD", str(tmp_path / "state" / "cards_deployed.json"))
    _tree, info, err = ida.export_sorter_snapshot(repo, "master", dest_parent=tmp_path)
    assert err == ""

    ida.record_cards_deploy(repo, info, False, "sorter")
    assert json.loads(record.read_text(encoding="utf-8"))["commit"] == head
    assert not (tmp_path / "state" / "cards_deployed.json").exists()
    assert ida.cards_deploy_record_path("sorter") == record
    # and by default it lives beside the Cards one
    monkeypatch.delenv("CCSYNC_SORTER_RECORD")
    assert ida.cards_deploy_record_path("sorter").name == "sorter_deployed.json"
    assert ida.cards_deploy_record_path().name == "cards_deployed.json"


# ----------------------------------------------------------- env block / keys

SORTER_KEYS = {"DASH_SORTER_ENABLED", "DASH_SORTER_SRC", "DASH_SORTER_DATA",
               "DASH_SORTER_CACHE", "DASH_SORTER_SETTINGS"}


def _dashboard(**kw):
    return ida.compose_config(8480, HOST_ROOT, "http://gui:8384", "k", "t",
                              **kw)["services"]["dashboard"]


def test_every_key_is_always_present_even_for_a_site_that_says_nothing():
    """test_safety's rule: the dict and both templates carry the same keys."""
    assert set(ida.sorter_env("0")) == SORTER_KEYS
    env = _dashboard()["environment"]
    assert SORTER_KEYS <= set(env)
    assert env["DASH_SORTER_ENABLED"] == "0"
    assert env["DASH_SORTER_SRC"] == ""
    assert env["DASH_SORTER_SETTINGS"] == ""
    assert env["DASH_SORTER_DATA"] == "/sorter-data"
    assert env["DASH_SORTER_CACHE"] == "/sorter-data/cache"
    for template in (ida.COMPOSE_TEMPLATE, IMAGE_TEMPLATE):
        text = template.read_text(encoding="utf-8")
        for key in SORTER_KEYS:
            assert re.search(rf"^      {key}: ", text, re.M), (template.name, key)


def test_enabled_needs_the_site_and_a_shipped_tree(monkeypatch):
    monkeypatch.setattr(ida, "SITE_SORTER_ENABLED", True)
    assert ida.sorter_enabled_for_site(True) == "1"
    assert ida.sorter_enabled_for_site(False) == "0"
    monkeypatch.setattr(ida, "SITE_SORTER_ENABLED", False)
    assert ida.sorter_enabled_for_site(True) == "0"

    env = ida.sorter_env("1")
    assert env["DASH_SORTER_ENABLED"] == "1" and env["DASH_SORTER_SRC"] == "/sorter-app"
    assert ida.sorter_env("0")["DASH_SORTER_SRC"] == ""


def test_the_settings_are_exactly_this_json(studio):
    assert ida.sorter_settings_json() == STUDIO_JSON
    parsed = json.loads(STUDIO_JSON)
    assert parsed["stagingRoot"] == parsed["sourceRoots"][0]
    assert parsed["legacyIdRoots"]["/pool/Temp Transfer"] == "W:\\Temp Transfer"
    # and the dict the TrueNAS path posts carries it raw
    assert _dashboard(sorter_enabled="1")["environment"]["DASH_SORTER_SETTINGS"] == STUDIO_JSON


def test_without_a_pool_the_settings_are_blank(studio, monkeypatch):
    """Roots under /pool mean nothing when nothing is mounted there."""
    monkeypatch.setattr(ida, "SITE_SORTER_POOL_HOST", "")
    assert ida.sorter_settings_json() == ""


def _rendered_setting_line(template):
    text = ida.render_compose_yaml(ida.compose_variables(), template=template)
    lines = [l for l in text.splitlines() if l.startswith("      DASH_SORTER_SETTINGS: ")]
    assert len(lines) == 1
    return text, lines[0].split(": ", 1)[1]


def _unquote_single(scalar):
    """YAML 1.2 single-quoted scalar, by the book: no escapes, `''` is `'`."""
    assert scalar.startswith("'") and scalar.endswith("'") and len(scalar) >= 2, scalar
    body = scalar[1:-1]
    assert "'" not in body.replace("''", ""), f"a lone quote ends the scalar early: {scalar}"
    return body.replace("''", "'")


@pytest.mark.parametrize("template", [ida.COMPOSE_TEMPLATE, IMAGE_TEMPLATE],
                         ids=["default", "image"])
def test_the_settings_round_trip_through_the_rendered_yaml(studio, template):
    """The value holds backslashes and double quotes; in a double-quoted YAML
    scalar every backslash would be an escape and TrueNAS would refuse the file
    at install. It is single-quoted, and what comes out of the parser is the
    exact JSON."""
    text, scalar = _rendered_setting_line(template)
    assert _unquote_single(scalar) == STUDIO_JSON
    assert json.loads(_unquote_single(scalar)) == json.loads(STUDIO_JSON)

    try:
        import yaml
    except ImportError:
        pytest.fail("PyYAML is a test dependency (dashboard dev extra, server/requirements.txt): "
                    "without it nothing checks that TrueNAS can parse the compose file")
    parsed = yaml.safe_load(text)["services"]["dashboard"]["environment"]
    assert parsed["DASH_SORTER_SETTINGS"] == STUDIO_JSON


def test_a_quote_and_a_dollar_in_a_folder_name_survive_the_file(studio, monkeypatch):
    """`Alex's Rushes` would end the scalar; `Cash$` would be a compose
    variable. Both are legal folder names, and the file has to carry them."""
    monkeypatch.setattr(ida, "SITE_SORTER_SOURCE_ROOTS", ["/pool/Alex's Rushes", "/pool/Cash$"])
    monkeypatch.setattr(ida, "SITE_SORTER_LEGACY_ID_ROOTS", {"/pool/Cash$": "W:\\Cash$"})
    want = ida.sorter_settings_json()
    assert json.loads(want)["sourceRoots"] == ["/pool/Alex's Rushes", "/pool/Cash$"]

    _text, scalar = _rendered_setting_line(ida.COMPOSE_TEMPLATE)
    after_yaml = _unquote_single(scalar)
    # `$$` is compose's spelling of a literal dollar: undo it as compose does
    assert after_yaml.replace("$$", "$") == want
    assert "$$" in after_yaml and "$" not in after_yaml.replace("$$", "")

    # non-ASCII names travel as JSON escapes and come back whole
    monkeypatch.setattr(ida, "SITE_SORTER_SOURCE_ROOTS", ["/pool/\u7d20\u6750"])
    assert json.loads(ida.sorter_settings_json())["sourceRoots"] == ["/pool/\u7d20\u6750"]
    assert ida.sorter_settings_json().isascii()


# ------------------------------------------------------------ volumes / groups

def test_the_code_and_data_mounts_are_unconditional():
    volumes = _dashboard()["volumes"]
    assert f"{HOST_ROOT}/sorter-web:/sorter-app:ro" in volumes
    assert f"{HOST_ROOT}/sorter-data:/sorter-data:rw" in volumes
    # no pool unless the site names one
    assert not any(":/pool" in v for v in volumes)
    assert "group_add" not in _dashboard()


def test_image_mode_keeps_the_sorter_code_mount_like_cards():
    """The image carries /app, /broll-app... as layers; it cannot carry
    another repo's tree."""
    volumes = _dashboard(mode="image")["volumes"]
    assert f"{HOST_ROOT}/sorter-web:/sorter-app:ro" in volumes
    assert f"{HOST_ROOT}/sorter-data:/sorter-data:rw" in volumes
    assert "/sorter-app" not in ida.IMAGE_MODE_CODE_MOUNTS


def test_the_pool_is_one_read_write_bind_of_the_whole_dataset(studio):
    volumes = _dashboard(sorter_enabled="1")["volumes"]
    pool = [v for v in volumes if v.split(":")[1:2] == ["/pool"]]
    assert pool == ["/mnt/tank/TheCreatorsPool:/pool:rw"]
    # ONE bind: a second bind of any part of the dataset beside it would make
    # a rename between them EXDEV. (Every root the sorter is told about is
    # under that one mount.)
    settings = json.loads(ida.sorter_settings_json())
    for path in [*settings["sourceRoots"], settings["destRoot"], *settings["legacyIdRoots"]]:
        assert path.startswith("/pool/")
    assert ida.sorter_problems() == []


def test_pool_gid_adds_the_group_once_alongside_the_cards_vault(studio, monkeypatch):
    monkeypatch.setattr(ida, "SITE_SORTER_POOL_GID", "3002")
    assert _dashboard()["group_add"] == ["3002"]
    # the Cards vault's group joins the same key; the same gid is not doubled
    monkeypatch.setattr(ida, "SITE_CARDS_VAULT_HOST", "/mnt/tank/web")
    monkeypatch.setattr(ida, "SITE_CARDS_VAULT_GID", "3000")
    assert _dashboard()["group_add"] == ["3000", "3002"]
    monkeypatch.setattr(ida, "SITE_SORTER_POOL_GID", "3000")
    assert _dashboard()["group_add"] == ["3000"]
    # a gid with no pool is nothing
    monkeypatch.setattr(ida, "SITE_SORTER_POOL_HOST", "")
    monkeypatch.setattr(ida, "SITE_CARDS_VAULT_HOST", "")
    assert "group_add" not in _dashboard()


def test_a_root_outside_the_pool_is_named_as_a_problem(studio, monkeypatch):
    monkeypatch.setattr(ida, "SITE_SORTER_SOURCE_ROOTS", ["/mnt/elsewhere/Temp"])
    problems = ida.sorter_problems()
    assert len(problems) == 1 and "/mnt/elsewhere/Temp" in problems[0] and "EXDEV" in problems[0]

    monkeypatch.setattr(ida, "SITE_SORTER_POOL_HOST", "")
    assert "pool_host" in ida.sorter_problems()[0]


def test_the_compose_file_and_the_dict_carry_the_same_sorter_volumes():
    """test_safety diffs the whole lists; this names the sorter's two."""
    for template in (ida.COMPOSE_TEMPLATE, IMAGE_TEMPLATE):
        text = ida.render_compose_yaml(ida.compose_variables(), template=template)
        assert f"- {HOST_ROOT}/sorter-web:/sorter-app:ro" in text, template.name
        assert f"- {HOST_ROOT}/sorter-data:/sorter-data:rw" in text, template.name


def test_the_synology_host_dirs_include_the_sorters():
    dirs = dict(ida.SYNOLOGY_HOST_DIRS)
    assert dirs["sorter-web"] == "code" and dirs["sorter-data"] == "private"


# ------------------------------------------------------------- the site reader

def test_the_site_reader_keeps_absolute_paths_and_backslashes(monkeypatch):
    """site_list() would turn /pool/Temp Transfer into pool/Temp Transfer."""
    fake = {"footage_sorter": {
        "source_roots": ["/pool/Temp Transfer/", "  "],
        "legacy_id_roots": {"/pool/Temp Transfer": "W:\\Temp Transfer"}}}
    monkeypatch.setattr(ida, "load_site", lambda: fake)
    assert ida._site_strings("footage_sorter", "source_roots") == ["/pool/Temp Transfer"]
    assert ida._site_string_table("footage_sorter", "legacy_id_roots") == {
        "/pool/Temp Transfer": "W:\\Temp Transfer"}
    assert ida._site_strings("footage_sorter", "nope") == []
    assert ida._site_string_table("footage_sorter", "source_roots") == {}


# ------------------------------------------------------- the cloud state mount (ledger browser)

def test_no_cloud_state_means_no_mount_and_unchanged_settings(studio):
    assert not any(":/cloud-state" in v for v in _dashboard(sorter_enabled="1")["volumes"])
    assert "cloudState" not in json.loads(ida.sorter_settings_json())
    assert ida.sorter_settings_json() == STUDIO_JSON


def test_cloud_state_is_one_read_only_mount_beside_the_pool(studio, monkeypatch):
    monkeypatch.setattr(ida, "SITE_SORTER_CLOUD_STATE", "/mnt/tank/backups/cloud")
    volumes = _dashboard(sorter_enabled="1")["volumes"]
    assert "/mnt/tank/backups/cloud:/cloud-state:ro" in volumes
    # the pool is still exactly one read-write bind, and nothing but the cloud folder is read-only
    assert [v for v in volumes if v.split(":")[1:2] == ["/pool"]] == ["/mnt/tank/TheCreatorsPool:/pool:rw"]
    assert [v for v in volumes if v.endswith(":/cloud-state:rw")] == []
    # the sorter is told where it is, as a setting
    assert json.loads(ida.sorter_settings_json())["cloudState"] == "/cloud-state"
    assert _dashboard(sorter_enabled="1")["environment"]["DASH_SORTER_SETTINGS"] == ida.sorter_settings_json()
    assert ida.sorter_problems() == []


def test_the_cloud_setting_survives_the_rendered_yaml(studio, monkeypatch):
    monkeypatch.setattr(ida, "SITE_SORTER_CLOUD_STATE", "/mnt/tank/backups/cloud")
    for template in (ida.COMPOSE_TEMPLATE, IMAGE_TEMPLATE):
        _text, scalar = _rendered_setting_line(template)
        assert json.loads(_unquote_single(scalar))["cloudState"] == "/cloud-state", template.name


def test_cloud_state_problems_are_named(studio, monkeypatch):
    monkeypatch.setattr(ida, "SITE_SORTER_CLOUD_STATE", "backups/cloud")
    assert any("absolute HOST path" in p for p in ida.sorter_problems())
    monkeypatch.setattr(ida, "SITE_SORTER_CLOUD_STATE", "/mnt/tank/backups/cloud")
    monkeypatch.setattr(ida, "SITE_SORTER_POOL_HOST", "")
    assert any("cloud_state is set but pool_host is not" in p for p in ida.sorter_problems())


# --------------------------------------------- the sorter's backup folder (nas/cloud-backup.sh's control + snapshots)

BACKUP_OUT = "/mnt/tank/backups/sorter"


def test_no_backup_out_means_nothing_extra(studio):
    assert not any(":/backup-out" in v for v in _dashboard(sorter_enabled="1")["volumes"])
    assert "backupOut" not in json.loads(ida.sorter_settings_json())
    assert ida.sorter_backup_out_command("editors") == ""
    assert "group_add" not in _dashboard(sorter_enabled="1")


def test_backup_out_is_a_read_write_mount_and_a_setting(studio, monkeypatch):
    monkeypatch.setattr(ida, "SITE_SORTER_BACKUP_OUT", BACKUP_OUT)
    monkeypatch.setattr(ida, "SITE_SORTER_CLOUD_STATE", "/mnt/tank/backups/cloud")
    volumes = _dashboard(sorter_enabled="1")["volumes"]
    assert f"{BACKUP_OUT}:/backup-out:rw" in volumes
    assert "/mnt/tank/backups/cloud:/cloud-state:ro" in volumes            # unchanged beside it
    assert [v for v in volumes if v.split(":")[1:2] == ["/pool"]] == ["/mnt/tank/TheCreatorsPool:/pool:rw"]
    settings = json.loads(ida.sorter_settings_json())
    assert settings["backupOut"] == "/backup-out" and settings["cloudState"] == "/cloud-state"
    assert ida.sorter_problems() == []
    for template in (ida.COMPOSE_TEMPLATE, IMAGE_TEMPLATE):
        _t, scalar = _rendered_setting_line(template)
        assert json.loads(_unquote_single(scalar))["backupOut"] == "/backup-out", template.name


def test_the_container_gets_the_editors_group_from_the_live_gid_never_a_literal(studio, monkeypatch):
    monkeypatch.setattr(ida, "SITE_SORTER_BACKUP_OUT", BACKUP_OUT)
    # the gid the installer read from the NAS is what is used, whatever it is
    assert ida.compose_config(8480, HOST_ROOT, "http://gui:8384", "k", "t", sorter_enabled="1",
                              app_gid=65536)["services"]["dashboard"]["group_add"] == ["65536"]
    assert ida.compose_config(8480, HOST_ROOT, "http://gui:8384", "k", "t", sorter_enabled="1",
                              app_gid=4242)["services"]["dashboard"]["group_add"] == ["4242"]
    # once, beside the other groups, and the same gid as the pool's is not doubled
    monkeypatch.setattr(ida, "SITE_SORTER_POOL_GID", "4242")
    assert ida.compose_config(8480, HOST_ROOT, "http://gui:8384", "k", "t", sorter_enabled="1",
                              app_gid=4242)["services"]["dashboard"]["group_add"] == ["4242"]
    monkeypatch.setattr(ida, "SITE_SORTER_POOL_GID", "3002")
    assert ida.dashboard_group_add(4242) == ["3002", "4242"]
    # no backup folder, no extra group
    monkeypatch.setattr(ida, "SITE_SORTER_BACKUP_OUT", "")
    monkeypatch.setattr(ida, "SITE_SORTER_POOL_GID", "")
    assert ida.dashboard_group_add(4242) == []


def test_the_folders_are_created_only_if_missing_with_names_not_ids(monkeypatch):
    monkeypatch.setattr(ida, "SITE_SORTER_BACKUP_OUT", BACKUP_OUT)
    cmd = ida.sorter_backup_out_command("editors")
    for d in (BACKUP_OUT, BACKUP_OUT + "/control", BACKUP_OUT + "/snapshots"):
        q = f"'{d}'"
        assert f"[ -d {q} ] || {{ mkdir -p {q} && chown 'alex:editors' {q} && chmod 2770 {q}; }}" in cmd
    # nothing recursive and nothing unconditional: an existing folder is never touched
    assert "-R" not in cmd and "chown -R" not in cmd
    monkeypatch.setattr(ida, "SITE_SORTER_BACKUP_OUT_OWNER", "sam")
    assert "chown 'sam:editors'" in ida.sorter_backup_out_command("editors")


def test_the_created_folders_behave_on_a_real_shell(tmp_path, monkeypatch):
    """Run the command for real (sh, with chown/chmod stubbed to record): a missing folder is made with
    the right owner and mode; an existing one is left exactly alone."""
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("no sh")
    monkeypatch.setattr(ida, "SITE_SORTER_BACKUP_OUT", str(tmp_path / "backups" / "sorter"))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "log"
    for tool in ("chown", "chmod"):
        stub = bin_dir / tool
        stub.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{log.as_posix()}"\n', encoding="utf-8")
        stub.chmod(0o755)
    env = {"PATH": f"{bin_dir.as_posix()}:/usr/bin:/bin"}
    cmd = ida.sorter_backup_out_command("editors")
    proc = subprocess.run([sh, "-c", cmd], env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    root = tmp_path / "backups" / "sorter"
    assert (root / "control").is_dir() and (root / "snapshots").is_dir()
    first = log.read_text(encoding="utf-8").splitlines()
    assert len(first) == 6 and sum(l.startswith("chmod 2770") for l in first) == 3
    log.write_text("", encoding="utf-8")
    proc = subprocess.run([sh, "-c", cmd], env=env, capture_output=True, text=True)
    assert proc.returncode == 0 and log.read_text(encoding="utf-8") == ""          # second run: nothing touched


def test_a_relative_backup_out_is_named_as_a_problem(studio, monkeypatch):
    monkeypatch.setattr(ida, "SITE_SORTER_BACKUP_OUT", "backups/sorter")
    assert any("backup_out" in p and "absolute HOST path" in p for p in ida.sorter_problems())
