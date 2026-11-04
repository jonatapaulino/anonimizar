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
import logging

from fastapi import Request

log = logging.getLogger("tramitacao.auth")

HDR_IDENTIDADE = "x-cliente-orgao"
MSG_OPACA = "credenciais ausentes ou inválidas"


class ErroAuth(RuntimeError):
    """Falha de autenticação — mapeada para 401 opaco."""

    def __init__(self, motivo_interno: str):
        super().__init__(MSG_OPACA)
        self.motivo = motivo_interno      # só para log interno


def orgao_atual(req: Request) -> str:
    orgao = (req.headers.get(HDR_IDENTIDADE) or "").strip()
    if not orgao:
        log.warning("sem identidade mTLS em %s", req.url.path)
        raise ErroAuth("header de identidade ausente")
    return orgao
