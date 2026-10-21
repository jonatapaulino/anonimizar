"""Camada de persistência — contrato do repositório + impl SQL.

NoTramitacao consome APENAS esta interface. A unidade de trabalho
é `transacao()`: tudo dentro do bloco comita junto — mudança de
status + linha da trilha são atômicas por construção, não por
convenção (mesma session, mesmo commit).

A hash-chain replica exatamente a matemática provada em memória:
  topo_n = sha256(topo_{n-1} ∥ evento)   com topo_0 = GENESIS cru
o que mantém os hashes iguais entre as implementações.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Protocol

from sqlalchemy import and_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (AsyncSession, async_sessionmaker,
                                    create_async_engine)

from app.errors import ErroConflitoIdempotencia
from app.models import (Base, Idempotencia, OutboxEvento,
                        StatusOutbox, Tramitacao, Trilha)
from app.schemas.comum import ModoTramitacao, StatusTramitacao

GENESIS = b"TRAMITACAO-GENESIS"

log = logging.getLogger("tramitacao.repository")


def _agora():
    return datetime.now(timezone.utc)


class Tx(Protocol):
    async def salvar(self, rec: dict): ...
    async def idem(self, origem: str, chave: str,
                   tid: uuid.UUID): ...
    async def encadear(self, tid: uuid.UUID, evento: str) -> str: ...
    async def outbox(self, tipo_evento: str, payload: dict): ...
    """Grava o evento na outbox na MESMA tx (ADR-0013)."""


class Repositorio(Protocol):
    """Metadados, status, trilha e outbox — NUNCA bytes de
    documento (T9: o binário vive só no object storage)."""
    def transacao(self) -> "_TransacaoSQL": ...
    async def carregar(self, tid: uuid.UUID) -> dict | None: ...
    async def tid_por_idem(self, origem: str,
                           chave: str) -> uuid.UUID | None: ...
    async def por_caso(self, orgao: str,
                       caso_cnj: str) -> dict | None: ...
    """Consulta por id_processo JÁ filtrada por soberania: só
    tramitações em que `orgao` é origem ou destino."""
    async def trilha(self, tid: uuid.UUID) -> list[dict]: ...
    """Hash-chain completa do doc — seq, evento, hashes, em."""
    async def outbox_elegiveis(self, limite: int,
                               agora: datetime): ...
    """Candidatos ao relay: PENDENTE ou (ERRO|PUBLICANDO) com
    proximo_retry_em vencido."""
    async def outbox_reservar(self, eid: uuid.UUID, agora: datetime,
                              lease_s: float) -> bool: ...
    """Claim atômico (UPDATE condicional) — só um relay vira dono."""
    async def outbox_marcar(self, eid: uuid.UUID,
                            status: StatusOutbox): ...
    async def outbox_falhar(self, eid: uuid.UUID, agora: datetime,
                            base_s: float, cap_s: float,
                            max_tentativas: int): ...
    """tentativas++; esgotou => ESGOTADO + falha_outbox:{tid} na
    trilha — mesma tx; senão ERRO + backoff exponencial."""


def _mapear_integridade(e: IntegrityError) -> Exception:
    """PK/UNIQUE(orgao, chave) de idempotência -> erro de domínio;
    todo o resto propaga. asyncpg expõe constraint_name direto;
    psycopg2 via .diag; sqlite só no texto. Casa só violação de
    unicidade (pkey/unique) — FK na mesma tabela NÃO é conflito
    de idempotência. A mensagem de domínio nunca carrega SQL."""
    nome = getattr(e.orig, "constraint_name", None)          # asyncpg
    if nome is None:
        diag = getattr(e.orig, "diag", None)                  # psycopg2
        nome = getattr(diag, "constraint_name", "") if diag else ""
    txt = f"{nome} {e.orig}".lower()
    if "idempotencia" in txt and ("pkey" in txt or "unique" in txt):
        return ErroConflitoIdempotencia(
            "chave de idempotência já utilizada")
    return e


# ---------- conversões dict<->ORM ----------
def _v(x):
    return x.value if hasattr(x, "value") else x


def _para_orm(rec: dict) -> Tramitacao:
    return Tramitacao(
        id=rec["id"], caso_cnj=rec["caso_cnj"], origem=rec["origem"],
        destino=rec["destino"], modo=_v(rec["modo"]),
        status=_v(rec["status"]),
        hash_documento_sha256=rec["hash_doc"],
        hash_cadeia=rec["hash_cadeia"], metadados=rec["metadados"],
        requer_anonimizacao_lgpd=rec.get(
            "requer_anonimizacao_lgpd", False),
        criado_em=rec["criado_em"], atualizado_em=rec["atualizado_em"])


def _para_dict(t: Tramitacao) -> dict:
    return dict(
        id=t.id, caso_cnj=t.caso_cnj, origem=t.origem,
        destino=t.destino, modo=ModoTramitacao(t.modo),
        status=StatusTramitacao(t.status),
        hash_doc=t.hash_documento_sha256,
        hash_cadeia=t.hash_cadeia, metadados=t.metadados,
        requer_anonimizacao_lgpd=t.requer_anonimizacao_lgpd,
        criado_em=t.criado_em, atualizado_em=t.atualizado_em)


class _TxSQL:
    def __init__(self, s: AsyncSession):
        self.s = s

    async def salvar(self, rec: dict):
        await self.s.merge(_para_orm(rec))

    async def idem(self, origem: str, chave: str, tid: uuid.UUID):
        await self.s.flush()   # idem: pai antes do filho
        self.s.add(Idempotencia(orgao=origem, chave=chave,
                                tramitacao_id=tid, criado_em=_agora()))

    async def encadear(self, tid: uuid.UUID, evento: str) -> str:
        ant = await self.s.scalar(
            select(Trilha.hash_cadeia)
            .order_by(Trilha.seq.desc()).limit(1))
        # primeira linha: preimage é o GENESIS cru (mesma matemática
        # da versão em memória); depois, o digest anterior
        ant_b = bytes.fromhex(ant) if ant else GENESIS
        ant_hex = ant if ant else GENESIS.hex()
        topo = hashlib.sha256(ant_b + evento.encode()).hexdigest()
        self.s.add(Trilha(tramitacao_id=tid, evento=evento,
                          hash_anterior=ant_hex, hash_cadeia=topo,
                          criado_em=_agora()))
        return topo

    async def outbox(self, tipo_evento: str, payload: dict):
        """Evento na outbox dentro desta tx — atômico com a
        mudança de estado por construção."""
        self.s.add(OutboxEvento(
            tipo_evento=tipo_evento, payload=payload,
            status=StatusOutbox.PENDENTE, tentativas=0,
            criado_em=_agora()))


class _TransacaoSQL:
    def __init__(self, sm: async_sessionmaker):
        self.sm = sm

    async def __aenter__(self) -> _TxSQL:
        self.s = self.sm()
        await self.s.begin()
        return _TxSQL(self.s)

    async def __aexit__(self, exc, *a):
        try:
            if exc:
                await self.s.rollback()
                if isinstance(exc, IntegrityError):
                    raise _mapear_integridade(exc) from exc
            else:
                try:
                    await self.s.commit()
                except IntegrityError as e:
                    await self.s.rollback()
                    raise _mapear_integridade(e) from e
        finally:
            await self.s.close()


class RepositorioSQL:
    """Implementação SQLAlchemy-async do contrato."""

    def __init__(self, sm: async_sessionmaker):
        self.sm = sm

    def transacao(self) -> _TransacaoSQL:
        return _TransacaoSQL(self.sm)

    async def carregar(self, tid: uuid.UUID) -> dict | None:
        async with self.sm() as s:
            t = await s.get(Tramitacao, tid)
            return _para_dict(t) if t else None

    async def tid_por_idem(self, origem: str,
                           chave: str) -> uuid.UUID | None:
        async with self.sm() as s:
            i = await s.get(Idempotencia, (origem, chave))
            return i.tramitacao_id if i else None

    async def por_caso(self, orgao: str,
                       caso_cnj: str) -> dict | None:
        """Isolamento na consulta (T12): o filtro de órgão vive no
        WHERE — um terceiro nem sequer descobre que o caso existe
        (404, não 403: não vazar existência)."""
        async with self.sm() as s:
            t = await s.scalar(
                select(Tramitacao)
                .where(Tramitacao.caso_cnj == caso_cnj,
                       (Tramitacao.origem == orgao)
                       | (Tramitacao.destino == orgao))
                .order_by(Tramitacao.criado_em.desc()).limit(1))
            return _para_dict(t) if t else None

    async def trilha(self, tid: uuid.UUID) -> list[dict]:
        async with self.sm() as s:
            rs = await s.scalars(
                select(Trilha).where(Trilha.tramitacao_id == tid)
                .order_by(Trilha.seq))
            return [dict(seq=r.seq, evento=r.evento,
                         hash_anterior=r.hash_anterior,
                         hash_cadeia=r.hash_cadeia,
                         criado_em=r.criado_em) for r in rs]

    # ---------- outbox (relay) ----------
    async def outbox_elegiveis(self, limite: int = 50,
                               agora: datetime | None = None
                               ) -> list[OutboxEvento]:
        """PENDENTE ou (ERRO|PUBLICANDO) com retry/lease vencido.
        ERRO volta a ser elegível após proximo_retry_em (backoff);
        PUBLICANDO vencido = relay morreu entre claim e publish —
        self-healing pelo lease."""
        agora = agora or _agora()
        async with self.sm() as s:
            rs = await s.scalars(
                select(OutboxEvento)
                .where(or_(
                    OutboxEvento.status == StatusOutbox.PENDENTE,
                    and_(OutboxEvento.status.in_(
                             (StatusOutbox.ERRO,
                              StatusOutbox.PUBLICANDO)),
                         OutboxEvento.proximo_retry_em <= agora)))
                .order_by(OutboxEvento.criado_em).limit(limite))
            return list(rs)

    async def outbox_reservar(self, eid: uuid.UUID,
                              agora: datetime,
                              lease_s: float = 60.0) -> bool:
        """Claim atômico do evento: UPDATE condicional — só um dos
        N relays vira dono (a linha serializa a corrida). Lease em
        proximo_retry_em: se o dono cair, expira e outro reclama."""
        async with self.sm() as s:
            r = await s.execute(
                update(OutboxEvento)
                .where(OutboxEvento.id == eid,
                       or_(OutboxEvento.status ==
                           StatusOutbox.PENDENTE,
                           and_(OutboxEvento.status.in_(
                                    (StatusOutbox.ERRO,
                                     StatusOutbox.PUBLICANDO)),
                                OutboxEvento.proximo_retry_em
                                <= agora)))
                .values(
                    status=StatusOutbox.PUBLICANDO,
                    proximo_retry_em=agora + timedelta(
                        seconds=lease_s)))
            await s.commit()
            return r.rowcount == 1

    async def outbox_marcar(self, eid: uuid.UUID,
                            status: StatusOutbox):
        """Marca o evento SÓ depois do ACK do broker (chamado pelo
        relay dono do claim)."""
        async with self.sm() as s:
            ev = await s.get(OutboxEvento, eid)
            if ev is None:
                return
            ev.status = status
            ev.proximo_retry_em = None
            await s.commit()

    async def outbox_falhar(self, eid: uuid.UUID, agora: datetime,
                            base_s: float = 5.0,
                            cap_s: float = 900.0,
                            max_tentativas: int = 8):
        """Falha de publish: tentativas++ e agenda a próxima
        tentativa (backoff exponencial com teto). Esgotou =>
        ESGOTADO + `falha_outbox:{tid}` na hash-chain — a mesma tx,
        para o esgotamento ser registrado onde a auditoria vive.
        No-op se o evento não está mais sob o relay (corrida)."""
        async with self.transacao() as tx:
            ev = await tx.s.get(OutboxEvento, eid)
            if ev is None or ev.status not in (
                    StatusOutbox.PUBLICANDO, StatusOutbox.ERRO):
                return
            ev.tentativas += 1
            if ev.tentativas >= max_tentativas:
                ev.status = StatusOutbox.ESGOTADO
                ev.proximo_retry_em = None
                tid = (ev.payload or {}).get("id_documento")
                if tid:
                    # a linha da trilha é observabilidade — não pode
                    # segurar o commit do estado terminal: savepoint +
                    # flush isolam a falha (payload sem tid, FK
                    # inexistente) e ESGOTADO comita mesmo assim
                    try:
                        async with tx.s.begin_nested():
                            await tx.encadear(
                                uuid.UUID(str(tid)),
                                f"falha_outbox:{tid}")
                            await tx.s.flush()
                    except Exception:
                        log.warning(
                            "outbox %s esgotado sem trilha "
                            "(tid=%s ilegível)", eid, tid)
            else:
                ev.status = StatusOutbox.ERRO
                espera = min(base_s * 2 ** (ev.tentativas - 1),
                             cap_s)
                ev.proximo_retry_em = \
                    agora + timedelta(seconds=espera)


def repo_from_url(url: str) -> RepositorioSQL:
    """Fábrica de produção — ex.: postgresql+asyncpg://...  As
    tabelas são criadas pelo alembic, não por create_all."""
    e = create_async_engine(url)
    return RepositorioSQL(
        async_sessionmaker(e, expire_on_commit=False))


def repo_sqlite_memoria() -> tuple:
    """Para testes/dev: sqlite em memória com StaticPool (uma
    conexão compartilhada — senão cada session veria um DB vazio).
    Retorna (engine, repo) para o chamador poder dispor o engine."""
    from sqlalchemy import event
    from sqlalchemy.pool import StaticPool
    e = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool)
    # sqlite desliga FK por padrão — ligar para aproximar do
    # comportamento do Postgres e pegar erro de ordem no TDD
    @event.listens_for(e.sync_engine, "connect")
    def _fk(c, _):
        c.execute("PRAGMA foreign_keys=ON")
    return e, RepositorioSQL(
        async_sessionmaker(e, expire_on_commit=False))


async def criar_tabelas(engine):
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
