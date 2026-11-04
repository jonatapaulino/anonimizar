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
from eval_cascata import (mesclar, spans_det, spans_res,   # noqa: E402
                         TAGSET_ALVO)

MAPA = {"NOME": "PESSOA", "CNJ": "PROCESSO_CNJ"}


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


def replay(part="ajuste", tag="poda", com_poda=True):
    """Replay fiel sobre .cands.json (pos-poda pre-merge) quando
    existe; fallback .spans.json (aceitos, aproximado). det e res
    sao regenerados deterministicamente."""
    pasta = Path("corpus") / part
    out = pasta / f"saidas_ollama_cascata_{tag}" \
        if tag else pasta / "saidas_ollama_cascata"
    docs = []
    for g in sorted(pasta.glob("doc-*.json")):
        gab = json.loads(g.read_text(encoding="utf-8"))
        txt = (pasta / gab["documento"]).read_text("utf-8")
        fc = out / f"{g.stem}.cands.json"
        fs = out / f"{g.stem}.spans.json"
        pred = json.loads((fc if fc.exists() else fs)
                          .read_text("utf-8"))
        det, prot = spans_det(txt)
        cands = det + spans_res(txt)
        for p in pred:
            i, f, o = p["ini"], p["fim"], p["fonte"]
            if o.startswith("det"):
                continue                    # det vem regenerado
            tipo = o.split(":")[-1]
            if tipo not in TAGSET_ALVO:
                continue                    # tipo morto (CEP...)
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
    part = sys.argv[1] if len(sys.argv) > 1 else "ajuste"
    tag = sys.argv[2] if len(sys.argv) > 2 else "poda"
    print(f"== replay offline — {part}/{tag} "
          f"(cands gravados + det/res regen.) ==")
    for rotulo, flag in (("sem poda (baseline)", False),
                         ("com poda+cpf+res+tagset", True)):
        docs = replay(part, tag, com_poda=flag)
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
