"""Eventos de domínio via OUTBOX transacional (ADR-0013, T9).

A asserção é na TABELA outbox_eventos. T9 mudou o gatilho: o
evento de IA só nasce DEPOIS do upload físico validado — criar
sem upload não notifica a esteira (documento não existe).
"""
import json

import pytest
from sqlalchemy import text

from tests.smoke.dbutil import FakeUpload

DOC = b"EXCELENTISSIMO SENHOR DOUTOR JUIZ - processo de teste."


async def _outbox(e):
    async with e.connect() as c:
        linhas = [dict(r._mapping) for r in (await c.execute(text(
            "SELECT * FROM outbox_eventos ORDER BY criado_em")))
            .all()]
    for l in linhas:                       # sqlite devolve texto
        if isinstance(l["payload"], str):
            l["payload"] = json.loads(l["payload"])
    return linhas


class TestEmissao:
    async def test_fluxo_completo_separado(self, org_a,
                                           payload_criacao):
        """DoD T9: 1) cria (metadados) → outbox VAZIA;
        2) upload do binário validado → 1 evento na outbox.
        A IA só é notificada quando o arquivo existe de verdade."""
        payload_criacao["requer_anonimizacao_lgpd"] = True
        out = await org_a.criar(payload_criacao)
        # passo 1: criação NÃO emite — o arquivo ainda não existe
        assert await _outbox(org_a.repo._engine) == []
        # passo 2: upload íntegro → evento commitado
        await org_a.upload_documento(out.id, FakeUpload(DOC), org_a.orgao)
        linhas = await _outbox(org_a.repo._engine)
        assert len(linhas) == 1
        ev = linhas[0]
        assert ev["tipo_evento"] == "DocumentoProntoParaAnonimizacao"
        assert str(ev["status"]) in ("PENDENTE",
                                     "StatusOutbox.PENDENTE")
        assert ev["tentativas"] == 0
        assert ev["payload"]["id_documento"] == str(out.id)
        assert ev["payload"]["orgao_origem"] == "tjpa"
        assert ev["payload"]["id_processo"] == \
            payload_criacao["caso_cnj"]

    async def test_upload_sem_flag_nao_grava(self, org_a,
                                             payload_criacao):
        out = await org_a.criar(payload_criacao)     # flag False
        await org_a.upload_documento(out.id, FakeUpload(DOC), org_a.orgao)
        assert await _outbox(org_a.repo._engine) == []

    async def test_upload_hash_errado_nao_grava(self, org_a,
                                                payload_criacao):
        """Upload rejeitado (hash diverge) não emite — arquivo
        nunca chegou a existir fisicamente."""
        from app.service import ErroFluxo
        payload_criacao["requer_anonimizacao_lgpd"] = True
        out = await org_a.criar(payload_criacao)
        with pytest.raises(ErroFluxo, match="difere"):
            await org_a.upload_documento(out.id,
                                         FakeUpload(b"FALSO"),
                                         org_a.orgao)
        assert await _outbox(org_a.repo._engine) == []

    async def test_reupload_nao_duplica_evento(self, org_a,
                                               payload_criacao):
        """Upload idempotente: re-POST do mesmo doc não emite
        segundo evento (dedup antes do broker)."""
        payload_criacao["requer_anonimizacao_lgpd"] = True
        out = await org_a.criar(payload_criacao)
        await org_a.upload_documento(out.id, FakeUpload(DOC), org_a.orgao)
        r2 = await org_a.upload_documento(out.id, FakeUpload(DOC), org_a.orgao)
        assert r2.get("duplicado") is True
        assert len(await _outbox(org_a.repo._engine)) == 1

    async def test_receber_nao_emite(self, org_a, org_b,
                                     payload_criacao):
        """O destino só recebe metadados — sem arquivo físico no
        SEU storage, o nó B não notifica a esteira."""
        payload_criacao["requer_anonimizacao_lgpd"] = True
        out = await org_a.criar(payload_criacao)
        await org_a.upload_documento(out.id, FakeUpload(DOC), org_a.orgao)
        env = (await org_a.enviar(out.id, org_a.orgao)).model_dump(mode="json")
        rec = await org_b.receber(env, org_b.orgao)
        assert rec.recebido
        # A emitiu (tem o arquivo); B não emitiu (não tem)
        assert len(await _outbox(org_a.repo._engine)) == 1
        assert await _outbox(org_b.repo._engine) == []

    async def test_upload_no_destino_emite_com_origem(
            self, org_a, org_b, payload_criacao):
        """Quando B sobe o arquivo para o SEU storage (ex.: após
        buscar no nó A), a esteira de B é notificada — com
        orgao_origem correta."""
        payload_criacao["requer_anonimizacao_lgpd"] = True
        out = await org_a.criar(payload_criacao)
        await org_a.upload_documento(out.id, FakeUpload(DOC), org_a.orgao)
        env = (await org_a.enviar(out.id, org_a.orgao)).model_dump(mode="json")
        await org_b.receber(env, org_b.orgao)
        await org_b.upload_documento(out.id, FakeUpload(DOC), org_b.orgao)
        linhas = await _outbox(org_b.repo._engine)
        assert len(linhas) == 1
        assert linhas[0]["payload"]["orgao_origem"] == "tjpa"


class TestHigiene:
    async def test_payload_nao_carrega_conteudo(
            self, org_a, payload_criacao):
        payload_criacao["requer_anonimizacao_lgpd"] = True
        out = await org_a.criar(payload_criacao)
        await org_a.upload_documento(out.id, FakeUpload(DOC), org_a.orgao)
        ev = (await _outbox(org_a.repo._engine))[0]
        assert set(ev["payload"]) == {"id_documento",
                                      "orgao_origem", "id_processo"}
        assert "EXCELENTISSIMO" not in str(ev["payload"])
