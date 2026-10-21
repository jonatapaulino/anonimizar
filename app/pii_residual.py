"""Gate de PII residual — salvaguarda mínima da POC.

Determinístico, auditável, sem PII no retorno: conta ocorrências
por tipo no TEXTO DE SAÍDA do motor (depois das substituições).
Qualquer contagem > 0 deve barrar a gravação no bucket
anonimizado — é a última linha de defesa antes de publicar um
documento que ainda contém dado pessoal.

Tipos:
  cpf, rg, email, telefone — formatos determinísticos;
  nome_contexto — nome de pessoa após rótulos de menção direta
  ("intimad[oa]", "em face de", "servidor(a)"), os contextos onde
  a passada LLM de nomes mostrou omitir enumerações.

DECLARAÇÃO: os padrões de contexto foram definidos após observar
falhas na partição ajuste; NÃO são validados como cobertura de
nomes e o gate NÃO garante ausência de PII — detecta apenas os
formatos/contextos codificados. Nomes livres, formatos novos e
PII fora dos padrões passam silenciosamente.
"""
from __future__ import annotations

import re

TAG = "[ANONIMIZADO_LGPD]"

# Cada tipo -> lista de padrões. Matches sobrepostos do mesmo
# tipo são deduplicados por span (rótulo e formato não contam 2x).
NOME = r"[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][\w.''-]*" \
       r"(?:\s+(?:d[aeios]|e)\s+[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][\w.''-]*|\s+" \
       r"[A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][\w.''-]*)+"

PADROES: dict[str, list[str]] = {
    "cpf": [
        r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b",
        r"\b\d{11}\b",                      # CPF sem pontuação
    ],
    "rg": [
        # com dígito verificador (hífen + dígito/X) — formato forte
        r"(?<!R\$\s)\b\d{1,2}\.\d{3}\.\d{3}-[\dXx]\b",
        r"\b\d{7,8}-[A-Z]{2}\b",            # "4455667-PA"
        # rótulo explícito cobre formatos sem dígito verificador
        r"(?i)\bRG\b[\s:]*(?:SSP[-\s]?[A-Z]{2}|[A-Z]{2})?"
        r"[\s]*\d[\d.]{5,}",
    ],
    "email": [
        r"\b[\w.+-]+@[\w-]+\.[\w.]+\b",
    ],
    "telefone": [
        r"(?:\(\d{2}\)\s?|\b\d{2}\s)?9?\d{4}-\d{4}\b",
    ],
    "nome_contexto": [
        # contexto case-insensitive, NOME case-sensitive —
        # um (?i) global deixaria 'servidor público' casar
        r"(?i:intimad[oa]\(?s?\)?|em\s+face\s+de|"
        r"servidor(?:\(a\)|a)?)\s*[:,]?\s+(" + NOME + r")",
    ],
}
_RE = {k: [re.compile(p) for p in ps] for k, ps in PADROES.items()}

# contextos de nome que NÃO são pessoa física — reduz FP de
# órgãos/instituições escritos em caps após "em face de"
_NOME_STOP = re.compile(
    r"(?i)^(banco|caixa|empresa|instituto|minist[eé]rio|"
    r"tribunal|defensoria|prefeitura|universidade|"
    r"funda[çc][ãa]o|secretaria|c[aâ]mara|procuradoria)\b")


def _spans(texto: str, tipo: str) -> list[tuple[int, int]]:
    """Spans casados do tipo, deduplicados por sobreposição —
    o mesmo trecho achado por rótulo e por formato conta 1x."""
    achados: list[tuple[int, int]] = []
    for rx in _RE[tipo]:
        for m in rx.finditer(texto):
            g = m.group(1) if m.groups() else m.group(0)
            if g.strip() == TAG or not g.strip():
                continue
            i = m.start(1) if m.groups() else m.start()
            if tipo == "nome_contexto" and _NOME_STOP.search(g):
                continue
            if not any(a < i + len(g) and i < b
                       for a, b in achados):
                achados.append((i, i + len(g)))
    return achados


def contar_residuos(texto_saida: str) -> dict[str, int]:
    """Contagem por tipo — retorna só números, nunca valores."""
    return {k: len(_spans(texto_saida, k)) for k in _RE}


def residuo(texto_saida: str) -> tuple[int, dict[str, int]]:
    """(total, por_tipo) — a API do gate."""
    c = contar_residuos(texto_saida)
    return sum(c.values()), c


def residuo_bytes(dados: bytes) -> tuple[int, dict[str, int]]:
    """Extrai texto da saída (PDF via pypdf, senão utf-8) e
    conta. Sem texto extraível -> (0, zeros): o gate de
    legibilidade em `medir` já tratou esse caso antes."""
    try:
        if dados.startswith(b"%PDF"):
            from app.motor_langchain import extrair_texto
            return residuo(extrair_texto(dados))
        return residuo(dados.decode("utf-8", errors="replace"))
    except Exception:
        return 0, {k: 0 for k in _RE}
