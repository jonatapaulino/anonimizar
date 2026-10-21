"""T12 — consulta de processo (GET /v1/tramitacoes/{ident}) e
download do anonimizado.

`ident` é polimórfico: UUID -> busca por id; texto -> busca por
id_processo (caso CNJ). Isolamento: só origem/destino do caso
enxergam — terceiro recebe 404 (nem a existência vaza).

O passo "worker processa" do E2E roda via `client.portal.call`:
a corrotina executa DENTRO do loop do TestClient — o mesmo loop
onde o repo/engine do app vivem (sqlite StaticPool e asyncpg são
fiéis ao loop que os criou; chamar de fora quebraria a conexão).
"""
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.storage import ArmazenamentoMemoria
from app.worker import StubMotorIA, processar_evento
from tests.jwthelper import hdr
from tests.smoke.conftest import DOC, HASH_DOC
from tests.smoke.dbutil import mk_repo

CASO = "5614226-41.2021.8.14.2679"


@pytest.fixture
def stack():
    """Nó A via HTTP com os DOIS buckets (bruto + anonimizado)."""
    st = ArmazenamentoMemoria("tjpa")
    st_anon = ArmazenamentoMemoria(
        "tjpa", nome_bucket="tjpa-docs-anonimizados")
    with TestClient(create_app(
            "tjpa", repo_factory=lambda: mk_repo("a"),
            storage=st, storage_anon=st_anon)) as c:
        yield c, st, st_anon


@pytest.fixture
def payload():
    return dict(
        caso_cnj=CASO, destino="mpf.pa", modo="pseudonimizacao",
        hash_documento_sha256=HASH_DOC,
        metadados={"assunto": "dano moral"},
        idempotency_key="tjpa-t12-consulta-01",
        requer_anonimizacao_lgpd=True)


def _criar_e_upar(ca, payload):
    r = ca.post("/v1/tramitacoes", json=payload, headers=hdr("tjpa"))
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    up = ca.post(f"/v1/documentos/{tid}/upload",
                 files={"arquivo": ("peca.pdf", DOC,
                                    "application/pdf")},
                 headers=hdr("tjpa"))
    assert up.status_code == 201, up.text
    return tid


class TestConsulta:
    def test_por_uuid_retorna_status_e_trilha(self, stack, payload):
        ca, _, _ = stack
        tid = _criar_e_upar(ca, payload)
        r = ca.get(f"/v1/tramitacoes/{tid}", headers=hdr("tjpa"))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["id"] == tid and d["status"] == "criada"
        assert d["metadados"]["assunto"] == "dano moral"
        assert d["requer_anonimizacao_lgpd"] is True
        assert d["anonimizacao_concluida"] is False
        evs = [e["evento"] for e in d["trilha"]]
        assert evs == [f"criada:{tid}", f"doc_arquivado:{tid}"]

    def test_por_id_processo_mesmo_resultado(self, stack, payload):
        ca, _, _ = stack
        tid = _criar_e_upar(ca, payload)
        r = ca.get(f"/v1/tramitacoes/{CASO}", headers=hdr("tjpa"))
        assert r.status_code == 200
        assert r.json()["id"] == tid

    def test_cadeia_de_hashes_integra(self, stack, payload):
        """DoD: a trilha exposta é encadeada — hash_anterior[i+1]
        == hash_cadeia[i], e cada topo é sha256 (64 hex)."""
        ca, _, _ = stack
        tid = _criar_e_upar(ca, payload)
        trilha = ca.get(f"/v1/tramitacoes/{tid}",
                        headers=hdr("tjpa")).json()["trilha"]
        for ev in trilha:
            assert len(ev["hash_cadeia"]) == 64
        for ant, prox in zip(trilha, trilha[1:]):
            assert prox["hash_anterior"] == ant["hash_cadeia"]

    def test_isolamento_terceiro_404(self, stack, payload):
        """DoD: órgão terceiro (nem origem nem destino) leva 404
        nos DOIS identificadores — existência não vaza."""
        ca, _, _ = stack
        tid = _criar_e_upar(ca, payload)
        assert ca.get(f"/v1/tramitacoes/{tid}",
                      headers=hdr("tre-pa")).status_code == 404
        assert ca.get(f"/v1/tramitacoes/{CASO}",
                      headers=hdr("tre-pa")).status_code == 404

    def test_sem_token_401(self, stack):
        ca, _, _ = stack
        assert ca.get("/v1/tramitacoes/qualquer").status_code == 401


class TestDownloadAnonimizado:
    def test_baixa_versao_sanitizada(self, stack, payload):
        ca, st, st_anon = stack
        tid = _criar_e_upar(ca, payload)
        # simula a esteira: anonimizado gravado pelo worker
        import io
        ca.portal.call(st_anon.guardar, tid, io.BytesIO(b"ANON"))
        r = ca.get(f"/v1/documentos/{tid}/download-anonimizado",
                   headers=hdr("tjpa"))
        assert r.status_code == 200 and r.content == b"ANON"

    def test_ausente_404(self, stack, payload):
        ca, _, _ = stack
        tid = _criar_e_upar(ca, payload)
        r = ca.get(f"/v1/documentos/{tid}/download-anonimizado",
                   headers=hdr("tjpa"))
        assert r.status_code == 404

    def test_terceiro_404(self, stack, payload):
        ca, _, _ = stack
        tid = _criar_e_upar(ca, payload)
        r = ca.get(f"/v1/documentos/{tid}/download-anonimizado",
                   headers=hdr("tre-pa"))
        assert r.status_code == 404


class TestE2EComWorker:
    def test_ciclo_completo_ate_consulta(self, stack, payload):
        """DoD T12: POST -> upload -> worker processa ->
        GET consulta traz trilha inteira + flag de conclusão."""
        ca, st, st_anon = stack
        tid = _criar_e_upar(ca, payload)
        no = ca.app.state.no
        # worker processa dentro do loop do app (portal) — mesmo
        # engine/repo das rotas; motor stub, zero tokens
        ca.portal.call(
            processar_evento,
            {"id_documento": tid, "orgao_origem": "tjpa",
             "id_processo": CASO},
            st, st_anon, StubMotorIA(atraso=0), no.repo)
        d = ca.get(f"/v1/tramitacoes/{tid}",
                   headers=hdr("tjpa")).json()
        evs = [e["evento"] for e in d["trilha"]]
        assert evs == [f"criada:{tid}", f"doc_arquivado:{tid}",
                       f"doc_anonimizado:{tid}"]
        assert d["anonimizacao_concluida"] is True
        # e o PDF sanitizado já sai pelo endpoint dedicado
        dl = ca.get(f"/v1/documentos/{tid}/download-anonimizado",
                    headers=hdr("tjpa"))
        assert dl.status_code == 200 and dl.content == DOC
