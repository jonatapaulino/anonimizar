"""Identidade do órgão — derivada de mTLS na borda (sem JWT).

Reprovado: Bearer JWT vive no cliente e pode ser exfiltrado —
token roubado = identidade roubada, de qualquer máquina. Em seu
lugar, a identidade vem do **certificado de cliente** verificado
pelo nginx na única superfície exposta (`borda`); o certificado
fica no SO/HSM do órgão — um script XSS não o copia para fora.

Contrato com o terminador TLS (deploy/nginx.conf):
  ssl_client_certificate + ssl_verify_client on
  => proxy_set_header X-Cliente-Orgao $ssl_client_s_dn  (CN)

A API confia no header porque o compose garante que SÓ o nginx
alcança a rede `interna` — a API não publica porta e forjaria do
header exigiria já estar dentro do perímetro. Zero trust fica na
borda; dentro do nó o header é a identidade autenticada. Ausente
ou vazio => 401 opaco (mesma mensagem para todo motivo — oráculo
de enumeração fechado).
"""
import hmac
import logging
import os
import re

from fastapi import Request

from app.schemas.comum import ORGAO_RE

log = logging.getLogger("tramitacao.auth")

HDR_IDENTIDADE = "x-cliente-orgao"
HDR_SEGREDO = "x-borda-segredo"
MSG_OPACA = "credenciais ausentes ou inválidas"

_ORGAO = re.compile(ORGAO_RE)


class ErroAuth(RuntimeError):
    """Falha de autenticação — mapeada para 401 opaco."""

    def __init__(self, motivo_interno: str):
        super().__init__(MSG_OPACA)
        self.motivo = motivo_interno      # só para log interno


def orgao_atual(req: Request) -> str:
    """Identidade autenticada do chamador — três portões,
    todos 401 opacos (o motivo fino fica só no log):

      1) `X-Cliente-Orgao` presente — extraído do CN do cert
         mTLS pelo nginx;
      2) formato OrgaoID — o mapa do nginx já restringe o CN,
         mas quem escreve no storage/bucket/where deriva nomes
         do valor: malformado não atravessa (defesa em
         profundidade contra qualquer caminho que injete o
         header sem passar pelo mapa);
      3) `BORDA_SEGREDO` (opcional, fail-closed quando
         configurado): segredo comparado em tempo constante —
         aplicação que entrar na `interna` por outro caminho
         (plugin/proxy interno) não fala em nome de órgão
         algum sem o segredo do par nginx↔API."""
    orgao = (req.headers.get(HDR_IDENTIDADE) or "").strip()
    if not orgao:
        log.warning("sem identidade mTLS em %s", req.url.path)
        raise ErroAuth("header de identidade ausente")
    if not _ORGAO.match(orgao):
        log.warning("identidade mTLS malformada em %s",
                    req.url.path)
        raise ErroAuth("identidade fora do formato OrgaoID")
    segredo = os.environ.get("BORDA_SEGREDO")
    if segredo:
        dado = req.headers.get(HDR_SEGREDO) or ""
        if not hmac.compare_digest(dado.encode(),
                                   segredo.encode()):
            log.warning("segredo de borda inválido em %s",
                        req.url.path)
            raise ErroAuth("segredo de borda ausente/inválido")
    return orgao
