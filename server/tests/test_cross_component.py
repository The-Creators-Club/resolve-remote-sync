"""Cross-component contract tests: the constants that are DELIBERATELY
duplicated across server/, dashboard/ and companion/ (the dashboard container
cannot import server/, and the companion ships as a frozen exe that imports
neither) must not drift apart.

The three `.stignore` builders and the four `VIDEO_EXTS`-shaped lists were
byte-identical by convention only, with nothing asserting it -- so adding an
extension in one place gave a media type carried by both rclone AND Syncthing,
or by neither (KNOWN_BUGS §3 minors). B12 added a `.partial` exclusion to all
three builders; this is the test that keeps them together.

Run with:
    cd E:\\Projects\\resolve-remote-sync\\server
    python -m pytest tests -v
"""
import fnmatch
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "server"))
sys.path.insert(0, str(REPO_ROOT / "dashboard" / "src"))
sys.path.insert(0, str(REPO_ROOT / "companion" / "src"))

import common  # noqa: E402
from ccsync_companion.sync import rclone_lane as companion_rclone  # noqa: E402
from ccsync_companion.sync import syncthing_admin as companion_admin  # noqa: E402
from ccsync_dashboard import provision as dash_provision  # noqa: E402

SERVER_LINES = common.build_stignore_lines()
DASHBOARD_LINES = dash_provision.build_stignore_lines()
COMPANION_LINES = list(companion_admin.STIGNORE_LINES)

ALL_BUILDERS = {
    "server/common.py": SERVER_LINES,
    "dashboard/provision.py": DASHBOARD_LINES,
    "companion/sync/syncthing_admin.py": COMPANION_LINES,
}


# -- VIDEO_EXTS duplication (four modules, no shared source) ----------------


def test_video_extension_lists_agree_across_all_four_modules():
    """`VIDEO_EXTS` is copied into four modules. They are the definition of
    "what travels by rclone and must therefore NOT travel by Syncthing", so a
    list that drifts hands a media type to both lanes or to neither."""
    lists = {
        "server/common.VIDEO_EXTENSIONS": list(common.VIDEO_EXTENSIONS),
        "dashboard/provision.VIDEO_EXTENSIONS": list(dash_provision.VIDEO_EXTENSIONS),
        "companion/sync/rclone_lane.VIDEO_EXTS": list(companion_rclone.VIDEO_EXTS),
        "companion/sync/syncthing_admin._VIDEO_EXTS": list(companion_admin._VIDEO_EXTS),
    }
    reference = lists["server/common.VIDEO_EXTENSIONS"]
    for name, value in lists.items():
        assert value == reference, (
            f"{name} has drifted from server/common.VIDEO_EXTENSIONS: "
            f"only here={sorted(set(value) - set(reference))}, "
            f"only there={sorted(set(reference) - set(value))}"
        )


def test_every_video_extension_is_ignored_by_every_stignore_builder():
    for name, lines in ALL_BUILDERS.items():
        for ext in common.VIDEO_EXTENSIONS:
            assert f"(?i)*{ext}" in lines, f"{name} does not ignore {ext}"


# -- B12: orphaned rclone .partial files ------------------------------------


def test_all_three_builders_emit_the_same_partial_patterns():
    """B12: rclone runs --inplace=false, so lane A writes
    "<name>.<token>.partial" into a directory that is also a sendreceive
    Syncthing root. Every builder emitted only "(?i)*<video-ext>" plus Proxy
    patterns, which match by EXTENSION -- so a 39 GB orphan left by a lane A
    killed mid-transfer was indexed by the NAS and fanned out over lane C to
    every editor with that project ticked, where nothing ever deletes it."""
    expected = ["(?i)**/*.partial", "(?i)*.partial"]
    assert common.PARTIAL_IGNORE_LINES == expected
    assert dash_provision.PARTIAL_IGNORE_LINES == expected
    assert companion_admin.PARTIAL_IGNORE_LINES == expected
    for name, lines in ALL_BUILDERS.items():
        for pattern in expected:
            assert pattern in lines, f"{name} does not ignore {pattern}"


def test_the_partial_patterns_match_rclone_s_real_temp_names():
    """rclone's temp name is "<name>.<token>.partial" -- the token is derived
    from the file, not the run (measured against the bundled 1.74.4) -- and
    the express lane appends its own ".exp.partial". Both must match, at the
    folder root and at any depth. A pattern with no '/' matches the base name
    at any level in Syncthing, which is what fnmatch models here."""
    names = [
        "A001_C001.braw.42048420.partial",
        "A001_C001.braw.42048420" + companion_rclone.EXPRESS_PARTIAL_SUFFIX,
        "clip.mov" + companion_rclone.PARTIAL_SUFFIX,
    ]
    for lines in ALL_BUILDERS.values():
        globs = [line[len("(?i)"):] for line in lines if line.startswith("(?i)")]
        for name in names:
            assert any(
                fnmatch.fnmatch(name.lower(), pattern.lower())
                for pattern in globs
                if "/" not in pattern
            ), f"{name} matches no ignore pattern"


def test_the_partial_patterns_do_not_swallow_real_media():
    """The exclusion must not be broad enough to stop a finished file: the
    rename that completes an rclone transfer drops the suffix entirely."""
    for lines in ALL_BUILDERS.values():
        globs = [line[len("(?i)"):] for line in lines if line.startswith("(?i)")]
        partial_globs = [p for p in globs if p.endswith(".partial")]
        for name in ("A001_C001.braw", "Timeline.drp", "notes.txt", "partial.txt"):
            assert not any(
                fnmatch.fnmatch(name.lower(), p.lower()) for p in partial_globs
            ), f"{name} was matched by a .partial pattern"


# -- the rest of the shared surface -----------------------------------------


def test_slugify_agrees_between_server_and_dashboard():
    for text in ("2025/FF4/Nuclear", "2026\\CCT\\Creator Profiles", "A  b--C"):
        assert common.slugify(text) == dash_provision.slugify(text)


def test_marker_filename_and_template_folders_agree():
    assert common.MARKER_FILENAME == dash_provision.MARKER_FILENAME
    assert common.TEMPLATE_FOLDERS == dash_provision.TEMPLATE_FOLDERS


def test_no_builder_emits_duplicate_lines():
    for name, lines in ALL_BUILDERS.items():
        assert len(lines) == len(set(lines)), f"{name} emits a duplicate pattern"


# -- shared asset folders (the LUT library) --------------------------------
#
# Same three-copy problem as the project .stignore above, and a worse failure
# mode: the dashboard collector repairs the server side's copy every
# provision cycle and the companion re-asserts the editor side's on every
# pass, so a drift between them is not a wrong pattern here and there -- it
# is the two ends rewriting the file at each other forever.

ASSET_BUILDERS = {
    "server": common.build_asset_stignore_lines(),
    "dashboard": dash_provision.build_asset_stignore_lines(),
    "companion": list(companion_admin.ASSET_STIGNORE_LINES),
}


def test_shared_asset_folder_identity_agrees_across_all_three_modules():
    assert common.LUTS_FOLDER_ID == dash_provision.LUTS_FOLDER_ID == companion_admin.LUTS_FOLDER_ID
    assert common.LUTS_REL == dash_provision.LUTS_REL == companion_admin.LUTS_REL
    assert (common.SHARED_ASSET_FOLDERS
            == dash_provision.SHARED_ASSET_FOLDERS
            == companion_admin.SHARED_ASSET_FOLDERS)


def test_all_three_asset_stignore_builders_agree_exactly():
    server, dashboard, companion = (
        ASSET_BUILDERS["server"], ASSET_BUILDERS["dashboard"], ASSET_BUILDERS["companion"],
    )
    assert server == dashboard == companion


def test_the_asset_list_is_not_the_project_list():
    """They are different lists on purpose: a shared asset folder has no
    lane A or B under it, so it must not carry the Proxy patterns, and it
    must carry the OS-junk ones that a project folder does not need."""
    assert ASSET_BUILDERS["server"] != SERVER_LINES
    assert not any("Proxy" in line for line in ASSET_BUILDERS["server"])
    assert "(?i)**/.DS_Store" in ASSET_BUILDERS["server"]


def test_the_asset_list_still_brakes_on_video():
    """This folder auto-shares to the whole fleet with no tick to opt out
    of, so a stray 40 GB .mov must not reach every machine."""
    for name, lines in ASSET_BUILDERS.items():
        for ext in common.VIDEO_EXTENSIONS:
            assert f"(?i)*{ext}" in lines, f"{name} would fan out {ext} files"


def test_no_asset_builder_emits_duplicate_lines():
    for name, lines in ASSET_BUILDERS.items():
        assert len(lines) == len(set(lines)), f"{name} emits a duplicate asset pattern"


# -- delete protection (2026-08-11, docs/delete-protection-ignoredelete.md) --
#
# `ignoreDelete: true` now lives in FOUR hand-kept copies of a folder config:
# the companion's accept_folder, server/setup_syncthing_folder.py, and the
# dashboard's two builders. The flag protects the device it is set ON against
# deletes made elsewhere, so it only protects the fleet if EVERY side sets it
# -- a copy that drifts leaves that machine applying deletes while everyone
# believes the tree is protected. Same drift hazard as the .stignore builders
# above, with a quieter failure.


def _companion_accept_folder_config() -> dict:
    """The body companion accept_folder POSTs to /rest/config/folders. Built
    inside the method, so it is captured through a stub http_request rather
    than read off a constant."""
    sent = []

    def fake_http_request(method, url, api_key, body, timeout):
        sent.append((method, url, body))
        return {}

    admin = companion_admin.SyncthingAdmin(
        syncthing_url="http://127.0.0.1:8384", api_key="k", http_request=fake_http_request
    )
    admin.accept_folder(
        "abcd-nuclear", label="2026/FF5/Nuclear",
        local_path="/local/Projects/2026/FF5/Nuclear", offered_by_device_id="DEVICE-1",
    )
    return next(body for method, url, body in sent
                if method == "POST" and url.endswith("/rest/config/folders"))


def test_every_folder_builder_sets_ignore_delete():
    builders = {
        "companion/sync/syncthing_admin.accept_folder": _companion_accept_folder_config(),
        "dashboard/provision.build_folder_config": dash_provision.build_folder_config(
            "abcd-nuclear", "2026/FF5/Nuclear", "/data/Projects", ["DEVICE-1"]),
        "dashboard/provision.build_shared_folder_config":
            dash_provision.build_shared_folder_config(
                dash_provision.LUTS_FOLDER_ID, "Assets/Luts (LUT library)",
                "/data/Assets/Luts", ["DEVICE-1"]),
    }
    for name, config in builders.items():
        assert config.get("ignoreDelete") is True, (
            f"{name} does not set ignoreDelete: that machine applies deletes the rest "
            f"of the fleet ignores (docs/delete-protection-ignoredelete.md)")


def test_the_server_folder_config_sets_ignore_delete():
    """setup_syncthing_folder builds its folder object inline in main(), so
    this is a source check -- the same shape as test_safety.py's
    tuning-matches-the-collector test, which guards the neighbouring keys."""
    source = (REPO_ROOT / "server" / "setup_syncthing_folder.py").read_text(encoding="utf-8")
    assert '"ignoreDelete": True' in source, (
        "server/setup_syncthing_folder.py stopped provisioning ignoreDelete on the NAS "
        "side -- the authoritative copy would then apply an editor's delete")
