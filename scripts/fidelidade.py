"""Fidelidade de saida — particao ajuste.

Para cada doc: reconstrucao = saida com cada tag
[ANONIMIZADO_LGPD] substituida pelos textos originais das
entidades removidas (na ordem em que aparecem no documento).
Compara a reconstrucao com o .txt original, token a token.

Classificacao de cada diferenca:
  acento    — tokens iguais ignorando acentos
  pontuacao — iguais ignorando chars nao-alfanumericos
  espaco    — apenas whitespace difere
  removida  — palavra presente so no original
  inserida  — palavra presente so na saida
  trocada   — demais substituicoes

Tambem conta tags fora do padrao exato [ANONIMIZADO_LGPD] em
todas as saidas gravadas (v0 e v1).

Uso: python scripts/fidelidade.py [base_corpus]
"""
from __future__ import annotations

import difflib
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TAG = "[ANONIMIZADO_LGPD]"
TOKEN = re.compile(r"\S+|\s+")


def sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def alnum(s: str) -> str:
    return re.sub(r"[^\w]", "", s)


def classif(a: str, b: str) -> str:
    if a.isspace() and b.isspace():
        return "espaco"
    if sem_acento(a) == sem_acento(b):
        return "acento"
    if alnum(a) == alnum(b):
        return "pontuacao"
    return "trocada"


def fidelidade(nome, txt, resp, ents):
    removidas = [e["texto"] for e in sorted(ents,
                                           key=lambda e: e["inicio"])
                 if not e["preservar"] and e["texto"] not in resp]
    # reconstrucao: intercala partes e entidades removidas
    partes = resp.split(TAG)
    rec = []
    it = iter(removidas)
    for i, p in enumerate(partes):
        rec.append(p)
        if i < len(partes) - 1:
            rec.append(next(it, ""))
    recon = "".join(rec)
    mismatch_tags = len(partes) - 1 - len(removidas)

    tok_a = TOKEN.findall(txt)
    tok_b = TOKEN.findall(recon)
    diffs = []
    sm = difflib.SequenceMatcher(None, tok_a, tok_b)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        if op == "delete":
            for t in tok_a[i1:i2]:
                diffs.append(("espaco" if t.isspace()
                              else "removida", t, ""))
        elif op == "insert":
            for t in tok_b[j1:j2]:
                diffs.append(("espaco" if t.isspace()
                              else "inserida", "", t))
        else:  # replace
            la, lb = tok_a[i1:i2], tok_b[j1:j2]
            for k in range(max(len(la), len(lb))):
                a = la[k] if k < len(la) else None
                b = lb[k] if k < len(lb) else None
                if a is None:
                    diffs.append(("espaco" if b.isspace()
                                  else "inserida", "", b))
                elif b is None:
                    diffs.append(("espaco" if a.isspace()
                                  else "removida", a, ""))
                else:
                    diffs.append((classif(a, b), a, b))
    return recon == txt, diffs, mismatch_tags


def main(base: Path):
    pasta = base / "ajuste"
    for rotulo in ("", "_v1"):
        dir_s = pasta / f"saidas_ollama{rotulo}"
        if not dir_s.exists():
            continue
        print(f"\n===== fidelidade — saidas_ollama{rotulo or '_v0'} =====")
        n_div = 0
        tipos = {}
        for g in sorted(pasta.glob("doc-*.json")):
            gab = json.loads(g.read_text(encoding="utf-8"))
            txt = (pasta / gab["documento"]).read_text("utf-8")
            resp = (dir_s / f"{g.stem}.txt").read_text("utf-8")
            igual, diffs, mm = fidelidade(g.stem, txt, resp,
                                          gab["entidades"])
            if not igual:
                n_div += 1
                for tipo, a, b in diffs:
                    tipos[tipo] = tipos.get(tipo, 0) + 1
                print(f"  {g.stem}: divergente "
                      f"(tag_mismatch={mm:+d})")
                for tipo, a, b in diffs[:6]:
                    print(f"      {tipo:<9} {a!r} -> {b!r}")
        print(f"  docs divergentes: {n_div}/30")
        print(f"  por tipo: {tipos}")

        # tags fora do padrao
        print(f"  -- tags fora de {TAG} --")
        total_ok = total_bad = 0
        for f in sorted(dir_s.glob("*.txt")):
            conteudo = f.read_text(encoding="utf-8")
            todas = re.findall(r"\[[^\]\n]{1,40}\]", conteudo)
            ok = todas.count(TAG)
            bad = [t for t in todas if t != TAG]
            total_ok += ok
            total_bad += len(bad)
            for b in set(bad):
                print(f"    {f.stem}: {b!r} x{bad.count(b)}")
        print(f"    {TAG}={total_ok}  fora_do_padrao={total_bad}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "corpus"))
