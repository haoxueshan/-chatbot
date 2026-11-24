"""Private ASR profiles and durable per-stream configuration (no credentials)."""
import uuid
from datetime import datetime,timezone
from alembic import op
import sqlalchemy as sa

revision='0004'
down_revision='0003'
branch_labels=None
depends_on=None


def upgrade():
    bind=op.get_bind()
    if 'asr_profiles' not in sa.inspect(bind).get_table_names():
        op.create_table('asr_profiles',sa.Column('id',sa.String(36),primary_key=True),
            sa.Column('user_id',sa.String(36),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
            sa.Column('provider',sa.String(32),nullable=False),sa.Column('model_id',sa.String(120),nullable=False),
            sa.Column('display_name',sa.String(100),nullable=False),sa.Column('language_hints',sa.JSON,nullable=True),
            sa.Column('enabled',sa.Boolean,nullable=False),sa.Column('is_default',sa.Boolean,nullable=False),
            sa.Column('credential_ref',sa.String(80),nullable=False),sa.Column('provider_options',sa.JSON,nullable=False),
            sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
        op.create_index('ix_asr_profiles_user_id','asr_profiles',['user_id'])
        op.create_index('uq_asr_default_owner','asr_profiles',['user_id'],unique=True,
            sqlite_where=sa.text('is_default = 1'),postgresql_where=sa.text('is_default = true'))
    for table,columns in {'sessions':[sa.Column('asr_profile_id',sa.String(36),nullable=True),sa.Column('asr_snapshot',sa.JSON,nullable=True)],
                          'recognition_streams':[sa.Column('asr_snapshot',sa.JSON,nullable=True)]}.items():
        existing={c['name'] for c in sa.inspect(bind).get_columns(table)}
        for column in columns:
            if column.name not in existing:op.add_column(table,column)
    from app.config import settings
    meta=sa.MetaData()
    users=sa.Table('users',meta,autoload_with=bind);profiles=sa.Table('asr_profiles',meta,autoload_with=bind)
    sessions=sa.Table('sessions',meta,autoload_with=bind);streams=sa.Table('recognition_streams',meta,autoload_with=bind)
    for user in bind.execute(sa.select(users)).mappings().all():
        if bind.execute(sa.select(profiles.c.id).where(profiles.c.user_id==user['id'])).first():continue
        profile_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'classbridge-asr:'+user['id']))
        stamp=datetime.now(timezone.utc)
        bind.execute(profiles.insert().values(id=profile_id,user_id=user['id'],provider='aliyun',model_id=settings.asr_model,
            display_name='原默认 阿里云 Qwen',language_hints=None,enabled=True,is_default=True,
            credential_ref='DASHSCOPE_API_KEY',provider_options={},created_at=stamp,updated_at=stamp))
        bind.execute(users.update().where(users.c.id==user['id']).values(settings={**(user['settings'] or {}),'asr_profiles_initialized':True}))
        historical={'profile_id':profile_id,'provider':'aliyun','model_id':settings.asr_model,
            'display_name':'原默认 阿里云 Qwen','provenance':'legacy_environment_assumed'}
        bind.execute(sessions.update().where(sessions.c.user_id==user['id'],sessions.c.mode=='real',sessions.c.asr_profile_id.is_(None))
            .values(asr_profile_id=profile_id,asr_snapshot=historical))
        ids=sa.select(sessions.c.id).where(sessions.c.user_id==user['id'])
        bind.execute(streams.update().where(streams.c.session_id.in_(ids),streams.c.mode=='real',streams.c.asr_snapshot.is_(None))
            .values(asr_snapshot=historical))


def downgrade():
    bind=op.get_bind();meta=sa.MetaData()
    from app.config import settings
    profiles=sa.Table('asr_profiles',meta,autoload_with=bind)
    streams=sa.Table('recognition_streams',meta,autoload_with=bind)
    for row in bind.execute(sa.select(profiles)).mappings():
        legacy_id=str(uuid.uuid5(uuid.NAMESPACE_URL,'classbridge-asr:'+row['user_id']))
        if (row['provider']!='aliyun' or row['display_name']!='原默认 阿里云 Qwen' or row['provider_options']
                or row['id']!=legacy_id or row['model_id']!=settings.asr_model or row['language_hints'] is not None
                or not row['enabled'] or not row['is_default']):
            raise RuntimeError('ASR 配置已使用，拒绝丢失模型信息的降级；请恢复升级前备份。')
    for row in bind.execute(sa.select(streams.c.asr_snapshot)):
        if row[0] and row[0].get('provenance')!='legacy_environment_assumed':
            raise RuntimeError('已有录音模型快照，拒绝删除历史模型信息。')
    sessions=sa.Table('sessions',meta,autoload_with=bind)
    for row in bind.execute(sa.select(sessions.c.asr_snapshot)):
        if row[0] and row[0].get('provenance')!='legacy_environment_assumed':
            raise RuntimeError('会话已选择模型，拒绝删除模型配置快照。')
    users=sa.Table('users',meta,autoload_with=bind)
    for user in bind.execute(sa.select(users)).mappings().all():
        bind.execute(users.update().where(users.c.id==user['id']).values(settings={k:v for k,v in (user['settings'] or {}).items() if k!='asr_profiles_initialized'}))
    op.drop_column('recognition_streams','asr_snapshot')
    op.drop_column('sessions','asr_snapshot');op.drop_column('sessions','asr_profile_id')
    op.drop_table('asr_profiles')
