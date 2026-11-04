"""Handshake mTLS real — prova do mecanismo de identidade.

Gera a CA dev + certs com scripts/gerar_certs_mtls.py (o MESMO
artefato que alimenta deploy/nginx.conf) e executa handshakes TLS
1.3 reais entre sockets Python:

1. servidor exige client-cert (ssl.CERT_REQUIRED — o
   ssl_verify_client do nginx): cliente COM cert do par (CN=tjpa)
   passa e o servidor extrai a identidade do CN — é exatamente o
   $ssl_client_s_dn -> X-Cliente-Orgao do nginx.conf;
2. cliente SEM certificado: handshake rejeitado;
3. cliente com cert de OUTRA CA (CA forjada): rejeitado — não
   basta ter cert, tem que ser da cadeia confiável.

A config do nginx permanece contrato estático (test_isolamento);
aqui se prova a PRIMITIVA que ela declara.
"""
import socket
import ssl
import subprocess
import sys
import threading
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def certs(tmp_path_factory):
    """CA dev + cert do nó + cert de cliente CN=tjpa (e uma CA
    forjada para o controle de cadeia errada)."""
    out = tmp_path_factory.mktemp("certs")
    subprocess.run(
        [sys.executable, "scripts/gerar_certs_mtls.py",
         "--out", str(out), "--node", "tjpa",
         "--peers", "tjpa"], cwd=RAIZ, check=True,
        capture_output=True)
    out2 = tmp_path_factory.mktemp("certs-forjada")
    subprocess.run(
        [sys.executable, "scripts/gerar_certs_mtls.py",
         "--out", str(out2), "--node", "x",
         "--peers", "tjpa"], cwd=RAIZ, check=True,
        capture_output=True)
    return out, out2


def _ctx_srv(out: Path) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(out / "node.crt", out / "node.key")
    ctx.load_verify_locations(cafile=str(out / "ca.crt"))
    ctx.verify_mode = ssl.CERT_REQUIRED        # ssl_verify_client on
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    return ctx


def _ctx_cli(out: Path, com_cert: Path | None = None) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(cafile=str(out / "ca.crt"))
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    if com_cert:
        ctx.load_cert_chain(com_cert.with_suffix(".crt"),
                            com_cert.with_suffix(".key"))
    return ctx


def _servidor(ctx: ssl.SSLContext, resultado: dict):
    ls = socket.socket()
    ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    ls.bind(("127.0.0.1", 0))
    ls.listen(1)
    resultado["porta"] = ls.getsockname()[1]
    resultado["pronto"] = True
    try:
        conn, _ = ls.accept()
        try:
            tls = ctx.wrap_socket(conn, server_side=True)
            cert = tls.getpeercert()
            cn = dict(x[0] for x in cert["subject"])
            resultado["cn"] = cn.get("commonName")
            tls.sendall(b"ok")
            tls.close()
        except ssl.SSLError as e:
            resultado["erro_srv"] = e
    finally:
        ls.close()


def _handshake(certs, com_cert=None, ca_cli=None):
    """Roda um handshake real; devolve dict com cn/erros."""
    import time
    out, _ = certs
    ctx_srv = _ctx_srv(out)
    resultado: dict = {}
    t = threading.Thread(target=_servidor,
                         args=(ctx_srv, resultado), daemon=True)
    t.start()
    for _ in range(200):
        if "pronto" in resultado:
            break
        time.sleep(0.01)
    out_cli = out if ca_cli is None else ca_cli
    ctx_cli = _ctx_cli(out_cli, com_cert)
    erro_cli = None
    try:
        raw = socket.create_connection(
            ("127.0.0.1", resultado["porta"]), timeout=10)
        tls = ctx_cli.wrap_socket(raw, server_hostname="localhost")
        tls.recv(16)
        tls.close()
    except (ssl.SSLError, ConnectionResetError, OSError) as e:
        erro_cli = e
    t.join(timeout=10)
    resultado["erro_cli"] = erro_cli
    return resultado


class TestIdentidadePorCertificado:
    def test_cert_valido_cn_vira_identidade(self, certs):
        out, _ = certs
        r = _handshake(certs, com_cert=out / "tjpa")
        assert r["erro_cli"] is None, f"handshake falhou: {r}"
        assert r["cn"] == "tjpa"    # = X-Cliente-Orgao do nginx

    def test_sem_cert_handshake_rejeitado(self, certs):
        r = _handshake(certs, com_cert=None)
        assert r.get("cn") is None
        assert r["erro_cli"] is not None or \
            r.get("erro_srv") is not None

    def test_cert_de_outra_ca_rejeitado(self, certs):
        out, forjada = certs
        # cliente confia na CA REAL (server cert ok) mas apresenta
        # cert 'tjpa' assinado por CA forjada — o servidor verifica
        # a cadeia do cliente contra ca.crt real: nome certo,
        # cadeia errada => rejeitado.
        r = _handshake(certs, com_cert=forjada / "tjpa")
        assert r.get("cn") is None
        assert r["erro_cli"] is not None or \
            r.get("erro_srv") is not None
