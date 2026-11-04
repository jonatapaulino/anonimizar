"""Identidade de borda para testes — substitui tests/jwthelper.

Com mTLS na borda (nginx), a API recebe o órgão autenticado no
header X-Cliente-Orgao — o TestClient injeta o header direto,
exercitando o MESMO caminho de deps.orgao_atual de produção.
"""


def hdr(orgao: str, **_ignorado) -> dict:
    """Headers de identidade prontos para TestClient."""
    return {"X-Cliente-Orgao": orgao}
