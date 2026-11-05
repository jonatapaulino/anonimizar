"""Smoke E2E: fluxo Órgão A cria -> upload -> Órgão B recebe ->
B confirma, sobre o serviço real (sqlite em memória + storage
em memória por nó — T9).

Cobre: caminho feliz, gate de arquivo físico no envio, detecção
de adulteração na fronteira nova (upload/confirmação),
idempotência, máquina de estados e recusa com motivo.
"""
import pytest

from app.schemas.comum import StatusTramitacao
from app.service import ErroFluxo
from tests.smoke.dbutil import FakeUpload

DOC = b"EXCELENTISSIMO SENHOR DOUTOR JUIZ - processo de teste."


async def fluxo_completo(org_a, org_b, payload):
    """Helper: executa o caminho feliz e devolve os artefatos.
    T9: upload físico entre criar e enviar — o envelope é só
    metadados. B arquiva os bytes recebidos ANTES de confirmar —
    a confirmação recomputa o SHA-256 do que está no storage de
    B; declarar sem os bytes não fecha o caso."""
    out_a = await org_a.criar(payload)
    await org_a.upload_documento(out_a.id, FakeUpload(DOC), org_a.orgao)
    env = (await org_a.enviar(out_a.id, org_a.orgao)).model_dump(mode="json")
    rec = await org_b.receber(env, "tjpa")
    await org_b.upload_documento(out_a.id, FakeUpload(DOC), org_b.orgao)
    conf = await org_b.confirmar(dict(
        tramitacao_id=out_a.id, decisao="aceita",
        hash_documento_recebido=(
            await org_b.obter(out_a.id)).hash_documento_sha256), org_b.orgao)
    await org_a.aplicar_confirmacao(out_a.id, conf, "mpf.pa")
    return out_a, env, rec, conf


class TestCaminhoFeliz:
    async def test_fluxo_completo(self, org_a, org_b, payload_criacao):
        out, env, rec, conf = await fluxo_completo(
            org_a, org_b, payload_criacao)

        assert (await org_a.obter(out.id)).status == \
            StatusTramitacao.CONFIRMADA
        assert rec.recebido is True
        assert conf.status == StatusTramitacao.CONFIRMADA
        # hash atravessa o trânsito intacto (âncora do binário)
        assert (env["hash_documento_sha256"]
                == out.hash_documento_sha256)
        # envelope NÃO carrega bytes (T9)
        assert "documento_b64" not in env
        # a trilha evoluiu: cadeia final != cadeia de criação
        assert conf.hash_cadeia != out.hash_cadeia

    async def test_estados_intermediarios(self, org_a, org_b,
                                          payload_criacao):
        out = await org_a.criar(payload_criacao)
        assert out.status == StatusTramitacao.CRIADA
        await org_a.upload_documento(out.id, FakeUpload(DOC), org_a.orgao)
        env = (await org_a.enviar(out.id, org_a.orgao)).model_dump(mode="json")
        assert (await org_a.obter(out.id)).status == \
            StatusTramitacao.EM_TRANSITO
        rec = await org_b.receber(env, "tjpa")
        assert rec.recebido
        assert (await org_b.obter(out.id)).status == \
            StatusTramitacao.RECEBIDA


class TestGateFisico:
    """T9: não se tramita o que não existe fisicamente."""

    async def test_enviar_sem_upload_falha(self, org_a,
                                           payload_criacao):
        out = await org_a.criar(payload_criacao)
        with pytest.raises(ErroFluxo, match="não está no storage"):
            await org_a.enviar(out.id, org_a.orgao)
        # e a tramitação NÃO transitou — segue CRIADA
        assert (await org_a.obter(out.id)).status == \
            StatusTramitacao.CRIADA


class TestIntegridade:
    """Defesa em profundidade da integridade, nas três camadas:
      1) assinatura Ed25519 — envelope adulterado em trânsito
         não chega nem a existir como registro;
      2) digest do upload — bytes divergentes do hash declarado
         não entram no storage;
      3) recomputação na confirmação — sem bytes verificados no
         storage de B, o caso não fecha."""

    async def test_hash_adulterado_no_envelope(
            self, org_a, org_b, payload_criacao):
        """MITM no envelope assinado: trocar o hash invalida a
        assinatura — a adulteração explode no INGRESSO, antes de
        qualquer registro. Sem a camada de assinatura, a verificação
        de bytes pegaria depois (teste seguinte)."""
        out = await org_a.criar(payload_criacao)
        await org_a.upload_documento(out.id, FakeUpload(DOC), org_a.orgao)
        env = (await org_a.enviar(out.id, org_a.orgao)).model_dump(mode="json")
        env["hash_documento_sha256"] = "0" * 64   # MITM no envelope
        with pytest.raises(ErroFluxo, match="assinatura"):
            await org_b.receber(env, "tjpa")

    async def test_doc_real_nao_casa_com_hash_adulterado(
            self, org_a, org_b, payload_criacao):
        """Camada de bytes: envelope íntegro, mas o documento que
        B recebeu não casa com o hash declarado — o upload de B
        rejeita e a confirmação não tem base para fechar."""
        out = await org_a.criar(payload_criacao)
        await org_a.upload_documento(out.id, FakeUpload(DOC), org_a.orgao)
        env = (await org_a.enviar(out.id, org_a.orgao)).model_dump(mode="json")
        await org_b.receber(env, "tjpa")
        # bytes errados não entram: digest diverge do declarado
        with pytest.raises(ErroFluxo, match="difere"):
            await org_b.upload_documento(
                out.id, FakeUpload(b"documento adulterado"),
                org_b.orgao)
        # e sem os bytes verificados no storage de B, declarar
        # o hash certo não confirma nada
        with pytest.raises(ErroFluxo, match="não está no storage"):
            await org_b.confirmar(dict(
                tramitacao_id=out.id, decisao="aceita",
                hash_documento_recebido=out.hash_documento_sha256),
                org_b.orgao)


class TestIdempotencia:
    async def test_mesma_chave_retorna_mesma_tramitacao(
            self, org_a, payload_criacao):
        a = await org_a.criar(payload_criacao)
        b = await org_a.criar(payload_criacao)      # re-POST idêntico
        assert a.id == b.id
        assert (await org_a.obter(a.id)).id == a.id

    async def test_chave_diferente_cria_outra(self, org_a,
                                              payload_criacao):
        a = await org_a.criar(payload_criacao)
        payload_criacao["idempotency_key"] = "tjpa-2026-0002-wxyz"
        b = await org_a.criar(payload_criacao)
        assert a.id != b.id


class TestMaquinaDeEstados:
    async def test_confirmar_sem_receber_falha(self, org_a, org_b,
                                               payload_criacao):
        out = await org_a.criar(payload_criacao)
        await org_a.upload_documento(out.id, FakeUpload(DOC), org_a.orgao)
        await org_a.enviar(out.id, org_a.orgao)
        # B nunca recebeu — confirmar direto deve falhar
        with pytest.raises(ErroFluxo, match="desconhecida"):
            await org_b.confirmar(dict(
                tramitacao_id=out.id, decisao="aceita",
                hash_documento_recebido=out.hash_documento_sha256), org_b.orgao)

    async def test_confirmar_duas_vezes_falha(self, org_a, org_b,
                                              payload_criacao):
        """Re-confirmação de caso fechado: mesmo com o hash
        correto e os bytes no storage, CONFIRMADA é terminal —
        o mapa de transições é a última linha de defesa."""
        out, env, rec, conf = await fluxo_completo(
            org_a, org_b, payload_criacao)
        with pytest.raises(ErroFluxo, match="transição ilegal"):
            await org_b.confirmar(dict(
                tramitacao_id=out.id, decisao="aceita",
                hash_documento_recebido=out.hash_documento_sha256),
                org_b.orgao)

    async def test_terminal_nao_transita(self, org_a, org_b,
                                         payload_criacao):
        out, env, rec, conf = await fluxo_completo(
            org_a, org_b, payload_criacao)
        with pytest.raises(ErroFluxo, match="transição ilegal"):
            await org_a.enviar(out.id, org_a.orgao)   # CONFIRMADA é terminal


class TestRecusa:
    async def test_recusa_com_motivo_fecha_fluxo(self, org_a, org_b,
                                               payload_criacao):
        out = await org_a.criar(payload_criacao)
        await org_a.upload_documento(out.id, FakeUpload(DOC), org_a.orgao)
        env = (await org_a.enviar(out.id, org_a.orgao)).model_dump(mode="json")
        await org_b.receber(env, "tjpa")
        await org_b.upload_documento(out.id, FakeUpload(DOC), org_b.orgao)
        conf = await org_b.confirmar(dict(
            tramitacao_id=out.id, decisao="recusada",
            motivo="fora da competência",
            hash_documento_recebido=(
                await org_b.obter(out.id)).hash_documento_sha256), org_b.orgao)
        await org_a.aplicar_confirmacao(out.id, conf, "mpf.pa")
        assert (await org_a.obter(out.id)).status == \
            StatusTramitacao.RECUSADA

    async def test_hash_divergente_na_confirmacao_falha(
            self, org_a, org_b, payload_criacao):
        out = await org_a.criar(payload_criacao)
        await org_a.upload_documento(out.id, FakeUpload(DOC), org_a.orgao)
        env = (await org_a.enviar(out.id, org_a.orgao)).model_dump(mode="json")
        await org_b.receber(env, "tjpa")
        with pytest.raises(ErroFluxo, match="difere do recebido"):
            await org_b.confirmar(dict(
                tramitacao_id=out.id, decisao="aceita",
                hash_documento_recebido="f" * 64), org_b.orgao)


class TestNaoPersistencia:
    """T9: a invariante endureceu — o banco não tem NENHUMA
    tabela de bytes; o arquivo vive só no storage do órgão."""

    async def test_banco_nao_tem_tabela_de_bytes(
            self, org_a, org_b, payload_criacao):
        from sqlalchemy import inspect, text
        out, env, rec, conf = await fluxo_completo(
            org_a, org_b, payload_criacao)
        async with org_a.repo._engine.connect() as c:
            tabelas = set(await c.run_sync(
                lambda conn: inspect(conn).get_table_names()))
        assert "documentos_transito" not in tabelas
        # e o arquivo continua existindo — no storage, seu lugar
        assert await org_a.storage.existe(str(out.id))
