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
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "server"))
sys.path.insert(0, str(REPO_ROOT / "dashboard" / "src"))
sys.path.insert(0, str(REPO_ROOT / "companion" / "src"))

import common  # noqa: E402
from ccsync_companion import upgrade as companion_upgrade  # noqa: E402
from ccsync_companion import ytdl_common as companion_ytdl  # noqa: E402
from ccsync_companion import ytdl_executor as companion_ytdl_exec  # noqa: E402
from ccsync_companion.sync import rclone_lane as companion_rclone  # noqa: E402
from ccsync_companion.sync import syncthing_admin as companion_admin  # noqa: E402
from ccsync_dashboard import provision as dash_provision  # noqa: E402

# The vendored ytdl_common pair (2026-08-14, docs/YTDL_LOCAL_DOWNLOAD.md §5).
YTDL_WEB_PKG = REPO_ROOT / "ytdl" / "web" / "ytdlweb"
YTDL_COMMON_SRC = YTDL_WEB_PKG / "ytdl_common.py"
YTDL_COMMON_VENDORED = (REPO_ROOT / "companion" / "src" / "ccsync_companion"
                        / "ytdl_common.py")
# The other three files the two executors have to agree with each other about.
# Read as TEXT, not imported: routes_fleet needs fastapi and the package around
# it, and vendor/downloader.py needs yt_dlp, which the companion deliberately
# does not have (docs/YTDL_LOCAL_DOWNLOAD.md §6). config.py is stdlib-only and
# so can be loaded by path, like ytdl_common above.
YTDLWEB_CONFIG_SRC = YTDL_WEB_PKG / "config.py"
YTDLWEB_ROUTES_FLEET_SRC = YTDL_WEB_PKG / "routes_fleet.py"
YTDLWEB_WORKER_SRC = YTDL_WEB_PKG / "worker.py"
YTDLWEB_DOWNLOADER_SRC = YTDL_WEB_PKG / "vendor" / "downloader.py"


def _load_by_path(name: str, path: Path):
    """Import a module from a file without putting its tree on sys.path.

    ytdl/web canNOT go on sys.path from here, at any position: `ytdl/web/tests`
    is a REGULAR package (it has an __init__.py) and `server/tests` is not, so
    the import system hands the name `tests` to ytdl/web's outright -- a
    regular package beats a namespace portion no matter what comes first -- and
    test_logic.py's `from tests.test_safety import unquoted_occurrences` then
    dies with ModuleNotFoundError, in a file this one never touches (measured
    2026-08-14). Loading by path is also the honest thing here: ytdl_common
    imports nothing but os and pathlib, which is the whole point of it, so it
    needs no tree around it to load."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


server_ytdl = _load_by_path("ytdlweb_ytdl_common_under_test", YTDL_COMMON_SRC)
server_ytdl_config = _load_by_path("ytdlweb_config_under_test", YTDLWEB_CONFIG_SRC)

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
    # THE canonical copy is dashboard/provision.py's, because that is the one
    # a client can read without the repo: GET /api/v1/site publishes it as
    # `video_extensions` (2026-08-17, COMMERCIAL_READINESS.md item 11). The
    # other three stay hand-copied -- the container cannot import server/, and
    # the companion is a frozen exe that imports neither -- so this is what
    # keeps them in step.
    reference = lists["dashboard/provision.VIDEO_EXTENSIONS"]
    for name, value in lists.items():
        assert value == reference, (
            f"{name} has drifted from dashboard/provision.VIDEO_EXTENSIONS "
            f"(the canonical copy, served by GET /api/v1/site): "
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


# -- yt-dlp in-flight files (2026-08-13/14) ---------------------------------


def test_all_three_builders_emit_the_same_ytdl_patterns():
    """B12's failure, one lane over: the NAS-side ytdl worker downloads INTO
    the shared Projects tree, so lane C replicated every growing `.part` out
    to each editor with the project ticked -- and the 2026-08-11
    ignoreDelete=True retrofit means the worker's completion rename never
    propagates, so the leftovers are permanent (27 orphans, ~1.6 GB, three
    days, one editor's machine).

    All three copies are load-bearing, for three different reasons: the server
    writes the file at provision time, the dashboard collector's
    _ensure_ignores() re-POSTs its own list on ANY difference (so a pattern
    only the server knows about is stripped next cycle), and the companion's
    accept_folder() writes the editor side before any collector pass reaches
    a newly offered folder."""
    expected = [
        "(?i)**/*.part", "(?i)*.part",
        "(?i)**/*.part-Frag*", "(?i)*.part-Frag*",
        "(?i)**/*.ytdl", "(?i)*.ytdl",
    ]
    assert common.YTDL_IGNORE_LINES == expected
    assert dash_provision.YTDL_IGNORE_LINES == expected
    assert companion_admin.YTDL_IGNORE_LINES == expected
    for name, lines in ALL_BUILDERS.items():
        for pattern in expected:
            assert pattern in lines, f"{name} does not ignore {pattern}"


def test_the_server_and_dashboard_project_builders_are_identical():
    """The collector compares a folder's live ignores to the DASHBOARD's
    build_stignore_lines() with `have == want`, so these two lists must agree
    line for line AND in order -- otherwise every provision cycle rewrites
    what the server provisioned, logging a misleading "REPAIRED .stignore ...
    video was unfiltered" warning each time. (The companion's list is a
    superset: it also carries the fixer's .ccsync-tmp pair, which is an
    editor-side concern, and its checker asks "is everything present?" rather
    than demanding byte-equality.)"""
    assert SERVER_LINES == DASHBOARD_LINES


def test_the_ytdl_patterns_match_yt_dlp_s_real_in_flight_names():
    """Real names taken from ytdl/web's own sweeper tests. `.part-Frag84` is
    the one that does NOT end in `.part`, which is why it needs its own
    pattern instead of riding along on `*.part`."""
    names = [
        "Chan - T [abcdefghijk].f616.mp4.part",
        "Chan - T [abcdefghijk].f616.mp4.ytdl",
        "Chan - T [abcdefghijk].part",
        "Chan - T [abcdefghijk].part-Frag12",
    ]
    for builder, lines in ALL_BUILDERS.items():
        globs = [line[len("(?i)"):] for line in lines if line.startswith("(?i)")]
        for name in names:
            assert any(
                fnmatch.fnmatch(name.lower(), pattern.lower())
                for pattern in globs
                if "/" not in pattern
            ), f"{name} matches no ignore pattern in {builder}"


def test_the_ytdl_patterns_are_not_in_the_asset_builders():
    """Deliberate asymmetry: no ytdl worker writes into the LUT library or the
    Resolve gallery, and that list must stay byte-identical across the three
    components or the collector and the companion rewrite it at each other."""
    for name, lines in ASSET_BUILDERS.items():
        for pattern in common.YTDL_IGNORE_LINES:
            assert pattern not in lines, (
                f"{name}'s asset .stignore picked up {pattern}")


# -- the rest of the shared surface -----------------------------------------


def test_slugify_agrees_between_server_and_dashboard():
    for text in ("2025/FF4/Nuclear", "2026\\CCT\\Creator Profiles", "A  b--C"):
        assert common.slugify(text) == dash_provision.slugify(text)


def test_marker_filename_and_template_folders_agree():
    """The DEFAULTS are what must agree (2026-08-17, COMMERCIAL_READINESS.md
    item 11). Both lists became site data -- site.toml [tree] template_folders
    on the server side, DASH_SITE_TEMPLATE_FOLDERS in the container -- so the
    effective lists CAN differ while a site is half-configured. What must
    never differ is the out-of-the-box template a customer who configures
    neither gets from both components."""
    assert common.MARKER_FILENAME == dash_provision.MARKER_FILENAME
    assert common.DEFAULT_TEMPLATE_FOLDERS == dash_provision.DEFAULT_TEMPLATE_FOLDERS
    # And with no override in either environment (which is the state of this
    # test run) the effective lists are those defaults.
    assert common.TEMPLATE_FOLDERS == dash_provision.TEMPLATE_FOLDERS


def test_the_shared_asset_id_rule_is_the_same_on_both_sides():
    """A site that adds a library names only its rel path; the Syncthing
    folder id is derived. Both derivations must be slugify(rel), or the two
    ends provision two different folders for one directory."""
    rels = ["Assets/Luts", "Assets/Stills", "Assets/SFX", "Assets/Fusion Macros"]
    assert (common.shared_asset_folders_for(rels)
            == dash_provision.shared_asset_folders_for(rels))
    for folder_id, rel, _label in common.shared_asset_folders_for(rels):
        assert folder_id == common.slugify(rel)


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
    assert (common.DEFAULT_SHARED_ASSET_FOLDERS
            == dash_provision.DEFAULT_SHARED_ASSET_FOLDERS
            == companion_admin.SHARED_ASSET_FOLDERS)
    # Unconfigured (this test run) the effective registries are the defaults.
    # The companion has no override at all on purpose: it is a frozen exe that
    # learns the registry from the folders the server shares with it.
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


# -- the vendored ytdl_common (2026-08-14, docs/YTDL_LOCAL_DOWNLOAD.md §5) ---
#
# Worst duplication in the repo so far, because the two copies do not merely
# describe the same thing -- they NAME the same file. From companion 0.8.0 a
# clip is fetched either by the NAS worker or by the requester's own machine,
# both writing into one canonical tree that syncs fleet-wide, so a drifted
# vendored copy is not an error anyone sees: it is the same video arriving
# twice under two names, months before anyone notices (§5, and the R12 path-canon
# class of bug).
#
# tools/release.ps1 refuses to build on this exact comparison, which is the
# gate that matters -- a drifted copy cannot reach the fleet. This is the
# suite's half: the gate only runs at release time and only on Windows, and
# the strip logic is reimplemented here on purpose so a bug in one does not
# silently become the definition of "identical" in the other.

# (YTDL_COMMON_SRC / YTDL_COMMON_VENDORED are defined with the imports above --
# the source path is needed there to load the module by path.)
VENDOR_MARKER = b"# --- vendored content below, byte-identical ---"


def _vendored_body(path: Path) -> bytes:
    """The vendored file's bytes below its header marker line.

    Bytes, not text: this is the byte comparison the contract is written in, so
    nothing may decode or newline-translate on the way in. An absent or repeated
    marker fails here rather than degrading to "no header found, compare the
    whole file" -- the same fail-safe rule release.ps1's check follows."""
    raw = path.read_bytes()
    assert raw.count(VENDOR_MARKER) == 1, (
        f"{path} must carry {VENDOR_MARKER.decode()!r} exactly once, as the last "
        f"line of its header (found {raw.count(VENDOR_MARKER)})")
    rest = raw.split(VENDOR_MARKER, 1)[1]
    if rest.startswith(b"\r\n"):
        return rest[2:]
    return rest[1:] if rest.startswith(b"\n") else rest


def test_the_companion_copy_is_byte_identical_to_its_source():
    """`ytdl/web/ytdlweb/ytdl_common.py` is the source of truth; the companion
    carries a header and then those same bytes. Fix a drift by editing the
    ytdl/web copy and re-copying it in below the marker -- never by editing the
    companion's, which is what the header says and what the release gate
    prints."""
    assert YTDL_COMMON_SRC.exists(), f"missing source of truth: {YTDL_COMMON_SRC}"
    assert YTDL_COMMON_VENDORED.exists(), f"missing vendored copy: {YTDL_COMMON_VENDORED}"
    body = _vendored_body(YTDL_COMMON_VENDORED)
    source = YTDL_COMMON_SRC.read_bytes()
    assert body == source, (
        f"{YTDL_COMMON_VENDORED} has drifted from {YTDL_COMMON_SRC}: "
        f"{len(body)} bytes below the marker vs {len(source)} in the source. "
        f"Edit the ytdl/web copy, then re-copy it below the marker line.")


def test_the_contract_versions_agree():
    """The handshake numbers. The download manifest carries them and a
    companion whose vendored copy disagrees declines the claim, so version skew
    degrades to server-side execution -- but only if both sides are reading the
    same constants."""
    assert companion_ytdl.TEMPLATE_VERSION == server_ytdl.TEMPLATE_VERSION
    assert companion_ytdl.SIDECAR_VERSION == server_ytdl.SIDECAR_VERSION


# -- the vendored local-VLM set (2026-08-18, docs/BROLL_INGEST_PLAN.md §3.3) --
#
# Second instance of the ytdl_common problem, and the same answer. From
# companion 0.8.x an editor's own machine indexes b-roll with the INDEXER's
# local backend -- the same Qwen3-VL prompt, the same GBNF grammar, the same
# tolerant parser, the same contract -- because both write into one search
# database that the whole fleet queries. A drifted copy does not throw either:
# it describes clips slightly differently forever, and the only symptom is
# that search results depend on which machine happened to index a clip.
#
# The companion cannot import `broll_index` (anthropic, xxhash, pyyaml,
# requests, jieba -- ~50 MB and a licence surface in a frozen exe), and the
# indexer cannot import `ccsync_companion`, so five modules and one prompt are
# copied. tools/release.ps1 refuses to build on drift; this is the suites'
# half, and the strip logic is reimplemented here on purpose (same reason as
# ytdl_common's above).
BROLL_INDEX_SRC = REPO_ROOT / "broll" / "indexer" / "broll_index"
BROLL_VLM_VENDORED = (REPO_ROOT / "companion" / "src" / "ccsync_companion" / "broll_vlm")
BROLL_VLM_MODULES = ("local_models.py", "local_runtime.py", "local_vlm.py",
                     "compact_format.py", "contract.py")
BROLL_VLM_PROMPT = Path("prompts") / "index_clip_v7_compact.md"


@pytest.mark.parametrize("name", BROLL_VLM_MODULES)
def test_the_vendored_broll_vlm_modules_are_byte_identical(name):
    source = BROLL_INDEX_SRC / name
    vendored = BROLL_VLM_VENDORED / name
    assert source.exists(), f"missing source of truth: {source}"
    assert vendored.exists(), f"missing vendored copy: {vendored}"
    body = _vendored_body(vendored)
    assert body == source.read_bytes(), (
        f"{vendored} has drifted from {source}: {len(body)} bytes below the marker "
        f"vs {len(source.read_bytes())} in the source. Edit the INDEXER's copy, then "
        f"re-copy the whole file in below the marker line.")


def test_the_vendored_vlm_prompt_is_an_exact_copy():
    """The ONE vendored file with no header: `build_compact_prompt` reads it
    and sends its text to the model, so a vendoring header would (a) be part of
    the prompt and (b) differ from what the indexer sends -- exactly the drift
    the copy exists to prevent. Whole-file equality instead, which is stricter,
    not looser."""
    source = BROLL_INDEX_SRC / BROLL_VLM_PROMPT
    vendored = BROLL_VLM_VENDORED / BROLL_VLM_PROMPT
    assert source.exists() and vendored.exists()
    assert vendored.read_bytes() == source.read_bytes(), (
        f"{vendored} has drifted from {source} -- copy the indexer's file over it whole.")


# -- the vendored CLAP audio front end (2026-08-18, MUSIC_INGEST_PLAN.md) ----
#
# Third instance of the same problem, and the sharpest one. The companion
# embeds dropped music with the CLAP audio tower now, and two of the three
# pieces that takes are the indexer's: the artefact catalogue (which ONNX,
# which sha256) and the log-mel front end. A drifted parser throws; a drifted
# MEL does not -- it produces a perfectly plausible 512-dimensional vector for
# audio that does not sound like that, in the one space every cosine in the
# music library is measured against.
MUSIC_INDEXER_SRC = REPO_ROOT / "music" / "indexer"
MUSIC_CLAP_VENDORED = (REPO_ROOT / "companion" / "src" / "ccsync_companion"
                       / "music_clap")
MUSIC_CLAP_MODULES = ("music_models.py", "mel_numpy.py")


@pytest.mark.parametrize("name", MUSIC_CLAP_MODULES)
def test_the_vendored_music_clap_modules_are_byte_identical(name):
    source = MUSIC_INDEXER_SRC / name
    vendored = MUSIC_CLAP_VENDORED / name
    assert source.exists(), f"missing source of truth: {source}"
    assert vendored.exists(), f"missing vendored copy: {vendored}"
    body = _vendored_body(vendored)
    assert body == source.read_bytes(), (
        f"{vendored} has drifted from {source}: {len(body)} bytes below the marker "
        f"vs {len(source.read_bytes())} in the source. Edit the INDEXER's copy, then "
        f"re-copy the whole file in below the marker line.")


def test_the_vendored_music_clap_set_has_no_unchecked_members():
    """A third module dropped into music_clap/ without a line in
    MUSIC_CLAP_MODULES (and in tools/release.ps1's $VendorPairs and
    tools/release_macos.sh's VENDOR_PAIRS) would be unpinned forever."""
    present = sorted(p.name for p in MUSIC_CLAP_VENDORED.glob("*.py")
                     if p.name != "__init__.py")
    assert present == sorted(MUSIC_CLAP_MODULES), (
        "companion/src/ccsync_companion/music_clap/ gained or lost a module: add it "
        "to MUSIC_CLAP_MODULES here AND to both release gates")


def test_the_vendored_vlm_set_has_no_unchecked_members():
    """A sixth module dropped into broll_vlm/ without a line in
    BROLL_VLM_MODULES (and in tools/release.ps1's $VendorPairs) would be
    unpinned forever, which is worse than not vendoring it at all."""
    present = sorted(p.name for p in BROLL_VLM_VENDORED.glob("*.py")
                     if p.name != "__init__.py")
    assert present == sorted(BROLL_VLM_MODULES), (
        "companion/src/ccsync_companion/broll_vlm/ gained or lost a module: add it to "
        "BROLL_VLM_MODULES here AND to $VendorPairs in tools/release.ps1")


@pytest.mark.parametrize("gate", ["release.ps1", "release_macos.sh"])
def test_both_release_gates_pin_every_vendored_pair(gate):
    """The suites and BOTH release gates must agree on what is checked. A pair
    added here but not there ships on the next release; a pair in the Windows
    gate only would let a Mac build carry a drifted copy (SHIP-3 is exactly
    that hole, found once already)."""
    text = (REPO_ROOT / "tools" / gate).read_text(encoding="utf-8")
    for name in (*BROLL_VLM_MODULES, BROLL_VLM_PROMPT.name, "ytdl_common.py"):
        assert name in text, f"tools/{gate} does not pin the vendored {name}"


# -- the b-roll ingest vendored pairs (2026-08-18, BROLL_INGEST_PLAN.md §3.1) --
#
# Same mechanism as ytdl_common above, two more files, and neither of them
# involves the companion at all: they cross from one deployed tree to another
# inside the container, which is a gap no import can close.
#
#   broll/web/app/normalize.py  <- broll/indexer/broll_index/normalize.py
#     `search_norm`, the word-segmented + script-normalised CJK blob. The
#     server computes it now (the HTTP ingest path used to insert an empty one
#     and leave it to a base-rig embed pass; dashboard ingest has no base rig).
#     A blob built by a DIFFERENT tokenisation than the one the query path
#     normalises with does not match badly, it matches nothing -- so this is
#     the same silent class of failure as a drifted ytdl_common, one layer
#     down. broll/web cannot import broll_index: the container has no
#     anthropic, xxhash, pyyaml or requests.
#
#   broll/web/app/identity.py   <- ytdl/web/ytdlweb/identity.py
#     Verifies WHICH editor's companion is calling. Two verifiers that disagree
#     about a token shape are two answers to that question and one is wrong.
#     broll/web cannot import ytdlweb either: ytdl is feature-gated and a site
#     may never have shipped it, and b-roll ingest must not stop working
#     because a customer turned the YouTube downloader off.
BROLL_VENDOR_PAIRS = {
    "broll/web/app/normalize.py": (
        REPO_ROOT / "broll" / "web" / "app" / "normalize.py",
        REPO_ROOT / "broll" / "indexer" / "broll_index" / "normalize.py"),
    "broll/web/app/identity.py": (
        REPO_ROOT / "broll" / "web" / "app" / "identity.py",
        YTDL_WEB_PKG / "identity.py"),
}


def test_the_broll_web_vendored_copies_are_byte_identical_to_their_sources():
    """Fix a drift by editing the SOURCE and re-copying it in below the marker
    -- never by editing broll/web's copy, which is what each header says and
    what tools/release.ps1 prints."""
    for label, (vendored, source) in sorted(BROLL_VENDOR_PAIRS.items()):
        assert source.exists(), f"missing source of truth for {label}: {source}"
        assert vendored.exists(), f"missing vendored copy: {vendored}"
        body = _vendored_body(vendored)
        assert body == source.read_bytes(), (
            f"{vendored} has drifted from {source}: {len(body)} bytes below the "
            f"marker vs {len(source.read_bytes())} in the source. Edit the source, "
            f"then re-copy it below the marker line.")


def test_the_vendored_identity_verifier_agrees_with_ytdls():
    """The bytes are equal, so this proves the two MODULES load independently
    and answer the same on the input that matters: a genuine token, and the
    session-purpose token that must never be replayable as a machine identity
    (the dashboard's SEC-1, copied into both copies of this file)."""
    ytdl_identity = _load_by_path("ytdlweb_identity_under_test",
                                  YTDL_WEB_PKG / "identity.py")
    broll_identity = _load_by_path(
        "broll_web_identity_under_test",
        REPO_ROOT / "broll" / "web" / "app" / "identity.py")
    secret = "s" * 32
    token = ytdl_identity.make_identity_token(secret, "jsmith")
    assert broll_identity.read_identity_token(secret, token) == "jsmith"
    assert ytdl_identity.read_identity_token(secret, token) == "jsmith"
    for bad in (None, "", "v1.jsmith.999.deadbeef", token.replace("identity", "session"),
                token[:-1] + ("0" if token[-1] != "0" else "1")):
        assert broll_identity.read_identity_token(secret, bad) is None, bad
        assert ytdl_identity.read_identity_token(secret, bad) is None, bad
    # No secret configured is None on BOTH sides -- fail-closed is the property,
    # not an implementation detail of one of them.
    assert broll_identity.read_identity_token("", token) is None
    assert ytdl_identity.read_identity_token("", token) is None


# -- the music ingest vendored pair (2026-08-18, MUSIC_INGEST_PLAN.md step 2) --
#
#   music/web/musicweb/identity.py  <- ytdl/web/ytdlweb/identity.py
#     The THIRD copy of the verifier that answers "which editor's companion is
#     calling", for the third fleet-token surface (music ingest). Three
#     verifiers that disagree about a token shape are three answers to one
#     question and two of them are wrong.
#
#     musicweb can import neither of the other two: ytdl is feature-gated and a
#     site may never have shipped it, and broll/web is deployed as a tree
#     imported as the top-level package `app` -- the one name musicweb must
#     never depend on (CLAUDE.md: two packages called `app` on one PYTHONPATH
#     collide in sys.modules and one silently wins), and a music mount that
#     stopped verifying identities because the b-roll checkout is stale would
#     break the rule that each mount fails on its own.
MUSIC_VENDOR_PAIRS = {
    "music/web/musicweb/identity.py": (
        REPO_ROOT / "music" / "web" / "musicweb" / "identity.py",
        YTDL_WEB_PKG / "identity.py"),
}


def test_the_music_web_vendored_copies_are_byte_identical_to_their_sources():
    """Fix a drift by editing the SOURCE and re-copying it in below the marker
    -- never by editing musicweb's copy, which is what its header says and what
    tools/release.ps1 prints."""
    for label, (vendored, source) in sorted(MUSIC_VENDOR_PAIRS.items()):
        assert source.exists(), f"missing source of truth for {label}: {source}"
        assert vendored.exists(), f"missing vendored copy: {vendored}"
        body = _vendored_body(vendored)
        assert body == source.read_bytes(), (
            f"{vendored} has drifted from {source}: {len(body)} bytes below the "
            f"marker vs {len(source.read_bytes())} in the source. Edit the source, "
            f"then re-copy it below the marker line.")


def test_all_three_identity_verifiers_agree():
    """The bytes are equal, so this proves the three MODULES load independently
    and answer the same on the input that matters: a genuine token, and the
    session-purpose token that must never be replayable as a machine identity
    (the dashboard's SEC-1, copied into all three copies of this file)."""
    modules = {
        "ytdl": _load_by_path("ytdlweb_identity_three", YTDL_WEB_PKG / "identity.py"),
        "broll": _load_by_path("broll_identity_three",
                               REPO_ROOT / "broll" / "web" / "app" / "identity.py"),
        "music": _load_by_path("music_identity_three",
                               REPO_ROOT / "music" / "web" / "musicweb" / "identity.py"),
    }
    secret = "s" * 32
    token = modules["ytdl"].make_identity_token(secret, "jsmith")
    for name, mod in modules.items():
        assert mod.read_identity_token(secret, token) == "jsmith", name
        for bad in (None, "", "v1.jsmith.999.deadbeef",
                    token.replace("identity", "session"),
                    token[:-1] + ("0" if token[-1] != "0" else "1")):
            assert mod.read_identity_token(secret, bad) is None, (name, bad)
        # No secret configured is None everywhere -- fail-closed is the
        # property, not an implementation detail of one of them.
        assert mod.read_identity_token("", token) is None, name
        assert mod.HEADER == modules["ytdl"].HEADER, name


def test_the_music_release_gates_pin_the_music_pair():
    """Both gates, for SHIP-3's reason: a pair pinned in the Windows gate only
    would let a Mac build ship a drifted copy."""
    for gate in ("release.ps1", "release_macos.sh"):
        text = (REPO_ROOT / "tools" / gate).read_text(encoding="utf-8")
        assert "music/web/musicweb/identity.py" in text.replace("\\", "/"), gate


# A deliberately hostile info dict: the byte comparison above proves the FILES
# match, this proves the two imported MODULES behave alike on the input most
# likely to expose an encoding or fallback difference between a Linux container
# and a Windows editor.
#
#   - a CJK title, every character 3 bytes in UTF-8 (the reason OUTTMPL
#     truncates with `.140B` and not `.140` -- NFS and SMB cap a NAME at 255
#     bytes, so a character count is the wrong unit);
#   - long enough to cross that 140-byte cap while staying under 140
#     characters, so a copy that lost the `B` would name the file differently;
#   - `channel` / `channel_url` / `upload_date` / `duration` absent, so the
#     uploader/uploader_url fallbacks and the None defaults all fire.
HOSTILE_INFO = {
    "uploader": "Крео Клуб · 创作者俱乐部",
    "uploader_url": "https://www.youtube.com/@创作者俱乐部",
    "title": ("無人機航拍：大河谷液化天然氣工程 — 第二部分「日落」（４Ｋ）"
              "测试测试测试测试测试测试测试测试测试测试测试测试测试"),
    "webpage_url": "https://www.youtube.com/watch?v=SAQBbd1Rxmo",
    "id": "SAQBbd1Rxmo",
}


def test_the_hostile_fixture_is_actually_hostile():
    """A guard on the fixture itself: if the title stops crossing 140 bytes
    while staying under 140 characters, the parity tests below still pass but
    stop testing the thing they were written for."""
    title = HOSTILE_INFO["title"]
    assert len(title.encode("utf-8")) > 140, "title no longer exercises the .140B cap"
    assert len(title) < 140, "title is long in CHARACTERS too -- bytes vs chars untested"


def test_credits_sidecar_agrees_on_the_hostile_fixture():
    for info in (HOSTILE_INFO, {}, None):
        assert companion_ytdl.credits_sidecar(info) == server_ytdl.credits_sidecar(info)
    # Field order is part of the payload once it is serialised, and dicts keep
    # insertion order -- so compare the ordering too, not just the mapping.
    assert (list(companion_ytdl.credits_sidecar(HOSTILE_INFO))
            == list(server_ytdl.credits_sidecar(HOSTILE_INFO))
            == list(server_ytdl.SIDECAR_FIELDS))


def test_the_serialised_sidecar_is_byte_identical():
    """`indent=2, ensure_ascii=False` is what actually reaches disk on both
    sides (downloader._write_sidecar on the NAS, ytdl_executor on the
    companion). ensure_ascii defaults to True, so getting this wrong would
    \\u-escape every CJK title on one executor and leave it literal on the
    other: one artifact, two byte streams, in one canonical tree."""
    dumped = [json.dumps(m.credits_sidecar(HOSTILE_INFO), indent=2, ensure_ascii=False)
              for m in (companion_ytdl, server_ytdl)]
    assert dumped[0] == dumped[1]
    assert dumped[0].encode("utf-8") == dumped[1].encode("utf-8")
    assert "\\u" not in dumped[0], "ensure_ascii escaping crept back in"


def test_the_naming_contract_agrees():
    """OUTTMPL is THE filename on both executors; `outtmpl()` only joins it to
    a destination, and the separator is deliberately the executing machine's --
    so the template and the sidecar rule are compared, and the join is compared
    against itself rather than against a hardcoded path shape."""
    assert companion_ytdl.OUTTMPL == server_ytdl.OUTTMPL
    assert companion_ytdl.SIDECAR_SUFFIX == server_ytdl.SIDECAR_SUFFIX
    assert companion_ytdl.SIDECAR_FIELDS == server_ytdl.SIDECAR_FIELDS
    for outdir in ("/projects/2026/FF5/Nuclear/Footage",
                   r"P:\Projects\2026\FF5\Nuclear\Footage"):
        assert companion_ytdl.outtmpl(outdir) == server_ytdl.outtmpl(outdir)
    for path in ("/projects/2026/FF5/Nuclear/Footage/Chan - T [abcdefghijk].mp4",
                 r"P:\Projects\2026\FF5\Nuclear\Chan - T [abcdefghijk].part.mkv",
                 "no-extension"):
        assert companion_ytdl.sidecar_path(path) == server_ytdl.sidecar_path(path)


def test_the_quality_ladder_agrees_on_every_rung():
    """The fallback rung a truncated stream drops to. A disagreement here is
    the quiet direction of the failure: the NAS delivers 1080p and the editor's
    own machine delivers 720p for the same click, or one of them gives up where
    the other would have retried."""
    assert companion_ytdl.QUALITY_HEIGHTS == server_ytdl.QUALITY_HEIGHTS
    assert companion_ytdl.BEST_FALLBACK_QUALITY == server_ytdl.BEST_FALLBACK_QUALITY
    assert companion_ytdl.TRUNCATION_MARKERS == server_ytdl.TRUNCATION_MARKERS
    assert companion_ytdl.TRUNCATED_NOTE == server_ytdl.TRUNCATED_NOTE

    rungs = list(server_ytdl.QUALITY_HEIGHTS) + ["audio", "1081p", "", "BEST", None]
    for quality in rungs:
        # Each side passes its OWN table, which is how it works in the wild:
        # the worker passes downloader.QUALITY_HEIGHTS, the companion has no
        # downloader and passes its vendored copy's.
        assert (companion_ytdl.lower_quality(quality, companion_ytdl.QUALITY_HEIGHTS)
                == server_ytdl.lower_quality(quality, server_ytdl.QUALITY_HEIGHTS)), (
            f"lower_quality disagrees for {quality!r}")


def test_the_format_selector_agrees_for_every_rung_and_codec_preference():
    """The `-f` string is what the two executors ask YouTube for. YTDL-4: the
    AVC alternatives are prepended only at <=1080p, and a copy that lost that
    rule downloads 1080p for a 2160p request and reports success -- silent
    quality loss, and only on one half of the fleet."""
    rungs = list(server_ytdl.QUALITY_HEIGHTS) + ["audio", "1081p", "", "BEST", None]
    for quality in rungs:
        for prefer_avc in (True, False):
            assert (companion_ytdl.format_selector(quality, prefer_avc)
                    == server_ytdl.format_selector(quality, prefer_avc)), (
                f"format_selector disagrees for {quality!r} prefer_avc={prefer_avc}")


# -- the two executors' THREE remaining hand-kept pairs (2026-08-14) ---------
#
# ytdl_common above is vendored, so the release gate can compare it byte for
# byte. These three cannot be: they are the same DECISION expressed twice, in
# two languages of the same repo, because neither side can import the other --
# the container has no companion source and the frozen companion has neither
# fastapi nor yt_dlp. Each pin below is two-sided on purpose: editing one half
# alone fails here rather than shipping a fleet whose two download paths
# quietly disagree.


def _paren_calls(source: str, needle: str) -> list[str]:
    """Every `needle(...)` call in `source`, balanced-paren, as text.

    Text rather than ast because these files are read, not imported (see the
    path constants above), and because the point of the comparison is the
    EXPRESSION an editor typed -- `body.channel or row['channel']` -- not the
    value it produces at runtime.
    """
    out, i = [], source.find(needle)
    while i != -1:
        depth = 0
        for j in range(i, len(source)):
            if source[j] == "(":
                depth += 1
            elif source[j] == ")":
                depth -= 1
                if depth == 0:
                    out.append(source[i:j + 1])
                    break
        else:  # pragma: no cover - an unbalanced call would not parse either
            raise AssertionError(f"unbalanced {needle} call in the source")
        i = source.find(needle, i + 1)
    return out


def _normalise_fallbacks(text: str) -> str:
    """Rewrite both sides' spelling of "what the executor sent" and "what the
    row already holds" into one vocabulary, so the two expressions can be
    compared for SHAPE.

    The worker reads yt-dlp's own result dict (`res.get('channel')`) and the
    fleet route reads the posted body (`body.channel`); the row is `v[...]`
    in one and `row[...]` in the other. Everything else -- the operator, the
    order, the argument positions -- must match exactly.
    """
    text = re.sub(r"res\.get\('(\w+)'\)", r"SENT.\1", text)
    text = re.sub(r"body\.(\w+)", r"SENT.\1", text)
    text = re.sub(r"v\['(\w+)'\]", r"ROW.\1", text)
    text = re.sub(r"row\['(\w+)'\]", r"ROW.\1", text)
    return " ".join(text.split())


def _kwarg(call: str, name: str) -> str:
    """One `name=<expr>` argument out of a normalised call, up to the next
    top-level comma."""
    i = call.index(f"{name}=") + len(name) + 1
    depth = 0
    for j in range(i, len(call)):
        if call[j] in "([{":
            depth += 1
        elif call[j] in ")]}":
            if depth == 0:
                return call[i:j].strip()
            depth -= 1
        elif call[j] == "," and depth == 0:
            return call[i:j].strip()
    raise AssertionError(f"{name}= is unterminated")


# 1. the `done` clip-status post: title/channel, and the per-field fallback ---


def test_the_clip_status_body_carries_the_ledger_fields_both_executors_fill():
    """YTDL-WEB-8 (2026-08-14): only the DOWNLOADER ever learns the uploader of
    a PASTED link -- create_url_job writes video_id/url/title and makes no
    metadata call -- so a clip fetched by an editor ledgered a NULL channel
    while the identical paste on the NAS filled it in. The fix is two-sided:
    the companion sends them and the route accepts them."""
    routes = YTDLWEB_ROUTES_FLEET_SRC.read_text(encoding="utf-8")
    body_model = routes[routes.index("class ClipStatusIn("):
                        routes.index("@router.post", routes.index("class ClipStatusIn("))]
    for field in ("title", "channel", "thumbnail"):
        assert f"{field}: str | None = None" in body_model, (
            f"ClipStatusIn stopped accepting {field}; the companion still posts it")

    import inspect
    params = inspect.signature(companion_ytdl_exec.FleetClient.clip_status).parameters
    for field in ("title", "channel"):
        assert field in params, (
            f"the companion stopped sending {field}; routes_fleet still reads it")
        assert params[field].default is None


def test_the_companion_omits_the_ledger_fields_it_does_not_know():
    """Sending `null` and sending nothing are DIFFERENT here: the route's
    fallback is `body.channel or row['channel']`, and a pasted-link row has no
    channel until a download reports one -- so an executor that could not read
    an info json must not overwrite the row's answer with a None."""
    class _Capturing(companion_ytdl_exec.FleetClient):
        def __init__(self):            # noqa: D107 - only _call is exercised
            self.sent = []

        def _call(self, method, suffix, body=None):
            self.sent.append(body)
            return 200, {}

    client = _Capturing()
    client.clip_status(7, "abcdefghijk", "done", filepath_rel="x.mp4",
                       title="T", channel="C")
    assert client.sent[-1]["title"] == "T"
    assert client.sent[-1]["channel"] == "C"

    client.clip_status(7, "abcdefghijk", "done", filepath_rel="x.mp4")
    assert "title" not in client.sent[-1], "a null title would blank the row"
    assert "channel" not in client.sent[-1], "a null channel would blank the row"


def test_the_done_ledger_row_is_written_the_same_way_by_both_executors():
    """`_record_done` is worker._phase_download's done-branch, written for a
    clip that landed on somebody else's disk -- the endpoint's stated contract
    is "the same rows from both executors". Compared as an expression, after
    normalising only the two names for "what the executor reported" and "what
    the row holds": argument order, the `or` fallbacks and every other argument
    have to be identical, so adding a ledger column to one side fails here."""
    worker = YTDLWEB_WORKER_SRC.read_text(encoding="utf-8")
    routes = YTDLWEB_ROUTES_FLEET_SRC.read_text(encoding="utf-8")
    # worker.py ledgers twice: the already-in-tree skip path (which has no
    # executor answer to fall back FROM) and the completed-download path.
    worker_call = [c for c in _paren_calls(worker, "db.ledger_add(")
                   if "res.get(" in c]
    routes_call = [c for c in _paren_calls(routes, "db.ledger_add(")
                   if "body." in c]
    assert len(worker_call) == 1, "worker.py's done-branch ledger row moved"
    assert len(routes_call) == 1, "_record_done's ledger row moved"

    assert _normalise_fallbacks(worker_call[0]) == _normalise_fallbacks(routes_call[0])
    # ...and the fallback really is per-field, not a single "did they send
    # anything" test, which is the shape YTDL-WEB-8 needed.
    assert "SENT.title or ROW.title" in _normalise_fallbacks(routes_call[0])
    assert "SENT.channel or ROW.channel" in _normalise_fallbacks(routes_call[0])


def test_the_done_video_row_falls_back_field_by_field_on_both_sides():
    """The same rule one row over. `download_host` is the ONE thing the fleet
    route writes that the worker does not (it is the only thing that differs
    between the modes, and the one thing the history should say), so the
    comparison is per-field rather than whole-call."""
    worker = YTDLWEB_WORKER_SRC.read_text(encoding="utf-8")
    routes = YTDLWEB_ROUTES_FLEET_SRC.read_text(encoding="utf-8")
    worker_done = next(_normalise_fallbacks(c)
                       for c in _paren_calls(worker, "db.set_video(")
                       if "dl_state='done'" in c and "res.get(" in c)
    routes_done = next(_normalise_fallbacks(c)
                       for c in _paren_calls(routes, "db.set_video(")
                       if "dl_state='done'" in c and "body." in c)
    for field in ("title", "thumbnail"):
        assert _kwarg(worker_done, field) == _kwarg(routes_done, field), field
    assert "download_host=host" in routes_done


# 2. version ranking: two implementations of one ordering --------------------

# Every shape the two rankers have to agree on, including the ones the
# docstrings on both sides call out by name.
VERSION_RANK_TABLE = (
    "2026.8.4",            # unpadded -- ranks BELOW 2026.08.10, unlike a string
    "2026.08.04",
    "2026.08.10",
    "2026.07.04.123456",   # a nightly: four parts, ranks after the release
    "v1.2",
    "nightly",             # unrankable
    "2026.08.04-hotfix",   # unrankable ON PURPOSE: truncating ranks it too low
    "",
    None,
    0,
)


def test_version_ranking_agrees_between_ytdlweb_and_the_companion():
    """ytdlweb.config.version_rank is a deliberate COPY of
    ccsync_companion.upgrade.parse_version -- the container must run with no
    companion source in reach, so it cannot import the original. The two are
    the SAME comparison seen from both ends: the server 403s a claim from a
    machine below MIN_YTDLP_VERSION, and the companion decides whether it has
    anything to update. A ranker that disagreed would 403 the whole fleet
    while every companion concluded it was up to date."""
    for version in VERSION_RANK_TABLE:
        assert (server_ytdl_config.version_rank(version)
                == companion_upgrade.parse_version(version)), (
            f"version ranking disagrees for {version!r}")


def test_both_rankers_order_unpadded_versions_numerically():
    """The hazard config.py names: one unpadded floor ('2026.8.5') sorts ABOVE
    every '2026.08.xx' AS A STRING, so a string comparison would 403 the fleet
    while each companion -- which ranks numerically -- saw nothing to do."""
    for rank in (server_ytdl_config.version_rank, companion_upgrade.parse_version):
        assert rank("2026.8.5") < rank("2026.08.10") < rank("2026.12.1")
        assert rank("2026.07.04") < rank("2026.07.04.123456")
    assert "2026.8.5" > "2026.08.10", "the string ordering this exists to avoid"


def test_the_shipped_yt_dlp_floor_can_be_ranked_by_both_sides():
    """An unrankable floor is the failure config._validated_floor exists to
    refuse; the shipped default must never be one, and it must mean the same
    number to the machine being gated as to the one gating it."""
    floor = server_ytdl_config.DEFAULT_MIN_YTDLP_VERSION
    assert server_ytdl_config.version_rank(floor) is not None
    assert companion_upgrade.parse_version(floor) == server_ytdl_config.version_rank(floor)
    # ...and the floor actually in force, after the import-time validation.
    assert server_ytdl_config.version_rank(server_ytdl_config.MIN_YTDLP_VERSION) is not None


# 3. the embedded credits tags: one postprocessor pass, two spellings --------

# `"key": "MetadataParser"` ... `"key": "FFmpegMetadata"` in the vendored
# downloader's build_opts: the pre_process actions whose output FFmpegMetadata
# then writes into the file.
_CREDITS_ACTION_RE = re.compile(
    r'_credits_action\("([^"]+)",\s*"([^"]+)"\)'
    r'|\(MetadataParserPP\.Actions\.INTERPRET,\s*"([^"]+)",\s*"([^"]+)"\)'
)


def _server_credits_mappings() -> list[str]:
    """The vendored downloader's metadata actions as `FROM:TO`, in order.

    `--parse-metadata FROM:TO` IS MetadataParserPP.Actions.INTERPRET, so the
    companion's CLI spelling and the NAS's postprocessor dict reduce to the
    same list -- which is the only reason these two can be compared at all.
    """
    source = YTDLWEB_DOWNLOADER_SRC.read_text(encoding="utf-8")
    start = source.index('"key": "MetadataParser"')
    end = source.index('"key": "FFmpegMetadata"', start)
    mappings = []
    for m in _CREDITS_ACTION_RE.finditer(source[start:end]):
        if m.group(1):
            mappings.append(f"{m.group(1)}:%(meta_{m.group(2)})s")
        else:
            mappings.append(f"{m.group(3)}:{m.group(4)}")
    return mappings


def _companion_credits_mappings() -> list[str]:
    args = companion_ytdl_exec.CREDITS_METADATA_ARGS
    return [args[i + 1] for i, a in enumerate(args) if a == "--parse-metadata"]


def test_the_embedded_credits_tags_agree_between_the_two_executors():
    """COMP-BROLL-2 (2026-08-14). The naming contract is "the outtmpl, the
    sidecar, EMBEDDED TAGS": two clips with IDENTICAL NAMES and different
    insides is precisely the skew §5 exists to prevent, and the tags are what
    the downstream Resolve credits script reads.

    Unlike the companion's own copy of this pin, this one does NOT skip when
    vendor/downloader.py is absent: both trees are in this repo by definition,
    and a missing one here means a broken checkout, not an unavailable
    component."""
    assert YTDLWEB_DOWNLOADER_SRC.is_file(), (
        f"missing {YTDLWEB_DOWNLOADER_SRC} -- the NAS-side downloader is part "
        f"of this repo; a checkout without it cannot be released")
    server = _server_credits_mappings()
    assert len(server) == 6, f"the vendored downloader's actions changed: {server}"
    # Order matters as much as membership: MetadataParser applies them in
    # sequence and two of them read the same source field.
    assert server == _companion_credits_mappings()


def test_the_four_custom_container_tags_are_still_the_ones_resolve_reads():
    """The mappings written out, so a change to BOTH sides at once still has
    to be a deliberate edit here rather than a silent rename of the tags the
    credits script looks for."""
    server = _server_credits_mappings()
    assert server[:4] == [
        "%(channel,uploader)s:%(meta_channel)s",
        "%(webpage_url)s:%(meta_video_url)s",
        "%(channel_url,uploader_url)s:%(meta_channel_url)s",
        "%(uploader,channel)s:%(meta_uploader)s",
    ]
    # ...and the two STANDARD tags the same pass writes.
    assert server[4:] == ["%(channel,uploader)s:%(artist)s",
                          "%(webpage_url)s:%(meta_comment)s"]


def test_the_companion_asks_for_the_chapters_the_servers_postprocessor_defaults_to():
    """The one place the two spellings are NOT symmetric. FFmpegMetadataPP
    defaults add_chapters=True, so the NAS's one-key dict embeds chapters --
    while the CLI flag defaults OFF, which is why the companion has to say
    --embed-chapters as well as --embed-metadata to get the same file."""
    source = YTDLWEB_DOWNLOADER_SRC.read_text(encoding="utf-8")
    assert '{"key": "FFmpegMetadata", "add_metadata": True}' in source
    assert "add_chapters" not in source, (
        "the vendored downloader now sets add_chapters explicitly -- the "
        "companion's --embed-chapters has to be re-derived from it")
    args = companion_ytdl_exec.CREDITS_METADATA_ARGS
    assert "--embed-metadata" in args and "--embed-chapters" in args
