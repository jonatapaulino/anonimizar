"""Assinatura Ed25519 dos artefatos que cruzam nós — envelope e
ack (divida-tecnica §5.5).

Sem assinatura, `origem`, `destino`, `status` e `hash_recebido`
eram DECLARADOS e confiados: a custódia repousava no canal mTLS
e na honestidade dos pares. Com assinatura, o conteúdo fica
criptograficamente atrelado ao emissor — um envelope adulterado
em trânsito (hash, caso, destino) é rejeitado antes de existir
como registro, e o ack só vale com a chave do destino do caso.

Modelo de chaves: cada órgão tem par Ed25519 próprio — a privada
(em `ORG_SIGN_SEED_B64`, 32B b64) assina; o diretório
`ORGAO_PUBKEYS_JSON` {"tjpa": "<b64>", ...} resolve a pública do
par pela identidade declarada. Distribuição das públicas é
out-of-band, junto ao provisionamento dos certs mTLS.

Não-configurado (dev/teste sem env): `assinante=None` — o nó não
assina nem verifica (retrocompatível). Configurado, a verificação
é fail-closed: assinatura ausente, inválida ou órgão fora do
diretório => rejeição.
"""
from __future__ import annotations

import base64
import json
import os

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey)

from app.crypto_e2e import ErroCripto


def payload_assinado(m) -> dict:
    """Campos cobertos pela assinatura — tudo do modelo menos a
    própria `assinatura`. `model_dump(mode="json")` é o formato
    canônico: o que o emissor assina e o que o receptor remonta
    após o parse são byte-a-byte o mesmo payload."""
    d = m.model_dump(mode="json")
    d.pop("assinatura", None)
    return d


def _canon(d: dict) -> bytes:
    """Serialização canônica — chaves ordenadas, separadores
    mínimos: repr ambígua não pode gerar assinaturas distintas
    do mesmo conteúdo."""
    return json.dumps(d, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


class AssinanteEd25519:
    """Par de chaves do nó + diretório org -> pública dos pares.

    `assinar(m)` devolve a assinatura b64 do payload canônico;
    `verificar(org, m)` confere a `assinatura` do modelo com a
    pública registrada para `org` — órgão fora do diretório é
    inválido (fail-closed: desconhecido não assina)."""

    def __init__(self, seed: bytes, pubkeys: dict[str, bytes]):
        if len(seed) != 32:
            raise ErroCripto("seed Ed25519 deve ter 32 bytes")
        self._priv = Ed25519PrivateKey.from_private_bytes(seed)
        self._pubs = dict(pubkeys)

    def assinar(self, m) -> str:
        return base64.b64encode(
            self._priv.sign(_canon(payload_assinado(m)))).decode()

    def verificar(self, org: str, m) -> bool:
        """True só se `org` está no diretório E a assinatura do
        modelo confere para a pública dele."""
        pub = self._pubs.get(org)
        sig = getattr(m, "assinatura", None)
        if pub is None or not sig:
            return False
        try:
            Ed25519PublicKey.from_public_bytes(pub).verify(
                base64.b64decode(sig, validate=True),
                _canon(payload_assinado(m)))
            return True
        except (InvalidSignature, ValueError):
            return False


def assinante_de_env() -> AssinanteEd25519 | None:
    """`ORG_SIGN_SEED_B64` (privada do nó) + `ORGAO_PUBKEYS_JSON`
    (diretório org->pública). Ambas ausentes => None (dev);
    configurar só uma é erro — o par é indivisível."""
    seed = os.environ.get("ORG_SIGN_SEED_B64")
    pubs = os.environ.get("ORGAO_PUBKEYS_JSON")
    if not seed and not pubs:
        return None
    if not seed or not pubs:
        raise ErroCripto(
            "assinatura requer ORG_SIGN_SEED_B64 e "
            "ORGAO_PUBKEYS_JSON juntos")
    return AssinanteEd25519(
        base64.b64decode(seed),
        {o: base64.b64decode(p)
         for o, p in json.loads(pubs).items()})
