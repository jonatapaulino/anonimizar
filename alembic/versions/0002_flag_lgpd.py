"""Flag de anonimização LGPD na tramitação.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tramitacoes",
        sa.Column("requer_anonimizacao_lgpd", sa.Boolean(),
                  nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("tramitacoes", "requer_anonimizacao_lgpd")
