"""A batch says what is happening to it, in words, and both renderers agree.

BROLL-22 of the usability + resilience sweep (2026-09-03), built 2026-09-04.

The card used to print the database's own enum beside the machine and a
heartbeat: `queued - creator-2 - heartbeat 3 hours ago`, which reads as
progress and in fact means that computer stopped answering and nothing at all
is happening. `expire_stale_leases`'s docstring even says `machine` is
"deliberately LEFT in place so the SPA can still say 'waiting for <machine>'";
the SPA never said it.

There are two renderers on purpose - the server's, for every reader that is
not the ingest panel, and the page's, so its "3h ago" keeps ageing between
five-second polls - so the templates are pinned as a PAIR here. One wording,
two renderers, and neither is allowed to drift.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app import ingest_batches

INGEST_JS = (Path(__file__).resolve().parents[1] / "static" / "ingest.js").read_text(
    encoding="utf-8")

_JS_TABLE = re.compile(r"const ING_BATCH_STATE_TEXT = \{(.*?)\n\};", re.S)
_JS_ENTRY = re.compile(r'"([a-z_]+)":\s*"([^"]*)"')


def _js_table() -> dict[str, str]:
    block = _JS_TABLE.search(INGEST_JS)
    assert block, "ING_BATCH_STATE_TEXT is the page's half of the mapping"
    return dict(_JS_ENTRY.findall(block.group(1)))


def _row(**over):
    row = {"state": "queued", "machine": None, "last_heartbeat_at": None,
           "cancel_requested": 0, "n_failed": 0}
    row.update(over)
    return row


# --- the two tables are one table ---------------------------------------------

def test_the_page_and_the_server_hold_the_same_words():
    assert _js_table() == ingest_batches.BATCH_STATE_TEXT


def test_every_batch_state_has_a_sentence():
    for state in ingest_batches.BATCH_STATES:
        assert state in ingest_batches.BATCH_STATE_TEXT, state


def test_none_of_the_words_is_an_enum_or_carries_an_em_dash():
    for state, text in ingest_batches.BATCH_STATE_TEXT.items():
        assert "—" not in text
        assert "_" not in text.replace("{n_failed}", ""), (
            f"{state} still reads as a database token")


# --- what the server renders ---------------------------------------------------

def test_a_queued_batch_nobody_has_taken_is_waiting_to_start():
    assert ingest_batches.batch_state_text(_row()) == "waiting to start"


def test_a_queued_batch_with_a_machine_says_that_machine_stopped_answering():
    now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    row = _row(machine="creator-2",
               last_heartbeat_at=(now - timedelta(hours=3)).isoformat())
    assert ingest_batches.batch_state_text(row, now=now) == (
        "waiting: creator-2 stopped answering 3h ago")


def test_a_running_batch_names_the_machine_it_is_on():
    assert ingest_batches.batch_state_text(
        _row(state="running", machine="EDIT-01")) == "indexing on EDIT-01"


def test_a_finished_batch_with_failures_counts_them():
    assert ingest_batches.batch_state_text(
        _row(state="done_with_errors", n_failed=12)) == (
        "finished, 12 could not be indexed")


def test_a_pending_cancel_outranks_the_state_it_is_cancelling():
    """The row still says `running` for one more heartbeat, and "indexing on
    EDIT-01" is not what is happening to a batch somebody just stopped."""
    assert ingest_batches.batch_state_text(
        _row(state="running", machine="EDIT-01", cancel_requested=1)) == "stopping"


def test_an_unknown_state_shows_its_token_rather_than_a_blank_line():
    assert ingest_batches.batch_state_text(_row(state="teleported")) == "teleported"


@pytest.mark.parametrize("seconds, expected", [
    (0, "0s ago"), (89, "89s ago"), (90, "2m ago"), (5399, "90m ago"),
    (5400, "2h ago"),
])
def test_the_ago_thresholds_are_the_pages_own(seconds, expected):
    now = datetime(2026, 9, 4, 12, 0, tzinfo=timezone.utc)
    then = (now - timedelta(seconds=seconds)).isoformat()
    assert ingest_batches.ago_text(then, now=now) == expected


def test_a_heartbeat_that_never_happened_is_never():
    assert ingest_batches.ago_text(None) == "never"


# --- and it travels on the wire -----------------------------------------------

def test_the_batch_payload_carries_the_sentence(client, conn):
    client.headers.update({"X-CCSync-User": "jsmith"})
    client.post("/api/ingest-batches", json={
        "share": "E2E", "settings": {"tier": "good"},
        "items": [{"local_id": "l0", "name": "A000.MP4", "size": 1, "hash": None,
                   "source": "upload", "rel_dir": ""}]})
    batch = client.get("/api/ingest-batches?scope=mine").json()["batches"][0]
    assert batch["state_text"] == "waiting to start"


def test_the_page_renders_the_state_through_the_shared_helper():
    card = INGEST_JS[INGEST_JS.index("function ingestRenderBatches"):]
    card = card[:card.index("\n}\n")]
    assert "ingestBatchStateText(batch)" in card
    assert "text: batch.state }" not in card, "the raw enum is what this replaced"


def test_the_counters_are_in_words_not_index_jargon():
    """`n_live` means "in the archive and searchable", which no editor was
    ever going to guess."""
    counts = INGEST_JS[INGEST_JS.index("function ingestBatchCounts"):]
    counts = counts[:counts.index("\n}\n")]
    assert "searchable" in counts
    assert "already in the archive" in counts
