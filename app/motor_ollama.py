"""Motor IA local — Ollama (/api/generate), soberano (IA_ENGINE=ollama).

Mesmo contrato do worker: anonimizar(bytes) -> bytes (PDF -> PDF).
O LLM é um EXTRATOR PURO (temperature=0): devolve o texto integral
com entidades pessoais substituídas por [ANONIMIZADO_LGPD] — o
mesmo SYSTEM_PROMPT do motor LangChain; o documento é inerte.

Diferença arquitetural relevante: o modelo roda na própria máquina
(localhost:11434) — nenhum byte do documento sai do perímetro
soberano, ao contrário de IA_LLM=openai|google (egress externo).

Env: IA_MODEL (default qwen2.5:7b), OLLAMA_URL (default
http://localhost:11434), IA_NUM_CTX (default 8192).
Na construção, GET /api/tags confirma o modelo e grava o digest —
tags flutuam entre releases; o digest é a referência estável.
"""
from __future__ import annotations

import logging
import os

from app.motor_langchain import (SYSTEM_PROMPT, TAG, _limpar,
                                 extrair_texto, pdf_de_texto)

log = logging.getLogger("tramitacao.motor.ollama")

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:7b"


class MotorOllama:
    """MotorIA via Ollama local — async, mesmo contrato do worker."""

    def __init__(self, base_url: str, modelo: str, digest: str,
                 num_ctx: int = 8192):
        self.base_url = base_url.rstrip("/")
        self.modelo = modelo
        self.digest = digest
        self.num_ctx = num_ctx
        self.chamados: list[int] = []       # observável p/ teste

    @classmethod
    def de_env(cls, num_ctx: int | None = None):
        """Confirma o modelo em /api/tags antes de qualquer
        execução e grava o digest exato (a tag flutua)."""
        import httpx
        base = os.environ.get("OLLAMA_URL", DEFAULT_URL).rstrip("/")
        modelo = os.environ.get("IA_MODEL", DEFAULT_MODEL)
        ctx = int(num_ctx or os.environ.get("IA_NUM_CTX", "8192"))
        tags = httpx.get(f"{base}/api/tags", timeout=10).json()
        hit = [m for m in tags.get("models", [])
               if m.get("model") == modelo or m.get("name") == modelo]
        if not hit:
            raise RuntimeError(
                f"Ollama: modelo {modelo!r} ausente em /api/tags — "
                f"rode `ollama pull {modelo}`")
        digest = hit[0]["digest"]
        log.info("ollama: modelo %s digest %s num_ctx=%d",
                 modelo, digest[:16], ctx)
        return cls(base, modelo, digest, ctx)

    async def _gerar(self, texto: str) -> str:
        """POST /api/generate — extrator puro, stream desligado."""
        import httpx
        async with httpx.AsyncClient(
                base_url=self.base_url, timeout=300) as cli:
            r = await cli.post("/api/generate", json={
                "model": self.modelo,
                "system": SYSTEM_PROMPT,
                "prompt": texto,
                "stream": False,
                "options": {"temperature": 0,
                            "num_ctx": self.num_ctx}})
            r.raise_for_status()
            return r.json().get("response", "")

    async def anonimizar_texto(self, texto: str) -> str:
        """Núcleo do extrator: texto -> texto anonimizado.
        Entrada: texto extraído, nunca bytes crus do arquivo."""
        self.chamados.append(len(texto))
        if not texto.strip():
            return texto
        return _limpar(await self._gerar(texto))

    async def anonimizar(self, conteudo: bytes) -> bytes:
        """Contrato do worker: bytes PDF -> bytes PDF anonimizado.
        O prompt leva só o texto extraído — nunca os bytes crus."""
        texto = extrair_texto(conteudo)
        if not texto.strip():
            log.warning("ollama: PDF sem texto extraível")
            return pdf_de_texto("")
        anonimizado = await self.anonimizar_texto(texto)
        log.info("ollama: %d chars -> %d chars",
                 len(texto), len(anonimizado))
        return pdf_de_texto(anonimizado)


__all__ = ["MotorOllama", "TAG"]
