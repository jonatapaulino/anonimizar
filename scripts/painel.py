"""Painel de metricas por conjunto de saidas — particao ajuste.

Categorias por entidade-ALVO (preservar=false):
  intacta          — texto exato presente na saida
  parcial          — ausente, mas fragmento contiguo >=50% sobrevive
  total            — ausente, so fragmentos coincidentes <50%
  residuo_prefixo  — flag independente: entidade ausente, mas um
                     prefixo estruturado (>=2 chars, fim em borda
                     de token) sobrevive IMEDIATAMENTE antes de
                     uma tag [ANONIMIZADO*] — ex.: 'PA', 'SSP-PA',
                     '(94)'. Nao exclui as faixas acima: uma
                     entidade 'total' pode ter residuo.

Tambem: excesso em preservadas, fidelidade (reconstrucao por
substituicao de tags) e varredura de tags fora do padrao.

Uso: python scripts/painel.py [base] [rotulo:dir ...]
   ex.: python scripts/painel.py corpus v0:saidas_ollama \
        v1:saidas_ollama_v1 14b:saidas_ollama_14b_v0
"""
from __future__ import annotations

import difflib
import json
import re
import sys
import unicodedata
from pathlib import Path

TAG = "[ANONIMIZADO_LGPD]"
TAG_RE = r"\[ANONIMIZAD[A-Z_]*\]"
TOKEN = re.compile(r"\S+|\s+")


def frac_removida(ent, saida):
    if ent in saida:
        return 0.0
    m = difflib.SequenceMatcher(None, ent, saida).find_longest_match()
    return 1.0 - m.size / max(len(ent), 1)


def faixa(f):
    return "intacta" if f <= 0.0 else \
           "parcial" if f <= 0.5 else "total"


def residuo_prefixo(ent, saida):
    """Tamanho do maior prefixo da entidade (borda de token,
    >=2 chars nao-espaco) sobrevivendo imediatamente antes de
    uma tag. 0 = sem residuo."""
    best = 0
    for m in re.finditer(r"\S+", ent):
        pref = ent[:m.end()]
        if len(pref.strip()) < 2:
            continue
        if re.search(re.escape(pref) + r"\s*,?\s*" + TAG_RE,
                     saida):
            best = len(pref)
    return best


def sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def alnum(s):
    return re.sub(r"[^\w]", "", s)


def classif(a, b):
    if a.isspace() and b.isspace():
        return "espaco"
    if sem_acento(a) == sem_acento(b):
        return "acento"
    if alnum(a) == alnum(b):
        return "pontuacao"
    return "trocada"


def fidelidade(txt, resp, ents):
    """Reconstroi trocando tags pelas entidades removidas (ordem).
    Retorna (igual_ao_txt, contagem_de_tipos, tag_mismatch)."""
    removidas = [e["texto"] for e in sorted(
        ents, key=lambda e: e["inicio"])
        if not e["preservar"] and e["texto"] not in resp]
    partes = re.split(TAG_RE, resp)
    rec, it = [], iter(removidas)
    for i, p in enumerate(partes):
        rec.append(p)
        if i < len(partes) - 1:
            rec.append(next(it, ""))
    recon = "".join(rec)
    mm = len(partes) - 1 - len(removidas)
    tipos = {}
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, TOKEN.findall(txt), TOKEN.findall(recon)
    ).get_opcodes():
        if op == "equal":
            continue
        la = TOKEN.findall(txt)[i1:i2]
        lb = TOKEN.findall(recon)[j1:j2]
        for k in range(max(len(la), len(lb))):
            a = la[k] if k < len(la) else None
            b = lb[k] if k < len(lb) else None
            if a is None:
                t = "espaco" if b.isspace() else "inserida"
            elif b is None:
                t = "espaco" if a.isspace() else "removida"
            else:
                t = classif(a, b)
            tipos[t] = tipos.get(t, 0) + 1
    return recon == txt, tipos, mm


def medir(docs, saidas):
    por_tipo, residuos, fid, tags_bad = {}, [], {}, []
    n_div = 0
    for nome, gab in docs:
        resp = saidas[nome]
        for e in gab["entidades"]:
            f = frac_removida(e["texto"], resp)
            r = 0 if e["preservar"] else \
                residuo_prefixo(e["texto"], resp)
            st = por_tipo.setdefault(e["tipo"], {
                "alvo": dict.fromkeys(
                    ("intacta", "parcial", "total"), 0),
                "pres": dict.fromkeys(
                    ("intacta", "parcial", "total"), 0),
                "residuo": 0})
            b = "pres" if e["preservar"] else "alvo"
            st[b][faixa(f)] += 1
            if r:
                st["residuo"] += 1
                residuos.append((nome, e["tipo"], r,
                                 e["texto"]))
        igual, tipos, _mm = fidelidade(
            (docs_txt[nome]), resp, gab["entidades"])
        if not igual:
            n_div += 1
        for t, c in tipos.items():
            fid[t] = fid.get(t, 0) + c
        for t in re.findall(r"\[[^\]\n]{1,40}\]", resp):
            if t != TAG:
                tags_bad.append((nome, t))
    return por_tipo, residuos, n_div, fid, tags_bad


docs_txt = {}


def main(base: Path, pares, particao: str = "ajuste"):
    pasta = base / particao
    docs = []
    for g in sorted(pasta.glob("doc-*.json")):
        gab = json.loads(g.read_text(encoding="utf-8"))
        docs.append((g.stem, gab))
        docs_txt[g.stem] = (
            pasta / gab["documento"]).read_text("utf-8")

    resultados = {}
    for rotulo, d in pares:
        dir_s = pasta / d
        if not dir_s.exists():
            print(f"[{rotulo}] {d} ausente — pulado")
            continue
        saidas = {n: (dir_s / f"{n}.txt").read_text("utf-8")
                  for n, _ in docs}
        resultados[rotulo] = medir(docs, saidas)

    tipos = sorted({t for r in resultados.values()
                    for t in r[0]})
    print(f"{'tipo':<12}", end="")
    for rotulo, _ in pares:
        if rotulo in resultados:
            print(f" | {rotulo:^22}", end="")
    print()
    print(f"{'':12}", end="")
    for rotulo, _ in pares:
        if rotulo in resultados:
            print(f" | {'recall':>9} {'exc':>5} {'resid':>5}",
                  end="")
    print()
    for t in tipos:
        print(f"{t:<12}", end="")
        for rotulo, _ in pares:
            if rotulo not in resultados:
                continue
            st = resultados[rotulo][0][t]
            a, p = st["alvo"], st["pres"]
            n = sum(a.values())
            np_ = sum(p.values())
            exc = p["total"] + p["parcial"]
            rec = f"{a['total']}/{n} {a['total']/n:.0%}" \
                if n else "-"
            exc_s = f"{exc}/{np_}" if np_ else "-"
            print(f" | {rec:>9} {exc_s:>5} {st['residuo']:>5}",
                  end="")
        print()

    for rotulo, _ in pares:
        if rotulo not in resultados:
            continue
        _, residuos, n_div, fid, tags_bad = resultados[rotulo]
        print(f"\n--- {rotulo}: detalhe ---")
        print(f"  fidelidade: {n_div}/30 docs divergentes  {fid}")
        print(f"  tags fora do padrao: {len(tags_bad)} "
              f"{sorted(set(tags_bad))[:6]}")
        print(f"  residuos de prefixo ({len(residuos)}):")
        for n, t, r, txt in residuos:
            print(f"    {n} {t:<9} residuo={r:>2}c {txt!r}")


if __name__ == "__main__":
    b = Path(sys.argv[1] if len(sys.argv) > 1 else "corpus")
    part = "ajuste"
    rest = sys.argv[2:]
    if rest and "=" in rest[0]:
        part = rest[0].split("=", 1)[1]
        rest = rest[1:]
    pares = [a.split(":", 1) for a in rest] or \
        [("v0", "saidas_ollama"), ("v1", "saidas_ollama_v1")]
    main(b, pares, part)
