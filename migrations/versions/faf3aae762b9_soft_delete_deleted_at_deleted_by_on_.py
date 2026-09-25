"""soft delete (deleted_at, deleted_by) on reqs, partners, products, events

Revision ID: faf3aae762b9
Revises: 48862aeb2649
Create Date: 2026-09-25 13:53:09.013179

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'faf3aae762b9'
down_revision: Union[str, Sequence[str], None] = '48862aeb2649'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Yalnızca nullable sütun eklenir (varsayılan/kısıt yok): SQLite ve Postgres'te düz ALTER TABLE ADD COLUMN yeter.
    op.add_column('events', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('events', sa.Column('deleted_by', sa.Integer(), nullable=True))
    op.add_column('partners', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('partners', sa.Column('deleted_by', sa.Integer(), nullable=True))
    op.add_column('products', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('products', sa.Column('deleted_by', sa.Integer(), nullable=True))
    op.add_column('reqs', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('reqs', sa.Column('deleted_by', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema. batch_alter_table: eski SQLite sürümleri DROP COLUMN'u doğrudan desteklemez (Postgres'te düz ALTER TABLE olur)."""
    for table in ('reqs', 'products', 'partners', 'events'):
        with op.batch_alter_table(table, schema=None) as batch_op:
            batch_op.drop_column('deleted_by')
            batch_op.drop_column('deleted_at')