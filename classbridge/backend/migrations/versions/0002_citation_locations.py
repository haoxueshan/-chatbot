"""Persist server-assigned citation labels and exact document positions."""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    columns = {c['name'] for c in sa.inspect(op.get_bind()).get_columns('citations')}
    for column in (sa.Column('label', sa.String(30), nullable=True), sa.Column('position', sa.Integer(), nullable=False, server_default='0'), sa.Column('location', sa.String(250), nullable=True)):
        if column.name not in columns:
            op.add_column('citations', column)


def downgrade():
    with op.batch_alter_table('citations') as batch:
        batch.drop_column('location')
        batch.drop_column('position')
        batch.drop_column('label')
