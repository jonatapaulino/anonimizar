"""Worker da esteira de IA (T10) — consumidor ia.anonimizacao.

Dois níveis:
- pipeline puro com storage em memória (TDD rápido, sem broker);
- integração real: mensagem injetada no RabbitMQ + MinIO real —
  só quando TEST_AMQP_URL **e** MINIO_URL estão definidas.
  (TEST_AMQP_URL, não RABBITMQ_URL: essa variável liga o RELAY
  dos apps de teste e criaria corrida nos asserts de outbox.)
"""
import hashlib
import io
import os
import uuid

import pytest
from sqlalchemy import text

from app.service import NoTramitacao
from app.storage import ArmazenamentoMemoria
from app.worker import (FabricaStorages, StubMotorIA,
                        processar_evento, registrar_falha,
                        um_ciclo, um_ciclo_dlq)
from tests.smoke.dbutil import mk_repo

DOC = b"%PDF-1.4 EXCELENTISSIMO SENHOR DOUTOR JUIZ - doc de teste."
CASO = "5614226-41.2021.8.14.2679"


def _fabrica_memoria():
    return FabricaStorages(
        lambda orgao, bucket: ArmazenamentoMemoria(
            orgao, nome_bucket=bucket))


class MotorRapido(StubMotorIA):
    def __init__(self):
        super().__init__(atraso=0)


class MotorQueFalha:
    def __init__(self):
        self.chamados = 0

    async def anonimizar(self, conteudo):
        self.chamados += 1
        raise RuntimeError("modelo fora do ar (simulado)")


class TestPipeline:
    async def test_processar_ok_grava_no_bucket_destino(self):
        fab = _fabrica_memoria()
        org, dest = await fab.par("tjpa")
        doc = str(uuid.uuid4())
        await org.guardar(doc, io.BytesIO(DOC))   # seed bruto
        motor = MotorRapido()
        await processar_evento(
            {"id_documento": doc, "orgao_origem": "tjpa",
             "id_processo": CASO}, org, dest, motor)
        assert motor.chamados == [len(DOC)]
        # resultado no bucket *-docs-anonimizados, mesma chave
        got = b"".join([c async for c in dest.abrir(doc)])
        assert got == DOC

    async def test_processar_duas_vezes_e_idempotente(self):
        fab = _fabrica_memoria()
        org, dest = await fab.par("tjpa")
        doc = str(uuid.uuid4())
        await org.guardar(doc, io.BytesIO(DOC))
        motor = MotorRapido()
        ev = {"id_documento": doc, "orgao_origem": "tjpa",
              "id_processo": CASO}
        await processar_evento(ev, org, dest, motor)
        await processar_evento(ev, org, dest, motor)   # re-entrega
        assert motor.chamados == [len(DOC), len(DOC)]
        got = b"".join([c async for c in dest.abrir(doc)])
        assert got == DOC            # mesmo objeto, sobrescrito

    async def test_falha_do_motor_nao_grava_destino(self):
        fab = _fabrica_memoria()
        org, dest = await fab.par("tjpa")
        doc = str(uuid.uuid4())
        await org.guardar(doc, io.BytesIO(DOC))
        with pytest.raises(RuntimeError, match="fora do ar"):
            await processar_evento(
                {"id_documento": doc, "orgao_origem": "tjpa",
                 "id_processo": CASO}, org, dest, MotorQueFalha())
        assert not await dest.existe(doc)

    async def test_download_inexistente_falha(self):
        fab = _fabrica_memoria()
        org, dest = await fab.par("tjpa")
        with pytest.raises(KeyError):
            await processar_evento(
                {"id_documento": str(uuid.uuid4()),
                 "orgao_origem": "tjpa", "id_processo": CASO},
                org, dest, MotorRapido())


class TestFeedbackTrilha:
    """T11: após o upload do anonimizado, o worker grava
    `doc_anonimizado:{id}` na trilha (hash-chain) do nó."""
    async def test_trilha_registra_anonimizacao(
            self, org_a, payload_criacao):
        # origem = o storage do PRÓPRIO nó (onde o upload gravou)
        st_org = org_a.storage
        st_dest = ArmazenamentoMemoria(
            "tjpa", nome_bucket="tjpa-docs-anonimizados")
        out = await org_a.criar(payload_criacao)
        from tests.smoke.conftest import DOC as DOC_CRIADO
        await org_a.upload_documento(out.id, _up(DOC_CRIADO),
                                     org_a.orgao)
        motor = MotorRapido()
        await processar_evento(
            {"id_documento": str(out.id), "orgao_origem": "tjpa",
             "id_processo": payload_criacao["caso_cnj"]},
            st_org, st_dest, motor, repo=org_a.repo)
        from sqlalchemy import select
        from app.models import Trilha
        async with org_a.repo._engine.connect() as c:
            eventos = list((await c.scalars(
                select(Trilha.evento)
                .where(Trilha.tramitacao_id == out.id)
                .order_by(Trilha.seq))).all())
        assert f"doc_anonimizado:{out.id}" in eventos
        # trilha completa do doc: criada -> arquivado -> anonimizado
        assert eventos == [f"criada:{out.id}",
                           f"doc_arquivado:{out.id}",
                           f"doc_anonimizado:{out.id}"]


def _up(b):
    from tests.smoke.dbutil import FakeUpload
    return FakeUpload(b)


class TestMetricas:
    """Item 3 — instrumentação (mede, não bloqueia): por evento,
    o pipeline conta entidades detectadas no bruto e residuais
    no anonimizado, por tipo. O registro é consultável."""
    DOC_PII = ("Outorgante: Jose Silva, CPF 123.456.789-09, "
               "email jose@exemplo.com, fone (91) 91234-5678. "
               "Processo 5614226-41.2021.8.14.2679.").encode()

    async def test_contagens_por_tipo_no_pipeline(self):
        from app import metricas
        from app.worker import DemoMotorIA
        fab = _fabrica_memoria()
        org, dest = await fab.par("tjpa")
        doc = str(uuid.uuid4())
        await org.guardar(doc, io.BytesIO(self.DOC_PII))
        await processar_evento(
            {"id_documento": doc, "orgao_origem": "tjpa",
             "id_processo": CASO}, org, dest, DemoMotorIA(atraso=0))
        m = metricas.ultimo(doc)
        assert m["detectadas"]["cpf"] == 1
        assert m["detectadas"]["email"] == 1
        assert m["detectadas"]["telefone"] == 1
        assert m["detectadas"]["nome"] == 1         # "Jose Silva"
        assert all(v == 0 for v in m["residuais"].values())
        # total == soma dos tipos (a tag não carrega tipo; a
        # soma por tipo é a única agregação confiável)
        soma = sum(v for k, v in m["substituidas"].items()
                   if k not in ("total", "tags_na_saida"))
        assert m["substituidas"]["total"] == soma == 4

    async def test_nome_e_endereco_por_rotulo(self):
        """Rótulos de petição viram tipos próprios na métrica.
        DemoMotorIA cobre 'nome' mas NÃO 'endereco' — a métrica
        deve mostrar o endereço como residual (vazamento real)."""
        from app import metricas
        from app.worker import DemoMotorIA
        fab = _fabrica_memoria()
        org, dest = await fab.par("tjpa")
        doc = str(uuid.uuid4())
        await org.guardar(doc, io.BytesIO(
            "Requerente: MARIA SOUZA, CPF 987.654.321-00.\n"
            "Endereço: Travessa B, 42 — Belém/PA.".encode()))
        await processar_evento(
            {"id_documento": doc, "orgao_origem": "tjpa",
             "id_processo": CASO}, org, dest, DemoMotorIA(atraso=0))
        m = metricas.ultimo(doc)
        assert m["detectadas"]["nome"] == 1
        assert m["detectadas"]["endereco"] == 1
        assert m["residuais"]["nome"] == 0          # coberto
        assert m["residuais"]["endereco"] == 1      # vazou!
        soma = sum(v for k, v in m["substituidas"].items()
                   if k not in ("total", "tags_na_saida"))
        assert m["substituidas"]["total"] == soma == 2

    async def test_motor_fraco_expoe_residual(self):
        """Motor que não toca nada: detectadas > 0, residuais
        iguais — é exatamente o que a métrica existe p/ mostrar."""
        from app import metricas
        fab = _fabrica_memoria()
        org, dest = await fab.par("tjpa")
        doc = str(uuid.uuid4())
        await org.guardar(doc, io.BytesIO(self.DOC_PII))
        await processar_evento(
            {"id_documento": doc, "orgao_origem": "tjpa",
             "id_processo": CASO}, org, dest, MotorRapido())
        m = metricas.ultimo(doc)
        assert m["detectadas"]["cpf"] == 1
        assert m["residuais"]["cpf"] == 1           # vazou!
        assert m["residuais"]["email"] == 1


# ---------- conjunto de avaliação do item 3 ----------
# (nome, conteudo, detectadas, residuais, substituidas_esperadas)
# tipos não listados = 0. xfail strict: ponto cego conhecido —
# melhoria no regex/NER faz o caso XPASS e quebra a suíte,
# forçando reavaliação da expectativa.
#
# ATENÇÃO — o que este corpus mede: o motor sob teste é o
# DemoMotorIA, um stub REGEX determinístico (CPF/e-mail/telefone
# + valor após rótulo de petição). Os números medem o recall do
# regex, NÃO o do LangChainMotorIA (LLM real). Conclusões sobre
# cobertura LGPD do motor de produção exigem rodar o corpus
# contra ele — é a próxima fronteira (N2 na divida-tecnica.md).
_CORPUS = [
    pytest.param(
        "Outorgante: Jose Silva, CPF 123.456.789-09.",
        {"cpf": 1, "nome": 1}, {},
        {"cpf": 1, "nome": 1, "total": 2},
        id="01_base_rotulo"),
    pytest.param(
        "REQUERENTE: MARIA APARECIDA SOUZA, RG 4455667-PA.",
        {"nome": 1}, {},
        {"nome": 1, "total": 1},
        id="02_nome_maiusculo"),
    pytest.param(
        "O CPF 12345678909 consta no pedido.",
        {"cpf": 1}, {},
        {"cpf": 1, "total": 1},
        marks=pytest.mark.xfail(
            strict=True,
            reason="ponto cego: regex de CPF exige pontuação"),
        id="03_cpf_sem_pontuacao"),
    pytest.param(
        "E-mail: JOSE.SILVA@EXEMPLO.COM.BR",
        {"email": 1}, {},
        {"email": 1, "total": 1},
        id="04_email_maiusculo"),
    pytest.param(
        "Contato: (91) 91234-5678",
        {"telefone": 1}, {},
        {"telefone": 1, "total": 1},
        id="05_fone_ddd_parenteses"),
    pytest.param(
        "Fone: 91 98123-4567",
        {"telefone": 1}, {},
        {"telefone": 1, "total": 1},
        id="06_fone_sem_parenteses"),
    pytest.param(
        "compareceu Jose Silva, outorgante.",
        {"nome": 1}, {},
        {"nome": 1, "total": 1},
        marks=pytest.mark.xfail(
            strict=True,
            reason="ponto cego: nome livre sem rótulo exige NER"),
        id="07_nome_sem_rotulo"),
    pytest.param(
        "CPF 123.456.789-09 e CPF 987.654.321-00.",
        {"cpf": 2}, {},
        {"cpf": 2, "total": 2},
        id="08_dois_cpfs"),
    pytest.param(
        "Processo CNJ 5614226-41.2021.8.14.2679. "
        "Valor da causa: R$ 50.000,00.",
        {}, {}, {"total": 0},
        id="09_sem_pii_cnj_nao_conta"),
    pytest.param(
        "Endereço: Rua X, 10 — Belém/PA.",
        {"endereco": 1}, {"endereco": 1},
        {"total": 0},
        id="10_endereco_rotulo_residual"),
    pytest.param(
        "mora na Rua X, 10, Belém.",
        {"endereco": 1}, {},
        {"endereco": 1, "total": 1},
        marks=pytest.mark.xfail(
            strict=True,
            reason="ponto cego: endereço livre sem rótulo"),
        id="11_endereco_sem_rotulo"),
    pytest.param(
        "Fone: (91) 991234567",
        {"telefone": 1}, {},
        {"telefone": 1, "total": 1},
        marks=pytest.mark.xfail(
            strict=True,
            reason="ponto cego: telefone sem hífen"),
        id="14_telefone_sem_hifen"),
]


class TestAvaliacaoCorpus:
    """Corpus sintético parametrizado — cada caso declara as
    contagens esperadas por tipo. xfail strict nos pontos cegos:
    melhoria de detecção quebra a suíte e obriga reavaliar."""

    @pytest.mark.parametrize(
        "texto,det,res,sub", _CORPUS)
    async def test_caso(self, texto, det, res, sub):
        from app import metricas
        from app.worker import DemoMotorIA
        fab = _fabrica_memoria()
        org, dest = await fab.par("tjpa")
        doc = str(uuid.uuid4())
        await org.guardar(doc, io.BytesIO(texto.encode()))
        await processar_evento(
            {"id_documento": doc, "orgao_origem": "tjpa",
             "id_processo": CASO}, org, dest, DemoMotorIA(atraso=0))
        m = metricas.ultimo(doc)
        for k, v in det.items():
            assert m["detectadas"][k] == v, \
                f"detectadas[{k}]"
        for k, v in res.items():
            assert m["residuais"][k] == v, f"residuais[{k}]"
        for k, v in sub.items():
            assert m["substituidas"][k] == v, \
                f"substituidas[{k}]"
        # nada fora do declarado: detectadas/residuais fora das
        # chaves esperadas devem ser zero
        for k, v in m["detectadas"].items():
            assert v == det.get(k, 0), f"detectadas[{k}] extra"
        for k, v in m["residuais"].items():
            assert v == res.get(k, 0), f"residuais[{k}] extra"

    async def test_12_pdf_real_mesma_extração(self):
        """Caso 12: PDF gerado pelo PRÓPRIO pdf_de_texto com o
        texto do caso 01 — a métrica deve ler via pypdf e a
        extração devolve o mesmo texto (round-trip)."""
        from app import metricas
        from app.motor_langchain import (extrair_texto,
                                         pdf_de_texto)
        bruto = pdf_de_texto(_CORPUS[0].values[0])
        assert extrair_texto(bruto).strip() == \
            _CORPUS[0].values[0]
        fab = _fabrica_memoria()
        org, dest = await fab.par("tjpa")
        doc = str(uuid.uuid4())
        await org.guardar(doc, io.BytesIO(bruto))
        from app.worker import DemoMotorIA
        await processar_evento(
            {"id_documento": doc, "orgao_origem": "tjpa",
             "id_processo": CASO}, org, dest, DemoMotorIA(atraso=0))
        m = metricas.ultimo(doc)
        assert m["detectadas"]["cpf"] == 1
        assert m["detectadas"]["nome"] == 1
        # DemoMotorIA faz decode utf-8/replace nos bytes do PDF
        # e CORROMPE a stream — a saída nem é lida pelo pypdf:
        # residuais=0 aqui é "não-lido", não "limpo"
        assert m["saida_legivel"] is False
        assert m["residuais"]["cpf"] == 0
        # e a saída ilegível NÃO foi gravada no bucket anonimizado
        assert not await dest.existe(doc)

    async def test_12b_saida_ilegivel_vira_falha(
            self, org_a, payload_criacao):
        """Gate de legibilidade: saida_legivel=False ->
        falha_anonimizacao:saida_ilegivel na trilha, NADA no
        bucket anonimizado, NENHUM doc_anonimizado — auditar
        PDF corrompido como sucesso seria registro falso."""
        from app.motor_langchain import pdf_de_texto
        from app.worker import DemoMotorIA
        out = await org_a.criar(payload_criacao)
        doc = str(out.id)
        st_dest = ArmazenamentoMemoria(
            "tjpa", nome_bucket="tjpa-docs-anonimizados")
        await org_a.storage.guardar(doc, io.BytesIO(pdf_de_texto(
            _CORPUS[0].values[0])))
        await processar_evento(
            {"id_documento": doc, "orgao_origem": "tjpa",
             "id_processo": CASO}, org_a.storage, st_dest,
            DemoMotorIA(atraso=0), repo=org_a.repo)
        assert not await st_dest.existe(doc)      # nada gravado
        evs = [t["evento"] for t in await org_a.repo.trilha(
            out.id)]
        assert f"falha_anonimizacao:{doc}:saida_ilegivel" in evs
        assert not any(e.startswith("doc_anonimizado:")
                       for e in evs)

    async def test_13_malformado_zeros_e_aviso(self, caplog):
        """Bytes ilegíveis: métrica zera tudo e deixa WARNING —
        instrumentação nunca derruba o pipeline."""
        import logging
        from app import metricas
        fab = _fabrica_memoria()
        org, dest = await fab.par("tjpa")
        doc = str(uuid.uuid4())
        await org.guardar(doc, io.BytesIO(
            b"\xff\xfe\x00\x01 binario \x80\x81"))
        with caplog.at_level(logging.WARNING,
                             "tramitacao.metricas"):
            await processar_evento(
                {"id_documento": doc, "orgao_origem": "tjpa",
                 "id_processo": CASO}, org, dest,
                MotorRapido())
        m = metricas.ultimo(doc)
        assert m["entrada_legivel"] is False
        assert all(v == 0 for v in m["detectadas"].values())
        assert all(v == 0 for v in m["residuais"].values())
        assert any(r.levelno == logging.WARNING and
                   "sem texto" in r.getMessage()
                   for r in caplog.records)


class TestFalhaDLQ:
    """T12: mensagem morta na DLQ -> `falha_anonimizacao:{id}`
    encadeado na trilha — incidente auditável no nó."""
    async def test_registrar_falha_grava_trilha(
            self, org_a, payload_criacao):
        out = await org_a.criar(payload_criacao)
        await registrar_falha(
            {"id_documento": str(out.id), "orgao_origem": "tjpa"},
            org_a.repo)
        trilha = await org_a.repo.trilha(out.id)
        evs = [t["evento"] for t in trilha]
        assert f"falha_anonimizacao:{out.id}" in evs

    async def test_falha_sem_tramitacao_levanta(self, org_a):
        """Doc órfão (sem tramitação -> FK) propaga — o chamador
        decide dropar; a DLQ não pode hot-loop."""
        with pytest.raises(Exception):
            await registrar_falha(
                {"id_documento": str(uuid.uuid4())},
                org_a.repo)


# ---------- integração real: RabbitMQ + MinIO ----------
AMQP = os.environ.get("TEST_AMQP_URL")
MINIO = os.environ.get("MINIO_URL")
precisa_stack = pytest.mark.skipif(
    not (AMQP and MINIO), reason="sem RabbitMQ/MinIO")


@precisa_stack
class TestWorkerIntegracao:
    async def _stack(self):
        """Broker real com a topologia T12. A fila virou quorum
        (args novos): redeclare divergente derruba o canal — por
        isso deletamos as filas antigas num canal DESCARTÁVEL
        (404 em delete também mata o canal) antes de subir."""
        import aio_pika
        from app.events import (PublicadorRabbitMQ,
                                declarar_topologia_ia)
        conn = await aio_pika.connect_robust(AMQP)
        ch0 = await conn.channel()
        for fila in (PublicadorRabbitMQ.FILA_ANON,
                     PublicadorRabbitMQ.FILA_DLQ):
            try:
                await ch0.queue_delete(fila)
            except Exception:                 # 404: canal morreu
                ch0 = await conn.channel()
        pub = PublicadorRabbitMQ(AMQP)
        await pub.conectar()                  # declara topologia
        ch = await conn.channel()
        _, q, dlq = await declarar_topologia_ia(ch)
        await q.purge()
        await dlq.purge()
        fab = FabricaStorages(lambda orgao, bucket: __import__(
            "app.storage", fromlist=["ArmazenamentoMinIO"]
        ).ArmazenamentoMinIO(
            orgao, MINIO, os.environ.get("MINIO_USER", "edvar"),
            os.environ.get("MINIO_PASS", "edvar_dev_minio"),
            nome_bucket=bucket))
        return pub, conn, q, dlq, fab

    async def test_worker_ia_pipeline(self):
        """DoD: injeta mensagem na fila real, um ciclo consome,
        motor chamado e objeto aparece no bucket anonimizado."""
        pub, conn, q, dlq, fab = await self._stack()
        org, dest = await fab.par("tjpa")
        # feedback: a trilha do nó precisa existir p/ o encadear —
        # cria a tramitação antes, o evento aponta para ela
        e, repo = await mk_repo("a")
        no = NoTramitacao("tjpa", repo, ArmazenamentoMemoria("tjpa"))
        rec = await no.criar(dict(
            caso_cnj=CASO, destino="mpf.pa", modo="pseudonimizacao",
            hash_documento_sha256=hashlib.sha256(DOC).hexdigest(),
            idempotency_key="wk-integ-0001"))
        doc = str(rec.id)
        await org.guardar(doc, io.BytesIO(DOC))    # seed MinIO
        await pub.publicar({"id_documento": doc,
                            "orgao_origem": "tjpa",
                            "id_processo": CASO})
        motor = MotorRapido()
        assert await um_ciclo(q, fab, motor, repo=repo) is True
        assert motor.chamados == [len(DOC)]        # IA foi chamada
        assert await dest.existe(doc)              # resultado lá
        got = b"".join([c async for c in dest.abrir(doc)])
        assert got == DOC
        assert await q.get(fail=False) is None     # fila drenada
        # trilha gravou doc_anonimizado (T11)
        from sqlalchemy import select
        from app.models import Trilha
        async with repo._engine.connect() as c:
            evs = list((await c.scalars(
                select(Trilha.evento).where(
                    Trilha.tramitacao_id == rec.id))).all())
        assert f"doc_anonimizado:{doc}" in evs
        await e.dispose()
        await pub.fechar()
        await fab.fechar()
        await conn.close()

    async def test_falha_motor_nack_e_requeue(self):
        """Motor falhando => NACK: a mensagem volta para a fila
        (requeue) — sem ACK, sem objeto no destino."""
        pub, conn, q, dlq, fab = await self._stack()
        doc = str(uuid.uuid4())
        org, dest = await fab.par("tjpa")
        await org.guardar(doc, io.BytesIO(DOC))
        await pub.publicar({"id_documento": doc,
                            "orgao_origem": "tjpa",
                            "id_processo": CASO})
        with pytest.raises(RuntimeError):
            await um_ciclo(q, fab, MotorQueFalha())
        assert not await dest.existe(doc)          # nada gravado
        de_volta = await q.get(fail=False)         # requeued!
        assert de_volta is not None
        await de_volta.nack(requeue=False)         # limpa a fila
        await pub.fechar()
        await fab.fechar()
        await conn.close()

    async def test_poison_message_dlq(self):
        """DoD T12: motor falhando SEMPRE -> o broker (quorum,
        x-delivery-limit=3) move a mensagem p/ ia.anonimizacao.dlq;
        o ciclo de DLQ grava falha_anonimizacao na trilha."""
        pub, conn, q, dlq, fab = await self._stack()
        e, repo = await mk_repo("a")
        no = NoTramitacao("tjpa", repo, ArmazenamentoMemoria("tjpa"))
        rec = await no.criar(dict(
            caso_cnj=CASO, destino="mpf.pa", modo="pseudonimizacao",
            hash_documento_sha256=hashlib.sha256(DOC).hexdigest(),
            idempotency_key="wk-dlq-0001"))
        doc = str(rec.id)
        org, dest = await fab.par("tjpa")
        await org.guardar(doc, io.BytesIO(DOC))
        await pub.publicar({"id_documento": doc,
                            "orgao_origem": "tjpa",
                            "id_processo": CASO})
        motor = MotorQueFalha()
        # cada ciclo falha -> nack+requeue; após o limite de
        # entregas o broker dead-letters (fila principal esvazia)
        for _ in range(8):
            try:
                if not await um_ciclo(q, fab, motor, repo=repo):
                    break
            except RuntimeError:
                continue
        assert motor.chamados >= 3               # tentou de vdd
        assert await q.get(fail=False) is None   # saiu do fluxo
        assert not await dest.existe(doc)        # nada gravado
        # DLQ drena -> trilha registra o incidente (DoD)
        assert await um_ciclo_dlq(dlq, repo) is True
        trilha = await repo.trilha(rec.id)
        evs = [t["evento"] for t in trilha]
        assert f"falha_anonimizacao:{doc}" in evs
        assert await dlq.get(fail=False) is None  # dlq drenada
        await e.dispose()
        await pub.fechar()
        await fab.fechar()
        await conn.close()
