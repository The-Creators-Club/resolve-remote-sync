"""Group A of the account page (account page 2026-09-25,
docs/ACCOUNT_PAGE_FEATURES.md sections 2 and 7): schema v58 and the db.py
functions every other group calls by their pinned signatures."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
import unicodedata

import pytest

from ccsync_dashboard import db as dbmod

NOW = "2026-09-25T10:00:00+00:00"
LATER = "2026-09-25T10:05:00+00:00"


def _iso(days: float = 0.0) -> str:
    return (dt.datetime.fromisoformat(NOW) + dt.timedelta(days=days)).isoformat()


def _machine(conn, editor="tchen", machine="TCHEN-RIG", *, state=True):
    dbmod.upsert_machine(conn, editor, machine, now=NOW)
    if state:
        conn.execute(
            "INSERT OR IGNORE INTO machine_state (editor_username, machine, reported_at) "
            "VALUES (?, ?, ?)", (editor, machine, NOW))
    conn.commit()


def _columns(conn, table):
    return {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}


def _tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _audits(conn, action):
    return [r for r in dbmod.fetch_audit(conn, limit=1000) if r["action"] == action]


CFG = {"cfg_accepts", "cfg_jobs_volunteer_minutes", "cfg_drive_reminder_minutes",
       "cfg_youtube", "cfg_pending_restart", "cfg_at"}


# ---------------------------------------------------------------- schema v58

def test_v58_is_the_head_and_the_list_stays_gapless():
    numbers = [n for n, _ in dbmod._MIGRATION_STEPS]
    assert numbers == list(range(1, dbmod.SCHEMA_VERSION + 1))
    assert dbmod.SCHEMA_VERSION == 58
    assert dict(dbmod._MIGRATION_STEPS)[58] is dbmod.SCHEMA_V58


def test_v58_on_a_fresh_database(conn):
    assert {"user_profiles", "machine_setting_requests"} <= _tables(conn)
    assert CFG <= _columns(conn, "machine_state")
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 58


@pytest.mark.parametrize("start", [57, 50])
def test_v58_on_an_older_database_reaches_the_same_shape(tmp_path, start):
    old = dbmod.connect(tmp_path / f"v{start}.db")
    dbmod.migrate(old, [s for s in dbmod._MIGRATION_STEPS if s[0] <= start])
    assert old.execute("PRAGMA user_version").fetchone()[0] == start
    assert "user_profiles" not in _tables(old)
    dbmod.migrate(old)
    assert old.execute("PRAGMA user_version").fetchone()[0] == 58
    fresh = sqlite3.connect(":memory:")
    dbmod.migrate(fresh)
    assert _tables(old) == _tables(fresh)
    assert _columns(old, "machine_state") == _columns(fresh, "machine_state")
    old.close()


def test_migrate_twice_is_a_no_op(conn):
    dbmod.set_display_name(conn, "tchen", "T. Chen", by="tchen", now=NOW)
    conn.commit()
    dbmod.migrate(conn)
    dbmod.migrate(conn)
    assert dbmod.get_display_name(conn, "tchen") == "T. Chen"


def test_v58_interrupted_between_two_add_columns_replays(tmp_path):
    """The _already_applied path: the first ADD COLUMN landed, user_version
    stayed at 57 (the measured crash-loop shape)."""
    path = tmp_path / "partial.db"
    c = dbmod.connect(path)
    dbmod.migrate(c, [s for s in dbmod._MIGRATION_STEPS if s[0] <= 57])
    c.execute("ALTER TABLE machine_state ADD COLUMN cfg_accepts TEXT")
    c.execute("ALTER TABLE machine_state ADD COLUMN cfg_jobs_volunteer_minutes INTEGER")
    c.execute("CREATE TABLE user_profiles (username TEXT PRIMARY KEY, display_name TEXT "
              "NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL)")
    c.commit()
    assert c.execute("PRAGMA user_version").fetchone()[0] == 57
    dbmod.migrate(c)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 58
    assert CFG <= _columns(c, "machine_state")
    c.close()


def test_an_older_image_refuses_a_v58_database(tmp_path):
    c = dbmod.connect(tmp_path / "new.db")
    dbmod.migrate(c)
    with pytest.raises(RuntimeError, match="newer than this build"):
        dbmod.migrate(c, [s for s in dbmod._MIGRATION_STEPS if s[0] <= 57])
    c.close()


# ---------------------------------------------------------- display names

def test_normalise_nfc_stores_the_composed_form():
    decomposed = "Matej Šimalčík"
    out = dbmod.normalise_display_name(decomposed)
    assert out == unicodedata.normalize("NFC", decomposed)
    assert "Š" in out and "̌" not in out


def test_normalise_collapses_whitespace_and_strips():
    assert dbmod.normalise_display_name("  T.\t\n  Chen  ") == "T. Chen"
    assert dbmod.normalise_display_name("A　B") == "A B"


def test_normalise_64_is_fine_65_is_refused():
    assert len(dbmod.normalise_display_name("x" * 64)) == 64
    with pytest.raises(dbmod.DisplayNameError) as exc:
        dbmod.normalise_display_name("x" * 65)
    assert str(exc.value) == "A name can be at most 64 characters."


@pytest.mark.parametrize("bad", [
    "T. Chen‮",        # RLO, a bidi override
    "T‍Chen",          # ZWJ
    "T​Chen",          # zero-width space
    "T\x07Chen",            # a control character
    "T\x00Chen",
    "T\x1eChen",            # a record separator str.isspace() would accept
    "TChen",          # private use
])
def test_normalise_refuses_invisible_and_control_characters(bad):
    with pytest.raises(dbmod.DisplayNameError) as exc:
        dbmod.normalise_display_name(bad)
    assert str(exc.value) == "A name cannot contain invisible or control characters."


@pytest.mark.parametrize("empty", ["", "   ", "\t\n"])
def test_normalise_refuses_empty(empty):
    with pytest.raises(dbmod.DisplayNameError) as exc:
        dbmod.normalise_display_name(empty)
    assert str(exc.value).startswith("A name cannot be empty.")


@pytest.mark.parametrize("good", ["陳小明", "Zoë Ångström", "Łukasz", "O'Brien-Smith", "김민수"])
def test_normalise_accepts_cjk_and_accented_names(good):
    assert dbmod.normalise_display_name(good) == good


def test_every_sentence_is_free_of_em_dashes():
    for text in (dbmod.DISPLAY_NAME_EMPTY, dbmod.DISPLAY_NAME_TOO_LONG,
                 dbmod.DISPLAY_NAME_BAD_CHARS, dbmod.DISPLAY_NAME_TAKEN):
        assert "—" not in text and "–" not in text


def test_display_name_taken_by_another_sign_in_name_in_any_case(conn):
    others = {"tchen", "owen"}
    assert dbmod.display_name_taken(conn, "tchen", "OWEN", others)
    assert dbmod.display_name_taken(conn, "tchen", "owen", others)
    assert not dbmod.display_name_taken(conn, "tchen", "Owen Lee", others)


def test_your_own_sign_in_name_is_allowed(conn):
    assert not dbmod.display_name_taken(conn, "tchen", "TChen", {"tchen", "owen"})


def test_display_name_taken_by_another_display_name(conn):
    dbmod.set_display_name(conn, "owen", "The Boss", by="owen", now=NOW)
    assert dbmod.display_name_taken(conn, "tchen", "the boss", set())
    # Your own existing display name is not a clash with yourself.
    assert not dbmod.display_name_taken(conn, "owen", "THE BOSS", set())


def test_display_name_taken_compares_through_nfc(conn):
    dbmod.set_display_name(conn, "owen", "Šef", by="owen", now=NOW)
    assert dbmod.display_name_taken(conn, "tchen", "Šef", set())


def test_set_get_and_clear(conn):
    assert dbmod.get_display_name(conn, "tchen") is None
    stored = dbmod.set_display_name(conn, "TChen", "  T.  Chen ", by="tchen", now=NOW)
    assert stored == "T. Chen"
    assert dbmod.get_display_name(conn, "tchen") == "T. Chen"
    assert dbmod.display_names(conn) == {"tchen": "T. Chen"}
    row = conn.execute("SELECT * FROM user_profiles").fetchone()
    assert (row["username"], row["updated_by"], row["updated_at"]) == ("tchen", "tchen", NOW)
    dbmod.set_display_name(conn, "tchen", "Tina", by="owen", now=LATER)
    assert dbmod.get_display_name(conn, "tchen") == "Tina"
    assert conn.execute("SELECT updated_by FROM user_profiles").fetchone()[0] == "owen"
    assert dbmod.clear_display_name(conn, "tchen") is True
    assert dbmod.clear_display_name(conn, "tchen") is False
    assert dbmod.get_display_name(conn, "tchen") is None


def test_set_refuses_a_known_editor_name_with_the_taken_subclass(conn):
    _machine(conn, "owen", "OWEN-PC")      # owen has reported: a known editor
    with pytest.raises(dbmod.DisplayNameTaken) as exc:
        dbmod.set_display_name(conn, "tchen", "Owen", by="tchen", now=NOW)
    assert str(exc.value) == "Someone else already goes by that name. Pick another."
    assert isinstance(exc.value, dbmod.DisplayNameError)
    assert dbmod.get_display_name(conn, "tchen") is None


def test_set_refuses_a_local_account_and_a_caller_supplied_admin(conn):
    conn.execute("INSERT INTO users (username, password_hash, role, created_at) "
                 "VALUES ('localguy', 'x', 'editor', ?)", (NOW,))
    with pytest.raises(dbmod.DisplayNameTaken):
        dbmod.set_display_name(conn, "tchen", "LocalGuy", by="tchen", now=NOW)
    # settings.admin_users is not in the database: the caller passes it.
    with pytest.raises(dbmod.DisplayNameTaken):
        dbmod.set_display_name(conn, "tchen", "breakglass", by="tchen", now=NOW,
                               other_usernames={"breakglass"})
    assert dbmod.set_display_name(conn, "tchen", "breakglass", by="tchen", now=NOW) \
        == "breakglass"


def test_set_holds_the_write_lock_across_the_check_and_the_upsert(tmp_path):
    # Review round (account page 2026-09-25): the taken check and the upsert
    # were two statements in autocommit, so two parallel claims of one name
    # could both pass. The second writer now waits for the first; after the
    # first commits it sees the name and is refused.
    path = tmp_path / "race.db"
    first = dbmod.connect(path)
    dbmod.migrate(first)
    second = dbmod.connect(path, busy_ms=100)
    try:
        dbmod.set_display_name(first, "tchen", "The Editor", by="tchen", now=NOW)
        assert first.in_transaction
        with pytest.raises(sqlite3.OperationalError):
            dbmod.set_display_name(second, "owen", "The Editor", by="owen", now=NOW)
        assert not second.in_transaction
        first.commit()
        with pytest.raises(dbmod.DisplayNameTaken):
            dbmod.set_display_name(second, "owen", "the editor", by="owen", now=NOW)
        # A refusal releases the lock it took: another writer is not blocked.
        assert not second.in_transaction
        first.execute("BEGIN IMMEDIATE")
        first.rollback()
        assert dbmod.get_display_name(second, "owen") is None
    finally:
        first.close()
        second.close()


def test_set_inside_the_callers_transaction_leaves_it_to_the_caller(conn):
    conn.execute("INSERT INTO user_profiles VALUES ('owen','Boss',?,'owen')", (NOW,))
    assert conn.in_transaction
    with pytest.raises(dbmod.DisplayNameTaken):
        dbmod.set_display_name(conn, "tchen", "boss", by="tchen", now=NOW)
    # Not ours to end: the caller's uncommitted row is still there.
    assert conn.in_transaction
    assert dbmod.get_display_name(conn, "owen") == "Boss"
    conn.rollback()


def test_set_propagates_the_normalise_refusals(conn):
    with pytest.raises(dbmod.DisplayNameError):
        dbmod.set_display_name(conn, "tchen", "x‮", by="tchen", now=NOW)
    assert dbmod.display_names(conn) == {}


# ------------------------------------------------ machine setting requests

def test_whitelist_is_exactly_the_two_keys():
    assert dbmod.MACHINE_SETTING_KEYS == ("jobs_enabled", "jobs_kinds")
    assert "mode" not in dbmod.MACHINE_SETTING_KEYS
    assert dbmod.MACHINE_SETTING_REQUEST_MAX_AGE_DAYS == \
        dbmod.MACHINE_UPDATE_REQUEST_MAX_AGE_DAYS == 14


def test_request_for_an_unknown_machine_is_none(conn):
    assert dbmod.request_machine_settings(
        conn, "tchen", "NOPE", {"jobs_enabled": False},
        requested_by="tchen", now=NOW) is None
    assert conn.execute("SELECT COUNT(*) FROM machine_setting_requests").fetchone()[0] == 0
    assert _audits(conn, dbmod.AUDIT_MACHINE_SETTINGS_REQUEST) == []


def test_request_stores_audits_and_reads_back(conn):
    _machine(conn)
    row = dbmod.request_machine_settings(
        conn, "tchen", "TCHEN-RIG", {"jobs_enabled": False, "mode": "base"},
        requested_by="owen", now=NOW)
    assert row["state"] == "pending"
    assert row["settings"] == {"jobs_enabled": False}       # mode never stored
    assert len(row["request_id"]) == 16
    assert row["delivered_at"] is None and row["detail"] == ""
    assert row["requested_by"] == "owen" and row["requested_at"] == NOW
    assert "settings_json" not in row
    audits = _audits(conn, "machine.settings_request")
    assert len(audits) == 1
    assert audits[0]["actor"] == "owen" and audits[0]["subject"] == "TCHEN-RIG"
    assert audits[0]["detail"]["editor"] == "tchen"
    assert dbmod.machine_settings_request(conn, "tchen", "TCHEN-RIG") == row


def test_request_with_nothing_whitelisted_raises(conn):
    _machine(conn)
    with pytest.raises(ValueError):
        dbmod.request_machine_settings(conn, "tchen", "TCHEN-RIG", {"mode": "base"},
                                       requested_by="tchen", now=NOW)


def test_merge_keeps_per_key_newest_new_id_and_clears_delivered(conn):
    _machine(conn)
    first = dbmod.request_machine_settings(
        conn, "tchen", "TCHEN-RIG", {"jobs_enabled": False, "jobs_kinds": ["peaks"]},
        requested_by="tchen", now=NOW)
    dbmod.mark_machine_settings_delivered(conn, "tchen", "TCHEN-RIG", first["request_id"], NOW)
    assert dbmod.machine_settings_request(conn, "tchen", "TCHEN-RIG")["delivered_at"] == NOW
    second = dbmod.request_machine_settings(
        conn, "tchen", "TCHEN-RIG", {"jobs_enabled": True},
        requested_by="owen", now=LATER)
    assert second["request_id"] != first["request_id"]
    assert second["settings"] == {"jobs_enabled": True, "jobs_kinds": ["peaks"]}
    assert second["delivered_at"] is None
    assert second["requested_by"] == "owen" and second["requested_at"] == LATER
    assert _audits(conn, "machine.settings_request")[0]["detail"]["merged_into"] \
        == first["request_id"]


def test_an_answered_row_is_replaced_not_merged(conn):
    _machine(conn)
    first = dbmod.request_machine_settings(
        conn, "tchen", "TCHEN-RIG", {"jobs_kinds": ["peaks"]},
        requested_by="tchen", now=NOW)
    assert dbmod.answer_machine_settings_request(
        conn, "tchen", "TCHEN-RIG", first["request_id"], "applied", "", NOW)
    again = dbmod.request_machine_settings(
        conn, "tchen", "TCHEN-RIG", {"jobs_enabled": False},
        requested_by="tchen", now=LATER)
    assert again["settings"] == {"jobs_enabled": False}
    assert again["state"] == "pending" and again["answered_at"] is None


def test_every_kind_is_stored_as_the_empty_list(conn):
    _machine(conn)
    row = dbmod.request_machine_settings(
        conn, "tchen", "TCHEN-RIG",
        {"jobs_kinds": list(dbmod.JOB_KINDS) + [dbmod.JOB_KINDS[0]]},
        requested_by="tchen", now=NOW)
    assert row["settings"] == {"jobs_kinds": []}


def test_kinds_duplicates_dropped_in_order(conn):
    _machine(conn)
    row = dbmod.request_machine_settings(
        conn, "tchen", "TCHEN-RIG", {"jobs_kinds": ["peaks", "whisper", "peaks"]},
        requested_by="tchen", now=NOW)
    assert row["settings"]["jobs_kinds"] == ["peaks", "whisper"]


def test_delivered_is_set_once_and_only_for_the_standing_id(conn):
    _machine(conn)
    row = dbmod.request_machine_settings(conn, "tchen", "TCHEN-RIG", {"jobs_enabled": False},
                                         requested_by="tchen", now=NOW)
    dbmod.mark_machine_settings_delivered(conn, "tchen", "TCHEN-RIG", "stale-id", NOW)
    assert dbmod.machine_settings_request(conn, "tchen", "TCHEN-RIG")["delivered_at"] is None
    dbmod.mark_machine_settings_delivered(conn, "tchen", "TCHEN-RIG", row["request_id"], NOW)
    dbmod.mark_machine_settings_delivered(conn, "tchen", "TCHEN-RIG", row["request_id"], LATER)
    assert dbmod.machine_settings_request(conn, "tchen", "TCHEN-RIG")["delivered_at"] == NOW


def test_answer_with_a_stale_id_is_ignored(conn):
    _machine(conn)
    first = dbmod.request_machine_settings(conn, "tchen", "TCHEN-RIG", {"jobs_enabled": False},
                                           requested_by="tchen", now=NOW)
    second = dbmod.request_machine_settings(conn, "tchen", "TCHEN-RIG", {"jobs_enabled": True},
                                            requested_by="tchen", now=LATER)
    assert dbmod.answer_machine_settings_request(
        conn, "tchen", "TCHEN-RIG", first["request_id"], "applied", "", LATER) is False
    row = dbmod.machine_settings_request(conn, "tchen", "TCHEN-RIG")
    assert row["state"] == "pending" and row["request_id"] == second["request_id"]
    assert _audits(conn, "machine.settings_applied") == []


@pytest.mark.parametrize("state,action", [("applied", "machine.settings_applied"),
                                          ("refused", "machine.settings_refused")])
def test_applied_and_refused_are_final_and_audited_by_the_editor(conn, state, action):
    _machine(conn)
    row = dbmod.request_machine_settings(conn, "tchen", "TCHEN-RIG", {"jobs_enabled": False},
                                         requested_by="owen", now=NOW)
    assert dbmod.answer_machine_settings_request(
        conn, "tchen", "TCHEN-RIG", row["request_id"], state, "x" * 400, LATER) is True
    after = dbmod.machine_settings_request(conn, "tchen", "TCHEN-RIG")
    assert after["state"] == state and after["answered_at"] == LATER
    assert len(after["detail"]) == 255
    audits = _audits(conn, action)
    assert len(audits) == 1 and audits[0]["actor"] == "tchen"
    assert audits[0]["detail"]["requested_by"] == "owen"
    # The companion repeats its ledger's last answer on every report: a second
    # identical answer is not a second event.
    assert dbmod.answer_machine_settings_request(
        conn, "tchen", "TCHEN-RIG", row["request_id"], state, "", LATER) is False
    assert len(_audits(conn, action)) == 1


@pytest.mark.parametrize("word", ["failed", "something-new", ""])
def test_failed_and_unknown_words_stay_pending_with_detail(conn, word):
    _machine(conn)
    row = dbmod.request_machine_settings(conn, "tchen", "TCHEN-RIG", {"jobs_enabled": False},
                                         requested_by="tchen", now=NOW)
    assert dbmod.answer_machine_settings_request(
        conn, "tchen", "TCHEN-RIG", row["request_id"], word,
        "could not save config.toml", LATER) is False
    after = dbmod.machine_settings_request(conn, "tchen", "TCHEN-RIG")
    assert after["state"] == "pending" and after["answered_at"] is None
    assert after["detail"] == "could not save config.toml"
    assert _audits(conn, "machine.settings_applied") == []
    assert _audits(conn, "machine.settings_refused") == []


def test_answer_with_no_request_or_empty_id(conn):
    _machine(conn)
    assert dbmod.answer_machine_settings_request(
        conn, "tchen", "TCHEN-RIG", "abc", "applied", "", NOW) is False
    assert dbmod.answer_machine_settings_request(
        conn, "tchen", "TCHEN-RIG", "", "applied", "", NOW) is False


def test_withdraw_only_a_pending_ask(conn):
    _machine(conn)
    assert dbmod.withdraw_machine_settings_request(
        conn, "tchen", "TCHEN-RIG", by="tchen", now=NOW) is False
    row = dbmod.request_machine_settings(conn, "tchen", "TCHEN-RIG", {"jobs_enabled": False},
                                         requested_by="tchen", now=NOW)
    assert dbmod.withdraw_machine_settings_request(
        conn, "tchen", "TCHEN-RIG", by="owen", now=LATER) is True
    after = dbmod.machine_settings_request(conn, "tchen", "TCHEN-RIG")
    assert after["state"] == "withdrawn" and after["answered_at"] == LATER
    audits = _audits(conn, "machine.settings_withdraw")
    assert len(audits) == 1 and audits[0]["actor"] == "owen"
    assert audits[0]["detail"]["request_id"] == row["request_id"]
    assert dbmod.withdraw_machine_settings_request(
        conn, "tchen", "TCHEN-RIG", by="owen", now=LATER) is False
    # A withdrawn ask is not answerable any more.
    assert dbmod.answer_machine_settings_request(
        conn, "tchen", "TCHEN-RIG", row["request_id"], "applied", "", LATER) is False


def test_expiry_runs_from_prune_after_14_days(conn):
    _machine(conn)
    _machine(conn, "tchen", "LAPTOP")
    dbmod.request_machine_settings(conn, "tchen", "TCHEN-RIG", {"jobs_enabled": False},
                                   requested_by="tchen", now=_iso(0))
    dbmod.request_machine_settings(conn, "tchen", "LAPTOP", {"jobs_enabled": False},
                                   requested_by="tchen", now=_iso(10))
    conn.commit()
    dbmod.prune(conn, _iso(14.5))
    conn.commit()
    assert dbmod.machine_settings_request(conn, "tchen", "TCHEN-RIG")["state"] == "expired"
    assert dbmod.machine_settings_request(conn, "tchen", "LAPTOP")["state"] == "pending"
    audits = _audits(conn, dbmod.AUDIT_MACHINE_SETTINGS_EXPIRED)
    assert len(audits) == 1 and audits[0]["actor"] == "system"
    assert audits[0]["subject"] == "TCHEN-RIG"
    assert dbmod.expire_machine_settings_requests(conn, _iso(14.5)) == 0


def test_expiry_leaves_answered_rows_alone(conn):
    _machine(conn)
    row = dbmod.request_machine_settings(conn, "tchen", "TCHEN-RIG", {"jobs_enabled": False},
                                         requested_by="tchen", now=_iso(0))
    dbmod.answer_machine_settings_request(conn, "tchen", "TCHEN-RIG", row["request_id"],
                                          "refused", "no", _iso(1))
    assert dbmod.expire_machine_settings_requests(conn, _iso(30)) == 0
    assert dbmod.machine_settings_request(conn, "tchen", "TCHEN-RIG")["state"] == "refused"


def test_unparseable_settings_json_reads_as_empty(conn):
    _machine(conn)
    dbmod.request_machine_settings(conn, "tchen", "TCHEN-RIG", {"jobs_enabled": False},
                                   requested_by="tchen", now=NOW)
    conn.execute("UPDATE machine_setting_requests SET settings_json='{nope'")
    assert dbmod.machine_settings_request(conn, "tchen", "TCHEN-RIG")["settings"] == {}


# ------------------------------------------------ forget / rename

def test_forget_machine_deletes_its_request(conn):
    _machine(conn)
    _machine(conn, "tchen", "LAPTOP")
    for m in ("TCHEN-RIG", "LAPTOP"):
        dbmod.request_machine_settings(conn, "tchen", m, {"jobs_enabled": False},
                                       requested_by="tchen", now=NOW)
    out = dbmod.forget_machine(conn, "tchen", "TCHEN-RIG")
    assert out["deleted"]["machine_setting_requests"] == 1
    assert dbmod.machine_settings_request(conn, "tchen", "TCHEN-RIG") is None
    assert dbmod.machine_settings_request(conn, "tchen", "LAPTOP") is not None


def test_forget_editor_deletes_requests_and_the_profile(conn):
    _machine(conn)
    _machine(conn, "owen", "OWEN-PC")
    dbmod.request_machine_settings(conn, "tchen", "TCHEN-RIG", {"jobs_enabled": False},
                                   requested_by="tchen", now=NOW)
    dbmod.request_machine_settings(conn, "owen", "OWEN-PC", {"jobs_enabled": False},
                                   requested_by="owen", now=NOW)
    dbmod.set_display_name(conn, "tchen", "T. Chen", by="tchen", now=NOW)
    dbmod.set_display_name(conn, "owen", "Boss", by="owen", now=NOW)
    out = dbmod.forget_editor(conn, "tchen")
    assert out["deleted"]["user_profiles"] == 1
    assert out["deleted"]["machine_setting_requests"] >= 1
    assert dbmod.get_display_name(conn, "tchen") is None
    assert dbmod.machine_settings_request(conn, "tchen", "TCHEN-RIG") is None
    # Another person is untouched.
    assert dbmod.get_display_name(conn, "owen") == "Boss"
    assert dbmod.machine_settings_request(conn, "owen", "OWEN-PC") is not None


def test_a_rename_carries_a_pending_request(conn):
    _machine(conn, "tchen", "OLD-PC")
    row = dbmod.request_machine_settings(conn, "tchen", "OLD-PC", {"jobs_enabled": False},
                                         requested_by="tchen", now=NOW)
    assert dbmod.adopt_renamed_machine(conn, "tchen", "OLD-PC", "NEW-PC") is True
    moved = dbmod.machine_settings_request(conn, "tchen", "NEW-PC")
    assert moved is not None and moved["request_id"] == row["request_id"]
    assert moved["state"] == "pending"
    assert dbmod.machine_settings_request(conn, "tchen", "OLD-PC") is None


def test_a_rename_does_not_carry_an_answered_request(conn):
    _machine(conn, "tchen", "OLD-PC")
    row = dbmod.request_machine_settings(conn, "tchen", "OLD-PC", {"jobs_enabled": False},
                                         requested_by="tchen", now=NOW)
    dbmod.answer_machine_settings_request(conn, "tchen", "OLD-PC", row["request_id"],
                                          "applied", "", NOW)
    assert dbmod.adopt_renamed_machine(conn, "tchen", "OLD-PC", "NEW-PC") is True
    assert dbmod.machine_settings_request(conn, "tchen", "NEW-PC") is None


@pytest.mark.parametrize("final", ["applied", "refused", "withdrawn", "expired"])
def test_a_rename_carries_a_pending_ask_over_an_answered_one_at_the_new_name(conn, final):
    # Review round (account page 2026-09-25): the SYS-18a deferred adoption,
    # where NEW-PC has been reporting for a while and already holds a
    # FINISHED ask. OR IGNORE used to skip the move, stranding OLD-PC's
    # pending ask on a name the registry no longer holds.
    _machine(conn, "tchen", "OLD-PC")
    _machine(conn, "tchen", "NEW-PC")
    old = dbmod.request_machine_settings(conn, "tchen", "NEW-PC", {"jobs_enabled": True},
                                         requested_by="tchen", now=NOW)
    conn.execute("UPDATE machine_setting_requests SET state=?, answered_at=? "
                 "WHERE editor_username='tchen' AND machine='NEW-PC'", (final, NOW))
    live = dbmod.request_machine_settings(conn, "tchen", "OLD-PC", {"jobs_enabled": False},
                                          requested_by="tchen", now=LATER)
    assert dbmod.adopt_renamed_machine(conn, "tchen", "OLD-PC", "NEW-PC",
                                       same_computer=True) is True
    moved = dbmod.machine_settings_request(conn, "tchen", "NEW-PC")
    assert moved is not None
    assert moved["request_id"] == live["request_id"] != old["request_id"]
    assert moved["state"] == "pending"
    assert conn.execute("SELECT COUNT(*) FROM machine_setting_requests "
                        "WHERE machine='OLD-PC'").fetchone()[0] == 0


def test_a_rename_keeps_the_new_names_own_pending_ask(conn):
    _machine(conn, "tchen", "OLD-PC")
    _machine(conn, "tchen", "NEW-PC")
    dbmod.request_machine_settings(conn, "tchen", "OLD-PC", {"jobs_enabled": False},
                                   requested_by="tchen", now=NOW)
    newer = dbmod.request_machine_settings(conn, "tchen", "NEW-PC", {"jobs_enabled": True},
                                           requested_by="tchen", now=LATER)
    assert dbmod.adopt_renamed_machine(conn, "tchen", "OLD-PC", "NEW-PC",
                                       same_computer=True) is True
    kept = dbmod.machine_settings_request(conn, "tchen", "NEW-PC")
    assert kept["request_id"] == newer["request_id"] and kept["state"] == "pending"


def test_a_rename_with_nothing_pending_leaves_the_new_names_history(conn):
    _machine(conn, "tchen", "OLD-PC")
    _machine(conn, "tchen", "NEW-PC")
    row = dbmod.request_machine_settings(conn, "tchen", "NEW-PC", {"jobs_enabled": True},
                                         requested_by="tchen", now=NOW)
    dbmod.answer_machine_settings_request(conn, "tchen", "NEW-PC", row["request_id"],
                                          "applied", "", NOW)
    assert dbmod.adopt_renamed_machine(conn, "tchen", "OLD-PC", "NEW-PC",
                                       same_computer=True) is True
    assert dbmod.machine_settings_request(conn, "tchen", "NEW-PC")["state"] == "applied"


# ------------------------------------------------ reported settings

SECTION = {
    "accepts": ["jobs_enabled", "jobs_kinds", "mode", "something_future"],
    "jobs_volunteer_minutes": 30,
    "drive_reminder_minutes": 30.0,
    "youtube": {"downloads": True, "signin_enabled": True, "terms_accepted": True,
                "signin": "ok", "cookies": "SECRET-COOKIE", "reason": "yt-dlp says"},
    "pending_restart": {"jobs_enabled": False, "mode": "base", "jobs_kinds": ["peaks"],
                        "jobs_volunteer_minutes": "30", "drive_reminder_minutes": 5},
    "applied": {"id": "abc", "state": "applied", "detail": "", "at": NOW},
}


def test_no_section_leaves_the_columns_alone(conn):
    _machine(conn)
    dbmod.store_machine_settings(conn, "tchen", "TCHEN-RIG", None, NOW)
    row = conn.execute("SELECT * FROM machine_state").fetchone()
    assert all(row[c] is None for c in CFG)
    assert dbmod.machine_settings_map(conn) == {}
    dbmod.store_machine_settings(conn, "tchen", "TCHEN-RIG", SECTION, NOW)
    dbmod.store_machine_settings(conn, "tchen", "TCHEN-RIG", None, LATER)
    assert dbmod.machine_settings_map(conn)[("tchen", "TCHEN-RIG")]["at"] == NOW


def test_a_section_is_cleaned_and_stored(conn):
    _machine(conn)
    dbmod.store_machine_settings(conn, "tchen", "TCHEN-RIG", SECTION, NOW)
    got = dbmod.machine_settings_map(conn)[("tchen", "TCHEN-RIG")]
    assert got == {
        "accepts": ["jobs_enabled", "jobs_kinds"],
        "jobs_volunteer_minutes": 30,
        "drive_reminder_minutes": 30.0,
        "youtube": {"downloads": True, "signin_enabled": True,
                    "terms_accepted": True, "signin": "ok"},
        "pending_restart": {"jobs_enabled": False, "jobs_kinds": ["peaks"],
                            "drive_reminder_minutes": 5.0},
        "at": NOW,
    }
    raw = conn.execute("SELECT cfg_youtube, cfg_accepts FROM machine_state").fetchone()
    assert "SECRET-COOKIE" not in raw["cfg_youtube"] and "reason" not in raw["cfg_youtube"]
    assert "mode" not in raw["cfg_accepts"]


def test_a_section_replaces_all_six_wholesale(conn):
    _machine(conn)
    dbmod.store_machine_settings(conn, "tchen", "TCHEN-RIG", SECTION, NOW)
    dbmod.store_machine_settings(conn, "tchen", "TCHEN-RIG", {"accepts": []}, LATER)
    got = dbmod.machine_settings_map(conn)[("tchen", "TCHEN-RIG")]
    assert got == {"accepts": [], "jobs_volunteer_minutes": None,
                   "drive_reminder_minutes": None, "youtube": None,
                   # absent = "cannot tell" (NULL), never "nothing waiting"
                   "pending_restart": None, "at": LATER}


def test_out_of_range_and_wrong_type_numbers(conn):
    _machine(conn)
    dbmod.store_machine_settings(conn, "tchen", "TCHEN-RIG", {
        "jobs_volunteer_minutes": 10 ** 9, "drive_reminder_minutes": -3}, NOW)
    got = dbmod.machine_settings_map(conn)[("tchen", "TCHEN-RIG")]
    assert got["jobs_volunteer_minutes"] == 100000
    assert got["drive_reminder_minutes"] == 0.0
    assert got["accepts"] == []            # NULL reads as "cannot take a request"
    dbmod.store_machine_settings(conn, "tchen", "TCHEN-RIG", {
        "jobs_volunteer_minutes": True, "drive_reminder_minutes": "30",
        "accepts": "jobs_enabled", "youtube": "ok", "pending_restart": ["x"]}, LATER)
    got = dbmod.machine_settings_map(conn)[("tchen", "TCHEN-RIG")]
    assert got["jobs_volunteer_minutes"] is None
    assert got["drive_reminder_minutes"] is None
    assert got["accepts"] == [] and got["youtube"] is None and got["pending_restart"] is None
    assert conn.execute("SELECT cfg_accepts FROM machine_state").fetchone()[0] is None


def test_unparseable_stored_json_reads_as_empty(conn):
    _machine(conn)
    dbmod.store_machine_settings(conn, "tchen", "TCHEN-RIG", SECTION, NOW)
    conn.execute("UPDATE machine_state SET cfg_accepts='[nope', cfg_youtube='{',"
                 " cfg_pending_restart='null'")
    got = dbmod.machine_settings_map(conn)[("tchen", "TCHEN-RIG")]
    assert got["accepts"] == [] and got["youtube"] is None and got["pending_restart"] == {}


def test_a_machine_with_no_state_row_is_not_written(conn):
    _machine(conn, state=False)
    dbmod.store_machine_settings(conn, "tchen", "TCHEN-RIG", SECTION, NOW)
    assert dbmod.machine_settings_map(conn) == {}


def test_forget_machine_takes_the_reported_settings_with_it(conn):
    _machine(conn)
    dbmod.store_machine_settings(conn, "tchen", "TCHEN-RIG", SECTION, NOW)
    dbmod.forget_machine(conn, "tchen", "TCHEN-RIG")
    assert dbmod.machine_settings_map(conn) == {}


def test_audit_constants_are_the_pinned_names():
    assert dbmod.AUDIT_ACCOUNT_DISPLAY_NAME == "account.display_name"
    assert dbmod.AUDIT_USER_DISPLAY_NAME == "user.display_name"
    assert dbmod.AUDIT_ACCOUNT_PASSWORD == "account.password_change"
    assert dbmod.AUDIT_ACCOUNT_SIGNOUT_ONE == "account.signout_one"
    assert dbmod.AUDIT_ACCOUNT_SIGNOUT_OTHERS == "account.signout_others"
    assert dbmod.AUDIT_MACHINE_SETTINGS_REQUEST == "machine.settings_request"
    assert dbmod.AUDIT_MACHINE_SETTINGS_WITHDRAW == "machine.settings_withdraw"
    assert dbmod.AUDIT_MACHINE_SETTINGS_APPLIED == "machine.settings_applied"
    assert dbmod.AUDIT_MACHINE_SETTINGS_REFUSED == "machine.settings_refused"
    assert dbmod.DISPLAY_NAME_MAX_CHARS == 64


def test_no_secret_shaped_value_is_audited(conn):
    _machine(conn)
    dbmod.request_machine_settings(conn, "tchen", "TCHEN-RIG", {"jobs_enabled": False},
                                   requested_by="tchen", now=NOW)
    for row in dbmod.fetch_audit(conn, limit=100):
        assert "password" not in json.dumps(row["detail"]).lower()


def test_an_empty_pending_restart_is_nothing_waiting_not_cannot_tell(conn):
    # Fable review 2026-09-25: an ABSENT pending_restart (the companion could
    # not read its config.toml) was stored as {} and read as "nothing is
    # waiting for a restart". Absent is NULL now; only an explicit {} is {}.
    _machine(conn)
    dbmod.store_machine_settings(conn, "tchen", "TCHEN-RIG", {"accepts": [], "pending_restart": {}}, NOW)
    assert dbmod.machine_settings_map(conn)[("tchen", "TCHEN-RIG")]["pending_restart"] == {}
    dbmod.store_machine_settings(conn, "tchen", "TCHEN-RIG", {"accepts": []}, LATER)
    assert dbmod.machine_settings_map(conn)[("tchen", "TCHEN-RIG")]["pending_restart"] is None
    assert conn.execute("SELECT cfg_pending_restart FROM machine_state").fetchone()[0] is None
