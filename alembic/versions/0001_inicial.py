"""Versão inicial — núcleo transacional do MVP de tramitação.

Espelha app/models.py (fonte de verdade):
- tramitacoes           estado + metadados + hashes (sem conteúdo)
- trilha_auditoria      hash-chain append-only
- documentos_transito   buffer com ciclo de vida do trânsito
- idempotencia          PK composta (orgao, chave)

Revision ID: 0001
Revises: (nenhuma — base)
Create Date: 2026-10-16
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tramitacoes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("caso_cnj", sa.String(25), nullable=False),
        sa.Column("origem", sa.String(63), nullable=False),
        sa.Column("destino", sa.String(63), nullable=False),
        sa.Column("modo", sa.String(20), nullable=False),
        sa.Column("status", sa.String(15), nullable=False),
        sa.Column("hash_documento_sha256", sa.String(64),
                  nullable=False),
        sa.Column("hash_cadeia", sa.String(64), nullable=False),
        sa.Column("metadados", sa.JSON(), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True),
                  nullable=False),
        sa.Column("atualizado_em", sa.DateTime(timezone=True),
                  nullable=False),
    )
    op.create_index("ix_tramitacoes_caso_cnj", "tramitacoes",
                    ["caso_cnj"])
    op.create_index("ix_tramitacoes_status", "tramitacoes",
                    ["status"])

    op.create_table(
        "trilha_auditoria",
        sa.Column("seq", sa.Integer(), primary_key=True,
                  autoincrement=True),
        sa.Column("tramitacao_id", sa.Uuid(),
                  sa.ForeignKey("tramitacoes.id"), nullable=False),
        sa.Column("evento", sa.String(128), nullable=False),
        sa.Column("hash_anterior", sa.String(64), nullable=False),
        sa.Column("hash_cadeia", sa.String(64), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True),
                  nullable=False),
    )
    op.create_index("ix_trilha_auditoria_tramitacao_id",
                    "trilha_auditoria", ["tramitacao_id"])

    op.create_table(
        "documentos_transito",
        sa.Column("tramitacao_id", sa.Uuid(),
                  sa.ForeignKey("tramitacoes.id",
                                ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("conteudo", sa.LargeBinary(), nullable=False),
    )

    op.create_table(
        "idempotencia",
        sa.Column("orgao", sa.String(63), primary_key=True),
        sa.Column("chave", sa.String(128), primary_key=True),
        sa.Column("tramitacao_id", sa.Uuid(),
                  sa.ForeignKey("tramitacoes.id"), nullable=False),
        sa.Column("criado_em", sa.DateTime(timezone=True),
                  nullable=False),
    )


def downgrade() -> None:
    op.drop_table("idempotencia")
    op.drop_table("documentos_transito")
    op.drop_table("trilha_auditoria")
    op.drop_table("tramitacoes")
