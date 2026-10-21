"""Metricas pre-registradas (docs/metricas.md) sobre a cascata.

NER: span-level P/R/F1, dois niveis — exact ((ini,fim,tipo)==gold)
e overlap (>=1 char, tipo igual). Gold = entidades com
preservar=false (PRIV). Pred = spans aceitos gravados pelo
eval_cascata (*.spans.json, campo fonte 'det:TIPO'/'llmN:TIPO').

Mapa de tipos -> tagset metricas.md: NOME->PESSOA, CNJ->PROCESSO_CNJ;
demais identicos. Tipo declarado CEP/PROCESSO do LLM mantido como esta.

Excesso sobre nao-entidade: chars do span fora de qualquer gold
span (alvo OU preservado). 'rotulo' = chars em tokens que batem
padrao de rotulo conhecido; 'conteudo' = o restante.

reident = entidades PRIV com texto claro na saida / total PRIV.
Gate: <=0.05 (metricas.md sec.4). Entidade = cada ocorrencia
plantada (corpus nao tem ent_id — ver declaracao de interpretacao).

Uso: python scripts/metricas_prereg.py [base] [particao] [dir_saidas]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TAG = "[ANONIMIZADO_LGPD]"
MAPA = {"NOME": "PESSOA", "CNJ": "PROCESSO_CNJ"}
ROTULOS = re.compile(
    r"^(?i:rg|ssp|cpf|endereco|endereço|telefone|tel|fone|celular|"
    r"contato|residente|domicilio|domicílio|sede|reside|portador|"
    r"inscrito|e-mail|email|ao|sob|n\.|no|da|de|a|o|e|sob o n\.|"
    r":|,|\(|\)|-|\s)+$")


def maptipo(t):
    return MAPA.get(t, t)


def ov(a0, a1, b0, b1):
    return a0 < b1 and b0 < a1


def main(base, part, dir_out):
    pasta = base / part
    docs = []
    for g in sorted(pasta.glob("doc-*.json")):
        gab = json.loads(g.read_text("utf-8"))
        txt = (pasta / gab["documento"]).read_text("utf-8")
        pred = json.loads((pasta / dir_out / f"{g.stem}.spans.json")
                          .read_text("utf-8"))
        saida = (pasta / dir_out / f"{g.stem}.txt").read_text("utf-8")
        docs.append((g.stem, gab, txt, pred, saida))

    tp_e = fp_e = fn_e = tp_o = fp_o = fn_o = 0
    por_tipo = {}
    prose_docs = []
    leaks = []
    n_priv = 0
    for nome, gab, txt, pred, saida in docs:
        golds = [(e["inicio"], e["fim"], maptipo(e["tipo"]))
                 for e in gab["entidades"] if not e["preservar"]]
        n_priv += len(golds)
        preds = [(p["ini"], p["fim"], maptipo(p["fonte"].split(":")[-1]))
                 for p in pred]
        matched_g = set()
        # exact
        for pi, pf, pt in preds:
            hit = next((k for k, (gi, gf, gt) in enumerate(golds)
                        if k not in matched_g and pi == gi and pf == gf
                        and pt == gt), None)
            if hit is None:
                fp_e += 1
            else:
                tp_e += 1
                matched_g.add(hit)
        fn_e += len(golds) - len(matched_g)
        # overlap
        matched_g = set()
        for pi, pf, pt in preds:
            hit = next((k for k, (gi, gf, gt) in enumerate(golds)
                        if k not in matched_g and pt == gt
                        and ov(pi, pf, gi, gf)), None)
            if hit is None:
                fp_o += 1
            else:
                tp_o += 1
                matched_g.add(hit)
        fn_o += len(golds) - len(matched_g)
        # por tipo (overlap)
        for (gi, gf, gt) in golds:
            st = por_tipo.setdefault(gt, [0, 0, 0])
            if any(ov(pi, pf, gi, gf) and pt == gt
                   for pi, pf, pt in preds):
                st[0] += 1
            else:
                st[2] += 1
        for (pi, pf, pt) in preds:
            st = por_tipo.setdefault(pt, [0, 0, 0])
            if not any(ov(pi, pf, gi, gf) and pt == gt
                       for gi, gf, gt in golds):
                st[1] += 1
        # prosa comida: chars do pred fora de qualquer gold span
        allgold = [(e["inicio"], e["fim"])
                   for e in gab["entidades"]]
        rot = cont = 0
        for pi, pf, pt in preds:
            for j in range(pi, pf):
                if any(ov(j, j + 1, gi, gf) for gi, gf in allgold):
                    continue
                (rot := rot + 1) if False else None
            # fragmentos contiguos fora de gold
            j = pi
            while j < pf:
                if any(ov(j, j + 1, gi, gf) for gi, gf in allgold):
                    j += 1
                    continue
                k = j
                while k < pf and not any(
                        ov(k, k + 1, gi, gf) for gi, gf in allgold):
                    k += 1
                frag = txt[j:k]
                if ROTULOS.match(frag.strip()) or \
                        not frag.strip():
                    rot += len(frag)
                else:
                    cont += len(frag)
                j = k
        if rot or cont:
            prose_docs.append((nome, rot, cont))
        # reident
        for e in gab["entidades"]:
            if not e["preservar"] and e["texto"] in saida:
                leaks.append((nome, e["tipo"], e["texto"]))

    p_e = tp_e / (tp_e + fp_e) if tp_e + fp_e else 0
    r_e = tp_e / (tp_e + fn_e) if tp_e + fn_e else 0
    p_o = tp_o / (tp_o + fp_o) if tp_o + fp_o else 0
    r_o = tp_o / (tp_o + fn_o) if tp_o + fn_o else 0
    f1_e = 2 * p_e * r_e / (p_e + r_e) if p_e + r_e else 0
    f1_o = 2 * p_o * r_o / (p_o + r_o) if p_o + r_o else 0

    print(f"== NER pre-registrado — {part} (cascata) ==")
    print(f"exact : TP={tp_e} FP={fp_e} FN={fn_e} "
          f"P={p_e:.3f} R={r_e:.3f} F1={f1_e:.3f}")
    print(f"overlap: TP={tp_o} FP={fp_o} FN={fn_o} "
          f"P={p_o:.3f} R={r_o:.3f} F1={f1_o:.3f}")
    print(f"gates: F1_micro_exact>=0.85 -> "
          f"{'PASS' if f1_e >= 0.85 else 'FAIL'}")
    print("\npor tipo (overlap, tipo igual):")
    for t in sorted(por_tipo):
        tp_, fp_, fn_ = por_tipo[t]
        p = tp_ / (tp_ + fp_) if tp_ + fp_ else 0
        r = tp_ / (tp_ + fn_) if tp_ + fn_ else 0
        f1 = 2 * p * r / (p + r) if p + r else 0
        print(f"  {t:<12} TP={tp_:<3} FP={fp_:<3} FN={fn_:<3} "
              f"P={p:.2f} R={r:.2f} F1={f1:.2f} "
              f"{'(>=0.70 OK)' if f1 >= 0.7 else '(<0.70 FALHA)'}")

    print("\n== excesso sobre nao-entidade (chars de prosa) ==")
    print("  doc: rotulo conteudo")
    tot_r = tot_c = 0
    for nome, rot, cont in prose_docs:
        tot_r += rot
        tot_c += cont
        if cont:
            print(f"  {nome}: {rot:>4} {cont:>5}  "
                  f"*conteudo fora de rotulo*")
    print(f"  TOTAL: rotulo={tot_r}c conteudo={tot_c}c "
          f"em {len(prose_docs)}/{len(docs)} docs")

    print("\n== reidentificacao ==")
    print(f"entidades PRIV com texto claro: {len(leaks)}/{n_priv} "
          f"= {len(leaks)/n_priv:.4f}  (gate <=0.05)")
    por_doc = {}
    for n, t, x in leaks:
        por_doc.setdefault(n, []).append((t, x))
    for n in sorted(por_doc):
        for t, x in por_doc[n]:
            print(f"  {n} {t}: {x!r}")


if __name__ == "__main__":
    b = Path(sys.argv[1] if len(sys.argv) > 1 else "corpus")
    part = sys.argv[2] if len(sys.argv) > 2 else "teste"
    dout = sys.argv[3] if len(sys.argv) > 3 else \
        f"saidas_ollama_cascata_{part}"
    main(b, part, dout)
