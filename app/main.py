"""API de tramitação — MVP (ADR-0003: FastAPI + OpenAPI de código).

Rotas (fluxo A cria -> B recebe -> B confirma):
  POST /v1/tramitacoes                     cria (origem = header auth)
  GET  /v1/tramitacoes/{tid}               status
  POST /v1/tramitacoes/{tid}/envio         monta envelope de trânsito
  POST /v1/tramitacoes/{tid}/reenvio       reemissão após TTL (reconciliação)
  POST /v1/recebimentos                    ingresso do envelope (destino)
  POST /v1/tramitacoes/{tid}/confirmacao   decisão do destino
  POST /v1/tramitacoes/{tid}/acks          origem aplica o ack
  GET  /healthz

Erros: sempre ErroOut, SANITIZADOS — o handler padrão do FastAPI
ecoaria `ctx.input` (o documento inteiro) nas falhas de validação.
Aqui entram só loc+msg: erro nunca vaza payload nem PII.
"""
import uuid

from fastapi import (Depends, FastAPI, File, Request, UploadFile)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse

from app.deps import ErroAuth, orgao_atual
from app.schemas.tramitacao import (
    ConfirmacaoCreate, ConfirmacaoOut, ConsultaTramitacaoOut,
    EnvelopeRecebimento, ErroOut, RecebimentoOut,
    TramitacaoCreate, TramitacaoOut,
)
import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

from app.events import PublicadorRabbitMQ
from app.relay import relay_loop
from app.repository import Repositorio
from app.service import (ErroFluxo, ErroLimiteDocumento,
                         ErroNaoEncontrado, NoTramitacao)


def _erro(status: int, codigo: str, mensagem: str,
          headers: dict = None) -> JSONResponse:
    return JSONResponse(
        status_code=status, headers=headers,
        content=ErroOut(
            erro=ErroOut.Erro(codigo=codigo, mensagem=mensagem)
        ).model_dump(mode="json"))


def _storage_de_env(orgao: str, anonimizados: bool = False):
    """Storage de produção por env: MINIO_URL presente =>
    ArmazenamentoMinIO (bucket do órgão). Ausente => None (testes
    injetam ArmazenamentoMemoria explicitamente).
    anonimizados=True => bucket `*-docs-anonimizados` (T12)."""
    import os
    url = os.environ.get("MINIO_URL")
    if not url:
        return None
    from app.storage import ArmazenamentoMinIO, bucket_para
    return ArmazenamentoMinIO(
        orgao, url, os.environ.get("MINIO_USER", "edvar"),
        os.environ.get("MINIO_PASS", ""),
        nome_bucket=bucket_para(
            orgao, "docs-anonimizados" if anonimizados
            else "docs"))


def create_app(orgao: str, repo: Repositorio = None,
               repo_factory=None, publicador=None,
               storage=None, storage_anon=None) -> FastAPI:
    """Um app por nó — cada órgão sobe a sua instância soberana.

    Duas formas de injeção:
    - `repo`: repositório pronto (mesmo event loop do chamador)
    - `repo_factory`: async () -> (engine, repo), invocada no
      lifespan — necessário quando o app roda em loop próprio
      (uvicorn/TestClient): o engine asyncpg tem que nascer no
      loop que o usa.
    `publicador`: PublicadorEventos para o RELAY outbox→broker
    (padrão: PublicadorRabbitMQ quando RABBITMQ_URL definida).
    Sem a env var o relay não inicia — sqlite/testes ignoram a
    outbox ativamente, como manda a restrição.
    `storage`: ArmazenamentoPort — bucket por órgão (MinIO em
    produção, memória em teste). Se omitido e MINIO_URL estiver
    definida, constrói ArmazenamentoMinIO para o órgão.
    """
    storage = storage if storage is not None else \
        _storage_de_env(orgao)
    storage_anon = storage_anon if storage_anon is not None else \
        _storage_de_env(orgao, anonimizados=True)
    # TTL do gate passivo de reenvio (reconciliação A->B) —
    # configurável por nó via env; default 1h.
    ttl_reenvio = float(
        os.environ.get("TRAMITACAO_REENVIO_TTL_S", "3600"))
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if app.state.no is None:
            e, r = await repo_factory()
            app.state.engine = e
            app.state.no = NoTramitacao(orgao, r, storage,
                                        storage_anon,
                                        ttl_reenvio_s=ttl_reenvio)
        if storage is not None:
            await storage.garantir()
        if storage_anon is not None:
            await storage_anon.garantir()
        url_amqp = os.environ.get("RABBITMQ_URL")
        if url_amqp:
            pub = publicador or PublicadorRabbitMQ(url_amqp)
            if hasattr(pub, "conectar"):
                await pub.conectar()
            app.state.relay_pub = pub
            # retry da outbox: claim por lease + backoff
            # exponencial até ESGOTADO — configurável por env
            app.state.relay_task = asyncio.create_task(
                relay_loop(
                    app.state.no.repo, pub,
                    lease_s=float(
                        os.environ.get("OUTBOX_LEASE_S", "60")),
                    backoff_base_s=float(
                        os.environ.get("OUTBOX_BACKOFF_BASE_S",
                                       "5")),
                    backoff_cap_s=float(
                        os.environ.get("OUTBOX_BACKOFF_CAP_S",
                                       "900")),
                    max_tentativas=int(
                        os.environ.get("OUTBOX_MAX_TENTATIVAS",
                                       "8"))))
        yield
        t = app.state.relay_task
        if t is not None:
            t.cancel()
            with suppress(asyncio.CancelledError):
                await t
        pub = getattr(app.state, "relay_pub", None)
        if hasattr(pub, "fechar"):
            await pub.fechar()
        if hasattr(storage, "fechar"):
            await storage.fechar()
        if hasattr(storage_anon, "fechar"):
            await storage_anon.fechar()
        if app.state.engine is not None:
            await app.state.engine.dispose()

    app = FastAPI(title=f"API de Tramitação — {orgao}",
                  version="0.1.0-mvp", lifespan=lifespan)
    app.state.no = (NoTramitacao(orgao, repo, storage,
                                 storage_anon,
                                 ttl_reenvio_s=ttl_reenvio)
                    if repo else None)
    app.state.engine = None
    app.state.relay_task = None
    app.state.relay_pub = None
    app.state.repo_factory = repo_factory

    def no_atual(req: Request) -> NoTramitacao:
        return req.app.state.no

    # ---------- handlers de erro sanitizados ----------
    @app.exception_handler(RequestValidationError)
    async def _val(req: Request, exc: RequestValidationError):
        # NÃO usar exc.errors() cru: inclui 'input' (= o documento)
        msgs = [".".join(map(str, e["loc"])) + ": " + e["msg"]
                for e in exc.errors()][:5]
        return _erro(422, "payload_invalido", " | ".join(msgs))

    @app.exception_handler(ErroAuth)
    async def _auth(req: Request, exc: ErroAuth):
        # motivo fino (exc.motivo) fica interno — resposta opaca
        log = logging.getLogger("tramitacao.auth")
        log.info("401 %s %s", exc.motivo, req.url.path)
        return _erro(401, "nao_autenticado", str(exc),
                     headers={"WWW-Authenticate": "Bearer"})

    @app.exception_handler(ErroNaoEncontrado)
    async def _404(req: Request, exc: ErroNaoEncontrado):
        return _erro(404, "nao_encontrado", str(exc))

    @app.exception_handler(ErroLimiteDocumento)
    async def _413(req: Request, exc: ErroLimiteDocumento):
        return _erro(413, "documento_excede_limite", str(exc))

    @app.exception_handler(ErroFluxo)
    async def _409(req: Request, exc: ErroFluxo):
        return _erro(409, "conflito_de_fluxo", str(exc))

    # ---------- rotas ----------
    @app.get("/healthz")
    def healthz(no: NoTramitacao = Depends(no_atual)):
        return {"status": "ok", "orgao": no.orgao}

    @app.post("/v1/tramitacoes", status_code=201,
              response_model=TramitacaoOut)
    async def criar(p: TramitacaoCreate,
                    origem: str = Depends(orgao_atual),
                    no: NoTramitacao = Depends(no_atual)):
        return await no.criar(p, origem)

    @app.get("/v1/tramitacoes/{ident}",
             response_model=ConsultaTramitacaoOut)
    async def status(ident: str, org: str = Depends(orgao_atual),
                     no: NoTramitacao = Depends(no_atual)):
        """T12: consulta por UUID da tramitação OU por id_processo
        (CNJ) — mesmo path, dispatch no serviço. Resposta inclui
        trilha encadeada e flags da esteira; isolamento por órgão."""
        return await no.consultar(ident, org)

    @app.post("/v1/tramitacoes/{tid}/envio",
              response_model=EnvelopeRecebimento)
    async def envio(tid: uuid.UUID, org: str = Depends(orgao_atual),
                    no: NoTramitacao = Depends(no_atual)):
        return await no.enviar(tid, org)

    @app.post("/v1/tramitacoes/{tid}/reenvio",
              response_model=EnvelopeRecebimento)
    async def reenvio(tid: uuid.UUID, org: str = Depends(orgao_atual),
                      no: NoTramitacao = Depends(no_atual)):
        """Reemissão idempotente do envelope — reconciliação da
        perda A->B. Só de EM_TRANSITO e só após o TTL do nó;
        mesmas guards e mesma ordem de `envio`."""
        return await no.reenviar(tid, org)

    @app.post("/v1/recebimentos", response_model=RecebimentoOut)
    async def recebimentos(env: EnvelopeRecebimento,
                           org: str = Depends(orgao_atual),
                           no: NoTramitacao = Depends(no_atual)):
        return await no.receber(env, org)

    @app.post("/v1/tramitacoes/{tid}/confirmacao",
              response_model=ConfirmacaoOut)
    async def confirmacao(tid: uuid.UUID, c: ConfirmacaoCreate,
                          org: str = Depends(orgao_atual),
                          no: NoTramitacao = Depends(no_atual)):
        if c.tramitacao_id != tid:
            raise ErroFluxo("id do path difere do corpo")
        return await no.confirmar(c, org)

    @app.post("/v1/tramitacoes/{tid}/acks",
              response_model=TramitacaoOut)
    async def acks(tid: uuid.UUID, conf: ConfirmacaoOut,
                   org: str = Depends(orgao_atual),
                   no: NoTramitacao = Depends(no_atual)):
        return await no.aplicar_confirmacao(tid, conf, org)

    # ---------- storage físico ----------
    @app.post("/v1/documentos/{did}/upload", status_code=201)
    async def upload(did: uuid.UUID, arquivo: UploadFile = File(...),
                     org: str = Depends(orgao_atual),
                     no: NoTramitacao = Depends(no_atual)):
        return await no.upload_documento(did, arquivo, org)

    @app.get("/v1/documentos/{did}/download")
    async def download(did: uuid.UUID,
                       org: str = Depends(orgao_atual),
                       no: NoTramitacao = Depends(no_atual)):
        gen = await no.abrir_documento(did, org)
        return StreamingResponse(
            gen, media_type="application/octet-stream")

    @app.get("/v1/documentos/{did}/download-anonimizado")
    async def download_anon(did: uuid.UUID,
                            org: str = Depends(orgao_atual),
                            no: NoTramitacao = Depends(no_atual)):
        gen = await no.abrir_anonimizado(did, org)
        return StreamingResponse(
            gen, media_type="application/octet-stream")

    return app
