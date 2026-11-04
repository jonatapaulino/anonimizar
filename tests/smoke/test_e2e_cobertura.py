"""Sniffer de cobertura — TODA rota /v1/ sai cifrada no fio.

Dois ângulos:

1. Estático: nenhuma rota da app pode escapar do middleware —
   toda APIRoute está sob /v1/ ou na whitelist pública.
2. Dinâmico: dispara CADA rota (todos os métodos) sobre socket
   real com envelope E2E e prova que a resposta no fio é quadro
   E2E — mesmo quando o handler responde 4xx (a blindagem é da
   camada de transporte, independe do sucesso da regra de negócio).
"""
import json
import re
import socket
import threading
import time

import pytest

from app.crypto_e2e import CT_E2E, abrir, eh_e2e, selar
from app.main import create_app
from tests.smoke.dbutil import mk_repo
from tests.smoke.test_sniffer_e2e import (CHAVE, SENTINELA,
                                        SnifferTCP, _dechunk,
                                        _porta_livre)

uvicorn = pytest.importorskip("uvicorn")

# Rotas fora do perímetro de dados — públicas por desenho.
WHITELIST = {"/healthz", "/openapi.json", "/docs", "/docs/oauth2-redirect",
             "/redoc"}


def _rotas_dados(app):
    """(metodo, path_template) de todas as APIRoute registradas."""
    for r in app.routes:
        path = getattr(r, "path", "")
        methods = getattr(r, "methods", None) or set()
        for m in sorted(methods):
            if path:
                yield m, path


def _materializa(path: str) -> str:
    """{param} -> valor dummy — a rota existe; o handler decidirá
    4xx, mas o fio já provou a blindagem (status é irrelevante)."""
    return re.sub(r"\{[^}]+\}",
                  "00000000-0000-0000-0000-000000000000", path)


@pytest.fixture(scope="module")
def app_e2e():
    # escopo module: um boot por arquivo — monkeypatch de função
    # não serve; env direto com restauração manual.
    import os
    old = {k: os.environ.get(k) for k in
           ("E2E_CHAVE", "E2E_OBRIGATORIO")}
    os.environ["E2E_CHAVE"] = CHAVE.hex()
    os.environ["E2E_OBRIGATORIO"] = "1"
    app = create_app("tjpa", repo_factory=lambda: mk_repo("a"))
    porta = _porta_livre()
    srv = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=porta, log_level="error"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    assert srv.started
    yield app, porta
    srv.should_exit = True
    t.join(timeout=5)
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _dispara(porta: int, metodo: str, path: str) -> bytes:
    corpo = selar(CHAVE, b'{"sniff":"cobertura"}')
    req = (f"{metodo} {path} HTTP/1.1\r\n"
           f"Host: 127.0.0.1:{porta}\r\n"
           f"Content-Type: {CT_E2E}\r\n"
           f"X-E2E-CT: application/json\r\n"
           f"X-Cliente-Orgao: tjpa\r\n"
           f"Content-Length: {len(corpo)}\r\n"
           f"Connection: close\r\n\r\n").encode() + corpo
    s = SnifferTCP("127.0.0.1", porta)
    s.enviar(req)
    wire = s.receber_ate_fim()
    s.fechar()
    return wire


def _corpo_no_fio(wire: bytes) -> bytes:
    hdr_b, _, corpo = wire.partition(b"\r\n\r\n")
    return _dechunk(corpo) if b"chunked" in hdr_b else corpo


class TestNenhumaRotaEscapa:
    def test_estatico_toda_rota_v1_ou_whitelist(self, app_e2e):
        app, _ = app_e2e
        for metodo, path in _rotas_dados(app):
            assert path.startswith("/v1/") or path in WHITELIST, \
                f"{metodo} {path} fora do perímetro E2E"


class TestTodaRespostaECifrada:
    """Dispara cada rota com envelope válido: a resposta no fio
    DEVE ser quadro E2E decifrável — qualquer que seja o status."""

    def test_todas_as_rotas(self, app_e2e):
        app, porta = app_e2e
        falhas = []
        n = 0
        for metodo, path_t in _rotas_dados(app):
            path = _materializa(path_t)
            if path in WHITELIST:
                continue
            n += 1
            wire = _dispara(porta, metodo, path)
            status = wire.split(b" ", 2)[1] if b" " in wire else b"?"
            bruto = _corpo_no_fio(wire)
            if not eh_e2e(bruto):
                falhas.append(
                    f"{metodo} {path} -> {status}: corpo não-E2E "
                    f"({bruto[:60]!r})")
                continue
            try:
                abrir(CHAVE, bruto)
            except Exception as e:
                falhas.append(f"{metodo} {path} -> {status}: "
                              f"selo não abre ({e})")
        assert n > 5, f"só {n} rotas exercitadas — inventário?"
        assert not falhas, "\n".join(falhas)

    def test_sentinela_ausente_em_todas(self, app_e2e):
        """Varredura: nenhuma resposta no fio contém o marcador
        nem JSON legível de domínio."""
        app, porta = app_e2e
        for metodo, path_t in _rotas_dados(app):
            path = _materializa(path_t)
            if path in WHITELIST:
                continue
            wire = _dispara(porta, metodo, path)
            assert SENTINELA.encode() not in wire
            assert b'"caso_cnj"' not in wire
            assert b'"origem"' not in wire, \
                f"{metodo} {path} vazou JSON legível"
