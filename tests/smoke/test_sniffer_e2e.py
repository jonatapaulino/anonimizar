"""Sniffer de socket real — prova de que a rede só vê ciphertext.

Sobe a API num uvicorn de verdade (TCP real, não TestClient) e
registra CADA byte que cruza o fio nos dois sentidos. Asserções:

1. corpo do request/reponse no fio é quadro E2E (magia 0xE2);
2. sentinela de PII não aparece em NENHUM byte capturado;
3. controle negativo: a MESMA app sem E2E_CHAVE deixa o claro
   visível no fio — senão o sniffer seria vacuoso.

AMQP/S3: captura de fronteira — os bytes exatos entregues a
exchange.publish / inner.guardar são o que o socket carregaria
(abaixo deles só há TLS de transporte).
"""
import json
import socket
import threading
import time

import pytest

from app.crypto_e2e import CT_E2E, abrir, eh_e2e, selar
from app.main import create_app
from tests.smoke.dbutil import mk_repo

uvicorn = pytest.importorskip("uvicorn")

CHAVE = bytes(range(32))
SENTINELA = "SENTINELA-PII-4f9c2e"


class SnifferTCP:
    """Socket cru — loga todos os bytes que trafegam no fio."""

    def __init__(self, host: str, port: int):
        self.host, self.port = host, port
        self.s = socket.create_connection((host, port), timeout=15)
        self.enviado = bytearray()
        self.recebido = bytearray()

    def enviar(self, dados: bytes):
        self.enviado += dados
        self.s.sendall(dados)

    def receber_ate_fim(self) -> bytes:
        # SEM shutdown(SHUT_WR): o FIN precoce derruba a conexão
        # no h11 antes da resposta. `Connection: close` no request
        # já garante o EOF após a resposta.
        self.s.settimeout(20)
        while True:
            try:
                b = self.s.recv(65536)
            except socket.timeout:
                break
            if not b:
                break
            self.recebido += b
        return bytes(self.recebido)

    def fechar(self):
        self.s.close()


def _porta_livre() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _boot_app(monkeypatch, e2e: bool):
    """uvicorn real num thread — devolve (porta, server)."""
    if e2e:
        monkeypatch.setenv("E2E_CHAVE", CHAVE.hex())
        monkeypatch.setenv("E2E_OBRIGATORIO", "1")
    else:
        monkeypatch.delenv("E2E_CHAVE", raising=False)
        monkeypatch.delenv("E2E_OBRIGATORIO", raising=False)
    app = create_app("tjpa", repo_factory=lambda: mk_repo("a"))
    porta = _porta_livre()
    cfg = uvicorn.Config(app, host="127.0.0.1", port=porta,
                         log_level="warning")
    srv = uvicorn.Server(cfg)
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):                    # espera o bind
        if srv.started:
            break
        time.sleep(0.05)
    assert srv.started, "uvicorn não subiu"
    return porta, srv


def _dechunk(body: bytes) -> bytes:
    """HTTP/1.1 chunked -> conteúdo puro (o que o fio carrega)."""
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


def _post_e2e(sniff: SnifferTCP, path: str, claro_json: bytes,
              orgao="tjpa"):
    corpo = selar(CHAVE, claro_json)
    req = (f"POST {path} HTTP/1.1\r\n"
           f"Host: {sniff.host}:{sniff.port}\r\n"
           f"Content-Type: {CT_E2E}\r\n"
           f"X-E2E-CT: application/json\r\n"
           f"X-Cliente-Orgao: {orgao}\r\n"
           f"Content-Length: {len(corpo)}\r\n"
           f"Connection: close\r\n\r\n").encode() + corpo
    sniff.enviar(req)
    return sniff.receber_ate_fim()


class TestFioSoVeCiphertext:
    def test_wire_nao_vaza_pii(self, monkeypatch, caso):
        import hashlib
        porta, srv = _boot_app(monkeypatch, e2e=True)
        try:
            sniff = SnifferTCP("127.0.0.1", porta)
            p = dict(caso_cnj=caso, destino="mpf.pa",
                     modo="pseudonimizacao",
                     hash_documento_sha256=hashlib.sha256(
                         SENTINELA.encode()).hexdigest(),
                     metadados={"marcador": SENTINELA},
                     idempotency_key="tjpa-sniff-0001")
            claro = json.dumps(p).encode()
            wire = _post_e2e(sniff, "/v1/tramitacoes", claro)
            sniff.fechar()

            # --- o fio NUNCA carregou o claro ---
            todo_o_fio = bytes(sniff.enviado) + wire
            assert SENTINELA.encode() not in todo_o_fio
            assert caso.encode() not in todo_o_fio
            assert b'{"caso_cnj"' not in todo_o_fio

            # --- request no fio já é quadro E2E ---
            corpo_req = bytes(sniff.enviado).split(b"\r\n\r\n", 1)[1]
            assert eh_e2e(corpo_req)
            assert json.loads(abrir(CHAVE, corpo_req)) == p

            # --- response no fio é E2E e decifra de volta ---
            hdr_b, corpo_w = wire.split(b"\r\n\r\n", 1)
            assert b" 201 " in hdr_b.split(b"\r\n")[0]
            assert CT_E2E.encode() in hdr_b
            bruto = _dechunk(corpo_w) if b"chunked" in hdr_b \
                else corpo_w
            assert eh_e2e(bruto)
            resp = json.loads(abrir(CHAVE, bruto))
            assert resp["origem"] == "tjpa"
        finally:
            srv.should_exit = True

    def test_controle_negativo_sem_e2e_vaza(self, monkeypatch, caso):
        """Sem E2E_CHAVE o MESMO payload aparece legível no fio —
        prova de que o sniffer detecta plaintext de verdade."""
        import hashlib
        porta, srv = _boot_app(monkeypatch, e2e=False)
        try:
            sniff = SnifferTCP("127.0.0.1", porta)
            p = dict(caso_cnj=caso, destino="mpf.pa",
                     modo="pseudonimizacao",
                     hash_documento_sha256=hashlib.sha256(
                         SENTINELA.encode()).hexdigest(),
                     metadados={"marcador": SENTINELA},
                     idempotency_key="tjpa-sniff-0002")
            claro = json.dumps(p).encode()
            req = (f"POST /v1/tramitacoes HTTP/1.1\r\n"
                   f"Host: {sniff.host}:{sniff.port}\r\n"
                   f"Content-Type: application/json\r\n"
                   f"X-Cliente-Orgao: tjpa\r\n"
                   f"Content-Length: {len(claro)}\r\n"
                   f"Connection: close\r\n\r\n").encode() + claro
            sniff.enviar(req)
            wire = sniff.receber_ate_fim()
            sniff.fechar()
            # controle: claro visível no fio = sniffer funciona
            assert SENTINELA.encode() in bytes(sniff.enviado)
            assert caso.encode() in bytes(sniff.enviado)
            assert b"caso_cnj" in wire          # resp em claro
            assert not eh_e2e(
                wire.split(b"\r\n\r\n", 1)[1][:34])
        finally:
            srv.should_exit = True

    def test_plaintext_recusado_quando_obrigatorio(
            self, monkeypatch):
        porta, srv = _boot_app(monkeypatch, e2e=True)
        try:
            sniff = SnifferTCP("127.0.0.1", porta)
            claro = b'{"x":1}'
            req = (f"POST /v1/recebimentos HTTP/1.1\r\n"
                   f"Host: {sniff.host}:{sniff.port}\r\n"
                   f"Content-Type: application/json\r\n"
                   f"Content-Length: {len(claro)}\r\n"
                   f"Connection: close\r\n\r\n").encode() + claro
            sniff.enviar(req)
            wire = sniff.receber_ate_fim()
            sniff.fechar()
            assert b" 415 " in wire.split(b"\r\n", 1)[0]
            assert b'{"x":1}' not in wire  # request claro: sim, mas
        finally:                          # resposta nunca espelha
            srv.should_exit = True


class TestFronteiraAmqp:
    """Captura do que sairia pelo socket AMQP — Message.body é o
    byte exato entregue ao broker (TLS de transporte é camada a
    mais, não a menos)."""

    async def test_publicar_so_entrega_ciphertext(self):
        from app.events import PublicadorRabbitMQ
        capturado = []

        class ExStub:
            async def publish(self, msg, routing_key):
                capturado.append((msg, routing_key))

        pub = PublicadorRabbitMQ("amqps://x", chave=CHAVE)
        pub._ex = ExStub()                 # injeta sem conectar
        await pub.publicar({"id_documento": "d-1",
                            "orgao_no": "tjpa",
                            "marcador": SENTINELA})
        msg, rk = capturado[0]
        assert rk == PublicadorRabbitMQ.RK_ANON
        assert msg.content_type == CT_E2E
        assert eh_e2e(msg.body)
        assert SENTINELA.encode() not in msg.body
        assert json.loads(abrir(CHAVE, msg.body))["marcador"] \
            == SENTINELA


class TestFronteiraS3:
    """Captura do que o backend persistiria — bytes entregues ao
    MinIO/memória são ciphertext puro."""

    async def test_guardar_entrega_só_quadros(self):
        import io
        from app.storage import (ArmazenamentoCifrado,
                                 ArmazenamentoMemoria)
        capturado = {}

        class SniffInner(ArmazenamentoMemoria):
            async def guardar(self, chave, fonte):
                capturado[chave] = fonte.read()
                await super().guardar(chave, io.BytesIO(
                    capturado[chave]))

        st = ArmazenamentoCifrado(SniffInner("tjpa"), CHAVE)
        dados = f"doc com {SENTINELA}".encode() * 5000   # > CHUNK?
        dados = dados[:200_000]
        await st.guardar("doc-sniff", io.BytesIO(dados))
        bruto = capturado["doc-sniff"]
        assert eh_e2e(bruto)
        assert SENTINELA.encode() not in bruto
        claro = b"".join([c async for c in st.abrir("doc-sniff")])
        assert claro == dados
