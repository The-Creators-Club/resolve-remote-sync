"""Tests for the all-in-one installer's clean-slate, config-merge, and
base-mode install helpers (steps.py additions, 2026-07) -- same
injected-fake style as test_steps.py: nothing here touches the registry,
scheduled tasks, real processes, or any path outside tmp_path."""
from __future__ import annotations

import re
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

    def test_base_role_never_treats_local_root_as_cleanup_candidate(self):
        # D-9: on the base rig, local_root (and an existing config's
        # local_root) IS the shared NAS tree -- must never be a cleanup dir.
        nas_exe = Path(r"T:\Creators_Club") / "ccsync-companion.exe"
        plan = self._plan(role="base", local_root=r"T:\Creators_Club",
                          config_root=r"T:\Creators_Club", existing=[nas_exe])
        assert nas_exe not in plan.exe_paths

    def test_editor_role_still_scans_local_root(self):
        exe = Path(r"D:\CC") / "ccsync-companion.exe"
        plan = self._plan(role="editor", local_root=r"D:\CC", existing=[exe])
        assert exe in plan.exe_paths

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

    def test_syncthing_is_never_blanket_killed(self):
        # INST-20: `taskkill /IM syncthing.exe` also kills the editor's OWN
        # Syncthing -- which nothing here ever restarts.
        plan = self._plan()
        assert "syncthing" not in plan.kill_process_names
        assert plan.syncthing_managed_dirs  # scoped kill instead

    def test_managed_syncthing_dirs_cover_our_install_locations(self):
        dirs = [str(p).lower() for p in steps.managed_syncthing_dirs()]
        assert any(str(steps.COMPANION_BIN_DIR).lower().startswith(d) for d in dirs)


# -- managed-only Syncthing kill (INST-20) ------------------------------------


class TestSyncthingScoping:
    def _run(self, processes):
        plan = steps.CleanupPlan(
            kill_process_names=[], kill_pythonw_launcher=False,
            syncthing_managed_dirs=[Path(r"C:\Users\x\AppData\Local\ccsync")],
        )
        killed = []
        logs = []

        def fake_run(cmd, **kw):
            killed.append(cmd)
            return _FakeCompleted()

        warnings = steps.execute_cleanup(
            plan, log=logs.append, run=fake_run,
            delete_file=lambda p: None, delete_run_value=lambda n: False,
            sleep=lambda s: None,
            list_processes=lambda name: processes,
        )
        return warnings, killed, logs

    def test_kills_our_syncthing(self):
        warnings, killed, logs = self._run(
            [("4242", r"C:\Users\x\AppData\Local\ccsync\bin\syncthing.exe")])
        assert ["taskkill", "/F", "/PID", "4242"] in killed
        assert warnings == []
        assert any("4242" in line for line in logs)

    def test_leaves_a_foreign_syncthing_alone_and_warns(self):
        warnings, killed, _logs = self._run(
            [("777", r"C:\Program Files\Syncthing\syncthing.exe")])
        assert not any("taskkill" in c for c in killed)
        assert any("not ours" in w for w in warnings)
        assert any("Program Files" in w for w in warnings)

    def test_mixed_kills_only_ours(self):
        warnings, killed, _logs = self._run([
            ("1", r"C:\Users\x\AppData\Local\ccsync\bin\syncthing.exe"),
            ("2", r"D:\scoop\apps\syncthing\current\syncthing.exe"),
        ])
        pids = [c[3] for c in killed if c[0] == "taskkill"]
        assert pids == ["1"]
        assert len(warnings) == 1

    def test_unknown_executable_path_is_treated_as_foreign(self):
        # A process we cannot resolve is one we must not kill.
        warnings, killed, _logs = self._run([("9", "")])
        assert not any("taskkill" in c for c in killed)
        assert warnings

    def test_enumeration_failure_is_a_warning_not_a_crash(self):
        plan = steps.CleanupPlan(
            kill_process_names=[], kill_pythonw_launcher=False,
            syncthing_managed_dirs=[Path(r"C:\ccsync")],
        )

        def boom(name):
            raise OSError("wmi is having a day")

        warnings = steps.execute_cleanup(
            plan, log=lambda m: None, run=lambda c, **k: _FakeCompleted(),
            delete_file=lambda p: None, delete_run_value=lambda n: False,
            sleep=lambda s: None, list_processes=boom,
        )
        assert any("enumerate" in w for w in warnings)


def test_execute_cleanup_decodes_subprocess_output_explicitly():
    # S-6: `text=True` alone decodes with the console codepage under
    # errors="strict", so one non-ASCII byte raises out of the worker thread.
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        return _FakeCompleted()

    steps.execute_cleanup(
        steps.CleanupPlan(kill_process_names=["ccsync-companion"],
                          kill_pythonw_launcher=False),
        log=lambda m: None, run=fake_run,
        delete_file=lambda p: None, delete_run_value=lambda n: False,
        sleep=lambda s: None,
    )
    assert seen["encoding"] == "utf-8"
    assert seen["errors"] == "replace"


def test_default_list_processes_parses_pid_and_path():
    def fake_run(cmd, **kw):
        assert "-NoProfile" in cmd and "-NonInteractive" in cmd
        return _FakeCompleted(stdout=(
            "4242|C:\\Users\\x\\AppData\\Local\\ccsync\\bin\\syncthing.exe\n"
            "777|C:\\Program Files\\Syncthing\\syncthing.exe\n"
            "\n"
            "garbage line\n"
        ))

    found = steps.default_list_processes("syncthing", run=fake_run)
    assert found == [
        ("4242", "C:\\Users\\x\\AppData\\Local\\ccsync\\bin\\syncthing.exe"),
        ("777", "C:\\Program Files\\Syncthing\\syncthing.exe"),
    ]


def test_default_list_processes_returns_empty_on_failure():
    def boom(cmd, **kw):
        raise OSError("no powershell")

    assert steps.default_list_processes("syncthing", run=boom) == []


# -- execute_cleanup ----------------------------------------------------------


class _FakeCompleted:
    def __init__(self, returncode=0, stderr="", stdout=""):
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout


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

    def test_defaults_fill_a_missing_key(self):
        merged = steps.merge_config_text("a = 1\n", {}, {"b": '"seeded"'})
        assert 'b = "seeded"' in merged

    def test_defaults_fill_a_blank_key(self):
        merged = steps.merge_config_text('remote_root = ""\n', {},
                                          {"remote_root": '"/mnt/tank/x"'})
        assert 'remote_root = "/mnt/tank/x"' in merged

    def test_defaults_never_overwrite_a_real_value(self):
        merged = steps.merge_config_text('remote_root = "/mnt/other/pool"\n', {},
                                          {"remote_root": '"/mnt/tank/x"'})
        assert 'remote_root = "/mnt/other/pool"' in merged
        assert "/mnt/tank/x" not in merged

    def test_forced_beats_defaults_for_the_same_key(self):
        merged = steps.merge_config_text('k = "old"\n', {"k": '"forced"'},
                                          {"k": '"default"'})
        assert 'k = "forced"' in merged and "default" not in merged


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

    def test_editor_role_forces_nonblank_remote_root(self, tmp_path):
        # S-1: a fresh editor config must never ship a blank remote_root --
        # rclone would otherwise target the bare SFTP home directory.
        path = tmp_path / "config.toml"
        steps.ensure_config(
            "editor", editor_name="ruskin", dashboard_url="http://tail:8480",
            dashboard_token="tok", local_root="D:\\CC", config_path=path,
        )
        text = path.read_text(encoding="utf-8")
        match = re.search(r'(?m)^remote_root\s*=\s*"(.*)"\s*$', text)
        assert match is not None
        assert match.group(1).strip() != ""
        assert match.group(1) == steps.DEFAULT_REMOTE_ROOT

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

    def test_cp1252_config_does_not_raise_after_clean_slate(self, tmp_path):
        # A config.toml saved by Notepad in cp1252 raises UnicodeDecodeError,
        # which is a ValueError and NOT an OSError -- it escaped the handler
        # and surfaced as "install failed" AFTER _clean_slate had removed the
        # working install, with RETRY failing identically forever.
        path = tmp_path / "config.toml"
        path.write_bytes('editor_name = "Jos\xe9"\ntransfers = 8\n'.encode("cp1252"))

        steps.ensure_config(
            "editor", editor_name="jose", dashboard_url="u", dashboard_token="t",
            local_root="D:\\CC", config_path=path,
        )

        text = path.read_text(encoding="utf-8")
        assert 'editor_name = "jose"' in text
        assert 'mode = "editor"' in text
        # the unreadable original is preserved beside it, not silently binned
        salvaged = [p for p in tmp_path.iterdir() if ".unreadable-" in p.name]
        assert len(salvaged) == 1

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

    def test_blank_report_token_never_wipes_a_working_dashboard_token(self, tmp_path):
        # INST-11: a verify response with no report_token (older dashboard, a
        # field rename) used to rewrite a good token to "" -- after which the
        # companion posts unauthenticated forever and the fleet grid shows
        # this editor offline, with the wizard saying DONE.
        path = tmp_path / "config.toml"
        path.write_text('dashboard_token = "still-works"\n', encoding="utf-8")
        steps.ensure_config(
            "editor", editor_name="e", dashboard_url="u", dashboard_token="",
            config_path=path,
        )
        assert 'dashboard_token = "still-works"' in path.read_text(encoding="utf-8")

    def test_a_real_report_token_still_replaces_the_old_one(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text('dashboard_token = "stale"\n', encoding="utf-8")
        steps.ensure_config(
            "editor", editor_name="e", dashboard_url="u", dashboard_token="fresh",
            config_path=path,
        )
        text = path.read_text(encoding="utf-8")
        assert 'dashboard_token = "fresh"' in text and "stale" not in text

    def test_blank_token_is_still_seeded_when_the_key_is_absent(self, tmp_path):
        path = tmp_path / "config.toml"
        path.write_text("transfers = 4\n", encoding="utf-8")
        steps.ensure_config(
            "editor", editor_name="e", dashboard_url="u", dashboard_token="",
            config_path=path,
        )
        assert re.search(r'(?m)^dashboard_token\s*=', path.read_text(encoding="utf-8"))

    def test_customised_remote_root_survives_a_reinstall(self, tmp_path):
        # §7 new-defect 7: remote_root moved from forced to seeded, so an
        # admin who pointed this editor at a different pool path keeps it.
        path = tmp_path / "config.toml"
        path.write_text('remote_root = "/mnt/tank/OtherPool/Creators_Club"\n',
                        encoding="utf-8")
        steps.ensure_config(
            "editor", editor_name="e", dashboard_url="u", dashboard_token="t",
            config_path=path,
        )
        text = path.read_text(encoding="utf-8")
        assert 'remote_root = "/mnt/tank/OtherPool/Creators_Club"' in text
        assert steps.DEFAULT_REMOTE_ROOT not in text

    def test_blank_remote_root_is_still_repaired(self, tmp_path):
        # ...but a blank one must never survive: S-1's whole point.
        path = tmp_path / "config.toml"
        path.write_text('remote_root = ""\n', encoding="utf-8")
        steps.ensure_config(
            "editor", editor_name="e", dashboard_url="u", dashboard_token="t",
            config_path=path,
        )
        assert f'remote_root = "{steps.DEFAULT_REMOTE_ROOT}"' in path.read_text(encoding="utf-8")

    def test_local_root_and_editor_name_are_still_forced(self, tmp_path):
        # These the installer DOES own -- a stale one is what makes reports
        # go to the wrong editor.
        path = tmp_path / "config.toml"
        path.write_text('editor_name = "old"\nlocal_root = "X:\\\\junk"\n',
                        encoding="utf-8")
        steps.ensure_config(
            "editor", editor_name="new", dashboard_url="u", dashboard_token="t",
            local_root="D:\\CC", config_path=path,
        )
        text = path.read_text(encoding="utf-8")
        assert 'editor_name = "new"' in text
        assert 'local_root = "D:\\\\CC"' in text

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
