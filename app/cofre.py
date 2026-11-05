"""Cofre de chaves — fonte e rotação de `E2E_CHAVE`.

Fontes (`E2E_FONTE`):

- `env` (dev/teste): `E2E_CHAVE` é a atual; `E2E_CHAVE_ANTERIOR_1..N`
  (hex 32B) são chaves aposentadas recentemente — a janela de
  rotação que deixa envelopes/objetos antigos legíveis sem
  re-selar o mundo.
- `vault` (produção): KV v2 em `VAULT_ADDR`/`VAULT_KV_PATH` com
  campos `atual` + `anterior_1..N`; auth `VAULT_TOKEN` (dev —
  AppRole/TLS ao Vault fica como dívida de implantação). Cache
  local com TTL (`VAULT_CACHE_TTL_S`, padrão 30 s): rotação no
  cofre propaga sem restart; indisponibilidade transitória não
  derruba o selamento.

Rotação: `ChavesE2E.atual` sela; `todas()` abrem — envelope selado
com a chave recém-rotacionada continua legível na transição. O
admin rotaciona gerando a nova `atual` e promovendo a antiga a
`anterior_1`; quando o último objeto legível expira, a aposentada
sai da lista.

`CofrePseudonimos`: mecanismo do cofre de pseudonimização — o
mapa `ent_id -> rótulo` ([PESSOA_1]…) por documento é gravado
como objeto E2E no storage do nó. Sem o mapa, o pseudônimo é
irrecuperável; com ele, a reidentificação é uma operação
auditável do dono do nó — **uso depende da decisão jurídica**
(pendente) e de o motor emitir `ent_id` (integração pendente).
"""
from __future__ import annotations

import io
import json
import os
import time
from dataclasses import dataclass, field
from typing import Protocol

from app.crypto_e2e import ErroCripto, chave_de_env


@dataclass
class ChavesE2E:
    """Conjunto de rotação: `atual` sela; `todas` abrem."""
    atual: bytes
    anteriores: tuple[bytes, ...] = field(default_factory=tuple)

    def todas(self) -> tuple[bytes, ...]:
        return (self.atual, *self.anteriores)


class FonteChaves(Protocol):
    def chaves(self) -> ChavesE2E | None: ...


class FonteEnv:
    """Dev/teste: env `E2E_CHAVE` + `E2E_CHAVE_ANTERIOR_1..N`."""

    def chaves(self) -> ChavesE2E | None:
        atual = chave_de_env()
        if atual is None:
            return None
        ant = []
        for i in range(1, 9):
            v = chave_de_env(f"E2E_CHAVE_ANTERIOR_{i}")
            if v is None:
                break
            ant.append(v)
        return ChavesE2E(atual, tuple(ant))


class FonteVaultKV:
    """KV v2: GET {addr}/v1/{mount}/data/{path} ->
    data.data = {atual: hex, anterior_1: hex, ...}.
    Auth: header `X-Vault-Token`. Falha transitória devolve a
    última leitura em cache (fail-closed só sem nenhuma leitura
    bem-sucedida — chave vazia seria pior)."""

    def __init__(self, addr: str, path: str, token: str | None,
                 mount: str = "secret", ttl_s: int = 30):
        self._addr, self._path = addr.rstrip("/"), path
        self._token, self._mount = token, mount
        self._ttl = ttl_s
        self._cache: tuple[float, ChavesE2E] | None = None

    def _le_vault(self) -> dict:
        import httpx
        r = httpx.get(
            f"{self._addr}/v1/{self._mount}/data/{self._path}",
            headers={"X-Vault-Token": self._token or ""},
            timeout=5.0)
        r.raise_for_status()
        d = r.json()["data"]["data"]
        if "atual" not in d:
            raise ErroCripto("segredo E2E sem campo 'atual'")
        return d

    def chaves(self) -> ChavesE2E | None:
        if self._cache and time.monotonic() - self._cache[0] \
                < self._ttl:
            return self._cache[1]
        try:
            d = self._le_vault()
        except Exception:
            if self._cache is not None:
                return self._cache[1]    # transitória: última boa
            raise
        ant = []
        for i in range(1, 9):
            v = d.get(f"anterior_{i}")
            if not v:
                break
            ant.append(bytes.fromhex(v))
        c = ChavesE2E(bytes.fromhex(d["atual"]), tuple(ant))
        for k in c.todas():
            if len(k) != 32:
                raise ErroCripto("segredo E2E: chave != 32 bytes")
        self._cache = (time.monotonic(), c)
        return c


def fonte_de_env() -> FonteChaves | None:
    """`E2E_FONTE=env|vault` (padrão env). Retorna a fonte; o
    chamador resolve `.chaves()` (None = sem chave = bypass dev)."""
    f = os.environ.get("E2E_FONTE", "env").lower()
    if f == "env":
        return FonteEnv()
    if f == "vault":
        return FonteVaultKV(
            addr=os.environ["VAULT_ADDR"],
            path=os.environ.get("VAULT_KV_PATH", "isaci/e2e"),
            token=os.environ.get("VAULT_TOKEN"),
            mount=os.environ.get("VAULT_KV_MOUNT", "secret"),
            ttl_s=int(os.environ.get("VAULT_CACHE_TTL_S", "30")))
    raise ErroCripto(f"E2E_FONTE desconhecida: {f}")


def abrir_todas(chaves: ChavesE2E, env: bytes, **kw) -> bytes:
    """`abrir` com rotação: tenta atual -> anteriores em ordem.
    Erro do primeiro candidato vence se nenhuma abrir (o motivo
    fino não vaza para o chamador de qualquer forma)."""
    ult: ErroCripto | None = None
    from app.crypto_e2e import abrir
    for c in chaves.todas():
        try:
            return abrir(c, env, **kw)
        except ErroCripto as e:
            ult = e
    raise ult or ErroCripto("conjunto de chaves vazio")


class CofrePseudonimos:
    """Mapa ent_id->rótulo por documento, como objeto E2E no
    storage do nó. A reidentificação passa por `abrir_mapa` —
    operação que o dono do nó audita (decisão jurídica pendente:
    quem pode pedir, por qual via, sob qual registro)."""

    PREFIXO = "pseudonimos/"

    def __init__(self, storage, chaves: ChavesE2E):
        from app.storage import ArmazenamentoCifrado
        self._st = (storage if isinstance(
            storage, ArmazenamentoCifrado)
            else ArmazenamentoCifrado(storage, chaves))

    async def guardar_mapa(self, tid: str, mapa: dict) -> None:
        dados = json.dumps(mapa, ensure_ascii=False).encode()
        await self._st.guardar(self.PREFIXO + tid,
                               io.BytesIO(dados))

    async def abrir_mapa(self, tid: str) -> dict:
        dados = b"".join(
            [c async for c in self._st.abrir(self.PREFIXO + tid)])
        return json.loads(dados)

    async def existe_mapa(self, tid: str) -> bool:
        return await self._st.existe(self.PREFIXO + tid)
