"""Cliente E2E — prova do lado emissor e do round-trip A<->B.

O repo só tinha o lado servidor do envelope. Aqui o ClienteE2E
monta o quadro, dispara contra uvicorn real e decifra a resposta:
1. round-trip POST/GET com E2E_OBRIGATORIO=1;
2. A↔B: nó tjpa cria tramitação, nó mpf.pa recebe o envelope —
   dois apps, dois ports, mesmo envelope cifrado;
3. par que responde em claro => ErroCripto (não engole).
"""
import hashlib
import json

import pytest

from app.cliente_e2e import ClienteE2E
from app.crypto_e2e import ErroCripto
from app.main import create_app
from tests.smoke.dbutil import mk_repo
from tests.smoke.test_sniffer_e2e import CHAVE, _porta_livre

uvicorn = pytest.importorskip("uvicorn")
import threading
import time


def _boot(orgao: str, e2e=True):
    import os
    if e2e:
        os.environ["E2E_CHAVE"] = CHAVE.hex()
        os.environ["E2E_OBRIGATORIO"] = "1"
    else:
        os.environ.pop("E2E_CHAVE", None)
        os.environ.pop("E2E_OBRIGATORIO", None)
    from app.storage import ArmazenamentoMemoria
    app = create_app(orgao, repo_factory=lambda: mk_repo(orgao),
                     storage=ArmazenamentoMemoria(orgao),
                     storage_anon=ArmazenamentoMemoria(
                         orgao, "docs-anonimizados"))
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
    return porta, srv


DOC = b"doc cliente e2e"


def _payload(caso, orgao="tjpa"):
    return dict(caso_cnj=caso, destino="mpf.pa",
                modo="pseudonimizacao",
                hash_documento_sha256=hashlib.sha256(DOC).hexdigest(),
                metadados={}, idempotency_key=f"{orgao}-cli-0001")


class TestEmissor:
    async def test_roundtrip_post_e_get(self, caso):
        porta, srv = _boot("tjpa")
        try:
            cli = ClienteE2E(f"http://127.0.0.1:{porta}", CHAVE,
                             orgao="tjpa")
            r = await cli.post("/v1/tramitacoes", _payload(caso))
            assert r.status_code == 201
            tid = r.json()["id"]
            assert r.json()["origem"] == "tjpa"

            # GET selado canonical: obrigatorio aceita envelope
            r2 = await cli.get(f"/v1/tramitacoes/{tid}")
            assert r2.status_code == 200
            assert r2.json()["caso_cnj"] == caso
            await cli.fechar()
        finally:
            srv.should_exit = True

    async def test_erro_de_dominio_volta_decifrado(self, caso):
        """404/409 saem cifrados pelo middleware — o cliente abre
        e devolve o JSON de erro, não estoura."""
        porta, srv = _boot("tjpa")
        try:
            cli = ClienteE2E(f"http://127.0.0.1:{porta}", CHAVE,
                             orgao="tre-pa")          # órgão errado
            r = await cli.post("/v1/tramitacoes", _payload(caso))
            assert r.status_code == 409             # autenticado,
            assert r.json()["erro"]                  # mas não é o nó
            await cli.fechar()
        finally:
            srv.should_exit = True


class TestAB:
    async def test_tjpa_para_mpfpa(self, caso):
        """Dois nós reais em duas portas: tjpa emite, mpf.pa
        recebe o envelope — o ciclo A->B atravessa o fio cifrado."""
        pa, srv_a = _boot("tjpa")
        pb, srv_b = _boot("mpf.pa")
        try:
            cli_a = ClienteE2E(f"http://127.0.0.1:{pa}", CHAVE,
                               orgao="tjpa")
            r = await cli_a.post("/v1/tramitacoes", _payload(caso))
            assert r.status_code == 201
            tid = r.json()["id"]
            # upload: multipart inteiro selado como um envelope
            up = await cli_a.post_multipart(
                f"/v1/documentos/{tid}/upload",
                "arquivo", "d.pdf", DOC, "application/pdf")
            assert up.status_code in (200, 201), up.content
            env = await cli_a.post(f"/v1/tramitacoes/{tid}/envio",
                                   {})
            assert env.status_code in (200, 201)
            envelope = env.json()
            await cli_a.fechar()

            # nó B ingere o envelope (identidade de A, que o envia)
            cli_b = ClienteE2E(f"http://127.0.0.1:{pb}", CHAVE,
                               orgao="tjpa")
            rb = await cli_b.post("/v1/recebimentos", envelope)
            assert rb.status_code in (200, 201), rb.content
            await cli_b.fechar()
        finally:
            srv_a.should_exit = True
            srv_b.should_exit = True


class TestParForaDoE2E:
    async def test_par_em_claro_levanta(self, caso):
        """Servidor SEM E2E (modo legado): resposta clara =>
        ErroCripto — o emissor não aceita downgrade silencioso."""
        import os
        os.environ.pop("E2E_OBRIGATORIO", None)
        os.environ.pop("E2E_CHAVE", None)
        porta, srv = _boot("tjpa", e2e=False)
        os.environ.pop("E2E_CHAVE", None)   # o app bootou sem chave
        try:
            cli = ClienteE2E(f"http://127.0.0.1:{porta}", CHAVE,
                             orgao="tjpa")
            # app sem chave: middleware bypass — responde em claro
            with pytest.raises(ErroCripto):
                await cli.post("/v1/tramitacoes", _payload(caso))
            await cli.fechar()
        finally:
            srv.should_exit = True
