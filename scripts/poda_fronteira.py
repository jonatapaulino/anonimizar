"""Poda deterministica de fronteira para spans do LLM (cascata).

Motivacao (medido, ajuste): o grosso do FP exact vem de bordas
frouxas — o LLM arrasta rotulos ('RG', 'CPF', 'inscrito no',
'sob o n.'), conectivos e ate entidades vizinhas para dentro do
span ('Nome, CPF 000...'). A poda encolhe/corta o span por regras
de texto deterministicas, CEGAS ao gabarito:

- tipos com formato fechado (CPF/RG/TELEFONE/EMAIL): encolhe ao(s)
  match(es) do nucleo interno — pode dividir um span em varios;
- ENDERECO: ancora esquerda no ultimo logradouro antes do CEP e
  direita no fim do CEP; sem CEP, so trim lexico;
- NOME: corta no primeiro rotulo/conectivo ('Nome, CPF ...' ->
  'Nome') e faz trim lexico;
- demais tipos: trim lexico nas bordas.

Aplicada aos candidatos llm* ANTES do mesclar: libera spans det e
candidatos que seriam suprimidos pela sobreposicao com o span
inchado. Det nao passa pela poda (ja e exato por construcao).
"""
from __future__ import annotations

import re

NUCLEO = {
    "EMAIL": re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),
    "CPF": re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
    "RG": re.compile(
        r"\b(?:SSP-)?[A-Z]{2}\s+\d{2}\.\d{3}\.\d{3}(?:-[0-9Xx])?\b"
        r"|\b\d{2}\.\d{3}\.\d{3}(?:-[0-9Xx])?\b"),
    "TELEFONE": re.compile(
        r"\(\d{2}\)\s?\d{4,5}-?\d{4}\b"
        r"|\b\d{2}\s?\d{4,5}-?\d{4}\b"
        r"|\b\d{2}\d{4,5}\d{4}\b"),
}
CEP = re.compile(r"CEP\s*\d{5}-?\d{3}")
LOGRADOURO = re.compile(
    r"(?:Rua|Avenida|Av\.|Travessa|Passagem|Alameda|Estrada|Rodovia)")

# rotulos, conectivos e pontuacao que nunca fazem parte do dado
LEX_BORDA = re.compile(
    r"^(?i:rg|ssp|cpf|oab|cep|endereco|endereço|telefone|tel|fone|"
    r"celular|contato|residente|domicilio|domicílio|sede|reside|"
    r"portador(?:\(a\))?|inscrit[oa](?:\(a\))?|e-?mail|"
    r"sob|no|na|do|da|de|o|a|e|n\.|nº|ao|com|para|por|em|"
    r"sob\s+o\s+n\.|sob\s+o|"
    r"[.,;:()\[\]\-–—]+)$")
CORTE_NOME = re.compile(
    r"(?i)(?:,\s*)?\b(?:cpf|rg|oab|ssp|inscrit[oa]|portador|"
    r"telefone|tel|fone|celular|e-?mail|endere[cç]o|residente|"
    r"domic[ií]lio|sob\s+o\s+n\.?|cep)\b")


def _trim_borda(txt, i, f):
    """Corta tokens de borda do lexico, a esquerda e a direita."""
    while i < f:
        m = re.match(r"\S+", txt[i:f])
        if not m or not LEX_BORDA.match(m.group(0)):
            break
        i += m.end()
        while i < f and txt[i] == " ":
            i += 1
    while f > i:
        m = re.search(r"\S+\s*$", txt[i:f])
        if not m or not LEX_BORDA.match(m.group(0).strip()):
            break
        f -= len(m.group(0))
    return i, f


def podar(txt, i, f, tipo):
    """Poda deterministica das bordas do span (i,f) de `tipo`.

    Retorna lista de (ini,fim): vazia = span descartado; >1 = span
    dividido em varios nucleos. Cega ao gabarito."""
    if tipo in NUCLEO:
        hits = [m.span() for m in NUCLEO[tipo].finditer(txt[i:f])]
        if hits:
            return [(i + a, i + b) for a, b in hits]
    elif tipo == "ENDERECO":
        cep = CEP.search(txt, i, f)
        if cep:
            log = None
            for m in LOGRADOURO.finditer(txt, i, cep.end()):
                log = m
            if log:
                a, b = _trim_borda(txt, log.start(), cep.end())
                return [(a, b)] if b > a else []
    elif tipo in ("NOME", "PESSOA"):
        m = CORTE_NOME.search(txt, i, f)
        if m:
            f = m.start()
    i, f = _trim_borda(txt, i, f)
    return [(i, f)] if f > i else []


__all__ = ["podar"]
