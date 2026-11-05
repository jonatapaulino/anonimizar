"""Middleware E2E — interceptação de I/O na fronteira do contêiner.

Contrato de trânsito: em `E2E_OBRIGATORIO=1`, todo request em /v1/
chega como quadro AEAD (`application/x-e2e`) e toda resposta sai
como quadro AEAD. A decifragem acontece ANTES do roteador: a regra
de negócio, os validadores e os handlers só veem plaintext em
memória. A cifragem acontece no envio da resposta — o que trafega
na rede é sempre ciphertext, inclusive em erros 4xx/5xx.

`x-e2e-ct` carrega o content-type real do payload claro (o JSON
que o roteador espera). Requisição não-E2E em rota protegida =>
415 opaco; selo inválido => 400 opaco. Nenhum motivo fino vaza.

/healthz fica fora do escopo /v1/ (probe de liveness sem payload).
Em modo não-obrigatório (dev sem chave) o middleware é bypass —
quem decidir a blindagem decide pela presença da chave, não por
código condicional espalhado.
"""
from __future__ import annotations

import json
import logging

from app.cofre import ChavesE2E, abrir_todas
from app.crypto_e2e import (CT_E2E, ErroCripto, FluxoSelador,
                            ReplayCache, janela_de_env)

log = logging.getLogger("tramitacao.e2e")

_PREFIXO_PROTEGIDO = "/v1/"

# anti-replay de ingresso: nonces do quadro 0 dentro da janela
# (processo-local — multi-réplica exigiria cache compartilhado)
_REPLAY = ReplayCache()


class MiddlewareE2E:
    """ASGI puro (não BaseHTTPMiddleware): preserva streaming —
    a resposta cifra quadro a quadro sem materializar o corpo."""

    def __init__(self, app, chave=None,
                 obrigatorio: bool = False):
        # bytes ou ChavesE2E (rotação: abre com todas, sela com a
        # atual); None = bypass dev
        self.app = app
        self.chaves = (chave if chave is None or isinstance(
            chave, ChavesE2E) else ChavesE2E(chave))
        self.obrigatorio = obrigatorio and self.chaves is not None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.chaves is None:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        protegida = path.startswith(_PREFIXO_PROTEGIDO)
        if not protegida:
            await self.app(scope, receive, send)
            return

        # ---- ingresso: junta e decifra o corpo antes do roteador
        partes = []
        while True:
            m = await receive()
            partes.append(m.get("body", b""))
            if not m.get("more_body"):
                break
        corpo = b"".join(partes)
        headers = {k: v for k, v in scope.get("headers", [])}
        ct = headers.get(b"content-type", b"").split(b";")[0].strip()
        vio_e2e = ct == CT_E2E.encode()

        if vio_e2e:
            try:
                corpo = abrir_todas(
                    self.chaves, corpo,
                    janela_ms=janela_de_env(), replay=_REPLAY)
            except ErroCripto:
                log.warning("e2e: selo inválido em %s", path)
                await _responder(send, 400)
                return
            ct_real = headers.get(b"x-e2e-ct")
            if ct_real:
                headers[b"content-type"] = ct_real
            headers.pop(b"content-length", None)
            scope["headers"] = list(headers.items())
        elif self.obrigatorio:
            log.warning("e2e: request em claro recusado em %s", path)
            await _responder(send, 415)
            return

        entregue = False

        async def receive_claro():
            nonlocal entregue
            if entregue:
                return {"type": "http.request", "body": b""}
            entregue = True
            return {"type": "http.request", "body": corpo,
                    "more_body": False}

        # ---- egresso: cifra quadro a quadro quando o par fala E2E
        cifrar = vio_e2e or self.obrigatorio
        selador = (FluxoSelador(self.chaves.atual)
                   if cifrar else None)

        async def send_cifrado(message):
            if not cifrar:
                await send(message)
                return
            if message["type"] == "http.response.start":
                hs = [(k, v) for k, v in message["headers"]
                      if k not in (b"content-length", b"content-type")]
                hs.append((b"content-type", CT_E2E.encode()))
                await send({"type": "http.response.start",
                            "status": message["status"],
                            "headers": hs})
                return
            if message["type"] == "http.response.body":
                bloco = message.get("body", b"")
                mais = message.get("more_body", False)
                out = selador.selar_bloco(bloco) if bloco else b""
                if not mais:
                    out += selador.terminador()
                await send({"type": "http.response.body",
                            "body": out, "more_body": mais})
                return
            await send(message)

        try:
            await self.app(scope, receive_claro, send_cifrado)
        except Exception:
            # falha interna não vaza — e vaza ainda menos em claro
            log.exception("e2e: exceção no handler de %s", path)
            await _responder(send_cifrado, 500)


async def _responder(send, status: int):
    corpo = json.dumps(
        {"erro": {"codigo": "payload_protegido",
                  "mensagem": "canal exige envelope E2E válido"}}
    ).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type",
                             b"application/json"),
                            (b"content-length",
                             str(len(corpo)).encode())]})
    await send({"type": "http.response.body", "body": corpo})
