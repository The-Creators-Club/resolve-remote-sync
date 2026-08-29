"""Getting something back without a root shell (SYS-15, wave 5).

Pins the four properties the finding is about, not the wording:

* a restore writes ONLY into `<project>/.restored-<ts>/` and never touches,
  moves or deletes anything that was already on the server -- which is what
  makes choosing the wrong snapshot cost disk space and nothing else;
* a restore whose snapshot, project or snapshot mount cannot be identified is
  REFUSED, with a sentence, rather than guessing at a path;
* the runbook prints no command built on a fact this server could not verify
  (a generated `zfs rollback` with a guessed dataset in it is worse than no
  command at all);
* a drill records a date the protection panel then reads, and a drill that
  fails records nothing there;
* `commands.resolve_undo` is delivered and acknowledged on the same contract
  `file_moves` uses, including `retrying`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ccsync_dashboard import auth
from ccsync_dashboard import db as dbmod
from ccsync_dashboard import protection, recovery
from ccsync_dashboard.app import create_app
from ccsync_dashboard.settings import Settings

SECRET = "s"
TOKEN = "tok"
NOW = "2026-08-29T12:00:00+00:00"


# --------------------------------------------------------------- fixtures

def _tree(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


@pytest.fixture
def site(tmp_path):
    """A live Projects tree, a snapshot mount beside it, and a project row.

    The snapshot holds a file the live tree has lost and one whose contents
    differ -- the two cases a restore has to tell apart."""
    projects = tmp_path / "projects"
    snaps = tmp_path / "snapshots"
    _tree(projects, {
        "2026/One/notes.txt": "live",
        "2026/One/Subs/ep3.srt": "live subs",
    })
    _tree(snaps / "ccsync-20260829-1100" / "2026/One", {
        "notes.txt": "older",
        "Subs/ep3.srt": "live subs",
        "Subs/ep4.srt": "the one that was deleted",
    })
    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                        report_token=TOKEN, admin_users=frozenset({"owen"}),
                        projects_dir=str(projects))
    conn = dbmod.connect(tmp_path / "d.db")
    dbmod.migrate(conn)
    dbmod.upsert_project(conn, "one", "2026/One", "/x", NOW)
    conn.commit()
    env = {recovery.ENV_SNAPSHOT_DIR: str(snaps)}
    yield {"settings": settings, "conn": conn, "projects": projects,
           "snaps": snaps, "env": env, "tmp": tmp_path}
    conn.close()


def _no_nas_snapshot(_settings, _label):
    """The pre-restore NAS snapshot, stubbed. Best effort in production; a
    test must not be able to reach a real NAS."""
    return {"ok": False, "reason": "no NAS in this test"}


# ------------------------------------------------------- (a) the restore

def test_a_restore_writes_only_into_the_quarantine_folder(site):
    """THE property of SYS-15(a). Everything that was on the server before is
    byte-for-byte identical afterwards, and everything restored is under one
    new `.restored-` folder."""
    before = {p: p.read_bytes() for p in site["projects"].rglob("*") if p.is_file()}

    result = recovery.restore_into_quarantine(
        site["settings"], site["conn"], "one", "ccsync-20260829-1100", "owen",
        env=site["env"], now=NOW, snapshot_before=_no_nas_snapshot)

    assert result["ok"] and result["files"] == 1
    after = {p: p.read_bytes() for p in site["projects"].rglob("*")
             if p.is_file() and recovery.QUARANTINE_PREFIX not in str(p)}
    assert after == before, "a restore changed a file that was already there"
    quarantine = Path(result["directory"])
    assert quarantine.name.startswith(recovery.QUARANTINE_PREFIX)
    assert quarantine.parent == site["projects"] / "2026" / "One"
    assert (quarantine / "Subs" / "ep4.srt").read_text() == "the one that was deleted"
    # ...and the file that exists but differs is NOT brought back by default:
    # that one is a judgement, and the default is the safe direction.
    assert not (quarantine / "notes.txt").exists()


def test_the_quarantine_folder_starts_with_a_dot_so_it_is_not_a_second_project(site):
    """A restored project carries a copy of its own `.ccsync-project` marker.
    provision's walk prunes dot-directories, which is the only reason a
    restore cannot raise `duplicate_slug_dirs` -- a recovery tool that started
    a new incident during an existing one."""
    assert recovery.QUARANTINE_PREFIX.startswith(".")

    from ccsync_dashboard import provision

    _tree(site["projects"] / "2026/One", {".ccsync-project": json.dumps({"slug": "one"})})
    _tree(site["snaps"] / "ccsync-20260829-1100" / "2026/One",
          {".ccsync-project": json.dumps({"slug": "one"})})
    recovery.restore_into_quarantine(
        site["settings"], site["conn"], "one", "ccsync-20260829-1100", "owen",
        env=site["env"], now=NOW, snapshot_before=_no_nas_snapshot)

    found = provision.scan_project_dirs(site["projects"])
    assert [rel for rel, _slug in found] == ["2026/One"]


def test_a_second_restore_never_writes_into_the_first_ones_folder(site):
    """Nothing here merges into a directory that is already there."""
    recovery.restore_into_quarantine(
        site["settings"], site["conn"], "one", "ccsync-20260829-1100", "owen",
        env=site["env"], now=NOW, snapshot_before=_no_nas_snapshot)
    with pytest.raises(recovery.RecoveryError) as exc:
        recovery.restore_into_quarantine(
            site["settings"], site["conn"], "one", "ccsync-20260829-1100", "owen",
            env=site["env"], now=NOW, snapshot_before=_no_nas_snapshot)
    # The second call finds nothing missing any more (the first restore did
    # not change the live tree, so this is the "nothing to restore" refusal),
    # and either way it is a refusal with a sentence in it.
    assert "restore" in str(exc.value).lower()


def test_a_restore_refuses_when_the_snapshot_cannot_be_identified(site):
    for snapshot in ("", "..", "no-such-snapshot", "../../etc"):
        with pytest.raises(recovery.RecoveryError):
            recovery.restore_into_quarantine(
                site["settings"], site["conn"], "one", snapshot, "owen",
                env=site["env"], now=NOW, snapshot_before=_no_nas_snapshot)


def test_a_restore_refuses_when_this_server_cannot_see_any_snapshots(site):
    """Unset is "this server was never told", never "there are none" -- and it
    is a refusal naming the variable, not a traceback."""
    with pytest.raises(recovery.RecoveryError) as exc:
        recovery.restore_into_quarantine(
            site["settings"], site["conn"], "one", "ccsync-20260829-1100", "owen",
            env={}, now=NOW, snapshot_before=_no_nas_snapshot)
    assert recovery.ENV_SNAPSHOT_DIR in str(exc.value)


def test_a_restore_refuses_a_project_this_server_does_not_know(site):
    with pytest.raises(recovery.RecoveryError) as exc:
        recovery.restore_into_quarantine(
            site["settings"], site["conn"], "ghost", "ccsync-20260829-1100", "owen",
            env=site["env"], now=NOW, snapshot_before=_no_nas_snapshot)
    assert exc.value.status == 404


def test_a_restore_refuses_when_the_tree_is_not_mounted(site, tmp_path):
    settings = Settings(db_path=str(tmp_path / "d.db"), session_secret=SECRET,
                        projects_dir="")
    with pytest.raises(recovery.RecoveryError) as exc:
        recovery.restore_into_quarantine(
            settings, site["conn"], "one", "ccsync-20260829-1100", "owen",
            env=site["env"], now=NOW, snapshot_before=_no_nas_snapshot)
    assert exc.value.status == 409


def test_the_preview_names_what_is_missing_and_changes_nothing(site):
    before = sorted(p.name for p in site["projects"].rglob("*"))
    view = recovery.preview_restore(site["settings"], site["conn"], "one",
                                    "ccsync-20260829-1100", site["env"])
    assert view["missing_count"] == 1
    assert view["missing"][0]["rel"] == "Subs/ep4.srt"
    assert view["changed_count"] == 1          # notes.txt differs in size
    assert sorted(p.name for p in site["projects"].rglob("*")) == before


def test_including_the_changed_ones_still_writes_only_into_quarantine(site):
    result = recovery.restore_into_quarantine(
        site["settings"], site["conn"], "one", "ccsync-20260829-1100", "owen",
        include_changed=True, env=site["env"], now=NOW,
        snapshot_before=_no_nas_snapshot)
    assert result["files"] == 2
    assert (site["projects"] / "2026/One/notes.txt").read_text() == "live"


# ---------------------------------------------------------- (d) the drill

def test_a_drill_records_a_date_the_protection_panel_reads(site):
    """SYS-15(d) closing SYS-14's MISSING line: the panel reads a DATE and
    does not care who put it there."""
    conn = site["conn"]
    assert protection.read_acks(conn).get(protection.ACK_RESTORE_DRILL) is None

    result = recovery.run_drill(site["settings"], conn, "owen",
                               env=site["env"], now=NOW)

    assert result["ok"] is True
    assert protection.read_acks(conn)[protection.ACK_RESTORE_DRILL]["date"] == "2026-08-29"
    line = protection._check_restore_drill(protection.Ctx(
        conn, site["settings"], NOW, tasks_fn=lambda: None, env={}))
    assert line.state == protection.OK


def test_a_drill_leaves_nothing_behind(site):
    recovery.run_drill(site["settings"], site["conn"], "owen",
                       env=site["env"], now=NOW)
    scratch = Path(site["settings"].db_path).parent / recovery.DRILL_DIR_NAME
    assert not any(scratch.iterdir()) if scratch.is_dir() else True
    # ...and nothing was written into the tree.
    assert sorted(p.name for p in site["projects"].rglob("*")) == [
        "2026", "One", "Subs", "ep3.srt", "notes.txt"]


def test_a_drill_that_cannot_run_records_no_date(site):
    """A backup nobody has restored from is a hypothesis, and a REHEARSAL
    THAT DID NOT HAPPEN must leave that line MISSING rather than green."""
    with pytest.raises(recovery.RecoveryError):
        recovery.run_drill(site["settings"], site["conn"], "owen", env={}, now=NOW)
    assert protection.read_acks(site["conn"]).get(protection.ACK_RESTORE_DRILL) is None


# -------------------------------------------------------- (c) the runbook

def _facts(site, *, verified_nas=True, tasks=None, env=None):
    return recovery.gather_facts(
        site["settings"], site["conn"],
        env=env if env is not None else site["env"],
        tasks_fn=lambda: tasks,
        nas_probe=(lambda: {"version": "TrueNAS-24"}) if verified_nas else (lambda: None))


def test_the_runbook_refuses_to_print_a_command_built_on_a_guess(site):
    """THE finding. Nothing anywhere prints `zfs rollback tank/...` unless
    this server has confirmed that dataset from the NAS itself."""
    facts = _facts(site, verified_nas=True, tasks=None)
    plan = recovery.plan("whole_tree", facts)

    kinds = [step["kind"] for step in plan["steps"]]
    assert "refusal" in kinds and "command" not in kinds
    printed = " ".join(line for step in plan["steps"] for line in step["commands"])
    assert "zfs rollback" not in printed
    refusal = next(s for s in plan["steps"] if s["kind"] == "refusal")
    assert "project tree" in refusal["body"]


def test_a_dataset_nothing_snapshots_is_not_a_verified_dataset(site):
    """CR-10, as a fact: `/mnt/tank/apps` is a plain DIRECTORY on this
    fleet's NAS, and the two `cp` lines in BACKUP_RESTORE.md differ by exactly
    that. A variable somebody typed is not evidence."""
    env = {**site["env"], protection.ENV_APPS_DATASET: "tank/apps",
           protection.ENV_TREE_DATASET: "tank/media"}
    facts = _facts(site, tasks=[{"dataset": "tank/media", "enabled": True}], env=env)

    assert facts["tree_dataset"].verified is True
    assert facts["apps_dataset"].verified is False
    assert "none of them covers" in facts["apps_dataset"].why_not


def test_a_verified_fact_is_substituted_into_the_printed_command(site):
    env = {**site["env"], protection.ENV_TREE_DATASET: "tank/media"}
    facts = _facts(site, tasks=[{"dataset": "tank", "enabled": True, "recursive": True}],
                   env=env)
    plan = recovery.plan("whole_tree", facts)

    printed = " ".join(line for step in plan["steps"] for line in step["commands"])
    assert "zfs rollback -r tank/media@<SNAPSHOT>" in printed
    assert "{tree_dataset}" not in printed


def test_a_nas_that_does_not_answer_leaves_the_platform_unverified(site):
    """`chown` is REQUIRED on TrueNAS and DELETES the share's ACL on DSM, so a
    platform this server could not confirm prints nothing at all."""
    env = {**site["env"], protection.ENV_TREE_DATASET: "tank/media"}
    facts = _facts(site, verified_nas=False,
                   tasks=[{"dataset": "tank/media", "enabled": True}], env=env)

    assert facts["platform"].verified is False
    plan = recovery.plan("whole_tree", facts)
    assert not any(step["commands"] for step in plan["steps"])


def test_every_problem_builds_a_plan_with_no_placeholder_left_in_it(site):
    """Every registry row, over both fact worlds: nothing renders `{pool}` at
    an owner, and a plan is never empty."""
    for verified in (True, False):
        facts = _facts(site, verified_nas=verified,
                       tasks=[{"dataset": "tank", "enabled": True, "recursive": True}],
                       env={**site["env"], protection.ENV_TREE_DATASET: "tank/media",
                            protection.ENV_APPS_DATASET: "tank/apps",
                            recovery.ENV_CONTAINER_NAME: "ccsync-dashboard"})
        for problem in recovery.PROBLEMS:
            plan = recovery.plan(problem.key, facts)
            assert plan["steps"]
            for step in plan["steps"]:
                for line in step["commands"]:
                    assert "{" not in line, f"{problem.key} printed a placeholder"


def test_the_page_renders_with_no_nas_and_no_snapshots(site, tmp_path):
    """The page an owner opens after losing something is the last page in this
    product that may fail to render."""
    view = recovery.page_view(site["settings"], site["conn"], "project", env={})
    assert view["snapshots"] == [] and view["snapshots_why_not"]
    assert view["plan"]["steps"]
    assert any(not f["verified"] for f in view["facts"])


# ------------------------------------------- (b) the admin-side undo, wired

@pytest.fixture
def env(tmp_path):
    db_path = tmp_path / "m.db"
    settings = Settings(db_path=str(db_path), session_secret=SECRET, report_token=TOKEN,
                        admin_users=frozenset({"owen"}))
    app = create_app(settings)
    with TestClient(app) as client:
        conn = dbmod.connect(db_path)
        client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "owen"))
        yield client, conn
        conn.close()


def _hdr(editor):
    return {"X-CCSync-Token": TOKEN,
            "X-CCSync-Identity": auth.make_identity_token(SECRET, editor)}


def _report(client, **extra):
    body = {"editor_name": "ruskin", "machine": "DESKTOP-1",
            "reported_at": NOW, "lanes": []}
    body.update(extra)
    resp = client.post("/api/v1/report", json=body, headers=_hdr("ruskin"))
    assert resp.status_code == 200, resp.text
    return resp.json()


JOURNAL = {"id": "Season_1_EP3/20260829-1042.json", "project": "Season 1 EP3",
           "started": "2026-08-29T10:42:00+00:00", "entries": 158,
           "sources": "auto_canonical"}


def test_a_machine_reports_what_it_can_undo_and_an_admin_can_ask_for_it(env):
    client, conn = env
    _report(client, resolve_journals=[JOURNAL])

    listed = client.get("/api/v1/admin/machines/ruskin/DESKTOP-1/resolve-journals")
    assert listed.status_code == 200
    assert listed.json()["journals"][0]["entries"] == 158

    asked = client.post("/api/v1/admin/machines/ruskin/DESKTOP-1/resolve-undo",
                        params={"journal": JOURNAL["id"]})
    assert asked.status_code == 200, asked.text

    command = _report(client)["commands"]["resolve_undo"][0]
    assert command["journal"] == JOURNAL["id"]
    assert command["requested_by"] == "owen"
    assert command["project"] == "Season 1 EP3"


def test_the_undo_keeps_riding_every_report_until_it_is_answered(env):
    """The file_moves rule, not the resume_lane_b rule: an undo an admin asked
    for while Resolve was closed must not be lost, and the companion refuses
    to replay a journal twice."""
    client, conn = env
    _report(client, resolve_journals=[JOURNAL])
    client.post("/api/v1/admin/machines/ruskin/DESKTOP-1/resolve-undo",
                params={"journal": JOURNAL["id"]})

    first = _report(client)["commands"]["resolve_undo"][0]
    assert _report(client)["commands"]["resolve_undo"][0]["id"] == first["id"]

    reply = _report(client, resolve_undo_applied=[
        {"id": first["id"], "ok": True, "detail": "put 158 clip path(s) back"}])
    assert "resolve_undo" not in reply["commands"]

    rows = dbmod.resolve_undos_for_machine(conn, "ruskin", "DESKTOP-1")
    assert rows[0]["ok"] == 1 and rows[0]["applied_at"]


def test_retrying_records_the_attempt_without_retiring_the_command(env):
    """An undo refused because the wrong project is open is going to work
    later: retiring it there would leave the wrong paths in place with the
    admin believing they had been put back."""
    client, conn = env
    _report(client, resolve_journals=[JOURNAL])
    client.post("/api/v1/admin/machines/ruskin/DESKTOP-1/resolve-undo",
                params={"journal": JOURNAL["id"]})
    command = _report(client)["commands"]["resolve_undo"][0]

    reply = _report(client, resolve_undo_applied=[
        {"id": command["id"], "ok": False, "state": "retrying", "attempts": 1,
         "detail": "Resolve is not running on this computer"}])

    assert reply["commands"]["resolve_undo"][0]["id"] == command["id"]
    row = dbmod.resolve_undos_for_machine(conn, "ruskin", "DESKTOP-1")[0]
    assert row["applied_at"] is None and row["state"] == "retrying"


def test_an_undo_naming_a_journal_the_machine_never_reported_is_a_404(env):
    client, _conn = env
    _report(client, resolve_journals=[JOURNAL])
    resp = client.post("/api/v1/admin/machines/ruskin/DESKTOP-1/resolve-undo",
                       params={"journal": "Other/20260101-0000.json"})
    assert resp.status_code == 404


def test_only_an_admin_can_undo_somebody_elses_clip_paths(env):
    client, _conn = env
    _report(client, resolve_journals=[JOURNAL])
    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "ruskin"))
    resp = client.post("/api/v1/admin/machines/ruskin/DESKTOP-1/resolve-undo",
                       params={"journal": JOURNAL["id"]})
    assert resp.status_code == 403


def test_the_recovery_page_renders_for_an_admin_and_not_for_an_editor(env):
    """The page an owner opens after losing something. It renders on a
    deployment with no NAS, no snapshot mount and nothing recorded, which is
    every deployment before this ships."""
    client, _conn = env
    page = client.get("/admin/recovery?problem=project")
    assert page.status_code == 200
    assert "GET SOMETHING BACK" in page.text
    assert "WHAT WENT WRONG" in page.text

    client.cookies.set(auth.COOKIE_NAME, auth.make_session_cookie(SECRET, "ruskin"))
    assert client.get("/admin/recovery").status_code in (302, 303, 403)


def test_the_drill_button_says_why_it_cannot_run_rather_than_500ing(env):
    client, _conn = env
    resp = client.post("/partials/admin/recovery/drill", data={"problem": ""})
    assert resp.status_code == 200
    assert recovery.ENV_SNAPSHOT_DIR in resp.text


def test_a_report_with_no_journals_section_keeps_the_last_list(env):
    """ABSENT IS NOT EMPTY. A companion too old to report journals must not
    empty the list an admin is looking at."""
    client, conn = env
    _report(client, resolve_journals=[JOURNAL])
    _report(client)
    assert dbmod.machine_resolve_journals(conn, "ruskin", "DESKTOP-1")[0]["id"] \
        == JOURNAL["id"]
    _report(client, resolve_journals=[])
    assert dbmod.machine_resolve_journals(conn, "ruskin", "DESKTOP-1") == []
