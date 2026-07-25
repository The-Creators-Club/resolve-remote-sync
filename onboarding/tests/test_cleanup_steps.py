"""Tests for the all-in-one installer's clean-slate, config-merge, and
base-mode install helpers (steps.py additions, 2026-07) -- same
injected-fake style as test_steps.py: nothing here touches the registry,
scheduled tasks, real processes, or any path outside tmp_path."""
from __future__ import annotations

from pathlib import Path

import steps


# -- build_cleanup_plan -------------------------------------------------------


class TestBuildCleanupPlan:
    def _plan(self, role="editor", local_root=None, run_value=None,
              config_root=None, existing=()):
        existing_norm = {str(p).lower() for p in existing}
        return steps.build_cleanup_plan(
            role,
            local_root,
            read_run_value=lambda name: run_value,
            read_local_root=lambda: config_root,
            exists=lambda p: str(p).lower() in existing_norm,
        )

    def test_editor_role_unmounts_p_base_does_not(self):
        assert self._plan(role="editor").unmount_p is True
        assert self._plan(role="base").unmount_p is False

    def test_run_values_and_tasks_always_listed(self):
        plan = self._plan()
        assert plan.run_values == steps.ALL_RUN_VALUES
        assert plan.scheduled_tasks == [steps.SUBST_TASK_NAME]
        assert "ccsync-companion" in plan.run_values  # base-rig manual entry

    def test_exe_paths_only_existing_files(self):
        target = steps.COMPANION_BIN_DIR / "ccsync-companion.exe"
        old = steps.COMPANION_BIN_DIR / "ccsync-companion.exe.old"
        plan = self._plan(existing=[target, old])
        assert target in plan.exe_paths
        assert old in plan.exe_paths
        assert len(plan.exe_paths) == 2

    def test_exe_candidates_cover_historical_locations(self):
        locations = [
            Path(r"C:\Creators_Club") / "ccsync-companion.exe",
            Path("P:/") / "ccsync-companion.exe",
            Path.home() / ".ccsync" / "bin" / "ccsync-companion.exe",
        ]
        plan = self._plan(role="editor", existing=locations)
        assert set(locations) <= set(plan.exe_paths)

    def test_base_role_never_reaches_into_p_drive(self):
        p_exe = Path("P:/") / "ccsync-companion.exe"
        plan = self._plan(role="base", existing=[p_exe])
        assert p_exe not in plan.exe_paths

    def test_run_value_dir_is_scanned(self):
        stray = Path(r"F:\Creators_Club") / "ccsync-companion.exe"
        plan = self._plan(run_value=r'"F:\Creators_Club\ccsync-companion.exe"',
                          existing=[stray])
        assert stray in plan.exe_paths

    def test_wscript_run_value_contributes_nothing(self):
        plan = self._plan(run_value=r'wscript.exe "C:\x\ccsync-companion.vbs"',
                          existing=[Path(r"C:\x") / "ccsync-companion.exe"])
        assert plan.exe_paths == []

    def test_config_local_root_is_scanned(self):
        stray = Path(r"D:\CC") / "ccsync-companion.new.exe"
        plan = self._plan(config_root=r"D:\CC", existing=[stray])
        assert stray in plan.exe_paths

    def test_never_lists_preserved_tools(self):
        rclone = steps.COMPANION_BIN_DIR / "rclone.exe"
        syncthing = steps.COMPANION_BIN_DIR / "syncthing.exe"
        plan = self._plan(existing=[rclone, syncthing])
        assert plan.exe_paths == []

    def test_duplicate_dirs_deduped(self):
        target = Path(r"C:\Creators_Club") / "ccsync-companion.exe"
        plan = self._plan(local_root=r"C:\Creators_Club", existing=[target])
        assert plan.exe_paths.count(target) == 1


# -- execute_cleanup ----------------------------------------------------------


class _FakeCompleted:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = ""


class TestExecuteCleanup:
    def _run_plan(self, plan, deleted=None, locked=None, run_calls=None,
                  removed_values=None):
        deleted = deleted if deleted is not None else []
        locked = locked or set()
        run_calls = run_calls if run_calls is not None else []
        removed_values = removed_values if removed_values is not None else []

        def fake_run(cmd, **kw):
            run_calls.append(cmd)
            return _FakeCompleted()

        def fake_delete(path):
            if str(path) in locked:
                raise OSError("locked")
            deleted.append(Path(path))

        logs = []
        warnings = steps.execute_cleanup(
            plan,
            log=logs.append,
            run=fake_run,
            delete_file=fake_delete,
            delete_run_value=lambda name: removed_values.append(name) or True,
            sleep=lambda s: None,
            now=lambda: 1234567890.0,
            p_drive_exists=lambda: False,
        )
        return warnings, deleted, run_calls, removed_values, logs

    def test_full_ordering_kill_then_registry_then_files_then_drive(self):
        exe = Path(r"C:\x\ccsync-companion.exe")
        plan = steps.CleanupPlan(
            kill_process_names=["ccsync-companion"],
            kill_pythonw_launcher=False,
            run_values=["CCSyncCompanion"],
            scheduled_tasks=["CCSync-SubstP"],
            exe_paths=[exe],
            unmount_p=True,
        )
        warnings, deleted, run_calls, removed_values, _logs = self._run_plan(plan)
        assert warnings == []
        assert deleted == [exe]
        assert removed_values == ["CCSyncCompanion"]
        joined = [" ".join(c) for c in run_calls]
        kill_idx = next(i for i, c in enumerate(joined) if c.startswith("taskkill"))
        task_idx = next(i for i, c in enumerate(joined) if "schtasks" in c)
        subst_idx = next(i for i, c in enumerate(joined) if "subst" in c)
        net_idx = next(i for i, c in enumerate(joined) if "net use" in c)
        assert kill_idx < task_idx < subst_idx < net_idx
        assert "P:" in joined[subst_idx]

    def test_no_unmount_for_base_plan(self):
        plan = steps.CleanupPlan(kill_process_names=[], kill_pythonw_launcher=False,
                                 unmount_p=False)
        _w, _d, run_calls, _rv, _logs = self._run_plan(plan)
        assert not any("subst" in " ".join(c) or "net use" in " ".join(c)
                       for c in run_calls)

    def test_locked_exe_renamed_stale_with_warning(self, monkeypatch):
        exe = Path(r"C:\x\ccsync-companion.exe")
        replaced = []
        monkeypatch.setattr(steps.os, "replace", lambda a, b: replaced.append((a, b)))
        plan = steps.CleanupPlan(kill_process_names=[], kill_pythonw_launcher=False,
                                 exe_paths=[exe])
        warnings, deleted, _rc, _rv, _logs = self._run_plan(plan, locked={str(exe)})
        assert deleted == []
        assert replaced and str(replaced[0][1]).endswith(".stale-1234567890")
        assert any("locked" in w for w in warnings)

    def test_never_raises_even_when_everything_fails(self):
        plan = steps.CleanupPlan(
            kill_process_names=["ccsync-companion"],
            run_values=["CCSyncCompanion"],
            scheduled_tasks=["CCSync-SubstP"],
            exe_paths=[Path(r"C:\x\ccsync-companion.exe")],
            unmount_p=True,
        )

        def exploding_run(cmd, **kw):
            raise OSError("no shell")

        def exploding_delete(path):
            raise OSError("nope")

        warnings = steps.execute_cleanup(
            plan, log=lambda m: None, run=exploding_run,
            delete_file=exploding_delete,
            delete_run_value=lambda name: False,
            sleep=lambda s: None,
        )
        assert warnings  # plenty of warnings, no exception

    def test_task_access_denied_warns_about_elevation(self):
        plan = steps.CleanupPlan(kill_process_names=[], kill_pythonw_launcher=False,
                                 scheduled_tasks=["CCSync-SubstP"])

        def fake_run(cmd, **kw):
            if "schtasks" in cmd:
                return _FakeCompleted(returncode=1, stderr="ERROR: Access is denied.")
            return _FakeCompleted()

        warnings = steps.execute_cleanup(
            plan, log=lambda m: None, run=fake_run,
            delete_file=lambda p: None, delete_run_value=lambda n: False,
            sleep=lambda s: None,
        )
        assert any("administrator" in w for w in warnings)


# -- config merge -------------------------------------------------------------


class TestMergeConfigText:
    def test_replaces_existing_and_appends_missing(self):
        text = '# comment\neditor_name = "old"\ntransfers = 4\n'
        merged = steps.merge_config_text(text, {
            "editor_name": '"alex"',
            "mode": '"base"',
        })
        assert 'editor_name = "alex"' in merged
        assert 'mode = "base"' in merged
        assert "# comment" in merged
        assert "transfers = 4" in merged
        assert merged.count("editor_name") == 1

    def test_preserves_unrelated_lines_and_order(self):
        text = "a = 1\nb = 2\nc = 3\n"
        merged = steps.merge_config_text(text, {"b": '"x"'})
        lines = merged.splitlines()
        assert lines.index("a = 1") < lines.index('b = "x"') < lines.index("c = 3")

    def test_toml_string_escapes_backslashes(self):
        assert steps._toml_string("T:\\Creators_Club") == '"T:\\\\Creators_Club"'


class TestEnsureConfig:
    def test_base_role_keys(self, tmp_path):
        path = tmp_path / "config.toml"
        steps.ensure_config(
            "base", editor_name="alex", dashboard_url="http://lan:8480",
            dashboard_token="tok", local_root="T:\\Creators_Club", config_path=path,
        )
        text = path.read_text(encoding="utf-8")
        assert 'mode = "base"' in text
        assert 'editor_name = "alex"' in text
        assert 'local_root = "T:\\\\Creators_Club"' in text
        assert 'canonical_prefix = "T:\\\\Creators_Club"' in text
        assert 'dashboard_token = "tok"' in text

    def test_editor_role_keys(self, tmp_path):
        path = tmp_path / "config.toml"
        steps.ensure_config(
            "editor", editor_name="ruskin", dashboard_url="http://tail:8480",
            dashboard_token="tok", local_root="D:\\CC", config_path=path,
        )
        text = path.read_text(encoding="utf-8")
        assert 'mode = "editor"' in text
        assert 'local_root = "D:\\\\CC"' in text
        assert 'canonical_prefix = "P:\\\\"' in text
        assert 'remote = "creators_club_sftp"' in text

    def test_existing_file_merged_not_replaced(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text('# my precious tweak\ntransfers = 8\nmode = "editor"\n',
                        encoding="utf-8")
        steps.ensure_config(
            "base", editor_name="alex", dashboard_url="u", dashboard_token="t",
            config_path=path,
        )
        text = path.read_text(encoding="utf-8")
        assert "# my precious tweak" in text
        assert "transfers = 8" in text
        assert 'mode = "base"' in text

    def test_missing_file_starts_from_companion_default(self, tmp_path):
        path = tmp_path / "config.toml"
        steps.ensure_config(
            "editor", editor_name="e", dashboard_url="u", dashboard_token="t",
            config_path=path,
        )
        text = path.read_text(encoding="utf-8")
        # keys only the companion's DEFAULT_TOML_TEXT contributes
        assert "remote_root" in text
        assert "poll_interval" in text

    def test_config_parses_as_valid_toml(self, tmp_path):
        import tomllib

        path = tmp_path / "config.toml"
        steps.ensure_config(
            "base", editor_name="alex", dashboard_url="http://lan:8480",
            dashboard_token="tok", local_root="T:\\Creators_Club", config_path=path,
        )
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        assert data["local_root"] == "T:\\Creators_Club"
        assert data["mode"] == "base"


# -- base-mode install helpers ------------------------------------------------


def test_register_companion_autostart_sets_run_value():
    values = {}
    steps.register_companion_autostart(
        Path("C:\\bin\\ccsync-companion.exe"),
        set_run_value=lambda name, value: values.update({name: value}),
    )
    assert values == {"CCSyncCompanion": "C:\\bin\\ccsync-companion.exe"}


def test_launch_companion_alive_dead_and_error(tmp_path):
    class _Proc:
        def __init__(self, alive):
            self._alive = alive

        def poll(self):
            return None if self._alive else 1

    exe = tmp_path / "ccsync-companion.exe"
    exe.write_bytes(b"x")
    assert steps.launch_companion(exe, popen=lambda *a, **k: _Proc(True),
                                  sleep=lambda s: None) is True
    assert steps.launch_companion(exe, popen=lambda *a, **k: _Proc(False),
                                  sleep=lambda s: None) is False

    def boom(*a, **k):
        raise OSError("blocked")

    assert steps.launch_companion(exe, popen=boom, sleep=lambda s: None) is False


def test_installer_on_forbidden_drive_only_when_frozen(monkeypatch):
    monkeypatch.setattr(steps.sys, "frozen", False, raising=False)
    assert steps.installer_on_forbidden_drive() is False
    monkeypatch.setattr(steps.sys, "frozen", True, raising=False)
    monkeypatch.setattr(steps.sys, "executable", "P:\\onboard.exe")
    assert steps.installer_on_forbidden_drive() is True
    monkeypatch.setattr(steps.sys, "executable", "\\\\192.168.0.102\\share\\onboard.exe")
    assert steps.installer_on_forbidden_drive() is True
    monkeypatch.setattr(steps.sys, "executable", "C:\\Users\\x\\Desktop\\onboard.exe")
    assert steps.installer_on_forbidden_drive() is False
