"""The tree drive letter is SITE DATA in the wizard too
(installer-onboard-tools-3 / -4, 2026-08-21).

windows_bootstrap.ps1 and windows_uninstall.ps1 have derived the letter, the
logon task name, the Run entry and the loopback share name from the site
manifest's `canonical_prefix` since 2026-08-17 (COMMERCIAL_READINESS.md item
11). The wizard was the one place left saying "P" out loud, so on a site
whose prefix is Q:\\ it guarded the wrong drive, refused the wrong local
root, cleaned up the wrong scheduled task and unmounted a drive this
installer never created.

Everything here passes a `site` dict explicitly: nothing may depend on the
developer's own ~/.ccsync/site.json.
"""

from __future__ import annotations

import re
from pathlib import Path

import steps

Q_SITE = {"canonical_prefix": "Q:\\"}
P_SITE = {"canonical_prefix": "P:\\"}


class TestSiteDriveLetter:
    def test_reads_the_manifest(self):
        assert steps.site_drive_letter(Q_SITE) == "Q"
        assert steps.site_drive_letter({"canonical_prefix": "q:/"}) == "Q"

    def test_falls_back_to_p_when_the_site_says_nothing(self):
        assert steps.site_drive_letter({}) == steps.DEFAULT_DRIVE_LETTER == "P"

    def test_a_prefix_windows_cannot_mount_as_a_letter_is_not_guessed_at(self):
        # The bootstrap REFUSES these outright; the wizard must not invent a
        # letter of its own and mask that refusal.
        for prefix in (r"\\nas\share", "/Volumes/Media", "P:\\Projects", ""):
            assert steps.site_drive_letter({"canonical_prefix": prefix}) == "P"

    def test_derived_names_match_the_bootstrap(self):
        assert steps.subst_task_name("Q") == "CCSync-SubstQ"
        assert steps.loopback_share_unc("Q") == r"\\localhost\CCSync_Q"
        assert "CCSyncSubstQ" in steps.all_run_values("Q")
        # The historical P names survive on every site: a machine may have
        # been provisioned before the letter became site data.
        assert "CCSyncSubstP" in steps.all_run_values("Q")

    def test_the_p_default_names_are_unchanged(self):
        assert steps.SUBST_TASK_NAME == "CCSync-SubstP"
        assert steps.ALL_RUN_VALUES == [
            "CCSyncCompanion", "CCSyncSyncthing", "CCSyncSubstP", "ccsync-companion"]
        assert steps.OUR_LOOPBACK_SHARE == r"\\localhost\CCSync_P"


class TestDefaultRoots:
    def test_base_local_root_follows_the_site(self):
        assert steps.default_base_local_root("win32", site=Q_SITE) == "Q:\\"
        assert steps.default_base_local_root("win32", site=P_SITE) == "P:\\"
        assert steps.default_base_local_root("win32", site={}) == "P:\\"

    def test_macos_base_is_untouched(self):
        assert steps.default_base_local_root("darwin", site=Q_SITE) == ""


class TestValidateLocalRootGuardsTheSitesDrive:
    def _check(self, value, site):
        return steps.validate_local_root(
            value, role="editor", platform="win32", site=site,
            drive_exists=lambda letter: True)

    def test_the_sites_own_letter_is_refused(self):
        problem = self._check(r"Q:\CCSync", Q_SITE)
        assert problem and problem.startswith("Q: is the drive this installer creates")

    def test_p_is_fine_on_a_q_site(self):
        # The wizard used to refuse P here and wave Q through, which is
        # exactly backwards: the bootstrap is about to unmap Q.
        assert self._check(r"P:\CCSync", Q_SITE) is None

    def test_p_is_still_refused_on_a_p_site(self):
        assert self._check(r"P:\CCSync", P_SITE) is not None

    def test_the_whole_volume_message_names_the_sites_letter(self):
        problem = self._check("D:\\", Q_SITE)
        assert problem and "maps Q: at it" in problem


class TestCleanupPlanFollowsTheSite:
    def _plan(self, site):
        return steps.build_cleanup_plan(
            "editor", local_root=r"C:\CCSync", site=site,
            read_run_value=lambda name: None,
            read_local_root=lambda: None,
            exists=lambda p: False)

    def test_the_plan_carries_the_letter(self):
        assert self._plan(Q_SITE).drive_letter == "Q"
        assert self._plan({}).drive_letter == "P"

    def test_the_logon_task_and_run_entry_are_the_sites(self):
        plan = self._plan(Q_SITE)
        assert "CCSync-SubstQ" in plan.scheduled_tasks
        # ...and the historical P one is still removed.
        assert "CCSync-SubstP" in plan.scheduled_tasks
        assert "CCSyncSubstQ" in plan.run_values

    def test_a_p_site_plan_is_exactly_what_it_always_was(self):
        plan = self._plan(P_SITE)
        assert plan.scheduled_tasks == [steps.SUBST_TASK_NAME]
        assert plan.run_values == steps.ALL_RUN_VALUES

    def test_the_exe_sweep_looks_at_the_sites_drive(self):
        seen: list[str] = []

        def exists(path):
            seen.append(str(path))
            return False

        steps.build_cleanup_plan("editor", local_root=r"C:\CCSync", site=Q_SITE,
                                 read_run_value=lambda name: None,
                                 read_local_root=lambda: None, exists=exists)
        assert any(p.upper().startswith("Q:") for p in seen)


class _FakeCompleted:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


class TestExecuteCleanupUnmountsTheSitesDrive:
    def _run_cleanup(self, letter):
        commands: list[list[str]] = []

        def run(cmd, **kw):
            commands.append(list(cmd))
            return _FakeCompleted()

        plan = steps.CleanupPlan(unmount_p=True, drive_letter=letter)
        logs: list[str] = []
        warnings = steps.execute_cleanup(
            plan, logs.append, run=run,
            delete_run_value=lambda name: False,
            read_p_mapping=lambda: {"known": True, "mapped": False},
            p_drive_exists=lambda: False,
        )
        return commands, logs, warnings

    def test_subst_and_net_use_name_the_sites_letter(self):
        commands, logs, warnings = self._run_cleanup("Q")
        flat = [" ".join(c) for c in commands]
        assert any("subst Q: /D" in f for f in flat), flat
        assert any("net use Q: /delete /y" in f for f in flat), flat
        assert not any("P:" in f for f in flat), flat
        assert warnings == []
        assert any("Q: drive unmounted" in line for line in logs)

    def test_a_default_plan_still_unmounts_p(self):
        commands, _logs, _warnings = self._run_cleanup(steps.DEFAULT_DRIVE_LETTER)
        flat = [" ".join(c) for c in commands]
        assert any("subst P: /D" in f for f in flat), flat


class TestMappingProbeFollowsTheSite:
    def test_subst_line_for_the_sites_letter_is_recognised(self):
        def run(cmd, **kw):
            if cmd[-1] == "subst":
                return _FakeCompleted(stdout="Q:\\: => C:\\CCSync\n")
            return _FakeCompleted()

        mapping = steps.default_read_p_mapping(run, "Q")
        assert mapping == {"mapped": True, "kind": "subst",
                           "target": "C:\\CCSync", "known": True}

    def test_our_own_loopback_share_is_ours_on_a_q_site(self):
        ours, why = steps.p_mapping_is_ours(
            {"known": True, "mapped": True, "kind": "net",
             "target": r"\\localhost\CCSync_Q"}, "", "Q")
        assert ours, why

    def test_a_foreign_mapping_is_reported_with_the_right_letter(self):
        ours, why = steps.p_mapping_is_ours(
            {"known": True, "mapped": True, "kind": "net",
             "target": r"\\nas\pool"}, r"\\nas\pool", "Q")
        assert not ours
        assert why.startswith("Q: is mapped to")


class TestResolveMappingWarning:
    def test_the_message_names_the_sites_drive(self):
        output = "[ccsync] RESOLVE-MAPPING-STATUS: running\n"
        warning = steps.resolve_mapping_warning(output, Q_SITE)
        assert warning and "Q:\\ Mapped Mount" in warning
        assert "P:" not in warning

    def test_an_unknown_status_is_still_reported(self):
        warning = steps.resolve_mapping_warning(
            "RESOLVE-MAPPING-STATUS: wat\n", Q_SITE)
        assert warning and "Q:\\ Mapped Mount" in warning and "wat" in warning

    def test_default_site_is_unchanged(self):
        warning = steps.resolve_mapping_warning(
            "RESOLVE-MAPPING-STATUS: running\n", {})
        assert warning and warning.startswith("Resolve's P:\\ Mapped Mount")


class TestForbiddenDrive:
    def test_the_sites_drive_and_p_are_both_refused(self, monkeypatch):
        monkeypatch.setattr(steps.sys, "frozen", True, raising=False)
        monkeypatch.setattr(steps.sys, "executable", r"Q:\Assets\Software\onboard.exe")
        assert steps.installer_on_forbidden_drive(Q_SITE) is True
        monkeypatch.setattr(steps.sys, "executable", r"P:\Assets\Software\onboard.exe")
        assert steps.installer_on_forbidden_drive(Q_SITE) is True
        monkeypatch.setattr(steps.sys, "executable", r"C:\Users\me\Desktop\onboard.exe")
        assert steps.installer_on_forbidden_drive(Q_SITE) is False


class TestWizardPrefillIsRecomputedAfterTheManifestArrives:
    """installer-onboard-tools-4: onboard.py seeds local_root_var in
    __init__, before this machine has ever seen a site manifest, so a FIRST
    run offered C:\\CCSync while a hand-run windows_bootstrap.ps1 would use
    C:\\<tree_name>. The fix is that _on_verify re-derives the default on
    EVERY verified sign-in, not only when the account's role differs from the
    radio. Source-scanned for the same reason test_macos_steps.py scans it:
    onboard.py is Tk and has no unit tests of its own."""

    def _on_verify_source(self) -> str:
        source = (Path(steps.__file__).parent / "onboard.py").read_text(encoding="utf-8")
        start = source.index("    def _on_verify(self)")
        end = source.index("\n    # -- page 4: install", start)
        return source[start:end]

    def test_the_default_is_recomputed_outside_the_role_switch(self):
        body = self._on_verify_source()
        assert body.count("self._on_role_changed()") == 1
        # 16 spaces: the same nesting as show_install(), i.e. NOT inside the
        # `if effective != picked:` branch (which is 20).
        assert re.search(r"\n {16}self\._on_role_changed\(\)\n", body), body
        assert body.index("self._on_role_changed()") < body.index("self.show_install()")

    def test_the_neutral_prefill_counts_as_a_default(self):
        source = (Path(steps.__file__).parent / "onboard.py").read_text(encoding="utf-8")
        # The set _on_role_changed clobbers must include the value __init__
        # seeded with no manifest, or the recompute above changes nothing.
        assert "steps.default_local_root(site={})" in source
