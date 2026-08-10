from __future__ import annotations

import json

import pytest
import yaml

from broll_index.taxonomy import apply_taxonomy_file, load_taxonomy_file, propose_taxonomy


def test_propose_taxonomy_writes_file(tmp_path, sqlite_storage):
    vid = sqlite_storage.upsert_video("broll", "clip.mov", status="proxied")
    sqlite_storage.write_index_result(
        vid,
        themes=["naval exercise", "harbor"],
        quality_flags=[],
        category_hint=None,
        segments=[],
        model="m",
    )

    def fake_invoke(prompt, model):
        assert "naval exercise" in prompt
        return json.dumps({"type": "result", "result": "# Proposed taxonomy\n- military/naval"})

    out_path = tmp_path / "taxonomy_proposal.md"
    result_path = propose_taxonomy(sqlite_storage, model="sonnet", out_path=out_path, invoke=fake_invoke)
    assert result_path == out_path
    assert "military/naval" in out_path.read_text(encoding="utf-8")


def test_propose_taxonomy_raises_without_themes(sqlite_storage):
    with pytest.raises(ValueError, match="no themes"):
        propose_taxonomy(sqlite_storage, invoke=lambda p, m: "")


def test_load_taxonomy_file_accepts_bare_list(tmp_path):
    path = tmp_path / "taxonomy.yaml"
    path.write_text(
        yaml.safe_dump([{"slug": "military/naval", "label": "Naval", "description": "ships"}]),
        encoding="utf-8",
    )
    categories = load_taxonomy_file(path)
    assert categories == [{"slug": "military/naval", "label": "Naval", "description": "ships"}]


def test_load_taxonomy_file_accepts_categories_key(tmp_path):
    path = tmp_path / "taxonomy.yaml"
    path.write_text(
        yaml.safe_dump({"categories": [{"slug": "a/b", "label": "AB"}]}),
        encoding="utf-8",
    )
    categories = load_taxonomy_file(path)
    assert categories == [{"slug": "a/b", "label": "AB"}]


def test_load_taxonomy_file_rejects_missing_keys(tmp_path):
    path = tmp_path / "taxonomy.yaml"
    path.write_text(yaml.safe_dump([{"slug": "a/b"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="missing keys"):
        load_taxonomy_file(path)


def test_apply_taxonomy_file_writes_to_storage(tmp_path, sqlite_storage):
    path = tmp_path / "taxonomy.yaml"
    path.write_text(
        yaml.safe_dump([{"slug": "military/naval", "label": "Naval", "description": "ships"}]),
        encoding="utf-8",
    )
    categories = apply_taxonomy_file(sqlite_storage, path)
    assert len(categories) == 1
    assert sqlite_storage.get_categories() == [
        {"slug": "military/naval", "label": "Naval", "description": "ships"}
    ]
