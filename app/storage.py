"""Armazenamento físico de documentos — object storage por órgão.

Isolamento por bucket: cada nó soberano tem o seu
(`bucket_para(orgao)` — ex.: tjpa -> tjpa-docs). O adaptador
garante o bucket na inicialização (ou primeiro uso).

Restrição dura: STREAMING sempre — arquivo nunca inteiro em RAM.
Upload: chunks assíncronos alimentam o SHA-256 e um spool em
disco; download: iterador async de chunks para StreamingResponse.
"""
from __future__ import annotations

import logging
import re
from typing import AsyncIterator, Protocol

log = logging.getLogger("tramitacao.storage")

CHUNK = 64 * 1024


def bucket_para(orgao: str, nome: str = "docs") -> str:
    """Nome de bucket válido a partir do id do órgão.
    `nome` permite variantes por função — a esteira grava o
    resultado em `<org>-docs-anonimizados`."""
    return re.sub(r"[^a-z0-9-]", "-", orgao.lower()).strip("-") \
        + "-" + nome


class ArmazenamentoPort(Protocol):
    """Contrato do storage físico — implementações não bloqueiam
    o event loop e nunca materializam o arquivo inteiro em RAM."""
    async def garantir(self) -> None:
        """Bucket do órgão existe (idempotente)."""
        ...
    async def guardar(self, chave: str, fonte) -> None:
        """fonte: fileobj posicionado (spool) — multipart/chunked."""
        ...
    def abrir(self, chave: str) -> AsyncIterator[bytes]: ...
    async def existe(self, chave: str) -> bool: ...
    async def fechar(self) -> None: ...


class ArmazenamentoMemoria:
    """TDD: dict em processo. `garantir` é no-op; guardar lê o
    spool inteiro — ok em teste (docs pequenos)."""
    def __init__(self, orgao: str, nome_bucket: str | None = None):
        self.bucket = nome_bucket or bucket_para(orgao)
        self._objs: dict[str, bytes] = {}

    async def garantir(self):
        pass

    async def guardar(self, chave: str, fonte):
        self._objs[chave] = fonte.read()

    async def abrir(self, chave: str):
        data = self._objs[chave]
        for i in range(0, len(data), CHUNK):
            yield data[i:i + CHUNK]

    async def existe(self, chave: str) -> bool:
        return chave in self._objs

    async def fechar(self):
        pass


class ArmazenamentoMinIO:
    """S3/MinIO via aioboto3 — upload_fileobj faz multipart
    chunked (não materializa em RAM); get_object devolve stream."""
    def __init__(self, orgao: str, endpoint: str, access: str,
                 secret: str, secure: bool = False,
                 nome_bucket: str | None = None,
                 ca_bundle: str | None = None):
        import aioboto3
        self.bucket = nome_bucket or bucket_para(orgao)
        # secure=True força https no endpoint — tráfego S3 nunca
        # legível na rede interna. ca_bundle = CA privada do nó
        # (TLS_CA_BUNDLE); sem ela, https de CA interna falha.
        if secure and endpoint.startswith("http://"):
            endpoint = "https://" + endpoint[len("http://"):]
        self._sess = aioboto3.Session()
        self._kw = dict(service_name="s3",
                        endpoint_url=endpoint,
                        aws_access_key_id=access,
                        aws_secret_access_key=secret)
        if ca_bundle:
            self._kw["verify"] = ca_bundle
        self._cm = self._s3 = None

    async def garantir(self):
        from botocore.exceptions import ClientError
        if self._s3 is None:
            self._cm = self._sess.client(**self._kw)
            self._s3 = await self._cm.__aenter__()
        try:
            await self._s3.head_bucket(Bucket=self.bucket)
        except ClientError:
            await self._s3.create_bucket(Bucket=self.bucket)
            log.info("bucket %s criado", self.bucket)

    async def guardar(self, chave: str, fonte):
        # multipart chunked — o SDK não lê o arquivo inteiro
        await self._s3.upload_fileobj(fonte, self.bucket, chave)

    async def abrir(self, chave: str):
        resp = await self._s3.get_object(Bucket=self.bucket,
                                         Key=chave)
        body = resp["Body"]
        while chunk := await body.read(CHUNK):
            yield chunk

    async def existe(self, chave: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            await self._s3.head_object(Bucket=self.bucket,
                                       Key=chave)
            return True
        except ClientError:
            return False

    async def fechar(self):
        if self._cm:
            await self._cm.__aexit__(None, None, None)
            self._s3 = self._cm = None


class ArmazenamentoCifrado:
    """Envelope AEAD sobre qualquer ArmazenamentoPort — blindagem
    de repouso+trânsito no objeto: o backend (MinIO/memória) só
    persiste quadros E2E; o claro existe só dentro do processo que
    selou/abriu. Streaming preservado: guardar cifra bloco a bloco
    para spool; abrir decifra quadro a quadro do stream.

    `chave` aceita `bytes` ou `ChavesE2E` (rotação): sela com a
    atual; abre tentando atual->anteriores — objeto selado com
    chave recém-rotacionada continua legível na transição."""
    def __init__(self, inner: ArmazenamentoPort, chave):
        from app.cofre import ChavesE2E
        self._chaves = (chave if isinstance(chave, ChavesE2E)
                        else ChavesE2E(chave))
        self._inner = inner
        self.bucket = inner.bucket

    async def garantir(self):
        await self._inner.garantir()

    async def guardar(self, chave: str, fonte):
        import tempfile
        from app.crypto_e2e import selar_stream
        spool = tempfile.SpooledTemporaryFile(max_size=CHUNK * 8)
        for q in selar_stream(self._chaves.atual, fonte):
            spool.write(q)
        spool.seek(0)
        await self._inner.guardar(chave, spool)

    async def abrir(self, chave: str):
        from app.crypto_e2e import ErroCripto, abrir_stream_async
        ult = None
        for c in self._chaves.todas():
            # fallback só ANTES de qualquer claro sair — falha no
            # meio do stream é adulteração, não chave errada
            cedeu = False
            try:
                async for b in abrir_stream_async(
                        c, self._inner.abrir(chave)):
                    cedeu = True
                    yield b
                return
            except ErroCripto as e:
                if cedeu:
                    raise
                ult = e
        raise ult or ErroCripto("conjunto de chaves vazio")

    async def existe(self, chave: str) -> bool:
        return await self._inner.existe(chave)

    async def fechar(self):
        await self._inner.fechar()
