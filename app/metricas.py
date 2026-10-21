"""Métricas de anonimização (item 3) — instrumentação pura.

O pipeline mede, não decide: para cada documento processado o
worker conta entidades por TIPO no texto bruto (detectadas) e no
anonimizado (residuais). substituidas = detectadas - residuais
por tipo (proxy determinístico — a tag não carrega o tipo
original). Residual > 0 é sinal de recall insuficiente do motor:
nesta etapa NÃO há gate nem bloqueio — só o número na trilha de
observação (log estruturado + registro em memória p/ inspeção).

Sem PII na métrica: contam-se ocorrências, nunca os valores.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("tramitacao.metricas")

TAG = "[ANONIMIZADO_LGPD]"

# Formatos LGPD determinísticos — os mesmos que o DemoMotorIA
# substitui, para a métrica medir o que o motor afirma fazer.
# 'nome'/'endereco' cobrem substituições POR RÓTULO (petição).
PADROES: dict[str, str] = {
    "cpf":      r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b",
    "email":    r"\b[\w.+-]+@[\w-]+\.[\w.]+\b",
    "telefone": r"\(?\d{2}\)?\s?9?\d{4}-\d{4}\b",
    "nome":     r"(?im)(?<=: )[^\n,]+(?=,?\s*(?:cpf|rg)\b)",
    "endereco": r"(?im)endere[cç]o\s*:\s*\S[^\n]*",
}
_RE = {k: re.compile(p) for k, p in PADROES.items()}

# Registro em memória por documento — consultável em teste e
# inspecionável no worker (último resultado sobrescreve).
_registro: dict[str, dict] = {}


def _contar(texto: str) -> dict[str, int]:
    # a própria TAG nunca conta — "[TAG], CPF" casaria no padrão
    # de 'nome' (rótulo + vírgula + CPF) sem o filtro
    return {k: len([m for m in rx.findall(texto)
                    if m.strip() != TAG])
            for k, rx in _RE.items()}


def _texto(dados: bytes) -> str:
    """PDF -> pypdf; magic %PDF inválido ou o resto -> utf-8
    ESTRITO. Nada legível -> "" + WARNING (métrica devolve
    zeros, nunca derruba o pipeline)."""
    try:
        if dados.startswith(b"%PDF"):
            try:
                from app.motor_langchain import extrair_texto
                return extrair_texto(dados)
            except Exception:
                pass          # magic %PDF falso: cai p/ utf-8
        txt = dados.decode("utf-8")
        if "�" in txt:
            # binário re-encodado como utf-8 por decode/replace
            # (motor que não lê o formato): parece texto, é lixo
            raise ValueError("utf-8 com U+FFFD — não é texto")
        return txt
    except Exception as e:
        log.warning("metricas: sem texto extraível (%s)", e)
        return ""


def medir(id_documento: str, bruto: bytes,
          anonimizado: bytes) -> dict:
    """Conta por tipo no bruto e no anonimizado; registra e loga
    a linha estruturada. NUNCA levanta — instrumentação não é
    gate (bloqueio p/ residual é dívida em divida-tecnica.md)."""
    try:
        txt_in = _texto(bruto)
        txt_out = _texto(anonimizado)
        det = _contar(txt_in)
        res = _contar(txt_out)
        sub = {k: max(0, det[k] - res[k]) for k in det}
        m = {"id_documento": id_documento,
             # sem legibilidade, residuais=0 é NÃO-LIDO, não limpo
             "entrada_legivel": bool(txt_in.strip()),
             "saida_legivel": bool(txt_out.strip()),
             "detectadas": det,
             "residuais": res,
             # total == soma dos tipos; tags_na_saida é a contagem
             # bruta da tag — divergência entre os dois sinaliza
             # substituição de tipo não-medido (ex.: nome livre)
             "substituidas": {**sub, "total": sum(sub.values()),
                              "tags_na_saida": txt_out.count(TAG)}}
        _registro[id_documento] = m
        log.info("metricas_anon doc=%s detectadas=%s residuais=%s "
                 "substituidas=%s", id_documento, det, res,
                 m["substituidas"])
        return m
    except Exception as e:                        # nunca propaga
        log.warning("metricas: medição falhou (%s)", e)
        return {}


def ultimo(id_documento: str) -> dict:
    return _registro[id_documento]
