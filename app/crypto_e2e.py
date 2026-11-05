"""Cifragem ponta a ponta (E2E) — AEAD sobre os bytes que atravessam
a fronteira de confiança de cada contêiner.

Primitivo: ChaCha20-Poly1305 (RFC 8439) — cifra autenticada:
confidencialidade + integridade + detecção de adulteração num
único selo. Não é "hash": hash é irreversível; aqui o receptor
decifra com a mesma chave (E2E simétrica entre os pares do nó).

Formato do quadro v2 (um ou N quadros por mensagem/stream):

  magia 1B = 0xE2 | versão 1B = 0x02 | nonce 12B | len 4B be
  | ts_ms 8B be (carimbo do selamento) | ciphertext len+16B

Fim de stream = quadro com len=0 (truncamento de stream é
detectável — sem o terminador o decifrador rejeita). O AAD de cada
quadro é índice‖ts (i64be + i64be): reordenar/suprimir quadros ou
alterar o carimbo quebra o selo Poly1305.

Anti-replay: o carimbo cobre integridade do tempo; a frescura é
imposta pelo receptor com janela `E2E_JANELA_MS` (padrão 300 s) —
envelope mais velho ou futuro demais é rejeitado. O ingresso HTTP
soma um `ReplayCache` de nonces do quadro 0, que bloqueia o
reenvio do mesmo envelope dentro da janela. Dois canais não usam
o cache de nonce: AMQP, porque a redelivery legítima do broker
reenvia o MESMO envelope (nonce-cache rejeitaria o retry — ele
leva só frescura; dedup de efeito fica na idempotência); e S3,
que é aberto SEM janela — um documento selado ontem precisa
continuar legível (dado em repouso não é replay de comando).
DLQ idem: drenagem forense lê mensagem morta há horas.

Chave: 32 bytes, vem de `E2E_CHAVE` em hex (64 chars) — em
produção a fonte é o Vault do nó (compose `interna`), nunca
imagem nem repo. Relógios dos pares precisam estar sincronizados
(NTP) — a janela tolera o skew até o seu tamanho.

Regra de ouro do desenho: o claro só existe dentro do processo;
tudo que sai pela fronteira (HTTP entre nós, AMQP, objeto S3) é
quadro E2E. Erros de decifragem viram `ErroCripto` — o chamador
mapeia para resposta opaca, sem ecoar o motivo.
"""
from __future__ import annotations

import os
import time
from typing import AsyncIterator, Iterator

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import (
    ChaCha20Poly1305,
)

MAGIA = 0xE2
VERSAO = 0x02
CT_E2E = "application/x-e2e"          # único content-type na rede
_HDR = 26                       # 1 magia + 1 ver + 12 nonce + 4 len + 8 ts
CHUNK = 64 * 1024
JANELA_PADRAO_MS = 300_000            # 5 min > atraso de retry do broker


class ErroCripto(RuntimeError):
    """Envelope malformado ou selo inválido — mapeado para 400/415
    opaco pelo chamador (motivo fino não vaza)."""


def agora_ms() -> int:
    """Relógio de parede em ms — injetável nos testes."""
    return int(time.time() * 1000)


def janela_de_env(nome: str = "E2E_JANELA_MS") -> int | None:
    """Janela de frescura em ms. Ausente => padrão (300 s);
    "0" desliga a frescura (dev — não usar em produção)."""
    v = os.environ.get(nome)
    if v is None:
        return JANELA_PADRAO_MS
    n = int(v)
    return n if n > 0 else None


class ReplayCache:
    """Nonces de quadro 0 dentro da janela — bloqueia o reenvio do
    mesmo envelope. Processo-local: deployment multi-réplica exige
    cache compartilhado (Redis/memcached) — dívida registrada."""

    def __init__(self, capacidade: int = 100_000):
        self._v: dict[bytes, int] = {}
        self._cap = capacidade

    def visto_antes(self, nonce: bytes, agora: int,
                    janela_ms: int) -> bool:
        if len(self._v) >= self._cap:
            self._v = {n: e for n, e in self._v.items()
                       if e > agora}
            if len(self._v) >= self._cap:
                self._v.clear()      # pressão extrema: fail-open com
                # ts+janela ainda ativos — fail-closed viria DoS próprio
        exp = self._v.get(nonce)
        if exp is not None and exp > agora:
            return True
        self._v[nonce] = agora + janela_ms
        return False


def _aead(chave: bytes) -> ChaCha20Poly1305:
    if len(chave) != 32:
        raise ErroCripto("chave deve ter 32 bytes")
    return ChaCha20Poly1305(chave)


def chave_de_env(nome: str = "E2E_CHAVE") -> bytes | None:
    """Chave simétrica do par: hex(32B) na env. Ausente => None
    (modo legado/dev — a blindagem só se impõe onde a chave existe;
    produção configura sempre, é contrato do compose)."""
    v = os.environ.get(nome)
    if not v:
        return None
    try:
        return bytes.fromhex(v.strip())
    except ValueError:
        raise ErroCripto(f"{nome} não é hex de 32 bytes")


def selar(chave: bytes, dados: bytes,
          ts_ms: int | None = None) -> bytes:
    """Um quadro E2E + terminador para o buffer inteiro."""
    return b"".join(_quadros(chave, iter([dados]), ts_ms))


def abrir(chave: bytes, env: bytes,
          janela_ms: int | None = None,
          replay: ReplayCache | None = None,
          agora_ms_: int | None = None) -> bytes:
    """Decifra e verifica envelope E2E em buffer (quadros +
    terminador). Exatamente um quadro de dados — o formato de
    resposta/request JSON do canal."""
    import io
    out = list(abrir_stream(chave, io.BytesIO(env),
                            janela_ms=janela_ms, replay=replay,
                            agora_ms_=agora_ms_))
    if len(out) != 1:
        raise ErroCripto("envelope deve conter exatamente um quadro")
    return out[0]


class FluxoSelador:
    """Cifra blocos incrementais em quadros numerados (AAD =
    índice‖ts) — usado pelo middleware de egresso e por guardar().
    Um carimbo por stream: todos os quadros levam o ts do início."""

    def __init__(self, chave: bytes, ts_ms: int | None = None):
        self._a = _aead(chave)
        self._i = 0
        self.ts = ts_ms if ts_ms is not None else agora_ms()

    def _aad(self, i: int) -> bytes:
        return i.to_bytes(8, "big") + self.ts.to_bytes(8, "big")

    def selar_bloco(self, b: bytes) -> bytes:
        if not b:
            # n=0 é o terminador — bloco vazio geraria quadro
            # ambíguo; quem chama decide antes (middleware pula).
            raise ErroCripto("bloco vazio não vira quadro")
        nonce = os.urandom(12)
        ct = self._a.encrypt(nonce, b, self._aad(self._i))
        self._i += 1
        return (bytes([MAGIA, VERSAO]) + nonce
                + len(b).to_bytes(4, "big")
                + self.ts.to_bytes(8, "big") + ct)

    @staticmethod
    def terminador() -> bytes:
        return bytes([MAGIA, VERSAO]) + b"\x00" * (_HDR - 2)


def _quadros(chave: bytes, blocos: Iterator[bytes],
             ts_ms: int | None = None) -> Iterator[bytes]:
    """Cifra blocos em quadros numerados (AAD = índice‖ts)."""
    s = FluxoSelador(chave, ts_ms)
    for b in blocos:
        yield s.selar_bloco(b)
    yield s.terminador()


def _verifica(i: int, q: bytes, janela_ms: int | None,
              replay: ReplayCache | None, agora: int) -> None:
    """Frescura + replay — comum aos parsers sync e async."""
    if janela_ms is None:
        return
    ts = int.from_bytes(q[18:26], "big")
    if abs(agora - ts) > janela_ms:
        raise ErroCripto("envelope fora da janela temporal")
    if i == 0 and replay is not None and \
            replay.visto_antes(q[2:14], agora, janela_ms):
        raise ErroCripto("envelope reenviado (replay)")


def _abrir_quadros(chave: bytes, quadros: Iterator[bytes],
                   janela_ms: int | None = None,
                   replay: ReplayCache | None = None,
                   agora_ms_: int | None = None
                   ) -> Iterator[bytes]:
    """Decifra/verifica quadros numerados até o terminador."""
    a = _aead(chave)
    agora = agora_ms_ if agora_ms_ is not None else agora_ms()
    for i, q in enumerate(quadros):
        if len(q) < _HDR or q[0] != MAGIA or q[1] != VERSAO:
            raise ErroCripto("quadro malformado")
        n = int.from_bytes(q[14:18], "big")
        if n == 0:
            if any(quadros):
                raise ErroCripto("lixo após o terminador")
            return
        if len(q) != _HDR + n + 16:
            raise ErroCripto("comprimento do quadro diverge")
        _verifica(i, q, janela_ms, replay, agora)
        try:
            yield a.decrypt(q[2:14], q[_HDR:],
                            i.to_bytes(8, "big") + q[18:26])
        except InvalidTag:
            raise ErroCripto("selo inválido (adulterado?)")
    raise ErroCripto("stream sem terminador")


def selar_stream(chave: bytes, fonte) -> Iterator[bytes]:
    """fileobj (spool) -> quadros E2E — streaming, sem materializar."""
    def blocos():
        while b := fonte.read(CHUNK):
            yield b
    return _quadros(chave, blocos())


def abrir_stream(chave: bytes, fonte,
                 janela_ms: int | None = None,
                 replay: ReplayCache | None = None,
                 agora_ms_: int | None = None) -> Iterator[bytes]:
    """fileobj cifrado -> plaintext em blocos — streaming."""
    def quadros():
        while True:
            hdr = fonte.read(_HDR)
            if not hdr:
                return
            if len(hdr) < _HDR:
                raise ErroCripto("cabeçalho de quadro truncado")
            n = int.from_bytes(hdr[14:18], "big")
            body = fonte.read(n + 16) if n else b""
            if len(body) < (n + 16 if n else 0):
                raise ErroCripto("corpo de quadro truncado")
            yield hdr + body
            if n == 0:
                return
    return _abrir_quadros(chave, quadros(), janela_ms=janela_ms,
                          replay=replay, agora_ms_=agora_ms_)


async def abrir_stream_async(chave: bytes,
                             it: AsyncIterator[bytes],
                             janela_ms: int | None = None,
                             replay: ReplayCache | None = None,
                             agora_ms_: int | None = None
                             ) -> AsyncIterator[bytes]:
    """Iterador async de ciphertext -> plaintext (path de download:
    abre o objeto S3 e devolve claro quadro a quadro, sem
    materializar o arquivo inteiro)."""
    a = _aead(chave)
    agora = agora_ms_ if agora_ms_ is not None else agora_ms()
    buf, i, fechado = b"", 0, False

    async for bloco in it:
        if fechado:
            raise ErroCripto("lixo após o terminador")
        buf += bloco
        while len(buf) >= _HDR:
            n = int.from_bytes(buf[14:18], "big")
            total = _HDR if n == 0 else _HDR + n + 16
            if len(buf) < total:
                break
            q, buf = buf[:total], buf[total:]
            if q[0] != MAGIA or q[1] != VERSAO:
                raise ErroCripto("quadro malformado")
            if n == 0:
                fechado = True
                break
            _verifica(i, q, janela_ms, replay, agora)
            try:
                yield a.decrypt(q[2:14], q[_HDR:],
                                i.to_bytes(8, "big") + q[18:26])
            except InvalidTag:
                raise ErroCripto("selo inválido (adulterado?)")
            i += 1
    if buf or not fechado:
        raise ErroCripto("stream cifrada truncada")


def eh_e2e(dados: bytes) -> bool:
    """Detecção barata de payload cifrado (magia + versão)."""
    return len(dados) >= 2 and dados[0] == MAGIA \
        and dados[1] == VERSAO
