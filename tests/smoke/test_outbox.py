"""Outbox transacional + relay (ADR-0013, T7/T9).

Provas: rollback não deixa evento (na criação E na tx pós-upload);
o relay só marca PROCESSADO após o ACK do publicador; falha vira
ERRO + tentativas. Roda com PublicadorMemoria — broker real só
via RABBITMQ_URL no lifespan.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from app.events import PublicadorMemoria
from app.main import create_app
from app.models import StatusOutbox
from app.relay import relay_pass
from app.service import NoTramitacao
from app.storage import ArmazenamentoMemoria
from tests.jwthelper import hdr
from tests.smoke.dbutil import FakeUpload, mk_repo
from tests.smoke.test_persistencia import RepoBomba

DOC = b"EXCELENTISSIMO SENHOR DOUTOR JUIZ - processo de teste."


def _dt(v):
    """sqlite devolve DateTime naive; Postgres, aware — normaliza."""
    if isinstance(v, str):
        v = datetime.fromisoformat(v)
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


async def _linhas(repo):
    async with repo._engine.connect() as c:
        linhas = [dict(r._mapping) for r in (await c.execute(
            text("SELECT * FROM outbox_eventos"))).all()]
    for l in linhas:                       # sqlite devolve texto
        if isinstance(l["payload"], str):
            l["payload"] = __import__("json").loads(l["payload"])
    return linhas


class PubQueFalha:
    def __init__(self):
        self.calls = 0

    async def publicar(self, evento):
        self.calls += 1
        raise ConnectionError("broker indisponível (simulado)")


class TestAtomicidade:
    async def test_outbox_atomicidade(self, payload_criacao):
        """Tx de criação quebrada => NENHUMA linha na outbox.
        E na tx pós-upload: falha no DB deixa o arquivo órfão no
        storage (GC depois) mas NUNCA evento na outbox."""
        e, repo = await mk_repo()
        st = ArmazenamentoMemoria("tjpa")
        no = NoTramitacao("tjpa", RepoBomba(repo), st)
        payload_criacao["requer_anonimizacao_lgpd"] = True
        with pytest.raises(RuntimeError, match="falha simulada"):
            await no.criar(payload_criacao)
        assert await _linhas(repo) == []

        # agora a tx do upload: criar OK no repo limpo, bomba liga
        # só na hora de gravar trilha+outbox
        e2, repo2 = await mk_repo()
        st2 = ArmazenamentoMemoria("tjpa")
        no2 = NoTramitacao("tjpa", repo2, st2)
        out = await no2.criar(payload_criacao | dict(
            idempotency_key="atom-0002-ok"))
        no2.repo = RepoBomba(repo2)
        with pytest.raises(RuntimeError, match="falha simulada"):
            await no2.upload_documento(out.id, FakeUpload(DOC), no2.orgao)
        assert await _linhas(repo2) == []          # zero eventos
        assert await st2.existe(str(out.id))       # órfão no storage
        await e.dispose()
        await e2.dispose()


class TestRelay:
    async def _semear(self, org_a, payload_criacao):
        payload_criacao["requer_anonimizacao_lgpd"] = True
        out = await org_a.criar(payload_criacao)
        await org_a.upload_documento(out.id, FakeUpload(DOC), org_a.orgao)
        return out

    async def test_relay_publica_e_marca_processado(
            self, org_a, payload_criacao):
        out = await self._semear(org_a, payload_criacao)
        pub = PublicadorMemoria()
        n = await relay_pass(org_a.repo, pub)
        assert n == 1
        ev = (await _linhas(org_a.repo))[0]
        assert str(ev["status"]).endswith("PROCESSADO")
        # o que chegou ao "broker" é o payload — só ids
        assert pub.eventos[0]["id_documento"] == str(out.id)

    async def test_relay_sem_pendente_nao_faz_nada(self, org_a,
                                                 payload_criacao):
        await org_a.criar(payload_criacao)      # sem upload nem flag
        pub = PublicadorMemoria()
        assert await relay_pass(org_a.repo, pub) == 0
        assert pub.eventos == []

    async def test_relay_falha_incrementa_tentativas(
            self, org_a, payload_criacao):
        """Broker fora: status ERRO, tentativas=1 e retry já
        agendado em proximo_retry_em (backoff) — a linha continua
        elegível quando o instante chega."""
        await self._semear(org_a, payload_criacao)
        t0 = datetime.now(timezone.utc)
        n = await relay_pass(org_a.repo, PubQueFalha(), agora=t0)
        assert n == 0
        ev = (await _linhas(org_a.repo))[0]
        assert str(ev["status"]).endswith("ERRO")
        assert ev["tentativas"] == 1
        assert _dt(ev["proximo_retry_em"]) > t0

    async def test_processado_nao_volta_na_fila(
            self, org_a, payload_criacao):
        await self._semear(org_a, payload_criacao)
        pub = PublicadorMemoria()
        await relay_pass(org_a.repo, pub)
        assert await relay_pass(org_a.repo, pub) == 0  # idempotente
        assert len(pub.eventos) == 1


class TestRetryBackoff:
    """Item 3 da análise: ERRO não estaciona — retry com limite e
    backoff; esgotado vira ESGOTADO + falha_outbox:{tid} na trilha
    (docs/analise-arquitetural.md §4, ponto 12)."""

    async def _semear(self, org_a, payload_criacao):
        payload_criacao["requer_anonimizacao_lgpd"] = True
        out = await org_a.criar(payload_criacao)
        await org_a.upload_documento(out.id, FakeUpload(DOC),
                                     org_a.orgao)
        return out

    async def test_erro_espera_backoff(self, org_a,
                                       payload_criacao):
        """Após falha: ERRO com proximo_retry_em NO FUTURO; uma
        passada no mesmo instante não republica (o evento nunca
        volta a PENDENTE antes do tempo de backoff). Vencido o
        backoff, volta a ser elegível."""
        await self._semear(org_a, payload_criacao)
        t0 = datetime.now(timezone.utc)
        pub = PubQueFalha()
        await relay_pass(org_a.repo, pub, agora=t0,
                         backoff_base_s=60)
        ev = (await _linhas(org_a.repo))[0]
        assert str(ev["status"]).endswith("ERRO")
        assert _dt(ev["proximo_retry_em"]) > t0     # no futuro
        # passada dentro do backoff: nenhuma publicação nova
        await relay_pass(org_a.repo, pub, agora=t0,
                         backoff_base_s=60)
        assert pub.calls == 1
        # vencido o backoff: republica e conta a tentativa
        await relay_pass(org_a.repo, pub,
                         agora=_dt(ev["proximo_retry_em"]))
        assert pub.calls == 2
        ev = (await _linhas(org_a.repo))[0]
        assert ev["tentativas"] == 2

    async def test_esgotado_registra_na_trilha_e_consulta(
            self, org_a, payload_criacao):
        """Esgotadas as tentativas: ESGOTADO é terminal e explícito
        — `falha_outbox:{tid}` entra na hash-chain na mesma tx e a
        consulta (HTTP) reporta anonimizacao_falhou."""
        out = await self._semear(org_a, payload_criacao)
        t0 = datetime.now(timezone.utc)
        pub = PubQueFalha()
        t = t0
        for _ in range(3):
            await relay_pass(org_a.repo, pub, agora=t,
                             backoff_base_s=60, max_tentativas=3)
            ev = (await _linhas(org_a.repo))[0]
            if ev["proximo_retry_em"] is not None:
                t = _dt(ev["proximo_retry_em"]) + \
                    timedelta(seconds=1)
        assert str(ev["status"]).endswith("ESGOTADO")
        assert ev["tentativas"] == 3
        eventos = [r["evento"]
                   for r in await org_a.repo.trilha(out.id)]
        assert f"falha_outbox:{out.id}" in eventos
        # terminal: nenhuma passada futura toca o evento
        assert await relay_pass(org_a.repo, pub,
                                agora=t0 + timedelta(days=1)) == 0
        assert pub.calls == 3
        # ponta a ponta: a consulta HTTP enxerga a falha
        with TestClient(create_app("tjpa",
                                   repo=org_a.repo)) as c:
            r = c.get(f"/v1/tramitacoes/{out.id}",
                      headers=hdr("tjpa"))
        assert r.status_code == 200
        assert r.json()["anonimizacao_falhou"] is True

    async def test_relay_caido_lease_expira(self, org_a,
                                            payload_criacao):
        """Relay morre depois do claim (PUBLICANDO com lease
        vencido): outra réplica reclama e publica — o evento não
        fica preso num estado intermediário."""
        await self._semear(org_a, payload_criacao)
        t0 = datetime.now(timezone.utc)
        ev = (await _linhas(org_a.repo))[0]
        assert await org_a.repo.outbox_reservar(
            uuid.UUID(str(ev["id"])), t0, lease_s=1)  # o "morto"
        pub = PublicadorMemoria()
        # durante o lease de outro relay: ninguém toca
        assert await relay_pass(org_a.repo, pub,
                                agora=t0) == 0
        assert pub.eventos == []
        # lease vencido: é reclamado e publicado
        assert await relay_pass(
            org_a.repo, pub,
            agora=t0 + timedelta(seconds=2)) == 1
        assert len(pub.eventos) == 1

    async def test_evento_sem_id_documento_esgota(
            self, org_a):
        """Payload sem `id_documento` (tipo futuro): o esgotamento
        NÃO pode depender do encadear — a linha chega a ESGOTADO
        mesmo sem linha de trilha correspondente."""
        async with org_a.repo.transacao() as tx:
            await tx.outbox("TipoFuturoSemDocumento",
                            {"campo": "valor"})
        t0 = datetime.now(timezone.utc)
        pub = PubQueFalha()
        t = t0
        for _ in range(2):
            await relay_pass(org_a.repo, pub, agora=t,
                             backoff_base_s=60, max_tentativas=2)
            ev = (await _linhas(org_a.repo))[0]
            if ev["proximo_retry_em"] is not None:
                t = _dt(ev["proximo_retry_em"]) + \
                    timedelta(seconds=1)
        ev = (await _linhas(org_a.repo))[0]
        assert str(ev["status"]).endswith("ESGOTADO")
        assert ev["tentativas"] == 2
        assert pub.calls == 2          # nunca travou em PUBLICANDO

    async def test_id_documento_inexistente_esgota(self, org_a):
        """id_documento que não existe em `tramitacoes` — o
        encadear violaria a FK da trilha; o savepoint isola a
        falha e a linha chega a ESGOTADO mesmo assim."""
        fantasma = uuid.uuid4()
        async with org_a.repo.transacao() as tx:
            await tx.outbox("TipoFuturo",
                            {"id_documento": str(fantasma)})
        t0 = datetime.now(timezone.utc)
        pub = PubQueFalha()
        t = t0
        for _ in range(2):
            await relay_pass(org_a.repo, pub, agora=t,
                             backoff_base_s=60, max_tentativas=2)
            ev = (await _linhas(org_a.repo))[0]
            if ev["proximo_retry_em"] is not None:
                t = _dt(ev["proximo_retry_em"]) + \
                    timedelta(seconds=1)
        ev = (await _linhas(org_a.repo))[0]
        assert str(ev["status"]).endswith("ESGOTADO")
        assert ev["tentativas"] == 2
        # sem trilha (não há tramitação para pendurar o evento) —
        # e, sobretudo, a linha não ficou em PUBLICANDO
        assert await org_a.repo.trilha(fantasma) == []


class TestSchema:
    async def test_tabela_outbox_existe_com_colunas(
            self, org_a):
        """A migração 0003 (PG) / create_all (sqlite) criou a
        tabela com as colunas do contrato."""
        async with org_a.repo._engine.connect() as c:
            cols = {c2["name"] for c2 in (await c.run_sync(
                lambda conn: inspect(conn).get_columns(
                    "outbox_eventos")))}
        assert {"id", "tipo_evento", "payload", "status",
                "tentativas", "proximo_retry_em",
                "criado_em"} <= cols

    async def test_documentos_transito_nao_existe(self, org_a):
        """Migração 0004 (PG) / modelos (sqlite): a tabela de
        bytes sumiu — o banco é só metadados."""
        async with org_a.repo._engine.connect() as c:
            tabelas = set(await c.run_sync(
                lambda conn: inspect(conn).get_table_names()))
        assert "documentos_transito" not in tabelas
