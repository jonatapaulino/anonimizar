"""Convenções partilhadas do nó — fonte única.

Acoplamentos que viviam como literais inline em módulos
distintos (divida-tecnica §4.9–4.11): divergir num deles
falhava em silêncio — bucket errado, flag da esteira apagada
na consulta, objeto não encontrado. Centralizados aqui.

  - buckets: sufixos de `storage.bucket_para` — API e worker
    montam o mesmo par `<org>-docs` / `<org>-docs-anonimizados`
  - chave de objeto: formato do id do documento no bucket —
    upload (API) e esteira (worker) endereçam o mesmo objeto
  - eventos da trilha: quem grava (serviço/worker/relay) e quem
    lê por prefixo (`consultar`) usam as MESMAS strings — a
    trilha é append-only, renomear exige emenda de dados.
"""
from __future__ import annotations

# ---------- buckets (sufixo de storage.bucket_para) ----------
BUCKET_BRUTOS = "docs"
BUCKET_ANONIMIZADOS = "docs-anonimizados"


def chave_objeto(tid) -> str:
    """id do documento no bucket do órgão — mesmo formato no
    upload (API) e na esteira (worker)."""
    return str(tid)


# ---------- eventos da trilha ----------
# `consultar` deriva as flags da esteira por startswith destes
# prefixos — mudá-los exige revisar ConsultaTramitacaoOut E os
# registros já persistidos (a trilha é append-only).
PREF_DOC_ANONIMIZADO = "doc_anonimizado:"
PREF_FALHA_ANONIMIZACAO = "falha_anonimizacao:"
PREF_FALHA_OUTBOX = "falha_outbox:"

# tupla pronta para str.startswith(...) — falhas da esteira
PREFS_FALHA_ESTEIRA = (PREF_FALHA_ANONIMIZACAO, PREF_FALHA_OUTBOX)


def ev_criada(tid) -> str:
    return f"criada:{tid}"


def ev_em_transito(tid) -> str:
    return f"em_transito:{tid}"


def ev_reenvio(tid) -> str:
    return f"reenvio:{tid}"


def ev_recebida(tid) -> str:
    return f"recebida:{tid}"


def ev_ack(tid, status) -> str:
    """Decisão do destino aplicada no nó da origem (acks)."""
    return f"conf:{tid}:{status}"


def ev_confirma(tid, status) -> str:
    """Decisão do destino registrada no próprio nó."""
    return f"confirma:{tid}:{status}"


def ev_doc_arquivado(tid) -> str:
    return f"doc_arquivado:{tid}"


def ev_doc_anonimizado(tid) -> str:
    return f"{PREF_DOC_ANONIMIZADO}{tid}"


def ev_falha_anonimizacao(tid, motivo: str | None = None) -> str:
    base = f"{PREF_FALHA_ANONIMIZACAO}{tid}"
    return f"{base}:{motivo}" if motivo else base


def ev_falha_outbox(tid) -> str:
    return f"{PREF_FALHA_OUTBOX}{tid}"
