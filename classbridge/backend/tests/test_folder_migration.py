"""Exercise the folder migration with SQLite FK enforcement and existing children."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_sqlite_folder_upgrade_preserves_parent_and_children(tmp_path):
    path = Path(__file__).parents[1] / "migrations/versions/0005_session_folders.py"
    spec = importlib.util.spec_from_file_location("folder_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite:///" + str(tmp_path / "migration.db"))
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.exec_driver_sql("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)")
        conn.exec_driver_sql("CREATE TABLE sessions (id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) REFERENCES users(id))")
        conn.exec_driver_sql("CREATE TABLE evidence (id INTEGER PRIMARY KEY, session_id VARCHAR(36) REFERENCES sessions(id) ON DELETE CASCADE, text TEXT)")
        conn.exec_driver_sql("INSERT INTO users VALUES ('alice')")
        conn.exec_driver_sql("INSERT INTO sessions VALUES ('lesson', 'alice')")
        conn.exec_driver_sql("INSERT INTO evidence VALUES (1, 'lesson', 'saved evidence')")
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            migration.upgrade()
            assert conn.exec_driver_sql("SELECT folder_id FROM sessions").scalar() is None
            assert conn.exec_driver_sql("SELECT text FROM evidence").scalar() == "saved evidence"
            conn.exec_driver_sql("INSERT INTO session_folders VALUES ('f', 'alice', 'Course', 'course', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)")
            conn.exec_driver_sql("UPDATE sessions SET folder_id='f'")
            with pytest.raises(RuntimeError, match="拒绝"):
                migration.downgrade()
            conn.exec_driver_sql("DELETE FROM session_folders WHERE id='f'")
            assert conn.exec_driver_sql("SELECT folder_id FROM sessions").scalar() is None
            assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            migration.downgrade()
            assert conn.exec_driver_sql("SELECT text FROM evidence").scalar() == "saved evidence"
    engine.dispose()