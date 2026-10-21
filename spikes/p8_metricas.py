"""P8 — Harness de métricas sobre corpus_v0 (proxy N2, docs/metricas.md).

Avalia, contra o gabarito automático:
  A) validadores regex determinísticos  -> P/R/F1 exact por tipo
  B) NER stock (LeNER-Br bert, sem fine-tune) -> P/R/F1 overlap em PESSOA
  C) motor de correferência do P3       -> pairwise P/R/F1, consistência,
                                         anti-merge
NÃO inclui: reidentificação (exige pipeline de saída) nem utility
(exige decisão jurídica de pseudônimos).
"""
import json, re, sys, unicodedata
from collections import Counter, defaultdict

sys.path.insert(0, "spikes")
from p3_correferencia import Engine

CORPUS = "spikes/corpus_v0.jsonl"

# ---------- A) validadores regex ----------
RX = {
 "CPF":          r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b",
 "OAB":          r"(?<=\bOAB/PA nº )\d{5}\b",
 "PROCESSO_CNJ": r"\b\d{7}-\d{2}\.\d{4}\.8\.\d{2}\.\d{4}\b",
 "CEP":          r"\b\d{5}-\d{3}\b",
 "TELEFONE":     r"\(\d{2}\) 9\d{4}-\d{4}",
 "EMAIL":        r"\b[\w.]+@[\w.]+\.\w+\b",
 "DATA_NASC":    r"\b\d{1,2} de março de \d{4}\b",
 "VALOR":        r"\b\d{1,3}\.\d{3},\d{2}\b",
}

def detect_regex(text):
    out = []
    for typ, pat in RX.items():
        for m in re.finditer(pat, text):
            out.append(dict(start=m.start(), end=m.end(), type=typ))
    return out

def prf(tp, fp, fn):
    p = tp/(tp+fp) if tp+fp else 0.0
    r = tp/(tp+fn) if tp+fn else 0.0
    f = 2*p*r/(p+r) if p+r else 0.0
    return p, r, f

# ---------- B) NER stock ----------
def detect_ner(text, ner):
    out = []
    # janela: texto é curto (<512 tokens típico); roda direto
    for e in ner(text):
        lab = e["entity_group"].upper()
        if "PES" in lab or "PER" in lab:
            out.append(dict(start=e["start"], end=e["end"], type="PESSOA"))
    return out

# ---------- C) correferência ----------
def aval_corref(doc):
    eng = Engine(); eng.analyze(doc["text"])
    gold = [g for g in doc["gold"] if g["type"] == "PESSOA"]
    def ent_pred(g):
        best, ov = None, 0
        for m in eng.mentions:
            o = max(0, min(g["end"], m.start + len(m.text)) - max(g["start"], m.start))
            if o > ov: best, ov = m.ent, o
        return best
    aligned = [(g["ent"], ent_pred(g)) for g in gold]
    # pairwise
    tp = fp = fn = 0
    for i in range(len(aligned)):
        for j in range(i+1, len(aligned)):
            g1, p1 = aligned[i]; g2, p2 = aligned[j]
            same_g = g1 == g2
            same_p = p1 is not None and p1 is p2
            if same_g and same_p: tp += 1
            elif same_p and not same_g: fp += 1
            elif same_g and not same_p: fn += 1
    # consistência por entidade gold: todas as menções na mesma predita
    grupos = defaultdict(set)
    for g, p in aligned:
        grupos[g].add(id(p) if p else f"none{g}")
    ok_cons = sum(1 for s in grupos.values() if len(s) == 1)
    return tp, fp, fn, ok_cons, len(grupos), len(gold)

# ---------- main ----------
docs = [json.loads(l) for l in open(CORPUS, encoding="utf-8")]

print("== A) VALIDADORES REGEX (exact) ==")
tot = Counter()
for typ in RX:
    tp = fp = fn = 0
    for d in docs:
        gold = [g for g in d["gold"] if g["type"] == typ]
        pred = [p for p in detect_regex(d["text"]) if p["type"] == typ]
        used = set()
        for p in pred:
            hit = [i for i, g in enumerate(gold)
                   if i not in used and g["start"] == p["start"]
                   and g["end"] == p["end"]]
            if hit: tp += 1; used.add(hit[0])
            else: fp += 1
        fn += len(gold) - len(used)
    P, R, F = prf(tp, fp, fn); tot.update(tp=tp, fp=fp, fn=fn)
    print(f"  {typ:<14} P={P:.2f} R={R:.2f} F1={F:.2f}  (tp{tp} fp{fp} fn{fn})")
P, R, F = prf(tot["tp"], tot["fp"], tot["fn"])
print(f"  {'MICRO':<14} P={P:.2f} R={R:.2f} F1={F:.2f}")

print("\n== B) NER STOCK LeNER-Br (overlap, PESSOA) ==")
try:
    from transformers import pipeline
    ner = pipeline("ner", model="pierreguillou/ner-bert-base-cased-pt-lenerbr",
                   aggregation_strategy="simple")
    STOPW0 = {"o","a","os","as","do","da","ele","ela","este","esta",
              "seu","sua","referido","referida","mencionado","sr","sra"}
    def is_name(g):
        w = g["text"].split()[0].lower()
        return g["text"][0].isupper() and w not in STOPW0
    for rotulo, filtro in [("todas-menções", lambda g: True),
                           ("só-nomes", is_name)]:
        tp = fp = fn = 0
        for d in docs:
            gold = [g for g in d["gold"]
                    if g["type"] == "PESSOA" and filtro(g)]
            pred = detect_ner(d["text"], ner)
            used_g = set()
            for p in pred:
                hit = [i for i, g in enumerate(gold)
                       if i not in used_g and
                       min(g["end"], p["end"]) - max(g["start"], p["start"]) > 0]
                if hit: tp += 1; used_g.add(hit[0])
                else: fp += 1
            fn += len(gold) - len(used_g)
        P, R, F = prf(tp, fp, fn)
        print(f"  PESSOA {rotulo:<14} P={P:.2f} R={R:.2f} F1={F:.2f}"
              f"  (tp{tp} fp{fp} fn{fn})")
    print("  'só-nomes' = menções que são nomes próprios — o subconjunto")
    print("  justo para NER; papéis/pronomes são domínio do motor simbólico")
except Exception as e:
    print(f"  NER indisponível: {e}")

print("\n== C) CORREFERÊNCIA (motor simbólico) ==")
TP = FP = FN = 0; cons_ok = cons_tot = ment = 0
for d in docs:
    tp, fp, fn, ok, totg, n = aval_corref(d)
    TP += tp; FP += fp; FN += fn; cons_ok += ok; cons_tot += totg; ment += n
P, R, F = prf(TP, FP, FN)
print(f"  pairwise  P={P:.2f} R={R:.2f} F1={F:.2f}  (tp{TP} fp{FP} fn{FN})")
print(f"  consistência/entidade: {cons_ok}/{cons_tot} = {cons_ok/cons_tot:.2f}")
print(f"  menções PESSOA alinhadas: {ment}")
json.dump(dict(regex=dict(P=P, R=R, F1=F)),
          open("spikes/p8_raw.json", "w"), indent=1)
