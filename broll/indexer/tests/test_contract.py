"""`broll_index/contract.py`: the contract helpers after they moved out of
`claude_client.py` (2026-08-18, docs/BROLL_INGEST_PLAN.md §3.4).

The move exists so the local backend's modules can be vendored into the
companion without the Anthropic SDK. Two things therefore have to stay true,
and neither is visible in a normal test run:

  1. every old import path still resolves to the SAME OBJECT -- there are ~60
     call sites and tests importing these names from `claude_client`, and a
     re-export that quietly became a copy would let the two drift;
  2. `contract` imports nothing but the stdlib, and neither do
     `compact_format`/`local_vlm` beyond it -- an `anthropic` import anywhere
     in that set is 50 MB and a licence surface inside every editor's frozen
     tray app.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from broll_index import claude_client, compact_format, contract, local_vlm

PKG = Path(claude_client.__file__).resolve().parent

MOVED_NAMES = (
    "QUALITY_FLAG_VOCAB",
    "NO_VISUAL_LABELS",
    "canonicalize_no_visual_label",
    "validate_contract",
    "merge_index_results",
    "_normalize_onscreen_text",
)


@pytest.mark.parametrize("name", MOVED_NAMES)
def test_claude_client_re_exports_the_same_object(name):
    """Identity, not equality: a `from .contract import` that turned into a
    second definition would pass an equality check and still let the validator
    the Anthropic path uses drift from the one the local path uses."""
    assert getattr(claude_client, name) is getattr(contract, name)


def test_the_local_backend_imports_the_contract_not_claude_client():
    """`compact_format` and `local_vlm` must reach the contract WITHOUT going
    through claude_client -- that import is what would drag `anthropic` into
    the vendored set."""
    assert compact_format.validate_contract is contract.validate_contract
    assert local_vlm.merge_index_results is contract.merge_index_results


def _imported_modules(path: Path) -> set[str]:
    """Every module name this file imports, top-level statements included."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level:
            names.update(alias.name for alias in node.names)
    return names


VENDORED_SET = ("contract.py", "compact_format.py", "local_vlm.py",
                "local_runtime.py", "local_models.py")


@pytest.mark.parametrize("filename", VENDORED_SET)
def test_the_vendored_set_never_imports_claude_client_or_anthropic(filename):
    """The five modules the companion carries VERBATIM (plan §3.3). Their
    import list is the whole reason contract.py exists; a new import here is a
    new dependency in a frozen tray app on every editor machine, so it fails
    HERE, in the indexer's own suite, rather than at a PyInstaller build weeks
    later."""
    imported = _imported_modules(PKG / filename)
    forbidden = {"claude_client", "anthropic", "xxhash", "yaml", "requests", "jieba"}
    assert not (imported & forbidden), (
        f"{filename} imports {sorted(imported & forbidden)} -- that set is vendored "
        f"into the companion, which has none of them (docs/BROLL_INGEST_PLAN.md §3.3)")


def test_contract_itself_is_stdlib_only():
    imported = _imported_modules(PKG / "contract.py")
    assert imported <= {"__future__", "logging", "typing"}, sorted(imported)
