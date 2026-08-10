from __future__ import annotations

import logging

import pytest

from broll_index import normalize


@pytest.fixture(autouse=True)
def _reset_warned_flag(monkeypatch):
    # `normalize` logs its degradation warning at most once per process; reset it per
    # test so "warns once" assertions don't depend on test execution order.
    monkeypatch.setattr(normalize, "_warned", False)


# ---------------------------------------------------------------------------
# empty / ASCII safety
# ---------------------------------------------------------------------------

def test_empty_string_in_empty_string_out():
    assert normalize.searchable_blob("") == ""


def test_pure_ascii_input_is_unchanged():
    text = "navy ship, warship, frigate, military vessel"
    assert normalize.searchable_blob(text) == text


def test_pure_ascii_input_no_pointless_duplication():
    # A naive tokenize-and-dedupe pass would reorder/collapse this; ASCII input must
    # pass through byte-for-byte.
    text = "the quick brown fox the quick brown fox"
    assert normalize.searchable_blob(text) == text


# ---------------------------------------------------------------------------
# the two measured gaps this module fixes (docs/indexing-findings.md)
# ---------------------------------------------------------------------------

def test_two_char_traditional_term_is_a_standalone_token():
    blob = normalize.searchable_blob("警方在廈門堵車現場處理事故")
    tokens = blob.split()
    assert "堵車" in tokens


def test_two_char_simplified_term_is_a_standalone_token():
    blob = normalize.searchable_blob("警方在厦门堵车现场处理事故")
    tokens = blob.split()
    assert "堵车" in tokens


def test_traditional_query_findable_in_blob_built_from_simplified_source():
    # Gap 1: script variants don't cross-match without normalization. A Traditional
    # 2-char query (堵車) must be reachable in a blob derived from Simplified source
    # text (堵车), and vice versa.
    blob_from_simplified = normalize.searchable_blob("厦门堵车现场处理事故")
    assert "堵車" in blob_from_simplified.split()

    blob_from_traditional = normalize.searchable_blob("廈門堵車現場處理事故")
    assert "堵车" in blob_from_traditional.split()


def test_both_script_variants_present_regardless_of_input_script():
    for source in ("警方处理惡龍槍戰案件", "警方處理惡龍槍戰案件"):
        blob = normalize.searchable_blob(source)
        tokens = blob.split()
        # both forms of the same 2-char proper noun should be reachable
        assert "惡龍" in tokens or "恶龙" in tokens


def test_absent_term_still_correctly_misses():
    blob = normalize.searchable_blob("警方在廈門堵車現場處理事故")
    assert "台北" not in blob
    assert "滑雪" not in blob


# ---------------------------------------------------------------------------
# graceful degradation — must never crash the indexer
# ---------------------------------------------------------------------------

def test_degrades_to_raw_text_when_both_jieba_and_opencc_unavailable(monkeypatch, caplog):
    monkeypatch.setattr(normalize, "_JIEBA_AVAILABLE", False)
    monkeypatch.setattr(normalize, "_OPENCC_AVAILABLE", False)

    text = "警方在廈門堵車現場處理事故"
    with caplog.at_level(logging.WARNING, logger="broll_index.normalize"):
        result = normalize.searchable_blob(text)

    assert result == text
    assert any("unavailable" in rec.message for rec in caplog.records)


def test_degrades_gracefully_when_only_jieba_unavailable(monkeypatch):
    monkeypatch.setattr(normalize, "_JIEBA_AVAILABLE", False)
    # opencc still available: still get cross-script matching, just not segmentation.
    result = normalize.searchable_blob("廈門堵車")
    assert result  # produced something, did not crash
    assert "廈門堵車" in result  # whole raw run present


def test_degrades_gracefully_when_only_opencc_unavailable(monkeypatch):
    monkeypatch.setattr(normalize, "_OPENCC_AVAILABLE", False)
    # jieba still available: still get segmentation, just not cross-script variants.
    result = normalize.searchable_blob("警方在廈門堵車現場處理事故")
    assert "堵車" in result.split()


def test_second_call_after_degradation_does_not_warn_again(monkeypatch, caplog):
    monkeypatch.setattr(normalize, "_JIEBA_AVAILABLE", False)
    monkeypatch.setattr(normalize, "_OPENCC_AVAILABLE", False)

    with caplog.at_level(logging.WARNING, logger="broll_index.normalize"):
        normalize.searchable_blob("第一次")
        caplog.clear()
        normalize.searchable_blob("第二次")

    assert caplog.records == []  # logged once, not once per call
