"""local_users.py: the dashboard's own identity provider (WP C,
docs/ZERO_TOUCH_PLAN.md §3.3, 2026-08-17). `conn` is the migrated-to-v17
connection from conftest.py.
"""
from __future__ import annotations

import pytest

from ccsync_dashboard import local_users


def test_create_verify_and_hash_shape(conn):
    local_users.create_user(conn, "JSmith", "correct-horse-battery-staple", "editor")
    conn.commit()
    # Stored lowercase, same convention as every other username in this repo.
    row = local_users.get_user(conn, "jsmith")
    assert row["username"] == "jsmith"
    assert row["role"] == "editor"
    assert row["disabled"] is False or row["disabled"] == 0

    # scrypt$n$r$p$salt_b64$hash_b64 -- self-describing so cost parameters can
    # be raised later without a migration.
    parts = row["password_hash"].split("$")
    assert len(parts) == 6
    assert parts[0] == "scrypt"
    assert int(parts[1]) == local_users.SCRYPT_N

    assert local_users.verify_password(conn, "jsmith", "correct-horse-battery-staple") is True
    assert local_users.verify_password(conn, "JSMITH", "correct-horse-battery-staple") is True
    assert local_users.verify_password(conn, "jsmith", "wrong password entirely") is False
    assert local_users.verify_password(conn, "nobody", "whatever-password-here") is False


def test_duplicate_username_refused(conn):
    local_users.create_user(conn, "jsmith", "correct-horse-battery-staple", "editor")
    with pytest.raises(local_users.LocalUserError, match="already exists"):
        local_users.create_user(conn, "jsmith", "another-correct-horse-battery", "editor")


def test_bad_username_refused(conn):
    with pytest.raises(local_users.LocalUserError, match="username"):
        local_users.create_user(conn, "Not A Username", "correct-horse-battery-staple", "editor")
    with pytest.raises(local_users.LocalUserError, match="username"):
        local_users.create_user(conn, "1startswithdigit", "correct-horse-battery-staple", "editor")


def test_bad_role_refused(conn):
    with pytest.raises(local_users.LocalUserError, match="role"):
        local_users.create_user(conn, "jsmith", "correct-horse-battery-staple", "superuser")


def test_weak_password_refused(conn):
    with pytest.raises(local_users.LocalUserError, match="at least"):
        local_users.create_user(conn, "jsmith", "short", "editor")


def test_disabled_account_cannot_verify(conn):
    local_users.create_user(conn, "jsmith", "correct-horse-battery-staple", "editor")
    conn.commit()
    assert local_users.verify_password(conn, "jsmith", "correct-horse-battery-staple") is True
    local_users.disable_user(conn, "jsmith", True)
    conn.commit()
    assert local_users.verify_password(conn, "jsmith", "correct-horse-battery-staple") is False
    local_users.disable_user(conn, "jsmith", False)
    conn.commit()
    assert local_users.verify_password(conn, "jsmith", "correct-horse-battery-staple") is True


def test_disable_unknown_user_refused(conn):
    with pytest.raises(local_users.LocalUserError, match="not a local account"):
        local_users.disable_user(conn, "ghost")


def test_set_password_updates_hash_and_enforces_floor(conn):
    local_users.create_user(conn, "jsmith", "correct-horse-battery-staple", "editor")
    conn.commit()
    local_users.set_password(conn, "jsmith", "new-correct-horse-battery")
    conn.commit()
    assert local_users.verify_password(conn, "jsmith", "correct-horse-battery-staple") is False
    assert local_users.verify_password(conn, "jsmith", "new-correct-horse-battery") is True
    with pytest.raises(local_users.LocalUserError):
        local_users.set_password(conn, "jsmith", "short")
    with pytest.raises(local_users.LocalUserError, match="not a local account"):
        local_users.set_password(conn, "ghost", "correct-horse-battery-staple")


def test_ssh_keys_add_list_remove(conn):
    local_users.create_user(conn, "jsmith", "correct-horse-battery-staple", "editor")
    conn.commit()
    key = "ssh-ed25519 QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE= jsmith@laptop"
    added = local_users.add_ssh_key(conn, "jsmith", key, label="laptop")
    conn.commit()
    assert added["fingerprint"].startswith("SHA256:")
    keys = local_users.keys_for(conn, "jsmith")
    assert len(keys) == 1 and keys[0]["label"] == "laptop"

    # Re-adding the same key is idempotent (same fingerprint), not a second row.
    local_users.add_ssh_key(conn, "jsmith", key, label="laptop (relabelled)")
    conn.commit()
    assert len(local_users.keys_for(conn, "jsmith")) == 1

    assert local_users.remove_ssh_key(conn, "jsmith", added["fingerprint"]) is True
    assert local_users.keys_for(conn, "jsmith") == []
    # Removing an already-gone key is not an error.
    assert local_users.remove_ssh_key(conn, "jsmith", added["fingerprint"]) is False


def test_add_ssh_key_refuses_garbage_and_unknown_user(conn):
    local_users.create_user(conn, "jsmith", "correct-horse-battery-staple", "editor")
    conn.commit()
    with pytest.raises(local_users.LocalUserError):
        local_users.add_ssh_key(conn, "jsmith", "not a key at all")
    with pytest.raises(local_users.LocalUserError, match="not a local account"):
        local_users.add_ssh_key(conn, "ghost", "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIBogus")


def test_any_users_exist_and_list_users(conn):
    assert local_users.any_users_exist(conn) is False
    local_users.create_user(conn, "owen", "correct-horse-battery-staple", "admin")
    conn.commit()
    assert local_users.any_users_exist(conn) is True
    users = local_users.list_users(conn)
    assert len(users) == 1
    assert users[0]["username"] == "owen"
    assert users[0]["role"] == "admin"
    assert users[0]["ssh_keys"] == []
    assert "password_hash" not in users[0]


def test_is_local_admin(conn):
    local_users.create_user(conn, "owen", "correct-horse-battery-staple", "admin")
    local_users.create_user(conn, "jsmith", "correct-horse-battery-staple", "editor")
    conn.commit()
    assert local_users.is_local_admin(conn, "owen") is True
    assert local_users.is_local_admin(conn, "jsmith") is False
    assert local_users.is_local_admin(conn, "ghost") is False
    local_users.disable_user(conn, "owen", True)
    conn.commit()
    assert local_users.is_local_admin(conn, "owen") is False


def test_delete_user_removes_the_row_and_its_keys(conn):
    local_users.create_user(conn, "jsmith", "correct-horse-battery-staple", "editor")
    local_users.add_ssh_key(
        conn, "jsmith",
        "ssh-ed25519 QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE= jsmith@laptop",
        label="laptop")
    result = local_users.delete_user(conn, "JSmith", requested_by="owen")
    conn.commit()
    assert result == {"username": "jsmith", "role": "editor", "ssh_keys_removed": 1}
    assert local_users.get_user(conn, "jsmith") is None
    assert local_users.keys_for(conn, "jsmith") == []
    assert local_users.verify_password(conn, "jsmith", "correct-horse-battery-staple") is False


def test_delete_unknown_user_refused(conn):
    with pytest.raises(local_users.LocalUserError, match="not a local account"):
        local_users.delete_user(conn, "nobody")


def test_delete_refuses_self_and_the_last_enabled_admin(conn):
    local_users.create_user(conn, "owen", "correct-horse-battery-owen", "admin")
    with pytest.raises(local_users.LocalUserError, match="signed in as"):
        local_users.delete_user(conn, "owen", requested_by="Owen")
    with pytest.raises(local_users.LocalUserError, match="last enabled admin"):
        local_users.delete_user(conn, "owen", requested_by="root")

    # A second enabled admin is what makes the first one deletable.
    local_users.create_user(conn, "boss", "correct-horse-battery-boss", "admin")
    assert local_users.count_enabled_admins(conn) == 2
    local_users.delete_user(conn, "owen", requested_by="boss")
    assert local_users.count_enabled_admins(conn) == 1


def test_delete_of_an_editor_ignores_the_admin_count(conn):
    local_users.create_user(conn, "jsmith", "correct-horse-battery-staple", "editor")
    assert local_users.count_enabled_admins(conn) == 0
    local_users.delete_user(conn, "jsmith")
    assert local_users.get_user(conn, "jsmith") is None


def test_warn_missing_admin_users_logs_for_unknown_names(conn, caplog):
    local_users.create_user(conn, "owen", "correct-horse-battery-staple", "admin")
    conn.commit()
    caplog.clear()
    with caplog.at_level("WARNING", logger="ccsync.dashboard.local_users"):
        local_users.warn_missing_admin_users(conn, frozenset({"owen", "ghost"}))
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("ghost" in r.message for r in warnings)
    assert not any("owen" in r.message for r in warnings)
