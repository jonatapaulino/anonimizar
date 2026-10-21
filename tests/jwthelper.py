"""Utilitário de teste — IdP local offline.

Par RSA transiente gerado na importação (novo a cada sessão de
teste) + emissor de tokens RS256. JWT_PUBLIC_KEY é exportada para
o app validar pelo MESMO caminho de produção (env var) — nada de
mock interno: o teste forja de verdade e a API rejeita de verdade.

Fica em módulo próprio (não no conftest) porque conftest é
carregado duas vezes pelo pytest (como `conftest` e como
`tests.conftest`) — um keypair por instância quebraria a
validação. Este arquivo é o ponto canônico único.
"""
import os
import time

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

_PRIV = rsa.generate_private_key(public_exponent=65537,
                                 key_size=2048)
PRIVADA_PEM = _PRIV.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption()).decode()
PUBLICA_PEM = _PRIV.public_key().public_bytes(
    serialization.Encoding.PEM,
    serialization.PublicFormat.SubjectPublicKeyInfo).decode()

os.environ["JWT_PUBLIC_KEY"] = PUBLICA_PEM


def token_para(orgao: str, ttl: int = 3600, **claims) -> str:
    """Token RS256 assinado pela chave privada local do IdP-teste."""
    agora = int(time.time())
    p = {"orgao_id": orgao, "iat": agora, "exp": agora + ttl,
         **claims}
    return jwt.encode(p, PRIVADA_PEM, algorithm="RS256")


def hdr(orgao: str, **claims) -> dict:
    """Header Authorization pronto para TestClient."""
    return {"Authorization": f"Bearer {token_para(orgao, **claims)}"}


def token_chave_errada(orgao: str, ttl: int = 3600) -> str:
    """Token assinado por OUTRO par RSA — forja com formato válido."""
    outra = rsa.generate_private_key(public_exponent=65537,
                                     key_size=2048)
    pem = outra.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()
    agora = int(time.time())
    return jwt.encode({"orgao_id": orgao, "iat": agora,
                       "exp": agora + ttl}, pem, algorithm="RS256")
