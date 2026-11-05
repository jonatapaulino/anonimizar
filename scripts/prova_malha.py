"""Round-trip REAL A↔B na malha — roda dentro do contêiner `peer`
(rede `borda`, só vê os dois nginx):

  peer --mTLS(tjpa)--> nginx-a --interna--> api-a   (cria+upload+envio)
  peer --mTLS(tjpa)--> nginx-b --interna--> api-b   (recebimentos)

Todo hop interno já é TLS (amqps/https/pg-ssl/vault-https); o
envelope E2E atravessa intocado — a prova de pcap complementa:
na `interna` só existem registros TLS e HTTP-com-quadros.

Uso (host): docker exec isaci-malha-peer-1 python /run/prova_malha.py
"""
import asyncio
import hashlib
import os
import sys

sys.path.insert(0, "/srv")
from app.cliente_e2e import ClienteE2E            # noqa: E402

SENTINELA = "SENTINELA-PII-malha-0001"
# caso único por execução (idempotência devolve a mesma
# tramitação se repete — aí envio seria transição ilegal)
RUN = f"{int(__import__('time').time()) % 10_000_000:07d}"
CASO = f"{RUN}-01.2026.8.00.0001"    # padrão CNJ válido


async def main() -> int:
    chave = bytes.fromhex(os.environ["E2E_CHAVE"])
    cert = ("/run/certs/tjpa.crt", "/run/certs/tjpa.key")
    ca = "/run/certs/ca.crt"

    doc = (f"processo {CASO} — parte {SENTINELA} — "
           f"conteúdo sigiloso").encode()
    cli_a = ClienteE2E("https://nginx-a", chave,
                       cert=cert, verify=ca)

    r = await cli_a.post("/v1/tramitacoes", dict(
        caso_cnj=CASO, destino="mpfpa", modo="pseudonimizacao",
        hash_documento_sha256=hashlib.sha256(doc).hexdigest(),
        metadados={"sentinela": SENTINELA},
        idempotency_key=f"tjpa-malha-{RUN}"))
    print("[A] criar:", r.status_code)
    assert r.status_code == 201, r.content
    tid = r.json()["id"]

    up = await cli_a.post_multipart(
        f"/v1/documentos/{tid}/upload",
        "arquivo", "d.pdf", doc, "application/pdf")
    print("[A] upload:", up.status_code)
    assert up.status_code in (200, 201), up.content

    env = await cli_a.post(f"/v1/tramitacoes/{tid}/envio", {})
    print("[A] envio:", env.status_code)
    assert env.status_code in (200, 201), env.content
    envelope = env.json()

    st = await cli_a.get(f"/v1/tramitacoes/{tid}")
    print("[A] status:", st.json().get("status"))
    await cli_a.fechar()

    # B recebe o envelope (quem envia é A — CN=tjpa no cert)
    cli_b = ClienteE2E("https://nginx-b", chave,
                       cert=cert, verify=ca)
    rb = await cli_b.post("/v1/recebimentos", envelope)
    print("[B] recebimentos:", rb.status_code)
    assert rb.status_code in (200, 201), rb.content
    print("[B] resposta:", rb.json())
    await cli_b.fechar()

    print("ROUND-TRIP A↔B REAL: OK — tid:", tid)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
