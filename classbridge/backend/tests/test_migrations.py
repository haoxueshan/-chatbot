"""Exercise the saved Alembic history without touching the user's local DB."""
import os
from pathlib import Path
import subprocess
import sys

from sqlalchemy import create_engine, inspect


def test_migration_upgrade_downgrade_and_reupgrade(tmp_path):
    root = Path(__file__).resolve().parents[1]
    database = tmp_path / 'migration.db'
    env = {**os.environ, 'DATABASE_URL': f'sqlite:///{database.as_posix()}', 'DATA_DIR': str(tmp_path)}
    def migrate(*args):
        subprocess.run([sys.executable, '-m', 'alembic', *args], cwd=root, env=env,
                       check=True, capture_output=True, text=True)
    migrate('upgrade', 'head')
    engine = create_engine(env['DATABASE_URL'])
    try:
        assert {'users', 'sessions', 'segment_revisions', 'outbox', 'citations', 'chunks'} <= set(inspect(engine).get_table_names())
        assert {'label', 'position', 'location'} <= {c['name'] for c in inspect(engine).get_columns('citations')}
    finally:
        engine.dispose()
    migrate('downgrade', 'base')
    engine = create_engine(env['DATABASE_URL'])
    try:
        assert inspect(engine).get_table_names() == ['alembic_version']
    finally:
        engine.dispose()
    migrate('upgrade', 'head')
