"""Erros de domínio — módulo neutro (sem deps de repo/service)
para ambos importarem sem ciclo. Mapeamento HTTP em main.py."""


class ErroFluxo(RuntimeError):
    """Violação de estado/contrato no fluxo — mapeada para 409."""


class ErroNaoEncontrado(ErroFluxo):
    """Tramitação inexistente neste nó — mapeada para 404."""


class ErroConflitoIdempotencia(ErroFluxo):
    """UNIQUE(orgao, chave) de idempotência violada numa corrida
    de escrita (a leitura prévia não viu, a constraint viu).
    Mapeada para 409 — nunca expõe SQL ao cliente."""


class ErroLimiteDocumento(ErroFluxo):
    """Upload excedeu MAX_DOC_BYTES — mapeada para 413. Corta no
    meio do stream: o excesso nunca chega ao spool."""
