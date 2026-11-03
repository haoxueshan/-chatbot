"""Freeze subtitle language per session; existing translations remain Chinese."""
from alembic import op
import sqlalchemy as sa

revision='0003'
down_revision='0002'
branch_labels=None
depends_on=None


def upgrade():
    for table in ('sessions','translations'):
        columns={c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}
        if 'target_language' not in columns:
            op.add_column(table,sa.Column('target_language',sa.String(16),nullable=False,server_default='zh-CN'))


def downgrade():
    # Removing language metadata after non-Chinese use would silently relabel
    # those translations Chinese on re-upgrade. Require backup restore instead.
    if not op.get_context().as_sql:
        for table in ('sessions','translations'):
            if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} WHERE target_language <> 'zh-CN' LIMIT 1")).first():
                raise RuntimeError('存在非中文会话或译文，拒绝丢失语言信息的降级；请恢复升级前的完整备份。')
    # Native DROP COLUMN on supported SQLite and PostgreSQL avoids rebuilding
    # parent tables and cascading deletion of child subtitle/version records.
    for table in ('translations','sessions'):
        op.drop_column(table,'target_language')
