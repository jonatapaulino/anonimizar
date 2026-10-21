"""Analise de metricas — particao ajuste, pos-execucao v0.

1. Registra sha256 do SYSTEM_PROMPT como v0 (NAO altera o prompt).
2. Remocao por fracao de caracteres por entidade:
     intacta (0%), parcial (0<f<100%), total (100%).
   Fracao removida = 1 - maior substring contigua sobrevivente /
   len(entidade)  (SequenceMatcher.find_longest_match).
3. Compara MotorOllama-v0 (saidas_ollama/ gravadas) vs DemoMotorIA
   (regex, IA_ENGINE=demo) lado a lado.

Uso: python scripts/analisar_metricas.py [base_corpus]
"""
from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.motor_langchain import SYSTEM_PROMPT, TAG   # noqa: E402
from app.worker import DemoMotorIA                   # noqa: E402


def frac_removida(ent: str, saida: str) -> float:
    """1.0 = nada do texto exato sobrou; 0.0 = intacto."""
    if ent in saida:
        return 0.0
    m = difflib.SequenceMatcher(None, ent, saida
                                ).find_longest_match()
    return 1.0 - m.size / max(len(ent), 1)


def faixa(f: float) -> str:
    """intacta: texto exato presente. parcial: fragmento contiguo
    sobrevivente >=50% da entidade (vazamento parcial real).
    total: ausente, com apenas fragmentos coincidentes <50%
    (na pratica <=0.41 neste corpus — ruido de texto adjacente)."""
    if f <= 0.0:
        return "intacta"
    if f <= 0.5:
        return "parcial"
    return "total"


def medir(docs, saidas: dict[str, str]):
    """docs: [(nome, gabarito, texto)]; saidas: nome -> resposta."""
    por_tipo, erros = {}, []
    for nome, gab, txt in docs:
        resp = saidas[nome]
        miss, exc = [], []
        for e in gab["entidades"]:
            f = frac_removida(e["texto"], resp)
            st = por_tipo.setdefault(e["tipo"], {
                "alvo": {"intacta": 0, "parcial": 0, "total": 0},
                "pres": {"intacta": 0, "parcial": 0, "total": 0}})
            bucket = "pres" if e["preservar"] else "alvo"
            st[bucket][faixa(f)] += 1
            if e["preservar"]:
                if f > 0:
                    exc.append((e["texto"], f))
            elif f < 1.0:
                miss.append((e["texto"], f))
        if miss or exc:
            erros.append({"doc": nome, "miss": miss, "exc": exc,
                          "tags": resp.count(TAG)})
    return por_tipo, erros


def tabela(titulo, por_tipo):
    print(f"\n== {titulo} ==")
    print(f"  {'tipo':<12} {'alvo':>5} {'tot':>4} {'par':>4} "
          f"{'int':>4} {'recall':>7}   {'pres':>4} {'exc_tot':>7}"
          f" {'exc_par':>7}")
    for t in sorted(por_tipo):
        a, p = por_tipo[t]["alvo"], por_tipo[t]["pres"]
        n_alvo = a["total"] + a["parcial"] + a["intacta"]
        n_pres = p["total"] + p["parcial"] + p["intacta"]
        rec = a["total"] / n_alvo if n_alvo else float("nan")
        et = p["total"] / n_pres if n_pres else float("nan")
        ep = p["parcial"] / n_pres if n_pres else float("nan")
        print(f"  {t:<12} {n_alvo:>5} {a['total']:>4} "
              f"{a['parcial']:>4} {a['intacta']:>4} "
              f"{rec:>6.0%}   {n_pres:>4} "
              f"{et:>6.0%} {ep:>6.0%}")


async def main(base: Path):
    pasta = base / "ajuste"
    docs = []
    for g in sorted(pasta.glob("doc-*.json")):
        gab = json.loads(g.read_text(encoding="utf-8"))
        txt = (pasta / gab["documento"]).read_text(encoding="utf-8")
        docs.append((g.stem, gab, txt))

    # 1. v0 — hash do prompt vigente (nao altera)
    h = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()
    reg = Path(base) / "prompt_versoes.json"
    versoes = json.loads(reg.read_text("utf-8")) \
        if reg.exists() else {}
    versoes["v0"] = {"sha256": h, "chars": len(SYSTEM_PROMPT),
                     "fonte": "app/motor_langchain.py:SYSTEM_PROMPT"}
    reg.write_text(json.dumps(versoes, ensure_ascii=False,
                              indent=2), "utf-8")
    print(f"SYSTEM_PROMPT v0  sha256={h}  chars={len(SYSTEM_PROMPT)}"
          f"\n  cita 'endereços'? "
          f"{'endereços' in SYSTEM_PROMPT or 'endere' in SYSTEM_PROMPT}")

    # 2. metricas — LLM v0 (saidas gravadas) e demo (regex)
    saidas_llm = {n: (pasta / "saidas_ollama" / f"{n}.txt")
                  .read_text(encoding="utf-8")
                  for n, _, _ in docs}
    demo = DemoMotorIA(atraso=0)
    saidas_demo = {}
    for n, _, txt in docs:
        out = await demo.anonimizar(txt.encode("utf-8"))
        saidas_demo[n] = out.decode("utf-8")

    t_llm, e_llm = medir(docs, saidas_llm)
    t_demo, e_demo = medir(docs, saidas_demo)
    tabela("LLM qwen2.5:7b — prompt v0", t_llm)
    tabela("DemoMotorIA (regex, IA_ENGINE=demo)", t_demo)

    # 3. inspecao dos ENDERECO perdidos no LLM v0
    print("\n== ENDERECO nao removido totalmente (LLM v0) ==")
    for nome, gab, txt in docs:
        for e in gab["entidades"]:
            if e["tipo"] != "ENDERECO":
                continue
            resp = saidas_llm[nome]
            f = frac_removida(e["texto"], resp)
            if f >= 1.0:
                continue
            m = difflib.SequenceMatcher(
                None, e["texto"], resp).find_longest_match()
            trecho = resp[max(0, m.b - 40):m.b + m.size + 40]
            print(f"  {nome} f_removida={f:.0%} "
                  f"sobrou: {e['texto'][m.a:m.a+m.size]!r}")
            print(f"      ctx saida: {trecho!r}")

    print("\n== DemoMotorIA — erros por documento ==")
    for e in e_demo:
        print(f"  {e['doc']}: miss={len(e['miss'])} "
              f"exc={len(e['exc'])} tags={e['tags']}")


if __name__ == "__main__":
    b = Path(sys.argv[1] if len(sys.argv) > 1 else "corpus")
    asyncio.run(main(b))
