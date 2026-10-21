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
                 nome_bucket: str | None = None):
        import aioboto3
        self.bucket = nome_bucket or bucket_para(orgao)
        self._sess = aioboto3.Session()
        self._kw = dict(service_name="s3",
                        endpoint_url=(endpoint if secure else
                                      endpoint),
                        aws_access_key_id=access,
                        aws_secret_access_key=secret)
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
