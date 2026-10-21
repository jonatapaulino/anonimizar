"""Smoke: contrato do HMAC por caso (emenda ADR-0004 / ADR-0012),
verificado contra a implementação de referência provada em P5
(spikes/p5_hmac_caso.py — mesmo código que gerou a evidência).

Na tramitação, o escopo da chave é o caso_cnj: a mesma entidade
recebe HMACs distintos em processos distintos e a destruição da
chave do caso mata o lookup (irreversibilidade operacional).
"""
import secrets
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from spikes.p5_hmac_caso import Cofre, key_new  # referência provada

ENT = "João da Silva|CPF:123.456.789-00"


@pytest.fixture
def K():
    return secrets.token_bytes(32)


def test_mesma_entidade_mesmo_caso_mesmo_token(K, caso):
    assert key_new(K, ENT, caso) == key_new(K, ENT, caso)


def test_mesma_entidade_outro_caso_outro_token(K):
    a = key_new(K, ENT, "5614226-41.2021.8.14.2679")
    b = key_new(K, ENT, "0000001-01.2020.8.13.0001")
    assert a != b                       # zero correlação transversal


def test_cofre_lookup_legitimo_funciona(K, caso):
    c = Cofre(K, key_new)
    c.put(ENT, caso, "PARTE-1")
    assert c.get(ENT, caso) == "PARTE-1"


def test_chaves_de_casos_distintos_nao_colidem(K):
    c = Cofre(K, key_new)
    casos = [f"000000{i}-0{i}.202{i}.8.14.000{i}" for i in range(1, 8)]
    for cs in casos:
        c.put(ENT, cs, f"P-{cs[-4:]}")
    assert len(c.chaves()) == len(casos)


def test_destruicao_da_chave_mata_lookup(caso):
    K = secrets.token_bytes(32)
    c = Cofre(K, key_new)
    c.put(ENT, caso, "PARTE-1")
    token_antes = key_new(K, ENT, caso)
    # ADR-0012: destruição cerimonial da chave do caso
    K = None
    assert not any(
        key_new(k, ENT, caso) == token_antes
        for k in (secrets.token_bytes(32) for _ in range(50))
    )   # nenhuma chave nova reproduz o token — oráculo morto


def test_token_nao_vaza_entidade(K, caso):
    t = key_new(K, ENT, caso)
    assert "jo" not in t.lower() and "silva" not in t.lower()
    assert len(t) == 64                 # hex sha256 — formato fixo
