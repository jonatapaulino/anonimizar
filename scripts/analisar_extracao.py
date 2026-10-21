"""Análise do corpus sintético — sem motor, só extração.

1. Sobreposição ajuste×teste: entidades cujo TEXTO EXATO aparece
   nas duas partições (vazamento de gabarito entre tuning e
   avaliação). Esperado: nenhuma sobreposição em entidades
   geradas aleatoriamente; vocabulário fechado (CIDADE/ORGAO/
   CARGO/INSTITUICAO e nomes) repete por construção.

2. Sobrevivência pós-extração: para cada .pdf, extrai o texto
   via app.motor_langchain.extrair_texto (pypdf, sem LLM) e marca
   quais entidades plantadas sobrevivem como substring exata.
   Grava corpus/<particao>/sobrevivencia.json por documento.

Uso:  python scripts/analisar_extracao.py [corpus]  # default corpus/
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.motor_langchain import extrair_texto   # noqa: E402


def _docs(pasta: Path):
    out = []
    for j in sorted(pasta.glob("doc-*.json")):
        gab = json.loads(j.read_text(encoding="utf-8"))
        txt = (pasta / gab["documento"]).read_text(encoding="utf-8")
        pdf = (pasta / gab["pdf"]).read_bytes()
        out.append((gab["documento"], txt, pdf,
                    gab["entidades"]))
    return out


def sobreposicao(ajuste, teste):
    """texto exato compartilhado entre partições -> lista de
    (doc_teste, tipo, texto)."""
    texto_para_docs_a = {}
    for doc, _, _, ents in ajuste:
        for e in ents:
            texto_para_docs_a.setdefault(e["texto"], set()).add(doc)
    compartilhadas = []
    for doc, _, _, ents in teste:
        for e in ents:
            if e["texto"] in texto_para_docs_a:
                compartilhadas.append({
                    "doc_teste": doc, "tipo": e["tipo"],
                    "texto": e["texto"],
                    "docs_ajuste": sorted(
                        texto_para_docs_a[e["texto"]])})
    return compartilhadas


def sobrevivencia(docs, pasta: Path):
    """Quais entidades plantadas saem inteiras do PDF extraído."""
    por_doc = {}
    dist = {}
    for doc, _txt, pdf, ents in docs:
        try:
            extraido = extrair_texto(pdf)
        except Exception as exc:
            por_doc[doc] = {"erro": str(exc), "entidades": []}
            continue
        linhas = []
        for e in ents:
            sob = e["texto"] in extraido
            linhas.append({"texto": e["texto"], "tipo": e["tipo"],
                           "preservar": e["preservar"],
                           "sobreviveu": sob})
            d = dist.setdefault(e["tipo"], [0, 0])
            d[1] += 1
            d[0] += sob
        por_doc[doc] = {"entidades": linhas}
    (pasta / "sobrevivencia.json").write_text(
        json.dumps(por_doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return dist


def main():
    base = Path(sys.argv[1] if len(sys.argv) > 1 else "corpus")
    part = {p: _docs(base / p) for p in ("ajuste", "teste")}

    print("== sobreposicao de texto exato (ajuste e teste) ==")
    comp = sobreposicao(part["ajuste"], part["teste"])
    por_tipo = {}
    for c in comp:
        por_tipo.setdefault(c["tipo"], []).append(c)
    if not comp:
        print("  nenhuma")
    for tipo, itens in sorted(por_tipo.items()):
        docs_t = sorted({i["doc_teste"] for i in itens})
        textos = sorted({i["texto"] for i in itens})
        print(f"  {tipo}: {len(textos)} texto(s) em "
              f"{len(docs_t)} doc(s) de teste")
        for t in textos[:6]:
            print(f"    \"{t}\"")
        if len(textos) > 6:
            print(f"    … +{len(textos) - 6}")

    print("\n== sobrevivência pós-extração (substring exata) ==")
    for p, docs in part.items():
        dist = sobrevivencia(docs, base / p)
        tot_s = tot_n = 0
        print(f"[{p}]")
        for tipo, (s, n) in sorted(dist.items()):
            tot_s += s
            tot_n += n
            print(f"    {tipo:<12} {s:>3}/{n:<3}  {100*s/n:5.1f}%")
        print(f"    {'TOTAL':<12} {tot_s:>3}/{tot_n:<3}  "
              f"{100*tot_s/tot_n:5.1f}%")


if __name__ == "__main__":
    main()
