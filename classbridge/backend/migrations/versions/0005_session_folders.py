"""Single-level private session folders; never rebuild the sessions parent table."""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if 'session_folders' not in sa.inspect(bind).get_table_names():
        op.create_table(
            'session_folders',
            sa.Column('id', sa.String(36), primary_key=True),
            sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('name', sa.String(80), nullable=False),
            sa.Column('name_key', sa.String(240), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint('user_id', 'name_key', name='uq_session_folders_owner_name'),
        )
        op.create_index('ix_session_folders_user_id', 'session_folders', ['user_id'])
    columns = {c['name'] for c in sa.inspect(bind).get_columns('sessions')}
    if 'folder_id' not in columns:
        if bind.dialect.name == 'sqlite':
            # Native nullable REFERENCES addition is supported by SQLite. Alembic's
            # separate ADD CONSTRAINT would require a dangerous parent-table rebuild.
            op.execute(sa.text(
                'ALTER TABLE sessions ADD COLUMN folder_id VARCHAR(36) '
                'CONSTRAINT fk_sessions_folder_id REFERENCES session_folders(id) ON DELETE SET NULL'
            ))
        else:
            op.add_column('sessions', sa.Column('folder_id', sa.String(36), nullable=True))
            op.create_foreign_key('fk_sessions_folder_id', 'sessions', 'session_folders',
                                  ['folder_id'], ['id'], ondelete='SET NULL')
        op.create_index('ix_sessions_folder_id', 'sessions', ['folder_id'])


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text('SELECT 1 FROM session_folders LIMIT 1')).first():
        raise RuntimeError('文件夹已使用，拒绝丢失分类信息的降级；请先删除文件夹或恢复升级前备份。')
    op.drop_index('ix_sessions_folder_id', table_name='sessions')
    if bind.dialect.name != 'sqlite':
        op.drop_constraint('fk_sessions_folder_id', 'sessions', type_='foreignkey')
    op.drop_column('sessions', 'folder_id')
    op.drop_table('session_folders')