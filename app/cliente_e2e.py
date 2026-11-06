"""Cliente E2E — o lado emissor do envelope que o repo não tinha.

O par (nó de outro órgão ou serviço interno) monta o request E2E:

  corpo_claro  ->  selar(chave)  ->  Content-Type: application/x-e2e
  tipo real    ->  X-E2E-CT (carrega o content-type do claro)
  resposta     ->  se x-e2e, abrir() e devolve o claro

Identidade: em produção o certificado de cliente do TLS faz o CN
(nginx extrai para X-Cliente-Orgao) — `cert=(crt,key)` + `verify=
ca.crt` cobrem esse caminho. `orgao=` injeta o header direto —
modo dev/teste sem nginx na frente (mesma assinatura de saída).

Regra de falha: resposta não-E2E quando se espera E2E, ou selo
inválido, levanta ErroCripto — o chamador decide (nunca engole
silenciosamente: um par que fala claro quando devia falar cifrado
é sinal de configuração quebrada ou de ataque).
"""
from __future__ import annotations

import json
from typing import Any

from app.cofre import ChavesE2E
from app.crypto_e2e import (CT_E2E, ErroCripto, abrir_stream,
                            eh_e2e, selar)


def _abrir_resposta(chaves: ChavesE2E, dados: bytes) -> bytes:
    """Abre a resposta selada coletando TODOS os quadros —
    `abrir` exige exatamente um (válido para JSON de comando);
    downloads streaming chegam em N quadros e são juntados na
    ordem. Rotação: tenta atual -> anteriores, como `abrir_todas`.
    """
    import io
    ult = None
    for c in chaves.todas():
        try:
            return b"".join(
                abrir_stream(c, io.BytesIO(dados)))
        except ErroCripto as e:
            ult = e
    raise ult or ErroCripto("conjunto de chaves vazio")


class RespostaE2E:
    """Resposta já decifrada — status + corpo claro."""
    def __init__(self, status: int, corpo: bytes):
        self.status_code, self.content = status, corpo

    def json(self) -> Any:
        return json.loads(self.content)


class ClienteE2E:
    """Emissor do envelope — httpx async por baixo."""

    def __init__(self, base_url: str, chave,
                 orgao: str | None = None,
                 cert: tuple[str, str] | None = None,
                 verify: str | bool = True,
                 client=None):
        """`client`: injetável (testes usam ASGITransport ou socket
        real). cert=(path_crt, path_key) ativa mTLS; verify=caminho
        da ca.crt. `chave` aceita bytes ou ChavesE2E (rotação)."""
        self.base = base_url.rstrip("/")
        self.chaves = (chave if isinstance(chave, ChavesE2E)
                       else ChavesE2E(chave))
        self.orgao = orgao
        self._client = client
        self._cert, self._verify = cert, verify

    async def _cli(self):
        if self._client is None:
            import ssl
            import httpx
            verify = self._verify
            if self._cert is not None:
                # httpx cert= não oferta o cert neste cenário —
                # monta o contexto explicitamente (mTLS real)
                ctx = ssl.create_default_context(
                    cafile=verify if isinstance(verify, str)
                    else None)
                ctx.load_cert_chain(*self._cert)
                verify = ctx
            self._client = httpx.AsyncClient(
                verify=verify,
                timeout=httpx.Timeout(60.0, connect=10.0))
        return self._client

    async def request(self, metodo: str, path: str,
                      corpo: bytes | None = None,
                      ct_real: str = "application/json",
                      headers: dict | None = None) -> RespostaE2E:
        """Envelope completo: sela o corpo (se houver), marca os
        content-types, dispara, decifra a resposta se vier E2E."""
        cli = await self._cli()
        h = dict(headers or {})
        # "sem excecao": TODA request e envelope — GET/HEAD sem
        # corpo levam um quadro vazio canonico, senao o lado
        # E2E_OBRIGATORIO do servidor recusa com 415.
        corpo = b"{}" if corpo is None else corpo
        h["Content-Type"] = CT_E2E
        h["X-E2E-CT"] = ct_real
        dados = selar(self.chaves.atual, corpo)
        if self.orgao:
            h.setdefault("X-Cliente-Orgao", self.orgao)
        r = await cli.request(metodo, self.base + path,
                              content=dados, headers=h)
        ct_resp = r.headers.get("content-type", "").split(";")[0]
        if ct_resp == CT_E2E or eh_e2e(r.content[:34]):
            return RespostaE2E(r.status_code,
                               _abrir_resposta(self.chaves,
                                               r.content))
        # resposta em claro quando o canal exige E2E: nao engole.
        # 400/415 sao erros de transporte que o proprio middleware
        # devolve em JSON claro (o par nem falou E2E ainda).
        if r.status_code not in (400, 415):
            raise ErroCripto(
                f"par respondeu em claro (status {r.status_code})")
        return RespostaE2E(r.status_code, r.content)

    async def post(self, path: str, payload: dict,
                   **kw) -> RespostaE2E:
        return await self.request(
            "POST", path, corpo=json.dumps(payload).encode(),
            **kw)

    async def post_multipart(self, path: str, campo: str,
                             nome: str, dados: bytes,
                             ct_dados: str = "application/octet-stream",
                             **kw) -> RespostaE2E:
        """Upload multipart sob envelope: o corpo inteiro
        (boundary+partes) é selado — X-E2E-CT carrega o
        multipart real, o servidor re-monta depois de abrir."""
        import os
        boundary = "e2e" + os.urandom(8).hex()
        part = (f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{campo}";'
                f' filename="{nome}"\r\n'
                f"Content-Type: {ct_dados}\r\n\r\n").encode()
        corpo = part + dados + f"\r\n--{boundary}--\r\n".encode()
        return await self.request(
            "POST", path, corpo=corpo,
            ct_real=f"multipart/form-data; boundary={boundary}",
            **kw)

    async def get(self, path: str, **kw) -> RespostaE2E:
        return await self.request("GET", path, **kw)

    async def fechar(self):
        if self._client is not None:
            await self._client.aclose()
            self._client = None
