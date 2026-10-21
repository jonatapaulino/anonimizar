"""Storage físico (T8) — bucket por órgão, integridade estrita,
streaming. Memória no TDD; MinIO real quando MINIO_URL está
definida (suíte de integração)."""
import hashlib
import io
import os

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.service import ErroFluxo, ErroNaoEncontrado, NoTramitacao
from app.storage import (ArmazenamentoMemoria, ArmazenamentoMinIO,
                         bucket_para)
from tests.jwthelper import hdr
from tests.smoke.dbutil import mk_repo

DOC = b"EXCELENTISSIMO SENHOR DOUTOR JUIZ - processo de teste."
HASH_DOC = hashlib.sha256(DOC).hexdigest()


class _Up:
    """Shim async-readable com a cara de UploadFile."""
    def __init__(self, b: bytes):
        self._f = io.BytesIO(b)

    async def read(self, n=-1):
        return self._f.read(n)


async def _no_com_storage():
    e, repo = await mk_repo()
    st = ArmazenamentoMemoria("tjpa")
    return e, repo, st, NoTramitacao("tjpa", repo, st)


class TestPorta:
    def test_bucket_por_orgao(self):
        assert bucket_para("tjpa") == "tjpa-docs"
        assert bucket_para("mpf.pa") == "mpf-pa-docs"   # sanitizado


class TestServico:
    async def test_upload_integro_e_download(
            self, payload_criacao):
        e, repo, st, no = await _no_com_storage()
        out = await no.criar(payload_criacao)
        r = await no.upload_documento(out.id, _Up(DOC), no.orgao)
        assert r["sha256"] == out.hash_documento_sha256
        # download devolve os mesmos bytes
        got = b"".join([c async for c in await no.abrir_documento(
            out.id, no.orgao)])
        assert got == DOC
        await e.dispose()

    async def test_upload_hash_divergente_rejeita(
            self, payload_criacao):
        e, repo, st, no = await _no_com_storage()
        out = await no.criar(payload_criacao)
        with pytest.raises(ErroFluxo, match="difere"):
            await no.upload_documento(out.id, _Up(b"OUTRO DOC"), no.orgao)
        assert await st.existe(str(out.id)) is False  # não gravou
        await e.dispose()

    async def test_upload_tramitacao_inexistente(
            self, payload_criacao):
        e, repo, st, no = await _no_com_storage()
        import uuid
        with pytest.raises(ErroNaoEncontrado):
            await no.upload_documento(uuid.uuid4(), _Up(DOC), no.orgao)
        await e.dispose()

    async def test_sem_storage_configurado(self,
                                           payload_criacao):
        e, repo = await mk_repo()
        no = NoTramitacao("tjpa", repo)          # sem storage
        out = await no.criar(payload_criacao)
        with pytest.raises(ErroFluxo, match="não configurado"):
            await no.upload_documento(out.id, _Up(DOC), no.orgao)
        # e o gate de envio também exige storage
        with pytest.raises(ErroFluxo, match="não configurado"):
            await no.enviar(out.id, no.orgao)
        await e.dispose()


@pytest.fixture
def ca_st():
    async def fab():
        e, r = await mk_repo("a")
        return e, r
    with TestClient(create_app(
            "tjpa", repo_factory=fab,
            storage=ArmazenamentoMemoria("tjpa"))) as c:
        yield c


class TestHTTP:
    def test_upload_download_roundtrip(self, ca_st, caso):
        r = ca_st.post("/v1/tramitacoes", json=dict(
            caso_cnj=caso, destino="mpf.pa", modo="pseudonimizacao",
            hash_documento_sha256=HASH_DOC,
            idempotency_key="upload-0001"), headers=hdr("tjpa"))
        tid = r.json()["id"]
        up = ca_st.post(f"/v1/documentos/{tid}/upload",
                        files={"arquivo": ("peca.pdf", DOC,
                                           "application/pdf")},
                        headers=hdr("tjpa"))
        assert up.status_code == 201
        dl = ca_st.get(f"/v1/documentos/{tid}/download",
                       headers=hdr("tjpa"))
        assert dl.status_code == 200 and dl.content == DOC

    def test_upload_hash_errado_409(self, ca_st, caso):
        r = ca_st.post("/v1/tramitacoes", json=dict(
            caso_cnj=caso, destino="mpf.pa", modo="pseudonimizacao",
            hash_documento_sha256=HASH_DOC,
            idempotency_key="upload-0002"), headers=hdr("tjpa"))
        tid = r.json()["id"]
        up = ca_st.post(f"/v1/documentos/{tid}/upload",
                        files={"arquivo": ("falso.pdf",
                                           b"CONTEUDO FALSO")},
                        headers=hdr("tjpa"))
        assert up.status_code == 409

    def test_upload_sem_auth_401(self, ca_st):
        import uuid
        up = ca_st.post(f"/v1/documentos/{uuid.uuid4()}/upload",
                        files={"arquivo": ("a.pdf", b"x")})
        assert up.status_code == 401

    def test_upload_acima_do_limite_413(self, ca_st, caso):
        """MAX_DOC_BYTES (20 MiB, comum.py) finalmente aplicado:
        upload gigante -> 413, sem spoolar o arquivo inteiro."""
        from app.schemas.comum import MAX_DOC_BYTES
        r = ca_st.post("/v1/tramitacoes", json=dict(
            caso_cnj=caso, destino="mpf.pa", modo="pseudonimizacao",
            hash_documento_sha256="0" * 64,   # não importa — o
            idempotency_key="upload-big01"),  # limite corta antes
            headers=hdr("tjpa"))
        tid = r.json()["id"]
        big = b"x" * (MAX_DOC_BYTES + 1)
        up = ca_st.post(f"/v1/documentos/{tid}/upload",
                        files={"arquivo": ("grande.pdf", big)},
                        headers=hdr("tjpa"))
        assert up.status_code == 413

    def test_download_inexistente_404(self, ca_st, caso):
        r = ca_st.post("/v1/tramitacoes", json=dict(
            caso_cnj=caso, destino="mpf.pa", modo="pseudonimizacao",
            hash_documento_sha256=HASH_DOC,
            idempotency_key="upload-0003"), headers=hdr("tjpa"))
        tid = r.json()["id"]
        dl = ca_st.get(f"/v1/documentos/{tid}/download",
                       headers=hdr("tjpa"))
        assert dl.status_code == 404


# ---------- integração MinIO real (MINIO_URL definida) ----------
MINIO_URL = os.environ.get("MINIO_URL")


@pytest.mark.skipif(not MINIO_URL, reason="MinIO não disponível")
class TestMinIOReal:
    async def test_roundtrip_minio(self, payload_criacao):
        st = ArmazenamentoMinIO(
            "tjpa", MINIO_URL,
            os.environ.get("MINIO_USER", "edvar"),
            os.environ.get("MINIO_PASS", "edvar_dev_minio"))
        await st.garantir()
        e, repo = await mk_repo()
        no = NoTramitacao("tjpa", repo, st)
        out = await no.criar(payload_criacao)
        r = await no.upload_documento(out.id, _Up(DOC), no.orgao)
        assert r["sha256"] == out.hash_documento_sha256
        got = b"".join(
            [c async for c in await no.abrir_documento(out.id, no.orgao)])
        assert got == DOC
        await st.fechar()
        await e.dispose()
