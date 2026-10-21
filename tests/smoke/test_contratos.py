"""Smoke: contratos aceitam o válido e recusam o inválido.
Barra: validação de forma ANTES de qualquer regra de negócio existir.
"""
import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.schemas.comum import StatusTramitacao
from app.schemas.tramitacao import (
    ConfirmacaoCreate, EnvelopeRecebimento, ErroOut, TramitacaoCreate,
    TramitacaoOut,
)


class TestCriacao:
    def test_payload_valido_aceita(self, payload_criacao):
        c = TramitacaoCreate(**payload_criacao)
        assert c.caso_cnj == payload_criacao["caso_cnj"]
        # T9: a criação carrega o hash DECLARADO — não os bytes
        assert c.hash_documento_sha256 == \
            payload_criacao["hash_documento_sha256"]
        assert not hasattr(c, "documento_b64")

    @pytest.mark.parametrize("cnj", [
        "123",                              # curto
        "5614226-41.2021.8.14.2679x",       # lixo no fim
        "56142264120218142679",             # sem pontuação
        "5614226-41.2021.7.14.2679",        # segmento J errado
    ])
    def test_cnj_invalido_recusa(self, payload_criacao, cnj):
        payload_criacao["caso_cnj"] = cnj
        with pytest.raises(ValidationError):
            TramitacaoCreate(**payload_criacao)

    def test_modo_invalido_recusa(self, payload_criacao):
        payload_criacao["modo"] = "ocultacao"   # modo inexistente
        with pytest.raises(ValidationError):
            TramitacaoCreate(**payload_criacao)

    @pytest.mark.parametrize("h", [
        "zz" * 32,                          # não-hex
        "0" * 63,                           # curto
        "0" * 65,                           # longo
    ])
    def test_hash_malformado_recusa(self, payload_criacao, h):
        payload_criacao["hash_documento_sha256"] = h
        with pytest.raises(ValidationError):
            TramitacaoCreate(**payload_criacao)

    def test_metadados_com_cpf_recusa(self, payload_criacao):
        payload_criacao["metadados"] = {
            "obs": "procurador do CPF 123.456.789-00"}
        with pytest.raises(ValidationError, match="identificadores"):
            TramitacaoCreate(**payload_criacao)

    def test_metadados_com_cpf_aninhado_recusa(self, payload_criacao):
        payload_criacao["metadados"] = {
            "partes": [{"doc": "123.456.789-00"}]}
        with pytest.raises(ValidationError, match="identificadores"):
            TramitacaoCreate(**payload_criacao)

    def test_metadados_acima_do_limite_recusa(self, payload_criacao):
        payload_criacao["metadados"] = {"obs": "x" * (8 * 1024 + 1)}
        with pytest.raises(ValidationError, match="limite"):
            TramitacaoCreate(**payload_criacao)

    def test_idempotency_curta_recusa(self, payload_criacao):
        payload_criacao["idempotency_key"] = "abc"
        with pytest.raises(ValidationError):
            TramitacaoCreate(**payload_criacao)


class TestSaida:
    async def test_saida_nao_carrega_documento(self, org_a,
                                               payload_criacao):
        out = await org_a.criar(payload_criacao)
        dados = out.model_dump(mode="json")
        assert "documento" not in dados
        assert "documento_b64" not in dados
        # e o conteúdo não vaza por nenhum campo
        assert b"EXCELENTISSIMO" not in \
            str(dados).encode()

    def test_saida_json_schema_valida(self):
        # TramitacaoOut vira a OpenAPI depois — o schema tem que gerar
        sch = TramitacaoOut.model_json_schema()
        assert sch["type"] == "object"
        assert "hash_documento_sha256" in sch["properties"]

    def test_erro_sanitizado(self):
        e = ErroOut(erro=ErroOut.Erro(codigo="422",
                                    mensagem="payload inválido"))
        assert e.erro.codigo == "422"
        # formato: objeto único com erro.codigo/erro.mensagem
        assert set(e.model_dump()["erro"]) == {"codigo", "mensagem"}


class TestConfirmacao:
    def _base(self):
        return dict(tramitacao_id=uuid.uuid4(),
                    hash_documento_recebido="a" * 64)

    def test_recusa_sem_motivo_recusa(self):
        with pytest.raises(ValidationError, match="motivo"):
            ConfirmacaoCreate(**self._base(), decisao="recusada")

    def test_recusa_com_motivo_aceita(self):
        c = ConfirmacaoCreate(**self._base(), decisao="recusada",
                              motivo="documento ilegível")
        assert c.decisao.value == "recusada"

    def test_hash_malformado_recusa(self):
        b = self._base(); b["hash_documento_recebido"] = "zz"
        with pytest.raises(ValidationError):
            ConfirmacaoCreate(**b, decisao="aceita")


class TestEnvelope:
    def test_envelope_valido(self, caso):
        e = EnvelopeRecebimento(
            tramitacao_id=uuid.uuid4(), origem="tjpa", caso_cnj=caso,
            modo="anonimizacao", hash_documento_sha256="b" * 64,
            enviado_em=datetime.now(timezone.utc))
        assert e.origem == "tjpa"
        # T9: o envelope é só metadados — nenhum campo de bytes
        assert not hasattr(e, "documento_b64")

    def test_envelope_imutavel(self, caso):
        e = EnvelopeRecebimento(
            tramitacao_id=uuid.uuid4(), origem="tjpa", caso_cnj=caso,
            modo="anonimizacao", hash_documento_sha256="b" * 64,
            enviado_em=datetime.now(timezone.utc))
        with pytest.raises(ValidationError):
            e.hash_documento_sha256 = "c" * 64   # frozen=True


def test_status_terminal_nao_transita():
    for s in (StatusTramitacao.CONFIRMADA, StatusTramitacao.RECUSADA,
              StatusTramitacao.CANCELADA):
        from app.schemas.comum import TRANSICOES
        assert TRANSICOES[s] == set()
