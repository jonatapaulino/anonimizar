"""Cifragem ponta a ponta (E2E) — AEAD sobre os bytes que atravessam
a fronteira de confiança de cada contêiner.

Primitivo: ChaCha20-Poly1305 (RFC 8439) — cifra autenticada:
confidencialidade + integridade + detecção de adulteração num
único selo. Não é "hash": hash é irreversível; aqui o receptor
decifra com a mesma chave (E2E simétrica entre os pares do nó).

Formato do quadro (um ou N quadros por mensagem/stream):

  magia 1B = 0xE2 | nonce 12B | len 4B be (plaintext do quadro)
  | ciphertext len+16B (tag Poly1305 no final)

Fim de stream = quadro com len=0 (truncamento de stream é
detectável — sem o terminador o decifrador rejeita). O AAD de cada
quadro é o seu índice (i64be): reordenar/suprimir quadros quebra
o selo. Chave: 32 bytes, vem de `E2E_CHAVE` em hex (64 chars) —
em produção a fonte é o Vault do nó (compose `interna`), nunca
imagem nem repo.

Regra de ouro do desenho: o claro só existe dentro do processo;
tudo que sai pela fronteira (HTTP entre nós, AMQP, objeto S3) é
quadro E2E. Erros de decifragem viram `ErroCripto` — o chamador
mapeia para resposta opaca, sem ecoar o motivo.
"""
from __future__ import annotations

import os
from typing import AsyncIterator, Iterator

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import (
    ChaCha20Poly1305,
)

MAGIA = 0xE2
CT_E2E = "application/x-e2e"          # único content-type na rede
_HDR = 17                              # 1 magia + 12 nonce + 4 len
CHUNK = 64 * 1024


class ErroCripto(RuntimeError):
    """Envelope malformado ou selo inválido — mapeado para 400/415
    opaco pelo chamador (motivo fino não vaza)."""


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


def selar(chave: bytes, dados: bytes) -> bytes:
    """Um quadro E2E + terminador para o buffer inteiro."""
    return b"".join(_quadros(chave, iter([dados])))


def abrir(chave: bytes, env: bytes) -> bytes:
    """Decifra e verifica envelope E2E em buffer (quadros +
    terminador). Exatamente um quadro de dados — o formato de
    resposta/request JSON do canal."""
    import io
    out = list(abrir_stream(chave, io.BytesIO(env)))
    if len(out) != 1:
        raise ErroCripto("envelope deve conter exatamente um quadro")
    return out[0]


class FluxoSelador:
    """Cifra blocos incrementais em quadros numerados (AAD =
    índice) — usado pelo middleware de egresso e por guardar()."""

    def __init__(self, chave: bytes):
        self._a = _aead(chave)
        self._i = 0

    def selar_bloco(self, b: bytes) -> bytes:
        if not b:
            # n=0 é o terminador — bloco vazio geraria quadro
            # ambíguo; quem chama decide antes (middleware pula).
            raise ErroCripto("bloco vazio não vira quadro")
        nonce = os.urandom(12)
        ct = self._a.encrypt(nonce, b, self._i.to_bytes(8, "big"))
        self._i += 1
        return (bytes([MAGIA]) + nonce + len(b).to_bytes(4, "big")
                + ct)

    @staticmethod
    def terminador() -> bytes:
        return bytes([MAGIA]) + b"\x00" * 16


def _quadros(chave: bytes, blocos: Iterator[bytes]
             ) -> Iterator[bytes]:
    """Cifra blocos em quadros numerados (AAD = índice)."""
    s = FluxoSelador(chave)
    for b in blocos:
        yield s.selar_bloco(b)
    yield s.terminador()


def _abrir_quadros(chave: bytes, quadros: Iterator[bytes]
                   ) -> Iterator[bytes]:
    """Decifra/verifica quadros numerados até o terminador."""
    a = _aead(chave)
    for i, q in enumerate(quadros):
        if len(q) < _HDR or q[0] != MAGIA:
            raise ErroCripto("quadro malformado")
        n = int.from_bytes(q[13:17], "big")
        if n == 0:
            if any(quadros):
                raise ErroCripto("lixo após o terminador")
            return
        if len(q) != _HDR + n + 16:
            raise ErroCripto("comprimento do quadro diverge")
        try:
            yield a.decrypt(q[1:13], q[_HDR:], i.to_bytes(8, "big"))
        except InvalidTag:
            raise ErroCripto("selo inválido (adulterado?)")
    raise ErroCripto("stream sem terminador")


def selar_stream(chave: bytes, fonte) -> Iterator[bytes]:
    """fileobj (spool) -> quadros E2E — streaming, sem materializar."""
    def blocos():
        while b := fonte.read(CHUNK):
            yield b
    return _quadros(chave, blocos())


def abrir_stream(chave: bytes, fonte) -> Iterator[bytes]:
    """fileobj cifrado -> plaintext em blocos — streaming."""
    def quadros():
        while True:
            hdr = fonte.read(_HDR)
            if not hdr:
                return
            if len(hdr) < _HDR:
                raise ErroCripto("cabeçalho de quadro truncado")
            n = int.from_bytes(hdr[13:17], "big")
            body = fonte.read(n + 16) if n else b""
            if len(body) < (n + 16 if n else 0):
                raise ErroCripto("corpo de quadro truncado")
            yield hdr + body
            if n == 0:
                return
    return _abrir_quadros(chave, quadros())


async def abrir_stream_async(chave: bytes,
                             it: AsyncIterator[bytes]
                             ) -> AsyncIterator[bytes]:
    """Iterador async de ciphertext -> plaintext (path de download:
    abre o objeto S3 e devolve claro quadro a quadro, sem
    materializar o arquivo inteiro)."""
    a = _aead(chave)
    buf, i, fechado = b"", 0, False

    async for bloco in it:
        if fechado:
            raise ErroCripto("lixo após o terminador")
        buf += bloco
        while len(buf) >= _HDR:
            n = int.from_bytes(buf[13:17], "big")
            total = _HDR if n == 0 else _HDR + n + 16
            if len(buf) < total:
                break
            q, buf = buf[:total], buf[total:]
            if q[0] != MAGIA:
                raise ErroCripto("quadro malformado")
            if n == 0:
                fechado = True
                break
            try:
                yield a.decrypt(q[1:13], q[_HDR:],
                                i.to_bytes(8, "big"))
            except InvalidTag:
                raise ErroCripto("selo inválido (adulterado?)")
            i += 1
    if buf or not fechado:
        raise ErroCripto("stream cifrada truncada")


def eh_e2e(dados: bytes) -> bool:
    """Detecção barata de payload cifrado (primeiro byte)."""
    return len(dados) >= _HDR and dados[0] == MAGIA
