"""0004 — drop documentos_transito (T9)

O binário sai do banco de uma vez: o documento vive SÓ no object
storage do órgão (bucket por nó, MinIO/S3 — Tarefa 8). O banco
fica com metadados, status, trilha e outbox.

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("documentos_transito")


def downgrade():
    # recria o buffer de trânsito exatamente como era no 0001
    op.create_table(
        "documentos_transito",
        sa.Column("tramitacao_id", sa.Uuid(), nullable=False),
        sa.Column("conteudo", sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tramitacao_id"], ["tramitacoes.id"],
            ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tramitacao_id"))
