"""The two dataset names the dashboard's protection panel checks against.

2026-09-03. `ccsync_dashboard/protection.py` has checked the NAS's snapshot
schedule against DASH_TREE_DATASET and DASH_UPDATE_SNAPSHOT_DATASET since the
2026-08-28 resilience sweep, and told every operator to "set DASH_TREE_DATASET
on the dashboard container" when they were unset. Nothing set them: this
script builds the container's whole environment from an explicit dict and had
no source for either name, so `protection_unverifiable` could not be cleared
by an operator. `docker inspect` on the live container confirmed both absent.

Offline, like the rest of this suite; run from GIT BASH (see CLAUDE.md).

    cd E:\\Projects\\resolve-remote-sync\\server
    ../dashboard/.venv/Scripts/python.exe -m pytest tests/test_protection_datasets.py -q
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402
import install_dashboard_app as ida  # noqa: E402
from backends.truenas import TrueNASBackend  # noqa: E402
from tests.fake_dsm import FakeSsh  # noqa: E402

HOST_ROOT = "/mnt/tank/apps/ccsync-dashboard"
TREE_ROOT = "/mnt/tank/TheCreatorsPool/Creators_Club"


def _truenas(ssh=None):
    module = type(sys)("fake_script")
    module.run_ssh = ssh or FakeSsh()
    return TrueNASBackend(calls=common.ScriptCalls(module))


def _no_site_keys(monkeypatch):
    """A manifest that names neither dataset -- the shipped state everywhere."""
    monkeypatch.setattr(ida, "site_value", lambda s, k, d="": "")


# --------------------------------------------------------------------------
# the manifest wins
# --------------------------------------------------------------------------

def test_the_site_manifest_names_both_datasets(monkeypatch):
    named = {("tree", "dataset"): "tank/TheCreatorsPool",
             ("apps", "dataset"): "tank"}
    monkeypatch.setattr(ida, "site_value",
                        lambda s, k, d="": named.get((s, k), d))
    monkeypatch.setattr(ida, "probe_dataset",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("a named dataset must not be probed")))
    env = ida.datasets_env(TREE_ROOT, HOST_ROOT, probe=True)
    assert env == {"DASH_TREE_DATASET": "tank/TheCreatorsPool",
                   "DASH_UPDATE_SNAPSHOT_DATASET": "tank"}


def test_a_named_dataset_beats_what_the_nas_answers(monkeypatch):
    """An operator who wrote the key meant it: the probe is the fallback, not
    the authority."""
    monkeypatch.setattr(ida, "site_value",
                        lambda s, k, d="": ("tank/Elsewhere"
                                            if (s, k) == ("tree", "dataset") else d))
    monkeypatch.setattr(ida, "probe_dataset", lambda path, dry_run=False: "tank/Wrong")
    env = ida.datasets_env(TREE_ROOT, HOST_ROOT, probe=True)
    assert env["DASH_TREE_DATASET"] == "tank/Elsewhere"
    # ...and the key that was NOT named still takes the probe's answer.
    assert env["DASH_UPDATE_SNAPSHOT_DATASET"] == "tank/Wrong"


# --------------------------------------------------------------------------
# derived from the NAS when the manifest says nothing
# --------------------------------------------------------------------------

def test_the_deploy_derives_both_from_the_paths_it_already_has(monkeypatch):
    """The tree root IS a dataset here; the apps root is a plain folder inside
    the bare pool, and `tank` is the correct answer for it rather than a
    lie -- a snapshot task on `tank` covers files living directly in it."""
    seen = {}

    def probe(path, dry_run=False):
        seen[path] = True
        return "tank/TheCreatorsPool" if path == TREE_ROOT else "tank"

    _no_site_keys(monkeypatch)
    monkeypatch.setattr(ida, "probe_dataset", probe)
    env = ida.datasets_env(TREE_ROOT, HOST_ROOT, probe=True)
    assert env == {"DASH_TREE_DATASET": "tank/TheCreatorsPool",
                   "DASH_UPDATE_SNAPSHOT_DATASET": "tank"}
    assert seen == {TREE_ROOT: True, HOST_ROOT: True}


def test_nothing_is_asked_of_the_nas_unless_the_caller_says_so(monkeypatch):
    """Rendering a compose body must never open an SSH session: only the real
    deploy passes probe=True, from a place where a session already exists."""
    _no_site_keys(monkeypatch)
    monkeypatch.setattr(ida, "probe_dataset",
                        lambda *a, **kw: (_ for _ in ()).throw(
                            AssertionError("no probe without probe=True")))
    assert ida.datasets_env(TREE_ROOT, HOST_ROOT) == {
        "DASH_TREE_DATASET": "", "DASH_UPDATE_SNAPSHOT_DATASET": ""}


def test_the_probe_asks_the_backend_and_returns_what_it_says(monkeypatch):
    ssh = FakeSsh(answers=[("df", (0, "tank\n", ""))])
    monkeypatch.setattr(ida, "backend", lambda: _truenas(ssh))
    assert ida.probe_dataset(HOST_ROOT) == "tank"
    assert any("df --output=source" in c for c in ssh.commands)


# --------------------------------------------------------------------------
# a lookup that cannot answer says nothing, which reads as NOT CHECKED
# --------------------------------------------------------------------------

def test_a_refused_lookup_is_blank_rather_than_a_guess(monkeypatch):
    """`tank/apps/ccsync-dashboard` is not a dataset. Passing that string would
    turn the panel's honest CANNOT VERIFY into MISSING BACKUP on a server that
    has one -- the one failure mode worse than saying nothing."""
    ssh = FakeSsh(answers=[("df", (1, "", "df: Permission denied"))])
    monkeypatch.setattr(ida, "backend", lambda: _truenas(ssh))
    assert ida.probe_dataset(HOST_ROOT) == ""
    # ...and the un-strict caller (every snapshot in this package) is unchanged.
    assert _truenas(ssh).resolve_dataset(HOST_ROOT, False) == \
        "tank/apps/ccsync-dashboard"


def test_a_dry_run_and_a_synology_both_answer_blank(monkeypatch):
    monkeypatch.setattr(ida, "backend", lambda: _truenas())
    assert ida.probe_dataset(HOST_ROOT, dry_run=True) == ""

    class NoZfs:
        pass

    monkeypatch.setattr(ida, "backend", NoZfs)
    assert ida.probe_dataset(HOST_ROOT) == ""


def test_a_backend_that_raises_does_not_fail_the_deploy(monkeypatch):
    class Angry:
        def resolve_dataset(self, path, dry_run, strict=False):
            raise OSError("no route to host")

    monkeypatch.setattr(ida, "backend", Angry)
    assert ida.probe_dataset(TREE_ROOT) == ""


def test_the_strict_flag_is_what_drops_the_guess():
    """The backend half, directly: strict returns "" wherever the ordinary
    call returns string surgery instead of the NAS's own answer."""
    ssh = FakeSsh(answers=[("df", (0, "/dev/sda1\n", ""))])
    backend = _truenas(ssh)
    assert backend.resolve_dataset(HOST_ROOT, False) == "tank/apps/ccsync-dashboard"
    assert backend.resolve_dataset(HOST_ROOT, False, strict=True) == ""
    # A path with no /mnt prefix has no dataset under either rule.
    assert backend.resolve_dataset("/var/tmp", False, strict=True) == ""


# --------------------------------------------------------------------------
# and they reach the container
# --------------------------------------------------------------------------

def _dashboard_env(**kw):
    body = ida.compose_config(8480, HOST_ROOT, "http://gui:8384", "k", "t", **kw)
    return body["services"]["dashboard"]["environment"]


def test_the_compose_body_always_carries_both_keys():
    env = _dashboard_env()
    assert env["DASH_TREE_DATASET"] == ""
    assert env["DASH_UPDATE_SNAPSHOT_DATASET"] == ""


def test_the_deploy_can_pass_the_names_it_looked_up():
    env = _dashboard_env(tree_dataset="tank/TheCreatorsPool", apps_dataset="tank")
    assert env["DASH_TREE_DATASET"] == "tank/TheCreatorsPool"
    assert env["DASH_UPDATE_SNAPSHOT_DATASET"] == "tank"


def test_a_manifest_key_reaches_the_container_with_no_lookup_at_all(monkeypatch):
    monkeypatch.setattr(ida, "site_value",
                        lambda s, k, d="": ("tank/TheCreatorsPool"
                                            if (s, k) == ("tree", "dataset") else d))
    assert _dashboard_env()["DASH_TREE_DATASET"] == "tank/TheCreatorsPool"


def test_the_compose_file_and_the_dict_describe_the_same_datasets():
    """The FILE an operator pastes (Synology, and the manual YAML fallback) and
    the DICT the TrueNAS middleware stores must not disagree."""
    variables = ida.compose_variables(tree_dataset="tank/TheCreatorsPool",
                                      apps_dataset="tank")
    assert variables["DASH_TREE_DATASET"] == "tank/TheCreatorsPool"
    assert variables["DASH_UPDATE_SNAPSHOT_DATASET"] == "tank"
    rendered = ida.render_compose_yaml(variables)
    assert 'DASH_TREE_DATASET: "tank/TheCreatorsPool"' in rendered
    assert 'DASH_UPDATE_SNAPSHOT_DATASET: "tank"' in rendered
