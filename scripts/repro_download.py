"""Reprodução do travamento no download E2E+MinIO (diagnóstico).

Sobe o nó tjpa local com o MESMO caminho da malha:
ArmazenamentoCifrado(ArmazenamentoMinIO) + MiddlewareE2E +
StreamingResponse. `faulthandler.dump_traceback_later` despeja o
stack de todas as threads se o processo ficar preso — o frame
repetido no topo aponta o loop síncrono.

Uso: docker start edvar-minio-dev && python scripts/repro_download.py
"""
import asyncio
import faulthandler
import hashlib
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CHAVE = bytes.fromhex("ab" * 32)
os.environ["E2E_CHAVE"] = CHAVE.hex()
os.environ["E2E_OBRIGATORIO"] = "1"
os.environ["MINIO_URL"] = os.environ.get("MINIO_URL",
                                         "http://localhost:9000")
os.environ["MINIO_USER"] = "edvar"
os.environ["MINIO_PASS"] = "edvar_dev_minio"

# dump automático de TODOS os stacks se ficar preso >20s
faulthandler.dump_traceback_later(20, exit=True)

from app.cliente_e2e import ClienteE2E          # noqa: E402
from app.main import create_app               # noqa: E402
from tests.smoke.dbutil import mk_repo        # noqa: E402

DOC = b"%PDF-1.4 documento de teste para download E2E\n" * 300
PORTA = 18123


async def main():
    import uvicorn
    app = create_app("tjpa", repo_factory=lambda: mk_repo("a"))
    srv = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=PORTA, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(200):
        if srv.started:
            break
        time.sleep(0.05)
    assert srv.started, "uvicorn não subiu"

    cli = ClienteE2E(f"http://127.0.0.1:{PORTA}", CHAVE, orgao="tjpa")
    r = await cli.post("/v1/tramitacoes", dict(
        caso_cnj="0000001-00.2026.8.14.0000", destino="mpf.pa",
        modo="pseudonimizacao",
        hash_documento_sha256=hashlib.sha256(DOC).hexdigest(),
        metadados={}, idempotency_key="repro-download-1"))
    print("criar:", r.status_code)
    assert r.status_code == 201, r.content
    tid = r.json()["id"]

    up = await cli.post_multipart(
        f"/v1/documentos/{tid}/upload",
        "arquivo", "d.pdf", DOC, "application/pdf")
    print("upload:", up.status_code)
    assert up.status_code == 201, up.content

    try:
        d = await asyncio.wait_for(
            cli.get(f"/v1/documentos/{tid}/download"), 12)
        print("download:", d.status_code,
              "integro:", d.content == DOC,
              "bytes:", len(d.content))
    except Exception as e:
        print("download FALHOU:", type(e).__name__, e)
        print("aguardando o dump do faulthandler (20s)...")
        time.sleep(22)          # handler do server ainda gira
    srv.should_exit = True


asyncio.run(main())
