"""Bug hunt 2026-09-24, wave 2 (mediums and lows), the onboarding group.

logic-onboarding-1: the account's role (derived from the admin list, i.e. the
    PERSON) overrode the radio and became config.toml `mode`. The radio wins
    now, seeded on a re-run from this machine's own config.toml.
logic-onboarding-2: on a site that retired the shared report token the wizard
    said DONE for a machine with no fleet credential, and a re-run dropped a
    per-editor token from identity.json.
logic-onboarding-4: "TrueNAS username and password" in the wizard/bootstraps.
logic-onboarding-5: the finish page's self-contradicting sign-in hint, and
    asking for a key already sent.
ui-onboarding-1: page nav bars (BACK/CLOSE) were the first thing to lose
    space on an over-tall page.
ui-onboarding-2: the licence page showed the raw EULA.md.
ui-onboarding-4: the winget Tailscale path (stale status, green on failure,
    join check that cannot find a freshly installed tailscale.exe).

Nothing here reads or writes the developer's own ~/.ccsync: every path is a
tmp_path, and the GUI-layer checks read onboard.py's source (onboard.py builds
a Tk root in __init__; see test_steps._onboard_method_source).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

import steps

ONBOARDING = Path(__file__).resolve().parent.parent
REPO = ONBOARDING.parent
ONBOARD_SRC = (ONBOARDING / "onboard.py").read_text(encoding="utf-8")
GOOD_TOKEN = "cce1." + "0123456789abcdef" + "." + "ab" * 24


def _method(name: str) -> str:
    tree = ast.parse(ONBOARD_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(ONBOARD_SRC, node) or ""
    raise AssertionError(f"onboard.py has no method named {name!r}")


def _code_only(text: str) -> str:
    return "\n".join(line for line in text.splitlines()
                     if not line.lstrip().startswith("#"))


# -- logic-onboarding-1 --------------------------------------------------------


class TestTheRadioDecidesTheMachinesRole:
    def test_admin_on_a_remote_laptop_gets_the_remote_install(self):
        # Scenario (a): an admin (verify says "base") picks REMOTE EDITOR on
        # his laptop. HEAD answered "base": mode=base, local_root on the NAS
        # letter, the Syncthing and tree-drive autostarts deleted.
        assert steps.effective_install_role("editor", "base") == "editor"

    def test_non_admin_on_a_wired_desktop_gets_the_wired_install(self):
        # Scenario (b): the refusal tells them to pick PHYSICALLY CONNECTED,
        # and HEAD overrode that pick back to "editor" on every run.
        assert steps.effective_install_role("base", "editor") == "base"

    def test_unknown_radio_still_lands_on_the_non_destructive_role(self):
        assert steps.effective_install_role(None, "editor") == "base"
        assert steps.effective_install_role("nonsense", "editor") == "base"

    def test_a_rerun_starts_from_this_machines_config_mode(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text('editor_name = "alex"\nmode = "base"  # wired\n', encoding="utf-8")
        assert steps.read_config_mode(cfg) == "base"
        assert steps.initial_install_role(cfg) == "base"
        cfg.write_text('mode = "editor"\n', encoding="utf-8")
        assert steps.initial_install_role(cfg) == "editor"

    def test_first_run_or_unusable_mode_defaults_to_remote(self, tmp_path):
        assert steps.initial_install_role(tmp_path / "absent.toml") == "editor"
        cfg = tmp_path / "config.toml"
        cfg.write_text('mode = "wizard"\n', encoding="utf-8")
        assert steps.read_config_mode(cfg) is None
        assert steps.initial_install_role(cfg) == "editor"
        cfg.write_text('# mode = "base"\nlocal_root = "C:\\\\x"\n', encoding="utf-8")
        assert steps.read_config_mode(cfg) is None

    def test_the_wizard_seeds_the_radio_and_no_longer_snaps_it(self):
        init = _code_only(_method("__init__"))
        assert "steps.initial_install_role()" in init
        verify = _code_only(_method("_on_verify"))
        assert "role_var.set(" not in verify, "the account's role is snapped onto the radio again"
        assert "obeys anyway" not in ONBOARD_SRC


# -- logic-onboarding-2 --------------------------------------------------------


class TestFleetCredential:
    def test_verify_account_passes_report_token_kind_through(self):
        def post(url, payload, headers, timeout):
            return {"ok": True, "username": "ana", "token": "t", "report_token": "",
                    "report_token_kind": "editor", "role": "editor"}
        result = steps.verify_account("http://dash:8480", "ana", "pw", http_post=post)
        assert result["report_token_kind"] == "editor"

    def test_an_older_dashboard_sends_no_kind_and_is_never_asked(self):
        def post(url, payload, headers, timeout):
            return {"ok": True, "username": "ana", "token": "t", "report_token": ""}
        result = steps.verify_account("http://dash:8480", "ana", "pw", http_post=post)
        assert result["report_token_kind"] is None
        assert steps.fleet_token_needed("", result["report_token_kind"], "") is False

    def test_needed_only_when_shared_is_retired_and_nothing_is_held(self):
        assert steps.fleet_token_needed("", "editor", "") is True
        assert steps.fleet_token_needed("shared-secret", "shared", "") is False
        assert steps.fleet_token_needed("", "shared", "") is False
        # a migrated machine re-running the wizard is not asked again
        assert steps.fleet_token_needed("", "editor", GOOD_TOKEN) is False

    def test_existing_token_is_found_in_either_place(self, tmp_path):
        ident = tmp_path / "identity.json"
        cfg = tmp_path / "config.toml"
        assert steps.existing_editor_report_token(cfg, ident) == ""
        cfg.write_text(f'report_token = "{GOOD_TOKEN}"\n', encoding="utf-8")
        assert steps.existing_editor_report_token(cfg, ident) == GOOD_TOKEN
        cfg.write_text('report_token = ""\n', encoding="utf-8")
        ident.write_text(json.dumps({"editor_report_token": GOOD_TOKEN}), encoding="utf-8")
        assert steps.existing_editor_report_token(cfg, ident) == GOOD_TOKEN

    def test_token_field_validation(self):
        assert steps.fleet_token_problem("") is None
        assert steps.fleet_token_problem(GOOD_TOKEN) is None
        assert steps.fleet_token_problem("hunter2") is not None
        assert steps.fleet_token_problem(" " + GOOD_TOKEN) is not None

    def test_ensure_config_writes_the_pasted_token_and_a_blank_never_erases(self, tmp_path):
        cfg = tmp_path / "config.toml"
        steps.ensure_config("editor", editor_name="ana", dashboard_url="http://d",
                            dashboard_token="", local_root=r"C:\Pool", config_path=cfg,
                            platform="win32", site={"canonical_prefix": "P:\\"},
                            report_token=GOOD_TOKEN)
        assert f'report_token = "{GOOD_TOKEN}"' in cfg.read_text(encoding="utf-8")
        steps.ensure_config("editor", editor_name="ana", dashboard_url="http://d",
                            dashboard_token="", local_root=r"C:\Pool", config_path=cfg,
                            platform="win32", site={"canonical_prefix": "P:\\"},
                            report_token="")
        assert f'report_token = "{GOOD_TOKEN}"' in cfg.read_text(encoding="utf-8")

    def test_write_identity_keeps_a_per_editor_token(self, tmp_path, monkeypatch):
        # HEAD's write_identity called save_identity with the identity only,
        # so a wizard re-run dropped the machine's cce1 token from
        # identity.json: on a site with the shared token retired, every
        # report after an install that said DONE was a 401.
        path = tmp_path / "identity.json"
        path.write_text(json.dumps({"username": "ana", "token": "old",
                                    "editor_report_token": GOOD_TOKEN,
                                    "report_token": "shared-old"}), encoding="utf-8")
        monkeypatch.setattr(steps.identity_mod, "identity_path", lambda *a, **k: path)
        steps.write_identity("ana", "new-token", role="editor")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["token"] == "new-token"
        assert data["editor_report_token"] == GOOD_TOKEN
        assert data["report_token"] == "shared-old"

    def test_both_finish_paths_warn_when_no_credential_was_entered(self):
        body = _code_only(_method("_write_config_and_identity"))
        assert "missing_fleet_token_warning" in body
        assert "report_token=self._fleet_token()" in body
        base_finish = _code_only(_method("show_finish_base"))
        assert "install_warnings" in base_finish
        assert "NOT READY" in base_finish


# -- logic-onboarding-4 --------------------------------------------------------


def test_no_storage_vendor_in_the_sign_in_copy():
    for path in (ONBOARDING / "onboard.py",
                 REPO / "installer" / "windows_bootstrap.ps1",
                 REPO / "installer" / "macos_bootstrap.sh"):
        text = path.read_text(encoding="utf-8")
        assert "TrueNAS username and password" not in text, path.name
        assert "SAME TrueNAS" not in text, path.name


# -- logic-onboarding-5 --------------------------------------------------------


class TestFinishPageCopy:
    def test_the_hint_does_not_announce_a_step_that_is_done(self):
        for sent in (True, False):
            copy = steps.finish_page_copy(sent, "ana")
            assert "One more step" not in copy["hint"]
            assert "already signed in" in copy["hint"]

    def test_a_sent_key_is_not_asked_for_again(self):
        copy = steps.finish_page_copy(True, "ana")
        assert "TWO VALUES" not in copy["heading"]
        assert "device ID" in copy["send"]
        assert "Users page" in copy["hint"]

    def test_an_unsent_key_still_asks_for_both(self):
        copy = steps.finish_page_copy(False, "ana")
        assert "TWO VALUES" in copy["heading"]

    def test_the_page_uses_the_helper(self):
        body = _code_only(_method("show_finish"))
        assert "finish_page_copy(self.ssh_key_sent" in body
        assert "One more step" not in body
        assert "self.ssh_key_sent = " in _method("_offer_ssh_key")


# -- ui-onboarding-1 -----------------------------------------------------------


def test_every_bottom_bar_goes_through_the_helper():
    """No page may pack its bar on its own again: `side="bottom"` packed LAST
    is exactly what lost BACK and CLOSE on the tall pages."""
    code = _code_only(ONBOARD_SRC)
    helper = _code_only(_method("_pack_bottom_bar"))
    outside = code.replace(helper, "")
    assert 'side="bottom"' not in outside
    assert "before=" in helper


def test_the_bar_is_packed_first_and_keeps_its_space():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display for Tk")
    try:
        import onboard

        root.withdraw()
        root.geometry("300x120")

        class _Host:
            pass

        host = _Host()
        host.root = root
        host._fit_window = lambda: None
        frame = tk.Frame(root)
        frame.pack(fill="both", expand=True)
        tall = tk.Label(frame, text="\n".join(["x"] * 40))
        tall.pack(anchor="w")
        bar = tk.Frame(frame, height=20)
        onboard.OnboardWizard._pack_bottom_bar(host, frame, bar)
        # First in the packing order = first to be given space.
        assert frame.pack_slaves()[0] is bar
    finally:
        root.destroy()


def test_fit_window_grows_height_only_and_is_capped_by_the_screen():
    import onboard

    class _Root:
        def __init__(self, req_h, screen_h):
            self.req_h, self.screen_h, self.set = req_h, screen_h, None

        def update_idletasks(self):
            pass

        def winfo_width(self):
            return 660

        def winfo_height(self):
            return 560

        def winfo_reqheight(self):
            return self.req_h

        def winfo_screenheight(self):
            return self.screen_h

        def geometry(self, value):
            self.set = value

    class _Host:
        pass

    host = _Host()
    host.root = _Root(706, 1080)
    onboard.OnboardWizard._fit_window(host)
    assert host.root.set == "660x706"
    host.root = _Root(900, 700)
    onboard.OnboardWizard._fit_window(host)
    assert host.root.set == "660x620"
    host.root = _Root(400, 1080)
    onboard.OnboardWizard._fit_window(host)
    assert host.root.set is None  # never shrinks


# -- ui-onboarding-2 -----------------------------------------------------------


class TestEulaDisplayText:
    def test_the_shipped_document_reads_clean(self):
        shown = steps.eula_display_text(steps.EULA_TEXT)
        assert steps.EULA_TEXT, "the wizard's EULA asset is missing"
        assert "<!--" not in shown
        assert "NOT YET EXECUTABLE" not in shown   # the internal draft comment
        assert "\u2014" not in shown
        assert "**" not in shown
        assert not any(line.startswith("#") for line in shown.splitlines())
        assert "END USER LICENCE AGREEMENT" in shown

    def test_the_raw_text_is_still_what_is_versioned(self):
        # Display only: the version marker and the acceptance hash read the
        # untouched file, so the companion's check still matches.
        assert steps.EULA_VERSION
        assert "EULA-VERSION" in steps.EULA_TEXT

    def test_markup_forms(self):
        text = ("<!-- hidden\nTODO -->\n# Title — here\n\n## 1. Part\n\n"
                "**bold** and *it* and `code` and [link](https://x.y)\n")
        shown = steps.eula_display_text(text)
        assert shown.startswith("TITLE - HERE\n\n1. PART\n\n")
        assert "bold and it and code and link (https://x.y)" in shown

    def test_the_page_inserts_the_display_form(self):
        assert "steps.EULA_DISPLAY_TEXT" in _method("show_eula")
        assert "steps.EULA_TEXT" not in _code_only(_method("show_eula"))


# -- ui-onboarding-4 -----------------------------------------------------------


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class TestTailscaleAfterWinget:
    def test_the_join_check_finds_a_freshly_installed_exe(self, monkeypatch):
        monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
        expected = steps.tailscale_exe_windows()
        calls = []

        def run(cmd, **kwargs):
            calls.append(cmd[0])
            if cmd[0] == "tailscale":
                raise FileNotFoundError("not on this process's PATH yet")
            return _Result(0, "100.64.0.9 pc ana@ windows -\n")

        assert steps.tailscale_up(run=run, platform="win32") is True
        assert calls == ["tailscale", expected]

    def test_winget_outcome_is_the_fact_on_disk(self):
        msg, ok = steps.winget_tailscale_outcome(0, installed=False)
        assert ok is False and "did not install" in msg
        msg, ok = steps.winget_tailscale_outcome(-1978335189, installed=False)
        assert ok is False and "-1978335189" in msg
        # "already installed, nothing newer" exits non-zero and is a success
        msg, ok = steps.winget_tailscale_outcome(-1978335189, installed=True)
        assert ok is True

    def test_the_page_refreshes_the_status_line(self):
        assert "_refresh_tailscale_status" in _method("_on_install_tailscale")
        assert "_refresh_tailscale_status" in _method("_on_check_connection")
        assert "winget_tailscale_outcome" in _method("_on_install_tailscale")


# =============================================================================
# Chunk 2: ui-onboarding-3, -5, -6, -8, -10, -11, -12 (ui-onboarding-7 was
# removed with the note it described by logic-onboarding-1 above).
# =============================================================================

import sys
import threading
import time


@pytest.fixture
def make_wizard(monkeypatch):
    """A real OnboardWizard, withdrawn, with every steps helper that would
    read this machine's own ~/.ccsync or shell out replaced."""
    pytest.importorskip("tkinter")
    import onboard
    from ccsync_companion import site as site_mod

    monkeypatch.setattr(site_mod, "cached_site", lambda **kw: {})
    monkeypatch.setattr(steps, "eula_accepted", lambda *a, **k: True)
    monkeypatch.setattr(steps, "initial_install_role", lambda *a, **k: "editor", raising=False)
    monkeypatch.setattr(steps, "default_console_user", lambda *a, **k: None)
    monkeypatch.setattr(steps, "install_log_path", lambda *a, **k: None)
    monkeypatch.setattr(steps, "tailscale_installed", lambda *a, **k: True)
    made = []

    def _make(breadcrumb=None):
        monkeypatch.setattr(steps, "read_install_breadcrumb", lambda *a, **k: breadcrumb)
        # This machine's Tcl intermittently fails to read init.tcl when many
        # interpreters are created back to back ("couldn't read file ... No
        # error"); a retry, not a skip, keeps these checks from going vacuous.
        for attempt in range(5):
            try:
                w = onboard.OnboardWizard()
                break
            except onboard.tk.TclError as exc:
                if attempt == 4:
                    pytest.skip(f"no usable Tk here: {exc}")
                time.sleep(0.2)
        # Mapped but off-screen, not withdrawn: Tk drops a focus request made
        # in a withdrawn toplevel, which would make the focus checks vacuous.
        w.root.geometry("660x560+-4000+-4000")
        w.root.update()
        made.append(w)
        return w

    yield _make
    for w in made:
        try:
            w.root.destroy()
        except Exception:
            pass


def _settle(w, timeout=5.0):
    """Run the real Tk event loop (and so the wizard's own UI pump) until
    every worker thread has finished and what it queued has run.
    Behavioural on purpose (no wizard attributes), so it means the same on
    HEAD's code as on the fix; and a mainloop, not a hand drain, because
    HEAD's workers read Tk variables, which tkinter only serves off-thread
    while mainloop is running."""
    deadline = time.monotonic() + timeout

    def _check():
        busy = [t for t in threading.enumerate()
                if t is not threading.main_thread() and t.daemon and t.is_alive()]
        if (not busy and w._ui_queue.empty()) or time.monotonic() > deadline:
            w.root.after(150, w.root.quit)  # let the pump run once more
        else:
            w.root.after(20, _check)

    w.root.after(20, _check)
    w.root.mainloop()


def _pump_until(w, pred, timeout=5.0):
    """Run the real Tk event loop until pred() holds and what the workers
    queued has run (review round, ui-onboarding-12: _settle waits for EVERY
    worker, which cannot work while one is held on purpose)."""
    deadline = time.monotonic() + timeout

    def _check():
        if (pred() and w._ui_queue.empty()) or time.monotonic() > deadline:
            w.root.after(150, w.root.quit)
        else:
            w.root.after(20, _check)

    w.root.after(20, _check)
    w.root.mainloop()


def _all_widgets(widget):
    out = [widget]
    for child in widget.winfo_children():
        out.extend(_all_widgets(child))
    return out


def _page_text(w):
    texts = []
    for widget in _all_widgets(w.page_frame):
        try:
            texts.append(str(widget.cget("text")))
        except Exception:
            pass
    return "\n".join(texts)


def _buttons(w, label):
    return [b for b in _all_widgets(w.page_frame)
            if b.winfo_class() == "Button" and label in str(b.cget("text"))]


def _requested_focus(w):
    # focus_get() answers None for a withdrawn window; the focus the page
    # ASKED for is what `focus -lastfor` reports.
    return str(w.root.tk.call("focus", "-lastfor", w.root))


def _entries(w):
    return [e for e in _all_widgets(w.page_frame) if e.winfo_class() == "Entry"]


# -- ui-onboarding-3 -----------------------------------------------------------


class TestInterruptedInstallCopy:
    def test_the_close_warning_names_the_drive_only_for_a_windows_editor(self):
        editor = steps.install_close_warning("Q", "editor", is_macos=False)
        assert "no Q drive" in editor
        base = steps.install_close_warning("Q", "base", is_macos=False)
        assert "drive" not in base and "no CCSync" in base
        mac = steps.install_close_warning("Q", "editor", is_macos=True)
        assert "drive" not in mac and "no CCSync" in mac

    def test_the_breadcrumb_role_is_read_back(self):
        assert steps.breadcrumb_role({"phase": "clean_slate:base"}) == "base"
        assert steps.breadcrumb_role({"phase": "clean_slate:editor"}) == "editor"
        assert steps.breadcrumb_role({"phase": "install"}) is None
        assert steps.breadcrumb_role({}) is None
        assert steps.breadcrumb_role(None) is None

    def test_the_interrupted_page_body(self):
        base = steps.interrupted_install_message("P", "base", is_macos=False)
        assert "no CCSync on this machine" in base
        assert "P: drive mappings were not touched" in base
        assert "no P drive" not in base
        editor = steps.interrupted_install_message("P", "editor", is_macos=False)
        assert "no CCSync and no P drive" in editor and "Nothing is syncing" in editor
        unknown = steps.interrupted_install_message("P", None, is_macos=False)
        assert "no P drive" in unknown  # the worse of the two, when unreadable
        mac = steps.interrupted_install_message("P", "editor", is_macos=True)
        assert "drive" not in mac
        mac_base = steps.interrupted_install_message("P", "base", is_macos=True)
        assert "NAS mounts were not touched" in mac_base
        for text in (base, editor, mac, mac_base):
            assert "—" not in text

    def test_a_wired_resume_says_the_truth_and_preselects_wired(self, make_wizard):
        w = make_wizard({"phase": "clean_slate:base", "started_at": "2026-09-25T10:00:00"})
        text = _page_text(w).replace("\n", " ")
        import onboard

        assert "THE LAST INSTALL DID NOT FINISH" in text
        assert ("NAS mounts were not touched" if onboard.IS_MACOS
                else "drive mappings were not touched") in text
        assert "no P drive" not in text
        assert w.role_var.get() == "base"

    def test_close_request_passes_the_running_role(self):
        body = _method("_on_close_request")
        assert "self._effective_role()" in body and "IS_MACOS" in body


# -- ui-onboarding-5 -----------------------------------------------------------


class TestFinishPageCopyLog:
    def test_the_truncation_line_points_at_this_page(self):
        lines = steps.finish_warning_lines([f"w{n}" for n in range(9)])
        assert "previous page" not in lines[-1]
        assert "COPY LOG at the bottom of this page" in lines[-1]

    def test_both_finish_pages_have_copy_log(self, make_wizard):
        w = make_wizard()
        w.verified_username = "ana"
        w.install_warnings = [f"problem {n}" for n in range(8)]
        w.show_finish()
        assert _buttons(w, "COPY LOG"), "the editor finish page has no COPY LOG"
        assert _buttons(w, "CLOSE")
        w.show_finish_base()
        assert _buttons(w, "COPY LOG"), "the base finish page has no COPY LOG"

    def test_copy_log_on_the_finish_page_copies_the_file(self, make_wizard, monkeypatch):
        w = make_wizard()
        w.verified_username = "ana"
        w.install_warnings = ["x"]
        monkeypatch.setattr(steps, "read_install_log", lambda *a, **k: "the whole log")
        w.show_finish()
        _buttons(w, "COPY LOG")[0].invoke()
        assert w.root.clipboard_get() == "the whole log"


# -- ui-onboarding-6 -----------------------------------------------------------


class TestWelcomeNamesTheDashboardAddress:
    @pytest.mark.parametrize("mac", [False, True])
    def test_both_platforms(self, mac):
        text = steps.welcome_text("P", is_macos=mac)
        assert "nothing else" not in text
        assert "dashboard address" in text
        assert "username and password" in text
        assert "—" not in text

    def test_the_page_uses_the_helper(self):
        body = _method("show_welcome")
        assert "steps.welcome_text(" in body
        assert "nothing else" not in body


# -- ui-onboarding-8 -----------------------------------------------------------


_MAC_FOCUS = pytest.mark.skipif(
    sys.platform == "darwin",
    reason="a CI Mac does not hand keyboard focus to a background Tk app; "
           "the same code is checked on the Windows job")


class TestKeyboard:
    def test_every_wizard_button_goes_through_the_keyboard_helper(self):
        code = _code_only(ONBOARD_SRC)
        helper = _code_only(_method("_button"))
        assert "theme.neon_button" not in code.replace(helper, "")

    @_MAC_FOCUS
    def test_buttons_show_focus_and_answer_enter(self, make_wizard):
        import onboard

        w = make_wizard()
        pressed = []
        btn = onboard._button(w.page_frame, "TRY", lambda: pressed.append(1))
        btn.pack()
        w.root.update()
        assert int(btn.cget("highlightthickness")) >= 1
        assert str(btn.cget("highlightcolor")) != str(btn.cget("highlightbackground"))
        assert str(btn.cget("takefocus")) == "1"
        # Key events go to the focus widget, which is what Tab moves.
        btn.focus_force()
        w.root.update()
        btn.event_generate("<Return>")
        w.root.update()
        assert pressed == [1]
        btn.config(state="disabled")
        btn.event_generate("<Return>")
        w.root.update()
        assert pressed == [1], "Enter pressed a disabled button"

    @_MAC_FOCUS
    def test_sign_in_focuses_the_form_and_enter_verifies(self, make_wizard):
        w = make_wizard()
        calls = []
        w._on_verify = lambda: calls.append("verify")
        w.show_signin()
        w.root.update()
        user_entry, pass_entry = _entries(w)[:2]
        assert _requested_focus(w) == str(user_entry)
        for entry in (pass_entry, user_entry):
            entry.focus_force()
            w.root.update()
            entry.event_generate("<Return>")
            w.root.update()
        assert calls == ["verify", "verify"]

    @_MAC_FOCUS
    def test_a_filled_username_starts_on_the_password(self, make_wizard):
        w = make_wizard()
        w.username_var.set("ana")
        w.show_signin()
        w.root.update()
        assert _requested_focus(w) == str(_entries(w)[1])

    @_MAC_FOCUS
    def test_enter_in_the_url_field_is_next(self, make_wizard):
        w = make_wizard()
        calls = []
        w._on_role_next = lambda: calls.append("next")
        w.dashboard_url_var.set("")  # CCSYNC_DASHBOARD_URL may prefill it here
        w.show_role()
        w.root.update()
        entry = _entries(w)[0]
        assert _requested_focus(w) == str(entry)
        entry.focus_force()
        w.root.update()
        entry.event_generate("<Return>")
        w.root.update()
        assert calls == ["next"]
        # A prefilled (scripted) url starts on NEXT instead.
        w.dashboard_url_var.set("http://nas:8480")
        w.show_role()
        w.root.update()
        assert "NEXT" in str(w.root.nametowidget(_requested_focus(w)).cget("text"))


# -- ui-onboarding-10 ----------------------------------------------------------


class TestWrongAccountRefusal:
    def test_it_does_not_ask_for_a_sign_in_that_already_happened(self):
        msg = steps.console_user_mismatch("STUDIO\\leso", "administrator")
        assert "Sign in as leso" not in msg
        assert "leso does not need to sign in again" in msg
        assert "double-clicking" in msg and "Run as administrator" in msg
        assert "—" not in msg

    def test_the_bootstrap_twin_says_the_same_thing(self):
        src = (REPO / "installer" / "windows_bootstrap.ps1").read_text(encoding="utf-8")
        assert "Sign in as $signedIn and run it again" not in src
        assert "$signedIn does not need to sign in again" in src


# -- ui-onboarding-11 ----------------------------------------------------------


def test_the_wizard_tells_the_bootstrap_it_ran_it(tmp_path):
    for plat, name in (("win32", "windows_bootstrap.ps1"), ("darwin", "macos_bootstrap.sh")):
        script = tmp_path / name
        script.write_text("# stub\n", encoding="utf-8")
        seen = {}

        def run(cmd, **kwargs):
            seen["env"] = kwargs.get("env") or {}
            return _Result(0, "", "")

        steps.run_bootstrap(editor_name="ana", dashboard_token="t", tailnet_host="nas",
                            dashboard_url="http://nas:8480", site={}, platform=plat,
                            script_path=script, run=run)
        assert seen["env"].get(steps.FROM_WIZARD_ENV) == "1", plat


def test_both_bootstraps_read_the_wizard_marker():
    ps1 = (REPO / "installer" / "windows_bootstrap.ps1").read_text(encoding="utf-8")
    sh = (REPO / "installer" / "macos_bootstrap.sh").read_text(encoding="utf-8")
    assert f"$env:{steps.FROM_WIZARD_ENV}" in ps1
    assert steps.FROM_WIZARD_ENV in sh
    # The banner goes through the wizard-aware helper, not the old literal list.
    assert ps1.count("Remaining manual steps (see docs/EDITOR_SETUP.md)") == 1
    assert sh.count("Remaining manual steps (see docs/EDITOR_SETUP.md)") == 1
    assert "    print_first_setup_steps\n" in sh


# -- ui-onboarding-12 ----------------------------------------------------------


class TestOneRequestAtATime:
    def _signin(self, make_wizard, monkeypatch, result):
        gate = threading.Event()
        calls = []

        def verify_account(url, user, pw, *a, **k):
            calls.append(user)
            gate.wait(5)
            return dict(result)

        monkeypatch.setattr(steps, "verify_account", verify_account)
        monkeypatch.setattr(steps, "fetch_site", lambda *a, **k: {})
        w = make_wizard()
        w.dashboard_url_var.set("http://nas:8480")
        w.username_var.set("ana")
        w.password_var.set("pw")
        w.show_signin()
        return w, gate, calls

    def test_a_double_click_verifies_once(self, make_wizard, monkeypatch):
        w, gate, calls = self._signin(make_wizard, monkeypatch, {"ok": False, "error": "no"})
        verify_btn = _buttons(w, "VERIFY")[0]
        w._on_verify()
        w._on_verify()
        assert str(verify_btn.cget("state")) == "disabled"
        gate.set()
        _settle(w)
        assert calls == ["ana"]
        assert str(verify_btn.cget("state")) == "normal"

    def test_a_result_for_a_page_that_was_left_is_dropped(self, make_wizard, monkeypatch):
        w, gate, calls = self._signin(
            make_wizard, monkeypatch, {"ok": True, "username": "ana", "token": "tok"})
        installs = []
        w.show_install = lambda: installs.append(1)
        w._on_verify()
        w.show_role()  # BACK while the sign-in is in flight
        gate.set()
        _settle(w)
        assert installs == [], "a stale sign-in jumped the editor to the install page"

    def test_check_connection_runs_once_at_a_time(self, make_wizard, monkeypatch):
        gate = threading.Event()
        calls = []

        def tailscale_up(*a, **k):
            calls.append(1)
            gate.wait(5)
            return True

        monkeypatch.setattr(steps, "tailscale_up", tailscale_up)
        monkeypatch.setattr(steps, "dashboard_probe", lambda *a, **k: {"ok": True})
        w = make_wizard()
        w.dashboard_url_var.set("http://nas:8480")
        w.show_tailscale()
        check_btn = _buttons(w, "CHECK CONNECTION")[0]
        w._on_check_connection()
        w._on_check_connection()
        assert str(check_btn.cget("state")) == "disabled"
        gate.set()
        _settle(w)
        assert calls == [1]
        assert str(_buttons(w, "NEXT")[0].cget("state")) == "normal"
        assert str(check_btn.cget("state")) == "normal"

    # Review round (2026-09-25): the guard was a boolean, so BACK during a
    # sign-in and NEXT again built a NEW sign-in page whose VERIFY only said
    # "still verifying the last attempt..." and did nothing, and the old
    # result (dropped: different page) never updated the new page. Keyed on
    # the page now: the new page starts its own request at once.
    def test_a_revisited_signin_page_is_not_stuck_behind_the_old_attempt(
            self, make_wizard, monkeypatch):
        gates = [threading.Event(), threading.Event()]
        calls = []
        done = []

        def verify_account(url, user, pw, *a, **k):
            n = len(calls)
            calls.append(user)
            gates[min(n, 1)].wait(5)
            done.append(n)
            if n == 0:
                return {"ok": False, "error": "old attempt"}
            return {"ok": False, "error": "new attempt"}

        monkeypatch.setattr(steps, "verify_account", verify_account)
        monkeypatch.setattr(steps, "fetch_site", lambda *a, **k: {})
        w = make_wizard()
        w.dashboard_url_var.set("http://nas:8480")
        w.username_var.set("ana")
        w.password_var.set("pw")
        w.show_signin()
        w._on_verify()                   # attempt 1, in flight
        w.show_role()                    # BACK
        w.show_signin()                  # and forward again: a new page
        new_btn = _buttons(w, "VERIFY")[0]
        assert str(new_btn.cget("state")) == "normal"
        w.password_var.set("pw")
        w._on_verify()                   # attempt 2 starts, not ignored
        _pump_until(w, lambda: len(calls) == 2)
        assert calls == ["ana", "ana"]
        assert "still verifying" not in w.signin_status_lbl.cget("text")
        assert str(new_btn.cget("state")) == "disabled"
        gates[0].set()                   # the old result lands: dropped
        _pump_until(w, lambda: done == [0])
        assert str(new_btn.cget("state")) == "disabled",             "the abandoned attempt re-enabled the new page's button mid-request"
        assert "old attempt" not in w.signin_status_lbl.cget("text")
        gates[1].set()                   # the new result lands on the new page
        _settle(w)
        assert "new attempt" in w.signin_status_lbl.cget("text")
        assert str(new_btn.cget("state")) == "normal"

    def test_a_revisited_tailscale_page_checks_at_once(self, make_wizard, monkeypatch):
        gates = [threading.Event(), threading.Event()]
        calls = []
        done = []

        def tailscale_up(*a, **k):
            n = len(calls)
            calls.append(1)
            gates[min(n, 1)].wait(5)
            done.append(n)
            return True

        monkeypatch.setattr(steps, "tailscale_up", tailscale_up)
        monkeypatch.setattr(steps, "dashboard_probe", lambda *a, **k: {"ok": True})
        w = make_wizard()
        w.dashboard_url_var.set("http://nas:8480")
        w.show_tailscale()
        w._on_check_connection()         # check 1, in flight
        w.show_role()
        w.show_tailscale()               # a new page
        check_btn = _buttons(w, "CHECK CONNECTION")[0]
        w._on_check_connection()         # check 2 starts, not ignored
        _pump_until(w, lambda: len(calls) == 2)
        assert len(calls) == 2
        gates[0].set()
        _pump_until(w, lambda: done == [0])
        assert str(check_btn.cget("state")) == "disabled"
        gates[1].set()
        _settle(w)
        assert str(check_btn.cget("state")) == "normal"
        assert str(_buttons(w, "NEXT")[0].cget("state")) == "normal"


# --- owed round: ui-onboarding-9 (from c-ui) ------------------------------------------


def test_wizard_input_and_box_outlines_use_the_field_border_colour():
    """ui-onboarding-9 (2026-09-25): RED_DIM outlines measured 1.86:1 on BG and 1.69:1
    on FIELD, under the 3:1 a component boundary needs. c-ui added theme.FIELD_BORDER;
    the wizard's four outlines (the Entry helper, the licence box, the log box and the
    readonly field) use it. The RULE label under each heading stays RED_DIM (text
    decoration, not a boundary)."""
    import re

    from ccsync_companion import theme

    assert hasattr(theme, "FIELD_BORDER")
    assert not re.search(r"highlightbackground\s*=\s*theme\.RED_DIM", ONBOARD_SRC)
    assert len(re.findall(r"highlightbackground\s*=\s*theme\.FIELD_BORDER", ONBOARD_SRC)) >= 4
    assert "text=theme.RULE, bg=theme.BG, fg=theme.RED_DIM" in ONBOARD_SRC
