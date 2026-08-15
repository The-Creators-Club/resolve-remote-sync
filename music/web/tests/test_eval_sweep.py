"""`eval.py --sweep` must not write the index that ships.

MUSIC-4 (2026-08-14): the sweep called `tagging.write_scores` once per alpha
against `db.connect()` -- no argument, so `config.DB_PATH`, the very file
`install_dashboard_app.py --music-data db` pushes to the NAS. write_scores
opens with `DELETE FROM tags` / `DELETE FROM axes`, re-inserts and commits, so
a sweep left the live index scored at whatever alpha the loop ended on (1.0)
while `vocab.CALIBRATION` said 0.5 -- invisibly, since every row was present
and well-formed and `vocab_hash` deliberately does not cover CALIBRATION.

eval.py is loaded from its path here because `music/eval` is not a package, and
only the half that needs no torch is touched: `tagging` (and through it CLAP)
is imported inside the sweep, not at module scope, exactly so this venv can
reach `open_scratch_copy`.
"""
import importlib.util
import sys
import types

import pytest

from musicweb import config, db

EVAL_PY = config.MUSIC_DIR / 'eval' / 'eval.py'


@pytest.fixture(scope='module')
def evalmod():
    if not EVAL_PY.is_file():
        pytest.skip(f'no eval half checked out at {EVAL_PY}')
    spec = importlib.util.spec_from_file_location('music_eval', EVAL_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_scratch_copy_holds_the_library(evalmod, seeded_db, tmp_path):
    con, path = evalmod.open_scratch_copy(tmp_path)
    try:
        assert path.parent == tmp_path
        assert path != config.DB_PATH
        assert con.execute('SELECT COUNT(*) FROM tracks').fetchone()[0] == \
            db.connect().execute('SELECT COUNT(*) FROM tracks').fetchone()[0]
        assert con.execute('SELECT COUNT(*) FROM tags').fetchone()[0] > 0
    finally:
        con.close()


def test_scoring_into_the_copy_leaves_the_live_index_alone(evalmod, seeded_db,
                                                           tmp_path):
    """What write_scores does to whatever connection it is handed."""
    live = db.connect()
    try:
        before = live.execute('SELECT COUNT(*) FROM tags').fetchone()[0]
        con, _ = evalmod.open_scratch_copy(tmp_path)
        try:
            con.execute('DELETE FROM tags')
            con.execute('DELETE FROM axes')
            con.commit()
        finally:
            con.close()
        assert live.execute('SELECT COUNT(*) FROM tags').fetchone()[0] == before
    finally:
        live.close()


@pytest.fixture()
def fake_clap_stack(monkeypatch):
    """`tagging` and CLAP, faked into sys.modules.

    The sweep imports both INSIDE the function (they drag in torch, which this
    venv deliberately does not have), so standing them up here is what lets the
    loop itself be tested rather than only the copy it writes to.
    """
    from music_index import vocab

    scored = []
    tagging = types.ModuleType('music_index.tagging')
    tagging.build_label_space = lambda clap: ({}, {})
    tagging.score_all = lambda mat, cats, axes: ({}, {})
    tagging.write_scores = lambda con, ids, tags, ax: scored.append(vocab.CALIBRATION)
    clap_model = types.ModuleType('music_index.clap_model')
    clap_model.Clap = lambda *a, **kw: object()

    monkeypatch.setitem(sys.modules, 'music_index.tagging', tagging)
    monkeypatch.setitem(sys.modules, 'music_index.clap_model', clap_model)
    return scored


def test_the_sweep_scores_every_alpha_into_the_connection_it_is_given(
        evalmod, seeded_db, tmp_path, fake_clap_stack, monkeypatch):
    monkeypatch.setattr(evalmod, 'bias_report', lambda con, top=6: 0.0)
    con, _ = evalmod.open_scratch_copy(tmp_path)
    try:
        evalmod.sweep(con, alphas=(0.0, 0.5, 1.0))
    finally:
        con.close()
    assert fake_clap_stack == [0.0, 0.5, 1.0]


def test_the_sweep_restores_the_calibration_it_borrowed(
        evalmod, seeded_db, tmp_path, fake_clap_stack, monkeypatch):
    """CALIBRATION is a module global and the loop ends at 1.0, so leaving it
    there mis-scores anything else this interpreter goes on to do -- including
    the retag an operator runs next to undo the damage."""
    from music_index import vocab

    original = vocab.CALIBRATION
    monkeypatch.setattr(evalmod, 'bias_report',
                        lambda con, top=6: (_ for _ in ()).throw(
                            RuntimeError('interrupted mid-sweep')))
    con, _ = evalmod.open_scratch_copy(tmp_path)
    try:
        with pytest.raises(RuntimeError):
            evalmod.sweep(con, alphas=(1.0,))
    finally:
        con.close()
    assert vocab.CALIBRATION == original
