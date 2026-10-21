"""Modelos ORM — schema do nó edge (fonte do alembic).

Decisões de modelagem:
  - `tramitacoes`: só metadados + hashes — NUNCA o documento
    (não-persistência: payload não vira linha permanente). T9:
    `documentos_transito` morreu — binário vive SÓ no object
    storage do órgão (bucket por nó), nunca no banco.
  - `trilha_auditoria`: hash-chain por nó (ADR-0004). hash_anterior
    referencia o topo anterior — GENESIS na primeira linha. Âncora
    externa é preocupação de implantação (assinatura do topo).
  - `idempotencia`: (orgao, chave) -> tid — resposta idempotente.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Enum, ForeignKey,
                        Integer, String, Uuid)
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class StatusOutbox(str, enum.Enum):
    PENDENTE = "PENDENTE"
    PUBLICANDO = "PUBLICANDO"   # reclamado por um relay — lease
    PROCESSADO = "PROCESSADO"   # em proximo_retry_em
    ERRO = "ERRO"               # falhou — retry em proximo_retry_em
    ESGOTADO = "ESGOTADO"       # tentativas esgotadas — terminal


class Base(DeclarativeBase):
    pass


class Tramitacao(Base):
    __tablename__ = "tramitacoes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    caso_cnj: Mapped[str] = mapped_column(String(25), index=True)
    origem: Mapped[str] = mapped_column(String(63))
    destino: Mapped[str] = mapped_column(String(63))
    modo: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(15), index=True)
    hash_documento_sha256: Mapped[str] = mapped_column(String(64))
    hash_cadeia: Mapped[str] = mapped_column(String(64))
    metadados: Mapped[dict] = mapped_column(JSON, default=dict)
    requer_anonimizacao_lgpd: Mapped[bool] = mapped_column(
        Boolean, default=False)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    atualizado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True))


class Trilha(Base):
    __tablename__ = "trilha_auditoria"

    seq: Mapped[int] = mapped_column(primary_key=True,
                                     autoincrement=True)
    tramitacao_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tramitacoes.id"), index=True)
    evento: Mapped[str] = mapped_column(String(128))
    hash_anterior: Mapped[str] = mapped_column(String(64))
    hash_cadeia: Mapped[str] = mapped_column(String(64))
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True))


class Idempotencia(Base):
    __tablename__ = "idempotencia"

    orgao: Mapped[str] = mapped_column(String(63), primary_key=True)
    chave: Mapped[str] = mapped_column(String(128), primary_key=True)
    tramitacao_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tramitacoes.id"))
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True))


class OutboxEvento(Base):
    """Outbox transacional (ADR-0013): o evento é gravado na
    MESMA tx da mudança de estado; o relay publica com retry.
    At-least-once fim a fim sai daqui, não do broker."""
    __tablename__ = "outbox_eventos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True,
                                          default=uuid.uuid4)
    tipo_evento: Mapped[str] = mapped_column(String(64))
    # JSONB em Postgres (consultável), JSON genérico no sqlite
    payload: Mapped[dict] = mapped_column(
        JSON().with_variant(postgresql.JSONB, "postgresql"))
    status: Mapped[StatusOutbox] = mapped_column(
        Enum(StatusOutbox, name="status_outbox",
             native_enum=False),
        default=StatusOutbox.PENDENTE, index=True)
    tentativas: Mapped[int] = mapped_column(Integer, default=0)
    # retry: ERRO => instante da próxima tentativa; PUBLICANDO =>
    # expiração do lease do relay que reclamou (crash => outro
    # relay reclama quando vence)
    proximo_retry_em: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True)
    criado_em: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc))
