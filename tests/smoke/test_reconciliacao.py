"""Reconciliação do handshake — item 1 da análise arquitetural
(docs/analise-arquitetural.md §5, risco 4).

Mecanismo implementado (proposta aprovada):
  * `NoTramitacao.reenviar(tid, org)` — só de EM_TRANSITO, só após
    `ttl_reenvio_s` desde a última transição; reemite o envelope
    pela aresta EM_TRANSITO->CRIADA->EM_TRANSITO numa única tx;
  * `receber` idempotente: tid conhecido => eco com o status
    atual (sem merge, sem trilha nova); hash divergente => 409;
    chamador que não participa do caso => 404 opaco.

Estrutura:
- TestEnvelopePerdido: `defeito_conhecido_` — os 4 testes de
  caracterização do defeito, com asserções INVERTIDAS na
  correção (o que era porta fechada agora tem saída). O prefixo
  fica dentro do nome `test_*` para a coleta do pytest continuar
  exercendo as asserções.
- TestPropostaReenvio: a especificação que estava vermelha —
  agora é a suíte de contrato do mecanismo.
"""
from datetime import datetime, timezone

import pytest

from app.schemas.comum import TRANSICOES, StatusTramitacao
from app.schemas.tramitacao import ConfirmacaoOut
from app.service import ErroFluxo, ErroNaoEncontrado
from tests.smoke.conftest import DOC
from tests.smoke.dbutil import FakeUpload


async def _ate_em_transito(org_a, payload):
    """Cria, sobe o arquivo e envia — devolve (out, envelope).
    O envelope é ENTÃO 'perdido': quem chama decide não entregar."""
    out = await org_a.criar(payload)
    await org_a.upload_documento(out.id, FakeUpload(DOC), org_a.orgao)
    env = await org_a.enviar(out.id, org_a.orgao)
    return out, env


class TestEnvelopePerdido:
    """defeito_conhecido — análise arquitetural §5, risco 4:
    envelope perdido deixava A em EM_TRANSITO para sempre.
    Asserções invertidas na correção: cada teste prova que a
    saída agora existe (ou que a invariante correta se manteve)."""

    async def test_defeito_conhecido_origem_tem_saida_via_reenvio(
            self, org_a, payload_criacao):
        """Antes: origem presa em EM_TRANSITO indefinidamente.
        Invertido: reenviar (após TTL) reemite o envelope e a
        trilha registra o evento — sem mudança de fase."""
        out, env1 = await _ate_em_transito(org_a, payload_criacao)
        org_a.ttl_reenvio_s = 0
        env2 = await org_a.reenviar(out.id, org_a.orgao)
        assert env2.tramitacao_id == env1.tramitacao_id
        assert env2.hash_documento_sha256 == \
            env1.hash_documento_sha256
        assert (await org_a.obter(out.id)).status == \
            StatusTramitacao.EM_TRANSITO
        eventos = [t["evento"] for t in await org_a.repo.trilha(out.id)]
        assert f"reenvio:{out.id}" in eventos

    async def test_defeito_conhecido_enviar_segue_ilegal_reenvio_e_dedicado(
            self, org_a, payload_criacao):
        """Antes: re-enviar pela rota normal falhava e era a única
        tentativa possível. Invertido: `enviar` SEGUE ilegal
        (invariante preservada — EM_TRANSITO->EM_TRANSITO não é
        aresta) e a saída é o método dedicado."""
        out, _env = await _ate_em_transito(org_a, payload_criacao)
        with pytest.raises(ErroFluxo, match="transição ilegal"):
            await org_a.enviar(out.id, org_a.orgao)
        org_a.ttl_reenvio_s = 0
        env2 = await org_a.reenviar(out.id, org_a.orgao)
        assert env2.tramitacao_id == out.id

    async def test_defeito_conhecido_aresta_morta_agora_viva(
            self, org_a, payload_criacao):
        """Antes: EM_TRANSITO->CRIADA existia no mapa sem código
        que a disparasse, e não havia cancelar nem reenviar.
        Invertido: reenviar existe e usa a aresta; cancelar segue
        inexistente (fora do mecanismo mínimo — registrado)."""
        out, _env = await _ate_em_transito(org_a, payload_criacao)
        assert hasattr(org_a, "reenviar")
        assert not hasattr(org_a, "cancelar")    # fora do mínimo
        assert (StatusTramitacao.CRIADA
                in TRANSICOES[StatusTramitacao.EM_TRANSITO])
        org_a.ttl_reenvio_s = 0
        await org_a.reenviar(out.id, org_a.orgao)
        eventos = [t["evento"] for t in await org_a.repo.trilha(out.id)]
        assert f"reenvio:{out.id}" in eventos

    async def test_defeito_conhecido_origem_nao_forca_ack_mas_tem_reenvio(
            self, org_a, payload_criacao):
        """Antes: origem presa sem saída. Invertido: a regra de
        papel SEGUE — a origem não aplica ack sozinha (404 é
        invariante de autorização, não defeito) — e a saída
        legítima é o reenvio."""
        out, _env = await _ate_em_transito(org_a, payload_criacao)
        conf = ConfirmacaoOut(
            tramitacao_id=out.id, status="confirmada",
            confirmado_em=datetime.now(timezone.utc),
            hash_cadeia="0" * 64)
        with pytest.raises(ErroNaoEncontrado):
            await org_a.aplicar_confirmacao(out.id, conf, org_a.orgao)
        org_a.ttl_reenvio_s = 0
        await org_a.reenviar(out.id, org_a.orgao)
        assert (await org_a.obter(out.id)).status == \
            StatusTramitacao.EM_TRANSITO


class TestPropostaReenvio:
    """Contrato do mecanismo mínimo — estes testes nasceram
    vermelhos na especificação e passam com a implementação."""

    async def test_reenvio_apos_ttl_devolve_envelope_identico(
            self, org_a, payload_criacao):
        out, env1 = await _ate_em_transito(org_a, payload_criacao)
        org_a.ttl_reenvio_s = 0
        env2 = await org_a.reenviar(out.id, org_a.orgao)
        assert env2.tramitacao_id == env1.tramitacao_id
        assert env2.origem == env1.origem
        assert env2.hash_documento_sha256 == \
            env1.hash_documento_sha256
        # o estado final continua EM_TRANSITO — reenvio não é
        # mudança de fase, é reemissão de mensagem
        assert (await org_a.obter(out.id)).status == \
            StatusTramitacao.EM_TRANSITO

    async def test_reenvio_antes_do_ttl_e_recusado(
            self, org_a, payload_criacao):
        out, _env = await _ate_em_transito(org_a, payload_criacao)
        org_a.ttl_reenvio_s = 3600       # acabou de transitar
        with pytest.raises(ErroFluxo):
            await org_a.reenviar(out.id, org_a.orgao)

    async def test_reenvio_exige_estado_em_transito(
            self, org_a, payload_criacao):
        out = await org_a.criar(payload_criacao)   # ainda CRIADA
        org_a.ttl_reenvio_s = 0
        with pytest.raises(ErroFluxo):
            await org_a.reenviar(out.id, org_a.orgao)

    async def test_reenvio_exige_papel_origem(
            self, org_a, payload_criacao):
        """Destino é participante mas não reemite envelope —
        mesmo 404 opaco de sempre."""
        out, _env = await _ate_em_transito(org_a, payload_criacao)
        org_a.ttl_reenvio_s = 0
        with pytest.raises(ErroNaoEncontrado):
            await org_a.reenviar(out.id, "mpf.pa")

    async def test_envelope_duplicado_nao_regride_confirmacao(
            self, org_a, org_b, payload_criacao):
        """Lado B: canal at-least-once pode reentregar o envelope
        depois da confirmação. O eco idempotente não regride
        CONFIRMADA -> RECEBIDA (era o vermelho da especificação)."""
        out, env = await _ate_em_transito(org_a, payload_criacao)
        env_d = env.model_dump(mode="json")
        await org_b.receber(env_d, org_b.orgao)
        await org_b.confirmar(dict(
            tramitacao_id=out.id, decisao="aceita",
            hash_documento_recebido=(
                await org_b.obter(out.id)).hash_documento_sha256),
            org_b.orgao)
        assert (await org_b.obter(out.id)).status == \
            StatusTramitacao.CONFIRMADA
        trilha_antes = await org_b.repo.trilha(out.id)
        # reentrega do MESMO envelope (duplicata do canal)
        rec2 = await org_b.receber(env_d, org_b.orgao)
        assert rec2.recebido is True
        assert (await org_b.obter(out.id)).status == \
            StatusTramitacao.CONFIRMADA
        # e o eco não escreve linha nova na trilha
        assert len(await org_b.repo.trilha(out.id)) == \
            len(trilha_antes)


class TestEcoRecebimento:
    """O eco idempotente de `receber`: conteúdo mínimo, oráculo
    fechado e trilha intacta."""

    async def _duplicata(self, org_a, org_b, payload):
        out, env = await _ate_em_transito(org_a, payload)
        env_d = env.model_dump(mode="json")
        await org_b.receber(env_d, org_b.orgao)
        return out, env_d

    async def test_eco_expoe_status_e_omite_hash_cadeia(
            self, org_a, org_b, payload_criacao):
        _out, env_d = await self._duplicata(org_a, org_b,
                                            payload_criacao)
        eco = await org_b.receber(env_d, org_b.orgao)
        assert eco.recebido is True
        assert eco.status == StatusTramitacao.RECEBIDA
        assert eco.hash_cadeia is None
        # recebido_em do eco é o instante do PRIMEIRO ingresso
        rec = await org_b.obter(_out.id)
        assert eco.recebido_em == rec.criado_em

    async def test_eco_nao_duplica_trilha(
            self, org_a, org_b, payload_criacao):
        out, env_d = await self._duplicata(org_a, org_b,
                                           payload_criacao)
        antes = await org_b.repo.trilha(out.id)
        await org_b.receber(env_d, org_b.orgao)
        depois = await org_b.repo.trilha(out.id)
        assert len(antes) == len(depois)

    async def test_terceiro_nao_obtem_eco(
            self, org_a, org_b, payload_criacao):
        """Um órgão fora do caso com um envelope capturado não
        descobre nem existência nem status — 404 opaco."""
        _out, env_d = await self._duplicata(org_a, org_b,
                                            payload_criacao)
        with pytest.raises(ErroNaoEncontrado):
            await org_b.receber(env_d, "tre-pa")

    async def test_hash_divergente_em_tid_conhecido_e_conflito(
            self, org_a, org_b, payload_criacao):
        """Participante com envelope adulterado para tid real:
        divergência de hash => 409. A checagem de participação
        vem antes — o 409 nunca é alcançável por terceiros."""
        _out, env_d = await self._duplicata(org_a, org_b,
                                            payload_criacao)
        env_mau = dict(env_d, hash_documento_sha256="f" * 64)
        with pytest.raises(ErroFluxo, match="diverge"):
            await org_b.receber(env_mau, "tjpa")
