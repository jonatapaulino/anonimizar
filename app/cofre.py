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

    Autenticação, na ordem de preferência:
      1) AppRole (`VAULT_ROLE_ID`/`VAULT_SECRET_ID`) — login em
         auth/approle/login devolve client_token de escopo e vida
         curtos, re-emitido ao expirar (produção);
      2) `VAULT_TOKEN`/`VAULT_TOKEN_FILE` — dev/seed da malha.
    TLS é verificado pelo bundle da CA interna (TLS_CA_BUNDLE) —
    `verify=ca_bundle() or True` nunca desliga a verificação
    quando a CA está definida.

    Falha transitória devolve a última leitura em cache
    (fail-closed só sem nenhuma leitura bem-sucedida — derrubar
    o nó por blip do Vault seria pior)."""

    def __init__(self, addr: str, path: str, token: str | None,
                 mount: str = "secret", ttl_s: int = 30,
                 token_file: str | None = None,
                 role_id: str | None = None,
                 secret_id: str | None = None,
                 role_id_file: str | None = None,
                 secret_id_file: str | None = None):
        self._addr, self._path = addr.rstrip("/"), path
        self._token, self._mount = token, mount
        self._token_file = token_file
        self._role_id, self._secret_id = role_id, secret_id
        self._role_id_file = role_id_file
        self._secret_id_file = secret_id_file
        self._ttl = ttl_s
        self._cache: tuple[float, ChavesE2E] | None = None
        self._tok_approle: str | None = None
        self._tok_expira = 0.0

    @staticmethod
    def _ler_arquivo(caminho: str | None) -> str:
        """Segredo em arquivo montado ro — mais fraco de vazamento
        que env (não aparece em /proc/*/environ nem em inspect)."""
        if not caminho:
            return ""
        try:
            return open(caminho).read().strip()
        except OSError:
            return ""

    def _cred_approle(self) -> tuple[str, str]:
        """Role/secret resolvidos por env OU por arquivo — o par
        é indivisível: metade ausente não é AppRole utilizável."""
        return (self._role_id
                or self._ler_arquivo(self._role_id_file),
                self._secret_id
                or self._ler_arquivo(self._secret_id_file))

    def _login_approle(self, role_id: str,
                     secret_id: str) -> str:
        """AppRole -> client token curto, cache até 80% do lease.
        Segredos nunca vão a log; falha de login propaga —
        `chaves()` decide se o cache cobre a transitoriedade."""
        agora = time.monotonic()
        if self._tok_approle and agora < self._tok_expira:
            return self._tok_approle
        import httpx
        from app.tls_interno import ca_bundle
        r = httpx.post(
            f"{self._addr}/v1/auth/approle/login",
            json={"role_id": role_id, "secret_id": secret_id},
            timeout=5.0, verify=ca_bundle() or True)
        r.raise_for_status()
        a = r.json()["auth"]
        self._tok_approle = a["client_token"]
        self._tok_expira = agora + a.get("lease_duration", 60) * 0.8
        return self._tok_approle

    def _token_atual(self) -> str:
        """AppRole (escopo curto) > token direto/arquivo (dev)."""
        role_id, secret_id = self._cred_approle()
        if role_id and secret_id:
            return self._login_approle(role_id, secret_id)
        if self._token:
            return self._token
        if self._token_file:
            try:
                return open(self._token_file).read().strip()
            except OSError:
                return ""
        return ""

    def _le_vault(self) -> dict:
        import httpx
        from app.tls_interno import ca_bundle
        r = httpx.get(
            f"{self._addr}/v1/{self._mount}/data/{self._path}",
            headers={"X-Vault-Token": self._token_atual()},
            timeout=5.0,
            verify=ca_bundle() or True)
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
        role_id = os.environ.get("VAULT_ROLE_ID")
        secret_id = os.environ.get("VAULT_SECRET_ID")
        role_id_file = os.environ.get("VAULT_ROLE_ID_FILE")
        secret_id_file = os.environ.get("VAULT_SECRET_ID_FILE")
        token = os.environ.get("VAULT_TOKEN")
        token_file = os.environ.get("VAULT_TOKEN_FILE")
        tem_approle = ((role_id or role_id_file)
                       and (secret_id or secret_id_file))
        if not (token or token_file or tem_approle):
            # produção pediu Vault sem credencial utilizável —
            # fail-closed: a API não sobe com a fonte cega
            raise ErroCripto(
                "E2E_FONTE=vault sem autenticação — configure "
                "VAULT_ROLE_ID(_FILE)+VAULT_SECRET_ID(_FILE) "
                "(AppRole) ou, em dev, VAULT_TOKEN(_FILE)")
        return FonteVaultKV(
            addr=os.environ["VAULT_ADDR"],
            path=os.environ.get("VAULT_KV_PATH", "isaci/e2e"),
            token=token,
            mount=os.environ.get("VAULT_KV_MOUNT", "secret"),
            ttl_s=int(os.environ.get("VAULT_CACHE_TTL_S", "30")),
            token_file=token_file,
            role_id=role_id, secret_id=secret_id,
            role_id_file=role_id_file,
            secret_id_file=secret_id_file)
    raise ErroCripto(f"E2E_FONTE desconhecida: {f}")


def abrir_todas(chaves: ChavesE2E, env: bytes, **kw) -> bytes:
    """`abrir` com rotação: tenta atual -> anteriores em ordem.
    Erro do primeiro candidato vence se nenhuma abrir (o motivo
    fino não vaza para o chamador de qualquer forma).

    O claim de replay NÃO vai junto das tentativas de chave: o
    nonce só é reclamado depois de uma abertura bem-sucedida —
    senão a 1ª chave errada já consumia o nonce e a vencedora
    esbarrava em "replay" (bug latente da rotação+replay)."""
    from app.crypto_e2e import abrir, agora_ms
    replay = kw.pop("replay", None)
    janela_ms = kw.get("janela_ms")
    agora = kw.get("agora_ms_") or agora_ms()
    ult: ErroCripto | None = None
    for c in chaves.todas():
        try:
            claro = abrir(c, env, replay=None, **kw)
        except ErroCripto as e:
            ult = e
            continue
        if replay is not None and janela_ms and \
                replay.visto_antes(env[2:14], agora, janela_ms):
            raise ErroCripto("envelope reenviado (replay)")
        return claro
    raise ult or ErroCripto("conjunto de chaves vazio")


_MAX_QUADRO_BYTES = 32 * 1024 * 1024


async def abrir_stream_todas(chaves: ChavesE2E, it,
                             janela_ms: int | None = None,
                             replay=None, replay_db=None,
                             agora_ms_: int | None = None):
    """`abrir_todas` em modo streaming — o ingresso E2E não
    materializa mais o corpo cifrado (divida-tecnica §4.c).

    Rotação com lookahead de UM quadro: o quadro 0 é bufado (o
    tamanho vem do próprio cabeçalho, cap `_MAX_QUADRO_BYTES`
    contra quadros gigantes) e cada chave é tentada nele — selo,
    janela e replay decidem já no primeiro frame. Achada a
    vencedora, os quadros seguintes decifram lazy conforme o
    consumidor puxa: um upload de 20 MiB atravessa quadro a
    quadro sem nunca existir inteiro em RAM.

    `replay` — cache síncrono (processo-local; uma réplica).
    `replay_db` — store compartilhado (`repo.replay_visto`):
    claim async do nonce do quadro 0, feito SÓ depois do selo
    conferir — nonce não autenticado nunca entra na tabela.
    """
    from cryptography.exceptions import InvalidTag
    from app.crypto_e2e import (_HDR, MAGIA, VERSAO, _aead,
                                _verifica, agora_ms)

    ait = it.__aiter__()
    buf = bytearray()

    async def _enche(n: int) -> bool:
        while len(buf) < n:
            try:
                buf.extend(await ait.__anext__())
            except StopAsyncIteration:
                return False
        return True

    # quadro 0 inteiro — janela, selo e replay decidem aqui;
    # qualquer rejeição sai antes de o request tocar a aplicação
    if not await _enche(_HDR):
        raise ErroCripto("stream vazio")
    if buf[0] != MAGIA or buf[1] != VERSAO:
        raise ErroCripto("quadro malformado")
    n0 = int.from_bytes(buf[14:18], "big")
    if n0 == 0:
        raise ErroCripto("sem dados no quadro 0")
    if n0 > _MAX_QUADRO_BYTES:
        raise ErroCripto("quadro acima do limite")
    total0 = _HDR + n0 + 16
    if not await _enche(total0):
        raise ErroCripto("quadro truncado")
    q0 = bytes(buf[:total0])
    del buf[:total0]

    agora = agora_ms_ if agora_ms_ is not None else agora_ms()
    vencedora = None
    for k in chaves.todas():
        try:
            _verifica(0, q0, janela_ms, None, agora)
            plain0 = _aead(k).decrypt(
                q0[2:14], q0[_HDR:],
                (0).to_bytes(8, "big") + q0[18:26])
            vencedora = k
            break
        except (ErroCripto, InvalidTag):
            continue
    if vencedora is None:
        raise ErroCripto("selo inválido")

    # claim do nonce UMA vez, com a chave que abriu — sync ou DB
    if replay is not None and janela_ms and \
            replay.visto_antes(q0[2:14], agora, janela_ms):
        raise ErroCripto("envelope reenviado (replay)")
    if replay_db is not None and await replay_db.replay_visto(
            q0[2:14].hex(), agora + (janela_ms or 0)):
        raise ErroCripto("envelope reenviado (replay)")

    yield plain0

    # continuação lazy — mesmo parser de `abrir_stream_async`,
    # índice seguindo do quadro 1 e drenando o lookahead primeiro
    a = _aead(vencedora)
    i, fechado = 1, False
    resto_inicial = bytes(buf)
    buf.clear()

    async def _resto():
        if resto_inicial:
            yield resto_inicial
        async for bloco in ait:
            yield bloco

    async for bloco in _resto():
        if fechado:
            raise ErroCripto("lixo após o terminador")
        buf += bloco
        while len(buf) >= _HDR:
            n = int.from_bytes(buf[14:18], "big")
            if n > _MAX_QUADRO_BYTES:
                raise ErroCripto("quadro acima do limite")
            total = _HDR if n == 0 else _HDR + n + 16
            if len(buf) < total:
                break
            q = bytes(buf[:total])
            del buf[:total]
            if q[0] != MAGIA or q[1] != VERSAO:
                raise ErroCripto("quadro malformado")
            if n == 0:
                fechado = True
                break
            _verifica(i, q, janela_ms, None, agora)
            try:
                yield a.decrypt(
                    q[2:14], q[_HDR:],
                    i.to_bytes(8, "big") + q[18:26])
            except InvalidTag:
                raise ErroCripto("selo inválido (adulterado?)")
            i += 1
    if buf or not fechado:
        raise ErroCripto("stream cifrada truncada")


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
