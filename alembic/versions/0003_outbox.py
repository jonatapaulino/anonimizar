"""Outbox transacional — ADR-0013.

Eventos para a esteira de IA gravados na mesma tx do estado;
o relay RabbitMQ drena com retry até ACK do broker.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbox_eventos",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tipo_evento", sa.String(64), nullable=False),
        sa.Column("payload",
                  sa.JSON().with_variant(postgresql.JSONB,
                                         "postgresql"),
                  nullable=False),
        sa.Column("status",
                  sa.Enum("PENDENTE", "PROCESSADO", "ERRO",
                          name="status_outbox", native_enum=False),
                  nullable=False, server_default="PENDENTE"),
        sa.Column("tentativas", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("criado_em", sa.DateTime(timezone=True),
                  nullable=False),
    )
    op.create_index("ix_outbox_eventos_status", "outbox_eventos",
                    ["status"])


def downgrade() -> None:
    op.drop_table("outbox_eventos")
