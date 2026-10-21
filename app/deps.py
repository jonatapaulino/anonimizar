"""Identidade do órgão — Bearer JWT validado OFFLINE (RS256).

A API é apenas Resource Server: valida, nunca emite. A chave
pública vem de JWT_PUBLIC_KEY (PEM) — nenhuma chamada de rede na
validação (sem /jwks em tempo real; a prova offline é o P7).
Zero trust: sem chave configurada => rejeita tudo (fail closed).

A identidade sai da claim `orgao_id` (fallback `sub`). O motivo
fino da recusa fica em log interno; ao cliente vai sempre a mesma
mensagem opaca — oráculo de enumeração não se constrói aqui.
"""
import logging
import os

import jwt
from fastapi import Request

log = logging.getLogger("tramitacao.auth")

_ALGS = ["RS256"]
MSG_OPACA = "credenciais ausentes ou inválidas"


class ErroAuth(RuntimeError):
    """Falha de autenticação — mapeada para 401 opaco."""

    def __init__(self, motivo_interno: str):
        super().__init__(MSG_OPACA)
        self.motivo = motivo_interno      # só para log interno


def orgao_atual(req: Request) -> str:
    auth = req.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise ErroAuth("sem bearer token")
    tok = auth[7:].strip()

    pub = os.environ.get("JWT_PUBLIC_KEY")
    if not pub:
        log.error("JWT_PUBLIC_KEY não configurada — fail closed")
        raise ErroAuth("chave pública ausente")

    try:
        p = jwt.decode(tok, pub, algorithms=_ALGS,
                       options={"require": ["exp"]})
    except jwt.ExpiredSignatureError:
        raise ErroAuth("token expirado")
    except jwt.PyJWTError as e:
        raise ErroAuth(f"token inválido ({type(e).__name__})")

    orgao = p.get("orgao_id") or p.get("sub")
    if not orgao or not isinstance(orgao, str):
        raise ErroAuth("sem claim de identidade do órgão")
    return orgao
