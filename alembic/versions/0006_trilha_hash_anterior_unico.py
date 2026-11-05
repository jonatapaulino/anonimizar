"""0006 — integridade estrutural da hash-chain

UNIQUE(hash_anterior) em trilha_auditoria: a cadeia é única por
nó (o topo é o da tabela inteira, intercalando casos) e cada elo
só pode ter UM filho. Dois escritores que derivarem do mesmo
topo — bifurcação por corrida — agora falham no banco em vez de
silenciar. A serialização preventiva fica no `encadear`
(pg_advisory_xact_lock na tx); a constraint é o backstop para
qualquer caminho que burlar o repositório.

Nota de dados: numa base já bifurcada o upgrade falha ao criar
a constraint — e DEVE falhar: a divergência existente precisa
ser resolvida manualmente, não mascarada pela migração.

Revision ID: 0006
Revises: 0005
"""
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_trilha_hash_anterior", "trilha_auditoria",
        ["hash_anterior"])


def downgrade() -> None:
    op.drop_constraint(
        "uq_trilha_hash_anterior", "trilha_auditoria",
        type_="unique")
