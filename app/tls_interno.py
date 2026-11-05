"""TLS dos links internos — CA privada do nó.

Os clientes internos (aio-pika/amqps, aioboto3/https, asyncpg)
não conhecem a CA interna: `TLS_CA_BUNDLE` aponta para o PEM da
CA dos serviços e este helper devolve o contexto comum. Sem a
env o comportamento é o padrão de cada cliente (dev sem TLS).

A camada E2E (quadros AEAD) é independente desta: TLS protege o
hop serviço-a-serviço; o envelope protege o dado ponta a ponta.
"""
from __future__ import annotations

import os
import ssl


def ca_bundle() -> str | None:
    """Caminho do PEM da CA interna — None = TLS padrão (dev)."""
    return os.environ.get("TLS_CA_BUNDLE") or None


def ctx_cliente() -> ssl.SSLContext | None:
    """Contexto de cliente que confia na CA interna. None quando
    TLS_CA_BUNDLE não está definida (dev legado)."""
    ca = ca_bundle()
    if ca is None:
        return None
    return ssl.create_default_context(cafile=ca)
