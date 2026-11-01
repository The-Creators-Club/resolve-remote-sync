"""GL-32 / CR-375 (2026-10-07): psycopg2 (LGPL) loads from a replaceable dir.

The build.spec half is pinned as text because a PyInstaller build cannot run
in a unit test; a frozen build is verified by hand (see KNOWN_BUGS CR-375).
"""

import sys
from pathlib import Path

import pytest

from ccsync_companion import lgpl_libs

SPEC = Path(__file__).resolve().parents[1] / "build.spec"


@pytest.fixture(autouse=True)
def _restore_path():
    saved = list(sys.path)
    yield
    sys.path[:] = saved


def test_source_checkout_adds_nothing(monkeypatch, tmp_path):
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    monkeypatch.setenv(lgpl_libs.ENV_VAR, str(tmp_path / "absent"))
    before = list(sys.path)
    assert lgpl_libs.activate() == []
    assert sys.path == before


def test_user_dir_wins_over_bundled(monkeypatch, tmp_path):
    bundle = tmp_path / "mei"
    (bundle / lgpl_libs.BUNDLED_SUBDIR).mkdir(parents=True)
    user = tmp_path / "userlib"
    user.mkdir()
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    monkeypatch.setenv(lgpl_libs.ENV_VAR, str(user))
    added = lgpl_libs.activate()
    assert added == [str(user), str(bundle / lgpl_libs.BUNDLED_SUBDIR)]
    assert sys.path[0] == str(user)
    assert sys.path[1] == str(bundle / lgpl_libs.BUNDLED_SUBDIR)


def test_user_copy_is_the_one_imported(monkeypatch, tmp_path):
    user = tmp_path / "userlib"
    pkg = user / "lgpl_probe_pkg_cr375"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("WHERE = 'user'\n")
    monkeypatch.setenv(lgpl_libs.ENV_VAR, str(user))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    lgpl_libs.activate()
    import importlib
    mod = importlib.import_module("lgpl_probe_pkg_cr375")
    try:
        assert mod.WHERE == "user"
    finally:
        sys.modules.pop("lgpl_probe_pkg_cr375", None)


def test_activate_is_idempotent_and_never_raises(monkeypatch, tmp_path):
    user = tmp_path / "u"
    user.mkdir()
    monkeypatch.setenv(lgpl_libs.ENV_VAR, str(user))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    lgpl_libs.activate()
    lgpl_libs.activate()
    assert sys.path.count(str(user)) == 1
    monkeypatch.setattr(lgpl_libs, "search_dirs",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert lgpl_libs.activate() == []


def test_role_activates_before_importing_engine():
    src = (Path(lgpl_libs.__file__).parent / "timeline_cards_role.py").read_text(encoding="utf-8")
    body = src[src.index("def load_engine"):]
    assert body.index("lgpl_libs.activate()") < body.index("importlib.import_module")


def test_build_spec_keeps_psycopg2_out_of_the_archive():
    spec = SPEC.read_text(encoding="utf-8")
    assert '"psycopg2", "zstandard"]' not in spec     # no hidden import
    assert 'excludes=["setuptools", "pkg_resources", "_distutils_hack",' in spec
    assert '"psycopg2"],' in spec                     # excluded from analysis
    assert "+ lgpl_datas" in spec                     # shipped as plain files
    assert '"ccsync_lib"' in spec
    assert lgpl_libs.BUNDLED_SUBDIR == "ccsync_lib"
