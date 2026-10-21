"""Hardening de persistência — idempotência sob corrida e
atomicidade real (status + trilha comitam juntos ou nada).

Roda sobre sqlite em memória (padrão) e sobre Postgres quando
TEST_DB_URL está definida — os testes são dialect-agnósticos.
"""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.errors import ErroConflitoIdempotencia
from app.main import create_app
from app.repository import RepositorioSQL
from app.service import NoTramitacao
from tests.jwthelper import hdr
from tests.smoke.dbutil import mk_repo




class RepoCego:
    """Simula a corrida real: tid_por_idem sempre 'não viu' a
    linha — o conflito só aparece na UNIQUE do banco, como numa
    leitura perdida entre duas transações concorrentes."""
    def __init__(self, repo):
        self._r = repo

    def __getattr__(self, n):
        return getattr(self._r, n)

    async def tid_por_idem(self, origem, chave):
        return None


class TestIdempotenciaConcorrencia:
    def test_idempotencia_concorrencia(self, payload_criacao):
        """Dois POSTs cuja leitura não viu a linha do outro: o
        primeiro cria (201), o segundo estoura a PK e deve virar
        409 sanitizado — nunca 500 nem eco de SQL."""
        async def fab():
            e, r = await mk_repo("a")
            return e, RepoCego(r)

        with TestClient(create_app("tjpa", repo_factory=fab)) as c:
            r1 = c.post("/v1/tramitacoes", json=payload_criacao,
                        headers=hdr("tjpa"))
            r2 = c.post("/v1/tramitacoes", json=payload_criacao,
                        headers=hdr("tjpa"))
        assert r1.status_code == 201
        assert r2.status_code == 409
        corpo = r2.json()
        assert corpo["erro"]["codigo"] == "conflito_de_fluxo"
        # nada de SQL na resposta
        for frag in ("UNIQUE", "INSERT", "idempotencia_pkey",
                     "psycopg", "asyncpg", "sqlstate"):
            assert frag not in str(corpo)

    async def test_idem_duplicado_nivel_repo(self):
        """A mesma PK (orgao, chave) escrita duas vezes — com
        tramitações existentes — mapeia IntegrityError ->
        ErroConflitoIdempotencia."""
        from datetime import datetime, timezone
        e, repo = await mk_repo()
        agora = datetime.now(timezone.utc)
        tid1, tid2 = uuid.uuid4(), uuid.uuid4()
        rec = lambda tid: dict(                               # noqa: E731
            id=tid, caso_cnj="5614226-41.2021.8.14.2679",
            origem="tjpa", destino="mpf.pa",
            modo="pseudonimizacao", status="criada",
            hash_doc="a" * 64, hash_cadeia="b" * 64,
            metadados={}, criado_em=agora, atualizado_em=agora)
        async with repo.transacao() as tx:
            await tx.salvar(rec(tid1))
            await tx.idem("tjpa", "K-1", tid1)
        async with repo.transacao() as tx:
            await tx.salvar(rec(tid2))
        with pytest.raises(ErroConflitoIdempotencia):
            async with repo.transacao() as tx:
                await tx.idem("tjpa", "K-1", tid2)
        await e.dispose()


class _TxBomba:
    """Delega tudo menos encadear — falha DEPOIS de salvar()."""
    def __init__(self, tx):
        self._tx = tx

    def __getattr__(self, n):
        return getattr(self._tx, n)

    async def encadear(self, t, e):
        raise RuntimeError("falha simulada no meio da tx")


class RepoBomba:
    """transacao() devolve um tx que explode no encadear — o
    INSERT da tramitação já foi feito quando a falha acontece."""
    def __init__(self, repo):
        self._r = repo

    def __getattr__(self, n):
        return getattr(self._r, n)

    def transacao(self):
        inner = self._r.transacao()

        class T:
            async def __aenter__(s):
                s.tx = await inner.__aenter__()
                return _TxBomba(s.tx)

            async def __aexit__(s, *a):
                return await inner.__aexit__(*a)
        return T()


class TestAtomicidade:
    async def test_falha_no_meio_nao_deixa_residuo(
            self, payload_criacao):
        """Status salvo e trilha falhando => rollback total:
        nem tramitação, nem trilha, nem idempotência ficam."""
        e, repo = await mk_repo()
        no = NoTramitacao("tjpa", RepoBomba(repo))
        with pytest.raises(RuntimeError, match="falha simulada"):
            await no.criar(payload_criacao)
        async with e.connect() as c:
            # T9: só tabelas de estado — bytes nunca tocam o banco
            for t in ("tramitacoes", "trilha_auditoria",
                      "outbox_eventos", "idempotencia"):
                n = (await c.execute(
                    text(f"SELECT count(*) FROM {t}"))).scalar()
                assert n == 0, f"resíduo em {t}"
        await e.dispose()

    async def test_comportamento_normal_apos_wrapper(
            self, payload_criacao):
        """Sanidade: repo sem bomba cria tudo numa tx só."""
        e, repo = await mk_repo()
        no = NoTramitacao("tjpa", repo)
        out = await no.criar(payload_criacao)
        async with e.connect() as c:
            n = (await c.execute(
                text("SELECT count(*) FROM trilha_auditoria"))
                ).scalar()
        assert n == 1
        assert (await repo.carregar(out.id))["id"] == out.id
        await e.dispose()
