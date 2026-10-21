"""0005 — retry da outbox: proximo_retry_em + ESGOTADO/PUBLICANDO

Evento falho não estaciona mais: ERRO volta a ser elegível quando
`proximo_retry_em` vence (backoff exponencial com teto, no relay)
e PUBLICANDO é o lease do claim — relay caído não trava a linha.
Esgotadas as tentativas, o relay grava ESGOTADO + `falha_outbox:`
na trilha, na mesma tx.

Nota de schema: `status` é sa.Enum(native_enum=False) — o DDL
emitido é VARCHAR puro, SEM CHECK constraint (verificado via
compile do dialect postgresql), então nenhum constraint precisa
ser alterado para os novos valores.

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("outbox_eventos", sa.Column(
        "proximo_retry_em", sa.DateTime(timezone=True),
        nullable=True))
    op.create_index("ix_outbox_eventos_proximo_retry_em",
                    "outbox_eventos", ["proximo_retry_em"])


def downgrade() -> None:
    op.drop_index("ix_outbox_eventos_proximo_retry_em",
                  "outbox_eventos")
    op.drop_column("outbox_eventos", "proximo_retry_em")
