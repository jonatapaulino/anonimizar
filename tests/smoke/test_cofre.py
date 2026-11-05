"""Cofre de chaves — fonte env/vault, rotação e pseudônimos.

Rotação = a invariante que importa: envelope/objeto selado com a
chave aposentada continua legível na janela de transição; o que é
selado depois usa só a atual.
"""
import io
import json

import pytest

from app.cofre import (ChavesE2E, CofrePseudonimos, FonteEnv,
                       FonteVaultKV, abrir_todas, fonte_de_env)
from app.crypto_e2e import ErroCripto, eh_e2e, selar
from app.storage import ArmazenamentoMemoria

CHAVE_A = bytes(range(32))
CHAVE_B = bytes(reversed(range(32)))


class TestFonteEnv:
    def test_so_atual(self, monkeypatch):
        monkeypatch.setenv("E2E_CHAVE", CHAVE_A.hex())
        c = FonteEnv().chaves()
        assert c.atual == CHAVE_A and c.anteriores == ()

    def test_com_anteriores(self, monkeypatch):
        monkeypatch.setenv("E2E_CHAVE", CHAVE_A.hex())
        monkeypatch.setenv("E2E_CHAVE_ANTERIOR_1", CHAVE_B.hex())
        c = FonteEnv().chaves()
        assert c.todas() == (CHAVE_A, CHAVE_B)

    def test_sem_chave_none(self, monkeypatch):
        monkeypatch.delenv("E2E_CHAVE", raising=False)
        assert FonteEnv().chaves() is None

    def test_fonte_de_env_padrao_env(self, monkeypatch):
        monkeypatch.delenv("E2E_FONTE", raising=False)
        assert isinstance(fonte_de_env(), FonteEnv)


class TestFonteVault:
    def _fake_httpx(self, monkeypatch, dados, status=200):
        class _Resp:
            status_code = status

            def raise_for_status(self):
                if self.status_code != 200:
                    raise RuntimeError("vault indisponível")

            def json(self):
                return {"data": {"data": dados}}
        import httpx
        monkeypatch.setattr(httpx, "get",
                            lambda *a, **k: _Resp())

    def test_le_kv(self, monkeypatch):
        self._fake_httpx(monkeypatch, {
            "atual": CHAVE_A.hex(), "anterior_1": CHAVE_B.hex()})
        f = FonteVaultKV("http://vault:8200", "isaci/e2e", "tok")
        c = f.chaves()
        assert c.todas() == (CHAVE_A, CHAVE_B)

    def test_cache_evita_releitura(self, monkeypatch):
        chamadas = []

        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                chamadas.append(1)
                return {"data": {"data": {"atual": CHAVE_A.hex()}}}
        import httpx
        monkeypatch.setattr(httpx, "get",
                            lambda *a, **k: _Resp())
        f = FonteVaultKV("http://v", "p", "t", ttl_s=60)
        f.chaves()
        f.chaves()
        assert len(chamadas) == 1

    def test_transitorio_devolve_cache(self, monkeypatch):
        """Falha na leitura com cache válido => última boa, não
        fail-closed cego (derrubar o nó seria pior)."""
        self._fake_httpx(monkeypatch, {"atual": CHAVE_A.hex()})
        f = FonteVaultKV("http://v", "p", "t")
        f.chaves()
        self._fake_httpx(monkeypatch, {}, status=500)
        assert f.chaves().atual == CHAVE_A

    def test_sem_cache_falha_propaga(self, monkeypatch):
        self._fake_httpx(monkeypatch, {}, status=500)
        f = FonteVaultKV("http://v", "p", "t")
        with pytest.raises(Exception):
            f.chaves()


class TestRotacao:
    def test_objeto_antigo_abre_na_transicao(self):
        """Selado com a aposentada -> abre com (nova, velha)."""
        env = selar(CHAVE_B, b"documento legado")
        c = ChavesE2E(CHAVE_A, (CHAVE_B,))
        assert abrir_todas(c, env) == b"documento legado"

    def test_novo_so_com_a_atual(self):
        """Selado com a atual não abre com a aposentada sozinha."""
        env = selar(CHAVE_A, b"x")
        with pytest.raises(ErroCripto):
            abrir_todas(ChavesE2E(CHAVE_B), env)

    async def test_storage_rotaciona(self):
        """Objeto gravado antes da rotação continua legível depois
        — a transição não re-sela o mundo."""
        from app.storage import ArmazenamentoCifrado
        inner = ArmazenamentoMemoria("tjpa")
        st_velho = ArmazenamentoCifrado(inner, ChavesE2E(CHAVE_B))
        await st_velho.guardar("doc", io.BytesIO(b"legado"))
        st_novo = ArmazenamentoCifrado(
            inner, ChavesE2E(CHAVE_A, (CHAVE_B,)))
        claro = b"".join([c async for c in st_novo.abrir("doc")])
        assert claro == b"legado"
        # e o que se grava agora é da chave nova
        await st_novo.guardar("doc2", io.BytesIO(b"novo"))
        with pytest.raises(ErroCripto):
            abrir_todas(ChavesE2E(CHAVE_B),
                        inner._objs["doc2"])


class TestPseudonimos:
    async def test_mapa_selado_roundtrip(self):
        inner = ArmazenamentoMemoria("tjpa")
        cofre = CofrePseudonimos(inner, ChavesE2E(CHAVE_A))
        mapa = {"e1": "PESSOA_1", "e2": "PESSOA_2",
                "e3": "ORGAO_1"}
        await cofre.guardar_mapa("tid-1", mapa)
        # no disco: objeto E2E, não o JSON do mapa
        bruto = inner._objs["pseudonimos/tid-1"]
        assert eh_e2e(bruto)
        assert b"PESSOA_1" not in bruto
        assert await cofre.existe_mapa("tid-1")
        assert await cofre.abrir_mapa("tid-1") == mapa

    async def test_mapa_adulterado_falha(self):
        inner = ArmazenamentoMemoria("tjpa")
        cofre = CofrePseudonimos(inner, ChavesE2E(CHAVE_A))
        await cofre.guardar_mapa("tid-2", {"e1": "PESSOA_1"})
        bruto = bytearray(inner._objs["pseudonimos/tid-2"])
        bruto[40] ^= 0x01
        inner._objs["pseudonimos/tid-2"] = bytes(bruto)
        with pytest.raises(ErroCripto):
            await cofre.abrir_mapa("tid-2")
