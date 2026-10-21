"""Smoke: contrato de isolamento — verificação ESTÁTICA de
deploy/compose.yaml (ADR-0007/0008).

A prova dinâmica real de egress já existe (P2: probe mediu zero
saída). Este teste garante que o manifesto de referência continua
declarando o que P2 provou — regressão de configuração vira CI.
"""
import yaml
from pathlib import Path
import pytest

COMPOSE = Path(__file__).resolve().parents[2] / "deploy" / "compose.yaml"


@pytest.fixture(scope="module")
def comp():
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def test_rede_interna_e_internal(comp):
    interna = comp["networks"]["interna"]
    assert interna.get("internal") is True


def test_so_nginx_toca_borda(comp):
    for nome, svc in comp["services"].items():
        if nome == "nginx":
            assert set(svc["networks"]) == {"borda", "interna"}
        else:
            assert "borda" not in svc["networks"], \
                f"{nome} não pode ver a rede borda"


def test_so_nginx_publica_porta(comp):
    for nome, svc in comp["services"].items():
        if nome == "nginx":
            assert svc["ports"] == ["443:443"], \
                "nginx publica apenas 443 (TLS+mTLS)"
        else:
            assert "ports" not in svc, \
                f"{nome} não pode publicar portas"


def test_servicos_internos_so_na_rede_interna(comp):
    for nome in ("api", "db", "vault"):
        assert comp["services"][nome]["networks"] == ["interna"]


def test_sem_modo_host_nem_privilegiado(comp):
    for nome, svc in comp["services"].items():
        assert svc.get("network_mode") != "host"
        assert svc.get("privileged") is not True


def test_hardening_baseline(comp):
    for nome, svc in comp["services"].items():
        assert "ALL" in svc.get("cap_drop", []), \
            f"{nome}: cap_drop ALL obrigatório"
        assert "no-new-privileges" in svc.get("security_opt", []), \
            f"{nome}: no-new-privileges obrigatório"
        assert svc.get("read_only") is True, \
            f"{nome}: rootfs read-only obrigatório (ADR-0008)"


def test_cap_add_so_excecao_documentada(comp):
    # única exceção permitida: IPC_LOCK do Vault (requisito dele)
    for nome, svc in comp["services"].items():
        adds = set(svc.get("cap_add", []))
        if nome == "vault":
            assert adds == {"IPC_LOCK"}
        else:
            assert not adds, f"{nome}: cap_add não permitido"
