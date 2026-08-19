"""This computer's minted id (machine.py, MULTI_MACHINE_PLAN.md WP1)."""

import json

from ccsync_companion import machine as machine_mod


def test_the_id_is_minted_once_and_then_reused(tmp_path):
    """An id that changed every run would be worse than none: the dashboard
    would read each report as another new computer with an empty plan."""
    path = tmp_path / "machine.json"

    first = machine_mod.machine_id(path)
    second = machine_mod.machine_id(path)

    assert first and first == second
    assert json.loads(path.read_text(encoding="utf-8"))["machine_id"] == first


def test_it_is_not_derived_from_anything_about_the_hardware(tmp_path):
    """Two machines, two ids -- and nothing that survives a reimage or
    changes under a NIC swap (see the module docstring)."""
    a = machine_mod.machine_id(tmp_path / "a.json")
    b = machine_mod.machine_id(tmp_path / "b.json")
    assert a != b


def test_create_false_does_not_write(tmp_path):
    path = tmp_path / "machine.json"
    assert machine_mod.machine_id(path, create=False) == ""
    assert not path.exists()


def test_an_unwritable_home_reports_no_id_rather_than_raising(tmp_path):
    """Never-raise ethos: a machine that cannot persist an id still reports
    and still syncs. It must NOT return an id it failed to save."""
    path = tmp_path / "nope" / "machine.json"
    path.parent.mkdir()
    path.parent.chmod(0o500)
    try:
        result = machine_mod.machine_id(path)
    finally:
        path.parent.chmod(0o700)
    # Windows ignores the mode bits, so accept either outcome -- what is
    # pinned is that it never raises and never invents an unsaved id.
    assert result == "" or (path.exists() and result)


def test_a_corrupt_file_is_replaced_rather_than_fatal(tmp_path):
    path = tmp_path / "machine.json"
    path.write_text("{not json", encoding="utf-8")

    minted = machine_mod.machine_id(path)

    assert minted
    assert json.loads(path.read_text(encoding="utf-8"))["machine_id"] == minted


def test_it_lives_beside_identity_not_under_state(tmp_path):
    """~/.ccsync/machine.json: state/ is the directory a support session is
    most likely to be told to delete, and this has to outlive that."""
    assert machine_mod.machine_path(tmp_path) == tmp_path / "machine.json"
