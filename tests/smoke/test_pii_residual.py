"""Gate de PII residual (app/pii_residual.py) — casos
sintéticos escritos à mão, sem trechos do corpus de avaliação.

Cobre: positivo por tipo, negativo de preservados (CNJ, valor
monetário, cargo, órgão, cidade, servidor público) e o fluxo
ponta a ponta do worker (residual -> falha_anonimizacao, nada
no bucket anonimizado, nenhum doc_anonimizado)."""
import io
import uuid

import pytest

from app.pii_residual import contar_residuos, residuo
from app.storage import ArmazenamentoMemoria
from app.worker import StubMotorIA, processar_evento

TAG = "[ANONIMIZADO_LGPD]"
CASO = "9999999-99.2099.9.99.9999"


def _res(texto):
    return {k: v for k, v in contar_residuos(texto).items() if v}


class TestFormatos:
    def test_cpf_pontuado(self):
        assert _res(f"CPF {TAG}, mas sobrou 111.222.333-44."
                    )["cpf"] == 1

    def test_cpf_sem_pontuacao(self):
        assert _res("inscrito sob 12345678901 no cadastro."
                    )["cpf"] == 1

    def test_rg_com_digito_verificador(self):
        assert _res("portador do RG 12.345.678-9.")["rg"] == 1

    def test_rg_x(self):
        assert _res("RG SSP 12.345.678-X.")["rg"] == 1

    def test_rg_sem_dv_so_com_rotulo(self):
        # sem dígito verificador: só o rótulo o denuncia
        assert _res("RG PA 12.345.678.")["rg"] == 1

    def test_email(self):
        assert _res("contato maria.silva@exemplo.org.br."
                    )["email"] == 1

    def test_telefone_ddd_parenteses(self):
        assert _res("fone (91) 91234-5678.")["telefone"] == 1

    def test_telefone_sem_ddd(self):
        assert _res("ligar 3222-4455.")["telefone"] == 1

    def test_telefone_celular_sem_hifen_no_ddd(self):
        assert _res("celular 91 98765-4321.")["telefone"] == 1

    def test_rg_e_formato_nao_contam_dobrado(self):
        # rótulo + formato sobre o MESMO trecho = 1 ocorrência
        assert _res("RG SSP-PA 12.345.678-9.")["rg"] == 1


class TestNomeContexto:
    def test_intimado(self):
        assert _res("Foi intimado Carlos Pereira Lopes na data."
                    )["nome_contexto"] == 1

    def test_intimada(self):
        assert _res("intimada Maria Souza Lima.")["nome_contexto"] == 1

    def test_em_face_de(self):
        assert _res("ajuizada em face de Joao Alves Braga."
                    )["nome_contexto"] == 1

    def test_servidor_caps(self):
        assert _res("servidor CARLOS ALBERTO MOTA, matricula 10."
                    )["nome_contexto"] == 1

    def test_tag_apos_rotulo_nao_dispara(self):
        # nome já removido: a tag não é um nome residual
        assert "nome_contexto" not in _res(
            f"intimado {TAG}, residente na comarca.")

    def test_orgao_apos_em_face_de_nao_dispara(self):
        # réu institucional em caps não é pessoa física
        assert "nome_contexto" not in _res(
            "ajuizada em face de BANCO ESTADUAL S.A.")
        assert "nome_contexto" not in _res(
            "em face de MINISTERIO PUBLICO FEDERAL")


class TestNegativos:
    """Preservados NÃO podem disparar — FP aqui bloquearia um
    documento corretamente anonimizado."""

    def test_cnj_limpo(self):
        assert _res(f"Processo {CASO}. Autos conclusos.") == {}

    def test_valor_monetario_limpo(self):
        assert _res("Valor da causa: R$ 1.234.567,89.") == {}
        assert _res("condenação de R$ 12.500,00.") == {}

    def test_cargo_limpo(self):
        assert _res("MM. Juiz de Direito titular da vara.") == {}
        assert _res("Excelentíssimo Senhor Doutor Juiz.") == {}

    def test_orgao_e_cidade_limpos(self):
        assert _res("TRIBUNAL DE JUSTICA DO ESTADO, comarca de "
                    "Belem do Para, Secretaria Judiciaria.") == {}

    def test_servidor_publico_generico_nao_dispara(self):
        assert "nome_contexto" not in _res(
            "servidor público lotado na secretaria")

    def test_data_iso_nao_e_telefone(self):
        assert "telefone" not in _res("em 2024-01-15 foi citado")

    def test_saida_totalmente_anonimizada(self):
        assert _res(
            f"Outorgante: {TAG}, CPF {TAG}, email {TAG}, "
            f"fone {TAG}. Processo {CASO}. "
            f"Valor: R$ 10.000,00.") == {}


class TestGateWorker:
    """Ponta a ponta: residual na saída -> falha_anonimizacao,
    nada no bucket, nenhum doc_anonimizado."""

    async def test_cpf_residual_vira_falha(self, org_a,
                                           payload_criacao):
        out = await org_a.criar(payload_criacao)
        doc = str(out.id)
        st_dest = ArmazenamentoMemoria(
            "tjpa", nome_bucket="tjpa-docs-anonimizados")
        # motor passthrough: a saída 'anonimizada' ainda tem CPF
        bruto = (f"Requerente {TAG}, CPF 123.456.789-09, "
                 f"processo {CASO}.").encode()
        await org_a.storage.guardar(doc, io.BytesIO(bruto))
        await processar_evento(
            {"id_documento": doc, "orgao_origem": "tjpa",
             "id_processo": CASO}, org_a.storage, st_dest,
            StubMotorIA(atraso=0), repo=org_a.repo)
        assert not await st_dest.existe(doc)          # não grava
        evs = [t["evento"] for t in await org_a.repo.trilha(
            out.id)]
        assert f"falha_anonimizacao:{doc}:residual_pii" in evs
        assert not any(e.startswith("doc_anonimizado:")
                       for e in evs)

    async def test_nome_contexto_residual_vira_falha(
            self, org_a, payload_criacao):
        out = await org_a.criar(payload_criacao)
        doc = str(out.id)
        st_dest = ArmazenamentoMemoria(
            "tjpa", nome_bucket="tjpa-docs-anonimizados")
        bruto = (f"CPF {TAG}. Foi intimado Pedro Costa Neto "
                 f"nesta data.").encode()
        await org_a.storage.guardar(doc, io.BytesIO(bruto))
        await processar_evento(
            {"id_documento": doc, "orgao_origem": "tjpa",
             "id_processo": CASO}, org_a.storage, st_dest,
            StubMotorIA(atraso=0), repo=org_a.repo)
        assert not await st_dest.existe(doc)
        evs = [t["evento"] for t in await org_a.repo.trilha(
            out.id)]
        assert f"falha_anonimizacao:{doc}:residual_pii" in evs

    async def test_sem_residual_fluxo_normal(self, org_a,
                                             payload_criacao):
        out = await org_a.criar(payload_criacao)
        doc = str(out.id)
        st_dest = ArmazenamentoMemoria(
            "tjpa", nome_bucket="tjpa-docs-anonimizados")
        bruto = (f"Requerente {TAG}, processo {CASO}, "
                 f"valor R$ 10.000,00.").encode()
        await org_a.storage.guardar(doc, io.BytesIO(bruto))
        await processar_evento(
            {"id_documento": doc, "orgao_origem": "tjpa",
             "id_processo": CASO}, org_a.storage, st_dest,
            StubMotorIA(atraso=0), repo=org_a.repo)
        assert await st_dest.existe(doc)              # grava
        evs = [t["evento"] for t in await org_a.repo.trilha(
            out.id)]
        assert f"doc_anonimizado:{doc}" in evs

    async def test_log_so_contagens_sem_valores(self, caplog):
        import logging
        from app.worker import FabricaStorages
        fab = FabricaStorages(
            lambda orgao, bucket: ArmazenamentoMemoria(
                orgao, nome_bucket=bucket))
        org, dest = await fab.par("tjpa")
        doc = str(uuid.uuid4())
        await org.guardar(doc, io.BytesIO(
            b"CPF 123.456.789-09 no corpo."))
        with caplog.at_level(logging.WARNING,
                             "tramitacao.worker"):
            await processar_evento(
                {"id_documento": doc, "orgao_origem": "tjpa",
                 "id_processo": CASO}, org, dest,
                StubMotorIA(atraso=0))
        msg = " ".join(r.getMessage() for r in caplog.records)
        assert "residual_pii" in msg and "cpf" in msg
        assert "123.456.789-09" not in msg    # nunca o valor
