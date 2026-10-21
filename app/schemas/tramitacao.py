"""Contratos do fluxo de tramitação inter-órgãos.

Fluxo N1-validado (mecanismos):
  Órgão A  POST /v1/tramitacoes          -> TramitacaoOut (status CRIADA)
  A -> B   envelope POST /v1/recebimentos -> RecebimentoOut
  Órgão B  POST /v1/tramitacoes/{id}/confirmacao -> ConfirmacaoOut
  A        GET status -> CONFIRMADA/RECUSADA

Invariantes de contrato (da especificação e ADRs):
  - saída NUNCA carrega o payload do documento — só hash (não-
    persistência: doc não vai para log, trilha nem resposta)
  - metadados são recusados se contiverem identificador pessoal
    estruturado — PII só existe dentro do documento
  - hash_documento_sha256 declarado pela origem é a âncora de
    integridade que o destino recomputa
  - caso_cnj é o escopo da chave HMAC (P5) — a tramitação é sempre
    por caso, nunca por órgão nem por entidade
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from .comum import (
    CasoCNJ, DecisaoConfirmacao, HashSHA256, IdempotencyKey,
    MAX_METADADOS_BYTES, ModoTramitacao, OrgaoID,
    StatusTramitacao, contem_pii_estruturada,
)


def _metadados_ok(v: dict) -> dict:
    if len(json.dumps(v, ensure_ascii=False)) > MAX_METADADOS_BYTES:
        raise ValueError("metadados excedem o limite de tamanho")
    if (tipo := contem_pii_estruturada(v)):
        raise ValueError(
            f"metadados não podem conter identificadores pessoais "
            f"({tipo} detectado) — PII pertence ao documento")
    return v


class TramitacaoCreate(BaseModel):
    """Entrada do Órgão A — cria a tramitação (metadados + hash;
    o binário NÃO transita aqui: sobe depois via /upload)."""
    caso_cnj: CasoCNJ
    destino: OrgaoID
    modo: ModoTramitacao
    hash_documento_sha256: HashSHA256   # declarado; conferido no upload
    metadados: dict[str, Any] = {}
    idempotency_key: IdempotencyKey
    requer_anonimizacao_lgpd: bool = False   # dispara evento p/ IA

    @field_validator("metadados")
    @classmethod
    def _meta(cls, v):
        return _metadados_ok(v)


class TramitacaoOut(BaseModel):
    """Visão pública da tramitação — NÃO contém o documento."""
    model_config = ConfigDict(use_enum_values=True)

    id: uuid.UUID
    caso_cnj: CasoCNJ
    origem: OrgaoID            # origem vem da identidade autenticada
    destino: OrgaoID           # (JWT/mTLS), nunca do payload
    modo: ModoTramitacao
    status: StatusTramitacao
    hash_documento_sha256: HashSHA256
    criado_em: datetime
    atualizado_em: datetime
    hash_cadeia: HashSHA256    # topo da hash-chain da trilha (ADR-0004)


class EnvelopeRecebimento(BaseModel):
    """Pacote em trânsito A→B — METADADOS apenas (T9): o binário
    vive no object storage do nó, nunca no envelope nem no banco.
    `origem` é DECLARADA aqui e deve ser conferida contra a
    identidade mTLS do canal (ADR-0007) na implementação."""
    model_config = ConfigDict(frozen=True)

    tramitacao_id: uuid.UUID
    origem: OrgaoID
    caso_cnj: CasoCNJ
    modo: ModoTramitacao
    hash_documento_sha256: HashSHA256
    enviado_em: datetime
    requer_anonimizacao_lgpd: bool = False   # vem do criador


class RecebimentoOut(BaseModel):
    """Resposta do nó destino ao ingresso do envelope.
    Pós-T9 o envelope é só metadados — a verificação de bytes
    migrou para o upload/download no object storage.

    Eco idempotente (reentrega do mesmo envelope — reconciliação
    do handshake): `status` informa o estado atual da projeção em
    B para a origem; `hash_cadeia` é omitido (prova interna da
    trilha, não insumo do chamador) e `recebido_em` é o instante
    do PRIMEIRO ingresso, não o do eco."""
    model_config = ConfigDict(use_enum_values=True)

    tramitacao_id: uuid.UUID
    recebido: bool
    status: StatusTramitacao | None = None
    recebido_em: datetime
    motivo: str | None = None
    hash_cadeia: HashSHA256 | None = None


class ConfirmacaoCreate(BaseModel):
    """Decisão do Órgão B sobre uma tramitação recebida."""
    tramitacao_id: uuid.UUID
    decisao: DecisaoConfirmacao
    motivo: str | None = None          # obrigatório se RECUSADA
    hash_documento_recebido: HashSHA256  # recomputado pelo destino

    @field_validator("motivo")
    @classmethod
    def _motivo(cls, v):
        if v is not None and len(v) > 500:
            raise ValueError("motivo excede 500 caracteres")
        return v

    @model_validator(mode="after")
    def _recusa_exige_motivo(self):
        if self.decisao is DecisaoConfirmacao.RECUSADA and not self.motivo:
            raise ValueError("recusa exige motivo")
        return self


class EventoTrilhaOut(BaseModel):
    """Uma linha da hash-chain (ADR-0004) — exposta na consulta.
    hash_anterior é `str` (não HashSHA256): a primeira linha
    referencia o preimage GENESIS, não um digest de 64 chars."""
    seq: int
    evento: str
    hash_anterior: str
    hash_cadeia: HashSHA256
    criado_em: datetime


class ConsultaTramitacaoOut(TramitacaoOut):
    """T12 — visão completa para o consultante autorizado
    (origem OU destino do caso): status + metadados + flags da
    esteira de IA derivadas da trilha + a hash-chain íntegra."""
    metadados: dict[str, Any] = {}
    requer_anonimizacao_lgpd: bool = False
    anonimizacao_concluida: bool = False
    anonimizacao_falhou: bool = False
    trilha: list[EventoTrilhaOut] = []


class ConfirmacaoOut(BaseModel):
    """Ack final — origem aplica e encerra a tramitação."""
    model_config = ConfigDict(use_enum_values=True)

    tramitacao_id: uuid.UUID
    status: StatusTramitacao           # CONFIRMADA ou RECUSADA
    confirmado_em: datetime
    hash_cadeia: HashSHA256


class ErroOut(BaseModel):
    """Erro sanitizado — nunca ecoa conteúdo do documento nem PII
    (invariante: respostas de erro não vazam payload)."""
    class Erro(BaseModel):
        codigo: str
        mensagem: str
    erro: Erro
