"""Prova da esteira de anonimização no NÓ DESTINO (bug orgao_no).

Antes do fix: o upload em B disparava evento com a ORIGEM do
caso (orgao_origem=A) — o worker de B buscava `A-docs` no MinIO
de B, miss garantido, NACK até DLQ e falha_anonimizacao na
trilha de B.

Depois do fix: o evento carrega orgao_no = dono do storage (o
próprio nó) — worker de B abre mpfpa-docs no MinIO de B, onde a
cópia existe; cada nó anonimiza a SUA cópia.

Fluxo provado (malha real, peer na rede borda):
  A: criar(flag) + upload + envio
  B: recebimento -> download dos bytes em A -> upload em B
  B: relay+worker processam -> doc_anonimizado na trilha de B
  B: GET /download-anonimizado devolve o objeto anonimizado

Uso (host): docker cp scripts/prova_esteira_b.py \
  isaci-malha-peer-1:/run/prova_esteira_b.py && \
  docker exec isaci-malha-peer-1 python /run/prova_esteira_b.py
"""
import asyncio
import hashlib
import os
import sys
import time

sys.path.insert(0, "/srv")
from app.cliente_e2e import ClienteE2E            # noqa: E402

RUN = f"{int(time.time()) % 10_000_000:07d}"
CASO = f"{RUN}-02.2026.8.00.0001"
DOC = (f"processo {CASO} — parte SENTINELA-PII-malha-0001 — "
       f"conteúdo sigiloso").encode()
ESPERA_S = 20          # relay lease + ciclo do worker


async def main() -> int:
    chave = bytes.fromhex(os.environ["E2E_CHAVE"])
    cert = ("/run/certs/tjpa.crt", "/run/certs/tjpa.key")
    ca = "/run/certs/ca.crt"
    cli_a = ClienteE2E("https://nginx-a", chave, cert=cert, verify=ca)
    cli_b = ClienteE2E("https://nginx-b", chave, cert=cert, verify=ca)

    r = await cli_a.post("/v1/tramitacoes", dict(
        caso_cnj=CASO, destino="mpfpa", modo="pseudonimizacao",
        hash_documento_sha256=hashlib.sha256(DOC).hexdigest(),
        metadados={}, idempotency_key=f"tjpa-b-est-{RUN}",
        requer_anonimizacao_lgpd=True))
    print("[A] criar(flag lgpd):", r.status_code)
    assert r.status_code == 201, r.content
    tid = r.json()["id"]

    up = await cli_a.post_multipart(
        f"/v1/documentos/{tid}/upload",
        "arquivo", "d.pdf", DOC, "application/pdf")
    print("[A] upload:", up.status_code)
    assert up.status_code in (200, 201), up.content

    env = await cli_a.post(f"/v1/tramitacoes/{tid}/envio", {})
    assert env.status_code in (200, 201), env.content

    rb = await cli_b.post("/v1/recebimentos", env.json())
    print("[B] recebimentos:", rb.status_code)
    assert rb.status_code in (200, 201), rb.content

    # B baixa os bytes de A (peer age como sistemas de A — CN=tjpa)
    dl = await cli_a.get(f"/v1/documentos/{tid}/download")
    assert dl.status_code == 200 and dl.content == DOC, dl.status_code
    print("[A] download p/ B:", dl.status_code, len(dl.content), "B")

    upb = await cli_b.post_multipart(
        f"/v1/documentos/{tid}/upload",
        "arquivo", "d.pdf", DOC, "application/pdf")
    print("[B] upload (storage de B):", upb.status_code)
    assert upb.status_code in (200, 201), upb.content

    print(f"[*] aguardando esteira de B ({ESPERA_S}s: relay -> "
          f"fila -> worker) ...")
    await asyncio.sleep(ESPERA_S)

    # prova: objeto anonimizado existe no storage de B e trilha
    # de B fechou o ciclo
    st = await cli_b.get(f"/v1/tramitacoes/{tid}")
    trilha = [e["evento"] for e in st.json().get("trilha", [])]
    print("[B] trilha:", trilha)
    assert any(e.startswith("doc_anonimizado") for e in trilha), \
        "doc_anonimizado ausente na trilha de B"

    da = await cli_b.get(
        f"/v1/documentos/{tid}/download-anonimizado")
    print("[B] download-anonimizado:", da.status_code,
          len(da.content), "B")
    assert da.status_code == 200 and len(da.content) > 0

    await cli_a.fechar()
    await cli_b.fechar()
    print("ESTEIRA NO NO DESTINO: OK — B anonimizou a propria copia")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
