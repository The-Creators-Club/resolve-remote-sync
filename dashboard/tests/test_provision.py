from __future__ import annotations

import json

import pytest

from ccsync_dashboard import db as dbmod
from ccsync_dashboard import provision
from ccsync_dashboard.collector import Collector
from ccsync_dashboard.settings import Settings
from ccsync_dashboard.syncthing_client import SyncthingClient

from fake_syncthing import EDITOR2_ID, EDITOR_ID, SERVER_ID, FakeSyncthing


def mark(root, rel, slug=None, stfolder=True):
    d = root / rel
    d.mkdir(parents=True, exist_ok=True)
    if stfolder:
        # Real project dirs served by Syncthing carry .stfolder; the retarget
        # and self-heal guards both require it (see the retarget sanity-check
        # and marker self-heal findings).
        (d / ".stfolder").mkdir(exist_ok=True)
    provision.write_marker(d, slug or provision.slugify(rel))
    return d


def make_tree(root):
    mark(root, "2025/FF4/Nuclear")
    mark(root, "2026/FF5/Energy Transition")
    mark(root, "2026/Creator Profiles/Season 1")
    (root / "2026/.hidden/Secret").mkdir(parents=True)
    (root / "2026/bare-no-marker").mkdir(parents=True)          # invisible: no marker
    (root / "2026/FF5/Energy Transition/AE").mkdir()             # inside a project: pruned
    (root / "2025/FF4/notes.txt").parent.joinpath("notes.txt").write_text("x")
    return root


def test_scan_project_dirs_markers_any_depth(tmp_path):
    make_tree(tmp_path)
    # depth-4 project under a container
    mark(tmp_path, "2026/CCT/Creator Profiles/Season 2")
    # depth-1 project
    mark(tmp_path, "OneOffs")
    assert provision.scan_project_dirs(tmp_path) == [
        ("2025/FF4/Nuclear", "2025-ff4-nuclear"),
        ("2026/CCT/Creator Profiles/Season 2", "2026-cct-creator-profiles-season-2"),
        ("2026/Creator Profiles/Season 1", "2026-creator-profiles-season-1"),
        ("2026/FF5/Energy Transition", "2026-ff5-energy-transition"),
        ("OneOffs", "oneoffs"),
    ]


def test_scan_prunes_nested_markers_and_skips_containers(tmp_path):
    outer = mark(tmp_path, "2026/Show")
    mark(tmp_path, "2026/Show/Nested")     # nested: pruned by outer
    (tmp_path / "2026/Container").mkdir(parents=True)
    mark(tmp_path, "2026/Container/Real Project")
    scanned = provision.scan_project_dirs(tmp_path)
    rels = [r for r, _ in scanned]
    assert "2026/Show" in rels
    assert "2026/Show/Nested" not in rels
    assert "2026/Container" not in rels                 # container itself: no marker
    assert "2026/Container/Real Project" in rels


def test_scan_malformed_marker_yields_none_slug(tmp_path):
    d = tmp_path / "2026/Broken"
    d.mkdir(parents=True)
    (d / provision.MARKER_FILENAME).write_text("not json{", encoding="utf-8")
    assert provision.scan_project_dirs(tmp_path) == [("2026/Broken", None)]


@pytest.mark.parametrize("slug", [
    "../../etc", "a/b", "UPPER", "has space", "semi;colon", "quote\"", "a?b", "a#b",
])
def test_marker_with_an_invalid_slug_is_ignored(tmp_path, slug):
    """A marker is a plain JSON file on a share every editor can write, and
    its slug becomes a Syncthing FOLDER ID and a dashboard URL segment. Only
    server/common.py's charset (^[a-z0-9-]+$) is an identity."""
    d = tmp_path / "2026" / "Sketchy"
    d.mkdir(parents=True)
    (d / provision.MARKER_FILENAME).write_text(json.dumps({"slug": slug}), encoding="utf-8")
    assert provision.read_marker(d) is None
    # still visible to the scan (the file IS there) but with no identity, so
    # the collector logs and skips instead of provisioning it
    assert provision.scan_project_dirs(tmp_path) == [("2026/Sketchy", None)]


def test_marker_with_a_valid_slug_is_kept(tmp_path):
    d = tmp_path / "2026" / "Fine"
    d.mkdir(parents=True)
    provision.write_marker(d, "2026-fine")
    assert provision.read_marker(d) == "2026-fine"


def test_marked_descendants_and_ancestor(tmp_path):
    mark(tmp_path, "2026/CCT/Season 1")
    mark(tmp_path, "2026/CCT/Season 2")
    (tmp_path / "2026" / "CCT" / "Loose").mkdir()
    assert provision.marked_descendants(tmp_path / "2026" / "CCT") == \
        ["Season 1", "Season 2"]
    assert provision.marked_descendants(tmp_path / "2026" / "CCT" / "Season 1") == []
    assert provision.marked_ancestor(tmp_path, "2026/CCT/Season 1/AE") == "2026/CCT/Season 1"
    assert provision.marked_ancestor(tmp_path, "2026/CCT/Season 1") == "2026/CCT/Season 1"
    assert provision.marked_ancestor(
        tmp_path, "2026/CCT/Season 1", include_self=False) is None
    assert provision.marked_ancestor(tmp_path, "2026/CCT/Loose") is None


def test_slugify_matches_server_convention():
    assert provision.slugify("2026/Creator Profiles/Season 1") == "2026-creator-profiles-season-1"
    assert provision.slugify("2025/FF4/Nuclear") == "2025-ff4-nuclear"


def test_stignore_excludes_rclones_orphaned_partials(tmp_path):
    """KNOWN_BUGS B12: lane A runs rclone with --inplace=false, writing
    "<name>.<token>.partial" into the NAS project dir -- which is also a
    sendreceive Syncthing root. The video-extension patterns match by
    EXTENSION and matched none of them, so a 39 GB orphan left by an
    interrupted upload was indexed and fanned out over lane C to every editor
    with the project ticked, where nothing ever deletes it."""
    import fnmatch

    lines = provision.build_stignore_lines()
    assert provision.PARTIAL_IGNORE_LINES == ["(?i)**/*.partial", "(?i)*.partial"]
    for pattern in provision.PARTIAL_IGNORE_LINES:
        assert pattern in lines
    globs = [line[len("(?i)"):] for line in lines if "/" not in line]
    for name in ("A001_C001.braw.42048420.partial",
                 "A001_C001.braw.42048420.exp.partial"):
        assert any(fnmatch.fnmatch(name.lower(), g.lower()) for g in globs), name
    # the completed file (rclone renames the suffix away) still syncs
    assert not any(fnmatch.fnmatch("Timeline.drp", g)
                   for g in globs if g.endswith(".partial"))


@pytest.fixture
def fake():
    server = FakeSyncthing().start()
    yield server
    server.stop()


def collector_for(fake, tmp_path):
    settings = Settings(syncthing_url=fake.url, syncthing_api_key="k",
                        projects_dir=str(tmp_path), syncthing_data_prefix="/data/Projects")
    return Collector(settings, client=SyncthingClient(fake.url, "k", timeout=5))


def test_provision_creates_missing_folders(conn, fake, tmp_path):
    make_tree(tmp_path)
    collector = collector_for(fake, tmp_path)
    results = collector.run_cycle(conn, ["provision", "config"])
    assert results["provision"] is True and results["config"] is True

    by_id = {f["id"]: f for f in fake.state["folders"]}
    # The shared asset libraries are provisioned by the same cycle -- they
    # are Syncthing folders, but not projects (see the shared-folder tests
    # below).
    assert set(by_id) == {"2025-ff4-nuclear", "2026-creator-profiles-season-1",
                          "2026-ff5-energy-transition", provision.LUTS_FOLDER_ID}
    created = by_id["2026-ff5-energy-transition"]
    assert created["label"] == "2026/FF5/Energy Transition"
    assert created["path"] == "/data/Projects/2026/FF5/Energy Transition"
    assert created["type"] == "sendreceive"
    assert created["ignorePerms"] is True
    assert created["versioning"]["type"] == "staggered"
    # created UNSHARED: the selections table + enforce cycle drive sharing
    assert created["devices"] == []

    ignores = fake.state["ignores"]["2026-ff5-energy-transition"]
    assert "(?i)*.braw" in ignores and "(?i)**/Proxy/**" in ignores

    slugs = [p["slug"] for p in dbmod.fetch_projects(conn)]
    assert "2026-ff5-energy-transition" in slugs and "2026-creator-profiles-season-1" in slugs


def test_provision_uses_marker_slug_not_path_slug(conn, fake, tmp_path):
    """An adopted/moved project keeps its marker identity even when the
    path would slugify differently."""
    mark(tmp_path, "2026/CCT/Moved Show", slug="original-identity")
    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision"])
    by_id = {f["id"]: f for f in fake.state["folders"]}
    assert "original-identity" in by_id
    assert by_id["original-identity"]["label"] == "2026/CCT/Moved Show"


def test_provision_retargets_moved_project(conn, fake, tmp_path):
    """The live 2026-07-25 scenario: dir moved on the NAS, marker traveled
    with it, folder must be re-pointed in place (same slug -- ticks/history
    survive)."""
    make_tree(tmp_path)
    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision", "config"])

    # move Season 1 into a CCT container (marker travels with the dir)
    src = tmp_path / "2026/Creator Profiles/Season 1"
    dst = tmp_path / "2026/CCT/Creator Profiles/Season 1"
    dst.parent.mkdir(parents=True)
    src.rename(dst)

    collector.run_cycle(conn, ["provision"])
    by_id = {f["id"]: f for f in fake.state["folders"]}
    moved = by_id["2026-creator-profiles-season-1"]         # SAME slug
    assert moved["path"] == "/data/Projects/2026/CCT/Creator Profiles/Season 1"
    assert moved["label"] == "2026/CCT/Creator Profiles/Season 1"
    # projects row updated in the same cycle
    row = conn.execute("SELECT label, path FROM projects WHERE slug=?",
                       ("2026-creator-profiles-season-1",)).fetchone()
    assert row["label"] == "2026/CCT/Creator Profiles/Season 1"


def test_provision_self_heals_missing_markers(conn, fake, tmp_path):
    """A pre-marker-era folder (or a marker someone deleted) gets its marker
    rewritten from the Syncthing folder id -- but only because .stfolder
    proves Syncthing has been serving THIS directory."""
    d = tmp_path / "2025/FF4/Nuclear"
    d.mkdir(parents=True)          # NO marker; folder exists in fake config
    (d / ".stfolder").mkdir()
    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision"])
    assert provision.read_marker(d) == "2025-ff4-nuclear"


def test_self_heal_refuses_a_dir_without_stfolder(conn, fake, tmp_path):
    """A freshly re-created empty dir at the folder's old path must NOT be
    stamped with the project's identity: that is how the real (moved)
    directory becomes permanently invisible to discovery while the folder
    points at an empty dir -- which is then a mass-delete path."""
    d = tmp_path / "2025/FF4/Nuclear"
    d.mkdir(parents=True)          # no marker AND no .stfolder
    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision"])
    assert provision.read_marker(d) is None


def test_self_heal_refuses_when_the_slug_lives_elsewhere(conn, fake, tmp_path):
    """The exact live scenario: the real project was moved (its marker went
    with it) and someone re-created a directory at the old path. Even with a
    .stfolder there, stamping the slug would make two dirs claim it and
    deadlock the duplicate-slug branch forever."""
    old = tmp_path / "2025/FF4/Nuclear"          # folder's configured path
    old.mkdir(parents=True)
    (old / ".stfolder").mkdir()
    real = mark(tmp_path, "2026/CCT/Nuclear", slug="2025-ff4-nuclear")

    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision"])
    assert provision.read_marker(old) is None    # not stamped
    assert provision.read_marker(real) == "2025-ff4-nuclear"
    # ...and the folder was NOT retargeted either: the old path still exists,
    # so this could be a copy rather than a move.
    by_id = {f["id"]: f for f in fake.state["folders"]}
    assert by_id["2025-ff4-nuclear"]["path"] == "/data/Projects/2025/FF4/Nuclear"


def test_provision_duplicate_slug_dirs_skipped_or_current_kept(conn, fake, tmp_path):
    make_tree(tmp_path)
    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision"])
    # copy Nuclear elsewhere WITH its marker (same slug, two dirs)
    copy = tmp_path / "2026/Copies/Nuclear Copy"
    copy.mkdir(parents=True)
    provision.write_marker(copy, "2025-ff4-nuclear")

    collector.run_cycle(conn, ["provision"])
    by_id = {f["id"]: f for f in fake.state["folders"]}
    # the folder still points at the ORIGINAL (current-path preferred)
    assert by_id["2025-ff4-nuclear"]["path"] == "/data/Projects/2025/FF4/Nuclear"


def test_provision_repairs_missing_ignores_every_cycle(conn, fake, tmp_path):
    """A set_ignores that failed once (one dropped HTTP request) used to
    leave the folder with NO .stignore forever: it was only ever set in the
    create branch. Lane C is sendreceive, so an ignore-less folder indexes
    every .braw/.mov, re-downloads them to every ticked editor, and
    propagates an editor-side delete back to the NAS."""
    make_tree(tmp_path)
    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision"])
    slug = "2026-ff5-energy-transition"
    assert fake.state["ignores"][slug]        # set at creation

    # Simulate the transient failure's aftermath: ignores are gone.
    fake.state["ignores"][slug] = []
    collector.run_cycle(conn, ["provision"])
    assert fake.state["ignores"][slug] == provision.build_stignore_lines()

    # Partial/edited ignores are repaired too...
    fake.state["ignores"][slug] = ["(?i)*.braw"]
    collector.run_cycle(conn, ["provision"])
    assert fake.state["ignores"][slug] == provision.build_stignore_lines()

    # ...and the pre-existing folder that was never created by us (no ignores
    # at all in the fake's default state) is repaired as well.
    assert fake.state["ignores"]["2025-ff4-nuclear"] == provision.build_stignore_lines()


def test_ignore_repair_failure_fails_the_cycle_for_retry(conn, fake, tmp_path, monkeypatch):
    """A failed repair must be visible and retried, never swallowed."""
    make_tree(tmp_path)
    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision"])
    fake.state["ignores"]["2025-ff4-nuclear"] = []

    from ccsync_dashboard.syncthing_client import SyncthingError

    def boom(*_a, **_kw):
        raise SyncthingError("simulated set_ignores failure")

    monkeypatch.setattr(collector.client, "set_ignores", boom)
    assert collector.run_cycle(conn, ["provision"])["provision"] is False
    monkeypatch.undo()
    assert collector.run_cycle(conn, ["provision"])["provision"] is True
    assert fake.state["ignores"]["2025-ff4-nuclear"] == provision.build_stignore_lines()


def test_retarget_refused_when_the_old_dir_still_exists(conn, fake, tmp_path):
    """A COPY, not a move: retargeting onto the copy makes Syncthing treat
    every file that hasn't been copied yet as deleted, and propagate that to
    every editor sharing the folder."""
    make_tree(tmp_path)
    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision", "config"])

    import shutil
    src = tmp_path / "2026/Creator Profiles/Season 1"
    dst = tmp_path / "2026/CCT/Creator Profiles/Season 1"
    dst.parent.mkdir(parents=True)
    shutil.copytree(src, dst)      # copy: BOTH dirs now claim the slug

    collector.run_cycle(conn, ["provision"])
    by_id = {f["id"]: f for f in fake.state["folders"]}
    assert by_id["2026-creator-profiles-season-1"]["path"] == \
        "/data/Projects/2026/Creator Profiles/Season 1"


def test_retarget_refused_without_stfolder(conn, fake, tmp_path):
    """An interrupted move: .ccsync-project is tiny and copies first, so the
    provision cycle can fire while the media is still in flight. No
    .stfolder = don't touch it."""
    make_tree(tmp_path)
    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision", "config"])

    src = tmp_path / "2026/Creator Profiles/Season 1"
    dst = tmp_path / "2026/CCT/Creator Profiles/Season 1"
    dst.parent.mkdir(parents=True)
    src.rename(dst)
    import shutil
    shutil.rmtree(dst / ".stfolder")           # marker arrived, .stfolder didn't

    collector.run_cycle(conn, ["provision"])
    by_id = {f["id"]: f for f in fake.state["folders"]}
    assert by_id["2026-creator-profiles-season-1"]["path"] == \
        "/data/Projects/2026/Creator Profiles/Season 1"


def test_retarget_refused_when_media_is_still_in_flight(conn, fake, tmp_path):
    """Half-copied move: the new dir carries the marker and .stfolder but
    only a fraction of the media the last NAS inventory recorded."""
    make_tree(tmp_path)
    src = tmp_path / "2026/Creator Profiles/Season 1"
    for i in range(10):
        (src / f"clip{i}.mov").write_bytes(b"x")
    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision", "config", "inventory"])
    pid = conn.execute(
        "SELECT id FROM projects WHERE slug='2026-creator-profiles-season-1'").fetchone()[0]
    assert dbmod.fetch_nas_media_summary(conn, pid)["n_originals"] == 10

    dst = tmp_path / "2026/CCT/Creator Profiles/Season 1"
    dst.parent.mkdir(parents=True)
    dst.mkdir()
    (dst / ".stfolder").mkdir()
    provision.write_marker(dst, "2026-creator-profiles-season-1")
    (dst / "clip0.mov").write_bytes(b"x")      # 1 of 10 -- under the 50% floor
    import shutil
    shutil.rmtree(src)                         # old path gone: a real move

    collector.run_cycle(conn, ["provision"])
    by_id = {f["id"]: f for f in fake.state["folders"]}
    assert by_id["2026-creator-profiles-season-1"]["path"] == \
        "/data/Projects/2026/Creator Profiles/Season 1"

    # Once the rest of the media lands, the same cycle retargets normally.
    for i in range(1, 10):
        (dst / f"clip{i}.mov").write_bytes(b"x")
    collector.run_cycle(conn, ["provision"])
    by_id = {f["id"]: f for f in fake.state["folders"]}
    assert by_id["2026-creator-profiles-season-1"]["path"] == \
        "/data/Projects/2026/CCT/Creator Profiles/Season 1"


def test_provision_skips_a_marker_with_an_invalid_slug(conn, fake, tmp_path):
    """A hand-dropped {"slug": "../../etc"} must never reach add_folder --
    the slug becomes a Syncthing folder id and a dashboard URL segment."""
    make_tree(tmp_path)
    sketchy = tmp_path / "2026" / "Sketchy"
    sketchy.mkdir(parents=True)
    (sketchy / provision.MARKER_FILENAME).write_text(
        json.dumps({"slug": "../../etc"}), encoding="utf-8")

    collector = collector_for(fake, tmp_path)
    assert collector.run_cycle(conn, ["provision"])["provision"] is True
    ids = {f["id"] for f in fake.state["folders"]}
    assert "../../etc" not in ids
    assert not any("Sketchy" in str(f.get("path", "")) for f in fake.state["folders"])


def test_provision_refuses_a_marker_dropped_on_a_container(conn, fake, tmp_path):
    """The live shape of the bug: a .ccsync-project on Projects/2026/CCT/.
    scan_project_dirs prunes there, so the three real projects underneath
    vanish from discovery -- and add_folder on the container either nests
    Syncthing folders or 400s. Refuse, loudly, and leave the tree alone."""
    make_tree(tmp_path)
    container = tmp_path / "2026" / "CCT"
    mark(tmp_path, "2026/CCT/Season 1")
    mark(tmp_path, "2026/CCT/Season 2")
    provision.write_marker(container, "2026-cct")     # dropped on the container

    collector = collector_for(fake, tmp_path)
    assert collector.run_cycle(conn, ["provision"])["provision"] is True
    ids = {f["id"] for f in fake.state["folders"]}
    assert "2026-cct" not in ids
    # every other project in the tree was still provisioned in the same cycle
    assert {"2025-ff4-nuclear", "2026-ff5-energy-transition",
            "2026-creator-profiles-season-1"} <= ids


def test_provision_refuses_a_marker_inside_an_existing_project(conn, fake, tmp_path):
    """scan_project_dirs prunes at markers so this normally can't be
    scanned -- but the collector must not depend on the scanner's pruning
    for a rule that decides whether a Syncthing folder is created."""
    make_tree(tmp_path)
    nested = tmp_path / "2026" / "FF5" / "Energy Transition" / "AE"
    provision.write_marker(nested, "2026-ff5-energy-transition-ae")

    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision"])
    assert collector._creatable(
        "2026-ff5-energy-transition-ae",
        "2026/FF5/Energy Transition/AE", tmp_path) is False
    assert "2026-ff5-energy-transition-ae" not in {f["id"] for f in fake.state["folders"]}


def test_one_bad_folder_does_not_abort_the_whole_provision_cycle(conn, fake, tmp_path,
                                                                monkeypatch):
    """add_folder throwing on ONE project used to abort the cycle before
    every later project was even looked at -- so a single bad marker froze
    provisioning fleet-wide, every 5 minutes, forever. Each slug is isolated;
    the cycle is still recorded FAILED so it retries."""
    make_tree(tmp_path)
    collector = collector_for(fake, tmp_path)
    real_add = collector.client.add_folder

    def boom(folder):
        # 2026-creator-profiles-season-1 sorts BEFORE 2026-ff5-energy-transition,
        # so the later folder proves the loop kept going.
        if folder["id"] == "2026-creator-profiles-season-1":
            raise RuntimeError("simulated syncthing 400")
        return real_add(folder)

    monkeypatch.setattr(collector.client, "add_folder", boom)
    assert collector.run_cycle(conn, ["provision"])["provision"] is False
    ids = {f["id"] for f in fake.state["folders"]}
    assert "2026-creator-profiles-season-1" not in ids
    # ...and the other project was still created despite that failure
    assert "2026-ff5-energy-transition" in ids
    run = conn.execute(
        "SELECT error FROM poll_runs WHERE kind='provision' ORDER BY id DESC LIMIT 1").fetchone()
    assert "2026-creator-profiles-season-1" in run["error"]

    monkeypatch.undo()
    assert collector.run_cycle(conn, ["provision"])["provision"] is True


def test_provision_never_deletes_folders(conn, fake, tmp_path):
    make_tree(tmp_path)
    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision"])
    import shutil
    shutil.rmtree(tmp_path / "2025/FF4/Nuclear")
    collector.run_cycle(conn, ["provision"])
    assert any(f["id"] == "2025-ff4-nuclear" for f in fake.state["folders"])


def test_provision_is_idempotent_and_preserves_existing(conn, fake, tmp_path):
    make_tree(tmp_path)
    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision"])
    snapshot = [f["id"] for f in fake.state["folders"]]
    put_calls_before = len(fake.state.get("put_folder_calls", []))
    collector.run_cycle(conn, ["provision"])
    assert [f["id"] for f in fake.state["folders"]] == snapshot
    # no retarget/label PUTs on a stable tree
    assert len(fake.state.get("put_folder_calls", [])) == put_calls_before


def test_provision_disabled_when_no_projects_dir(conn, fake):
    settings = Settings(syncthing_url=fake.url, syncthing_api_key="k")  # projects_dir=""
    collector = Collector(settings, client=SyncthingClient(fake.url, "k", timeout=5))
    results = collector.run_cycle(conn, ["provision"])
    assert results["provision"] is True
    assert conn.execute("SELECT COUNT(*) FROM poll_runs WHERE kind='provision'").fetchone()[0] == 0


def test_provision_fails_loud_on_missing_dir(conn, fake, tmp_path):
    collector = collector_for(fake, tmp_path / "nope")
    results = collector.run_cycle(conn, ["provision"])
    assert results["provision"] is False
    run = conn.execute("SELECT * FROM poll_runs WHERE kind='provision'").fetchone()
    assert "does not exist" in run["error"]


def test_provision_repairs_wan_puller_tuning_on_existing_folders(conn, fake, tmp_path):
    """KNOWN_BUGS B19: `setup_syncthing_folder.py --force` PUTs a folder object
    built from scratch, so it reset maxConcurrentWrites/pullerMaxPendingKiB to
    Syncthing's defaults permanently -- and unlike .stignore there was no
    repair pass, so re-forcing a folder to fix its path left that project
    pulling at maxConcurrentWrites=2 over the WAN forever, nothing logged.
    Folders created by the server script rather than by the collector never
    had the tuning at all -- which is the state the fake starts in."""
    from ccsync_dashboard.collector import folder_tuning_drift

    make_tree(tmp_path)
    collector = collector_for(fake, tmp_path)
    slug = "2025-ff4-nuclear"
    live = next(f for f in fake.state["folders"] if f["id"] == slug)
    assert folder_tuning_drift(live)          # the fake's folder has neither knob

    collector.run_cycle(conn, ["provision"])
    live = next(f for f in fake.state["folders"] if f["id"] == slug)
    assert live["maxConcurrentWrites"] == 32
    assert live["pullerMaxPendingKiB"] == 65536
    # the repair preserved everything else about the folder
    assert live["label"] == "2025/FF4/Nuclear"
    assert live["path"] == "/data/Projects/2025/FF4/Nuclear"
    assert {d["deviceID"] for d in live["devices"]} == {SERVER_ID, EDITOR_ID, EDITOR2_ID}

    # ...and it converges: a second cycle writes nothing.
    fake.state.pop("put_folder_calls", None)
    collector.run_cycle(conn, ["provision"])
    assert "put_folder_calls" not in fake.state


def test_a_force_reset_is_repaired_next_cycle(conn, fake, tmp_path):
    make_tree(tmp_path)
    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision"])
    slug = "2026-ff5-energy-transition"

    # simulate `setup_syncthing_folder.py --force`: the knobs are gone
    for folder in fake.state["folders"]:
        if folder["id"] == slug:
            folder.pop("maxConcurrentWrites", None)
            folder.pop("pullerMaxPendingKiB", None)
    collector.run_cycle(conn, ["provision"])
    repaired = next(f for f in fake.state["folders"] if f["id"] == slug)
    assert repaired["maxConcurrentWrites"] == 32
    assert repaired["pullerMaxPendingKiB"] == 65536


def test_provision_refuses_a_second_folder_over_the_same_directory(conn, fake, tmp_path):
    """The folder-id divergence (KNOWN_BUGS §4 minors): the collector keys on
    the marker's immutable slug, `setup_syncthing_folder.py` derives the id
    with slugify(rel). For a MOVED project those disagree, so an admin
    repairing ignores with the server script creates a SECOND Syncthing
    folder over the same directory -- one no editor is shared with, which
    fails the collector every cycle. Never add to the confusion."""
    make_tree(tmp_path)
    # the dir carries an adopted marker whose slug is not slugify(rel)...
    provision.write_marker(tmp_path / "2026/FF5/Energy Transition", "adopted-slug")
    # ...and a folder created the server script's way already serves it
    fake.state["folders"].append({
        "id": "2026-ff5-energy-transition", "label": "2026/FF5/Energy Transition",
        "path": "/data/Projects/2026/FF5/Energy Transition",
        "devices": [{"deviceID": SERVER_ID}, {"deviceID": EDITOR_ID}],
        "type": "sendreceive", "ignorePerms": True,
    })
    collector = collector_for(fake, tmp_path)
    collector.run_cycle(conn, ["provision"])

    ids = [f["id"] for f in fake.state["folders"]]
    assert "adopted-slug" not in ids                  # nothing was created
    assert ids.count("2026-ff5-energy-transition") == 1
    # the existing folder is untouched, editors still shared
    live = next(f for f in fake.state["folders"] if f["id"] == "2026-ff5-energy-transition")
    assert {d["deviceID"] for d in live["devices"]} == {SERVER_ID, EDITOR_ID}


def test_duplicate_path_folder_ignores_the_folder_itself():
    from ccsync_dashboard.collector import Collector

    folders = {"a": {"path": "/data/Projects/X"}, "b": {"path": "/data/Projects/Y/"}}
    assert Collector._duplicate_path_folder("a", "/data/Projects/X", folders) is None
    assert Collector._duplicate_path_folder("c", "/data/Projects/X", folders) == "a"
    assert Collector._duplicate_path_folder("c", "/data/Projects/Y", folders) == "b"
    assert Collector._duplicate_path_folder("c", "/data/Projects/Z", folders) is None
