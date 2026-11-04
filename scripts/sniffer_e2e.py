"""Sniffer E2E — demo visual: mostra EXATAMENTE o que a rede vê.

Sobe a API num uvicorn real (TCP, não TestClient), dispara um
POST E2E com sentinela de PII e imprime:

  1. bytes crus do REQUEST no fio
  2. bytes crus da RESPONSE no fio (dechunked)
  3. decifragem local de prova (só quem tem a chave lê)
  4. veredito: sentinela presente/ausente no fio

Uso:
    E2E_DEMO_SEM_CHAVE=1 python scripts/sniffer_e2e.py   # controle
    python scripts/sniffer_e2e.py                      # blindado
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CHAVE = bytes(range(32))
SENTINELA = "SENTINELA-PII-4f9c2e"


def _porta_livre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _dechunk(body: bytes) -> bytes:
    out, i = b"", 0
    while True:
        j = body.find(b"\r\n", i)
        if j < 0:
            return out
        n = int(body[i:j].split(b";")[0], 16)
        if n == 0:
            return out
        out += body[j + 2: j + 2 + n]
        i = j + 2 + n + 2


def _hexdump(b: bytes, limite: int = 160) -> str:
    fat = b[:limite]
    hx = " ".join(f"{x:02x}" for x in fat)
    asc = "".join(chr(x) if 32 <= x < 127 else "." for x in fat)
    return f"{hx}\n    |{asc}|" + (" …[+]" if len(b) > limite else "")


def main() -> int:
    import uvicorn
    from app.crypto_e2e import CT_E2E, abrir, eh_e2e, selar
    from app.main import create_app
    from tests.smoke.dbutil import mk_repo

    sem_chave = os.environ.get("E2E_DEMO_SEM_CHAVE") == "1"
    if sem_chave:
        os.environ.pop("E2E_CHAVE", None)
        os.environ.pop("E2E_OBRIGATORIO", None)
        print("== MODO CONTROLE (sem E2E) ==")
    else:
        os.environ["E2E_CHAVE"] = CHAVE.hex()
        os.environ["E2E_OBRIGATORIO"] = "1"
        print("== MODO BLINDADO (E2E obrigatório) ==")

    app = create_app("tjpa", repo_factory=lambda: mk_repo("a"))
    porta = _porta_livre()
    srv = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=porta, log_level="error"))
    threading.Thread(target=srv.run, daemon=True).start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)

    caso = "0000001-23.2026.8.13.0001"
    p = dict(caso_cnj=caso, destino="mpf.pa", modo="pseudonimizacao",
             hash_documento_sha256=hashlib.sha256(
                 SENTINELA.encode()).hexdigest(),
             metadados={"marcador": SENTINELA},
             idempotency_key="sniff-demo-0001")
    claro = json.dumps(p).encode()

    if sem_chave:
        corpo, ct, extra = claro, "application/json", ""
    else:
        corpo, ct, extra = selar(CHAVE, claro), CT_E2E, \
            "X-E2E-CT: application/json\r\n"
    req = (f"POST /v1/tramitacoes HTTP/1.1\r\n"
           f"Host: 127.0.0.1:{porta}\r\n"
           f"Content-Type: {ct}\r\n{extra}"
           f"X-Cliente-Orgao: tjpa\r\n"
           f"Content-Length: {len(corpo)}\r\n"
           f"Connection: close\r\n\r\n").encode() + corpo

    s = socket.create_connection(("127.0.0.1", porta))
    s.sendall(req)
    s.settimeout(20)
    wire = b""
    while True:
        b = s.recv(65536)
        if not b:
            break
        wire += b
    s.close()
    srv.should_exit = True

    print("\n--- O QUE SAIU DO CLIENTE (request no fio) ---")
    print(_hexdump(req))
    print("\n--- O QUE VOLTOU DO SERVIDOR (response no fio) ---")
    print(_hexdump(wire))

    hdr_b, _, corpo_w = wire.partition(b"\r\n\r\n")
    bruto = _dechunk(corpo_w) if b"chunked" in hdr_b else corpo_w
    status = hdr_b.split(b"\r\n", 1)[0].decode(errors="replace")
    print(f"\nstatus: {status}")

    corpo_req = req.split(b"\r\n\r\n", 1)[1]
    if eh_e2e(corpo_req) and not sem_chave:
        print("request no fio: quadro E2E (0xE2) — decifrando:  ",
          json.loads(abrir(CHAVE, corpo_req))["caso_cnj"])
    if eh_e2e(bruto) and not sem_chave:
        print("response no fio: quadro E2E (0xE2) — decifrando:  ",
          json.loads(abrir(CHAVE, bruto))["origem"])

    fio = req + wire
    vazou = SENTINELA.encode() in fio or caso.encode() in fio
    print(f"\nsentinela '{SENTINELA}' no fio: {'SIM' if SENTINELA.encode() in fio else 'não'}")
    print(f"caso_cnj '{caso}' no fio: {'SIM' if caso.encode() in fio else 'não'}")
    print("\nVEREDITO:",
          "REDE VÊ CLARO — falha de blindagem" if vazou
          else "REDE SÓ VÊ CIPHERTEXT — blindagem provada")
    return 1 if (vazou != sem_chave) else 0


if __name__ == "__main__":
    raise SystemExit(main())
