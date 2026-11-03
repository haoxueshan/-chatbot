"""Migration tests use isolated databases/schemas, never the application DB."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import uuid
from io import StringIO
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session
from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT=Path(__file__).resolve().parents[1]


def load_file(path):
    spec=importlib.util.spec_from_file_location('frozen_migration',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def history_roundtrip(url,tmp_path):
    env={**os.environ,'DATABASE_URL':url,'DATA_DIR':str(tmp_path),'DASHSCOPE_API_KEY':''}
    def migrate(*args):
        result=subprocess.run([sys.executable,'-m','alembic',*args],cwd=ROOT,env=env,capture_output=True,text=True)
        assert result.returncode==0,result.stderr
    migrate('upgrade','0002')
    old=load_file(ROOT/'migrations/schema_v1.py')
    engine=create_engine(url)
    # Explicit FK checks make SQLite destructive table recreation detectable.
    if engine.dialect.name=='sqlite':
        from sqlalchemy import event
        @event.listens_for(engine,'connect')
        def fk(connection,_):connection.execute('PRAGMA foreign_keys=ON')
    try:
        with Session(engine) as db:
            db.add(old.User(id='u',username='u',password_hash='not-a-real-login',settings={'target_language':'ja'}));db.flush()
            db.add(old.Session(id='s',user_id='u',title='历史韩英课堂',mode='real'));db.flush()
            db.add(old.RecognitionStream(id='r',session_id='s',mode='real'));db.flush()
            db.add(old.SegmentRevision(id='v',session_id='s',stream_id='r',sentence_id='sentence',source_revision=7,
                start_ms=5,end_ms=500,text='작업기억 working memory',mode='real'));db.flush()
            db.add(old.Translation(id='t',segment_id='v',source_revision=7,translation_revision=3,text='工作记忆',mode='real'));db.commit()
        for action,revision,has_language in [('upgrade','head',True),('downgrade','0002',False),('upgrade','head',True)]:
            migrate(action,revision)
            with engine.connect() as conn:
                assert conn.execute(text('SELECT text, source_revision FROM segment_revisions')).one()==('작업기억 working memory',7)
                assert conn.execute(text('SELECT text, source_revision, translation_revision FROM translations')).one()==('工作记忆',7,3)
                for table in ('sessions','translations'):
                    assert ('target_language' in {c['name'] for c in inspect(conn).get_columns(table)})==has_language
                    if has_language:assert conn.execute(text(f'SELECT target_language FROM {table}')).scalar_one()=='zh-CN'
        with engine.begin() as conn:conn.execute(text("UPDATE sessions SET target_language='en' WHERE id='s'"))
        result=subprocess.run([sys.executable,'-m','alembic','downgrade','0002'],cwd=ROOT,env=env,capture_output=True,text=True)
        assert result.returncode!=0 and '拒绝丢失语言信息' in result.stderr
        with engine.connect() as conn:
            assert conn.execute(text('SELECT target_language FROM sessions')).scalar_one()=='en'
            assert conn.execute(text('SELECT target_language FROM translations')).scalar_one()=='zh-CN'
            assert conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='0003'
    finally:engine.dispose()


def test_sqlite_historical_text_versions_survive_upgrade_downgrade(tmp_path):
    history_roundtrip(f'sqlite:///{(tmp_path/"history.db").as_posix()}',tmp_path)


def test_postgresql_revision_ddl_compilation(monkeypatch):
    # Compile the actual migration with PostgreSQL dialect; this is NOT a live DB test.
    migration=load_file(ROOT/'migrations/versions/0003_translation_language.py')
    output=StringIO()
    ctx=MigrationContext.configure(dialect_name='postgresql',opts={'as_sql':True,'output_buffer':output})
    monkeypatch.setattr(migration,'op',Operations(ctx))
    monkeypatch.setattr(migration.sa,'inspect',lambda bind:SimpleNamespace(get_columns=lambda table:[]))
    migration.upgrade();migration.downgrade()
    sql=output.getvalue()
    assert "ALTER TABLE sessions ADD COLUMN target_language VARCHAR(16) DEFAULT 'zh-CN' NOT NULL" in sql
    assert "ALTER TABLE translations ADD COLUMN target_language VARCHAR(16) DEFAULT 'zh-CN' NOT NULL" in sql
    assert 'ALTER TABLE sessions DROP COLUMN target_language' in sql
    assert 'DELETE ' not in sql and 'DROP TABLE' not in sql


@pytest.mark.skipif(not os.environ.get('CLASSBRIDGE_TEST_POSTGRES_URL'),reason='No isolated PostgreSQL + pgvector test server configured')
def test_postgresql_historical_roundtrip(tmp_path):
    # Explicit opt-in test database only. Generated schema contains all test data.
    url=make_url(os.environ['CLASSBRIDGE_TEST_POSTGRES_URL'])
    schema='cb_test_'+uuid.uuid4().hex
    engine=create_engine(url)
    with engine.begin() as conn:conn.execute(text(f'CREATE SCHEMA {schema}'))
    try:
        isolated=url.update_query_dict({'options':f'-csearch_path={schema},public'})
        history_roundtrip(isolated.render_as_string(hide_password=False),tmp_path)
    finally:
        with engine.begin() as conn:conn.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        engine.dispose()
