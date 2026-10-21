"""Dedup de upload — item 2 da análise arquitetural
(docs/analise-arquitetural.md §4, ponto 5).

Defeito: `upload_documento` deduplicava por EXISTÊNCIA do arquivo
no storage. Se a tx pós-`guardar` falhava, o arquivo ficava
órfão e o re-upload caía no ramo `duplicado` — sem `doc_arquivado:`
na trilha e sem evento na outbox: a esteira de IA ficava
permanentemente cega para aquele documento.

Regra correta: duplicata = arquivo existe E evento
`doc_arquivado:` commitado na trilha. Órfão => o re-upload repara
(trilha + outbox) sem regravar o binário.
"""
import io

import pytest
from sqlalchemy import text

from app.service import ErroFluxo, NoTramitacao
from app.storage import ArmazenamentoMemoria
from tests.smoke.conftest import DOC
from tests.smoke.dbutil import FakeUpload, mk_repo
from tests.smoke.test_persistencia import RepoBomba


async def _n_outbox(engine):
    async with engine.connect() as c:
        return (await c.execute(
            text("SELECT count(*) FROM outbox_eventos"))).scalar()


async def _eventos(repo, tid):
    return [t["evento"] for t in await repo.trilha(tid)]


class TestDedupPorEventoCommitado:
    async def test_orfao_reupload_repara_trilha_e_outbox(
            self, payload_criacao):
        """Tx pós-upload falha: arquivo órfão, trilha e outbox
        vazias. O re-upload deve REPARAR — grava `doc_arquivado`
        + evento LGPD — não dedup cego sobre o órfão."""
        e, repo = await mk_repo()
        st = ArmazenamentoMemoria("tjpa")
        no = NoTramitacao("tjpa", repo, st)
        payload_criacao["requer_anonimizacao_lgpd"] = True
        out = await no.criar(payload_criacao)

        no.repo = RepoBomba(repo)          # tx explode no encadear
        with pytest.raises(RuntimeError, match="falha simulada"):
            await no.upload_documento(out.id, FakeUpload(DOC),
                                      no.orgao)
        assert await st.existe(str(out.id))          # órfão real
        assert f"doc_arquivado:{out.id}" not in \
            await _eventos(repo, out.id)
        assert await _n_outbox(e) == 0

        no.repo = repo                     # infra volta ao normal
        resp = await no.upload_documento(out.id, FakeUpload(DOC),
                                         no.orgao)
        assert resp.get("duplicado") is not True
        eventos = await _eventos(repo, out.id)
        assert f"doc_arquivado:{out.id}" in eventos
        assert await _n_outbox(e) == 1
        await e.dispose()

    async def test_duplicado_verdadeiro_nao_repete_eventos(
            self, payload_criacao):
        """Arquivo + evento commitados: re-upload do MESMO doc é
        duplicata de verdade — eco sem segunda linha na trilha nem
        segundo evento na outbox."""
        e, repo = await mk_repo()
        st = ArmazenamentoMemoria("tjpa")
        no = NoTramitacao("tjpa", repo, st)
        payload_criacao["requer_anonimizacao_lgpd"] = True
        out = await no.criar(payload_criacao)
        await no.upload_documento(out.id, FakeUpload(DOC), no.orgao)
        resp = await no.upload_documento(out.id, FakeUpload(DOC),
                                         no.orgao)
        assert resp["duplicado"] is True
        assert await _eventos(repo, out.id) == [
            f"criada:{out.id}", f"doc_arquivado:{out.id}"]
        assert await _n_outbox(e) == 1
        await e.dispose()

    async def test_orfao_divergente_rejeitado(
            self, payload_criacao):
        """Órfão cujos bytes divergem da declaração (storage
        adulterado/corrompido — o upload normal só guarda depois
        do digest bater, então divergência é anomalia): mesmo com
        re-upload correto -> 409, sem evento. Não se escreve
        `doc_arquivado` sobre bytes errados."""
        e, repo = await mk_repo()
        st = ArmazenamentoMemoria("tjpa")
        no = NoTramitacao("tjpa", repo, st)
        out = await no.criar(payload_criacao)
        await st.garantir()
        # órfão fabricado com bytes A != declaração (sha256(DOC))
        await st.guardar(str(out.id),
                         io.BytesIO(b"bytes A adulterados"))
        with pytest.raises(ErroFluxo, match="diverge"):
            await no.upload_documento(out.id, FakeUpload(DOC),
                                      no.orgao)
        assert await _n_outbox(e) == 0
        assert f"doc_arquivado:{out.id}" not in \
            await _eventos(repo, out.id)
        await e.dispose()

    async def test_reupload_divergente_preserva_orfao(
            self, payload_criacao):
        """Re-upload com bytes que não batem a declaração: 409 no
        gate de digest — o órfão permanece intocado no storage e
        nada é gravado."""
        e, repo = await mk_repo()
        st = ArmazenamentoMemoria("tjpa")
        no = NoTramitacao("tjpa", repo, st)
        out = await no.criar(payload_criacao)
        no.repo = RepoBomba(repo)
        with pytest.raises(RuntimeError, match="falha simulada"):
            await no.upload_documento(out.id, FakeUpload(DOC),
                                      no.orgao)
        assert await st.existe(str(out.id))          # órfão=DOC
        no.repo = repo
        with pytest.raises(ErroFluxo, match="difere"):
            await no.upload_documento(
                out.id, FakeUpload(b"bytes B errados"), no.orgao)
        # o órfão segue intacto — nada foi sobrescrito nem marcado
        chunks = [c async for c in st.abrir(str(out.id))]
        assert b"".join(chunks) == DOC
        assert await _n_outbox(e) == 0
        assert f"doc_arquivado:{out.id}" not in \
            await _eventos(repo, out.id)
        await e.dispose()

    async def test_duplicado_reporta_tamanho_real(
            self, payload_criacao):
        """O eco da dedup devolve o tamanho real do documento —
        o spool foi relido, não faz sentido reportar posição 0."""
        e, repo = await mk_repo()
        st = ArmazenamentoMemoria("tjpa")
        no = NoTramitacao("tjpa", repo, st)
        out = await no.criar(payload_criacao)
        await no.upload_documento(out.id, FakeUpload(DOC), no.orgao)
        resp = await no.upload_documento(out.id, FakeUpload(DOC),
                                         no.orgao)
        assert resp["tamanho"] == len(DOC)
        await e.dispose()
