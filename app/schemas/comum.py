"""Tipos, enums e validadores compartilhados dos contratos.

Padrões e limites já validados nos spikes ou fixados na
especificação:
  - regex CNJ: mesmo padrão medido em P8 (F1=1,00 no caso limpo)
  - limites: 20 MiB de documento, 8 KiB de metadados
    (especificação: erro 413 em bytes OU tokens)
  - metadados não carregam identificadores pessoais — invariante
    de higiene de payload (não-persistência de PII fora do doc)
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Annotated

from pydantic import Field

CNJ_RE = r"^\d{7}-\d{2}\.\d{4}\.8\.\d{2}\.\d{4}$"
ORGAO_RE = r"^[a-z0-9][a-z0-9.-]{1,62}$"
SHA256_RE = r"^[0-9a-f]{64}$"
_CPF_LIKE = re.compile(r"\d{3}\.\d{3}\.\d{3}-\d{2}")
_RG_LIKE = re.compile(r"\b\d{1,2}\.\d{3}\.\d{3}-[\dXx]\b")

# Número do processo no padrão CNJ: NNNNNNN-DD.AAAA.J.TR.OOOO
CasoCNJ = Annotated[str, Field(pattern=CNJ_RE)]
# Slug institucional do órgão: "tjpa", "mpf.pa", "tre-pa"
OrgaoID = Annotated[str, Field(pattern=ORGAO_RE)]
HashSHA256 = Annotated[str, Field(pattern=SHA256_RE)]
# Chave de idempotência do cliente (estágio 1 do pipeline)
IdempotencyKey = Annotated[str, Field(min_length=8, max_length=128)]

MAX_DOC_BYTES = 20 * 1024 * 1024       # 413 acima disso na API real
MAX_METADADOS_BYTES = 8 * 1024


class ModoTramitacao(str, Enum):
    # irreversível — a destruição cerimonial da chave HMAC do caso
    # é o evento que materializa a irreversibilidade (ADR-0012)
    ANONIMIZACAO = "anonimizacao"
    # reversível — mapeamento no cofre sob DEK por caso (ADR-0005)
    PSEUDONIMIZACAO = "pseudonimizacao"


class StatusTramitacao(str, Enum):
    CRIADA = "criada"              # aceita pelo nó de origem
    EM_TRANSITO = "em_transito"    # envelope enviado ao nó destino
    RECEBIDA = "recebida"          # destino validou e ingressou
    CONFIRMADA = "confirmada"      # destino confirmou (ack final)
    RECUSADA = "recusada"          # destino recusou
    CANCELADA = "cancelada"        # origem cancelou antes do recebimento


# Transições legais da máquina de estados — testadas no smoke E2E
TRANSICOES = {
    StatusTramitacao.CRIADA: {StatusTramitacao.EM_TRANSITO,
                            StatusTramitacao.CANCELADA},
    StatusTramitacao.EM_TRANSITO: {StatusTramitacao.RECEBIDA,
                                   StatusTramitacao.CRIADA,     # reenvio
                                   # origem aplica o ack do destino:
                                   StatusTramitacao.CONFIRMADA,
                                   StatusTramitacao.RECUSADA},
    StatusTramitacao.RECEBIDA: {StatusTramitacao.CONFIRMADA,
                                StatusTramitacao.RECUSADA},
    # estados terminais não transitam
    StatusTramitacao.CONFIRMADA: set(),
    StatusTramitacao.RECUSADA: set(),
    StatusTramitacao.CANCELADA: set(),
}


class DecisaoConfirmacao(str, Enum):
    ACEITA = "aceita"
    RECUSADA = "recusada"


def contem_pii_estruturada(valor) -> str | None:
    """Detecta identificador estruturado em strings de metadados.
    Retorna o tipo encontrado ou None — usado para RECUSAR metadados
    que carregariam PII fora do documento (higiene de payload).
    """
    if isinstance(valor, dict):
        return next((t for v in valor.values()
                     if (t := contem_pii_estruturada(v))), None)
    if isinstance(valor, (list, tuple)):
        return next((t for v in valor
                     if (t := contem_pii_estruturada(v))), None)
    if isinstance(valor, str):
        if _CPF_LIKE.search(valor):
            return "cpf"
        if _RG_LIKE.search(valor):
            return "rg"
    return None
