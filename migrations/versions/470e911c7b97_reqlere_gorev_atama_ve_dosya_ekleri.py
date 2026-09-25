"""reqlere gorev atama ve dosya ekleri

Revision ID: 470e911c7b97
Revises: db88b61a5d41
Create Date: 2026-09-24 11:25:49.988088

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '470e911c7b97'
down_revision: Union[str, Sequence[str], None] = 'db88b61a5d41'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    NOT: autogenerate'in ürettiği düz op.create_foreign_key(...) SQLite'ta NotImplementedError ile patlıyordu
    ("No support for ALTER of constraints in SQLite dialect") -- SQLite ALTER TABLE ile constraint ekleyemez,
    Alembic'in batch mode'u (tabloyu kopyala-yeniden oluştur) gerekiyor. batch_alter_table Postgres'te de
    çalışır (orada sıradan ALTER TABLE'a düşer), yani tek migration hem yerel SQLite hem Supabase için doğru.
    Kısıtlara da kalıcı isim verildi (isimsiz kısıt sonradan downgrade'de güvenilir şekilde bulunamaz)."""
    with op.batch_alter_table('attachments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('req_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_attachments_req_id'), ['req_id'], unique=False)
        batch_op.create_foreign_key('fk_attachments_req_id_reqs', 'reqs', ['req_id'], ['id'], ondelete='CASCADE')

    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.add_column(sa.Column('assignee_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('done_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key('fk_events_assignee_id_users', 'users', ['assignee_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_constraint('fk_events_assignee_id_users', type_='foreignkey')
        batch_op.drop_column('done_at')
        batch_op.drop_column('assignee_id')

    with op.batch_alter_table('attachments', schema=None) as batch_op:
        batch_op.drop_constraint('fk_attachments_req_id_reqs', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_attachments_req_id'))
        batch_op.drop_column('req_id')
