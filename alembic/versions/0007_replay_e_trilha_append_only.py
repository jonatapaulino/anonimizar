"""0007 — anti-replay compartilhado + append-only no banco

Duas peças de defesa em profundidade:

  - `replay_nonces`: store compartilhado do anti-replay E2E —
    o claim atômico do nonce do quadro (PK) vale para TODAS as
    réplicas do nó (o ReplayCache processo-local só enxerga o
    processo). `expira_ms` marca o fim da janela de frescura —
    linhas mortas são varridas oportunistamente pelo próximo
    insert (sem sweeper dedicado).

  - trigger `trilha_append_only` (só Postgres): UPDATE/DELETE
    em `trilha_auditoria` levanta exceção — a trilha deixa de
    ser append-only por convenção e passa a sê-lo por mecanismo.
    INSERT segue livre (o encadear é o único caminho legítimo).
    SQLite não tem o recurso — em dev/teste a propriedade segue
    por convenção + testes.

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "replay_nonces",
        sa.Column("nonce", sa.String(24), primary_key=True),
        sa.Column("expira_ms", sa.BigInteger(), nullable=False),
        sa.Column("visto_em",
                  sa.DateTime(timezone=True), nullable=False))
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE OR REPLACE FUNCTION trilha_imutavel()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION
                    'trilha_auditoria é append-only';
            END;
            $$ LANGUAGE plpgsql;
            """)
        op.execute("""
            CREATE TRIGGER trilha_append_only
            BEFORE UPDATE OR DELETE ON trilha_auditoria
            FOR EACH ROW EXECUTE FUNCTION trilha_imutavel();
            """)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trilha_append_only "
                   "ON trilha_auditoria")
        op.execute("DROP FUNCTION IF EXISTS trilha_imutavel()")
    op.drop_table("replay_nonces")
