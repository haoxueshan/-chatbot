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


def test_asr_upgrade_keeps_legacy_history_and_backfills_only_once(tmp_path):
    from sqlalchemy import MetaData,Table,select
    from sqlalchemy.orm import Session
    from test_multilingual_migration import load_file
    root=Path(__file__).resolve().parents[1]
    env={**os.environ,'DATABASE_URL':f'sqlite:///{(tmp_path/"asr.db").as_posix()}',
        'DATA_DIR':str(tmp_path),'ASR_MODEL':'legacy-qwen-model','DASHSCOPE_API_KEY':'','SONIOX_API_KEY':''}
    def migrate():
        subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=root,env=env,check=True,capture_output=True)
    subprocess.run([sys.executable,'-m','alembic','upgrade','0002'],cwd=root,env=env,check=True,capture_output=True)
    engine=create_engine(env['DATABASE_URL']);old=load_file(root/'migrations/schema_v1.py')
    try:
        with Session(engine) as db:
            db.add(old.User(id='legacy',username='legacy',password_hash='mock',settings={'asr_language_mode':'ko_en'}));db.flush()
            db.add(old.Session(id='s',user_id='legacy',mode='real',title='보존'));db.flush()
            db.add(old.RecognitionStream(id='r',session_id='s',mode='real'));db.flush()
            db.add(old.SegmentRevision(id='v',session_id='s',stream_id='r',sentence_id='r:1',source_revision=3,start_ms=0,end_ms=500,text='history',mode='real'));db.commit()
        migrate();migrate()
        tables={name:Table(name,MetaData(),autoload_with=engine) for name in ('users','asr_profiles','sessions','recognition_streams','segment_revisions')}
        with engine.connect() as conn:
            profile=conn.execute(select(tables['asr_profiles'])).mappings().one()
            assert profile['provider']=='aliyun' and profile['model_id']=='legacy-qwen-model'
            assert profile['is_default'] and profile['credential_ref']=='DASHSCOPE_API_KEY'
            assert conn.execute(select(tables['users'].c.settings)).scalar_one()=={'asr_language_mode':'ko_en','asr_profiles_initialized':True}
            for name in ('sessions','recognition_streams'):
                snapshot=conn.execute(select(tables[name].c.asr_snapshot)).scalar_one()
                assert snapshot['profile_id']==profile['id'] and snapshot['provenance']=='legacy_environment_assumed'
            assert conn.execute(select(tables['segment_revisions'].c.text,tables['segment_revisions'].c.source_revision)).one()==('history',3)
        with engine.begin() as conn:
            conn.execute(tables['asr_profiles'].update().values(model_id='edited-model'))
        downgrade=subprocess.run([sys.executable,'-m','alembic','downgrade','0003'],cwd=root,env=env,capture_output=True)
        assert downgrade.returncode!=0
        with engine.connect() as conn:
            assert conn.execute(select(tables['asr_profiles'].c.model_id)).scalar_one()=='edited-model'
    finally:engine.dispose()
