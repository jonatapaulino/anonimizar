"""P9 — poda de fronteira dos spans LLM (gate NER exact >= 0.85).

Diagnostico read-only sobre corpus/ajuste: para cada span aceito
gravado em saidas_ollama_cascata/*.spans.json, classifica contra o
gabarito e extrai os fragmentos arrastados nas bordas (prefixo/
sufixo fora do gold casado por overlap+tipo), para definir as
regras de poda. Nao roda motor, nao escreve nada.

Uso: python spikes/p9_poda_fronteira.py
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                     / "scripts"))
from poda_fronteira import podar                       # noqa: E402

MAPA = {"NOME": "PESSOA", "CNJ": "PROCESSO_CNJ"}

# ---- camada deterministica (mesma de scripts/eval_cascata.py) ----
PRESERVADOS = [
    r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}",      # CNJ
    r"(?:de\s+)?R\$\s?[\d.]+,\d{2}",              # VALOR
]
DET = [
    ("EMAIL", r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),
    ("CPF", r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
    ("ENDERECO", r"(?:Rua|Avenida|Av\.|Travessa|Passagem|Alameda"
                 r"|Estrada|Rodovia)[^.\n]*?CEP\s*\d{5}-?\d{3}"),
    ("RG", r"\b(?:SSP-)?[A-Z]{2}\s+\d{2}\.\d{3}\.\d{3}(?:-[0-9Xx])?"
           r"\b|\b\d{2}\.\d{3}\.\d{3}(?:-[0-9Xx])?\b"),
    ("TELEFONE", r"\(\d{2}\)\s?\d{4,5}-?\d{4}\b"
                 r"|\b\d{2}\s?\d{4,5}-?\d{4}\b"
                 r"|\b\d{2}\d{4,5}\d{4}\b"),
]

# ---- avaliacao pre-registrada (mesma definicao de metricas) ----
def spans_det(txt):
    prot = [(m.start(), m.end()) for p in PRESERVADOS
            for m in re.finditer(p, txt)]
    out = []
    for tipo, pat in DET:
        for m in re.finditer(pat, txt):
            i, f = m.span()
            if any(i < pf and pi < f for pi, pf in prot):
                continue
            out.append((i, f, f"det:{tipo}"))
    return out, prot


def mesclar(cands, prot):
    cands = sorted(cands, key=lambda s: (s[0], -(s[1] - s[0])))
    ok = []
    for i, f, o in cands:
        if any(i < pf and pi < f for pi, pf in prot):
            continue
        if any(i < of and oi < f for oi, of, _ in ok):
            continue
        ok.append((i, f, o))
    return ok


def maptipo(t):
    return MAPA.get(t, t)


def ov(a0, a1, b0, b1):
    return a0 < b1 and b0 < a1


def medir(docs):
    tp_e = fp_e = fn_e = tp_o = fp_o = fn_o = 0
    por_tipo = {}
    for nome, gab, txt, preds in docs:
        golds = [(e["inicio"], e["fim"], maptipo(e["tipo"]))
                 for e in gab["entidades"] if not e["preservar"]]
        matched = set()
        for pi, pf, pt in preds:
            hit = next((k for k, (gi, gf, gt) in enumerate(golds)
                        if k not in matched and pi == gi
                        and pf == gf and pt == gt), None)
            if hit is None:
                fp_e += 1
            else:
                tp_e += 1
                matched.add(hit)
        fn_e += len(golds) - len(matched)
        matched = set()
        for pi, pf, pt in preds:
            hit = next((k for k, (gi, gf, gt) in enumerate(golds)
                        if k not in matched and pt == gt
                        and ov(pi, pf, gi, gf)), None)
            if hit is None:
                fp_o += 1
            else:
                tp_o += 1
                matched.add(hit)
        fn_o += len(golds) - len(matched)
        for (gi, gf, gt) in golds:
            st = por_tipo.setdefault(gt, [0, 0, 0])
            st[0 if any(ov(pi, pf, gi, gf) and pt == gt
                        for pi, pf, pt in preds) else 2] += 1
        for (pi, pf, pt) in preds:
            st = por_tipo.setdefault(pt, [0, 0, 0])
            if not any(ov(pi, pf, gi, gf) and pt == gt
                       for gi, gf, gt in golds):
                st[1] += 1
    def prf(tp, fp, fn):
        p = tp / (tp + fp) if tp + fp else 0
        r = tp / (tp + fn) if tp + fn else 0
        return p, r, (2 * p * r / (p + r) if p + r else 0)
    return prf(tp_e, fp_e, fn_e), prf(tp_o, fp_o, fn_o), \
        por_tipo, (tp_e, fp_e, fn_e)


def replay(com_poda=True):
    pasta = Path("corpus/ajuste")
    out = pasta / "saidas_ollama_cascata"
    docs = []
    for g in sorted(pasta.glob("doc-*.json")):
        gab = json.loads(g.read_text(encoding="utf-8"))
        txt = (pasta / gab["documento"]).read_text("utf-8")
        pred = json.loads(
            (out / f"{g.stem}.spans.json").read_text("utf-8"))
        det, prot = spans_det(txt)
        cands = list(det)
        for p in pred:
            i, f, o = p["ini"], p["fim"], p["fonte"]
            if o.startswith("det"):
                continue                    # det vem regenerado
            tipo = o.split(":")[-1]
            if com_poda:
                for pi, pf in podar(txt, i, f, tipo):
                    cands.append((pi, pf, o))
            else:
                cands.append((i, f, o))
        spans = mesclar(cands, prot)
        preds = [(i, f, maptipo(o.split(":")[-1]))
                 for i, f, o in spans]
        docs.append((g.stem, gab, txt, preds))
    return docs


def diag():
    pasta = Path("corpus/ajuste")
    out = pasta / "saidas_ollama_cascata"

    frag_ini, frag_fim, frag_int = Counter(), Counter(), Counter()
    bloated = []
    stats = Counter()
    exemplos = []

    for g in sorted(pasta.glob("doc-*.json")):
        gab = json.loads(g.read_text(encoding="utf-8"))
        txt = (pasta / gab["documento"]).read_text("utf-8")
        pred = json.loads(
            (out / f"{g.stem}.spans.json").read_text("utf-8"))

        golds = [(e["inicio"], e["fim"], maptipo(e["tipo"]))
                 for e in gab["entidades"] if not e["preservar"]]
        allgold = [(e["inicio"], e["fim"], maptipo(e["tipo"]))
                   for e in gab["entidades"]]
        preds = [(p["ini"], p["fim"], maptipo(p["fonte"].split(":")[-1]),
                  p["fonte"]) for p in pred]

        matched = set()
        for pi, pf, pt, fonte in preds:
            best, bj = -1, None
            for k, (gi, gf, gt) in enumerate(golds):
                if k in matched or pt != gt or not ov(pi, pf, gi, gf):
                    continue
                inter = min(pf, gf) - max(pi, gi)
                if inter > best:
                    best, bj = inter, k
            if bj is None:
                if any(ov(pi, pf, gi, gf)
                       for gi, gf, _ in allgold):
                    stats["fp_tipo_ou_preservado"] += 1
                else:
                    stats["fp_puro"] += 1
                exemplos.append(("FP-SEM-OURO", fonte,
                                 txt[max(0, pi - 20):pf + 20]))
                continue
            matched.add(bj)
            gi, gf, gt = golds[bj]
            if pi == gi and pf == gf:
                stats["tp_exact"] += 1
                continue
            stats["fp_borda"] += 1
            pre = txt[pi:gi] if pi < gi else ""
            pos = txt[gf:pf] if pf > gf else ""
            # pred dentro do gold: falta cobrir miolo (corte)
            if pi > gi:
                frag_int[txt[gi:pi].strip()[:40] or "<vazio>"] += 1
            if pf < gf:
                frag_int[txt[pf:gf].strip()[:40] or "<vazio>"] += 1
            if pre.strip():
                frag_ini[pre.strip()[:40]] += 1
            if pos.strip():
                frag_fim[pos.strip()[:40]] += 1
            tam = pf - pi
            if tam > 100 or (pre and pos) or len(pre) > 15 \
                    or len(pos) > 15:
                bloated.append((g.stem, fonte, tam,
                                txt[pi:pf][:110]))
            if len(exemplos) < 60:
                exemplos.append(("BORDA", fonte,
                                 f"[{pre!r}] OURO[{txt[gi:gf][:40]!r}]"
                                 f" [{pos!r}]"))
        stats["fn"] += len(golds) - len(matched)

    print("== diagnostico ajuste (30 docs, spans gravados) ==")
    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")

    print("\n== prefixos arrastados (top 30) ==")
    for frag, n in frag_ini.most_common(30):
        print(f"  {n:>3}x {frag!r}")

    print("\n== sufixos arrastados (top 30) ==")
    for frag, n in frag_fim.most_common(30):
        print(f"  {n:>3}x {frag!r}")

    print("\n== miolo gold deixado de fora (cortes) ==")
    for frag, n in frag_int.most_common(20):
        print(f"  {n:>3}x {frag!r}")

    print(f"\n== spans grandes/suspeitos: {len(bloated)} ==")
    for nome, fonte, tam, trecho in bloated[:25]:
        print(f"  {nome} {fonte} {tam}c: {trecho!r}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "diag":
        diag()
        return
    print("== replay offline — ajuste (spans gravados + det regen.) ==")
    for rotulo, flag in (("sem poda (baseline)", False),
                         ("com poda", True)):
        docs = replay(com_poda=flag)
        (pe, re_, fe), (po, ro, fo), por_tipo, (tp, fp, fn) = \
            medir(docs)
        print(f"\n[{rotulo}]")
        print(f"  exact : TP={tp} FP={fp} FN={fn} "
              f"P={pe:.3f} R={re_:.3f} F1={fe:.3f}")
        print(f"  overlap: P={po:.3f} R={ro:.3f} F1={fo:.3f}")
        print("  por tipo (overlap):")
        for t in sorted(por_tipo):
            t_, f_, n_ = por_tipo[t]
            p = t_ / (t_ + f_) if t_ + f_ else 0
            r = t_ / (t_ + n_) if t_ + n_ else 0
            f1 = 2 * p * r / (p + r) if p + r else 0
            print(f"    {t:<10} TP={t_:<3} FP={f_:<3} FN={n_:<3} "
                  f"F1={f1:.2f}")


if __name__ == "__main__":
    main()
